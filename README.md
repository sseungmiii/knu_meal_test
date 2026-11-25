# 경북대학교 학식

개선된 test2 화면을 메인으로 통합한 학식 사이트입니다. 기존 `/test_2/` 주소는 메인으로 이동합니다.

## 데이터 원본

`get_menu.py`는 파일이 있는 폴더의 `menu.json` 하나만 갱신합니다. GitHub Actions가 main에 반영하며 아래 공개 원본을 학식 화면과 크누패스가 함께 읽습니다.

`https://raw.githubusercontent.com/sseungmiii/knu_meal_test/main/menu.json`

로컬 폴더명이 knu-meals로 바뀌어도 원격 저장소명과 이 경로는 유지됩니다. PC의 로컬 수집 결과가 자동으로 서버에 전송되는 것은 아닙니다. 로컬 실행은 해당 체크아웃의 JSON만 변경하며, 운영 갱신은 GitHub Actions가 담당합니다.

첫 점검은 한국 시간 02:47에 예약합니다. 이번 주 월~금 식단이 기본 6개 식당과 기존 등록 식당에 모두 들어 있으면 저장 파일을 확인한 뒤 수집을 건너뜁니다. 원본과 ScraperAPI를 모두 호출하지 않고 마지막 실제 점검 시각도 유지합니다. 토·일 메뉴가 없다는 이유로 이미 등록된 평일 식단을 다시 수집하지 않습니다.

지난 주 데이터이거나, 식당 또는 평일 메뉴가 비어 있으면 수집합니다. 결측이 계속되면 03:47·04:47·05:47에 미완료 식당을 최대 세 번 재시도합니다. 예약 지연과 원본 게시 시각에 따라 07:00을 넘길 수 있습니다. 일요일은 이번 주 데이터가 불완전할 때 기존 다음 주 선조회 동작을 유지합니다. 원본에 식단과 구분되는 휴무 표시가 없으면 휴무인 평일도 결측으로 처리될 수 있습니다.

직접 요청이 유효하지 않을 때만 URL당 프록시를 한 번 요청합니다. 식당 탐색에 쓴 응답은 같은 수집에서 재사용합니다. 이미 완료된 회차는 요청 없이 끝나고 코드 푸시는 검증만 실행합니다. Actions 로그의 직접/프록시 요청 횟수 및 `menu.json`의 `collection.pending`, `collection.proxy_requests`로 운영을 평가할 수 있습니다. 프록시 요청 횟수는 공급자 청구 크레딧과 다를 수 있습니다. main에서 수동 실행도 지원합니다. 실시간 수집은 아닙니다. 크누패스는 추가로 캐시를 사용합니다. 수집 실패 시 기존 식단을 보존하고 갱신 시각과 점검 시각을 구분합니다.

## 실행과 검사

Python 3.11+와 Node 22+를 사용합니다.

```text
python -m pip install -r requirements.txt
python -m http.server 8080
python -m unittest discover -s tests -v
node tests/test_meal_status.cjs
node scripts/build-static.cjs
node --test tests/test_data_contract.cjs
```

브라우저는 `http://localhost:8080/`을 엽니다. 로컬 화면도 운영 원본을 읽습니다. 실제 수집기를 로컬에서 실행하려면 `python get_menu.py`를 사용합니다. SCRAPER_API_KEY는 필요할 때 로컬 환경 또는 GitHub Actions Secret으로만 관리하며 코드·로그에 넣지 않습니다.

## Vercel / GitHub Pages

Vercel은 Other, 저장소 루트, `node scripts/build-static.cjs`, Output Directory `public`을 사용합니다. 정적 출력에는 화면·공개 설정·상태 스크립트·기존 주소 이동 안내만 포함합니다. `/menu.json`은 공개 원본으로 프록시되어 배포 시점의 오래된 복사본을 만들지 않습니다. 정적 Vercel에는 수집용 비밀 키가 필요하지 않습니다.

GitHub Pages도 main을 사용하며, 루트 화면이 같은 원본 URL을 읽습니다. menu.json이 갱신되면 화면 재배포 없이 새 조회에 반영됩니다(상위 CDN 및 앱 캐시 지연 가능).

## 파일

- `index.html`: 통합 메인 화면
- `meal-config.js`: 두 서비스가 공유하는 공개 데이터 URL
- `meal-status.js`: 한국 시간·식단 상태 표시
- `get_menu.py`, `menu.json`: 수집기와 유일한 원본 데이터
- `.github/workflows/crawler.yml`: 검증과 정기 수집
- `scripts/build-static.cjs`, `vercel.json`: 공개 출력과 배포 설정
- `tests/`: 수집 회귀·상태·공개 데이터 경로 검사
- `test_2/index.html`, `test_2/get_menu.py`: 이전 URL/실행 명령 호환
