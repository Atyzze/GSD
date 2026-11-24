# Where it started

The operator's first models, sent on 2026-10-01 ("it started from ..."), kept byte for byte as they were sent, each
under its own name with `.txt` after it, so that no check of the tree's own code reads them as the tree's code (a
hygiene test did, at 558). GSD grew out of them; nothing in the tree imports them. To run one, copy it without the
`.txt`; they need their own dependencies (networkx, matplotlib, and for `universe.py` scikit-learn and optionally
numba).

* **`universe.py.txt`, the Universe Observatory.** A thousand nodes, each with one of eight colours, rewired by
  Metropolis: a link pays for matching colours (coherence), is taxed for mismatching ones (frustration), and every
  node pays for its degree and its degree squared (connection cost and congestion); a penalty for mutual information
  between far pairs and for extra components. Read by an information metric (MDS of time-lagged mutual information),
  its metricity, a dimension probe (MDS stress by dimension) and the Ollivier-Ricci curvature.
* **`universe0.py.txt` to `universe3.py.txt`, Relational Physics v2 to v2.2.** A complex matter field on the nodes and a U(1)
  gauge field on the edges: mass and quartic terms, hopping through the gauge field, the flux around each triangle, an
  edge cost and a degree-squared congestion, and from v2.1 a stress-geometry coupling that makes an edge cost more
  where the field is dense. Read by a gauge-invariance check, a correlator against hop distance, a light cone after a
  local kick, a curvature-density diagnostic (a Forman proxy, 4 - deg u - deg v, which reads only degrees) and, from
  v2, a quench that injects matter and reads the curvature's response.

What GSD took from them is the graph half: the edge cost and the degree-squared congestion (the founder, whose energy
reads only degrees, so its equilibrium wiring is random), and then triangles, squares and the curvature. The fields
(colours, the matter field, the gauge field and its flux, the stress coupling) never entered the survey's term pool;
they are the first candidates for new terms, and Relational Physics v2.2 is a candidate back-test for the literature
stage (`docs/ROADMAP.md`, "Where the research is going").
