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

echo "=== Auto-implement started at $(date) ===" >> "$LOG_FILE"

# Claude Code 실행 (비대화형 모드, 최대 허용)
cd "$PROJECT_DIR"
/Users/songhansu/.local/bin/claude -p "$(cat "$PROMPT_FILE")" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
  >> "$LOG_FILE" 2>&1

echo "=== Auto-implement finished at $(date) ===" >> "$LOG_FILE"

# 패치노트 Google Calendar 등록
echo "=== Patch note event started at $(date) ===" >> "$LOG_FILE"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/create_patch_note_event.py" \
  >> "$LOG_FILE" 2>&1 || true
echo "=== Patch note event finished at $(date) ===" >> "$LOG_FILE"
