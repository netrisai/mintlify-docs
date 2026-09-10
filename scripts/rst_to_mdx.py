"""Deterministic reStructuredText -> Mintlify MDX transformer for the Netris docs.

Re-run this script after any rule change instead of hand-patching generated
output. Usage:

    python3 scripts/rst_to_mdx.py

Reads the mirrored corpus in ``mirror/`` and writes ``.mdx`` pages, ``docs.json``
navigation and ``parity-manifest.json`` into the repository root.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import netris_source as S  # noqa: E402

REPO = S.REPO

ADORNMENTS = S.ADORNMENTS

CALLOUTS = {
    "note": "Note",
    "tip": "Tip",
    "warning": "Warning",
    "important": "Info",
    "caution": "Warning",
    "seealso": "Info",
    "attention": "Warning",
    "danger": "Danger",
    "hint": "Tip",
    "error": "Danger",
}

LANG_MAP = {
    "shell-session": "shell",
    "shell": "shell",
    "bash": "bash",
    "console": "shell",
    "yaml": "yaml",
    "json": "json",
    "ini": "ini",
    "text": "text",
    "python": "python",
    "sql": "sql",
    "hcl": "hcl",
    "go": "go",
    "": "text",
}

TABLE_MARK = "\x00TBL{}\x00"

# Sphinx directives that carry no visible output in a Mintlify build.
DROP_DIRECTIVES = {"meta", "toctree", "contents", "include", "highlight", "sectionauthor", "index"}


# --------------------------------------------------------------------------- #
# link + inline handling
# --------------------------------------------------------------------------- #


class Links:
    def __init__(self):
        self.labels = S.label_map()
        self.named = S.named_links()
        self.doc_titles: dict[str, str] = {}
        self.doc_paths: dict[str, str] = {}
        for doc in S.all_docnames():
            if doc in S.NON_PAGE_DOCS:
                continue
            self.doc_titles[doc] = S.source_title(doc)
            self.doc_paths[doc] = "/" + S.normalized_path(doc)
        # Release notes are consolidated into one <Update> timeline page.
        for doc in list(self.doc_paths):
            if S.RELEASE_NOTE_RE.match(doc):
                anchor = _release_anchor(self.doc_titles[doc])
                self.doc_paths[doc] = "/release-notes#" + anchor
        self.doc_paths["release-notes/index"] = "/release-notes"
        for name, target in list(self.labels.items()):
            m = re.match(r"^/release-notes/(.+?)(#.*)?$", target)
            if m:
                doc = "release-notes/" + m.group(1)
                if doc in self.doc_titles:
                    self.labels[name] = "/release-notes#" + _release_anchor(self.doc_titles[doc])

    def doc_target(self, base_doc: str, target: str) -> tuple[str, str]:
        """Resolve a ``:doc:`` target relative to ``base_doc``."""
        target = target.strip()
        if target.startswith("/"):
            doc = target.lstrip("/")
        else:
            base = os.path.dirname(base_doc)
            doc = os.path.normpath(os.path.join(base, target)) if base else target
        doc = doc.replace("\\", "/")
        # Sphinx clamps `../` that would escape the source root.
        while doc.startswith("../"):
            doc = doc[3:]
        if doc.endswith(".rst"):
            doc = doc[:-4]
        if doc in self.doc_paths:
            return self.doc_paths[doc], self.doc_titles.get(doc, doc)
        return "/" + S.normalized_path(doc), doc


def _release_anchor(title: str) -> str:
    """Anchor for an entry inside the consolidated changelog timeline."""
    label = _release_label(title)
    return S.slugify(label)


def _release_label(title: str) -> str:
    m = re.search(r"\(([^)]+)\)\s*$", title)
    if not m:
        return title
    return _pretty_date(m.group(1))


MONTHS = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "oct": "October", "nov": "November", "dec": "December",
}


def _pretty_date(raw: str) -> str:
    m = re.match(r"^([A-Za-z]+)/(\d+)/(\d{4})$", raw.strip())
    if not m:
        return raw.strip()
    mon = MONTHS.get(m.group(1)[:3].lower(), m.group(1))
    return f"{mon} {int(m.group(2))}, {m.group(3)}"


LINKS: Links | None = None
CUR_DOC = ""
FOOTNOTES: dict[str, str] = {}


#: Absolute links into the current/stable source docs for a page this repo also
#: has. Explicitly-versioned links (e.g. `/en/4.8/`) are left alone, because the
#: source uses those deliberately to point at an older release.
_SOURCE_SELF_LINK = re.compile(
    r"^https?://(?:www\.)?netris\.io/docs/en/(?:latest|stable)/(?P<doc>[\w./+-]+?)\.html(?P<frag>#\S*)?$"
)


def internalize(url: str) -> str:
    """Rewrite an absolute self-link into a repo-relative path when possible."""
    assert LINKS is not None
    m = _SOURCE_SELF_LINK.match(url)
    if not m:
        return url
    doc = m.group("doc")
    if doc not in LINKS.doc_paths:
        return url
    target = LINKS.doc_paths[doc]
    frag = m.group("frag") or ""
    if frag and "#" in target:
        return target
    return target + frag


def _mdx_escape(text: str) -> str:
    """Escape characters that MDX/acorn would otherwise parse as JSX."""
    # Angle-bracket autolinks -> bare URL.
    text = re.sub(r"<((?:https?|mailto):[^>\s]+)>", r"\1", text)
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "`":
            j = text.find("`", i + 1)
            if j == -1:
                out.append("`")
                i += 1
                continue
            out.append(text[i : j + 1])
            i = j + 1
            continue
        if ch == "<":
            # Preserve the small set of real HTML tags we emit deliberately.
            m = re.match(r"</?(br|img|Frame|sup|sub)\b[^>]*/?>", text[i:])
            if m:
                out.append(m.group(0))
                i += len(m.group(0))
                continue
            # `<placeholder>` in prose: backtick it rather than HTML-escaping it.
            # Escaping renders literal `<name>` text that reads as a stray tag;
            # inline code is what the value actually is (mdx-conversion.md,
            # port-artifact Pattern G).
            m = re.match(r"<([A-Za-z][A-Za-z0-9_.:/ +-]{0,48})>", text[i:])
            if m:
                out.append("`<" + m.group(1) + ">`")
                i += len(m.group(0))
                continue
            out.append("&lt;")
            i += 1
            continue
        if ch == ">":
            out.append("&gt;")
            i += 1
            continue
        if ch in "{}":
            out.append("\\" + ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def inline(text: str) -> str:
    """Convert rST inline markup to MDX, protecting code spans."""
    assert LINKS is not None
    slots: list[str] = []

    def stash(value: str) -> str:
        slots.append(value)
        return f"\x01{len(slots) - 1}\x01"

    # 1. Inline literals -> backticked code (protected from later passes).
    def lit(m):
        body = m.group(1)
        fence = "`"
        while fence in body:
            fence += "`"
        pad = " " if body.startswith("`") or body.endswith("`") else ""
        return stash(f"{fence}{pad}{body}{pad}{fence}")

    text = re.sub(r"``(.+?)``", lit, text, flags=re.S)

    # 2. Roles.
    def role_doc(m):
        label, target = m.group("label"), m.group("target")
        if target is None:
            target, label = label, None
        path, title = LINKS.doc_target(CUR_DOC, target)
        return stash(f"[{_mdx_escape(label or title)}]({path})")

    text = re.sub(
        r":doc:`(?P<label>[^`<>]*?)\s*<(?P<target>[^`<>]+)>`|:doc:`(?P<label2>[^`<>]+)`",
        lambda m: role_doc_wrapper(m, stash),
        text,
    )

    def role_ref(m):
        groups = m.groups()
        label = groups[0]
        target = groups[1] if len(groups) > 1 else None
        if target is None:
            target = label
            label = None
        key = target.strip().lower()
        entry = LINKS.labels.get(key)
        if entry is None:
            # Unresolved on the source too: keep the visible text only.
            return stash(_mdx_escape(label or target))
        shown = label
        if shown is None:
            disp = _label_display(key)
            shown = disp or target
        return stash(f"[{_mdx_escape(shown)}]({entry})")

    text = re.sub(r":ref:`([^`<>]*?)\s*<([^`<>]+)>`", lambda m: role_ref(m), text)
    text = re.sub(r":ref:`([^`<>]+)`", lambda m: role_ref(m), text)

    # Remaining single-word roles (:guilabel:, :menuselection:, ...) -> plain text.
    text = re.sub(r":[a-z:-]+:`([^`]*)`", lambda m: stash(_mdx_escape(m.group(1))), text)

    # 3. Explicit hyperlinks `text <url>`_ and named references.
    def named_link(m):
        label, url = m.group(1).strip(), m.group(2).strip()
        label = re.sub(r"\s+", " ", label)
        url = url.replace("\n", "").strip()
        return stash(f"[{_mdx_escape(label)}]({internalize(url)})")

    text = re.sub(r"`([^`<>]+?)\s*<([^`<>]+?)>`__?", named_link, text, flags=re.S)

    # Footnote references -> superscript marker matching the source's number.
    def footnote_ref(m):
        fid = m.group(1).lstrip("#")
        return stash("<sup>" + FOOTNOTES.get(fid, fid) + "</sup>")

    text = re.sub(r"\[([#*]?[\w.-]+)\]_", footnote_ref, text)

    def bare_named(m):
        raw = m.group(1)
        key = raw.strip().lower()
        url = LINKS.named.get(key)
        if url:
            return stash(f"[{_mdx_escape(raw.strip())}]({url})")
        return stash(_mdx_escape(raw.strip()))

    text = re.sub(r"`([^`<>]+?)`__?", bare_named, text)
    text = re.sub(r"(?<![\w`])([A-Za-z][A-Za-z0-9.-]*)_(?![\w`])", bare_named, text)

    # 4. Emphasis (rST -> Markdown is a no-op, but protect it from escaping).
    text = re.sub(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", lambda m: stash("**" + _mdx_escape(m.group(1)) + "**"), text, flags=re.S)
    text = re.sub(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])", lambda m: stash("*" + _mdx_escape(m.group(1)) + "*"), text)

    text = _mdx_escape(text)
    # Placeholders can nest (a role inside emphasis), so expand to a fixed point.
    for _ in range(12):
        new = re.sub(r"\\?\x01(\d+)\\?\x01", lambda m: slots[int(m.group(1))], text)
        if new == text:
            break
        text = new
    return text


def role_doc_wrapper(m, stash):
    assert LINKS is not None
    label = m.group("label")
    target = m.group("target")
    if target is None:
        target = m.group("label2")
        label = None
    path, title = LINKS.doc_target(CUR_DOC, target)
    return stash(f"[{_mdx_escape(label or title)}]({path})")


_LABEL_DISP: dict[str, str] | None = None


def _label_display(key: str) -> str | None:
    global _LABEL_DISP
    if _LABEL_DISP is None:
        _LABEL_DISP = {}
        for name, (role, _uri, disp) in S._objects_inv_labels().items():
            if disp and disp != "-":
                _LABEL_DISP[name] = disp
    return _LABEL_DISP.get(key)


# --------------------------------------------------------------------------- #
# block parsing
# --------------------------------------------------------------------------- #


def dedent(lines: list[str]) -> list[str]:
    widths = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    if not widths:
        return ["" for _ in lines]
    pad = min(widths)
    return [l[pad:] if l.strip() else "" for l in lines]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _take_indented(lines: list[str], i: int, base: int) -> tuple[list[str], int]:
    """Collect the block indented deeper than ``base`` starting at ``i``."""
    body: list[str] = []
    while i < len(lines):
        if not lines[i].strip():
            body.append("")
            i += 1
            continue
        if _indent_of(lines[i]) <= base:
            break
        body.append(lines[i])
        i += 1
    while body and not body[-1].strip():
        body.pop()
    return dedent(body), i


def section_levels(text: str) -> dict[str, int]:
    order: list[str] = []
    for key, _title, _idx in S._iter_sections(text):
        if key not in order:
            order.append(key)
    return {k: n + 1 for n, k in enumerate(order)}


def quote_attr(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = _html.unescape(value)
    if '"' in value:
        value = value.replace('"', "'")
    return '"' + value + '"'


def render(lines: list[str], levels: dict[str, int], tables: list[str], depth: int = 0) -> str:
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        base = _indent_of(line)
        stripped = line.strip()

        # --- table placeholder -------------------------------------------- #
        m = re.match(r"^\x00TBL(\d+)\x00$", stripped)
        if m:
            idx = int(m.group(1))
            body = tables[idx] if idx < len(tables) else ""
            if body:
                out.append(body)
            i += 1
            continue

        # --- directives ---------------------------------------------------- #
        m = re.match(r"^\.\.\s+([A-Za-z][\w-]*)::(.*)$", stripped)
        if m:
            name, arg = m.group(1).lower(), m.group(2).strip()
            opts, body, i = _parse_directive(lines, i, base)
            chunk = emit_directive(name, arg, opts, body, levels, tables, depth)
            if chunk:
                out.append(chunk)
            continue

        # --- footnote / citation definitions ------------------------------- #
        m = re.match(r"^\.\.\s+\[([^\]]+)\]\s+(.*)$", stripped)
        if m:
            fid = m.group(1).lstrip("#") or ""
            rest = [m.group(2)]
            body, i = _take_indented(lines, i + 1, base)
            inner = render(dedent(rest + [""] + body) if body else [m.group(2)], levels, tables, depth + 1)
            num = FOOTNOTES.get(fid, fid)
            out.append(f"<sup>{num}</sup> {inner.strip()}")
            continue

        # --- empty comment -------------------------------------------------- #
        # A bare `..` does not swallow the block that follows it: docutils uses
        # it to terminate the preceding construct, which turns the following
        # indented block into a visible block quote.
        if stripped == "..":
            body, i = _take_indented(lines, i + 1, base)
            if body:
                out.append(render(body, levels, tables, depth + 1))
            continue

        # --- substitution definitions, targets, comments ------------------- #
        if re.match(r"^\.\.\s+\|[^|]+\|\s", stripped) or re.match(r"^\.\.\s+_", stripped):
            _body, i = _take_indented(lines, i + 1, base)
            continue
        if stripped.startswith(".. "):
            _body, i = _take_indented(lines, i + 1, base)
            continue

        # --- section headings ---------------------------------------------- #
        head = _match_section(lines, i)
        if head:
            key, title, consumed = head
            level = levels.get(key, 2)
            hashes = "#" * max(2, min(level, 6))
            out.append(f"{hashes} {inline(title)}")
            i += consumed
            continue

        # --- transition ---------------------------------------------------- #
        if len(set(stripped)) == 1 and stripped[0] in ADORNMENTS and len(stripped) >= 4:
            out.append("---")
            i += 1
            continue

        # --- line block ---------------------------------------------------- #
        if stripped.startswith("| ") or stripped == "|":
            block: list[str] = []
            while i < n and (lines[i].strip().startswith("| ") or lines[i].strip() == "|"):
                block.append(lines[i].strip()[1:].strip())
                i += 1
            rendered = [inline(b) for b in block if b]
            out.append("\n".join(rendered))
            continue

        # --- bullet list --------------------------------------------------- #
        if re.match(r"^[-*+]\s+\S", stripped) or re.match(r"^[-*+]$", stripped):
            chunk, i = _render_list(lines, i, levels, tables, depth, ordered=False)
            out.append(chunk)
            continue

        # --- enumerated list ----------------------------------------------- #
        if re.match(r"^(\d+|#|[a-zA-Z])[.)]\s+\S", stripped):
            chunk, i = _render_list(lines, i, levels, tables, depth, ordered=True)
            out.append(chunk)
            continue

        # --- field list ---------------------------------------------------- #
        if re.match(r"^:[^:]+:(\s|$)", stripped):
            rows: list[str] = []
            while i < n and re.match(r"^:[^:]+:(\s|$)", lines[i].strip()):
                fm = re.match(r"^:([^:]+):\s*(.*)$", lines[i].strip())
                rows.append(f"**{inline(fm.group(1))}**: {inline(fm.group(2))}")
                i += 1
            out.append("\n\n".join(rows))
            continue

        # --- paragraph / literal block intro / definition list ------------- #
        para: list[str] = []
        while i < n and lines[i].strip() and _indent_of(lines[i]) >= base:
            nxt = _match_section(lines, i)
            if nxt and para:
                break
            s = lines[i].strip()
            if para and (
                re.match(r"^[-*+]\s+\S", s)
                or re.match(r"^\.\.\s+[A-Za-z][\w-]*::", s)
                or re.match(r"^\x00TBL\d+\x00$", s)
                or s.startswith("| ")
            ):
                break
            para.append(s)
            i += 1
        text = " ".join(para)

        literal = text.endswith("::")
        if literal:
            text = text[:-2].rstrip()
            if text.endswith(":"):
                text = text[:-1].rstrip()
            if text:
                text += ":"

        if text:
            out.append(inline(text))

        # Indented follow-on block: literal block, definition, or block quote.
        if i < n:
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j < n and _indent_of(lines[j]) > base:
                body, i = _take_indented(lines, j, base)
                if literal:
                    out.append("```text\n" + "\n".join(body) + "\n```")
                else:
                    inner = render(body, levels, tables, depth + 1)
                    if len(para) == 1 and not text.endswith((".", ":", "!", "?")) and inner:
                        # Definition list: term + indented definition.
                        if out and out[-1] == inline(text):
                            out[-1] = f"**{inline(text)}**"
                        out.append(indent_block(inner, "  ") if depth == 0 else inner)
                    else:
                        out.append(inner)
        continue

    return "\n\n".join(c for c in out if c.strip())


def indent_block(text: str, pad: str) -> str:
    return "\n".join(pad + l if l.strip() else "" for l in text.split("\n"))


def _match_section(lines: list[str], i: int) -> tuple[str, str, int] | None:
    line = lines[i].strip()
    is_adorn = len(line) >= 3 and len(set(line)) == 1 and line[0] in ADORNMENTS
    if is_adorn and i + 2 < len(lines):
        title = lines[i + 1].strip()
        below = lines[i + 2].strip()
        if (
            title
            and len(below) >= 3
            and len(set(below)) == 1
            and below[0] == line[0]
            and len(below) >= len(title) - 2
        ):
            return ("over:" + line[0], title, 3)
    if line and i + 1 < len(lines):
        below = lines[i + 1].strip()
        if (
            len(below) >= 3
            and len(set(below)) == 1
            and below[0] in ADORNMENTS
            and len(below) >= len(line) - 2
            and not line.startswith("..")
            and not line.startswith(":")
            and not re.match(r"^[-*+]\s", line)
            and not line.startswith("|")
            and len(set(line)) != 1
        ):
            return ("under:" + below[0], line, 2)
    return None


def _parse_directive(lines: list[str], i: int, base: int) -> tuple[dict[str, str], list[str], int]:
    """Consume a directive's options and body; returns ``(opts, body, next_i)``."""
    first = lines[i].strip()
    m = re.match(r"^\.\.\s+[A-Za-z][\w-]*::(.*)$", first)
    inline_arg = m.group(1).strip() if m else ""
    i += 1
    opts: dict[str, str] = {}
    while i < len(lines):
        s = lines[i]
        if not s.strip():
            break
        if _indent_of(s) <= base:
            break
        om = re.match(r"^\s*:([a-zA-Z][\w-]*):\s*(.*)$", s)
        if not om:
            break
        opts[om.group(1)] = om.group(2).strip()
        i += 1
    body, i = _take_indented(lines, i, base)
    while body and not body[0].strip():
        body.pop(0)
    if inline_arg:
        opts["__arg__"] = inline_arg
    return opts, body, i


def emit_directive(
    name: str,
    arg: str,
    opts: dict[str, str],
    body: list[str],
    levels: dict[str, int],
    tables: list[str],
    depth: int,
) -> str:
    if name in DROP_DIRECTIVES:
        return ""

    if name == "code-block" or name == "code" or name == "literalinclude":
        lang = LANG_MAP.get(arg.lower(), arg.lower() or "text")
        code = "\n".join(body)
        fence = "```"
        while fence in code:
            fence += "`"
        # Sphinx's `:caption:` maps to Mintlify's code-block title.
        caption = opts.get("caption", "").strip()
        header = f"{fence}{lang}" + (f" {caption}" if caption else "")
        return f"{header}\n{code}\n{fence}"

    if name == "image" or name == "figure":
        return emit_image(arg, opts, body, levels, tables, depth)

    if name in CALLOUTS:
        tag = CALLOUTS[name]
        content_lines = list(body)
        if arg:
            content_lines = [arg] + ([""] + content_lines if content_lines else [])
        inner = render(dedent(content_lines), levels, tables, depth + 1)
        if not inner.strip():
            return ""
        return f"<{tag}>\n{indent_block(inner, '  ')}\n</{tag}>"

    if name == "topic":
        inner = render(body, levels, tables, depth + 1)
        title = f"**{inline(arg)}**\n\n" if arg else ""
        return f"<Check>\n{indent_block(title + inner, '  ')}\n</Check>"

    if name in ("dropdown", "collapse", "details"):
        inner = render(body, levels, tables, depth + 1)
        title = arg or "Details"
        return f"<Accordion title={quote_attr(title)}>\n{indent_block(inner, '  ')}\n</Accordion>"

    if name == "tab-set":
        return emit_tab_set(body, levels, tables, depth)

    if name == "tab-item":
        inner = render(body, levels, tables, depth + 1)
        return f"<Tab title={quote_attr(arg)}>\n{indent_block(inner, '  ')}\n</Tab>"

    if name == "raw":
        return emit_raw(arg, body)

    if name in ("list-table", "csv-table"):
        # Replaced by the rendered-HTML table in the pre-pass; nothing to emit.
        return ""

    if name in ("centered", "rubric"):
        return f"**{inline(arg)}**" if arg else ""

    if name == "container":
        return render(body, levels, tables, depth)

    # Unknown directive: keep its body so no content is lost.
    return render(body, levels, tables, depth)


def emit_tab_set(body: list[str], levels: dict[str, int], tables: list[str], depth: int) -> str:
    items: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(body):
        line = body[i]
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^(\s*)\.\.\s+tab-item::\s*(.*)$", line)
        if not m:
            i += 1
            continue
        base = len(m.group(1))
        title = m.group(2).strip()
        opts, inner, i = _parse_directive(body, i, base)
        items.append((title, inner))
    if not items:
        return render(body, levels, tables, depth)
    parts = []
    for title, inner in items:
        rendered = render(inner, levels, tables, depth + 1)
        parts.append(f"  <Tab title={quote_attr(title)}>\n{indent_block(rendered, '    ')}\n  </Tab>")
    return "<Tabs>\n" + "\n".join(parts) + "\n</Tabs>"


def emit_raw(fmt: str, body: list[str]) -> str:
    text = " ".join(l.strip() for l in body if l.strip())
    if fmt.lower() != "html":
        return ""
    if re.fullmatch(r"(?:<br\s*/?>|</br>)+", text.strip()):
        return "<br />"
    m = re.match(r"^<p[^>]*>\s*<em>(.*?)</em>\s*</p>$", text.strip(), re.S)
    if m:
        # Figure caption: attached to the preceding image by the caller.
        return "\x02CAPTION:" + re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip()
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", _html.unescape(plain)).strip()
    return inline(plain) if plain else ""


def humanize_filename(src: str) -> str:
    """Fallback alt text from the source's (descriptive) image filename."""
    name = os.path.basename(src)
    name = re.sub(r"\.(png|jpe?g|svg|gif|webp)$", "", name, flags=re.I)
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


def emit_image(arg: str, opts: dict[str, str], body: list[str], levels, tables, depth) -> str:
    src = arg.strip()
    if not src.startswith("http"):
        src = "/images/" + os.path.basename(src)
    alt = opts.get("alt", "") or humanize_filename(src)
    attrs = [f'src="{src}"', f"alt={quote_attr(alt)}"]
    if "width" in opts:
        w = opts["width"].strip()
        if re.fullmatch(r"\d+", w):
            w += "px"
        attrs.append(f'width="{w}"')
    if "height" in opts:
        h = opts["height"].strip()
        if re.fullmatch(r"\d+", h):
            h += "px"
        attrs.append(f'height="{h}"')
    img = "<img " + " ".join(attrs) + " />"
    caption = ""
    if body:
        caption = re.sub(r"\s+", " ", " ".join(l.strip() for l in body if l.strip())).strip()
    if caption:
        return f"<Frame caption={quote_attr(caption)}>\n  {img}\n</Frame>"
    return f"<Frame>\n  {img}\n</Frame>"


# --------------------------------------------------------------------------- #
# lists
# --------------------------------------------------------------------------- #


def _render_list(lines, i, levels, tables, depth, ordered: bool):
    out: list[str] = []
    n = len(lines)
    base = _indent_of(lines[i])
    counter = 0
    if ordered:
        # Honour an explicit start number so a list split by an intervening
        # directive keeps the source's numbering.
        m0 = re.match(r"^(\d+)[.)]\s", lines[i].strip())
        if m0:
            counter = int(m0.group(1)) - 1
    while i < n:
        if not lines[i].strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j >= n or _indent_of(lines[j]) < base:
                i = j
                break
            if _indent_of(lines[j]) == base and not _is_item(lines[j].strip(), ordered):
                i = j
                break
            i = j
            continue
        if _indent_of(lines[i]) < base:
            break
        s = lines[i].strip()
        if not _is_item(s, ordered):
            break
        m = re.match(r"^([-*+]|\d+[.)]|#[.)]|[a-zA-Z][.)])\s*(.*)$", s)
        marker, rest = m.group(1), m.group(2)
        counter += 1
        item_lines = [rest] if rest else []
        cont_indent = base + len(marker) + 1
        i += 1
        while i < n:
            if not lines[i].strip():
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and _indent_of(lines[j]) > base:
                    item_lines.append("")
                    i = j
                    continue
                break
            if _indent_of(lines[i]) > base:
                item_lines.append(lines[i][min(cont_indent, _indent_of(lines[i])) :])
                i += 1
                continue
            break
        inner = render(dedent(item_lines), levels, tables, depth + 1)
        bullet = f"{counter}." if ordered else "-"
        pad = " " * (len(bullet) + 1)
        block = indent_block(inner, pad).lstrip()
        out.append(f"{bullet} {block}")
    body = "\n".join(out)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body, i


def _is_item(s: str, ordered: bool) -> bool:
    if ordered:
        return bool(re.match(r"^(\d+|#|[a-zA-Z])[.)]\s+\S", s))
    return bool(re.match(r"^[-*+]\s+\S", s)) or s in ("-", "*", "+")


# --------------------------------------------------------------------------- #
# pre-passes
# --------------------------------------------------------------------------- #


def substitute(text: str) -> str:
    subs = dict(re.findall(r"^\.\.\s+\|(\w+)\|\s+replace::\s*(.+)$", text, re.M))
    for key, val in subs.items():
        text = text.replace(f"|{key}|", val.strip())
    return text


def mark_tables(text: str) -> str:
    """Replace every table-producing construct with an ordered placeholder."""
    lines = text.split("\n")
    out: list[str] = []
    idx = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        m = re.match(r"^\.\.\s+(list-table|csv-table)::", s)
        if m:
            base = _indent_of(line)
            i += 1
            while i < n:
                if not lines[i].strip():
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and _indent_of(lines[j]) > base:
                        i = j
                        continue
                    break
                if _indent_of(lines[i]) <= base:
                    break
                i += 1
            out.append(" " * base + TABLE_MARK.format(idx))
            idx += 1
            continue
        if re.match(r"^\+[-=+]{3,}\+$", s):
            base = _indent_of(line)
            while i < n and lines[i].strip() and re.match(r"^[+|]", lines[i].strip()):
                i += 1
            out.append(" " * base + TABLE_MARK.format(idx))
            idx += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def attach_captions(text: str) -> str:
    """Fold ``\\x02CAPTION:`` markers into the preceding ``<Frame>``."""
    blocks = text.split("\n\n")
    out: list[str] = []
    for block in blocks:
        if block.startswith("\x02CAPTION:"):
            caption = block[len("\x02CAPTION:") :].strip()
            if out and out[-1].lstrip().startswith("<Frame"):
                pad = out[-1][: len(out[-1]) - len(out[-1].lstrip())]
                inner = out[-1].strip()
                if inner.startswith("<Frame>"):
                    inner = "<Frame caption=" + quote_attr(caption) + ">" + inner[len("<Frame>") :]
                    # The source's own caption is the best alt text available, so
                    # promote it over the filename-derived fallback.
                    alt_text = re.sub(r"^(Figure|Diagram)[.:]\s*", "", caption).strip()
                    if alt_text:
                        inner = re.sub(r'alt="[^"]*"', "alt=" + quote_attr(alt_text), inner, count=1)
                    out[-1] = indent_block(inner, pad) if pad else inner
                    continue
            out.append("*" + inline(caption) + "*")
            continue
        out.append(block)
    return "\n\n".join(out)


def tidy(text: str) -> str:
    text = attach_captions(text)
    text = re.sub(r"\x02CAPTION:(.*)", lambda m: "*" + m.group(1).strip() + "*", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Never open/close a component or fence on a prose line.
    text = re.sub(r"(?m)^(\s*)(</?(?:Note|Tip|Warning|Info|Danger|Check|Accordion|Tabs|Tab|Frame|Steps|Step|CardGroup|Card)\b[^\n]*>)[ \t]+(\S)", r"\1\2\n\n\1\3", text)
    return text.strip() + "\n"


# --------------------------------------------------------------------------- #
# page conversion
# --------------------------------------------------------------------------- #


def convert_page(docname: str) -> tuple[str, str]:
    """Return ``(title, mdx_body)`` for one source document."""
    global CUR_DOC, FOOTNOTES
    CUR_DOC = docname
    FOOTNOTES = S.footnote_numbers(docname)
    text = read_source(docname)
    levels = section_levels(text)
    tables = S.html_tables(docname, inline_fn=inline)
    lines = text.split("\n")

    # Drop the document title (level 1) so it is not rendered twice.
    title = None
    for i, _line in enumerate(lines):
        head = _match_section(lines, i)
        if head and levels.get(head[0]) == 1:
            title = head[1]
            del lines[i : i + head[2]]
            break
    if title is None:
        title = S.source_title(docname)

    body = render(dedent(lines), levels, tables)
    return _html.unescape(title), tidy(body)


def read_source(docname: str) -> str:
    text = S.read_rst(docname)
    text = substitute(text)
    text = mark_tables(text)
    return text
