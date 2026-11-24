from __future__ import annotations

from graph_scale_dynamics.observability import law_kind


def _side(d, degree, reach, moved=None, capped=0):
    side = {key: {"mean": d, "seeds": 3, "of": 3} for key in ("d_s", "d_V", "d_B", "d_w")}
    side.update(mean_degree={"mean": degree}, reach={"mean": reach}, giant_fraction={"mean": 1.0},
                ended_at_cap={"seeds": capped, "of": 3})
    if moved is not None:
        side["moved"] = {"median": moved}
    return side


def test_a_law_s_kind_at_each_size_is_the_catalogue_s_read_from_its_rungs():
    empty = {key: {"mean": None} for key in ("d_s", "d_V", "d_B", "d_w", "reach")}
    empty.update(mean_degree={"mean": 0.0}, giant_fraction={"mean": 0.0})
    chains = {"rungs": [
        {"n": 4096, "empty": empty, "given": _side(None, 0.0, None),
         "more_given": {"bcc": _side(3.48, 27.1, 4.58, 2.0), "fcc": _side(3.48, 27.0, 4.56, 2.0)}},
        {"n": 16384, "empty": empty, "given": _side(None, 0.0, None),
         "more_given": {"bcc": _side(4.02, 26.0, 5.98, 2.0), "fcc": _side(4.01, 25.9, 5.97, 2.0)}}]}
    found = law_kind.kinds(chains)
    assert found == {4096: "made", 16384: "small_world"}
    assert law_kind.at(found) == "made" and law_kind.deepest(found) == "small_world" and law_kind.at({}) is None
    still = {"rungs": [{"n": 1024, "empty": empty, "given": _side(None, 0.0, None),
                        "more_given": {"bcc": _side(3.0, 8.0, 6.0, 0.001)}}]}
    assert law_kind.kinds(still) == {1024: "still"}
