import hashlib

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_full_keyboard(current_index: int, total: int, manga_url: str):
    """Создает клавиатуру для навигации и скачивания"""
    # Хешируем URL для callback_data (ограничение Telegram на длину)
    url_hash = hashlib.md5(manga_url.encode()).hexdigest()[:16]
    all_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"prev_{url_hash}"
            ),
            InlineKeyboardButton(
                text=f"{current_index + 1}/{total}",
                callback_data="current_pos"
            ),
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=f"next_{url_hash}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Скачать все",
                callback_data=f"download_all_{url_hash}"
            )
        ]
    ])
    first_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{current_index + 1}/{total}",
                callback_data="current_pos"
            ),
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=f"next_{url_hash}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Скачать все",
                callback_data=f"download_all_{url_hash}"
            )
        ]
    ])
    last_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"prev_{url_hash}"
            ),
            InlineKeyboardButton(
                text=f"{current_index + 1}/{total}",
                callback_data="current_pos"
            )
        ],
        [
            InlineKeyboardButton(
                text="Скачать текущую главу",
                callback_data=f"download_ch_1_{url_hash}"
            ),
            InlineKeyboardButton(
                text="Скачать все",
                callback_data=f"download_all_{url_hash}"
            )
        ]
    ])
    if current_index == 0:
        return first_keyboard
    elif current_index == total - 1:
        return last_keyboard
    return all_keyboard
