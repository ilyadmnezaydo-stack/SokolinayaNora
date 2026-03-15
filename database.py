# ФАЙЛ: database.py

import sqlite3
from datetime import datetime, timedelta, timezone

DB_NAME = "igroteka.db"


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_type TEXT DEFAULT 'guest',
                game_name TEXT,
                game_date TEXT,
                game_time TEXT,
                host_name TEXT,
                host_contact TEXT,
                limit_count INTEGER,
                participants TEXT DEFAULT ''
            )
        """)
        try:
            cursor.execute("ALTER TABLE games ADD COLUMN game_type TEXT DEFAULT 'guest'")
        except sqlite3.OperationalError:
            pass
        conn.commit()


# --- ФУНКЦИИ ДЛЯ СИНХРОНИЗАЦИИ ---

def clear_official_games():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM games WHERE game_type = 'official'")
        conn.commit()


def add_game_db(game_type, game, date_str, time_str, host, contact, limit, participants_list=None):
    if participants_list is None:
        participants_list = []
    parts_str = ",".join(participants_list)
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO games (game_type, game_name, game_date, game_time, host_name, host_contact, limit_count, participants)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_type, game, date_str, time_str, host, contact, limit, parts_str))
        return cursor.lastrowid


# --- ФУНКЦИИ ЧТЕНИЯ И ЗАПИСИ (С АВТО-ОЧИСТКОЙ) ---

def get_all_games():
    """
    Возвращает список актуальных игр.
    УДАЛЯЕТ из базы игры, которые уже прошли.
    """
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM games")
        rows = cursor.fetchall()

    games = []
    ids_to_delete = []  # Список ID для удаления

    # Московское время
    msk_offset = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_offset)
    today_date = now_msk.date()

    for row in rows:
        game_date_str = row['game_date']
        game_time_str = row['game_time']

        is_expired = False

        try:
            # 1. Парсим дату
            g_date = datetime.strptime(game_date_str, "%d.%m.%Y").date()

            # 2. Если дата в прошлом (вчера и ранее) -> УДАЛЯЕМ
            if g_date < today_date:
                is_expired = True

            # 3. Если дата сегодня -> Проверяем время
            elif g_date == today_date:
                # Пытаемся вытащить время "19:00" из строки "19:00 (коммент)"
                import re
                time_match = re.search(r'\d{1,2}:\d{2}', game_time_str)
                if time_match:
                    g_time = datetime.strptime(time_match.group(), "%H:%M").time()
                    g_dt = datetime.combine(g_date, g_time).replace(tzinfo=msk_offset)

                    # Если игра началась более 3 часов назад -> Считаем завершенной и скрываем
                    # (но не удаляем сразу, чтобы можно было посмотреть участников, если надо.
                    # Но для чистоты списка лучше скрыть).
                    if now_msk > g_dt + timedelta(hours=3):
                        # Можно просто скрыть (continue), а можно удалить.
                        # Давайте удалять, чтобы база не пухла.
                        is_expired = True

        except ValueError:
            # Если формат даты битый, удаляем от греха подальше
            # print(f"Неверный формат даты: {game_date_str}, удаляю...")
            is_expired = True

        if is_expired:
            ids_to_delete.append(row['id'])
            continue

        # Если игра актуальна, добавляем в список
        parts_str = row['participants']
        parts = parts_str.split(",") if parts_str else []
        parts = [p.strip() for p in parts if p.strip()]

        games.append({
            "id": row['id'],
            "col_index": row['id'],
            "type": row['game_type'],
            "игра": row['game_name'],
            "дата": row['game_date'],
            "время": row['game_time'],
            "time_str": row['game_time'],
            "хост": row['host_name'],
            "контакт": row['host_contact'],
            "лимит": row['limit_count'],
            "участники": parts
        })

    # === ФИЗИЧЕСКОЕ УДАЛЕНИЕ СТАРЫХ ИГР ===
    if ids_to_delete:
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                # Удаляем пачкой
                placeholders = ','.join('?' for _ in ids_to_delete)
                cursor.execute(f"DELETE FROM games WHERE id IN ({placeholders})", ids_to_delete)
                conn.commit()
            print(f"🧹 [DB CLEANUP] Удалено {len(ids_to_delete)} прошедших игр.")
        except Exception as e:
            print(f"❌ Ошибка очистки БД: {e}")

    # Сортировка по дате
    try:
        games.sort(key=lambda x: datetime.strptime(x['дата'], "%d.%m.%Y"))
    except:
        pass

    return games


def get_game_by_id(game_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()

    if not row: return None

    parts_str = row['participants']
    parts = parts_str.split(",") if parts_str else []
    parts = [p.strip() for p in parts if p.strip()]

    return {
        "id": row['id'],
        "col_index": row['id'],
        "type": row['game_type'],
        "игра": row['game_name'],
        "дата": row['game_date'],
        "время": row['game_time'],
        "time_str": row['game_time'],
        "хост": row['host_name'],
        "контакт": row['host_contact'],
        "лимит": row['limit_count'],
        "участники": parts
    }


def add_participant_db(game_id, user_name):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT participants, limit_count FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        if not row: return "ERROR"

        current_parts_str, limit = row
        parts = current_parts_str.split(",") if current_parts_str else []
        parts = [p.strip() for p in parts if p.strip()]

        # Проверка дублей (без учета регистра)
        user_clean = user_name.lower().replace("@", "")
        for p in parts:
            if user_clean in p.lower().replace("@", ""):
                return "ALREADY"

        if len(parts) >= limit: return "FULL"

        parts.append(user_name)
        new_parts_str = ",".join(parts)
        cursor.execute("UPDATE games SET participants = ? WHERE id = ?", (new_parts_str, game_id))
        conn.commit()
        return "OK"


def remove_participant_db(game_id, user_name):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT participants FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        if not row: return False

        current_parts_str = row[0]
        parts = current_parts_str.split(",") if current_parts_str else []
        parts = [p.strip() for p in parts if p.strip()]

        # Удаление
        target_clean = user_name.lower().replace("@", "")
        new_parts = []
        found = False
        for p in parts:
            if target_clean in p.lower().replace("@", "") or p.lower().replace("@", "") in target_clean:
                found = True
            else:
                new_parts.append(p)

        if not found: return False

        new_parts_str = ",".join(new_parts)
        cursor.execute("UPDATE games SET participants = ? WHERE id = ?", (new_parts_str, game_id))
        conn.commit()
        return True


def delete_game_db(game_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
        conn.commit()