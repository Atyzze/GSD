# What settles means, on known answers

The score's definitions, committed before they were read: `gsd-score-known-answers-criterion-3` (2026-11-19T22:42:43Z). A probe settles at two sizes from 4,096, the larger at least three times the smaller, when its relative step is within its margin at the larger size; all four agree by the Einstein relation when all four settle and d_s is within tau of 2 d_V / d_w and of 2 d_B / d_w. Each margin is twice the widest step of the calibration table's exact lattices and fractals, three seeds a mean, on its grid; tau the smallest value of its grid above every training residual. Trained on `calibration/seed_table.json`, estimator e639334808716378.

## Judged on seeds 51 to 53, built and read for it

**It passes**: K1 72 of 72, K2 15 of 15, K3 20 of 20, K4 16 of 16. A held probe that did not read at both sizes is the probes' to judge, reported here, not a miss of the score.

| probe | 16,384 | 65,536 | 262,144 | 1,048,576 | 4,194,304 |
|---|---|---|---|---|---|
| d_s | 0.06 | 0.1 | 0.06 | 0.02 | 0.02 |
| d_V | 0.15 | 0.03 | 0.05 | 0.02 | 0.02 |
| d_B | 0.08 | 0.05 | 0.08 | 0.03 | 0.03 |
| d_w | 0.05 | 0.08 | 0.05 | 0.03 | 0.03 |

The Einstein relation's tolerance tau: 0.075 of d_s.

## Where each exact structure of the table first reaches five points

| family | first pair's larger size |
|---|---|
| periodic_body_centred_cubic_lattice | 65,536 |
| periodic_cubic_lattice | 64,000 |
| periodic_cubic_quotient | 65,536 |
| periodic_face_centred_cubic_lattice | 65,536 |
| periodic_honeycomb_lattice | 16,384 |
| periodic_hypercubic_lattice_4d | 331,776 |
| periodic_ring | 16,384 |
| periodic_square_lattice | 16,384 |
| periodic_tesseract_quotient | 262,144 |
| periodic_triangular_lattice | 16,384 |
| sierpinski_carpet | 262,144 |
| sierpinski_gasket | 88,575 |

No table family failed to settle under the margins its own steps set, and none broke tau (0 steps above a margin, 0 residuals above tau, of 249 steps and 84 residuals).

## Under 4,096 nodes: kept, not relied on

What the pair from about 1,024 to 4,096 would have given each table family under the 16,384 margins:

* periodic_a4_lattice: 0 of 5 (nothing settles)
* periodic_body_centred_cubic_lattice: 2 of 5 (d_s, d_V)
* periodic_cubic_lattice: 2 of 5 (d_s, d_V)
* periodic_cubic_quotient: 2 of 5 (d_s, d_V)
* periodic_d4_lattice: 0 of 5 (nothing settles)
* periodic_face_centred_cubic_lattice: 2 of 5 (d_s, d_V)
* periodic_honeycomb_lattice: 5 of 5 (d_s, d_V, d_B, d_w)
* periodic_hypercubic_lattice_4d: 2 of 5 (d_s, d_V)
* periodic_ring: 5 of 5 (d_s, d_V, d_B, d_w)
* periodic_square_lattice: 5 of 5 (d_s, d_V, d_B, d_w)
* periodic_tesseract_quotient: 2 of 5 (d_s, d_V)
* periodic_triangular_lattice: 5 of 5 (d_s, d_V, d_B, d_w)
* sierpinski_carpet: 3 of 5 (d_V, d_B, d_w)
* sierpinski_gasket: 5 of 5 (d_s, d_V, d_B, d_w)
* uniform_random_tree: 2 of 5 (d_V, d_B)

The score reads these margins (`graph_scale_dynamics/resources/calibration/score_margins.json`).
