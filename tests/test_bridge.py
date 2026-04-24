import unittest

from apple_notes_bridge import AppleNotesBridge


class AppleNotesBridgeTests(unittest.TestCase):
    def test_escape_for_applescript(self) -> None:
        bridge = AppleNotesBridge()
        self.assertEqual(bridge._escape_for_applescript('a"b\\c'), 'a\\"b\\\\c')

    def test_folder_path_applescript(self) -> None:
        bridge = AppleNotesBridge(account="iCloud")
        self.assertEqual(
            bridge._folder_path_applescript("Wiki/Sources"),
            'folder "Sources" of folder "Wiki" of account "iCloud"',
        )

    def test_list_notes_parses_output(self) -> None:
        bridge = AppleNotesBridge()
        bridge._run_applescript = lambda script: "id-1|||First\nid-2|||Second\n"  # type: ignore[method-assign]
        self.assertEqual(
            bridge.list_notes("Wiki/Sources"),
            [{"id": "id-1", "name": "First"}, {"id": "id-2", "name": "Second"}],
        )


if __name__ == "__main__":
    unittest.main()
