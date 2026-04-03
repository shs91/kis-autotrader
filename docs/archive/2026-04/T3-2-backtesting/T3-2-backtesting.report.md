# T3-2: 백테스팅 프레임워크 — PDCA 완료 보고서

> 작성일: 2026-04-03
> 로드맵 ID: T3-2
> PDCA 결과: **PASS (Match Rate 95%)**

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| 기능 | 과거 일봉 데이터 기반 매매 전략 시뮬레이션 |
| 목적 | 실전 투입 전 전략 성능 검증, 파라미터 최적화 기반 마련 |
| PDCA 단계 | Plan → Design → Do → Check → **Complete** |
| Match Rate | **95%** |

---

## 2. PDCA 사이클 요약

### Plan (계획)
- 6개 필수 요구사항(R1~R6) 정의: 전략 재사용, 데이터 로드, 시뮬레이션 엔진, 리스크 관리, 성과 지표, 결과 리포트
- 핵심 설계 원칙: `BaseStrategy.analyze()` 인터페이스 동일 사용, API 미호출, 실전 리스크 동일 적용
- 기존 코드 영향도: **없음** (신규 모듈만 추가)

### Design (설계)
- 5개 모듈 상세 설계: broker, data_loader, engine, report, CLI
- 실전 코드(TradingEngine, RiskManager)와의 1:1 매핑 테이블 작성
- 25개+ 테스트 케이스 설계 (4개 테스트 파일)
- 에러 처리 7개 시나리오 정의

### Do (구현)
- 서브에이전트 병렬 구현: broker, data_loader, report 동시 → engine 순차
- 구현 결과: **1,712줄** (소스 865줄 + 테스트 785줄 + CLI 62줄)

### Check (검증)
- gap-detector 에이전트로 Design vs Implementation 비교
- **Match Rate 95%**: 핵심 로직/아키텍처 완벽 일치, 테스트 커버리지에서 경미한 갭

---

## 3. 구현 산출물

### 소스 코드

| 파일 | 줄 수 | 설명 |
|------|:-----:|------|
| `src/backtest/__init__.py` | 18 | 패키지 공개 API |
| `src/backtest/broker.py` | 286 | VirtualBroker — 수수료/슬리피지/손절/익절/포지션 관리 |
| `src/backtest/data_loader.py` | 130 | DataLoader — CSV 파일 및 KIS API 일봉 로드 |
| `src/backtest/engine.py` | 188 | BacktestEngine — 슬라이딩 윈도우 시뮬레이션 |
| `src/backtest/report.py` | 243 | BacktestReport — MDD/샤프비율/승률/손익비 계산 |
| `scripts/run_backtest.py` | 62 | CLI 실행 스크립트 |
| **소스 합계** | **927** | |

### 테스트 코드

| 파일 | 줄 수 | 테스트 수 | 설명 |
|------|:-----:|:---------:|------|
| `tests/test_backtest/test_broker.py` | 376 | 21 | 매수/매도/손절/익절/수수료/슬리피지 |
| `tests/test_backtest/test_engine.py` | 150 | 4 | 시뮬레이션 실행/골든크로스/손절 |
| `tests/test_backtest/test_report.py` | 259 | 9 | 수익률/MDD/승률/샤프비율/손익비 |
| **테스트 합계** | **785** | **34** | |

---

## 4. 검증 결과

| 검증 항목 | 결과 |
|-----------|------|
| `pytest tests/test_backtest/ -v` | **34 passed** (0.32s) |
| `ruff check src/backtest/` | **All checks passed** |
| `mypy src/backtest/` | pandas-stubs 이슈 (프로젝트 기존 이슈, backtest 고유 에러 없음) |

### Gap 분석 점수

| 카테고리 | 점수 |
|----------|:----:|
| 클래스/메서드 일치 | 97% |
| 데이터 흐름 일치 | 100% |
| 비즈니스 로직 일치 | 98% |
| 테스트 커버리지 | 82% |
| 에러 처리 | 100% |
| 데이터 스키마 일치 | 100% |
| **종합 Match Rate** | **95%** |

---

## 5. 핵심 설계 결정

### 5.1 전략 인터페이스 동일 사용
`BaseStrategy.analyze(df) -> Signal` 인터페이스를 변경 없이 그대로 사용.
→ 실전에서 검증된 전략을 백테스트에서도 동일하게 실행 가능.

### 5.2 실전 리스크 로직 재현
| 실전 (RiskManager) | 백테스트 (VirtualBroker) |
|---------------------|-------------------------|
| `should_stop_loss()` | `check_stop_loss()` — 동일 공식 |
| `should_take_profit()` | `check_take_profit()` — 동일 공식 |
| `calculate_position_size()` | `buy()` 내부 — 동일 공식 |
| 처리 순서: 손절→익절→전략매도 | `_process_day()` — 동일 순서 |

### 5.3 수수료/슬리피지 현실 반영
- 수수료 0.015% (매수/매도 각각)
- 슬리피지 0.1% (매수 시 불리, 매도 시 불리)
→ 실전과 유사한 수익률 시뮬레이션 가능.

### 5.4 미청산 포지션 자동 청산
백테스트 종료 시 보유 포지션을 마지막 종가로 강제 청산하여, 모든 거래가 완결된 상태의 성과 지표를 산출.

---

## 6. 사용법

```bash
# CSV 파일 기반 백테스트
python scripts/run_backtest.py --csv data/005930.csv --code 005930

# KIS API 기반 백테스트 (최근 100일)
python scripts/run_backtest.py --code 005930 --api

# 자본금/전략 파라미터 변경
python scripts/run_backtest.py --csv data/005930.csv --code 005930 \
    --capital 50000000 --short-ma 3 --long-ma 15
```

---

## 7. 남은 개선 사항 (향후)

| 우선순위 | 항목 | 설명 |
|:--------:|------|------|
| LOW | test_data_loader.py | DataLoader 테스트 파일 추가 (4건) |
| LOW | 엔진 테스트 보강 | 데드크로스/익절/우선순위 테스트 3건 |
| N1 | 차트 시각화 | matplotlib 수익률 곡선, 매매 시점 마킹 |
| N2 | 파라미터 최적화 | 전략 파라미터 범위 탐색 |
| N3 | 벤치마크 비교 | KOSPI 지수 대비 초과수익률 |

---

## 8. 후속 기능 영향

| 기능 | 관계 | 비고 |
|------|------|------|
| **T3-3 다중 전략 동시 운영** | 직접 의존 | 백테스트로 전략 성능 비교 후 전략 선택 |
| T3-5 Docker 컨테이너화 | 간접 | 백테스트 스크립트도 컨테이너에 포함 |

---

## 9. PDCA 사이클 완료

```
[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ (95%) → [Report] ✅
```

**T3-2 백테스팅 프레임워크 — PDCA 완료.**
