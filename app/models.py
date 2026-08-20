"""
Model backend.

Two implementations behind one interface:

  OpenAIBackend   - used when OPENAI_API_KEY is present
  OfflineBackend  - deterministic rule tables, so the whole test suite runs
                    without network access or a key

The split is not just convenience. It forces every model call to have a
declared, checkable contract: if a deterministic fallback cannot be written for
a call, that call is doing reasoning that belongs in the solver, not the model.
That constraint is what keeps the architecture honest.

Set OPENAI_API_KEY to switch to live calls. Nothing else changes.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

MODEL_TEXT = os.environ.get("VESTED_MODEL", "gpt-5")
MODEL_VISION = os.environ.get("VESTED_MODEL_VISION", "gpt-5")


class Backend(Protocol):
    name: str

    def available(self) -> bool: ...
    def transliterate(self, text: str) -> str: ...
    def classify_narration(self, narration: str) -> dict: ...
    def draft(self, system: str, user: str) -> str: ...


# ---------------------------------------------------------------------------
# Offline backend
# ---------------------------------------------------------------------------

# Devanagari -> Latin. Deliberately conservative: it produces a canonical
# spelling, not a pretty one, because downstream comparison is on token shape.
_INDEP = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri",
}
_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
_MATRA = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri",
}
_HALANT = "्"
_NUKTA = "़"
_ANUSVARA = "ं"
_CHANDRA = "ँ"


def _translit_offline(text: str) -> str:
    if not re.search(r"[ऀ-ॿ]", text):
        return text
    out: list[str] = []
    chars = [c for c in text if c not in (_NUKTA,)]
    i = 0
    while i < len(chars):
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if ch in _CONS:
            out.append(_CONS[ch])
            if nxt in _MATRA:
                out.append(_MATRA[nxt])
                i += 2
                continue
            if nxt == _HALANT:
                i += 2
                continue
            out.append("a")  # inherent vowel
            i += 1
            continue
        if ch in _INDEP:
            out.append(_INDEP[ch])
            i += 1
            continue
        if ch in (_ANUSVARA, _CHANDRA):
            # The anusvara is a nasal whose romanisation depends on what
            # follows. Before a velar or ह it is conventionally written "ng"
            # on Indian documents - which is why सिंह is spelled "Singh" and
            # not "Sinh". Getting this wrong makes Singh and Sinha collide.
            if nxt in ("क", "ख", "ग", "घ", "ह"):
                out.append("ng")
            elif nxt in ("प", "फ", "ब", "भ", "म"):
                out.append("m")
            else:
                out.append("n")
            i += 1
            continue
        if ch.isspace():
            out.append(" ")
            i += 1
            continue
        i += 1
    # Trim the trailing inherent vowel Hindi drops in speech (schwa deletion).
    words = [re.sub(r"a$", "", w) if len(w) > 3 else w for w in "".join(out).split()]
    return " ".join(w for w in words if w)


_SALARY_HINTS = re.compile(
    r"\b(sal|salary|sala|payroll|wages?|stipend|remun)\b", re.I)
_NON_SALARY = re.compile(
    r"\b(interest|int\.?cr|dividend|refund|reversal|cashback|upi|atm|"
    r"chq|cheque|emi|loan|insurance|premium)\b", re.I)


class OfflineBackend:
    name = "offline"

    def available(self) -> bool:
        return True

    def transliterate(self, text: str) -> str:
        return _translit_offline(text)

    def classify_narration(self, narration: str) -> dict:
        is_sal = bool(_SALARY_HINTS.search(narration)) and not _NON_SALARY.search(narration)
        # Employer guess: longest alphabetic run that is not a known noise token.
        parts = [p for p in re.split(r"[^A-Za-z&]+", narration) if len(p) > 3]
        noise = {"NEFT", "IMPS", "RTGS", "SALARY", "SAL", "CREDIT", "TRANSFER"}
        cands = [p for p in parts if p.upper() not in noise]
        return {
            "is_salary": is_sal,
            "employer_hint": max(cands, key=len) if cands else None,
            "confidence": 0.75 if is_sal else 0.6,
        }

    def draft(self, system: str, user: str) -> str:
        # No generation offline. The claim gate is exercised separately with
        # adversarial fixtures, so nothing depends on this path producing prose.
        return ""


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

class OpenAIBackend:
    """
    UNUSED IN THIS BUILD, DELIBERATELY.

    The prototype ships local-only: no API key is configured, so every result
    is deterministic and nothing a member uploads leaves the server. That is a
    stronger privacy claim than any wording could be, and it makes every output
    reproducible.

    This class is kept as a working extension point, not as a claimed
    capability. It has never been executed against the live API - the model id,
    the strict-schema call shape and the error handling are all unverified.
    Before relying on it, run `python app/models.py` with a key set and expect
    to fix something.
    """

    name = "openai"

    def __init__(self) -> None:
        from openai import OpenAI
        self._client = OpenAI()

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def _json_call(self, system: str, user: str, schema: dict) -> dict:
        resp = self._client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        )
        return json.loads(resp.choices[0].message.content)

    def transliterate(self, text: str) -> str:
        """
        Romanise an Indian-language name. The model NORMALISES only - it is
        never asked whether two names match. That decision stays in the
        deterministic aligner so it can be cross-examined.
        """
        if not re.search(r"[ऀ-ॿ਀-ൿ]", text):
            return text
        out = self._json_call(
            system=(
                "You romanise Indian personal names. Return the most common "
                "Latin spelling used on Indian identity documents. Preserve "
                "token order and count exactly. Do not translate, expand "
                "initials, add honorifics, or correct spelling."
            ),
            user=text,
            schema={
                "type": "object",
                "properties": {"romanised": {"type": "string"}},
                "required": ["romanised"],
                "additionalProperties": False,
            },
        )
        return out["romanised"]

    def classify_narration(self, narration: str) -> dict:
        return self._json_call(
            system=(
                "Classify a single Indian bank statement narration. Decide "
                "whether it represents a salary credit, and extract the paying "
                "employer's name if present. Return employer_hint null if no "
                "employer name is discernible. Do not guess."
            ),
            user=narration,
            schema={
                "type": "object",
                "properties": {
                    "is_salary": {"type": "boolean"},
                    "employer_hint": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["is_salary", "employer_hint", "confidence"],
                "additionalProperties": False,
            },
        )

    def draft(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------

SELFTEST_CASES = {
    "transliterate": [
        ("राहुल कुमार सिंह", lambda r: r.isascii() and "singh" in r.lower()),
        ("प्रिया शर्मा", lambda r: r.isascii() and len(r.split()) == 2),
        ("RAHUL SINGH", lambda r: r == "RAHUL SINGH"),  # passthrough, no call
    ],
    "classify_narration": [
        ("NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY JUN21",
         lambda r: r["is_salary"] is True),
        ("INT.CR QUARTERLY INTEREST CREDIT", lambda r: r["is_salary"] is False),
        ("UPI/P2A/408123456789/RENT", lambda r: r["is_salary"] is False),
    ],
}


def selftest(backend: Backend) -> int:
    """
    Exercise every model call against its contract.

    Run this the moment a real key is available - it is the only thing that
    proves the live path works. Code that has never executed is not working
    code, however well typed.
    """
    print(f"backend: {backend.name}")
    failures = 0
    for method, cases in SELFTEST_CASES.items():
        fn = getattr(backend, method)
        for arg, check in cases:
            label = arg if len(arg) < 46 else arg[:43] + "..."
            try:
                out = fn(arg)
                ok = check(out)
            except Exception as e:
                print(f"  ERROR {method:20} {label}")
                print(f"        {type(e).__name__}: {str(e)[:140]}")
                failures += 1
                continue
            print(f"  {'PASS ' if ok else 'FAIL '} {method:20} {label}")
            if not ok:
                print(f"        returned: {out!r}")
                failures += 1
    print(f"\n{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    return failures


_backend: Backend | None = None


def get_backend(force: str | None = None) -> Backend:
    global _backend
    if force == "offline":
        return OfflineBackend()
    if _backend is None:
        if os.environ.get("OPENAI_API_KEY"):
            try:
                _backend = OpenAIBackend()
            except Exception:
                _backend = OfflineBackend()
        else:
            _backend = OfflineBackend()
    return _backend


if __name__ == "__main__":
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    force = "offline" if "--offline" in _sys.argv else None
    _sys.exit(selftest(get_backend(force)))
