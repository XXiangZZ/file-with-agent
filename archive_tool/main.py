"""
档案著录工序桌面工具 - 程序入口
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread


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

    # 记录启动日志
    from core.logger import Logger
    logger = Logger()
    logger.log('startup', {'version': 'V1.0'})

    # 运行应用
    result = app.exec()

    # 等待OCR预热线程结束
    if ocr_warmup.isRunning():
        ocr_warmup.wait(3000)

    sys.exit(result)


if __name__ == '__main__':
    main()