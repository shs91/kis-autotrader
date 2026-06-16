#!/bin/bash
# KIS 자동매매 - 일간 데이터 분석 스크립트
# 평일 16:30 launchd로 실행 (auto-implement 전에 완료되어야 함)

set -euo pipefail

export HOME="/Users/songhansu"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
PROMPT_FILE="$PROJECT_DIR/docs/prompts/daily_routine.md"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_analysis_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

echo "=== Daily analysis started at $(date) ===" >> "$LOG_FILE"

cd "$PROJECT_DIR"

# claude -p 단발 호출은 API 일시 장애(401/429/529/5xx)에 그날 분석을 통째로 유실시켰다
# (2026-06-04·05 401 인증, 06-15 529 과부하). set -e 우회(if-then-else) + 지수 백오프 재시도로
# 일시 에러를 흡수하고, 전 시도 실패 시 Telegram으로 알려 조용한 유실을 막는다.
PROMPT="$(cat "$PROMPT_FILE")"
MAX_ATTEMPTS=4
BACKOFFS=(30 60 120)   # 1·2·3차 실패 후 대기(초)
CLAUDE_EXIT=0
attempt=1
while [[ "$attempt" -le "$MAX_ATTEMPTS" ]]; do
  echo "--- claude attempt $attempt/$MAX_ATTEMPTS at $(date) ---" >> "$LOG_FILE"
  if /Users/songhansu/.local/bin/claude -p "$PROMPT" \
       --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__postgres__query" \
       >> "$LOG_FILE" 2>&1; then
    CLAUDE_EXIT=0
    break
  else
    CLAUDE_EXIT=$?
    echo "[retry] claude attempt $attempt 실패 (exit=$CLAUDE_EXIT) at $(date)" >> "$LOG_FILE"
    if [[ "$attempt" -lt "$MAX_ATTEMPTS" ]]; then
      sleep "${BACKOFFS[$((attempt-1))]}"
    fi
  fi
  attempt=$((attempt+1))
done

echo "=== Daily analysis finished at $(date) — claude_exit=$CLAUDE_EXIT ===" >> "$LOG_FILE"

# 전 시도 실패 시 Telegram 에러 알림(조용한 유실 방지). Telegram은 Anthropic API와 별개라 발송 가능.
if [[ "$CLAUDE_EXIT" != "0" ]]; then
  echo "[alert] 일일분석 ${MAX_ATTEMPTS}회 모두 실패 — Telegram 알림 발송 시도" >> "$LOG_FILE"
  ERR_TAIL="$(tail -n 5 "$LOG_FILE" | tr '\n' ' ')"
  PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" -c '
import sys, asyncio
from src.notify.telegram import TelegramNotifier
asyncio.run(TelegramNotifier().notify_error(sys.argv[1], sys.argv[2]))
' "일일분석 자동화" "claude -p ${MAX_ATTEMPTS}회 실패 (exit=${CLAUDE_EXIT}). 최근 로그: ${ERR_TAIL}" \
    >> "$LOG_FILE" 2>&1 || true
fi

# 일간 리포트 영속화 (2026-05-22)
# claude -p가 생성하는 docs/reports/<날짜>_daily.md 는 untracked 상태로 남는다.
# 제안서를 구현한 날에는 auto-implement 커밋이 이 파일을 휩쓸어 보존했지만,
# 구현 0건인 날(룰 게이트 보류 등)에는 커밋 없이 untracked로 방치되다
# 이후 수동/자동 git 작업에 소실됐다. 분석 직후 리포트만 단독 커밋해 보존한다.
REPORT_REL="docs/reports/$(date +%Y-%m-%d)_daily.md"
echo "=== Report commit started at $(date) — $REPORT_REL ===" >> "$LOG_FILE"
if [[ -f "$PROJECT_DIR/$REPORT_REL" ]]; then
  REPORT_BRANCH="$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  if git -C "$PROJECT_DIR" add -- "$REPORT_REL" >> "$LOG_FILE" 2>&1; then
    if git -C "$PROJECT_DIR" diff --cached --quiet -- "$REPORT_REL"; then
      echo "[report-commit] 변경 없음 — 이미 커밋된 리포트 (branch=$REPORT_BRANCH)" >> "$LOG_FILE"
    elif git -C "$PROJECT_DIR" commit --no-verify \
        -m "docs(report): 일간 분석 리포트 $(date +%Y-%m-%d) 자동 커밋" \
        -- "$REPORT_REL" >> "$LOG_FILE" 2>&1; then
      echo "[report-commit] 커밋 완료 (branch=$REPORT_BRANCH)" >> "$LOG_FILE"
    else
      echo "[report-commit] 커밋 실패 — 수동 확인 필요 (branch=$REPORT_BRANCH)" >> "$LOG_FILE"
    fi
  else
    echo "[report-commit] git add 실패 — 스킵" >> "$LOG_FILE"
  fi
else
  echo "[report-commit] 리포트 파일 없음 — 분석이 리포트 미생성(데이터 부족 등), 스킵" >> "$LOG_FILE"
fi
echo "=== Report commit finished at $(date) ===" >> "$LOG_FILE"
