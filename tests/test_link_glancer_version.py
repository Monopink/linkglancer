from __future__ import annotations

import importlib.util
import sys
import tomllib
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _load_src_module(module_name: str, relative_path: str):
    package_name = module_name.split(".", 1)[0]
    package_path = SRC_ROOT / package_name
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_path)]
        sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(module_name, SRC_ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {module_name} from {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_src_module("link_glancer", "link_glancer/__init__.py")
_version_core = _load_src_module("link_glancer.version_core", "link_glancer/version_core.py")
_version = _load_src_module("link_glancer.version", "link_glancer/version.py")
_creator_version = _load_src_module(
    "creator_enrichment.version",
    "creator_enrichment/version.py",
)


class LinkGlancerVersionTests(unittest.TestCase):
    def test_public_version_text_uses_three_segments(self) -> None:
        self.assertEqual("v0.3.4", _version.public_version_text())

    def test_internal_version_text_uses_four_segments(self) -> None:
        self.assertEqual("v0.3.4.8", _version.internal_version_text())

    def test_internal_version_inherits_public_version_prefix(self) -> None:
        self.assertEqual(
            f"v{_version_core.PUBLIC_VERSION}.{_creator_version.CREATOR_ENRICHMENT_BUILD}",
            _creator_version.CREATOR_ENRICHMENT_IMPL_VERSION,
        )

    def test_pyproject_uses_dynamic_version_source(self) -> None:
        config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = config["project"]
        self.assertNotIn("version", project)
        self.assertIn("version", project["dynamic"])
        self.assertEqual(
            "link_glancer.__version__",
            config["tool"]["setuptools"]["dynamic"]["version"]["attr"],
        )


if __name__ == "__main__":
    unittest.main()
