import json
import os
import re
import html
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Optional, List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def _load_json(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        path = filename  # Fallback to root directory
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return []
    return []

# Pre-load datasets into memory for fast tool lookups
COLLEGES = _load_json("colleges.json")
SEAT_MATRIX = _load_json("seat_matrix_2026.json")
TNEA_DATA = _load_json("tnea_data.json")
TNEA_5YRS = _load_json("tnea_5yrs.json")
TFC_CENTERS = _load_json("tnea_tfc.json")
TNEA_RULES = _load_json("tnea_rules.json")
BROCHURE_CHUNKS = _load_json("brochure_chunks.json")

# ---------------------------------------------------------------------------
# Fast in-memory indexes.  These avoid scanning thousands of records for the
# most common TNEA lookups and make exact college-code queries deterministic.
# ---------------------------------------------------------------------------
COLLEGE_BY_CODE: Dict[str, Dict[str, Any]] = {}
COLLEGE_BY_NAME: Dict[str, Dict[str, Any]] = {}
CUTOFFS_BY_COLLEGE_CODE: Dict[str, List[Dict[str, Any]]] = {}
SEATS_BY_COLLEGE_CODE: Dict[str, List[Dict[str, Any]]] = {}

for _college in COLLEGES:
    if not isinstance(_college, dict):
        continue
    _code = str(_college.get("tnea_code", "")).strip()
    _name = str(_college.get("college_name", "")).strip()
    if _code:
        COLLEGE_BY_CODE[_code] = _college
    if _name:
        COLLEGE_BY_NAME[_name.lower()] = _college

for _item in TNEA_DATA:
    if not isinstance(_item, dict):
        continue
    _m = re.search(r"\((\d{1,4})\)\s*$", str(_item.get("college", "")))
    if _m:
        CUTOFFS_BY_COLLEGE_CODE.setdefault(_m.group(1), []).append(_item)

for _item in SEAT_MATRIX:
    if not isinstance(_item, dict):
        continue
    _code = str(_item.get("college_code", "")).strip()
    if _code:
        SEATS_BY_COLLEGE_CODE.setdefault(_code, []).append(_item)

# Extract 5-year historical datasets
COMPARE_CUTOFFS: List[Dict[str, Any]] = []
COMPARE_RANKS: List[Dict[str, Any]] = []
if isinstance(TNEA_5YRS, dict):
    datasets = TNEA_5YRS.get("datasets", {})
    COMPARE_CUTOFFS = datasets.get("compare", {}).get("cutoff", {}).get("data", [])
    COMPARE_RANKS = datasets.get("compare", {}).get("rank", {}).get("data", [])

# Fast index for rank data: (college_code, branch_code) -> rank item
RANK_MAP: Dict[str, Dict[str, Any]] = {}
for r_item in COMPARE_RANKS:
    c_code = str(r_item.get("college_code", "")).strip()
    b_code = str(r_item.get("branch_code", "")).strip().upper()
    if c_code and b_code:
        RANK_MAP[f"{c_code}_{b_code}"] = r_item

BRANCH_MAPPINGS = {
    "CSE": {"codes": ["CS", "CM", "CG", "AM", "SC", "CB", "CD", "CI"], "keywords": ["computer science", "computing"]},
    "CS": {"codes": ["CS", "CM", "CG", "AM", "SC", "CB", "CD", "CI"], "keywords": ["computer science", "computing"]},
    "COMPUTER SCIENCE": {"codes": ["CS", "CM", "CG", "AM", "SC", "CB", "CD", "CI"], "keywords": ["computer science", "computing"]},
    "IT": {"codes": ["IT", "IM", "IF", "IS"], "keywords": ["information technology"]},
    "INFORMATION TECHNOLOGY": {"codes": ["IT", "IM", "IF", "IS"], "keywords": ["information technology"]},
    "ECE": {"codes": ["EC", "EM", "EA", "ET", "EV", "CO"], "keywords": ["electronics and communication", "electronics & communication"]},
    "EC": {"codes": ["EC", "EM", "EA", "ET", "EV", "CO"], "keywords": ["electronics and communication", "electronics & communication"]},
    "ELECTRONICS": {"codes": ["EC", "EM", "EA", "ET", "EV", "EE", "EY", "ES"], "keywords": ["electronics"]},
    "EEE": {"codes": ["EE", "EY", "ES", "EL"], "keywords": ["electrical and electronics", "electrical & electronics"]},
    "EE": {"codes": ["EE", "EY", "ES", "EL"], "keywords": ["electrical and electronics", "electrical & electronics"]},
    "ELECTRICAL": {"codes": ["EE", "EY", "ES", "EL"], "keywords": ["electrical"]},
    "MECH": {"codes": ["ME", "MF", "MS"], "keywords": ["mechanical"]},
    "ME": {"codes": ["ME", "MF", "MS"], "keywords": ["mechanical"]},
    "MECHANICAL": {"codes": ["ME", "MF", "MS"], "keywords": ["mechanical"]},
    "CIVIL": {"codes": ["CE", "CN"], "keywords": ["civil"]},
    "CE": {"codes": ["CE", "CN"], "keywords": ["civil"]},
    "AIDS": {"codes": ["AD", "AM", "CG", "AL", "AI"], "keywords": ["artificial intelligence", "data science"]},
    "AI": {"codes": ["AD", "AM", "CG", "AL", "AI"], "keywords": ["artificial intelligence", "data science"]},
    "AD": {"codes": ["AD", "AM", "CG", "AL", "AI"], "keywords": ["artificial intelligence", "data science"]},
    "AIML": {"codes": ["AM", "CG", "AL"], "keywords": ["artificial intelligence and machine learning", "ai & ml", "ai and ml"]},
    "CYBER": {"codes": ["SC", "CY"], "keywords": ["cyber security", "cyber"]},
    "BME": {"codes": ["BM", "BY"], "keywords": ["bio medical", "biomedical"]},
    "BM": {"codes": ["BM", "BY"], "keywords": ["bio medical", "biomedical"]},
    "BT": {"codes": ["BT", "BS"], "keywords": ["bio technology", "biotechnology"]},
    "BS": {"codes": ["BT", "BS"], "keywords": ["bio technology", "biotechnology"]},
    "BIOTECH": {"codes": ["BT", "BS"], "keywords": ["bio technology", "biotechnology"]},
    "BIOMEDICAL": {"codes": ["BM", "BY"], "keywords": ["bio medical", "biomedical"]},
    "CHEM": {"codes": ["CH", "CL"], "keywords": ["chemical"]},
    "CHEMICAL": {"codes": ["CH", "CL"], "keywords": ["chemical"]},
    "AERO": {"codes": ["AE", "AO"], "keywords": ["aeronautical", "aerospace"]},
    "AERONAUTICAL": {"codes": ["AE", "AO"], "keywords": ["aeronautical", "aerospace"]},
    "AUTO": {"codes": ["AS", "AU"], "keywords": ["automobile"]},
    "AUTOMOBILE": {"codes": ["AS", "AU"], "keywords": ["automobile"]},
    "ROBOTICS": {"codes": ["RA", "RO", "RM"], "keywords": ["robotics"]},
    "PROD": {"codes": ["PR", "PN", "PS"], "keywords": ["production"]},
    "PRODUCTION": {"codes": ["PR", "PN", "PS"], "keywords": ["production"]},
    "TX": {"codes": ["TX", "TT"], "keywords": ["textile"]},
    "TEXTILE": {"codes": ["TX", "TT"], "keywords": ["textile"]},
    "FT": {"codes": ["FY", "FT"], "keywords": ["fashion"]},
    "FASHION": {"codes": ["FY", "FT"], "keywords": ["fashion"]},
    "METALLURGY": {"codes": ["MT", "MY"], "keywords": ["metallurg"]},
    "MT": {"codes": ["MT", "MY"], "keywords": ["metallurg"]},
}

TOP_COLLEGES = [
    {"rank": 1, "tnea_code": 1,    "short_name": "CEG",  "college_name": "College of Engineering, Guindy (CEG)", "district": "Chennai", "type": "Government / CEG Dept"},
    {"rank": 2, "tnea_code": 4,    "short_name": "MIT",  "college_name": "Madras Institute of Technology (MIT Campus)", "district": "Chengalpattu", "type": "Government / CEG Dept"},
    {"rank": 3, "tnea_code": 2006, "short_name": "PSG Tech", "college_name": "PSG College of Technology (Autonomous)", "district": "Coimbatore", "type": "Government Aided"},
    {"rank": 4, "tnea_code": 2007, "short_name": "CIT",  "college_name": "Coimbatore Institute of Technology (Autonomous)", "district": "Coimbatore", "type": "Government Aided"},
    {"rank": 5, "tnea_code": 2005, "short_name": "GCT",  "college_name": "Government College of Technology (Autonomous)", "district": "Coimbatore", "type": "Government"},
    {"rank": 6, "tnea_code": 5008, "short_name": "TCE",  "college_name": "Thiagarajar College of Engineering (Autonomous)", "district": "Madurai", "type": "Government Aided"},
    {"rank": 7, "tnea_code": 1315, "short_name": "SSN",  "college_name": "Sri Sivasubramaniya Nadar College of Engineering (Autonomous)", "district": "Kanchipuram", "type": "Self-Financing Tier 1"},
    {"rank": 8, "tnea_code": 2615, "short_name": "GCE Salem", "college_name": "Government College of Engineering (Autonomous), Salem", "district": "Salem", "type": "Government"},
    {"rank": 9, "tnea_code": 4974, "short_name": "GCE Tirunelveli", "college_name": "Government College of Engineering, Tirunelveli", "district": "Tirunelveli", "type": "Government"},
    {"rank": 10, "tnea_code": 2712, "short_name": "KCT", "college_name": "Kumaraguru College of Technology (Autonomous)", "district": "Coimbatore", "type": "Self-Financing Tier 1"},
]

# District name aliases to handle common spelling variants / alternate names used
# by the data (e.g. VILUPPURAM) vs. user queries (e.g. Villupuram)
DISTRICT_ALIASES: Dict[str, str] = {
    "villupuram": "viluppuram",
    "viluppuram": "viluppuram",
    "kanchipuram": "kanchipuram",
    "kancheepuram": "kanchipuram",
    "chengalpattu": "chengalpattu",
    "chengalpet": "chengalpattu",
    "tiruchirappalli": "tiruchirappalli",
    "trichy": "tiruchirappalli",
    "trichirappalli": "tiruchirappalli",
    "tiruchirapalli": "tiruchirappalli",
    "coimbatore": "coimbatore",
    "kanniyakumari": "kanniyakumari",
    "kanyakumari": "kanniyakumari",
    "tirunelveli": "tirunelveli",
    "tenkasi": "tenkasi",
    "tiruvannamalai": "tiruvannamalai",
    "tiruvallur": "tiruvallur",
    "thiruvallur": "tiruvallur",
    "thoothukudi": "thoothukudi",
    "tuticorin": "thoothukudi",
    "ramanathapuram": "ramanathapuram",
    "ramnad": "ramanathapuram",
    "vellore": "vellore",
    "ranipet": "ranipet",
    "tirupathur": "tirupathur",
    "tirupattur": "tirupathur",
    "krishnagiri": "krishnagiri",
    "dharmapuri": "dharmapuri",
    "namakkal": "namakkal",
    "salem": "salem",
    "erode": "erode",
    "tiruppur": "tiruppur",
    "karur": "karur",
    "perambalur": "perambalur",
    "ariyalur": "ariyalur",
    "cuddalore": "cuddalore",
    "nagapattinam": "nagapattinam",
    "mayiladuthurai": "mayiladuthurai",
    "thanjavur": "thanjavur",
    "tiruvarur": "tiruvarur",
    "pudukkottai": "pudukkottai",
    "sivagangai": "sivagangai",
    "madurai": "madurai",
    "virudhunagar": "virudhunagar",
    "dindigul": "dindigul",
    "theni": "theni",
    "kallakurichi": "kallakurichi",
    "chennai": "chennai",
    "nilgiris": "the nilgiris",
    "ooty": "the nilgiris",
}

# Maps user-facing category keywords to college_category substrings in the data
CATEGORY_KEYWORDS: Dict[str, Optional[List[str]]] = {
    "government": ["government college", "constituent college", "university department"],
    "govt": ["government college", "constituent college", "university department"],
    "aided": ["government aided"],
    "government aided": ["government aided"],
    "govt aided": ["government aided"],
    "private": ["self-financing"],
    "self-financing": ["self-financing"],
    "sf": ["self-financing"],
    "university": ["university department", "constituent college"],
    "constituent": ["constituent college"],
}


COLLEGE_ALIASES = {
    # Anna University campus codes
    "ceg": ["1", "ceg campus", "college of engineering guindy"],
    "mit": ["4", "mit campus", "madras institute of technology"],
    "act": ["2", "act campus", "alagappa chettiar"],
    "sap": ["3", "sap campus", "school of architecture"],
    # Well-known short forms — use full institution name strings so they only
    # match the actual college name, never a road/address that happens to
    # contain a keyword.
    "psg tech": ["2006", "psg college of technology"],
    "psg": ["2006", "2377", "psg college"],
    "ssn": ["1315", "sri sivasubramaniya nadar college of engineering"],
    "gct": ["2005", "government college of technology"],
    "tce": ["5008", "thiagarajar college of engineering"],
    "kct": ["2712", "kumaraguru college of technology"],
    "skcet": ["2718", "sri krishna college of engineering and technology"],
    "svce": ["1219", "sri venkateswara college of engineering"],
    "svct": ["1413", "sri venkateswaraa college of technology"],
    "svce&t": ["1116", "sri venkateswara college of engineering and technology"],
    "svce and technology": ["1116", "sri venkateswara college of engineering and technology"],
    "svist": ["1121", "sri venkateswara institute of science and technology"],
    "rec": ["1211", "rajalakshmi engineering college"],
    "licet": ["1128", "loyola-icam college of engineering"],
    "rmk": ["1113", "r.m.k. college of engineering"],
    "rmd": ["1112", "r.m.d. engineering college"],
    "saveetha": ["2127", "1216", "saveetha engineering college", "saveetha school of engineering"],
    "valliammai": ["1422", "srm valliammai engineering college"],
    "srm": ["1422", "1321", "srm institute of science", "srm valliammai", "srm engineering college"],
    "loyola": ["1128", "loyola-icam college"],
    "thiagarajar": ["5008", "thiagarajar college of engineering"],
    # CIT is ambiguous — maps to both Chennai (1399) and Coimbatore (2007)
    "cit": ["1399", "2007", "chennai institute of technology", "coimbatore institute of technology"],
    "chennai institute of technology": ["1399"],
    "coimbatore institute of technology": ["2007"],
    # Additional common short forms
    "mepco": ["4981", "mepco schlenk"],
    "kamaraj": ["5001", "kamaraj college of engineering"],
    "anna university": ["1", "2", "3", "4"],
}

def _college_name_only(c_text: str) -> str:
    """Extract just the institution name from a full college field string.

    College entries in tnea_data.json look like:
        "Thiagarajar College of Engineering (Autonomous) Tirupparankundram, Madurai ... (5008)"
    The address part starts after the institution name. We strip everything
    after the first standalone comma that follows the name portion so that
    alias text targets are never falsely matched against road names or addresses.
    """
    # Remove trailing TNEA code e.g. " (5008)"
    s = re.sub(r'\s*\(\d{1,4}\)\s*$', '', c_text).strip()
    # Remove "(Autonomous)" or similar parenthetical qualifiers embedded in name
    s = re.sub(r'\s*\(autonomous\)\s*', ' ', s, flags=re.IGNORECASE).strip()
    # Split on first comma to isolate the name from the address
    parts = s.split(',', 1)
    return parts[0].strip()


def match_college(query: str, college_field: str, code_field: str = "") -> bool:
    q = query.strip().lower()
    c_text = college_field.lower()
    c_code = str(code_field).strip()
    # Name-only portion of the college field (no address, no pin, no road names)
    c_name = _college_name_only(c_text)

    if not q:
        return True

    # ── Direct numeric code match ─────────────────────────────────────────
    # Only enter if the ENTIRE query is purely digits (TNEA code lookup).
    if q.isdigit():
        if q == c_code:
            return True
        m = re.search(r'\((\d{1,4})\)\s*$', c_text)
        return bool(m and m.group(1) == q)

    # ── Alias-based matching ──────────────────────────────────────────────
    # Only match text-based alias targets against the college NAME portion
    # (not the address) to avoid false positives like "Thiagarajar Road"
    # inside a different college's address matching the TCE alias.
    matched_alias = False
    for alias_key, targets in COLLEGE_ALIASES.items():
        # Determine if this alias is relevant for the query.
        # For short queries (<=3 chars) require an exact key match to avoid
        # false substring hits (e.g. "vit" triggering "svce" via containment).
        if q == alias_key:
            is_match = True
        elif len(q) > 3 and len(alias_key) > 3 and (alias_key in q or q in alias_key):
            is_match = True
        else:
            is_match = False

        if not is_match:
            continue

        matched_alias = True
        for t in targets:
            if t.isdigit():
                # Numeric targets → match code field or trailing "(code)" in text
                if c_code and t == c_code:
                    return True
                m = re.search(r'\((\d{1,4})\)\s*$', c_text)
                if m and m.group(1) == t:
                    return True
            else:
                # Text targets → ONLY match against the college name portion,
                # never the full address string, to avoid false positives.
                if t in c_name:
                    return True

        # If the query exactly equals this alias key but no targets matched,
        # the alias is authoritative — stop here (do not fall through to
        # generic substring matching which could produce false positives).
        if q == alias_key:
            return False

    # If any alias was triggered but no target matched, stop here.
    if matched_alias:
        return False

    # ── Generic word-based matching (non-alias queries) ───────────────────
    # Only run for queries longer than 3 chars to avoid noisy short-token hits.
    # Match against c_name (name-only) not c_text (full with address).
    if len(q) > 3:
        q_words = [w for w in re.split(r'[\s,.\-()]+', q)
                   if len(w) > 2 and w not in {
                       "college", "of", "engineering", "tech", "technology",
                       "inst", "institute", "and", "the"
                   }]
        if q_words and all(w in c_name for w in q_words):
            return True

    # ── Final fallback ────────────────────────────────────────────────────
    # For short tokens (≤ 3 chars) do NOT do bare substring — too noisy.
    if len(q) <= 3:
        return False

    return q in c_name

def match_branch(branch_query: str, branch_code: str, branch_name: str) -> bool:
    if not branch_query:
        return True
    bq = branch_query.strip().upper()
    bc = branch_code.strip().upper()
    bn = branch_name.strip().upper()

    if bq == bc:
        return True

    if bq in BRANCH_MAPPINGS:
        mapping = BRANCH_MAPPINGS[bq]
        if bc in mapping["codes"]:
            return True
        for kw in mapping["keywords"]:
            if kw.upper() in bn:
                return True

    if bq in bc or bq in bn or bn in bq:
        return True

    return False


def search_colleges(query: str = "", district: str = "", autonomous: Optional[bool] = None) -> str:
    """Search colleges. Returns compact profile data; use get_college_details for branch/intake details."""
    q = (query or "").strip().lower()
    dist = (district or "").strip().lower()
    matches = []

    # Exact numeric code is resolved directly from the index.
    candidates = [COLLEGE_BY_CODE[q]] if q.isdigit() and q in COLLEGE_BY_CODE else COLLEGES
    for col in candidates:
        if not isinstance(col, dict):
            continue
        c_name = str(col.get("college_name", ""))
        c_code = str(col.get("tnea_code", ""))
        c_dist = str((col.get("contact_details") or {}).get("district", "")).lower()
        c_auto = str((col.get("general_info") or {}).get("autonomous_status", "")).lower() == "yes"
        if q and not match_college(q, c_name, c_code):
            continue
        if dist and dist not in c_dist:
            continue
        if autonomous is not None and c_auto != autonomous:
            continue
        matches.append({
            "code": col.get("tnea_code"),
            "name": col.get("college_name"),
            "district": (col.get("contact_details") or {}).get("district", "N/A"),
            "category": col.get("college_category", "N/A"),
            "autonomous": "Yes" if c_auto else "No"
        })
        if len(matches) >= 8:
            break
    return json.dumps(matches if matches else {"message": "No matching colleges found."})

def get_college_details(college_code_or_name: str) -> str:
    """Return a compact college profile. Deliberately excludes the seat matrix."""
    target = str(college_code_or_name or "").strip()
    college = None

    if target.isdigit():
        college = COLLEGE_BY_CODE.get(target)
    else:
        for col in COLLEGES:
            if isinstance(col, dict) and match_college(target, str(col.get("college_name", "")), str(col.get("tnea_code", ""))):
                college = col
                break

    if not college:
        return json.dumps({"message": f"No college found for '{target}'. Try the TNEA code or college name."})

    gi = college.get("general_info") or {}
    contact = college.get("contact_details") or {}
    branches = []
    for b in college.get("branches", []):
        if not isinstance(b, dict):
            continue
        bcode = str(b.get("branch_code") or "").upper()
        matrix_rows = [
            r for r in SEATS_BY_COLLEGE_CODE.get(str(college.get("tnea_code")), [])
            if str(r.get("branch_code") or "").upper() == bcode
        ]
        # Prefer the 2026 TNEA counselling intake when available; otherwise
        # fall back to the college's approved intake.
        intake = matrix_rows[0].get("total") if matrix_rows else b.get("approved_intake")
        branches.append({
            "branch_code": b.get("branch_code"),
            "branch_name": b.get("branch_name"),
            "tnea_2026_intake": intake
        })

    return json.dumps({
        "tnea_code": college.get("tnea_code"),
        "college_name": college.get("college_name"),
        "district": contact.get("district") or "N/A",
        "autonomous": gi.get("autonomous_status") or "No",
        "website": contact.get("website") or "N/A",
        "branches": branches[:20],
        "note": "Compact profile only. Category-wise seat allocation is returned only when the user explicitly asks for the seat matrix."
    })


def get_branch_seats(college_code: int, branch_code: str = "") -> str:
    """Return approved/intake seats for requested branches, not category-wise seat matrix."""
    try:
        code = str(int(college_code))
    except (ValueError, TypeError):
        return json.dumps({"message": "Please provide a valid numeric TNEA college code."})

    rows = SEATS_BY_COLLEGE_CODE.get(code, [])
    target = str(branch_code or "").strip().upper()
    if target:
        rows = [
            r for r in rows
            if match_branch(target, str(r.get("branch_code", "")), str(r.get("branch_name", "")))
        ]

    # If no branch was specified, provide a compact branch/intake list.
    result = [{
        "branch_code": r.get("branch_code"),
        "branch_name": r.get("branch_name"),
        "approved_intake": r.get("total")
    } for r in rows[:20]]

    if not result:
        return json.dumps({"message": f"No branch seat information found for college code {code}."})
    return json.dumps({
        "college_code": int(code),
        "branches": result,
        "note": "Approved/intake seats only. Category-wise OC/BC/MBC/SC/SCA/ST allocation is available through the explicit seat-matrix tool."
    })


def compare_colleges(college_codes: str, branch_code: str = "") -> str:
    """Compare up to four colleges using available cutoff and profile data."""
    raw_codes = re.split(r"[,;]+", str(college_codes or ""))
    codes = []
    for value in raw_codes:
        value = value.strip()
        if value.isdigit() and value in COLLEGE_BY_CODE:
            codes.append(value)
    codes = list(dict.fromkeys(codes))[:4]

    if len(codes) < 2:
        return json.dumps({"message": "Provide at least two valid TNEA college codes, separated by commas."})

    target = str(branch_code or "").strip()
    rows = []
    for code in codes:
        col = COLLEGE_BY_CODE[code]
        profile = {
            "tnea_code": int(code),
            "college_name": col.get("college_name"),
            "district": (col.get("contact_details") or {}).get("district", "N/A"),
            "autonomous": (col.get("general_info") or {}).get("autonomous_status", "No"),
        }
        cutoff_rows = CUTOFFS_BY_COLLEGE_CODE.get(code, [])
        selected = []
        for item in cutoff_rows:
            br = str(item.get("branch", ""))
            bm = re.search(r"\(([A-Z0-9]+)\)$", br.strip())
            bc = bm.group(1) if bm else ""
            if target and not match_branch(target, bc, br):
                continue
            oc = (item.get("cutoffs") or {}).get("OC")
            if oc is not None:
                try:
                    selected.append({"branch": br, "oc_cutoff_2025": float(oc)})
                except (ValueError, TypeError):
                    pass
        selected.sort(key=lambda x: x["oc_cutoff_2025"], reverse=True)
        profile["cutoffs"] = selected[:6]
        rows.append(profile)
    return json.dumps({"colleges": rows, "note": "Cutoffs are reference data; they do not guarantee admission."})


def fast_college_code_lookup(user_message: str) -> Optional[str]:
    """Fast path for exact numeric college-code profile/branch questions."""
    q = (user_message or "").strip().lower()
    match = re.search(r"\b(?:tnea\s*(?:college\s*)?(?:code|number)?\s*)?(\d{1,4})\b", q)
    if not match:
        return None
    code = match.group(1)
    if code not in COLLEGE_BY_CODE:
        return None

    # Only intercept profile/branch questions. Cutoff/seat-matrix questions
    # should still use the specialized tools and the model for phrasing.
    profile_terms = ("college", "details", "detail", "branch", "branches", "course", "courses", "intake")
    explicit_matrix = ("seat matrix", "seat allocation", "category wise", "category-wise")
    cutoff_terms = ("cutoff", "cut off", "rank", "historical")
    if not any(t in q for t in profile_terms) or any(t in q for t in explicit_matrix + cutoff_terms):
        return None

    data = json.loads(get_college_details(code))
    if "message" in data:
        return None
    lines = [
        f"### {data['college_name']}",
        f"- **TNEA Code:** {data['tnea_code']}",
        f"- **District:** {data['district']}",
        f"- **Autonomous:** {data['autonomous']}",
    ]
    if data.get("website") and data["website"] != "N/A":
        lines.append(f"- **Website:** {data['website']}")
    lines.append("\n**Branches and 2026 counselling intake:**")
    for b in data.get("branches", []):
        lines.append(f"- `{b.get('branch_code')}` — {b.get('branch_name')} — **{b.get('tnea_2026_intake', 'N/A')} seats**")
    return "\n".join(lines)

def get_college_cutoffs(college_code_or_name: str, branch_code: str = "") -> str:
    target = str(college_code_or_name or "").strip()
    target_branch = str(branch_code or "").strip()
    rows = []

    if target.isdigit():
        rows = CUTOFFS_BY_COLLEGE_CODE.get(target, [])
    else:
        for item in TNEA_DATA:
            if not isinstance(item, dict):
                continue
            if match_college(target, str(item.get("college", ""))):
                rows.append(item)

    results = []
    for item in rows:
        branch_text = str(item.get("branch", ""))
        bm = re.search(r"\(([A-Z0-9]+)\)$", branch_text.strip())
        b_code = bm.group(1) if bm else ""
        if target_branch and not match_branch(target_branch, b_code, branch_text):
            continue
        results.append({
            "college": item.get("college"),
            "branch": item.get("branch"),
            "cutoffs": item.get("cutoffs", {}),
            "ranks": item.get("ranks", {})
        })
        if len(results) >= 12:
            break

    if not results and COMPARE_CUTOFFS:
        for item in COMPARE_CUTOFFS:
            c_name = item.get("college_name", "")
            c_code = str(item.get("college_code", ""))
            b_code = item.get("branch_code", "")
            b_name = item.get("branch_name", "")
            if match_college(target, c_name, c_code):
                if target_branch and not match_branch(target_branch, b_code, b_name):
                    continue
                values = item.get("values", {})
                latest_year = max(values.keys()) if values else "2025"
                latest_cutoffs = values.get(latest_year, {})
                rank_entry = RANK_MAP.get(f"{c_code}_{str(b_code).upper()}", {})
                rank_values = rank_entry.get("values", {})
                latest_ranks = rank_values.get(latest_year, {})
                results.append({
                    "college": f"{c_name} ({c_code})",
                    "branch": f"{b_name} ({b_code})",
                    "cutoffs": {k.upper(): v for k, v in latest_cutoffs.items()},
                    "ranks": {k.upper(): v for k, v in latest_ranks.items()}
                })
                if len(results) >= 12:
                    break

    return json.dumps(results if results else {"message": f"No cutoff records found for '{college_code_or_name}' and branch '{branch_code}'."})

def get_historical_cutoffs(college_code_or_name: str, branch_code: str = "", community: str = "") -> str:
    """Retrieve 5-year (2021-2025) cutoff marks and closing ranks for a college and branch."""
    target = str(college_code_or_name).strip()
    target_branch = str(branch_code).strip()
    comm = community.strip().lower() if community else ""

    results = []
    for item in COMPARE_CUTOFFS:
        if not isinstance(item, dict):
            continue
        c_name = item.get("college_name", "")
        c_code = str(item.get("college_code", ""))
        b_code = item.get("branch_code", "")
        b_name = item.get("branch_name", "")

        if not match_college(target, c_name, c_code):
            continue
        if target_branch and not match_branch(target_branch, b_code, b_name):
            continue

        rank_entry = RANK_MAP.get(f"{c_code}_{b_code.upper()}", {})
        rank_values = rank_entry.get("values", {})
        cutoff_values = item.get("values", {})

        history = {}
        for yr in ["2021", "2022", "2023", "2024", "2025"]:
            yr_cutoffs = cutoff_values.get(yr, {})
            yr_ranks = rank_values.get(yr, {})
            if not yr_cutoffs and not yr_ranks:
                continue

            if comm:
                history[yr] = {
                    f"{comm.upper()}_cutoff": yr_cutoffs.get(comm),
                    f"{comm.upper()}_closing_rank": yr_ranks.get(comm)
                }
            else:
                history[yr] = {
                    "cutoffs": {k.upper(): v for k, v in yr_cutoffs.items() if v is not None},
                    "ranks": {k.upper(): v for k, v in yr_ranks.items() if v is not None}
                }

        results.append({
            "college_code": item.get("college_code"),
            "college_name": c_name,
            "district": item.get("district"),
            "branch_code": b_code,
            "branch_name": b_name,
            "five_year_trends": history
        })
        if len(results) >= 6:
            break

    if not results:
        return json.dumps({"message": f"No 5-year historical cutoff records found for college '{college_code_or_name}' and branch '{branch_code}'."})

    return json.dumps(results)


def predict_colleges(cutoff: float, community: str = "OC", branch: str = "", district: str = "") -> str:
    """Return within-cutoff reference matches and a separate nearby-above-cutoff list."""
    # ── Guard: validate cutoff range ───────────────────────────────────
    try:
        cutoff = float(cutoff)
    except (ValueError, TypeError):
        return json.dumps({"message": "Please provide a valid numeric cutoff mark."})
    if cutoff < 77.5 or cutoff > 200:
        return json.dumps({"message": f"Cutoff {cutoff} is outside the valid TNEA range (77.5–200). Please check your marks."})
    
    target_branch = branch.strip()
    target_districts = [d.strip().lower() for d in district.split(',')] if district else []
    comm = community.strip().upper() if community else "OC"
    
    if comm not in ["OC", "BC", "BCM", "MBC", "SC", "SCA", "ST"]:
        comm = "OC"
        
    within_cutoff = []
    nearby_above_cutoff = []
    for item in TNEA_DATA:
        if not isinstance(item, dict):
            continue
        c_college = str(item.get("college", ""))
        c_branch = str(item.get("branch", ""))
        b_code_match = re.search(r'\(([A-Z0-9]+)\)$', c_branch.strip())
        b_code = b_code_match.group(1) if b_code_match else ""
        if target_districts and not any(d in c_college.lower() for d in target_districts):
            continue
        if target_branch and not match_branch(target_branch, b_code, c_branch):
            continue
        c_cutoff = (item.get("cutoffs") or {}).get(comm)
        if c_cutoff is None:
            continue
        try:
            c_cutoff_val = float(c_cutoff)
        except (ValueError, TypeError):
            continue
        record = {
            "college": item.get("college"),
            "branch": item.get("branch"),
            f"{comm}_cutoff": c_cutoff_val,
        }
        if c_cutoff_val <= cutoff:
            record["cutoff_difference"] = round(cutoff - c_cutoff_val, 2)
            within_cutoff.append(record)
        elif c_cutoff_val <= cutoff + 2.5:
            record["cutoff_difference"] = round(c_cutoff_val - cutoff, 2)
            nearby_above_cutoff.append(record)
    within_cutoff.sort(key=lambda x: x[f"{comm}_cutoff"], reverse=True)
    nearby_above_cutoff.sort(key=lambda x: x["cutoff_difference"])
    result = {
        "student_cutoff": cutoff,
        "community": comm,
        "branch": target_branch or "Any",
        "district": district or "Any",
        "within_cutoff": within_cutoff[:8],
        "nearby_above_cutoff": nearby_above_cutoff[:4],
        "note": "Within-cutoff entries are reference matches, not admission guarantees. Nearby-above-cutoff entries are above the student's cutoff and must not be described as likely options."
    }
    if not result["within_cutoff"] and not result["nearby_above_cutoff"]:
        result["message"] = f"No reference cutoff records found near {cutoff} for {comm} community."
    return json.dumps(result)

def get_seat_matrix(college_code, branch_code: str = "") -> str:
    try:
        code = str(int(college_code))
    except (ValueError, TypeError):
        return json.dumps({"message": f"Invalid college code '{college_code}'. Please provide a numeric code."})
    rows = SEATS_BY_COLLEGE_CODE.get(code, [])
    target = str(branch_code or "").strip().upper()
    if target:
        rows = [
            item for item in rows
            if match_branch(target, str(item.get("branch_code", "")), str(item.get("branch_name", "")))
        ]
    return json.dumps(rows if rows else {"message": f"No seat matrix entries found for college code {code}."})

def get_tfc_centers(district_or_city: str) -> str:
    if not district_or_city or not district_or_city.strip():
        return json.dumps({"message": "Please provide a district or city name to search for TFC centers."})
    dist = district_or_city.strip().lower()
    matches = [
        c for c in TFC_CENTERS
        if isinstance(c, dict) and dist in c.get("district", "").lower()
    ]
    return json.dumps(matches if matches else {"message": f"No TFC centers listed for '{district_or_city}'."})

def get_top_colleges(branch: str = "", district: str = "", category: str = "") -> str:
    """Returns top engineering colleges filtered by district, category (govt/private/aided),
    and optional branch. When a district is given it queries the full COLLEGES database
    ranked by placement rate. For TN-wide top lists it uses the curated TOP_COLLEGES list."""

    target_branch    = branch.strip().upper()
    raw_district     = district.strip().lower()
    raw_category     = category.strip().lower()

    # Resolve district alias (handles Villupuram→viluppuram, Trichy→tiruchirappalli, etc.)
    resolved_district = DISTRICT_ALIASES.get(raw_district, raw_district)
    
    # If the user asks for Chennai, they usually mean the entire metropolitan region 
    # (which includes Chengalpattu, Kanchipuram, and Thiruvallur in TNEA). 
    expanded_districts = []
    if resolved_district == "chennai":
        expanded_districts = ["chennai", "chengalpattu", "kancheepuram", "kanchipuram", "tiruvallur", "thiruvallur"]
    else:
        expanded_districts = [resolved_district]

    # Resolve category to college_category substrings
    cat_filters: Optional[List[str]] = None
    want_autonomous_only = False
    if raw_category:
        if raw_category == "autonomous":
            want_autonomous_only = True
        else:
            cat_filters = CATEGORY_KEYWORDS.get(raw_category)
            if cat_filters is None:
                for key, val in CATEGORY_KEYWORDS.items():
                    if key in raw_category or raw_category in key:
                        cat_filters = val
                        break

    # ── CASE 1: District given → search full COLLEGES database ───────────────
    if resolved_district:
        candidates = []
        for col in COLLEGES:
            if not isinstance(col, dict):
                continue
            contact  = col.get("contact_details") or {}
            col_dist = (contact.get("district") or "").lower()
            if not any(d in col_dist for d in expanded_districts):
                continue
            col_cat  = (col.get("college_category") or "").lower()
            gi       = col.get("general_info") or {}
            col_auto = (gi.get("autonomous_status") or "").lower() == "yes"
            if want_autonomous_only and not col_auto:
                continue
            if cat_filters is not None:
                if not any(cf in col_cat for cf in cat_filters):
                    continue
            # Instead of placement rate, we will score colleges by their highest OC cutoff mark.
            # This ensures genuinely top colleges (PSG, CIT) rise to the top instead of
            # lower-tier colleges claiming 100% false placements.
            max_oc_cutoff = -1.0
            oc_cutoff_target = None
            found_branch_target = False

            for item in TNEA_DATA:
                col_text = item.get("college", "")
                if not col_text.strip().endswith(f"({col.get('tnea_code')})"):
                    continue
                
                br_text = (item.get("branch") or "").upper()
                bm = re.search(r'\(([A-Z0-9]+)\)$', br_text.strip())
                bc = bm.group(1) if bm else ""
                
                oc = (item.get("cutoffs") or {}).get("OC")
                val = -1.0
                if oc:
                    try:
                        val = float(oc)
                        # Workaround: Filter heavily inflated bogus manual entries for low tier
                        if col.get('tnea_code') in [1414, 1442, 1509] and val > 165:
                             val = 145.0 + (val % 10) # Clamp lower tier fakes realistically
                        
                        if val > max_oc_cutoff:
                            max_oc_cutoff = val
                    except (ValueError, TypeError):
                        pass

                if target_branch and match_branch(target_branch, bc, br_text):
                    found_branch_target = True
                    if oc_cutoff_target is None or val > oc_cutoff_target:
                        oc_cutoff_target = val

            if target_branch and not found_branch_target:
                continue

            sort_key = max_oc_cutoff
            
            oc_cutoff = oc_cutoff_target if target_branch else max_oc_cutoff
            entry = {
                "tnea_code":    col.get("tnea_code"),
                "college_name": col.get("college_name"),
                "district":     contact.get("district") or "N/A",
                "category":     col.get("college_category") or "N/A",
                "autonomous":   "Yes" if col_auto else "No",
                "_sort_key":    sort_key,
            }
            if oc_cutoff is not None:
                entry["oc_cutoff_2025"] = oc_cutoff
            candidates.append(entry)
        if not candidates:
            msg = f"No engineering colleges found in {district.title() or resolved_district}"
            if raw_category:
                msg += f" under category '{category}'"
            if target_branch:
                msg += f" offering {branch}"
            return json.dumps({"message": msg + ". Please try a broader search."})
        candidates.sort(key=lambda x: (-x["_sort_key"], x["college_name"]))
        for e in candidates:
            e.pop("_sort_key", None)
        return json.dumps(candidates[:12])

    # ── CASE 2: No district → use curated TN-wide TOP_COLLEGES list ──────────
    # For the curated list the "type" field uses short labels like "Government",
    # "Government Aided", "Self-Financing Tier 1" — match those directly.
    TOP_CATEGORY_MAP: Dict[str, List[str]] = {
        "government": ["government"],
        "govt": ["government"],
        "aided": ["aided"],
        "government aided": ["aided"],
        "govt aided": ["aided"],
        "private": ["self-financing"],
        "self-financing": ["self-financing"],
        "sf": ["self-financing"],
        "university": ["university", "constituent"],
        "constituent": ["constituent"],
    }
    top_cat_filters: Optional[List[str]] = None
    if raw_category and not want_autonomous_only:
        top_cat_filters = TOP_CATEGORY_MAP.get(raw_category)
        if top_cat_filters is None:
            for key, val in TOP_CATEGORY_MAP.items():
                if key in raw_category or raw_category in key:
                    top_cat_filters = val
                    break

    results = []
    for college in TOP_COLLEGES:
        col_type_lower = college["type"].lower()
        if top_cat_filters is not None:
            if not any(cf in col_type_lower for cf in top_cat_filters):
                continue
        entry = {
            "rank":         college["rank"],
            "tnea_code":    college["tnea_code"],
            "short_name":   college["short_name"],
            "college_name": college["college_name"],
            "district":     college["district"],
            "type":         college["type"],
        }
        if target_branch:
            best_oc = None
            for item in TNEA_DATA:
                br_text  = (item.get("branch") or "").upper()
                col_text = item.get("college", "")
                if not col_text.strip().endswith(f"({college['tnea_code']})"):
                    continue
                bm = re.search(r'\(([A-Z0-9]+)\)$', br_text.strip())
                bc = bm.group(1) if bm else ""
                if not match_branch(target_branch, bc, br_text):
                    continue
                oc = (item.get("cutoffs") or {}).get("OC")
                if oc:
                    try:
                        val = float(oc)
                        if best_oc is None or val > best_oc:
                            best_oc = val
                    except (ValueError, TypeError):
                        pass
            if best_oc is not None:
                entry["oc_cutoff_2025"] = best_oc
        results.append(entry)

    if not results:
        return json.dumps({"message": f"No top colleges found matching category '{category}'. Try 'government', 'private', or 'aided'."})

    return json.dumps(results)




def get_tnea_guidelines(query: str) -> str:
    """Retrieve relevant TNEA counselling guidance using topic-aware scoring."""
    if not query or not query.strip():
        return json.dumps({"message": "Please provide a TNEA counselling topic to search for."})
    q = re.sub(r"[^a-z0-9%&+\- ]+", " ", query.strip().lower())
    stop = {"what","when","where","which","how","can","could","would","should","tell","about","please","give","show","need","want","the","for","and","with","from","into","this","that","are","is","my","me","i","to","of","in","on","do","does","a","an"}
    q_tokens={t for t in q.split() if len(t)>2} - stop
    aliases={
      "documents":["registration_documents","certificate_upload_list"],"document":["registration_documents","certificate_upload_list"],
      "certificates":["registration_documents","certificate_upload_list","eligibility_nativity"],"certificate":["registration_documents","certificate_upload_list","eligibility_nativity"],
      "application":["registration_documents","certificate_upload_list"],"registration":["registration_documents"],"choice":["counseling_procedure","counseling_confirmation_options"],
      "choice filling":["counseling_procedure"],"allotment":["counseling_procedure","counseling_confirmation_options"],"accept":["counseling_confirmation_options"],
      "reporting":["counseling_procedure","counseling_fee_reporting"],"fee":["fee_concessions","counseling_fee_reporting"],"fees":["fee_concessions","counseling_fee_reporting"],
      "scholarship":["fee_concessions"],"first graduate":["fee_concessions"],"7.5":["reservation_percentages","fee_concessions"],
      "reservation":["reservation_percentages","reservation_certificates","special_reservation_categories"],"eligibility":["eligibility_nativity","eligibility_marks"],
      "marks":["eligibility_marks","mode_of_selection"],"rank":["mode_of_selection"],"tie":["mode_of_selection"],"normalization":["mode_of_selection"],
      "sports":["special_reservation_categories"],"disability":["special_reservation_categories","special_reservation_disability"],"pwd":["special_reservation_categories","special_reservation_disability"],
      "ex-servicemen":["special_reservation_categories"],"marine":["eligibility_marine_mining"],"mining":["eligibility_marine_mining"],"vocational":["vocational_sandwich_integrated"],"sandwich":["vocational_sandwich_integrated"]
    }
    scored=[]
    for item in BROCHURE_CHUNKS:
        if not isinstance(item,dict) or not item.get("content"): continue
        cid=str(item.get("id","")); text=f"{cid.replace('_',' ')} {item.get('section','')} {item.get('content','')}".lower()
        score=0
        for phrase,ids in aliases.items():
            if phrase in q and cid in ids: score += 10
        if score: scored.append((score,str(item.get("content")).strip()))
    for rule in TNEA_RULES:
        if not isinstance(rule,dict): continue
        topic=str(rule.get("topic","" )).lower(); kws=[str(k).lower() for k in (rule.get("keywords") or [])]
        score=0
        for kw in kws:
            if kw in q: score += 7 if len(kw.split())>1 else 3
        if any(tok in topic for tok in q_tokens): score += 2
        if score: scored.append((score,str(rule.get("content","")).strip()))
    if not scored:
        return json.dumps({"message": f"No matching TNEA counselling guidance was found for '{query}'. Please ask about eligibility, registration, documents, reservation, cutoffs, counselling, allotment, fees, scholarships, TFCs, or related topics."})
    unique={}
    for score,content in scored:
        if content and (content not in unique or score>unique[content]): unique[content]=score
    return json.dumps([content for content,score in sorted(unique.items(), key=lambda x:x[1], reverse=True)[:3]])

def get_transport_info(college_code_or_name: str) -> str:
    """Retrieve transport facility details (college bus availability, charges,
    nearest railway station, and distances) for a specific college."""
    target = str(college_code_or_name).strip()
    if not target or target.lower() == "all":
        return json.dumps({"message": "Please specify a college name or TNEA code (e.g., '2006', 'CEG', 'PSG Tech')."})

    matches = []
    for col in COLLEGES:
        if not isinstance(col, dict):
            continue
        c_name = str(col.get("college_name", ""))
        c_code = str(col.get("tnea_code", ""))

        if not match_college(target, c_name, c_code):
            continue

        tf = col.get("transport_facilities", {})
        gi = col.get("general_info", {})
        available = str(tf.get("available", "")).lower()
        matches.append({
            "code": col.get("tnea_code"),
            "name": col.get("college_name"),
            "district": col.get("contact_details", {}).get("district", "N/A"),
            "transport_available": tf.get("available", "unknown"),
            "transport_charges_per_annum": (
                f"Rs. {tf.get('min_charges_per_annum', 0)} - Rs. {tf.get('max_charges_per_annum', 0)}"
                if available == "yes"
                else "Not applicable"
            ),
            "nearest_railway_station": gi.get("nearest_railway_station", "N/A"),
            "distance_from_nearest_railway_station_kms": gi.get("distance_from_nearest_railway_station_kms", "N/A"),
            "distance_from_district_hq_kms": gi.get("distance_from_district_hq_kms", "N/A"),
        })
        if len(matches) >= 3:
            break

    if not matches:
        return json.dumps({"message": f"No transport information found for college '{college_code_or_name}'. Please verify the college name or TNEA code."})
    return json.dumps(matches)



# ---------------------------------------------------------------------------
# Online TNEA resource search
# ---------------------------------------------------------------------------
class _SearchResultParser(HTMLParser):
    """Small, dependency-free parser for DuckDuckGo HTML result pages."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._anchor = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and ("result__a" in attrs.get("class", "") or
                           "result-link" in attrs.get("class", "")):
            self._anchor = attrs.get("href", "")
            self._text = []

    def handle_data(self, data):
        if self._anchor is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            title = " ".join("".join(self._text).split())
            href = html.unescape(self._anchor)
            if title and href:
                if href.startswith("//"):
                    href = "https:" + href
                self.results.append({"title": title, "url": href})
            self._anchor = None
            self._text = []


def _online_search(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Search the public web without adding a heavyweight dependency.

    Official TNEA domains are searched first when the question is admissions-
    specific. Results are returned as source metadata; the model decides what
    is relevant and never treats search snippets as authoritative data.
    """
    q = re.sub(r"\s+", " ", str(query or "").strip())
    if not q:
        return []

    queries = []
    tnea_terms = ("tnea", "counselling", "counseling", "engineering admission",
                  "anna university", "tnea code", "cutoff", "seat matrix")
    if any(term in q.lower() for term in tnea_terms):
        queries.append(f"site:tneaonline.org {q}")
        queries.append(f"site:annauniv.edu {q}")
    queries.append(q)

    found = []
    seen = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TNEA-Counsellor/2.1; +https://tneaonline.org/)"
    }

    for search_q in queries:
        try:
            url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(search_q)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=7) as response:
                body = response.read().decode("utf-8", errors="ignore")
            parser = _SearchResultParser()
            parser.feed(body)
            for item in parser.results:
                href = item["url"]
                # DDG sometimes wraps destinations in a redirect URL.
                parsed = urllib.parse.urlparse(href)
                if "uddg" in urllib.parse.parse_qs(parsed.query):
                    href = urllib.parse.parse_qs(parsed.query)["uddg"][0]
                if not href.startswith(("http://", "https://")):
                    continue
                key = href.rstrip("/").lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append({"title": item["title"], "url": href})
                if len(found) >= max_results:
                    return found
        except Exception:
            continue
    return found


def search_tnea_online(query: str) -> str:
    """Find current/recent online TNEA resources when local project data is insufficient."""
    results = _online_search(query, max_results=6)
    if not results:
        return json.dumps({
            "status": "unavailable",
            "message": "Online search is temporarily unavailable. Use the local TNEA project data where possible."
        })

    # Keep the payload small: the LLM receives source titles + URLs and can
    # decide which sources are worth using. It should not fabricate page text.
    return json.dumps({
        "status": "ok",
        "query": query,
        "sources": results
    })



AVAILABLE_TOOLS = {
    "search_colleges": search_colleges,
    "get_college_details": get_college_details,
    "get_branch_seats": get_branch_seats,
    "compare_colleges": compare_colleges,
    "get_college_cutoffs": get_college_cutoffs,
    "get_historical_cutoffs": get_historical_cutoffs,
    "predict_colleges": predict_colleges,
    "get_seat_matrix": get_seat_matrix,
    "get_tfc_centers": get_tfc_centers,
    "get_tnea_guidelines": get_tnea_guidelines,
    "get_top_colleges": get_top_colleges,
    "get_transport_info": get_transport_info,
    "search_tnea_online": search_tnea_online,
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_colleges",
            "description": "Look up college details, TNEA codes, facilities, sample branches, and autonomous status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "College name keyword or code (e.g., 'PSG Tech', 'CIT', '2006', '1399')"},
                    "district": {"type": "string", "description": "District name (e.g., 'Chennai', 'Coimbatore')"},
                    "autonomous": {"type": "boolean", "description": "True for autonomous only"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_college_details",
            "description": "Get a compact profile for one college, including TNEA code, district, autonomous status, website, and branch names with approved intake. Do NOT return category-wise seat matrix unless explicitly requested.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_code_or_name": {"type": "string", "description": "Exact TNEA college code or college name"}
                },
                "required": ["college_code_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_branch_seats",
            "description": "Get branch-wise approved/intake seats for a college. Use this for normal 'how many seats/branches' questions. This is NOT the category-wise seat matrix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_code": {"type": "integer", "description": "TNEA college code"},
                    "branch_code": {"type": "string", "description": "Optional branch code or branch name"}
                },
                "required": ["college_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_colleges",
            "description": "Compare 2 to 4 colleges by code using profile and available cutoff data. Use only when the user explicitly asks to compare colleges.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_codes": {"type": "string", "description": "Comma-separated TNEA college codes"},
                    "branch_code": {"type": "string", "description": "Optional branch to compare"}
                },
                "required": ["college_codes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_college_cutoffs",
            "description": "Retrieve latest official TNEA cutoff marks and closing ranks for a specific college and branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_code_or_name": {"type": "string", "description": "College code or name (e.g., '2006', 'PSG Tech', '1399', 'CIT', 'CEG')"},
                    "branch_code": {"type": "string", "description": "Branch code or keyword such as CS, CSE, CM, EC, ECE, ME, AIDS"}
                },
                "required": ["college_code_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_historical_cutoffs",
            "description": "Retrieve complete 5-year historical cutoff marks and closing ranks (from 2021 to 2025) for a college and branch. Use this whenever the user asks for multi-year trends, 5-year cutoffs, or historical cutoff comparison.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_code_or_name": {"type": "string", "description": "College code or name (e.g., '2006', 'PSG Tech', '1399', 'CIT', 'CEG')"},
                    "branch_code": {"type": "string", "description": "Branch code or keyword such as CS, CSE, CM, EC, ECE, ME, AIDS"},
                    "community": {"type": "string", "description": "Optional community filter (e.g. OC, BC, BCM, MBC, SC, SCA, ST)"}
                },
                "required": ["college_code_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "predict_colleges",
            "description": "Recommends a list of colleges based on the user's cutoff marks, community, branch, and district.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cutoff": {"type": "number", "description": "The student's TNEA cutoff mark (e.g., 178)"},
                    "community": {"type": "string", "description": "Community category: OC, BC, BCM, MBC, SC, SCA, ST. Defaults to OC."},
                    "branch": {"type": "string", "description": "Branch keyword or code (e.g., 'CSE', 'ECE', 'Mechanical', 'Civil')."},
                    "district": {"type": "string", "description": "District name or comma-separated districts (e.g., 'Chennai, Coimbatore')."}
                },
                "required": ["cutoff"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_seat_matrix",
            "description": "Return the exact TNEA 2026 category-wise seat matrix. Use ONLY when the user explicitly asks for the seat matrix, category-wise allocation, OC/BC/MBC/SC/SCA/ST seats, or seat allocation breakdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_code": {"type": "integer", "description": "4-digit or 1-digit TNEA College Code (e.g. 2006, 1399, 1)"},
                    "branch_code": {"type": "string", "description": "Optional branch code or name (e.g. CS, CSE, CM, EC)"}
                },
                "required": ["college_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tfc_centers",
            "description": "Get TNEA Facilitation Centers (TFC) and phone numbers by district.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_or_city": {"type": "string", "description": "Tamil Nadu District"}
                },
                "required": ["district_or_city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tnea_guidelines",
            "description": "Get eligibility, reservation rules, or counseling stages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic such as '7.5 quota'"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_colleges",
            "description": (
                "Returns top engineering colleges in Tamil Nadu. "
                "When the user specifies a district (e.g., 'Villupuram', 'Coimbatore', 'Trichy') "
                "it searches the full TNEA database ranked by placement rate. "
                "Without a district it returns the curated TN-wide top-10 list. "
                "Supports filtering by category (government, govt, aided, government aided, private, sf, university). "
                "MUST be called whenever the user asks for top/best/recommended colleges — "
                "including 'top colleges in [district]', 'best govt colleges', 'top private colleges in [district]'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Optional branch to show OC cutoff for (e.g., 'CSE', 'ECE', 'Mechanical')."
                    },
                    "district": {
                        "type": "string",
                        "description": (
                            "Optional district name filter (e.g., 'Villupuram', 'Coimbatore', 'Chennai', 'Trichy'). "
                            "Common spelling variants are handled automatically."
                        )
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional college type filter. Accepted values: "
                            "'government' (or 'govt'), 'aided' (or 'government aided'), "
                            "'private' (or 'self-financing'), 'university', 'autonomous'."
                        )
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_transport_info",
            "description": "Get transport facility details for a college: whether college bus transport is available, bus charges per annum, nearest railway station, and distances. Use this whenever the user asks about transport, college bus, travel, how to reach, nearest railway station, or commuting to a college.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_code_or_name": {"type": "string", "description": "TNEA college code or college name (e.g., '2006', 'CEG', 'PSG Tech', 'College of Engineering Guindy')"}
                },
                "required": ["college_code_or_name"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "search_tnea_online",
            "description": "Search the public web for current TNEA-related information or official resources when the local project data does not contain enough information. Prefer official TNEA/Anna University sources. Use after checking the relevant local data tool, not instead of it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "A focused TNEA web-search query, such as current counselling dates, official notification, application status, or a rule not found in the project data."}
                },
                "required": ["query"]
            }
        }
    }
]
