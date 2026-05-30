#!/usr/bin/env python
"""실체결 슬리피지 분석 — 소액 실전 캘리브레이션 졸업 판정.

`FILL_SLIPPAGE` 메트릭(엔진이 매 체결 시 적재)을 집계해 실전 체결 비용을 추정하고,
모의 평균 엣지(+157 bps/거래)와 비교해 50만원 확대 가능 여부를 판정한다.

사용:
    python scripts/analyze_slippage.py            # 최근 14일
    python scripts/analyze_slippage.py --days 7
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.db.models import Trade, TradeType  # noqa: E402
from src.db.repository import SystemMetricRepository  # noqa: E402
from src.db.session import get_session  # noqa: E402

# 모의 8주 평균 실현 엣지(체결 1건당). 슬리피지 0·즉시체결 가정의 gross 수치.
MOCK_EDGE_BPS = 157.0
# 한국 왕복 세금·수수료(KIS 온라인 ~0.0140527%×2 + 매도세 0.18%) ≈ 21 bps
FEE_TAX_BPS = 21.0
# 통계적 신뢰를 위한 최소 체결 표본
MIN_FILLS_FOR_VERDICT = 20


def _pct(values: list[float], p: float) -> float:
    """간이 백분위수(선형 보간 없이 nearest-rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1)
    return ordered[max(0, idx)]


def _stats(label: str, adverse: list[float]) -> dict[str, float]:
    if not adverse:
        print(f"  {label}: 표본 없음")
        return {"n": 0, "mean": 0.0, "median": 0.0, "p90": 0.0}
    n = len(adverse)
    mean = sum(adverse) / n
    median = sorted(adverse)[n // 2]
    p90 = _pct(adverse, 90)
    print(
        f"  {label}: n={n}  평균 {mean:+.1f} bps  중앙 {median:+.1f} bps  "
        f"p90 {p90:+.1f} bps"
    )
    return {"n": float(n), "mean": mean, "median": median, "p90": p90}


def main() -> None:
    parser = argparse.ArgumentParser(description="실체결 슬리피지 분석/졸업 판정")
    parser.add_argument("--days", type=int, default=14, help="분석 기간(일, 기본 14)")
    args = parser.parse_args()

    cutoff = datetime.now(UTC) - timedelta(days=args.days)

    with get_session() as session:
        metrics = SystemMetricRepository(session).get_by_type("FILL_SLIPPAGE", since=cutoff)
        sells = list(
            session.execute(
                select(Trade).where(
                    Trade.trade_type == TradeType.SELL, Trade.traded_at >= cutoff
                )
            ).scalars()
        )

    buy_adv = [
        float(m.detail["adverse_bps"])
        for m in metrics
        if m.detail and m.detail.get("side") == "BUY" and "adverse_bps" in m.detail
    ]
    sell_adv = [
        float(m.detail["adverse_bps"])
        for m in metrics
        if m.detail and m.detail.get("side") == "SELL" and "adverse_bps" in m.detail
    ]

    print(f"\n=== 슬리피지 분석 (최근 {args.days}일, FILL_SLIPPAGE {len(metrics)}건) ===")
    print("[비용 bps] 양수 = 슬리피지로 손해 (매수 더 비싸게 / 매도 더 싸게)")
    b = _stats("매수", buy_adv)
    s = _stats("매도", sell_adv)

    # 왕복 슬리피지: 양측 표본이 있으면 합산, 매도 표본이 없으면 매수×2로 근사
    if s["n"] > 0:
        round_trip_slip = b["mean"] + s["mean"]
        basis = "매수+매도 실측"
    else:
        round_trip_slip = b["mean"] * 2
        basis = "매수×2 근사(매도 표본 없음 — 실전 매도 누적 필요)"
    round_trip_cost = round_trip_slip + FEE_TAX_BPS
    net_edge = MOCK_EDGE_BPS - round_trip_cost

    print(f"\n=== 왕복 비용 추정 ({basis}) ===")
    print(f"  슬리피지 왕복   : {round_trip_slip:+.1f} bps")
    print(f"  세금·수수료 왕복: {FEE_TAX_BPS:+.1f} bps")
    print(f"  → 왕복 총비용   : {round_trip_cost:+.1f} bps ({round_trip_cost / 100:+.2f}%)")
    print(f"  모의 평균 엣지  : {MOCK_EDGE_BPS:.0f} bps (+1.57%, gross)")
    print(f"  → 추정 순엣지   : {net_edge:+.1f} bps ({net_edge / 100:+.2f}%/거래)")

    if sells:
        realized = sum(int(t.profit_loss_amount or 0) for t in sells)
        wins = sum(1 for t in sells if (t.profit_loss_pct or 0) > 0)
        print(
            f"\n  실현(참고): 매도 {len(sells)}건, 순손익 {realized:+,}원, "
            f"승률 {wins}/{len(sells)} ({wins / len(sells) * 100:.0f}%)"
        )

    # ── 졸업 판정 ──
    print("\n=== 50만원 확대 판정 ===")
    total_fills = int(b["n"] + s["n"])
    if total_fills < MIN_FILLS_FOR_VERDICT:
        print(
            f"  ⏳ 표본 부족 ({total_fills} < {MIN_FILLS_FOR_VERDICT}) — "
            f"캘리브레이션 지속. 더 많은 실체결 누적 필요."
        )
    elif net_edge <= 0:
        print(
            "  🛑 확대 금지 — 실전 비용이 모의 엣지를 전부 잠식. "
            "전략/종목 유니버스 재검토 필요."
        )
    elif net_edge < MOCK_EDGE_BPS * 0.4:
        print(
            f"  ⚠️ 주의 — 순엣지가 모의의 {net_edge / MOCK_EDGE_BPS * 100:.0f}%로 얇음. "
            "확대 보류, 비용 절감(저가종목/유동성 필터) 우선."
        )
    else:
        print(
            f"  ✅ 확대 검토 가능 — 순엣지 {net_edge / 100:+.2f}%/거래가 비용 차감 후 유지. "
            "단계적으로 50만원 상향 권장(급격한 전액 투입 금지)."
        )
    print()


if __name__ == "__main__":
    main()
