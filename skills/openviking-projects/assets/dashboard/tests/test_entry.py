import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import manage
REAL_RESPONSE = manage.response


class StudioEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.studio = self.base / "studio"
        self.runtime = self.base / "state"
        self.studio.mkdir()
        self.runtime.mkdir()
        self.original = b"<html><title>Original Studio</title></html>"
        (self.studio / "index.html").write_bytes(self.original)
        for name, value in [("RUNTIME", self.runtime), ("response", lambda: True), ("studio_dir", lambda: self.studio), ("studio_url", lambda: "http://127.0.0.1:21933/studio/home"), ("URL", "http://127.0.0.1:21934")]:
            patched = patch.object(manage, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def test_entry_install_is_idempotent_and_restores_exact_original(self):
        self.assertEqual(manage.install_entry()["status"], "installed")
        self.assertEqual(manage.install_entry()["status"], "already_installed")
        self.assertEqual((self.studio / "classic.html").read_bytes(), self.original)
        self.assertEqual(manage.restore_entry()["status"], "restored")
        self.assertEqual((self.studio / "index.html").read_bytes(), self.original)
        self.assertFalse((self.studio / "local-entry.js").exists())

    def test_entry_respects_configured_service_and_dashboard_ports(self):
        result = manage.install_entry()
        self.assertEqual(result["url"], "http://127.0.0.1:21933/studio/home")
        self.assertIn('http://127.0.0.1:21934/', (self.studio / "local-entry.js").read_text())
        self.assertIn('http://127.0.0.1:21934/', (self.studio / "index.html").read_text())

    def test_other_state_cannot_be_mistaken_for_this_dashboard(self):
        import io
        from contextlib import nullcontext
        class Opener:
            def open(self, *args, **kwargs):
                return nullcontext(io.StringIO('{"app":"openviking-local-dashboard","instance":"another-home"}'))
        with patch.object(manage, "build_opener", return_value=Opener()):
            self.assertFalse(REAL_RESPONSE())

    def test_restore_preserves_an_entry_edited_after_installation(self):
        manage.install_entry()
        user_edit = b"User changed the entry after installation"
        (self.studio / "index.html").write_bytes(user_edit)
        with self.assertRaises(RuntimeError):
            manage.restore_entry()
        self.assertEqual((self.studio / "index.html").read_bytes(), user_edit)


if __name__ == "__main__":
    unittest.main()
