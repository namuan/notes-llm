# Apple Notes Wiki Daemon — Technical Specification

**Project:** Background daemon that maintains a personal knowledge wiki inside Apple Notes, powered by an LLM.

**Summary:** A Python-based macOS daemon that watches a local folder for new source files, calls the Anthropic API to analyze them, and autonomously creates/updates a structured wiki of interlinked notes inside the Apple Notes app. The user drops files into a folder and reads the resulting wiki in Apple Notes on any Apple device. All syncing, encryption, and cross-device availability come from iCloud for free.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                    macOS Host                     │
│                                                   │
│  ┌────────────┐    ┌───────────────────────────┐  │
│  │  ~/Wiki/   │    │    wiki-daemon (Python)    │  │
│  │  inbox/    │───▶│                            │  │
│  │  processed/│◀───│  1. Detect new files       │  │
│  │  config.yml│    │  2. Read existing wiki     │  │
│  │  state.json│    │     from Apple Notes       │  │
│  │  daemon.log│    │  3. Call Anthropic API      │  │
│  └────────────┘    │  4. Push updates to         │  │
│                    │     Apple Notes via          │  │
│                    │     AppleScript              │  │
│                    │  5. Update state.json        │  │
│                    └──────────┬────────────────┘  │
│                               │                   │
│  ┌────────────────────────────▼────────────────┐  │
│  │           Apple Notes.app                    │  │
│  │  ┌─────────────────────────────────────┐     │  │
│  │  │  Wiki/                              │     │  │
│  │  │    📝 _Index                        │     │  │
│  │  │    📝 _Log                          │     │  │
│  │  │  Wiki/Sources/                      │     │  │
│  │  │    📝 Summary: <article title>      │     │  │
│  │  │  Wiki/Entities/                     │     │  │
│  │  │    📝 <Person or Company>           │     │  │
│  │  │  Wiki/Concepts/                     │     │  │
│  │  │    📝 <Topic name>                  │     │  │
│  │  │  Wiki/Synthesis/                    │     │  │
│  │  │    📝 Overview                      │     │  │
│  │  │    📝 Open Questions                │     │  │
│  │  └─────────────────────────────────────┘     │  │
│  └──────────────────────────────────────────────┘  │
│                       │  iCloud Sync                │
└───────────────────────┼────────────────────────────┘
                        ▼
              📱 iPhone / iPad
              (read-only browsing)
```

**Three layers (from the original pattern):**

1. **Raw sources** — files dropped into `~/Wiki/inbox/`. Immutable. The daemon reads from them but never modifies them.
2. **The wiki** — notes inside Apple Notes, organized into subfolders. The daemon owns this layer entirely. It creates notes, updates them, maintains cross-references.
3. **The schema** — `config.yml` plus the system prompt embedded in the daemon. Tells the LLM how the wiki is structured, what conventions to follow, what output format to use.

---

## 2. File System Layout

```
~/Wiki/
├── inbox/                    # Drop source files here
│   ├── article.md
│   ├── paper.pdf
│   └── notes.txt
├── processed/                # Daemon moves files here after ingestion
│   └── 2026-04-24_article.md
├── config.yml                # User configuration
├── state.json                # Daemon state (note IDs, checksums, timestamps)
├── schema.md                 # Wiki schema prompt (co-evolved with LLM)
├── daemon.log                # Operational log (rotating)
└── cache/                    # Temporary working files
    └── extracted/            # Extracted text from PDFs, images, etc.
```

### 2.1 `config.yml`

```yaml
# Apple Notes configuration
notes_account: "iCloud"           # Which Notes account to use
wiki_folder: "Wiki"               # Top-level folder in Apple Notes
subfolders:                        # Auto-created subfolders
  - "Sources"
  - "Entities"
  - "Concepts"
  - "Synthesis"

# LLM configuration — supports any OpenAI-compatible API
# The daemon uses the OpenAI chat completions format (POST /v1/chat/completions)
# which is supported by: Anthropic, OpenAI, Ollama, LM Studio, vLLM, Together,
# Groq, Fireworks, Mistral, Azure OpenAI, OpenRouter, and many others.

llm:
  # Default profile used for ingestion
  default_profile: "anthropic-sonnet"

  # Profile used for lint (can be a stronger model)
  lint_profile: "anthropic-sonnet"

  # Named profiles — switch between backends by changing default_profile
  profiles:
    anthropic-sonnet:
      base_url: "https://api.anthropic.com/v1/"
      api_key_env: "ANTHROPIC_API_KEY"        # env var name (never store key in file)
      model: "claude-sonnet-4-20250514"
      max_tokens: 8192
      extra_headers:                           # optional: provider-specific headers
        anthropic-version: "2023-06-01"

    anthropic-opus:
      base_url: "https://api.anthropic.com/v1/"
      api_key_env: "ANTHROPIC_API_KEY"
      model: "claude-opus-4-20250514"
      max_tokens: 8192
      extra_headers:
        anthropic-version: "2023-06-01"

    openai:
      base_url: "https://api.openai.com/v1/"
      api_key_env: "OPENAI_API_KEY"
      model: "gpt-4o"
      max_tokens: 8192

    ollama:
      base_url: "http://localhost:11434/v1/"
      api_key_env: ""                          # Ollama doesn't need a key
      api_key_value: "ollama"                  # placeholder; some clients require non-empty
      model: "llama3.1:70b"
      max_tokens: 4096

    lmstudio:
      base_url: "http://localhost:1234/v1/"
      api_key_env: ""
      api_key_value: "lm-studio"
      model: "local-model"
      max_tokens: 4096

    openrouter:
      base_url: "https://openrouter.ai/api/v1/"
      api_key_env: "OPENROUTER_API_KEY"
      model: "anthropic/claude-sonnet-4"
      max_tokens: 8192

    # Add your own profiles here. Any OpenAI-compatible endpoint works.

# Daemon behavior
poll_interval_seconds: 30          # How often to check inbox (if not using fswatch)
use_fswatch: true                  # Use file system events instead of polling
batch_mode: false                  # true = ingest all inbox files at once
                                   # false = ingest one at a time, wait for next cycle

# Lint schedule (cron-style, run by separate LaunchAgent)
lint_enabled: true
lint_hour: 3                       # Run lint at 3 AM daily

# File handling
supported_extensions:
  - ".md"
  - ".txt"
  - ".pdf"
  - ".html"
  - ".csv"
  - ".json"
max_file_size_mb: 10

# Wiki conventions
max_note_length_chars: 30000       # Apple Notes has no hard limit but performance degrades
cross_reference_style: "inline"    # "inline" = mention in text, "section" = Related Notes section
```

### 2.2 `state.json`

```json
{
  "version": 1,
  "last_run": "2026-04-24T14:30:00Z",
  "last_lint": "2026-04-24T03:00:00Z",
  "notes": {
    "_Index": {
      "apple_notes_id": "x-coredata://ABC123/ICNote/p42",
      "last_updated": "2026-04-24T14:30:00Z",
      "checksum": "sha256:abc123..."
    },
    "Sources/Summary: The Attention Paper": {
      "apple_notes_id": "x-coredata://ABC123/ICNote/p43",
      "last_updated": "2026-04-24T14:25:00Z",
      "source_file": "attention_is_all_you_need.pdf",
      "checksum": "sha256:def456..."
    }
  },
  "processed_files": {
    "attention_is_all_you_need.pdf": {
      "processed_at": "2026-04-24T14:25:00Z",
      "file_hash": "sha256:789abc...",
      "notes_created": ["Sources/Summary: The Attention Paper"],
      "notes_updated": ["_Index", "Concepts/Transformer Architecture", "Entities/Google Brain"]
    }
  },
  "folders_created": ["Wiki", "Wiki/Sources", "Wiki/Entities", "Wiki/Concepts", "Wiki/Synthesis"]
}
```

---

## 3. AppleScript Bridge Module

This is the most critical component. All communication with Apple Notes happens through AppleScript, invoked from Python via `subprocess.run(["osascript", "-e", script])`.

### 3.1 Available AppleScript Operations

Apple Notes has a limited but sufficient scripting dictionary:

| Operation | AppleScript | Notes |
|-----------|-------------|-------|
| List all folders | `tell application "Notes" to get name of every folder of account "iCloud"` | Returns flat list; subfolders need recursive traversal |
| Create folder | `tell application "Notes" to make new folder at account "iCloud" with properties {name:"Wiki"}` | Subfolders: `make new folder at folder "Wiki" of account "iCloud"` |
| List notes in folder | `tell application "Notes" to get {id, name} of every note of folder "Sources" of folder "Wiki" of account "iCloud"` | Returns parallel lists |
| Read note body | `tell application "Notes" to get body of note id "x-coredata://..." of account "iCloud"` | Returns HTML string |
| Create note | `tell application "Notes" to make new note at folder "Sources" of folder "Wiki" of account "iCloud" with properties {name:"Title", body:"<html>..."}` | Body is HTML |
| Update note body | `tell application "Notes" to set body of note id "x-coredata://..." to "<html>..."` | Full replacement only — no append or partial edit |
| Delete note | `tell application "Notes" to delete note id "x-coredata://..."` | Moves to Recently Deleted |
| Search notes | `tell application "Notes" to get name of every note of account "iCloud" whose name contains "query"` | Name-only search; body search not supported via AppleScript |

### 3.2 Python Bridge Implementation

```python
# apple_notes_bridge.py

import subprocess
import json
import html
import re
from typing import Optional

class AppleNotesBridge:
    """Interface to Apple Notes via osascript (AppleScript)."""

    def __init__(self, account: str = "iCloud"):
        self.account = account

    def _run_applescript(self, script: str) -> str:
        """Execute AppleScript and return stdout."""
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise AppleScriptError(
                f"AppleScript failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def _escape_for_applescript(self, text: str) -> str:
        """Escape a string for embedding in AppleScript."""
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def _folder_path_applescript(self, folder_path: str) -> str:
        """
        Convert 'Wiki/Sources' to AppleScript folder reference:
        'folder "Sources" of folder "Wiki" of account "iCloud"'
        """
        parts = folder_path.split("/")
        ref = f'account "{self.account}"'
        for part in parts:
            ref = f'folder "{self._escape_for_applescript(part)}" of {ref}'
        return ref

    # --- Folder operations ---

    def create_folder(self, folder_path: str) -> None:
        """Create a folder (and parents if needed). e.g. 'Wiki/Sources'."""
        parts = folder_path.split("/")
        for i in range(len(parts)):
            partial = "/".join(parts[:i+1])
            parent = "/".join(parts[:i]) if i > 0 else None
            name = parts[i]
            try:
                if parent:
                    parent_ref = self._folder_path_applescript(parent)
                else:
                    parent_ref = f'account "{self.account}"'
                script = f'''
                    tell application "Notes"
                        make new folder at {parent_ref} with properties {{name:"{self._escape_for_applescript(name)}"}}
                    end tell
                '''
                self._run_applescript(script)
            except AppleScriptError:
                pass  # Folder already exists

    def list_folders(self, parent: str = "") -> list[str]:
        """List subfolder names under a folder path."""
        if parent:
            ref = self._folder_path_applescript(parent)
        else:
            ref = f'account "{self.account}"'
        script = f'''
            tell application "Notes"
                get name of every folder of {ref}
            end tell
        '''
        result = self._run_applescript(script)
        if not result:
            return []
        return [f.strip() for f in result.split(",")]

    # --- Note operations ---

    def create_note(self, folder_path: str, title: str, html_body: str) -> str:
        """
        Create a note and return its Apple Notes ID.
        html_body should be valid HTML (Apple Notes uses HTML internally).
        """
        folder_ref = self._folder_path_applescript(folder_path)
        escaped_body = self._escape_for_applescript(html_body)
        escaped_title = self._escape_for_applescript(title)
        script = f'''
            tell application "Notes"
                set newNote to make new note at {folder_ref} with properties {{name:"{escaped_title}", body:"{escaped_body}"}}
                return id of newNote
            end tell
        '''
        return self._run_applescript(script)

    def read_note(self, note_id: str) -> dict:
        """Read a note by its Apple Notes ID. Returns {id, name, body, folder}."""
        script = f'''
            tell application "Notes"
                set n to note id "{self._escape_for_applescript(note_id)}"
                set noteName to name of n
                set noteBody to body of n
                set noteFolder to name of container of n
                return noteName & "|||DELIM|||" & noteBody & "|||DELIM|||" & noteFolder
            end tell
        '''
        result = self._run_applescript(script)
        parts = result.split("|||DELIM|||")
        return {
            "id": note_id,
            "name": parts[0] if len(parts) > 0 else "",
            "body": parts[1] if len(parts) > 1 else "",
            "folder": parts[2] if len(parts) > 2 else ""
        }

    def update_note(self, note_id: str, html_body: str) -> None:
        """Replace the full body of an existing note."""
        escaped = self._escape_for_applescript(html_body)
        script = f'''
            tell application "Notes"
                set body of note id "{self._escape_for_applescript(note_id)}" to "{escaped}"
            end tell
        '''
        self._run_applescript(script)

    def list_notes(self, folder_path: str) -> list[dict]:
        """List all notes in a folder. Returns [{id, name}, ...]."""
        folder_ref = self._folder_path_applescript(folder_path)
        script = f'''
            tell application "Notes"
                set noteList to every note of {folder_ref}
                set output to ""
                repeat with n in noteList
                    set output to output & (id of n) & "|||" & (name of n) & "\\n"
                end repeat
                return output
            end tell
        '''
        result = self._run_applescript(script)
        notes = []
        for line in result.strip().split("\n"):
            if "|||" in line:
                note_id, name = line.split("|||", 1)
                notes.append({"id": note_id.strip(), "name": name.strip()})
        return notes

    def delete_note(self, note_id: str) -> None:
        """Delete a note by ID (moves to Recently Deleted)."""
        script = f'''
            tell application "Notes"
                delete note id "{self._escape_for_applescript(note_id)}"
            end tell
        '''
        self._run_applescript(script)

    def find_notes_by_name(self, query: str, folder_path: str = "") -> list[dict]:
        """Search notes by name (contains match)."""
        if folder_path:
            scope = f"of {self._folder_path_applescript(folder_path)}"
        else:
            scope = f'of account "{self.account}"'
        escaped_query = self._escape_for_applescript(query)
        script = f'''
            tell application "Notes"
                set matches to every note {scope} whose name contains "{escaped_query}"
                set output to ""
                repeat with n in matches
                    set output to output & (id of n) & "|||" & (name of n) & "\\n"
                end repeat
                return output
            end tell
        '''
        result = self._run_applescript(script)
        notes = []
        for line in result.strip().split("\n"):
            if "|||" in line:
                note_id, name = line.split("|||", 1)
                notes.append({"id": note_id.strip(), "name": name.strip()})
        return notes


class AppleScriptError(Exception):
    pass
```

### 3.3 Critical AppleScript Constraints

The developer must be aware of these limitations:

1. **Body is HTML, not markdown.** Apple Notes stores and returns note bodies as HTML. The daemon must convert all LLM output (markdown) to HTML before writing, and convert HTML back to markdown/plaintext before sending to the LLM for context.

2. **No partial updates.** `set body of note` replaces the entire note body. There is no append-only or diff-based update. The daemon must always read the current body, have the LLM produce the full updated version, and write the whole thing back.

3. **No real wiki links.** Apple Notes has no `[[wiki-link]]` syntax. Cross-references should be rendered as bold text mentions (e.g., `<b>See: Transformer Architecture</b>`) rather than clickable links. An alternative is using `notes://` URL scheme links, but these are fragile and break if the note is renamed. The recommended approach is to use a "Related Notes" section at the bottom of each note with plain-text names the user can search for.

4. **HTML tag support is limited.** Apple Notes renders a subset of HTML. Reliably supported tags:
   - `<h1>` through `<h6>` — headings
   - `<b>`, `<i>`, `<u>` — bold, italic, underline
   - `<ul>`, `<ol>`, `<li>` — lists
   - `<br>` — line breaks
   - `<div>` — block containers
   - `<a href="">` — hyperlinks (web URLs only)
   - `<font>` — limited font/color control
   - Tables, images, and complex CSS are NOT reliably supported via AppleScript body injection.

5. **Image attachments not accessible via AppleScript.** The `body` property strips image references. Images in notes use a proprietary internal format. The daemon should work with text-only notes.

6. **Performance.** AppleScript calls are slow (~200-500ms per call). Listing all notes in a large folder can take several seconds. The daemon should minimize calls by caching state in `state.json` and only reading/writing notes that need to change.

7. **First-run permission prompt.** The first time the daemon's Python process calls `osascript` to control Notes.app, macOS will show a dialog: "Python wants to control Notes.app." The user must click Allow. This only happens once. The app must be in System Settings → Privacy & Security → Automation.

8. **Notes.app must be running.** AppleScript commands will launch Notes.app if it's not running, but this causes a visible window flash. Recommend keeping Notes.app running in the background.

---

## 4. HTML Conversion Layer

Since the LLM naturally outputs markdown and Apple Notes consumes HTML, a bidirectional converter is needed.

### 4.1 Markdown → HTML (for writing to Apple Notes)

Use the Python `markdown` library with extensions:

```python
import markdown

def md_to_apple_notes_html(md_text: str) -> str:
    """
    Convert markdown to HTML compatible with Apple Notes.
    Strips unsupported tags and simplifies output.
    """
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"]
    )

    # Wrap in a basic structure Apple Notes expects
    # Note: Apple Notes adds its own wrapper; we just provide body content
    return html_body
```

**Important:** Apple Notes silently drops HTML it doesn't understand. The converter should strip or simplify:
- `<table>` → convert to formatted text or nested lists
- `<code>` / `<pre>` → preserve as plain text with a monospace font tag if possible, or just leave as plain text
- `<img>` → remove (images can't be injected via AppleScript body)
- Complex CSS → remove entirely

### 4.2 HTML → Plain Text (for sending to the LLM)

When the daemon reads existing wiki notes to give the LLM context, it needs to strip HTML:

```python
from html.parser import HTMLParser

def html_to_plaintext(html_body: str) -> str:
    """Strip HTML tags, convert to readable plain text."""
    # Use Python's built-in HTML parser or BeautifulSoup
    # Convert <h1> to "# ", <li> to "- ", etc.
    # This gives the LLM clean text to reason about.
    pass
```

Alternatively, use `beautifulsoup4` with `get_text()` for quick extraction, or `markdownify` for HTML-to-markdown round-tripping.

**Recommended dependency:** `pip install markdownify beautifulsoup4 markdown`

---

## 5. The Daemon Loop

### 5.1 Core Loop Logic

```python
# daemon.py — main loop (pseudocode)

import time
import os
import hashlib
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class WikiDaemon:
    def __init__(self, config_path: str):
        self.config = load_config(config_path)
        self.state = load_state(self.config.state_path)
        self.bridge = AppleNotesBridge(account=self.config.notes_account)
        self.llm = LLMClient.from_profile(
            self.config.llm_profiles[self.config.llm_default_profile]
        )
        # Optionally use a different (stronger) model for lint
        lint_profile_name = self.config.llm_lint_profile
        self.llm_lint = LLMClient.from_profile(
            self.config.llm_profiles[lint_profile_name]
        ) if lint_profile_name != self.config.llm_default_profile else self.llm

    def run(self):
        """Main entry point. Called by LaunchAgent or directly."""
        self.ensure_folders_exist()
        new_files = self.scan_inbox()

        if not new_files:
            log("No new files in inbox. Exiting.")
            return

        for filepath in new_files:
            try:
                self.ingest_file(filepath)
            except Exception as e:
                log(f"Error ingesting {filepath}: {e}")
                # Leave file in inbox for retry on next run

    def ensure_folders_exist(self):
        """Create Apple Notes folder structure if not present."""
        for subfolder in self.config.subfolders:
            full_path = f"{self.config.wiki_folder}/{subfolder}"
            if full_path not in self.state.folders_created:
                self.bridge.create_folder(full_path)
                self.state.folders_created.append(full_path)
                self.save_state()

    def scan_inbox(self) -> list[Path]:
        """Find new files in inbox that haven't been processed."""
        inbox = Path(self.config.base_dir) / "inbox"
        new_files = []
        for f in inbox.iterdir():
            if f.is_file() and f.suffix in self.config.supported_extensions:
                file_hash = hash_file(f)
                if file_hash not in [v["file_hash"] for v in self.state.processed_files.values()]:
                    new_files.append(f)
        return sorted(new_files, key=lambda f: f.stat().st_mtime)

    def ingest_file(self, filepath: Path):
        """Full ingestion pipeline for a single source file."""
        log(f"Ingesting: {filepath.name}")

        # Step 1: Extract text content from file
        content = self.extract_content(filepath)

        # Step 2: Read current wiki state (index + relevant notes)
        wiki_context = self.build_wiki_context()

        # Step 3: Call LLM to produce wiki updates
        updates = self.llm.ingest(
            source_content=content,
            source_filename=filepath.name,
            wiki_context=wiki_context,
            schema=self.load_schema()
        )

        # Step 4: Apply updates to Apple Notes
        self.apply_updates(updates)

        # Step 5: Move file to processed/
        dest = Path(self.config.base_dir) / "processed" / f"{today()}_{filepath.name}"
        filepath.rename(dest)

        # Step 6: Update state
        self.state.processed_files[filepath.name] = {
            "processed_at": now_iso(),
            "file_hash": hash_file(dest),
            "notes_created": updates.created_note_paths,
            "notes_updated": updates.updated_note_paths
        }
        self.save_state()

        # Step 7: Update the _Log note
        self.append_to_log(filepath.name, updates)

        log(f"Ingested: {filepath.name} — created {len(updates.created)} / updated {len(updates.updated)} notes")

    def extract_content(self, filepath: Path) -> str:
        """Extract text from various file types."""
        suffix = filepath.suffix.lower()
        if suffix in (".md", ".txt"):
            return filepath.read_text(encoding="utf-8")
        elif suffix == ".pdf":
            # Use pdftotext (poppler) or PyMuPDF
            return extract_pdf_text(filepath)
        elif suffix == ".html":
            return extract_html_text(filepath)
        elif suffix == ".csv":
            return filepath.read_text(encoding="utf-8")
        elif suffix == ".json":
            return filepath.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    def build_wiki_context(self) -> str:
        """
        Read the _Index note and a sample of key notes to give the LLM
        context about the current wiki state.
        """
        context_parts = []

        # Always include the index
        if "_Index" in self.state.notes:
            index_note = self.bridge.read_note(self.state.notes["_Index"]["apple_notes_id"])
            context_parts.append(f"## Current Index\n{html_to_plaintext(index_note['body'])}")

        # Include recent log entries
        if "_Log" in self.state.notes:
            log_note = self.bridge.read_note(self.state.notes["_Log"]["apple_notes_id"])
            context_parts.append(f"## Recent Log\n{html_to_plaintext(log_note['body'])}")

        # Include titles of all existing notes for cross-reference awareness
        all_notes = []
        for subfolder in self.config.subfolders:
            folder_path = f"{self.config.wiki_folder}/{subfolder}"
            try:
                notes = self.bridge.list_notes(folder_path)
                all_notes.extend([(subfolder, n["name"]) for n in notes])
            except AppleScriptError:
                pass
        if all_notes:
            listing = "\n".join(f"- {folder}/{name}" for folder, name in all_notes)
            context_parts.append(f"## All Wiki Pages\n{listing}")

        return "\n\n".join(context_parts)

    def apply_updates(self, updates: WikiUpdates):
        """Create or update notes based on LLM output."""
        for note_update in updates.notes:
            html_body = md_to_apple_notes_html(note_update.markdown_content)
            folder_path = f"{self.config.wiki_folder}/{note_update.subfolder}"

            if note_update.action == "create":
                note_id = self.bridge.create_note(
                    folder_path, note_update.title, html_body
                )
                state_key = f"{note_update.subfolder}/{note_update.title}"
                self.state.notes[state_key] = {
                    "apple_notes_id": note_id,
                    "last_updated": now_iso(),
                    "checksum": hash_string(note_update.markdown_content)
                }

            elif note_update.action == "update":
                state_key = f"{note_update.subfolder}/{note_update.title}"
                note_id = self.state.notes[state_key]["apple_notes_id"]
                self.bridge.update_note(note_id, html_body)
                self.state.notes[state_key]["last_updated"] = now_iso()
                self.state.notes[state_key]["checksum"] = hash_string(note_update.markdown_content)

        self.save_state()
```

### 5.2 File Content Extraction

The daemon needs to handle multiple file types. Dependencies:

| File Type | Extraction Method | Python Dependency |
|-----------|-------------------|-------------------|
| `.md`, `.txt` | Direct read | None |
| `.pdf` | Text extraction | `pymupdf` (PyMuPDF) or shell out to `pdftotext` (poppler-utils) |
| `.html` | Strip tags, extract text | `beautifulsoup4` |
| `.csv` | Read as text | None (built-in `csv` module) |
| `.json` | Read as text | None (built-in `json` module) |
| `.docx` | Extract text | `python-docx` |
| `.epub` | Extract text | `ebooklib` |

For PDFs, `pymupdf` (`pip install pymupdf`) is recommended — it handles most PDFs without needing system-level dependencies. Alternative: install `poppler-utils` via Homebrew (`brew install poppler`) and shell out to `pdftotext`.

---

## 6. LLM Integration (Multi-Backend, OpenAI-Compatible)

The daemon talks to LLMs via the **OpenAI chat completions API format** (`POST /v1/chat/completions`). This is the de facto standard — nearly every LLM provider and local inference server implements it. By coding against this single interface, the daemon can switch between Anthropic, OpenAI, Ollama, LM Studio, Groq, Together, OpenRouter, Mistral, Azure OpenAI, vLLM, and any future provider without code changes — just a config change.

### 6.1 Why OpenAI Format (Not Native SDKs)

The Anthropic Python SDK, OpenAI Python SDK, etc. each have their own request/response shapes. Using native SDKs would mean writing a separate adapter for each provider. Instead, the daemon uses the `openai` Python package as a **universal HTTP client** — it sends standard chat completion requests to any `base_url`, regardless of who's running the server. Anthropic's API supports OpenAI-compatible requests at `https://api.anthropic.com/v1/`. OpenAI is natively compatible. Local servers like Ollama and LM Studio implement the same interface.

The `openai` Python package is the only LLM dependency needed. No provider-specific SDKs.

### 6.2 Provider Configuration

Each provider is defined as a **profile** in `config.yml` (see section 2.1). A profile contains:

| Field | Required | Description |
|-------|----------|-------------|
| `base_url` | Yes | The API endpoint. Include trailing `/v1/` for most providers. |
| `api_key_env` | No | Name of the environment variable holding the API key. |
| `api_key_value` | No | Literal API key fallback (for local servers that need a placeholder). `api_key_env` takes priority if both are set. |
| `model` | Yes | Model identifier string (provider-specific). |
| `max_tokens` | Yes | Maximum response tokens. |
| `extra_headers` | No | Dict of additional HTTP headers (e.g., `anthropic-version` for Anthropic). |
| `temperature` | No | Sampling temperature. Default: `0.3` (low creativity for wiki maintenance). |
| `timeout_seconds` | No | Request timeout. Default: `120`. |

**Tested provider configurations:**

| Provider | `base_url` | `model` example | Notes |
|----------|-----------|-----------------|-------|
| Anthropic | `https://api.anthropic.com/v1/` | `claude-sonnet-4-20250514` | Requires `anthropic-version` header |
| OpenAI | `https://api.openai.com/v1/` | `gpt-4o` | Standard |
| Ollama | `http://localhost:11434/v1/` | `llama3.1:70b` | No API key needed; use placeholder |
| LM Studio | `http://localhost:1234/v1/` | `local-model` | No API key needed |
| OpenRouter | `https://openrouter.ai/api/v1/` | `anthropic/claude-sonnet-4` | Aggregator; access many models with one key |
| Together | `https://api.together.xyz/v1/` | `meta-llama/Llama-3-70b-chat-hf` | Standard |
| Groq | `https://api.groq.com/openai/v1/` | `llama-3.1-70b-versatile` | Very fast inference |
| Fireworks | `https://api.fireworks.ai/inference/v1/` | `accounts/fireworks/models/llama-v3p1-70b-instruct` | Standard |
| Mistral | `https://api.mistral.ai/v1/` | `mistral-large-latest` | Standard |
| Azure OpenAI | `https://{resource}.openai.azure.com/openai/deployments/{deployment}/` | `gpt-4o` | Requires `api-version` query param; see Azure notes below |
| vLLM | `http://localhost:8000/v1/` | Model name from server | Self-hosted; OpenAI-compatible |

**Azure OpenAI special handling:** Azure uses a different URL structure and requires an `api-version` query parameter. The `openai` Python package supports this natively via `AzureOpenAI` client. The daemon should detect `base_url` containing `.openai.azure.com` and switch to the Azure client class automatically. Add `api_version` as an additional profile field for Azure profiles.

### 6.3 API Client Implementation

```python
# llm_client.py

import os
import logging
from dataclasses import dataclass, field
from openai import OpenAI, AzureOpenAI

logger = logging.getLogger("wiki-daemon.llm")

# ── Data structures (unchanged from before) ──────────────────────────

@dataclass
class NoteUpdate:
    action: str              # "create" or "update"
    subfolder: str           # e.g. "Sources", "Entities", "Concepts"
    title: str               # Note title
    markdown_content: str    # Full note body in markdown

@dataclass
class WikiUpdates:
    notes: list[NoteUpdate]
    log_entry: str           # One-line summary for the log

@dataclass
class LLMProfile:
    """Parsed from a single entry under llm.profiles in config.yml."""
    name: str
    base_url: str
    model: str
    max_tokens: int = 8192
    api_key_env: str = ""
    api_key_value: str = ""
    extra_headers: dict = field(default_factory=dict)
    temperature: float = 0.3
    timeout_seconds: int = 120
    api_version: str = ""    # Azure OpenAI only

# ── Universal LLM Client ─────────────────────────────────────────────

class LLMClient:
    """
    Talks to any OpenAI-compatible chat completions endpoint.
    One client per profile. Construct via LLMClient.from_profile().
    """

    def __init__(self, profile: LLMProfile):
        self.profile = profile
        self.client = self._build_client(profile)

    @classmethod
    def from_profile(cls, profile: LLMProfile) -> "LLMClient":
        return cls(profile)

    @staticmethod
    def _resolve_api_key(profile: LLMProfile) -> str:
        """Resolve API key: env var takes priority, then literal value."""
        if profile.api_key_env:
            key = os.environ.get(profile.api_key_env, "")
            if key:
                return key
        if profile.api_key_value:
            return profile.api_key_value
        # Some local servers (Ollama, LM Studio) don't need a real key
        return "no-key-required"

    @staticmethod
    def _build_client(profile: LLMProfile) -> OpenAI:
        """
        Build the appropriate OpenAI client.
        Detects Azure endpoints and uses AzureOpenAI automatically.
        """
        api_key = LLMClient._resolve_api_key(profile)

        # Azure OpenAI detection
        if ".openai.azure.com" in profile.base_url:
            return AzureOpenAI(
                azure_endpoint=profile.base_url,
                api_key=api_key,
                api_version=profile.api_version or "2024-10-21",
                timeout=profile.timeout_seconds,
                default_headers=profile.extra_headers or None,
            )

        return OpenAI(
            base_url=profile.base_url,
            api_key=api_key,
            timeout=profile.timeout_seconds,
            default_headers=profile.extra_headers or None,
        )

    def _call(self, system_prompt: str, user_message: str) -> str:
        """
        Make a chat completion request. Returns the assistant's text response.
        This is the single point of contact with the LLM API.
        """
        logger.info(
            f"LLM call: profile={self.profile.name} model={self.profile.model} "
            f"base_url={self.profile.base_url}"
        )

        response = self.client.chat.completions.create(
            model=self.profile.model,
            max_tokens=self.profile.max_tokens,
            temperature=self.profile.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        text = response.choices[0].message.content
        logger.info(
            f"LLM response: {len(text)} chars, "
            f"usage={getattr(response, 'usage', 'N/A')}"
        )
        return text

    # ── Wiki operations ───────────────────────────────────────────────

    def ingest(
        self,
        source_content: str,
        source_filename: str,
        wiki_context: str,
        schema: str,
    ) -> WikiUpdates:
        """
        Send source content + wiki context to LLM.
        Returns structured wiki updates.
        """
        system_prompt = self._build_system_prompt(schema)
        user_message = self._build_ingest_message(
            source_content, source_filename, wiki_context
        )
        response_text = self._call(system_prompt, user_message)
        return self._parse_response(response_text)

    def lint(self, wiki_context: str, schema: str) -> WikiUpdates:
        """Ask LLM to health-check the wiki."""
        system_prompt = self._build_system_prompt(schema)
        user_message = f"""Perform a lint/health-check on the wiki. Review the current state below
and produce updates to fix any issues you find.

Look for:
- Contradictions between pages
- Stale claims that newer sources may have superseded
- Orphan pages with no cross-references pointing to them
- Important concepts mentioned in notes that lack their own page
- Missing cross-references between related pages
- The Index note being out of date

Current wiki state:
{wiki_context}"""

        response_text = self._call(system_prompt, user_message)
        return self._parse_response(response_text)

    # ── Prompt construction ───────────────────────────────────────────

    def _build_system_prompt(self, schema: str) -> str:
        return f"""You are a wiki maintenance daemon. You manage a personal knowledge wiki
stored in Apple Notes. Your job is to process new source documents and maintain
the wiki by creating, updating, and cross-referencing notes.

{schema}

CRITICAL OUTPUT FORMAT:
You must respond with a series of note operations in the following XML format.
Do not include any other text outside these tags.

<wiki_updates>
  <note action="create" subfolder="Sources" title="Summary: Article Title">
    Markdown content of the note goes here.
    Use ## for sections within notes.
    Use **bold** for emphasis.
    Use "See: Note Title" for cross-references to other wiki pages.
  </note>
  <note action="update" subfolder="Concepts" title="Existing Concept Page">
    Full updated markdown content (replaces existing note entirely).
  </note>
  <log_entry>Ingested "Article Title" — created 1 source summary, updated 2 concept pages</log_entry>
</wiki_updates>

Rules:
- Subfolder must be one of: Sources, Entities, Concepts, Synthesis
- For "update" actions, output the FULL note content (it replaces the entire note)
- Always update the _Index note (subfolder="" title="_Index") with any new pages
- Cross-reference other wiki pages by writing "See: <Page Title>" in relevant sections
- Keep notes focused — one entity/concept per note
- Use "## Related Notes" as the final section listing cross-references
"""

    def _build_ingest_message(
        self, source_content: str, filename: str, wiki_context: str
    ) -> str:
        return f"""Ingest the following source document into the wiki.

SOURCE FILENAME: {filename}

SOURCE CONTENT:
{source_content}

CURRENT WIKI STATE:
{wiki_context}

Process this source and produce wiki updates. Create a source summary note,
and create or update any entity, concept, or synthesis pages as appropriate.
Update the _Index note to include any new pages."""

    # ── Response parsing ──────────────────────────────────────────────

    def _parse_response(self, response_text: str) -> WikiUpdates:
        """Parse the XML-formatted LLM response into WikiUpdates."""
        import re

        notes = []
        note_pattern = re.compile(
            r'<note\s+action="(\w+)"\s+subfolder="([^"]*)"\s+title="([^"]*)">\s*(.*?)\s*</note>',
            re.DOTALL,
        )
        for match in note_pattern.finditer(response_text):
            notes.append(NoteUpdate(
                action=match.group(1),
                subfolder=match.group(2),
                title=match.group(3),
                markdown_content=match.group(4).strip(),
            ))

        log_match = re.search(
            r"<log_entry>(.*?)</log_entry>", response_text, re.DOTALL
        )
        log_entry = log_match.group(1).strip() if log_match else "Update"

        if not notes:
            logger.warning(
                "LLM response contained no <note> elements. "
                "Raw response (first 500 chars): %s",
                response_text[:500],
            )

        return WikiUpdates(notes=notes, log_entry=log_entry)
```

### 6.4 Config Loader for LLM Profiles

```python
# config_loader.py (LLM-relevant excerpt)

import yaml
from llm_client import LLMProfile

def load_llm_profiles(config: dict) -> dict[str, LLMProfile]:
    """Parse the llm.profiles section of config.yml into LLMProfile objects."""
    profiles = {}
    for name, pconf in config.get("llm", {}).get("profiles", {}).items():
        profiles[name] = LLMProfile(
            name=name,
            base_url=pconf["base_url"],
            model=pconf["model"],
            max_tokens=pconf.get("max_tokens", 8192),
            api_key_env=pconf.get("api_key_env", ""),
            api_key_value=pconf.get("api_key_value", ""),
            extra_headers=pconf.get("extra_headers", {}),
            temperature=pconf.get("temperature", 0.3),
            timeout_seconds=pconf.get("timeout_seconds", 120),
            api_version=pconf.get("api_version", ""),
        )
    return profiles
```

### 6.5 Usage Examples

**Switch from Anthropic to a local Ollama model — zero code changes:**

```yaml
# config.yml — just change this line:
llm:
  default_profile: "ollama"      # was "anthropic-sonnet"
```

**Use a strong cloud model for lint, cheap local model for ingestion:**

```yaml
llm:
  default_profile: "ollama"           # fast & free for routine ingestion
  lint_profile: "anthropic-opus"      # deep analysis for weekly lint
```

**Add a new provider (e.g., Cerebras, DeepSeek):**

```yaml
llm:
  profiles:
    # ... existing profiles ...
    deepseek:
      base_url: "https://api.deepseek.com/v1/"
      api_key_env: "DEEPSEEK_API_KEY"
      model: "deepseek-chat"
      max_tokens: 8192
```

No code changes required — just add the profile and set `default_profile`.

### 6.6 The Schema File (`schema.md`)

This is the LLM's instruction manual for the wiki. It lives on disk and is loaded into every API call. The user and LLM co-evolve it over time. Initial template:

```markdown
# Wiki Schema

## Purpose
This wiki tracks [USER'S DOMAIN — e.g., "AI research papers and developments"].

## Folder Structure
- **Sources/** — One summary note per ingested source document.
  Title format: "Summary: <source title>"
- **Entities/** — One note per person, organization, or product.
  Title format: The entity's name (e.g., "OpenAI", "Yann LeCun")
- **Concepts/** — One note per idea, technique, or topic.
  Title format: The concept name (e.g., "Transformer Architecture", "RLHF")
- **Synthesis/** — Higher-order notes that span multiple sources.
  Includes "Overview" (big picture), "Open Questions", "Timeline", etc.

## Note Format
Each note should follow this structure:
- **Title** (first line, becomes note title)
- **Summary** (2-3 sentence overview)
- **Key Points** (bulleted details)
- **Source** (which source documents this information comes from)
- **Related Notes** (final section, list of cross-referenced wiki pages)

## Cross-References
When a note mentions an entity or concept that has its own wiki page,
add "See: <Page Title>" inline. Also list all cross-references in the
"Related Notes" section at the bottom.

## Handling Contradictions
When new information contradicts existing wiki content, do NOT silently
overwrite. Instead, note the contradiction explicitly:
"⚠️ Conflict: <source A> claims X, but <source B> claims Y."

## Index Format
The _Index note should list every wiki page organized by subfolder,
with a one-line description for each.
```

### 6.7 Token Budget & Cost Considerations

Each LLM call includes:
- System prompt + schema: ~1,000-2,000 tokens
- Wiki context (index + note list): scales with wiki size. At ~100 notes, roughly 2,000-5,000 tokens.
- Source content: varies. A typical article is 2,000-8,000 tokens; a paper can be 15,000+.
- Response: the LLM must output full note bodies, typically 2,000-6,000 tokens.

**Cost estimates by provider (per typical ingestion call):**

| Provider | Model | Approximate Cost | Notes |
|----------|-------|-----------------|-------|
| Anthropic | Claude Sonnet | $0.01-0.05 | Good balance of quality/cost |
| Anthropic | Claude Opus | $0.05-0.25 | Best quality; use for lint |
| OpenAI | GPT-4o | $0.01-0.05 | Comparable to Sonnet |
| OpenAI | GPT-4o-mini | $0.001-0.005 | Budget option |
| Ollama (local) | Llama 3.1 70B | $0.00 | Free; requires beefy hardware |
| Groq | Llama 3.1 70B | $0.001-0.003 | Very fast, very cheap |
| OpenRouter | Varies | Varies | Aggregator; price depends on model |

**For large sources (>15,000 tokens):** Pre-chunk the source and ingest in multiple passes, or summarize first then ingest the summary. The daemon should detect this and handle it automatically. Check the model's context window size (available in most provider docs) against source length before sending.

**Local model quality note:** For wiki maintenance (which requires careful cross-referencing and structured XML output), models smaller than ~30B parameters may produce unreliable structured output. Recommended minimums for local inference: Llama 3.1 70B, Qwen 2.5 72B, or Mistral Large. Smaller models can work for simple ingestion but may struggle with lint operations that require reasoning across many pages.

### 6.8 Retry & Error Handling (Provider-Aware)

Different providers return different error codes. The client should handle:

```python
import time
from openai import (
    APIError, RateLimitError, APIConnectionError,
    APITimeoutError, AuthenticationError
)

def call_with_retry(client: LLMClient, system: str, user: str, max_retries: int = 3) -> str:
    """Retry wrapper with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return client._call(system, user)

        except AuthenticationError as e:
            # Bad API key — don't retry, fail immediately
            logger.error(f"Authentication failed for profile '{client.profile.name}': {e}")
            raise

        except RateLimitError as e:
            # 429 — back off and retry
            wait = 30 * (2 ** attempt)  # 30s, 60s, 120s
            logger.warning(f"Rate limited. Waiting {wait}s before retry {attempt+1}/{max_retries}")
            time.sleep(wait)

        except APITimeoutError as e:
            # Request took too long — retry with same timeout
            logger.warning(f"Timeout. Retry {attempt+1}/{max_retries}")
            time.sleep(5)

        except APIConnectionError as e:
            # Network error (common with local servers that may not be running)
            logger.warning(f"Connection error to {client.profile.base_url}: {e}")
            if "localhost" in client.profile.base_url:
                logger.error("Local LLM server may not be running. Check Ollama/LM Studio.")
                raise
            time.sleep(10)

        except APIError as e:
            # 500-level server errors — retry
            logger.warning(f"API error ({e.status_code}): {e}. Retry {attempt+1}/{max_retries}")
            time.sleep(10 * (attempt + 1))

    raise RuntimeError(f"LLM call failed after {max_retries} retries")
```

---

## 7. Scheduling with launchd

### 7.1 Main Daemon (Inbox Watcher)

Two scheduling approaches — pick one:

**Option A: Polling (simpler, recommended to start)**

Create `~/Library/LaunchAgents/com.user.wiki-daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.wiki-daemon</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/USERNAME/Wiki/daemon.py</string>
        <string>ingest</string>
    </array>

    <key>StartInterval</key>
    <integer>60</integer>  <!-- Run every 60 seconds -->

    <key>WorkingDirectory</key>
    <string>/Users/USERNAME/Wiki</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-...</string>  <!-- Or use keychain; see section 7.3 -->
    </dict>

    <key>StandardOutPath</key>
    <string>/Users/USERNAME/Wiki/daemon.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/USERNAME/Wiki/daemon.stderr.log</string>

    <key>Nice</key>
    <integer>10</integer>  <!-- Lower priority -->
</dict>
</plist>
```

**Option B: File System Watching (more responsive)**

```xml
    <!-- Replace StartInterval with WatchPaths -->
    <key>WatchPaths</key>
    <array>
        <string>/Users/USERNAME/Wiki/inbox</string>
    </array>
```

With `WatchPaths`, launchd triggers the daemon whenever any file in the inbox folder changes. Note Apple's caveat: file system event monitoring has race conditions — files may be caught in a partially-written state. The daemon should verify files are fully written (e.g., check that file size hasn't changed in the last 2 seconds) before processing.

### 7.2 Lint Agent (Daily)

Create `~/Library/LaunchAgents/com.user.wiki-lint.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.wiki-lint</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/USERNAME/Wiki/daemon.py</string>
        <string>lint</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>WorkingDirectory</key>
    <string>/Users/USERNAME/Wiki</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-...</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/Users/USERNAME/Wiki/lint.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/USERNAME/Wiki/lint.stderr.log</string>
</dict>
</plist>
```

### 7.3 Loading/Unloading Agents

```bash
# Install and start
launchctl load ~/Library/LaunchAgents/com.user.wiki-daemon.plist
launchctl load ~/Library/LaunchAgents/com.user.wiki-lint.plist

# Stop and uninstall
launchctl unload ~/Library/LaunchAgents/com.user.wiki-daemon.plist
launchctl unload ~/Library/LaunchAgents/com.user.wiki-lint.plist

# Check status
launchctl list | grep wiki
```

### 7.4 API Key Security

Storing the API key directly in the plist is not ideal. Better options:

**Option 1: macOS Keychain**

Store the key:
```bash
security add-generic-password -s "wiki-daemon" -a "anthropic" -w "sk-ant-..."
```

Retrieve in Python:
```python
import subprocess
result = subprocess.run(
    ["security", "find-generic-password", "-s", "wiki-daemon", "-a", "anthropic", "-w"],
    capture_output=True, text=True
)
api_key = result.stdout.strip()
```

Then remove `EnvironmentVariables` from the plist entirely.

**Option 2: `.env` file with restricted permissions**

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > ~/Wiki/.env
chmod 600 ~/Wiki/.env
```

Load in Python with `python-dotenv`.

---

## 8. Detailed Operation Flows

### 8.1 Ingest Flow

```
User drops "attention_paper.pdf" into ~/Wiki/inbox/

Daemon wakes (triggered by WatchPaths or StartInterval)
  │
  ├─ 1. Scan inbox → finds attention_paper.pdf
  │
  ├─ 2. Extract text from PDF (PyMuPDF)
  │     → "Attention Is All You Need. Ashish Vaswani et al..."
  │
  ├─ 3. Build wiki context
  │     ├─ Read _Index note via AppleScript → get list of all pages
  │     ├─ Read _Log note → get recent activity
  │     └─ Compile list of all note titles across subfolders
  │
  ├─ 4. Call Anthropic API
  │     ├─ System: schema.md + output format instructions
  │     ├─ User: source content + wiki context + "ingest this"
  │     └─ Response: XML with note operations
  │
  ├─ 5. Parse LLM response → list of NoteUpdate objects
  │     Example:
  │     ├─ CREATE Sources/"Summary: Attention Is All You Need"
  │     ├─ CREATE Entities/"Google Brain"
  │     ├─ CREATE Concepts/"Transformer Architecture"
  │     ├─ CREATE Concepts/"Self-Attention"
  │     ├─ UPDATE Concepts/"Sequence Models" (if exists — add cross-ref)
  │     └─ UPDATE _Index (add new entries)
  │
  ├─ 6. For each NoteUpdate:
  │     ├─ Convert markdown → HTML
  │     ├─ If CREATE: bridge.create_note() → store returned ID in state.json
  │     └─ If UPDATE: bridge.update_note(known_id, new_html)
  │
  ├─ 7. Move attention_paper.pdf → processed/2026-04-24_attention_paper.pdf
  │
  ├─ 8. Append to _Log note:
  │     "## [2026-04-24] ingest | Attention Is All You Need
  │      Created 4 notes, updated 2. Key topics: transformers, self-attention."
  │
  └─ 9. Save state.json
```

### 8.2 Lint Flow

```
LaunchAgent triggers at 3:00 AM
  │
  ├─ 1. Read ALL wiki notes (titles + bodies) via AppleScript
  │     This is the expensive step — may take 30-60 seconds for 100+ notes
  │
  ├─ 2. Compile full wiki dump as plain text
  │
  ├─ 3. Call Anthropic API (use claude-opus for deeper analysis)
  │     System: schema.md + lint instructions
  │     User: full wiki dump + "perform health check"
  │
  ├─ 4. LLM identifies issues:
  │     ├─ "Concepts/RLHF mentions 'PPO' but no PPO page exists → create one"
  │     ├─ "Sources/Summary: GPT-4 Report says 'March 2023' but
  │     │   Entities/OpenAI says 'released 2024' → flag contradiction"
  │     ├─ "Entities/Anthropic has no inbound cross-references → add refs
  │     │   from Concepts/RLHF and Concepts/Constitutional AI"
  │     └─ "_Index is missing 3 recently created pages → update"
  │
  ├─ 5. Apply fixes via the same create/update pipeline
  │
  └─ 6. Append to _Log:
       "## [2026-04-24] lint | Fixed 4 issues: 1 missing page, 1 contradiction
        flagged, 2 cross-reference gaps filled."
```

### 8.3 Query Flow (Optional — Manual Mode)

The daemon is primarily automated, but a manual query mode is useful. This would be a separate CLI command, not a background task:

```bash
python daemon.py query "What are the main differences between GPT-4 and Claude?"
```

The query flow:
1. Read `_Index` to find relevant pages
2. Read the relevant pages' bodies
3. Call LLM with the question + relevant page content
4. Print the answer to stdout
5. Optionally, if the answer is valuable, save it as a new note in `Synthesis/`

This is lower priority for the initial build but should be accounted for in the architecture.

---

## 9. Error Handling & Resilience

### 9.1 Error Categories

| Error | Handling |
|-------|----------|
| Anthropic API rate limit (429) | Exponential backoff: wait 30s, 60s, 120s, then skip file (leave in inbox) |
| Anthropic API error (500) | Retry once after 10s, then skip file |
| AppleScript timeout | Retry once; if persistent, log error and skip |
| Notes.app not responding | Check if running; if not, attempt to launch; wait 5s; retry |
| Malformed LLM response | Log the raw response, skip file, leave in inbox |
| File too large for context window | Chunk the file or pre-summarize; see section 6.3 |
| Permission denied (first run) | Log clear message telling user to approve automation permission |
| `state.json` corruption | Keep a backup (`state.json.bak`) updated on every successful save |
| iCloud sync conflict | Not directly manageable — Apple Notes handles sync. Daemon should never update the same note twice in rapid succession |

### 9.2 Locking

The daemon should use a filesystem lock (`/tmp/wiki-daemon.lock` or `~/Wiki/.lock`) to prevent concurrent runs. launchd may trigger a new run while a previous one is still processing.

```python
import fcntl

def acquire_lock(lock_path: str):
    lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except BlockingIOError:
        return None  # Another instance is running
```

### 9.3 File Stability Check

When using `WatchPaths`, the daemon may be triggered while a file is still being written (e.g., downloading a large PDF). Check file stability:

```python
import time

def is_file_stable(filepath: Path, wait_seconds: float = 2.0) -> bool:
    """Check that file size hasn't changed in the last N seconds."""
    size1 = filepath.stat().st_size
    time.sleep(wait_seconds)
    size2 = filepath.stat().st_size
    return size1 == size2 and size1 > 0
```

---

## 10. Setup & Installation

### 10.1 Prerequisites

- macOS 12+ (Monterey or later recommended)
- Python 3.10+ (`brew install python` or use system Python)
- An Anthropic API key

### 10.2 Installation Script

```bash
#!/bin/bash
# install.sh — Run once to set up the wiki daemon

set -e

WIKI_DIR="$HOME/Wiki"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "=== Wiki Daemon Setup ==="

# 1. Create directory structure
mkdir -p "$WIKI_DIR"/{inbox,processed,cache/extracted}

# 2. Create Python virtual environment
python3 -m venv "$WIKI_DIR/.venv"
source "$WIKI_DIR/.venv/bin/activate"

# 3. Install dependencies
pip install openai pymupdf beautifulsoup4 markdownify markdown pyyaml python-dotenv watchdog

# 4. Copy daemon files (assumes they're in current directory)
cp daemon.py apple_notes_bridge.py llm_client.py html_converter.py "$WIKI_DIR/"

# 5. Create default config
cat > "$WIKI_DIR/config.yml" << 'EOF'
notes_account: "iCloud"
wiki_folder: "Wiki"
subfolders:
  - "Sources"
  - "Entities"
  - "Concepts"
  - "Synthesis"
model: "claude-sonnet-4-20250514"
max_tokens: 8192
supported_extensions: [".md", ".txt", ".pdf", ".html", ".csv", ".json"]
max_file_size_mb: 10
EOF

# 6. Create initial schema
cat > "$WIKI_DIR/schema.md" << 'EOF'
# Wiki Schema
## Purpose
This wiki tracks [DESCRIBE YOUR DOMAIN HERE].
## Note Format
(customize this — see section 6.2 of the spec)
EOF

# 7. Initialize state
echo '{"version":1,"notes":{},"processed_files":{},"folders_created":[]}' > "$WIKI_DIR/state.json"

# 8. Store API key in Keychain
echo "Enter your Anthropic API key:"
read -s API_KEY
security add-generic-password -s "wiki-daemon" -a "anthropic" -w "$API_KEY"

# 9. Install LaunchAgents
PYTHON_PATH="$WIKI_DIR/.venv/bin/python"

cat > "$LAUNCH_AGENTS/com.user.wiki-daemon.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.wiki-daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$WIKI_DIR/daemon.py</string>
        <string>ingest</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>$WIKI_DIR/inbox</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$WIKI_DIR</string>
    <key>StandardOutPath</key>
    <string>$WIKI_DIR/daemon.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$WIKI_DIR/daemon.stderr.log</string>
    <key>Nice</key>
    <integer>10</integer>
</dict>
</plist>
PLIST

cat > "$LAUNCH_AGENTS/com.user.wiki-lint.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.wiki-lint</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$WIKI_DIR/daemon.py</string>
        <string>lint</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>$WIKI_DIR</string>
    <key>StandardOutPath</key>
    <string>$WIKI_DIR/lint.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$WIKI_DIR/lint.stderr.log</string>
</dict>
</plist>
PLIST

# 10. Load agents
launchctl load "$LAUNCH_AGENTS/com.user.wiki-daemon.plist"
launchctl load "$LAUNCH_AGENTS/com.user.wiki-lint.plist"

echo ""
echo "=== Setup Complete ==="
echo "Drop files into $WIKI_DIR/inbox/ to start building your wiki."
echo ""
echo "IMPORTANT: The first time the daemon runs, macOS will ask you to"
echo "approve automation access for Python → Notes.app."
echo "Go to System Settings → Privacy & Security → Automation to verify."
```

---

## 11. Python Dependencies

```
# requirements.txt
openai>=1.40.0            # Universal LLM client (OpenAI-compatible format)
pymupdf>=1.24.0
beautifulsoup4>=4.12.0
markdownify>=0.12.0
markdown>=3.6
pyyaml>=6.0
python-dotenv>=1.0.0
watchdog>=4.0.0           # Optional: for filesystem watching within Python
```

Note: the `openai` package is the **only** LLM dependency. It acts as a generic HTTP client for any OpenAI-compatible endpoint (Anthropic, OpenAI, Ollama, etc.). No provider-specific SDKs are needed.

---

## 12. Known Limitations & Future Enhancements

### Current Limitations
1. **macOS only.** The daemon requires AppleScript, which only runs on macOS. The wiki notes sync to iPhone/iPad via iCloud for reading, but the daemon itself cannot run on iOS.
2. **No clickable cross-references.** Apple Notes doesn't support wiki-style links. Cross-references are text-based ("See: Page Title") — the user searches manually.
3. **Full note replacement.** Every update rewrites the entire note body. For large notes, this is wasteful but unavoidable given AppleScript's API.
4. **No images.** AppleScript cannot inject images into notes. The wiki is text-only.
5. **No native checklists/tables.** These Apple Notes features use proprietary internal formats not accessible via AppleScript body injection.
6. **Slow at scale.** AppleScript calls are ~200-500ms each. A wiki with 500+ notes will have slow lint operations. At that scale, consider reading from the NoteStore.sqlite database directly (read-only) for faster bulk reads.

### Future Enhancements
1. **Direct SQLite reading.** For large wikis, read note content directly from `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` (read-only, decompressing gzipped protobuf blobs) for fast full-wiki scans. Continue using AppleScript for writes.
2. **Local vector search.** As the wiki grows beyond ~100 notes, add a local embedding index (e.g., using `chromadb` or `lancedb`) to help the LLM find relevant notes without sending the full index in every API call.
3. **Shortcuts integration.** Build Apple Shortcuts that trigger ingestion from iOS — e.g., share a web article from Safari → Shortcut saves it to the inbox folder in iCloud Drive → daemon picks it up on the Mac.
4. **Query mode via Shortcuts.** An Apple Shortcut that sends a question to the daemon (via a small HTTP server or a shared file), gets the answer back, and displays it.
5. **MCP server.** Wrap the daemon as an MCP server so Claude Desktop or Claude Code can interact with the wiki directly during conversations. Several open-source Apple Notes MCP servers already exist (see references) and could be adapted.
6. **Conflict-aware updates.** Track note modification dates and refuse to overwrite if the user has manually edited a note since the daemon's last update.
7. **Web clipper integration.** Use Obsidian Web Clipper or a custom bookmarklet that saves articles directly to `~/Wiki/inbox/` as markdown.

---

## 13. Testing Strategy

### Unit Tests
- AppleScript bridge: mock `subprocess.run` and test escaping, folder path construction, response parsing
- HTML conversion: test markdown→HTML and HTML→plaintext with edge cases (code blocks, special characters, empty input)
- LLM client: test profile loading from config, Azure endpoint detection, API key resolution (env var vs literal vs missing), retry logic with mocked error responses, XML response parsing with various shapes/malformed XML/missing fields
- Config loader: test YAML parsing with multiple profiles, missing optional fields, invalid profiles
- State management: test save/load/merge of `state.json`

### Integration Tests (require macOS with Notes.app)
- Create a test folder in Apple Notes, run CRUD operations, verify content
- Full ingest pipeline with a sample markdown file
- Verify iCloud sync by checking note appears on a second device

### Manual Smoke Tests
1. Drop a `.md` file in inbox → verify note appears in Apple Notes within 60 seconds
2. Drop a `.pdf` file → verify text extraction and note creation
3. Drop 3 files rapidly → verify all are processed without conflicts
4. Edit a wiki note manually in Apple Notes → verify daemon doesn't overwrite on next run (unless it has updates)
5. Run lint command → verify it identifies and fixes issues
6. Kill daemon mid-run → verify it recovers cleanly on next run (file stays in inbox)
7. Switch `default_profile` from `anthropic-sonnet` to `openai` → verify ingestion still works with no code changes
8. Set `default_profile` to `ollama` with Ollama not running → verify clear error message about local server being down

---

## 14. Project Structure

```
wiki-daemon/
├── README.md
├── requirements.txt
├── install.sh
├── daemon.py                  # Entry point, CLI handling, main loop
├── apple_notes_bridge.py      # AppleScript bridge (section 3)
├── html_converter.py          # Markdown ↔ HTML conversion (section 4)
├── llm_client.py              # Multi-backend LLM client, OpenAI-compatible (section 6)
├── file_extractor.py          # PDF/HTML/etc text extraction (section 5.2)
├── state_manager.py           # state.json load/save/locking
├── config_loader.py           # config.yml parsing, LLM profile loading
├── launchd/
│   ├── com.user.wiki-daemon.plist
│   └── com.user.wiki-lint.plist
├── schema_templates/
│   ├── general.md             # Generic wiki schema
│   ├── research.md            # Academic research schema
│   ├── book_notes.md          # Book reading schema
│   └── business.md            # Business/team schema
└── tests/
    ├── test_bridge.py
    ├── test_html_converter.py
    ├── test_llm_client.py     # Test profile loading, provider detection, retry logic
    └── test_state_manager.py
```

---

## 15. References

- **Original pattern document:** The "LLM Wiki" concept document (attached to this spec)
- **AppleScript Notes dictionary:** https://www.macosxautomation.com/applescript/notes/
- **Apple Notes MCP servers (existing open source):**
  - https://github.com/sweetrb/apple-notes-mcp (read + write via AppleScript, most complete)
  - https://github.com/RafalWilinski/mcp-apple-notes (RAG with embeddings)
  - https://github.com/sirmews/apple-notes-mcp (read-only via SQLite)
- **Apple Notes SQLite structure:** `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- **launchd documentation:** https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html
- **OpenAI Python SDK (universal client):** https://github.com/openai/openai-python
- **Anthropic OpenAI-compatible endpoint:** https://docs.anthropic.com/en/api/openai-sdk
- **Ollama OpenAI compatibility:** https://ollama.com/blog/openai-compatibility
