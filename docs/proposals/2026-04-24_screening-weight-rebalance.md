# 스크리닝 스코어링 가중치 재조정 — 전략 의존도 축소

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-24
- 상태: implemented
- 우선순위: high
- 카테고리: param_tuning
- 관련파일: config_overrides.json

## 현상 분석

4/16~4/24 **9일 연속 스크리닝 전환율 0.0%**. ScreeningWorker는 매일 110~143종목을 발굴하지만, 전략 분석에서 모든 후보가 HOLD(confidence=0)을 받아 전환되지 않는다.

스크리닝 스코어링 공식:
```
total_score = volume_rank × WEIGHT_VOLUME_RANK(0.2)
            + change_rate × WEIGHT_CHANGE_RATE(0.3)
            + strategy   × WEIGHT_STRATEGY(0.5)
```

`strategy_score = confidence if BUY else 0.0`이므로, 전략이 BUY를 반환하지 않으면 strategy 기여는 0이다. 이 경우 최대 가능 점수는 0.5 (volume 0.2 + change_rate 0.3)로 min_score(0.25) 이상이 되어 일부 종목은 통과 가능해야 하지만, 실제로는 `rank_candidates` 이후 `new_codes`가 비어 전환이 0이다.

현재 구조에서 전략 가중치 50%는 과도하다. 전략이 BUY를 반환하지 않는 시장 상황(횡보·약세)에서는 스크리닝이 완전히 무력화된다. 스크리닝의 본래 목적은 "거래량과 등락률 기반으로 유망 종목을 발굴"하는 것이며, 전략 시그널은 보조 지표여야 한다.

## 제안 내용

가중치를 재조정하여 전략 의존도를 축소한다:

| 파라미터 | 현재값 | 제안값 | BRIDGE_SPEC 허용범위 |
|----------|--------|--------|---------------------|
| SCREENING_WEIGHT_VOLUME_RANK | 0.2 | 0.3 | 0.0 ~ 1.0 |
| SCREENING_WEIGHT_CHANGE_RATE | 0.3 | 0.4 | 0.0 ~ 1.0 |
| SCREENING_WEIGHT_STRATEGY | 0.5 | 0.3 | 0.0 ~ 1.0 |

합계: 0.3 + 0.4 + 0.3 = **1.0** (제약 조건 충족)

효과:
- 전략이 BUY일 때 최대 점수: 0.3 + 0.4 + 0.3 = 1.0 (변경 없음)
- 전략이 HOLD일 때 최대 점수: 0.3 + 0.4 + 0.0 = **0.7** (기존 0.5)
- min_score(0.25) 통과 여유 확대: 0.7 vs 0.5
- 거래량 상위 + 등락률 양호한 종목이 전략 시그널 없이도 전환 가능

## 변경 스펙

### 파일별 변경사항

- `config_overrides.json`: 가중치 3개 파라미터 추가/수정

변경 후:
```json
{
  "_meta": {
    "updated_at": "2026-04-24",
    "updated_by": "proposal:2026-04-24_screening-weight-rebalance"
  },
  "STRATEGY_RSI_OVERSOLD": 35.0,
  "SCREENING_WEIGHT_VOLUME_RANK": 0.3,
  "SCREENING_WEIGHT_CHANGE_RATE": 0.4,
  "SCREENING_WEIGHT_STRATEGY": 0.3
}
```

기존 `STRATEGY_RSI_OVERSOLD: 35.0` (4/17 제안서)은 유지.

## 기대 효과

- 전략이 모두 HOLD인 시장 상황에서도 거래량/등락률 기반 후보가 min_score를 통과하여 converted_to_trade=true 비율 상승
- 엔진의 `_screened_codes`에 종목이 유입되어 모니터링 대상 확대 (현재 7종목 → 최대 17종목)
- 앙상블 HOLD 가드 완화(별도 제안서)와 병행 시 스크리닝→시그널→매매 파이프라인 정상화 기대
- 과도한 매수 위험은 MAX_POSITION_RATIO(20%), MIN_CONFIDENCE(0.1), MAX_LOSS_RATE(3%)가 제어

## 롤백

`config_overrides.json`에서 아래 3개 키를 제거 (기본값 복원):
- `SCREENING_WEIGHT_VOLUME_RANK`
- `SCREENING_WEIGHT_CHANGE_RATE`
- `SCREENING_WEIGHT_STRATEGY`
