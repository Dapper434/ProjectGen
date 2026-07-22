"""Simple RAG completeness check: retrieves relevant excerpts from agency-uploaded
authoritative RequirementDocument rows and asks the LLM whether a generated brief or
proposal satisfies them. Deliberately lexical (TF-IDF over paragraphs) rather than
embeddings-based — no verified NIM embeddings access for this API key, no new
dependency, and retrieval only needs to get a reasonably relevant candidate set since
the LLM does the actual judgment on top of it.
"""
import re
import math
from collections import Counter
from typing import List
from pydantic import BaseModel, Field

from agents import call_nim_api, _extract_json, NIM_API_KEY

# Small hardcoded stopword list — enough to stop generic business-prose words from
# swamping the term-frequency signal. Not exhaustive; this is a "simple" RAG.
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "be", "this", "that", "it", "as", "by", "at", "from", "we", "will", "which", "its",
    "their", "our", "should", "must", "shall", "not", "if", "then", "also", "any",
    "all", "can", "have", "has", "had", "into", "about", "than", "these", "those",
    "your", "you", "they", "them", "such", "may", "each", "other", "when", "what",
}

MAX_CONTEXT_CHARS = 6000
TOP_K_PARAGRAPHS = 10


class CompletenessCheckSchema(BaseModel):
    complete: bool
    missing: List[str] = Field(default_factory=list)
    notes: str = ""


def _paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n', text or '') if p.strip()]


def _tokenize(text):
    return [t for t in re.findall(r'[a-z0-9]+', text.lower()) if t not in STOPWORDS]


def _rank_paragraphs(query_text, paragraphs):
    """Paragraphs sorted most-relevant-first by TF-IDF cosine similarity to the query."""
    tokenized = [_tokenize(p) for p in paragraphs]
    df = Counter()
    for toks in tokenized:
        df.update(set(toks))
    n_docs = len(paragraphs)
    idf = {term: math.log(n_docs / count) for term, count in df.items()}

    def vectorize(tokens):
        tf = Counter(tokens)
        return {term: tf[term] * idf.get(term, 0) for term in tf}

    def cosine(v1, v2):
        common = set(v1) & set(v2)
        dot = sum(v1[t] * v2[t] for t in common)
        norm1 = math.sqrt(sum(v * v for v in v1.values()))
        norm2 = math.sqrt(sum(v * v for v in v2.values()))
        return dot / (norm1 * norm2) if norm1 and norm2 else 0.0

    query_vec = vectorize(_tokenize(query_text))
    scored = sorted(
        zip(paragraphs, tokenized),
        key=lambda pair: -cosine(query_vec, vectorize(pair[1]))
    )
    return [p for p, _ in scored]


def _gather_context(query_text, requirement_docs):
    """All matching requirement paragraphs verbatim if the corpus is small; otherwise
    the top TF-IDF-scored paragraphs against the generated document as the query."""
    paragraphs = []
    for doc in requirement_docs:
        paragraphs.extend(_paragraphs(doc.raw_text))

    combined = "\n\n".join(paragraphs)
    if not paragraphs or len(combined) <= MAX_CONTEXT_CHARS:
        return combined

    return "\n\n".join(_rank_paragraphs(query_text, paragraphs)[:TOP_K_PARAGRAPHS])


REFERENCE_PURPOSE_LABELS = {
    "structure": "structure/template reference — follow its organization and phrasing conventions",
    "content": "content/background reference — factual material to enrich context",
}


def build_reference_context(query_text, reference_docs, max_chars=MAX_CONTEXT_CHARS):
    """Formatted excerpt block from engagement-scoped ReferenceDocument rows, for
    feeding INTO generation prompts (structure and content enrichment). Unlike the
    completeness corpus, per-document titles/purposes are kept so the model can tell
    a template apart from client background material. Each document gets an equal
    share of the char budget; oversized ones contribute their most query-relevant
    paragraphs only."""
    docs = [d for d in reference_docs if (d.raw_text or '').strip()]
    if not docs:
        return ""

    per_doc_budget = max(800, max_chars // len(docs))
    blocks = []
    for doc in docs:
        text = doc.raw_text.strip()
        if len(text) > per_doc_budget:
            kept, used = [], 0
            for para in _rank_paragraphs(query_text, _paragraphs(text)):
                if used + len(para) > per_doc_budget and kept:
                    break
                kept.append(para)
                used += len(para)
            text = "\n\n".join(kept)
        label = REFERENCE_PURPOSE_LABELS.get(doc.purpose, "reference")
        blocks.append(f'--- "{doc.title}" [{label}] ---\n{text}')
    return "\n\n".join(blocks)


def check_completeness(doc_type: str, rendered_markdown: str, requirement_docs) -> dict:
    """doc_type is 'brief' or 'proposal'. requirement_docs is the list of active
    RequirementDocument rows already filtered by the caller (doc_type + 'general')."""
    label = "Production Brief" if doc_type == "brief" else "Client Proposal"

    if not NIM_API_KEY:
        return {"complete": None, "missing": [], "notes": "No NIM_API_KEY configured — completeness check unavailable."}

    context = _gather_context(rendered_markdown, requirement_docs)

    system_prompt = f"""You are a Requirements Completeness Checker for a creative agency middleman platform. You are given excerpts from the agency's own authoritative documents describing what a complete {label} must contain, and a generated {label}. Identify anything the authoritative excerpts require that is missing, vague, or explicitly marked as unspecified in the generated document.

<task>
1. Only flag something as missing if the authoritative excerpts actually require it — never invent a requirement that isn't grounded in the excerpts, even if you personally think it would be good practice.
2. If the excerpts don't clearly require something, don't flag it.
3. Be specific: name the missing item the way the excerpts describe it, not a vague restatement.
</task>

<output_format>
Respond ONLY with a JSON object with exactly these keys:
1. "complete": true if every requirement from the excerpts is satisfied, false otherwise.
2. "missing": a list of short strings, each one a specific missing or incomplete requirement. Empty list if complete.
3. "notes": one short sentence of context, or an empty string.
</output_format>"""

    user_prompt = f"""<authoritative_excerpts>
{context}
</authoritative_excerpts>

<generated_document>
{rendered_markdown}
</generated_document>"""

    try:
        raw_response, _usage = call_nim_api(system_prompt, user_prompt, reasoning="low")
        parsed_json = _extract_json(raw_response)
        CompletenessCheckSchema(**parsed_json)
        return parsed_json
    except Exception as e:
        print(f"Completeness check failed: {e}. Retrying with escalated reasoning...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response, _usage = call_nim_api(system_prompt, retry_prompt, reasoning="full")
            parsed_json = _extract_json(raw_response)
            CompletenessCheckSchema(**parsed_json)
            return parsed_json
        except Exception as retry_e:
            print(f"Completeness check failed on retry: {retry_e}. Reporting unknown.")
            return {"complete": None, "missing": [], "notes": f"Completeness check failed: {retry_e}"}
