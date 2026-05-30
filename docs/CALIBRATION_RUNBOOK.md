# 소액 실전 캘리브레이션 런북 (Phase 1)

> 목적: 모의에 없던 **실체결 슬리피지**를 소액(20~30만원) 실전으로 측정해, 모의 엣지
> (+1.57%/거래, gross)가 실전 비용 차감 후에도 살아있는지 확인한 뒤 **단계적으로 50만원
> 으로 확대**한다. 2026-05-30 전환 검토(No-Go) 후속. 관련: PR #47(Phase 0 안전장치).

전제: PR #47(v0.8.0 안전장치)이 main에 머지됨. 본 단계는 **실체결 슬리피지 계측
(FILL_SLIPPAGE)** + 분석/판정 도구를 제공한다.

---

## 0. 운영자 사전 준비 (코드 외 — 직접)

- [ ] 실전 계좌 개설·**20~30만원 입금**
- [ ] 실전 API 앱키/시크릿/계좌번호 발급 (모의 키와 다름)
- [ ] `.env`에 실전 인증정보 + `KIS_ENV=real` 설정
- [ ] (신규 고객) 발급 후 3일간 초당 3건 제한 인지

## 1. 실전 DB 스키마 부트스트랩 (1회)

```bash
scripts/bootstrap_real_db.sh   # KIS_ENV=real로 alembic upgrade head → kis_trader_real
```
`kis_trader_real`에 19개 테이블 + `alembic_version`이 생성되는지 확인.

## 2. 캘리브레이션 설정 (`.env`)

소액·저슬리피지·보수적 한도. 모의 기본값과의 핵심 차이:

| 환경변수 | 모의/기본 | **캘리브레이션 권장** | 이유 |
|---|---|---|---|
| `DAILY_TRADE_LIMIT` | 200 | **5** | 과회전 차단·비용 누적 방지 |
| `MAX_DAILY_TRADES_PER_STOCK` | 2 | **1** | 단일종목 누적 진입 차단 |
| `MAX_LOSS_RATE` | 0.03 | **0.02** | 실체결이 손절 트리거보다 나쁘게 잡히는 갭 버퍼 |
| `MAX_DAILY_DRAWDOWN` | 0.08 | **0.04** | 소액 일일 손실 상한 |
| `MAX_CONSECUTIVE_LOSSES` | 7 | **4** | 빠른 자동 halt |
| `MAX_POSITION_RATIO` | 0.2 | 0.2 유지 | 20만→4만/포지션, 30만→6만/포지션 |
| `SCREENING_MAX_PRICE` | 300000 | **20000** | 4~6만 예산으로 복수 주식 체결(슬리피지 표본 품질↑) |
| `MAX_SCREENED_STOCKS` | 10 | **5** | 소액 동시 포지션 제한 |
| `MEASURE_FILL_SLIPPAGE` | true | true | 슬리피지 계측 on(기본) |
| `DB_PRECHECK_BEFORE_ORDER` | (real)true | true | 추적불가 포지션 차단 |

> 리스크 한도는 `.env`에서 설정한다(`config_overrides.json`은 자동 파이프라인 전용 —
> 손절률/포지션 등 고위험 값은 넣지 말 것).

## 3. 기동

```bash
launchctl stop com.kis.autotrader && sleep 2 && launchctl start com.kis.autotrader
```
기동 로그 확인: `base_url=https://openapi.koreainvestment.com`, DB가 `kis_trader_real`,
첫 매수 `tr_id=TTTC...`(실전; `VTTC`면 모의 — 즉시 중단).

## 4. 일일 모니터링

```bash
python scripts/analyze_slippage.py --days 14    # 슬리피지·순엣지·졸업 판정
```
매일 점검:
- **슬리피지**: 매수/매도 평균 adverse_bps. 모의는 0이었음 — 실전 비용의 실체.
- **안전 메트릭**(`system_metrics`): `ORDER_SKIPPED_DB_DOWN`, `ORPHAN_FILL_RECONCILED`,
  `RISK_STATE_RESTORED`, `KILL_SWITCH_ENGAGED` — 0이 정상. 발생 시 원인 조사.
- **긴급 폴백**: `logs/urgent_alerts.fallback.log`가 비어있는지(알림 전달 실패 흔적).
- 비상정지: `touch .trading_halt` (재개 `rm .trading_halt`).

## 5. 졸업 판정 → 50만원 확대

`analyze_slippage.py`가 **✅ 확대 검토 가능**을 출력하려면:
- 체결 표본 **≥ 20건** (≈ 5건/일 × 1~2주)
- 왕복 비용(슬리피지×2 + 세금·수수료 21bps) 차감 후 **순엣지 > 모의의 40%(>62bps)**
- 안전 메트릭 이상 없음(추적불가/halt복원 사고 0)
- 실현 승률 40~75% 밴드 내

충족 시 **급격한 전액 투입 금지** — 주 단위로 +10만씩(20→30→40→50) 상향하며 매주
`analyze_slippage.py` 재확인. 순엣지가 음수로 꺾이면 즉시 동결·재검토.

## 6. 롤백

문제 시: `touch .trading_halt`(즉시 동결) → `.env` `KIS_ENV=virtual` → 재시작(모의 복귀).
모의 DB(`kis_trader`)는 실전(`kis_trader_real`)과 분리되어 데이터 영향 없음.

---

## 미포함 (다음 단계 후보)
실시간/서브사이클 손절 모니터링(websocket), 사이클 주기 단축, 매도측 슬리피지의
체결조회 의존도 검증. 캘리브레이션 데이터로 우선순위 결정.
