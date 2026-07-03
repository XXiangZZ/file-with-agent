import os
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker


class OCRWorker(QThread):
    """OCR识别工作线程 - 使用 PaddleOCR PP-OCRv6 Medium"""
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(str)

    _paddle_ocr = None
    _probe_done = False
    _probe_lock = QMutex()

    @classmethod
    def _probe_available_engine(cls):
        with QMutexLocker(cls._probe_lock):
            if cls._probe_done:
                return

            try:
                from core.ocr_engine import OCREngine
                if cls._paddle_ocr is None:
                    print("[OCR] 正在初始化 PaddleOCR (PP-OCRv6 Medium + ONNX)...")
                    cls._paddle_ocr = OCREngine(use_gpu=False)
                    print("[OCR] PaddleOCR 初始化成功")
            except Exception as e:
                print(f"[OCR] PaddleOCR 初始化失败: {e}")
                import traceback
                print(f"[OCR] 堆栈: {traceback.format_exc()}")
                cls._paddle_ocr = None

            cls._probe_done = True
            if cls._paddle_ocr is None:
                print("[OCR] 警告: PaddleOCR 初始化失败")

    def __init__(self, image_path: str):
        super().__init__()
        self.image_path = image_path

    def run(self):
        self._probe_available_engine()

        if OCRWorker._paddle_ocr is None:
            self.error.emit("OCR引擎初始化失败，请检查PaddleOCR是否正确安装")
            return

        self.progress.emit("使用 PaddleOCR PP-OCRv6 Medium 识别中...")

        try:
            text = OCRWorker._paddle_ocr.recognize_region(self.image_path)
            if text and text.strip():
                self.finished.emit(text.strip())
            else:
                self.error.emit("未识别到文字，请检查图片是否包含文字")
        except Exception as e:
            import traceback
            print(f"[OCR] 识别错误: {e}")
            print(f"[OCR] 堆栈: {traceback.format_exc()}")
            self.error.emit(f"OCR识别失败: {str(e)}")
