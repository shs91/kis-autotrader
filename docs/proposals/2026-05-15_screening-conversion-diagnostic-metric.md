# 스크리닝→매매 매핑 진단 메트릭 추가 — 룰 B 측정값 분해

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-15
- 상태: implemented
- 우선순위: high
- 카테고리: performance
- 관련파일: src/worker/screener.py, src/engine.py

## 현상 분석

### 룰 B 트리거 (3일 연속 스크리닝 전환율 < 10%)
| 일자(KST) | 스크리닝 발굴 | 전환(converted=true) | 전환율 |
|------|----------|------|--------|
| 2026-05-13 | 27 | 0 | 0.0% |
| 2026-05-14 | 39 | 0 | 0.0% |
| 2026-05-15 | 29 | 0 | 0.0% |

### 문제 — 측정값 의미 모호
- 워커 로직 점검(`src/worker/screener.py:201-225`) 결과 `converted_to_trade`는 워커가 자체 산정한 `new_candidates`(추천 후보)에 포함되는지 여부로만 기록됨. **실제 매매(trades 발생) 여부와 매핑되지 않는다.**
- 엔진 측 로직(`src/engine.py:540-580`)도 `converted_to_trade` 플래그를 활용하지 않고 ranked 결과만 읽어 매매 후보로 추가.
- 즉 현재 측정 가능한 "전환율 = SUM(converted_to_trade) / total"은 워커의 사전 필터를 표현할 뿐, 룰 B가 진단하려는 "스크리닝 풀에서 얼마나 매매로 이어졌는가"를 직접 측정하지 못한다.

### 어제(5-14) 실제 사례
- 5-14에는 BUY 3건(전부 LG디스플레이)이 발생했으나 5-14 스크리닝 전환은 0건이었음.
- 5-15는 BUY 0건 + 스크리닝 전환 0건.
- 두 케이스를 동일하게 "전환율 0%"로 보면 룰 B 의도(매매 부진 감지)가 흐려진다.

### 결론
파라미터(`SCREENING_MIN_SCORE`, `SCREENING_MIN_VOLUME`) 조정 전 측정값을 분해하여 다음 두 지표를 system_metrics에 분리 기록한다:
1. 워커 사이클별 추천 후보 수 (`SCREENING_CANDIDATE`)
2. 엔진의 신규 매수 시 스크리닝 풀 일치 여부 (`SCREENING_HIT` / `SCREENING_MISS`)

## 제안 내용

룰 B는 트리거 조건을 충족했으나, 직접 파라미터 조정은 부적절하다. 진단 메트릭을 먼저 도입하여 실제 매수가 스크리닝 풀에서 얼마나 나오고 있는지를 별도 카운터로 확보한다.

이 진단이 1주일 운영되면 룰 B의 의미가 (a) 워커가 추천을 안 함, (b) 추천했으나 엔진이 매수 안 함, (c) 엔진이 매수했으나 매핑 갱신 안 됨 중 어디에 해당하는지 분리 가능 → 후속 제안에서 정확한 파라미터 대상 식별 가능.

## 변경 스펙

### 파일별 변경사항

#### 1. `src/worker/screener.py`
- `_record_to_db` 메서드의 배치 기록 직후 system_metrics에 추천 후보 카운트 1건 기록 추가.
- 기록 위치: 226줄(`if etf_blocked:` 직전)에 신규 블록 삽입.
- 사용 컬럼: `metric_type='SCREENING_CANDIDATE'`, `detail={"cycle": self._cycle_count, "ranked_total": len(ranked), "candidate_count": len(candidate_set)}`.
- 기록은 `SystemMetricRepository.record_metric` 등 기존 등록 경로 활용(현 모듈에서 import 추가 필요). 기록 실패 시 `logger.exception`만 남기고 진행(스크리닝 본 흐름 중단 금지).

#### 2. `src/engine.py`
- 신규 BUY 주문 체결 직후 동일 사이클 내 screening_results를 조회하여 매칭 여부를 system_metrics에 기록.
- 기록 위치: 신규 BUY 주문 처리 종료 직전(`record_screening` 호출은 사이클 종료 시점 1001줄 부근에서 이미 발생 → 별도 위치에서 매수 직후 1회 기록 권장).
- 사용 컬럼: `metric_type='SCREENING_HIT'`(매칭 성공) 또는 `'SCREENING_MISS'`(매칭 실패), `detail={"cycle": cycle, "stock_code": code, "matched": bool}`.
- 매칭 기준: 당일 KST 기준 `screening_results.stock_code = trades.stock_code` 의 행이 1건이라도 존재하면 HIT, 없으면 MISS.
- 조회 실패/예외 발생 시 `logger.exception` 후 매매 본 흐름은 그대로 진행(주문 후 처리이므로 매매에 영향 없음).

### 추가 테스트
- `tests/test_worker/test_screener.py`에 `_record_to_db` 호출 후 `record_metric`이 `SCREENING_CANDIDATE`로 1회 호출됐는지 확인하는 케이스 추가(mock 활용).
- `tests/test_engine_db_integration.py`(또는 신규 `tests/test_engine_screening_hit.py`)에 신규 BUY 발생 시 동일 stock_code의 screening_results 존재/미존재에 따라 `SCREENING_HIT` / `SCREENING_MISS`가 기록되는지 확인하는 케이스 추가.

### 변경 파일 수
- 코드: 2개 (`src/worker/screener.py`, `src/engine.py`)
- 테스트: 1~2개 (기존 + 신규)
- 합계 4개 이하 — BRIDGE_SPEC 5개 제한 준수.

## 기대 효과

- 1~2주 누적 후 룰 B의 측정값을 (워커 후보 / 엔진 매수 / 매핑 일치율)로 분해 가능.
- 분해된 지표를 토대로 후속 제안서에서 진짜 병목 단계(워커 vs 엔진 vs 매핑)에 맞는 파라미터 조정 가능 — 무차별 임계값 조정으로 인한 매매 위축 위험 회피.
- 시스템 안정성에 미치는 영향: 기록 실패 시 fallback 처리되므로 매매·스크리닝 본 흐름과 무관(0% 회귀 위험).

## 롤백

- 변경 파일이 모두 추가 코드(insert)이므로 `git restore src/worker/screener.py src/engine.py tests/test_worker/test_screener.py tests/test_engine_db_integration.py`로 즉시 원복 가능.
- system_metrics 테이블에 신규 카테고리 추가지만 enum 제약은 없음 — DB 마이그레이션 불필요. 잔여 기록은 향후 무시 가능(또는 `DELETE FROM system_metrics WHERE metric_type IN ('SCREENING_CANDIDATE', 'SCREENING_HIT', 'SCREENING_MISS')` 1회 실행).
