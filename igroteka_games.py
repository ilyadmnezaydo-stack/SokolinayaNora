import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS_FILE = "credentials.json"

creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
client = gspread.authorize(creds)

def получить_настолки():
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