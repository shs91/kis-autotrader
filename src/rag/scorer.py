"""뉴스/공시 청크의 sentiment·importance 룰베이스 스코어링.

교체 가능한 `Scorer` 추상화 — 룰베이스가 첫 구현. 향후 로컬 모델 스코어러는
같은 인터페이스로 추가하고 `get_scorer()`에 등록하면 호출부·스키마 무변경으로
전환된다. 순수·결정적이며 어떤 입력에도 예외를 던지지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from src.db.models import NewsSourceType

# 호재(+)/악재(-) 가중 키워드. 부분 문자열 매칭(한국어 금융 표현).
POSITIVE_TERMS: dict[str, float] = {
    "흑자전환": 1.0, "사상최대": 1.0, "최대실적": 1.0, "어닝서프라이즈": 1.0, "호실적": 0.8,
    "신규수주": 0.9, "공급계약": 0.8, "계약체결": 0.8, "수주": 0.6, "실적개선": 0.7,
    "자사주매입": 0.8, "자사주취득": 0.8, "배당확대": 0.7, "특허취득": 0.6,
    "임상성공": 1.0, "품목허가": 0.9, "흑자": 0.5,
    "목표주가상향": 0.8, "투자의견상향": 0.8,
}
NEGATIVE_TERMS: dict[str, float] = {
    "적자전환": 1.0, "어닝쇼크": 1.0, "분식회계": 1.0, "부도": 1.0,
    "회생절차": 1.0, "상장폐지": 1.0,
    "횡령": 1.0, "배임": 1.0, "압수수색": 0.9, "영업손실": 0.8, "실적부진": 0.7, "적자": 0.6,
    "거래정지": 0.9, "영업정지": 0.9, "관리종목": 0.9, "불성실공시": 0.8, "무상감자": 0.8,
    "유상증자": 0.7, "리콜": 0.7, "피소": 0.6,
    "소송": 0.5,  # 방향 무관 매칭(알려진 한계)
    "전환사채": 0.4,
    "목표주가하향": 0.8, "투자의견하향": 0.8,
}
# tanh 정규화 스케일: 가중합 ≈1.5 → sentiment ≈0.66.
SENTIMENT_SCALE = 1.5

# importance source_type 기본 가중 (공시/실적 > 리포트 > 뉴스).
IMPORTANCE_BASE: dict[NewsSourceType, float] = {
    NewsSourceType.DISCLOSURE: 0.5,
    NewsSourceType.EARNINGS: 0.5,
    NewsSourceType.REPORT: 0.35,
    NewsSourceType.NEWS: 0.3,
}
_IMPORTANCE_DEFAULT = 0.3
# 방향 무관 '시장영향 크기' boost.
HIGH_IMPACT_TERMS: dict[str, float] = {
    "상장폐지": 0.5, "부도": 0.5, "회생절차": 0.5, "거래정지": 0.4, "영업정지": 0.4,
    "횡령": 0.4, "배임": 0.4, "분식회계": 0.4, "합병": 0.35, "임상성공": 0.35,
    "유상증자": 0.3, "무상감자": 0.3, "분할": 0.3, "최대실적": 0.3, "어닝서프라이즈": 0.3,
    "어닝쇼크": 0.3, "품목허가": 0.3, "자사주매입": 0.25,
}


def _matched_weight(lexicon: dict[str, float], haystack: str) -> float:
    """haystack에 매칭된 term들의 가중합.

    더 긴 매칭 term의 부분문자열인 term은 제외(longest-match-wins) — 예:
    '적자전환' 매칭 시 '적자'가 중복 계산되지 않도록 한다.
    """
    matched = [t for t in lexicon if t in haystack]
    total = 0.0
    for term in matched:
        if any(term != other and term in other for other in matched):
            continue
        total += lexicon[term]
    return total


@dataclass(frozen=True)
class ChunkScore:
    """스코어링 결과 + provenance. 추후 confidence/feature 필드 확장 가능."""

    sentiment: float  # [-1, 1]
    importance: float  # [0, 1]
    method: str  # 생성 스코어러 식별자 (예: "rule_v1")


class Scorer(Protocol):
    """스코어러 인터페이스 — 룰베이스/모델 구현 교체점."""

    method: str

    def score(
        self,
        text: str,
        source_type: NewsSourceType,
        title: str | None,
        metadata: dict[str, object],
    ) -> ChunkScore: ...


class RuleBasedScorer:
    """키워드 lexicon + source_type 가중 기반 룰베이스 스코어러."""

    method = "rule_v1"

    def score(
        self,
        text: str,
        source_type: NewsSourceType,
        title: str | None,
        metadata: dict[str, object],
    ) -> ChunkScore:
        """청크 텍스트를 받아 sentiment/importance 스코어를 계산한다."""
        try:
            return self._score(text, source_type, title)
        except Exception:  # noqa: BLE001 — 향후 lexicon 타입 변경 등 미래 변경으로부터 적재 파이프라인 보호
            return ChunkScore(0.0, 0.0, self.method)

    def _score(
        self, text: str, source_type: NewsSourceType, title: str | None,
    ) -> ChunkScore:
        """내부 스코어 계산 로직."""
        haystack = f"{title or ''} {text or ''}".strip()
        if not haystack:
            return ChunkScore(0.0, 0.0, self.method)

        pos = _matched_weight(POSITIVE_TERMS, haystack)
        neg = _matched_weight(NEGATIVE_TERMS, haystack)
        sentiment = math.tanh((pos - neg) / SENTIMENT_SCALE)

        base = IMPORTANCE_BASE.get(source_type, _IMPORTANCE_DEFAULT)
        boost = _matched_weight(HIGH_IMPACT_TERMS, haystack)
        importance = max(0.0, min(1.0, base + boost))

        return ChunkScore(round(sentiment, 4), round(importance, 4), self.method)


# 룰베이스 스코어러는 I/O 없는 순수 객체이므로 임포트 시점에 즉시 생성해도 안전하다
# (Embedder.get() 처럼 지연 초기화가 필요 없다).
_DEFAULT_SCORER: Scorer = RuleBasedScorer()


def get_scorer() -> Scorer:
    """현재 활성 스코어러를 반환. 추후 env/config로 모델 스코어러 선택 확장."""
    return _DEFAULT_SCORER
