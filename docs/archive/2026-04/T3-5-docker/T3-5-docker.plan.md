# T3-5: Docker 컨테이너화

> 작성일: 2026-04-03
> 상태: Plan
> 로드맵 ID: T3-5
> 의존성: 모든 기능 안정화 후 (T1~T3 완료)

---

## 1. 목적

Mac Mini 홈서버에서 24시간 안정적으로 운영하기 위해 전체 시스템을 Docker로 컨테이너화한다.

### 현재 운영 방식의 문제
- Python 환경, PostgreSQL, Streamlit 대시보드를 각각 수동 관리
- 시스템 재시작 시 3개 프로세스를 각각 기동해야 함
- 환경 의존성(Python 버전, pip 패키지)이 호스트에 직접 설치됨
- 다른 머신으로 이전 시 환경 재구성 필요

### Docker화 후 기대 효과
- `docker compose up -d` 한 줄로 전체 시스템 기동
- PostgreSQL + 앱 + 대시보드가 격리된 환경에서 실행
- 호스트 OS 업데이트와 무관하게 앱 동작 보장
- 백업/복원이 볼륨 단위로 단순화

---

## 2. 핵심 요구사항

### 2.1 필수 (Must Have)

| ID | 요구사항 | 설명 |
|----|----------|------|
| R1 | Dockerfile | Python 3.12 기반, 프로덕션 최적화 (multi-stage) |
| R2 | docker-compose.yml | 앱 + PostgreSQL + 대시보드 3개 서비스 |
| R3 | 환경변수 관리 | `.env` 파일 마운트, 시크릿 분리 |
| R4 | 데이터 영속성 | PostgreSQL 데이터 볼륨, 로그 볼륨, 백업 볼륨 |
| R5 | 자동 재시작 | `restart: unless-stopped` 정책 |
| R6 | 헬스체크 | Docker 내장 HEALTHCHECK + 기존 /health 엔드포인트 |
| R7 | .dockerignore | 불필요 파일 제외 |

### 2.2 선택 (Nice to Have)

| ID | 요구사항 | 설명 |
|----|----------|------|
| N1 | DB 백업 자동화 | 컨테이너 내 cron으로 pg_dump 실행 |
| N2 | 로그 로테이션 | Docker 로그 드라이버 설정 |
| N3 | Watchtower | 이미지 자동 업데이트 |

---

## 3. 아키텍처

### 3.1 서비스 구성

```
docker-compose.yml
├── app (kis-autotrader)      ← 매매 엔진 + 스케줄러 + 봇 + 헬스체크
├── db (PostgreSQL 16)        ← 데이터베이스
└── dashboard (Streamlit)     ← 웹 대시보드
```

### 3.2 네트워크

```
┌────────────────────────────────────────┐
│           kis-network (bridge)          │
│                                        │
│  ┌─────┐    ┌────┐    ┌───────────┐   │
│  │ app │───▶│ db │◀───│ dashboard │   │
│  └──┬──┘    └────┘    └─────┬─────┘   │
│     │                       │          │
└─────┼───────────────────────┼──────────┘
      │ :8080 (health)        │ :8501 (web)
      ▼                       ▼
   호스트                    호스트
```

### 3.3 볼륨

| 볼륨 | 마운트 | 용도 |
|------|--------|------|
| `pgdata` | `/var/lib/postgresql/data` | DB 데이터 영속성 |
| `./logs` | `/app/logs` | 앱 로그 파일 |
| `./backups` | `/app/backups` | DB 백업 파일 |
| `./.env` | `/app/.env` (읽기전용) | 환경변수 |
| `./credentials.json` | `/app/credentials.json` (읽기전용) | Google API 인증 |
| `./token.json` | `/app/token.json` | Google OAuth 토큰 |

---

## 4. 파일 구조

```
kis-autotrader/
├── Dockerfile              # 앱 이미지 (multi-stage)
├── Dockerfile.dashboard    # 대시보드 이미지
├── docker-compose.yml      # 서비스 오케스트레이션
├── .dockerignore           # 빌드 제외 파일
├── .env                    # 환경변수 (기존)
└── ...
```

---

## 5. Dockerfile 설계

### 5.1 앱 (multi-stage)

```
Stage 1: builder
  - python:3.12-slim
  - pip install (의존성만, 소스 제외)

Stage 2: runtime
  - python:3.12-slim
  - builder에서 site-packages 복사
  - 소스코드 복사
  - ENTRYPOINT ["python", "main.py"]
```

### 5.2 대시보드

```
  - python:3.12-slim
  - pip install streamlit + 의존성
  - dashboard/ 소스코드 복사
  - ENTRYPOINT ["streamlit", "run", "dashboard/app.py"]
```

---

## 6. docker-compose.yml 설계

```yaml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U $POSTGRES_USER
    ports:
      - "5432:5432"  # 개발 시만, 프로덕션에서는 제거 가능

  app:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    env_file: .env
    environment:
      DATABASE_URL: postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/$POSTGRES_DB
    volumes:
      - ./logs:/app/logs
      - ./backups:/app/backups
      - ./credentials.json:/app/credentials.json:ro
      - ./token.json:/app/token.json
    ports:
      - "8080:8080"  # 헬스체크
    healthcheck:
      test: curl -f http://localhost:8080/health || exit 1

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
      DATABASE_URL: postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/$POSTGRES_DB
    ports:
      - "8501:8501"  # Streamlit

volumes:
  pgdata:
```

---

## 7. 환경변수 전략

### Docker 전용 변경사항

| 변수 | 기존 (.env) | Docker 내부 |
|------|-------------|-------------|
| `DATABASE_URL` | `localhost:5432` | `db:5432` (서비스명) |
| `HEALTH_PORT` | `8080` | `8080` (동일) |

### 추가 필요 변수

```env
# Docker PostgreSQL
POSTGRES_DB=kis_trader
POSTGRES_USER=kis
POSTGRES_PASSWORD=your_password
```

`.env` 파일 하나로 앱 + Docker 모두 관리. `DATABASE_URL`만 docker-compose.yml에서 오버라이드.

---

## 8. 구현 순서

| 순서 | 파일 | 내용 |
|------|------|------|
| 1 | `.dockerignore` | 빌드 제외 목록 |
| 2 | `Dockerfile` | 앱 이미지 (multi-stage) |
| 3 | `Dockerfile.dashboard` | 대시보드 이미지 |
| 4 | `docker-compose.yml` | 서비스 오케스트레이션 |
| 5 | `.env` 업데이트 | POSTGRES_* 변수 추가 |
| 6 | `alembic.ini` 확인 | DATABASE_URL 환경변수 사용 확인 |
| 7 | 빌드/실행 테스트 | `docker compose build && docker compose up -d` |

---

## 9. 검증 기준

- [ ] `docker compose build` 에러 없이 완료
- [ ] `docker compose up -d` 3개 서비스 모두 healthy
- [ ] 앱 컨테이너에서 매매 엔진 정상 기동 (로그 확인)
- [ ] 대시보드 `http://localhost:8501` 접근 가능
- [ ] 헬스체크 `http://localhost:8080/health` 응답
- [ ] DB 데이터가 `pgdata` 볼륨에 영속 (컨테이너 재시작 후 데이터 유지)
- [ ] `docker compose down && docker compose up -d` 후 정상 복귀
- [ ] Telegram 봇 명령 (`/status`, `/watch`) 정상 동작

---

## 10. 리스크 및 제약사항

| 리스크 | 대응 |
|--------|------|
| Mac Mini ARM(Apple Silicon) 호환 | `python:3.12-slim`은 ARM 지원, `postgres:16-alpine`도 ARM 지원 |
| Google OAuth 토큰 갱신 | `token.json` 볼륨 마운트로 컨테이너 밖에서 유지 |
| 컨테이너 시간대 | `TZ=Asia/Seoul` 환경변수 설정 |
| DB 마이그레이션 | 앱 시작 시 `alembic upgrade head` 자동 실행 |
| 이미지 크기 | multi-stage 빌드로 최소화 (~300MB 목표) |

---

## 11. 운영 명령어 (완성 후)

```bash
# 전체 시작
docker compose up -d

# 로그 확인
docker compose logs -f app

# 앱만 재시작
docker compose restart app

# 전체 중지
docker compose down

# DB 백업
docker compose exec db pg_dump -U kis kis_trader > backups/$(date +%Y%m%d).sql

# 이미지 재빌드 (코드 변경 후)
docker compose build app && docker compose up -d app
```
