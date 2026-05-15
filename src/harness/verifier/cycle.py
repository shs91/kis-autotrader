"""Verifier 결과를 proposals 상태 머신에 반영.

contract.passed이면 IN_FLIGHT → IMPLEMENTED, 아니면 → FAILED(reason 첨부).
호출자는 cycle_id로 영향 범위를 좁힌다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.repository import ProposalRepository
from src.harness.verifier.contract import ContractResult
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def apply_verification_result(
    *,
    session: Session,
    cycle_id: str,
    contract: ContractResult,
) -> None:
    """contract 결과로 cycle_id의 모든 IN_FLIGHT 제안서 상태 전이."""
    repo = ProposalRepository(session)
    in_flights = repo.list_in_flight_for_cycle(cycle_id)
    if not in_flights:
        logger.info("cycle %s: no IN_FLIGHT proposals to update", cycle_id)
        return

    if contract.passed:
        for p in in_flights:
            repo.mark_implemented(p.id)
        logger.info(
            "cycle %s: %d proposals → IMPLEMENTED", cycle_id, len(in_flights),
        )
        return

    reason = "; ".join(contract.reasons) or "contract failed without reasons"
    for p in in_flights:
        repo.mark_failed(p.id, reason=reason[:1000])
    logger.warning(
        "cycle %s: %d proposals → FAILED — %s",
        cycle_id, len(in_flights), reason[:200],
    )
