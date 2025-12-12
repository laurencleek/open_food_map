import json
import re
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_module_from_path(module_name: str, path: Path):
    spec = spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_infer_cuisine_chequers_is_pub():
    root = _project_root()
    collect_data_path = root / "src" / "data_collection" / "collect_data.py"
    mod = _load_module_from_path("collect_data", collect_data_path)

    cuisine, source = mod.infer_cuisine(
        name="The Chequers",
        types=[],
        editorial=None,
        reviews=[],
    )
    assert cuisine == "pub"
    assert source == "name"


def test_extended_infer_cuisine_chequers_is_pub():
    root = _project_root()
    collect_data_path = root / "src" / "data_collection" / "collect_data.py"
    mod = _load_module_from_path("collect_data", collect_data_path)

    cuisine, source, *_ = mod.extended_infer_cuisine(
        name="The Chequers",
        types=[],
        editorial=None,
        reviews=[],
        website=None,
    )
    assert cuisine == "pub"
    assert source in {"name", "mixed"}


def test_interactive_map_injects_all_boroughs(tmp_path: Path):
    root = _project_root()
    script_path = root / "src" / "visualization" / "interactive_cuisine_map.py"
    boroughs_path = root / "data" / "raw" / "london_boroughs.geojson"

    # Minimal input CSV required by the visualization script.
    city = "testcity"
    input_csv = tmp_path / f"{city}_hype_adjusted_ratings.csv"
    input_csv.write_text(
        "lat,lon,name,cuisine,rating,user_ratings_total,price_level,vicinity,hype_residual,is_chain\n"
        "51.5155,-0.0922,The Chequers,pub,4.2,120,2,City of London,0.1,0\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(tmp_path),
            "--output-dir",
            str(tmp_path),
            "--city-name",
            city,
            "--boroughs-file",
            str(boroughs_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Script failed: {proc.stdout}\n{proc.stderr}"

    output_html = tmp_path / f"{city}_restaurants_interactive.html"
    assert output_html.exists(), "Expected HTML output file to be created"

    html = output_html.read_text(encoding="utf-8")
    m = re.search(r"var allBoroughs = (\[.*?\]);", html, flags=re.DOTALL)
    assert m, "Expected 'var allBoroughs = [...]' to be present in HTML"
    boroughs_in_html = json.loads(m.group(1))
    assert isinstance(boroughs_in_html, list)
    assert len(boroughs_in_html) > 0

    geo = json.loads(boroughs_path.read_text(encoding="utf-8"))
    expected = sorted(
        {
            (f.get("properties") or {}).get("name")
            for f in (geo.get("features") or [])
            if (f.get("properties") or {}).get("name")
        }
        - {"Unknown"}
    )
    assert boroughs_in_html == expected