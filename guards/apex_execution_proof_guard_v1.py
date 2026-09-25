from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


class ExecutionProofViolation(RuntimeError):
    """Raised when a board cannot prove canonical engine execution."""
    pass


REQUIRED_EXECUTION_FIELDS = {
    "sport",
    "mode",
    "engine_version",
    "runtime_id",
    "bundle_sha256",
    "engine_sha256",
    "selector_id",
    "mc_worlds",
    "public_field_sims",
    "machine_receipt_sha256",
    "engine_owned_board",
    "chat_synthesized",
}


def _valid_sha256(value: object) -> bool:
    s = str(value).lower()
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def require_canonical_execution_proof(
    receipt: dict,
    *,
    expected_sport: str,
    expected_mode: str,
    expected_runtime_id: str | None = None,
    requested_field_size: int | None = None,
) -> dict:
    """
    Global fail-closed execution provenance gate.

    No board may be reported as TOOL_PROVEN_EXECUTED / EXECUTION_COMPLETE
    unless this function passes on an engine-owned machine receipt.
    """
    missing = sorted(REQUIRED_EXECUTION_FIELDS - set(receipt))
    if missing:
        raise ExecutionProofViolation(f"missing execution provenance={missing}")

    if str(receipt["sport"]).upper() != expected_sport.upper():
        raise ExecutionProofViolation(
            f"sport mismatch: got={receipt['sport']} expected={expected_sport}"
        )
    if str(receipt["mode"]).upper() != expected_mode.upper():
        raise ExecutionProofViolation(
            f"mode mismatch: got={receipt['mode']} expected={expected_mode}"
        )

    if expected_runtime_id is not None and receipt["runtime_id"] != expected_runtime_id:
        raise ExecutionProofViolation(
            f"runtime mismatch: got={receipt['runtime_id']} expected={expected_runtime_id}"
        )

    if not bool(receipt["engine_owned_board"]):
        raise ExecutionProofViolation("board is not engine-owned")
    if bool(receipt["chat_synthesized"]):
        raise ExecutionProofViolation("chat-synthesized board is prohibited")

    if int(receipt["mc_worlds"]) <= 0:
        raise ExecutionProofViolation("mc_worlds must be > 0")
    if int(receipt["public_field_sims"]) <= 0:
        raise ExecutionProofViolation("public_field_sims must be > 0")

    if requested_field_size is not None:
        if "field_size" not in receipt:
            raise ExecutionProofViolation("field_size missing from execution receipt")
        if int(receipt["field_size"]) != int(requested_field_size):
            raise ExecutionProofViolation(
                f"field size mismatch: got={receipt['field_size']} "
                f"requested={requested_field_size}"
            )

    for key in ("bundle_sha256", "engine_sha256", "machine_receipt_sha256"):
        if not _valid_sha256(receipt[key]):
            raise ExecutionProofViolation(f"invalid sha256 field={key}")

    selector_id = str(receipt["selector_id"]).strip()
    engine_version = str(receipt["engine_version"]).strip()
    runtime_id = str(receipt["runtime_id"]).strip()
    if not selector_id:
        raise ExecutionProofViolation("selector_id is empty")
    if not engine_version:
        raise ExecutionProofViolation("engine_version is empty")
    if not runtime_id:
        raise ExecutionProofViolation("runtime_id is empty")

    canonical = {
        "sport": str(receipt["sport"]).upper(),
        "mode": str(receipt["mode"]).upper(),
        "engine_version": engine_version,
        "runtime_id": runtime_id,
        "selector_id": selector_id,
        "mc_worlds": int(receipt["mc_worlds"]),
        "public_field_sims": int(receipt["public_field_sims"]),
        "field_size": int(receipt["field_size"]) if "field_size" in receipt else None,
        "bundle_sha256": str(receipt["bundle_sha256"]).lower(),
        "engine_sha256": str(receipt["engine_sha256"]).lower(),
        "machine_receipt_sha256": str(receipt["machine_receipt_sha256"]).lower(),
        "engine_owned_board": True,
        "chat_synthesized": False,
    }
    digest = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    canonical["proof_guard_sha256"] = digest
    canonical["status"] = "CANONICAL_EXECUTION_PROOF_PASS"
    return canonical


NFL_SS_YARDS_RUNTIME_ID = "APEX_NFL_SS_YARDS_CHUNK_STREAM_RUNTIME_v1"


def preseal_nfl_ss_yards(
    receipt: dict,
    *,
    requested_field_size: int,
    requested_entries: int,
    board_size: int,
) -> dict:
    """
    NFL SS-YARDS fail-closed terminal seal.

    The gate validates execution provenance only. It does not generate, rank,
    simulate, or select lineups.
    """
    proof = require_canonical_execution_proof(
        receipt,
        expected_sport="NFL",
        expected_mode="SS_YARDS",
        expected_runtime_id=NFL_SS_YARDS_RUNTIME_ID,
        requested_field_size=requested_field_size,
    )

    if requested_entries < 1:
        raise ExecutionProofViolation("requested_entries must be positive")
    if board_size != requested_entries:
        raise ExecutionProofViolation(
            f"board size mismatch: got={board_size} requested={requested_entries}"
        )

    if receipt.get("stat_authority") != "RUSHING_PLUS_RECEIVING_YARDS":
        raise ExecutionProofViolation(
            "invalid SS-YARDS stat authority; rushing+receiving yards required"
        )
    if bool(receipt.get("passing_yards_enabled", True)):
        raise ExecutionProofViolation("passing yards must be disabled")
    if bool(receipt.get("qb_eligible", True)):
        raise ExecutionProofViolation("QB eligibility must be false")
    if bool(receipt.get("k_dst_eligible", True)):
        raise ExecutionProofViolation("K/DST eligibility must be false")

    proof["requested_entries"] = requested_entries
    proof["board_size"] = board_size
    proof["stat_authority"] = receipt["stat_authority"]
    proof["passing_yards_enabled"] = False
    proof["qb_eligible"] = False
    proof["k_dst_eligible"] = False
    proof["status"] = "NFL_SS_YARDS_PRESEAL_PASS"
    return proof
