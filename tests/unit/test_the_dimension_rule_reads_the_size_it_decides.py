from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions import starts_rule as FS
from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS
from graph_scale_dynamics.research import dimension_rule as R

COLUMNS = list(VALUE_COLUMNS)


def row(n, *, degree=6.0, piece=1.0, d=2.9):
    values = {"n": n, "d_s": 3.1, "d_V": d, "d_B": d, "d_w": 2.0, "reach": 1.5 * n ** (1 / 3.0),
              "mean_degree": degree, "giant_fraction": piece, "triangles_per_node": 0.0, "squares_per_node": 1.0,
              "kappa": 0.0, "moved": None}
    return [values[c] for c in COLUMNS]


READ_EVERYWHERE = [row(1024), row(4096), row(16384)]
DENSE_AT_THE_TOP = [row(1024), row(4096), row(16384, degree=16.0)]
IN_PIECES_AT_THE_TOP = [row(1024), row(4096), row(16384, degree=1.1, piece=0.06)]
PARK = E.Decision(law="law-x", action=E.STOP, rule=FS.ALIKE, reason="every start ends alike", at_n=16384,
                  next_n=None)


def test_a_reader_still_reads_a_chain_on_its_usable_sizes():
    found = R.block({"empty": DENSE_AT_THE_TOP}, COLUMNS, {})
    assert found["tier"] == 1 and found["chains"]["empty"]["sizes"] == [1024, 4096]
    assert "not_read_at" not in found


def test_the_decision_path_does_not_count_a_chain_its_top_size_could_not_read():
    for top in (DENSE_AT_THE_TOP, IN_PIECES_AT_THE_TOP):
        found = R.block({"empty": top}, COLUMNS, {}, read_at_top=True)
        assert found["tier"] is None and found["chains"] == {}
        assert found["not_read_at"] == {"n": 16384, "chains": ["empty"]}


def test_a_chain_read_at_the_top_still_extends():
    found = R.block({"empty": READ_EVERYWHERE}, COLUMNS, {}, read_at_top=True)
    assert found["tier"] == 1 and found["chains"]["empty"]["sizes"] == [1024, 4096, 16384]
    assert "not_read_at" not in found


def test_a_stale_chain_leaves_the_others_their_tier():
    found = R.block({"empty": DENSE_AT_THE_TOP, "cubic": READ_EVERYWHERE}, COLUMNS, {"cubic": ["unmoved", 1.0]},
                    read_at_top=True)
    assert set(found["chains"]) == {"cubic"} and found["chains"]["cubic"]["kind"] == "kept_d"
    assert found["tier"] == 3 and found["not_read_at"]["chains"] == ["empty"]


def test_the_park_stands_when_no_chain_read_the_size_it_decides():
    policy = E.Policy(dimension_extends=True)
    stale = R.block({"empty": DENSE_AT_THE_TOP}, COLUMNS, {}, read_at_top=True)
    assert FS.shown(PARK, {"dimension": stale}, policy, 65536) is PARK
    fresh = R.block({"empty": READ_EVERYWHERE}, COLUMNS, {}, read_at_top=True)
    extended = FS.shown(PARK, {"dimension": fresh}, policy, 65536)
    assert (extended.action, extended.rule, extended.next_n) == (E.RUN_NEXT, FS.DIMENSION, 65536)



def test_a_law_read_only_through_a_kept_shape_is_parked_as_its_own_class():
    from dataclasses import replace

    from graph_scale_dynamics.decisions import gates as G
    kept = R.block({"cubic": READ_EVERYWHERE}, COLUMNS, {"cubic": ["holds", 1.0]}, read_at_top=True)
    assert kept["tier"] == FS.KEPT_SHAPE_TIER
    on = E.Policy(dimension_extends=True, let_through_rule=G.LET_THROUGH_RULE, kept_shape_park=True,
                  salt_shares=((FS.KEPT_SHAPE, 16384, 0.0),))
    parked = FS.shown(PARK, {"dimension": kept}, on, 65536)
    assert (parked.action, parked.rule, parked.next_n) == (E.STOP, FS.KEPT_SHAPE, None)
    assert parked.facts["kept_shape"] == {"tier": 3, "parked_over": FS.ALIKE} and parked.facts["dimension"] == kept
    assert parked.reason.startswith("kept shape: the dimension test reads only lattice starts that kept their shape")
    assert FS.KEPT_SHAPE in E.PARKING_RULES and FS.KEPT_SHAPE in G.BY_NAME
    through = FS.shown(PARK, {"dimension": kept}, replace(on, salt_shares=((FS.KEPT_SHAPE, 16384, 1.0),)), 65536)
    assert (through.action, through.rule, through.next_n) == (E.RUN_NEXT, FS.DIMENSION, 65536)
    assert through.facts["salted"] == [FS.KEPT_SHAPE] and "let through past kept_shape" in through.reason
    off = FS.shown(PARK, {"dimension": kept}, replace(on, kept_shape_park=False), 65536)
    assert (off.action, off.rule) == (E.RUN_NEXT, FS.DIMENSION) and "salted" not in off.facts
    grown = R.block({"empty": READ_EVERYWHERE}, COLUMNS, {}, read_at_top=True)
    assert FS.shown(PARK, {"dimension": grown}, on, 65536).rule == FS.DIMENSION, "a grown dimension is never parked"
    changed = R.block({"cubic": READ_EVERYWHERE}, COLUMNS, {"cubic": ["partly", 1.0]}, read_at_top=True)
    assert changed["tier"] == 2 and FS.shown(PARK, {"dimension": changed}, on, 65536).rule == FS.DIMENSION


def test_the_kept_shape_park_moves_no_fingerprint_left_off():
    from dataclasses import replace
    policy = E.Policy(dimension_extends=True)
    assert E.policy_fingerprint(policy) == E.policy_fingerprint(replace(policy, kept_shape_park=False))
    assert E.policy_fingerprint(policy) != E.policy_fingerprint(replace(policy, kept_shape_park=True))
