from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
import time
import xml.etree.ElementTree as ET

logger = logging.getLogger("wiki-daemon.llm")

try:
    from openai import (
        APIConnectionError,
        APIError,
        APITimeoutError,
        AuthenticationError,
        AzureOpenAI,
        OpenAI,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - optional dependency

    class APIError(Exception):
        status_code = None

    class RateLimitError(APIError):
        pass

    class APIConnectionError(APIError):
        pass

    class APITimeoutError(APIError):
        pass

    class AuthenticationError(APIError):
        pass

    class OpenAI:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("The 'openai' package is required to use LLMClient")

    class AzureOpenAI(OpenAI):  # type: ignore[no-redef]
        pass


@dataclass(slots=True)
class NoteUpdate:
    action: str
    subfolder: str
    title: str
    markdown_content: str

    @property
    def path(self) -> str:
        return f"{self.subfolder}/{self.title}" if self.subfolder else self.title


@dataclass(slots=True)
class WikiUpdates:
    notes: list[NoteUpdate]
    log_entry: str

    @property
    def created_note_paths(self) -> list[str]:
        return [note.path for note in self.notes if note.action == "create"]

    @property
    def updated_note_paths(self) -> list[str]:
        return [note.path for note in self.notes if note.action == "update"]


@dataclass(slots=True)
class LLMProfile:
    name: str
    base_url: str
    model: str
    max_tokens: int = 8192
    api_key_env: str = ""
    api_key_value: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    temperature: float = 0.3
    timeout_seconds: int = 120
    api_version: str = ""


def call_with_retry(
    client: "LLMClient", system: str, user: str, max_retries: int = 3
) -> str:
    for attempt in range(max_retries):
        try:
            return client._call(system, user)
        except AuthenticationError:
            raise
        except RateLimitError:
            time.sleep(30 * (2**attempt))
        except APITimeoutError:
            time.sleep(5)
        except APIConnectionError:
            if (
                "localhost" in client.profile.base_url
                or "127.0.0.1" in client.profile.base_url
            ):
                raise
            time.sleep(10)
        except APIError:
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {max_retries} retries")


class LLMClient:
    def __init__(self, profile: LLMProfile):
        self.profile = profile
        self.client = self._build_client(profile)

    @classmethod
    def from_profile(cls, profile: LLMProfile) -> "LLMClient":
        return cls(profile)

    @staticmethod
    def _resolve_api_key(profile: LLMProfile) -> str:
        if profile.api_key_env:
            value = os.environ.get(profile.api_key_env, "")
            if value:
                return value
        if profile.api_key_value:
            return profile.api_key_value
        return "no-key-required"

    @staticmethod
    def _build_client(profile: LLMProfile):
        api_key = LLMClient._resolve_api_key(profile)
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
        logger.info(
            "LLM call: profile=%s model=%s base_url=%s",
            self.profile.name,
            self.profile.model,
            self.profile.base_url,
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
        text = response.choices[0].message.content or ""
        logger.info("LLM response length=%s", len(text))
        return text

    def ingest(
        self, source_content: str, source_filename: str, wiki_context: str, schema: str
    ) -> WikiUpdates:
        system_prompt = self._build_system_prompt(schema)
        user_message = self._build_ingest_message(
            source_content, source_filename, wiki_context
        )
        return self._parse_response(call_with_retry(self, system_prompt, user_message))

    def lint(self, wiki_context: str, schema: str) -> WikiUpdates:
        system_prompt = self._build_system_prompt(schema)
        user_message = (
            "Perform a lint/health-check on the wiki. Review the current state below and produce updates to fix issues.\n\n"
            "Look for contradictions, stale claims, orphan pages, missing concept pages, missing cross-references, and an out-of-date index.\n\n"
            f"Current wiki state:\n{wiki_context}"
        )
        return self._parse_response(call_with_retry(self, system_prompt, user_message))

    def answer_query(self, query: str, wiki_context: str, schema: str) -> str:
        system_prompt = (
            self._build_system_prompt(schema)
            + "\nAnswer the user's question using the wiki context. You may answer in plain text instead of XML."
        )
        return call_with_retry(
            self, system_prompt, f"Question: {query}\n\nWiki context:\n{wiki_context}"
        )

    def _build_system_prompt(self, schema: str) -> str:
        return f"""You are a wiki maintenance daemon. You manage a personal knowledge wiki
stored in Apple Notes. Your job is to process new source documents and maintain
the wiki by creating, updating, and cross-referencing notes.

{schema}

CRITICAL OUTPUT FORMAT:
You must respond with a series of note operations in the following XML format.
Do not include any other text outside these tags.

<wiki_updates>
  <note action=\"create\" subfolder=\"Sources\" title=\"Summary: Article Title\">
    Markdown content of the note goes here.
  </note>
  <note action=\"update\" subfolder=\"Concepts\" title=\"Existing Concept Page\">
    Full updated markdown content.
  </note>
  <log_entry>Ingested source and updated the wiki.</log_entry>
</wiki_updates>

Rules:
- Subfolder must be one of: Sources, Entities, Concepts, Synthesis, or empty string ""
- For update actions, output the full note content
- Always update the _Index note using subfolder="" (empty string, NOT "_Index") and title="_Index"
- Use See: <Page Title> for cross-references
- Be thorough and comprehensive — prefer more detail over less
- Use ## Related Notes as the final section
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

Instructions:
1. SOURCE SUMMARY (subfolder="Sources"): Write a thorough, detailed note covering:
   - A 2-3 paragraph executive summary of the document
   - All major arguments, findings, or claims — use ## sections for each major theme
   - Methodology or approach (if applicable)
   - Key data points, statistics, or evidence cited
   - Limitations, caveats, or open questions raised by the authors
   - Practical implications or takeaways
   - Direct quotes or paraphrases of the most important passages (use > blockquote markdown)
   - Full bibliographic info if available (authors, year, publication)

2. ENTITY NOTES (subfolder="Entities"): For each significant person, organisation, system, or product mentioned — create or update a note with: who/what they are, their role in this document, and links to other relevant wiki pages.

3. CONCEPT NOTES (subfolder="Concepts"): For each significant idea, theory, technique, or term — create or update a detailed note with: definition, how the source explains or uses it, nuances, and connections to other concepts.

4. SYNTHESIS NOTE (subfolder="Synthesis"): If this document connects meaningfully with existing wiki content, create or update a synthesis note that draws out the cross-document insight.

5. CROSS-REFERENCES: In the ## Related Notes section of every note you create or update, add `See: <Exact Title>` lines referencing the other notes you are creating in this same batch, as well as any relevant existing wiki pages. Use the exact title you are giving each note.

6. Update the _Index note (subfolder="", title="_Index") with any new pages created."""

    def _parse_response(self, response_text: str) -> WikiUpdates:
        logger.debug("LLM raw response:\n%s", response_text)
        xml_text = self._extract_xml_block(response_text)
        if not xml_text:
            logger.warning("LLM response contained no <wiki_updates> block")
            return WikiUpdates(notes=[], log_entry="Update")

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return self._parse_response_with_regex(xml_text)

        notes: list[NoteUpdate] = []
        for element in root.findall("note"):
            notes.append(
                NoteUpdate(
                    action=(element.attrib.get("action") or "").strip(),
                    subfolder=(element.attrib.get("subfolder") or "").strip(),
                    title=(element.attrib.get("title") or "").strip(),
                    markdown_content=(element.text or "").strip(),
                )
            )

        log_entry_element = root.find("log_entry")
        log_entry = (
            (log_entry_element.text or "Update").strip()
            if log_entry_element is not None
            else "Update"
        )
        return WikiUpdates(notes=notes, log_entry=log_entry)

    @staticmethod
    def _extract_xml_block(response_text: str) -> str:
        match = re.search(r"<wiki_updates>.*?</wiki_updates>", response_text, re.DOTALL)
        return match.group(0) if match else ""

    @staticmethod
    def _parse_response_with_regex(response_text: str) -> WikiUpdates:
        note_pattern = re.compile(
            r'<note\s+action="([^"]+)"\s+subfolder="([^"]*)"\s+title="([^"]+)">\s*(.*?)\s*</note>',
            re.DOTALL,
        )
        notes = [
            NoteUpdate(
                action=match.group(1).strip(),
                subfolder=match.group(2).strip(),
                title=match.group(3).strip(),
                markdown_content=match.group(4).strip(),
            )
            for match in note_pattern.finditer(response_text)
        ]
        log_match = re.search(r"<log_entry>(.*?)</log_entry>", response_text, re.DOTALL)
        log_entry = log_match.group(1).strip() if log_match else "Update"
        return WikiUpdates(notes=notes, log_entry=log_entry)
