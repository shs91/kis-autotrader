# 스크리닝 종목 시그널 품질 진단 메트릭 추가

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-08
- 상태: implemented
- 우선순위: medium
- 카테고리: performance
- 관련파일: src/engine.py

## 현상 분석

스크리닝 전환율이 7일 연속 0%이다(쿼리 11). 최근 2주간 6건의 파라미터/파이프라인 제안서를 구현했으나(MIN_CONFIDENCE, SCREENING_MIN_SCORE, 일봉 요구량, 파이프라인 수정 등) 전환율 개선이 없다.

금일 심층 분석 결과:
- EVAL_TARGETS: 매 사이클 screening 소스에서 10종목 평가 (파이프라인 정상)
- 시그널 분포: SK하이닉스(000660) 851건 SELL, 삼성전자(005930) 851건 SELL → 미보유 종목 매도 시그널 (전환 불가)
- 나머지 8개 screening 종목: HOLD 시그널 → DB 미기록
- BUY 시그널 발생 screening 종목: 0건

**핵심 병목**: 스크리닝 종목이 전략 분석 시 BUY 시그널을 생성하지 않음. 파라미터 튜닝으로는 해결 불가하며, "어떤 종목이 어떤 시그널을 어떤 신뢰도로 받는지"를 정량적으로 추적해야 원인 특정 가능.

## 제안 내용

매매 사이클 종료 시 기존 SIGNAL_SUMMARY 메트릭에 **스크리닝 소스 종목의 시그널 분포**를 추가 기록한다. 이를 통해 다음 분석에서:
1. 스크리닝 종목 BUY/SELL/HOLD 비율 추적
2. 스크리닝 종목 평균 신뢰도 추적
3. 비BUY 원인 파악 (SELL 과다 vs HOLD 과다 vs 저신뢰도)

이 데이터가 3~5일 축적되면 전환율 0% 근본 원인을 데이터 기반으로 특정할 수 있다.

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:
  - `run_trading_cycle` 메서드 내, 사이클별 카운터 초기화 블록(line ~367)에 스크리닝 종목 전용 카운터 3개 추가:
    ```python
    self._cycle_screening_buy = 0
    self._cycle_screening_sell = 0
    self._cycle_screening_hold = 0
    ```
  - `_process_stock` 메서드 내, 사이클 전략 평가 카운터 갱신 블록(line ~649) 이후에 스크리닝 종목 여부 체크 추가:
    ```python
    if stock_code in self._screened_codes:
        if signal.signal_type == SignalType.BUY:
            self._cycle_screening_buy += 1
        elif signal.signal_type == SignalType.SELL:
            self._cycle_screening_sell += 1
        else:
            self._cycle_screening_hold += 1
    ```
  - SIGNAL_SUMMARY 메트릭 기록 블록(line ~412)의 detail dict에 3개 필드 추가:
    ```python
    "screening_buy": self._cycle_screening_buy,
    "screening_sell": self._cycle_screening_sell,
    "screening_hold": self._cycle_screening_hold,
    ```
  - `__init__` 메서드에 인스턴스 변수 초기화 3개 추가:
    ```python
    self._cycle_screening_buy: int = 0
    self._cycle_screening_sell: int = 0
    self._cycle_screening_hold: int = 0
    ```

## 기대 효과

- 스크리닝 종목의 시그널 품질을 사이클별로 추적 가능
- 3~5 거래일 데이터 축적 후 전환율 0% 근본 원인 특정 가능:
  - SELL 과다 → 스크리닝 기준 변경 필요 (하락 추세 종목 필터링)
  - HOLD 과다 → 전략 감도 조정 필요
  - 저신뢰 BUY → MIN_CONFIDENCE 재조정 필요
- 이후 제안서의 근거 데이터 품질 향상

## 롤백

`src/engine.py`에서 추가된 카운터 변수 3개와 SIGNAL_SUMMARY detail 필드 3개를 제거하면 원복.
기존 SIGNAL_SUMMARY 구조에 필드 추가만 하므로 하위 호환성 영향 없음.
