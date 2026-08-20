"""
Stylesheet minification, done once at import.

The CSS is inlined into every page, so its bytes are paid on every request -
and this product's whole premise is that it has to work on a slow connection.
But the comments in that stylesheet explain decisions a reader of this
repository should be able to see, and stripping them from the source to save
bandwidth would be trading the wrong thing.

So the source keeps its comments and its indentation, and this runs once when
the module loads.
"""

from __future__ import annotations

# Characters that already imply a break, so a space beside them is decoration.
_PUNCT = "{};:,>+~"


def minify(css: str) -> str:
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        ch = css[i]

        # Quoted strings are stepped over intact. `content:` carries real text
        # that is shown to the reader, and collapsing whitespace inside it
        # would change what the page says.
        if ch in ("'", '"'):
            j = i + 1
            while j < n and css[j] != ch:
                j += 2 if css[j] == "\\" else 1
            out.append(css[i:j + 1])
            i = j + 1
            continue

        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue

        if ch.isspace():
            j = i
            while j < n and css[j].isspace():
                j += 1
            prev = out[-1][-1] if out and out[-1] else ""
            nxt = css[j] if j < n else ""
            # Between two values a space is load-bearing:
            #   clamp(32px, 7vw, 44px)   1px solid var(--line)
            # Next to punctuation it is not.
            if prev and nxt and prev not in _PUNCT and nxt not in _PUNCT:
                out.append(" ")
            i = j
            continue

        # The final semicolon in a block is optional, and there is one per rule.
        if ch == "}" and out and out[-1] == ";":
            out.pop()

        out.append(ch)
        i += 1

    return "".join(out).strip()


def _self_test() -> int:
    cases = [
        ("a { color : red ; }", "a{color:red}", "spaces around punctuation go"),
        ("a{margin:0 0 14px}", "a{margin:0 0 14px}", "spaces between values stay"),
        ("a{font-size:clamp(32px, 7vw, 44px)}",
         "a{font-size:clamp(32px,7vw,44px)}", "commas collapse inside functions"),
        ("/* note */\na{color:red}", "a{color:red}", "comments are removed"),
        ('a::after{content:"one  two"}', 'a::after{content:"one  two"}',
         "text inside quotes is untouched"),
        ('a::after{content:"a" "b"}', 'a::after{content:"a" "b"}',
         "adjacent strings keep their separator"),
        ("a{border:1px solid var(--line)}", "a{border:1px solid var(--line)}",
         "shorthand values survive"),
        ("@media print{ a{color:#000} }", "@media print{a{color:#000}}",
         "at-rules survive"),
    ]
    bad = 0
    print("=" * 62)
    print("  css minifier")
    for src, want, label in cases:
        got = minify(src)
        ok = got == want
        bad += not ok
        print(f"    {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            print(f"          wanted {want!r}\n             got {got!r}")
    print(f"\n  {len(cases)} checks · RESULT: {'ALL PASS' if not bad else f'{bad} FAILURE(S)'}")
    print("=" * 62)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
