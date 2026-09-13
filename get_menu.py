import os
import json
import re
import sys
import time
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
    """
    [2중 스마트 요청 (Smart Fallback & Retry) 로직]
    1. 1차 시도 (직접 요청):
       - 로컬 PC 등 국내 IP 환경에서는 직접 연결하여 ScraperAPI 크레딧 소모 0회 달성.
    2. 2차 시도 (ScraperAPI 프록시 우회):
       - 해외 IP(GitHub Actions 등)로 인해 403 차단, 방화벽 거부, 타임아웃 발생 시 즉시 ScraperAPI로 전환.
       - 한 번 차단이 감지되면(DIRECT_BLOCKED=True), 이후 식당 요청은 타임아웃 대기 없이 바로 프록시로 실행하여 속도 최적화.
    3. 최대 2회 지수 백오프 재시도로 일시적 네트워크 오류 극복.
    """
    global DIRECT_BLOCKED, DIRECT_REQUEST_COUNT, PROXY_REQUEST_COUNT

    for attempt in range(max_retries):
        # 1차: 직접 요청 시도 (이미 차단된 환경이 아니면 우선 시도)
        if not DIRECT_BLOCKED:
            try:
                res = session.get(target_url, timeout=8)
                if res.status_code == 200 and len(res.text) > 500:
                    DIRECT_REQUEST_COUNT += 1
                    return res
                if res.status_code in [403, 429, 503]:
                    print(f"[감지] 직접 요청 차단(HTTP {res.status_code}). 이후 요청은 ScraperAPI로 즉시 우회합니다.")
                    DIRECT_BLOCKED = True
            except Exception as e:
                if SCRAPER_KEY:
                    print(f"[감지] 직접 연결 불가({e}). 이후 요청은 ScraperAPI로 즉시 우회합니다.")
                    DIRECT_BLOCKED = True
                else:
                    print(f"[경고] 직접 연결 실패 ({attempt + 1}/{max_retries}): {e}")

        # 2차: ScraperAPI 프록시 요청
        if SCRAPER_KEY:
            try:
                PROXY_REQUEST_COUNT += 1
                proxy_url = f"https://api.scraperapi.com?api_key={SCRAPER_KEY}&url={quote(target_url)}&country_code=kr"
                res_proxy = session.get(proxy_url, timeout=25)
                if res_proxy.status_code == 200:
                    return res_proxy
                else:
                    print(f"[경고] ScraperAPI 응답 코드: {res_proxy.status_code}")
            except Exception as proxy_e:
                print(f"[경고] ScraperAPI 프록시 재시도 ({attempt + 1}/{max_retries}): {proxy_e}")

        if attempt < max_retries - 1:
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"HTML 요청 최종 실패: {target_url}")

def get_next_week_seldate(soup_main, now_kst):
    """
    메인 페이지 링크 중 다음주 버튼(b_nextweek.gif)의 selDate 파라미터를 추출하거나
    다음 주 월요일 날짜를 계산하여 반환
    """
    for a in soup_main.find_all("a", href=True):
        href = a["href"]
        if "selDate=" in href and any(img for img in a.find_all("img") if "nextweek" in img.get("src", "")):
            m = re.search(r"selDate=([\d\-]+)", href)
            if m:
                return m.group(1)
    # 폴백: 다음 주 월요일 날짜 계산
    days_ahead = 7 - now_kst.weekday()  # 일요일(6)이면 1일 뒤(월요일)
    next_monday = now_kst + timedelta(days=days_ahead)
    return next_monday.strftime("%Y-%m-%d")

def extract_days(soup):
    for tbl in soup.find_all("table"):
        cells = tbl.find_all(["th", "td"])
        found = []
        for c in cells:
            txt = c.get_text().strip().replace("\xa0", " ")
            if any(txt.startswith(d) for d in ["월", "화", "수", "목", "금", "토"]) and "(" in txt:
                found.append(txt)
        if len(found) >= 5:
            return found
    return []

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
    """
    지정된 sel_date(없으면 기본 이번 주) 기준으로 식당 목록을 순회하며 식단을 크롤링
    """
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

            cleaned_weekly = {}
            for d in days:
                cleaned_weekly[d] = {}
                for m in ["조식", "중식", "석식"]:
                    if weekly[d][m]["items"]:
                        cleaned_weekly[d][m] = weekly[d][m]

            all_shops_data[shop_name] = cleaned_weekly
            success_count += 1
            print(f"[수집 성공] {shop_name}")

        except Exception as e:
            print(f"[수집 실패] {shop_name}: {e}")
            all_shops_data[shop_name] = {}

    return all_days, all_shops_data, success_count, total_items_count

def main():
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    is_sunday = (now_kst.weekday() == 6)
    
    print(f"[실행 시각] {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (일요일 여부: {is_sunday})")

    # 1. 메인 페이지 로드 및 동적 식당 목록 추출
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
    
    # 2. 일요일인 경우: 다음 주 식단 우선 수집 시도
    if is_sunday and next_week_date:
        print(f"[시도] 일요일이므로 다음 주 식단 수집을 먼저 시도합니다 (selDate={next_week_date})...")
        days, data, sc_count, item_count = crawl_menus(shops, sel_date=next_week_date)
        
        # 다음 주 식단에 실제 등록된 메뉴가 유의미하게 존재하는지 확인 (예: 총 메뉴 수 10개 이상)
        if sc_count >= 2 and item_count >= 10:
            print(f"[성공] 다음 주 식단이 정상 등록되어 있습니다 (총 메뉴 {item_count}개).")
            all_days, all_shops_data = days, data
            is_next_week_loaded = True
        else:
            print(f"[미등록 감지] 다음 주 식단이 아직 등록되지 않았거나 비어있습니다 (메뉴 {item_count}개).")
            notice_message = "다음 주 식단이 아직 등록되지 않아 지난 식단 정보를 유지합니다."
            print("[폴백] 이전 식단(현재 기본 페이지)을 수집합니다...")
            all_days, all_shops_data, sc_count, _ = crawl_menus(shops, sel_date=None)
    else:
        # 평일 또는 토요일: 일반 수집
        all_days, all_shops_data, sc_count, _ = crawl_menus(shops, sel_date=None)

    # 3. 최소 유효성 검사 (너무 실패가 많으면 기존 menu.json 보호)
    if len(all_days) == 0 or sc_count < 2:
        print(f"[크롤링 중단] 유효 수집 식당 부족 ({sc_count}곳). 기존 menu.json을 유지합니다.")
        # 만약 이전 menu.json이 있다면 notice 메시지만 업데이트 시도
        if os.path.exists("menu.json") and notice_message:
            try:
                with open("menu.json", "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                old_data["notice"] = notice_message
                with open("menu.json", "w", encoding="utf-8") as f:
                    json.dump(old_data, f, ensure_ascii=False, indent=2)
                print("[알림] 기존 menu.json에 안내 문구(notice)를 추가했습니다.")
            except Exception as e:
                pass
        sys.exit(1)

    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "updated_at": now_str,
        "notice": notice_message,
        "is_next_week": is_next_week_loaded,
        "days": all_days,
        "shops": list(shops.keys()),
        "data": all_shops_data
    }

    with open("menu.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print("[크롤링 수집 통계 리포트]")
    print(f" - 수집 성공 식당: {sc_count}개")
    if PROXY_REQUEST_COUNT > 0:
        print(f" - 크롤링 방식: ScraperAPI 프록시 우회 (해외 IP 차단 대응)")
        print(f" - 소비한 ScraperAPI 토큰: {PROXY_REQUEST_COUNT}개 (월 5,000회 제한)")
    else:
        print(f" - 크롤링 방식: 로컬 직접 요청 (Direct Fetch)")
        print(f" - 소비한 ScraperAPI 토큰: 0개 (토큰 소모 없음)")
    if DIRECT_REQUEST_COUNT > 0:
        print(f" - 직접 요청 성공 횟수: {DIRECT_REQUEST_COUNT}회")
    print(f" - 데이터 갱신 시각: {now_str}")
    if notice_message:
        print(f" - 안내 상태: {notice_message}")
    print("=" * 55)

if __name__ == "__main__":
    main()