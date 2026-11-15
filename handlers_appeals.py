from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.markdown import hbold

ADMIN_IDS = [286027936, 1111340826, 6797588447]

appeal_router = Router()

@appeal_router.callback_query(F.data == "appeal_ban")
async def handle_appeal(callback: CallbackQuery):
    user = callback.from_user

    await callback.message.edit_text("📨 Ваш запрос на обжалование отправлен администратору.")

    text = (
        f"🚨 <b>Запрос на обжалование</b>\n\n"
        f"👤 Пользователь: {hbold(user.full_name)} (@{user.username or 'нет username'})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📅 Время: {callback.message.date.strftime('%Y-%m-%d %H:%M')}\n"
        f"💬 Повод: пользователь нажал кнопку обжалования после блокировки."
    )

    for admin_id in ADMIN_IDS:
        try:
            await callback.bot.send_message(admin_id, text)
        except Exception as e:
            print(f"[ERROR] Не удалось отправить апелляцию админу {admin_id}: {e}")
