# 작업계획 C — STRATEGY_MIN_CONFIDENCE 튜닝 검토 (0.20 → 0.15)

- 작성일: 2026-05-21
- 상태: **보류 (2026-05-21 Phase 0 결과로 임계값 튜닝 기각)** — ensemble confidence 산출식 재검토로 전환
- 담당: strategy-engineer / team lead (config)
- 우선순위: MEDIUM (저위험, 1주 관찰)
- 선행 의존: 없음

---

## Phase 0 실측 결과 (2026-05-21) — 임계값 튜닝 기각

> DB 최신화 결과 본 계획서의 핵심 전제(평균 confidence 0.240, "약 절반 탈락")가 **생존편향**임이 확인되어
> 0.20→0.15 완화는 보류하고 산출식 재검토로 전환함.

### 발견 1 — signals 테이블 평균값은 무의미 (생존편향)
- `src/engine.py:1087-1092`: `confidence < min_confidence` 이고 미체결인 시그널은 **DB 저장 자체를 스킵**.
- 따라서 `signals` 테이블에는 구조적으로 ≥0.20만 존재(실측 min 0.2029, 100%가 ≥0.20).
- 계획서의 "ENSEMBLE 평균 0.240"은 0.20 미만이 제거된 표본의 평균 → "0.20이 평균 아래" 논리 성립 안 함.

### 발견 2 — 실제 거절 시그널 분포는 임계값보다 한참 아래 (`system_metrics` BUY_REJECT, 최근 7일)
- LOW_CONFIDENCE 거절 929건의 confidence: 평균 **0.058**, 최대 **0.155**.
- 히스토그램: 0.034~0.047 = 185건 / **0.054~0.059 = 685건(74%)** / 0.155 = 59건. (0.06~0.155 및 0.155~0.20 구간 **0건**)
- 임계값별 구제: 0.20→0.15 = **59건(6.3%)만 구제**. 0.12/0.10/0.08도 동일 59건(구간이 비어있음). 본체(685건) 구제하려면 0.05 이하 필요(= 5/1 회귀).
- **결론: 0.20→0.15는 퍼널을 의미있게 넓히지 못함 → 기각.**

### 발견 3 — 진짜 원인은 ensemble confidence 산출식 (`src/strategy/ensemble.py:173`)
- `_weighted_vote()`: `confidence = winner_weight / len(signals)`. 분모 `len(signals)`는 **HOLD 포함 전체 전략 수(=4)**.
- 기본 앙상블 멤버 4종(ma, rsi, macd, bollinger, `registry.py:76`).
- 단일 전략이 BUY conf≈0.23으로 단독 투표 → `0.23/4 ≈ 0.058` → 0.058 대량 클러스터(685건)의 정체.
- 즉 다수 전략이 HOLD일 때 소수 BUY의 신뢰도가 **HOLD 표 수만큼 기계적으로 희석**됨. 임계값을 아무리 내려도 분모 4가 신뢰도를 깔아뭉갠다.

### 결정 (사용자 확인, 2026-05-21)
- **MIN_CONFIDENCE 튜닝 보류** (config_overrides 0.20 유지, 변경 없음).
- 2차 작업으로 **ensemble confidence 산출식 재검토** 진행 — 분모를 비-HOLD(참여) 전략 수 또는 winner+loser weight로 정규화하는 안 검토(별도 계획/제안서, strategy-engineer 합의 + TDD 필수).

## 1. 배경 (자기완결)

2026-05-21 매매 퍼널 점검 결과, 신호 대비 실제 매매가 극히 적음.
- DB: signals 40,776건 중 action_taken=true 2,741건(6.7%), 실제 trades 72건.
- 최근 7일 BUY_REJECT 사유: **LOW_CONFIDENCE 929(약 68%)**, MARKET_CLOSE_GUARD 172, POSITION_RATIO 137, OTHER 131, RISK_GATE 5, MAX_DAILY_DRAWDOWN 2.
- 신뢰도 분포(검증): `signals` 중 ENSEMBLE 평균 confidence **0.240** (최근 7일 6,393건), GOLDEN_CROSS 평균 **0.172**. 임계값 0.20이 ENSEMBLE 평균 바로 아래 → 약 절반이 임계값 미달로 탈락.

## 2. 현황 (코드/설정 확정)

- 실효값: `config_overrides.json` `"STRATEGY_MIN_CONFIDENCE": 0.20` (`_meta.updated_by = proposal:2026-05-11_ensemble-confidence-further-raise`).
- 코드 기본값: `src/config.py` `STRATEGY_MIN_CONFIDENCE` 기본 0.1. BRIDGE_SPEC 허용 범위 **0.05~0.5**.
- 변경 이력: 0.1(기본) → 0.05(5/1) → 0.15(5/7) → **0.20(5/11)**. 약 열흘간 보수적으로 상향됨.
- 게이트 코드: `src/strategy/risk.py` `check_buy_gates()` (≈line 325-367) — `if signal.confidence < self._min_confidence: return "LOW_CONFIDENCE"`.
- 신뢰도 산출: `src/strategy/ensemble.py` `_weighted_vote()` (≈line 141-181) — 하위 전략 confidence 합을 전략 수로 나눔 → 평균이 0.24 부근에 형성.

## 3. 판단

- LOW_CONFIDENCE 필터 자체는 5/1~5/11 제안서로 **의도적으로 강화**된 것.
- 그러나 현재 임계값 0.20이 ENSEMBLE 신뢰도 분포의 중앙(평균 0.240)에 위치 → **약 절반을 기계적으로 탈락**시켜 퍼널이 과도하게 좁음.
- 0.20 → 0.15 완화는 BRIDGE_SPEC 범위 내(0.05~0.5)이며 리스크는 하위 게이트(RISK_GATE/POSITION_RATIO/손절·익절)가 2차로 흡수.

## 4. 작업 단계

### Phase 0 — 현황 재확인 (수치 최신화)
- DB로 ENSEMBLE/GOLDEN_CROSS confidence 분포(avg/median/p90), 임계값별 통과 비율 재산출. BUY_REJECT 최근 분포 재확인.
- `config_overrides.json` 현재값과 `_meta` 확인.

### Phase 1 — 변경안 결정 (저위험 1-스텝)
- `STRATEGY_MIN_CONFIDENCE`: 0.20 → **0.15** 1차 완화안. (한 번에 0.10까지 내리지 말고 단계적.)
- 동반 검토(선택): `SCREENING_MIN_SCORE` 0.15 → 0.20 상향으로 신규/단기 종목 유입을 줄여 `DAILY_DATA_INSUFFICIENT` 감소(설계상 22일봉 필요 — 버그 아님, 시간경과로 자동 감소 5/20 1,383→5/21 66).

### Phase 2 — 적용 경로 선택
- (a) `config_overrides.json` 직접 수정 + `_meta.updated_by/at` 기록. 서비스 재시작 시 반영.
- (b) `docs/proposals/2026-05-21_*.md` 제안서로 작성(상태: ready)하여 자동 파이프라인이 안전게이트 검증 후 적용 — **단, 이 경로는 17:15/19:00 autoimplement가 자동 구현**하므로 의도한 경우에만.
- 권장: 사용자 확인 후 (a) 또는 (b) 선택.

### Phase 3 — 관찰 (1주)
- act_rate(action_taken/signals), trades 수, BUY_REJECT 사유 분포, 실현손익 추이를 1주 모니터.
- 개선 미흡 시 0.15 → 0.10 추가 완화 또는 ensemble confidence 산출식 검토(2차).

## 5. 수용 기준
- [ ] 변경 후 LOW_CONFIDENCE 거절 비율 하락(목표 ~50% 이하), act_rate 상승.
- [ ] 손실률/MDD가 리스크 한도(MAX_LOSS_RATE 0.03, MAX_DAILY_DRAWDOWN) 내 유지.
- [ ] 변경 기록: config 경로면 `_meta`, 코드 경로면 record_implementation + CHANGELOG.

## 6. 주의 / 제약
- **고위험 파라미터 아님**이나, 손절률/최대포지션 등은 절대 함께 건드리지 말 것(BRIDGE_SPEC 고위험군 — 사용자 확인 게이트).
- 한 번에 한 파라미터만 변경해 효과 분리 관찰.
- 매매 시간 중 변경/재시작 지양 — 장 마감 후 적용 권장.

## 7. 트리거 프롬프트
```
docs/plans/2026-05-21_min-confidence-tuning.md 를 읽고 작업계획 C를 진행해줘.
Phase 0에서 DB(docker exec kis-postgres psql)로 ENSEMBLE confidence 분포와 BUY_REJECT
최근 분포, config_overrides.json 현재값을 최신화한 뒤, STRATEGY_MIN_CONFIDENCE 0.20→0.15
완화안을 정리해서 적용 경로((a) config_overrides 직접 (b) proposal 경유)를 나에게 물어봐.
손절률·최대포지션 등 고위험 파라미터는 건드리지 말고, 변경은 한 번에 하나만. 적용 시
_meta 또는 record_implementation 기록을 남겨줘.
```
