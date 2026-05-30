"""치명 공시 키워드 매칭 — 매수 리스크 판정의 단일 진실원천.

상장폐지/정리매매/관리종목 등 "사면 안 되는" 종목을 DART 공시 제목으로
판별하는 순수 로직(모델 미사용, DB/API 미접근). 매매 엔진의 매수 직전
게이트(``engine._check_disclosure_risk_block``)와 스크리닝 Worker의 후보
사전 배제(``worker.screener``)가 **동일한 키워드·매처**를 공유해 드리프트를
방지하기 위해 분리했다.

설계 메모:
- ``거래정지`` 단일 키워드는 제외한다 — "주권매매거래정지**해제**"(거래 재개=호재)
  오탐을 피하기 위함. 상장폐지/정리매매/관리종목 등 명확한 항목으로 충분히 잡힌다.
  (실데이터 예: "주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)"는
  ``상장폐지``·``정리매매``로 매칭된다.)
"""

from __future__ import annotations

# 매수를 차단해야 하는 치명 공시 키워드(부분 문자열 매칭).
CRITICAL_DISCLOSURE_KEYWORDS: tuple[str, ...] = (
    "상장폐지",
    "정리매매",
    "관리종목",
    "회생절차",
    "감사의견거절",
    "감사의견 거절",
    "횡령",
    "배임",
    "부도",
    "영업정지",
)


def match_critical_disclosure(titles: list[str]) -> str | None:
    """공시 제목 목록에서 치명 키워드를 가진 첫 제목을 반환(없으면 None)."""
    for title in titles:
        if any(kw in title for kw in CRITICAL_DISCLOSURE_KEYWORDS):
            return title
    return None
