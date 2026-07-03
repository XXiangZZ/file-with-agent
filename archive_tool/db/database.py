"""
数据库初始化与连接管理
"""
import sqlite3
import threading
from contextlib import contextmanager
from config.settings import DATABASE_PATH

# 线程本地存储，每个线程一个连接
_local = threading.local()


def get_connection():
    """获取数据库连接（每个线程一个连接）"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    else:
        # 检查连接是否仍然有效
        try:
            _local.conn.execute('SELECT 1')
        except sqlite3.ProgrammingError:
            # 连接已关闭，重新创建
            _local.conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            _local.conn.row_factory = sqlite3.Row
    return _local.conn


def close_connection():
    """关闭当前线程的数据库连接"""
    if hasattr(_local, 'conn') and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None


@contextmanager
def get_cursor():
    """上下文管理器，自动提交/回滚"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def init_database():
    """初始化数据库表"""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 模板定义表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                filing_type TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 字段定义表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER REFERENCES templates(id),
                key TEXT NOT NULL,
                name TEXT NOT NULL,
                required INTEGER DEFAULT 0,
                field_type TEXT DEFAULT 'text',
                layer TEXT DEFAULT 'item',
                dropdown_options TEXT,
                hint TEXT,
                is_custom INTEGER DEFAULT 0,
                UNIQUE(template_id, key)
            )
        ''')

        # 批次管理表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                template_id INTEGER REFERENCES templates(id),
                template_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try:
            cursor.execute('ALTER TABLE batches ADD COLUMN template_name TEXT')
        except sqlite3.OperationalError:
            pass

        # 档案记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER REFERENCES batches(id),
                template_id INTEGER REFERENCES templates(id),
                template_name TEXT,
                name TEXT,
                filing_type TEXT NOT NULL,
                layer TEXT,
                parent_id INTEGER,
                year INTEGER,
                review_status TEXT DEFAULT 'pending',
                upload_status TEXT DEFAULT 'none',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 字段值存储表（EAV模型）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS record_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER REFERENCES records(id) ON DELETE CASCADE,
                field_key TEXT NOT NULL,
                field_value TEXT,
                is_custom INTEGER DEFAULT 0,
                UNIQUE(record_id, field_key)
            )
        ''')

        # 自动缓存表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auto_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER,
                template_id INTEGER REFERENCES templates(id),
                cache_data TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 草稿管理表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER REFERENCES batches(id),
                record_id INTEGER,
                draft_name TEXT NOT NULL,
                template_name TEXT,
                draft_data TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try:
            cursor.execute('ALTER TABLE drafts ADD COLUMN template_name TEXT')
        except sqlite3.OperationalError:
            pass

        # 批次-模板-年度关联表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS batch_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER REFERENCES batches(id) ON DELETE CASCADE,
                template_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                UNIQUE(batch_id, template_name, year)
            )
        ''')

        # 上传日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS upload_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER REFERENCES records(id),
                status TEXT NOT NULL,
                message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 操作日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT NOT NULL,
                details TEXT,
                machine_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 标准词库表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS std_vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_key TEXT NOT NULL,
                value TEXT NOT NULL,
                pinyin_abbr TEXT,
                category TEXT,
                weight INTEGER DEFAULT 0,
                UNIQUE(field_key, value)
            )
        ''')

        conn.commit()
    finally:
        conn.close()
