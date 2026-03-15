from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Забронировать")],
        [KeyboardButton(text="Создать свою игротеку")],
        [KeyboardButton(text="Записаться на игротеку")],
        [KeyboardButton(text="Мои брони")],
        [KeyboardButton(text="Отзывы"), KeyboardButton(text="Где мы находимся?")],
        [KeyboardButton(text="Тариф")]
    ],
    resize_keyboard=True
)

booking_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Забронировать стол", callback_data="book_table")],
        [InlineKeyboardButton(text="Забронировать большую комнату", callback_data="book_big_room")],
        [InlineKeyboardButton(text="Забронировать маленькую комнату", callback_data="book_small_room")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
)

def build_confirm_keyboard(event_id: str, key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking")],
            [InlineKeyboardButton(text="❌Отменить", callback_data=f"user_cancel_{event_id}_{key}")]
        ]
    )

# Подтверждение записи на игротеку (динамически создаётся)
def get_igroteka_confirm_menu(game_name: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{game_name}"),
            InlineKeyboardButton(text="❌ Удалить запись", callback_data=f"cancel_{game_name}")
        ]
    ])

# Меню тарифов и игротек
igroteka_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📘 Меню настолок", callback_data="games_menu")],
    [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
])

# Меню отзывов — только две кнопки и Назад
review_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⭐️Наши отзывы на ЯндексКартах", callback_data="show_live_reviews")],
    [InlineKeyboardButton(text="Оставить отзыв на ЯндексКартах", url="https://yandex.ru/maps/213/moscow/?ll=37.737082%2C55.783465&mode=poi&poi%5Bpoint%5D=37.737598%2C55.783175&poi%5Buri%5D=ymapsbm1%3A%2F%2Forg%3Foid%3D204283434707&tab=reviews&z=18.47")],
    [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
])


games_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Создать свою игротеку", callback_data="create_igroteka")],
        [InlineKeyboardButton(text="🔎 Поиск по названию", callback_data="search_game")],  # ← ЗАПЯТАЯ тут!
        [InlineKeyboardButton(text="📂 По жанрам", callback_data="show_games")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
)

back_to_menu_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
    ]
)

after_booking_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои брони", callback_data="my_bookings")],
    ]
)

def get_appeal_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Обжаловать бан", callback_data="appeal_ban")]
    ])

def get_admin_unmute_button(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Снять мут", callback_data=f"unmute_{user_id}")]
    ])

def get_admin_unban_button(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪬 Разблокировать", callback_data=f"unban_{user_id}")]
    ])
