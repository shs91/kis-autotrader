---
name: proposal-validation
description: BRIDGE_SPEC 안전 게이트에 따라 자동 구현 제안서를 검증한다. 파일 화이트리스트, 파라미터 범위, 카테고리 분류를 결정적으로 점검.
---

# Proposal Validation Skill

## 사용 시점
proposal-validator agent가 ready 제안서를 받았을 때.

## 절차
1. `docs/BRIDGE_SPEC.md`를 읽고 다음을 추출:
   - `safety_gate.forbidden_paths` (절대 변경 금지 경로)
   - `safety_gate.allowed_categories` (자동 구현 허용 카테고리)
   - `parameter_ranges` (파라미터별 허용 범위)
   - `file_count_threshold` (사이클당 최대 변경 파일 수, 기본 5)
2. 제안서의 메타데이터 검증:
   - `상태` == "ready"
   - `카테고리` ∈ `allowed_categories`
   - `우선순위` ∈ {low, medium, high, critical}
3. 제안서의 "변경 대상 파일" 섹션 검증:
   - 각 파일이 `forbidden_paths`에 없는지
   - 파일 수 ≤ `file_count_threshold`
4. 파라미터 변경이 있는 경우:
   - 각 파라미터가 `parameter_ranges`의 ±50% 이내
5. 통과: 종료(다음 단계에서 implementer가 인계받음)
6. 거절: `pipeline_mark_skipped.py --reason safety_gate_violation` 호출

## 예시
- 통과: `2026-05-15_strategy-tweak-rsi.md` (카테고리 param_tuning, 단일 파일, 파라미터 변경 ±20%)
- 거절: 카테고리 "infra" + 변경 파일이 `alembic/versions/*` → SKIP
