"""
草稿管理
"""
import json
from datetime import datetime
from db.database import get_cursor


class DraftManager:
    """草稿管理器"""

    def save_draft(self, draft_name, batch_id, template_name, data: dict):
        """保存草稿"""
        with get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO drafts (draft_name, batch_id, template_name, draft_data, created_at)
                VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
            ''', (draft_name, batch_id, template_name, json.dumps(data, ensure_ascii=False)))
            return cursor.lastrowid

    def get_drafts_by_batch(self, batch_id):
        """获取批次的草稿列表"""
        with get_cursor() as cursor:
            cursor.execute('SELECT * FROM drafts WHERE batch_id = ? ORDER BY created_at DESC', (batch_id,))
            drafts = cursor.fetchall()
            result = []
            for draft in drafts:
                d = dict(draft)
                d['draft_data'] = json.loads(d['draft_data'])
                result.append(d)
            return result

    def get_draft(self, draft_id):
        """获取单个草稿"""
        with get_cursor() as cursor:
            cursor.execute('''
                SELECT d.*, b.name as batch_name
                FROM drafts d
                LEFT JOIN batches b ON d.batch_id = b.id
                WHERE d.id = ?
            ''', (draft_id,))
            draft = cursor.fetchone()
            if draft:
                d = dict(draft)
                d['draft_data'] = json.loads(d['draft_data'])
                return d
            return None

    def delete_draft(self, draft_id):
        """删除草稿"""
        with get_cursor() as cursor:
            cursor.execute('DELETE FROM drafts WHERE id = ?', (draft_id,))

    def update_draft(self, draft_id, draft_name, draft_data: dict):
        """更新草稿"""
        with get_cursor() as cursor:
            cursor.execute('''
                UPDATE drafts SET draft_name = ?, draft_data = ?, created_at = ?
                WHERE id = ?
            ''', (draft_name, json.dumps(draft_data, ensure_ascii=False),
                 datetime.now().isoformat(), draft_id))
