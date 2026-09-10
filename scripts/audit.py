"""Second-pass structural audit of the converted docs.

Complements `port_artifact_sweep.py` (which asserts zero hits) with checks that
need judgement: heading hierarchy, title/H1 agreement with the source, component
counts against the source, anchor collisions, oversized pages, and residual
links back to the source domain.

    python3 scripts/audit.py [--verbose]
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import netris_source as S  # noqa: E402

REPO = S.REPO
SKIP_DIRS = {".git", "mstack", "node_modules", "mirror", ".mintlify"}

# Mintlify renders a page's own H1 from frontmatter `title`, so a page body
# should start at h2. Anything deeper without an h2 above it is a skip.
findings: dict[str, list[str]] = {}


def add(check: str, detail: str) -> None:
    findings.setdefault(check, []).append(detail)


def mdx_files() -> list[str]:
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".mdx"):
                out.append(os.path.join(root, name))
    return sorted(out)


def strip_fences(text: str) -> str:
    return re.sub(r"(?ms)^[ \t]*(`{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", text)


def main() -> int:
    verbose = "--verbose" in sys.argv
    manifest = {
        m["converted_file"]: m
        for m in json.load(open(os.path.join(REPO, "parity-manifest.json")))["pages"]
    }
    docs_json = json.load(open(os.path.join(REPO, "docs.json")))

    nav_pages: list[str] = []

    def walk(node):
        if isinstance(node, str):
            nav_pages.append(node)
        elif isinstance(node, dict):
            for c in node.get("pages", []):
                walk(c)
        elif isinstance(node, list):
            for c in node:
                walk(c)

    walk(docs_json["navigation"]["pages"])

    for path in mdx_files():
        rel = os.path.relpath(path, REPO)
        text = open(path, encoding="utf-8").read()
        fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        fm = fm_match.group(1) if fm_match else ""
        body = text[fm_match.end() :] if fm_match else text
        prose = strip_fences(body)

        title_m = re.search(r'^title:\s*"?(.*?)"?\s*$', fm, re.M)
        title = title_m.group(1) if title_m else None
        if not title:
            add("page has no frontmatter title", rel)

        # --- heading hierarchy ------------------------------------------- #
        levels = [len(m.group(1)) for m in re.finditer(r"(?m)^(#{1,6}) \S", prose)]
        if any(l == 1 for l in levels):
            add("body contains an h1 (duplicates the frontmatter title)", rel)
        prev = 1
        for lvl in levels:
            if lvl > prev + 1:
                add("heading level skipped", f"{rel} (h{prev} -> h{lvl})")
                break
            prev = lvl

        # --- anchor collisions ------------------------------------------- #
        heads = [
            S.slugify(re.sub(r"[`*\[\]()]", "", m.group(2)))
            for m in re.finditer(r"(?m)^(#{2,6}) (.+)$", prose)
        ]
        dupes = [h for h, n in Counter(heads).items() if n > 1 and h]
        if dupes:
            add("duplicate heading anchors on one page", f"{rel}: {dupes[:4]}")

        # --- title vs source H1 ------------------------------------------ #
        entry = manifest.get(rel)
        if entry and entry.get("source_h1") and title:
            if title != entry["source_h1"]:
                add("frontmatter title differs from source H1", f"{rel}: {title!r} vs {entry['source_h1']!r}")

        # --- links back to the source domain ----------------------------- #
        for m in re.finditer(r"\]\((https?://(?:www\.)?netris\.io/docs[^)]*)\)", body):
            add("link points back at the source docs domain", f"{rel}: {m.group(1)}")

        # --- code fences without a language ------------------------------ #
        for m in re.finditer(r"(?m)^[ \t]*```\s*$", body):
            line = body[: m.start()].count("\n") + 1
            # Closing fences also match; only flag an opener.
            before = body[: m.start()]
            if before.count("```") % 2 == 0:
                add("code fence with no language", f"{rel}:{line}")

        # --- oversized pages --------------------------------------------- #
        if len(body) > 120_000:
            add("page over 120K characters", f"{rel} ({len(body):,})")

        # --- nav membership ---------------------------------------------- #
        slug = rel[:-4]
        if slug != "index" and slug not in nav_pages:
            add("MDX page absent from docs.json navigation", rel)

        # --- component sanity -------------------------------------------- #
        if "<Tab " in body and "<Tabs>" not in body:
            add("<Tab> outside a <Tabs> wrapper", rel)
        if "<Accordion " in body and "<AccordionGroup>" not in body and body.count("<Accordion ") > 1:
            add("multiple <Accordion> without <AccordionGroup>", rel)
        if re.search(r"<Frame[^>]*>\s*</Frame>", body):
            add("empty <Frame>", rel)

        # --- images resolve ---------------------------------------------- #
        for m in re.finditer(r'src="(/images/[^"]+)"', body):
            if not os.path.exists(os.path.join(REPO, m.group(1).lstrip("/"))):
                add("image src does not resolve", f"{rel}: {m.group(1)}")

    # --- component counts vs source ------------------------------------- #
    for doc in S.all_docnames():
        if doc in S.NON_PAGE_DOCS or doc.startswith("release-notes/") or doc == "index":
            continue
        rst = S.read_rst(doc)
        mdx_path = os.path.join(REPO, S.normalized_path(doc) + ".mdx")
        if not os.path.exists(mdx_path):
            continue
        mdx = open(mdx_path, encoding="utf-8").read()
        pairs = [
            ("callout", r"^\s*\.\.\s+(?:note|tip|warning|important|caution|seealso|attention|hint)::", r"<(?:Note|Tip|Warning|Info|Danger)>"),
            ("accordion", r"^\s*\.\.\s+(?:dropdown|collapse)::", r"<Accordion\b"),
            ("tab", r"^\s*\.\.\s+tab-item::", r"<Tab\b"),
            ("image", r"^\s*\.\.\s+image::", r"<img\b"),
            ("code block", r"^\s*\.\.\s+code-block::", r"(?m)^\s*```\w"),
        ]
        for name, rst_pat, mdx_pat in pairs:
            n_rst = len(re.findall(rst_pat, rst, re.M))
            n_mdx = len(re.findall(mdx_pat, mdx))
            if name == "code block":
                # `::` literal blocks also produce fences, so only flag shortfalls.
                if n_mdx < n_rst:
                    add(f"{name} count lower than source", f"{doc}: rst {n_rst} vs mdx {n_mdx}")
            elif n_rst != n_mdx:
                add(f"{name} count differs from source", f"{doc}: rst {n_rst} vs mdx {n_mdx}")

    print(f"Structural audit — {len(mdx_files())} MDX files")
    if not findings:
        print("  no findings")
        return 0
    total = 0
    for check, items in sorted(findings.items(), key=lambda kv: -len(kv[1])):
        total += len(items)
        print(f"\n  {len(items):4d}  {check}")
        show = items if verbose else items[:8]
        for item in show:
            print(f"          {item}")
        if len(items) > len(show):
            print(f"          … {len(items) - len(show)} more")
    print(f"\ntotal findings: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
