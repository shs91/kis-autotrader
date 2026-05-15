---
name: strategy-add-pattern
description: 새 매매 전략(`src/strategy/*.py`)을 추가할 때 따라야 할 체크리스트. 레지스트리 등록, 셀렉터 갱신, TDD.
---

# Strategy Add Pattern

## 절차

### 1. 클래스 신설
- `src/strategy/<name>.py` — `BaseStrategy` 상속
- `generate_signal(data: pd.DataFrame) -> Signal` 메소드 구현
- `__init__`에서 파라미터 받기 (env 변수 또는 config_overrides.json)

### 2. 레지스트리 등록
- `src/strategy/registry.py`의 `STRATEGY_REGISTRY`에 추가:
  ```python
  STRATEGY_REGISTRY = {
      ...,
      "new_strategy_name": NewStrategy,
  }
  ```

### 3. 셀렉터 갱신 (필요 시)
- 종목별 전략 매핑이 필요하면 `src/strategy/selector.py` 갱신

### 4. TDD
- `tests/test_strategy/test_<name>.py` 신설
  - 매수 시그널 케이스
  - 매도 시그널 케이스
  - HOLD 케이스 (정상 범위)
  - NaN/empty 데이터 가드

### 5. 백테스트 검증
- `python scripts/run_backtest.py --strategy <name> --period 1month`로 회귀 확인

### 6. 문서
- `README.md` 매매 전략 섹션에 추가
- 신규 환경변수 있으면 `.env.example` 갱신

## 금지
- BaseStrategy 우회한 시그널 직접 발행
- API 직접 호출 (전략은 데이터를 인자로 받음)
- DB 직접 쓰기 (Repository 경유)
