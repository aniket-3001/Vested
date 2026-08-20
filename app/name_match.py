"""
Person-name matching across scripts and documents.

Why this is on the critical path: your name is typed independently into Aadhaar,
PAN, EPFO and now ABHA, by different clerks, in different scripts, years apart.
The UAN-ABHA linkage auto-rejects mismatched names as suspected identity fraud,
and name mismatch is a leading cause of PF claim rejection generally. Record
linkage across three documents is impossible if the person cannot be matched
across them first.

Division of labour, following the project thesis:

    The model NORMALISES.  The algorithm DECIDES.

The model romanises Devanagari - a genuine language task where rules are weak.
It is never asked "are these the same person", because that verdict must be
auditable and contestable. A member has to be able to argue with a specific
step, and a model cannot be cross-examined.

The decision rule rests on one observation: Indian name spelling varies enormously
in VOWELS (Rahul / Rahool / Raahul) and barely at all in CONSONANT SKELETON.
Singh and Sinha are different surnames; Rahul and Rahool are one name.
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import re
from dataclasses import dataclass, field

from app.models import Backend, get_backend

HONORIFICS = {
    "SHRI", "SHREE", "SRI", "SMT", "SHRIMATI", "KUM", "KUMARI", "MR", "MRS",
    "MS", "DR", "PROF", "LATE", "M/S", "SH",
}

# Aspirate digraphs are single consonant units - this is what separates
# SINGH (S-N-GH) from SINHA (S-N-H).
DIGRAPHS = ["CHH", "KSH", "BH", "CH", "DH", "GH", "JH", "KH", "PH", "SH", "TH", "ZH"]

# Spelling variants that carry no phonetic difference on Indian documents.
EQUIV = {"W": "V", "F": "PH", "Z": "J", "X": "KS", "Q": "K"}

VOWELS = set("AEIOU")


def _strip_vowels_to_skeleton(word: str) -> str:
    w = word.upper()
    for src, dst in EQUIV.items():
        w = w.replace(src, dst)
    out: list[str] = []
    i = 0
    while i < len(w):
        matched = False
        for d in DIGRAPHS:
            if w.startswith(d, i):
                out.append(d)
                i += len(d)
                matched = True
                break
        if matched:
            continue
        c = w[i]
        if c not in VOWELS and c.isalpha():
            out.append(c)
        i += 1
    skeleton = "".join(out)
    # A name that is all vowels (rare, e.g. "IA") keeps its letters.
    return skeleton or w


# Vowels vary in LENGTH and in the u/o, i/e pairs that Indian romanisation
# treats as interchangeable - but an ADDED vowel is a different syllable, and
# usually a different name. Joshi and Joshua share the skeleton JSH; only the
# vowel sequence separates them.
VOWEL_CLASS = {"A": "A", "E": "I", "I": "I", "O": "U", "U": "U"}


def _vowel_signature(word: str) -> str:
    w = word.upper()
    for src, dst in EQUIV.items():
        w = w.replace(src, dst)
    w = re.sub(r"([AEIOU])\1+", r"\1", w)  # collapse lengthening: OO -> O
    return "".join(VOWEL_CLASS[c] for c in w if c in VOWELS)


def _signature(word: str) -> str:
    """Full comparison key: consonant skeleton plus vowel-class sequence."""
    return f"{_strip_vowels_to_skeleton(word)}|{_vowel_signature(word)}"


@dataclass
class NameMatch:
    same_person: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    normalised: tuple[str, str] = ("", "")

    def explain(self) -> str:
        return "; ".join(self.reasons)


def normalise(raw: str, backend: Backend) -> list[str]:
    text = backend.transliterate(raw)
    text = re.sub(r"[^A-Za-z\s.]", " ", text).upper()
    tokens = [t.strip(".") for t in text.split() if t.strip(".")]
    return [t for t in tokens if t not in HONORIFICS]


def _is_initial(tok: str) -> bool:
    return len(tok) == 1


def compare(a_raw: str, b_raw: str, backend: Backend | None = None) -> NameMatch:
    backend = backend or get_backend()
    a = normalise(a_raw, backend)
    b = normalise(b_raw, backend)
    norm = (" ".join(a), " ".join(b))

    if not a or not b:
        return NameMatch(False, 0.0, ["one name is empty after normalisation"], norm)

    a_words = [t for t in a if not _is_initial(t)]
    b_words = [t for t in b if not _is_initial(t)]
    a_inits = [t for t in a if _is_initial(t)]
    b_inits = [t for t in b if _is_initial(t)]

    if not a_words or not b_words:
        return NameMatch(False, 0.0, ["a name consists only of initials"], norm)

    a_sk = {w: _signature(w) for w in a_words}
    b_sk = {w: _signature(w) for w in b_words}

    reasons: list[str] = []

    # --- 1. the given name must be present on both sides --------------------
    # The first full word is the given name in every ordering convention that
    # matters here, including South Indian initial-first forms.
    if a_sk[a_words[0]] != b_sk[b_words[0]]:
        # Allow for the case where one side leads with an expanded initial.
        lead_ok = (
            (a_inits and b_words and a_inits[0] == b_words[0][0]) or
            (b_inits and a_words and b_inits[0] == a_words[0][0])
        )
        if not lead_ok and a_sk[a_words[0]] not in b_sk.values():
            return NameMatch(
                False, 0.15,
                [f"given names differ: {a_words[0]} vs {b_words[0]}"], norm)
    else:
        if a_words[0] != b_words[0]:
            reasons.append(f"given name spelling varies ({a_words[0]}/{b_words[0]}), "
                           f"same consonant skeleton")
        else:
            reasons.append("given name matches exactly")

    # --- 2. the surname is strict -------------------------------------------
    # This is where false positives become dangerous, so it is the tightest rule.
    a_sur, b_sur = a_words[-1], b_words[-1]
    if len(a_words) > 1 and len(b_words) > 1:
        if a_sk[a_sur] != b_sk[b_sur]:
            return NameMatch(
                False, 0.1,
                [f"surnames are different names: {a_sur} vs {b_sur}"], norm)
        if a_sur != b_sur:
            reasons.append(f"surname spelling varies ({a_sur}/{b_sur}), same skeleton")
        else:
            reasons.append("surname matches exactly")
    elif len(a_words) == 1 or len(b_words) == 1:
        reasons.append("one document records no surname")

    # --- 3. middle components ------------------------------------------------
    a_mid = {a_sk[w] for w in a_words[1:-1]} if len(a_words) > 2 else set()
    b_mid = {b_sk[w] for w in b_words[1:-1]} if len(b_words) > 2 else set()
    only_a, only_b = a_mid - b_mid, b_mid - a_mid

    if only_a and only_b:
        return NameMatch(
            False, 0.2,
            reasons + [f"conflicting middle names: {sorted(only_a)} vs {sorted(only_b)}"],
            norm)

    dropped = only_a or only_b
    if dropped:
        # A middle name present on one document and absent on the other is
        # normal - unless the other side has an initial that contradicts it.
        other_inits = b_inits if only_a else a_inits
        missing = sorted(dropped)[0]
        if other_inits and not any(i == missing[0] for i in other_inits):
            reasons.append(
                f"middle name {missing} recorded on one document only, and the "
                f"other document's initial does not match it")
            return NameMatch(False, 0.35, reasons, norm)
        reasons.append(f"middle name recorded on one document only (normal variation)")

    # --- 4. initials must not contradict -------------------------------------
    # An initial is only a contradiction when the OTHER document records a
    # middle name that this initial fails to match. An initial standing for a
    # component the other document simply omits (RAHUL K SINGH vs RAHUL SINGH)
    # is the same ordinary variation as a dropped middle name.
    def _initial_conflict(inits: list[str], other_words: list[str]) -> str | None:
        other_mid = other_words[1:-1] if len(other_words) > 2 else []
        if not other_mid:
            return None
        for i in inits:
            if not any(w[0] == i for w in other_mid):
                return i
        return None

    for inits, other in ((a_inits, b_words), (b_inits, a_words)):
        clash = _initial_conflict(inits, other)
        if clash:
            reasons.append(
                f"initial {clash}. does not match the middle name recorded on "
                f"the other document")
            return NameMatch(False, 0.4, reasons, norm)
    if a_inits or b_inits:
        reasons.append("initials are consistent with the expanded name")

    exact = (a == b)
    return NameMatch(True, 0.99 if exact else (0.85 if not dropped else 0.75),
                     reasons, norm)


def worst_pair(names: dict[str, str], backend: Backend | None = None):
    """
    Compare every document's spelling against every other and return the
    weakest link - that is the one EPFO or ABHA will reject on.
    """
    backend = backend or get_backend()
    keys = list(names)
    worst = None
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            m = compare(names[keys[i]], names[keys[j]], backend)
            if worst is None or m.confidence < worst[2].confidence:
                worst = (keys[i], keys[j], m)
    return worst
