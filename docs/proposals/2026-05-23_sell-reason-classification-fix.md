# sell_reason 분류 anomaly 수정 — PL 부호와 라벨 일관성 보장

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-23
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py, src/strategy/risk.py, src/db/models.py

## 현상 분석

### 760027 ETN 매도 anomaly (2026-05-22 09:00:10 KST)

| 필드 | 값 |
|------|-----|
| stock_code | 760027 |
| stock_name | 키움 인버스 2X 전력 TOP5 ETN |
| trade_type | SELL |
| sell_reason | **STOP_LOSS** ← anomaly |
| quantity | 942 |
| price | 4,226원 (avg_price 3,565원) |
| total_amount | 3,980,770원 |
| profit_loss_amount | **+622,540원** |
| profit_loss_pct | **+18.54%** |
| traded_at (KST) | 2026-05-22 09:00:10 |

`profit_loss_pct=+18.54%`인데 `sell_reason="STOP_LOSS"`로 기록 — 분류 불일치. 익절 매도가 손절 라벨로 기록되어 통계 왜곡:
- W21 STOP_LOSS 평균 PL: 8건 기준 -0.74% (anomaly 1건 보정 시 7건 기준 -3.18%)
- 손익비 통계 왜곡 (1.64 → 표면상 negative)
- 룰 A/B 자동 트리거가 sell_reason 통계에 의존하면 측정 오류

### 코드 경로 추정

5/21 14:55 구현된 `2026-05-21_일봉-부재-시-보유-종목-현재가-기준-손절-익절-평가` (ETN 리스크 청산 누락 수정) implementation_log:
> "일봉이 없어도 보유 종목은 현재가 vs 평균단가 기준 손절(-3%)/익절(+5%, 14:30 이후 +2.5%)을 평가."

760027은 5/22 09:00:04 ~ 09:01:21 사이 4사이클 동안 `RISK_ONLY_EVAL` 메트릭 기록 후 09:00:10 청산. 시간 순서로 보면 RISK_ONLY_EVAL이 청산을 트리거하지 않고 직후 일반 매매 루프에서 청산된 것으로 추정 (current_price가 RISK_ONLY_EVAL detail에서 0으로 기록). 매도 자체는 가격 정보가 들어오자마자 트리거 — 그러나 **sell_reason 결정 분기에서 +5% 익절 기준 통과를 못 잡고 STOP_LOSS fallback으로 라벨링**된 것으로 보임.

가설:
- (1) ETN 리스크 청산 경로(`src/strategy/risk.py`)에서 익절/손절 판정 분기가 부재하거나 PL 부호 분기 누락
- (2) 5/22 09:31 구현된 트레일링/마감 게이트와 ETN 청산 경로가 동일 sell_reason fallback("STOP_LOSS")을 공유
- (3) 매도 사유 결정이 시그널 발생 시점이 아닌 주문 체결 시점에 PL 계산 후 라벨링되는 경로 누락

### 다른 anomaly 가능성 점검

W21 STOP_LOSS 8건 중 760027만 PL >0 (1건). 다른 7건은 -3.04% ~ -3.45%로 정상. 따라서:
- 1회 발생한 anomaly이나 ETN 청산 경로/트레일링 게이트가 신규 도입된 직후 발생 — 동일 패턴 재발 가능성 매우 높음
- 향후 ETN 보유 종목이 추가되거나 동일 경로 청산 시 반복 발생

## 제안 내용

매도 시 PL 부호와 sell_reason 라벨의 일관성을 보장. 3중 방어:
1. **결정 분기 수정**: ETN 리스크 청산 경로 + 트레일링 스톱 게이트 + 기존 STOP_LOSS/TAKE_PROFIT 경로 모두에서 매도 결정 시 PL 부호로 분기
2. **모델 validation listener**: SQLAlchemy event listener로 trades 행 INSERT/UPDATE 시 일관성 검증, 경고 + 강제 보정
3. **회귀 테스트**: 760027 시나리오 재현 단위 테스트 + listener 작동 단위 테스트

## 변경 스펙

### 파일별 변경사항

#### 1. `src/strategy/risk.py` (ETN 리스크 청산 경로)
- `_evaluate_stop_loss_take_profit_without_daily()` 또는 동등 함수(5/21 구현 본체):
  - 매도 결정 직후 PL 계산 → sell_reason 분기
  ```python
  pl_pct = (current_price - avg_price) / avg_price * 100
  if pl_pct > 0:
      sell_reason = 'TAKE_PROFIT'
  else:
      sell_reason = 'STOP_LOSS'
  ```
- 트리거 임계 정보도 detail에 보존 (`stop_loss_pct=-3.0`, `take_profit_pct=5.0/2.5`)

#### 2. `src/engine.py` (트레일링 스톱 게이트 — 5/22 구현 본체)
- 트레일링 스톱 매도 결정 시 sell_reason은 `TRAILING_STOP` 유지 (분류 명확).
- 마감 청산 매도 결정 시 sell_reason은 `MARKET_CLOSE` 유지.
- 단, 기존 fallback이 STOP_LOSS로 설정되어 있다면 명시적으로 PL 부호로 분기하도록 변경.

#### 3. `src/db/models.py` (SQLAlchemy listener)
- trades 테이블에 INSERT/UPDATE event listener 추가:
  ```python
  @event.listens_for(Trade, 'before_insert')
  @event.listens_for(Trade, 'before_update')
  def _validate_sell_reason(mapper, connection, target):
      if target.trade_type != 'SELL':
          return
      if target.profit_loss_pct is None:
          return
      if target.profit_loss_pct > 0 and target.sell_reason == 'STOP_LOSS':
          logger.warning(
              f"sell_reason anomaly: STOP_LOSS with PL +{target.profit_loss_pct:.2f}% "
              f"(stock={target.stock_code}). Auto-correcting to TAKE_PROFIT."
          )
          target.sell_reason = 'TAKE_PROFIT'
      elif target.profit_loss_pct < 0 and target.sell_reason == 'TAKE_PROFIT':
          logger.warning(
              f"sell_reason anomaly: TAKE_PROFIT with PL {target.profit_loss_pct:.2f}% "
              f"(stock={target.stock_code}). Auto-correcting to STOP_LOSS."
          )
          target.sell_reason = 'STOP_LOSS'
  ```
- 단, TRAILING_STOP / MARKET_CLOSE / STRATEGY / MANUAL은 PL 부호와 무관한 분류이므로 보정 대상 제외.

#### 4. 테스트 추가
- `tests/test_strategy/test_etn_risk_eval.py` (5/21 제안서 본체 테스트 확장):
  - 760027 시나리오 재현 (avg_price=3565, current_price=4226) → sell_reason='TAKE_PROFIT'
  - PL <0 케이스 → sell_reason='STOP_LOSS'
- `tests/test_db/test_sell_reason_listener.py` (신규):
  - PL +5%인데 sell_reason='STOP_LOSS'로 INSERT 시도 → listener가 TAKE_PROFIT으로 보정 + WARNING 로그
  - PL -3%인데 sell_reason='TAKE_PROFIT' → listener가 STOP_LOSS로 보정
  - TRAILING_STOP / MARKET_CLOSE / STRATEGY / MANUAL은 보정 대상 외 (PL 부호 무관)

## 기대 효과

1. **매도 사유 통계 정확도 회복**: STOP_LOSS 평균 PL이 실제 손절 평균(-3.18%) 정확 반영. 손익비 통계 신뢰성 회복.
2. **룰 A/B 자동 트리거 측정 신뢰성**: sell_reason 통계 기반 룰 엔진의 트리거 정확도 회복.
3. **defense-in-depth**: 결정 분기 + listener 이중 방어로 향후 유사 anomaly 재발 차단.
4. **분석 신뢰도**: 일일/주간 리포트의 매도 사유 분포 표가 실제 동작을 정확히 반영.

## 회귀 테스트

- 단위 테스트 (위 참조)
- 통합 테스트: 760027 시나리오 + DB 적재 검증 — `tests/test_engine_db_integration.py`에 추가
- 회귀 데이터 보정 (선택): 기존 trades.id=73 (760027 5/22 매도) 행의 sell_reason을 TAKE_PROFIT으로 수동 UPDATE
  ```sql
  UPDATE trades SET sell_reason='TAKE_PROFIT' WHERE id=73 AND stock_code='760027';
  ```
  - 단, **이력 보존 우선** 입장이면 수동 UPDATE 생략하고 향후 신규 데이터만 정상 분류되도록 해도 무방
  - 본 제안에서는 수동 UPDATE를 권장하지 않음(이력 보존). 단, W21 리포트 통계는 anomaly 보정 기준으로 작성됨.

## 리스크 / 부작용

- **이력 데이터 영향 없음**: listener는 INSERT/UPDATE 시점에만 동작. 기존 760027 행은 보정하지 않음(이력 보존).
- **트레일링/마감 게이트와 충돌 없음**: TRAILING_STOP / MARKET_CLOSE는 listener 보정 대상 외 — PL 부호와 무관한 분류로 유지.
- **STRATEGY / MANUAL 매도**: 동일하게 보정 대상 외 — 전략 시그널 매도는 익절·손절 외의 사유일 수 있음.

## 검증 방법 (구현 후)

- W22 매도 데이터에서 `(profit_loss_pct > 0 AND sell_reason = 'STOP_LOSS')` 또는 `(profit_loss_pct < 0 AND sell_reason = 'TAKE_PROFIT')` 케이스가 0건인지 확인
- 750xxx/760xxx (ETN 코드) 매도 발생 시 sell_reason 정확 분류 확인
- 트레일링 스톱 게이트로 매도된 케이스의 sell_reason이 TRAILING_STOP 유지되는지 확인 (PL 부호 무관)
- listener 작동 로그 확인 (WARNING 발생 시 즉시 알림)

## BRIDGE_SPEC 안전 게이트 검증

- 변경 범위: `src/strategy/risk.py` (ETN 청산 분기), `src/engine.py` (트레일링 게이트 분기 점검), `src/db/models.py` (listener 신설), 테스트 신설
- 금지 영역: 없음 (손절률/포지션 상수 변경 없음, 로직 분기만 수정)
- 파라미터 변경 범위: 없음
- 기존 동작 호환성: 매도 자체는 동일하게 발생. sell_reason 라벨만 정확화. 이력 데이터 무영향.
