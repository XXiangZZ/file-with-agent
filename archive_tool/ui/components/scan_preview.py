import fitz  # pymupdf
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QSlider, QFileDialog
)
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont, QFontMetrics

class ScanPreview(QWidget):
    region_selected = Signal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None           # 当前显示的页面图片
        self._pdf_doc = None          # fitz.Document 对象
        self._pdf_pages = []          # 各页渲染后的 QPixmap 列表
        self._current_page = 0
        self._total_pages = 0
        self._ocr_mode = False
        self._selecting = False
        self._selection_start = QPoint()
        self._selection_rect = QRect()
        self._cropped_bytes = None
        self._cropped_pixmap = None   # 裁剪后的 QPixmap（用于后续转 bytes）
        self._scale = 1.0
        self._auto_fit = True
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("background: #F9FAFB; border-bottom: 1px solid #E5E7EB;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 0, 10, 0)
        tb_layout.setSpacing(0)

        btn_style = """
        QPushButton {
            border: none; border-radius: 4px;
            padding: 0 8px; color: #374151;
            background: transparent; font-size: 12px;
        }
        QPushButton:hover { background: #E5E7EB; }
        QPushButton:pressed { background: #D1D5DB; }
        QPushButton:disabled { color: #D1D5DB; }
        """

        self.open_btn = QPushButton("📂 打开文件")
        self.open_btn.setFixedSize(96, 28)
        self.open_btn.setStyleSheet(btn_style)
        self.open_btn.clicked.connect(self._open_file)
        tb_layout.addWidget(self.open_btn)

        tb_layout.addStretch()

        self.prev_btn = QPushButton("‹")
        self.prev_btn.setFixedSize(32, 28)
        self.prev_btn.setStyleSheet(btn_style)
        self.prev_btn.clicked.connect(self._prev_page)
        self.prev_btn.hide()
        tb_layout.addWidget(self.prev_btn)

        tb_layout.addSpacing(6)

        self.page_label = QLabel("1 / 1")
        self.page_label.setFixedSize(56, 28)
        self.page_label.setStyleSheet("font-size: 12px; color: #6B7280;")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.hide()
        tb_layout.addWidget(self.page_label)

        tb_layout.addSpacing(6)

        self.next_btn = QPushButton("›")
        self.next_btn.setFixedSize(32, 28)
        self.next_btn.setStyleSheet(btn_style)
        self.next_btn.clicked.connect(self._next_page)
        self.next_btn.hide()
        tb_layout.addWidget(self.next_btn)

        self.ocr_status_label = QLabel("")
        self.ocr_status_label.setFixedHeight(28)
        self.ocr_status_label.setStyleSheet("font-size: 12px; color: #F59E0B; padding: 0 8px;")
        self.ocr_status_label.setAlignment(Qt.AlignCenter)
        self.ocr_status_label.hide()
        tb_layout.addWidget(self.ocr_status_label)

        tb_layout.addStretch()

        

        tb_layout.addSpacing(4)

        self.zoom_out_btn = QPushButton("－")
        self.zoom_out_btn.setFixedSize(28, 28)
        self.zoom_out_btn.setStyleSheet(btn_style + "font-size: 20px;")
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_out_btn.setToolTip("缩小")
        tb_layout.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedSize(44, 28)
        self.zoom_label.setStyleSheet("font-size: 12px; color: #374151;")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        tb_layout.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton("＋")
        self.zoom_in_btn.setFixedSize(28, 28)
        self.zoom_in_btn.setStyleSheet(btn_style + "font-size: 20px;")
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.zoom_in_btn.setToolTip("放大")
        tb_layout.addWidget(self.zoom_in_btn)

        layout.addWidget(toolbar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("background: #ffffff;")

        self.image_label = _SelectableImageLabel(self)
        self.image_label.region_selected.connect(self._on_region_selected)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area, stretch=1)
        
        self._resize_timer = None

        self.ocr_hint = QLabel("🔲 OCR模式：在图片上拖拽框选要识别的区域")
        self.ocr_hint.setStyleSheet("""
            background: #FEF3C7; color: #92400E;
            padding: 4px 10px; font-size: 12px;
            border-top: 1px solid #FCD34D;
        """)
        self.ocr_hint.setAlignment(Qt.AlignCenter)
        self.ocr_hint.hide()
        layout.addWidget(self.ocr_hint)

    def _open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "打开文件", "",
            "所有支持的文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.pdf *.docx *.doc *.xlsx *.xls *.txt *.rtf);;"
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
            "PDF文件 (*.pdf);;"
            "Word文件 (*.docx *.doc);;"
            "Excel文件 (*.xlsx *.xls);;"
            "文本文件 (*.txt *.rtf)"
        )
        if paths:
            self.load_files(paths)

    def load_files(self, paths: list):
        self._pdf_doc = None
        self._pdf_pages.clear()
        self._current_page = 0

        for path in paths:
            lower_path = path.lower()
            if lower_path.endswith(".pdf"):
                self._load_pdf(path)
            elif lower_path.endswith((".docx", ".doc")):
                self._load_word(path)
            elif lower_path.endswith((".xlsx", ".xls")):
                self._load_excel(path)
            elif lower_path.endswith((".txt", ".rtf")):
                self._load_text(path)
            else:
                self._load_image(path)

        if self._pdf_pages:
            self._current_page = 0
            self._set_pixmap(self._pdf_pages[0])
            if self._total_pages > 1:
                self._show_page_controls()
            else:
                self._hide_page_controls()
            self._update_page_label()

    def load_file(self, path: str):
        self.load_files([path])

    def _load_image(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self._pdf_pages.append(pixmap)
        self._total_pages = len(self._pdf_pages)

    def _load_pdf(self, path: str):
        try:
            doc = fitz.open(path)

            matrix = fitz.Matrix(2.0, 2.0)
            for page in doc:
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                qimage = QImage(
                    pix.samples, pix.width, pix.height,
                    pix.stride, QImage.Format_RGB888
                )
                self._pdf_pages.append(QPixmap.fromImage(qimage))

            self._total_pages = len(self._pdf_pages)

        except Exception as e:
            print(f"PDF加载失败: {e}")

    def _load_text(self, path: str):
        try:
            encodings = ['utf-8', 'gbk', 'gb2312', 'utf-16']
            content = None
            
            for encoding in encodings:
                try:
                    with open(path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                print(f"无法读取文件: {path}")
                return
            
            if not content.strip():
                return
            
            pixmap = self._text_to_pixmap(content)
            if pixmap:
                self._pdf_pages.append(pixmap)
                self._total_pages = len(self._pdf_pages)

        except Exception as e:
            print(f"文本文件加载失败: {e}")

    def _load_word(self, path: str):
        try:
            from docx import Document
            doc = Document(path)
            
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(para.text)
            
            if not paragraphs:
                return
            
            page_text = "\n".join(paragraphs)
            pixmap = self._text_to_pixmap(page_text)
            if pixmap:
                self._pdf_pages.append(pixmap)
                self._total_pages = len(self._pdf_pages)

        except ImportError:
            print("python-docx 模块未安装，请运行 pip install python-docx")
        except Exception as e:
            print(f"Word文件加载失败: {e}")

    def _load_excel(self, path: str):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                
                rows_data = []
                for row in ws.iter_rows(values_only=True):
                    row_str = "\t".join(str(cell) if cell is not None else "" for cell in row)
                    if row_str.strip():
                        rows_data.append(row_str)
                
                if rows_data:
                    sheet_text = f"【{sheet_name}】\n" + "\n".join(rows_data)
                    pixmap = self._text_to_pixmap(sheet_text)
                    if pixmap:
                        self._pdf_pages.append(pixmap)
            
            self._total_pages = len(self._pdf_pages)

        except Exception as e:
            print(f"Excel文件加载失败: {e}")

    def _text_to_pixmap(self, text: str) -> QPixmap:
        font = QFont("Microsoft YaHei", 12)
        font_metrics = QFontMetrics(font)
        
        max_width = 800
        lines = []
        for line in text.split("\n"):
            current_line = ""
            for char in line:
                test_line = current_line + char
                if font_metrics.horizontalAdvance(test_line) > max_width:
                    lines.append(current_line)
                    current_line = char
                else:
                    current_line = test_line
            if current_line:
                lines.append(current_line)
        
        line_height = font_metrics.height() + 4
        padding = 40
        image_width = max_width + padding * 2
        image_height = max(len(lines) * line_height + padding * 2, 200)
        
        image = QImage(image_width, image_height, QImage.Format_RGB888)
        image.fill(Qt.white)
        
        painter = QPainter(image)
        painter.setFont(font)
        painter.setPen(QColor(30, 30, 30))
        
        y = padding
        for line in lines:
            painter.drawText(padding, y + font_metrics.ascent(), line)
            y += line_height
        
        painter.end()
        
        return QPixmap.fromImage(image)

    def _set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._scale_to_fit()
        self._apply_zoom()
    
    def _scale_to_fit(self):
        """自动缩放到最佳视角，使图片适应预览区域"""
        if self._pixmap is None:
            return
        
        scroll_area_rect = self.scroll_area.contentsRect()
        available_width = scroll_area_rect.width() - 20
        available_height = scroll_area_rect.height() - 20
        
        if available_width <= 0 or available_height <= 0:
            self._scale = 0.8
            return
        
        pixmap_width = self._pixmap.width()
        pixmap_height = self._pixmap.height()
        
        scale_x = available_width / pixmap_width
        scale_y = available_height / pixmap_height
        
        self._scale = min(scale_x, scale_y)
        
        if self._scale < 0.1:
            self._scale = 0.1
        if self._scale > 3.0:
            self._scale = 3.0
    
    def resizeEvent(self, event):
        """响应预览区域大小变化，自动调整图片尺寸"""
        super().resizeEvent(event)
        if self._pixmap is not None:
            from PySide6.QtCore import QTimer, Qt
            if self._resize_timer:
                self._resize_timer.stop()
            self._resize_timer = QTimer.singleShot(100, self._on_resize_finished)
    
    def _on_resize_finished(self):
        """调整完成后重新计算缩放"""
        if self._pixmap is not None and self._auto_fit:
            self._scale_to_fit()
            self._apply_zoom()

    def _apply_zoom(self):
        if self._pixmap is None:
            return
        w = int(self._pixmap.width() * self._scale)
        h = int(self._pixmap.height() * self._scale)
        scaled = self._pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.set_pixmap(scaled)
        self.zoom_label.setText(f"{int(self._scale * 100)}%")

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._set_pixmap(self._pdf_pages[self._current_page])
            self._update_page_label()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._set_pixmap(self._pdf_pages[self._current_page])
            self._update_page_label()

    def _update_page_label(self):
        self.page_label.setText(f"{self._current_page + 1} / {self._total_pages}")
        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(self._current_page < self._total_pages - 1)

    def _show_page_controls(self):
        for w in (self.prev_btn, self.page_label, self.next_btn):
            w.show()

    def _hide_page_controls(self):
        for w in (self.prev_btn, self.page_label, self.next_btn):
            w.hide()

    def set_ocr_status(self, status):
        """设置OCR状态提示"""
        if status == 'recognizing':
            self.ocr_status_label.setText("正在识别...")
            self.ocr_status_label.setStyleSheet("font-size: 12px; color: #F59E0B; padding: 0 10px;")
            self.ocr_status_label.show()
        elif status == 'success':
            self.ocr_status_label.setText("识别成功")
            self.ocr_status_label.setStyleSheet("font-size: 12px; color: #10B981; padding: 0 10px;")
            self.ocr_status_label.show()
            # 3秒后隐藏成功提示
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._hide_ocr_status)
        elif status == 'error':
            self.ocr_status_label.setText("识别失败")
            self.ocr_status_label.setStyleSheet("font-size: 12px; color: #EF4444; padding: 0 10px;")
            self.ocr_status_label.show()
            # 3秒后隐藏失败提示
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._hide_ocr_status)
        else:
            self._hide_ocr_status()
    
    def _hide_ocr_status(self):
        """隐藏OCR状态提示"""
        self.ocr_status_label.hide()
        self.ocr_status_label.setText("")

    def _zoom_in(self):
        self._auto_fit = False
        if self._scale < 4.0:
            self._scale = round(self._scale + 0.25, 2)
            self._apply_zoom()

    def _zoom_out(self):
        self._auto_fit = False
        if self._scale > 0.25:
            self._scale = round(self._scale - 0.25, 2)
            self._apply_zoom()

    def enter_ocr_mode(self, field_name: str = ""):
        self._ocr_mode = True
        if hasattr(self, 'image_label') and self.image_label:
            self.image_label.set_ocr_mode(True)
        
        if hasattr(self, 'ocr_hint') and self.ocr_hint:
            if self._pixmap is not None:
                hint = f"🔲 OCR模式：框选图中【{field_name}】对应的文字区域" if field_name else "🔲 OCR模式：拖拽框选要识别的区域"
                self.ocr_hint.setText(hint)
                self.ocr_hint.show()
            else:
                self.ocr_hint.hide()

    def enable_ocr_mode(self, enabled: bool):
        self._ocr_mode = enabled
        self.image_label.set_ocr_mode(enabled)
        if not enabled:
            self.ocr_hint.hide()
            self.image_label.clear_selection()

    def clear_selection(self):
        self.image_label.clear_selection()

    def get_cropped_image_bytes(self) -> bytes | None:
        return self.image_label.get_cropped_bytes()

    def _on_region_selected(self, rect: QRect):
        self._cropped_bytes = self.image_label.get_cropped_bytes()
        self.region_selected.emit(rect)


class _SelectableImageLabel(QLabel):
    region_selected = Signal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap_orig = None
        self._ocr_mode = False
        self._selecting = False
        self._start = QPoint()
        self._end = QPoint()
        self._sel_rect = QRect()
        self._cropped_bytes = None
        self._cropped_pixmap = None   # 裁剪后的 QPixmap（用于后续转 bytes）
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setCursor(Qt.ArrowCursor)

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap_orig = pixmap
        self.setPixmap(pixmap)
        self.adjustSize()
        self._sel_rect = QRect()

    def set_ocr_mode(self, enabled: bool):
        self._ocr_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        if not enabled:
            self.clear_selection()

    def clear_selection(self):
        self._sel_rect = QRect()
        self._cropped_bytes = None
        self._cropped_pixmap = None
        self.update()

    def get_cropped_bytes(self) -> bytes | None:
        """将框选区域的 QPixmap 转为 PNG bytes（使用 QBuffer，兼容 PySide6）"""
        if self._cropped_pixmap is None:
            return None

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self._cropped_pixmap.save(buffer, "PNG")
        buffer.close()

        return bytes(byte_array)

    def mousePressEvent(self, event):
        if self._ocr_mode and event.button() == Qt.LeftButton:
            self._selecting = True
            self._start = event.position().toPoint()
            self._end = self._start
            self._sel_rect = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        if self._ocr_mode and self._selecting:
            self._end = event.position().toPoint()
            self._sel_rect = QRect(self._start, self._end).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._ocr_mode and self._selecting and event.button() == Qt.LeftButton:
            self._selecting = False
            self._end = event.position().toPoint()
            self._sel_rect = QRect(self._start, self._end).normalized()

            if self._sel_rect.width() > 5 and self._sel_rect.height() > 5:
                self._crop_region()
                self.region_selected.emit(self._sel_rect)
            self.update()

    def _crop_region(self):
        """裁剪选中区域，结果暂存为 QPixmap"""
        if self._pixmap_orig is None or self._sel_rect.isEmpty():
            self._cropped_pixmap = None
            return
        self._cropped_pixmap = self._pixmap_orig.copy(self._sel_rect)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._sel_rect.isEmpty():
            painter = QPainter(self)
            painter.fillRect(
                self._sel_rect,
                QColor(59, 130, 246, 50)
            )
            pen = QPen(QColor(59, 130, 246), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.drawRect(self._sel_rect)
            painter.end()