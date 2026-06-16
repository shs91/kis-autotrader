# P2a: 해외 시세(Quote) API 구현 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 미국 주식 시세 조회용 `OverseasQuoteAPI`(현재가/일봉/거래량순위)를 구현한다. 가격은 **해외 전용 dataclass + `Decimal`** 로 다루며 **국내 코드는 0 변경**한다.

**Architecture:** 국내/해외 응답 체계가 완전히 다르므로(`FID_*`/`stck_*` vs `EXCD`/`SYMB`/`last`,`clos`), 해외 전용 dataclass(`OverseasCurrentPrice`/`OverseasDailyPriceItem`/`OverseasRankItem`, 가격 `Decimal`)와 별도 `OverseasQuoteProvider` Protocol을 둔다. `OverseasQuoteAPI`는 기존 `KISClient`(rate limiter/circuit breaker 공용)를 그대로 쓰고, 시세 거래소코드(`EXCD`: NAS/NYS/AMS)와 종목심볼(`SYMB`)을 인자로 받는다.

**Tech Stack:** Python 3.12, `decimal.Decimal`, `typing.Protocol`+`runtime_checkable`, `unittest.mock.AsyncMock`(KISClient 주입 패턴), pytest-asyncio, mypy(strict), ruff(E,F,I,N,W,UP,DTZ,B,S).

**기준 spec:** `docs/superpowers/specs/2026-06-14-us-stock-trading-design.md` (§2.2 시세, §2.3 순위, §2.4 거래소코드)

**검증 환경:** worktree `.claude/worktrees/us-stock-trading-impl`. 명령은 `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest|mypy|ruff` 기준.

**확정된 사실(spec §2.2/2.3):** 현재가 `price` HHDFS00000300(AUTH/EXCD/SYMB → output: last/base/open/high/low/tvol/rate/zdiv), 일봉 `dailyprice` HHDFS76240000(GUBN 0일/1주/2월 → output2: xymd/clos/open/high/low/tvol), 거래량순위 `ranking/trade-vol` HHDFS76310010(EXCD/NDAY/VOL_RANG → output2). 가격은 문자열로 내려와 `Decimal` 파싱. **순위 output2의 정확한 필드명(symb/last/rate/tvol/rank)은 confidence=low → Task 4에 실측 재확인 표시.**

---

## 파일 구조

| 파일 | 책임 | 종류 |
|------|------|------|
| `src/api/overseas_quote.py` | 해외 시세 dataclass + `_decimal` 헬퍼 + `OverseasQuoteAPI` | Create |
| `src/api/protocols.py` | `OverseasQuoteProvider` Protocol 추가 | Modify |
| `tests/test_api/test_overseas_quote.py` | `OverseasQuoteAPI` 단위 테스트(AsyncMock) | Create |

> 국내 `src/api/quote.py`는 건드리지 않는다. `_get`(대소문자 무관) 헬퍼는 해외 모듈에 자체 정의한다(기존 `quote.py`/`account.py`가 각자 정의한 패턴과 동일).

---

### Task 1: 해외 시세 dataclass + Decimal 헬퍼 + Protocol

**Files:**
- Create: `src/api/overseas_quote.py` (dataclass/상수/헬퍼 부분)
- Modify: `src/api/protocols.py`
- Test: `tests/test_api/test_overseas_quote.py` (헬퍼/dataclass 부분)

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_api/test_overseas_quote.py`:

```python
"""해외 시세 API(OverseasQuoteAPI) 테스트."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

from src.api.overseas_quote import (
    OverseasCurrentPrice,
    OverseasDailyPriceItem,
    OverseasQuoteAPI,
    OverseasRankItem,
    _decimal,
)
from src.api.protocols import OverseasQuoteProvider


class TestDecimalHelper:
    def test_parses_decimal_string(self) -> None:
        assert _decimal("150.25") == Decimal("150.25")

    def test_empty_string_is_zero(self) -> None:
        assert _decimal("") == Decimal("0")

    def test_invalid_is_zero(self) -> None:
        assert _decimal("N/A") == Decimal("0")

    def test_preserves_precision(self) -> None:
        # float 손실 없이 문자열 그대로 보존
        assert _decimal("0.0001") == Decimal("0.0001")


def test_overseas_quote_api_satisfies_protocol() -> None:
    assert issubclass(OverseasQuoteAPI, OverseasQuoteProvider)


def test_dataclass_shapes() -> None:
    cp = OverseasCurrentPrice(
        symbol="AAPL",
        exchange="NAS",
        last=Decimal("150.25"),
        base=Decimal("149.00"),
        change_rate=0.84,
        volume=1000,
        high=Decimal("151.0"),
        low=Decimal("148.5"),
        open=Decimal("149.5"),
        raw_data={},
    )
    assert cp.last == Decimal("150.25")
    dp = OverseasDailyPriceItem(
        date="20260615",
        open=Decimal("149.5"),
        high=Decimal("151.0"),
        low=Decimal("148.5"),
        close=Decimal("150.25"),
        volume=1000,
    )
    assert dp.close == Decimal("150.25")
    ri = OverseasRankItem(
        symbol="AAPL",
        exchange="NAS",
        last=Decimal("150.25"),
        change_rate=0.84,
        volume=1000,
        rank=1,
    )
    assert ri.rank == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_api/test_overseas_quote.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.overseas_quote'`

- [ ] **Step 3: dataclass + 상수 + 헬퍼 구현**

Create `src/api/overseas_quote.py`:

```python
"""해외(미국) 시세 조회 API 모듈.

국내 ``src/api/quote.py``와 응답 체계가 완전히 달라(엔드포인트 overseas-price,
파라미터 EXCD/SYMB, 응답 필드 last/clos 등) 별도 모듈로 둔다. 가격은 KIS가
문자열로 내려주므로 부동소수점 손실 없이 ``Decimal``로 파싱한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from src.api.client import KISClient
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# ── 엔드포인트 / TR_ID (spec §2.2, §2.3) ──
OVERSEAS_PRICE_PATH: str = "/uapi/overseas-price/v1/quotations/price"
OVERSEAS_DAILY_PATH: str = "/uapi/overseas-price/v1/quotations/dailyprice"
OVERSEAS_RANK_VOL_PATH: str = "/uapi/overseas-stock/v1/ranking/trade-vol"

TR_ID_OVERSEAS_PRICE: str = "HHDFS00000300"
TR_ID_OVERSEAS_DAILY: str = "HHDFS76240000"
TR_ID_OVERSEAS_RANK_VOL: str = "HHDFS76310010"

# 기간(period) → KIS GUBN 코드
_GUBN_MAP: dict[str, str] = {"D": "0", "W": "1", "M": "2"}


def _get(data: dict[str, Any], key: str, default: str = "") -> str:
    """대소문자 무관 조회. 해외 응답은 소문자 키(last/clos 등)지만 환경별 변동 대비."""
    return cast(str, data.get(key) or data.get(key.upper(), default))


def _decimal(value: str) -> Decimal:
    """문자열 가격을 Decimal로 파싱한다. 빈 값/파싱 불가 시 Decimal('0')."""
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return Decimal("0")


@dataclass
class OverseasCurrentPrice:
    """해외 현재가 정보 (가격은 Decimal)."""

    symbol: str
    exchange: str  # 시세 거래소코드(EXCD): NAS/NYS/AMS
    last: Decimal
    base: Decimal  # 전일종가
    change_rate: float  # rate (%)
    volume: int  # tvol
    high: Decimal
    low: Decimal
    open: Decimal
    raw_data: dict[str, Any]


@dataclass
class OverseasDailyPriceItem:
    """해외 일봉 한 건 (가격은 Decimal)."""

    date: str  # xymd
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal  # clos
    volume: int  # tvol


@dataclass
class OverseasRankItem:
    """해외 거래량순위 종목."""

    symbol: str
    exchange: str
    last: Decimal
    change_rate: float
    volume: int
    rank: int
```

- [ ] **Step 4: OverseasQuoteProvider Protocol 추가**

`src/api/protocols.py`에 다음을 추가한다. 파일 상단 import 블록에:

```python
from src.api.overseas_quote import (
    OverseasCurrentPrice,
    OverseasDailyPriceItem,
    OverseasRankItem,
)
```

파일 끝에 Protocol 추가:

```python
@runtime_checkable
class OverseasQuoteProvider(Protocol):
    """해외 시세 조회 인터페이스 (가격 Decimal, EXCD/SYMB 기반)."""

    async def get_current_price(
        self, symbol: str, exchange: str
    ) -> OverseasCurrentPrice:
        """해외 종목 현재가를 조회한다."""
        ...

    async def get_daily_price(
        self,
        symbol: str,
        exchange: str,
        period: str = "D",
        lookback_days: int = 60,
    ) -> list[OverseasDailyPriceItem]:
        """해외 종목 일봉을 조회한다(최신→과거)."""
        ...

    async def get_ranking(
        self, exchange: str, top_n: int = 20
    ) -> list[OverseasRankItem]:
        """거래소별 거래량순위를 조회한다."""
        ...
```

> 주의: `src/api/protocols.py`가 `src/api/overseas_quote.py`를 import하고, 후자가 `OverseasQuoteAPI`를 같은 파일에 두므로, Task 2에서 `OverseasQuoteAPI`를 추가해도 순환은 없다(protocols → overseas_quote 단방향, overseas_quote는 protocols를 import하지 않음).

- [ ] **Step 5: 테스트 실행 — Protocol/dataclass는 통과, API는 아직 미구현**

이 시점에서 `OverseasQuoteAPI`가 아직 없으므로 `test_overseas_quote_api_satisfies_protocol`과 import가 실패한다. Task 2에서 `OverseasQuoteAPI`를 추가한 뒤 통과시킨다. 지금은 다음만 확인:

Run: `python -m pytest tests/test_api/test_overseas_quote.py::TestDecimalHelper -q`
Expected: FAIL — `ImportError: cannot import name 'OverseasQuoteAPI'` (아직 미정의)

> 이 Task는 Task 2와 한 커밋으로 묶는다(인터페이스+첫 구현이 함께 의미를 가짐). Task 2 Step 4에서 커밋.

---

### Task 2: OverseasQuoteAPI.get_current_price

**Files:**
- Modify: `src/api/overseas_quote.py` (OverseasQuoteAPI 클래스 추가)
- Test: `tests/test_api/test_overseas_quote.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_api/test_overseas_quote.py`에 클래스 추가:

```python
class TestOverseasCurrentPrice:
    def _make_api(self, response: dict[str, object]) -> OverseasQuoteAPI:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        return OverseasQuoteAPI(client=mock_client)

    async def test_get_current_price_parses_decimal(self) -> None:
        response = {
            "output": {
                "rsym": "DNASAAPL",
                "zdiv": "2",
                "base": "149.00",
                "last": "150.25",
                "open": "149.50",
                "high": "151.00",
                "low": "148.50",
                "tvol": "50000000",
                "rate": "0.84",
            }
        }
        api = self._make_api(response)
        result = await api.get_current_price("AAPL", "NAS")

        assert result.symbol == "AAPL"
        assert result.exchange == "NAS"
        assert result.last == Decimal("150.25")
        assert result.base == Decimal("149.00")
        assert result.open == Decimal("149.50")
        assert result.high == Decimal("151.00")
        assert result.low == Decimal("148.50")
        assert result.volume == 50000000
        assert result.change_rate == 0.84

    async def test_get_current_price_sends_excd_symb(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output": {}}
        api = OverseasQuoteAPI(client=mock_client)
        await api.get_current_price("AAPL", "NAS")

        call = mock_client.get.call_args
        assert call.args[0] == OVERSEAS_PRICE_PATH
        assert call.kwargs.get("tr_id") == TR_ID_OVERSEAS_PRICE
        params = call.kwargs.get("params")
        assert params["EXCD"] == "NAS"
        assert params["SYMB"] == "AAPL"
        assert "AUTH" in params
```

import 줄에 상수 추가:

```python
from src.api.overseas_quote import (
    OVERSEAS_PRICE_PATH,
    TR_ID_OVERSEAS_PRICE,
    OverseasCurrentPrice,
    OverseasDailyPriceItem,
    OverseasQuoteAPI,
    OverseasRankItem,
    _decimal,
)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_api/test_overseas_quote.py -q`
Expected: FAIL — `ImportError`/`AttributeError` (OverseasQuoteAPI 미정의)

- [ ] **Step 3: OverseasQuoteAPI + get_current_price 구현**

`src/api/overseas_quote.py` 끝에 추가:

```python
class OverseasQuoteAPI:
    """KIS 해외주식 시세 조회 API. (EXCD/SYMB 기반, 가격 Decimal)"""

    def __init__(self, client: KISClient | None = None) -> None:
        self._client = client or KISClient()

    async def get_current_price(
        self, symbol: str, exchange: str
    ) -> OverseasCurrentPrice:
        """해외 종목 현재가를 조회한다.

        Args:
            symbol: 종목 심볼 (예: "AAPL")
            exchange: 시세 거래소코드 EXCD ("NAS"/"NYS"/"AMS")
        """
        logger.info("[해외 현재가] %s.%s", exchange, symbol)
        params = {"AUTH": "", "EXCD": exchange, "SYMB": symbol}
        response = await self._client.get(
            OVERSEAS_PRICE_PATH, params=params, tr_id=TR_ID_OVERSEAS_PRICE
        )
        output = response.get("output", {}) or {}
        return OverseasCurrentPrice(
            symbol=symbol,
            exchange=exchange,
            last=_decimal(_get(output, "last")),
            base=_decimal(_get(output, "base")),
            change_rate=float(_get(output, "rate", "0") or "0"),
            volume=int(_get(output, "tvol", "0") or "0"),
            high=_decimal(_get(output, "high")),
            low=_decimal(_get(output, "low")),
            open=_decimal(_get(output, "open")),
            raw_data=output,
        )
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

Run: `python -m pytest tests/test_api/test_overseas_quote.py -q`
Expected: PASS (TestDecimalHelper 4 + dataclass/protocol 2 + current_price 2)

Run: `python -m mypy src/api/overseas_quote.py src/api/protocols.py`
Expected: `Success`

Run: `ruff check src/api/overseas_quote.py src/api/protocols.py tests/test_api/test_overseas_quote.py`
Expected: `All checks passed!`

```bash
git add src/api/overseas_quote.py src/api/protocols.py tests/test_api/test_overseas_quote.py
git commit -m "feat(api): 해외 현재가 OverseasQuoteAPI.get_current_price + Decimal dataclass (P2a)"
```

---

### Task 3: get_daily_price (일봉)

**Files:**
- Modify: `src/api/overseas_quote.py`
- Test: `tests/test_api/test_overseas_quote.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class TestOverseasDailyPrice:
    def _make_api(self, response: dict[str, object]) -> OverseasQuoteAPI:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        return OverseasQuoteAPI(client=mock_client)

    async def test_get_daily_price_parses_output2(self) -> None:
        response = {
            "output1": {"rsym": "DNASAAPL"},
            "output2": [
                {
                    "xymd": "20260615",
                    "open": "149.50",
                    "high": "151.00",
                    "low": "148.50",
                    "clos": "150.25",
                    "tvol": "50000000",
                },
                {
                    "xymd": "20260612",
                    "open": "148.00",
                    "high": "149.80",
                    "low": "147.50",
                    "clos": "149.00",
                    "tvol": "42000000",
                },
            ],
        }
        api = self._make_api(response)
        result = await api.get_daily_price("AAPL", "NAS")

        assert len(result) == 2
        assert result[0].date == "20260615"
        assert result[0].close == Decimal("150.25")
        assert result[0].volume == 50000000
        assert result[1].date == "20260612"

    async def test_get_daily_price_sends_gubn_for_period(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": []}
        api = OverseasQuoteAPI(client=mock_client)
        await api.get_daily_price("AAPL", "NAS", period="W")

        call = mock_client.get.call_args
        assert call.args[0] == OVERSEAS_DAILY_PATH
        assert call.kwargs.get("tr_id") == TR_ID_OVERSEAS_DAILY
        params = call.kwargs.get("params")
        assert params["GUBN"] == "1"  # W → 1
        assert params["EXCD"] == "NAS"
        assert params["SYMB"] == "AAPL"
```

import에 추가: `OVERSEAS_DAILY_PATH, TR_ID_OVERSEAS_DAILY`.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_api/test_overseas_quote.py::TestOverseasDailyPrice -q`
Expected: FAIL — `AttributeError: ... has no attribute 'get_daily_price'`

- [ ] **Step 3: 구현**

`OverseasQuoteAPI`에 메서드 추가:

```python
    async def get_daily_price(
        self,
        symbol: str,
        exchange: str,
        period: str = "D",
        lookback_days: int = 60,
    ) -> list[OverseasDailyPriceItem]:
        """해외 종목 일봉을 조회한다(최신→과거).

        Args:
            symbol: 종목 심볼
            exchange: 시세 거래소코드 EXCD
            period: "D"(일)/"W"(주)/"M"(월)
            lookback_days: 확보할 최대 건수(응답 상위 N건 절단)
        """
        logger.info("[해외 일봉] %s.%s period=%s", exchange, symbol, period)
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol,
            "GUBN": _GUBN_MAP.get(period, "0"),
            "BYMD": "",
            "MODP": "1",
        }
        response = await self._client.get(
            OVERSEAS_DAILY_PATH, params=params, tr_id=TR_ID_OVERSEAS_DAILY
        )
        output2 = response.get("output2", []) or []
        results: list[OverseasDailyPriceItem] = []
        for item in output2[:lookback_days]:
            date = _get(item, "xymd")
            if not date:
                continue
            results.append(
                OverseasDailyPriceItem(
                    date=date,
                    open=_decimal(_get(item, "open")),
                    high=_decimal(_get(item, "high")),
                    low=_decimal(_get(item, "low")),
                    close=_decimal(_get(item, "clos")),
                    volume=int(_get(item, "tvol", "0") or "0"),
                )
            )
        return results
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

Run: `python -m pytest tests/test_api/test_overseas_quote.py -q`
Expected: PASS

Run: `python -m mypy src/api/overseas_quote.py` → `Success`
Run: `ruff check src/api/overseas_quote.py tests/test_api/test_overseas_quote.py` → `All checks passed!`

```bash
git add src/api/overseas_quote.py tests/test_api/test_overseas_quote.py
git commit -m "feat(api): 해외 일봉 OverseasQuoteAPI.get_daily_price (P2a)"
```

---

### Task 4: get_ranking (거래량순위)

> **⚠️ 실측 재확인(spec §13):** 순위 `output2`의 필드명(`symb`/`last`/`rate`/`tvol`/`rank`)은 confidence=low. 구현은 아래 가정으로 작성하되, 실전키 실측(P2 종료 절차)에서 실제 응답 샘플로 키를 교정한다. `_get`이 빈 값을 견디므로 키가 틀려도 빈 리스트로 안전 degrade한다.

**Files:**
- Modify: `src/api/overseas_quote.py`
- Test: `tests/test_api/test_overseas_quote.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class TestOverseasRanking:
    def _make_api(self, response: dict[str, object]) -> OverseasQuoteAPI:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        return OverseasQuoteAPI(client=mock_client)

    async def test_get_ranking_parses_output2(self) -> None:
        response = {
            "output2": [
                {"symb": "TSLA", "last": "250.10", "rate": "3.2", "tvol": "90000000", "rank": "1"},
                {"symb": "AAPL", "last": "150.25", "rate": "0.84", "tvol": "50000000", "rank": "2"},
            ]
        }
        api = self._make_api(response)
        result = await api.get_ranking("NAS", top_n=10)

        assert len(result) == 2
        assert result[0].symbol == "TSLA"
        assert result[0].last == Decimal("250.10")
        assert result[0].rank == 1
        assert result[1].symbol == "AAPL"

    async def test_get_ranking_sends_excd(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": []}
        api = OverseasQuoteAPI(client=mock_client)
        await api.get_ranking("NYS")

        call = mock_client.get.call_args
        assert call.args[0] == OVERSEAS_RANK_VOL_PATH
        assert call.kwargs.get("tr_id") == TR_ID_OVERSEAS_RANK_VOL
        params = call.kwargs.get("params")
        assert params["EXCD"] == "NYS"

    async def test_get_ranking_empty_on_missing_output2(self) -> None:
        api = self._make_api({})
        result = await api.get_ranking("NAS")
        assert result == []
```

import에 추가: `OVERSEAS_RANK_VOL_PATH, TR_ID_OVERSEAS_RANK_VOL`.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_api/test_overseas_quote.py::TestOverseasRanking -q`
Expected: FAIL — `AttributeError: ... 'get_ranking'`

- [ ] **Step 3: 구현**

```python
    async def get_ranking(
        self, exchange: str, top_n: int = 20
    ) -> list[OverseasRankItem]:
        """거래소별 거래량순위를 조회한다(HHDFS76310010).

        Args:
            exchange: 시세 거래소코드 EXCD ("NAS"/"NYS"/"AMS")
            top_n: 상위 N개 절단
        """
        logger.info("[해외 거래량순위] EXCD=%s top=%d", exchange, top_n)
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "NDAY": "0",
            "VOL_RANG": "0",
        }
        response = await self._client.get(
            OVERSEAS_RANK_VOL_PATH, params=params, tr_id=TR_ID_OVERSEAS_RANK_VOL
        )
        output2 = response.get("output2", []) or []
        results: list[OverseasRankItem] = []
        for idx, item in enumerate(output2[:top_n], start=1):
            symbol = _get(item, "symb")
            if not symbol:
                continue
            results.append(
                OverseasRankItem(
                    symbol=symbol,
                    exchange=exchange,
                    last=_decimal(_get(item, "last")),
                    change_rate=float(_get(item, "rate", "0") or "0"),
                    volume=int(_get(item, "tvol", "0") or "0"),
                    rank=int(_get(item, "rank", "0") or str(idx)),
                )
            )
        return results
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

Run: `python -m pytest tests/test_api/test_overseas_quote.py -q` → PASS
Run: `python -m mypy src/api/overseas_quote.py` → `Success`
Run: `ruff check src/api/overseas_quote.py tests/test_api/test_overseas_quote.py` → `All checks passed!`

```bash
git add src/api/overseas_quote.py tests/test_api/test_overseas_quote.py
git commit -m "feat(api): 해외 거래량순위 OverseasQuoteAPI.get_ranking (P2a, 필드명 실측 재확인 필요)"
```

---

### Task 5: 회귀 + Protocol 부합 확정

**Files:** (검증 전용)

- [ ] **Step 1: 해외 + 인접 회귀**

Run: `python -m pytest tests/test_api/ tests/test_market/ -q`
Expected: PASS (기존 + 신규, 0 failures)

- [ ] **Step 2: 타입/린트**

Run: `python -m mypy src/api/overseas_quote.py src/api/protocols.py`
Expected: `Success`

Run: `ruff check src/api/overseas_quote.py src/api/protocols.py tests/test_api/test_overseas_quote.py`
Expected: `All checks passed!`

- [ ] **Step 3: 실측 재확인 메모(코드 변경 없음)**

P2 종료 시 실전 appkey로 다음을 1회 실호출하여 검증한다(자동화 아님, 운영자 수동):
1. `get_current_price("AAPL", "NAS")` → `last`가 실제 가격과 일치, `zdiv` 자릿수 확인.
2. `get_ranking("NAS", 5)` → output2 필드명(`symb`/`last`/`rate`/`tvol`/`rank`)이 가정과 일치하는지. 불일치 시 `get_ranking`의 `_get` 키를 실제 값으로 교정 후 Task 4 테스트 픽스처도 갱신.

---

## Self-Review (작성자 점검 완료)

**1. Spec coverage:** §2.2 현재가/일봉(Task 2/3) ✓, §2.3 거래량순위(Task 4) ✓, §2.4 EXCD 시세코드(전 Task의 `exchange` 인자) ✓, "가격 Decimal"(전 dataclass) ✓. 분봉(get_minute_price)은 P2a 미포함 — 1차 매매에 일봉+현재가면 충분(YAGNI), 필요 시 후속.

**2. Placeholder scan:** 모든 step에 실제 코드/명령/기대출력 포함. 단 Task 4는 필드명 confidence=low를 명시적 "실측 재확인"으로 표기(placeholder 아님 — 동작하는 가정값 + 안전 degrade).

**3. Type consistency:** dataclass 필드(`last/base/open/high/low: Decimal`, `volume/rank: int`, `change_rate: float`)가 Task 1 정의·Task 2~4 사용·테스트에서 일치. `OverseasQuoteAPI` 메서드 시그니처(`get_current_price(symbol, exchange)`, `get_daily_price(symbol, exchange, period, lookback_days)`, `get_ranking(exchange, top_n)`)가 `OverseasQuoteProvider` Protocol과 일치. 상수명(`OVERSEAS_*_PATH`, `TR_ID_OVERSEAS_*`)이 정의·import·테스트에서 일치. `_get`은 대문자 폴백(`key.upper()`)으로 해외 소문자 키에 맞춤.

**4. 순환 import 점검:** `protocols.py` → `overseas_quote.py`(dataclass) 단방향. `overseas_quote.py`는 `protocols`를 import하지 않고 `client`만. ✓

---

## Execution Handoff

P2a는 국내 무변경·순수 추가. 완료 후 P2b(해외 잔고), P2c(해외 주문)로 이어간다. P2a~P2c는 한 worktree 브랜치에 누적(PR 분할 정책: 순수 코드 묶음).
