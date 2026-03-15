from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils import send_long_text
from keyboards import games_menu
from igroteka_games import получить_жанры_и_игры
from keyboards import back_to_menu_keyboard
router = Router()

class GameSearch(StatesGroup):
    entering_name = State()
    entering_filter = State()

@router.callback_query(F.data == "games_menu")
async def открыть_меню_настолок(callback: CallbackQuery):
    await callback.message.answer("📘 Меню настолок:", reply_markup=games_menu)
    await callback.answer()

@router.callback_query(F.data == "show_games")
async def показать_жанры(callback: CallbackQuery):
    жанры = получить_жанры_и_игры()
    if not жанры:
        await callback.message.answer("😕 Жанры не найдены.")
        return

    клавиатура = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=жанр, callback_data=f"genre_{жанр}")]
            for жанр in жанры
        ]
    )
    await callback.message.answer("📚 Выберите жанр настолок:", reply_markup=клавиатура)
    await callback.answer()

@router.callback_query(F.data.startswith("genre_"))
async def показать_игры_по_жанру(callback: CallbackQuery):
    жанр = callback.data.replace("genre_", "")
    жанры = получить_жанры_и_игры()
    игры = жанры.get(жанр)

    if not игры:
        await callback.message.answer("❌ В этом жанре пока нет игр.")
        await callback.answer()
        return

    текст = ""
    for игра in игры:
        текст += (
            f"🎲 <b>{игра['название']}</b>\n"
            f"📚 Полка: {игра['полка']}\n"
            f"🕒 Время: {игра['время']} мин\n"
            f"👶 Возраст: {игра['возраст']}\n"
            f"📅 Добавлена: {игра['дата']}\n\n"
        )
    await send_long_text(callback.message, текст)
    await callback.answer()

@router.callback_query(F.data == "search_game")
async def начать_поиск(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Введите часть названия игры:")
    await state.set_state(GameSearch.entering_name)
    await callback.answer()

@router.message(GameSearch.entering_name)
async def выполнить_поиск(message: Message, state: FSMContext):
    запрос = message.text.lower()
    жанры = получить_жанры_и_игры()
    результаты = []

    for игры in жанры.values():
        for игра in игры:
            if запрос in игра['название'].lower():
                результаты.append(игра)

    if not результаты:
        await message.answer(
            "🙁 Ничего не найдено. Попробуйте другое название или выйдите в меню.",
            reply_markup=back_to_menu_keyboard
        )
    else:
        текст = ""
        for игра in результаты[:10]:
            текст += (
                f"🎲 <b>{игра['название']}</b>\n"
                f"📚 Полка: {игра['полка']}\n"
                f"🕒 Время: {игра['время']} мин\n"
                f"👶 Возраст: {игра['возраст']}\n"
                f"📅 Добавлена: {игра['дата']}\n\n"
            )
        await send_long_text(message, текст)
        await message.answer(
            "Хотите найти другую игру? Введите название или выйдите в меню.",
            reply_markup=back_to_menu_keyboard
        )

    # ! Не делай await state.clear() сразу!


@router.callback_query(F.data == "filter_game")
async def начать_фильтрацию(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🧮 Введите сложность и максимальное время (например: легко 60):")
    await state.set_state(GameSearch.entering_filter)
    await callback.answer()

@router.message(GameSearch.entering_filter)
async def выполнить_фильтрацию(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split()
        сложность_запрос = parts[0].lower()
        время_макс = int(parts[1])
    except:
        await message.answer("❌ Формат: сложность и максимальное время, например: легко 45")
        return

    жанры = получить_жанры_и_игры()
    результаты = []

    for игры in жанры.values():
        for игра in игры:
            сложность_игры = str(игра.get('сложность', '')).lower()
            try:
                время_игры = int(str(игра['время']).strip())
            except:
                continue

            # Фильтруем по сложности и времени
            if сложность_игры == сложность_запрос and время_игры <= время_макс:
                результаты.append(игра)

    if not результаты:
        await message.answer("🙁 Подходящих игр не найдено.")
    else:
        текст = ""
        for игра in результаты[:10]:
            текст += (
                f"🎲 <b>{игра['название']}</b>\n"
                f"📚 Полка: {игра['полка']}\n"
                f"🕒 Время: {игра['время']} мин\n"
                f"💡 Сложность: {игра.get('сложность', '—')}\n"
                f"👶 Возраст: {игра.get('возраст', '—')}\n"
                f"📅 Добавлена: {игра.get('дата', '—')}\n\n"
            )
        await send_long_text(message, текст)

    await state.clear()
    
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Вы вернулись в главное меню. Выберите пункт ниже.", reply_markup=games_menu)
    await callback.answer()
