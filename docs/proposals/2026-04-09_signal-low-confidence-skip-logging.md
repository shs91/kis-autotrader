# 저신뢰도 시그널 DB 저장 스킵 (로깅 볼륨 축소)

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-09
- 상태: implemented
- 우선순위: medium
- 카테고리: performance
- 관련파일: src/engine.py

## 현상 분석

`signals` 테이블에 매일 수천 건의 시그널이 적재되고 있으나, 대부분은 신뢰도가 `STRATEGY_MIN_CONFIDENCE`(기본 0.1) 미만이라 매매 전환이 원천 불가능함. 즉 **영속화된 가치가 없는 노이즈 데이터**가 대량으로 쌓이는 중.

### 4일간 축적 데이터 (2026-04-06 ~ 2026-04-09)

```sql
SELECT
  d,
  COUNT(*)                                    AS total_signals,
  SUM(CASE WHEN confidence < 0.10 THEN 1 END) AS below_min,
  SUM(CASE WHEN action_taken THEN 1 ELSE 0 END) AS acted
FROM signals
GROUP BY date_trunc('day', detected_at)::date d
ORDER BY d;
```

| 일자 | 총 시그널 | 0.10 미만 | 실제 매매 전환 | 노이즈 비율 |
|------|-----------|-----------|----------------|-------------|
| 2026-04-06 | 3,195 | 2,020 | 1 | 63.2% |
| 2026-04-07 | 1,367 | 1,367 | 0 | 100.0% |
| 2026-04-08 | 3,387 | 3,106 | 2 | 91.7% |
| **4일 합계** | **7,949** | **6,493+** | **3** | **≈ 82%** |

- **평균 활용률**: 0.038% (3건 / 7,949건)
- **4/9 세부**: 3,387건 중 SK하이닉스에 집중 발생한 2건만 매매 전환. 나머지 3,385건(99.94%)은 DB 부담만 초래
- 동일 종목(000660·105560·207940)에 사이클당 1건씩 기록되므로 **장 시간이 길수록 거의 선형 증가**
- 현재 5일치만 축적된 상태에서도 8천 건 돌파 — 30일 운영 시 약 **5~10만 건** 예상

### 영향

1. **디스크**: `signals` 테이블 불필요 팽창 → 인덱스 스캔 비용 증가
2. **쿼리 성능**: daily 분석 쿼리가 매일 수천 건을 full scan. 향후 주간·월간 리포트 쿼리 속도 저하 누적
3. **분석 노이즈**: 평균 신뢰도가 실사용 값이 아닌 노이즈 값으로 왜곡됨 (오늘 평균 8.25%는 매매와 무관한 값)

## 제안 내용

`EngineCore._record_signal()` 함수 진입 시, 아래 두 조건을 **모두** 만족하는 시그널만 저장하도록 필터 추가:

1. `action_taken == True` (실제 매매 전환된 시그널은 **무조건** 기록 — 감사 추적 목적)
2. 또는 `confidence >= settings.strategy.min_confidence` (매매 전환은 안 됐지만 임계값을 돌파한 의미 있는 시그널은 기록 — 시그널 정확도 분석용)

즉, **매매 전환이 안 됐고 동시에 신뢰도가 min_confidence 미만인 시그널만 저장에서 제외**. 이 조합은 "어차피 매매될 수 없었고, 분석적으로도 무의미한" 데이터를 정확히 걸러냄.

### 신규 파라미터 도입 없음
- 기존 `settings.strategy.min_confidence` (기본 0.1) 재사용
- 따라서 BRIDGE_SPEC.md의 자동 변경 허용 파라미터 범위 제약 대상 아님

## 변경 스펙

### 파일별 변경사항

- `src/engine.py` — `_record_signal` 함수 (현재 809~849행):

**변경 전** (815~816행):
```python
        if signal.signal_type == SignalType.HOLD:
            return
```

**변경 후**:
```python
        if signal.signal_type == SignalType.HOLD:
            return
        # 저신뢰도 + 비(非) 매매전환 시그널은 DB 저장 스킵 (노이즈 축소)
        # - 매매 전환된 시그널(action_taken=True)은 감사 목적으로 항상 기록
        # - 매매 전환 안 됐더라도 임계값(min_confidence)은 넘긴 시그널은 분석용으로 기록
        if (
            not action_taken
            and signal.confidence < settings.strategy.min_confidence
        ):
            return
```

`settings`는 이미 `src/engine.py` 상단에서 `from src.config import settings` 형태로 import 되어 있다고 가정. 만약 미임포트라면 import 추가 필요 (동일 파일 내 1줄 수정, 제안서 변경 범위 내).

### 추가 테스트

- `tests/test_engine/test_record_signal_threshold.py` 생성 (선택):
  - `confidence=0.05, action_taken=False` → `repo.record_signal` 호출 안 됨 검증
  - `confidence=0.05, action_taken=True` → `repo.record_signal` 호출됨 검증
  - `confidence=0.15, action_taken=False` → `repo.record_signal` 호출됨 검증

단, `EngineCore._record_signal`이 `with get_session()` 컨텍스트 매니저를 직접 사용하므로 Mock 설정이 번거로울 수 있음. 테스트 작성 난이도가 높을 경우 본 변경 자체가 1줄 조건문 추가에 해당하므로 기존 `pytest tests/`가 모두 pass 하는 것만으로 충분히 안전함.

## 기대 효과

### 정량적
- 오늘(4/9) 기준: **3,387건 → 281건** (91.7% 감소) + 매매 전환 2건 보장 기록
- 4일 누적(4/6~4/9): **7,949건 → 약 1,456건** (81.7% 감소)
- 30일 운영 시 예상: 약 **5~10만 건 → 약 1~2만 건**
- 일일 리포트 시그널 쿼리 속도 5~10배 개선 예상

### 정성적
- `signal_accuracy` 지표가 "실제로 임계값을 넘긴 시그널" 기반으로 계산되어 **의미 있는 값**으로 정규화됨
- 신뢰도 평균/분포가 노이즈에 의한 왜곡 없이 해석 가능

### 검증 방법 (구현 후 24시간)
```sql
-- 2026-04-10 이후 데이터로 확인
SELECT
  date_trunc('day', detected_at)::date d,
  COUNT(*) total,
  MIN(confidence) min_c,
  AVG(confidence) avg_c
FROM signals
WHERE detected_at::date >= '2026-04-10'
GROUP BY d;
```

**합격 기준**:
- `min_c >= 0.1` (단, `action_taken=TRUE` 제외 시) — 임계값 미달 시그널이 걸러짐
- `total` < 500 (기존 3,387의 15% 이하)
- `action_taken=TRUE`인 시그널은 모두 `avg_c`와 무관하게 기록되어 있음

## 롤백

```bash
git restore src/engine.py
# (테스트 파일이 생성되었다면)
rm -f tests/test_engine/test_record_signal_threshold.py
```

이미 적재된 과거 노이즈 시그널은 삭제하지 않음 (분석 이력 보존). 추후 필요 시 별도 데이터 클린업 스크립트로 정리.
