import os
import json
import re
import sys
import time
import tempfile
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

# Windows 콘솔 cp949 인코딩 충돌 방지
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 파일 저장 경로 설정 (현재 스크립트 위치 기준)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, "menu.json")

BASE_URL = "https://coop.knu.ac.kr/sub03/sub01_01.html"
SCRAPER_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()

DEFAULT_SHOPS = {
    "정보센터식당": "35",
    "복지관 교직원식당": "36",
    "카페테리아 첨성": "37",
    "GP감꽃식당": "46",
    "공학관교직원식당(외부업체)": "85",
    "공학관학생식당(외부업체)": "86"
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
})

DIRECT_REQUEST_COUNT = 0
PROXY_REQUEST_COUNT = 0


def fetch_html(target_url, max_retries=2):
    global DIRECT_REQUEST_COUNT, PROXY_REQUEST_COUNT
    for attempt in range(1 if SCRAPER_KEY else max_retries):
        try:
            DIRECT_REQUEST_COUNT += 1
            res = session.get(target_url, timeout=8)
            if valid_response(res):
                return res
        except requests.RequestException:
            pass
        if not SCRAPER_KEY and attempt + 1 < max_retries:
            time.sleep(1.5)

    if SCRAPER_KEY:
        try:
            PROXY_REQUEST_COUNT += 1
            proxy = f"https://api.scraperapi.com?api_key={SCRAPER_KEY}&url={quote(target_url)}&country_code=kr"
            res = session.get(proxy, timeout=25)
            if valid_response(res):
                return res
        except requests.RequestException:
            pass
    raise RuntimeError(f"HTML 요청 최종 실패: {target_url}")


def extract_days(soup):
    for tbl in soup.find_all("table"):
        cells = tbl.find_all(["th", "td"])
        found = []
        for c in cells:
            txt = c.get_text().strip().replace("\xa0", " ")
            if any(txt.startswith(d) for d in ["월", "화", "수", "목", "금", "토"]) and "(" in txt:
                if txt not in found:  # 중복 추가 방지
                    found.append(txt)
        # 공휴일/단축 주간 대응: 운영일이 5개가 안 되더라도 요일이 1개 이상 존재하면 수집하도록 조건 완화
        if len(found) >= 1:
            return found
    return []

def valid_response(response):
    """HTTP 200 안내 페이지 및 요일 헤더만 있는 빈 표를 거부한다."""
    if response.status_code != 200:
        return False
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    days = extract_days(soup)
    if not days:
        return False
    for row in soup.select("table tr"):
        cells = [cell for cell in row.find_all("td", recursive=False)
                 if cell.get_text().strip() not in ["조식", "중식", "석식", "분류", "코너"]]
        if len(cells) != len(days):
            continue
        for cell in cells:
            text = cell.get_text(" ", strip=True)
            if price_pattern.search(text) and not re.match(r"^[월화수목금토]\s*\(", text):
                return True
    return False

raw_time_regex = re.compile(r"\(?\b(\d{1,2}:?\d{2})\s*~\s*(\d{1,2}:?\d{2})분?\)?")
price_pattern = re.compile(r"([￦₩]\s*[\d,]+|[\d,]+\s*원)")

def normalize_time_str(time_str):
    clean = time_str.replace("분", "").strip()
    if ":" not in clean and len(clean) in [3, 4]:
        return f"{clean[:-2]}:{clean[-2:]}"
    return clean

def format_time_range(t_start, t_end):
    start = normalize_time_str(t_start)
    end = normalize_time_str(t_end)
    return f"{start}~{end}"

def clean_menu_text(text):
    t = text.replace("★", "").replace("☆", "").replace("*", "")
    t = re.sub(r"\b(특식|정식)\b", "", t)
    t = re.sub(r"(?<!\d),(?!\d)", " ", t)
    t = re.sub(r"\s*&\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def parse_cell(td_el):
    raw_lines = [l.strip() for l in td_el.get_text(separator="\n").split("\n") if l.strip()]
    raw_lines = [l for l in raw_lines if l not in ["분류", "코너", "조식", "중식", "석식", "특식", "정식"]]
    if not raw_lines:
        return []

    full_text = " ".join(raw_lines)

    cell_time = ""
    t_match = raw_time_regex.search(full_text)
    if t_match:
        cell_time = format_time_range(t_match.group(1), t_match.group(2))

    meal = "중식"
    if "천원의 아침밥" in full_text or "천원의아침밥" in full_text or any(h in cell_time for h in ["08:", "09:", "10:00~11"]):
        meal = "조식"
        if not cell_time:
            cell_time = "09:00~11:00"
    elif any(h in cell_time for h in ["17:", "18:", "19:"]) or "1식4찬" in full_text:
        meal = "석식"
        if not cell_time:
            cell_time = "17:00~19:00"

    items = []
    item_parts = {}
    curr_tokens = []

    for line in raw_lines:
        if raw_time_regex.fullmatch(line) or line.startswith("운영시간"):
            continue

        cleaned = raw_time_regex.sub("", line).strip()
        cleaned = clean_menu_text(cleaned)
        if not cleaned:
            continue

        curr_tokens.append(cleaned)

        if price_pattern.search(line):
            menu_combined = " ".join(curr_tokens).strip()
            menu_combined = re.sub(r"^(특식|정식)\s*", "", menu_combined).strip()
            if menu_combined:
                items.append(menu_combined)
                parts = [price_pattern.sub("", token).strip() for token in curr_tokens]
                parts = [part for part in parts if part]
                if len(parts) > 1:
                    item_parts[menu_combined] = parts
            curr_tokens = []

    if curr_tokens:
        remaining = " ".join(curr_tokens).strip()
        remaining = re.sub(r"^(특식|정식)\s*", "", remaining).strip()
        if remaining:
            items.append(remaining)

    return [{
        "meal": meal,
        "time": cell_time,
        "items": items,
        "item_parts": item_parts
    }]

def crawl_menus(target_shops, sel_date=None, prefetched=None):
    all_shops_data = {}
    all_days = []
    total_items_count = 0
    success_count = 0

    for shop_name, shop_id in target_shops.items():
        url = f"{BASE_URL}?shop_sqno={shop_id}"
        if sel_date:
            url += f"&selDate={sel_date}"

        time.sleep(0.8)
        try:
            res = (prefetched or {}).get(url)
            if isinstance(res, Exception):
                raise res
            if res is None:
                res = fetch_html(url)
            res.encoding = "utf-8"
            soup = BeautifulSoup(res.text, "html.parser")

            days = extract_days(soup)
            shop_items_count = 0
            if not days:
                all_shops_data[shop_name] = {}
                continue

            if not all_days:
                all_days = days

            weekly = {day: {"조식": {"time": "", "items": []},
                            "중식": {"time": "", "items": []},
                            "석식": {"time": "", "items": []}} for day in days}

            row_context_meal = None

            for tbl in soup.find_all("table"):
                for tr in tbl.find_all("tr"):
                    header_txt = tr.get_text().replace(" ", "")
                    if "조식" in header_txt:
                        row_context_meal = "조식"
                    elif "석식" in header_txt:
                        row_context_meal = "석식"
                    elif "중식" in header_txt:
                        row_context_meal = "중식"

                    tds = tr.find_all("td")
                    content_tds = [td for td in tds if td.get_text().strip() not in ["조식", "중식", "석식", "분류", "코너"]]

                    if len(content_tds) == len(days):
                        for idx, td in enumerate(content_tds):
                            day_key = days[idx]
                            results = parse_cell(td)

                            for res_item in results:
                                target_meal = res_item["meal"]
                                if target_meal == "중식" and row_context_meal and not res_item["time"]:
                                    target_meal = row_context_meal

                                if res_item["time"] and not weekly[day_key][target_meal]["time"]:
                                    weekly[day_key][target_meal]["time"] = res_item["time"]

                                for itm in res_item["items"]:
                                    if itm not in weekly[day_key][target_meal]["items"]:
                                        weekly[day_key][target_meal]["items"].append(itm)
                                        if itm in res_item["item_parts"]:
                                            weekly[day_key][target_meal].setdefault("item_parts", {})[itm] = res_item["item_parts"][itm]
                                        total_items_count += 1
                                        shop_items_count += 1

            cleaned_weekly = {}
            for d in days:
                cleaned_weekly[d] = {}
                for m in ["조식", "중식", "석식"]:
                    if weekly[d][m]["items"]:
                        cleaned_weekly[d][m] = weekly[d][m]

            all_shops_data[shop_name] = cleaned_weekly
            if shop_items_count:
                success_count += 1
                print(f"[수집 성공] {shop_name} ({shop_items_count}개 메뉴)")

        except Exception as e:
            print(f"[수집 실패] {shop_name}: {e}")
            all_shops_data[shop_name] = {}

    return all_days, all_shops_data, success_count, total_items_count

def atomic_save(data):
    """Replace only after the complete JSON has reached disk."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=os.path.dirname(JSON_PATH), delete=False) as f:
            temp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, JSON_PATH)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def valid_week(days, target):
    """Allow shortened weeks, but reject dates/weekday labels outside the target week."""
    monday = target.date() - timedelta(days=target.weekday())
    expected = {
        f"{'월화수목금토일'[i]}({(monday + timedelta(days=i)).strftime('%m/%d')})"
        for i in range(7)
    }
    normalized = [re.sub(r"\s", "", day) for day in days]
    return bool(normalized) and len(set(normalized)) == len(normalized) and all(day in expected for day in normalized)


def build_result(old, shops, data, target, now, notice="", next_week=False):
    stamp = now.strftime('%Y-%m-%d %H:%M:%S')
    merged, statuses, days = {}, {}, []
    successes = 0
    shop_names = list(dict.fromkeys([*shops, *old.get('shops', []), *old.get('data', {})]))
    for shop in shop_names:
        weekly = data.get(shop, {})
        valid = valid_week(list(weekly), target) and any(
            info.get('items') for daily in weekly.values() for info in daily.values())
        previous = old.get('shop_status', {}).get(shop, {})
        if valid:
            successes += 1
            merged[shop] = weekly
            statuses[shop] = dict(status='success', last_checked=stamp, last_success=stamp)
            for day in weekly:
                if day not in days:
                    days.append(day)
        else:
            merged[shop] = old.get('data', {}).get(shop, {})
            statuses[shop] = dict(status='failed', last_checked=stamp,
                                  last_success=previous.get('last_success', old.get('last_checked')),
                                  message='수집 실패 또는 대상 주간과 날짜가 다릅니다. 이전 식단을 표시합니다.')
    status = 'success' if successes == len(shop_names) and successes else 'partial' if successes else 'failed'
    # Keep older day keys selectable without hiding the successful current week.
    for weekly in merged.values():
        for day in weekly:
            if day not in days:
                days.append(day)
    result = dict(old, last_checked=stamp, crawl_status=status, shop_status=statuses,
                  notice=notice, data=merged, days=days, shops=shop_names, is_next_week=next_week)
    changed = any(result.get(key) != old.get(key) for key in ('data', 'days', 'shops'))
    result['updated_at'] = stamp if successes and changed else old.get('updated_at')
    if status == 'failed':
        result['data'] = old.get('data', {})
        result['days'] = old.get('days', [])
        result['is_next_week'] = old.get('is_next_week', False)
        result['notice'] = '식단 수집에 실패하여 이전 식단을 표시합니다. 실제 갱신 날짜를 확인해주세요.'
    return result


def missing_meals(weekly, previous, target):
    """Require a weekday menu and retain previously published meals for the same date."""
    day = f"{'월화수목금토일'[target.weekday()]}({target:%m/%d})"
    def at_date(data):
        return next((meals for key, meals in data.items()
                     if isinstance(meals, dict) and re.sub(r"\s", "", key) == day), {})
    current, prior = at_date(weekly), at_date(previous)
    missing = {meal for meal, value in prior.items() if value.get("items")
               and not current.get(meal, {}).get("items")}
    if target.weekday() < 5 and not any(value.get("items") for value in current.values()):
        missing.add("오늘 식단")
    return missing


def main(slot=None):
    global DIRECT_REQUEST_COUNT, PROXY_REQUEST_COUNT
    DIRECT_REQUEST_COUNT = PROXY_REQUEST_COUNT = 0
    now_kst = datetime.now(timezone(timedelta(hours=9)))
    run_date = now_kst.date().isoformat()
    old_data = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, encoding='utf-8') as f:
                old_data = json.load(f)
        except (OSError, ValueError) as e:
            print(f'[오류] 기존 식단을 읽을 수 없어 덮어쓰지 않습니다: {e}')
            return 1

    state = old_data.get("collection", {})
    same_day = state.get("date") == run_date
    retry = slot is not None and slot > 0 and same_day
    if slot is not None and same_day and (slot <= state.get("slot", -1) or not state.get("pending")):
        print("[수집 생략] 이미 처리한 회차 또는 재시도할 식당 없음")
        return 0

    next_week = now_kst.weekday() == 6
    target = now_kst + timedelta(days=1) if next_week else now_kst
    shops = dict(DEFAULT_SHOPS)
    prefetched = {}
    if retry:
        shops.update(state.get("shop_ids", {}))
    elif not next_week:
        url = f"{BASE_URL}?shop_sqno=35"
        try:
            response = fetch_html(url)
            prefetched[url] = response
            soup = BeautifulSoup(response.text, "html.parser")
            discovered = {}
            for link in soup.find_all("a", href=True):
                match = re.search(r"shop_sqno=(\d+)", link["href"])
                name = link.get_text(strip=True)
                if match and name and "ENGLISH" not in name:
                    discovered[match.group(1)] = name
            # Keep known IDs if the navigation itself is incomplete.
            by_id = {shop_id: shop for shop, shop_id in shops.items()}
            by_id.update(discovered)
            shops = {shop: shop_id for shop_id, shop in by_id.items()}
        except RuntimeError as e:
            prefetched[url] = e  # don't pay again for the same failed lookup
            print("[수집] 식당 목록 조회 실패: 기본 식당 목록 사용")

    requested = {shop: shop_id for shop, shop_id in shops.items()
                 if not retry or shop in state["pending"]}
    _, data, _, _ = crawl_menus(requested, sel_date=f"{target:%Y-%m-%d}" if next_week else None,
                                prefetched=prefetched)
    carried = old_data.get("data", {})
    failed = {}
    for shop, weekly in data.items():
        if valid_week(list(weekly), target):
            missing = missing_meals(weekly, carried.get(shop, {}), target)
            if missing:
                failed[shop] = sorted(missing)
    reused = {shop: carried[shop] for shop in shops if shop not in requested and shop in carried}
    result = build_result(old_data, shops, {**reused, **data}, target, now_kst, next_week=next_week)
    for shop in reused:
        result["shop_status"][shop] = old_data["shop_status"][shop]
    for shop, missing in failed.items():
        status = result["shop_status"][shop]
        if status["status"] != "success":
            continue
        day = f"{'월화수목금토일'[target.weekday()]}({target:%m/%d})"
        previous_day = next((value for key, value in carried.get(shop, {}).items()
                             if re.sub(r"\s", "", key) == day), {})
        current_day = next((key for key in data[shop] if re.sub(r"\s", "", key) == day), day)
        for meal in missing:
            if meal in previous_day:
                result["data"][shop].setdefault(current_day, {})[meal] = previous_day[meal]
        status.update(status="partial", missing=missing,
                      last_success=old_data.get("shop_status", {}).get(shop, {}).get("last_success"))
    pending = [shop for shop, info in result["shop_status"].items() if info["status"] != "success"]
    if pending and result["crawl_status"] == "success":
        result["crawl_status"] = "partial"
    if result["crawl_status"] == "partial":
        result["updated_at"] = (now_kst.strftime("%Y-%m-%d %H:%M:%S")
                                if result["data"] != carried else old_data.get("updated_at"))
    if not retry:
        attempts = 0
    else:
        attempts = state.get("proxy_requests", 0)
    result["collection"] = dict(date=run_date, slot=slot if slot is not None else state.get("slot", -1) if same_day else -1,
                                pending=pending, shop_ids=shops,
                                proxy_requests=attempts + PROXY_REQUEST_COUNT)
    print(f"[요청] 직접 {DIRECT_REQUEST_COUNT}회 / 프록시 {PROXY_REQUEST_COUNT}회")
    try:
        atomic_save(result)
    except (OSError, ValueError, TypeError) as e:
        print(f"[오류] 식단 저장 실패. 기존 파일을 보존합니다: {e}")
        return 1
    print(f"[수집 결과] {result['crawl_status']} / 점검: {result['last_checked']}")
    return 0 if result['crawl_status'] == 'success' else 1

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", type=int, choices=range(4))
    sys.exit(main(parser.parse_args().slot))
