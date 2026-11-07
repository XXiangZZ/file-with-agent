"""Atomic incremental local index, separate from the existing archive SQLite DB."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from .parsing import Parser

VERSION = '1:500:80'


class KnowledgeIndex:
    def __init__(self, path, parser=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.parser = parser or Parser()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sources (
                    path TEXT PRIMARY KEY, digest TEXT NOT NULL, kind TEXT NOT NULL,
                    scope TEXT NOT NULL, imported TEXT NOT NULL, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, text TEXT NOT NULL,
                    metadata TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def sources(self):
        with self.connect() as db:
            return [dict(zip(('path', 'digest', 'kind', 'scope', 'imported', 'version'), row))
                    for row in db.execute('SELECT * FROM sources ORDER BY path')]

    def import_file(self, path, kind='规范', scope='通用', progress=lambda message: None, force=False):
        path = str(Path(path).resolve())
        if kind not in {'规范', '手册', '样例'} or not scope.strip():
            raise ValueError('必须指定资料类型和适用范围')
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with self.connect() as db:
            old = db.execute('SELECT digest,kind,scope,version FROM sources WHERE path=?', (path,)).fetchone()
        if not force and old == (digest, kind, scope, VERSION):
            return '未变化，跳过'
        docs = self.parser.parse(path, progress)
        imported = datetime.now(timezone.utc).isoformat()
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80,
            add_start_index=True, separators=['\n\n', '\n', '。', '；', '',])
        chunks = splitter.split_documents(docs)
        # Parse completely before replacing anything; failed OCR cannot erase old evidence.
        with self.connect() as db:
            db.execute('DELETE FROM chunks WHERE source=?', (path,))
            db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)',
                       (path, digest, kind, scope, imported, VERSION))
            for i, doc in enumerate(chunks):
                identity = hashlib.sha256(f'{path}:{digest}:{i}'.encode()).hexdigest()[:20]
                doc.metadata.update(id=identity, kind=kind, scope=scope, imported=imported)
                db.execute('INSERT INTO chunks VALUES (?,?,?,?)',
                           (identity, path, doc.page_content, json.dumps(doc.metadata, ensure_ascii=False)))
        return f'已索引 {len(docs)} 页 / {len(chunks)} 片段'

    def delete(self, path):
        with self.connect() as db:
            db.execute('DELETE FROM chunks WHERE source=?', (path,))
            db.execute('DELETE FROM sources WHERE path=?', (path,))

    def documents(self, scope, kinds=None):
        with self.connect() as db:
            stale = db.execute('SELECT COUNT(*) FROM sources WHERE version != ?', (VERSION,)).fetchone()[0]
            if stale:
                raise ValueError('索引版本已失效，请重建索引')
            rows = db.execute('SELECT text,metadata FROM chunks').fetchall()
        docs = [Document(page_content=t, metadata=json.loads(m)) for t, m in rows]
        return [d for d in docs if d.metadata['scope'] in {scope, '通用'}
                and d.metadata['kind'] != '样例'
                and (kinds is None or d.metadata['kind'] in kinds)]

    def rebuild(self, progress=lambda message: None):
        results = []
        for source in self.sources():
            try:
                result = self.import_file(source['path'], source['kind'], source['scope'], progress, force=True)
            except Exception as exc:
                result = f'失败，保留旧索引：{exc}'
            results.append(f"{source['path']}: {result}")
        return '\n'.join(results) or '知识库为空'
