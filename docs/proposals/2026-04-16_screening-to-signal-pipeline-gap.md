# 스크리닝 발굴 종목이 시그널 파이프라인에 유입되지 않는 경로 확인

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-16
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py, src/worker/screener.py, src/strategy/selector.py

## 현상 분석

### DB 근거 — 오늘(2026-04-16 KST)

- 스크리닝 발굴: **145 distinct 종목** (`screening_results`)
- 시그널 평가 대상: **6종** (블루칩 5 + 034020 1) — `signals` + `system_metrics.SIGNAL_SKIP`에서 stock_code 분포로 확인
- 발굴 145종 중 시그널 평가를 받은 종목: **0종**

스크리너는 하루 종일(00:06~23:57) 145개 종목을 지속적으로 발굴했지만, 그 중 어느 한 종목도 전략 평가(ENSEMBLE vote)의 입력이 되지 못했다. 평가 대상은 어제와 동일한 고정 블루칩 5종과 어제 매도된 두산에너빌리티 1종뿐이었다.

### 최근 7일 rolling 관찰

| 날짜 | 스크리닝 발굴 | 전환 | ENSEMBLE 시그널 건수 |
|------|----------------|------|-----------------------|
| 2026-04-14 | - | - | 1,503 |
| 2026-04-15 | 67 | 13 (19.4%) | 4,400 |
| 2026-04-16 | 145 | 0 (0.0%) | 398 |

전환율 19.4%(어제) → 0%(오늘) 급락. 시그널 건수도 4,400 → 398로 수직 하락. 스크리닝 발굴 수가 오히려 2배 이상 늘었음에도 매매 평가 대상이 줄어든 것은 **스크리닝 결과가 전략 평가 리스트에 주입되는 경로가 단절되었거나, 어제 일시적으로 작동하던 우회 경로가 오늘 복구 실패**한 것으로 추정된다.

### 배제 가능 원인

- 스크리너 자체는 정상(145 distinct, 모두 `converted_to_trade=false`로 기록).
- API/인프라 정상(에러 0, API 한도 도달 0, 사이클 완료율 100%).
- `ScreeningWorker`가 2026-04-15에 분리되어(Phase 3), 메인 엔진은 DB 결과를 읽도록 바뀜. 이 구간에서 "메인 엔진이 screening_results를 평가 대상 리스트에 반영" 로직이 제대로 붙어 있는지가 핵심.

## 제안 내용

본 제안은 두 단계로 구성된다. **1단계(observability)만 본 제안의 변경 스펙에 포함**하고, 2단계(수정)는 1단계 결과를 본 뒤 별도 제안서로 분리한다.

1. 메인 엔진이 매 사이클 시작 시점에 "이번 사이클에서 평가할 종목 리스트"를 `system_metrics`에 `metric_type='EVAL_TARGETS'` 레코드로 기록한다.
2. 동시에 그 리스트를 구성할 때 참조한 원천(`screening_results` 조회 결과 수, watchlist 수, 보유 포지션 수)도 함께 detail에 기록한다.

이 관측 데이터로 내일:
- `EVAL_TARGETS.detail.counts = {screening: N, watchlist: M, positions: K}` 가 나온다.
- 만약 `screening=0`으로 찍히면 → 엔진이 `screening_results`를 읽지 못하고 있는 것 (Worker 분리 시 DB 조회 쿼리/캐시 이슈 의심).
- `screening>0`인데 signals에 해당 종목 코드가 안 찍히면 → selector/evaluation 루프에서 필터링되는 것(전략 적용 대상 제외 조건 확인).

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:
  - 사이클 시작 직후 평가 대상 리스트를 생성하는 지점(기존 코드 위치)에서 다음을 호출:
    ```python
    await self._record_eval_targets(
        cycle_number=cycle_number,
        targets=target_codes,
        counts={
            "screening": len(screening_codes),
            "watchlist": len(watchlist_codes),
            "positions": len(position_codes),
        },
    )
    ```
  - `_record_eval_targets()` 신규 메서드 추가: `system_metrics` 테이블에 `metric_type='EVAL_TARGETS'` 레코드 1건 enqueue. `detail` JSON에는 최대 50개까지만 종목 코드를 기록(너무 길어지면 truncate 플래그 추가).

- `src/worker/screener.py`:
  - ScreeningWorker가 `screening_results`에 insert한 결과를 메인 엔진이 어떤 키(시간 범위, 사이클 번호 등)로 조회하는지 주석·docstring 보강. 코드 변경 없음.

- `src/strategy/selector.py`:
  - selector가 "평가 대상 리스트"를 받을 때 내부에서 어떤 기준으로 추려내는지를 로깅하는 경량 트레이스 1줄 추가(DEBUG). 기존 시그니처 유지.

총 3개 파일 → 5개 한도 이내.

### 추가 테스트

- `tests/test_engine_db_integration.py`에 "사이클 시작 시 EVAL_TARGETS 메트릭이 기록된다" 통합 테스트 1개. counts 필드 3개 존재 확인.

### db/models.py / alembic 변경 없음

`system_metrics`는 `detail: jsonb`로 이미 설계되어 있어 스키마 변경 없이 신규 metric_type만 추가하면 된다(기존 `CYCLE_START/END/API_LIMIT/ERROR/RESTART`에 `EVAL_TARGETS` 추가). 값 자체는 문자열이라 스키마 마이그레이션 불필요.

## 기대 효과

- 내일 리포트부터 "screening=N개 발굴 → 엔진 평가 M개 반영" 비율이 보인다.
- 만약 반영 비율이 0%면 "스크리닝 결과 DB 조회 경로 복구"라는 구체적 후속 제안이 가능해진다.
- 반영 비율이 양수인데 signals에 안 나타나면 selector/strategy 필터 문제로 좁혀진다.
- 본 제안 자체는 매매 성과 직접 개선 없음. 후속 제안의 근거 제공.

## 롤백

- `src/engine.py`의 `_record_eval_targets` 호출·메서드 제거.
- `src/strategy/selector.py`의 추가 로깅 1줄 제거.
- `src/worker/screener.py` 주석 변경은 롤백 불필요(주석만).
- 추가 테스트 케이스 제거.
- `config_overrides.json` 영향 없음.
- `git restore` 범위: engine.py, selector.py, screener.py, test_engine_db_integration.py.
