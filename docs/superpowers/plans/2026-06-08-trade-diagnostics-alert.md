# 장 마감 매매 진단 알림 (C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 장 마감 후 결산 직후, "오늘 왜/얼마나 매매했나"를 보여주는 `[매매 진단]` 텔레그램 알림 1건을 추가한다(매매 로직 무변경).

**Architecture:** `system_metrics`(EVAL_TARGETS·SIGNAL_SUMMARY·SCREENING_*·BUY_REJECT) + `trades` + `balance`를 당일 집계한 dict를 만들어, 결산 enqueue 직후 별도 worker task(`notify_type="diagnostics"`)로 전송한다. worker handler의 동적 디스패치(`getattr(notifier, "notify_diagnostics")`)가 새 메서드를 자동 연결한다.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, pytest, 기존 worker queue / TelegramNotifier 패턴.

**설계 근거:** `docs/superpowers/specs/2026-06-08-trade-diagnostics-alert-design.md`

**데이터 계약 (diag dict — 전 task 공유):**
```python
{
    "trade_date": "2026-06-08",   # str
    "trade_count": 0, "buy_count": 0, "sell_count": 0,   # int
    "monitored": [                 # list[dict]
        {"code": "027360", "name": "아주IB투자", "max_conf": 0.0},
    ],
    "monitored_counts": {"positions": 0, "watchlist": 0, "screening": 2},
    "screening": {"ranked_total": 30, "candidate_avg": 0.08, "risk_excluded": ["271830"]},
    "buy_rejects": {"DAILY_TRADE_LIMIT": 0},   # reason -> count (없으면 빈 dict)
    "deposit": 449947, "holdings": 0,          # int
    "headline": "매매 0건 — 발굴 부족 + 모니터링 전원 HOLD",   # str
}
```
모든 값은 JSON 직렬화 가능(worker payload 통과). dataclass 없이 `dict[str, Any]`로 통일한다.

---

### Task 1: 집계 함수 `build_daily_diagnostics` (analytics.py)

**Files:**
- Modify: `src/db/analytics.py` (기존 `get_daily_screening` 패턴 따름, `_day_range`/`get_daily_trades` 재사용)
- Test: `tests/test_analytics.py`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_analytics.py`에 추가; 기존 `db_session` fixture 사용 — `tests/conftest.py`)

```python
def test_build_daily_diagnostics_zero_trades(db_session):
    from datetime import date, datetime
    from src.db.analytics import build_daily_diagnostics
    from src.db.models import SystemMetric

    rec = datetime(2026, 6, 8, 12, 0)
    db_session.add_all([
        SystemMetric(metric_type="EVAL_TARGETS",
                     detail={"targets": ["027360", "036170"],
                             "counts": {"positions": 0, "watchlist": 0, "screening": 2}},
                     recorded_at=rec),
        SystemMetric(metric_type="SIGNAL_SUMMARY", detail={"max_confidence": 0.0}, recorded_at=rec),
        SystemMetric(metric_type="SIGNAL_SKIP",
                     detail={"stock_code": "027360", "confidence": 0.0, "signal_type": "HOLD"},
                     recorded_at=rec),
        SystemMetric(metric_type="SCREENING_CANDIDATE",
                     detail={"ranked_total": 30, "candidate_count": 0}, recorded_at=rec),
        SystemMetric(metric_type="SCREENING_RISK_EXCLUDED", detail={"codes": ["271830"]}, recorded_at=rec),
    ])
    db_session.commit()

    diag = build_daily_diagnostics(db_session, date(2026, 6, 8))

    assert diag["trade_count"] == 0
    assert diag["monitored_counts"]["screening"] == 2
    assert [m["code"] for m in diag["monitored"]] == ["027360", "036170"]
    assert diag["screening"]["ranked_total"] == 30
    assert diag["screening"]["risk_excluded"] == ["271830"]
    assert diag["buy_rejects"] == {}
    assert "매매 0건" in diag["headline"]


def test_build_daily_diagnostics_with_buy_reject(db_session):
    from datetime import date, datetime
    from src.db.analytics import build_daily_diagnostics
    from src.db.models import SystemMetric

    rec = datetime(2026, 6, 8, 12, 0)
    db_session.add(SystemMetric(metric_type="BUY_REJECT",
                                detail={"reason": "DAILY_TRADE_LIMIT", "stock_code": "005880"},
                                recorded_at=rec))
    db_session.commit()
    diag = build_daily_diagnostics(db_session, date(2026, 6, 8))
    assert diag["buy_rejects"] == {"DAILY_TRADE_LIMIT": 1}
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_analytics.py::test_build_daily_diagnostics_zero_trades -v`
Expected: FAIL — `ImportError: cannot import name 'build_daily_diagnostics'`

- [ ] **Step 3: 구현** (`src/db/analytics.py`에 추가)

```python
def build_daily_diagnostics(session: Session, target_date: date) -> dict[str, Any]:
    """장 마감 진단 알림용 당일 지표를 집계한다(읽기 전용).

    system_metrics(EVAL_TARGETS·SIGNAL_SUMMARY·SIGNAL_SKIP·SCREENING_*·BUY_REJECT)와
    trades를 모아 진단 dict를 만든다. signals 테이블은 사용하지 않는다.
    """
    start, end = _day_range(target_date)
    metrics = session.execute(
        select(SystemMetric)
        .where(SystemMetric.recorded_at >= start, SystemMetric.recorded_at < end)
        .order_by(SystemMetric.recorded_at)
    ).scalars().all()

    by_type: dict[str, list[SystemMetric]] = {}
    for m in metrics:
        by_type.setdefault(m.metric_type, []).append(m)

    # 모니터링 종목 (당일 마지막 EVAL_TARGETS)
    targets: list[str] = []
    monitored_counts: dict[str, int] = {"positions": 0, "watchlist": 0, "screening": 0}
    if by_type.get("EVAL_TARGETS"):
        last = by_type["EVAL_TARGETS"][-1].detail or {}
        targets = list(last.get("targets", []))
        monitored_counts = dict(last.get("counts", monitored_counts))

    # 종목별 당일 max confidence (SIGNAL_SKIP detail)
    per_stock_conf: dict[str, float] = {}
    for m in by_type.get("SIGNAL_SKIP", []):
        d = m.detail or {}
        code = d.get("stock_code")
        if code:
            per_stock_conf[code] = max(per_stock_conf.get(code, 0.0), float(d.get("confidence", 0.0)))

    names = _resolve_stock_names(session, targets)
    monitored = [
        {"code": c, "name": names.get(c, c), "max_conf": round(per_stock_conf.get(c, 0.0), 3)}
        for c in targets
    ]

    # 스크리닝
    sc = by_type.get("SCREENING_CANDIDATE", [])
    ranked_total = max((int((m.detail or {}).get("ranked_total", 0)) for m in sc), default=0)
    candidate_avg = (
        sum(int((m.detail or {}).get("candidate_count", 0)) for m in sc) / len(sc) if sc else 0.0
    )
    risk_excluded = sorted(
        {c for m in by_type.get("SCREENING_RISK_EXCLUDED", []) for c in (m.detail or {}).get("codes", [])}
    )

    # 매수 거절 사유별 카운트
    buy_rejects: dict[str, int] = {}
    for m in by_type.get("BUY_REJECT", []):
        reason = str((m.detail or {}).get("reason", "UNKNOWN"))
        buy_rejects[reason] = buy_rejects.get(reason, 0) + 1

    # 체결
    trades = get_daily_trades(session, target_date)
    buy_count = sum(1 for t in trades if t["trade_type"] == "BUY")
    sell_count = sum(1 for t in trades if t["trade_type"] == "SELL")

    max_conf = max((float((m.detail or {}).get("max_confidence", 0.0))
                    for m in by_type.get("SIGNAL_SUMMARY", [])), default=0.0)

    return {
        "trade_date": target_date.isoformat(),
        "trade_count": len(trades),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "monitored": monitored,
        "monitored_counts": monitored_counts,
        "screening": {
            "ranked_total": ranked_total,
            "candidate_avg": round(candidate_avg, 2),
            "risk_excluded": risk_excluded,
        },
        "buy_rejects": buy_rejects,
        "deposit": 0,    # engine이 balance에서 채움
        "holdings": 0,   # engine이 balance에서 채움
        "headline": _diagnostics_headline(
            trade_count=len(trades), monitored=monitored,
            candidate_avg=candidate_avg, max_conf=max_conf,
        ),
    }


def _resolve_stock_names(session: Session, codes: list[str]) -> dict[str, str]:
    """stocks 테이블에서 종목명을 조회한다. 없으면 코드 그대로(빈 dict 항목)."""
    if not codes:
        return {}
    from src.db.models import Stock
    rows = session.execute(
        select(Stock.stock_code, Stock.stock_name).where(Stock.stock_code.in_(codes))
    ).all()
    return {code: name for code, name in rows if name}


def _diagnostics_headline(
    *, trade_count: int, monitored: list[dict[str, Any]], candidate_avg: float, max_conf: float
) -> str:
    """진단 한 줄 요약을 파생한다."""
    if trade_count > 0:
        return f"매매 {trade_count}건 — 정상"
    parts: list[str] = []
    if candidate_avg < 1.0:
        parts.append("발굴 부족")
    if monitored and all(m["max_conf"] == 0.0 for m in monitored):
        parts.append("모니터링 전원 HOLD")
    elif not monitored:
        parts.append("모니터링 0종목")
    reason = " + ".join(parts) if parts else f"max_conf {max_conf:.2f}"
    return f"매매 0건 — {reason}"
```

> `Stock` 모델의 실제 컬럼명(`stock_code`/`stock_name`)은 구현 시 `src/db/models.py`에서 확인. 다르면 맞춘다.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_analytics.py -k build_daily_diagnostics -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add src/db/analytics.py tests/test_analytics.py
git commit -m "feat(analytics): 장 마감 진단 집계 build_daily_diagnostics 추가"
```

---

### Task 2: 포맷 함수 `format_diagnostics` (formatter.py)

**Files:**
- Modify: `src/notify/formatter.py` (순수 함수, `format_system` 아래에 추가)
- Test: `tests/test_notify/test_formatter.py` (없으면 생성)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_format_diagnostics_zero_trades():
    from src.notify.formatter import format_diagnostics
    diag = {
        "trade_date": "2026-06-08", "trade_count": 0, "buy_count": 0, "sell_count": 0,
        "monitored": [
            {"code": "027360", "name": "아주IB투자", "max_conf": 0.0},
            {"code": "036170", "name": "에이치엠넥스", "max_conf": 0.0},
        ],
        "monitored_counts": {"positions": 0, "watchlist": 0, "screening": 2},
        "screening": {"ranked_total": 30, "candidate_avg": 0.08, "risk_excluded": ["271830"]},
        "buy_rejects": {}, "deposit": 449947, "holdings": 0,
        "headline": "매매 0건 — 발굴 부족 + 모니터링 전원 HOLD",
    }
    msg = format_diagnostics(diag)
    assert "[매매 진단]" in msg
    assert "2026-06-08" in msg
    assert "매매 0건" in msg
    assert "027360" in msg and "아주IB투자" in msg
    assert "449,947" in msg          # 천단위 구분
    assert "271830" in msg


def test_format_diagnostics_with_trades_and_rejects():
    from src.notify.formatter import format_diagnostics
    diag = {
        "trade_date": "2026-06-08", "trade_count": 2, "buy_count": 1, "sell_count": 1,
        "monitored": [], "monitored_counts": {"positions": 0, "watchlist": 0, "screening": 0},
        "screening": {"ranked_total": 30, "candidate_avg": 1.5, "risk_excluded": []},
        "buy_rejects": {"DAILY_TRADE_LIMIT": 3}, "deposit": 100000, "holdings": 1,
        "headline": "매매 2건 — 정상",
    }
    msg = format_diagnostics(diag)
    assert "매매 2건" in msg
    assert "DAILY_TRADE_LIMIT" in msg or "일일한도" in msg
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_notify/test_formatter.py -k format_diagnostics -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 구현** (`src/notify/formatter.py`, `format_system` 아래)

```python
# 매수 거절 사유 → 한글 라벨
_REJECT_LABELS: dict[str, str] = {
    "DAILY_TRADE_LIMIT": "일일한도",
    "DAILY_TRADE_LIMIT_PER_STOCK": "종목한도",
    "LOW_CONFIDENCE": "저신뢰",
    "INSUFFICIENT_BALANCE": "예수금부족",
    "RISK": "위험",
    "PRICE_FLOOR": "가격하한",
}


def format_diagnostics(diag: dict[str, Any]) -> str:
    """장 마감 매매 진단 알림 메시지를 생성한다(무음).

    Args:
        diag: build_daily_diagnostics 결과 dict.
    """
    trade_count = diag["trade_count"]
    emoji = "\U0001f4c8" if trade_count > 0 else "\U0001f6ab"
    lines = [
        f"\U0001f52d <b>[매매 진단]</b> {diag['trade_date']}",
        f"{emoji} {diag['headline']}",
        "",
    ]

    mc = diag["monitored_counts"]
    lines.append(
        f"\U0001f4e1 모니터링 {len(diag['monitored'])}종목 "
        f"(보유{mc.get('positions', 0)}/관심{mc.get('watchlist', 0)}/발굴{mc.get('screening', 0)})"
    )
    for m in diag["monitored"][:10]:
        lines.append(f"  • {m['code']} {m['name']} — {m['max_conf']:.2f}")

    sc = diag["screening"]
    lines.append("")
    lines.append(
        f"\U0001f50d 스크리닝 top{sc['ranked_total']} → 후보 avg {sc['candidate_avg']:.2f}/사이클"
    )
    if sc["risk_excluded"]:
        lines.append(f"  • 위험배제 {len(sc['risk_excluded'])}종목 ({', '.join(sc['risk_excluded'][:5])})")

    lines.append("")
    if diag["buy_rejects"]:
        parts = [f"{_REJECT_LABELS.get(k, k)}{v}" for k, v in diag["buy_rejects"].items()]
        lines.append("⛔ 매수게이트 차단: " + " · ".join(parts))
    else:
        lines.append("⛔ 매수게이트: 신호 0이라 도달 전 차단")

    lines.append("")
    lines.append(f"\U0001f4b0 예수금 {diag['deposit']:,}원 · 보유 {diag['holdings']}종목")
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_notify/test_formatter.py -k format_diagnostics -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add src/notify/formatter.py tests/test_notify/test_formatter.py
git commit -m "feat(notify): format_diagnostics 진단 메시지 포맷 추가"
```

---

### Task 3: Notifier 메서드 `notify_diagnostics` (telegram.py)

**Files:**
- Modify: `src/notify/telegram.py` (`notify_system` 아래; `format_diagnostics` import 추가)
- Test: `tests/test_notify/test_telegram.py` (없으면 생성)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import pytest

@pytest.mark.asyncio
async def test_notify_diagnostics_calls_send(monkeypatch):
    from src.notify.telegram import TelegramNotifier
    notifier = TelegramNotifier()
    sent = {}

    async def fake_send(message, *, urgent=False):
        sent["message"] = message
        sent["urgent"] = urgent

    monkeypatch.setattr(notifier, "send", fake_send)
    diag = {
        "trade_date": "2026-06-08", "trade_count": 0, "buy_count": 0, "sell_count": 0,
        "monitored": [], "monitored_counts": {"positions": 0, "watchlist": 0, "screening": 0},
        "screening": {"ranked_total": 0, "candidate_avg": 0.0, "risk_excluded": []},
        "buy_rejects": {}, "deposit": 0, "holdings": 0, "headline": "매매 0건 — 모니터링 0종목",
    }
    await notifier.notify_diagnostics(diag=diag)

    assert "[매매 진단]" in sent["message"]
    assert sent["urgent"] is False    # 무음
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_notify/test_telegram.py -k notify_diagnostics -v`
Expected: FAIL — `AttributeError: notify_diagnostics`

- [ ] **Step 3: 구현**

`src/notify/telegram.py` 상단 import에 `format_diagnostics` 추가(기존 formatter import 줄에 합류), 그리고 `notify_system` 아래에:

```python
    async def notify_diagnostics(self, diag: dict[str, Any]) -> None:
        """장 마감 매매 진단 알림을 전송한다 (무음)."""
        await self.send(format_diagnostics(diag))
```

(파일 상단에 `from typing import Any`가 없으면 추가)

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_notify/test_telegram.py -k notify_diagnostics -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/notify/telegram.py tests/test_notify/test_telegram.py
git commit -m "feat(notify): notify_diagnostics 전송 메서드 추가"
```

---

### Task 4: Engine 연결 `_enqueue_telegram_diagnostics` + post_market (engine.py)

**Files:**
- Modify: `src/engine.py` (`_enqueue_telegram_daily_summary`(2229) 아래에 메서드 추가, `post_market`의 결산 enqueue(683) 직후 1줄 호출)
- Test: `tests/test_engine_db_integration.py` 또는 신규 `tests/test_engine_diagnostics.py`

- [ ] **Step 1: 실패하는 테스트 작성** (task_queue mock으로 enqueue 호출 검증)

```python
def test_enqueue_telegram_diagnostics_payload():
    from unittest.mock import MagicMock
    from datetime import date
    from src.engine import TradingEngine

    engine = TradingEngine.__new__(TradingEngine)   # __init__ 우회
    engine._task_queue = MagicMock()

    diag = {"trade_date": date.today().isoformat(), "trade_count": 0, "headline": "x",
            "monitored": [], "monitored_counts": {}, "screening": {}, "buy_rejects": {},
            "deposit": 449947, "holdings": 0, "buy_count": 0, "sell_count": 0}
    engine._enqueue_telegram_diagnostics(diag)

    engine._task_queue.enqueue.assert_called_once()
    kwargs = engine._task_queue.enqueue.call_args.kwargs
    assert kwargs["task_type"] == "telegram_notify"
    assert kwargs["payload"]["notify_type"] == "diagnostics"
    assert kwargs["payload"]["message_data"]["diag"]["deposit"] == 449947
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_engine_diagnostics.py -v`
Expected: FAIL — `AttributeError: _enqueue_telegram_diagnostics`

- [ ] **Step 3: 구현**

`src/engine.py`, `_enqueue_telegram_daily_summary` 아래:

```python
    def _enqueue_telegram_diagnostics(self, diag: dict[str, Any]) -> None:
        """장 마감 매매 진단 알림을 Worker Queue에 적재한다(결산 직후 별도 1건)."""
        today_str = date.today().isoformat()
        self._task_queue.enqueue(
            task_type="telegram_notify",
            payload={"notify_type": "diagnostics", "message_data": {"diag": diag}},
            priority=3,
            idempotency_key=f"telegram_diag_{today_str}",
        )
```

그리고 `post_market`의 결산 enqueue(`engine.py:683` `self._enqueue_telegram_daily_summary(...)`) 직후에 집계+전송 추가:

```python
            # 매매 진단 알림 (결산 직후 별도 1건) — 집계 실패는 결산에 영향 없음
            try:
                with get_session() as session:
                    diag = build_daily_diagnostics(session, today)
                diag["deposit"] = int(balance.deposit)
                diag["holdings"] = sum(1 for h in balance.holdings if h.quantity > 0)
                self._enqueue_telegram_diagnostics(diag)
            except Exception:
                logger.exception("매매 진단 집계/적재 실패 (결산·매매에 영향 없음)")
```

`build_daily_diagnostics` import를 engine.py 상단 analytics import에 추가. `today`/`balance`/`get_session`은 post_market 스코프에 이미 존재(683 주변 확인).

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_engine_diagnostics.py -v && mypy src/engine.py`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/engine.py tests/test_engine_diagnostics.py
git commit -m "feat(engine): post_market에 매매 진단 알림 적재 연결"
```

---

### Task 5: Worker 라우팅 통합 테스트 (코드 변경 없음)

**Files:**
- Test: `tests/test_worker/test_handlers.py` (없으면 생성)

> 동적 디스패치(`getattr(notifier, "notify_diagnostics")`)라 handler 코드 변경은 없다. 라우팅이 실제로 연결되는지만 회귀 테스트로 고정한다.

- [ ] **Step 1: 테스트 작성**

```python
import pytest

@pytest.mark.asyncio
async def test_telegram_notify_routes_diagnostics(monkeypatch):
    from src.worker.handlers import TelegramNotifyHandler
    import src.notify.telegram as tg

    captured = {}

    class FakeNotifier:
        async def notify_diagnostics(self, diag):
            captured["diag"] = diag

    monkeypatch.setattr(tg, "TelegramNotifier", FakeNotifier)
    handler = TelegramNotifyHandler()
    await handler.execute({"notify_type": "diagnostics", "message_data": {"diag": {"x": 1}}})

    assert captured["diag"] == {"x": 1}
```

- [ ] **Step 2: 실행 (바로 통과해야 함 — 디스패치는 이미 구현됨)**

Run: `pytest tests/test_worker/test_handlers.py -k diagnostics -v`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add tests/test_worker/test_handlers.py
git commit -m "test(worker): diagnostics 알림 라우팅 회귀 테스트"
```

---

### Task 6: 전체 검증 + 문서/이력

**Files:**
- Modify: `README.md` (Telegram 섹션 1줄), `docs/CHANGELOG.md` (rolling)

- [ ] **Step 1: 전체 게이트**

Run: `pytest tests/ && python -m mypy src/ && ruff check src/`
Expected: 전부 PASS

- [ ] **Step 2: README 1줄 추가** — Telegram 알림 목록에 "매매 진단(장 마감, 무음)" 추가

- [ ] **Step 3: 구현 이력 기록**

```bash
python scripts/record_implementation.py   # 인자는 스크립트 도움말 확인
# docs/CHANGELOG.md rolling 최신 5건 갱신 (가장 오래된 항목 제거)
```

- [ ] **Step 4: 최종 커밋**

```bash
git add README.md docs/CHANGELOG.md
git commit -m "docs: 매매 진단 알림 README/CHANGELOG 반영"
```

---

## 검증 체크리스트 (완료 기준)

- [ ] `pytest tests/` 전부 통과 (신규 테스트 포함)
- [ ] `mypy src/` strict 통과, `ruff check src/` 통과
- [ ] 진단 메시지가 결산 직후 별도 1건으로 전송됨(수동: post_market 1회 dry-run 또는 worker 로그)
- [ ] 휴장일엔 미전송(post_market_job 가드)
- [ ] `signals` 테이블 미사용 확인(적재 공백 이슈와 독립)
