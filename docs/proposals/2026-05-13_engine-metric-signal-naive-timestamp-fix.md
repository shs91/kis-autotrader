# engine.py의 메트릭·시그널 큐 적재 시 naive timestamp 차단 버그 수정

## 메타데이터
- 작성: Cowork (사용자 지시 기반, 2026-05-13 일일 리포트 핫픽스)
- 일자: 2026-05-13
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/engine.py
- 적용버전: v0.2.4

## 현상 분석

### 관측 사실 (2026-05-13 일일 리포트 기반)
- `system_metrics` 기록이 **2026-05-12 15:20:17 UTC (= 2026-05-13 00:20:17 KST) 이후 완전 단절**.
- `trades`(09:32 BUY, 14:31 SELL)와 `screening_results`(09:03~15:27 KST 분포)는 정상 기록 → 엔진/스크리너는 작동 중이나 메트릭 큐 경로만 차단.
- 같은 일자 `signals` 테이블도 **0건** — 매매 사유는 `ENSEMBLE`인데 시그널 row가 없음. 동일 원인으로 추정.

### 원인 (일일 리포트의 진단 정정)

리포트는 `src/db/repository.py:884`의 `datetime.utcnow()`를 원인으로 지목했으나, 해당 라인은 **c44dade(2026-05-13 08:22 UTC) 커밋에서 이미 `datetime.now(UTC)`로 정리됨**. 실제 차단 지점은 **상류의 큐 적재부**:

| 파일 | 라인 | 코드 | 영향 컬럼 | 컬럼 타입 |
|------|------|------|-----------|-----------|
| `src/engine.py` | 1079 | `"detected_at": datetime.now().isoformat()` | `Signal.detected_at` | `DateTime(timezone=True)` |
| `src/engine.py` | 1102 | `"recorded_at": datetime.now().isoformat()` | `SystemMetric.recorded_at` | `DateTime(timezone=True)` |

흐름:
1. 엔진이 `datetime.now()` (naive, **로컬타임** = KST) → `.isoformat()` (tzinfo 없는 ISO 문자열) → 큐 페이로드에 적재.
2. `src/worker/handlers.py:252, 281`에서 `datetime.fromisoformat(...)` → **naive** datetime 복원.
3. `SignalRepository.record_signal()` / `SystemMetricRepository.record_metric()`이 그 값을 `Signal.detected_at` / `SystemMetric.recorded_at`에 명시적으로 set.
4. `src/db/session.py:25`의 `validate_timezone_aware` `before_flush` 리스너가 TIMESTAMPTZ 컬럼에 set된 naive datetime을 감지 → `ValueError("Naive datetime in TIMESTAMPTZ column ...")` 발생.
5. 세션 컨텍스트가 rollback + `DatabaseError`로 변환 → 메트릭/시그널 한 건도 영속화되지 않음.

### 왜 어제(2026-05-12)부터인가
- `before_flush` 리스너는 **fb7b548 (2026-05-12)** 에서 도입.
- 리스너가 들어오기 전에는 naive timestamp가 PostgreSQL이 알아서 UTC로 해석해 저장되었기 때문에 표면화되지 않음.
- 리스너 도입 → 같은 날 `repository.py:884` 만 핫픽스로 `datetime.now(UTC)`로 변경(fb7b548)했고, 그 외 큐 경로(`engine.py:1079, 1102`)는 누락됨.
- c44dade(오늘 08:22 UTC)에서 `repository.py`의 `utcnow()` 7곳을 일괄 정리했지만, **`engine.py`는 손대지 않아** 동일 증상 지속.

### 영향
- `system_metrics` CYCLE_START/CYCLE_END/API_LIMIT/ERROR/SIGNAL_SUMMARY/EVAL_TARGETS/EVAL_SKIP 등 **모든 메트릭 누락 (~16시간+)**.
- `signals` 테이블 누락 → 시그널 정확도/전환율 분석(룰 A, 주간 리포트의 `signal_performance`) 데이터 손실.
- 자동 파이프라인 안전 게이트 룰 C(에러 카운트 기반)·룰 D(사이클 가용성 기반) 판정이 **항상 통과** → 안전 게이트 우회 위험.
- 사용자/Cowork의 일일·주간 분석이 잘못된 시스템 안정성 신호를 받음.

### 부수 효과: 로컬타임 vs UTC 의미 불일치
`datetime.now()` (naive)는 **로컬타임**(KST)을 반환한다. 만약 리스너가 없었다면 KST 시각을 UTC 컬럼에 그대로 넣어 9시간 미래 기록이 됐을 것. 리스너가 ValueError로 막은 덕에 잘못된 시각 저장은 회피되었으나, 단지 "에러로 끝나기 때문에" 데이터 무결성이 지켜졌을 뿐. 본 수정으로 의미·타임존 모두 정합화된다.

## 제안 내용

`src/engine.py`의 큐 적재 시점에 naive `datetime.now()` 대신 **aware `datetime.now(UTC)`** 를 사용한다. `UTC`는 이미 파일 상단(L6)에서 import 되어 있어 추가 import 불필요.

### 패턴 선택 근거
- 동일 파일 L969(`traded_at`)·L999(`screened_at`)가 이미 `datetime.now(UTC)` 사용 — 본 수정으로 파일 내 **TIMESTAMPTZ 컬럼 입력은 모두 aware UTC** 로 통일.
- worker handler 측 변경은 불필요: `datetime.fromisoformat`은 ISO 문자열의 tz 정보를 그대로 보존하므로, 적재 측만 aware로 만들면 자동으로 aware로 복원됨.

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:
  - **L1079** (`_record_signal_to_db` 내부, `task_type="record_signal"` 페이로드):
    - 변경 전: `"detected_at": datetime.now().isoformat(),`
    - 변경 후: `"detected_at": datetime.now(UTC).isoformat(),`
  - **L1102** (`_record_metric` 내부, `task_type="record_metric"` 페이로드):
    - 변경 전: `"recorded_at": datetime.now().isoformat(),`
    - 변경 후: `"recorded_at": datetime.now(UTC).isoformat(),`

> 그 외 라인 변경 없음. L217의 `datetime.now().timestamp()`는 산술용 unix timestamp라 그대로 둠.

### 추가 테스트 (`tests/test_engine_db_integration.py`)

기존 `TestRecordMetric` 클래스에 회귀 테스트 1건 추가, 새 `TestRecordSignal` 클래스 1개 추가:

```python
class TestRecordMetric:
    # ... 기존 테스트 유지 ...

    def test_metric_payload_recorded_at_is_timezone_aware(self) -> None:
        """L1102 회귀: recorded_at이 timezone-aware ISO 문자열인지 검증.

        naive datetime이 적재되면 `validate_timezone_aware` 리스너에 의해
        flush 시점에 ValueError가 발생해 메트릭이 영속화되지 않는다.
        """
        engine = _make_engine()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_metric("CYCLE_START", {"cycle": 1})

            payload = mock_enqueue.call_args.kwargs["payload"]
            recorded_at = datetime.fromisoformat(payload["recorded_at"])
            assert recorded_at.tzinfo is not None, (
                "recorded_at must be timezone-aware to pass "
                "validate_timezone_aware listener on TIMESTAMPTZ column"
            )


class TestRecordSignalToDb:
    """_record_signal_to_db의 큐 페이로드 검증."""

    def test_signal_payload_detected_at_is_timezone_aware(self) -> None:
        """L1079 회귀: detected_at이 timezone-aware ISO 문자열인지 검증."""
        engine = _make_engine()

        signal = MagicMock()
        signal.reason = "앙상블 매수 신호"
        signal.confidence = 0.42
        signal.target_price = None

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_signal_to_db(
                stock_code="005930",
                stock_name="삼성전자",
                signal=signal,
                action_taken=True,
                skip_reason=None,
            )

            calls = [
                c for c in mock_enqueue.call_args_list
                if c.kwargs.get("task_type") == "record_signal"
            ]
            assert len(calls) == 1
            payload = calls[0].kwargs["payload"]
            detected_at = datetime.fromisoformat(payload["detected_at"])
            assert detected_at.tzinfo is not None
```

> 시그널 테스트의 `_record_signal_to_db` 호출 시그니처는 `src/engine.py:1028` 정의 기준. 실제 파라미터 이름이 다르면 호출부에 맞춰 조정.
> `datetime`은 파일 상단에 이미 import 되어 있어야 하며, 없으면 `from datetime import datetime` 추가.

### 검증 명령
```bash
# 1. 회귀 테스트
pytest tests/test_engine_db_integration.py -v -k "timezone_aware"

# 2. 전체 테스트
pytest tests/ -q

# 3. 타입체크/린트
python -m mypy src/
ruff check src/
```

### 운영 검증 (구현 후 launchd 재시작 직후)
```bash
# 메트릭이 다시 쌓이는지 확인 (재시작 후 1~2분 내 CYCLE_START 1건 이상 기대)
psql "$DATABASE_URL" -c "SELECT metric_type, recorded_at FROM system_metrics ORDER BY recorded_at DESC LIMIT 5;"

# 시그널이 다시 쌓이는지 확인
psql "$DATABASE_URL" -c "SELECT signal_type, detected_at, confidence FROM signals ORDER BY detected_at DESC LIMIT 5;"
```

## 기대 효과

- **즉시**: `system_metrics`·`signals` 영속화 복구. 16+ 시간 단절 종료.
- **자동 파이프라인 안전 게이트 복원**: 룰 C(에러 카운트)·룰 D(사이클 가용성) 트리거가 실제 시스템 상태를 반영하게 됨.
- **일일/주간 리포트 신뢰성 회복**: 사이클 실행/완료, API 한도 도달, 시그널 정확도, signal_performance 분석이 다시 데이터 기반으로 가능.
- **의미 정합성**: `Signal.detected_at`·`SystemMetric.recorded_at`이 UTC aware 시각으로 저장되어 다른 TIMESTAMPTZ 컬럼(`trades.traded_at`, `screening_results.screened_at`)과 동일 규약.
- **회귀 방지**: 추가된 2건의 단위 테스트로 동일 류 버그(naive datetime을 큐 페이로드에 넣는 패턴) 재발 시 CI에서 즉시 포착.

## 롤백

- `git revert <commit>` — 2개 라인 변경이라 영향 범위 최소.
- 데이터 마이그레이션 없음 — 기존 누락 기간(2026-05-12 15:20 UTC ~ 본 수정 적용 시점)의 메트릭/시그널은 **복구 불가**(원천 데이터가 없음). 자동 파이프라인은 누락 구간을 인지하고 해당 기간의 룰 판정을 보류해야 함.
- 롤백 시 다시 메트릭/시그널 단절 상태로 복귀 → 운영상 비권장.

## 후속 작업 (본 제안서 범위 외)

1. **누락 구간 명시**: `docs/reports/2026-05-13_daily.md`에 시스템 메트릭 단절 구간(2026-05-12 15:20 UTC ~ 본 수정 적용 시각)을 명시. 주간 리포트에서 이 구간의 룰 평가를 제외하도록 분석 측이 인지.
2. **`datetime.now()` 사용처 일제 점검**: `grep -n "datetime\.now()" src/` 결과 중 DB·큐 페이로드 적재에 쓰이는 곳이 더 있는지 감사. 산술용은 무관, 영속화 경로면 같은 류 잠재 버그.
3. **린트 룰 검토**: ruff 커스텀 룰 또는 `DTZ` 룰셋(`flake8-datetimez`)으로 `datetime.now()` 무인자 호출을 차단하는 정책 검토.
