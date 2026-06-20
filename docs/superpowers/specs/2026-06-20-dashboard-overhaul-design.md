# 대시보드 고도화 설계 (2026-06-20)

## 목표

운영 대시보드를 KR/US 멀티마켓 인지로 개편하고, 데이터 표기 정확도·가독성·매매 사유 설명력을 끌어올린다.

운영자 요구:
1. 한국/미국 시장 분리
2. 그래프 음수 표기 오류 수정
3. 직관적·깔끔한 데이터 테이블
4. 매수/매도 사유 구체화 (앙상블 투표 내역까지)
5. 전체 메뉴 개편

## 데이터 모델 사실 (탐색 결과)

- `trades`·`signals`·`portfolios`·`screening_results`·`daily_summary`·`daily_performances`·`price_snapshots` 모두 **`market` 컬럼 보유**(`trades`/`portfolios`/`price_snapshots`는 `currency`도). → KR/US 분리는 **스키마 변경 없이 쿼리·UI만**으로 가능.
- 데이터 분포: trades KRX 66 / US 8, signals KRX 56k / US 6.9k, portfolios KRX만 5건.
- **FX/환율 테이블 없음** → 시장별 **네이티브 통화**(한국 원, 미국 $)로 표기. 환산하지 않는다.
- **`daily_summary`/`daily_performances`는 KRX 행만** 존재(US 미적재). → US 성과·요약은 `trades`에서 파생.
- `sell_reason` enum 8종(STOP_LOSS, TAKE_PROFIT, STRATEGY, MANUAL, TRAILING_STOP, MARKET_CLOSE, BREAKEVEN, STAGNATION), `buy_reason` 4종(GOLDEN_CROSS, RSI_OVERSOLD, ENSEMBLE, MANUAL). 현재 대시보드는 일부만 한글 라벨.
- 앙상블 투표 내역은 `system_metrics.detail`(jsonb)에 있음:
  - `SIGNAL_SKIP.detail.vote_meta.votes[]` — 전략별 `action`/`confidence`/지표값(`last_rsi`, `last_macd`, `last_hist`, `last_percent_b`, `last_long/short` 등) + 한글 전략명. **HOLD(skip) 평가에 한해** 풍부(280k건).
  - `BUY_OUTCOME.detail` = `{cycle, outcome, stock_code}`만 — **실제 매수 건엔 투표 미저장**.
  - → 투표 탐색은 **신호 페이지**에서 완전 제공. 체결 단위는 신뢰도·시그널 + 진입 근접 평가 스냅샷("참고용").

## 설계

### 메뉴 구조 — 전역 시장 선택 + 개요 중심
- 사이드바 상단 **시장 선택** `전체 / 🇰🇷 한국 / 🇺🇸 미국` (`st.session_state` 유지). 모든 페이지가 선택을 따른다.
- `st.navigation` + `st.Page`(Streamlit 1.56)로 한글 라벨·아이콘·그룹 구성:
  - **📊 개요** — 엔진 상태, 당일 요약, 보유종목, 최근 체결 (선택 시장; '전체'는 KR·US 병렬)
  - **💹 매매** — 체결 내역 + 구체화된 사유, 종목별 손익, 사유 분포
  - **📡 신호** — 신호 분석 + 앙상블 투표 탐색기
  - **🛡 리스크** — MDD/Sharpe/연패
  - **📈 성과** — 누적 손익 추이
  - **시스템 그룹** · **🛠 파이프라인 KPI** (기존 하네스 페이지; 매매와 분리)

### 시장 인지 & 통화
- 시장 필터: `전체`면 미적용, 그 외 `WHERE market = :market`. 시장 코드 KRX/US.
- 네이티브 통화 포맷: KRW `1,234원`, USD `$12.34`. '전체' 집계는 통화별 분리(합산 금액 단일화 금지).
- US 성과/요약은 `trades` 파생 경로 사용(daily_summary US 부재).

### 데이터 테이블
- 손익/수익률 셀 부호별 색상, 통화기호·천단위·시장별 소수 자릿수, 한글 헤더, 사유 한글화.
- 핵심 수치는 표 상단 metric 카드.

### 그래프 음수 표기 수정
- 손익 막대/누적선을 **Altair**로 교체, `음수=빨강 / 양수=초록` 조건부 색상(`alt.condition`). 단색 `st.bar_chart(color=...)` 제거. 빈/단일 데이터 가드(Infinite extent 경고 제거).

### 매수/매도 사유 구체화
- `sell_reason` 8종 + `buy_reason` 4종 전부 한글 라벨(공용 매핑, 누락분 포함).
- 체결별: 신뢰도(confidence) + 시그널 + 진입 근접 평가 스냅샷(vote_meta, 종목+시각 매칭, "참고용" 명시).
- 신호 페이지: 종목 선택 → 전략별 투표표(전략·action·가중치·지표값) + 가중합→결정 노출.

### 기술 구조
- `dashboard/lib/` 공용 패키지:
  - `db.py` — 기존 `dashboard/db_config.py` 흡수(`resolve_db_url`, `secret_get`) + 엔진/세션 헬퍼.
  - `market.py` — 사이드바 시장 선택 위젯, 선택값(session_state), SQL 필터 절·파라미터 생성.
  - `format.py` — 시장별 통화/수치/수익률 포맷, 부호 색상.
  - `charts.py` — Altair 시맨틱 손익 차트(막대/누적선), 빈데이터 가드.
  - `reasons.py` — buy/sell 사유 한글 라벨, `vote_meta` 파싱/표 변환.
- 페이지는 위 모듈만 호출(중복 DB_URL/get_engine/라벨맵 제거).
- `dashboard/db_config.py`는 `lib/db.py`로 이전하고 호환 shim 유지(외부 참조 안전).

## 범위 밖 (YAGNI)
- FX 환산/통합 평가금액, 실시간 푸시, 신규 DB 컬럼·마이그레이션, US 결산행 생성(엔진 변경).

## 구현 계획 (단계)
1. **lib 기반** — `lib/{db,market,format,charts,reasons}.py` 신설 + 단위 검증(import/포맷/파싱).
2. **네비게이션 골격** — `app.py`를 `st.navigation` 엔트리로 전환, 페이지를 `pages_v2/`(또는 함수)로 재구성, 시장 선택 사이드바.
3. **개요 페이지** — 시장 인지 요약/보유/최근체결, 네이티브 통화, 시맨틱 색상.
4. **매매 페이지** — 사유 구체화(라벨+신뢰도+스냅샷), 종목별 손익, Altair 차트.
5. **신호 페이지** — 투표 탐색기(vote_meta).
6. **리스크·성과 페이지** — 시장 필터 + Altair 시맨틱 차트.
7. **시스템(파이프라인)** — 그룹 분리, 라벨 정리.
8. **검증** — ruff/mypy(diff-scope), `KIS_ENV=real` 주입 렌더 검증(가능 시), 스크린샷.

## 검증 기준
- ruff/mypy: 신규 파일 클린, 기존 파일 diff-scope 신규 위반 0건.
- `전체/한국/미국` 전환 시 각 페이지 정상 렌더 + 통화·색상·사유 정확.
- 음수 손익이 빨강으로 표기됨.
