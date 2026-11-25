from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from graph_scale_dynamics.reporting import science_contract
from graph_scale_dynamics.operations.report_cycle import COMPLETE, normalize_state
from graph_scale_dynamics.operations.report_home import root_for
from graph_scale_dynamics.research.report_bundle import (
    BUNDLE_ZSTD_LEVEL, BundleIncoherent, bundle_files, bundle_stem, check_coherence, load_report_bodies)

STUDY_BUNDLE_CONTRACT = "gsd-study-bundle-1"
STUDY_DIR, BUNDLES_DIR, INDEX_NAME = "study", "bundles", "index.json"
DECISION_REPORT_CODE = "28"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _compact(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _tables(repo, campaign_ids: list[str], blobs: Path | None = None) -> dict:
    from graph_scale_dynamics.reporting.study_tables import tables
    try:
        return tables(repo, campaign_ids, blobs=blobs if blobs is not None and blobs.is_dir() else None)
    except Exception as exc:  # noqa: BLE001
        return {"unavailable.json": _compact({"why": f"{type(exc).__name__}: {str(exc)[:300]}"})}


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def study_tree(base: Path) -> Path:
    return Path(base).resolve().parent.parent


def study_id(base: Path, repo=None) -> str:
    from graph_scale_dynamics.operations.study_record import study_id as recorded
    return _SAFE.sub("-", recorded(Path(base).parent, repo)).strip("-") or "study"


def _study_note(base: Path) -> str | None:
    from graph_scale_dynamics.operations.study_record import note
    return note(Path(base).parent)


def bundles_dir(base: Path) -> Path:
    return Path(base) / STUDY_DIR / BUNDLES_DIR


def read_index(base: Path) -> dict:
    path = bundles_dir(base) / INDEX_NAME
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = None
    if not isinstance(index, dict):
        index = {"contract": STUDY_BUNDLE_CONTRACT, "bundles": []}
    return index


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _how_read(spec: dict) -> dict:
    from graph_scale_dynamics.operations.study_design import STARTS_READING_KEYS
    sampling = spec.get("sampling_contract") or {}
    five = {key: sampling[key] for key in STARTS_READING_KEYS if key in sampling}
    controls = {key: spec[key] for key in ("controls_criterion", "controls_judged_by") if spec.get(key)}
    return {**({"starts_reading": five} if five else {}), **({"controls": controls} if controls else {})}


def _campaign_record(repo, campaign_id: str) -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study

    row = repo.campaign(str(campaign_id)) or {}
    spec = row.get("spec") or {}
    budget = study.budget_state(repo, str(campaign_id)) or {}
    return {"campaign_id": str(campaign_id), "name": spec.get("name"), "quadrant": study.quadrant_of(spec),
            **({"study_design": spec["study_design"]} if spec.get("study_design") else {}),
            **_how_read(spec),
            "status": row.get("status"), "state": budget.get("state") or control.derived_state(row),
            "workers_target": row.get("workers_target"), "created_utc": row.get("created_utc"),
            "law_budget": budget.get("law_budget", study.law_budget(repo, str(campaign_id))),
            "laws_held": study.laws_held(repo, str(campaign_id)),
            "budget_reached_utc": budget.get("reached_at"),
            "laws": _count(repo, "SELECT COUNT(*) AS c FROM campaign_candidates WHERE campaign_id=?", campaign_id),
            "graphs": _count(repo, "SELECT COUNT(*) AS c FROM jobs WHERE campaign_id=? AND kind='simulate' "
                                   "AND status='done' AND result_artifact IS NOT NULL", campaign_id),
            "graphs_finished": _count(repo, "SELECT COUNT(*) AS c FROM (SELECT DISTINCT candidate_id, n, seed FROM jobs "
                                            "WHERE campaign_id=? AND kind='simulate' AND status='done' "
                                            "AND result_artifact IS NOT NULL) AS finished", campaign_id),
            **_known_answers(repo, row)}


def _known_answers(repo, row: dict) -> dict:
    if ((row.get("spec") or {}).get("search_policy") or {}).get("kind") != "hand":
        return {}
    try:
        from graph_scale_dynamics.research.control_verdict import campaign_verdict
        found = campaign_verdict(repo, row)
    except Exception as exc:  # noqa: BLE001
        found = {"overall": "unreadable", "why": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"known_answers": found} if found else {}


def _label(repo, part: dict, records: dict) -> str:
    from graph_scale_dynamics.operations import study
    spec = (repo.campaign(part["campaign_id"]) or {}).get("spec") or {}
    return (study.quadrant_label(spec) or spec.get("name")
            or records[part["campaign_id"]]["quadrant"]["label"])


def learns_alone(repo, campaign_ids) -> bool:
    from graph_scale_dynamics.decisions.engine import Policy
    for cid in campaign_ids:
        spec = (repo.campaign(str(cid)) or {}).get("spec") or {}
        try:
            if Policy.from_spec(spec).let_through_rule:
                return True
        except ValueError:
            continue
    return False


def gates_ledger_document(repo, campaign_ids) -> dict:
    from graph_scale_dynamics.db.decision_store import let_through_ledger
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.decisions.let_through import CONTRACT
    try:
        policy = next(policy for policy in (Policy.from_spec((repo.campaign(str(cid)) or {}).get("spec") or {})
                                            for cid in campaign_ids) if policy.let_through_rule)
        return let_through_ledger(repo.conn, "bundle", fresh=True, counts_priced=bool(
            policy.ledger_counts_priced)).document(policy, signatures=None, laws=True)
    except Exception as exc:  # noqa: BLE001
        return {"contract": CONTRACT, "unavailable": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _calibration(ready: list[dict]) -> dict | None:
    for part in ready:
        table = Path(part["root"]) / "evidence" / "probe_calibration.json"
        if table.is_file():
            return json.loads(table.read_text(encoding="utf-8"))
    return None


def _read_parts(repo, ready: list[dict], records: dict, calibration: dict | None = None) -> tuple[dict, str | None]:
    from graph_scale_dynamics.reporting import study_explorer as E
    try:
        return {part["campaign_id"]: E.read_part(Path(part["root"]), dict(records.get(part["campaign_id"]) or {},
                                                                          label=_label(repo, part, records)),
                                                 calibration=calibration)
                for part in ready}, None
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {str(exc)[:160]}"


def _explorer(repo, ready: list[dict], records: dict, read: dict, why: str | None, *, sid: str, built: str,
              calibration: dict | None) -> bytes:
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.reporting import study_explorer as E
    title = f"Study {sid}: the explorer, {built}"
    if why is not None:
        return E.unavailable(title, f"the reports could not be read ({why})").encode("utf-8")
    try:
        parts = [{"campaign": dict(records.get(part["campaign_id"]) or {}, label=_label(repo, part, records)),
                  "part": read[part["campaign_id"]]} for part in ready if part["campaign_id"] in read]
        data = E.document(parts, title=title, calibration=calibration,
                          study={"study_id": sid, "built_utc": built, "build_number": BUILD_NUMBER})
        return E.render(data).encode("utf-8")
    except Exception as exc:
        return E.unavailable(title, f"{type(exc).__name__}: {str(exc)[:200]}").encode("utf-8")


def _gate_trees(repo, ready: list[dict], records: dict, read: dict, *, sid: str, built: str):
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.reporting import gate_trees_page as P
    title = f"Study {sid}: the gate trees, {built}"
    try:
        columns = []
        for part in ready:
            record = records[part["campaign_id"]]
            graphs = record.get("graphs")
            graphs = graphs if graphs is not None else (part["tree"] or {}).get("graphs")
            budget = f" · law budget {record['law_budget']:,}" if record.get("law_budget") else ""
            columns.append({"campaign_id": part["campaign_id"], "label": _label(repo, part, records),
                            "tree": part["tree"], "subtitle": (f"{(record.get('laws') or record.get('laws_held') or 0):,} "
                                                               f"laws · {(graphs or 0):,} graphs{budget} · "
                                                               f"{record.get('state')}")})
        carried = [part["campaign_id"] for part in ready if part["campaign_id"] in read]
        data = P.document(columns, title=title, study={"study_id": sid, "built_utc": built,
                                                       "build_number": BUILD_NUMBER},
                          explorer_index={cid: i for i, cid in enumerate(carried)},
                          fate_counts={cid: P.fates(read[cid]) for cid in carried})
    except Exception as exc:  # noqa: BLE001
        why = f"{type(exc).__name__}: {str(exc)[:200]}"
        return lambda links: P.unavailable(title, why).encode("utf-8")
    return lambda links: P.render(data, links=links).encode("utf-8")


def _gate_tree_links(explorer: str, front: str) -> dict:
    return {"explorer": explorer, "front": front}


def _part_stem(part: dict) -> str:
    manifest = part["manifest"]
    return bundle_stem(manifest, manifest.get("bundle_revision") or manifest.get("source_revision"))


def _advice(repo, ready: list[dict], records: dict, read: dict, why: str | None, *, anchors: dict) -> dict:
    from graph_scale_dynamics.research import advice
    if why is not None:
        return {"contract": advice.CONTRACT, "unavailable": f"the reports could not be read ({why})"}
    try:
        parts = [{"campaign": dict(records.get(part["campaign_id"]) or {}, label=_label(repo, part, records)),
                  "part": read[part["campaign_id"]]} for part in ready if part["campaign_id"] in read]
        return advice.advise(parts, anchors=None if anchors.get("unavailable") else anchors)
    except Exception as exc:  # noqa: BLE001
        return {"contract": advice.CONTRACT, "unavailable": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _front_parts(repo, ready: list[dict], records: dict, read: dict) -> tuple[list, list]:
    from graph_scale_dynamics.reporting import study_front as F
    labelled = [dict(part, label=_label(repo, part, records)) for part in ready]
    try:
        cost = F.cost_models(labelled)
    except Exception as exc:  # noqa: BLE001
        cost = [{"campaign_id": part["campaign_id"], "model": None, "why": f"{type(exc).__name__}: {exc}"}
                for part in ready]
    try:
        classify = F.classify_summary([{"campaign": dict(records.get(part["campaign_id"]) or {},
                                                         label=_label(repo, part, records)),
                                        "part": read[part["campaign_id"]]} for part in ready
                                       if part["campaign_id"] in read])
    except Exception:  # noqa: BLE001
        classify = []
    return cost, classify


def _count(repo, sql: str, campaign_id: str) -> int | None:
    try:
        row = repo.conn.execute(sql, (str(campaign_id),)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return int((row["c"] if row is not None else 0) or 0)


def _tree_summary(tree: dict | None) -> dict | None:
    if not isinstance(tree, dict):
        return None
    rungs = tree.get("rungs") or []
    return {"laws_decided": tree.get("laws"), "graphs": tree.get("graphs"),
            "finished_by_rung": {str(r["n"]): r.get("finished") for r in rungs},
            "graphs_by_rung": {str(r["n"]): r.get("graphs", 0) + r.get("graphs_in_progress", 0) for r in rungs
                               if "graphs" in r},
            "settled_d_s_by_rung": {str(r["n"]): (r.get("went_on_by") or {}).get("d_s_settled", 0) for r in rungs},
            "withheld_by_gate": {g["gate"]: g.get("withheld") for g in tree.get("gates") or [] if g.get("withheld")},
            "let_through_by_gate": {g["gate"]: g.get("let_through") for g in tree.get("gates") or []
                                    if g.get("let_through")}}


def _part(base: Path, campaign_id: str) -> dict:
    root = root_for(base, campaign_id)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"campaign_id": campaign_id, "why": "no report manifest"}
    state = normalize_state(manifest.get("cycle_state") or manifest.get("generation_status"))
    if state != COMPLETE:
        failed = manifest.get("failed_report_errors") or {}
        return {"campaign_id": campaign_id, "why": f"its last report cycle is {state or 'unknown'}"
                + (f"; failed: {', '.join(sorted(failed))}" if failed else ""),
                "errors": failed or ({"cycle": manifest.get("service_error")} if manifest.get("service_error") else {})}
    try:
        body = load_report_bodies(root, (DECISION_REPORT_CODE,)).get(DECISION_REPORT_CODE) or {}
    except BundleIncoherent as exc:
        body = {"error": str(exc)}
    body = body.get("body", body) if isinstance(body, dict) else {}
    return {"campaign_id": campaign_id, "root": root, "manifest": manifest, "tree": body.get("gate_tree"),
            "graphs_by_rung": body.get("graphs_by_rung"), "finds": _finds_of(body, campaign_id)}


def _finds_of(body: dict, campaign_id: str) -> list[dict] | str:
    from graph_scale_dynamics.research.finds import finds_of_report_28
    try:
        return finds_of_report_28(body, campaign=campaign_id)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:200]}"



def _finds(ready: list[dict], records: dict, *, sid: str, built: str) -> dict:
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.research import finds as FN
    found, failed = [], {}
    for part in ready:
        cid = part["campaign_id"]
        name = (records.get(cid) or {}).get("name")
        listed = part.get("finds")
        if isinstance(listed, str):
            failed[cid] = listed
            continue
        found += [dict(f, campaign_name=name, control="controls" in str(name or "")) for f in listed or []]
    out = FN.document(sid, BUILD_NUMBER, built, found)
    return dict(out, unavailable=failed) if failed else out


def _write_tar_zstd(target: Path, members) -> None:
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd executable is required for the study bundle")
    partial = target.with_name(target.name + ".partial")
    command = [zstd, f"-{BUNDLE_ZSTD_LEVEL}", "-T1", "-q", "-f", "-o", str(partial)]
    nice = shutil.which("nice") if os.name == "posix" else None
    if nice:
        command = [nice, "-n", "15", *command]
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        with tarfile.open(fileobj=proc.stdin, mode="w|") as archive:
            for name, payload in members:
                info = tarfile.TarInfo(name)
                info.mtime, info.mode = 0, 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        proc.stdin.close()
        code = proc.wait()
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        if code != 0:
            raise RuntimeError(f"zstd level {BUNDLE_ZSTD_LEVEL} failed with exit {code}: {stderr.strip()}")
        os.replace(partial, target)
    except BaseException:
        try:
            proc.kill()
        except OSError:
            pass
        partial.unlink(missing_ok=True)
        raise


def anchors_document(repo) -> dict:
    from collections import Counter

    from graph_scale_dynamics.research.anchors import ANCHOR_CONTRACT, listing
    try:
        anchors, why = listing(repo), None
    except Exception as exc:  # noqa: BLE001
        anchors, why = [], f"{type(exc).__name__}: {exc}"
    return {"contract": "gsd-study-anchors-1", "anchor_contract": ANCHOR_CONTRACT,
            "count": None if why else len(anchors),
            "by_status": dict(Counter(str(a.get("status") or "watching") for a in anchors)), "anchors": anchors,
            **({"unavailable": why} if why else {})}


def _advice_summary(document: dict) -> dict:
    from graph_scale_dynamics.research import advice
    return advice.summary(document)


def _absent(repo, campaign_ids: list[str]) -> list[dict]:
    from graph_scale_dynamics.operations import campaign_control as control
    asked = {str(cid) for cid in campaign_ids}
    out = []
    for row in repo.all_campaigns():
        cid = str(row["campaign_id"])
        if cid in asked:
            continue
        why = control.focus_problem(repo, row) or "it was not asked for in this request"
        out.append({"campaign_id": cid, "status": row.get("status"), "why": f"not in this request: {why}"})
    return out


def _science() -> tuple[dict, bytes | None]:
    try:
        return science_contract.science()
    except Exception as exc:  # noqa: BLE001
        return {"contract": science_contract.CONTRACT, "unavailable": f"{type(exc).__name__}: {str(exc)[:200]}"}, None


def _focus(repo) -> dict | None:
    from graph_scale_dynamics.operations import focus
    try:
        return focus.load(repo)
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _map_and_groups(repo) -> tuple[dict | None, dict | None]:
    from graph_scale_dynamics.operations import study_map
    from graph_scale_dynamics.scheduling import work_groups
    try:
        return study_map.load(repo), work_groups.reading(repo)
    except Exception as exc:  # noqa: BLE001
        return None, {"unavailable": f"{type(exc).__name__}: {str(exc)[:200]}"}


def build(base: Path, repo, campaign_ids: list[str], *, request_id: str | None = None,
          reporting_seconds: float | None = None, finished: list[str] | None = None,
          resumed_utc: str | None = None) -> dict:
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.operations import study
    from graph_scale_dynamics.reporting import study_front as F

    base = Path(base)
    sid, built = study_id(base, repo), _utc()
    stem = f"study_{sid}_{built.replace(':', '-')}"
    late = set(str(c) for c in campaign_ids) - set(str(c) for c in finished) if finished is not None else set()
    parts = [{"campaign_id": str(cid), "why": "its report cycle did not finish in this request"} if str(cid) in late
             else _part(base, str(cid)) for cid in campaign_ids]
    for part in parts:
        if "manifest" in part:
            try:
                check_coherence(part["root"], part["manifest"])
            except BundleIncoherent as exc:
                cid = part["campaign_id"]
                part.clear()
                part.update(campaign_id=cid, why=f"its reports are not one cycle: {exc}")
    absent = _absent(repo, campaign_ids)
    ready = [p for p in parts if "manifest" in p]
    counts_read = _read_utc()
    records = {str(cid): _campaign_record(repo, str(cid)) for cid in campaign_ids}
    calibration = _calibration(ready)
    read, unread = _read_parts(repo, ready, records, calibration)
    explorer = _explorer(repo, ready, records, read, unread, sid=sid, built=built, calibration=calibration)
    gate_trees = _gate_trees(repo, ready, records, read, sid=sid, built=built)
    anchors_read = _read_utc()
    anchors = anchors_document(repo)
    advice = _advice(repo, ready, records, read, unread, anchors=anchors)
    cost, classify = _front_parts(repo, ready, records, read)
    del read
    missing = [{"campaign_id": p["campaign_id"], "why": p["why"], **({"errors": p["errors"]} if p.get("errors") else {})}
               for p in parts if "why" in p] + absent
    stems = {part["campaign_id"]: _part_stem(part) for part in ready}
    finds = _finds(ready, records, sid=sid, built=built)
    gates = gates_ledger_document(repo, campaign_ids) if learns_alone(repo, campaign_ids) else None
    labels = {part["campaign_id"]: _label(repo, part, records) for part in ready}
    tables_read = _read_utc()
    study_tables = _tables(repo, [p["campaign_id"] for p in ready], blobs=base.parent / "blobs")
    read_utc = {"counts": counts_read, "anchors": anchors_read, "tables": tables_read,
                **({"fleet_resumed_utc": resumed_utc} if resumed_utc else {})}

    the_map, groups = _map_and_groups(repo)
    the_focus = _focus(repo)
    science, table = _science()

    def front_page(links: dict) -> bytes:
        campaigns = [dict(records[p["campaign_id"]], label=labels[p["campaign_id"]],
                          gate_tree=_tree_summary(p["tree"])) for p in ready]
        try:
            return F.render(study={"study_id": sid, "built_utc": built, "build_number": BUILD_NUMBER,
                                   "read_utc": read_utc},
                            campaigns=campaigns, links=links, advice=advice, cost=cost, classify=classify,
                            missing=missing).encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            from graph_scale_dynamics.reporting.study_explorer import unavailable
            return unavailable(f"Study {sid}", f"{type(exc).__name__}: {str(exc)[:200]}").encode("utf-8")

    document = {
        "contract": STUDY_BUNDLE_CONTRACT, "study_id": sid, "folder": str(study_tree(base)),
        "note": _study_note(base),
        "build_number": BUILD_NUMBER, "built_utc": built,
        "request_id": request_id, "axes": {k: {"values": list(v["values"]),
                                               "labels": [v["label"][x] for x in v["values"]]}
                                           for k, v in study.AXES.items()},
        "campaigns": [dict(records[p["campaign_id"]], bundle=stems[p["campaign_id"]],
                           report={"revision": p["manifest"].get("bundle_revision")
                                   or p["manifest"].get("source_revision"),
                                   "cycle_id": p["manifest"].get("bundle_cycle_id") or p["manifest"].get("cycle_id"),
                                   "finished_utc": p["manifest"].get("generation_finished_utc")},
                           gate_tree=_tree_summary(p["tree"]),
                           graphs_by_rung=(p.get("graphs_by_rung") or {}).get("rungs")) for p in ready],
        "missing": missing,
        "read_utc": dict(read_utc, reading=(
            "The reports are each campaign's cycle on the quiet fleet. The campaigns' counts, the anchors and the "
            "tables are read from the folder's rows when the bundle is made, at these times"
            + (", after the fleet was resumed, so they may run ahead of the reports" if resumed_utc else "") + ".")),
        "anchors": {"count": anchors["count"], "by_status": anchors["by_status"], "file": "anchors.json",
                    **({"unavailable": anchors["unavailable"]} if anchors.get("unavailable") else {})},
        **({"gates_ledger": {"file": "gates_ledger.json", "contract": gates.get("contract"),
                             "decisions_read": gates.get("decisions_read"),
                             **({"unavailable": gates["unavailable"]} if gates.get("unavailable") else {})}}
           if gates is not None else {}),
        "finds": {"file": "finds.json", "contract": finds.get("contract"), **(finds.get("counted") or {}),
                  **({"unavailable": finds["unavailable"]} if finds.get("unavailable") else {})},
        **({"map": {"file": "map.json", "contract": the_map.get("contract"),
                    "regions": len(the_map.get("regions") or {})}} if the_map else {}),
        **({"focus": {"file": "focus.json", "contract": the_focus.get("contract"),
                      "campaigns": the_focus.get("campaigns"), "done": len(the_focus.get("done") or []),
                      "regions": [region.get("name") for region in the_focus.get("regions") or []],
                      **{key: (the_focus.get("current") or {}).get(key) for key in ("law", "label", "stage")}}}
           if the_focus else {}),
        "work_groups": groups,
        "science": science,
        "advice": _advice_summary(advice), "front_page": "index.html", "gate_trees": "gate_trees.html",
        "tables": sorted(f"tables/{name}" for name in study_tables),
        "reading": ("One folder is one study. index.html is its front page: what the study found, what deserves a "
                    "closer look (advice.json) and what a law costs. explorer.html is every law at every rung, "
                    "filtered, drawn and listed; gate_trees.html every campaign's report 28 gate tree, rung by rung "
                    "(578); each a page with its data inside it. gates_ledger.json is every gate at every size, "
                    "learned from this study's own decisions (784). tables/ holds one "
                    "row per law, one per law and rung and one per draw, read from the folder's rows (tables/README.json). Each "
                    "campaign's part is its whole report bundle, after the study's own files."),
    }

    def members():
        yield f"{stem}/index.html", front_page(F.links_inside(stems))
        yield f"{stem}/explorer.html", explorer
        yield f"{stem}/gate_trees.html", gate_trees(_gate_tree_links("explorer.html", "index.html"))
        yield f"{stem}/study.json", _compact(document)
        yield f"{stem}/advice.json", _compact(advice)
        yield f"{stem}/anchors.json", _compact(anchors)
        if gates is not None:
            yield f"{stem}/gates_ledger.json", _compact(gates)
        yield f"{stem}/finds.json", _compact(finds)
        if the_map:
            yield f"{stem}/map.json", _compact(the_map)
        if the_focus:
            yield f"{stem}/focus.json", _compact(the_focus)
        if table is not None:
            yield f"{stem}/{science_contract.TABLE_IN_BUNDLE}", table
        for name in sorted(study_tables):
            yield f"{stem}/tables/{name}", study_tables[name]
        for part in ready:
            files, part_stem = bundle_files(part["root"], part["manifest"])
            if part_stem != stems[part["campaign_id"]]:
                raise BundleIncoherent(f"campaign {part['campaign_id']}'s part is {part_stem}, its manifest says "
                                       f"{stems[part['campaign_id']]}")
            for name in sorted(files):
                yield f"{stem}/{part_stem}/{name}", files[name]

    folder = bundles_dir(base)
    target = folder / f"{stem}.tar.zst"
    _write_tar_zstd(target, members())
    explorer_name, gates_name = f"{stem}.explorer.html", f"{stem}.gate_trees.html"
    front_name, advice_name = f"{stem}.index.html", f"{stem}.advice.json"
    _atomic_write(folder / explorer_name, explorer)
    _atomic_write(folder / gates_name, gate_trees(_gate_tree_links(explorer_name, front_name)))
    _atomic_write(folder / advice_name, json.dumps(advice, indent=1, sort_keys=True, default=str).encode("utf-8"))
    _atomic_write(folder / front_name, front_page(F.links_beside(stem)))
    payload_bytes = target.stat().st_size
    digest = hashlib.sha256()
    with open(target, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    entry = {"filename": target.name, "explorer": explorer_name, "gates": gates_name,
             "front": front_name, "advice": advice_name, "study_id": sid,
             "built_utc": built,
             "bytes": payload_bytes,
             "sha256": digest.hexdigest(), "build_number": BUILD_NUMBER, "request_id": request_id,
             "campaigns": [{"campaign_id": c["campaign_id"], "label": records[c["campaign_id"]]["quadrant"]["label"],
                            "state": records[c["campaign_id"]]["state"], "bundle": stems.get(c["campaign_id"]),
                            "laws": records[c["campaign_id"]].get("laws"),
                            "graphs": records[c["campaign_id"]].get("graphs"),
                            "seconds": c["manifest"].get("cycle_seconds")}
                           for c in ready],
             "missing": missing, "reporting_seconds": reporting_seconds}
    index = read_index(base)
    index["bundles"] = [entry] + [b for b in index.get("bundles") or [] if b.get("filename") != entry["filename"]]
    index.update(contract=STUDY_BUNDLE_CONTRACT, study_id=sid, updated_utc=built)
    _atomic_write(folder / INDEX_NAME, json.dumps(index, indent=1, sort_keys=True).encode("utf-8"))
    return entry
