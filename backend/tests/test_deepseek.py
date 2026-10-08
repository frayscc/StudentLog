import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.local_config import get_llm_config, update_local_config
from backend.app.main import app
from backend.app.auth import create_session
from backend.app.providers import DeepSeekProvider, ProviderError, get_llm_provider
from backend.app.schemas import NameCandidate


@pytest.fixture
def local_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    monkeypatch.setattr(settings, 'llm_provider', 'mock')
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    update_local_config({'asr_provider': 'paraformer'})
    return tmp_path


def authenticated_client():
    # Use a signed session directly so these settings tests never open a database.
    from fastapi import Response
    response = Response()
    create_session(response, 'teacher')
    client = TestClient(app)
    cookie = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    client.cookies.set('studentlog_session', cookie)
    return client


def test_llm_settings_preserve_clear_and_never_return_key(local_settings):
    unauthorized = TestClient(app)
    assert unauthorized.get('/api/settings/llm').status_code == 401
    client = authenticated_client()
    assert client.put('/api/settings/llm', json={'provider': 'deepseek'}).status_code == 400
    key = 'sk-test-local-private'
    saved = client.put('/api/settings/llm', json={'provider': 'deepseek', 'api_key': key})
    assert saved.status_code == 200
    assert saved.json() == {'provider': 'deepseek', 'api_key_configured': True}
    assert key not in client.get('/api/settings/llm').text
    assert get_llm_provider().name == 'deepseek'
    assert get_llm_config()['api_key'] == key
    assert client.put('/api/settings/llm', json={'provider': 'mock', 'api_key': ''}).status_code == 200
    assert get_llm_config()['api_key'] == key
    assert client.put('/api/settings/llm', json={'provider': 'mock', 'clear_api_key': True}).json()['api_key_configured'] is False
    assert get_llm_provider().name == 'mock'
    config = json.loads((local_settings / 'config.json').read_text(encoding='utf-8'))
    assert config['asr_provider'] == 'paraformer'


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def candidate():
    return NameCandidate(student_id='10000000-0000-0000-0000-000000000001', student_no='01', name='陈颢霖', confidence=1, reason='完全匹配')


def test_deepseek_masks_request_and_restores_names(local_settings, monkeypatch):
    update_local_config({'llm_provider': 'deepseek', 'deepseek_api_key': 'sk-test'})
    student = candidate()

    def handler(request):
        body = json.loads(request.content)
        assert student.name not in body['messages'][1]['content']
        assert student.student_id in body['messages'][1]['content']
        assert request.headers['authorization'] == 'Bearer sk-test'
        content = {'student_ids': [student.student_id], 'occurred_at': '2026-10-08T10:00:00',
                   'event_description': f'{student.student_id}完成作业。', 'teacher_action': f'提醒{student.student_id}。',
                   'tags': [student.student_id]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}}]})

    mock_http(monkeypatch, handler)
    result = asyncio.run(DeepSeekProvider().structure('陈颢霖完成作业。', [student], [student.student_id]))
    assert result.event_description == '陈颢霖完成作业。'
    assert result.teacher_action == '提醒陈颢霖。'
    assert result.tags == ['陈颢霖']
    assert result.student_ids == [student.student_id]


@pytest.mark.parametrize('failure', ['timeout', '401', '429', '500', 'json', 'shape', 'foreign_student'])
@pytest.mark.parametrize('operation', ['structure', 'summarize'])
def test_deepseek_failures_are_actionable_without_leaking_content(local_settings, monkeypatch, failure, operation):
    private = 'sk-private-error-sentinel'
    update_local_config({'deepseek_api_key': private})

    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout(private, request=request)
        if failure.isdigit():
            return httpx.Response(int(failure), text=private)
        if failure == 'json':
            return httpx.Response(200, text=private)
        if failure == 'shape':
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'event_description': private})}}]})
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'student_ids': ['not-a-local-student'], 'occurred_at': '2026-10-08T10:00:00', 'event_description': private,
        })}}]})

    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        provider = DeepSeekProvider()
        task = (provider.structure('原始记录', [candidate()], [candidate().student_id])
                if operation == 'structure' else provider.summarize([]))
        asyncio.run(task)
    assert private not in str(error.value)
    assert any(action in str(error.value) for action in ('重试', '检查', '拒绝'))


def test_summary_uses_validated_json_and_dynamic_key(local_settings, monkeypatch):
    update_local_config({'deepseek_api_key': 'sk-new-key'})
    facts = [{'occurred_at': '2026-10-08', 'category': '作业', 'event_description': '完成物理作业。'}]

    def handler(request):
        assert request.headers['authorization'] == 'Bearer sk-new-key'
        body = json.loads(request.content)
        assert json.loads(body['messages'][1]['content']) == {'events': facts}
        sections = {field: [] for field in ('learning_records', 'discipline_records', 'teacher_communication',
                                          'family_communication', 'actions_taken', 'follow_up_items')}
        sections['learning_records'] = ['完成物理作业。']
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(sections)}}]})

    mock_http(monkeypatch, handler)
    assert asyncio.run(DeepSeekProvider().summarize(facts)).learning_records == ['完成物理作业。']


def test_malformed_signed_cookie_returns_401():
    from backend.app.auth import _signature
    client = TestClient(app)
    body = 'teacher:not-an-expiry:nonce'
    client.cookies.set('studentlog_session', f'{body}:{_signature(body)}')
    assert client.get('/api/auth/me').status_code == 401
