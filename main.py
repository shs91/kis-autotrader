"""KIS 주식 자동매매 시스템 엔트리포인트."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import date, timedelta

from sqlalchemy import case as sa_case
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from src.api.health import HealthServer
from src.config import settings
from src.db.analytics import (
    get_daily_errors,
    get_daily_screening,
    get_daily_trades,
    get_optimal_risk_params,
    get_signal_accuracy,
)
from src.db.event_logger import log_system
from src.db.models import Signal as SignalModel
from src.db.models import SystemMetric, Trade, TradeType
from src.db.repository import WatchlistRepository
from src.db.session import get_session, init_db
from src.engine import TradingEngine
from src.harness.telegram_commands import (
    cmd_pause_implement,
    cmd_run_implement,
    cmd_status_implement,
)
from src.notify.bot import TelegramBot
from src.notify.telegram import TelegramNotifier
from src.scheduler.jobs import TradingScheduler
from src.utils.logger import setup_logger
from src.worker.handlers import (
    CalendarEventHandler,
    DailyPerformanceHandler,
    DailySummaryHandler,
    RecordMetricHandler,
    RecordSignalHandler,
    RecordTradeHandler,
    SyncPortfolioHandler,
    TelegramNotifyHandler,
)
from src.worker.runner import WorkerRunner
from src.worker.screener import ScreeningWorker

logger = setup_logger(__name__)


def _register_bot_commands(
    bot: TelegramBot,
    engine: TradingEngine,
    scheduler: TradingScheduler,
    notifier: TelegramNotifier,
) -> None:
    """Telegram 봇 명령을 등록한다."""

    async def cmd_status(_args: str) -> str:
        """시스템 상태를 반환한다 (DB 기반)."""
        limiter = engine._client._limiter
        running = scheduler.scheduler.running

        try:
            from datetime import datetime as dt_cls
            today = date.today()
            start = dt_cls(today.year, today.month, today.day)
            with get_session() as session:
                cycle_cnt = session.execute(
                    sa_select(sa_func.count()).select_from(SystemMetric)
                    .where(
                        SystemMetric.metric_type == "CYCLE_START",
                        SystemMetric.recorded_at >= start,
                    )
                ).scalar_one()
                error_cnt = session.execute(
                    sa_select(sa_func.count()).select_from(SystemMetric)
                    .where(
                        SystemMetric.metric_type == "ERROR",
                        SystemMetric.recorded_at >= start,
                    )
                ).scalar_one()
                trade_cnt = session.execute(
                    sa_select(sa_func.count()).select_from(Trade)
                    .where(Trade.traded_at >= start)
                ).scalar_one()

                # 최신 CYCLE_END에서 API 호출, 모니터링 상세
                last_cycle = session.execute(
                    sa_select(SystemMetric)
                    .where(
                        SystemMetric.metric_type == "CYCLE_END",
                        SystemMetric.recorded_at >= start,
                    )
                    .order_by(SystemMetric.recorded_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

            # 최신 사이클 상세
            if last_cycle and last_cycle.detail:
                d = last_cycle.detail
                api_calls = d.get("api_calls", limiter.daily_count)
                api_limit = d.get("api_limit", limiter.daily_limit)
                monitor = d.get("monitor_stocks", "?")
                held = d.get("held_stocks", "?")
                screened = d.get("screened_stocks", "?")
                last_cycle_num = d.get("cycle", "?")
                cycle_detail = (
                    f"최근 사이클: #{last_cycle_num}\n"
                    f"API 호출: {api_calls:,}/{api_limit:,}\n"
                    f"모니터링: {monitor}종목"
                    f" (보유 {held} + 발굴 {screened})"
                )
            else:
                cycle_detail = (
                    f"API 호출: {limiter.daily_count:,}"
                    f"/{limiter.daily_limit:,}"
                )

            return (
                f"<b>[상태]</b>\n"
                f"환경: {settings.kis.env}\n"
                f"스케줄러: {'가동중' if running else '중지'}\n"
                f"사이클: {cycle_cnt}회\n"
                f"매매: {trade_cnt}건\n"
                f"에러: {error_cnt}건\n"
                f"{cycle_detail}"
            )
        except Exception:
            # DB 실패 시 메모리 폴백
            return (
                f"<b>[상태]</b>\n"
                f"환경: {settings.kis.env}\n"
                f"스케줄러: {'가동중' if running else '중지'}\n"
                f"사이클: #{engine._cycle_count}\n"
                f"API 호출: {limiter.daily_count:,}"
                f"/{limiter.daily_limit:,}\n"
                f"당일 매매: {engine._today_trade_count}건\n"
                f"(DB 조회 실패, 메모리 기준)"
            )

    async def cmd_balance(_args: str) -> str:
        """잔고를 조회한다."""
        try:
            balance = await engine._get_balance()
            lines = [
                "<b>[잔고]</b>",
                f"예수금: {balance.deposit:,}원",
                f"평가손익: {balance.total_profit_loss:,}원 ({balance.total_profit_rate:.2f}%)",
            ]
            for h in balance.holdings[:10]:
                lines.append(
                    f"  {h.stock_name}({h.stock_code}) {h.quantity}주 {h.profit_rate:+.2f}%"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"잔고 조회 실패: {e!s:.100}"

    async def cmd_today(_args: str) -> str:
        """당일 매매 요약을 반환한다 (DB 기반)."""
        try:
            today = date.today()
            with get_session() as session:
                trades = get_daily_trades(session, today)
                errors = get_daily_errors(session, today)
                screening = get_daily_screening(session, today)

            buys = [t for t in trades if t["trade_type"] == "BUY"]
            sells = [t for t in trades if t["trade_type"] == "SELL"]
            total_pnl = sum(t["profit_loss_amount"] or 0 for t in sells)
            wins = sum(
                1 for t in sells
                if t["profit_loss_amount"] is not None and t["profit_loss_amount"] > 0
            )
            win_rate = (wins / len(sells) * 100) if sells else 0

            lines = [
                f"<b>[당일 현황]</b> {today}",
                f"매수: {len(buys)}건 / 매도: {len(sells)}건",
                f"실현손익: {total_pnl:+,}원 (승률 {win_rate:.0f}%)",
                f"스크리닝: {screening['total_screened']}건"
                f" → 전환 {screening['converted_count']}건",
                f"에러: {errors['total_errors']}건",
                f"관심종목: {len(engine._get_watchlist_codes())}개",
                f"발굴종목: {len(engine._screened_codes)}개",
                f"한도 초과: {'예' if engine._daily_limit_reached else '아니오'}",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 당일 현황 조회 실패: {e!s:.100}"

    async def cmd_watch(args: str) -> str:
        """관심종목을 추가한다."""
        stock_code = args.strip()
        if not stock_code:
            return "사용법: /watch 005930"
        if len(stock_code) != 6 or not stock_code.isdigit():
            return f"잘못된 종목코드: {stock_code} (6자리 숫자)"
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                added = repo.add(stock_code)
            if added:
                return f"✅ {stock_code} 관심종목에 추가했습니다."
            return f"ℹ️ {stock_code}은(는) 이미 관심종목입니다."
        except Exception as e:
            return f"❌ 추가 실패: {e!s:.100}"

    async def cmd_unwatch(args: str) -> str:
        """관심종목에서 제거한다."""
        stock_code = args.strip()
        if not stock_code:
            return "사용법: /unwatch 005930"
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                removed = repo.remove(stock_code)
            if removed:
                return f"✅ {stock_code} 관심종목에서 제거했습니다."
            return f"ℹ️ {stock_code}은(는) 관심종목이 아닙니다."
        except Exception as e:
            return f"❌ 제거 실패: {e!s:.100}"

    async def cmd_watchlist(_args: str) -> str:
        """관심종목 목록을 반환한다."""
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                codes = repo.get_codes()
            if not codes:
                return "관심종목이 없습니다."
            return f"<b>[관심종목]</b> ({len(codes)}건)\n" + ", ".join(codes)
        except Exception as e:
            return f"❌ 조회 실패: {e!s:.100}"

    async def cmd_trades(_args: str) -> str:
        """당일 체결 상세를 반환한다."""
        try:
            with get_session() as session:
                trades = get_daily_trades(session, date.today())
            if not trades:
                return "<b>[당일 체결]</b> 체결 내역 없음"

            buys = [t for t in trades if t["trade_type"] == "BUY"]
            sells = [t for t in trades if t["trade_type"] == "SELL"]
            total_pnl = sum(t["profit_loss_amount"] or 0 for t in sells)

            lines = [
                f"<b>[당일 체결]</b> {date.today()}",
                f"매수 {len(buys)}건 / 매도 {len(sells)}건"
                f" / 실현손익 {total_pnl:+,}원",
                "",
            ]
            for t in trades[-15:]:  # 최근 15건
                base = (
                    f"{t['stock_name']}({t['stock_code']}) "
                    f"{t['trade_type']} {t['quantity']}주 "
                    f"@{t['price']:,}"
                )
                if t["trade_type"] == "SELL" and t["sell_reason"]:
                    reason = {
                        "STOP_LOSS": "손절",
                        "TAKE_PROFIT": "익절",
                        "STRATEGY": "전략",
                        "MANUAL": "수동",
                    }.get(t["sell_reason"], t["sell_reason"])
                    pct = t["profit_loss_pct"]
                    pct_str = f" {pct:+.2f}%" if pct is not None else ""
                    base += f" {reason}{pct_str}"
                lines.append(base)

            if len(trades) > 15:
                lines.append(f"... 외 {len(trades) - 15}건")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 체결 조회 실패: {e!s:.100}"

    async def cmd_pnl(args: str) -> str:
        """기간 손익 요약을 반환한다."""
        try:
            days_str = args.strip()
            days = int(days_str) if days_str else 7
            days = max(1, min(days, 90))

            with get_session() as session:
                since = date.today() - timedelta(days=days)
                rows = session.execute(
                    sa_select(
                        sa_func.cast(
                            sa_func.date_trunc('day', Trade.traded_at),
                            Trade.traded_at.type,
                        ).label("day"),
                        sa_func.coalesce(
                            sa_func.sum(Trade.profit_loss_amount),
                            0,
                        ).label("pnl"),
                    )
                    .where(
                        Trade.traded_at >= since,
                        Trade.trade_type == TradeType.SELL,
                    )
                    .group_by("day")
                    .order_by("day")
                ).all()

            if not rows:
                return f"<b>[손익]</b> 최근 {days}일 매도 내역 없음"

            daily = [(r.day, int(r.pnl)) for r in rows]
            total = sum(pnl for _, pnl in daily)
            wins = sum(1 for _, pnl in daily if pnl > 0)
            losses = sum(1 for _, pnl in daily if pnl < 0)
            best = max(daily, key=lambda x: x[1])
            worst = min(daily, key=lambda x: x[1])
            win_rate = (wins / len(daily) * 100) if daily else 0

            lines = [
                f"<b>[손익 요약]</b> 최근 {days}일",
                f"총 실현손익: {total:+,}원",
                f"승률: {win_rate:.0f}% ({wins}승 {losses}패)",
                f"최대 수익: {best[1]:+,} ({best[0].strftime('%m/%d')})",
                f"최대 손실: {worst[1]:+,} ({worst[0].strftime('%m/%d')})",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 손익 조회 실패: {e!s:.100}"

    async def cmd_signals(_args: str) -> str:
        """당일 시그널 현황을 반환한다."""
        try:
            with get_session() as session:
                accuracy = get_signal_accuracy(session, date.today())

            total = accuracy["total_signals"]
            if total == 0:
                return "<b>[시그널]</b> 당일 시그널 없음"

            acted = accuracy["acted_count"]
            confirmed = accuracy["confirmed_count"]
            acc_rate = accuracy["accuracy_rate"]

            # 유형별 상세
            with get_session() as session:
                from datetime import datetime as dt_cls
                today = date.today()
                start = dt_cls(today.year, today.month, today.day)
                end = start + timedelta(days=1)
                rows = session.execute(
                    sa_select(
                        SignalModel.signal_type,
                        sa_func.count().label("cnt"),
                        sa_func.sum(sa_case(
                            (SignalModel.action_taken.is_(True), 1),
                            else_=0,
                        )).label("acted"),
                        sa_func.round(
                            sa_func.avg(SignalModel.confidence), 2
                        ).label("avg_conf"),
                    )
                    .where(
                        SignalModel.detected_at >= start,
                        SignalModel.detected_at < end,
                    )
                    .group_by(SignalModel.signal_type)
                    .order_by(sa_func.count().desc())
                ).all()

            lines = [
                f"<b>[당일 시그널]</b> {date.today()}",
            ]
            for r in rows:
                lines.append(
                    f"{r.signal_type}: {r.cnt}건"
                    f" (실행 {int(r.acted)}건,"
                    f" 신뢰도 {float(r.avg_conf):.2f})"
                )
            lines.append(
                f"\n총 {total}건, 실행 {acted}건,"
                f" 체결확인 {confirmed}건 ({acc_rate:.0f}%)"
            )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 시그널 조회 실패: {e!s:.100}"

    async def cmd_risk(args: str) -> str:
        """리스크 현황을 반환한다."""
        try:
            days_str = args.strip()
            days = int(days_str) if days_str else 30
            days = max(1, min(days, 90))

            with get_session() as session:
                result = get_optimal_risk_params(session, lookback_days=days)

            if result["total_sells"] == 0:
                return f"<b>[리스크]</b> 최근 {days}일 매도 내역 없음"

            sl = result["stop_loss"]
            tp = result["take_profit"]
            st_sell = result["strategy"]
            rec = result["recommendation"]

            lines = [
                f"<b>[리스크 현황]</b> 최근 {days}일",
            ]
            if sl["count"] > 0:
                lines.append(
                    f"손절: {sl['count']}건,"
                    f" 평균 {sl['avg']:+.2f}%"
                )
            if tp["count"] > 0:
                lines.append(
                    f"익절: {tp['count']}건,"
                    f" 평균 {tp['avg']:+.2f}%"
                )
            if st_sell["count"] > 0:
                lines.append(
                    f"전략매도: {st_sell['count']}건,"
                    f" 평균 {st_sell['avg']:+.2f}%"
                )
            lines.append(
                f"\n<b>권장</b>: 손절 {rec['stop_loss_rate'] * 100:.1f}%"
                f" / 익절 {rec['take_profit_rate'] * 100:.1f}%"
            )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 리스크 조회 실패: {e!s:.100}"

    async def cmd_screen(_args: str) -> str:
        """스크리닝 현황을 반환한다."""
        try:
            with get_session() as session:
                today_data = get_daily_screening(session, date.today())

            total = today_data["total_screened"]
            converted = today_data["converted_count"]
            rate = today_data["conversion_rate"]

            # 최근 7일 평균
            with get_session() as session:
                week_total = 0
                week_converted = 0
                for i in range(7):
                    d = date.today() - timedelta(days=i)
                    day_data = get_daily_screening(session, d)
                    week_total += day_data["total_screened"]
                    week_converted += day_data["converted_count"]

            week_rate = (
                week_converted / week_total * 100
            ) if week_total > 0 else 0

            lines = [
                f"<b>[스크리닝]</b> {date.today()}",
                f"스캔: {total}종목,"
                f" 발굴→매매: {converted}종목"
                f" ({rate:.1f}%)",
                f"최근 7일 평균 전환율: {week_rate:.1f}%"
                f" ({week_converted}/{week_total})",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 스크리닝 조회 실패: {e!s:.100}"

    async def cmd_restart(_args: str) -> str:
        """시스템을 재시작한다 (launchd가 자동 재시작)."""
        import os

        logger.info("Telegram 명령으로 재시작 요청")
        await notifier.notify_system("재시작 요청 수신, 종료 후 자동 재시작됩니다")
        # KeepAlive=true이므로 SIGTERM 후 launchd가 자동 재시작
        asyncio.get_event_loop().call_later(1.0, os.kill, os.getpid(), signal.SIGTERM)
        return "재시작 중... (약 10초 후 복귀)"

    async def cmd_stop(_args: str) -> str:
        """매매를 일시 중단한다."""
        engine._risk._portfolio_halted = True
        logger.info("Telegram 명령으로 매매 중단")
        return "매매가 중단되었습니다. /resume으로 재개할 수 있습니다."

    async def cmd_resume(_args: str) -> str:
        """매매를 재개한다."""
        engine._risk._portfolio_halted = False
        logger.info("Telegram 명령으로 매매 재개")
        return "매매가 재개되었습니다."

    async def cmd_setlimit(args: str) -> str:
        """일일 매매 한도를 조정한다."""
        try:
            new_limit = int(args.strip())
            if new_limit < 1 or new_limit > 1000:
                return "유효 범위: 1~1000"
            engine._risk._daily_trade_limit = new_limit
            logger.info("Telegram 명령으로 일일 매매 한도 변경: %d", new_limit)
            return f"일일 매매 한도가 {new_limit}건으로 변경되었습니다."
        except ValueError:
            return "사용법: /setlimit 숫자 (예: /setlimit 50)"

    async def cmd_help(_args: str) -> str:
        """사용 가능한 명령을 반환한다."""
        halted = "중단" if engine._risk.is_portfolio_halted else "운영"
        return (
            f"<b>[명령어]</b> (매매: {halted})\n"
            "/status — 시스템 상태\n"
            "/balance — 잔고 조회\n"
            "/today — 당일 현황\n"
            "/trades — 당일 체결 상세\n"
            "/pnl [일수] — 기간 손익 요약\n"
            "/signals — 당일 시그널 현황\n"
            "/risk [일수] — 리스크 현황\n"
            "/screen — 스크리닝 현황\n"
            "/watch 종목코드 — 관심종목 추가\n"
            "/unwatch 종목코드 — 관심종목 제거\n"
            "/watchlist — 관심종목 목록\n"
            "/stop — 매매 중단\n"
            "/resume — 매매 재개\n"
            "/setlimit N — 일일 매매 한도 변경\n"
            "/restart — 시스템 재시작\n"
            "/help — 명령어 목록"
        )

    bot.register("status", cmd_status)
    bot.register("balance", cmd_balance)
    bot.register("today", cmd_today)
    bot.register("trades", cmd_trades)
    bot.register("pnl", cmd_pnl)
    bot.register("signals", cmd_signals)
    bot.register("risk", cmd_risk)
    bot.register("screen", cmd_screen)
    bot.register("watch", cmd_watch)
    bot.register("unwatch", cmd_unwatch)
    bot.register("watchlist", cmd_watchlist)
    bot.register("stop", cmd_stop)
    bot.register("resume", cmd_resume)
    bot.register("setlimit", cmd_setlimit)
    bot.register("restart", cmd_restart)
    bot.register("run_implement", cmd_run_implement)
    bot.register("status_implement", cmd_status_implement)
    bot.register("pause_implement", cmd_pause_implement)
    bot.register("help", cmd_help)


async def main() -> None:
    """자동매매 시스템을 시작한다."""
    logger.info("=== KIS 주식 자동매매 시스템 시작 ===")
    logger.info("환경: %s", settings.kis.env)
    logger.info("계좌: %s", settings.kis.account_no)
    logger.info("API 호출 제한: %d건/초", settings.rate_limit.per_second)
    logger.info("최대 손실률: %.1f%%", settings.trading.max_loss_rate * 100)
    logger.info("최대 포지션 비율: %.1f%%", settings.trading.max_position_ratio * 100)
    logger.info("관심종목: %s", settings.trading.watchlist_codes)

    notifier = TelegramNotifier()

    # DB 초기화
    logger.info("데이터베이스 초기화 중...")
    init_db()

    # 매매 엔진 생성
    engine = TradingEngine()

    # 스케줄러에 엔진 연결 후 시작
    scheduler = TradingScheduler(engine=engine)
    scheduler.start()
    logger.info("스케줄러 시작 완료")

    # 헬스체크 서버 시작
    health_server: HealthServer | None = None
    if settings.health.enabled:
        health_server = HealthServer(port=settings.health.port)
        health_server.set_status_provider(
            lambda: {
                "scheduler_running": scheduler.scheduler.running,
                "cycle_count": engine._cycle_count,
                "daily_api_count": engine._client._limiter.daily_count,
            }
        )
        try:
            await health_server.start()
        except OSError as e:
            logger.warning("헬스체크 서버 시작 실패 (매매에 영향 없음): %s", e)
            health_server = None

    # Telegram Bot 시작
    bot = TelegramBot()
    _register_bot_commands(bot, engine, scheduler, notifier)
    await bot.start()

    # Worker 시작 (비동기 태스크 처리)
    worker: WorkerRunner | None = None
    worker_task: asyncio.Task[None] | None = None
    if settings.worker.enabled:
        worker = WorkerRunner()
        worker.register_handler("calendar_event", CalendarEventHandler())
        worker.register_handler("telegram_notify", TelegramNotifyHandler())
        worker.register_handler("daily_summary", DailySummaryHandler())
        worker.register_handler("sync_portfolio", SyncPortfolioHandler())
        worker.register_handler("daily_performance", DailyPerformanceHandler())
        worker.register_handler("record_trade", RecordTradeHandler())
        worker.register_handler("record_signal", RecordSignalHandler())
        worker.register_handler("record_metric", RecordMetricHandler())
        worker_task = asyncio.create_task(worker.run())
        logger.info("Worker 프로세스 시작")

    # Screening Worker 시작 (스크리닝 API 분리)
    screener_worker: ScreeningWorker | None = None
    screener_task: asyncio.Task[None] | None = None
    if settings.worker.enabled:
        screener_worker = ScreeningWorker()
        screener_task = asyncio.create_task(screener_worker.run())
        logger.info("Screening Worker 시작")

    await notifier.notify_system(f"자동매매 시스템 가동 ({settings.kis.env})")
    log_system(f"시스템 시작 ({settings.kis.env})")

    # 종료 시그널 핸들러
    stop_event = asyncio.Event()

    def _handle_signal(sig: int, _frame: object) -> None:
        logger.info("종료 시그널 수신: %s", signal.Signals(sig).name)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("시스템 가동 중... (Ctrl+C로 종료)")

    try:
        await stop_event.wait()
    finally:
        logger.info("시스템 종료 중...")
        if screener_worker:
            screener_worker.stop()
        if screener_task:
            screener_task.cancel()
            try:
                await screener_task
            except asyncio.CancelledError:
                pass
        if worker:
            worker.stop()
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        await bot.stop()
        if health_server:
            await health_server.stop()
        await notifier.notify_system("자동매매 시스템 종료")
        log_system("시스템 종료")
        scheduler.shutdown()
        logger.info("=== KIS 주식 자동매매 시스템 종료 ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
