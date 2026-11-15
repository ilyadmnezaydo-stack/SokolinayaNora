# ФАЙЛ: handlers.py

import asyncio
from html import escape
from datetime import datetime, date
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext

# --- ИМПОРТЫ ---
from keyboards import main_menu, games_menu, review_menu
from database import get_all_games, add_participant_db, get_game_by_id
from notifications import notify_admins
from sync_service import instant_add_user_to_sheet

router = Router()

# ... (Утилиты дат и форматирования) ...
RU_DOW_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _parse_date_guess(dstr: str) -> date | None:
    if not dstr: return None
    s = dstr.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            pass
    if "." in s and len(s.split(".")) == 2:
        try:
            day, month = map(int, s.split("."))
            today = date.today()
            candidate = date(today.year, month, day)
            if candidate < today: candidate = date(today.year + 1, month, day)
            return candidate
        except:
            pass
    return None


def format_date_ui_with_weekday(raw_date: str) -> str:
    d = _parse_date_guess(raw_date)
    if d: return f"{raw_date} ({RU_DOW_SHORT[d.weekday()]})"
    return raw_date


# ======================== РЕНДЕР КАРТОЧКИ ИГРЫ ========================
async def _send_game_card(message: Message, игра: dict):
    """Отправляет карточку одной игры"""
    if игра['type'] == 'official':
        icon, desc = "🎲", "(Антикафе)"
    else:
        icon, desc = "♟", "(Гостевая)"

    # --- ИЗВЛЕЧЕНИЕ ССЫЛКИ ---
    raw_time = игра.get('time_str', игра['время'])
    external_link = None
    display_time = raw_time

    if "|||" in raw_time:
        parts = raw_time.split("|||")
        display_time = parts[0].strip()
        if len(parts) > 1:
            external_link = parts[1].strip()
    # -------------------------

    дата_ui = format_date_ui_with_weekday(игра['дата'])
    game_id = игра['col_index']
    deep_link = f"https://t.me/SokolinayaNoraBot?start=game_{game_id}"

    # ПРОВЕРКА НА ПОЛНУЮ ПОСАДКУ
    занято = len(игра['участники'])
    лимит = игра['лимит']
    мест_нет = занято >= лимит

    # === ЛОГИКА ФОРМИРОВАНИЯ ТЕКСТА ===
    if external_link:
        # ВАРИАНТ 1: Игра по ссылке (Скрываем места и участников)
        text_val = (
            f"{icon} <b>{игра['игра']}</b> {desc}\n"
            f"📅 Дата: <b>{дата_ui}</b>\n"
            f"🕒 Время: <b>{display_time}</b>\n"
            f"👤 Хост: {игра['хост']}\n\n"
            f"💌 <b>Хочешь позвать друга?</b>\n"
            f"Перешли ему это сообщение! Ссылка на игру:\n"
            f"👉 <a href='{deep_link}'><b>Открыть в боте</b></a> 👈"
        )
    else:
        # ВАРИАНТ 2: Обычная игра (Показываем всё)
        участники_str = "\n".join([f"• {escape(str(u))}" for u in игра['участники']]) if игра['участники'] else "Пока пусто"

        # Если мест нет, добавляем пометку в текст (опционально)
        status_line = f"🪑 Мест: <b>{занято}</b> из {лимит}"
        if мест_нет:
            status_line += " ⛔ <b>(Полная посадка)</b>"

        text_val = (
            f"{icon} <b>{игра['игра']}</b> {desc}\n"
            f"📅 Дата: <b>{дата_ui}</b>\n"
            f"🕒 Время: <b>{display_time}</b>\n"
            f"👤 Хост: {игра['хост']}\n"
            f"{status_line}\n\n"
            f"💌 <b>Хочешь позвать друга?</b>\n"
            f"Перешли ему это сообщение! Ссылка для записи:\n"
            f"👉 <a href='{deep_link}'><b>Открыть игру в боте</b></a> 👈\n\n"
            f"🙋‍♂️ <b>Участники:</b>\n{участники_str}"
        )

    # === ЛОГИКА КНОПОК ===
    kb_rows = []

    if external_link:
        kb_rows.append([
            InlineKeyboardButton(text="🔗 Регистрация по ссылке", url=external_link)
        ])
        text_val += "\n\n⚠️ <i>Регистрация на эту игру проходит на внешнем сайте.</i>"
    else:
        stop_words = ["форма", "лс", "личка", "сайт", "директ"]
        if any(w in display_time.lower() for w in stop_words):
            kb_rows.append([
                InlineKeyboardButton(text="ℹ️ Как записаться?", callback_data=f"info_alert_{game_id}")
            ])
        else:
            # === ИСПРАВЛЕНИЕ: БЛОКИРОВКА ЗАПИСИ, ЕСЛИ МЕСТ НЕТ ===
            if мест_нет:
                kb_rows.append([
                    InlineKeyboardButton(text="⛔ Мест нет", callback_data="game_full_alert")
                ])
            else:
                kb_rows.append([
                    InlineKeyboardButton(text="✅ Записаться", callback_data=f"join_db_{game_id}")
                ])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await message.answer(text_val, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


# ======================== /START ========================
@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    args = command.args

    # 1. Переход по deep link (game_123)
    if args and args.startswith("game_"):
        try:
            game_id = int(args.replace("game_", ""))
            game = await asyncio.to_thread(get_game_by_id, game_id)

            if game:
                await message.answer(f"🚀 <b>Вы перешли по ссылке на игру:</b>\n{game['игра']}")
                await _send_game_card(message, game)
                return
            else:
                await message.answer("⚠️ Игра не найдена (возможно, она уже прошла).")
        except Exception:
            await message.answer("⚠️ Некорректная ссылка.")

    # 2. Обычный старт
    text_val = (
        f"Привет, <b>{message.from_user.first_name}</b>! 👋 Это бот Антикафе Соколиная Нора!\n\n"
        "Я помогу тебе забронировать место, записаться на игротеки и узнать тарифы."
    )
    try:
        photo = FSInputFile("sokol_logo.jpg")
        await message.answer_photo(photo=photo, caption=text_val, parse_mode="HTML", reply_markup=main_menu)
    except:
        await message.answer(text_val, parse_mode="HTML", reply_markup=main_menu)


# ======================== СПИСОК ИГР (БЕЗ ФИЛЬТРА FULL) ========================
user_lock_anticafe = {}


@router.message(lambda m: m.text and m.text.strip().lower() == "записаться на игротеку")
async def show_all_games_combined(message: Message):
    user_id = message.from_user.id
    if user_lock_anticafe.get(user_id): return
    user_lock_anticafe[user_id] = True

    loading = await message.answer("⏳ Загружаю список игр...")
    try:
        games = await asyncio.to_thread(get_all_games)
        try:
            await loading.delete()
        except:
            pass

        if not games:
            await message.answer("😔 Нет доступных игр.")
            return

        # === ИСПРАВЛЕНИЕ: УБРАЛИ ФИЛЬТР ПО ЛИМИТУ ===
        # Раньше тут было: active_games = [g for g in games if len(g['участники']) < g['лимит']]
        # Теперь мы показываем ВСЕ игры, а кнопку блокируем в _send_game_card

        # Можно добавить проверку на пустоту базы
        if not games:
            await message.answer("😔 Список игр пока пуст.")
            return

        for игра in games:
            await _send_game_card(message, игра)

        # Гостевые игротеки живут в отдельном листе и раньше были недостижимы из меню
        await message.answer(
            "🎭 Хочешь записаться на гостевую игротеку?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Гостевые игротеки", callback_data="гостевые_игротеки")
            ]])
        )

    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")
    finally:
        user_lock_anticafe.pop(user_id, None)


# ======================== ОБРАБОТКА ЗАПИСИ ========================
user_join_lock = {}


# НОВЫЙ ХЕНДЛЕР: Уведомление, что мест нет
@router.callback_query(F.data == "game_full_alert")
async def alert_game_full_callback(callback: CallbackQuery):
    await callback.answer("❌ К сожалению, на эту игру уже нет свободных мест.", show_alert=True)


@router.callback_query(F.data.startswith("join_db_"))
async def join_game_db(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if user_join_lock.get(user_id):
        await callback.answer("⏳ ...", show_alert=False)
        return
    user_join_lock[user_id] = True

    try:
        game_id = int(callback.data.split("_")[2])
        user_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

        # 1. Запись в БД
        status = await asyncio.to_thread(add_participant_db, game_id, user_name)

        if status == 'OK':
            await callback.answer("✅ Записано!", show_alert=False)

            game_info = await asyncio.to_thread(get_game_by_id, game_id)
            if game_info:
                # Мгновенная запись в Google
                if game_info['type'] == 'official':
                    asyncio.create_task(
                        instant_add_user_to_sheet(
                            game_info['игра'],
                            game_info['дата'],
                            user_name
                        )
                    )

                # Уведомление
                head = "📥 <b>НОВАЯ ЗАПИСЬ (АНТИКАФЕ)</b>" if game_info[
                                                                 'type'] == 'official' else "📥 <b>НОВАЯ ЗАПИСЬ (ГОСТЬ)</b>"
                admin_text = (
                    f"{head}\n━━━━━━━━━━━━━━━━\n"
                    f"👤 {user_name}\n🎲 {game_info['игра']}\n🗓 {game_info['дата']} {game_info['время']}"
                )
                await notify_admins(bot, admin_text)

                await callback.message.answer(
                    f"✅ <b>Вы записаны на {game_info['игра']}!</b>\n"
                    "Для отмены перейдите в раздел «Мои брони».",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📂 Мои брони", callback_data="my_bookings")]
                    ])
                )

                # Опционально: можно перерисовать карточку, чтобы кнопка сразу стала "Мест нет", если это был последний слот
                # await _send_game_card(callback.message, await asyncio.to_thread(get_game_by_id, game_id))


        elif status == 'ALREADY':
            await callback.answer("⚠️ Вы уже записаны!", show_alert=True)
        elif status == 'FULL':
            # На всякий случай обрабатываем статус FULL, если кто-то успел нажать кнопку до обновления
            await callback.answer("❌ Мест нет (кто-то успел быстрее).", show_alert=True)
            # Можно обновить сообщение
        else:
            await callback.answer("🚫 Ошибка.", show_alert=True)

    except Exception as e:
        print(f"Join Error: {e}")
        await callback.answer("Ошибка записи.", show_alert=True)
    finally:
        user_join_lock.pop(user_id, None)


@router.callback_query(F.data.startswith("info_alert_"))
async def show_custom_reg_info(callback: CallbackQuery):
    await callback.answer("📝 Запись ведется через хоста (см. описание).", show_alert=True)


# ======================== Остальные кнопки меню ========================

@router.message(F.text.lower() == "создать свою игротеку")
async def show_games_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите игру из меню настолок:", reply_markup=games_menu)


@router.message(F.text.lower() == "отзывы")
async def send_reviews(message: Message):
    await message.answer("Наши отзывы:", reply_markup=review_menu)


@router.message(F.text.lower() == "где мы находимся?")
async def send_location(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🗺 Построить маршрут (Яндекс.Карты)",
            url="https://yandex.ru/maps/?rtext=~55.783175,37.737598"
        )],
        [InlineKeyboardButton(
            text="🌍 Открыть в Google Maps",
            url="https://www.google.com/maps/search/?api=1&query=55.783175,37.737598"
        )]
    ])

    await message.answer(
        "📍 Мы находимся по адресу:\n"
        "<b>Ул. Щербаковская 53к2, Москва</b>\n\n"
        "⬇ Выберите карту для построения маршрута:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(lambda m: m.text and m.text.strip().lower() == "тариф")
async def send_tariffs(message: Message):
    tariff_text = (
        "<b>💰 Наши тарифы с 01.09.2025:</b>\n\n"
        "🕘 Первый час 240 руб.\n"
        "Второй час и далее – 4 руб./мин.\n"
        "Стопчек будни – 700 руб.\n"
        "Стопчек пятница и выходные – 900 руб.\n\n"
        "⛔️ <i>*Стопчек - cумма, больше которой вы не заплатите</i>\n\n"
        "🎲 Игротека с ведущим будни – 700 руб.\n"
        "Игротека с ведущим пятница и выходные – 900 руб.\n\n"
        "💼 Абонемент коворкинг 30 дней будни до 18.00 – 6 000 руб.\n"
        "👑 Абонемент безлимит 30 дней – 8 000 руб.\n\n"
        "🏡 Аренда мягкой комнаты будни – 800 руб./час\n"
        "Аренда мягкой комнаты пятница и выходные – 1 100 руб./час\n\n"
        "🏠 Аренда большой комнаты будни – 1 100 руб./час\n"
        "Аренда большой комнаты пятница и выходные – 1 600 руб./час\n\n"
        "☕️🫖🍪 В стоимость входит чай, кофе, печеньки в неограниченном количестве!\n"
        "🍔🍕🍸 Вы можете принести с собой свою еду и/или напитки!"
    )

    await message.answer(tariff_text, parse_mode="HTML")