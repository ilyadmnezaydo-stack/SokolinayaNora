# utils.py

from aiogram.types import Message

async def send_long_text(message: Message, text: str):
    """Делит длинный текст и отправляет частями (лимит Telegram — 4096 символов)."""
    for i in range(0, len(text), 4096):
        await message.answer(text[i:i+4096])
