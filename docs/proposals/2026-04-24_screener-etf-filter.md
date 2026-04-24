# 스크리너 ETF/ETN/레버리지 종목 필터링 추가

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-24
- 상태: implemented
- 우선순위: high
- 카테고리: refactor
- 관련파일: src/strategy/screener.py

## 현상 분석

최근 7일간(04/18~04/24 KST) 시스템이 매일 1,300~2,200 사이클을 정상 실행하고 110~143종목을 스크리닝했으나, **전략 시그널 0건, 매매전환 0건**이다.

스크리닝 상위 종목 분석 결과, 거래량 기반 랭킹 상위를 레버리지/인버스 ETF·ETN이 독점하고 있다:

| 순위 | 종목 | 유형 | 평균 등락률 |
|------|------|------|------------|
| 1 | KODEX 200선물인버스2X (252670) | 레버리지 ETF | -1.27% |
| 1 | KODEX 2차전지산업레버리지 (462330) | 레버리지 ETF | -4.42% |
| 2 | KODEX 인버스 (114800) | 인버스 ETF | -0.61% |
| 2 | 삼성 인버스 2X WTI원유 선물 ETN (Q530036) | 레버리지 ETN | -3.98% |
| 3 | N2 인버스 레버리지 WTI원유 선물 ETN(H) (Q550043) | 레버리지 ETN | -6.67% |

이들 종목은:
1. 거래량이 수십억 주 단위로 개별 종목 대비 압도적이어서 거래량 랭킹 상위를 독점
2. MA 교차/RSI 전략과의 적합성이 낮음 (레버리지 상품은 기초지수 추종으로 개별주 패턴과 다름)
3. 스크리닝 슬롯(MAX_SCREENED_STOCKS=10)을 차지하여 정상 개별 종목의 전략 평가 기회를 차단

코드 분석(src/engine.py:929-930) 결과, 전략이 HOLD 시그널을 반환하면 DB에 기록되지 않으므로, 스크리닝된 ETF/ETN 종목에 대해 전략이 HOLD를 반환하는 것이 **시그널 0건**의 직접 원인이다.

## 제안 내용

`src/strategy/screener.py`에 ETF/ETN/레버리지 종목 필터링 로직을 추가한다.

한국 시장의 ETF/ETN 종목 코드 패턴:
- **ETF**: 6자리 숫자, 일반적으로 `1xxxxx`, `2xxxxx`, `3xxxxx`, `4xxxxx` 대역 중 특정 패턴. 보다 안정적인 방법으로 종목명에 "KODEX", "TIGER", "KBSTAR", "ARIRANG", "SOL", "ACE", "HANARO" 등 ETF 브랜드명 포함 여부로 판별.
- **ETN**: 종목 코드가 `Q`로 시작하거나, 종목명에 "ETN" 포함.
- **레버리지/인버스**: 종목명에 "레버리지", "인버스", "2X", "곱버스" 포함.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/screener.py`:
  - `_is_etf_etn(stock_code: str, stock_name: str) -> bool` 정적/클래스 메서드 추가
    - 종목 코드가 `Q`로 시작하면 `True` (ETN)
    - 종목명에 다음 키워드 포함 시 `True`: "KODEX", "TIGER", "KBSTAR", "ARIRANG", "SOL ", "ACE ", "HANARO", "ETN", "레버리지", "인버스", "2X", "곱버스"
    - 그 외 `False`
  - 스크리닝 결과 필터링 단계에서 `_is_etf_etn()` 통과 종목 제외
  - 로그: 필터링된 종목 수를 INFO 레벨로 기록

- `tests/test_strategy/test_screener.py` (신규 또는 기존 파일에 추가):
  - `test_is_etf_etn_filters_kodex`: KODEX ETF 종목 필터링 확인
  - `test_is_etf_etn_filters_etn_code`: Q로 시작하는 ETN 코드 필터링 확인
  - `test_is_etf_etn_passes_normal_stock`: 일반 종목(삼성전자 등) 통과 확인
  - `test_screening_excludes_etf`: 스크리닝 결과에서 ETF 제외 확인

### 추가 테스트
- ETF 브랜드명 각각에 대한 필터링 테스트
- 경계 케이스: "TIGER" 가 포함된 일반 종목명이 있을 경우 대비 (현실적으로 한국 시장에서 거의 없음)

## 기대 효과

- 스크리닝 슬롯에서 ETF/ETN/레버리지 종목 제거 → 개별 종목이 전략 평가 기회 획득
- 개별 종목에 대해 MA 교차/RSI 전략이 유의미한 시그널 생성 가능성 회복
- 스크리닝 전환율(현재 0.0%) 개선 기대

## 롤백

- `src/strategy/screener.py`에서 `_is_etf_etn()` 호출부를 주석 처리 또는 제거
- 필터링 로직은 독립 메서드이므로 기존 코드에 영향 없이 원복 가능
