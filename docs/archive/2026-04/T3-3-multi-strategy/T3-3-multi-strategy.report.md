# T3-3: 다중 전략 동시 운영 — PDCA 완료 보고서

> 작성일: 2026-04-03
> 로드맵 ID: T3-3
> PDCA 결과: **PASS (Match Rate 99%)**

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| 기능 | 종목별 다른 전략 배정, 투표 앙상블, 운영 중 전략 전환 |
| 목적 | 단일 전략 한계 극복, 종목 특성에 맞는 전략 적용 |
| Match Rate | **99%** |
| 전체 테스트 | **255 passed** (기존 기능 퇴행 없음) |

---

## 2. 구현 산출물

### 신규 모듈 (321줄)

| 파일 | 줄 수 | 설명 |
|------|:-----:|------|
| `src/strategy/registry.py` | 58 | StrategyRegistry — 전략 등록/조회 중앙 저장소 |
| `src/strategy/ensemble.py` | 120 | EnsembleStrategy — majority/weighted 투표 앙상블 |
| `src/strategy/selector.py` | 143 | StrategySelector — 종목-전략 매핑 + 환경변수 로드 |

### 수정 파일

| 파일 | 변경 |
|------|------|
| `src/config.py` | StrategyConfig dataclass 추가 (STRATEGY_DEFAULT, STRATEGY_MAPPINGS) |
| `src/engine.py` | selector 통합 (init, process_stock, screen_stocks, 로그) |
| `src/strategy/__init__.py` | 신규 클래스 re-export |

### 테스트 (366줄, 26개)

| 파일 | 줄 수 | 테스트 수 |
|------|:-----:|:---------:|
| `test_registry.py` | 94 | 7 |
| `test_ensemble.py` | 170 | 10 |
| `test_selector.py` | 102 | 9 |

---

## 3. 핵심 설계 결정

### 3.1 하위 호환성 완벽 유지
```python
TradingEngine(strategy=X)    # 기존 방식 → 내부적으로 selector 래핑
TradingEngine(selector=X)    # 새 방식 → 다중 전략
TradingEngine()              # 기본 → 환경변수 기반 자동 구성
```

### 3.2 기존 전략 파일 변경 없음
base.py, moving_average.py, rsi.py 수정 없이 레지스트리/셀렉터만 추가.

### 3.3 앙상블 = BaseStrategy
`EnsembleStrategy`가 `BaseStrategy`를 상속하므로 백테스트에서도 그대로 사용 가능.

---

## 4. 사용법

```env
# .env
STRATEGY_DEFAULT=moving_average
STRATEGY_MAPPINGS=005930:rsi,000660:moving_average
```

```python
# 코드에서 직접 제어
selector.set_mapping("005930", "rsi")
selector.remove_mapping("005930")  # 기본 전략으로 복귀
```

---

## 5. PDCA 사이클 완료

```
[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ (99%) → [Report] ✅
```
