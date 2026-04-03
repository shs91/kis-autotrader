#!/bin/bash
set -e

echo "=== KIS AutoTrader Docker Entrypoint ==="

# DB 마이그레이션 자동 실행
echo "Alembic 마이그레이션 실행 중..."
python -m alembic upgrade head
echo "마이그레이션 완료."

# 메인 애플리케이션 실행
echo "매매 시스템 시작..."
exec python main.py
