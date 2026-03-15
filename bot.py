import asyncio
import logging
import ssl
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

# Импорты роутеров
from admin_panel import admin_router
from create_igroteka import router as igroteka_create_router
from fsm_booking_combined import router as booking_router
from handlers import router as full_router
from handlers_admin_unblocks import admin_unblock_router
from handlers_appeals import appeal_router
from handlers_games import router as games_router
from handlers_guest import guest_router
from handlers_questions import router as support_router
from handlers_reviews import router as reviews_router
from my_bookings import router as bookings_router

from middlewares.advanced_antispam import AdvancedAntiSpamMiddleware
from sync_service import run_sync_cycle

BOT_TOKEN = "8340140999:AAEnBJevc2d1snYtvncV_35y5hAv-wiSsRA"

# Фикс SSL
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

logging.basicConfig(level=logging.INFO)

async def scheduled_sync():

    logging.info("⏳ Планировщик синхронизации запущен.")
    while True:
        try:
            await run_sync_cycle()
            # Успешно -> ждем 5 минут
            await asyncio.sleep(600)
        except Exception as e:
            logging.error(f"[SCHEDULER ERROR] {e}")
            await asyncio.sleep(600)

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(AdvancedAntiSpamMiddleware())

    main_router = Router()
    main_router.include_router(admin_router)
    main_router.include_router(bookings_router)
    main_router.include_router(booking_router)
    main_router.include_router(igroteka_create_router)
    main_router.include_router(admin_unblock_router)
    main_router.include_router(reviews_router)
    main_router.include_router(games_router)
    main_router.include_router(appeal_router)
    main_router.include_router(support_router)
    main_router.include_router(guest_router)
    main_router.include_router(full_router)

    dp.include_router(main_router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="admin", description="Админка"),
    ])

    # Запускаем планировщик в фоне
    asyncio.create_task(scheduled_sync())

    logging.info("🤖 Бот запущен! Начинаю polling…")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())