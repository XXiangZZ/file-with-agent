"""Local, bounded JSONL diagnostics. Never serialize prompts, values or exceptions.

ContextVars join nested RAG/tool/model calls without persisting agent state. A trace
is diagnostic only: it cannot approve or resume an execution plan.
"""
import hashlib
import json
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from time import perf_counter
from uuid import uuid4

_current = ContextVar('archive_local_trace', default=None)
_lock = threading.Lock()
MAX_BYTES = 2 * 1024 * 1024


def text_summary(value):
    """A stable fingerprint is searchable without storing a user's question."""
    value = value if isinstance(value, str) else ''
    return {'chars': len(value), 'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()}


def argument_summary(arguments):
    # Deliberately omit keys as well: a model may put sensitive text in a key.
    if not isinstance(arguments, dict):
        return {'type': type(arguments).__name__}
    return {'argument_count': len(arguments),
            'value_types': sorted(type(value).__name__ for value in arguments.values()),
            'field_count': sum(len(arguments.get(key, {})) for key in ('fields', 'data')
                               if isinstance(arguments.get(key), dict))}


def result_summary(result):
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return {'type': 'text', 'chars': len(result)}
    if not isinstance(result, dict):
        return {'type': type(result).__name__}
    return {'has_error': bool(result.get('error')),
            'citation_count': len(result.get('citations', []))
                if isinstance(result.get('citations'), list) else 0,
            'has_pending_plan': result.get('status') == 'pending',
            'count': result.get('count') if isinstance(result.get('count'), int) else None}


class LocalTrace:
    def __init__(self, path):
        self.path = Path(path)
        self.run_id = uuid4().hex
        self.sequence = 0
        self.failed = False

    def emit(self, event, **fields):
        """Internal callers supply only whitelisted summaries; I/O cannot fail QA."""
        try:
            with _lock:
                self.sequence += 1
                row = {'version': 1, 'run_id': self.run_id, 'seq': self.sequence,
                       'time': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
                line = json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'
                if len(line.encode('utf-8')) > MAX_BYTES:
                    raise ValueError('trace event exceeds local size limit')
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
                    raise OSError('trace destination must be a regular file')
                if self.path.exists() and self.path.stat().st_size + len(line.encode('utf-8')) > MAX_BYTES:
                    backup = self.path.with_suffix(self.path.suffix + '.1')
                    if backup.is_symlink() or (backup.exists() and not backup.is_file()):
                        raise OSError('trace backup must be a regular file')
                    self.path.replace(backup)
                with self.path.open('a', encoding='utf-8') as output:
                    output.write(line)
        except Exception:
            # Disk full, permissions, serialization: diagnostic failure never changes
            # tool results, approval state, transaction outcome or model fallback.
            self.failed = True


def emit(event, **fields):
    trace = _current.get()
    if trace is not None:
        trace.emit(event, **fields)


def traced(kind):
    """Start a root trace, or join the active run; optional trace_path for tests/CLI."""
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            path = kwargs.pop('trace_path', None)
            existing = _current.get()
            token = None
            if existing is None:
                index = kwargs.get('index')
                if index is None:
                    index = next((arg for arg in args if hasattr(arg, 'path') and hasattr(arg, 'documents')), None)
                if path is None:
                    if index is not None:
                        path = Path(index.path).parent / 'logs' / 'assistant.jsonl'
                    else:
                        from config.settings import LOG_DIR
                        path = LOG_DIR / 'assistant.jsonl'
                existing = LocalTrace(path)
                token = _current.set(existing)
            started = perf_counter()
            query = kwargs.get('query')
            if query is None and kind == 'evaluation':
                question = kwargs.get('question') or next(
                    (arg for arg in args if isinstance(arg, dict) and 'question' in arg), {})
                query = question.get('question', '')
            if query is None:
                query = next((arg for arg in args if isinstance(arg, str)), '')
            emit('span_start', kind=kind, question=text_summary(query) if kind != 'transport' else None)
            try:
                result = function(*args, **kwargs)
                if isinstance(result, dict) and 'citations' in result:
                    emit('answer_summary', model_used=bool(result.get('model_used')),
                         citations=len(result.get('citations', [])),
                         verification='not_applicable_extractive' if not result.get('model_used')
                         else 'see_verification_events')
                emit('span_end', kind=kind, elapsed_ms=round((perf_counter() - started) * 1000, 3),
                     outcome='ok', fallback=bool(isinstance(result, dict) and
                     (result.get('fallback_reason') or '退回' in result.get('notice', ''))))
                return result
            except Exception as exc:
                emit('span_end', kind=kind, elapsed_ms=round((perf_counter() - started) * 1000, 3),
                     outcome='error', error_type=type(exc).__name__)
                raise
            finally:
                if token is not None:
                    _current.reset(token)
        return invoke
    return decorate


def retrieval_event(docs, mode, k):
    emit('retrieval', mode=mode if mode in {'keyword', 'hybrid', 'bm25_rrf'} else 'other', k=k,
         hits=[{'id': doc.metadata.get('id'), 'page': doc.metadata.get('page'),
                'retrieval_score': doc.metadata.get('retrieval_score'),
                'rerank_score': doc.metadata.get('rerank_score')}
               for doc in docs])


def verification(kind):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            try:
                result = function(*args, **kwargs)
            except Exception as exc:
                emit('verification', kind=kind, passed=False, error_type=type(exc).__name__)
                raise
            emit('verification', kind=kind, passed=True)
            return result
        return invoke
    return decorate
