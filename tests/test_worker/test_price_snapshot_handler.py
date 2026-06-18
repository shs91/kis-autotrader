"""PriceSnapshotHandler 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.worker.handlers import PriceSnapshotHandler


@pytest.mark.asyncio
async def test_handler_inserts_snapshot() -> None:
    fake_repo = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with patch("src.db.session.get_session", return_value=fake_session), \
         patch("src.db.repository.PriceSnapshotRepository", return_value=fake_repo):
        handler = PriceSnapshotHandler()
        await handler.execute({
            "stock_code": "AAPL",
            "market": "US",
            "currency": "USD",
            "price": 145.32,
        })

    fake_repo.add.assert_called_once_with(
        stock_code="AAPL", market="US", currency="USD", price=145.32,
    )


@pytest.mark.asyncio
async def test_handler_uses_default_market_and_currency() -> None:
    """market/currency를 생략하면 기본값 KRX/KRW로 add가 호출된다."""
    fake_repo = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with patch("src.db.session.get_session", return_value=fake_session), \
         patch("src.db.repository.PriceSnapshotRepository", return_value=fake_repo):
        handler = PriceSnapshotHandler()
        await handler.execute({
            "stock_code": "005930",
            "price": 75000.0,
        })

    fake_repo.add.assert_called_once_with(
        stock_code="005930", market="KRX", currency="KRW", price=75000.0,
    )
