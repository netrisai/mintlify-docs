"""Validate every internal `#fragment` against the running preview.

`mint broken-links` checks page paths but **not** fragments, so a link to a
heading that Mintlify slugs differently (or does not render at all) silently
lands at the top of the page. This closes that gap.

Start `mint dev`, then:

    python3 scripts/check_anchors.py [--base http://localhost:3000]
"""

from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "mstack", "node_modules", "mirror", ".mintlify"}


def base_url() -> str:
    if "--base" in sys.argv:
        return sys.argv[sys.argv.index("--base") + 1].rstrip("/")
    return "http://localhost:3000"


def mdx_files() -> list[str]:
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".mdx"):
                out.append(os.path.join(root, name))
    return sorted(out)


def main() -> int:
    base = base_url()
    wanted: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for path in mdx_files():
        rel = os.path.relpath(path, REPO)
        text = open(path, encoding="utf-8").read()
        for m in re.finditer(r"\]\((/[^)\s#]*)#([^)\s]+)\)", text):
            wanted[m.group(1)].add((m.group(2), rel))

    broken: list[str] = []
    checked = 0
    for page in sorted(wanted):
        url = base + (page if page != "/" else "/")
        try:
            html = urllib.request.urlopen(url, timeout=90).read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            broken.append(f"{page}: could not fetch ({exc})")
            continue
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for anchor, src in sorted(wanted[page]):
            checked += 1
            if anchor not in ids:
                broken.append(f"{page}#{anchor}   <- {src}")

    print(f"Anchor check — {checked} internal fragments across {len(wanted)} pages")
    if broken:
        print(f"  FAIL  {len(broken)} unresolved")
        for item in broken:
            print(f"        {item}")
        return 1
    print("  PASS  every fragment resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
