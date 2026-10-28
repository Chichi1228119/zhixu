"""Sensitive, allowlisted SQLite backups and validated fresh-directory restores."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
import time
import zipfile

MAX_TOTAL_BYTES = 2 * 1024 ** 3
MAX_MEMBERS = 4097
MAX_MANIFEST_BYTES = 1024 * 1024
_WORKSPACE = re.compile(r'[a-f0-9]{32}')


class BackupError(ValueError):
    """A safe, non-secret-bearing backup or restore failure."""


def _allowed(name):
    parts = PurePosixPath(name).parts
    return (name in {'control.db', 'knowledge.db', 'model-config.json'} or
            len(parts) == 3 and parts[0] == 'workspaces' and
            _WORKSPACE.fullmatch(parts[1]) is not None and parts[2] == 'knowledge.db')


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _sources(root):
    if not root.is_dir() or _linked(root):
        raise ValueError
    paths = [root / name for name in ('control.db', 'knowledge.db', 'model-config.json')]
    workspace_root = root / 'workspaces'
    if _linked(workspace_root):
        raise ValueError
    if workspace_root.exists():
        for directory in sorted(workspace_root.iterdir()):
            if _WORKSPACE.fullmatch(directory.name):
                if _linked(directory) or not directory.is_dir():
                    raise ValueError
                paths.append(directory / 'knowledge.db')
    result = []
    for path in paths:
        if _linked(path):
            raise ValueError
        if path.exists():
            if not path.is_file():
                raise ValueError
            result.append(path)
    if not any(path.suffix == '.db' for path in result) or len(result) >= MAX_MEMBERS:
        raise ValueError
    return result


def _readonly(path, immutable=False):
    query = '?mode=ro&immutable=1' if immutable else '?mode=ro'
    return sqlite3.connect(path.resolve().as_uri() + query, uri=True, timeout=5)


def _integrity(path):
    with path.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\0':
            raise ValueError
    connection = _readonly(path, immutable=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError
    finally:
        connection.close()


def _new_file(path):
    return os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600), 'w+b')


def _purge_sessions(connection):
    if (connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone()
            and connection.execute('SELECT 1 FROM sessions LIMIT 1').fetchone()):
        connection.execute('PRAGMA secure_delete=ON')
        connection.execute('DELETE FROM sessions')
        connection.commit()


def _snapshot(source, target, remaining):
    if not source.is_file() or _linked(source) or source.stat().st_size > remaining:
        raise ValueError
    with source.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\0':
            raise ValueError
    with _new_file(target):
        pass
    started = time.monotonic()
    with closing(_readonly(source)) as connection, closing(sqlite3.connect(target)) as copy:
        page_size = connection.execute('PRAGMA page_size').fetchone()[0]

        def progress(status, remaining_pages, total_pages):
            if total_pages * page_size > remaining or time.monotonic() - started > 60:
                raise ValueError

        connection.backup(copy, pages=128, progress=progress, sleep=0.01)
        if source.name == 'control.db':
            _purge_sessions(copy)
    if not source.is_file() or _linked(source):
        raise ValueError
    _integrity(target)


def _metadata(path):
    with path.open('rb') as stream:
        return {'sha256': hashlib.file_digest(stream, 'sha256').hexdigest(), 'bytes': path.stat().st_size}


def _publish_file(source, target):
    # POSIX rename replaces an existing file; hard-link publication is atomic
    # and exclusive. Both names are on the same filesystem in the target parent.
    if os.name == 'nt':
        os.rename(source, target)
    else:
        os.link(source, target)
        source.unlink()


def create_backup(data_dir: Path, destination: Path) -> dict:
    """Snapshot each DB independently. The optional settings file contains secrets."""
    try:
        root = Path(data_dir).absolute()
        target = Path(destination).absolute()
        if target.resolve().is_relative_to(root.resolve()) or target.exists() or _linked(target):
            raise ValueError
        sources = _sources(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.zhixu-backup-', dir=target.parent) as directory:
            staging = Path(directory)
            files = {}
            total = 0
            for source in sources:
                name = source.relative_to(root).as_posix()
                snapshot = staging / name
                snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if source.suffix == '.db':
                    _snapshot(source, snapshot, MAX_TOTAL_BYTES - total)
                else:
                    if source.stat().st_size > MAX_TOTAL_BYTES - total:
                        raise ValueError
                    with source.open('rb') as original, _new_file(snapshot) as output:
                        copied = 0
                        while chunk := original.read(1024 * 1024):
                            copied += len(chunk)
                            if copied > MAX_TOTAL_BYTES - total:
                                raise ValueError
                            output.write(chunk)
                metadata = _metadata(snapshot)
                total += metadata['bytes']
                if total > MAX_TOTAL_BYTES:
                    raise ValueError
                files[name] = metadata
            manifest = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                        'consistency': 'per-database', 'files': files}
            raw = json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(raw) > MAX_MANIFEST_BYTES or total + len(raw) > MAX_TOTAL_BYTES:
                raise ValueError
            archive = staging / 'archive.zip'
            with _new_file(archive) as output:
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as stored:
                    for name in files:
                        stored.write(staging / name, name)
                    stored.writestr('manifest.json', raw)
                output.flush()
                os.fsync(output.fileno())
            _publish_file(archive, target)
        return manifest
    except Exception:
        raise BackupError('备份失败：请检查来源数据库、目标位置及可用空间；不会覆盖已有归档。') from None


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _manifest(stored):
    entries = stored.infolist()
    if len(entries) > MAX_MEMBERS:
        raise ValueError
    names = set()
    total = 0
    for entry in entries:
        name = entry.filename
        if (name != PurePosixPath(name).as_posix() or '\\' in name or '\0' in entry.orig_filename
                or ':' in name or PurePosixPath(name).is_absolute() or
                any(part in {'.', '..'} for part in name.split('/')) or
                name.casefold() in names or entry.is_dir() or
                stat.S_IFMT(entry.external_attr >> 16) not in {0, stat.S_IFREG} or
                entry.flag_bits & 1 or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} or
                name != 'manifest.json' and not _allowed(name)):
            raise ValueError
        names.add(name.casefold())
        total += entry.file_size
        if entry.file_size > MAX_TOTAL_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError
    info = stored.getinfo('manifest.json')
    if info.file_size > MAX_MANIFEST_BYTES:
        raise ValueError
    with stored.open(info) as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError
    manifest = json.loads(raw, object_pairs_hook=_unique_json)
    if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'created_at', 'consistency', 'files'} or
            type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or
            manifest['consistency'] != 'per-database' or not isinstance(manifest['created_at'], str)):
        raise ValueError
    if datetime.fromisoformat(manifest['created_at']).utcoffset() is None:
        raise ValueError
    files = manifest['files']
    if (not isinstance(files, dict) or not files or set(files) != {entry.filename for entry in entries} - {'manifest.json'} or
            not any(name.endswith('.db') for name in files)):
        raise ValueError
    for name, metadata in files.items():
        if (not _allowed(name) or not isinstance(metadata, dict) or set(metadata) != {'sha256', 'bytes'} or
                type(metadata['bytes']) is not int or not 0 <= metadata['bytes'] <= MAX_TOTAL_BYTES or
                metadata['bytes'] != stored.getinfo(name).file_size or not isinstance(metadata['sha256'], str) or
                re.fullmatch(r'[a-f0-9]{64}', metadata['sha256']) is None):
            raise ValueError
    return manifest


def restore_backup(archive: Path, destination: Path) -> dict:
    """Validate, purge restored sessions, then publish into a fresh directory.

    The returned manifest describes the original verified archive payload. A
    legacy control DB can change after validation because sessions are removed.
    """
    try:
        target = Path(destination).absolute()
        if _linked(target) or target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.zhixu-restore-', dir=target.parent) as directory:
            staging = Path(directory) / 'restored'
            staging.mkdir(mode=0o700)
            with zipfile.ZipFile(archive) as stored:
                manifest = _manifest(stored)
                for name, metadata in manifest['files'].items():
                    path = staging / name
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest = hashlib.sha256()
                    size = 0
                    with stored.open(name) as source, _new_file(path) as output:
                        while chunk := source.read(1024 * 1024):
                            size += len(chunk)
                            if size > metadata['bytes']:
                                raise ValueError
                            digest.update(chunk)
                            output.write(chunk)
                    if size != metadata['bytes'] or digest.hexdigest() != metadata['sha256']:
                        raise ValueError
                    if path.suffix == '.db':
                        _integrity(path)
            control = staging / 'control.db'
            if control.exists():
                with closing(sqlite3.connect(control)) as connection:
                    _purge_sessions(connection)
                _integrity(control)
            if _linked(target) or target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ValueError
            existed = target.exists()
            mode = stat.S_IMODE(target.stat().st_mode) if existed else 0o700
            if existed:
                target.rmdir()
            try:
                os.rename(staging, target)
            except Exception:
                if existed and not target.exists():
                    target.mkdir(mode=mode)
                    target.chmod(mode)
                raise
        return manifest
    except Exception:
        raise BackupError('恢复失败：归档无效或目标不是新的空目录；已有资料不会被覆盖。') from None
