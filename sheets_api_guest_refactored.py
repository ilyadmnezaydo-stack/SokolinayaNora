import re
from html import escape
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from urllib.parse import quote

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS_FILE = "credentials.json"

_client = None
_sheet_guest_igroteka = None

# === ЧАСОВОЙ ПОЯС (МОСКВА UTC+3) ===
MSK_TZ = timezone(timedelta(hours=3))


def get_client():
    global _client
    if _client is None:
        try:
            creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
            _client = gspread.authorize(creds)
        except (ConnectionResetError, ConnectionError) as e:
            print(f"[ОШИБКА подключения к Google]: {e}")
            return None
        except Exception as e:
            print(f"[ОШИБКА авторизации]: {e}")
            return None
    return _client


def get_sheet_guest_igroteka():
    global _sheet_guest_igroteka
    if _sheet_guest_igroteka is None:
        client = get_client()
        if client:
            try:
                _sheet_guest_igroteka = client.open_by_key("1RiEIRl8QPVEyRKtpQKyGkE3yTKbTeEja-wyA8PFWVRk").worksheet(
                    "Игротеки_Гостевые")
                print("[SHEETS_API ЗАГРУЗИЛСЯ]")
            except Exception as e:
                print(f"[ОШИБКА открытия листа Игротеки_Гостевые]: {e}")
                return None
    return _sheet_guest_igroteka


def extract_limit_from_info(info: str) -> int:
    match = re.search(r'\b(\d{1,2})\s*чел', info.lower())
    return int(match.group(1)) if match else 0


def получить_гостевые_игротеки_данные():
    sheet = get_sheet_guest_igroteka()
    if not sheet:
        print("[ОШИБКА] Не удалось получить доступ к листу Игротеки_Гостевые")
        return []

    try:
        data = sheet.get_all_values()
    except Exception as e:
        print(f"[ОШИБКА чтения данных]: {e}")
        return []

    # Текущее время по МОСКВЕ
    now_msk = datetime.now(MSK_TZ)
    result = []

    if len(data) < 6:
        return []

    дата_строка = data[1]
    игра_строка = data[2]
    время_строка = data[3]
    хост_строка = data[4]
    участники_строки = data[5:13]

    for col in range(1, len(игра_строка)):
        if col >= len(дата_строка) or col >= len(время_строка) or col >= len(хост_строка):
            continue

        игра = игра_строка[col].strip()
        дата = дата_строка[col].strip()
        инфо = время_строка[col].strip()
        хост = хост_строка[col].strip()

        if not игра or not дата or not инфо or not хост or хост.lower() == "свободно":
            continue

        # Очистка формата даты (убираем лишнее, если ввели 2106 вместо 21.06)
        clean_date = дата
        if "." not in дата and len(''.join(filter(str.isdigit, дата))) == 4:
            nums = ''.join(filter(str.isdigit, дата))
            clean_date = f"{nums[:2]}.{nums[2:]}"

        # Извлечение времени
        match = re.search(r"\d{1,2}[:.]\d{2}", инфо)
        время = match.group().replace(".", ":") if match else "00:00"

        full_date_str = f"{clean_date} {время}"

        # === ФИЛЬТРАЦИЯ ПО ДАТЕ (С УЧЕТОМ MSK) ===
        try:
            # 1. Пробуем формат с годом: 25.12.2025 18:00
            try:
                event_dt = datetime.strptime(full_date_str, "%d.%m.%Y %H:%M")
            except ValueError:
                # 2. Пробуем формат без года: 25.12 18:00
                event_dt = datetime.strptime(full_date_str, "%d.%m %H:%M")

                # Умное определение года
                year = now_msk.year
                if event_dt.month - now_msk.month > 6:
                    year -= 1  # Это было в прошлом году (сейчас Янв, игра в Дек)
                elif now_msk.month - event_dt.month > 6:
                    year += 1  # Это будет в следующем году (сейчас Дек, игра в Янв)

                event_dt = event_dt.replace(year=year)

            # Присваиваем таймзону Москвы для корректного сравнения
            event_dt = event_dt.replace(tzinfo=MSK_TZ)

            # Проверка: если игра была раньше чем (сейчас - 30 минут), скрываем
            if event_dt < now_msk - timedelta(minutes=30):
                continue

        except Exception as e:
            print(f"[ОШИБКА даты]: {full_date_str} -> {e}")
            continue
        # ========================================

        лимит = extract_limit_from_info(инфо)
        участники = []
        for row in участники_строки:
            if col < len(row):
                val = row[col].strip()
                if val and val.lower() != "свободно":
                    участники.append(val)

        свободно = max(лимит - len(участники), 0)

        result.append({
            "дата": clean_date,
            "игра": игра,
            "инфо": инфо,
            "дата_время": event_dt.strftime("%d.%m.%Y %H:%M"),
            "хост": хост,
            "свободно": свободно,
            "лимит": лимит,
            "участники": участники,
            "col_index": col
        })

    return result


def есть_места_в_гостевой(дата, игра, время):
    sheet = get_sheet_guest_igroteka()
    if not sheet: return False

    try:
        data = sheet.get_all_values()
    except Exception:
        return False

    if len(data) < 6: return False

    for col in range(1, len(data[1])):
        if col >= len(data[2]) or col >= len(data[3]): continue

        if (
                data[1][col].strip() == дата
                and data[2][col].strip().lower() == игра.lower()
                and время in data[3][col]
        ):
            свободно = 0
            for row in data[5:13]:
                if col < len(row):
                    val = row[col].strip()
                    if val.lower() == "свободно":
                        свободно += 1
            return свободно > 0
    return False


def записать_участника_гостевые(дата: str, игра: str, время: str, имя: str):
    sheet = get_sheet_guest_igroteka()
    if not sheet: return False

    try:
        data = sheet.get_all_values()
    except Exception:
        return False

    col_index = None
    for col in range(1, len(data[1])):
        if col >= len(data[2]) or col >= len(data[3]): continue

        дата_столбца = data[1][col].strip()
        игра_столбца = data[2][col].strip().lower()
        инфо_столбца = data[3][col].strip()

        if дата_столбца == дата and игра_столбца == игра.lower():
            if время in инфо_столбца:
                col_index = col + 1
                break

    if not col_index:
        return False

    for i in range(5, len(data)):
        if col_index - 1 < len(data[i]) and data[i][col_index - 1].strip().lower() == "свободно":
            try:
                sheet.update_cell(i + 1, col_index, имя)
                return True
            except Exception as e:
                print(f"[ОШИБКА записи]: {e}")
                return False

    return False


def удалить_участника_гостевые(дата: str, игра: str, время: str, имя: str):
    sheet = get_sheet_guest_igroteka()
    if not sheet: return False

    try:
        data = sheet.get_all_values()
    except Exception:
        return False

    for col in range(1, len(data[1])):
        if col >= len(data[2]) or col >= len(data[3]): continue

        дата_столбца = data[1][col].strip()
        игра_столбца = data[2][col].strip().lower()
        инфо_столбца = data[3][col].strip()

        if дата_столбца == дата and игра_столбца == игра.lower() and время in инфо_столбца:
            for i in range(5, 13):
                if i < len(data) and col < len(data[i]):
                    val = data[i][col].strip().lower()
                    if имя.lower().replace("@", "") in val.replace("@", ""):
                        try:
                            sheet.update_cell(i + 1, col + 1, "свободно")
                            return True
                        except Exception as e:
                            print(f"[ОШИБКА удаления]: {e}")
                            return False
    return False


async def получить_гостевые_игротеки(message: Message):
    result = получить_гостевые_игротеки_данные()

    if not result:
        await message.answer("😔 Сейчас нет активных гостевых игротек.")
        return

    for игра in result:
        участники_str = "\n".join([f"• {escape(str(u))}" for u in игра['участники']]) if игра[
            'участники'] else "Пока никто не записан"
        дата = игра['дата']
        игра_name = игра['игра']

        match = re.search(r"\d{1,2}:\d{2}", игра['инфо'])
        время = match.group() if match else "00:00"
        игра_code = quote(игра_name)[:32]

        кнопка = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text=f"✅ Записаться на {игра_name}",
                    callback_data=f"join_guest_{дата.replace('.', '')}_{время.replace(':', '')}_{игра_code}"
                )
            ]]
        )

        текст = (
            f"🎯 <b>{игра_name}</b>\n"
            f"📅 Дата: <b>{дата}</b>\n"
            f"🕒 Время: <b>{игра['инфо']}</b>\n"
            f"👤 Хост: {игра['хост']}\n"
            f"🪑 Свободных мест: <b>{игра['свободно']}</b>\n\n"
            f"🙋‍♂️ <b>Участники:</b>\n{участники_str}"
        )

        await message.answer(text=текст, reply_markup=кнопка, parse_mode="HTML")



# --- ПЕРЕКРАСКА ГОСТЕВОГО ЛИСТА ---
GUEST_SPREADSHEET_ID = "1RiEIRl8QPVEyRKtpQKyGkE3yTKbTeEja-wyA8PFWVRk"
BLUE = {"red": 0.678, "green": 0.847, "blue": 0.902}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def _guest_service():
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)


def перекрасить_гостевую_игротеку(дата: str, игра: str, время: str = "") -> None:
    """Красит название гостевой игры: синий, если мест нет, белый, если есть."""
    try:
        sheet = get_sheet_guest_igroteka()
        if not sheet:
            return
        data = sheet.get_all_values()
        if len(data) < 4:
            return
        col_idx = None
        width = max(len(data[1]), len(data[2]), len(data[3]))
        for col in range(1, width):
            if col >= len(data[1]) or col >= len(data[2]) or col >= len(data[3]):
                continue
            if (data[1][col].strip() == дата
                    and data[2][col].strip().lower() == игра.lower()
                    and (not время or время in data[3][col])):
                col_idx = col
                break
        if col_idx is None:
            return
        limit = extract_limit_from_info(data[3][col_idx])
        taken = 0
        for r in range(5, 13):
            if r < len(data) and col_idx < len(data[r]):
                v = data[r][col_idx].strip().lower()
                if v and v != "свободно":
                    taken += 1
        color = BLUE if (limit > 0 and taken >= limit) else WHITE
        body = {"requests": [{
            "repeatCell": {
                "range": {"sheetId": sheet.id, "startRowIndex": 2, "endRowIndex": 3,
                          "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        }]}
        _guest_service().spreadsheets().batchUpdate(
            spreadsheetId=GUEST_SPREADSHEET_ID, body=body).execute()
    except Exception as e:
        print(f"[ГОСТЕВАЯ ПЕРЕКРАСКА] Ошибка: {e}")
