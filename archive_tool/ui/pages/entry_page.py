"""
录入主页面 - 布局：上表单区、下扫描预览+目录树（QSplitter）
功能说明：
  1. 上半区：档案录入表单（多列网格布局）
  2. 下半区：左扫描件预览、右档案目录树（可拖拽调整宽度）
  3. OCR识别：点击字段激活→框选图片区域→自动填入
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QGroupBox, QTextEdit, QScrollArea, QListWidget, QListWidgetItem, QFileDialog,
    QDateEdit, QDateTimeEdit, QFrame, QHeaderView, QDialog, QDialogButtonBox,
    QCalendarWidget, QInputDialog, QMenu, QCheckBox, QCompleter, QSplitter, QLayout,
    QApplication, QAbstractItemView, QComboBox
)
from PySide6.QtCore import Qt, QDate, QDateTime, QTime, QEvent, QRect, QSize, QPoint
from PySide6.QtGui import QColor
import time

from ui.components.fixed_combo import FixedComboBox


class FlowLayout(QLayout):
    """自适应换行布局"""
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.item_list = []

    def addItem(self, item):
        self.item_list.append(item)

    def count(self):
        return len(self.item_list)

    def itemAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self._do_layout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.item_list:
            size = size.expandedTo(item.minimumSize())
        margin, _, _, _ = self.getContentsMargins()
        size += QSize(2 * margin, 2 * margin)
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0

        for item in self.item_list:
            wid = item.widget()
            space_x = self.spacing()
            space_y = self.spacing()
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()
from core.template_manager import TemplateManager
from core.record_manager import RecordManager
from core.cache_manager import CacheManager
from core.draft_manager import DraftManager
from core.validation import Validator
from core.export_manager import ExportManager
from core.import_manager import ImportManager
from core.logger import Logger
from ui.components.archive_tree import ArchiveTree
from ui.components.scan_preview import ScanPreview


class CollapsibleSection(QWidget):
    """可折叠区域组件"""
    def __init__(self, title: str, expanded: bool = False):
        super().__init__()
        self._expanded = expanded
        self._title = title
        self._content_widget = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = QWidget()
        self.header.setObjectName("collapsibleHeader")
        self.header.setStyleSheet("""
            QWidget#collapsibleHeader {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
            }
        """)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)

        self.toggle_btn = QPushButton("▶")
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 12px;
                color: #3B82F6;
            }
            QPushButton:hover { color: #1D4ED8; }
        """)
        self.toggle_btn.clicked.connect(self.toggle)
        header_layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(self._title)
        self.title_label.setStyleSheet("""
            QLabel { font-weight: bold; color: #1E40AF; font-size: 12px; }
        """)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        main_layout.addWidget(self.header)
        self._update_toggle_icon()

    def _update_toggle_icon(self):
        self.toggle_btn.setText("▼" if self._expanded else "▶")

    def toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._update_toggle_icon()
        if self._content_widget:
            self._content_widget.setVisible(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_content(self, widget: QWidget):
        self._content_widget = widget
        widget.setVisible(self._expanded)
        self.layout().addWidget(widget)


class DatePickerWidget(QWidget):
    """日期选择器"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._date = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.display_btn = QPushButton("请选择日期")
        self.display_btn.setObjectName("datePickerDisplay")
        self.display_btn.setFlat(True)
        self.display_btn.setStyleSheet("""
            QPushButton#datePickerDisplay {
                text-align: left; padding: 4px 8px; border: 1px solid #D1D5DB;
                border-radius: 6px; background: white; color: #9CA3AF; font-size: 13px;
                max-width: 280px; min-width: 280px; min-height: 26px; max-height: 26px;
                outline: none;
            }
            QPushButton#datePickerDisplay:hover { border-color: #9CA3AF; background: white; }
            QPushButton#datePickerDisplay:focus { border-color: #D1D5DB; outline: none; }
            QPushButton#datePickerDisplay[hasDate="true"] { color: #1F2937; }
        """)
        self.display_btn.clicked.connect(self._open_calendar)
        layout.addWidget(self.display_btn, stretch=1)

    def _open_calendar(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("选择日期")
        dialog.setFixedSize(360, 340)
        layout = QVBoxLayout(dialog)

        calendar = QCalendarWidget()
        calendar.setStyleSheet("""
            QCalendarWidget QAbstractItemView {
                font-size: 12px; color: #1F2937;
                selection-background-color: #3B82F6; selection-color: white;
            }
            QCalendarWidget QToolButton { color: #1F2937; }
        """)
        layout.addWidget(calendar)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda: (self.setDate(calendar.selectedDate()), dialog.accept()))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def clear(self):
        self._date = None
        self.display_btn.setText("请选择日期")
        self.display_btn.setProperty("hasDate", False)
        self.display_btn.style().unpolish(self.display_btn)
        self.display_btn.style().polish(self.display_btn)

    def date(self):
        return self._date

    def setDate(self, date: QDate):
        if date is None or not date.isValid():
            self.clear()
            return
        self._date = date
        self.display_btn.setText(date.toString("yyyy-MM-dd"))
        self.display_btn.setProperty("hasDate", True)
        self.display_btn.style().unpolish(self.display_btn)
        self.display_btn.style().polish(self.display_btn)


class DateTimePickerWidget(QWidget):
    """日期时间选择器"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._datetime = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.display_btn = QPushButton("请选择日期时间")
        self.display_btn.setObjectName("datePickerDisplay")
        self.display_btn.setFlat(True)
        self.display_btn.setStyleSheet("""
            QPushButton#datePickerDisplay {
                text-align: left; padding: 4px 8px; border: 1px solid #D1D5DB;
                border-radius: 6px; background: white; color: #9CA3AF; font-size: 13px;
                max-width: 280px; min-width: 280px; min-height: 26px; max-height: 26px;
            }
            QPushButton#datePickerDisplay:hover { border-color: #9CA3AF; background: white; }
            QPushButton#datePickerDisplay:focus { border-color: #9CA3AF; }
            QPushButton#datePickerDisplay[hasValue="true"] { color: #1F2937; }
        """)
        self.display_btn.clicked.connect(self._open_picker)
        layout.addWidget(self.display_btn, stretch=1)

    def _open_picker(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("选择日期时间")
        dialog.setFixedSize(360, 380)
        layout = QVBoxLayout(dialog)

        calendar = QCalendarWidget()
        layout.addWidget(calendar)

        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm:ss")
        layout.addWidget(time_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda: (self.setDateTime(QDateTime(calendar.selectedDate(), time_edit.time())), dialog.accept()))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def clear(self):
        self._datetime = None
        self.display_btn.setText("请选择日期时间")
        self.display_btn.setProperty("hasValue", False)
        self.display_btn.style().unpolish(self.display_btn)
        self.display_btn.style().polish(self.display_btn)

    def dateTime(self):
        return self._datetime

    def setDateTime(self, datetime: QDateTime):
        if datetime is None or not datetime.isValid():
            self.clear()
            return
        self._datetime = datetime
        self.display_btn.setText(datetime.toString("yyyy-MM-dd HH:mm:ss"))
        self.display_btn.setProperty("hasValue", True)
        self.display_btn.style().unpolish(self.display_btn)
        self.display_btn.style().polish(self.display_btn)


class EntryPage(QWidget):
    """档案录入页面"""

    def __init__(self):
        super().__init__()
        self.template_manager = TemplateManager()
        self.record_manager = RecordManager()
        self.cache_manager = CacheManager()
        self.draft_manager = DraftManager()
        self.validator = Validator()
        self.export_manager = ExportManager()
        self.import_manager = ImportManager()
        self.logger = Logger()

        self.current_template = None
        self.current_fields = []
        self.current_record_id = None
        self.current_batch_id = None
        self.current_filing_type = 'item'
        self.is_new_record = False
        self.form_groups = {}
        self.combo_boxes = []
        self.date_widgets = []
        self._templates_need_filing_choice = set()  # template names that support volume
        self._template_filing_types = {}  # name -> filing_type mapping

        # OCR状态管理
        self.active_field = None              # 当前获得焦点的字段
        self.ocr_target_field = None          # OCR结果写入目标
        self.last_manual_field = None         # 用户最后手动点击的字段
        self.manual_override_mode = False     # 是否处于手动覆盖模式
        self._ocr_is_processing = False       # OCR处理中锁，防止重复识别

        self._init_ui()
        self._apply_style()
        self._init_template_combo()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 顶部工具栏
        self.toolbar = self._build_info_card()
        main_layout.addWidget(self.toolbar)

        # 下方三栏式布局：左扫描预览、中表单、右档案目录
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setContentsMargins(10, 0, 10, 0)

        # 左侧：扫描预览面板
        self.left_panel = self._create_left_panel()
        self.left_panel.setMinimumWidth(300)
        self.left_panel.setMaximumWidth(720)

        # 中间：表单面板
        self.form_panel = self._create_form_panel()
        self.form_panel.setMinimumWidth(200)

        # 右侧：档案目录面板
        self.right_panel = self._create_right_panel()
        self.right_panel.setMinimumWidth(240)
        self.right_panel.setMaximumWidth(360)

        # 添加面板到splitter
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.form_panel)
        self.splitter.addWidget(self.right_panel)

        # 设置初始宽度比例：预览38%、表单32%、目录30%
        self.splitter.setStretchFactor(0, 38)
        self.splitter.setStretchFactor(1, 32)
        self.splitter.setStretchFactor(2, 30)

        main_layout.addWidget(self.splitter, stretch=1)

        # 当前激活的字段
        self.active_field = None

        # 标记第一次显示
        self._first_show = True
        self._tree_hidden = False

    def _create_left_panel(self):
        """左侧扫描件预览面板"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("QWidget { background: #059669; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)

        title = QLabel("\ud83d\udcf4 扫描件预览")
        title.setStyleSheet("color: white; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(title)

        # 当前目标字段提示
        self.target_field_label = QLabel("")
        self.target_field_label.setObjectName("targetFieldLabel")
        header_layout.addWidget(self.target_field_label)
        header_layout.addStretch()
        
        self.show_tree_btn = QPushButton("◀ 目录")
        self.show_tree_btn.setObjectName("showTreeBtn")
        self.show_tree_btn.setFixedSize(56, 24)
        self.show_tree_btn.setToolTip("显示档案目录")
        self.show_tree_btn.setStyleSheet("""
            QPushButton {
                border: none; border-radius: 4px;
                color: white; background: rgba(255,255,255,0.2);
                font-size: 12px; padding: 0;
            }
            QPushButton:hover { background: rgba(255,255,255,0.3); }
            QPushButton:pressed { background: rgba(255,255,255,0.4); }
            QPushButton:disabled { color: #86EFAC; background: rgba(255,255,255,0.1); }
        """)
        self.show_tree_btn.clicked.connect(self._on_toggle_tree)
        self.show_tree_btn.hide()
        header_layout.addWidget(self.show_tree_btn)
        
        # OCR状态提示标签
        self.ocr_status_label = QLabel("")
        self.ocr_status_label.setStyleSheet("font-size: 12px; padding: 0 15px;")
        self.ocr_status_label.hide()
        header_layout.addWidget(self.ocr_status_label)
        
        container_layout.addWidget(header)

        # 扫描预览组件
        self.scan_preview = ScanPreview()
        self.scan_preview.region_selected.connect(self._on_scan_region_selected)
        container_layout.addWidget(self.scan_preview, stretch=1)

        return container

    def _create_form_panel(self):
        """表单面板（占满宽度）"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.form_widget = QWidget()
        self.form_layout = QVBoxLayout(self.form_widget)
        self.form_layout.setSpacing(8)
        self.form_layout.setContentsMargins(8, 8, 8, 8)
        self.form_layout.addStretch()
        self.form_scroll.setWidget(self.form_widget)
        layout.addWidget(self.form_scroll, stretch=1)

        return panel

    def showEvent(self, event):
        """第一次显示时动态设置splitter尺寸"""
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._update_splitter_sizes()

    def _update_splitter_sizes(self):
        """根据可用宽度动态计算splitter各部分尺寸"""
        available = self.width() - 20  # 减去边距
        if available > 0:
            left_width = int(available * 0.42)   # 扫描件占38%
            right_width = int(available * 0.28)  # 目录占28%
            mid_width = available - left_width - right_width  # 表单占34%

            left_width = max(self.left_panel.minimumWidth(), min(left_width, self.left_panel.maximumWidth()))
            right_width = max(self.right_panel.minimumWidth(), min(right_width, self.right_panel.maximumWidth()))
            mid_width = max(self.form_panel.minimumWidth(), mid_width)

            self.splitter.setSizes([left_width, mid_width, right_width])

    def _create_right_panel(self):
        """右侧档案目录树面板"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        header = QWidget()
        header.setStyleSheet("QWidget { background: #1E40AF; border-radius: 8px 8px 0 0; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)

        title = QLabel("\ud83d\udcc1 档案目录")
        title.setStyleSheet("color: white; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        self.tree_toggle_btn = QPushButton("▶")
        self.tree_toggle_btn.setObjectName("treeToggleBtn")
        self.tree_toggle_btn.setFixedSize(24, 24)
        self.tree_toggle_btn.setToolTip("隐藏目录")
        self.tree_toggle_btn.setStyleSheet("""
            QPushButton {
                border: none; border-radius: 4px;
                color: white; background: rgba(255,255,255,0.2);
                font-size: 14px; padding: 0;
            }
            QPushButton:hover { background: rgba(255,255,255,0.3); }
            QPushButton:pressed { background: rgba(255,255,255,0.4); }
        """)
        self.tree_toggle_btn.clicked.connect(self._on_toggle_tree)
        header_layout.addWidget(self.tree_toggle_btn)
        
        container_layout.addWidget(header)

        search_widget = QWidget()
        search_widget.setStyleSheet("QWidget { background: #FFFFFF; padding: 6px 8px; }")
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)
        
        self.tree_search_edit = QLineEdit()
        self.tree_search_edit.setPlaceholderText("搜索档案…")
        self.tree_search_edit.setObjectName("treeSearchEdit")
        search_layout.addWidget(self.tree_search_edit)
        container_layout.addWidget(search_widget)

        self.archive_tree = ArchiveTree()
        self.archive_tree.batch_selected.connect(self._on_tree_batch_selected)
        self.archive_tree.year_selected.connect(self._on_tree_year_selected)
        self.archive_tree.record_selected.connect(self._on_tree_record_selected)
        container_layout.addWidget(self.archive_tree, stretch=1)

        footer = QWidget()
        footer.setStyleSheet("QWidget { background: #F9FAFB; border-top: 1px solid #E5E7EB; padding: 1px; }")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        
        self.new_batch_btn = QPushButton("＋")
        self.new_batch_btn.setObjectName("newBatchBtn")
        self.new_batch_btn.setFixedSize(24, 24)
        self.new_batch_btn.setToolTip("新建批次")
        self.new_batch_btn.clicked.connect(self._on_new_batch)
        footer_layout.addWidget(self.new_batch_btn)
        
        self.delete_batch_btn = QPushButton("×")
        self.delete_batch_btn.setObjectName("deleteBatchBtn")
        self.delete_batch_btn.setFixedSize(24, 24)
        self.delete_batch_btn.setToolTip("删除批次")
        self.delete_batch_btn.clicked.connect(self._on_delete_batch)
        self.delete_batch_btn.setEnabled(False)
        footer_layout.addWidget(self.delete_batch_btn)
        
        self.tree_refresh_btn = QPushButton("↻")
        self.tree_refresh_btn.setObjectName("treeRefreshBtn")
        self.tree_refresh_btn.setFixedSize(24, 24)
        self.tree_refresh_btn.setToolTip("刷新目录")
        self.tree_refresh_btn.clicked.connect(self.archive_tree.refresh)
        footer_layout.addWidget(self.tree_refresh_btn)
        
        self.tree_expand_btn = QPushButton("⊞")
        self.tree_expand_btn.setObjectName("treeExpandBtn")
        self.tree_expand_btn.setFixedSize(24, 24)
        self.tree_expand_btn.setToolTip("展开所有")
        self.tree_expand_btn.clicked.connect(lambda: self.archive_tree.tree_widget.expandAll())
        footer_layout.addWidget(self.tree_expand_btn)
        
        self.tree_collapse_btn = QPushButton("⊟")
        self.tree_collapse_btn.setObjectName("treeCollapseBtn")
        self.tree_collapse_btn.setFixedSize(24, 24)
        self.tree_collapse_btn.setToolTip("收起所有")
        self.tree_collapse_btn.clicked.connect(lambda: self.archive_tree.tree_widget.collapseAll())
        footer_layout.addWidget(self.tree_collapse_btn)
        
        footer_layout.addStretch()
        container_layout.addWidget(footer)

        self.tree_search_edit.textChanged.connect(self.archive_tree._on_search)

        return container

    def _create_compact_card(self, label_text, widget, width=180):
        """创建紧凑型信息卡片（带阴影）"""
        card = QWidget()
        card.setFixedWidth(width)
        card.setFixedHeight(78)  # 统一卡片高度
        card.setObjectName("infoCard")

        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 30))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("cardTitle")
        layout.addWidget(label)
        layout.addWidget(widget)

        return card

    def _build_info_card(self):
        """顶部工具栏 - 两行布局"""
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        toolbar.setFixedHeight(96)
        
        main_layout = QVBoxLayout(toolbar)
        main_layout.setContentsMargins(12, 6, 12, 6)
        main_layout.setSpacing(6)

        def create_label(text):
            label = QLabel(text)
            label.setObjectName("toolbarLabel")
            return label

        # 第一行：下拉选择控件
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(12)

        # 模板选择：标签 + 下拉框
        row1_layout.addWidget(create_label("模板："))
        self.template_combo = FixedComboBox()
        self.template_combo.setObjectName("templateCombo")
        self.template_combo.setFixedSize(150, 28)
        self.template_combo.currentTextChanged.connect(self._on_template_changed)
        row1_layout.addWidget(self.template_combo)

        # 归档类型：标签 + 下拉框
        row1_layout.addWidget(create_label("归档类型："))
        self.filing_type_combo = FixedComboBox()
        self.filing_type_combo.setObjectName("filingTypeCombo")
        self.filing_type_combo.setFixedSize(100, 28)
        self.filing_type_combo.addItems(["以件归档", "以卷归档"])
        self.filing_type_combo.setEnabled(False)
        row1_layout.addWidget(self.filing_type_combo)

        # 批次：标签 + 下拉框
        row1_layout.addWidget(create_label("批次："))
        self.batch_combo = FixedComboBox()
        self.batch_combo.setObjectName("batchCombo")
        self.batch_combo.setFixedHeight(28)
        self.batch_combo.setMinimumWidth(120)
        self.batch_combo.currentIndexChanged.connect(self._on_batch_changed)
        row1_layout.addWidget(self.batch_combo)

        row1_layout.addStretch()

        # 第二行：操作按钮
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(8)

        self.new_record_btn = QPushButton("＋ 新建")
        self.save_draft_btn = QPushButton("📝 存草稿")
        self.save_record_btn = QPushButton("✓ 保存")
        self.fill_btn = QPushButton("📋 一键填充")
        self.export_btn = QPushButton("↓ 导出")
        self.validate_btn = QPushButton("✔ 校验")
        self.import_btn = QPushButton("📥 Excel导入")

        for btn in (self.new_record_btn, self.save_draft_btn, self.save_record_btn, self.fill_btn, self.export_btn, self.validate_btn, self.import_btn):
            btn.setFixedHeight(26)
            btn.setMinimumWidth(42)

        self.new_record_btn.setStyleSheet("""
            QPushButton {
                background: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #2563EB; }
        """)
        self.save_draft_btn.setStyleSheet("""
            QPushButton {
                background: #6B7280;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #4B5563; }
        """)
        self.save_record_btn.setStyleSheet("""
            QPushButton {
                background: #059669;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.fill_btn.setStyleSheet("""
            QPushButton {
                background: #EDE9FE;
                color: #5B21B6;
                border: 1px solid #C4B5FD;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #DDD6FE; }
        """)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background: #DBEAFE;
                color: #1D4ED8;
                border: 1px solid #93C5FD;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #BFDBFE; }
        """)
        self.validate_btn.setStyleSheet("""
            QPushButton {
                background: #FEF3C7;
                color: #92400E;
                border: 1px solid #FCD34D;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #FDE68A; }
        """)
        self.import_btn.setStyleSheet("""
            QPushButton {
                background: #ECFDF5;
                color: #065F46;
                border: 1px solid #A7F3D0;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #D1FAE5; }
        """)

        self.new_record_btn.clicked.connect(self._on_new_record)
        self.save_draft_btn.clicked.connect(self._on_save_draft)
        self.save_record_btn.clicked.connect(self._on_save_record)
        self.fill_btn.clicked.connect(self._on_fill_from_record)
        self.export_btn.clicked.connect(self._on_export)
        self.validate_btn.clicked.connect(self._on_validate)
        self.import_btn.clicked.connect(self._on_import)

        row2_layout.addWidget(self.new_record_btn)
        row2_layout.addWidget(self.save_draft_btn)
        row2_layout.addWidget(self.save_record_btn)
        row2_layout.addWidget(self.fill_btn)
        row2_layout.addWidget(self.export_btn)
        row2_layout.addWidget(self.validate_btn)
        row2_layout.addWidget(self.import_btn)

        main_layout.addLayout(row1_layout)
        main_layout.addLayout(row2_layout)
        
        return toolbar

    def _init_template_combo(self):
        templates = self.template_manager.get_all_templates()
        for template in templates:
            filing_type = template.get('filing_type', 'item')
            self.template_combo.addItem(template['name'], template['filename'])
            self._template_filing_types[template['name']] = filing_type
            if filing_type == 'volume':
                self._templates_need_filing_choice.add(template['name'])

        if templates:
            self._on_template_changed(templates[0]['name'])

        self._load_batches()

    def _load_batches(self):
        from db.database import get_cursor
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.batch_combo.addItem("请选择批次", None)
        max_text_width = 0
        try:
            with get_cursor() as cursor:
                cursor.execute("SELECT id, name FROM batches ORDER BY id DESC")
                for b in cursor.fetchall():
                    self.batch_combo.addItem(f"{b['name']}", b['id'])
        except Exception:
            pass
        self.batch_combo.blockSignals(False)
        
        fm = self.fontMetrics()
        max_text_width = max(fm.horizontalAdvance(self.batch_combo.itemText(i)) for i in range(self.batch_combo.count()))
        total_width = max_text_width + 60
        min_width = self.batch_combo.minimumWidth()
        self.batch_combo.setFixedWidth(max(total_width, min_width))

    def _on_template_changed(self, template_name):
        self.current_template = template_name
        filename = self.template_manager.get_filename_by_name(template_name)
        if filename:
            self._load_template_fields(filename)

    def _load_template_fields(self, template_filename):
        self.current_fields = self.template_manager.get_fields(template_filename)
        self._update_filing_type()  # must set filing_type BEFORE _build_form
        self._build_form()
        self._clear_form()

    def _update_filing_type(self):
        template_filing_type = self._template_filing_types.get(self.current_template, 'item')

        if template_filing_type == 'volume':
            self.filing_type_combo.setCurrentIndex(1)  # "以卷归档"
            self.current_filing_type = 'volume'
        else:
            self.filing_type_combo.setCurrentIndex(0)  # "以件归档"
            self.current_filing_type = 'item'

    def _build_form(self):
        self.combo_boxes.clear()
        self.date_widgets.clear()

        while self.form_layout.count() > 0:
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        self.form_groups.clear()

        if not self.current_fields:
            self.form_layout.addStretch()
            return

        filing_type = self.current_filing_type

        if filing_type == 'item':
            filtered_fields = [f for f in self.current_fields if f.get('layer', 'file') == 'file']
        else:
            filtered_fields = self.current_fields

        col_count = 1

        form_widget = QWidget()
        form_widget.setObjectName("formWidget")
        gl = QGridLayout(form_widget)
        gl.setSpacing(8)
        gl.setHorizontalSpacing(16)
        gl.setVerticalSpacing(10)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setColumnStretch(0, 1)
        gl.setColumnStretch(1, 1)

        for idx, field in enumerate(filtered_fields):
            field_key = field["key"]
            field_name = field["name"]
            field_type = field.get("type", "text")
            required = field.get("required", False)
            options = field.get("dropdown_options", [])
            hint = field.get("hint", "")

            label_text = f"{field_name} <span style='color:#EF4444'>*</span>" if required else field_name

            if options:
                w = FixedComboBox()
                w.addItems(options)
                w.installEventFilter(self)
                self.combo_boxes.append(w)
            elif field_type == "date":
                w = QLineEdit()
                w.setPlaceholderText("yyyyMMdd")
                w.setMaxLength(8)
                w.installEventFilter(self)
            elif field_type == "datetime":
                w = QLineEdit()
                w.setPlaceholderText("yyyyMMdd")
                w.setMaxLength(8)
                w.installEventFilter(self)
            elif field_type == "number":
                w = QLineEdit()
                w.setInputMask("9999999999")
                w.installEventFilter(self)
            elif field_type == "textarea":
                w = QTextEdit()
                w.setMaximumHeight(72)
                w.installEventFilter(self)
            else:
                w = QLineEdit()
                w.installEventFilter(self)
                self._setup_completer(w, field_key)

            w.setObjectName(field_key)
            if hint:
                w.setToolTip(hint)
            if isinstance(w, (QLineEdit, QComboBox)):
                w.setMinimumWidth(240)
                w.setMaximumWidth(440)

            field_container = QWidget()
            field_layout = QVBoxLayout(field_container)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(2)

            label = QLabel(label_text)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setObjectName("formFieldLabel")
            if hint:
                label.setToolTip(hint)
            field_layout.addWidget(label)
            field_layout.addWidget(w)

            row = idx // col_count
            col = idx % col_count
            gl.addWidget(field_container, row, col)

        self.form_layout.addWidget(form_widget)
        self.form_layout.addStretch()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _setup_completer(self, line_edit, field_key):
        """为文本框设置智能联想（三层：标准词库+历史值+拼音首字母）"""
        from db.database import get_cursor

        candidates = []

        try:
            with get_cursor() as cursor:
                # 第一层：标准词库（权重高，排前面）
                cursor.execute('''
                    SELECT value FROM std_vocabulary 
                    WHERE field_key = ? 
                    ORDER BY weight DESC, value
                ''', (field_key,))
                std_values = [row['value'] for row in cursor.fetchall()]

                # 第二层：历史录入值（去重）
                cursor.execute('''
                    SELECT DISTINCT field_value FROM record_values 
                    WHERE field_key = ? 
                    AND field_value IS NOT NULL 
                    AND field_value != ''
                    ORDER BY rowid DESC LIMIT 50
                ''', (field_key,))
                history_values = [row['field_value'] for row in cursor.fetchall()]

            # 合并，标准词库优先，历史值补充
            seen = set()
            for v in std_values + history_values:
                if v not in seen:
                    candidates.append(v)
                    seen.add(v)

        except Exception as e:
            print(f"联想加载失败: {e}")

        if not candidates:
            return

        completer = QCompleter(candidates)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setMaxVisibleItems(8)
        
        completer.popup().setStyleSheet("""
            QListView {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                background: white;
                font-size: 12px;
                padding: 4px;
            }
            QListView::item {
                padding: 5px 12px;
                border-radius: 4px;
                color: #374151;
            }
            QListView::item:selected {
                background: #EFF6FF;
                color: #1D4ED8;
            }
        """)
        
        line_edit.setCompleter(completer)

        # 断开旧的信号连接，防止重复触发
        try:
            line_edit.textEdited.disconnect()
        except Exception:
            pass
        
        # 输入时动态更新（支持拼音首字母）
        line_edit.textEdited.connect(
            lambda text: self._on_field_text_edited(text, field_key, completer, candidates)
        )

    def _on_field_text_edited(self, text, field_key, completer, candidates):
        """输入时动态更新候选列表（支持拼音首字母匹配）"""
        if not text:
            completer.model().setStringList(candidates)
            return
        
        if text.isalpha() and text.islower():
            from db.database import get_cursor
            try:
                with get_cursor() as cursor:
                    cursor.execute('''
                        SELECT value FROM std_vocabulary 
                        WHERE field_key = ? AND pinyin_abbr LIKE ?
                        ORDER BY weight DESC LIMIT 10
                    ''', (field_key, f'{text}%'))
                    pinyin_matches = [row['value'] for row in cursor.fetchall()]
                
                if pinyin_matches:
                    merged = pinyin_matches + [c for c in candidates if c not in pinyin_matches]
                    completer.model().setStringList(merged)
                else:
                    completer.model().setStringList(candidates)
            except Exception:
                completer.model().setStringList(candidates)
        else:
            completer.model().setStringList(candidates)

    def _clear_form(self):
        for field in self.current_fields:
            fk = field["key"]
            w = (self.form_widget.findChild(QLineEdit, fk) or
                 self.form_widget.findChild(QComboBox, fk) or
                 self.form_widget.findChild(QTextEdit, fk) or
                 self.form_widget.findChild(QDateEdit, fk) or
                 self.form_widget.findChild(QDateTimeEdit, fk) or
                 self.form_widget.findChild(QWidget, fk))
            if not w:
                continue
            if isinstance(w, DatePickerWidget):
                w.clear()
            elif isinstance(w, DateTimePickerWidget):
                w.clear()
            elif isinstance(w, QLineEdit):
                w.clear()
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(0)
            elif isinstance(w, QTextEdit):
                w.clear()
            elif isinstance(w, QDateEdit):
                w.clear()
            elif isinstance(w, QDateTimeEdit):
                w.clear()

    def _on_new_record(self):
        self.current_record_id = None
        self.is_new_record = True
        self._clear_form()
        self._load_cache()

    def _on_save_draft(self):
        """存为草稿 - 不校验，直接保存到草稿表"""
        if not self.current_batch_id:
            QMessageBox.warning(self, "提示", "请先选择批次")
            return

        data = self._collect_field_data()

        draft_name, ok = QInputDialog.getText(
            self, "保存草稿", "请输入草稿名称：",
            text=f"草稿_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        if not ok or not draft_name.strip():
            return

        try:
            self.draft_manager.save_draft(
                draft_name=draft_name.strip(),
                batch_id=self.current_batch_id,
                template_name=self.current_template,
                data=data
            )
            QMessageBox.information(self, "成功", f"草稿「{draft_name}」已保存")
            self.logger.log("save_draft", {"draft_name": draft_name})
            self.save_auto_cache()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _on_fill_from_record(self):
        """一键填充 - 从同批次记录复制默认字段"""
        print(f"current_batch_id: {self.current_batch_id}")
        print(f"current_template: {self.current_template}")
        
        if not self.current_batch_id:
            QMessageBox.warning(self, "提示", "请先选择批次")
            return

        records = self.record_manager.get_records_by_batch(self.current_batch_id)
        print(f"查到记录数: {len(records) if records else 0}")
        
        if not records:
            QMessageBox.information(self, "提示", "当前批次没有记录可供复制")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("选择记录填充")
        dialog.setMinimumSize(500, 360)
        layout = QVBoxLayout(dialog)

        label = QLabel("请选择同批次的一条记录，复制其默认字段值：")
        label.setStyleSheet("color: #6B7280; font-size: 12px; padding: 4px 0;")
        layout.addWidget(label)

        record_list = QListWidget()
        record_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #F3F4F6;
                color: #374151;
            }
            QListWidget::item:selected {
                background: #EFF6FF;
                color: #1D4ED8;
            }
            QListWidget::item:hover:!selected {
                background: #F9FAFB;
            }
        """)

        for record in records:
            template_name = record.get('template_name') or '未知模板'
            filing_type = '以卷归档' if record.get('filing_type') == 'volume' else '以件归档'
            year = record.get('year') or '未知年份'
            name = record.get('name') or f"记录{record['id']}"

            display = f"{template_name}  |  {filing_type}  |  {year}年  |  {name}"
            
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, record['id'])
            record_list.addItem(item)

        layout.addWidget(record_list)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("填充")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_item = record_list.currentItem()
            if selected_item:
                record_id = selected_item.data(Qt.ItemDataRole.UserRole)
                record = self.record_manager.get_record(record_id)
                if record:
                    self._fill_from_record_data(record.get('values', {}))
                    QMessageBox.information(self, "成功", "已填充选中记录的字段值")

    def _fill_from_record_data(self, values):
        """从记录数据填充表单"""
        for field in self.current_fields:
            fk = field["key"]
            field_type = field.get("type", "text")
            val = values.get(fk, "")
            if not val:
                continue

            w = self.form_widget.findChild(QLineEdit, fk)
            if w:
                if field_type == "datetime" and len(val) > 8:
                    val = val[:8]
                w.setText(val)
                continue
            w = self.form_widget.findChild(QComboBox, fk)
            if w:
                idx = w.findText(val)
                w.setCurrentIndex(idx if idx >= 0 else 0)
                continue
            w = self.form_widget.findChild(QTextEdit, fk)
            if w:
                w.setText(val)
                continue


    def _on_save_record(self):
        if not self.current_batch_id:
            QMessageBox.warning(self, "提示", "请先选择批次")
            return

        data = self._collect_field_data()
        
        if self.current_filing_type == 'item':
            file_fields = [f for f in self.current_fields if f.get('layer', 'file') == 'file']
            errors = self.validator.validate_record(file_fields, data)
            if errors:
                field_names = [e.field_name for e in errors]
                msg = f"以下字段是必填项，请填写后再保存：\n{'、'.join(field_names)}"
                QMessageBox.warning(self, "校验失败", msg)
                return
        else:
            project_errors = self._validate_by_layer(data, 'project')
            case_errors = self._validate_by_layer(data, 'case')
            file_errors = self._validate_by_layer(data, 'file')
            
            if project_errors or case_errors or file_errors:
                self._show_layered_errors(project_errors, case_errors, file_errors)
                return

        try:
            year = self._extract_year_from_data(data)
            
            if self.is_new_record:
                # 弹窗输入记录名称
                record_name, ok = QInputDialog.getText(self, "保存记录", "请输入记录名称：")
                if not ok or not record_name.strip():
                    return
                record_name = record_name.strip()
                
                record_id = self.record_manager.create_record(
                    batch_id=self.current_batch_id,
                    template_id=self.template_manager.get_template_id(self.current_template),
                    template_name=self.current_template,
                    name=record_name,
                    filing_type=self.current_filing_type,
                    year=year,
                    data=data
                )
                self.current_record_id = record_id
                self.is_new_record = False
                QMessageBox.information(self, "成功", "档案记录已保存")
            else:
                self.record_manager.update_record(self.current_record_id, data)
                QMessageBox.information(self, "成功", "档案记录已更新")

            self.archive_tree.refresh()
            self.save_auto_cache()
            self.logger.log("save_record", {
                "record_id": self.current_record_id,
                "record_name": record_name,
                "template_name": self.current_template
            })
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _collect_field_data(self):
        data = {}
        for field in self.current_fields:
            fk = field["key"]
            w = self.form_widget.findChild(QLineEdit, fk, Qt.FindChildrenRecursively)
            if w:
                data[fk] = w.text().strip()
                continue
            w = self.form_widget.findChild(QComboBox, fk, Qt.FindChildrenRecursively)
            if w:
                data[fk] = w.currentText().strip()
                continue
            w = self.form_widget.findChild(QTextEdit, fk, Qt.FindChildrenRecursively)
            if w:
                data[fk] = w.toPlainText().strip()
                continue

        return data

    def _extract_year_from_data(self, data):
        """从字段数据中提取年份值"""
        from PySide6.QtCore import QDate
        
        for field in self.current_fields:
            field_key = field.get('key', '')
            field_name = field.get('name', '')
            
            if 'year' in field_key.lower() or '年' in field_name:
                val = data.get(field_key, '')
                if val and len(val) >= 4 and val[:4].isdigit():
                    return int(val[:4])
        
        return QDate.currentDate().year()

    def _load_record_to_form(self, record):
        if not record:
            return

        values = record.get('values', {})
        for field in self.current_fields:
            fk = field["key"]
            val = values.get(fk, "")

            w = self.form_widget.findChild(QLineEdit, fk, Qt.FindChildrenRecursively)
            if w:
                w.setText(val)
                continue
            w = self.form_widget.findChild(QComboBox, fk, Qt.FindChildrenRecursively)
            if w:
                idx = w.findText(val)
                w.setCurrentIndex(idx if idx >= 0 else 0)
                continue
            w = self.form_widget.findChild(QTextEdit, fk, Qt.FindChildrenRecursively)
            if w:
                w.setText(val)
                continue


    def _validate_by_layer(self, data, layer):
        layer_fields = [f for f in self.current_fields if f.get('layer') == layer]
        return self.validator.validate_record(layer_fields, data)

    def _show_layered_errors(self, project_errors, case_errors, file_errors):
        msg_parts = ["以下字段是必填项，请填写后再保存："]
        if project_errors:
            field_names = [e.field_name for e in project_errors]
            msg_parts.append(f"【项目层】{'、'.join(field_names)}")
        if case_errors:
            field_names = [e.field_name for e in case_errors]
            msg_parts.append(f"【案卷层】{'、'.join(field_names)}")
        if file_errors:
            field_names = [e.field_name for e in file_errors]
            msg_parts.append(f"【文件层】{'、'.join(field_names)}")
        QMessageBox.warning(self, "校验失败", "\n".join(msg_parts))

    def _show_batch_validation_result(self, all_errors, duplicate_errors):
        dialog = QDialog(self)
        dialog.setWindowTitle("批次自查结果")
        dialog.setMinimumSize(600, 500)
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        result_list = QListWidget()
        result_list.setWordWrap(True)
        result_list.setSpacing(6)
        result_list.setResizeMode(QListWidget.Adjust)

        if self.current_batch_id:
            filing_type_text = '以件归档' if self.current_filing_type == 'item' else '以卷归档'
            result_list.addItem(f"📦 批次ID: {self.current_batch_id}")
            result_list.addItem(f"📋 模板: {self.current_template or '未设置'}")
            result_list.addItem(f"📁 归档类型: {filing_type_text}")

        field_error_count = sum(len(e['errors']) for e in all_errors)
        dup_count = len(duplicate_errors) if duplicate_errors else 0
        
        if all_errors:
            result_list.addItem(f"❌ 校验失败记录: {len(all_errors)} 条，共 {field_error_count} 个字段错误")
            
            for error_item in all_errors:
                record_id = error_item['record_id']
                errors = error_item['errors']
                field_names = [e.field_name for e in errors]
                item_text = f"📝 记录ID {record_id}: {', '.join(field_names)}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, {'type': 'field_error', 'record_id': record_id})
                result_list.addItem(item)

        if duplicate_errors:
            result_list.addItem(f"⚠️ 重复编号: {dup_count} 条")
            dup_numbers = set(d.message for d in duplicate_errors)
            for num in dup_numbers:
                item_text = f"  - {num}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, {'type': 'duplicate'})
                result_list.addItem(item)

        if not all_errors and not duplicate_errors:
            result_list.addItem("✓ 批次内所有记录校验通过，无重复编号")

        result_list.itemClicked.connect(self._on_validation_result_clicked)
        layout.addWidget(result_list, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.close)
        layout.addWidget(button_box)

        dialog.exec()

    def _on_validation_result_clicked(self, item):
        data = item.data(Qt.UserRole)
        if data and data.get('type') in ['field_error', 'error_detail']:
            record_id = data.get('record_id')
            if record_id:
                record = self.record_manager.get_record(record_id)
                if record:
                    self._on_tree_record_selected({'id': record_id})

    def _on_export(self):
        export_menu = QMenu(self)
        
        action_single = export_menu.addAction("导出当前记录")
        action_batch = export_menu.addAction("导出批次所有记录")
        
        pos = self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft())
        action = export_menu.exec(pos)
        
        if action == action_single:
            if self.current_record_id:
                self.export_manager.export_records([self.current_record_id], self.current_filing_type)
            else:
                QMessageBox.warning(self, "提示", "请先选择或创建一条记录")
        elif action == action_batch:
            if self.current_batch_id:
                records = self.record_manager.get_records_by_batch(self.current_batch_id)
                if records:
                    record_ids = [r['id'] for r in records]
                    self.export_manager.export_records(record_ids, self.current_filing_type)
                    QMessageBox.information(self, "成功", "批次导出完成")
                else:
                    QMessageBox.warning(self, "提示", "当前批次没有记录")
            else:
                QMessageBox.warning(self, "提示", "请先选择批次")

    def _on_import(self):
        if not self.current_template:
            QMessageBox.warning(self, "提示", "请先选择模板")
            return

        if not self.current_batch_id:
            QMessageBox.warning(self, "提示", "请先选择批次")
            return

        filing_type_text = '以件归档' if self.current_filing_type == 'item' else '以卷归档'

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择Excel文件", "", "Excel文件 (*.xlsx *.xls)"
        )

        if not file_path:
            return

        if self.current_filing_type == 'item':
            expected_fields = [f for f in self.current_fields if f.get('layer', 'file') == 'file']
        else:
            expected_fields = self.current_fields

        success, result = self.import_manager.import_from_excel(file_path, expected_fields)

        if not success:
            QMessageBox.warning(self, "导入失败", f"{result}")
            return

        import_data = result['data']
        total_rows = len(import_data)
        extra_columns = result.get('extra_columns', [])

        confirm_msg = f"即将导入 {total_rows} 条记录到批次【{self.batch_combo.currentText()}】\n"
        confirm_msg += f"模板：{self.current_template}\n"
        confirm_msg += f"归档类型：{filing_type_text}\n"
        if extra_columns:
            confirm_msg += f"\n⚠️ 检测到 {len(extra_columns)} 个多余列，将被忽略：\n{', '.join(extra_columns)}\n"

        reply = QMessageBox.question(
            self, "确认导入", confirm_msg,
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            success_count = 0
            fail_count = 0
            fail_messages = []

            existing_names = set(self.record_manager.get_record_names_by_batch(self.current_batch_id))

            def get_unique_name(base_name, existing):
                if base_name not in existing:
                    return base_name
                suffix = 2
                while f"{base_name}-{suffix}" in existing:
                    suffix += 1
                return f"{base_name}-{suffix}"

            for idx, row_data in enumerate(import_data, 1):
                if self.current_filing_type == 'item':
                    file_fields = [f for f in self.current_fields if f.get('layer', 'file') == 'file']
                    errors = self.validator.validate_record(file_fields, row_data)
                    if errors:
                        field_names = [e.field_name for e in errors]
                        fail_messages.append(f"第{idx}行：必填项缺失 - {', '.join(field_names)}")
                        fail_count += 1
                        continue

                    year = self._extract_year_from_data(row_data)
                    base_name = row_data.get('title') or row_data.get('mingcheng') or f"导入记录{idx}"
                    record_name = get_unique_name(base_name, existing_names)
                    existing_names.add(record_name)

                    self.record_manager.create_record(
                        batch_id=self.current_batch_id,
                        template_id=self.template_manager.get_template_id(self.current_template),
                        template_name=self.current_template,
                        name=record_name,
                        filing_type=self.current_filing_type,
                        year=year,
                        data=row_data
                    )
                    success_count += 1
                else:
                    project_errors = self._validate_by_layer(row_data, 'project')
                    case_errors = self._validate_by_layer(row_data, 'case')
                    file_errors = self._validate_by_layer(row_data, 'file')

                    if project_errors or case_errors or file_errors:
                        error_parts = []
                        if project_errors:
                            error_parts.append(f"项目层: {', '.join([e.field_name for e in project_errors])}")
                        if case_errors:
                            error_parts.append(f"案卷层: {', '.join([e.field_name for e in case_errors])}")
                        if file_errors:
                            error_parts.append(f"文件层: {', '.join([e.field_name for e in file_errors])}")
                        fail_messages.append(f"第{idx}行：必填项缺失 - {'；'.join(error_parts)}")
                        fail_count += 1
                        continue

                    year = self._extract_year_from_data(row_data)
                    base_name = row_data.get('title') or row_data.get('mingcheng') or f"导入记录{idx}"
                    record_name = get_unique_name(base_name, existing_names)
                    existing_names.add(record_name)

                    self.record_manager.create_record(
                        batch_id=self.current_batch_id,
                        template_id=self.template_manager.get_template_id(self.current_template),
                        template_name=self.current_template,
                        name=record_name,
                        filing_type=self.current_filing_type,
                        year=year,
                        data=row_data
                    )
                    success_count += 1

            self.archive_tree.refresh()
            self.logger.log("import_records", {"success_count": success_count, "fail_count": fail_count})

            if fail_count == 0:
                QMessageBox.information(self, "导入成功", f"成功导入 {success_count} 条记录")
            else:
                msg = f"导入完成：成功 {success_count} 条，失败 {fail_count} 条\n\n失败详情：\n"
                msg += "\n".join(fail_messages[:10])
                if len(fail_messages) > 10:
                    msg += f"\n...（还有 {len(fail_messages) - 10} 条失败记录）"
                QMessageBox.warning(self, "导入结果", msg)

        except Exception as e:
            QMessageBox.critical(self, "导入错误", f"导入过程中发生错误：{str(e)}")

    def _on_validate(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("选择校验模式")
        msg_box.setText("请选择校验范围：")
        msg_box.setInformativeText("【单条校验】仅校验当前表单记录\n【批次自查】遍历当前批次所有记录并检查重复编号")
        msg_box.setIcon(QMessageBox.Question)
        
        single_btn = msg_box.addButton("单条校验", QMessageBox.AcceptRole)
        batch_btn = msg_box.addButton("批次自查", QMessageBox.RejectRole)
        msg_box.setDefaultButton(single_btn)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == single_btn:
            self._validate_single_record()
        elif msg_box.clickedButton() == batch_btn:
            self._validate_batch_records()

    def _validate_single_record(self):
        data = self._collect_field_data()
        
        if self.current_filing_type == 'item':
            file_fields = [f for f in self.current_fields if f.get('layer', 'file') == 'file']
            errors = self.validator.validate_record(file_fields, data)
            if errors:
                field_names = [e.field_name for e in errors]
                msg = f"以下字段是必填项，请填写后再保存：\n{'、'.join(field_names)}"
                QMessageBox.warning(self, "校验失败", msg)
            else:
                QMessageBox.information(self, "校验通过", "所有字段校验通过")
        else:
            project_errors = self._validate_by_layer(data, 'project')
            case_errors = self._validate_by_layer(data, 'case')
            file_errors = self._validate_by_layer(data, 'file')
            
            if project_errors or case_errors or file_errors:
                self._show_layered_errors(project_errors, case_errors, file_errors)
            else:
                QMessageBox.information(self, "校验通过", "所有字段校验通过")

    def _validate_batch_records(self):
        if not self.current_batch_id:
            QMessageBox.warning(self, "提示", "请先选择批次")
            return

        records = self.record_manager.get_records_by_batch(self.current_batch_id)
        if not records:
            QMessageBox.information(self, "提示", "当前批次没有记录")
            return

        all_errors = []
        for record in records:
            record_id = record.get('id')
            values = record.get('values', {})
            errors = self.validator.validate_record(self.current_fields, values)
            if errors:
                all_errors.append({
                    'record_id': record_id,
                    'errors': errors
                })

        duplicate_errors = self.validator.validate_batch_duplicates(records)

        self._show_batch_validation_result(all_errors, duplicate_errors)

    def _on_batch_changed(self, index):
        self.current_batch_id = self.batch_combo.itemData(index)
        print(f"批次切换: index={index}, batch_id={self.current_batch_id}")
        self.delete_batch_btn.setEnabled(self.current_batch_id is not None)

    def _on_new_batch(self):
        from db.database import get_cursor
        from datetime import datetime
        
        # 生成默认批次名称建议
        default_name = f"批次_{datetime.now().strftime('%Y%m%d')}"
        
        while True:
            name, ok = QInputDialog.getText(self, "新建批次", 
                "请输入批次名称（必填）：\n建议使用有意义的名称，如【采购项目2024年第一批】",
                text=default_name)
            
            if not ok:
                return  # 用户取消
            
            if not name.strip():
                QMessageBox.warning(self, "提示", "批次名称不能为空，请重新输入")
                continue
            
            try:
                with get_cursor() as cursor:
                    cursor.execute("INSERT INTO batches (name, template_name) VALUES (?, ?)", (name.strip(), ''))
                self._load_batches()
                # 查找并选中新创建的批次
                for i in range(self.batch_combo.count()):
                    if self.batch_combo.itemText(i).startswith(name.strip()):
                        self.batch_combo.setCurrentIndex(i)
                        break
                QMessageBox.information(self, "成功", f"批次【{name.strip()}】已创建")
                self.archive_tree.refresh()
                return
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建失败: {e}")
                return

    def _on_delete_batch(self):
        if not self.current_batch_id:
            return

        reply = QMessageBox.question(self, "确认删除", "确定要删除此批次吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                from db.database import get_cursor
                with get_cursor() as cursor:
                    cursor.execute("DELETE FROM batches WHERE id = ?", (self.current_batch_id,))
                self._load_batches()
                self.current_batch_id = None
                QMessageBox.information(self, "成功", "批次已删除")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def _load_cache(self):
        template_id = self.template_manager.get_template_id(self.current_template)
        if template_id:
            cache = self.cache_manager.get_cache(template_id)
            if cache:
                for k, v in cache.items():
                    w = self.form_widget.findChild(QLineEdit, k)
                    if w:
                        w.setText(v)

    def save_auto_cache(self):
        if not self.current_record_id and not self.current_batch_id:
            return
        template_id = self.template_manager.get_template_id(self.current_template)
        if template_id:
            self.cache_manager.save_cache(self.current_record_id, template_id, self._collect_field_data())

    # ──────────────────────────────── 目录树事件处理 ────────────────────────

    def _on_tree_batch_selected(self, batch_id):
        """点击批次节点：切换批次，清空表单"""
        try:
            self.current_batch_id = batch_id

            idx = self.batch_combo.findData(batch_id)
            if idx >= 0:
                self.batch_combo.setCurrentIndex(idx)

            # 清空表单，准备新建
            self.current_record_id = None
            self.is_new_record = True
            self._clear_form()
        except Exception:
            pass

    def _on_tree_year_selected(self, batch_id, template_name, year):
        """点击年份节点：切换模板+批次，清空表单，准备新建"""
        try:
            # 切换批次
            self.current_batch_id = batch_id
            idx = self.batch_combo.findData(batch_id)
            if idx >= 0:
                self.batch_combo.setCurrentIndex(idx)

            # 切换模板
            if template_name:
                idx = self.template_combo.findText(template_name)
                if idx >= 0:
                    self.template_combo.setCurrentIndex(idx)

            # 清空表单，准备新建
            self.current_record_id = None
            self.is_new_record = True
            self._clear_form()
        except Exception:
            pass

    def _on_tree_record_selected(self, record_id):
        """点击记录节点：加载记录到表单，进入编辑模式"""
        try:
            record = self.record_manager.get_record(record_id)
            if record:
                self.current_record_id = record_id
                self.current_batch_id = record.get('batch_id')
                self.is_new_record = False

                idx = self.batch_combo.findData(self.current_batch_id)
                if idx >= 0:
                    self.batch_combo.setCurrentIndex(idx)

                template_id = record.get('template_id')
                if template_id:
                    tmpl_name = self.template_manager.get_template_name(template_id)
                    if tmpl_name:
                        idx = self.template_combo.findText(tmpl_name)
                        if idx >= 0:
                            self.template_combo.setCurrentIndex(idx)

                from PySide6.QtCore import QTimer
                QTimer.singleShot(50, lambda: self._load_record_to_form(record))

        except Exception:
            pass

    def _on_toggle_tree(self):
        """切换档案目录面板显示/隐藏"""
        if self.right_panel.isVisible():
            self._tree_hidden = True
            sizes = self.splitter.sizes()
            total_width = sum(sizes)
            new_left = int(total_width * 0.65)
            new_mid = total_width - new_left
            
            self.left_panel.setMaximumWidth(1000)
            self.splitter.setSizes([new_left, new_mid, 1])
            self.right_panel.hide()
            self.tree_toggle_btn.setText("◀")
            self.tree_toggle_btn.setToolTip("显示目录")
            self.show_tree_btn.show()
        else:
            self._tree_hidden = False
            self.left_panel.setMaximumWidth(720)
            self.right_panel.show()
            self._update_splitter_sizes()
            self.tree_toggle_btn.setText("▶")
            self.tree_toggle_btn.setToolTip("隐藏目录")
            self.show_tree_btn.hide()

    # ──────────────────────────────── 字段激活处理 ─────────────────────────

    def _on_field_focus(self, widget):
        # 更新三种状态
        self.active_field = widget              # 当前获得焦点
        self.ocr_target_field = widget          # OCR结果写入目标
        self.last_manual_field = widget         # 用户最后手动点击的字段
        self.manual_override_mode = True        # 进入手动覆盖模式

        # 获取字段显示名称
        field_name = self._get_field_display_name(widget.objectName())
        # 更新左侧预览面板的目标字段提示
        self._update_target_field_label(field_name)
        # 激活扫描预览的OCR模式
        if hasattr(self, 'scan_preview'):
            self.scan_preview.enter_ocr_mode(field_name)

    def _on_field_blur(self, widget):
        """失焦时延迟判断，避免切换到预览区时误清除"""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._deferred_clear(widget))

    def _deferred_clear(self, widget):
        """延迟清除：若焦点已转移到扫描预览区则不清除"""
        new_focus = QApplication.focusWidget()
        if new_focus and self._is_child_of_scan_preview(new_focus):
            return
        self._clear_field_activation()

    def _is_child_of_scan_preview(self, widget):
        """判断控件是否属于扫描预览区"""
        w = widget
        while w:
            if w is self.scan_preview:
                return True
            w = w.parent()
        return False

    def _clear_field_activation(self):
        if self.active_field:
            self.active_field.setStyleSheet("""
                QLineEdit { border: 1px solid #D1D5DB; background: white; }
                QTextEdit { border: 1px solid #D1D5DB; background: white; }
            """)
            self.active_field = None
            self.ocr_target_field = None
            # 清除目标字段提示
            self._update_target_field_label("")
            # 退出OCR模式
            if hasattr(self, 'scan_preview'):
                self.scan_preview.enable_ocr_mode(False)
            # 保留last_manual_field，用于支持重新进入该字段

    def _get_field_display_name(self, field_key):
        """根据字段key获取字段显示名称"""
        for field in self.current_fields:
            if field.get('key') == field_key:
                return field.get('name', field_key)
        return field_key

    def _update_target_field_label(self, field_name):
        """更新目标字段提示标签"""
        if hasattr(self, 'target_field_label'):
            # 只有在有扫描件时才显示字段名称
            has_image = False
            if hasattr(self, 'scan_preview') and hasattr(self.scan_preview, '_pixmap'):
                has_image = self.scan_preview._pixmap is not None
            
            if field_name and has_image:
                self.target_field_label.setText(f"【{field_name}】")
                self.target_field_label.show()
            else:
                self.target_field_label.setText("")
                self.target_field_label.hide()

    # ──────────────────────────────── 事件过滤器 ───────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FocusIn:
            if isinstance(obj, (QLineEdit, QTextEdit)):
                self._on_field_focus(obj)
        elif event.type() == QEvent.FocusOut:
            if isinstance(obj, (QLineEdit, QTextEdit)):
                new_focus = QApplication.focusWidget()
                if new_focus and self._is_child_of_scan_preview(new_focus):
                    pass
                else:
                    self._on_field_blur(obj)
        elif event.type() == QEvent.ToolTip:
            if isinstance(obj, (QLineEdit, QTextEdit)):
                text = obj.text() if isinstance(obj, QLineEdit) else obj.toPlainText()
                if text:
                    font_metrics = obj.fontMetrics()
                    text_width = font_metrics.horizontalAdvance(text)
                    if text_width > obj.width() - 24:
                        QApplication.instance().setOverrideCursor(Qt.ArrowCursor)
                        obj.setToolTip(text)
                    else:
                        obj.setToolTip("")
        return super().eventFilter(obj, event)

    # ──────────────────────────────── OCR 识别相关方法 ──────────────────────

    def _on_scan_region_selected(self, rect):
        """处理扫描预览的区域选择事件"""
        if not self.active_field:
            return

        image_bytes = self.scan_preview.get_cropped_image_bytes()
        if not image_bytes:
            print("警告：未能获取裁剪图片数据")
            return

        self._run_ocr_on_region(image_bytes)

    def _run_ocr_on_region(self, image_bytes):
        import tempfile, os

        # 检查是否正在处理中，防止重复识别
        if self._ocr_is_processing:
            print("警告：OCR正在处理中，请等待完成")
            return

        # 确保有OCR目标字段
        if not self.ocr_target_field:
            print("警告：没有OCR目标字段，请先点击一个字段")
            return

        # 设置处理中锁
        self._ocr_is_processing = True

        # 显示"正在识别"状态
        self._set_ocr_status('recognizing')

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            with open(tmp_path, 'wb') as f:
                f.write(image_bytes)

            from ui.components.ocr.ocr_worker import OCRWorker
            
            if hasattr(self, '_ocr_worker') and self._ocr_worker.isRunning():
                self._ocr_worker.quit()
                self._ocr_worker.wait(2000)

            self._ocr_worker = OCRWorker(tmp_path)
            self._ocr_worker.finished.connect(self._on_ocr_result)
            self._ocr_worker.error.connect(self._on_ocr_error)
            self._ocr_worker.finished.connect(lambda _: self._cleanup_tmp(tmp_path))
            self._ocr_worker.error.connect(lambda _: self._cleanup_tmp(tmp_path))
            self._ocr_worker.start()

        except Exception as e:
            print(f"OCR启动失败: {e}")
            self._cleanup_tmp(tmp_path)
            # 显示"识别失败"状态
            self._set_ocr_status('error')
            # 释放处理中锁
            self._ocr_is_processing = False

    def _cleanup_tmp(self, path):
        """清理临时文件"""
        import os
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass

    def _on_ocr_result(self, text):
        """OCR识别完成后的处理"""
        # 释放处理中锁
        self._ocr_is_processing = False

        if not text or not self.ocr_target_field:
            # 显示"识别失败"状态
            self._set_ocr_status('error')
            return

        # 回填字段 - 写入ocr_target_field
        if isinstance(self.ocr_target_field, QLineEdit):
            self.ocr_target_field.setText(text.strip())
        elif isinstance(self.ocr_target_field, QTextEdit):
            self.ocr_target_field.setPlainText(text.strip())

        # 自动切换到下一字段
        self._focus_next_field()

        # 清除选区
        if hasattr(self, 'scan_preview'):
            self.scan_preview.clear_selection()
        
        # 如果是手动覆盖模式，OCR完成后退出手动模式
        if self.manual_override_mode:
            self.manual_override_mode = False
        
        # 显示"识别成功"状态
        self._set_ocr_status('success')

    def _on_ocr_error(self, error_msg):
        """OCR识别错误处理"""
        # 释放处理中锁
        self._ocr_is_processing = False
        
        print(f"OCR错误: {error_msg}")
        # 清除选区
        if hasattr(self, 'scan_preview'):
            self.scan_preview.clear_selection()
        # 显示"识别失败"状态
        self._set_ocr_status('error')

    def _set_ocr_status(self, status):
        """设置OCR状态提示"""
        if not hasattr(self, 'ocr_status_label'):
            return
        
        if status == 'recognizing':
            self.ocr_status_label.setText("正在识别...")
            self.ocr_status_label.setStyleSheet("font-size: 12px; color: #FEF3C7; padding: 0 15px;")
            self.ocr_status_label.show()
        elif status == 'success':
            self.ocr_status_label.setText("识别成功")
            self.ocr_status_label.setStyleSheet("font-size: 12px; color: #86EFAC; padding: 0 15px;")
            self.ocr_status_label.show()
            # 3秒后隐藏成功提示
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._hide_ocr_status)
        elif status == 'error':
            self.ocr_status_label.setText("识别失败")
            self.ocr_status_label.setStyleSheet("font-size: 12px; color: #FCA5A5; padding: 0 15px;")
            self.ocr_status_label.show()
            # 3秒后隐藏失败提示
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._hide_ocr_status)
        else:
            self._hide_ocr_status()
    
    def _hide_ocr_status(self):
        """隐藏OCR状态提示"""
        if hasattr(self, 'ocr_status_label'):
            self.ocr_status_label.hide()
            self.ocr_status_label.setText("")
    
    def _focus_next_field(self):
        """自动切换到下一个可编辑字段"""
        if not self.ocr_target_field or not hasattr(self, 'form_widget'):
            return

        # 获取当前OCR目标字段的objectName
        current_key = self.ocr_target_field.objectName()
        if not current_key:
            return

        # 找到当前字段在current_fields中的索引
        current_index = -1
        for idx, field in enumerate(self.current_fields):
            if field.get('key') == current_key:
                current_index = idx
                break

        # 找到下一个可编辑字段
        for i in range(current_index + 1, len(self.current_fields)):
            field_key = self.current_fields[i].get('key')
            if not field_key:
                continue

            # 查找对应的控件
            widget = self.form_widget.findChild(QLineEdit, field_key)
            if not widget:
                widget = self.form_widget.findChild(QTextEdit, field_key)

            if widget:
                widget.setFocus()
                # 更新ocr_target_field，但保留last_manual_field
                self.active_field = widget
                self.ocr_target_field = widget
                # 更新目标字段提示
                field_name = self._get_field_display_name(field_key)
                self._update_target_field_label(field_name)
                if hasattr(self, 'scan_preview'):
                    self.scan_preview.enter_ocr_mode(field_name)
                break
    def _apply_style(self):
            self.setStyleSheet("""
                QWidget#toolbar {
                    background: #FFFFFF;
                    border: 1px solid #E5E7EB;
                    border-radius: 8px;
                }
                QLabel#toolbarLabel {
                    color: #6B7280;
                    font-size: 12px;
                    font-weight: 500;
                    background: transparent;
                }
                QLabel#toolbarDivider {
                    color: #9CA3AF;
                    font-size: 14px;
                }
                QComboBox#templateCombo {
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    font-size: 13px;
                    background: white;
                    min-height: 26px;
                    max-height: 26px;
                }
                QComboBox#templateCombo::drop-down {
                    border: none;
                    width: 32px;
                    border-radius: 0 6px 6px 0;
                }
                QComboBox#filingTypeCombo {
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    font-size: 13px;
                    background: white;
                    min-height: 26px;
                    max-height: 26px;
                }
                QComboBox#filingTypeCombo::drop-down {
                    border: none;
                    width: 20px;
                    border-radius: 0 6px 6px 0;
                }
                QComboBox#batchCombo {
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    font-size: 13px;
                    background: white;
                    min-height: 26px;
                    max-height: 26px;
                }
                QComboBox#batchCombo::drop-down {
                    border: none;
                    width: 32px;
                    border-radius: 0 6px 6px 0;
                }
                QComboBox QAbstractItemView {
                    border: 1px solid #E5E7EB;
                    border-radius: 6px;
                    background: white;
                    selection-background-color: #EFF6FF;
                    selection-color: #1E40AF;
                    outline: none;
                    padding: 4px 0;
                }
                QComboBox QAbstractItemView::item {
                    padding: 6px 12px;
                    font-size: 12px;
                    color: #374151;
                    min-height: 24px;
                    margin: 0;
                }
                QComboBox QAbstractItemView::item:hover {
                    background: #EFF6FF;
                    color: #1E40AF;
                }
                QComboBox QAbstractItemView::item:selected {
                    background: #EFF6FF;
                    color: #1E40AF;
                }
                QCheckBox#reviewCheckbox {
                    font-size: 12px;
                    color: #374151;
                    spacing: 6px;
                }
                QCheckBox#reviewCheckbox::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 4px;
                }
                QCheckBox#reviewCheckbox::indicator:unchecked {
                    background: #F3F4F6;
                    border: 1px solid #D1D5DB;
                }
                QCheckBox#reviewCheckbox::indicator:checked {
                    background: #059669;
                    border: 1px solid #047857;
                }
                QPushButton#newBatchBtn, QPushButton#deleteBatchBtn, QPushButton#treeRefreshBtn, QPushButton#treeExpandBtn, QPushButton#treeCollapseBtn {
                    background: transparent;
                    color: #374151;
                    border: 1px solid #D1D5DB;
                    border-radius: 4px;
                    font-size: 14px;
                    min-width: 45px;
                    max-width: 60px;
                    min-height: 28px;
                    max-height: 28px;
                    padding: 0px;
                }
                QPushButton#newBatchBtn:hover, QPushButton#deleteBatchBtn:hover, QPushButton#treeRefreshBtn:hover, QPushButton#treeExpandBtn:hover, QPushButton#treeCollapseBtn:hover {
                    background: #F3F4F6;
                    border-color: #9CA3AF;
                }
                QPushButton#newBatchBtn:pressed, QPushButton#deleteBatchBtn:pressed, QPushButton#treeRefreshBtn:pressed, QPushButton#treeExpandBtn:pressed, QPushButton#treeCollapseBtn:pressed {
                    background: #E5E7EB;
                }
                QPushButton#deleteBatchBtn:disabled { 
                    background: transparent; 
                    color: #9CA3AF;
                    border-color: #E5E7EB;
                }
                QWidget#buttonBar {
                    background: #FFFFFF;
                    border-top: 1px solid #E5E7EB;
                }
                QPushButton#primaryBtn {
                    background: #3B82F6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#primaryBtn:hover { background: #2563EB; }
                QPushButton#draftBtn {
                    background: #6B7280;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#draftBtn:hover { background: #4B5563; }
                QPushButton#fillBtn {
                    background: transparent;
                    color: #374151;
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#fillBtn:hover { 
                    background: #F3F4F6; 
                    border-color: #9CA3AF;
                }
                QPushButton#successBtn {
                    background: #059669;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#successBtn:hover { background: #047857; }
                QPushButton#warningBtn {
                    background: transparent;
                    color: #374151;
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#warningBtn:hover { 
                    background: #F3F4F6; 
                    border-color: #9CA3AF;
                }
                QPushButton#exportBtn {
                    background: transparent;
                    color: #374151;
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#exportBtn:hover { 
                    background: #F3F4F6; 
                    border-color: #9CA3AF;
                }
                QSplitter#mainSplitter::handle {
                    background: #E5E7EB;
                    width: 5px;
                }
                QSplitter#mainSplitter::handle:hover {
                    background: #D1D5DB;
                }
                QLabel#targetFieldLabel {
                    color: rgba(255,255,255,0.9);
                    font-size: 11px;
                    background: rgba(255,255,255,0.2);
                    padding: 2px 8px;
                    border-radius: 4px;
                }
                QLabel#formFieldLabel {
                    color: #6B7280;
                    font-size: 11px;
                    padding-bottom: 1px;
                }
                QLineEdit, QTextEdit, QComboBox {
                    border: 1px solid #D1D5DB;
                    border-radius: 5px;
                    padding: 4px 8px 4px 4px;
                    font-size: 12px;
                    background: white;
                }
                QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                    border-color: #D1D5DB;
                    outline: none;
                }
                QGroupBox#formGroup {
                    background: #FFFFFF;
                    border: 1px solid #E5E7EB;
                    border-radius: 8px;
                    font-weight: 500;
                    color: #374151;
                    font-size: 12px;
                }
                QGroupBox#formGroup::title {
                    left: 12px;
                    padding: 0 8px;
                }
                QLineEdit#treeSearchEdit {
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 12px;
                }
                QLineEdit#treeSearchEdit:focus {
                    border-color: #3B82F6;
                    outline: none;
                }

            """)