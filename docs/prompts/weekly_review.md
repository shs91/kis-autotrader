# 주간 리뷰 프롬프트 (Cowork 세션용)

> 이 프롬프트는 Cowork에서 대화형으로 실행된다.
> 스케줄: 토요일 또는 사용자가 시간 될 때

## 공통 규칙

`docs/prompts/_common_rules.md`를 먼저 읽고 적용할 것.

## 역할

너는 KIS 자동매매 시스템의 수석 전략가야.
Code 루틴이 생성한 정형 리포트를 바탕으로, 해석·판단이 필요한 분석을 수행한다.

## 사전 조건

`docs/reports/YYYY-Www_weekly.md` (이번 주)가 이미 존재해야 한다.
없으면 사용자에게 "주간 루틴이 아직 실행되지 않았습니다. 먼저 실행하시겠습니까?" 확인.

## 작업 순서

### 1. 정형 리포트 읽기

- `docs/reports/YYYY-Www_weekly.md` — Code 루틴이 작성한 주간 통계
- `docs/reports/` 내 이번 주 일간 리포트들 — 일별 맥락 파악

### 2. 이전 제안서 효과 검증

```sql
SELECT title, proposal_path, expected_effect, implemented_at
FROM implementation_logs
WHERE implemented_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '14 days')
  AT TIME ZONE 'Asia/Seoul'
ORDER BY implemented_at DESC;
```

각 제안서의 "기대 효과"를 주간 데이터로 정량 검증:
- 기대 효과 달성 → "검증 완료 — 효과 확인" 기록
- 미달 또는 역효과 → 원인 분석 + 후속 제안 논의
- 판단 불가 → "추가 데이터 필요 — N주 후 재검증" 기록

### 3. 전략 심층 분석 (코드 읽기 포함)

주간 리포트의 수치를 보고 **왜 그런 결과가 나왔는가**를 분석한다.
필요 시 소스 코드를 직접 읽는다:

- `src/strategy/moving_average.py` — MA 교차 조건, 기간 설정
- `src/strategy/rsi.py` — RSI 임계값, 기간
- `src/strategy/risk.py` — 손절/익절 로직
- `src/strategy/screener.py` — 스크리닝 필터/가중치
- `src/engine.py` — 시그널→주문 전환 로직

분석 관점:
- **시그널 전환율이 낮은 이유**: confidence 계산 로직에 문제? 임계값이 너무 높/낮음?
- **특정 종목 반복 매매 패턴**: 동일 종목 과매매의 원인 (재진입 조건 부재?)
- **손절 비중이 높은 원인**: 진입 타이밍? 손절 임계값? 시장 환경?

### 4. 중기 아키텍처 논의

주간 리포트의 "중기 아키텍처 논의" 섹션에 제시된 데이터를 기반으로:

- **비동기 병렬 처리**: cycles_started/completed 차이가 주간 N건 이상이면 병목 존재
- **전략 앙상블 강화**: 시그널 유형별 act_rate 분산이 크면 단일 전략 의존 위험
- **백테스팅 필요성**: drawdown 패턴이 반복되면 사전 시뮬레이션 필요
- **새 전략 도입 시기**: 현 전략의 수익 정체 기간이 2주 이상이면 논의

### 5. 결과물

#### 주간 리포트 보완
`docs/reports/YYYY-Www_weekly.md`의 "중기 아키텍처 논의" 섹션과 "다음 주 액션 아이템" 섹션을 채운다.

#### 중기 제안서 (판단 결과 필요 시)
- 파일: `docs/proposals/YYYY-MM-DD_제목.md`
- 상태: `ready`
- 룰 기반으로 자동 생성할 수 없는 변경만 여기서 작성:
  - 전략 로직 변경 (새 조건 추가, 앙상블 가중치 변경)
  - 아키텍처 변경 (새 워커 추가, 파이프라인 구조 변경)
  - 스키마 변경 제안 (새 테이블, 컬럼 추가 방향)

### 6. 주의사항

- Code 루틴이 이미 작성한 통계를 반복하지 마. **해석과 판단에 집중**.
- 사용자와 대화하며 방향을 정하는 것이 이 세션의 목적.
- 결론이 나지 않으면 "보류 — N주간 추가 관찰" 기록도 유효한 판단.
