// Headless screenshots for the /preview-qa visual verification gate.
//
//   node scripts/screenshot.mjs --out /tmp/qa --base http://localhost:3000 \
//     --paths / introduction bgp --modes light,dark --viewports desktop,mobile
//
// Uses the Puppeteer bundled with the `mint` CLI.

import { mkdir } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(
  path.join(process.env.HOME, ".npm-global/lib/node_modules/mint/package.json"),
);
const puppeteer = require("puppeteer");

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1) return fallback;
  return process.argv[i + 1];
}

function list(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1) return fallback;
  const out = [];
  for (let j = i + 1; j < process.argv.length && !process.argv[j].startsWith("--"); j++) {
    out.push(process.argv[j]);
  }
  return out.length ? out : fallback;
}

const outDir = arg("out", "/tmp/qa");
const base = arg("base", "http://localhost:3000");
const modes = arg("modes", "light").split(",");
const viewports = arg("viewports", "desktop").split(",");
const fullPage = process.argv.includes("--full");
const paths = list("paths", ["/"]);

const VIEWPORTS = {
  desktop: { width: 1440, height: 1000, deviceScaleFactor: 1 },
  mobile: { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true },
};

await mkdir(outDir, { recursive: true });

const browser = await puppeteer.launch({
  headless: "shell",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
});

for (const mode of modes) {
  for (const vp of viewports) {
    const page = await browser.newPage();
    await page.setViewport(VIEWPORTS[vp]);
    await page.emulateMediaFeatures([
      { name: "prefers-color-scheme", value: mode },
    ]);
    for (const p of paths) {
      const slug = p.replace(/^\/+|\/+$/g, "") || "home";
      const url = `${base.replace(/\/$/, "")}/${p.replace(/^\/+/, "")}`;
      try {
        await page.goto(url, { waitUntil: "networkidle2", timeout: 90000 });
        if (mode === "dark" || mode === "light") {
          // Mintlify persists the theme choice in localStorage; force it so the
          // screenshot matches the requested mode regardless of default.
          await page.evaluate((m) => {
            document.documentElement.classList.toggle("dark", m === "dark");
            document.documentElement.style.colorScheme = m;
          }, mode);
        }
        await new Promise((r) => setTimeout(r, 1200));
        const file = path.join(outDir, `${slug.replace(/\//g, "_")}-${mode}-${vp}.png`);
        await page.screenshot({ path: file, fullPage });
        console.log(`ok   ${file}`);
      } catch (err) {
        console.log(`FAIL ${url}  ${err.message}`);
      }
    }
    await page.close();
  }
}

await browser.close();
