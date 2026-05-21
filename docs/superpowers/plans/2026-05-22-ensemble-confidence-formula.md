# Ensemble `_weighted_vote` Confidence 산출식 재정의 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_weighted_vote`의 confidence를 `W/len(signals)`(HOLD 희석) 대신 `n_win≥2` 게이트 + `clamp((W/n_win)×(W/(W+L)), 0, 1)`로 재정의해 단독표를 억제하고 다수-동의 약신호를 구제한다.

**Architecture:** `src/strategy/ensemble.py`의 `_weighted_vote()` 한 함수만 교체. HOLD는 기권으로 처리(분모에서 제거), 승자 방향 최소 2표 게이트, base(승자 평균 강도)×opp(승자 우세도) 곱. 임계값·리스크 파라미터·다른 vote 메서드는 불변.

**Tech Stack:** Python 3.12, pytest, mypy(strict), ruff. 테스트는 `tests/test_strategy/test_ensemble.py`의 `FixedStrategy(signal_type, confidence)` + `EMPTY_DF` 헬퍼 사용.

**작업 디렉토리:** worktree `/Users/songhansu/IdeaProjects/kis-autotrader/.claude/worktrees/ensemble-confidence-formula` (branch `worktree-ensemble-confidence-formula`). 모든 명령은 이 디렉토리에서 실행. pytest는 `PYTHONPATH=. /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest ...` 형태로 실행(worktree에 .venv 없음, main venv 사용).

---

## 참고: 산출식 (모든 task 공통)

```
n = 전략 수, buy_w/sell_w = 방향별 confidence 합
winner = (buy_w vs sell_w 큰 쪽), W = 승자 가중치, L = 패자 가중치
n_win = 승자 방향 투표 수

게이트/분기 순서:
  1. hold_count > n*3/4         → HOLD ("HOLD 대다수")
  2. buy_w==0 and sell_w==0     → HOLD ("모든 전략 HOLD")
  3. buy_w == sell_w            → HOLD ("동수")
  4. n_win < 2                  → HOLD ("승자표 부족")
  5. else: base=W/n_win, opp=W/(W+L), conf=min(base*opp, 1.0)
```

검증용 기대값 (abs=0.01):

| Case | votes | winner | W | L | n_win | conf |
|---|---|---|---|---|---|---|
| A | 1 BUY@0.23, 3 HOLD | — | 0.23 | 0 | 1 | HOLD |
| B | 2 BUY@0.3, 2 HOLD | BUY | 0.6 | 0 | 2 | 0.30 |
| C | 2 BUY@0.5, 1 SELL@0.4 | BUY | 1.0 | 0.4 | 2 | 0.357 |
| D | 1 BUY@0.6, 1 SELL@0.5, 2 HOLD | BUY | 0.6 | 0.5 | 1 | HOLD |
| E | 3 BUY@0.3, 1 SELL@0.5 | BUY | 0.9 | 0.5 | 3 | 0.193 |
| tie | 2 BUY@0.5, 2 SELL@0.5 | — | 1.0 | 1.0 | — | HOLD(동수) |
| clamp | 3 BUY@1.0, 1 HOLD | BUY | 3.0 | 0 | 3 | 1.0 |

---

### Task 1: 테스트 갱신 — 신규 케이스 추가 + 기존 기대값 수정 (RED)

**Files:**
- Test: `tests/test_strategy/test_ensemble.py`

- [ ] **Step 1: 기존 `test_weighted_buy_wins` 기대값 수정 (line ~106-119)**

`test_weighted_buy_wins` 함수의 마지막 두 줄(주석 + assert)을 교체:

```python
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    # W=1.0, L=0.8, n_win=2 → base=0.5, opp=1.0/1.8 → conf≈0.278
    assert result.confidence == pytest.approx(0.278, abs=0.01)
```

- [ ] **Step 2: 기존 `test_weighted_sell_wins`를 2-SELL 입력으로 수정 (line ~122-135)**

단일 SELL은 이제 n_win<2로 HOLD가 되므로, SELL이 이기되 n_win=2가 되도록 입력 변경. 함수 본문 전체 교체:

```python
def test_weighted_sell_wins() -> None:
    """SELL 2표(0.5+0.4) vs BUY 1표(0.3) → SELL, n_win=2."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.SELL, 0.5),
            FixedStrategy(SignalType.SELL, 0.4),
            FixedStrategy(SignalType.BUY, 0.3),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.SELL
    # W=0.9, L=0.3, n_win=2 → base=0.45, opp=0.9/1.2=0.75 → conf≈0.3375
    assert result.confidence == pytest.approx(0.3375, abs=0.01)
```

- [ ] **Step 3: 기존 `test_weighted_hold_3_of_4_passes_through`를 게이트 검증으로 재작성 (line ~240-252)**

3 HOLD + 1 BUY는 이제 n_win=1이라 HOLD가 정답. 함수 전체 교체:

```python
def test_weighted_single_vote_gated_to_hold() -> None:
    """단독표(3 HOLD + 1 BUY) → n_win<2 게이트로 HOLD."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.BUY, 0.5),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert result.confidence == 0.0
    assert "승자표 부족" in result.reason
```

- [ ] **Step 4: 신규 테스트 블록 추가 (파일 끝에 append)**

```python
# --- weighted vote: n_win 게이트 + base×opp 산출식 ---


def test_weighted_two_buy_no_opposition() -> None:
    """Case B: 2 BUY@0.3, 2 HOLD → base=0.3, opp=1.0 → conf=0.30."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    assert result.confidence == pytest.approx(0.30, abs=0.01)


def test_weighted_two_buy_with_opposition() -> None:
    """Case C: 2 BUY@0.5, 1 SELL@0.4 → base=0.5, opp=1.0/1.4 → conf≈0.357."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.4),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    assert result.confidence == pytest.approx(0.357, abs=0.01)


def test_weighted_single_buy_beats_single_sell_gated() -> None:
    """Case D: 1 BUY@0.6 vs 1 SELL@0.5 → 승자 n_win=1 → HOLD."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.6),
            FixedStrategy(SignalType.SELL, 0.5),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert "승자표 부족" in result.reason


def test_weighted_three_buy_with_opposition() -> None:
    """Case E: 3 BUY@0.3, 1 SELL@0.5 → base=0.3, opp=0.9/1.4 → conf≈0.193."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.SELL, 0.5),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    assert result.confidence == pytest.approx(0.193, abs=0.01)


def test_weighted_tie_weight_holds() -> None:
    """동수 가중치(2 BUY@0.5 vs 2 SELL@0.5) → HOLD(동수)."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.5),
            FixedStrategy(SignalType.SELL, 0.5),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert "동수" in result.reason


def test_weighted_confidence_clamped_to_one() -> None:
    """3 BUY@1.0 (반대 0) → base=1.0, opp=1.0 → conf=1.0 (clamp 상한)."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 1.0),
            FixedStrategy(SignalType.BUY, 1.0),
            FixedStrategy(SignalType.BUY, 1.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    assert result.confidence == 1.0
```

- [ ] **Step 5: 테스트 실행 → RED 확인**

Run: `PYTHONPATH=. /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_strategy/test_ensemble.py -q`
Expected: FAIL — 수정/신규 테스트들이 현재 `W/len(signals)` 구현과 불일치(예: `test_weighted_two_buy_no_opposition`은 현재 0.6/4=0.15 반환, `test_weighted_single_vote_gated_to_hold`은 현재 BUY 반환).

---

### Task 2: `_weighted_vote` 구현 (GREEN)

**Files:**
- Modify: `src/strategy/ensemble.py:141-181` (`_weighted_vote` 함수 전체)

- [ ] **Step 1: `_weighted_vote` 함수 전체 교체**

`def _weighted_vote(self, signals: list[Signal]) -> Signal:` 부터 `return` 끝(line ~181)까지 다음으로 교체:

```python
    def _weighted_vote(self, signals: list[Signal]) -> Signal:
        """가중 투표를 수행한다.

        HOLD는 기권으로 보아 신뢰도를 희석하지 않는다. 승자 방향에 최소 2개
        전략이 동의(``n_win >= 2``)해야 매매로 전환한다(단독표 억제). 신뢰도는
        승자 평균 강도(base)와 승자 우세도(opp)의 곱으로 산출한다.

            base = W / n_win,  opp = W / (W + L),  conf = min(base * opp, 1.0)

        여기서 W=승자 가중치 합, L=패자 가중치 합, n_win=승자 방향 투표 수.
        """
        hold_count = sum(1 for s in signals if s.signal_type == SignalType.HOLD)
        if hold_count > len(signals) * 3 / 4:
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason=f"앙상블 가중투표: HOLD 대다수 ({hold_count}/{len(signals)})",
            )

        buy_sigs = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_sigs = [s for s in signals if s.signal_type == SignalType.SELL]
        buy_w = sum(s.confidence for s in buy_sigs)
        sell_w = sum(s.confidence for s in sell_sigs)

        if buy_w == 0.0 and sell_w == 0.0:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블: 모든 전략 HOLD",
            )

        if buy_w == sell_w:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블 가중투표: 동수 → HOLD",
            )

        if buy_w > sell_w:
            winner_type = SignalType.BUY
            winner_weight, loser_weight = buy_w, sell_w
            n_win = len(buy_sigs)
        else:
            winner_type = SignalType.SELL
            winner_weight, loser_weight = sell_w, buy_w
            n_win = len(sell_sigs)

        # 단독표 억제: 승자 방향 동의가 2개 미만이면 매매 전환하지 않음
        if n_win < 2:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason=f"앙상블 가중투표: 승자표 부족 (n_win={n_win}) → HOLD",
            )

        base = winner_weight / n_win
        opp = winner_weight / (winner_weight + loser_weight)
        confidence = min(base * opp, 1.0)
        return Signal(
            signal_type=winner_type,
            confidence=confidence,
            reason=(
                f"앙상블 가중투표: {winner_type.value} n_win={n_win} "
                f"W={winner_weight:.2f} L={loser_weight:.2f} "
                f"(base={base:.2f}×opp={opp:.2f})"
            ),
        )
```

- [ ] **Step 2: 테스트 실행 → GREEN 확인**

Run: `PYTHONPATH=. /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_strategy/test_ensemble.py -q`
Expected: PASS (전부 통과).

- [ ] **Step 3: 전체 strategy 테스트 회귀 확인**

Run: `PYTHONPATH=. /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_strategy/ -q`
Expected: PASS (베이스라인 151 → 신규 6개 추가, 0 failures). 만약 `_weighted_vote` 의존 다른 테스트가 깨지면 기대값을 산출식대로 갱신.

- [ ] **Step 4: 커밋**

```bash
git add tests/test_strategy/test_ensemble.py src/strategy/ensemble.py
git commit -m "feat(strategy): ensemble _weighted_vote 산출식 재정의 (n_win 게이트 + base×opp)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 정적 검사 (mypy strict + ruff)

**Files:** 없음 (검증만)

- [ ] **Step 1: mypy strict**

Run: `cd /Users/songhansu/IdeaProjects/kis-autotrader/.claude/worktrees/ensemble-confidence-formula && /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m mypy src/strategy/ensemble.py`
Expected: `Success: no issues found`. 오류 시 타입 주석 보강 후 재실행.

- [ ] **Step 2: ruff**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/ruff check src/strategy/ensemble.py tests/test_strategy/test_ensemble.py`
Expected: `All checks passed!`. 위반 시 `ruff check --fix` 후 재확인.

- [ ] **Step 3: 전체 테스트 스위트 (회귀 안전망)**

Run: `PYTHONPATH=. /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/ -q`
Expected: PASS. (engine 등에서 ensemble confidence에 의존하는 테스트가 깨지면 산출식 기준으로 기대값 갱신.)

- [ ] **Step 4: 정적검사 수정이 있었으면 커밋**

```bash
git add -A && git commit -m "style(strategy): ensemble 산출식 mypy/ruff 정리"
```
수정이 없으면 이 step은 건너뜀.

---

### Task 4: 백테스트 신/구 비교 (리스크 직결 검증)

**Files:**
- Create: `docs/superpowers/specs/2026-05-22-ensemble-backtest-comparison.md` (결과 리포트)

> 목적: BUY_REJECT 메트릭에 투표 분해가 없어 사전 추정 불가 → 신 산출식이 trade 수·MDD·실현손익에 미치는 영향을 백테스트로 확인. 동일 데이터·기간으로 신(worktree HEAD) vs 구(`origin/main`) 산출식 결과를 비교.

- [ ] **Step 1: 백테스트 실행 방법 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python scripts/run_backtest.py --help`
Expected: 사용법 출력. 인자(종목/기간/전략)와 결과 출력 형식을 확인한다. (전략은 `ensemble`, method `weighted` 고정.)

- [ ] **Step 2: 신(NEW) 산출식 백테스트 실행 + 결과 저장**

worktree HEAD(신 산출식) 상태에서 대표 기간/종목으로 실행하고 결과(trade 수, 승률, MDD, 누적/실현손익)를 기록.
Run 예: `PYTHONPATH=. /Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python scripts/run_backtest.py <Step 1에서 확인한 인자>`
결과를 `docs/superpowers/specs/2026-05-22-ensemble-backtest-comparison.md`에 "NEW" 표로 기록.

- [ ] **Step 3: 구(OLD) 산출식 백테스트 실행**

`src/strategy/ensemble.py`만 origin/main 버전으로 임시 복원해 동일 인자로 재실행:
```bash
git stash push -- src/strategy/ensemble.py   # 신 산출식 잠시 치움 (테스트 파일은 유지)
# 또는: git show origin/main:src/strategy/ensemble.py > /tmp/old_ensemble.py 후 비교 실행
```
실행 후 결과를 "OLD" 표로 기록하고 즉시 복원:
```bash
git stash pop
```
Expected: 신/구 두 결과표가 리포트에 채워짐.

- [ ] **Step 4: 비교 판정 기록**

리포트에 판정 작성: trade 수 증가 여부, MDD가 한도(MAX_DAILY_DRAWDOWN) 내인지, 실현손익 악화 없는지. **MDD가 한도를 초과하거나 손익이 유의하게 악화되면 머지 보류하고 사용자에게 보고**(게이트 임계 n_win 또는 산출식 재논의).

- [ ] **Step 5: 커밋**

```bash
git add docs/superpowers/specs/2026-05-22-ensemble-backtest-comparison.md
git commit -m "docs: ensemble 산출식 신/구 백테스트 비교 리포트"
```

---

### Task 5: 구현 이력 기록 (CLAUDE.md 필수 규칙)

**Files:**
- Modify: `docs/CHANGELOG.md` (최근 5건 rolling)

- [ ] **Step 1: record_implementation 실행**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python scripts/record_implementation.py --help`
사용법 확인 후, ensemble `_weighted_vote` 산출식 재정의 내용으로 DB 기록 실행(인자는 help 기준).

- [ ] **Step 2: CHANGELOG rolling 갱신**

`docs/CHANGELOG.md` 최상단에 항목 추가(가장 오래된 1건 제거, 최근 5건 유지):
```markdown
- 2026-05-22 feat(strategy): ensemble `_weighted_vote` confidence 산출식 재정의 — HOLD 희석 제거, 승자표 n_win≥2 게이트, conf=clamp((W/n_win)×(W/(W+L)),0,1). 임계값/리스크 파라미터 불변. (백테스트 신/구 비교 첨부)
```

- [ ] **Step 3: 커밋**

```bash
git add docs/CHANGELOG.md
git commit -m "docs(changelog): ensemble 산출식 재정의 기록"
```

---

## 완료 기준

- [ ] Task 1~2: Case A~E + 경계 테스트 green, 기존 3개 테스트 갱신 완료.
- [ ] Task 3: `tests/` 전체 green, mypy strict / ruff 통과.
- [ ] Task 4: 신/구 백테스트 비교 리포트 작성, MDD/손익이 한도 내 — 초과 시 머지 보류·보고.
- [ ] Task 5: record_implementation + CHANGELOG 기록.
- [ ] 변경 범위: `src/strategy/ensemble.py` `_weighted_vote` + 테스트 + 문서뿐. 임계값·리스크·다른 vote 메서드 불변.
