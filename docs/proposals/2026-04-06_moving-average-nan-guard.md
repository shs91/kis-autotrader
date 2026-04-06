# 이동평균 전략 NaN 방어 로직 추가

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-06
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/strategy/moving_average.py

## 현상 분석

`autotrader.err.log`에서 아래 RuntimeWarning이 3회 기록됨:

```
/Users/songhansu/IdeaProjects/kis-autotrader/src/strategy/moving_average.py:101: RuntimeWarning: invalid value encountered in scalar divide
  divergence_rate = abs(current_short - current_long) / current_long
```

**원인**: `current_long`이 NaN일 때 `current_long != 0`은 `True`로 평가되므로(NaN은 어떤 비교에서도 False를 반환하지만 `!= 0`은 True), 나눗셈이 실행되어 RuntimeWarning 발생.

이는 rolling mean 계산 시 데이터가 부족하면(예: 20일 이동평균인데 실제 데이터가 20일 미만) 초기 값이 NaN이 되는 것이 원인. 현재 `min_required` 체크가 있지만, 데이터 내부에 결측값이 있거나 경계 조건에서 NaN이 발생할 수 있음.

## 제안 내용

`moving_average.py`의 101번째 줄 괴리율 계산에 `numpy.isnan()` 또는 `math.isnan()` 체크를 추가하여 NaN 입력 시 안전하게 0.0을 반환하도록 수정.

추가로, MA 값이 NaN인 경우 골든크로스/데드크로스 비교도 무의미하므로 조기에 HOLD를 반환하는 가드 조건을 추가.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/moving_average.py`:

**변경 전** (98~102행):
```python
        prev_long = long_ma.iloc[-2]

        # 괴리율 기반 신뢰도 계산
        divergence_rate = abs(current_short - current_long) / current_long if current_long != 0 else 0.0
        confidence = min(divergence_rate / MAX_DIVERGENCE_RATE, 1.0)
```

**변경 후**:
```python
        prev_long = long_ma.iloc[-2]

        # NaN 방어: MA 값 중 하나라도 NaN이면 시그널 판단 불가
        import math
        if any(math.isnan(v) for v in [current_short, current_long, prev_short, prev_long]):
            logger.warning(
                "MA 값에 NaN 포함 — HOLD 반환 (short: %s, long: %s)",
                current_short,
                current_long,
            )
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason="이동평균 값에 NaN 포함 — 데이터 부족",
            )

        # 괴리율 기반 신뢰도 계산
        divergence_rate = abs(current_short - current_long) / current_long if current_long != 0 else 0.0
        confidence = min(divergence_rate / MAX_DIVERGENCE_RATE, 1.0)
```

**참고**: `import math`는 이미 파일 상단에 있으면 생략. 없으면 기존 import 블록에 추가.

### 추가 테스트 (필요 시)

- `tests/test_strategy/test_moving_average.py`에 NaN 데이터 케이스 추가:
  - 테스트명: `test_nan_ma_values_return_hold`
  - 내용: 20개 미만의 종가 데이터(rolling mean 결과에 NaN 포함)를 전달했을 때 HOLD가 반환되는지 확인
  - 단, 기존 `min_required` 체크로 걸리지 않는 경우를 테스트 (예: 데이터 개수는 충분하나 중간에 NaN이 있는 경우)

## 기대 효과

- `autotrader.err.log`의 RuntimeWarning 완전 제거
- NaN 입력 시 예측 불가능한 시그널 발생 방지 (NaN 비교 결과가 False가 되어 의도치 않게 HOLD가 반환되는 현재 동작을 명시적으로 처리)
- 로그에 NaN 발생 원인을 WARNING으로 남겨 추후 디버깅 용이

## 롤백

- `git restore src/strategy/moving_average.py`
- 추가된 테스트는 삭제하거나 유지해도 무방 (기존 동작에 영향 없음)
