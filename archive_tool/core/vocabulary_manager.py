"""
标准词库管理模块
"""

def import_vocabulary(field_key, values: list[str], category=None, weight=0):
    """批量导入标准词条"""
    from db.database import get_cursor
    with get_cursor() as cursor:
        for v in values:
            cursor.execute('''
                INSERT OR IGNORE INTO std_vocabulary (field_key, value, category, weight)
                VALUES (?, ?, ?, ?)
            ''', (field_key, v, category, weight))


def import_vocabulary_with_pinyin(field_key, items: list[dict]):
    """批量导入带拼音缩写的标准词条"""
    from db.database import get_cursor
    with get_cursor() as cursor:
        for item in items:
            cursor.execute('''
                INSERT OR IGNORE INTO std_vocabulary (field_key, value, pinyin_abbr, category, weight)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                field_key,
                item.get('value'),
                item.get('pinyin_abbr'),
                item.get('category'),
                item.get('weight', 0)
            ))


def get_vocabulary(field_key):
    """获取指定字段的标准词条"""
    from db.database import get_cursor
    with get_cursor() as cursor:
        cursor.execute('''
            SELECT value, pinyin_abbr, category, weight 
            FROM std_vocabulary 
            WHERE field_key = ? 
            ORDER BY weight DESC, value
        ''', (field_key,))
        return [dict(row) for row in cursor.fetchall()]


def delete_vocabulary(field_key, value):
    """删除指定词条"""
    from db.database import get_cursor
    with get_cursor() as cursor:
        cursor.execute('''
            DELETE FROM std_vocabulary WHERE field_key = ? AND value = ?
        ''', (field_key, value))


def update_vocabulary(field_key, value, new_value=None, pinyin_abbr=None, category=None, weight=None):
    """更新词条信息"""
    from db.database import get_cursor
    with get_cursor() as cursor:
        updates = []
        params = []
        
        if new_value is not None:
            updates.append('value = ?')
            params.append(new_value)
        if pinyin_abbr is not None:
            updates.append('pinyin_abbr = ?')
            params.append(pinyin_abbr)
        if category is not None:
            updates.append('category = ?')
            params.append(category)
        if weight is not None:
            updates.append('weight = ?')
            params.append(weight)
        
        if updates:
            params.extend([field_key, value])
            cursor.execute(f'''
                UPDATE std_vocabulary SET {', '.join(updates)}
                WHERE field_key = ? AND value = ?
            ''', params)


def init_default_vocabulary():
    """初始化预置标准词条"""
    vocabulary_data = {
        'responsible_person': {
            'category': '责任者',
            'items': [
            
            ]
        },
        'category_code': {
            'category': '分类号',
            'items': [
                
            ]
        },
        'organization_name': {
            'category': '单位名称',
            'items': [
                
            ]
        },
        'doc_type': {
            'category': '文件类型',
            'items': [
                {'value': '请示', 'pinyin_abbr': 'qs', 'weight': 15},
                {'value': '批复', 'pinyin_abbr': 'pf', 'weight': 15},
                {'value': '通知', 'pinyin_abbr': 'tz', 'weight': 15},
                {'value': '报告', 'pinyin_abbr': 'bg', 'weight': 15},
                {'value': '函', 'pinyin_abbr': 'h', 'weight': 10},
                {'value': '会议纪要', 'pinyin_abbr': 'hyjy', 'weight': 10},
            ]
        },
        'file_title': {
            'category': '文件题名',
            'items': [
                {'value': '关于电网建设项目的请示', 'pinyin_abbr': 'gwjsxmqs', 'weight': 10},
                {'value': '关于安全生产检查的通知', 'pinyin_abbr': 'gwasjccztz', 'weight': 10},
                {'value': '年度工作总结报告', 'pinyin_abbr': 'ndgzjzbg', 'weight': 5},
            ]
        },
    }

    for field_key, data in vocabulary_data.items():
        items_with_category = []
        for item in data['items']:
            item_copy = item.copy()
            item_copy['category'] = data['category']
            items_with_category.append(item_copy)
        import_vocabulary_with_pinyin(field_key, items_with_category)