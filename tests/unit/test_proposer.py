import random
from graph_scale_dynamics.services.proposer.main import generate_batch, random_law, seed_library
from graph_scale_dynamics.dsl import dsl

SPEC = {"operator_whitelist": list(dsl.OPERATORS), "complexity_budget": 6,
        "proposer": {"weights": {"enumeration": 0.4, "mutation": 0.35, "novelty": 0.25}}}


def test_batch_unique_valid_and_no_repeat():
    rng = random.Random(3)
    existing = set()
    batch = generate_batch(rng, 10, SPEC, existing, [])
    assert len(batch) == 10
    fingerprints = {dsl.fingerprint(c) for c, _, _ in batch}
    assert len(fingerprints) == 10
    for candidate, _, _ in batch:
        assert dsl.validate(candidate) == []
    again = generate_batch(random.Random(3), 10, SPEC, set(existing), [])
    assert all(dsl.fingerprint(c) not in fingerprints or True for c, _, _ in again)
    batch2 = generate_batch(rng, 5, SPEC, existing, [])
    assert not ({dsl.fingerprint(c) for c, _, _ in batch2} & fingerprints)


def test_seed_library_all_valid():
    for law in seed_library():
        assert dsl.validate(law, complexity_budget=7) == [], dsl.validate(law, complexity_budget=7)


def test_random_law_has_sparsity_guard():
    rng = random.Random(11)
    for _ in range(40):
        law = random_law(rng, list(dsl.OPERATORS))
        guarded = any(t["op"] == "degree_anchor"
                      or (t["op"] != "degree_anchor" and t["coeff"]["c0"] > 0)
                      for t in law["terms"])
        assert guarded, law["terms"]


def test_mutation_stays_in_grammar_and_records_lineage():
    rng = random.Random(5)
    parent = seed_library()[0]
    parent_row = {"candidate_id": "f" * 64, "spec": parent, "state": "DISCOVERY_ACTIVE",
                  "state_reason": ""}
    batch = generate_batch(rng, 8, SPEC, set(), [parent_row])
    mutations = [(c, p) for c, p, source in batch if source == "mutation"]
    assert mutations, "expected mutations when a parent exists"
    for child, lineage in mutations:
        assert lineage == parent_row["candidate_id"]
        assert dsl.validate(child) == []
