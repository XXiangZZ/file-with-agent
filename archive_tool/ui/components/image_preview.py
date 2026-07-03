from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFileDialog, QFrame, QTextEdit
)
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PySide6.QtCore import Qt, Signal
from PIL import Image
import io


# ─────────────────────────────────────────────────────────────────────────────
#  小工具类
# ─────────────────────────────────────────────────────────────────────────────

class _ToolBtn(QPushButton):
    """工具栏图标按钮，支持 active 高亮态"""

    def __init__(self, icon_text: str, tooltip: str = "", active: bool = False):
        super().__init__(icon_text)
        self.setFixedSize(28, 28)
        self.setToolTip(tooltip)
        self._active = active
        self._refresh_style()

    def set_active(self, val: bool):
        self._active = val
        self._refresh_style()

    def _refresh_style(self):
        if self._active:
            self.setStyleSheet("""
                QPushButton {
                    background: #DBEAFE;
                    border: 1px solid #93C5FD;
                    border-radius: 6px;
                    color: #1D4ED8;
                    font-size: 14px;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 6px;
                    color: #6B7280;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background: #F3F4F6;
                    border: 1px solid #E5E7EB;
                    color: #374151;
                }
                QPushButton:pressed { background: #E5E7EB; }
                QPushButton:disabled { color: #D1D5DB; }
            """)


class _VDivider(QFrame):
    """工具栏竖向分隔线"""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedSize(1, 18)
        self.setStyleSheet("background: #E5E7EB; border: none;")


# ─────────────────────────────────────────────────────────────────────────────
#  主组件
# ─────────────────────────────────────────────────────────────────────────────

class ImagePreview(QWidget):
    """
    扫描件预览区（重构版）

    对外信号
    --------
    ocr_requested  — 用户点击"开始识别"
    fill_requested — 用户点击"自动填充"
    image_loaded(str) — 图片加载成功，参数为文件路径
    """

    ocr_requested  = Signal()
    fill_requested = Signal()
    image_loaded   = Signal(str)

    # OCR 状态常量
    OCR_IDLE    = "idle"
    OCR_RUNNING = "running"
    OCR_DONE    = "done"

    def __init__(self):
        super().__init__()
        self.current_image_path = None
        self._zoom_factor       = 1.0
        self._rotation          = 0
        self._total_pages       = 1
        self._current_page      = 1
        self._ocr_status        = self.OCR_IDLE

        self.setAcceptDrops(True)
        self._init_ui()
        self._apply_style()

    # ──────────────────────────────── UI 构建 ────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_preview_area(), stretch=1)
        root.addWidget(self._build_page_nav())
        root.addWidget(self._build_ocr_section())

    # ── 工具栏 ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(38)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(2)

        # 组1：翻页
        self.btn_prev = _ToolBtn("◀", "上一页")
        self.btn_next = _ToolBtn("▶", "下一页")
        self.btn_prev.clicked.connect(self._on_prev_page)
        self.btn_next.clicked.connect(self._on_next_page)
        layout.addWidget(self.btn_prev)
        layout.addWidget(self.btn_next)
        layout.addWidget(_VDivider())

        # 组2：视图模式
        self.btn_fit    = _ToolBtn("⤢", "适应窗口", active=True)
        self.btn_actual = _ToolBtn("⊡", "实际大小")
        self.btn_fit.clicked.connect(lambda: self._set_view_mode("fit"))
        self.btn_actual.clicked.connect(lambda: self._set_view_mode("actual"))
        layout.addWidget(self.btn_fit)
        layout.addWidget(self.btn_actual)
        layout.addWidget(_VDivider())

        # 组3：旋转
        self.btn_rotate = _ToolBtn("↻", "顺时针旋转 90°")
        self.btn_rotate.clicked.connect(self._on_rotate)
        layout.addWidget(self.btn_rotate)

        layout.addStretch()

        # 组4：缩放
        self.btn_zoom_out = _ToolBtn("－", "缩小")
        self.zoom_label   = QLabel("100%")
        self.zoom_label.setFixedWidth(36)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setObjectName("zoomLabel")
        self.btn_zoom_in  = _ToolBtn("＋", "放大")
        self.btn_zoom_out.clicked.connect(self._on_zoom_out)
        self.btn_zoom_in.clicked.connect(self._on_zoom_in)
        layout.addWidget(self.btn_zoom_out)
        layout.addWidget(self.zoom_label)
        layout.addWidget(self.btn_zoom_in)

        return bar

    # ── 预览区 ───────────────────────────────────────────────────────────────

    def _build_preview_area(self):
        container = QWidget()
        container.setObjectName("previewContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 滚动区（有图时可见）
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("previewScroll")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.hide()

        # 空状态 drop zone（无图时可见）
        self.drop_zone = self._build_drop_zone()

        layout.addWidget(self.scroll_area, stretch=1)
        layout.addWidget(self.drop_zone,   stretch=1)
        return container

    def _build_drop_zone(self):
        zone = QWidget()
        zone.setObjectName("dropZone")
        zone.setCursor(Qt.CursorShape.PointingHandCursor)
        zone.mousePressEvent = lambda _: self._on_upload()

        layout = QVBoxLayout(zone)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(5)

        icon = QLabel("⬆")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName("dropIcon")

        text = QLabel("拖拽或点击上传")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setObjectName("dropText")

        sub = QLabel("PNG · JPG · PDF，最大 20 MB")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setObjectName("dropSub")

        choose_btn = QPushButton("  选择文件")
        choose_btn.setObjectName("chooseBtn")
        choose_btn.setFixedSize(100, 28)
        choose_btn.clicked.connect(self._on_upload)

        layout.addWidget(icon)
        layout.addWidget(text)
        layout.addWidget(sub)
        layout.addSpacing(4)
        layout.addWidget(choose_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        return zone

    # ── 分页导航 ─────────────────────────────────────────────────────────────

    def _build_page_nav(self):
        self.page_nav_bar = QWidget()
        self.page_nav_bar.setObjectName("pageNavBar")
        self.page_nav_bar.setFixedHeight(30)
        layout = QHBoxLayout(self.page_nav_bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(5)

        self.page_prev_btn = _ToolBtn("◀", "上一页")
        self.page_prev_btn.setFixedSize(22, 22)
        self.page_prev_btn.clicked.connect(self._on_prev_page)

        # 圆点行
        self.dot_container = QWidget()
        self.dot_layout = QHBoxLayout(self.dot_container)
        self.dot_layout.setContentsMargins(0, 0, 0, 0)
        self.dot_layout.setSpacing(3)

        self.page_label = QLabel("1 / 1")
        self.page_label.setObjectName("pageLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.page_next_btn = _ToolBtn("▶", "下一页")
        self.page_next_btn.setFixedSize(22, 22)
        self.page_next_btn.clicked.connect(self._on_next_page)

        layout.addWidget(self.page_prev_btn)
        layout.addWidget(self.dot_container)
        layout.addWidget(self.page_label)
        layout.addStretch()
        layout.addWidget(self.page_next_btn)

        self._refresh_page_nav()
        return self.page_nav_bar

    def _refresh_page_nav(self):
        """刷新圆点指示器和页码"""
        # 清旧圆点
        while self.dot_layout.count():
            item = self.dot_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        shown = min(self._total_pages, 5)
        for i in range(shown):
            dot = QLabel()
            is_active = (i == self._current_page - 1)
            dot.setFixedHeight(6)
            dot.setFixedWidth(14 if is_active else 6)
            dot.setObjectName("dotActive" if is_active else "dotInactive")
            self.dot_layout.addWidget(dot)

        self.page_label.setText(f"{self._current_page} / {self._total_pages}")
        self.page_prev_btn.setEnabled(self._current_page > 1)
        self.btn_prev.setEnabled(self._current_page > 1)
        self.page_next_btn.setEnabled(self._current_page < self._total_pages)
        self.btn_next.setEnabled(self._current_page < self._total_pages)

    # ── OCR 区 ───────────────────────────────────────────────────────────────

    def _build_ocr_section(self):
        section = QWidget()
        section.setObjectName("ocrSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(5)

        # 标题行（标题 + 状态 pill）
        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("✦ OCR 识别")
        title.setObjectName("ocrTitle")
        self.ocr_status_pill = QLabel("未识别")
        self.ocr_status_pill.setObjectName("ocrPillIdle")
        self.ocr_status_pill.setFixedHeight(18)
        header.addWidget(title)
        header.addWidget(self.ocr_status_pill)
        header.addStretch()
        layout.addLayout(header)

        # 识别结果文本框
        self.ocr_text = QTextEdit()
        self.ocr_text.setObjectName("ocrTextBox")
        self.ocr_text.setPlaceholderText("识别结果将显示在此处...")
        self.ocr_text.setFixedHeight(54)
        layout.addWidget(self.ocr_text)

        # 已匹配字段提示（默认隐藏）
        self.ocr_match_label = QLabel()
        self.ocr_match_label.setObjectName("ocrMatchLabel")
        self.ocr_match_label.hide()
        layout.addWidget(self.ocr_match_label)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.ocr_btn  = QPushButton("  开始识别")
        self.fill_btn = QPushButton("  自动填充")
        self.ocr_btn.setObjectName("ocrBtnSecondary")
        self.fill_btn.setObjectName("ocrBtnPrimary")
        self.ocr_btn.setFixedHeight(28)
        self.fill_btn.setFixedHeight(28)
        self.ocr_btn.clicked.connect(self._on_ocr_clicked)
        self.fill_btn.clicked.connect(self._on_fill_clicked)
        btn_row.addWidget(self.ocr_btn)
        btn_row.addWidget(self.fill_btn)
        layout.addLayout(btn_row)

        return section

    # ──────────────────────────────── 事件 ──────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self.load_image(urls[0].toLocalFile())

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择扫描件", "",
            "图片/PDF (*.png *.jpg *.jpeg *.bmp *.tiff *.pdf)"
        )
        if path:
            self.load_image(path)

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._refresh_page_nav()

    def _on_next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._refresh_page_nav()

    def _set_view_mode(self, mode: str):
        self.btn_fit.set_active(mode == "fit")
        self.btn_actual.set_active(mode == "actual")
        if self.current_image_path:
            if mode == "actual":
                self._zoom_factor = 1.0
                self._update_zoom_label()
                self._reload_image_at_zoom()
            else:
                self._fit_image()

    def _on_rotate(self):
        self._rotation = (self._rotation + 90) % 360
        if self.current_image_path:
            self._reload_image_at_zoom()

    def _on_zoom_in(self):
        self._zoom_factor = min(self._zoom_factor + 0.25, 4.0)
        self._update_zoom_label()
        self._reload_image_at_zoom()

    def _on_zoom_out(self):
        self._zoom_factor = max(self._zoom_factor - 0.25, 0.25)
        self._update_zoom_label()
        self._reload_image_at_zoom()

    def _on_ocr_clicked(self):
        self.set_ocr_status(self.OCR_RUNNING)
        self.ocr_requested.emit()

    def _on_fill_clicked(self):
        self.fill_requested.emit()

    # ──────────────────────────────── 公共方法 ───────────────────────────────

    def load_image(self, file_path: str):
        """加载图片或 PDF（外部统一入口）"""
        self.current_image_path = file_path
        self._rotation    = 0
        self._zoom_factor = 1.0
        self._update_zoom_label()

        try:
            if file_path.lower().endswith(".pdf"):
                self._load_pdf(file_path)
            else:
                pixmap = QPixmap(file_path)
                if pixmap.isNull():
                    self._show_error("无法识别的图片格式")
                    return
                self._display_pixmap(pixmap)

            self.drop_zone.hide()
            self.scroll_area.show()
            self.image_loaded.emit(file_path)

        except Exception as e:
            self._show_error(str(e))

    def set_ocr_status(self, status: str, matched: int = 0):
        """
        更新 OCR 状态 pill。
        status: OCR_IDLE | OCR_RUNNING | OCR_DONE
        matched: 已匹配字段数（OCR_DONE 时有效）
        """
        self._ocr_status = status

        pill = self.ocr_status_pill
        if status == self.OCR_IDLE:
            pill.setText("未识别")
            pill.setObjectName("ocrPillIdle")
            self.ocr_btn.setText("  开始识别")
            self.ocr_btn.setEnabled(True)
            self.ocr_match_label.hide()

        elif status == self.OCR_RUNNING:
            pill.setText("识别中…")
            pill.setObjectName("ocrPillRunning")
            self.ocr_btn.setText("  识别中…")
            self.ocr_btn.setEnabled(False)
            self.ocr_match_label.hide()

        elif status == self.OCR_DONE:
            pill.setText("已识别")
            pill.setObjectName("ocrPillDone")
            self.ocr_btn.setText("  重新识别")
            self.ocr_btn.setEnabled(True)
            if matched > 0:
                self.ocr_match_label.setText(f"✔ 已匹配 {matched} 个字段")
                self.ocr_match_label.show()

        # objectName 改变后须强制刷新 QSS
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    def load_ocr_result(self, text: str, matched: int = 0):
        """外部调用：写入识别结果并切换到 DONE 状态"""
        self.ocr_text.setPlainText(text)
        self.set_ocr_status(self.OCR_DONE, matched)

    def get_image_path(self) -> str | None:
        return self.current_image_path

    def set_total_pages(self, total: int):
        """设置总页数（多页 PDF 调用）"""
        self._total_pages  = max(1, total)
        self._current_page = 1
        self._refresh_page_nav()

    # ──────────────────────────────── 私有辅助 ───────────────────────────────

    def _load_pdf(self, pdf_path: str):
        try:
            import fitz
            doc = fitz.open(pdf_path)
            self.set_total_pages(doc.page_count)
            page = doc[self._current_page - 1]
            pix  = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            buf  = io.BytesIO()
            img.save(buf, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            self._display_pixmap(pixmap)
            doc.close()
        except ImportError:
            self._show_error("请安装 PyMuPDF 以支持 PDF 预览")
        except Exception as e:
            self._show_error(f"PDF 加载失败: {e}")

    def _display_pixmap(self, pixmap: QPixmap):
        if self._rotation:
            from PySide6.QtGui import QTransform
            t = QTransform().rotate(self._rotation)
            pixmap = pixmap.transformed(t, Qt.TransformationMode.SmoothTransformation)
        self._fit_image(pixmap)

    def _fit_image(self, pixmap: QPixmap | None = None):
        if pixmap is None:
            if not self.current_image_path:
                return
            pixmap = QPixmap(self.current_image_path)
        w = max(self.scroll_area.width()  - 20, 100)
        h = max(self.scroll_area.height() - 20, 100)
        scaled = pixmap.scaled(
            int(w * self._zoom_factor),
            int(h * self._zoom_factor),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _reload_image_at_zoom(self):
        if self.current_image_path:
            self._fit_image()

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{int(self._zoom_factor * 100)}%")

    def _show_error(self, msg: str):
        self.image_label.setText(f"⚠ {msg}")
        self.drop_zone.hide()
        self.scroll_area.show()

    # ──────────────────────────────── 样式 ──────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet("""

        /* ── 工具栏 ──────────────────────────── */
        QWidget#toolbar {
            background: #F8FAFC;
            border-bottom: 1px solid #E2E8F0;
        }
        QLabel#zoomLabel {
            font-size: 11px;
            color: #6B7280;
            font-family: "Microsoft YaHei";
        }

        /* ── 预览区 ──────────────────────────── */
        QScrollArea#previewScroll {
            border: none;
            background: #F1F5F9;
        }
        QWidget#dropZone {
            background: #F8FAFC;
            border: 2px dashed #CBD5E1;
            border-radius: 10px;
            margin: 6px;
        }
        QWidget#dropZone:hover {
            background: #EFF6FF;
            border-color: #93C5FD;
        }
        QLabel#dropIcon {
            font-size: 26px;
            color: #94A3B8;
        }
        QLabel#dropText {
            font-size: 13px;
            color: #475569;
            font-family: "Microsoft YaHei";
        }
        QLabel#dropSub {
            font-size: 11px;
            color: #94A3B8;
            font-family: "Microsoft YaHei";
        }
        QPushButton#chooseBtn {
            background: white;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            font-size: 12px;
            color: #374151;
            font-family: "Microsoft YaHei";
        }
        QPushButton#chooseBtn:hover {
            background: #F1F5F9;
            border-color: #94A3B8;
        }

        /* ── 分页导航 ─────────────────────────── */
        QWidget#pageNavBar {
            background: #F8FAFC;
            border-top: 1px solid #E2E8F0;
        }
        QLabel#pageLabel {
            font-size: 11px;
            color: #6B7280;
            font-family: "Microsoft YaHei";
        }
        QLabel#dotActive {
            background: #3B82F6;
            border-radius: 3px;
        }
        QLabel#dotInactive {
            background: #CBD5E1;
            border-radius: 3px;
        }

        /* ── OCR 区 ──────────────────────────── */
        QWidget#ocrSection {
            background: #FFFFFF;
            border-top: 1px solid #E2E8F0;
        }
        QLabel#ocrTitle {
            font-size: 12px;
            font-weight: bold;
            color: #374151;
            font-family: "Microsoft YaHei";
        }
        QLabel#ocrPillIdle {
            font-size: 11px;
            padding: 1px 8px;
            border-radius: 10px;
            background: #F1F5F9;
            color: #94A3B8;
            font-family: "Microsoft YaHei";
        }
        QLabel#ocrPillRunning {
            font-size: 11px;
            padding: 1px 8px;
            border-radius: 10px;
            background: #FEF3C7;
            color: #92400E;
            font-family: "Microsoft YaHei";
        }
        QLabel#ocrPillDone {
            font-size: 11px;
            padding: 1px 8px;
            border-radius: 10px;
            background: #D1FAE5;
            color: #065F46;
            font-family: "Microsoft YaHei";
        }
        QTextEdit#ocrTextBox {
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 5px 7px;
            background: #F8FAFC;
            color: #374151;
            font-size: 12px;
            font-family: "Microsoft YaHei";
        }
        QLabel#ocrMatchLabel {
            font-size: 11px;
            color: #065F46;
            font-family: "Microsoft YaHei";
        }
        QPushButton#ocrBtnSecondary {
            background: #F8FAFC;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            font-size: 12px;
            color: #374151;
            font-family: "Microsoft YaHei";
        }
        QPushButton#ocrBtnSecondary:hover { background: #F1F5F9; }
        QPushButton#ocrBtnSecondary:disabled { color: #CBD5E1; }

        QPushButton#ocrBtnPrimary {
            background: #2563EB;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            color: white;
            font-family: "Microsoft YaHei";
            font-weight: bold;
        }
        QPushButton#ocrBtnPrimary:hover { background: #1D4ED8; }

        """)