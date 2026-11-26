#ifndef GSD_MT_H
#define GSD_MT_H

#include <stddef.h>
#include <stdint.h>

#define MT_N 624
#define MT_M 397

typedef struct {
    uint32_t mt[MT_N];
    size_t mti;
} Mt;

static inline uint32_t mt_u32(Mt *r) {
    if (r->mti >= MT_N) {
        uint32_t *mt = r->mt;
        size_t kk;
        uint32_t y;
        for (kk = 0; kk < MT_N - MT_M; kk++) {
            y = (mt[kk] & 0x80000000u) | (mt[kk + 1] & 0x7fffffffu);
            mt[kk] = mt[kk + MT_M] ^ (y >> 1) ^ ((y & 1u) ? 0x9908b0dfu : 0u);
        }
        for (; kk < MT_N - 1; kk++) {
            y = (mt[kk] & 0x80000000u) | (mt[kk + 1] & 0x7fffffffu);
            mt[kk] = mt[kk + MT_M - MT_N] ^ (y >> 1) ^ ((y & 1u) ? 0x9908b0dfu : 0u);
        }
        y = (mt[MT_N - 1] & 0x80000000u) | (mt[0] & 0x7fffffffu);
        mt[MT_N - 1] = mt[MT_M - 1] ^ (y >> 1) ^ ((y & 1u) ? 0x9908b0dfu : 0u);
        r->mti = 0;
    }
    uint32_t y = r->mt[r->mti++];
    y ^= y >> 11;
    y ^= (y << 7) & 0x9d2c5680u;
    y ^= (y << 15) & 0xefc60000u;
    y ^= y >> 18;
    return y;
}

static inline double mt_random(Mt *r) {
    double a = (double)(mt_u32(r) >> 5);
    double b = (double)(mt_u32(r) >> 6);
    return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
}

static inline uint64_t mt_bits(Mt *r, unsigned k) {
    if (k <= 32) return (uint64_t)(mt_u32(r) >> (32 - k));
    uint64_t result = 0;
    unsigned remaining = k, shift = 0;
    while (remaining > 0) {
        uint32_t w = mt_u32(r);
        if (remaining < 32) w >>= 32 - remaining;
        result |= (uint64_t)w << shift;
        shift += 32;
        remaining = remaining > 32 ? remaining - 32 : 0;
    }
    return result;
}

static inline uint64_t mt_below(Mt *r, uint64_t n) {
    if (n == 0) return 0;
    unsigned k = 64 - (unsigned)__builtin_clzll(n);
    uint64_t x = mt_bits(r, k);
    while (x >= n) x = mt_bits(r, k);
    return x;
}

static inline size_t mt_range(Mt *r, size_t n) { return (size_t)mt_below(r, (uint64_t)n); }

#endif
