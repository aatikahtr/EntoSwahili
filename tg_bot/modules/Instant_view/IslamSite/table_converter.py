"""
    Geuza HTML <table> kuwa Telegraph-compatible nodes.

    Inatambua aina 3 za tables:
    ──────────────────────────
    1. SPECS TABLE  (GSMArena-style: category | label | value)
       → Kichwa cha category = <h4>
       → Kila row = <p><b>Label</b>  Value</p>

    2. TWO-COLUMN TABLE  (label | value, bila category)
       → Kila row = <p><b>Label</b>  Value</p>

    3. GENERAL TABLE  (data table ya kawaida)
       → Header row (th) = <h4>Col1 · Col2 · Col3</h4>
       → Data rows = <p>Val1 · Val2 · Val3</p>
    ──────────────────────────
    """

# Standard library
import re

# Third-party
from bs4 import BeautifulSoup, NavigableString

# Local modules
from .constants import NOISE_TEXTS



def extract_cell_text(cell) -> str:
    """Pata text safi kutoka td/th, safisha whitespace."""
    return re.sub(r'\s+', ' ', cell.get_text(separator=" ", strip=True))





def convert_to_telegraph(table_tag, base_url: str, soup: BeautifulSoup) -> list:
    
    result = []

    # Kusanya rows zote — ignore thead/tbody/tfoot structure
    all_rows = table_tag.find_all("tr")
    if not all_rows:
        return []

    # ── Chunguza muundo wa table ──
    col_counts = []
    for row in all_rows:
        cells = row.find_all(["td", "th"])
        if cells:
            col_counts.append(len(cells))

    if not col_counts:
        return []

    max_cols = max(col_counts)

    # Angalia kama ni specs table (3 cols, col ya kwanza inajirudia — rowspan)
    # au two-column table
    is_specs = max_cols >= 3
    is_two_col = max_cols == 2

    current_category = None  # Kwa specs tables

    for row in all_rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        texts = [extract_cell_text(c) for c in cells]
        texts = [t for t in texts if t]  # Futa tupu

        if not texts:
            continue

        # ── SPECS TABLE (GSMArena, PhoneArena, n.k.) ──────
        if is_specs:
            num_cells = len(cells)

            if num_cells == 1:
                # Row ya category peke yake (rowspan row)
                cat_text = texts[0]
                if cat_text and cat_text.lower() not in NOISE_TEXTS:
                    current_category = cat_text
                    h4 = soup.new_tag("h4")
                    h4.append(NavigableString(f"▸ {cat_text}"))
                    result.append(h4)

            elif num_cells == 2:
                # Category imekwisha, row hii ni label + value
                label, value = texts[0], texts[1]
                if label.lower() in NOISE_TEXTS or not value:
                    continue
                p = soup.new_tag("p")
                b = soup.new_tag("b")
                b.append(NavigableString(label))
                p.append(b)
                p.append(NavigableString(f"  {value}"))
                result.append(p)

            elif num_cells >= 3:
                # category | label | value  (classic GSMArena)
                cat_text = texts[0]
                label = texts[1] if len(texts) > 1 else ""
                value = texts[2] if len(texts) > 2 else ""

                # Category mpya
                if cat_text and cat_text != current_category:
                    current_category = cat_text
                    h4 = soup.new_tag("h4")
                    h4.append(NavigableString(f"▸ {cat_text}"))
                    result.append(h4)

                # Row ya data
                if label and value:
                    p = soup.new_tag("p")
                    b = soup.new_tag("b")
                    b.append(NavigableString(label))
                    p.append(b)
                    p.append(NavigableString(f"  {value}"))
                    result.append(p)
                elif value and not label:
                    # Extra value bila label (continuation)
                    p = soup.new_tag("p")
                    p.append(NavigableString(f"    ↳ {value}"))
                    result.append(p)

        # ── TWO-COLUMN TABLE ───
        elif is_two_col:
            if len(texts) == 1:
                # Header row
                h4 = soup.new_tag("h4")
                h4.append(NavigableString(texts[0]))
                result.append(h4)
            else:
                label, value = texts[0], texts[1]
                # Angalia kama cells ni th (headers)
                is_header_row = all(c.name == "th" for c in cells)
                if is_header_row:
                    h4 = soup.new_tag("h4")
                    h4.append(NavigableString(f"{label}  ·  {value}"))
                    result.append(h4)
                else:
                    p = soup.new_tag("p")
                    b = soup.new_tag("b")
                    b.append(NavigableString(label))
                    p.append(b)
                    p.append(NavigableString(f"  {value}"))
                    result.append(p)

        # ── GENERAL TABLE ───
        else:
            is_header_row = any(c.name == "th" for c in cells)
            joined = "  ·  ".join(texts)

            if is_header_row:
                h4 = soup.new_tag("h4")
                h4.append(NavigableString(joined))
                result.append(h4)
            else:
                p = soup.new_tag("p")
                p.append(NavigableString(joined))
                result.append(p)

    return result
