from graph_scale_dynamics.dsl import dsl


def good_spec():
    return {"dsl_version": 1, "init": "empty",
            "terms": [{"op": "degree_anchor", "params": {"k": 8}, "coeff": {"c0": 0.3, "scale": "one"}},
                      {"op": "edge_count", "params": {}, "coeff": {"c0": 0.25, "scale": "log_N"}}],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 30}}


def test_valid_spec_passes():
    assert dsl.validate(good_spec()) == []


def test_fingerprint_is_term_order_invariant():
    a = good_spec()
    b = good_spec()
    b["terms"].reverse()
    assert dsl.fingerprint(a) == dsl.fingerprint(b)


def test_unknown_operator_rejected():
    spec = good_spec()
    spec["terms"][0] = {"op": "hausdorff_pull", "params": {}, "coeff": {"c0": 1.0, "scale": "one"}}
    assert any("unknown operator" in p for p in dsl.validate(spec))


def test_whitelist_enforced():
    problems = dsl.validate(good_spec(), operator_whitelist=["edge_count"])
    assert any("not whitelisted" in p for p in problems)


def test_complexity_budget():
    spec = good_spec()
    spec["terms"].append({"op": "square_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}})
    spec["terms"].append({"op": "triangle_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}})
    assert any("complexity" in p for p in dsl.validate(spec, complexity_budget=4))


def test_non_empty_init_rejected():
    spec = good_spec()
    spec["init"] = "random"
    assert any("init" in p for p in dsl.validate(spec))


def test_duplicate_terms_rejected():
    spec = good_spec()
    spec["terms"].append(dict(spec["terms"][0]))
    assert any("duplicate" in p for p in dsl.validate(spec))


def test_equilibrium_declaration_required():
    spec = good_spec()
    spec["dynamics"]["kind"] = "mystery"
    assert any("dynamics.kind" in p for p in dsl.validate(spec))


def test_move_mix_accepts_optional_swap_and_validates_weights():
    spec = good_spec()
    spec["dynamics"]["move_mix"] = {"add": 1.0}
    problems = dsl.validate(spec)
    assert any("delete" in problem for problem in problems)

    spec["dynamics"]["move_mix"] = {"add": "half", "delete": 0.5}
    problems = dsl.validate(spec)
    assert any("positive add/delete" in problem for problem in problems)

    spec["dynamics"]["move_mix"] = {"add": 0.4, "delete": 0.4, "swap": 0.2}
    assert dsl.validate(spec) == []

    spec["dynamics"]["move_mix"] = {"add": 0.4, "delete": 0.4, "swap": -0.2}
    assert any("nonnegative swap" in problem for problem in dsl.validate(spec))


def test_nonequilibrium_is_rejected_until_implemented():
    spec = good_spec()
    spec["dynamics"]["kind"] = "nonequilibrium"
    assert any("not implemented" in problem for problem in dsl.validate(spec))
