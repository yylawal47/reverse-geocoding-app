import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO
import os
from datetime import datetime

# ==============================
# API CLIENTS
# ==============================

class BaseGeocodingClient:
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError()

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
            if log_callback: log_callback(f"❌ LocationIQ API error: {e}")
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
            else:
                if log_callback:
                    log_callback(f"❌ Google Maps API returned status {resp.status_code}")
            return None
        except Exception as e:
            if log_callback: log_callback(f"❌ Google Maps API error: {e}")
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
            if log_callback: log_callback(f"❌ OpenStreetMap API error: {e}")
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
# UTILS
# ==============================

def get_api_key_from_env(provider):
    key_map = {"LocationIQ": "LOCATIONIQ_API_KEY", "Google Maps": "GOOGLE_MAPS_API_KEY"}
    env_var = key_map.get(provider)
    if env_var: return os.environ.get(env_var)
    return None

def load_file(uploaded_file):
    filename = uploaded_file.name
    if filename.endswith('.xlsx'):
        xls = pd.ExcelFile(uploaded_file)
        sheets = xls.sheet_names
        df = pd.read_excel(xls, sheet_name=sheets[0])
    elif filename.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
        sheets = ['Sheet1']
    else:
        raise ValueError("Unsupported file type")
    return df, sheets, sheets[0]

def find_coordinate_columns(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinates(df, lat_col, lon_col):
    return df[lat_col].notna() & df[lon_col].notna()

def initialize_processed_data():
    return { 'Latitude':[], 'Longitude':[], 'Street1':[], 'Street2':[], 'City':[], 'State':[],
             'Postal Code':[], 'Country':[], 'Full Address':[], 'Status':[] }

def get_error_record(): return { 'Street1':'','Street2':'','City':'','State':'Not Available',
                                 'Postal Code':'','Country':'','Full Address':'','Status':'Error' }

def get_coordinate_error_record(reason='Invalid'): 
    return { 'Street1':'','Street2':'','City':'','State':'Not Available',
             'Postal Code':'','Country':'','Full Address':'','Status':reason }

def validate_coordinate_values(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
        if -90<=lat<=90 and -180<=lon<=180: return True,'Valid'
        return False,'Out of range'
    except:
        return False,'Invalid'

def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    result_df.insert(0, id_col, df[id_col])
    result_df.insert(1, lat_col, df[lat_col])
    result_df.insert(2, lon_col, df[lon_col])
    result_df.rename(columns={'Status':'Geocoding Status'}, inplace=True)
    return result_df

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.main {padding:2rem;}
.success-box{background-color:#d4edda;border:1px solid #c3e6cb;color:#155724;padding:1rem;border-radius:0.5rem;margin:1rem 0;}
.warning-box{background-color:#fff3cd;border:1px solid #ffeeba;color:#856404;padding:1rem;border-radius:0.5rem;margin:1rem 0;}
.error-box{background-color:#f8d7da;border:1px solid #f5c6cb;color:#721c24;padding:1rem;border-radius:0.5rem;margin:1rem 0;}
.log-box{background-color:#f5f5f5;border:1px solid #ddd;color:#333;padding:1rem;border-radius:0.5rem;font-family:monospace;font-size:0.85rem;max-height:400px;overflow-y:auto;margin:1rem 0;}
</style>
""", unsafe_allow_html=True)

st.title("🗺️ Geocoding & Map Dashboard")

# Session state
if "df" not in st.session_state: st.session_state.df=None
if "processed_df" not in st.session_state: st.session_state.processed_df=None
if "logs" not in st.session_state: st.session_state.logs
