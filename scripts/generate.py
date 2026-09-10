"""Build the Mintlify docs from the mirrored Netris Sphinx corpus.

Writes MDX pages, ``docs.json``, ``release-notes.mdx`` (consolidated
``<Update>`` timeline), ``parity-manifest.json`` and the sidebar-label review
file. Idempotent — re-run after any transformer rule change.

    python3 scripts/generate.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import netris_source as S  # noqa: E402
import rst_to_mdx as T  # noqa: E402

REPO = S.REPO

# llms.txt link prefix. Empty by default so links are root-relative, which
# resolves correctly on the local preview and on any deployed origin.
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")

# --------------------------------------------------------------------------- #
# sidebar labels
# --------------------------------------------------------------------------- #

# Deterministic boilerplate stripping, applied longest-first. Kept deliberately
# short: over-stripping produces sidebar labels that no longer say what the page
# is, which is worse than a label that wraps to two lines.
SIDEBAR_SUFFIX_RULES = [
    " Integration Plugin for Netris Controller",
    " Switch Initial Setup",
]

SIDEBAR_PREFIX_RULES = [
    "Getting Started with ",
]

# Small humanisation map for the remaining long titles. `title` (page H1,
# browser tab, search) stays verbatim from source; only the sidebar label
# changes, per style-docs "Shorten long, repetitive sidebar labels".
SIDEBAR_MAP = {
    "try-learn/nvidia-spectrum-x-scenario": "GPU-as-a-Service with Spectrum-X",
    "installation/controller-k3s-air-gap-ha": "HA Air-Gapped Installation",
    "supported-platform-matrix": "Functionality & Platforms Matrix",
}

# Landing pages of a nested group carry "Overview" so the sidebar does not
# render `Group > Group` (docs-json.md -> nested groups).
GROUP_LANDINGS = {
    "installation/installation",
    "switch-agent-installation",
    "vnet",
    "cloudstack/netris-cloudstack",
}

SIDEBAR_MIN_LEN = 30


def sidebar_title(docname: str, title: str) -> str | None:
    if docname in GROUP_LANDINGS:
        return "Overview"
    if docname in SIDEBAR_MAP:
        return SIDEBAR_MAP[docname]
    label = title
    for suffix in sorted(SIDEBAR_SUFFIX_RULES, key=len, reverse=True):
        if label.endswith(suffix) and len(label) > len(suffix) + 2:
            label = label[: -len(suffix)].rstrip()
    for prefix in sorted(SIDEBAR_PREFIX_RULES, key=len, reverse=True):
        if label.startswith(prefix) and len(label) > len(prefix) + 2:
            label = label[len(prefix) :].lstrip()
    if label != title and len(title) >= SIDEBAR_MIN_LEN and label:
        return label
    return None


# --------------------------------------------------------------------------- #
# changelog
# --------------------------------------------------------------------------- #


def build_changelog(order: list[str]) -> tuple[str, list[dict]]:
    """One page of ``<Update>`` blocks, in the source's release-notes order."""
    entries = []
    redirects = []
    for doc in order:
        title, body = T.convert_page(doc)
        label = T._release_label(title)
        # description: the source entry title without its date parenthetical.
        version = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
        # tag: just the version, which drives Mintlify's timeline filter UI.
        version_num = re.sub(r"^Netris\s+", "", version).replace(" Release Notes", "").strip()
        # Demote headings one level so each entry's structure nests under its label.
        body = re.sub(r"(?m)^(#{2,5}) ", lambda m: "#" * (len(m.group(1)) + 1) + " ", body)
        entries.append(
            {
                "doc": doc,
                "label": label,
                "description": version,
                "tag": version_num,
                "body": body.strip(),
            }
        )
        redirects.append(
            {
                "source": "/" + S.normalized_path(doc),
                "destination": "/release-notes#" + S.slugify(label),
                "permanent": True,
            }
        )

    labels = [e["label"] for e in entries]
    dupes = {l for l in labels if labels.count(l) > 1}
    if dupes:
        raise SystemExit(f"duplicate <Update> labels: {sorted(dupes)}")

    out = ['---', 'title: "Release Notes"', "rss: true", "---", ""]
    for e in entries:
        out.append(f'{{/* source: {S.SOURCE_BASE}/{e["doc"]}.html */}}')
        out.append(
            f'<Update label="{e["label"]}" description="{e["description"]}" '
            f'tags={{["{e["tag"]}"]}}>'
        )
        out.append(T.indent_block(e["body"], "  "))
        out.append("</Update>")
        out.append("")
    return "\n".join(out).rstrip() + "\n", redirects


# --------------------------------------------------------------------------- #
# navigation
# --------------------------------------------------------------------------- #


def build_navigation(sections: list[S.NavSection], titles: dict[str, str]):
    """Root-level navigation mirroring the source's caption sections.

    The source is a Sphinx/RTD sidebar: one continuous list of caption
    sections with no top-of-page tab toggle, so this uses sibling groups (not
    ``tabs``) per style-docs "Tabs vs sibling groups".
    """
    entries: list = []
    for section in sections:
        if section.caption == "Release Notes":
            # Consolidated changelog: a single page, flattened alongside the
            # sibling groups so the sidebar shows no `Release Notes > Release
            # Notes` duplicate-label pair (preview-qa Gate 3).
            entries.append("release-notes")
            continue
        pages: list = []
        for node in section.nodes:
            pages.append(node_entry(node, titles))
        entries.append({"group": section.caption, "pages": pages})
    return entries


def lead_sentence(body: str, limit: int = 170) -> str:
    """First substantive sentence of a converted page, for the llms.txt index.

    This is agent-only metadata (llms.txt is never rendered), so unlike the MDX
    `description` frontmatter it can be derived from the page body without
    putting text on the page that the source does not have.
    """
    text = body
    text = re.sub(r"(?ms)^[ \t]*(`{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", text)
    text = re.sub(r"(?m)^\s*<[^>]+>\s*$", "", text)
    text = re.sub(r"(?m)^#{1,6} .*$", "", text)
    text = re.sub(r"(?m)^\s*\|.*$", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*`]", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = re.sub(r"\\([{}])", r"\1", text)
    for para in text.split("\n\n"):
        para = " ".join(para.split())
        # Drop leading escaped markers (the source uses `\*` for footnote refs);
        # the `*` is already gone by this point, leaving the backslash.
        para = re.sub(r"^[\\*+]+\s*", "", para)
        if len(para) < 40 or para.startswith(("-", "1.", "|", ":")):
            continue
        m = re.match(r"^(.{40,}?[.!?])(\s|$)", para)
        sentence = m.group(1) if m else para
        if len(sentence) > limit:
            sentence = sentence[: limit - 1].rsplit(" ", 1)[0] + "…"
        return sentence
    return ""


def build_llms_txt(sections, titles, leads, site_url: str) -> str:
    """Curated root llms.txt.

    Mintlify generates one from `docs.json` plus page frontmatter, but because
    this migration deliberately omits `description` frontmatter (the source
    renders no subtitles), the generated index would be titles only. A curated
    file keeps the source's own section structure and adds a source-derived
    one-line summary per page.

    Links are root-relative and point at `.md`, which Mintlify's hosted
    deployment serves for every page (the local `mint dev` preview does not).
    """
    lines = [
        "# Netris Documentation",
        "",
        "> Netris is the network automation, abstraction, and multi-tenancy platform for"
        " GPU clouds and AI factories. This index covers installing the Netris Controller,"
        " managing switch fabrics, and running cloud-style network services on them.",
        "",
        "## Docs",
        "",
        f"- [Welcome to Netris Documentation]({site_url}/index.md): Documentation home,"
        " with the recommended reading order for a first Netris deployment.",
    ]
    for section in sections:
        if section.caption == "Release Notes":
            lines += [
                "",
                f"## {section.caption}",
                "",
                f"- [Release Notes]({site_url}/release-notes.md): Every Netris release"
                " from 2.8.0 to 4.16.0 as a dated timeline, newest first.",
            ]
            continue
        lines += ["", f"## {section.caption}", ""]

        def walk(node: S.NavNode):
            slug = S.normalized_path(node.docname)
            lead = leads.get(node.docname, "")
            entry = f"- [{titles[node.docname]}]({site_url}/{slug}.md)"
            if lead:
                entry += f": {lead}"
            lines.append(entry)
            for child in node.children:
                walk(child)

        for node in section.nodes:
            walk(node)
    return "\n".join(lines).rstrip() + "\n"


def child_map(sections: list[S.NavSection]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def walk(node: S.NavNode):
        out[node.docname] = [c.docname for c in node.children]
        for child in node.children:
            walk(child)

    for section in sections:
        for node in section.nodes:
            walk(node)
    return out


def child_cards(docs: list[str], titles: dict[str, str]) -> str:
    cards = "\n".join(
        f'  <Card title="{esc(titles[d])}" href="/{S.normalized_path(d)}" />' for d in docs
    )
    return "<CardGroup cols={2}>\n" + cards + "\n</CardGroup>\n"


def node_entry(node: S.NavNode, titles: dict[str, str]):
    path = S.normalized_path(node.docname)
    if not node.children:
        return path
    # Mirror the source's nesting depth: a page with children becomes a nested
    # group whose first entry is the parent page (labelled "Overview").
    #
    # The source's RTD sidebar puts a clickable expand toggle on every entry
    # that has children and renders them collapsed until the entry is active
    # (sphinx_rtd_theme's theme.js injects `span.toctree-expand`). Mintlify's
    # nested-group default is identical — collapsed, auto-expanded for the
    # active page — so `expanded` is deliberately left unset (preview-qa Gate 4).
    pages = [path] + [node_entry(c, titles) for c in node.children]
    return {"group": titles[node.docname], "pages": pages}


# --------------------------------------------------------------------------- #
# docs.json
# --------------------------------------------------------------------------- #

CONTEXTUAL_OPTIONS = [
    "copy", "view", "assistant", "chatgpt", "claude", "perplexity", "grok",
    "aistudio", "devin", "windsurf", "mcp", "add-mcp", "cursor", "vscode",
    "devin-mcp",
]


def build_docs_json(nav_entries, redirects) -> dict:
    return {
        "$schema": "https://mintlify.com/docs.json",
        # mstack standard; luma gives one full-width sticky navbar.
        "theme": "luma",
        "name": "Netris Documentation",
        # The source docs colour links, sidebar captions and section anchors with
        # navy (#01358d) and reserve coral (#f9556d) for buttons and hover
        # states, so navy is the brand token Mintlify's `primary` should carry.
        # `light` is the dark-mode emphasis colour and uses netris.io's own light
        # blue (#609FFF) — same hue family, 1.5 degrees apart, and much brighter.
        # `dark` is deliberately omitted: any value darker than a navy primary
        # fails `mint a11y`'s dark-on-dark-background check, and Mintlify falls
        # back to `primary` for that role.
        "colors": {
            "primary": "#01358d",
            "light": "#609fff",
        },
        "appearance": {"default": "light"},
        "fonts": {"family": "Montserrat"},
        "logo": {
            "light": "/logo/netris-light.png",
            "dark": "/logo/netris-dark.png",
            "href": "https://www.netris.io",
        },
        "favicon": "/favicon.png",
        "navbar": {
            # The source header shows a single "Join Slack" button.
            "primary": {"type": "button", "label": "Join Slack", "href": "https://netris.slack.com/"}
        },
        "navigation": {"pages": nav_entries},
        "seo": {"metatags": {"robots": "noindex"}},
        "contextual": {"options": CONTEXTUAL_OPTIONS},
        "redirects": redirects,
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def resolve_anchors() -> None:
    """Point every internal `#fragment` at a heading that actually exists.

    Sphinx labels can target a spot Mintlify gives no anchor to — most often the
    page's own H1, which Mintlify renders from frontmatter rather than as a body
    heading. `mint broken-links` does not validate fragments, so those links
    would silently land at the top of the page. Drop the fragment in that case
    (the page is still the right destination) and report what was dropped.
    """
    pages: dict[str, str] = {}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "mstack", "node_modules", "mirror", ".mintlify"}]
        for name in files:
            if name.endswith(".mdx"):
                path = os.path.join(root, name)
                pages[os.path.relpath(path, REPO)[:-4]] = path

    anchors = {
        slug: S.heading_ids(re.sub(r"^---\n.*?\n---\n", "", open(p, encoding="utf-8").read(), flags=re.S))
        for slug, p in pages.items()
    }

    dropped: list[str] = []
    for slug, path in sorted(pages.items()):
        text = open(path, encoding="utf-8").read()

        def fix(m: re.Match) -> str:
            target, frag = m.group(1), m.group(2)
            key = target.lstrip("/") or "index"
            table = anchors.get(key)
            if table is None:
                return m.group(0)
            if frag in table.values():
                return m.group(0)
            if frag in table:
                return f"]({target}#{table[frag]})"
            dropped.append(f"{slug}.mdx -> {target}#{frag}")
            return f"]({target})"

        new = re.sub(r"\](\(/[^)\s#]*)#([^)\s]+)\)", lambda m: fix(re.match(r"\]\((/[^)\s#]*)#([^)\s]+)\)", m.group(0))), text)
        if new != text:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)

    if dropped:
        print(f"anchors dropped (no matching heading): {len(dropped)}")
        for item in dropped[:12]:
            print(f"    {item}")
        if len(dropped) > 12:
            print(f"    … {len(dropped) - 12} more")


def collect_nav_pages(entries) -> list[str]:
    out: list[str] = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for child in node.get("pages", []):
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(entries)
    return out


def main() -> int:
    T.LINKS = T.Links()
    sections = S.nav_sections()
    flat = S.flatten(sections)
    titles = {doc: S.source_title(doc) for doc, _c in flat}
    titles["index"] = S.source_title("index")

    # Clean previously generated pages (never touch hand-authored files).
    for path in list(GENERATED_PAGES()):
        os.remove(path)

    manifest = []
    label_review = []

    children = child_map(sections)
    leads: dict[str, str] = {}

    for doc, caption in flat:
        # Release notes (and their listing page) become one <Update> timeline.
        if doc.startswith("release-notes/"):
            continue
        title, body = T.convert_page(doc)
        if not body.strip() and children.get(doc):
            # The source page's entire body is a visible (non-hidden) toctree,
            # which the converter drops because Mintlify owns navigation. Render
            # the same child list as Mintlify cards so the page is not blank.
            body = child_cards(children[doc], titles)
        leads[doc] = lead_sentence(body)
        slug = S.normalized_path(doc)
        fm = ['---', f'title: "{esc(title)}"']
        side = sidebar_title(doc, title)
        if side:
            fm.append(f'sidebarTitle: "{esc(side)}"')
            if side != "Overview":
                label_review.append({"slug": slug, "title": title, "sidebarTitle": side})
        fm.append("---")
        out_path = os.path.join(REPO, slug + ".mdx")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(fm) + "\n\n" + body)
        manifest.append(
            {
                "source_url": f"{S.SOURCE_BASE}/{doc}.html",
                "source_title": title,
                "source_sidebar_label": titles[doc],
                "source_h1": title,
                "source_description": "",
                "normalized_path": "/" + slug,
                "nav_section": caption,
                "converted_file": slug + ".mdx",
                "status": "done",
                "notes": "",
            }
        )

    # Consolidated changelog.
    release_docs = [d for d, _c in flat if S.RELEASE_NOTE_RE.match(d)]
    changelog, redirects = build_changelog(release_docs)
    with open(os.path.join(REPO, "release-notes.mdx"), "w", encoding="utf-8") as fh:
        fh.write(changelog)
    for doc in release_docs:
        title = S.source_title(doc)
        manifest.append(
            {
                "source_url": f"{S.SOURCE_BASE}/{doc}.html",
                "source_title": title,
                "source_sidebar_label": title,
                "source_h1": title,
                "source_description": "",
                "normalized_path": "/release-notes#" + S.slugify(T._release_label(title)),
                "nav_section": "Release Notes",
                "converted_file": "release-notes.mdx",
                "status": "done",
                "notes": "Consolidated into the single <Update> changelog timeline; "
                         "per-entry source URL preserved via docs.json redirects.",
            }
        )
    manifest.append(
        {
            "source_url": f"{S.SOURCE_BASE}/release-notes/index.html",
            "source_title": "Release Notes",
            "source_sidebar_label": "Release Notes",
            "source_h1": "Release Notes",
            "source_description": "",
            "normalized_path": "/release-notes",
            "nav_section": "Release Notes",
            "converted_file": "release-notes.mdx",
            "status": "done",
            "notes": "Source listing page replaced by the consolidated <Update> timeline.",
        }
    )
    manifest.append(
        {
            "source_url": f"{S.SOURCE_BASE}/index.html",
            "source_title": titles["index"],
            "source_sidebar_label": "Home",
            "source_h1": titles["index"],
            "source_description": "",
            "normalized_path": "/",
            "nav_section": "Home",
            "converted_file": "index.mdx",
            "status": "done",
            "notes": "Hand-authored landing page (/create-landing-page); the source index "
                     "is a Sphinx-generated toctree listing that Mintlify's sidebar covers.",
        }
    )
    manifest.append(
        {
            "source_url": f"{S.SOURCE_BASE}/_includes/links.html",
            "source_title": "",
            "source_sidebar_label": "",
            "source_h1": "",
            "source_description": "",
            "normalized_path": "",
            "nav_section": "",
            "converted_file": "",
            "status": "excluded",
            "notes": "Sphinx include fragment (named hyperlink targets), not a published "
                     "page; its targets are inlined into the converted links.",
        }
    )

    resolve_anchors()

    nav_entries = build_navigation(sections, titles)
    docs_json = build_docs_json(nav_entries, redirects)
    with open(os.path.join(REPO, "docs.json"), "w", encoding="utf-8") as fh:
        json.dump(docs_json, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with open(os.path.join(REPO, "parity-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "source_site": S.SOURCE_BASE,
                "generator": "scripts/generate.py",
                "discovered_pages": len(manifest),
                "converted_pages": sum(1 for m in manifest if m["status"] == "done"),
                "excluded_pages": sum(1 for m in manifest if m["status"] == "excluded"),
                "blocked_pages": sum(1 for m in manifest if m["status"] == "blocked"),
                "pages": manifest,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")

    with open(os.path.join(REPO, "llms.txt"), "w", encoding="utf-8") as fh:
        fh.write(build_llms_txt(sections, titles, leads, SITE_URL))

    with open(os.path.join(REPO, "scripts", "sidebar-labels.json"), "w", encoding="utf-8") as fh:
        json.dump(label_review, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # Parity gate: navigation must reference exactly the files on disk.
    nav_pages = collect_nav_pages(nav_entries)
    dupes = {p for p in nav_pages if nav_pages.count(p) > 1}
    on_disk = {
        os.path.relpath(os.path.join(r, f), REPO)[:-4]
        for r, _d, fs in os.walk(REPO)
        for f in fs
        if f.endswith(".mdx") and "mstack" not in r and "node_modules" not in r
    }
    missing = [p for p in nav_pages if p not in on_disk]
    orphan = sorted(on_disk - set(nav_pages) - {"index"})
    print(f"pages written : {len(manifest)} manifest rows")
    print(f"nav entries   : {len(nav_pages)}")
    print(f"duplicates    : {sorted(dupes) or 'none'}")
    print(f"nav -> no file: {missing or 'none'}")
    print(f"orphan mdx    : {orphan or 'none'}")
    if dupes or missing or orphan:
        return 1
    return 0


def esc(value: str) -> str:
    return value.replace('"', "'")


def GENERATED_PAGES():
    """Every previously generated MDX page (index.mdx is hand-authored)."""
    keep = {"index.mdx"}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "mstack", "node_modules", "mirror", "scripts", "images", "logo", ".mintlify"}]
        for name in files:
            if not name.endswith(".mdx"):
                continue
            rel = os.path.relpath(os.path.join(root, name), REPO)
            if rel in keep:
                continue
            yield os.path.join(root, name)


if __name__ == "__main__":
    raise SystemExit(main())
