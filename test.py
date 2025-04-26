import pprint

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

from GoogleUploader import GoogleDiskUploader
from manga_search_func import *
from keyboard import *

# Настройки бота
API_TOKEN = ''
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)

# Инициализируем
manga_cache = MangaCache()
uploader = GoogleDiskUploader()


class Search_state(StatesGroup):
    manga_name = State()
    view = State()


async def main():
    # Инициализация

    # Запускаем фоновую задачу очистки
    cleanup_task = asyncio.create_task(uploader.start_cleanup_scheduler())

    try:
        # Запускаем бота
        await dp.start_polling(bot)
    finally:

        # Останавливаем фоновую задачу при завершении
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


# Команда /start
@dp.message(Command('start'))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.reply("Привет! Введи название манги для поиска.")
    await state.set_state(Search_state.manga_name)


@dp.message(Command('cache'))
async def print_cache(message: types.Message, state: FSMContext):
    pprint.pprint(manga_cache.cache)


# В обработчике сообщений нужно передавать state
@dp.message(Search_state.manga_name)
async def process_search(message: types.Message, state: FSMContext):
    query = message.text
    results = await search_manga(query)
    await state.update_data(manga_name=query)

    if not results:
        await message.reply("Ничего не найдено.")
        await state.clear()
        return
    await state.update_data(results=results, current_index=0)
    await send_manga_info(message, results[0], state)  # Передаем state
    await state.set_state(Search_state.view)


async def send_manga_info(
        message: types.Message | types.CallbackQuery,
        manga_data: tuple,  # (manga_url, manga_title)
        state: FSMContext,
        edit_message: bool = False
):
    manga_url, manga_title = manga_data
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    results = data.get("results", [])

    # Получаем данные из кеша
    cached_data = manga_cache.get_manga_by_url(manga_url)

    # Устанавливаем значения по умолчанию
    poster_url = None

    if cached_data:
        # Обновляем название, если есть в кеше
        manga_title = cached_data.get("title", manga_title)
        # Получаем URL постера
        poster_url = cached_data.get("poster_url")

        # Если постера нет, попробуем его загрузить
        if not poster_url:
            print(f"Постер не найден в кеше для: {manga_title}")
            poster_url = await download_poster(manga_url)
    else:
        print(f"Манга не найдена в кеше: {manga_url}")
        # Добавляем мангу в кеш (без постера)
        manga_cache.add_manga(manga_url, manga_title)

    # Создаем клавиатуру
    keyboard = get_full_keyboard(current_index, len(results), manga_url)
    caption = f"<b>{manga_title}</b>\n\n🔗 {manga_url}"

    # Отправляем сообщение
    if isinstance(message, types.CallbackQuery):
        message_obj = message.message
        if poster_url:
            try:
                media = types.InputMediaPhoto(media=poster_url, caption=caption, parse_mode="HTML")
                await message_obj.edit_media(media, reply_markup=keyboard)
            except Exception as e:
                print(f"Ошибка при отправке постера: {e}")
                await message_obj.edit_text(caption, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_obj.edit_text(caption, reply_markup=keyboard, parse_mode="HTML")
    else:
        if poster_url:
            try:
                await message.answer_photo(
                    photo=poster_url,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка при отправке постера: {e}")
                await message.answer(
                    text=caption,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        else:
            await message.answer(
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )


@dp.callback_query(F.data.startswith(('prev_', 'next_', 'download_')), StateFilter(Search_state.view))
async def process_callback(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        # Разбираем callback data
        parts = callback_query.data.split('_', 1)
        if len(parts) < 2:
            await callback_query.answer("Некорректный запрос")
            return

        action, data_part = parts

        # Получаем текущее состояние
        data = await state.get_data()
        results = data.get("results", [])
        current_index = data.get("current_index", 0)

        if not results:
            await callback_query.answer("Нет данных для отображения")
            return

        # Обработка навигации
        if action in ['prev', 'next']:
            if action == 'prev':
                current_index = max(0, current_index - 1)
            else:
                current_index = min(len(results) - 1, current_index + 1)

            await state.update_data(current_index=current_index)

            # Получаем текущую мангу
            manga_url, manga_title = results[current_index]
            await send_manga_info(
                callback_query,
                (manga_url, manga_title),
                state,
                edit_message=True
            )

        # Обработка скачивания
        elif action == 'download':
            manga_url, manga_title = results[current_index]
            manga_title = manga_title.split("/")[0]

            if 'ch' in data_part:  # Скачать главу
                chapter_num = data_part.split('ch_')[1].split('_')[0]
                await callback_query.answer(f"Начинаем скачивание главы {chapter_num}...")

            elif 'all' in data_part:
                await download_all_chapters(manga_url, manga_title, callback_query.message)
                print(manga_url)
                await uploader.upload_manga(
                    manga_title=manga_title,
                    manga_url=manga_url,
                    local_path="downloads",
                    bot=bot,
                    chat_id=callback_query.from_user.id
                )
        await callback_query.answer()

    except Exception as e:
        print(e)


# Запуск бота
if __name__ == '__main__':
    asyncio.run(main())
