from __future__ import annotations

REFUSED_PREFIX = "REFUSED_"


def refused(bucket) -> bool:
    return bucket is not None and str(bucket).startswith(REFUSED_PREFIX)


def masked(values, buckets) -> list:
    buckets = list(buckets or [])
    return [None if (i < len(buckets) and refused(buckets[i])) else value for i, value in enumerate(values or [])]


def ladder_buckets(phenotype: dict, probe: str, base: list, extension: list) -> list:
    def half(stored, rungs, cells):
        column = list(stored or [])
        if len(column) == len(rungs):
            return column
        out = []
        for n in rungs:
            cell = cells.get(str(n)) or {}
            out.append(cell.get(f"{probe}_bucket", ((cell.get("probes") or {}).get(probe) or {}).get("bucket")))
        return out
    return (half((phenotype.get("probe_bucket_vectors") or {}).get(probe), base, phenotype.get("per_n") or {})
            + half((phenotype.get("extension_probe_bucket_vectors") or {}).get(probe), extension,
                   phenotype.get("extension_per_n") or {}))
