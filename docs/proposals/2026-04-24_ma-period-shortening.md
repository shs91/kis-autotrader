# MA 이동평균 기간 단축 — 골든크로스 발생 빈도 개선

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-24
- 상태: implemented
- 우선순위: high
- 카테고리: param_tuning
- 관련파일: config_overrides.json

## 현상 분석

4월 월간 데이터 분석 결과, GOLDEN_CROSS 시그널이 4/14 이후 완전히 소멸했다. MA(5/20) 설정에서 단기 이동평균과 장기 이동평균의 교차가 발생하지 않는 시장 국면이 9거래일 이상 지속 중이다.

근거 데이터:
- 4/7~4/10: GOLDEN_CROSS 5,837건 발생 (일평균 1,946건)
- 4/13~4/14: GOLDEN_CROSS 299건으로 급감
- 4/15 이후: GOLDEN_CROSS 0건
- 시스템 전체 매수 시그널 0건 → 매매 완전 중단

MA(5/20)은 단기 5일과 장기 20일의 교차를 감지하는데, 시장이 완만한 추세를 유지하거나 좁은 범위에서 횡보하면 두 이동평균이 수렴하여 교차 없이 병행한다.

단기 기간을 3일로 단축하면 더 민감한 가격 변동에도 교차가 발생하여 시그널 빈도를 높일 수 있다.

## 제안 내용

`STRATEGY_MA_SHORT_PERIOD`를 5 → 3으로 변경한다.

**근거**:
- BRIDGE_SPEC 허용 범위: 3 ~ 10 (범위 내)
- 단기 MA를 3일로 줄이면 가격 변동에 더 민감하게 반응하여 교차 빈도 증가
- 장기 MA(20)는 유지하여 추세 기반 필터링 역할 보존
- MA(3/20)은 일반적으로 사용되는 기간 조합

**리스크**:
- 노이즈 시그널 증가 가능 → 그러나 신뢰도 필터(MIN_CONFIDENCE 0.1)와 리스크 관리자(손절 3%/익절 5%)가 방어
- 현재 0건인 시그널 빈도를 올리는 것이 최우선이므로, false positive 증가보다 false negative 감소가 더 중요

## 변경 스펙

### 파일별 변경사항
- `config_overrides.json`: `STRATEGY_MA_SHORT_PERIOD: 3` 추가

변경 후 `config_overrides.json`:
```json
{
  "_meta": {
    "updated_at": "2026-04-24",
    "updated_by": "proposal:2026-04-24_ma-period-shortening"
  },
  "STRATEGY_RSI_OVERSOLD": 35.0,
  "STRATEGY_MA_SHORT_PERIOD": 3
}
```

### 추가 테스트
- 기존 테스트 통과 필수 (파라미터 변경만이므로 코드 변경 없음)

## 기대 효과

- GOLDEN_CROSS 시그널 발생 빈도 증가 (단기 MA가 가격 변동에 더 민감하게 반응)
- 매매 활동 재개 — 9거래일 연속 유휴 상태 해소
- 앙상블 내 MA 서브전략이 BUY 투표를 내기 시작하면 ENSEMBLE 시그널도 BUY 방향 생성 가능

**정량 검증**: 변경 후 5거래일간 GOLDEN_CROSS BUY 시그널 발생 건수를 모니터링. 0건이면 추가 조정 검토.

## 롤백

`config_overrides.json`에서 `STRATEGY_MA_SHORT_PERIOD` 키를 제거하면 기본값 5로 복귀.
```json
{
  "_meta": { "updated_at": "2026-04-24", "updated_by": "rollback" },
  "STRATEGY_RSI_OVERSOLD": 35.0
}
```
