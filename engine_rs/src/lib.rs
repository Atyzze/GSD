mod accounting;
mod graph;
mod mt;
pub mod value;

use std::collections::HashSet;
use std::time::Instant;

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use value::{Answer, Fault, MapBuilder, Value};

use accounting::{Accounting, KIND_ADD, KIND_DELETE, KIND_SWAP, SCOPE_GLOBAL, SCOPE_LOCAL};
use graph::{edge, Deltas, Edge, GraphState, Op, LEDGERS, LEDGER_NAMES, PARTS};
use mt::Mt;

pub const FINGERPRINT: &str = env!("CARGO_PKG_VERSION");

pub const STOP_CHECK_SECONDS: f64 = 4.0;
pub const WORK_CHECK_MOVES: usize = 64;

pub const CLOCK_STRIDE_START_MOVES: usize = 1;
pub const CLOCK_STRIDE_MAX_MOVES: usize = 1 << 22;

pub const STRUCTURE_POINT_STRIDE: usize = 20;

#[pyfunction]
#[pyo3(name = "delta_h_bin")]
fn delta_h_bin_py(delta_h: f64) -> String {
    accounting::delta_h_bin(delta_h)
}

#[pyfunction]
#[pyo3(name = "structure_point_stride")]
fn structure_point_stride_py(n: usize) -> usize {
    structure_point_stride(n)
}

fn structure_point_stride(_n: usize) -> usize {
    STRUCTURE_POINT_STRIDE
}

#[pyfunction]
#[pyo3(name = "next_clock_stride")]
fn next_clock_stride_py(stride: usize, elapsed: f64, tick: f64) -> usize {
    next_clock_stride(stride, elapsed, tick)
}

fn next_clock_stride(stride: usize, elapsed: f64, tick: f64) -> usize {
    if elapsed < 0.5 * tick {
        return (stride.max(1) * 2).min(CLOCK_STRIDE_MAX_MOVES);
    }
    if elapsed > tick {
        return (((stride as f64) * 0.5 * tick / elapsed) as usize).max(1);
    }
    stride.max(1)
}

const LOCAL_WALK_DELETE: f64 = 0.2;
const LOCAL_WALK_SWAP_BELOW: f64 = 0.6;
const LOCAL_WALK_ADD: f64 = 0.4;
const LOCAL_WALK_STEPS: [usize; 2] = [2, 3];

fn neighbours(state: &GraphState, w: u32, without: Option<Edge>) -> Vec<u32> {
    state.read_lists(1, state.adj[w as usize].len());
    let mut found: Vec<u32> = state.adj[w as usize].clone();
    found.sort_unstable();
    if let Some((a, b)) = without {
        let other = if w == a { Some(b) } else if w == b { Some(a) } else { None };
        if let Some(other) = other {
            if let Some(pos) = found.iter().position(|&x| x == other) {
                found.remove(pos);
            }
        }
    }
    found
}

fn walk_ends(state: &GraphState, u: u32, x: u32, steps: usize, without: Option<Edge>) -> f64 {
    let first = neighbours(state, u, without);
    let du = first.len();
    let mut total = 0.0f64;
    for &b in &first {
        let second = neighbours(state, b, without);
        let db = second.len();
        if steps == 2 {
            state.scan(second.len());
            if second.contains(&x) {
                total += 1.0 / ((du * db) as f64);
            }
            continue;
        }
        for &c in &second {
            let third = neighbours(state, c, without);
            state.scan(third.len());
            if third.contains(&x) {
                total += 1.0 / ((du * db * third.len()) as f64);
            }
        }
    }
    total
}

fn walk_add_chance(state: &GraphState, u: u32, x: u32, n: usize, without: Option<Edge>) -> f64 {
    let ends = (walk_ends(state, u, x, 2, without) + walk_ends(state, x, u, 2, without))
        + (walk_ends(state, u, x, 3, without) + walk_ends(state, x, u, 3, without));
    LOCAL_WALK_ADD * ends / ((2 * n) as f64)
}

fn delete_chance(du: usize, dv: usize, n: usize) -> f64 {
    LOCAL_WALK_DELETE * (1.0 / du as f64 + 1.0 / dv as f64) / n as f64
}

#[allow(clippy::too_many_arguments)]
fn local_toggle(
    model: &Model, state: &mut GraphState, rng: &mut Mt, n: usize, u: u32, v: u32, adding: bool, beta: f64,
    zero_temperature: bool, energy: &mut f64, energy_int: &mut bool, peak_edge_count: &mut usize,
    proposed: &mut Counter, accepted: &mut Counter, acc: &mut Accounting, mv: usize,
) -> Answer<()> {
    if adding { proposed.add += 1; } else { proposed.delete += 1; }
    let (deltas, delta_h) = model.apply_edge(state, u, v, adding);
    if !delta_h.is_finite() {
        return Err(Fault::floating(
            format!("non-finite energy delta at move {mv}; refusing to sample")));
    }
    let du = state.degree(u);
    let dv = state.degree(v);
    let (forward, reverse) = if adding {
        (walk_add_chance(state, u, v, n, None), delete_chance(du + 1, dv + 1, n))
    } else {
        (delete_chance(du, dv, n), walk_add_chance(state, u, v, n, Some((u, v))))
    };
    let took = if reverse <= 0.0 || forward <= 0.0 {
        false
    } else if zero_temperature {
        delta_h <= 0.0
    } else {
        (rng.random() + 1e-300).ln() < -beta * delta_h + (reverse / forward).ln()
    };
    if took {
        state.apply(u, v, adding, &deltas);
        *energy += delta_h;
        *energy_int = false;
        *peak_edge_count = (*peak_edge_count).max(state.edge_count());
        if adding { accepted.add += 1; } else { accepted.delete += 1; }
    }
    acc.tally(mv, if adding { KIND_ADD } else { KIND_DELETE }, SCOPE_LOCAL, delta_h, took);
    Ok(())
}

#[derive(Clone)]
struct Term {
    op: Op,
    coeff: f64,
    k: i64,
    scale: String,
    params_k: Option<i64>,
}

const EXACT_ZERO_SHARE: f64 = 1e-12;

fn exact_zero(change: f64, magnitude: f64) -> f64 {
    if change.abs() <= EXACT_ZERO_SHARE * magnitude { 0.0 } else { change }
}

#[inline]
fn node_functional(op: Op, d: i64, k: i64) -> i128 {
    let d = d as i128;
    let k = k as i128;
    match op {
        Op::DegreeAnchor => (d - k) * (d - k),
        Op::DegreeAnchorAbs => (d - k).abs(),
        Op::DegreeCubeSum => d * d * d,
        Op::DegreeFourthSum => d * d * d * d,
        _ => 0,
    }
}

struct Model {
    terms: Vec<Term>,
    node_terms: Vec<Term>,
}

impl Model {
    #[inline]
    fn apply_edge(&self, state: &mut GraphState, u: u32, v: u32, adding: bool) -> (Deltas, f64) {
        let deltas = state.op_deltas(u, v, adding);
        let mut node_energy = 0.0f64;
        let mut node_magnitude = 0.0f64;
        if !self.node_terms.is_empty() {
            let sign: f64 = if adding { 1.0 } else { -1.0 };
            let du = state.degree(u) as i64 - if adding { 0 } else { 1 };
            let dv = state.degree(v) as i64 - if adding { 0 } else { 1 };
            for t in &self.node_terms {
                let inner = node_functional(t.op, du + 1, t.k) - node_functional(t.op, du, t.k)
                    + node_functional(t.op, dv + 1, t.k)
                    - node_functional(t.op, dv, t.k);
                let part = t.coeff * sign * (inner as f64);
                node_energy += part;
                node_magnitude += part.abs();
            }
        }
        let mut energy = node_energy;
        let mut magnitude = node_magnitude;
        for t in &self.terms {
            if t.op.is_node() {
                continue;
            }
            let idx = t.op.ledger_index().expect("ledger op");
            let part = t.coeff * deltas.ledger[idx];
            energy += part;
            magnitude += part.abs();
        }
        (deltas, exact_zero(energy, magnitude))
    }

    fn swap_change(&self, moved: &[f64; LEDGERS]) -> f64 {
        let mut change = 0.0f64;
        let mut magnitude = 0.0f64;
        for t in &self.terms {
            if t.op.is_node() {
                continue;
            }
            let part = t.coeff * moved[t.op.ledger_index().expect("ledger op")];
            change += part;
            magnitude += part.abs();
        }
        exact_zero(change, magnitude)
    }
}

#[derive(Default, Clone, Copy)]
struct Counter {
    add: u64,
    delete: u64,
    swap: u64,
}

impl Counter {
    fn from_value(value: Option<&Value>) -> Answer<Self> {
        let mut c = Counter::default();
        if let Some(d) = value.filter(|v| !v.is_null()) {
            c.add = d.present("add").map(|v| v.as_u64()).transpose()?.unwrap_or(0);
            c.delete = d.present("delete").map(|v| v.as_u64()).transpose()?.unwrap_or(0);
            c.swap = d.present("swap").map(|v| v.as_u64()).transpose()?.unwrap_or(0);
        }
        Ok(c)
    }

    fn to_value(&self) -> Value {
        let mut d = MapBuilder::new();
        d.set("add", self.add).set("delete", self.delete).set("swap", self.swap);
        d.build()
    }
}

fn parse_terms(value: &Value) -> Answer<(Vec<Term>, Vec<Term>)> {
    let mut terms = Vec::new();
    let mut node_terms = Vec::new();
    for item in value.items()? {
        let op_name = item.present("op").ok_or_else(|| Fault::key("term has no 'op'"))?.as_str()?.to_string();
        let op = Op::parse(&op_name).ok_or_else(|| Fault::value(format!("unknown op {op_name}")))?;
        let coeff = item.present("coeff").ok_or_else(|| Fault::key(format!("term {op_name} has no 'coeff'")))?.as_f64()?;
        let k = item.present("k").map(|v| v.as_i64()).transpose()?.unwrap_or(0);
        let scale = item.present("scale").map(|v| v.as_str().map(str::to_string)).transpose()?
            .unwrap_or_else(|| "one".into());
        let params_k = item.present("params_k").map(|v| v.as_i64()).transpose()?;
        let t = Term { op, coeff, k, scale, params_k };
        if op.is_node() {
            node_terms.push(t.clone());
        }
        terms.push(t);
    }
    Ok((terms, node_terms))
}

fn field<'a>(request: &'a Value, key: &str) -> Answer<&'a Value> {
    request.present(key).ok_or_else(|| Fault::key(format!("the request has no '{key}'")))
}

fn optional<T>(request: &Value, key: &str, read: impl Fn(&Value) -> Answer<T>) -> Answer<Option<T>> {
    request.present(key).map(read).transpose()
}

fn run_chain(request: &Value) -> Answer<Value> {
    let n = field(request, "n")?.as_usize()?;
    let beta = field(request, "beta")?.as_f64()?;
    let p_add = field(request, "p_add")?.as_f64()?;
    let p_del = field(request, "p_del")?.as_f64()?;
    let p_swap = field(request, "p_swap")?.as_f64()?;
    let proposal_locality = field(request, "proposal_locality")?.as_f64()?;
    let total_moves = field(request, "total_moves")?.as_usize()?;
    let start_move = field(request, "start_move")?.as_usize()?;
    let points = field(request, "points")?.as_usize()?;
    let late_from_move = optional(request, "late_from_move", Value::as_usize)?;
    let mt_words = field(request, "mt_words")?.as_words()?;
    let mt_index = field(request, "mt_index")?.as_usize()?;
    let edge_list = field(request, "edge_list")?.as_pairs()?;
    let energy = field(request, "energy")?.as_f64()?;
    let late_change = match request.present("late_change") {
        None => None,
        Some(v) => {
            let parts = v.items()?;
            if parts.len() != 3 {
                return Err(Fault::value("late_change is its first move, the edges added and the edges removed"));
            }
            Some((parts[0].as_usize()?, parts[1].as_pairs()?, parts[2].as_pairs()?))
        }
    };
    let trajectory_len = optional(request, "trajectory_len", Value::as_usize)?.unwrap_or(0);
    let peak_edge_count = optional(request, "peak_edge_count", Value::as_usize)?.unwrap_or(0);
    let non_edge_fast_path_hits = optional(request, "non_edge_fast_path_hits", Value::as_u64)?.unwrap_or(0);
    let non_edge_exact_fallbacks = optional(request, "non_edge_exact_fallbacks", Value::as_u64)?.unwrap_or(0);
    let cap_edges = optional(request, "cap_edges", Value::as_usize)?;
    let mean_degree_cap = optional(request, "mean_degree_cap", Value::as_f64)?;
    let energy_is_int = optional(request, "energy_is_int", Value::as_bool)?.unwrap_or(false);
    let segment_start = optional(request, "segment_start", Value::as_usize)?;
    let stop_file = optional(request, "stop_file", |v| v.as_str().map(str::to_string))?;
    let rebuild_stop_file = optional(request, "rebuild_stop_file", |v| v.as_str().map(str::to_string))?;
    let stop_check_seconds = optional(request, "stop_check_seconds", Value::as_f64)?.unwrap_or(STOP_CHECK_SECONDS);
    let locality = optional(request, "locality", Value::as_f64)?.unwrap_or(0.0);
    let zero_temperature = optional(request, "zero_temperature", Value::as_bool)?.unwrap_or(false);
    let cooling_from_beta = optional(request, "cooling_from_beta", Value::as_f64)?;
    let cooling_moves = optional(request, "cooling_moves", Value::as_usize)?;
    let local_walk = optional(request, "local_walk", Value::as_bool)?.unwrap_or(false);
    let work_room = optional(request, "work_room", Value::as_u64)?;
    let work_weights: Option<Vec<u64>> = match request.present("work_weights") {
        Some(v) => Some(v.items()?.iter().map(Value::as_u64).collect::<Answer<Vec<u64>>>()?),
        None => None,
    };
    if work_room.is_some() && work_weights.as_ref().map_or(true, |w| w.len() != PARTS + 1) {
        return Err(Fault::value("a chain weighed against a budget carries one weight for each part of its work"));
    }
    let _ = p_swap;
    if !(0.0..1.0).contains(&locality) {
        return Err(Fault::value("locality must lie in [0,1)"));
    }
    if locality > 0.0 && proposal_locality > 0.0 {
        return Err(Fault::value(
            "a law with its own locality is not audited with another proposal locality"));
    }
    let cooling = match (cooling_from_beta, cooling_moves) {
        (Some(start), Some(moves)) if moves > 0 => Some((start, moves)),
        _ => None,
    };
    if cooling.is_some() && zero_temperature {
        return Err(Fault::value("a zero-temperature law cannot cool"));
    }
    let beta_at = |mv: usize| -> f64 {
        match cooling {
            Some((start, moves)) if mv < moves => start + (beta - start) * (mv as f64 / moves as f64),
            _ => beta,
        }
    };
    let accept = |rng: &mut Mt, delta_h: f64, log_ratio: f64, mv: usize| -> bool {
        if zero_temperature { delta_h <= 0.0 } else { (rng.random() + 1e-300).ln() < -beta_at(mv) * delta_h + log_ratio }
    };
    let (terms, node_terms) = parse_terms(field(request, "terms")?)?;
    let required: Vec<Op> = terms.iter().map(|t| t.op).filter(|op| !op.is_node()).collect();
    let model = Model { terms, node_terms };
    let mut rng = Mt::from_state(&mt_words, mt_index)
        .map_err(Fault::value)?;

    check_edge_list(n, &edge_list)?;
    let mut state = GraphState::new(n, &required);
    let mut rebuild_clock = RebuildClock::new(rebuild_stop_file.map(std::path::PathBuf::from), stop_check_seconds);
    for (index, &(u, v)) in edge_list.iter().enumerate() {
        if let Some(reason) = rebuild_clock.interrupted(index) {
            let mut out = MapBuilder::new();
            out.set("interrupted", reason).set("edges_rebuilt", index);
            return Ok(out.build());
        }
        let (deltas, _) = model.apply_edge(&mut state, u, v, true);
        state.apply(u, v, true, &deltas);
    }
    state.non_edge_fast_path_hits = non_edge_fast_path_hits;
    state.non_edge_exact_fallbacks = non_edge_exact_fallbacks;
    let mut late_from: Option<usize> = None;
    if let Some((from_move, added, removed)) = late_change {
        late_from = Some(from_move);
        state.late = Some((added.into_iter().map(|(u, v)| edge(u, v)).collect(),
                           removed.into_iter().map(|(u, v)| edge(u, v)).collect()));
    }
    let arm_at: Option<usize> = late_from_move.filter(|m| *m >= start_move);
    let mut energy = energy;
    let mut energy_int = energy_is_int;

    let mut attempted = Counter::from_value(request.get("attempted"))?;
    let mut proposed = Counter::from_value(request.get("proposed"))?;
    let mut accepted = Counter::from_value(request.get("accepted"))?;
    let mut peak_edge_count = peak_edge_count.max(state.edge_count());
    let segment_start = segment_start.unwrap_or(start_move);
    let segment_moves = total_moves.saturating_sub(segment_start);
    let record_every = (segment_moves / points.max(1)).max(1);
    let structure_stride = structure_point_stride(n);
    let mut acc = Accounting::from_value(request.get("accounting"))?;
    acc.start_segment(start_move, segment_start, segment_moves);
    let stop_path = stop_file.map(std::path::PathBuf::from);
    let mut last_stop_check = Instant::now();
    let mut last_clock_read = last_stop_check;
    let mut clock_stride = CLOCK_STRIDE_START_MOVES;
    let mut next_clock_move = start_move + clock_stride;
    let max_edges = n * (n.saturating_sub(1)) / 2;

    let mut trajectory: Vec<Value> = Vec::new();
    let mut trajectory_count = trajectory_len;
    let mut termination: Option<MapBuilder> = None;

    let counted_from = state.counted();
    let mut late_counted_from: Option<[u64; PARTS + 1]> = None;
    let mut moves_run: u64 = 0;
    let mut late_moves_run: u64 = 0;
    let mut move_idx = start_move;
    while move_idx < total_moves {
        let mv = move_idx;
        moves_run += 1;
        if acc.late_from.map_or(false, |from| mv >= from) {
            late_moves_run += 1;
            if late_counted_from.is_none() {
                late_counted_from = Some(state.counted());
            }
        }
        if arm_at == Some(mv) {
            state.late = Some((HashSet::new(), HashSet::new()));
            late_from = Some(mv);
        }
        let e_count = state.edge_count();

        if local_walk {
            let a = rng.randrange(n) as u32;
            let draw = rng.random();
            if draw < LOCAL_WALK_DELETE {
                attempted.delete += 1;
                let first = neighbours(&state, a, None);
                if !first.is_empty() {
                    let b = first[rng.randrange(first.len())];
                    local_toggle(&model, &mut state, &mut rng, n, a, b, false, beta_at(mv), zero_temperature,
                                 &mut energy, &mut energy_int, &mut peak_edge_count, &mut proposed, &mut accepted,
                                 &mut acc, mv)?;
                }
            } else if draw < LOCAL_WALK_SWAP_BELOW {
                attempted.swap += 1;
                let first = neighbours(&state, a, None);
                let pick = if first.is_empty() {
                    None
                } else {
                    let b = first[rng.randrange(first.len())];
                    let second: Vec<u32> = neighbours(&state, b, None).into_iter().filter(|&w| w != a).collect();
                    if second.is_empty() {
                        None
                    } else {
                        let c = second[rng.randrange(second.len())];
                        let third: Vec<u32> = neighbours(&state, c, None).into_iter().filter(|&w| w != b).collect();
                        if third.is_empty() {
                            None
                        } else {
                            let d = third[rng.randrange(third.len())];
                            if d == a || state.tests_edge(a, c) || state.tests_edge(b, d) { None } else { Some((b, c, d)) }
                        }
                    }
                };
                if let Some((b, c, d)) = pick {
                    proposed.swap += 1;
                    let (e1, e2, n1, n2) = (edge(a, b), edge(c, d), edge(a, c), edge(b, d));
                    let old_energy = energy;
                    let old_energy_int = energy_int;
                    energy_int = false;
                    let mut moved = [0.0f64; LEDGERS];
                    for (e, adding) in [(e1, false), (e2, false), (n1, true), (n2, true)] {
                        let (deltas, dh) = model.apply_edge(&mut state, e.0, e.1, adding);
                        if !dh.is_finite() {
                            return Err(Fault::floating(
                                "non-finite energy delta during edge swap"));
                        }
                        state.apply(e.0, e.1, adding, &deltas);
                        for (sum, change) in moved.iter_mut().zip(deltas.ledger.iter()) {
                            *sum += *change;
                        }
                    }
                    let delta_h = model.swap_change(&moved);
                    energy = old_energy + delta_h;
                    let took = accept(&mut rng, delta_h, 0.0, mv);
                    if took {
                        accepted.swap += 1;
                    } else {
                        for (e, adding) in [(n2, false), (n1, false), (e2, true), (e1, true)] {
                            let (deltas, dh) = model.apply_edge(&mut state, e.0, e.1, adding);
                            if !dh.is_finite() {
                                return Err(Fault::floating(
                                    "non-finite energy delta during edge swap"));
                            }
                            state.apply(e.0, e.1, adding, &deltas);
                            #[allow(unused_assignments)]
                            { energy += dh; }
                        }
                        energy = old_energy;
                        energy_int = old_energy_int;
                    }
                    acc.tally(mv, KIND_SWAP, SCOPE_LOCAL, delta_h, took);
                }
            } else {
                attempted.add += 1;
                let steps = LOCAL_WALK_STEPS[rng.randrange(LOCAL_WALK_STEPS.len())];
                let mut x = a;
                let mut stuck = false;
                for _ in 0..steps {
                    let onward = neighbours(&state, x, None);
                    if onward.is_empty() {
                        stuck = true;
                        break;
                    }
                    x = onward[rng.randrange(onward.len())];
                }
                if !stuck && x != a && !state.tests_edge(a, x) {
                    local_toggle(&model, &mut state, &mut rng, n, a, x, true, beta_at(mv), zero_temperature,
                                 &mut energy, &mut energy_int, &mut peak_edge_count, &mut proposed, &mut accepted,
                                 &mut acc, mv)?;
                }
            }
        } else if locality > 0.0 && rng.random() < locality {
            let u = rng.randrange(n);
            state.read_lists(1, state.adj[u].len());
            let mut nbrs: Vec<u32> = state.adj[u].clone();
            nbrs.sort_unstable();
            let d = nbrs.len();
            let pair: Option<Edge> = if d < 2 {
                None
            } else {
                let i = rng.randrange(d);
                let mut j = rng.randrange(d - 1);
                if j >= i {
                    j += 1;
                }
                Some(edge(nbrs[i], nbrs[j]))
            };
            match pair {
                Some((a, b)) => {
                    let adding = !state.tests_edge(a, b);
                    if adding { attempted.add += 1; proposed.add += 1; } else { attempted.delete += 1; proposed.delete += 1; }
                    let (deltas, delta_h) = model.apply_edge(&mut state, a, b, adding);
                    if !delta_h.is_finite() {
                        return Err(Fault::floating(
                            format!("non-finite energy delta at move {mv}; refusing to sample")));
                    }
                    let took = accept(&mut rng, delta_h, 0.0, mv);
                    if took {
                        state.apply(a, b, adding, &deltas);
                        energy += delta_h;
                        energy_int = false;
                        peak_edge_count = peak_edge_count.max(state.edge_count());
                        if adding { accepted.add += 1; } else { accepted.delete += 1; }
                    }
                    acc.tally(mv, if adding { KIND_ADD } else { KIND_DELETE }, SCOPE_LOCAL, delta_h, took);
                }
                None => attempted.add += 1,
            }
        } else if proposal_locality > 0.0 {
            let pair: Option<Edge> = if n < 2 {
                None
            } else if rng.random() < proposal_locality {
                let radius = 1.max(((n as f64).sqrt() as usize).min(1.max((n - 1) / 2)));
                let u = rng.randrange(n);
                let distance = 1 + rng.randrange(radius);
                let mut v = if rng.random() < 0.5 { (u + distance) % n } else { (u + n - (distance % n)) % n };
                if v == u {
                    v = (u + 1) % n;
                }
                Some(edge(u as u32, v as u32))
            } else {
                let u = rng.randrange(n);
                let mut v = rng.randrange(n - 1);
                if v >= u {
                    v += 1;
                }
                Some(edge(u as u32, v as u32))
            };
            match pair {
                None => attempted.add += 1,
                Some((u, v)) => {
                    let adding = !state.tests_edge(u, v);
                    if adding { attempted.add += 1; proposed.add += 1; } else { attempted.delete += 1; proposed.delete += 1; }
                    let (deltas, delta_h) = model.apply_edge(&mut state, u, v, adding);
                    if !delta_h.is_finite() {
                        return Err(Fault::floating(
                            format!("non-finite energy delta at move {mv}; refusing to sample")));
                    }
                    let took = accept(&mut rng, delta_h, 0.0, mv);
                    if took {
                        state.apply(u, v, adding, &deltas);
                        energy += delta_h;
                        energy_int = false;
                        peak_edge_count = peak_edge_count.max(state.edge_count());
                        if adding { accepted.add += 1; } else { accepted.delete += 1; }
                    }
                    acc.tally(mv, if adding { KIND_ADD } else { KIND_DELETE }, SCOPE_GLOBAL, delta_h, took);
                }
            }
        } else {
            let draw = rng.random();
            let kind = if draw < p_add { 0u8 } else if draw < p_add + p_del { 1 } else { 2 };
            match kind { 0 => attempted.add += 1, 1 => attempted.delete += 1, _ => attempted.swap += 1 }

            if kind == 2 {
                let ec = state.edge_count();
                let proposal: Option<(Edge, Edge, Edge, Edge)> = if ec < 2 {
                    None
                } else {
                    let i = rng.randrange(ec);
                    let mut j = rng.randrange(ec - 1);
                    if j >= i {
                        j += 1;
                    }
                    let e1 = state.edge_list[i];
                    let e2 = state.edge_list[j];
                    let (a, b) = e1;
                    let (c, d) = e2;
                    let distinct = a != c && a != d && b != c && b != d;
                    if !distinct {
                        None
                    } else {
                        let (n1, n2) = if rng.random() < 0.5 { (edge(a, c), edge(b, d)) } else { (edge(a, d), edge(b, c)) };
                        if n1 == n2 || state.tests_edge(n1.0, n1.1) || state.tests_edge(n2.0, n2.1) {
                            None
                        } else {
                            Some((e1, e2, n1, n2))
                        }
                    }
                };
                if let Some((e1, e2, n1, n2)) = proposal {
                    proposed.swap += 1;
                    let old_energy = energy;
                    let old_energy_int = energy_int;
                    energy_int = false;
                    let mut moved = [0.0f64; LEDGERS];
                    for (e, adding) in [(e1, false), (e2, false), (n1, true), (n2, true)] {
                        let (deltas, dh) = model.apply_edge(&mut state, e.0, e.1, adding);
                        if !dh.is_finite() {
                            return Err(Fault::floating(
                                "non-finite energy delta during edge swap"));
                        }
                        state.apply(e.0, e.1, adding, &deltas);
                        for (sum, change) in moved.iter_mut().zip(deltas.ledger.iter()) {
                            *sum += *change;
                        }
                    }
                    let delta_h = model.swap_change(&moved);
                    energy = old_energy + delta_h;
                    let took = accept(&mut rng, delta_h, 0.0, mv);
                    if took {
                        accepted.swap += 1;
                    } else {
                        for (e, adding) in [(n2, false), (n1, false), (e2, true), (e1, true)] {
                            let (deltas, dh) = model.apply_edge(&mut state, e.0, e.1, adding);
                            if !dh.is_finite() {
                                return Err(Fault::floating(
                                    "non-finite energy delta during edge swap"));
                            }
                            state.apply(e.0, e.1, adding, &deltas);
                            #[allow(unused_assignments)]
                            { energy += dh; }
                        }
                        energy = old_energy;
                        energy_int = old_energy_int;
                    }
                    acc.tally(mv, KIND_SWAP, SCOPE_GLOBAL, delta_h, took);
                }
            } else {
                let adding = kind == 0;
                let feasible = !((adding && e_count >= max_edges) || (!adding && e_count == 0));
                if feasible {
                    let (u, v, log_ratio) = if adding {
                        let (u, v) = state.sample_non_edge(&mut rng)
                            .map_err(Fault::runtime)?;
                        proposed.add += 1;
                        let lr = (p_del * ((max_edges - e_count) as f64)).ln()
                            - (p_add * ((e_count + 1) as f64)).ln();
                        (u, v, lr)
                    } else {
                        let (u, v) = state.edge_list[rng.randrange(e_count)];
                        proposed.delete += 1;
                        let lr = (p_add * (e_count as f64)).ln()
                            - (p_del * ((max_edges - e_count + 1) as f64)).ln();
                        (u, v, lr)
                    };
                    let (deltas, delta_h) = model.apply_edge(&mut state, u, v, adding);
                    if !delta_h.is_finite() {
                        return Err(Fault::floating(
                            format!("non-finite energy delta at move {mv}; refusing to sample")));
                    }
                    let took = accept(&mut rng, delta_h, log_ratio, mv);
                    if took {
                        state.apply(u, v, adding, &deltas);
                        energy += delta_h;
                        energy_int = false;
                        peak_edge_count = peak_edge_count.max(state.edge_count());
                        if adding { accepted.add += 1; } else { accepted.delete += 1; }
                    }
                    acc.tally(mv, if adding { KIND_ADD } else { KIND_DELETE }, SCOPE_GLOBAL, delta_h, took);
                }
            }
        }

        if let Some(cap) = cap_edges {
            if state.edge_count() > cap {
                let mut t = MapBuilder::new();
                t.set("reason", "mean_degree_cap").set("at_move", mv).set("at_sweep", mv / n.max(1))
                    .set("mean_degree_at_stop", 2.0 * state.edge_count() as f64 / n as f64)
                    .set("cap", mean_degree_cap.unwrap_or(2.0 * (cap as f64) / (n as f64)));
                termination = Some(t);
            }
        }
        let at_record = (mv - segment_start) % record_every == 0 || mv == total_moves - 1;
        let at_stride = mv >= next_clock_move;
        let at_clock = at_record || at_stride;
        let now = if at_clock { Instant::now() } else { last_clock_read };
        if at_stride {
            clock_stride = next_clock_stride(
                clock_stride, now.duration_since(last_clock_read).as_secs_f64(), stop_check_seconds);
            last_clock_read = now;
            next_clock_move = mv + clock_stride;
        }
        let mut stopping = false;
        if termination.is_none() && at_clock && mv + 1 < total_moves {
            if let Some(path) = stop_path.as_ref() {
                if now.duration_since(last_stop_check).as_secs_f64() >= 0.5 * stop_check_seconds {
                    last_stop_check = now;
                    if path.exists() {
                        let mut t = MapBuilder::new();
                        t.set("reason", "stop_requested").set("at_move", mv);
                        termination = Some(t);
                        stopping = true;
                    }
                }
            }
        }
        if termination.is_none() && mv + 1 < total_moves
            && (mv - segment_start) % WORK_CHECK_MOVES == WORK_CHECK_MOVES - 1 {
            if let (Some(room), Some(weights)) = (work_room, work_weights.as_ref()) {
                let now = state.counted();
                let mut spent = weights[0] * moves_run;
                for i in 1..=PARTS {
                    spent += weights[i] * (now[i] - counted_from[i]);
                }
                if spent >= room {
                    let mut t = MapBuilder::new();
                    t.set("reason", "work_budget").set("at_move", mv).set("units", spent);
                    termination = Some(t);
                    stopping = true;
                }
            }
        }
        if stopping && !at_record {
            break;
        }
        if at_record || termination.is_some() {
            let mut point = record_point(&model, &state, energy, mv, n, &attempted, &proposed, &accepted);
            point.set("_energy_is_int", energy_int);
            if trajectory_count % structure_stride == 0 {
                let (components, largest, triangles) = state.trajectory_structure();
                point.set("components", components).set("largest_component", largest).set("triangles", triangles);
            }
            trajectory.push(point.build());
            trajectory_count += 1;
            if let Some(t) = termination.as_mut() {
                t.set("trajectory_points", trajectory_count);
                break;
            }
        }
        move_idx += 1;
    }

    let counted_now = state.counted();
    acc.whole.count(&counted_from, &counted_now, moves_run);
    if let Some(from) = late_counted_from {
        acc.late.count(&from, &counted_now, late_moves_run);
    }
    let (words, index) = rng.state();
    let mut out = MapBuilder::new();
    out.set("edge_list", Value::Pairs(state.edge_list.clone())).set("energy", energy).set("energy_is_int", energy_int)
        .set("trajectory", Value::List(trajectory));
    match (late_from, state.late.take()) {
        (Some(from_move), Some((added, removed))) => {
            let mut added: Vec<Edge> = added.into_iter().collect();
            let mut removed: Vec<Edge> = removed.into_iter().collect();
            added.sort_unstable();
            removed.sort_unstable();
            out.set("late_change", Value::List(vec![from_move.into(), Value::Pairs(added), Value::Pairs(removed)]));
        }
        _ => { out.set("late_change", Value::Null); }
    }
    out.set("attempted", attempted.to_value()).set("proposed", proposed.to_value()).set("accepted", accepted.to_value())
        .set("peak_edge_count", peak_edge_count)
        .set("termination", termination.map(MapBuilder::build).unwrap_or(Value::Null))
        .set("accounting", acc.to_value()).set("mt_words", Value::Words(words)).set("mt_index", index)
        .set("non_edge_fast_path_hits", state.non_edge_fast_path_hits)
        .set("non_edge_exact_fallbacks", state.non_edge_exact_fallbacks)
        .set("ledgers", ledgers_of(&state));
    let degrees: Vec<usize> = state.adj.iter().map(|a| a.len()).collect();
    out.set("degrees", Value::Sizes(degrees)).set("adj", Value::Lists(state.adj.clone()))
        .set("structural_summary", summary_of(&state));
    Ok(out.build())
}

fn ledgers_of(state: &GraphState) -> Value {
    let mut ledgers = MapBuilder::new();
    for (i, name) in LEDGER_NAMES.iter().enumerate() {
        ledgers.set(name, state.ledgers[i]);
    }
    ledgers.build()
}

fn summary_of(state: &GraphState) -> Value {
    let (cf, cc, crd, tcf) = state.structural_summary();
    let mut summary = MapBuilder::new();
    summary.set("connected_fraction", cf).set("component_count", cc)
        .set("largest_component_cycle_rank_density", crd).set("two_core_fraction", tcf);
    summary.build()
}

pub const REBUILD_CLOCK_EDGES: usize = 64;

struct RebuildClock {
    stop_path: Option<std::path::PathBuf>,
    tick: f64,
    last_stop: Instant,
}

fn check_edge_list(n: usize, edge_list: &[(u32, u32)]) -> Answer<()> {
    let mut seen = std::collections::HashSet::with_capacity(edge_list.len());
    for &(u, v) in edge_list {
        if (u as usize) >= n || (v as usize) >= n {
            return Err(Fault::value(
                format!("checkpoint edge ({u}, {v}) has an endpoint outside 0..{n}")));
        }
        if u == v {
            return Err(Fault::value(format!("checkpoint edge ({u}, {v}) is a loop")));
        }
        if !seen.insert((u.min(v), u.max(v))) {
            return Err(Fault::value(
                format!("checkpoint edge ({u}, {v}) appears twice")));
        }
    }
    Ok(())
}

impl RebuildClock {
    fn new(stop_path: Option<std::path::PathBuf>, tick: f64) -> Self {
        RebuildClock { stop_path, tick, last_stop: Instant::now() }
    }

    fn interrupted(&mut self, index: usize) -> Option<&'static str> {
        if index == 0 || index % REBUILD_CLOCK_EDGES != 0 {
            return None;
        }
        let now = Instant::now();
        if now.duration_since(self.last_stop).as_secs_f64() >= 0.5 * self.tick {
            self.last_stop = now;
            if self.stop_path.as_ref().map_or(false, |path| path.exists()) {
                return Some("stop_requested");
            }
        }
        None
    }
}

fn rebuild_graph(request: &Value) -> Answer<Value> {
    let n = field(request, "n")?.as_usize()?;
    let edge_list = field(request, "edge_list")?.as_pairs()?;
    let non_edge_fast_path_hits = optional(request, "non_edge_fast_path_hits", Value::as_u64)?.unwrap_or(0);
    let non_edge_exact_fallbacks = optional(request, "non_edge_exact_fallbacks", Value::as_u64)?.unwrap_or(0);
    let stop_file = optional(request, "stop_file", |v| v.as_str().map(str::to_string))?;
    let stop_check_seconds = optional(request, "stop_check_seconds", Value::as_f64)?.unwrap_or(STOP_CHECK_SECONDS);
    let (terms, node_terms) = parse_terms(field(request, "terms")?)?;
    let required: Vec<Op> = terms.iter().map(|t| t.op).filter(|op| !op.is_node()).collect();
    let model = Model { terms, node_terms };
    check_edge_list(n, &edge_list)?;
    let mut state = GraphState::new(n, &required);
    let started = Instant::now();
    let mut clock = RebuildClock::new(stop_file.map(std::path::PathBuf::from), stop_check_seconds);
    let mut out = MapBuilder::new();
    for (index, &(u, v)) in edge_list.iter().enumerate() {
        if let Some(reason) = clock.interrupted(index) {
            out.set("interrupted", reason).set("edges_rebuilt", index).set("seconds", started.elapsed().as_secs_f64());
            return Ok(out.build());
        }
        let (deltas, _) = model.apply_edge(&mut state, u, v, true);
        state.apply(u, v, true, &deltas);
    }
    state.non_edge_fast_path_hits = non_edge_fast_path_hits;
    state.non_edge_exact_fallbacks = non_edge_exact_fallbacks;
    out.set("edge_list", Value::Pairs(state.edge_list.clone()))
        .set("non_edge_fast_path_hits", state.non_edge_fast_path_hits)
        .set("non_edge_exact_fallbacks", state.non_edge_exact_fallbacks)
        .set("ledgers", ledgers_of(&state)).set("adj", Value::Lists(state.adj.clone()))
        .set("structural_summary", summary_of(&state)).set("seconds", started.elapsed().as_secs_f64());
    Ok(out.build())
}

fn init_random_graph(request: &Value) -> Answer<Value> {
    let n = field(request, "n")?.as_usize()?;
    let target_edges = field(request, "target_edges")?.as_usize()?;
    let mt_words = field(request, "mt_words")?.as_words()?;
    let mt_index = field(request, "mt_index")?.as_usize()?;
    let mut energy = field(request, "energy")?.as_f64()?;
    let mut energy_int = optional(request, "energy_is_int", Value::as_bool)?.unwrap_or(false);
    let (terms, node_terms) = parse_terms(field(request, "terms")?)?;
    let required: Vec<Op> = terms.iter().map(|t| t.op).filter(|op| !op.is_node()).collect();
    let model = Model { terms, node_terms };
    let mut rng = Mt::from_state(&mt_words, mt_index).map_err(Fault::value)?;
    let mut state = GraphState::new(n, &required);
    while state.edge_count() < target_edges {
        let (u, v) = state.sample_non_edge(&mut rng).map_err(Fault::runtime)?;
        let (deltas, dh) = model.apply_edge(&mut state, u, v, true);
        state.apply(u, v, true, &deltas);
        energy += dh;
        energy_int = false;
    }
    let (words, index) = rng.state();
    let mut out = MapBuilder::new();
    out.set("edge_list", Value::Pairs(state.edge_list.clone())).set("adj", Value::Lists(state.adj.clone()))
        .set("energy", energy).set("energy_is_int", energy_int).set("mt_words", Value::Words(words))
        .set("mt_index", index).set("non_edge_fast_path_hits", state.non_edge_fast_path_hits)
        .set("non_edge_exact_fallbacks", state.non_edge_exact_fallbacks).set("ledgers", ledgers_of(&state));
    Ok(out.build())
}

fn init_declared(request: &Value) -> Answer<Value> {
    let n = field(request, "n")?.as_usize()?;
    let edges = field(request, "edges")?.as_pairs()?;
    let mut energy = field(request, "energy")?.as_f64()?;
    let mut energy_int = optional(request, "energy_is_int", Value::as_bool)?.unwrap_or(false);
    let (terms, node_terms) = parse_terms(field(request, "terms")?)?;
    let required: Vec<Op> = terms.iter().map(|t| t.op).filter(|op| !op.is_node()).collect();
    let model = Model { terms, node_terms };
    let mut state = GraphState::new(n, &required);
    for (u, v) in edges {
        if u as usize >= n || v as usize >= n || u == v {
            return Err(Fault::value(format!("declared edge ({u}, {v}) is not an edge of a graph on {n} nodes")));
        }
        if state.has_edge(u, v) {
            continue;
        }
        let (deltas, dh) = model.apply_edge(&mut state, u, v, true);
        state.apply(u, v, true, &deltas);
        energy += dh;
        energy_int = false;
    }
    let mut out = MapBuilder::new();
    out.set("edge_list", Value::Pairs(state.edge_list.clone())).set("adj", Value::Lists(state.adj.clone()))
        .set("energy", energy).set("energy_is_int", energy_int)
        .set("non_edge_fast_path_hits", state.non_edge_fast_path_hits)
        .set("non_edge_exact_fallbacks", state.non_edge_exact_fallbacks).set("ledgers", ledgers_of(&state));
    Ok(out.build())
}

#[allow(clippy::too_many_arguments)]
fn record_point(
    model: &Model, state: &GraphState, energy: f64, mv: usize, n: usize,
    attempted: &Counter, proposed: &Counter, accepted: &Counter,
) -> MapBuilder {
    let mut degree_sum: i128 = 0;
    let mut sq: i128 = 0;
    let mut cube: i128 = 0;
    let mut fourth: i128 = 0;
    let mut max_degree: usize = 0;
    let mut isolated: usize = 0;
    let mut wedge: i128 = 0;
    for a in &state.adj {
        let d = a.len() as i128;
        degree_sum += d;
        sq += d * d;
        cube += d * d * d;
        fourth += (d * d) * (d * d);
        wedge += d * (d - 1) / 2;
        if a.len() > max_degree { max_degree = a.len(); }
        if a.is_empty() { isolated += 1; }
    }
    let nf = n.max(1) as f64;
    let degree_sum_f = degree_sum as f64;
    let degree_square_sum = sq as f64;
    let degree_cube_sum = cube as f64;
    let degree_fourth_sum = fourth as f64;
    let mean_degree = degree_sum_f / nf;
    let degree_variance = (degree_square_sum / nf - mean_degree * mean_degree).max(0.0);

    let mut components: Vec<Value> = Vec::new();
    let mut component_sum = 0.0f64;
    for (term_index, t) in model.terms.iter().enumerate() {
        let observable: f64 = match t.op {
            Op::EdgeCount => state.edge_count() as f64,
            Op::DegreeSquareSum => degree_square_sum,
            Op::WedgeCount => wedge as f64,
            Op::DegreeCubeSum => degree_cube_sum,
            Op::DegreeFourthSum => degree_fourth_sum,
            Op::DegreeAnchor | Op::DegreeAnchorAbs => {
                let k = t.params_k.unwrap_or(0) as i128;
                let mut s: i128 = 0;
                for a in &state.adj {
                    let d = a.len() as i128;
                    s += if t.op == Op::DegreeAnchor { (d - k) * (d - k) } else { (d - k).abs() };
                }
                s as f64
            }
            other => state.ledgers[other.ledger_index().expect("ledger")],
        };
        let energy_component = t.coeff * observable;
        component_sum += energy_component;
        let mut params = MapBuilder::new();
        if let Some(k) = t.params_k { params.set("k", k); }
        let mut c = MapBuilder::new();
        c.set("term_index", term_index).set("op", op_name(t.op)).set("params", params.build())
            .set("scale", t.scale.clone()).set("coefficient", t.coeff).set("observable", observable)
            .set("energy_component", energy_component);
        components.push(c.build());
    }

    let mut p = MapBuilder::new();
    p.set("move", mv).set("energy", energy).set("edges", state.edge_count()).set("mean_degree", mean_degree)
        .set("max_degree", max_degree).set("isolated_fraction", isolated as f64 / nf)
        .set("degree_variance", degree_variance).set("degree_second_moment", degree_square_sum / nf)
        .set("degree_third_moment", degree_cube_sum / nf).set("degree_fourth_moment", degree_fourth_sum / nf)
        .set("active_term_components", Value::List(components)).set("term_energy_sum", component_sum)
        .set("term_energy_residual", energy - component_sum)
        .set("attempted_add", attempted.add).set("attempted_delete", attempted.delete)
        .set("attempted_swap", attempted.swap).set("proposed_add", proposed.add)
        .set("proposed_delete", proposed.delete).set("proposed_swap", proposed.swap)
        .set("accepted_add", accepted.add).set("accepted_delete", accepted.delete).set("accepted_swap", accepted.swap);
    p
}

fn op_name(op: Op) -> &'static str {
    match op {
        Op::EdgeCount => "edge_count",
        Op::DegreeSquareSum => "degree_square_sum",
        Op::WedgeCount => "wedge_count",
        Op::TriangleCount => "triangle_count",
        Op::TriangleEdgeOverlap => "triangle_edge_overlap",
        Op::SquareCount => "square_count",
        Op::SquareEdgeOverlap => "square_edge_overlap",
        Op::InducedSquareCount => "induced_square_count",
        Op::DegreeNeighborGradient => "degree_neighbor_gradient",
        Op::DegreeAnchor => "degree_anchor",
        Op::DegreeAnchorAbs => "degree_anchor_abs",
        Op::DegreeCubeSum => "degree_cube_sum",
        Op::DegreeFourthSum => "degree_fourth_sum",
        Op::OllivierCurvature => "ollivier_curvature",
    }
}

#[pyfunction]
#[pyo3(signature = (n, packed_edges, incremental=false))]
fn curvature_per_edge<'py>(
    py: Python<'py>,
    n: usize,
    packed_edges: &Bound<'py, pyo3::types::PyBytes>,
    incremental: bool,
) -> PyResult<Bound<'py, pyo3::types::PyBytes>> {
    let raw = packed_edges.as_bytes();
    if raw.len() % 8 != 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("packed edges are u32 pairs: 8 bytes each"));
    }
    let edges: Vec<Edge> = raw
        .chunks_exact(8)
        .map(|c| {
            let u = u32::from_ne_bytes([c[0], c[1], c[2], c[3]]);
            let v = u32::from_ne_bytes([c[4], c[5], c[6], c[7]]);
            (u, v)
        })
        .collect();
    let result: Result<Vec<i64>, String> = py.allow_threads(|| {
        if !incremental {
            return graph::curvature_of_graph(n, &edges);
        }
        let mut state = GraphState::new(n, &[Op::OllivierCurvature]);
        for &(u, v) in &edges {
            if u == v || (u as usize) >= n || (v as usize) >= n || state.has_edge(u, v) {
                return Err(format!("edge ({u}, {v}) is a loop, outside 0..{n} or repeated"));
            }
            let deltas = state.op_deltas(u, v, true);
            state.apply(u, v, true, &deltas);
        }
        Ok(edges
            .iter()
            .map(|&(u, v)| {
                let c = state.edge_cycles_of(u, v);
                graph::scaled_curvature(c[0], c[1], c[2], state.degree(u) as i64, state.degree(v) as i64)
            })
            .collect())
    });
    let values = result.map_err(pyo3::exceptions::PyValueError::new_err)?;
    let mut bytes = Vec::with_capacity(values.len() * 8);
    for value in values {
        bytes.extend_from_slice(&value.to_ne_bytes());
    }
    Ok(pyo3::types::PyBytes::new(py, &bytes))
}

pub const OPERATIONS: [&str; 4] = ["init_random_graph", "init_declared", "run_chain", "rebuild_graph"];

pub fn answer(operation: &str, request: &Value) -> Answer<Value> {
    match operation {
        "init_random_graph" => init_random_graph(request),
        "init_declared" => init_declared(request),
        "run_chain" => run_chain(request),
        "rebuild_graph" => rebuild_graph(request),
        other => Err(Fault::value(format!("unknown operation {other}; the engine answers {OPERATIONS:?}"))),
    }
}

fn value_from_py(item: &Bound<'_, PyAny>) -> PyResult<Value> {
    if item.is_none() {
        return Ok(Value::Null);
    }
    if item.is_instance_of::<PyBool>() {
        return Ok(Value::Bool(item.extract()?));
    }
    if item.is_instance_of::<PyInt>() {
        if let Ok(v) = item.extract::<i64>() {
            return Ok(Value::Int(v));
        }
        return Ok(Value::UInt(item.extract::<u64>()?));
    }
    if item.is_instance_of::<PyFloat>() {
        return Ok(Value::Float(item.extract()?));
    }
    if item.is_instance_of::<PyString>() {
        return Ok(Value::Str(item.extract()?));
    }
    if let Ok(d) = item.downcast::<PyDict>() {
        let mut out = Vec::with_capacity(d.len());
        for (k, v) in d.iter() {
            out.push((k.extract::<String>()?, value_from_py(&v)?));
        }
        return Ok(Value::Map(out));
    }
    if item.is_instance_of::<PyList>() || item.is_instance_of::<PyTuple>() {
        if let Ok(pairs) = item.extract::<Vec<(u32, u32)>>() {
            if !pairs.is_empty() {
                return Ok(Value::Pairs(pairs));
            }
        }
        let mut out = Vec::new();
        for v in item.try_iter()? {
            out.push(value_from_py(&v?)?);
        }
        return Ok(Value::List(out));
    }
    Err(pyo3::exceptions::PyTypeError::new_err(format!(
        "a request is plain data: {} is not", item.get_type().name()?)))
}

const SHARED_NUMBERS: usize = 1 << 26;

struct Numbers(Vec<Option<PyObject>>);

impl Numbers {
    fn of(&mut self, py: Python<'_>, value: u32) -> PyResult<PyObject> {
        let at = value as usize;
        if at >= SHARED_NUMBERS {
            return Ok(value.into_pyobject(py)?.into_any().unbind());
        }
        if at >= self.0.len() {
            self.0.resize_with(at + 1, || None);
        }
        if self.0[at].is_none() {
            self.0[at] = Some(value.into_pyobject(py)?.into_any().unbind());
        }
        Ok(self.0[at].as_ref().expect("a number just kept").clone_ref(py))
    }
}

fn value_to_py(py: Python<'_>, value: Value) -> PyResult<PyObject> {
    to_py(py, value, &mut Numbers(Vec::new()))
}

fn to_py(py: Python<'_>, value: Value, numbers: &mut Numbers) -> PyResult<PyObject> {
    Ok(match value {
        Value::Null => py.None(),
        Value::Bool(v) => v.into_pyobject(py)?.to_owned().into_any().unbind(),
        Value::Int(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::UInt(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::Float(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::Str(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::List(items) => {
            let list = PyList::empty(py);
            for item in items {
                list.append(to_py(py, item, numbers)?)?;
            }
            list.into_any().unbind()
        }
        Value::Map(items) => {
            let d = PyDict::new(py);
            for (k, v) in items {
                d.set_item(k, to_py(py, v, numbers)?)?;
            }
            d.into_any().unbind()
        }
        Value::Pairs(v) => {
            let mut pairs = Vec::with_capacity(v.len());
            for (a, b) in v {
                pairs.push(PyTuple::new(py, [numbers.of(py, a)?, numbers.of(py, b)?])?);
            }
            PyList::new(py, pairs)?.into_any().unbind()
        }
        Value::Lists(v) => {
            let mut lists = Vec::with_capacity(v.len());
            for row in v {
                let mut kept = Vec::with_capacity(row.len());
                for x in row {
                    kept.push(numbers.of(py, x)?);
                }
                lists.push(PyList::new(py, kept)?);
            }
            PyList::new(py, lists)?.into_any().unbind()
        }
        Value::Words(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::Sizes(v) => v.into_pyobject(py)?.into_any().unbind(),
    })
}

fn fault_to_py(fault: Fault) -> PyErr {
    match fault.kind {
        "FloatingPointError" => pyo3::exceptions::PyFloatingPointError::new_err(fault.message),
        "RuntimeError" => pyo3::exceptions::PyRuntimeError::new_err(fault.message),
        "KeyError" => pyo3::exceptions::PyKeyError::new_err(fault.message),
        _ => pyo3::exceptions::PyValueError::new_err(fault.message),
    }
}

#[pyfunction]
fn call(py: Python<'_>, operation: &str, request: &Bound<'_, PyAny>) -> PyResult<PyObject> {
    let request = value_from_py(request)?;
    let operation = operation.to_string();
    let answered = py.allow_threads(move || answer(&operation, &request));
    value_to_py(py, answered.map_err(fault_to_py)?)
}

fn answered_as_json(operation: &str, request: &str) -> String {
    let answered = Value::from_json(request).and_then(|request| answer(operation, &request));
    let mut out = MapBuilder::new();
    match answered {
        Ok(value) => { out.set("answer", value); }
        Err(fault) => {
            let mut f = MapBuilder::new();
            f.set("kind", fault.kind).set("message", fault.message);
            out.set("fault", f.build());
        }
    }
    out.build().to_json()
}

#[no_mangle]
pub extern "C" fn gsd_engine_call(operation: *const std::os::raw::c_char,
                                  request: *const std::os::raw::c_char) -> *mut std::os::raw::c_char {
    let read = |text: *const std::os::raw::c_char| -> Option<String> {
        if text.is_null() {
            return None;
        }
        unsafe { std::ffi::CStr::from_ptr(text) }.to_str().ok().map(str::to_string)
    };
    let out = match (read(operation), read(request)) {
        (Some(operation), Some(request)) => answered_as_json(&operation, &request),
        _ => "{\"fault\":{\"kind\":\"ValueError\",\"message\":\"the operation and the request are UTF-8 text\"}}"
            .to_string(),
    };
    std::ffi::CString::new(out).map(|c| c.into_raw()).unwrap_or(std::ptr::null_mut())
}

#[no_mangle]
pub extern "C" fn gsd_engine_free(answered: *mut std::os::raw::c_char) {
    if !answered.is_null() {
        drop(unsafe { std::ffi::CString::from_raw(answered) });
    }
}

#[no_mangle]
pub extern "C" fn gsd_engine_version() -> *const std::os::raw::c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const std::os::raw::c_char
}

#[pymodule]
fn gsd_engine_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("FINGERPRINT", FINGERPRINT)?;
    m.add("OPERATIONS", OPERATIONS.to_vec())?;
    m.add_function(wrap_pyfunction!(next_clock_stride_py, m)?)?;
    m.add_function(wrap_pyfunction!(delta_h_bin_py, m)?)?;
    m.add_function(wrap_pyfunction!(structure_point_stride_py, m)?)?;
    m.add("CLOCK_STRIDE_START_MOVES", CLOCK_STRIDE_START_MOVES)?;
    m.add("REBUILD_CLOCK_EDGES", REBUILD_CLOCK_EDGES)?;
    m.add("CLOCK_STRIDE_MAX_MOVES", CLOCK_STRIDE_MAX_MOVES)?;
    m.add("STOP_CHECK_SECONDS", STOP_CHECK_SECONDS)?;
    m.add("WORK_CHECK_MOVES", WORK_CHECK_MOVES)?;
    m.add("STRUCTURE_POINT_STRIDE", STRUCTURE_POINT_STRIDE)?;
    m.add("DELTA_H_BIN_LIMIT", accounting::DELTA_H_BIN_LIMIT)?;
    m.add_function(wrap_pyfunction!(call, m)?)?;
    m.add_function(wrap_pyfunction!(curvature_per_edge, m)?)?;
    Ok(())
}
