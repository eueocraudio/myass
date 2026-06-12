import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# GUI headless: renderiza num backend offscreen (sem display).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:  # noqa: BLE001
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 não disponível")
class TestAdminGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_builds_and_is_safe_without_client(self):
        from myass.client.admin_gui import AdminWindow
        win = AdminWindow(client=None)
        # As ações não devem quebrar sem conexão (guard -> status informativo).
        win._refresh_catalog()
        win._refresh_occurrences()
        win._refresh_env()
        win._publish_bot()
        self.assertIn("Sem conexão", win.status.text())
        win.close()


if __name__ == "__main__":
    unittest.main()
