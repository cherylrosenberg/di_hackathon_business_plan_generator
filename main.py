# =====================================================================
# AI Business Plan Generator — Main Entry Point
#
# Run with:  py main.py
# Skip local plan scoring:  py main.py --no-score
#
# Pipeline:
#   1. Interview  — collect business info via conversational Q&A
#   2. Generate   — produce a Markdown business plan section by section
#   3. Export     — convert the Markdown to a styled PDF
#   4. Score      — local distilgpt2 + textstat (optional; see plan_gptscore.py)
# =====================================================================

import argparse

from dotenv import load_dotenv

load_dotenv()

from question_asker import run_interview
from plan_generator import generate_plan
from pdf_converter import convert_to_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Business Plan Generator")
    parser.add_argument(
        "--no-score",
        action="store_true",
        help="Skip local GPTScore-style plan scoring (torch/transformers download).",
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  AI Business Plan Generator")
    print("=" * 55)

    run_interview()
    generate_plan()
    convert_to_pdf()

    if not args.no_score:
        try:
            from plan_gptscore import run_plan_scoring

            run_plan_scoring()
        except ImportError as e:
            print(
                "\n[Plan scoring] Skipped (install torch, transformers, textstat): "
                f"{e}\n"
            )

    print()
    print("=" * 55)
    print("  All done! Files created:")
    print("    - business_info.json   (interview answers)")
    print("    - business_plan.md     (generated plan)")
    print("    - business_plan.pdf    (PDF export)")
    if not args.no_score:
        print(
            "    - plan_scores.json     (local scoring; requires torch, transformers)"
        )
    print("=" * 55)


if __name__ == "__main__":
    main()
