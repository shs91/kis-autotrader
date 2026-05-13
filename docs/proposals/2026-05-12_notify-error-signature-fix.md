# DEAD 태스크 알림의 notify_error 시그니처 불일치 수정

## 메타데이터
- 작성: Claude Code (2026-05-12 헬스체크 후속)
- 일자: 2026-05-12
- 상태: implemented
- 우선순위: low
- 카테고리: bug_fix
- 관련파일: src/worker/runner.py, tests/test_worker/test_runner.py

## 현상 분석

2026-05-12 헬스체크 중 `logs/autotrader.log`에서 다음 에러 흔적 발견:

```
2026-05-12 21:16:24 | ERROR | src.worker.runner | DEAD 태스크 알림 전송 실패 (매매에 영향 없음)
Traceback (most recent call last):
  ...
  await notifier.notify_error(
      f"error: {error[:200]}"
TypeError: TelegramNotifier.notify_error() missing 1 required positional argument: 'error'
```

### 근본 원인

`TelegramNotifier.notify_error()` 시그니처는 **2개 인자** (`context`, `error`):

- `src/notify/telegram.py:196`: `async def notify_error(self, context: str, error: str) -> None:`
- `src/notify/formatter.py:190`: `format_error(context, error)` — context는 발생 위치, error는 메시지

다른 호출자는 모두 2개 인자로 정상 호출 중:
- `src/engine.py:235-237`: `await self._notifier.notify_error("장중 매매", "API 일일 한도 초과...")`
- `tests/test_notify/test_telegram.py:148`: `notify_error("테스트", "에러 발생")`

**오직 `src/worker/runner.py:124-128`의 `_notify_dead_task()`만 1개 인자로 호출** — concatenated f-string 하나를 통째로 첫 인자에 전달.

### 영향

- DEAD 태스크 발생 시 알림 전송이 항상 `TypeError`로 실패
- `except` 블록이 swallow하여 `"DEAD 태스크 알림 전송 실패 (매매에 영향 없음)"` 로그만 남김
- **매매 로직 영향 0** — DEAD 태스크 자체는 `record_metric`/`record_signal` 같은 후처리 큐로, 매매 사이클과 분리됨
- **모니터링 사각지대 발생** — DEAD 태스크가 쌓여도 Telegram에 알림이 안 옴 → 사용자가 모르고 누적될 수 있음

### 회귀 빠져나간 이유

`tests/test_worker/test_runner.py`에 `notify_error` 호출을 검증하는 테스트가 없음. `_notify_dead_task`의 except가 모든 예외를 swallow하므로 단위 테스트도 통과해 버림.

## 제안 내용

1. **`_notify_dead_task()`의 호출을 2개 인자 형식으로 수정** — `context`(발생 위치)와 `error`(원인 메시지)를 분리.
2. **`tests/test_worker/test_runner.py`에 회귀 테스트 추가** — DEAD 트리거 시 `notify_error`가 정확히 2개의 string 인자로 호출되는지 mock으로 검증.

## 변경 스펙

### 파일별 변경사항

- `src/worker/runner.py` (L124~128):
  ```python
  # 변경 전
  await notifier.notify_error(
      f"[Worker DEAD] 태스크 영구 실패\n"
      f"id={task_id}, type={task_type}\n"
      f"error: {error[:200]}"
  )

  # 변경 후
  await notifier.notify_error(
      f"Worker DEAD (id={task_id}, type={task_type})",
      error,
  )
  ```
  - `context`: 발생 위치 한 줄 — `format_error()`가 자동으로 `🚨 [에러]` 접두사를 붙임
  - `error`: 원인 메시지 — `format_error()` 내부에서 200자로 truncate되므로 호출 측 `[:200]` 제거

- `tests/test_worker/test_runner.py` (신규 테스트):
  ```python
  @pytest.mark.asyncio()
  async def test_notify_dead_task_uses_correct_signature():
      """DEAD 태스크 알림이 notify_error를 (context, error) 형식으로 호출한다."""
      with patch("src.notify.telegram.TelegramNotifier") as mock_cls:
          mock_notifier = AsyncMock()
          mock_cls.return_value = mock_notifier

          runner = TaskWorker(...)  # 또는 직접 _notify_dead_task 호출
          await runner._notify_dead_task(
              task_id=42, task_type="record_trade", error="DB connection lost"
          )

          mock_notifier.notify_error.assert_called_once()
          args, kwargs = mock_notifier.notify_error.call_args
          # context와 error 두 인자 모두 전달되었는지
          assert len(args) + len(kwargs) == 2
          assert any("Worker DEAD" in str(a) for a in args + tuple(kwargs.values()))
          assert any("DB connection lost" in str(a) for a in args + tuple(kwargs.values()))
  ```

### 추가 테스트

위 회귀 테스트 1건만 추가. 기존 `tests/test_notify/test_telegram.py`의 `test_notify_error_is_urgent`이 시그니처 자체는 이미 검증 중.

## 기대 효과

- DEAD 태스크 발생 시 Telegram 긴급 알림이 정상 전송됨 → 모니터링 사각지대 해소
- 회귀 테스트로 같은 패턴(`notify_error` 인자 누락) 재발 차단
- `error[:200]` 호출 측 truncate 제거 → 책임이 `format_error` 한 곳에 집중되어 일관성 향상

## 롤백

- `git revert <commit>` — 코드와 테스트 모두 원복
- 데이터 영향 없음 (read-only 알림 경로 변경)

## 변경 파일 수

2개 — BRIDGE_SPEC 5개 한도 내.

## 검증

```bash
.venv/bin/pytest tests/test_worker/test_runner.py -v
.venv/bin/python -m mypy src/worker/runner.py
.venv/bin/ruff check src/worker/runner.py tests/test_worker/test_runner.py
```

세 가지 모두 pass해야 implemented 처리.
