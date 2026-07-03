"""
数据操作公共方法
"""
from db.database import get_cursor


def execute_query(query, params=None):
    """执行查询"""
    with get_cursor() as cursor:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor.fetchall()


def execute_insert(query, params=None):
    """执行插入并返回ID"""
    with get_cursor() as cursor:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor.lastrowid


def execute_update(query, params=None):
    """执行更新"""
    with get_cursor() as cursor:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor.rowcount
