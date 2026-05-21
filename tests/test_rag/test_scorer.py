from __future__ import annotations

from src.db.models import NewsSourceType
from src.rag.scorer import ChunkScore, RuleBasedScorer, get_scorer


def test_get_scorer_returns_rule_based() -> None:
    scorer = get_scorer()
    assert isinstance(scorer, RuleBasedScorer)
    assert scorer.method == "rule_v1"


def test_positive_text_has_positive_sentiment() -> None:
    s = get_scorer().score("사상최대 실적 흑자전환 신규수주", NewsSourceType.NEWS, None, {})
    assert s.sentiment > 0
    assert s.method == "rule_v1"


def test_negative_text_has_negative_sentiment() -> None:
    s = get_scorer().score("횡령 혐의로 압수수색, 영업손실 적자전환", NewsSourceType.NEWS, None, {})
    assert s.sentiment < 0


def test_no_keyword_text_is_neutral() -> None:
    s = get_scorer().score("회사가 정기 주주총회를 개최한다", NewsSourceType.NEWS, None, {})
    assert s.sentiment == 0.0


def test_empty_content_returns_zero_zero() -> None:
    s = get_scorer().score("", NewsSourceType.NEWS, None, {})
    assert s == ChunkScore(0.0, 0.0, "rule_v1")


def test_disclosure_base_importance_higher_than_news() -> None:
    disc = get_scorer().score("정기보고서 제출", NewsSourceType.DISCLOSURE, None, {})
    news = get_scorer().score("정기보고서 제출", NewsSourceType.NEWS, None, {})
    assert disc.importance > news.importance


def test_high_impact_term_raises_importance() -> None:
    plain = get_scorer().score("실적 발표", NewsSourceType.NEWS, None, {})
    impact = get_scorer().score("상장폐지 사유 발생", NewsSourceType.NEWS, None, {})
    assert impact.importance > plain.importance


def test_score_ranges_are_bounded() -> None:
    s = get_scorer().score(
        "상장폐지 횡령 배임 부도 적자전환 영업정지 거래정지", NewsSourceType.DISCLOSURE, None, {},
    )
    assert -1.0 <= s.sentiment <= 1.0
    assert 0.0 <= s.importance <= 1.0


def test_title_is_included_in_matching() -> None:
    s = get_scorer().score("본문에는 키워드 없음", NewsSourceType.NEWS, "흑자전환 신규수주", {})
    assert s.sentiment > 0
