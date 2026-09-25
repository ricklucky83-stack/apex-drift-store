from guards.nfl_showdown_preseal_guard_v1 import SDLineup, PresealViolation, preseal_nfl_showdown

SAL = {
    "A":10000,"B":9000,"C":8000,"D":7000,"E":6000,"F":5000,
    "G":4000,"H":3000,"I":2000,"J":1000,"K":6000
}
GOOD_RECEIPT = {
    "engine_version":"1.33.403",
    "bundle_sha256":"a"*64,
    "engine_sha256":"b"*64,
    "selector_id":"NFL_SD_150MAX_VECTOR_PORTFOLIO_SELECT_v1",
    "mc_worlds":20000,
    "public_field_sims":88235,
    "machine_receipt_sha256":"c"*64,
}

def expect_fail(fn):
    try:
        fn()
    except PresealViolation:
        return
    raise AssertionError("expected PresealViolation")

def test_over_cap_rejected():
    lu = SDLineup("A",("B","C","D","E","K"),SAL,"shootout")
    expect_fail(lambda: preseal_nfl_showdown([lu], GOOD_RECEIPT, 1))

def test_missing_provenance_rejected():
    lu = SDLineup("G",("F","H","I","J","E"),SAL,"low")
    bad = dict(GOOD_RECEIPT)
    bad.pop("machine_receipt_sha256")
    expect_fail(lambda: preseal_nfl_showdown([lu], bad, 1, min_salary=0))

def test_duplicate_board_rejected():
    lu = SDLineup("G",("F","H","I","J","E"),SAL,"low")
    expect_fail(lambda: preseal_nfl_showdown([lu,lu], GOOD_RECEIPT, 2, min_salary=0))

def test_large_board_core_collapse_rejected():
    salary = {f"P{i}":1000 for i in range(220)}
    lineups=[]
    for n in range(40):
        flex=("P1","P2",f"P{10+n}",f"P{60+n}",f"P{110+n}")
        lineups.append(SDLineup("P0",flex,salary,f"script-{n%4}"))
    expect_fail(lambda: preseal_nfl_showdown(
        lineups, GOOD_RECEIPT, 40, min_salary=0, max_salary=50000,
        min_captains_large_board=1, max_three_player_core_share=0.85
    ))

def test_script_coverage_required():
    salary = {f"P{i}":1000 for i in range(260)}
    lineups=[]
    for n in range(40):
        cpt=f"P{n%4}"
        flex=(f"P{20+n}",f"P{70+n}",f"P{120+n}",f"P{170+n}",f"P{210+n}")
        lineups.append(SDLineup(cpt,flex,salary,"one-script"))
    expect_fail(lambda: preseal_nfl_showdown(
        lineups, GOOD_RECEIPT, 40, min_salary=0, max_salary=50000,
        max_three_player_core_share=1.0
    ))
