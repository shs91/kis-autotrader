# [Design] config_overrides.json 로더

## 참조
- 규격: `docs/BRIDGE_SPEC.md` (§ 파라미터 변경 메커니즘, `config_overrides.json` 규격)
- 대상 파일: `src/config.py`
- 작성일: 2026-04-10

---

## 1. 배경 / 목적

Cowork ↔ Claude Code 자동 구현 파이프라인은 파라미터 튜닝 제안서를 `config_overrides.json`을 통해 적용하도록 `docs/BRIDGE_SPEC.md`에 명시되어 있다. `.env` 파일은 안전 게이트의 금지 영역이므로 직접 수정할 수 없기 때문이다.

그러나 현재 `src/config.py`는 `load_dotenv()`만 호출하고 `config_overrides.json`은 읽지 않는다. 이 설계는 `config.py`가 해당 파일을 로드하여 `_env*` 헬퍼가 반환하는 값을 런타임에 덮어쓰도록 하는 로딩 로직을 정의한다.

---

## 2. 설계 원칙

1. **`.env` 불변** — `config_overrides.json`은 `.env`를 수정하지 않고, 런타임에 우선 조회되는 별도의 dict로만 관리한다.
2. **범위 검증 비중복** — BRIDGE_SPEC의 안전 게이트가 제안서 구현 시점에 이미 허용 키/범위를 검증한다. `config.py`는 파일 무결성(파싱 가능성, 타입 유효성)만 책임지고 파라미터 범위 테이블을 복제하지 않는다.
3. **부작용 없음** — `os.environ`을 수정하지 않는다. override는 내부 dict에만 반영되며, 하위 프로세스/테스트로 전파되지 않는다.
4. **시작 시 fail-fast** — 파일은 선택적이지만, 존재할 때 파싱/타입 오류가 있으면 프로세스 시작을 거부한다. 부분 적용 상태로 구동되는 것을 방지한다.
5. **관찰 가능성** — 어떤 키가 오버라이드됐는지 로그와 API 양쪽으로 노출한다.

---

## 3. 파일 위치 & 로드 순서

- 경로: `<프로젝트 루트>/config_overrides.json` (`.env`와 동일 레벨)
- 해석 방법: `Path(__file__).resolve().parent.parent / "config_overrides.json"` (`src/config.py` 기준)
- 로드 순서는 `src/config.py` 모듈 상단에서 아래 순서로 고정:
  1. `load_dotenv()` — 기존 동작 유지
  2. `_overrides, _overrides_meta = _load_overrides()` — 파일이 없으면 빈 dict, 있으면 검증 후 반영
  3. `settings = Settings()` — override가 이미 적재된 상태에서 dataclass 기본값이 계산되므로 모든 dataclass 필드에 자동 반영

---

## 4. `_load_overrides()` 로직

### 4.1 함수 시그니처

```python
def _load_overrides() -> tuple[dict[str, str], dict[str, Any]]:
    """config_overrides.json을 로드하여 (values, meta) 튜플을 반환한다.

    - 파일이 없으면 ({}, {})를 반환한다.
    - 파싱/타입 오류 시 RuntimeError를 발생시켜 프로세스 시작을 중단시킨다.
    """
```

### 4.2 처리 흐름

1. 경로 `PROJECT_ROOT / "config_overrides.json"` 계산
2. 파일 미존재 → `logger.debug("config_overrides.json not found, using .env only")` 후 `({}, {})` 반환
3. `json.loads(path.read_text(encoding="utf-8"))` 시도
   - 실패 → `RuntimeError(f"config_overrides.json parse failed: {e}")`
4. 최상위가 `dict`가 아니면 → `RuntimeError("config_overrides.json root must be an object")`
5. 각 `(key, value)` 순회:
   - `key == "_meta"`: `value`가 dict이면 `meta.update(value)`로 평탄화 저장, dict가 아니면 무시 (타입 검증 없음 — 메타는 스키마를 강제하지 않는다)
   - `key.startswith("_")` 이고 `_meta`가 아닌 경우: 무시 (경고 로그 없음)
   - 값 타입이 `(str, int, float, bool)` 중 하나가 아니면 → `RuntimeError(f"config_overrides.json: unsupported type for {key}: {type(value).__name__}")`
   - 타입별 문자열 변환:
     - `bool`: `"true"` / `"false"` (소문자 — 기존 `HEALTH_ENABLED`, `TELEGRAM_ENABLED`의 `.lower() == "true"` 비교와 호환)
     - `int` / `float`: `str(value)`
     - `str`: 그대로
   - `values[key] = 변환된 문자열`
6. 시작 로그:
   ```python
   if values:
       logger.info(
           "config_overrides loaded: %d keys (source=%s)",
           len(values),
           meta.get("updated_by", "unknown"),
       )
   ```
7. `(values, meta)` 반환

### 4.3 범위/허용 키 검증은 하지 않는다

BRIDGE_SPEC의 허용 파라미터 테이블을 `config.py`에 복제하지 않는다. 검증은 제안서 구현 시점에 Claude Code가 수행하며, `config.py`는 이를 신뢰한다.

### 4.4 테스트용 주입 훅

테스트에서 임의 경로의 JSON을 로드할 수 있도록 하위 함수를 분리한다:

```python
def _load_overrides_from(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """지정한 경로에서 overrides를 로드한다. _load_overrides()의 내부 구현."""
    ...

def _load_overrides() -> tuple[dict[str, str], dict[str, Any]]:
    return _load_overrides_from(_PROJECT_ROOT / "config_overrides.json")
```

---

## 5. `_env*` 헬퍼 개조

### 5.1 변경 전

```python
def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def _env_int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))

def _env_float(key: str, default: float = 0.0) -> float:
    return float(os.getenv(key, str(default)))
```

### 5.2 변경 후

```python
_overrides: dict[str, str] = {}
_overrides_meta: dict[str, Any] = {}


def _env(key: str, default: str = "") -> str:
    if key in _overrides:
        return _overrides[key]
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(_env(key, str(default)))


def _env_float(key: str, default: float = 0.0) -> float:
    return float(_env(key, str(default)))
```

포인트:
- `_env_int`/`_env_float`가 `os.getenv`를 직접 호출하던 것을 `_env()`를 경유하도록 변경 → 한 곳만 고치면 세 헬퍼 전부 override를 본다.
- `_overrides`는 모듈 전역. `_load_overrides()` 직후 `_overrides.update(values)`, `_overrides_meta.update(meta)`로 채운다.

---

## 6. 가시성 노출

### 6.1 `OverrideState` dataclass 신설

```python
@dataclass(frozen=True)
class OverrideState:
    """config_overrides.json 적용 상태 스냅샷."""

    values: dict[str, str]           # 적용된 key → string 값
    meta: dict[str, Any]             # _meta 내용물 (평탄화 — updated_at, updated_by 등)
    source_path: Path                # config_overrides.json 절대 경로
    loaded: bool                     # 파일 존재 여부
```

### 6.2 `Settings.overrides` 필드 추가

```python
@dataclass(frozen=True)
class Settings:
    ...
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    overrides: OverrideState = field(default_factory=_build_override_state)
```

`_build_override_state()`는 이미 로드된 모듈 전역 `_overrides` / `_overrides_meta`를 기반으로 `OverrideState` 인스턴스를 만든다 (파일을 재파싱하지 않는다).

### 6.3 `get_active_overrides()` 모듈 함수

```python
def get_active_overrides() -> OverrideState:
    """현재 프로세스에 적용된 config override 상태를 반환한다.

    대시보드/디버깅 용도. `settings.overrides`와 동일한 값을 반환한다.
    """
    return settings.overrides
```

대시보드는 `from src.config import get_active_overrides`로 간편 조회 가능. 내부 테스트나 다른 모듈에서도 동일한 스냅샷에 접근한다.

---

## 7. 안전/영향 범위

- 현재 코드베이스에서 `os.getenv`는 `src/config.py` 3곳(`_env`, `_env_int`, `_env_float`)에만 존재. 다른 모든 설정은 `settings.*`를 통해 소비된다. → override가 모든 소비 경로를 커버한다.
- `.env` 파일은 수정하지 않음 → BRIDGE_SPEC 금지 영역 준수.
- `config_overrides.json`은 BRIDGE_SPEC상 "5파일 제한에 포함되지 않음" — 본 변경의 제안서/PR은 이 파일을 만들거나 수정하지 않는다 (실제 override 값 쓰기는 이후 Cowork 제안서가 수행).
- `.gitignore`: **추적 유지**. CHANGELOG + proposals 감사 모델과 일치시키며, 현재 운영 값이 git 히스토리로 보존된다. `.gitignore`에 추가하지 않는다.
- 하위 프로세스 전파 없음: `os.environ`을 건드리지 않으므로 `subprocess`/`launchctl`로 상속되는 환경변수에는 영향 없음.

---

## 8. 테스트 계획 (`tests/test_config.py` 신규)

테스트는 `_load_overrides_from(path)`를 직접 호출하거나 `monkeypatch`로 모듈 전역 `_overrides`를 교체하는 방식으로 구성한다. `tmp_path`에 임시 JSON을 작성한 뒤 로더에 주입한다.

| # | 케이스 | 검증 |
|---|--------|------|
| 1 | `test_no_override_file` | `tmp_path`에 파일 없음 → `_load_overrides_from()`이 `({}, {})` 반환 |
| 2 | `test_basic_float_override_applied` | `{"MAX_LOSS_RATE": 0.025}` → `_env_float("MAX_LOSS_RATE")` == 0.025 |
| 3 | `test_basic_int_override_applied` | `{"SCREENING_TOP_N": 15}` → `_env_int("SCREENING_TOP_N")` == 15 |
| 4 | `test_str_override_applied` | `{"STRATEGY_ENSEMBLE_METHOD": "majority"}` → `_env(...)` == `"majority"` |
| 5 | `test_bool_coercion_true_false` | `{"HEALTH_ENABLED": false}` → `_env("HEALTH_ENABLED")` == `"false"` |
| 6 | `test_meta_flattened_in_state` | `{"_meta": {"updated_by": "x"}, "MAX_LOSS_RATE": 0.02}` → `meta["updated_by"] == "x"` (평탄화), `values`에는 `_meta` 없음 |
| 7 | `test_unknown_underscore_key_ignored` | `{"_other": 1, "MAX_LOSS_RATE": 0.02}` → `_other`는 values/meta 모두에 없음 |
| 8 | `test_override_precedence_over_env` | `monkeypatch.setenv("MAX_LOSS_RATE", "0.01")` + override `0.04` → `_env_float` == 0.04 |
| 9 | `test_env_used_when_no_override` | override 비어 있고 env만 세팅 → env 값 반환 |
| 10 | `test_malformed_json_raises` | `{not json}` → `RuntimeError` |
| 11 | `test_root_not_object_raises` | `[1,2,3]` → `RuntimeError` |
| 12 | `test_unsupported_type_raises` | `{"FOO": [1,2]}` → `RuntimeError` |
| 13 | `test_null_value_raises` | `{"FOO": null}` → `RuntimeError` (None은 지원 타입 아님) |
| 14 | `test_get_active_overrides_exposes_loaded_state` | 모듈 로드 후 `get_active_overrides().values`와 `settings.overrides.values`가 동일하고, `loaded` 플래그와 `source_path`가 기대값 |

타입 체크/린트:
- `python -m mypy src/` 통과
- `ruff check src/` 통과
- `pytest tests/test_config.py -v` 전부 pass

---

## 9. 변경 요약

| 파일 | 변경 종류 | 내용 |
|------|-----------|------|
| `src/config.py` | 수정 | `_PROJECT_ROOT` 상수, `OverrideState` dataclass, `_load_overrides_from()` / `_load_overrides()` 함수, 모듈 전역 `_overrides` / `_overrides_meta`, `_env*` 헬퍼 개조, `Settings.overrides` 필드, `_build_override_state()`, `get_active_overrides()` |
| `tests/test_config.py` | 신규 | § 8의 14개 테스트 케이스 |

BRIDGE_SPEC 코드 변경 규칙 준수: 변경 파일 2개 (상한 5개 이하), `src/config.py`는 기존 파일 수정, 테스트는 `tests/` 하위 신규.

---

## 10. 롤백

문제 발생 시:
1. `git restore src/config.py tests/test_config.py` — 원복
2. 프로세스 재시작 (`launchctl stop/start com.kis.autotrader`)

`config_overrides.json` 자체는 이 변경에서 생성되지 않으므로 롤백 대상에 포함되지 않는다.

---

## 11. 오픈 이슈 / 후속 작업

- 본 구현 이후, Cowork가 작성하는 첫 파라미터 튜닝 제안서는 `config_overrides.json`을 실제로 생성/수정하게 된다. 그 제안서는 본 설계와 별개 PR로 처리.
- 대시보드(`dashboard/`)에서 `get_active_overrides()`를 호출해 "현재 적용 중인 override" 섹션을 표시하는 것은 선택적 후속 과제. 이 설계에는 포함하지 않는다.
