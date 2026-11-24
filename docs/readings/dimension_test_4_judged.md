# The dimension test on its known answers

gsd-dimension-test-1; rule: from_n 1024, piece_at_least 0.95, degree_above 0.5, degree_below 15.5, sizes_at_least 2, sizes_fitted 3, reach_exponent_at_least 0.125, growth_agrees_within 0.4, d_step_within 0.75.

Passes: **yes**.

| part | family | expected | band | seeds right | d read | reach exponent | growth gap | Einstein gap | why not |
|---|---|---|---|---:|---|---|---|---|---|
| training | `rgg_2d` | dimensional | 1.5 to 2.5 | 3 of 3 | dim 2.06, dim 2.11, dim 2.09 | 0.47, 0.48, 0.47 | 0.03, 0.02, 0.02 | 0.19, 0.00, 0.04 |  |
| training | `rgg_3d` | dimensional | 2.5 to 3.5 | 3 of 3 | dim 3.17, dim 3.19, dim 3.13 | 0.31, 0.30, 0.30 | 0.04, 0.03, 0.05 | 0.27, 0.30, 0.30 |  |
| training | `rgg_4d` | dimensional | 3.0 to 5.0 | 3 of 3 | dim 4.29, dim 4.36, dim 4.27 | 0.24, 0.24, 0.24 | 0.03, 0.05, 0.03 | , ,  |  |
| training | `sierpinski` | dimensional | 1.085 to 2.085 | 3 of 3 | dim 1.54, dim 1.55, dim 1.53 | 0.63, 0.62, 0.63 | 0.03, 0.04, 0.05 | 0.06, 0.05, 0.08 |  |
| training | `ring` | dimensional | 0.5 to 1.5 | 3 of 3 | dim 0.99, dim 0.99, dim 0.99 | 1.00, 1.00, 1.00 | 0.01, 0.01, 0.01 | 0.02, 0.03, 0.03 |  |
| training | `cubic` | dimensional | 2.5 to 3.5 | 3 of 3 | dim 2.88, dim 2.89, dim 2.89 | 0.34, 0.34, 0.34 | 0.02, 0.02, 0.02 | 0.20, 0.09, 0.06 |  |
| training | `tesseract` | dimensional | 3.0 to 5.0 | 3 of 3 | dim 3.65, dim 3.63, dim 3.63 | 0.28, 0.28, 0.28 | 0.04, 0.03, 0.03 | , ,  |  |
| training | `honeycomb` | dimensional | 1.5 to 2.5 | 3 of 3 | dim 1.97, dim 1.97, dim 1.97 | 0.50, 0.50, 0.50 | 0.02, 0.02, 0.03 | 0.08, 0.09, 0.02 |  |
| training | `erdos_renyi_4` | not_dimensional |  | 3 of 3 | not, not, not | 0.10, 0.12, 0.11 | , ,  | , ,  |  |
| training | `random_regular_6` | not_dimensional |  | 3 of 3 | not, not, not | 0.15, 0.15, 0.15 | , ,  | , ,  |  |
| training | `ring_with_chords` | not_dimensional |  | 3 of 3 | not, not, not | 0.19, 0.18, 0.17 | , ,  | , ,  |  |
| training | `subdivided_regular` | not_dimensional |  | 3 of 3 | not, not, not | 0.16, 0.16, 0.16 | , ,  | , ,  |  |
| training | `preferential_attachment` | not_dimensional |  | 3 of 3 | not, not, not | 0.07, 0.09, 0.08 | , ,  | , ,  |  |
| held_out | `rgg_2d_sparse` | dimensional | 1.5 to 2.5 | 3 of 3 | dim 1.87, dim 1.93, dim 1.76 | 0.43, 0.43, 0.42 | 0.24, 0.20, 0.34 | , , 0.09 |  |
| held_out | `rgg_3d_dense` | dimensional | 2.5 to 3.5 | 3 of 3 | dim 3.16, dim 3.15, dim 3.15 | 0.32, 0.31, 0.31 | 0.00, 0.01, 0.01 | 0.14, 0.38, 0.16 |  |
| held_out | `percolation_2d` | dimensional | 1.396 to 2.396 | 3 of 3 | dim 1.52, dim 1.55, dim 1.57 | 0.66, 0.64, 0.85 | 0.00, 0.01, 0.25 | 0.04, 0.05, 0.04 |  |
| held_out | `random_tree` | dimensional | 1.5 to 2.5 | 3 of 3 | dim 2.03, dim 1.96, dim 1.82 | 0.62, 0.47, 0.53 | 0.21, 0.09, 0.03 | , , 0.04 |  |
| held_out | `random_regular_3` | not_dimensional |  | 3 of 3 | not, not, not | 0.14, 0.13, 0.14 | , ,  | , ,  |  |
| held_out | `erdos_renyi_8` | not_dimensional |  | 3 of 3 | not, not, not | 0.10, 0.11, 0.10 | , ,  | , ,  |  |
| held_out | `ring_with_chords_dense` | not_dimensional |  | 3 of 3 | not, not, not | 0.14, 0.15, 0.15 | , ,  | , ,  |  |
| held_out | `subdivided_regular_long` | not_dimensional |  | 3 of 3 | not, not, not | 0.17, 0.17, 0.17 | , ,  | , ,  |  |
| held_out | `preferential_attachment_3` | not_dimensional |  | 3 of 3 | not, not, not | 0.08, 0.08, 0.10 | , ,  | , ,  |  |
