#!/bin/bash
# KIS 자동매매 — 자동 진단/수정 파이프라인
# watchdog.sh에서 반복 재시작 감지 시 트리거됨
#
# 흐름:
# 1. 에러로그 + 시스템 상태 수집 → context 파일 생성
# 2. Claude Code 진단 세션 호출
# 3. 성공 → 서비스 재시작 / 실패 → Telegram 알림

set -euo pipefail

# launchd/cron 환경 대비
export HOME="/Users/songhansu"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
LOG_DIR="$PROJECT_DIR/logs"
HEAL_LOG="$LOG_DIR/auto_heal_$(date +%Y-%m-%d).log"
CONTEXT_FILE="$LOG_DIR/heal_context_$(date +%Y-%m-%d).txt"
PROMPT_FILE="$PROJECT_DIR/scripts/auto_heal_prompt.txt"
SERVICE_NAME="com.kis.autotrader"

mkdir -p "$LOG_DIR"

TRIGGER_REASON="${1:-알 수 없는 원인}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$HEAL_LOG"
}

notify_telegram() {
    "$PROJECT_DIR/.venv/bin/python" -c "
import asyncio
from src.notify.telegram import TelegramNotifier
asyncio.run(TelegramNotifier().notify_error('AutoHeal', '$1'))
" 2>/dev/null || true
}

log "=========================================="
log "Auto-Heal 시작"
log "트리거 사유: $TRIGGER_REASON"
log "=========================================="

# ── 1단계: 진단 컨텍스트 수집 ──
log "진단 컨텍스트 수집 중..."

{
    echo "=== AUTO-HEAL DIAGNOSTIC CONTEXT ==="
    echo "수집 시각: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "트리거 사유: $TRIGGER_REASON"
    echo ""

    # 1-1. 최근 에러 로그 (ERROR/CRITICAL/Traceback)
    echo "=== 최근 에러 로그 (최근 200줄 중 에러만) ==="
    if [ -f "$LOG_DIR/autotrader.log" ]; then
        tail -500 "$LOG_DIR/autotrader.log" | grep -E "(ERROR|CRITICAL|Traceback|Exception|Error:)" | tail -100 2>/dev/null || echo "(에러 로그 없음)"
    else
        echo "(autotrader.log 파일 없음)"
    fi
    echo ""

    # 1-2. 최근 전체 로그 (마지막 100줄 — 에러 전후 문맥 파악용)
    echo "=== 최근 전체 로그 (마지막 100줄) ==="
    if [ -f "$LOG_DIR/autotrader.log" ]; then
        tail -100 "$LOG_DIR/autotrader.log" 2>/dev/null || echo "(읽기 실패)"
    fi
    echo ""

    # 1-3. stdout/stderr 로그
    echo "=== stdout/stderr 로그 (마지막 50줄) ==="
    if [ -f "$LOG_DIR/autotrader.out.log" ]; then
        tail -50 "$LOG_DIR/autotrader.out.log" 2>/dev/null || echo "(읽기 실패)"
    fi
    echo ""

    # 1-4. watchdog 로그
    echo "=== Watchdog 로그 (마지막 30줄) ==="
    if [ -f "$LOG_DIR/watchdog.log" ]; then
        tail -30 "$LOG_DIR/watchdog.log" 2>/dev/null || echo "(읽기 실패)"
    fi
    echo ""

    # 1-5. 시스템 상태
    echo "=== 시스템 상태 ==="
    echo "--- 디스크 사용량 ---"
    df -h "$PROJECT_DIR" 2>/dev/null || echo "(확인 불가)"
    echo ""
    echo "--- 메모리 ---"
    vm_stat 2>/dev/null | head -10 || free -h 2>/dev/null || echo "(확인 불가)"
    echo ""
    echo "--- Python 프로세스 ---"
    ps aux | grep -E "[p]ython.*main.py" || echo "(실행 중인 프로세스 없음)"
    echo ""

    # 1-6. DB 연결 상태
    echo "=== DB 연결 상태 ==="
    cd "$PROJECT_DIR"
    "$PROJECT_DIR/.venv/bin/python" -c "
from src.db.session import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('SELECT 1'))
    print('DB 연결: 정상')
" 2>&1 || echo "DB 연결: 실패"
    echo ""

    # 1-7. 헬스체크 응답
    echo "=== 헬스체크 응답 ==="
    curl -s --connect-timeout 3 --max-time 5 "http://localhost:18923/health" 2>/dev/null || echo "(헬스체크 응답 없음)"
    echo ""

    # 1-8. 최근 git 변경 (자동 구현으로 인한 문제인지 확인)
    echo "=== 최근 Git 커밋 (5건) ==="
    cd "$PROJECT_DIR"
    git log --oneline -5 2>/dev/null || echo "(git 정보 없음)"
    echo ""

    echo "=== END OF DIAGNOSTIC CONTEXT ==="
} > "$CONTEXT_FILE" 2>&1

log "컨텍스트 수집 완료: $CONTEXT_FILE"

# ── 2단계: Claude Code 진단 세션 ──
log "Claude Code 진단 세션 시작..."

# 프롬프트에 컨텍스트를 결합
FULL_PROMPT="$(cat "$PROMPT_FILE")

--- DIAGNOSTIC CONTEXT ---
$(cat "$CONTEXT_FILE")
--- END DIAGNOSTIC CONTEXT ---"

cd "$PROJECT_DIR"
if /Users/songhansu/.local/bin/claude -p "$FULL_PROMPT" \
    --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
    >> "$HEAL_LOG" 2>&1; then
    log "Claude Code 진단 세션 완료"
else
    log "Claude Code 진단 세션 실패 (exit code: $?)"
    notify_telegram "자동 진단 세션이 비정상 종료되었습니다. 수동 확인이 필요합니다. 로그: $HEAL_LOG"
    exit 1
fi

# ── 3단계: 결과 확인 및 서비스 재시작 ──
if grep -q "HEAL_SUCCESS" "$HEAL_LOG" 2>/dev/null; then
    log "진단/수정 성공 — 서비스 재시작 시도"
    launchctl stop "$SERVICE_NAME" 2>/dev/null || true
    sleep 5
    launchctl start "$SERVICE_NAME" 2>/dev/null || true
    sleep 10

    if launchctl list 2>/dev/null | grep -q "$SERVICE_NAME"; then
        log "서비스 재시작 성공"
        notify_telegram "자동 진단/수정 완료. 서비스가 정상 재시작되었습니다."
    else
        log "ERROR: 수정 후 서비스 재시작 실패"
        notify_telegram "코드 수정은 완료되었으나 서비스 재시작에 실패했습니다. 수동 확인 필요."
    fi
elif grep -q "HEAL_FAILED" "$HEAL_LOG" 2>/dev/null; then
    log "자동 수정 실패 — 수동 개입 필요"
    notify_telegram "자동 진단 결과 자동 수정이 불가능합니다. 수동 확인이 필요합니다. 로그: $HEAL_LOG"
else
    log "진단 결과 판별 불가 — 수동 확인 필요"
    notify_telegram "자동 진단 결과를 판별할 수 없습니다. 로그를 확인해주세요: $HEAL_LOG"
fi

log "Auto-Heal 종료"
