#!/bin/bash
# KIS 자동매매 - Claude Code 자동 구현 스크립트
# 평일 17:00 cron으로 실행

set -euo pipefail

# launchd/cron 환경에서 누락될 수 있는 환경변수 설정
export HOME="/Users/songhansu"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

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

# Claude Code 실행 (비대화형 모드, 최대 허용)
cd "$PROJECT_DIR"
/Users/songhansu/.local/bin/claude -p "$(cat "$PROMPT_FILE")" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
  >> "$LOG_FILE" 2>&1

echo "=== Auto-implement finished at $(date) ===" >> "$LOG_FILE"

# 구현 성공 시 서비스 재시작 (BRIDGE_SPEC 규격)
if grep -q "implemented" "$LOG_FILE" 2>/dev/null; then
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

# 패치노트 Google Calendar 등록
echo "=== Patch note event started at $(date) ===" >> "$LOG_FILE"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/create_patch_note_event.py" \
  >> "$LOG_FILE" 2>&1 || true
echo "=== Patch note event finished at $(date) ===" >> "$LOG_FILE"
