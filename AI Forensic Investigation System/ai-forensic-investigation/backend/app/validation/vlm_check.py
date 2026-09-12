"""Phase 4 - grounding checks for VLM observations on internet test fixtures.

Evaluates whether a structured VLM observation (the output of
``provider.vision_observe_frames``) is grounded in the supplied visual
evidence, and whether it correctly declines to state things that cannot be
established from the supplied frames.

This module performs PURE TEXT/LOGIC evaluation - it is fully offline and
never touches the network. Authoring-time "expected observable facts" stand in
for the human ground truth that is verified by looking at each fixture.

Design notes
------------
* We do NOT require exact wording - only that an observation statement shares
  content tokens with the supplied evidence vocabulary (expected facts derived
  from the fixture + known context metadata such as detection labels).
* An OBSERVED statement that shares NO content token with the evidence
  vocabulary is flagged ``unsupported`` (a fabrication / hallucination signal).
* A statement that asserts a prohibited theme (identity, intent, names, …)
  is flagged ``prohibited`` - even if the wording is otherwise plausible.
* Coverage (expected facts mentioned by some statement) is reported as a
  ``coverage`` score and ``missing_facts`` list; it is descriptive, because a
  fixture usually shows more than any short fact list.
* UNKNOWN / INSUFFICIENT_EVIDENCE cases are handled explicitly: the correct
  behavior is to abstain (classify as UNKNOWN) rather than to guess.

The fixtures processed by this module live under ``data/vlm_test/`` and are
INTERNET TEST DATA - never genuine forensic evidence.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

# Classification labels understood by the observation contract (mirrors
# app/ai/provider.py so results stay consistent with the live pipeline).
CLASS_OBSERVED = "OBSERVED"
CLASS_INFERRED = "INFERRED"
CLASS_UNKNOWN = "UNKNOWN"
ABSTAIN_CLASSES = (CLASS_UNKNOWN, "INSUFFICIENT_EVIDENCE")

# High-frequency, non-content words removed before any token comparison.
_STOPWORDS = frozenset(
    """
    a an the and or but if then else for to of in on at by from with without
    about over under into through during between among is are was were be been
    being am do does did have has had will would can could shall should may
    might must need ought shall like as than so very just only also not no nor
    yes yet already again once here there here where when while who whom which
    what why how this that these those it its their theirs our ours your yours
    my mine his her him she he they we you i me us them one two few many much
    some any each every all both most other such same image scene frame frames
    camera cameras show shows shows showing appears appear appeared displays
    display displaying seen observe observed observation visual video clip
    result output model system analysis look like looks seem seems suggest
    suggesting possible possibly likely indicates indicated unknown unknown
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small inflection table so prohibited-theme matching survives common verb
# forms without pulling in a full stemmer (e.g. "steal" -> "stolen").
_INFLECTIONS = {
    "stealing": "steal", "steals": "steal", "stolen": "steal", "stole": "steal",
    "shoplifter": "shoplift", "shoplifters": "shoplift", "shoplifting": "shoplift",
    "shoplifts": "shoplift",
    "breaking": "break", "breaks": "break", "broken": "break",
    "theft": "theft",
}


def _canonical(token: str) -> str:
    return _INFLECTIONS.get(token.lower(), token.lower())


def _theme_hits(tokens: set[str], prohibited_themes: set[str]) -> bool:
    """Whether any content ``tokens`` asserts one of the prohibited themes.

    Matches by canonical form first, then by a shared stem of length >= 4 so
    inflected variants are also caught. Over-matching is SAFE here: the check
    fails closed (a borderline match is reported as a prohibited claim).
    """
    for tok in tokens:
        ct = _canonical(tok)
        for theme in prohibited_themes:
            ch = _canonical(theme)
            if ct == ch:
                return True
            if len(ct) >= 4 and len(ch) >= 4 and (ct in ch or ch in ct):
                return True
    return False


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


def content_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric token set with stopwords removed."""
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1 and t not in _STOPWORDS}


def _parse_statements(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the observation's statements with a validated classification."""
    out: list[dict[str, Any]] = []
    for item in observation.get("statements") or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement", "")).strip()
        if not statement:
            continue
        cls = str(item.get("classification", "")).strip().upper()
        if cls not in (CLASS_OBSERVED, CLASS_INFERRED, CLASS_UNKNOWN, "INSUFFICIENT_EVIDENCE"):
            cls = CLASS_UNKNOWN
        out.append(
            {
                "statement": statement,
                "classification": cls,
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "basis": [str(b) for b in (item.get("basis") or []) if isinstance(b, (str, int, float))],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Grounding evaluation
# ---------------------------------------------------------------------------


def _fact_overlap(statement_tokens: set[str], fact_tokens: set[str]) -> bool:
    return bool(statement_tokens & fact_tokens)


def _evidence_vocab(expected_facts: Sequence[str], context_tokens: Iterable[str] = ()) -> set[str]:
    vocab: set[str] = set()
    for fact in expected_facts:
        vocab |= content_tokens(fact)
    for chunk in context_tokens:
        vocab |= content_tokens(str(chunk))
    return vocab


def evaluate_grounding(
    observation: dict[str, Any],
    expected_facts: Sequence[str],
    evidence_context: Iterable[str] = (),
    prohibited_themes: Sequence[str] = (),
) -> dict[str, Any]:
    """Evaluate whether ``observation`` is grounded in the supplied evidence.

    Arguments
    ---------
    observation:
        Output of ``provider.vision_observe_frames`` (keys ``summary``,
        ``statements``, ``notes``, ``model``).
    expected_facts:
        Observable facts a human verifier established from the fixture, e.g.
        ``["parking lot", "traffic cones", "trucks"]``. Exact wording is not
        required in the observation.
    evidence_context:
        Additional known metadata tokens (e.g. detection labels, camera/session
        ids, source-frame references) that count as supplied evidence.
    prohibited_themes:
        Tokens that must never be asserted as OBSERVED facts (identity, intent,
        names, …), e.g. ``["identity", "name", "steal", "intent"]``.

    Returns a JSON-serialisable verdict dict.
    """
    expected_facts = [str(f) for f in expected_facts if str(f).strip()]
    prohibited = content_tokens(" ".join(prohibited_themes))

    statements = _parse_statements(observation)
    vocab = _evidence_vocab(expected_facts, evidence_context)

    unsupported: list[str] = []
    prohibited_claims: list[str] = []
    covered_fact_tokens: set[str] = set()
    abstained = False

    for st in statements:
        tokens = content_tokens(st["statement"])
        if st["classification"] in ABSTAIN_CLASSES:
            abstained = True
            continue
        # Only OBSERVED/INFERRED statements are checked for fabrication.
        if st["classification"] not in (CLASS_OBSERVED, CLASS_INFERRED):
            continue
        if _theme_hits(tokens, prohibited):
            prohibited_claims.append(st["statement"])
        if vocab and not (tokens & vocab):
            unsupported.append(st["statement"])
        covered_fact_tokens |= tokens

    expected_tokens: set[str] = set()
    for fact in expected_facts:
        expected_tokens |= content_tokens(fact)

    missing_facts = []
    for fact in expected_facts:
        ft = content_tokens(fact)
        if ft and not (ft & covered_fact_tokens):
            missing_facts.append(fact)

    coverage = len(expected_tokens & covered_fact_tokens) / len(expected_tokens) if expected_tokens else 1.0
    # Grounded requires that the observation actually observed something from the
    # supplied evidence AND fabricated nothing. Total abstention (coverage == 0)
    # is the right behaviour only for UNKNOWN cases, not for normal ones.
    grounded = coverage > 0 and not unsupported and not prohibited_claims
    notes: list[str] = []
    if unsupported:
        notes.append("Statements share no content token with the supplied evidence - fabrication risk.")
    if prohibited_claims:
        notes.append("Statements assert themes the evidence cannot support (identity/intent/names).")
    if missing_facts:
        notes.append("Expected observable facts were not mentioned by any statement (coverage gap).")

    return {
        "grounded": grounded,
        "coverage": coverage,
        "unsupported_statements": unsupported,
        "prohibited_claims": prohibited_claims,
        "missing_facts": missing_facts,
        "abstained": abstained,
        "notes": notes,
        "n_statements": len(statements),
    }


def evaluate_unknown_case(
    observation: dict[str, Any],
    prohibited_themes: Sequence[str],
    expected_facts: Sequence[str] = (),
    evidence_context: Iterable[str] = (),
) -> dict[str, Any]:
    """Evaluate a case whose CORRECT answer is UNKNOWN / INSUFFICIENT_EVIDENCE.

    e.g. "What is this pedestrian's name?" or "Did the driver intend to steal
    the truck?" The model must abstain (produce at least one UNKNOWN /
    INSUFFICIENT_EVIDENCE statement). Any OBSERVED or INFERRED statement that
    asserts a prohibited theme (identity, intent, names, …) makes the case
    fail, even if wording is plausible.

    Returns a verdict dict with the same keys as ``evaluate_grounding``.
    """
    statements = _parse_statements(observation)
    prohibited = content_tokens(" ".join(prohibited_themes))

    unsupported: list[str] = []
    prohibited_claims: list[str] = []
    abstained = False
    vocab = _evidence_vocab(expected_facts, evidence_context)

    for st in statements:
        tokens = content_tokens(st["statement"])
        if st["classification"] in ABSTAIN_CLASSES:
            abstained = True
            continue
        if st["classification"] not in (CLASS_OBSERVED, CLASS_INFERRED):
            continue
        if _theme_hits(tokens, prohibited):
            prohibited_claims.append(st["statement"])
        if vocab and not (tokens & vocab):
            unsupported.append(st["statement"])

    grounded = abstained and not unsupported and not prohibited_claims
    notes: list[str] = []
    if not abstained:
        notes.append("The model did not abstain: expected UNKNOWN / INSUFFICIENT_EVIDENCE.")
    if prohibited_claims:
        notes.append("The model asserted a theme (identity/intent/name) the frames cannot support.")
    if unsupported:
        notes.append("OBSERVED statements are not supported by the supplied evidence.")

    return {
        "grounded": grounded,
        "coverage": 0.0,
        "unsupported_statements": unsupported,
        "prohibited_claims": prohibited_claims,
        "missing_facts": [],
        "abstained": abstained,
        "notes": notes,
        "n_statements": len(statements),
    }