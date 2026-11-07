"""Guarded form adapter; caller must obtain explicit user confirmation."""
from PySide6.QtWidgets import QLineEdit, QTextEdit, QComboBox


def fill_empty(entry, suggestions):
    current = entry._collect_field_data()
    applied, skipped = [], []
    allowed = {f['key']: f for f in entry.current_fields}
    for suggestion in suggestions:
        key, value = suggestion['key'], suggestion.get('value')
        if key not in allowed or not value or current.get(key, '').strip():
            skipped.append(key)
            continue
        if entry.validator.validate_field(allowed[key], value):
            skipped.append(key)
            continue
        widget = entry.form_widget.findChild(QLineEdit, key)
        if widget:
            widget.setText(value)
        else:
            widget = entry.form_widget.findChild(QTextEdit, key)
            if widget:
                widget.setPlainText(value)
            else:
                widget = entry.form_widget.findChild(QComboBox, key)
                if not widget or widget.currentText().strip() or widget.findText(value) < 0:
                    skipped.append(key)
                    continue
                widget.setCurrentIndex(widget.findText(value))
        current[key] = value
        applied.append(key)
    return applied, skipped
