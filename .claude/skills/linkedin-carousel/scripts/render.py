#!/usr/bin/env python3
"""
LinkedIn Carousel Renderer
Renders a multi-slide PDF carousel from a JSON spec.

Usage:
    python render_carousel.py output/<topic-slug>/spec.json
    python render_carousel.py output/<topic-slug>/spec.json --slides 3,5
    python render_carousel.py output/<topic-slug>/spec.json --no-pdf
"""

import argparse
import json
import os
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright
import img2pdf

SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"
ASSETS_DIR = SKILL_ROOT
BRAND_FILE = SKILL_ROOT / "brand.json"


def load_brand():
    with open(BRAND_FILE) as f:
        return json.load(f)


def resolve_asset_path(rel_path):
    """Convert a relative asset path in brand.json to a file:// URL."""
    if not rel_path:
        return None
    if rel_path.startswith(("http://", "https://", "file://")):
        return rel_path
    abs_path = (SKILL_ROOT / rel_path).resolve()
    if not abs_path.exists():
        print(f"  WARNING: asset {rel_path} not found at {abs_path}", file=sys.stderr)
        return None
    return f"file://{abs_path}"


def render_slide(env, brand, slide, page_total, output_dir):
    """Render a single slide HTML to PNG."""
    template_name = slide["template"]
    template = env.get_template(f"{template_name}.html")

    # Page counter
    counter_format = brand["page_counter"]["format"]
    page_counter = ""
    if template_name not in ("cover", "cta_close"):
        page_counter = counter_format.format(
            current=slide["slide_number"], total=page_total
        )

    # Asset paths (resolve relative to skill root)
    photo_cover = resolve_asset_path(brand["assets"]["photo_cover"])
    photo_close = resolve_asset_path(brand["assets"]["photo_close"])
    background_image = slide.get("background_image")
    if background_image:
        background_image = resolve_asset_path(background_image)
    proof_image = slide.get("proof_image")
    if proof_image:
        proof_image = resolve_asset_path(proof_image)

    context = {
        # Brand tokens
        "colors": brand["colors"],
        "fonts": brand["fonts"],
        "dimensions": brand["dimensions"],
        # Per-slide data merged from spec
        **slide,
        # Computed
        "handle": brand["handle"],
        "page_counter": page_counter,
        "next_text": brand["footer"]["next_text"],
        "photo_cover": photo_cover,
        "photo_close": photo_close,
        "background_image": background_image,
        "proof_image": proof_image,
        "slide_title": f"Slide {slide['slide_number']}",
    }

    html = template.render(**context)
    return html


def screenshot_html(html, output_path, width, height):
    """Use Playwright to screenshot an HTML string at exact dimensions."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html, wait_until="networkidle")
        # wait for fonts
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(output_path), full_page=False, omit_background=False)
        browser.close()


def assemble_pdf(slide_paths, pdf_path):
    """Combine PNG slides into a single PDF."""
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in slide_paths]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="Path to spec.json")
    ap.add_argument("--slides", help="Comma-separated slide numbers to re-render only (e.g., '3,5')")
    ap.add_argument("--no-pdf", action="store_true", help="Skip PDF assembly")
    ap.add_argument("--preview", action="store_true", help="Render at half resolution for speed")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"ERROR: spec not found at {spec_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = spec_path.parent
    slides_dir = output_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    with open(spec_path) as f:
        spec = json.load(f)

    brand = load_brand()
    width = brand["dimensions"]["width"]
    height = brand["dimensions"]["height"]
    if args.preview:
        width //= 2
        height //= 2

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    target_slides = None
    if args.slides:
        target_slides = {int(s.strip()) for s in args.slides.split(",")}

    page_total = len(spec["slides"])
    rendered_paths = []

    for slide in spec["slides"]:
        slide_num = slide["slide_number"]
        out_path = slides_dir / f"{slide_num:02d}.png"

        if target_slides is not None and slide_num not in target_slides:
            # Reuse the existing PNG
            if out_path.exists():
                rendered_paths.append(out_path)
            continue

        print(f"  Rendering slide {slide_num} ({slide['template']})...")
        html = render_slide(env, brand, slide, page_total, output_dir)
        screenshot_html(html, out_path, width, height)
        rendered_paths.append(out_path)

    rendered_paths.sort()

    if not args.no_pdf and not args.preview:
        pdf_path = output_dir / "carousel.pdf"
        # gather ALL slides for PDF, not just re-rendered ones
        all_paths = sorted(slides_dir.glob("*.png"))
        assemble_pdf(all_paths, pdf_path)
        print(f"\nPDF written: {pdf_path}")

    print(f"Rendered {len(rendered_paths)} slide(s).")


if __name__ == "__main__":
    main()
