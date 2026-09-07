import json
import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://coop.knu.ac.kr/sub03/sub01_01.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

res_main = requests.get(f"{BASE_URL}?shop_sqno=35", headers=headers, timeout=5)
res_main.encoding = "utf-8"
soup_main = BeautifulSoup(res_main.text, "html.parser")

shops = {}
for a in soup_main.find_all("a", href=True):
    href = a["href"]
    if "shop_sqno=" in href:
        m = re.search(r"shop_sqno=(\d+)", href)
        if m:
            name = a.get_text().strip()
            if name and "ENGLISH" not in name and name not in shops:
                shops[name] = m.group(1)

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
# 가격 정규식: ₩ 뒤 공백 및 쉼표 포함 숫자 전체 매칭
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
    # 별표, 불필요 특수문자 제거
    t = text.replace("★", "").replace("☆", "").replace("*", "")
    # 숫자 사이의 쉼표는 보존하고, 일반 쉼표만 공백 처리
    t = re.sub(r"(?<!\d),(?!\d)", " ", t)
    t = re.sub(r"\s*&\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def parse_cell(td_el):
    raw_lines = [l.strip() for l in td_el.get_text(separator="\n").split("\n") if l.strip()]
    raw_lines = [l for l in raw_lines if l not in ["분류", "코너", "조식", "중식", "석식"]]
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
            menu_combined = " ".join(curr_tokens)
            items.append(menu_combined)
            curr_tokens = []

    if curr_tokens:
        items.append(" ".join(curr_tokens))

    return [{
        "meal": meal,
        "time": cell_time,
        "items": items
    }]

all_shops_data = {}
all_days = []

for shop_name, shop_id in shops.items():
    url = f"{BASE_URL}?shop_sqno={shop_id}"
    try:
        res = requests.get(url, headers=headers, timeout=5)
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

        cleaned_weekly = {}
        for d in days:
            cleaned_weekly[d] = {}
            for m in ["조식", "중식", "석식"]:
                if weekly[d][m]["items"]:
                    cleaned_weekly[d][m] = weekly[d][m]

        all_shops_data[shop_name] = cleaned_weekly
        print(f"[수집 성공] {shop_name}")

    except Exception as e:
        print(f"[수집 실패] {shop_name}: {e}")
        all_shops_data[shop_name] = {}

result = {
    "days": all_days,
    "shops": list(shops.keys()),
    "data": all_shops_data
}

with open("menu.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("\n전체 식당 파싱 완료: menu.json 최신화 성공")
