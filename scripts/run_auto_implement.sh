#!/bin/bash
# KIS 자동매매 - Claude Code 자동 구현 스크립트
# 평일 17:00 cron으로 실행

set -euo pipefail

# launchd/cron 환경에서 누락될 수 있는 환경변수 설정
# .venv/bin 선두 prepend — verifier가 subprocess로 호출하는 ruff 바이너리가 venv에만 존재(2026-05-17 실패 사례)
export HOME="/Users/songhansu"
export PATH="$HOME/IdeaProjects/kis-autotrader/.venv/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
PROMPT_FILE="$PROJECT_DIR/scripts/auto_implement_prompt.txt"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/auto_implement_$(date +%Y-%m-%d).log"

# 로그 디렉토리 확인
mkdir -p "$LOG_DIR"

# 하네스 pause lock 체크 (Phase 1 T12)
PAUSE_LOCK="${HARNESS_PAUSE_LOCK_PATH:-$HOME/.kis-autotrader/harness-paused}"
if [[ -f "$PAUSE_LOCK" ]]; then
  echo "[auto-implement] paused (lock=$PAUSE_LOCK) — skip cycle at $(date)" >> "$LOG_FILE"
  exit 0
fi

echo "=== Auto-implement started at $(date) ===" >> "$LOG_FILE"

# Phase 3 hotfix A: markdown → proposals DB 동기화 (cron 사이클 직전)
# 분석 단계(주간/일간 Cowork)가 새로 작성한 ready 제안서를 DB에 적재해야
# Cycle Orchestrator의 list_ready()가 인식한다.
cd "$PROJECT_DIR"
echo "=== Proposal sync started at $(date) ===" >> "$LOG_FILE"
PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" \
  -m scripts.harness.sync_proposals_md_to_db >> "$LOG_FILE" 2>&1
SYNC_EXIT=$?
echo "=== Proposal sync finished at $(date) — exit=$SYNC_EXIT ===" >> "$LOG_FILE"

# Phase 3: Initializer + new top-level prompt (subagent 오케스트레이션)
PROGRESS_PATH="$HOME/.kis-autotrader/claude-progress.json"
PROMPT_FILE_V2="$PROJECT_DIR/scripts/auto_implement_prompt_v2.txt"

# Phase 3 hotfix D1: if-then-else로 감싸 set -e가 cycle 실패에 트리거되지 않게 함
# Phase 4 wiring: TrajectoryRepository를 주입해 사이클 단계별 trajectory 적재
if PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" -c "
from pathlib import Path
from src.config import settings
from src.db.repository import TrajectoryRepository
from src.db.session import get_session
from src.harness.cycle.orchestrator import run_cycle
with get_session() as session:
    outcome = run_cycle(
        repo_root=Path('$PROJECT_DIR'),
        env=settings.kis.env,
        progress_path=Path('$PROGRESS_PATH'),
        prompt_path=Path('$PROMPT_FILE_V2'),
        trajectory_repo=TrajectoryRepository(session),
    )
print(f'[cycle] {outcome.cycle_id} claude_exit={outcome.claude_exit_code} '
      f'completed={outcome.completed_count} failed={outcome.failed_count} '
      f'skipped={outcome.skipped_count}')
" >> "$LOG_FILE" 2>&1; then
  CYCLE_EXIT=0
else
  CYCLE_EXIT=$?
fi

echo "=== Auto-implement finished at $(date) — cycle_exit=$CYCLE_EXIT ===" >> "$LOG_FILE"

# Phase 2: 골든 회귀 셋 사전 검증 (D1: set -e 우회)
echo "=== Golden regression check started at $(date) ===" >> "$LOG_FILE"
if PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" -m pytest \
  "$PROJECT_DIR/tests/eval/test_golden_runner.py" -q --no-header \
  >> "$LOG_FILE" 2>&1; then
  GOLDEN_EXIT=0
else
  GOLDEN_EXIT=$?
fi
echo "=== Golden regression check finished at $(date) — exit=$GOLDEN_EXIT ===" >> "$LOG_FILE"

# Phase 2: Verifier 실행 (변경 사항이 있을 때만)
if git -C "$PROJECT_DIR" diff --quiet HEAD; then
  echo "[verifier] no diff vs HEAD — skip verifier" >> "$LOG_FILE"
  VERIFIER_EXIT=0
else
  VERIFIER_OUT="$LOG_DIR/verifier_$(date +%Y-%m-%d_%H%M%S).json"
  # Phase 3 hotfix D1: set -e가 verifier exit 2를 잡지 않도록 if-then-else
  if PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" \
    -m scripts.harness.run_verifier \
    --base-ref HEAD~1 --head-ref HEAD --out "$VERIFIER_OUT" \
    >> "$LOG_FILE" 2>&1; then
    VERIFIER_EXIT=0
  else
    VERIFIER_EXIT=$?
  fi
  echo "[verifier] exit=$VERIFIER_EXIT artifact=$VERIFIER_OUT" >> "$LOG_FILE"
fi

# 구현 성공 시 서비스 재시작 (BRIDGE_SPEC 규격 + Phase 2 Verifier 통과 강제)
if [[ "$CYCLE_EXIT" == "0" && "$GOLDEN_EXIT" == "0" && "$VERIFIER_EXIT" == "0" ]] && grep -q "implemented" "$LOG_FILE" 2>/dev/null; then
  echo "=== Service restart started at $(date) ===" >> "$LOG_FILE"
  launchctl stop com.kis.autotrader 2>> "$LOG_FILE" || true
  sleep 5
  launchctl start com.kis.autotrader 2>> "$LOG_FILE" || true
  sleep 10
  if launchctl list 2>/dev/null | grep -q "com.kis.autotrader"; then
    echo "서비스 재시작 완료" >> "$LOG_FILE"
  else
    echo "서비스 재시작 실패 — 수동 확인 필요" >> "$LOG_FILE"
  fi
  echo "=== Service restart finished at $(date) ===" >> "$LOG_FILE"
else
  echo "구현된 제안서 없음 — 재시작 스킵" >> "$LOG_FILE"
fi

# Phase 4 wiring: 사이클 결산 카드 Telegram 발송 (실패 사이클도 발송)
echo "=== Cycle summary notify started at $(date) ===" >> "$LOG_FILE"
CYCLE_ID=$(grep '^\[cycle\] ' "$LOG_FILE" | tail -1 | awk '{print $2}')
if [[ -n "$CYCLE_ID" ]]; then
  PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" \
    -m scripts.harness.notify_cycle_summary --cycle-id "$CYCLE_ID" \
    >> "$LOG_FILE" 2>&1 || true
else
  echo "[notify] cycle_id 추출 실패 — 결산 스킵" >> "$LOG_FILE"
fi
echo "=== Cycle summary notify finished at $(date) ===" >> "$LOG_FILE"

# 패치노트 Google Calendar 등록
echo "=== Patch note event started at $(date) ===" >> "$LOG_FILE"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/create_patch_note_event.py" \
  >> "$LOG_FILE" 2>&1 || true
echo "=== Patch note event finished at $(date) ===" >> "$LOG_FILE"
