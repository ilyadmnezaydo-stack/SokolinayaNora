from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import socket

# === ВАЖНО: Увеличиваем тайм-аут ожидания ответа, чтобы избежать ранних разрывов ===
socket.setdefaulttimeout(60)

# --- Конфиги ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'  # путь к credentials

# --- Твои реальные ID календарей ---
CALENDAR_IDS = {
    "большая": "db2c9af3eb363d0b7b48c1bb5278812ac181b16c3a8de0aac983583c068d1537@group.calendar.google.com",
    "мягкая": "cf6725bef1922ca09566f56fa247daba54c19501bd4ac9e73ced7529b70bf3ca@group.calendar.google.com",
    "общая": "sokolinaya.nora@gmail.com",
}

# --- Авторизация ---
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('calendar', 'v3', credentials=credentials)
except Exception as e:
    print(f"❌ [CALENDAR API INIT ERROR] {e}")
    service = None


def _определить_календарь(тип: str) -> str:
    if not тип or not isinstance(тип, str):
        print(f"[DEBUG] Тип брони некорректен: {тип}, использую 'общая'")
        return CALENDAR_IDS["общая"]

    тип = тип.strip().lower()
    for ключ in CALENDAR_IDS:
        if ключ in тип:
            return CALENDAR_IDS[ключ]

    return CALENDAR_IDS["общая"]


def создать_бронь(тип: str, пользователь: str, start: datetime, end: datetime):
    if not service:
        print("[API ERROR] Сервис календаря не инициализирован")
        return None

    calendar_id = _определить_календарь(тип)
    print(f"[DEBUG] Создаю бронь в календаре: {calendar_id}...")

    event = {
        'summary': f'Бронь: {тип} от {пользователь}',
        'description': f'Забронировано через Telegram-бот\nuser_id={пользователь}',
        'start': {'dateTime': start.isoformat(), 'timeZone': 'Europe/Moscow'},
        'end': {'dateTime': end.isoformat(), 'timeZone': 'Europe/Moscow'}
    }

    try:
        # num_retries=5 заставит библиотеку повторить попытку 5 раз при разрыве сети
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute(num_retries=5)

        return created_event.get("id")
    except Exception as e:
        print(f"[ОШИБКА создания]: {e}")
        return None


def удалить_бронь(event_id: str, тип: str):
    """Удалить событие по event_id"""
    if not service: return False

    calendar_id = _определить_календарь(тип)
    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute(num_retries=5)  # Добавляем повторы
        return True
    except Exception as e:
        print(f"[ОШИБКА удаления]: {e}")
        return False


def есть_пересечение_брони(start: datetime, end: datetime, тип: str) -> bool:
    """Есть ли пересечение с другими бронями?"""
    if not service: return False

    calendar_id = _определить_календарь(тип)
    time_min = start.astimezone(timezone.utc).isoformat()
    time_max = end.astimezone(timezone.utc).isoformat()
    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute(num_retries=5)  # Добавляем повторы

        events = events_result.get('items', [])
        return bool(events)
    except Exception as e:
        print(f"[ОШИБКА поиска пересечений]: {e}")
        return False


def получить_пересекающиеся_брони(start: datetime, end: datetime, тип: str):
    """
    Возвращает список броней, пересекающихся с данным интервалом времени.
    """
    if not service: return []

    calendar_id = _определить_календарь(тип)
    time_min = start.astimezone(timezone.utc).isoformat()
    time_max = end.astimezone(timezone.utc).isoformat()
    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute(num_retries=5)  # Добавляем повторы

        events = events_result.get('items', [])
        result = []
        for event in events:
            ev_start = event['start'].get('dateTime') or event['start'].get('date')
            ev_end = event['end'].get('dateTime') or event['end'].get('date')
            try:
                ev_start_dt = datetime.fromisoformat(ev_start)
                ev_end_dt = datetime.fromisoformat(ev_end)
            except Exception:
                continue
            summary = event.get("summary", "")
            result.append({
                "start": ev_start_dt,
                "end": ev_end_dt,
                "summary": summary,
            })
        return result
    except Exception as e:
        print(f"[ОШИБКА получения списка пересечений]: {e}")
        return []


def найти_свободное_время(тип: str, start: datetime, end: datetime, шаг_минут=30, попыток=6):
    """Найти свободные окна для брони"""
    свободные_окна = []
    длительность = end - start
    попытка = 0
    while len(свободные_окна) < 3 and попытка < попыток:
        new_start = start + timedelta(minutes=шаг_минут * попытка)
        new_end = new_start + длительность
        if not есть_пересечение_брони(start=new_start, end=new_end, тип=тип):
            свободные_окна.append((new_start, new_end))
        попытка += 1
    return свободные_окна


# --- Тест ---
if __name__ == "__main__":
    try:
        print(f"Используемый сервис-аккаунт: {credentials.service_account_email}")
        print("Список календарей:")
        for ключ, календарь in CALENDAR_IDS.items():
            print(f"{ключ}: {календарь}")
    except Exception as e:
        print(f"Ошибка при тесте: {e}")

