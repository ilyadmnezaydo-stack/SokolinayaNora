from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from keyboards import review_menu, main_menu
import aiohttp
from bs4 import BeautifulSoup

router = Router()

# URLы для Яндекс карт
YANDEX_MAPS_URL = "https://yandex.ru/maps/213/moscow/?ll=37.737082%2C55.783465&mode=poi&poi%5Bpoint%5D=37.737598%2C55.783175&poi%5Buri%5D=ymapsbm1%3A%2F%2Forg%3Foid%3D204283434707&z=18.47"

async def get_yandex_reviews(count=3):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://yandex.ru/maps/org/204283434707/reviews/?ll=37.737082,55.783465&z=18.47",
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resp:
                html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        reviews = []
        for block in soup.find_all("div", class_="business-review-view__body")[:count]:
            author = block.find("span", class_="business-review-view__author").get_text(strip=True)
            text = block.find("span", class_="business-review-view__text").get_text(strip=True)
            rating = block.find("span", class_="business-rating-badge-view__rating")
            rating = rating.get_text(strip=True) if rating else "Без оценки"
            reviews.append(f"⭐️ {rating} — <b>{author}</b>\n{text}")
        return reviews
    except Exception as e:
        print("Ошибка парсинга отзывов Яндекс:", e)
        return []

@router.message(F.text.lower() == "отзывы")
async def show_review_menu(message: Message):
    await message.answer(
        "<b>Наши отзывы</b>",
        reply_markup=review_menu,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "show_live_reviews")
async def show_live_reviews(callback: CallbackQuery):
    reviews = await get_yandex_reviews()
    if reviews:
        text = "<b>Свежие отзывы с Яндекс.Карт:</b>\n\n"
        text += "\n\n".join(reviews)
        text += f"\n\n<i>Все отзывы можно посмотреть по <a href='{YANDEX_MAPS_URL}'>ссылке на Яндекс.Карты</a>.</i>"
    else:
        text = (
            "Не удалось получить отзывы с Яндекс.Карт.\n"
            f"Попробуйте позже или посмотрите их <a href='{YANDEX_MAPS_URL}'>на странице Яндекса</a>."
        )
    await callback.message.edit_text(text, reply_markup=review_menu)
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_menu)
    await callback.answer()
