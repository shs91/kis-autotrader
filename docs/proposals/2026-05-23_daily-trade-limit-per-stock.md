# 종목 일별 최대 진입 횟수 제한 — 동일 종목 다중 진입 패턴 차단

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-23
- 상태: implemented
- 우선순위: medium
- 카테고리: risk_gate
- 관련파일: src/engine.py, src/strategy/risk.py, src/config.py

## 현상 분석

### 2주 연속 동일 종목 3회전 진입 패턴

| 주차 | 종목 | 매수 | 매도 | 실현손익 | 비고 |
|------|------|------|------|----------|------|
| W20 (5/11~5/15) | LG디스플레이(034220) | 3 | 3 | +840원 | 5/14 단일일 3회전 (W20 §2 식별) |
| W21 (5/18~5/22) | 진원생명과학(011000) | 3 | 3 | **-6,557원** | 5/19~5/22 분포 |
| W21 (5/18~5/22) | 켄코아에어로스페이스(274090) | 3 | 3 | **-15,750원** | 5/19~5/22 분포 |

W20에서는 "단기적으로는 문제 아님(LG디스플레이 손익비 1.3 양호)" 판단했으나 W21에서 **2종**에서 동일 패턴 + **실현손익 모두 음수**로 결과 악화. 종목 다양성 결여 + 동일 종목 데이트레이딩 집중이 2주 연속 + 임계 도달.

### 본질 — 종목 선택 알고리즘의 보유종목 재진입 편향

`src/engine.py`의 종목 선택 로직이 (a) 스크리너 추천 + (b) 기보유 종목 재평가를 함께 처리하는 구조에서, 동일 종목이 매도 직후 동일 사이클 또는 다음 사이클에 재시그널되어 진입되는 경향이 관찰됨. W20~W21 데이터로 보면 보유 → 매도 → 익일/당일 재매수가 빈번.

스크리닝의 다양성 결여는 W19~W20 분석에서도 식별된 항목이나, "엔진의 종목 선정 로직" 차원에서 직접 차단할 게이트가 부재.

## 제안 내용

종목별 일별 최대 진입(매수) 횟수 제한을 설정. 동일 종목 동일 거래일 N회 이상 진입 시 매수 게이트가 차단하고 `BUY_REJECT` 메트릭에 `reason=DAILY_TRADE_LIMIT_PER_STOCK`으로 기록.

- 기본값: **`MAX_DAILY_TRADES_PER_STOCK=2`** (1회전 = 매수1회 → 같은 종목 매수 2회까지 허용, 3회차 매수부터 차단)
- 환경변수로 조정 가능 (1~5 권장 범위)
- 매도는 제한하지 않음 (보유분 청산은 항상 허용)
- 위반 시 BUY_REJECT 메트릭에 카테고리 신설 — W21 §7에서 식별된 "BUY_REJECT 단일 카테고리 편중" 보강 효과도 있음

## 변경 스펙

### 파일별 변경사항

#### 1. `src/config.py`
- `Settings`에 `MAX_DAILY_TRADES_PER_STOCK: int = 2` 추가 (환경변수 동일명)
- 환경별 차이 없음 (virtual/real 모두 동일)

#### 2. `src/engine.py` (또는 매수 게이트 위치)
- 매수 의사결정 직전에 신규 게이트 추가:
  ```python
  # 동일 종목 일별 진입 횟수 카운터
  today_kst = (datetime.now(UTC).astimezone(KST)).date()
  buys_today_per_stock = await self.repo.count_buy_trades_today(stock_code, today_kst)
  if buys_today_per_stock >= settings.MAX_DAILY_TRADES_PER_STOCK:
      record_metric('BUY_REJECT', {
          'cycle': cycle,
          'stock_code': stock_code,
          'reason': 'DAILY_TRADE_LIMIT_PER_STOCK',
          'buys_today': buys_today_per_stock,
          'limit': settings.MAX_DAILY_TRADES_PER_STOCK,
      })
      return
  ```
- 카운터는 DB raw 쿼리 또는 사이클별 캐시(딕셔너리) 중 선택. **사이클 캐시 권장** — 동일 사이클 내 다중 매수 차단도 자연스럽게 지원되고, DB 부하 회피.
- 캐시 구조: `Dict[str, int]` (key: stock_code, value: 당일 매수 카운트). 사이클 종료 또는 일자 변경 시 초기화.

#### 3. `src/strategy/risk.py:validate_order` (옵션)
- 엔진과 위험 게이트 모두에서 점검할 경우 `validate_order`에도 동일 로직 추가 가능 — defense-in-depth.
- 단, 동일 정보(당일 매수 카운트)를 두 곳에서 관리하면 일관성 위험. **엔진 단일 게이트 권장**.

#### 4. `src/db/repository.py` (옵션, DB 쿼리 경로 채택 시)
- `count_buy_trades_today(stock_code, kst_date) -> int` 추가
- KST 일자 기준 trades 테이블 조회 (`(traded_at AT TIME ZONE 'Asia/Seoul')::date = $1 AND stock_code = $2 AND trade_type = 'BUY'`)

#### 5. `.env.example`
- `MAX_DAILY_TRADES_PER_STOCK=2` 주석 추가

#### 6. 테스트 추가
- `tests/test_engine_db_integration.py` 또는 신규 `tests/test_strategy/test_daily_trade_limit_per_stock.py`:
  - 동일 종목 1회 매수 → 2회차 매수 허용 → 3회차 매수 차단 + BUY_REJECT 메트릭 발생
  - 다른 종목은 영향 없음 (종목별 독립 카운터)
  - 매도는 영향 없음
  - 환경변수 `MAX_DAILY_TRADES_PER_STOCK=1` 설정 시 2회차부터 차단

## 기대 효과

1. **종목 다양성 회복**: 단일 종목 데이트레이딩 집중 완화. 매일 다른 종목 진입 유도.
2. **동일 종목 연속 손절 패턴 방지**: W21 011000(-6,557)/274090(-15,750)처럼 같은 종목 반복 손절 차단.
3. **BUY_REJECT 메트릭 카테고리 다양화**: W21 §7 식별된 단일 카테고리 편중 보강.
4. **리스크 분산**: 자본의 단일 종목 집중 노출 시간 단축.

## 회귀 테스트

- **단위 테스트**: `tests/test_strategy/test_daily_trade_limit_per_stock.py` 신설
  - case A: 동일 종목 2회 매수 후 3회차 차단
  - case B: 다른 종목은 카운터 독립
  - case C: 매도는 제한 없음 (보유 청산 가능)
  - case D: `MAX_DAILY_TRADES_PER_STOCK=1` 설정 시 2회차부터 차단
  - case E: 날짜 변경 시 카운터 초기화 (mock으로 KST 일자 변경)
- **통합 테스트**: `tests/test_engine_db_integration.py`에 통합 시나리오 추가
  - 같은 종목 매수→매도→매수→매도→매수(차단) 흐름

## 리스크 / 부작용

- **익절 기회 손실 가능성**: 단일 종목 강한 추세에서 다중 진입이 수익 기여 가능. 그러나 W21 데이터로는 다중 진입이 손실 누적과 강한 상관.
- **트레일링 스톱(5/22 도입) 후 매도 빈도 변화**: TS/MC 게이트가 익절 도달 후 청산을 더 빨리 트리거하면 동일 종목 재진입 자연 감소 효과도 있을 수 있음 — 본 제안은 더 직접적인 차단.
- 디폴트 2회는 보수적 — 1회전(매수→매도→매수→매도) 허용. 더 보수적이면 `MAX_DAILY_TRADES_PER_STOCK=1`로 환경변수 조정.

## 검증 방법 (구현 후)

- W22 매매 데이터에서 동일 종목 매수 3회 이상 케이스 0건 확인
- W22 종목 다양성 지표 비교 — 매매 종목 수 / 총 매매 건수 비율이 W21 대비 개선되는지
- BUY_REJECT 메트릭에 `reason=DAILY_TRADE_LIMIT_PER_STOCK` 적재 확인
- W22 종목별 PL 분포 — 부진 종목 누적 손실 패턴 차단 여부

## BRIDGE_SPEC 안전 게이트 검증

- 변경 범위: `src/config.py` (신규 설정), `src/engine.py` (게이트 추가), `src/db/repository.py` (옵션), 테스트 신설
- 금지 영역: 없음
- 파라미터 변경 범위: 신규 환경변수 — 기본값 2, 허용 범위 1~5
- 기존 동작 호환성: 신규 게이트 — 활성 시 기존보다 보수적. 무효화하려면 `MAX_DAILY_TRADES_PER_STOCK=999` 등 큰 값 설정 가능
