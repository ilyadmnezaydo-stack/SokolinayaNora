from aiogram import Router, F, types, Bot
from aiogram.types import CallbackQuery, Message, ChatPermissions
from aiogram.filters import Command
from datetime import timedelta, datetime

from middlewares.advanced_antispam import user_warnings

admin_unblock_router = Router()
ADMIN_IDS = [1111340826]  # Укажи всех админов

# 🔓 Обработка кнопки "Размутить"
@admin_unblock_router.callback_query(F.data.startswith("unmute_"))
async def handle_unmute(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Недоступно.", show_alert=True)
        return

    try:
        _, chat_id, user_id = callback.data.split("_")
        chat_id = int(chat_id)
        user_id = int(user_id)

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=True)
        )
        await callback.message.edit_text("✅ Пользователь успешно размучен.")
    except Exception as e:
        await callback.message.edit_text(f"❌ Не удалось снять мут: {e}")

# 🚫 Обработка кнопки "Разбанить"
@admin_unblock_router.callback_query(F.data.startswith("unban_"))
async def handle_unban(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Недоступно.", show_alert=True)
        return

    try:
        _, chat_id, user_id = callback.data.split("_")
        chat_id = int(chat_id)
        user_id = int(user_id)

        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)

        # Обнуляем предупреждения
        user_warnings.get(chat_id, {}).pop(user_id, None)

        await callback.message.edit_text("✅ Пользователь успешно разбанен и предупреждения обнулены.")
    except Exception as e:
        await callback.message.edit_text(f"❌ Не удалось разбанить: {e}")

# 🔇 Команда /mute [в минутах]
@admin_unblock_router.message(Command("mute"))
async def cmd_mute_user(message: Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав.")
        return

    if not message.reply_to_message:
        await message.answer("🔁 Ответьте на сообщение пользователя, чтобы выдать мут.")
        return

    try:
        args = message.text.split()
        duration = int(args[1]) if len(args) > 1 else 10
        until = datetime.now() + timedelta(minutes=duration)

        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=message.reply_to_message.from_user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )

        await message.answer(f"🔇 Пользователь замучен на {duration} минут.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при муте: {e}")

# 🔨 Команда /ban
@admin_unblock_router.message(Command("ban"))
async def cmd_ban_user(message: Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав.")
        return

    if not message.reply_to_message:
        await message.answer("🔁 Ответьте на сообщение пользователя, чтобы забанить.")
        return

    try:
        await bot.ban_chat_member(
            chat_id=message.chat.id,
            user_id=message.reply_to_message.from_user.id
        )

        # Обнуляем предупреждения
        user_warnings.get(message.chat.id, {}).pop(message.reply_to_message.from_user.id, None)

        await message.answer("🚫 Пользователь забанен и предупреждения удалены.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при бане: {e}")
