# =====================================================================
# Business Plan Generator — Phase 4
#
# Run after question_asker.py has completed the interview.
# Can be run standalone (loads business_info.json from disk) or called
# from main.py after run_interview() populates business_info in memory.
# =====================================================================

from dotenv import load_dotenv

load_dotenv()

import json
import sys
import time
from pathlib import Path

import groq
from groq import Groq

from business_info_schema import (
    SECTION_DESCRIPTIONS,
    business_info,
    generated_sections,
    workflow_state,
    advance_workflow,
    is_plan_complete,
)

MODEL = "llama-3.1-8b-instant"
TEMPLATE_PATH = Path("business_plan_template.md")
JSON_INPUT_PATH = Path("business_info.json")

SYSTEM_PROMPT = (
    "You are a professional business plan writer. You write clear, concise, and "
    "compelling business plan sections. You are given structured business information "
    "and must write exactly one section. Do not include the section heading — only "
    "the body prose. Do not reference other sections. Do not add commentary or "
    "preamble. Output only the section content."
)

client = Groq()


# =====================================================================
# Public API
# =====================================================================

def generate_section(section_key: str) -> str:
    """Call Groq to generate prose for a single business plan section."""
    section_name = section_key.replace("_", " ").title()
    section_desc = SECTION_DESCRIPTIONS[section_key]

    user_message = (
        f"Write the {section_name} section of a business plan using the "
        f"following business information:\n\n"
        f"Business Name: {business_info['business_name']}\n"
        f"Business Idea: {business_info['business_idea']}\n"
        f"Problem Solved: {business_info['problem_solved']}\n"
        f"Target Market: {business_info['target_market']}\n"
        f"Revenue Model: {business_info['revenue_model']}\n"
        f"Competitors: {business_info['competitors']}\n"
        f"Marketing Strategy: {business_info['marketing_strategy']}\n"
        f"Startup Budget: {business_info['startup_budget']}\n"
        f"Unique Value Proposition: {business_info['unique_value_proposition']}\n\n"
        f"Section to write: {section_name}\n"
        f"Section description: {section_desc}\n\n"
        f"Write only the body of this section. No heading. No preamble."
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()

    except groq.AuthenticationError:
        print("Invalid GROQ_API_KEY. Check your .env file.")
        sys.exit(1)
    except groq.APIConnectionError:
        print("Could not reach Groq API. Check your internet connection.")
        sys.exit(1)
    except Exception as e:
        print(f"  Error generating {section_key}: {e} — skipping.")
        return ""


def generate_plan() -> None:
    """Generate all business plan sections one at a time."""
    _load_business_info()

    workflow_state["phase"] = "generating"
    print("\n=== Generating Business Plan ===\n")

    for section_key in SECTION_DESCRIPTIONS:
        section_name = section_key.replace("_", " ").title()
        print(f"  Generating: {section_name}...", end=" ", flush=True)

        prose = generate_section(section_key)

        if prose:
            generated_sections[section_key] = prose
            print("Done")
        else:
            generated_sections[section_key] = (
                f"*[This section could not be generated automatically. "
                f"Please write the {section_name} manually.]*"
            )
            print("Failed — placeholder inserted")

        time.sleep(5)

    advance_workflow(workflow_state, business_info, generated_sections)
    print()
    render_and_save()


def render_and_save(output_path: str = "business_plan.md") -> None:
    """Fill the template with generated content and save to disk."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    template = template.replace("{business_name}", business_info["business_name"])
    for section_key, prose in generated_sections.items():
        template = template.replace(f"{{{section_key}}}", prose)

    Path(output_path).write_text(template, encoding="utf-8")
    print(f"Business plan saved to {output_path}")


# =====================================================================
# Internal helpers
# =====================================================================

def _load_business_info() -> None:
    """Load interview answers from JSON if business_info is empty.

    Allows plan_generator.py to run standalone after question_asker.py
    has saved business_info.json. When called from main.py in the same
    process, business_info is already populated and this is a no-op.
    """
    if all(v == "" for v in business_info.values()):
        if not JSON_INPUT_PATH.exists():
            print("No interview data found. Run question_asker.py first.")
            sys.exit(1)

        data = json.loads(JSON_INPUT_PATH.read_text(encoding="utf-8"))
        business_info.update(data)
        print(f"Loaded interview data from {JSON_INPUT_PATH}")


# =====================================================================
# Standalone entry point
# =====================================================================

if __name__ == "__main__":
    generate_plan()
