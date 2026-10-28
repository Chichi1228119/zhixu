"""Single-organization HTTP authentication and workspace authorization boundary."""
import hmac
import os
from pathlib import Path
import re
import threading
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .identity import IdentityError, IdentityStore, InvalidCredentials, LastAdminError, RateLimited
from .service import KnowledgeService
from .origins import canonical_origin

COOKIE = 'zhixu_session'


class LoginBody(BaseModel):
    model_config = {'extra': 'forbid'}
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128, repr=False)


class UserBody(LoginBody):
    is_admin: bool = False


class WorkspaceBody(BaseModel):
    model_config = {'extra': 'forbid'}
    name: str = Field(min_length=1, max_length=128)


class MemberBody(BaseModel):
    model_config = {'extra': 'forbid'}
    user_id: str = Field(min_length=1, max_length=64)
    role: Literal['viewer', 'editor', 'admin']


class ActiveBody(BaseModel):
    model_config = {'extra': 'forbid'}
    active: bool


class PasswordBody(BaseModel):
    model_config = {'extra': 'forbid'}
    current_password: str = Field(min_length=1, max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)


class EnterpriseBoundary:
    def __init__(self, data_dir: Path, model_cache: Path):
        self.data_dir = data_dir
        self.model_cache = model_cache
        self.identity = IdentityStore(data_dir / 'control.db')
        if not any(user['active'] and user['is_admin'] for user in self.identity.list_users()):
            raise ValueError('企业模式须先初始化管理员：zhixu admin init --data-dir PATH（bootstrap）。')
        self._services = {}
        self._lock = threading.RLock()
        self._logins = threading.BoundedSemaphore(4)
        self.public_host = None
        self.public_origin = None
        self.secure_cookie = False
        public_url = os.getenv('ZHIXU_PUBLIC_URL', '')
        if public_url:
            try:
                url = urlsplit(public_url)
                if (url.scheme != 'https' or not url.hostname or url.username or url.password
                        or url.query or url.fragment or url.path not in {'', '/'}):
                    raise ValueError
                _ = url.port
                self.public_host = url.hostname
                self.public_origin = canonical_origin(public_url)
                if self.public_origin is None:
                    raise ValueError
                self.secure_cookie = True
            except ValueError:
                raise ValueError('ZHIXU_PUBLIC_URL 须为不含用户信息、路径和查询参数的 HTTPS 来源。') from None

    def status(self, session):
        if not session:
            return {'enabled': True, 'authenticated': False}
        user = {key: session[key] for key in ('id', 'username', 'is_admin', 'active')}
        return {'enabled': True, 'authenticated': True, 'user': user,
                'csrf_token': session['csrf_token'], 'workspaces': self.identity.workspaces_for(session['id'])}

    def authorize(self, request: Request):
        session = self.identity.resolve_session(request.cookies.get(COOKIE, ''))
        request.state.user = session
        path = request.url.path
        public = (request.method in {'GET', 'HEAD'} and (path in {'/', '/api/health', '/api/auth/status'} or path.startswith('/static/')))
        if public or path == '/api/auth/login':
            return None
        if not session:
            return JSONResponse({'detail': '请先登录，或会话已失效。'}, status_code=401)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token', '').encode('utf-8'), session['csrf_token'].encode('utf-8')):
                self.identity.audit(session['id'], 'access.denied', outcome='csrf', request_id=request.state.request_id)
                return JSONResponse({'detail': '会话校验失败，请刷新并重新登录。'}, status_code=403)
        if path.startswith(('/api/admin/', '/api/settings/', '/api/evaluation')) and not session['is_admin']:
            self.identity.audit(session['id'], 'access.denied', outcome='role', request_id=request.state.request_id)
            return JSONResponse({'detail': '此操作需要系统管理员权限。'}, status_code=403)
        workspace_path = path.startswith('/api/documents') or path in {'/api/ask', '/api/demo/restore'}
        if workspace_path:
            workspaces = self.identity.workspaces_for(session['id'])
            selected = request.headers.get('X-Workspace-ID') or (workspaces[0]['id'] if workspaces else '')
            role = self.identity.membership(session['id'], selected) if re.fullmatch('[0-9a-f]{32}', selected) else None
            if not role:
                self.identity.audit(session['id'], 'access.denied', outcome='workspace', request_id=request.state.request_id)
                return JSONResponse({'detail': '你没有该知识空间的访问权限，请联系管理员授权。'}, status_code=403)
            if request.method not in {'GET', 'HEAD'} and path != '/api/ask' and role == 'viewer':
                self.identity.audit(session['id'], 'access.denied', workspace_id=selected, outcome='role', request_id=request.state.request_id)
                return JSONResponse({'detail': '阅读者不能修改知识文档。'}, status_code=403)
            request.state.workspace_id = selected
            request.state.workspace_role = role
            request.state.knowledge_service = self.service(selected)
        return None

    def service(self, workspace_id):
        with self._lock:
            if workspace_id not in self._services:
                self._services[workspace_id] = KnowledgeService(self.data_dir / 'workspaces' / workspace_id / 'knowledge.db', model_cache=self.model_cache)
            return self._services[workspace_id]

    def audit_response(self, request, status_code):
        actions = {('POST', '/api/documents'): 'document.import', ('POST', '/api/ask'): 'question.ask',
                   ('POST', '/api/demo/restore'): 'demo.restore', ('PUT', '/api/settings/model'): 'model.update',
                   ('POST', '/api/settings/model/test'): 'model.test', ('POST', '/api/evaluation/run'): 'evaluation.run'}
        action = actions.get((request.method, request.url.path))
        if request.method == 'DELETE' and request.url.path.startswith('/api/documents/'):
            action = 'document.delete'
        user = getattr(request.state, 'user', None)
        if action and user:
            self.identity.audit(user['id'], action, workspace_id=getattr(request.state, 'workspace_id', None),
                target_id=getattr(request.state, 'audit_target', None), outcome='success' if status_code < 400 else 'failure', request_id=request.state.request_id)

    def router(self):
        router = APIRouter()

        @router.get('/api/auth/status')
        def status(request: Request):
            return self.status(getattr(request.state, 'user', None))

        @router.post('/api/auth/login')
        def login(body: LoginBody, request: Request):
            if not self._logins.acquire(blocking=False):
                raise HTTPException(429, '登录请求过多，请稍后重试。')
            try:
                try:
                    token, csrf, user = self.identity.authenticate(body.username, body.password,
                        client_key=request.client.host if request.client else 'unknown')
                except RateLimited:
                    raise HTTPException(429, '登录尝试过多，请在 15 分钟后重试。', headers={'Retry-After': '900'}) from None
                except InvalidCredentials:
                    self.identity.audit(None, 'auth.login', outcome='failure', request_id=request.state.request_id)
                    raise HTTPException(401, '账号或密码错误。') from None
            finally:
                self._logins.release()
            self.identity.logout(request.cookies.get(COOKIE, ''))
            self.identity.audit(user['id'], 'auth.login', request_id=request.state.request_id)
            response = JSONResponse(self.status({**user, 'csrf_token': csrf}))
            response.set_cookie(COOKIE, token, max_age=28800, httponly=True, secure=self.secure_cookie, samesite='strict')
            return response

        @router.post('/api/auth/logout')
        def logout(request: Request):
            self.identity.logout(request.cookies.get(COOKIE, ''))
            self.identity.audit(request.state.user['id'], 'auth.logout', request_id=request.state.request_id)
            response = JSONResponse({'ok': True})
            response.delete_cookie(COOKIE, httponly=True, secure=self.secure_cookie, samesite='strict')
            return response

        @router.post('/api/auth/password')
        def change_password(body: PasswordBody, request: Request):
            try:
                self.identity.change_password(request.state.user['id'], body.current_password, body.new_password)
            except RateLimited:
                raise HTTPException(429, '身份验证繁忙，请稍后重试。') from None
            except IdentityError:
                raise HTTPException(400, '当前密码错误，或新密码不符合要求。') from None
            self.identity.audit(request.state.user['id'], 'user.password_change', request_id=request.state.request_id)
            response = JSONResponse({'ok': True})
            response.delete_cookie(COOKIE, httponly=True, secure=self.secure_cookie, samesite='strict')
            return response

        @router.get('/api/admin/users')
        def users():
            return {'users': self.identity.list_users()}

        @router.post('/api/admin/users')
        def create_user(body: UserBody, request: Request):
            try:
                user = self.identity.create_user(body.username, body.password, is_admin=body.is_admin)
            except IdentityError as error:
                raise HTTPException(400, str(error)) from None
            self.identity.audit(request.state.user['id'], 'user.create', target_id=user['id'], request_id=request.state.request_id)
            return user

        @router.put('/api/admin/users/{user_id}/active')
        def active(user_id: str, body: ActiveBody, request: Request):
            try:
                self.identity.set_user_active(user_id, body.active)
            except LastAdminError as error:
                raise HTTPException(409, str(error)) from None
            except IdentityError as error:
                raise HTTPException(400, str(error)) from None
            self.identity.audit(request.state.user['id'], 'user.activate' if body.active else 'user.disable', target_id=user_id, request_id=request.state.request_id)
            return {'ok': True}

        @router.post('/api/admin/workspaces')
        def create_workspace(body: WorkspaceBody, request: Request):
            try:
                workspace = self.identity.create_workspace(body.name)
            except IdentityError as error:
                raise HTTPException(400, str(error)) from None
            self.identity.audit(request.state.user['id'], 'workspace.create', workspace_id=workspace['id'], request_id=request.state.request_id)
            return workspace

        @router.put('/api/admin/workspaces/{workspace_id}/members')
        def grant(workspace_id: str, body: MemberBody, request: Request):
            try:
                self.identity.grant(workspace_id, body.user_id, body.role)
            except IdentityError as error:
                raise HTTPException(400, str(error)) from None
            self.identity.audit(request.state.user['id'], 'member.grant', workspace_id=workspace_id, target_id=body.user_id, request_id=request.state.request_id)
            return {'ok': True}

        @router.delete('/api/admin/workspaces/{workspace_id}/members/{user_id}')
        def revoke(workspace_id: str, user_id: str, request: Request):
            try:
                self.identity.revoke(workspace_id, user_id)
            except IdentityError as error:
                raise HTTPException(400, str(error)) from None
            self.identity.audit(request.state.user['id'], 'member.revoke', workspace_id=workspace_id, target_id=user_id, request_id=request.state.request_id)
            return {'ok': True}

        @router.get('/api/admin/audit')
        def audit(limit: int = 50, offset: int = 0):
            if not 1 <= limit <= 200 or offset < 0 or offset > 1_000_000:
                raise HTTPException(422, '审计分页参数无效。')
            return {'events': self.identity.audit_events(limit=limit, offset=offset)}

        return router
