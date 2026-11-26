from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


GATES_CONTRACT = "gates-1"

PASS, STOP, SALTED = "pass", "stop", "salted"


@dataclass(frozen=True)
class Gate:
    name: str
    stage: str
    reads: str
    salted: bool
    why_not: str = ""
    action: str | None = "stop"


@dataclass(frozen=True)
class Stream:
    action: str
    rule: str
    means: str
    audit: bool = False


GATES = (
    Gate("failed", "operational", "a seed or its analysis failed for good", False,
         "the rung cannot be completed: nothing is there to let through"),
    Gate("over_budget", "operational", "the law's first chunk at the next size, predicted from its own seeds a size "
                                       "below, would not fit that size's budget in work (806)", False,
         "a seed that cannot start is not let through: the budget is the design's, fixed before the study"),
    Gate("memory_ceiling", "operational", "a depth law's next size, priced from its own peak memory at the sizes "
                                          "below, would not fit the host's reach with its free memory kept: settled "
                                          "at its memory ceiling, everything it measured kept (873)", False,
         "a size that cannot fit is not let through: the host's memory is the limit"),
    Gate("cut", "operational", "a seed of the law ran out of its budget in work before it settled, at the size "
                               "the law is at: parked there, on a design's cut_gate (841)", True),
    Gate("empty", "final verdict", "mean degree at most the empty line at every rung, from 256; on a design's "
                                "fact_sizes_in_a_row, at that many sizes in a row and not rising (828)", True),
    Gate("disconnected", "final verdict", "the largest component under the floor and not growing, from 1,024; on a "
                                       "design's fact_sizes_in_a_row, under it at that many sizes in a row (828)",
         True),
    Gate("too_dense", "final verdict", "mean degree at the campaign's cap, from 256; on a design's "
                                    "fact_sizes_in_a_row, at that many sizes in a row (828)", True),
    Gate("nothing_read", "settling", "no chain read any probe at any size of the base block, the law parked at its "
                                     "top (782, the first gate on the base block)", True),
    Gate("no_steady_chain", "settling", "no chain steady and moved by the law from 1,024 to 4,096, the law parked at "
                                        "4,096 (796)", True),
    Gate("reading_lost", "settling", "d_s settled and then has no reading at the top rung", True),
    Gate("no_reading", "settling", "no d_s at either of the top two rungs", True),
    Gate("unsettled_twice", "settling", "d_s unsettled at two looks in a row", True),
    Gate("no_second_rung", "settling", "unsettled where the next rung takes a plateau", True),
    Gate("unsettled", "settling", "a hold on an unsettled step (529's rules, `second_rung: false`)", True,
         action="hold"),
    Gate("no_plateau", "deep rungs", "d_s did not settle at the step before a deep rung", True, action="hold"),
    Gate("deep_lane_full", "deep rungs", "the deep rung's lane is full", False,
         "a queue, not a verdict: the law runs when the lane frees, best score first", action="hold"),
    Gate("starts_alike", "settling", "every start ends alike, no shape held, from the last base rung (602)", True),
    Gate("starts_apart_twice", "settling", "the starts apart with no shape held at two sizes in a row (602)", True),
    Gate("starts_apart_by_history", "settling", "the starts apart, and every start alike at the size below or the "
                                                "starts in two groups (629)", True),
    Gate("starts_shape_unread", "settling", "a shape read below a size its starts were not read at: its one size "
                                            "spent without a reading (631)", True),
    Gate("not_promising", "deep rungs", "a rung from 262,144 for a law not shaped at its top two rungs, mostly small "
                                        "worlds, unsettled, or with d_V unread (629)", False,
         "629: no salt buys a rung from 262,144; its other side is the laws that pass it. Under 784's "
         "let-through rule it lets 10% through, then 1%, as every gate does"),
    Gate("no_finite_dimension", "structure", "no finite dimension on either chain, or undecidable twice", True),
    Gate("no_giant_component", "structure", "the giant component under half the graph where the rule reads", True),
    Gate("kept_shape", "repeats", "the dimension test reads only lattice starts that kept their shape and their own d "
                                  "(732's tier 3): parked as a class to extend on its own (789)", False,
         "a gate of 784's let-through rule only, on a design's kept_shape_park: 10% through, then 1%"),
    Gate("repeats_a_known_result", "repeats", "the law's every chain repeats a result 100 laws already reached and "
                                              "kept one size up (784; named so at 835, "
                                              "seen_enough before)", False,
         "a gate of 784's let-through rule only: 10% through, then 1%, from 4,096"),
    Gate("early_stage", "structure", "the clear case at 16,384, in shadow until its switch is on", False,
         "a label while its switch is off: what it would refuse is recorded beside the full rule's verdict",
         action=None),
)
BY_NAME = {gate.name: gate for gate in GATES}
KINDS = (("fact", ("empty", "too_dense", "disconnected")),
         ("judgment", ("starts_alike", "starts_apart_by_history", "starts_apart_twice", "starts_shape_unread",
                       "nothing_read", "no_steady_chain", "repeats_a_known_result")),
         ("class", ("kept_shape",)),
         ("settling", ("reading_lost", "no_reading", "unsettled_twice", "no_second_rung", "unsettled")),
         ("depth", ("not_promising", "no_plateau", "deep_lane_full")),
         ("structure", ("no_finite_dimension", "no_giant_component", "early_stage")),
         ("operational", ("failed", "over_budget", "cut", "memory_ceiling")))
KIND_OF = {name: kind for kind, names in KINDS for name in names}


def about() -> dict:
    order = [name for _kind, names in KINDS for name in names]
    return {gate.name: {"kind": KIND_OF.get(gate.name, gate.stage), "reads": gate.reads,
                        "let_through": gate.name in LET_THROUGH_GATES,
                        "order": order.index(gate.name) if gate.name in order else len(order)} for gate in GATES}

STREAMS = (
    Stream("run_next", "start", "the law's first rung: its seeds at the bottom of the ladder"),
    Stream("run_next", "complete_rung", "the same rung again, for the seeds it has not measured yet"),
    Stream("run_next", "base_block", "the next rung of the base block, which every law is measured through"),
    Stream("run_next", "d_s_settled", "d_s settled at the rung: the next rung, to see whether it holds"),
    Stream("run_next", "second_rung", "unsettled below the plateau rungs: the next rung once, the look before a park"),
    Stream("run_next", "longer_chain", "no d_s at the top two rungs, refused for the sampling: the rung once more "
                                       "with a longer chain"),
    Stream("run_next", "starts_shape", "a lattice start holds its shape, or a start without one reaches a held "
                                       "lattice's state: the next size (602, a campaign decided chain by chain)"),
    Stream("run_next", "starts_apart", "the starts end apart, no shape held: the next size once, the look before a "
                                       "park (602)"),
    Stream("run_next", "dimension_shows", "where the starts' rule or the depth bar would park it, a chain reads "
                                          "dimensional: the next size, in the order of its tier (732)"),
    Stream("run_next", "lane_resumed", "its rung's lane has room again: the chains it saved resume where they stopped"),
    Stream("run_next", "hold_released", "a held law released when nothing else was waiting"),
    Stream("run_next", "salted", "one rung past a gate that would have withheld it: the gate's control arm",
           audit=True),
    Stream("run_next", "gate_audit", "near a structure gate's threshold: bought anyway, inside the windows the gate "
                                     "reads", audit=True),
    Stream("run_next", "plateau_follow", "d_s settled step after step where the structure gate refused: followed",
           audit=True),
    *(Stream(gate.action, gate.name, gate.reads) for gate in GATES if gate.action),
    Stream("done", "ladder_complete", "the last declared rung is measured"),
)
SALTED_GATES = frozenset(gate.name for gate in GATES if gate.salted)
SALT_DEEP_FROM = 16384
WITHHOLDING_GATES = frozenset({"reading_lost", "no_reading", "unsettled_twice", "no_second_rung", "unsettled",
                               "no_plateau"})


REFUSAL_GEOMETRY = frozenset({"REFUSED_NO_SCALING_WINDOW", "REFUSED_BELOW_CONNECTIVITY_FLOOR"})
REFUSAL_LIMITS = frozenset({"REFUSED_MEAN_DEGREE_ABOVE_WINDOW", "REFUSED_MEAN_DEGREE_BELOW_WINDOW",
                            "REFUSED_COMPUTE_BUDGET"})
REFUSAL_SAMPLING = frozenset({"REFUSED_CHAINS_DISAGREED", "REFUSED_NO_EFFECTIVE_SAMPLE",
                              "REFUSED_NEVER_EQUILIBRATED"})
FIRST_STEP_OF = {"longer_chain": "no_reading"}


def refusal_kind(bucket) -> str:
    if bucket is None:
        return "read"
    bucket = str(getattr(bucket, "value", bucket))
    if bucket in REFUSAL_GEOMETRY:
        return "geometry"
    if bucket in REFUSAL_LIMITS:
        return "limits"
    if bucket in REFUSAL_SAMPLING:
        return "sampling"
    return "other refusal" if bucket.startswith("REFUSED_") else "read"


def gate_of(rule: str) -> str:
    return FIRST_STEP_OF.get(str(rule), str(rule))


SALT_STREAM_LABELS = {"starts_alike": "five_starts_alike", "starts_apart": "five_starts_apart",
                      "starts_apart_by_history": "five_starts_apart_by_history",
                      "starts_apart_twice": "five_starts_apart_twice", "starts_shape": "five_starts_shape",
                      "starts_shape_unread": "five_starts_shape_unread"}


def salt_label(gate: str) -> str:
    return SALT_STREAM_LABELS.get(gate, gate)


def salted(law: str, gate: str, fraction: float) -> bool:
    if not fraction or gate not in SALTED_GATES:
        return False
    value = int(hashlib.sha256(f"gate:{salt_label(gate)}:{law}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return value < float(fraction)


LET_THROUGH_RULE = "gsd-let-through-1"
LET_THROUGH_FROM = 4096
RECORD_ONLY, TESTING_SHARE, CONFIRMED_SHARE = 1.0, 0.10, 0.01
CONFIRM_AFTER = 100
LET_THROUGH_GATES = SALTED_GATES | frozenset({"not_promising", "repeats_a_known_result", "kept_shape"})
FORMER_NAMES = {"seen_enough": "repeats_a_known_result"}
DIE_LABELS = {"repeats_a_known_result": "seen_enough"}
FORMER_WORD = re.compile(r"\b(" + "|".join(sorted(FORMER_NAMES)) + r")\b")
FORMER_PHRASES = {"seen enough: ": "repeats a known result: ",
                  "the clear case (the operator's switch is on and ": "the clear case (its switch is on and "}


def today(name):
    return FORMER_NAMES.get(str(name), str(name)) if name is not None else None


def in_today_s_words(value):
    if isinstance(value, str):
        value = FORMER_WORD.sub(lambda match: FORMER_NAMES[match.group(1)], value)
        for former, now in FORMER_PHRASES.items():
            value = value.replace(former, now)
        return value
    if isinstance(value, dict):
        return {in_today_s_words(key): in_today_s_words(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(in_today_s_words(item) for item in value)
    return value


def drawn(law: str, gate: str, n, fraction: float, *, one_die: bool = False) -> bool:
    if not fraction or gate not in LET_THROUGH_GATES:
        return False
    if float(fraction) >= 1.0:
        return True
    return die(law, None if one_die else gate, n) < float(fraction)


def die(law: str, gate: str | None, n) -> float:
    size = int(n) if n is not None else "-"
    key = f"one-die:{size}:{law}" if gate is None else f"let-through:{DIE_LABELS.get(gate, gate)}:{size}:{law}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF


def unsalted_law(prefix: str, fraction: float, gates=SALTED_GATES, *, start: int = 0) -> str:
    i = int(start)
    while any(salted(f"{prefix}{i}", gate, fraction) for gate in gates):
        i += 1
    return f"{prefix}{i}"
