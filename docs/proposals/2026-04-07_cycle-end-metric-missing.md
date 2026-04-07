# 사이클 조기종료 시 CYCLE_END 메트릭 누락 수정

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-07
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py

## 현상 분석

2026-04-07 DB 데이터에서 CYCLE_START 2,271건 vs CYCLE_END 1,724건으로 **547건(24.1%)의 CYCLE_END가 누락**됨.

`src/engine.py`의 `run_trading_cycle()` 메서드에서 CYCLE_START를 기록한 뒤 조기 return하는 경로가 5곳 있으며, 이 경로들에서 CYCLE_END를 기록하지 않음:

1. **290~292행**: 일일 매매 횟수 한도 도달 시 return
2. **298~300행**: 스크리닝 중 DailyLimitExceededError 시 return
3. **304~307행**: 잔고 조회 중 DailyLimitExceededError 시 return
4. **308~310행**: 잔고 조회 실패(기타 예외) 시 return
5. **327~329행**: 종목 처리 중 DailyLimitExceededError 시 return

이로 인해:
- 사이클 완료율을 정확히 측정할 수 없음 (미완료 vs 조기종료 구분 불가)
- 일일 리포트의 "사이클 실행/스킵" 집계가 부정확
- 시스템 건강도 모니터링 지표 왜곡

## 제안 내용

`run_trading_cycle()` 메서드에 try/finally 패턴을 적용하여, 정상 완료든 조기 종료든 항상 CYCLE_END 메트릭을 기록하도록 수정. 조기 종료 시에는 `exit_reason` 필드를 추가하여 종료 사유를 명시.

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:

**변경 전** (273~358행 — `run_trading_cycle` 메서드 전체):
```python
    async def run_trading_cycle(self) -> None:
        """장중 매매 사이클 1회 실행."""
        self._cycle_count += 1

        # 일일 한도 초과 시 이후 사이클 전부 즉시 중단
        if self._daily_limit_reached:
            return

        logger.info("--- 장중 매매 사이클 #%d 시작 ---", self._cycle_count)
        limiter = self._client._limiter
        self._record_metric("CYCLE_START", {
            "cycle": self._cycle_count,
            "api_calls": limiter.daily_count,
            "api_limit": limiter.daily_limit,
            "trade_count": self._today_trade_count,
        })

        if self._risk.check_daily_trade_limit(self._today_trade_count):
            logger.warning("일일 매매 횟수 한도 도달, 사이클 스킵")
            return

        # 주기적 스크리닝 (N사이클마다)
        if self._cycle_count % SCREENING_INTERVAL_CYCLES == 0:
            try:
                await self._screen_stocks()
            except DailyLimitExceededError:
                await self._set_daily_limit_reached()
                return

        try:
            balance = await self._get_balance()
        except DailyLimitExceededError:
            self._daily_limit_reached = True
            logger.warning("API 일일 한도 초과, 당일 매매 사이클 중단")
            return
        except Exception:
            logger.exception("잔고 조회 실패, 사이클 스킵")
            return

        held_codes = {h.stock_code for h in balance.holdings if h.quantity > 0}
        targets = self._build_monitor_targets(held_codes)
        logger.info(
            "모니터링 대상: %d종목 (보유 %d + 관심 %d + 발굴 %d)",
            len(targets),
            len(held_codes),
            len(self._get_watchlist_codes()),
            len(self._screened_codes),
        )

        for stock_code in targets:
            try:
                is_held = stock_code in held_codes
                holding_info = self._find_holding_from_balance(balance, stock_code)
                await self._process_stock(stock_code, balance.deposit, is_held, holding_info)
            except DailyLimitExceededError:
                await self._set_daily_limit_reached()
                return
            except Exception:
                logger.exception("종목 처리 중 에러: %s", stock_code)
                self._record_metric("ERROR", {
                    "cycle": self._cycle_count,
                    "stock_code": stock_code,
                    "error": "종목 처리 실패",
                })

        limiter = self._client._limiter
        self._record_metric("CYCLE_END", {
            "cycle": self._cycle_count,
            "trade_count": self._today_trade_count,
            "api_calls": limiter.daily_count,
            "api_limit": limiter.daily_limit,
            "monitor_stocks": len(targets),
            "held_stocks": len(held_codes),
            "screened_stocks": len(self._screened_codes),
        })
        logger.info(
            "--- 사이클 #%d 완료 — 매매 %d건, API %d/%d, "
            "모니터링 %d종목(보유 %d/발굴 %d) ---",
            self._cycle_count,
            self._today_trade_count,
            limiter.daily_count,
            limiter.daily_limit,
            len(targets),
            len(held_codes),
            len(self._screened_codes),
        )
```

**변경 후**:
```python
    async def run_trading_cycle(self) -> None:
        """장중 매매 사이클 1회 실행."""
        self._cycle_count += 1

        # 일일 한도 초과 시 이후 사이클 전부 즉시 중단
        if self._daily_limit_reached:
            return

        logger.info("--- 장중 매매 사이클 #%d 시작 ---", self._cycle_count)
        limiter = self._client._limiter
        self._record_metric("CYCLE_START", {
            "cycle": self._cycle_count,
            "api_calls": limiter.daily_count,
            "api_limit": limiter.daily_limit,
            "trade_count": self._today_trade_count,
        })

        exit_reason: str = "completed"
        held_codes: set[str] = set()
        targets: list[str] = []
        try:
            if self._risk.check_daily_trade_limit(self._today_trade_count):
                logger.warning("일일 매매 횟수 한도 도달, 사이클 스킵")
                exit_reason = "trade_limit"
                return

            # 주기적 스크리닝 (N사이클마다)
            if self._cycle_count % SCREENING_INTERVAL_CYCLES == 0:
                try:
                    await self._screen_stocks()
                except DailyLimitExceededError:
                    await self._set_daily_limit_reached()
                    exit_reason = "api_limit_screening"
                    return

            try:
                balance = await self._get_balance()
            except DailyLimitExceededError:
                self._daily_limit_reached = True
                logger.warning("API 일일 한도 초과, 당일 매매 사이클 중단")
                exit_reason = "api_limit_balance"
                return
            except Exception:
                logger.exception("잔고 조회 실패, 사이클 스킵")
                exit_reason = "balance_error"
                return

            held_codes = {h.stock_code for h in balance.holdings if h.quantity > 0}
            targets = self._build_monitor_targets(held_codes)
            logger.info(
                "모니터링 대상: %d종목 (보유 %d + 관심 %d + 발굴 %d)",
                len(targets),
                len(held_codes),
                len(self._get_watchlist_codes()),
                len(self._screened_codes),
            )

            for stock_code in targets:
                try:
                    is_held = stock_code in held_codes
                    holding_info = self._find_holding_from_balance(balance, stock_code)
                    await self._process_stock(stock_code, balance.deposit, is_held, holding_info)
                except DailyLimitExceededError:
                    await self._set_daily_limit_reached()
                    exit_reason = "api_limit_processing"
                    return
                except Exception:
                    logger.exception("종목 처리 중 에러: %s", stock_code)
                    self._record_metric("ERROR", {
                        "cycle": self._cycle_count,
                        "stock_code": stock_code,
                        "error": "종목 처리 실패",
                    })
        finally:
            limiter = self._client._limiter
            self._record_metric("CYCLE_END", {
                "cycle": self._cycle_count,
                "exit_reason": exit_reason,
                "trade_count": self._today_trade_count,
                "api_calls": limiter.daily_count,
                "api_limit": limiter.daily_limit,
                "monitor_stocks": len(targets),
                "held_stocks": len(held_codes),
                "screened_stocks": len(self._screened_codes),
            })
            logger.info(
                "--- 사이클 #%d %s — 매매 %d건, API %d/%d, "
                "모니터링 %d종목(보유 %d/발굴 %d) ---",
                self._cycle_count,
                "완료" if exit_reason == "completed" else f"조기종료({exit_reason})",
                self._today_trade_count,
                limiter.daily_count,
                limiter.daily_limit,
                len(targets),
                len(held_codes),
                len(self._screened_codes),
            )
```

**핵심 변경 요약**:
1. CYCLE_START 이후의 전체 로직을 `try/finally` 블록으로 감싸 CYCLE_END가 항상 기록되도록 변경
2. `exit_reason` 변수 추가 — 조기종료 사유를 CYCLE_END 메트릭의 `exit_reason` 필드에 기록
3. `held_codes`와 `targets`를 try 블록 바깥에서 초기화하여 finally에서 안전하게 참조 가능
4. 로그 메시지에 조기종료 사유 포함

### 추가 테스트 (필요 시)

기존 `tests/test_engine.py`에 사이클 조기종료 시 CYCLE_END 기록 검증 테스트 추가:
- 테스트명: `test_cycle_end_recorded_on_early_exit`
- 내용: `_risk.check_daily_trade_limit`가 True를 반환할 때 CYCLE_END 메트릭이 `exit_reason="trade_limit"`으로 기록되는지 확인

## 기대 효과

- CYCLE_START와 CYCLE_END 건수 1:1 대응 → 사이클 완료율 100% (미완료 = 0)
- `exit_reason` 필드로 조기종료 원인 정량 분석 가능 (trade_limit, api_limit, balance_error 등)
- 일일 리포트에서 "사이클 실행/완료/조기종료(사유별)" 정밀 집계 가능
- 시스템 건강도 모니터링 지표 정확도 향상

## 롤백

- `git restore src/engine.py`
- CYCLE_END 메트릭 구조 변경(exit_reason 필드 추가)은 DB 스키마 변경 없음 (JSONB detail 컬럼)
