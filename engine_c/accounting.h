#ifndef GSD_ACCOUNTING_H
#define GSD_ACCOUNTING_H

#include <stdint.h>

#include "value.h"

#define KEYS 36
#define BINS 163
#define DELTA_H_BIN_LIMIT 40
#define KIND_ADD 0
#define KIND_DELETE 1
#define KIND_SWAP 2
#define SCOPE_LOCAL 0
#define SCOPE_GLOBAL 1

typedef struct {
    char *key;
    uint64_t proposed, accepted;
    int has_proposed, has_accepted;
} Extra;

typedef struct {
    uint64_t work;
    uint64_t parts[6];
    uint64_t counts[KEYS];
    uint64_t proposed[BINS], accepted[BINS];
    unsigned char has_proposed[BINS], has_accepted[BINS];
    Extra *extras;
    size_t extras_n;
} Block;

typedef struct {
    Block whole, late;
    int has_late_from;
    size_t late_from;
    int has_last_decrease;
    size_t last_decrease_move;
} Accounting;

int accounting_read(Accounting *acc, const Value *value, Fault *f);
void accounting_free(Accounting *acc);
void accounting_write(const Accounting *acc, Out *o);
void accounting_start_segment(Accounting *acc, size_t start_move, size_t segment_start, size_t segment_moves);
void accounting_tally(Accounting *acc, size_t mv, int kind, int scope, double delta_h, int took);
void block_count(Block *b, const uint64_t from[6], const uint64_t now[6], uint64_t moves);

#endif
