from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.identity import IdentityStore
from app.main import create_app


PASSWORD = 'Synthetic-only-pass-2026!'


@pytest.fixture
def team(tmp_path, monkeypatch):
    for key in ('ZHIXU_PUBLIC_URL', 'RAG_BASE_URL', 'RAG_MODEL', 'RAG_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    data = tmp_path / 'data'
    identity = IdentityStore(data / 'control.db')
    admin = identity.bootstrap('admin', PASSWORD)
    editor = identity.create_user('editor', PASSWORD)
    viewer = identity.create_user('viewer', PASSWORD)
    outsider = identity.create_user('outsider', PASSWORD)
    first = identity.create_workspace('研发资料')
    second = identity.create_workspace('另一空间')
    identity.grant(first['id'], editor['id'], 'editor')
    identity.grant(first['id'], viewer['id'], 'viewer')
    identity.grant(second['id'], outsider['id'], 'editor')
    app = create_app(db_path=data / 'knowledge.db', enterprise=True, seed_demo=False)
    return app, identity, data, first, second, viewer


def login(client, username, workspace=None):
    response = client.post('/api/auth/login', json={'username': username, 'password': PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers['X-CSRF-Token'] = body['csrf_token']
    if workspace:
        client.headers['X-Workspace-ID'] = workspace['id']
    return body


def import_rule(client):
    response = client.post('/api/documents', files={'file': ('工程.txt', '唯一验收代号为 SILVER-816，归档周期为45天。'.encode())})
    assert response.status_code == 200, response.text
    return response.json()


def test_anonymous_has_no_knowledge_or_machine_details(team):
    app, *_ = team
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/auth/status').json()['authenticated'] is False
        health = client.get('/api/health').json()
        assert health['status'] == 'ok'
        assert 'data_location' not in health and 'process_id' not in health
        for path in ('/api/documents', '/api/settings/model', '/api/evaluation', '/openapi.json'):
            assert client.get(path).status_code == 401


def test_login_cookie_csrf_logout_and_revocation(team):
    app, *_ = team
    with TestClient(app) as client:
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': PASSWORD})
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie
        assert PASSWORD not in response.text
        assert client.post('/api/demo/restore').status_code == 403
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/documents').status_code == 401


def test_viewer_cannot_mutate_or_use_global_admin_endpoints(team):
    app, _, _, first, _, _ = team
    with TestClient(app) as editor:
        login(editor, 'editor', first)
        document = import_rule(editor)
    with TestClient(app) as viewer:
        login(viewer, 'viewer', first)
        assert len(viewer.get('/api/documents').json()['documents']) == 1
        assert viewer.get('/api/documents/' + document['id']).status_code == 200
        result = viewer.post('/api/ask', json={'question': '唯一验收代号是什么？'}).json()
        assert 'SILVER-816' in result['answer']
        assert viewer.post('/api/documents', files={'file': ('x.txt', b'test')}).status_code == 403
        assert viewer.delete('/api/documents/' + document['id']).status_code == 403
        assert viewer.post('/api/demo/restore').status_code == 403
        for path in ('/api/admin/users', '/api/admin/audit', '/api/settings/model', '/api/evaluation'):
            assert viewer.get(path).status_code == 403


def test_cross_workspace_ids_never_expose_sources(team):
    app, _, _, first, second, _ = team
    with TestClient(app) as editor:
        login(editor, 'editor', first)
        document = import_rule(editor)
        editor.headers['X-Workspace-ID'] = second['id']
        assert editor.get('/api/documents').status_code == 403
        editor.headers['X-Workspace-ID'] = '../../escape'
        assert editor.get('/api/documents').status_code == 403
    with TestClient(app) as outsider:
        login(outsider, 'outsider', second)
        assert outsider.get('/api/documents').json()['documents'] == []
        assert outsider.get('/api/documents/' + document['id']).status_code == 404
        assert outsider.delete('/api/documents/' + document['id']).status_code == 404
        body = outsider.post('/api/ask', json={'question': '唯一验收代号是什么？', 'document_ids': [document['id']]}).json()
        assert not body['sources'] and 'SILVER-816' not in body['answer']


def test_admin_can_manage_members_and_audit_excludes_content(team):
    app, _, _, first, second, viewer = team
    with TestClient(app) as admin:
        login(admin, 'admin', first)
        created = admin.post('/api/admin/users', json={'username': 'reader-two', 'password': PASSWORD, 'is_admin': False})
        assert created.status_code == 200
        assert 'hash' not in created.text and PASSWORD not in created.text
        assert admin.put(f'/api/admin/workspaces/{second["id"]}/members', json={'user_id': viewer['id'], 'role': 'viewer'}).status_code == 200
        assert admin.put(f'/api/admin/workspaces/{second["id"]}/members', json={'user_id': viewer['id'], 'role': 'superuser'}).status_code == 422
        document = import_rule(admin)
        answer_response = admin.post('/api/ask', json={'question': '唯一验收代号是什么？'})
        response = admin.get('/api/admin/audit')
        assert response.status_code == 200
        assert 'document.import' in response.text and 'question.ask' in response.text
        assert 'SILVER-816' not in response.text and PASSWORD not in response.text
        assert document['id'] in response.text
        assert answer_response.headers['X-Request-ID'] in response.text


def test_disabled_account_loses_existing_session(team):
    app, identity, _, first, _, viewer = team
    with TestClient(app) as client:
        login(client, 'viewer', first)
        identity.set_user_active(viewer['id'], False)
        assert client.get('/api/documents').status_code == 401


def test_revoking_membership_blocks_existing_session_and_scope(team):
    app, _, _, first, _, viewer = team
    with TestClient(app) as reader, TestClient(app) as admin:
        login(reader, 'viewer', first)
        login(admin, 'admin', first)
        assert reader.get('/api/documents').status_code == 200
        assert admin.delete(f'/api/admin/workspaces/{first["id"]}/members/{viewer["id"]}').status_code == 200
        assert reader.get('/api/documents').status_code == 403
        assert reader.get('/api/auth/status').json()['workspaces'] == []


def test_password_change_checks_current_password_and_revokes_sessions(team):
    app, *_ = team
    with TestClient(app) as client:
        login(client, 'admin')
        body = {'current_password': 'wrong-password', 'new_password': 'Synthetic-new-password!'}
        assert client.post('/api/auth/password', json=body).status_code == 400
        body['current_password'] = PASSWORD
        assert client.post('/api/auth/password', json=body).status_code == 200
        assert client.get('/api/admin/users').status_code == 401
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'Synthetic-new-password!'}).status_code == 200


def test_enterprise_mode_never_migrates_personal_documents(team):
    _, _, data, first, *_ = team
    from app.service import KnowledgeService
    old = KnowledgeService(data / 'knowledge.db')
    old.import_document('private.txt', '旧个人资料不可默认共享。'.encode())
    with TestClient(create_app(db_path=data / 'knowledge.db', enterprise=True)) as client:
        login(client, 'admin', first)
        assert client.get('/api/documents').json()['documents'] == []
    assert len(old.documents()) == 1


def test_enterprise_requires_explicit_bootstrap(tmp_path):
    with pytest.raises(ValueError, match='初始化|bootstrap'):
        create_app(db_path=tmp_path / 'data' / 'knowledge.db', enterprise=True)


def test_configured_https_origin_enables_secure_cookie(team, monkeypatch):
    _, _, data, *_ = team
    monkeypatch.setenv('ZHIXU_PUBLIC_URL', 'https://knowledge.example.com')
    app = create_app(db_path=data / 'knowledge.db', enterprise=True)
    with TestClient(app, base_url='https://knowledge.example.com') as client:
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': PASSWORD}, headers={'Origin': 'https://knowledge.example.com'})
        assert response.status_code == 200
        assert 'secure' in response.headers['set-cookie'].lower()
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': PASSWORD}, headers={'Origin': 'https://evil.example'}).status_code == 403
