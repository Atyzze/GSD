import ast, re
from pathlib import Path
from tests.support import split_sources

ROOT = Path(__file__).resolve().parents[2]

SHIPPED_SCHEMA_SHA256 = "be568138ca72b98155c873cc71c8fa5da2a204c08d672b91d02791391e9c2ec1"


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_domain_depends_on_nothing_local():
    for path in (ROOT / "graph_scale_dynamics/domain").rglob("*.py"):
        for module in imports_of(path):
            assert not module.startswith(("graph_scale_dynamics.services", "graph_scale_dynamics.")), f"{path.name} imports {module}"


def test_engine_and_dsl_are_blind():
    forbidden_imports = ("graph_scale_dynamics.measurements", "graph_scale_dynamics.scaleflow", "graph_scale_dynamics.db",
                         "graph_scale_dynamics.services", "graph_scale_dynamics.scheduling", "graph_scale_dynamics.artifact_store")
    banned_tokens = re.compile(r"hausdorff|spectral|\bd_H\b|\bd_s\b|dimension", re.IGNORECASE)
    for package in ("graph_scale_dynamics/engine", "graph_scale_dynamics/dsl"):
        for path in (ROOT / package).rglob("*.py"):
            for module in imports_of(path):
                assert not module.startswith(forbidden_imports), f"{path} imports {module}"
            source = path.read_text()
            assert not banned_tokens.search(source), f"{path} references dimensional concepts"


def test_apps_only_executor_orchestrates_other_apps():
    allowed = {"graph_scale_dynamics.services.worker", "graph_scale_dynamics.services.analyzer"}
    for app_dir in (ROOT / "graph_scale_dynamics" / "services").iterdir():
        if not app_dir.is_dir():
            continue
        own = f"graph_scale_dynamics.services.{app_dir.name}"
        for path in app_dir.rglob("*.py"):
            for module in imports_of(path):
                if not module.startswith("graph_scale_dynamics.services.") or module.startswith(own):
                    continue
                if app_dir.name == "executor" and any(
                    module == prefix or module.startswith(prefix + ".") for prefix in allowed
                ):
                    continue
                raise AssertionError(f"{path} imports {module}")


def test_analyzer_never_mutates_simulation_records():
    source = (ROOT / "graph_scale_dynamics/services/analyzer/main.py").read_text()
    assert "finish_job" not in source and "insert_job" not in source


def test_proposer_reads_summaries_never_physics():
    for path in (ROOT / "graph_scale_dynamics/services/proposer").rglob("*.py"):
        for module in imports_of(path):
            assert not module.startswith(("graph_scale_dynamics.engine", "graph_scale_dynamics.measurements",
                                          "graph_scale_dynamics.scaleflow")), f"{path} imports {module}"


def test_calibration_suite_stays_inside_its_declared_boundary():
    forbidden = ("graph_scale_dynamics.services", "graph_scale_dynamics.db",
                 "graph_scale_dynamics.scheduling", "graph_scale_dynamics.readmodel",
                 "graph_scale_dynamics.reporting", "graph_scale_dynamics.research",
                 "graph_scale_dynamics.artifact_store")
    from graph_scale_dynamics.calibration.admission import DECLARED_BOUNDARY_IMPORTS
    package = ROOT / "graph_scale_dynamics" / "calibration"
    assert package.is_dir()
    for path in package.rglob("*.py"):
        for module in imports_of(path):
            if not module.startswith(forbidden):
                continue
            if path.name == "admission.py" and module in DECLARED_BOUNDARY_IMPORTS:
                continue
            raise AssertionError(f"{path.relative_to(ROOT)} imports {module} across the suite boundary")


def test_only_the_entry_points_reach_into_the_calibration_suite():
    public = {"graph_scale_dynamics.calibration"}
    package = ROOT / "graph_scale_dynamics"
    offenders = []
    for path in package.rglob("*.py"):
        if "calibration" in path.relative_to(package).parts[:1]:
            continue
        for module in imports_of(path):
            if module.startswith("graph_scale_dynamics.calibration") and module not in public:
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")
    assert not offenders, "\n".join(offenders)


def test_the_shipped_schema_matches_the_ledger_of_the_previous_release():
    import hashlib
    schema = ROOT / "graph_scale_dynamics" / "resources" / "schema" / "schema.sql"
    digest = hashlib.sha256(schema.read_bytes()).hexdigest()
    assert digest == SHIPPED_SCHEMA_SHA256, (
        f"schema.sql changed ({digest[:12]} vs {SHIPPED_SCHEMA_SHA256[:12]}). Every existing "
        "database will refuse to start with SchemaLedgerMismatch and must be archived and "
        "reinitialised. If that is intended, update SHIPPED_SCHEMA_SHA256 and record the "
        "migration in the build notes."
    )


def test_every_column_the_runtime_writes_exists_in_the_shipped_schema():
    import re
    schema = (ROOT / "graph_scale_dynamics" / "resources" / "schema" / "schema.sql").read_text()
    repo = split_sources.source(split_sources.REPO_MODULES)
    tables = {}
    for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)", schema, flags=re.S):
        body = match.group(2)
        tables[match.group(1)] = {
            line.strip().split()[0].strip(",")
            for line in body.splitlines()
            if line.strip() and not line.strip().upper().startswith(("CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "--"))
        }
    missing = []
    for table, columns in re.findall(r'INSERT INTO (\w+)\(([\w,]+)\)', repo):
        known = tables.get(table)
        if known is None:
            continue
        for column in columns.split(","):
            if column and column not in known:
                missing.append(f"{table}.{column}")
    for table, assignments in re.findall(r'UPDATE (\w+) SET ([^"]+)', repo):
        known = tables.get(table)
        if known is None:
            continue
        for column in re.findall(r'(\w+)=', assignments):
            if column not in known and column not in {"WHERE", "AND", "OR"} and not column.isupper():
                missing.append(f"{table}.{column}")
    assert not sorted(set(missing)), (
        "repo.py writes columns the shipped schema does not declare: "
        f"{sorted(set(missing))}. The schema was reverted to the wrong baseline."
    )
