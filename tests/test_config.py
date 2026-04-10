"""src/config.py 오버라이드 로더 테스트."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from src import config


@pytest.fixture(autouse=True)
def reset_overrides() -> Iterator[None]:
    """각 테스트 전후에 모듈 전역 _overrides/_overrides_meta를 초기화한다.

    테스트 시작 전에 기존 상태를 저장·클리어하고, 종료 후 복원한다.
    Task 8에서 _load_overrides()가 import 시점에 모듈 전역을 채우게 되면
    해당 상태는 이 fixture에 의해 각 테스트 경계에서 일시적으로 비워진다.
    """
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


def test_str_override_applied(tmp_path: Path) -> None:
    """문자열 값이 그대로 values에 저장된다."""
    path = tmp_path / "config_overrides.json"
    path.write_text('{"STRATEGY_ENSEMBLE_METHOD": "majority"}', encoding="utf-8")

    values, meta = config._load_overrides_from(path)

    assert values == {"STRATEGY_ENSEMBLE_METHOD": "majority"}
    assert meta == {}


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
