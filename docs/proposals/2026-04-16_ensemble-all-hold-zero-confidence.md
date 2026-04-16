# 앙상블 서브전략 전원 HOLD/confidence=0 수렴 원인 진단

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-16
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/strategy/ensemble.py, src/strategy/moving_average.py, src/strategy/rsi.py, src/strategy/macd.py, src/strategy/bollinger.py

## 현상 분석

2026-04-15 구현된 observability 제안서(`SIGNAL_SKIP` 메트릭 + `vote_meta`) 덕분에 오늘 처음으로 앙상블 내부 투표 결과가 데이터로 확인됐다.

### DB 근거 — 오늘(2026-04-16 KST)

**system_metrics.detail (SIGNAL_SKIP, hold_action) — 1,445건 전량 동일 패턴:**

```json
{
  "method": "weighted",
  "votes": [
    {"strategy": "이동평균교차(5/20)", "action": "HOLD", "confidence": 0},
    {"strategy": "RSI(14)",           "action": "HOLD", "confidence": 0},
    {"strategy": "MACD(12,26,9)",     "action": "HOLD", "confidence": 0},
    {"strategy": "볼린저(20,2.0)",     "action": "HOLD", "confidence": 0}
  ]
}
```

| 종목 | 건수 |
|------|------|
| 000660 (SK하이닉스) | 289 |
| 005930 (삼성전자) | 289 |
| 012450 (한화에어로스페이스) | 289 |
| 105560 (KB금융) | 289 |
| 207940 (삼성바이오로직스) | 289 |

5종목 × 289회 = 1,445건, 전부 4개 서브전략이 `confidence=0` HOLD.

### 왜 비정상인가

- 서로 다른 지표(MA·RSI·MACD·BB)가 "동시에 모두" 0 confidence를 낼 가능성은 통계적으로 매우 낮다. 실제 시장 데이터로 계산된 지표라면 적어도 1~2개는 중립값 근처의 비영 confidence를 낸다.
- `confidence=0`은 일반적으로 **NaN·빈 시리즈·데이터 길이 부족**에 대한 방어 분기에서 반환되는 값이다.
- 어제(2026-04-15)는 같은 종목군에서 ENSEMBLE 시그널 4,400건 평균 confidence 0.208로 지표가 정상 계산됐다. 오늘 갑자기 0으로 떨어진 것은 오늘 시점 환경 변화(데이터 소스·캐시 초기화·사이클 주기 변경)를 시사한다.

### 배제한 원인

- API 한도 도달 0회, event_logs ERROR 0건, 사이클 완료율 100% — 인프라 장애 아님.
- RateLimiter / CircuitBreaker 에러 없음.
- 가격 자체가 안 들어오면 시그널 레코드가 발생하지 않아야 하는데 시그널 skip은 기록됐다 → 가격은 입수됐으나 지표 계산 단계에서 가드 분기로 들어간 것으로 추정.

## 제안 내용

지표 계산 함수에 "입력 시리즈 길이 / NaN 비율 / 최종 계산값"을 디버그 로그로 남겨 어느 단계에서 confidence=0으로 떨어지는지 데이터로 확인한다. **이번에도 파라미터 튜닝이 아니라 관측성 추가 제안**이며, 한 단계 더 좁히는 것이 목적이다.

구체적으로 각 서브전략의 `generate()` 또는 `analyze()` 진입 직후/반환 직전에 다음 필드를 `vote_meta.votes[i]`에 추가한다:

- `series_len`: 입력 가격 시리즈 길이
- `nan_ratio`: 입력 중 NaN 비율
- `last_value`: 핵심 지표의 마지막 값 (MA5, RSI, MACD hist, %B)
- `guard_triggered`: 길이 부족 / NaN / 기타 방어 분기 진입 여부 (bool)

이 메타가 쌓이면 내일 리포트에서 "길이 부족"과 "NaN 방어"를 구분해 한 단계 더 좁힐 수 있다.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/ensemble.py`:
  - 하위 전략 결과를 votes에 담을 때 각 sub-strategy가 반환한 `Signal.meta`를 그대로 vote에 merge. 기존 shape(`{strategy, action, confidence}`)는 유지하고, 추가 키만 append.
- `src/strategy/moving_average.py`:
  - `generate()` 내부에서 지표 계산 후 `Signal.meta`에 `series_len`, `nan_ratio`, `last_short`, `last_long`, `guard_triggered` 기록.
- `src/strategy/rsi.py`:
  - 동일 패턴으로 `series_len`, `nan_ratio`, `last_rsi`, `guard_triggered` 기록.
- `src/strategy/macd.py`:
  - `series_len`, `nan_ratio`, `last_macd`, `last_signal`, `last_hist`, `guard_triggered` 기록.
- `src/strategy/bollinger.py`:
  - `series_len`, `nan_ratio`, `last_price`, `last_upper`, `last_lower`, `last_percent_b`, `guard_triggered` 기록.

총 5개 파일 → BRIDGE_SPEC의 5개 한도 정확히 충족.

### 추가 테스트 (필요 시)

- `tests/test_strategy/test_ensemble.py`에 "sub-strategy meta가 vote_meta.votes에 병합되는지" 검증 테스트 1개 추가. 기존 shape 호환 확인.
- 각 서브전략 테스트 파일(`test_moving_average.py` 등)은 Signal.meta에 추가된 키가 들어있는지 가벼운 assertion만 추가(기존 기능 영향 없음).

> 위 테스트 추가는 기존 파일 수정에 해당하지만 파일 수 5개 한도와 무관(tests는 BRIDGE_SPEC의 코드 변경 규칙 상 "관련 테스트가 반드시 같이 수정되어야 함"에 해당).

## 기대 효과

- 내일(2026-04-17) 리포트에서 5종목 × 4전략 × 각 진입값의 분포를 집계할 수 있다.
- `guard_triggered=true`가 전부라면 → 데이터 길이 부족 문제. 종목별 히스토리 로딩 로직 수정 제안.
- `guard_triggered=false` + `last_value=NaN`이라면 → 지표 계산 단계 버그. 해당 지표 함수 수정 제안.
- `guard_triggered=false` + `last_value` 정상인데 action=HOLD confidence=0이라면 → 신호 판정 임계값 로직 문제. 각 전략의 BUY/SELL 분기 조건 검토.
- 본 제안 자체는 매매 지표에 영향을 주지 않으나, 다음 성과 개선 제안의 근거를 제공한다.

## 롤백

- 5개 전략 파일의 Signal.meta 추가 기록 코드 제거.
- 추가된 테스트 assertion 제거.
- `config_overrides.json`에는 영향 없음.
- `git restore` 범위: 위 5개 소스 파일 + 테스트 파일 1~5개.
