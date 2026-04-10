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
