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
