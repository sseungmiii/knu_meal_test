# 학식 개발 규칙

- 이 폴더는 `sseungmiii/knu_meal_test`의 독립 저장소다. 상위 작업 공간과 다른 앱은 수정하지 않는다.
- main은 운영 기준. 큰 변경은 codex/feature-*에서 검사·diff 검토 후 main에 반영한다. 기존 변경을 덮어쓰거나 강제 push하지 않는다.
- 수집기는 `__file__` 기준의 루트 menu.json 하나만 갱신한다. 운영 데이터 원본 경로 main/menu.json을 유지하고 샘플/오래된 로컬 데이터로 덮어쓰지 않는다.
- 학식 화면과 크누패스는 동일한 공개 원본 URL을 사용한다. 크누패스의 별도 저장소 파일 경로를 직접 읽지 않는다.
- 수집은 GitHub Actions에서 실행한다. SCRAPER_API_KEY는 Actions Secret에만 두고 문서/로그/브라우저에 출력하지 않는다.
- 실패 시 기존 식단 보존·원자적 저장·주간 검증·수집 상태 표시를 유지한다. 정기 수집과 실시간 데이터를 혼동하지 않는다.
- 검사: `python -m unittest discover -s tests -v`, `node tests/test_meal_status.cjs`, `node scripts/build-static.cjs`, `node --test tests/test_data_contract.cjs`.
- Vercel은 public 출력만 배포한다. .env·Python 소스·테스트·백업을 공개 출력에 넣지 않는다. public은 생성물이며 직접 수정하지 않는다.
- 완료 시 변경 내용, 검사, 실제 배포/데이터 갱신 여부, Git 상태와 미확인 사항을 보고한다.
