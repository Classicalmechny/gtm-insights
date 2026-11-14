"""Centralized title list (ICP persona) for all people-finder scripts."""
import re

# Order matters for primary preference, but all are equally accepted.
TITLES = [
    # Founders / CEOs / Owners
    "Founder", "Co-Founder", "Co Founder", "Cofounder",
    "CEO", "Chief Executive Officer",
    "Owner", "President", "Principal", "Managing Director",
    # Brand
    "Head of Brand", "Brand Director", "VP Brand", "VP of Brand",
    # Creative
    "Creative Director", "Head of Creative", "VP Creative",
    # E-commerce / DTC
    "Head of E-commerce", "Head of Ecommerce", "Head of E commerce",
    "Head of DTC", "Head of D2C", "Head of Direct to Consumer",
    "VP E-commerce", "VP Ecommerce", "Director of E-commerce", "Director of DTC",
    "Chief Marketing Officer", "CMO", "Chief Brand Officer",
]

# Substring-match regex covering all variants (case-insensitive).
# Excludes junior titles: Brand Manager, Assistant *, Personal *, Strategist, Coordinator.
TITLES_RX = re.compile(
    r"("
    r"founder|cofounder|co.?founder|"
    r"chief executive|\bceo\b|"
    r"owner|\bpresident\b|principal|managing director|"
    r"head of brand|brand director|vp of brand|vp brand|"
    r"creative director|head of creative|vp creative|design director|art director|"
    r"head of e.?commerce|head of dtc|head of d2c|head of direct to consumer|"
    r"vp e.?commerce|director of e.?commerce|director of dtc|director of marketing|"
    r"chief marketing officer|\bcmo\b|chief brand officer"
    r")",
    re.IGNORECASE,
)
TITLES_RX_EXCLUDE = re.compile(
    r"(assistant|personal brand|coordinator|associate|intern|trainee|former|ex.?|previous)",
    re.IGNORECASE,
)
