# ФАЙЛ: my_bookings.py

import asyncio
from datetime import datetime, timezone

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from aiogram.filters import Command

# Импорты API
from calendar_api import service, CALENDAR_IDS, удалить_бронь
from database import get_all_games, remove_participant_db, get_game_by_id
from notifications import notify_admins

# === ИМПОРТ ФУНКЦИИ МГНОВЕННОГО УДАЛЕНИЯ ===
from sync_service import instant_remove_user_from_sheet

router = Router()


async def _render_bookings_for_user(event: types.TelegramObject, service_obj, calendar_ids_dict, is_edit=False):
    """
    Универсальная функция, которая собирает брони и отправляет их пользователю.
    """
    if isinstance(event, Message):
        user = event.from_user
        message = event
        is_edit = False
    elif isinstance(event, CallbackQuery):
        user = event.from_user
        message = event.message
    else:
        return

    user_id = str(user.id)
    username = user.username
    full_name = user.full_name

    # Список имен для поиска (все варианты в нижнем регистре без @)
    search_terms = [user_id]
    if username:
        search_terms.append(username.lower().replace("@", ""))
    if full_name:
        search_terms.append(full_name.lower())

    text_result = "<b>📋 Ваши активные записи:</b>\n\n"
    has_bookings = False
    cancel_buttons = []

    # --- 1. ПОИСК БРОНЕЙ ПОМЕЩЕНИЙ (Google Calendar) ---
    now = datetime.now(timezone.utc).isoformat()

    for key, cal_id in calendar_ids_dict.items():
        try:
            events_result = await asyncio.to_thread(
                service_obj.events().list(
                    calendarId=cal_id,
                    timeMin=now,
                    singleEvents=True,
                    orderBy='startTime',
                    q=user_id
                ).execute
            )
            items = events_result.get('items', [])

            for event_item in items:
                desc = event_item.get('description', '').lower()
                summary = event_item.get('summary', '').lower()
                event_id_cal = event_item['id']

                if user_id in desc or user_id in summary:
                    has_bookings = True
                    start = event_item['start'].get('dateTime') or event_item['start'].get('date')
                    try:
                        start_dt = datetime.fromisoformat(start)
                        fmt_date = start_dt.strftime("%d.%m %H:%M")
                    except:
                        fmt_date = start

                    real_summary = event_item.get('summary', 'Без названия')

                    text_result += (
                        f"🏨 <b>{key.title()}</b>\n"
                        f"📅 {fmt_date}\n"
                        f"📝 {real_summary}\n\n"
                    )

                    btn_text = f"❌ Отменить: {key.title()} ({fmt_date})"
                    cancel_buttons.append([InlineKeyboardButton(
                        text=btn_text,
                        callback_data=f"del_cal_{key}_{event_id_cal}"
                    )])

        except Exception as e:
            print(f"Ошибка чтения календаря {key}: {e}")

    # --- 2. ПОИСК ИГР (SQLite Database) ---
    try:
        all_games = await asyncio.to_thread(get_all_games)
        for game in all_games:
            is_participating = False

            # Проверяем, есть ли пользователь в списке участников
            for p in game.get('участники', []):
                p_clean = p.lower().replace("@", "").strip()
                # Ищем совпадение по любому из вариантов имени (username, full_name, id)
                for term in search_terms:
                    if term in p_clean:
                        is_participating = True
                        break
                if is_participating: break

            if is_participating:
                has_bookings = True
                icon = "🎲" if game['type'] == 'official' else "♟"

                text_result += (
                    f"{icon} <b>{game['игра']}</b>\n"
                    f"📅 {game['дата']} {game['время']}\n"
                    f"👤 Хост: {game['хост']}\n\n"
                )

                cancel_buttons.append([InlineKeyboardButton(
                    text=f"❌ Отменить: {game['игра']}",
                    callback_data=f"cancel_game_{game['col_index']}"
                )])

    except Exception as e:
        print(f"Ошибка поиска в БД: {e}")

    if not has_bookings:
        msg_text = "📭 У вас пока нет активных записей."
    else:
        msg_text = text_result

    cancel_buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="my_bookings")])
    kb = InlineKeyboardMarkup(inline_keyboard=cancel_buttons)

    if is_edit and isinstance(event, CallbackQuery):
        try:
            await message.edit_text(msg_text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await message.answer(msg_text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(msg_text, parse_mode="HTML", reply_markup=kb)


# --- ХЕНДЛЕРЫ ---

@router.message(F.text.lower().in_({"мои брони", "мои записи", "брони"}))
async def cmd_my_bookings_text(message: Message):
    await _render_bookings_for_user(message, service, CALENDAR_IDS, is_edit=False)


@router.callback_query(F.data == "my_bookings")
async def show_my_bookings_callback(callback: CallbackQuery):
    await callback.answer("Обновляю...")
    await _render_bookings_for_user(callback, service, CALENDAR_IDS, is_edit=True)


# ОТМЕНА БРОНИ КАЛЕНДАРЯ
@router.callback_query(F.data.startswith("del_cal_"))
async def cancel_calendar_booking(callback: CallbackQuery):
    try:
        parts = callback.data.split("_")
        cal_key = parts[2]
        event_id = "_".join(parts[3:])

        success = await asyncio.to_thread(удалить_бронь, event_id, cal_key)

        if success:
            await callback.answer("✅ Бронь удалена.", show_alert=True)
            user_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
            admin_text = (
                f"❌ <b>ОТМЕНА БРОНИ ({cal_key.upper()})</b>\n"
                "━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Гость:</b> {user_name}\n"
                f"🆔 <b>User ID:</b> {callback.from_user.id}\n"
                f"ℹ️ Удалено через бота."
            )
            await notify_admins(callback.bot, admin_text)
        else:
            await callback.answer("⚠️ Ошибка удаления.", show_alert=True)

        await _render_bookings_for_user(callback, service, CALENDAR_IDS, is_edit=True)

    except Exception as e:
        print(f"Calendar Cancel Error: {e}")
        await callback.answer("Ошибка при отмене.", show_alert=True)


# ОТМЕНА ЗАПИСИ НА ИГРУ
@router.callback_query(F.data.startswith("cancel_game_"))
async def cancel_my_game_booking(callback: CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[2])
        game = await asyncio.to_thread(get_game_by_id, game_id)

        if not game:
            await callback.answer("Игра не найдена.", show_alert=True)
            await _render_bookings_for_user(callback, service, CALENDAR_IDS, is_edit=True)
            return

        # === УЛУЧШЕННЫЙ ПОИСК ИМЕНИ ===
        # Нам нужно найти точное имя, записанное в БД, чтобы передать его в instant_remove
        target_name = None
        my_username = callback.from_user.username or ""
        my_fullname = callback.from_user.full_name or ""

        search_terms = []
        if my_username: search_terms.append(my_username.lower().replace("@", ""))
        if my_fullname: search_terms.append(my_fullname.lower())

        for p in game['участники']:
            p_clean = p.lower().replace("@", "").strip()
            # Проверяем вхождение username в имя участника или наоборот
            for term in search_terms:
                if term in p_clean or p_clean in term:
                    target_name = p  # Берем оригинальное имя из БД
                    break
            if target_name: break

        # Если не нашли (странно, но бывает), берем дефолт
        if not target_name:
            target_name = f"@{my_username}" if my_username else my_fullname

        # 1. Удаляем из БД
        success = await asyncio.to_thread(remove_participant_db, game_id, target_name)

        if success:
            await callback.answer("✅ Запись отменена.", show_alert=True)

            # 2. Удаляем из Таблицы (для официальных игр)
            if game['type'] == 'official':
                print(f"[DEBUG] Запуск instant_remove для: {game['игра']} | {game['дата']} | {target_name}")
                asyncio.create_task(
                    instant_remove_user_from_sheet(
                        game['игра'],
                        game['дата'],
                        target_name
                    )
                )

            # 3. Уведомляем админов
            try:
                type_label = "(Антикафе)" if game.get('type') == 'official' else "(Гостевая)"
                admin_text = (
                    f"❌ <b>ОТМЕНА ЗАПИСИ {type_label}</b>\n"
                    "━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>Гость:</b> {target_name}\n"
                    f"🎲 <b>Игра:</b> {game['игра']}\n"
                    f"🗓 <b>Дата:</b> {game['дата']} {game['время']}"
                )
                await notify_admins(callback.bot, admin_text)
            except Exception:
                pass

        else:
            await callback.answer("⚠️ Не удалось найти вашу запись.", show_alert=True)

        await _render_bookings_for_user(callback, service, CALENDAR_IDS, is_edit=True)

    except Exception as e:
        print(f"Cancel Error: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)