# The curvature probe against Ollivier's curvature, edge by edge

gsd-curvature-known-answers-1: the probe is Kelly, Trugenberger and Biancalana's formula from the triangles, squares and pentagons on an edge (`engine.scaled_curvature` over the two degrees); the known answer is Ollivier's curvature of the same edge, 1 less the cost of moving one end's neighbours onto the other's, solved exactly. A family is exact when every edge read agrees.

Predictions right: **8 of 8**.

| family | nodes | mean degree | edges read | agreeing | Ollivier, mean | the probe, mean | the probe less Ollivier (least, most) | expected | exact |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `square_torus` | 400 | 4 | 300 | 300 | 0.0000 | 0.0000 | +0.0000, +0.0000 | exact | yes |
| `cubic_torus` | 729 | 6 | 300 | 300 | 0.0000 | 0.0000 | -0.0000, +0.0000 | exact | yes |
| `tesseract_torus` | 1,296 | 8 | 300 | 300 | 0.0000 | 0.0000 | +0.0000, +0.0000 | exact | yes |
| `ring` | 200 | 2 | 200 | 200 | 0.0000 | 0.0000 | +0.0000, +0.0000 | exact | yes |
| `honeycomb_torus` | 1,024 | 3 | 300 | 300 | -0.6667 | -0.6667 | -0.0000, -0.0000 | exact | yes |
| `complete_6` | 6 | 5 | 15 | 15 | 0.8000 | 0.8000 | +0.0000, +0.0000 | exact | yes |
| `triangular_torus` | 400 | 6 | 300 | 0 | 0.0000 | 0.3333 | +0.3333, +0.3333 | not_exact | no |
| `random_geometric_2d` | 1,000 | 7.846 | 300 | 47 | 0.1108 | 0.4048 | -0.0000, +1.0714 | not_exact | no |
| `random_regular_3` | 2,000 | 3 | 300 | 300 | -0.6667 | -0.6667 | -0.0000, -0.0000 | not committed | yes |
| `erdos_renyi_4` | 977 | 4.0921 | 300 | 295 | -0.9900 | -0.9879 | -0.0000, +0.1429 | not committed | no |
