#!/bin/bash
# KIS 자동매매 - 주간 데이터 분석 스크립트
# 금요일 18:00 launchd로 실행

set -euo pipefail

export HOME="/Users/songhansu"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
PROMPT_FILE="$PROJECT_DIR/docs/prompts/weekly_routine.md"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/weekly_analysis_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

echo "=== Weekly analysis started at $(date) ===" >> "$LOG_FILE"

cd "$PROJECT_DIR"
/Users/songhansu/.local/bin/claude -p "$(cat "$PROMPT_FILE")" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__postgres__query" \
  >> "$LOG_FILE" 2>&1

echo "=== Weekly analysis finished at $(date) ===" >> "$LOG_FILE"
