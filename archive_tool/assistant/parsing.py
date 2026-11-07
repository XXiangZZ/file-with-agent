"""Page-preserving parsers; OCR is lazy and uses the existing engine."""
from pathlib import Path
from langchain_core.documents import Document


class Parser:
    def __init__(self, ocr=None):
        self.ocr = ocr

    def _recognize(self, image):
        if self.ocr is None:
            from core.ocr_engine import OCREngine, get_model_dir
            root = get_model_dir()
            expected = ('PP-OCRv6_medium_det', 'PP-OCRv6_medium_rec', 'PP-LCNet_x1_0_textline_ori')
            if not root or any(not any((Path(root) / name).glob('*.pdiparams')) for name in expected):
                raise RuntimeError('本地 OCR 权重缺失，请配置 ARCHIVE_OCR_MODEL_DIR 指向完整模型目录；不会自动下载模型')
            import os
            if os.name == 'nt' and not str(root).isascii():
                # Paddle 2.x native model loader cannot reliably open Chinese paths.
                import tempfile
                import shutil
                self._model_temp = tempfile.TemporaryDirectory(prefix='archive_ocr_')
                for name in expected:
                    shutil.copytree(Path(root) / name, Path(self._model_temp.name) / name)
                root = self._model_temp.name
            self.ocr = OCREngine(allow_download=False, model_dir=str(root))
        rows = self.ocr.recognize_full_image(image)
        return "\n".join(str(r['text']) for r in rows if r.get('text'))

    def parse(self, path, progress=lambda message: None):
        path = Path(path).resolve()
        pages = []
        suffix = path.suffix.lower()
        if suffix in {'.txt', '.md'}:
            # Explicit form feed is a page boundary in text fixtures.
            for number, text in enumerate(path.read_text(encoding='utf-8-sig').split('\f'), 1):
                pages.append((number, text, False))
        elif suffix == '.pdf':
            import fitz
            from PIL import Image
            with fitz.open(path) as pdf:
                for number, page in enumerate(pdf, 1):
                    progress(f'读取第 {number}/{len(pdf)} 页；扫描页 OCR 可能较慢')
                    text = page.get_text().strip()
                    scanned = not text
                    if scanned:
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        text = self._recognize(Image.frombytes('RGB', [pix.width, pix.height], pix.samples))
                    pages.append((number, text, scanned))
        elif suffix in {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}:
            from PIL import Image, ImageSequence
            with Image.open(path) as image:
                for number, frame in enumerate(ImageSequence.Iterator(image), 1):
                    progress(f'正在 OCR 第 {number} 页；请等待')
                    pages.append((number, self._recognize(frame.convert('RGB')), True))
        else:
            raise ValueError('仅支持 UTF-8 TXT/MD、PDF、PNG/JPEG/BMP/TIFF')
        docs = [Document(page_content=text.strip(), metadata={
            'source': str(path), 'page': page, 'ocr': ocr,
        }) for page, text, ocr in pages if text.strip()]
        if not docs:
            raise ValueError('没有解析出文本；原索引保持不变，请检查扫描质量或 OCR 模型')
        return docs
