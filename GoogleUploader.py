import asyncio
import datetime
from datetime import timedelta
import gc
import os
import shutil
import time
from aiogram import Bot
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

from cache_class import *

gauth = GoogleAuth()
gauth.LocalWebserverAuth()


# async def delete_files_in_folder(folder_path):
#     gc.collect()
#     for filename in os.listdir(folder_path):
#         file_path = os.path.join(folder_path, filename)
#         try:
#             if os.path.isfile(file_path):
#                 os.remove(file_path)
#         except Exception as e:
#             print(f'Ошибка при удалении файла {file_path}. {e}')
async def close_open_files(path):
    """Закрывает все открытые файловые дескрипторы"""
    # Принудительно вызываем сборщик мусора
    gc.collect()

    # Пытаемся закрыть файлы через os.close()
    for fd in range(3, 256):  # 0-2 это stdin, stdout, stderr
        try:
            os.close(fd)
        except (OSError, AttributeError):
            pass


async def safe_delete(path):
    """Безопасное удаление с закрытием файлов"""
    try:
        await close_open_files(path)
        shutil.rmtree(path)
        return True
    except Exception as e:
        print(f"Ошибка удаления: {e}")
        return False


class GoogleDiskUploader:
    def __init__(self):
        self.drive = GoogleDrive(gauth)
        self.cache = MangaCache()
        self.folder_id = None  # Будет хранить ID созданной папки
        self.cleanup_interval = timedelta(minutes=1)
        self.cleanup_task = None  # Здесь будет храниться задача очистки
        self.is_running = False  # Флаг работы фоновой задачи

    async def start_cleanup_scheduler(self):
        """Запускает фоновую задачу периодической очистки"""
        if self.is_running:
            return

        self.is_running = True
        while self.is_running:
            try:
                await self.cleanup_old_folders()
            except Exception as e:
                print(f"Ошибка при очистке старых папок: {str(e)}")

            # Ожидаем 24 часа до следующей проверки
            await asyncio.sleep(10)

    async def upload_manga(self, manga_title: str, manga_url: str, local_path: str, bot: Bot, chat_id: int):
        drive_info = self.cache.get_drive_info(manga_url)
        # Проверяем, существует ли папка на Drive
        try:
            folder = self.drive.CreateFile({'id': drive_info["folder_id"]})
            folder.FetchMetadata()

            # Получаем количество файлов в папке
            file_query = f"'{drive_info['folder_id']}' in parents and trashed=false"
            files = self.drive.ListFile({'q': file_query}).GetList()

            await bot.send_message(
                chat_id,
                f"📚 Манга уже доступна на Google Drive:\n"
                f"🏷 Название: {manga_title}\n"
                f"📂 Глав: {len(files)}\n"
                f"🔗 Ссылка: {drive_info['link']}\n"
                f"🕒 Загружена: {drive_info['created_at']}"
            )
            return True
        except:
            # Если папка не найдена, продолжаем загрузку
            pass

        try:
            # 1. Создаем папку на Google Drive
            folder_name = f"{manga_title.replace(' ', '_')}"
            folder_metadata = {
                'title': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [{'id': 'root'}]
            }

            folder = self.drive.CreateFile(folder_metadata)
            folder.Upload()
            self.folder_id = folder['id']

            await bot.send_message(chat_id, f"📁 Начата загрузка на google disk")

            # 2. Загружаем все файлы из локальной папки
            uploaded_files = 0
            for root, _, files in os.walk(local_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        # Пропускаем не-CBR файлы
                        if not file.lower().endswith('.cbr'):
                            continue

                        # Создаем метаданные файла
                        file_metadata = {
                            'title': file,
                            'parents': [{'id': self.folder_id}]
                        }

                        # Загружаем файл
                        gfile = self.drive.CreateFile(file_metadata)
                        gfile.SetContentFile(file_path)
                        gfile.Upload()
                        uploaded_files += 1

                        # Отправляем прогресс каждые 5 файлов
                        if uploaded_files % 5 == 0:
                            await bot.send_message(
                                chat_id,
                                f"⬆️ Загружено {uploaded_files} глав..."
                            )
                    except Exception as e:
                        print(f"Ошибка загрузки {file}: {str(e)}")
                        continue

            # 3. Открываем доступ к папке
            folder.InsertPermission({
                'type': 'anyone',
                'value': 'anyone',
                'role': 'reader',
                'withLink': True
            })

            # 4. Получаем и отправляем ссылку
            folder_link = f"https://drive.google.com/drive/folders/{self.folder_id}"

            self.cache.add_manga(
                url=manga_url,
                title=manga_title,
                drive_folder_id=self.folder_id,
                drive_link=folder_link
            )
            await safe_delete(os.path.abspath(f"downloads/{manga_title}"))

            await bot.send_message(
                chat_id,
                f"✅ Все главы загружены!\n"
                f"📚 Манга: {manga_title}\n"
                f"📂 Файлов: {uploaded_files}\n"
                f"🔗 Ссылка: {folder_link}"
            )
            return True

        except Exception as e:
            await bot.send_message(chat_id, f"❌ Ошибка: {str(e)}")
            return False

    async def cleanup_old_folders(self):
        """Удаляет папки на Google Drive и чистит кеш для старых записей"""
        cutoff_date = datetime.now() - self.cleanup_interval
        deleted_count = 0

        # Создаем копию элементов кеша для безопасной итерации
        cache_items = list(self.cache.cache.items())

        for url_hash, manga_data in cache_items:
            drive_data = manga_data.get("drive_data")
            if not drive_data:
                continue

            try:
                created_at = datetime.fromisoformat(drive_data["created_at"])
                if created_at < cutoff_date:
                    # Удаляем папку с Google Drive
                    folder = self.drive.CreateFile({'id': drive_data["folder_id"]})
                    folder.Delete()

                    # Удаляем информацию о папке из кеша
                    manga_data["drive_data"] = None
                    deleted_count += 1

                    print(f"Удалена старая папка: {manga_data['title']} ({drive_data['folder_id']})")
            except Exception as e:
                print(f"Ошибка при удалении папки {manga_data.get('title')}: {str(e)}")

        # Сохраняем изменения в кеше
        if deleted_count > 0:
            self.cache._save_cache()

        print(f"Очистка завершена. Удалено папок: {deleted_count}")
