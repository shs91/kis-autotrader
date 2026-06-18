# 보유종목 실시간 가격 vs 매수가 비교 차트 설계

> 대시보드에 **보유 중인 종목의 실시간(폴링) 가격과 내 매수 평단가를 그래프로 비교**하는 기능.
> 손절/익절 기준선·체결 마커까지 한 화면에서 "내가 산 가격 대비 지금 어디쯤이고 어디서 팔릴지"를 본다.

작성일: 2026-06-19 · 상태: 설계 승인(구현 대기) · 브랜치: `feat/positions-realtime-chart`

---

## 1. 확정된 결정 사항

| # | 결정 | 근거 |
|---|------|------|
| 1 | **데이터 소스 = 폴링 재사용**(웹소켓 아님) | 엔진이 이미 매 사이클(~10초) 보유종목 현재가를 REST로 폴링 중. 웹소켓은 dead code·US(HDFSCNT0) 미지원·CLAUDE.md IP/앱키 차단 위험. 폴링 재사용은 추가 API 0·ban 위험 0·KRX+US 즉시 동작. |
| 2 | **시간 범위 = 최근 7일 롤링** | 여러 세션 추이를 보되 저장량 유계. 일 1회 정리 잡으로 7일 초과분 삭제. |
| 3 | **그래프 내용 = 가격 + 평단가 + 손익률 + 리스크선 + 체결 마커** | 실시간 가격 line, 매수 평단가 수평선, 현재 손익률 라벨, 손절/익절/peak 수평선, 매수(▲)/매도(▼) 체결 마커. |
| 4 | **범위 = 보유종목만** | 사용자 요구. 보유 ≤ ~40(웹소켓 41 구독 한도와 무관 — 폴링이라). |
| 5 | **차트 라이브러리 = Altair**(`st.altair_chart`) | 내장 `st.line_chart`는 수평 기준선·scatter 마커·hover 불가. Altair는 가볍고 Streamlit 네이티브, layer로 line+rule+point 합성. plotly보다 의존성 가벼움. |

### 핵심 함의
- **추가 API 호출 없음**: 엔진이 이미 가진 현재가를 시계열로 적재만 한다.
- **매매 루프 무차단**: 스냅샷 기록은 trades/metrics와 동일하게 워커 태스크 큐 경유.
- **평단가/리스크선은 적재하지 않음**: `portfolios`(현재 평단가·peak) + `config`(손절/익절%)에서 계산 → 중복 적재 회피.

---

## 2. 데이터 흐름

```
[엔진] 매 사이클 보유종목 현재가 폴링(기존)
   └─ 보유종목에 한해 enqueue("price_snapshot", {code, market, currency, price})
        └─ [워커] price_snapshots 테이블 INSERT
[정리 잡] 일 1회 DELETE captured_at < now()-7d

[대시보드 positions 페이지]
   price_snapshots(7일) + portfolios(평단가·peak) + trades(체결마커) + config(손절/익절%)
   └─ 종목별 Altair 차트 렌더(통화 인지)
```

---

## 3. 데이터 모델 & 마이그레이션

신규 테이블 `price_snapshots` (`src/db/models.py`):

| 컬럼 | 타입 | 비고 |
|------|------|------|
| id | Integer PK | |
| stock_code | String(20) | 종목코드/심볼 |
| market | String(10) | "KRX"/"US" (멀티마켓 구분) |
| currency | String(8) | "KRW"/"USD" (대시보드 축 통화) |
| price | Numeric(18,4) asdecimal=False | 현재가(스냅샷 시점). US 소수·KRX 정수값 |
| captured_at | timestamptz(서버 default now) | 스냅샷 시각 |

인덱스: `(stock_code, captured_at)`(종목별 시계열 조회), `(captured_at)`(7일 정리).

- Alembic 마이그레이션 1건(테이블 생성). 기존 테이블 불변.
- `repository.py`에 `add_price_snapshot(...)` + `get_price_snapshots(stock_code, since)` 추가.

## 4. 쓰기 경로 (엔진 → 워커)

- **엔진** (`src/engine.py`): 매매 사이클에서 보유종목(`held_codes`)의 현재가를 이미 조회한다. 해당 종목에 한해 `price_snapshot` 태스크를 enqueue. 관심/발굴 종목은 제외(범위 = 보유만).
  - 가격은 시장별 정규화값(`_norm_price`: KRX 정수·US 센트). market/currency는 `self._market`.
  - 멱등키 불필요(시계열 append). DB 장애에도 매매 무차단(기존 enqueue 패턴).
  - **스냅샷 주기 = 매 사이클**(보유 ≤ 수십 종목이라 볼륨 유계). 필요 시 N초 throttle 추가 가능(설정값).
- **워커** (`src/worker/handlers.py`): `price_snapshot` 핸들러가 `add_price_snapshot` 호출.

## 5. 읽기 / UI

신규 페이지 `dashboard/pages/positions.py`:

- **상단 요약 표**: 보유종목별 — 종목명·시장·평단가·현재가(최신 스냅샷)·손익률·손익금액(통화 인지 표기).
- **종목 선택**(드롭다운/라디오) → 선택 종목 **Altair 차트**:
  - 가격 line (7일 price_snapshots, captured_at × price)
  - **평단가 수평선**(`portfolios.avg_price`) — 현재 cost basis 기준선
  - **손절선**(평단가 × (1 − `MAX_LOSS_RATE`)) · **익절선**(평단가 × (1 + `take_profit_ratio`, 기본 5%))
  - **peak 수평선**(`portfolios.peak_price`, 트레일링 기준; null이면 생략)
  - **체결 마커**: trades(7일, 해당 종목) — 매수 ▲(상승색)·매도 ▼(하강색), traded_at × price, hover에 수량/사유
  - **손익률 라벨**: (현재가 − 평단가)/평단가 × 100, 색상 분기
- **통화 인지**: KRX = ₩·정수, US = $·소수(기존 `format_money` 규약 #64 재사용). 종목별 개별 차트라 KRX·US 보유 혼재해도 스케일 충돌 없음.
- 데이터 없음(스냅샷 미수집/장 시작 전) 가드: 빈 상태 안내.

## 6. 보존 (7일 롤링)

- `src/scheduler/jobs.py`에 일 1회 정리 잡: `DELETE FROM price_snapshots WHERE captured_at < now() - interval '7 days'`.
- 기존 백업/정리 잡 패턴 재사용. misfire_grace_time·max_instances=1 준수.

## 7. 모듈 경계 (CLAUDE.md 담당 영역)

| 영역 | 파일 | 담당 |
|------|------|------|
| 모델 + 마이그레이션 | `src/db/models.py`, `alembic/versions/` | db-scheduler |
| repository (add/get) | `src/db/repository.py` | db-scheduler |
| 워커 핸들러 | `src/worker/handlers.py` | db-scheduler |
| 보존 잡 | `src/scheduler/jobs.py` | db-scheduler |
| 엔진 enqueue(보유 스냅샷) | `src/engine.py` | team lead |
| 대시보드 페이지 | `dashboard/pages/positions.py` | team lead |
| 의존성(altair) | `pyproject.toml` | team lead |

## 8. 검증 / 테스트

- repository add/get 단위 테스트(시장 필터·since 범위).
- 워커 핸들러 테스트(payload → INSERT).
- 엔진: 보유종목만 `price_snapshot` enqueue되고 관심/발굴은 제외 회귀.
- 정리 잡: 7일 경계 삭제 테스트.
- 대시보드: 차트 데이터 구성(가격·평단가·리스크선·마커 결합) 로직 단위 테스트(렌더 자체는 수동 확인).
- pytest + mypy strict + ruff. **KRX 동작 불변**(신규 테이블·경로라 기존 KRX 매매/결산 무영향).

## 9. 비범위 (YAGNI)

- 웹소켓 실시간 틱(향후 KRX 한정 확장 가능, 현재 폴링 ~10초로 충분).
- 평단가 진화 계단선(현재는 현재 평단가 수평선 + 체결 마커로 매수 시점/가격 표현).
- 알림/임계 트리거(대시보드는 조회 전용).
- 일봉 종가 백필(7일 롤링은 출시 시점부터 수집).

## 10. 운영자 액션

- 마이그레이션 1건: `alembic upgrade head`(price_snapshots 생성).
- 대시보드 의존성: altair 설치(`pyproject.toml` 반영 후 재설치).
- DB 쓰기 증가는 소량(보유종목 × 사이클, 7일 retention). 기존 서비스 재시작으로 스냅샷 수집 시작.
