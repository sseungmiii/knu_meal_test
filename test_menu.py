import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://coop.knu.ac.kr/sub03/sub01_01.html"

# 고정 식당 ID 맵 (학교 방화벽으로 메인 메뉴 목록이 안 긁힐 때 대비)
DEFAULT_SHOPS = {
    "정보센터식당": "35",
    "복지관 교직원식당": "36",
    "카페테리아 첨성": "37",
    "GP감꽃식당": "46",
    "공학관교직원식당(외부업체)": "85",
    "공학관학생식당(외부업체)": "86"
}

# 실제 Chrome 브라우저 완벽 위장 헤더
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://coop.knu.ac.kr/",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

session = requests.Session()
session.headers.update(headers)

# 1. 식당 목록 파싱 (실패 시 DEFAULT_SHOPS 사용)
shops = {}
try:
    res_main = session.get(f"{BASE_URL}?shop_sqno=35", timeout=15)
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
except Exception as e:
    print(f"[경고] 메인 식당 목록 조회 실패: {e}")

if not shops:
    print("[알림] 기본 식당 ID 맵으로 대체 진행합니다.")
    shops = DEFAULT_SHOPS

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

all_shops_data = {}
all_days = []
success_count = 0

for shop_name, shop_id in shops.items():
    url = f"{BASE_URL}?shop_sqno={shop_id}"
    time.sleep(0.5)  # 방화벽 연속 호출 제한(Rate Limit) 회피용 딜레이
    try:
        res = session.get(url, timeout=15)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")

        # 첫 번째 식당에서 본문 상태 디버깅 출력
        if shop_name == "정보센터식당":
            print(f"[디버그] {shop_name} 응답 코드: {res.status_code}, 본문 길이: {len(res.text)}")
            print(f"[디버그 9625바이트 제목] {soup.title.string.strip() if soup.title and soup.title.string else '제목없음'}")
            print(f"[디버그 9625바이트 텍스트 요약] {' '.join(soup.get_text().split())[:300]}")
            print(f"[디버그 본문 앞 300자] {res.text[:300]}")

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

if len(all_days) == 0 or success_count < 2:
    print(f"[테스트 실패] 데이터 부족(성공: {success_count}곳). test_menu.json 저장을 중단합니다.")
    sys.exit(1)

kst = timezone(timedelta(hours=9))
now_str = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")

result = {
    "updated_at": now_str,
    "days": all_days,
    "shops": list(shops.keys()),
    "data": all_shops_data
}

with open("test_menu.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\n[테스트 완료] 총 {success_count}개 식당 수집 성공. test_menu.json 갱신 완료 ({now_str})")
