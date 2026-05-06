# 엔진 일봉 데이터 최소 요구량 하향 — 매매 교착 해소

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-06
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/engine.py

## 현상 분석

KIS API 일봉 조회(FHKST01010400)가 최대 30건만 반환하는데, 엔진(`src/engine.py:180`)이 36건 미만 시 전략 평가를 전면 스킵하고 있음.

- 2026-05-06 기준: DAILY_DATA_INSUFFICIENT 14,726건, EVAL_SKIP 14,719건
- 7일 연속 스크리닝 전환율 0% (쿼리 11 근거)
- 전 종목에서 동일 패턴: required=36, returned=30

36건 요구의 근거는 MACD 전략 (slow=26 + signal=9 + 1 = 36) 이지만, MACD 전략은 자체적으로 데이터 부족 시 HOLD(confidence=0)을 반환하는 안전장치가 이미 구현되어 있음(`src/strategy/macd.py:55-70`).

MA(21건 필요), RSI(15건 필요), Bollinger(21건 필요)는 30건으로 충분히 평가 가능.

## 제안 내용

엔진의 일봉 데이터 최소 요구량을 하드코딩된 36에서 `settings.strategy.ma_long_period + 2`(기본값: 22)로 변경한다.

- MA, RSI, Bollinger 전략: 30건 데이터로 정상 평가 가능
- MACD 전략: 데이터 부족 시 자체 가드에서 HOLD 반환 → 앙상블 투표에서 중립 처리
- 각 전략이 이미 자체 `min_required` 검증 로직을 보유하므로, 엔진 레벨에서의 과도한 필터링만 완화

## 변경 스펙

### 파일별 변경사항

- `src/engine.py` (1개 파일):
  - **L180**: `if len(daily_prices) < 36:` → `if len(daily_prices) < settings.strategy.ma_long_period + 2:`
  - **L185**: `"required_count": 36,` → `"required_count": settings.strategy.ma_long_period + 2,`

### 추가 테스트 (필요 시)

기존 테스트에서 `_get_daily_df`를 모킹하고 있으므로 추가 테스트 불필요. 변경은 임계값 상수만 수정하며 함수 시그니처 변경 없음.

## 기대 효과

- 스크리닝 전환율 0% → 정상화 (MA/RSI/Bollinger 3개 전략 평가 가능)
- 매매 교착 상태 해소 → 실질적 매수/매도 시그널 생성 가능
- MACD는 데이터 축적 후 자동 활성화 (API가 36건 이상 반환 시)

## 롤백

```python
# src/engine.py L180
if len(daily_prices) < 36:
# src/engine.py L185
"required_count": 36,
```
