# 스크리너 다중 순위 병합 + 신호 스코어링 (증분 1)

- **작성일**: 2026-06-15
- **브랜치**: `feat/us-stock-trading`
- **상태**: design (승인됨, spec 검토 대기)
- **백로그 위치**: P1 증분 1 / 6 (단일소스 탈출 백로그의 첫 단계)
- **목표**: 스크리너의 후보 소스를 **거래량순위 단일 → 4개 순위 병합**으로 확대하고, 체결강도·호가잔량을 **스코어 컴포넌트**로 추가한다. 메모리상 "candidate 구조적 빈약 → 약세장 0매매"의 근본원인(후보 폭)을 직격한다.

---

## 1. 확정된 결정

| # | 항목 | 결정 |
|---|------|------|
| 1 | 범위 | 다중 순위 병합 (거래량+등락률+체결강도+호가잔량) |
| 2 | 도입 방식 | **B** — 후보 확대 + 신규 신호(체결강도·호가잔량) 스코어링 |
| 3 | 초기 상태 | **2단계 기본 OFF** — 마스터 스위치 default off(=현행과 완전 동일) + 신규 가중치 default 0.0 |
| 4 | 환경 | env=real (실매수 즉시 영향) → config 토글 롤백 + 관측 로깅 필수 |

### default-off 의미 (중요)
"기본 OFF = 출시 직후 매매 동작이 **현재와 완전히 동일**"을 보장하기 위해 **마스터 스위치** `SCREENING_MULTISOURCE_ENABLED`(default **false**)를 둔다. (소스를 켜면 후보 풀이 넓어져 선택이 달라지므로, "가중치 0"만으로는 현행 동일이 보장되지 않음 — 스위치로 경로 자체를 분기.)
- **스위치 OFF (기본)**: 워커는 기존 단일 소스(거래량순위) 경로만 사용 → **현행과 코드 경로·동작 동일**.
- **스위치 ON (운영자 1차 opt-in)**: 4개 순위 조회·병합으로 후보 풀 확대(breadth). 신규 가중치가 0이면 순위 결정은 현행 축(거래량·등락률·전략)이 담당.
- **신규 가중치 > 0 (2차 opt-in)**: 체결강도/호가잔량이 스코어에 반영.
- ⇒ 활성화는 **스위치 ON(폭 관측) → 가중치 상향(신호 반영)** 2단계로, 각 단계 `config_overrides.json`·관측·롤백.

---

## 2. 검증된 KIS API 사실 (출처: `docs/KIS_openAPI_260614.xlsx`)

4개 순위 엔드포인트. **모두 `output` 배열, env=real에서 동작**(모의 미지원).

| 소스 | TR_ID | URL | 화면코드(scr) | 정렬/주요 param | 코드 키 | metric |
|------|-------|-----|--------------|------------------|---------|--------|
| 거래량(기존) | FHPST01710000 | `/quotations/volume-rank` | 20171 | (기존 구현) | `MKSC_SHRN_ISCD` | ACML_VOL |
| 등락률 | FHPST01700000 | `/ranking/fluctuation` | 20170 | `fid_rank_sort_cls_code=0`(상승률) | `stck_shrn_iscd` | PRDY_CTRT |
| 체결강도 | FHPST01680000 | `/ranking/volume-power` | 20168 | — | `stck_shrn_iscd` | `tday_rltv`(당일 체결강도) |
| 호가잔량 | FHPST01720000 | `/ranking/quote-balance` | 20172 | `fid_rank_sort_cls_code=0` | `mksc_shrn_iscd` | `shnu_rsqn_rate`(매수잔량 비율) |

**공통 응답 필드**: 코드, `data_rank`(신규 3종, 1-based 순위), `hts_kor_isnm`, `stck_prpr`, `prdy_ctrt`, `acml_vol`.

**제약 (설계 반영됨)**:
1. **신규 3종은 시총(`LSTN_STCN`) 미반환** → `market_cap`은 거래량순위 출처에서만 확보.
2. **코드 키 불일치** (`stck_shrn_iscd` vs `mksc_shrn_iscd` vs `MKSC_SHRN_ISCD`) → 엔드포인트별 파싱.

신규 3종 공통 query(예시값): `fid_cond_mrkt_div_code=J`, `fid_input_iscd=0000`, `fid_div_cls_code=0`, `fid_trgt_cls_code=0`, `fid_trgt_exls_cls_code=0`, `fid_input_price_1/2=""`, `fid_vol_cnt=""` (+ 위 표의 scr/sort).

---

## 3. 아키텍처 · 데이터 흐름

```
worker/screener.py  (사이클당 순위 4콜 — 저비용)
  ├ get_volume_rank()         거래량 (기존)
  ├ get_change_rate_rank()    등락률 (신규)
  ├ get_volume_power_rank()   체결강도 (신규)
  └ get_quote_balance_rank()  호가잔량 (신규)
        │  4 × list[RankItem]
        ▼
strategy/screener.py (순수 — 데이터 인자 수신, api 직접호출 없음)
  merge_rankings()  → list[MergedCandidate]  (union+dedup, per-source rank/metric, market_cap propagate)
  filter            → 기존 필터 (market_cap은 알 때만)
  prelim_score+cap  → rank-decay 사전점수로 상위 K개만 선별  ★예산 가드
  (worker) 상위 K에 대해서만 get_daily_price + strategy.analyze  ← per-stock 비용 한정
  score_candidate   → 5축 점수 (거래량·등락률·체결강도·호가잔량·전략)
  rank_candidates   → 최종 후보
        ▼
  screening_results 테이블 (기존 규약 유지: converted_to_trade=True 마킹)
```

**마스터 스위치**: 위 흐름은 `SCREENING_MULTISOURCE_ENABLED=true`일 때만. OFF(기본)면 워커는 `get_volume_rank` 단일 경로(현행)만 타고 신규 fetch/merge를 건너뛴다.

**예산 가드(신규)**: 현재 워커는 필터 통과 후보 **전부**에 `get_daily_price`(per-stock)를 호출한다. 다중소스로 풀이 커지면 이 호출이 비례 증가(EGW00201 위험). → 병합·필터 후 **rank-decay 사전점수로 상위 K개(`MAX_ANALYSIS_POOL`)만** daily-price 분석 대상으로 컷한다. K는 현행 수준(≈ 거래량 top_n)으로 기본 설정해 예산 중립.

---

## 4. API 계층 (`src/api/quote.py`)

### 4.1 공통 DTO
```python
@dataclass
class RankItem:
    """순위 API 공통 항목."""
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    volume: int
    source_rank: int          # data_rank (1-based)
    market_cap: int | None = None   # 거래량순위만 채움
    metric: float | None = None     # 소스별 지표(tday_rltv, shnu_rsqn_rate 등)
```
- `VolumeRankItem`(기존)은 **변경하지 않는다**(시그니처 안정). merge 입력에서 `RankItem`으로 정규화.

### 4.2 신규 메서드 3종
`get_change_rate_rank`, `get_volume_power_rank`, `get_quote_balance_rank` — 각각:
- 표(§2)의 path/TR_ID/scr/sort param 사용, `headers` 불필요(기존 순위와 동일 패턴).
- `output` 배열 파싱(엔드포인트별 코드 키 처리), `source_rank`=`data_rank`(없으면 enumerate 순번), `metric`=소스 지표.
- 실패/빈 응답 시 빈 리스트 반환(스크리닝 막지 않음).
- `top_n` 인자(기본 `settings.screening.top_n`).

> 기존 `get_volume_rank`는 그대로. (시총 필요해 유지)

---

## 5. 병합 · 스코어링 (`src/strategy/screener.py`)

### 5.1 MergedCandidate + merge
```python
@dataclass
class MergedCandidate:
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    volume: int
    market_cap: int | None
    ranks: dict[str, int]      # {"volume": 3, "change_rate": 11, ...}
    metrics: dict[str, float]  # 소스별 지표
```
- `merge_rankings(sources: dict[str, list[RankItem]]) -> list[MergedCandidate]`: code로 union+dedup. 각 후보에 등장한 소스의 `source_rank`/`metric` 보존. `market_cap`은 `volume` 소스 출처면 채움(아니면 None). 가격/등락률/거래량은 임의 소스(우선순위: volume→change_rate→…)에서 취함.

### 5.2 필터 (`ScreeningFilter`)
- 기존 필터 유지. 단 **`market_cap` 필터는 값이 있을 때만** 적용(None은 통과) → breadth 보존. 가격/등락률/거래량 범위 + ETF/ETN 제외는 전 후보 적용.

### 5.3 스코어 (`ScoredCandidate` 확장)
- 신규 필드: `volume_power_score: float`, `quote_balance_score: float`.
- 각 source score = **rank-decay**: `max(0.0, 1.0 - (rank-1)/top_n)`, 해당 순위 미등장 시 0.0.
- 멀티소스 ON 시 `volume_rank_score`는 거래량 소스 rank(`ranks["volume"]`)의 rank-decay로 산출(거래량순위 미등장=0). `change_rate_score`·`strategy_score` 계산식은 불변. (현행 동일성은 이 식이 아니라 **마스터 스위치 OFF 경로**로 보장.)
- `total_score = w_vol·volume_rank_score + w_chg·change_rate_score + w_vp·volume_power_score + w_qb·quote_balance_score + w_strat·strategy_score`.
- 가중치 5개 합 = 1.0. **기본값**: `w_vp=0.0`, `w_qb=0.0`, 나머지 3개는 현행 유지(합 1.0 불변).

### 5.4 사전 컷 (예산 가드)
- `prelim_score(candidate)` = 신규 신호 무관한 저비용 점수(volume/change_rate/power/balance rank-decay 가중합, strategy 제외) → 내림차순 상위 `MAX_ANALYSIS_POOL`개만 반환.
- 워커는 이 상위 K개에 대해서만 `get_daily_price`+`strategy.analyze` 수행 후 `score_candidate` 호출.

---

## 6. 설정 · BRIDGE_SPEC

### 6.1 `src/config.py` `ScreeningConfig` 신규 필드
| 필드 | env 키 | 기본값 |
|------|--------|--------|
| `weight_volume_power` | `SCREENING_WEIGHT_VOLUME_POWER` | 0.0 |
| `weight_quote_balance` | `SCREENING_WEIGHT_QUOTE_BALANCE` | 0.0 |
| `multisource_enabled` | `SCREENING_MULTISOURCE_ENABLED` | **false** (마스터 스위치) |
| `max_analysis_pool` | `MAX_ANALYSIS_POOL` | 40 |

### 6.2 `docs/BRIDGE_SPEC.md`
- 가중치 표에 `SCREENING_WEIGHT_VOLUME_POWER`(0.0, 범위 0.0~0.5)·`SCREENING_WEIGHT_QUOTE_BALANCE`(0.0, 0.0~0.5) 추가.
- **가중치 제약 갱신**: `VOLUME_RANK + CHANGE_RATE + STRATEGY + VOLUME_POWER + QUOTE_BALANCE = 1.0` (3→5).
- 신규 소스 토글·`MAX_ANALYSIS_POOL`(범위 20~80) 항목 추가.

---

## 7. 롤아웃 안전 · 관측 (env=real)

- **2단계 활성화**: ① `SCREENING_MULTISOURCE_ENABLED=true`(폭 확대, 신호 가중치 0) → 며칠 관측 ② `SCREENING_WEIGHT_VOLUME_POWER/QUOTE_BALANCE` 상향(신호 반영). 각 단계 `config_overrides.json`, 코드 배포 없이 즉시 롤백.
- **관측 로깅**(신규 메트릭 `SCREENING_MULTISOURCE`, 스위치 ON일 때): 사이클당 `{소스별 후보수, 병합 후, 필터 후, 분석컷 후}` → 후보 폭 효과 정량화. 기존 `SCREENING_CANDIDATE` 유지.
- **다운스트림 불변**: 앙상블·min_confidence·리스크 게이트·위험종목 사전배제 전부 그대로.
- **기본 출시 = 무변경**: 스위치 OFF가 기본이라 P6 재시작 후에도 매매 동작은 현행과 동일(운영자 opt-in 전까지).

---

## 8. 테스트

- `tests/test_api/test_quote.py`: 신규 3 메서드 — 코드 키 차이·`data_rank`·metric 파싱, 빈/에러 응답 빈 리스트(AsyncMock 패턴).
- `tests/test_strategy/test_screener.py`: `merge_rankings`(union/dedup/rank·metric 보존/market_cap propagate·None), 필터(market_cap None 통과), `score_candidate`(rank-decay·미등장 0·가중합 1.0·신규 가중치 0이면 신규 컴포넌트 기여 0), `prelim_score` 상위 K 컷.
- **마스터 스위치 OFF 동등성**: `multisource_enabled=false`면 워커가 기존 단일소스 경로만 타고 신규 fetch를 호출하지 않는지 → 기존 screener/worker 테스트 green 유지(회귀 검출기).

---

## 9. 구현 Phase 순서

```
P1  api/quote.py: RankItem + 3 메서드 + respx/AsyncMock 테스트
P2  strategy/screener.py: MergedCandidate·merge·5축 score·prelim cap + 테스트 (TDD)
P3  config.py: 신규 필드 (+ 기본 0/true)
P4  worker/screener.py: 4소스 fetch → merge → filter → prelim cap → 분석 → score → DB + 관측 로깅
P5  docs/BRIDGE_SPEC.md 갱신
P6  검증(pytest/mypy/ruff diff) → 마감(record_implementation enhancement→minor + CHANGELOG + tag + 재시작)
```
각 Phase는 행동 불변/테스트 green 유지. 마스터 스위치 OFF가 기본이라 P6 재시작 후에도 매매 동작은 현행과 동일(운영자 opt-in 전까지).

---

## 10. 비범위 (Out of Scope)

- 신규 가중치의 **튜닝값 결정**(운영자가 config_overrides로 점진 상향 — forward 관측 후).
- 종목조건검색(증분 3)·flow_filter 배선(증분 2)·외인기관 추정(증분 6).
- `VolumeRankItem`→`RankItem` 전면 통합(기존 시그니처 유지, 차후 정리 과제).
- per-stock 시총 enrich(예산상 미채택 — market_cap은 거래량순위 best-effort).
