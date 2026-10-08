"""Single-process request gate for consistent backups and exclusive restores."""

import asyncio
from contextlib import asynccontextmanager

from starlette.responses import JSONResponse


class MaintenanceTimeout(Exception):
    pass


class DataAccessGate:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = 0
        self.maintenance = False

    @asynccontextmanager
    async def enter(self, exclusive=False):
        acquired = False
        async with self.condition:
            if not self.maintenance:
                if exclusive:
                    self.maintenance = True
                    try:
                        await asyncio.wait_for(self.condition.wait_for(lambda: self.active == 0), timeout=30)
                        acquired = True
                    except asyncio.TimeoutError as exc:
                        self.maintenance = False
                        self.condition.notify_all()
                        raise MaintenanceTimeout() from exc
                    except BaseException:
                        self.maintenance = False
                        self.condition.notify_all()
                        raise
                else:
                    self.active += 1
                    acquired = True
        try:
            yield acquired
        finally:
            if acquired:
                async with self.condition:
                    if exclusive:
                        self.maintenance = False
                    else:
                        self.active -= 1
                    self.condition.notify_all()


class DataMaintenanceMiddleware:
    def __init__(self, app):
        self.app = app
        self.gate = DataAccessGate()

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or path == '/api/health' or not path.startswith(('/api/', '/files/')):
            await self.app(scope, receive, send)
            return
        exclusive = path in {'/api/backups/export', '/api/backups/restore'}
        try:
            async with self.gate.enter(exclusive) as acquired:
                if not acquired:
                    response = JSONResponse({'detail': '正在备份或恢复数据，请稍后重试'}, status_code=503, headers={'Retry-After': '3'})
                    await response(scope, receive, send)
                    return
                await self.app(scope, receive, send)
        except MaintenanceTimeout:
            response = JSONResponse({'detail': '仍有请求正在处理，尚未开始备份或恢复，请稍后重试'}, status_code=409)
            await response(scope, receive, send)
