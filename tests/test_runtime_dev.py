from __future__ import annotations

import importlib.util
import sys
import tempfile
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


_runtime_dev = _load_src_module("link_glancer.runtime.dev", "link_glancer/runtime/dev.py")


class RuntimeDevTests(unittest.TestCase):
    def test_jsonl_dev_logger_writes_text_artifact_to_separate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            original_ensure_logs_dir = _runtime_dev.ensure_logs_dir
            _runtime_dev.ensure_logs_dir = lambda: temp_root
            try:
                logger = _runtime_dev.JsonlDevLogger(
                    module="creator_enrichment",
                    file_stem="creator_enrichment_task_2",
                )
                artifact_path = logger.write_text_artifact(
                    name="creator_enrichment_task_2_item_171_attempt_1",
                    content="diagnostic content",
                )
            finally:
                _runtime_dev.ensure_logs_dir = original_ensure_logs_dir
            self.assertIsNotNone(artifact_path)
            assert artifact_path is not None
            self.assertTrue(artifact_path.exists())
            self.assertEqual("diagnostic content", artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact_path.parent, logger.artifact_dir)
            self.assertIn("_artifacts", str(artifact_path.parent))
            self.assertTrue(artifact_path.name.endswith(".txt"))


if __name__ == "__main__":
    unittest.main()
