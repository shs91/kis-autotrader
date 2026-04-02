"""일일 매매 리포트 자동 생성 스크립트.

장 마감 후 로그를 분석하여 docs/reports/daily/YYYY-MM-DD.md를 생성한다.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "autotrader.out.log"
REPORT_DIR = Path(__file__).resolve().parent.parent / "docs" / "reports" / "daily"


def main() -> None:
    today = date.today().isoformat()
    log_lines = _read_today_logs(today)

    if not log_lines:
        print(f"오늘({today}) 로그가 없습니다.")
        return

    report = _build_report(today, log_lines)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{today}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"리포트 생성 완료: {report_path}")


def _read_today_logs(today: str) -> list[str]:
    """오늘 날짜의 로그만 필터링한다."""
    if not LOG_PATH.exists():
        return []
    lines = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith(today):
            lines.append(line)
    return lines


def _build_report(today: str, lines: list[str]) -> str:
    """로그를 분석하여 리포트를 생성한다."""
    # 사이클 수
    cycle_starts = [l for l in lines if "매매 사이클 #" in l and "시작" in l]
    cycle_completes = [l for l in lines if "매매 사이클 #" in l and "완료" in l]

    # 체결 내역
    buys = [l for l in lines if "[매수 체결]" in l]
    sells = [l for l in lines if "[매도 체결]" in l]

    # 시그널 분석
    signals = [l for l in lines if "시그널=" in l]
    signal_counts: Counter[str] = Counter()
    signal_details: list[dict[str, str]] = []
    for s in signals:
        m = re.search(r"\[(\S+)\s+(\S*)\]\s+보유=(\S+),\s+시그널=(\S+),\s+신뢰도=(\S+),\s+현재가=(\S+)", s)
        if m:
            code, name, held, sig_type, confidence, price = m.groups()
            signal_counts[sig_type] += 1
            if sig_type != "HOLD":
                signal_details.append({
                    "time": s[:19],
                    "code": code,
                    "name": name,
                    "held": held,
                    "signal": sig_type,
                    "confidence": confidence,
                    "price": price,
                })

    # 스크리닝
    screen_lines = [l for l in lines if "스크리닝 완료" in l]
    discovered = [l for l in lines if "스크리닝 발굴" in l]

    # 에러
    errors = [l for l in lines if "ERROR" in l or "에러" in l or "실패" in l]
    warnings = [l for l in lines if "WARNING" in l]

    # API 호출
    api_calls = [l for l in lines if "일일 API 호출 횟수" in l]
    api_limit_hit = [l for l in lines if "한도 초과" in l]

    # 리포트 작성
    parts: list[str] = []
    parts.append(f"# [{today}] 일일 매매 리포트\n")

    parts.append("## 요약")
    parts.append(f"- 총 매매: {len(buys) + len(sells)}건 (매수 {len(buys)} / 매도 {len(sells)})")
    parts.append(f"- 스크리닝 발굴: {len(discovered)}종목")
    parts.append(f"- 에러: {len(errors)}건")
    parts.append(f"- 장중 사이클: 실행 {len(cycle_completes)}회 / 시작 {len(cycle_starts)}회")
    if api_calls:
        parts.append(f"- API 호출: {api_calls[-1].split('횟수: ')[-1] if api_calls else 'N/A'}")
    if api_limit_hit:
        parts.append(f"- **API 한도 초과 발생**: {len(api_limit_hit)}건")
    parts.append("")

    # 체결 내역
    parts.append("## 체결 내역")
    if buys or sells:
        parts.append("| 시각 | 구분 | 내용 |")
        parts.append("|------|------|------|")
        for b in buys:
            parts.append(f"| {b[:19]} | 매수 | {b.split('[매수 체결]')[-1].strip()} |")
        for s in sells:
            parts.append(f"| {s[:19]} | 매도 | {s.split('[매도 체결]')[-1].strip()} |")
    else:
        parts.append("체결 없음")
    parts.append("")

    # 시그널
    parts.append("## 전략 시그널 분석")
    parts.append(f"- HOLD: {signal_counts.get('HOLD', 0)}건")
    parts.append(f"- BUY: {signal_counts.get('BUY', 0)}건")
    parts.append(f"- SELL: {signal_counts.get('SELL', 0)}건")
    if signal_details:
        parts.append("")
        parts.append("### 비-HOLD 시그널")
        parts.append("| 시각 | 종목 | 시그널 | 신뢰도 | 현재가 |")
        parts.append("|------|------|--------|--------|--------|")
        for d in signal_details[:20]:
            parts.append(f"| {d['time']} | {d['name']}({d['code']}) | {d['signal']} | {d['confidence']} | {d['price']} |")
    parts.append("")

    # 스크리닝
    parts.append("## 스크리닝 결과")
    parts.append(f"- 실행 횟수: {len(screen_lines)}회")
    parts.append(f"- 발굴 종목: {len(discovered)}개")
    if discovered:
        for d in discovered:
            parts.append(f"  - {d.split('[스크리닝 발굴]')[-1].strip()}")
    parts.append("")

    # 에러
    parts.append("## 에러/경고")
    parts.append(f"- 에러: {len(errors)}건, 경고: {len(warnings)}건")
    if errors:
        parts.append("")
        parts.append("### 주요 에러 (최근 10건)")
        for e in errors[-10:]:
            parts.append(f"- `{e[:80]}...`")
    parts.append("")

    # 개선 포인트 (자동 분석)
    parts.append("## 개선 포인트")
    improvements: list[str] = []

    if len(buys) == 0 and len(sells) == 0:
        improvements.append("매매 0건 — 전략 파라미터 또는 전략 다양화 검토 필요")
    if signal_counts.get("BUY", 0) == 0 and signal_counts.get("SELL", 0) == 0:
        improvements.append("BUY/SELL 시그널 0건 — MA 교차가 발생하지 않음, RSI 병행 또는 파라미터 조정 검토")
    if api_limit_hit:
        improvements.append("API 일일 한도 초과 — 호출 최적화 또는 한도 상향 필요")
    if len(errors) > 10:
        improvements.append(f"에러 {len(errors)}건 — 반복 에러 패턴 분석 필요")
    if len(discovered) == 0 and len(screen_lines) > 0:
        improvements.append("스크리닝 발굴 0건 — 스크리닝 조건 완화 또는 전략 다양화 검토")

    if improvements:
        for imp in improvements:
            parts.append(f"- {imp}")
    else:
        parts.append("- 특이사항 없음")

    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    main()
