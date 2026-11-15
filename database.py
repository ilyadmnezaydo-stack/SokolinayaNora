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
        try:
            # id участников в том же порядке, что и имена — чтобы люди
            # с одинаковыми именами не могли отменять чужие записи
            cursor.execute("ALTER TABLE games ADD COLUMN participant_ids TEXT DEFAULT ''")
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
        try:
            ids_raw = row['participant_ids']
        except (IndexError, KeyError):
            ids_raw = ""
        ids = [i.strip() for i in (ids_raw or "").split(",")]
        ids = (ids + [""] * len(parts))[:len(parts)]

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
            "участники": parts,
            "участники_ids": ids
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
    try:
        ids_raw = row['participant_ids']
    except (IndexError, KeyError):
        ids_raw = ""
    ids = [i.strip() for i in (ids_raw or "").split(",")]
    ids = (ids + [""] * len(parts))[:len(parts)]

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
        "участники": parts,
        "участники_ids": ids
    }


def add_participant_db(game_id, user_name, user_id=None):
    """Добавляет участника. user_id пишется в параллельный список participant_ids,
    чтобы потом можно было отменить запись строго по человеку, а не по имени."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT participants, limit_count, COALESCE(participant_ids, '') FROM games WHERE id = ?",
            (game_id,))
        row = cursor.fetchone()
        if not row: return "ERROR"

        current_parts_str, limit, current_ids_str = row
        parts = [p.strip() for p in (current_parts_str or "").split(",") if p.strip()]
        ids = [i.strip() for i in (current_ids_str or "").split(",")]
        ids = (ids + [""] * len(parts))[:len(parts)]

        user_clean = str(user_name or "").lower().replace("@", "")

        # Дубли: по user_id строго; по имени — только для старых записей без id,
        # иначе два разных человека с одинаковым именем не смогут записаться
        if user_id:
            if str(user_id) in ids:
                return "ALREADY"
            for p, pid in zip(parts, ids, strict=False):
                if not pid and user_clean and user_clean in p.lower().replace("@", ""):
                    return "ALREADY"
        else:
            for p in parts:
                if user_clean and user_clean in p.lower().replace("@", ""):
                    return "ALREADY"

        if limit and len(parts) >= int(limit):
            return "FULL"

        parts.append(user_name)
        ids.append(str(user_id) if user_id else "")
        cursor.execute(
            "UPDATE games SET participants = ?, participant_ids = ? WHERE id = ?",
            (",".join(parts), ",".join(ids), game_id))
        conn.commit()
        return "OK"


def remove_participant_db(game_id, user_name, user_id=None):
    """Удаляет участника по user_id (если известен), иначе по имени.
    Имена и id удаляются по одному и тому же индексу, чтобы списки не разъехались."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT participants, COALESCE(participant_ids, '') FROM games WHERE id = ?",
            (game_id,))
        row = cursor.fetchone()
        if not row: return False

        parts = [p.strip() for p in (row[0] or "").split(",") if p.strip()]
        ids = [i.strip() for i in (row[1] or "").split(",")]
        ids = (ids + [""] * len(parts))[:len(parts)]

        target_clean = str(user_name or "").lower().replace("@", "").strip()
        idx = None

        if user_id:
            for i, pid in enumerate(ids):
                if pid and pid == str(user_id):
                    idx = i
                    break

        if idx is None and target_clean:
            for i, p in enumerate(parts):
                if p.lower().replace("@", "").strip() == target_clean:
                    idx = i
                    break

        if idx is None and target_clean:
            for i, p in enumerate(parts):
                norm = p.lower().replace("@", "").strip()
                if norm and (target_clean in norm or norm in target_clean):
                    idx = i
                    break

        if idx is None:
            return False

        del parts[idx]
        del ids[idx]
        cursor.execute(
            "UPDATE games SET participants = ?, participant_ids = ? WHERE id = ?",
            (",".join(parts), ",".join(ids), game_id))
        conn.commit()
        return True


def delete_game_db(game_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
        conn.commit()