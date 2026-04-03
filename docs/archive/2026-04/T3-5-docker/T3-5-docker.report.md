# T3-5: Docker 컨테이너화 — PDCA 완료 보고서

> 작성일: 2026-04-03 | PDCA 결과: **PASS (Match Rate 98%)**

## 개요

| 항목 | 내용 |
|------|------|
| 기능 | docker-compose로 앱+DB+대시보드 3서비스 컨테이너화 |
| 목적 | Mac Mini 홈서버 24시간 안정 운영, `docker compose up -d` 한 줄 기동 |
| Match Rate | **98%** |

## 생성 파일

| 파일 | 핵심 |
|------|------|
| `Dockerfile` | multi-stage, python:3.12-slim, 마이그레이션 자동 실행 |
| `Dockerfile.dashboard` | Streamlit headless, HEALTHCHECK |
| `docker-compose.yml` | 3서비스, pgdata 볼륨, 로그 로테이션, 포트 변수화 |
| `.dockerignore` | 21개 제외 규칙 |
| `scripts/docker-entrypoint.sh` | alembic upgrade head → exec python main.py |

## 운영

```bash
docker compose up -d          # 전체 시작
docker compose logs -f app    # 로그 확인
docker compose restart app    # 앱 재시작
docker compose down           # 전체 중지
```

## PDCA 완료

```
[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ (98%) → [Report] ✅
```
