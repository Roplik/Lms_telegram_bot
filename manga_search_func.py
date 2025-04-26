import asyncio
import json
import re
import os
from typing import List, Tuple, Optional
from playwright.async_api import async_playwright
from cache_class import MangaCache
from aiogram.types import Message

# Инициализируем кеш
manga_cache = MangaCache()
# Загружаем cookies из файла
with open('cookies.json', 'r') as f:
    cookies = json.load(f)


# Исправленная функция search_manga
async def search_manga(query: str) -> List[Tuple[str, str]]:
    # Сначала проверяем кеш
    print(query)
    cached_results = manga_cache.search_in_cache(query)
    if cached_results:
        print(f"Найдено в кеше: {len(cached_results)} результатов")
        print([(manga["url"], manga["title"]) for manga in cached_results])
        return [(manga["url"], manga["title"]) for manga in cached_results]

    # Если в кеше нет, идем в сеть
    url = f"https://com-x.life/search/{query}"
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()
        await page.goto(url)
        # Получаем элементы пагинации
        all_page = await page.query_selector_all('.pagination__pages a, .cl__navigation.pagination__pages span')
        if not all_page:
            print("Элементы пагинации не найдены, парсим только первую страницу")
            max_pages = 1
        else:
            # Асинхронно получаем текст со всех элементов пагинации
            page_texts = await asyncio.gather(*[el.text_content() for el in all_page])
            page_numbers = []
            for text in page_texts:
                if text:
                    numbers = re.findall(r'\d+', text)
                    if numbers:
                        page_numbers.extend(map(int, numbers))
            max_pages = max(page_numbers) if page_numbers else 1
            print(f"Всего страниц: {max_pages}")

        # Асинхронная обработка всех страниц
        async def process_page(page_num: int):
            page_url = f"https://com-x.life/search/{query}/page/{page_num}"
            print(f"Обрабатываю страницу {page_num}")

            page_instance = await context.new_page()
            await page_instance.goto(page_url)

            titles = await page_instance.query_selector_all('.readed__title')
            page_results = []

            results = []

            async def process_title(title_element, idx):
                manga_title = await title_element.inner_text()
                manga_link_el = await title_element.query_selector('a')
                manga_link = await manga_link_el.get_attribute('href')

                # Исправленная проверка наличия в кеше
                if manga_link not in manga_cache:  # Теперь работает благодаря __contains__
                    manga_cache.add_manga(manga_link, manga_title)
                return (manga_link, manga_title)

            page_results = await asyncio.gather(*[
                process_title(title, idx)
                for idx, title in enumerate(titles)
            ])

            await page_instance.close()
            return page_results

        # Обрабатываем все страницы параллельно с ограничением (semaphore)
        semaphore = asyncio.Semaphore(5)  # Ограничиваем количество одновременных запросов

        async def limited_process_page(page_num):
            async with semaphore:
                return await process_page(page_num)

        tasks = [limited_process_page(num) for num in range(1, max_pages + 1)]
        all_results = await asyncio.gather(*tasks)

        results = []
        for page_results in all_results:
            for manga_url, manga_title in page_results:
                # Добавляем в кеш
                manga_cache.add_manga(manga_url, manga_title)
                results.append((manga_url, manga_title))

        await browser.close()
        return results


# Функция для загрузки превью
async def download_poster(manga_url: str) -> Optional[str]:
    # Проверяем кеш через get_manga_by_url
    cached = manga_cache.get_manga_by_url(manga_url)
    if cached and cached.get("poster_url"):
        return cached["poster_url"]

    # Если постера нет в кеше, скачиваем
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()
        await page.goto(manga_url)

        poster_element = await page.query_selector('.page__poster.img-wide img')
        if poster_element:
            poster_url = await poster_element.get_attribute('src')
            if poster_url.startswith('/'):
                poster_url = "https://com-x.life" + poster_url

            # Сохраняем в кеш
            manga_cache.add_manga(manga_url, None, poster_url)

            await browser.close()
            return poster_url

    await browser.close()
    return None


async def download_all_chapters(manga_url, manga_title, message: Message):
    manga_url = manga_url + "#chapters"
    # Нормализация названия манги для пути
    safe_title = re.sub(r'[<>:"/\\|?*]', '', manga_title)  # Удаляем запрещенные символы
    safe_title = safe_title.strip()  # Убираем пробелы по краям

    # Создаем безопасный путь для Windows
    download_dir = os.path.join(os.getcwd(), "downloads", safe_title)
    os.makedirs(download_dir, exist_ok=True)  # Создаем папку, если не существует
    button_selector = ".cl__itemAction.btn"
    page_selector = ".cl__navigation.pagination__pages a, .cl__navigation.pagination__pages span"

    try:
        async with async_playwright() as p:
            # Уведомляем пользователя о начале загрузки
            status_msg = await message.answer("🔄 Начинаю загрузку глав...")

            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)

            # Загрузка cookies (если есть)
            if os.path.exists('cookies.json'):
                with open('cookies.json', 'r') as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)

            page = await context.new_page()
            await page.goto(manga_url)
            # Получаем ВСЕ элементы глав

            await page.wait_for_selector('.cl__item')

            # Получаем ВСЕ элементы глав
            chapter_items = await page.query_selector_all('.cl__item')

            if not chapter_items:
                return 0

            # Берем последнюю главу
            last_chapter = chapter_items[0]

            # Извлекаем номер из элемента с классом cl__item-num
            chapter_num_element = await last_chapter.query_selector('.cl__item-num')
            if not chapter_num_element:
                return 0

            chapter_num_text = await chapter_num_element.inner_text()

            # Извлекаем только цифры (убираем #)
            last_chapter = int(chapter_num_text.replace('#', ''))

            # Получаем количество страниц
            pagination = await page.query_selector_all(page_selector)
            max_page = 1
            if pagination:
                page_numbers = []
                for element in pagination:
                    text = await element.inner_text()
                    if text.isdigit():
                        page_numbers.append(int(text))
                if page_numbers:
                    max_page = max(page_numbers)

            await status_msg.edit_text(f"📚 Найдено глав: {last_chapter}\n⏳ Загружаю...")
            actual_download_chapter = 1

            # Скачиваем все страницы
            for page_index in range(1, max_page + 1):
                buttons = await page.query_selector_all(button_selector)
                try:
                    if buttons:
                        for i, button in enumerate(buttons):
                            try:
                                async with page.expect_download() as download_info:
                                    await button.click()
                                    download = await download_info.value
                                    filename = download.suggested_filename
                                    save_path = os.path.join(download_dir, filename)
                                    await download.save_as(save_path)
                                    progress = int((actual_download_chapter / last_chapter) * 100)
                                    try:
                                        await status_msg.edit_text(
                                            f"📥 Загружаю главу {actual_download_chapter}/{last_chapter}\n"
                                            f"└ Прогресс: [{progress}%] {'⬜' * (progress // 10)}{'⬛' * (10 - progress // 10)}"
                                        )
                                        actual_download_chapter += 1
                                    except Exception as e:
                                        print(f"Ошибка обновления: {e}")
                                        await browser.close()
                                        continue
                            except Exception as e:
                                print(f"Ошибка при загрузке главы: {e}")
                                await browser.close()
                                continue
                    if page_index < max_page:
                        next_button = await page.query_selector('a:has-text("Вперед")')
                        if next_button:
                            await next_button.click()
                            await page.wait_for_selector(page_selector, timeout=5000)  # Таймаут 5 сек
                except Exception as e:
                    print(f"Критическая ошибка: {e}")
                    await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
                    await browser.close()
            await browser.close()
            await status_msg.edit_text("✅ Все главы успешно загружены!")


    except Exception as e:
        await browser.close()
        print(e)
