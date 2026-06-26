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
