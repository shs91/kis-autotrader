"""하네스 사이클 KPI 대시보드 페이지 — Phase 4."""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit이 pages/*.py를 별도 컨텍스트로 실행 — sys.path[0]은 이 파일의
# 디렉토리. src.* import를 위해 프로젝트 루트를 path에 추가.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from datetime import UTC, datetime, timedelta  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from src.db.analytics import (  # noqa: E402
    get_prediction_calibration,
    get_recurrence_risk,
)
from src.db.models import (  # noqa: E402
    ImplementationLog,
    Proposal,
    ProposalState,
    TrajectoryEntry,
    TrajectoryStep,
)
from src.db.session import get_session  # noqa: E402

st.set_page_config(page_title="Pipeline KPI", layout="wide")
st.title("🛠 하네스 사이클 KPI")

with get_session() as session:
    # ── Section 1: 사이클 성공률 (30일)
    since_30d = datetime.now(UTC) - timedelta(days=30)
    impl_count = session.execute(
        select(func.count(ImplementationLog.id)).where(
            ImplementationLog.implemented_at >= since_30d
        )
    ).scalar() or 0
    failed_count = session.execute(
        select(func.count(Proposal.id)).where(
            Proposal.state == ProposalState.FAILED,
            Proposal.last_attempt_at >= since_30d,
        )
    ).scalar() or 0
    skipped_count = session.execute(
        select(func.count(Proposal.id)).where(
            Proposal.state == ProposalState.SKIPPED,
            Proposal.last_attempt_at >= since_30d,
        )
    ).scalar() or 0
    denom = impl_count + failed_count + skipped_count
    success_rate = (impl_count / denom * 100) if denom else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("30일 성공률", f"{success_rate:.1f}%")
    col2.metric("적용 건수", impl_count)
    col3.metric("실패/스킵", f"{failed_count} / {skipped_count}")

    # ── Section 2: MTTR (mean time to revert) — trajectory 기반
    st.subheader("MTTR (mean time to revert)")
    rollback_rows = list(session.execute(
        select(TrajectoryEntry).where(
            TrajectoryEntry.step.in_([TrajectoryStep.ROLLBACK]),
            TrajectoryEntry.started_at >= since_30d,
        )
    ).scalars().all())
    if rollback_rows:
        avg_seconds = sum(r.duration_seconds or 0 for r in rollback_rows) / len(rollback_rows)
        st.write(f"평균 {avg_seconds:.0f}초, 총 {len(rollback_rows)}회")
    else:
        st.info("30일 내 rollback 이벤트 없음")

    # ── Section 3: Top failure reasons
    st.subheader("Top failure reasons (30일)")
    fail_rows = list(session.execute(
        select(Proposal.failure_reason, func.count(Proposal.id))
        .where(Proposal.state == ProposalState.FAILED,
               Proposal.last_attempt_at >= since_30d)
        .group_by(Proposal.failure_reason)
        .order_by(func.count(Proposal.id).desc())
        .limit(10)
    ).all())
    if fail_rows:
        df_fail = pd.DataFrame(fail_rows, columns=["reason", "count"])
        st.dataframe(df_fail, hide_index=True)
    else:
        st.info("실패 이력 없음")

    # ── Section 4: Component edit heatmap (재발 위험)
    st.subheader("Component edit heatmap (7일 / 재발 위험 ≥ 3회)")
    recur = get_recurrence_risk(session, window_days=7, min_edits=3)
    if recur["risk_components"]:
        st.dataframe(pd.DataFrame(recur["risk_components"]), hide_index=True)
    else:
        st.info("재발 위험 component 없음")
    if recur["risk_files"]:
        st.write("**파일 단위 재발**")
        st.dataframe(pd.DataFrame(recur["risk_files"]), hide_index=True)

    # ── Section 5: Prediction calibration (현재 prediction 분포만)
    st.subheader("Prediction calibration (30일)")
    cal = get_prediction_calibration(session, window_days=30)
    st.write(
        f"제안서 {cal['proposal_count']}건 중 "
        f"{cal['with_prediction_count']}건이 prediction 보유"
    )
    if cal["categories"]:
        cal_rows = []
        for category, metrics in cal["categories"].items():
            for metric_name, stats in metrics.items():
                cal_rows.append({
                    "category": category,
                    "metric": metric_name,
                    "count": stats["count"],
                    "avg_predicted": round(stats["avg_predicted"], 3),
                })
        st.dataframe(pd.DataFrame(cal_rows), hide_index=True)
    else:
        st.info("prediction 데이터 없음 (제안서 ## 기대 효과 섹션 미작성)")
