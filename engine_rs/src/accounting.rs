use std::collections::BTreeMap;

use crate::value::{Answer, MapBuilder, Value};

pub const KINDS: [&str; 3] = ["add", "delete", "swap"];
pub const SCOPES: [&str; 2] = ["local", "global"];
pub const SIGNS: [&str; 3] = ["neg", "zero", "pos"];
pub const OUTCOMES: [&str; 2] = ["accepted", "rejected"];
pub const KEYS: usize = 36;
pub const DELTA_H_BIN_LIMIT: i32 = 40;
pub const LATE_QUARTERS: usize = 3;

pub const KIND_ADD: usize = 0;
pub const KIND_DELETE: usize = 1;
pub const KIND_SWAP: usize = 2;
pub const SCOPE_LOCAL: usize = 0;
pub const SCOPE_GLOBAL: usize = 1;

fn key_name(index: usize) -> String {
    let outcome = index % 2;
    let sign = (index / 2) % 3;
    let scope = (index / 6) % 2;
    let kind = index / 12;
    format!("{}.{}.{}.{}", KINDS[kind], SCOPES[scope], SIGNS[sign], OUTCOMES[outcome])
}

pub fn delta_h_bin(delta_h: f64) -> String {
    if delta_h == 0.0 {
        return "0".to_string();
    }
    let bits = delta_h.abs().to_bits();
    let biased = ((bits >> 52) & 0x7ff) as i32;
    let exponent = if biased == 0 { -1074 } else { biased - 1022 };
    let clamped = exponent.clamp(-DELTA_H_BIN_LIMIT, DELTA_H_BIN_LIMIT);
    format!("{}2^{}", if delta_h > 0.0 { "+" } else { "-" }, clamped)
}

pub const PART_NAMES: [&str; 6] = ["moves", "evaluations", "changes", "lists", "entries", "tests"];

#[derive(Clone)]
pub struct Block {
    pub work: u64,
    pub parts: [u64; 6],
    pub counts: [u64; KEYS],
    pub proposed: BTreeMap<String, u64>,
    pub accepted: BTreeMap<String, u64>,
}

impl Default for Block {
    fn default() -> Self {
        Block { work: 0, parts: [0; 6], counts: [0; KEYS], proposed: BTreeMap::new(), accepted: BTreeMap::new() }
    }
}

impl Block {
    fn from_value(value: Option<&Value>) -> Answer<Self> {
        let mut block = Block::default();
        let Some(d) = value.filter(|v| !v.is_null()) else { return Ok(block) };
        if let Some(work) = d.present("work") {
            block.work = work.as_u64()?;
        }
        if let Some(parts) = d.present("parts") {
            for (i, name) in PART_NAMES.iter().enumerate() {
                if let Some(v) = parts.get(name) {
                    block.parts[i] = v.as_u64()?;
                }
            }
        }
        if let Some(counts) = d.get("counts") {
            for i in 0..KEYS {
                if let Some(v) = counts.get(&key_name(i)) {
                    block.counts[i] = v.as_u64()?;
                }
            }
        }
        if let Some(hist) = d.get("delta_h_log2") {
            for (side, target) in [("proposed", &mut block.proposed), ("accepted", &mut block.accepted)] {
                if let Some(Value::Map(bins)) = hist.get(side) {
                    for (k, v) in bins {
                        target.insert(k.clone(), v.as_u64()?);
                    }
                }
            }
        }
        Ok(block)
    }

    fn fill(&self, d: &mut MapBuilder) {
        let mut counts = MapBuilder::new();
        for i in 0..KEYS {
            counts.set(&key_name(i), self.counts[i]);
        }
        d.set("counts", counts.build());
        let mut hist = MapBuilder::new();
        for (side, source) in [("proposed", &self.proposed), ("accepted", &self.accepted)] {
            let mut bins = MapBuilder::new();
            for (k, v) in source {
                bins.set(k, *v);
            }
            hist.set(side, bins.build());
        }
        d.set("delta_h_log2", hist.build());
        d.set("work", self.work);
        let mut parts = MapBuilder::new();
        for (i, name) in PART_NAMES.iter().enumerate() {
            parts.set(name, self.parts[i]);
        }
        d.set("parts", parts.build());
    }

    pub fn count(&mut self, from: &[u64; 6], now: &[u64; 6], moves: u64) {
        self.work += now[0] - from[0];
        self.parts[0] += moves;
        for i in 1..6 {
            self.parts[i] += now[i] - from[i];
        }
    }

    #[inline]
    fn add(&mut self, index: usize, bin: &str, took: bool) {
        self.counts[index] += 1;
        *self.proposed.entry(bin.to_string()).or_insert(0) += 1;
        if took {
            *self.accepted.entry(bin.to_string()).or_insert(0) += 1;
        }
    }
}

#[derive(Default, Clone)]
pub struct Accounting {
    pub whole: Block,
    pub late: Block,
    pub late_from: Option<usize>,
    pub last_decrease_move: Option<usize>,
}

impl Accounting {
    pub fn from_value(value: Option<&Value>) -> Answer<Self> {
        let mut acc = Accounting::default();
        let Some(d) = value.filter(|v| !v.is_null()) else { return Ok(acc) };
        acc.whole = Block::from_value(Some(d))?;
        if let Some(late) = d.present("late") {
            acc.late = Block::from_value(Some(late))?;
            acc.late_from = late.present("from_move").and_then(|v| v.as_usize().ok());
        }
        acc.last_decrease_move = d.present("last_decrease_move").and_then(|v| v.as_usize().ok());
        Ok(acc)
    }

    pub fn to_value(&self) -> Value {
        let mut d = MapBuilder::new();
        d.set("contract", "move-accounting-1");
        self.whole.fill(&mut d);
        let mut late = MapBuilder::new();
        late.set("from_move", self.late_from);
        self.late.fill(&mut late);
        d.set("late", late.build());
        d.set("last_decrease_move", self.last_decrease_move);
        d.build()
    }

    pub fn start_segment(&mut self, start_move: usize, segment_start: usize, segment_moves: usize) {
        let late_from = segment_start + (LATE_QUARTERS * segment_moves) / 4;
        if start_move == segment_start || self.late_from != Some(late_from) {
            self.late = Block::default();
            self.late_from = Some(late_from);
        }
    }

    #[inline]
    pub fn tally(&mut self, mv: usize, kind: usize, scope: usize, delta_h: f64, took: bool) {
        let sign = if delta_h < 0.0 { 0 } else if delta_h > 0.0 { 2 } else { 1 };
        let outcome = if took { 0 } else { 1 };
        let index = ((kind * 2 + scope) * 3 + sign) * 2 + outcome;
        let bin = delta_h_bin(delta_h);
        self.whole.add(index, &bin, took);
        if took && delta_h < 0.0 {
            self.last_decrease_move = Some(mv);
        }
        if mv >= self.late_from.unwrap_or(usize::MAX) {
            self.late.add(index, &bin, took);
        }
    }
}
