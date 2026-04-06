#!/bin/bash
# KIS 자동매매 — PostgreSQL 일일 백업 스크립트
# crontab: 매일 04:00 실행
# 7일 롤링 보관

set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

PROJECT_DIR="$HOME/IdeaProjects/kis-autotrader"
BACKUP_DIR="$PROJECT_DIR/backups"
CONTAINER_NAME="kis-postgres"
DB_NAMES=("kis_trader" "kis_trader_real")
DB_USER="kis_user"
RETENTION_DAYS=7

DATE=$(date +%Y-%m-%d)
LOG_FILE="$PROJECT_DIR/logs/backup.log"

mkdir -p "$BACKUP_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "=== DB 백업 시작 ==="

# Docker 컨테이너 상태 확인
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "ERROR: Docker 컨테이너 '${CONTAINER_NAME}'가 실행 중이 아닙니다"
    exit 1
fi

for DB_NAME in "${DB_NAMES[@]}"; do
    BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${DATE}.sql.gz"

    # DB 존재 여부 확인
    if ! docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -lqt | grep -qw "$DB_NAME"; then
        log "SKIP: DB '${DB_NAME}' 없음"
        continue
    fi

    # pg_dump 실행 (Docker exec → gzip 압축)
    if docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"; then
        FILE_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        log "백업 완료: $BACKUP_FILE ($FILE_SIZE)"
    else
        log "ERROR: pg_dump 실패 ($DB_NAME)"
        rm -f "$BACKUP_FILE"
        continue
    fi

    # 백업 파일 무결성 확인 (빈 파일 체크)
    if [ ! -s "$BACKUP_FILE" ]; then
        log "ERROR: 백업 파일이 비어있습니다 ($DB_NAME)"
        rm -f "$BACKUP_FILE"
        continue
    fi

    # 오래된 백업 삭제 (7일 초과)
    DELETED=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +${RETENTION_DAYS} -print -delete | wc -l | tr -d ' ')
    if [ "$DELETED" -gt 0 ]; then
        log "오래된 백업 ${DELETED}개 삭제: ${DB_NAME} (${RETENTION_DAYS}일 초과)"
    fi
done

TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "*.sql.gz" | wc -l | tr -d ' ')
log "현재 백업 파일: ${TOTAL_BACKUPS}개"
log "=== DB 백업 완료 ==="
