import os
import time
import math
import json
import csv
import sys
import signal
import pathlib
import re
from typing import Dict, List, Tuple, Optional, Set
import requests
from dotenv import load_dotenv
import shutil
import unicodedata
from urllib.parse import urlparse
try:
    import matplotlib.pyplot as plt
    import matplotlib as mpl
    import seaborn as sns
except Exception:
    plt = None
    mpl = None
    sns = None

# Load API key from .env
load_dotenv()
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# ---------------------- Configuration ---------------------- #
import argparse

def get_args():
    parser = argparse.ArgumentParser(description="Collect restaurant data from Google Maps")
    parser.add_argument("--lat-min", type=float, default=51.2868, help="Min Latitude")
    parser.add_argument("--lat-max", type=float, default=51.6919, help="Max Latitude")
    parser.add_argument("--lon-min", type=float, default=-0.5103, help="Min Longitude")
    parser.add_argument("--lon-max", type=float, default=0.3340, help="Max Longitude")
    parser.add_argument("--grid-step", type=float, default=1.5, help="Grid step in km")
    parser.add_argument("--radius", type=int, default=1500, help="Search radius in meters")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Output directory")
    parser.add_argument("--city-name", type=str, default="london", help="City name for file naming")
    return parser.parse_known_args()[0]

args = get_args()

# Bbox
LAT_MIN = args.lat_min
LAT_MAX = args.lat_max
LON_MIN = args.lon_min
LON_MAX = args.lon_max

# Grid & query params
GRID_STEP_KM = args.grid_step
RADIUS_M     = args.radius
PLACE_TYPE   = "restaurant"

# Paths
OUTDIR       = pathlib.Path(args.output_dir)
CITY_NAME    = args.city_name
CSV_PATH     = OUTDIR / f"{CITY_NAME}_restaurants.csv"
DETAILS_CSV  = OUTDIR / f"{CITY_NAME}_restaurant_details.csv"
REVIEWS_CSV  = OUTDIR / f"{CITY_NAME}_restaurant_reviews.csv"
LOG_PATH     = OUTDIR / "progress_log.json"
GRID_PATH    = OUTDIR / "grid_points.csv"
PLOTS_DIR    = OUTDIR / "plots"

# API endpoints
NEARBY_URL   = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
DETAILS_URL  = "https://maps.googleapis.com/maps/api/place/details/json"

# Details fields
DETAILS_FIELDS = ",".join([
    "place_id",
    "name",
    "types",
    "rating",
    "price_level",
    "user_ratings_total",
    "editorial_summary",
    "opening_hours",
    "international_phone_number",
    "website",
    "review",
    "geometry",
    "vicinity",
    "business_status"
])

# Throttling
REQUEST_SLEEP_S     = 0.2
PAGE_TOKEN_WAIT_S   = 2.1
DETAILS_SLEEP_S     = 0.25
MAX_RETRIES         = 5

# ---------------------- Cuisine detection rules ---------------------- #

CUISINE_KEYWORDS = {
    "italian": ["pizza","pasta","italian","ristorante","trattoria","napoli","sicilian","roma","osteria"],
    "indian": ["indian","curry","tandoori","biryani","masala","punjab","goa","bombay","delhi","hyderabadi"],
    "chinese": ["chinese","szechuan","sichuan","dim sum","dumpling","noodle","peking","cantonese","hunan"],
    "thai": ["thai","siam","bangkok","pad thai","green curry","tom yum"],
    "japanese": ["sushi","ramen","izakaya","yakitori","tempura","kaiseki","japanese","udon"],
    "korean": ["korean","kimchi","bibimbap","bulgogi","jjigae","seoul","kbbq","k-bbq"],
    "vietnamese": ["pho","banh mi","viet","saigon","bun bo","hanoi"],
    "mexican": ["taco","burrito","cantina","taqueria","mexican","al pastor","quesadilla"],
    "spanish": ["tapas","paella","spanish","jamon","iberico","bodega","galician","andalus"],
    "french": ["bistro","brasserie","fromage","boulangerie","patisserie","french","bordeaux","paris"],
    "turkish": ["turkish","kebab","doner","mezze","ocakbasi","mangal","istanbul","adana"],
    "greek": ["greek","souvlaki","gyro","taverna","mezze","crete","athen"],
    "middle_eastern": ["lebanese","persian","iranian","iraqi","syrian","moroccan","tagine","shawarma","mezze","meze"],
    "american": ["burger","bbq","smokehouse","diner","american","fried chicken","hot dog"],
    "ethiopian": ["injera","ethiopian","habesha","kitfo","tibs"],
    "caribbean": ["jerk","caribbean","jamaican","trini","roti"],
    "european": ["brasserie","european","continental"],
    "british": ["british","fish and chips","pie and mash","sunday roast","full english","roast dinner"],
    "portuguese": ["portuguese","bacalhau","piri piri","porto","lisboa"],
    "polish": ["pierogi","polish","zurek","bigos"],
    "pakistani": ["pakistani","karahi","nihari","haleem","lahori"],
    "pub": ["pub", "public house", "tavern", "inn", "alehouse", "taproom", "brewery", "brewhouse", "cask", "draught", "arms", "castle", "lion", "crown", "plough", "anchor", "ship", "bell", "swan", "hart", "oak", "wheatsheaf", "greyhound", "coach and horses", "fox and hounds", "rose and crown", "chequers"],
}

# Extended cuisine keywords (extra categories/variants)
EXTENDED_CUISINE_KEYWORDS = {
    "seafood": ["seafood","fishmonger","oyster","lobster","crab shack","marisqueria","fish house"],
    "steakhouse": ["steakhouse","steak house","churrascaria","steak","grill house"],
    "cafe": ["cafe","coffee","espresso","cafeteria","tea room","tearoom","roastery"],
    "bakery": ["bakery","boulangerie","patisserie","pasteleria","panetteria","cake shop","bagel"],
    "sri_lankan": ["sri lankan","kottu","hoppers","sri lanka","ceylon"],
    "nepalese": ["nepalese","momo","thakali","gundruk","newari","kathmandu"],
    "bangladeshi": ["bangladeshi","bhuna","panta","fuchka","chittagong","dhaka"],
    "afghan": ["afghan","qabuli","mantu","bolani","kabul"],
    "georgian": ["georgian","khachapuri","khinkali","adjara","tbilisi"],
    "israeli": ["israeli","sabich","shakshuka","tel aviv","jerusalem"],
    "peruvian": ["peruvian","ceviche","anticucho","lomo saltado","lima"],
    "brazilian": ["brazilian","rodizio","feijoada","churrasco","rio"],
    "argentinian": ["argentinian","asado","empanada","parrilla","buenos aires"],
    "malaysian": ["malaysian","nasi lemak","laksa","satay","kuala lumpur"],
    "indonesian": ["indonesian","nasi goreng","rendang","sate","bali","jakarta"],
    "taiwanese": ["taiwanese","lu rou fan","bubble tea","boba","gua bao","taipei"],
    "cambodian": ["cambodian","khmer","amok","phnom penh"],
    "lao": ["lao","laotian","larb","laap","vientiane"],
    "middle_eastern": ["middle eastern","middle-eastern","levant","mezze","meze","falafel","hummus"],
    "fish_and_chips": ["fish & chips","fish and chips","chippy","cod and chips"],
    "vegan_vegetarian": ["vegan","vegetarian","plant based","plant-based"],
    "mediterranean": ["mediterranean"],
    "asian_fusion": ["asian fusion","pan asian","pan-asian"],
    "gastropub": ["gastropub"],
    "cocktail_bar": ["cocktail bar", "speakeasy"],
    "wine_bar": ["wine bar", "bodega", "enoteca"]
}

# Common chains/brands mapping
BRAND_KEYWORDS: Dict[str, Dict[str, str]] = {
    # brand_name: {"category": ..., "cuisine": ...}
    "starbucks": {"category": "coffee", "cuisine": "cafe"},
    "costa": {"category": "coffee", "cuisine": "cafe"},
    "caffe nero": {"category": "coffee", "cuisine": "cafe"},
    "pret a manger": {"category": "sandwich", "cuisine": "european"},
    "greggs": {"category": "bakery", "cuisine": "bakery"},
    "subway": {"category": "sandwich", "cuisine": "american"},
    "mcdonalds": {"category": "burger", "cuisine": "american"},
    "burger king": {"category": "burger", "cuisine": "american"},
    "five guys": {"category": "burger", "cuisine": "american"},
    "kfc": {"category": "chicken", "cuisine": "american"},
    "dominos": {"category": "pizza", "cuisine": "italian"},
    "pizza hut": {"category": "pizza", "cuisine": "italian"},
    "papa johns": {"category": "pizza", "cuisine": "italian"},
    "pizzaexpress": {"category": "pizza", "cuisine": "italian"},
    "zizzi": {"category": "italian", "cuisine": "italian"},
    "ask italian": {"category": "italian", "cuisine": "italian"},
    "wagamama": {"category": "asian", "cuisine": "japanese"},
    "itsu": {"category": "asian", "cuisine": "japanese"},
    "yo sushi": {"category": "asian", "cuisine": "japanese"},
    "taco bell": {"category": "mexican", "cuisine": "mexican"},
    "chipotle": {"category": "mexican", "cuisine": "mexican"},
    "nandos": {"category": "chicken", "cuisine": "british"},
    "wetherspoon": {"category": "pub", "cuisine": "pub"},
    "wetherspoons": {"category": "pub", "cuisine": "pub"},
    "jd wetherspoon": {"category": "pub", "cuisine": "pub"},
    "greene king": {"category": "pub", "cuisine": "pub"},
    "fuller's": {"category": "pub", "cuisine": "pub"},
    "fullers": {"category": "pub", "cuisine": "pub"},
    "young's": {"category": "pub", "cuisine": "pub"},
    "youngs": {"category": "pub", "cuisine": "pub"},
    "nicholson's": {"category": "pub", "cuisine": "pub"},
    "nicholsons": {"category": "pub", "cuisine": "pub"},
    "o'neill's": {"category": "pub", "cuisine": "irish"},
    "oneills": {"category": "pub", "cuisine": "irish"},
    "all bar one": {"category": "bar", "cuisine": "bar"},
    "slug and lettuce": {"category": "bar", "cuisine": "bar"},
    "slug & lettuce": {"category": "bar", "cuisine": "bar"},
    "walkabout": {"category": "bar", "cuisine": "australian"},
    "brewdog": {"category": "pub", "cuisine": "pub"},
    "stonegate": {"category": "pub", "cuisine": "pub"},
    "marston's": {"category": "pub", "cuisine": "pub"},
    "marstons": {"category": "pub", "cuisine": "pub"},
    "mitchells & butlers": {"category": "pub", "cuisine": "pub"},
    "ember inns": {"category": "pub", "cuisine": "pub"},
    "sizzling pubs": {"category": "pub", "cuisine": "pub"},
    "vintage inns": {"category": "pub", "cuisine": "pub"},
    "chef & brewer": {"category": "pub", "cuisine": "pub"},
    "chef and brewer": {"category": "pub", "cuisine": "pub"},
    "hungry horse": {"category": "pub", "cuisine": "pub"},
    "beefeater": {"category": "pub", "cuisine": "pub"},
    "brewers fayre": {"category": "pub", "cuisine": "pub"},
    "yates": {"category": "pub", "cuisine": "pub"},
    "pitcher & piano": {"category": "bar", "cuisine": "bar"},
    "revolution": {"category": "bar", "cuisine": "bar"},
    "leon": {"category": "fast_casual", "cuisine": "european"},
    "le pain quotidien": {"category": "bakery", "cuisine": "french"}
}

def km_to_deg_lat(km: float) -> float:
    return km / 111.0

def km_to_deg_lon(km: float, lat_deg: float) -> float:
    return km / (111.0 * math.cos(math.radians(lat_deg)))

def generate_grid(lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                  step_km: float) -> list[tuple[float, float]]:
    lat0 = (lat_min + lat_max) / 2.0
    dlat = km_to_deg_lat(step_km)
    dlon = km_to_deg_lon(step_km, lat0)
    lats, lons = [], []
    lat = lat_min
    while lat <= lat_max + 1e-9:
        lats.append(lat); lat += dlat
    lon = lon_min
    while lon <= lon_max + 1e-9:
        lons.append(lon); lon += dlon
    return [(la, lo) for la in lats for lo in lons]

def safe_request(url: str, params: Dict, max_retries: int = MAX_RETRIES) -> Dict:
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[warn] HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as e:
            print(f"[warn] Request error: {e}")
        sleep = min(REQUEST_SLEEP_S * (2 ** (attempt - 1)), 8.0)
        time.sleep(sleep)
    raise RuntimeError("Failed after retries.")

def places_nearby_all_pages(lat: float, lon: float, radius_m: int, place_type: str) -> list[Dict]:
    collected = []
    params = {"key": API_KEY, "location": f"{lat},{lon}", "radius": radius_m, "type": place_type}
    data = safe_request(NEARBY_URL, params)
    results = data.get("results", []); collected.extend(results)
    while True:
        next_token = data.get("next_page_token")
        if not next_token: break
        time.sleep(PAGE_TOKEN_WAIT_S)
        params2 = {"key": API_KEY, "pagetoken": next_token}
        data = safe_request(NEARBY_URL, params2)
        results = data.get("results", []); collected.extend(results)
    return collected

def normalize_base_record(r: Dict, source_lat: float, source_lon: float, grid_id: int) -> Dict:
    geo = r.get("geometry", {}).get("location", {})
    types = r.get("types", [])
    types_str = ",".join(types) if isinstance(types, list) else (str(types) if types else "")
    return {
        "place_id": r.get("place_id"),
        "name": r.get("name"),
        "types": types_str,
        "rating": r.get("rating"),
        "user_ratings_total": r.get("user_ratings_total"),
        "price_level": r.get("price_level"),
        "lat": geo.get("lat"),
        "lon": geo.get("lng"),
        "vicinity": r.get("vicinity"),
        "business_status": r.get("business_status"),
        "permanently_closed": r.get("permanently_closed"),
        "source_lat": source_lat,
        "source_lon": source_lon,
        "grid_id": grid_id
    }

def append_base_records(rows: List[Dict]):
    fieldnames = [
        "place_id","name","types","rating","user_ratings_total","price_level",
        "lat","lon","vicinity","business_status","permanently_closed",
        "source_lat","source_lon","grid_id"
    ]
    file_exists = CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists: w.writeheader()
        for row in rows: w.writerow(row)

def load_seen_place_ids() -> Set[str]:
    seen: Set[str] = set()
    if CSV_PATH.exists():
        with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("place_id")
                if pid: seen.add(pid)
    return seen

def save_grid(grid: List[Tuple[float, float]]):
    with GRID_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["grid_id","lat","lon"])
        for i,(la,lo) in enumerate(grid):
            w.writerow([i, la, lo])

def save_progress(idx: int, total: int):
    LOG_PATH.write_text(json.dumps({"last_index": idx, "total": total}, indent=2))

def load_progress() -> int:
    if LOG_PATH.exists():
        try:
            return int(json.loads(LOG_PATH.read_text()).get("last_index", -1))
        except Exception:
            return -1
    return -1

# ---------------------- Details & enrichment ---------------------- #

def get_place_details(place_id: str) -> Optional[Dict]:
    params = {"key": API_KEY, "place_id": place_id, "fields": DETAILS_FIELDS}
    data = safe_request(DETAILS_URL, params)
    if data.get("status") != "OK":
        return None
    return data.get("result", {})

def cuisine_from_text(text: str) -> Optional[str]:
    t = (text or "").lower()
    for cuisine, kws in CUISINE_KEYWORDS.items():
        for kw in kws:
            # word boundary fix
            if re.search(rf"\b{re.escape(kw)}\b", t):
                return cuisine
    return None

def infer_cuisine(name: str, types: List[str], editorial: Optional[str], reviews: List[Dict]) -> tuple[str,str]:
    c = cuisine_from_text(name or "")
    if c: return c, "name"
    if editorial:
        c = cuisine_from_text(editorial)
        if c: return c, "editorial_summary"
    joined = " ".join([rv.get("text","") or "" for rv in reviews])[:8000]
    c = cuisine_from_text(joined)
    if c: return c, "reviews"
    types_text = " ".join(types or [])
    c = cuisine_from_text(types_text)
    if c: return c, "types"
    return "unknown", ""

def summarize_review_languages(reviews: List[Dict]) -> tuple[str, float, int, Dict[str,int]]:
    counts: Dict[str,int] = {}
    for rv in reviews:
        lang = rv.get("language") or "und"
        counts[lang] = counts.get(lang, 0) + 1
    n = sum(counts.values())
    if n == 0: return ("", 0.0, 0, {})
    top_lang, top_cnt = max(counts.items(), key=lambda x: x[1])
    return (top_lang, top_cnt / n, n, counts)

def append_details_record(row: Dict):
    fieldnames = [
        "place_id","name","types","rating","user_ratings_total","price_level",
        "lat","lon","vicinity","business_status",
        "editorial_summary","website","international_phone_number",
        "cuisine_detected","cuisine_source","top_review_language","top_language_share","n_reviews_fetched","review_language_counts_json"
    ]
    file_exists = DETAILS_CSV.exists()
    with DETAILS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists: w.writeheader()
        w.writerow(row)

def append_reviews(place_id: str, reviews: List[Dict]):
    fieldnames = ["place_id","author_name","language","rating","relative_time_description","time","text"]
    file_exists = REVIEWS_CSV.exists()
    with REVIEWS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists: w.writeheader()
        for rv in reviews:
            w.writerow({
                "place_id": place_id,
                "author_name": rv.get("author_name"),
                "language": rv.get("language"),
                "rating": rv.get("rating"),
                "relative_time_description": rv.get("relative_time_description"),
                "time": rv.get("time"),
                "text": rv.get("text"),
            })

# ---------------------- Extended cuisine + brand helpers ---------------------- #

# Normalization helpers for brand and text
def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _domain(host: str) -> str:
    h = (host or "").lower()
    # strip common subdomains
    h = re.sub(r"^(www\d?|m)\.", "", h)
    return h

# Scoring helper for robust detection
def _score_cuisines(text: str, weight: float, scores: Dict[str, float]):
    """
    Scans text for keywords from both standard and extended lists.
    Adds 'weight' to the score of any detected cuisine.
    """
    t = _normalize_text(text)
    # Check standard keywords
    for cuisine, kws in CUISINE_KEYWORDS.items():
        for kw in kws:
            # Use word boundary check for accuracy
            if re.search(rf"\b{re.escape(kw)}\b", t):
                scores[cuisine] = scores.get(cuisine, 0.0) + weight
                # Break inner loop to avoid double counting same cuisine for same text block
                break 
    
    # Check extended keywords
    for cuisine, kws in EXTENDED_CUISINE_KEYWORDS.items():
        for kw in kws:
            if re.search(rf"\b{re.escape(kw)}\b", t):
                scores[cuisine] = scores.get(cuisine, 0.0) + weight
                break

# Detect brand from name/website
def detect_brand(name: str, website: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    n = (name or "").lower()
    w = _domain(website)
    
    for brand, info in BRAND_KEYWORDS.items():
        # Check name
        if brand in n:
            # simple check: is it a distinct word or the whole name?
            if re.search(rf"\b{re.escape(brand)}\b", n):
                return brand, info.get("category"), "name_match"
        
        # Check website (if brand name is in domain)
        brand_clean = brand.replace(" ", "")
        if brand_clean in w:
            return brand, info.get("category"), "website_match"
            
    return None, None, None

# Extended cuisine inference combining extra keywords + brand
def extended_infer_cuisine(name: str, types: List[str], editorial: Optional[str], reviews: List[Dict], website: Optional[str]) -> Tuple[str, str, Optional[str], Optional[str], Optional[str]]:
    # 1) Brand takes precedence (High confidence)
    b_name, b_cat, b_src = detect_brand(name, website)
    if b_name:
        # if we have a mapped cuisine for the brand, use it
        cuisine = BRAND_KEYWORDS[b_name].get("cuisine") or (b_cat or "unknown")
        return cuisine, "brand", b_name, b_cat, b_src

    # 2) Scoring System
    scores: Dict[str, float] = {}

    # A. Name (High weight)
    _score_cuisines(name or "", 5.0, scores)

    # B. Types (Medium-High weight) - filter out generic types first
    ignored_types = {"restaurant", "food", "point_of_interest", "establishment", "store"}
    valid_types = [t for t in (types or []) if t not in ignored_types]
    _score_cuisines(" ".join(valid_types), 3.0, scores)

    # C. Editorial Summary (Medium weight)
    if editorial:
        _score_cuisines(editorial, 2.0, scores)

    # D. Reviews (Low weight, cumulative)
    # Only scan a subset of reviews to avoid noise
    if reviews:
        review_text = " ".join([(rv.get("text") or "") for rv in reviews[:5]])
        _score_cuisines(review_text, 0.5, scores)

    # 3) Determine Winner
    if not scores:
        return "unknown", "", None, None, None

    # Sort by score descending
    best_cuisine, best_score = max(scores.items(), key=lambda item: item[1])

    # Threshold check (optional, e.g. must have at least 1.0 score)
    if best_score < 0.5:
        return "unknown", "low_confidence", None, None, None

    # Determine source based on what contributed most (heuristic)
    # We re-check where the winner came from to attribute source
    source = "mixed"
    if _check_match(name, best_cuisine):
        source = "name"
    elif _check_match(" ".join(valid_types), best_cuisine):
        source = "types"
    elif editorial and _check_match(editorial, best_cuisine):
        source = "editorial"
    elif reviews and _check_match(review_text, best_cuisine):
        source = "reviews"

    return best_cuisine, source, None, None, None

def _check_match(text: str, cuisine: str) -> bool:
    """Helper to verify if a specific cuisine's keywords appear in text."""
    t = _normalize_text(text or "")
    # Check standard
    if cuisine in CUISINE_KEYWORDS:
        for kw in CUISINE_KEYWORDS[cuisine]:
            if re.search(rf"\b{re.escape(kw)}\b", t): return True
    # Check extended
    if cuisine in EXTENDED_CUISINE_KEYWORDS:
        for kw in EXTENDED_CUISINE_KEYWORDS[cuisine]:
            if re.search(rf"\b{re.escape(kw)}\b", t): return True
    return False

def _load_reviews_by_place(limit_per_place: int = 5) -> Dict[str, List[Dict]]:
    reviews: Dict[str, List[Dict]] = {}
    if not REVIEWS_CSV.exists():
        return reviews
    
    with REVIEWS_CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("place_id")
            if not pid: continue
            if pid not in reviews:
                reviews[pid] = []
            if len(reviews[pid]) < limit_per_place:
                reviews[pid].append(row)
    return reviews

def _detail_stub_from_base(base_row: Dict) -> Dict:
    return {
        "place_id": base_row.get("place_id"),
        "name": base_row.get("name"),
        "types": base_row.get("types"),
        "rating": base_row.get("rating"),
        "user_ratings_total": base_row.get("user_ratings_total"),
        "price_level": base_row.get("price_level"),
        "lat": base_row.get("lat"),
        "lon": base_row.get("lon"),
        "vicinity": base_row.get("vicinity"),
        "business_status": base_row.get("business_status"),
        "editorial_summary": "",
        "website": "",
        "international_phone_number": "",
        "cuisine_detected": "unknown",
        "cuisine_source": "",
        "top_review_language": "",
        "top_language_share": 0.0,
        "n_reviews_fetched": 0,
        "review_language_counts_json": "{}"
    }

def extend_cuisine_offline(out_path: Optional[pathlib.Path] = None, inplace: bool = False, use_reviews: bool = True,
                           limit_reviews: int = 5, verbose: bool = False, sample_n: int = 8, from_base: bool = False):
    if not DETAILS_CSV.exists() and not (from_base and CSV_PATH.exists()):
        print("ERROR: No input CSVs found.")
        sys.exit(2)

    rows: List[Dict] = []
    fieldnames: List[str] = []

    # Load current details rows if present
    if DETAILS_CSV.exists():
        with DETAILS_CSV.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = (reader.fieldnames or [])
    else:
        rows = []
        fieldnames = [
            "place_id","name","types","rating","user_ratings_total","price_level",
            "lat","lon","vicinity","business_status",
            "editorial_summary","website","international_phone_number",
            "cuisine_detected","cuisine_source","top_review_language","top_language_share","n_reviews_fetched","review_language_counts_json"
        ]

    # Optionally add missing place_ids from base CSV
    if from_base:
        if not CSV_PATH.exists():
            print(f"ERROR: Base CSV not found at {CSV_PATH}")
            sys.exit(2)
        with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
            base_reader = csv.DictReader(f)
            base_rows = list(base_reader)
        detail_by_pid = {r.get("place_id",""): r for r in rows if r.get("place_id")}
        added = 0
        for b in base_rows:
            pid = b.get("place_id","")
            if pid and pid not in detail_by_pid:
                stub = _detail_stub_from_base(b)
                rows.append(stub)
                added += 1
        if verbose:
            print(f"[info] Added {added} missing rows from base.")

    # Ensure appended fields exist
    new_fields = ["cuisine_detected_ext","cuisine_source_ext","brand_name","brand_category","brand_source"]
    for nf in new_fields:
        if nf not in fieldnames:
            fieldnames.append(nf)

    # Load reviews (limited per place)
    reviews_by_pid = _load_reviews_by_place(limit_per_place=limit_reviews) if use_reviews else {}

    changes = 0
    samples = []

    for row in rows:
        pid = row.get("place_id") or ""
        name = row.get("name") or ""
        types_list = [t.strip() for t in (row.get("types") or "").split(",") if t.strip()]
        editorial = row.get("editorial_summary") or ""
        website = row.get("website")
        reviews = reviews_by_pid.get(pid, [])

        cuisine_ext, source_ext, brand_name, brand_category, brand_source = extended_infer_cuisine(
            name, types_list, editorial, reviews, website
        )

        prev_c = row.get("cuisine_detected_ext")
        prev_b = row.get("brand_name")
        if (prev_c != cuisine_ext) or (prev_b != (brand_name or "")):
            changes += 1
            if verbose and len(samples) < sample_n:
                samples.append({
                    "place_id": pid,
                    "name": name[:80],
                    "cuisine_ext": cuisine_ext,
                    "source_ext": source_ext,
                    "brand": brand_name,
                    "brand_cat": brand_category,
                    "brand_src": brand_source
                })

        row["cuisine_detected_ext"] = cuisine_ext
        row["cuisine_source_ext"] = source_ext
        row["brand_name"] = brand_name or ""
        row["brand_category"] = brand_category or ""
        row["brand_source"] = brand_source or ""

    if verbose and samples:
        print("[info] Sample extended detections:")
        for s in samples:
            print(f"  {s['place_id']}: '{s['name']}' -> cuisine={s['cuisine_ext']} (src={s['source_ext']}), brand={s['brand']} ({s['brand_cat']}, via {s['brand_src']})")

    # Decide output
    if inplace:
        backup = DETAILS_CSV.with_suffix(".details.bak.csv")
        if DETAILS_CSV.exists():
            shutil.copy(DETAILS_CSV, backup)
            print(f"[info] Backed up original details to {backup}")
        out_file = DETAILS_CSV
    else:
        out_file = out_path or (OUTDIR / ("london_restaurant_details.extended.csv" if not from_base else "london_restaurant_details.extended_full.csv"))
        out_file.parent.mkdir(parents=True, exist_ok=True)

    with out_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"[done] Extended cuisine/brand computed for {len(rows)} places ({changes} updated).")
    print(f"[info] Output written to: {out_file.resolve()}")

# ---------------------- Visualization ---------------------- #
# read value counts for a column in details CSV
def _value_counts_from_details(column: str, exclude_unknown: bool = True, min_count: int = 0) -> Tuple[List[str], List[int]]:
    if not DETAILS_CSV.exists():
        print(f"ERROR: Details CSV not found at {DETAILS_CSV}")
        return [], []
    with DETAILS_CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or column not in reader.fieldnames:
            print(f"ERROR: Column '{column}' not found in details CSV.")
            return [], []
        counts: Dict[str, int] = {}
        total = 0
        for row in reader:
            v = (row.get(column) or "").strip()
            if not v:
                continue
            v_norm = v.lower()
            if exclude_unknown and v_norm in ("unknown", "und", "n/a"):
                continue
            total += 1
            counts[v] = counts.get(v, 0) + 1
    # apply min_count filter and sort
    items = [(k, c) for k, c in counts.items() if c >= min_count]
    items.sort(key=lambda x: (-x[1], x[0]))
    labels = [k for k, _ in items]
    values = [c for _, c in items]
    return labels, values

# palette helper
def _make_palette(n: int, theme: str = "dark"):
    cmap_name = "viridis" if theme == "dark" else "mako"
    if sns:
        try:
            return sns.color_palette(cmap_name, n)
        except Exception:
            pass
    if mpl:
        cmap = mpl.cm.get_cmap("viridis" if theme == "dark" else "plasma")
        return [cmap((i + 0.5) / max(n, 1)) for i in range(n)]
    # fallback
    return [(0.2, 0.4, 0.8, 1.0)] * n

# Bar chart for top cuisines
def _plot_cuisine_bar(labels: List[str], values: List[int], title: str, theme: str, out_base: pathlib.Path, total: Optional[int] = None):
    if plt is None:
        print("ERROR: matplotlib not available. Try: pip install matplotlib seaborn")
        return
    n = len(labels)
    if n == 0:
        print("[info] Nothing to plot.")
        return
    if sns:
        sns.set_theme(style="whitegrid" if theme == "light" else "darkgrid", context="talk")
    colors = _make_palette(n, theme=theme)
    # dynamic figure height
    h = max(6, 0.45 * n + 2)
    fig, ax = plt.subplots(figsize=(12, h), dpi=150, constrained_layout=True)
    y_pos = list(range(n))[::-1]
    labels_rev = labels[::-1]
    values_rev = values[::-1]
    ax.barh(y_pos, values_rev, color=colors[::-1], edgecolor="none")
    sum_vals = sum(values) if total is None else total
    for i, v in enumerate(values_rev):
        pct = (v / sum_vals * 100.0) if sum_vals else 0.0
        ax.text(v + max(values) * 0.01, i, f"{v} ({pct:.1f}%)", va="center", fontsize=10, color="#444" if theme == "light" else "#ddd")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels_rev)
    ax.set_xlabel("Count")
    ax.set_title(title, pad=14, weight="bold")
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    png = out_base.with_suffix(".png")
    svg = out_base.with_suffix(".svg")
    plt.savefig(png)
    plt.savefig(svg)
    plt.close(fig)
    print(f"[plot] Saved bar chart to: {png}")

# Donut chart for top cuisines (with 'Others' aggregated)
def _plot_cuisine_donut(labels: List[str], values: List[int], title: str, theme: str, out_base: pathlib.Path, top_n: int = 8):
    if plt is None:
        print("ERROR: matplotlib not available. Try: pip install matplotlib seaborn")
        return
    if len(labels) == 0:
        print("[info] Nothing to plot.")
        return
    # aggregate top_n and others
    top_labels = labels[:top_n]
    top_values = values[:top_n]
    other_sum = sum(values[top_n:])
    if other_sum > 0:
        top_labels = top_labels + ["Others"]
        top_values = top_values + [other_sum]
    colors = _make_palette(len(top_labels), theme=theme)
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150, constrained_layout=True)
    wedges, _ = ax.pie(
        top_values,
        labels=None,
        colors=colors,
        startangle=140,
        wedgeprops=dict(width=0.35, edgecolor="white")
    )
    # add legend with labels and percentages
    total = sum(top_values)
    legend_labels = [f"{l} • {v} ({(v/total*100):.1f}%)" for l, v in zip(top_labels, top_values)]
    ax.legend(wedges, legend_labels, title="Cuisines", loc="center left", bbox_to_anchor=(1.0, 0.5))
    ax.set_title(title, weight="bold")
    # center text
    ax.text(0, 0, f"{total}\nplaces", ha="center", va="center", fontsize=12, weight="bold")
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    png = out_base.with_suffix(".donut.png")
    svg = out_base.with_suffix(".donut.svg")
    plt.savefig(png, bbox_inches="tight")
    plt.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] Saved donut chart to: {png}")

# Brand bar chart (optional)
def _plot_brand_bar(top_n: int = 20, theme: str = "dark"):
    labels, values = _value_counts_from_details("brand_name", exclude_unknown=True, min_count=1)
    # filter empties
    filtered = [(l, v) for l, v in zip(labels, values) if l.strip()]
    if not filtered:
        print("[info] No brands to plot.")
        return
    filtered.sort(key=lambda x: -x[1])
    labels = [l for l, _ in filtered[:top_n]]
    values = [v for _, v in filtered[:top_n]]
    ts = int(time.time())
    out_base = PLOTS_DIR / f"brands_top{len(labels)}_{ts}"
    _plot_cuisine_bar(labels, values, f"Top {len(labels)} brands", theme, out_base)

# Public API to plot cuisines
def plot_cuisine_frequency(column: str = "auto", top_n: int = 20, min_count: int = 0, theme: str = "dark", include_donut: bool = True, title: Optional[str] = None):
    if plt is None:
        print("ERROR: matplotlib not available. Try: pip install matplotlib seaborn")
        return
    if not DETAILS_CSV.exists():
        print(f"ERROR: Details CSV not found at {DETAILS_CSV}")
        return
    # determine column
    with DETAILS_CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
    if column == "auto":
        if "cuisine_detected_ext" in fields:
            column = "cuisine_detected_ext"
        elif "cuisine_detected" in fields:
            column = "cuisine_detected"
        else:
            print("ERROR: No cuisine column found in details CSV.")
            return
    labels, values = _value_counts_from_details(column, exclude_unknown=True, min_count=min_count)
    if not labels:
        print(f"[info] No values to plot for column '{column}'.")
        return
    # trim to top_n
    labels = labels[:top_n]
    values = values[:top_n]
    total = sum(values)
    ts = int(time.time())
    out_base = PLOTS_DIR / f"{column}_top{len(labels)}_{ts}"
    nice_title = title or f"Top {len(labels)} cuisines ({column})"
    _plot_cuisine_bar(labels, values, nice_title, theme, out_base, total=total)
    if include_donut:
        _plot_cuisine_donut(labels, values, f"{nice_title} – share", theme, out_base, top_n=min(8, len(labels)))

# ---------------------- Main ---------------------- #

STOP = False
def handle_sigint(sig, frame):
    global STOP
    STOP = True
    print("\\n[info] Caught interrupt. Finishing current step and exiting...")
signal.signal(signal.SIGINT, handle_sigint)

def main():
    if not API_KEY:
        print("ERROR: Please set GOOGLE_MAPS_API_KEY in .env")
        sys.exit(1)

    OUTDIR.mkdir(parents=True, exist_ok=True)

    grid = generate_grid(LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, GRID_STEP_KM)
    save_grid(grid)
    total_points = len(grid)
    print(f"[info] Grid points: {total_points} (step {GRID_STEP_KM} km)")

    start_idx = load_progress() + 1
    if start_idx >= total_points: start_idx = 0
    if start_idx > 0: print(f"[info] Resuming from grid index {start_idx}")

    seen_place_ids: Set[str] = load_seen_place_ids()
    print(f"[info] Already collected base places: {len(seen_place_ids)}")

    for i in range(start_idx, total_points):
        if STOP: break
        lat, lon = grid[i]
        print(f"[info] ({i+1}/{total_points}) Nearby lat={lat:.5f}, lon={lon:.5f}")
        try:
            results = places_nearby_all_pages(lat, lon, RADIUS_M, PLACE_TYPE)
        except Exception as e:
            print(f"[warn] Nearby failed at grid {i}: {e}")
            save_progress(i, total_points); time.sleep(1.0); continue

        new_base_rows = []
        new_ids = []
        for r in results:
            pid = r.get("place_id")
            if not pid or pid in seen_place_ids: continue
            row = normalize_base_record(r, lat, lon, i)
            new_base_rows.append(row)
            new_ids.append(pid)
            seen_place_ids.add(pid)

        if new_base_rows:
            append_base_records(new_base_rows)
            print(f"[info] Added {len(new_base_rows)} new base places (total {len(seen_place_ids)})")
        else:
            print("[info] No new base places from this grid point.]")

        # Enrich
        for pid in new_ids:
            if STOP: break
            try:
                det = get_place_details(pid)
            except Exception as e:
                print(f"[warn] Details failed for {pid}: {e}")
                det = None
            time.sleep(DETAILS_SLEEP_S)
            if not det: continue

            name = det.get("name","")
            types = det.get("types",[]) or []
            rating = det.get("rating")
            price_level = det.get("price_level")
            urt = det.get("user_ratings_total")
            editorial = (det.get("editorial_summary") or {}).get("overview")
            website = det.get("website")
            phone = det.get("international_phone_number")
            vicinity = det.get("vicinity")
            bs = det.get("business_status")
            geo = det.get("geometry",{}).get("location",{})
            lat2, lon2 = geo.get("lat"), geo.get("lng")
            reviews = det.get("reviews",[]) or []

            cuisine, source = infer_cuisine(name, types, editorial, reviews)
            top_lang, top_share, n_reviews, counts = summarize_review_languages(reviews)

            details_row = {
                "place_id": pid,
                "name": name,
                "types": ",".join(types),
                "rating": rating,
                "user_ratings_total": urt,
                "price_level": price_level,
                "lat": lat2,
                "lon": lon2,
                "vicinity": vicinity,
                "business_status": bs,
                "editorial_summary": editorial,
                "website": website,
                "international_phone_number": phone,
                "cuisine_detected": cuisine,
                "cuisine_source": source,
                "top_review_language": top_lang,
                "top_language_share": round(top_share,3) if top_share else 0.0,
                "n_reviews_fetched": n_reviews,
                "review_language_counts_json": json.dumps(counts, ensure_ascii=False)
            }
            append_details_record(details_row)
            if reviews: append_reviews(pid, reviews)

        save_progress(i, total_points)
        time.sleep(REQUEST_SLEEP_S)

    print("[done] Collection + enrichment complete.")
    print("Base CSV:", CSV_PATH.resolve())
    print("Details CSV:", DETAILS_CSV.resolve())
    print("Reviews CSV:", REVIEWS_CSV.resolve())
# CLI entry for offline extended cuisine enrichment
if __name__ == "__main__":
    if "--extend-cuisine" in sys.argv:
        inplace = "--inplace" in sys.argv
        verbose = "--verbose" in sys.argv
        use_reviews = "--no-reviews" not in sys.argv
        from_base = "--from-base" in sys.argv
        # optional: --out <path>, --limit-reviews N, --sample N
        out_path: Optional[pathlib.Path] = None
        limit_reviews = 5
        sample_n = 8
        if "--out" in sys.argv:
            i = sys.argv.index("--out")
            if i + 1 < len(sys.argv):
                out_path = pathlib.Path(sys.argv[i + 1])
        if "--limit-reviews" in sys.argv:
            i = sys.argv.index("--limit-reviews")
            if i + 1 < len(sys.argv):
                try:
                    limit_reviews = int(sys.argv[i + 1])
                except ValueError:
                    pass
        if "--sample" in sys.argv and verbose:
            i = sys.argv.index("--sample")
            if i + 1 < len(sys.argv):
                try:
                    sample_n = int(sys.argv[i + 1])
                except ValueError:
                    pass
        extend_cuisine_offline(out_path=out_path, inplace=inplace, use_reviews=use_reviews,
                               limit_reviews=limit_reviews, verbose=verbose, sample_n=sample_n,
                               from_base=from_base)
        sys.exit(0)

    # CLI entry for plotting cuisines
    if "--plot-cuisines" in sys.argv:
        # options: --column <name|auto> --top N --min-count N --theme light|dark --no-donut --brands --title "..."
        column = "auto"
        top_n = 20
        min_count = 0
        theme = "dark"
        include_donut = True
        title = None
        if "--column" in sys.argv:
            i = sys.argv.index("--column")
            if i + 1 < len(sys.argv):
                column = sys.argv[i + 1]
        if "--top" in sys.argv:
            i = sys.argv.index("--top")
            if i + 1 < len(sys.argv):
                try:
                    top_n = int(sys.argv[i + 1])
                except ValueError:
                    pass
        if "--min-count" in sys.argv:
            i = sys.argv.index("--min-count")
            if i + 1 < len(sys.argv):
                try:
                    min_count = int(sys.argv[i + 1])
                except ValueError:
                    pass
        if "--theme" in sys.argv:
            i = sys.argv.index("--theme")
            if i + 1 < len(sys.argv):
                theme = sys.argv[i + 1].lower().strip()
                if theme not in ("light", "dark"):
                    theme = "dark"
        if "--no-donut" in sys.argv:
            include_donut = False
        if "--title" in sys.argv:
            i = sys.argv.index("--title")
            if i + 1 < len(sys.argv):
                title = sys.argv[i + 1]
        plot_cuisine_frequency(column=column, top_n=top_n, min_count=min_count, theme=theme, include_donut=include_donut, title=title)
        if "--brands" in sys.argv:
            _plot_brand_bar(top_n=top_n, theme=theme)
        sys.exit(0)

    main()