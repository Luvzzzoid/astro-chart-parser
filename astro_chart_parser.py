import streamlit as st
import re
from PyPDF2 import PdfReader
from collections import defaultdict
import streamlit.components.v1 as components

# -------- SETTINGS --------
ZODIAC = {
    'a': ('Aries', 0), 'b': ('Taurus', 30), 'c': ('Gemini', 60), 'd': ('Cancer', 90),
    'e': ('Leo', 120), 'f': ('Virgo', 150), 'g': ('Libra', 180), 'h': ('Scorpio', 210),
    'i': ('Sagittarius', 240), 'j': ('Capricorn', 270), 'k': ('Aquarius', 300), 'l': ('Pisces', 330)
}

ASPECTS = [
    ("conjunct", 0), ("sextile", 60), ("square", 90), ("trine", 120), ("opposite", 180),
]

NAME_FIX = {
    "P.Fort.": "Part of Fortune",
    "MC": "Midheaven",
    "Asc.": "Ascendant",
}

# Planets & key points — always go to Placements, never Asteroids
CORE_OBJECTS = {
    "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
    "Uranus", "Neptune", "Pluto", "Ascendant", "Midheaven", "Vertex",
    "Part of Fortune", "Lilith", "Chiron",
    "Mean Node", "True Node",
}

# Degree token — matches D°M'S", D°M', or D°
DEG_TOKEN = r'(?:\d{1,2}°\s*\d{1,2}\'\s*\d{1,2}"|\d{1,2}°\s*\d{1,2}\'|\d{1,2}°)'


def ordinal(n: int) -> str:
    if n < 1:
        n = 1
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def parse_deg_string(s: str) -> float | None:
    s = s.replace(" ", "")
    m = (re.match(r"(\d+)°(\d+)'(\d+)\"", s) or
         re.match(r"(\d+)°(\d+)'", s) or
         re.match(r"(\d+)°", s))
    if not m:
        return None
    d = int(m.group(1))
    mnt = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else 0
    sec = int(m.group(3)) if m.lastindex and m.lastindex >= 3 and m.group(3) else 0
    return d + mnt / 60 + sec / 3600


def extract_title(pdf_text: str) -> str:
    m = re.search(r'([A-Za-z0-9 #]+Chart)\s*\(Data Sheet[s]?\)', pdf_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return "Chart"


def parse_planet_rows(lines):
    """Parse main planet/point rows (single uppercase letter code at start).
    Handles retrograde (#) and direct (D) markers after the degree value."""
    placements, objects = [], []
    pat = re.compile(
        rf'^(?P<code>[A-Z])\s+(?P<label>[A-Za-z\.\* ]+?)\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})[#RD]?\s+(?:#\s*)?(?P<house>\d+)\b'
    )
    for line in lines:
        m = pat.match(line)
        if not m:
            continue
        label = NAME_FIX.get(m.group('label').strip(), m.group('label').strip())
        sign_code = m.group('sign')
        deg_text = re.sub(r'\s+', ' ', m.group('deg').strip())
        house = int(m.group('house'))
        sign_name, sign_base = ZODIAC[sign_code]
        lon30 = parse_deg_string(deg_text) or 0.0
        abs_lon = sign_base + lon30
        placements.append((label, sign_name, house, deg_text))
        objects.append((label, abs_lon))
    return placements, objects


def parse_asteroids(lines):
    """
    Parse asteroid rows (lines beginning with #letter code).
    KEY FIX: allow optional retrograde '#' immediately after the degree value.
    Skips any entry whose cleaned name is in CORE_OBJECTS (e.g. Vertex).
    """
    asts, objs = [], []
    pat = re.compile(
        rf'^#\w+\s+(?P<rawname>.*?)\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})[#RD]?\s+(?P<house>\d+)\b'
    )
    for line in lines:
        m = pat.match(line)
        if not m:
            continue
        raw = m.group('rawname').strip()
        # Strip leading catalog numbers: "408 Fama" → "Fama", "*Regulus" → "Regulus"
        name = re.sub(r'^\d+\s*', '', raw)          # remove leading number
        name = re.sub(r'^[^A-Za-z*]+', '', name)    # remove remaining non-alpha (but keep *)
        if name in CORE_OBJECTS:
            continue
        sign_code = m.group('sign')
        deg_text = re.sub(r'\s+', ' ', m.group('deg').strip())
        house = int(m.group('house'))
        sign_name, sign_base = ZODIAC[sign_code]
        lon30 = parse_deg_string(deg_text) or 0.0
        abs_lon = sign_base + lon30
        asts.append((name, sign_name, house, deg_text))
        objs.append((name, abs_lon))
    return asts, objs


def get_house_lines(lines):
    """Grab lines between 'Houses' header and 'Aspects' header."""
    house_lines, in_houses = [], False
    for ln in lines:
        if "Houses" in ln:
            in_houses = True
            continue
        if in_houses:
            if ln.strip().startswith("Aspects"):
                break
            house_lines.append(ln)
    return house_lines


def parse_houses_section(lines):
    """Parse Ascendant and Midheaven from the Houses section."""
    placements, objects = [], []
    asc_pat = re.compile(rf'^Asc\.\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})')
    mc_pat = re.compile(rf'^MC\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})')
    for line in lines:
        s = line.strip()
        ma = asc_pat.match(s)
        if ma:
            sign_code, deg_text = ma.group('sign'), re.sub(r'\s+', ' ', ma.group('deg').strip())
            sign_name, sign_base = ZODIAC[sign_code]
            lon30 = parse_deg_string(deg_text) or 0.0
            placements.append(("Ascendant", sign_name, 1, deg_text))
            objects.append(("Ascendant", sign_base + lon30))
        mm = mc_pat.match(s)
        if mm:
            sign_code, deg_text = mm.group('sign'), re.sub(r'\s+', ' ', mm.group('deg').strip())
            sign_name, sign_base = ZODIAC[sign_code]
            lon30 = parse_deg_string(deg_text) or 0.0
            placements.append(("Midheaven", sign_name, 10, deg_text))
            objects.append(("Midheaven", sign_base + lon30))
    return placements, objects


def merge_no_dupe(base, additions):
    """Add items from additions to base, skipping names already present."""
    names = {x[0] for x in base}
    for item in additions:
        if item[0] not in names:
            base.append(item)
            names.add(item[0])
    return base


def compute_aspects(objects, orb_limit=3.0):
    hits = []
    for i in range(len(objects)):
        n1, lon1 = objects[i]
        for j in range(i + 1, len(objects)):
            n2, lon2 = objects[j]
            diff = abs((lon1 - lon2) % 360.0)
            if diff > 180:
                diff = 360 - diff
            for asp_name, angle in ASPECTS:
                if abs(diff - angle) <= orb_limit + 1e-9:
                    hits.append((n1, asp_name, n2))
    return hits


# -------- STREAMLIT APP --------
st.title("Astro.com Chart Parser")

pdf_file = st.file_uploader("Upload your Astro.com PDF", type=["pdf"])

show_degrees = st.checkbox("Show degrees in placements", value=True)
orb_limit = st.slider("Aspect orb limit (degrees)", 1, 10, 3)

if pdf_file is not None:
    reader = PdfReader(pdf_file)
    full_text = "\n".join(page.extract_text() for page in reader.pages)
    lines = full_text.splitlines()

    title = extract_title(full_text)
    planet_lines = [ln for ln in lines if re.match(r'^[A-Z]\s+[A-Z]', ln)]
    house_lines = get_house_lines(lines)

    placements_p, objects_p = parse_planet_rows(planet_lines)
    asteroids_p, objects_a = parse_asteroids(lines)
    ascmc_p, asc_mc_objs = parse_houses_section(house_lines)

    placements_main = merge_no_dupe(list(placements_p), ascmc_p)
    placements_ast = list(asteroids_p)

    names_seen, objects_all = set(), []
    for name, lon in objects_p + asc_mc_objs + objects_a:
        if name not in names_seen:
            names_seen.add(name)
            objects_all.append((name, lon))

    aspects = compute_aspects(objects_all, orb_limit)

    # --- Display ---
    st.subheader(title)

    output_lines = [f"### {title}\n", "Placements:"]

    st.markdown("### Placements")
    for name, sign, house, deg in placements_main:
        line = f"* {name}: {sign}, {ordinal(house)} house" + (f", {deg}" if show_degrees else "")
        st.write(line)
        output_lines.append(line)

    if placements_ast:
        st.markdown(f"### Asteroids ({len(placements_ast)})")
        output_lines.append(f"\nAsteroids ({len(placements_ast)}):")
        for name, sign, house, deg in placements_ast:
            line = f"* {name}: {sign}, {ordinal(house)} house" + (f", {deg}" if show_degrees else "")
            st.write(line)
            output_lines.append(line)

    st.markdown(f"### Aspects (orb ≤ {orb_limit}°)")
    output_lines.append(f"\nAspects (orb ≤ {orb_limit}°):")
    grouped = defaultdict(list)
    for a, asp, b in aspects:
        grouped[(a, asp)].append(b)

    if grouped:
        for (a, asp), bs in grouped.items():
            line = f"* {a} {asp} {', '.join(bs)}"
            st.write(line)
            output_lines.append(line)
    else:
        st.write("No aspects found.")
        output_lines.append("No aspects found.")

    # --- Export ---
    export_text = "\n".join(output_lines)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button("⬇ Save as .txt", export_text, file_name="parsed_chart.txt")
    with col2:
        # Use a hidden textarea to avoid backtick/quote escaping issues in clipboard
        import json
        escaped = json.dumps(export_text)  # safely escape all special chars
        copy_code = f"""
        <textarea id="clipdata" style="position:absolute;left:-9999px;">{export_text}</textarea>
        <button onclick="var t=document.getElementById('clipdata');navigator.clipboard.writeText(t.value).then(function(){{this.textContent='✅ Copied!'}}.bind(this))"
                style="padding:8px 16px; border:none; border-radius:6px;
                       background:#4CAF50; color:white; cursor:pointer; font-size:14px;">
            📋 Copy to Clipboard
        </button>
        """
        components.html(copy_code, height=44)