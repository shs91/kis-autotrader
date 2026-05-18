"""제안서 markdown의 '## 기대 효과' 섹션 → JSONB prediction.

키 형식 (BRIDGE_SPEC v3 도입 예정):
- win_rate_delta_pp: float (퍼센트 포인트)
- error_count_delta_ratio: float (비율, -0.3 = 30% 감소)
- signal_count_delta: float (개수, 절대값)
- 등 자유 형식 key: value (float 변환 가능한 라인만 적재)
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE_RE = re.compile(
    r"^-\s*(?P<key>[a-z_][a-z0-9_]*)\s*:\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*$"
)


def parse_prediction(path: Path) -> dict[str, float]:
    """`## 기대 효과` 섹션에서 정량 key:value 라인을 추출."""
    in_section = False
    result: dict[str, float] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for raw in lines:
        line = raw.strip()
        if line.startswith("## 기대 효과") or line.startswith("## 예상 효과"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            m = _LINE_RE.match(line)
            if m:
                try:
                    result[m.group("key")] = float(m.group("value"))
                except ValueError:
                    continue
    return result
