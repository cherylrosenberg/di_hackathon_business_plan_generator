# =====================================================================
# Local GPTScore-style evaluation (class / demo)
#
# Uses Hugging Face open weights (distilgpt2): length-normalized negative
# log-likelihood of plan excerpts under short aspect prompts (coherence,
# fluency). Readability uses textstat (Flesch Reading Ease) — a classical
# metric — because small LMs are weak judges of "readability" alone.
#
# Lower avg_nll = higher model confidence under that prompt (better for demo).
# First run downloads model weights. Optional HF_TOKEN or HUGGING_FACE_HUB_TOKEN
# in .env improves Hugging Face Hub rate limits (never log or print the token).
# =====================================================================

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCORING_MODEL = "distilgpt2"
MAX_POSITIONS = 1024
RESERVED_FOR_PROMPT = 120
MAX_CHUNK_TOKENS = MAX_POSITIONS - RESERVED_FOR_PROMPT

COHERENCE_PREFIX = (
    "You are scoring COHERENCE for a business plan excerpt. "
    "The excerpt should read as one connected argument (clear flow, no "
    "contradictions, sections that fit together).\n\nPlan excerpt:\n"
)

FLUENCY_PREFIX = (
    "You are scoring FLUENCY for a business plan excerpt. "
    "The writing should be grammatical, natural, and easy to follow.\n\n"
    "Plan excerpt:\n"
)

_model = None
_tokenizer = None


def _get_model_and_tokenizer():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    _tokenizer = AutoTokenizer.from_pretrained(SCORING_MODEL, token=hf_token)
    _model = AutoModelForCausalLM.from_pretrained(SCORING_MODEL, token=hf_token)
    _model.eval()
    if torch.cuda.is_available():
        _model = _model.cuda()
    return _model, _tokenizer


def markdown_to_plain(md: str) -> str:
    """Strip lightweight markdown for readability metrics and chunking."""
    lines = []
    for line in md.splitlines():
        s = line.strip()
        if not s or s == "---":
            continue
        if s.startswith("#"):
            s = re.sub(r"^#+\s*", "", s)
        s = re.sub(r"\*+", "", s)
        lines.append(s)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_markdown_sections(md: str) -> list[str]:
    """Split on ## headings; fall back to plain chunks if no headings."""
    parts: list[str] = []
    current: list[str] = []
    for line in md.splitlines():
        if line.strip().startswith("## ") and current:
            parts.append("\n".join(current).strip())
            current = [line.strip()]
        else:
            current.append(line)
    if current:
        parts.append("\n".join(current).strip())
    out = [p for p in parts if p]
    return out if out else [md.strip()]


def _chunk_by_tokens(text: str, tokenizer, max_tokens: int) -> list[str]:
    """Split long text into chunks that fit in context with the prompt."""
    ids = tokenizer.encode(text, add_special_tokens=False)
    if len(ids) <= max_tokens:
        return [text]
    chunks: list[str] = []
    # Byte-level or token windows: use token windows via decoding slices
    start = 0
    while start < len(ids):
        end = min(start + max_tokens, len(ids))
        piece = tokenizer.decode(ids[start:end], skip_special_tokens=True)
        if piece.strip():
            chunks.append(piece)
        start = end
    return chunks


def _avg_nll_for_chunk(model, tokenizer, prefix: str, chunk: str) -> float | None:
    """Mean NLL (nat) over chunk tokens only; None if nothing to score.

    Tokenizes ``prefix + chunk`` once and uses ``return_offsets_mapping`` so
    chunk boundaries survive BPE merges between prefix and body (avoids null
    scores when ``encode(prefix)`` does not match the start of ``encode(full)``).
    """
    import torch

    device = next(model.parameters()).device
    chunk = chunk.strip()
    if not chunk:
        return None

    prefix_str = prefix
    full_str = prefix_str + chunk
    body_char_start = len(prefix_str)

    enc = tokenizer(
        full_str,
        return_tensors="pt",
        add_special_tokens=False,
        truncation=True,
        max_length=MAX_POSITIONS,
        return_offsets_mapping=True,
    )
    input_ids = enc["input_ids"].to(device)
    seq_len = input_ids.shape[1]
    if seq_len < 2:
        return None

    om = enc["offset_mapping"][0]
    first_body_token_idx: int | None = None
    for t in range(seq_len):
        start, end = om[t]
        start_i = int(start)
        end_i = int(end)
        if start_i == 0 and end_i == 0:
            continue
        if end_i > body_char_start:
            first_body_token_idx = t
            break

    if first_body_token_idx is None:
        return None

    start_j = max(first_body_token_idx, 1)
    if start_j >= seq_len:
        return None

    with torch.no_grad():
        out = model(input_ids)
        logits = out.logits[0]

    nll_sum = 0.0
    count = 0
    for j in range(start_j, seq_len):
        i = j - 1
        target = input_ids[0, j]
        logp = torch.nn.functional.log_softmax(logits[i], dim=-1)[target]
        nll_sum -= float(logp.item())
        count += 1
    return nll_sum / count if count else None


def _score_aspect_on_document(raw_md: str, prefix: str) -> float | None:
    """Average NLL over token-chunks, splitting on ## sections in the raw markdown."""
    model, tokenizer = _get_model_and_tokenizer()
    chunks: list[str] = []
    for section in _split_markdown_sections(raw_md):
        plain_section = markdown_to_plain(section)
        if not plain_section.strip():
            continue
        chunks.extend(_chunk_by_tokens(plain_section, tokenizer, MAX_CHUNK_TOKENS))

    if not chunks:
        plain_all = markdown_to_plain(raw_md)
        if not plain_all.strip():
            return None
        chunks = _chunk_by_tokens(plain_all, tokenizer, MAX_CHUNK_TOKENS)

    values: list[float] = []
    for ch in chunks:
        v = _avg_nll_for_chunk(model, tokenizer, prefix, ch.strip())
        if v is not None:
            values.append(v)
    if not values:
        return None
    return sum(values) / len(values)


def evaluate_plan_scores(md_path: str | Path = "business_plan.md") -> dict:
    """
    Run local scoring. Returns a dict suitable for JSON serialization.
    Raises ImportError if torch/transformers/textstat missing.
    """
    try:
        import textstat
    except ImportError as e:
        return {
            "error": "missing_dependencies",
            "message": f"Install scoring deps: {e}",
            "model": SCORING_MODEL,
        }

    path = Path(md_path)
    if not path.exists():
        raise FileNotFoundError(f"No business plan at {path}")

    raw = path.read_text(encoding="utf-8")
    plain = markdown_to_plain(raw)

    if not plain:
        return {
            "error": "empty_plan",
            "model": SCORING_MODEL,
        }

    try:
        coherence = _score_aspect_on_document(raw, COHERENCE_PREFIX)
        fluency = _score_aspect_on_document(raw, FLUENCY_PREFIX)
    except ImportError as e:
        return {
            "error": "missing_dependencies",
            "message": str(e),
            "model": SCORING_MODEL,
        }

    try:
        flesch = float(textstat.flesch_reading_ease(plain))
    except Exception:
        flesch = None

    return {
        "model": SCORING_MODEL,
        "coherence_avg_nll": coherence,
        "fluency_avg_nll": fluency,
        "readability_flesch_reading_ease": flesch,
        "interpretation": {
            "coherence_avg_nll": "Lower is better (higher LM confidence under coherence framing).",
            "fluency_avg_nll": "Lower is better (higher LM confidence under fluency framing).",
            "readability_flesch_reading_ease": "0–100; higher = easier to read (classical readability).",
        },
    }


def print_score_table(scores: dict) -> None:
    err = scores.get("error")
    if err:
        print(f"\n[Plan scoring] {err}: {scores.get('message', '')}")
        return
    print("\n=== Local plan scores (GPTScore-style + readability) ===\n")
    print(f"  Model: {scores['model']}")
    c = scores.get("coherence_avg_nll")
    f = scores.get("fluency_avg_nll")
    r = scores.get("readability_flesch_reading_ease")
    print(f"  Coherence (avg NLL):     {c:.4f}" if c is not None else "  Coherence (avg NLL):     n/a")
    print(f"  Fluency (avg NLL):     {f:.4f}" if f is not None else "  Fluency (avg NLL):     n/a")
    print(
        f"  Readability (Flesch):   {r:.1f}"
        if r is not None
        else "  Readability (Flesch):   n/a"
    )
    print("\n  Lower NLL = more confident under that aspect prompt. "
          "Flesch is independent (textstat).")
    print()


def save_scores_json(scores: dict, out_path: str | Path = "plan_scores.json") -> None:
    Path(out_path).write_text(json.dumps(scores, indent=2), encoding="utf-8")
    print(f"Scores saved to {out_path}")


def run_plan_scoring(
    md_path: str | Path = "business_plan.md",
    json_path: str | Path = "plan_scores.json",
) -> dict:
    """Evaluate plan; print table and write JSON. Returns scores dict."""
    scores = evaluate_plan_scores(md_path)
    print_score_table(scores)
    if not scores.get("error"):
        save_scores_json(scores, json_path)
    return scores


if __name__ == "__main__":
    run_plan_scoring()
