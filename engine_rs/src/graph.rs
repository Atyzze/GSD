use std::cell::Cell;
use std::collections::{HashMap, HashSet};

use crate::mt::Mt;

pub const PARTS: usize = 5;
pub const PART_EVALUATIONS: usize = 0;
pub const PART_CHANGES: usize = 1;
pub const PART_LISTS: usize = 2;
pub const PART_ENTRIES: usize = 3;
pub const PART_TESTS: usize = 4;

pub type Edge = (u32, u32);

#[inline]
pub fn edge(u: u32, v: u32) -> Edge {
    if u < v {
        (u, v)
    } else {
        (v, u)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Op {
    EdgeCount,
    DegreeSquareSum,
    WedgeCount,
    TriangleCount,
    TriangleEdgeOverlap,
    SquareCount,
    SquareEdgeOverlap,
    InducedSquareCount,
    DegreeNeighborGradient,
    DegreeAnchor,
    DegreeAnchorAbs,
    DegreeCubeSum,
    DegreeFourthSum,
    OllivierCurvature,
}

impl Op {
    pub fn parse(name: &str) -> Option<Op> {
        Some(match name {
            "edge_count" => Op::EdgeCount,
            "degree_square_sum" => Op::DegreeSquareSum,
            "wedge_count" => Op::WedgeCount,
            "triangle_count" => Op::TriangleCount,
            "triangle_edge_overlap" => Op::TriangleEdgeOverlap,
            "square_count" => Op::SquareCount,
            "square_edge_overlap" => Op::SquareEdgeOverlap,
            "induced_square_count" => Op::InducedSquareCount,
            "degree_neighbor_gradient" => Op::DegreeNeighborGradient,
            "degree_anchor" => Op::DegreeAnchor,
            "degree_anchor_abs" => Op::DegreeAnchorAbs,
            "degree_cube_sum" => Op::DegreeCubeSum,
            "degree_fourth_sum" => Op::DegreeFourthSum,
            "ollivier_curvature" => Op::OllivierCurvature,
            _ => return None,
        })
    }

    pub fn is_node(self) -> bool {
        matches!(
            self,
            Op::DegreeAnchor | Op::DegreeAnchorAbs | Op::DegreeCubeSum | Op::DegreeFourthSum
        )
    }

    pub fn ledger_index(self) -> Option<usize> {
        Some(match self {
            Op::EdgeCount => 0,
            Op::DegreeSquareSum => 1,
            Op::WedgeCount => 2,
            Op::TriangleCount => 3,
            Op::TriangleEdgeOverlap => 4,
            Op::SquareCount => 5,
            Op::SquareEdgeOverlap => 6,
            Op::InducedSquareCount => 7,
            Op::DegreeNeighborGradient => 8,
            Op::OllivierCurvature => 9,
            _ => return None,
        })
    }
}

pub const LEDGERS: usize = 10;

pub const LEDGER_NAMES: [&str; LEDGERS] = [
    "edge_count",
    "degree_square_sum",
    "wedge_count",
    "triangle_count",
    "triangle_edge_overlap",
    "square_count",
    "square_edge_overlap",
    "induced_square_count",
    "degree_neighbor_gradient",
    "ollivier_curvature",
];

struct Fenwick {
    tree: Vec<i64>,
    size: usize,
}

impl Fenwick {
    fn new(values: &[i64]) -> Self {
        let size = values.len();
        let mut tree = vec![0i64; size + 1];
        for (i, v) in values.iter().enumerate() {
            let mut idx = i + 1;
            while idx <= size {
                tree[idx] += v;
                idx += idx & idx.wrapping_neg();
            }
        }
        Fenwick { tree, size }
    }

    fn add(&mut self, index: usize, delta: i64) {
        let mut idx = index + 1;
        while idx <= self.size {
            self.tree[idx] += delta;
            idx += idx & idx.wrapping_neg();
        }
    }

    fn total(&self) -> i64 {
        let mut idx = self.size;
        let mut s = 0;
        while idx > 0 {
            s += self.tree[idx];
            idx -= idx & idx.wrapping_neg();
        }
        s
    }

    fn find_by_order(&self, mut order: i64) -> usize {
        let mut pos = 0usize;
        let mut step = 1usize;
        while step * 2 <= self.size {
            step *= 2;
        }
        while step > 0 {
            let next = pos + step;
            if next <= self.size && self.tree[next] <= order {
                order -= self.tree[next];
                pos = next;
            }
            step /= 2;
        }
        pos
    }
}

pub struct Deltas {
    pub ledger: [f64; LEDGERS],
}

pub struct GraphState {
    pub n: usize,
    pub adj: Vec<Vec<u32>>,
    pub edge_list: Vec<Edge>,
    edge_index: HashMap<Edge, usize>,
    pub non_degree: Vec<i64>,
    tree: Fenwick,
    pub non_edge_fast_path_hits: u64,
    pub non_edge_exact_fallbacks: u64,
    pub ledgers: [f64; LEDGERS],
    edge_square_counts: HashMap<Edge, i64>,
    required: [bool; LEDGERS],
    edge_cycles: HashMap<Edge, [i64; 3]>,
    last_curvature: Option<((u32, u32, bool), HashMap<Edge, [i64; 3]>, [i64; 3])>,
    mark: Vec<u32>,
    stamp: u32,
    last_square_key: Option<(u32, u32, bool)>,
    last_square_paths: Vec<(u32, u32)>,
    last_square_multiplicity: Option<HashMap<Edge, i64>>,
    pub late: Option<(HashSet<Edge>, HashSet<Edge>)>,
    pub work: Cell<u64>,
    pub parts: [Cell<u64>; PARTS],
}

impl GraphState {
    pub fn new(n: usize, required_ops: &[Op]) -> Self {
        let mut required = [false; LEDGERS];
        for op in required_ops {
            if let Some(i) = op.ledger_index() {
                required[i] = true;
            }
        }
        let non_degree = vec![(n as i64) - 1; n];
        GraphState {
            n,
            adj: vec![Vec::new(); n],
            edge_list: Vec::new(),
            edge_index: HashMap::new(),
            tree: Fenwick::new(&non_degree),
            non_degree,
            non_edge_fast_path_hits: 0,
            non_edge_exact_fallbacks: 0,
            ledgers: [0.0; LEDGERS],
            edge_square_counts: HashMap::new(),
            required,
            edge_cycles: HashMap::new(),
            last_curvature: None,
            mark: vec![0; n],
            stamp: 0,
            last_square_key: None,
            last_square_paths: Vec::new(),
            last_square_multiplicity: None,
            late: None,
            work: Cell::new(0),
            parts: Default::default(),
        }
    }

    #[inline]
    fn add(&self, part: usize, amount: usize) {
        self.parts[part].set(self.parts[part].get() + amount as u64);
    }

    #[inline]
    fn spend(&self, amount: usize) {
        self.work.set(self.work.get() + amount as u64);
    }

    #[inline]
    pub fn read_lists(&self, lists: usize, entries: usize) {
        self.spend(entries);
        self.add(PART_LISTS, lists);
        self.add(PART_ENTRIES, entries);
    }

    #[inline]
    pub fn scan(&self, entries: usize) {
        self.spend(entries);
        self.add(PART_ENTRIES, entries);
    }

    #[inline]
    pub fn units(&self, count: usize) {
        self.spend(count);
        self.add(PART_TESTS, count);
    }

    #[inline]
    pub fn tested(&self) {
        self.add(PART_TESTS, 1);
    }

    pub fn counted(&self) -> [u64; PARTS + 1] {
        let mut out = [0u64; PARTS + 1];
        out[0] = self.work.get();
        for (i, part) in self.parts.iter().enumerate() {
            out[i + 1] = part.get();
        }
        out
    }

    #[inline]
    pub fn edge_count(&self) -> usize {
        self.edge_list.len()
    }

    #[inline]
    pub fn degree(&self, v: u32) -> usize {
        self.adj[v as usize].len()
    }

    #[inline]
    pub fn tests_edge(&self, u: u32, v: u32) -> bool {
        self.tested();
        self.has_edge(u, v)
    }

    #[inline]
    pub fn has_edge(&self, u: u32, v: u32) -> bool {
        let (a, b) = if self.adj[u as usize].len() <= self.adj[v as usize].len() {
            (u, v)
        } else {
            (v, u)
        };
        self.adj[a as usize].contains(&b)
    }

    fn next_stamp(&mut self) -> u32 {
        self.stamp = self.stamp.wrapping_add(1);
        if self.stamp == 0 {
            for m in self.mark.iter_mut() {
                *m = 0;
            }
            self.stamp = 1;
        }
        self.stamp
    }

    pub fn sample_non_edge(&mut self, rng: &mut Mt) -> Result<Edge, String> {
        let oriented_missing = self.tree.total();
        if oriented_missing <= 0 {
            return Err("complete graph has no non-edge".into());
        }
        let n = self.n;
        for _ in 0..16 {
            self.units(1);
            let u = rng.randrange(n) as u32;
            let mut v = if n > 1 { rng.randrange(n - 1) as u32 } else { 0 };
            if v >= u {
                v += 1;
            }
            if v != u && !self.adj[u as usize].contains(&v) {
                self.non_edge_fast_path_hits += 1;
                return Ok(edge(u, v));
            }
        }
        self.non_edge_exact_fallbacks += 1;
        let u = self.tree.find_by_order(rng.randbelow(oriented_missing as u128) as i64) as u32;
        let missing = self.non_degree[u as usize];
        if missing <= 0 {
            return Err("complement-degree sampler selected a saturated vertex".into());
        }
        for _ in 0..64 {
            self.units(1);
            let v = rng.randrange(n) as u32;
            if v != u && !self.adj[u as usize].contains(&v) {
                return Ok(edge(u, v));
            }
        }
        let mut rank = rng.randbelow(missing as u128) as i64;
        for v in 0..n as u32 {
            self.units(1);
            if v == u || self.adj[u as usize].contains(&v) {
                continue;
            }
            if rank == 0 {
                return Ok(edge(u, v));
            }
            rank -= 1;
        }
        Err("complement-degree ledger disagrees with adjacency".into())
    }

    fn square_paths(&mut self, u: u32, v: u32) -> Vec<(u32, u32)> {
        let mut work = self.adj[u as usize].len() + self.adj[v as usize].len();
        let mut lists = 2;
        let stamp = self.next_stamp();
        for &y in &self.adj[v as usize] {
            if y != u {
                self.mark[y as usize] = stamp;
            }
        }
        let mut paths = Vec::new();
        for &x in &self.adj[u as usize] {
            if x == v {
                continue;
            }
            work += self.adj[x as usize].len();
            lists += 1;
            for &y in &self.adj[x as usize] {
                if self.mark[y as usize] == stamp {
                    paths.push((x, y));
                }
            }
        }
        self.read_lists(lists, work);
        paths
    }

    fn square_multiplicity(u: u32, v: u32, paths: &[(u32, u32)]) -> HashMap<Edge, i64> {
        let mut m: HashMap<Edge, i64> = HashMap::new();
        for &(x, y) in paths {
            *m.entry(edge(u, x)).or_insert(0) += 1;
            *m.entry(edge(x, y)).or_insert(0) += 1;
            *m.entry(edge(y, v)).or_insert(0) += 1;
        }
        m
    }

    fn square_overlap_delta(&self, adding: bool, paths_len: i64, multiplicity: &HashMap<Edge, i64>) -> f64 {
        let s = paths_len;
        if adding {
            let mut delta = (s * (s - 1) / 2) as f64;
            for (e, &m) in multiplicity {
                let q = *self.edge_square_counts.get(e).unwrap_or(&0);
                delta += (m * q) as f64 + (m * (m - 1) / 2) as f64;
            }
            delta
        } else {
            let mut delta = -((s * (s - 1) / 2) as f64);
            for (e, &m) in multiplicity {
                let q = *self.edge_square_counts.get(e).unwrap_or(&0);
                delta += (-m * q) as f64 + (m * (m + 1) / 2) as f64;
            }
            delta
        }
    }

    fn common_neighbours(&mut self, u: u32, v: u32) -> Vec<u32> {
        self.read_lists(2, self.adj[u as usize].len() + self.adj[v as usize].len());
        let stamp = self.next_stamp();
        for &x in &self.adj[u as usize] {
            self.mark[x as usize] = stamp;
        }
        let mut common = Vec::new();
        for &y in &self.adj[v as usize] {
            if self.mark[y as usize] == stamp {
                common.push(y);
            }
        }
        common
    }

    fn intersection_size(&mut self, a: u32, b: u32) -> i64 {
        self.read_lists(2, self.adj[a as usize].len() + self.adj[b as usize].len());
        let stamp = self.next_stamp();
        for &x in &self.adj[a as usize] {
            self.mark[x as usize] = stamp;
        }
        self.adj[b as usize].iter().filter(|y| self.mark[**y as usize] == stamp).count() as i64
    }

    fn cycle_paths(&mut self, u: u32, v: u32) -> (Vec<u32>, Vec<(u32, u32)>, Vec<(u32, u32, u32)>) {
        let mut work = self.adj[u as usize].len() + self.adj[v as usize].len();
        let mut lists = 2;
        let stamp = self.next_stamp();
        for &y in &self.adj[v as usize] {
            if y != u {
                self.mark[y as usize] = stamp;
            }
        }
        let in_nv = |mark: &Vec<u32>, y: u32| mark[y as usize] == stamp;
        let mut triangles = Vec::new();
        let mut squares = Vec::new();
        let mut pentagons = Vec::new();
        for &x in &self.adj[u as usize] {
            if x == v {
                continue;
            }
            if in_nv(&self.mark, x) {
                triangles.push(x);
            }
            work += 2 * self.adj[x as usize].len();
            lists += 2;
            for &y in &self.adj[x as usize] {
                if in_nv(&self.mark, y) {
                    squares.push((x, y));
                }
            }
            for &z in &self.adj[x as usize] {
                if z == u || z == v {
                    continue;
                }
                work += self.adj[z as usize].len();
                lists += 1;
                for &y in &self.adj[z as usize] {
                    if y != x && in_nv(&self.mark, y) {
                        pentagons.push((x, z, y));
                    }
                }
            }
        }
        self.read_lists(lists, work);
        (triangles, squares, pentagons)
    }

    fn curvature_delta(&mut self, u: u32, v: u32, adding: bool) -> (i64, HashMap<Edge, [i64; 3]>, [i64; 3]) {
        let sign: i64 = if adding { 1 } else { -1 };
        let (triangles, squares, pentagons) = self.cycle_paths(u, v);
        let mut changes: HashMap<Edge, [i64; 3]> = HashMap::new();
        let mut bump = |a: u32, b: u32, index: usize| {
            changes.entry(edge(a, b)).or_insert([0, 0, 0])[index] += sign;
        };
        for &w in &triangles {
            bump(u, w, 0);
            bump(w, v, 0);
        }
        for &(x, y) in &squares {
            bump(u, x, 1);
            bump(x, y, 1);
            bump(y, v, 1);
        }
        for &(x, z, y) in &pentagons {
            bump(u, x, 2);
            bump(x, z, 2);
            bump(z, y, 2);
            bump(y, v, 2);
        }
        let mut affected: std::collections::HashSet<Edge> = changes.keys().copied().collect();
        for &x in &self.adj[u as usize] {
            if x != v {
                affected.insert(edge(u, x));
            }
        }
        for &y in &self.adj[v as usize] {
            if y != u {
                affected.insert(edge(v, y));
            }
        }
        self.read_lists(2, self.adj[u as usize].len() + self.adj[v as usize].len());
        self.units(affected.len());
        let degree = |node: u32| self.adj[node as usize].len() as i64;
        let after = |node: u32| degree(node) + if node == u || node == v { sign } else { 0 };
        let mut delta: i64 = 0;
        for e in &affected {
            let (a, b) = *e;
            let before = self.edge_cycles.get(e).copied().unwrap_or([0, 0, 0]);
            let moved = changes.get(e).copied().unwrap_or([0, 0, 0]);
            delta += scaled_curvature(before[0] + moved[0], before[1] + moved[1], before[2] + moved[2],
                                      after(a), after(b));
            delta -= scaled_curvature(before[0], before[1], before[2], degree(a), degree(b));
        }
        let own = [triangles.len() as i64, squares.len() as i64, pentagons.len() as i64];
        if adding {
            delta += scaled_curvature(own[0], own[1], own[2], after(u), after(v));
        } else {
            delta -= scaled_curvature(own[0], own[1], own[2], degree(u), degree(v));
        }
        (delta, changes, own)
    }

    fn update_edge_cycles(&mut self, u: u32, v: u32, adding: bool, changes: &HashMap<Edge, [i64; 3]>,
                          own: [i64; 3]) {
        for (e, moved) in changes {
            let before = self.edge_cycles.get(e).copied().unwrap_or([0, 0, 0]);
            let now = [before[0] + moved[0], before[1] + moved[1], before[2] + moved[2]];
            if now != [0, 0, 0] {
                self.edge_cycles.insert(*e, now);
            } else {
                self.edge_cycles.remove(e);
            }
        }
        let toggled = edge(u, v);
        if adding && own != [0, 0, 0] {
            self.edge_cycles.insert(toggled, own);
        } else {
            self.edge_cycles.remove(&toggled);
        }
    }

    pub fn op_deltas(&mut self, u: u32, v: u32, adding: bool) -> Deltas {
        self.spend(1);
        self.add(PART_EVALUATIONS, 1);
        let sign = if adding { 1.0 } else { -1.0 };
        let mut du = self.adj[u as usize].len() as i64;
        let mut dv = self.adj[v as usize].len() as i64;
        if !adding {
            du -= 1;
            dv -= 1;
        }
        let mut d = [0.0f64; LEDGERS];
        d[0] = sign;
        d[1] = sign * ((2 * du + 1 + 2 * dv + 1) as f64);
        d[2] = sign * ((du + dv) as f64);

        if self.required[9] {
            let (delta, changes, own) = self.curvature_delta(u, v, adding);
            d[9] = delta as f64;
            self.last_curvature = Some(((u, v, adding), changes, own));
        } else {
            self.last_curvature = None;
        }

        if self.required[8] {
            let read = self.adj[u as usize].len() + self.adj[v as usize].len();
            self.read_lists(2, read);
            self.add(PART_LISTS, read);
            let mut gradient = sign * (((du - dv) * (du - dv)) as f64);
            for &x in &self.adj[u as usize] {
                if x != v {
                    gradient += sign * ((2 * (du - self.adj[x as usize].len() as i64) + 1) as f64);
                }
            }
            for &y in &self.adj[v as usize] {
                if y != u {
                    gradient += sign * ((2 * (dv - self.adj[y as usize].len() as i64) + 1) as f64);
                }
            }
            d[8] = gradient;
        }

        let neighbourhood = self.required[3] || self.required[4] || self.required[5]
            || self.required[6] || self.required[7] || self.required[8];
        if !neighbourhood {
            self.last_square_key = None;
            self.last_square_paths.clear();
            self.last_square_multiplicity = None;
            return Deltas { ledger: d };
        }

        let common_nodes = self.common_neighbours(u, v);
        let common = common_nodes.len() as i64;
        d[3] = sign * (common as f64);

        let square_required = self.required[5] || self.required[6] || self.required[7];
        let square_paths = if square_required { self.square_paths(u, v) } else { Vec::new() };
        if square_required {
            self.last_square_key = Some((u, v, adding));
            self.last_square_multiplicity = None;
        } else {
            self.last_square_key = None;
            self.last_square_paths.clear();
            self.last_square_multiplicity = None;
        }

        if self.required[5] {
            d[5] = sign * (square_paths.len() as f64);
        }

        if self.required[7] {
            self.units(2 * square_paths.len() + common_nodes.len() * common_nodes.len().saturating_sub(1) / 2);
            let mut boundary = 0i64;
            for &(x, y) in &square_paths {
                if !self.adj[u as usize].contains(&y) && !self.adj[v as usize].contains(&x) {
                    boundary += 1;
                }
            }
            let mut diagonal = 0i64;
            for i in 0..common_nodes.len() {
                let x = common_nodes[i];
                for &y in &common_nodes[i + 1..] {
                    if !self.adj[x as usize].contains(&y) {
                        diagonal += 1;
                    }
                }
            }
            d[7] = sign * ((boundary - diagonal) as f64);
        }

        if self.required[6] {
            let multiplicity = Self::square_multiplicity(u, v, &square_paths);
            self.units(3 * square_paths.len() + multiplicity.len());
            d[6] = self.square_overlap_delta(adding, square_paths.len() as i64, &multiplicity);
            self.last_square_multiplicity = Some(multiplicity);
        }

        if self.required[4] {
            let mut overlap: f64;
            if adding {
                overlap = (common * (common - 1) / 2) as f64;
                for &w in &common_nodes {
                    overlap += self.intersection_size(u, w) as f64;
                    overlap += self.intersection_size(v, w) as f64;
                }
            } else {
                overlap = -((common * (common - 1) / 2) as f64);
                for &w in &common_nodes {
                    overlap -= (self.intersection_size(u, w) - 1).max(0) as f64;
                    overlap -= (self.intersection_size(v, w) - 1).max(0) as f64;
                }
            }
            d[4] = overlap;
        }
        if square_required {
            self.last_square_paths = square_paths;
        }
        Deltas { ledger: d }
    }

    fn update_square_edge_counts(&mut self, u: u32, v: u32, adding: bool,
                                 paths: &[(u32, u32)], multiplicity: Option<&HashMap<Edge, i64>>) {
        let owned;
        let multiplicity = match multiplicity {
            Some(m) => m,
            None => {
                owned = Self::square_multiplicity(u, v, paths);
                &owned
            }
        };
        let toggled = edge(u, v);
        if adding {
            for (e, &m) in multiplicity {
                *self.edge_square_counts.entry(*e).or_insert(0) += m;
            }
            if !paths.is_empty() {
                self.edge_square_counts.insert(toggled, paths.len() as i64);
            } else {
                self.edge_square_counts.remove(&toggled);
            }
            return;
        }
        for (e, &m) in multiplicity {
            let value = self.edge_square_counts.get(e).copied().unwrap_or(0) - m;
            if value > 0 {
                self.edge_square_counts.insert(*e, value);
            } else {
                self.edge_square_counts.remove(e);
            }
        }
        self.edge_square_counts.remove(&toggled);
    }

    pub fn apply(&mut self, u: u32, v: u32, adding: bool, deltas: &Deltas) {
        self.spend(1);
        self.add(PART_CHANGES, 1);
        if self.required[9] {
            let cached = self.last_curvature.take();
            let (changes, own) = match cached {
                Some((key, changes, own)) if key == (u, v, adding) => (changes, own),
                _ => {
                    let (_, changes, own) = self.curvature_delta(u, v, adding);
                    (changes, own)
                }
            };
            self.update_edge_cycles(u, v, adding, &changes, own);
        }
        self.last_curvature = None;
        if self.required[6] {
            if self.last_square_key == Some((u, v, adding)) {
                let paths = std::mem::take(&mut self.last_square_paths);
                let mult = self.last_square_multiplicity.take();
                self.update_square_edge_counts(u, v, adding, &paths, mult.as_ref());
            } else {
                let paths = self.square_paths(u, v);
                self.update_square_edge_counts(u, v, adding, &paths, None);
            }
        }
        self.last_square_key = None;
        self.last_square_paths.clear();
        self.last_square_multiplicity = None;
        let e = edge(u, v);
        if adding {
            self.adj[u as usize].push(v);
            self.adj[v as usize].push(u);
            self.non_degree[u as usize] -= 1;
            self.non_degree[v as usize] -= 1;
            self.tree.add(u as usize, -1);
            self.tree.add(v as usize, -1);
            self.edge_index.insert(e, self.edge_list.len());
            self.edge_list.push(e);
            if let Some((added, removed)) = self.late.as_mut() {
                if !removed.remove(&e) {
                    added.insert(e);
                }
            }
        } else {
            remove_from(&mut self.adj[u as usize], v);
            remove_from(&mut self.adj[v as usize], u);
            self.non_degree[u as usize] += 1;
            self.non_degree[v as usize] += 1;
            self.tree.add(u as usize, 1);
            self.tree.add(v as usize, 1);
            let index = self.edge_index.remove(&e).expect("edge index");
            let last = *self.edge_list.last().expect("edge list");
            if index != self.edge_list.len() - 1 {
                self.edge_list[index] = last;
                self.edge_index.insert(last, index);
            }
            self.edge_list.pop();
            if let Some((added, removed)) = self.late.as_mut() {
                if !added.remove(&e) {
                    removed.insert(e);
                }
            }
        }
        for i in 0..LEDGERS {
            self.ledgers[i] += deltas.ledger[i];
        }
    }

    pub fn structural_summary(&self) -> (f64, usize, f64, f64) {
        let n = self.n;
        let mut seen = vec![false; n];
        let mut component_count = 0usize;
        let mut largest: Vec<u32> = Vec::new();
        let mut stack: Vec<u32> = Vec::new();
        let mut comp: Vec<u32> = Vec::new();
        for start in 0..n {
            if seen[start] {
                continue;
            }
            stack.clear();
            comp.clear();
            stack.push(start as u32);
            seen[start] = true;
            while let Some(node) = stack.pop() {
                comp.push(node);
                for &other in &self.adj[node as usize] {
                    if !seen[other as usize] {
                        seen[other as usize] = true;
                        stack.push(other);
                    }
                }
            }
            component_count += 1;
            if comp.len() > largest.len() {
                largest = comp.clone();
            }
        }
        let mut in_largest = vec![false; n];
        for &v in &largest {
            in_largest[v as usize] = true;
        }
        let mut largest_edges = 0usize;
        let mut degree = vec![0i64; n];
        for &v in &largest {
            let d = self.adj[v as usize].iter().filter(|o| in_largest[**o as usize]).count();
            largest_edges += d;
            degree[v as usize] = d as i64;
        }
        largest_edges /= 2;
        let ls = largest.len();
        let cycle_rank = (largest_edges as i64 - ls as i64 + if ls > 0 { 1 } else { 0 }).max(0);
        let mut removed = vec![false; n];
        let mut queue: Vec<u32> = Vec::new();
        for &v in &largest {
            if degree[v as usize] < 2 {
                removed[v as usize] = true;
                queue.push(v);
            }
        }
        let mut cursor = 0usize;
        while cursor < queue.len() {
            let v = queue[cursor];
            cursor += 1;
            for &other in &self.adj[v as usize] {
                if in_largest[other as usize] && !removed[other as usize] {
                    degree[other as usize] -= 1;
                    if degree[other as usize] < 2 {
                        removed[other as usize] = true;
                        queue.push(other);
                    }
                }
            }
        }
        let nf = n.max(1) as f64;
        let lf = ls.max(1) as f64;
        (
            ls as f64 / nf,
            component_count,
            cycle_rank as f64 / lf,
            (ls as f64 - queue.len() as f64) / lf,
        )
    }

    pub fn trajectory_structure(&self) -> (usize, usize, u64) {
        let n = self.n;
        let mut seen = vec![false; n];
        let mut stack: Vec<u32> = Vec::new();
        let mut components = 0usize;
        let mut largest = 0usize;
        for start in 0..n {
            if seen[start] {
                continue;
            }
            components += 1;
            seen[start] = true;
            stack.push(start as u32);
            let mut size = 0usize;
            while let Some(node) = stack.pop() {
                size += 1;
                for &other in &self.adj[node as usize] {
                    if !seen[other as usize] {
                        seen[other as usize] = true;
                        stack.push(other);
                    }
                }
            }
            largest = largest.max(size);
        }
        let rank_below = |a: usize, b: usize| (self.adj[a].len(), a) < (self.adj[b].len(), b);
        let up: Vec<Vec<u32>> = (0..n)
            .map(|u| self.adj[u].iter().copied().filter(|&v| rank_below(u, v as usize)).collect())
            .collect();
        let mut mark = vec![usize::MAX; n];
        let mut triangles = 0u64;
        for u in 0..n {
            for &w in &up[u] {
                mark[w as usize] = u;
            }
            for &v in &up[u] {
                for &w in &up[v as usize] {
                    if mark[w as usize] == u {
                        triangles += 1;
                    }
                }
            }
        }
        (components, largest, triangles)
    }

    pub fn edge_cycles_of(&self, u: u32, v: u32) -> [i64; 3] {
        self.edge_cycles.get(&edge(u, v)).copied().unwrap_or([0, 0, 0])
    }
}

pub fn count_cycles(adj: &[Vec<u32>], mark: &mut [u32], stamp: u32, u: u32, v: u32) -> [i64; 3] {
    for &y in &adj[v as usize] {
        if y != u {
            mark[y as usize] = stamp;
        }
    }
    let (mut t, mut s, mut p) = (0i64, 0i64, 0i64);
    for &x in &adj[u as usize] {
        if x == v {
            continue;
        }
        if mark[x as usize] == stamp {
            t += 1;
        }
        for &z in &adj[x as usize] {
            if mark[z as usize] == stamp {
                s += 1;
            }
            if z == u || z == v {
                continue;
            }
            for &y in &adj[z as usize] {
                if y != x && mark[y as usize] == stamp {
                    p += 1;
                }
            }
        }
    }
    [t, s, p]
}

pub fn curvature_of_graph(n: usize, edges: &[Edge]) -> Result<Vec<i64>, String> {
    let mut adj: Vec<Vec<u32>> = vec![Vec::new(); n];
    for &(u, v) in edges {
        if u == v || (u as usize) >= n || (v as usize) >= n {
            return Err(format!("edge ({u}, {v}) is a loop or outside 0..{n}"));
        }
        adj[u as usize].push(v);
        adj[v as usize].push(u);
    }
    for (node, list) in adj.iter_mut().enumerate() {
        list.sort_unstable();
        if list.windows(2).any(|w| w[0] == w[1]) {
            return Err(format!("an edge at node {node} is repeated"));
        }
    }
    let mut mark = vec![0u32; n];
    let mut out = Vec::with_capacity(edges.len());
    let mut stamp: u32 = 0;
    for &(u, v) in edges {
        if stamp == u32::MAX {
            mark.iter_mut().for_each(|m| *m = 0);
            stamp = 0;
        }
        stamp += 1;
        let c = count_cycles(&adj, &mut mark, stamp, u, v);
        out.push(scaled_curvature(c[0], c[1], c[2], adj[u as usize].len() as i64, adj[v as usize].len() as i64));
    }
    Ok(out)
}

#[inline]
pub fn scaled_curvature(t: i64, s: i64, p: i64, da: i64, db: i64) -> i64 {
    let (low, high) = if da <= db { (da, db) } else { (db, da) };
    t * high
        - (low * high - (1 + t + s) * low - high).max(0)
        - (t * high - t * low).max(low * high - (1 + t + s + p) * low - high)
}

fn remove_from(list: &mut Vec<u32>, value: u32) {
    if let Some(pos) = list.iter().position(|&x| x == value) {
        list.swap_remove(pos);
    }
}
