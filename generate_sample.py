import pandas as pd
import numpy as np
import random
import string

# Load existing sample
file_path = r"data/sample/london_restaurant_details.csv"
df = pd.read_csv(file_path)

# Cuisines to inject
cuisines = [
    "Ethiopian", "Peruvian", "Vietnamese", "Lebanese", "Korean", 
    "Japanese", "Brazilian", "Turkish", "Thai", "Greek", 
    "Spanish", "French", "Italian", "Indian", "Chinese",
    "Mexican", "Caribbean", "Polish", "Malaysian", "Argentinian"
]

new_rows = []
base_lat = 51.512
base_lon = -0.090

for i in range(100):
    cuisine = random.choice(cuisines)
    
    # Random location in City of London (approx)
    lat = base_lat + random.uniform(-0.01, 0.01)
    lon = base_lon + random.uniform(-0.02, 0.02)
    
    row = {
        "place_id": "sample_" + "".join(random.choices(string.ascii_letters + string.digits, k=10)),
        "name": f"The {cuisine} Spot {i}",
        "types": "restaurant,food,point_of_interest,establishment",
        "rating": round(random.uniform(3.5, 5.0), 1),
        "user_ratings_total": random.randint(50, 2000),
        "price_level": random.randint(1, 4),
        "lat": lat,
        "lon": lon,
        "vicinity": "City of London, London",
        "business_status": "OPERATIONAL",
        "editorial_summary": f"A popular {cuisine} restaurant in the heart of the city.",
        "website": "http://example.com",
        "international_phone_number": "+44 20 1234 5678",
        "cuisine_detected": cuisine.lower(),
        "cuisine_source": "manual",
        "top_review_language": "en",
        "top_language_share": 1.0,
        "n_reviews_fetched": 5,
        "review_language_counts_json": '{"en": 5}',
        "cuisine_detected_ext": cuisine.lower(),
        "cuisine_source_ext": "manual",
        "brand_name": np.nan,
        "brand_category": np.nan,
        "brand_source": np.nan
    }
    new_rows.append(row)

# Append
df_new = pd.DataFrame(new_rows)
df_combined = pd.concat([df, df_new], ignore_index=True)

# Save back
df_combined.to_csv(file_path, index=False)
print(f"Added {len(new_rows)} rows. Total rows: {len(df_combined)}")
