# T3-5: Docker 컨테이너화 — 상세 설계

> 작성일: 2026-04-03
> 상태: Design
> Plan 문서: `docs/01-plan/features/T3-5-docker.plan.md`

---

## 1. 파일 목록

### 신규 파일

| 파일 | 설명 |
|------|------|
| `Dockerfile` | 앱 이미지 (multi-stage) |
| `Dockerfile.dashboard` | 대시보드 이미지 |
| `docker-compose.yml` | 3개 서비스 오케스트레이션 |
| `.dockerignore` | 빌드 제외 |
| `scripts/docker-entrypoint.sh` | 앱 엔트리포인트 (마이그레이션 + 실행) |

### 수정 파일

| 파일 | 변경 |
|------|------|
| `.env.example` | POSTGRES_* 변수 추가 |

### 변경 없음

기존 소스코드(`src/`, `main.py`, `dashboard/`) 수정 없음.

---

## 2. `.dockerignore`

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.git/
.github/
docs/
tests/
scripts/docs/
*.md
!requirements*.txt
.env
.env.*
credentials.json
token.json
backups/
logs/
*.sql
```

---

## 3. `Dockerfile` (앱)

```dockerfile
# Stage 1: 의존성 설치
FROM python:3.12-slim AS builder

WORKDIR /build

# 시스템 의존성 (psycopg2-binary용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: 런타임
FROM python:3.12-slim

WORKDIR /app

# 런타임 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 복사
COPY --from=builder /install /usr/local

# 소스코드 복사
COPY src/ ./src/
COPY main.py ./
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/docker-entrypoint.sh ./docker-entrypoint.sh

# 엔트리포인트 실행 권한
RUN chmod +x docker-entrypoint.sh

# 시간대 설정
ENV TZ=Asia/Seoul
ENV PYTHONUNBUFFERED=1

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
```

### 설계 결정

- `python:3.12-slim`: ARM(Apple Silicon) 지원, Debian 기반 안정성
- `gcc libpq-dev`: builder에서만 사용 (psycopg2 빌드), 런타임에 미포함
- `libpq5 curl`: 런타임 최소 의존성 (DB 연결 + 헬스체크)
- `PYTHONUNBUFFERED=1`: 로그 즉시 출력 (Docker 로그에서 지연 방지)

---

## 4. `scripts/docker-entrypoint.sh`

```bash
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
```

### 설계 결정

- `set -e`: 마이그레이션 실패 시 컨테이너 즉시 종료 (재시작 정책으로 재시도)
- `exec`: PID 1에서 main.py 실행 → SIGTERM이 직접 전달됨

---

## 5. `Dockerfile.dashboard`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 대시보드 의존성
COPY pyproject.toml ./
RUN pip install --no-cache-dir . streamlit

# 소스코드 복사
COPY dashboard/ ./dashboard/
COPY src/ ./src/

ENV TZ=Asia/Seoul
ENV PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "dashboard/app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true"]
```

### 설계 결정

- single-stage: 대시보드는 빌드 단계가 단순
- `src/` 포함: 대시보드가 `src/db/`, `src/config.py` 등을 import
- `--server.headless=true`: 브라우저 자동 열기 비활성화
- `_stcore/health`: Streamlit 내장 헬스체크 엔드포인트

---

## 6. `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-kis_trader}
      POSTGRES_USER: ${POSTGRES_USER:-kis}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-kis}"]
      interval: 10s
      timeout: 5s
      retries: 5
    ports:
      - "${DB_PORT:-5432}:5432"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  app:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    env_file: .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-kis}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-kis_trader}
      TZ: Asia/Seoul
    volumes:
      - ./logs:/app/logs
      - ./backups:/app/backups
      - ./credentials.json:/app/credentials.json:ro
      - ./token.json:/app/token.json
      - ./holidays.json:/app/holidays.json:ro
    ports:
      - "${HEALTH_PORT:-8080}:8080"
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    env_file: .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-kis}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-kis_trader}
      TZ: Asia/Seoul
    ports:
      - "${DASHBOARD_PORT:-8501}:8501"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  pgdata:
```

### 설계 결정

| 항목 | 결정 | 이유 |
|------|------|------|
| `postgres:16-alpine` | Alpine 기반 | ARM 지원, 경량 (~80MB) |
| `service_healthy` | DB 준비 대기 | 앱 시작 전 DB 연결 보장 |
| `POSTGRES_PASSWORD:?` | 필수 변수 | 비밀번호 없이 시작 방지 |
| `json-file` 로그 | 기본 드라이버 | max-size/max-file로 로테이션 |
| `holidays.json` 마운트 | 읽기전용 | 공휴일 데이터 |
| 포트 변수화 | `${DB_PORT:-5432}` | 포트 충돌 시 변경 가능 |

---

## 7. `.env.example` 추가 변수

```env
# Docker PostgreSQL (docker-compose 전용)
POSTGRES_DB=kis_trader
POSTGRES_USER=kis
POSTGRES_PASSWORD=change_me_to_strong_password

# 포트 커스텀 (선택)
# DB_PORT=5432
# HEALTH_PORT=8080
# DASHBOARD_PORT=8501
```

---

## 8. 구현 순서

| 순서 | 파일 | 검증 |
|------|------|------|
| 1 | `.dockerignore` | - |
| 2 | `scripts/docker-entrypoint.sh` | `bash -n` 문법 검사 |
| 3 | `Dockerfile` | `docker build -t kis-app .` |
| 4 | `Dockerfile.dashboard` | `docker build -f Dockerfile.dashboard -t kis-dashboard .` |
| 5 | `docker-compose.yml` | `docker compose config` 유효성 |
| 6 | `.env.example` 업데이트 | - |
| 7 | 통합 테스트 | `docker compose up -d` → 3서비스 healthy |

---

## 9. 검증 체크리스트

### 빌드 검증
- [ ] `docker compose build` 에러 없음
- [ ] 앱 이미지 크기 < 400MB
- [ ] 대시보드 이미지 크기 < 400MB

### 기동 검증
- [ ] `docker compose up -d` → 3개 서비스 running
- [ ] `docker compose ps` — db, app, dashboard 모두 healthy
- [ ] `docker compose logs app` — "매매 시스템 시작" 로그 확인
- [ ] `docker compose logs app` — "Alembic 마이그레이션 완료" 확인

### 기능 검증
- [ ] `curl http://localhost:8080/health` — 200 응답
- [ ] `http://localhost:8501` — 대시보드 페이지 로드
- [ ] Telegram `/status` — 컨테이너 내부에서 봇 동작

### 영속성 검증
- [ ] `docker compose down && docker compose up -d` → DB 데이터 유지
- [ ] `docker volume ls` — pgdata 볼륨 존재

### 재시작 검증
- [ ] `docker compose restart app` → 앱 정상 복귀
- [ ] `docker kill kis-autotrader-app-1` → 자동 재시작 (unless-stopped)
