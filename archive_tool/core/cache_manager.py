"""缓存管理器 - 管理表单数据的临时缓存"""
import json
import os
from pathlib import Path


class CacheManager:
    """管理著录表单的临时缓存"""

    def __init__(self):
        self.cache_dir = Path.home() / ".archive_tool" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_file(self, template_id):
        """获取指定模板的缓存文件路径"""
        return self.cache_dir / f"cache_{template_id}.json"

    def get_cache(self, template_id):
        """获取指定模板的缓存数据"""
        cache_file = self._get_cache_file(template_id)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        return None

    def save_cache(self, record_id, template_id, data):
        """保存缓存数据"""
        cache_file = self._get_cache_file(template_id)
        cache_data = {
            "record_id": record_id,
            "data": data
        }
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    def clear_cache(self, template_id=None):
        """清除缓存，template_id为None时清除所有"""
        if template_id:
            cache_file = self._get_cache_file(template_id)
            if cache_file.exists():
                cache_file.unlink()
        else:
            for cache_file in self.cache_dir.glob("cache_*.json"):
                cache_file.unlink()
