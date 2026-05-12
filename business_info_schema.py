"""
Central state schema for the AI Business Plan Generator.

Three distinct data layers, each with a clear owner:

  business_info        – RAW user input collected by the Question-Asker.
  generated_sections   – GENERATED prose written by the Plan Generator LLM.
  workflow_state       – Workflow control state (current field, phase, etc.).

Design rule (MVP):
  Each user answer maps to exactly ONE field. Do NOT attempt to extract
  multiple fields from a single response. This keeps the interview loop
  simple and the codebase hackathon-friendly. Multi-field extraction can
  be added as a future improvement.
"""

# =====================================================================
# 1. FIELD DESCRIPTIONS  (single source of truth for field metadata)
# =====================================================================

FIELD_DESCRIPTIONS: dict[str, str] = {
    "business_name": "The official or working name of the business or startup.",
    "business_idea": "A concise description of what the business does (1-3 sentences).",
    "problem_solved": "The specific pain point or gap in the market the business addresses.",
    "target_market": "The ideal customer profile — demographics, geography, niche, or industry.",
    "revenue_model": "How the business will make money (e.g. subscriptions, one-time sales, ads).",
    "competitors": "Key existing competitors or alternatives the target market uses today.",
    "marketing_strategy": "High-level plan for acquiring and retaining customers.",
    "startup_budget": "Estimated initial budget or funding needed to launch.",
    "unique_value_proposition": "What makes this business different and hard to replicate.",
}

# =====================================================================
# 2. COLLECTED INPUTS  (populated by the Question-Asker workflow)
# =====================================================================

business_info: dict[str, str] = {field: "" for field in FIELD_DESCRIPTIONS}

required_fields: list[str] = list(FIELD_DESCRIPTIONS.keys())

# =====================================================================
# 3. GENERATED OUTPUTS  (populated by the Plan Generator workflow)
#    Each key maps to a section in business_plan_template.md.
#    The generator fills these; the template uses the tokens to render.
# =====================================================================

SECTION_DESCRIPTIONS: dict[str, str] = {
    "executive_summary": "High-level snapshot: what the business does, who it serves, and why it will succeed.",
    "problem_statement": "The pain point or market gap, its significance, and consequences if unsolved.",
    "solution_overview": "How the product or service directly solves the stated problem.",
    "unique_value_proposition": "What makes this business different and hard to replicate.",
    "target_market": "Ideal customer profile with demographics, geography, and market size.",
    "competitive_analysis": "Competitor landscape, strengths/weaknesses, and differentiation.",
    "revenue_model": "Revenue streams, pricing strategy, and monetisation phases.",
    "marketing_strategy": "Customer acquisition and retention plan across channels.",
    "financial_overview": "Startup budget, projected costs, and path to break-even.",
    "conclusion": "Opportunity summary, restated value proposition, and next steps.",
}

generated_sections: dict[str, str] = {section: "" for section in SECTION_DESCRIPTIONS}

# =====================================================================
# 4. WORKFLOW STATE  (tracks where the application is in its lifecycle)
# =====================================================================

workflow_state: dict = {
    "current_field": None,      # field key currently being asked about
    "phase": "interviewing",    # "interviewing" | "reviewing" | "generating" | "done"
    "completed": False,         # True once the final plan has been written
}

# =====================================================================
# 5. UTILITY HELPERS
# =====================================================================

def get_missing_fields(info: dict[str, str]) -> list[str]:
    """Return the list of required fields that are still empty."""
    return [f for f in required_fields if not info.get(f, "").strip()]


def get_next_field(info: dict[str, str]) -> str | None:
    """Return the next single field to ask about, or None if complete.

    MVP approach: always ask about exactly one field at a time.
    """
    missing = get_missing_fields(info)
    return missing[0] if missing else None


def get_field_prompt_context(field: str) -> str:
    """Return a human-readable description for a field.

    Useful for injecting into an LLM prompt so the model knows what
    information it should collect next.
    """
    return FIELD_DESCRIPTIONS.get(field, field)


def is_interview_complete(info: dict[str, str]) -> bool:
    """True when every required field has been filled in."""
    return len(get_missing_fields(info)) == 0


def is_plan_complete(sections: dict[str, str]) -> bool:
    """True when every generated section has content."""
    return all(sections.get(s, "").strip() for s in SECTION_DESCRIPTIONS)


def advance_workflow(state: dict, info: dict[str, str], sections: dict[str, str]) -> None:
    """Move workflow_state to the next phase based on current data.

    Call after every meaningful state change (field stored, section generated).
    """
    if state["phase"] == "interviewing" and is_interview_complete(info):
        state["phase"] = "reviewing"
        state["current_field"] = None
    elif state["phase"] == "generating" and is_plan_complete(sections):
        state["phase"] = "done"
        state["completed"] = True
