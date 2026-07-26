"""Data layer for the Streamlit dashboard.

Python port of dashboard/internal/data/career.go — parses applications.md,
normalizes statuses, computes metrics, and writes status/notes updates back
to the tracker. Mirrors the Go TUI so behavior stays consistent.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("career-ops.data")

RE_REPORT_LINK = re.compile(r"\[(\d+)\]\(([^)]+)\)")
RE_SCORE = re.compile(r"(\d+\.?\d*)/5")
RE_REPORT_URL = re.compile(r"^\*\*URL:\*\*\s*(https?://\S+)", re.MULTILINE)
RE_ARCHETYPE = re.compile(r"\*\*Arquetipo(?:\s+detectado)?\*\*\s*\|\s*(.+)", re.IGNORECASE)
RE_ARCHETYPE_COLON = re.compile(r"\*\*Arquetipo:\*\*\s*(.+)", re.IGNORECASE)
RE_TLDR = re.compile(r"\*\*TL;DR\*\*\s*\|\s*(.+)", re.IGNORECASE)
RE_TLDR_COLON = re.compile(r"\*\*TL;DR:\*\*\s*(.+)", re.IGNORECASE)
RE_REMOTE = re.compile(r"\*\*Remote\*\*\s*\|\s*(.+)", re.IGNORECASE)
RE_COMP = re.compile(r"\*\*Comp\*\*\s*\|\s*(.+)", re.IGNORECASE)


STATUS_OPTIONS = [
    "Evaluated",
    "Applied",
    "Responded",
    "Interview",
    "Offer",
    "Rejected",
    "Discarded",
    "SKIP",
]

STATUS_GROUP_ORDER = [
    "interview",
    "offer",
    "responded",
    "applied",
    "evaluated",
    "skip",
    "rejected",
    "discarded",
]

FILTER_TABS = [
    ("all", "ALL"),
    ("evaluated", "EVALUATED"),
    ("applied", "APPLIED"),
    ("interview", "INTERVIEW"),
    ("top", "TOP ≥4"),
    ("skip", "SKIP"),
    ("rejected", "REJECTED"),
    ("discarded", "DISCARDED"),
]


@dataclass
class Application:
    number: int = 0
    date: str = ""
    company: str = ""
    role: str = ""
    status: str = ""
    score: float = 0.0
    score_raw: str = ""
    has_pdf: bool = False
    report_path: str = ""
    report_number: str = ""
    notes: str = ""
    job_url: str = ""
    archetype: str = ""
    tldr: str = ""
    remote: str = ""
    comp_estimate: str = ""
    # Raw line index in applications.md (for safe edits)
    _line_index: int = -1


@dataclass
class PipelineMetrics:
    total: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    avg_score: float = 0.0
    top_score: float = 0.0
    with_pdf: int = 0
    actionable: int = 0


@dataclass
class FunnelStage:
    label: str
    count: int
    pct: float


@dataclass
class ScoreBucket:
    label: str
    count: int


@dataclass
class WeekActivity:
    week: str
    count: int


@dataclass
class ProgressMetrics:
    funnel_stages: list[FunnelStage] = field(default_factory=list)
    score_buckets: list[ScoreBucket] = field(default_factory=list)
    weekly_activity: list[WeekActivity] = field(default_factory=list)
    response_rate: float = 0.0
    interview_rate: float = 0.0
    offer_rate: float = 0.0
    avg_score: float = 0.0
    top_score: float = 0.0
    total_offers: int = 0
    active_apps: int = 0


def applications_path(career_ops_path: Path) -> Path:
    """Return the on-disk path of applications.md, preferring data/ subdir."""
    p = career_ops_path / "data" / "applications.md"
    if p.exists():
        return p
    return career_ops_path / "applications.md"


def normalize_status(raw: str) -> str:
    """Mirror data.NormalizeStatus in the Go dashboard. Accepts EN + ES aliases."""
    s = raw.replace("**", "").strip().lower()
    # Strip trailing date (e.g., "applied 2026-03-12")
    idx = s.find(" 202")
    if idx > 0:
        s = s[:idx].strip()

    if "no aplicar" in s or "no_aplicar" in s or s == "skip" or "geo blocker" in s:
        return "skip"
    if "interview" in s or "entrevista" in s:
        return "interview"
    if s == "offer" or "oferta" in s:
        return "offer"
    if "responded" in s or "respondido" in s:
        return "responded"
    if "applied" in s or "aplicado" in s or s in {"enviada", "aplicada", "sent"}:
        return "applied"
    if "rejected" in s or "rechazado" in s or s == "rechazada":
        return "rejected"
    if (
        "discarded" in s
        or "descartado" in s
        or s in {"descartada", "cerrada", "cancelada"}
        or s.startswith("duplicado")
        or s.startswith("dup")
    ):
        return "discarded"
    if (
        "evaluated" in s
        or "evaluada" in s
        or s in {"condicional", "hold", "monitor", "evaluar", "verificar"}
    ):
        return "evaluated"
    return s


def status_label(norm: str) -> str:
    return {
        "interview": "Interview",
        "offer": "Offer",
        "responded": "Responded",
        "applied": "Applied",
        "evaluated": "Evaluated",
        "skip": "SKIP",
        "rejected": "Rejected",
        "discarded": "Discarded",
    }.get(norm, norm.title())


def status_priority(status: str) -> int:
    return {
        "interview": 0,
        "offer": 1,
        "responded": 2,
        "applied": 3,
        "evaluated": 4,
        "skip": 5,
        "rejected": 6,
        "discarded": 7,
    }.get(normalize_status(status), 8)


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into cell values. Mirrors the Go parser:
    pipe-delimited, optionally tab-delimited inside if a tab is present.
    """
    if "\t" in line:
        line = line.lstrip("|").strip()
        return [p.strip().strip("|") for p in line.split("\t")]
    line = line.strip().strip("|")
    return [p.strip() for p in line.split("|")]


def resolve_report_path(career_ops_path: Path, report_path: str) -> Optional[Path]:
    """Resolve a tracker report link to an on-disk path.

    Report links in applications.md are written relative to the tracker file's
    own directory: `../reports/...` when the tracker lives in `data/`,
    `reports/...` when it sits at the project root. Resolving them against
    `career_ops_path` directly is wrong for the `data/` layout (it escapes the
    project). Try the tracker-relative path first, then a few sensible
    fallbacks, and return the first that exists (or None).
    """
    if not report_path:
        return None
    tracker_dir = applications_path(career_ops_path).parent
    candidates = [
        tracker_dir / report_path,
        career_ops_path / report_path,
        career_ops_path / "reports" / Path(report_path).name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _enrich_from_report(app: Application, career_ops_path: Path) -> None:
    """Read the report header (~1KB) to extract URL/TL;DR/comp/etc."""
    if not app.report_path:
        return
    full = resolve_report_path(career_ops_path, app.report_path)
    if full is None:
        return
    try:
        content = full.read_text(encoding="utf-8")
    except OSError:
        return
    header = content[:1500]

    if m := RE_REPORT_URL.search(header):
        app.job_url = m.group(1)

    full_text = content  # use full text for TL;DR/archetype
    if m := RE_ARCHETYPE.search(full_text):
        app.archetype = m.group(1).rstrip("|").strip()
    elif m := RE_ARCHETYPE_COLON.search(full_text):
        app.archetype = m.group(1).rstrip("|").strip()

    if m := RE_TLDR.search(full_text):
        app.tldr = m.group(1).rstrip("|").strip()
    elif m := RE_TLDR_COLON.search(full_text):
        app.tldr = m.group(1).rstrip("|").strip()

    if m := RE_REMOTE.search(full_text):
        app.remote = m.group(1).rstrip("|").strip()

    if m := RE_COMP.search(full_text):
        app.comp_estimate = m.group(1).rstrip("|").strip()

    if len(app.tldr) > 200:
        app.tldr = app.tldr[:197] + "..."


def parse_applications(career_ops_path: Path, enrich: bool = True) -> list[Application]:
    """Parse applications.md and (optionally) enrich each row with report data."""
    path = applications_path(career_ops_path)
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError:
        return []

    apps: list[Application] = []
    fallback_num = 0

    for line_idx, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("# ") or line.startswith("|---") or line.startswith("| #"):
            continue
        if not line.startswith("|"):
            continue

        fields = _split_row(line)
        if len(fields) < 8:
            continue

        fallback_num += 1
        try:
            num = int(fields[0])
        except ValueError:
            num = fallback_num

        app = Application(
            number=num,
            date=fields[1],
            company=fields[2],
            role=fields[3],
            status=fields[5],
            has_pdf="✅" in fields[6],
            _line_index=line_idx,
        )
        app.score_raw = fields[4]
        if m := RE_SCORE.search(fields[4]):
            try:
                app.score = float(m.group(1))
            except ValueError:
                pass

        if m := RE_REPORT_LINK.search(fields[7]):
            app.report_number = m.group(1)
            app.report_path = m.group(2)

        if len(fields) > 8:
            app.notes = fields[8]

        apps.append(app)

    if enrich:
        for app in apps:
            _enrich_from_report(app, career_ops_path)

    return apps


def compute_metrics(apps: list[Application]) -> PipelineMetrics:
    m = PipelineMetrics(total=len(apps))
    total_score = 0.0
    scored = 0
    for a in apps:
        norm = normalize_status(a.status)
        m.by_status[norm] = m.by_status.get(norm, 0) + 1
        if a.score > 0:
            total_score += a.score
            scored += 1
            if a.score > m.top_score:
                m.top_score = a.score
        if a.has_pdf:
            m.with_pdf += 1
        if norm not in {"skip", "rejected", "discarded"}:
            m.actionable += 1
    if scored:
        m.avg_score = total_score / scored
    return m


def compute_progress(apps: list[Application]) -> ProgressMetrics:
    pm = ProgressMetrics()
    status_counts: dict[str, int] = {}
    total_score = 0.0
    scored = 0

    for a in apps:
        norm = normalize_status(a.status)
        status_counts[norm] = status_counts.get(norm, 0) + 1
        if a.score > 0:
            total_score += a.score
            scored += 1
            if a.score > pm.top_score:
                pm.top_score = a.score
        if norm == "offer":
            pm.total_offers += 1
        if norm not in {"skip", "rejected", "discarded"}:
            pm.active_apps += 1

    if scored:
        pm.avg_score = total_score / scored

    total = len(apps)
    applied = (
        status_counts.get("applied", 0)
        + status_counts.get("responded", 0)
        + status_counts.get("interview", 0)
        + status_counts.get("offer", 0)
        + status_counts.get("rejected", 0)
    )
    responded = (
        status_counts.get("responded", 0)
        + status_counts.get("interview", 0)
        + status_counts.get("offer", 0)
    )
    interview = status_counts.get("interview", 0) + status_counts.get("offer", 0)
    offer = status_counts.get("offer", 0)

    def pct(part: int, whole: int) -> float:
        return (part / whole * 100) if whole else 0.0

    pm.funnel_stages = [
        FunnelStage("Evaluated", total, 100.0),
        FunnelStage("Applied", applied, pct(applied, total)),
        FunnelStage("Responded", responded, pct(responded, applied)),
        FunnelStage("Interview", interview, pct(interview, applied)),
        FunnelStage("Offer", offer, pct(offer, applied)),
    ]

    if applied:
        pm.response_rate = responded / applied * 100
        pm.interview_rate = interview / applied * 100
        pm.offer_rate = offer / applied * 100

    buckets = [0, 0, 0, 0, 0]
    for a in apps:
        if a.score <= 0:
            continue
        if a.score >= 4.5:
            buckets[0] += 1
        elif a.score >= 4.0:
            buckets[1] += 1
        elif a.score >= 3.5:
            buckets[2] += 1
        elif a.score >= 3.0:
            buckets[3] += 1
        else:
            buckets[4] += 1
    pm.score_buckets = [
        ScoreBucket("4.5-5.0", buckets[0]),
        ScoreBucket("4.0-4.4", buckets[1]),
        ScoreBucket("3.5-3.9", buckets[2]),
        ScoreBucket("3.0-3.4", buckets[3]),
        ScoreBucket("<3.0", buckets[4]),
    ]

    week_counts: dict[str, int] = {}
    for a in apps:
        if not a.date:
            continue
        try:
            dt = datetime.strptime(a.date, "%Y-%m-%d")
        except ValueError:
            continue
        year, week, _ = dt.isocalendar()
        key = f"{year}-W{week:02d}"
        week_counts[key] = week_counts.get(key, 0) + 1
    sorted_weeks = sorted(week_counts.keys())[-8:]
    pm.weekly_activity = [WeekActivity(w, week_counts[w]) for w in sorted_weeks]
    return pm


def filter_apps(
    apps: list[Application], tab: str, query: str = ""
) -> list[Application]:
    q = query.strip().lower()
    out: list[Application] = []
    for a in apps:
        if q and q not in a.company.lower() and q not in a.role.lower() and q not in a.notes.lower():
            continue
        norm = normalize_status(a.status)
        if tab == "all":
            out.append(a)
        elif tab == "top":
            if a.score >= 4.0 and norm != "skip":
                out.append(a)
        elif norm == tab:
            out.append(a)
    return out


def sort_apps(apps: list[Application], mode: str) -> list[Application]:
    if mode == "score":
        return sorted(apps, key=lambda a: a.score, reverse=True)
    if mode == "date":
        return sorted(apps, key=lambda a: a.date, reverse=True)
    if mode == "company":
        return sorted(apps, key=lambda a: a.company.lower())
    if mode == "status":
        return sorted(apps, key=lambda a: status_priority(a.status))
    return apps


# -- Writers --

def _rewrite_cells(cells: list[str]) -> str:
    """Rebuild a markdown table row from cells with leading/trailing pipes."""
    return "| " + " | ".join(cells) + " |"


def _find_row_index(lines: list[str], app: Application) -> Optional[int]:
    """Locate the line in applications.md that matches this application.

    Prefer matching by report number (unique), then by (#, company, role).
    """
    if 0 <= app._line_index < len(lines):
        candidate = lines[app._line_index]
        if candidate.startswith("|") and (
            (app.report_number and f"[{app.report_number}]" in candidate)
            or (f"| {app.company} |" in candidate or f"\t{app.company}\t" in candidate)
        ):
            return app._line_index

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if app.report_number and f"[{app.report_number}]" in line:
            return i
    # Last-resort fallback: match by # + company + role
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        fields = _split_row(line)
        if len(fields) < 8:
            continue
        try:
            if int(fields[0]) == app.number and fields[2] == app.company and fields[3] == app.role:
                return i
        except ValueError:
            continue
    return None


def update_application(
    career_ops_path: Path,
    app: Application,
    new_status: Optional[str] = None,
    new_notes: Optional[str] = None,
) -> bool:
    """Update status and/or notes for an application. Returns True on success."""
    if new_status is None and new_notes is None:
        return False
    path = applications_path(career_ops_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    lines = text.split("\n")
    idx = _find_row_index(lines, app)
    if idx is None:
        return False

    line = lines[idx]
    fields = _split_row(line)
    if len(fields) < 8:
        return False
    # Pad to 9 columns if notes missing
    while len(fields) < 9:
        fields.append("")

    if new_status is not None:
        # Strip any markdown bold / trailing date per states.yml rules.
        clean = new_status.replace("**", "").strip()
        fields[5] = clean
    if new_notes is not None:
        # Notes can't contain pipes (table delimiter) — replace with U+2758 fallback.
        fields[8] = new_notes.replace("|", "❘").strip()

    lines[idx] = _rewrite_cells(fields)
    path.write_text("\n".join(lines), encoding="utf-8")
    return True


def load_report_markdown(career_ops_path: Path, report_path: str) -> str:
    full = resolve_report_path(career_ops_path, report_path)
    if full is None:
        return ""
    try:
        return full.read_text(encoding="utf-8")
    except OSError:
        return ""


# -- Output files (CVs, cover letters) ---------------------------------------

CV_PREFIXES = ("cv-",)
COVER_PREFIXES = ("cover-letter-", "cover_letter-", "coverletter-")


def _slug_from_report_path(report_path: str) -> str:
    """Derive the company slug from a report filename.

    Example: `reports/021-hivemq-2026-05-20.md` -> `hivemq`.
    `reports/014-trade-republic-2026-05-18.md` -> `trade-republic`.
    Strips the leading number and trailing ISO date.
    """
    if not report_path:
        return ""
    stem = Path(report_path).stem  # drop .md
    # Drop leading "NNN-"
    stem = re.sub(r"^\d+-", "", stem)
    # Drop trailing "-YYYY-MM-DD"
    stem = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", stem)
    return stem.lower()


def _slug_from_company(company: str) -> str:
    s = company.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@dataclass
class OutputFile:
    path: Path
    kind: str  # "cv", "cover_letter", "other"
    size_bytes: int
    mtime: float

    @property
    def mime(self) -> str:
        suffix = self.path.suffix.lower()
        return {
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".html": "text/html",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(suffix, "application/octet-stream")


def sync_static_output(career_ops_path: Path) -> None:
    """Mirror `output/` into `streamlit_app/static/output/` via hardlinks.

    Streamlit's static server refuses symlinked files for security, and we
    don't want to duplicate disk usage. Hardlinks give us a real directory
    entry that points at the same inode — Streamlit serves it, edits propagate
    automatically, and removed files are pruned on next sync.
    """
    src = career_ops_path / "output"
    dst = career_ops_path / "streamlit_app" / "static" / "output"
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)

    src_entries: dict[str, Path] = {}
    for entry in src.iterdir():
        if entry.is_file():
            src_entries[entry.name] = entry

    pruned = 0
    for entry in dst.iterdir():
        if entry.is_file() and entry.name not in src_entries:
            try:
                entry.unlink()
                pruned += 1
            except OSError:
                pass

    linked = 0
    for name, source in src_entries.items():
        target = dst / name
        try:
            src_stat = source.stat()
        except OSError:
            continue
        try:
            tgt_stat = target.stat()
            same = tgt_stat.st_ino == src_stat.st_ino and tgt_stat.st_size == src_stat.st_size
        except FileNotFoundError:
            same = False
        if same:
            continue
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        try:
            os.link(source, target)
            linked += 1
        except OSError:
            # Cross-filesystem or hardlinks unsupported — fall back to copy.
            try:
                shutil.copy2(source, target)
                linked += 1
            except OSError:
                pass
    if linked or pruned:
        log.debug("sync_static_output: linked=%d pruned=%d total=%d",
                  linked, pruned, len(src_entries))


def newest_files_by_kind(
    career_ops_path: Path, app: "Application"
) -> dict[str, Optional[OutputFile]]:
    """Return the newest CV and newest cover-letter file for an app (or None).

    Convenience wrapper over `find_application_files` for the table cell case
    where we only need one URL per kind per row.
    """
    files = find_application_files(career_ops_path, app)
    result: dict[str, Optional[OutputFile]] = {"cv": None, "cover_letter": None}
    for f in files:
        if f.kind in result and result[f.kind] is None:
            result[f.kind] = f
    return result


def find_application_files(
    career_ops_path: Path, app: "Application"
) -> list[OutputFile]:
    """Return CVs / cover letters / other artifacts associated with an app.

    Matches files in `output/` whose name contains the company slug
    (derived from the report filename when available, else from the company
    name). Results are sorted: cover letters first, then CVs, newest first.
    """
    output_dir = career_ops_path / "output"
    if not output_dir.is_dir():
        return []

    slugs: list[str] = []
    if app.report_path:
        s = _slug_from_report_path(app.report_path)
        if s:
            slugs.append(s)
    company_slug = _slug_from_company(app.company)
    if company_slug and company_slug not in slugs:
        slugs.append(company_slug)
    if not slugs:
        return []

    seen: set[Path] = set()
    files: list[OutputFile] = []
    for entry in output_dir.iterdir():
        if not entry.is_file():
            continue
        name = entry.name.lower()
        if not any(slug in name for slug in slugs):
            continue
        if entry in seen:
            continue
        seen.add(entry)

        if name.startswith(COVER_PREFIXES):
            kind = "cover_letter"
        elif name.startswith(CV_PREFIXES):
            kind = "cv"
        else:
            kind = "other"

        try:
            stat = entry.stat()
        except OSError:
            continue
        files.append(
            OutputFile(
                path=entry, kind=kind, size_bytes=stat.st_size, mtime=stat.st_mtime
            )
        )

    # Sort: cover letters first, then CVs, then other; within each, newest first.
    kind_order = {"cover_letter": 0, "cv": 1, "other": 2}
    files.sort(key=lambda f: (kind_order[f.kind], -f.mtime))
    return files


# -- Pipeline inbox (data/pipeline.md) ---------------------------------------

RE_URL = re.compile(r"https?://\S+")


def pipeline_path(career_ops_path: Path) -> Path:
    p = career_ops_path / "data" / "pipeline.md"
    if p.exists():
        return p
    return career_ops_path / "pipeline.md"


@dataclass
class PipelineEntry:
    url: str
    company: str = ""
    role: str = ""
    note: str = ""

    def to_line(self) -> str:
        bits = [self.url]
        if self.company:
            bits.append(self.company)
        if self.role:
            bits.append(self.role)
        if self.note:
            bits.append(self.note)
        return "- [ ] " + " | ".join(bits)


def parse_pipeline_input(text: str) -> tuple[list[PipelineEntry], list[str]]:
    """Parse a textarea of pasted pipeline lines.

    Returns (entries, errors). Accepted shapes per line:
        - [ ] #ID | URL | Company | Role | note
        - [ ] URL | Company | Role
        URL | Company | Role
        URL
    Strips checkbox/ID prefix; locates the URL by `https?://` regardless of
    column position; pipe-separated fields around the URL become metadata.
    """
    entries: list[PipelineEntry] = []
    errors: list[str] = []
    seen_urls: set[str] = set()

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        # Strip leading markdown list markers and checkboxes
        line = re.sub(r"^[-*]\s+\[[ x!]\]\s*", "", line)
        # Strip leading #ID followed by pipe
        line = re.sub(r"^#\d+\s*\|\s*", "", line)

        urls = RE_URL.findall(line)
        if not urls:
            errors.append(f"Line {lineno}: no URL found — `{raw[:60]}`")
            continue
        if len(urls) > 1:
            errors.append(f"Line {lineno}: multiple URLs, taking first — `{raw[:60]}`")
        url = urls[0].rstrip(",;")

        if url in seen_urls:
            errors.append(f"Line {lineno}: duplicate within input — {url}")
            continue
        seen_urls.add(url)

        # Split remaining fields by pipe, drop the URL itself.
        parts = [p.strip() for p in line.split("|")]
        meta = [p for p in parts if p and url not in p]
        company = meta[0] if len(meta) > 0 else ""
        role = meta[1] if len(meta) > 1 else ""
        note = " | ".join(meta[2:]) if len(meta) > 2 else ""
        entries.append(PipelineEntry(url=url, company=company, role=role, note=note))

    return entries, errors


def _existing_pipeline_urls(text: str) -> set[str]:
    """Return all URLs already present in pipeline.md (Pending or Processed)."""
    return {m.group(0).rstrip(",;") for m in RE_URL.finditer(text)}


def append_to_pipeline(
    career_ops_path: Path, entries: list[PipelineEntry]
) -> tuple[int, list[str]]:
    """Append entries to the `## Pending` section of pipeline.md.

    Returns (count_added, skipped_dupes). Skips URLs already present anywhere
    in pipeline.md (Pending or Processed). Creates the file if missing.
    """
    path = pipeline_path(career_ops_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Pipeline -- Pending URLs Inbox\n\n"
            "Add job URLs as checkbox items. Run `/career-ops pipeline` to process them.\n\n"
            "Format: `- [ ] {url} | {company} | {title}`\n\n"
            "## Pending\n\n"
            "## Processed\n",
            encoding="utf-8",
        )

    text = path.read_text(encoding="utf-8")
    existing = _existing_pipeline_urls(text)

    new_lines: list[str] = []
    skipped: list[str] = []
    for e in entries:
        if e.url in existing:
            skipped.append(e.url)
            continue
        new_lines.append(e.to_line())
        existing.add(e.url)

    if not new_lines:
        return 0, skipped

    lines = text.split("\n")
    # Find ## Pending header, then the start of the next section.
    pending_idx = None
    next_section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Pending":
            pending_idx = i
            continue
        if pending_idx is not None and line.startswith("## "):
            next_section_idx = i
            break

    if pending_idx is None:
        # No ## Pending — append as a new section at the end.
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("## Pending")
        lines.append("")
        lines.extend(new_lines)
        lines.append("")
    else:
        # Insert before next section header (or at EOF if none), keeping a
        # blank line separating the new items from the next section header.
        insert_at = next_section_idx if next_section_idx is not None else len(lines)
        # Trim trailing blank lines inside the Pending block so additions stack tightly.
        while insert_at - 1 > pending_idx and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        block = new_lines[:]
        if next_section_idx is not None:
            block.append("")  # blank line before next ## section
        lines[insert_at:insert_at] = block

    path.write_text("\n".join(lines), encoding="utf-8")
    return len(new_lines), skipped


# -- Pipeline runner (subprocess management) ---------------------------------

import json
import signal
import subprocess
import time

PIPELINE_STATE_FILE = ".streamlit/pipeline-run.json"
PIPELINE_LOG_DIR = ".streamlit/pipeline-logs"

# Headless mode is a single round-trip — `claude -p` returns once and exits.
# The bare `/career-ops pipeline` skill asks "how would you like to proceed?",
# which in headless mode just exits without doing work. We pre-answer that
# question so the subprocess actually processes URLs.
PIPELINE_PROMPT = (
    "/career-ops pipeline\n\n"
    "Process every URL in the `## Pending` section of `data/pipeline.md` "
    "without asking for confirmation. For each URL: extract the JD "
    "(Playwright/WebFetch/WebSearch), run the full A–F evaluation, write the "
    "report under `reports/`, generate a PDF if score ≥ 3.0, and move the "
    "entry from `## Pending` to `## Processed`. Ignore the "
    "`## Pendientes (archive)` section entirely. If a URL is unreachable, "
    "mark it `- [!]` with a brief note and continue with the next one.\n\n"
    "Name generated PDFs WITHOUT the report/application number — follow the "
    "`cv-{candidate}-{company}-{YYYY-MM-DD}.pdf` convention (e.g. "
    "`cv-amir-golparvar-acme-2026-07-02.pdf`), never `89-acme-...pdf`."
)

DEFAULT_PIPELINE_CMD = [
    "claude",
    "-p",
    PIPELINE_PROMPT,
    "--dangerously-skip-permissions",
    # stream-json keeps stdout line-buffered (one JSON event per line) so the
    # log file fills in real time. With --output-format text Node block-buffers
    # the file fd and we see nothing for minutes until a 4–16 KB buffer fills.
    "--output-format",
    "stream-json",
    "--include-partial-messages",
    "--verbose",
]


def build_pipeline_cmd() -> list[str]:
    """Compose the spawn argv for the pipeline runner."""
    return list(DEFAULT_PIPELINE_CMD)


def _state_path(career_ops_path: Path) -> Path:
    return career_ops_path / PIPELINE_STATE_FILE


def _pid_alive(pid: int) -> bool:
    """True iff pid points at a running (non-zombie) process.

    A subprocess we spawned becomes a zombie when it exits until reaped, and
    plain os.kill(pid, 0) returns success for zombies — so we'd mis-report
    finished runs as still alive. Reap-with-WNOHANG handles our own children;
    /proc/{pid}/status catches the rest on Linux.
    """
    if pid <= 0:
        return False
    # Reap if this pid is our child and has exited.
    try:
        reaped_pid, _ = os.waitpid(pid, os.WNOHANG)
        if reaped_pid == pid:
            return False
    except ChildProcessError:
        pass  # not our child; continue with other checks
    except OSError:
        pass
    # Linux: read /proc to detect zombie state.
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("State:"):
                    return not line.split()[1].startswith("Z")
    except FileNotFoundError:
        return False
    except OSError:
        pass
    # Fallback (e.g. macOS without /proc): existence-only check.
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _log_shows_completion(career_ops_path: Path, log_path: Optional[str]) -> bool:
    """True if the runner's log ends with a terminal result event.

    The `claude -p ... --output-format stream-json` runner emits a final
    `{"type":"result", ...}` object when the turn ends. A run whose log carries
    that line is finished — even if its PID lingers as an unreaped zombie, or on
    platforms where _pid_alive degrades to an existence-only check that can't
    tell a zombie from a live process. Belt-and-suspenders next to the PID probe.
    """
    if not log_path:
        return False
    full = career_ops_path / log_path
    try:
        with open(full, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))  # result line is last; tail is plenty
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue  # partial first line from the seek, or non-JSON noise
        if evt.get("type") == "result":
            return True
    return False


def get_pipeline_run(career_ops_path: Path) -> Optional[dict]:
    """Return current/last pipeline run state, or None if never run."""
    path = _state_path(career_ops_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    alive = _pid_alive(int(data.get("pid", 0)))
    if alive and _log_shows_completion(career_ops_path, data.get("log_path")):
        alive = False  # process reported the run done; PID probe was fooled
    data["alive"] = alive
    return data


def start_pipeline_run(
    career_ops_path: Path, cmd: Optional[list[str]] = None
) -> dict:
    """Spawn the pipeline runner as a detached subprocess. Returns state dict.

    Raises RuntimeError if a run is already alive, FileNotFoundError if the
    requested binary isn't on PATH.
    """
    existing = get_pipeline_run(career_ops_path)
    if existing and existing.get("alive"):
        raise RuntimeError(
            f"Pipeline already running (pid={existing['pid']}). Stop it before starting another."
        )

    if cmd is None:
        cmd = DEFAULT_PIPELINE_CMD

    state_dir = career_ops_path / ".streamlit"
    log_dir = career_ops_path / PIPELINE_LOG_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    log_path = log_dir / f"pipeline-{ts}.log"

    log_fh = open(log_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(career_ops_path),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach from streamlit's process group
        )
    except FileNotFoundError:
        log_fh.close()
        try:
            log_path.unlink()
        except OSError:
            pass
        raise

    state = {
        "pid": proc.pid,
        "started_at": time.time(),
        "log_path": str(log_path.relative_to(career_ops_path)),
        "cmd": " ".join(cmd),
        "pending_count": count_pipeline_pending(career_ops_path),
    }
    _state_path(career_ops_path).write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    log.info(
        "pipeline spawned: pid=%d pending=%d log=%s cmd=%s",
        proc.pid, state["pending_count"], state["log_path"], state["cmd"],
    )
    return state


def stop_pipeline_run(career_ops_path: Path) -> bool:
    """Send SIGTERM to the running pipeline. Returns True if a process was signalled."""
    state = get_pipeline_run(career_ops_path)
    if not state or not state.get("alive"):
        log.debug("stop_pipeline_run called but no live process")
        return False
    pid = int(state["pid"])
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        log.info("pipeline SIGTERM sent to pgid=%d (pid=%d)", pgid, pid)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("pipeline SIGTERM sent to pid=%d (no pgroup)", pid)
        except OSError as exc:
            log.error("pipeline SIGTERM failed pid=%d: %s", pid, exc)
            return False
    return True


# -- Generic detached-task runner (shares logs + liveness with the pipeline) --


def _task_state_path(career_ops_path: Path, name: str) -> Path:
    return career_ops_path / ".streamlit" / f"task-{name}.json"


def get_task_run(career_ops_path: Path, name: str) -> Optional[dict]:
    """Return current/last state for a named detached task, or None."""
    path = _task_state_path(career_ops_path, name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    alive = _pid_alive(int(data.get("pid", 0)))
    if alive and _log_shows_completion(career_ops_path, data.get("log_path")):
        alive = False
    data["alive"] = alive
    return data


def start_task_run(
    career_ops_path: Path, name: str, cmd: list[str], meta: Optional[dict] = None
) -> dict:
    """Spawn a named detached `claude -p` task. Returns its state dict.

    Same detachment + logging model as start_pipeline_run, but keyed by `name`
    so it coexists with the pipeline runner (separate state file + log prefix).
    Raises RuntimeError if a task of this name is already alive.
    """
    existing = get_task_run(career_ops_path, name)
    if existing and existing.get("alive"):
        raise RuntimeError(
            f"Task '{name}' already running (pid={existing['pid']}). Stop it first."
        )
    state_dir = career_ops_path / ".streamlit"
    log_dir = career_ops_path / PIPELINE_LOG_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    log_path = log_dir / f"{name}-{ts}.log"
    log_fh = open(log_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(career_ops_path),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        log_fh.close()
        try:
            log_path.unlink()
        except OSError:
            pass
        raise

    state = {
        "pid": proc.pid,
        "started_at": time.time(),
        "log_path": str(log_path.relative_to(career_ops_path)),
        "cmd": " ".join(cmd),
    }
    if meta:
        state.update(meta)
    _task_state_path(career_ops_path, name).write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    log.info("task '%s' spawned: pid=%d log=%s", name, proc.pid, state["log_path"])
    return state


def stop_task_run(career_ops_path: Path, name: str) -> bool:
    """SIGTERM a named detached task. Returns True if a process was signalled."""
    state = get_task_run(career_ops_path, name)
    if not state or not state.get("alive"):
        return False
    pid = int(state["pid"])
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            log.error("task '%s' SIGTERM failed pid=%d: %s", name, pid, exc)
            return False
    return True


def _answers_slug(app: "Application") -> str:
    slug = _slug_from_report_path(app.report_path) if app.report_path else ""
    if not slug:
        slug = _slug_from_company(app.company)
    return slug or "job"


def answers_output_path(app: "Application", date_str: str) -> str:
    """Repo-relative path where drafted application answers are written."""
    return str(Path("output") / f"answers-{_answers_slug(app)}-{date_str}.md")


def find_answers_file(career_ops_path: Path, app: "Application") -> Optional[Path]:
    """Return the newest drafted-answers file for this job, or None."""
    out = career_ops_path / "output"
    if not out.is_dir():
        return None
    matches = sorted(
        out.glob(f"answers-{_answers_slug(app)}-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def build_answer_cmd(
    career_ops_path: Path,
    *,
    company: str,
    role: str,
    report_path: str,
    questions: str,
    answers_path: str,
) -> list[str]:
    """Compose the `claude -p` argv that drafts application answers grounded in
    the candidate's own profile, in their first-person voice."""
    profile_files = ["cv.md", "article-digest.md", "modes/_profile.md", "config/profile.yml"]
    present = [f for f in profile_files if (career_ops_path / f).exists()]
    sources = "\n".join(f"- {f}" for f in present)
    if report_path and (career_ops_path / report_path).exists():
        sources += f"\n- {report_path}  (this role's evaluation report)"

    prompt = (
        "You are drafting answers to a job application's custom questions on "
        "behalf of the candidate, written in their own first-person voice.\n\n"
        "Read these files for the candidate's background, proof points, and voice:\n"
        f"{sources}\n\n"
        f"Role: {role} at {company}.\n\n"
        "Answer EACH of the following application questions:\n\n"
        f"{questions.strip()}\n\n"
        "Rules:\n"
        "- First person, as the candidate. Ground every claim in the files "
        "above; never invent employers, titles, metrics, or projects. If the "
        "profile lacks a basis for a strong answer, stay honest about what is "
        "true rather than fabricating.\n"
        "- Concise and specific: roughly 60-150 words per answer unless the "
        "question implies shorter. Lead with the concrete point.\n"
        "- Plain, direct English. Do NOT use em-dashes. Avoid 'delve', "
        "'leverage', 'robust', 'spearhead' and similar filler. No three-part "
        "parallel phrases. Vary sentence length so it reads as a real person.\n"
        "- Follow the candidate's established writing style in modes/_profile.md "
        "if that file defines one.\n"
        f"- Write the final answers as markdown to `{answers_path}`, with one "
        "`### <question>` heading per answer, and also print them to stdout.\n\n"
        "Do not ask for confirmation. Produce the answers directly."
    )
    return [
        "claude",
        "-p",
        prompt,
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]


def tail_pipeline_log(
    career_ops_path: Path, log_path: str, max_lines: int = 60
) -> str:
    """Render the tail of a pipeline log. Handles both plain text and JSONL
    (`--output-format stream-json`) formats; non-JSON lines pass through."""
    full = career_ops_path / log_path
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    rendered = _render_log_lines(text.splitlines())
    return "\n".join(rendered[-max_lines:])


def _render_log_lines(lines: list[str]) -> list[str]:
    """Turn raw log lines (mix of plain text + JSONL stream events) into a
    human-readable list. Consecutive text_delta chunks are concatenated."""
    out: list[str] = []
    text_buf: list[str] = []

    def flush() -> None:
        if text_buf:
            joined = "".join(text_buf)
            out.extend(joined.splitlines() or [joined])
            text_buf.clear()

    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if not line.lstrip().startswith("{"):
            flush()
            out.append(line)
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            flush()
            out.append(line)
            continue

        typ = evt.get("type")

        # Streaming token deltas — buffer until we hit a non-delta event.
        if typ == "stream_event":
            e = evt.get("event", {})
            if e.get("type") == "content_block_delta":
                d = e.get("delta", {})
                if d.get("type") == "text_delta":
                    text_buf.append(d.get("text", ""))
                    continue
            continue  # other stream sub-events are noise

        flush()

        if typ == "assistant":
            for c in evt.get("message", {}).get("content", []):
                ctype = c.get("type")
                # Skip text content: with --include-partial-messages on, the
                # streaming deltas have already emitted the full text.
                if ctype == "tool_use":
                    name = c.get("name", "?")
                    summary = _summarize_tool_input(c.get("input") or {})
                    out.append(f"⚙ {name}({summary})")
        elif typ == "user":
            for c in evt.get("message", {}).get("content", []):
                if c.get("type") == "tool_result":
                    payload = c.get("content", "")
                    if isinstance(payload, list):
                        payload = "".join(
                            p.get("text", "") for p in payload
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    snippet = (str(payload) or "").strip().split("\n")[0][:140]
                    out.append(f"  ↳ {snippet or '(empty)'}")
        elif typ == "result":
            cost = evt.get("total_cost_usd", 0) or 0
            subtype = evt.get("subtype", "?")
            out.append(f"━━━ result: {subtype} (cost: ${cost:.2f}) ━━━")
        # system/init/etc → silent

    flush()
    return out


def _summarize_tool_input(inp: dict) -> str:
    """Compact one-line summary of tool call args for log display."""
    if not inp:
        return ""
    # Prefer common fields that identify the action
    for key in ("file_path", "url", "command", "pattern", "path", "prompt"):
        if key in inp and isinstance(inp[key], str):
            v = inp[key]
            if len(v) > 80:
                v = v[:77] + "…"
            return f"{key}={v!r}"
    # Fallback: just list keys
    return ", ".join(inp.keys())


PENDING_SECTION_HEADERS = {"## Pending", "## Pendientes"}


def count_pipeline_pending(career_ops_path: Path) -> int:
    """Count `- [ ]` items across all pending sections (English + Spanish)."""
    return sum(count_pipeline_pending_by_section(career_ops_path).values())


def count_pipeline_pending_by_section(career_ops_path: Path) -> dict[str, int]:
    """Return {section_header: count} for each pending-style section."""
    path = pipeline_path(career_ops_path)
    counts: dict[str, int] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return counts
    current: Optional[str] = None
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped if stripped in PENDING_SECTION_HEADERS else None
            continue
        if current and stripped.startswith("- [ ]"):
            counts[current] = counts.get(current, 0) + 1
    return counts


# -- Local artifact cleanup --------------------------------------------------

_CLEANUP_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def human_bytes(n: int) -> str:
    """Format a byte count compactly (e.g. 883558 -> '863 KB')."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.0f} GB"


def _artifact(root: Path, path: Path, category: str) -> dict:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {"path": path, "rel": str(path.relative_to(root)), "category": category, "size": size}


def scan_local_artifacts(career_ops_path: Path) -> list[dict]:
    """Enumerate throwaway local files that are safe to delete.

    Covers: pipeline stream-json logs, a *finished* run's state file, orphaned
    static-mirror files (present in static/output but gone from output/), and
    dangling *.bak / *.bak.<ts> backups anywhere in the tree. Never includes the
    log or state of an active run, and never touches real files under output/,
    reports/, or the user's CV. Returns a list of {path, rel, category, size}.
    """
    items: list[dict] = []
    run = get_pipeline_run(career_ops_path)
    running = bool(run and run.get("alive"))
    active_log = None
    if running and run:
        try:
            active_log = (career_ops_path / run["log_path"]).resolve()
        except (OSError, KeyError):
            active_log = None

    # 1. Pipeline logs — keep the active run's log.
    log_dir = career_ops_path / PIPELINE_LOG_DIR
    if log_dir.is_dir():
        for f in sorted(log_dir.glob("*.log")):
            if active_log is not None and f.resolve() == active_log:
                continue
            items.append(_artifact(career_ops_path, f, "Pipeline log"))

    # 2. Run state file — only once the run has finished.
    state = _state_path(career_ops_path)
    if state.exists() and not running:
        items.append(_artifact(career_ops_path, state, "Run state"))

    # 3. Orphaned static-mirror files (safe: hardlink/copy, not the real output/).
    src = career_ops_path / "output"
    dst = career_ops_path / "streamlit_app" / "static" / "output"
    src_names = {e.name for e in src.iterdir() if e.is_file()} if src.is_dir() else set()
    if dst.is_dir():
        for f in sorted(dst.iterdir()):
            if f.is_file() and f.name not in src_names:
                items.append(_artifact(career_ops_path, f, "Orphaned static mirror"))

    # 4. Dangling *.bak / *.bak.<ts> backups, skipping VCS/deps dirs.
    for dirpath, dirnames, filenames in os.walk(career_ops_path):
        dirnames[:] = [d for d in dirnames if d not in _CLEANUP_SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".bak") or ".bak." in fn:
                items.append(_artifact(career_ops_path, Path(dirpath) / fn, "Backup file"))

    return items


def delete_local_artifacts(items: list[dict]) -> tuple[int, int]:
    """Delete the given artifacts. Returns (deleted_count, freed_bytes)."""
    deleted = 0
    freed = 0
    for it in items:
        path: Path = it["path"]
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        try:
            path.unlink()
            deleted += 1
            freed += size
        except OSError as exc:
            log.warning("cleanup: failed to delete %s: %s", path, exc)
    return deleted, freed


# -- Generated-item deletion (CVs, cover letters, parsed jobs) ----------------

TRACKER_HEADER = (
    "# Applications Tracker\n\n"
    "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
    "|---|------|---------|------|-------|--------|-----|--------|-------|\n"
)


def scan_generated_items(career_ops_path: Path) -> dict[str, list[dict]]:
    """Group user-generated deliverables for bulk deletion.

    Unlike scan_local_artifacts (throwaway files), these are real outputs the
    user produced: tailored CVs and cover letters in output/, and parsed-job
    evaluation reports in reports/. Returns {category: [{path, rel, size}]}.
    The applications tracker is reset separately via reset_tracker().
    """
    groups: dict[str, list[dict]] = {
        "CVs": [],
        "Cover letters": [],
        "Parsed jobs (reports)": [],
    }
    output_dir = career_ops_path / "output"
    if output_dir.is_dir():
        for entry in sorted(output_dir.iterdir()):
            if not entry.is_file():
                continue
            name = entry.name.lower()
            if name.startswith(CV_PREFIXES):
                groups["CVs"].append(_artifact(career_ops_path, entry, "CV"))
            elif name.startswith(COVER_PREFIXES):
                groups["Cover letters"].append(_artifact(career_ops_path, entry, "Cover letter"))
    reports_dir = career_ops_path / "reports"
    if reports_dir.is_dir():
        for entry in sorted(reports_dir.glob("*.md")):
            groups["Parsed jobs (reports)"].append(_artifact(career_ops_path, entry, "Report"))
    return groups


def reset_tracker(career_ops_path: Path) -> int:
    """Overwrite applications.md with the empty header. Returns rows removed."""
    path = applications_path(career_ops_path)
    removed = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("|") and not s.startswith("| #") and "---" not in s:
                removed += 1
    except OSError:
        pass
    try:
        path.write_text(TRACKER_HEADER, encoding="utf-8")
    except OSError as exc:
        log.warning("reset_tracker: failed to write %s: %s", path, exc)
        return 0
    return removed


def reset_pipeline_processed(career_ops_path: Path) -> int:
    """Empty the `## Processed` section of pipeline.md. Returns entries removed.

    Processed entries are the pipeline's 'already done' record; the inbox dedup
    skips any URL found anywhere in pipeline.md, so leftover Processed entries
    block re-adding a job after its report/tracker row was deleted. Clearing
    them re-enables re-processing. Keeps the Pending and Pendientes sections and
    every non-entry line (headers, prose) intact.
    """
    path = pipeline_path(career_ops_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    out: list[str] = []
    in_processed = False
    removed = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_processed = stripped == "## Processed"
            out.append(line)
            continue
        if in_processed and stripped.startswith("- ["):
            removed += 1
            continue  # drop the processed entry
        out.append(line)
    if removed:
        path.write_text("\n".join(out), encoding="utf-8")
    return removed


def extract_run_summary(career_ops_path: Path, log_path: Optional[str]) -> Optional[dict]:
    """Pull the runner's final result event from its log.

    The terminal `{"type":"result", ...}` object carries the agent's full
    markdown summary of every job parsed in the batch, plus run metadata.
    Returns {result, subtype, num_turns, duration_ms, cost_usd, is_error} or
    None if no result line is present (run still in flight or log missing).
    """
    if not log_path:
        return None
    full = career_ops_path / log_path
    try:
        with open(full, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 262144))  # 256 KB tail holds the whole summary
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "result":
            return {
                "result": evt.get("result", ""),
                "subtype": evt.get("subtype", ""),
                "num_turns": evt.get("num_turns"),
                "duration_ms": evt.get("duration_ms"),
                "cost_usd": evt.get("total_cost_usd"),
                "is_error": bool(evt.get("is_error")),
            }
    return None
