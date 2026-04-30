# 스크리닝 DB 조회 타임존 불일치 수정

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-30
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/db/repository.py

## 현상 분석

스크리닝→엔진 파이프라인이 7일 연속 단절(전환율 0.0%). 04-28 제안서에서 `converted_to_trade` 필터를 제거했으나 문제 지속.

**근본 원인**: `ScreeningResultRepository.get_by_date()` (repository.py:839-849)의 타임존 불일치.

```python
# 현재 코드
start = datetime.combine(target_date, datetime.min.time())  # naive: 2026-04-30 00:00:00
end = start + timedelta(days=1)                             # naive: 2026-05-01 00:00:00
```

`screened_at` 컬럼은 `timestamptz`이며, DB에 UTC 오프셋으로 저장된다.
naive datetime으로 비교 시 PostgreSQL은 이를 **UTC로 해석**한다.

실측 데이터:
- 04-30 KST 기준 스크리닝 데이터: `screened_at = 2026-04-29 15:00:49+00:00` (= 04-30 00:00 KST)
- naive 비교 (`>= '2026-04-30 00:00:00'`): **0건** 반환
- KST 비교 (`>= '2026-04-30 00:00:00+09'`): **3,000건** 반환

스크리닝 워커가 KST 장중(09:00~15:30)에 기록하므로, UTC 기준으로는 전일(04-29 00:00~15:00 UTC)에 해당.
`get_by_date(date(2026,4,30))`은 UTC 04-30 00:00 이후만 조회 → 항상 0건.

### 근거 데이터
- 쿼리 11: 7일 연속 전환율 0.0% (04-24 ~ 04-30)
- 쿼리 10: 7일간 시그널 0건
- EVAL_TARGETS: 금일 83사이클 전수 `screening: 0`
- 직접 검증: naive datetime 조회 0건 vs KST 조회 3,000건

## 제안 내용

`get_by_date` 메서드에서 KST 타임존을 명시적으로 적용하여, KST 날짜 기준으로 스크리닝 결과를 조회한다.

## 변경 스펙

### 파일별 변경사항

- `src/db/repository.py`: `ScreeningResultRepository.get_by_date()` (line 839-849)

변경 전:
```python
def get_by_date(self, target_date: date) -> list[ScreeningResult]:
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)
    stmt = (
        select(ScreeningResult)
        .where(
            ScreeningResult.screened_at >= start,
            ScreeningResult.screened_at < end,
        )
        .order_by(ScreeningResult.screening_rank)
    )
    return list(self._session.execute(stmt).scalars().all())
```

변경 후:
```python
def get_by_date(self, target_date: date) -> list[ScreeningResult]:
    from zoneinfo import ZoneInfo
    kst = ZoneInfo("Asia/Seoul")
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=kst)
    end = start + timedelta(days=1)
    stmt = (
        select(ScreeningResult)
        .where(
            ScreeningResult.screened_at >= start,
            ScreeningResult.screened_at < end,
        )
        .order_by(ScreeningResult.screening_rank)
    )
    return list(self._session.execute(stmt).scalars().all())
```

핵심: `datetime.combine`에 `tzinfo=kst`를 추가하여 timezone-aware datetime으로 비교. PostgreSQL이 KST 기준으로 필터링하게 된다.

### 추가 테스트 (필요 시)
- `tests/test_db/` 에 기존 `get_by_date` 테스트가 있으면, timezone-aware 비교를 검증하는 케이스 추가

## 기대 효과

- `get_by_date`가 KST 날짜 기준으로 올바르게 조회 → 스크리닝 결과 반영 복원
- `EVAL_TARGETS.screening > 0` → 스크리닝 종목 시그널 평가 활성화
- 7일간 교착 상태였던 매매 파이프라인 정상화

## 롤백

`src/db/repository.py`의 해당 변경을 `git restore`로 원복. 기존 동작(naive datetime)으로 복귀.
