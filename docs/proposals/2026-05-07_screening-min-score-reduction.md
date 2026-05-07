# 스크리닝 최소 점수 하향 — 전환율 0% 장기화 해소

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-07
- 상태: implemented
- 우선순위: high
- 카테고리: param_tuning
- 관련파일: config_overrides.json

## 현상 분석

### 스크리닝 전환율 0% 장기화 (룰 B 트리거)

쿼리 11 (최근 7일 스크리닝 전환율):

| 날짜 | 스크리닝 | 전환 | 전환율 |
|------|----------|------|--------|
| 2026-05-01 | 30 | 0 | 0.0% |
| 2026-05-02 | 30 | 0 | 0.0% |
| 2026-05-03 | 30 | 0 | 0.0% |
| 2026-05-04 | 127 | 0 | 0.0% |
| 2026-05-05 | 32 | 0 | 0.0% |
| 2026-05-06 | 137 | 0 | 0.0% |
| 2026-05-07 | 125 | 0 | 0.0% |

- **7일 연속 전환율 0%** (임계값 10% 미달)
- 4월 하순 이후 지속적인 버그 수정(파이프라인 단절, 타임존, 메서드명 등)에도 불구하고 전환율 개선 없음

### 원인 분석

스크리닝에서 종목을 발굴하지만 `converted_to_trade = true`로 마킹되는 종목이 없음.

가능한 원인:
1. 스크리닝 점수(SCREENING_MIN_SCORE=0.25)가 엔진 평가 기준과 불일치 — 스크리닝 통과 종목이 엔진에서 시그널 미발생
2. 현재 가중치 구성(volume_rank 0.3, change_rate 0.4, strategy 0.3)에서 strategy 가중치가 0.5→0.3으로 하향되어, 전략적 유망성보다 거래량/등락률 중심으로 후보 선정
3. SCREENING_MIN_SCORE 0.25 기준이 현재 시장 상황에서 지나치게 선별적

### 이전 시도 이력

| 구현일 | 내용 | 효과 |
|--------|------|------|
| 04-22 | 스크리닝 메서드명 수정 | 전환율 0% 지속 |
| 04-24 | ETF 필터, 가중치 재조정 | 전환율 0% 지속 |
| 04-28 | 파이프라인 단절 수정 | 전환율 0% 지속 |
| 04-30 | 타임존 불일치 수정 | 전환율 0% 지속 |
| 05-01 | MIN_CONFIDENCE 하향 | 전환율 0% 지속 |

## 제안 내용

`SCREENING_MIN_SCORE`를 기본값 0.25에서 **0.15**로 하향 조정.

- 허용 범위: 0.1 ~ 0.8 (BRIDGE_SPEC 기준)
- 0.15로 하향하면 더 많은 종목이 스크리닝 통과 → 엔진 평가 기회 확대
- 동시에 strategy 가중치가 0.3으로 낮은 상태이므로, 점수 기준 하향이 합리적

## 변경 스펙

### 파일별 변경사항
- `config_overrides.json`: `SCREENING_MIN_SCORE` 키 추가 (값: `0.15`), `_meta` 갱신

```json
{
  "_meta": {
    "updated_at": "2026-05-07",
    "updated_by": "proposal:2026-05-07_screening-min-score-reduction"
  },
  "STRATEGY_RSI_OVERSOLD": 35.0,
  "STRATEGY_MA_SHORT_PERIOD": 3,
  "STRATEGY_MIN_CONFIDENCE": 0.15,
  "SCREENING_WEIGHT_VOLUME_RANK": 0.3,
  "SCREENING_WEIGHT_CHANGE_RATE": 0.4,
  "SCREENING_WEIGHT_STRATEGY": 0.3,
  "SCREENING_MIN_SCORE": 0.15
}
```

> 주의: `STRATEGY_MIN_CONFIDENCE` 값은 동일 날짜 제안서(min-confidence-upward-adjustment)의 변경값 0.15를 반영. 해당 제안서가 먼저 구현될 경우 이미 적용되어 있을 것이며, 미구현 시에도 이 제안서에서 함께 반영.

## 기대 효과

- 스크리닝 후보군 확대 — 0.15~0.25 점수대 종목 추가 포함
- 엔진 평가 대상 종목 증가 → 전환 가능성 향상
- 전환율 0% 교착 상태 해소 기대
- 효과 없을 경우 `converted_to_trade` 마킹 로직 자체의 구조적 점검 필요

## 롤백

`config_overrides.json`에서 `SCREENING_MIN_SCORE` 키를 제거하여 기본값 0.25으로 복원.
