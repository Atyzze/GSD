#ifndef GSD_VALUE_H
#define GSD_VALUE_H

#include <stddef.h>
#include <stdint.h>

typedef enum { V_NULL, V_BOOL, V_INT, V_UINT, V_FLOAT, V_STR, V_LIST, V_MAP, V_PAIRS } Kind;

typedef struct Value Value;

struct Value {
    Kind kind;
    union {
        int b;
        int64_t i;
        uint64_t u;
        double f;
        struct { char *s; size_t len; } str;
        struct { Value *items; size_t n, cap; } list;
        struct { char **keys; Value *vals; size_t n, cap; } map;
        struct { uint32_t *ab; size_t n, cap; } pairs;
    } as;
};

typedef struct {
    const char *kind;
    char message[512];
    int set;
} Fault;

int fault(Fault *f, const char *kind, const char *fmt, ...);

int value_parse(const char *text, Value *out, Fault *f);
void value_free(Value *v);

const Value *value_get(const Value *map, const char *key);
const Value *value_present(const Value *map, const char *key);
int value_is_null(const Value *v);
const char *value_kind(const Value *v);

int as_i64(const Value *v, int64_t *out, Fault *f);
int as_u64(const Value *v, uint64_t *out, Fault *f);
int as_usize(const Value *v, size_t *out, Fault *f);
int as_u32(const Value *v, uint32_t *out, Fault *f);
int as_f64(const Value *v, double *out, Fault *f);
int as_bool(const Value *v, int *out, Fault *f);
int as_str(const Value *v, const char **out, Fault *f);
int as_pairs(const Value *v, uint32_t **out, size_t *n, Fault *f);
int as_words(const Value *v, uint32_t **out, size_t *n, Fault *f);
size_t list_len(const Value *v);
int list_item(const Value *v, size_t i, Value *scratch, const Value **out, Fault *f);

typedef struct {
    char *s;
    size_t len, cap;
    int first[256];
    int depth;
} Out;

void out_init(Out *o);
void out_free(Out *o);
void out_raw(Out *o, const char *text);
void out_key(Out *o, const char *key);
void out_begin_map(Out *o);
void out_end_map(Out *o);
void out_begin_list(Out *o);
void out_end_list(Out *o);
void out_null(Out *o);
void out_bool(Out *o, int b);
void out_int(Out *o, int64_t v);
void out_uint(Out *o, uint64_t v);
void out_float(Out *o, double v);
void out_str(Out *o, const char *text);
void out_pairs(Out *o, const uint32_t *ab, size_t n);
void out_words(Out *o, const uint32_t *w, size_t n);
void out_json(Out *o, const char *text, size_t n);

#endif
