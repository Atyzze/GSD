# The score's next step, on known answers written fresh

Committed before any of its structures was built or read: `gsd-score-known-answers-criterion-5` (2026-11-23T11:20:00Z), after criterion 4 missed (`docs/readings/score_known_answers_4_judged.md`). The score judged is `gsd-law-score-8`: criterion 4's counted seeds, connected piece and scale, and a pair whose next step breaks its scale settles nothing, because the dimension it read was a crossover on its way. A strip or a tube may settle only as the line it is at that size.

q = 0.2, trained as criterion 4 trained it, over 160 training pairs of `calibration/seed_table.json`.

## Judged on seeds 61 to 63, built and read for it

**It does not pass**: K1 56 of 56, K2 11 of 11, K3 16 of 16, K4 16 of 16, S1 9 of 9, S2 2 of 6, S3 3 of 3.

What missed:

* S2: uniform random tree, every edge a path of 8 4,097 to 16,385, d 1.36, reach 209.654 to 463.452, grows as d 1.7474 against d 1.3611 read
* S2: uniform random tree, every edge a path of 8 16,385 to 65,537, d 1.38, reach 463.452 to 937.137, grows as d 1.9687 against d 1.3839 read
* S2: uniform random tree, every edge a path of 16 4,097 to 16,385, d 1.12, reach 264.005 to 629.753, grows as d 1.5944 against d 1.122 read
* S2: uniform random tree, every edge a path of 16 16,385 to 65,537, d 1.18, reach 629.753 to 1364.75, grows as d 1.7924 against d 1.1799 read

## The crossovers, pair by pair

| structure | pair | judged | d read | reach and d | points now | without the next step | without scale or floor |
|---|---|---|---|---|---|---|---|
| periodic strip 24 nodes wide | 4,104 to 16,392 | yes | 1.21 | reach 49 to 177, grows as d 1.0783 against d 1.2097 read | 1 | 1 | 1 |
| periodic strip 24 nodes wide | 16,392 to 65,544 | yes | 1.16 | reach 177 to 689, grows as d 1.0197 against d 1.1638 read | 1 | 1 | 1 |
| periodic strip 40 nodes wide | 4,120 to 16,400 | yes | 1.97 | reach 36 to 112, grows as d 1.2171 against d 1.975 read | 0 | 0 | 5 |
| periodic strip 40 nodes wide | 16,400 to 65,560 | yes | 1.95 | reach 112 to 420, grows as d 1.0484 against d 1.954 read | 0 | 0 | 4 |
| periodic strip 56 nodes wide | 4,144 to 16,408 | reported | 1.97 | reach 32 to 87, grows as d 1.3759 against d 1.9726 read | 0 | 0 | 5 |
| periodic strip 56 nodes wide | 16,408 to 65,576 | yes | 2.0 | reach 87 to 307, grows as d 1.0987 against d 2.0036 read | 0 | 0 | 4 |
| periodic tube 6 by 6 nodes across | 4,104 to 16,416 | yes | 1.08 | reach 31 to 117, grows as d 1.0437 against d 1.0752 read | 2 | 2 | 2 |
| periodic tube 6 by 6 nodes across | 16,416 to 65,556 | yes | 1.07 | reach 117 to 458, grows as d 1.0146 against d 1.0658 read | 3 | 3 | 3 |
| periodic tube 12 by 12 nodes across | 4,176 to 16,416 | yes | 1.15 | reach 13 to 34, grows as d 1.4238 against d 1.1512 read | 0 | 0 | 0 |
| periodic tube 12 by 12 nodes across | 16,416 to 65,664 | yes | 1.11 | reach 34 to 120, grows as d 1.0992 against d 1.1124 read | 1 | 1 | 1 |
| uniform random tree, every edge a path of 4 | 4,097 to 16,385 | yes | none | no growth of the reach | 0 | 0 | 0 |
| uniform random tree, every edge a path of 4 | 16,385 to 65,537 | yes | 1.64 | reach 346.57 to 577, grows as d 2.7194 against d 1.6373 read | 0 | 0 | 0 |
| uniform random tree, every edge a path of 8 | 4,097 to 16,385 | yes | 1.36 | reach 209.654 to 463.452, grows as d 1.7474 against d 1.3611 read | 2 | 2 | 2 |
| uniform random tree, every edge a path of 8 | 16,385 to 65,537 | yes | 1.38 | reach 463.452 to 937.137, grows as d 1.9687 against d 1.3839 read | 2 | 2 | 2 |
| uniform random tree, every edge a path of 16 | 4,097 to 16,385 | yes | 1.12 | reach 264.005 to 629.753, grows as d 1.5944 against d 1.122 read | 3 | 3 | 3 |
| uniform random tree, every edge a path of 16 | 16,385 to 65,537 | yes | 1.18 | reach 629.753 to 1364.75, grows as d 1.7924 against d 1.1799 read | 1 | 1 | 1 |
| soup of cycles, the largest 6,144 nodes | 4,096 to 16,384 | yes | 0.99 | reach 1024 to 1536, grows as d 3.419 against d 0.9939 read, largest piece under half the graph | 0 | 0 | 5 |
| soup of cycles, the largest 6,144 nodes | 16,384 to 65,536 | yes | 1.0 | no growth of the reach, largest piece under half the graph | 0 | 0 | 5 |
| soup of cycles, the largest 12,288 nodes | 4,096 to 16,384 | reported | 1.0 | reach 1024 to 3072, grows as d 1.2619 against d 0.9999 read | 0 | 0 | 5 |
| soup of cycles, the largest 12,288 nodes | 16,384 to 65,536 | yes | 1.0 | no growth of the reach, largest piece under half the graph | 0 | 0 | 5 |

## Criterion 3's structures, on seeds 61 to 63

| structure | pair | reach and d | points now | without the next step | without scale or floor |
|---|---|---|---|---|---|
| 4D | 4,096 to 16,384 | reach 8 to 11, grows as d 4.3532 against d 3.8075 read | 2 | 2 | 2 |
| 4D | 16,384 to 65,536 | reach 11 to 16, grows as d 3.6998 against d 3.7141 read | 3 | 3 | 3 |
| body-centred cubic | 4,096 to 16,384 | reach 10 to 16, grows as d 2.9495 against d 2.9162 read | 2 | 2 | 2 |
| body-centred cubic | 16,384 to 65,536 | reach 16 to 25, grows as d 3.1063 against d 2.9404 read | 5 | 5 | 5 |
| cubic | 4,096 to 16,384 | reach 12 to 18, grows as d 3.419 against d 2.8947 read | 3 | 3 | 3 |
| cubic | 16,384 to 65,536 | reach 18 to 29, grows as d 2.9067 against d 2.8921 read | 5 | 5 | 5 |
| face-centred cubic | 4,096 to 16,384 | reach 8 to 13, grows as d 2.8553 against d 2.9077 read | 2 | 2 | 2 |
| face-centred cubic | 16,384 to 65,536 | reach 13 to 21, grows as d 2.8907 against d 2.9098 read | 5 | 5 | 5 |
| honeycomb | 4,096 to 16,384 | reach 37 to 75, grows as d 1.962 against d 1.9984 read | 5 | 5 | 5 |
| honeycomb | 16,384 to 65,536 | reach 75 to 150, grows as d 2 against d 1.9913 read | 5 | 5 | 5 |
| preferential attachment, two links a node | 4,096 to 16,384 | no growth of the reach | 0 | 0 | 0 |
| random 3-regular graph | 4,096 to 16,384 | no growth of the reach | 0 | 0 | 0 |
| random graph of mean degree 2.5 | 4,096 to 16,384 | no growth of the reach | 0 | 0 | 0 |
| ring | 4,096 to 16,384 | reach 1024 to 4096, grows as d 1 against d 1.0039 read | 5 | 5 | 5 |
| square | 4,096 to 16,384 | reach 32 to 64, grows as d 2 against d 1.989 read | 5 | 5 | 5 |
| square | 16,384 to 65,536 | reach 64 to 128, grows as d 2 against d 1.9908 read | 5 | 5 | 5 |
| square lattice with 0.008 shortcuts a node | 4,096 to 16,384 | no growth of the reach | 0 | 0 | 0 |
| square lattice with chords within three steps | 4,096 to 16,384 | reach 26.1797 to 50.2917, grows as d 2.1234 against d 2.1199 read | 5 | 5 | 5 |
| triangular | 4,096 to 16,384 | reach 26 to 52, grows as d 2 against d 2.0052 read | 5 | 5 | 5 |
| triangular | 16,384 to 65,536 | reach 52 to 105, grows as d 1.9728 against d 1.9875 read | 5 | 5 | 5 |

Reported, not judged:

* periodic strip 56 nodes wide 4,144 to 16,408: a pair from a square or a cube, 0 points, reach 32 to 87, grows as d 1.3759 against d 1.9726 read
* soup of cycles, the largest 12,288 nodes 4,096 to 16,384: its largest piece is half the graph or more at the larger size, 0 points, reach 1024 to 3072, grows as d 1.2619 against d 0.9999 read

It misses, so the score in force stays gsd-law-score-6, and the candidate is read beside it.
