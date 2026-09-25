from guards.apex_execution_proof_guard_v1 import (
    ExecutionProofViolation,
    NFL_SS_YARDS_RUNTIME_ID,
    preseal_nfl_ss_yards,
    require_canonical_execution_proof,
)


GOOD = {
    "sport": "NFL",
    "mode": "SS_YARDS",
    "engine_version": "1.33.403",
    "runtime_id": NFL_SS_YARDS_RUNTIME_ID,
    "bundle_sha256": "a" * 64,
    "engine_sha256": "b" * 64,
    "selector_id": "NFL_SS_YARDS_3MAX_FIELD_RELATIVE_JOINT_v1",
    "mc_worlds": 50000,
    "public_field_sims": 1189,
    "machine_receipt_sha256": "c" * 64,
    "engine_owned_board": True,
    "chat_synthesized": False,
    "field_size": 1189,
    "stat_authority": "RUSHING_PLUS_RECEIVING_YARDS",
    "passing_yards_enabled": False,
    "qb_eligible": False,
    "k_dst_eligible": False,
}


def expect_fail(fn):
    try:
        fn()
    except ExecutionProofViolation:
        return
    raise AssertionError("expected ExecutionProofViolation")


def test_chat_local_board_rejected():
    bad = dict(GOOD)
    bad["chat_synthesized"] = True
    expect_fail(lambda: preseal_nfl_ss_yards(
        bad, requested_field_size=1189, requested_entries=3, board_size=3
    ))


def test_missing_machine_receipt_rejected():
    bad = dict(GOOD)
    bad.pop("machine_receipt_sha256")
    expect_fail(lambda: require_canonical_execution_proof(
        bad, expected_sport="NFL", expected_mode="SS_YARDS"
    ))


def test_wrong_runtime_rejected():
    bad = dict(GOOD)
    bad["runtime_id"] = "IN_CHAT_FALLBACK_SIM"
    expect_fail(lambda: preseal_nfl_ss_yards(
        bad, requested_field_size=1189, requested_entries=3, board_size=3
    ))


def test_zero_public_field_rejected():
    bad = dict(GOOD)
    bad["public_field_sims"] = 0
    expect_fail(lambda: preseal_nfl_ss_yards(
        bad, requested_field_size=1189, requested_entries=3, board_size=3
    ))


def test_field_size_mismatch_rejected():
    bad = dict(GOOD)
    bad["field_size"] = 713
    expect_fail(lambda: preseal_nfl_ss_yards(
        bad, requested_field_size=1189, requested_entries=3, board_size=3
    ))


def test_board_size_mismatch_rejected():
    expect_fail(lambda: preseal_nfl_ss_yards(
        GOOD, requested_field_size=1189, requested_entries=3, board_size=2
    ))


def test_ss_yards_scoring_contract_rejected_when_wrong():
    bad = dict(GOOD)
    bad["passing_yards_enabled"] = True
    expect_fail(lambda: preseal_nfl_ss_yards(
        bad, requested_field_size=1189, requested_entries=3, board_size=3
    ))


def test_valid_machine_owned_ss_yards_receipt_passes():
    out = preseal_nfl_ss_yards(
        GOOD, requested_field_size=1189, requested_entries=3, board_size=3
    )
    assert out["status"] == "NFL_SS_YARDS_PRESEAL_PASS"
    assert len(out["proof_guard_sha256"]) == 64
