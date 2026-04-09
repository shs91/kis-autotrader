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
