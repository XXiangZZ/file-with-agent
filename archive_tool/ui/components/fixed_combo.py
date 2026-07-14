"""
固定位置下拉框 —— 自动设置 QListView 视图，样式统一
"""
from PySide6.QtWidgets import QComboBox, QListView


class FixedComboBox(QComboBox):
    """下拉框，自动使用 QListView 作为下拉视图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
