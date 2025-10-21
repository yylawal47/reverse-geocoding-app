import streamlit as st
import pandas as pd
import requests
import pydeck as pdk
from io import BytesIO
from datetime import datetime
import os

# ==============================
# Geocoding clients
# ==============================
class BaseGeocodingClient:
    RATE_LIMIT = 1

    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError

class LocationIQClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def __init__(self, api_key):
        self.api_key = api_key

    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://us1.locationiq.com/v1/reverse.php?key={self.api_key}&lat={lat}&lon={lon}&format=json"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                address = data.get('address', {})
                return {
                    'Street1': address.get('road', ''),
                    'Street2': address.get('suburb', ''),
                    'City': address.get('city', address.get('town', address.get('village', ''))),
                    'State': address.get('state', ''),
                    'Postal Code': address.get('postcode', ''),
                    'Country': address.get('country', ''),
                    'Full Address': data.get('display_name', '')
                }
            else:
                if log_callback:
                    log_callback(f"LocationIQ API error: status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback:
                log_callback(f"LocationIQ API exception: {e}")
            return None

def get_client(provider, api_key=None):
    if provider == "LocationIQ":
        return LocationIQClient(api_key)
    else:
        return None  # Only LocationIQ implemented for now

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
    except:
        return False

def initialize_processed_data(df):
    columns = df.columns.tolist() + ['Street1','Street2','City','State','Postal Code','Country','Full Address','Geocoding Status']
    return pd.DataFrame(columns=columns)

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# Streamlit App
# ==============================
st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")
st.markdown("Upload a CSV or Excel file with coordinates, optionally geocode addresses, view on map, and see summary by state.")

# ----------------------
# File upload
# ----------------------
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV file", type=["xlsx","csv"])
df = None
if uploaded_file:
    df = load_file(uploaded_file)
    st.subheader("📊 File Preview")
    st.dataframe(df.head(5))
    lat_col, lon_col = find_coordinate_columns(df)
    if not lat_col or not lon_col:
        st.error("Couldn't automatically detect latitude/longitude columns.")
        st.stop()
else:
    st.info("Upload a file to get started")
    st.stop()

# ----------------------
# Optional Geocoding
# ----------------------
st.sidebar.header("⚙️ Geocoding")
geocode_option = st.sidebar.checkbox("Run Geocoding")
if geocode_option:
    api_key = st.sidebar.text_input("Enter LocationIQ API Key", type="password")
    if not api_key:
        st.warning("Provide API key to geocode")
        st.stop()
    client = get_client("LocationIQ", api_key)
    processed_df = initialize_processed_data(df)
    st.info("Running geocoding...")
    progress_bar = st.progress(0)
    for idx, row in df.iterrows():
        lat = row[lat_col]
        lon = row[lon_col]
        if validate_coordinate_values(lat, lon):
            result = client.reverse_geocode(lat, lon)
            if result:
                for k,v in result.items():
                    processed_df.at[idx,k] = v
                processed_df.at[idx,'Geocoding Status'] = "Success"
            else:
                processed_df.at[idx,'Geocoding Status'] = "Failed"
        else:
            processed_df.at[idx,'Geocoding Status'] = "Invalid"
        progress_bar.progress((idx+1)/len(df))
    st.success("🎉 Geocoding complete!")
else:
    processed_df = df.copy()
    processed_df['Geocoding Status'] = "Skipped"

# ----------------------
# Show Map
# ----------------------
st.sidebar.header("🗺️ Map View")
show_map = st.sidebar.checkbox("Show points on map")
if show_map:
    map_df = processed_df.dropna(subset=[lat_col, lon_col]).copy()
    map_df['lat'] = map_df[lat_col].astype(float)
    map_df['lon'] = map_df[lon_col].astype(float)
    map_df['tooltip_text'] = map_df.apply(lambda r: '\n'.join([f"{c}: {r[c]}" for c in map_df.columns]), axis=1)

    st.subheader("📍 Map View")
    st.pydeck_chart(pdk.Deck(
        map_style="mapbox://styles/mapbox/light-v10",
        initial_view_state=pdk.ViewState(
            latitude=map_df['lat'].mean(),
            longitude=map_df['lon'].mean(),
            zoom=6,
            pitch=0
        ),
        layers=[pdk.Layer(
            "ScatterplotLayer",
            data=map_df,
            get_position='[lon, lat]',
            get_radius=5000,
            get_fill_color=[0, 128, 255],
            pickable=True,
            auto_highlight=True
        )],
        tooltip={"text": "{tooltip_text}"}
    ))

# ----------------------
# Summary Table by State
# ----------------------
st.sidebar.header("📋 Summary")
show_summary = st.sidebar.checkbox("Show summary table (ID distribution by State)")
if show_summary and 'State' in processed_df.columns:
    st.subheader("📊 Summary by State")
    id_col_name = processed_df.columns[0]
    summary = processed_df.groupby('State')[id_col_name].count().reset_index()
    summary.columns = ['State','Count']
    st.dataframe(summary, use_container_width=True)
    csv_buffer = summary.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download summary CSV", csv_buffer, file_name=f"summary_{generate_unique_filename()}.csv")

# ----------------------
# Export processed data
# ----------------------
st.subheader("💾 Export Data")
excel_buffer = BytesIO()
with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
    processed_df.to_excel(writer, index=False, sheet_name="Data")
excel_buffer.seek(0)
st.download_button("📥 Download full data as Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
st.download_button("📥 Download full data as CSV", processed_df.to_csv(index=False).encode('utf-8'), file_name=f"{generate_unique_filename()}.csv")
