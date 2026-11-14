"""Per-task transport limits; nested RAG/tool calls share one in-memory budget."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from inspect import signature
import math
from time import monotonic

_budget = ContextVar('archive_request_budget', default=None)


class BudgetExceeded(RuntimeError):
    pass


class CircuitOpen(RuntimeError):
    pass


def number(config, name, default, low, high):
    value = float(config.get(name, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} 超出允许范围')
    return value


@dataclass
class RequestBudget:
    deadline: float
    max_requests: int
    max_tokens: int
    max_cost: float | None = None
    requests: int = 0
    reserved_tokens: int = 0
    reserved_cost: float = 0.
    reported_tokens: int = 0
    cost_known: bool = True

    @classmethod
    def from_config(cls, config):
        seconds = number(config, 'task_timeout', 180, .01, 3600)
        requests = number(config, 'max_requests', 16, 1, 100)
        tokens = number(config, 'max_task_tokens', 256000, 1, 10000000)
        if not requests.is_integer() or not tokens.is_integer():
            raise ValueError('请求数与token预算必须为整数')
        cost = number(config, 'max_task_cost', 0, 0, 1000) if config.get('max_task_cost') is not None else None
        return cls(monotonic() + seconds, int(requests), int(tokens), cost)

    def remaining(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise BudgetExceeded('任务总时间预算已用尽')
        return remaining

    def reserve(self, tokens, cost=None):
        self.remaining()
        if self.requests >= self.max_requests:
            raise BudgetExceeded('任务模型请求次数已达上限')
        if self.reserved_tokens + tokens > self.max_tokens:
            raise BudgetExceeded('任务token估算预算不足')
        if self.max_cost is not None and (cost is None or self.reserved_cost + cost > self.max_cost):
            raise BudgetExceeded('任务金额估算预算不足')
        self.requests += 1
        self.reserved_tokens += tokens
        self.cost_known = self.cost_known and cost is not None
        self.reserved_cost += cost or 0.

    def summary(self):
        return {'requests': self.requests, 'reserved_tokens': self.reserved_tokens,
                'reported_tokens': self.reported_tokens,
                'reserved_cost': round(self.reserved_cost, 8) if self.cost_known and self.requests else None,
                'max_requests': self.max_requests, 'max_tokens': self.max_tokens}


@contextmanager
def task_budget(config=None):
    existing = _budget.get()
    if existing is not None:
        yield existing
        return
    current = RequestBudget.from_config(config or {})
    token = _budget.set(current)
    try:
        yield current
    finally:
        from .tracing import emit
        emit('request_budget', **current.summary())
        _budget.reset(token)


def budgeted(function):
    parameters = signature(function)
    @wraps(function)
    def invoke(*args, **kwargs):
        bound = parameters.bind_partial(*args, **kwargs)
        service = bound.arguments.get('service') or bound.arguments.get('self') or bound.arguments.get('embeddings')
        config = getattr(service, 'config', {}) if service is not None else {}
        with task_budget(config) as current:
            result = function(*args, **kwargs)
            if isinstance(result, dict):
                result.setdefault('request_budget', current.summary())
            return result
    return invoke
