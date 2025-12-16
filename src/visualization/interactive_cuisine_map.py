import pandas as pd
import json
import os
import sys
import argparse
import geopandas as gpd
from shapely.geometry import Point

# Determine the project root based on this script's location
# Script is in src/visualization/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_INPUT_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
DEFAULT_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

# ============================================================
# 1. LOAD AND PREPARE DATA
# ============================================================
def get_args():
    parser = argparse.ArgumentParser(description="Create interactive cuisine map")
    parser.add_argument("--input-dir", type=str, default=DEFAULT_INPUT_DIR, help="Input directory")
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--city-name", type=str, default="london", help="City name")
    parser.add_argument("--boroughs-file", type=str, default=os.path.join(DEFAULT_DATA_DIR, "london_boroughs.geojson"), help="Path to boroughs geojson")
    return parser.parse_known_args()[0]

args = get_args()

INPUT_FILE = os.path.join(args.input_dir, f"{args.city_name}_hype_adjusted_ratings.csv")
BOROUGH_FILE = args.boroughs_file
OUTPUT_FILE = os.path.join(args.output_dir, f"{args.city_name}_restaurants_interactive.html")

# Check if input file exists, if not try sample or fail
if not os.path.exists(INPUT_FILE):
    print(f"Warning: {INPUT_FILE} not found.")
print(f"Loading {INPUT_FILE}...")
try:
    df = pd.read_csv(INPUT_FILE)
except FileNotFoundError:
    print(f"Error: Could not find {INPUT_FILE}. Please run the analysis script first.")
    sys.exit(1)

# Ensure df is defined
if 'df' not in locals():
    print("Error: DataFrame not loaded.")
    sys.exit(1)

# Filter valid coordinates
df = df.dropna(subset=["lat", "lon"])

# --- SPATIAL JOIN FOR BOROUGHS ---
print("Assigning boroughs...")
borough_centers = {}
all_borough_names = []
try:
    boroughs = gpd.read_file(BOROUGH_FILE)
    # Ensure CRS matches (assuming WGS84 for lat/lon)
    if boroughs.crs is None:
        boroughs.set_crs(epsg=4326, inplace=True)
    
    # Calculate centroids for zooming
    # Reproject to a projected CRS for accurate centroid calculation if needed, 
    # but for simple zooming WGS84 centroid is usually fine enough for this scale.
    for _, row in boroughs.iterrows():
        if row.geometry:
            c = row.geometry.centroid
            # Use 'name' as it hasn't been renamed to 'borough_name' yet
            borough_centers[row['name']] = [c.y, c.x]

    # Keep a complete list of borough names for the UI dropdown (even if
    # no restaurants are currently assigned to that borough).
    all_borough_names = sorted([str(k) for k in borough_centers.keys() if str(k) and str(k) != "Unknown"])

    # Create GeoDataFrame for restaurants
    geometry = [Point(xy) for xy in zip(df.lon, df.lat)]
    gdf_restaurants = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    
    # Spatial Join
    # Rename borough 'name' to avoid conflict
    boroughs = boroughs.rename(columns={'name': 'borough_name'})
    
    # Perform join
    joined = gpd.sjoin(gdf_restaurants, boroughs[['borough_name', 'geometry']], how="left", predicate="within")
    
    # Assign back to df
    df['borough'] = joined['borough_name'].fillna("Unknown")
    print("Borough assignment complete.")
except Exception as e:
    print(f"Warning: Could not assign boroughs ({e}). Defaulting to 'Unknown'.")
    df['borough'] = "Unknown"
    all_borough_names = []

# Normalize cuisine column
def format_cuisine_name(c):
    c = str(c).replace("_", " ").title()
    if c == "Fish And Chips":
        return "Fish and Chips"
    if c == "Middle Eastern": # Already title cased, but ensuring consistency
        return "Middle Eastern"
    return c

df["cuisine"] = df["cuisine"].fillna("Unknown").apply(format_cuisine_name)

# Use all identified cuisines (no grouping into 'Other')
df["cuisine_group"] = df["cuisine"]

# Chain vs independent (expected in analyzed CSV; fallback to 0=independent if missing)
if "is_chain" not in df.columns:
    df["is_chain"] = 0

# Bounds for initial map view (ensure categories outside central London still appear)
data_bounds = [
    [float(df["lat"].min()), float(df["lon"].min())],
    [float(df["lat"].max()), float(df["lon"].max())],
]

# Prepare data list for JSON
data_list = []
for _, row in df.iterrows():
    try:
        item = {
            "lat": round(float(row["lat"]), 5),
            "lon": round(float(row["lon"]), 5),
            "name": str(row["name"]).replace('"', ''),
            "cuisine": str(row["cuisine"]),
            "cuisine_group": str(row["cuisine_group"]),
            "rating": float(row["rating"]) if pd.notnull(row["rating"]) else 0.0,
            "reviews": int(row["user_ratings_total"]) if pd.notnull(row["user_ratings_total"]) else 0,
            "price": int(row["price_level"]) if pd.notnull(row["price_level"]) else 1,
            "vicinity": str(row["vicinity"]).replace('"', ''),
            "hype_residual": round(float(row["hype_residual"]), 2) if pd.notnull(row.get("hype_residual")) else 0.0,
            "borough": str(row["borough"]),
            "is_chain": int(row["is_chain"]) if pd.notnull(row.get("is_chain")) else 0,
        }
        data_list.append(item)
    except (ValueError, TypeError):
        continue

print(f"Exporting {len(data_list)} restaurants to HTML...")

# ============================================================
# 2. GENERATE HTML
# ============================================================

html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{args.city_name.capitalize()} Restaurant Map</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Google Fonts: Inter for a clean, professional look -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
    
    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
     integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
     crossorigin=""/>
     
    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
     integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
     crossorigin=""></script>

    <style>
        body {{ margin: 0; padding: 0; font-family: 'Inter', sans-serif; color: #333; }}
        #map {{ position: absolute; top: 0; bottom: 0; width: 100%; z-index: 1; }}
        
        /* --- Professional Sidebar --- */
        #sidebar {{
            position: absolute;
            top: 20px;
            left: 20px;
            bottom: 20px;
            width: 320px;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            z-index: 1000;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 20px;
            transition: transform 0.3s ease;
        }}
        
        /* Mobile toggle */
        #sidebar-toggle {{
            display: none;
            position: absolute;
            top: 20px;
            left: 20px;
            z-index: 1001;
            background: white;
            border: none;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: pointer;
        }}

        /* Fullscreen Button */
        #fullscreen-btn {{
            position: absolute;
            top: 20px;
            right: 60px;
            z-index: 1001;
            background: white;
            border: none;
            padding: 10px 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            font-size: 13px;
            color: #333;
            transition: background 0.2s;
        }}
        #fullscreen-btn:hover {{ background: #f5f5f5; }}

        /* Help Button */
        #help-btn {{
            position: absolute;
            top: 20px;
            right: 170px;
            z-index: 1001;
            background: white;
            border: none;
            padding: 10px 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            font-size: 13px;
            color: #333;
            transition: background 0.2s;
        }}
        #help-btn:hover {{ background: #f5f5f5; }}

        /* Modal Styling */
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 2000;
            justify-content: center;
            align-items: center;
        }}
        .modal-content {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            max-width: 500px;
            width: 90%;
            box-shadow: 0 20px 50px rgba(0,0,0,0.2);
            position: relative;
            animation: slideUp 0.3s ease;
        }}
        @keyframes slideUp {{
            from {{ transform: translateY(20px); opacity: 0; }}
            to {{ transform: translateY(0); opacity: 1; }}
        }}
        .close-modal {{
            position: absolute;
            top: 15px;
            right: 15px;
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: #666;
        }}
        .tutorial-step {{
            margin-bottom: 20px;
            display: flex;
            gap: 15px;
        }}
        .step-icon {{
            width: 40px;
            height: 40px;
            background: #f0f0f0;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            flex-shrink: 0;
        }}

        h1 {{ margin: 0; font-size: 22px; font-weight: 600; color: #1a1a1a; letter-spacing: -0.5px; }}
        h2 {{ margin: 0 0 10px 0; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #888; font-weight: 600; }}
        
        .control-section {{ border-bottom: 1px solid #eee; padding-bottom: 20px; }}
        .control-section:last-child {{ border-bottom: none; }}

        /* Inputs */
        input[type="text"] {{
            width: 100%;
            padding: 12px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            font-family: 'Inter', sans-serif;
            font-size: 14px;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }}
        input[type="text"]:focus {{ outline: none; border-color: #333; }}

        select {{
            width: 100%;
            padding: 10px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            font-family: 'Inter', sans-serif;
            font-size: 14px;
            background-color: white;
            cursor: pointer;
        }}

        /* Toggle Switch */
        .toggle-container {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 15px;
            cursor: pointer;
        }}
        .toggle-label {{ font-size: 14px; font-weight: 500; color: #333; }}
        .toggle-switch {{
            position: relative;
            width: 40px;
            height: 20px;
            background: #e0e0e0;
            border-radius: 20px;
            transition: background 0.3s;
        }}
        .toggle-switch::after {{
            content: '';
            position: absolute;
            top: 2px;
            left: 2px;
            width: 16px;
            height: 16px;
            background: white;
            border-radius: 50%;
            transition: transform 0.3s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }}
        input[type="checkbox"] {{ display: none; }}
        input[type="checkbox"]:checked + .toggle-switch {{ background: #2a9d8f; }}
        input[type="checkbox"]:checked + .toggle-switch::after {{ transform: translateX(20px); }}

        /* Custom Range Slider */
        .range-container {{ margin-top: 10px; }}
        .range-header {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; font-weight: 500; }}
        input[type=range] {{
            width: 100%;
            -webkit-appearance: none;
            background: transparent;
        }}
        input[type=range]::-webkit-slider-thumb {{
            -webkit-appearance: none;
            height: 16px;
            width: 16px;
            border-radius: 50%;
            background: #1a1a1a;
            cursor: pointer;
            margin-top: -6px;
        }}
        input[type=range]::-webkit-slider-runnable-track {{
            width: 100%;
            height: 4px;
            cursor: pointer;
            background: #e0e0e0;
            border-radius: 2px;
        }}

        /* Price Filter Buttons */
        .price-buttons {{ display: flex; gap: 8px; }}
        .price-btn {{
            flex: 1;
            padding: 8px;
            border: 1px solid #e0e0e0;
            background: white;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
            text-align: center;
        }}
        .price-btn.active {{
            background: #1a1a1a;
            color: white;
            border-color: #1a1a1a;
        }}

        /* Stats & Legend */
        .stats {{ 
            background: #f8f9fa; 
            padding: 15px; 
            border-radius: 8px; 
            font-size: 13px; 
            color: #555;
            text-align: center;
        }}
        .stats strong {{ color: #1a1a1a; font-size: 16px; display: block; margin-bottom: 4px; }}

        .legend {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; max-height: 150px; overflow-y: auto; }}
        .legend-item {{ display: flex; align-items: center; font-size: 12px; color: #555; cursor: pointer; padding: 2px; border-radius: 4px; }}
        .legend-item:hover {{ background: #f0f0f0; }}
        .color-dot {{ width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; flex-shrink: 0; }}

        /* Popup Styling */
        .leaflet-popup-content-wrapper {{ border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); padding: 0; }}
        .leaflet-popup-content {{ margin: 0; width: 260px !important; }}
        .popup-header {{ background: #1a1a1a; color: white; padding: 12px 15px; border-radius: 8px 8px 0 0; }}
        .popup-title {{ font-weight: 600; font-size: 15px; margin: 0; }}
        .popup-body {{ padding: 15px; font-size: 13px; line-height: 1.5; }}
        .popup-meta {{ display: flex; justify-content: space-between; margin-bottom: 8px; color: #666; }}
        .popup-rating {{ font-weight: 600; color: #1a1a1a; display: flex; align-items: center; gap: 4px; }}
        .star-icon {{ color: #f59e0b; }}
        .popup-link {{ 
            display: block; 
            margin-top: 12px; 
            text-align: center; 
            background: #f0f0f0; 
            color: #333; 
            text-decoration: none; 
            padding: 8px; 
            border-radius: 6px; 
            font-weight: 500;
            transition: background 0.2s;
        }}
        .popup-link:hover {{ background: #e0e0e0; }}
        
        .underrated-badge {{
            background: #2a9d8f;
            color: white;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 5px;
        }}

        @media (max-width: 768px) {{
            #sidebar {{ transform: translateX(-110%); width: 85%; left: 0; top: 0; bottom: 0; border-radius: 0; }}
            #sidebar.open {{ transform: translateX(0); }}
            #sidebar-toggle {{ display: block; }}
            #fullscreen-btn {{ display: none; }} /* Hide fullscreen on mobile as it's less useful/buggy */
        }}
    </style>
</head>
<body>

<button id="sidebar-toggle" onclick="toggleSidebar()">☰ Filters</button>
<button id="fullscreen-btn" onclick="toggleFullscreen()">⛶ Fullscreen</button>
<button id="help-btn" onclick="toggleHelp()">? Help</button>

<div id="helpModal" class="modal-overlay" onclick="if(event.target === this) toggleHelp()">
    <div class="modal-content">
        <button class="close-modal" onclick="toggleHelp()">×</button>
        <h2 style="font-size: 20px; color: #1a1a1a; margin-bottom: 20px;">How to use this map</h2>
        
        <div class="tutorial-step">
            <div class="step-icon">💎</div>
            <div>
                <strong>Find Underrated Gems</strong>
                <p style="margin: 5px 0 0 0; color: #666; font-size: 13px;">Toggle "Highlight Underrated Gems" to see spots where our machine learning model thinks the rating should be higher than it is.</p>
            </div>
        </div>

        <div class="tutorial-step">
            <div class="step-icon">🔍</div>
            <div>
                <strong>Filter & Search</strong>
                <p style="margin: 5px 0 0 0; color: #666; font-size: 13px;">Use the sidebar to filter by borough, cuisine, price, rating, or search for a specific restaurant name.</p>
            </div>
        </div>

        <div class="tutorial-step">
            <div class="step-icon">🎨</div>
            <div>
                <strong>Explore Cuisines</strong>
                <p style="margin: 5px 0 0 0; color: #666; font-size: 13px;">Click items in the "Cuisines Legend" to instantly filter the map to that specific cuisine type.</p>
            </div>
        </div>
        
        <button onclick="toggleHelp()" style="width: 100%; padding: 12px; background: #1a1a1a; color: white; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; margin-top: 10px;">Got it!</button>
    </div>
</div>

<div id="sidebar">
    <div class="control-section">
        <h1>{args.city_name.capitalize()} Food Map</h1>
        <div style="font-size: 11px; color: #999; margin-top: 4px;">
            Built by <a href="https://laurenleek.eu" target="_blank" style="color: #666; text-decoration: none; font-weight: 500;">Lauren Leek</a>
        </div>
    </div>

    <div class="control-section">
        <input type="text" id="searchInput" placeholder="Search by name..." oninput="updateMap()">
    </div>

    <div class="control-section">
        <h2>Filters</h2>
        
        <label class="toggle-container">
            <span class="toggle-label">Highlight Underrated Gems</span>
            <input type="checkbox" id="underratedToggle" onchange="updateMap()">
            <div class="toggle-switch"></div>
        </label>

        <label class="toggle-container">
            <span class="toggle-label">Only Independents</span>
            <input type="checkbox" id="independentToggle" onchange="updateMap()">
            <div class="toggle-switch"></div>
        </label>
        
        <div style="margin-bottom: 15px;">
            <label style="display:block; font-size:12px; font-weight:500; margin-bottom:5px;">Borough</label>
            <select id="boroughSelect" onchange="onBoroughChange()">
                <option value="All">All Boroughs</option>
            </select>
        </div>

        <div style="margin-bottom: 15px;">
            <label style="display:block; font-size:12px; font-weight:500; margin-bottom:5px;">Cuisine</label>
            <select id="cuisineSelect" onchange="updateMap()">
                <option value="All">All Cuisines</option>
            </select>
        </div>

        <div class="range-container">
            <div class="range-header">
                <span>Min Rating</span>
                <span id="ratingVal">0.0</span>
            </div>
            <input type="range" id="ratingRange" min="0" max="5" step="0.1" value="0" oninput="updateMap()">
        </div>

        <div class="range-container">
            <div class="range-header">
                <span>Min Reviews</span>
                <span id="reviewVal">0</span>
            </div>
            <input type="range" id="reviewRange" min="0" max="500" step="10" value="0" oninput="updateMap()">
        </div>
    </div>

    <div class="control-section">
        <h2>Price Level</h2>
        <div class="price-buttons" id="priceFilters">
            <div class="price-btn active" onclick="togglePrice(1, this)">£</div>
            <div class="price-btn active" onclick="togglePrice(2, this)">££</div>
            <div class="price-btn active" onclick="togglePrice(3, this)">£££</div>
            <div class="price-btn active" onclick="togglePrice(4, this)">££££</div>
        </div>
    </div>

    <div class="control-section">
        <h2>Cuisines Legend</h2>
        <div id="legend" class="legend"></div>
    </div>

    <div class="stats" id="stats">
        <strong>0</strong> restaurants visible
    </div>
</div>

<div id="map"></div>

<script>
    // --- Data ---
    var restaurants = {json.dumps(data_list)};
    var boroughCenters = {json.dumps(borough_centers)};
    var allBoroughs = {json.dumps(all_borough_names)};
    var dataBounds = {json.dumps(data_bounds)};
    
    // --- State ---
    var activePrices = [1, 2, 3, 4];
    
    // --- Map Init ---
    var map = L.map('map', {{preferCanvas: true, zoomControl: false}}).setView([51.5074, -0.1278], 12);
    
    // Move zoom control to top right
    L.control.zoom({{ position: 'topright' }}).addTo(map);

    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 20
    }}).addTo(map);

    // Ensure the initial view includes all points (important when data contains areas outside central London)
    try {{
        map.fitBounds(dataBounds, {{ padding: [30, 30] }});
    }} catch (e) {{
        // Fallback to default London view if bounds are invalid
    }}

    var markersLayer = L.layerGroup().addTo(map);

    // --- Colors ---
    // A more professional, muted palette
    var colors = [
        "#e63946", "#2a9d8f", "#e9c46a", "#f4a261", "#264653", 
        "#8d99ae", "#ef476f", "#06d6a0", "#118ab2", "#073b4c",
        "#9b5de5", "#f15bb5", "#fee440", "#00bbf9", "#00f5d4",
        "#606c38", "#283618", "#dda15e", "#bc6c25", "#333333"
    ];
    
    // Fixed colors for key cuisines to ensure consistency
    var fixedColors = {{
        "Pub": "#d62828",       // Red
        "British": "#003049",   // Dark Blue
        "Italian": "#2a9d8f",   // Teal
        "Indian": "#e9c46a",    // Yellow
        "Chinese": "#f4a261",   // Orange
        "Japanese": "#9b5de5",  // Purple
        "French": "#00bbf9",    // Light Blue
        "American": "#333333",  // Dark Grey
        "Cafe": "#bc6c25",      // Brown
        "Coffee": "#bc6c25",    // Brown
        "Pizza": "#e76f51",     // Burnt Orange
        "Burger": "#8d99ae",    // Grey Blue
        "Thai": "#06d6a0",      // Green
        "Turkish": "#ef476f",   // Pink
        "Middle Eastern": "#dda15e" // Tan
    }};
    
    var cuisineColors = {{}};
    var uniqueCuisines = [...new Set(restaurants.map(r => r.cuisine_group))].sort();
    // Populate borough dropdown from the GeoJSON list (all boroughs),
    // but fall back to restaurant-derived boroughs if GeoJSON load failed.
    var uniqueBoroughs = (allBoroughs && allBoroughs.length)
        ? [...allBoroughs]
        : [...new Set(restaurants.map(r => r.borough))].sort();

    // Pin key cuisines to the top so they're always visible in the dropdown/legend
    var cuisinePriority = {{ "Pub": 0, "British": 1 }};
    uniqueCuisines.sort((a, b) => {{
        var pa = (a in cuisinePriority) ? cuisinePriority[a] : 999;
        var pb = (b in cuisinePriority) ? cuisinePriority[b] : 999;
        if (pa !== pb) return pa - pb;
        return a.localeCompare(b);
    }});
    
    if (uniqueCuisines.includes("Other")) {{
        uniqueCuisines = uniqueCuisines.filter(c => c !== "Other");
        uniqueCuisines.push("Other");
    }}
    
    uniqueCuisines.forEach((c, i) => {{
        if (fixedColors[c]) {{
            cuisineColors[c] = fixedColors[c];
        }} else {{
            cuisineColors[c] = colors[i % colors.length];
        }}
    }});

    // --- Populate UI ---
    var select = document.getElementById('cuisineSelect');
    uniqueCuisines.forEach(c => {{
        var opt = document.createElement('option');
        opt.value = c;
        opt.innerHTML = c;
        select.appendChild(opt);
    }});

    var boroughSelect = document.getElementById('boroughSelect');
    uniqueBoroughs.forEach(b => {{
        if (b === "Unknown") return;
        var opt = document.createElement('option');
        opt.value = b;
        opt.innerHTML = b;
        boroughSelect.appendChild(opt);
    }});

    var legend = document.getElementById('legend');
    uniqueCuisines.forEach(c => {{
        var item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = `<div class="color-dot" style="background:${{cuisineColors[c]}}"></div>${{c}}`;
        item.onclick = () => {{
            select.value = c;
            updateMap();
        }};
        legend.appendChild(item);
    }});

    // --- Logic ---
    function togglePrice(level, btn) {{
        if (activePrices.includes(level)) {{
            activePrices = activePrices.filter(p => p !== level);
            btn.classList.remove('active');
        }} else {{
            activePrices.push(level);
            btn.classList.add('active');
        }}
        updateMap();
    }}

    function toggleSidebar() {{
        document.getElementById('sidebar').classList.toggle('open');
    }}

    function toggleFullscreen() {{
        if (!document.fullscreenElement) {{
            document.documentElement.requestFullscreen().catch(err => {{
                console.log(`Error attempting to enable fullscreen: ${{err.message}}`);
            }});
        }} else {{
            if (document.exitFullscreen) {{
                document.exitFullscreen();
            }}
        }}
    }}

    function toggleHelp() {{
        const modal = document.getElementById('helpModal');
        modal.style.display = modal.style.display === 'flex' ? 'none' : 'flex';
    }}

    function onBoroughChange() {{
        var b = document.getElementById('boroughSelect').value;
        if (b !== "All" && boroughCenters[b]) {{
            // Fly to borough centroid
            // Zoom level 13 is usually good for a borough view
            map.flyTo(boroughCenters[b], 13, {{
                animate: true,
                duration: 1.5
            }});
        }} else if (b === "All") {{
            // Reset to London view
            map.flyTo([51.5074, -0.1278], 11, {{
                animate: true,
                duration: 1.5
            }});
        }}
        updateMap();
    }}

    // Helper to get color for hype score
    function getHypeColor(score) {{
        // Gradient from Yellow (0.0) to Green (1.0+)
        // Simple thresholding for now
        if (score >= 1.0) return "#006400"; // Dark Green
        if (score >= 0.5) return "#2a9d8f"; // Teal
        if (score >= 0.2) return "#e9c46a"; // Yellow-Orange
        return "#f4a261"; // Orange
    }}

    function updateMap() {{
        var selectedCuisine = document.getElementById('cuisineSelect').value;
        var selectedBorough = document.getElementById('boroughSelect').value;
        var minRating = parseFloat(document.getElementById('ratingRange').value);
        var minReviews = parseInt(document.getElementById('reviewRange').value);
        var searchText = document.getElementById('searchInput').value.toLowerCase();
        var showUnderrated = document.getElementById('underratedToggle').checked;
        var onlyIndependents = document.getElementById('independentToggle').checked;
        
        document.getElementById('ratingVal').innerText = minRating.toFixed(1);
        document.getElementById('reviewVal').innerText = minReviews;
        
        markersLayer.clearLayers();
        
        var count = 0;
        
        restaurants.forEach(r => {{
            // Filters
            if (onlyIndependents) {{
                // is_chain: 1 => chain, 0 => independent
                if (r.is_chain === 1) return;
            }}

            if (showUnderrated) {{
                // If toggle is ON, only show positive hype residuals
                if (r.hype_residual <= 0.1) return;
            }}

            if (selectedCuisine !== "All" && r.cuisine_group !== selectedCuisine) return;
            if (selectedBorough !== "All" && r.borough !== selectedBorough) return;
            if (r.rating < minRating) return;
            if (r.reviews < minReviews) return;
            if (!activePrices.includes(r.price)) return;
            if (searchText && !r.name.toLowerCase().includes(searchText)) return;
            
            count++;
            
            var color;
            var radius = 6;
            
            if (showUnderrated) {{
                color = getHypeColor(r.hype_residual);
                // Make highly underrated spots slightly larger
                if (r.hype_residual > 0.5) radius = 8;
            }} else {{
                color = cuisineColors[r.cuisine_group] || "#333";
            }}
            
            var marker = L.circleMarker([r.lat, r.lon], {{
                radius: radius,
                fillColor: color,
                color: "white",
                weight: 1,
                opacity: 1,
                fillOpacity: 0.85
            }});
            
            var priceStr = r.price > 0 ? '£'.repeat(r.price) : '?';
            var hypeBadge = "";
            if (r.hype_residual > 0.2) {{
                hypeBadge = `<span class="underrated-badge" title="Actual rating is ${{r.hype_residual}} higher than expected">Underrated +${{r.hype_residual}}</span>`;
            }}
            
            var popupContent = `
                <div class="popup-header" style="${{showUnderrated ? 'background:'+color : ''}}">
                    <h3 class="popup-title">${{r.name}}</h3>
                </div>
                <div class="popup-body">
                    <div class="popup-meta">
                        <span>${{r.cuisine}}</span>
                        <span>${{priceStr}}</span>
                    </div>
                    <div class="popup-rating">
                        <span class="star-icon">★</span> ${{r.rating}} 
                        <span style="color:#888; font-weight:400; font-size:12px; margin-left:4px;">(${{r.reviews}} reviews)</span>
                        ${{hypeBadge}}
                    </div>
                    <p style="margin: 8px 0 0 0; color: #555;">${{r.vicinity}}</p>
                    <a href="https://www.google.com/maps/search/?api=1&query=${{r.lat}},${{r.lon}}" target="_blank" class="popup-link">
                        Get Directions
                    </a>
                </div>
            `;
            
            marker.bindPopup(popupContent);
            markersLayer.addLayer(marker);
        }});
        
        document.getElementById('stats').innerHTML = `<strong>${{count.toLocaleString()}}</strong> restaurants visible`;
    }}
    
    // Initial Load
    updateMap();
    
    // Show help modal on startup
    setTimeout(toggleHelp, 500); // Small delay for smooth entrance

</script>

</body>
</html>
"""

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Done! Map saved to {OUTPUT_FILE}")
