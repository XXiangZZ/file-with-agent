"""
可折叠分组组件
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFormLayout
)
from PySide6.QtCore import Qt


class CollapsibleGroup(QWidget):
    """可折叠的字段分组"""

    def __init__(self, title: str, expanded: bool = True):
        super().__init__()
        self._expanded = expanded
        self._title = title
        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 标题栏
        header = QWidget()
        header.setStyleSheet("""
            QWidget {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        # 展开/折叠按钮
        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 14px;
                color: #3B82F6;
            }
            QPushButton:hover {
                color: #1D4ED8;
            }
        """)
        self._update_toggle_icon()
        self.toggle_btn.clicked.connect(self.toggle)
        header_layout.addWidget(self.toggle_btn)

        # 标题
        title_label = QLabel(self._title)
        title_label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                color: #1E40AF;
                font-size: 13px;
            }
        """)
        header_layout.addWidget(title_label)

        header_layout.addStretch()
        self.layout.addWidget(header)

        # 内容区域
        self.content = QWidget()
        self.content_layout = QFormLayout(self.content)
        self.content_layout.setContentsMargins(12, 10, 12, 10)
        self.content_layout.setSpacing(8)
        self.content.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #E5E7EB;
                border-top: none;
                border-radius: 0 0 8px 8px;
            }
        """)
        self.layout.addWidget(self.content)

        self.set_expanded(self._expanded)

    def _update_toggle_icon(self):
        """更新切换图标"""
        if self._expanded:
            self.toggle_btn.setText("▼")
        else:
            self.toggle_btn.setText("▶")

    def toggle(self):
        """切换展开/折叠状态"""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        """设置展开状态"""
        self._expanded = expanded
        self._update_toggle_icon()
        self.content.setVisible(expanded)

    def is_expanded(self) -> bool:
        """返回当前展开状态"""
        return self._expanded

    def add_row(self, label: str, widget):
        """添加一行字段"""
        label_widget = QLabel(label)
        label_widget.setStyleSheet("color: #374151; font-size: 13px;")
        self.content_layout.addRow(label_widget, widget)

    def get_layout(self) -> QFormLayout:
        """获取内容布局"""
        return self.content_layout

    def set_title(self, title: str):
        """设置标题"""
        self._title = title