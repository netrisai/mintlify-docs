"""/preview-qa Gate 1.5 — port-artifact sweep.

Every check must report zero hits. These are the malformed-but-parseable shapes
that `mint validate` accepts and that render as visibly broken cards, steps,
code blocks or admonitions, documented in
``mstack/plugins/mstack/skills/docs-to-mintlify/references/mdx-conversion.md``,
plus source-specific checks for leftover reStructuredText.

    python3 scripts/port_artifact_sweep.py [--verbose]
"""

from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "mstack", "node_modules", "mirror", ".mintlify"}

EMOJI = "\U0001F000-\U0001FFFF\u2600-\u27bf\u2190-\u21ff\u2b00-\u2bff\ufe0f"

# Tags the conversion emits on purpose, plus the landing page's own JSX.
ALLOWED_TAGS = {
    "br", "img", "sup", "sub", "div", "span", "section", "a", "p", "h1", "h2",
    "h3", "h4", "h5", "h6", "svg", "path", "ul", "li", "strong", "em", "button",
}


def mdx_files() -> list[str]:
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".mdx"):
                out.append(os.path.join(root, name))
    return sorted(out)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)


def strip_code(text: str) -> str:
    """Remove fenced blocks (including indented fences) and inline code."""
    text = re.sub(r"(?ms)^[ \t]*(`{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


CHECKS: list[tuple[str, callable]] = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn

    return deco


@check("A  broken-card link smash (multi-line)")
def _a(text, prose):
    return re.search(rf"\[\s*[{EMOJI}][^\]]*?####[^\]]*?\]\([^)]+\)", text, re.S)


@check("B  inline emoji card")
def _b(text, prose):
    return re.search(rf"\[[{EMOJI}]+\s*[A-Z][^\]]+\]\([^)]+\)", text)


@check("C  broken Steps (link-wrapped numbers)")
def _c(text, prose):
    return re.search(r"\[\s*\d+\s*\n\s*\n\s*###[^\]]+\]\([^)]+\)", text, re.S)


@check("D  orphan emoji + heading + body")
def _d(text, prose):
    return re.search(rf"^[{EMOJI}]\s*\n\s*\n####\s", text, re.M)


@check("E  prism-code fences")
def _e(text, prose):
    return "```prism-code" in text


@check("F  admonition prefix leaked into frontmatter")
def _f(text, prose):
    return re.search(r'^description:\s*"?:::', text, re.M)


@check("G  angle-bracket placeholder leakage in prose")
def _g(text, prose):
    if re.search(r"&lt;[^&\s]{1,40}&gt;", prose):
        return True
    for m in re.finditer(r"(?<![\w`])</?([A-Za-z][A-Za-z0-9_.-]*)[^>]*>", prose):
        tag = m.group(1)
        if tag in ALLOWED_TAGS or tag[0].isupper():
            continue
        return True
    return False


@check("H  orphan --- horizontal rules")
def _h(text, prose):
    return re.search(r"^---\s*\n\s*\n---", strip_frontmatter(text), re.M)


@check("J  source chrome leakage")
def _j(text, prose):
    return re.search(
        r"^(Copy page|Edit on GitHub|Was this helpful|Next|Previous|Built with Sphinx)\s*$",
        prose,
        re.M,
    )


@check("rST directive leakage (.. name::)")
def _rst_directive(text, prose):
    return re.search(r"^\s*\.\. +[a-z][a-z0-9_-]*::", prose, re.M)


@check("rST role leakage (:doc:/:ref:/:guilabel:)")
def _rst_role(text, prose):
    return re.search(r":(doc|ref|guilabel|menuselection|term):`", prose)


@check("rST section adornment leakage")
def _rst_adorn(text, prose):
    return re.search(r"^(=|~|\^|\+|\"){4,}\s*$", prose, re.M)


@check("rST footnote/target syntax leakage")
def _rst_target(text, prose):
    return re.search(r"^\.\. _\S|\]_(?![\w])", prose, re.M)


@check("unresolved substitution (|name|)")
def _subs(text, prose):
    return re.search(r"\|[a-z][a-z0-9_]*\|", prose)


@check("empty alt attributes")
def _alt(text, prose):
    return 'alt=""' in text


@check("internal .md / .mdx / .html link extensions")
def _ext(text, prose):
    return re.search(r"\]\(/[^)]*\.(md|mdx|html)([)#])", text)


@check("transformer placeholder leakage (control chars)")
def _ctrl(text, prose):
    return re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text)


@check("component tag sharing a line with prose")
def _tag_prose(text, prose):
    return re.search(
        r"(?m)^\s*</?(Note|Tip|Warning|Info|Danger|Check|Accordion|AccordionGroup"
        r"|Tabs|Tab|Frame|Steps|Step|CardGroup|Card|Update)\b[^\n]*>[ \t]+\S",
        text,
    )


@check("unbalanced Mintlify component tags")
def _balance(text, prose):
    for tag in (
        "Note", "Tip", "Warning", "Info", "Danger", "Check", "Accordion",
        "AccordionGroup", "Tabs", "Tab", "Frame", "Steps", "Step", "CardGroup",
        "Card", "Update",
    ):
        opens = len(re.findall(rf"<{tag}(?=[\s>])(?![^>]*/>)", text))
        closes = len(re.findall(rf"</{tag}>", text))
        if opens != closes:
            return f"{tag}: {opens} open / {closes} close"
    return False


def main() -> int:
    verbose = "--verbose" in sys.argv
    files = mdx_files()
    results: dict[str, list[str]] = {name: [] for name, _fn in CHECKS}
    for path in files:
        text = read(path)
        prose = strip_code(strip_frontmatter(text))
        for name, fn in CHECKS:
            hit = fn(text, prose)
            if hit:
                detail = hit if isinstance(hit, str) else ""
                rel = os.path.relpath(path, REPO)
                results[name].append(f"{rel} {detail}".strip())

    print(f"Port-artifact sweep (preview-qa Gate 1.5) — {len(files)} MDX files")
    failed = 0
    for name, _fn in CHECKS:
        hits = results[name]
        status = "PASS" if not hits else "FAIL"
        if hits:
            failed += 1
        print(f"  {status}  {name:<52} {len(hits)}")
        if hits and (verbose or len(hits) <= 6):
            for h in hits[:12]:
                print(f"          {h}")
    print()
    print("Gate 1.5: " + ("PASS" if failed == 0 else "FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
