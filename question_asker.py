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

SYSTEM_PROMPT = (
    "You are a business interview assistant. "
    "Ask exactly one short, friendly question to collect the following "
    "information: {field_description}. "
    "Do not ask multiple questions. Do not introduce yourself. "
    "Do not include any preamble, explanation, or follow-up. "
    "Output the question only."
)

client = Groq()


# =====================================================================
# Public API
# =====================================================================

def ask_question(field: str) -> str:
    """Call Groq to generate a single conversational question for *field*."""
    description = FIELD_DESCRIPTIONS[field]

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(field_description=description),
                },
                {
                    "role": "user",
                    "content": (
                        f"Generate one question to collect this field: "
                        f"{field} — {description}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()

    except groq.AuthenticationError:
        print("Invalid GROQ_API_KEY. Check your .env file.")
    except groq.APIConnectionError:
        print("Could not reach Groq API. Check your internet connection.")
    except Exception as e:
        print(f"Error generating question: {e}")

    return f"Please describe your {field.replace('_', ' ')}:"


def store_answer(field: str, answer: str) -> None:
    """Store the user's response, persist to JSON, and advance the workflow."""
    business_info[field] = answer
    workflow_state["current_field"] = None
    _save_json()
    advance_workflow(workflow_state, business_info, generated_sections)


def run_interview() -> dict[str, str]:
    """Run the full interview loop in the terminal and return business_info."""
    print("\n=== Business Plan Interview ===\n")

    while not is_interview_complete(business_info):
        field = get_next_field(business_info)
        workflow_state["current_field"] = field

        question = ask_question(field)
        print(f"\n{question}")
        answer = input("> ").strip()
        store_answer(field, answer)

    _confirm_answers()
    return business_info


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
