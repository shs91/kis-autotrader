# 멀티타임프레임 전략 (옵션 B: 일봉 + 분봉 조합)

- 상태: pending
- 예정일: 2026-04-28 이후 (최소 3~4주 데이터 축적 후)
- 카테고리: enhancement
- 난이도: 높음

## 배경

2026-04-09 기준 4개 전략(MA, RSI, MACD, 볼린저)이 일봉 단일 타임프레임으로 운영 중.
분봉(30분/60분)을 추가하여 단기 진입 타이밍 정밀도를 높이는 것이 목표.

## 전제 조건 (착수 전 확인)

- [ ] 4개 전략 모두 최소 20영업일 데이터 확보
- [ ] 전략별 매도 30건 이상 축적
- [ ] Sharpe Ratio / 승률 등 기준선 성과 확립
- [ ] `get_strategy_win_rates()` 결과로 전략별 성과 비교 가능

확인 방법:
```sql
-- 전략별 매도 건수 확인
SELECT signal_type, COUNT(*) FROM trades
WHERE trade_type = 'SELL' AND signal_type IS NOT NULL
GROUP BY signal_type ORDER BY COUNT(*) DESC;

-- 운영 일수 확인
SELECT COUNT(DISTINCT traded_at::date) FROM trades;
```

## 구현 계획

### 1. 분봉 데이터 조회 인프라

기존 `quote.py`의 `MINUTE_PRICE_PATH`를 활용한 `get_minute_prices()` 구현.

```python
# src/api/quote.py — 이미 엔드포인트 정의됨
MINUTE_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
TR_ID_MINUTE_PRICE = "FHKST03010200"
```

구현할 함수:
```python
async def get_minute_prices(
    self, stock_code: str, period: int = 30
) -> list[MinutePrice]:
    """분봉(30분/60분) 데이터를 조회한다."""
```

### 2. 분봉 캐시

- 분봉은 일봉보다 빈번하게 변하므로 TTL 기반 캐시 필요
- `_minute_cache: dict[str, tuple[float, pd.DataFrame]]` (타임스탬프 + 데이터)
- TTL: 분봉 주기와 동일 (30분봉이면 30분)

### 3. 멀티타임프레임 전략 클래스

```python
# src/strategy/multi_timeframe.py
class MultiTimeframeStrategy(BaseStrategy):
    """일봉(장기 추세) + 분봉(단기 진입) 조합 전략.

    - 일봉: 추세 방향 판단 (MA 골든/데드크로스)
    - 분봉: 진입 타이밍 (RSI 과매도 or MACD 골든크로스)

    규칙:
    - 일봉 BUY + 분봉 BUY → 강한 매수 (신뢰도 상향)
    - 일봉 BUY + 분봉 HOLD → 약한 매수 (신뢰도 유지)
    - 일봉 BUY + 분봉 SELL → HOLD (충돌 → 대기)
    - 일봉 HOLD/SELL → 분봉 무관 HOLD/SELL
    """
```

### 4. API 호출량 관리

| 항목 | 현재 | 분봉 추가 후 |
|------|------|------------|
| 종목당 사이클 API | 2건 (일봉+현재가) | 3건 (일봉+분봉+현재가) |
| 10종목 기준 | 20건/사이클 | 30건/사이클 |
| 분봉 조회 주기 | — | 스크리닝처럼 N사이클마다 (30사이클=5분) |

최적화:
- 분봉은 매 사이클이 아닌 **N사이클마다** 조회 (SCREENING_INTERVAL_CYCLES와 유사)
- 보유 종목만 분봉 조회 (미보유 종목은 일봉만)
- 분봉 캐시 TTL로 불필요한 재조회 방지

### 5. 설정값 (.env)

```env
# 멀티타임프레임 설정
STRATEGY_MINUTE_PERIOD=30          # 분봉 주기 (30분)
STRATEGY_MTF_ENABLED=true          # 활성화 여부
STRATEGY_MTF_DAILY_STRATEGY=moving_average  # 일봉 전략
STRATEGY_MTF_MINUTE_STRATEGY=rsi            # 분봉 전략
STRATEGY_MTF_MINUTE_INTERVAL=30    # 분봉 조회 간격 (사이클 수)
```

### 6. 성과 비교

도입 후 2주간 Before/After 비교:
- 승률 변화
- Sharpe Ratio 변화
- MDD 변화
- 평균 진입 타이밍 개선 여부 (시그널→체결 수익률)

## 변경 대상 파일 (예상)

| 파일 | 변경 |
|------|------|
| src/api/quote.py | `get_minute_prices()` 구현 |
| src/strategy/multi_timeframe.py | **신규** — 멀티타임프레임 전략 |
| src/strategy/registry.py | multi_timeframe 등록 |
| src/config.py | StrategyConfig에 MTF 설정 추가 |
| src/engine.py | 분봉 캐시 + 분봉 조회 주기 로직 |
| tests/test_strategy/test_multi_timeframe.py | **신규** |
| .env.example | MTF 설정 항목 |

## 리스크

- 분봉 API 호출 실패 시 일봉만으로 fallback (graceful degradation)
- 분봉 데이터 부족(장 초반) 시 HOLD 반환
- API 일일 한도(50,000건) 모니터링 강화 필요
