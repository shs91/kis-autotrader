# 변경 이력

> Claude Code가 제안서를 구현할 때마다 이 파일에 기록합니다.
> 제안서 경로: docs/proposals/

---

## [2026-04-03] T2-1 웹 대시보드 (Streamlit)
- 신규 파일: dashboard/app.py, scripts/run_dashboard.sh
- 기능: 시스템 상태, 보유 포트폴리오, 일일 성과 차트, 최근 주문 내역
- 헬스체크 API + PostgreSQL 직접 조회
- 실행: .venv/bin/streamlit run dashboard/app.py (포트 8501)
- 테스트: 188 passed (기존 테스트 영향 없음)

## [2026-04-03] T2-4 Telegram 원격 명령
- 신규 파일: src/notify/bot.py, tests/test_notify/test_bot.py
- 변경 파일: main.py
- 명령: /status (시스템 상태), /balance (잔고), /today (당일 현황), /help
- getUpdates 롱 폴링, chat_id 검증, 명령 핸들러 패턴
- 테스트: 188 passed (신규 5건)

## [2026-04-03] T2-3 알림 레벨 분류
- 변경 파일: src/notify/telegram.py, tests/test_notify/test_telegram.py
- 긴급(손절, 에러) → 소리/진동 알림, 일반(체결, 결산) → 무음 전송
- Telegram disable_notification 파라미터 활용
- 테스트: 183 passed (신규 2건)

## [2026-04-03] T1-4 프로세스 행 감지 + 자동 재시작
- 로드맵: docs/plans/feature-roadmap.md (T1-4)
- 신규 파일: scripts/watchdog.sh
- 기능: 로그 미갱신 5분 초과 시 hang 판단, launchctl 재시작, Telegram 알림
- 장중 시간(09:00~15:25)에만 동작, 평일 5분마다 crontab 실행

## [2026-04-03] T1-3 DB 자동 백업 구현
- 로드맵: docs/plans/feature-roadmap.md (T1-3)
- 신규 파일: scripts/backup_db.sh
- 기능: Docker exec pg_dump → gzip 압축, 7일 롤링 보관, crontab 매일 04:00 실행
- crontab 등록 완료

## [2026-04-03] T1-2 헬스체크 API 구현
- 로드맵: docs/plans/feature-roadmap.md (T1-2)
- 신규 파일: src/api/health.py
- 변경 파일: src/config.py, main.py
- 기능: asyncio 기반 경량 HTTP 서버, GET /health 엔드포인트 (DB, 스케줄러, API 호출량 상태)
- 외부 패키지 추가 없음 (표준 라이브러리만 사용)
- 테스트: 181 passed (신규 4건)

## [2026-04-03] T1-1 Telegram 알림 기능 구현
- 로드맵: docs/plans/feature-roadmap.md (T1-1)
- 신규 파일: src/notify/__init__.py, src/notify/telegram.py, src/notify/formatter.py
- 변경 파일: src/config.py, src/engine.py, main.py
- 기능: 매수/매도 체결, 손절, 일일 결산, 에러, 시스템 시작/종료 Telegram 알림
- 테스트: 177 passed (신규 20건)

## [2026-04-03] KIS API 호출 제한 정책 최신화 (2026년 기준)
- 변경 파일: .env, src/config.py, src/api/rate_limiter.py, src/api/websocket.py
- 수정 내용:
  - 초당 호출 제한을 KIS 최신 정책에 맞게 수정 (모의=5건/초, 실전=20건/초)
  - MIN_CALL_INTERVAL을 하드코딩에서 초당 호출 수 기반 동적 계산으로 변경
  - 웹소켓 구독 종목 수 상한 41개 추가 (KIS 세션당 제한)
  - 일일 호출 한도 10,000 → 50,000으로 상향 (KIS 공식 일일 한도 없음, 안전장치)
- 테스트: 157 passed

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
