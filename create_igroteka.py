# ФАЙЛ: create_igroteka.py

import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
import re

# Используем функцию добавления в БД
from database import add_game_db
from notifications import notify_admins
from sheets_api_guest_refactored import добавить_гостевую_игротеку

router = Router()


class CreateIgrotekaFSM(StatesGroup):
    waiting_for_game = State()
    waiting_for_contact = State()
    waiting_for_people = State()
    waiting_for_datetime = State()
    waiting_for_confirm = State()


# Старт FSM: callback или текст
@router.callback_query(F.data == "create_igroteka")
async def start_create_igroteka(event, state: FSMContext):
    send = event.message.answer if isinstance(event, CallbackQuery) else event.answer
    await send(
        "🛠 Введите название вашей настольной игры для игротеки:\n"
        "(Можно ознакомиться с играми в разделе <b>Меню настолок</b>)"
    )
    await state.set_state(CreateIgrotekaFSM.waiting_for_game)
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(CreateIgrotekaFSM.waiting_for_game)
async def ask_contact(message: Message, state: FSMContext):
    await state.update_data(game=message.text.strip())
    await message.answer("📞 Укажите контактный номер телефона (или @username):")
    await state.set_state(CreateIgrotekaFSM.waiting_for_contact)


@router.message(CreateIgrotekaFSM.waiting_for_contact)
async def ask_people(message: Message, state: FSMContext):
    contact = message.text.strip()
    phone_re = re.compile(r"^@[\w\d_]{5,}$|^\+?\d{10,15}$")
    if not phone_re.match(contact.replace(" ", "")):
        await message.answer("❌ Введите корректный номер телефона (например, +79998887766) или @username.")
        return
    await state.update_data(contact=contact)
    await message.answer("👥 Сколько человек будет?")
    await state.set_state(CreateIgrotekaFSM.waiting_for_people)


@router.message(CreateIgrotekaFSM.waiting_for_people)
async def ask_datetime(message: Message, state: FSMContext):
    people = message.text.strip()
    if not people.isdigit() or not (1 <= int(people) <= 16):
        await message.answer("❌ Введите корректное количество человек (1-16):")
        return
    await state.update_data(people=people)
    await message.answer("📅 Введите дату и время проведения (например, 21.06.2025 17:00):")
    await state.set_state(CreateIgrotekaFSM.waiting_for_datetime)


@router.message(CreateIgrotekaFSM.waiting_for_datetime)
async def confirm_igroteka(message: Message, state: FSMContext):
    datetime_text = message.text.strip()
    # Простая проверка формата
    date_re = re.compile(r"\d{2}\.\d{2}\.\d{4} ?\d{2}:\d{2}")
    if not date_re.match(datetime_text):
        await message.answer("❌ Введите дату и время в формате: 21.06.2025 17:00")
        return

    await state.update_data(datetime=datetime_text)
    data = await state.get_data()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="igroteka_confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="igroteka_cancel"),
            ]
        ]
    )
    await message.answer(
        f"Проверьте данные:\n\n"
        f"🎲 Игра: <b>{data['game']}</b>\n"
        f"👤 Контакт: <b>{data['contact']}</b>\n"
        f"👥 Людей: <b>{data['people']}</b>\n"
        f"🗓 Дата/время: <b>{data['datetime']}</b>\n\n"
        f"Если всё верно — подтвердите.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(CreateIgrotekaFSM.waiting_for_confirm)


@router.callback_query(CreateIgrotekaFSM.waiting_for_confirm, F.data == "igroteka_confirm")
async def submit_igroteka(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()

    dt_str = data['datetime']
    parts = dt_str.split()
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "00:00"

    host_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    # Пишем в БД с типом 'guest'
    add_game_db(
        game_type='guest',
        game=data['game'],
        date_str=date_part,
        time_str=time_part,
        host=host_name,
        contact=data['contact'],
        limit=int(data['people'])
    )

    # Пишем колонку в гостевой лист: без этого созданная игра видна только в БД
    try:
        await asyncio.to_thread(
            добавить_гостевую_игротеку,
            date_part, data['game'], time_part, host_name, int(data['people'])
        )
    except Exception as e:
        print(f"[Создание игротеки -> лист] Ошибка: {e}")

    # Уведомление админам (ЧИСТОЕ, БЕЗ ССЫЛКИ НА БОТА)
    admin_text = (
        f"🛠 <b>СОЗДАНА ИГРОТЕКА (ГОСТЬ)</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Хост:</b> {host_name}\n"
        f"♟ <b>Игра:</b> {data['game']}\n"
        f"🗓 <b>Дата:</b> {dt_str}\n"
        f"👥 <b>Мест:</b> {data['people']}\n"
        f"📞 <b>Связь:</b> {data['contact']}"
    )

    # notify_admins из admin_panel
    await notify_admins(bot, admin_text)

    await callback.message.edit_text(
        "✅ Ваша игротека успешно создана и добавлена в список!\n"
        "Другие участники уже могут записываться."
    )
    await state.clear()
    await callback.answer()


@router.callback_query(CreateIgrotekaFSM.waiting_for_confirm, F.data == "igroteka_cancel")
async def cancel_igroteka(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🚫 Создание игротеки отменено. Главное меню:")
    await state.clear()
    await callback.answer()