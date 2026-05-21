# 설계 — Ensemble `_weighted_vote` confidence 산출식 재정의

- 작성일: 2026-05-22
- 상태: 승인됨 (사용자 확정)
- 담당: strategy-engineer (`src/strategy/`) / team lead
- 선행: `docs/plans/2026-05-21_min-confidence-tuning.md` Phase 0 (임계값 튜닝 기각, 산출식으로 전환)
- 범위: 코드 로직 변경 (config/리스크 파라미터 불변)

## 1. 배경

2026-05-21 매매 퍼널 점검에서 신호 대비 매매가 극소(LOW_CONFIDENCE가 BUY_REJECT의 67.5%).
임계값(`STRATEGY_MIN_CONFIDENCE` 0.20) 완화를 검토했으나, Phase 0 실측 결과 기각:

- LOW_CONFIDENCE 거절 929건의 confidence는 평균 **0.058**, 최대 **0.155**.
  히스토그램: 0.034~0.047=185건 / **0.054~0.059=685건(74%)** / 0.155=59건. (0.06~0.155, 0.155~0.20 구간 0건)
- 0.20→0.15 완화는 **59건(6.3%)만 구제** → 임계값은 원인이 아님.

근본 원인은 산출식. `src/strategy/ensemble.py` `_weighted_vote()`:
```python
confidence = winner_weight / len(signals)   # 분모 = HOLD 포함 전체 전략 수 (기본 4)
```
다수 전략이 HOLD(기권)일 때 소수 방향표의 신뢰도가 **HOLD 표 수만큼 기계적으로 희석**됨.
단일 전략이 BUY conf≈0.23으로 단독 투표 → `0.23/4≈0.058` → 0.058 대량 클러스터의 정체.
기본 앙상블 멤버 4종(ma, rsi, macd, bollinger; `registry.py:76`), 활성 method=`weighted`(`.env` `STRATEGY_ENSEMBLE_METHOD=weighted`).

## 2. 설계

### 2.1 기호
- n: 전략 수 (기본 4)
- `buy_w` / `sell_w`: 방향별 confidence 합
- `W`: 승자 방향 가중치, `L`: 패자 방향 가중치 (가중치 비교로 승자 결정)
- `n_win`: 승자 방향 투표 수

### 2.2 새 로직 (`_weighted_vote` 만 변경)
```
1. (기존 유지) HOLD 과반 guard: hold_count > n*3/4 → HOLD
2. (기존 유지) buy_w==0 and sell_w==0 → HOLD
3. (기존 유지) buy_w==sell_w → HOLD (동수)
4. 승자 방향 결정(가중치 비교): W, L, n_win 산출
5. [신규] 최소 참여 게이트: n_win < 2 → HOLD     # 단독표 억제
6. [신규] confidence:
       base = W / n_win          # 승자 캠프 평균 강도 (방식 1)
       opp  = W / (W + L)         # 반대표 강도 반영 (승자라 항상 > 0.5)
       conf = clamp(base * opp, 0.0, 1.0)
```

### 2.3 설계 근거
- **base 분모 = `n_win`** (전체 참여수 `k` 아님): `k`로 두면 반대표가 분모(개수)와 opp(강도)
  양쪽에서 이중 감점됨. `n_win`이면 base="동의 캠프 평균 확신", opp="동의 캠프 우세도"로
  각 인자가 1개 역할만 수행 → 추론·테스트 용이.
- **n_win≥2 게이트**: HOLD=기권으로 보아 희석은 제거하되, 단일 전략 단독 신호가 full conf로
  통과해 리스크 사이징을 키우는 것을 방지(승자 방향에 최소 2개 동의 요구). 1 BUY vs 1 SELL은
  승자 방향 표가 1개이므로 HOLD.
- `reason` 문자열에 `n_win` / opp 값을 노출해 사후 진단 가능하게.

### 2.4 동작 검증 (현재 `W/4` 대비)

| Case | votes | W | L | n_win | 현재 | base | opp | 신규 conf | 게이트 |
|---|---|---|---|---|---|---|---|---|---|
| A | 1 BUY@0.23, 3 HOLD | 0.23 | 0 | 1 | 0.058 | — | — | HOLD | n_win<2 차단 |
| B | 2 BUY@0.3, 2 HOLD | 0.6 | 0 | 2 | 0.15 | 0.30 | 1.00 | 0.30 | 통과 |
| C | 2 BUY@0.5, 1 SELL@0.4 | 1.0 | 0.4 | 2 | 0.25 | 0.50 | 0.71 | 0.36 | 통과 |
| D | 1 BUY@0.6, 1 SELL@0.5, 2 HOLD | 0.6 | 0.5 | 1 | 0.15 | — | — | HOLD | n_win<2 차단 |
| E | 3 BUY@0.3, 1 SELL@0.5 | 0.9 | 0.5 | 3 | 0.35 | 0.30 | 0.64 | 0.19 | 통과(임계 근접) |

효과: 단독표(685건 클러스터)는 LOW_CONFIDENCE 거절 대신 HOLD로 분류, 희석으로 탈락하던
다수-동의 약신호(Case B류)가 구제되어 퍼널이 넓어짐.

## 3. 범위

- **수정**: `src/strategy/ensemble.py` `_weighted_vote()` 한 함수.
- **불변**: `_majority_vote`, `_performance_vote` (performance는 이미 `W/(W+L)` 정규화 사용 —
  단 n_win 게이트는 없음. 비활성 경로라 이번 범위 밖, 추후 패리티는 별도 검토).
- **불변**: `STRATEGY_MIN_CONFIDENCE`(0.20), 리스크 파라미터 일체. 이번엔 산출식만.

## 4. 테스트 (TDD, `tests/test_strategy/`)

- 신규 단위테스트: Case A~E 표 그대로 검증 (n_win 게이트 HOLD, base×opp 값, clamp).
- 경계: n_win=2 정확히 / 모두 HOLD / buy_w==sell_w 동수 / 단일 강신호(0.9) 단독→HOLD /
  L=0일 때 opp=1.0 / clamp 상한.
- 기존 ensemble 테스트: confidence 기대값 변경분 갱신(의도된 회귀 수정).

## 5. 검증 (리스크 직결 — 필수)

- ⚠️ `BUY_REJECT` 메트릭에 투표 분해(n_win, W, L)가 없어 **사전 영향 추정 불가**.
  → 머지 전 백테스트(`scripts/run_backtest.py`)로 최근 구간 신/구 수식의 trade 수·승률·MDD·
  실현손익 비교.
- 1차 1주 관찰: act_rate, LOW_CONFIDENCE→HOLD 전환, 손실률/MDD가 한도(MAX_LOSS_RATE 0.03,
  MAX_DAILY_DRAWDOWN) 내인지.
- (선택, 권장 — 별도 항목) `_weighted_vote` 진단을 위해 signal/BUY_REJECT 메트릭에 n_win·W·L
  추가 기록 → 향후 데이터 기반 튜닝 가능.

## 6. 기록

- `src/strategy/` 로직 변경이므로 `scripts/record_implementation.py` + `docs/CHANGELOG.md`
  rolling 갱신. config 변경 아님.

## 7. 수용 기준

- [ ] `_weighted_vote`가 위 로직대로 동작 (Case A~E 단위테스트 green).
- [ ] 기존 strategy 테스트 전부 green(기대값 갱신 포함), mypy strict / ruff 통과.
- [ ] 백테스트로 trade 수·MDD·실현손익 신/구 비교 리포트 확보.
- [ ] record_implementation + CHANGELOG 기록.
