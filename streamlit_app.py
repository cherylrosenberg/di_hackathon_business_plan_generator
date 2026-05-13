# =====================================================================
# Streamlit UI for the AI Business Plan Generator
#
# Run from the project directory:
#   streamlit run streamlit_app.py
#   py -m streamlit run streamlit_app.py
#
# Requires GROQ_API_KEY in .env (same as main.py). Optional HF token for scoring.
# =====================================================================

from __future__ import annotations

import json
from pathlib import Path

import groq
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from business_info_schema import (
    SECTION_DESCRIPTIONS,
    business_info,
    generated_sections,
    is_interview_complete,
    is_plan_complete,
    required_fields,
    workflow_state,
    advance_workflow,
    get_next_field,
)
from pdf_converter import convert_to_pdf
from plan_generator import (
    finalize_plan_outputs,
    generate_and_store_section,
    load_business_info,
)
from question_asker import (
    ask_question,
    evaluate_answer,
    save_business_info,
    store_answer,
)

MD_PATH = Path("business_plan.md")
PDF_PATH = Path("business_plan.pdf")
JSON_INFO_PATH = Path("business_info.json")
SCORES_PATH = Path("plan_scores.json")

# Export UI: only show PDF download / scores viewer after explicit actions this session.
_SS_PDF_DL = "export_pdf_download_unlocked"
_SS_SCORES_VIEW = "export_scores_viewer_unlocked"


def _reset_export_session_flags() -> None:
    st.session_state[_SS_PDF_DL] = False
    st.session_state[_SS_SCORES_VIEW] = False


def _sidebar_step_indicator() -> None:
    phase = workflow_state.get("phase", "interviewing")
    steps = [
        ("1. Interview", phase == "interviewing"),
        ("2. Review", phase == "reviewing"),
        ("3. Generate", phase == "generating"),
        ("4. Done", phase == "done"),
    ]
    st.sidebar.header("Pipeline")
    for label, active in steps:
        st.sidebar.markdown(f"{'**' if active else ''}{label}{'**' if active else ''}")


def _load_interview_from_disk() -> bool:
    if not JSON_INFO_PATH.exists():
        return False
    data = json.loads(JSON_INFO_PATH.read_text(encoding="utf-8"))
    business_info.update(data)
    advance_workflow(workflow_state, business_info, generated_sections)
    return True


def _render_interview() -> None:
    st.header("Interview")
    if not is_interview_complete(business_info):
        stage = st.session_state.get("interview_stage", "bootstrap")

        if stage == "bootstrap":
            field = get_next_field(business_info)
            if field is None:
                st.warning("No next field; try loading saved interview from the sidebar.")
                return
            workflow_state["current_field"] = field
            issued_for = st.session_state.get("iv_issued_field")
            if issued_for != field:
                with st.spinner("Asking the assistant for a question…"):
                    question = ask_question(field)
                st.session_state["iv_main_question"] = question
                st.session_state["iv_issued_field"] = field
            st.session_state["iv_field"] = field
            st.session_state["iv_followup_text"] = ""
            st.session_state["interview_stage"] = "awaiting_answer"

        field = st.session_state["iv_field"]
        if st.session_state["interview_stage"] == "awaiting_followup":
            st.markdown(st.session_state.get("iv_followup_text", ""))
        else:
            st.markdown(st.session_state.get("iv_main_question", ""))

        with st.form("interview_answer_form", clear_on_submit=True):
            answer = st.text_area("Your answer", key="interview_ta", height=120)
            submitted = st.form_submit_button("Submit")

        if submitted:
            answer = (answer or "").strip()
            if not answer:
                st.error("Please enter an answer.")
                return

            if st.session_state["interview_stage"] == "awaiting_followup":
                store_answer(field, answer)
                st.session_state["interview_stage"] = "bootstrap"
                st.rerun()
                return

            main_q = st.session_state["iv_main_question"]
            sufficient, follow_up = evaluate_answer(field, main_q, answer)
            if not sufficient and follow_up:
                st.session_state["iv_followup_text"] = follow_up
                st.session_state["interview_stage"] = "awaiting_followup"
                st.rerun()
                return

            store_answer(field, answer)
            st.session_state["interview_stage"] = "bootstrap"
            st.rerun()
        return

    st.success("Interview fields are complete. Continue to **Review** in the sidebar step list — the app will switch to the review screen on the next action.")
    if workflow_state.get("phase") == "interviewing":
        advance_workflow(workflow_state, business_info, generated_sections)
        st.rerun()


def _render_review() -> None:
    st.header("Review answers")
    for f in required_fields:
        label = f.replace("_", " ").title()
        with st.expander(label):
            st.write(business_info.get(f, "") or "_(empty)_")

    st.subheader("Edit a field")
    edit_field = st.selectbox("Field", required_fields, format_func=lambda x: x.replace("_", " ").title())
    new_val = st.text_area("New value", value=business_info.get(edit_field, ""), height=100, key=f"edit_{edit_field}")
    if st.button("Save field"):
        business_info[edit_field] = (new_val or "").strip()
        save_business_info()
        st.success(f"Saved **{edit_field}**.")

    st.divider()


def _start_generation() -> None:
    if not load_business_info():
        st.error("No interview data. Complete the interview or load `business_info.json` from the sidebar.")
        return
    for key in SECTION_DESCRIPTIONS:
        generated_sections[key] = ""
    workflow_state["phase"] = "generating"
    workflow_state["completed"] = False
    st.session_state["gen_autorun"] = True
    st.session_state["gen_index"] = 0
    _reset_export_session_flags()
    st.rerun()


def _render_generation_autorun() -> None:
    st.header("Generating plan")
    keys = list(SECTION_DESCRIPTIONS.keys())
    n = len(keys)

    if not st.session_state.get("gen_autorun"):
        if is_plan_complete(generated_sections):
            finalize_plan_outputs()
            st.success("Plan finalized.")
            st.rerun()
            return
        st.warning("Generation is paused or was interrupted.")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Resume auto-generation"):
                st.session_state["gen_autorun"] = True
                for i, k in enumerate(keys):
                    if not (generated_sections.get(k) or "").strip():
                        st.session_state["gen_index"] = i
                        break
                st.rerun()
        with col_b:
            if st.button("Cancel and return to review"):
                workflow_state["phase"] = "reviewing"
                st.rerun()
        return

    idx = int(st.session_state.get("gen_index", 0))
    st.progress(min(idx / max(n, 1), 1.0))
    if idx < n:
        st.caption(f"Section {idx + 1} of {n}: `{keys[idx]}`")

    if idx >= n:
        st.session_state["gen_autorun"] = False
        finalize_plan_outputs()
        st.success("Saved **business_plan.md**.")
        st.rerun()
        return

    try:
        generate_and_store_section(keys[idx], sleep_after=idx < n - 1)
    except groq.AuthenticationError:
        st.session_state["gen_autorun"] = False
        st.error("Invalid **GROQ_API_KEY**. Fix `.env` and use **Resume**.")
        return
    except groq.APIConnectionError:
        st.session_state["gen_autorun"] = False
        st.error("Could not reach the Groq API. Check your connection, then **Resume**.")
        return

    st.session_state["gen_index"] = idx + 1
    st.rerun()


def _render_export() -> None:
    st.header("Export")
    if MD_PATH.exists():
        st.download_button(
            label="Download Markdown",
            data=MD_PATH.read_bytes(),
            file_name="business_plan.md",
            mime="text/markdown",
        )
    else:
        st.info("**business_plan.md** will appear here after generation completes.")

    st.caption(
        "**Convert to PDF** writes `business_plan.pdf` in this folder. "
        "**Download PDF** appears only after a successful convert in this session."
    )
    if st.button("Convert to PDF", type="primary"):
        if not MD_PATH.exists():
            st.error("No **business_plan.md** yet. Generate the plan first.")
        else:
            try:
                convert_to_pdf(str(MD_PATH), str(PDF_PATH))
                st.session_state[_SS_PDF_DL] = True
                st.success(f"Wrote **{PDF_PATH}**. Use **Download PDF** below.")
            except OSError as e:
                st.error(f"PDF conversion failed: {e}")

    if st.session_state.get(_SS_PDF_DL) and PDF_PATH.exists():
        st.download_button(
            label="Download PDF",
            data=PDF_PATH.read_bytes(),
            file_name="business_plan.pdf",
            mime="application/pdf",
        )
    elif PDF_PATH.exists() and not st.session_state.get(_SS_PDF_DL):
        st.caption("A PDF file exists on disk from an earlier run. Click **Convert to PDF** to refresh it and enable download.")

    st.caption(
        "**Run local scoring** evaluates the current Markdown and writes `plan_scores.json`. "
        "The JSON viewer appears only after a successful run in this session."
    )
    if st.button("Run local scoring"):
        if not MD_PATH.exists():
            st.error("Need **business_plan.md** before scoring.")
        else:
            try:
                from plan_gptscore import run_plan_scoring

                scores = run_plan_scoring(MD_PATH, SCORES_PATH)
            except ImportError as e:
                st.error(f"Scoring dependencies missing: {e}")
            except Exception as e:
                st.error(f"Scoring failed: {e}")
            else:
                err = scores.get("error")
                if err:
                    st.warning(str(err))
                else:
                    st.session_state[_SS_SCORES_VIEW] = True
                    st.success(f"Scores written to **{SCORES_PATH}**.")
                    st.write(scores)

    if st.session_state.get(_SS_SCORES_VIEW) and SCORES_PATH.exists():
        with st.expander("View plan_scores.json"):
            st.code(SCORES_PATH.read_text(encoding="utf-8"), language="json")
    elif SCORES_PATH.exists() and not st.session_state.get(_SS_SCORES_VIEW):
        st.caption(
            "A `plan_scores.json` from an earlier run is on disk. Click **Run local scoring** to refresh and unlock the viewer."
        )


def main() -> None:
    st.set_page_config(page_title="Business Plan Generator", layout="wide")
    st.title("AI Business Plan Generator")

    if _SS_PDF_DL not in st.session_state:
        _reset_export_session_flags()

    _sidebar_step_indicator()
    with st.sidebar:
        st.divider()
        if st.button("Load interview from disk"):
            if _load_interview_from_disk():
                st.session_state["interview_stage"] = "bootstrap"
                st.success(f"Loaded **{JSON_INFO_PATH}**.")
                st.rerun()
            else:
                st.error(f"**{JSON_INFO_PATH}** not found.")

    phase = workflow_state.get("phase", "interviewing")

    if phase == "interviewing":
        _render_interview()
        return

    if phase == "reviewing":
        _render_review()
        st.subheader("Plan generation")
        st.caption(
            "Groq generates one section at a time with a short pause between calls "
            "(rate limiting). This step may take a few minutes."
        )
        if st.button("Generate all sections"):
            _start_generation()
        return

    if phase == "generating":
        _render_generation_autorun()
        return

    if phase == "done":
        _render_review()
        st.subheader("Plan generation")
        if st.button("Regenerate full plan (clears all sections)"):
            _start_generation()
        st.divider()
        _render_export()
        return

    st.error(f"Unknown workflow phase: {phase!r}")


if __name__ == "__main__":
    main()
