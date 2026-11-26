#include "value.h"

#include <errno.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int fault(Fault *f, const char *kind, const char *fmt, ...) {
    if (f && !f->set) {
        va_list args;
        va_start(args, fmt);
        vsnprintf(f->message, sizeof f->message, fmt, args);
        va_end(args);
        f->kind = kind;
        f->set = 1;
    }
    return -1;
}

typedef struct {
    const unsigned char *b;
    size_t at, len;
    Fault *f;
} Parser;

static int pfault(Parser *p, const char *what) {
    return fault(p->f, "ValueError", "JSON: %s at byte %zu", what, p->at);
}

static void space(Parser *p) {
    while (p->at < p->len && (p->b[p->at] == ' ' || p->b[p->at] == '\n' || p->b[p->at] == '\r' || p->b[p->at] == '\t'))
        p->at++;
}

static int word(Parser *p, const char *w) {
    size_t n = strlen(w);
    if (p->at + n <= p->len && memcmp(p->b + p->at, w, n) == 0) {
        p->at += n;
        return 1;
    }
    return 0;
}

static int parse_value(Parser *p, Value *out);

static int grow(void **items, size_t *cap, size_t need, size_t size) {
    if (need <= *cap) return 0;
    size_t cap2 = *cap ? *cap * 2 : 8;
    while (cap2 < need) cap2 *= 2;
    void *next = realloc(*items, cap2 * size);
    if (!next) return -1;
    *items = next;
    *cap = cap2;
    return 0;
}

static int parse_number(Parser *p, Value *out) {
    size_t start = p->at;
    int is_float = 0;
    while (p->at < p->len) {
        unsigned char c = p->b[p->at];
        if ((c >= '0' && c <= '9') || c == '-' || c == '+') {
        } else if (c == '.' || c == 'e' || c == 'E') {
            is_float = 1;
        } else {
            break;
        }
        p->at++;
    }
    size_t n = p->at - start;
    char buf[64];
    if (n == 0 || n >= sizeof buf) return pfault(p, is_float ? "a float" : "an integer");
    memcpy(buf, p->b + start, n);
    buf[n] = 0;
    char *end = NULL;
    if (is_float) {
        errno = 0;
        double v = strtod(buf, &end);
        if (end != buf + n) return pfault(p, "a float");
        out->kind = V_FLOAT;
        out->as.f = v;
        return 0;
    }
    errno = 0;
    long long i = strtoll(buf, &end, 10);
    if (end == buf + n && errno == 0) {
        out->kind = V_INT;
        out->as.i = (int64_t)i;
        return 0;
    }
    if (buf[0] == '-') return pfault(p, "an integer");
    errno = 0;
    unsigned long long u = strtoull(buf, &end, 10);
    if (end != buf + n || errno != 0) return pfault(p, "an integer");
    out->kind = V_UINT;
    out->as.u = (uint64_t)u;
    return 0;
}

static int put_utf8(char **s, size_t *len, size_t *cap, uint32_t code) {
    unsigned char tmp[4];
    size_t n;
    if (code < 0x80) { tmp[0] = (unsigned char)code; n = 1; }
    else if (code < 0x800) { tmp[0] = 0xC0 | (code >> 6); tmp[1] = 0x80 | (code & 0x3F); n = 2; }
    else if (code < 0x10000) {
        tmp[0] = 0xE0 | (code >> 12); tmp[1] = 0x80 | ((code >> 6) & 0x3F); tmp[2] = 0x80 | (code & 0x3F); n = 3;
    } else {
        tmp[0] = 0xF0 | (code >> 18); tmp[1] = 0x80 | ((code >> 12) & 0x3F);
        tmp[2] = 0x80 | ((code >> 6) & 0x3F); tmp[3] = 0x80 | (code & 0x3F); n = 4;
    }
    if (grow((void **)s, cap, *len + n + 1, 1)) return -1;
    memcpy(*s + *len, tmp, n);
    *len += n;
    return 0;
}

static int hex4(Parser *p, uint32_t *out) {
    if (p->at + 4 > p->len) return pfault(p, "a short \\u escape");
    uint32_t v = 0;
    for (int i = 0; i < 4; i++) {
        unsigned char c = p->b[p->at + i];
        v <<= 4;
        if (c >= '0' && c <= '9') v |= c - '0';
        else if (c >= 'a' && c <= 'f') v |= c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v |= c - 'A' + 10;
        else return pfault(p, "a \\u escape");
    }
    p->at += 4;
    *out = v;
    return 0;
}

static int parse_string(Parser *p, char **out_s, size_t *out_len) {
    p->at++;
    char *s = NULL;
    size_t len = 0, cap = 0;
    if (grow((void **)&s, &cap, 16, 1)) return fault(p->f, "RuntimeError", "out of memory");
    for (;;) {
        if (p->at >= p->len) { free(s); return pfault(p, "a string never ends"); }
        unsigned char c = p->b[p->at++];
        if (c == '"') break;
        if (c == '\\') {
            if (p->at >= p->len) { free(s); return pfault(p, "an escape never ends"); }
            unsigned char e = p->b[p->at++];
            uint32_t code;
            switch (e) {
                case '"': code = '"'; break;
                case '\\': code = '\\'; break;
                case '/': code = '/'; break;
                case 'b': code = 8; break;
                case 'f': code = 12; break;
                case 'n': code = '\n'; break;
                case 'r': code = '\r'; break;
                case 't': code = '\t'; break;
                case 'u': {
                    uint32_t high;
                    if (hex4(p, &high)) { free(s); return -1; }
                    if (high >= 0xD800 && high < 0xDC00) {
                        if (!word(p, "\\u")) { free(s); return pfault(p, "a lone surrogate"); }
                        uint32_t low;
                        if (hex4(p, &low)) { free(s); return -1; }
                        code = 0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00);
                    } else {
                        code = high;
                    }
                    break;
                }
                default: free(s); return pfault(p, "an unknown escape");
            }
            if (put_utf8(&s, &len, &cap, code)) { free(s); return fault(p->f, "RuntimeError", "out of memory"); }
            continue;
        }
        if (grow((void **)&s, &cap, len + 2, 1)) { free(s); return fault(p->f, "RuntimeError", "out of memory"); }
        s[len++] = (char)c;
    }
    s[len] = 0;
    *out_s = s;
    *out_len = len;
    return 0;
}

static int read_u32(Parser *p, uint32_t *out) {
    size_t start = p->at;
    uint64_t v = 0;
    while (p->at < p->len && p->b[p->at] >= '0' && p->b[p->at] <= '9') {
        v = v * 10 + (p->b[p->at] - '0');
        if (v > 0xFFFFFFFFu) return -1;
        p->at++;
    }
    if (p->at == start) return -1;
    if (p->at < p->len && (p->b[p->at] == '.' || p->b[p->at] == 'e' || p->b[p->at] == 'E')) return -1;
    *out = (uint32_t)v;
    return 0;
}

static int try_pairs(Parser *p, Value *out) {
    size_t back = p->at;
    uint32_t *ab = NULL;
    size_t n = 0, cap = 0;
    p->at++;
    space(p);
    for (;;) {
        uint32_t a, b;
        if (p->at >= p->len || p->b[p->at] != '[') goto fail;
        p->at++;
        space(p);
        if (read_u32(p, &a)) goto fail;
        space(p);
        if (p->at >= p->len || p->b[p->at] != ',') goto fail;
        p->at++;
        space(p);
        if (read_u32(p, &b)) goto fail;
        space(p);
        if (p->at >= p->len || p->b[p->at] != ']') goto fail;
        p->at++;
        if (grow((void **)&ab, &cap, 2 * (n + 1), sizeof *ab)) goto fail;
        ab[2 * n] = a;
        ab[2 * n + 1] = b;
        n++;
        space(p);
        if (p->at < p->len && p->b[p->at] == ',') { p->at++; space(p); continue; }
        if (p->at < p->len && p->b[p->at] == ']') { p->at++; break; }
        goto fail;
    }
    out->kind = V_PAIRS;
    out->as.pairs.ab = ab;
    out->as.pairs.n = n;
    out->as.pairs.cap = cap;
    return 1;
fail:
    free(ab);
    p->at = back;
    return 0;
}

static int parse_list(Parser *p, Value *out) {
    size_t look = p->at + 1;
    while (look < p->len && (p->b[look] == ' ' || p->b[look] == '\n' || p->b[look] == '\r' || p->b[look] == '\t'))
        look++;
    if (look < p->len && p->b[look] == '[' && try_pairs(p, out)) return 0;
    p->at++;
    out->kind = V_LIST;
    out->as.list.items = NULL;
    out->as.list.n = out->as.list.cap = 0;
    space(p);
    if (p->at < p->len && p->b[p->at] == ']') { p->at++; return 0; }
    for (;;) {
        space(p);
        if (grow((void **)&out->as.list.items, &out->as.list.cap, out->as.list.n + 1, sizeof(Value)))
            return fault(p->f, "RuntimeError", "out of memory");
        Value *item = &out->as.list.items[out->as.list.n];
        item->kind = V_NULL;
        if (parse_value(p, item)) return -1;
        out->as.list.n++;
        space(p);
        if (p->at < p->len && p->b[p->at] == ',') { p->at++; continue; }
        if (p->at < p->len && p->b[p->at] == ']') { p->at++; return 0; }
        return pfault(p, "a list is not closed");
    }
}

static int parse_map(Parser *p, Value *out) {
    p->at++;
    out->kind = V_MAP;
    out->as.map.keys = NULL;
    out->as.map.vals = NULL;
    out->as.map.n = out->as.map.cap = 0;
    space(p);
    if (p->at < p->len && p->b[p->at] == '}') { p->at++; return 0; }
    for (;;) {
        space(p);
        if (p->at >= p->len || p->b[p->at] != '"') return pfault(p, "a key is not a string");
        char *key;
        size_t key_len;
        if (parse_string(p, &key, &key_len)) return -1;
        space(p);
        if (p->at >= p->len || p->b[p->at] != ':') { free(key); return pfault(p, "a key has no value"); }
        p->at++;
        space(p);
        size_t cap_keys = out->as.map.cap;
        if (out->as.map.n + 1 > out->as.map.cap) {
            size_t cap2 = cap_keys ? cap_keys * 2 : 8;
            char **keys = realloc(out->as.map.keys, cap2 * sizeof(char *));
            if (!keys) { free(key); return fault(p->f, "RuntimeError", "out of memory"); }
            out->as.map.keys = keys;
            Value *vals = realloc(out->as.map.vals, cap2 * sizeof(Value));
            if (!vals) { free(key); return fault(p->f, "RuntimeError", "out of memory"); }
            out->as.map.vals = vals;
            out->as.map.cap = cap2;
        }
        out->as.map.keys[out->as.map.n] = key;
        Value *item = &out->as.map.vals[out->as.map.n];
        item->kind = V_NULL;
        out->as.map.n++;
        if (parse_value(p, item)) return -1;
        space(p);
        if (p->at < p->len && p->b[p->at] == ',') { p->at++; continue; }
        if (p->at < p->len && p->b[p->at] == '}') { p->at++; return 0; }
        return pfault(p, "a map is not closed");
    }
}

static int parse_value(Parser *p, Value *out) {
    if (p->at >= p->len) return pfault(p, "a value is missing");
    unsigned char c = p->b[p->at];
    if (c == '{') return parse_map(p, out);
    if (c == '[') return parse_list(p, out);
    if (c == '"') {
        out->kind = V_STR;
        return parse_string(p, &out->as.str.s, &out->as.str.len);
    }
    if (c == 'n' && word(p, "null")) { out->kind = V_NULL; return 0; }
    if (c == 't' && word(p, "true")) { out->kind = V_BOOL; out->as.b = 1; return 0; }
    if (c == 'f' && word(p, "false")) { out->kind = V_BOOL; out->as.b = 0; return 0; }
    if (c == 'N' && word(p, "NaN")) { out->kind = V_FLOAT; out->as.f = NAN; return 0; }
    if (c == 'I' && word(p, "Infinity")) { out->kind = V_FLOAT; out->as.f = INFINITY; return 0; }
    if (c == '-' && word(p, "-Infinity")) { out->kind = V_FLOAT; out->as.f = -INFINITY; return 0; }
    if (c == '-' || (c >= '0' && c <= '9')) return parse_number(p, out);
    return pfault(p, "an unexpected character");
}

int value_parse(const char *text, Value *out, Fault *f) {
    Parser p = {(const unsigned char *)text, 0, strlen(text), f};
    out->kind = V_NULL;
    space(&p);
    if (parse_value(&p, out)) return -1;
    space(&p);
    if (p.at != p.len) return fault(f, "ValueError", "JSON has more after its value at byte %zu", p.at);
    return 0;
}

void value_free(Value *v) {
    if (!v) return;
    switch (v->kind) {
        case V_STR: free(v->as.str.s); break;
        case V_LIST:
            for (size_t i = 0; i < v->as.list.n; i++) value_free(&v->as.list.items[i]);
            free(v->as.list.items);
            break;
        case V_MAP:
            for (size_t i = 0; i < v->as.map.n; i++) {
                free(v->as.map.keys[i]);
                value_free(&v->as.map.vals[i]);
            }
            free(v->as.map.keys);
            free(v->as.map.vals);
            break;
        case V_PAIRS: free(v->as.pairs.ab); break;
        default: break;
    }
    v->kind = V_NULL;
}

const Value *value_get(const Value *map, const char *key) {
    if (!map || map->kind != V_MAP) return NULL;
    for (size_t i = 0; i < map->as.map.n; i++)
        if (strcmp(map->as.map.keys[i], key) == 0) return &map->as.map.vals[i];
    return NULL;
}

const Value *value_present(const Value *map, const char *key) {
    const Value *v = value_get(map, key);
    return v && v->kind != V_NULL ? v : NULL;
}

int value_is_null(const Value *v) { return !v || v->kind == V_NULL; }

const char *value_kind(const Value *v) {
    switch (v->kind) {
        case V_NULL: return "null";
        case V_BOOL: return "a boolean";
        case V_INT: case V_UINT: return "an integer";
        case V_FLOAT: return "a float";
        case V_STR: return "a string";
        case V_MAP: return "a map";
        default: return "a list";
    }
}

int as_i64(const Value *v, int64_t *out, Fault *f) {
    if (v->kind == V_INT) { *out = v->as.i; return 0; }
    if (v->kind == V_UINT && v->as.u <= (uint64_t)INT64_MAX) { *out = (int64_t)v->as.u; return 0; }
    if (v->kind == V_BOOL) { *out = v->as.b; return 0; }
    return fault(f, "ValueError", "expected an integer, got %s", value_kind(v));
}

int as_u64(const Value *v, uint64_t *out, Fault *f) {
    if (v->kind == V_UINT) { *out = v->as.u; return 0; }
    if (v->kind == V_INT && v->as.i >= 0) { *out = (uint64_t)v->as.i; return 0; }
    if (v->kind == V_BOOL) { *out = (uint64_t)v->as.b; return 0; }
    return fault(f, "ValueError", "expected a non-negative integer, got %s", value_kind(v));
}

int as_usize(const Value *v, size_t *out, Fault *f) {
    uint64_t u;
    if (as_u64(v, &u, f)) return -1;
    *out = (size_t)u;
    return 0;
}

int as_u32(const Value *v, uint32_t *out, Fault *f) {
    uint64_t u;
    if (as_u64(v, &u, f)) return -1;
    if (u > 0xFFFFFFFFu) return fault(f, "ValueError", "%llu does not fit 32 bits", (unsigned long long)u);
    *out = (uint32_t)u;
    return 0;
}

int as_f64(const Value *v, double *out, Fault *f) {
    switch (v->kind) {
        case V_FLOAT: *out = v->as.f; return 0;
        case V_INT: *out = (double)v->as.i; return 0;
        case V_UINT: *out = (double)v->as.u; return 0;
        case V_BOOL: *out = v->as.b ? 1.0 : 0.0; return 0;
        default: return fault(f, "ValueError", "expected a number, got %s", value_kind(v));
    }
}

int as_bool(const Value *v, int *out, Fault *f) {
    switch (v->kind) {
        case V_BOOL: *out = v->as.b; return 0;
        case V_INT: *out = v->as.i != 0; return 0;
        case V_UINT: *out = v->as.u != 0; return 0;
        default: return fault(f, "ValueError", "expected a boolean, got %s", value_kind(v));
    }
}

int as_str(const Value *v, const char **out, Fault *f) {
    if (v->kind == V_STR) { *out = v->as.str.s; return 0; }
    return fault(f, "ValueError", "expected a string, got %s", value_kind(v));
}

size_t list_len(const Value *v) {
    if (v->kind == V_LIST) return v->as.list.n;
    if (v->kind == V_PAIRS) return v->as.pairs.n;
    return 0;
}

int list_item(const Value *v, size_t i, Value *scratch, const Value **out, Fault *f) {
    if (v->kind == V_LIST) { *out = &v->as.list.items[i]; return 0; }
    (void)scratch;
    return fault(f, "ValueError", "expected a list, got %s", value_kind(v));
}

int as_pairs(const Value *v, uint32_t **out, size_t *n, Fault *f) {
    if (v->kind == V_PAIRS) {
        size_t count = v->as.pairs.n;
        uint32_t *ab = malloc((count ? count : 1) * 2 * sizeof *ab);
        if (!ab) return fault(f, "RuntimeError", "out of memory");
        if (count) memcpy(ab, v->as.pairs.ab, count * 2 * sizeof *ab);
        *out = ab;
        *n = count;
        return 0;
    }
    if (v->kind != V_LIST) return fault(f, "ValueError", "expected a list of edges, got %s", value_kind(v));
    size_t count = v->as.list.n;
    uint32_t *ab = malloc((count ? count : 1) * 2 * sizeof *ab);
    if (!ab) return fault(f, "RuntimeError", "out of memory");
    for (size_t i = 0; i < count; i++) {
        const Value *item = &v->as.list.items[i];
        if (item->kind == V_PAIRS) {
            if (item->as.pairs.n != 2) { free(ab); return fault(f, "ValueError", "an edge is a pair of nodes"); }
            free(ab);
            return fault(f, "ValueError", "expected an integer, got a list");
        }
        if (item->kind != V_LIST) {
            free(ab);
            return fault(f, "ValueError", "expected a list, got %s", value_kind(item));
        }
        if (item->as.list.n != 2) { free(ab); return fault(f, "ValueError", "an edge is a pair of nodes"); }
        if (as_u32(&item->as.list.items[0], &ab[2 * i], f) || as_u32(&item->as.list.items[1], &ab[2 * i + 1], f)) {
            free(ab);
            return -1;
        }
    }
    *out = ab;
    *n = count;
    return 0;
}

int as_words(const Value *v, uint32_t **out, size_t *n, Fault *f) {
    if (v->kind != V_LIST) return fault(f, "ValueError", "expected a list, got %s", value_kind(v));
    size_t count = v->as.list.n;
    uint32_t *w = malloc((count ? count : 1) * sizeof *w);
    if (!w) return fault(f, "RuntimeError", "out of memory");
    for (size_t i = 0; i < count; i++)
        if (as_u32(&v->as.list.items[i], &w[i], f)) { free(w); return -1; }
    *out = w;
    *n = count;
    return 0;
}

void out_init(Out *o) {
    o->s = malloc(4096);
    o->len = 0;
    o->cap = o->s ? 4096 : 0;
    o->depth = 0;
    o->first[0] = 1;
    if (o->s) o->s[0] = 0;
}

void out_free(Out *o) {
    free(o->s);
    o->s = NULL;
    o->len = o->cap = 0;
}

static void put(Out *o, const char *text, size_t n) {
    if (!o->s) return;
    if (o->len + n + 1 > o->cap) {
        size_t cap2 = o->cap * 2;
        while (cap2 < o->len + n + 1) cap2 *= 2;
        char *next = realloc(o->s, cap2);
        if (!next) { free(o->s); o->s = NULL; return; }
        o->s = next;
        o->cap = cap2;
    }
    memcpy(o->s + o->len, text, n);
    o->len += n;
    o->s[o->len] = 0;
}

void out_raw(Out *o, const char *text) { put(o, text, strlen(text)); }

static void before(Out *o) {
    if (o->depth > 0 && o->first[o->depth] != 2) {
        if (!o->first[o->depth]) put(o, ",", 1);
        o->first[o->depth] = 0;
    } else if (o->depth > 0) {
        o->first[o->depth] = 0;
    }
}

static void write_string(Out *o, const char *text) {
    put(o, "\"", 1);
    for (const unsigned char *c = (const unsigned char *)text; *c; c++) {
        switch (*c) {
            case '"': put(o, "\\\"", 2); break;
            case '\\': put(o, "\\\\", 2); break;
            case '\n': put(o, "\\n", 2); break;
            case '\r': put(o, "\\r", 2); break;
            case '\t': put(o, "\\t", 2); break;
            default:
                if (*c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof buf, "\\u%04x", *c);
                    put(o, buf, 6);
                } else {
                    put(o, (const char *)c, 1);
                }
        }
    }
    put(o, "\"", 1);
}

void out_key(Out *o, const char *key) {
    if (!o->first[o->depth]) put(o, ",", 1);
    write_string(o, key);
    put(o, ":", 1);
    o->first[o->depth] = 2;
}

static void out_open(Out *o, const char *c) {
    before(o);
    put(o, c, 1);
    o->depth++;
    o->first[o->depth] = 1;
}

static void close_(Out *o, const char *c) {
    put(o, c, 1);
    o->depth--;
    if (o->depth > 0 && o->first[o->depth] == 2) o->first[o->depth] = 0;
}

void out_begin_map(Out *o) { out_open(o, "{"); }
void out_end_map(Out *o) { close_(o, "}"); }
void out_begin_list(Out *o) { out_open(o, "["); }
void out_end_list(Out *o) { close_(o, "]"); }

static void after(Out *o) {
    if (o->depth > 0 && o->first[o->depth] == 2) o->first[o->depth] = 0;
}

void out_null(Out *o) { before(o); put(o, "null", 4); after(o); }
void out_bool(Out *o, int b) { before(o); out_raw(o, b ? "true" : "false"); after(o); }

void out_int(Out *o, int64_t v) {
    char buf[32];
    before(o);
    int n = snprintf(buf, sizeof buf, "%lld", (long long)v);
    put(o, buf, (size_t)n);
    after(o);
}

void out_uint(Out *o, uint64_t v) {
    char buf[32];
    before(o);
    int n = snprintf(buf, sizeof buf, "%llu", (unsigned long long)v);
    put(o, buf, (size_t)n);
    after(o);
}

void out_float(Out *o, double v) {
    before(o);
    if (isnan(v)) {
        put(o, "NaN", 3);
    } else if (isinf(v)) {
        out_raw(o, v > 0 ? "Infinity" : "-Infinity");
    } else {
        char buf[40];
        for (int precision = 1; precision <= 17; precision++) {
            snprintf(buf, sizeof buf, "%.*g", precision, v);
            if (strtod(buf, NULL) == v) break;
        }
        if (!strpbrk(buf, ".eE")) strcat(buf, ".0");
        out_raw(o, buf);
    }
    after(o);
}

void out_str(Out *o, const char *text) { before(o); write_string(o, text); after(o); }

void out_pairs(Out *o, const uint32_t *ab, size_t n) {
    char buf[32];
    before(o);
    put(o, "[", 1);
    for (size_t i = 0; i < n; i++) {
        int len = snprintf(buf, sizeof buf, i ? ",[%u,%u]" : "[%u,%u]", ab[2 * i], ab[2 * i + 1]);
        put(o, buf, (size_t)len);
    }
    put(o, "]", 1);
    after(o);
}

void out_words(Out *o, const uint32_t *w, size_t n) {
    char buf[16];
    before(o);
    put(o, "[", 1);
    for (size_t i = 0; i < n; i++) {
        int len = snprintf(buf, sizeof buf, i ? ",%u" : "%u", w[i]);
        put(o, buf, (size_t)len);
    }
    put(o, "]", 1);
    after(o);
}

void out_json(Out *o, const char *text, size_t n) {
    before(o);
    put(o, text, n);
    after(o);
}
