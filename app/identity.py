"""Single-organization identities, membership and revocable sessions."""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_USERNAME = re.compile(r'[A-Za-z0-9_.-]{3,64}\Z')
_AUDIT_TAG = re.compile(r'[A-Za-z0-9_.:-]+\Z')
_ARGON2_SLOTS = threading.BoundedSemaphore(4)
_FAILURE_WINDOW = 15 * 60


@contextmanager
def _argon_slot():
    if not _ARGON2_SLOTS.acquire(blocking=False):
        raise RateLimited('身份验证繁忙，请稍后重试。')
    try:
        yield
    finally:
        _ARGON2_SLOTS.release()


@lru_cache(maxsize=1)
def _dummy_hash():
    with _argon_slot():
        return PasswordHasher().hash(secrets.token_urlsafe(32))


def _created_at():
    return datetime.now(timezone.utc).isoformat()


def _public_user(row):
    return {'id': row['id'], 'username': row['username'], 'is_admin': bool(row['is_admin']),
            'active': bool(row['active']), 'created_at': row['created_at']}


def _validate_credentials(username, password):
    if not isinstance(username, str) or _USERNAME.fullmatch(username) is None:
        raise IdentityError('账号须为 3 到 64 个 ASCII 字母、数字、下划线、点或连字符。')
    _validate_password(password)
    return username.casefold()


def _validate_password(password):
    try:
        valid = isinstance(password, str) and 12 <= len(password) <= 128 and len(password.encode('utf-8')) <= 512
    except UnicodeError:
        valid = False
    if not valid:
        raise IdentityError('密码须为 12 到 128 个有效 UTF-8 字符，最多 512 字节。')


def _password_candidate(password):
    try:
        _validate_password(password)
        return password, True
    except IdentityError:
        return 'invalid-input-placeholder', False


def _audit_field(value, label, maximum, optional=False):
    if value is None and optional:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or _AUDIT_TAG.fullmatch(value) is None:
        raise IdentityError(f'{label} 必须是最多 {maximum} 字符的标识符。')


class IdentityError(ValueError):
    pass


class InvalidCredentials(IdentityError):
    pass


class RateLimited(IdentityError):
    pass


class LastAdminError(IdentityError):
    pass


class IdentityStore:
    def __init__(self, path: Path, session_seconds=28800):
        if type(session_seconds) is not int or session_seconds <= 0:
            raise IdentityError('会话期限须为正整数秒。')
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != 'nt':
            os.chmod(self.path.parent, 0o700)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        if os.name != 'nt':
            os.chmod(self.path, 0o600)
        self.session_seconds = session_seconds
        self._hasher = PasswordHasher()
        self._dummy = _dummy_hash()
        with self._connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL CHECK(is_admin IN (0,1)),
                    active INTEGER NOT NULL CHECK(active IN (0,1)), created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memberships (
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('viewer','editor','admin')),
                    PRIMARY KEY(workspace_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS login_failures (bucket TEXT NOT NULL, failed_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS failures_bucket ON login_failures(bucket,failed_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    actor_id TEXT, action TEXT NOT NULL, workspace_id TEXT, target_id TEXT,
                    outcome TEXT NOT NULL, request_id TEXT
                );
            ''')
        with self._connect(write=True) as connection:
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(audit_events)')}
            if 'request_id' not in columns:
                connection.execute('ALTER TABLE audit_events ADD COLUMN request_id TEXT')

    @contextmanager
    def _connect(self, write=False):
        connection = sqlite3.connect(str(self.path), timeout=20, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=20000')
        try:
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _hash_password(self, password):
        with _argon_slot():
            return self._hasher.hash(password)

    def _verify_password(self, digest, password):
        with _argon_slot():
            try:
                return self._hasher.verify(digest, password)
            except (VerificationError, InvalidHashError):
                return False

    def _create_user(self, username, password, is_admin, bootstrap=False):
        username = _validate_credentials(username, password)
        if type(is_admin) is not bool:
            raise IdentityError('管理员标志必须为布尔值。')
        digest = self._hash_password(password)
        user = {'id': uuid4().hex, 'username': username, 'is_admin': is_admin,
                'active': True, 'created_at': _created_at()}
        try:
            with self._connect(write=True) as connection:
                if bootstrap and connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                    raise IdentityError('已存在账号，不能重复初始化管理员。')
                connection.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',
                                   (user['id'], username, digest, int(is_admin), 1, user['created_at']))
        except sqlite3.IntegrityError:
            raise IdentityError('该账号已存在。') from None
        return user

    def bootstrap(self, username, password):
        return self._create_user(username, password, True, bootstrap=True)

    def create_user(self, username, password, is_admin=False):
        return self._create_user(username, password, is_admin)

    def list_users(self):
        with self._connect() as connection:
            return [_public_user(row) for row in connection.execute('SELECT * FROM users ORDER BY created_at,id')]

    def reset_password(self, user_id, new_password):
        _validate_password(new_password)
        digest = self._hash_password(new_password)
        with self._connect(write=True) as connection:
            if not connection.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
                raise IdentityError('账号不存在。')
            connection.execute('UPDATE users SET password_hash=? WHERE id=?', (digest, user_id))
            connection.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def change_password(self, user_id, current_password, new_password):
        _validate_password(new_password)
        with self._connect() as connection:
            user = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        candidate, valid = _password_candidate(current_password)
        verified = self._verify_password(user['password_hash'] if user else self._dummy, candidate)
        if not (valid and verified and user and user['active']):
            raise InvalidCredentials('账号或密码错误。')
        digest = self._hash_password(new_password)
        with self._connect(write=True) as connection:
            current = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not current or not current['active'] or current['password_hash'] != user['password_hash']:
                raise InvalidCredentials('账号或密码错误。')
            connection.execute('UPDATE users SET password_hash=? WHERE id=?', (digest, user_id))
            connection.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def set_user_active(self, user_id, active):
        if type(active) is not bool:
            raise IdentityError('账号启用标志必须为布尔值。')
        with self._connect(write=True) as connection:
            user = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if user is None:
                raise IdentityError('账号不存在。')
            if not active and user['active'] and user['is_admin']:
                remaining = connection.execute('SELECT COUNT(*) FROM users WHERE active=1 AND is_admin=1').fetchone()[0]
                if remaining <= 1:
                    raise LastAdminError('不能停用最后一个已启用的全局管理员。')
            connection.execute('UPDATE users SET active=? WHERE id=?', (int(active), user_id))
            connection.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            result = _public_user(user)
            result['active'] = active
            return result

    def authenticate(self, username, password, client_key='local'):
        normalized = username.casefold() if isinstance(username, str) else ''
        valid_username = isinstance(username, str) and _USERNAME.fullmatch(username) is not None
        if not isinstance(client_key, str) or len(client_key) > 256:
            raise IdentityError('登录来源标识无效。')
        bucket = hashlib.sha256(json.dumps([client_key, normalized], ensure_ascii=True).encode()).hexdigest()
        cutoff = time.time() - _FAILURE_WINDOW
        with self._connect() as connection:
            failures = connection.execute('SELECT COUNT(*) FROM login_failures WHERE bucket=? AND failed_at>?', (bucket, cutoff)).fetchone()[0]
            if failures >= 5:
                raise RateLimited('尝试次数过多，请在失败记录过期后重试。')
            user = connection.execute('SELECT * FROM users WHERE username=?', (normalized,)).fetchone() if valid_username else None
        candidate, valid_password = _password_candidate(password)
        digest = user['password_hash'] if user else self._dummy
        verified = self._verify_password(digest, candidate)
        now = time.time()
        limited = False
        result = None
        with self._connect(write=True) as connection:
            connection.execute('DELETE FROM login_failures WHERE failed_at<=?', (now - _FAILURE_WINDOW,))
            failures = connection.execute('SELECT COUNT(*) FROM login_failures WHERE bucket=?', (bucket,)).fetchone()[0]
            current = connection.execute('SELECT * FROM users WHERE username=?', (normalized,)).fetchone() if valid_username else None
            if failures >= 5:
                limited = True
            elif not (valid_password and verified and current and current['active'] and current['password_hash'] == digest):
                connection.execute('INSERT INTO login_failures VALUES (?,?)', (bucket, now))
            else:
                connection.execute('DELETE FROM login_failures WHERE bucket=?', (bucket,))
                connection.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                connection.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                                   (hashlib.sha256(token.encode()).hexdigest(), current['id'], csrf,
                                    int(now), int(now) + self.session_seconds))
                result = token, csrf, _public_user(current)
        if limited:
            raise RateLimited('尝试次数过多，请在失败记录过期后重试。')
        if result is None:
            raise InvalidCredentials('账号或密码错误。')
        return result

    def resolve_session(self, token):
        if not isinstance(token, str) or not token:
            return None
        digest = hashlib.sha256(token.encode('utf-8', errors='replace')).hexdigest()
        with self._connect() as connection:
            row = connection.execute('''
                SELECT u.*,s.csrf_token,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.active=1
            ''', (digest, time.time())).fetchone()
            return dict(_public_user(row), csrf_token=row['csrf_token'], expires_at=row['expires_at']) if row else None

    def logout(self, token):
        if not isinstance(token, str) or not token:
            return
        with self._connect(write=True) as connection:
            connection.execute('DELETE FROM sessions WHERE token_hash=?',
                               (hashlib.sha256(token.encode('utf-8', errors='replace')).hexdigest(),))

    def create_workspace(self, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128:
            raise IdentityError('空间名称须为 1 到 128 个字符。')
        workspace = {'id': uuid4().hex, 'name': name.strip(), 'created_at': _created_at()}
        with self._connect(write=True) as connection:
            connection.execute('INSERT INTO workspaces VALUES (?,?,?)', tuple(workspace.values()))
        return workspace

    def workspaces_for(self, user_id):
        with self._connect() as connection:
            user = connection.execute('SELECT * FROM users WHERE id=? AND active=1', (user_id,)).fetchone()
            if not user:
                return []
            if user['is_admin']:
                rows = connection.execute("SELECT *, 'admin' AS role FROM workspaces ORDER BY created_at,id")
            else:
                rows = connection.execute('''
                    SELECT w.*,m.role FROM workspaces w JOIN memberships m ON m.workspace_id=w.id
                    WHERE m.user_id=? ORDER BY w.created_at,w.id
                ''', (user_id,))
            return [dict(row) for row in rows]

    def _check_membership_ids(self, connection, workspace_id, user_id):
        if (not connection.execute('SELECT 1 FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
                or not connection.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone()):
            raise IdentityError('空间或账号不存在。')

    def grant(self, workspace_id, user_id, role):
        if not isinstance(role, str) or role not in {'viewer', 'editor', 'admin'}:
            raise IdentityError('空间角色只能是 viewer、editor 或 admin。')
        with self._connect(write=True) as connection:
            self._check_membership_ids(connection, workspace_id, user_id)
            connection.execute('''
                INSERT INTO memberships VALUES (?,?,?)
                ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role
            ''', (workspace_id, user_id, role))

    def revoke(self, workspace_id, user_id):
        with self._connect(write=True) as connection:
            self._check_membership_ids(connection, workspace_id, user_id)
            connection.execute('DELETE FROM memberships WHERE workspace_id=? AND user_id=?', (workspace_id, user_id))

    def membership(self, user_id, workspace_id):
        with self._connect() as connection:
            row = connection.execute('''
                SELECT u.is_admin,m.role FROM workspaces w JOIN users u ON u.id=? AND u.active=1
                LEFT JOIN memberships m ON m.workspace_id=w.id AND m.user_id=u.id WHERE w.id=?
            ''', (user_id, workspace_id)).fetchone()
            return ('admin' if row['is_admin'] else row['role']) if row else None

    def audit(self, actor_id, action, workspace_id=None, target_id=None, outcome='success', request_id=None):
        _audit_field(actor_id, '身份 ID', 128, optional=True)
        _audit_field(action, '操作类型', 64)
        _audit_field(workspace_id, '空间 ID', 128, optional=True)
        _audit_field(target_id, '对象 ID', 128, optional=True)
        _audit_field(outcome, '操作结果', 32)
        _audit_field(request_id, '请求 ID', 128, optional=True)
        with self._connect(write=True) as connection:
            connection.execute('''
                INSERT INTO audit_events(created_at,actor_id,action,workspace_id,target_id,outcome,request_id)
                VALUES (?,?,?,?,?,?,?)
            ''', (_created_at(), actor_id, action, workspace_id, target_id, outcome, request_id))

    def audit_events(self, limit=100, offset=0):
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise IdentityError('审计分页须为 1 到 1000 条，offset 不得为负数。')
        with self._connect() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset))]
