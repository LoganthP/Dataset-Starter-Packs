"""Deterministic vocabulary: synonyms, regions and the plain-language query parser.

The parser turns "traffic incident data with latitude, longitude and timestamps, at least one year, CSV"
into editable criteria. It never guesses beyond these rules; anything it doesn't recognise stays
in the free-text topic. Add synonyms here when a benchmark query misses (see catalog/benchmark.json).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------- topic synonyms (expand free text)
TOPIC_GROUPS: list[set[str]] = [
    {"incident", "incidents", "crash", "crashes", "collision", "collisions", "accident", "accidents"},
    {"traffic", "road", "roads", "vehicle", "vehicles", "transport", "mobility"},
    {"weather", "climate", "meteorology", "temperature", "precipitation", "rainfall", "rain", "monsoon"},
    {"bike", "bikes", "bicycle", "cycling", "bikeshare"},
    {"ecommerce", "e-commerce", "orders", "retail", "shopping", "delivery", "deliveries", "logistics"},
    {"exoplanet", "exoplanets", "planet", "planets", "astronomy", "space"},
    {"energy", "electricity", "power", "consumption"},
    {"pollution", "air", "aq", "emissions"},
    {"bean", "beans", "crop", "agriculture"},
    {"social", "twitter", "tweet", "tweets", "reddit", "subreddit", "subreddits", "facebook", "instagram", "posts", "weibo", "mastodon"},
    {"sentiment", "emotion", "opinion", "polarity"},
]
STOPWORDS = set("""
a an the and or of for to in on with without at by from into over under as is are be need needs want looking find
data dataset datasets project projects some any that this it its i we my our me which should have has
suitable good best use using about across per each every one two three four five six seven eight nine ten
""".split())

# ---------------------------------------------------------------- field concepts
FIELD_PATTERNS: dict[str, list[str]] = {
    "latlon": [r"\blat(itude)?s?\s*(/|and|&|,)?\s*(lon|lng|long|longitude)s?\b", r"\bcoordinates?\b", r"\bgps\b",
               r"\bgeo-?coded\b", r"\blatitude\b", r"\blongitude\b", r"\blat/?lon\b"],
    "timestamp": [r"\btime-?stamps?\b", r"\bdate\s*(and|&|/)\s*time\b", r"\bdatetimes?\b", r"\bdate-?times?\b"],
    "target_label": [r"\btarget (label|column|variable)\b", r"\blabell?ed\b", r"\bground truth\b", r"\bclass labels?\b"],
    "join_key": [r"\bjoin keys?\b", r"\bforeign keys?\b", r"\bjoinable\b"],
    "geo_boundary": [r"\b(geographic )?boundar(y|ies)\b", r"\bpolygons?\b", r"\bshapefiles?\b"],
}
CONCEPT_LABELS = {
    "latlon": "Latitude and longitude",
    "timestamp": "Timestamp",
    "target_label": "Target label",
    "join_key": "Join key",
    "geo_boundary": "Geographic boundary",
}

FORMATS = {"csv": "csv", "json": "json", "parquet": "parquet", "netcdf": "netcdf", "xlsx": "xlsx", "excel": "xlsx", "geojson": "geojson"}
GRANULARITY = {"daily": "daily", "hourly": "hourly", "monthly": "monthly", "minute": "minute", "per-minute": "minute"}
PURPOSES = {
    "forecasting": [r"\bforecast(ing|s)?\b", r"\bpredict(ing)? (future|next|tomorrow)", r"\btime[- ]series prediction\b"],
    "classification": [r"\bclassif(y|ier|ication)\b"],
    "regression": [r"\bregression\b"],
    "geospatial": [r"\bgeospatial\b", r"\bmapping\b", r"\bspatial analysis\b", r"\bhotspots?\b"],
    "sql-analytics": [r"\bsql\b", r"\bjoins?\b(?! key)"],
    "exploratory": [r"\bexplor(e|atory|ation)\b", r"\beda\b"],
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "a": 1, "an": 1, "single": 1, "several": 3, "twenty": 20}

# ---------------------------------------------------------------- regions (small, explicit hierarchy)
REGIONS: dict[str, dict] = {
    "global": {"label": "Global", "parents": []},
    "india": {"label": "India", "parents": ["asia"], "aliases": ["indian"]},
    "bengaluru": {"label": "Bengaluru", "parents": ["karnataka", "india"], "aliases": ["bangalore", "blr"]},
    "mysuru": {"label": "Mysuru", "parents": ["karnataka", "india"], "aliases": ["mysore"]},
    "chennai": {"label": "Chennai", "parents": ["india"], "aliases": ["madras"]},
    "karnataka": {"label": "Karnataka", "parents": ["india"]},
    "united-states": {"label": "United States", "parents": [], "aliases": ["usa", "us", "u.s.", "america", "american"]},
    "new-york-city": {"label": "New York City", "parents": ["united-states"], "aliases": ["nyc", "new york"]},
    "chicago": {"label": "Chicago", "parents": ["united-states"]},
    "washington-dc": {"label": "Washington D.C.", "parents": ["united-states"], "aliases": ["washington dc", "dc"]},
    "minnesota": {"label": "Minnesota", "parents": ["united-states"]},
    "united-kingdom": {"label": "United Kingdom", "parents": [], "aliases": ["uk", "britain", "great britain", "england"]},
    "brazil": {"label": "Brazil", "parents": [], "aliases": ["brazilian"]},
    "italy": {"label": "Italy", "parents": [], "aliases": ["italian"]},
    "france": {"label": "France", "parents": [], "aliases": ["paris", "french"]},
}


def region_ancestors(region: str) -> set[str]:
    seen, stack = set(), [region]
    while stack:
        r = stack.pop()
        if r in seen:
            continue
        seen.add(r)
        stack.extend(REGIONS.get(r, {}).get("parents", []))
    return seen


def region_label(region: str) -> str:
    return REGIONS.get(region, {}).get("label", region.replace("-", " ").title())


@dataclass
class Criteria:
    """Everything a search can require. `soft` lists criteria the user downgraded to preferences."""
    topic: str = ""
    fields: list[str] = field(default_factory=list)
    min_years: float | None = None
    formats: list[str] = field(default_factory=list)
    region: str | None = None
    granularity: str | None = None
    commercial: bool = False
    soft: list[str] = field(default_factory=list)
    # plain filters the parser can also infer
    purposes: list[str] = field(default_factory=list)
    difficulty: list[str] = field(default_factory=list)
    offline: bool = False
    notebook: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def is_required(self, key: str) -> bool:
        return key not in self.soft


def _years(text: str) -> tuple[float | None, str]:
    m = re.search(r"\b(?:at least|minimum of|min(?:imum)?|over|>=?)\s+(\d+|[a-z]+)\s+years?\b", text) or \
        re.search(r"\b(\d+|[a-z]+)\+?\s+years?\s+(?:of|or more|history|coverage)\b", text) or \
        re.search(r"\b(?:over|for|covering|across|last|past)\s+(\d+|[a-z]+)\s+years?\b", text)
    if m:
        token = m.group(1)
        n = int(token) if token.isdigit() else NUMBER_WORDS.get(token)
        if n:
            return float(n), m.group(0)
    m = re.search(r"\b(?:over |for |covering )?(?:a|one|full) decade\b|\bdecade of\b", text)
    if m:
        return 10.0, m.group(0)
    m = re.search(r"\b(?:at least |over |for )?(?:a|one|full) year\b|\byear[- ]long\b", text)
    if m:
        return 1.0, m.group(0)
    return None, ""


def parse_query(q: str) -> Criteria:
    text = " " + (q or "").lower().strip() + " "
    c = Criteria()
    consumed: list[str] = []

    for concept, pats in FIELD_PATTERNS.items():
        for p in pats:
            for m in re.finditer(p, text):
                if concept not in c.fields:
                    c.fields.append(concept)
                consumed.append(m.group(0))
    # "with dates/times" as a weaker timestamp signal
    if "timestamp" not in c.fields and re.search(r"\bwith (dates|times|date|time)\b", text):
        c.fields.append("timestamp")

    years, span = _years(text)
    if years:
        c.min_years = years
        consumed.append(span)

    for word, fmt in FORMATS.items():
        if re.search(rf"\b{word}\b", text) and fmt not in c.formats:
            c.formats.append(fmt)
            consumed.append(word)
    for word, g in GRANULARITY.items():
        if re.search(rf"\b{word}\b", text):
            c.granularity = g
            consumed.append(word)
            break
    if re.search(r"\bcommercial(ly)?\b", text) and not re.search(r"\bnon-?commercial\b", text):
        c.commercial = True
        consumed += ["commercial", "commercially", "reuse", "use", "re-use"]

    for purpose, pats in PURPOSES.items():
        if any(re.search(p, text) for p in pats):
            c.purposes.append(purpose)
            consumed.append(purpose)
    for level in ("beginner", "intermediate", "advanced"):
        if re.search(rf"\b{level}s?\b", text):
            c.difficulty.append(level)
            consumed.append(level)
    if re.search(r"\boffline\b", text):
        c.offline = True
        consumed += ["offline", "sample"]
    if re.search(r"\bnotebooks?\b", text):
        c.notebook = True
        consumed.append("notebook")

    matched_regions = []
    for key, info in REGIONS.items():
        if key == "global":
            continue
        names = [info["label"].lower(), key.replace("-", " ")] + info.get("aliases", [])
        for name in names:
            if len(name) <= 3 and name not in ("usa", "nyc", "uk"):
                continue  # "us", "dc" are too ambiguous as plain words
            if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
                matched_regions.append(key)
                consumed.append(name)
    if matched_regions:
        # the most specific place mentioned wins (Bengaluru over India)
        c.region = max(matched_regions, key=lambda r: len(region_ancestors(r)))

    # Topic: what's left, minus stopwords and consumed criteria words.
    leftover = text
    for chunk in sorted(set(consumed), key=len, reverse=True):
        if chunk.strip():
            leftover = leftover.replace(chunk, " ")
    words = [w for w in re.findall(r"[a-z][a-z0-9\-]+", leftover)
             if w not in STOPWORDS and w not in {"latitude", "longitude", "timestamps", "timestamp", "year", "years", "sample",
                                                  "reuse", "re-use", "format", "file", "files", "available", "cover", "covers", "coverage"}]
    c.topic = " ".join(dict.fromkeys(words))
    return c


def expand_topic(topic: str) -> list[str]:
    """Terms for full-text search: each topic word plus its synonym group."""
    terms: list[str] = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-]+", (topic or "").lower()):
        if w in STOPWORDS:
            continue
        group = next((g for g in TOPIC_GROUPS if w in g), {w})
        for t in sorted(group):
            if t not in terms:
                terms.append(t)
    return terms
