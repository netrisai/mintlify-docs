"""Re-create the `mirror/` staging copy of the Netris Sphinx documentation.

The conversion pipeline reads from `mirror/`, which is gitignored because it is
a reproducible download rather than repository content. Run this before
`scripts/generate.py` on a fresh checkout:

    python3 scripts/fetch_mirror.py
    python3 scripts/generate.py

Discovery method (docs-to-mintlify -> references/discovery.md):

* `sitemap.xml` is not published by this site (404), so the canonical inventory
  comes from Sphinx's own `searchindex.js` `docnames` array — the authoritative
  list of every document in the build.
* The inventory was cross-checked by extracting every internal `.html` link from
  all 94 rendered pages; two consecutive passes discovered no additional page.
* Each page is fetched twice:
  - `_sources/<docname>.rst.txt` — the raw reStructuredText, which is what the
    transformer converts.
  - `<docname>.html` — the rendered page, used for tables (Sphinx does not
    publish the `csv-table` `:file:` CSVs), footnote numbering, and parity
    checking.
* `objects.inv` supplies the `:ref:` label table.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import os
import re
import sys
import urllib.request

BASE = "https://www.netris.io/docs/en/latest"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(REPO, "mirror")
TIMEOUT = 60


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "netris-docs-migration/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def docnames() -> list[str]:
    raw = get(f"{BASE}/searchindex.js").decode("utf-8")
    payload = raw[raw.index("(") + 1 :].rstrip().rstrip(")")
    return json.loads(payload)["docnames"]


def save(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def fetch_page(doc: str) -> str | None:
    try:
        save(os.path.join(MIRROR, "rst", doc + ".rst"), get(f"{BASE}/_sources/{doc}.rst.txt"))
        save(os.path.join(MIRROR, "html", doc + ".html"), get(f"{BASE}/{doc}.html"))
    except Exception as exc:  # noqa: BLE001
        return f"{doc}: {exc}"
    return None


def main() -> int:
    docs = docnames()
    print(f"discovered {len(docs)} docnames via searchindex.js")
    save(os.path.join(MIRROR, "objects.inv"), get(f"{BASE}/objects.inv"))

    errors = []
    with futures.ThreadPoolExecutor(max_workers=12) as pool:
        for err in pool.map(fetch_page, docs):
            if err:
                errors.append(err)
    print(f"fetched {len(docs) - len(errors)} pages ({len(errors)} errors)")
    for err in errors:
        print("  ", err)

    # Images: the rendered pages reference Sphinx's copied `_images/` output.
    srcs: set[str] = set()
    for doc in docs:
        html_path = os.path.join(MIRROR, "html", doc + ".html")
        if not os.path.exists(html_path):
            continue
        page = open(html_path, encoding="utf-8", errors="replace").read()
        # Only the article body: the source's own page chrome (its header logo
        # and Slack glyph) lives under _static/, not _images/.
        start = page.find('<div itemprop="articleBody"')
        end = page.find("<footer", start if start > 0 else 0)
        body = page[start:end] if start > 0 else page
        for m in re.finditer(r'<img[^>]+src="([^"]+)"', body):
            src = m.group(1)
            if src.startswith(("http", "data:")):
                continue
            srcs.add(os.path.basename(src))

    images_dir = os.path.join(REPO, "images")
    os.makedirs(images_dir, exist_ok=True)

    def fetch_image(name: str) -> str | None:
        target = os.path.join(images_dir, name)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            return None
        try:
            save(target, get(f"{BASE}/_images/{name}"))
        except Exception as exc:  # noqa: BLE001
            return f"{name}: {exc}"
        return None

    img_errors = []
    with futures.ThreadPoolExecutor(max_workers=12) as pool:
        for err in pool.map(fetch_image, sorted(srcs)):
            if err:
                img_errors.append(err)
    print(f"images referenced: {len(srcs)} ({len(img_errors)} errors)")
    for err in img_errors:
        print("  ", err)
    return 1 if errors or img_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
