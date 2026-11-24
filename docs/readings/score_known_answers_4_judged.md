# The score's scale, its floor and its counted seeds, on known answers

Committed before any crossover was built or read: `gsd-score-known-answers-criterion-4` (2026-11-23T10:32:00Z). The score judged is `gsd-law-score-7`. A seed counts only where its chain stopped changing; a chain is read at a size only on a piece of at least 4,096 nodes and half the graph; a pair holds its scale when the reach grows as the d the score reads at the larger size, within q of that growth plus half a step of the reach at each size and two standard errors of the seeds' reach. Only a pair that holds its scale lets a probe settle or the Einstein relation hold.

q = 0.2, twice the widest training excess (0.0756, periodic_cubic_quotient from 262,144 to 1,048,576) on its grid, over 160 training pairs of `calibration/seed_table.json`.

## Judged on seeds 51 to 53, built and read for it

**It does not pass**: K1 56 of 56, K2 11 of 11, K3 16 of 16, K4 15 of 15, S1 4 of 9, S2 1 of 2, S3 2 of 2.

What missed:

* S1: periodic strip 16 nodes wide 4,096 to 16,384, reach 68 to 260, grows as d 1.0336 against d 1.1111 read
* S1: periodic strip 16 nodes wide 16,384 to 65,536, reach 260 to 1028, grows as d 1.0084 against d 1.0959 read
* S1: periodic tube 8 by 8 nodes across 4,096 to 16,384, reach 20 to 68, grows as d 1.1328 against d 1.0439 read
* S1: periodic tube 8 by 8 nodes across 16,384 to 65,536, reach 68 to 260, grows as d 1.0336 against d 1.0959 read
* S1: periodic tube 16 by 16 nodes across 16,384 to 65,536, reach 24 to 72, grows as d 1.2619 against d 1.213 read
* S2: uniform random tree, every edge a path of 8 4,097 to 16,385

## The crossovers, pair by pair

| structure | pair | judged | reach and d | points now | points without scale or floor |
|---|---|---|---|---|---|
| periodic strip 16 nodes wide | 4,096 to 16,384 | yes | reach 68 to 260, grows as d 1.0336 against d 1.1111 read | 2 | 2 |
| periodic strip 16 nodes wide | 16,384 to 65,536 | yes | reach 260 to 1028, grows as d 1.0084 against d 1.0959 read | 3 | 3 |
| periodic strip 32 nodes wide | 4,096 to 16,384 | yes | reach 40 to 136, grows as d 1.1328 against d 1.9949 read | 0 | 3 |
| periodic strip 32 nodes wide | 16,384 to 65,536 | yes | reach 136 to 520, grows as d 1.0336 against d 1.9949 read | 0 | 3 |
| periodic strip 48 nodes wide | 4,128 to 16,416 | reported | reach 33 to 97, grows as d 1.2803 against d 1.9733 read | 0 | 5 |
| periodic strip 48 nodes wide | 16,416 to 65,568 | yes | reach 97 to 353, grows as d 1.0721 against d 1.994 read | 0 | 4 |
| periodic strip 64 nodes wide | 4,096 to 16,384 | reported | reach 32 to 80, grows as d 1.5129 against d 2.0054 read | 0 | 5 |
| periodic strip 64 nodes wide | 16,384 to 65,536 | yes | reach 80 to 272, grows as d 1.1328 against d 1.9985 read | 0 | 5 |
| periodic tube 8 by 8 nodes across | 4,096 to 16,384 | yes | reach 20 to 68, grows as d 1.1328 against d 1.0439 read | 0 | 0 |
| periodic tube 8 by 8 nodes across | 16,384 to 65,536 | yes | reach 68 to 260, grows as d 1.0336 against d 1.0959 read | 2 | 2 |
| periodic tube 16 by 16 nodes across | 4,096 to 16,384 | reported | reach 12 to 24, grows as d 2 against d 2.7477 read | 0 | 2 |
| periodic tube 16 by 16 nodes across | 16,384 to 65,536 | yes | reach 24 to 72, grows as d 1.2619 against d 1.213 read | 0 | 0 |
| uniform random tree, every edge a path of 8 | 4,097 to 16,385 | reported | reach 190.879 to 492.355, grows as d 1.4628 against d 1.2976 read | 3 | 3 |
| uniform random tree, every edge a path of 8 | 16,385 to 65,537 | reported | reach 492.355 to 780.088, grows as d 3.0122 against d 1.3636 read | 0 | 2 |
| soup of cycles, the largest 6,144 nodes | 4,096 to 16,384 | reported | reach 1024 to 1536, grows as d 3.419 against d 0.9982 read, largest piece under half the graph | 0 | 5 |
| soup of cycles, the largest 6,144 nodes | 16,384 to 65,536 | reported | no growth of the reach, largest piece under half the graph | 0 | 5 |

## Criterion 3's structures under the scale

| structure | pair | reach and d | points now | points without scale or floor |
|---|---|---|---|---|
| 4D | 4,096 to 16,384 | reach 8 to 11, grows as d 4.3532 against d 3.8075 read | 2 | 2 |
| 4D | 16,384 to 65,536 | reach 11 to 16, grows as d 3.6998 against d 3.713 read | 3 | 3 |
| body-centred cubic | 4,096 to 16,384 | reach 10 to 16, grows as d 2.9495 against d 2.9068 read | 2 | 2 |
| body-centred cubic | 16,384 to 65,536 | reach 16 to 25, grows as d 3.1063 against d 2.9401 read | 5 | 5 |
| cubic | 4,096 to 16,384 | reach 12 to 18, grows as d 3.419 against d 2.8889 read | 3 | 3 |
| cubic | 16,384 to 65,536 | reach 18 to 29, grows as d 2.9067 against d 2.8931 read | 5 | 5 |
| face-centred cubic | 4,096 to 16,384 | reach 8 to 13, grows as d 2.8553 against d 2.8594 read | 2 | 2 |
| face-centred cubic | 16,384 to 65,536 | reach 13 to 21, grows as d 2.8907 against d 2.9252 read | 5 | 5 |
| honeycomb | 4,096 to 16,384 | reach 37 to 75, grows as d 1.962 against d 1.9675 read | 5 | 5 |
| honeycomb | 16,384 to 65,536 | reach 75 to 150, grows as d 2 against d 1.9956 read | 5 | 5 |
| preferential attachment, two links a node | 4,096 to 16,384 | no growth of the reach | 0 | 0 |
| random 3-regular graph | 4,096 to 16,384 | no growth of the reach | 0 | 0 |
| random geometric graph in three dimensions, mean degree 10 | 4,096 to 16,384 | reach 9.0443 to 14, grows as d 3.1728 against d 3.0853 read | 1 | 1 |
| random graph of mean degree 2.5 | 4,096 to 16,384 | no growth of the reach | 0 | 0 |
| ring | 4,096 to 16,384 | reach 1024 to 4096, grows as d 1 against d 1.0015 read | 5 | 5 |
| square | 4,096 to 16,384 | reach 32 to 64, grows as d 2 against d 1.9871 read | 5 | 5 |
| square | 16,384 to 65,536 | reach 64 to 128, grows as d 2 against d 1.9836 read | 5 | 5 |
| square lattice with 0.008 shortcuts a node | 4,096 to 16,384 | no growth of the reach | 0 | 0 |
| square lattice with chords within three steps | 4,096 to 16,384 | reach 26.3203 to 50.2396, grows as d 2.1444 against d 2.1211 read | 5 | 5 |
| triangular | 4,096 to 16,384 | reach 26 to 52, grows as d 2 against d 1.9643 read | 5 | 5 |
| triangular | 16,384 to 65,536 | reach 52 to 105, grows as d 1.9728 against d 1.9953 read | 5 | 5 |

Reported, not judged:

* periodic strip 48 nodes wide 4,128 to 16,416: a pair from a square or a cube, 0 points, reach 33 to 97, grows as d 1.2803 against d 1.9733 read
* periodic strip 64 nodes wide 4,096 to 16,384: a pair from a square or a cube, 0 points, reach 32 to 80, grows as d 1.5129 against d 2.0054 read
* periodic tube 16 by 16 nodes across 4,096 to 16,384: a pair from a square or a cube, 0 points, reach 12 to 24, grows as d 2 against d 2.7477 read

q is not judged fit `graph_scale_dynamics/resources/calibration/score_margins.json` (its reach block).
