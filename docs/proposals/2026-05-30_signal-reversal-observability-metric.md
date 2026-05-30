# 앙상블 단기 신호 변동성 관측 — SIGNAL_REVERSAL 메트릭 도입

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-30
- 상태: implemented
- 우선순위: medium
- 카테고리: performance
- 관련파일: src/engine.py, src/config.py, tests/test_engine_signal_reversal.py

## 현상 분석

W22 주간 리포트 §리스크 분석 / 중기 아키텍처 논의, 5월 월간 리포트 §신규 미해결 항목 3에서
**앙상블 단기 신호 변동성**이 반복 지적되었다.

- **5/26 062970(한국첨단소재)**: 09:15:55 STOP_LOSS 매도(-3.11%) → **42초 뒤** 09:16:37 ENSEMBLE BUY 재진입.
  동일 종목에 대해 단 42초 사이 SELL → BUY 신호가 반전됨.
- **5/28~5/29 230980(비유테크놀러지)**: conf 1.000 → 24시간 내 conf 0(HOLD)으로 소멸.

5/30 v0.7.0(`screening 위험종목 사전 배제`)으로 230980 같은 **정리매매·치명 공시 종목**은
후보 풀에서 사전 배제되어 신호 평가 자체에서 빠졌다. 그러나 062970은 정상 종목이며,
v0.7.0 배제 대상이 아니다. 즉 **정상 종목에서의 단기 신호 반전 현상은 여전히 미관측·미계량 상태**다.

문제는 현재 시스템에 **"동일 종목의 신호 방향이 단기간에 몇 번 반전되는가"를 측정하는 수단이 없다**는 것이다.
`signals` 테이블에는 개별 신호가 적재되나, 반전 사건을 사후 raw 쿼리로만 추정할 수 있어
리포트가 매번 수작업으로 사례를 발굴해 왔다. 리포트의 권고(월간 §방향 제안 2)는
"**먼저 정량화한 뒤** cooldown/평활화 도입 여부를 판단"이다.

본 제안서는 그 첫 단계인 **계량(관측)만** 수행한다. 매매 동작은 일절 바꾸지 않는다.

## 제안 내용

매매 사이클에서 종목별 직전 BUY/SELL 신호를 인메모리로 기억하고, 새 신호가
**직전과 반대 방향**이며 **설정 윈도(기본 600초) 이내**에 발생하면
`SIGNAL_REVERSAL` 시스템 메트릭을 1건 기록한다.

- 매매·주문·게이트 로직은 변경하지 않는다(순수 관측). 메트릭 기록 실패는 swallow.
- HOLD 신호는 무행동이므로 반전 판정·기억 대상에서 제외(노이즈 차단).
- 윈도는 `config_overrides.json` 또는 env로 조정 가능하게 설정값화한다.

이 데이터가 1~2주 누적되면 "반전 빈발 종목/시간대"가 드러나며,
이후 신호 cooldown 또는 앙상블 confidence 평활화(EMA) 도입을 **데이터 근거로** 판단할 수 있다.

## 변경 스펙

### 파일별 변경사항

- `src/config.py` — `TradingConfig`(현재 src/config.py:208)에 관측 윈도 필드 추가.
  기존 `news_risk_lookback_days`(src/config.py:228) 바로 아래에 동일 패턴으로 삽입:

  ```python
  # 단기 신호 반전 관측 윈도 (proposal 2026-05-30, 관측 전용)
  signal_reversal_window_seconds: int = field(
      default_factory=lambda: _env_int("SIGNAL_REVERSAL_WINDOW_SECONDS", 600)
  )
  ```

- `src/engine.py`:
  1. `__init__`의 인메모리 상태 영역(현재 src/engine.py:117-146, `_pending_orders`(146) 부근)에
     종목별 직전 신호 상태 추가. 다른 일일 인메모리 상태(`_today_buys_per_stock`(121),
     `_untradable_today`(124))와 같은 성격:

     ```python
     # 종목별 직전 BUY/SELL 신호 (단기 반전 관측용, BUY/SELL만 저장)
     self._last_signal_by_stock: dict[str, tuple[SignalType, float, datetime]] = {}
     ```

     (`datetime`은 src/engine.py:8 `from datetime import UTC, date, datetime, timedelta`로
     이미 import. `SignalType`도 이미 사용 중.)

  2. `pre_market`의 일일 카운터 리셋부(현재 src/engine.py:295-297,
     `_today_buys_per_stock.clear()`·`_untradable_today.clear()` 인접)에 초기화 1줄 추가:

     ```python
     self._last_signal_by_stock.clear()
     ```

  3. `_process_stock`(src/engine.py:668)에서 `signal = strategy.analyze(df)`(src/engine.py:710)로
     시그널을 확보·로깅한 직후(현재 src/engine.py:720 이후, 사이클 카운터 갱신 직전)에
     반전 관측 헬퍼 호출을 삽입한다. 신규 private 메서드로 분리:

     ```python
     def _observe_signal_reversal(self, stock_code: str, signal: Signal) -> None:
         """동일 종목의 단기 BUY↔SELL 신호 반전을 SIGNAL_REVERSAL 메트릭으로 관측한다.

         매매 동작에는 영향이 없는 순수 관측 경로다. HOLD는 무행동이므로 제외한다.
         기록 실패는 매매 본 흐름에 영향이 없도록 swallow 한다.
         """
         if signal.signal_type not in (SignalType.BUY, SignalType.SELL):
             return
         try:
             now = datetime.now(UTC)
             prev = self._last_signal_by_stock.get(stock_code)
             if prev is not None:
                 prev_type, prev_conf, prev_time = prev
                 gap = (now - prev_time).total_seconds()
                 window = settings.trading.signal_reversal_window_seconds
                 if prev_type != signal.signal_type and 0 <= gap <= window:
                     self._record_metric("SIGNAL_REVERSAL", {
                         "stock_code": stock_code,
                         "prev_type": prev_type.value,
                         "new_type": signal.signal_type.value,
                         "prev_confidence": round(float(prev_conf), 4),
                         "new_confidence": round(float(signal.confidence), 4),
                         "gap_seconds": round(gap, 1),
                         "cycle": self._cycle_count,
                     })
             self._last_signal_by_stock[stock_code] = (
                 signal.signal_type, signal.confidence, now,
             )
         except Exception:
             logger.exception("SIGNAL_REVERSAL 관측 실패: %s", stock_code)
     ```

     `_process_stock` 본문에서 시그널 확보 직후 `self._observe_signal_reversal(stock_code, signal)` 호출.
     (시간은 코드베이스 표준 `datetime.now(UTC)` 사용 — 별도 시간 helper 모듈 없음.)

### 추가 테스트

- `tests/test_engine_signal_reversal.py` 신설. 기존 `tests/test_engine_untradable_blacklist.py`의
  엔진 인스턴스 구성 패턴을 따른다. `_record_metric`을 모킹/감시해 호출 여부·detail을 검증:
  1. 동일 종목 BUY→SELL, 윈도 이내 → `SIGNAL_REVERSAL` 1건 기록(detail 필드 검증).
  2. 동일 종목 BUY→SELL, 윈도 초과(gap > window) → 미기록.
  3. 동일 종목 BUY→BUY(동일 방향) → 미기록.
  4. 다른 종목 신호 → 미기록(상태 분리).
  5. HOLD 신호는 비교·기억 대상에서 제외(직전 BUY가 있어도 HOLD로는 반전 미기록, 상태 미갱신).
  6. `pre_market` 호출(일자 변경) 후 `_last_signal_by_stock`가 비워짐.

## 기대 효과

- **정량 근거 확보**: 062970 같은 단기 신호 반전이 정상 종목에서 일·주 단위로 몇 건 발생하는지
  `system_metrics(SIGNAL_REVERSAL)`로 직접 집계 가능. 리포트의 수작업 사례 발굴 → 자동 계량으로 전환.
- **후속 의사결정 입력**: 누적 데이터로 신호 cooldown 또는 앙상블 평활화(EMA) 도입 여부를
  데이터 기반으로 판단(월간 §방향 제안 2의 "측정 먼저" 단계 충족).
- **무위험**: 매수/매도/게이트 어느 경로도 바뀌지 않으며, 메트릭 큐 적재만 추가됨.
  DB 마이그레이션·신규 의존성 없음(`system_metrics`는 기존 테이블, `_record_metric` 기존 경로 재사용).

## 롤백

- `config_overrides.json`에서 키 제거가 아니라 코드 변경이므로, `git restore`로
  `src/engine.py`·`src/config.py` 원복 + `tests/test_engine_signal_reversal.py` 삭제.
- 관측 전용이라 비활성화만 원하면 `SIGNAL_REVERSAL_WINDOW_SECONDS=0`으로 두면
  `0 <= gap <= 0` 조건상 사실상 동시(0초) 신호만 잡혀 기록이 거의 발생하지 않음(완전 차단은 코드 원복).
