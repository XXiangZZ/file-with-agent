"""Modal assistant keeps the current record stable while OCR runs in a worker."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QComboBox, QFileDialog, QTextEdit, QListWidget,
    QListWidgetItem, QMessageBox, QCheckBox)
from config.settings import DATA_DIR, BASE_DIR
from assistant.index import KnowledgeIndex
from assistant.parsing import Parser
from assistant.generation import ask, suggest
from assistant.services import ModelService, load_config


class Work(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task

    def run(self):
        try:
            self.result.emit(self.task(self.progress.emit))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class AssistantDialog(QDialog):
    def __init__(self, entry):
        super().__init__(entry)
        self.entry = entry
        self.index = KnowledgeIndex(DATA_DIR / 'knowledge.sqlite3')
        self.worker = None
        self.suggestions = []
        self.originals = []
        self.setWindowTitle('档案著录智能辅助工作台')
        self.resize(980, 780)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('默认仅在本机处理。知识库与档案数据库分开保存；建议确认后仅填入空字段，仍需原有保存和校验。'))
        self.controls = []
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(['规范', '手册', '样例'])
        template = entry.current_template
        scope = template.get('name', '通用') if isinstance(template, dict) else (template or '通用')
        self.scope = QLineEdit(scope)
        self.scope.setPlaceholderText('适用范围：必须与当前档案类型一致，或填写通用')
        row.addWidget(self.kind)
        row.addWidget(self.scope)
        layout.addLayout(row)
        row = QHBoxLayout()
        for title, fn in [('导入 / 增量更新', self.import_files), ('删除选中资料', self.delete_source), ('重建索引', self.rebuild)]:
            self.button(row, title, fn)
        layout.addLayout(row)
        self.sources = QListWidget()
        self.sources.setMaximumHeight(125)
        layout.addWidget(self.sources)
        self.external = QCheckBox('本次窗口允许发送问题和知识库文本到配置的模型 / 嵌入服务（档案原文不发送）')
        layout.addWidget(self.external)
        self.service_label = QLabel()
        layout.addWidget(self.service_label)
        try:
            self.config = load_config(BASE_DIR / 'config' / 'assistant.local.json')
            chat_url = self.config.get('chat_base_url', self.config.get('base_url', '未配置'))
            embedding_url = self.config.get('embedding_base_url', self.config.get('base_url', '未配置'))
            self.service_label.setText(f'聊天服务：{chat_url}；嵌入服务：{embedding_url}')
        except Exception:
            self.config = {}
            self.service_label.setText('服务配置无法读取；使用本地模式')
        self.question = QLineEdit()
        self.question.setPlaceholderText('例如：文件题名如何著录？')
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.button(row, '查规范（带出处）', self.ask)
        self.button(row, '从当前预览原文获取字段建议', self.from_preview)
        self.button(row, '选择档案原文并获取建议', self.choose_original)
        layout.addLayout(row)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.choices = QListWidget()
        self.choices.setMaximumHeight(130)
        layout.addWidget(self.choices)
        row = QHBoxLayout()
        self.button(row, '确认将勾选建议填入空字段', self.apply)
        layout.addLayout(row)
        self.status = QLabel('就绪；样例资料不作为规范问答依据')
        layout.addWidget(self.status)
        self.refresh()

    def button(self, row, title, callback):
        button = QPushButton(title)
        button.clicked.connect(callback)
        row.addWidget(button)
        self.controls.append(button)

    def refresh(self):
        self.sources.clear()
        for row in self.index.sources():
            item = QListWidgetItem(f"[{row['kind']} / {row['scope']}] {row['path']} · {row['imported']}")
            item.setData(Qt.UserRole, row['path'])
            self.sources.addItem(item)

    def start(self, task, callback):
        if self.worker and self.worker.isRunning():
            return
        for widget in self.controls + [self.scope, self.kind, self.external, self.question]:
            widget.setEnabled(False)
        self.status.setText('处理中；OCR 初始化及扫描识别可能较慢，请等待。')
        self.worker = Work(task, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.result.connect(callback)
        self.worker.failed.connect(lambda message: self.output.setPlainText('操作失败；已有索引保留。\n' + message))
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def finished_work(self):
        for widget in self.controls + [self.scope, self.kind, self.external, self.question]:
            widget.setEnabled(True)
        self.status.setText('处理结束；请核对结果和出处')
        self.refresh()

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入知识库资料', '', '资料 (*.txt *.md *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
        if not paths:
            return
        kind, scope = self.kind.currentText(), self.scope.text().strip()
        def task(progress):
            results = []
            service = ModelService(self.config) if self.external.isChecked() and self.config.get('embedding_model') else None
            for path in paths:
                try:
                    results.append(f'{path}: {self.index.import_file(path, kind, scope, progress, embeddings=service)}')
                except Exception as exc:
                    if service:
                        try:
                            local_result = self.index.import_file(path, kind, scope, progress)
                            results.append(f'{path}: 嵌入失败，已回退本地索引：{local_result}')
                            continue
                        except Exception:
                            pass
                    results.append(f'{path}: 失败，原索引保留：{exc}')
            return '\n'.join(results)
        self.start(task, self.output.setPlainText)

    def delete_source(self):
        item = self.sources.currentItem()
        if item and QMessageBox.question(self, '删除知识库资料', '删除选中资料的全部索引？原始文件不会删除。') == QMessageBox.Yes:
            self.index.delete(item.data(Qt.UserRole))
            self.refresh()

    def rebuild(self):
        self.start(lambda progress: self.index.rebuild(progress), self.output.setPlainText)

    def ask(self):
        query, scope, external = self.question.text().strip(), self.scope.text().strip(), self.external.isChecked()
        if not query or not scope:
            return
        def task(progress):
            try:
                service = ModelService(self.config) if external else None
                result = ask(self.index, query, scope,
                             embeddings=service if service and self.config.get('embedding_model') else None,
                             service=service)
            except Exception:
                if not external:
                    raise
                result = ask(self.index, query, scope)
                result['answer'] = '外部服务不可用，已退回本地证据摘录。\n' + result['answer']
            return self.render_answer(result)
        self.start(task, self.output.setPlainText)

    @staticmethod
    def render_answer(result):
        claims = result.get('claims', [])
        answer = result['answer']
        if claims:
            answer = '\n'.join(f"{claim['text']} [{', '.join(claim['citation_ids'])}]" for claim in claims)
        return answer + '\n\n' + '\n\n'.join(
            f"来源：{c['source']} · 第 {c['page']} 页 · 字符 {c.get('start_index', 0)}\n{c['quote']}"
            for c in result['citations'])

    def from_preview(self):
        paths = getattr(self.entry.scan_preview, 'source_paths', [])
        if not paths:
            QMessageBox.information(self, '缺少原文', '当前预览没有关联文件，请先打开扫描件或选择档案原文。')
            return
        self.generate(paths)

    def choose_original(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '为当前档案选择原文（仅本地解析）', '', '原文 (*.txt *.md *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
        if paths:
            self.generate(paths)

    def generate(self, paths):
        self.choices.clear()
        self.suggestions = []
        fields = list(self.entry.current_fields)
        def task(progress):
            parser = Parser()
            docs = [doc for path in paths for doc in parser.parse(path, progress)]
            return suggest(docs, fields)
        self.start(task, self.show_suggestions)

    def show_suggestions(self, suggestions):
        self.suggestions = suggestions
        messages = []
        for i, suggestion in enumerate(suggestions):
            if suggestion['value'] is None:
                messages.append(f"{suggestion['name']}：{suggestion['reason']}")
                continue
            c = suggestion['citation']
            messages.append(f"{suggestion['name']} → {suggestion['value']}\n原文：{c['quote']}\n来源：{c['source']} 第 {c['page']} 页\n{suggestion['warning']}")
            item = QListWidgetItem(f"{suggestion['name']}：{suggestion['value']}")
            item.setData(Qt.UserRole, i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.choices.addItem(item)
        self.output.setPlainText('\n\n'.join(messages) or '当前模板没有题名、日期或责任者字段。')

    def apply(self):
        selected = [self.suggestions[self.choices.item(i).data(Qt.UserRole)]
                    for i in range(self.choices.count()) if self.choices.item(i).checkState() == Qt.Checked]
        if not selected:
            return
        if QMessageBox.question(self, '确认回填', '已核对原文与来源，确认将勾选建议填入当前表单空字段？') != QMessageBox.Yes:
            return
        from assistant.form_fill import fill_empty
        applied, skipped = fill_empty(self.entry, selected)
        self.status.setText(f'已回填 {len(applied)} 项；跳过 {len(skipped)} 项（已有值或字段不支持）。请按原流程校验和保存。')

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.status.setText('正在处理，请等待完成后关闭，以免中断 OCR 或索引事务。')
            return
        super().reject()
