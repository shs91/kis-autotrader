"""sync_proposals_md_to_db.py TDD."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scripts.harness.sync_proposals_md_to_db import (
    backfill_predictions,
    parse_proposal,
    sync_directory,
)
from src.db.models import Base
from src.db.repository import ProposalRepository


@pytest.fixture
def session():
    # SQLite 컴파일러에 JSONB를 JSON으로 렌더링하는 방법 등록 (Base.metadata.create_all 호환).
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"

        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def test_parse_proposal_extracts_meta(tmp_path: Path):
    f = tmp_path / "2026-05-14_x.md"
    f.write_text(
        "# 제목\n\n## 메타데이터\n- 작성: Cowork\n- 일자: 2026-05-14\n"
        "- 상태: implemented\n- 우선순위: high\n- 카테고리: bug_fix\n"
        "- 관련파일: src/x.py\n\n## 본문\n…",
        encoding="utf-8",
    )
    parsed = parse_proposal(f)
    assert parsed["state"] == "implemented"
    assert parsed["category"] == "bug_fix"
    assert parsed["priority"] == "high"
    assert parsed["title"] == "제목"


def test_parse_proposal_unknown_priority_defaults_to_medium(tmp_path: Path):
    f = tmp_path / "y.md"
    f.write_text("# T\n\n## 메타데이터\n- 상태: ready\n- 카테고리: refactor\n", encoding="utf-8")
    parsed = parse_proposal(f)
    assert parsed["priority"] == "medium"


def test_sync_directory_inserts_all_then_skips_existing(tmp_path: Path, session):
    (tmp_path / "a.md").write_text(
        "# A\n\n## 메타데이터\n- 상태: implemented\n- 카테고리: bug_fix\n- 우선순위: high\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "# B\n\n## 메타데이터\n- 상태: ready\n- 카테고리: param_tuning\n- 우선순위: medium\n",
        encoding="utf-8",
    )
    inserted, skipped = sync_directory(tmp_path, session)
    session.commit()
    assert (inserted, skipped) == (2, 0)

    repo = ProposalRepository(session)
    assert repo.find_by_path(str((tmp_path / "a.md").resolve())) is not None

    # 두 번째 실행은 모두 skip
    inserted2, skipped2 = sync_directory(tmp_path, session)
    session.commit()
    assert (inserted2, skipped2) == (0, 2)


# ── backfill_predictions ────────────────────────────────────────


def test_backfill_predictions_updates_existing_when_prediction_present(
    tmp_path: Path, session
):
    md = tmp_path / "p.md"
    md.write_text(
        "# P\n\n## 메타데이터\n- 상태: ready\n- 카테고리: bug_fix\n- 우선순위: high\n",
        encoding="utf-8",
    )
    sync_directory(tmp_path, session)
    session.commit()

    # prediction 섹션을 사후 추가 (백필 시나리오: 기존 row + 나중에 본문 보강)
    md.write_text(
        "# P\n\n## 메타데이터\n- 상태: ready\n- 카테고리: bug_fix\n- 우선순위: high\n\n"
        "## 기대 효과\n- win_rate_delta_pp: 1.5\n- error_count_delta_ratio: -0.25\n",
        encoding="utf-8",
    )

    updated, skipped = backfill_predictions(tmp_path, session)
    session.commit()
    assert (updated, skipped) == (1, 0)

    repo = ProposalRepository(session)
    row = repo.find_by_path(str(md.resolve()))
    assert row is not None
    assert row.prediction == {
        "win_rate_delta_pp": 1.5,
        "error_count_delta_ratio": -0.25,
    }


def test_backfill_predictions_skips_when_no_prediction_section(
    tmp_path: Path, session
):
    md = tmp_path / "q.md"
    md.write_text(
        "# Q\n\n## 메타데이터\n- 상태: ready\n- 카테고리: refactor\n- 우선순위: low\n",
        encoding="utf-8",
    )
    sync_directory(tmp_path, session)
    session.commit()

    updated, skipped = backfill_predictions(tmp_path, session)
    assert (updated, skipped) == (0, 1)


def test_backfill_predictions_skips_unknown_path(tmp_path: Path, session):
    # DB에 등록되지 않은 markdown은 skip (insert 안 함)
    md = tmp_path / "new.md"
    md.write_text(
        "# N\n\n## 메타데이터\n- 상태: ready\n- 카테고리: bug_fix\n- 우선순위: high\n\n"
        "## 기대 효과\n- win_rate_delta_pp: 2.0\n",
        encoding="utf-8",
    )
    updated, skipped = backfill_predictions(tmp_path, session)
    assert (updated, skipped) == (0, 1)
    repo = ProposalRepository(session)
    assert repo.find_by_path(str(md.resolve())) is None
