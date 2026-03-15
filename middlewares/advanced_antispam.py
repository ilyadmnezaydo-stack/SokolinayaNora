import re
import asyncio
from aiogram import Bot
from aiogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from typing import Callable, Dict, Awaitable
from datetime import datetime, timedelta

# Запрещённые слова
RAW_BAD_WORDS = {"лох", "идиот", "дурак", "мразь", "тупица", "чурка"}

def build_fuzzy_pattern(word: str) -> re.Pattern:
    pattern = r"[\W_]*".join(list(word))
    return re.compile(pattern, re.IGNORECASE)

BAD_PATTERNS = [build_fuzzy_pattern(word) for word in RAW_BAD_WORDS]

# Хранилище предупреждений
user_warnings: dict[int, dict[int, list[datetime]]] = {}
lock = asyncio.Lock()

# Админы
ADMIN_IDS = [1111340826]


class AdvancedAntiSpamMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict], Awaitable],
        event,
        data: Dict
    ) -> Awaitable:

        message: Message = event
        bot: Bot = data["bot"]

        if message.chat.type == "private" or not message.text or message.text.startswith("/"):
            return await handler(event, data)

        text = message.text.lower()
        if not any(p.search(text) for p in BAD_PATTERNS):
            return await handler(event, data)

        async with lock:
            now = datetime.now()
            chat_id = message.chat.id
            user_id = message.from_user.id
            full_name = message.from_user.full_name
            username = message.from_user.username or "нет username"
            chat_title = message.chat.title or "Без имени"

            # Обновление истории предупреждений
            user_data = user_warnings.setdefault(chat_id, {}).setdefault(user_id, [])
            user_data = [t for t in user_data if now - t < timedelta(hours=1)]
            user_data.append(now)
            user_warnings[chat_id][user_id] = user_data

            warn_count = len(user_data)

            # Уведомление
            alert_text = (
                f"🚨 <b>Нарушение антиспама!</b>\n"
                f"👤 Пользователь: {full_name} (@{username})\n"
                f"💬 Сообщение: {message.text}\n"
                f"📍 Чат: {chat_title}\n"
                f"🔢 Предупреждений за час: {warn_count}"
            )

            if warn_count >= 3:
                try:
                    await bot.ban_chat_member(chat_id, user_id)
                    await message.answer(f"🚫 {full_name} был забанен за грубость.")
                    for admin_id in ADMIN_IDS:
                        await bot.send_message(
                            admin_id,
                            alert_text.replace("🔢", "🔨 Пользователь забанен."),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🔓 Разбанить", callback_data=f"unban_{chat_id}_{user_id}")]
                            ])
                        )
                except Exception as e:
                    print(f"[ERROR] Ban failed: {e}")
                return

            # Мут на 10 минут
            try:
                until = now + timedelta(minutes=10)
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                await message.answer(f"⚠️ {full_name} получил мут на 10 минут за ненормативную лексику.")
                for admin_id in ADMIN_IDS:
                    await bot.send_message(
                        admin_id,
                        alert_text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔓 Размутить", callback_data=f"unmute_{chat_id}_{user_id}")]
                        ])
                    )
            except Exception as e:
                print(f"[ERROR] Mute failed: {e}")
            return
