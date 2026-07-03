"""
主窗口 - 企业级美化版 V2.0
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget,
    QLabel, QMessageBox, QGraphicsDropShadowEffect,
    QStatusBar
)
from PySide6.QtCore import Qt, QTimer, QSize, QDateTime
from PySide6.QtGui import QColor

from ui.pages.entry_page import EntryPage
from ui.pages.draft_page import DraftPage
from ui.pages.search_page import SearchPage
from ui.pages.stats_page import StatsPage
from ui.pages.excel_import_page import ExcelImportPage

from core.logger import Logger


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.logger = Logger()
        self.pages = {}

        self._init_ui()
        self._init_clock()
        self._init_auto_cache()

    # =====================================================
    # UI
    # =====================================================
    def _init_ui(self):

        self.setWindowTitle("档案著录工序桌面工具")

        # 窗口铺满屏幕
        from PySide6.QtGui import QScreen
        screen = QScreen.availableGeometry(self.screen())
        self.resize(screen.width(), screen.height())
        self.setMinimumSize(1200, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # =================================================
        # 左侧导航栏
        # =================================================
        nav_widget = QWidget()
        nav_widget.setFixedWidth(240)

        nav_widget.setStyleSheet("""
            QWidget{
                background-color:#111827;
            }
        """)

        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0,0,0,0)
        nav_layout.setSpacing(0)

        # =================================================
        # LOGO区域
        # =================================================
        logo_widget = QWidget()
        logo_widget.setFixedHeight(110)

        logo_layout = QVBoxLayout(logo_widget)
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo_icon = QLabel("📚")
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_icon.setStyleSheet("""
            font-size:32px;
            color:white;
        """)

        logo_title = QLabel("档案著录系统")
        logo_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_title.setStyleSheet("""
            color:white;
            font-size:18px;
            font-weight:bold;
        """)

        logo_layout.addWidget(logo_icon)
        logo_layout.addWidget(logo_title)

        nav_layout.addWidget(logo_widget)

        # =================================================
        # 导航菜单
        # =================================================
        self.nav_list = QListWidget()

        self.nav_list.setStyleSheet("""
            QListWidget{
                border:none;
                outline:none;
                background:transparent;
                padding-top:10px;
            }

            QListWidget::item{
                color:#D1D5DB;
                margin:5px 12px;
                padding:15px 20px;
                border-radius:10px;
                font-size:15px;
            }

            QListWidget::item:hover{
                background-color:#1F2937;
                color:white;
            }

            QListWidget::item:selected{
                background-color:#2563EB;
                color:white;
                font-weight:bold;
            }
        """)

        nav_items = [
            "📝 档案录入",
            "📋 草稿管理",
            "🔍 检索核对",
            "📊 台账统计",
            "📑 Excel导入"
        ]

        for text in nav_items:
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(200, 55))
            self.nav_list.addItem(item)

        self.nav_list.currentRowChanged.connect(
            self._on_nav_changed
        )

        nav_layout.addWidget(self.nav_list)

        # =================================================
        # 底部版本信息（无登录功能）
        # =================================================
        version_widget = QWidget()
        version_widget.setFixedHeight(50)

        version_widget.setStyleSheet("""
            background-color:#0F172A;
            border-top:1px solid #1E293B;
        """)

        version_layout = QVBoxLayout(version_widget)

        self.version_label = QLabel("档案著录工序桌面工具 v2.0")
        self.version_label.setStyleSheet("""
            color:#64748B;
            font-size:11px;
        """)

        version_layout.addWidget(self.version_label)

        nav_layout.addWidget(version_widget)

        main_layout.addWidget(nav_widget)

        # =================================================
        # 右侧区域
        # =================================================
        right_widget = QWidget()

        right_widget.setStyleSheet("""
            background-color:#F8FAFC;
        """)

        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(20,20,20,20)
        right_layout.setSpacing(0)

        # =================================================
        # 顶部标题栏
        # =================================================
        header_widget = QWidget()
        header_widget.setFixedHeight(60)

        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5,0,5,0)

        self.page_title = QLabel("档案录入")

        self.page_title.setStyleSheet("""
            color:#111827;
            font-size:26px;
            font-weight:700;
        """)

        header_layout.addWidget(self.page_title)

        header_layout.addStretch()

        # 操作按钮栏（将从 EntryPage 获取）
        self.entry_buttons = QWidget()
        header_layout.addWidget(self.entry_buttons)

        header_layout.addStretch()

        self.time_label = QLabel()

        self.time_label.setStyleSheet("""
            color:#6B7280;
            font-size:14px;
        """)

        header_layout.addWidget(self.time_label)

        right_layout.addWidget(header_widget)

        # =================================================
        # 页面容器
        # =================================================
        self.page_stack = QStackedWidget()

        self.page_stack.setStyleSheet("""
            QStackedWidget{
                background:white;
                border-radius:16px;
                border:1px solid #E5E7EB;
            }
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(25)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 30))

        self.page_stack.setGraphicsEffect(shadow)

        right_layout.addWidget(self.page_stack)

        main_layout.addWidget(right_widget)

        # =================================================
        # 页面初始化
        # =================================================
        self.pages["entry"] = EntryPage()
        self.pages["draft"] = DraftPage()
        self.pages["search"] = SearchPage()
        self.pages["stats"] = StatsPage()
        self.pages["excel"] = ExcelImportPage()

        # 将 EntryPage 的按钮栏移动到标题栏
        if hasattr(self.pages["entry"], 'button_bar'):
            button_bar = self.pages["entry"].button_bar
            # 从原布局移除
            button_bar.setParent(None)
            # 添加到标题栏
            layout = QHBoxLayout(self.entry_buttons)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(button_bar)

        self.page_stack.addWidget(self.pages["entry"])
        self.page_stack.addWidget(self.pages["draft"])
        self.page_stack.addWidget(self.pages["search"])
        self.page_stack.addWidget(self.pages["stats"])
        self.page_stack.addWidget(self.pages["excel"])

        self.pages["draft"].draft_load_requested.connect(self._on_load_draft_to_entry)

        self.page_titles = [
            "档案录入",
            "草稿管理",
            "检索核对",
            "台账统计",
            "Excel批量导入"
        ]

        self.nav_list.setCurrentRow(0)

        # =================================================
        # 状态栏
        # =================================================
        status = QStatusBar()

        status.setStyleSheet("""
            QStatusBar{
                background:#F3F4F6;
                border-top:1px solid #E5E7EB;
            }
        """)

        self.setStatusBar(status)

        self.status_label = QLabel("系统就绪")
        self.template_label = QLabel("📋 当前模板：选择模板")
        self.cache_label = QLabel("💾 缓存：正常")

        status.addWidget(self.status_label)
        status.addPermanentWidget(self.template_label)
        status.addPermanentWidget(self.cache_label)

    # =====================================================
    # 时钟
    # =====================================================
    def _init_clock(self):

        self.clock_timer = QTimer(self)

        self.clock_timer.timeout.connect(
            self._update_time
        )

        self.clock_timer.start(1000)

        self._update_time()

    def _update_time(self):

        current = QDateTime.currentDateTime()

        self.time_label.setText(
            current.toString("yyyy-MM-dd HH:mm:ss")
        )

    # =====================================================
    # 导航切换
    # =====================================================
    def _on_nav_changed(self, index):

        self.page_stack.setCurrentIndex(index)

        if 0 <= index < len(self.page_titles):
            self.page_title.setText(
                self.page_titles[index]
            )

        # 切换到草稿管理页时自动刷新
        if index == 1:
            self.pages["draft"]._load_drafts()
        # 切换到台账统计页时自动刷新
        if index == 3:
            self.pages["stats"]._load_stats()

    def nav_to_entry_page(self):
        """跳转到录入页"""
        self.nav_list.setCurrentRow(0)

    def _on_load_draft_to_entry(self, draft):
        """加载草稿到录入页"""
        self.nav_to_entry_page()
        entry_page = self.pages["entry"]
        
        if draft.get('batch_id'):
            entry_page.current_batch_id = draft['batch_id']
            idx = entry_page.batch_combo.findText(f"{draft['batch_name']} ")
            if idx >= 0:
                entry_page.batch_combo.setCurrentIndex(idx)
        
        if draft.get('template_name'):
            idx = entry_page.template_combo.findText(draft['template_name'])
            if idx >= 0:
                entry_page.template_combo.setCurrentIndex(idx)
        
        entry_page._fill_from_record_data(draft.get('draft_data', {}))

    # =====================================================
    # 自动缓存
    # =====================================================
    def _init_auto_cache(self):

        from config.settings import AUTO_CACHE_INTERVAL

        self.auto_cache_timer = QTimer()

        self.auto_cache_timer.timeout.connect(
            self._auto_save_cache
        )

        self.auto_cache_timer.start(
            AUTO_CACHE_INTERVAL
        )

    def _auto_save_cache(self):

        current_index = self.page_stack.currentIndex()

        if current_index == 0:

            page = self.pages["entry"]

            if hasattr(page, "save_auto_cache"):
                page.save_auto_cache()

                self.cache_label.setText(
                    "缓存：已自动保存"
                )

    # =====================================================
    # 消息框
    # =====================================================
    def show_message(self, message, level="info"):

        if level == "warning":
            QMessageBox.warning(
                self, "警告", message
            )

        elif level == "error":
            QMessageBox.critical(
                self, "错误", message
            )

        else:
            QMessageBox.information(
                self, "提示", message
            )

    # =====================================================
    # 关闭事件
    # =====================================================
    def closeEvent(self, event):

        reply = QMessageBox.question(
            self,
            "确认退出",
            "确定退出档案著录系统吗？",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:

            self.logger.log(
                "exit",
                {
                    "action":
                    "application_exit"
                }
            )

            event.accept()

        else:
            event.ignore()
