"""Async entrypoints: local tools in one worker, native HTTP on the event loop."""
import asyncio
import inspect
from .async_http import AsyncModelService, AsyncBridge


async def invoke_async(function, *args, service=None, stream=True, progress=None, transport=None, **kwargs):
    if progress is not None and 'progress' in inspect.signature(function).parameters:
        kwargs['progress'] = progress
    def local(active_service):
        from db.database import close_connection
        try:
            return function(*args, service=active_service, **kwargs)
        finally:
            close_connection()
    if service is None:
        return await asyncio.to_thread(local, None)
    async with AsyncModelService(service.config, transport=transport, progress=progress) as remote:
        bridge = AsyncBridge(remote, asyncio.get_running_loop(), stream=stream)
        worker = asyncio.create_task(asyncio.to_thread(local, bridge))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            bridge.cancel()
            # Drain the local bounded loop so pending plans/session flags and SQLite
            # connection lifetime finish before callers reuse the session.
            try:
                await asyncio.shield(worker)
            except Exception:
                pass
            raise


async def arun_agent(query, index, service=None, **kwargs):
    from .agent.runner import run_agent
    if not kwargs.get('allow_model_calls'):
        service = None
    return await invoke_async(run_agent, query, index, service=service, **kwargs)


async def aask(index, query, scope='通用', service=None, *, use_embeddings=False, **kwargs):
    from .generation import ask
    def question(active_index, text, *, service, **options):
        return ask(active_index, text, scope, service=service,
                   embeddings=service if use_embeddings else None, **options)
    return await invoke_async(question, index, query, service=service, **kwargs)


async def aask_manual(index, query, service=None, **kwargs):
    from .manual import ask_manual
    return await invoke_async(ask_manual, index, query, service=service, **kwargs)
