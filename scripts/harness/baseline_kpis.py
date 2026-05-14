"""Phase 0 baseline KPI 측정 스크립트.

자동 구현 파이프라인의 현황 KPI를 산출한다. 측정 범위는 최근 N일(기본 90일).

- 제안서 상태 분포(state) — docs/proposals/*.md 메타데이터 파싱
- 카테고리 분포 — markdown + implementation_logs
- 사이클 성공률 — implemented / (implemented + failed + skipped)
- 7일 내 동일 모듈 재수정 빈도 — implementation_logs.changed_files 기반
- 구현 cadence — implementation_logs.implemented_at 분포
- 토큰 사용량 — 현재 미적재(N/A)로 기록, Phase 3+에서 trajectory 테이블에 추가 예정

CLI:
    python -m scripts.harness.baseline_kpis [--days 90] [--out docs/harness/phase0_baseline.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from src.db.models import ImplementationLog
from src.db.session import get_session

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSALS_DIR = REPO_ROOT / "docs" / "proposals"

# `## 메타데이터` 블록 내 `- key: value` 라인 파서
META_LINE = re.compile(r"^-\s*([^:]+?)\s*:\s*(.+?)\s*$")
DATE_FROM_FILENAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


def parse_proposal_meta(path: Path) -> dict[str, str]:
    """제안서 markdown의 `## 메타데이터` 블록을 파싱한다.

    Args:
        path: 제안서 파일 경로

    Returns:
        파싱된 메타데이터 dict (key는 한글). 파싱 실패 시 빈 dict.
    """
    meta: dict[str, str] = {}
    in_meta = False
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("## 메타데이터") or line.startswith("## 메타 정보"):
                in_meta = True
                continue
            if in_meta:
                if line.startswith("## "):
                    break
                m = META_LINE.match(line)
                if m:
                    meta[m.group(1)] = m.group(2)
    except OSError:
        pass
    # 파일명에서 일자 추정 (메타에 누락된 경우 fallback)
    if "일자" not in meta:
        fm = DATE_FROM_FILENAME.match(path.name)
        if fm:
            meta["일자"] = fm.group(1)
    return meta


def collect_proposals() -> list[dict[str, Any]]:
    """모든 제안서를 메타데이터와 함께 수집한다."""
    items: list[dict[str, Any]] = []
    for p in sorted(PROPOSALS_DIR.glob("*.md")):
        meta = parse_proposal_meta(p)
        items.append(
            {
                "filename": p.name,
                "date": meta.get("일자"),
                "state": meta.get("상태", "unknown"),
                "category": meta.get("카테고리", "unknown"),
                "priority": meta.get("우선순위", "unknown"),
            }
        )
    return items


def compute_proposal_kpis(items: list[dict[str, Any]]) -> dict[str, Any]:
    """제안서 markdown 기반 KPI."""
    state_dist = Counter(i["state"] for i in items)
    category_dist = Counter(i["category"] for i in items)
    priority_dist = Counter(i["priority"] for i in items)

    implemented = state_dist.get("implemented", 0)
    failed = state_dist.get("failed", 0)
    skipped = state_dist.get("skipped", 0)
    denom = implemented + failed + skipped
    success_rate = (implemented / denom) if denom else None

    return {
        "total_proposals": len(items),
        "state_distribution": dict(state_dist),
        "category_distribution": dict(category_dist),
        "priority_distribution": dict(priority_dist),
        "success_rate": success_rate,
        "success_rate_denominator": denom,
    }


def fetch_impl_logs(days: int) -> list[ImplementationLog]:
    """최근 N일의 implementation_logs를 조회한다."""
    since = datetime.now(UTC) - timedelta(days=days)
    with get_session() as session:
        stmt = (
            select(ImplementationLog)
            .where(ImplementationLog.implemented_at >= since)
            .order_by(ImplementationLog.implemented_at)
        )
        rows = list(session.scalars(stmt))
        # 세션 종료 전 필요한 속성을 미리 추출하여 detached 객체 사용 방지
        for r in rows:
            _ = r.id, r.title, r.category, r.changed_files, r.implemented_at, r.version
        return rows


def extract_changed_paths(changed_files: Any) -> list[str]:
    """changed_files JSONB에서 파일 경로 리스트를 추출한다.

    포맷은 시점별로 다양할 수 있으므로 list/dict 양쪽을 허용한다.
    """
    if not changed_files:
        return []
    if isinstance(changed_files, list):
        paths: list[str] = []
        for item in changed_files:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                p = item.get("path") or item.get("file")
                if isinstance(p, str):
                    paths.append(p)
        return paths
    if isinstance(changed_files, dict):
        files = changed_files.get("files") or changed_files.get("paths")
        if isinstance(files, list):
            return [f for f in files if isinstance(f, str)]
    return []


def compute_impl_kpis(logs: list[ImplementationLog], days: int) -> dict[str, Any]:
    """implementation_logs 기반 KPI."""
    if not logs:
        return {
            "window_days": days,
            "implemented_count": 0,
            "category_distribution": {},
            "reedit_within_7d": {"unique_files": 0, "reedited_files": 0, "ratio": None},
            "implementations_per_active_day": None,
            "version_progression": [],
            "token_usage": "N/A (currently not tracked; planned for Phase 3 trajectory table)",
        }

    cat_dist = Counter(log.category.value for log in logs)

    # 동일 파일이 7일 내 다시 수정된 빈도
    file_timestamps: dict[str, list[datetime]] = defaultdict(list)
    for log in logs:
        ts = log.implemented_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        for path in extract_changed_paths(log.changed_files):
            file_timestamps[path].append(ts)

    reedited = 0
    for stamps in file_timestamps.values():
        stamps.sort()
        for i in range(1, len(stamps)):
            if (stamps[i] - stamps[i - 1]) <= timedelta(days=7):
                reedited += 1
                break
    unique_files = len(file_timestamps)
    ratio = (reedited / unique_files) if unique_files else None

    # 활성일(=구현이 적어도 1건 있는 날)당 평균 구현 수
    active_days: Counter[str] = Counter(
        log.implemented_at.astimezone(UTC).date().isoformat() for log in logs
    )
    impl_per_day = (
        sum(active_days.values()) / len(active_days) if active_days else None
    )

    version_progression = [
        {
            "implemented_at": log.implemented_at.astimezone(UTC).isoformat(),
            "version": log.version,
            "title": log.title,
            "category": log.category.value,
        }
        for log in logs[-20:]  # 최근 20건만 trace
    ]

    return {
        "window_days": days,
        "implemented_count": len(logs),
        "category_distribution": dict(cat_dist),
        "reedit_within_7d": {
            "unique_files": unique_files,
            "reedited_files": reedited,
            "ratio": ratio,
        },
        "implementations_per_active_day": impl_per_day,
        "active_days_count": len(active_days),
        "version_progression_tail": version_progression,
        "token_usage": "N/A (currently not tracked; planned for Phase 3 trajectory table)",
    }


def render_console_summary(report: dict[str, Any]) -> str:
    """사람이 읽는 요약."""
    lines = [
        "=" * 60,
        f"Phase 0 Baseline — {report['generated_at']}",
        "=" * 60,
        "",
        f"[제안서] 총 {report['proposals']['total_proposals']}건",
    ]
    for state, n in sorted(
        report["proposals"]["state_distribution"].items(), key=lambda x: -x[1]
    ):
        lines.append(f"  - {state}: {n}")
    sr = report["proposals"]["success_rate"]
    sr_str = f"{sr * 100:.1f}%" if sr is not None else "N/A"
    lines.extend(
        [
            f"  성공률(implemented/(impl+failed+skipped)): {sr_str}"
            f" (분모 {report['proposals']['success_rate_denominator']})",
            "",
            f"[implementation_logs] 최근 {report['implementations']['window_days']}일",
            f"  - 구현 건수: {report['implementations']['implemented_count']}",
            f"  - 활성일 수: {report['implementations'].get('active_days_count', 0)}",
            f"  - 활성일당 평균 구현: "
            f"{report['implementations']['implementations_per_active_day']}",
            "  - 카테고리 분포:",
        ]
    )
    for cat, n in sorted(
        report["implementations"]["category_distribution"].items(), key=lambda x: -x[1]
    ):
        lines.append(f"      {cat}: {n}")
    reedit = report["implementations"]["reedit_within_7d"]
    reedit_ratio = (
        f"{reedit['ratio'] * 100:.1f}%" if reedit["ratio"] is not None else "N/A"
    )
    lines.extend(
        [
            "",
            f"[재발률] 7일 내 동일 파일 재수정: {reedit['reedited_files']}/{reedit['unique_files']}"
            f" ({reedit_ratio})",
            "",
            f"[토큰 사용량] {report['implementations']['token_usage']}",
            "=" * 60,
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="조회 기간(일). 기본 90.")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "docs" / "harness" / "phase0_baseline.json",
        help="JSON 결과 출력 경로",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="DB 미접속 모드(제안서 KPI만 산출)",
    )
    args = parser.parse_args(argv)

    proposals = collect_proposals()
    proposal_kpis = compute_proposal_kpis(proposals)

    if args.no_db:
        impl_kpis = {
            "window_days": args.days,
            "note": "skipped (--no-db)",
        }
    else:
        logs = fetch_impl_logs(args.days)
        impl_kpis = compute_impl_kpis(logs, args.days)

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": args.days,
        "proposals": proposal_kpis,
        "implementations": impl_kpis,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print(render_console_summary(report))
    print(f"\n→ JSON saved: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
