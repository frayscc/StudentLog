"""Test a built image with disposable bind mounts, never the teacher's data.

Run: python scripts/docker_smoke_test.py --image frayscc/studentlog:latest
Only Python's standard library and Docker Compose are needed on the host.
"""

import argparse
import io
import json
import os
import secrets
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import http.cookiejar
import zipfile
import zlib
from pathlib import Path


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def test_image():
    """Generate a valid RGB PNG without a host imaging dependency."""
    def chunk(kind, content):
        return struct.pack('!I', len(content)) + kind + content + struct.pack('!I', zlib.crc32(kind + content))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('!2I5B', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x28\x58\x4d' * 2) * 2))
            + chunk(b'IEND', b''))


class Client:
    def __init__(self, url):
        self.url = url
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

    def request(self, path, method='GET', payload=None, upload=None):
        headers = {}
        data = None
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(payload).encode()
        if upload is not None:
            filename, mime, content = upload
            boundary = secrets.token_hex(16)
            headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                    f'Content-Type: {mime}\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
        request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        with self.opener.open(request, timeout=60) as response:
            content = response.read()
            if 'application/json' in response.headers.get('Content-Type', ''):
                return json.loads(content)
            return content

    def wait(self):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if self.request('/api/health') == {'status': 'ok'}:
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        raise RuntimeError('Container did not become ready within 90 seconds')


def seed(client, credentials):
    check(client.request('/api/auth/status') == {'initialized': False}, 'Expected an empty test database')
    client.request('/api/auth/setup', 'POST', credentials)
    llm_status = client.request('/api/settings/llm', 'PUT', {
        'provider': 'mock', 'api_key': 'sk-smoke-local-only',
    })
    check(llm_status == {'provider': 'mock', 'api_key_configured': True}, 'AI settings were not saved')
    check('sk-smoke-local-only' not in json.dumps(llm_status), 'AI settings revealed the API Key')
    html = client.request('/').decode()
    check('/assets/' in html, 'Production frontend is not served')
    first = client.request('/api/students', 'POST', {'student_no': '01', 'name': '陈颢霖'})
    second = client.request('/api/students', 'POST', {'student_no': '02', 'name': '陈梓恒'})
    uploaded = client.request(f"/api/students/{first['id']}/avatar", 'POST',
                              upload=('avatar.png', 'image/png', test_image()))
    raw = '今天陈浩霖和陈子恒一起完成了物理作业。'
    structured = client.request('/api/ai/structure', 'POST', {'transcript': raw})
    ids = {first['id'], second['id']}
    check(set(structured['draft']['student_ids']) == ids, 'Resolved names did not link to both students')
    event = client.request('/api/events', 'POST', {
        **structured['draft'], 'raw_transcript': raw, 'record_method': 'voice', 'ai_processed': True,
    })
    attachment = client.request(f"/api/events/{event['id']}/attachments", 'POST',
                                upload=('proof.png', 'image/png', test_image()))
    backup = client.request('/api/backups/export')
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        members = archive.namelist()
        check({'app.db', 'metadata.json', 'config.json'}.issubset(members), 'Backup has no database, metadata or configuration')
        check(any(path.startswith('avatars/') for path in members), 'Backup has no avatar')
        check(any(path.startswith('attachments/') for path in members), 'Backup has no attachment')
    return {
        'ids': ids, 'event_id': event['id'], 'description': event['event_description'], 'raw': raw,
        'avatar_url': uploaded['avatar_url'], 'avatar': client.request(uploaded['avatar_url']),
        'attachment_url': attachment['url'], 'attachment': client.request(attachment['url']), 'backup': backup,
    }


def verify(client, credentials, state):
    check(client.request('/api/auth/status') == {'initialized': True}, 'Administrator was lost')
    client.request('/api/auth/login', 'POST', credentials)
    check(client.request('/api/settings/llm') == {'provider': 'mock', 'api_key_configured': True},
          'Saved AI settings were lost')
    event = client.request(f"/api/events/{state['event_id']}")
    check({student['id'] for student in event['students']} == state['ids'], 'Student associations were lost')
    check(event['raw_transcript'] == state['raw'], 'Original transcript was lost')
    check(event['event_description'] == state['description'], 'Confirmed event text changed')
    for student_id in state['ids']:
        timeline = client.request(f'/api/events?student_id={student_id}')
        check(any(item['id'] == state['event_id'] for item in timeline), 'Event missing from student timeline')
    check(client.request(state['avatar_url']) == state['avatar'], 'Avatar content changed')
    check(client.request(state['attachment_url']) == state['attachment'], 'Attachment content changed')
    summary = client.request(f"/api/students/{next(iter(state['ids']))}/summary", 'POST', {
        'date_from': '2000-01-01T00:00:00', 'date_to': '2100-01-01T00:00:00',
    })
    check(summary['source_event_count'] == 1, 'Summary did not read the associated event')
    check(len(client.request('/api/export/json')['events']) == 1, 'JSON export lost events')
    check('陈颢霖' in client.request('/api/export/csv').decode('utf-8-sig'), 'CSV export lost student name')


def verify_restore(client, credentials, state):
    client.request(f"/api/events/{state['event_id']}", 'DELETE')
    client.request('/api/settings/llm', 'PUT', {'provider': 'mock', 'clear_api_key': True})
    check(not client.request('/api/settings/llm')['api_key_configured'], 'Key clear did not take effect before restore')
    check(client.request('/api/events') == [], 'Delete did not take effect before restore')
    restored = client.request('/api/backups/restore', 'POST',
                              upload=('backup.zip', 'application/zip', state['backup']))
    check(restored['ok'] and restored['safety_backup'], 'Restore did not create a safety backup')
    try:
        client.request('/api/auth/me')
    except urllib.error.HTTPError as error:
        check(error.code == 401, 'Restore should invalidate the current session')
    else:
        raise RuntimeError('Restore did not clear the login session')
    verify(client, credentials, state)


def run(image):
    with tempfile.TemporaryDirectory(prefix='studentlog-smoke-') as temporary:
        root = Path(temporary)
        data = root / 'data'
        models = root / 'models'
        data.mkdir()
        models.mkdir()
        marker = models / 'persistence-marker.txt'
        marker.write_text('keep-models', encoding='utf-8')
        compose_file = root / 'compose.json'
        service = {
            'image': image, 'ports': ['127.0.0.1::8765'], 'init': True,
            'stop_grace_period': '30s',
            'environment': {'APP_SECRET': secrets.token_hex(32), 'LLM_PROVIDER': 'mock',
                            'ASR_ALLOW_MODEL_DOWNLOAD': 'false'},
            'volumes': [f'{data.as_posix()}:/app/data', f'{models.as_posix()}:/app/models'],
        }
        # On Linux, keep bind-mounted test files owned by the runner so the
        # temporary directory can be removed after the container exits.
        if hasattr(os, 'getuid'):
            service['user'] = f'{os.getuid()}:{os.getgid()}'
        compose_file.write_text(json.dumps({'services': {'app': service}}), encoding='utf-8')
        command = ['docker', 'compose', '-p', 'studentlog-smoke-' + secrets.token_hex(6), '-f', str(compose_file)]

        def compose(*args):
            return subprocess.run([*command, *args], check=True, text=True, capture_output=True).stdout.strip()

        def start(*args):
            compose('up', '-d', '--pull', 'never', *args)
            address = compose('port', 'app', '8765')
            client = Client('http://' + address)
            client.wait()
            return client

        credentials = {'username': 'smoke-teacher', 'password': secrets.token_urlsafe(24)}
        try:
            client = start()
            state = seed(client, credentials)
            verify(client, credentials, state)
            print('PASS: production frontend, first-run setup, name linking, timelines, summary and exports', flush=True)
            compose('stop')
            client = start()
            verify(client, credentials, state)
            print('PASS: stop/start preserves database, student links, avatar and attachment', flush=True)
            client = start('--force-recreate')
            verify(client, credentials, state)
            check(marker.read_text(encoding='utf-8') == 'keep-models', 'Models bind mount was overwritten')
            check(any((data / 'backups').glob('*.zip')), 'Backups were lost on container recreation')
            print('PASS: container recreation preserves both data and models bind mounts', flush=True)
            verify_restore(client, credentials, state)
            client = start('--force-recreate')
            verify(client, credentials, state)
            print('PASS: ZIP restore, safety backup, re-login and restart after restore', flush=True)
        except Exception:
            print(compose('logs', '--no-color', '--tail', '80'))
            raise
        finally:
            compose('down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='frayscc/studentlog:latest')
    run(parser.parse_args().image)
