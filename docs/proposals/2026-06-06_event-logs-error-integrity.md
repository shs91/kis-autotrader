# event_logs 적재 정합 — 종목 처리 ERROR를 event_logs에도 기록

## 메타데이터
- 작성: Cowork
- 일자: 2026-06-06
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py, tests/test_engine_error_event.py

## 현상 분석

W23 주말 리뷰(`docs/reports/2026-W23_weekly.md`)에서 실전 DB(`kis_trader_real`) 직접 조회 결과, **에러가 `event_logs`에 전혀 적재되지 않는 관측성 결함**을 확인했다.

- 2026-06-05 `system_metrics`에 `ERROR` 2건 적재됨:
  `{"cycle":2365,"error":"종목 처리 실패","stock_code":"034220"}`, 동 `131400`.
- 그러나 `event_logs`는 전 기간 누적 **65행**뿐이고, **ERROR 레벨 행이 0건**이다. 위 06-05 에러 2건도 `event_logs`에는 없다.
- `event_logs`에 실제로 적재되는 것은 `trade`/`system`/`warning` 카테고리뿐이다.

### 근본 원인 (코드 확인)

- `src/engine.py:22` 의 import가 `from src.db.event_logger import log_trade, log_warning` 로, **`log_error`를 import하지 않는다.** 실제로 `log_error`는 `src/engine.py` 어디에서도 호출되지 않는다.
- 종목 처리 예외 경로(`run_trading_cycle`, 현재 565–571행)는 `self._record_metric("ERROR", {...})`로 **system_metrics에만** 기록하고 `event_logs`에는 기록하지 않는다:

  ```python
  except Exception:
      logger.exception("종목 처리 중 에러: %s", stock_code)
      self._record_metric("ERROR", {
          "cycle": self._cycle_count,
          "stock_code": stock_code,
          "error": "종목 처리 실패",
      })
  ```

- 그 결과 공통규칙(`docs/prompts/_common_rules.md`)의 `event_logs` 기반 에러 진단(룰 C: 동일 category 에러 반복)과 일간 리포트의 "에러/경고" 섹션이 **event_logs 기준으로는 항상 0건**으로 보여, 실제 에러를 놓친다.

> `src/db/event_logger.py`에 `log_error(message, details)`는 이미 구현되어 있고 내부 try-except로 보호된다(매매 흐름 비영향). **호출 지점만 누락된 상태**다.

## 제안 내용

종목 처리 예외를 `system_metrics(ERROR)`와 `event_logs(ERROR)` **양쪽에 일관 적재**한다. 메트릭/이벤트 적재 로직을 작은 헬퍼 `_record_error()`로 묶어, 기존 `_record_buy_reject()`와 동일한 패턴으로 단위 테스트한다.

매매 로직·시그니처·파라미터는 일절 변경하지 않는다(순수 관측성 보강). 적재 실패는 기존대로 swallow된다(`_record_metric`는 큐 enqueue, `log_error`는 내부 try-except).

### 범위 밖 (이번 제안 미포함 — 후속 조사 필요)

06-01·06-02 `event_logs`에 trades 정본에 없는 **팬텀 '테스트' 매매**(`지연체결 회수 BUY 테스트(069540) 147주 @ 0원`, 760027 942주 등)가 적재된 건은, 고아체결 회수 경로(`_reconcile_orphan_fill`, engine.py ~1686행)에 **테스트/합성 미체결 주문이 실전 DB로 유입**된 것으로 의심된다. 이는 매매/회수 경로를 건드려야 하고 런타임 원인 규명이 선행되어야 하므로 **자동 구현 범위에서 제외**한다. 별도 조사 항목으로 남긴다.

## 변경 스펙

### 파일별 변경사항

**`src/engine.py`**

1. import 보강 (현재 22행):
   - 변경 전: `from src.db.event_logger import log_trade, log_warning`
   - 변경 후: `from src.db.event_logger import log_error, log_trade, log_warning`

2. 헬퍼 메서드 추가 (엔진 클래스 내, `_record_buy_reject` 인근에 배치):

   ```python
   def _record_error(self, stock_code: str, error: str = "종목 처리 실패") -> None:
       """종목 처리 예외를 관측 채널에 일관 적재한다.

       system_metrics(ERROR)와 event_logs(ERROR) 양쪽에 기록해, 일간·주간
       분석이 event_logs 기준으로도 에러를 추적할 수 있게 한다.
       두 채널 모두 적재 실패는 swallow되어 매매 흐름에 영향을 주지 않는다.
       """
       self._record_metric("ERROR", {
           "cycle": self._cycle_count,
           "stock_code": stock_code,
           "error": error,
       })
       log_error(f"{error}: {stock_code}", details=f"cycle={self._cycle_count}")
   ```

3. 종목 처리 예외 블록(현재 565–571행)을 헬퍼 호출로 치환:
   - 변경 전:
     ```python
     except Exception:
         logger.exception("종목 처리 중 에러: %s", stock_code)
         self._record_metric("ERROR", {
             "cycle": self._cycle_count,
             "stock_code": stock_code,
             "error": "종목 처리 실패",
         })
     ```
   - 변경 후:
     ```python
     except Exception:
         logger.exception("종목 처리 중 에러: %s", stock_code)
         self._record_error(stock_code)
     ```

> 동작 동일성: `_record_metric("ERROR", ...)`의 payload(cycle/stock_code/error)는 그대로 유지된다. `log_error` 호출만 추가된다.

### 추가 테스트

**`tests/test_engine_error_event.py`** (신규 — `tests/` 하위, 코드 변경 규칙 허용)

`test_engine_buy_gate_metric.py`의 `_make_engine()` 패턴을 재사용한다.

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        return TradingEngine(watchlist=["005930"])


def test_record_error_emits_metric_and_event() -> None:
    """_record_error가 system_metrics(ERROR) enqueue + event_logs(log_error) 양쪽을 적재."""
    engine = _make_engine()
    engine._cycle_count = 7
    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch("src.engine.log_error") as mock_log_error:
        engine._record_error("034220")

        metric_calls = [
            c.kwargs["payload"]
            for c in mock_enqueue.call_args_list
            if c.kwargs.get("task_type") == "record_metric"
            and (c.kwargs.get("payload") or {}).get("metric_type") == "ERROR"
        ]
        assert len(metric_calls) == 1
        detail = metric_calls[0]["detail"]
        assert detail["stock_code"] == "034220"
        assert detail["cycle"] == 7
        assert detail["error"] == "종목 처리 실패"

        mock_log_error.assert_called_once()
        assert "034220" in mock_log_error.call_args.args[0]


def test_record_error_logger_failure_is_swallowed() -> None:
    """log_error가 예외를 던져도 _record_error는 전파하지 않는다(매매 흐름 보호)."""
    engine = _make_engine()
    with patch.object(engine._task_queue, "enqueue"), \
         patch("src.engine.log_error", side_effect=Exception("db down")):
        # 예외 없이 정상 반환되어야 한다.
        engine._record_error("005930")
```

> 두 번째 테스트가 통과하려면 `_record_error`가 `log_error` 호출을 방어적으로 감싸야 한다. 구현 시 `log_error(...)`를 `try: ... except Exception: logger.debug(...)`로 보호할 것. (`_record_metric`은 이미 enqueue 기반이라 비차단.)

## 기대 효과

- 종목 처리 에러가 `event_logs`(ERROR)에도 적재되어, 일간 리포트 "에러/경고" 섹션과 공통규칙 룰 C(에러 반복)가 **event_logs 기준으로 정상 작동**한다.
- 06-05 같은 "system_metrics엔 ERROR 있는데 event_logs엔 0건" 불일치 해소.
- 정량 검증: 다음 종목 처리 예외 발생일에 `event_logs`의 ERROR 행수 > 0 이고 `system_metrics` ERROR 건수와 일치하면 효과 확인.
- 매매 동작·수익률·시그니처 불변(순수 관측성).

## 롤백

- `src/engine.py`: import에서 `log_error` 제거, `_record_error` 메서드 삭제, 예외 블록을 원래 인라인 `_record_metric("ERROR", {...})` 형태로 복원.
- `tests/test_engine_error_event.py` 파일 삭제.
- 변경이 엔진 1파일 + 신규 테스트 1파일뿐이라 `git restore src/engine.py && rm tests/test_engine_error_event.py`로 즉시 원복 가능.
