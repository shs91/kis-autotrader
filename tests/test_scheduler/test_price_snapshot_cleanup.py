"""가격 스냅샷 정리 잡 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.scheduler.jobs import TradingScheduler


def test_cleanup_job_deletes_old() -> None:
    """7일 초과 스냅샷 삭제 메서드(delete_older_than)가 단 1회 호출되는지 검증한다."""
    jobs = TradingScheduler()
    fake_repo = MagicMock()
    fake_repo.delete_older_than.return_value = 5
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with (
        patch("src.db.session.get_session", return_value=fake_session),
        patch("src.db.repository.PriceSnapshotRepository", return_value=fake_repo),
        patch("src.db.repository.CandidateSnapshotRepository", return_value=fake_repo),
    ):
        jobs.cleanup_price_snapshots_job()

    # 가격·후보 두 repo의 delete_older_than이 호출된다(동일 fake_repo이므로 2회).
    assert fake_repo.delete_older_than.call_count == 2


def test_cleanup_job_retention_split() -> None:
    """가격=7일, 후보=30일 보존으로 분리 정리됨을 검증(레짐 비교용 장기 보존)."""
    from datetime import UTC, datetime

    jobs = TradingScheduler()
    price_repo = MagicMock()
    price_repo.delete_older_than.return_value = 5
    cand_repo = MagicMock()
    cand_repo.delete_older_than.return_value = 3
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with (
        patch("src.db.session.get_session", return_value=fake_session),
        patch("src.db.repository.PriceSnapshotRepository", return_value=price_repo),
        patch("src.db.repository.CandidateSnapshotRepository", return_value=cand_repo),
    ):
        jobs.cleanup_price_snapshots_job()

    now = datetime.now(UTC)
    price_cutoff = price_repo.delete_older_than.call_args.args[0]
    cand_cutoff = cand_repo.delete_older_than.call_args.args[0]
    # 가격 7일·후보 30일(±1일 허용)
    assert abs((now - price_cutoff).days - 7) <= 1
    assert abs((now - cand_cutoff).days - 30) <= 1
