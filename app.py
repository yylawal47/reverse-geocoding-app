import streamlit as st
import pandas as pd
import requests
from io import BytesIO
from datetime import datetime
import pydeck as pdk
import os

# ==============================
# API CLIENT FUNCTIONS
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
                    'street1': address.get('road', ''),
                    'street2': address.get('suburb', ''),
                    'city': address.get('city', address.get('town', address.get('village', ''))),
                    'state': address.get('state', ''),
                    'postal': address.get('postcode', ''),
                    'country': address.get('country', ''),
                    'address': data.get('display_name', '')
                }
            else:
                if log_callback:
                    log_callback(f"❌ LocationIQ API returned status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback:
                log_callback(f"❌ LocationIQ API error: {str(e)}")
            return None

class GoogleMapsClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def __init__(self, api_key):
        self.api_key = api_key

    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={self.api_key}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'OK' and data.get('results'):
                    result = data['results'][0]
                    components = {c['types'][0]: c['long_name'] for c in result['address_components']}
                    return {
                        'street1': components.get('route', ''),
                        'street2': components.get('sublocality_level_1', ''),
                        'city': components.get('locality', ''),
                        'state': components.get('administrative_area_level_1', ''),
                        'postal': components.get('postal_code', ''),
                        'country': components.get('country', ''),
                        'address': result.get('formatted_address', '')
                    }
                return None
            else:
                if log_callback:
                    log_callback(f"❌ Google Maps API returned status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback:
                log_callback(f"❌ Google Maps API error: {str(e)}")
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
                    'street1': address.get('road', ''),
                    'street2': address.get('suburb', ''),
                    'city': address.get('city', address.get('town', address.get('village', ''))),
                    'state': address.get('state', ''),
                    'postal': address.get('postcode', ''),
                    'country': address.get('country', ''),
                    'address': data.get('display_name', '')
                }
            else:
                if log_callback:
                    log_callback(f"❌ OpenStreetMap API returned status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback:
                log_callback(f"❌ OpenStreetMap API error: {str(e)}")
            return None

def get_client(provider, api_key=None):
    if provider == "LocationIQ":
        return LocationIQClient(api_key)
    elif provider == "Google Maps":
        return GoogleMapsClient(api_key)
    elif provider == "OpenStreetMap (Nominatim)":
        return OpenStreetMapClient()
    else:
        raise ValueError(f"Unsupported provider: {provider}")

# ==============================
# UTILITY FUNCTIONS
# ==============================

def get_api_key_from_env(provider):
    key_map = {
        "LocationIQ": "LOCATIONIQ_API_KEY",
        "Google Maps": "GOOGLE_MAPS_API_KEY"
    }
    env_var = key_map.get(provider)
    return os.environ.get(env_var) if env_var else None

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

def detect_unique_id(df):
    candidates = ['id','ID','Id','Unnamed: 0']
    for c in candidates:
        if c in df.columns:
            return c
    return df.columns[0]

def validate_coordinate_values(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        return -90 <= lat <= 90 and -180 <= lon <= 180
    except:
        return False

def initialize_processed_data(df):
    return df.copy()  # keep all original columns
def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")
st.title("🗺️ Geocoding & Map Dashboard")

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Geocoding Provider",
                                ["LocationIQ","Google Maps","OpenStreetMap (Nominatim)"])
env_api_key = get_api_key_from_env(api_provider)
api_key = None
if api_provider in ["LocationIQ","Google Maps"]:
    api_key = env_api_key or st.sidebar.text_input(f"{api_provider} API Key", type="password")
if api_provider == "OpenStreetMap (Nominatim)":
    st.sidebar.info("OpenStreetMap does not require API key")

# Initialize API client
api_client = get_client(api_provider, api_key) if (api_key or api_provider=="OpenStreetMap (Nominatim)") else None

# File upload
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx","csv"])
if uploaded_file:
    df = load_file(uploaded_file)
    lat_col, lon_col = find_coordinate_columns(df)
    if not lat_col or not lon_col:
        st.error("Could not detect latitude/longitude columns.")
        st.stop()
    id_col = detect_unique_id(df)

    st.subheader("📊 File Preview")
    st.dataframe(df.head(5))

    # Option: View map without geocoding
    st.subheader("🗺️ Map View")
    show_map = st.checkbox("Show points on map using current coordinates")
    if show_map:
        map_df = df.dropna(subset=[lat_col, lon_col])
        map_df['lat'] = map_df[lat_col].astype(float)
        map_df['lon'] = map_df[lon_col].astype(float)
        st.pydeck_chart(pdk.Deck(
            map_style="mapbox://styles/mapbox/light-v10",
            initial_view_state=pdk.ViewState(
                latitude=map_df['lat'].mean(),
                longitude=map_df['lon'].mean(),
                zoom=6,
                pitch=0,
            ),
            layers=[pdk.Layer(
                "ScatterplotLayer",
                data=map_df,
                get_position='[lon, lat]',
                get_radius=5000,
                get_fill_color=[0, 128, 255],
                pickable=True,
                auto_highlight=True,
            )],
            tooltip={"text": str(df.columns.tolist())}
        ))

    # Option: Run geocoding
    st.subheader("🚀 Geocode Coordinates")
    if st.button("Start Geocoding") and api_client:
        processed_df = initialize_processed_data(df)
        for idx, row in df.iterrows():
            lat, lon = row[lat_col], row[lon_col]
            if validate_coordinate_values(lat, lon):
                result = api_client.reverse_geocode(lat, lon)
                if result:
                    for k,v in result.items():
                        processed_df.loc[idx, k] = v
                else:
                    processed_df.loc[idx, ['street1','street2','city','state','postal','country','address']] = [None]*7
            else:
                processed_df.loc[idx, ['street1','street2','city','state','postal','country','address']] = [None]*7
        st.success("🎉 Geocoding Complete!")
        st.dataframe(processed_df.head())

        # Export processed data
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            processed_df.to_excel(writer, index=False)
        excel_buffer.seek(0)
        st.download_button("📥 Download Geocoded Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("📥 Download Geocoded CSV", processed_df.to_csv(index=False), file_name=f"{generate_unique_filename()}.csv")

        # Summary by state
        if 'state' in processed_df.columns:
            st.subheader("📋 Summary by State")
            summary_df = processed_df.groupby('state')[id_col].count().reset_index().rename(columns={id_col:'Count'})
            st.dataframe(summary_df)
            summary_buffer = BytesIO()
            with pd.ExcelWriter(summary_buffer, engine='openpyxl') as writer:
                summary_df.to_excel(writer, index=False)
            summary_buffer.seek(0)
            st.download_button("📥 Download Summary Excel", summary_buffer, file_name=f"summary_by_state_{generate_unique_filename()}.xlsx")
            st.download_button("📥 Download Summary CSV", summary_df.to_csv(index=False), file_name=f"summary_by_state_{generate_unique_filename()}.csv")
