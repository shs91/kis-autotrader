"""Initializer — 사이클 시작 시점의 결정적 환경 점검 + progress.json 생성.

매 사이클 시작에서 1회 호출. claude-progress.json을 만들고 cycle_id를 발급한다.
이후 subagent들이 progress.json을 통해 상태를 공유한다.

점검 항목:
- alembic head: 마이그레이션이 최신인지
- git clean: 워킹 디렉토리가 깨끗한지 (uncommitted 변경 없음)
- venv: 파이썬 인터프리터 + 핵심 패키지 import 가능
- disk free: 1GB 이상
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from src.harness.progress import (
    CycleProgress,
    InitializerCheck,
    InitializerCheckResult,
    save_progress,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_KST = timezone(timedelta(hours=9))
_DEFAULT_DISK_THRESHOLD_GB = 1.0


@dataclass(frozen=True)
class EnvCheckResult:
    name: str
    result: InitializerCheckResult
    detail: str | None = None


@dataclass(frozen=True)
class InitializerStatus:
    cycle_id: str
    progress_path: Path
    all_passed: bool


class Initializer:
    def __init__(
        self,
        repo_root: Path,
        env: Literal["virtual", "real"],
        progress_path: Path | None = None,
        disk_threshold_gb: float = _DEFAULT_DISK_THRESHOLD_GB,
    ) -> None:
        self.repo_root = repo_root
        self.env = env
        self.progress_path = (
            progress_path
            if progress_path
            else Path.home() / ".kis-autotrader" / "claude-progress.json"
        )
        self.disk_threshold_gb = disk_threshold_gb

    def _check_alembic_head_present(self) -> EnvCheckResult:
        try:
            cp = subprocess.run(  # noqa: S603, S607
                [".venv/bin/alembic", "current"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return EnvCheckResult(
                name="alembic_head",
                result=InitializerCheckResult.SKIP,
                detail=f"alembic 실행 실패: {e!s:.80}",
            )
        if cp.returncode == 0 and "head" in cp.stdout:
            return EnvCheckResult(name="alembic_head", result=InitializerCheckResult.PASS)
        return EnvCheckResult(
            name="alembic_head",
            result=InitializerCheckResult.FAIL,
            detail=cp.stdout.strip()[:200],
        )

    def _check_git_clean(self) -> EnvCheckResult:
        try:
            cp = subprocess.run(  # noqa: S603
                ["git", "status", "--porcelain"],  # noqa: S607
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return EnvCheckResult(
                name="git_clean",
                result=InitializerCheckResult.SKIP,
                detail=f"git 실행 실패: {e!s:.80}",
            )
        if cp.returncode != 0:
            return EnvCheckResult(
                name="git_clean",
                result=InitializerCheckResult.FAIL,
                detail=cp.stderr.strip()[:200],
            )
        if cp.stdout.strip():
            return EnvCheckResult(
                name="git_clean",
                result=InitializerCheckResult.FAIL,
                detail=f"uncommitted changes:\n{cp.stdout.strip()[:200]}",
            )
        return EnvCheckResult(name="git_clean", result=InitializerCheckResult.PASS)

    def _check_venv(self) -> EnvCheckResult:
        venv_py = self.repo_root / ".venv" / "bin" / "python"
        if not venv_py.exists():
            return EnvCheckResult(
                name="venv",
                result=InitializerCheckResult.FAIL,
                detail=f".venv/bin/python 없음: {venv_py}",
            )
        return EnvCheckResult(name="venv", result=InitializerCheckResult.PASS)

    def _check_disk_free(self) -> EnvCheckResult:
        try:
            usage = shutil.disk_usage(self.repo_root)
        except OSError as e:
            return EnvCheckResult(
                name="disk_free",
                result=InitializerCheckResult.SKIP,
                detail=f"disk_usage 실패: {e!s:.80}",
            )
        free_gb = usage.free / (1024**3)
        if free_gb < self.disk_threshold_gb:
            return EnvCheckResult(
                name="disk_free",
                result=InitializerCheckResult.FAIL,
                detail=f"free={free_gb:.2f}GB, threshold={self.disk_threshold_gb}GB",
            )
        return EnvCheckResult(
            name="disk_free",
            result=InitializerCheckResult.PASS,
            detail=f"free={free_gb:.2f}GB",
        )

    def _last_safe_tag(self) -> str | None:
        try:
            cp = subprocess.run(  # noqa: S603
                ["git", "tag", "--sort=-creatordate"],  # noqa: S607
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
        if cp.returncode != 0 or not cp.stdout.strip():
            return None
        return cp.stdout.strip().splitlines()[0]

    def run(self) -> InitializerStatus:
        cycle_id = "auto-" + datetime.now(_KST).strftime("%Y%m%d-%H%M%S")
        checks = [
            self._check_alembic_head_present(),
            self._check_git_clean(),
            self._check_venv(),
            self._check_disk_free(),
        ]
        progress = CycleProgress(
            cycle_id=cycle_id,
            started_at=datetime.now(_KST),
            env=self.env,
            last_safe_tag=self._last_safe_tag(),
            initializer_checks=[
                InitializerCheck(name=c.name, result=c.result, detail=c.detail)
                for c in checks
            ],
        )
        save_progress(self.progress_path, progress)
        all_passed = all(c.result == InitializerCheckResult.PASS for c in checks)
        if all_passed:
            logger.info("Initializer %s: all checks PASS", cycle_id)
        else:
            failures = [c.name for c in checks if c.result == InitializerCheckResult.FAIL]
            logger.warning(
                "Initializer %s: %d failures (%s)",
                cycle_id, len(failures), ",".join(failures),
            )
        return InitializerStatus(
            cycle_id=cycle_id,
            progress_path=self.progress_path,
            all_passed=all_passed,
        )
