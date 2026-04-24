# Apple Notes Wiki Daemon

Background macOS daemon that ingests files from a local folder, asks an LLM for structured wiki updates, and writes the resulting wiki into Apple Notes.

## Files

- `daemon.py`: CLI entry point for `ingest`, `lint`, and `query`
- `apple_notes_bridge.py`: AppleScript bridge for Apple Notes CRUD
- `html_converter.py`: markdown and HTML conversion helpers
- `llm_client.py`: OpenAI-compatible LLM client and XML response parsing
- `file_extractor.py`: source file content extraction
- `state_manager.py`: `state.json` load/save/lock helpers
- `config_loader.py`: `config.yml` parser and defaults

## Quick Start

1. Install `uv`.
2. Run `uv sync`.
3. Copy `config.sample.yml` to `~/Wiki/config.yml`.
4. Copy `schema_templates/general.md` to `~/Wiki/schema.md`.
5. Run `uv run python -m unittest discover -s tests`.
6. Run `uv run python daemon.py ingest --config ~/Wiki/config.yml`.

## Setup Script

Run `./install.sh` to:

- create `~/Wiki/{inbox,processed,cache/extracted}`
- copy `config.sample.yml` to `~/Wiki/config.yml`
- copy the default schema to `~/Wiki/schema.md`
- initialize `~/Wiki/state.json`
- create the local `.venv` with `uv sync`
- render launchd plist files into `~/Library/LaunchAgents`

The script does not automatically load the LaunchAgents or store API keys.

## Notes

- The daemon is macOS-only because Apple Notes access is implemented with AppleScript.
- The first AppleScript call will trigger a macOS automation permission prompt for Notes.
- Cross-references are plain text, not durable wiki links.
- Dependencies are managed in `pyproject.toml` and installed with `uv`.
