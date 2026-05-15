---
name: alembic-migration-flow
description: SQLAlchemy 모델 변경 → Alembic 자동 생성 → 검토 → 적용 워크플로. 기존 enum 재사용·UNIQUE·index 패턴.
---

# Alembic Migration Flow

## 절차

### 1. 모델 수정
- `src/db/models.py`에 새 컬럼/테이블/enum 추가
- `from __future__ import annotations` 첫 줄 유지

### 2. 자동 생성
```bash
PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "설명"
```
- 출력: `alembic/versions/<hash>_설명.py`

### 3. 검토 (필수)
생성된 파일을 반드시 확인:
- **enum 재사용**: 이미 존재하는 enum(예: `impl_category_enum`)을 재생성하지 말 것. `sa.Enum(..., create_type=False)` 또는 `postgresql.ENUM(..., create_type=False)` 적용
- **task_queue 등 무관 인덱스**: autogenerate가 잡아낸 무관한 변경은 제거
- **UNIQUE 제약**: 이름 명시 (`sa.UniqueConstraint('path', name='uq_proposals_path')`)
- **인덱스**: `op.create_index('ix_<table>_<col>', ...)` 형식
- **downgrade**: drop_table + 신규 enum drop. **기존 enum drop 금지**

### 4. 적용
```bash
PYTHONPATH=. .venv/bin/alembic upgrade head
psql "$DATABASE_URL" -c "\d <table>"  # 스키마 검증
```

### 5. 롤백 검증 (권장)
```bash
PYTHONPATH=. .venv/bin/alembic downgrade -1
PYTHONPATH=. .venv/bin/alembic upgrade head
```

## 금지
- 마이그레이션 파일 수기 작성 (autogenerate 거치지 않음)
- 운영 DB에 직접 DDL (DROP TABLE 등)
- 적용 후 마이그레이션 파일 수정 (새 revision 추가로 보완)
