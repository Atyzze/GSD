# The engines' chains against exact Boltzmann measures

gsd-boltzmann-known-answers-1: on every graph of 4 and of 5 nodes the engine's own energy gives the exact measure of a law at a finite temperature. Each run starts one chain at a graph drawn from that measure and one at the empty graph, and the graphs the chains end on are counted against the measure (a chi-square on the graphs, the rare ones pooled). A chain that keeps the measure ends distributed as it started, however long it ran, so the given chain tests the balance of the moves without assuming the chain mixed; the chain from empty tests that the measure is reached from empty. A count agrees when its p is at least 2.69e-05, which is 1% shared over the 372 counts judged.

* K1, the measure is kept: **260 of 260** cells (held).
* K2, the measure is reached from empty: **112 of 112** cells (held).
* K3, the energies agree: the engines (python, rust) differ by at most 0 of the largest energy on 71,808 graphs, the two orders of a graph's edges by at most 2.22e-16, and 0 chain ends carried an energy that was not their graph's (held).
* K4, every kind of move is taken: python: 8,588,910 local toggles, 5,914,779 other toggles, 612,553 swaps accepted; rust: 17,177,188 local toggles, 11,828,696 other toggles, 1,224,227 swaps accepted (held).

The criterion passes.

## By term

| term | cells | kept | reached from empty |
|---|---:|---:|---:|
| `edge_count` | 20 | 20 of 20 | 8 of 8 |
| `degree_anchor` | 32 | 32 of 32 | 8 of 8 |
| `degree_square_sum` | 16 | 16 of 16 | 8 of 8 |
| `wedge_count` | 20 | 20 of 20 | 8 of 8 |
| `triangle_count` | 20 | 20 of 20 | 8 of 8 |
| `triangle_edge_overlap` | 28 | 28 of 28 | 8 of 8 |
| `square_count` | 32 | 32 of 32 | 8 of 8 |
| `square_edge_overlap` | 20 | 20 of 20 | 8 of 8 |
| `induced_square_count` | 20 | 20 of 20 | 8 of 8 |
| `degree_neighbor_gradient` | 24 | 24 of 24 | 8 of 8 |
| `degree_anchor_abs` | 24 | 24 of 24 | 8 of 8 |
| `degree_cube_sum` | 16 | 16 of 16 | 8 of 8 |
| `degree_fourth_sum` | 24 | 24 of 24 | 8 of 8 |
| `ollivier_curvature` | 16 | 16 of 16 | 8 of 8 |

## What the count can tell apart

The same counts read against a wrong measure, the law's energies multiplied by a factor:

| factor on the energies | cells refusing the wrong measure |
|---:|---:|
| 1.25 | 77 of 260 |
| 1.5 | 163 of 260 |
| 2 | 221 of 260 |

## The controls

A control's chain runs at its own beta and is judged against the law's measure at beta 1; the last column reads the same count against the measure its chain keeps, the energies multiplied by its beta.

| law | nodes | engine | its chain's beta | expected | kept | p | right | p at its chain's beta |
|---|---:|---|---:|---|---|---:|---|---:|
| `the_tree_s_law_toggle` | 4 | python | 1 | kept | kept | 0.177 | right | 0.177 |
| `the_tree_s_law_toggle` | 5 | python | 1 | kept | kept | 0.383 | right | 0.383 |
| `the_tree_s_law_at_twice_its_energy` | 4 | python | 2 | refused | refused | 2.78e-167 | right | 0.946 |
| `the_tree_s_law_at_twice_its_energy` | 5 | python | 2 | refused | refused | 0 | right | 0.182 |
| `the_tree_s_law_toggle` | 4 | rust | 1 | kept | kept | 0.333 | right | 0.333 |
| `the_tree_s_law_toggle` | 5 | rust | 1 | kept | kept | 0.961 | right | 0.961 |
| `the_tree_s_law_at_twice_its_energy` | 4 | rust | 2 | refused | refused | 0 | right | 0.348 |
| `the_tree_s_law_at_twice_its_energy` | 5 | rust | 2 | refused | refused | 0 | right | 0.326 |

## The cells that missed

None.

## Every cell

| law | nodes | engine | runs | locality | swap share | energy span | given p | from empty p | runs that moved |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `alone_edge_count_1` | 4 | python | 1,000 | 0.554768 | 0.135875 | 3.68 | 0.0994 | 0.447 | 1,000 |
| `alone_edge_count_1` | 5 | python | 1,000 | 0.554768 | 0.135875 | 3.68 | 0.476 | 0.106 | 1,000 |
| `alone_edge_count_2` | 4 | python | 1,000 | 0.732151 | 0.181247 | 3.86 | 0.976 | 0.0302 | 1,000 |
| `alone_edge_count_2` | 5 | python | 1,000 | 0.732151 | 0.181247 | 3.86 | 0.93 | 0.235 | 1,000 |
| `alone_degree_anchor_1` | 4 | python | 1,000 | 0.520215 | 0.023149 | 2.45 | 0.215 | 0.217 | 1,000 |
| `alone_degree_anchor_1` | 5 | python | 1,000 | 0.520215 | 0.023149 | 2.45 | 0.687 | 0.821 | 1,000 |
| `alone_degree_anchor_2` | 4 | python | 1,000 | 0.849294 | 0.537768 | 3.18 | 0.799 | 0.275 | 1,000 |
| `alone_degree_anchor_2` | 5 | python | 1,000 | 0.849294 | 0.537768 | 3.18 | 0.403 | 0.27 | 1,000 |
| `alone_degree_square_sum_1` | 4 | python | 1,000 | 0.152668 | 0.066786 | 3.03 | 0.537 | 0.966 | 1,000 |
| `alone_degree_square_sum_1` | 5 | python | 1,000 | 0.152668 | 0.066786 | 3.03 | 0.464 | 0.56 | 1,000 |
| `alone_degree_square_sum_2` | 4 | python | 1,000 | 0.129912 | 0.284192 | 3.19 | 0.314 | 0.137 | 1,000 |
| `alone_degree_square_sum_2` | 5 | python | 1,000 | 0.129912 | 0.284192 | 3.19 | 0.467 | 0.734 | 1,000 |
| `alone_wedge_count_1` | 4 | python | 1,000 | 0.666038 | 0.293808 | 5.44 | 0.144 | 0.536 | 1,000 |
| `alone_wedge_count_1` | 5 | python | 1,000 | 0.666038 | 0.293808 | 5.44 | 0.723 | 0.938 | 1,000 |
| `alone_wedge_count_2` | 4 | python | 1,000 | 0.897581 | 0.288812 | 3.05 | 0.417 | 0.798 | 1,000 |
| `alone_wedge_count_2` | 5 | python | 1,000 | 0.897581 | 0.288812 | 3.05 | 0.0801 | 0.212 | 1,000 |
| `alone_triangle_count_1` | 4 | python | 1,000 | 0.114144 | 0.205276 | 2.74 | 0.828 | 0.638 | 1,000 |
| `alone_triangle_count_1` | 5 | python | 1,000 | 0.114144 | 0.205276 | 2.74 | 0.125 | 0.438 | 1,000 |
| `alone_triangle_count_2` | 4 | python | 1,000 | 0.678171 | 0.327516 | 4.44 | 0.411 | 0.999 | 1,000 |
| `alone_triangle_count_2` | 5 | python | 1,000 | 0.678171 | 0.327516 | 4.44 | 0.856 | 0.0646 | 1,000 |
| `alone_triangle_edge_overlap_1` | 4 | python | 1,000 | 0.847064 | 0.447959 | 5.65 | 0.887 | 0.963 | 1,000 |
| `alone_triangle_edge_overlap_1` | 5 | python | 1,000 | 0.847064 | 0.447959 | 5.65 | 0.923 | 0.408 | 1,000 |
| `alone_triangle_edge_overlap_2` | 4 | python | 1,000 | 0.114473 | 0.528528 | 3.94 | 0.662 | 0.242 | 1,000 |
| `alone_triangle_edge_overlap_2` | 5 | python | 1,000 | 0.114473 | 0.528528 | 3.94 | 0.983 | 0.375 | 1,000 |
| `alone_square_count_1` | 4 | python | 1,000 | 0.866417 | 0.401032 | 2.84 | 0.953 | 0.237 | 1,000 |
| `alone_square_count_1` | 5 | python | 1,000 | 0.866417 | 0.401032 | 2.84 | 0.57 | 0.0596 | 1,000 |
| `alone_square_count_2` | 4 | python | 1,000 | 0.884025 | 0.002932 | 3.03 | 0.304 | 0.954 | 1,000 |
| `alone_square_count_2` | 5 | python | 1,000 | 0.884025 | 0.002932 | 3.03 | 0.204 | 0.299 | 1,000 |
| `alone_square_edge_overlap_1` | 4 | python | 1,000 | 0.419413 | 0.849612 | 2.66 | 0.923 | 0.773 | 1,000 |
| `alone_square_edge_overlap_1` | 5 | python | 1,000 | 0.419413 | 0.849612 | 2.66 | 0.325 | 0.131 | 1,000 |
| `alone_square_edge_overlap_2` | 4 | python | 1,000 | 0.653947 | 0.34559 | 4.43 | 0.868 | 0.025 | 1,000 |
| `alone_square_edge_overlap_2` | 5 | python | 1,000 | 0.653947 | 0.34559 | 4.43 | 0.935 | 0.794 | 1,000 |
| `alone_induced_square_count_1` | 4 | python | 1,000 | 0.729669 | 0.308882 | 3.29 | 0.159 | 0.528 | 1,000 |
| `alone_induced_square_count_1` | 5 | python | 1,000 | 0.729669 | 0.308882 | 3.29 | 0.411 | 0.959 | 1,000 |
| `alone_induced_square_count_2` | 4 | python | 1,000 | 0.594491 | 0.352436 | 2.72 | 0.766 | 0.382 | 1,000 |
| `alone_induced_square_count_2` | 5 | python | 1,000 | 0.594491 | 0.352436 | 2.72 | 0.704 | 0.287 | 1,000 |
| `alone_degree_neighbor_gradient_1` | 4 | python | 1,000 | 0.364839 | 0.97075 | 3.65 | 0.548 | 1.35e-18 | 995 |
| `alone_degree_neighbor_gradient_1` | 5 | python | 1,000 | 0.364839 | 0.97075 | 3.65 | 0.189 | 7.29e-97 | 1,000 |
| `alone_degree_neighbor_gradient_2` | 4 | python | 1,000 | 0.633733 | 0.572771 | 5.03 | 0.147 | 0.167 | 1,000 |
| `alone_degree_neighbor_gradient_2` | 5 | python | 1,000 | 0.633733 | 0.572771 | 5.03 | 0.111 | 0.29 | 1,000 |
| `alone_degree_anchor_abs_1` | 4 | python | 1,000 | 0.896993 | 0.879043 | 2.36 | 0.46 | 1.18e-76 | 980 |
| `alone_degree_anchor_abs_1` | 5 | python | 1,000 | 0.896993 | 0.879043 | 2.36 | 0.367 | 0 | 998 |
| `alone_degree_anchor_abs_2` | 4 | python | 1,000 | 0.60079 | 0.332857 | 2.59 | 0.751 | 0.798 | 1,000 |
| `alone_degree_anchor_abs_2` | 5 | python | 1,000 | 0.60079 | 0.332857 | 2.59 | 0.836 | 0.667 | 1,000 |
| `alone_degree_cube_sum_1` | 4 | python | 1,000 | 0.144085 | 0.091615 | 2.87 | 0.279 | 0.98 | 1,000 |
| `alone_degree_cube_sum_1` | 5 | python | 1,000 | 0.144085 | 0.091615 | 2.87 | 0.741 | 0.571 | 1,000 |
| `alone_degree_cube_sum_2` | 4 | python | 1,000 | 0.302163 | 0.483334 | 4.34 | 0.91 | 0.991 | 1,000 |
| `alone_degree_cube_sum_2` | 5 | python | 1,000 | 0.302163 | 0.483334 | 4.34 | 0.103 | 0.233 | 1,000 |
| `alone_degree_fourth_sum_1` | 4 | python | 1,000 | 0.023484 | 0.318097 | 3.91 | 0.767 | 0.968 | 1,000 |
| `alone_degree_fourth_sum_1` | 5 | python | 1,000 | 0.023484 | 0.318097 | 3.91 | 0.11 | 0.132 | 1,000 |
| `alone_degree_fourth_sum_2` | 4 | python | 1,000 | 0.874808 | 0.977859 | 2.24 | 0.973 | 0 | 912 |
| `alone_degree_fourth_sum_2` | 5 | python | 1,000 | 0.874808 | 0.977859 | 2.24 | 0.819 | 0 | 993 |
| `alone_ollivier_curvature_1` | 4 | python | 1,000 | 0.458721 | 0.030501 | 5.99 | 0.436 | 0.535 | 1,000 |
| `alone_ollivier_curvature_1` | 5 | python | 1,000 | 0.458721 | 0.030501 | 5.99 | 0.541 | 0.453 | 1,000 |
| `alone_ollivier_curvature_2` | 4 | python | 1,000 | 0.981955 | 0.701006 | 5.17 | 0.22 | 0 | 995 |
| `alone_ollivier_curvature_2` | 5 | python | 1,000 | 0.981955 | 0.701006 | 5.17 | 0.653 | 0 | 999 |
| `mixed_1` | 4 | python | 1,000 | 0.856685 | 0.74857 | 1.83 | 0.333 | 0.241 | 1,000 |
| `mixed_1` | 5 | python | 1,000 | 0.856685 | 0.74857 | 2.21 | 0.813 | 0.234 | 1,000 |
| `mixed_2` | 4 | python | 1,000 | 0.740276 | 0.882352 | 1.96 | 0.349 | 0.373 | 1,000 |
| `mixed_2` | 5 | python | 1,000 | 0.740276 | 0.882352 | 1.96 | 0.218 | 0.00953 | 1,000 |
| `mixed_3` | 4 | python | 1,000 | 0.289847 | 0.132823 | 1.98 | 0.933 | 0.448 | 1,000 |
| `mixed_3` | 5 | python | 1,000 | 0.289847 | 0.132823 | 2.19 | 0.762 | 0.542 | 1,000 |
| `mixed_4` | 4 | python | 1,000 | 0.126608 | 0.478348 | 2.73 | 0.252 | 0.0742 | 1,000 |
| `mixed_4` | 5 | python | 1,000 | 0.126608 | 0.478348 | 2.58 | 0.402 | 0.688 | 1,000 |
| `mixed_5` | 4 | python | 1,000 | 0.570437 | 0.959296 | 1.26 | 0.0765 | 3.74e-164 | 998 |
| `mixed_5` | 5 | python | 1,000 | 0.570437 | 0.959296 | 1.22 | 0.0285 | 3.19e-251 | 1,000 |
| `mixed_6` | 4 | python | 1,000 | 0.860047 | 0.280454 | 0.95 | 0.565 | 0.889 | 1,000 |
| `mixed_6` | 5 | python | 1,000 | 0.860047 | 0.280454 | 0.92 | 0.931 | 0.176 | 1,000 |
| `mixed_7` | 4 | python | 1,000 | 0.623038 | 0.826645 | 0.23 | 0.788 | 0.869 | 1,000 |
| `mixed_7` | 5 | python | 1,000 | 0.623038 | 0.826645 | 0.31 | 0.296 | 0.797 | 1,000 |
| `mixed_8` | 4 | python | 1,000 | 0.534503 | 0.926362 | 1.78 | 0.233 | 0.438 | 1,000 |
| `mixed_8` | 5 | python | 1,000 | 0.534503 | 0.926362 | 1.67 | 0.00815 | 0.498 | 1,000 |
| `reach_edge_count_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 3.68 | 0.532 | 0.532 | 1,000 |
| `reach_edge_count_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 3.68 | 0.548 | 0.882 | 1,000 |
| `reach_edge_count_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 3.68 | 0.577 | 0.643 | 1,000 |
| `reach_edge_count_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 3.68 | 0.893 | 0.501 | 1,000 |
| `reach_degree_anchor_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 2.45 | 0.237 | 0.319 | 1,000 |
| `reach_degree_anchor_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 2.45 | 0.93 | 0.912 | 1,000 |
| `reach_degree_anchor_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 2.45 | 0.598 | 0.885 | 1,000 |
| `reach_degree_anchor_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 2.45 | 0.00789 | 0.701 | 1,000 |
| `reach_degree_square_sum_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 3.03 | 0.467 | 0.609 | 1,000 |
| `reach_degree_square_sum_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 3.03 | 0.865 | 0.094 | 1,000 |
| `reach_degree_square_sum_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 3.03 | 0.201 | 0.877 | 1,000 |
| `reach_degree_square_sum_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 3.03 | 0.486 | 0.221 | 1,000 |
| `reach_wedge_count_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 5.44 | 0.187 | 0.443 | 1,000 |
| `reach_wedge_count_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 5.44 | 0.564 | 0.898 | 1,000 |
| `reach_wedge_count_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 5.44 | 0.486 | 0.119 | 1,000 |
| `reach_wedge_count_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 5.44 | 0.0368 | 0.937 | 1,000 |
| `reach_triangle_count_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 2.74 | 0.445 | 0.0696 | 1,000 |
| `reach_triangle_count_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 2.74 | 0.274 | 0.657 | 1,000 |
| `reach_triangle_count_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 2.74 | 0.834 | 0.909 | 1,000 |
| `reach_triangle_count_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 2.74 | 0.977 | 0.076 | 1,000 |
| `reach_triangle_edge_overlap_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 5.65 | 0.58 | 0.765 | 1,000 |
| `reach_triangle_edge_overlap_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 5.65 | 0.0435 | 0.614 | 1,000 |
| `reach_triangle_edge_overlap_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 5.65 | 0.875 | 0.375 | 1,000 |
| `reach_triangle_edge_overlap_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 5.65 | 0.779 | 0.828 | 1,000 |
| `reach_square_count_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 2.84 | 0.516 | 0.801 | 1,000 |
| `reach_square_count_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 2.84 | 0.0993 | 0.758 | 1,000 |
| `reach_square_count_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 2.84 | 0.575 | 0.0328 | 1,000 |
| `reach_square_count_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 2.84 | 0.695 | 0.353 | 1,000 |
| `reach_square_edge_overlap_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 2.66 | 0.5 | 0.865 | 1,000 |
| `reach_square_edge_overlap_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 2.66 | 0.322 | 0.288 | 1,000 |
| `reach_square_edge_overlap_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 2.66 | 0.0648 | 0.987 | 1,000 |
| `reach_square_edge_overlap_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 2.66 | 0.494 | 0.549 | 1,000 |
| `reach_induced_square_count_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 3.29 | 0.795 | 0.125 | 1,000 |
| `reach_induced_square_count_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 3.29 | 0.414 | 0.253 | 1,000 |
| `reach_induced_square_count_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 3.29 | 0.729 | 0.602 | 1,000 |
| `reach_induced_square_count_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 3.29 | 0.781 | 0.483 | 1,000 |
| `reach_degree_neighbor_gradient_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 3.65 | 0.582 | 0.317 | 1,000 |
| `reach_degree_neighbor_gradient_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 3.65 | 0.446 | 0.0391 | 1,000 |
| `reach_degree_neighbor_gradient_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 3.65 | 0.198 | 0.0303 | 1,000 |
| `reach_degree_neighbor_gradient_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 3.65 | 0.341 | 0.14 | 1,000 |
| `reach_degree_anchor_abs_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 2.36 | 0.897 | 0.623 | 1,000 |
| `reach_degree_anchor_abs_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 2.36 | 0.305 | 0.336 | 1,000 |
| `reach_degree_anchor_abs_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 2.36 | 0.685 | 0.117 | 1,000 |
| `reach_degree_anchor_abs_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 2.36 | 0.359 | 0.428 | 1,000 |
| `reach_degree_cube_sum_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 2.87 | 0.841 | 0.325 | 1,000 |
| `reach_degree_cube_sum_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 2.87 | 0.689 | 0.847 | 1,000 |
| `reach_degree_cube_sum_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 2.87 | 0.562 | 0.893 | 1,000 |
| `reach_degree_cube_sum_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 2.87 | 0.00215 | 0.686 | 1,000 |
| `reach_degree_fourth_sum_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 3.91 | 0.769 | 0.816 | 1,000 |
| `reach_degree_fourth_sum_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 3.91 | 0.211 | 0.857 | 1,000 |
| `reach_degree_fourth_sum_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 3.91 | 0.989 | 0.709 | 1,000 |
| `reach_degree_fourth_sum_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 3.91 | 0.445 | 0.56 | 1,000 |
| `reach_ollivier_curvature_locality_0` | 4 | python | 1,000 | 0 | 0.15 | 5.99 | 0.425 | 0.172 | 1,000 |
| `reach_ollivier_curvature_locality_0` | 5 | python | 1,000 | 0 | 0.15 | 5.99 | 0.819 | 0.446 | 1,000 |
| `reach_ollivier_curvature_locality_0.5` | 4 | python | 1,000 | 0.5 | 0.15 | 5.99 | 0.363 | 0.217 | 1,000 |
| `reach_ollivier_curvature_locality_0.5` | 5 | python | 1,000 | 0.5 | 0.15 | 5.99 | 0.693 | 0.296 | 1,000 |
| `the_tree_s_law_toggle` | 4 | python | 1,000 | 0.7 | 0.1 | 2.60 | 0.177 | 0.174 | 1,000 |
| `the_tree_s_law_toggle` | 5 | python | 1,000 | 0.7 | 0.1 | 6.80 | 0.383 | 0.609 | 1,000 |
| `the_tree_s_law_at_twice_its_energy` | 4 | python | 1,000 | 0.7 | 0.1 | 2.60 | 2.78e-167 | 5.08e-165 | 1,000 |
| `the_tree_s_law_at_twice_its_energy` | 5 | python | 1,000 | 0.7 | 0.1 | 6.80 | 0 | 0 | 1,000 |
| `alone_edge_count_1` | 4 | rust | 2,000 | 0.554768 | 0.135875 | 3.68 | 0.0333 | 0.969 | 2,000 |
| `alone_edge_count_1` | 5 | rust | 2,000 | 0.554768 | 0.135875 | 3.68 | 0.204 | 0.957 | 2,000 |
| `alone_edge_count_2` | 4 | rust | 2,000 | 0.732151 | 0.181247 | 3.86 | 0.658 | 0.0971 | 2,000 |
| `alone_edge_count_2` | 5 | rust | 2,000 | 0.732151 | 0.181247 | 3.86 | 0.985 | 0.496 | 2,000 |
| `alone_degree_anchor_1` | 4 | rust | 2,000 | 0.520215 | 0.023149 | 2.45 | 0.32 | 0.294 | 2,000 |
| `alone_degree_anchor_1` | 5 | rust | 2,000 | 0.520215 | 0.023149 | 2.45 | 0.456 | 0.215 | 2,000 |
| `alone_degree_anchor_2` | 4 | rust | 2,000 | 0.849294 | 0.537768 | 3.18 | 0.515 | 0.164 | 2,000 |
| `alone_degree_anchor_2` | 5 | rust | 2,000 | 0.849294 | 0.537768 | 3.18 | 0.66 | 0.0217 | 2,000 |
| `alone_degree_square_sum_1` | 4 | rust | 2,000 | 0.152668 | 0.066786 | 3.03 | 0.964 | 0.22 | 2,000 |
| `alone_degree_square_sum_1` | 5 | rust | 2,000 | 0.152668 | 0.066786 | 3.03 | 0.312 | 0.217 | 2,000 |
| `alone_degree_square_sum_2` | 4 | rust | 2,000 | 0.129912 | 0.284192 | 3.19 | 0.723 | 0.447 | 2,000 |
| `alone_degree_square_sum_2` | 5 | rust | 2,000 | 0.129912 | 0.284192 | 3.19 | 0.806 | 0.938 | 2,000 |
| `alone_wedge_count_1` | 4 | rust | 2,000 | 0.666038 | 0.293808 | 5.44 | 0.936 | 0.22 | 2,000 |
| `alone_wedge_count_1` | 5 | rust | 2,000 | 0.666038 | 0.293808 | 5.44 | 0.14 | 0.27 | 2,000 |
| `alone_wedge_count_2` | 4 | rust | 2,000 | 0.897581 | 0.288812 | 3.05 | 0.187 | 0.529 | 2,000 |
| `alone_wedge_count_2` | 5 | rust | 2,000 | 0.897581 | 0.288812 | 3.05 | 0.547 | 0.706 | 2,000 |
| `alone_triangle_count_1` | 4 | rust | 2,000 | 0.114144 | 0.205276 | 2.74 | 0.616 | 0.307 | 2,000 |
| `alone_triangle_count_1` | 5 | rust | 2,000 | 0.114144 | 0.205276 | 2.74 | 0.935 | 0.115 | 2,000 |
| `alone_triangle_count_2` | 4 | rust | 2,000 | 0.678171 | 0.327516 | 4.44 | 0.768 | 0.806 | 2,000 |
| `alone_triangle_count_2` | 5 | rust | 2,000 | 0.678171 | 0.327516 | 4.44 | 0.145 | 0.758 | 2,000 |
| `alone_triangle_edge_overlap_1` | 4 | rust | 2,000 | 0.847064 | 0.447959 | 5.65 | 0.427 | 0.559 | 2,000 |
| `alone_triangle_edge_overlap_1` | 5 | rust | 2,000 | 0.847064 | 0.447959 | 5.65 | 0.408 | 0.442 | 2,000 |
| `alone_triangle_edge_overlap_2` | 4 | rust | 2,000 | 0.114473 | 0.528528 | 3.94 | 0.71 | 0.458 | 2,000 |
| `alone_triangle_edge_overlap_2` | 5 | rust | 2,000 | 0.114473 | 0.528528 | 3.94 | 0.0548 | 0.843 | 2,000 |
| `alone_square_count_1` | 4 | rust | 2,000 | 0.866417 | 0.401032 | 2.84 | 0.00678 | 0.45 | 2,000 |
| `alone_square_count_1` | 5 | rust | 2,000 | 0.866417 | 0.401032 | 2.84 | 0.957 | 0.126 | 2,000 |
| `alone_square_count_2` | 4 | rust | 2,000 | 0.884025 | 0.002932 | 3.03 | 0.571 | 0.787 | 2,000 |
| `alone_square_count_2` | 5 | rust | 2,000 | 0.884025 | 0.002932 | 3.03 | 0.839 | 0.808 | 2,000 |
| `alone_square_edge_overlap_1` | 4 | rust | 2,000 | 0.419413 | 0.849612 | 2.66 | 0.0811 | 0.741 | 2,000 |
| `alone_square_edge_overlap_1` | 5 | rust | 2,000 | 0.419413 | 0.849612 | 2.66 | 0.543 | 0.361 | 2,000 |
| `alone_square_edge_overlap_2` | 4 | rust | 2,000 | 0.653947 | 0.34559 | 4.43 | 0.764 | 0.842 | 1,999 |
| `alone_square_edge_overlap_2` | 5 | rust | 2,000 | 0.653947 | 0.34559 | 4.43 | 0.19 | 0.284 | 2,000 |
| `alone_induced_square_count_1` | 4 | rust | 2,000 | 0.729669 | 0.308882 | 3.29 | 0.499 | 0.72 | 2,000 |
| `alone_induced_square_count_1` | 5 | rust | 2,000 | 0.729669 | 0.308882 | 3.29 | 0.825 | 0.842 | 2,000 |
| `alone_induced_square_count_2` | 4 | rust | 2,000 | 0.594491 | 0.352436 | 2.72 | 0.788 | 0.788 | 2,000 |
| `alone_induced_square_count_2` | 5 | rust | 2,000 | 0.594491 | 0.352436 | 2.72 | 0.863 | 0.507 | 2,000 |
| `alone_degree_neighbor_gradient_1` | 4 | rust | 2,000 | 0.364839 | 0.97075 | 3.65 | 0.298 | 6.53e-53 | 1,996 |
| `alone_degree_neighbor_gradient_1` | 5 | rust | 2,000 | 0.364839 | 0.97075 | 3.65 | 0.735 | 1.8e-121 | 1,999 |
| `alone_degree_neighbor_gradient_2` | 4 | rust | 2,000 | 0.633733 | 0.572771 | 5.03 | 0.582 | 0.887 | 2,000 |
| `alone_degree_neighbor_gradient_2` | 5 | rust | 2,000 | 0.633733 | 0.572771 | 5.03 | 0.614 | 0.737 | 2,000 |
| `alone_degree_anchor_abs_1` | 4 | rust | 2,000 | 0.896993 | 0.879043 | 2.36 | 0.991 | 8.03e-156 | 1,975 |
| `alone_degree_anchor_abs_1` | 5 | rust | 2,000 | 0.896993 | 0.879043 | 2.36 | 0.576 | 0 | 1,994 |
| `alone_degree_anchor_abs_2` | 4 | rust | 2,000 | 0.60079 | 0.332857 | 2.59 | 0.417 | 0.144 | 2,000 |
| `alone_degree_anchor_abs_2` | 5 | rust | 2,000 | 0.60079 | 0.332857 | 2.59 | 0.9 | 0.0926 | 2,000 |
| `alone_degree_cube_sum_1` | 4 | rust | 2,000 | 0.144085 | 0.091615 | 2.87 | 0.297 | 0.674 | 2,000 |
| `alone_degree_cube_sum_1` | 5 | rust | 2,000 | 0.144085 | 0.091615 | 2.87 | 0.908 | 0.532 | 2,000 |
| `alone_degree_cube_sum_2` | 4 | rust | 2,000 | 0.302163 | 0.483334 | 4.34 | 0.959 | 0.908 | 2,000 |
| `alone_degree_cube_sum_2` | 5 | rust | 2,000 | 0.302163 | 0.483334 | 4.34 | 0.604 | 0.575 | 2,000 |
| `alone_degree_fourth_sum_1` | 4 | rust | 2,000 | 0.023484 | 0.318097 | 3.91 | 0.0169 | 0.159 | 2,000 |
| `alone_degree_fourth_sum_1` | 5 | rust | 2,000 | 0.023484 | 0.318097 | 3.91 | 0.0259 | 0.622 | 2,000 |
| `alone_degree_fourth_sum_2` | 4 | rust | 2,000 | 0.874808 | 0.977859 | 2.24 | 0.15 | 0 | 1,806 |
| `alone_degree_fourth_sum_2` | 5 | rust | 2,000 | 0.874808 | 0.977859 | 2.24 | 0.302 | 0 | 1,986 |
| `alone_ollivier_curvature_1` | 4 | rust | 2,000 | 0.458721 | 0.030501 | 5.99 | 0.713 | 0.865 | 2,000 |
| `alone_ollivier_curvature_1` | 5 | rust | 2,000 | 0.458721 | 0.030501 | 5.99 | 0.135 | 0.954 | 2,000 |
| `alone_ollivier_curvature_2` | 4 | rust | 2,000 | 0.981955 | 0.701006 | 5.17 | 0.36 | 0 | 1,985 |
| `alone_ollivier_curvature_2` | 5 | rust | 2,000 | 0.981955 | 0.701006 | 5.17 | 0.729 | 0 | 1,999 |
| `mixed_1` | 4 | rust | 2,000 | 0.856685 | 0.74857 | 1.83 | 0.83 | 0.11 | 2,000 |
| `mixed_1` | 5 | rust | 2,000 | 0.856685 | 0.74857 | 2.21 | 0.513 | 0.0577 | 2,000 |
| `mixed_2` | 4 | rust | 2,000 | 0.740276 | 0.882352 | 1.96 | 0.678 | 0.0651 | 2,000 |
| `mixed_2` | 5 | rust | 2,000 | 0.740276 | 0.882352 | 1.96 | 0.43 | 0.0506 | 2,000 |
| `mixed_3` | 4 | rust | 2,000 | 0.289847 | 0.132823 | 1.98 | 0.475 | 0.465 | 2,000 |
| `mixed_3` | 5 | rust | 2,000 | 0.289847 | 0.132823 | 2.19 | 0.613 | 0.508 | 2,000 |
| `mixed_4` | 4 | rust | 2,000 | 0.126608 | 0.478348 | 2.73 | 0.98 | 0.376 | 2,000 |
| `mixed_4` | 5 | rust | 2,000 | 0.126608 | 0.478348 | 2.58 | 0.342 | 0.544 | 2,000 |
| `mixed_5` | 4 | rust | 2,000 | 0.570437 | 0.959296 | 1.26 | 0.153 | 5.17e-296 | 1,999 |
| `mixed_5` | 5 | rust | 2,000 | 0.570437 | 0.959296 | 1.22 | 0.723 | 0 | 2,000 |
| `mixed_6` | 4 | rust | 2,000 | 0.860047 | 0.280454 | 0.95 | 0.962 | 0.462 | 2,000 |
| `mixed_6` | 5 | rust | 2,000 | 0.860047 | 0.280454 | 0.92 | 0.893 | 0.303 | 2,000 |
| `mixed_7` | 4 | rust | 2,000 | 0.623038 | 0.826645 | 0.23 | 0.381 | 0.397 | 2,000 |
| `mixed_7` | 5 | rust | 2,000 | 0.623038 | 0.826645 | 0.31 | 0.825 | 0.524 | 2,000 |
| `mixed_8` | 4 | rust | 2,000 | 0.534503 | 0.926362 | 1.78 | 0.381 | 0.349 | 1,999 |
| `mixed_8` | 5 | rust | 2,000 | 0.534503 | 0.926362 | 1.67 | 0.115 | 0.041 | 2,000 |
| `reach_edge_count_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 3.68 | 0.122 | 0.394 | 2,000 |
| `reach_edge_count_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 3.68 | 0.798 | 0.798 | 2,000 |
| `reach_edge_count_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 3.68 | 0.221 | 0.928 | 2,000 |
| `reach_edge_count_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 3.68 | 0.793 | 0.534 | 2,000 |
| `reach_degree_anchor_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 2.45 | 0.857 | 0.367 | 2,000 |
| `reach_degree_anchor_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 2.45 | 0.673 | 0.674 | 2,000 |
| `reach_degree_anchor_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 2.45 | 0.331 | 0.0973 | 2,000 |
| `reach_degree_anchor_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 2.45 | 0.0544 | 0.633 | 2,000 |
| `reach_degree_square_sum_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 3.03 | 0.614 | 0.567 | 2,000 |
| `reach_degree_square_sum_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 3.03 | 0.642 | 0.674 | 2,000 |
| `reach_degree_square_sum_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 3.03 | 0.371 | 0.296 | 2,000 |
| `reach_degree_square_sum_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 3.03 | 0.336 | 0.0817 | 2,000 |
| `reach_wedge_count_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 5.44 | 0.905 | 0.234 | 2,000 |
| `reach_wedge_count_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 5.44 | 0.296 | 0.908 | 2,000 |
| `reach_wedge_count_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 5.44 | 0.131 | 0.351 | 2,000 |
| `reach_wedge_count_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 5.44 | 0.798 | 0.544 | 2,000 |
| `reach_triangle_count_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 2.74 | 0.928 | 0.888 | 2,000 |
| `reach_triangle_count_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 2.74 | 0.966 | 0.44 | 2,000 |
| `reach_triangle_count_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 2.74 | 0.932 | 0.45 | 2,000 |
| `reach_triangle_count_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 2.74 | 0.0613 | 0.211 | 2,000 |
| `reach_triangle_edge_overlap_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 5.65 | 0.889 | 0.884 | 2,000 |
| `reach_triangle_edge_overlap_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 5.65 | 0.661 | 0.674 | 2,000 |
| `reach_triangle_edge_overlap_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 5.65 | 0.402 | 0.785 | 2,000 |
| `reach_triangle_edge_overlap_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 5.65 | 0.823 | 0.145 | 2,000 |
| `reach_square_count_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 2.84 | 0.581 | 0.795 | 2,000 |
| `reach_square_count_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 2.84 | 0.461 | 0.455 | 2,000 |
| `reach_square_count_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 2.84 | 0.679 | 0.0521 | 2,000 |
| `reach_square_count_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 2.84 | 0.0693 | 0.0801 | 2,000 |
| `reach_square_edge_overlap_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 2.66 | 0.0998 | 0.00491 | 2,000 |
| `reach_square_edge_overlap_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 2.66 | 0.338 | 0.683 | 2,000 |
| `reach_square_edge_overlap_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 2.66 | 0.802 | 0.449 | 2,000 |
| `reach_square_edge_overlap_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 2.66 | 1 | 0.642 | 2,000 |
| `reach_induced_square_count_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 3.29 | 0.798 | 0.0331 | 2,000 |
| `reach_induced_square_count_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 3.29 | 0.0325 | 0.267 | 2,000 |
| `reach_induced_square_count_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 3.29 | 0.307 | 0.953 | 2,000 |
| `reach_induced_square_count_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 3.29 | 0.454 | 0.0551 | 2,000 |
| `reach_degree_neighbor_gradient_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 3.65 | 0.566 | 0.914 | 2,000 |
| `reach_degree_neighbor_gradient_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 3.65 | 0.783 | 0.209 | 2,000 |
| `reach_degree_neighbor_gradient_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 3.65 | 0.237 | 0.33 | 2,000 |
| `reach_degree_neighbor_gradient_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 3.65 | 0.49 | 0.295 | 2,000 |
| `reach_degree_anchor_abs_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 2.36 | 0.625 | 0.607 | 2,000 |
| `reach_degree_anchor_abs_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 2.36 | 0.923 | 0.782 | 2,000 |
| `reach_degree_anchor_abs_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 2.36 | 0.611 | 0.426 | 2,000 |
| `reach_degree_anchor_abs_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 2.36 | 0.646 | 0.539 | 2,000 |
| `reach_degree_cube_sum_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 2.87 | 0.138 | 0.518 | 2,000 |
| `reach_degree_cube_sum_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 2.87 | 0.562 | 0.911 | 2,000 |
| `reach_degree_cube_sum_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 2.87 | 0.618 | 0.166 | 2,000 |
| `reach_degree_cube_sum_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 2.87 | 0.197 | 0.799 | 2,000 |
| `reach_degree_fourth_sum_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 3.91 | 0.388 | 0.421 | 2,000 |
| `reach_degree_fourth_sum_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 3.91 | 0.734 | 0.598 | 2,000 |
| `reach_degree_fourth_sum_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 3.91 | 0.291 | 0.437 | 2,000 |
| `reach_degree_fourth_sum_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 3.91 | 0.0384 | 0.248 | 2,000 |
| `reach_ollivier_curvature_locality_0` | 4 | rust | 2,000 | 0 | 0.15 | 5.99 | 0.249 | 0.924 | 2,000 |
| `reach_ollivier_curvature_locality_0` | 5 | rust | 2,000 | 0 | 0.15 | 5.99 | 0.695 | 0.252 | 2,000 |
| `reach_ollivier_curvature_locality_0.5` | 4 | rust | 2,000 | 0.5 | 0.15 | 5.99 | 0.268 | 0.159 | 2,000 |
| `reach_ollivier_curvature_locality_0.5` | 5 | rust | 2,000 | 0.5 | 0.15 | 5.99 | 0.239 | 0.306 | 2,000 |
| `the_tree_s_law_toggle` | 4 | rust | 2,000 | 0.7 | 0.1 | 2.60 | 0.333 | 0.734 | 2,000 |
| `the_tree_s_law_toggle` | 5 | rust | 2,000 | 0.7 | 0.1 | 6.80 | 0.961 | 0.111 | 2,000 |
| `the_tree_s_law_at_twice_its_energy` | 4 | rust | 2,000 | 0.7 | 0.1 | 2.60 | 0 | 0 | 2,000 |
| `the_tree_s_law_at_twice_its_energy` | 5 | rust | 2,000 | 0.7 | 0.1 | 6.80 | 0 | 0 | 2,000 |
