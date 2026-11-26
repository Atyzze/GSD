#ifndef GSD_GRAPH_H
#define GSD_GRAPH_H

#include <stddef.h>
#include <stdint.h>

#include "mt.h"

#define PARTS 5
#define PART_EVALUATIONS 0
#define PART_CHANGES 1
#define PART_LISTS 2
#define PART_ENTRIES 3
#define PART_TESTS 4
#define LEDGERS 10

typedef enum {
    OP_EDGE_COUNT, OP_DEGREE_SQUARE_SUM, OP_WEDGE_COUNT, OP_TRIANGLE_COUNT, OP_TRIANGLE_EDGE_OVERLAP,
    OP_SQUARE_COUNT, OP_SQUARE_EDGE_OVERLAP, OP_INDUCED_SQUARE_COUNT, OP_DEGREE_NEIGHBOR_GRADIENT,
    OP_DEGREE_ANCHOR, OP_DEGREE_ANCHOR_ABS, OP_DEGREE_CUBE_SUM, OP_DEGREE_FOURTH_SUM, OP_OLLIVIER_CURVATURE,
    OP_UNKNOWN
} Op;

extern const char *const LEDGER_NAMES[LEDGERS];

Op op_parse(const char *name);
const char *op_name(Op op);
int op_is_node(Op op);
int op_ledger(Op op);

typedef uint64_t EdgeKey;

static inline EdgeKey edge_key(uint32_t u, uint32_t v) {
    return u < v ? ((uint64_t)u << 32) | v : ((uint64_t)v << 32) | u;
}
static inline uint32_t key_a(EdgeKey k) { return (uint32_t)(k >> 32); }
static inline uint32_t key_b(EdgeKey k) { return (uint32_t)k; }

typedef struct {
    EdgeKey *keys;
    int64_t *vals;
    size_t cap, n, width;
} EdgeMap;

int map_init(EdgeMap *m, size_t width);
void map_free(EdgeMap *m);
void map_clear(EdgeMap *m);
int64_t *map_entry(EdgeMap *m, EdgeKey key);
int64_t *map_find(const EdgeMap *m, EdgeKey key);
int map_remove(EdgeMap *m, EdgeKey key);

typedef struct {
    uint32_t *nb;
    uint32_t *sl;
    uint32_t len, cap;
} NodeList;

typedef struct {
    double ledger[LEDGERS];
} Deltas;

typedef struct {
    size_t n;
    NodeList *adj;
    uint32_t *edges;
    size_t edge_count, edge_cap;
    int64_t *non_degree;
    int64_t *tree;
    uint64_t non_edge_fast_path_hits, non_edge_exact_fallbacks;
    double ledgers[LEDGERS];
    int required[LEDGERS];
    int64_t *squares;
    int64_t *cycles;
    int has_last_curvature;
    uint32_t lc_u, lc_v;
    int lc_adding;
    EdgeMap lc_changes;
    int64_t lc_own[3];
    EdgeMap scratch_changes;
    EdgeMap affected;
    uint32_t *mark;
    uint32_t stamp;
    int has_square_key;
    uint32_t sq_u, sq_v;
    int sq_adding;
    uint32_t *sq_paths;
    size_t sq_paths_n, sq_paths_cap;
    int has_square_multiplicity;
    EdgeMap sq_multiplicity;
    int late_on;
    EdgeMap late_added, late_removed;
    uint64_t work;
    uint64_t parts[PARTS];
    uint32_t *tmp_a, *tmp_b, *tmp_c;
    size_t tmp_a_cap, tmp_b_cap, tmp_c_cap;
} Graph;

int graph_init(Graph *g, size_t n, const int *required);
void graph_free(Graph *g);
static inline size_t graph_degree(const Graph *g, uint32_t v) { return g->adj[v].len; }
int graph_has_edge(const Graph *g, uint32_t u, uint32_t v);
int graph_tests_edge(Graph *g, uint32_t u, uint32_t v);
void graph_read_lists(Graph *g, size_t lists, size_t entries);
void graph_scan(Graph *g, size_t entries);
void graph_counted(const Graph *g, uint64_t out[PARTS + 1]);
int graph_sample_non_edge(Graph *g, Mt *rng, uint32_t *u, uint32_t *v, const char **why);
int graph_op_deltas(Graph *g, uint32_t u, uint32_t v, int adding, Deltas *out);
int graph_apply(Graph *g, uint32_t u, uint32_t v, int adding, const Deltas *deltas);
void graph_structural_summary(const Graph *g, double *connected, size_t *components, double *cycle_density,
                              double *two_core);
int graph_trajectory_structure(const Graph *g, size_t *components, size_t *largest, uint64_t *triangles);

#endif
