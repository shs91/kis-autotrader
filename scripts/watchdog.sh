#!/bin/bash
# KIS 자동매매 — 프로세스 행(Hang) 감지 + 자동 재시작
# crontab: 평일 09:05~15:30 사이 5분마다 실행
#
# 판단 기준: 로그 파일이 일정 시간(기본 300초) 동안 업데이트되지 않으면 hang으로 간주
# 장중 시간(09:00~15:20)에만 동작 — 장외 시간에는 로그가 안 쌓이는 게 정상

set -euo pipefail

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
LOG_FILE="$PROJECT_DIR/logs/autotrader.out.log"
WATCHDOG_LOG="$PROJECT_DIR/logs/watchdog.log"
SERVICE_NAME="com.kis.autotrader"
STALE_THRESHOLD=300  # 초 (5분)

mkdir -p "$PROJECT_DIR/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$WATCHDOG_LOG"
}

# 장중 시간 체크 (09:00~15:25)
HOUR=$(date +%H)
MINUTE=$(date +%M)
CURRENT_MIN=$((HOUR * 60 + MINUTE))
MARKET_OPEN=$((9 * 60))       # 09:00
MARKET_CLOSE=$((15 * 60 + 25)) # 15:25

if [ "$CURRENT_MIN" -lt "$MARKET_OPEN" ] || [ "$CURRENT_MIN" -gt "$MARKET_CLOSE" ]; then
    # 장외 시간 — 체크하지 않음
    exit 0
fi

# 프로세스 실행 여부 확인
if ! launchctl list | grep -q "$SERVICE_NAME"; then
    log "WARNING: 서비스가 실행 중이 아닙니다. 시작 시도."
    launchctl start "$SERVICE_NAME"
    sleep 10
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log "서비스 시작 성공"
        # Telegram 알림 (Python 이용)
        "$PROJECT_DIR/.venv/bin/python" -c "
import asyncio
from src.notify.telegram import TelegramNotifier
asyncio.run(TelegramNotifier().notify_error('Watchdog', '서비스가 중지되어 있어 재시작했습니다'))
" 2>/dev/null || true
    else
        log "ERROR: 서비스 시작 실패"
    fi
    exit 0
fi

# 로그 파일 존재 확인
if [ ! -f "$LOG_FILE" ]; then
    log "WARNING: 로그 파일이 없습니다: $LOG_FILE"
    exit 0
fi

# 로그 파일 최종 수정 시각 확인
if [[ "$(uname)" == "Darwin" ]]; then
    LAST_MODIFIED=$(stat -f %m "$LOG_FILE")
else
    LAST_MODIFIED=$(stat -c %Y "$LOG_FILE")
fi
NOW=$(date +%s)
ELAPSED=$((NOW - LAST_MODIFIED))

if [ "$ELAPSED" -gt "$STALE_THRESHOLD" ]; then
    log "HANG 감지: 로그 ${ELAPSED}초 동안 미갱신 (임계값: ${STALE_THRESHOLD}초). 재시작 실행."

    # Telegram 알림
    "$PROJECT_DIR/.venv/bin/python" -c "
import asyncio
from src.notify.telegram import TelegramNotifier
asyncio.run(TelegramNotifier().notify_error('Watchdog', '프로세스 hang 감지 (${ELAPSED}초 무응답), 재시작 실행'))
" 2>/dev/null || true

    # 재시작
    launchctl stop "$SERVICE_NAME"
    sleep 5
    launchctl start "$SERVICE_NAME"
    sleep 10

    if launchctl list | grep -q "$SERVICE_NAME"; then
        log "재시작 성공"
    else
        log "ERROR: 재시작 실패"
    fi
else
    # 정상 — 로그 없이 조용히 종료 (5분마다 실행되므로 로그 노이즈 방지)
    :
fi
