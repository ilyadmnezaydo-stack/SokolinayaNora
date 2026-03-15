from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

router = Router()
ADMINS =[286027936, 1111340826, 6797588447]

class SupportStates(StatesGroup):
    waiting_question = State()
    waiting_admin_answer = State()

# --- Главное меню поддержки для пользователя
def support_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Задать вопрос", callback_data="user_ask_question")]
        ]
    )

# --- Только по специальному слову или кнопке!
@router.message(F.text.lower().in_(["✍️ поддержка", "/support", "задать вопрос"]))
async def show_support_menu(message: Message):
    await message.answer(
        "Если у вас есть вопрос — нажмите кнопку ниже:",
        reply_markup=support_menu()
    )

# --- Кнопка пользователя "Задать вопрос"
@router.callback_query(F.data == "user_ask_question")
async def ask_question(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Напишите свой вопрос и отправьте его одним сообщением.")
    await state.set_state(SupportStates.waiting_question)
    await callback.answer()

# --- Пользователь пишет вопрос, после этого снова выводим кнопку меню!
@router.message(SupportStates.waiting_question)
async def handle_user_question(message: Message, bot: Bot, state: FSMContext):
    for admin_id in ADMINS:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="✉️ Ответить",
                    callback_data=f"admin_reply_{message.from_user.id}"
                )]
            ]
        )
        await bot.send_message(
            admin_id,
            f"❓ <b>Новый вопрос от пользователя!</b>\n"
            f"👤 <b>{message.from_user.full_name}</b> (@{message.from_user.username or '-'})\n"
            f"🆔 ID: <code>{message.from_user.id}</code>\n"
            f"💬 <b>Вопрос:</b>\n{message.text}",
            parse_mode="HTML",
            reply_markup=kb  # <-- КНОПКА ДЛЯ АДМИНА!!!
        )
    await message.answer(
        "Спасибо за вопрос! Мы скоро ответим вам.\n\nМожете задать ещё вопрос, если нужно:",
        reply_markup=support_menu()  # <-- КНОПКА ДЛЯ ПОЛЬЗОВАТЕЛЯ!!!
    )
    await state.clear()

# --- Админ жмёт "Ответить" — следующий текст уходит только этому юзеру!
@router.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_callback(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.replace("admin_reply_", ""))
    await state.update_data(reply_user_id=user_id)
    await callback.message.answer(
        f"✉️ Напишите ваш ответ пользователю (ID {user_id}). Первое ваше сообщение уйдёт ему в личку."
    )
    await state.set_state(SupportStates.waiting_admin_answer)
    await callback.answer()

# --- Первый ответ админа уходит выбранному юзеру
@router.message(SupportStates.waiting_admin_answer, F.from_user.id.in_(ADMINS))
async def send_admin_answer(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    user_id = data.get('reply_user_id')
    if not user_id:
        await message.answer("Ошибка: не выбран пользователь для ответа.")
        await state.clear()
        return
    try:
        await bot.send_message(
            user_id,
            f"👮‍♂️ <b>Админ ответил:</b>\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer("Ответ отправлен пользователю.")
    except Exception:
        await message.answer("❌ Не удалось отправить сообщение пользователю.")
    await state.clear()
