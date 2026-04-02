"""주문 API 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.api.order import ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET, OrderAPI
from src.utils.exceptions import OrderError


class TestOrderAPI:
    """OrderAPI 테스트."""

    def _make_order_api(self, mock_response: dict) -> OrderAPI:  # type: ignore[type-arg]
        """테스트용 OrderAPI를 생성한다."""
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        return OrderAPI(client=mock_client)

    async def test_buy_market_order_success(self) -> None:
        """시장가 매수 주문이 정상적으로 동작한다."""
        response = {
            "rt_cd": "0",
            "msg1": "주문 완료",
            "output": {
                "ODNO": "0001234567",
                "ORD_TMD": "130000",
            },
        }

        api = self._make_order_api(response)
        result = await api.buy("005930", quantity=10)

        assert result.order_no == "0001234567"
        assert result.message == "주문 완료"

    async def test_buy_limit_order_success(self) -> None:
        """지정가 매수 주문이 정상적으로 동작한다."""
        response = {
            "rt_cd": "0",
            "msg1": "주문 완료",
            "output": {
                "ODNO": "0001234568",
                "ORD_TMD": "130100",
            },
        }

        api = self._make_order_api(response)
        result = await api.buy(
            "005930", quantity=5, price=70000, order_type=ORDER_TYPE_LIMIT
        )

        assert result.order_no == "0001234568"

    async def test_sell_success(self) -> None:
        """매도 주문이 정상적으로 동작한다."""
        response = {
            "rt_cd": "0",
            "msg1": "매도 주문 완료",
            "output": {
                "ODNO": "0001234569",
                "ORD_TMD": "140000",
            },
        }

        api = self._make_order_api(response)
        result = await api.sell("005930", quantity=10)

        assert result.order_no == "0001234569"
        assert result.message == "매도 주문 완료"

    async def test_buy_failure_raises_order_error(self) -> None:
        """주문 실패 시 OrderError가 발생한다."""
        response = {
            "rt_cd": "1",
            "msg1": "잔고 부족",
            "output": {},
        }

        api = self._make_order_api(response)

        with pytest.raises(OrderError, match="잔고 부족"):
            await api.buy("005930", quantity=10)

    async def test_modify_order_success(self) -> None:
        """주문 정정이 정상적으로 동작한다."""
        response = {
            "rt_cd": "0",
            "msg1": "정정 완료",
            "output": {
                "ODNO": "0001234570",
                "ORD_TMD": "140100",
            },
        }

        api = self._make_order_api(response)
        result = await api.modify(
            order_no="0001234567",
            stock_code="005930",
            quantity=5,
            price=71000,
        )

        assert result.order_no == "0001234570"

    async def test_cancel_order_success(self) -> None:
        """주문 취소가 정상적으로 동작한다."""
        response = {
            "rt_cd": "0",
            "msg1": "취소 완료",
            "output": {
                "ODNO": "0001234571",
                "ORD_TMD": "140200",
            },
        }

        api = self._make_order_api(response)
        result = await api.cancel(
            order_no="0001234567",
            stock_code="005930",
            quantity=10,
        )

        assert result.order_no == "0001234571"
        assert result.message == "취소 완료"

    async def test_buy_passes_correct_tr_id(self) -> None:
        """매수 시 올바른 tr_id가 전달된다."""
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "rt_cd": "0",
            "msg1": "ok",
            "output": {"ODNO": "001", "ORD_TMD": "100000"},
        }

        api = OrderAPI(client=mock_client)
        await api.buy("005930", quantity=1)

        call_kwargs = mock_client.post.call_args
        # 모의투자 환경이면 VTTC0802U
        assert call_kwargs.kwargs.get("tr_id") == "VTTC0802U" or \
            call_kwargs[1].get("tr_id") == "VTTC0802U"
