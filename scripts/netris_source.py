"""Shared source model for the Netris documentation conversion.

Reads the mirrored Sphinx corpus under ``mirror/`` and exposes:

* the navigation tree declared by the source ``toctree`` directives
* the docname -> title / slug maps used for link rewriting
* the ``:ref:`` label table (``objects.inv`` plus in-file ``.. _label:`` anchors)
* the rendered-HTML tables, which replace ``list-table`` / ``csv-table`` /
  grid-table directives (the ``:file:`` CSVs are not published by Sphinx)
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import zlib
from dataclasses import dataclass, field

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(REPO, "mirror")
RST_DIR = os.path.join(MIRROR, "rst")
HTML_DIR = os.path.join(MIRROR, "html")
SOURCE_BASE = "https://www.netris.io/docs/en/latest"

# Sphinx include fragment, not a page.
NON_PAGE_DOCS = {"_includes/links"}
# Consolidated into the single <Update> changelog timeline.
RELEASE_NOTE_RE = re.compile(r"^release-notes/(?!index$)")

ADORNMENTS = set("=-~^\"'`:.+_*#<>")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def read_rst(docname: str) -> str:
    with open(os.path.join(RST_DIR, docname + ".rst"), encoding="utf-8") as fh:
        return fh.read()


def read_html(docname: str) -> str:
    with open(os.path.join(HTML_DIR, docname + ".html"), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def all_docnames() -> list[str]:
    out = []
    for root, _dirs, files in os.walk(RST_DIR):
        for name in files:
            if name.endswith(".rst"):
                out.append(os.path.relpath(os.path.join(root, name), RST_DIR)[:-4])
    return sorted(out)


#: Characters Mintlify drops from a heading when deriving its anchor id.
_SLUG_DROP = re.compile(r"[()\[\]{}?!,:;\"'`*]")
#: Runs of these become a single hyphen. Note `&`, `/` and em dashes survive.
_SLUG_SEP = re.compile(r"[\s._]+")


def slugify(text: str) -> str:
    """Reproduce Mintlify's heading anchor id.

    Verified against all 651 content headings rendered by `mint dev` across this
    corpus. Mintlify keeps characters that most slug functions strip (`&`, `/`,
    em dash) and converts `.` to a hyphen, so a generic slugifier produces
    anchors that silently miss (`mint broken-links` does not check fragments).
    Run `scripts/check_anchors.py` after any Mintlify upgrade to re-verify.
    """
    text = _html.unescape(text).replace("\u200b", "")
    text = text.strip().lower()
    text = _SLUG_DROP.sub("", text)
    text = _SLUG_SEP.sub("-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def heading_ids(body: str) -> dict[str, str]:
    """``slug -> anchor id`` for one converted page body.

    Mintlify disambiguates repeated headings by appending ``-2``, ``-3``, … in
    document order; the first occurrence keeps the bare slug.
    """
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    body = re.sub(r"(?ms)^[ \t]*(`{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", body)
    # `<Update label="…">` also produces an anchor from its label.
    for m in re.finditer(r'<Update[^>]*\blabel="([^"]+)"', body):
        slug = slugify(m.group(1))
        if slug:
            seen[slug] = seen.get(slug, 0) + 1
            out.setdefault(slug, slug)
    for m in re.finditer(r"(?m)^#{2,6} (.+)$", body):
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1))
        text = re.sub(r"[`*]", "", text)
        slug = slugify(text)
        if not slug:
            continue
        seen[slug] = seen.get(slug, 0) + 1
        anchor = slug if seen[slug] == 1 else f"{slug}-{seen[slug]}"
        out.setdefault(slug, anchor)
        out[f"{slug}#{seen[slug]}"] = anchor
    return out


def normalized_path(docname: str) -> str:
    """Repo-relative MDX slug for a source docname (no extension, no leading /)."""
    if docname == "index":
        return "index"
    parts = docname.split("/")
    parts = [_slug_segment(p) for p in parts]
    return "/".join(parts)


def _slug_segment(seg: str) -> str:
    seg = seg.replace("+", "-plus")
    seg = re.sub(r"[^A-Za-z0-9._-]+", "-", seg)
    seg = re.sub(r"-{2,}", "-", seg).strip("-").lower()
    return seg


# --------------------------------------------------------------------------- #
# titles
# --------------------------------------------------------------------------- #


def _iter_sections(text: str):
    """Yield ``(level_key, title, line_index)`` for every rST section header."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        is_adorn = len(stripped) >= 3 and len(set(stripped)) == 1 and stripped[0] in ADORNMENTS
        if is_adorn and i + 2 < len(lines):
            title = lines[i + 1].strip()
            below = lines[i + 2].strip()
            if (
                title
                and len(below) >= 3
                and len(set(below)) == 1
                and below[0] == stripped[0]
                and len(below) >= len(title) - 2
            ):
                yield ("over:" + stripped[0], title, i)
                i += 3
                continue
        if stripped and i + 1 < len(lines):
            below = lines[i + 1].strip()
            if (
                len(below) >= 3
                and len(set(below)) == 1
                and below[0] in ADORNMENTS
                and len(below) >= len(stripped) - 2
                and not stripped.startswith("..")
                and not stripped.startswith(":")
                and not re.match(r"^[-*+]\s", stripped)
                and not re.match(r"^\|", stripped)
                and len(set(stripped)) != 1
            ):
                yield ("under:" + below[0], stripped, i)
                i += 2
                continue
        i += 1


def source_title(docname: str) -> str:
    """First section title of the document, with substitutions resolved."""
    text = read_rst(docname)
    subs = dict(re.findall(r"^\.\.\s+\|(\w+)\|\s+replace::\s*(.+)$", text, re.M))
    for key, val in subs.items():
        text = text.replace(f"|{key}|", val.strip())
    for _level, title, _idx in _iter_sections(text):
        return _html.unescape(title)
    return docname.rsplit("/", 1)[-1].replace("-", " ").title()


# --------------------------------------------------------------------------- #
# navigation (source toctree)
# --------------------------------------------------------------------------- #


@dataclass
class NavNode:
    docname: str
    children: list["NavNode"] = field(default_factory=list)


@dataclass
class NavSection:
    caption: str
    nodes: list[NavNode]


def _toctrees(docname: str) -> list[tuple[str | None, list[str]]]:
    """Return ``[(caption, [child docname, ...]), ...]`` for one document."""
    text = read_rst(docname)
    base = os.path.dirname(docname)
    lines = text.split("\n")
    out: list[tuple[str | None, list[str]]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)\.\.\s+toctree::\s*$", lines[i])
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        i += 1
        caption = None
        entries: list[str] = []
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            cur = len(line) - len(line.lstrip())
            if cur <= indent:
                break
            s = line.strip()
            if s.startswith(":"):
                fm = re.match(r":caption:\s*(.+)$", s)
                if fm:
                    caption = _html.unescape(fm.group(1).strip())
            else:
                target = s
                if "<" in target and target.endswith(">"):
                    target = target[target.index("<") + 1 : -1]
                target = target.strip()
                if target.endswith(".rst"):
                    target = target[:-4]
                target = target.lstrip("/")
                resolved = os.path.normpath(os.path.join(base, target)) if base else target
                entries.append(resolved)
            i += 1
        out.append((caption, entries))
    return out


def _build_node(docname: str, seen: set[str]) -> NavNode:
    node = NavNode(docname)
    if docname in seen:
        return node
    seen.add(docname)
    for _caption, entries in _toctrees(docname):
        for child in entries:
            node.children.append(_build_node(child, seen))
    return node


def nav_sections() -> list[NavSection]:
    """The source sidebar: ordered caption sections from ``index.rst``."""
    seen: set[str] = {"index"}
    sections = []
    for caption, entries in _toctrees("index"):
        nodes = [_build_node(e, seen) for e in entries]
        sections.append(NavSection(caption or "Documentation", nodes))
    return sections


def flatten(sections: list[NavSection]) -> list[tuple[str, str]]:
    """``[(docname, caption), ...]`` in source sidebar order."""
    out: list[tuple[str, str]] = []

    def walk(node: NavNode, caption: str):
        out.append((node.docname, caption))
        for child in node.children:
            walk(child, caption)

    for section in sections:
        for node in section.nodes:
            walk(node, section.caption)
    return out


# --------------------------------------------------------------------------- #
# :ref: labels
# --------------------------------------------------------------------------- #


def _objects_inv_labels() -> dict[str, tuple[str, str, str]]:
    path = os.path.join(MIRROR, "objects.inv")
    if not os.path.exists(path):
        return {}
    raw = open(path, "rb").read()
    idx = 0
    for _ in range(4):
        idx = raw.index(b"\n", idx) + 1
    data = zlib.decompress(raw[idx:]).decode("utf-8")
    labels = {}
    for line in data.split("\n"):
        if not line.strip():
            continue
        m = re.match(r"^(.+?)\s+(\S+:\S+)\s+(-?\d+)\s+(\S+)\s+(.*)$", line)
        if not m:
            continue
        name, role, _prio, uri, disp = m.groups()
        labels[name.lower()] = (role, uri, disp)
    return labels


def label_map() -> dict[str, str]:
    """``label -> root-absolute target`` (``/path`` or ``/path#anchor``).

    Sphinx anchors and Mintlify anchors are unrelated: `.. _bgp-def:` before a
    section gives Sphinx the id ``bgp-def``, while Mintlify derives the id from
    the heading text. So every label is resolved through the section's *title*
    (``objects.inv``'s dispname), never through the Sphinx anchor in the URI.
    """
    out: dict[str, str] = {}
    for name, (role, uri, disp) in _objects_inv_labels().items():
        if role == "std:doc":
            doc = uri[:-5] if uri.endswith(".html") else uri.rstrip("/")
            out[name] = "/" + normalized_path(doc)
            continue
        page, _, _anchor = uri.partition("#")
        doc = page[:-5] if page.endswith(".html") else page
        target = "/" + normalized_path(doc)
        anchor = slugify(disp) if disp and disp != "-" else ""
        if anchor:
            target += "#" + anchor
        out[name] = target

    # In-file `.. _label:` anchors: Sphinx omits untitled targets from
    # objects.inv, so resolve them against the following section heading.
    for docname in all_docnames():
        if docname in NON_PAGE_DOCS:
            continue
        text = read_rst(docname)
        lines = text.split("\n")
        sections = list(_iter_sections(text))
        for m in re.finditer(r"^\.\.\s+_([^:\s][^:]*):\s*$", text, re.M):
            name = m.group(1).strip().lower()
            if name in out:
                continue
            line_no = text[: m.start()].count("\n")
            following = [s for s in sections if s[2] >= line_no]
            target = "/" + normalized_path(docname)
            if following:
                target += "#" + slugify(following[0][1])
            out[name] = target
        del lines
    return out


def named_links() -> dict[str, str]:
    """Named hyperlink targets, e.g. ``Slack_`` -> the Slack URL."""
    out: dict[str, str] = {}
    for docname in all_docnames():
        text = read_rst(docname)
        for m in re.finditer(r"^\.\.\s+_([^:]+):\s*(https?://\S+)\s*$", text, re.M):
            out[m.group(1).strip().lower().strip("`")] = m.group(2).strip()
    return out


# --------------------------------------------------------------------------- #
# rendered tables
# --------------------------------------------------------------------------- #


def _cell_markdown(cell, inline_fn) -> str:
    """Render one table cell as single-line Markdown."""
    from bs4 import NavigableString, Tag

    parts: list[str] = []

    def walk(node, in_code=False):
        if isinstance(node, NavigableString):
            parts.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        name = node.name
        if name in ("script", "style"):
            return
        if name in ("code", "tt", "span") and "docutils" in (node.get("class") or []) and name != "span":
            parts.append("`" + node.get_text() + "`")
            return
        if name in ("code", "tt"):
            parts.append("`" + node.get_text() + "`")
            return
        if name in ("strong", "b"):
            parts.append("**" + node.get_text().strip() + "**")
            return
        if name in ("em", "i"):
            parts.append("*" + node.get_text().strip() + "*")
            return
        if name == "br":
            parts.append("<br />")
            return
        if name == "a":
            classes = node.get("class") or []
            if "footnote-reference" in classes:
                # Render as a plain superscript marker; the definition is
                # emitted inline by the transformer, so no anchor is needed.
                num = node.get_text().strip().strip("[]")
                parts.append(f"<sup>{num}</sup>")
                return
            href = node.get("href", "")
            label = node.get_text().strip()
            parts.append(f"[{label}]({href})" if href and label else label)
            return
        if name in ("p", "div"):
            if parts and not parts[-1].endswith(("<br />", " ")):
                parts.append("<br />")
            for child in node.children:
                walk(child)
            return
        if name in ("ul", "ol"):
            for li in node.find_all("li", recursive=False):
                parts.append("<br />- " + " ".join(li.get_text(" ", strip=True).split()))
            return
        for child in node.children:
            walk(child)

    for child in cell.children:
        walk(child)
    text = "".join(parts)
    text = re.sub(r"(?:<br />)+", "<br />", text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"^(?:<br />)+", "", text)
    text = re.sub(r"(?:<br />)+$", "", text)
    text = text.replace("|", "\\|")
    return inline_fn(text) if inline_fn else text


def footnote_numbers(docname: str) -> dict[str, str]:
    """``footnote id -> rendered number`` from the built page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read_html(docname), "lxml")
    out: dict[str, str] = {}
    for node in soup.select("aside.footnote, dt.label, .footnote"):
        fid = node.get("id")
        if not fid:
            continue
        label = node.find("span", class_="label") or node
        text = label.get_text(" ", strip=True)
        m = re.search(r"(\d+)", text)
        if m:
            out[fid] = m.group(1)
    return out


def html_tables(docname: str, inline_fn=None) -> list[str]:
    """Every table in the rendered article body, as a Markdown/MDX table."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read_html(docname), "lxml")
    body = soup.find("div", itemprop="articleBody") or soup.find("div", class_="rst-content")
    if body is None:
        return []
    out = []
    for table in body.find_all("table"):
        out.append(_render_table(table, inline_fn))
    return out


def _all_bold(row: list[str]) -> bool:
    cells = [c.strip() for c in row if c and c.strip()]
    if len(cells) < 2:
        return False
    return all(c.startswith("**") and c.endswith("**") for c in cells)


def _render_table(table, inline_fn) -> str:
    for anchor in table.select("a.headerlink"):
        anchor.decompose()
    caption = ""
    cap = table.find("caption")
    if cap is not None:
        caption = " ".join(cap.get_text(" ", strip=True).split())
        cap.extract()

    grid: list[list[str | None]] = []

    def place(row_idx: int, value: str, span: int, rowspan: int):
        while len(grid) <= row_idx + rowspan - 1:
            grid.append([])
        row = grid[row_idx]
        col = 0
        while col < len(row) and row[col] is not None:
            col += 1
        for dr in range(rowspan):
            target = grid[row_idx + dr]
            while len(target) < col:
                target.append(None)
            for dc in range(span):
                while len(target) <= col + dc:
                    target.append(None)
                target[col + dc] = value if (dr == 0 and dc == 0) else ""

    header_rows = 0
    rows = table.find_all("tr")
    for r_i, tr in enumerate(rows):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        if all(c.name == "th" for c in cells) and r_i == header_rows:
            header_rows += 1
        for cell in cells:
            place(
                r_i,
                _cell_markdown(cell, inline_fn),
                int(cell.get("colspan", 1) or 1),
                int(cell.get("rowspan", 1) or 1),
            )

    if not grid:
        return ""
    width = max(len(r) for r in grid)
    for row in grid:
        while len(row) < width:
            row.append("")
        for i, v in enumerate(row):
            if v is None:
                row[i] = ""

    if header_rows == 0 and _all_bold(grid[0]):
        # `:header-rows: 0` with an entirely bold first row is the source
        # author writing a header without declaring one. Promote it rather
        # than emitting an empty Markdown header band.
        header = [c.strip().strip("*") for c in grid[0]]
        data = grid[1:]
    elif header_rows == 0:
        # Source renders these borderless and header-free. Markdown requires a
        # delimiter row, so emit an empty header rather than inventing labels.
        header = [""] * width
        data = grid
    elif header_rows == 1:
        header = grid[0]
        data = grid[1:]
    else:
        header = [
            " ".join(x for x in (grid[r][c] for r in range(header_rows)) if x).strip()
            for c in range(width)
        ]
        data = grid[header_rows:]

    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in data:
        lines.append("| " + " | ".join(row) + " |")
    out = "\n".join(lines)
    if caption:
        out = f"**{caption}**\n\n" + out
    return out
