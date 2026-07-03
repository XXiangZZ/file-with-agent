"""
全局配置
"""
import os
import sys
from pathlib import Path


def get_base_dir():
    """获取项目根目录（支持PyInstaller打包）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def get_resource_path(relative_path):
    """获取资源文件路径（支持PyInstaller打包）"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / relative_path
    return get_base_dir() / relative_path


BASE_DIR = get_base_dir()
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = DATA_DIR / 'logs'
TEMPLATE_DIR = get_resource_path('config/templates')

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DATABASE_PATH = DATA_DIR / 'archive.db'

LOG_LEVEL = 'INFO'
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

AUTO_CACHE_INTERVAL = 30000

DATE_FORMAT = '%Y%m%d'

EXPORT_HEADER_FILL = '2E75B6'
EXPORT_HEADER_FONT_COLOR = 'FFFFFF'