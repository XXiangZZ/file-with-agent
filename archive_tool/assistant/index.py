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

VERSION = '2:500:80:vector'


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
                CREATE TABLE IF NOT EXISTS vectors (
                    chunk_id TEXT PRIMARY KEY, vector TEXT NOT NULL,
                    model TEXT NOT NULL, dimension INTEGER NOT NULL,
                    FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE);
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

    def import_file(self, path, kind='规范', scope='通用', progress=lambda message: None, force=False, embeddings=None):
        path = str(Path(path).resolve())
        if kind not in {'规范', '手册', '样例'} or not scope.strip():
            raise ValueError('必须指定资料类型和适用范围')
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with self.connect() as db:
            old = db.execute('SELECT digest,kind,scope,version FROM sources WHERE path=?', (path,)).fetchone()
        if not force and old == (digest, kind, scope, VERSION):
            if embeddings and self._vector_count(path) == 0:
                self._embed_source(path, embeddings, progress)
                return '未变化，已完成服务向量创建'
            return '未变化，跳过'
        docs = self.parser.parse(path, progress)
        imported = datetime.now(timezone.utc).isoformat()
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80,
            add_start_index=True, separators=['\n\n', '\n', '。', '；', '',])
        chunks = splitter.split_documents(docs)
        vectors = None
        if embeddings:
            progress('正在为分块生成并保存向量')
            vectors = embeddings.embed_documents([doc.page_content for doc in chunks])
            if len(vectors) != len(chunks) or any(not vector for vector in vectors):
                raise ValueError('嵌入服务返回的向量与分块不匹配')
            dimension = len(vectors[0])
            if any(len(vector) != dimension for vector in vectors):
                raise ValueError('嵌入向量维度不一致')
        # Parse and embed completely before replacing anything; failed OCR/vectorization cannot erase old evidence.
        with self.connect() as db:
            db.execute('DELETE FROM chunks WHERE source=?', (path,))
            db.execute('DELETE FROM vectors WHERE chunk_id NOT IN (SELECT id FROM chunks)')
            db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)',
                       (path, digest, kind, scope, imported, VERSION))
            for i, doc in enumerate(chunks):
                identity = hashlib.sha256(f'{path}:{digest}:{i}'.encode()).hexdigest()[:20]
                doc.metadata.update(id=identity, kind=kind, scope=scope, imported=imported)
                db.execute('INSERT INTO chunks VALUES (?,?,?,?)',
                           (identity, path, doc.page_content, json.dumps(doc.metadata, ensure_ascii=False)))
                if vectors is not None:
                    db.execute('INSERT INTO vectors VALUES (?,?,?,?)',
                               (identity, json.dumps(vectors[i]),
                                getattr(embeddings, 'model_name', type(embeddings).__name__),
                                len(vectors[i])))
        return f'已索引 {len(docs)} 页 / {len(chunks)} 片段'

    def delete(self, path):
        with self.connect() as db:
            db.execute('DELETE FROM chunks WHERE source=?', (path,))
            db.execute('DELETE FROM vectors WHERE chunk_id NOT IN (SELECT id FROM chunks)')
            db.execute('DELETE FROM sources WHERE path=?', (path,))

    def _vector_count(self, source):
        with self.connect() as db:
            return db.execute('''SELECT COUNT(*) FROM vectors v JOIN chunks c ON c.id=v.chunk_id
                                 WHERE c.source=?''', (source,)).fetchone()[0]

    def _embed_source(self, source, embeddings, progress):
        with self.connect() as db:
            rows = db.execute('SELECT id,text FROM chunks WHERE source=? ORDER BY id', (source,)).fetchall()
        vectors = embeddings.embed_documents([text for _, text in rows])
        if len(vectors) != len(rows) or not vectors or any(len(v) != len(vectors[0]) for v in vectors):
            raise ValueError('嵌入服务返回的向量不可用')
        with self.connect() as db:
            for (chunk_id, _), vector in zip(rows, vectors):
                db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)',
                           (chunk_id, json.dumps(vector),
                            getattr(embeddings, 'model_name', type(embeddings).__name__), len(vector)))
        progress(f'已完成索引向量：{len(rows)} 个分块')

    def vector_rows(self, scope, kinds=None):
        """Return filtered documents together with persisted vectors."""
        docs = self.documents(scope, kinds)
        with self.connect() as db:
            rows = {row[0]: json.loads(row[1]) for row in db.execute('SELECT chunk_id,vector FROM vectors')}
        return [(doc, rows.get(doc.metadata.get('id'))) for doc in docs]
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
