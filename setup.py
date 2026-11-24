"""Build shim: this project's wheel is not platform-independent.

Everything about the build is declared in ``pyproject.toml``; this file exists
for one reason. The wheel ships ``runtime/bootstrap/linux-amd64/`` -- a
statically staged ``unshare``, loader and libc that let the folder-local
PostgreSQL come up in a user namespace without root. That makes the
distribution Linux x86-64 only, but the project has no extension modules, so
setuptools sees a pure-Python tree and tags the wheel ``py3-none-any``. Such a
wheel installs happily on macOS or aarch64 and then fails at the first attempt
to start a database, which is the worst possible time to discover it.

``tools/package_release.py`` refuses to publish a wheel that is not tagged
``py3-none-linux_x86_64``. Marking the root impure is what produces that tag:
the Python and ABI tags stay ``py3``/``none``, because the code really is pure
Python, and only the platform tag narrows.

Build 273. Before it, the release tool had never reached this check, because
the suite it runs first could not pass.
"""
import sysconfig

from setuptools import setup

try:  # setuptools >= 70.1 vendors the command
    from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel
except ImportError:  # pragma: no cover - older setuptools with the wheel package
    try:
        from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
    except ImportError:  # pragma: no cover - no wheel machinery available
        _bdist_wheel = None


if _bdist_wheel is not None:

    class bdist_wheel(_bdist_wheel):
        """Tag the wheel for the platform whose runtime it carries."""

        def finalize_options(self) -> None:
            super().finalize_options()
            # Supply the platform rather than marking the root impure. An
            # impure root sets `Root-Is-Purelib: false`, which remaps the
            # archive root to platlib and makes setuptools relocate every
            # module under `<name>.data/purelib/`. That still installs
            # correctly, but it is the wrong description: this project has no
            # extension modules, and its content belongs in purelib. It is
            # platform-bound only because of the bootstrap binaries it carries
            # as package data. Keeping the root pure leaves the tree at the
            # archive root, which is also what the release tool inspects.
            self.plat_name = sysconfig.get_platform().replace("-", "_").replace(".", "_")
            self.plat_name_supplied = True

        def get_tag(self) -> tuple[str, str, str]:
            # The code runs on any supported interpreter, so the Python and
            # ABI tags stay open and only the platform narrows.
            _python, _abi, platform = super().get_tag()
            return "py3", "none", platform

    CMDCLASS = {"bdist_wheel": bdist_wheel}
else:  # pragma: no cover
    CMDCLASS = {}


setup(cmdclass=CMDCLASS)
