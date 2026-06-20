"""시장별 통화/수치/수익률 포맷 헬퍼.

FX 환율 소스가 없으므로 환산하지 않고 시장별 네이티브 통화로 표기한다
(한국=원, 미국=$). '전체' 화면은 통화별로 분리해 합산을 피한다.
"""

from __future__ import annotations

import math
from typing import Any

# 시장별 통화 메타 (기호/접미사/소수 자릿수/통화코드)
_CCY: dict[str, dict[str, Any]] = {
    "KRX": {"prefix": "", "suffix": "원", "decimals": 0, "code": "KRW"},
    "US": {"prefix": "$", "suffix": "", "decimals": 2, "code": "USD"},
}


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def currency_code(market: str) -> str:
    """시장의 통화 코드(KRW/USD)."""
    return str(_CCY.get(market, _CCY["KRX"])["code"])


def money(value: Any, market: str = "KRX", *, signed: bool = False) -> str:
    """시장별 통화로 금액을 포맷한다. KRW ``1,234원``, USD ``$12.34``."""
    if _is_missing(value):
        return "-"
    meta = _CCY.get(market, _CCY["KRX"])
    decimals = int(meta["decimals"])
    # 음수 부호는 통화기호 앞에 둔다 (예: -$12.30, 양수는 signed일 때만 +)
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    body = f"{abs(value):,.{decimals}f}"
    return f"{sign}{meta['prefix']}{body}{meta['suffix']}"


def pct(value: Any, *, signed: bool = True) -> str:
    """수익률을 ``+2.50%`` 형태로 포맷한다."""
    if _is_missing(value):
        return "-"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.2f}%"


def qty(value: Any, market: str = "KRX") -> str:
    """수량/가격 등 일반 수치 포맷(시장별 소수 자릿수)."""
    if _is_missing(value):
        return "-"
    decimals = int(_CCY.get(market, _CCY["KRX"])["decimals"])
    return f"{value:,.{decimals}f}"


def num(value: Any, *, decimals: int = 0) -> str:
    """단순 정수/실수 천단위 포맷."""
    if _is_missing(value):
        return "-"
    return f"{value:,.{decimals}f}"
