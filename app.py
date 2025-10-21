import streamlit as st
import pandas as pd
import requests
import os
from io import BytesIO
from datetime import datetime
import pydeck as pdk

# ==============================
# API CLIENTS
# ==============================

class BaseGeocodingClient:
    RATE_LIMIT = 1  # seconds between requests

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
                if log_callback: log_callback(f"❌ LocationIQ status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ LocationIQ error: {str(e)}")
            return None

class OpenStreetMapClient(BaseGeocodingClient):
    RATE_LIMIT = 1

    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        headers = {'User-Agent': 'streamlit-geocoder-app'}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
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
                if log_callback: log_callback(f"❌ OSM status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OSM error: {str(e)}")
            return None

def get_client(provider, api_key=None):
    if provider == "LocationIQ":
        return LocationIQClient(api_key)
    elif provider == "OpenStreetMap (Nominatim)":
        return OpenStreetMapClient()
    else:
        raise ValueError(f"Unsupported provider: {provider}")

# ==============================
# UTILITY FUNCTIONS
# ==============================

def get_api_key_from_env(provider):
    key_map = {"LocationIQ": "LOCATIONIQ_API_KEY"}
    return os.environ.get(key_map.get(provider)) if key_map.get(provider) else None

def load_file(uploaded_file):
    if uploaded_file.name.endswith('.xlsx'):
        df = pd.read_excel(uploaded_file, sheet_name=0)
    elif uploaded_file.name.endswith('.csv'):
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
        lat, lon = float(lat), float(lon)
        return -90 <= lat <= 90 and -180 <= lon <= 180
    except:
        return False

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding Dashboard", layout="wide")
st.title("🗺️ Geocoding & Map Dashboard")

# Sidebar config
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Provider", ["LocationIQ", "OpenStreetMap (Nominatim)"])
env_api_key = get_api_key_from_env(api_provider)
if api_provider == "LocationIQ":
    api_key = env_api_key or st.sidebar.text_input("Enter LocationIQ API Key", type="password")
else:
    api_key = None

try:
    st.session_state.api_client = get_client(api_provider, api_key)
except Exception as e:
    st.sidebar.error(f"API client error: {e}")

uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx", "csv"])
if uploaded_file:
    df = load_file(uploaded_file)
    lat_col, lon_col = find_coordinate_columns(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    id_col = st.sidebar.selectbox("Select ID column", remaining_cols)
    stat_col = st.sidebar.selectbox("Select Statistics column", remaining_cols)

    st.subheader("Data Preview")
    st.dataframe(df.head())

    st.sidebar.header("Filters")
    unique_stats = df[stat_col].dropna().unique().tolist()
    selected_stats = st.sidebar.multiselect("Filter Statistics", unique_stats, default=unique_stats)
    filtered_df = df[df[stat_col].isin(selected_stats)]

    if st.button("🚀 Show Map"):
        filtered_df = filtered_df.dropna(subset=[lat_col, lon_col])
        filtered_df = filtered_df.copy()
        filtered_df['Latitude'] = filtered_df[lat_col].astype(float)
        filtered_df['Longitude'] = filtered_df[lon_col].astype(float)

        # Color mapping
        color_map = {"Stopped":[200,0,0,180],"Moving":[0,200,0,180],"Idle":[255,215,0,180]}
        filtered_df['color'] = filtered_df[stat_col].map(lambda x: color_map.get(x,[128,128,128,180]))

        tooltip_html = "<br>".join([f"<b>{c}:</b> {{{c}}}" for c in filtered_df.columns if c not in ['color','Latitude','Longitude']])

        layer = pdk.Layer(
            "ScatterplotLayer",
            data=filtered_df,
            get_position=["Longitude","Latitude"],
            get_fill_color="color",
            get_radius=200,
            pickable=True
        )

        view_state = pdk.ViewState(
            longitude=filtered_df["Longitude"].mean(),
            latitude=filtered_df["Latitude"].mean(),
            zoom=6,
            pitch=0
        )

        r = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip={"html": tooltip_html, "style":{"backgroundColor":"#F0F0F0","color":"#000","fontSize":12,"padding":10}}
        )
        st.pydeck_chart(r)

        # Export filtered data
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            filtered_df.to_excel(writer, index=False, sheet_name="Filtered Data")
        excel_buffer.seek(0)
        st.download_button("📥 Download Filtered Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("📥 Download Filtered CSV", filtered_df.to_csv(index=False), file_name=f"{generate_unique_filename()}.csv")

else:
    st.info("👈 Upload a file to start")
