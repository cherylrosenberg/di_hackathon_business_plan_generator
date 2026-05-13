# =====================================================================
# Question-Asker Workflow — Phase 2
#
# Setup:
#   1. Create a .env file with: GROQ_API_KEY=your_key_here
#   2. Get a free API key at: https://console.groq.com/keys
#   3. Install dependencies: pip install groq python-dotenv
# =====================================================================

from dotenv import load_dotenv

load_dotenv()

import json
import re
from pathlib import Path

import groq
from groq import Groq

from business_info_schema import (
    FIELD_DESCRIPTIONS,
    business_info,
    required_fields,
    generated_sections,
    workflow_state,
    get_next_field,
    is_interview_complete,
    advance_workflow,
)

MODEL = "llama-3.1-8b-instant"
JSON_OUTPUT_PATH = Path("business_info.json")
_ROADMAP_PATH = Path(__file__).resolve().parent / "interview_roadmap.md"

# Prior-answer injection for conversational questions (TPM / size bounds)
PRIOR_ANSWER_FIELD_MAX_CHARS = 450
PRIOR_ANSWERS_BLOCK_MAX_CHARS = 2400

_roadmap_text_cache: str | None = None
_roadmap_missing_warned = False

client = Groq()

QUESTION_PROMPT_CORE = (
    "You are a business interview assistant. "
    "Ask exactly one short, friendly question to collect the following "
    "information: {field_description}. "
    "Do not ask multiple questions. Do not introduce yourself. "
    "Do not include any preamble, explanation, or follow-up. "
    "Output the question only."
)

EVALUATION_SYSTEM_CORE = (
    "You validate a single user answer for one business plan interview field. "
    "Be lenient for an MVP: accept answers that are on-topic and usable in a plan, "
    "even if brief. Mark insufficient only if the answer is clearly off-topic, "
    "nonsensical, or too vague to use (e.g. single word like 'yes' or 'idk' when "
    "substance was expected). "
    "At most one follow-up will be asked in the app; do not assume a second chance. "
    "Respond with ONLY valid JSON, no markdown fences, no other text. "
    'Schema: {"sufficient": true or false, "follow_up_question": "string"}. '
    "If sufficient is true, follow_up_question must be an empty string. "
    "If sufficient is false, follow_up_question must be one short sentence: a single "
    "clarifying question that addresses ONLY the same field being validated—rephrase, "
    "narrow, or offer examples for that exact topic. "
    "Never ask about a different interview field (do not pivot to business idea, "
    "problem, target market, revenue, etc., unless that IS the field being validated). "
    "If the user said they do not know, gently re-ask the same field's intent, do not "
    "change subject."
)


# =====================================================================
# Public API
# =====================================================================


def ask_question(field: str) -> str:
    """Call Groq to generate a single conversational question for *field*."""
    description = FIELD_DESCRIPTIONS[field]
    system_content = _build_question_system_prompt(field, description, business_info)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": (
                        f"Generate one question for field `{field}` "
                        f"(canonical description: {description})"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=140,
        )
        return response.choices[0].message.content.strip()

    except groq.AuthenticationError:
        print("Invalid GROQ_API_KEY. Check your .env file.")
    except groq.APIConnectionError:
        print("Could not reach Groq API. Check your internet connection.")
    except Exception as e:
        print(f"Error generating question: {e}")

    return f"Please describe your {field.replace('_', ' ')}:"


def evaluate_answer(field: str, question_text: str, answer: str) -> tuple[bool, str | None]:
    """Ask the LLM if *answer* is sufficient; optionally return one follow-up question."""
    description = FIELD_DESCRIPTIONS[field]
    roadmap = _get_roadmap_text()
    rules = _short_rules_for_evaluation(_extract_conversation_rules(roadmap))
    field_blurb = _field_roadmap_blurb(field, roadmap)
    if not field_blurb:
        field_blurb = f"(Schema) {description}"

    system_content = (
        f"{EVALUATION_SYSTEM_CORE}\n\n"
        f"### Field: {field}\n{field_blurb}\n\n"
        f"### Conversation rules (excerpt)\n{rules}"
    )

    user_content = (
        f"The interview is collecting exactly ONE field at a time. "
        f"The active field key is `{field}`—any follow-up question must target ONLY "
        f"this field (same topic as the question below), not a different step.\n\n"
        f"Question asked to the user:\n{question_text}\n\n"
        f"User's answer:\n{answer}\n\n"
        "Return only the JSON object."
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_validation_json(raw)
        if parsed is not None:
            return parsed
    except groq.AuthenticationError:
        print("Invalid GROQ_API_KEY. Check your .env file.")
    except groq.APIConnectionError:
        print("Could not reach Groq API. Check your internet connection.")
    except Exception as e:
        print(f"Error validating answer: {e}")

    return True, None


def store_answer(field: str, answer: str) -> None:
    """Store the user's response, persist to JSON, and advance the workflow."""
    business_info[field] = answer
    workflow_state["current_field"] = None
    _save_json()
    advance_workflow(workflow_state, business_info, generated_sections)


def save_business_info() -> None:
    """Persist ``business_info`` to JSON (e.g. after manual edits in Streamlit)."""
    _save_json()


def run_interview() -> dict[str, str]:
    """Run the full interview loop in the terminal and return business_info."""
    print("\n=== Business Plan Interview ===\n")

    while not is_interview_complete(business_info):
        field = get_next_field(business_info)
        workflow_state["current_field"] = field

        question = ask_question(field)
        print(f"\n{question}")
        answer = input("> ").strip()

        sufficient, follow_up = evaluate_answer(field, question, answer)
        if not sufficient and follow_up:
            print(f"\n{follow_up}")
            answer = input("> ").strip()

        store_answer(field, answer)

    _confirm_answers()
    return business_info


# =====================================================================
# Internal helpers — prior answers + roadmap excerpts
# =====================================================================


def _format_prior_answers_for_question(field: str, info: dict[str, str]) -> str:
    """Summarise answers for fields before *field* in interview order (read-only context)."""
    try:
        current_index = required_fields.index(field)
    except ValueError:
        return ""

    lines: list[str] = []
    for f in required_fields[:current_index]:
        raw = (info.get(f) or "").strip()
        if not raw:
            continue
        if len(raw) > PRIOR_ANSWER_FIELD_MAX_CHARS:
            raw = raw[: PRIOR_ANSWER_FIELD_MAX_CHARS - 1].rstrip() + "…"
        label = f.replace("_", " ").title()
        lines.append(f"- {label}: {raw}")

    if not lines:
        return ""

    while len(lines) > 1:
        block = "\n".join(lines)
        if len(block) <= PRIOR_ANSWERS_BLOCK_MAX_CHARS:
            return block
        lines.pop(0)

    single = lines[0]
    if len(single) <= PRIOR_ANSWERS_BLOCK_MAX_CHARS:
        return single
    return single[: PRIOR_ANSWERS_BLOCK_MAX_CHARS - 1].rstrip() + "…"


def _get_roadmap_text() -> str:
    global _roadmap_text_cache, _roadmap_missing_warned
    if _roadmap_text_cache is not None:
        return _roadmap_text_cache
    if not _ROADMAP_PATH.exists():
        if not _roadmap_missing_warned:
            print(
                f"Note: interview roadmap not found at {_ROADMAP_PATH}. "
                "Continuing without roadmap excerpts."
            )
            _roadmap_missing_warned = True
        _roadmap_text_cache = ""
        return _roadmap_text_cache
    _roadmap_text_cache = _ROADMAP_PATH.read_text(encoding="utf-8")
    return _roadmap_text_cache


def _extract_conversation_rules(full: str) -> str:
    if not full.strip():
        return ""
    start_tag = "## Conversation Rules"
    end_tag = "## Integration Notes"
    i = full.find(start_tag)
    if i == -1:
        return ""
    start = i + len(start_tag)
    j = full.find(end_tag, start)
    body = full[start:j] if j != -1 else full[start:]
    body = body.strip().rstrip("-").strip()
    return body


def _strip_md_cell(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^\*+", "", t)
    t = re.sub(r"\*+$", "", t)
    t = t.replace("`", "")
    return t.strip()


def _field_roadmap_blurb(field: str, full: str) -> str:
    if not full:
        return ""
    for line in full.splitlines():
        s = line.strip()
        if not s.startswith("|") or s.startswith("|---"):
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) < 5:
            continue
        field_cell = parts[2].replace("*", "")
        if field_cell != field:
            continue
        why = _strip_md_cell(parts[3])
        example = _strip_md_cell(parts[4])
        return f"Why it matters: {why}\nExample question tone: {example}"
    return ""


def _short_rules_for_evaluation(rules_block: str, max_chars: int = 1200) -> str:
    if not rules_block:
        return "(No roadmap rules excerpt.)"
    if len(rules_block) <= max_chars:
        return rules_block
    return rules_block[: max_chars - 3].rstrip() + "..."


def _build_question_system_prompt(
    field: str, field_description: str, info: dict[str, str]
) -> str:
    core = QUESTION_PROMPT_CORE.format(field_description=field_description)
    roadmap = _get_roadmap_text()
    rules = _extract_conversation_rules(roadmap)
    field_blurb = _field_roadmap_blurb(field, roadmap)
    if field_blurb:
        field_section = (
            f"### Grounding: this field ({field})\n"
            f"{field_blurb}\n"
            f"Canonical one-line description: {field_description}"
        )
    else:
        field_section = (
            f"### Grounding: this field ({field})\n{field_description}"
        )

    rules_section = (
        "### Grounding: conversation rules (from interview roadmap)\n"
        + (rules if rules else "(Roadmap rules section not available.)")
    )

    parts = [core, rules_section, field_section]

    prior_block = _format_prior_answers_for_question(field, info)
    if prior_block:
        how_prior = (
            "### Prior answers (already collected; read-only)\n"
            f"{prior_block}\n\n"
            "### How to use prior answers\n"
            "- Only acknowledge prior text if it **already answers or partially answers "
            "THIS field's intent**. Example: for a **problem** / pain-point field, reference "
            "prior answers only if they already describe friction, gaps, failed alternatives, "
            "or consequences—not merely target customer, revenue model, or product description "
            "unless that same text explicitly states the problem.\n"
            "- If you are **unsure** whether prior text satisfies this field, **do not** "
            "reference it; ask a normal standalone question.\n"
            "- **Never** paste long phrases verbatim from prior answers. At most one short "
            "paraphrase (about eight words or fewer), or skip acknowledgment entirely.\n"
            "- Do not invent details not present in the prior answers or field description.\n"
            "- Output exactly one question total (no bullet lists). One optional brief "
            "acknowledgment clause, then the question.\n"
            "- (The instruction to avoid preamble allows at most that one optional "
            "acknowledgment clause when you use prior answers as above.)"
        )
        parts.append(how_prior)

    return "\n\n".join(parts)


def _parse_validation_json(raw: str) -> tuple[bool, str | None] | None:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    sufficient = bool(data.get("sufficient"))
    fq = (data.get("follow_up_question") or "").strip()

    if sufficient:
        return True, None
    if fq:
        return False, fq
    return None


# =====================================================================
# Internal helpers
# =====================================================================


def _save_json() -> None:
    """Persist current business_info to disk as JSON."""
    JSON_OUTPUT_PATH.write_text(json.dumps(business_info, indent=2))


def _print_summary() -> None:
    """Print a formatted summary of all collected answers."""
    print("\n=== Interview Summary ===\n")
    for i, field in enumerate(required_fields, start=1):
        label = field.replace("_", " ").title()
        print(f"  {i}. {label}: {business_info[field]}")
    print()


def _confirm_answers() -> None:
    """Show summary and let the user re-enter fields until satisfied."""
    while True:
        _print_summary()
        choice = input("Are you happy with these answers? (y/n): ").strip().lower()

        if choice == "y":
            _save_json()
            print(
                "\nInterview complete. "
                "Ready to generate your business plan.\n"
            )
            return

        print("\nWhich field would you like to change?")
        for i, field in enumerate(required_fields, start=1):
            label = field.replace("_", " ").title()
            print(f"  {i}. {label}")

        try:
            pick = int(input("\nEnter the number: ").strip())
            if 1 <= pick <= len(required_fields):
                field = required_fields[pick - 1]
                label = field.replace("_", " ").title()
                print(f"\nCurrent value: {business_info[field]}")
                new_value = input(f"New value for {label}: ").strip()
                if new_value:
                    business_info[field] = new_value
            else:
                print("Invalid number. Try again.")
        except ValueError:
            print("Please enter a valid number.")


# =====================================================================
# Standalone entry point
# =====================================================================

if __name__ == "__main__":
    run_interview()
