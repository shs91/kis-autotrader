# 스크리닝 등락률(price_change_pct) 필드명 불일치 수정

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-08
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py

## 현상 분석

DB의 `screening_results` 테이블에서 **3일간(4/6~4/8) 총 1,520건**의 스크리닝 레코드 전량의 `price_change_pct`가 **0.00%**로 기록되어 있음.

```sql
SELECT screened_at::date, AVG(price_change_pct), MIN(price_change_pct), MAX(price_change_pct)
FROM screening_results GROUP BY screened_at::date;
-- 결과: 3일 모두 avg=0, min=0, max=0
```

**원인**: `src/engine.py` 777행에서 스크리닝 결과를 DB에 저장할 때:

```python
price_change_pct=float(getattr(item, "price_change_pct", 0.0)),
```

그러나 `item`은 `VolumeRankItem` 타입이며, 이 dataclass의 등락률 필드명은 **`change_rate`**임 (`src/api/quote.py` 91행):

```python
@dataclass
class VolumeRankItem:
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float    # ← 실제 필드명
    volume: int
    market_cap: int
```

`getattr(item, "price_change_pct", 0.0)`은 존재하지 않는 속성이므로 항상 기본값 `0.0`을 반환. `getattr`의 기본값 폴백이 에러 없이 잘못된 데이터를 조용히 기록해 온 것.

## 제안 내용

`engine.py` 777행의 `getattr` 호출에서 필드명을 `price_change_pct` → `change_rate`로 수정.

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:

**변경 전** (777행):
```python
                        price_change_pct=float(getattr(item, "price_change_pct", 0.0)),
```

**변경 후**:
```python
                        price_change_pct=item.change_rate,
```

`VolumeRankItem.change_rate`는 이미 `float` 타입이므로 `float()` 래핑과 `getattr` 기본값이 불필요. 직접 속성 접근으로 변경하여, 향후 필드명 변경 시 즉시 `AttributeError`가 발생하도록 함 (silent failure 방지).

### 추가 테스트 (필요 시)

없음. 기존 테스트에서 `_record_screening_to_db`를 직접 테스트하는 케이스가 있다면 자동으로 커버됨. 런타임 버그 수정이므로 별도 테스트 추가 불필요.

## 기대 효과

- `screening_results.price_change_pct`에 실제 등락률 데이터가 정확히 기록됨
- 스크리닝 효율 분석 시 등락률 기반 분석이 가능해짐 (현재는 거래량만 유의미)
- 일일 리포트의 스크리닝 섹션에서 등락률 분포 분석 가능
- 향후 스크리닝 필터 기준(등락률 하한/상한) 도입의 기초 데이터 확보

## 롤백

- `git restore src/engine.py`
- 이미 적재된 과거 데이터(3일분)의 price_change_pct=0.0은 복구 불가 (원본 데이터 소실)
