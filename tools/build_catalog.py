#!/usr/bin/env python3
"""
Общий каталог Frame: снимок ответов Кинопоиска для главного экрана и карточек фильмов.

Запускается в GitHub Actions по расписанию. Ответы сохраняются «как есть» под ключом
пути запроса (например, "/api/v2.2/films/301"), поэтому приложение отдаёт их своему
обычному клиенту API без изменений. Карточки докачиваются постепенно, с жёстким
лимитом запросов за запуск, чтобы не съедать дневной лимит ключа.
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://kinopoiskapiunofficial.tech"
KEY = os.environ.get("KP_API_KEY", "").strip()
OUT = os.environ.get("CATALOG_OUT", "catalog.json")
PREVIOUS = os.environ.get("CATALOG_PREVIOUS", OUT)
MAX_REQUESTS = int(os.environ.get("MAX_REQUESTS", "120"))
DETAILS_TTL_DAYS = 14

COLLECTIONS = [
    "TOP_POPULAR_MOVIES", "POPULAR_SERIES", "FAMILY", "KIDS_ANIMATION_THEME",
    "TOP_250_MOVIES", "TOP_250_TV_SHOWS", "OSKAR_WINNERS_2021", "LOVE_THEME",
    "COMICS_THEME", "CATASTROPHE_THEME",
]
MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]

used = 0


def get(path):
    """GET к API Кинопоиска; None при ошибке. Считает запросы и соблюдает лимит 10/с."""
    global used
    if used >= MAX_REQUESTS:
        return None
    used += 1
    req = urllib.request.Request(API + path, headers={"X-API-KEY": KEY, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                time.sleep(0.15)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (402, 429):
                print(f"limit reached ({e.code}) on {path}", file=sys.stderr)
                used = MAX_REQUESTS
                return None
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # сеть: короткий повтор
            print(f"retry {path}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def trim_staff(staff):
    """Из полного состава оставляем режиссёров и до 20 актёров — как показывает приложение."""
    if not isinstance(staff, list):
        return []
    directors = [s for s in staff if s.get("professionKey") == "DIRECTOR"]
    actors = [s for s in staff if s.get("professionKey") == "ACTOR"][:20]
    keep = ("staffId", "nameRu", "nameEn", "professionKey", "posterUrl", "description")
    return [{k: s.get(k) for k in keep} for s in directors + actors]


def main():
    if not KEY:
        sys.exit("KP_API_KEY is not set")
    now = datetime.datetime.utcnow()
    try:
        with open(PREVIOUS, encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = {}
    responses = dict(prev.get("responses", {}))
    fetched_at = dict(prev.get("fetchedAt", {}))

    # 1. Подборки главного экрана (каждый запуск — свежие).
    row_paths = [f"/api/v2.2/films/collections?type={c}&page=1" for c in COLLECTIONS]
    row_paths.append(f"/api/v2.2/films/premieres?year={now.year}&month={MONTHS[now.month - 1]}")
    for path in row_paths:
        data = get(path)
        if data is not None:
            responses[path] = data
            fetched_at[path] = now.isoformat()

    # 2. Фильмы из подборок: карточка + состав. Сначала новые, затем устаревшие.
    ids = []
    for path in row_paths:
        data = responses.get(path) or {}
        for item in data.get("items", []):
            fid = item.get("kinopoiskId") or item.get("filmId")
            if fid and fid not in ids:
                ids.append(fid)

    def age_days(path):
        ts = fetched_at.get(path)
        if not ts:
            return 10 ** 6
        return (now - datetime.datetime.fromisoformat(ts)).days

    queue = sorted(ids, key=lambda i: -age_days(f"/api/v2.2/films/{i}"))
    for fid in queue:
        film_path = f"/api/v2.2/films/{fid}"
        staff_path = f"/api/v1/staff?filmId={fid}"
        if age_days(film_path) < DETAILS_TTL_DAYS and staff_path in responses:
            continue
        if used + 3 > MAX_REQUESTS:
            break
        film = get(film_path)
        if film is None:
            continue
        responses[film_path] = film
        fetched_at[film_path] = now.isoformat()
        staff = get(staff_path)
        if staff is not None:
            responses[staff_path] = trim_staff(staff)
            fetched_at[staff_path] = now.isoformat()
        # Нет обложки — приложение возьмёт кадр из фильма; кладём первую страницу кадров.
        if not film.get("coverUrl") and used < MAX_REQUESTS:
            images_path = f"/api/v2.2/films/{fid}/images?type=STILL&page=1"
            images = get(images_path)
            if images is not None:
                items = (images.get("items") or [])[:1]
                responses[images_path] = {"total": len(items), "totalPages": 1, "items": items}
                fetched_at[images_path] = now.isoformat()

    # Удаляем карточки фильмов, выпавших из всех подборок больше месяца назад.
    keep_ids = {str(i) for i in ids}
    for path in list(responses):
        fid = None
        if path.startswith("/api/v2.2/films/") and path.split("/")[-1].isdigit():
            fid = path.split("/")[-1]
        elif path.startswith("/api/v1/staff?filmId="):
            fid = path.split("=")[-1]
        elif "/images?" in path:
            fid = path.split("/")[4]
        if fid and fid not in keep_ids and age_days(path) > 30:
            responses.pop(path, None)
            fetched_at.pop(path, None)

    out = {
        "version": 1,
        "generatedAt": now.isoformat() + "Z",
        "responses": responses,
        "fetchedAt": fetched_at,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    films = sum(1 for p in responses if p.startswith("/api/v2.2/films/") and p.split("/")[-1].isdigit())
    print(f"requests used: {used}, rows: {len(row_paths)}, films with details: {films}/{len(ids)}")


if __name__ == "__main__":
    main()
