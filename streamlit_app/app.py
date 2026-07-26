"""career-ops Streamlit dashboard.

Mirrors the Go/Bubble Tea TUI: Pipeline + Progress + Report viewer, with
write actions for status and notes. Run from the project root:

    streamlit run streamlit_app/app.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

# Repo root is one level up from this file; resolve it before importing siblings.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

import career_data as cd


# -- Logging ----------------------------------------------------------------
# Writes to stderr so messages show in the terminal that launched `./gui.sh`.
# Level controlled by env var: CAREER_OPS_LOG=DEBUG ./gui.sh
_LOG_LEVEL = os.environ.get("CAREER_OPS_LOG", "INFO").upper()
_root = logging.getLogger("career-ops")
log = logging.getLogger("career-ops.gui")
if not _root.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    _root.addHandler(_handler)
    _root.propagate = False
    _root.setLevel(_LOG_LEVEL)
    # Fires once per process (handler-absence is the once-flag).
    log.info("career-ops GUI booting (level=%s, root=%s)", _LOG_LEVEL, PROJECT_ROOT)

st.set_page_config(
    page_title="career-ops",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -- Data loading (cached, manual refresh resets) -----------------------------


@st.cache_data(show_spinner=False)
def load_apps(_mtime: float) -> list[cd.Application]:
    # Refresh hardlinks in streamlit_app/static/output so per-row download
    # URLs resolve under Streamlit's static server.
    t0 = time.time()
    cd.sync_static_output(PROJECT_ROOT)
    apps = cd.parse_applications(PROJECT_ROOT, enrich=True)
    log.info(
        "load_apps: parsed %d apps (mtime=%.0f, took %.0fms)",
        len(apps), _mtime, (time.time() - t0) * 1000,
    )
    return apps


def applications_mtime() -> float:
    path = cd.applications_path(PROJECT_ROOT)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def get_apps() -> list[cd.Application]:
    return load_apps(applications_mtime())


# -- Helpers ------------------------------------------------------------------

STATUS_COLORS = {
    "interview": "#a6e3a1",
    "offer": "#a6e3a1",
    "applied": "#89dceb",
    "responded": "#89b4fa",
    "evaluated": "#cdd6f4",
    "skip": "#f38ba8",
    "rejected": "#6c7086",
    "discarded": "#6c7086",
}


def score_color(score: float) -> str:
    if score >= 4.2:
        return "#a6e3a1"
    if score >= 3.8:
        return "#f9e2af"
    if score >= 3.0:
        return "#cdd6f4"
    if score > 0:
        return "#f38ba8"
    return "#6c7086"


def _static_url_for(file: cd.OutputFile | None) -> str | None:
    """Map an output file to a Streamlit static URL, or None if absent."""
    if file is None:
        return None
    try:
        rel = file.path.relative_to(PROJECT_ROOT / "output")
    except ValueError:
        return None
    # static/output is a symlink to ../output (set up in gui.sh); served at /app/static/.
    return f"app/static/output/{rel.as_posix()}"


def apps_to_dataframe(apps: list[cd.Application]) -> pd.DataFrame:
    rows = []
    for a in apps:
        artifacts = cd.newest_files_by_kind(PROJECT_ROOT, a)
        rows.append(
            {
                "#": a.number,
                "Date": a.date,
                "Company": a.company,
                "Role": a.role,
                "Score": a.score,
                "Status": cd.status_label(cd.normalize_status(a.status)),
                "CV": _static_url_for(artifacts["cv"]),
                "Cover Letter": _static_url_for(artifacts["cover_letter"]),
                "Comp": a.comp_estimate or "—",
                "Notes": a.notes,
                "URL": a.job_url,
                "Report": a.report_path,
                "_key": f"{a.number}-{a.report_number or a.company}",
            }
        )
    return pd.DataFrame(rows)


# -- Sidebar ------------------------------------------------------------------

st.sidebar.title("career-ops")
st.sidebar.caption(f"Repo: `{PROJECT_ROOT}`")

# Programmatic navigation (e.g. "View report →") must land BEFORE the radio is
# instantiated — Streamlit forbids writing a widget-keyed session value once its
# widget has run this cycle. Buttons set `_pending_view` + rerun; we apply it here.
if "_pending_view" in st.session_state:
    st.session_state["view"] = st.session_state.pop("_pending_view")

view = st.sidebar.radio(
    "View",
    ["Pipeline", "Progress", "Report"],
    label_visibility="collapsed",
    key="view",
)

if st.sidebar.button("Refresh data", width="stretch"):
    log.info("user clicked: Refresh data")
    st.cache_data.clear()
    st.rerun()


def render_cleanup_sidebar() -> None:
    """Sidebar control to delete throwaway local files (logs, stale state,
    orphaned static mirrors, *.bak backups). Never touches CVs, reports, or
    live output/ files."""
    items = cd.scan_local_artifacts(PROJECT_ROOT)
    title = f"🧹 Clean up ({len(items)})" if items else "🧹 Clean up"
    with st.sidebar.expander(title):
        if not items:
            st.caption("Nothing to clean up.")
            return
        by_cat: dict[str, list[int]] = {}
        for it in items:
            agg = by_cat.setdefault(it["category"], [0, 0])
            agg[0] += 1
            agg[1] += it["size"]
        for cat, (count, size) in sorted(by_cat.items()):
            plural = "s" if count != 1 else ""
            st.markdown(f"- **{cat}** — {count} file{plural} · {cd.human_bytes(size)}")
        total = sum(it["size"] for it in items)
        st.caption("Skips your CV, reports, and live `output/` files.")
        label = f"Delete {len(items)} file{'s' if len(items) != 1 else ''} · {cd.human_bytes(total)}"
        if st.button(label, type="secondary", width="stretch", key="cleanup_go"):
            deleted, freed = cd.delete_local_artifacts(items)
            log.warning("user cleanup: deleted=%d freed=%d bytes", deleted, freed)
            st.success(f"Deleted {deleted} file(s), freed {cd.human_bytes(freed)}.")
            st.cache_data.clear()
            time.sleep(0.6)
            st.rerun()


render_cleanup_sidebar()


def render_danger_zone_sidebar() -> None:
    """Sidebar control to permanently delete generated deliverables — tailored
    CVs, cover letters, and parsed-job reports — and optionally reset the
    applications tracker. Gated behind an explicit acknowledgement."""
    groups = cd.scan_generated_items(PROJECT_ROOT)
    total = sum(len(v) for v in groups.values())
    with st.sidebar.expander("⚠️ Delete generated items"):
        st.caption("Permanently deletes your generated deliverables. Cannot be undone.")
        picks: dict[str, bool] = {}
        for cat, items in groups.items():
            if not items:
                continue
            size = sum(i["size"] for i in items)
            picks[cat] = st.checkbox(
                f"{cat} — {len(items)} · {cd.human_bytes(size)}",
                value=True,
                key=f"del_{cat}",
            )
        reset_tr = st.checkbox(
            "Reset applications tracker (all rows)", value=True, key="del_tracker"
        )
        reset_pipe = st.checkbox(
            "Clear pipeline processed-history",
            value=False,
            key="del_pipeline_hist",
            help="Empties the ## Processed section of data/pipeline.md so those "
            "URLs can be re-added and re-run. Keeps Pending and the Pendientes "
            "archive. Enable this for a true fresh start.",
        )
        selected = [i for cat, on in picks.items() if on for i in groups[cat]]
        if total == 0 and not reset_tr and not reset_pipe:
            st.caption("Nothing to delete.")
            return
        if not selected and not reset_tr and not reset_pipe:
            st.caption("Select at least one category.")
            return
        ack = st.checkbox(
            "I understand this permanently deletes the items above.", key="del_ack"
        )
        n = len(selected)
        freed = sum(i["size"] for i in selected)
        label = f"Delete {n} file{'s' if n != 1 else ''} · {cd.human_bytes(freed)}"
        extras = []
        if reset_tr:
            extras.append("reset tracker")
        if reset_pipe:
            extras.append("clear history")
        if extras:
            label += " + " + " + ".join(extras)
        if st.button(label, type="primary", disabled=not ack, width="stretch", key="del_go"):
            deleted, bytes_freed = cd.delete_local_artifacts(selected)
            msg = f"Deleted {deleted} file(s), freed {cd.human_bytes(bytes_freed)}."
            if reset_tr:
                removed = cd.reset_tracker(PROJECT_ROOT)
                msg += f" Tracker reset ({removed} row{'s' if removed != 1 else ''} removed)."
            if reset_pipe:
                cleared = cd.reset_pipeline_processed(PROJECT_ROOT)
                msg += f" Pipeline history cleared ({cleared} entr{'ies' if cleared != 1 else 'y'} removed)."
            cd.sync_static_output(PROJECT_ROOT)  # prune now-orphaned mirror links
            log.warning(
                "user delete-generated: files=%d freed=%d tracker_reset=%s pipeline_hist=%s",
                deleted, bytes_freed, reset_tr, reset_pipe,
            )
            st.success(msg)
            st.cache_data.clear()
            time.sleep(0.8)
            st.rerun()


render_danger_zone_sidebar()

st.sidebar.divider()


# -- Pipeline view ------------------------------------------------------------


INBOX_PLACEHOLDER = """- [ ] #3422 | https://www.linkedin.com/jobs/view/4414820579/ | Privatize | Senior Fullstack Developer
- [ ] https://boards.greenhouse.io/foo/jobs/123 | Acme | Senior Backend
https://www.linkedin.com/jobs/view/8888888888/"""


KIND_ICON = {"cv": "📄", "cover_letter": "✉️", "other": "📎"}
KIND_LABEL = {"cv": "CV", "cover_letter": "Cover letter", "other": "File"}


def render_report_link(app: cd.Application, row_key: str) -> None:
    """Button that switches to the Report tab with this report pre-selected."""
    label = f"📋 View report ({app.report_number or '—'}) →"
    if st.button(label, key=f"goto_report_{row_key}"):
        log.info("navigate: View report → Report tab (path=%s)", app.report_path)
        st.session_state["_pending_view"] = "Report"
        st.session_state["preselect_report_path"] = app.report_path
        st.rerun()


def render_downloads(app: cd.Application, row_key: str) -> None:
    """Render download buttons for any CV / cover letter found in `output/`."""
    files = cd.find_application_files(PROJECT_ROOT, app)
    if not files:
        return
    st.markdown("**Downloads**")
    for i, f in enumerate(files):
        try:
            data = f.path.read_bytes()
        except OSError as exc:
            st.warning(f"Could not read {f.path.name}: {exc}")
            continue
        kb = max(1, f.size_bytes // 1024)
        label = f"{KIND_ICON[f.kind]} {KIND_LABEL[f.kind]} — {f.path.name} ({kb} KB)"
        st.download_button(
            label=label,
            data=data,
            file_name=f.path.name,
            mime=f.mime,
            key=f"dl_{row_key}_{i}",
        )


ANSWER_TASK = "answers"


def render_application_questions(app: cd.Application, row_key: str) -> None:
    """Panel: enter an application's custom questions and have Claude draft
    first-person answers grounded in the user's profile + this role's report.
    Spawns a detached `claude -p` task (separate from the pipeline runner)."""
    task = cd.get_task_run(PROJECT_ROOT, ANSWER_TASK)
    running = bool(task and task.get("alive"))
    this_row = task.get("row_key") == row_key if task else False

    with st.expander("✍️ Application questions → draft answers from my profile"):
        st.caption(
            "Paste the questions this application asks (one per line). Claude "
            "drafts first-person answers grounded only in your CV, profile, and "
            "this role's report — then you review and edit before submitting."
        )
        questions = st.text_area(
            "Application questions",
            key=f"appq_{row_key}",
            height=160,
            placeholder=(
                "Why this company, and why now?\n"
                "What's the most impactful thing you've built? "
                "What was your specific contribution?\n"
                "How did you know it worked? What did success look like?"
            ),
            label_visibility="collapsed",
        )

        if running and this_row:
            age = _humanize_age(task["started_at"])
            st.info(f"Drafting answers… PID `{task['pid']}` · started {age}.")
            tail = cd.tail_pipeline_log(PROJECT_ROOT, task["log_path"], max_lines=30)
            st.code(tail or "(no output yet)", language="text")
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("⟳ Refresh", key=f"appq_refresh_{row_key}"):
                st.rerun()
            if c2.button("🛑 Stop", key=f"appq_stop_{row_key}"):
                cd.stop_task_run(PROJECT_ROOT, ANSWER_TASK)
                time.sleep(0.5)
                st.rerun()
            time.sleep(3)  # poll so the panel clears itself when the draft lands
            st.rerun()
            return

        if running and not this_row:
            st.warning(
                f"A draft is already running for another job "
                f"({task.get('company', '?')}). Wait for it to finish."
            )
        else:
            disabled = not questions.strip()
            if st.button(
                "✨ Draft answers from my profile",
                type="primary",
                disabled=disabled,
                key=f"appq_go_{row_key}",
            ):
                answers_path = cd.answers_output_path(app, date.today().isoformat())
                cmd = cd.build_answer_cmd(
                    PROJECT_ROOT,
                    company=app.company,
                    role=app.role,
                    report_path=app.report_path or "",
                    questions=questions,
                    answers_path=answers_path,
                )
                try:
                    cd.start_task_run(
                        PROJECT_ROOT,
                        ANSWER_TASK,
                        cmd,
                        meta={
                            "row_key": row_key,
                            "answers_path": answers_path,
                            "company": app.company,
                        },
                    )
                    log.warning(
                        "user draft-answers: company=%s path=%s", app.company, answers_path
                    )
                    st.success(
                        "Started drafting (headless, skips permission prompts, "
                        "costs API credits)."
                    )
                    time.sleep(0.6)
                    st.rerun()
                except FileNotFoundError:
                    st.error("`claude` not found on PATH.")
                except RuntimeError as exc:
                    st.error(str(exc))

        # Surface the most recent drafted answers for this job, if any.
        answers_file = cd.find_answers_file(PROJECT_ROOT, app)
        if answers_file and answers_file.exists():
            try:
                md = answers_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                md = ""
            if md.strip():
                rel = answers_file.relative_to(PROJECT_ROOT)
                st.markdown(f"**Drafted answers** (`{rel}`)")
                st.download_button(
                    "⬇ Download answers",
                    data=md.encode("utf-8"),
                    file_name=answers_file.name,
                    mime="text/markdown",
                    key=f"appq_dl_{row_key}",
                )
                with st.expander("Show drafted answers", expanded=True):
                    st.markdown(md)


def _humanize_age(started_at: float) -> str:
    elapsed = max(0.0, time.time() - started_at)
    if elapsed < 60:
        return f"{int(elapsed)}s ago"
    if elapsed < 3600:
        return f"{int(elapsed // 60)}m {int(elapsed % 60)}s ago"
    return f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m ago"


def render_pipeline_runner() -> None:
    """Run / stop / monitor the `claude -p /career-ops pipeline` subprocess."""
    section_counts = cd.count_pipeline_pending_by_section(PROJECT_ROOT)
    pending = sum(section_counts.values())
    state = cd.get_pipeline_run(PROJECT_ROOT)
    running = bool(state and state.get("alive"))

    # Detect a batch that just finished (was running on a prior render, now not)
    # so the router can pop its summary dialog. We only watch runs the GUI saw
    # go live, so a run that finished before this session started won't surprise
    # the user — they can still open it via the manual button below.
    watching = st.session_state.get("_pipeline_watch_pid")
    if running and state:
        st.session_state["_pipeline_watch_pid"] = state["pid"]
    elif watching is not None:
        st.session_state.pop("_pipeline_watch_pid", None)
        if state and state.get("pid") == watching:
            st.session_state["_show_summary_log"] = state.get("log_path")

    header = "⚙️ Pipeline runner"
    if running:
        header += " — 🟢 running"
    elif pending > 0:
        header += f" — {pending} pending"

    with st.expander(header, expanded=running or pending > 0):
        if running:
            age = _humanize_age(state["started_at"])
            st.warning(
                f"Pipeline is running. PID `{state['pid']}` · started {age} · "
                f"processing {state.get('pending_count', '?')} URL(s). "
                "Closing the GUI will NOT stop it."
            )
            tail = cd.tail_pipeline_log(PROJECT_ROOT, state["log_path"], max_lines=40)
            st.markdown("**Log tail** (`" + state["log_path"] + "`)")
            st.code(tail or "(no output yet)", language="text")
            cols = st.columns([1, 1, 4])
            if cols[0].button("⟳ Refresh"):
                st.rerun()
            if cols[1].button("🛑 Stop", type="secondary"):
                log.warning("user clicked: Stop pipeline (pid=%s)", state.get("pid"))
                if cd.stop_pipeline_run(PROJECT_ROOT):
                    log.info("pipeline stop: SIGTERM dispatched")
                    st.success("SIGTERM sent. The runner will exit shortly.")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    log.error("pipeline stop: failed to signal pid=%s", state.get("pid"))
                    st.error("Couldn't signal the process.")
            # Streamlit won't re-run on its own while the detached subprocess
            # works, so this banner would sit stale until the user clicked
            # Refresh — the run could finish minutes earlier. Poll on a short
            # interval so the UI clears itself the moment the run completes.
            st.caption("Auto-refreshing every 3 s while the run is active…")
            time.sleep(3)
            st.rerun()
            return

        # Idle state — show pending count, last log, and offer to start a new run.
        if state:
            st.caption(
                f"Last run: PID `{state['pid']}` finished. "
                f"Log: `{state['log_path']}`"
            )
            if st.button("📋 Show run summary", key="show_last_summary"):
                st.session_state["_show_summary_log"] = state["log_path"]
                st.rerun()
            tail = cd.tail_pipeline_log(PROJECT_ROOT, state["log_path"], max_lines=20)
            if tail:
                with st.expander("Show last log tail", expanded=False):
                    st.code(tail, language="text")

        if pending == 0:
            st.info("No pending URLs in `data/pipeline.md`. Add some via the inbox above.")
            return

        # Surface per-section breakdown — the user may have a `## Pendientes`
        # block (Spanish) with hundreds of URLs they've forgotten about.
        if len(section_counts) > 1 or "## Pendientes" in section_counts:
            for section, n in section_counts.items():
                st.markdown(f"- `{section}` → **{n}**")
        else:
            st.markdown(f"**{pending}** URL{'s' if pending != 1 else ''} pending.")

        st.caption(
            "Each URL takes 10–30 min and consumes API credits. Subprocess "
            "detaches from the GUI — closing this tab won't stop it. Runs with "
            "`--dangerously-skip-permissions` (no permission prompts). The prompt "
            "is directive (no questions), so Claude proceeds with full evaluation "
            "of every URL in `## Pending`."
        )

        confirm_key = "pipeline_confirming"
        if not st.session_state.get(confirm_key):
            if st.button(
                f"▶ Run pipeline on {pending} URL{'s' if pending != 1 else ''}",
                type="primary",
                key="pipeline_run_btn",
            ):
                st.session_state[confirm_key] = True
                st.rerun()
            return

        # Confirmation step
        st.error("**Confirm — this will spawn a subprocess that costs money.**")
        st.markdown(
            f"- URLs in scope: **{pending}** across {len(section_counts)} section(s)\n"
            f"- Permission prompts: **skipped** (headless mode)\n"
            f"- Detached: closing the GUI won't stop it\n"
            f"- No budget cap"
        )
        with st.expander("Show full command and prompt"):
            st.code(" \\\n  ".join(cd.build_pipeline_cmd()), language="bash")
        ack = st.checkbox(
            "I've reviewed the pending URLs and accept the API spend.",
            key="pipeline_ack",
        )
        cols = st.columns([1, 1, 4])
        if cols[0].button("Cancel", key="pipeline_cancel"):
            st.session_state.pop(confirm_key, None)
            st.session_state.pop("pipeline_ack", None)
            st.rerun()
        if cols[1].button("Yes, run", type="primary", disabled=not ack, key="pipeline_go"):
            log.warning("user confirmed: Run pipeline (pending=%d)", pending)
            st.session_state.pop(confirm_key, None)
            st.session_state.pop("pipeline_ack", None)
            try:
                new_state = cd.start_pipeline_run(PROJECT_ROOT, cmd=cd.build_pipeline_cmd())
                st.success(f"Started — PID `{new_state['pid']}`.")
                time.sleep(0.5)
                st.rerun()
            except FileNotFoundError:
                log.error("pipeline start: `claude` binary not found on PATH")
                st.error(
                    "`claude` not found on PATH. Install Claude Code CLI "
                    "or edit `DEFAULT_PIPELINE_CMD`."
                )
            except RuntimeError as exc:
                log.error("pipeline start refused: %s", exc)
                st.error(str(exc))


def render_inbox_form() -> None:
    """Textarea that parses pasted lines and appends them to data/pipeline.md."""
    pipeline_file = cd.pipeline_path(PROJECT_ROOT)
    with st.expander("➕ Add URLs to pipeline inbox", expanded=False):
        st.caption(
            f"Lines are parsed and appended to `{pipeline_file.relative_to(PROJECT_ROOT)}` "
            "under `## Pending`. Accepted shapes: `- [ ] #ID | URL | Company | Role | note`, "
            "`URL | Company | Role`, or a bare URL. Duplicates are skipped."
        )
        text = st.text_area(
            "Paste lines",
            height=160,
            placeholder=INBOX_PLACEHOLDER,
            key="inbox_text",
            label_visibility="collapsed",
        )
        action_cols = st.columns([1, 1, 4])
        preview_clicked = action_cols[0].button("Preview", key="inbox_preview")
        add_clicked = action_cols[1].button("Add to inbox", type="primary", key="inbox_add")

        if preview_clicked or add_clicked:
            entries, errors = cd.parse_pipeline_input(text or "")
            if errors:
                with st.container():
                    for err in errors:
                        st.warning(err)
            if not entries:
                st.info("Nothing to add — paste at least one URL.")
                return
            with st.container():
                st.markdown("**Parsed entries:**")
                st.code("\n".join(e.to_line() for e in entries), language="markdown")
            if add_clicked:
                added, skipped = cd.append_to_pipeline(PROJECT_ROOT, entries)
                log.info(
                    "inbox add: parsed=%d errors=%d added=%d skipped=%d",
                    len(entries), len(errors), added, len(skipped),
                )
                if added:
                    st.success(
                        f"Added **{added}** to inbox. "
                        f"Next: run `/career-ops pipeline` in your CLI to process them."
                    )
                if skipped:
                    st.info(
                        f"Skipped {len(skipped)} already-present URL"
                        f"{'s' if len(skipped) != 1 else ''}."
                    )
                if added:
                    st.rerun()


def render_pipeline() -> None:
    apps = get_apps()
    metrics = cd.compute_metrics(apps)
    pending = cd.count_pipeline_pending(PROJECT_ROOT)

    st.markdown("### Career Pipeline")
    cols = st.columns([2, 1, 1, 1, 1, 1])
    cols[0].metric("Total offers", metrics.total)
    cols[1].metric("Avg score", f"{metrics.avg_score:.2f}")
    cols[2].metric("Top score", f"{metrics.top_score:.1f}")
    cols[3].metric("With PDF", metrics.with_pdf)
    cols[4].metric("Actionable", metrics.actionable)
    cols[5].metric("Inbox", pending, help="Pending URLs in data/pipeline.md")

    render_inbox_form()
    render_pipeline_runner()

    # Tab + sort + search controls
    tab_keys = [key for key, _ in cd.FILTER_TABS]
    counts = {
        key: len(cd.filter_apps(apps, key))
        for key, _ in cd.FILTER_TABS
    }
    tab_display = [f"{label} ({counts[k]})" for k, label in cd.FILTER_TABS]

    selected_tab_display = st.radio(
        "Filter",
        tab_display,
        horizontal=True,
        label_visibility="collapsed",
    )
    selected_tab = tab_keys[tab_display.index(selected_tab_display)]

    ctrl_cols = st.columns([2, 2, 1])
    query = ctrl_cols[0].text_input(
        "Search (company / role / notes)", value="", placeholder="e.g. fullstack, berlin, python"
    )
    sort_mode = ctrl_cols[1].selectbox(
        "Sort by", ["score", "date", "company", "status"], index=0
    )
    show_skip_first = ctrl_cols[2].toggle("Group by status", value=False)

    filtered = cd.filter_apps(apps, selected_tab, query)
    filtered = cd.sort_apps(filtered, sort_mode)
    if show_skip_first:
        filtered.sort(key=lambda a: cd.status_priority(a.status))

    if not filtered:
        st.info("No offers match this filter.")
        return

    df = apps_to_dataframe(filtered)
    display_df = df.drop(columns=["_key", "Report"])

    # Build a stable identifier list to map selection back to Application
    keys = df["_key"].tolist()
    apps_by_key = {f"{a.number}-{a.report_number or a.company}": a for a in filtered}

    st.caption(f"Showing **{len(filtered)}** of {len(apps)} — click a row to see actions.")

    event = st.dataframe(
        display_df,
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Date": st.column_config.TextColumn(width="small"),
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0.0, max_value=5.0, format="%.1f"
            ),
            "CV": st.column_config.LinkColumn(
                "CV", display_text="⬇", width="small",
                help="Download the most recent CV for this row",
            ),
            "Cover Letter": st.column_config.LinkColumn(
                "Cover", display_text="⬇", width="small",
                help="Download the most recent cover letter for this row",
            ),
            "URL": st.column_config.LinkColumn("Job", display_text="open", width="small"),
        },
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        height=min(600, 80 + 35 * len(filtered)),
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if not selected_rows:
        st.info("Select a row to edit status, notes, or open the report.")
        return

    row_idx = selected_rows[0]
    key = keys[row_idx]
    app = apps_by_key.get(key)
    if not app:
        return

    st.divider()
    detail_cols = st.columns([3, 2])
    with detail_cols[0]:
        st.markdown(f"#### {app.company} — {app.role}")
        meta_bits = []
        if app.date:
            meta_bits.append(f"📅 {app.date}")
        if app.score:
            meta_bits.append(f"⭐ {app.score:.1f}/5")
        if app.archetype:
            meta_bits.append(f"🎯 {app.archetype}")
        if app.remote:
            meta_bits.append(f"🌍 {app.remote}")
        if app.comp_estimate:
            meta_bits.append(f"💰 {app.comp_estimate}")
        if meta_bits:
            st.markdown(" · ".join(meta_bits))
        if app.tldr:
            st.markdown(f"> {app.tldr}")
        if app.notes:
            st.caption(f"Notes: {app.notes}")
        if app.job_url:
            st.markdown(f"[Open job posting →]({app.job_url})")
        if app.report_path:
            render_report_link(app, key)

        render_downloads(app, key)

    with detail_cols[1]:
        st.markdown("##### Update status")
        norm = cd.normalize_status(app.status)
        current_label = cd.status_label(norm)
        try:
            default_idx = cd.STATUS_OPTIONS.index(current_label)
        except ValueError:
            default_idx = 0
        new_status = st.selectbox(
            "Status",
            cd.STATUS_OPTIONS,
            index=default_idx,
            key=f"status_{key}",
        )
        new_notes = st.text_area(
            "Notes",
            value=app.notes,
            key=f"notes_{key}",
            height=120,
        )

        save_col, ghost = st.columns([1, 1])
        if save_col.button("Save changes", type="primary", key=f"save_{key}"):
            changes = {}
            if new_status != current_label:
                changes["new_status"] = new_status
            if new_notes != app.notes:
                changes["new_notes"] = new_notes
            if not changes:
                log.debug("save clicked but no changes: #%d %s", app.number, app.company)
                st.info("Nothing to save.")
            else:
                ok = cd.update_application(PROJECT_ROOT, app, **changes)
                log.info(
                    "save app #%d %s: status=%s→%s notes_changed=%s ok=%s",
                    app.number, app.company,
                    current_label, new_status,
                    "new_notes" in changes, ok,
                )
                if ok:
                    st.success(f"Updated {app.company} → {new_status}")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Could not locate row in applications.md")

        ghost.markdown("&nbsp;", unsafe_allow_html=True)

    render_application_questions(app, key)


# -- Progress view ------------------------------------------------------------


def render_progress() -> None:
    apps = get_apps()
    pm = cd.compute_progress(apps)

    st.markdown("### Search Progress")
    head = st.columns(4)
    head[0].metric("Evaluated", pm.funnel_stages[0].count if pm.funnel_stages else 0)
    head[1].metric("Avg score", f"{pm.avg_score:.2f}")
    head[2].metric("Top score", f"{pm.top_score:.1f}")
    head[3].metric("Active apps", pm.active_apps)

    st.divider()
    st.markdown("#### Pipeline Funnel")
    funnel_df = pd.DataFrame(
        [
            {"Stage": s.label, "Count": s.count, "Pct": s.pct}
            for s in pm.funnel_stages
        ]
    )
    if not funnel_df.empty:
        st.bar_chart(funnel_df.set_index("Stage")["Count"], horizontal=True)
        with st.expander("Funnel details"):
            st.dataframe(funnel_df, hide_index=True, width="stretch")
    else:
        st.info("No data.")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("#### Score Distribution")
        score_df = pd.DataFrame(
            [{"Range": b.label, "Count": b.count} for b in pm.score_buckets]
        )
        st.bar_chart(score_df.set_index("Range")["Count"])

    with cols[1]:
        st.markdown("#### Weekly Activity (last 8 wks)")
        if pm.weekly_activity:
            wk = pd.DataFrame(
                [{"Week": w.week, "Count": w.count} for w in pm.weekly_activity]
            )
            st.bar_chart(wk.set_index("Week")["Count"])
        else:
            st.info("No dated entries yet.")

    st.divider()
    st.markdown("#### Conversion Rates")
    rate_cols = st.columns(3)
    rate_cols[0].metric("Response rate", f"{pm.response_rate:.1f}%")
    rate_cols[1].metric("Interview rate", f"{pm.interview_rate:.1f}%")
    rate_cols[2].metric("Offer rate", f"{pm.offer_rate:.1f}%")

    if pm.funnel_stages and pm.funnel_stages[1].count == 0:
        st.caption(
            "No applications submitted yet — rates will populate once you mark offers as Applied."
        )


# -- Report viewer ------------------------------------------------------------


def render_report() -> None:
    apps = get_apps()
    with_report = cd.sort_apps([a for a in apps if a.report_path], "score")
    if not with_report:
        st.info("No reports found in `reports/`.")
        return

    labels = [
        f"{cd.status_label(cd.normalize_status(a.status))} · {a.score:.1f} · {a.company} — {a.role}"
        for a in with_report
    ]

    # Honor a one-shot preselect coming from the Pipeline view's "View report" button.
    preselect_path = st.session_state.pop("preselect_report_path", None)
    default_idx = 0
    if preselect_path:
        for i, a in enumerate(with_report):
            if a.report_path == preselect_path:
                default_idx = i
                break

    label = st.selectbox("Pick a report", labels, index=default_idx, key="report_pick")
    app = with_report[labels.index(label)]

    head = st.columns([3, 1])
    head[0].markdown(f"### {app.company} — {app.role}")
    if app.job_url:
        head[1].markdown(f"[Open posting →]({app.job_url})")

    md = cd.load_report_markdown(PROJECT_ROOT, app.report_path)
    if not md:
        st.warning(f"Could not read `{app.report_path}`.")
        return

    st.download_button(
        label=f"⬇ Download {Path(app.report_path).name}",
        data=md.encode("utf-8"),
        file_name=Path(app.report_path).name,
        mime="text/markdown",
        key="dl_report_view",
    )
    st.markdown(md)


# -- Router -------------------------------------------------------------------

if view == "Pipeline":
    render_pipeline()
elif view == "Progress":
    render_progress()
else:
    render_report()


# -- Batch-complete summary ---------------------------------------------------


@st.dialog("📋 Batch complete — run summary", width="large")
def show_run_summary_dialog(summary: dict) -> None:
    """Modal that surfaces the agent's summary of every job parsed in a run."""
    meta: list[str] = []
    if summary.get("duration_ms"):
        meta.append(f"{summary['duration_ms'] / 1000:.0f}s")
    if summary.get("num_turns") is not None:
        meta.append(f"{summary['num_turns']} turns")
    if summary.get("cost_usd"):
        meta.append(f"${summary['cost_usd']:.2f}")
    if summary.get("is_error"):
        meta.append("⚠️ ended with error")
    if meta:
        st.caption(" · ".join(meta))
    st.markdown(
        summary.get("result") or "_The run finished but left no summary text in its log._"
    )
    if st.button("Close", key="close_run_summary", type="primary"):
        st.session_state.pop("_show_summary_log", None)
        st.rerun()


_summary_log = st.session_state.get("_show_summary_log")
if _summary_log:
    _summary = cd.extract_run_summary(PROJECT_ROOT, _summary_log)
    if _summary:
        show_run_summary_dialog(_summary)
    else:
        st.session_state.pop("_show_summary_log", None)
