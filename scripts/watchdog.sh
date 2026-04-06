#!/bin/bash
# KIS 자동매매 — 프로세스/스케줄러 감시 + 자동 재시작
# crontab: 평일 5분마다 실행
#
# 감지 항목:
# 1. 프로세스 생존 여부
# 2. 헬스체크 API 기반 스케줄러 작동 확인 (cycle_count 변화)
# 3. 로그 파일 갱신 확인 (fallback)

set -euo pipefail

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
LOG_FILE="$PROJECT_DIR/logs/autotrader.out.log"
WATCHDOG_LOG="$PROJECT_DIR/logs/watchdog.log"
WATCHDOG_STATE="$PROJECT_DIR/logs/.watchdog_state"
SERVICE_NAME="com.kis.autotrader"
HEALTH_URL="http://localhost:8080/health"
STALE_THRESHOLD=300  # 초 (5분)

mkdir -p "$PROJECT_DIR/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$WATCHDOG_LOG"
}

notify_telegram() {
    "$PROJECT_DIR/.venv/bin/python" -c "
import asyncio
from src.notify.telegram import TelegramNotifier
asyncio.run(TelegramNotifier().notify_error('Watchdog', '$1'))
" 2>/dev/null || true
}

restart_service() {
    local reason="$1"
    log "재시작 실행: $reason"
    notify_telegram "$reason. 재시작 실행합니다."

    launchctl stop "$SERVICE_NAME"
    sleep 5
    launchctl start "$SERVICE_NAME"
    sleep 10

    if launchctl list | grep -q "$SERVICE_NAME"; then
        log "재시작 성공"
        # 상태 파일 초기화 (재시작 후 첫 사이클 대기)
        rm -f "$WATCHDOG_STATE"
    else
        log "ERROR: 재시작 실패"
    fi
}

# 장중 시간 체크 (09:05~15:25)
HOUR=$(date +%H)
MINUTE=$(date +%M)
CURRENT_MIN=$((HOUR * 60 + MINUTE))
MARKET_OPEN=$((9 * 60 + 5))   # 09:05 (장 시작 후 5분 여유)
MARKET_CLOSE=$((15 * 60 + 20)) # 15:20

if [ "$CURRENT_MIN" -lt "$MARKET_OPEN" ] || [ "$CURRENT_MIN" -gt "$MARKET_CLOSE" ]; then
    # 장외 시간 — 상태 파일 초기화 후 종료
    rm -f "$WATCHDOG_STATE"
    exit 0
fi

# ── 검사 1: 프로세스 실행 여부 ──
if ! launchctl list | grep -q "$SERVICE_NAME"; then
    log "WARNING: 서비스가 실행 중이 아닙니다. 시작 시도."
    launchctl start "$SERVICE_NAME"
    sleep 10
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log "서비스 시작 성공"
        notify_telegram "서비스가 중지되어 있어 재시작했습니다"
    else
        log "ERROR: 서비스 시작 실패"
    fi
    exit 0
fi

# ── 검사 2: 헬스체크 기반 스케줄러 작동 확인 ──
HEALTH_JSON=$(curl -s --connect-timeout 3 --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "")

if [ -n "$HEALTH_JSON" ]; then
    # cycle_count 추출
    CYCLE_COUNT=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['components']['trading']['cycle_count'])" 2>/dev/null || echo "-1")

    if [ "$CYCLE_COUNT" = "-1" ]; then
        log "WARNING: 헬스체크 응답 파싱 실패, fallback으로 진행"
    elif [ "$CYCLE_COUNT" = "0" ]; then
        # cycle_count가 0 — 장중인데 매매 사이클이 한 번도 실행되지 않음
        log "스케줄러 미작동 감지: cycle_count=0 (장중 시간)"
        restart_service "장중 매매 사이클 미실행 감지 (cycle_count=0)"
        exit 0
    else
        # cycle_count > 0: 이전 값과 비교하여 진행 중인지 확인
        PREV_CYCLE=0
        if [ -f "$WATCHDOG_STATE" ]; then
            PREV_CYCLE=$(cat "$WATCHDOG_STATE" 2>/dev/null || echo "0")
        fi

        if [ "$PREV_CYCLE" != "0" ] && [ "$CYCLE_COUNT" = "$PREV_CYCLE" ]; then
            # 5분 동안 cycle_count가 변하지 않음 → hang
            log "스케줄러 hang 감지: cycle_count=${CYCLE_COUNT} (5분간 변화 없음)"
            restart_service "매매 사이클 정지 감지 (cycle_count=${CYCLE_COUNT}, 5분간 변화 없음)"
            exit 0
        fi

        # 현재 cycle_count 저장
        echo "$CYCLE_COUNT" > "$WATCHDOG_STATE"
        # 정상 — 조용히 종료
        exit 0
    fi
fi

# ── 검사 3: 로그 파일 갱신 확인 (fallback) ──
# 헬스체크 API가 응답하지 않을 때만 실행
if [ ! -f "$LOG_FILE" ]; then
    log "WARNING: 로그 파일이 없습니다: $LOG_FILE"
    exit 0
fi

if [[ "$(uname)" == "Darwin" ]]; then
    LAST_MODIFIED=$(stat -f %m "$LOG_FILE")
else
    LAST_MODIFIED=$(stat -c %Y "$LOG_FILE")
fi
NOW=$(date +%s)
ELAPSED=$((NOW - LAST_MODIFIED))

if [ "$ELAPSED" -gt "$STALE_THRESHOLD" ]; then
    log "HANG 감지 (fallback): 로그 ${ELAPSED}초 동안 미갱신"
    restart_service "프로세스 hang 감지 (로그 ${ELAPSED}초 무응답)"
fi
