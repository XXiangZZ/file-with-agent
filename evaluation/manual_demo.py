"""Render a real Qt manual answer using a temporary index, for README preview."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from ui.components import manual_dialog as ui


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if font_path.exists():
        identity = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(identity)
        if families:
            app.setFont(QFont(families[0], 10))
    with tempfile.TemporaryDirectory() as tmp:
        ui.DATA_DIR = Path(tmp)
        ui.load_config = lambda path: {}  # Screenshot uses local mode only.
        dialog = ui.ManualDialog()
        dialog.show()
        def wait_idle():
            loop = QEventLoop()
            timer = QTimer()
            timer.timeout.connect(lambda: loop.quit() if dialog.worker and not dialog.worker.isRunning() else None)
            timer.start(10)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            timer.stop()
            app.processEvents()
            if dialog.worker and dialog.worker.isRunning():
                dialog.worker.wait()
                raise RuntimeError('Manual QA screenshot timed out')
        wait_idle()
        dialog.question.setText('如何导入Excel？')
        dialog.ask()
        wait_idle()
        if not dialog.last_result or not dialog.last_result['citations']:
            raise RuntimeError('No cited answer to show')
        dialog.output.moveCursor(dialog.output.textCursor().MoveOperation.Start)
        app.processEvents()
        output = ROOT / 'evaluation/manual_demo.png'
        if not dialog.grab().save(str(output)):
            raise RuntimeError('Cannot save screenshot')
        dialog.reject()
        print(output)


if __name__ == '__main__':
    main()
