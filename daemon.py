from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shutil
import sys
import time

from apple_notes_bridge import AppleNotesBridge, AppleScriptError
from config_loader import Config, load_config
from file_extractor import extract_content
from html_converter import html_to_plaintext, md_to_apple_notes_html
from llm_client import LLMClient, NoteUpdate, WikiUpdates
from state_manager import WikiState, acquire_lock, load_state, save_state


logger = logging.getLogger("wiki-daemon")


@dataclass(slots=True)
class ApplyResult:
    created: list[str]
    updated: list[str]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def hash_string(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_file(path: str | Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return "sha256:" + sha.hexdigest()


def is_file_stable(filepath: Path, wait_seconds: float = 2.0) -> bool:
    size_1 = filepath.stat().st_size
    if size_1 <= 0:
        return False
    time.sleep(wait_seconds)
    size_2 = filepath.stat().st_size
    return size_1 == size_2


def note_state_key(subfolder: str, title: str) -> str:
    return f"{subfolder}/{title}" if subfolder else title


def setup_logging(config: Config) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = RotatingFileHandler(
        config.log_path, maxBytes=1_000_000, backupCount=3
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


class WikiDaemon:
    def __init__(self, config_path: str | Path):
        self.config = load_config(config_path)
        setup_logging(self.config)
        self.state = load_state(self.config.state_path)
        self.bridge = AppleNotesBridge(account=self.config.notes_account)
        self.llm = self._build_client(self.config.llm_default_profile)
        self.llm_lint = (
            self._build_client(self.config.llm_lint_profile)
            if self.config.llm_lint_profile
            else self.llm
        )

    def _build_client(self, profile_name: str) -> LLMClient:
        if not profile_name:
            raise ValueError("No LLM profile configured")
        return LLMClient.from_profile(self.config.llm_profiles[profile_name])

    def save_state(self) -> None:
        save_state(self.config.state_path, self.state)

    def load_schema(self) -> str:
        return self.config.schema_path.read_text(encoding="utf-8")

    def ensure_local_dirs(self) -> None:
        for path in (
            self.config.inbox_dir,
            self.config.processed_dir,
            self.config.cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def ensure_folders_exist(self) -> None:
        required_folders = [self.config.wiki_folder] + [
            f"{self.config.wiki_folder}/{subfolder}"
            for subfolder in self.config.subfolders
        ]
        for folder_path in required_folders:
            if folder_path not in self.state.folders_created:
                self.bridge.create_folder(folder_path)
                self.state.folders_created.append(folder_path)
                self.save_state()
        self.ensure_system_notes_exist()

    def ensure_system_notes_exist(self) -> None:
        self._ensure_note_exists("", "_Index", "# Wiki Index\n")
        self._ensure_note_exists("", "_Log", "# Wiki Log\n")

    def _ensure_note_exists(
        self, subfolder: str, title: str, markdown_content: str
    ) -> None:
        key = note_state_key(subfolder, title)
        if key in self.state.notes:
            return
        folder_path = (
            self.config.wiki_folder
            if not subfolder
            else f"{self.config.wiki_folder}/{subfolder}"
        )
        note_id = self.bridge.create_note(
            folder_path, title, md_to_apple_notes_html(markdown_content)
        )
        self.state.notes[key] = {
            "apple_notes_id": note_id,
            "last_updated": now_iso(),
            "checksum": hash_string(markdown_content),
        }
        self.save_state()

    def scan_inbox(self) -> list[Path]:
        known_hashes = {
            entry.get("file_hash", "") for entry in self.state.processed_files.values()
        }
        files: list[Path] = []
        for path in sorted(
            self.config.inbox_dir.iterdir(), key=lambda item: item.stat().st_mtime
        ):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.config.supported_extensions:
                continue
            if path.stat().st_size > self.config.max_file_size_mb * 1024 * 1024:
                logger.warning(
                    "Skipping %s because it exceeds max_file_size_mb", path.name
                )
                continue
            if self.config.use_fswatch and not is_file_stable(path):
                logger.info("Skipping %s because it is still being written", path.name)
                continue
            file_hash = hash_file(path)
            if file_hash in known_hashes:
                continue
            files.append(path)
            if not self.config.batch_mode:
                break
        return files

    def run_ingest(self) -> None:
        self.ensure_local_dirs()
        self.ensure_folders_exist()
        files = self.scan_inbox()
        if not files:
            logger.info("No new files in inbox")
            self.state.last_run = now_iso()
            self.save_state()
            return

        for path in files:
            self.ingest_file(path)

        self.state.last_run = now_iso()
        self.save_state()

    def run_lint(self) -> None:
        self.ensure_local_dirs()
        self.ensure_folders_exist()
        updates = self.llm_lint.lint(self.build_full_wiki_context(), self.load_schema())
        applied = self.apply_updates(updates)
        self.append_to_log(
            "lint",
            f"{updates.log_entry} (created {len(applied.created)}, updated {len(applied.updated)})",
        )
        self.state.last_lint = now_iso()
        self.save_state()

    def run_query(self, query: str) -> str:
        return self.llm.answer_query(
            query, self.build_wiki_context(), self.load_schema()
        )

    def ingest_file(self, filepath: Path) -> None:
        logger.info("Ingesting %s", filepath.name)
        content = extract_content(filepath)
        wiki_context = self.build_wiki_context()
        updates = self.llm.ingest(
            content, filepath.name, wiki_context, self.load_schema()
        )
        applied = self.apply_updates(updates)

        destination = self._processed_destination(filepath.name)
        shutil.move(str(filepath), destination)

        self.state.processed_files[filepath.name] = {
            "processed_at": now_iso(),
            "file_hash": hash_file(destination),
            "notes_created": applied.created,
            "notes_updated": applied.updated,
        }
        self.save_state()
        self.append_to_log("ingest", f"{filepath.name}: {updates.log_entry}")
        logger.info("Finished %s", filepath.name)

    def _processed_destination(self, filename: str) -> Path:
        destination = self.config.processed_dir / f"{today()}_{filename}"
        if not destination.exists():
            return destination
        stem = destination.stem
        suffix = destination.suffix
        counter = 1
        while True:
            candidate = destination.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def build_wiki_context(self) -> str:
        parts: list[str] = []
        for title, label in (("_Index", "Current Index"), ("_Log", "Recent Log")):
            body = self._read_state_note_body(title)
            if body:
                parts.append(f"## {label}\n{body}")

        note_listing: list[str] = []
        for subfolder in self.config.subfolders:
            folder_path = f"{self.config.wiki_folder}/{subfolder}"
            try:
                note_listing.extend(
                    f"- {subfolder}/{note['name']}"
                    for note in self.bridge.list_notes(folder_path)
                )
            except AppleScriptError as exc:
                logger.warning("Failed to list notes for %s: %s", folder_path, exc)
        if note_listing:
            parts.append("## All Wiki Pages\n" + "\n".join(note_listing))
        return "\n\n".join(parts)

    def build_full_wiki_context(self) -> str:
        sections: list[str] = []
        for key, note_meta in sorted(self.state.notes.items()):
            note_id = note_meta.get("apple_notes_id", "")
            if not note_id:
                continue
            try:
                note = self.bridge.read_note(note_id)
            except AppleScriptError as exc:
                logger.warning("Failed to read note %s: %s", key, exc)
                continue
            sections.append(f"# {key}\n{html_to_plaintext(note['body'])}")
        return "\n\n".join(sections)

    def _read_state_note_body(self, title: str) -> str:
        note_meta = self.state.notes.get(title)
        if not note_meta:
            return ""
        try:
            return html_to_plaintext(
                self.bridge.read_note(note_meta["apple_notes_id"])["body"]
            )
        except AppleScriptError as exc:
            logger.warning("Failed to read %s: %s", title, exc)
            return ""

    def apply_updates(self, updates: WikiUpdates) -> ApplyResult:
        created: list[str] = []
        updated: list[str] = []
        for note_update in updates.notes:
            applied = self._apply_single_update(note_update)
            if applied == "create":
                created.append(note_update.path)
            else:
                updated.append(note_update.path)
        self.save_state()
        return ApplyResult(created=created, updated=updated)

    def _apply_single_update(self, note_update: NoteUpdate) -> str:
        markdown_content = note_update.markdown_content.strip()
        if len(markdown_content) > self.config.max_note_length_chars:
            markdown_content = (
                markdown_content[: self.config.max_note_length_chars].rstrip()
                + "\n\n[Truncated by daemon]"
            )
        html_body = md_to_apple_notes_html(markdown_content)
        folder_path = (
            self.config.wiki_folder
            if not note_update.subfolder
            else f"{self.config.wiki_folder}/{note_update.subfolder}"
        )
        state_key = note_state_key(note_update.subfolder, note_update.title)
        note_meta = self.state.notes.get(state_key)

        if note_meta is None:
            matches = self.bridge.find_notes_by_name(note_update.title, folder_path)
            exact = next(
                (match for match in matches if match["name"] == note_update.title), None
            )
            if exact is not None:
                note_meta = {"apple_notes_id": exact["id"]}
                self.state.notes[state_key] = note_meta

        if note_meta is None:
            note_id = self.bridge.create_note(folder_path, note_update.title, html_body)
            self.state.notes[state_key] = {
                "apple_notes_id": note_id,
                "last_updated": now_iso(),
                "checksum": hash_string(markdown_content),
            }
            return "create"

        self.bridge.update_note(note_meta["apple_notes_id"], html_body)
        note_meta["last_updated"] = now_iso()
        note_meta["checksum"] = hash_string(markdown_content)
        return "update"

    def append_to_log(self, operation: str, log_entry: str) -> None:
        key = "_Log"
        timestamp = today()
        entry = f"## [{timestamp}] {operation}\n{log_entry}\n"
        note_meta = self.state.notes.get(key)
        if note_meta is None:
            self._ensure_note_exists("", key, entry)
            return
        current_body = html_to_plaintext(
            self.bridge.read_note(note_meta["apple_notes_id"])["body"]
        )
        new_body = f"{entry}\n{current_body}".strip() + "\n"
        self.bridge.update_note(
            note_meta["apple_notes_id"], md_to_apple_notes_html(new_body)
        )
        note_meta["last_updated"] = now_iso()
        note_meta["checksum"] = hash_string(new_body)
        self.save_state()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apple Notes Wiki Daemon")
    parser.add_argument("command", choices=["ingest", "lint", "query"])
    parser.add_argument("query_text", nargs="?", default="")
    parser.add_argument("--config", default="config.yml")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    daemon = WikiDaemon(args.config)
    lock = acquire_lock(daemon.config.lock_path)
    if lock is None:
        logger.info("Another daemon instance is already running")
        return 0

    try:
        if args.command == "ingest":
            daemon.run_ingest()
        elif args.command == "lint":
            daemon.run_lint()
        else:
            print(daemon.run_query(args.query_text))
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
