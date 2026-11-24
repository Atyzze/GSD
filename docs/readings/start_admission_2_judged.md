# Which lattices a law of the fourteen terms can tell from a random graph

Judged against `gsd-start-admission-criterion-2`, committed before this reading. It passes: 6 of 8 lattices are admitted (square, triangular, cubic, body-centred cubic, face-centred cubic, 4D), and not honeycomb, diamond.

A term tells a lattice when its energy a node there, taken alone with coupling 1, differs from its mean on random regular graphs of the same size and degree by at least 0.05 at the largest size and by at least 0.5 of its difference at the smallest: an amount a node that does not shrink with N. Sizes read: 1,024, 4,096, 16,384 nodes; 3 random graphs a size.

| lattice | dimension | neighbours | admitted | told by | as expected |
|---|---:|---:|---|---|---|
| honeycomb | 2 | 3 | no | no term | yes |
| diamond | 3 | 4 | no | no term | yes |
| square | 2 | 4 | yes | `induced_square_count`, `ollivier_curvature`, `square_count`, `square_edge_overlap` | yes |
| triangular | 2 | 6 | yes | `ollivier_curvature`, `square_count`, `square_edge_overlap`, `triangle_count`, `triangle_edge_overlap` | expected `induced_square_count`, `ollivier_curvature`, `square_count`, `square_edge_overlap`, `triangle_count`, `triangle_edge_overlap` |
| cubic | 3 | 6 | yes | `induced_square_count`, `ollivier_curvature`, `square_count`, `square_edge_overlap` | yes |
| body-centred cubic | 3 | 8 | yes | `induced_square_count`, `ollivier_curvature`, `square_count`, `square_edge_overlap` | yes |
| face-centred cubic | 3 | 12 | yes | `induced_square_count`, `ollivier_curvature`, `square_count`, `square_edge_overlap`, `triangle_count`, `triangle_edge_overlap` | yes |
| 4D | 4 | 8 | yes | `induced_square_count`, `ollivier_curvature`, `square_count`, `square_edge_overlap` | yes |

## Every term on every lattice

The lattice's energy a node less the random graphs' mean, at each size; a term that reads the same on both at every size is left out.

### honeycomb

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | -0.001302 | -0.0005697 | -0.0002035 | no |
| `ollivier_curvature` | -0.1475 | -0.02515 | -0.007263 | no |
| `square_count` | -0.001302 | -0.0005697 | -0.0002035 | no |
| `triangle_count` | -0.001953 | -0.0002441 | -2.035e-05 | no |

### diamond

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | -0.008138 | -0.00236 | -0.0006307 | no |
| `ollivier_curvature` | -0.8464 | -0.2236 | -0.06185 | no |
| `square_count` | -0.008138 | -0.00236 | -0.0006307 | no |
| `triangle_count` | -0.003255 | -0.001221 | -0.0003662 | no |

### square

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | +0.9919 | +0.9976 | +0.9994 | yes |
| `ollivier_curvature` | +31.15 | +31.78 | +31.94 | yes |
| `square_count` | +0.9919 | +0.9976 | +0.9994 | yes |
| `square_edge_overlap` | +2 | +2 | +2 | yes |
| `triangle_count` | -0.003255 | -0.001221 | -0.0003662 | no |

### triangular

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | -0.07389 | -0.0188 | -0.004822 | no |
| `ollivier_curvature` | +166.4 | +176.6 | +179.1 | yes |
| `square_count` | +2.926 | +2.981 | +2.995 | yes |
| `square_edge_overlap` | +17.99 | +18 | +18 | yes |
| `triangle_count` | +1.977 | +1.995 | +1.999 | yes |
| `triangle_edge_overlap` | +3 | +3 | +3 | yes |

### cubic

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | +2.926 | +2.981 | +2.995 | yes |
| `ollivier_curvature` | +130.4 | +140.6 | +143.1 | yes |
| `square_count` | +2.926 | +2.981 | +2.995 | yes |
| `square_edge_overlap` | +17.99 | +18 | +18 | yes |
| `triangle_count` | -0.02344 | -0.005046 | -0.001078 | no |

### body-centred cubic

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | +11.7 | +11.92 | +11.98 | yes |
| `ollivier_curvature` | +296.8 | +361.5 | +378.5 | yes |
| `square_count` | +11.7 | +11.92 | +11.98 | yes |
| `square_edge_overlap` | +263.8 | +264 | +264 | yes |
| `triangle_count` | -0.05892 | -0.01335 | -0.003845 | no |
| `triangle_edge_overlap` | -0.001953 | -0.0002441 | -2.035e-05 | no |

### face-centred cubic

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | +1.211 | +2.555 | +2.89 | yes |
| `ollivier_curvature` | +918 | +1445 | +1658 | yes |
| `square_count` | +31.18 | +32.55 | +32.89 | yes |
| `square_edge_overlap` | +1382 | +1386 | +1386 | yes |
| `triangle_count` | +7.787 | +7.949 | +7.988 | yes |
| `triangle_edge_overlap` | +35.97 | +36 | +36 | yes |

### 4D

| term | 1,024 | 4,096 | 16,384 | tells |
|---|---:|---:|---:|---|
| `induced_square_count` | +5.701 | +5.922 | +5.982 | yes |
| `ollivier_curvature` | +296.8 | +361.5 | +378.5 | yes |
| `square_count` | +5.7 | +5.921 | +5.982 | yes |
| `square_edge_overlap` | +59.81 | +59.99 | +60 | yes |
| `triangle_count` | -0.05892 | -0.01335 | -0.003845 | no |
| `triangle_edge_overlap` | -0.001953 | -0.0002441 | -2.035e-05 | no |
