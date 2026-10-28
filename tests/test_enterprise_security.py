from fastapi.testclient import TestClient

from app.identity import IdentityStore
from app.main import create_app
import pytest
from app.origins import canonical_origin


@pytest.mark.parametrize('value,expected', [
    ('https://KNOWLEDGE.example.test', ('https', 'knowledge.example.test', 443)),
    ('https://knowledge.example.test:443', ('https', 'knowledge.example.test', 443)),
    ('http://localhost:18769', ('http', 'localhost', 18769)),
    ('https://knowledge.example.test:444', ('https', 'knowledge.example.test', 444)),
    ('http://localhost:0', None),
    ('https://user:secret@knowledge.example.test', None),
    ('null', None), ('http://[invalid', None),
    ('https://knowledge.example.test/path', None),
])
def test_origin_canonicalization(value, expected):
    assert canonical_origin(value) == expected


def test_configured_https_origin_rejects_same_host_http_login(tmp_path, monkeypatch):
    for key in ('RAG_BASE_URL', 'RAG_MODEL', 'RAG_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('ZHIXU_PUBLIC_URL', 'https://knowledge.example.test')
    data = tmp_path / 'data'
    password = 'Synthetic-cross-scheme-password!'
    IdentityStore(data / 'control.db').bootstrap('owner', password)
    application = create_app(db_path=data / 'knowledge.db', enterprise=True, seed_demo=False)
    with TestClient(application, base_url='https://knowledge.example.test') as client:
        response = client.post('/api/auth/login', json={'username': 'owner', 'password': password},
                               headers={'Origin': 'http://knowledge.example.test'})
        assert response.status_code == 403
        assert 'zhixu_session' not in response.headers.get('set-cookie', '')
        accepted = client.post('/api/auth/login', json={'username': 'owner', 'password': password},
                               headers={'Origin': 'https://knowledge.example.test'})
        assert accepted.status_code == 200
