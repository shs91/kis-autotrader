"""골든 셋 10건이 현재 워크트리에서 모두 통과해야 한다.

이 테스트가 실패하면 동일 카테고리 회귀가 들어왔다는 신호.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.golden.loader import GoldenCase, load_cases
from src.harness.golden.runner import evaluate_case

GOLDEN_DIR = Path(__file__).resolve().parent / "golden_proposals"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cases() -> list[GoldenCase]:
    return load_cases(GOLDEN_DIR, strict=True)


def test_golden_set_has_at_least_10_cases(cases: list[GoldenCase]) -> None:
    assert len(cases) >= 10


@pytest.mark.parametrize(
    "case_id",
    [
        "G01_dtz_engine_queue",
        "G02_dtz_timestamptz_listener",
        "G03_dtz_repository_utcnow",
        "G04_screening_query_kst",
        "G05_engine_daily_threshold",
        "G06_ma_nan_guard",
        "G07_screener_etf_blocklist",
        "G08_notify_error_signature",
        "G09_dtz_ruleset_active",
        "G10_proposals_table_migrated",
    ],
)
def test_golden_case_passes(cases: list[GoldenCase], case_id: str) -> None:
    case = next((c for c in cases if c.id == case_id), None)
    assert case is not None, f"case {case_id} not loaded"
    result = evaluate_case(case, repo_root=REPO_ROOT)
    assert result.passed, f"{case_id}: {result.detail}"
