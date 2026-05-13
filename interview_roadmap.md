# Interview Roadmap — Question-Asker Workflow

## Purpose

This document is the reference guide (and future LLM grounding context) for the **Question-Asker** workflow. The workflow's job is to have a natural, one-question-at-a-time conversation with the user until every required business field has been collected. Once complete, the structured data is handed off to the **Business Plan Generator** workflow.

---

## Required Fields & Why They Matter

| # | Field | Why It Matters | Example Question |
|---|-------|---------------|-----------------|
| 1 | **business_name** | Anchors the entire plan and gives the reader immediate context. | *"What is the name of your business or startup?"* |
| 2 | **business_idea** | Provides the foundational description of the venture; everything else builds on it. | *"In a few sentences, what does your business do?"* |
| 3 | **problem_solved** | Investors and readers need to see a clear pain point. A plan without a problem is just a solution looking for one. | *"What specific problem does your business solve for its customers?"* |
| 4 | **target_market** | Defines who will pay. Without a well-defined audience the marketing and revenue sections fall apart. | *"Who are your ideal customers? Think about age, location, profession, or any specific niche."* |
| 5 | **revenue_model** | Shows the business is financially viable and has a path to sustainability. | *"How will your business make money? For example: subscriptions, one-time purchases, advertising, licensing…"* |
| 6 | **competitors** | Demonstrates market awareness and helps frame the unique value proposition. | *"Who are your main competitors or alternatives that your customers use today?"* |
| 7 | **marketing_strategy** | Explains how the business will actually reach and acquire customers. | *"What is your plan for reaching your target customers? Think about channels like social media, SEO, partnerships, or events."* |
| 8 | **startup_budget** | Grounds the plan in reality and sets expectations for the financial overview. | *"What is your estimated startup budget or the funding you'll need to launch?"* |
| 9 | **unique_value_proposition** | The differentiator — why a customer would choose this business over an alternative. | *"What makes your business unique compared to existing solutions?"* |

---

## Conversation Rules

### One question → one field (strict)
Each assistant message targets exactly **one** missing field. Never combine multiple fields into a single prompt. Use `get_next_field()` to determine which field to ask about.

### Do NOT extract multiple fields from one answer
Even if the user's response contains information relevant to several fields, **store only the answer for the field you asked about**. Ignore embedded clues about other fields. This keeps the MVP loop simple and predictable.

> **Example — what NOT to do:**
> The user says *"I'm building a fitness app for busy professionals and charging monthly subscriptions."*
> You could theoretically extract `business_idea`, `target_market`, and `revenue_model` — but **don't**.
> Store the answer for the single field you asked, then move on to the next question.

> **Future improvement:** Multi-field extraction with an LLM parsing step can be added post-hackathon to make the interview feel shorter.

### Follow the defined field order
Ask fields in the order they appear in `required_fields` (name → idea → problem → market → …). A predictable sequence is easier to debug and demo.

### Avoid repetitive or redundant questions
Before asking, check whether the user has already provided the information in a prior answer. If so, skip that field — but only if the stored value is already non-empty. Do not silently infer and populate fields.

### Keep questions conversational and clear
Avoid jargon-heavy phrasing. If a field might confuse a first-time founder (e.g., "revenue model"), include a short clarification or examples in the question. Use `FIELD_DESCRIPTIONS` from the schema to ground the question.

### Validate briefly, don't over-interrogate
If a response is vague or too short to be useful in a business plan, ask **one** follow-up for more detail. If the user insists, accept the answer and move on. This is an MVP, not a due-diligence interview.

When the app generates that follow-up via `evaluate_answer` in `question_asker.py`, it must stay on **the same field** as the question being validated (rephrase, narrow, or add examples for that topic only)—never redirect the user to a different interview field (e.g. do not ask about business idea or problem when the current step is target market).

### Prior answers in later questions (runtime)
At question generation time, `question_asker.py` may inject a **read-only** summary of answers for fields **already collected** (same order as `required_fields` in `business_info_schema.py`; only fields strictly *before* the current field).

- Each prior answer is **truncated per field** in code to cap prompt size; this is not the full unbounded transcript.
- The question LLM may add **at most** one short acknowledgment **only when** prior text **already answers or partially answers the current field's intent**—not merely because it is thematically related to the business (e.g. do not pull target-audience or product-positioning lines from `business_idea` into a **problem_solved** question unless that text explicitly states the pain or gap).
- If relevance is **uncertain**, the model should **not** reference prior answers and should ask a normal standalone question instead.
- **No long verbatim quotes** from prior answers; at most a **brief paraphrase** (on the order of eight words or fewer), or no acknowledgment.
- The model must **not** invent facts that are not in the injected block or in the field description.
- This injection does **not** copy or infer values into other `business_info` keys; each reply is still stored only under the field currently being asked (same as **Do NOT extract multiple fields from one answer**).

### Determine when collection is complete
The interview is finished when `is_interview_complete(business_info)` returns `True`. At that point:
1. Summarise the collected information back to the user.
2. Ask for confirmation or final edits.
3. Transition to the Business Plan Generator workflow.

---

## Integration Notes

- This document is injected into the question LLM **system** prompt as grounding context (conversation rules + per-field table blurbs), loaded from disk at runtime by `question_asker.py`.
- When there are prior answers for earlier fields, the same system prompt also includes a **bounded prior-answers block** (see **Prior answers in later questions (runtime)** above), with **strict rules** so acknowledgments only occur when prior text already addresses the current field's intent; omitted entirely for the first field or when no prior fields are filled.
- The assistant should reference `business_info_schema.py` at runtime to know which fields remain empty.
- Use `FIELD_DESCRIPTIONS[field]` in the prompt so the LLM understands what information to collect.
- Use `get_next_field(business_info)` to pick the next question — do not let the LLM decide field order.
- Each user response is stored into **exactly one** field in `business_info`, then the loop repeats.
