"""Content-parity checker: compares converted MDX against the rendered source.

Normalises both sides to a bag of words / lines and reports content present on
the source page but missing from the converted page (and vice versa). Run:

    python3 scripts/parity_check.py [--verbose] [docname ...]
"""

from __future__ import annotations

import html as _html
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import netris_source as S  # noqa: E402

REPO = S.REPO

# Source chrome / theme boilerplate that never belongs in the converted body.
CHROME = re.compile(
    r"^(Next|Previous|Toggle|Read the Docs|Built with Sphinx|©|Copyright|Search|Table of Contents"
    r"|Bases:|You are browsing|Join Slack|Netris Documentation|latest|stable)",
    re.I,
)


def source_text(docname: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(S.read_html(docname), "lxml")
    body = soup.find("div", itemprop="articleBody") or soup.find("div", class_="rst-content")
    if body is None:
        return ""
    for sel in (
        "a.headerlink",
        ".admonition-title",
        "div.toctree-wrapper",
        "div.contents",
        "nav.contents",
        "#table-of-contents",
        "p.topic-title",
        "footer",
        "div.rst-footer-buttons",
        "div.related",
        "button",
        "span.linenos",
        "div.highlight button",
    ):
        for node in body.select(sel):
            node.decompose()
    for node in body.select("div.topic"):
        if "contents" in (node.get("class") or []):
            node.decompose()
    return body.get_text("\n")


def mdx_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fm = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    visible_fm = ""
    if fm:
        for key in ("title", "sidebarTitle", "description"):
            m = re.search(rf'^{key}:\s*"?(.*?)"?\s*$', fm.group(1), re.M)
            if m:
                visible_fm += m.group(1) + "\n"
        text = text[fm.end() :]
    text = re.sub(r"^\{/\*.*?\*/\}\s*$", "", text, flags=re.M | re.S)
    # Attribute values (caption=, alt=, title=, label=, description=) are visible text.
    attrs = "\n".join(
        (m.group(1) or m.group(2) or "")
        for m in re.finditer(
            r'(?:caption|alt|title|label|description)=(?:"([^"]*)"|\'([^\']*)\')', text
        )
    )
    # Fenced code is compared verbatim; only prose goes through tag stripping,
    # because placeholders like `<bucket-name>` inside code are real content.
    fences: list[str] = []

    def hide_fence(m):
        fences.append(m.group(0))
        return f"\x01F{len(fences) - 1}\x01"

    text = re.sub(r"(?ms)^[ \t]*(`{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", hide_fence, text)
    # Strip only real markup: HTML tags and Mintlify components. A bare
    # `<placeholder>` is content, not a tag, and must survive the comparison.
    text = re.sub(
        r"</?(?:[A-Z][A-Za-z0-9]*|br|img|sup|sub|div|span|section|a|p|h[1-6]|svg|path"
        r"|ul|ol|li|strong|em|button|table|thead|tbody|tr|td|th|code|pre)\b[^>]*/?>",
        " ",
        text,
    )
    text = re.sub(r"\x01F(\d+)\x01", lambda m: fences[int(m.group(1))], text)
    text = visible_fm + attrs + "\n" + text
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = re.sub(r"\\([{}])", r"\1", text)
    return text


# Tokenise aggressively: the source's syntax highlighter splits identifiers
# across <span> boundaries, so any punctuation-joined token must be split on
# both sides to compare like with like.
WORD = re.compile(r"[A-Za-z0-9]+")


# The changelog renders `Sep/02/2026`-style source titles as `September 2, 2026`
# in the <Update> label, so canonicalise month names and zero-padding on both
# sides of the comparison.
MONTH_CANON = {
    m[:3].lower(): m.lower()
    for m in (
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    )
}


def _canon(word: str) -> str:
    word = word.lower()
    word = MONTH_CANON.get(word, word)
    if word.isdigit():
        word = str(int(word))
    return word


def words(text: str) -> Counter:
    text = _html.unescape(text)
    text = re.sub(r"[`*|#>\[\]()!]", " ", text)
    out = Counter()
    for line in text.split("\n"):
        line = line.strip()
        if not line or CHROME.match(line):
            continue
        for w in WORD.findall(line):
            out[_canon(w)] += 1
    return out


def compare(docname: str, mdx_path: str):
    src = words(source_text(docname))
    dst = words(mdx_text(mdx_path))
    missing = Counter()
    for w, c in src.items():
        gap = c - dst.get(w, 0)
        if gap > 0:
            missing[w] = gap
    extra = Counter()
    for w, c in dst.items():
        gap = c - src.get(w, 0)
        if gap > 0:
            extra[w] = gap
    return sum(src.values()), missing, extra


def main() -> int:
    verbose = "--verbose" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    docs = args or [
        d for d in S.all_docnames() if d not in S.NON_PAGE_DOCS and d != "index"
    ]
    rows = []
    for doc in docs:
        if doc.startswith("release-notes/"):
            # Consolidated into the single <Update> timeline page.
            mdx = os.path.join(REPO, "release-notes.mdx")
        else:
            mdx = os.path.join(REPO, S.normalized_path(doc) + ".mdx")
        if not os.path.exists(mdx):
            print(f"MISSING FILE  {doc} -> {mdx}")
            continue
        total, missing, extra = compare(doc, mdx)
        lost = sum(missing.values())
        pct = 100.0 * (1 - lost / total) if total else 100.0
        rows.append((pct, lost, total, doc, missing, extra))
    rows.sort()
    print(f"{'coverage':>9}  {'lost':>6}  {'words':>6}  page")
    for pct, lost, total, doc, missing, extra in rows:
        flag = "  <-- CHECK" if pct < 99.0 else ""
        print(f"{pct:8.2f}%  {lost:6d}  {total:6d}  {doc}{flag}")
        if verbose and missing:
            print("      missing:", ", ".join(f"{w}x{c}" for w, c in missing.most_common(25)))
    worst = [r for r in rows if r[0] < 99.0]
    print(f"\npages below 99% word coverage: {len(worst)} / {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
