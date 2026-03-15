import json
import html
import asyncio
from datetime import datetime, timezone, timedelta

from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импорты API Календаря
from calendar_api import CALENDAR_IDS, service

# Импорты Базы Данных
from database import (
    get_all_games,
    remove_participant_db,
    delete_game_db,
    add_participant_db,
    get_game_by_id
)
# === ИМПОРТ ФУНКЦИИ СИНХРОНИЗАЦИИ ===
from sync_service import sync_anticafe_games, instant_remove_user_from_sheet
from sheets_api_guest_refactored import удалить_участника_гостевые

# Импорт Уведомлений
from notifications import notify_admins, ADMIN_IDS

admin_router = Router()
BLOCKED_TABLES_FILE = "blocked_tables.json"


class AdminAction(StatesGroup):
    waiting_for_guest_user = State()


# --- Утилиты ---
def load_blocked_tables():
    try:
        with open(BLOCKED_TABLES_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_blocked_tables(dates):
    with open(BLOCKED_TABLES_FILE, "w", encoding="utf-8") as f:
        json.dump(list(dates), f, ensure_ascii=False)


# ======================== МЕНЮ ========================
def get_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Большая", callback_data="admin_cal_bolshaya"),
         InlineKeyboardButton(text="📅 Мягкая", callback_data="admin_cal_myagkaya")],
        [InlineKeyboardButton(text="📅 Общая", callback_data="admin_cal_obshchaya")],
        [InlineKeyboardButton(text="🎲 Игротеки (Антикафе)", callback_data="admin_igroteka_today")],
        [InlineKeyboardButton(text="♟ Гостевые Игротеки", callback_data="admin_igroteka_guest")],
        [InlineKeyboardButton(text="🚫 Блок столов", callback_data="admin_block_tables")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
    ])


back_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ В меню админа", callback_data="admin_back_to_menu")]
])


@admin_router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("🔧 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=get_admin_menu())


@admin_router.callback_query(F.data == "admin_back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🔧 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=get_admin_menu())


# === ХЕНДЛЕР СИНХРОНИЗАЦИИ ===
@admin_router.callback_query(F.data == "admin_force_sync")
async def force_sync_handler(callback: types.CallbackQuery):
    await callback.answer("⏳ Синхронизирую с Google...", show_alert=False)
    try:
        await sync_anticafe_games()
        await callback.message.answer("✅ <b>Синхронизация успешна!</b>\nБаза данных обновлена.", reply_markup=back_menu,
                                      parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}", reply_markup=back_menu)


# ======================== 1. Управление КАЛЕНДАРЯМИ (Брони) ========================
# (Оставляем без изменений, так как это работает через Google API напрямую)

CAL_KEY_MAP = {
    "bolshaya": "большая",
    "myagkaya": "мягкая",
    "obshchaya": "общая"
}


@admin_router.callback_query(F.data.startswith("admin_cal_"))
async def show_broni_for_calendar(callback: types.CallbackQuery):
    cal_key = callback.data.replace("admin_cal_", "")
    key = CAL_KEY_MAP.get(cal_key)

    if not key:
        await callback.answer("Ошибка календаря", show_alert=True)
        return

    calendar_id = CALENDAR_IDS[key]
    now = datetime.now(timezone.utc).isoformat()

    try:
        events = await asyncio.to_thread(
            service.events().list(
                calendarId=calendar_id,
                timeMin=now,
                singleEvents=True,
                orderBy="startTime"
            ).execute
        )
        items = events.get("items", [])
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка API: {e}", reply_markup=back_menu)
        return

    if not items:
        await callback.message.answer(f"📭 В календаре <b>{key.title()}</b> пусто.", reply_markup=back_menu,
                                      parse_mode="HTML")
        return

    await callback.message.answer(f"📅 <b>Брони: {key.title()}</b>", parse_mode="HTML")

    for event in items:
        summary = event.get("summary", "Без названия")
        start = (event["start"].get("dateTime") or event["start"].get("date")).replace("T", " ")[:16]
        end = (event["end"].get("dateTime") or event["end"].get("date")).replace("T", " ")[:16]
        event_id = event["id"]

        text = (
            f"🔹 <b>{html.escape(summary)}</b>\n"
            f"🕒 {start} – {end}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Удалить бронь", callback_data=f"admin_cancel_{event_id}_{key}")
        ]])

        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

    await callback.message.answer("--- Конец списка ---", reply_markup=back_menu)


@admin_router.callback_query(F.data.startswith("admin_cancel_"))
async def admin_cancel_booking(callback: types.CallbackQuery):
    try:
        _, _, event_id, key = callback.data.split("_", 3)
        calendar_id = CALENDAR_IDS[key]

        await asyncio.to_thread(service.events().delete(calendarId=calendar_id, eventId=event_id).execute)

        await callback.message.edit_text(f"✅ Бронь удалена (Календарь: {key})", reply_markup=None)
        await callback.answer("Удалено!")
    except Exception as e:
        await callback.answer(f"Ошибка удаления: {e}", show_alert=True)


# ======================== 2. Управление ИГРОТЕКАМИ (DB) ========================

async def _render_games_list(callback: types.CallbackQuery, show_type: str):
    """
    Универсальная функция рендера списка игр.
    show_type: 'official' (Антикафе) или 'guest' (Гостевые)
    """
    await callback.answer("Загружаю из базы...")

    # Получаем все игры из БД
    all_games = await asyncio.to_thread(get_all_games)

    # Фильтруем
    if show_type == 'official':
        target_games = [g for g in all_games if g['type'] == 'official']
        title = "🎲 Игротеки (Антикафе)"
    else:
        target_games = [g for g in all_games if g['type'] != 'official']
        title = "♟ Гостевые Игротеки"

    if not target_games:
        try:
            await callback.message.edit_text(f"📭 {title}: список пуст.", reply_markup=back_menu)
        except:
            await callback.message.answer(f"📭 {title}: список пуст.", reply_markup=back_menu)
        return

    try:
        await callback.message.delete()
    except:
        pass

    await callback.message.answer(f"📋 <b>{title}</b>", parse_mode="HTML")

    for игра in target_games:
        game_id = игра['col_index']  # ID БД
        участники = игра.get('участники', [])

        icon = "🎲" if show_type == 'official' else "♟"

        text = (
            f"{icon} <b>{игра['игра']}</b>\n"
            f"📅 {игра['дата']} | {игра['время']}\n"
            f"👤 Хост: {игра['хост']}\n"
            f"👥 Занято: {len(участники)}/{игра['лимит']}"
        )

        buttons = []

        # 1. Кнопки удаления участников (Кик)
        for u in участники:
            u_short = u.replace("@", "")[:10]
            buttons.append([InlineKeyboardButton(
                text=f"❌ Кикнуть {u}",
                callback_data=f"adm_kick_{game_id}_{u_short}"
            )])

        # 2. Доп кнопки
        row_actions = []
        row_actions.append(InlineKeyboardButton(text="➕ Добавить", callback_data=f"adm_add_{game_id}"))
        row_actions.append(InlineKeyboardButton(text="🗑 Удалить игру", callback_data=f"adm_del_{game_id}"))
        buttons.append(row_actions)

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

    await callback.message.answer("--- Конец списка ---", reply_markup=back_menu)


@admin_router.callback_query(F.data == "admin_igroteka_today")
async def admin_igroteka_anticafe(callback: types.CallbackQuery):
    await _render_games_list(callback, 'official')


@admin_router.callback_query(F.data == "admin_igroteka_guest")
async def admin_igroteka_guest(callback: types.CallbackQuery):
    await _render_games_list(callback, 'guest')


# --- УДАЛЕНИЕ УЧАСТНИКА (KICK) ---
@admin_router.callback_query(F.data.startswith("adm_kick_"))
async def admin_kick_user_db(callback: types.CallbackQuery):
    try:
        # Парсим callback: adm_kick_{game_id}_{username_fragment}
        parts = callback.data.split("_")
        game_id = int(parts[2])
        username_part = "_".join(parts[3:])

        # Получаем игру, чтобы найти полное имя
        game = await asyncio.to_thread(get_game_by_id, game_id)
        if not game:
            await callback.answer("Игра не найдена (возможно, удалена).", show_alert=True)
            return

        full_username = None
        for u in game['участники']:
            if username_part in u:
                full_username = u
                break

        if not full_username:
            # Если короткое имя совпало с несколькими или не найдено, пробуем удалить как есть
            full_username = username_part

        # 1. Удаляем из БД
        success = await asyncio.to_thread(remove_participant_db, game_id, full_username)

        if success:
            await callback.answer(f"✅ {full_username} удален из БД.", show_alert=False)

            # 2. Удаляем из Google Таблиц
            try:
                if game['type'] == 'official':
                    # Официальные игры (Главная таблица)
                    asyncio.create_task(
                        instant_remove_user_from_sheet(
                            game['игра'],
                            game['дата'],
                            full_username
                        )
                    )
                else:
                    # Гостевые игры (Гостевая таблица)
                    # Используем функцию из sheets_api_guest_refactored
                    # Ей нужны: дата, игра, время, имя
                    # Время берем из game['время']
                    await asyncio.to_thread(
                        удалить_участника_гостевые,
                        game['дата'],
                        game['игра'],
                        game['время'],
                        full_username
                    )
            except Exception as e_sheet:
                print(f"[Admin Kick] Ошибка удаления из таблицы: {e_sheet}")

            # Обновляем клавиатуру (убираем кнопку удаленного)
            new_kb_rows = []
            for row in callback.message.reply_markup.inline_keyboard:
                if row[0].callback_data != callback.data:
                    new_kb_rows.append(row)
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_kb_rows))
        else:
            await callback.answer("Ошибка: участник не найден в БД.", show_alert=True)

    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# --- УДАЛЕНИЕ ИГРЫ ПОЛНОСТЬЮ ---
@admin_router.callback_query(F.data.startswith("adm_del_"))
async def admin_delete_game_fully(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[2])
        await asyncio.to_thread(delete_game_db, game_id)
        await callback.answer("🗑 Игротека удалена!", show_alert=True)
        await callback.message.delete()
    except Exception as e:
        await callback.answer(f"Ошибка удаления: {e}", show_alert=True)


# --- ДОБАВЛЕНИЕ УЧАСТНИКА ВРУЧНУЮ ---
@admin_router.callback_query(F.data.startswith("adm_add_"))
async def admin_start_add_user(callback: types.CallbackQuery, state: FSMContext):
    game_id = int(callback.data.split("_")[2])
    await state.update_data(target_game_id=game_id)
    await state.set_state(AdminAction.waiting_for_guest_user)

    await callback.message.answer(
        "✍️ <b>Введите Имя или @username участника:</b>\n"
        "(Отправьте текстовым сообщением)",
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.message(AdminAction.waiting_for_guest_user)
async def admin_finish_add_user(message: types.Message, state: FSMContext):
    data = await state.get_data()
    game_id = data.get('target_game_id')
    user_name = message.text.strip()

    if not " " in user_name and not user_name.startswith("@"):
        user_name = "@" + user_name

    res = await asyncio.to_thread(add_participant_db, game_id, user_name)

    if res == "OK":
        await message.answer(f"✅ Участник <b>{user_name}</b> добавлен!", parse_mode="HTML")
    elif res == "ALREADY":
        await message.answer(f"⚠️ <b>{user_name}</b> уже записан.", parse_mode="HTML")
    elif res == "FULL":
        await message.answer(f"❌ Нет мест.", parse_mode="HTML")
    else:
        await message.answer("⚠️ Ошибка базы данных.", parse_mode="HTML")

    await state.clear()

    # Возвращаемся в меню
    await message.answer("Вернуться:", reply_markup=back_menu)


# ======================== 4. Блокировка столов (JSON) ========================

def generate_block_dates_keyboard():
    today = datetime.now()
    days = [today + timedelta(days=i) for i in range(10)]
    blocked = load_blocked_tables()

    buttons = []
    for d in days:
        d_str = d.strftime("%d.%m.%Y")
        if d_str not in blocked:
            buttons.append([InlineKeyboardButton(text=f"🚫 Заблочить {d_str}", callback_data=f"block_{d_str}")])

    if blocked:
        buttons.append([InlineKeyboardButton(text="--- Разблокировать ---", callback_data="none")])
        for b in sorted(blocked):
            buttons.append([InlineKeyboardButton(text=f"✅ Разблочить {b}", callback_data=f"unblock_{b}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@admin_router.callback_query(F.data == "admin_block_tables")
async def admin_block_tables_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("🚫 <b>Управление блокировкой столов</b>", parse_mode="HTML",
                                     reply_markup=generate_block_dates_keyboard())


@admin_router.callback_query(F.data.startswith("block_"))
async def block_date(callback: types.CallbackQuery):
    date_str = callback.data.replace("block_", "")
    blocked = load_blocked_tables()
    blocked.add(date_str)
    save_blocked_tables(blocked)
    await callback.message.edit_reply_markup(reply_markup=generate_block_dates_keyboard())


@admin_router.callback_query(F.data.startswith("unblock_"))
async def unblock_date(callback: types.CallbackQuery):
    date_str = callback.data.replace("unblock_", "")
    blocked = load_blocked_tables()
    if date_str in blocked:
        blocked.remove(date_str)
        save_blocked_tables(blocked)
    await callback.message.edit_reply_markup(reply_markup=generate_block_dates_keyboard())


# ======================== 5. Подробная Статистика (БД) ========================

@admin_router.callback_query(F.data == "admin_stats")
async def show_stats(callback: types.CallbackQuery):
    await callback.answer("⏳ Собираю данные...", show_alert=False)

    now = datetime.now(timezone.utc)
    stat_text = "<b>📊 СВОДКА</b>\n━━━━━━━━━━━━━━━━\n"

    # 1. Календари (Google API)
    stat_text += "📅 <b>Брони помещений:</b>\n"
    today_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc).isoformat()
    today_end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat()

    for key, calendar_id in CALENDAR_IDS.items():
        try:
            res = await asyncio.to_thread(
                service.events().list(
                    calendarId=calendar_id, timeMin=today_start, timeMax=today_end, singleEvents=True
                ).execute
            )
            count = len(res.get("items", []))
            stat_text += f"— {key.title()}: <b>{count}</b> сег.\n"
        except Exception:
            stat_text += f"— {key.title()}: ⚠️ Ошибка API\n"

    # 2. Игротеки (Из БД)
    stat_text += "\n🎲 <b>Игротеки (Все типы):</b>\n"

    try:
        games = await asyncio.to_thread(get_all_games)

        official_count = 0
        official_people = 0
        guest_count = 0
        guest_people = 0

        if games:
            for g in games:
                n = len(g.get('участники', []))
                if g['type'] == 'official':
                    official_count += 1
                    official_people += n
                else:
                    guest_count += 1
                    guest_people += n

            stat_text += (
                f"🏢 <b>Антикафе:</b> {official_count} игр | {official_people} чел.\n"
                f"👤 <b>Гостевые:</b> {guest_count} игр | {guest_people} чел.\n"
                f"∑ <b>Всего записей:</b> {official_people + guest_people}"
            )
        else:
            stat_text += "Игр в базе нет."

    except Exception as e:
        stat_text += f"Ошибка БД: {e}"

    await callback.message.edit_text(stat_text, parse_mode="HTML", reply_markup=back_menu)