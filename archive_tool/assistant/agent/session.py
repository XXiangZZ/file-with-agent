"""Bounded in-memory conversational context, never an approval checkpoint."""
import json
import threading
from time import monotonic
from functools import wraps
from langchain_core.messages import HumanMessage, AIMessage


class AgentSession:
    def __init__(self, max_turns=6, max_chars=12000, ttl=900):
        if max_turns < 1 or max_chars < 100 or ttl <= 0:
            raise ValueError('会话保留参数无效')
        self.max_turns, self.max_chars, self.ttl = max_turns, max_chars, ttl
        self.turns = []
        self.context = None
        self.updated = monotonic()
        self.plan_store = None
        self._lock = threading.Lock()
        self._running = False

    def clear(self):
        with self._lock:
            if self._running:
                raise RuntimeError('会话正在处理，不能清空')
            if self._pending():
                raise RuntimeError('请先处理待确认计划，再清空会话')
            self.turns.clear()
            self.context = None
            self.plan_store = None

    def _pending(self):
        return self.plan_store and any(plan.status in {'pending', 'approved'} for plan in self.plan_store.plans.values())

    def begin(self, context):
        with self._lock:
            if self._running or self._pending():
                raise RuntimeError('请先完成当前任务或处理待确认计划')
            if self.context != context or monotonic() - self.updated > self.ttl:
                self.turns.clear()
            self.context = context
            self._running = True

    def messages(self):
        messages = []
        for question, answer in self.turns:
            messages.extend([HumanMessage(content=question), AIMessage(content=answer)])
        return messages

    def finish(self, query, result):
        with self._lock:
            self.plan_store = result.get('_plan_store', self.plan_store)
            if result.get('answer_verified') and result.get('verified_claims'):
                # Do not save full tool messages, citation content, draft fields,
                # snapshots, plan arguments or raw model output in history.
                answer = json.dumps({'previous_verified_answer': result['verified_answer'],
                    'context_only_not_current_evidence': True}, ensure_ascii=False)
                self.turns.append((query, answer))
                self.turns = self.turns[-self.max_turns:]
                while self.turns and sum(len(q) + len(a) for q, a in self.turns) > self.max_chars:
                    self.turns.pop(0)
            self.updated = monotonic()


def session_turn(function):
    @wraps(function)
    def invoke(query, index, service, **kwargs):
        session = kwargs.get('session')
        if session is None:
            return function(query, index, service, **kwargs)
        context = (str(index.path), kwargs.get('batch_id'), kwargs.get('template_name'),
                   kwargs.get('allow_model_calls'), getattr(service, 'model_name', None),
                   getattr(service, 'chat_model', None), index.revision())
        session.begin(context)
        try:
            result = function(query, index, service, **kwargs)
            session.finish(query, result)
            result['session_turns'] = len(session.turns)
            return result
        finally:
            with session._lock:
                session._running = False
    return invoke
