"""
模板字段管理页面
功能说明：
  1. 选择模板，查看该模板的所有字段
  2. 添加新字段（设置字段名称、字段类型、必填选项、层级）
  3. 编辑已有字段
  4. 删除自定义字段
  5. 字段排序
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QLabel, QMessageBox, QCheckBox,
    QDialog, QDialogButtonBox, QListView, QHeaderView,
    QTextEdit
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor

from core.template_manager import TemplateManager


class TemplateFieldPage(QWidget):
    """模板字段管理页面"""

    def __init__(self):
        super().__init__()
        self.template_manager = TemplateManager()
        
        self.current_template_id = None
        self.current_template_name = None
        self.editing_field_id = None
        
        self._init_ui()
        self._load_templates()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setSpacing(12)

        label = QLabel("选择模板：")
        label.setStyleSheet("font-weight: 600; font-size: 14px; color: #374151;")
        header_layout.addWidget(label)

        self.template_combo = QComboBox()
        self.template_combo.setView(QListView())
        self.template_combo.setObjectName("templateCombo")
        self.template_combo.setFixedHeight(32)
        self.template_combo.setMinimumWidth(200)
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        header_layout.addWidget(self.template_combo)

        header_layout.addStretch()

        self.create_template_btn = QPushButton("＋ 新建模板")
        self.create_template_btn.setStyleSheet("""
            QPushButton {
                background: #059669;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.create_template_btn.clicked.connect(self._on_create_template)
        header_layout.addWidget(self.create_template_btn)

        self.add_field_btn = QPushButton("＋ 添加字段")
        self.add_field_btn.setStyleSheet("""
            QPushButton {
                background: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover { background: #2563EB; }
            QPushButton:disabled { background: #9CA3AF; }
        """)
        self.add_field_btn.clicked.connect(self._on_add_field)
        self.add_field_btn.setEnabled(False)
        header_layout.addWidget(self.add_field_btn)

        main_layout.addWidget(header_widget)

        field_count_label = QLabel()
        field_count_label.setObjectName("fieldCountLabel")
        field_count_label.setStyleSheet("font-size: 12px; color: #6B7280;")
        main_layout.addWidget(field_count_label)
        self.field_count_label = field_count_label

        self.fields_table = QTableWidget()
        self.fields_table.setObjectName("fieldsTable")
        self.fields_table.setColumnCount(6)
        self.fields_table.setHorizontalHeaderLabels([
            "字段名称", "字段类型", "层级", "必填", "提示", "操作"
        ])
        self.fields_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fields_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.fields_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.fields_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.fields_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.fields_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.fields_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                font-size: 13px;
                background: white;
            }
            QTableWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #F3F4F6;
            }
            QTableWidget::item:selected {
                background: #EFF6FF;
                color: #1D4ED8;
            }
            QHeaderView::section {
                background: #F9FAFB;
                border: none;
                border-bottom: 2px solid #E5E7EB;
                padding: 8px 12px;
                font-weight: 600;
                font-size: 12px;
                color: #374151;
            }
        """)
        main_layout.addWidget(self.fields_table, stretch=1)

        footer_widget = QWidget()
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setSpacing(8)
        footer_layout.addStretch()

        self.refresh_btn = QPushButton("↻ 刷新")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #F3F4F6;
                color: #374151;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background: #E5E7EB; }
        """)
        self.refresh_btn.clicked.connect(self._load_fields)
        footer_layout.addWidget(self.refresh_btn)

        main_layout.addWidget(footer_widget)

    def _load_templates(self):
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("请选择模板", None)
        
        templates = self.template_manager.get_templates_with_id()
        for template in templates:
            self.template_combo.addItem(template['name'], template['id'])
        
        self.template_combo.blockSignals(False)

    def _on_template_changed(self, index):
        self.current_template_id = self.template_combo.currentData()
        self.current_template_name = self.template_combo.currentText()
        
        if self.current_template_id:
            self.add_field_btn.setEnabled(True)
            self._load_fields()
        else:
            self.add_field_btn.setEnabled(False)
            self.fields_table.setRowCount(0)
            self.field_count_label.setText("")

    def _load_fields(self):
        if not self.current_template_id:
            return

        fields = self.template_manager.get_fields(self.current_template_name)
        self.fields_table.setRowCount(0)

        for field in fields:
            row = self.fields_table.rowCount()
            self.fields_table.insertRow(row)

            name_item = QTableWidgetItem(field['name'])
            name_item.setData(Qt.UserRole, field.get('id'))
            name_item.setData(Qt.UserRole + 1, field.get('is_custom', False))
            name_item.setData(Qt.UserRole + 2, field['key'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            
            type_map = {
                'text': '文本',
                'textarea': '多行文本',
                'number': '数字',
                'date': '日期',
                'datetime': '日期时间',
                'dropdown': '下拉选择'
            }
            type_item = QTableWidgetItem(type_map.get(field['type'], field['type']))
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)

            layer_map = {
                'project': '项目层',
                'case': '案卷层',
                'file': '文件层',
                'item': '文件层'
            }
            layer_item = QTableWidgetItem(layer_map.get(field['layer'], field['layer']))
            layer_item.setFlags(layer_item.flags() & ~Qt.ItemIsEditable)

            required_item = QTableWidgetItem("✓" if field['required'] else "")
            required_item.setTextAlignment(Qt.AlignCenter)
            required_item.setFlags(required_item.flags() & ~Qt.ItemIsEditable)
            if field['required']:
                required_item.setForeground(QColor("#EF4444"))

            hint_item = QTableWidgetItem(field.get('hint', ''))
            hint_item.setFlags(hint_item.flags() & ~Qt.ItemIsEditable)

            is_custom = field.get('is_custom', False)
            edit_btn = QPushButton("编辑")
            edit_btn.setFixedSize(56, 24)
            edit_btn.setStyleSheet("""
                QPushButton {
                    background: #DBEAFE;
                    color: #1D4ED8;
                    border: none;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover { background: #BFDBFE; }
            """)
            edit_btn.clicked.connect(lambda checked, r=row: self._on_edit_field(r))

            delete_btn = QPushButton("删除")
            delete_btn.setFixedSize(56, 24)
            delete_btn.setStyleSheet("""
                QPushButton {
                    background: #FEE2E2;
                    color: #DC2626;
                    border: none;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover { background: #FECACA; }
                QPushButton:disabled { background: #F3F4F6; color: #9CA3AF; }
            """)
            delete_btn.setEnabled(is_custom)
            delete_btn.clicked.connect(lambda checked, r=row: self._on_delete_field(r))

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.setSpacing(4)
            action_layout.addWidget(edit_btn)
            action_layout.addWidget(delete_btn)
            action_layout.addStretch()

            self.fields_table.setItem(row, 0, name_item)
            self.fields_table.setItem(row, 1, type_item)
            self.fields_table.setItem(row, 2, layer_item)
            self.fields_table.setItem(row, 3, required_item)
            self.fields_table.setItem(row, 4, hint_item)
            self.fields_table.setCellWidget(row, 5, action_widget)

        self.field_count_label.setText(f"共 {len(fields)} 个字段")

    def _on_create_template(self):
        dialog = TemplateCreateDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self._load_templates()
            QMessageBox.information(self, "成功", "模板已创建")

    def _on_add_field(self):
        dialog = FieldEditDialog(self, template_id=self.current_template_id)
        if dialog.exec() == QDialog.Accepted:
            self._load_fields()
            QMessageBox.information(self, "成功", "字段已添加")

    def _on_edit_field(self, row):
        name_item = self.fields_table.item(row, 0)
        field_id = name_item.data(Qt.UserRole)
        field_key = name_item.data(Qt.UserRole + 2)
        
        field = self.template_manager.get_field_by_id(field_id)
        if not field:
            QMessageBox.warning(self, "提示", "字段不存在或已被删除")
            return
        
        dialog = FieldEditDialog(self, field=field, template_id=self.current_template_id)
        if dialog.exec() == QDialog.Accepted:
            self._load_fields()
            QMessageBox.information(self, "成功", "字段已更新")

    def _on_delete_field(self, row):
        name_item = self.fields_table.item(row, 0)
        field_id = name_item.data(Qt.UserRole)
        field_name = name_item.text()
        
        reply = QMessageBox.warning(
            self, "确认删除",
            f"确定要删除字段「{field_name}」吗？\n删除后，已录入的该字段数据将不再显示。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success = self.template_manager.delete_field(field_id)
            if success:
                self._load_fields()
                QMessageBox.information(self, "成功", "字段已删除")
            else:
                QMessageBox.warning(self, "失败", "删除失败，请重试")


class FieldEditDialog(QDialog):
    """字段编辑对话框"""

    def __init__(self, parent=None, field=None, template_id=None):
        super().__init__(parent)
        self.setWindowTitle("编辑字段" if field else "添加字段")
        self.setMinimumSize(500, 400)
        
        self.field = field
        self.template_id = template_id
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignLeft)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入字段名称")
        self.name_edit.setFixedHeight(32)
        self.name_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3B82F6;
                outline: none;
            }
        """)
        form_layout.addRow("字段名称 *", self.name_edit)

        type_label = QLabel("字段类型")
        type_label.setStyleSheet("font-weight: 500;")
        self.type_combo = QComboBox()
        self.type_combo.setView(QListView())
        self.type_combo.setFixedHeight(32)
        self.type_combo.addItems(["文本", "多行文本", "数字", "日期", "日期时间", "下拉选择"])
        type_map = {
            'text': 0, 'textarea': 1, 'number': 2,
            'date': 3, 'datetime': 4, 'dropdown': 5
        }
        if self.field:
            self.type_combo.setCurrentIndex(type_map.get(self.field.get('type', 'text'), 0))
        form_layout.addRow(type_label, self.type_combo)

        layer_label = QLabel("层级")
        layer_label.setStyleSheet("font-weight: 500;")
        self.layer_combo = QComboBox()
        self.layer_combo.setView(QListView())
        self.layer_combo.setFixedHeight(32)
        self.layer_combo.addItems(["项目层", "案卷层", "文件层"])
        layer_map = {'project': 0, 'case': 1, 'file': 2, 'item': 2}
        if self.field:
            self.layer_combo.setCurrentIndex(layer_map.get(self.field.get('layer', 'file'), 2))
        form_layout.addRow(layer_label, self.layer_combo)

        self.required_check = QCheckBox()
        form_layout.addRow("必填", self.required_check)

        hint_label = QLabel("提示信息")
        hint_label.setStyleSheet("font-weight: 500;")
        self.hint_edit = QLineEdit()
        self.hint_edit.setPlaceholderText("输入字段提示信息（可选）")
        self.hint_edit.setFixedHeight(32)
        self.hint_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3B82F6;
                outline: none;
            }
        """)
        form_layout.addRow(hint_label, self.hint_edit)

        self.dropdown_options_label = QLabel("下拉选项")
        self.dropdown_options_label.setStyleSheet("font-weight: 500;")
        self.dropdown_options_edit = QTextEdit()
        self.dropdown_options_edit.setPlaceholderText("每行一个选项（仅下拉选择类型有效）")
        self.dropdown_options_edit.setMaximumHeight(100)
        self.dropdown_options_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QTextEdit:focus {
                border-color: #3B82F6;
                outline: none;
            }
        """)
        form_layout.addRow(self.dropdown_options_label, self.dropdown_options_edit)

        layout.addWidget(form_widget)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed(self.type_combo.currentIndex())

        if self.field:
            self.name_edit.setText(self.field.get('name', ''))
            self.required_check.setChecked(self.field.get('required', False))
            self.hint_edit.setText(self.field.get('hint', ''))
            if self.field.get('dropdown_options'):
                self.dropdown_options_edit.setText('\n'.join(self.field['dropdown_options']))

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("确定")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_type_changed(self, index):
        is_dropdown = index == 5
        self.dropdown_options_label.setVisible(is_dropdown)
        self.dropdown_options_edit.setVisible(is_dropdown)

    def _on_ok(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入字段名称")
            return

        type_map = {0: 'text', 1: 'textarea', 2: 'number', 3: 'date', 4: 'datetime', 5: 'dropdown'}
        field_type = type_map[self.type_combo.currentIndex()]

        layer_map = {0: 'project', 1: 'case', 2: 'file'}
        layer = layer_map[self.layer_combo.currentIndex()]

        required = self.required_check.isChecked()
        hint = self.hint_edit.text().strip()

        dropdown_options = []
        if field_type == 'dropdown':
            options_text = self.dropdown_options_edit.toPlainText()
            for line in options_text.split('\n'):
                line = line.strip()
                if line:
                    dropdown_options.append(line)

        if self.field:
            self.parent().template_manager.update_field(
                field_id=self.field['id'],
                name=name,
                required=required,
                field_type=field_type,
                layer=layer,
                dropdown_options=dropdown_options,
                hint=hint
            )
        else:
            import hashlib
            timestamp = str(int(__import__('time').time()))
            key = hashlib.md5(f"{self.template_id}_{name}_{timestamp}".encode()).hexdigest()[:16]
            
            self.parent().template_manager.add_field(
                template_id=self.template_id,
                key=key,
                name=name,
                required=required,
                field_type=field_type,
                layer=layer,
                dropdown_options=dropdown_options,
                hint=hint
            )

        self.accept()


class TemplateCreateDialog(QDialog):
    """创建模板对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建模板")
        self.setMinimumSize(400, 280)
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignLeft)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入模板名称")
        self.name_edit.setFixedHeight(32)
        self.name_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3B82F6;
                outline: none;
            }
        """)
        form_layout.addRow("模板名称 *", self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("请输入模板描述（可选）")
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QTextEdit:focus {
                border-color: #3B82F6;
                outline: none;
            }
        """)
        form_layout.addRow("模板描述", self.desc_edit)

        type_label = QLabel("归档类型")
        type_label.setStyleSheet("font-weight: 500;")
        self.filing_type_combo = QComboBox()
        self.filing_type_combo.setView(QListView())
        self.filing_type_combo.setFixedHeight(32)
        self.filing_type_combo.addItems(["以件归档", "以卷归档"])
        form_layout.addRow(type_label, self.filing_type_combo)

        layout.addWidget(form_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("创建")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_ok(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入模板名称")
            return

        description = self.desc_edit.toPlainText().strip()
        filing_type = 'item' if self.filing_type_combo.currentIndex() == 0 else 'volume'

        try:
            self.parent().template_manager.create_template(name, description, filing_type)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "失败", f"创建模板失败: {e}")
            self.reject()