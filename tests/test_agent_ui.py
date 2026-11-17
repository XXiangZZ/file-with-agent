import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget
import pytest


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_agent_dialog_runs_local_tool_without_model_calls(app, tmp_path, monkeypatch):
    from ui.components import assistant_dialog as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ui, "load_config", lambda path: {"chat_model": "unused"})

    def forbidden_service(_):
        raise AssertionError("model transport must not be constructed")

    monkeypatch.setattr(ui, "ModelService", forbidden_service)

    class Entry(QWidget):
        current_template = {"name": "文书"}
        current_batch_id = None

    dialog = ui.AssistantDialog(Entry())
    dialog.agent_mode.setCurrentIndex(1)
    dialog.local_tool.setCurrentIndex(dialog.local_tool.findData("kb_sources"))
    dialog.question.setText("查看资料状态")
    dialog.ask()
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if dialog.worker and not dialog.worker.isRunning() else None)
    timer.start(10)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    assert "本地只读工具模式" in dialog.status.text()
    assert "未调用外部模型" in dialog.output.toPlainText()
    assert dialog.plan_list.count() == 0
    dialog.reject()


def test_ui_uses_async_work_and_only_publishes_verified_body(app, tmp_path, monkeypatch):
    import asyncio
    from ui.components import assistant_dialog as ui
    from assistant import async_api
    monkeypatch.setattr(ui, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(ui, 'load_config', lambda _: {'chat_model': 'fake'})
    class Entry(QWidget):
        current_template = {'name': '文书'}
        current_batch_id = None
    entry = Entry()
    dialog = ui.AssistantDialog(entry)
    dialog.agent_mode.setCurrentIndex(1)
    dialog.external.setChecked(True)
    dialog.remember.setChecked(True)
    safe_text = '已核验的原文证据。'
    async def fake(query, index, service, **kwargs):
        assert kwargs['stream'] and kwargs['session'] is dialog.session
        kwargs['progress']({'type': 'receiving', 'chars': 20})
        await asyncio.sleep(.005)
        return {'answer': safe_text, 'verified_answer': safe_text, 'citations': [], 'plans': [],
                'tool_calls': 1, 'mode': '异步受控工具模式'}
    monkeypatch.setattr(async_api, 'arun_agent', fake)
    dialog.question.setText('问题')
    chunks = []
    dialog.ask()
    dialog.worker.verified_chunk.connect(chunks.append)
    loop = QEventLoop()
    dialog.worker.finished.connect(loop.quit)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    app.processEvents()
    assert ''.join(chunks) == safe_text
    assert dialog.output.toPlainText() == safe_text
    assert not dialog.cancel_button.isEnabled()
    dialog.session.turns.append(('问题', '临时记忆'))
    dialog.reject()
    assert dialog.session.turns == []
