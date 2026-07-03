"""
操作日志记录
"""
import json
import socket
from datetime import datetime
from db.database import get_cursor


class Logger:
    """操作日志记录器"""

    def log(self, operation_type, details=None):
        """记录操作日志"""
        machine_name = socket.gethostname()
        with get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO operation_log (operation_type, details, machine_name, created_at)
                VALUES (?, ?, ?, ?)
            ''', (operation_type, json.dumps(details, ensure_ascii=False) if details else '',
                 machine_name, datetime.now().isoformat()))

    def get_logs(self, limit=100):
        """获取最近的操作日志"""
        with get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM operation_log ORDER BY created_at DESC LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_logs_by_type(self, operation_type, limit=100):
        """按类型获取操作日志"""
        with get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM operation_log WHERE operation_type = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (operation_type, limit))
            return [dict(row) for row in cursor.fetchall()]
