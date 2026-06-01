#!/usr/bin/env python3
"""스크리닝 튜닝 측정 하니스 — 일별 후보 품질·전환·신호·매수퍼널 요약.

v0.8.4(엔진이 Worker 선정분만 모니터링 + buy-time 가격 하한) 이후 스크리닝 유니버스의
품질과 전환을 계량해, 데이터 기반 튜닝(소스/파라미터) 결정을 돕는다.
앙상블은 사전 백테스트가 불가하므로 forward 관측 지표를 매일 누적하는 용도.

사용법:
    python scripts/screening_diag.py             # 오늘(KST)
    python scripts/screening_diag.py 2026-06-01
    python scripts/screening_diag.py --json       # 기계 파싱용 JSON

실행 DB는 KIS_ENV에 따라 결정된다(real → kis_trader_real). 읽기 전용.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from typing import Any

sys.path.insert(0, ".")

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import settings
from src.db.analytics import (
    _day_range,
    get_daily_screening,
    get_daily_signals,
    get_daily_trades,
)
from src.db.models import SystemMetric
from src.db.session import get_session


def _metric_counts(
    session: Session, target_date: date, metric_type: str, key: str
) -> tuple[dict[str, int], int]:
    """해당일 ``metric_type`` 메트릭을 ``detail[key]`` 값별로 집계한다."""
    start, end = _day_range(target_date)
    rows = (
        session.execute(
            select(SystemMetric).where(
                SystemMetric.metric_type == metric_type,
                SystemMetric.recorded_at >= start,
                SystemMetric.recorded_at < end,
            )
        )
        .scalars()
        .all()
    )
    counter: Counter[str] = Counter()
    for m in rows:
        detail = m.detail or {}
        counter[str(detail.get(key))] += 1
    return dict(counter), len(rows)


def collect(target_date: date) -> dict[str, Any]:
    """스크리닝 튜닝용 일별 요약 지표를 수집한다."""
    scfg = settings.screening
    with get_session() as session:
        screening = get_daily_screening(session, target_date)
        signals = get_daily_signals(session, target_date)
        trades = get_daily_trades(session, target_date)
        buy_outcome, _ = _metric_counts(session, target_date, "BUY_OUTCOME", "outcome")
        _, risk_excluded_n = _metric_counts(
            session, target_date, "SCREENING_RISK_EXCLUDED", "stock_code"
        )

    # 스크리닝은 사이클마다 중복 기록 → 종목 단위로 고유화.
    # converted는 "해당일 어느 런에서든 1회라도 선정(converted_to_trade=True)"으로 판정한다.
    # (last-wins로 보면 나중 런의 converted=False 재기록에 가려져 과소집계됨)
    uniq: dict[str, dict[str, Any]] = {}
    converted_codes: set[str] = set()
    for it in screening.get("items", []):
        uniq[it["stock_code"]] = it
        if it["converted_to_trade"]:
            converted_codes.add(it["stock_code"])

    converted = [uniq[c] for c in converted_codes]
    out_of_band = [
        it
        for it in uniq.values()
        if it["price_change_pct"] is not None
        and (
            it["price_change_pct"] < scfg.change_rate_min
            or it["price_change_pct"] > scfg.change_rate_max
        )
    ]

    sig_types = Counter(s["signal_type"] for s in signals)
    max_conf = max((s["confidence"] for s in signals), default=0.0)
    acted = sum(1 for s in signals if s["action_taken"])

    return {
        "date": target_date.isoformat(),
        "screening": {
            "raw_unique_candidates": len(uniq),
            "monitored_converted": len(converted),
            "out_of_band_candidates": len(out_of_band),
            "monitored_list": [
                {
                    "code": c["stock_code"],
                    "name": c["stock_name"],
                    "rank": c["screening_rank"],
                    "change_pct": c["price_change_pct"],
                }
                for c in sorted(
                    converted, key=lambda x: x["screening_rank"] or 999
                )
            ],
            "config": {
                "top_n": scfg.top_n,
                "max_screened": scfg.max_screened,
                "price": [scfg.min_price, scfg.max_price],
                "change_rate": [scfg.change_rate_min, scfg.change_rate_max],
                "min_volume": scfg.min_volume,
                "min_score": scfg.min_score,
            },
        },
        "signals": {
            "total": len(signals),
            "by_type": dict(sig_types),
            "max_confidence": round(max_conf, 4),
            "acted": acted,
        },
        "buy_outcome": buy_outcome,
        "risk_excluded_count": risk_excluded_n,
        "trades": len(trades),
    }


def render(data: dict[str, Any]) -> str:
    """사람이 읽기 쉬운 한 화면 요약으로 렌더링한다."""
    s = data["screening"]
    sig = data["signals"]
    cfg = s["config"]
    lines = [
        f"📊 스크리닝 측정 — {data['date']}",
        f"  후보(고유) {s['raw_unique_candidates']} → 모니터링(converted) "
        f"{s['monitored_converted']}  | 밴드이탈 후보 {s['out_of_band_candidates']}",
    ]
    for m in s["monitored_list"]:
        lines.append(
            f"    · {m['code']} {m['name']} (rank {m['rank']}, {m['change_pct']}%)"
        )
    lines.append(
        f"  설정: price {cfg['price']} TOP_N {cfg['top_n']} "
        f"max_screened {cfg['max_screened']} min_vol {cfg['min_volume']} "
        f"change {cfg['change_rate']} min_score {cfg['min_score']}"
    )
    lines.append(
        f"  신호: {sig['total']}건 {sig['by_type']} "
        f"max_conf={sig['max_confidence']} acted={sig['acted']}"
    )
    lines.append(f"  매수퍼널(BUY_OUTCOME): {data['buy_outcome'] or '없음'}")
    lines.append(
        f"  위험배제: {data['risk_excluded_count']}건 | 체결: {data['trades']}건"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="스크리닝 튜닝 측정 하니스")
    parser.add_argument("date", nargs="?", help="YYYY-MM-DD (기본: 오늘 KST)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args(argv)

    if args.date:
        target = date.fromisoformat(args.date)
    else:
        target = date.today()  # noqa: DTZ011 — 시스템 로컬(KST) 기준, 프로젝트 관례
    data = collect(target)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))


if __name__ == "__main__":
    main()
