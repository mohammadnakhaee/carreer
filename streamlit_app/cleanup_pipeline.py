#!/usr/bin/env python3
"""One-shot cleanup for data/pipeline.md.

What it does:
  1. Cross-references URLs in `## Pendientes` against `data/applications.md`.
  2. For URLs already evaluated, emits `- [x]` entries into `## Processed`
     using metadata from the tracker (company, role, score, PDF flag).
  3. Renames the `## Pendientes` header to `## Pendientes (archive)` so
     neither the GUI counter nor the `/career-ops pipeline` mode picks it up.
     The 281 truly-orphaned URLs are preserved in place.

Dry-run by default. Pass --apply to write changes. A timestamped backup of
pipeline.md is written next to it before any edit.

Usage:
    .venv/bin/python streamlit_app/cleanup_pipeline.py            # preview
    .venv/bin/python streamlit_app/cleanup_pipeline.py --apply    # commit
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import career_data as cd  # noqa: E402

URL_RE = re.compile(r"https?://\S+")


def extract_pendientes_urls(text: str) -> list[tuple[int, str, str]]:
    """Return [(line_idx, url, full_line)] for every `- [ ]` line in Pendientes."""
    out: list[tuple[int, str, str]] = []
    in_section = False
    for i, line in enumerate(text.split("\n")):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == "## Pendientes"
            continue
        if in_section and stripped.startswith("- [ ]"):
            m = URL_RE.search(stripped)
            if m:
                out.append((i, m.group(0).rstrip(",;"), line))
    return out


def format_processed_entry(app: cd.Application, url: str) -> str:
    """Match the existing Processed format in the file."""
    score = f"{app.score:.1f}/5" if app.score > 0 else "—"
    pdf_flag = "PDF ✅" if app.has_pdf else "PDF ❌"
    parts = [f"#{app.number}", url, app.company, app.role, score, pdf_flag]
    return "- [x] " + " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    pipeline_file = PROJECT_ROOT / "data" / "pipeline.md"
    text = pipeline_file.read_text(encoding="utf-8")
    lines = text.split("\n")

    pendientes = extract_pendientes_urls(text)
    apps = cd.parse_applications(PROJECT_ROOT, enrich=True)
    apps_by_url = {a.job_url: a for a in apps if a.job_url}

    matched: list[tuple[int, cd.Application, str]] = []
    orphan_count = 0
    for line_idx, url, _ in pendientes:
        app = apps_by_url.get(url)
        if app:
            matched.append((line_idx, app, url))
        else:
            orphan_count += 1

    print(f"Pendientes section: {len(pendientes)} URLs")
    print(f"  matched in applications.md: {len(matched)} → move to Processed")
    print(f"  orphaned:                   {orphan_count} → preserved under renamed header")
    print()
    print("Sample of entries to be moved to ## Processed:")
    for _, app, url in matched[:10]:
        print(f"  {format_processed_entry(app, url)}")
    if len(matched) > 10:
        print(f"  ... and {len(matched) - 10} more")
    print()

    if not args.apply:
        print("Dry-run. Re-run with --apply to commit.")
        return 0

    # --- Mutate -----------------------------------------------------------

    backup = pipeline_file.with_suffix(f".md.bak.{int(time.time())}")
    backup.write_text(text, encoding="utf-8")
    print(f"Backup written: {backup.relative_to(PROJECT_ROOT)}")

    # 1) Remove matched lines from Pendientes (highest line index first so
    #    earlier indices stay valid).
    matched_idxs = {line_idx for line_idx, _, _ in matched}
    new_lines: list[str] = []
    for i, line in enumerate(lines):
        if i in matched_idxs:
            continue  # drop
        new_lines.append(line)
    lines = new_lines

    # 2) Insert the moved entries at the end of ## Processed (before next ##).
    proc_idx = None
    next_section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Processed":
            proc_idx = i
            continue
        if proc_idx is not None and line.startswith("## "):
            next_section_idx = i
            break
    if proc_idx is None:
        print("ERROR: ## Processed section not found", file=sys.stderr)
        return 1

    insert_at = next_section_idx if next_section_idx is not None else len(lines)
    while insert_at - 1 > proc_idx and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    new_entries = [format_processed_entry(app, url) for _, app, url in matched]
    if new_entries:
        # Mark the block so the source is obvious later.
        new_entries = (
            ["", f"<!-- Migrated from ## Pendientes by cleanup_pipeline.py on "
                 f"{time.strftime('%Y-%m-%d')} ({len(new_entries)} entries) -->"]
            + new_entries
        )
        if next_section_idx is not None:
            new_entries.append("")  # blank line before next ##
        lines[insert_at:insert_at] = new_entries

    # 3) Rename the Pendientes header.
    for i, line in enumerate(lines):
        if line.strip() == "## Pendientes":
            lines[i] = "## Pendientes (archive)"
            break

    pipeline_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {pipeline_file.relative_to(PROJECT_ROOT)}")

    # Post-check
    counts = cd.count_pipeline_pending_by_section(PROJECT_ROOT)
    print()
    print("Post-cleanup pending counts (only sections the GUI/mode read):")
    for header, n in counts.items():
        print(f"  {header}: {n}")
    print(
        "\n(`## Pendientes (archive)` is invisible to the counter — the 281 "
        "orphaned URLs are preserved but won't trigger the runner.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
