import os
import io
import tempfile
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QSplitter, QFrame, QWidget, QFileDialog,
    QListView, QApplication, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent

from .ocr_worker import OCRWorker
from .region_selector import RegionSelector


class OCRDialog(QDialog):
    fill_requested = Signal(str, str)   # field_name/col_name, value

    _VALID_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".pdf"}

    def __init__(self, parent=None, headers: list = None, target_field: str = "", field_list: list = None):
        super().__init__(parent)
        self.setWindowTitle("OCR 图片识别")
        self.setMinimumSize(960, 600)
        self.setModal(False)
        
        self._headers = headers or []          # Excel模式：列名列表
        self._target_field = target_field      # Entry模式：默认目标字段
        self._field_list = field_list or []    # Entry模式：可选择的字段列表
        self._image_path = ""
        self._ocr_image_path = ""
        self._orig_pixmap = None
        self._ocr_worker = None
        self._tmp_paths = []
        self._is_append = True
        self._ocr_running = False
        
        self._init_ui()
        self._apply_style()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部工具栏
        toolbar = QWidget()
        toolbar.setObjectName("ocrToolbar")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(12, 7, 12, 7)
        tb.setSpacing(8)

        self._sel_btn = QPushButton("📂 选择文件")
        self._sel_btn.setObjectName("ocrToolBtn")
        self._sel_btn.setFixedHeight(30)
        self._sel_btn.clicked.connect(self._select_file)
        tb.addWidget(self._sel_btn)

        self._full_btn = QPushButton("🔍 整图识别")
        self._full_btn.setObjectName("ocrPrimaryBtn")
        self._full_btn.setFixedHeight(30)
        self._full_btn.setEnabled(False)
        self._full_btn.clicked.connect(self._run_full_ocr)
        tb.addWidget(self._full_btn)

        # 当前字段提示（Entry模式）
        if self._target_field:
            self._field_lbl = QLabel(f"当前字段：{self._target_field}")
            self._field_lbl.setObjectName("ocrFieldLbl")
            tb.addWidget(self._field_lbl)

        self._hint_lbl = QLabel("① 载入图片  ② 拖拽框选区域  ③ 填入字段")
        self._hint_lbl.setObjectName("ocrHintLbl")
        tb.addWidget(self._hint_lbl)

        tb.addStretch()

        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("ocrStatusLbl")
        self._status_lbl.setMinimumWidth(200)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tb.addWidget(self._status_lbl)

        root.addWidget(toolbar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("ocrSep")
        root.addWidget(sep)

        # 主体区（水平分割器）
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)
        splitter.setObjectName("ocrSplitter")

        # 左侧：图片框选区
        left = QWidget()
        left.setObjectName("ocrLeft")
        l_lay = QVBoxLayout(left)
        l_lay.setContentsMargins(0, 0, 0, 0)
        l_lay.setSpacing(0)

        self._selector = RegionSelector(self)
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.region_previewing.connect(self._on_region_preview)
        self._selector.setObjectName("ocrSelector")
        l_lay.addWidget(self._selector, stretch=1)

        splitter.addWidget(left)

        # 右侧：结果面板
        right = QWidget()
        right.setObjectName("ocrRight")
        right.setMinimumWidth(280)
        r_lay = QVBoxLayout(right)
        r_lay.setContentsMargins(10, 10, 10, 10)
        r_lay.setSpacing(10)

        # 标题行
        hdr = QHBoxLayout()
        res_title = QLabel("识别结果")
        res_title.setObjectName("ocrResTitle")
        hdr.addWidget(res_title)
        hdr.addStretch()
        self._copy_btn = QPushButton("📋 复制")
        self._copy_btn.setObjectName("ocrSmallBtn")
        self._copy_btn.setFixedHeight(24)
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_result)
        hdr.addWidget(self._copy_btn)
        clear_btn = QPushButton("✕ 清空")
        clear_btn.setObjectName("ocrSmallBtn")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._clear_result)
        hdr.addWidget(clear_btn)
        r_lay.addLayout(hdr)

        # 结果文本框 —— 吃掉所有剩余空间
        self._result_edit = QTextEdit()
        self._result_edit.setObjectName("ocrResultEdit")
        self._result_edit.setMinimumHeight(140)
        self._result_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._result_edit.setPlaceholderText(
            "在左侧图片上拖拽框选区域\n识别结果会自动显示在这里\n\n"
            "可直接在此编辑后再填入"
        )
        self._result_edit.textChanged.connect(self._on_result_changed)
        r_lay.addWidget(self._result_edit, stretch=1)   # 关键：stretch=1

        # 追加/替换模式 —— 固定高度，不参与拉伸
        mode_wrap = QWidget()
        mode_wrap.setObjectName("ocrModeWrap")
        mode_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)  # 关键
        mode_inner = QHBoxLayout(mode_wrap)
        mode_inner.setContentsMargins(8, 6, 8, 6)
        mode_inner.setSpacing(6)
        mode_lbl = QLabel("框选追加到：")
        mode_lbl.setObjectName("ocrModeLabel")
        mode_inner.addWidget(mode_lbl)
        self._append_btn = QPushButton("结果末尾")
        self._append_btn.setCheckable(True)
        self._append_btn.setChecked(True)
        self._append_btn.setFixedHeight(26)
        self._append_btn.setObjectName("ocrModeBtn")
        self._replace_btn = QPushButton("替换全部")
        self._replace_btn.setCheckable(True)
        self._replace_btn.setChecked(False)
        self._replace_btn.setFixedHeight(26)
        self._replace_btn.setObjectName("ocrModeBtn")
        self._append_btn.clicked.connect(lambda: self._set_append_mode(True))
        self._replace_btn.clicked.connect(lambda: self._set_append_mode(False))
        mode_inner.addWidget(self._append_btn)
        mode_inner.addWidget(self._replace_btn)
        mode_inner.addStretch()
        r_lay.addWidget(mode_wrap, stretch=0)

        # 填入目标列/字段
        if self._headers:
            col_wrap = QWidget()
            col_wrap.setObjectName("ocrColWrap")
            col_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)  # 关键
            col_inner = QHBoxLayout(col_wrap)
            col_inner.setContentsMargins(8, 6, 8, 6)
            col_inner.setSpacing(8)
            col_lbl = QLabel("填入列")
            col_lbl.setObjectName("ocrColLabel")
            col_inner.addWidget(col_lbl)
            self._col_combo = QComboBox()
            self._col_combo.setView(QListView())
            self._col_combo.setObjectName("ocrColCombo")
            self._col_combo.setFixedHeight(28)
            self._col_combo.addItems(self._headers)
            col_inner.addWidget(self._col_combo, stretch=1)
            r_lay.addWidget(col_wrap, stretch=0)
        elif self._field_list:
            field_wrap = QWidget()
            field_wrap.setObjectName("ocrColWrap")
            field_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)  # 关键
            field_inner = QHBoxLayout(field_wrap)
            field_inner.setContentsMargins(8, 6, 8, 6)
            field_inner.setSpacing(8)
            field_lbl = QLabel("填入字段")
            field_lbl.setObjectName("ocrColLabel")
            field_inner.addWidget(field_lbl)
            self._field_combo = QComboBox()
            self._field_combo.setView(QListView())
            self._field_combo.setObjectName("ocrColCombo")
            self._field_combo.setFixedHeight(28)
            self._field_combo.addItems(self._field_list)
            if self._target_field and self._target_field in self._field_list:
                self._field_combo.setCurrentText(self._target_field)
            field_inner.addWidget(self._field_combo, stretch=1)
            r_lay.addWidget(field_wrap, stretch=0)

        # 填入按钮 —— 固定高度，作为底部主操作按钮
        btn_text = "→ 填入" + (f"「{self._target_field}」" if self._target_field else "当前字段")
        self._fill_btn = QPushButton(btn_text)
        self._fill_btn.setObjectName("ocrFillBtn")
        self._fill_btn.setFixedHeight(36)
        self._fill_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)  # 关键
        self._fill_btn.setEnabled(False)
        self._fill_btn.clicked.connect(self._on_fill)
        r_lay.addWidget(self._fill_btn, stretch=0)

        splitter.addWidget(right)
        splitter.setSizes([620, 340])
        root.addWidget(splitter, stretch=1)

        self.setAcceptDrops(True)

    def _set_append_mode(self, append: bool):
        self._is_append = append
        self._append_btn.setChecked(append)
        self._replace_btn.setChecked(not append)
        self._append_btn.setProperty("active", append)
        self._replace_btn.setProperty("active", not append)
        self._append_btn.style().unpolish(self._append_btn)
        self._append_btn.style().polish(self._append_btn)
        self._replace_btn.style().unpolish(self._replace_btn)
        self._replace_btn.style().polish(self._replace_btn)

    def _select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片或 PDF", "",
            "图片/PDF (*.png *.jpg *.jpeg *.bmp *.tiff *.pdf)"
        )
        if path:
            self._load_image(path)

    def _load_image(self, path: str):
        if not os.path.exists(path):
            return

        self._cleanup_tmp()

        self._image_path = path
        pixmap = QPixmap()
        ext = os.path.splitext(path)[1].lower()

        if ext == ".pdf":
            # OCR 使用原始 PDF 路径（PaddleOCR 3.x 支持直接处理 PDF）
            self._ocr_image_path = path
            try:
                import fitz
                doc = fitz.open(path)
                if doc.page_count > 0:
                    mat = fitz.Matrix(4, 4)
                    pix = doc[0].get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")

                    buf = io.BytesIO(img_bytes)
                    pixmap.loadFromData(buf.getvalue())
                else:
                    doc.close()
                    self._set_status("❌ PDF 无页面")
                    return
                doc.close()
            except ImportError:
                self._set_status("⚠ 需安装 PyMuPDF 才能预览 PDF")
                return
            except Exception as e:
                self._set_status(f"❌ PDF 加载失败: {str(e)[:50]}")
                return
        else:
            pixmap.load(path)
            self._ocr_image_path = path

        if pixmap.isNull():
            self._set_status("❌ 图片加载失败")
            return

        self._orig_pixmap = pixmap
        self._selector.set_pixmap(pixmap)
        self._full_btn.setEnabled(True)
        fname = os.path.basename(path)
        w, h = pixmap.width(), pixmap.height()
        size_kb = os.path.getsize(path) // 1024
        self._set_status(f"📄 {fname}  {w}×{h}px  {size_kb}KB")
        self._hint_lbl.setText("在图片上拖拽框选要识别的区域  →  松手自动识别")

    def _on_region_preview(self, rect: QRect):
        if not self._orig_pixmap or rect.width() < 5 or rect.height() < 5:
            return
        self._set_status(f"🖱️  选区：{rect.width()} × {rect.height()} px  -  松手自动识别")

    def _on_region_selected(self, rect: QRect):
        if not self._orig_pixmap or rect.width() < 5 or rect.height() < 5:
            return
        if self._ocr_running:
            self._set_status("⚠ 上一次识别仍在进行，请稍候")
            return

        cropped = self._orig_pixmap.copy(rect)
        if cropped.isNull():
            self._set_status("❌ 裁剪图像失败")
            return

        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            tmp_path = tmp.name
            cropped.save(tmp_path)
            self._tmp_paths.append(tmp_path)

            w, h = rect.width(), rect.height()
            self._set_status(f"🔄 识别中…  框选区域 {w} × {h} px")
            self._full_btn.setEnabled(False)
            self._ocr_running = True

            worker = OCRWorker(tmp_path)
            worker.finished.connect(lambda text: self._on_region_done(text, tmp_path))
            worker.error.connect(self._on_ocr_error)
            worker.progress.connect(lambda m: self._set_status(f"🔄 {m}"))
            self._ocr_worker = worker
            worker.start()

        except Exception as e:
            self._set_status(f"❌ 图像处理失败: {str(e)[:50]}")
            self._ocr_running = False
            self._full_btn.setEnabled(True)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _on_region_done(self, text: str, tmp_path: str):
        self._ocr_running = False
        self._full_btn.setEnabled(True)
        try:
            os.unlink(tmp_path)
            self._tmp_paths = [p for p in self._tmp_paths if p != tmp_path]
        except Exception:
            pass

        text = text.strip()
        if not text:
            self._set_status("⚠ 未识别到文字，请重新框选（尝试更大范围）")
            return

        self._write_result(text)
        lines = len([l for l in text.splitlines() if l.strip()])
        chars = len(text.replace("\n", ""))
        self._set_status(f"✅ 识别完成  {lines} 行 · {chars} 字")
        self._selector.clear_selection()

    def _run_full_ocr(self):
        if not self._ocr_image_path or self._ocr_running:
            return
        self._full_btn.setEnabled(False)
        self._full_btn.setText("识别中…")
        self._set_status("🔄 正在识别整图，请稍候…")
        self._ocr_running = True

        worker = OCRWorker(self._ocr_image_path)
        worker.finished.connect(self._on_full_done)
        worker.error.connect(self._on_ocr_error)
        worker.progress.connect(lambda m: self._set_status(f"🔄 {m}"))
        self._ocr_worker = worker
        worker.start()

    def _on_full_done(self, text: str):
        self._ocr_running = False
        self._full_btn.setEnabled(True)
        self._full_btn.setText("🔍 整图识别")
        self._cleanup_tmp()
        text = text.strip()
        if text:
            self._write_result(text)
            lines = len([l for l in text.splitlines() if l.strip()])
            self._set_status(f"✅ 整图识别完成  {lines} 行")
        else:
            self._set_status("⚠ 未识别到文字，图片可能不含文字内容")

    def _on_ocr_error(self, msg: str):
        self._ocr_running = False
        self._full_btn.setEnabled(True)
        self._full_btn.setText("🔍 整图识别")
        self._cleanup_tmp()
        if "未找到可用" in msg:
            self._result_edit.setPlainText(msg)
            self._set_status("❌ 未找到 OCR 引擎，请安装")
        else:
            self._set_status(f"❌ 识别失败：{msg[:50]}")

    def _cleanup_tmp(self):
        # 如果 OCR 正在运行，不清理临时文件，避免删除正在使用的文件
        if getattr(self, '_ocr_running', False):
            return
        for path in self._tmp_paths[:]:
            try:
                os.unlink(path)
                self._tmp_paths.remove(path)
            except Exception:
                pass

    def _write_result(self, text: str):
        if self._is_append:
            existing = self._result_edit.toPlainText().strip()
            combined = (existing + "\n" + text) if existing else text
            self._result_edit.setPlainText(combined)
        else:
            self._result_edit.setPlainText(text)
        cur = self._result_edit.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self._result_edit.setTextCursor(cur)

    def _on_result_changed(self):
        has_text = bool(self._result_edit.toPlainText().strip())
        # 有列列表或字段列表时允许填入
        has_target = bool(self._headers) or bool(self._field_list) or True
        self._fill_btn.setEnabled(has_text and has_target)
        self._copy_btn.setEnabled(has_text)
        
        # 更新按钮文本
        if self._headers:
            btn_text = "→ 填入「" + self._col_combo.currentText() + "」"
        elif self._field_list:
            if hasattr(self, '_field_combo'):
                btn_text = "→ 填入「" + self._field_combo.currentText() + "」"
            else:
                btn_text = "→ 填入" + (f"「{self._target_field}」" if self._target_field else "当前字段")
        else:
            btn_text = "→ 填入" + (f"「{self._target_field}」" if self._target_field else "当前字段")
        self._fill_btn.setText(btn_text)

    def _clear_result(self):
        self._result_edit.clear()
        self._fill_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)

    def _on_fill(self):
        text = self._result_edit.toPlainText().strip()
        if not text:
            return

        if self._headers:
            col_name = self._col_combo.currentText()
            self.fill_requested.emit(col_name, text)
            self._set_status(f"✅ 已填入「{col_name}」列")
        elif self._field_list:
            # Entry模式：从下拉框获取选中的字段
            if hasattr(self, '_field_combo'):
                field_name = self._field_combo.currentText()
                self.fill_requested.emit(field_name, text)
                self._set_status(f"✅ 已填入「{field_name}」字段")
            else:
                field_name = self._target_field if self._target_field else ""
                self.fill_requested.emit(field_name, text)
                if self._target_field:
                    self._set_status(f"✅ 已填入「{self._target_field}」")
                else:
                    self._set_status("✅ 已复制到剪贴板，可手动粘贴")
        else:
            # 旧版Entry模式：直接使用目标字段
            field_name = self._target_field if self._target_field else ""
            self.fill_requested.emit(field_name, text)
            if self._target_field:
                self._set_status(f"✅ 已填入「{self._target_field}」")
            else:
                self._set_status("✅ 已复制到剪贴板，可手动粘贴")

    def _copy_result(self):
        text = self._result_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._set_status("✅ 已复制到剪贴板")

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            ext = os.path.splitext(event.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in self._VALID_EXTS:
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self._load_image(urls[0].toLocalFile())

    def closeEvent(self, event):
        self._cleanup_tmp()
        super().closeEvent(event)

    def _apply_style(self):
        self.setStyleSheet("""
        QDialog { background:#FFFFFF; font-family:"Microsoft YaHei"; }

        QWidget#ocrToolbar {
            background:#F8FAFC;
            border-bottom:1px solid #E9ECF0;
        }
        QFrame#ocrSep { background:#E9ECF0; border:none; max-height:1px; }

        QPushButton#ocrToolBtn {
            background:#F1F5F9; border:1px solid #E2E8F0; border-radius:7px;
            font-size:12px; color:#374151; padding:0 10px;
        }
        QPushButton#ocrToolBtn:hover { background:#E2E8F0; }

        QPushButton#ocrPrimaryBtn {
            background:#7C3AED; border:none; border-radius:7px;
            font-size:12px; font-weight:bold; color:white; padding:0 16px;
        }
        QPushButton#ocrPrimaryBtn:hover { background:#6D28D9; }
        QPushButton#ocrPrimaryBtn:disabled { background:#DDD6FE; color:#A78BFA; }

        QLabel#ocrFieldLbl { font-size:12px; color:#7C3AED; font-weight:bold; }
        QLabel#ocrHintLbl { font-size:11px; color:#94A3B8; }
        QLabel#ocrStatusLbl { font-size:11px; color:#6B7280; }

        QWidget#ocrLeft { background:#F1F5F9; }
        QWidget#ocrSelector { background:#F1F5F9; }

        QWidget#ocrRight {
            background:#FFFFFF;
            border-left:1px solid #E9ECF0;
        }

        QLabel#ocrResTitle { font-size:13px; font-weight:bold; color:#1E293B; }

        QPushButton#ocrSmallBtn {
            background:#F1F5F9; border:1px solid #E2E8F0; border-radius:5px;
            font-size:11px; color:#6B7280; padding:0 10px;
        }
        QPushButton#ocrSmallBtn:hover { background:#E2E8F0; }

        QTextEdit#ocrResultEdit {
            border:1px solid #E2E8F0; border-radius:8px;
            padding:6px; font-size:12px; color:#374151;
            background:white; font-family:"Microsoft YaHei";
            line-height:1.4;
            min-height: 0px;
            max-height: 16777215px;   /* 覆盖全局 max-height:26px 限制 */
        }
        QTextEdit#ocrResultEdit:focus { border-color:#3B82F6; }

        QWidget#ocrModeWrap {
            background:#F8FAFC; border:1px solid #E9ECF0; border-radius:7px;
        }
        QLabel#ocrModeLabel { font-size:11px; color:#9CA3AF; }

        QPushButton#ocrModeBtn {
            background:#F1F5F9; border:1px solid #E5E7EB;
            border-radius:5px; font-size:11px; color:#9CA3AF; padding:0 10px;
        }
        QPushButton#ocrModeBtn:checked {
            background:#EFF6FF; border-color:#93C5FD; color:#1D4ED8; font-weight:bold;
        }
        QPushButton#ocrModeBtn:hover:!checked { background:#F3F4F6; color:#374151; }

        QWidget#ocrColWrap {
            background:#F0FDF4; border:1px solid #BBF7D0; border-radius:7px;
        }
        QLabel#ocrColLabel {
            font-size:12px; color:#065F46; font-weight:bold;
        }
        QComboBox#ocrColCombo {
            border:1px solid #BBF7D0; border-radius:6px;
            padding:4px 8px; font-size:12px; background:white; color:#065F46;
        }
        QComboBox#ocrColCombo::drop-down { border:none; }

        QPushButton#ocrFillBtn {
            background:#10B981; border:none; border-radius:8px;
            font-size:13px; font-weight:bold; color:white;
        }
        QPushButton#ocrFillBtn:hover { background:#059669; }
        QPushButton#ocrFillBtn:disabled {
            background:#D1FAE5; color:#6EE7B7;
        }

        QSplitter#ocrSplitter::handle { background:#E9ECF0; width:4px; }
        """)

    def set_target_field(self, field_name: str):
        """设置当前目标字段（用于Entry模式）"""
        self._target_field = field_name
        if hasattr(self, '_field_lbl'):
            self._field_lbl.setText(f"当前字段：{field_name}")
        if hasattr(self, '_fill_btn'):
            self._fill_btn.setText(f"→ 填入{field_name}")
