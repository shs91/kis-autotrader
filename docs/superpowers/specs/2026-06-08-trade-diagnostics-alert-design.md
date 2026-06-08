# 장 마감 매매 진단 알림 (C) 설계

- 날짜: 2026-06-08
- 상태: 승인됨 (사용자 승인 2026-06-08)
- 범위: 옵션 C(관측성 보강) — 매매 로직 무변경, 알림 추가만
- 관련: `[[project_zero_trades_diagnosis]]`, `[[project_screening_filter_bypass]]`, `[[project_signals_ingestion_halt]]`

## 1. 배경 / 목적

2026-06-08 진단 결과, 시스템은 정상 가동 중이나 매매가 구조적으로 멈춰 있다(누적 체결 2건, 6/2 이후 신규 매수 0). 텔레그램은 **실제 체결·일일결산만** 알리므로(시그널 알림 함수 없음), 운영자는 "왜 매매가 없는지"를 알 수 없다.

C의 목적: **장 마감 후 1회**, "오늘 왜/얼마나 매매했나(또는 안 했나)"를 텔레그램으로 가시화한다. 이는
1. 매매 정지가 "정상 보수화"인지 "버그"인지 운영자가 매일 판별할 계기판이 되고,
2. 이후 A-1(스크리닝 완화)·B(stale 만료) 튜닝의 **효과 측정 기준선**이 된다.

## 2. 비범위 (YAGNI)

- 장중 주기 하트비트, 이벤트 트리거 즉시 알림, 봇 온디맨드 명령(`/why`) — 이번 C 아님
- 매수 차단 사유 메트릭 신규 추가 — 이미 `_record_buy_reject`가 기록 중(§5)
- 매매 파라미터(`SCREENING_MIN_SCORE`, `STRATEGY_MIN_CONFIDENCE`) 변경 — A 영역, 별도 작업

## 3. 데이터 흐름

```
post_market_job (15:40, 휴장일 가드 有)
  → engine.post_market()
      → 기존 결산 enqueue (engine.py:683, _enqueue_telegram_daily_summary)
      → [신규] _enqueue_telegram_diagnostics(...)
          → worker queue: telegram_notify task, notify_type="diagnostics"
              → worker handler 동적 디스패치 getattr(notifier, "notify_diagnostics")
                  → TelegramNotifier.notify_diagnostics(diag)
                      → format_diagnostics(diag) → send()
```

결산 메시지 **직후 별도 1건**으로 전송된다(하루 1회, 노이즈 0).

## 4. 변경 컴포넌트 (4곳, 모두 기존 패턴 재사용)

| # | 파일 | 추가 | 담당 영역 |
|---|------|------|-----------|
| 1 | `src/db/analytics.py` | `build_daily_diagnostics(session, target_date) -> DailyDiagnostics` (읽기전용 집계) | db-scheduler-engineer (구현 시 위임 검토) |
| 2 | `src/notify/formatter.py` | `format_diagnostics(diag: DailyDiagnostics) -> str` (순수 함수) | team lead |
| 3 | `src/notify/telegram.py` | `async notify_diagnostics(diag: DailyDiagnostics) -> None` | team lead |
| 4 | `src/engine.py` | `_enqueue_telegram_diagnostics(diag/balance)` post_market 결산 직후 호출 | team lead |

> 모듈 경계: §1 집계는 db 영역. 읽기전용 단순 집계이나 인터페이스 추가이므로, 구현 시 db-scheduler-engineer 위임 또는 합의. 나머지 2~4는 team lead 영역(직접).

## 5. 진단 dict ↔ 데이터 소스

집계 대상은 **당일(KST) `system_metrics` + `trades` + 전달받은 `balance`**. `signals` 테이블은 사용하지 않는다(§8 참조).

| 진단 항목 | 소스 metric_type / 데이터 | 산출 |
|-----------|---------------------------|------|
| 한 줄 진단 | 파생 규칙 | 체결>0 → "매매 N건 — 정상"; 아니면 발굴0/max_conf<min_conf 조합으로 사유 문자열 |
| 모니터링 N + 종목 | `EVAL_TARGETS`(targets, counts) | 당일 마지막 레코드의 targets |
| 종목별 max_conf | `SIGNAL_SUMMARY`(max_confidence) | 당일 max(앙상블 confidence) |
| 스크리닝 top30→후보 N | `SCREENING_CANDIDATE`(ranked_total, candidate_count) | max(ranked_total), avg(candidate_count) |
| 위험배제 | `SCREENING_RISK_EXCLUDED`(codes) | 당일 distinct codes |
| 매수게이트 차단 분포 | `BUY_REJECT` 메트릭 (engine.py:2077, `detail.reason`) | reason별 count (DAILY_TRADE_LIMIT / DAILY_TRADE_LIMIT_PER_STOCK / 저신뢰 / 잔고 / 위험 / 가격하한) |
| 예수금·보유 | `balance` (post_market 보유) | 그대로 |

> 매수 차단은 `engine.py:2040 _record_buy_reject` → `_record_metric("BUY_REJECT", detail)`로 이미 기록된다. `detail.reason`을 집계 키로 사용한다. 신규 메트릭 추가 불필요.

## 6. 메시지 포맷 (승인된 mockup, 매매 0건 예시)

```
🔭 [매매 진단] 2026-06-08
🚫 매매 0건 — 발굴 부족 + 모니터링 전원 HOLD

📡 모니터링 2종목 (보유0/발굴2)
  • 027360 아주IB투자 — HOLD 0.00
  • 036170 에이치엠넥스 — HOLD 0.00

🔍 스크리닝 top30 → 후보 0 (avg 0.08/사이클)
  • 위험배제 1종목 (271830)

⛔ 매수게이트: 신호 0이라 도달 전 차단
  · 일일한도0 · 종목한도0 · 예수금부족0 · 위험0

💰 예수금 449,947원 · 보유 0종목
```

- 체결>0인 날: 헤더를 `📈 [매매 진단] … 매매 N건 — 정상`으로, 차단 분포는 유지(아까운 기회 가시화).
- HTML 파싱 모드(`<b>` 등)는 기존 formatter 관례를 따른다.

## 7. 엣지 케이스

| 상황 | 처리 |
|------|------|
| 휴장일 | `post_market_job` 가드로 자동 스킵(진단도 미전송) |
| 체결 > 0 | 한 줄 진단 "정상", 차단 분포 유지 |
| 당일 메트릭 없음 | "데이터 없음" 안전 출력 |
| 집계/포맷 예외 | `post_market` try/except 내부 → 매매·결산에 무영향, 로그만 |
| 텔레그램 전송 실패 | 기존 `send()`의 urgent fallback(`_write_urgent_fallback`) 재사용 |

## 8. 데이터 소스 신뢰성 노트

- `system_metrics`는 **건강**하다: 2026-06-08 당일 `SIGNAL_SUMMARY` 14,517건 등 정상 적재 확인.
- `signals`(6/3 이후 0건)·`event_logs` 적재 공백 이슈(`[[project_signals_ingestion_halt]]`)와 **독립적**이다. C는 `signals`를 읽지 않는다.
- 따라서 C는 안전한 소스 위에 서며, 오히려 향후 그런 적재 공백을 진단 메시지로 드러낼 수 있다.

## 9. 테스트 (TDD, 외부 API mock)

| 테스트 | 위치 | 검증 |
|--------|------|------|
| `format_diagnostics` 스냅샷 | `tests/test_notify/` | 0건 / N건 / 빈데이터 3케이스 (순수 함수) |
| `build_daily_diagnostics` | `tests/test_analytics.py` | SQLite in-memory에 메트릭 시드 → 집계값 검증 |
| `notify_diagnostics` | `tests/test_notify/` | `send` mock, 호출 인자·HTML 검증 |
| worker 라우팅 | `tests/test_*` | `notify_type="diagnostics"` 디스패치 검증 |

## 10. 검증·기록

- `pytest tests/ && mypy src/ && ruff check src/` 통과
- `scripts/record_implementation.py` 실행 + `docs/CHANGELOG.md` rolling 갱신
- README/.env 영향 없음(신규 환경변수 없음) — 단 알림 종류 추가는 README "Telegram" 섹션에 1줄 반영 검토
