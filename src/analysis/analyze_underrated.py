import argparse
import os

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


def get_args():
    parser = argparse.ArgumentParser(
        description="Compute hype-adjusted ratings (hype_residual) for restaurants"
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=os.path.join("data", "raw"),
        help="Input directory containing raw CSVs",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=os.path.join("data", "processed"),
        help="Output directory for analyzed data",
    )
    parser.add_argument("--city-name", type=str, default="london", help="City name")
    parser.add_argument(
        "--min-reviews",
        type=int,
        default=50,
        help="Minimum review count threshold for stable hype_residual",
    )
    return parser.parse_known_args()[0]


def _types_to_set(value) -> set[str]:
    if pd.isna(value):
        return set()
    s = str(value)
    s = s.replace("[", "").replace("]", "")
    s = s.replace("\"", "").replace("'", "")
    return {t.strip() for t in s.split(",") if t.strip()}


def main() -> int:
    args = get_args()

    details_path = os.path.join(args.input_dir, f"{args.city_name}_restaurant_details.csv")
    basic_path = os.path.join(args.input_dir, f"{args.city_name}_restaurants.csv")

    if not os.path.exists(details_path):
        sample_details = os.path.join("data", "sample", "london_restaurant_details.csv")
        if os.path.exists(sample_details):
            print(f"Warning: {details_path} not found. Using sample: {sample_details}")
            details_path = sample_details
        else:
            print(f"Error: Could not find details CSV at {details_path} or sample data.")
            return 1

    df_det = pd.read_csv(details_path)

    # Normalize the restaurant name column for downstream visualization.
    # Some sample/generated datasets may contain name_left/name_right from merges.
    if "name" not in df_det.columns:
        for candidate in ("name_left", "name_right", "restaurant_name", "title"):
            if candidate in df_det.columns:
                df_det["name"] = df_det[candidate]
                break
        else:
            df_det["name"] = ""

    if os.path.exists(basic_path):
        df_basic = pd.read_csv(basic_path)
        if "place_id" in df_basic.columns and "grid_id" in df_basic.columns:
            df = df_det.merge(df_basic[["place_id", "grid_id"]], on="place_id", how="left")
        else:
            df = df_det.copy()
    else:
        df = df_det.copy()

    # --- Feature engineering ---
    df["rating"] = pd.to_numeric(df.get("rating"), errors="coerce")
    df["user_ratings_total"] = pd.to_numeric(
        df.get("user_ratings_total"), errors="coerce"
    ).fillna(0)
    df["log_reviews"] = np.log1p(df["user_ratings_total"].astype(float))
    df["price_level"] = pd.to_numeric(df.get("price_level"), errors="coerce")

    # cuisine
    cuisine_series = df.get("cuisine_detected_ext")
    if cuisine_series is None:
        cuisine_series = df.get("cuisine_detected")
    if cuisine_series is None:
        cuisine_series = pd.Series(["unknown"] * len(df))

    df["cuisine"] = (
        cuisine_series.fillna(df.get("cuisine_detected"))
        .fillna("unknown")
        .astype(str)
        .str.lower()
    )

    # brand / chain
    brand = df.get("brand_name")
    if brand is None:
        df["brand_name_clean"] = np.nan
    else:
        df["brand_name_clean"] = brand.astype(str).str.lower().replace("nan", np.nan)
    df["is_chain"] = df["brand_name_clean"].notna().astype(int)

    # type flags (lightweight; used in rating model)
    important_types = [
        "restaurant",
        "cafe",
        "bar",
        "meal_takeaway",
        "meal_delivery",
        "bakery",
        "night_club",
        "store",
    ]
    type_sets = (
        df["types"].apply(_types_to_set)
        if "types" in df.columns
        else pd.Series([set()] * len(df))
    )
    for t in important_types:
        df[f"type_{t}"] = type_sets.apply(lambda st, t=t: int(t in st))

    model_df = df[df["rating"].notna()].copy()
    if model_df.empty:
        print("Error: No rows with a valid rating to model.")
        return 1

    numeric_features = ["log_reviews", "price_level"] + [f"type_{t}" for t in important_types]
    categorical_features = ["cuisine", "grid_id", "business_status"]

    numeric_features = [c for c in numeric_features if c in model_df.columns]
    categorical_features = [c for c in categorical_features if c in model_df.columns]

    X = model_df[numeric_features + categorical_features]
    y = model_df["rating"]

    preprocess = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(steps=[("imputer", SimpleImputer(strategy="median"))]),
                numeric_features,
            ),
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
        ],
        sparse_threshold=0,
    )

    def _rating_transform(y_in):
        y_clamped = np.clip(y_in, 1.01, 4.99)
        y_norm = (y_clamped - 1) / 4.0
        return np.log(y_norm / (1 - y_norm))

    def _rating_inverse_transform(z):
        y_norm = 1 / (1 + np.exp(-z))
        return y_norm * 4.0 + 1.0

    gbr = HistGradientBoostingRegressor(
        max_depth=6,
        learning_rate=0.05,
        max_iter=300,
        random_state=42,
    )

    model = TransformedTargetRegressor(
        regressor=gbr,
        func=_rating_transform,
        inverse_func=_rating_inverse_transform,
    )

    pipe = Pipeline(steps=[("prep", preprocess), ("model", model)])
    pipe.fit(X, y)

    model_df["expected_rating"] = pipe.predict(X)
    model_df["hype_residual"] = model_df["rating"] - model_df["expected_rating"]

    out_df = model_df[model_df["user_ratings_total"] >= int(args.min_reviews)].copy()

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, f"{args.city_name}_hype_adjusted_ratings.csv")
    out_df.to_csv(out_path, index=False)
    print(f"Saved ratings to {out_path} (rows={len(out_df)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
