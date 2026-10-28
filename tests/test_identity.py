import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import re
import sqlite3
import threading

from argon2 import PasswordHasher
import pytest

from app.identity import IdentityError, IdentityStore, InvalidCredentials, LastAdminError, RateLimited


PASSWORD = 'unique-test-password-2026'


@pytest.fixture
def store(tmp_path):
    return IdentityStore(tmp_path / 'identity.db')


def test_bootstrap_creates_only_first_admin_and_hides_password_hash(store):
    user = store.bootstrap('First.Admin', PASSWORD)
    assert user['username'] == 'first.admin'
    assert user['is_admin'] is True and user['active'] is True
    assert re.fullmatch(r'[0-9a-f]{32}', user['id'])
    assert set(user) == {'id', 'username', 'is_admin', 'active', 'created_at'}
    with pytest.raises(IdentityError):
        store.bootstrap('second.admin', PASSWORD)
    assert store.list_users() == [user]


@pytest.mark.parametrize('username', ['ab', 'a' * 65, 'space name', '用户名', 'Kelvin', "bad';--", '../user'])
def test_invalid_usernames_are_rejected(store, username):
    with pytest.raises(IdentityError):
        store.create_user(username, PASSWORD)
    assert store.list_users() == []


@pytest.mark.parametrize('password', ['short', 'x' * 129, '\ud800' * 12])
def test_password_character_and_utf8_limits(store, password):
    with pytest.raises(IdentityError):
        store.create_user('valid.user', password)
    assert store.list_users() == []


def test_unicode_passwords_and_casefold_unique_usernames(store):
    password = '可靠的中文密码与随机字符123'
    user = store.create_user('Case.User', password)
    with pytest.raises(IdentityError):
        store.create_user('CASE.USER', password)
    _, _, authenticated = store.authenticate('CASE.USER', password)
    assert authenticated == user


def test_real_argon2id_hash_and_only_session_digest_are_stored(store):
    user = store.bootstrap('administrator', PASSWORD)
    token, csrf, public = store.authenticate('administrator', PASSWORD)
    assert len(base64.urlsafe_b64decode(token + '=')) == 32
    assert len(base64.urlsafe_b64decode(csrf + '=')) == 32
    assert public == user
    with sqlite3.connect(store.path) as connection:
        digest = connection.execute('SELECT password_hash FROM users').fetchone()[0]
        session = connection.execute('SELECT token_hash, csrf_token FROM sessions').fetchone()
    assert digest.startswith('$argon2id$') and PasswordHasher().verify(digest, PASSWORD)
    assert session == (hashlib.sha256(token.encode()).hexdigest(), csrf)
    assert token != csrf
    persisted = b''.join(path.read_bytes() for path in store.path.parent.glob('identity.db*') if path.is_file())
    assert PASSWORD.encode() not in persisted and token.encode() not in persisted
    for user in store.list_users():
        assert 'password' not in user and 'password_hash' not in user


def test_session_resolution_expiry_and_logout_are_fixed_lifetime(tmp_path, monkeypatch):
    import app.identity as module
    now = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: now[0])
    store = IdentityStore(tmp_path / 'identity.db', session_seconds=5)
    user = store.bootstrap('administrator', PASSWORD)
    token, csrf, _ = store.authenticate('administrator', PASSWORD)
    session = store.resolve_session(token)
    assert session == dict(user, csrf_token=csrf, expires_at=1005)
    assert store.resolve_session('unknown') is None
    assert store.resolve_session(None) is None
    now[0] = 1004
    assert store.resolve_session(token)
    now[0] = 1005
    assert store.resolve_session(token) is None
    token, _, _ = store.authenticate('administrator', PASSWORD)
    store.logout(token)
    assert store.resolve_session(token) is None
    store.logout('unknown')


def test_disabled_user_cannot_authenticate_and_all_prior_sessions_are_revoked(store):
    user = store.create_user('ordinary.user', PASSWORD)
    token, _, _ = store.authenticate('ordinary.user', PASSWORD)
    store.set_user_active(user['id'], False)
    assert store.resolve_session(token) is None
    with pytest.raises(InvalidCredentials) as disabled:
        store.authenticate('ordinary.user', PASSWORD)
    with pytest.raises(InvalidCredentials) as missing:
        store.authenticate('missing.user', PASSWORD)
    with pytest.raises(InvalidCredentials) as wrong:
        store.authenticate('ordinary.user', 'wrong-password')
    assert str(disabled.value) == str(missing.value) == str(wrong.value)
    store.set_user_active(user['id'], True)
    assert store.resolve_session(token) is None
    assert store.authenticate('ordinary.user', PASSWORD)[2]['active'] is True


def test_last_active_admin_cannot_be_disabled_and_failed_update_preserves_session(store):
    admin = store.bootstrap('administrator', PASSWORD)
    token, _, _ = store.authenticate('administrator', PASSWORD)
    with pytest.raises(LastAdminError):
        store.set_user_active(admin['id'], False)
    assert store.resolve_session(token)
    assert store.list_users()[0]['active'] is True


def test_last_admin_protection_is_atomic_across_connections(tmp_path):
    first_store = IdentityStore(tmp_path / 'identity.db')
    first = first_store.bootstrap('first.admin', PASSWORD)
    second = first_store.create_user('second.admin', PASSWORD, is_admin=True)
    second_store = IdentityStore(tmp_path / 'identity.db')
    barrier = threading.Barrier(2)

    def disable(arguments):
        instance, user = arguments
        barrier.wait()
        try:
            instance.set_user_active(user['id'], False)
            return 'disabled'
        except LastAdminError:
            return 'protected'

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(disable, [(first_store, first), (second_store, second)]))
    assert sorted(results) == ['disabled', 'protected']
    assert sum(user['active'] and user['is_admin'] for user in first_store.list_users()) == 1


def test_bootstrap_race_only_creates_one_account(tmp_path):
    instances = [IdentityStore(tmp_path / 'identity.db'), IdentityStore(tmp_path / 'identity.db')]
    barrier = threading.Barrier(2)

    def bootstrap(index):
        barrier.wait()
        try:
            return instances[index].bootstrap(f'admin{index}', PASSWORD)
        except IdentityError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(bootstrap, [0, 1]))
    assert sum(user is not None for user in results) == 1
    assert len(instances[0].list_users()) == 1


def test_five_failures_lock_sixth_attempt_and_persist_across_instances(store):
    store.create_user('test.user', PASSWORD)
    for _ in range(5):
        with pytest.raises(InvalidCredentials):
            store.authenticate('TEST.USER', 'incorrect-password', client_key='client-a')
    another = IdentityStore(store.path)
    with pytest.raises(RateLimited):
        another.authenticate('test.user', PASSWORD, client_key='client-a')
    assert another.authenticate('test.user', PASSWORD, client_key='client-b')[2]['username'] == 'test.user'
    with pytest.raises(RateLimited):
        another.authenticate('test.user', PASSWORD, client_key='client-a')


def test_sliding_failure_window_retains_recent_failures(tmp_path, monkeypatch):
    import app.identity as module
    now = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: now[0])
    store = IdentityStore(tmp_path / 'identity.db')
    store.create_user('test.user', PASSWORD)
    for timestamp in [1000, 1100, 1200, 1300, 1400, 1901]:
        now[0] = timestamp
        with pytest.raises(InvalidCredentials):
            store.authenticate('test.user', 'incorrect-password')
    now[0] = 1902
    with pytest.raises(RateLimited):
        store.authenticate('test.user', PASSWORD)
    now[0] = 2802
    assert store.authenticate('test.user', PASSWORD)[2]['username'] == 'test.user'


def test_success_clears_only_its_failure_bucket(store):
    store.create_user('test.user', PASSWORD)
    for _ in range(4):
        with pytest.raises(InvalidCredentials):
            store.authenticate('test.user', 'incorrect-password', client_key='first')
    store.authenticate('test.user', PASSWORD, client_key='first')
    for _ in range(5):
        with pytest.raises(InvalidCredentials):
            store.authenticate('test.user', 'incorrect-password', client_key='first')
    assert store.authenticate('test.user', PASSWORD, client_key='second')[2]['username'] == 'test.user'


def test_missing_account_still_verifies_dummy_hash(store, monkeypatch):
    original = PasswordHasher.verify
    verified = []

    def track(self, digest, password):
        verified.append(digest)
        return original(self, digest, password)

    monkeypatch.setattr(PasswordHasher, 'verify', track)
    with pytest.raises(InvalidCredentials):
        store.authenticate('missing.user', PASSWORD)
    assert len(verified) == 1 and verified[0].startswith('$argon2id$')


def test_argon_concurrency_overload_is_rate_limited(store, monkeypatch):
    import app.identity as module
    monkeypatch.setattr(module, '_ARGON2_SLOTS', threading.BoundedSemaphore(0))
    with pytest.raises(RateLimited):
        store.authenticate('missing.user', PASSWORD)


def test_workspace_access_and_grant_changes_are_immediate(store):
    admin = store.bootstrap('administrator', PASSWORD)
    user = store.create_user('ordinary.user', PASSWORD)
    workspace = store.create_workspace('  研究空间  ')
    another = store.create_workspace('另一空间')
    assert workspace['name'] == '研究空间'
    assert re.fullmatch(r'[0-9a-f]{32}', workspace['id'])
    assert set(workspace) == {'id', 'name', 'created_at'}
    assert store.membership(admin['id'], workspace['id']) == 'admin'
    assert {row['id'] for row in store.workspaces_for(admin['id'])} == {workspace['id'], another['id']}
    assert all(row['role'] == 'admin' for row in store.workspaces_for(admin['id']))
    assert store.membership(admin['id'], 'missing') is None
    assert store.workspaces_for(user['id']) == []
    for role in ['viewer', 'editor', 'admin']:
        store.grant(workspace['id'], user['id'], role)
        assert store.membership(user['id'], workspace['id']) == role
        assert store.workspaces_for(user['id']) == [dict(workspace, role=role)]
    assert not next(item for item in store.list_users() if item['id'] == user['id'])['is_admin']
    store.revoke(workspace['id'], user['id'])
    assert store.membership(user['id'], workspace['id']) is None
    assert store.workspaces_for(user['id']) == []
    store.revoke(workspace['id'], user['id'])
    store.revoke(workspace['id'], admin['id'])
    assert store.membership(admin['id'], workspace['id']) == 'admin'


@pytest.mark.parametrize('role', ['owner', 'ADMIN', '', {'role': 'admin'}, ['viewer']])
def test_invalid_roles_are_rejected_without_grants(store, role):
    user = store.create_user('ordinary.user', PASSWORD)
    workspace = store.create_workspace('space')
    with pytest.raises(IdentityError):
        store.grant(workspace['id'], user['id'], role)
    assert store.membership(user['id'], workspace['id']) is None


def test_memberships_require_existing_ids_and_disabled_users_have_no_access(store):
    user = store.create_user('ordinary.user', PASSWORD)
    workspace = store.create_workspace('space')
    with pytest.raises(IdentityError):
        store.grant('missing', user['id'], 'viewer')
    with pytest.raises(IdentityError):
        store.grant(workspace['id'], 'missing', 'viewer')
    store.grant(workspace['id'], user['id'], 'editor')
    store.set_user_active(user['id'], False)
    assert store.membership(user['id'], workspace['id']) is None
    assert store.workspaces_for(user['id']) == []
    assert store.workspaces_for('missing') == []


def test_parameterized_queries_preserve_schema(store):
    user = store.create_user('ordinary.user', PASSWORD)
    workspace = store.create_workspace("space'; DROP TABLE users;--")
    with pytest.raises(InvalidCredentials):
        store.authenticate("' OR 1=1;--", PASSWORD)
    with pytest.raises(IdentityError):
        store.grant(workspace['id'], "' OR 1=1;--", 'admin')
    assert store.list_users() == [user]
    assert store.membership(user['id'], workspace['id']) is None


def test_audit_is_bounded_metadata_and_paginated(store):
    user = store.bootstrap('administrator', PASSWORD)
    workspace = store.create_workspace('space')
    store.audit(user['id'], 'document.import', workspace_id=workspace['id'], target_id='a' * 32)
    store.audit(None, 'session.login', outcome='denied')
    events = store.audit_events(limit=1)
    assert len(events) == 1 and events[0]['outcome'] == 'denied'
    assert events[0]['actor_id'] is None
    older = store.audit_events(limit=1, offset=1)[0]
    assert older['actor_id'] == user['id'] and older['target_id'] == 'a' * 32
    assert set(older) == {'id', 'created_at', 'actor_id', 'action', 'workspace_id', 'target_id', 'outcome', 'request_id'}
    assert older['request_id'] is None
    for kwargs in [{'action': {'password': PASSWORD}}, {'action': 'a' * 65},
                   {'action': 'document.import', 'target_id': 't' * 129},
                   {'action': 'document.import', 'outcome': 'o' * 33}]:
        with pytest.raises(IdentityError):
            store.audit(user['id'], **kwargs)
    assert len(store.audit_events()) == 2
    with pytest.raises(IdentityError):
        store.audit_events(limit=1001)
    with pytest.raises(IdentityError):
        store.audit_events(offset=-1)


def test_sqlite_connection_has_wal_foreign_keys_and_busy_timeout(store):
    with store._connect() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert connection.execute('PRAGMA busy_timeout').fetchone()[0] >= 5000


@pytest.mark.skipif(os.name == 'nt', reason='Windows uses the parent directory ACL instead of POSIX mode bits.')
def test_private_database_and_directory_permissions(store):
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.path.parent.stat().st_mode & 0o777 == 0o700


def test_reset_password_revokes_all_sessions_and_only_new_password_authenticates(store):
    user = store.create_user('reset.user', PASSWORD)
    first, _, _ = store.authenticate('reset.user', PASSWORD)
    second, _, _ = store.authenticate('reset.user', PASSWORD)
    replacement = 'new-secret-password-2026'
    assert store.reset_password(user['id'], replacement) is None
    assert store.resolve_session(first) is None and store.resolve_session(second) is None
    with pytest.raises(InvalidCredentials):
        store.authenticate('reset.user', PASSWORD)
    assert store.authenticate('reset.user', replacement)[2] == user


def test_password_reset_validation_and_unknown_user_do_not_revoke_session(store):
    user = store.create_user('reset.user', PASSWORD)
    token, _, _ = store.authenticate('reset.user', PASSWORD)
    with pytest.raises(IdentityError):
        store.reset_password(user['id'], 'short')
    assert store.resolve_session(token)
    with pytest.raises(IdentityError):
        store.reset_password('missing', 'new-secret-password-2026')


def test_change_password_requires_current_password_and_revokes_every_session(store):
    user = store.create_user('change.user', PASSWORD)
    token, _, _ = store.authenticate('change.user', PASSWORD)
    replacement = 'new-secret-password-2026'
    with pytest.raises(InvalidCredentials):
        store.change_password(user['id'], 'incorrect-password', replacement)
    assert store.resolve_session(token)
    with pytest.raises(IdentityError):
        store.change_password(user['id'], PASSWORD, 'short')
    assert store.change_password(user['id'], PASSWORD, replacement) is None
    assert store.resolve_session(token) is None
    assert store.authenticate('change.user', replacement)[2] == user


def test_password_change_cannot_overwrite_a_concurrent_reset(store, monkeypatch):
    user = store.create_user('change.user', PASSWORD)
    verify = store._verify_password

    def verify_then_reset(digest, password):
        result = verify(digest, password)
        store.reset_password(user['id'], 'administrator-reset-secret')
        return result

    monkeypatch.setattr(store, '_verify_password', verify_then_reset)
    with pytest.raises(InvalidCredentials):
        store.change_password(user['id'], PASSWORD, 'stale-request-secret')
    monkeypatch.setattr(store, '_verify_password', verify)
    assert store.authenticate('change.user', 'administrator-reset-secret')[2] == user


def test_audit_request_id_is_optional_and_stored_without_payload(store):
    request_id = 'b' * 32
    store.audit(None, 'document.read', target_id='a' * 32, request_id=request_id)
    store.audit(None, 'session.login')
    assert store.audit_events()[0]['request_id'] is None
    assert store.audit_events()[1]['request_id'] == request_id
    with pytest.raises(IdentityError):
        store.audit(None, 'document.read', request_id={'not': 'metadata'})


def test_old_audit_table_is_migrated_without_losing_rows(tmp_path):
    path = tmp_path / 'identity.db'
    with sqlite3.connect(path) as connection:
        connection.executescript('''
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                actor_id TEXT, action TEXT NOT NULL, workspace_id TEXT, target_id TEXT, outcome TEXT NOT NULL
            );
            INSERT INTO audit_events VALUES (1,'2026-01-01T00:00:00Z',NULL,'legacy.action',NULL,NULL,'success');
        ''')
    store = IdentityStore(path)
    assert store.audit_events()[0]['action'] == 'legacy.action'
    assert store.audit_events()[0]['request_id'] is None
    store.audit(None, 'current.action', request_id='c' * 32)
    assert len(store.audit_events()) == 2
