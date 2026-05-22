#!/usr/bin/env python3
"""Verifier 사이클 CLI 진입점.

run_auto_implement.sh가 `claude -p` 직후 호출한다. 사용:
    python -m scripts.harness.run_verifier --base-ref <tag> --head-ref HEAD --out path.json

exit code:
    0  contract pass
    2  contract fail (artifact 부재 또는 검증 실패)
    3  runner internal error

--self-test 옵션은 실제 명령 호출 없이 가짜 통과 결과를 출력한다 (CLI smoke test 용).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.harness.verifier.contract import ContractResult, evaluate_contract
from src.harness.verifier.diff import ChangedFile, DiffSummary
from src.harness.verifier.parsers import (
    MypyArtifact,
    PytestArtifact,
    RuffArtifact,
)
from src.harness.verifier.runner import VerifierRunner

REPO_ROOT = Path(__file__).resolve().parents[2]


def _self_test() -> ContractResult:
    return evaluate_contract(
        pytest=PytestArtifact(tests=1, failures=0, errors=0),
        mypy=MypyArtifact(files_checked=1),
        ruff=RuffArtifact(),
        diff=DiffSummary(files=[ChangedFile(path="self-test", additions=0, deletions=0)]),
    )


def _mirror_cycle_artifacts(result: ContractResult) -> None:
    """HARNESS_CYCLE_ARTIFACTS_PATH가 설정된 경우에만 표준 산출물 파일을 기록.

    Stop 훅(`scripts/claude-hooks/run_hook.py`)이 동일 경로를 읽어 검증 수행
    여부를 판정한다. 환경변수 미설정(수동 실행)이면 아무것도 쓰지 않는다.
    """
    target = os.environ.get("HARNESS_CYCLE_ARTIFACTS_PATH")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_jsonb()["artifacts"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. argparse로 파싱 → Verifier 실행 → JSON 출력 → exit code 반환."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-ref", default="HEAD~1", help="git diff 시작 ref")
    p.add_argument("--head-ref", default="HEAD", help="git diff 종료 ref")
    p.add_argument("--out", type=Path, required=True, help="결과 JSON 출력 경로")
    p.add_argument("--self-test", action="store_true", help="실제 명령 호출 없이 통과 결과")
    args = p.parse_args(argv)

    if args.self_test:
        result = _self_test()
    else:
        runner_result = VerifierRunner(repo_root=REPO_ROOT).run(
            base_ref=args.base_ref, head_ref=args.head_ref,
        )
        if runner_result.runner_error:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(
                    {"passed": False, "runner_error": runner_result.runner_error},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            print(f"runner error: {runner_result.runner_error}", file=sys.stderr)
            return 3
        result = evaluate_contract(
            pytest=runner_result.pytest,
            mypy=runner_result.mypy,
            ruff=runner_result.ruff,
            diff=runner_result.diff,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result.to_jsonb(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 사이클 컨텍스트(orchestrator가 HARNESS_CYCLE_ARTIFACTS_PATH를 export)에서는
    # Stop 훅이 읽는 표준 산출물 파일을 함께 기록한다. top-level pytest/mypy/ruff 키가
    # 모두 존재해야 Stop 훅이 "검증이 실제로 수행됨"을 인정하고 종료를 허용한다.
    # (pass/fail 자체는 본 CLI의 exit code와 후처리 verifier가 강제하므로,
    #  여기서는 contract 통과 여부와 무관하게 4종 아티팩트 dict를 그대로 기록한다.)
    _mirror_cycle_artifacts(result)

    if not result.passed:
        for reason in result.reasons:
            print(f"[verifier] FAIL: {reason}", file=sys.stderr)
        return 2
    if result.warnings:
        for w in result.warnings:
            print(f"[verifier] WARN: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
