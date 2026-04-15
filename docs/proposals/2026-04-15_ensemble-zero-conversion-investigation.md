# ENSEMBLE 시그널 매매 전환율 0% 원인 조사

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-15
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py, src/strategy/ensemble.py, src/strategy/selector.py

## 현상 분석

2026-04-10 구현된 `default-strategy-to-ensemble` 제안서 이후 ENSEMBLE signal_type이 DB에 기록되기 시작했으나, **매매 전환율이 2일 연속 0%** 를 기록 중이다.

### DB 근거 (쿼리 결과)

**오늘(2026-04-15 KST) — 쿼리 4**

| signal_type | total | acted | act_rate_pct | avg_confidence |
|-------------|-------|-------|--------------|----------------|
| ENSEMBLE | 4,400 | 0 | 0.0% | 0.208 |

**최근 7일 rolling — signals 테이블**

| date (KST) | signal_type | total | acted | avg_conf |
|------------|-------------|-------|-------|----------|
| 2026-04-15 | ENSEMBLE | 4,400 | 0 | 0.208 |
| 2026-04-14 | ENSEMBLE | 1,503 | 0 | 0.256 |
| 2026-04-14 | GOLDEN_CROSS | 299 | 1 | 0.115 |
| 2026-04-10 | GOLDEN_CROSS | 1,083 | 1 | 0.426 |
| 2026-04-09 | GOLDEN_CROSS | 3,387 | 2 | 0.082 |

7일간 ENSEMBLE 누적: **5,903건 발생 / 0건 전환 (0.00%)**, 평균 confidence 0.220.

### 신뢰도 분포 확인 (오늘)

| confidence 구간 | 건수 | 비율 |
|-----------------|------|------|
| ≥ 0.10 (MIN_CONFIDENCE 기본값) | 4,400 | 100% |
| ≥ 0.15 | 3,179 | 72.3% |
| ≥ 0.20 | 2,423 | 55.1% |
| ≥ 0.25 | 903 | 20.5% |

MIN_CONFIDENCE=0.1 을 전량 통과하며, 그 2.5배인 0.25 이상만 추려도 903건이 남는다. **신뢰도 임계값 문제는 원인이 아닌 것으로 보인다.**

### 병행 관찰

- 오늘 실제 체결 3건 중 SELL 1건은 리스크 게이트(TAKE_PROFIT), BUY 2건은 `buy_reason` NULL로 앙상블 연계가 확인되지 않는다.
- 2026-04-10 이전 GOLDEN_CROSS 전환율도 0.07% 수준으로 낮았으나, 당시에는 signal_type에 GOLDEN_CROSS가 찍힌 체결이 존재했다. ENSEMBLE은 **완전 0**이라는 점이 질적으로 다르다.
- API 한도·에러·사이클 완료율은 정상 (1,030/1,034, ERROR 0, API_LIMIT 0). 인프라 장애는 아님.

## 제안 내용

ENSEMBLE 시그널이 generation 단계를 넘어 engine 주문 파이프라인까지 전달·집행되는 경로에서 어디에서 차단되고 있는지 로깅을 강화해 원인 구간을 좁힌다. 파라미터 튜닝이 아닌 **관측 가능성(observability) 개선**이 1차 목표이며, 원인 구간 식별 후 후속 제안서에서 실제 수정을 진행한다.

현 시점에서 의심되는 후보 구간은 다음과 같다 — 본 제안은 그 중 어느 구간이 원인인지를 데이터로 특정하는 것이 목적이다.

1. `src/engine.py`의 시그널 → 주문 변환 루프에서 ENSEMBLE 시그널을 HOLD/SKIP으로 조기 필터링하는 분기 존재 여부
2. `src/strategy/ensemble.py`의 최종 Signal action이 항상 HOLD로 수렴 (투표 동률/미달 처리)
3. 포지션·예산 게이트에서 ENSEMBLE 경로만 `InsufficientBalanceError`·`MAX_POSITION_RATIO` 등으로 배제
4. selector 또는 registry에서 ensemble 생성 시 BUY/SELL action이 빈 값으로 채워진 채 저장

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:
  - 시그널 처리 루프에서 신호가 주문 호출 직전까지 도달했는지 여부를 DEBUG 레벨로 기록 (이미 있는 경우 레벨 상향). 분기별 skip 사유(예: `"below_confidence"`, `"hold_action"`, `"position_cap"`, `"budget"`, `"duplicate"`)를 `signals.meta` JSON 필드에 기록 또는 `event_logs`에 `category='signal_skip'`, `level='INFO'` 로 append.
  - 변경 함수 시그니처 없음 — 로그/메타 기록만 추가.

- `src/strategy/ensemble.py`:
  - 투표 결과가 HOLD로 결론난 경우 내부 투표 집계(각 sub-strategy의 action, weight)를 Signal.meta에 기록.

- `tests/test_strategy/test_ensemble.py` (또는 기존 테스트 파일):
  - HOLD 수렴 케이스에 대해 투표 meta가 채워지는지 단위 테스트 추가.
  - 기존 signature를 건드리지 않는 순수 기록 로직이면 기존 테스트는 그대로 통과해야 한다.

### 추가 테스트

- `tests/test_engine_db_integration.py`에 "ENSEMBLE 시그널이 주문 파이프라인을 통과하지 못할 때 skip 사유가 DB에 기록된다"는 통합 테스트 1개.

변경 파일 총 3~4개로 BRIDGE_SPEC의 5개 한도 이내.

## 기대 효과

- 내일(2026-04-16) 리포트부터 skip 사유별 분포를 집계할 수 있어, ENSEMBLE 0% 전환의 원인 구간이 1~2일 내에 데이터로 특정된다.
- 원인이 (a) 투표 로직이면 ensemble.py 조정 제안서, (b) 리스크/포지션 게이트면 engine.py 조정 제안서, (c) confidence 문제면 STRATEGY_MIN_CONFIDENCE 튜닝으로 연결 가능하다.
- 본 제안 자체는 매매 성과 지표(승률·손익)를 직접 개선하지 않으나, 다음 성과 개선 제안의 근거를 제공한다.

## 롤백

- `src/engine.py`, `src/strategy/ensemble.py`의 추가 로깅/메타 코드를 제거.
- 추가된 테스트 케이스 삭제.
- `config_overrides.json`에는 영향 없음.
- `git restore` 범위: 위 3개 파일 + 테스트 파일.
