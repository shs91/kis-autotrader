"""Cycle 결산 Telegram 카드 발송 — Phase 4 wiring.

run_auto_implement.sh의 사이클 종료 단계에서 호출. format_pipeline_summary
3섹션 카드(오늘 적용 / 회귀 위험 / 예측 미달)를 만들어 Telegram으로 전송.

CLI:
    python -m scripts.harness.notify_cycle_summary --cycle-id auto-20260519-171501
    python -m scripts.harness.notify_cycle_summary --cycle-id ... --hours 12
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.analytics import get_recurrence_risk
from src.db.models import ImplementationLog
from src.db.session import get_session
from src.notify.formatter import format_pipeline_summary
from src.notify.telegram import TelegramNotifier
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def collect_applied(
    session: Session, *, since: datetime,
) -> list[dict[str, Any]]:
    """since 이후 implemented된 ImplementationLog를 카드 항목 dict로 반환."""
    stmt = (
        select(ImplementationLog)
        .where(ImplementationLog.implemented_at >= since)
        .order_by(ImplementationLog.implemented_at)
    )
    rows = list(session.execute(stmt).scalars().all())
    return [{"title": r.title, "version": r.version} for r in rows]


def collect_recurrence_risks(
    session: Session, *, window_days: int = 7, min_edits: int = 3,
) -> list[dict[str, Any]]:
    """get_recurrence_risk의 risk_components를 카드 항목 dict 리스트로 변환."""
    data = get_recurrence_risk(
        session, window_days=window_days, min_edits=min_edits,
    )
    return list(data.get("risk_components") or [])


def collect_prediction_misses(session: Session) -> list[dict[str, Any]]:
    """Phase 5 자리 — 현재는 빈 리스트.

    실측(win_rate 등) 매핑이 Phase 5 리포트 사이클에서 추가되면 prediction 대비
    미달 카테고리/메트릭으로 채운다.
    """
    return []


def build_message(
    *, cycle_id: str, session: Session, since: datetime,
) -> str:
    """3섹션 결산 카드 메시지를 생성."""
    return format_pipeline_summary(
        cycle_id=cycle_id,
        applied=collect_applied(session, since=since),
        recurrence_risks=collect_recurrence_risks(session),
        prediction_misses=collect_prediction_misses(session),
    )


async def _send(message: str, notifier: TelegramNotifier | None = None) -> None:
    n = notifier or TelegramNotifier()
    await n.send(message, urgent=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-id", required=True, help="결산 대상 cycle_id")
    parser.add_argument(
        "--hours", type=int, default=24,
        help="applied 카드를 채울 시간 윈도우 (기본 24시간)",
    )
    args = parser.parse_args(argv)
    since = datetime.now(UTC) - timedelta(hours=args.hours)
    with get_session() as session:
        msg = build_message(cycle_id=args.cycle_id, session=session, since=since)
    try:
        asyncio.run(_send(msg))
    except Exception:
        logger.exception("cycle summary 전송 실패 — 본 흐름에 영향 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
