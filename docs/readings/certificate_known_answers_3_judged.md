# Every chain its own count, on series whose answer is known

gsd-certificate-known-answers-2, against `gsd-certificate-known-answers-criterion-3`, committed before any rung was drawn. Each chain of a rung is its own AR(1) series of 240 points, read by the count every chain runs (the smaller of the windowed sum and the 8-batch means, on its late 60%); the rung's count is the smallest. Beside it, the count on the chain from empty alone, which cannot see a starved chain.

K1: a rung whose every chain has at most T/8 true samples is certified at most 5% of the time. K2: a rung whose every chain has at least 4T, at least 95%. K3: a rung one of whose chains has at most T/8 and every other 4T, at most 5%.

## Asked for 8 effective samples

| chains | K1 worst | K2 worst | K3 worst | K3 by the chain from empty alone | verdict |
|---:|---:|---:|---:|---:|---|
| 2 | 40.5% (missed) | 100.0% (held) | 64.2% (missed) | 100.0% (missed) | not fit |
| 8 | 2.3% (held) | 100.0% (held) | 61.6% (missed) | 100.0% (missed) | not fit |

Share of rungs certified, by true samples of every chain (one chain alone beside):

| chains | 0.25 | 0.5 | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 28.0% | 30.9% | 40.5% | 57.4% | 77.0% | 93.0% | 99.6% | 100.0% | 100.0% | 100.0% |
| 8 | 0.9% | 0.8% | 2.3% | 9.2% | 34.9% | 75.2% | 97.2% | 100.0% | 100.0% | 100.0% |
| 1 | 52.3% | 55.4% | 63.4% | 75.7% | 87.7% | 96.5% | 99.8% | 100.0% | 100.0% | 100.0% |

## Asked for 16 effective samples

| chains | K1 worst | K2 worst | K3 worst | K3 by the chain from empty alone | verdict |
|---:|---:|---:|---:|---:|---|
| 2 | 0.2% (held) | 99.7% (held) | 4.8% (held) | 99.8% (missed) | fit |
| 8 | 0.0% (held) | 98.6% (held) | 5.0% (held) | 99.8% (missed) | fit |

Share of rungs certified, by true samples of every chain (one chain alone beside):

| chains | 0.25 | 0.5 | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 0.1% | 0.0% | 0.1% | 0.2% | 1.2% | 11.5% | 58.5% | 94.5% | 99.7% | 100.0% |
| 8 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 10.0% | 80.8% | 98.6% | 100.0% |
| 1 | 1.9% | 1.8% | 2.9% | 4.6% | 10.4% | 33.7% | 76.5% | 97.2% | 99.8% | 100.0% |

Every chain's own count is fit at 16.
