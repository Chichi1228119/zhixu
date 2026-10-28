import hashlib
from contextlib import closing
import io
import json
import os
import sqlite3
import stat
import threading
import time
import zipfile

import pytest

from app.backup import create_backup, restore_backup


WORKSPACE = 'a' * 32


def database(path, value='original'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('CREATE TABLE records (value TEXT)')
        connection.execute('INSERT INTO records VALUES (?)', (value,))


def values(path):
    with closing(sqlite3.connect(path)) as connection:
        return [row[0] for row in connection.execute('SELECT value FROM records')]


@pytest.fixture
def source(tmp_path):
    data = tmp_path / 'source'
    database(data / 'control.db', 'identity')
    database(data / 'knowledge.db', 'legacy')
    database(data / 'workspaces' / WORKSPACE / 'knowledge.db', 'workspace')
    (data / 'model-config.json').write_text('{"api_key":"synthetic-private-key"}', encoding='utf-8')
    return data


def rewritten(path, entries=None, manifest_change=None, extra=()):
    target = io.BytesIO()
    with zipfile.ZipFile(path) as original, zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for item in original.infolist():
            data = original.read(item)
            if item.filename == 'manifest.json' and manifest_change:
                manifest = json.loads(data)
                manifest_change(manifest)
                data = json.dumps(manifest).encode()
            output.writestr(item, (entries or {}).get(item.filename, data))
        for name, data in extra:
            output.writestr(name, data)
    path.write_bytes(target.getvalue())


def test_roundtrip_all_databases_and_optional_secret(source, tmp_path):
    other = source / 'workspaces' / ('b' * 32) / 'knowledge.db'
    database(other, 'other-workspace')
    archive = tmp_path / 'snapshot.zip'
    manifest = create_backup(source, archive)
    assert manifest['schema_version'] == 1
    assert manifest['consistency'] == 'per-database'
    expected = {'control.db', 'knowledge.db', f'workspaces/{WORKSPACE}/knowledge.db',
                f'workspaces/{"b" * 32}/knowledge.db', 'model-config.json'}
    assert set(manifest['files']) == expected
    with zipfile.ZipFile(archive) as stored:
        assert json.loads(stored.read('manifest.json')) == manifest
        for name, metadata in manifest['files'].items():
            payload = stored.read(name)
            assert metadata == {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
    target = tmp_path / 'restored'
    assert restore_backup(archive, target) == manifest
    assert values(target / 'control.db') == ['identity']
    assert values(target / 'knowledge.db') == ['legacy']
    assert values(target / 'workspaces' / WORKSPACE / 'knowledge.db') == ['workspace']
    assert (target / 'model-config.json').read_bytes() == (source / 'model-config.json').read_bytes()


def test_backup_excludes_unlisted_data_models_logs_and_wal(source, tmp_path):
    for name in ['server.log', 'arbitrary.txt', 'models/model.gguf', 'private/private.db',
                 f'workspaces/{WORKSPACE}/secret.txt', 'workspaces/not-a-workspace/knowledge.db']:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('must-not-ship')
    manifest = create_backup(source, tmp_path / 'backup.zip')
    assert len(manifest['files']) == 4
    assert all(not name.endswith(('-wal', '-shm', '.log', '.gguf')) for name in manifest['files'])


def test_control_snapshot_omits_sessions_without_changing_live_identity_data(source, tmp_path):
    control = source / 'control.db'
    with closing(sqlite3.connect(control)) as connection, connection:
        connection.execute('CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id TEXT)')
        connection.execute("INSERT INTO sessions VALUES ('synthetic-token-hash', 'user-one')")
        connection.execute('CREATE TABLE users (id TEXT, password_hash TEXT)')
        connection.execute("INSERT INTO users VALUES ('user-one', 'synthetic-password-hash')")
        connection.execute('CREATE TABLE memberships (user_id TEXT, workspace_id TEXT)')
        connection.execute("INSERT INTO memberships VALUES ('user-one', 'workspace-one')")
        connection.execute('CREATE TABLE audit (action TEXT)')
        connection.execute("INSERT INTO audit VALUES ('preserve-audit')")
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    with closing(sqlite3.connect(control)) as connection:
        assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
    target = tmp_path / 'restore'; restore_backup(archive, target)
    with closing(sqlite3.connect(target / 'control.db')) as connection:
        assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
        assert connection.execute('SELECT * FROM users').fetchall() == [('user-one', 'synthetic-password-hash')]
        assert connection.execute('SELECT * FROM memberships').fetchall() == [('user-one', 'workspace-one')]
        assert connection.execute('SELECT * FROM audit').fetchall() == [('preserve-audit',)]
    with zipfile.ZipFile(archive) as stored:
        snapshot = tmp_path / 'archived-control.db'
        snapshot.write_bytes(stored.read('control.db'))
    with closing(sqlite3.connect(snapshot)) as connection:
        assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0


def test_valid_legacy_archive_cannot_revive_an_existing_session(tmp_path):
    from app.identity import IdentityStore
    data = tmp_path / 'data'
    identity = IdentityStore(data / 'control.db')
    user = identity.bootstrap('owner', 'Synthetic-legacy-backup-password!')
    workspace = identity.create_workspace('legacy-workspace')
    identity.grant(workspace['id'], user['id'], 'admin')
    identity.audit(user['id'], 'legacy.fixture', workspace_id=workspace['id'])
    token, *_ = identity.authenticate('owner', 'Synthetic-legacy-backup-password!')
    archive = tmp_path / 'backup.zip'; create_backup(data, archive)
    legacy = tmp_path / 'legacy-control.db'
    with closing(sqlite3.connect(data / 'control.db')) as source, closing(sqlite3.connect(legacy)) as copy:
        source.backup(copy)
    payload = legacy.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    rewritten(archive, entries={'control.db': payload}, manifest_change=lambda manifest: manifest['files'].update(
        {'control.db': {'sha256': digest, 'bytes': len(payload)}}))
    target = tmp_path / 'restore'
    manifest = restore_backup(archive, target)
    assert manifest['files']['control.db']['sha256'] == digest  # Describes the verified archive payload.
    assert identity.resolve_session(token) is not None
    restored = IdentityStore(target / 'control.db')
    assert restored.resolve_session(token) is None
    assert restored.list_users() == identity.list_users()
    assert restored.workspaces_for(user['id']) == identity.workspaces_for(user['id'])
    assert restored.audit_events() == identity.audit_events()


def test_existing_archive_and_destination_inside_data_are_refused(source, tmp_path):
    archive = tmp_path / 'existing.zip'
    archive.write_bytes(b'preserve')
    with pytest.raises(ValueError):
        create_backup(source, archive)
    assert archive.read_bytes() == b'preserve'
    with pytest.raises(ValueError):
        create_backup(source, source / 'nested' / 'backup.zip')
    assert not (source / 'nested').exists()


def test_restore_never_overwrites_existing_library(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    target = tmp_path / 'existing'; database(target / 'knowledge.db', 'keep-me')
    with pytest.raises(ValueError):
        restore_backup(archive, target)
    assert values(target / 'knowledge.db') == ['keep-me']


def test_restore_accepts_empty_directory(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    target = tmp_path / 'empty'; target.mkdir()
    restore_backup(archive, target)
    assert values(target / 'knowledge.db') == ['legacy']


@pytest.mark.parametrize('existing', [False, True])
def test_bad_hash_leaves_restore_destination_unchanged(source, tmp_path, existing):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    rewritten(archive, entries={'model-config.json': b'changed'})
    target = tmp_path / 'target'
    if existing:
        target.mkdir()
    with pytest.raises(ValueError):
        restore_backup(archive, target)
    assert target.exists() == existing
    assert not target.exists() or list(target.iterdir()) == []


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/escape', 'workspaces/../control.db',
                                'workspaces\\escape.db', 'private.db', 'models/model.gguf'])
def test_zip_slip_and_unlisted_members_are_rejected(source, tmp_path, name):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    rewritten(archive, extra=[(name, b'not-allowed')])
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


@pytest.mark.parametrize('change', [
    lambda m: m.update(schema_version=True), lambda m: m.update(schema_version=2),
    lambda m: m.update(consistency='atomic'), lambda m: m.update(created_at='not-a-date'),
    lambda m: m.update(unexpected='value'), lambda m: m.update(files={}),
    lambda m: m['files']['control.db'].update(bytes=True),
    lambda m: m['files']['control.db'].update(sha256='bad'),
    lambda m: m['files'].pop('control.db'),
])
def test_manifest_schema_is_strict(source, tmp_path, change):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    rewritten(archive, manifest_change=change)
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')


def test_duplicate_zip_member_is_rejected(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    with pytest.warns(UserWarning):
        rewritten(archive, extra=[('control.db', b'duplicate')])
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')


def test_symlink_member_is_rejected(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    link = zipfile.ZipInfo('model-config.json')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    target = io.BytesIO()
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(target, 'w') as output:
        for name in original.namelist():
            output.writestr(link if name == link.filename else name, original.read(name))
    archive.write_bytes(target.getvalue())
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')


def test_malformed_database_with_correct_hash_is_rejected(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    bad = b'not-a-database'
    rewritten(archive, entries={'control.db': bad}, manifest_change=lambda m: m['files'].update(
        {'control.db': {'bytes': len(bad), 'sha256': hashlib.sha256(bad).hexdigest()}}))
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')


def test_empty_source_and_corrupt_source_are_failures(tmp_path):
    source = tmp_path / 'data'; source.mkdir()
    (source / 'model-config.json').write_text('{"api_key":"synthetic-private-key"}')
    with pytest.raises(ValueError):
        create_backup(source, tmp_path / 'empty.zip')
    (source / 'control.db').write_text('synthetic-private-key')
    with pytest.raises(ValueError):
        create_backup(source, tmp_path / 'corrupt.zip')
    assert not (tmp_path / 'corrupt.zip').exists()


def test_sensitive_content_is_never_printed_or_in_errors(tmp_path, capsys):
    source = tmp_path / 'data'; source.mkdir()
    (source / 'control.db').write_text('synthetic-secret-do-not-echo')
    with pytest.raises(ValueError) as error:
        create_backup(source, tmp_path / 'failed.zip')
    assert 'synthetic-secret-do-not-echo' not in str(error.value)
    assert capsys.readouterr() == ('', '')


def test_live_wal_commits_are_in_online_snapshot(tmp_path):
    source = tmp_path / 'data'; source.mkdir()
    live = sqlite3.connect(source / 'control.db')
    live.execute('PRAGMA journal_mode=WAL')
    live.execute('CREATE TABLE records (value TEXT)')
    live.execute("INSERT INTO records VALUES ('committed-in-wal')"); live.commit()
    assert (source / 'control.db-wal').stat().st_size > 0
    try:
        create_backup(source, tmp_path / 'wal.zip')
        restore_backup(tmp_path / 'wal.zip', tmp_path / 'restored')
        assert {file.name for file in (tmp_path / 'restored').iterdir()} == {'control.db'}
        assert values(tmp_path / 'restored/control.db') == ['committed-in-wal']
    finally:
        live.close()


def test_online_snapshot_during_concurrent_wal_writer(tmp_path):
    source = tmp_path / 'source'; database(source / 'control.db')
    ready, stop = threading.Event(), threading.Event()

    def writer():
        with closing(sqlite3.connect(source / 'control.db')) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            number = 0
            while not stop.is_set():
                connection.execute('INSERT INTO records VALUES (?)', (str(number),))
                connection.commit()
                ready.set()
                number += 1
                time.sleep(0.001)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert ready.wait(3)
        create_backup(source, tmp_path / 'live.zip')
    finally:
        stop.set(); thread.join(timeout=5)
    restore_backup(tmp_path / 'live.zip', tmp_path / 'restore')
    assert values(tmp_path / 'restore/control.db')[:2] == ['original', '0']


def test_source_disappearance_does_not_publish_partial_backup(source, tmp_path, monkeypatch):
    import app.backup as module
    snapshot = module._snapshot

    def disappear(original, target, remaining):
        original.unlink()
        return snapshot(original, target, remaining)

    monkeypatch.setattr(module, '_snapshot', disappear)
    with pytest.raises(ValueError):
        create_backup(source, tmp_path / 'failed.zip')
    assert not (tmp_path / 'failed.zip').exists()
    assert not list(tmp_path.glob('.zhixu-backup-*'))


def test_restore_limits_bytes_and_entry_count_before_publish(source, tmp_path, monkeypatch):
    import app.backup as module
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 100)
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 2 * 1024 ** 3)
    monkeypatch.setattr(module, 'MAX_MEMBERS', 2)
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')


def test_final_archive_publication_never_clobbers_a_racing_file(source, tmp_path, monkeypatch):
    import app.backup as module
    publish = module._publish_file
    archive = tmp_path / 'racing.zip'

    def racing_file(original, destination):
        destination.write_bytes(b'created-by-someone-else')
        return publish(original, destination)

    monkeypatch.setattr(module, '_publish_file', racing_file)
    with pytest.raises(ValueError):
        create_backup(source, archive)
    assert archive.read_bytes() == b'created-by-someone-else'


def test_failed_restore_publication_preserves_existing_empty_directory(source, tmp_path, monkeypatch):
    import app.backup as module
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    target = tmp_path / 'empty'; target.mkdir()

    def denied(*args):
        raise PermissionError('synthetic-secret-never-echo')

    monkeypatch.setattr(module.os, 'rename', denied)
    with pytest.raises(ValueError) as error:
        restore_backup(archive, target)
    assert target.is_dir() and list(target.iterdir()) == []
    assert 'synthetic-secret-never-echo' not in str(error.value)
    assert not list(tmp_path.glob('.zhixu-restore-*'))


def test_zero_byte_optional_settings_file_roundtrips(source, tmp_path):
    (source / 'model-config.json').write_bytes(b'')
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    restore_backup(archive, tmp_path / 'restore')
    assert (tmp_path / 'restore/model-config.json').read_bytes() == b''


def test_duplicate_manifest_json_keys_are_rejected(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    with zipfile.ZipFile(archive) as original:
        manifest = original.read('manifest.json')
    rewritten(archive, entries={'manifest.json': manifest.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')})
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restore')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX modes do not describe Windows ACLs')
def test_archive_and_restored_files_are_owner_only(source, tmp_path):
    archive = tmp_path / 'backup.zip'; create_backup(source, archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    target = tmp_path / 'restore'; restore_backup(archive, target)
    for file in target.rglob('*'):
        if file.is_file():
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
