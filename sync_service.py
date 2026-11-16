# ФАЙЛ: sync_service.py

import asyncio
import re
from datetime import datetime, date
from sheets_api_guest_refactored import get_client
from database import clear_official_games, add_game_db, get_all_games
from gspread.utils import rowcol_to_a1

# ID вашей таблицы и имя листа
SPREADSHEET_ID = "1RiEIRl8QPVEyRKtpQKyGkE3yTKbTeEja-wyA8PFWVRk"
SHEET_NAME = "Игротеки_Антикафе"

# ЦВЕТА
COLOR_FREE = {"red": 0.675, "green": 0.843, "blue": 0.902}  # #acd7e6
COLOR_BUSY = {"red": 1.0, "green": 1.0, "blue": 1.0}  # Белый


def normalize_date_for_comparison(sheet_date_raw):
    now = datetime.now()
    clean = sheet_date_raw.strip()
    if not clean: return ""
    if len(clean) >= 8 and clean.count('.') == 2: return clean
    try:
        if clean.count('.') == 1:
            day, month = map(int, clean.split("."))
            year = now.year
            if month < now.month - 2: year += 1
            return f"{day:02d}.{month:02d}.{year}"
    except:
        pass
    return clean


# === ТЕХНИЧЕСКИЕ ФУНКЦИИ ===

async def _update_cell_with_format(sheet, row, col, value, color):
    try:
        request = {
            "requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": col - 1,
                        "endColumnIndex": col
                    },
                    "cell": {
                        "userEnteredValue": {"stringValue": value},
                        "userEnteredFormat": {"backgroundColor": color}
                    },
                    "fields": "userEnteredValue,userEnteredFormat.backgroundColor"
                }
            }]
        }
        await asyncio.to_thread(sheet.spreadsheet.batch_update, request)
    except Exception as e:
        print(f"❌ [FORMAT ERROR] {e}")


async def _find_game_column_and_limit(sheet, game_name, game_date):
    try:
        # Проверка на прошедшую дату
        try:
            dt_obj = datetime.strptime(game_date, "%d.%m.%Y").date()
            if dt_obj < datetime.now().date():
                print(f"⚠️ [INSTANT] Дата {game_date} уже прошла.")
                return None, 0
        except:
            pass

        headers = await asyncio.to_thread(sheet.get_values, "A1:ZZ4")
        if len(headers) < 4: return None, 0

        row_dates = headers[1]
        row_names = headers[2]
        row_infos = headers[3]
        target_name = game_name.strip().lower()

        for col_idx in range(1, len(row_names)):
            if col_idx >= len(row_names): break
            if row_names[col_idx].strip().lower() != target_name: continue

            if col_idx >= len(row_dates): break
            sheet_date = normalize_date_for_comparison(row_dates[col_idx])

            if sheet_date == game_date:
                limit = 8
                if col_idx < len(row_infos):
                    match = re.search(r'(\d+)\s*чел', row_infos[col_idx].lower())
                    if match: limit = int(match.group(1))
                return col_idx + 1, limit
    except Exception as e:
        print(f"❌ [INSTANT ERROR] {e}")
    return None, 0


# === МГНОВЕННЫЕ ОПЕРАЦИИ ===

async def instant_add_user_to_sheet(game_name, game_date, user_name):
    # Не пишем, если это игра по внешней ссылке
    print(f"⚡ [INSTANT ADD] {user_name} -> {game_name}")
    client = get_client()
    if not client: return

    try:
        sheet = await asyncio.to_thread(client.open_by_key(SPREADSHEET_ID).worksheet, SHEET_NAME)
        col_idx, limit = await _find_game_column_and_limit(sheet, game_name, game_date)
        if not col_idx: return

        col_letter = rowcol_to_a1(1, col_idx).replace("1", "")
        range_str = f"{col_letter}6:{col_letter}{6 + limit - 1}"
        participants_data = await asyncio.to_thread(sheet.get_values, range_str)
        participants = [row[0] if row else "" for row in participants_data]

        row_to_write = -1
        for i in range(limit):
            val = participants[i].strip().lower() if i < len(participants) else ""
            if not val or val == "свободно":
                row_to_write = 6 + i
                break

        if row_to_write != -1:
            await _update_cell_with_format(sheet, row_to_write, col_idx, user_name, COLOR_BUSY)
            print(f"✅ [INSTANT ADD] Успех: {col_letter}{row_to_write}")
        else:
            print(f"⚠️ [INSTANT ADD] Нет мест.")
    except Exception as e:
        print(f"❌ [INSTANT ADD] Ошибка: {e}")


async def instant_remove_user_from_sheet(game_name, game_date, user_name_fragment):
    print(f"⚡ [INSTANT REMOVE] Ищу '{user_name_fragment}' в '{game_name}' ({game_date})...")
    client = get_client()
    if not client: return

    try:
        sheet = await asyncio.to_thread(client.open_by_key(SPREADSHEET_ID).worksheet, SHEET_NAME)
        col_idx, limit = await _find_game_column_and_limit(sheet, game_name, game_date)

        if not col_idx:
            print("⚠️ [INSTANT REMOVE] Игра не найдена в таблице (проверьте дату/название).")
            return

        col_letter = rowcol_to_a1(1, col_idx).replace("1", "")
        # Читаем с запасом (вдруг записали ниже лимита)
        range_str = f"{col_letter}6:{col_letter}{6 + 15}"
        participants_data = await asyncio.to_thread(sheet.get_values, range_str)

        target_clean = user_name_fragment.lower().replace("@", "").strip()

        for i, row in enumerate(participants_data):
            val = row[0] if row else ""
            val_clean = val.lower().replace("@", "").strip()

            # Проверяем вхождение
            if target_clean in val_clean and val_clean not in ["", "свободно"]:
                row_to_clear = 6 + i

                # ЛОГИКА ЦВЕТОВ ПРИ УДАЛЕНИИ:
                # Если строка внутри лимита -> "свободно" (Голубой)
                # Если строка за пределами лимита -> "" (Белый/Очистить)
                if i < limit:
                    await _update_cell_with_format(sheet, row_to_clear, col_idx, "свободно", COLOR_FREE)
                    print(f"✅ [INSTANT REMOVE] Удален (Свободно): {col_letter}{row_to_clear}")
                else:
                    await _update_cell_with_format(sheet, row_to_clear, col_idx, "", COLOR_BUSY)
                    print(f"✅ [INSTANT REMOVE] Удален (Очищен): {col_letter}{row_to_clear}")
                return

        print(f"⚠️ [INSTANT REMOVE] Имя '{user_name_fragment}' не найдено в столбце {col_letter}.")

    except Exception as e:
        print(f"❌ [INSTANT REMOVE] Ошибка: {e}")


# ==========================================
# 🔄 УМНЫЙ ЭКСПОРТ (БЕЗОПАСНЫЙ)
# ==========================================

async def export_to_sheets():
    """
    УМНЫЙ ЭКСПОРТ: Не удаляет ручные записи!
    Только заполняет пустые места и 'свободно'.
    """
    # print("📤 [BG EXPORT] Запуск безопасного экспорта...")
    client = get_client()
    if not client: return

    try:
        sheet = await asyncio.to_thread(client.open_by_key(SPREADSHEET_ID).worksheet, SHEET_NAME)
        sheet_values = await asyncio.to_thread(sheet.get_all_values)  # Читаем ВСЮ таблицу
    except:
        return

    if len(sheet_values) < 5: return

    db_games = await asyncio.to_thread(get_all_games)
    official_games = [g for g in db_games if g['type'] == 'official']

    row_dates = sheet_values[1]
    row_names = sheet_values[2]
    requests = []
    now_date = datetime.now().date()

    for game in official_games:
        db_date = game['дата']
        db_name = game['игра'].strip().lower()

        # === НОВАЯ ПРОВЕРКА ===
        # Если в описании есть маркеры "своей записи" (ссылка или стоп-слова),
        # мы вообще не трогаем эту колонку в таблице.
        info_raw = str(game.get('инфо', '')).lower()
        stop_words = ["форма", "лс", "личка", "сайт", "директ", "запись через"]

        if "|||" in info_raw or any(w in info_raw for w in stop_words):
            # print(f"⏩ [SKIP] Пропускаем игру со своей формой записи: {game['игра']}")
            continue
        # ======================

        try:
            if datetime.strptime(db_date, "%d.%m.%Y").date() < now_date: continue
        except:
            continue

        db_participants = game['участники']
        limit = game['лимит']

        found_col = -1
        for col in range(1, len(row_names)):
            if row_names[col].strip().lower() == db_name:
                if normalize_date_for_comparison(row_dates[col]) == db_date:
                    found_col = col
                    break

        if found_col != -1:
            # 1. Считываем ТЕКУЩИЙ столбец из памяти (sheet_values)
            # Мы не будем его стирать, мы будем его дополнять.

            final_col_values = []

            for i in range(limit):
                row_idx = 5 + i
                existing_val = ""
                if row_idx < len(sheet_values) and found_col < len(sheet_values[row_idx]):
                    existing_val = sheet_values[row_idx][found_col].strip()

                final_col_values.append(existing_val)

            # 2. Пытаемся вписать отсутствующих бот-юзеров
            for user in db_participants:
                # Проверяем, есть ли этот юзер уже (нечеткий поиск)
                found = False
                for val in final_col_values:
                    if user.lower().replace("@", "") in val.lower().replace("@", ""):
                        found = True
                        break

                if not found:
                    # Если юзера нет в таблице -> ищем СВОБОДНОЕ место
                    inserted = False
                    for k in range(len(final_col_values)):
                        cell = final_col_values[k]
                        if not cell or cell.lower() == "свободно":
                            final_col_values[k] = user  # Вписываем сюда
                            inserted = True
                            break
                    if not inserted:
                        print(f"⚠️ [BG EXPORT] Нет места для {user} в таблице (все занято ручными записями)")

            # 3. Формируем запросы на обновление
            # (Только если значение в таблице отличается или нужно покрасить)
            # Для надежности перезапишем сформированный столбец final_col_values с правильными цветами

            for i in range(limit):
                val = final_col_values[i]
                row_idx = 5 + i

                # Если пусто, пишем "свободно" и синий цвет
                if not val or val.lower() == "свободно":
                    final_val = "свободно"
                    color = COLOR_FREE
                else:
                    final_val = val
                    color = COLOR_BUSY

                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet.id,
                            "startRowIndex": row_idx,
                            "endRowIndex": row_idx + 1,
                            "startColumnIndex": found_col,
                            "endColumnIndex": found_col + 1
                        },
                        "cell": {
                            "userEnteredValue": {"stringValue": final_val},
                            "userEnteredFormat": {"backgroundColor": color}
                        },
                        "fields": "userEnteredValue,userEnteredFormat.backgroundColor"
                    }
                })

    if requests:
        try:
            body = {"requests": requests}
            await asyncio.to_thread(sheet.spreadsheet.batch_update, body)
            print(f"✅ [BG EXPORT] Синхронизация завершена.")
        except Exception as e:
            print(f"❌ [BG EXPORT] Ошибка: {e}")


async def sync_anticafe_games():
    """Импорт игротек «Антикафе» из листа в БД.

    Возвращает (сколько игр загружено, текст ошибки или None).
    """
    # print("🔄 [BG IMPORT] Чтение таблицы...")
    client = get_client()
    if not client:
        return 0, f"нет доступа к Google (лист «{SHEET_NAME}»)"
    try:
        sheet = await asyncio.to_thread(client.open_by_key(SPREADSHEET_ID).worksheet, SHEET_NAME)
        data = await asyncio.to_thread(sheet.get_all_values)
    except Exception as e:
        return 0, f"лист «{SHEET_NAME}»: {e}"

    if len(data) < 5:
        return 0, f"лист «{SHEET_NAME}» пуст"

    clear_official_games()
    count = 0
    try:
        date_row, game_row, time_row, host_row = data[1], data[2], data[3], data[4]
        note_row_index = -1
        for i, row in enumerate(data[:30]):
            if row and "примечания" in str(row[0]).lower(): note_row_index = i; break

        now_date = datetime.now().date()

        # Ширина берётся по самой длинной строке: строка дат короче строки игр,
        # и новые колонки иначе молча не находятся
        width = max(len(date_row), len(game_row), len(time_row), len(host_row))
        for col_idx in range(1, width):
            # Безопасная проверка длины
            if col_idx >= len(date_row) or col_idx >= len(time_row) or col_idx >= len(host_row):
                continue

            if not game_row[col_idx] or not date_row[col_idx]: continue
            if host_row[col_idx].lower() == "свободно" and not time_row[col_idx]: continue

            full_date = normalize_date_for_comparison(date_row[col_idx])
            try:
                if datetime.strptime(full_date, "%d.%m.%Y").date() < now_date: continue
            except:
                pass

            note_text, ext_link = "", None
            if note_row_index != -1 and note_row_index < len(data) and col_idx < len(data[note_row_index]):
                raw = data[note_row_index][col_idx].strip()
                match = re.search(r'(https?://[^\s]+)', raw)
                if match:
                    ext_link = match.group(0);
                    note_text = raw.replace(ext_link, "").strip()
                else:
                    note_text = raw

            info = time_row[col_idx].strip()
            if note_text: info = f"{info} ({note_text})"
            if ext_link: info += f"|||{ext_link}"

            limit = 10
            match = re.search(r'(\d+)\s*чел', time_row[col_idx].lower())
            if match: limit = int(match.group(1))

            curr_parts = []
            end = note_row_index if note_row_index != -1 else 20
            for r in range(5, end):
                if r < len(data) and col_idx < len(data[r]):
                    val = data[r][col_idx].strip()
                    if val and val.lower() != "свободно": curr_parts.append(val)

            add_game_db('official', game_row[col_idx], full_date, info, host_row[col_idx], "Антикафе", limit,
                        curr_parts)
            count += 1
        # print(f"✅ [BG IMPORT] Загружено игр: {count}")
    except Exception as e:
        print(f"❌ [BG IMPORT] Ошибка: {e}")
        return count, f"разбор листа «{SHEET_NAME}»: {e}"
    return count, None


async def run_sync_cycle():
    await export_to_sheets()
    await asyncio.sleep(5)
    await sync_anticafe_games()