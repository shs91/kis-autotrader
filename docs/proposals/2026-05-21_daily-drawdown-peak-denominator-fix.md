# 일일 MDD halt 분모 결함 수정 — 피크 대비 비율이 장 초반 정상 손절을 봉인

## 메타데이터
- 작성: Cowork (일간 분석 자동 라우틴)
- 일자: 2026-05-21
- 상태: implemented (2026-05-22)
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/strategy/risk.py, tests/test_strategy/test_risk.py

> ✅ **결정·구현 완료 (2026-05-22).** 사용자가 **안 (a) 순손실 가드**를 채택. `record_trade_result`의 MDD 발동 조건에 `daily_cumulative_pnl < 0` 가드를 추가했다. 회귀 테스트 3종 추가 + 구 동작(흑자 halt)에 의존하던 테스트 2건(test_risk, test_engine_buy_gate_metric)을 순손실 시나리오로 갱신. 고위험(리스크 게이트 완화) 변경이라 자동 구현이 아닌 사용자 승인 후 수동 PR로 처리.

## 현상 분석

2026-05-21, 09:22:10에 `MAX_DAILY_DRAWDOWN` halt가 발동하여 당일 매매가 장 마감까지(약 5시간 35분) 전면 중단되었다.

당일 실현 매도는 단 2건:
- 09:11:14 TAKE_PROFIT **+39,440원** → 누적손익 +39,440, 일중 피크 +39,440
- 09:21:53 STOP_LOSS **-24,300원** → 누적손익 +15,140 (여전히 흑자), 연패 1회

이때 `src/strategy/risk.py:record_trade_result()`의 MDD 계산:
```
drawdown      = daily_peak_pnl - daily_cumulative_pnl = 39,440 - 15,140 = 24,300
drawdown_pct  = drawdown / daily_peak_pnl             = 24,300 / 39,440 = 0.616 (61.6%)
0.616 >= max_daily_drawdown(0.05) → _portfolio_halted = True
```

**근본 원인**: MDD 비율의 분모가 "당일 실현손익 피크(`daily_peak_pnl`)"다. 장 초반 피크가 작을 때(첫 익절 1회)는 그 뒤 **정상적인 손절 1회**(-3.16%, MAX_LOSS_RATE 이내)만으로도 피크 대비 비율이 폭증해 즉시 한도를 넘긴다. 결과적으로 "첫 익절 → 손절" 시퀀스가 **순익 흑자·연패 1회 상태에서 당일 매매를 봉인**한다.

**param 튜닝으로 해결 불가**: MAX_DAILY_DRAWDOWN 허용 범위 상한은 0.15(15%)인데 오늘 trip 값은 61.6%. 상한으로도 막을 수 없음 → 임계값이 아니라 **분모 정의(로직)** 결함.

### 근거 데이터 (쿼리 번호 인용)
- 쿼리 1 (daily_stats): buy 2 / sell 2 / win 1, total_pnl **+15,140**, win_rate 50%
- 쿼리 8 (intraday_cumulative_pnl): 피크 +39,440 → 종료 +15,140 (회수폭 24,300 = 피크의 61.6%)
- 쿼리 9 (system_metrics): cycles_started **66** (09:00:00~09:21:50), 이후 halt
- BUY_REJECT 분포: LOW_CONFIDENCE 101, **MAX_DAILY_DRAWDOWN 2** (halt 사유 확인)
- 7일 사이클 추이: 5/21 **66** vs 5/20 706 / 5/19 527 (91% 급감, halt 영향)
- 로그: `2026-05-21 09:21:53 | WARNING | 포트폴리오 MDD 한도 도달: 61.6% >= 5.0% (피크 39440 → 현재 15140)`

## 제안 내용

일일 MDD halt의 본래 취지는 "**당일 손실이 과도해지면 매매를 멈춘다**"이다. 현재 구현은 "장중 실현이익의 반납폭"을 측정하므로 흑자 상태에서도 발동한다. 분모/발동 조건을 취지에 맞게 교정한다.

### 후보 수정 (사람이 택일 — 검토 항목)

- **(a) 권장: 순손실 가드 추가.** 피크 대비 MDD halt는 **당일 누적손익이 순손실(`daily_cumulative_pnl < 0`)일 때만** 발동하도록 한다. 흑자 구간에서는 일일 손실 한도가 발동하지 않음 → 오늘 사례 방지. 부작용: 장중 큰 이익을 흑자 범위 내에서 반납해도 halt 안 함(트레일링 보호 약화). 일일 "손실" 한도 취지와는 일치.
- **(b) 대안: 최소 피크 floor.** `daily_peak_pnl`이 일정 절대금액(예: 1회 평균 손절폭 또는 설정값) 이상일 때만 피크 대비 MDD를 적용. 장 초반 작은 피크에서의 오발동만 차단하고 트레일링 보호는 유지. 단, floor 값 근거가 임의적.

> 본 제안서는 (a)를 기준으로 변경 스펙을 기술한다. (b) 채택 시 스펙 재작성.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/risk.py` (`record_trade_result`, 현재 90-103행):
  - **변경 전**:
    ```python
    drawdown = self._daily_peak_pnl - self._daily_cumulative_pnl
    if self._daily_peak_pnl > 0:
        drawdown_pct = drawdown / self._daily_peak_pnl
        if drawdown_pct >= self._max_daily_drawdown:
            self._portfolio_halted = True
            if self._halt_reason is None:
                self._halt_reason = "MAX_DAILY_DRAWDOWN"
            logger.warning(...)
    ```
  - **변경 후** (안 a): MDD 발동 조건에 `self._daily_cumulative_pnl < 0` 가드 추가.
    ```python
    drawdown = self._daily_peak_pnl - self._daily_cumulative_pnl
    # 일일 손실 한도는 "당일 순손실" 상태에서만 발동 (흑자 구간 오발동 방지)
    if self._daily_peak_pnl > 0 and self._daily_cumulative_pnl < 0:
        drawdown_pct = drawdown / self._daily_peak_pnl
        if drawdown_pct >= self._max_daily_drawdown:
            self._portfolio_halted = True
            if self._halt_reason is None:
                self._halt_reason = "MAX_DAILY_DRAWDOWN"
            logger.warning(...)
    ```
  - (관측 개선, 동반 권장) halt 경고를 `log_warning()` 경로로 승격하거나 engine.py halt 분기에서 system_metrics(HALT) 1회 적재 → event_logs/룰엔진 가시성 확보. 별도 항목으로 분리 가능.

### 추가 테스트 (tests/test_strategy/test_risk.py)
- `test_take_profit_then_stop_loss_no_halt_when_net_positive`: +39,440 기록 후 -24,300 기록 → `is_portfolio_halted is False` (오늘 회귀 케이스).
- `test_drawdown_halt_triggers_when_net_negative`: 순손실 상태에서 피크 대비 회수폭이 한도 초과 → `is_portfolio_halted is True`, `halt_reason == "MAX_DAILY_DRAWDOWN"` (기존 의도 보존).
- `test_consecutive_loss_halt_unaffected`: 연패 한도 halt 경로는 본 변경의 영향을 받지 않음.

## 기대 효과
- "첫 익절 → 손절" 시퀀스에 의한 흑자 상태 조기 halt 제거. 오늘 같은 날 정상적으로 장중 매매 지속(추정 600~700사이클 정상화).
- 일일 손실 한도는 실제 순손실 구간에서 정상 작동(취지 유지).
- BUY_REJECT/system_metrics에 halt가 잡히면 모니터링 사각지대 해소.

## 롤백
- `src/strategy/risk.py`의 가드 조건을 원복(`git restore src/strategy/risk.py`).
- 추가 테스트 제거. config 변경 없음(`config_overrides.json` 무관).
- 안전 지점 태그(`git tag -l 'v*'`)로 되돌릴 수 있음.
