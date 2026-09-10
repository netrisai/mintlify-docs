# Preview QA report — Netris documentation

Last reviewed: 2026-09-09 (landing-page and information-architecture redesign)

Source: <https://www.netris.io/docs/en/latest/> (Sphinx / sphinx_rtd_theme)
Customer website: <https://www.netris.io>
Branch: `cursor/mintlify-docs-migration-7094`

Re-run every gate with:

```bash
python3 scripts/fetch_mirror.py         # refresh the source mirror
python3 scripts/generate.py             # regenerate pages, docs.json, manifest, llms.txt
python3 scripts/port_artifact_sweep.py  # Gate 1.5
python3 scripts/parity_check.py         # Gate 2
python3 scripts/audit.py                # structural audit (judgement-level checks)
mint validate && mint broken-links && mint a11y
python3 scripts/check_anchors.py        # internal #fragments (mint broken-links skips these)
node scripts/screenshot.mjs --out /tmp/qa --modes light,dark --viewports desktop,mobile --paths / introduction
```

## Coverage

| | Count |
|---|---|
| Documents discovered on the source | 94 |
| Converted (`status: done`) | 93 |
| Excluded with a reason | 1 (`_includes/links`, a Sphinx include fragment) |
| Blocked | 0 |
| MDX pages in the repo | 64 (63 navigation entries + the homepage) |
| Source images vendored | 211 |

The 29 release-note pages are intentionally one page rather than 29: they are
consolidated into a single `<Update>` timeline per
`docs-to-mintlify/references/changelogs.md`, with `docs.json` redirects
preserving every per-entry source URL.

Discovery method: the site publishes no `sitemap.xml`, so the inventory comes
from Sphinx's own `searchindex.js` `docnames` array. It was cross-checked by
extracting every internal `.html` link from all 94 rendered pages; two
consecutive passes found no additional in-scope page.

## Gate results

| Gate | Status | Notes |
|------|--------|-------|
| 1. Config + validation | PASS | `docs.json` parses; `mint validate` clean; `mint broken-links` clean; `mint a11y` clean (colors + all 64 files); no orphan MDX, no dangling nav entries, no root `.js` |
| 1.5. Port-artifact sweep | PASS | 19 checks, zero hits: patterns A–J plus rST directive/role/adornment/footnote leakage, unresolved substitutions, empty `alt`, `.md`/`.html` link extensions, control-character leakage, tags sharing a line with prose, unbalanced components |
| 2. Source-mirror parity | PASS | All 92 source pages at ≥99.6% word coverage against the rendered source; 0 pages below 99% |
| 3. Chrome parity | PASS | See below |
| 4. Collapsibility parity | PASS | See below |
| 5. Background + theme | PASS | See below |
| 6. Visual verification | PASS | Light + dark, desktop (1440×1000) + mobile (390×844) |

Ready for `/han-review`: **YES**

## Gate 3 — chrome parity

Audited field by field against a fresh fetch of the source:

| Source chrome | `docs.json` surface |
|---|---|
| Logo, top-left, links to `https://www.netris.io` | `logo.light` / `logo.dark` / `logo.href` |
| "Join Slack" button | `navbar.primary` |
| One long source sidebar | Four task-oriented tabs: Overview, Deploy, Operate, Integrate |
| No sidebar anchor rail | `navigation.global.anchors` absent |
| No right-side utility links | `navbar.links` absent |
| Footer shows only a copyright line and Sphinx/RTD attribution | `footer` absent |

- **Tabs:** the 11 source sections are reorganized into four user-intent areas:
  Overview, Deploy, Operate, and Integrate. Each tab exposes only the groups
  needed for that job, which keeps the desktop sidebar and mobile drawer
  scannable without changing the 63-page content set.
- **Products and versions:** deliberately omitted. The corpus describes one
  connected Netris platform and contains only the current 4.16 documentation;
  adding selectors would create destinations the repository cannot support.
- **Icons:** none. The source's sidebar and captions are text-only, so no
  `icon:` is set on any group or page (`style-docs` → *Icon parity*). Card icons
  on the homepage are a landing-page affordance, not navigation chrome.
- **Site root not duplicated:** `index` is not in any sidebar group. It is served
  at `/` and reachable from the navbar logo. Recorded here per Gate 1.
- **No single-page wrapper group with a duplicate label:** the consolidated
  changelog is a bare `"release-notes"` slug in Operate → Administration, not a
  one-page `Release Notes` group.
- **Nested groups:** V-Net is nested under Operate → Network Services because
  its child workflows share one clear parent. Controller, switch, and
  integration landing pages stay in their task groups, avoiding repeated
  `Group > Group` labels.
- **No external `href` inside a group's `pages`.**
- **No template defaults:** no Blog anchor, no Twitter/GitHub footer socials, no
  "Get started" CTA, no default favicon or site name.
- **Browser tab `<title>`:** Mintlify renders `<title> - Netris Documentation`.
  The source renders `<title> — Netris Documentation`. `docs.json.name` matches
  the source's suffix; the separator differs (Mintlify hardcodes ` - `) and is
  not natively overridable. Recorded as a known divergence.
- **Homepage chrome:** `index.mdx` uses `mode: "custom"`, so the sidebar, TOC,
  page header and footer-nav are hidden natively while the navbar stays
  identical to every content page. Navigating `/` ↔ any page shows no shift.

## Gate 4 — collapsibility parity

The source's RTD theme injects a clickable `span.toctree-expand` on every
sidebar entry that has children (`sphinx_rtd_theme`'s `theme.js`; the static HTML
contains no such markup, which is why this needs checking in a browser, not a
`curl`). Those entries render **collapsed** until the entry is active, and the
caption headings themselves are static and not collapsible.

Mintlify keeps the active tab's top-level groups expanded and nested groups
collapsed with a chevron until active. `expanded` is deliberately unset.
Page-set parity holds: 63 unique navigation entries, no duplicates, no orphans.

## Gate 5 — background and theme parity

Tokens were extracted from the source stylesheet and the marketing site, not
eyeballed.

| Token | Value | Source |
|---|---|---|
| `colors.primary` | `#01358d` | source `_static/styles.css` link / caption navy |
| `colors.light` | `#609fff` | netris.io light blue (dark-mode emphasis) |
| Brand accent (CSS) | `#f9556d` | source `.btn-neutral` / `.button` / hover coral |
| `fonts.family` | Montserrat | the family netris.io loads from Google Fonts |
| `appearance.default` | `light` | the source docs load light |
| Page background | Mintlify default (flat white / near-black) | the source body is a flat `#ffffff`; no `background.decoration` is set, so no `colors.primary`-derived tint |

- **Brand ramp consistency:** `primary` and `light` sit 1.5° apart in hue, and
  `light` is much brighter (L 68.8 vs 27.8), so dark-mode links and the active
  sidebar item pop at 7.35:1. `colors.dark` is **deliberately omitted**: any
  value darker than a navy primary fails `mint a11y`'s dark-on-dark-background
  check, and Mintlify falls back to `primary` for that role. This is the one
  intentional departure from the `preview-qa` ramp checklist, taken to keep
  `mint a11y` fully green.
- **Single-tone source:** the source paints one flat background behind the
  content, sidebar and navbar (`.wy-nav-side` and `.netris-header` are both
  `#fff`), so no per-region `custom.css` override is needed.
- **Link colour:** the source colours links navy and reserves coral for hover.
  `colors.primary` supplies the navy; `custom.css` adds the coral hover.
- **Contrast:** `mint a11y` reports PASS on all colours. The landing page's
  filled CTA uses a deepened coral (`#da3756`) so its white label reaches 4.5:1,
  while the verbatim source coral stays on decorative and large-text surfaces.

## Gate 6 — visual verification

The redesigned homepage and navigation were inspected in the in-app Chrome
runtime in light and dark desktop modes and at a 390×844 mobile viewport. The
mobile drawer, tab selector, task CTAs, hero image, and Deploy sidebar all render
without overflow, clipping, or contrast regressions.

Findings, all fixed:

1. Decorative hero glows rendered as hard-edged circles — Mintlify's Tailwind
   build does not reliably emit `blur-*`. Reimplemented as radial gradients in
   `custom.css`.
2. Landing-page CTA labels inherited the body-link colour. Replaced ad-hoc
   Tailwind button classes with reusable `.netris-btn-primary` /
   `.netris-btn-secondary` classes and excluded them from the link rule.
3. `lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]` did not compile (arbitrary
   Tailwind values), so the hero stacked at desktop width. Replaced with
   `lg:grid-cols-2`.
4. Every image rendered with an empty `alt`. Alt text now comes from the source
   `:alt:` option or the figure caption, falling back to the image filename.
5. `switch-agent-installation` and `cloudstack/netris-cloudstack` rendered
   blank, because each source page's entire body is a visible `toctree`. They
   now render the same child list as a Mintlify `<CardGroup>`.
6. A `custom.css` rule (`display: block; overflow-x: auto`) replaced Mintlify's
   native table scroll area and let the 6–8 column reference matrices overflow
   the content column. Removed; the native scroll area with its edge fade now
   handles them.
7. `<Update>` rail showed a truncated `4.16.0 Release Notes` description.
   Now the full source entry title minus its date parenthetical.

Asset integrity: all 211 images return real image bytes (no HTML fallbacks). The
two logo variants and the favicon were served as WebP by the CDN despite `.png`
URLs and were converted to real PNG, alpha-trimmed and normalised to 96px tall.

## Accepted items

1. **`markdown-url-support`, `content-negotiation`, `llms-txt-directive-md`
   fail locally.** `mint dev` does not serve `.md` URLs, `Accept: text/markdown`,
   `/llms.txt` generation or `/mcp` — these are platform-owned and provided by
   the hosted Mintlify deployment. Per `agent-ready-docs`, route handlers for
   them must not be added to the repo.
2. **`page-size-html` WARN on `release-notes.mdx`** (91K of converted markdown,
   95% of the source HTML being Mintlify's own chrome). Splitting it would
   contradict the mandated single-page `<Update>` changelog shape, and the
   Page Size category already scores 100/100.
3. **Browser tab separator** is ` - ` rather than the source's ` — `. Hardcoded
   by Mintlify with no override.
4. **No `description` frontmatter on migrated content pages.** The source's Sphinx
   `.. meta:: :description:` values are invisible metadata, whereas Mintlify
   renders `description` as visible subtitle text under the H1. Setting them
   would put text on the page that the source does not show
   (`preview-qa` Gate 2). The custom homepage now has a purpose-written
   description; the agent-readiness index carries a source-derived one-line
   summary per page in `llms.txt`, which is never rendered.
5. **One deliberate fix to broken source markup.** On `/bgp` the source renders
   `` :doc:`VPC Connect <vpc-connect>` `` literally, because the role is nested
   inside `**strong**`, which reStructuredText does not support. The converted
   page renders a working link instead of the leaked markup.

## Agent readiness (`npx afdocs check`)

| | Overall | Content discoverability |
|---|---|---|
| Baseline | 59 / 100 (F), capped by `llms-txt-exists` | 33 / 100 |
| After | **84 / 100 (B)** | **88 / 100** |

Page Size, Content Structure, URL Stability, Observability and Authentication
all score 100/100. The remaining gap is entirely Markdown Availability, which is
platform-owned (item 1 above) and will resolve on the deployed preview.

The improvement comes from a curated root `llms.txt`: Mintlify generates one
from `docs.json` plus frontmatter, but because this migration omits
`description` the generated index would be titles only. The curated file keeps
the source's own 11 section headings and adds a source-derived one-line summary
per page, with root-relative `.md` links (11.5K, well under the 50K threshold).

The score was re-measured after the second pass and holds at 84/100, confirming
it is at its repo-controllable ceiling.

## Second-pass audit

Run as a fresh review of what shipped in the first pass.

**Coverage re-crawl.** The mirror was re-fetched from scratch and diffed against
the first pass: the source rST is byte-identical, all 94 documents are still
discovered, every one is in the manifest, and every non-changelog page has an
MDX file. No gaps to fill.

**Findings fixed:**

1. **21 of 43 internal heading anchors did not resolve.** `mint broken-links`
   validates page paths but not `#fragment`s, so these were invisible to the
   first pass. Two causes:
   - Sphinx anchors and Mintlify anchors are unrelated. `.. _bgp-def:` before a
     section gives Sphinx the id `bgp-def`, while Mintlify derives the id from
     the heading text, so `/bgp#bgp-def` did not exist. Labels now resolve
     through the section title, never the Sphinx anchor.
   - The slug function did not match Mintlify's. Mintlify keeps `&`, `/` and em
     dashes, converts `.` to a hyphen, and keeps leading digits, so
     "9. Deploy North-South controller VIP (optional)" is
     `9-deploy-north-south-controller-vip-optional`. The replacement was fitted
     against all 651 content headings the preview renders and matches every one,
     including Mintlify's `-2`/`-3` disambiguation and the anchors generated from
     `<Update label>`.

   13 links whose Sphinx label targeted something Mintlify gives no anchor to
   (almost always the page's own H1, rendered from frontmatter rather than as a
   body heading) now drop the fragment and resolve to the correct page.
   `scripts/check_anchors.py` is the new gate: 33/33 fragments resolve, and all
   29 changelog redirect anchors resolve.

2. **Absolute self-links bounced readers to the customer's live docs.** Links of
   the form `https://www.netris.io/docs/en/latest/<page>.html` for a page this
   repo contains are now repo-relative. The two remaining absolute links are
   deliberate: one points at the 4.8 docs because the surrounding sentence says
   so, and one references a tutorial that no longer exists in the corpus.

3. **One sidebar label still carried pure boilerplate.** "Getting Started with
   Switch-Fabric Manager & VPC" wrapped to three lines; the prefix is redundant
   inside a group called Tutorials, so the sidebar now reads "Switch-Fabric
   Manager & VPC". The remaining labels over 30 characters were reviewed and
   left alone — they are distinct and meaningful, and over-stripping is worse
   than a two-line label.

**Reviewed and accepted:**

- **Duplicate headings on 5 pages** (e.g. two "Verification" sections). Mintlify
  disambiguates automatically (`verification`, `verification-2`), so there is no
  collision; the headings are source text and are preserved verbatim.
- **Visual review widened from a sample to all 63 content pages** at desktop
  width, plus dark mode and mobile on the component-heavy pages (tabs,
  accordions, callouts, wide tables, screenshots). No further defects found.
- **`vpc-gateways-with-managed-fabric` is a bare list of 15 links.** That is
  exactly what the source page is; adding intro copy would be invention, and
  restructuring it as `<Steps>` would duplicate each label as both a step title
  and a link. Left as the source has it.
- **`general-settings` renders an email as a `mailto:` link.** The source does
  the same (docutils auto-linkifies bare addresses). Parity is exact.
- **Navigation restructuring not needed.** 11 root groups, largest 11 pages;
  well inside the thresholds that trigger `/style-docs`'s restructuring workflow.
