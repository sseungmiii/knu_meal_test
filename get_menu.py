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

DIRECT_BLOCKED = False
DIRECT_REQUEST_COUNT = 0
PROXY_REQUEST_COUNT = 0

def fetch_html(target_url, max_retries=2):
    global DIRECT_BLOCKED, DIRECT_REQUEST_COUNT, PROXY_REQUEST_COUNT

    for attempt in range(max_retries):
        if not DIRECT_BLOCKED:
            try:
                res = session.get(target_url, timeout=8)
                if valid_response(res):
                    DIRECT_REQUEST_COUNT += 1
                    return res
                print(f"[감지] 직접 응답 무효 (HTTP {res.status_code}, {len(res.content)} bytes). 프록시로 재시도합니다.")
                DIRECT_BLOCKED = bool(SCRAPER_KEY)
            except Exception as e:
                if SCRAPER_KEY:
                    print(f"[감지] 직접 연결 불가({type(e).__name__}). 프록시로 재시도합니다.")
                    DIRECT_BLOCKED = True
                else:
                    print(f"[경고] 직접 연결 실패 ({attempt + 1}/{max_retries}): {type(e).__name__}")

        if SCRAPER_KEY:
            try:
                PROXY_REQUEST_COUNT += 1
                proxy_url = f"https://api.scraperapi.com?api_key={SCRAPER_KEY}&url={quote(target_url)}&country_code=kr"
                res_proxy = session.get(proxy_url, timeout=25)
                if valid_response(res_proxy):
                    return res_proxy
                else:
                    print(f"[경고] 프록시 응답 무효 (HTTP {res_proxy.status_code}, {len(res_proxy.content)} bytes)")
            except Exception as proxy_e:
                print(f"[경고] 프록시 재시도 ({attempt + 1}/{max_retries}): {type(proxy_e).__name__}")

        if attempt < max_retries - 1:
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"HTML 요청 최종 실패: {target_url}")

def get_next_week_seldate(soup_main, now_kst):
    for a in soup_main.find_all("a", href=True):
        href = a["href"]
        if "selDate=" in href and any(img for img in a.find_all("img") if "nextweek" in img.get("src", "")):
            m = re.search(r"selDate=([\d\-]+)", href)
            if m:
                return m.group(1)
    days_ahead = 7 - now_kst.weekday()
    next_monday = now_kst + timedelta(days=days_ahead)
    return next_monday.strftime("%Y-%m-%d")

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
            curr_tokens = []

    if curr_tokens:
        remaining = " ".join(curr_tokens).strip()
        remaining = re.sub(r"^(특식|정식)\s*", "", remaining).strip()
        if remaining:
            items.append(remaining)

    return [{
        "meal": meal,
        "time": cell_time,
        "items": items
    }]

def crawl_menus(target_shops, sel_date=None):
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


def main():
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    old_data = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, encoding='utf-8') as f:
                old_data = json.load(f)
        except (OSError, ValueError) as e:
            print(f'[오류] 기존 식단을 읽을 수 없어 덮어쓰지 않습니다: {e}')
            return 1
    is_sunday = (now_kst.weekday() == 6)

    print(f"[실행 시각] {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (일요일 여부: {is_sunday})")

    shops = {}
    next_week_date = None
    try:
        res_main = fetch_html(f"{BASE_URL}?shop_sqno=35")
        res_main.encoding = "utf-8"
        soup_main = BeautifulSoup(res_main.text, "html.parser")

        for a in soup_main.find_all("a", href=True):
            href = a["href"]
            if "shop_sqno=" in href:
                m = re.search(r"shop_sqno=(\d+)", href)
                if m:
                    name = a.get_text().strip()
                    if name and "ENGLISH" not in name and name not in shops:
                        shops[name] = m.group(1)

        if is_sunday:
            next_week_date = get_next_week_seldate(soup_main, now_kst)
            print(f"[일요일 감지] 다음 주 식단 selDate 타깃: {next_week_date}")
    except Exception as e:
        print(f"[경고] 메인 페이지 조회 실패: {e}")

    if not shops:
        print("[알림] 기본 식당 ID 맵으로 대체 진행합니다.")
        shops = DEFAULT_SHOPS

    notice_message = ""
    is_next_week_loaded = False

    if is_sunday and next_week_date:
        print(f"[시도] 일요일이므로 다음 주 식단 수집을 먼저 시도합니다 (selDate={next_week_date})...")
        days, data, sc_count, item_count = crawl_menus(shops, sel_date=next_week_date)

        next_target = now_kst + timedelta(days=1)
        if sc_count >= 2 and item_count >= 10 and valid_week(days, next_target):
            print(f"[성공] 다음 주 식단이 정상 등록되어 있습니다 (총 메뉴 {item_count}개).")
            all_days, all_shops_data = days, data
            is_next_week_loaded = True
        else:
            print(f"[미등록 감지] 다음 주 식단이 아직 등록되지 않았거나 비어있습니다 (메뉴 {item_count}개).")
            notice_message = "다음 주 식단이 아직 등록되지 않아 지난 식단 정보를 유지합니다."
            print("[폴백] 이전 식단(현재 기본 페이지)을 수집합니다...")
            all_days, all_shops_data, sc_count, _ = crawl_menus(shops, sel_date=None)
    else:
        all_days, all_shops_data, sc_count, _ = crawl_menus(shops, sel_date=None)

    target = now_kst + timedelta(days=1) if is_next_week_loaded else now_kst
    result = build_result(old_data, shops, all_shops_data, target, now_kst,
                          notice_message, is_next_week_loaded)
    try:
        atomic_save(result)
    except (OSError, ValueError, TypeError) as e:
        print(f"[오류] 식단 저장 실패. 기존 파일을 보존합니다: {e}")
        return 1
    print(f"[수집 결과] {result['crawl_status']} / 점검: {result['last_checked']}")
    return 0 if result['crawl_status'] == 'success' else 1

if __name__ == "__main__":
    sys.exit(main())
