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
