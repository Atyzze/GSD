# The calibration table's known answers on the final probes

Judged against `table_known_answers_criterion.json`, committed 2026-11-19T00:02:01Z before the table was read. It passes: 0 judged cells are not as the criterion says.

A bold reading is held to its band (the mean over the seeds that read); the rest are shown. A family without a dimension is held to no value from 4,096 nodes.

## balanced_binary_tree, without a dimension

255 shown, 511 shown, 1,023 shown, 2,047 shown, 4,095 shown, 8,191 refused as required, 16,383 refused as required, 65,535 refused as required, 262,143 refused as required, 1,048,575 refused as required.

## erdos_renyi_degree_16, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required.

## erdos_renyi_degree_2, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## erdos_renyi_degree_32, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required.

## erdos_renyi_degree_6, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## erdos_renyi_dense, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## erdos_renyi_mid, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## erdos_renyi_sparse, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## hyperbolic_geometric_graph, without a dimension

1,024 shown, 4,096 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required.

## hyperbolic_triangle_tiling, without a dimension

617 shown, 1,625 shown, 4,264 refused as required, 11,173 refused as required, 29,261 refused as required, 76,616 refused as required, 200,593 refused as required.

## periodic_a4_lattice (d_B 4 from 65,536; d_V 4 from 4,096; d_s 4 from 4,096; d_w 2 from 331,776; held from this table's own cells)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 81 | refused | refused | refused | refused |
| 256 | refused | refused | refused | refused |
| 625 | refused | refused | refused | refused |
| 1,296 | refused | refused | refused | refused |
| 4,096 | **4.069** | **3.824** | refused | refused |
| 10,000 | **4.033** | **3.896** | refused | refused |
| 20,736 | **4.081** | **3.914** | refused | refused |
| 65,536 | **4.028** | **3.944** | **3.681** | refused |
| 160,000 | **4.020** | **3.967** | **3.722** | refused |
| 331,776 | **4.006** | **3.966** | **3.755** | **1.953** |
| 614,656 | **3.982** | **3.977** | **3.775** | **1.961** |

## periodic_body_centred_cubic_lattice (d_B 3 from 16,384; d_V 3 from 1,024; d_s 3 from 1,024; d_w 2 from 16,384; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 256 | refused | refused | refused | refused |
| 1,024 | **3.068** | **2.932** | refused | refused |
| 4,096 | **2.985** | **2.939** | refused | refused |
| 16,384 | **2.991** | **2.988** | **2.850** | **1.972** |
| 65,536 | **3.012** | **2.996** | **2.880** | **1.974** |
| 262,144 | **3.002** | **2.993** | **2.897** | **1.988** |
| 1,048,576 | **2.995** | **2.999** | **2.914** | **1.985** |

## periodic_cubic_lattice (d_B 3 from 4,096; d_V 3 from 1,024; d_s 3 from 1,024; d_w 2 from 16,384; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 125 | refused | refused | refused | refused |
| 216 | refused | refused | refused | refused |
| 512 | 3.099 | 2.751 | refused | refused |
| 1,000 | 3.058 | 2.846 | refused | refused |
| 1,728 | **3.037** | **2.879** | refused | refused |
| 4,096 | **2.999** | **2.924** | **2.740** | refused |
| 8,000 | **2.969** | **2.952** | **2.781** | 1.949 |
| 15,625 | **3.001** | **2.968** | **2.794** | 1.974 |
| 64,000 | **2.984** | **2.981** | **2.837** | **1.970** |
| 262,144 | **3.007** | **2.989** | **2.865** | **1.978** |
| 1,030,301 | **3.002** | **2.994** | **2.884** | **1.982** |

## periodic_cubic_quotient (d_B 3 from 4,096; d_V 3 from 1,024; d_s 3 from 1,024; d_w 2 from 16,384; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 256 | 3.181 | 2.751 | refused | refused |
| 1,024 | **3.060** | **2.890** | refused | refused |
| 4,096 | **2.999** | **2.924** | **2.740** | refused |
| 16,384 | **3.002** | **2.978** | **2.803** | **1.931** |
| 65,536 | **2.996** | **2.994** | **2.835** | **1.969** |
| 262,144 | **3.007** | **2.989** | **2.865** | **1.978** |
| 1,048,576 | **3.002** | **2.994** | **2.886** | **1.986** |

## periodic_d4_lattice (d_B 4 from 80,000; d_V 4 from 5,000; d_s 4 from 5,000; d_w 2 from 307,328; held from this table's own cells)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 128 | refused | refused | refused | refused |
| 648 | refused | refused | refused | refused |
| 2,048 | refused | refused | refused | refused |
| 5,000 | **4.041** | **3.907** | refused | refused |
| 10,368 | **4.020** | **3.947** | refused | refused |
| 32,768 | **3.984** | **3.969** | refused | refused |
| 80,000 | **3.978** | **3.980** | **3.747** | refused |
| 165,888 | **4.057** | **3.986** | **3.751** | refused |
| 307,328 | **4.011** | **3.990** | **3.781** | **1.987** |
| 524,288 | **3.970** | **3.992** | **3.801** | **1.987** |

## periodic_face_centred_cubic_lattice (d_B 3 from 16,384; d_V 3 from 1,024; d_s 3 from 1,024; d_w 2 from 16,384; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 256 | refused | refused | refused | refused |
| 1,024 | **3.072** | **2.963** | refused | refused |
| 4,096 | **3.012** | **2.977** | refused | refused |
| 16,384 | **2.987** | **2.993** | **2.837** | **1.966** |
| 65,536 | **3.021** | **2.997** | **2.868** | **1.979** |
| 262,144 | **2.998** | **2.997** | **2.891** | **1.991** |
| 1,048,576 | **2.999** | **3.000** | **2.910** | **1.994** |

## periodic_honeycomb_lattice (d_B 2 from 1,024; d_V 2 from 1,024; d_s 2 from 1,024; d_w 2 from 1,024; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | 2.009 | 1.871 | refused | refused |
| 144 | 2.045 | 1.940 | refused | refused |
| 256 | 2.012 | 1.966 | refused | 2.012 |
| 576 | 2.022 | 1.985 | 1.851 | 1.996 |
| 1,024 | **2.016** | **1.992** | **1.874** | **1.988** |
| 2,304 | **2.011** | **1.997** | **1.898** | **1.981** |
| 4,096 | **2.007** | **1.997** | **1.922** | **1.993** |
| 9,216 | **1.990** | **1.999** | **1.935** | **1.976** |
| 16,384 | **2.011** | **1.999** | **1.936** | **1.975** |
| 65,536 | **1.999** | **2.000** | **1.949** | **1.989** |
| 262,144 | **1.998** | **2.000** | **1.950** | **1.983** |
| 1,048,576 | **2.002** | **2.000** | **1.952** | **1.990** |

## periodic_hypercubic_lattice_4d (d_B 4 from 16,384; d_V 4 from 1,024; d_s 4 from 1,024; d_w 2 from 262,144; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 81 | refused | refused | refused | refused |
| 256 | refused | refused | refused | refused |
| 625 | refused | refused | refused | refused |
| 1,296 | **4.179** | **3.299** | refused | refused |
| 4,096 | **4.053** | **3.562** | refused | refused |
| 10,000 | **3.968** | **3.676** | refused | refused |
| 20,736 | **4.048** | **3.758** | **3.517** | refused |
| 65,536 | **4.009** | **3.855** | **3.582** | 1.916 |
| 160,000 | **4.032** | **3.899** | **3.666** | 1.900 |
| 331,776 | **4.009** | **3.920** | **3.711** | **1.911** |
| 614,656 | **3.962** | **3.942** | **3.732** | **1.944** |
| 1,048,576 | **3.969** | **3.949** | **3.751** | **1.928** |

## periodic_ring (d_B 1 from 1,024; d_V 1 from 1,024; d_s 1 from 1,024; d_w 2 from 1,024; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | 0.999 | 1.000 | refused | 1.989 |
| 128 | 0.998 | 1.000 | 0.941 on 7 of 10 | 1.959 |
| 256 | 0.998 | 1.000 | 0.971 | 2.005 |
| 512 | 0.998 | 1.000 | 0.977 | 1.999 |
| 1,024 | **1.000** | **1.000** | **0.979** | **2.018** |
| 2,048 | **1.001** | **1.000** | **0.978** | **1.988** |
| 4,096 | **1.003** | **1.000** | **0.980** | **2.006** |
| 8,192 | **1.003** | **1.000** | **0.981** | **1.989** |
| 16,384 | **1.002** | **1.000** | **0.982** | **1.998** |
| 65,536 | **1.000** | **1.000** | **0.982** | **2.002** |
| 262,144 | **1.000** | **1.000** | **0.983** | **1.990** |
| 1,048,576 | **0.999** | **1.000** | **0.984** | **2.004** |

## periodic_square_lattice (d_B 2 from 1,024; d_V 2 from 1,024; d_s 2 from 1,024; d_w 2 from 1,024; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 144 | 2.037 | 1.973 | refused | refused |
| 256 | 2.012 | 1.985 | refused | refused |
| 576 | 2.007 | 1.988 | refused | 1.970 |
| 1,024 | **2.011** | **1.994** | **1.905** | **1.985** |
| 2,304 | **2.015** | **1.997** | **1.912** | **1.996** |
| 4,096 | **1.989** | **1.999** | **1.927** | **1.989** |
| 9,216 | **1.986** | **1.999** | **1.939** | **1.994** |
| 16,384 | **1.984** | **2.000** | **1.950** | **1.986** |
| 65,536 | **2.009** | **2.000** | **1.957** | **1.991** |
| 262,144 | **2.002** | **2.000** | **1.960** | **1.987** |
| 1,048,576 | **2.000** | **2.000** | **1.961** | **1.997** |

## periodic_tesseract_quotient (d_B 4 from 16,384; d_V 4 from 1,024; d_s 4 from 1,024; d_w 2 from 262,144; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 256 | refused | refused | refused | refused |
| 1,024 | **4.203** | **3.371** | refused | refused |
| 4,096 | **4.053** | **3.562** | refused | refused |
| 16,384 | **4.026** | **3.807** | **3.515** | refused |
| 65,536 | **4.009** | **3.855** | **3.582** | 1.916 |
| 262,144 | **3.982** | **3.948** | **3.703** | **1.916** |
| 1,048,576 | **3.969** | **3.949** | **3.751** | **1.928** |

## periodic_triangular_lattice (d_B 2 from 1,024; d_V 2 from 1,024; d_s 2 from 1,024; d_w 2 from 1,024; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 64 | refused | refused | refused | refused |
| 144 | 2.042 | 1.984 | refused | refused |
| 256 | 2.013 | 1.992 | refused | refused |
| 576 | 2.018 | 1.997 | refused | 2.073 |
| 1,024 | **2.024** | **1.998** | **1.881** on 9 of 10 | **2.013** |
| 2,304 | **2.009** | **1.999** | **1.900** | **2.009** |
| 4,096 | **2.003** | **2.000** | **1.927** | **1.998** |
| 9,216 | **1.976** | **2.000** | **1.935** | **1.995** |
| 16,384 | **1.995** | **2.000** | **1.945** | **1.986** |
| 65,536 | **2.008** | **2.000** | **1.955** | **2.001** |
| 262,144 | **2.006** | **2.000** | **1.961** | **1.993** |
| 1,048,576 | **1.999** | **2.000** | **1.960** | **2.002** |

## random_3_regular, without a dimension

256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## random_4_regular, without a dimension

128 shown, 256 shown, 512 shown, 1,024 shown, 2,048 shown, 4,096 refused as required, 8,192 refused as required, 16,384 refused as required, 65,536 refused as required, 262,144 refused as required, 1,048,576 refused as required.

## sierpinski_carpet (d_B 1.89 from 4,096; d_V 1.89 from 4,096; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 8 | refused | refused | refused | refused |
| 64 | 1.481 | 1.555 | refused | refused |
| 512 | 1.509 | 1.713 | 1.649 | 2.262 |
| 4,096 | 1.595 | **1.808** | **1.729** | 2.183 |
| 32,768 | 1.725 | **1.780** | **1.781** | 2.129 |
| 262,144 | 1.767 | **1.830** | **1.823** | 2.105 |

## sierpinski_gasket (d_B 1.58 from 1,095; d_V 1.58 from 1,095; d_s 1.37 from 1,095; d_w 2.32 from 1,095; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 6 | refused | refused | refused | refused |
| 15 | refused | refused | refused | refused |
| 42 | refused | refused | refused | refused |
| 123 | 1.217 | 1.470 | refused | 2.447 |
| 366 | 1.283 | 1.473 | 1.310 on 3 of 10 | 2.405 |
| 1,095 | **1.332** | **1.462** | **1.467** | **2.347** |
| 3,282 | **1.359** | **1.462** | **1.525** | **2.321** |
| 9,843 | **1.360** | **1.539** | **1.545** | **2.306** |
| 29,526 | **1.370** | **1.557** | **1.554** | **2.318** |
| 88,575 | **1.371** | **1.573** | **1.562** | **2.324** |
| 265,722 | **1.368** | **1.590** | **1.567** | **2.311** |
| 797,163 | **1.369** | **1.582** | **1.573** | **2.312** |

## uniform_random_tree (d_s 1.33 from 4,096; held from the fifth judged set)

| nodes | d_s | d_V | d_B | d_w |
|---:|---|---|---|---|
| 256 | 1.221 | 1.674 | 1.296 on 4 of 10 | 2.509 on 9 of 10 |
| 512 | 1.226 | 1.646 | 1.494 on 9 of 10 | 2.570 on 9 of 10 |
| 1,024 | 1.247 | 1.702 | 1.529 | 2.569 |
| 2,048 | 1.267 | 1.824 | 1.579 | 2.551 on 8 of 10 |
| 4,096 | **1.294** | 1.933 | 1.694 | 2.576 on 4 of 10 |
| 8,192 | **1.289** on 9 of 10 | 1.927 on 9 of 10 | 1.684 on 9 of 10 | 2.720 on 8 of 10 |
| 16,384 | **1.296** | 1.948 | 1.731 | 2.659 on 8 of 10 |
| 65,536 | **1.292** | 1.985 | 1.791 | 2.628 on 5 of 10 |
| 262,144 | **1.295** | 1.924 | 1.751 | 2.681 on 9 of 10 |
| 1,048,576 | **1.294** | 1.956 | 1.746 | 2.616 |

## Not as the criterion says

Nothing.

## The predictions

* Every value and refusal of the seed's cells repeated, bit for bit: true: 2,194 cells compared, 0 readings differ, 0 cells missing.
* A4 and D4 held from the predicted sizes: false: periodic_a4_lattice d_s from 4096 (1296 predicted); periodic_a4_lattice d_V from 4096 (1296 predicted); periodic_d4_lattice d_s from 5000 (2048 predicted); periodic_d4_lattice d_V from 5000 (2048 predicted); periodic_d4_lattice d_B from 80000 (65536 predicted).
* The random graphs of mean degree 16 and 32 refused everywhere: true.
* d_s's error within 0.5 to 2 of its seeds' spread in nine cells of ten: true: 96 of 96 cells inside.
* No geometry refused for its balls from 4,096 nodes: true: uniform_random_tree at 8,192 on seeds [6].
