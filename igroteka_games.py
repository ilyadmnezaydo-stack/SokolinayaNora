import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS_FILE = "credentials.json"

creds = None
client = None
try:
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
except Exception as e:  # ключа может не быть — бот должен запускаться и без Google
    print(f"❌ [IGROTEKA SHEETS INIT ERROR] {e}")


def _ensure_client():
    """Ленивая инициализация: если credentials.json появился позже, подхватим его."""
    global creds, client
    if client is None:
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
    return client

def получить_настолки():
    client = _ensure_client()
    print("🔐 Подключаемся к Google Таблице...")
    лист = client.open_by_key("1eHiZNAYHqkazm0sOnW9uEZqwDLLgTp82qJjNXpF7gKE").worksheet("Лист1")
    print("✅ Таблица открыта!")
    данные = лист.get_all_values()

    игры = []
    for row in данные[1:]:  # Пропускаем заголовок
        if len(row) < 8 or not row[1].strip():
            continue

        игра = {
            "название": row[1].strip(),
            "полка": row[2].strip(),
            "тип": row[3].strip(),
            "подтип": row[4].strip(),
            "дата": row[5].strip(),
            "время": row[6].strip(),
            "возраст": row[7].strip()
        }
        игры.append(игра)

    return игры

def получить_жанры_и_игры():
    client = _ensure_client()
    лист = client.open_by_key("1eHiZNAYHqkazm0sOnW9uEZqwDLLgTp82qJjNXpF7gKE").worksheet("Лист1")
    данные = лист.get_all_values()

    жанры = {}

    for row in данные[1:]:  # Пропускаем заголовок
        if len(row) < 8 or not row[1].strip():
            continue

        игра = {
            "название": row[1].strip(),
            "полка": row[2].strip(),
            "тип": row[3].strip(),
            "подтип": row[4].strip(),
            "дата": row[5].strip(),
            "время": row[6].strip(),
            "возраст": row[7].strip()
        }

        ключ = f"{игра['тип']} / {игра['подтип']}"
        жанры.setdefault(ключ, []).append(игра)

    return жанры