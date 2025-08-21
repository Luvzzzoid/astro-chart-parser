import streamlit as st
import re
from PyPDF2 import PdfReader
from collections import defaultdict

# -------- SETTINGS --------
ZODIAC = {
    'a': ('Aries', 0), 'b': ('Taurus', 30), 'c': ('Gemini', 60), 'd': ('Cancer', 90),
    'e': ('Leo', 120), 'f': ('Virgo', 150), 'g': ('Libra', 180), 'h': ('Scorpio', 210),
    'i': ('Sagittarius', 240), 'j': ('Capricorn', 270), 'k': ('Aquarius', 300), 'l': ('Pisces', 330)
}

ASPECTS = [
    ("conjunct", 0),
    ("sextile", 60),
    ("square", 90),
    ("trine", 120),
    ("opposite", 180),
]

NAME_FIX = {
    "P.Fort.": "Part of Fortune",
    "MC": "Midheaven",
    "Asc.": "Ascendant",
}

DEG_TOKEN = r'(?:\d{1,2}°\s*\d{1,2}\'\s*\d{1,2}"|\d{1,2}°\s*\d{1,2}\'|\d{1,2}°)'

def ordinal(n: int) -> str:
    if n < 1: n = 1
    if 10 <= n % 100 <= 20: suf = "th"
    else: suf = {1:"st",2:"nd",3:"rd"}.get(n % 10, "th")
    return f"{n}{suf}"

def parse_deg_string(s: str) -> float | None:
    s = s.replace(" ", "")
    m = re.match(r"(\d+)°(\d+)'(\d+)\"", s) or \
        re.match(r"(\d+)°(\d+)'", s) or \
        re.match(r"(\d+)°", s)
    if not m: return None
    d = int(m.group(1))
    mnt = int(m.group(2)) if m.lastindex >= 2 and m.group(2) else 0
    sec = int(m.group(3)) if m.lastindex >= 3 and m.group(3) else 0
    return d + mnt/60 + sec/3600

def extract_title(pdf_text: str) -> str:
    m = re.search(r'([0-9A-Za-z *]+Chart).*?\(Data Sheet\)', pdf_text)
    return m.group(1).strip() if m else "Chart"

def parse_planet_rows(lines):
    placements, objects = [], []
    pat = re.compile(rf'^(?P<code>[A-Z])\s{{2,}}(?P<label>[A-Za-z\.\* ]+?)\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})\s+(?:#\s*)?(?P<house>\d+)\b')
    for line in lines:
        m = pat.match(line)
        if not m: continue
        label = NAME_FIX.get(m.group('label').strip(), m.group('label').strip())
        sign_code, deg_text, house = m.group('sign'), m.group('deg'), int(m.group('house'))
        sign_name, sign_base = ZODIAC[sign_code]
        lon30 = parse_deg_string(deg_text) or 0.0
        abs_lon = sign_base + lon30
        placements.append((label, sign_name, house, re.sub(r'\s+', ' ', deg_text.strip())))
        objects.append((label, abs_lon))
    return placements, objects

def parse_asteroids(lines):
    asts, objs = [], []
    pat = re.compile(rf'^#\w+\s+(?P<name>.*?)\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})\s+(?P<house>\d+)\b')
    for line in lines:
        m = pat.match(line)
        if not m: continue
        raw = m.group('name').strip()
        name = re.sub(r'^[^A-Za-z]+', '', re.sub(r'^\d+\s*', '', raw))
        sign_code, deg_text, house = m.group('sign'), m.group('deg'), int(m.group('house'))
        sign_name, sign_base = ZODIAC[sign_code]
        lon30 = parse_deg_string(deg_text) or 0.0
        abs_lon = sign_base + lon30
        asts.append((name, sign_name, house, re.sub(r'\s+', ' ', deg_text.strip())))
        objs.append((name, abs_lon))
    return asts, objs

def parse_houses_section(lines):
    asc, mc = None, None
    asc_pat = re.compile(rf'^Asc\.\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})')
    mc_pat  = re.compile(rf'^MC\s+(?P<sign>[a-l])\s+(?P<deg>{DEG_TOKEN})')
    for line in lines:
        ma = asc_pat.match(line)
        if ma:
            sign_code, deg_text = ma.group('sign'), ma.group('deg')
            sign_name, sign_base = ZODIAC[sign_code]
            lon30 = parse_deg_string(deg_text) or 0.0
            asc = ("Ascendant", sign_name, 1, re.sub(r'\s+', ' ', deg_text.strip()), ("Ascendant", sign_base + lon30))
        mm = mc_pat.match(line)
        if mm:
            sign_code, deg_text = mm.group('sign'), mm.group('deg')
            sign_name, sign_base = ZODIAC[sign_code]
            lon30 = parse_deg_string(deg_text) or 0.0
            mc = ("Midheaven", sign_name, 10, re.sub(r'\s+', ' ', deg_text.strip()), ("Midheaven", sign_base + lon30))
    placements, objects = [], []
    if asc: placements.append(asc[:4]); objects.append(asc[4])
    if mc:  placements.append(mc[:4]);  objects.append(mc[4])
    return placements, objects

def compute_aspects(objects, orb_limit=3.0):
    hits = []
    for i in range(len(objects)):
        n1, lon1 = objects[i]
        for j in range(i+1, len(objects)):
            n2, lon2 = objects[j]
            diff = abs((lon1 - lon2) % 360.0)
            if diff > 180: diff = 360 - diff
            for asp_name, angle in ASPECTS:
                orb = abs(diff - angle)
                if orb <= orb_limit + 1e-9:
                    hits.append((n1, asp_name, n2))
    return hits

# -------- STREAMLIT APP --------
st.title("Astro.com Chart Parser")

pdf_file = st.file_uploader("Upload your Astro.com PDF", type=["pdf"])

# toggles
show_degrees = st.checkbox("Show degrees in placements", value=True)
orb_limit = st.slider("Aspect orb limit (degrees)", 1, 10, 3)

if pdf_file is not None:
    reader = PdfReader(pdf_file)
    full_text = "\n".join(page.extract_text() for page in reader.pages)
    lines = full_text.splitlines()

    planet_lines = [ln for ln in lines if re.match(r'^[A-Z]\s{2,}', ln)]

    house_lines, in_houses = [], False
    for ln in lines:
        if 'Houses (Plac.)' in ln:
            in_houses = True
            continue
        if in_houses:
            if ln.strip().startswith("Aspects"): break
            house_lines.append(ln)

    placements_p, objects_p = parse_planet_rows(planet_lines)
    asteroids_p, objects_a = parse_asteroids(lines)
    ascmc_p, asc_mc_objs = parse_houses_section(house_lines)

    def merge_lists(a, b):
        names = {x[0] for x in a}
        for item in b:
            if item[0] not in names:
                a.append(item)
        return a

    placements_main = []
    placements_main = merge_lists(placements_main, placements_p)
    placements_main = merge_lists(placements_main, ascmc_p)

    placements_ast = []
    placements_ast = merge_lists(placements_ast, asteroids_p)

    names_seen, objects_all = set(), []
    for name, lon in objects_p + asc_mc_objs + objects_a:
        if name not in names_seen:
            names_seen.add(name)
            objects_all.append((name, lon))

    aspects = compute_aspects(objects_all, orb_limit)
    title = extract_title(full_text)

    # --- Display ---
    st.subheader(f"{title}")

    st.markdown("### Placements")
    for name, sign, house, deg in placements_main:
        if show_degrees:
            st.write(f"* {name}: {sign}, {ordinal(house)} house, {deg}")
        else:
            st.write(f"* {name}: {sign}, {ordinal(house)} house")

    if placements_ast:
        st.markdown("### Asteroids")
        for name, sign, house, deg in placements_ast:
            if show_degrees:
                st.write(f"* {name}: {sign}, {ordinal(house)} house, {deg}")
            else:
                st.write(f"* {name}: {sign}, {ordinal(house)} house")

    st.markdown(f"### Aspects (orb ≤ {orb_limit}°)")
    grouped = defaultdict(list)
    for a, asp, b in aspects:
        grouped[(a, asp)].append(b)

    if grouped:
        for (a, asp), bs in grouped.items():
            st.write(f"* {a} {asp} {', '.join(bs)}")
    else:
        st.write("No aspects found.")
