"""
档案著录工序桌面工具 - 程序入口
"""
import sys
import os
import io
from datetime import datetime
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread


class _TeeWriter:
    """分流输出：同时写入"原终端"和 debug.log 日志文件（UTF-8 缓冲）"""

    def __init__(self, original_stream, log_file_path, mode='a', encoding='utf-8'):
        self._original = original_stream
        try:
            dir_name = os.path.dirname(log_file_path)
            if dir_name and not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)
            self._log_file = io.open(log_file_path, mode=mode, encoding=encoding, buffering=1)
            self._ok = True
        except Exception:
            self._log_file = None
            self._ok = False

    @property
    def original(self):
        return self._original

    def write(self, data):
        try:
            self._original.write(data)
            self._original.flush()
        except Exception:
            pass
        if self._ok:
            try:
                self._log_file.write(data)
                self._log_file.flush()
            except Exception:
                pass

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        if self._ok:
            try:
                self._log_file.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False

    def close(self):
        try:
            self._original.close()
        except Exception:
            pass
        if self._ok and self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._original, name)


def _setup_debug_log():
    """最早期重定向 stdout/stderr 到 debug.log（窗口化打包后没有终端，所有输出都会落到该文件）"""
    try:
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, 'debug.log')

        sep = "\n" + ("=" * 80) + "\n"
        header = f"=== 运行启动 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | " \
                 f"Python {sys.version.split()[0]} | {'FROZEN EXE' if getattr(sys, 'frozen', False) else 'SOURCE'} ===\n"

        stdout_tee = _TeeWriter(sys.__stdout__, log_path, mode='a', encoding='utf-8')
        stderr_tee = _TeeWriter(sys.__stderr__, log_path, mode='a', encoding='utf-8')

        stdout_tee.write(sep + header)
        stderr_tee.write(sep + f"=== STDERR 捕获启动 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

        sys.stdout = stdout_tee
        sys.stderr = stderr_tee
    except Exception:
        pass


class _OCRWarmupThread(QThread):
    """OCR引擎预热线程"""
    def run(self):
        from ui.components.ocr.ocr_worker import OCRWorker
        OCRWorker._probe_available_engine()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 使用Fusion样式，确保QSS在Windows上完整生效
    app.setStyle("Fusion")

    # 调亮调色板，消除 Windows Fusion 样式下 QComboBox 弹窗的黑色底框
    from PySide6.QtGui import QPalette, QColor
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#FFFFFF"))
    palette.setColor(QPalette.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.Dark, QColor("#D1D5DB"))
    palette.setColor(QPalette.Shadow, QColor("#D1D5DB"))
    palette.setColor(QPalette.Mid, QColor("#D1D5DB"))
    palette.setColor(QPalette.Midlight, QColor("#E5E9EC"))
    palette.setColor(QPalette.Light, QColor("#F0F3F4"))
    app.setPalette(palette)

    # 初始化数据库
    from db.database import init_database
    init_database()

    # 初始化标准词库
    from core.vocabulary_manager import init_default_vocabulary
    init_default_vocabulary()

    # 初始化模板
    from core.template_manager import TemplateManager
    template_manager = TemplateManager()
    template_manager.init_database_templates()

    # 加载样式
    from config.settings import get_resource_path
    style_file = get_resource_path('ui/styles/theme.qss')
    if style_file.exists():
        with open(style_file, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())

    # 后台预热OCR引擎
    ocr_warmup = _OCRWarmupThread()
    ocr_warmup.start()

    # 创建并显示主窗口
    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    # 运行应用
    result = app.exec()

    # 等待OCR预热线程结束
    if ocr_warmup.isRunning():
        ocr_warmup.wait(3000)

    sys.exit(result)


if __name__ == '__main__':
    _setup_debug_log()
    main()