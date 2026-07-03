"""
数据同步上传（预留接口）
"""
import requests
from datetime import datetime
from db.database import get_cursor


class UploadManager:
    """上传管理器（预留接口实现）"""

    def __init__(self, api_config=None):
        self.api_config = api_config or {}
        self.api_url = self.api_config.get('url', '')
        self.api_token = self.api_config.get('token', '')

    def upload_record(self, record):
        """上传单条记录"""
        if not self.api_url:
            return False, '接口地址未配置'

        try:
            # TODO: 接口文档到位后实现实际请求逻辑
            headers = {'Authorization': f'Bearer {self.api_token}'}
            response = requests.post(
                self.api_url,
                json=record,
                headers=headers,
                timeout=30
            )
            if response.status_code == 200:
                return True, '上传成功'
            else:
                return False, f'上传失败: {response.status_code}'
        except requests.exceptions.RequestException as e:
            return False, f'网络错误: {str(e)}'
        except NotImplementedError:
            return False, '上传功能待接口文档确认后实现'

    def upload_batch(self, records):
        """批量上传记录"""
        results = []
        for record in records:
            success, message = self.upload_record(record)
            results.append({
                'record_id': record.get('id'),
                'success': success,
                'message': message
            })
            # 记录上传日志
            self._log_upload(record.get('id'), 'success' if success else 'failed', message)

        return results

    def _log_upload(self, record_id, status, message):
        """记录上传日志"""
        with get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO upload_log (record_id, status, message, created_at)
                VALUES (?, ?, ?, ?)
            ''', (record_id, status, message, datetime.now().isoformat()))

    def get_upload_logs(self, record_id=None, limit=100):
        """获取上传日志"""
        with get_cursor() as cursor:
            if record_id:
                cursor.execute('''
                    SELECT * FROM upload_log WHERE record_id = ?
                    ORDER BY created_at DESC LIMIT ?
                ''', (record_id, limit))
            else:
                cursor.execute('SELECT * FROM upload_log ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
