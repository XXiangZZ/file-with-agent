"""Visible manual QA entry; no archive values or executable tools are accessed."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QComboBox, QCheckBox, QFileDialog)
from config.settings import DATA_DIR, BASE_DIR, get_resource_path
from assistant.index import KnowledgeIndex
from assistant.manual import prepare_manual, ask_manual, SCOPE
from assistant.services import ModelService, load_config
from .assistant_dialog import Work


class ManualDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('软件使用助手 · 操作手册问答')
        self.resize(880, 740)
        self.index = KnowledgeIndex(DATA_DIR / 'manual.sqlite3')
        self.worker = None
        self.ready = False
        self.config = {}
        self.last_result = None
        layout = QVBoxLayout(self)
        title = QLabel('软件使用助手')
        title.setStyleSheet('font-size:22px; font-weight:bold;')
        layout.addWidget(title)
        intro = QLabel('不知道下一步怎么操作？输入问题，查看操作步骤和手册出处。\n'
                       '助手只解释软件操作，不会点击按钮或修改档案。')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.examples = QComboBox()
        self.examples.addItems(['选择一个常见问题…', '第一次用怎么开始？', '如何导入Excel？',
            '怎么导出当前批次？', '如何保存和恢复草稿？', '日期格式错误如何校验？',
            '扫描件识别怎么用？', '如何查找档案？'])
        self.examples.currentIndexChanged.connect(self.choose_example)
        layout.addWidget(self.examples)
        row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText('例如：如何导入Excel？为什么日期校验不通过？')
        self.question.returnPressed.connect(self.ask)
        row.addWidget(self.question)
        self.ask_button = QPushButton('查操作手册')
        self.ask_button.clicked.connect(self.ask)
        row.addWidget(self.ask_button)
        layout.addLayout(row)
        self.external = QCheckBox('本次允许向下方模型服务发送问题及操作手册内容')
        layout.addWidget(self.external)
        self.service_label = QLabel()
        self.service_label.setWordWrap(True)
        try:
            self.config = load_config(BASE_DIR / 'config' / 'assistant.local.json')
            available = bool(self.config.get('chat_model') or self.config.get('embedding_model'))
            self.external.setEnabled(available)
            self.service_label.setText('服务目标：' + self.config.get('base_url', '未配置') +
                ('；勾选后才调用，档案字段和档案原文不发送。' if available else
                 '。当前使用本地手册检索；配置模型后可使用模型辅助回答。'))
        except Exception:
            self.external.setEnabled(False)
            self.service_label.setText('模型配置无法读取；当前使用本地手册检索。')
        layout.addWidget(self.service_label)
        self.model_available = self.external.isEnabled()
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText('回答将在这里显示，并附上手册名称、位置和引用原文。')
        layout.addWidget(self.output, 1)
        self.status = QLabel('正在准备随软件提供的操作指南…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.import_button = QPushButton('补充本软件操作手册')
        self.import_button.clicked.connect(self.import_manual)
        row.addWidget(self.import_button)
        self.refresh_button = QPushButton('重新读取内置指南')
        self.refresh_button.clicked.connect(self.prepare)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.controls = [self.ask_button, self.question, self.examples, self.import_button,
                         self.refresh_button]
        self.set_busy(True)
        QTimer.singleShot(0, self.prepare)

    def choose_example(self, index):
        if index > 0:
            self.question.setText(self.examples.itemText(index))

    def set_busy(self, busy):
        for control in self.controls:
            control.setEnabled(not busy)
        self.external.setEnabled(not busy and self.model_available)

    def start(self, task, callback):
        if self.worker and self.worker.isRunning():
            return
        self.set_busy(True)
        self.worker = Work(task, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.result.connect(callback)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def show_error(self, error):
        self.status.setText('操作未完成；可以重试或重新读取指南。')
        self.output.setPlainText('处理失败：' + error)

    def prepare(self):
        self.status.setText('正在准备操作手册索引…')
        def finished(count):
            self.ready = True
            self.status.setText(f'已准备 {count} 篇内置操作指南，可直接提问；当前未调用模型。')
        self.start(lambda progress: prepare_manual(self.index, get_resource_path('resources/manual'), progress), finished)

    def ask(self):
        if self.worker and self.worker.isRunning():
            return
        query = self.question.text().strip()
        if not query:
            self.status.setText('请输入操作问题，或选择一个常见问题。')
            return
        if not self.ready:
            self.status.setText('请先点击“重新读取内置指南”完成手册准备。')
            return
        external = self.external.isChecked()
        self.status.setText('正在查找与问题相关的操作步骤…')
        def task(progress):
            if not external:
                return ask_manual(self.index, query)
            try:
                service = ModelService(self.config)
                return ask_manual(self.index, query, service,
                    use_embeddings=bool(self.config.get('embedding_model')))
            except Exception:
                result = ask_manual(self.index, query)
                result['notice'] = '模型服务不可用，已退回本地手册检索。'
                return result
        self.start(task, self.show_result)

    def show_result(self, result):
        self.last_result = result
        sections = [result.get('notice', ''), result['answer']]
        for i, cite in enumerate(result['citations'], 1):
            sections.append(f"[{i}] {cite['quote']}\n\n出处：{cite['source']}\n"
                            f"第 {cite['page']} 页 / 字符位置 {cite.get('start_index', 0)}")
        self.output.setPlainText('\n\n'.join(section for section in sections if section))
        self.status.setText(f"{result['mode']} · 找到 {result['retrieved']} 个候选片段 · "
                            f"展示 {len(result['citations'])} 处依据 · "
                            + ('已调用生成模型' if result['model_used'] else '未调用生成模型'))

    def import_manual(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '补充操作手册（仅选本软件的指南）', '',
            '手册 (*.txt *.md *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
        if not paths:
            return
        self.status.setText('正在解析手册；扫描资料的 OCR 可能较慢…')
        def task(progress):
            results = []
            service = ModelService(self.config) if self.external.isChecked() and self.config.get('embedding_model') else None
            for path in paths:
                try:
                    message = self.index.import_file(path, '手册', SCOPE, progress, embeddings=service)
                except Exception as exc:
                    message = f'导入失败，原索引保留：{exc}'
                results.append(f'{path}: {message}')
            return '\n'.join(results)
        def finished(text):
            self.output.setPlainText(text + '\n\n为便于检索，建议每一节以操作名称开头，并以编号列出步骤。'
                '\n新导入的手册会参与本地检索；勾选外部服务时也会发送所需手册内容。')
            self.status.setText('手册处理结束，请查看各文件结果。')
        self.start(task, finished)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.status.setText('正在处理，请等待结束后关闭。')
            return
        super().reject()
