# 수급 섀도우 필터 — flow_filter 순수 스코어러 추가

## 메타데이터
- 작성: Cowork
- 일자: 2026-06-12
- 상태: ready
- 우선순위: medium
- 카테고리: new_strategy
- 관련파일: `src/strategy/flow_filter.py` (신규), `tests/test_strategy/test_flow_filter.py` (신규)

## 현상 분석
- 실전 `news_chunks`의 수급 데이터(투자자별 매매 / 공매도 잔고)는 `chunk_text`에 **자유 텍스트로만** 존재한다. 매매 보조신호로 쓰려면 숫자 파싱·점수화가 선행돼야 한다.
- 전체 활용(수집 범위 확대·스코어링 가동·엔진 배선)은 `worker`/`db`/`rag` 인프라라 자동 안전게이트 밖이다 → `docs/plans/2026-06-12_news-flow-data-utilization.md`(수동)에서 다룬다.
- 본 제안은 그중 **순수(무 I/O) 파서 + 스코어러**만 먼저 안전하게 도입한다. 매매경로·DB·스키마를 건드리지 않으므로 자동 구현 가능하다.
- 안전게이트 부합: 신규 파일은 `src/strategy`·`tests` 한정(2파일), 외부 패키지·스키마 변경 없음, 기존 파일 무수정.

## 제안 내용
- `chunk_text`(투자자별 매매 / 공매도 잔고)에서 기관합계·외국인·연기금·개인 순매수와 공매도 잔고/거래량을 파싱하는 `FlowFeatures` + `parse_flow_text()`, 그리고 `[-1.0, 1.0]` 범위의 `flow_score()` 순수 함수를 추가한다.
- 전략 모듈 규약(데이터를 인자로 수신, 순수 함수, DB/엔진 접근 없음)을 준수한다. **호출부 배선은 본 제안 범위 밖**(수동 계획 Phase 3).
- 점수 정의: `(기관합계 + 외국인 순매수) / (|기관합계| + |외국인| + |개인|)` → 양수=기관·외국인 매수 우위(강세), 음수=매도 우위. 공매도 항목은 일중 거래량 맥락이 없어 현재 점수 미반영, 피처로만 노출.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/flow_filter.py` (신규 생성) — 아래 전체 내용:

```python
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
```

- `tests/test_strategy/test_flow_filter.py` (신규 생성) — 아래 전체 내용:

```python
"""flow_filter 순수 스코어러 테스트 (실전 DB 실제 청크 문자열 사용)."""

from __future__ import annotations

from src.strategy.flow_filter import FlowFeatures, flow_score, parse_flow_text

_TRADE_TEXT = (
    "[투자자별 매매] 005880 — 2026-06-10\n"
    "금융투자 순매수: +1,141,731원\n"
    "보험 순매수: +0원\n"
    "투신 순매수: +7,545,500원\n"
    "사모 순매수: +32,202,302원\n"
    "은행 순매수: +0원\n"
    "기타금융 순매수: +0원\n"
    "연기금 등 순매수: +66,255,734원\n"
    "기관합계 순매수: +107,145,267원\n"
    "기타법인 순매수: +60,028,281원\n"
    "개인 순매수: +861,030,996원\n"
    "외국인 순매수: -1,091,127,076원\n"
    "기타외국인 순매수: +62,922,532원\n"
    "전체 순매수: +0원"
)

_SHORT_TEXT = (
    "[공매도 잔고] 005880 — 2026-06-10\n"
    "잔고 수량: 1,070,919주\n"
    "잔고 금액: 2,056,164,480원\n"
    "당일 공매도 거래량: 584,958주 (1,110,120,249원)"
)


def test_parse_trade_text() -> None:
    f = parse_flow_text(_TRADE_TEXT)
    assert f.institution_net == 107_145_267
    assert f.foreign_net == -1_091_127_076  # 기타외국인(+62,922,532)이 아니어야 함
    assert f.pension_net == 66_255_734
    assert f.individual_net == 861_030_996
    assert f.short_balance_qty is None


def test_parse_short_text() -> None:
    f = parse_flow_text(_SHORT_TEXT)
    assert f.short_balance_qty == 1_070_919
    assert f.short_volume_qty == 584_958
    assert f.institution_net is None


def test_flow_score_sign_and_bounds() -> None:
    score = flow_score(parse_flow_text(_TRADE_TEXT))
    assert score < 0.0  # 외국인 대량 순매도 → 음수
    assert -1.0 <= score <= 1.0


def test_flow_score_positive() -> None:
    f = FlowFeatures(institution_net=100, foreign_net=50, individual_net=-150)
    assert flow_score(f) == 150 / 300


def test_flow_score_empty() -> None:
    assert flow_score(FlowFeatures()) == 0.0
    assert flow_score(parse_flow_text("관련 없는 텍스트")) == 0.0
```

### 추가 테스트 (위 파일에 포함)
- 투자자별/공매도 텍스트 파싱 정확성, 부호(+/-) 처리, `외국인` vs `기타외국인` 구분
- `flow_score` 부호·경계([-1.0, 1.0]), 빈/무관 텍스트 시 0.0 안전 반환

## 기대 효과
- 수급 점수화 로직 + 회귀 테스트가 **검증된 상태로 확보** → 수동 계획 Phase 3에서 즉시 배선 가능(엔진이 read-only로 호출).
- 매매 동작 **무변경**(순수 함수, 미배선)이라 실거래 리스크 0. 측정·검증 인프라의 첫 조각.

## 롤백
- 신규 2파일뿐이므로 `git restore`/파일 삭제로 즉시 원복. `config_overrides.json`·스키마·기존 파일에 영향 없음.
