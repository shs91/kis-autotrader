"""치명 공시 매처(disclosure_risk) 단위 테스트.

매매 엔진 buy-time 게이트와 스크리닝 Worker 사전 배제가 공유하는 단일
진실원천이므로, 키워드·오탐 방지 규칙을 직접 검증한다.
"""

from __future__ import annotations

from src.strategy.disclosure_risk import (
    CRITICAL_DISCLOSURE_KEYWORDS,
    match_critical_disclosure,
)


def test_matches_delisting_liquidation() -> None:
    """상장폐지/정리매매 제목은 매칭된다 (실데이터 케이스)."""
    titles = ["주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)"]
    assert match_critical_disclosure(titles) == titles[0]


def test_matches_embezzlement() -> None:
    """횡령·배임은 매칭된다."""
    assert match_critical_disclosure(["횡령ㆍ배임혐의발생"]) is not None


def test_bare_trading_halt_release_not_matched() -> None:
    """'주권매매거래정지해제'(거래 재개=호재)만으로는 매칭되지 않는다 — 오탐 방지."""
    assert match_critical_disclosure(["주권매매거래정지해제"]) is None


def test_benign_disclosure_not_matched() -> None:
    """일반 공시(공급계약 등)는 매칭되지 않는다."""
    assert match_critical_disclosure(["단일판매ㆍ공급계약체결"]) is None


def test_empty_list_returns_none() -> None:
    """빈 목록은 None."""
    assert match_critical_disclosure([]) is None


def test_returns_first_matching_title() -> None:
    """여러 제목 중 첫 매칭 제목을 반환한다."""
    titles = ["정상공시", "관리종목지정", "또다른정상공시"]
    assert match_critical_disclosure(titles) == "관리종목지정"


def test_keyword_set_is_nonempty_tuple() -> None:
    """키워드 집합은 비어있지 않은 튜플(상수 무결성)."""
    assert isinstance(CRITICAL_DISCLOSURE_KEYWORDS, tuple)
    assert "상장폐지" in CRITICAL_DISCLOSURE_KEYWORDS
    assert "거래정지" not in CRITICAL_DISCLOSURE_KEYWORDS  # 단일 '거래정지'는 의도적 제외
