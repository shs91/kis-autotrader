"""리스크 관리 모듈."""

from __future__ import annotations

from datetime import datetime

from src.config import settings
from src.strategy.base import Signal, SignalType
from src.utils.exceptions import RiskLimitError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)



class RiskManager:
    """리스크 관리를 수행하는 클래스.

    최대 손실률, 포지션 사이징, 일일 매매 횟수 제한 등
    매매 리스크를 종합적으로 관리한다.

    설정값은 src/config.py의 settings.trading에서 가져온다.
    """

    def __init__(
        self,
        max_loss_rate: float | None = None,
        max_position_ratio: float | None = None,
        daily_trade_limit: int | None = None,
        take_profit_ratio: float | None = None,
        trailing_activation_ratio: float | None = None,
        trailing_drawdown_ratio: float | None = None,
        min_profitable_close: float | None = None,
    ) -> None:
        """리스크 관리자를 초기화한다.

        Args:
            max_loss_rate: 최대 손실률 (None이면 설정값 사용, 기본 3%)
            max_position_ratio: 최대 포지션 비율 (None이면 설정값 사용, 기본 20%)
            daily_trade_limit: 일일 매매 횟수 제한 (None이면 설정값 사용, 기본 10건)
            take_profit_ratio: 익절 비율 (기본 5%)
            trailing_activation_ratio: 트레일링 무장 임계 (기본 5%)
            trailing_drawdown_ratio: 트레일링 매도폭 (기본 5%)
            min_profitable_close: 마감 청산 수익률 임계 (기본 1.5%)
        """
        self._max_loss_rate = (
            max_loss_rate
            if max_loss_rate is not None
            else settings.trading.max_loss_rate
        )
        self._max_position_ratio = (
            max_position_ratio
            if max_position_ratio is not None
            else settings.trading.max_position_ratio
        )
        self._daily_trade_limit = (
            daily_trade_limit
            if daily_trade_limit is not None
            else settings.trading.daily_trade_limit
        )
        self._take_profit_ratio = (
            take_profit_ratio
            if take_profit_ratio is not None
            else settings.strategy.take_profit_ratio
        )
        self._trailing_activation_ratio = (
            trailing_activation_ratio
            if trailing_activation_ratio is not None
            else settings.strategy.trailing_activation_ratio
        )
        self._trailing_drawdown_ratio = (
            trailing_drawdown_ratio
            if trailing_drawdown_ratio is not None
            else settings.strategy.trailing_drawdown_ratio
        )
        self._min_profitable_close = (
            min_profitable_close
            if min_profitable_close is not None
            else settings.strategy.min_profitable_close
        )
        self._min_confidence = settings.strategy.min_confidence

        # 포트폴리오 리스크 추적
        self._max_daily_drawdown = settings.trading.max_daily_drawdown
        self._max_consecutive_losses = settings.trading.max_consecutive_losses
        self._daily_peak_pnl: int = 0
        self._daily_cumulative_pnl: int = 0
        self._consecutive_losses: int = 0
        self._portfolio_halted: bool = False
        # halt 발동 사유 — BUY_REJECT 메트릭의 reason 코드 분류용
        self._halt_reason: str | None = None

    def record_trade_result(self, profit_loss_amount: int) -> None:
        """매도 결과를 기록하여 포트폴리오 리스크를 업데이트한다.

        Args:
            profit_loss_amount: 실현 손익 (원)
        """
        self._daily_cumulative_pnl += profit_loss_amount

        if self._daily_cumulative_pnl > self._daily_peak_pnl:
            self._daily_peak_pnl = self._daily_cumulative_pnl

        # 연패 추적
        if profit_loss_amount < 0:
            self._consecutive_losses += 1
        elif profit_loss_amount > 0:
            self._consecutive_losses = 0

        # 포트폴리오 MDD 체크
        # 순손실 가드(proposal 2026-05-21, 안 a): 피크 대비 회수폭이 한도를 넘더라도
        # 당일 누적이 순손실(<0)일 때만 halt한다. 분모가 '실현이익 피크'라 장 초반
        # 작은 피크 직후 정상 손절 1건만으로 비율이 폭증해 흑자 상태에서 매매를
        # 봉인하던 오발동(첫 익절 → 손절 시퀀스)을 제거한다.
        drawdown = self._daily_peak_pnl - self._daily_cumulative_pnl
        if self._daily_peak_pnl > 0 and self._daily_cumulative_pnl < 0:
            drawdown_pct = drawdown / self._daily_peak_pnl
            if drawdown_pct >= self._max_daily_drawdown:
                self._portfolio_halted = True
                if self._halt_reason is None:
                    self._halt_reason = "MAX_DAILY_DRAWDOWN"
                logger.warning(
                    "포트폴리오 MDD 한도 도달: %.1f%% >= %.1f%% (피크 %d → 현재 %d)",
                    drawdown_pct * 100,
                    self._max_daily_drawdown * 100,
                    self._daily_peak_pnl,
                    self._daily_cumulative_pnl,
                )

        # 연패 체크
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._portfolio_halted = True
            if self._halt_reason is None:
                self._halt_reason = "MAX_CONSECUTIVE_LOSSES"
            logger.warning(
                "연속 손실 한도 도달: %d연패 >= %d",
                self._consecutive_losses,
                self._max_consecutive_losses,
            )

    @property
    def is_portfolio_halted(self) -> bool:
        """포트폴리오 리스크로 인한 매매 중단 여부."""
        return self._portfolio_halted

    @property
    def consecutive_losses(self) -> int:
        """현재 연속 손실 횟수."""
        return self._consecutive_losses

    @property
    def daily_cumulative_pnl(self) -> int:
        """당일 누적 손익."""
        return self._daily_cumulative_pnl

    def reset_daily_risk(self) -> None:
        """일일 리스크 카운터를 초기화한다 (장 시작 시 호출)."""
        self._daily_peak_pnl = 0
        self._daily_cumulative_pnl = 0
        self._consecutive_losses = 0
        self._portfolio_halted = False
        self._halt_reason = None

    def is_near_market_close(self, now: datetime | None = None) -> bool:
        """장 마감 임박 여부를 판단한다.

        Returns:
            True이면 MARKET_CLOSE_CUTOFF 이후 (기본 14:30)
        """
        now = now or datetime.now()
        cutoff_hour = settings.trading.market_close_cutoff_hour
        cutoff_minute = settings.trading.market_close_cutoff_minute
        return (now.hour > cutoff_hour) or (
            now.hour == cutoff_hour and now.minute >= cutoff_minute
        )

    def check_max_loss(self, current_price: float, avg_price: float) -> bool:
        """최대 손실률 초과 여부를 확인한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가

        Returns:
            True이면 손실률이 최대 손실률을 초과한 것

        Raises:
            RiskLimitError: 최대 손실률을 초과한 경우
        """
        if avg_price <= 0:
            raise RiskLimitError("평균 매입가는 0보다 커야 합니다.")

        loss_rate = (avg_price - current_price) / avg_price

        if loss_rate > self._max_loss_rate:
            logger.warning(
                "최대 손실률 초과: 현재 %.2f%% > 제한 %.2f%%",
                loss_rate * 100,
                self._max_loss_rate * 100,
            )
            return True

        return False

    def calculate_position_size(self, total_balance: float, price: float) -> int:
        """포지션 크기(매수 가능 수량)를 계산한다.

        계좌 잔고 대비 최대 포지션 비율을 적용하여
        매수 가능한 최대 수량을 반환한다.

        Args:
            total_balance: 총 계좌 잔고
            price: 현재 주가

        Returns:
            매수 가능 수량 (정수)

        Raises:
            RiskLimitError: 잔고 또는 가격이 유효하지 않은 경우
        """
        if total_balance <= 0:
            raise RiskLimitError("계좌 잔고는 0보다 커야 합니다.")
        if price <= 0:
            raise RiskLimitError("주가는 0보다 커야 합니다.")

        max_investment = total_balance * self._max_position_ratio
        quantity = int(max_investment / price)

        logger.info(
            "포지션 사이징: 잔고 %.0f, 주가 %.0f, 최대투자금 %.0f, 수량 %d",
            total_balance,
            price,
            max_investment,
            quantity,
        )

        return quantity

    def check_daily_trade_limit(self, trade_count: int) -> bool:
        """일일 매매 횟수 제한 초과 여부를 확인한다.

        Args:
            trade_count: 당일 매매 횟수

        Returns:
            True이면 제한을 초과한 것

        Raises:
            RiskLimitError: 일일 매매 횟수 제한을 초과한 경우
        """
        if trade_count >= self._daily_trade_limit:
            logger.warning(
                "일일 매매 횟수 제한 초과: %d >= %d",
                trade_count,
                self._daily_trade_limit,
            )
            return True

        return False

    def should_stop_loss(self, current_price: float, avg_price: float) -> bool:
        """손절 여부를 판단한다.

        현재가가 평균 매입가 대비 최대 손실률 이상 하락하면 손절한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가

        Returns:
            True이면 손절해야 함
        """
        if avg_price <= 0:
            return False

        loss_rate = (avg_price - current_price) / avg_price
        should_stop = loss_rate >= self._max_loss_rate

        if should_stop:
            logger.warning(
                "손절 시그널: 손실률 %.2f%% >= 제한 %.2f%%",
                loss_rate * 100,
                self._max_loss_rate * 100,
            )

        return should_stop

    def should_take_profit(
        self,
        current_price: float,
        avg_price: float,
        profit_ratio: float | None = None,
    ) -> bool:
        """익절 여부를 판단한다.

        현재가가 평균 매입가 대비 익절 비율 이상 상승하면 익절한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가
            profit_ratio: 익절 비율 (None이면 기본값 사용)

        Returns:
            True이면 익절해야 함
        """
        if avg_price <= 0:
            return False

        target_ratio = profit_ratio if profit_ratio is not None else self._take_profit_ratio

        # 장 마감 임박 시 익절 기준 절반으로 하향 (빠른 실현)
        if self.is_near_market_close():
            target_ratio = target_ratio * 0.5

        current_profit = (current_price - avg_price) / avg_price
        should_profit = current_profit >= target_ratio

        if should_profit:
            logger.info(
                "익절 시그널: 수익률 %.2f%% >= 목표 %.2f%%%s",
                current_profit * 100,
                target_ratio * 100,
                " (마감임박 조정)" if self.is_near_market_close() else "",
            )

        return should_profit

    def should_trailing_stop(
        self, current_price: float, avg_price: float, peak_price: float
    ) -> bool:
        """고점 대비 되돌림 청산 여부를 판단한다 (시간 무관).

        무장 조건: 고점이 평균단가 대비 활성화 임계 이상 상승.
        청산 조건: 무장 상태 AND 현재가가 고점 대비 매도폭 이상 하락.
        peak_price는 호출자(engine)가 보존·전달한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가
            peak_price: 보유 후 도달한 최고가

        Returns:
            True이면 트레일링 스톱 청산
        """
        if avg_price <= 0 or peak_price <= 0:
            return False

        peak_profit = (peak_price - avg_price) / avg_price
        if peak_profit < self._trailing_activation_ratio:
            return False  # 미무장

        drawdown = (peak_price - current_price) / peak_price
        should = drawdown >= self._trailing_drawdown_ratio
        if should:
            logger.info(
                "트레일링 시그널: 고점 %.0f 대비 %.2f%% 하락 >= %.2f%% (현재 %.0f)",
                peak_price, drawdown * 100,
                self._trailing_drawdown_ratio * 100, current_price,
            )
        return should

    def should_close_for_market_end(
        self,
        current_price: float,
        avg_price: float,
        now: datetime | None = None,
    ) -> bool:
        """마감 임박 강제 청산 게이트 — 이익 포지션 한정.

        트레일링과 독립된 별도 규칙. 시간 의존은 이 게이트의 발동 조건뿐이며,
        손실 포지션(수익률 < min_profitable_close)은 대상에서 제외한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가
            now: 판정 기준 시각 (None이면 현재 시각)

        Returns:
            True이면 마감 임박 + 최소 수익률 충족으로 청산
        """
        if avg_price <= 0:
            return False
        if not self.is_near_market_close(now):
            return False

        profit = (current_price - avg_price) / avg_price
        should = profit >= self._min_profitable_close
        if should:
            logger.info(
                "마감 청산 게이트: 수익률 %.2f%% >= %.2f%% (마감 임박)",
                profit * 100, self._min_profitable_close * 100,
            )
        return should

    # ── 매수 게이트 진단 (proposal 2026-05-18 + 사유 코드 정밀화) ──
    #
    # ``check_buy_gates``는 매수 시그널에 대한 모든 게이트를 평가해 첫번째로
    # 트립된 사유 코드를 반환한다. 호출자는 이 코드를 ``BUY_REJECT`` 메트릭
    # ``reason`` 필드에 그대로 적재한다. ``validate_order``의 책임을 흡수했고,
    # validate_order는 deprecate (하위 호환 시그니처만 유지).
    #
    # 반환 규약:
    # - ``None``   : 모든 게이트 통과 (매수 진행 가능)
    # - 문자열     : 첫번째로 트립된 게이트 사유 코드
    #
    # 게이트 평가 순서 (절대성 강한 것부터):
    #   1) ``MAX_CONSECUTIVE_LOSSES`` (포트폴리오 halt: 연패 한도)
    #      ``MAX_DAILY_DRAWDOWN``     (포트폴리오 halt: MDD 한도)
    #   2) ``MARKET_CLOSE_GUARD``     (장 마감 임박 — 시간 절대 차단)
    #   3) ``INSUFFICIENT_CASH``      (balance <= 0 또는 target_price > balance)
    #   4) ``LOW_CONFIDENCE``         (signal.confidence < min_confidence)
    #
    # BUY 시그널에 한해서만 사유를 반환하고, HOLD/SELL 시그널은 None.
    # 호출자(engine)는 BUY 시그널 경로에서 본 메서드를 호출하고 None일 때만
    # 매수를 진행한다.

    def check_buy_gates(
        self,
        signal: Signal,
        balance: float,
    ) -> str | None:
        """매수 시그널에 대해 게이트 검증을 수행하고 거절 사유 코드를 반환한다.

        Args:
            signal: 매매 시그널 (signal_type=BUY 가정).
            balance: 가용 잔고.

        Returns:
            거절 사유 코드 문자열 또는 None(모든 게이트 통과).
            반환 가능한 코드:

            - ``"MAX_CONSECUTIVE_LOSSES"`` : 연패 한도 도달로 halt
            - ``"MAX_DAILY_DRAWDOWN"``     : MDD 한도 도달로 halt
            - ``"MARKET_CLOSE_GUARD"``     : 장 마감 임박 (신규 매수 차단)
            - ``"INSUFFICIENT_CASH"``      : 잔고 부족
            - ``"LOW_CONFIDENCE"``         : 시그널 신뢰도 미달
        """
        if signal.signal_type != SignalType.BUY:
            return None

        # 1) 포트폴리오 리스크 halt — 구체 사유 코드로 매핑
        if self._portfolio_halted:
            return self._halt_reason or "MAX_CONSECUTIVE_LOSSES"

        # 2) 장 마감 임박 (시간 절대 차단)
        if self.is_near_market_close():
            return "MARKET_CLOSE_GUARD"

        # 3) 잔고 부족
        if balance <= 0:
            return "INSUFFICIENT_CASH"
        if signal.target_price is not None and signal.target_price > balance:
            return "INSUFFICIENT_CASH"

        # 4) 저신뢰도
        if signal.confidence < self._min_confidence:
            return "LOW_CONFIDENCE"

        return None

    def validate_order(
        self,
        signal: Signal,
        balance: float,
        current_positions: int,
    ) -> bool:
        """주문 유효성을 종합적으로 검증한다.

        매수 시그널인 경우:
        - 잔고가 충분한지 확인
        - 포지션 비율 제한 확인

        Args:
            signal: 매매 시그널
            balance: 가용 잔고
            current_positions: 현재 보유 종목 수

        Returns:
            True이면 주문이 유효함

        Raises:
            RiskLimitError: 주문이 유효하지 않은 경우
        """
        # HOLD 시그널은 주문 불필요
        if signal.signal_type == SignalType.HOLD:
            return False

        # 장 마감 임박 시 신규 매수 차단
        if signal.signal_type == SignalType.BUY and self.is_near_market_close():
            logger.info("장 마감 임박으로 신규 매수 차단")
            return False

        # 매수 시 잔고 확인
        if signal.signal_type == SignalType.BUY:
            if balance <= 0:
                raise RiskLimitError("가용 잔고가 부족합니다.")

            if signal.target_price is not None and signal.target_price > balance:
                raise RiskLimitError(
                    f"잔고 부족: 필요 {signal.target_price:.0f}, 가용 {balance:.0f}"
                )

        # 신뢰도가 너무 낮은 시그널은 거부
        if signal.confidence < self._min_confidence:
            logger.info(
                "낮은 신뢰도로 주문 거부: %.2f < %.2f",
                signal.confidence,
                self._min_confidence,
            )
            return False

        logger.info(
            "주문 검증 통과: %s, 신뢰도 %.2f, 잔고 %.0f",
            signal.signal_type.value,
            signal.confidence,
            balance,
        )

        return True
