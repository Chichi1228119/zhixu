"""Parameterized SQLite persistence; connections belong to each operation."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, kind TEXT NOT NULL,
                    byte_size INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, location TEXT NOT NULL, text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def by_hash(self, digest: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM documents WHERE sha256=?', (digest,)).fetchone()
            return dict(row) if row else None

    def add(self, parsed: dict, byte_size: int, digest: str) -> dict:
        document = {'id': uuid4().hex, 'filename': parsed['filename'], 'kind': parsed['kind'],
                    'byte_size': byte_size, 'chunk_count': len(parsed['chunks']),
                    'created_at': datetime.now(timezone.utc).isoformat(), 'sha256': digest}
        with self.connect() as conn:
            conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', tuple(document.values()))
            conn.executemany('INSERT INTO chunks VALUES (?,?,?,?,?)',
                             [(uuid4().hex, document['id'], i, c['location'], c['text']) for i, c in enumerate(parsed['chunks'])])
        return document

    def documents(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM documents ORDER BY created_at, id')]

    def document(self, document_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
            if row is None:
                raise KeyError(document_id)
            result = dict(row)
            result['chunks'] = [dict(c) for c in conn.execute('''
                SELECT c.id, c.document_id, d.filename, c.location, c.text
                FROM chunks c JOIN documents d ON c.document_id=d.id
                WHERE c.document_id=? ORDER BY c.ordinal
            ''', (document_id,))]
            return result

    def chunks(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('''
                SELECT c.id, c.document_id, d.filename, c.location, c.text
                FROM chunks c JOIN documents d ON c.document_id=d.id
                ORDER BY d.created_at, d.id, c.ordinal
            ''')]

    def delete(self, document_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute('DELETE FROM documents WHERE id=?', (document_id,)).rowcount > 0
