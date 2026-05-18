#!/usr/bin/env bash
# 수동 자동 구현 사이클 트리거.
#
# 사용:
#   scripts/trigger_implement.sh                     # 기본
#   scripts/trigger_implement.sh --dry              # 안전 게이트만 돌리고 구현 안 함
#   scripts/trigger_implement.sh --proposal X.md    # 단일 제안서만
#   scripts/trigger_implement.sh --force            # real+장중 가드 우회

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY=""
PROPOSAL=""
FORCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry) DRY="1"; shift ;;
    --proposal) PROPOSAL="$2"; shift 2 ;;
    --force) FORCE="--force"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

# Python 가드 평가
PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" -c "
import sys
from datetime import datetime, timezone, timedelta
from src.harness.trigger import can_trigger
from src.config import settings

# 한국 표준시
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
in_market = (
    now_kst.weekday() < 5
    and (now_kst.hour, now_kst.minute) >= (9, 0)
    and (now_kst.hour, now_kst.minute) <= (15, 30)
)
force = '$FORCE' == '--force'
d = can_trigger(env=settings.kis.env, market_hour=in_market, force=force)
if not d.allowed:
    print(f'BLOCKED: {d.reason}', file=sys.stderr)
    sys.exit(2)
print('OK')
"

if [[ -n "$DRY" ]]; then
  echo "[trigger] --dry: 가드만 통과, 구현 단계 생략"
  exit 0
fi

# 자동 구현 사이클 호출 (기존 launchd 작업 재사용)
exec launchctl start com.kis.autoimplement
