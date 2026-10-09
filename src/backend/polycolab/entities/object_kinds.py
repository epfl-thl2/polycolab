"""Canonical research vocabulary, independent of immutable legacy encodings."""

from enum import StrEnum


class ObjectKind(StrEnum):
    PROBLEM = "PROBLEM"
    STATEMENT = "STATEMENT"
    PROOF = "PROOF"
    DEFINITION = "DEFINITION"
    NOTE = "NOTE"
    FORMALIZATION = "FORMALIZATION"
    ATTEMPT = "ATTEMPT"


class StatementLabel(StrEnum):
    CLAIM = "CLAIM"
    CONJECTURE = "CONJECTURE"
    LEMMA = "LEMMA"
    PROPOSITION = "PROPOSITION"
    THEOREM = "THEOREM"
    COROLLARY = "COROLLARY"


class ProofDirection(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"


LEGACY_KINDS = {
    "CLAIM": "STATEMENT",
    "PROOF_SKETCH": "PROOF",
    "IDEA": "NOTE",
    "DISCUSSION": "NOTE",
    "COUNTEREXAMPLE": "NOTE",
    "COMPUTATION": "NOTE",
}


def canonical_kind(kind: str) -> ObjectKind:
    return ObjectKind(LEGACY_KINDS.get(kind, kind))


def storage_kind(kind: str) -> str:
    """Stable storage codec; never rewrite frozen versions or retry payloads."""
    return {"STATEMENT": "CLAIM", "PROOF": "PROOF_SKETCH"}.get(kind, kind)


KIND_SQL = (
    "CASE kind WHEN 'CLAIM' THEN 'STATEMENT' WHEN 'PROOF_SKETCH' THEN 'PROOF' "
    "WHEN 'IDEA' THEN 'NOTE' WHEN 'DISCUSSION' THEN 'NOTE' "
    "WHEN 'COUNTEREXAMPLE' THEN 'NOTE' WHEN 'COMPUTATION' THEN 'NOTE' ELSE kind END"
)
