"""수급(투자자별 매매·공매도) 텍스트 파서 + flow_score 순수 스코어러.

news_chunks.chunk_text에 저장된 수급 텍스트에서 순매수/공매도 수치를 파싱하고,
[-1.0, 1.0] 범위의 수급 점수를 계산한다. **순수 함수만 제공** — DB/API/엔진 접근
없음(전략 모듈 경계: 데이터를 인자로만 받는다). 호출부 배선은 별도(수동 계획).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "라벨: +1,234원" / "라벨: 1,234주"에서 부호 포함 정수를 뽑는 캡처 패턴.
_NUM = r"([+-]?[\d,]+)"


@dataclass(frozen=True)
class FlowFeatures:
    """수급 텍스트에서 파싱한 피처. 미발견 항목은 None (단위: 원 또는 주)."""

    institution_net: int | None = None
    foreign_net: int | None = None
    pension_net: int | None = None
    individual_net: int | None = None
    short_balance_qty: int | None = None
    short_volume_qty: int | None = None


def _find_int(pattern: str, text: str) -> int | None:
    """`pattern`의 첫 캡처그룹을 정수로 변환한다. 매칭 없으면 None."""
    match = re.search(pattern, text)
    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


def parse_flow_text(chunk_text: str) -> FlowFeatures:
    """투자자별 매매 / 공매도 잔고 텍스트에서 수급 피처를 파싱한다.

    한 청크는 둘 중 하나의 포맷이며, 매칭되는 항목만 채우고 나머지는 None이다.
    라벨은 줄 시작에 고정(`외국인`이 `기타외국인` 줄을 잘못 잡지 않도록).
    """
    return FlowFeatures(
        institution_net=_find_int(rf"(?m)^기관합계 순매수:\s*{_NUM}", chunk_text),
        foreign_net=_find_int(rf"(?m)^외국인 순매수:\s*{_NUM}", chunk_text),
        pension_net=_find_int(rf"(?m)^연기금 등 순매수:\s*{_NUM}", chunk_text),
        individual_net=_find_int(rf"(?m)^개인 순매수:\s*{_NUM}", chunk_text),
        short_balance_qty=_find_int(rf"(?m)^잔고 수량:\s*{_NUM}주", chunk_text),
        short_volume_qty=_find_int(
            rf"(?m)^당일 공매도 거래량:\s*{_NUM}주", chunk_text
        ),
    )


def flow_score(features: FlowFeatures) -> float:
    """수급 점수 [-1.0, 1.0]. 기관+외국인 순매수 방향을 전체 활동 대비 비율로 반환.

    양수=기관·외국인 매수 우위(강세), 음수=매도 우위(약세). 수급 항목이 전혀
    없으면 0.0. 공매도 항목은 일중 거래량 맥락이 없어 현재 점수에 미반영한다.
    """
    if features.institution_net is None and features.foreign_net is None:
        return 0.0
    inst = features.institution_net or 0
    frgn = features.foreign_net or 0
    indiv = features.individual_net or 0
    smart = inst + frgn
    denom = abs(inst) + abs(frgn) + abs(indiv)
    if denom == 0:
        return 0.0
    return max(-1.0, min(1.0, smart / denom))
