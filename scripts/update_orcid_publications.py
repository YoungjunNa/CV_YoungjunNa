#!/usr/bin/env python3
"""Synchronize the README publication list with a public ORCID record."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE = "https://pub.orcid.org/v3.0"
START_MARKER = "<!-- ORCID_PUBLICATIONS:START -->"
END_MARKER = "<!-- ORCID_PUBLICATIONS:END -->"


def fetch_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "orcid-readme-publications/1.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to retrieve valid ORCID data from {url}: {error}") from error


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


def work_title(work: dict) -> str:
    title = work.get("title")
    if isinstance(title, dict):
        return field_value(title.get("title"))
    return ""


def work_year(work: dict) -> str:
    publication_date = work.get("publication-date")
    if isinstance(publication_date, dict):
        return field_value(publication_date.get("year"))
    return ""


def work_authors(work: dict) -> list[str]:
    contributors = work.get("contributors")
    if not isinstance(contributors, dict):
        return []
    authors = []
    for contributor in as_list(contributors.get("contributor")):
        if not isinstance(contributor, dict):
            continue
        name = field_value(contributor.get("credit-name"))
        if name:
            authors.append(name)
    return authors


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


def render_work(work: dict) -> str:
    citation = field_value(work.get("citation", {}).get("citation-value")) if isinstance(work.get("citation"), dict) else ""
    title = work_title(work)
    doi = work_doi(work)
    if citation:
        citation = " ".join(citation.split())
        citation = citation.replace("[", r"\[").replace("]", r"\]")
        if doi and doi.lower() not in citation.lower():
            citation += f" DOI: https://doi.org/{doi}"
        return f"- {citation}"

    if not title:
        raise ValueError(f"ORCID work {work.get('put-code', '<unknown>')} has no title or citation")
    authors = ", ".join(work_authors(work))
    year = work_year(work)
    journal = field_value(work.get("journal-title"))
    parts = []
    if authors:
        parts.append(f"{authors}.")
    if year:
        parts.append(f"{year}.")
    parts.append(f"{title}.")
    if journal:
        parts.append(f"{journal}.")
    citation = " ".join(parts).replace("[", r"\[").replace("]", r"\]")
    if doi:
        citation += f" https://doi.org/{doi}"
    return f"- {citation}"


def generate_publications(orcid_id: str) -> str:
    base_url = f"{API_BASE}/{orcid_id}"
    summaries = extract_work_summaries(fetch_json(f"{base_url}/works"))
    works = []
    for summary in summaries:
        put_code = summary["put-code"]
        work = fetch_json(f"{base_url}/work/{put_code}")
        works.append(work)
    works.sort(key=lambda work: (work_year(work), work_title(work).casefold()), reverse=True)

    lines = ["<!-- This section is synchronized from the public ORCID record. -->"]
    if not works:
        lines.append("No public works are currently listed in ORCID.")
    else:
        lines.extend(render_work(work) for work in works)
    return "\n".join(lines)


def update_readme(readme: str, publications: str) -> str:
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise ValueError("README.md must contain exactly one pair of ORCID publication markers")
    start = readme.index(START_MARKER) + len(START_MARKER)
    end = readme.index(END_MARKER)
    if start > end:
        raise ValueError("README.md ORCID publication markers are out of order")
    return f"{readme[:start]}\n{publications}\n{readme[end:]}"


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
