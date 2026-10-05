# 경북대학교 학식

두 화면이 하나의 크롤러와 식단 데이터를 공유합니다.

- `/index.html`: 기본 화면
- `/test_2/index.html`: 식당 필터·가격 배지가 있는 개선 화면
- `/get_menu.py`: 공통 수집기
- `/menu.json`: 공통 데이터, 식단 갱신·점검 시각과 수집 상태
- `/meal-status.js`: 두 화면의 상태 표시와 한국 시간 날짜 계산
- `/test_2/get_menu.py`: 기존 실행 명령을 지원하는 공통 수집기 진입점

`test_2` 디렉터리와 별도 `test_2` 브랜치는 다릅니다. 배포·자동 수집은 main 브랜치를 기준으로 합니다.

## 실행

`python -m pip install -r requirements.txt`

`python -m http.server 8080`

`python get_menu.py`

`python -m unittest discover -s tests -v`

SCRAPER_API_KEY가 있으면 무효 직접 응답을 프록시로 재시도합니다. 식단 수집 실패 시 기존 식단과 updated_at을 보존하고 last_checked, crawl_status, 안내 문구를 갱신하며 종료 코드 1을 반환합니다.

자동화는 매일 한국 시간 06:23에 실행하도록 예약되어 있습니다. GitHub 실행 지연이 발생할 수 있습니다. 관련 코드 변경 시에도 실행합니다. 단일 워크플로를 직렬화하고 push 직전에 rebase해 다른 커밋과의 충돌을 줄입니다. 실패 상태도 저장한 뒤 Actions 실패를 표시합니다.

추가 분석: docs/repository-analysis.md
