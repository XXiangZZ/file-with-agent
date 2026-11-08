"""Atomic incremental local index, separate from the existing archive SQLite DB."""
import hashlib
import json
import math
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
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL, answer TEXT NOT NULL,
                    citations TEXT NOT NULL, scope TEXT NOT NULL,
                    helpful INTEGER, correction TEXT NOT NULL DEFAULT '',
                    failure TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
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
            preserved_vectors = {}
            if not embeddings and old and old[0] == digest and old[3] == VERSION:
                preserved_vectors = {row[0]: row[1:] for row in db.execute('''
                    SELECT v.chunk_id,v.vector,v.model,v.dimension FROM vectors v
                    JOIN chunks c ON c.id=v.chunk_id WHERE c.source=?''', (path,))}
        if not force and old == (digest, kind, scope, VERSION):
            if embeddings and not self._source_vectors_match(path, embeddings):
                self._embed_source(path, embeddings, progress)
                return '未变化，已按当前嵌入模型更新向量'
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
            self._validate_vectors(vectors, len(chunks))
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
                elif identity in preserved_vectors:
                    vector, model, dimension = preserved_vectors[identity]
                    db.execute('INSERT INTO vectors VALUES (?,?,?,?)',
                               (identity, vector, model, dimension))
            db.execute('DELETE FROM vectors WHERE chunk_id NOT IN (SELECT id FROM chunks)')
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

    def _source_vectors_match(self, source, embeddings):
        expected = getattr(embeddings, 'model_name', type(embeddings).__name__)
        with self.connect() as db:
            rows = db.execute('''SELECT v.vector,v.dimension,v.model FROM chunks c
                LEFT JOIN vectors v ON v.chunk_id=c.id WHERE c.source=?''',
                (source,)).fetchall()
        models = {row[2] for row in rows if row[2] is not None}
        stored_dimensions = {row[1] for row in rows if row[1] is not None}
        if not rows or any(row[0] is None or row[1] is None for row in rows):
            return False
        try:
            vectors_valid = all(len(json.loads(row[0])) == row[1] for row in rows)
        except (TypeError, ValueError, json.JSONDecodeError):
            vectors_valid = False
        return len(models) == 1 and models == {expected} and len(stored_dimensions) == 1 and vectors_valid

    @staticmethod
    def _validate_vectors(vectors, expected_count):
        if not isinstance(vectors, (list, tuple)) or len(vectors) != expected_count or not vectors:
            raise ValueError('嵌入服务返回的向量与分块不匹配')
        if any(not isinstance(vector, (list, tuple)) for vector in vectors):
            raise ValueError('嵌入服务返回的向量格式无效')
        dimension = len(vectors[0])
        if not dimension or any(not isinstance(vector, (list, tuple)) or len(vector) != dimension
                                for vector in vectors):
            raise ValueError('嵌入向量维度不一致')
        if any(not isinstance(value, (int, float)) or not math.isfinite(value)
               for vector in vectors for value in vector):
            raise ValueError('嵌入向量包含无效数值')
        return dimension

    def _embed_source(self, source, embeddings, progress):
        with self.connect() as db:
            rows = db.execute('SELECT id,text FROM chunks WHERE source=? ORDER BY id', (source,)).fetchall()
        vectors = embeddings.embed_documents([text for _, text in rows])
        dimension = self._validate_vectors(vectors, len(rows))
        model = getattr(embeddings, 'model_name', type(embeddings).__name__)
        with self.connect() as db:
            db.execute('''DELETE FROM vectors WHERE chunk_id IN
                          (SELECT id FROM chunks WHERE source=?)''', (source,))
            for (chunk_id, _), vector in zip(rows, vectors):
                db.execute('INSERT INTO vectors VALUES (?,?,?,?)',
                           (chunk_id, json.dumps(vector), model, len(vector)))
        progress(f'已完成索引向量：{len(rows)} 个分块')

    def vector_rows(self, scope, kinds=None, expected_model=None):
        """Return filtered documents together with persisted vectors."""
        docs = self.documents(scope, kinds)
        with self.connect() as db:
            rows = {row[0]: (json.loads(row[1]), row[2], row[3])
                    for row in db.execute('SELECT chunk_id,vector,model,dimension FROM vectors')}
        if expected_model:
            models = {rows[doc.metadata['id']][1] for doc in docs if doc.metadata['id'] in rows}
            if models and models != {expected_model}:
                raise ValueError('嵌入模型已变更，向量索引失效；请重新导入或重建索引')
        for doc in docs:
            stored = rows.get(doc.metadata.get('id'))
            if stored and (len(stored[0]) != stored[2] or
                           any(not isinstance(value, (int, float)) or not math.isfinite(value)
                               for value in stored[0])):
                raise ValueError('持久化向量维度异常，请重建索引')
        return [(doc, rows[doc.metadata['id']][0] if doc.metadata['id'] in rows else None)
                for doc in docs]

    def vector_state(self, source, expected_model=None):
        with self.connect() as db:
            chunk_count = db.execute('SELECT COUNT(*) FROM chunks WHERE source=?', (source,)).fetchone()[0]
            rows = db.execute('''SELECT v.model,v.dimension,v.vector FROM vectors v
                JOIN chunks c ON c.id=v.chunk_id WHERE c.source=?''', (source,)).fetchall()
        if not rows:
            return {'state': 'missing', 'chunks': chunk_count, 'vectors': 0, 'models': []}
        models = sorted({row[0] for row in rows})
        try:
            dimensions_valid = all(len(json.loads(row[2])) == row[1] and
                                   all(math.isfinite(value) for value in json.loads(row[2]))
                                   for row in rows)
        except (TypeError, ValueError, json.JSONDecodeError):
            dimensions_valid = False
        valid = len(rows) == chunk_count and len(models) == 1 and dimensions_valid
        if expected_model:
            valid = valid and models == [expected_model]
        return {'state': 'ready' if valid else 'invalid', 'chunks': chunk_count,
                'vectors': len(rows), 'models': models}
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

    def rebuild(self, progress=lambda message: None, embeddings=None):
        results = []
        for source in self.sources():
            try:
                result = self.import_file(source['path'], source['kind'], source['scope'],
                                          progress, force=True, embeddings=embeddings)
            except Exception as exc:
                result = f'失败，保留旧索引：{exc}'
            results.append(f"{source['path']}: {result}")
        return '\n'.join(results) or '知识库为空'

    def record_feedback(self, question, answer='', citations=(), scope='通用', helpful=None,
                        correction='', failure=''):
        if helpful not in (None, True, False):
            raise ValueError('反馈状态无效')
        with self.connect() as db:
            cursor = db.execute('''INSERT INTO feedback
                (question,answer,citations,scope,helpful,correction,failure,created)
                VALUES (?,?,?,?,?,?,?,?)''',
                (question, answer, json.dumps(citations, ensure_ascii=False), scope,
                 None if helpful is None else int(helpful), correction, failure,
                 datetime.now(timezone.utc).isoformat()))
            return cursor.lastrowid

    def feedback_samples(self, needs_review=False):
        query = '''SELECT id,question,answer,citations,scope,helpful,correction,failure,created
                   FROM feedback'''
        params = ()
        if needs_review:
            query += ' WHERE helpful=? OR failure != ?'
            params = (0, '')
        query += ' ORDER BY id'
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        keys = ('id', 'question', 'answer', 'citations', 'scope', 'helpful',
                'correction', 'failure', 'created')
        result = [dict(zip(keys, row)) for row in rows]
        for row in result:
            row['citations'] = json.loads(row['citations'])
            if row['helpful'] is not None:
                row['helpful'] = bool(row['helpful'])
        return result
