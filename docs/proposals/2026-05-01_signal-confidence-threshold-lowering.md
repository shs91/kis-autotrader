# 시그널 저장 필터 임계값 하향 — 스크리닝 전환율 0% 장기화 해소

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-01
- 상태: implemented
- 우선순위: high
- 카테고리: param_tuning
- 관련파일: config_overrides.json

## 현상 분석

### 스크리닝 전환율 0% 장기화 (룰 B 트리거)

쿼리 11 결과, 최근 7일(04-25 ~ 05-01) 전체 기간에서 스크리닝 전환율 0.0%:

| 날짜 | 스크리닝 | 전환 | 전환율 |
|------|----------|------|--------|
| 04-27 (월, 거래일) | 147 | 0 | 0.0% |
| 04-28 (화, 거래일) | 129 | 0 | 0.0% |
| 04-29 (수, 거래일) | 122 | 0 | 0.0% |
| 04-30 (목, 거래일) | 33 | 0 | 0.0% |
| 05-01 (금, 휴장) | 30 | 0 | 0.0% |

3일 연속 < 10% 조건 충족.

### 근본 원인: 시그널 저장 필터 임계값

시그널은 04-17 이후 0건 (signals 테이블). 그러나 EVAL_TARGETS 메트릭은 매 사이클 17종목 평가 정상 수행 확인. 시그널 생성 자체는 작동하나, `src/engine.py:997-1004`의 저장 필터에서 전량 탈락:

1. HOLD 시그널 → 무조건 스킵 (저장 안 함)
2. BUY/SELL 시그널 + 미체결(action_taken=False) + confidence < `STRATEGY_MIN_CONFIDENCE`(0.08) → 스킵
3. 현재 시장 상황에서 BUY/SELL 시그널의 confidence가 대부분 0.08 미만 → 전량 필터링

04-24 구현에서 MIN_CONFIDENCE를 0.10 → 0.08로 하향했으나, 여전히 임계값 이상의 시그널이 발생하지 않고 있음.

### 데이터 근거

- signals 테이블 최근 기록: 04-17 (1,753건), 이후 0건 (14일 연속)
- system_metrics EVAL_TARGETS: 17종목/사이클, 1,099사이클/일 = 약 18,683회 평가/일
- system_metrics SIGNAL_SKIP: 0건 (HOLD 시그널 스킵 기록도 미작동)
- 현재 config_overrides: STRATEGY_MIN_CONFIDENCE = 0.08

## 제안 내용

`STRATEGY_MIN_CONFIDENCE`를 0.08에서 0.05로 하향 (BRIDGE_SPEC 허용 최솟값).

### 근거
- BRIDGE_SPEC 허용 범위: 0.05 ~ 0.5
- 현재값 0.08에서 시그널 0건 → 임계값이 현재 시장 상황에 비해 높음
- 0.05로 하향 시 경계 수준(borderline) 시그널이 DB에 기록되어 (1) 매매 발생 가능성 증가 (2) 시그널 분포 데이터 확보 → 이후 최적값 산정 가능
- 리스크 관리(MAX_LOSS_RATE 3%, MAX_POSITION_RATIO 20%, DAILY_TRADE_LIMIT 200)가 별도 작동하므로 저신뢰도 시그널의 매매 리스크는 제한적

## 변경 스펙

### config_overrides.json

변경 전:
```json
{
  "_meta": {
    "updated_at": "2026-04-24",
    "updated_by": "proposal:2026-04-24_screening-weight-rebalance+ma-period-shortening+min-confidence-lowering"
  },
  "STRATEGY_MIN_CONFIDENCE": 0.08
}
```

변경 후:
```json
{
  "_meta": {
    "updated_at": "2026-05-01",
    "updated_by": "proposal:2026-05-01_signal-confidence-threshold-lowering"
  },
  "STRATEGY_MIN_CONFIDENCE": 0.05
}
```

(다른 기존 오버라이드 값은 유지)

## 기대 효과

- confidence 0.05~0.08 범위의 시그널이 DB에 기록됨 → 시그널 가뭄 해소
- 기록된 시그널 중 리스크 체크를 통과하는 건이 매매로 전환 → 스크리닝 전환율 0% 탈피
- 시그널 분포 데이터 축적 → 향후 최적 임계값 재산정 근거 확보

## 롤백

config_overrides.json에서 `STRATEGY_MIN_CONFIDENCE`를 0.08로 복원.
