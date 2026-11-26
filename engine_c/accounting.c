#include "accounting.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *const KINDS[3] = {"add", "delete", "swap"};
static const char *const SCOPES[2] = {"local", "global"};
static const char *const SIGNS[3] = {"neg", "zero", "pos"};
static const char *const OUTCOMES[2] = {"accepted", "rejected"};
static const char *const PART_NAMES[6] = {"moves", "evaluations", "changes", "lists", "entries", "tests"};

static char bin_names[BINS][12];
static int bin_order[BINS];
static int names_ready;

static void key_name(int index, char *out, size_t size) {
    int outcome = index % 2, sign = (index / 2) % 3, scope = (index / 6) % 2, kind = index / 12;
    snprintf(out, size, "%s.%s.%s.%s", KINDS[kind], SCOPES[scope], SIGNS[sign], OUTCOMES[outcome]);
}

static int by_name(const void *a, const void *b) {
    return strcmp(bin_names[*(const int *)a], bin_names[*(const int *)b]);
}

static void ready(void) {
    if (names_ready) return;
    strcpy(bin_names[0], "0");
    for (int side = 0; side < 2; side++)
        for (int e = -DELTA_H_BIN_LIMIT; e <= DELTA_H_BIN_LIMIT; e++)
            snprintf(bin_names[1 + side * 81 + (e + DELTA_H_BIN_LIMIT)], 12, "%s2^%d", side ? "-" : "+", e);
    for (int i = 0; i < BINS; i++) bin_order[i] = i;
    qsort(bin_order, BINS, sizeof bin_order[0], by_name);
    names_ready = 1;
}

static int bin_of(double delta_h) {
    if (delta_h == 0.0) return 0;
    double magnitude = delta_h < 0 ? -delta_h : delta_h;
    uint64_t bits;
    memcpy(&bits, &magnitude, sizeof bits);
    int biased = (int)((bits >> 52) & 0x7ff);
    int exponent = biased == 0 ? -1074 : biased - 1022;
    if (exponent < -DELTA_H_BIN_LIMIT) exponent = -DELTA_H_BIN_LIMIT;
    if (exponent > DELTA_H_BIN_LIMIT) exponent = DELTA_H_BIN_LIMIT;
    return 1 + (delta_h > 0 ? 0 : 81) + (exponent + DELTA_H_BIN_LIMIT);
}

static int bin_named(const char *name) {
    ready();
    for (int i = 0; i < BINS; i++)
        if (strcmp(bin_names[i], name) == 0) return i;
    return -1;
}

static void block_free(Block *b) {
    for (size_t i = 0; i < b->extras_n; i++) free(b->extras[i].key);
    free(b->extras);
    memset(b, 0, sizeof *b);
}

void accounting_free(Accounting *acc) {
    block_free(&acc->whole);
    block_free(&acc->late);
}

static Extra *extra_of(Block *b, const char *key) {
    for (size_t i = 0; i < b->extras_n; i++)
        if (strcmp(b->extras[i].key, key) == 0) return &b->extras[i];
    Extra *next = realloc(b->extras, (b->extras_n + 1) * sizeof *next);
    if (!next) return NULL;
    b->extras = next;
    Extra *e = &b->extras[b->extras_n++];
    memset(e, 0, sizeof *e);
    e->key = strdup(key);
    return e->key ? e : NULL;
}

static int block_read(Block *b, const Value *d, Fault *f) {
    memset(b, 0, sizeof *b);
    if (value_is_null(d)) return 0;
    const Value *work = value_present(d, "work");
    if (work && as_u64(work, &b->work, f)) return -1;
    const Value *parts = value_present(d, "parts");
    if (parts) {
        for (int i = 0; i < 6; i++) {
            const Value *v = value_get(parts, PART_NAMES[i]);
            if (v && as_u64(v, &b->parts[i], f)) return -1;
        }
    }
    const Value *counts = value_get(d, "counts");
    if (counts) {
        char name[64];
        for (int i = 0; i < KEYS; i++) {
            key_name(i, name, sizeof name);
            const Value *v = value_get(counts, name);
            if (v && as_u64(v, &b->counts[i], f)) return -1;
        }
    }
    const Value *hist = value_get(d, "delta_h_log2");
    if (hist) {
        for (int side = 0; side < 2; side++) {
            const Value *bins = value_get(hist, side ? "accepted" : "proposed");
            if (!bins || bins->kind != V_MAP) continue;
            for (size_t i = 0; i < bins->as.map.n; i++) {
                uint64_t count;
                if (as_u64(&bins->as.map.vals[i], &count, f)) return -1;
                int at = bin_named(bins->as.map.keys[i]);
                if (at >= 0) {
                    if (side) { b->accepted[at] = count; b->has_accepted[at] = 1; }
                    else { b->proposed[at] = count; b->has_proposed[at] = 1; }
                } else {
                    Extra *e = extra_of(b, bins->as.map.keys[i]);
                    if (!e) return fault(f, "RuntimeError", "out of memory");
                    if (side) { e->accepted = count; e->has_accepted = 1; }
                    else { e->proposed = count; e->has_proposed = 1; }
                }
            }
        }
    }
    return 0;
}

int accounting_read(Accounting *acc, const Value *value, Fault *f) {
    memset(acc, 0, sizeof *acc);
    ready();
    if (value_is_null(value)) return 0;
    if (block_read(&acc->whole, value, f)) return -1;
    const Value *late = value_present(value, "late");
    if (late) {
        if (block_read(&acc->late, late, f)) return -1;
        const Value *from = value_present(late, "from_move");
        size_t at;
        Fault ignored = {0};
        if (from && as_usize(from, &at, &ignored) == 0) {
            acc->has_late_from = 1;
            acc->late_from = at;
        }
    }
    const Value *last = value_present(value, "last_decrease_move");
    size_t at;
    Fault ignored = {0};
    if (last && as_usize(last, &at, &ignored) == 0) {
        acc->has_last_decrease = 1;
        acc->last_decrease_move = at;
    }
    return 0;
}

static int by_key(const void *a, const void *b) {
    return strcmp((*(const Extra *const *)a)->key, (*(const Extra *const *)b)->key);
}

static void write_bins(const Block *b, Out *o, int accepted) {
    out_begin_map(o);
    const Extra **extras = malloc((b->extras_n + 1) * sizeof *extras);
    size_t extras_n = 0;
    for (size_t i = 0; i < b->extras_n; i++)
        if (accepted ? b->extras[i].has_accepted : b->extras[i].has_proposed) extras[extras_n++] = &b->extras[i];
    if (extras_n) qsort(extras, extras_n, sizeof *extras, by_key);
    size_t next = 0;
    for (int k = 0; k < BINS; k++) {
        int i = bin_order[k];
        if (!(accepted ? b->has_accepted[i] : b->has_proposed[i])) continue;
        while (next < extras_n && strcmp(extras[next]->key, bin_names[i]) < 0) {
            out_key(o, extras[next]->key);
            out_uint(o, accepted ? extras[next]->accepted : extras[next]->proposed);
            next++;
        }
        out_key(o, bin_names[i]);
        out_uint(o, accepted ? b->accepted[i] : b->proposed[i]);
    }
    for (; next < extras_n; next++) {
        out_key(o, extras[next]->key);
        out_uint(o, accepted ? extras[next]->accepted : extras[next]->proposed);
    }
    free(extras);
    out_end_map(o);
}

static void block_fill(const Block *b, Out *o) {
    char name[64];
    out_key(o, "counts");
    out_begin_map(o);
    for (int i = 0; i < KEYS; i++) {
        key_name(i, name, sizeof name);
        out_key(o, name);
        out_uint(o, b->counts[i]);
    }
    out_end_map(o);
    out_key(o, "delta_h_log2");
    out_begin_map(o);
    out_key(o, "proposed");
    write_bins(b, o, 0);
    out_key(o, "accepted");
    write_bins(b, o, 1);
    out_end_map(o);
    out_key(o, "work");
    out_uint(o, b->work);
    out_key(o, "parts");
    out_begin_map(o);
    for (int i = 0; i < 6; i++) {
        out_key(o, PART_NAMES[i]);
        out_uint(o, b->parts[i]);
    }
    out_end_map(o);
}

void accounting_write(const Accounting *acc, Out *o) {
    ready();
    out_begin_map(o);
    out_key(o, "contract");
    out_str(o, "move-accounting-1");
    block_fill(&acc->whole, o);
    out_key(o, "late");
    out_begin_map(o);
    out_key(o, "from_move");
    if (acc->has_late_from) out_uint(o, acc->late_from); else out_null(o);
    block_fill(&acc->late, o);
    out_end_map(o);
    out_key(o, "last_decrease_move");
    if (acc->has_last_decrease) out_uint(o, acc->last_decrease_move); else out_null(o);
    out_end_map(o);
}

void accounting_start_segment(Accounting *acc, size_t start_move, size_t segment_start, size_t segment_moves) {
    size_t late_from = segment_start + (3 * segment_moves) / 4;
    if (start_move == segment_start || !acc->has_late_from || acc->late_from != late_from) {
        block_free(&acc->late);
        acc->has_late_from = 1;
        acc->late_from = late_from;
    }
}

static void block_add(Block *b, int index, int bin, int took) {
    b->counts[index] += 1;
    b->proposed[bin] += 1;
    b->has_proposed[bin] = 1;
    if (took) {
        b->accepted[bin] += 1;
        b->has_accepted[bin] = 1;
    }
}

void accounting_tally(Accounting *acc, size_t mv, int kind, int scope, double delta_h, int took) {
    int sign = delta_h < 0.0 ? 0 : (delta_h > 0.0 ? 2 : 1);
    int outcome = took ? 0 : 1;
    int index = ((kind * 2 + scope) * 3 + sign) * 2 + outcome;
    int bin = bin_of(delta_h);
    block_add(&acc->whole, index, bin, took);
    if (took && delta_h < 0.0) {
        acc->has_last_decrease = 1;
        acc->last_decrease_move = mv;
    }
    if (acc->has_late_from && mv >= acc->late_from) block_add(&acc->late, index, bin, took);
}

void block_count(Block *b, const uint64_t from[6], const uint64_t now[6], uint64_t moves) {
    b->work += now[0] - from[0];
    b->parts[0] += moves;
    for (int i = 1; i < 6; i++) b->parts[i] += now[i] - from[i];
}
