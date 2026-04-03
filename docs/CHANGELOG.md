# 변경 이력

> Claude Code가 제안서를 구현할 때마다 이 파일에 기록합니다.
> 제안서 경로: docs/proposals/

---

## [2026-04-03] API 일일 한도 초과 대응 수정
- 변경 파일: src/engine.py, src/strategy/moving_average.py
- 원인: 스크리닝 발굴 종목이 무제한 증가하여 API 호출량 폭증 + 한도 초과 후에도 스케줄러가 계속 실행
- 수정 내용:
  - `_daily_limit_reached` 플래그 도입: 한도 초과 시 이후 사이클 즉시 중단 (다음 장 시작 시 초기화)
  - 스크리닝 발굴 종목 상한(`MAX_SCREENED_STOCKS=15`) 추가하여 API 호출량 제어
  - 이동평균 전략 괴리율 계산 시 0 나누기 방어 코드 추가
- 테스트: 157 passed

## [2026-04-03] 스크리닝 간격 최적화
- 제안서: docs/proposals/2026-04-03_스크리닝_간격_최적화.md
- 테스트: PASS
- 자동 구현 완료

## [2026-04-03 03:21] 잔고 캐시 TTL 조정
- 제안서: docs/proposals/2026-04-03_잔고캐시_TTL_조정.md
- 변경 파일: src/engine.py
- 테스트: PASS
- 재시작: 예정
