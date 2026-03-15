# ФАЙЛ: notifications.py

import logging
from aiogram import Bot

# === СПИСОК АДМИНОВ ===
ADMIN_IDS = [286027936, 1111340826, 6797588447, 209042305]

async def notify_admins(bot: Bot, text: str):
    """
    Отправляет сообщение всем админам из списка ADMIN_IDS.
    """
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            # Логируем ошибку, чтобы видеть её в консоли
            logging.error(f"⚠️ [NOTIFY ERROR] Не удалось отправить админу {admin_id}: {e}")