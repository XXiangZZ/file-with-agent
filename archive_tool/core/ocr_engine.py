import io
import sys
import os
import traceback
import numpy as np
from PIL import Image


# ──────────────────────────────────────────────
# 日志
# ──────────────────────────────────────────────
def log_ocr(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("gbk", errors="replace").decode("gbk"))
    except Exception:
        pass
    try:
        log_dir = os.path.dirname(sys.executable)
        log_file = os.path.join(log_dir, 'ocr_debug.log')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def _is_frozen():
    return getattr(sys, 'frozen', False)


def _meipass():
    return getattr(sys, '_MEIPASS', '')


# ──────────────────────────────────────────────
# 打包路径修正（必须在 import paddleocr 之前调用）
# ──────────────────────────────────────────────
def patch_paddlex_path():
    if not _is_frozen():
        return
    mp = _meipass()
    if not mp:
        return

    log_ocr(f"[OCR] _MEIPASS: {mp}")

    if mp not in sys.path:
        sys.path.insert(0, mp)


# ──────────────────────────────────────────────
# 找本地模型目录
# ──────────────────────────────────────────────
def get_model_dir():
    exe_dir = os.path.dirname(sys.executable)

    if _is_frozen():
        mp = _meipass()
        candidates = [
            os.path.join(exe_dir, 'models', 'paddleocr'),
            os.path.join(mp, 'models', 'paddleocr'),
            os.path.join(exe_dir, '_internal', 'models', 'paddleocr'),
        ]
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [os.path.join(project_root, 'models', 'paddleocr')]

    for i, p in enumerate(candidates, 1):
        exists = os.path.exists(p)
        log_ocr(f"[OCR] 检查模型路径{i}: {p} -> {'存在' if exists else '不存在'}")
        if exists:
            log_ocr(f"[OCR] 使用模型路径{i}: {p}")
            return p

    log_ocr("[OCR] 警告：未找到本地模型目录")
    return None


# ──────────────────────────────────────────────
# OCR 引擎
# ──────────────────────────────────────────────
class OCREngine:
    def __init__(self, use_gpu=False):
        self._ocr = None
        self._init_model(use_gpu)

    def _init_model(self, use_gpu):
        patch_paddlex_path()

        try:
            from paddleocr import PaddleOCR

            model_dir = get_model_dir()
            det_dir = rec_dir = cls_dir = None

            if model_dir:
                det_dir = os.path.join(model_dir, 'PP-OCRv6_medium_det')
                rec_dir = os.path.join(model_dir, 'PP-OCRv6_medium_rec')
                cls_dir = os.path.join(model_dir, 'PP-LCNet_x1_0_textline_ori')
                log_ocr(f"[OCR] 检测模型: {det_dir} -> {'存在' if os.path.exists(det_dir) else '缺失'}")
                log_ocr(f"[OCR] 识别模型: {rec_dir} -> {'存在' if os.path.exists(rec_dir) else '缺失'}")
                log_ocr(f"[OCR] 方向模型: {cls_dir} -> {'存在' if os.path.exists(cls_dir) else '缺失'}")

            params = {
                'use_angle_cls': True,
                'lang': 'ch',
            }
            
            if det_dir and os.path.exists(det_dir):
                params['det_model_dir'] = det_dir
            if rec_dir and os.path.exists(rec_dir):
                params['rec_model_dir'] = rec_dir
            if cls_dir and os.path.exists(cls_dir):
                params['cls_model_dir'] = cls_dir
            
            try:
                self._ocr = PaddleOCR(**params)
            except (TypeError, ValueError) as inst_e:
                try:
                    for key in ['use_gpu', 'show_log']:
                        params.pop(key, None)
                    self._ocr = PaddleOCR(**params)
                except Exception:
                    try:
                        self._ocr = PaddleOCR(lang='ch', use_angle_cls=True)
                    except Exception:
                        raise inst_e
            log_ocr("[OCR] PaddleOCR 初始化成功 ✓")

        except Exception as e:
            full_tb = traceback.format_exc()
            log_ocr(f"[OCR] PaddleOCR 初始化失败: {e}")
            log_ocr(f"[OCR] 完整 Traceback:\n{full_tb}")
            raise

    def _parse_result(self, result):
        texts = []
        if result and result[0]:
            for line in result[0]:
                if isinstance(line, list) and len(line) >= 2:
                    if isinstance(line[1], tuple) and len(line[1]) >= 2:
                        text, score = line[1][0], line[1][1]
                        if score > 0.6 and text:
                            texts.append(str(text))
                    elif isinstance(line[1], str):
                        texts.append(line[1])
        return " ".join(texts).strip()

    def _parse_structured(self, result):
        structured = []
        if result:
            for line in result:
                if isinstance(line, list) and len(line) >= 2:
                    bbox = line[0] if line[0] else None
                    if isinstance(line[1], tuple) and len(line[1]) >= 2:
                        text, score = line[1][0], line[1][1]
                        structured.append({"bbox": bbox, "text": text, "score": score})
                    elif isinstance(line[1], str):
                        structured.append({"bbox": bbox, "text": line[1], "score": 1.0})
        return structured

    def recognize_region(self, image_input, region_rect=None):

        # bytes
        if isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input)).convert("RGB")
            img_array = np.array(img)

        # path（关键修复点）
        elif isinstance(image_input, str):
            if not os.path.exists(image_input):
                raise FileNotFoundError(f"图片文件不存在: {image_input}")

            img = Image.open(image_input).convert("RGB")
            img_array = np.array(img)

        # numpy
        else:
            img_array = np.array(image_input)

        result = self._ocr.ocr(img_array, cls=True)

        return self._parse_result(result)

    def recognize_full_image(self, image_input):

        if isinstance(image_input, bytes):
            img_array = np.array(Image.open(io.BytesIO(image_input)).convert("RGB"))

        elif isinstance(image_input, str):

            # PDF
            if image_input.lower().endswith(".pdf"):
                images = self.pdf_to_images(image_input)
                all_results = []

                for img in images:
                    img_array = np.array(img.convert("RGB"))
                    result = self._ocr.ocr(img_array, cls=True)

                    if result and result[0]:
                        all_results.extend(result[0])

                return self._parse_structured(all_results)

            # 图片文件
            img_array = np.array(Image.open(image_input).convert("RGB"))

        else:
            img_array = np.array(image_input)

        result = self._ocr.ocr(img_array, cls=True)

        return self._parse_structured(result[0] if result and result[0] else [])

    def pdf_to_images(self, pdf_path, dpi=150):
        import fitz
        doc = fitz.open(pdf_path)
        images = []
        for page in doc:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
        return images