"""Modal assistant keeps the current record stable while OCR runs in a worker."""
import json
from pathlib import Path
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QComboBox, QFileDialog, QTextEdit, QListWidget,
    QListWidgetItem, QMessageBox, QCheckBox, QInputDialog)
from config.settings import DATA_DIR, BASE_DIR
from assistant.index import KnowledgeIndex
from assistant.parsing import Parser
from assistant.generation import ask, suggest
from assistant.services import ModelService, load_config
from assistant.feedback_ui import FeedbackControls


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
        self.external = QCheckBox('本次窗口允许发送问题、知识库证据和工具参数到配置服务；不会自动读取档案字段或扫描件')
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
        mode_row = QHBoxLayout()
        self.agent_mode = QComboBox()
        self.agent_mode.addItem('固定检索问答', 'standard')
        self.agent_mode.addItem('受控 ReAct 工具模式', 'agent')
        self.local_tool = QComboBox()
        for label, name in [('规范证据检索', 'ask_policy'), ('软件手册检索', 'ask_manual'),
                            ('知识库资料状态', 'kb_sources'), ('本地档案关键词检索', 'search_records'),
                            ('本地档案安全详情', 'get_record_detail'), ('当前批次档案列表', 'list_records'),
                            ('当前批次草稿列表', 'list_drafts')]:
            self.local_tool.addItem(label, name)
        mode_row.addWidget(self.agent_mode)
        mode_row.addWidget(self.local_tool)
        layout.addLayout(mode_row)
        self.agent_mode.currentIndexChanged.connect(self._mode_changed)
        self.external.toggled.connect(self._mode_changed)
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.button(row, '查规范（带出处）', self.ask)
        self.button(row, '从当前预览原文获取字段建议', self.from_preview)
        self.button(row, '选择档案原文并获取建议', self.choose_original)
        layout.addLayout(row)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        layout.addWidget(QLabel('待确认执行计划'))
        self.plan_list = QListWidget()
        self.plan_list.setMaximumHeight(150)
        layout.addWidget(self.plan_list)
        plan_row = QHBoxLayout()
        self.reject_plans_button = QPushButton('全部拒绝')
        self.reject_plans_button.clicked.connect(self.reject_plans)
        self.edit_plan_button = QPushButton('编辑选中计划')
        self.edit_plan_button.clicked.connect(self.edit_selected_plan)
        self.execute_plans_button = QPushButton('确认执行勾选计划')
        self.execute_plans_button.clicked.connect(self.execute_selected_plans)
        for button in (self.reject_plans_button, self.edit_plan_button, self.execute_plans_button):
            plan_row.addWidget(button)
            self.controls.append(button)
        layout.addLayout(plan_row)
        self._plan_store = None
        self.choices = QListWidget()
        self.choices.setMaximumHeight(130)
        layout.addWidget(self.choices)
        row = QHBoxLayout()
        self.button(row, '确认将勾选建议填入空字段', self.apply)
        layout.addLayout(row)
        self.status = QLabel('就绪；样例资料不作为规范问答依据')
        layout.addWidget(self.status)
        self.feedback = FeedbackControls(self.index, self.status.setText)
        layout.addWidget(self.feedback)
        self.refresh()
        self._mode_changed()

    def _mode_changed(self, *_):
        is_agent = self.agent_mode.currentData() == 'agent'
        self.local_tool.setVisible(is_agent and not self.external.isChecked())
        self.plan_list.setVisible(is_agent)
        self.reject_plans_button.setVisible(is_agent)
        self.edit_plan_button.setVisible(is_agent)
        self.execute_plans_button.setVisible(is_agent)
        self.plan_list.setEnabled(is_agent)

    def button(self, row, title, callback):
        button = QPushButton(title)
        button.clicked.connect(callback)
        row.addWidget(button)
        self.controls.append(button)

    def refresh(self):
        self.sources.clear()
        expected_model = None
        if self.config.get('embedding_model'):
            endpoint = self.config.get('embedding_base_url', self.config.get('base_url', ''))
            expected_model = f'{endpoint.rstrip("/")}#{self.config["embedding_model"]}'
        for row in self.index.sources():
            vector_state = self.index.vector_state(row['path'], expected_model)['state']
            state_label = {'ready': '向量就绪', 'missing': '未生成向量', 'invalid': '向量失效'}[vector_state]
            item = QListWidgetItem(f"[{row['kind']} / {row['scope']}] {row['path']} · {state_label} · {row['imported']}")
            item.setData(Qt.UserRole, row['path'])
            self.sources.addItem(item)

    def start(self, task, callback):
        if self.worker and self.worker.isRunning():
            return
        for widget in self.controls + [self.scope, self.kind, self.external, self.question,
                                       self.agent_mode, self.local_tool, self.plan_list]:
            widget.setEnabled(False)
        self.feedback.setEnabled(False)
        self.status.setText('处理中；OCR 初始化及扫描识别可能较慢，请等待。')
        self.worker = Work(task, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.result.connect(callback)
        self.worker.failed.connect(lambda message: self.output.setPlainText('操作失败；已有索引保留。\n' + message))
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def finished_work(self):
        for widget in self.controls + [self.scope, self.kind, self.external, self.question,
                                       self.agent_mode, self.local_tool]:
            widget.setEnabled(True)
        self.plan_list.setEnabled(self.agent_mode.currentData() == 'agent')
        if self.agent_mode.currentData() != 'agent':
            self.status.setText('处理结束；请核对结果和出处')
        self.feedback.setEnabled(self.feedback.has_context)
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
        def task(progress):
            service = ModelService(self.config) if self.external.isChecked() and self.config.get('embedding_model') else None
            return self.index.rebuild(progress, embeddings=service)
        self.start(task, self.output.setPlainText)

    def ask(self):
        query, scope, external = self.question.text().strip(), self.scope.text().strip(), self.external.isChecked()
        if not query or not scope:
            return
        if self.agent_mode.currentData() == 'agent':
            if self._plan_store and self._plan_store.get_pending():
                QMessageBox.information(self, '待处理计划',
                    '请先拒绝或确认当前待处理计划，再开始下一轮工具推理。')
                return
            from assistant.agent.runner import run_agent
            from core.draft_manager import DraftManager
            from core.record_manager import RecordManager
            from core.template_manager import TemplateManager
            batch_id = self.entry.current_batch_id
            template = self.entry.current_template
            template_name = template.get('name', scope) if isinstance(template, dict) else (template or scope)
            local_tool = self.local_tool.currentData()
            def task(progress):
                managers = (RecordManager(), DraftManager(), TemplateManager())
                service = ModelService(self.config) if external and self.config.get('chat_model') else None
                try:
                    result = run_agent(query, self.index, service,
                        allow_model_calls=bool(external and service),
                        record_manager=managers[0], draft_manager=managers[1],
                        template_manager=managers[2], batch_id=batch_id,
                        template_name=template_name, local_tool=local_tool)
                except Exception as exc:
                    result = run_agent(query, self.index, None, allow_model_calls=False,
                        record_manager=managers[0], draft_manager=managers[1],
                        template_manager=managers[2], batch_id=batch_id,
                        template_name=template_name, local_tool=local_tool)
                    result['notice'] = '模型不可用，已退回所选本地只读工具。'
                    result['fallback_reason'] = type(exc).__name__
                return result
            self.start(task, self.show_agent_result)
            return
        def task(progress):
            try:
                service = ModelService(self.config) if external else None
                result = ask(self.index, query, scope,
                             embeddings=service if service and self.config.get('embedding_model') else None,
                             service=service)
            except Exception as exc:
                self.index.record_feedback(query, scope=scope, failure=type(exc).__name__)
                if not external:
                    raise
                result = ask(self.index, query, scope)
                result['answer'] = '外部服务不可用，已退回本地证据摘录。\n' + result['answer']
            if result.get('notice'):
                self.index.record_feedback(query, result.get('answer', ''), result.get('citations', []),
                                           scope, failure='service_fallback')
            return self.render_answer(result), result, query, scope
        self.start(task, self.show_answer)

    def show_agent_result(self, result):
        self._plan_store = result.get('_plan_store')
        answer = result.get('verified_answer') or result.get('answer', '')
        citations = result.get('verified_citations') or result.get('citations', [])
        rendered = answer
        if citations:
            rendered += '\n\n' + '\n\n'.join(
                (f"来源：{item.get('source', '本地资料')} · 第 {item.get('page')} 页 · "
                 f"字符 {item.get('start_index', 0)}" if item.get('page') is not None
                 else f"来源：{item.get('source', '本地数据库')}") + f"\n{item.get('quote', '')}"
                for item in citations)
        if result.get('notice'):
            rendered += '\n\n' + result['notice']
        self.output.setPlainText(rendered)
        self.plan_list.clear()
        for plan in result.get('plans', []):
            item = QListWidgetItem(f"{plan['action']} · {plan['reason']}")
            item.setData(Qt.UserRole, plan['plan_id'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setToolTip(json.dumps({"preview": plan['preview'],
                                       "citations": plan.get('citations', [])},
                                      ensure_ascii=False, indent=2))
            self.plan_list.addItem(item)
        self.status.setText(result.get('mode', '工具模式') +
            f"；模型调用 {result.get('tool_calls', 0)} 次；待确认计划 {len(result.get('plans', []))} 项")

    def edit_selected_plan(self):
        item = self.plan_list.currentItem()
        if not item or not self._plan_store:
            return
        plan = self._plan_store.plans.get(item.data(Qt.UserRole))
        if not plan or plan.status != 'pending':
            return
        edited, accepted = QInputDialog.getMultiLineText(
            self, '编辑待确认计划', '修改参数 JSON；编辑后会重新生成预览并保持待确认状态。',
            json.dumps(plan.args, ensure_ascii=False, indent=2))
        if not accepted:
            return
        try:
            values = json.loads(edited)
            if not isinstance(values, dict):
                raise ValueError
            self._plan_store.update(plan.plan_id, **values)
            self._refresh_plan_list()
            self.status.setText('计划已编辑；请重新核对预览后勾选确认。')
        except Exception:
            QMessageBox.warning(self, '计划参数无效', '参数格式或模板字段不符合要求；计划未执行。')

    def _refresh_plan_list(self):
        if not self._plan_store:
            return
        selected_id = self.plan_list.currentItem().data(Qt.UserRole) if self.plan_list.currentItem() else None
        self.plan_list.clear()
        for plan in self._plan_store.get_pending():
            item = QListWidgetItem(f"{plan.action} · {plan.reason}")
            item.setData(Qt.UserRole, plan.plan_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setToolTip(json.dumps({"preview": plan.preview, "citations": plan.citations},
                                       ensure_ascii=False, indent=2))
            self.plan_list.addItem(item)
            if plan.plan_id == selected_id:
                self.plan_list.setCurrentItem(item)

    def reject_plans(self):
        if not self._plan_store:
            return
        count = 0
        for plan in self._plan_store.get_pending():
            self._plan_store.decide(plan.plan_id, 'rejected')
            count += 1
        self._refresh_plan_list()
        self.status.setText(f'已拒绝 {count} 项计划；没有执行数据库写入。')

    def execute_selected_plans(self):
        if not self._plan_store:
            return
        selected = [self.plan_list.item(i).data(Qt.UserRole) for i in range(self.plan_list.count())
                    if self.plan_list.item(i).checkState() == Qt.Checked]
        if not selected:
            return
        if QMessageBox.question(self, '确认执行计划',
                f'将按单事务逐条执行所选 {len(selected)} 项计划；请先核对每项预览与出处。') != QMessageBox.Yes:
            return
        from assistant.agent.executor import PlanExecutor
        store = self._plan_store
        executor = PlanExecutor(store.record_manager, store.draft_manager, store.template_manager)
        results = []
        for plan_id in selected:
            store.decide(plan_id, 'approved')
            results.append(executor.execute_plan(store.plans[plan_id]))
        succeeded = sum(item['status'] == 'executed' for item in results)
        self._refresh_plan_list()
        tree = getattr(self.entry, 'archive_tree', None)
        if tree and hasattr(tree, 'refresh'):
            tree.refresh()
        self.status.setText(f'已执行 {succeeded}/{len(results)} 项；每项独立事务，失败计划已回滚。')

    def show_answer(self, payload):
        rendered, result, query, scope = payload
        self.output.setPlainText(rendered)
        self.feedback.bind(query, result, scope)

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
