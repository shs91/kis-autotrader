# 매수 게이트 진단 메트릭 신설 — 시그널→매수 전환 0% anomaly 분해

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-18
- 상태: implemented
- 우선순위: high
- 카테고리: performance
- 관련파일: src/engine.py, src/strategy/risk.py

## 현상 분석

### 오늘(2026-05-18) anomaly 관찰
| 일자 | ENSEMBLE 시그널 | acted (매수) | avg_conf | max_conf | p50_conf | MIN_CONFIDENCE 통과 추정 |
|------|-----------------|--------------|----------|----------|----------|--------------------------|
| 2026-05-18 | 1,824 | **0** | 0.256 | **0.330** | 0.227 | 상당수 (max > 0.20) |
| 2026-05-15 | 1,092 | 336 | 0.221 | 0.250 | 0.207 | 일부 |
| 2026-05-14 | 5,025 | 3 | 0.267 | 0.322 | 0.279 | 다수 |

- 오늘 시그널 max=0.330으로 현재 `STRATEGY_MIN_CONFIDENCE=0.20`을 충분히 초과하는 시그널이 다수 존재했음.
- 직전 거래일(5/15)에는 동일 수준(max=0.250) 시그널에서도 336건 매수가 발생했으나 오늘은 0건.
- 시그널 발생량·품질 차이만으로는 설명되지 않는 매수 차단 — **시그널이 매수 게이트(잔고/포지션/리스크 룰) 단계에서 차단되고 있을 가능성이 매우 높다.**

### 문제 — 매수 거절 사유 측정 불가
현재 시스템은 매수 의사결정 과정에서 어떤 단계에서 차단되었는지 별도로 기록하지 않는다:

1. **`src/engine.py`의 매수 의사결정 흐름**: 시그널 발생 → confidence 임계값 체크 → 포지션 한도 체크 → 잔고 체크 → 일일 한도 체크 → 주문 실행. 각 단계의 거절 카운터가 없다.
2. **`src/strategy/risk.py`의 리스크 게이트**: `MAX_DAILY_DRAWDOWN`, `MAX_CONSECUTIVE_LOSSES` 등 트립 시 매매 차단되지만 차단 사실이 system_metrics에 기록되지 않는다.
3. `event_logs`에는 WARNING 로그가 남을 수 있으나, 카테고리·집계가 불일치해 룰 엔진에서 활용 불가.

결과적으로 룰 A(시그널 전환율 저하) 트리거 시 무엇을 조정해야 할지 판단 불가 — MIN_CONFIDENCE 무차별 상향은 매매 위축을 가속할 위험.

### 5-15 진단 메트릭과의 관계
- 5-15에 도입된 `SCREENING_CANDIDATE` / `SCREENING_HIT` / `SCREENING_MISS`는 **스크리닝→매수** 매핑 측정용.
- 본 제안의 `BUY_REJECT_{REASON}`은 **시그널→매수** 게이트 측정용으로 직교 관계. 둘이 함께 누적되면 워커/엔진/리스크 어느 단계가 병목인지 완전 분해 가능.

## 제안 내용

매수 시도 단계마다 거절 사유를 `system_metrics`에 `BUY_REJECT_{REASON}` 형태(또는 통합 metric_type `BUY_REJECT` + detail의 reason 필드)로 기록한다. 임계값 무차별 조정 전에 거절 원인 분포부터 측정해야 한다.

### 기록 대상 거절 사유 (최소 6종)
| reason 코드 | 의미 |
|-------------|------|
| `LOW_CONFIDENCE` | 시그널 confidence < `STRATEGY_MIN_CONFIDENCE` |
| `POSITION_LIMIT` | 보유 포지션 수가 `MAX_POSITIONS`/`MAX_SCREENED_STOCKS` 한도 도달 |
| `POSITION_RATIO` | 종목 매수 금액이 `MAX_POSITION_RATIO` 초과 |
| `INSUFFICIENT_CASH` | 매수 가능 현금 부족 |
| `DAILY_TRADE_LIMIT` | 당일 매매 횟수가 `DAILY_TRADE_LIMIT` 도달 |
| `RISK_GATE` | `MAX_DAILY_DRAWDOWN` / `MAX_CONSECUTIVE_LOSSES` 등 리스크 게이트 트립 |

기타 사유는 `OTHER`로 통합 기록(detail에 메시지 보존).

## 변경 스펙

### 파일별 변경사항

#### 1. `src/engine.py`
- 매수 의사결정 함수(시그널 평가 → 매수 주문 호출 사이) 내부의 각 거절 분기에 `system_metrics` 기록을 1줄씩 삽입.
- 기록 형식: `metric_type='BUY_REJECT'`, `detail={"cycle": cycle, "stock_code": code, "reason": <code>, "confidence": <float|null>, "context": {...}}`.
- 기존 `SystemMetricRepository.record_metric` 또는 `engine.py` 내 기존 system_metric 기록 경로 재사용 (5-13 fix 이후 timezone-aware 보장됨).
- 기록 실패 시 `logger.exception` 후 매매 본 흐름은 계속 진행(매매 차단 절대 금지 — fallback 원칙).
- 신규 import 최소화 (이미 SystemMetricRepository 사용 중인 모듈로 가정. 미사용 시 import 추가).

#### 2. `src/strategy/risk.py`
- `RiskManager`의 게이트 메서드(예: `is_blocked_by_drawdown`, `is_blocked_by_consecutive_losses` 등)가 차단을 반환할 때, 차단 사유 문자열을 반환값에 포함하거나 호출자가 식별 가능하도록 시그니처를 보강.
- 기존 인터페이스가 단순 `bool` 반환이면, **하위 호환** 위해 (1) 기존 메서드 유지 + (2) 사유 반환 메서드 신규 추가 패턴 권장 (예: `check_buy_gates(...)` → `Optional[str]`).
- `engine.py`는 새 메서드를 사용해 차단 사유를 받아 `BUY_REJECT` 기록의 reason으로 매핑.

### 추가 테스트
- `tests/test_engine_db_integration.py` (또는 신규 `tests/test_engine_buy_gate_metric.py`):
  - confidence 미달 시그널 → `BUY_REJECT` (reason=`LOW_CONFIDENCE`) 1회 기록 확인.
  - 포지션 한도 도달 상황 모의 → `BUY_REJECT` (reason=`POSITION_LIMIT`) 1회 기록 확인.
  - 잔고 부족 mock → `INSUFFICIENT_CASH` 기록 확인.
  - 기록 실패(mock raise) 시에도 매매 흐름 정상 진행 확인.
- `tests/test_strategy/test_risk.py`: `check_buy_gates` 신규 메서드의 각 게이트 트립 케이스별 사유 문자열 검증.

### 변경 파일 수
- 코드: 2개 (`src/engine.py`, `src/strategy/risk.py`)
- 테스트: 1~2개 (기존 보강 + 신규 1)
- 합계 **최대 4개** — BRIDGE_SPEC 5개 제한 준수.

## 기대 효과

- 1~2주 누적 후 매수 차단 단계별 분포 측정 가능. 룰 A 발동 시 (a) 시그널 품질 (b) 포지션/잔고 (c) 리스크 게이트 중 진짜 병목 식별 가능.
- 5-15 도입된 `SCREENING_CANDIDATE`/`HIT`/`MISS` 메트릭과 결합 시 (워커 → 엔진 → 매수 게이트)의 전 구간 매수 funnel 측정 완성.
- 무차별 임계값 조정으로 인한 매매 위축 위험 회피 — 진단 후 정확한 파라미터 대상 식별 가능.
- 시스템 안정성: 모든 기록 호출은 try/except로 fallback 보장 — 매매·시그널 본 흐름과 무관(0% 회귀 위험).

## 롤백

- `git restore src/engine.py src/strategy/risk.py tests/test_engine_db_integration.py tests/test_strategy/test_risk.py`로 즉시 원복.
- 신규 system_metrics 카테고리(`BUY_REJECT`)는 enum 제약 없음 — DB 마이그레이션 불필요.
- 잔여 기록 정리(선택): `DELETE FROM system_metrics WHERE metric_type = 'BUY_REJECT';`.
- 5-15 진단 메트릭과 마찬가지로 모두 추가 코드(insert)이며 기존 시그니처 비파괴 변경 (risk.py의 기존 메서드 유지 + 신규 메서드 추가).
