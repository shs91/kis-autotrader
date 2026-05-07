# 시그널 최소 신뢰도 상향 조정 — 저신뢰 시그널 필터링

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-07
- 상태: implemented
- 우선순위: high
- 카테고리: param_tuning
- 관련파일: config_overrides.json

## 현상 분석

### 시그널 전환율 저하 (룰 A 트리거)

쿼리 10 (최근 7일 시그널 성과):

| 시그널 유형 | 발생 | 실행 | 전환율 | 평균 신뢰도 |
|-------------|------|------|--------|-------------|
| ENSEMBLE | 5,079 | 1,499 | 29.5% | 0.230 |

- **act_rate_pct 29.5% < 50%** (임계값 미달)
- **avg_confidence 0.230 < 0.3** (임계값 미달)

### 원인 분석

2026-05-01 제안서에서 `STRATEGY_MIN_CONFIDENCE`를 0.08에서 0.05로 하향 조정한 결과:
- 시그널 발생량 대폭 증가 (일 5,000건 이상)
- 그러나 평균 신뢰도가 0.230으로 저하
- 대량의 저신뢰 시그널이 리스크 체크 등에서 필터링되어 실행률 29.5%에 그침
- 신뢰도 0.05~0.15 구간의 노이즈성 시그널이 act_rate를 끌어내리는 구조

### 배경

MIN_CONFIDENCE 하향은 매매 교착 해소를 위한 조치였으나, 일봉 데이터 요구량 하향(05-06)으로 매매 교착이 이미 해소됨 (05-07 첫 매수 발생). 따라서 MIN_CONFIDENCE를 적절히 상향하여 신호 대 잡음 비율을 개선할 시점.

## 제안 내용

`STRATEGY_MIN_CONFIDENCE`를 0.05에서 **0.15**로 상향 조정.

- 허용 범위: 0.05 ~ 0.5 (BRIDGE_SPEC 기준)
- 0.15는 현재 평균 신뢰도 0.230보다 낮으므로, 상위 ~70% 시그널은 유지
- 극저신뢰(0.05~0.15) 노이즈 제거로 act_rate 개선 기대

## 변경 스펙

### 파일별 변경사항
- `config_overrides.json`: `STRATEGY_MIN_CONFIDENCE` 값을 `0.05` → `0.15`로 변경, `_meta` 갱신

```json
{
  "_meta": {
    "updated_at": "2026-05-07",
    "updated_by": "proposal:2026-05-07_min-confidence-upward-adjustment"
  },
  "STRATEGY_RSI_OVERSOLD": 35.0,
  "STRATEGY_MA_SHORT_PERIOD": 3,
  "STRATEGY_MIN_CONFIDENCE": 0.15,
  "SCREENING_WEIGHT_VOLUME_RANK": 0.3,
  "SCREENING_WEIGHT_CHANGE_RATE": 0.4,
  "SCREENING_WEIGHT_STRATEGY": 0.3
}
```

## 기대 효과

- 시그널 발생량 감소 (저신뢰 구간 필터링)
- act_rate 상승 (분모 감소)
- 평균 신뢰도 상승 (0.230 → 예상 0.30 이상)
- 매매 품질 개선 — 고신뢰 시그널 기반 매매 집중

## 롤백

`config_overrides.json`에서 `STRATEGY_MIN_CONFIDENCE`를 `0.05`로 복원.
