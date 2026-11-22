from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_app = importlib.import_module("link_glancer.app")
_database = importlib.import_module("link_glancer.tasks.database")


class DatabaseResetTests(unittest.TestCase):
    def tearDown(self) -> None:
        _database.consume_database_reset_summary()

    def test_reset_app_database_creates_backup_before_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_path = root / "app.db"
            database_path.write_bytes(b"legacy-db")
            backup_dir = root / "database-backups"
            backup_dir.mkdir()

            with (
                patch.object(_database, "app_database_path", return_value=database_path),
                patch.object(
                    _database,
                    "ensure_database_backups_dir",
                    return_value=backup_dir,
                ),
            ):
                result = _database.reset_app_database()

            self.assertEqual(database_path, result)
            backup_paths = list(backup_dir.glob("app_*.db"))
            self.assertEqual(1, len(backup_paths))
            self.assertEqual(b"legacy-db", backup_paths[0].read_bytes())

            summary = _database.consume_database_reset_summary()
            self.assertIsNotNone(summary)
            if summary is None:
                self.fail("expected database reset summary")
            self.assertEqual("用户确认重建数据库。", summary.reason)
            self.assertEqual(backup_paths[0], summary.backup_path)

    def test_reset_app_database_aborts_when_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_path = root / "app.db"
            database_path.write_bytes(b"legacy-db")
            backup_dir = root / "database-backups"
            backup_dir.mkdir()

            with (
                patch.object(_database, "app_database_path", return_value=database_path),
                patch.object(
                    _database,
                    "ensure_database_backups_dir",
                    return_value=backup_dir,
                ),
                patch.object(_database.shutil, "copy2", side_effect=OSError("locked")),
            ):
                with self.assertRaisesRegex(RuntimeError, "无法备份现有数据库文件"):
                    _database.reset_app_database()

            self.assertTrue(database_path.exists())
            self.assertEqual(b"legacy-db", database_path.read_bytes())
            self.assertIsNone(_database.consume_database_reset_summary())


class ApplicationStartupTests(unittest.TestCase):
    def test_create_application_exits_silently_when_database_reset_is_cancelled(self) -> None:
        app_instance = MagicMock()
        tray_icon = MagicMock()
        instance_registration = MagicMock(instance_id=1)

        with (
            patch.object(_app, "_set_windows_app_user_model_id"),
            patch.object(_app, "QApplication", MagicMock(return_value=app_instance)),
            patch.object(_app, "register_instance", return_value=instance_registration),
            patch.object(_app, "bundled_asset_path", return_value=Path("missing.svg")),
            patch.object(_app, "QSystemTrayIcon", MagicMock(return_value=tray_icon)),
            patch.object(_app, "QStyleFactory") as style_factory,
            patch.object(_app, "apply_application_font"),
            patch.object(_app, "_apply_color_scheme"),
            patch.object(
                _app,
                "_create_main_window_with_database_recovery",
                side_effect=_app.StartupCancelledError(),
            ),
            patch.object(_app, "QMessageBox") as message_box,
        ):
            style_factory.create.return_value = object()
            with self.assertRaises(SystemExit) as exc_info:
                _app.create_application()

        self.assertEqual(0, exc_info.exception.code)
        message_box.critical.assert_not_called()
        tray_icon.hide.assert_called_once()
        instance_registration.release.assert_called_once()
