import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO
import os
from datetime import datetime

# ==============================
# API CLIENT FUNCTIONS (merged from api_client.py)
# ==============================

class BaseGeocodingClient:
    RATE_LIMIT = 1  # seconds between requests

    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError("This method should be implemented by subclasses.")


class LocationIQClient(BaseGeocodingClient):
    RATE_LIMIT = 1  # LocationIQ free tier: 1 request/sec

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
    RATE_LIMIT = 1  # adjust per quota

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
    RATE_LIMIT = 1  # seconds

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
# UTILITY FUNCTIONS (merged from utils.py)
# ==============================

def get_api_key_from_env(provider):
    key_map = {
        "LocationIQ": "LOCATIONIQ_API_KEY",
        "Google Maps": "GOOGLE_MAPS_API_KEY"
    }
    env_var = key_map.get(provider)
    if env_var:
        return os.environ.get(env_var)
    return None


def load_file(uploaded_file):
    filename = uploaded_file.name
    if filename.endswith('.xlsx'):
        xls = pd.ExcelFile(uploaded_file)
        sheets = xls.sheet_names
        selected_sheet = sheets[0]
        df = pd.read_excel(xls, sheet_name=selected_sheet)
    elif filename.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
        sheets = ['Sheet1']
        selected_sheet = 'Sheet1'
    else:
        raise ValueError("Unsupported file type")
    return df, sheets, selected_sheet


def find_coordinate_columns(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col


def validate_coordinates(df, lat_col, lon_col):
    valid = df[lat_col].notna() & df[lon_col].notna()
    return valid.sum()


def initialize_processed_data():
    return {
        'Latitude': [],
        'Longitude': [],
        'Street1': [],
        'Street2': [],
        'City': [],
        'State': [],
        'Postal Code': [],
        'Country': [],
        'Full Address': [],
        'Status': []
    }


def get_error_record():
    return {
        'Street1': '',
        'Street2': '',
        'City': '',
        'State': 'Not Available',
        'Postal Code': '',
        'Country': '',
        'Full Address': '',
        'Status': 'Error'
    }


def get_coordinate_error_record(reason='Invalid'):
    return {
        'Street1': '',
        'Street2': '',
        'City': '',
        'State': 'Not Available',
        'Postal Code': '',
        'Country': '',
        'Full Address': '',
        'Status': reason
    }


def validate_coordinate_values(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return True, 'Valid'
        return False, 'Out of range'
    except Exception:
        return False, 'Invalid'


def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    result_df.insert(0, id_col, df[id_col])
    result_df.insert(1, lat_col, df[lat_col])
    result_df.insert(2, lon_col, df[lon_col])
    result_df.rename(columns={'Status': 'Geocoding Status'}, inplace=True)
    return result_df


def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def calculate_total_processing_time(num_records, rate_limit):
    return num_records * rate_limit


# ==============================
# STREAMLIT APP
# ==============================

# Page config
st.set_page_config(
    page_title="🗺️ Geocoding Dashboard",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS
st.markdown("""
<style>
.main {padding: 2rem;}
.stTabs [data-baseweb="tab-list"] {gap: 2rem;}
.success-box {background-color:#d4edda;border:1px solid #c3e6cb;color:#155724;padding:1rem;border-radius:0.5rem;margin:1rem 0;}
.warning-box {background-color:#fff3cd;border:1px solid #ffeeba;color:#856404;padding:1rem;border-radius:0.5rem;margin:1rem 0;}
.error-box {background-color:#f8d7da;border:1px solid #f5c6cb;color:#721c24;padding:1rem;border-radius:0.5rem;margin:1rem 0;}
.log-box {background-color:#f5f5f5;border:1px solid #ddd;color:#333;padding:1rem;border-radius:0.5rem;font-family:monospace;font-size:0.85rem;max-height:400px;overflow-y:auto;margin:1rem 0;}
</style>
""", unsafe_allow_html=True)

st.title("🗺️ Geocoding & Address Extraction Dashboard")
st.markdown("Convert latitude/longitude coordinates to detailed addresses using LocationIQ, Google Maps, or OpenStreetMap")

# Session state
if "df" not in st.session_state: st.session_state.df = None
if "processed_df" not in st.session_state: st.session_state.processed_df = None
if "logs" not in st.session_state: st.session_state.logs = []
if "api_client" not in st.session_state: st.session_state.api_client = None
if "api_provider" not in st.session_state: st.session_state.api_provider = None

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("🗺️ Select Geocoding Provider",
                                options=["LocationIQ", "Google Maps", "OpenStreetMap (Nominatim)"])
st.session_state.api_provider = api_provider
env_api_key = get_api_key_from_env(api_provider)
if api_provider in ["LocationIQ", "Google Maps"]:
    if env_api_key:
        st.sidebar.success(f"✅ {api_provider} API key loaded from environment")
        api_key = env_api_key
    else:
        api_key = st.sidebar.text_input(f"🔑 Enter your {api_provider} API Key", type="password")
        if not api_key: st.sidebar.warning(f"⚠️ Please provide API key")
else:
    api_key = None
    st.sidebar.info("ℹ️ OpenStreetMap does not require API key")

# Initialize API client
try:
    if api_key or api_provider == "OpenStreetMap (Nominatim)":
        st.session_state.api_client = get_client(api_provider, api_key)
except Exception as e:
    st.sidebar.error(f"❌ Failed to initialize API client: {str(e)}")

# File upload
st.sidebar.header("📤 Upload File")
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV file", type=["xlsx", "csv"])

# ==============================
# Main processing
# ==============================

if uploaded_file:
    try:
        df, sheets, selected_sheet = load_file(uploaded_file)
        st.session_state.df = df
    except Exception as e:
        st.error(f"❌ Error loading file: {str(e)}")
        st.stop()

    st.markdown("### 📊 File Analysis")
    st.write(f"**Total Columns:** {len(df.columns)}")
    st.write(df.columns.tolist())

    lat_col, lon_col = find_coordinate_columns(df)

    col1, col2, col3 = st.columns(3)
    with col1:
        lat_col = st.selectbox("Select Latitude Column", df.columns, index=list(df.columns).index(lat_col) if lat_col else 0)
    with col2:
        lon_col = st.selectbox("Select Longitude Column", df.columns, index=list(df.columns).index(lon_col) if lon_col else 0)
    with col3:
        remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
        id_col = st.selectbox("Select Unique ID Column", remaining_cols)

    st.markdown("### 📋 Data Preview")
    st.dataframe(df[[id_col, lat_col, lon_col]].head(5), use_container_width=True)

    if st.button("🚀 Start Geocoding"):
        if api_provider in ["LocationIQ", "Google Maps"] and not api_key:
            st.error(f"❌ Please enter API key")
            st.stop()
        if not st.session_state.api_client:
            st.error("❌ API client not initialized")
            st.stop()

        valid_coords = validate_coordinates(df, lat_col, lon_col)
        if valid_coords == 0:
            st.error("❌ No valid coordinates found")
            st.stop()
        st.success(f"✅ Found {valid_coords} valid coordinate pairs")
        st.session_state.logs = []
        processed_data = initialize_processed_data()

        log_col, progress_col = st.columns([1, 1])
        with log_col:
            log_placeholder = st.empty()
        with progress_col:
            progress_bar = st.progress(0)
            status_text = st.empty()

        def log_message(msg):
            st.session_state.logs.append(msg)
            log_placeholder.markdown(f'<div class="log-box">{"<br>".join(st.session_state.logs[-20:])}</div>', unsafe_allow_html=True)

        processed_count = error_count = skipped_count = 0
        for idx, (i, row) in enumerate(df.iterrows()):
            lat = row[lat_col]; lon = row[lon_col]
            is_valid, status = validate_coordinate_values(lat, lon)
            if not is_valid:
                err = get_coordinate_error_record(status)
                for k, v in err.items(): processed_data[k].append(v)
                skipped_count += 1
                log_message(f"⏭️ Row {idx + 1} skipped: {status}")
            else:
                result = st.session_state.api_client.reverse_geocode(lat, lon, log_message)
                if result:
                    for k in ['street1','street2','city','state','postal','country','address']:
                        processed_data_key = {'street1':'Street1','street2':'Street2','city':'City','state':'State',
                                              'postal':'Postal Code','country':'Country','address':'Full Address'}[k]
                        processed_data[processed_data_key].append(result[k])
                    processed_data['Latitude'].append(lat); processed_data['Longitude'].append(lon); processed_data['Status'].append('Success')
                    processed_count += 1
                    log_message(f"✅ Row {idx + 1} processed")
                else:
                    err = get_error_record()
                    for k, v in err.items(): processed_data[k].append(v)
                    error_count += 1
                    log_message(f"❌ Row {idx + 1} failed")

            progress_bar.progress((idx+1)/len(df))
            status_text.text(f"Processing {idx+1}/{len(df)} | ✅ {processed_count} | ❌ {error_count} | ⏭️ {skipped_count}")

        result_df = prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col)
        st.session_state.processed_df = result_df
        st.success(f"🎉 Geocoding Complete! ✅ {processed_count} | ❌ {error_count} | ⏭️ {skipped_count}")

        st.dataframe(result_df, use_container_width=True, height=400)
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name="Geocoded Data")
        excel_buffer.seek(0)
        st.download_button("📥 Download as Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("📥 Download as CSV", result_df.to_csv(index=False), file_name=f"{generate_unique_filename()}.csv")

else:
    st.info("👈 Please upload an Excel or CSV file to get started")
