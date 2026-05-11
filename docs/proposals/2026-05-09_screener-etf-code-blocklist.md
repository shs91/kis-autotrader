# 스크리너 ETF/Q-code 필터 누수 수정 — 코드 기반 블록리스트 도입

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-09
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/strategy/screener.py, src/api/quote.py (또는 ScreeningWorker 위치)

## 현상 분석

### 정량 근거 (W19 데이터)

`screening_results` 테이블 기준 05-06 ~ 05-08(KST) 누적 5,094건 중 **명백한 ETF/레버리지/Q-code 종목이 다수 잔존**:

| 종목코드 | 추정 종목 | 등장 횟수 |
|----------|-----------|-----------|
| 252670 | KODEX 200선물인버스2X | 721 |
| 114800 | KODEX 인버스 | 715 |
| 252710 | KODEX 코스닥150선물인버스 | 715 |
| 069500 | KODEX 200 | 676 |
| 396500 | TIGER 미국S&P500선물H | 715 |
| 379800 | KODEX 미국S&P500 | 582 |
| Q530036 | (선물/옵션 추정) | 659 |
| Q550043 | (선물/옵션 추정) | 150 |

이 종목들이 평가 대상에 포함된 결과:

- **05-07 시그널 acted 1,499건 중 1,498건이 252670/252710** (avg_conf 0.114~0.116)
- 05-07 MIN_CONFIDENCE 0.10→0.15 상향이 사실상 **이 ETF 시그널을 차단하는 부수효과로 작용** — 본래 의도였던 시그널 품질 개선이 아닌 ETF 잡음 제거였음
- 04-24 "스크리너 ETF/ETN/레버리지 종목 필터링 추가" 제안서 구현 후에도 **15일째 누수 지속**

### 근본 원인

`src/strategy/screener.py::_is_etf_etn`(line 95)은:
1. `stock_code.startswith("Q")` — Q-prefix 필터 (정상 동작 가정)
2. `stock_name`에 KODEX/TIGER/KBSTAR/ARIRANG/SOL/ACE/HANARO/ETN/레버리지/인버스/2X/곱버스 키워드 포함 여부 검사

그러나 **KIS 거래량 순위 응답에서 stock_name이 stock_code와 동일하게 들어오는 케이스**가 다수 존재(시그널 데이터에서 확인: stock_name="252670"). 이 경우 키워드 매칭이 모두 실패해 ETF가 그대로 통과.

또한 Q-prefix 필터가 `screening_results`에 잔존하는 점은 **ScreeningFilter 외부 경로**(예: 워커가 별도 소스에서 직접 적재) 가능성 시사 — 워커 코드 점검 필요.

## 제안 내용

세 가지 보강을 결합한다(하나라도 빠지면 누수가 재발할 수 있음):

1. **코드 기반 ETF 블록리스트** 도입: 한국거래소 KODEX·TIGER·KBSTAR 등 주요 ETF/ETN의 종목코드 패턴/명시 리스트 도입.
2. **stock_name 결손 시 보수적 차단**: stock_name이 비어있거나 stock_code와 동일하면 자동 차단(불확실하면 제외 우선).
3. **워커 적재 직전 재검증**: ScreeningWorker(또는 동등 코드)가 `screening_results`에 INSERT 직전 동일 필터를 다시 적용하여 누수 종목을 차단.

### 코드 기반 블록리스트 (1차 대상)

검증 가능한 ETF 코드 패턴:
- KODEX 류: `069500`, `114800`, `122630`, `233740`, `251340`, `252670`, `252710`, `379800`, `462330` 등 (구체 리스트는 settings에 외부화)
- TIGER 류: `091160`, `102110`, `139660`, `139220`, `233160`, `360750`, `396500` 등
- 거래소 코드 prefix:
  - 일반 종목 6자리 숫자 (00~9XXXX)
  - **ETF는 보통 0xx, 1xx, 2xx, 3xx, 4xx 범위에 분포** — 코드 만으로 100% 분리 불가하므로 **명시 리스트 + name 키워드 + Q-prefix** 조합이 필요

→ **블록리스트는 외부 JSON 파일**(`config/etf_blocklist.json`)로 관리해 운영 중 갱신을 용이하게 한다(코드 변경 불필요).

## 변경 스펙

### 파일별 변경사항

- `config/etf_blocklist.json` (신규):
  ```json
  {
    "_meta": {"updated_at": "2026-05-09", "source": "Cowork weekly review"},
    "codes": [
      "069500", "114800", "122630", "233740", "251340", "252670", "252710",
      "379800", "396500", "462330"
    ]
  }
  ```
  (운영 중 발견되는 누수 종목은 여기에 점진 추가)

- `src/strategy/screener.py`:
  - `ScreeningFilter` 클래스에 `_load_etf_blocklist() -> set[str]` 정적 메서드 추가 — JSON을 한 번 로드해 캐시.
  - `_is_etf_etn(stock_code, stock_name)` 변경:
    1. `stock_code.startswith("Q")` → True (기존)
    2. `stock_code in _BLOCKLIST` → True (신규)
    3. stock_name이 비어있거나 stock_code와 동일하면 (이름 정보 결손) → True 반환 (보수적 차단, 신규)
    4. stock_name 키워드 매칭 (기존)
  - 로깅 보강: 블록리스트로 차단된 건수 별도 카운트해 `etf_count_by_blocklist`로 INFO 로그 출력.

- ScreeningWorker (위치 추정: `src/scheduler/jobs.py` 또는 워커 모듈) — DB INSERT 직전 `ScreeningFilter._is_etf_etn`을 재호출해 누수 차단:
  - 지금은 적재된 결과 자체가 ETF를 포함하므로 워커 단계에서 한 번 더 필터링하는 게 가장 확실.
  - 변경 위치는 PR 작성 시 `git grep "screening_results"` 로 INSERT 지점을 식별 후 한 줄 추가(가드 위치는 구현 단계에서 보정).

- `tests/test_strategy/test_screener.py`:
  - `_is_etf_etn` 단위 테스트 추가:
    - 블록리스트 코드 (252670) → True
    - stock_name이 stock_code와 동일 → True
    - 정상 종목 (예: 005930, "삼성전자") → False
    - Q-prefix → True
  - JSON 로딩이 실패해도 안전하게 빈 set으로 fallback하는지 확인.

## 기대 효과

1. **즉시**: 252670, 114800, 252710 등이 다음 거래일부터 스크리닝 결과/엔진 평가에서 제외 → 시그널 품질 잡음 제거
2. **MIN_CONFIDENCE 효과 분리 가능**: 05-07 상향 효과를 ETF 잡음 제거와 분리해 W20에 정확히 측정 가능
3. **장기**: 운영 중 발견되는 ETF 코드를 JSON에 추가만 하면 즉시 차단 — 코드 배포 불필요
4. **회귀 방지**: stock_name 결손 시 보수적 차단으로 향후 데이터 품질 저하에도 견고

## 리스크 및 롤백

### 리스크

- 블록리스트가 너무 공격적이면 정상 종목까지 차단 가능 — 초기 리스트는 명백한 KODEX/TIGER 코드만 포함 (10개 내외)하고 운영 중 점진 확장.
- stock_name 결손 시 보수적 차단으로 일부 정상 종목도 일시 제외될 수 있음 → 워커 응답에서 stock_name이 정상적으로 채워지면 자동 통과되므로 영구 영향 없음. 추가로 `event_logs`에 결손 케이스 카운트 로깅해 모니터링.

### 롤백

- `config/etf_blocklist.json`을 비우거나 삭제 → `_load_etf_blocklist`는 빈 set 반환 → 블록 동작 무효화 (코드 변경 없이 즉시 롤백 가능)
- 워커 단계 재검증 추가는 단일 라인이므로 git 단위로 revert 용이.
