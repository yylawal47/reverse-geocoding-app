import streamlit as st
import pandas as pd
import requests
from time import sleep
import io

st.set_page_config(page_title="Reverse Geocoding App", layout="wide")

st.title("🌍 Reverse Geocoding App")
st.write("Upload an Excel file with latitude and longitude columns to get readable location names.")

# === File uploader ===
uploaded_file = st.file_uploader("📂 Upload your Excel file", type=["xlsx"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    st.success(f"File uploaded successfully! Total rows: {len(df)}")

    # Detect date column
    date_col = None
    for col in df.columns:
        if "date" in col.lower() or "time" in col.lower():
            date_col = col
            break

    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce').dt.strftime('%m/%d/%Y')

    # Detect lat/lon columns
    lat_col = None
    lon_col = None
    for col in df.columns:
        if "lat" in col.lower():
            lat_col = col
        if "lon" in col.lower():
            lon_col = col

    if lat_col and lon_col:
        df = df[(df[lat_col].between(4, 14)) & (df[lon_col].between(2, 15))]
        st.info(f"Filtered rows to Nigerian coordinates. Remaining: {len(df)}")

        # Define reverse geocoding function
        def reverse_geocode(lat, lon):
            try:
                url = f'https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}'
                r = requests.get(url, timeout=10, headers={'User-Agent': 'GeoTracker/1.0'})
                if r.status_code == 200:
                    data = r.json()
                    return data.get('display_name', 'Unknown')
            except Exception:
                pass
            return "Unknown"

        # Run geocoding
        st.write("🔍 Starting reverse geocoding... please wait ⏳")
        locations = []
        progress = st.progress(0)

        for i, row in df.iterrows():
            lat = row[lat_col]
            lon = row[lon_col]
            if pd.notnull(lat) and pd.notnull(lon):
                address = reverse_geocode(lat, lon)
                locations.append(address)
            else:
                locations.append("Invalid Coordinates")

            if len(df) > 0:
                progress.progress(int((i + 1) / len(df) * 100))
            sleep(1)  # Respect API rate limit

        df['Location'] = locations
        st.success("✅ Reverse geocoding completed!")

        # Download processed file
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        st.download_button(
            label="📥 Download Excel File",
            data=output,
            file_name="geocoded_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.dataframe(df.head(10))
    else:
        st.error("Could not find latitude or longitude columns in your file.")
else:
    st.info("Please upload an Excel file to start.")
