from __future__ import annotations

import sys
import argparse
from pathlib import Path
from typing import Optional, Tuple
import math, webbrowser, json
import pandas as pd
import folium
from folium.plugins import MarkerCluster


CSV_NAME = "london_restaurant_details.csv"
DEFAULT_CENTER = (51.5074, -0.1278)  # London
ZOOM_START = 11
MAX_RICH_MARKERS = 8000  # switch to FastMarkerCluster above this (no sampling)


def get_args():
    parser = argparse.ArgumentParser(description="Create interactive map")
    parser.add_argument("--input-file", type=str, default=CSV_NAME, help="Input CSV file name")
    parser.add_argument("--city-name", type=str, default="london", help="City name")
    return parser.parse_known_args()[0]

args = get_args()

def find_csv(filename: str = args.input_file) -> Optional[Path]:
	# Look in standard locations relative to project root
	# Assuming this script is in src/visualization/
	project_root = Path(__file__).resolve().parent.parent.parent
	
	# Also check if filename is a full path
	if Path(filename).exists():
		return Path(filename)

	candidates = [
		project_root / "data" / "processed" / filename,
		project_root / "data" / "raw" / filename,
		project_root / "data" / "sample" / filename,
		project_root / "output" / filename,
		Path(filename),
	]
	for p in candidates:
		if p.exists():
			return p
	return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
	colmap = {
		"latitude": "lat", "Latitude": "lat", "LAT": "lat",
		"y": "lat", "Y": "lat",
		"longitude": "lon", "Longitude": "lon", "lng": "lon", "long": "lon", "Lon": "lon",
		"x": "lon", "X": "lon",
		"name": "name", "restaurant_name": "name", "title": "name",
		"rating": "rating", "ratings": "rating", "stars": "rating", "score": "rating",
		"address": "address", "vicinity": "address", "formatted_address": "address",
		"cuisine": "cuisine", "category": "cuisine", "type": "cuisine",
	}
	rename = {c: colmap[c] for c in df.columns if c in colmap}
	df = df.rename(columns=rename)

	# Ensure required columns exist even if missing in source
	for required in ("lat", "lon"):
		if required not in df.columns:
			df[required] = pd.NA

	# Cast to numeric and drop invalid coordinates
	df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
	df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
	df["rating"] = pd.to_numeric(df["rating"], errors="coerce") if "rating" in df.columns else pd.NA
	# Derive cuisines (original + detected)
	c1 = df["cuisine"] if "cuisine" in df.columns else pd.Series("", index=df.index)
	c2 = df["cuisine_detected"] if "cuisine_detected" in df.columns else pd.Series("", index=df.index)
	raw = c1.fillna("").astype(str)
	alt = c2.fillna("").astype(str)
	merged = raw.where(raw.str.strip().ne(""), alt)
	# Normalize: first token, trimmed, title-case; fallback "Unknown"
	def _norm_cuisine(val: str) -> str:
		val = (val or "").strip()
		if not val: return "Unknown"
		for sep in [",",";","/"]:
			if sep in val: val = val.split(sep)[0]
		return val.strip().title() or "Unknown"
	df["cuisine_norm"] = merged.apply(_norm_cuisine)
	def _bucket(r):
		if pd.isna(r): return "Unknown"
		if r >= 4.5: return ">=4.5"
		if r >= 4.0: return "4.0-4.4"
		if r >= 3.5: return "3.5-3.9"
		return "<3.5"
	df["rating_bucket"] = df["rating"].apply(_bucket)
	return df


def _finite(x) -> bool:
	return isinstance(x, (int, float)) and math.isfinite(x)


def load_data(csv_path: Path) -> pd.DataFrame:
	df = pd.read_csv(csv_path)
	print(f"[INFO] Loaded rows: {len(df)} from {csv_path}")
	df = normalize_columns(df)
	before = len(df)
	df = df.dropna(subset=["lat", "lon"])
	# Ensure finite numeric only
	df = df[_finite_series(df["lat"]) & _finite_series(df["lon"])]
	if df.empty:
		print("[WARN] All rows removed after finite coordinate filtering.")
	# Diagnostics
	if not df.empty:
		print(f"[INFO] lat range: {df['lat'].min()} .. {df['lat'].max()}")
		print(f"[INFO] lon range: {df['lon'].min()} .. {df['lon'].max()}")
	dropped = before - len(df)
	if dropped:
		print(f"[INFO] Dropped rows without coordinates: {dropped}")
	print(f"[INFO] Final rows: {len(df)} | Columns: {list(df.columns)}")
	if not df.empty:
		print(df.head(3).to_string(index=False))
	return df


def _finite_series(s: pd.Series) -> pd.Series:
	return pd.to_numeric(s, errors="coerce").apply(lambda v: isinstance(v, (int,float)) and math.isfinite(v))


def safe_center(df: pd.DataFrame) -> Tuple[float, float]:
	if df.empty or df["lat"].isna().all() or df["lon"].isna().all():
		return DEFAULT_CENTER
	lat, lon = float(df["lat"].median()), float(df["lon"].median())
	if not (_finite(lat) and _finite(lon)):
		print("[WARN] Computed center invalid -> fallback to DEFAULT_CENTER.")
		return DEFAULT_CENTER
	return lat, lon


def icon_color(r: Optional[float]) -> str:
	if pd.isna(r):
		return "gray"
	if r >= 4.5:
		return "darkgreen"
	if r >= 4.0:
		return "green"
	if r >= 3.5:
		return "orange"
	return "red"


def build_popup(row: pd.Series) -> folium.Popup:
	name = str(row.get("name", "") or "")
	rating = row.get("rating", pd.NA)
	addr = str(row.get("address", "") or "")
	cuisine = str(row.get("cuisine", "") or "")

	parts = []
	if name:
		parts.append(f"<b>{name}</b>")
	if pd.notna(rating):
		parts.append(f"Rating: {rating:.1f}")
	if cuisine:
		parts.append(f"Cuisine: {cuisine}")
	if addr:
		parts.append(addr)

	html = "<br/>".join(parts) if parts else "Restaurant"
	return folium.Popup(html, max_width=300)


def _in_ipython() -> bool:
	try:
		from IPython import get_ipython
		return get_ipython() is not None
	except Exception:
		return False


def build_map(df: pd.DataFrame, center: Tuple[float,float]) -> folium.Map:
	m = folium.Map(location=list(center), zoom_start=ZOOM_START, tiles="OpenStreetMap",
	               control_scale=True, width="100%", height="100%", prefer_canvas=True)
	if df.empty:
		return m
	points = []
	for _, row in df.iterrows():
		lat, lon = row["lat"], row["lon"]
		if not _finite(lat) or not _finite(lon):
			continue
		points.append({
			"lat": float(lat),
			"lon": float(lon),
			"name": str(row.get("name","") or ""),
			"rating": float(row["rating"]) if pd.notna(row["rating"]) else None,
			"cuisine": str(row.get("cuisine_norm","") or "Unknown"),
			"rating_bucket": str(row.get("rating_bucket","Unknown"))
		})
	
	# Get all unique cuisines for the filter, sorted alphabetically
	unique_cuisines = sorted(list(set([p["cuisine"] for p in points if p["cuisine"]!="Unknown"])))
	
	js_points = json.dumps(points)
	js_cuisines = json.dumps(unique_cuisines)

	# Inject JS for filtering & cluster creation
	filter_js = f"""
	(function() {{
		const map = {m.get_name()};
		const POINTS = {js_points};
		const CUISINES = {js_cuisines};
		const RATING_BUCKETS = ["All",">=4.5","4.0-4.4","3.5-3.9","<3.5","Unknown"];

		const ctrl = L.control({{position:'topright'}});
		ctrl.onAdd = function() {{
			const d = L.DomUtil.create('div','filter-control');
			d.style.background='rgba(255,255,255,0.95)';
			d.style.padding='8px';
			d.style.border='1px solid #ccc';
			d.style.borderRadius='4px';
			d.style.font='12px Arial';
			d.innerHTML =
				'<div style="font-weight:600;margin-bottom:6px;">Filters</div>' +
				'<label style="display:block;margin-bottom:4px;">Cuisine</label>' +
				'<select id="fcCuisine" style="width:100%;margin-bottom:8px;">' +
				'<option value="All">All</option>' +
				CUISINES.map(c => '<option value="'+c+'">'+c+'</option>').join('') +
				'</select>' +
				'<label style="display:block;margin-bottom:4px;">Rating</label>' +
				'<select id="fcRating" style="width:100%;margin-bottom:8px;">' +
				RATING_BUCKETS.map(r => '<option value="'+r+'">'+r+'</option>').join('') +
				'</select>' +
				'<button id="fcReset" style="width:100%;padding:4px;">Reset</button>' +
				'<div id="fcCount" style="margin-top:6px;font-size:11px;color:#333;"></div>';
			return d;
		}};
		ctrl.addTo(map);

		let cluster = L.markerClusterGroup({{chunkedLoading:true}});
		map.addLayer(cluster);

		function makeMarker(p) {{
			const m = L.marker([p.lat, p.lon], {{customData:p}});
			if (p.name) m.bindTooltip(p.name);
			const popupParts = [];
			if (p.name) popupParts.push('<b>'+p.name+'</b>');
			if (p.rating !== null && !isNaN(p.rating)) popupParts.push('Rating: '+p.rating.toFixed(1));
			if (p.cuisine && p.cuisine !== 'Unknown') popupParts.push('Cuisine: '+p.cuisine);
			if (popupParts.length) m.bindPopup(popupParts.join('<br/>'), {{maxWidth:300}});
			return m;
		}}

		let allMarkers = POINTS.map(makeMarker);

		function applyFilters() {{
			const selC = document.getElementById('fcCuisine').value;
			const selR = document.getElementById('fcRating').value;
			cluster.clearLayers();
			const filtered = allMarkers.filter(m => {{
				const d = m.options.customData;
				const cPass = (selC === 'All') || (d.cuisine === selC);
				const rPass = (selR === 'All') || (d.rating_bucket === selR);
				return cPass && rPass;
			}});
			cluster.addLayers(filtered);
			const countDiv = document.getElementById('fcCount');
			if (countDiv) countDiv.textContent = 'Showing ' + filtered.length + ' / ' + allMarkers.length;
			if (filtered.length) {{
				try {{ map.fitBounds(cluster.getBounds(), {{padding:[20,20]}}); }} catch(e){{}}
			}}
		}}

		function resetFilters() {{
			document.getElementById('fcCuisine').value='All';
			document.getElementById('fcRating').value='All';
			applyFilters();
		}}

		setTimeout(() => {{
			document.getElementById('fcCuisine').addEventListener('change', applyFilters);
			document.getElementById('fcRating').addEventListener('change', applyFilters);
			document.getElementById('fcReset').addEventListener('click', resetFilters);
			applyFilters();
		}},0);
	}})();
	"""
	folium.Element(f"<script>{filter_js}</script>").add_to(m)
	# Initial bounds (full dataset)
	m.fit_bounds([[df["lat"].min(), df["lon"].min()], [df["lat"].max(), df["lon"].max()]])
	return m


def main(return_map: bool = False) -> int:
	csv_path = find_csv()
	if not csv_path:
		print(f"[ERROR] CSV not found. Looked for {CSV_NAME} in script, data, and output folders.")
		return 1

	df = load_data(csv_path)
	center_lat, center_lon = safe_center(df)
	if not (_finite(center_lat) and _finite(center_lon)):
		center_lat, center_lon = DEFAULT_CENTER
	m = build_map(df, (center_lat, center_lon))
	out_dir = Path(__file__).resolve().parent / "output"
	out_dir.mkdir(parents=True, exist_ok=True)
	out_file = out_dir / "london_restaurants_map.html"
	m.save(out_file.as_posix())
	try:
		size_mb = out_file.stat().st_size / (1024 * 1024)
		print(f"[INFO] HTML size: {size_mb:.2f} MB")
	except Exception:
		pass
	print(f"[INFO] Map written: {out_file}  (rows: {len(df)})")

	# In notebooks: display map safely and via IFrame; also open in browser
	if _in_ipython():
		try:
			from IPython.display import display, IFrame
			print("[INFO] Displaying map inline and via IFrame (if inline is sanitized).")
			display(m)  # works in trusted notebooks
			# IFrame circumvents output sanitizer by loading as a separate document
			display(IFrame(src=out_file.as_posix(), width="100%", height="700px"))
		except Exception as e:
			print(f"[WARN] Inline display failed: {e}")
		# Also open in system browser to confirm proper rendering
		try:
			webbrowser.open(out_file.resolve().as_uri())
		except Exception as e:
			print(f"[WARN] Could not open browser: {e}")

	if return_map:
		return m  # type: ignore
	return 0


if __name__ == "__main__":
	if _in_ipython():
		print("[INFO] IPython detected: not calling sys.exit().")
		main()
	else:
		sys.exit(main())
