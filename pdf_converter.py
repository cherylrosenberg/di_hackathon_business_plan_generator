# =====================================================================
# PDF Converter — Markdown to PDF via fpdf2
#
# Converts the generated business_plan.md into a styled PDF.
# Parses the predictable markdown structure directly — no HTML step.
# =====================================================================

from pathlib import Path

from fpdf import FPDF

UNICODE_REPLACEMENTS = {
    "\u2014": "--",   # em dash
    "\u2013": "-",    # en dash
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",    # non-breaking space
}


def _sanitize(text: str) -> str:
    """Replace common Unicode characters with ASCII equivalents."""
    for char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text


class BusinessPlanPDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def convert_to_pdf(
    md_path: str = "business_plan.md",
    pdf_path: str = "business_plan.pdf",
) -> None:
    """Convert the business plan Markdown file to a styled PDF."""
    md_text = Path(md_path).read_text(encoding="utf-8")
    lines = md_text.splitlines()

    pdf = BusinessPlanPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    for line in lines:
        stripped = line.strip()

        if not stripped:
            pdf.ln(4)
            continue

        if stripped.startswith("# ") and not stripped.startswith("## "):
            _render_title(pdf, stripped[2:])
        elif stripped.startswith("## "):
            _render_heading(pdf, stripped[3:])
        elif stripped == "---":
            _render_hr(pdf)
        elif stripped.startswith("*") and stripped.endswith("*"):
            _render_italic(pdf, stripped.strip("*"))
        else:
            _render_body(pdf, stripped)

    try:
        pdf.output(pdf_path)
        print(f"PDF saved to {pdf_path}")
    except Exception as e:
        print(f"PDF conversion failed: {e}")
        print(f"The Markdown file is still available at {md_path}")


def _render_title(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 14, _sanitize(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(50, 50, 50)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(8)


def _render_heading(pdf: FPDF, text: str) -> None:
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 10, _sanitize(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)


def _render_hr(pdf: FPDF) -> None:
    pdf.ln(2)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)


def _render_body(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 6, _sanitize(text))
    pdf.ln(2)


def _render_italic(pdf: FPDF, text: str) -> None:
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 10, _sanitize(text), new_x="LMARGIN", new_y="NEXT")


if __name__ == "__main__":
    convert_to_pdf()
