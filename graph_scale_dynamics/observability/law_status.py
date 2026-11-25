from __future__ import annotations

from graph_scale_dynamics.domain.model import CandidateState as S

WAITING, SETTLED, RUNNING, NOT_RUN = "waiting to be extended", "settled", "running", "not started"
GATE, BUDGET, CONDITION, LADDER = "a gate", "its budget", "a condition", "the top of its ladder"
REASON_PREFIX = "decision engine: "
NOT_RUN_STATES = frozenset({S.PROPOSED.value, S.VALIDATING.value, S.PILOT_QUEUED.value})
RUNNING_STATES = frozenset({S.PILOT_RUNNING.value, S.BASE_BLOCK_RUNNING.value, S.EXTENDING.value,
                            S.DISCOVERY_ACTIVE.value, S.ROBUSTNESS_ACTIVE.value})
SETTLED_STATES = frozenset({S.PARKED.value, S.STOPPED.value, S.QUARANTINE.value, S.REJECTED_HEALTH.value,
                            S.REJECTED_SCALING.value, S.REJECTED_STATIC.value})
OVER_BUDGET = "over_budget"


def rule_of(state_reason) -> str | None:
    text = str(state_reason or "")
    if not text.startswith(REASON_PREFIX):
        return None
    rule = text[len(REASON_PREFIX):].strip()
    return rule or None


def settled_by(rule) -> str:
    from graph_scale_dynamics.decisions import gates as G
    if rule is None:
        return CONDITION
    if str(rule) == OVER_BUDGET:
        return BUDGET
    return GATE if G.today(str(rule)) in G.BY_NAME else CONDITION


def _n(value) -> str:
    return f"N={int(value):,}"


def status(state, *, rule=None, at_n=None, next_n=None, region=None) -> dict:
    state = str(state or "")
    at = int(at_n) if at_n is not None else None
    if state == S.DONE.value:
        text = (f"waiting to be extended: read to {_n(at)}, the top of its ladder" if at is not None
                else "waiting to be extended: read to the top of its ladder")
        return {"word": WAITING, "by": LADDER, "rule": rule, "at_n": at, "text": text}
    if state == S.HELD.value:
        text = (f"waiting to be extended: read to {_n(at)}, {_n(next_n)} when a place frees"
                if at is not None and next_n is not None else "waiting to be extended: its next size when a place frees")
        return {"word": WAITING, "by": None, "rule": rule, "at_n": at, "text": text}
    if state in RUNNING_STATES:
        text = (f"running: read to {_n(at)}, {_n(next_n)} under way" if at is not None and next_n is not None
                else f"running: {_n(next_n)} under way" if next_n is not None else "running")
        return {"word": RUNNING, "by": None, "rule": rule, "at_n": at, "text": text}
    if state in NOT_RUN_STATES or not state:
        return {"word": NOT_RUN, "by": None, "rule": None, "at_n": None, "text": NOT_RUN}
    by = f"region {region}" if region else settled_by(rule)
    if at is None:
        word = SETTLED
        text = f"settled by {by}" + (f" ({rule})" if rule else f" ({state.lower()})") + " before any size was read"
    else:
        word = f"settled at {_n(at)}"
        text = (f"settled by {by}" + (f" ({rule})" if rule else "") + f", its highest reading {_n(at)}; "
                "it waits to be extended past it")
    return {"word": word, "by": by, "rule": rule, "at_n": at, "text": text}


def of_row(row: dict) -> dict:
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    rule = decision.get("rule") or rule_of(row.get("state_reason"))
    at_n = decision.get("at_n")
    if at_n is None:
        at_n = row.get("decision_at_n", row.get("largest_n", row.get("top_n")))
    return status(row.get("state"), rule=rule, at_n=at_n, next_n=decision.get("next_n", row.get("next_n")),
                  region=row.get("region_name"))


ONE_DIMENSION_BELOW = 1.5
RING_DEGREE_WITHIN = 0.02
WHOLE_AT_LEAST = 0.95
FORMS = ("grown", "made", "ring", "small_world")


def form_of(d, degree, giant) -> str | None:
    if d is None:
        return None
    if float(d) >= ONE_DIMENSION_BELOW:
        return f"d {float(d):.1f}"
    if degree is not None and abs(float(degree) - 2.0) <= 2.0 * RING_DEGREE_WITHIN:
        return "a ring" if giant is not None and float(giant) >= WHOLE_AT_LEAST else "rings"
    return "open strings" if degree is not None and float(degree) < 2.0 else "a line"


ONE_DIMENSIONAL = {"a ring": "ring", "rings": "ring", "open strings": "line", "a line": "line"}
RING_KIND, MADE = "ring", "made"


def type_of(kind, form) -> str | None:
    if kind is None:
        return None
    if form is None:
        return str(kind)
    family = ONE_DIMENSIONAL.get(form) or (f"d {round(float(form.split()[1]))}" if form.startswith("d ") else form)
    return f"{MADE if kind == RING_KIND else kind} {family}"


def one_dimensional(found_type: str | None) -> bool:
    return bool(found_type) and found_type.split()[-1] in set(ONE_DIMENSIONAL.values())


KEPT_STARTS = ("frozen", "still")


def known_from_the_table(found_type: str | None) -> bool:
    return one_dimensional(found_type) or (bool(found_type) and found_type.split()[0] in KEPT_STARTS)


def phenotype(chains: dict, place: dict | None = None, at_n: int | None = None) -> dict:
    from graph_scale_dynamics.observability import catalogue as K
    from graph_scale_dynamics.observability import law_kind
    found = law_kind.kinds(chains or {})
    if at_n is not None:
        found = {n: k for n, k in found.items() if int(n) <= int(at_n)}
    region = (place or {}).get("region")
    if not found:
        return {"kind": None, "name": "not read yet", "at_n": None, "form": None, "region": region,
                "mapped": (place or {}).get("how"), "words": "not read yet" + (f" \u00b7 {region}" if region else "")}
    n = max(found)
    kind = found[n]
    _views, values = law_kind.read(chains)
    empty = (values.get("empty") or {}).get(n) or {}
    d = K.d_of(empty)
    form = form_of(d, empty.get("mean_degree"), empty.get("giant_fraction")) if kind in FORMS else None
    name = K.names().get(kind, kind)
    how = (place or {}).get("how")
    words = f"{name}{', ' + form if form else ''} at N={n:,} \u00b7 " + (
        f"{region} ({how})" if region else "no GG region yet")
    return {"kind": kind, "name": name, "at_n": n, "form": form, "type": type_of(kind, form),
            "d": None if d is None else round(float(d), 3),
            "mean_degree": empty.get("mean_degree"), "giant": empty.get("giant_fraction"),
            "region": region, "mapped": how, "words": words}


def of_law(repo, campaign_id: str, candidate: dict) -> dict:
    found = repo.conn.execute(
        "SELECT rule, at_n, next_n FROM engine_decisions_latest WHERE campaign_id=? AND candidate_id=?",
        (str(campaign_id), str(candidate["candidate_id"]))).fetchone()
    if found is None:
        return of_row(dict(candidate))
    return status(candidate.get("state"), rule=found["rule"], at_n=found["at_n"], next_n=found["next_n"])


__all__ = ["BUDGET", "CONDITION", "GATE", "LADDER", "NOT_RUN", "RUNNING", "SETTLED", "WAITING", "form_of", "of_law",
           "known_from_the_table", "of_row", "one_dimensional", "phenotype", "rule_of", "settled_by", "status", "type_of"]
