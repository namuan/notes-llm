import json
import tempfile
import unittest
from pathlib import Path

from state_manager import WikiState, load_state, save_state


class StateManagerTests(unittest.TestCase):
    def test_save_then_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            state = WikiState(notes={"_Index": {"apple_notes_id": "abc"}})
            save_state(path, state)
            loaded = load_state(path)
            self.assertEqual(loaded.notes["_Index"]["apple_notes_id"], "abc")
            self.assertTrue(path.with_suffix(".json.bak").exists())

    def test_load_uses_backup_when_primary_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            backup = path.with_suffix(".json.bak")
            path.write_text("{bad json", encoding="utf-8")
            backup.write_text(
                json.dumps({"version": 1, "notes": {"x": {}}}), encoding="utf-8"
            )
            loaded = load_state(path)
            self.assertIn("x", loaded.notes)


if __name__ == "__main__":
    unittest.main()
