#!/usr/bin/env python3
"""
screenshot_ui.py — screenshot-ui skill (Python implementation)

Usage:
    python scripts/screenshot_ui.py
    python scripts/screenshot_ui.py --url http://localhost:8080
    python scripts/screenshot_ui.py --output-dir screenshots
    python scripts/screenshot_ui.py --delay 15   # manual login window

Auto-discovers routes via DOM crawl; falls back to MANUAL_ROUTES below.
Injects screenshots into project README.md.

Requires:
    pip install playwright
    python -m playwright install chromium
"""

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Config (edit these or override via CLI) ───────────────────────────────────

BASE_URL = "http://localhost:8080"   # changed to match fifa-2026 dashboard
OUTPUT_DIR = "screenshots"            # relative to project root

VIEWPORT = {"width": 1440, "height": 900}
EXTRA_DELAY_MS = 1200                 # ms to wait after page load
DEVICE_SCALE_FACTOR = 2              # 2 = retina quality

# CSS selectors tried when discovering nav links
NAV_SELECTORS = [
    "nav a",
    "header a",
    '[role="navigation"] a',
    ".navbar a",
    ".nav-links a",
    ".sidebar a",
    ".menu a",
    '[class*="nav"] a',
    '[class*="menu"] a',
    '[class*="sidebar"] a',
    '[class*="tab"] a',
]

# Selectors for tab-based SPAs (no URL change on tab click)
TAB_SELECTORS = [
    'button[role="tab"]',
    '[role="tablist"] button',
    '[class*="tab"] button',
]

# Fallback routes if DOM discovery fails
MANUAL_ROUTES: list[dict] = [
    # { "path": "/", "name": "home" },
    # { "path": "/dashboard", "name": "dashboard" },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def slugify(text: str) -> str:
    s = text.lower().strip("/").replace("/", "_")
    s = re.sub(r"[^a-z0-9_-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "home"


def title_case(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def sleep_ms(ms: int):
    time.sleep(ms / 1000)


# ── Route discovery ───────────────────────────────────────────────────────────

def discover_routes(page, base_url: str) -> list[dict]:
    """Return list of {path, name, type} dicts."""
    from urllib.parse import urlparse
    base_origin = urlparse(base_url).scheme + "://" + urlparse(base_url).netloc

    found: dict[str, str] = {}

    for selector in NAV_SELECTORS:
        try:
            links = page.eval_on_selector_all(
                selector,
                """els => els.map(el => ({
                    href: el.href || "",
                    text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || "").trim()
                }))"""
            )
            for link in links:
                href = link.get("href", "")
                text = link.get("text", "")
                try:
                    parsed = urlparse(href)
                    origin = parsed.scheme + "://" + parsed.netloc
                    if origin == base_origin and parsed.path and parsed.path not in found:
                        found[parsed.path] = text or parsed.path
                except Exception:
                    pass
        except Exception:
            pass

    if len(found) > 1:
        logger.info("  ✅ Found %d routes via nav links", len(found))
        return [
            {"path": p, "name": slugify(name) or slugify(p), "type": "route"}
            for p, name in found.items()
        ]

    # Check for tab-based SPA
    for sel in TAB_SELECTORS:
        try:
            tabs = page.eval_on_selector_all(
                sel,
                """els => els.map((el, i) => ({
                    text: (el.innerText || el.getAttribute("aria-label") || "").trim(),
                    index: i
                }))"""
            )
            if len(tabs) > 1:
                logger.info("  ✅ Found %d tabs via tab selectors", len(tabs))
                return [
                    {
                        "path": "/",
                        "name": slugify(t["text"]) or f"tab-{t['index']}",
                        "type": "tab",
                        "tab_index": t["index"],
                        "tab_selector": sel,
                    }
                    for t in tabs
                ]
        except Exception:
            pass

    # Fallback
    logger.warning(
        "  ⚠️  DOM found %d route(s) — using %d manual routes", len(found), len(MANUAL_ROUTES)
    )
    return [
        {"path": r["path"], "name": slugify(r.get("name") or r["path"]), "type": "route"}
        for r in MANUAL_ROUTES
    ]


# ── Screenshot logic ──────────────────────────────────────────────────────────

def take_screenshots(base_url: str, output_dir: Path, login_delay: int = 0) -> list[dict]:
    """Run Playwright, capture all routes, return result list."""
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE_FACTOR,
            locale="en-US",
        )
        page = context.new_page()

        # Suppress app console noise
        page.on("console", lambda _: None)
        page.on("pageerror", lambda _: None)

        logger.info("  📄 Loading root page: %s", base_url)
        page.goto(base_url, wait_until="networkidle", timeout=30000)
        sleep_ms(EXTRA_DELAY_MS)

        if login_delay > 0:
            logger.info("  🔐 Login window: %ds — complete login now...", login_delay)
            time.sleep(login_delay)
            page.goto(base_url, wait_until="networkidle", timeout=30000)
            sleep_ms(EXTRA_DELAY_MS)

        routes = discover_routes(page, base_url)

        # Ensure root is present for route-based apps
        has_root = any(r["path"] in ("/", "") for r in routes)
        if not has_root and (not routes or routes[0]["type"] == "route"):
            routes.insert(0, {"path": "/", "name": "home", "type": "route"})

        # Deduplicate
        seen: set[str] = set()
        unique = []
        for r in routes:
            key = f"{r['path']}::{r['name']}"
            if key not in seen:
                seen.add(key)
                unique.append(r)

        logger.info(
            "  📋 Capturing %d pages: %s",
            len(unique),
            ", ".join(r["name"] for r in unique),
        )

        for route in unique:
            out_file = output_dir / f"{route['name']}.png"
            logger.info("  📸 [%s]...", route["name"])

            try:
                if route["type"] == "tab":
                    tab_els = page.query_selector_all(route["tab_selector"])
                    idx = route["tab_index"]
                    if idx < len(tab_els):
                        tab_els[idx].click()
                        sleep_ms(EXTRA_DELAY_MS)
                        # Dismiss toasts/overlays
                        page.evaluate(
                            """() => document.querySelectorAll(
                                '[role="alert"], .toast, .notification'
                            ).forEach(el => el.remove())"""
                        )
                        page.screenshot(path=str(out_file), full_page=False)
                        logger.info("  ✅ %s (tab %d)", route["name"], idx)
                        results.append({"name": route["name"], "file": str(out_file.relative_to(PROJECT_ROOT)), "status": "ok"})
                    else:
                        raise IndexError(f"Tab index {idx} out of range ({len(tab_els)} tabs found)")
                else:
                    url = base_url.rstrip("/") + route["path"]
                    page.goto(url, wait_until="networkidle", timeout=20000)
                    sleep_ms(EXTRA_DELAY_MS)
                    page.evaluate(
                        """() => document.querySelectorAll(
                            '[role="alert"], .toast, .notification'
                        ).forEach(el => el.remove())"""
                    )
                    page.screenshot(path=str(out_file), full_page=False)
                    logger.info("  ✅ %s → %s", route["name"], url)
                    results.append({"name": route["name"], "file": str(out_file.relative_to(PROJECT_ROOT)), "status": "ok"})

            except Exception as exc:
                logger.warning("  ❌ %s: %s", route["name"], exc)
                try:
                    page.screenshot(path=str(out_file), full_page=False)
                    results.append({"name": route["name"], "file": str(out_file.relative_to(PROJECT_ROOT)), "status": "partial"})
                except Exception:
                    results.append({"name": route["name"], "file": str(out_file.relative_to(PROJECT_ROOT)), "status": "error", "error": str(exc)})

        browser.close()

    return results


# ── README injection ──────────────────────────────────────────────────────────

def build_screenshot_markdown(results: list[dict]) -> str:
    ok = [r for r in results if r["status"] in ("ok", "partial")]
    if not ok:
        return ""

    cols = 3 if len(ok) >= 3 else len(ok)
    lines = ["## Screenshots", ""]

    for i in range(0, len(ok), cols):
        group = ok[i:i + cols]
        header = "| " + " | ".join(title_case(r["name"]) for r in group) + " |"
        sep    = "| " + " | ".join("---" for _ in group) + " |"
        images = "| " + " | ".join(
            f'![{title_case(r["name"])}]({r["file"].replace(os.sep, "/")})'
            for r in group
        ) + " |"
        lines += [header, sep, images, ""]

    return "\n".join(lines)


def inject_readme(readme_path: Path, markdown_block: str):
    if not readme_path.exists():
        logger.info("  ℹ️  README not found at %s — skipping injection", readme_path)
        return

    content = readme_path.read_text(encoding="utf-8")
    start_marker = "<!-- screenshots -->"
    end_marker   = "<!-- /screenshots -->"
    block = f"{start_marker}\n{markdown_block}\n{end_marker}"

    if start_marker in content and end_marker in content:
        content = re.sub(
            re.escape(start_marker) + r"[\s\S]*?" + re.escape(end_marker),
            block,
            content,
        )
        logger.info("  ✏️  Updated existing <!-- screenshots --> block in README")
    elif start_marker in content:
        content = content.replace(start_marker, block)
        logger.info("  ✏️  Replaced <!-- screenshots --> marker in README")
    else:
        content = content.rstrip() + "\n\n" + block + "\n"
        logger.info("  ✏️  Appended ## Screenshots section to README")

    readme_path.write_text(content, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Screenshot UI — screenshot-ui skill")
    parser.add_argument("--url",        default=BASE_URL,    help=f"Base URL (default: {BASE_URL})")
    parser.add_argument("--output-dir", default=OUTPUT_DIR,  help=f"Output directory (default: {OUTPUT_DIR})")
    parser.add_argument("--delay",      type=int, default=0, help="Manual login window in seconds")
    parser.add_argument("--no-readme",  action="store_true", help="Skip README injection")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = PROJECT_ROOT / args.output_dir
    logger.info("🚀 Screenshot UI — starting")
    logger.info("   URL:    %s", args.url)
    logger.info("   Output: %s", output_dir)

    results = take_screenshots(args.url, output_dir, login_delay=args.delay)

    # Inject README
    if not args.no_readme:
        md_block = build_screenshot_markdown(results)
        if md_block:
            inject_readme(PROJECT_ROOT / "README.md", md_block)

    # Summary
    print("\n── Summary ──────────────────────────────────────────────────")
    ok  = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    print(f"  {ok} captured, {err} failed")
    for r in results:
        icon = "✅" if r["status"] == "ok" else ("⚠️" if r["status"] == "partial" else "❌")
        print(f"  {icon}  {r['name']}.png")
    print(f"\n📁 Screenshots: {output_dir}")
    print(f"📝 README:      {PROJECT_ROOT / 'README.md'}")


if __name__ == "__main__":
    main()
