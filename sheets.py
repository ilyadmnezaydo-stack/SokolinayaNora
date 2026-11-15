import re
import gspread
import asyncio
import functools
from google.oauth2.service_account import Credentials
from datetime import datetime
from googleapiclient.discovery import build

# --- НАСТРОЙКИ ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS_FILE = "credentials.json"
SPREADSHEET_ID = "1RiEIRl8QPVEyRKtpQKyGkE3yTKbTeEja-wyA8PFWVRk"

# Цвета
BLUE = {"red": 0.678, "green": 0.847, "blue": 0.902}  # Полная посадка
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}  # Есть места

print("[SHEETS_API] Инициализация...")


# --- АВТОРИЗАЦИЯ ---
def get_creds():
    return Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)


# 1. gspread client (для чтения/записи данных)
creds = get_creds()
client = gspread.authorize(creds)

try:
    # Основной лист с расписанием
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Игротеки_Антикафе")
    # Лист для гостевых данных (если нужен)
    sheet_igroteka = client.open_by_key(SPREADSHEET_ID).worksheet("Данные_от_бота_гостевые")
    print("[SHEETS_API] Таблицы успешно загружены.")
except Exception as e:
    print(f"[CRITICAL ERROR] Не удалось открыть таблицу: {e}")


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_service():
    """Создает raw-сервис googleapiclient для быстрой перекраски"""
    return build('sheets', 'v4', credentials=creds)


async def run_blocking(func, *args, **kwargs):
    """Запускает синхронные функции gspread в отдельном потоке"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


def _normalize_name(name):
    """Убирает @, пробелы и приводит к нижнему регистру для сравнения"""
    if not name: return ""
    return str(name).lower().replace("@", "").strip()


def extract_limit_from_info(info: str) -> int:
    """Извлекает лимит из строки формата '18.00 4 чел'"""
    if not info: return 0
    match = re.search(r'\b(\d{1,2})\s*чел', str(info).lower())
    return int(match.group(1)) if match else 0


def _get_column_index(data, date_str, game_name):
    """Ищет индекс колонки (0-based)"""
    target_date = date_str.replace(".", "").strip()
    target_game = game_name.strip().lower()

    try:
        if len(data) < 3: return None
        row_dates = data[1]  # Индекс 1 (вторая строка)
        row_games = data[2]  # Индекс 2 (третья строка)

        for idx, (d_val, g_val) in enumerate(zip(row_dates, row_games, strict=False)):
            if d_val.strip().replace(".", "") == target_date:
                if g_val.strip().lower() == target_game:
                    return idx
    except IndexError:
        pass
    return None


def prepare_color_request(sheet_id, row_idx, col_idx, color):
    """Формирует JSON для одного запроса покраски"""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_idx,
                "endRowIndex": row_idx + 1,
                "startColumnIndex": col_idx,
                "endColumnIndex": col_idx + 1
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": color
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    }


# --- ФУНКЦИИ ЛОГИКИ (СИНХРОННЫЕ) ---

def перекрасить_игротеку_по_содержимому(дата: str, игра: str):
    """
    Красит ячейку с названием игры в зависимости от заполненности.
    """
    try:
        # Используем текущий sheet для чтения, но raw service для записи (быстрее)
        data = sheet.get_all_values()
        col_idx = _get_column_index(data, дата, игра)

        if col_idx is None:
            return

        # Лимит (строка 4, индекс 3)
        info_cell = data[3][col_idx]
        limit = extract_limit_from_info(info_cell)

        # Считаем занятые места (строки 6-12, индексы 5-11)
        taken = 0
        for r in range(5, 12):
            if r < len(data) and col_idx < len(data[r]):
                val = data[r][col_idx].strip().lower()
                if val and val != "свободно":
                    taken += 1

        # Определяем цвет
        color = BLUE if (limit > 0 and taken >= limit) else WHITE

        # Отправляем запрос
        service = get_service()
        req = prepare_color_request(sheet.id, 2, col_idx, color)  # Красим 3-ю строку (название)

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': [req]}
        ).execute()
        # print(f"[COLOR] Перекрашено: {игра}")

    except Exception as e:
        print(f"[COLOR ERROR] Ошибка перекраски {игра}: {e}")


def записать_участника_sync(дата: str, игра: str, имя: str):
    """
    Пытается записать участника.
    Возвращает: 'OK', 'ALREADY', 'FULL', 'ERROR'
    """
    data = sheet.get_all_values()
    col_index = _get_column_index(data, дата, игра)

    if col_index is None:
        return 'ERROR'

    # 1. ПРОВЕРКА НА ДУБЛИКАТ
    target_name = _normalize_name(имя)
    for i in range(5, 12):
        if i < len(data) and col_index < len(data[i]):
            existing_name = _normalize_name(data[i][col_index])
            if existing_name == target_name and existing_name not in ["свободно", ""]:
                return 'ALREADY'  # Уже записан

    # 2. ПОИСК МЕСТА
    for i in range(5, 12):
        # Проверка границ
        if i >= len(data): break

        val = ""
        if col_index < len(data[i]):
            val = data[i][col_index].strip().lower()

        if val == "свободно" or val == "":
            # Пишем
            sheet.update_cell(i + 1, col_index + 1, имя)
            перекрасить_игротеку_по_содержимому(дата, игра)
            return 'OK'

    return 'FULL'  # Нет мест


def удалить_участника_sync(дата: str, игра: str, имя: str):
    """
    Удаляет участника и перекрашивает слот в "свободно"
    """
    data = sheet.get_all_values()
    col_index = _get_column_index(data, дата, игра)

    if col_index is None:
        return False

    имя_l = _normalize_name(имя)

    for i in range(5, 12):
        if i < len(data) and col_index < len(data[i]):
            cell_val = _normalize_name(data[i][col_index])
            # Ищем совпадение имени (частичное или полное)
            if имя_l in cell_val and cell_val not in ["свободно", ""]:
                sheet.update_cell(i + 1, col_index + 1, "свободно")
                перекрасить_игротеку_по_содержимому(дата, игра)
                return True
    return False


def получить_актуальные_игротеки_sync():
    """
    Возвращает список словарей с доступными играми
    """
    data = sheet.get_all_values()
    result = []
    now = datetime.now()

    if len(data) < 4: return []

    # Проходим по колонкам
    width = len(data[1])
    for col in range(1, width):
        try:
            дата = data[1][col].strip()
            название_игры = data[2][col].strip()
            инфо = data[3][col].strip()
            хост = data[4][col].strip()

            if not дата or not название_игры: continue
            if название_игры.lower() in ["", "_", "берсерк"]: continue

            # Парсинг даты
            dt_full = дата.zfill(5)
            # Пытаемся понять год (текущий или следующий)
            # Для упрощения считаем текущий год
            try:
                date_str = f"{dt_full}.{now.year}"
                _dt_obj = datetime.strptime(date_str, "%d.%m.%Y")
                # Логика пропуска прошедших дат (если дата была вчера - скрываем)
                # if dt_obj.date() < now.date(): continue
            except:
                pass  # Если дата кривая, все равно пытаемся показать

            лимит = extract_limit_from_info(инфо)
            if лимит == 0: continue

            # Считаем места
            участники = []
            for row in range(5, 12):
                if row < len(data) and col < len(data[row]):
                    val = data[row][col].strip()
                    if val and val.lower() != "свободно":
                        участники.append(val)

            свободно = max(лимит - len(участники), 0)

            result.append({
                "дата": дата,
                "игра": название_игры,
                "инфо": инфо,
                "хост": хост,
                "свободно": свободно,
                "лимит": лимит,
                "участники": участники,
                "col_index": col
            })
        except Exception:
            continue

    return result


# --- АСИНХРОННЫЕ ОБЕРТКИ (ВЫЗЫВАТЬ ИЗ БОТА) ---

async def записать_участника(дата: str, игра: str, имя: str):
    """Возвращает 'OK', 'ALREADY', 'FULL', 'ERROR'"""
    return await run_blocking(записать_участника_sync, дата, игра, имя)


async def удалить_участника(дата: str, игра: str, имя: str):
    """Возвращает True если удалил, False если не нашел"""
    return await run_blocking(удалить_участника_sync, дата, игра, имя)


async def получить_актуальные_игротеки():
    """Возвращает список игр"""
    return await run_blocking(получить_актуальные_игротеки_sync)


# --- ПРОЧИЕ ФУНКЦИИ ---
def декодировать_дату_время(строка):
    try:
        строка = строка.strip()
        if строка.isdigit() and len(строка) == 8:
            строка = f"{строка[:2]}.{строка[2:4]} {строка[4:6]}:{строка[6:]}"
        if re.match(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", строка):
            dt = datetime.strptime(строка, "%d.%m.%Y %H:%M")
        elif re.match(r"\d{2}\.\d{2} \d{2}:\d{2}", строка):
            dt = datetime.strptime(строка, "%d.%m %H:%M")
            dt = dt.replace(year=datetime.now().year)
        else:
            return строка
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return строка


def добавить_игротеку(игра, контакт, людей, дата_время, хост):
    # Эта функция работает с sheet_igroteka (гостевой лист)
    # Если она используется редко, можно оставить синхронной, или тоже обернуть
    try:
        row = [игра, контакт, людей, дата_время, хост]
        sheet_igroteka.append_row(row, table_range="A1")
    except Exception as e:
        print(f"Ошибка добавления игротеки: {e}")