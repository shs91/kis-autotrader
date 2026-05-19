"""TickerMatcher (Aho-Corasick 종목 매칭) 테스트.

뉴스/공시 본문에서 종목명을 다중 매칭하여 종목코드 리스트를 반환한다.
정규식 OR 누적은 종목 수 1,000+에서 비효율 → Aho-Corasick automaton 사용.

false positive 차단:
- 종목명 길이가 너무 짧으면 (기본 3글자 미만) 동음이의 위험으로 무시.
- 중복 매칭은 dedup.
"""

from __future__ import annotations

import pytest

from src.rag.ticker_matcher import TickerMatcher


@pytest.fixture()
def stocks() -> list[tuple[str, str]]:
    return [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
        ("373220", "LG에너지솔루션"),
        ("009830", "한화솔루션"),
        ("207940", "삼성바이오로직스"),
    ]


class TestMatch:
    def test_single_match(self, stocks: list[tuple[str, str]]) -> None:
        m = TickerMatcher(stocks)
        assert m.match("삼성전자 3분기 영업이익 발표") == ["005930"]

    def test_multiple_matches_dedup(self, stocks: list[tuple[str, str]]) -> None:
        m = TickerMatcher(stocks)
        text = "삼성전자와 SK하이닉스가 동반 강세. 삼성전자 외인 매수 유입."
        result = sorted(m.match(text))
        assert result == ["000660", "005930"]

    def test_no_match_returns_empty(self, stocks: list[tuple[str, str]]) -> None:
        m = TickerMatcher(stocks)
        assert m.match("한국은행 기준금리 동결") == []

    def test_empty_text(self, stocks: list[tuple[str, str]]) -> None:
        m = TickerMatcher(stocks)
        assert m.match("") == []

    def test_longest_match_wins_over_substring(
        self, stocks: list[tuple[str, str]]
    ) -> None:
        """'삼성바이오로직스'는 '삼성전자'의 substring이 아니지만,
        본문에 '삼성바이오로직스'가 등장하면 '삼성전자'는 매칭되면 안 된다."""
        m = TickerMatcher(stocks)
        assert m.match("삼성바이오로직스 임상 통과") == ["207940"]


class TestShortNameFilter:
    def test_short_name_skipped(self) -> None:
        """기본 min_name_length=3 — 2글자 이하는 false positive 위험."""
        stocks = [
            ("000001", "삼성"),  # 너무 짧음 — 무시
            ("000002", "한화"),  # 너무 짧음 — 무시
            ("000003", "현대차"),  # OK
        ]
        m = TickerMatcher(stocks)
        result = m.match("삼성 한화 현대차 시황")
        assert result == ["000003"]

    def test_custom_min_name_length(self) -> None:
        stocks = [("000001", "OK")]
        # min=2이면 매칭, min=3이면 무시
        assert TickerMatcher(stocks, min_name_length=2).match("OK저축은행") == ["000001"]
        assert TickerMatcher(stocks, min_name_length=3).match("OK저축은행") == []


class TestEmpty:
    def test_no_stocks(self) -> None:
        m = TickerMatcher([])
        assert m.match("아무 텍스트") == []
