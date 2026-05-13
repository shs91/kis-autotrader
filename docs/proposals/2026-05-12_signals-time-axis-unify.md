# 분석 프롬프트의 signals 시간축을 detected_at으로 통일

## 메타데이터
- 작성: Claude Code (timestamp 검증 후속)
- 일자: 2026-05-12
- 상태: implemented
- 우선순위: low
- 카테고리: docs
- 관련파일: docs/prompts/_common_rules.md, docs/prompts/daily_routine.md, docs/prompts/weekly_routine.md

## 현상 분석

`signals` 테이블에는 시각 컬럼이 두 개 존재한다 (`src/db/models.py:270-289`):

- `detected_at` (nullable=False): 시그널이 발생한 시각 — write 경로에서 명시 set
- `created_at` (default=`datetime.utcnow`): DB row가 INSERT된 시각

분석 프롬프트의 시간 필터에서 두 컬럼이 혼용되어 있다:

| 파일·위치 | 사용 컬럼 | 의도 |
|----------|----------|------|
| `daily_routine.md:87,178` | `created_at` | 오늘/최근 7일 시그널 집계 |
| `daily_analysis.md:92,219,229` (레거시) | `created_at` | 동일 |
| `weekly_routine.md:65` | `created_at` | 이번 주 시그널 집계 |
| `weekly_analysis.md:69,232,244` (레거시) | `created_at` | 동일 |
| `monthly_analysis.md:138` (레거시) | `created_at` | 월간 시그널 집계 |
| `monthly_review.md:57,63` | `detected_at` | trades JOIN 윈도우 |
| `monthly_analysis.md:313,319` (레거시) | `detected_at` | trades JOIN 윈도우 |

### 정합성 문제

- **의미 다름**: `detected_at`은 비즈니스 이벤트 시점, `created_at`은 DB 메타데이터.
- **트랜잭션 지연 시 일자 경계가 어긋남**: 시그널이 KST 23:59:58에 detect되어 트랜잭션이 다음날 00:00:01에 commit되면, `created_at` 기준으로는 다음날 데이터로 분류됨. 매매시간 09:00~15:30 안에서는 이 차이가 거의 없지만, 향후 매매시간 확장이나 시간외 분석 시 어긋남 가능성.
- **`_common_rules.md`에 가이드 없음**: 6줄에서 두 컬럼 모두 timestamptz라고만 명시하고, 어느 쪽을 분석에 쓸지 정책이 부재 — 후속 프롬프트 작성 시 혼용이 재발할 가능성.

### 영향

- 현 데이터 분포에서는 표시 결과 차이 거의 없음 (KST 09:00~15:30 안의 매매·시그널은 같은 일자로 분류됨)
- 그러나 위 정합성 문제로 차후 분석 신뢰도 저하 가능
- 분석 의미축의 일관성 확보 = "왜 이 컬럼을 쓰는가"에 대한 일관된 답 가능

## 제안 내용

1. **`_common_rules.md`에 정책 추가** — 시간축 선택 가이드를 명문화.
2. **활성 Code 루틴 2개의 `signals.created_at` 필터를 `signals.detected_at`으로 일괄 변경.**
3. **레거시 `*_analysis.md` 3개는 손대지 않음** — `docs/prompts/README.md:21-23,154-158`에서 "참조용 보존, 향후 안정화되면 삭제 가능"으로 명시.

## 변경 스펙

### 파일별 변경사항

- `docs/prompts/_common_rules.md`:
  - "타임존 규칙" 섹션 하단(현 9줄 다음)에 한 줄 추가:
    ```markdown
    - `signals` 시간 필터는 항상 `detected_at`을 사용한다 (`created_at`은 DB 메타데이터). `trades` JOIN 윈도우에서도 `detected_at` 기준으로 조인한다.
    ```

- `docs/prompts/daily_routine.md`:
  - 쿼리 4 `signal_performance` (L80~90): `WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date = ...` → `WHERE (detected_at AT TIME ZONE 'Asia/Seoul')::date = ...`
  - 쿼리 10 `rolling_7d_signals` (L171~180): `WHERE created_at >= ...` → `WHERE detected_at >= ...`

- `docs/prompts/weekly_routine.md`:
  - 쿼리 3 `signal_performance` (L57~68): `WHERE created_at >= ...` → `WHERE detected_at >= ...`

총 변경: 3 파일, 4개 SQL 라인.

### 추가 테스트

해당 없음 (문서 변경, pytest 영향 없음).

## 기대 효과

- 분석 시간축 일관성 — 모든 시그널 시간 필터가 비즈니스 이벤트 시점(`detected_at`) 기준
- `_common_rules.md`의 정책 명문화로 후속 프롬프트 작성·확장 시 혼용 재발 방지
- 일자 경계 근처 트랜잭션 지연으로 인한 미세한 일자 누수 차단
- 분석 결과 수치는 현 데이터에서 미세 변동(±1~2건 수준) 예상되나 의미적 정확성 확보

## 롤백

- `git revert <commit>` — 모든 변경 원복
- 데이터 영향 없음 (read-only 쿼리 변경)

## 변경 파일 수

3 파일 — BRIDGE_SPEC 5개 한도 내.

## 카테고리 / 버저닝

`docs` 카테고리 — BRIDGE_SPEC 자동 버저닝 규칙상 버전 bump 없음. `record_implementation.py --no-bump`로 기록만 수행.
