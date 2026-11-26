#include "graph.h"

#include <stdlib.h>
#include <string.h>

static const EdgeKey EMPTY = UINT64_MAX;

const char *const LEDGER_NAMES[LEDGERS] = {
    "edge_count", "degree_square_sum", "wedge_count", "triangle_count", "triangle_edge_overlap", "square_count",
    "square_edge_overlap", "induced_square_count", "degree_neighbor_gradient", "ollivier_curvature"};

static const char *const OP_NAMES[OP_UNKNOWN] = {
    "edge_count", "degree_square_sum", "wedge_count", "triangle_count", "triangle_edge_overlap", "square_count",
    "square_edge_overlap", "induced_square_count", "degree_neighbor_gradient", "degree_anchor", "degree_anchor_abs",
    "degree_cube_sum", "degree_fourth_sum", "ollivier_curvature"};

Op op_parse(const char *name) {
    for (int i = 0; i < OP_UNKNOWN; i++)
        if (strcmp(OP_NAMES[i], name) == 0) return (Op)i;
    return OP_UNKNOWN;
}

const char *op_name(Op op) { return op < OP_UNKNOWN ? OP_NAMES[op] : "unknown"; }

int op_is_node(Op op) {
    return op == OP_DEGREE_ANCHOR || op == OP_DEGREE_ANCHOR_ABS || op == OP_DEGREE_CUBE_SUM || op == OP_DEGREE_FOURTH_SUM;
}

int op_ledger(Op op) {
    switch (op) {
        case OP_EDGE_COUNT: return 0;
        case OP_DEGREE_SQUARE_SUM: return 1;
        case OP_WEDGE_COUNT: return 2;
        case OP_TRIANGLE_COUNT: return 3;
        case OP_TRIANGLE_EDGE_OVERLAP: return 4;
        case OP_SQUARE_COUNT: return 5;
        case OP_SQUARE_EDGE_OVERLAP: return 6;
        case OP_INDUCED_SQUARE_COUNT: return 7;
        case OP_DEGREE_NEIGHBOR_GRADIENT: return 8;
        case OP_OLLIVIER_CURVATURE: return 9;
        default: return -1;
    }
}

static size_t hash_at(EdgeKey key, size_t cap) {
    return (size_t)((key * 0x9E3779B97F4A7C15ull) >> 17) & (cap - 1);
}

int map_init(EdgeMap *m, size_t width) {
    m->cap = 16;
    m->n = 0;
    m->width = width;
    m->keys = malloc(m->cap * sizeof *m->keys);
    m->vals = calloc(m->cap * (width ? width : 1), sizeof *m->vals);
    if (!m->keys || !m->vals) return -1;
    for (size_t i = 0; i < m->cap; i++) m->keys[i] = EMPTY;
    return 0;
}

void map_free(EdgeMap *m) {
    free(m->keys);
    free(m->vals);
    m->keys = NULL;
    m->vals = NULL;
    m->cap = m->n = 0;
}

void map_clear(EdgeMap *m) {
    if (m->n == 0) return;
    if (m->cap > 4096 && m->n * 64 < m->cap) {
        size_t width = m->width;
        map_free(m);
        map_init(m, width);
        return;
    }
    for (size_t i = 0; i < m->cap; i++) m->keys[i] = EMPTY;
    m->n = 0;
}

static int map_grow(EdgeMap *m) {
    size_t width = m->width ? m->width : 1;
    size_t cap = m->cap * 2;
    EdgeKey *keys = malloc(cap * sizeof *keys);
    int64_t *vals = calloc(cap * width, sizeof *vals);
    if (!keys || !vals) { free(keys); free(vals); return -1; }
    for (size_t i = 0; i < cap; i++) keys[i] = EMPTY;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->keys[i] == EMPTY) continue;
        size_t at = hash_at(m->keys[i], cap);
        while (keys[at] != EMPTY) at = (at + 1) & (cap - 1);
        keys[at] = m->keys[i];
        memcpy(&vals[at * width], &m->vals[i * width], width * sizeof *vals);
    }
    free(m->keys);
    free(m->vals);
    m->keys = keys;
    m->vals = vals;
    m->cap = cap;
    return 0;
}

int64_t *map_entry(EdgeMap *m, EdgeKey key) {
    if ((m->n + 1) * 2 > m->cap && map_grow(m)) return NULL;
    size_t width = m->width ? m->width : 1;
    size_t at = hash_at(key, m->cap);
    while (m->keys[at] != EMPTY) {
        if (m->keys[at] == key) return &m->vals[at * width];
        at = (at + 1) & (m->cap - 1);
    }
    m->keys[at] = key;
    memset(&m->vals[at * width], 0, width * sizeof *m->vals);
    m->n++;
    return &m->vals[at * width];
}

int64_t *map_find(const EdgeMap *m, EdgeKey key) {
    size_t width = m->width ? m->width : 1;
    size_t at = hash_at(key, m->cap);
    while (m->keys[at] != EMPTY) {
        if (m->keys[at] == key) return &m->vals[at * width];
        at = (at + 1) & (m->cap - 1);
    }
    return NULL;
}

int map_remove(EdgeMap *m, EdgeKey key) {
    size_t width = m->width ? m->width : 1;
    size_t mask = m->cap - 1;
    size_t at = hash_at(key, m->cap);
    while (m->keys[at] != key) {
        if (m->keys[at] == EMPTY) return 0;
        at = (at + 1) & mask;
    }
    size_t hole = at;
    size_t next = (hole + 1) & mask;
    while (m->keys[next] != EMPTY) {
        size_t home = hash_at(m->keys[next], m->cap);
        if (((next - home) & mask) >= ((next - hole) & mask)) {
            m->keys[hole] = m->keys[next];
            memcpy(&m->vals[hole * width], &m->vals[next * width], width * sizeof *m->vals);
            hole = next;
        }
        next = (next + 1) & mask;
    }
    m->keys[hole] = EMPTY;
    m->n--;
    return 1;
}

static void fen_add(Graph *g, size_t index, int64_t delta) {
    size_t idx = index + 1;
    while (idx <= g->n) {
        g->tree[idx] += delta;
        idx += idx & (~idx + 1);
    }
}

static int64_t fen_total(const Graph *g) {
    size_t idx = g->n;
    int64_t s = 0;
    while (idx > 0) {
        s += g->tree[idx];
        idx -= idx & (~idx + 1);
    }
    return s;
}

static size_t fen_find(const Graph *g, int64_t order) {
    size_t pos = 0, step = 1;
    while (step * 2 <= g->n) step *= 2;
    while (step > 0) {
        size_t next = pos + step;
        if (next <= g->n && g->tree[next] <= order) {
            order -= g->tree[next];
            pos = next;
        }
        step /= 2;
    }
    return pos;
}

int graph_init(Graph *g, size_t n, const int *required) {
    memset(g, 0, sizeof *g);
    g->n = n;
    g->adj = calloc(n ? n : 1, sizeof *g->adj);
    g->non_degree = malloc((n ? n : 1) * sizeof *g->non_degree);
    g->tree = calloc(n + 1, sizeof *g->tree);
    g->mark = calloc(n ? n : 1, sizeof *g->mark);
    if (!g->adj || !g->non_degree || !g->tree || !g->mark) return -1;
    for (size_t i = 0; i < n; i++) g->non_degree[i] = (int64_t)n - 1;
    for (size_t i = 0; i < n; i++) {
        size_t idx = i + 1;
        while (idx <= n) {
            g->tree[idx] += g->non_degree[i];
            idx += idx & (~idx + 1);
        }
    }
    for (int i = 0; i < LEDGERS; i++) g->required[i] = required[i];
    if (map_init(&g->lc_changes, 3) || map_init(&g->scratch_changes, 3) || map_init(&g->affected, 0)
        || map_init(&g->sq_multiplicity, 1) || map_init(&g->late_added, 0) || map_init(&g->late_removed, 0))
        return -1;
    return 0;
}

void graph_free(Graph *g) {
    if (g->adj) {
        for (size_t i = 0; i < g->n; i++) {
            free(g->adj[i].nb);
            free(g->adj[i].sl);
        }
    }
    free(g->adj);
    free(g->edges);
    free(g->non_degree);
    free(g->tree);
    free(g->squares);
    free(g->cycles);
    free(g->mark);
    free(g->sq_paths);
    free(g->tmp_a);
    free(g->tmp_b);
    free(g->tmp_c);
    map_free(&g->lc_changes);
    map_free(&g->scratch_changes);
    map_free(&g->affected);
    map_free(&g->sq_multiplicity);
    map_free(&g->late_added);
    map_free(&g->late_removed);
    memset(g, 0, sizeof *g);
}

static inline void spend(Graph *g, size_t amount) { g->work += amount; }
static inline void part(Graph *g, int which, size_t amount) { g->parts[which] += amount; }

void graph_read_lists(Graph *g, size_t lists, size_t entries) {
    spend(g, entries);
    part(g, PART_LISTS, lists);
    part(g, PART_ENTRIES, entries);
}

void graph_scan(Graph *g, size_t entries) {
    spend(g, entries);
    part(g, PART_ENTRIES, entries);
}

static inline void units(Graph *g, size_t count) {
    spend(g, count);
    part(g, PART_TESTS, count);
}

void graph_counted(const Graph *g, uint64_t out[PARTS + 1]) {
    out[0] = g->work;
    for (int i = 0; i < PARTS; i++) out[i + 1] = g->parts[i];
}

static int contains(const NodeList *l, uint32_t value) {
    for (uint32_t i = 0; i < l->len; i++)
        if (l->nb[i] == value) return 1;
    return 0;
}

static long position(const NodeList *l, uint32_t value) {
    for (uint32_t i = 0; i < l->len; i++)
        if (l->nb[i] == value) return (long)i;
    return -1;
}

int graph_has_edge(const Graph *g, uint32_t u, uint32_t v) {
    if (g->adj[u].len <= g->adj[v].len) return contains(&g->adj[u], v);
    return contains(&g->adj[v], u);
}

int graph_tests_edge(Graph *g, uint32_t u, uint32_t v) {
    part(g, PART_TESTS, 1);
    return graph_has_edge(g, u, v);
}

static long slot_of(const Graph *g, uint32_t u, uint32_t v) {
    uint32_t a = u, b = v;
    if (g->adj[u].len > g->adj[v].len) { a = v; b = u; }
    long at = position(&g->adj[a], b);
    return at < 0 ? -1 : (long)g->adj[a].sl[at];
}

static int64_t squares_at(const Graph *g, EdgeKey e) {
    if (!g->required[6]) return 0;
    long s = slot_of(g, key_a(e), key_b(e));
    return s < 0 ? 0 : g->squares[s];
}

static void cycles_at(const Graph *g, EdgeKey e, int64_t out[3]) {
    out[0] = out[1] = out[2] = 0;
    if (!g->required[9]) return;
    long s = slot_of(g, key_a(e), key_b(e));
    if (s < 0) return;
    out[0] = g->cycles[3 * s];
    out[1] = g->cycles[3 * s + 1];
    out[2] = g->cycles[3 * s + 2];
}

static uint32_t next_stamp(Graph *g) {
    g->stamp++;
    if (g->stamp == 0) {
        memset(g->mark, 0, g->n * sizeof *g->mark);
        g->stamp = 1;
    }
    return g->stamp;
}

static int push_u32(uint32_t **items, size_t *n, size_t *cap, uint32_t value) {
    if (*n >= *cap) {
        size_t cap2 = *cap ? *cap * 2 : 16;
        uint32_t *next = realloc(*items, cap2 * sizeof *next);
        if (!next) return -1;
        *items = next;
        *cap = cap2;
    }
    (*items)[(*n)++] = value;
    return 0;
}

int graph_sample_non_edge(Graph *g, Mt *rng, uint32_t *ou, uint32_t *ov, const char **why) {
    int64_t oriented_missing = fen_total(g);
    if (oriented_missing <= 0) { *why = "complete graph has no non-edge"; return -1; }
    size_t n = g->n;
    for (int tries = 0; tries < 16; tries++) {
        units(g, 1);
        uint32_t u = (uint32_t)mt_range(rng, n);
        uint32_t v = n > 1 ? (uint32_t)mt_range(rng, n - 1) : 0;
        if (v >= u) v++;
        if (v != u && !contains(&g->adj[u], v)) {
            g->non_edge_fast_path_hits++;
            *ou = u < v ? u : v;
            *ov = u < v ? v : u;
            return 0;
        }
    }
    g->non_edge_exact_fallbacks++;
    uint32_t u = (uint32_t)fen_find(g, (int64_t)mt_below(rng, (uint64_t)oriented_missing));
    int64_t missing = g->non_degree[u];
    if (missing <= 0) { *why = "complement-degree sampler selected a saturated vertex"; return -1; }
    for (int tries = 0; tries < 64; tries++) {
        units(g, 1);
        uint32_t v = (uint32_t)mt_range(rng, n);
        if (v != u && !contains(&g->adj[u], v)) {
            *ou = u < v ? u : v;
            *ov = u < v ? v : u;
            return 0;
        }
    }
    int64_t rank = (int64_t)mt_below(rng, (uint64_t)missing);
    for (uint32_t v = 0; v < (uint32_t)n; v++) {
        units(g, 1);
        if (v == u || contains(&g->adj[u], v)) continue;
        if (rank == 0) {
            *ou = u < v ? u : v;
            *ov = u < v ? v : u;
            return 0;
        }
        rank--;
    }
    *why = "complement-degree ledger disagrees with adjacency";
    return -1;
}

static int square_paths(Graph *g, uint32_t u, uint32_t v, uint32_t **paths, size_t *count, size_t *cap) {
    size_t work = g->adj[u].len + g->adj[v].len;
    size_t lists = 2;
    uint32_t stamp = next_stamp(g);
    const NodeList *nv = &g->adj[v], *nu = &g->adj[u];
    for (uint32_t i = 0; i < nv->len; i++)
        if (nv->nb[i] != u) g->mark[nv->nb[i]] = stamp;
    *count = 0;
    for (uint32_t i = 0; i < nu->len; i++) {
        uint32_t x = nu->nb[i];
        if (x == v) continue;
        const NodeList *nx = &g->adj[x];
        work += nx->len;
        lists++;
        for (uint32_t j = 0; j < nx->len; j++) {
            uint32_t y = nx->nb[j];
            if (g->mark[y] == stamp) {
                size_t two = 2 * *count;
                if (push_u32(paths, &two, cap, x) || push_u32(paths, &two, cap, y)) return -1;
                (*count)++;
            }
        }
    }
    graph_read_lists(g, lists, work);
    return 0;
}

static int square_multiplicity(EdgeMap *m, uint32_t u, uint32_t v, const uint32_t *paths, size_t count) {
    map_clear(m);
    for (size_t i = 0; i < count; i++) {
        uint32_t x = paths[2 * i], y = paths[2 * i + 1];
        int64_t *a = map_entry(m, edge_key(u, x));
        if (!a) return -1;
        *a += 1;
        int64_t *b = map_entry(m, edge_key(x, y));
        if (!b) return -1;
        *b += 1;
        int64_t *c = map_entry(m, edge_key(y, v));
        if (!c) return -1;
        *c += 1;
    }
    return 0;
}

static double square_overlap_delta(const Graph *g, int adding, int64_t s, const EdgeMap *m) {
    double delta = adding ? (double)(s * (s - 1) / 2) : -((double)(s * (s - 1) / 2));
    for (size_t i = 0; i < m->cap; i++) {
        if (m->keys[i] == EMPTY) continue;
        int64_t mult = m->vals[i];
        int64_t q = squares_at(g, m->keys[i]);
        if (adding)
            delta += (double)(mult * q) + (double)(mult * (mult - 1) / 2);
        else
            delta += (double)(-mult * q) + (double)(mult * (mult + 1) / 2);
    }
    return delta;
}

static int common_neighbours(Graph *g, uint32_t u, uint32_t v, size_t *count) {
    graph_read_lists(g, 2, g->adj[u].len + g->adj[v].len);
    uint32_t stamp = next_stamp(g);
    const NodeList *nu = &g->adj[u], *nv = &g->adj[v];
    for (uint32_t i = 0; i < nu->len; i++) g->mark[nu->nb[i]] = stamp;
    *count = 0;
    for (uint32_t i = 0; i < nv->len; i++) {
        uint32_t y = nv->nb[i];
        if (g->mark[y] == stamp && push_u32(&g->tmp_a, count, &g->tmp_a_cap, y)) return -1;
    }
    return 0;
}

static int64_t intersection_size(Graph *g, uint32_t a, uint32_t b) {
    graph_read_lists(g, 2, g->adj[a].len + g->adj[b].len);
    uint32_t stamp = next_stamp(g);
    const NodeList *na = &g->adj[a], *nb = &g->adj[b];
    for (uint32_t i = 0; i < na->len; i++) g->mark[na->nb[i]] = stamp;
    int64_t found = 0;
    for (uint32_t i = 0; i < nb->len; i++)
        if (g->mark[nb->nb[i]] == stamp) found++;
    return found;
}

int64_t scaled_curvature(int64_t t, int64_t s, int64_t p, int64_t da, int64_t db);

int64_t scaled_curvature(int64_t t, int64_t s, int64_t p, int64_t da, int64_t db) {
    int64_t low = da <= db ? da : db, high = da <= db ? db : da;
    int64_t first = low * high - (1 + t + s) * low - high;
    if (first < 0) first = 0;
    int64_t left = t * high - t * low, right = low * high - (1 + t + s + p) * low - high;
    return t * high - first - (left > right ? left : right);
}

static int bump(EdgeMap *changes, uint32_t a, uint32_t b, int index, int64_t sign) {
    int64_t *c = map_entry(changes, edge_key(a, b));
    if (!c) return -1;
    c[index] += sign;
    return 0;
}

static int curvature_delta(Graph *g, uint32_t u, uint32_t v, int adding, EdgeMap *changes, int64_t own[3],
                           int64_t *out_delta) {
    int64_t sign = adding ? 1 : -1;
    size_t work = g->adj[u].len + g->adj[v].len;
    size_t lists = 2;
    uint32_t stamp = next_stamp(g);
    const NodeList *nu = &g->adj[u], *nv = &g->adj[v];
    for (uint32_t i = 0; i < nv->len; i++)
        if (nv->nb[i] != u) g->mark[nv->nb[i]] = stamp;
    map_clear(changes);
    int64_t triangles = 0, squares = 0, pentagons = 0;
    for (uint32_t i = 0; i < nu->len; i++) {
        uint32_t x = nu->nb[i];
        if (x == v) continue;
        if (g->mark[x] == stamp) {
            triangles++;
            if (bump(changes, u, x, 0, sign) || bump(changes, x, v, 0, sign)) return -1;
        }
        const NodeList *nx = &g->adj[x];
        work += 2 * nx->len;
        lists += 2;
        for (uint32_t j = 0; j < nx->len; j++) {
            uint32_t y = nx->nb[j];
            if (g->mark[y] == stamp) {
                squares++;
                if (bump(changes, u, x, 1, sign) || bump(changes, x, y, 1, sign) || bump(changes, y, v, 1, sign))
                    return -1;
            }
        }
        for (uint32_t j = 0; j < nx->len; j++) {
            uint32_t z = nx->nb[j];
            if (z == u || z == v) continue;
            const NodeList *nz = &g->adj[z];
            work += nz->len;
            lists++;
            for (uint32_t k = 0; k < nz->len; k++) {
                uint32_t y = nz->nb[k];
                if (y != x && g->mark[y] == stamp) {
                    pentagons++;
                    if (bump(changes, u, x, 2, sign) || bump(changes, x, z, 2, sign) || bump(changes, z, y, 2, sign)
                        || bump(changes, y, v, 2, sign))
                        return -1;
                }
            }
        }
    }
    graph_read_lists(g, lists, work);
    EdgeMap *affected = &g->affected;
    map_clear(affected);
    for (size_t i = 0; i < changes->cap; i++)
        if (changes->keys[i] != EMPTY && !map_entry(affected, changes->keys[i])) return -1;
    for (uint32_t i = 0; i < nu->len; i++)
        if (nu->nb[i] != v && !map_entry(affected, edge_key(u, nu->nb[i]))) return -1;
    for (uint32_t i = 0; i < nv->len; i++)
        if (nv->nb[i] != u && !map_entry(affected, edge_key(v, nv->nb[i]))) return -1;
    graph_read_lists(g, 2, nu->len + nv->len);
    units(g, affected->n);
    int64_t delta = 0;
    for (size_t i = 0; i < affected->cap; i++) {
        EdgeKey e = affected->keys[i];
        if (e == EMPTY) continue;
        uint32_t a = key_a(e), b = key_b(e);
        int64_t before[3], moved[3] = {0, 0, 0};
        cycles_at(g, e, before);
        int64_t *found = map_find(changes, e);
        if (found) { moved[0] = found[0]; moved[1] = found[1]; moved[2] = found[2]; }
        int64_t da = (int64_t)g->adj[a].len, db = (int64_t)g->adj[b].len;
        int64_t aa = da + ((a == u || a == v) ? sign : 0), ab = db + ((b == u || b == v) ? sign : 0);
        delta += scaled_curvature(before[0] + moved[0], before[1] + moved[1], before[2] + moved[2], aa, ab);
        delta -= scaled_curvature(before[0], before[1], before[2], da, db);
    }
    own[0] = triangles;
    own[1] = squares;
    own[2] = pentagons;
    int64_t du = (int64_t)nu->len, dv = (int64_t)nv->len;
    if (adding)
        delta += scaled_curvature(own[0], own[1], own[2], du + sign, dv + sign);
    else
        delta -= scaled_curvature(own[0], own[1], own[2], du, dv);
    *out_delta = delta;
    return 0;
}

static void update_edge_cycles(Graph *g, const EdgeMap *changes) {
    for (size_t i = 0; i < changes->cap; i++) {
        EdgeKey e = changes->keys[i];
        if (e == EMPTY) continue;
        long s = slot_of(g, key_a(e), key_b(e));
        int64_t *c = &g->cycles[3 * s];
        c[0] += changes->vals[3 * i];
        c[1] += changes->vals[3 * i + 1];
        c[2] += changes->vals[3 * i + 2];
    }
}

void graph_evaluated(Graph *g) {
    spend(g, 1);
    part(g, PART_EVALUATIONS, 1);
    g->has_last_curvature = 0;
    g->has_square_key = 0;
    g->sq_paths_n = 0;
    g->has_square_multiplicity = 0;
}

int graph_op_deltas(Graph *g, uint32_t u, uint32_t v, int adding, Deltas *out) {
    spend(g, 1);
    part(g, PART_EVALUATIONS, 1);
    double sign = adding ? 1.0 : -1.0;
    int64_t du = (int64_t)g->adj[u].len, dv = (int64_t)g->adj[v].len;
    if (!adding) { du -= 1; dv -= 1; }
    double *d = out->ledger;
    for (int i = 0; i < LEDGERS; i++) d[i] = 0.0;
    d[0] = sign;
    d[1] = sign * (double)(2 * du + 1 + 2 * dv + 1);
    d[2] = sign * (double)(du + dv);
    if (g->required[9]) {
        int64_t delta;
        if (curvature_delta(g, u, v, adding, &g->lc_changes, g->lc_own, &delta)) return -1;
        d[9] = (double)delta;
        g->has_last_curvature = 1;
        g->lc_u = u;
        g->lc_v = v;
        g->lc_adding = adding;
    } else {
        g->has_last_curvature = 0;
    }
    if (g->required[8]) {
        size_t read = g->adj[u].len + g->adj[v].len;
        graph_read_lists(g, 2, read);
        part(g, PART_LISTS, read);
        double gradient = sign * (double)((du - dv) * (du - dv));
        const NodeList *nu = &g->adj[u], *nv = &g->adj[v];
        for (uint32_t i = 0; i < nu->len; i++) {
            uint32_t x = nu->nb[i];
            if (x != v) gradient += sign * (double)(2 * (du - (int64_t)g->adj[x].len) + 1);
        }
        for (uint32_t i = 0; i < nv->len; i++) {
            uint32_t y = nv->nb[i];
            if (y != u) gradient += sign * (double)(2 * (dv - (int64_t)g->adj[y].len) + 1);
        }
        d[8] = gradient;
    }
    int neighbourhood = g->required[3] || g->required[4] || g->required[5] || g->required[6] || g->required[7]
        || g->required[8];
    if (!neighbourhood) {
        g->has_square_key = 0;
        g->sq_paths_n = 0;
        g->has_square_multiplicity = 0;
        return 0;
    }
    size_t common_n;
    if (common_neighbours(g, u, v, &common_n)) return -1;
    int64_t common = (int64_t)common_n;
    d[3] = sign * (double)common;
    int square_required = g->required[5] || g->required[6] || g->required[7];
    size_t paths_n = 0;
    if (square_required) {
        if (square_paths(g, u, v, &g->sq_paths, &paths_n, &g->sq_paths_cap)) return -1;
        g->has_square_key = 1;
        g->sq_u = u;
        g->sq_v = v;
        g->sq_adding = adding;
        g->has_square_multiplicity = 0;
    } else {
        g->has_square_key = 0;
        g->sq_paths_n = 0;
        g->has_square_multiplicity = 0;
    }
    const uint32_t *paths = g->sq_paths;
    if (g->required[5]) d[5] = sign * (double)paths_n;
    if (g->required[7]) {
        size_t pairs = common_n * (common_n > 0 ? common_n - 1 : 0) / 2;
        units(g, 2 * paths_n + pairs);
        int64_t boundary = 0, diagonal = 0;
        for (size_t i = 0; i < paths_n; i++) {
            uint32_t x = paths[2 * i], y = paths[2 * i + 1];
            if (!contains(&g->adj[u], y) && !contains(&g->adj[v], x)) boundary++;
        }
        for (size_t i = 0; i < common_n; i++) {
            uint32_t x = g->tmp_a[i];
            for (size_t j = i + 1; j < common_n; j++)
                if (!contains(&g->adj[x], g->tmp_a[j])) diagonal++;
        }
        d[7] = sign * (double)(boundary - diagonal);
    }
    if (g->required[6]) {
        if (square_multiplicity(&g->sq_multiplicity, u, v, paths, paths_n)) return -1;
        units(g, 3 * paths_n + g->sq_multiplicity.n);
        d[6] = square_overlap_delta(g, adding, (int64_t)paths_n, &g->sq_multiplicity);
        g->has_square_multiplicity = 1;
    }
    if (g->required[4]) {
        double overlap;
        size_t count = common_n;
        if (count > g->tmp_b_cap) {
            uint32_t *next = realloc(g->tmp_b, count * sizeof *next);
            if (!next) return -1;
            g->tmp_b = next;
            g->tmp_b_cap = count;
        }
        if (count) memcpy(g->tmp_b, g->tmp_a, count * sizeof *g->tmp_b);
        if (adding) {
            overlap = (double)(common * (common - 1) / 2);
            for (size_t i = 0; i < count; i++) {
                uint32_t w = g->tmp_b[i];
                overlap += (double)intersection_size(g, u, w);
                overlap += (double)intersection_size(g, v, w);
            }
        } else {
            overlap = -((double)(common * (common - 1) / 2));
            for (size_t i = 0; i < count; i++) {
                uint32_t w = g->tmp_b[i];
                int64_t a = intersection_size(g, u, w) - 1, b = intersection_size(g, v, w) - 1;
                overlap -= (double)(a > 0 ? a : 0);
                overlap -= (double)(b > 0 ? b : 0);
            }
        }
        d[4] = overlap;
    }
    if (square_required) g->sq_paths_n = paths_n;
    return 0;
}

static int update_square_edge_counts(Graph *g, uint32_t u, uint32_t v, int adding, const uint32_t *paths,
                                     size_t paths_n, int have_multiplicity) {
    if (!have_multiplicity && square_multiplicity(&g->sq_multiplicity, u, v, paths, paths_n)) return -1;
    EdgeMap *m = &g->sq_multiplicity;
    for (size_t i = 0; i < m->cap; i++) {
        EdgeKey e = m->keys[i];
        if (e == EMPTY) continue;
        long s = slot_of(g, key_a(e), key_b(e));
        int64_t *count = &g->squares[s];
        if (adding) {
            *count += m->vals[i];
        } else {
            int64_t left = *count - m->vals[i];
            *count = left > 0 ? left : 0;
        }
    }
    return 0;
}

static int list_push(NodeList *l, uint32_t value, uint32_t slot) {
    if (l->len >= l->cap) {
        uint32_t cap2 = l->cap ? l->cap * 2 : 4;
        uint32_t *nb = realloc(l->nb, cap2 * sizeof *nb);
        if (!nb) return -1;
        l->nb = nb;
        uint32_t *sl = realloc(l->sl, cap2 * sizeof *sl);
        if (!sl) return -1;
        l->sl = sl;
        l->cap = cap2;
    }
    l->nb[l->len] = value;
    l->sl[l->len] = slot;
    l->len++;
    return 0;
}

static void list_remove(NodeList *l, uint32_t value) {
    long at = position(l, value);
    if (at < 0) return;
    l->len--;
    l->nb[at] = l->nb[l->len];
    l->sl[at] = l->sl[l->len];
}

static void reslot(Graph *g, uint32_t a, uint32_t b, uint32_t slot) {
    long at = position(&g->adj[a], b);
    g->adj[a].sl[at] = slot;
}

static int grow_edges(Graph *g) {
    if (g->edge_count < g->edge_cap) return 0;
    size_t cap2 = g->edge_cap ? g->edge_cap * 2 : 16;
    uint32_t *edges = realloc(g->edges, cap2 * 2 * sizeof *edges);
    if (!edges) return -1;
    g->edges = edges;
    if (g->required[6]) {
        int64_t *squares = realloc(g->squares, cap2 * sizeof *squares);
        if (!squares) return -1;
        g->squares = squares;
    }
    if (g->required[9]) {
        int64_t *cycles = realloc(g->cycles, cap2 * 3 * sizeof *cycles);
        if (!cycles) return -1;
        g->cycles = cycles;
    }
    g->edge_cap = cap2;
    return 0;
}

int graph_apply(Graph *g, uint32_t u, uint32_t v, int adding, const Deltas *deltas) {
    spend(g, 1);
    part(g, PART_CHANGES, 1);
    int64_t own_cycles[3] = {0, 0, 0};
    if (g->required[9]) {
        if (g->has_last_curvature && g->lc_u == u && g->lc_v == v && g->lc_adding == adding) {
            update_edge_cycles(g, &g->lc_changes);
            memcpy(own_cycles, g->lc_own, sizeof own_cycles);
        } else {
            int64_t ignored;
            if (curvature_delta(g, u, v, adding, &g->scratch_changes, own_cycles, &ignored)) return -1;
            update_edge_cycles(g, &g->scratch_changes);
        }
    }
    g->has_last_curvature = 0;
    int64_t own_squares = 0;
    if (g->required[6]) {
        if (g->has_square_key && g->sq_u == u && g->sq_v == v && g->sq_adding == adding) {
            if (update_square_edge_counts(g, u, v, adding, g->sq_paths, g->sq_paths_n, g->has_square_multiplicity))
                return -1;
            own_squares = (int64_t)g->sq_paths_n;
        } else {
            size_t paths_n = 0;
            if (square_paths(g, u, v, &g->tmp_c, &paths_n, &g->tmp_c_cap)) return -1;
            if (update_square_edge_counts(g, u, v, adding, g->tmp_c, paths_n, 0)) return -1;
            own_squares = (int64_t)paths_n;
        }
    }
    g->has_square_key = 0;
    g->sq_paths_n = 0;
    g->has_square_multiplicity = 0;
    EdgeKey e = edge_key(u, v);
    if (adding) {
        if (grow_edges(g)) return -1;
        uint32_t slot = (uint32_t)g->edge_count;
        if (list_push(&g->adj[u], v, slot) || list_push(&g->adj[v], u, slot)) return -1;
        g->non_degree[u] -= 1;
        g->non_degree[v] -= 1;
        fen_add(g, u, -1);
        fen_add(g, v, -1);
        g->edges[2 * slot] = key_a(e);
        g->edges[2 * slot + 1] = key_b(e);
        if (g->required[6]) g->squares[slot] = own_squares;
        if (g->required[9]) memcpy(&g->cycles[3 * slot], own_cycles, sizeof own_cycles);
        g->edge_count++;
        if (g->late_on && !map_remove(&g->late_removed, e) && !map_entry(&g->late_added, e)) return -1;
    } else {
        long index = slot_of(g, u, v);
        list_remove(&g->adj[u], v);
        list_remove(&g->adj[v], u);
        g->non_degree[u] += 1;
        g->non_degree[v] += 1;
        fen_add(g, u, 1);
        fen_add(g, v, 1);
        size_t last_index = g->edge_count - 1;
        if ((size_t)index != last_index) {
            uint32_t la = g->edges[2 * last_index], lb = g->edges[2 * last_index + 1];
            g->edges[2 * index] = la;
            g->edges[2 * index + 1] = lb;
            reslot(g, la, lb, (uint32_t)index);
            reslot(g, lb, la, (uint32_t)index);
            if (g->required[6]) g->squares[index] = g->squares[last_index];
            if (g->required[9]) memcpy(&g->cycles[3 * index], &g->cycles[3 * last_index], 3 * sizeof *g->cycles);
        }
        g->edge_count--;
        if (g->late_on && !map_remove(&g->late_added, e) && !map_entry(&g->late_removed, e)) return -1;
    }
    for (int i = 0; i < LEDGERS; i++) g->ledgers[i] += deltas->ledger[i];
    return 0;
}

void graph_structural_summary(const Graph *g, double *connected, size_t *components, double *cycle_density,
                              double *two_core) {
    size_t n = g->n;
    unsigned char *seen = calloc(n ? n : 1, 1);
    uint32_t *stack = malloc((n ? n : 1) * sizeof *stack);
    uint32_t *comp = malloc((n ? n : 1) * sizeof *comp);
    uint32_t *largest = malloc((n ? n : 1) * sizeof *largest);
    size_t largest_n = 0, count = 0;
    for (size_t start = 0; start < n; start++) {
        if (seen[start]) continue;
        size_t top = 0, comp_n = 0;
        stack[top++] = (uint32_t)start;
        seen[start] = 1;
        while (top > 0) {
            uint32_t node = stack[--top];
            comp[comp_n++] = node;
            const NodeList *l = &g->adj[node];
            for (uint32_t i = 0; i < l->len; i++) {
                uint32_t other = l->nb[i];
                if (!seen[other]) {
                    seen[other] = 1;
                    stack[top++] = other;
                }
            }
        }
        count++;
        if (comp_n > largest_n) {
            memcpy(largest, comp, comp_n * sizeof *largest);
            largest_n = comp_n;
        }
    }
    unsigned char *in_largest = calloc(n ? n : 1, 1);
    int64_t *degree = calloc(n ? n : 1, sizeof *degree);
    unsigned char *removed = calloc(n ? n : 1, 1);
    uint32_t *queue = malloc((n ? n : 1) * sizeof *queue);
    for (size_t i = 0; i < largest_n; i++) in_largest[largest[i]] = 1;
    size_t largest_edges = 0;
    for (size_t i = 0; i < largest_n; i++) {
        uint32_t v = largest[i];
        size_t d = 0;
        for (uint32_t j = 0; j < g->adj[v].len; j++)
            if (in_largest[g->adj[v].nb[j]]) d++;
        largest_edges += d;
        degree[v] = (int64_t)d;
    }
    largest_edges /= 2;
    int64_t rank = (int64_t)largest_edges - (int64_t)largest_n + (largest_n > 0 ? 1 : 0);
    if (rank < 0) rank = 0;
    size_t queue_n = 0, cursor = 0;
    for (size_t i = 0; i < largest_n; i++) {
        uint32_t v = largest[i];
        if (degree[v] < 2) {
            removed[v] = 1;
            queue[queue_n++] = v;
        }
    }
    while (cursor < queue_n) {
        uint32_t v = queue[cursor++];
        for (uint32_t j = 0; j < g->adj[v].len; j++) {
            uint32_t other = g->adj[v].nb[j];
            if (in_largest[other] && !removed[other]) {
                degree[other] -= 1;
                if (degree[other] < 2) {
                    removed[other] = 1;
                    queue[queue_n++] = other;
                }
            }
        }
    }
    double nf = (double)(n > 1 ? n : 1), lf = (double)(largest_n > 1 ? largest_n : 1);
    *connected = (double)largest_n / nf;
    *components = count;
    *cycle_density = (double)rank / lf;
    *two_core = ((double)largest_n - (double)queue_n) / lf;
    free(seen);
    free(stack);
    free(comp);
    free(largest);
    free(in_largest);
    free(degree);
    free(removed);
    free(queue);
}

int graph_trajectory_structure(const Graph *g, size_t *components, size_t *largest, uint64_t *triangles) {
    size_t n = g->n;
    unsigned char *seen = calloc(n ? n : 1, 1);
    uint32_t *stack = malloc((n ? n : 1) * sizeof *stack);
    size_t *mark = malloc((n ? n : 1) * sizeof *mark);
    size_t *start_at = malloc((n + 1) * sizeof *start_at);
    uint32_t *up = malloc((2 * g->edge_count + 1) * sizeof *up);
    if (!seen || !stack || !mark || !start_at || !up) {
        free(seen); free(stack); free(mark); free(start_at); free(up);
        return -1;
    }
    size_t count = 0, most = 0;
    for (size_t s = 0; s < n; s++) {
        if (seen[s]) continue;
        count++;
        seen[s] = 1;
        size_t top = 0, size = 0;
        stack[top++] = (uint32_t)s;
        while (top > 0) {
            uint32_t node = stack[--top];
            size++;
            const NodeList *l = &g->adj[node];
            for (uint32_t i = 0; i < l->len; i++) {
                uint32_t other = l->nb[i];
                if (!seen[other]) {
                    seen[other] = 1;
                    stack[top++] = other;
                }
            }
        }
        if (size > most) most = size;
    }
    size_t at = 0;
    for (size_t u = 0; u < n; u++) {
        start_at[u] = at;
        const NodeList *l = &g->adj[u];
        for (uint32_t i = 0; i < l->len; i++) {
            uint32_t v = l->nb[i];
            size_t du = l->len, dv = g->adj[v].len;
            if (du < dv || (du == dv && u < v)) up[at++] = v;
        }
    }
    start_at[n] = at;
    for (size_t i = 0; i < n; i++) mark[i] = SIZE_MAX;
    uint64_t found = 0;
    for (size_t u = 0; u < n; u++) {
        for (size_t i = start_at[u]; i < start_at[u + 1]; i++) mark[up[i]] = u;
        for (size_t i = start_at[u]; i < start_at[u + 1]; i++) {
            uint32_t v = up[i];
            for (size_t j = start_at[v]; j < start_at[v + 1]; j++)
                if (mark[up[j]] == u) found++;
        }
    }
    *components = count;
    *largest = most;
    *triangles = found;
    free(seen);
    free(stack);
    free(mark);
    free(start_at);
    free(up);
    return 0;
}
