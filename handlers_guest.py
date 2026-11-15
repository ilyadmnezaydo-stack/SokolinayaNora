import asyncio
from html import escape
from datetime import datetime, date

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from calendar_api import service, CALENDAR_IDS
from my_bookings import _render_bookings_for_user
from admin_panel import notify_admins
from keyboards import main_menu
from sheets_api_guest_refactored import (
    удалить_участника_гостевые,
    получить_гостевые_игротеки_данные,
    перекрасить_гостевую_игротеку,
)
from database import get_game_by_id, add_participant_db

guest_router = Router()
MAX_CALLBACK_LENGTH = 64
TIMEOUT_CANCEL_MINUTES = 10

guest_click_locks = {}

# ====== 🗓 Утилиты для дат/времени ======

# Карта дней недели: Monday=0 ... Sunday=6
РУ_ДНИ_ПОЛНЫЕ = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

def _parse_date_maybe(s: str) -> date | None:
    """Пробуем распарсить дату в нескольких популярных форматах."""
    if not s:
        return None
    s = s.strip()
    fmts = ["%Y-%m-%d", "%d.%m.%Y", "%Y.%m.%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def _extract_date_from_game(игра: dict) -> date | None:
    """
    Пытаемся достать date из полей игры.
    Предпочтение: 'дата' -> 1-й токен 'дата_время' до пробела.
    """
    # 1) Пробуем поле 'дата'
    d = _parse_date_maybe(игра.get('дата', ''))
    if d:
        return d
    # 2) Пробуем левую часть 'дата_время'
    dv = (игра.get('дата_время') or '').strip()
    if dv:
        left = dv.split()[0]
        d = _parse_date_maybe(left)
        if d:
            return d
    return None

def формат_дата_время_с_днем(игра: dict, дата_str: str = None, время_str: str = None) -> str:
    """
    Возвращает строку вида: '2025-11-05 18:00 (Среда)' или '05.11.2025 18:00 (Среда)'
    Берём дату из аргумента или вычисляем из игры; время — из аргумента или правой части 'дата_время'.
    Если не удаётся распарсить дату — просто добавим исходную строку без дня недели.
    """
    d_obj = None
    # Определяем дату-объект
    if дата_str:
        d_obj = _parse_date_maybe(дата_str)
    if not d_obj:
        d_obj = _extract_date_from_game(игра)

    # Определяем человекочитаемую базовую строку даты+времени
    if дата_str and время_str:
        base = f"{дата_str} {время_str}".strip()
    else:
        # Пытаемся взять из 'дата_время' как есть
        base = (игра.get('дата_время') or '').strip()
        if not base and дата_str:
            # fallback
            base = дата_str
            if время_str:
                base += f" {время_str}"

    if d_obj:
        weekday = РУ_ДНИ_ПОЛНЫЕ[d_obj.weekday()]
        return f"{base} ({weekday})"
    else:
        # не смогли вычислить день недели — возвращаем как есть
        return base

# 🛠 Утилита: Получить игру по col_index
def получить_гостевую_игру(col_index: int) -> dict | None:
    игры = получить_гостевые_игротеки_данные()
    return next((i for i in игры if i["col_index"] == col_index), None)

# 🧷 Проверка длины callback_data
def validate_callback(callback_data: str) -> str:
    if len(callback_data.encode('utf-8')) > MAX_CALLBACK_LENGTH:
        raise ValueError(f"callback_data слишком длинное: {callback_data}")
    return callback_data

# 📌 Показать все гостевые игротеки
@guest_router.callback_query(F.data.contains("гостевую игротеку"))
async def handle_guest(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем и устанавливаем блокировку
    if guest_click_locks.get(user_id):
        await callback.answer("⏳ Пожалуйста, подождите...", show_alert=False)
        return

    guest_click_locks[user_id] = True

    try:
        игротеки = получить_гостевые_игротеки_данные()

        if not игротеки:
            await callback.message.answer(
                "😔 Сейчас нет доступных гостевых игротек для записи.",
                reply_markup=main_menu
            )
            return

        for игра in игротеки:
            участники = игра.get('участники', [])
            участники_str = "\n".join([f"• {escape(str(u))}" for u in участники]) if участники else "Пока никто не записан"

            дата_время_с_днем = формат_дата_время_с_днем(игра)

            текст = (
                f"🎲 <b>{игра['игра']}</b>\n"
                f"📅 Дата/время: <b>{дата_время_с_днем}</b>\n"
                f"👤 Организатор: {игра['хост']}\n"
                f"💺 Лимит мест: <b>{игра['лимит']}</b>\n\n"
                f"🙋‍♂️ <b>Участники:</b>\n{участники_str}\n\n"
                f'👉 Для записи на игру <a href="https://t.me/SokolinayaNoraBot">нажми сюда</a>'
            )

            callback_data = validate_callback(f"join_guest_{игра['col_index']}")

            клавиатура = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"✅ Записаться на {игра['игра']}",
                            callback_data=callback_data
                        )
                    ],
                ]
            )

            await callback.message.answer(
                text=текст,
                reply_markup=клавиатура,
                parse_mode="HTML"
            )

    finally:
        await asyncio.sleep(0.1)
        guest_click_locks.pop(user_id, None)

# 📌 Записаться на игру
# handlers_guest.py

# handlers_guest.py

@guest_router.callback_query(F.data.startswith("join_guest_"))
async def join_guest_game(callback: CallbackQuery):
    try:
        # ⚡️ МГНОВЕННЫЙ ОТВЕТ
        await callback.answer("⏳ Проверяю места...", show_alert=False)

        game_id = int(callback.data.split("_")[2])
        игра = get_game_by_id(game_id)
        if not игра:
            await callback.message.answer("Игра не найдена.")
            return
    except Exception:
        return

    имя = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    # Пишем в БД (вместе с user_id, чтобы отмена была строго по человеку)
    успешно = await asyncio.to_thread(add_participant_db, game_id, имя, callback.from_user.id)

    if успешно:
        # Уведомляем админа
        await notify_admins(
            callback.bot,
            (
                "📥 <b>НОВАЯ ЗАПИСЬ (ГОСТЬ)</b>\n"
                "━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Гость:</b> {имя}\n"
                f"♟ <b>Игра:</b> {игра['игра']}\n"
                f"🗓 <b>Дата:</b> {игра['дата']} {игра['время']}"
            )
        )

        # Переходим в "Мои брони"
        await _render_bookings_for_user(callback, service, CALENDAR_IDS, is_edit=True)
    else:
        await callback.message.answer("⚠️ Мест нет или вы уже записаны.")


# ⏱ Асинхронная задача автосброса
async def автосброс_записи(bot: Bot, col_index: int, имя: str):
    await asyncio.sleep(TIMEOUT_CANCEL_MINUTES * 60)
    игра = получить_гостевую_игру(col_index)
    if not игра:
        return
    дата = игра['дата']
    время = игра['дата_время'].split()[1]

    успешно = удалить_участника_гостевые(дата, игра['игра'], время, имя)
    if успешно:
        дата_время_с_днем = формат_дата_время_с_днем(игра, дата_str=дата, время_str=время)
        await notify_admins(
            bot,
            (
                "⏱ <b>Автосброс участника по таймеру:</b>\n"
                f"👤 {имя}\n"
                f"🎲 <b>{игра['игра']}</b>\n"
                f"🗓 {дата_время_с_днем}"
            )
        )

# 📌 Отменить одну запись
@guest_router.callback_query(F.data.startswith("remove_guest_"))
async def remove_guest_booking(callback: CallbackQuery):
    try:
        col_index = int(callback.data.split("_")[2])
        игра = получить_гостевую_игру(col_index)
        if not игра:
            raise ValueError("Игра не найдена.")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return

    дата = игра['дата']
    время = игра['дата_время'].split()[1]
    имя = "@" + (callback.from_user.username or callback.from_user.full_name)

    успешно = удалить_участника_гостевые(дата, игра['игра'], время, имя)
    if успешно:
        # 🔵 перекраска гостевого листа
        await asyncio.to_thread(перекрасить_гостевую_игротеку, дата, игра['игра'], время)

        дата_время_с_днем = формат_дата_время_с_днем(игра, дата_str=дата, время_str=время)
        await callback.message.edit_text(
            f"❌ Ваша запись на гостевую игротеку <b>{игра['игра']}</b> отменена!\n"
            f"🗓 Дата/время: <b>{дата_время_с_днем}</b>",
            parse_mode="HTML"
        )
        await notify_admins(
            callback.bot,
            (
                "❌ <b>Участник отменил запись на гостевую игротеку!</b>\n"
                f"👤 {имя}\n"
                f"🎲 <b>{игра['игра']}</b>\n"
                f"🗓 {дата_время_с_днем}"
            )
        )
        await callback.answer("Запись отменена.", show_alert=True)
    else:
        await callback.answer("Не удалось отменить запись.", show_alert=True)

@guest_router.callback_query(F.data == "guest_cancel_all")
async def отменить_все_мои_гостевые_брони(callback: CallbackQuery, bot: Bot):
    имя = "@" + (callback.from_user.username or callback.from_user.full_name)
    актуальные = получить_гостевые_игротеки_данные()
    удалено = 0

    for игра in актуальные:
        дата = игра['дата']
        время = игра['дата_время'].split()[1]
        if удалить_участника_гостевые(дата, игра['игра'], время, имя):
            удалено += 1
            # 🔵 перекраска гостевого листа
            await asyncio.to_thread(перекрасить_гостевую_игротеку, дата, игра['игра'], время)
            await notify_admins(
                bot,
                (
                    "❌ <b>Гость отменил бронь:</b>\n"
                    f"👤 {имя}\n"
                    f"🎲 <b>{игра['игра']}</b>\n"
                    f"📅 {дата}"
                )
            )

    await callback.answer("Все ваши гостевые брони отменены!", show_alert=True)
    await callback.message.edit_text(
        "❌ Все ваши гостевые брони успешно удалены." if удалено else "У вас не было гостевых записей."
    )
