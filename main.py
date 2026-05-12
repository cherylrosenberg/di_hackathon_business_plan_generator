# =====================================================================
# AI Business Plan Generator — Main Entry Point
#
# Run with:  py main.py
#
# Pipeline:
#   1. Interview  — collect business info via conversational Q&A
#   2. Generate   — produce a Markdown business plan section by section
#   3. Export     — convert the Markdown to a styled PDF
# =====================================================================

from dotenv import load_dotenv

load_dotenv()

from question_asker import run_interview
from plan_generator import generate_plan
from pdf_converter import convert_to_pdf


def main() -> None:
    print("=" * 55)
    print("  AI Business Plan Generator")
    print("=" * 55)

    run_interview()
    generate_plan()
    convert_to_pdf()

    print()
    print("=" * 55)
    print("  All done! Files created:")
    print("    - business_info.json   (interview answers)")
    print("    - business_plan.md     (generated plan)")
    print("    - business_plan.pdf    (PDF export)")
    print("=" * 55)


if __name__ == "__main__":
    main()
