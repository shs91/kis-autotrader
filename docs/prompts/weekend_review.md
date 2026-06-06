# 주말 리뷰 프롬프트 (Cowork 통합 진입점)

> 매주 토요일 Cowork 스케줄로 실행된다.
> 주간 리뷰는 항상 수행하고, 마지막주 토요일이면 월간 리뷰도 추가 수행한다.

## 분석 대상 (실전)

이 리뷰는 **실전 운영 DB `kis_trader_real`** 을 대상으로 한다 (2026-06-01 실전 전면 전환). 모의 `kis_trader`는 분석 대상이 아니다. 자세한 규칙·DB 검증 가드는 `docs/prompts/_common_rules.md`의 "분석 대상 DB" 섹션을 따른다.

## 실행 흐름

### Step 0: 공통 규칙 + DB 검증 가드

`docs/prompts/_common_rules.md`를 읽고, "DB 검증 가드"에 따라 `SELECT current_database();`를 실행한다.
결과가 `kis_trader_real`이 아니면 **즉시 중단**하고 가드 메시지를 출력한다 (모의 DB로 리뷰를 진행하지 말 것).

### Step 1: 마지막주 토요일 판별

아래 쿼리로 오늘이 이번 달 마지막 토요일인지 확인한다.

```sql
SELECT
  (now() AT TIME ZONE 'Asia/Seoul')::date AS today,
  (
    (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day')::date
    - ((EXTRACT(DOW FROM (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day'))::int + 1) % 7)
  ) AS last_saturday,
  (now() AT TIME ZONE 'Asia/Seoul')::date = (
    (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day')::date
    - ((EXTRACT(DOW FROM (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day'))::int + 1) % 7)
  ) AS is_last_saturday;
```

### Step 2: 주간 리뷰 (매주 수행)

`docs/prompts/weekly_review.md`를 읽고 그 지시사항을 수행한다.

### Step 3: 월간 리뷰 (마지막주만)

`is_last_saturday = true`인 경우에만:
`docs/prompts/monthly_review.md`를 읽고 그 지시사항을 수행한다.

`is_last_saturday = false`이면 이 단계를 건너뛴다.
