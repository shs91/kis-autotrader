# config_overrides.json Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `src/config.py` load `config_overrides.json` at import time so that the Cowork ↔ Claude Code pipeline can adjust runtime parameters without touching `.env` (forbidden by BRIDGE_SPEC).

**Architecture:** Module-level `_overrides` dict populated from `<PROJECT_ROOT>/config_overrides.json` before `Settings()` is instantiated. `_env()` helper checks this dict before `os.getenv()`. `os.environ` is never mutated. A frozen `OverrideState` dataclass exposes the applied state via `settings.overrides` and `get_active_overrides()`.

**Tech Stack:** Python 3.12, stdlib `json` + `logging` + `pathlib`, pytest with `tmp_path` / `monkeypatch`, mypy strict, ruff.

**Spec reference:** `docs/02-design/features/config-overrides-loader.design.md`

---

## File Structure

**Modified:**
- `src/config.py` — add imports (`json`, `logging`, `Any`), `_PROJECT_ROOT` constant, `OverrideState` dataclass, `_load_overrides_from()` / `_load_overrides()` functions, module-level `_overrides` / `_overrides_meta` dicts, refactor `_env` / `_env_int` / `_env_float`, add `Settings.overrides` field, `_build_override_state()` helper, `get_active_overrides()` public function.

**Created:**
- `tests/test_config.py` — 14 test cases covering loader behavior, error paths, and exposure API.

Both changes stay well under BRIDGE_SPEC's 5-file limit.

---

## Task 1: Scaffolding — imports, constants, `OverrideState` dataclass

**Files:**
- Modify: `src/config.py:1-11` (imports) and `src/config.py:27` (after helper imports)

**Purpose:** Add every new symbol that later tasks reference, so subsequent tasks don't need to re-touch the header. No behavior yet, no test.

- [ ] **Step 1: Add new imports to `src/config.py`**

  At the top of the file, replace:

  ```python
  """환경변수 및 설정값 관리 모듈."""

  from __future__ import annotations

  import os
  from dataclasses import dataclass, field
  from pathlib import Path

  from dotenv import load_dotenv

  load_dotenv()
  ```

  with:

  ```python
  """환경변수 및 설정값 관리 모듈."""

  from __future__ import annotations

  import json
  import logging
  import os
  from dataclasses import dataclass, field
  from pathlib import Path
  from typing import Any

  from dotenv import load_dotenv

  load_dotenv()

  _PROJECT_ROOT = Path(__file__).resolve().parent.parent
  logger = logging.getLogger(__name__)

  # config_overrides.json 로드 결과. _load_overrides()가 import 시점에 채운다.
  _overrides: dict[str, str] = {}
  _overrides_meta: dict[str, Any] = {}
  ```

- [ ] **Step 2: Add `OverrideState` dataclass**

  Immediately after the `_overrides_meta` global (and before the `_env` function), add:

  ```python
  @dataclass(frozen=True)
  class OverrideState:
      """config_overrides.json 적용 상태 스냅샷."""

      values: dict[str, str]
      """적용된 key → 문자열화된 값."""

      meta: dict[str, Any]
      """_meta 내용물 (평탄화 — updated_at, updated_by 등)."""

      source_path: Path
      """config_overrides.json 절대 경로."""

      loaded: bool
      """파일이 실제로 존재하여 로드되었는지 여부."""
  ```

- [ ] **Step 3: Verify the module still imports**

  Run: `python -c "import src.config; print(src.config.settings.trading.max_loss_rate)"`
  Expected: prints the current `MAX_LOSS_RATE` value (e.g. `0.03`) with no errors.

- [ ] **Step 4: Run the existing test suite to catch regressions**

  Run: `pytest tests/ -q`
  Expected: all existing tests pass (no new tests yet).

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py
  git commit -m "refactor(config): scaffold overrides loader imports and OverrideState"
  ```

---

## Task 2: `_load_overrides_from()` — empty / missing file (TDD)

**Files:**
- Create: `tests/test_config.py`
- Modify: `src/config.py` (add function stub after `OverrideState`)

**Purpose:** Establish the loader function signature and happy-path for a missing file. Subsequent tasks add behavior case-by-case.

- [ ] **Step 1: Create `tests/test_config.py` with the "no file" test**

  ```python
  """src/config.py 오버라이드 로더 테스트."""

  from __future__ import annotations

  from collections.abc import Iterator
  from pathlib import Path

  import pytest

  from src import config


  @pytest.fixture(autouse=True)
  def reset_overrides() -> Iterator[None]:
      """각 테스트 전후에 모듈 전역 _overrides/_overrides_meta를 초기화한다."""
      saved_values = dict(config._overrides)
      saved_meta = dict(config._overrides_meta)
      config._overrides.clear()
      config._overrides_meta.clear()
      yield
      config._overrides.clear()
      config._overrides_meta.clear()
      config._overrides.update(saved_values)
      config._overrides_meta.update(saved_meta)


  def test_no_override_file(tmp_path: Path) -> None:
      """파일이 없으면 빈 dict 튜플을 반환한다."""
      missing = tmp_path / "config_overrides.json"

      values, meta = config._load_overrides_from(missing)

      assert values == {}
      assert meta == {}
  ```

- [ ] **Step 2: Run the test — expect failure**

  Run: `pytest tests/test_config.py::test_no_override_file -v`
  Expected: FAIL with `AttributeError: module 'src.config' has no attribute '_load_overrides_from'`.

- [ ] **Step 3: Add minimal `_load_overrides_from()` stub**

  In `src/config.py`, after the `OverrideState` dataclass, add:

  ```python
  def _load_overrides_from(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
      """지정한 경로에서 config_overrides.json을 로드한다.

      파일이 없으면 ``({}, {})``를 반환한다. 파싱/타입 오류 시 ``RuntimeError``.
      """
      if not path.exists():
          logger.debug("config_overrides.json not found, using .env only")
          return {}, {}
      return {}, {}
  ```

- [ ] **Step 4: Run the test — expect pass**

  Run: `pytest tests/test_config.py::test_no_override_file -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): add _load_overrides_from stub with missing-file path"
  ```

---

## Task 3: String-value override parsing (TDD)

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/config.py` (`_load_overrides_from` body)

- [ ] **Step 1: Add the string-value test**

  Append to `tests/test_config.py`:

  ```python
  def test_str_override_applied(tmp_path: Path) -> None:
      """문자열 값이 그대로 values에 저장된다."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"STRATEGY_ENSEMBLE_METHOD": "majority"}', encoding="utf-8")

      values, meta = config._load_overrides_from(path)

      assert values == {"STRATEGY_ENSEMBLE_METHOD": "majority"}
      assert meta == {}
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py::test_str_override_applied -v`
  Expected: FAIL — `values` is empty dict.

- [ ] **Step 3: Implement basic JSON parsing for string values**

  Replace the body of `_load_overrides_from()` in `src/config.py` with:

  ```python
  def _load_overrides_from(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
      """지정한 경로에서 config_overrides.json을 로드한다.

      파일이 없으면 ``({}, {})``를 반환한다. 파싱/타입 오류 시 ``RuntimeError``.
      """
      if not path.exists():
          logger.debug("config_overrides.json not found, using .env only")
          return {}, {}

      raw_text = path.read_text(encoding="utf-8")
      data = json.loads(raw_text)
      if not isinstance(data, dict):
          raise RuntimeError("config_overrides.json root must be an object")

      values: dict[str, str] = {}
      meta: dict[str, Any] = {}

      for key, value in data.items():
          if key.startswith("_"):
              continue
          if isinstance(value, str):
              values[key] = value

      return values, meta
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py::test_str_override_applied -v`
  Expected: PASS.

- [ ] **Step 5: Re-run prior test to make sure it still passes**

  Run: `pytest tests/test_config.py -v`
  Expected: both `test_no_override_file` and `test_str_override_applied` pass.

- [ ] **Step 6: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): parse string overrides from JSON file"
  ```

---

## Task 4: Int / float coercion (TDD)

**Files:**
- Modify: `tests/test_config.py`, `src/config.py`

- [ ] **Step 1: Add int & float coercion tests**

  Append to `tests/test_config.py`:

  ```python
  def test_int_override_coerced_to_str(tmp_path: Path) -> None:
      """정수 값은 문자열로 변환되어 저장된다."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"SCREENING_TOP_N": 15}', encoding="utf-8")

      values, _ = config._load_overrides_from(path)

      assert values == {"SCREENING_TOP_N": "15"}


  def test_float_override_coerced_to_str(tmp_path: Path) -> None:
      """실수 값은 문자열로 변환되어 저장된다."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"MAX_LOSS_RATE": 0.025}', encoding="utf-8")

      values, _ = config._load_overrides_from(path)

      assert values == {"MAX_LOSS_RATE": "0.025"}
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py -v`
  Expected: two new tests FAIL (int/float not handled yet).

- [ ] **Step 3: Extend loop to handle int and float**

  In `src/config.py`, replace the `for key, value in data.items():` block inside `_load_overrides_from()` with:

  ```python
      for key, value in data.items():
          if key.startswith("_"):
              continue
          # NOTE: bool은 int의 하위 타입이므로 반드시 bool 체크를 먼저 해야 한다.
          # 이 태스크에서는 아직 bool을 다루지 않으므로, 다음 태스크에서 분기를 추가한다.
          if isinstance(value, str):
              values[key] = value
          elif isinstance(value, (int, float)):
              values[key] = str(value)
          else:
              raise RuntimeError(
                  f"config_overrides.json: unsupported type for {key}: "
                  f"{type(value).__name__}"
              )
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py -v`
  Expected: all four tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): coerce int/float override values to strings"
  ```

---

## Task 5: Bool coercion — must precede int check (TDD)

**Files:**
- Modify: `tests/test_config.py`, `src/config.py`

**Important background:** In Python, `bool` is a subclass of `int`. `isinstance(True, int)` returns `True`. The naive `isinstance(value, (int, float))` branch from Task 4 will currently coerce `True` → `"True"` and `False` → `"False"` — but the existing `HEALTH_ENABLED` / `TELEGRAM_ENABLED` checks compare against `"true"` / `"false"` (lowercase). We must handle `bool` explicitly and with lowercase output.

- [ ] **Step 1: Add bool coercion tests**

  Append to `tests/test_config.py`:

  ```python
  def test_bool_true_coerced_to_lowercase(tmp_path: Path) -> None:
      """True는 'true' 소문자 문자열로 저장된다."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"HEALTH_ENABLED": true}', encoding="utf-8")

      values, _ = config._load_overrides_from(path)

      assert values == {"HEALTH_ENABLED": "true"}


  def test_bool_false_coerced_to_lowercase(tmp_path: Path) -> None:
      """False는 'false' 소문자 문자열로 저장된다."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"TELEGRAM_ENABLED": false}', encoding="utf-8")

      values, _ = config._load_overrides_from(path)

      assert values == {"TELEGRAM_ENABLED": "false"}
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py -v`
  Expected: both bool tests FAIL — stored as `"True"`/`"False"` instead of `"true"`/`"false"`.

- [ ] **Step 3: Add the bool branch before the int/float branch**

  In `src/config.py`, replace the loop body inside `_load_overrides_from()` with:

  ```python
      for key, value in data.items():
          if key.startswith("_"):
              continue
          # bool은 int의 하위 타입이므로 반드시 먼저 체크한다.
          if isinstance(value, bool):
              values[key] = "true" if value else "false"
          elif isinstance(value, str):
              values[key] = value
          elif isinstance(value, (int, float)):
              values[key] = str(value)
          else:
              raise RuntimeError(
                  f"config_overrides.json: unsupported type for {key}: "
                  f"{type(value).__name__}"
              )
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py -v`
  Expected: all six tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): coerce bool overrides to lowercase true/false"
  ```

---

## Task 6: `_meta` flattening and underscore-key handling (TDD)

**Files:**
- Modify: `tests/test_config.py`, `src/config.py`

- [ ] **Step 1: Add `_meta` flatten test**

  Append to `tests/test_config.py`:

  ```python
  def test_meta_flattened_in_state(tmp_path: Path) -> None:
      """_meta의 내용물은 평탄화되어 meta dict에 저장되고, values에는 없다."""
      path = tmp_path / "config_overrides.json"
      path.write_text(
          '{"_meta": {"updated_by": "proposal:x", "updated_at": "2026-04-10"}, '
          '"MAX_LOSS_RATE": 0.02}',
          encoding="utf-8",
      )

      values, meta = config._load_overrides_from(path)

      assert values == {"MAX_LOSS_RATE": "0.02"}
      assert meta == {"updated_by": "proposal:x", "updated_at": "2026-04-10"}


  def test_unknown_underscore_key_ignored(tmp_path: Path) -> None:
      """_meta가 아닌 _ 접두사 키는 조용히 무시된다."""
      path = tmp_path / "config_overrides.json"
      path.write_text(
          '{"_other": 1, "_scratch": "x", "MAX_LOSS_RATE": 0.02}',
          encoding="utf-8",
      )

      values, meta = config._load_overrides_from(path)

      assert values == {"MAX_LOSS_RATE": "0.02"}
      assert "_other" not in meta
      assert "_scratch" not in meta
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py -v`
  Expected: `test_meta_flattened_in_state` FAILs — `_meta` value (a dict) raises `RuntimeError: unsupported type`. `test_unknown_underscore_key_ignored` should already pass (underscore keys are skipped).

- [ ] **Step 3: Add `_meta` handling before the skip**

  In `src/config.py`, replace the loop body inside `_load_overrides_from()` with:

  ```python
      for key, value in data.items():
          if key == "_meta":
              if isinstance(value, dict):
                  meta.update(value)
              continue
          if key.startswith("_"):
              continue
          # bool은 int의 하위 타입이므로 반드시 먼저 체크한다.
          if isinstance(value, bool):
              values[key] = "true" if value else "false"
          elif isinstance(value, str):
              values[key] = value
          elif isinstance(value, (int, float)):
              values[key] = str(value)
          else:
              raise RuntimeError(
                  f"config_overrides.json: unsupported type for {key}: "
                  f"{type(value).__name__}"
              )
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py -v`
  Expected: all eight tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): flatten _meta and skip underscore-prefixed keys"
  ```

---

## Task 7: Error-path cases — malformed JSON, non-dict root, unsupported types (TDD)

**Files:**
- Modify: `tests/test_config.py`, `src/config.py`

- [ ] **Step 1: Add error-case tests**

  Append to `tests/test_config.py`:

  ```python
  def test_malformed_json_raises(tmp_path: Path) -> None:
      """깨진 JSON은 RuntimeError를 발생시킨다."""
      path = tmp_path / "config_overrides.json"
      path.write_text("{not json}", encoding="utf-8")

      with pytest.raises(RuntimeError, match="parse failed"):
          config._load_overrides_from(path)


  def test_root_not_object_raises(tmp_path: Path) -> None:
      """최상위가 객체가 아니면 RuntimeError를 발생시킨다."""
      path = tmp_path / "config_overrides.json"
      path.write_text("[1, 2, 3]", encoding="utf-8")

      with pytest.raises(RuntimeError, match="root must be an object"):
          config._load_overrides_from(path)


  def test_unsupported_list_value_raises(tmp_path: Path) -> None:
      """list 값은 지원하지 않으므로 RuntimeError."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"FOO": [1, 2]}', encoding="utf-8")

      with pytest.raises(RuntimeError, match="unsupported type for FOO"):
          config._load_overrides_from(path)


  def test_null_value_raises(tmp_path: Path) -> None:
      """null 값은 지원하지 않으므로 RuntimeError."""
      path = tmp_path / "config_overrides.json"
      path.write_text('{"FOO": null}', encoding="utf-8")

      with pytest.raises(RuntimeError, match="unsupported type for FOO"):
          config._load_overrides_from(path)
  ```

- [ ] **Step 2: Run — expect partial failure**

  Run: `pytest tests/test_config.py -v`
  Expected:
  - `test_malformed_json_raises` FAILs — currently `json.loads` raises `JSONDecodeError` (a subclass of `ValueError`, not `RuntimeError`).
  - `test_root_not_object_raises`, `test_unsupported_list_value_raises`, `test_null_value_raises` already PASS (Task 6 already wired those paths).

- [ ] **Step 3: Wrap `json.loads` in try/except**

  In `src/config.py`, replace:

  ```python
      raw_text = path.read_text(encoding="utf-8")
      data = json.loads(raw_text)
      if not isinstance(data, dict):
  ```

  with:

  ```python
      raw_text = path.read_text(encoding="utf-8")
      try:
          data = json.loads(raw_text)
      except json.JSONDecodeError as exc:
          raise RuntimeError(
              f"config_overrides.json parse failed: {exc}"
          ) from exc
      if not isinstance(data, dict):
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py -v`
  Expected: all twelve tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): fail-fast on malformed JSON in config_overrides"
  ```

---

## Task 8: Module-level wiring — `_load_overrides()` + import-time population

**Files:**
- Modify: `src/config.py` (add wrapper function + call site)

**Purpose:** Hook `_load_overrides_from()` into the module's import sequence so the module globals `_overrides` / `_overrides_meta` get populated automatically. This is the first time the loader will run at real import time.

- [ ] **Step 1: Add a test that exercises the wrapper with a temporary project root**

  Append to `tests/test_config.py`:

  ```python
  def test_load_overrides_populates_module_globals(
      tmp_path: Path, monkeypatch: pytest.MonkeyPatch
  ) -> None:
      """_load_overrides()는 _PROJECT_ROOT를 기반으로 모듈 전역을 채운다."""
      path = tmp_path / "config_overrides.json"
      path.write_text(
          '{"_meta": {"updated_by": "test"}, "MAX_LOSS_RATE": 0.04}',
          encoding="utf-8",
      )
      monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)

      config._load_overrides()

      assert config._overrides == {"MAX_LOSS_RATE": "0.04"}
      assert config._overrides_meta == {"updated_by": "test"}
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py::test_load_overrides_populates_module_globals -v`
  Expected: FAIL — `AttributeError: module 'src.config' has no attribute '_load_overrides'`.

- [ ] **Step 3: Add `_load_overrides()` wrapper and call it at import time**

  In `src/config.py`, immediately after the `_load_overrides_from()` function body add:

  ```python
  def _load_overrides() -> None:
      """프로젝트 루트의 config_overrides.json을 로드하여 모듈 전역을 채운다."""
      values, meta = _load_overrides_from(_PROJECT_ROOT / "config_overrides.json")
      _overrides.update(values)
      _overrides_meta.update(meta)
      if values:
          logger.info(
              "config_overrides loaded: %d keys (source=%s)",
              len(values),
              meta.get("updated_by", "unknown"),
          )


  _load_overrides()
  ```

  The bare `_load_overrides()` call at module top-level MUST be placed after the function definition and BEFORE any dataclass default_factory that could call `_env*`. Since all the existing config dataclasses (`KISConfig`, `DBConfig`, …) only read env values via `default_factory` when `Settings()` is instantiated (at module bottom, line ~299), placing `_load_overrides()` right after the function definition is safe.

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py::test_load_overrides_populates_module_globals -v`
  Expected: PASS.

- [ ] **Step 5: Run the full file to guard against fixture pollution**

  Run: `pytest tests/test_config.py -v`
  Expected: all thirteen tests pass. The `reset_overrides` fixture keeps the new test's mutations from leaking.

- [ ] **Step 6: Sanity-import the module**

  Run: `python -c "import src.config; print(len(src.config._overrides))"`
  Expected: prints `0` (no `config_overrides.json` exists at project root yet).

- [ ] **Step 7: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): wire _load_overrides at module import time"
  ```

---

## Task 9: Refactor `_env*` helpers to consult `_overrides` first (TDD)

**Files:**
- Modify: `tests/test_config.py`, `src/config.py`

- [ ] **Step 1: Add `_env*` override tests**

  Append to `tests/test_config.py`:

  ```python
  def test_env_helper_returns_override_when_present(
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      """_env는 _overrides에 값이 있으면 os.getenv보다 우선한다."""
      monkeypatch.setenv("MAX_LOSS_RATE", "0.01")
      config._overrides["MAX_LOSS_RATE"] = "0.04"

      assert config._env("MAX_LOSS_RATE") == "0.04"


  def test_env_helper_falls_back_to_os_getenv(
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      """_overrides에 없으면 os.getenv에서 읽는다."""
      monkeypatch.setenv("MAX_LOSS_RATE", "0.02")

      assert config._env("MAX_LOSS_RATE") == "0.02"


  def test_env_helper_uses_default_when_nothing_set(
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      """override와 env 모두 없으면 default를 반환한다."""
      monkeypatch.delenv("NONEXISTENT_KEY", raising=False)

      assert config._env("NONEXISTENT_KEY", "fallback") == "fallback"


  def test_env_int_honors_override(monkeypatch: pytest.MonkeyPatch) -> None:
      """_env_int도 override를 반영한다."""
      monkeypatch.setenv("SCREENING_TOP_N", "10")
      config._overrides["SCREENING_TOP_N"] = "25"

      assert config._env_int("SCREENING_TOP_N") == 25


  def test_env_float_honors_override(monkeypatch: pytest.MonkeyPatch) -> None:
      """_env_float도 override를 반영한다."""
      monkeypatch.setenv("MAX_LOSS_RATE", "0.03")
      config._overrides["MAX_LOSS_RATE"] = "0.025"

      assert config._env_float("MAX_LOSS_RATE") == 0.025
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py -v`
  Expected: the override-related tests FAIL because the current `_env*` helpers ignore `_overrides`. `test_env_helper_falls_back_to_os_getenv` and `test_env_helper_uses_default_when_nothing_set` should already pass.

- [ ] **Step 3: Refactor the three helpers**

  In `src/config.py`, replace:

  ```python
  def _env(key: str, default: str = "") -> str:
      """환경변수를 조회한다."""
      return os.getenv(key, default)


  def _env_int(key: str, default: int = 0) -> int:
      """환경변수를 정수로 조회한다."""
      return int(os.getenv(key, str(default)))


  def _env_float(key: str, default: float = 0.0) -> float:
      """환경변수를 실수로 조회한다."""
      return float(os.getenv(key, str(default)))
  ```

  with:

  ```python
  def _env(key: str, default: str = "") -> str:
      """환경변수를 조회한다. config_overrides.json 값이 있으면 우선한다."""
      if key in _overrides:
          return _overrides[key]
      return os.getenv(key, default)


  def _env_int(key: str, default: int = 0) -> int:
      """환경변수를 정수로 조회한다. override를 반영한다."""
      return int(_env(key, str(default)))


  def _env_float(key: str, default: float = 0.0) -> float:
      """환경변수를 실수로 조회한다. override를 반영한다."""
      return float(_env(key, str(default)))
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py -v`
  Expected: all eighteen tests pass.

- [ ] **Step 5: Full-suite regression check**

  Run: `pytest tests/ -q`
  Expected: all pre-existing tests in the repo still pass — this refactor must not regress anything.

- [ ] **Step 6: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): _env helpers consult override dict before os.getenv"
  ```

---

## Task 10: `OverrideState` exposure — `Settings.overrides` and `get_active_overrides()`

**Files:**
- Modify: `src/config.py`, `tests/test_config.py`

- [ ] **Step 1: Add exposure tests**

  Append to `tests/test_config.py`:

  ```python
  def test_get_active_overrides_returns_settings_overrides() -> None:
      """get_active_overrides()는 settings.overrides와 동일 객체를 반환한다."""
      state = config.get_active_overrides()

      assert state is config.settings.overrides
      assert isinstance(state, config.OverrideState)


  def test_override_state_has_expected_shape() -> None:
      """OverrideState는 values/meta/source_path/loaded를 노출한다."""
      state = config.get_active_overrides()

      assert isinstance(state.values, dict)
      assert isinstance(state.meta, dict)
      assert state.source_path.name == "config_overrides.json"
      assert isinstance(state.loaded, bool)
  ```

- [ ] **Step 2: Run — expect failure**

  Run: `pytest tests/test_config.py::test_get_active_overrides_returns_settings_overrides -v`
  Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'get_active_overrides'`.

- [ ] **Step 3: Add `_build_override_state()`, `Settings.overrides` field, `get_active_overrides()`**

  In `src/config.py`, immediately after the `_load_overrides()` function (and before `KISConfig`), add:

  ```python
  def _build_override_state() -> OverrideState:
      """현재 모듈 전역 _overrides/_overrides_meta를 기반으로 스냅샷을 만든다."""
      source_path = _PROJECT_ROOT / "config_overrides.json"
      return OverrideState(
          values=dict(_overrides),
          meta=dict(_overrides_meta),
          source_path=source_path,
          loaded=source_path.exists(),
      )
  ```

  Then modify the `Settings` dataclass (around the existing `telegram: TelegramConfig = ...` line near the bottom) to add an `overrides` field:

  ```python
  @dataclass(frozen=True)
  class Settings:
      """전체 설정을 통합 관리한다."""

      kis: KISConfig = field(default_factory=KISConfig)
      db: DBConfig = field(default_factory=DBConfig)
      calendar: CalendarConfig = field(default_factory=CalendarConfig)
      rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
      trading: TradingConfig = field(default_factory=TradingConfig)
      strategy: StrategyConfig = field(default_factory=StrategyConfig)
      screening: ScreeningConfig = field(default_factory=ScreeningConfig)
      health: HealthConfig = field(default_factory=HealthConfig)
      telegram: TelegramConfig = field(default_factory=TelegramConfig)
      overrides: OverrideState = field(default_factory=_build_override_state)
  ```

  Finally, after `settings = Settings()` at the very bottom, add:

  ```python
  def get_active_overrides() -> OverrideState:
      """현재 프로세스에 적용된 config override 상태를 반환한다.

      대시보드/디버깅 용도. ``settings.overrides``와 동일한 객체를 반환한다.
      """
      return settings.overrides
  ```

- [ ] **Step 4: Run — expect pass**

  Run: `pytest tests/test_config.py -v`
  Expected: all twenty tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/config.py tests/test_config.py
  git commit -m "feat(config): expose override state via Settings.overrides + get_active_overrides"
  ```

---

## Task 11: End-to-end validation — pytest / mypy / ruff

**Files:** No code changes. This task enforces the BRIDGE_SPEC acceptance gate.

- [ ] **Step 1: Full pytest run**

  Run: `pytest tests/ -q`
  Expected: 0 failures. If any existing test breaks, investigate — the refactor should have been transparent to `_env*` callers.

- [ ] **Step 2: mypy strict type check**

  Run: `python -m mypy src/`
  Expected: `Success: no issues found`.

  If mypy complains about `meta.get("updated_by", "unknown")` returning `Any`, cast the result:
  `str(meta.get("updated_by", "unknown"))` inside the `logger.info` call.

- [ ] **Step 3: ruff lint**

  Run: `ruff check src/ tests/`
  Expected: `All checks passed!`

  If ruff flags the `isinstance(value, (int, float))` tuple form (newer rules prefer `int | float`), change it to:
  `elif isinstance(value, (int, float)):` → `elif isinstance(value, int | float):` — both are valid on Python 3.12.

- [ ] **Step 4: Manual smoke check of the import-time log message**

  Create a temporary `config_overrides.json` at the project root with real content, run a Python import, and confirm the info log line appears. Then delete the temp file.

  ```bash
  cat > config_overrides.json <<'JSON'
  {
    "_meta": {"updated_by": "smoke-test", "updated_at": "2026-04-10"},
    "MAX_LOSS_RATE": 0.025
  }
  JSON
  python -c "import src.config; print('max_loss:', src.config.settings.trading.max_loss_rate); print('overrides:', src.config.get_active_overrides().values)"
  rm config_overrides.json
  ```

  Expected output:
  ```
  max_loss: 0.025
  overrides: {'MAX_LOSS_RATE': '0.025'}
  ```

  (The info log line — `config_overrides loaded: 1 keys (source=smoke-test)` — may or may not print depending on whether root logger handlers are initialized at that moment; the key correctness signal is that `max_loss_rate` reflects the override value.)

- [ ] **Step 5: Confirm `.gitignore` does NOT list `config_overrides.json`**

  Run: `grep -n "config_overrides" .gitignore || echo "not listed (correct)"`
  Expected: `not listed (correct)` — per spec §7, the file is tracked.

- [ ] **Step 6: Final commit if any fixes were needed**

  If Steps 2–3 required the mypy/ruff tweaks noted above:

  ```bash
  git add src/config.py
  git commit -m "chore(config): satisfy mypy/ruff on override loader"
  ```

  If no fixes were needed, skip this step.

---

## Post-implementation notes

- This change ships the loader infrastructure only. No `config_overrides.json` file is created as part of this plan. The first real parameter tuning via overrides is a separate Cowork proposal.
- After merging, Cowork-generated proposals in `docs/proposals/` with `카테고리: param_tuning` will write/modify `config_overrides.json` directly. That file is explicitly excluded from BRIDGE_SPEC's 5-file change limit.
- Dashboard integration (`dashboard/` pages showing "현재 적용 중인 override") is a deferred follow-up per spec §11 and is not part of this plan.
