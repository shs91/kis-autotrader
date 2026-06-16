"""기존 Domestic API가 Provider Protocol을 구조적으로 만족하는지 고정한다.

P1에서는 행동을 바꾸지 않고, 해외 구현체(P2)가 따라야 할 인터페이스 계약만
정의한다. runtime_checkable Protocol의 issubclass는 메서드 존재만 검사하며,
정확한 시그니처는 mypy가 정적으로 보장한다.
"""

from __future__ import annotations

from src.api.account import AccountAPI
from src.api.order import OrderAPI
from src.api.protocols import AccountProvider, OrderProvider, QuoteProvider
from src.api.quote import QuoteAPI


def test_order_api_satisfies_order_provider() -> None:
    assert issubclass(OrderAPI, OrderProvider)


def test_quote_api_satisfies_quote_provider() -> None:
    assert issubclass(QuoteAPI, QuoteProvider)


def test_account_api_satisfies_account_provider() -> None:
    assert issubclass(AccountAPI, AccountProvider)
