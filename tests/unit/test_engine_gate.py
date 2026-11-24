import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _main():
    spec = importlib.util.spec_from_file_location("gsd_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_gate_reads_the_available_flag_not_the_key(monkeypatch, capsys):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "rust")
    monkeypatch.setattr(main, "_default_engine_available", lambda: False)
    monkeypatch.setattr(main, "_engine_toolchain", lambda: {"cargo": None, "maturin": None, "path": ""})
    assert main._refuse_without_default_engine() == 2
    assert "prepare_environment.sh" in capsys.readouterr().out


def _registry(monkeypatch, *, stale=None, current_after_build=True):
    from graph_scale_dynamics.services.worker import engine_registry
    monkeypatch.setattr(engine_registry, "stale_rust_engine", lambda root=None: stale)
    monkeypatch.setattr(engine_registry, "rust_engine_current_after_build", lambda root=None: current_after_build)


def test_an_installed_engine_passes_the_gate(monkeypatch):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "rust")
    _registry(monkeypatch)
    monkeypatch.setattr(main, "_default_engine_available", lambda: True)
    assert main._refuse_without_default_engine() is None


def test_a_host_with_a_toolchain_builds_instead_of_refusing(monkeypatch, capsys):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "rust")
    _registry(monkeypatch)
    state = {"available": False, "built": 0}
    monkeypatch.setattr(main, "_default_engine_available", lambda: state["available"])
    monkeypatch.setattr(main, "_engine_toolchain", lambda: {"cargo": "/x/cargo", "maturin": "/x/maturin", "path": ""})

    class _Done:
        returncode = 0

    def fake_run(cmd, **_):
        assert cmd[-1].endswith("tools/build_engine.sh")
        state["built"] += 1
        state["available"] = True
        return _Done()

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    assert main._refuse_without_default_engine() is None
    assert state["built"] == 1
    assert "building it now" in capsys.readouterr().out


def test_python_on_purpose_is_not_gated(monkeypatch):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "python")
    monkeypatch.setattr(main, "_default_engine_available", lambda: False)
    assert main._refuse_without_default_engine() is None


def test_an_engine_built_from_other_sources_is_rebuilt_not_run(monkeypatch, capsys):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "rust")
    _registry(monkeypatch, stale="the installed gsd_engine_rs is 0.327.0 and this tree's engine_rs is 0.457.0")
    monkeypatch.setattr(main, "_default_engine_available", lambda: True)
    monkeypatch.setattr(main, "_engine_toolchain", lambda: {"cargo": "/x/cargo", "maturin": "/x/maturin", "path": ""})
    built = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **_: built.append(cmd) or _Done())
    assert main._refuse_without_default_engine() is None
    assert len(built) == 1 and built[0][-1].endswith("tools/build_engine.sh")
    assert "0.327.0" in capsys.readouterr().out


def test_a_build_that_leaves_the_engine_stale_refuses(monkeypatch, capsys):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "rust")
    _registry(monkeypatch, stale="the installed gsd_engine_rs is 0.1.0 and this tree's engine_rs is 0.457.0",
              current_after_build=False)
    monkeypatch.setattr(main, "_default_engine_available", lambda: True)
    monkeypatch.setattr(main, "_engine_toolchain", lambda: {"cargo": "/x/cargo", "maturin": "/x/maturin", "path": ""})

    class _Done:
        returncode = 0

    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **_: _Done())
    assert main._refuse_without_default_engine() == 2
    assert "did not produce a current gsd_engine_rs" in capsys.readouterr().out


def test_a_stale_engine_without_a_toolchain_says_it_is_stale(monkeypatch, capsys):
    main = _main()
    monkeypatch.setenv("GSD_ENGINE", "rust")
    _registry(monkeypatch, stale="the installed gsd_engine_rs is 0.1.0 and this tree's engine_rs is 0.457.0")
    monkeypatch.setattr(main, "_default_engine_available", lambda: True)
    monkeypatch.setattr(main, "_engine_toolchain", lambda: {"cargo": None, "maturin": None, "path": ""})
    assert main._refuse_without_default_engine() == 2
    out = capsys.readouterr().out
    assert "0.1.0" in out and "not importable" not in out


def test_the_source_version_is_the_package_version(tmp_path):
    from graph_scale_dynamics.services.worker.engine_registry import rust_source_version
    (tmp_path / "engine_rs").mkdir()
    (tmp_path / "engine_rs" / "Cargo.toml").write_text(
        '[package]\nname = "gsd_engine_rs"\nversion = "9.8.7"\n\n[dependencies]\n'
        'pyo3 = { version = "0.23" }\n[profile.release]\nopt-level = 3\n')
    assert rust_source_version(tmp_path) == "9.8.7"
    assert rust_source_version(tmp_path / "nowhere") is None


def test_the_stale_check_compares_the_module_with_the_tree(tmp_path, monkeypatch):
    from tests.support.engines import require_rust_engine
    gsd_engine_rs = require_rust_engine()
    from graph_scale_dynamics.services.worker.engine_registry import stale_rust_engine
    (tmp_path / "engine_rs").mkdir()
    (tmp_path / "engine_rs" / "Cargo.toml").write_text('[package]\nname = "gsd_engine_rs"\nversion = "1.2.3"\n')
    monkeypatch.setattr(gsd_engine_rs, "FINGERPRINT", "1.2.3", raising=False)
    assert stale_rust_engine(tmp_path) is None
    monkeypatch.setattr(gsd_engine_rs, "FINGERPRINT", "0.327.0", raising=False)
    reason = stale_rust_engine(tmp_path)
    assert "0.327.0" in reason and "1.2.3" in reason
