#!/usr/bin/env python3
"""Synchronize the README publication list with a public ORCID record."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ORCID_API = "https://pub.orcid.org/v3.0"
CROSSREF_API = "https://api.crossref.org/works"
START_MARKER = "<!-- ORCID_PUBLICATIONS:START -->"
END_MARKER = "<!-- ORCID_PUBLICATIONS:END -->"
SELF_FAMILY = "na"
SELF_GIVEN_INITIAL = "y"
CONFERENCE_TYPES = {"conference-abstract", "conference-paper", "conference-poster", "conference-output"}


def fetch_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "orcid-readme-publications/1.0 (https://github.com/YoungjunNa/CV_YoungjunNa)",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to retrieve valid data from {url}: {error}") from error


def as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def field_value(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    return str(value).strip() if value is not None else ""


def extract_work_summaries(payload: dict) -> list[dict]:
    summaries = []
    for group in as_list(payload.get("group")):
        if not isinstance(group, dict):
            continue
        candidates = [
            summary
            for summary in as_list(group.get("work-summary"))
            if isinstance(summary, dict) and summary.get("put-code") is not None
        ]
        if candidates:
            summaries.append(max(candidates, key=lambda item: int(item["put-code"])))
    return summaries


# --- Text cleanup -----------------------------------------------------------

def _replace_latex_command(text: str, command: str, wrap: str) -> str:
    """Replace ``\\command{...}`` (with nested braces) by ``wrap...wrap``."""
    token = f"\\{command}{{"
    while token in text:
        start = text.index(token)
        depth, index = 1, start + len(token)
        while index < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            index += 1
        inner = text[start + len(token):index - 1]
        text = f"{text[:start]}{wrap}{inner}{wrap}{text[index:]}"
    return text


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _dedupe_bilingual(text: str) -> str:
    """Collapse values exported twice, such as ``Title , Title``."""
    for separator in (" , ", ", "):
        offset = 0
        while (index := text.find(separator, offset)) != -1:
            left, right = text[:index], text[index + len(separator):]
            if _normalize(left) and _normalize(left) == _normalize(right):
                return left.strip()
            offset = index + 1
    return text


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("{\\&}", "&").replace("\\&", "&").replace("$\\mathsemicolon$", ";")
    text = _replace_latex_command(text, "textit", "*")
    text = _replace_latex_command(text, "emph", "*")
    text = html.unescape(text)
    text = re.sub(r"<\s*(i|em)\s*>(.*?)<\s*/\s*\1\s*>", r"*\2*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]*>", "", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\*\s*\*", "", text)
    text = " ".join(text.split())
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    if text.count("*") % 2:
        text = text.replace("*", "")
    text = _dedupe_bilingual(text)
    return text.replace("[", r"\[").replace("]", r"\]").strip()


# --- BibTeX -----------------------------------------------------------------

def parse_bibtex(source: str) -> dict[str, str]:
    """Parse the fields of a single BibTeX entry."""
    fields: dict[str, str] = {}
    body_start = source.find(",")
    if not source.lstrip().startswith("@") or body_start == -1:
        return fields
    index, length = body_start + 1, len(source)
    while index < length:
        match = re.compile(r"\s*([A-Za-z_-]+)\s*=\s*").match(source, index)
        if not match:
            break
        key, index = match.group(1).lower(), match.end()
        if index < length and source[index] == "{":
            depth, start = 1, index + 1
            index += 1
            while index < length and depth:
                depth += {"{": 1, "}": -1}.get(source[index], 0)
                index += 1
            value = source[start:index - 1]
        elif index < length and source[index] == '"':
            end = source.find('"', index + 1)
            end = length if end == -1 else end
            value, index = source[index + 1:end], end + 1
        else:
            end_match = re.compile(r"[^,}]*").match(source, index)
            value, index = end_match.group(0), end_match.end()
        fields[key] = value.strip()
        comma = source.find(",", index)
        if comma == -1:
            break
        index = comma + 1
    return fields


# --- Authors ----------------------------------------------------------------

def split_name(name: str) -> tuple[str, str]:
    """Return ``(given, family)`` from ``Given Family`` or ``Family, Given``."""
    name = clean_text(name).replace("*", "")
    if "," in name:
        family, given = (part.strip() for part in name.split(",", 1))
    else:
        parts = name.split()
        if len(parts) == 1:
            return "", parts[0]
        family, given = parts[-1], " ".join(parts[:-1])
    return given, family


def initials(given: str) -> str:
    result = []
    for part in given.replace(".", " ").split():
        letter = next((char for char in part if char.isalpha()), "")
        if letter:
            result.append(f"{letter.upper()}.")
    return " ".join(result)


def is_self(given: str, family: str) -> bool:
    return family.lower() == SELF_FAMILY and given[:1].lower() == SELF_GIVEN_INITIAL


def format_author(given: str, family: str, first: bool) -> str:
    if is_self(given, family):
        return "**Na, Y.**" if first else "**Y. Na**"
    abbreviated = initials(given)
    if not abbreviated:
        return family
    return f"{family} {abbreviated}" if first else f"{abbreviated} {family}"


def format_authors(names: list[tuple[str, str]]) -> str:
    formatted = [format_author(given, family, index == 0) for index, (given, family) in enumerate(names)]
    if len(formatted) <= 1:
        text = "".join(formatted)
    elif len(formatted) == 2:
        text = f"{formatted[0]} and {formatted[1]}"
    else:
        text = f"{', '.join(formatted[:-1])}, and {formatted[-1]}"
    return text if text.replace("*", "").endswith(".") else f"{text}."


# --- Work metadata ----------------------------------------------------------

def work_doi(work: dict) -> str:
    external_ids = work.get("external-ids")
    if not isinstance(external_ids, dict):
        return ""
    for external_id in as_list(external_ids.get("external-id")):
        if isinstance(external_id, dict) and field_value(external_id.get("external-id-type")).lower() == "doi":
            doi = field_value(external_id.get("external-id-value"))
            if doi:
                return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return ""


def fetch_crossref(doi: str) -> dict:
    try:
        return fetch_json(f"{CROSSREF_API}/{quote(doi, safe='')}").get("message", {})
    except RuntimeError as error:
        print(f"Warning: {error}", file=sys.stderr)
        return {}


def work_metadata(work: dict, crossref_lookup=fetch_crossref) -> dict:
    citation = work.get("citation") if isinstance(work.get("citation"), dict) else {}
    bibtex = {}
    if field_value(citation.get("citation-type")).lower() == "bibtex":
        bibtex = parse_bibtex(field_value(citation.get("citation-value")))

    title_block = work.get("title") if isinstance(work.get("title"), dict) else {}
    date = work.get("publication-date") if isinstance(work.get("publication-date"), dict) else {}
    doi = work_doi(work) or bibtex.get("doi", "")

    authors = []
    contributors = work.get("contributors") if isinstance(work.get("contributors"), dict) else {}
    for contributor in as_list(contributors.get("contributor")):
        if isinstance(contributor, dict) and field_value(contributor.get("credit-name")):
            authors.append(split_name(field_value(contributor.get("credit-name"))))
    if not authors and bibtex.get("author"):
        authors = [split_name(name) for name in re.split(r"\s+and\s+", bibtex["author"]) if name.strip()]

    metadata = {
        "type": field_value(work.get("type")).lower(),
        "title": clean_text(field_value(title_block.get("title")) or bibtex.get("title", "")),
        "journal": clean_text(field_value(work.get("journal-title")) or bibtex.get("journal", "")),
        "year": field_value(date.get("year")) or bibtex.get("year", ""),
        "month": field_value(date.get("month")),
        "day": field_value(date.get("day")),
        "volume": clean_text(bibtex.get("volume", "")),
        "issue": clean_text(bibtex.get("number", "")),
        "pages": clean_text(bibtex.get("pages", "")).replace("--", "-"),
        "authors": authors,
        "doi": doi,
    }

    if doi and not all(metadata[key] for key in ("authors", "volume", "pages")):
        crossref = crossref_lookup(doi)
        if not metadata["authors"]:
            metadata["authors"] = [
                (author.get("given", ""), author.get("family", ""))
                for author in crossref.get("author", [])
                if author.get("family")
            ]
        if not metadata["journal"]:
            metadata["journal"] = clean_text(next(iter(crossref.get("container-title", [])), ""))
        metadata["volume"] = metadata["volume"] or clean_text(str(crossref.get("volume", "")))
        metadata["issue"] = metadata["issue"] or clean_text(str(crossref.get("issue", "")))
        metadata["pages"] = metadata["pages"] or clean_text(str(crossref.get("page", crossref.get("article-number", ""))))
    return metadata


def render_work(metadata: dict) -> str:
    if not metadata["title"]:
        raise ValueError("ORCID work has no title")
    parts = []
    if metadata["authors"]:
        parts.append(format_authors(metadata["authors"]))
    if metadata["year"]:
        parts.append(f"{metadata['year']}.")
    title = metadata["title"]
    parts.append(title if title.rstrip("*")[-1:] in ".?!" else f"{title}.")

    source = metadata["journal"]
    if metadata["volume"]:
        source += f" {metadata['volume']}"
        if metadata["issue"]:
            source += f"({metadata['issue']})"
    if metadata["pages"]:
        source += f": {metadata['pages']}" if metadata["volume"] else f" {metadata['pages']}"
    source = source.strip()
    if source:
        parts.append(f"{source}.")
    if metadata["doi"]:
        parts.append(f"[DOI](https://doi.org/{metadata['doi']})")
    return f"- {' '.join(parts)}"


def section_for(metadata: dict) -> str:
    if metadata["type"] in CONFERENCE_TYPES:
        return "Conference"
    authors = metadata["authors"]
    if not authors or is_self(*authors[0]) or is_self(*authors[-1]):
        return "First or corresponding author"
    return "Co-author"


def sort_key(metadata: dict) -> tuple:
    def number(value: str) -> int:
        return int(value) if value.isdigit() else 0

    return (number(metadata["year"]), number(metadata["month"]), number(metadata["day"]), metadata["title"].casefold())


def render_publications(works: list[dict]) -> str:
    sections: dict[str, list[dict]] = {"First or corresponding author": [], "Co-author": [], "Conference": []}
    for metadata in works:
        sections[section_for(metadata)].append(metadata)

    lines = ["<!-- This section is synchronized from the public ORCID record. -->"]
    for heading, items in sections.items():
        if not items:
            continue
        lines.extend(["", f"### {heading}"])
        lines.extend(render_work(item) for item in sorted(items, key=sort_key, reverse=True))
    if len(lines) == 1:
        lines.append("No public works are currently listed in ORCID.")
    return "\n".join(lines) + "\n"


def generate_publications(orcid_id: str) -> str:
    base_url = f"{ORCID_API}/{orcid_id}"
    works = []
    for summary in extract_work_summaries(fetch_json(f"{base_url}/works")):
        works.append(work_metadata(fetch_json(f"{base_url}/work/{summary['put-code']}")))
    return render_publications(works)


def update_readme(readme: str, publications: str) -> str:
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise ValueError("README.md must contain exactly one pair of ORCID publication markers")
    start = readme.index(START_MARKER) + len(START_MARKER)
    end = readme.index(END_MARKER)
    if start > end:
        raise ValueError("README.md ORCID publication markers are out of order")
    return f"{readme[:start]}\n{publications}{readme[end:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orcid", required=True, help="ORCID iD to synchronize")
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    args = parser.parse_args()

    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", args.orcid):
        parser.error("--orcid must be a validly formatted ORCID iD")

    try:
        publications = generate_publications(args.orcid)
        original = args.readme.read_text(encoding="utf-8")
        updated = update_readme(original, publications)
        if updated != original:
            args.readme.write_text(updated, encoding="utf-8")
            print(f"Updated {args.readme} from ORCID.")
        else:
            print(f"{args.readme} is already up to date.")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ORCID publication sync failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
