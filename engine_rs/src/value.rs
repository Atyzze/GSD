use std::fmt::Write as _;

#[derive(Clone, Debug)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    UInt(u64),
    Float(f64),
    Str(String),
    List(Vec<Value>),
    Map(Vec<(String, Value)>),
    Pairs(Vec<(u32, u32)>),
    Lists(Vec<Vec<u32>>),
    Words(Vec<u32>),
    Sizes(Vec<usize>),
}

#[derive(Clone, Debug)]
pub struct Fault {
    pub kind: &'static str,
    pub message: String,
}

impl Fault {
    pub fn new(kind: &'static str, message: impl Into<String>) -> Self {
        Fault { kind, message: message.into() }
    }
    pub fn value(message: impl Into<String>) -> Self {
        Fault::new("ValueError", message)
    }
    pub fn key(message: impl Into<String>) -> Self {
        Fault::new("KeyError", message)
    }
    pub fn floating(message: impl Into<String>) -> Self {
        Fault::new("FloatingPointError", message)
    }
    pub fn runtime(message: impl Into<String>) -> Self {
        Fault::new("RuntimeError", message)
    }
}

pub type Answer<T> = Result<T, Fault>;

pub struct MapBuilder(Vec<(String, Value)>);

impl MapBuilder {
    pub fn new() -> Self {
        MapBuilder(Vec::new())
    }
    pub fn set(&mut self, key: &str, value: impl Into<Value>) -> &mut Self {
        let value = value.into();
        if let Some(slot) = self.0.iter_mut().find(|(k, _)| k == key) {
            slot.1 = value;
        } else {
            self.0.push((key.to_string(), value));
        }
        self
    }
    pub fn build(self) -> Value {
        Value::Map(self.0)
    }
}

impl From<bool> for Value {
    fn from(v: bool) -> Self { Value::Bool(v) }
}
impl From<i64> for Value {
    fn from(v: i64) -> Self { Value::Int(v) }
}
impl From<u64> for Value {
    fn from(v: u64) -> Self { Value::UInt(v) }
}
impl From<usize> for Value {
    fn from(v: usize) -> Self { Value::UInt(v as u64) }
}
impl From<u32> for Value {
    fn from(v: u32) -> Self { Value::UInt(v as u64) }
}
impl From<f64> for Value {
    fn from(v: f64) -> Self { Value::Float(v) }
}
impl From<&str> for Value {
    fn from(v: &str) -> Self { Value::Str(v.to_string()) }
}
impl From<String> for Value {
    fn from(v: String) -> Self { Value::Str(v) }
}
impl<T: Into<Value>> From<Option<T>> for Value {
    fn from(v: Option<T>) -> Self {
        match v { Some(x) => x.into(), None => Value::Null }
    }
}

impl Value {
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Map(items) => items.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn present(&self, key: &str) -> Option<&Value> {
        self.get(key).filter(|v| !matches!(v, Value::Null))
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    pub fn as_i64(&self) -> Answer<i64> {
        match self {
            Value::Int(v) => Ok(*v),
            Value::UInt(v) if *v <= i64::MAX as u64 => Ok(*v as i64),
            Value::Bool(v) => Ok(*v as i64),
            other => Err(Fault::value(format!("expected an integer, got {}", other.kind()))),
        }
    }

    pub fn as_u64(&self) -> Answer<u64> {
        match self {
            Value::UInt(v) => Ok(*v),
            Value::Int(v) if *v >= 0 => Ok(*v as u64),
            Value::Bool(v) => Ok(*v as u64),
            other => Err(Fault::value(format!("expected a non-negative integer, got {}", other.kind()))),
        }
    }

    pub fn as_usize(&self) -> Answer<usize> {
        Ok(self.as_u64()? as usize)
    }

    pub fn as_u32(&self) -> Answer<u32> {
        let v = self.as_u64()?;
        u32::try_from(v).map_err(|_| Fault::value(format!("{v} does not fit 32 bits")))
    }

    pub fn as_f64(&self) -> Answer<f64> {
        match self {
            Value::Float(v) => Ok(*v),
            Value::Int(v) => Ok(*v as f64),
            Value::UInt(v) => Ok(*v as f64),
            Value::Bool(v) => Ok(if *v { 1.0 } else { 0.0 }),
            other => Err(Fault::value(format!("expected a number, got {}", other.kind()))),
        }
    }

    pub fn as_bool(&self) -> Answer<bool> {
        match self {
            Value::Bool(v) => Ok(*v),
            Value::Int(v) => Ok(*v != 0),
            Value::UInt(v) => Ok(*v != 0),
            other => Err(Fault::value(format!("expected a boolean, got {}", other.kind()))),
        }
    }

    pub fn as_str(&self) -> Answer<&str> {
        match self {
            Value::Str(v) => Ok(v),
            other => Err(Fault::value(format!("expected a string, got {}", other.kind()))),
        }
    }

    pub fn items(&self) -> Answer<Vec<Value>> {
        match self {
            Value::List(items) => Ok(items.clone()),
            Value::Pairs(pairs) => Ok(pairs.iter().map(|&(u, v)| Value::List(vec![u.into(), v.into()])).collect()),
            Value::Words(words) => Ok(words.iter().map(|&w| w.into()).collect()),
            Value::Sizes(sizes) => Ok(sizes.iter().map(|&s| s.into()).collect()),
            Value::Lists(lists) => Ok(lists.iter().map(|l| Value::Words(l.clone())).collect()),
            other => Err(Fault::value(format!("expected a list, got {}", other.kind()))),
        }
    }

    pub fn as_pairs(&self) -> Answer<Vec<(u32, u32)>> {
        match self {
            Value::Pairs(pairs) => Ok(pairs.clone()),
            Value::List(items) => items.iter().map(|item| {
                let pair = item.items()?;
                if pair.len() != 2 {
                    return Err(Fault::value("an edge is a pair of nodes"));
                }
                Ok((pair[0].as_u32()?, pair[1].as_u32()?))
            }).collect(),
            other => Err(Fault::value(format!("expected a list of edges, got {}", other.kind()))),
        }
    }

    pub fn as_words(&self) -> Answer<Vec<u32>> {
        match self {
            Value::Words(words) => Ok(words.clone()),
            _ => self.items()?.iter().map(|v| v.as_u32()).collect(),
        }
    }

    fn kind(&self) -> &'static str {
        match self {
            Value::Null => "null",
            Value::Bool(_) => "a boolean",
            Value::Int(_) | Value::UInt(_) => "an integer",
            Value::Float(_) => "a float",
            Value::Str(_) => "a string",
            Value::Map(_) => "a map",
            _ => "a list",
        }
    }

    pub fn to_json(&self) -> String {
        let mut out = String::new();
        self.write_json(&mut out);
        out
    }

    fn write_json(&self, out: &mut String) {
        match self {
            Value::Null => out.push_str("null"),
            Value::Bool(v) => out.push_str(if *v { "true" } else { "false" }),
            Value::Int(v) => { let _ = write!(out, "{v}"); }
            Value::UInt(v) => { let _ = write!(out, "{v}"); }
            Value::Float(v) => write_float(out, *v),
            Value::Str(v) => write_string(out, v),
            Value::List(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i > 0 { out.push(','); }
                    item.write_json(out);
                }
                out.push(']');
            }
            Value::Map(items) => {
                out.push('{');
                for (i, (key, item)) in items.iter().enumerate() {
                    if i > 0 { out.push(','); }
                    write_string(out, key);
                    out.push(':');
                    item.write_json(out);
                }
                out.push('}');
            }
            Value::Pairs(pairs) => {
                out.push('[');
                for (i, (u, v)) in pairs.iter().enumerate() {
                    if i > 0 { out.push(','); }
                    let _ = write!(out, "[{u},{v}]");
                }
                out.push(']');
            }
            Value::Lists(lists) => {
                out.push('[');
                for (i, list) in lists.iter().enumerate() {
                    if i > 0 { out.push(','); }
                    write_numbers(out, list.iter().map(|&w| w as u64));
                }
                out.push(']');
            }
            Value::Words(words) => write_numbers(out, words.iter().map(|&w| w as u64)),
            Value::Sizes(sizes) => write_numbers(out, sizes.iter().map(|&s| s as u64)),
        }
    }

    pub fn from_json(text: &str) -> Answer<Value> {
        let mut parser = Parser { bytes: text.as_bytes(), at: 0 };
        parser.space();
        let value = parser.value()?;
        parser.space();
        if parser.at != parser.bytes.len() {
            return Err(Fault::value(format!("JSON has more after its value at byte {}", parser.at)));
        }
        Ok(value)
    }
}

fn write_numbers(out: &mut String, values: impl Iterator<Item = u64>) {
    out.push('[');
    for (i, value) in values.enumerate() {
        if i > 0 { out.push(','); }
        let _ = write!(out, "{value}");
    }
    out.push(']');
}

fn write_float(out: &mut String, v: f64) {
    if v.is_nan() {
        out.push_str("NaN");
    } else if v.is_infinite() {
        out.push_str(if v > 0.0 { "Infinity" } else { "-Infinity" });
    } else {
        let _ = write!(out, "{v:?}");
    }
}

fn write_string(out: &mut String, text: &str) {
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => { let _ = write!(out, "\\u{:04x}", c as u32); }
            c => out.push(c),
        }
    }
    out.push('"');
}

struct Parser<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl<'a> Parser<'a> {
    fn space(&mut self) {
        while self.at < self.bytes.len() && matches!(self.bytes[self.at], b' ' | b'\n' | b'\r' | b'\t') {
            self.at += 1;
        }
    }

    fn fault(&self, what: &str) -> Fault {
        Fault::value(format!("JSON: {what} at byte {}", self.at))
    }

    fn word(&mut self, word: &str) -> bool {
        if self.bytes[self.at..].starts_with(word.as_bytes()) {
            self.at += word.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self) -> Answer<Value> {
        let Some(&c) = self.bytes.get(self.at) else { return Err(self.fault("a value is missing")) };
        match c {
            b'{' => self.map(),
            b'[' => self.list(),
            b'"' => Ok(Value::Str(self.string()?)),
            b'n' if self.word("null") => Ok(Value::Null),
            b't' if self.word("true") => Ok(Value::Bool(true)),
            b'f' if self.word("false") => Ok(Value::Bool(false)),
            b'N' if self.word("NaN") => Ok(Value::Float(f64::NAN)),
            b'I' if self.word("Infinity") => Ok(Value::Float(f64::INFINITY)),
            b'-' if self.word("-Infinity") => Ok(Value::Float(f64::NEG_INFINITY)),
            b'-' | b'0'..=b'9' => self.number(),
            _ => Err(self.fault("an unexpected character")),
        }
    }

    fn number(&mut self) -> Answer<Value> {
        let start = self.at;
        let mut float = false;
        while let Some(&c) = self.bytes.get(self.at) {
            match c {
                b'0'..=b'9' | b'-' | b'+' => {}
                b'.' | b'e' | b'E' => float = true,
                _ => break,
            }
            self.at += 1;
        }
        let text = std::str::from_utf8(&self.bytes[start..self.at]).map_err(|_| self.fault("a number"))?;
        if float {
            return text.parse::<f64>().map(Value::Float).map_err(|_| self.fault("a float"));
        }
        if let Ok(v) = text.parse::<i64>() {
            return Ok(Value::Int(v));
        }
        text.parse::<u64>().map(Value::UInt).map_err(|_| self.fault("an integer"))
    }

    fn string(&mut self) -> Answer<String> {
        self.at += 1;
        let mut out = String::new();
        loop {
            let Some(&c) = self.bytes.get(self.at) else { return Err(self.fault("a string never ends")) };
            self.at += 1;
            match c {
                b'"' => return Ok(out),
                b'\\' => {
                    let Some(&e) = self.bytes.get(self.at) else { return Err(self.fault("an escape never ends")) };
                    self.at += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let high = self.hex()?;
                            let code = if (0xD800..0xDC00).contains(&high) {
                                if !self.word("\\u") {
                                    return Err(self.fault("a lone surrogate"));
                                }
                                let low = self.hex()?;
                                0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00)
                            } else {
                                high
                            };
                            out.push(char::from_u32(code).ok_or_else(|| self.fault("a bad code point"))?);
                        }
                        _ => return Err(self.fault("an unknown escape")),
                    }
                }
                _ => {
                    let start = self.at - 1;
                    let mut end = self.at;
                    while end < self.bytes.len() && !matches!(self.bytes[end], b'"' | b'\\') {
                        end += 1;
                    }
                    out.push_str(std::str::from_utf8(&self.bytes[start..end]).map_err(|_| self.fault("bad UTF-8"))?);
                    self.at = end;
                }
            }
        }
    }

    fn hex(&mut self) -> Answer<u32> {
        let digits = self.bytes.get(self.at..self.at + 4).ok_or_else(|| self.fault("a short \\u escape"))?;
        let text = std::str::from_utf8(digits).map_err(|_| self.fault("a \\u escape"))?;
        self.at += 4;
        u32::from_str_radix(text, 16).map_err(|_| self.fault("a \\u escape"))
    }

    fn list(&mut self) -> Answer<Value> {
        self.at += 1;
        let mut items = Vec::new();
        self.space();
        if self.bytes.get(self.at) == Some(&b']') {
            self.at += 1;
            return Ok(Value::List(items));
        }
        loop {
            self.space();
            items.push(self.value()?);
            self.space();
            match self.bytes.get(self.at) {
                Some(b',') => self.at += 1,
                Some(b']') => { self.at += 1; return Ok(Value::List(items)); }
                _ => return Err(self.fault("a list is not closed")),
            }
        }
    }

    fn map(&mut self) -> Answer<Value> {
        self.at += 1;
        let mut items = Vec::new();
        self.space();
        if self.bytes.get(self.at) == Some(&b'}') {
            self.at += 1;
            return Ok(Value::Map(items));
        }
        loop {
            self.space();
            if self.bytes.get(self.at) != Some(&b'"') {
                return Err(self.fault("a key is not a string"));
            }
            let key = self.string()?;
            self.space();
            if self.bytes.get(self.at) != Some(&b':') {
                return Err(self.fault("a key has no value"));
            }
            self.at += 1;
            self.space();
            let value = self.value()?;
            items.push((key, value));
            self.space();
            match self.bytes.get(self.at) {
                Some(b',') => self.at += 1,
                Some(b'}') => { self.at += 1; return Ok(Value::Map(items)); }
                _ => return Err(self.fault("a map is not closed")),
            }
        }
    }
}
