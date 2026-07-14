"""
archive_tree.py  ——  档案目录树（三层结构）

层级：
  批次（第一层，可重命名）
    └─ 模板名称（第二层，如 电网建设 / 文书）
         └─ 年份（第三层，如 2024）
"""

from __future__ import annotations

from typing import Optional, Dict, List

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel, QModelIndex
from PySide6.QtGui import (
    QStandardItemModel,
    QStandardItem,
    QFont,
    QColor,
    QBrush,
)
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QVBoxLayout,
    QTreeView,
    QAbstractItemView,
    QMenu,
    QMessageBox,
    QInputDialog,
)
import os
# ──────────────────────────────────────────────
#  数据层（从数据库加载）
# ──────────────────────────────────────────────

# 模板列表（可扩展）
TEMPLATE_NAMES: list[str] = [
    "采购项目",
    "电网建设",
    "文书",
    "合同",
]


# ──────────────────────────────────────────────
#  自定义条目角色
# ──────────────────────────────────────────────
LEVEL_ROLE    = Qt.ItemDataRole.UserRole + 1   # "batch" | "template" | "year" | "record"
DATA_ROLE     = Qt.ItemDataRole.UserRole + 2   # 原始数据（名称或年份整数）
ID_ROLE       = Qt.ItemDataRole.UserRole + 3   # 数据库 ID
BATCH_ID_ROLE = Qt.ItemDataRole.UserRole + 4   # 批次 ID


# ──────────────────────────────────────────────
#  新建批次对话框
# ──────────────────────────────────────────────
class NewBatchDialog(QDialog):
    """选择模板名称 + 起始年度，填写批次名称"""

    def __init__(self, parent: Optional[QWidget] = None, template_names: Optional[List[str]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建批次")
        self.setMinimumWidth(340)
        self.setModal(True)
        self._template_names = template_names or TEMPLATE_NAMES
        self._build_ui()

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import (
            QVBoxLayout, QFormLayout, QHBoxLayout,
            QLabel, QLineEdit, QComboBox, QSpinBox,
            QDialogButtonBox
        )
        from PySide6.QtCore import QDate
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 16)

        title_lbl = QLabel("新建档案批次")
        title_lbl.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #1E40AF;"
        )
        layout.addWidget(title_lbl)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.batch_name_edit = QLineEdit()
        self.batch_name_edit.setPlaceholderText("例：2025年第一批")
        form.addRow("批次名称：", self.batch_name_edit)

        self.template_combo = QComboBox()
        self.template_combo.addItems(self._template_names)
        form.addRow("模板类型：", self.template_combo)

        year_widget = QWidget()
        year_layout = QHBoxLayout(year_widget)
        year_layout.setContentsMargins(0, 0, 0, 0)
        year_layout.setSpacing(6)

        self.year_from = QSpinBox()
        self.year_from.setRange(1980, 2100)
        self.year_from.setValue(QDate.currentDate().year())

        sep = QLabel("至")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.year_to = QSpinBox()
        self.year_to.setRange(1980, 2100)
        self.year_to.setValue(QDate.currentDate().year())

        year_layout.addWidget(self.year_from)
        year_layout.addWidget(sep)
        year_layout.addWidget(self.year_to)
        form.addRow("年度范围：", year_widget)

        layout.addLayout(form)

        hint = QLabel("年度范围将作为第三层节点展开在模板下方。")
        hint.setStyleSheet("color: #6B7280; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("创建")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btn_box.accepted.connect(self._validate_and_accept)
        btn_box.rejected.connect(self.close)
        layout.addWidget(btn_box)

        self.setStyleSheet(
            """
            QDialog { background: #FFFFFF; }
            QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #3B82F6;
            }
            QPushButton {
                padding: 5px 16px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton[text="创建"] {
                background: #1E40AF;
                color: white;
                border: none;
            }
            QPushButton[text="创建"]:hover { background: #1D4ED8; }
            QPushButton[text="取消"] {
                background: #F3F4F6;
                border: 1px solid #D1D5DB;
            }
            """
        )

    def _validate_and_accept(self) -> None:
        if not self.batch_name_edit.text().strip():
            QMessageBox.warning(self, "提示", "请填写批次名称。")
            return
        if self.year_from.value() > self.year_to.value():
            QMessageBox.warning(self, "提示", "起始年度不能大于结束年度。")
            return
        self.accept()

    def batch_name(self) -> str:
        return self.batch_name_edit.text().strip()

    def template_name(self) -> str:
        return self.template_combo.currentText()

    def year_range(self) -> list[int]:
        return list(range(self.year_from.value(), self.year_to.value() + 1))


# ──────────────────────────────────────────────
#  档案树组件
# ──────────────────────────────────────────────
class ArchiveTree(QWidget):
    """
    四层档案目录树

    层级：
      批次（第一层）
        └─ 模板名称（第二层）
             └─ 年份（第三层）
                  └─ 记录（第四层）

    信号:
        batch_selected(batch_id)         ── 点击批次节点
        year_selected(batch_id, template_name, year)  ── 点击年份节点
        record_selected(record_id)       ── 点击记录节点
    """

    batch_selected  = Signal(int)
    year_selected   = Signal(int, str, int)
    record_selected = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data = self._load_from_db()
        self._build_ui()
        self._populate()

    def _load_from_db(self):
        """从数据库加载档案目录数据（四层结构）"""
        result = {}
        try:
            from db.database import get_cursor
            with get_cursor() as cursor:
                cursor.execute('SELECT id, name FROM batches ORDER BY id DESC')
                for batch in cursor.fetchall():
                    batch_id = batch['id']
                    batch_name = batch['name']
                    result[batch_id] = {
                        'name': batch_name,
                        'templates': {}
                    }

                cursor.execute('''
                    SELECT batch_id, template_name, year
                    FROM batch_templates
                    ORDER BY batch_id DESC, template_name, year DESC
                ''')
                for row in cursor.fetchall():
                    batch_id = row['batch_id']
                    template_name = row['template_name']
                    year = row['year']

                    if batch_id not in result:
                        continue

                    if template_name not in result[batch_id]['templates']:
                        result[batch_id]['templates'][template_name] = {}

                    result[batch_id]['templates'][template_name][year] = []

                cursor.execute('''
                    SELECT 
                        b.id AS batch_id,
                        b.name AS batch_name,
                        r.template_name,
                        r.year,
                        r.id AS record_id,
                        r.name AS record_name
                    FROM records r
                    JOIN batches b ON r.batch_id = b.id
                    WHERE r.year IS NOT NULL
                    ORDER BY b.id DESC, r.template_name, r.year DESC, r.id DESC
                ''')
                for row in cursor.fetchall():
                    batch_id = row['batch_id']
                    template_name = row['template_name'] or '未知模板'
                    year = int(row['year'])
                    record_id = row['record_id']
                    record_name = row['record_name'] or f'记录{record_id}'

                    if batch_id not in result:
                        result[batch_id] = {
                            'name': row['batch_name'],
                            'templates': {}
                        }

                    if template_name not in result[batch_id]['templates']:
                        result[batch_id]['templates'][template_name] = {}

                    if year not in result[batch_id]['templates'][template_name]:
                        result[batch_id]['templates'][template_name][year] = []

                    result[batch_id]['templates'][template_name][year].append({
                        'id': record_id,
                        'name': record_name
                    })
        except Exception as e:
            print(f"目录加载失败: {e}")
        return result

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["档案目录"])

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setFilterKeyColumn(0)

        self.tree_widget = QTreeView()
        self.tree_widget.setModel(self._proxy)
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setAnimated(True)
        self.tree_widget.setIndentation(9)
        self.tree_widget.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tree_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tree_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.tree_widget.clicked.connect(self._on_item_clicked)
        self.tree_widget.setStyleSheet(self._tree_style())

        self._model.itemChanged.connect(self._on_item_renamed)

        layout.addWidget(self.tree_widget)

    def _populate(self) -> None:
        self._model.removeRows(0, self._model.rowCount())

        for batch_id, batch_data in self._data.items():
            batch_name = batch_data['name']
            batch_item = self._make_item(
                batch_name, level="batch"
            )
            batch_item.setData(batch_id, ID_ROLE)
            batch_item.setFlags(
                batch_item.flags()
                | Qt.ItemFlag.ItemIsEditable
            )

            for tmpl_name, years in batch_data['templates'].items():
                tmpl_item = self._make_item(
                    tmpl_name, level="template"
                )
                tmpl_item.setFlags(
                    tmpl_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )

                for year in sorted(years.keys(), reverse=True):
                    year_item = self._make_item(
                        str(year), level="year"
                    )
                    year_item.setData(year, DATA_ROLE)
                    year_item.setData(batch_id, BATCH_ID_ROLE)
                    year_item.setFlags(
                        year_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )

                    # 第四层：记录节点
                    records = years[year]
                    for rec in records:
                        rec_item = self._make_item(
                            rec['name'], level="record"
                        )
                        rec_item.setData(rec['id'], ID_ROLE)
                        rec_item.setFlags(
                            rec_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                        )
                        year_item.appendRow(rec_item)

                    tmpl_item.appendRow(year_item)

                batch_item.appendRow(tmpl_item)

            self._model.appendRow(batch_item)

        self.tree_widget.expandAll()

    @staticmethod
    def _make_item(
        text: str,
        *,
        level: str,
        icon: str = "",
        bold: bool = False,
        color: str = "#111827",
        small: bool = False,
    ) -> QStandardItem:
        item = QStandardItem(text)
        item.setData(level, LEVEL_ROLE)
        item.setData(text, DATA_ROLE)

        font = QFont("Microsoft YaHei")
        font.setPointSize(9)
        font.setBold(False)
        item.setFont(font)
        item.setForeground(QBrush(QColor("#6B7280")))  # 统一用年度的颜色

        return item

    def _on_item_clicked(self, proxy_index: QModelIndex) -> None:
        src_index = self._proxy.mapToSource(proxy_index)
        item = self._model.itemFromIndex(src_index)
        if item is None:
            return

        level: str = item.data(LEVEL_ROLE)

        if level == "batch":
            batch_id = item.data(ID_ROLE)
            self.batch_selected.emit(batch_id)
        elif level == "year":
            batch_id = item.data(BATCH_ID_ROLE)
            year = item.data(DATA_ROLE)
            tmpl_item = item.parent()
            tmpl_name = tmpl_item.data(DATA_ROLE) if tmpl_item else ""
            self.year_selected.emit(batch_id, tmpl_name, int(year))
        elif level == "record":
            record_id = item.data(ID_ROLE)
            self.record_selected.emit(record_id)

    def _on_search(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)
        if text:
            self.tree_widget.expandAll()

    def refresh(self) -> None:
        self._data = self._load_from_db()
        self._populate()

    def _get_template_names_from_db(self) -> List[str]:
        """从数据库获取模板名称列表"""
        names = []
        try:
            from db.database import get_cursor
            with get_cursor() as cursor:
                cursor.execute('SELECT name FROM templates ORDER BY name')
                for row in cursor.fetchall():
                    names.append(row['name'])
        except Exception as e:
            print(f"获取模板列表失败: {e}")
        return names if names else TEMPLATE_NAMES

    def create_new_batch(self) -> None:
        template_names = self._get_template_names_from_db()
        dlg = NewBatchDialog(self, template_names)
        result = dlg.exec()
        if result != QDialog.DialogCode.Accepted:
            return

        batch_name = dlg.batch_name()
        tmpl = dlg.template_name()
        years = dlg.year_range()

        if not batch_name:
            return

        from db.database import get_cursor
        with get_cursor() as cursor:
            cursor.execute("INSERT INTO batches (name, template_name) VALUES (?, ?)", (batch_name, tmpl))
            batch_id = cursor.lastrowid

            for year in years:
                cursor.execute('''
                    INSERT INTO batch_templates (batch_id, template_name, year)
                    VALUES (?, ?, ?)
                ''', (batch_id, tmpl, year))

        self._data[batch_id] = {
            'name': batch_name,
            'templates': {
                tmpl: {}
            }
        }
        for year in years:
            self._data[batch_id]['templates'][tmpl][year] = []

        self._populate()

    def delete_selected_batch(self) -> bool:
        idx = self.tree_widget.currentIndex()
        src = self._proxy.mapToSource(idx)
        item = self._model.itemFromIndex(src)
        if item is None or item.data(LEVEL_ROLE) != "batch":
            return False

        batch_id = item.data(ID_ROLE)
        batch_name: str = item.data(DATA_ROLE)
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除批次「{batch_name}」及其所有档案吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        from db.database import get_cursor
        try:
            with get_cursor() as cursor:
                cursor.execute('''
                    SELECT id FROM records WHERE batch_id = ?
                ''', (batch_id,))
                record_ids = [row['id'] for row in cursor.fetchall()]
                
                for record_id in record_ids:
                    cursor.execute('DELETE FROM record_values WHERE record_id = ?', (record_id,))
                
                cursor.execute('DELETE FROM records WHERE batch_id = ?', (batch_id,))
                cursor.execute('DELETE FROM batch_templates WHERE batch_id = ?', (batch_id,))
                cursor.execute('DELETE FROM batches WHERE id = ?', (batch_id,))
        except Exception as e:
            QMessageBox.warning(self, "提示", f"删除失败: {e}")
            return False

        self._data.pop(batch_id, None)
        self._populate()
        return True

    def _on_context_menu(self, pos) -> None:
        proxy_idx = self.tree_widget.indexAt(pos)
        if not proxy_idx.isValid():
            return

        src = self._proxy.mapToSource(proxy_idx)
        item = self._model.itemFromIndex(src)
        level = item.data(LEVEL_ROLE) if item else None

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                padding: 4px;
                font-family: "Microsoft YaHei";
                font-size: 13px;
            }
            QMenu::item {
                padding: 4px 10px 4px 5px;
                border-radius: 6px;
                color: #374151;
                margin: 1px 2px;
                font-size: 10px;
                min-height: 15px;
            }
            QMenu::item:selected {
                background: #EFF6FF;
                color: #1D4ED8;
            }
            QMenu::item:pressed {
                background: #DBEAFE;
            }
            QMenu::separator {
                height: 1px;
                background: #F3F4F6;
                margin: 4px 8px;
            }
            QMenu::item[danger="true"] {
                color: #DC2626;
            }
            QMenu::item[danger="true"]:selected {
                background: #FEE2E2;
                color: #B91C1C;
            }
        """)

        if level == "batch":
            act_rename = menu.addAction("重命名")
            act_add_tmpl = menu.addAction("添加模板 / 年度")
            menu.addSeparator()
            act_delete = menu.addAction("删除批次")
            act_delete.setProperty("danger", True)

            chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if chosen == act_rename:
                self.tree_widget.edit(proxy_idx)
            elif chosen == act_delete:
                self.delete_selected_batch()
            elif chosen == act_add_tmpl:
                self._add_template_to_batch(item)

        elif level == "template":
            act_add_year = menu.addAction("添加年份")
            menu.addSeparator()
            act_del_tmpl = menu.addAction("删除模板")
            act_del_tmpl.setProperty("danger", True)

            chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if chosen == act_add_year:
                self._add_year_to_template(item)
            elif chosen == act_del_tmpl:
                self._delete_template(item)

        elif level == "year":
            act_del_year = menu.addAction("删除年份")
            act_del_year.setProperty("danger", True)
            chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if chosen == act_del_year:
                self._delete_year(item)

        elif level == "record":
            act_rename = menu.addAction("重命名")
            menu.addSeparator()
            act_delete = menu.addAction("删除记录")
            act_delete.setProperty("danger", True)

            chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if chosen == act_rename:
                self._rename_record(item)
            elif chosen == act_delete:
                self._delete_record(item)

    def _on_item_renamed(self, item: QStandardItem) -> None:
        if item.data(LEVEL_ROLE) != "batch":
            return

        batch_id = item.data(ID_ROLE)
        old_name: str = item.data(DATA_ROLE)
        new_display = item.text().strip()
        new_name = new_display.replace("📦  ", "").replace("📦 ", "").strip()

        if not new_name or new_name == old_name:
            item.setText(f"📦  {old_name}")
            return

        from db.database import get_cursor
        try:
            with get_cursor() as cursor:
                cursor.execute("UPDATE batches SET name = ? WHERE id = ?", (new_name, batch_id))
            self._data[batch_id]['name'] = new_name
            item.setData(new_name, DATA_ROLE)
            item.setText(f"📦  {new_name}")
        except Exception as e:
            QMessageBox.warning(self, "提示", f"重命名失败: {e}")
            item.setText(f"📦  {old_name}")

    def _add_template_to_batch(self, batch_item: QStandardItem) -> None:
        batch_id = batch_item.data(ID_ROLE)
        batch_name: str = batch_item.data(DATA_ROLE)
        template_names = self._get_template_names_from_db()
        dlg = NewBatchDialog(self, template_names)
        dlg.setWindowTitle("添加模板/年度")
        dlg.batch_name_edit.setText(batch_name)
        dlg.batch_name_edit.setEnabled(False)

        result = dlg.exec()
        if result != QDialog.DialogCode.Accepted:
            return

        tmpl = dlg.template_name()
        years = dlg.year_range()

        from db.database import get_cursor
        try:
            with get_cursor() as cursor:
                for year in years:
                    try:
                        cursor.execute('''
                            INSERT INTO batch_templates (batch_id, template_name, year)
                            VALUES (?, ?, ?)
                        ''', (batch_id, tmpl, year))
                    except Exception:
                        pass

            if tmpl not in self._data[batch_id]['templates']:
                self._data[batch_id]['templates'][tmpl] = {}
                for year in years:
                    self._data[batch_id]['templates'][tmpl][year] = []
            else:
                existing = set(self._data[batch_id]['templates'][tmpl].keys())
                for year in years:
                    if year not in existing:
                        self._data[batch_id]['templates'][tmpl][year] = []

            self._populate()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"添加失败: {e}")

    def _add_year_to_template(self, tmpl_item: QStandardItem) -> None:
        batch_item = tmpl_item.parent()
        if batch_item is None:
            return
        batch_id = batch_item.data(ID_ROLE)
        tmpl_name: str = tmpl_item.data(DATA_ROLE)

        year, ok = QInputDialog.getInt(
            self, "添加年份", "请输入年份：", 2024, 1980, 2100
        )
        if not ok:
            return

        from db.database import get_cursor
        try:
            with get_cursor() as cursor:
                cursor.execute('''
                    INSERT INTO batch_templates (batch_id, template_name, year)
                    VALUES (?, ?, ?)
                ''', (batch_id, tmpl_name, year))

            templates = self._data[batch_id].get('templates', {})
            if tmpl_name not in templates:
                templates[tmpl_name] = {}
            if year not in templates[tmpl_name]:
                templates[tmpl_name][year] = []
                self._populate()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"添加失败: {e}")

    def _delete_template(self, tmpl_item: QStandardItem) -> None:
        batch_item = tmpl_item.parent()
        if batch_item is None:
            return
        batch_id = batch_item.data(ID_ROLE)
        tmpl_name: str = tmpl_item.data(DATA_ROLE)

        reply = QMessageBox.question(
            self, "确认删除",
            f"删除模板「{tmpl_name}」及其所有年份和档案？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from db.database import get_cursor
            try:
                with get_cursor() as cursor:
                    cursor.execute('''
                        SELECT id FROM records WHERE batch_id = ? AND template_name = ?
                    ''', (batch_id, tmpl_name))
                    record_ids = [row['id'] for row in cursor.fetchall()]
                    
                    for record_id in record_ids:
                        cursor.execute('DELETE FROM record_values WHERE record_id = ?', (record_id,))
                    
                    cursor.execute('DELETE FROM records WHERE batch_id = ? AND template_name = ?', (batch_id, tmpl_name))
                    cursor.execute('''
                        DELETE FROM batch_templates
                        WHERE batch_id = ? AND template_name = ?
                    ''', (batch_id, tmpl_name))

                self._data[batch_id]['templates'].pop(tmpl_name, None)
                self._populate()
            except Exception as e:
                QMessageBox.warning(self, "提示", f"删除失败: {e}")

    def _delete_year(self, year_item: QStandardItem) -> None:
        tmpl_item = year_item.parent()
        batch_item = tmpl_item.parent() if tmpl_item else None
        if tmpl_item is None or batch_item is None:
            return

        batch_id = batch_item.data(ID_ROLE)
        tmpl_name: str = tmpl_item.data(DATA_ROLE)
        year: int = year_item.data(DATA_ROLE)
        
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除年份「{year}」及其所有档案吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from db.database import get_cursor
        try:
            with get_cursor() as cursor:
                cursor.execute('''
                    SELECT id FROM records WHERE batch_id = ? AND template_name = ? AND year = ?
                ''', (batch_id, tmpl_name, year))
                record_ids = [row['id'] for row in cursor.fetchall()]
                
                for record_id in record_ids:
                    cursor.execute('DELETE FROM record_values WHERE record_id = ?', (record_id,))
                
                cursor.execute('DELETE FROM records WHERE batch_id = ? AND template_name = ? AND year = ?', (batch_id, tmpl_name, year))
                cursor.execute('''
                    DELETE FROM batch_templates
                    WHERE batch_id = ? AND template_name = ? AND year = ?
                ''', (batch_id, tmpl_name, year))

            templates = self._data[batch_id].get('templates', {})
            if tmpl_name in templates:
                years = templates[tmpl_name]
                if year in years:
                    del years[year]
                    self._populate()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"删除失败: {e}")

    def _rename_record(self, item: QStandardItem) -> None:
        from PySide6.QtWidgets import QInputDialog
        record_id = item.data(ID_ROLE)
        old_name = item.data(DATA_ROLE)

        new_name, ok = QInputDialog.getText(
            self, "重命名记录", "请输入新名称：", text=old_name
        )
        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()
        try:
            from db.database import get_cursor
            with get_cursor() as cursor:
                cursor.execute(
                    "UPDATE records SET name = ? WHERE id = ?",
                    (new_name, record_id)
                )
            item.setText(new_name)
            item.setData(new_name, DATA_ROLE)
        except Exception as e:
            QMessageBox.warning(self, "失败", f"重命名失败: {e}")

    def _delete_record(self, item: QStandardItem) -> None:
        record_id = item.data(ID_ROLE)
        record_name = item.data(DATA_ROLE)

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除记录「{record_name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from db.database import get_cursor
            with get_cursor() as cursor:
                cursor.execute("DELETE FROM records WHERE id = ?", (record_id,))
                cursor.execute("DELETE FROM record_values WHERE record_id = ?", (record_id,))
            self.refresh()
        except Exception as e:
            QMessageBox.warning(self, "失败", f"删除失败: {e}")

    @staticmethod
    def _tree_style() -> str:
        base = os.path.dirname(os.path.abspath(__file__))
        # archive_tree.py -> components -> ui -> archive_tool -> resources
        resources = os.path.join(base, "..", "..", "resources").replace("\\", "/")
        right = f"{resources}/chevron-right.svg"
        down  = f"{resources}/chevron-down.svg"

        return f"""
        QTreeView {{
            background: #FFFFFF;
            border: none;
            font-family: "Microsoft YaHei", sans-serif;
            outline: none;
        }}
        QTreeView::item {{
            padding: 1px 8px 1px 2px;
            min-height: 18px;
        }}
        QTreeView::item:hover {{
            background: #F0F4FF;
        }}
        QTreeView::item:selected {{
            background: #E8EFFE;
            color: #1E40AF;
            border-left: 2px solid #3B82F6;
        }}
        QTreeView::branch {{
            background: #FFFFFF;
            width: 8px;
        }}
        QTreeView::branch:has-children:!has-siblings:closed,
        QTreeView::branch:closed:has-children:has-siblings {{
            image: url({right});
        }}
        QTreeView::branch:open:has-children:!has-siblings,
        QTreeView::branch:open:has-children:has-siblings {{
            image: url({down});
        }}
        """