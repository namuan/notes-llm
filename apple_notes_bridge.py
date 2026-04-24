from __future__ import annotations

import subprocess


class AppleScriptError(Exception):
    pass


class AppleNotesBridge:
    """Interface to Apple Notes via osascript."""

    def __init__(self, account: str = "iCloud"):
        self.account = account

    def _run_applescript(self, script: str) -> str:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise AppleScriptError(
                result.stderr.strip() or "AppleScript execution failed"
            )
        return result.stdout.strip()

    def _escape_for_applescript(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def _folder_path_applescript(self, folder_path: str) -> str:
        parts = [part for part in folder_path.split("/") if part]
        reference = f'account "{self._escape_for_applescript(self.account)}"'
        for part in parts:
            reference = f'folder "{self._escape_for_applescript(part)}" of {reference}'
        return reference

    def create_folder(self, folder_path: str) -> None:
        parts = [part for part in folder_path.split("/") if part]
        for index, name in enumerate(parts):
            parent = "/".join(parts[:index])
            parent_ref = (
                self._folder_path_applescript(parent)
                if parent
                else f'account "{self._escape_for_applescript(self.account)}"'
            )
            script = f'''
                tell application "Notes"
                    make new folder at {parent_ref} with properties {{name:"{self._escape_for_applescript(name)}"}}
                end tell
            '''
            try:
                self._run_applescript(script)
            except AppleScriptError:
                continue

    def list_folders(self, parent: str = "") -> list[str]:
        reference = (
            self._folder_path_applescript(parent)
            if parent
            else f'account "{self._escape_for_applescript(self.account)}"'
        )
        script = f"""
            tell application "Notes"
                get name of every folder of {reference}
            end tell
        """
        output = self._run_applescript(script)
        if not output:
            return []
        return [part.strip() for part in output.split(",") if part.strip()]

    def create_note(self, folder_path: str, title: str, html_body: str) -> str:
        folder_ref = self._folder_path_applescript(folder_path)
        script = f'''
            tell application "Notes"
                set newNote to make new note at {folder_ref} with properties {{name:"{self._escape_for_applescript(title)}", body:"{self._escape_for_applescript(html_body)}"}}
                return id of newNote
            end tell
        '''
        return self._run_applescript(script)

    def read_note(self, note_id: str) -> dict[str, str]:
        script = f'''
            tell application "Notes"
                set n to note id "{self._escape_for_applescript(note_id)}"
                set noteName to name of n
                set noteBody to body of n
                set noteFolder to name of container of n
                return noteName & "|||DELIM|||" & noteBody & "|||DELIM|||" & noteFolder
            end tell
        '''
        output = self._run_applescript(script)
        parts = output.split("|||DELIM|||")
        return {
            "id": note_id,
            "name": parts[0] if len(parts) > 0 else "",
            "body": parts[1] if len(parts) > 1 else "",
            "folder": parts[2] if len(parts) > 2 else "",
        }

    def update_note(self, note_id: str, html_body: str) -> None:
        script = f'''
            tell application "Notes"
                set body of note id "{self._escape_for_applescript(note_id)}" to "{self._escape_for_applescript(html_body)}"
            end tell
        '''
        self._run_applescript(script)

    def list_notes(self, folder_path: str) -> list[dict[str, str]]:
        folder_ref = self._folder_path_applescript(folder_path)
        script = f"""
            tell application "Notes"
                set noteList to every note of {folder_ref}
                set output to ""
                repeat with n in noteList
                    set output to output & (id of n) & "|||" & (name of n) & "\\n"
                end repeat
                return output
            end tell
        """
        output = self._run_applescript(script)
        notes: list[dict[str, str]] = []
        for line in output.splitlines():
            if "|||" not in line:
                continue
            note_id, name = line.split("|||", 1)
            notes.append({"id": note_id.strip(), "name": name.strip()})
        return notes

    def delete_note(self, note_id: str) -> None:
        script = f'''
            tell application "Notes"
                delete note id "{self._escape_for_applescript(note_id)}"
            end tell
        '''
        self._run_applescript(script)

    def find_notes_by_name(
        self, query: str, folder_path: str = ""
    ) -> list[dict[str, str]]:
        scope = (
            f"of {self._folder_path_applescript(folder_path)}"
            if folder_path
            else f'of account "{self._escape_for_applescript(self.account)}"'
        )
        script = f'''
            tell application "Notes"
                set matches to every note {scope} whose name contains "{self._escape_for_applescript(query)}"
                set output to ""
                repeat with n in matches
                    set output to output & (id of n) & "|||" & (name of n) & "\\n"
                end repeat
                return output
            end tell
        '''
        output = self._run_applescript(script)
        matches: list[dict[str, str]] = []
        for line in output.splitlines():
            if "|||" not in line:
                continue
            note_id, name = line.split("|||", 1)
            matches.append({"id": note_id.strip(), "name": name.strip()})
        return matches
