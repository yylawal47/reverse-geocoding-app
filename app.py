import streamlit as st
import pandas as pd
import pydeck as pdk
from io import BytesIO
from datetime import datetime
import requests

# ==============================
# Utility functions
# ==============================

def load_file(uploaded_file):
    filename = uploaded_file.name
    if filename.endswith('.xlsx'):
        xls = pd.ExcelFile(uploaded_file)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
    elif filename.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        raise ValueError("Unsupported file type")
    return df

def find_coordinate_columns(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinate_values(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return True
        return False
    except Exception:
        return False

def reverse_geocode_osm(lat, lon):
    """Reverse geocode using OpenStreetMap Nominatim"""
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {'User-Agent': 'streamlit-geocoder-app'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            addr = data.get('address', {})
            return {
                'state': addr.get('state', 'Unknown'),
                'city': addr.get('city', addr.get('town', addr.get('village', ''))),
                'full_address': data.get('display_name', '')
            }
        return {'state': 'Unknown', 'city': '', 'full_address': ''}
    except Exception:
        return {'state': 'Unknown', 'city': '', 'full_address': ''}

def generate_unique_filename(prefix="geocoded"):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# Streamlit App
# ==============================

st.set_page_config(
    page_title="🗺️ Geocoding & Map Dashboard",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Geocoding & Map Dashboard")

# File upload
uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["xlsx", "csv"])
if uploaded_file:
    df = load_file(uploaded_file)
    st.subheader("📊 File Preview")
    st.dataframe(df.head(5))

    # Auto-detect lat/lon
    lat_col, lon_col = find_coordinate_columns(df)
    if not lat_col or not lon_col:
        st.error("Could not detect latitude/longitude columns automatically. Please ensure column names contain 'lat' and 'lon'.")
        st.stop()
    else:
        st.info(f"Detected Latitude: {lat_col}, Longitude: {lon_col}")

    # Filter valid coordinates
    df_valid = df[df.apply(lambda x: validate_coordinate_values(x[lat_col], x[lon_col]), axis=1)]
    if df_valid.empty:
        st.error("No valid coordinate pairs found.")
        st.stop()

    # ==============================
    # Reverse Geocoding Option
    # ==============================
    run_geocode = st.checkbox("Run Reverse Geocoding (to get state and city)", value=False)
    if run_geocode:
        st.info("Running reverse geocoding on valid coordinates...")
        states = []
        cities = []
        full_addresses = []
        for i, row in df_valid.iterrows():
            result = reverse_geocode_osm(row[lat_col], row[lon_col])
            states.append(result['state'])
            cities.append(result['city'])
            full_addresses.append(result['full_address'])
        df_valid['State'] = states
        df_valid['City'] = cities
        df_valid['Full Address'] = full_addresses
        st.success("✅ Reverse geocoding complete!")

        # Summary table by state
        if 'State' in df_valid.columns:
            st.subheader("📋 ID Column Distribution by State")
            summary = df_valid.groupby('State')[df_valid.columns[0]].count().reset_index()
            summary.rename(columns={df_valid.columns[0]: 'Count'}, inplace=True)
            st.dataframe(summary)
            # Export summary
            summary_buffer = BytesIO()
            summary.to_excel(summary_buffer, index=False, sheet_name="Summary")
            summary_buffer.seek(0)
            st.download_button("📥 Download Summary as Excel", summary_buffer, file_name=f"{generate_unique_filename('summary')}.xlsx")

    # ==============================
    # Map View
    # ==============================
    show_map = st.checkbox("Show Map View", value=True)
    if show_map:
        st.subheader("📍 Map View")
        st.markdown("Hover over points to see full row data.")

        map_df = df_valid.copy()
        hover_cols = df_valid.columns.tolist()
        map_df['hover'] = map_df.apply(lambda x: '<br>'.join([f"{col}: {x[col]}" for col in hover_cols]), axis=1)

        st.pydeck_chart(pdk.Deck(
            map_style='mapbox://styles/mapbox/streets-v12',
            initial_view_state=pdk.ViewState(
                latitude=map_df[lat_col].mean(),
                longitude=map_df[lon_col].mean(),
                zoom=10,
                pitch=0
            ),
            layers=[
                pdk.Layer(
                    'IconLayer',
                    data=map_df,
                    get_icon={
                        "url": "https://img.icons8.com/emoji/48/tanker-truck.png",
                        "width": 128,
                        "height": 128,
                        "anchor": [64, 128]
                    },
                    get_size=4,
                    size_scale=15,
                    get_position=[lon_col, lat_col],
                    pickable=True
                )
            ],
            tooltip={"html": "{hover}", "style": {"color": "white"}}
        ))

    # ==============================
    # Export geocoded/processed data
    # ==============================
# ==============================
# Export geocoded/processed data
# ==============================
if uploaded_file:
    ...
    # after df_valid or df_full is ready
    if run_geocode:
        st.subheader("📤 Export Data")

        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df_valid.to_excel(writer, index=False, sheet_name="Geocoded Data")
        excel_buffer.seek(0)
        
        st.download_button(
            "📥 Download Geocoded Data as Excel",
            excel_buffer,
            file_name=f"{generate_unique_filename()}.xlsx"
        )

        st.download_button(
            "📥 Download Geocoded Data as CSV",
            df_valid.to_csv(index=False),
            file_name=f"{generate_unique_filename()}.csv"
        )
