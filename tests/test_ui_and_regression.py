import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import pytest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QTextEdit, QMessageBox
from PySide6.QtCore import Qt, QEventLoop, QTimer
from core.validation import Validator


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_fill_empty_preserves_existing_and_checks_validation(app):
    from assistant.form_fill import fill_empty
    class Entry:
        current_fields = [{'key': 'title', 'name': '题名'}, {'key': 'date', 'name': '日期', 'type': 'date'}]
        validator = Validator()
        def _collect_field_data(self):
            return {'title': title.text(), 'date': date.text()}
    entry = Entry()
    entry.form_widget = QWidget()
    layout = QVBoxLayout(entry.form_widget)
    title, date = QLineEdit('已填写内容'), QLineEdit()
    title.setObjectName('title')
    date.setObjectName('date')
    layout.addWidget(title)
    layout.addWidget(date)
    applied, skipped = fill_empty(entry, [{'key': 'title', 'value': '建议题名'}, {'key': 'date', 'value': '20261107'}])
    assert applied == ['date'] and skipped == ['title']
    assert title.text() == '已填写内容' and date.text() == '20261107'


def test_worker_is_nonblocking_and_close_guarded(app, tmp_path, monkeypatch):
    from ui.components import assistant_dialog as ui
    monkeypatch.setattr(ui, 'DATA_DIR', tmp_path)
    class Entry(QWidget):
        current_template = {'name': '文书'}
        current_fields = []
    parent = Entry()
    dialog = ui.AssistantDialog(parent)
    import threading
    release = threading.Event()
    dialog.start(lambda progress: release.wait(2) or 'done', lambda result: None)
    app.processEvents()
    assert not dialog.controls[0].isEnabled()
    dialog.reject()
    assert '正在处理' in dialog.status.text()
    release.set()
    loop = QEventLoop()
    dialog.worker.finished.connect(loop.quit)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    app.processEvents()
    assert dialog.controls[0].isEnabled()
    dialog.reject()


def test_existing_validation_and_excel_export(app, tmp_path, monkeypatch):
    from core.export_manager import ExportManager
    from PySide6.QtWidgets import QFileDialog
    import openpyxl
    validator = Validator()
    assert validator.validate_field({'key': 'a', 'name': '题名', 'required': True}, '').error_type == 'required'
    assert validator.validate_field({'key': 'd', 'name': '日期', 'type': 'date'}, '2026-11-07').error_type == 'format'
    manager = ExportManager()
    rows = [{'id': 1, 'template_id': 1, 'values': {'title': '脱敏题名', 'date': '20261107'}}]
    monkeypatch.setattr(manager.record_manager, 'get_records_by_batch', lambda batch_id: rows)
    monkeypatch.setattr(manager.template_manager, 'get_template_by_id', lambda tid: {
        'name': '脱敏模板', 'fields': [{'key': 'title', 'name': '题名'}, {'key': 'date', 'name': '日期'}]})
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path / 'export.xlsx'), ''))
    result = manager.export_batch_by_template(1)
    assert result['success']
    book = openpyxl.load_workbook(result['output_file'])
    assert book['脱敏模板']['A2'].value == '脱敏题名'


def test_service_failure_falls_back_and_default_never_calls_service(app, tmp_path, monkeypatch):
    from ui.components import assistant_dialog as ui
    monkeypatch.setattr(ui, 'DATA_DIR', tmp_path)
    class Entry(QWidget):
        current_template = '文书'
        current_fields = []
    parent = Entry()
    dialog = ui.AssistantDialog(parent)
    path = tmp_path / 'rules.txt'
    path.write_text('题名：照录文件标题。', encoding='utf-8')
    dialog.index.import_file(path, scope='文书')
    dialog.question.setText('题名怎么填写')
    calls = []
    def unavailable(config):
        calls.append(True)
        raise RuntimeError('offline')
    monkeypatch.setattr(ui, 'ModelService', unavailable)
    def complete():
        loop = QEventLoop()
        dialog.worker.finished.connect(loop.quit)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        app.processEvents()
    dialog.ask()
    complete()
    assert not calls
    assert '照录文件标题' in dialog.output.toPlainText()
    dialog.external.setChecked(True)
    dialog.ask()
    complete()
    assert calls and '退回本地' in dialog.output.toPlainText()
    dialog.reject()


def test_manual_dialog_ready_query_and_explicit_model_opt_in(app, tmp_path, monkeypatch):
    from ui.components import manual_dialog as ui
    monkeypatch.setattr(ui, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(ui, 'load_config', lambda path: {
        'base_url': 'http://localhost:11434/v1', 'chat_model': 'mock-only'})
    calls = []
    def unavailable(config):
        calls.append(True)
        raise RuntimeError('offline')
    monkeypatch.setattr(ui, 'ModelService', unavailable)
    dialog = ui.ManualDialog()
    def wait_idle():
        loop = QEventLoop()
        def poll():
            if dialog.worker and not dialog.worker.isRunning():
                loop.quit()
        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(10)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        timer.stop()
        app.processEvents()
    wait_idle()
    assert dialog.ready and not dialog.external.isChecked()
    dialog.question.setText('如何导入Excel？')
    dialog.ask()
    assert not dialog.ask_button.isEnabled()
    wait_idle()
    assert not calls
    assert '出处：' in dialog.output.toPlainText()
    assert 'Excel导入' in dialog.output.toPlainText()
    assert '未调用生成模型' in dialog.status.text()
    dialog.external.setChecked(True)
    dialog.ask()
    wait_idle()
    assert calls and '退回本地' in dialog.output.toPlainText()
    dialog.question.setText('软件自动联网同步怎么用')
    dialog.external.setChecked(False)
    dialog.ask()
    wait_idle()
    assert '证据不足' in dialog.output.toPlainText()
    dialog.reject()


def test_manual_button_available_in_main_window(app, tmp_path, monkeypatch):
    from db import database
    database.close_connection()
    monkeypatch.setattr(database, 'DATABASE_PATH', tmp_path / 'archive.db')
    database.init_database()
    from core.template_manager import TemplateManager
    TemplateManager().init_database_templates()
    from ui.main_window import MainWindow
    from ui.components import manual_dialog as ui
    shown = []
    class FakeDialog:
        def __init__(self, parent):
            self.parent = parent
        def exec(self):
            shown.append(self.parent)
    monkeypatch.setattr(ui, 'ManualDialog', FakeDialog)
    window = MainWindow()
    window.nav_list.setCurrentRow(2)
    window.manual_button.click()
    assert shown == [window]
    window.clock_timer.stop()
    window.auto_cache_timer.stop()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    window.close()
    database.close_connection()


def test_real_entry_page_and_confirmed_fill(app, tmp_path, monkeypatch):
    from db import database
    database.close_connection()
    monkeypatch.setattr(database, 'DATABASE_PATH', tmp_path / 'archive.db')
    database.init_database()
    from core.template_manager import TemplateManager
    TemplateManager().init_database_templates()
    from ui.pages.entry_page import EntryPage
    from ui.components import assistant_dialog as ui
    monkeypatch.setattr(ui, 'DATA_DIR', tmp_path)
    entry = EntryPage()
    entry.template_combo.setCurrentText('文书')
    app.processEvents()
    dialog = ui.AssistantDialog(entry)
    suggestion = {'key': 'wj_wentiming', 'name': '文件题名', 'value': '脱敏测试题名', 'warning': '',
                  'citation': {'source': 'sample.txt', 'page': 1, 'quote': '题名：脱敏测试题名'}}
    dialog.show_suggestions([suggestion])
    item = dialog.choices.item(0)
    assert item.checkState() == Qt.Unchecked
    item.setCheckState(Qt.Checked)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.No)
    dialog.apply()
    assert not entry._collect_field_data().get('wj_wentiming')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    dialog.apply()
    assert entry._collect_field_data()['wj_wentiming'] == '脱敏测试题名'
    assert entry.current_record_id is None  # No persistence side effect.
    dialog.reject()
    entry.close()
    database.close_connection()
