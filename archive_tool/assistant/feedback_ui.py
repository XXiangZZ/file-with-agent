"""Small local feedback form shared by the RAG and manual dialogs."""
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class FeedbackControls(QWidget):
    def __init__(self, index, on_status=None, parent=None):
        super().__init__(parent)
        self.index = index
        self.on_status = on_status or (lambda message: None)
        self.context = None
        self.rating = None
        layout = QHBoxLayout(self)
        self.helpful = QPushButton('有帮助')
        self.not_helpful = QPushButton('无帮助')
        self.correction = QLineEdit()
        self.correction.setPlaceholderText('纠错说明（选填）')
        self.submit = QPushButton('提交反馈')
        for widget in (self.helpful, self.not_helpful, self.correction, self.submit):
            layout.addWidget(widget)
        self.helpful.clicked.connect(lambda: self.set_rating(True))
        self.not_helpful.clicked.connect(lambda: self.set_rating(False))
        self.submit.clicked.connect(self.save)
        self.setEnabled(False)

    @property
    def has_context(self):
        return self.context is not None

    def bind(self, question, result, scope):
        self.context = {'question': question, 'answer': result.get('answer', ''),
                        'citations': result.get('citations', []), 'scope': scope}
        self.rating = None
        self.correction.clear()
        self.setEnabled(True)

    def set_rating(self, helpful):
        self.rating = helpful
        self.on_status('已选择“有帮助”' if helpful else '已选择“无帮助”；可补充纠错说明后提交。')

    def save(self):
        if not self.context or self.rating is None:
            self.on_status('请先选择“有帮助”或“无帮助”。')
            return
        self.index.record_feedback(**self.context, helpful=self.rating,
                                   correction=self.correction.text().strip())
        self.context = None
        self.rating = None
        self.setEnabled(False)
        self.on_status('反馈已保存在本机知识库中。')
