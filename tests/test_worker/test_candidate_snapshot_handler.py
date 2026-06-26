"""CandidateSnapshotHandler 테스트 (shadow 검증)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.worker.handlers import CandidateSnapshotHandler


@pytest.mark.asyncio
async def test_handler_records_snapshot() -> None:
    fake_repo = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with patch("src.db.session.get_session", return_value=fake_session), \
         patch("src.db.repository.CandidateSnapshotRepository", return_value=fake_repo):
        handler = CandidateSnapshotHandler()
        await handler.execute({
            "stock_code": "AAPL",
            "market": "US",
            "price": 145.32,
            "ensemble_action": "BUY",
            "ensemble_confidence": 0.72,
            "ensemble_reason": "MA cross",
        })

    fake_repo.record.assert_called_once_with(
        stock_code="AAPL",
        market="US",
        price=145.32,
        ensemble_action="BUY",
        ensemble_confidence=0.72,
        ensemble_reason="MA cross",
    )


@pytest.mark.asyncio
async def test_handler_uses_defaults() -> None:
    """market 생략 시 KRX, reason 생략 시 None으로 record가 호출된다."""
    fake_repo = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with patch("src.db.session.get_session", return_value=fake_session), \
         patch("src.db.repository.CandidateSnapshotRepository", return_value=fake_repo):
        handler = CandidateSnapshotHandler()
        await handler.execute({
            "stock_code": "005930",
            "price": 75000.0,
            "ensemble_action": "HOLD",
            "ensemble_confidence": 0.0,
        })

    fake_repo.record.assert_called_once_with(
        stock_code="005930",
        market="KRX",
        price=75000.0,
        ensemble_action="HOLD",
        ensemble_confidence=0.0,
        ensemble_reason=None,
    )
