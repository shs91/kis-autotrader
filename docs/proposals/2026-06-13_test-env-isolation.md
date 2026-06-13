# 테스트 환경 격리 — 운영(real) .env가 pytest에 누수되어 8건이 깨지는 결함 수정

## 메타데이터
- 작성: Claude Code
- 일자: 2026-06-13
- 상태: ready
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: tests/conftest.py(신설), tests/test_harness/test_pipeline_cli.py

> 배경: 2026-06-12 `aggressive-entry-tuning`(v0.10.1) 구현 중, real 운영 환경에서 `pytest tests/`가 제안서·코드와 무관하게 8건 실패하는 것을 확정했다. 원인은 테스트 격리 결함이며, 이로 인해 BRIDGE_SPEC의 "pytest 전체 그린" 게이트가 real 환경에서 구조적으로 무력화된다(모든 제안서가 형식상 failed 위험).

## 현상 분석

`KIS_ENV=real`(현재 운영) 상태에서 `pytest tests/`를 돌리면 항상 **8건 실패**한다. `git stash push -- config_overrides.json` baseline에서도 동일하게 재현되어, 제안서/코드 변경과 **무관한 사전 존재 실패**임이 확정됐다.

### 실패 8건 분류 (실측)

| 테스트 | 실패 양상 | 근본 원인 | 위험도 |
|--------|-----------|-----------|--------|
| `test_harness/test_pipeline_cli.py` (6건) | fixture `x.md` 대신 real DB의 ready 제안서 반환 / CLI `exit 1` | subprocess CLI가 **real DB(kis_trader_real)** 연결 | **높음 — 운영 DB 조회/쓰기** |
| `test_api/test_order.py::test_buy_passes_correct_tr_id` (1건) | `TTTC0802U` ≠ `VTTC0802U` | `KIS_ENV=real` → 실전 TR ID | 낮음 (read-only) |
| `test_strategy/test_rsi.py::test_default_init` (1건) | `RSI(9)` ≠ `RSI(14)` | `.env` `STRATEGY_RSI_PERIOD=9` | 낮음 (read-only) |

### 근본 원인

**`tests/conftest.py`가 존재하지 않아, 운영 `.env`(`KIS_ENV=real`, `DATABASE_URL_REAL`, `STRATEGY_*`)가 테스트 프로세스에 그대로 누수된다.**

1. **pipeline_cli (최우선).** `db_session` fixture는 격리를 시도하나 불완전하다:
   ```python
   # tests/test_harness/test_pipeline_cli.py:37
   monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")  # DATABASE_URL만 교체
   ```
   그러나 `config.py:159-160`은 `KIS_ENV=real`이면 **`DATABASE_URL_REAL`을 우선**한다:
   ```python
   env = _env("KIS_ENV", "virtual")
   env_key = "DATABASE_URL_REAL" if env == "real" else "DATABASE_URL"
   ```
   → `DATABASE_URL=sqlite` 오버라이드가 무시되고, subprocess(`_run`)로 띄운 CLI가 **real DB에 연결**된다. virtual 개발 환경에서는 `DATABASE_URL`이 쓰여 통과하므로 이 결함이 지금까지 은폐됐다.
   - **위험**: `pipeline_mark_in_flight`/`mark_implemented` 등은 real `proposals` 테이블에 `UPDATE`를 시도할 수 있어 **운영 데이터 오염 가능**. `test_list_ready`는 실제로 운영 제안서(직전 적재된 id=48)를 반환했다.

2. **test_order.** `order.py:18-23`의 `(env, type)→tr_id` 맵에서 `KIS_ENV=real`이라 `TTTC0802U`(실전) 반환. 테스트는 `VTTC0802U`(모의) 기대.

3. **test_rsi.** `config.py:313` `rsi_period = _env_int("STRATEGY_RSI_PERIOD", 14)`. `.env`에 `STRATEGY_RSI_PERIOD=9`가 있어 `RSIStrategy()` 기본이 `RSI(9)`. 테스트는 코드 기본값 `RSI(14)` 기대.

> **공통 분모**: 세 원인 모두 "운영 `.env` 환경변수가 테스트에 새는 것"이다. 테스트 프로세스를 `virtual`로 고정하고 운영 튜닝값을 차단하면 일괄 해소된다.

## 제안 내용

`tests/conftest.py`를 신설하여 **pytest 세션 시작 시점(테스트 수집·`src.config` import 이전)에 운영 환경변수를 차단**한다. `conftest.py`는 pytest가 가장 먼저 import하므로, 이후 `settings = Settings()`가 항상 `virtual` 기준으로 로드된다.

- **축 1 — 환경/DB 고정**: `KIS_ENV=virtual` 강제 + `DATABASE_URL_REAL` 제거. → pipeline_cli 6건 + test_order 1건 해결. real DB 오염 위험 제거.
- **축 2 — 전략 튜닝값 차단**: `.env`의 `STRATEGY_*`/`SCREENING_*` 운영 튜닝값을 제거해 테스트가 **코드 기본값**으로 결정론화. → test_rsi 1건 해결.
- **축 3 — subprocess 이중 방어**(선택): pipeline_cli `db_session` fixture에 `KIS_ENV`/`DATABASE_URL_REAL` 격리를 명시해, conftest와 독립적으로도 안전하게.

> **범위 경계**: 본 제안은 **`.env` 환경변수 누수**만 차단한다. `config_overrides.json`(파일) 누수는 환경변수 pop으로 막히지 않으므로(예: `STRATEGY_MIN_CONFIDENCE`는 파일에서 로드), 개별 테스트의 명시 주입으로 방어한다 — v0.10.1에서 `RiskManager(min_confidence=...)` 주입으로 `test_risk`를 격리한 패턴과 동일. 이는 별도 후속 과제(§ 후속)로 둔다.

## 변경 스펙

### 파일별 변경사항

#### `tests/conftest.py` (신설)

```python
"""pytest 전역 설정 — 운영(real) .env가 테스트에 누수되지 않도록 격리.

이 모듈은 pytest가 테스트 수집 전에 가장 먼저 import한다. 따라서 여기서
os.environ을 정리하면, 이후 어떤 테스트 모듈이 src.config를 import해도
settings = Settings()가 virtual + 코드 기본값 기준으로 로드된다.

배경: KIS_ENV=real 운영 환경에서 pytest를 돌리면 config가 DATABASE_URL_REAL/
실전 TR ID/운영 전략 튜닝값을 읽어, 환경 의존 테스트 8건이 깨졌다
(2026-06-13 확정). 자세한 내용은 docs/proposals/2026-06-13_test-env-isolation.md.
"""

from __future__ import annotations

import os

# 축 1 — 환경/DB 고정: config.py가 KIS_ENV=real이면 DATABASE_URL_REAL·실전
# TR ID를 쓰므로, 테스트는 항상 virtual로 고정해 모의 TR ID·테스트 DB를 쓴다.
os.environ["KIS_ENV"] = "virtual"
os.environ.pop("DATABASE_URL_REAL", None)

# 축 2 — 전략/스크리닝 튜닝값 차단: 운영 .env의 STRATEGY_*/SCREENING_* 값을
# 제거해, 전략 테스트가 코드 기본값(예: RSI_PERIOD 기본 14)으로 결정론화한다.
# (config_overrides.json 파일 누수는 개별 테스트의 명시 주입으로 방어 — 본 범위 밖)
for _key in list(os.environ):
    if _key.startswith(("STRATEGY_", "SCREENING_")):
        os.environ.pop(_key, None)
```

#### `tests/test_harness/test_pipeline_cli.py` (축 3 — 이중 방어, 선택)

`db_session` fixture(현재 line 37 부근)에 2줄 추가:

```python
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("KIS_ENV", "virtual")             # 추가: DATABASE_URL_REAL 우선 방지
    monkeypatch.delenv("DATABASE_URL_REAL", raising=False)  # 추가: real DB 누수 차단
```

> conftest만으로도 해결되나, fixture가 subprocess 격리를 명시하면 conftest 변경에 독립적으로 안전하고 의도가 드러난다.

### 추가 테스트 (필요 시)

- `tests/test_harness/test_conftest_isolation.py` (선택): conftest 적용 후 `os.environ["KIS_ENV"] == "virtual"`, `"DATABASE_URL_REAL" not in os.environ`, `"STRATEGY_RSI_PERIOD" not in os.environ`를 단언하는 회귀 가드 1~3건.

## 기대 효과

- **real 환경에서 `pytest tests/` 8건 실패 → 0건** (제안서 유발 회귀 없이 사전 존재 실패 해소).
- **BRIDGE_SPEC "pytest 전체 그린" 게이트 복구** — real 운영 환경에서도 제안서 자동 구현 검증이 정상 작동.
- **운영 DB 오염 위험 제거** — pipeline_cli subprocess가 더 이상 `kis_trader_real`에 연결하지 않음.
- 부수적으로, 향후 모든 테스트가 운영 `.env` 변동(전략 튜닝 등)에 영향받지 않고 **결정론적**으로 동작.

## 리스크 / 비용 경고

- **전역 conftest 영향 범위**: `tests/conftest.py`는 1,000여 개 전체 테스트에 적용된다. `KIS_ENV=virtual` 고정으로 인해, `KIS_ENV=real`에서만 활성화되는 동작(`config.py:255` 부근, real 한정 기능)을 **명시적으로 검증하던 테스트가 있다면 영향**받을 수 있다. → 구현 시 `pytest tests/`로 신규 회귀 0 확인 필수.
- **STRATEGY_*/SCREENING_* 일괄 제거 보수성**: 특정 운영 튜닝값을 전제하던 테스트가 있으면 코드 기본값으로 바뀌며 깨질 수 있다. 만약 신규 회귀가 발생하면, 축 2를 `STRATEGY_RSI_PERIOD`만 콕 집어 제거하는 최소 범위로 축소한다(test_rsi만 해결, 안전 우선).
- **config_overrides.json 누수는 미해결**: 본 제안은 `.env`만 차단한다. 파일 기반 오버라이드(`STRATEGY_MIN_CONFIDENCE` 등)에 의존하는 테스트는 개별 명시 주입으로 별도 방어해야 한다(§ 후속).

## 검증 (구현 후 필수)

```bash
pytest tests/ -q          # real 환경에서 8 failed → 0 failed 확인, 신규 회귀 0
python -m mypy src/       # 변경은 tests/ 한정이나 전체 통과 확인
ruff check tests/conftest.py tests/test_harness/test_pipeline_cli.py
```

- 구현은 **반드시 현재 운영 환경(`KIS_ENV=real`)에서 검증**해야 한다. virtual에서는 결함이 재현되지 않으므로 효과를 확인할 수 없다.

## 롤백

- `tests/conftest.py` 삭제(또는 내용 제거)로 즉시 원복. 운영 코드(`src/`)·매매 동작에 전혀 영향 없음(테스트 전용 변경).
- 축 3(pipeline_cli fixture)만 단독 롤백도 가능.

## 후속 (별도 제안 후보)

- **config_overrides.json 테스트 격리**: 파일 기반 오버라이드가 테스트에 누수되는 문제. `RiskManager.min_confidence` 주입(v0.10.1) 같은 개별 방어를 표준화하거나, `config.py`에 테스트 모드(`PYTEST_RUNNING` 시 오버라이드 미로드) 도입 검토.
- **`TestCheckBuyGates` 잠재 결합**: `test_risk.py`의 `TestCheckBuyGates`도 `RiskManager()`를 운영값으로 생성한다(현재는 통과하나, min_confidence 추가 변경 시 깨질 잠재). v0.10.1의 `TestValidateOrder`와 동일하게 `min_confidence` 명시 주입 권장.
