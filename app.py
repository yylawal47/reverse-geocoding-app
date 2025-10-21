import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO
from datetime import datetime
import pydeck as pdk

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
                if log_callback: log_callback(f"❌ LocationIQ API returned status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ LocationIQ API error: {str(e)}")
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
            if log_callback: log_callback(f"❌ Google Maps API returned status {resp.status_code}")
            return None
        except Exception as e:
            if log_callback: log_callback(f"❌ Google Maps API error: {str(e)}")
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
            if log_callback: log_callback(f"❌ OpenStreetMap API returned status {resp.status_code}")
            return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OpenStreetMap API error: {str(e)}")
            return None


def get_client(provider, api_key=None):
    if provider == "LocationIQ": return LocationIQClient(api_key)
    if provider == "Google Maps": return GoogleMapsClient(api_key)
    if provider == "OpenStreetMap (Nominatim)": return OpenStreetMapClient()
    raise ValueError(f"Unsupported provider: {provider}")


# ==============================
# UTILITY FUNCTIONS
# ==============================

def get_api_key_from_env(provider):
    key_map = {"LocationIQ":"LOCATIONIQ_API_KEY","Google Maps":"GOOGLE_MAPS_API_KEY"}
    return os.environ.get(key_map.get(provider)) if key_map.get(provider) else None

def load_file(uploaded_file):
    if uploaded_file.name.endswith('.xlsx'):
        xls = pd.ExcelFile(uploaded_file)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
    elif uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else: raise ValueError("Unsupported file type")
    return df

def find_coordinate_columns(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinates(df, lat_col, lon_col):
    return df[lat_col].notna() & df[lon_col].notna()

def initialize_processed_data():
    return {k:[] for k in ['Latitude','Longitude','Street1','Street2','City','State','Postal Code','Country','Full Address','Status']}

def get_error_record(): return {'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'','Country':'','Full Address':'','Status':'Error'}
def get_coordinate_error_record(reason='Invalid'): return {'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'','Country':'','Full Address':'','Status':reason}

def validate_coordinate_values(lat, lon):
    try: lat, lon = float(lat), float(lon); return (-90<=lat<=90 and -180<=lon<=180, 'Valid' if -90<=lat<=180 else 'Out of range')
    except: return False,'Invalid'

def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    result_df.insert(0, id_col, df[id_col])
    result_df.insert(1, lat_col, df[lat_col])
    result_df.insert(2, lon_col, df[lon_col])
    result_df.rename(columns={'Status':'Geocoding Status'}, inplace=True)
    return result_df

def generate_unique_filename(): return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")

# Session state
for key in ["df","processed_df","logs","api_client","api_provider"]:
    if key not in st.session_state: st.session_state[key]=None

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Geocoding Provider", ["LocationIQ","Google Maps","OpenStreetMap (Nominatim)"])
st.session_state.api_provider = api_provider
env_api_key = get_api_key_from_env(api_provider)
api_key = env_api_key if env_api_key else (st.sidebar.text_input("API Key", type="password") if api_provider!="OpenStreetMap (Nominatim)" else None)
if api_provider!="OpenStreetMap (Nominatim)" and not api_key: st.sidebar.warning("⚠️ Provide API key")

# Initialize client
if api_key or api_provider=="OpenStreetMap (Nominatim)":
    st.session_state.api_client = get_client(api_provider, api_key)

# Upload file
uploaded_file = st.sidebar.file_uploader("Upload Excel/CSV", type=["xlsx","csv"])

if uploaded_file:
    df = load_file(uploaded_file)
    st.session_state.df = df
    lat_col, lon_col = find_coordinate_columns(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    id_col = remaining_cols[0] if remaining_cols else df.columns[0]

    # Preview & column selection
    col1,col2,col3 = st.columns(3)
    with col1: lat_col = st.selectbox("Latitude Column", df.columns, index=df.columns.get_loc(lat_col) if lat_col else 0)
    with col2: lon_col = st.selectbox("Longitude Column", df.columns, index=df.columns.get_loc(lon_col) if lon_col else 0)
    with col3: id_col = st.selectbox("ID Column", remaining_cols)

    st.dataframe(df[[id_col, lat_col, lon_col]].head(5))

    if st.button("🚀 Start Geocoding"):
        valid_mask = validate_coordinates(df, lat_col, lon_col)
        processed_data = initialize_processed_data()
        logs = []

        def log(msg): logs.append(msg)

        for idx, row in df.iterrows():
            lat, lon = row[lat_col], row[lon_col]
            is_valid, status = validate_coordinate_values(lat, lon)
            if not is_valid:
                err = get_coordinate_error_record(status)
                for k,v in err.items(): processed_data[k].append(v)
            else:
                res = st.session_state.api_client.reverse_geocode(lat, lon, log)
                if res:
                    mapping = {'street1':'Street1','street2':'Street2','city':'City','state':'State','postal':'Postal Code','country':'Country','address':'Full Address'}
                    for k in mapping: processed_data[mapping[k]].append(res[k])
                    processed_data['Latitude'].append(lat); processed_data['Longitude'].append(lon); processed_data['Status'].append('Success')
                else:
                    err=get_error_record()
                    for k,v in err.items(): processed_data[k].append(v)
            time.sleep(st.session_state.api_client.RATE_LIMIT)

        result_df = prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col)
        st.session_state.processed_df = result_df

        # ================= Map View =================
        st.markdown("### 🗺️ Map View")
        filters_col1, filters_col2
