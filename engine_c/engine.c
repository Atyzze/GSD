#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#include "accounting.h"
#include "graph.h"
#include "mt.h"
#include "value.h"

#define STOP_CHECK_SECONDS 4.0
#define WORK_CHECK_MOVES 64
#define CLOCK_STRIDE_START_MOVES 1
#define CLOCK_STRIDE_MAX_MOVES (1u << 22)
#define STRUCTURE_POINT_STRIDE 20
#define REBUILD_CLOCK_EDGES 64
#define LOCAL_WALK_DELETE 0.2
#define LOCAL_WALK_SWAP_BELOW 0.6
#define LOCAL_WALK_ADD 0.4
#define EXACT_ZERO_SHARE 1e-12

#ifndef GSD_ENGINE_C_VERSION
#define GSD_ENGINE_C_VERSION "0.0.0"
#endif

typedef __int128 wide;

typedef struct {
    Op op;
    double coeff;
    int64_t k;
    char *scale;
    int has_params_k;
    int64_t params_k;
} Term;

typedef struct {
    int64_t op;
    double coeff;
    int64_t k;
} AsmTerm;

typedef struct {
    Term *terms;
    size_t n;
    int has_node_terms;
    AsmTerm *asm_terms;
} Model;

#ifdef GSD_ASM
int gsd_asm_accept(Mt *rng, double beta, double delta_h, double log_ratio);
double gsd_asm_energy(const AsmTerm *terms, size_t n, int64_t du, int64_t dv, int adding, double *ledger);

static int covered(Op op) {
    return op == OP_EDGE_COUNT || op == OP_DEGREE_SQUARE_SUM || op == OP_WEDGE_COUNT || op == OP_DEGREE_ANCHOR
        || op == OP_DEGREE_ANCHOR_ABS;
}
#endif

typedef struct {
    uint64_t add, del, swap;
} Counter;

static double now_seconds(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static int exists(const char *path) {
    struct stat st;
    return path && stat(path, &st) == 0;
}

static size_t next_clock_stride(size_t stride, double elapsed, double tick) {
    if (elapsed < 0.5 * tick) {
        size_t doubled = (stride > 1 ? stride : 1) * 2;
        return doubled < CLOCK_STRIDE_MAX_MOVES ? doubled : CLOCK_STRIDE_MAX_MOVES;
    }
    if (elapsed > tick) {
        size_t s = (size_t)((double)stride * 0.5 * tick / elapsed);
        return s > 1 ? s : 1;
    }
    return stride > 1 ? stride : 1;
}

static void model_free(Model *m) {
    for (size_t i = 0; i < m->n; i++) free(m->terms[i].scale);
    free(m->terms);
    free(m->asm_terms);
    memset(m, 0, sizeof *m);
}

static int field(const Value *request, const char *key, const Value **out, Fault *f) {
    *out = value_present(request, key);
    if (!*out) return fault(f, "KeyError", "the request has no '%s'", key);
    return 0;
}

static int parse_terms(const Value *value, Model *m, Fault *f) {
    memset(m, 0, sizeof *m);
    if (value->kind != V_LIST) return fault(f, "ValueError", "expected a list, got %s", value_kind(value));
    m->terms = calloc(value->as.list.n ? value->as.list.n : 1, sizeof *m->terms);
    if (!m->terms) return fault(f, "RuntimeError", "out of memory");
    for (size_t i = 0; i < value->as.list.n; i++) {
        const Value *item = &value->as.list.items[i];
        const Value *v = value_present(item, "op");
        const char *name;
        if (!v) return fault(f, "KeyError", "term has no 'op'");
        if (as_str(v, &name, f)) return -1;
        Term *t = &m->terms[m->n];
        t->op = op_parse(name);
        if (t->op == OP_UNKNOWN) return fault(f, "ValueError", "unknown op %s", name);
#ifdef GSD_ASM
        if (!covered(t->op))
            return fault(f, "OutsideCoverage", "the assembly engine covers edge_count, degree_square_sum, wedge_count, "
                         "degree_anchor and degree_anchor_abs, not %s", name);
#endif
        v = value_present(item, "coeff");
        if (!v) return fault(f, "KeyError", "term %s has no 'coeff'", name);
        if (as_f64(v, &t->coeff, f)) return -1;
        v = value_present(item, "k");
        t->k = 0;
        if (v && as_i64(v, &t->k, f)) return -1;
        v = value_present(item, "scale");
        const char *scale = "one";
        if (v && as_str(v, &scale, f)) return -1;
        t->scale = strdup(scale);
        if (!t->scale) return fault(f, "RuntimeError", "out of memory");
        v = value_present(item, "params_k");
        if (v) {
            if (as_i64(v, &t->params_k, f)) return -1;
            t->has_params_k = 1;
        }
        if (op_is_node(t->op)) m->has_node_terms = 1;
        m->n++;
    }
    m->asm_terms = calloc(m->n ? m->n : 1, sizeof *m->asm_terms);
    if (!m->asm_terms) return fault(f, "RuntimeError", "out of memory");
    for (size_t i = 0; i < m->n; i++) {
        m->asm_terms[i].op = m->terms[i].op;
        m->asm_terms[i].coeff = m->terms[i].coeff;
        m->asm_terms[i].k = m->terms[i].k;
    }
    return 0;
}

static void required_of(const Model *m, int required[LEDGERS]) {
    for (int i = 0; i < LEDGERS; i++) required[i] = 0;
    for (size_t i = 0; i < m->n; i++) {
        if (op_is_node(m->terms[i].op)) continue;
        int at = op_ledger(m->terms[i].op);
        if (at >= 0) required[at] = 1;
    }
}

static wide node_functional(Op op, int64_t d0, int64_t k0) {
    wide d = d0, k = k0;
    switch (op) {
        case OP_DEGREE_ANCHOR: return (d - k) * (d - k);
        case OP_DEGREE_ANCHOR_ABS: return d - k < 0 ? k - d : d - k;
        case OP_DEGREE_CUBE_SUM: return d * d * d;
        case OP_DEGREE_FOURTH_SUM: return d * d * d * d;
        default: return 0;
    }
}

static double exact_zero(double change, double magnitude) {
    return fabs(change) <= EXACT_ZERO_SHARE * magnitude ? 0.0 : change;
}

static int apply_edge(const Model *m, Graph *g, uint32_t u, uint32_t v, int adding, Deltas *deltas, double *dh,
                      Fault *f) {
#ifdef GSD_ASM
    graph_evaluated(g);
    for (int i = 3; i < LEDGERS; i++) deltas->ledger[i] = 0.0;
    *dh = gsd_asm_energy(m->asm_terms, m->n, (int64_t)graph_degree(g, u) - (adding ? 0 : 1),
                         (int64_t)graph_degree(g, v) - (adding ? 0 : 1), adding, deltas->ledger);
    (void)f;
    return 0;
#endif
    if (graph_op_deltas(g, u, v, adding, deltas)) return fault(f, "RuntimeError", "out of memory");
    double node_energy = 0.0, node_magnitude = 0.0;
    if (m->has_node_terms) {
        double sign = adding ? 1.0 : -1.0;
        int64_t du = (int64_t)graph_degree(g, u) - (adding ? 0 : 1);
        int64_t dv = (int64_t)graph_degree(g, v) - (adding ? 0 : 1);
        for (size_t i = 0; i < m->n; i++) {
            const Term *t = &m->terms[i];
            if (!op_is_node(t->op)) continue;
            wide inner = node_functional(t->op, du + 1, t->k) - node_functional(t->op, du, t->k)
                + node_functional(t->op, dv + 1, t->k) - node_functional(t->op, dv, t->k);
            double part = t->coeff * sign * (double)inner;
            node_energy += part;
            node_magnitude += fabs(part);
        }
    }
    double energy = node_energy, magnitude = node_magnitude;
    for (size_t i = 0; i < m->n; i++) {
        const Term *t = &m->terms[i];
        if (op_is_node(t->op)) continue;
        double part = t->coeff * deltas->ledger[op_ledger(t->op)];
        energy += part;
        magnitude += fabs(part);
    }
    *dh = exact_zero(energy, magnitude);
    return 0;
}

static double swap_change(const Model *m, const double moved[LEDGERS]) {
    double change = 0.0, magnitude = 0.0;
    for (size_t i = 0; i < m->n; i++) {
        const Term *t = &m->terms[i];
        if (op_is_node(t->op)) continue;
        double part = t->coeff * moved[op_ledger(t->op)];
        change += part;
        magnitude += fabs(part);
    }
    return exact_zero(change, magnitude);
}

static int counter_read(Counter *c, const Value *value, Fault *f) {
    memset(c, 0, sizeof *c);
    if (value_is_null(value)) return 0;
    const Value *v;
    if ((v = value_present(value, "add")) && as_u64(v, &c->add, f)) return -1;
    if ((v = value_present(value, "delete")) && as_u64(v, &c->del, f)) return -1;
    if ((v = value_present(value, "swap")) && as_u64(v, &c->swap, f)) return -1;
    return 0;
}

static void counter_write(const Counter *c, Out *o) {
    out_begin_map(o);
    out_key(o, "add");
    out_uint(o, c->add);
    out_key(o, "delete");
    out_uint(o, c->del);
    out_key(o, "swap");
    out_uint(o, c->swap);
    out_end_map(o);
}

static int compare_keys(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

static int check_edge_list(size_t n, const uint32_t *ab, size_t count, Fault *f) {
    size_t bad = count;
    for (size_t i = 0; i < count; i++) {
        uint32_t u = ab[2 * i], v = ab[2 * i + 1];
        if (u >= n || v >= n || u == v) { bad = i; break; }
    }
    if (bad) {
        uint64_t *keys = malloc(bad * sizeof *keys);
        if (!keys) return fault(f, "RuntimeError", "out of memory");
        for (size_t i = 0; i < bad; i++) keys[i] = edge_key(ab[2 * i], ab[2 * i + 1]);
        qsort(keys, bad, sizeof *keys, compare_keys);
        int twice = 0;
        for (size_t i = 1; i < bad; i++)
            if (keys[i] == keys[i - 1]) { twice = 1; break; }
        free(keys);
        if (twice) {
            EdgeMap seen;
            if (map_init(&seen, 0)) return fault(f, "RuntimeError", "out of memory");
            for (size_t i = 0; i < bad; i++) {
                EdgeKey e = edge_key(ab[2 * i], ab[2 * i + 1]);
                if (map_find(&seen, e)) {
                    map_free(&seen);
                    return fault(f, "ValueError", "checkpoint edge (%u, %u) appears twice", ab[2 * i], ab[2 * i + 1]);
                }
                if (!map_entry(&seen, e)) { map_free(&seen); return fault(f, "RuntimeError", "out of memory"); }
            }
            map_free(&seen);
        }
    }
    if (bad < count) {
        uint32_t u = ab[2 * bad], v = ab[2 * bad + 1];
        if (u >= n || v >= n)
            return fault(f, "ValueError", "checkpoint edge (%u, %u) has an endpoint outside 0..%zu", u, v, n);
        return fault(f, "ValueError", "checkpoint edge (%u, %u) is a loop", u, v);
    }
    return 0;
}

typedef struct {
    const char *path;
    double tick, last;
} RebuildClock;

static int interrupted(RebuildClock *c, size_t index) {
    if (index == 0 || index % REBUILD_CLOCK_EDGES != 0) return 0;
    double now = now_seconds();
    if (now - c->last >= 0.5 * c->tick) {
        c->last = now;
        if (exists(c->path)) return 1;
    }
    return 0;
}

static void write_adj(const Graph *g, Out *o) {
    out_begin_list(o);
    for (size_t i = 0; i < g->n; i++) out_words(o, g->adj[i].nb, g->adj[i].len);
    out_end_list(o);
}

static void write_ledgers(const Graph *g, Out *o) {
    out_begin_map(o);
    for (int i = 0; i < LEDGERS; i++) {
        out_key(o, LEDGER_NAMES[i]);
        out_float(o, g->ledgers[i]);
    }
    out_end_map(o);
}

static void write_summary(const Graph *g, Out *o) {
    double connected, cycles, core;
    size_t components;
    graph_structural_summary(g, &connected, &components, &cycles, &core);
    out_begin_map(o);
    out_key(o, "connected_fraction");
    out_float(o, connected);
    out_key(o, "component_count");
    out_uint(o, components);
    out_key(o, "largest_component_cycle_rank_density");
    out_float(o, cycles);
    out_key(o, "two_core_fraction");
    out_float(o, core);
    out_end_map(o);
}

static int optional_usize(const Value *r, const char *key, size_t *out, int *has, Fault *f) {
    const Value *v = value_present(r, key);
    *has = v != NULL;
    return v ? as_usize(v, out, f) : 0;
}

static int optional_u64(const Value *r, const char *key, uint64_t *out, uint64_t fallback, Fault *f) {
    const Value *v = value_present(r, key);
    *out = fallback;
    return v ? as_u64(v, out, f) : 0;
}

static int optional_f64(const Value *r, const char *key, double *out, double fallback, int *has, Fault *f) {
    const Value *v = value_present(r, key);
    *out = fallback;
    if (has) *has = v != NULL;
    return v ? as_f64(v, out, f) : 0;
}

static int optional_bool(const Value *r, const char *key, int *out, int fallback, Fault *f) {
    const Value *v = value_present(r, key);
    *out = fallback;
    return v ? as_bool(v, out, f) : 0;
}

static int optional_str(const Value *r, const char *key, const char **out, Fault *f) {
    const Value *v = value_present(r, key);
    *out = NULL;
    return v ? as_str(v, out, f) : 0;
}

static int mt_from(Mt *rng, const uint32_t *words, size_t n_words, size_t index, Fault *f) {
    if (n_words < MT_N) return fault(f, "ValueError", "MT19937 state needs %d words, got %zu", MT_N, n_words);
    if (index > MT_N) return fault(f, "ValueError", "MT19937 state index %zu is past the %d-word block", index, MT_N);
    memcpy(rng->mt, words, MT_N * sizeof *words);
    rng->mti = index;
    return 0;
}

static int rebuild_from(const Model *m, Graph *g, const uint32_t *ab, size_t count, RebuildClock *clock,
                        size_t *stopped_at, Fault *f) {
    *stopped_at = count;
    for (size_t i = 0; i < count; i++) {
        if (clock && interrupted(clock, i)) { *stopped_at = i; return 0; }
        Deltas d;
        double dh;
        if (apply_edge(m, g, ab[2 * i], ab[2 * i + 1], 1, &d, &dh, f)) return -1;
        if (graph_apply(g, ab[2 * i], ab[2 * i + 1], 1, &d)) return fault(f, "RuntimeError", "out of memory");
    }
    return 0;
}

static int sorted_neighbours(Graph *g, uint32_t w, int has_without, uint32_t wa, uint32_t wb, uint32_t **out,
                             size_t *count) {
    const NodeList *l = &g->adj[w];
    graph_read_lists(g, 1, l->len);
    uint32_t *found = malloc((l->len ? l->len : 1) * sizeof *found);
    if (!found) return -1;
    memcpy(found, l->nb, l->len * sizeof *found);
    size_t n = l->len;
    for (size_t i = 1; i < n; i++) {
        uint32_t x = found[i];
        size_t j = i;
        while (j > 0 && found[j - 1] > x) { found[j] = found[j - 1]; j--; }
        found[j] = x;
    }
    if (has_without) {
        int has_other = 0;
        uint32_t other = 0;
        if (w == wa) { other = wb; has_other = 1; }
        else if (w == wb) { other = wa; has_other = 1; }
        if (has_other) {
            for (size_t i = 0; i < n; i++) {
                if (found[i] == other) {
                    memmove(&found[i], &found[i + 1], (n - i - 1) * sizeof *found);
                    n--;
                    break;
                }
            }
        }
    }
    *out = found;
    *count = n;
    return 0;
}

static int has(const uint32_t *list, size_t n, uint32_t x) {
    for (size_t i = 0; i < n; i++)
        if (list[i] == x) return 1;
    return 0;
}

static int walk_ends(Graph *g, uint32_t u, uint32_t x, int steps, int hw, uint32_t wa, uint32_t wb, double *total) {
    uint32_t *first;
    size_t du;
    *total = 0.0;
    if (sorted_neighbours(g, u, hw, wa, wb, &first, &du)) return -1;
    for (size_t i = 0; i < du; i++) {
        uint32_t *second;
        size_t db;
        if (sorted_neighbours(g, first[i], hw, wa, wb, &second, &db)) { free(first); return -1; }
        if (steps == 2) {
            graph_scan(g, db);
            if (has(second, db, x)) *total += 1.0 / (double)(du * db);
            free(second);
            continue;
        }
        for (size_t j = 0; j < db; j++) {
            uint32_t *third;
            size_t dc;
            if (sorted_neighbours(g, second[j], hw, wa, wb, &third, &dc)) { free(second); free(first); return -1; }
            graph_scan(g, dc);
            if (has(third, dc, x)) *total += 1.0 / (double)(du * db * dc);
            free(third);
        }
        free(second);
    }
    free(first);
    return 0;
}

static int walk_add_chance(Graph *g, uint32_t u, uint32_t x, size_t n, int hw, uint32_t wa, uint32_t wb,
                           double *out) {
    double a, b, c, d;
    if (walk_ends(g, u, x, 2, hw, wa, wb, &a) || walk_ends(g, x, u, 2, hw, wa, wb, &b)
        || walk_ends(g, u, x, 3, hw, wa, wb, &c) || walk_ends(g, x, u, 3, hw, wa, wb, &d))
        return -1;
    double ends = (a + b) + (c + d);
    *out = LOCAL_WALK_ADD * ends / (double)(2 * n);
    return 0;
}

static double delete_chance(size_t du, size_t dv, size_t n) {
    return LOCAL_WALK_DELETE * (1.0 / (double)du + 1.0 / (double)dv) / (double)n;
}

typedef struct {
    const Model *model;
    Graph *g;
    Mt *rng;
    size_t n;
    int zero_temperature;
    double *energy;
    int *energy_int;
    size_t *peak;
    Counter *proposed, *accepted;
    Accounting *acc;
} Run;

static int local_toggle(Run *r, uint32_t u, uint32_t v, int adding, double beta, size_t mv, Fault *f) {
    if (adding) r->proposed->add++; else r->proposed->del++;
    Deltas d;
    double dh;
    if (apply_edge(r->model, r->g, u, v, adding, &d, &dh, f)) return -1;
    if (!isfinite(dh))
        return fault(f, "FloatingPointError", "non-finite energy delta at move %zu; refusing to sample", mv);
    size_t du = graph_degree(r->g, u), dv = graph_degree(r->g, v);
    double forward, reverse;
    if (adding) {
        if (walk_add_chance(r->g, u, v, r->n, 0, 0, 0, &forward)) return fault(f, "RuntimeError", "out of memory");
        reverse = delete_chance(du + 1, dv + 1, r->n);
    } else {
        forward = delete_chance(du, dv, r->n);
        if (walk_add_chance(r->g, u, v, r->n, 1, u, v, &reverse)) return fault(f, "RuntimeError", "out of memory");
    }
    int took;
    if (reverse <= 0.0 || forward <= 0.0)
        took = 0;
    else if (r->zero_temperature)
        took = dh <= 0.0;
    else
#ifdef GSD_ASM
        took = gsd_asm_accept(r->rng, beta, dh, log(reverse / forward));
#else
        took = log(mt_random(r->rng) + 1e-300) < -beta * dh + log(reverse / forward);
#endif
    if (took) {
        if (graph_apply(r->g, u, v, adding, &d)) return fault(f, "RuntimeError", "out of memory");
        *r->energy += dh;
        *r->energy_int = 0;
        if (r->g->edge_count > *r->peak) *r->peak = r->g->edge_count;
        if (adding) r->accepted->add++; else r->accepted->del++;
    }
    accounting_tally(r->acc, mv, adding ? KIND_ADD : KIND_DELETE, SCOPE_LOCAL, dh, took);
    return 0;
}

typedef struct {
    int has_beta_cooling;
    double start;
    size_t moves;
    double beta;
    int zero_temperature;
} Acceptance;

static double beta_at(const Acceptance *a, size_t mv) {
    if (a->has_beta_cooling && mv < a->moves)
        return a->start + (a->beta - a->start) * ((double)mv / (double)a->moves);
    return a->beta;
}

static int accept(const Acceptance *a, Mt *rng, double delta_h, double log_ratio, size_t mv) {
    if (a->zero_temperature) return delta_h <= 0.0;
#ifdef GSD_ASM
    return gsd_asm_accept(rng, beta_at(a, mv), delta_h, log_ratio);
#else
    return log(mt_random(rng) + 1e-300) < -beta_at(a, mv) * delta_h + log_ratio;
#endif
}

static int run_swap(Run *r, const Acceptance *a, const EdgeKey e[4], size_t mv, int scope, Fault *f) {
    r->proposed->swap++;
    double old_energy = *r->energy;
    int old_int = *r->energy_int;
    *r->energy_int = 0;
    double moved[LEDGERS] = {0};
    const int forward[4] = {0, 0, 1, 1};
    for (int i = 0; i < 4; i++) {
        Deltas d;
        double dh;
        if (apply_edge(r->model, r->g, key_a(e[i]), key_b(e[i]), forward[i], &d, &dh, f)) return -1;
        if (!isfinite(dh)) return fault(f, "FloatingPointError", "non-finite energy delta during edge swap");
        if (graph_apply(r->g, key_a(e[i]), key_b(e[i]), forward[i], &d)) return fault(f, "RuntimeError", "out of memory");
        for (int k = 0; k < LEDGERS; k++) moved[k] += d.ledger[k];
    }
    double delta_h = swap_change(r->model, moved);
    *r->energy = old_energy + delta_h;
    int took = accept(a, r->rng, delta_h, 0.0, mv);
    if (took) {
        r->accepted->swap++;
    } else {
        const int back[4] = {3, 2, 1, 0};
        const int adding[4] = {0, 0, 1, 1};
        for (int i = 0; i < 4; i++) {
            EdgeKey x = e[back[i]];
            Deltas d;
            double dh;
            if (apply_edge(r->model, r->g, key_a(x), key_b(x), adding[i], &d, &dh, f)) return -1;
            if (!isfinite(dh)) return fault(f, "FloatingPointError", "non-finite energy delta during edge swap");
            if (graph_apply(r->g, key_a(x), key_b(x), adding[i], &d)) return fault(f, "RuntimeError", "out of memory");
            *r->energy += dh;
        }
        *r->energy = old_energy;
        *r->energy_int = old_int;
    }
    accounting_tally(r->acc, mv, KIND_SWAP, scope, delta_h, took);
    return 0;
}

static int run_toggle(Run *r, const Acceptance *a, uint32_t u, uint32_t v, int adding, double log_ratio, size_t mv,
                      int scope, Fault *f) {
    Deltas d;
    double dh;
    if (apply_edge(r->model, r->g, u, v, adding, &d, &dh, f)) return -1;
    if (!isfinite(dh))
        return fault(f, "FloatingPointError", "non-finite energy delta at move %zu; refusing to sample", mv);
    int took = accept(a, r->rng, dh, log_ratio, mv);
    if (took) {
        if (graph_apply(r->g, u, v, adding, &d)) return fault(f, "RuntimeError", "out of memory");
        *r->energy += dh;
        *r->energy_int = 0;
        if (r->g->edge_count > *r->peak) *r->peak = r->g->edge_count;
        if (adding) r->accepted->add++; else r->accepted->del++;
    }
    accounting_tally(r->acc, mv, adding ? KIND_ADD : KIND_DELETE, scope, dh, took);
    return 0;
}

static void record_point(const Model *m, const Graph *g, double energy, size_t mv, size_t n, const Counter *att,
                         const Counter *pro, const Counter *acc, Out *o) {
    wide degree_sum = 0, sq = 0, cube = 0, fourth = 0, wedge = 0;
    size_t max_degree = 0, isolated = 0;
    for (size_t i = 0; i < g->n; i++) {
        wide d = g->adj[i].len;
        degree_sum += d;
        sq += d * d;
        cube += d * d * d;
        fourth += (d * d) * (d * d);
        wedge += d * (d - 1) / 2;
        if (g->adj[i].len > max_degree) max_degree = g->adj[i].len;
        if (g->adj[i].len == 0) isolated++;
    }
    double nf = (double)(n > 1 ? n : 1);
    double degree_sum_f = (double)degree_sum, degree_square_sum = (double)sq, degree_cube_sum = (double)cube;
    double degree_fourth_sum = (double)fourth;
    double mean_degree = degree_sum_f / nf;
    double variance = degree_square_sum / nf - mean_degree * mean_degree;
    if (!(variance > 0.0)) variance = variance > 0.0 ? variance : 0.0;
    out_begin_map(o);
    out_key(o, "move");
    out_uint(o, mv);
    out_key(o, "energy");
    out_float(o, energy);
    out_key(o, "edges");
    out_uint(o, g->edge_count);
    out_key(o, "mean_degree");
    out_float(o, mean_degree);
    out_key(o, "max_degree");
    out_uint(o, max_degree);
    out_key(o, "isolated_fraction");
    out_float(o, (double)isolated / nf);
    out_key(o, "degree_variance");
    out_float(o, variance);
    out_key(o, "degree_second_moment");
    out_float(o, degree_square_sum / nf);
    out_key(o, "degree_third_moment");
    out_float(o, degree_cube_sum / nf);
    out_key(o, "degree_fourth_moment");
    out_float(o, degree_fourth_sum / nf);
    out_key(o, "active_term_components");
    out_begin_list(o);
    double component_sum = 0.0;
    for (size_t i = 0; i < m->n; i++) {
        const Term *t = &m->terms[i];
        double observable;
        switch (t->op) {
            case OP_EDGE_COUNT: observable = (double)g->edge_count; break;
            case OP_DEGREE_SQUARE_SUM: observable = degree_square_sum; break;
            case OP_WEDGE_COUNT: observable = (double)wedge; break;
            case OP_DEGREE_CUBE_SUM: observable = degree_cube_sum; break;
            case OP_DEGREE_FOURTH_SUM: observable = degree_fourth_sum; break;
            case OP_DEGREE_ANCHOR:
            case OP_DEGREE_ANCHOR_ABS: {
                wide k = t->has_params_k ? t->params_k : 0, s = 0;
                for (size_t j = 0; j < g->n; j++) {
                    wide d = g->adj[j].len;
                    s += t->op == OP_DEGREE_ANCHOR ? (d - k) * (d - k) : (d - k < 0 ? k - d : d - k);
                }
                observable = (double)s;
                break;
            }
            default: observable = g->ledgers[op_ledger(t->op)];
        }
        double component = t->coeff * observable;
        component_sum += component;
        out_begin_map(o);
        out_key(o, "term_index");
        out_uint(o, i);
        out_key(o, "op");
        out_str(o, op_name(t->op));
        out_key(o, "params");
        out_begin_map(o);
        if (t->has_params_k) {
            out_key(o, "k");
            out_int(o, t->params_k);
        }
        out_end_map(o);
        out_key(o, "scale");
        out_str(o, t->scale);
        out_key(o, "coefficient");
        out_float(o, t->coeff);
        out_key(o, "observable");
        out_float(o, observable);
        out_key(o, "energy_component");
        out_float(o, component);
        out_end_map(o);
    }
    out_end_list(o);
    out_key(o, "term_energy_sum");
    out_float(o, component_sum);
    out_key(o, "term_energy_residual");
    out_float(o, energy - component_sum);
    out_key(o, "attempted_add");
    out_uint(o, att->add);
    out_key(o, "attempted_delete");
    out_uint(o, att->del);
    out_key(o, "attempted_swap");
    out_uint(o, att->swap);
    out_key(o, "proposed_add");
    out_uint(o, pro->add);
    out_key(o, "proposed_delete");
    out_uint(o, pro->del);
    out_key(o, "proposed_swap");
    out_uint(o, pro->swap);
    out_key(o, "accepted_add");
    out_uint(o, acc->add);
    out_key(o, "accepted_delete");
    out_uint(o, acc->del);
    out_key(o, "accepted_swap");
    out_uint(o, acc->swap);
}

static int sorted_keys(const EdgeMap *m, uint32_t **out, size_t *count) {
    uint64_t *keys = malloc((m->n ? m->n : 1) * sizeof *keys);
    uint32_t *ab = malloc((m->n ? m->n : 1) * 2 * sizeof *ab);
    if (!keys || !ab) { free(keys); free(ab); return -1; }
    size_t n = 0;
    for (size_t i = 0; i < m->cap; i++)
        if (m->keys[i] != UINT64_MAX) keys[n++] = m->keys[i];
    qsort(keys, n, sizeof *keys, compare_keys);
    for (size_t i = 0; i < n; i++) {
        ab[2 * i] = key_a(keys[i]);
        ab[2 * i + 1] = key_b(keys[i]);
    }
    free(keys);
    *out = ab;
    *count = n;
    return 0;
}

static int run_chain(const Value *r, Out *o, Fault *f) {
    const Value *v;
    size_t n, total_moves, start_move, points, mt_index, late_from_move = 0;
    int has_late_from_move;
    double beta, p_add, p_del, p_swap, proposal_locality, energy0;
    uint32_t *words = NULL, *ab = NULL, *late_added = NULL, *late_removed = NULL;
    size_t n_words = 0, n_edges = 0, n_added = 0, n_removed = 0, late_change_from = 0;
    int has_late_change = 0, status = -1;
    Model model = {0};
    Graph g;
    int graph_ready = 0;
    Accounting acc;
    int acc_ready = 0;
    Out traj;
    out_init(&traj);
    uint64_t *weights = NULL;
    size_t n_weights = 0;

    if (field(r, "n", &v, f) || as_usize(v, &n, f)) goto done;
    if (field(r, "beta", &v, f) || as_f64(v, &beta, f)) goto done;
    if (field(r, "p_add", &v, f) || as_f64(v, &p_add, f)) goto done;
    if (field(r, "p_del", &v, f) || as_f64(v, &p_del, f)) goto done;
    if (field(r, "p_swap", &v, f) || as_f64(v, &p_swap, f)) goto done;
    if (field(r, "proposal_locality", &v, f) || as_f64(v, &proposal_locality, f)) goto done;
    if (field(r, "total_moves", &v, f) || as_usize(v, &total_moves, f)) goto done;
    if (field(r, "start_move", &v, f) || as_usize(v, &start_move, f)) goto done;
    if (field(r, "points", &v, f) || as_usize(v, &points, f)) goto done;
    if (optional_usize(r, "late_from_move", &late_from_move, &has_late_from_move, f)) goto done;
    if (field(r, "mt_words", &v, f) || as_words(v, &words, &n_words, f)) goto done;
    if (field(r, "mt_index", &v, f) || as_usize(v, &mt_index, f)) goto done;
    if (field(r, "edge_list", &v, f) || as_pairs(v, &ab, &n_edges, f)) goto done;
    if (field(r, "energy", &v, f) || as_f64(v, &energy0, f)) goto done;
    if ((v = value_present(r, "late_change"))) {
        if (v->kind != V_LIST) { fault(f, "ValueError", "expected a list, got %s", value_kind(v)); goto done; }
        if (v->as.list.n != 3) {
            fault(f, "ValueError", "late_change is its first move, the edges added and the edges removed");
            goto done;
        }
        if (as_usize(&v->as.list.items[0], &late_change_from, f)) goto done;
        if (as_pairs(&v->as.list.items[1], &late_added, &n_added, f)) goto done;
        if (as_pairs(&v->as.list.items[2], &late_removed, &n_removed, f)) goto done;
        has_late_change = 1;
    }
    size_t trajectory_len, peak, cap_edges = 0, segment_start;
    int has_x, has_cap, has_segment, energy_int, zero_temperature, local_walk, has_cooling_from, has_cooling_moves;
    uint64_t hits, fallbacks, work_room = 0;
    double mean_degree_cap, stop_check_seconds, locality, cooling_from = 0.0;
    size_t cooling_moves = 0;
    int has_mean_degree_cap, has_work_room;
    const char *stop_file, *rebuild_stop_file;
    if (optional_usize(r, "trajectory_len", &trajectory_len, &has_x, f)) goto done;
    if (!has_x) trajectory_len = 0;
    if (optional_usize(r, "peak_edge_count", &peak, &has_x, f)) goto done;
    if (!has_x) peak = 0;
    if (optional_u64(r, "non_edge_fast_path_hits", &hits, 0, f)) goto done;
    if (optional_u64(r, "non_edge_exact_fallbacks", &fallbacks, 0, f)) goto done;
    if (optional_usize(r, "cap_edges", &cap_edges, &has_cap, f)) goto done;
    if (optional_f64(r, "mean_degree_cap", &mean_degree_cap, 0.0, &has_mean_degree_cap, f)) goto done;
    if (optional_bool(r, "energy_is_int", &energy_int, 0, f)) goto done;
    if (optional_usize(r, "segment_start", &segment_start, &has_segment, f)) goto done;
    if (optional_str(r, "stop_file", &stop_file, f)) goto done;
    if (optional_str(r, "rebuild_stop_file", &rebuild_stop_file, f)) goto done;
    if (optional_f64(r, "stop_check_seconds", &stop_check_seconds, STOP_CHECK_SECONDS, NULL, f)) goto done;
    if (optional_f64(r, "locality", &locality, 0.0, NULL, f)) goto done;
    if (optional_bool(r, "zero_temperature", &zero_temperature, 0, f)) goto done;
    if (optional_f64(r, "cooling_from_beta", &cooling_from, 0.0, &has_cooling_from, f)) goto done;
    if (optional_usize(r, "cooling_moves", &cooling_moves, &has_cooling_moves, f)) goto done;
    if (optional_bool(r, "local_walk", &local_walk, 0, f)) goto done;
    v = value_present(r, "work_room");
    has_work_room = v != NULL;
    if (v && as_u64(v, &work_room, f)) goto done;
    int has_weights = 0;
    if ((v = value_present(r, "work_weights"))) {
        if (v->kind != V_LIST) { fault(f, "ValueError", "expected a list, got %s", value_kind(v)); goto done; }
        n_weights = v->as.list.n;
        weights = malloc((n_weights ? n_weights : 1) * sizeof *weights);
        if (!weights) { fault(f, "RuntimeError", "out of memory"); goto done; }
        for (size_t i = 0; i < n_weights; i++)
            if (as_u64(&v->as.list.items[i], &weights[i], f)) goto done;
        has_weights = 1;
    }
    if (has_work_room && (!has_weights || n_weights != PARTS + 1)) {
        fault(f, "ValueError", "a chain weighed against a budget carries one weight for each part of its work");
        goto done;
    }
    (void)p_swap;
    if (!(locality >= 0.0 && locality < 1.0)) { fault(f, "ValueError", "locality must lie in [0,1)"); goto done; }
    if (locality > 0.0 && proposal_locality > 0.0) {
        fault(f, "ValueError", "a law with its own locality is not audited with another proposal locality");
        goto done;
    }
    Acceptance a = {0};
    a.beta = beta;
    a.zero_temperature = zero_temperature;
    if (has_cooling_from && has_cooling_moves && cooling_moves > 0) {
        a.has_beta_cooling = 1;
        a.start = cooling_from;
        a.moves = cooling_moves;
    }
    if (a.has_beta_cooling && zero_temperature) { fault(f, "ValueError", "a zero-temperature law cannot cool"); goto done; }
    if (field(r, "terms", &v, f) || parse_terms(v, &model, f)) goto done;
    int required[LEDGERS];
    required_of(&model, required);
    Mt rng;
    if (mt_from(&rng, words, n_words, mt_index, f)) goto done;
    if (check_edge_list(n, ab, n_edges, f)) goto done;
    if (graph_init(&g, n, required)) { fault(f, "RuntimeError", "out of memory"); goto done; }
    graph_ready = 1;
    RebuildClock clock = {rebuild_stop_file, stop_check_seconds, now_seconds()};
    size_t stopped_at;
    if (rebuild_from(&model, &g, ab, n_edges, &clock, &stopped_at, f)) goto done;
    if (stopped_at < n_edges) {
        out_begin_map(o);
        out_key(o, "interrupted");
        out_str(o, "stop_requested");
        out_key(o, "edges_rebuilt");
        out_uint(o, stopped_at);
        out_end_map(o);
        status = 0;
        goto done;
    }
    g.non_edge_fast_path_hits = hits;
    g.non_edge_exact_fallbacks = fallbacks;
    int has_late_from = 0;
    size_t late_from = 0;
    if (has_late_change) {
        has_late_from = 1;
        late_from = late_change_from;
        g.late_on = 1;
        for (size_t i = 0; i < n_added; i++)
            if (!map_entry(&g.late_added, edge_key(late_added[2 * i], late_added[2 * i + 1]))) {
                fault(f, "RuntimeError", "out of memory");
                goto done;
            }
        for (size_t i = 0; i < n_removed; i++)
            if (!map_entry(&g.late_removed, edge_key(late_removed[2 * i], late_removed[2 * i + 1]))) {
                fault(f, "RuntimeError", "out of memory");
                goto done;
            }
    }
    int arm = has_late_from_move && late_from_move >= start_move;
    double energy = energy0;
    Counter attempted, proposed, accepted;
    if (counter_read(&attempted, value_get(r, "attempted"), f) || counter_read(&proposed, value_get(r, "proposed"), f)
        || counter_read(&accepted, value_get(r, "accepted"), f))
        goto done;
    if (g.edge_count > peak) peak = g.edge_count;
    if (!has_segment) segment_start = start_move;
    size_t segment_moves = total_moves > segment_start ? total_moves - segment_start : 0;
    size_t record_every = segment_moves / (points > 1 ? points : 1);
    if (record_every < 1) record_every = 1;
    if (accounting_read(&acc, value_get(r, "accounting"), f)) goto done;
    acc_ready = 1;
    accounting_start_segment(&acc, start_move, segment_start, segment_moves);
    double last_stop_check = now_seconds();
    double last_clock_read = last_stop_check;
    size_t clock_stride = CLOCK_STRIDE_START_MOVES;
    size_t next_clock_move = start_move + clock_stride;
    size_t max_edges = n * (n > 0 ? n - 1 : 0) / 2;
    size_t trajectory_count = trajectory_len;
    int term_kind = 0, term_has_points = 0;
    size_t term_at = 0, term_points = 0;
    uint64_t term_units = 0;
    double term_mean = 0.0, term_cap = 0.0;
    uint64_t counted_from[PARTS + 1], late_counted_from[PARTS + 1], counted_now[PARTS + 1];
    int has_late_counted = 0;
    graph_counted(&g, counted_from);
    uint64_t moves_run = 0, late_moves_run = 0;
    Run run = {&model, &g, &rng, n, zero_temperature, &energy, &energy_int, &peak, &proposed, &accepted, &acc};
    out_begin_list(&traj);
    for (size_t mv = start_move; mv < total_moves; mv++) {
        moves_run++;
        if (acc.has_late_from && mv >= acc.late_from) {
            late_moves_run++;
            if (!has_late_counted) {
                graph_counted(&g, late_counted_from);
                has_late_counted = 1;
            }
        }
        if (arm && late_from_move == mv) {
            map_free(&g.late_added);
            map_free(&g.late_removed);
            if (map_init(&g.late_added, 0) || map_init(&g.late_removed, 0)) {
                fault(f, "RuntimeError", "out of memory");
                goto done;
            }
            g.late_on = 1;
            has_late_from = 1;
            late_from = mv;
        }
        size_t e_count = g.edge_count;
        if (local_walk) {
            uint32_t a0 = (uint32_t)mt_range(&rng, n);
            double draw = mt_random(&rng);
            if (draw < LOCAL_WALK_DELETE) {
                attempted.del++;
                uint32_t *first;
                size_t nf;
                if (sorted_neighbours(&g, a0, 0, 0, 0, &first, &nf)) { fault(f, "RuntimeError", "out of memory"); goto done; }
                if (nf) {
                    uint32_t b = first[mt_range(&rng, nf)];
                    free(first);
                    if (local_toggle(&run, a0, b, 0, beta_at(&a, mv), mv, f)) goto done;
                } else {
                    free(first);
                }
            } else if (draw < LOCAL_WALK_SWAP_BELOW) {
                attempted.swap++;
                uint32_t *first, *second = NULL, *third = NULL;
                size_t nf, ns = 0, nt = 0;
                int pick = 0;
                uint32_t b = 0, c = 0, d = 0;
                if (sorted_neighbours(&g, a0, 0, 0, 0, &first, &nf)) { fault(f, "RuntimeError", "out of memory"); goto done; }
                if (nf) {
                    b = first[mt_range(&rng, nf)];
                    if (sorted_neighbours(&g, b, 0, 0, 0, &second, &ns)) { free(first); fault(f, "RuntimeError", "out of memory"); goto done; }
                    size_t kept = 0;
                    for (size_t i = 0; i < ns; i++)
                        if (second[i] != a0) second[kept++] = second[i];
                    ns = kept;
                    if (ns) {
                        c = second[mt_range(&rng, ns)];
                        if (sorted_neighbours(&g, c, 0, 0, 0, &third, &nt)) {
                            free(first); free(second); fault(f, "RuntimeError", "out of memory"); goto done;
                        }
                        kept = 0;
                        for (size_t i = 0; i < nt; i++)
                            if (third[i] != b) third[kept++] = third[i];
                        nt = kept;
                        if (nt) {
                            d = third[mt_range(&rng, nt)];
                            if (!(d == a0 || graph_tests_edge(&g, a0, c) || graph_tests_edge(&g, b, d))) pick = 1;
                        }
                    }
                }
                free(first);
                free(second);
                free(third);
                if (pick) {
                    EdgeKey e[4] = {edge_key(a0, b), edge_key(c, d), edge_key(a0, c), edge_key(b, d)};
                    if (run_swap(&run, &a, e, mv, SCOPE_LOCAL, f)) goto done;
                }
            } else {
                attempted.add++;
                static const size_t steps_of[2] = {2, 3};
                size_t steps = steps_of[mt_range(&rng, 2)];
                uint32_t x = a0;
                int stuck = 0;
                for (size_t s = 0; s < steps; s++) {
                    uint32_t *onward;
                    size_t no;
                    if (sorted_neighbours(&g, x, 0, 0, 0, &onward, &no)) { fault(f, "RuntimeError", "out of memory"); goto done; }
                    if (!no) { free(onward); stuck = 1; break; }
                    x = onward[mt_range(&rng, no)];
                    free(onward);
                }
                if (!stuck && x != a0 && !graph_tests_edge(&g, a0, x))
                    if (local_toggle(&run, a0, x, 1, beta_at(&a, mv), mv, f)) goto done;
            }
        } else if (locality > 0.0 && mt_random(&rng) < locality) {
            uint32_t u = (uint32_t)mt_range(&rng, n);
            uint32_t *nbrs;
            size_t d;
            if (sorted_neighbours(&g, u, 0, 0, 0, &nbrs, &d)) { fault(f, "RuntimeError", "out of memory"); goto done; }
            if (d < 2) {
                free(nbrs);
                attempted.add++;
            } else {
                size_t i = mt_range(&rng, d), j = mt_range(&rng, d - 1);
                if (j >= i) j++;
                EdgeKey e = edge_key(nbrs[i], nbrs[j]);
                free(nbrs);
                int adding = !graph_tests_edge(&g, key_a(e), key_b(e));
                if (adding) { attempted.add++; proposed.add++; } else { attempted.del++; proposed.del++; }
                if (run_toggle(&run, &a, key_a(e), key_b(e), adding, 0.0, mv, SCOPE_LOCAL, f)) goto done;
            }
        } else if (proposal_locality > 0.0) {
            int has_pair = 0;
            EdgeKey e = 0;
            if (n >= 2) {
                if (mt_random(&rng) < proposal_locality) {
                    size_t root = (size_t)sqrt((double)n), half = (n - 1) / 2;
                    if (half < 1) half = 1;
                    size_t radius = root < half ? root : half;
                    if (radius < 1) radius = 1;
                    size_t u = mt_range(&rng, n);
                    size_t distance = 1 + mt_range(&rng, radius);
                    size_t w = mt_random(&rng) < 0.5 ? (u + distance) % n : (u + n - (distance % n)) % n;
                    if (w == u) w = (u + 1) % n;
                    e = edge_key((uint32_t)u, (uint32_t)w);
                } else {
                    size_t u = mt_range(&rng, n), w = mt_range(&rng, n - 1);
                    if (w >= u) w++;
                    e = edge_key((uint32_t)u, (uint32_t)w);
                }
                has_pair = 1;
            }
            if (!has_pair) {
                attempted.add++;
            } else {
                int adding = !graph_tests_edge(&g, key_a(e), key_b(e));
                if (adding) { attempted.add++; proposed.add++; } else { attempted.del++; proposed.del++; }
                if (run_toggle(&run, &a, key_a(e), key_b(e), adding, 0.0, mv, SCOPE_GLOBAL, f)) goto done;
            }
        } else {
            double draw = mt_random(&rng);
            int kind = draw < p_add ? 0 : (draw < p_add + p_del ? 1 : 2);
            if (kind == 0) attempted.add++; else if (kind == 1) attempted.del++; else attempted.swap++;
            if (kind == 2) {
                size_t ec = g.edge_count;
                int pick = 0;
                EdgeKey e[4];
                if (ec >= 2) {
                    size_t i = mt_range(&rng, ec), j = mt_range(&rng, ec - 1);
                    if (j >= i) j++;
                    uint32_t pa = g.edges[2 * i], pb = g.edges[2 * i + 1], pc = g.edges[2 * j], pd = g.edges[2 * j + 1];
                    if (pa != pc && pa != pd && pb != pc && pb != pd) {
                        EdgeKey n1, n2;
                        if (mt_random(&rng) < 0.5) { n1 = edge_key(pa, pc); n2 = edge_key(pb, pd); }
                        else { n1 = edge_key(pa, pd); n2 = edge_key(pb, pc); }
                        if (!(n1 == n2 || graph_tests_edge(&g, key_a(n1), key_b(n1))
                              || graph_tests_edge(&g, key_a(n2), key_b(n2)))) {
                            e[0] = edge_key(pa, pb);
                            e[1] = edge_key(pc, pd);
                            e[2] = n1;
                            e[3] = n2;
                            pick = 1;
                        }
                    }
                }
                if (pick && run_swap(&run, &a, e, mv, SCOPE_GLOBAL, f)) goto done;
            } else {
                int adding = kind == 0;
                int feasible = !((adding && e_count >= max_edges) || (!adding && e_count == 0));
                if (feasible) {
                    uint32_t u, w;
                    double lr;
                    if (adding) {
                        const char *why;
                        if (graph_sample_non_edge(&g, &rng, &u, &w, &why)) { fault(f, "RuntimeError", "%s", why); goto done; }
                        proposed.add++;
                        lr = log(p_del * (double)(max_edges - e_count)) - log(p_add * (double)(e_count + 1));
                    } else {
                        size_t at = mt_range(&rng, e_count);
                        u = g.edges[2 * at];
                        w = g.edges[2 * at + 1];
                        proposed.del++;
                        lr = log(p_add * (double)e_count) - log(p_del * (double)(max_edges - e_count + 1));
                    }
                    if (run_toggle(&run, &a, u, w, adding, lr, mv, SCOPE_GLOBAL, f)) goto done;
                }
            }
        }
        if (has_cap && g.edge_count > cap_edges) {
            term_kind = 1;
            term_at = mv;
            term_mean = 2.0 * (double)g.edge_count / (double)n;
            term_cap = has_mean_degree_cap ? mean_degree_cap : 2.0 * (double)cap_edges / (double)n;
        }
        int at_record = (mv - segment_start) % record_every == 0 || mv == total_moves - 1;
        int at_stride = mv >= next_clock_move;
        int at_clock = at_record || at_stride;
        double now = at_clock ? now_seconds() : last_clock_read;
        if (at_stride) {
            clock_stride = next_clock_stride(clock_stride, now - last_clock_read, stop_check_seconds);
            last_clock_read = now;
            next_clock_move = mv + clock_stride;
        }
        int stopping = 0;
        if (!term_kind && at_clock && mv + 1 < total_moves && stop_file) {
            if (now - last_stop_check >= 0.5 * stop_check_seconds) {
                last_stop_check = now;
                if (exists(stop_file)) {
                    term_kind = 2;
                    term_at = mv;
                    stopping = 1;
                }
            }
        }
        if (!term_kind && mv + 1 < total_moves && (mv - segment_start) % WORK_CHECK_MOVES == WORK_CHECK_MOVES - 1
            && has_work_room && has_weights) {
            uint64_t now_counted[PARTS + 1];
            graph_counted(&g, now_counted);
            uint64_t spent = weights[0] * moves_run;
            for (int i = 1; i <= PARTS; i++) spent += weights[i] * (now_counted[i] - counted_from[i]);
            if (spent >= work_room) {
                term_kind = 3;
                term_at = mv;
                term_units = spent;
                stopping = 1;
            }
        }
        if (stopping && !at_record) break;
        if (at_record || term_kind) {
            record_point(&model, &g, energy, mv, n, &attempted, &proposed, &accepted, &traj);
            out_key(&traj, "_energy_is_int");
            out_bool(&traj, energy_int);
            if (trajectory_count % STRUCTURE_POINT_STRIDE == 0) {
                size_t components, largest;
                uint64_t triangles;
                if (graph_trajectory_structure(&g, &components, &largest, &triangles)) {
                    fault(f, "RuntimeError", "out of memory");
                    goto done;
                }
                out_key(&traj, "components");
                out_uint(&traj, components);
                out_key(&traj, "largest_component");
                out_uint(&traj, largest);
                out_key(&traj, "triangles");
                out_uint(&traj, triangles);
            }
            out_end_map(&traj);
            trajectory_count++;
            if (term_kind) {
                term_has_points = 1;
                term_points = trajectory_count;
                break;
            }
        }
    }
    out_end_list(&traj);
    graph_counted(&g, counted_now);
    block_count(&acc.whole, counted_from, counted_now, moves_run);
    if (has_late_counted) block_count(&acc.late, late_counted_from, counted_now, late_moves_run);
    if (!traj.s) { fault(f, "RuntimeError", "out of memory"); goto done; }
    out_begin_map(o);
    out_key(o, "edge_list");
    out_pairs(o, g.edges, g.edge_count);
    out_key(o, "energy");
    out_float(o, energy);
    out_key(o, "energy_is_int");
    out_bool(o, energy_int);
    out_key(o, "trajectory");
    out_json(o, traj.s, traj.len);
    out_key(o, "late_change");
    if (has_late_from && g.late_on) {
        uint32_t *added, *removed;
        size_t na, nr;
        if (sorted_keys(&g.late_added, &added, &na)) { fault(f, "RuntimeError", "out of memory"); goto done; }
        if (sorted_keys(&g.late_removed, &removed, &nr)) { free(added); fault(f, "RuntimeError", "out of memory"); goto done; }
        out_begin_list(o);
        out_uint(o, late_from);
        out_pairs(o, added, na);
        out_pairs(o, removed, nr);
        out_end_list(o);
        free(added);
        free(removed);
    } else {
        out_null(o);
    }
    out_key(o, "attempted");
    counter_write(&attempted, o);
    out_key(o, "proposed");
    counter_write(&proposed, o);
    out_key(o, "accepted");
    counter_write(&accepted, o);
    out_key(o, "peak_edge_count");
    out_uint(o, peak);
    out_key(o, "termination");
    if (term_kind == 0) {
        out_null(o);
    } else {
        out_begin_map(o);
        out_key(o, "reason");
        out_str(o, term_kind == 1 ? "mean_degree_cap" : (term_kind == 2 ? "stop_requested" : "work_budget"));
        out_key(o, "at_move");
        out_uint(o, term_at);
        if (term_kind == 1) {
            out_key(o, "at_sweep");
            out_uint(o, term_at / (n > 1 ? n : 1));
            out_key(o, "mean_degree_at_stop");
            out_float(o, term_mean);
            out_key(o, "cap");
            out_float(o, term_cap);
        } else if (term_kind == 3) {
            out_key(o, "units");
            out_uint(o, term_units);
        }
        if (term_has_points) {
            out_key(o, "trajectory_points");
            out_uint(o, term_points);
        }
        out_end_map(o);
    }
    out_key(o, "accounting");
    accounting_write(&acc, o);
    out_key(o, "mt_words");
    out_words(o, rng.mt, MT_N);
    out_key(o, "mt_index");
    out_uint(o, rng.mti);
    out_key(o, "non_edge_fast_path_hits");
    out_uint(o, g.non_edge_fast_path_hits);
    out_key(o, "non_edge_exact_fallbacks");
    out_uint(o, g.non_edge_exact_fallbacks);
    out_key(o, "ledgers");
    write_ledgers(&g, o);
    out_key(o, "degrees");
    out_begin_list(o);
    for (size_t i = 0; i < n; i++) out_uint(o, g.adj[i].len);
    out_end_list(o);
    out_key(o, "adj");
    write_adj(&g, o);
    out_key(o, "structural_summary");
    write_summary(&g, o);
    out_end_map(o);
    status = 0;
done:
    if (acc_ready) accounting_free(&acc);
    if (graph_ready) graph_free(&g);
    model_free(&model);
    out_free(&traj);
    free(words);
    free(ab);
    free(late_added);
    free(late_removed);
    free(weights);
    return status;
}

static int rebuild_graph(const Value *r, Out *o, Fault *f) {
    const Value *v;
    size_t n, n_edges = 0;
    uint32_t *ab = NULL;
    uint64_t hits, fallbacks;
    const char *stop_file;
    double tick;
    Model model = {0};
    Graph g;
    int graph_ready = 0, status = -1;
    if (field(r, "n", &v, f) || as_usize(v, &n, f)) goto done;
    if (field(r, "edge_list", &v, f) || as_pairs(v, &ab, &n_edges, f)) goto done;
    if (optional_u64(r, "non_edge_fast_path_hits", &hits, 0, f)) goto done;
    if (optional_u64(r, "non_edge_exact_fallbacks", &fallbacks, 0, f)) goto done;
    if (optional_str(r, "stop_file", &stop_file, f)) goto done;
    if (optional_f64(r, "stop_check_seconds", &tick, STOP_CHECK_SECONDS, NULL, f)) goto done;
    if (field(r, "terms", &v, f) || parse_terms(v, &model, f)) goto done;
    int required[LEDGERS];
    required_of(&model, required);
    if (check_edge_list(n, ab, n_edges, f)) goto done;
    if (graph_init(&g, n, required)) { fault(f, "RuntimeError", "out of memory"); goto done; }
    graph_ready = 1;
    double started = now_seconds();
    RebuildClock clock = {stop_file, tick, started};
    size_t stopped_at;
    if (rebuild_from(&model, &g, ab, n_edges, &clock, &stopped_at, f)) goto done;
    out_begin_map(o);
    if (stopped_at < n_edges) {
        out_key(o, "interrupted");
        out_str(o, "stop_requested");
        out_key(o, "edges_rebuilt");
        out_uint(o, stopped_at);
        out_key(o, "seconds");
        out_float(o, now_seconds() - started);
        out_end_map(o);
        status = 0;
        goto done;
    }
    g.non_edge_fast_path_hits = hits;
    g.non_edge_exact_fallbacks = fallbacks;
    out_key(o, "edge_list");
    out_pairs(o, g.edges, g.edge_count);
    out_key(o, "non_edge_fast_path_hits");
    out_uint(o, g.non_edge_fast_path_hits);
    out_key(o, "non_edge_exact_fallbacks");
    out_uint(o, g.non_edge_exact_fallbacks);
    out_key(o, "ledgers");
    write_ledgers(&g, o);
    out_key(o, "adj");
    write_adj(&g, o);
    out_key(o, "structural_summary");
    write_summary(&g, o);
    out_key(o, "seconds");
    out_float(o, now_seconds() - started);
    out_end_map(o);
    status = 0;
done:
    if (graph_ready) graph_free(&g);
    model_free(&model);
    free(ab);
    return status;
}

static int init_random_graph(const Value *r, Out *o, Fault *f) {
    const Value *v;
    size_t n, target, mt_index, n_words = 0;
    uint32_t *words = NULL;
    double energy;
    int energy_int, graph_ready = 0, status = -1;
    Model model = {0};
    Graph g;
    if (field(r, "n", &v, f) || as_usize(v, &n, f)) goto done;
    if (field(r, "target_edges", &v, f) || as_usize(v, &target, f)) goto done;
    if (field(r, "mt_words", &v, f) || as_words(v, &words, &n_words, f)) goto done;
    if (field(r, "mt_index", &v, f) || as_usize(v, &mt_index, f)) goto done;
    if (field(r, "energy", &v, f) || as_f64(v, &energy, f)) goto done;
    if (optional_bool(r, "energy_is_int", &energy_int, 0, f)) goto done;
    if (field(r, "terms", &v, f) || parse_terms(v, &model, f)) goto done;
    int required[LEDGERS];
    required_of(&model, required);
    Mt rng;
    if (mt_from(&rng, words, n_words, mt_index, f)) goto done;
    if (graph_init(&g, n, required)) { fault(f, "RuntimeError", "out of memory"); goto done; }
    graph_ready = 1;
    while (g.edge_count < target) {
        uint32_t u, w;
        const char *why;
        if (graph_sample_non_edge(&g, &rng, &u, &w, &why)) { fault(f, "RuntimeError", "%s", why); goto done; }
        Deltas d;
        double dh;
        if (apply_edge(&model, &g, u, w, 1, &d, &dh, f)) goto done;
        if (graph_apply(&g, u, w, 1, &d)) { fault(f, "RuntimeError", "out of memory"); goto done; }
        energy += dh;
        energy_int = 0;
    }
    out_begin_map(o);
    out_key(o, "edge_list");
    out_pairs(o, g.edges, g.edge_count);
    out_key(o, "adj");
    write_adj(&g, o);
    out_key(o, "energy");
    out_float(o, energy);
    out_key(o, "energy_is_int");
    out_bool(o, energy_int);
    out_key(o, "mt_words");
    out_words(o, rng.mt, MT_N);
    out_key(o, "mt_index");
    out_uint(o, rng.mti);
    out_key(o, "non_edge_fast_path_hits");
    out_uint(o, g.non_edge_fast_path_hits);
    out_key(o, "non_edge_exact_fallbacks");
    out_uint(o, g.non_edge_exact_fallbacks);
    out_key(o, "ledgers");
    write_ledgers(&g, o);
    out_end_map(o);
    status = 0;
done:
    if (graph_ready) graph_free(&g);
    model_free(&model);
    free(words);
    return status;
}

static int init_declared(const Value *r, Out *o, Fault *f) {
    const Value *v;
    size_t n, n_edges = 0;
    uint32_t *ab = NULL;
    double energy;
    int energy_int, graph_ready = 0, status = -1;
    Model model = {0};
    Graph g;
    if (field(r, "n", &v, f) || as_usize(v, &n, f)) goto done;
    if (field(r, "edges", &v, f) || as_pairs(v, &ab, &n_edges, f)) goto done;
    if (field(r, "energy", &v, f) || as_f64(v, &energy, f)) goto done;
    if (optional_bool(r, "energy_is_int", &energy_int, 0, f)) goto done;
    if (field(r, "terms", &v, f) || parse_terms(v, &model, f)) goto done;
    int required[LEDGERS];
    required_of(&model, required);
    if (graph_init(&g, n, required)) { fault(f, "RuntimeError", "out of memory"); goto done; }
    graph_ready = 1;
    for (size_t i = 0; i < n_edges; i++) {
        uint32_t u = ab[2 * i], w = ab[2 * i + 1];
        if (u >= n || w >= n || u == w) {
            fault(f, "ValueError", "declared edge (%u, %u) is not an edge of a graph on %zu nodes", u, w, n);
            goto done;
        }
        if (graph_has_edge(&g, u, w)) continue;
        Deltas d;
        double dh;
        if (apply_edge(&model, &g, u, w, 1, &d, &dh, f)) goto done;
        if (graph_apply(&g, u, w, 1, &d)) { fault(f, "RuntimeError", "out of memory"); goto done; }
        energy += dh;
        energy_int = 0;
    }
    out_begin_map(o);
    out_key(o, "edge_list");
    out_pairs(o, g.edges, g.edge_count);
    out_key(o, "adj");
    write_adj(&g, o);
    out_key(o, "energy");
    out_float(o, energy);
    out_key(o, "energy_is_int");
    out_bool(o, energy_int);
    out_key(o, "non_edge_fast_path_hits");
    out_uint(o, g.non_edge_fast_path_hits);
    out_key(o, "non_edge_exact_fallbacks");
    out_uint(o, g.non_edge_exact_fallbacks);
    out_key(o, "ledgers");
    write_ledgers(&g, o);
    out_end_map(o);
    status = 0;
done:
    if (graph_ready) graph_free(&g);
    model_free(&model);
    free(ab);
    return status;
}

static char *faulted(const Fault *f) {
    Out o;
    out_init(&o);
    out_begin_map(&o);
    out_key(&o, "fault");
    out_begin_map(&o);
    out_key(&o, "kind");
    out_str(&o, f->kind ? f->kind : "RuntimeError");
    out_key(&o, "message");
    out_str(&o, f->message);
    out_end_map(&o);
    out_end_map(&o);
    return o.s;
}

char *gsd_engine_call(const char *operation, const char *request) {
    Fault f = {0};
    Value r;
    r.kind = V_NULL;
    if (!operation || !request) {
        fault(&f, "ValueError", "the operation and the request are UTF-8 text");
        return faulted(&f);
    }
    if (value_parse(request, &r, &f)) {
        value_free(&r);
        return faulted(&f);
    }
    Out o;
    out_init(&o);
    out_raw(&o, "{\"answer\":");
    o.depth = 0;
    int status;
    if (strcmp(operation, "init_random_graph") == 0) status = init_random_graph(&r, &o, &f);
    else if (strcmp(operation, "init_declared") == 0) status = init_declared(&r, &o, &f);
    else if (strcmp(operation, "run_chain") == 0) status = run_chain(&r, &o, &f);
    else if (strcmp(operation, "rebuild_graph") == 0) status = rebuild_graph(&r, &o, &f);
    else {
        status = fault(&f, "ValueError",
                       "unknown operation %s; the engine answers [\"init_random_graph\", \"init_declared\", "
                       "\"run_chain\", \"rebuild_graph\"]", operation);
    }
    value_free(&r);
    if (status) {
        out_free(&o);
        return faulted(&f);
    }
    out_raw(&o, "}");
    if (!o.s) {
        fault(&f, "RuntimeError", "out of memory");
        return faulted(&f);
    }
    return o.s;
}

void gsd_engine_free(char *answered) { free(answered); }

const char *gsd_engine_version(void) { return GSD_ENGINE_C_VERSION; }
