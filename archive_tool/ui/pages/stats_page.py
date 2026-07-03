"""
台账统计页面
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QLabel, QGroupBox, QPushButton, QTableWidgetItem,
    QHeaderView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from db.database import get_cursor


class StatsPage(QWidget):
    """台账统计页面"""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_stats()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # 统计卡片
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)

        self.total_label = self._create_stat_card('总录入数', '0', '#3498DB')
        stats_layout.addWidget(self.total_label)

        self.pending_label = self._create_stat_card('待核对', '0', '#F39C12')
        stats_layout.addWidget(self.pending_label)

        self.reviewed_label = self._create_stat_card('已核对', '0', '#27AE60')
        stats_layout.addWidget(self.reviewed_label)

        self.uploaded_label = self._create_stat_card('已上传', '0', '#9B59B6')
        stats_layout.addWidget(self.uploaded_label)

        self.failed_label = self._create_stat_card('上传失败', '0', '#E74C3C')
        stats_layout.addWidget(self.failed_label)

        main_layout.addLayout(stats_layout)

        # 批次统计表
        batch_group = QGroupBox('批次统计')
        batch_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2C3E50;
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                margin-top: 15px;
                padding: 12px 10px 8px 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 8px;
                color: #3498DB;
            }
        """)
        batch_layout = QVBoxLayout()

        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(5)
        self.batch_table.setHorizontalHeaderLabels(
            ['批次ID', '批次名称', '模板', '记录数', '状态']
        )
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                background-color: white;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #34495E,
                    stop: 1 #2C3E50
                );
                color: white;
                padding: 10px;
                border: none;
                font-weight: bold;
            }
        """)

        header = self.batch_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)

        self.batch_table.setColumnWidth(0, 60)
        self.batch_table.setColumnWidth(3, 70)
        self.batch_table.setColumnWidth(4, 70)

        batch_layout.addWidget(self.batch_table)

        batch_group.setLayout(batch_layout)
        main_layout.addWidget(batch_group)

        # 刷新按钮
        refresh_btn = QPushButton('刷新统计')
        refresh_btn.setProperty("class", "primary")
        refresh_btn.clicked.connect(self._load_stats)
        main_layout.addWidget(refresh_btn)

    def _create_stat_card(self, title, value, color):
        """创建统计卡片"""
        card = QGroupBox(title)
        card.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #666;
                border: 1px solid #E5E9EC;
                border-radius: 10px;
                margin-top: 5px;
                padding: 15px 10px 10px 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                left: 0;
                padding: 0 10px;
                color: #888;
            }
        """)
        card_layout = QVBoxLayout()
        value_label = QLabel(value)
        value_label.setStyleSheet(f'''
            font-size: 28px;
            font-weight: bold;
            color: {color};
        ''')
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(value_label)
        card.setLayout(card_layout)
        return card

    def _load_stats(self):
        """加载统计数据"""
        with get_cursor() as cursor:
            # 总录入数
            cursor.execute('SELECT COUNT(*) as count FROM records')
            total = cursor.fetchone()['count']
            self.total_label.findChild(QLabel).setText(str(total))

            # 待核对
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE review_status = ?', ('pending',))
            pending = cursor.fetchone()['count']
            self.pending_label.findChild(QLabel).setText(str(pending))

            # 已核对
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE review_status = ?', ('reviewed',))
            reviewed = cursor.fetchone()['count']
            self.reviewed_label.findChild(QLabel).setText(str(reviewed))

            # 已上传
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE upload_status = ?', ('uploaded',))
            uploaded = cursor.fetchone()['count']
            self.uploaded_label.findChild(QLabel).setText(str(uploaded))

            # 上传失败
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE upload_status = ?', ('failed',))
            failed = cursor.fetchone()['count']
            self.failed_label.findChild(QLabel).setText(str(failed))

            # 批次统计
            cursor.execute('''
                SELECT b.id, b.name, 
                       COALESCE(t.name, b.template_name, 'N/A') as template_name,
                       COUNT(r.id) as record_count
                FROM batches b
                LEFT JOIN templates t ON b.template_id = t.id
                LEFT JOIN records r ON r.batch_id = b.id
                GROUP BY b.id
            ''')
            batches = cursor.fetchall()

            self.batch_table.setRowCount(len(batches))
            for i, batch in enumerate(batches):
                id_item = QTableWidgetItem(str(batch['id']))
                id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_table.setItem(i, 0, id_item)
                
                name_item = QTableWidgetItem(batch['name'])
                name_item.setToolTip(batch['name'])
                self.batch_table.setItem(i, 1, name_item)
                
                template_item = QTableWidgetItem(batch['template_name'] or 'N/A')
                template_item.setToolTip(batch['template_name'] or 'N/A')
                self.batch_table.setItem(i, 2, template_item)
                
                count_item = QTableWidgetItem(str(batch['record_count']))
                count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_table.setItem(i, 3, count_item)
                
                status_item = QTableWidgetItem('正常')
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_table.setItem(i, 4, status_item)
