import json
import os
from typing import Dict, Optional, List
import hashlib
from datetime import datetime


# Исправленный класс MangaCache
class MangaCache:
    _instance = None
    CACHE_FILE = "manga_cache.json"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_cache()
        return cls._instance

    def _initialize_cache(self):
        """Инициализация кеша из файла или создание нового"""
        if os.path.exists(self.CACHE_FILE):
            try:
                with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self.cache = {}
        else:
            self.cache = {}

    def __contains__(self, url: str) -> bool:
        """Проверка наличия URL в кеше"""
        return self._hash_url(url) in self.cache

    def _save_cache(self):
        """Сохранить кеш в файл"""
        with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def get_manga_by_url(self, url: str) -> Optional[Dict]:
        """Получить данные манги по URL"""
        url_hash = self._hash_url(url)
        return self.cache.get(url_hash)

    def add_manga(self, url: str, title: str, poster_url: Optional[str] = None,
                  drive_folder_id: Optional[str] = None, drive_link: Optional[str] = None):
        """Добавить мангу в кеш"""
        url_hash = self._hash_url(url)
        now = datetime.now().isoformat()
        if url_hash not in self.cache:
            self.cache[url_hash] = {
                "url": url,
                "title": title,
                "poster_url": poster_url,
                "last_updated": now,
                "drive_data": {
                    "folder_id": drive_folder_id,
                    "link": drive_link,
                    "created_at": now
                } if drive_folder_id else None
            }
        else:
            self.cache[url_hash]["title"] = title
            self.cache[url_hash]["poster_url"] = poster_url or self.cache[url_hash].get("poster_url")
            self.cache[url_hash]["last_updated"] = now

            if drive_folder_id:
                self.cache[url_hash]["drive_data"] = {
                    "folder_id": drive_folder_id,
                    "link": drive_link,
                    "created_at": now
                }

        self._save_cache()

    def _hash_url(self, url: str) -> str:
        """Хеширование URL для использования в качестве ключа"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def search_in_cache(self, query: str) -> List[Dict]:
        """Поиск в кеше по названию"""
        query = query.lower()
        return [
            manga for manga in self.cache.values()
            if query in (manga.get("title") or "").lower()
        ]

    def get_drive_info(self, url: str) -> Optional[Dict]:
        """Получить информацию о Google Drive по URL манги"""
        manga = self.get_manga_by_url(url)
        return manga.get("drive_data") if manga else None
