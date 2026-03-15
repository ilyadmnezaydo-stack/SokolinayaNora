from aiogram import Router, F, types, Bot
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from datetime import datetime, time, timedelta
import re
import holidays

# Импорты API и утилит
from calendar_api import (
    создать_бронь,
    найти_свободное_время,
    получить_пересекающиеся_брони,
    CALENDAR_IDS
)
from keyboards import booking_menu, build_confirm_keyboard, main_menu
import keyboards
from admin_panel import load_blocked_tables, notify_admins

router = Router()


# ========================= Настройки и Утилиты =========================

class Booking(StatesGroup):
    booking_type = State()
    date = State()
    time = State()
    contact = State()
    people = State()


RU_HOLIDAYS = holidays.RU()

# Список команд, которые должны "ломать" FSM и выводить пользователя в меню
NAV_BUTTONS = [
    "/start",
    "забронировать",
    "создать свою игротеку",
    "записаться на игротеку",
    "мои брони",
    "отзывы",
    "где мы находимся?",
    "тариф",
    "меню"
]


def normalize_interval(date_str: str, start_str: str, end_str: str) -> tuple[datetime, datetime]:
    start_dt = datetime.strptime(f"{date_str} {start_str}", "%d.%m.%Y %H:%M")
    end_dt = datetime.strptime(f"{date_str} {end_str}", "%d.%m.%Y %H:%M")
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def check_working_hours(date_obj, start_time_str, end_time_str):
    start_t = datetime.strptime(start_time_str, "%H:%M").time()
    end_t = datetime.strptime(end_time_str, "%H:%M").time()

    weekday = date_obj.weekday()  # 0=Mon ... 6=Sun
    is_holiday = date_obj in RU_HOLIDAYS

    # Праздники и выхи (Сб, Вс): 11:00–01:00
    if is_holiday or weekday in (5, 6):
        open_t, close_t = time(11, 0), time(1, 0)
    # Пятница: 09:00–01:00
    elif weekday == 4:
        open_t, close_t = time(9, 0), time(1, 0)
    # Пн–Чт: 09:00–23:00
    else:
        open_t, close_t = time(9, 0), time(23, 0)

    open_dt = datetime.combine(date_obj, open_t)
    close_dt = datetime.combine(date_obj, close_t)

    # Если закрытие после полуночи (например, 01:00 следующего дня)
    if close_t <= open_t:
        close_dt += timedelta(days=1)

    start_dt = datetime.combine(date_obj, start_t)
    end_dt = datetime.combine(date_obj, end_t)

    # Если бронь переходит через полночь
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    if end_dt <= start_dt:
        return False

    # Проверяем, попадает ли интервал в рабочее время
    return open_dt <= start_dt and end_dt <= close_dt


# ========================= Хендлеры Бронирования =========================

# --- 🔥 НОВЫЙ ХЕНДЛЕР: ПЕРЕХВАТ НАВИГАЦИИ ---
# Этот хендлер стоит ПЕРВЫМ и проверяет: если мы в состоянии Booking
# и пользователь нажал кнопку меню — мы сбрасываем состояние.
@router.message(Booking.booking_type, F.text.lower().in_(NAV_BUTTONS))
@router.message(Booking.date, F.text.lower().in_(NAV_BUTTONS))
@router.message(Booking.time, F.text.lower().in_(NAV_BUTTONS))
@router.message(Booking.contact, F.text.lower().in_(NAV_BUTTONS))
@router.message(Booking.people, F.text.lower().in_(NAV_BUTTONS))
async def interrupt_booking_by_command(message: Message, state: FSMContext):
    await state.clear()
    # Мы не можем автоматически "нажать" кнопку за пользователя в другом роутере,
    # поэтому просто сообщаем, что вышли из режима.
    await message.answer(
        f"🔄 Вы прервали бронирование. Чтобы перейти в раздел <b>«{message.text}»</b>, нажмите на кнопку меню ещё раз.",
        parse_mode="HTML"
    )


@router.message(F.text.lower() == "забронировать")
async def start_booking(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите, что хотите забронировать:", reply_markup=booking_menu)
    await state.set_state(Booking.booking_type)


@router.callback_query(F.data.in_({"book_table", "book_big_room", "book_small_room"}))
async def choose_type(callback: types.CallbackQuery, state: FSMContext):
    # ⚡️ МГНОВЕННЫЙ ОТВЕТ (чтобы кнопка не крутилась)
    await callback.answer()

    type_map = {
        "book_table": "стол",
        "book_big_room": "большая комната",
        "book_small_room": "мягкая комната"
    }
    await state.update_data(booking_type=type_map[callback.data])
    await state.set_state(Booking.date)
    await callback.message.edit_text("📅 Введите дату бронирования (например, 18.06.2025):")


@router.message(Booking.date)
async def enter_date(message: Message, state: FSMContext):
    дата_текст = message.text.strip()

    # Доп. проверка: если пользователь ввел текст, похожий на дату, но с ошибкой - ок.
    # Но если это явно не дата, а мусор (и не кнопка меню, т.к. ее перехватили выше), предупреждаем.

    try:
        дата = datetime.strptime(дата_текст, "%d.%m.%Y")
        now = datetime.now()

        if дата.date() < now.date():
            await message.answer("⚠️ Нельзя бронировать в прошлом.")
            return
        if дата > now.replace(year=now.year + 1):
            await message.answer("⚠️ Нельзя бронировать более чем на год вперёд.")
            return

    except ValueError:
        await message.answer("❌ Неверный формат даты. Введите, например: 18.06.2025")
        return

    data = await state.get_data()
    booking_type = data.get("booking_type")

    # Проверка блокировки столов
    заблокированные = load_blocked_tables()
    if booking_type == "стол" and дата_текст in заблокированные:
        await message.answer(
            "❌ В этот день бронирование столов закрыто (мероприятие). Выберите комнату или другую дату.")
        await state.clear()
        return

    await state.update_data(date=дата_текст)
    await state.set_state(Booking.time)
    await message.answer("🕰 Введите время (например, 17:00–19:00):")


@router.message(Booking.time)
async def enter_time(message: Message, state: FSMContext):
    текст = re.sub(r"[–—−-]+", "–", message.text.strip())
    parts = текст.split("–")

    if len(parts) != 2:
        await message.answer("⚠️ Формат времени некорректен. Попробуйте ещё раз (например: 17:00–19:00)")
        return
    try:
        start_time = parts[0].strip()
        end_time = parts[1].strip()
        datetime.strptime(start_time, "%H:%M")
        datetime.strptime(end_time, "%H:%M")
    except:
        await message.answer("⚠️ Не удалось распознать время. Используйте формат: 17:00–19:00")
        return

    data = await state.get_data()
    date_str = data.get("date")
    if not date_str:
        await message.answer("⚠️ Сначала введите дату.")
        await state.set_state(Booking.date)
        return

    date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
    now = datetime.now()

    # Проверка на прошедшее время сегодня
    if date_obj == now.date():
        start_dt, end_dt = normalize_interval(date_str, start_time, end_time)
        if end_dt <= now:
            await message.answer("⚠️ Это время уже прошло сегодня.")
            return

    # Проверка рабочих часов
    if not check_working_hours(date_obj, start_time, end_time):
        await message.answer(
            "❗ В это время заведение закрыто.\n"
            "<b>Пн–Чт:</b> 09:00–23:00\n"
            "<b>Пятница:</b> 09:00–01:00\n"
            "<b>Сб, Вс:</b> 11:00–01:00\n"
            "Пожалуйста, введите другое время."
        )
        return

    await state.update_data(time=текст)
    await state.set_state(Booking.contact)
    await message.answer("📞 Укажите ваш контакт (номер телефона или @username):")


@router.message(Booking.contact)
async def enter_contact(message: Message, state: FSMContext):
    контакт = message.text.strip()
    контакт_clean = re.sub(r"[^\d+]", "", контакт)

    # Простая валидация: либо начинается с @, либо похож на телефон
    if not (контакт.startswith("@") or len(контакт_clean) >= 10):
        await message.answer("❌ Введите корректный номер телефона или @username.")
        return

    await state.update_data(contact=контакт)
    await state.set_state(Booking.people)
    await message.answer("👥 Сколько человек будет?")


@router.message(Booking.people)
async def enter_people(message: Message, state: FSMContext, bot: Bot):
    people_text = message.text.strip()
    if not people_text.isdigit():
        await message.answer("❌ Введите количество людей числом.")
        return

    people = int(people_text)
    data = await state.get_data()
    тип = data.get("booking_type")

    # Лимиты
    if "мягкая" in тип and people > 6:
        await message.answer("❗ В мягкой комнате максимум 6 человек.")
        return
    if "большая" in тип and people > 12:
        await message.answer("❗ В большой комнате максимум 12 человек.")
        return
    if people < 1:
        await message.answer("❗ Должен быть хотя бы 1 человек.")
        return

    await state.update_data(people=people)

    # Подготовка дат
    дата = data.get("date")
    время = data.get("time")
    try:
        start_str, end_str = время.split("–")
        start_dt, end_dt = normalize_interval(дата, start_str.strip(), end_str.strip())
    except Exception:
        await message.answer("⚠️ Ошибка обработки времени. Начните заново.")
        await state.clear()
        return

    await state.update_data(start=start_dt.isoformat(), end=end_dt.isoformat())

    # Проверка пересечений (только для комнат)
    if тип != "стол":
        занятые = получить_пересекающиеся_брони(start_dt, end_dt, тип)
        if занятые:
            # Если занято, ищем свободные окна
            свободные = найти_свободное_время(тип, start=start_dt, end=end_dt)

            msg = f"❗ В это время помещение занято.\n"
            if свободные:
                msg += "Вот ближайшие свободные окна:"
                buttons = []
                for slot_start, slot_end in свободные:
                    текст = f"{slot_start.strftime('%H:%M')}–{slot_end.strftime('%H:%M')}"
                    # Кодируем данные в callback
                    дата_код = slot_start.strftime('%d%m%Y')
                    время_код = f"{slot_start.strftime('%H%M')}{slot_end.strftime('%H%M')}"
                    код = f"{дата_код}_{время_код}"

                    buttons.append([InlineKeyboardButton(text=текст, callback_data=f"suggest_{код}")])

                kb = InlineKeyboardMarkup(inline_keyboard=buttons)
                await message.answer(msg, reply_markup=kb)
            else:
                await message.answer("❗ К сожалению, всё занято. Попробуйте другое время.")
                await state.set_state(Booking.time)
            return

    # Создаём "черновую" бронь, чтобы получить ID
    contact = data['contact']

    # === ИСПРАВЛЕНИЕ: Добавляем ID в строку пользователя, чтобы он попал в описание события ===
    пользователь_строка = f"{message.from_user.full_name} (ID: {message.from_user.id})"

    summary_text = f"{тип} | {people} чел | {contact} | {message.from_user.id} (@{message.from_user.username})"

    event_id = создать_бронь(
        тип=summary_text,
        пользователь=пользователь_строка,  # <-- Передаем строку с ID
        start=start_dt,
        end=end_dt
    )

    if not event_id:
        await message.answer("⚠️ Ошибка соединения с календарем. Попробуйте позже.")
        await state.clear()
        return

    await state.update_data(event_id=event_id)

    # Определяем ключ календаря для кнопки отмены
    key = next((k for k in CALENDAR_IDS if k in тип.lower()), "общая")

    await message.answer(
        f"✅ <b>Проверьте бронь перед подтверждением:</b>\n"
        f"<b>Тип:</b> {тип}\n"
        f"<b>Дата:</b> {дата}\n"
        f"<b>Время:</b> {время}\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>Людей:</b> {people}",
        reply_markup=build_confirm_keyboard(event_id, key),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("suggest_"))
async def handle_suggestion(callback: CallbackQuery, state: FSMContext):
    # ⚡️ МГНОВЕННЫЙ ОТВЕТ
    await callback.answer()

    код = callback.data.replace("suggest_", "")
    дата_str, время_str = код.split("_")
    дата = datetime.strptime(дата_str, "%d%m%Y").strftime("%d.%m.%Y")

    start_h, start_m = время_str[:2], время_str[2:4]
    end_h, end_m = время_str[4:6], время_str[6:8]
    время = f"{start_h}:{start_m}–{end_h}:{end_m}"

    start_dt, end_dt = normalize_interval(дата, f"{start_h}:{start_m}", f"{end_h}:{end_m}")

    await state.update_data(
        date=дата,
        time=время,
        start=start_dt.isoformat(),
        end=end_dt.isoformat()
    )

    # Повторная попытка создания брони с новым временем
    data = await state.get_data()
    тип = data['booking_type']
    contact = data['contact']
    people = data['people']

    # === ИСПРАВЛЕНИЕ: Добавляем ID в строку пользователя ===
    пользователь_строка = f"{callback.from_user.full_name} (ID: {callback.from_user.id})"

    summary_text = f"{тип} | {people} чел | {contact} | {callback.from_user.id} (@{callback.from_user.username})"

    event_id = создать_бронь(
        тип=summary_text,
        пользователь=пользователь_строка,  # <-- Передаем строку с ID
        start=start_dt,
        end=end_dt
    )
    await state.update_data(event_id=event_id)

    key = next((k for k in CALENDAR_IDS if k in тип.lower()), "общая")

    await callback.message.answer(
        f"✅ <b>Проверьте бронь (новое время):</b>\n"
        f"<b>Тип:</b> {тип}\n"
        f"<b>Дата:</b> {дата}\n"
        f"<b>Время:</b> {время}\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>Людей:</b> {people}",
        reply_markup=build_confirm_keyboard(event_id, key),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "confirm_booking")
async def confirm_booking(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    # ⚡️ МГНОВЕННЫЙ ОТВЕТ: "Фиксирую..."
    await callback.answer("⏳ Фиксирую бронь...", show_alert=False)

    data = await state.get_data()
    if not data.get('event_id'):
        await callback.message.edit_text("⚠️ Данные устарели. Начните бронирование заново.")
        await state.clear()
        return

    # Уведомление админам (ЕДИНЫЙ СТИЛЬ)
    booking_info = (
        "📥 <b>НОВАЯ БРОНЬ (СТОЛ/КОМНАТА)</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Гость:</b> @{callback.from_user.username or callback.from_user.full_name}\n"
        f"🏷 <b>Тип:</b> {data['booking_type']}\n"
        f"🗓 <b>Дата:</b> {data['date']}\n"
        f"⏰ <b>Время:</b> {data['time']}\n"
        f"👥 <b>Людей:</b> {data['people']}\n"
        f"📞 <b>Контакт:</b> {data['contact']}"
    )

    try:
        await notify_admins(bot, booking_info)
    except Exception:
        pass

    await callback.message.edit_text(
        "✅ <b>Бронь успешно подтверждена!</b>\n\n"
        "Найти и отменить её можно в разделе <b>Мои Брони</b>.",
        reply_markup=keyboards.after_booking_keyboard,
        parse_mode="HTML"
    )
    await state.clear()