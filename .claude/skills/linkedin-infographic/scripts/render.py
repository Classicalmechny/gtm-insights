#!/usr/bin/env python3
"""
LinkedIn Infographic Renderer
Renders a single tall infographic image (PNG + PDF) from a JSON spec.

Usage:
    python render_infographic.py output/<topic-slug>/spec.json
    python render_infographic.py output/<topic-slug>/spec.json --width 1200
"""

import argparse
import json
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright
import img2pdf

SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"
ASSETS_DIR = SKILL_ROOT
INFOGRAPHIC_BRAND_FILE = SKILL_ROOT / "brand.json"


def load_brand():
    with open(INFOGRAPHIC_BRAND_FILE) as f:
        return json.load(f)


def resolve_asset_path(rel_path):
    """Inline images as base64 data URIs to avoid file:// races and space-in-path issues."""
    if not rel_path:
        return None
    if rel_path.startswith(("http://", "https://", "data:")):
        return rel_path
    if rel_path.startswith("file://"):
        return rel_path
    abs_path = (SKILL_ROOT / rel_path).resolve()
    if not abs_path.exists():
        print(f"  WARNING: asset {rel_path} not found at {abs_path}", file=sys.stderr)
        return None
    import base64, mimetypes
    mime, _ = mimetypes.guess_type(str(abs_path))
    if not mime:
        mime = "application/octet-stream"
    with open(abs_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def resolve_profile_assets(profile_data):
    if not profile_data:
        return None
    if "photo" in profile_data:
        profile_data = dict(profile_data)
        profile_data["photo"] = resolve_asset_path(profile_data["photo"])
    return profile_data


def render_html(env, brand, spec):
    template_name = spec["template"]
    template = env.get_template(f"{template_name}.html")

    # Resolve profile assets
    profile = resolve_profile_assets(spec.get("profile"))

    # Resolve any image paths in cta_repost / sections
    cta_repost = spec.get("cta_repost")
    if cta_repost and "photo" in cta_repost:
        cta_repost = dict(cta_repost)
        cta_repost["photo"] = resolve_asset_path(cta_repost["photo"])

    sections = spec.get("sections", [])
    for section in sections:
        if "image" in section:
            section["image"] = resolve_asset_path(section["image"])

    columns = spec.get("columns", [])
    for col in columns:
        if "logo" in col:
            col["logo"] = resolve_asset_path(col["logo"])

    context = {
        "dimensions": brand["dimensions"],
        **spec,
        "profile": profile,
        "cta_repost": cta_repost,
    }

    return template.render(**context)


def screenshot_locked(html, output_path, width, height):
    """Screenshot a fixed-canvas page. Width and height are both locked — if content
    overflows, the spec must be tightened. Uses viewport screenshot (not full_page)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_function(
            "Array.from(document.images).every(img => img.complete && img.naturalHeight > 0)",
            timeout=15000,
        )
        # Detect overflow so we can warn the user before they see a clipped image.
        overflow = page.evaluate(
            "({sh: document.documentElement.scrollHeight, h: window.innerHeight})"
        )
        if overflow["sh"] > overflow["h"] + 1:
            print(
                f"  WARNING: content overflows the locked canvas — "
                f"document height {overflow['sh']}px vs canvas {overflow['h']}px. "
                f"Tighten copy / drop points / use compact mode.",
                file=sys.stderr,
            )
        page.wait_for_timeout(300)
        page.screenshot(path=str(output_path), full_page=False, omit_background=False)
        browser.close()


def png_to_pdf(png_path, pdf_path):
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert([str(png_path)]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="Path to spec.json")
    ap.add_argument("--width", type=int, default=None, help="Override width (default from brand)")
    ap.add_argument("--height", type=int, default=None, help="Override height (default from brand)")
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"ERROR: spec not found at {spec_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = spec_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(spec_path) as f:
        spec = json.load(f)

    brand = load_brand()
    width = args.width or brand["dimensions"]["width"]
    height = args.height or brand["dimensions"].get("height", 1350)

    # Inject dimensions into spec for the template
    spec.setdefault("dimensions", brand["dimensions"])
    spec["dimensions"]["width"] = width
    spec["dimensions"]["height"] = height

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    print(f"  Rendering infographic ({spec['template']}) at {width}x{height}...")
    html = render_html(env, brand, spec)

    # Save HTML for debugging
    html_path = output_dir / "infographic.html"
    with open(html_path, "w") as f:
        f.write(html)

    png_path = output_dir / "infographic.png"
    screenshot_locked(html, png_path, width, height)
    print(f"PNG written: {png_path}")

    if not args.no_pdf:
        pdf_path = output_dir / "infographic.pdf"
        png_to_pdf(png_path, pdf_path)
        print(f"PDF written: {pdf_path}")


if __name__ == "__main__":
    main()
