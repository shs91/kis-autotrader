# 최소 신뢰도 임계값 하향 — 앙상블 BUY 시그널 실행 가능성 확대

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-24
- 상태: implemented
- 우선순위: medium
- 카테고리: param_tuning
- 관련파일: config_overrides.json

## 현상 분석

4월 데이터 분석 결과, GOLDEN_CROSS 시그널 9,326건 중 5건만 실행(0.05%)되었다. 미실행 시그널의 평균 신뢰도는 0.172로 MIN_CONFIDENCE(0.1) 이상이지만, RiskManager의 `validate_order()`에서 추가 필터(잔고 부족, 장 마감 임박, 일일 매매 제한 등)에 의해 대부분 차단되었다.

실행된 5건의 평균 신뢰도는 0.264였으나, 실제 수익률과의 상관관계가 없었다:
- 신뢰도 0.508 → 결과 미확인
- 신뢰도 0.426 → -3.01% (손절)
- 신뢰도 0.110 → +5.03% (익절 최고)

현재 MIN_CONFIDENCE = 0.1에서 추가적으로 걸러지는 시그널은 소수이나, 향후 MA 기간 단축(제안서: 2026-04-24_ma-period-shortening)으로 시그널 빈도가 증가하면, 낮은 괴리율의 교차도 매수 기회로 활용할 수 있도록 임계값을 낮추는 것이 유리하다.

## 제안 내용

`STRATEGY_MIN_CONFIDENCE`를 0.1 → 0.08로 하향한다.

**근거**:
- BRIDGE_SPEC 허용 범위: 0.05 ~ 0.5 (범위 내)
- 신뢰도와 수익률 간 상관이 없으므로, 임계값을 낮춰 매수 기회를 넓히는 것이 합리적
- 손절/익절(3%/5%)이 독립적으로 리스크를 관리하므로, 진입 필터를 약간 완화해도 안전
- 0.08은 보수적 하향 — 급격한 변경(0.05) 대신 소폭 조정하여 효과 관찰

**리스크**:
- 노이즈 매수 약간 증가 가능 → 손절 3%가 방어
- 일일 매매 제한(200건)이 과도한 매수를 차단

## 변경 스펙

### 파일별 변경사항
- `config_overrides.json`: `STRATEGY_MIN_CONFIDENCE: 0.08` 추가

변경 후 `config_overrides.json` (MA 제안서가 먼저 구현된 경우):
```json
{
  "_meta": {
    "updated_at": "2026-04-24",
    "updated_by": "proposal:2026-04-24_min-confidence-lowering"
  },
  "STRATEGY_RSI_OVERSOLD": 35.0,
  "STRATEGY_MA_SHORT_PERIOD": 3,
  "STRATEGY_MIN_CONFIDENCE": 0.08
}
```

### 추가 테스트
- 기존 테스트 통과 필수 (파라미터 변경만이므로 코드 변경 없음)

## 기대 효과

- 신뢰도 0.08~0.10 구간의 시그널이 추가로 매수 실행 대상에 포함
- MA 기간 단축과 결합 시 매매 활동 재개 가능성 증대
- 앙상블 시그널의 BUY 방향 전환 시에도 실행 가능성 확보

**정량 검증**: MA 기간 변경과 함께 적용 후 5거래일간 action_taken=true 건수 추이 모니터링. 과도한 손절(일 3건 이상 STOP_LOSS) 발생 시 0.1로 복귀.

## 롤백

`config_overrides.json`에서 `STRATEGY_MIN_CONFIDENCE` 키를 제거하면 기본값 0.1로 복귀.
