import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO
import os
from datetime import datetime
import pydeck as pdk

# ==============================
# API CLIENT FUNCTIONS
# ==============================

class BaseGeocodingClient:
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError("This method should be implemented by subclasses.")

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
                return None
            else:
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
            else:
                if log_callback: log_callback(f"❌ OpenStreetMap API returned status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OpenStreetMap API error: {str(e)}")
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
    key_map = {"LocationIQ": "LOCATIONIQ_API_KEY", "Google Maps": "GOOGLE_MAPS_API_KEY"}
    env_var = key_map.get(provider)
    return os.environ.get(env_var) if env_var else None

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
    return df, sheets

def find_coordinate_columns(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinates(df, lat_col, lon_col):
    valid = df[lat_col].notna() & df[lon_col].notna()
    return valid.sum()

def initialize_processed_data():
    return {'Latitude': [], 'Longitude': [], 'Street1': [], 'Street2': [], 'City': [], 'State': [], 'Postal Code': [], 'Country': [], 'Full Address': [], 'Status': []}

def get_error_record():
    return {'Street1': '', 'Street2': '', 'City': '', 'State': 'Not Available', 'Postal Code': '', 'Country': '', 'Full Address': '', 'Status': 'Error'}

def get_coordinate_error_record(reason='Invalid'):
    return {'Street1': '', 'Street2': '', 'City': '', 'State': 'Not Available', 'Postal Code': '', 'Country': '', 'Full Address': '', 'Status': reason}

def validate_coordinate_values(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        return (-90 <= lat <= 90 and -180 <= lon <= 180), 'Valid' if (-90 <= lat <= 90 and -180 <= lon <= 180) else 'Out of range'
    except: return False, 'Invalid'

def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    result_df.insert(0, id_col, df[id_col])
    result_df.insert(1, lat_col, df[lat_col])
    result_df.insert(2, lon_col, df[lon_col])
    # Merge with all original columns for hover
    combined_df = pd.concat([df.reset_index(drop=True), result_df.drop([lat_col, lon_col], axis=1)], axis=1)
    # Ensure unique columns
    combined_df = combined_df.loc[:, ~combined_df.columns.duplicated()]
    return combined_df

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")
st.markdown("Convert latitude/longitude to addresses and visualize on map.")

# Session state
for key in ["df","processed_df","logs","api_client","api_provider"]: 
    if key not in st.session_state: st.session_state[key] = None

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Provider", ["LocationIQ","Google Maps","OpenStreetMap (Nominatim)"])
st.session_state.api_provider = api_provider
env_api_key = get_api_key_from_env(api_provider)
if api_provider in ["LocationIQ","Google Maps"]:
    if env_api_key:
        api_key = env_api_key
    else:
        api_key = st.sidebar.text_input(f"API Key for {api_provider}", type="password")
else:
    api_key = None

# Initialize client
if api_key or api_provider=="OpenStreetMap (Nominatim)":
    st.session_state.api_client = get_client(api_provider, api_key)

# File upload
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx","csv"])
if uploaded_file:
    try:
        df, sheets = load_file(uploaded_file)
        st.session_state.df = df
    except Exception as e:
        st.error(f"Error loading file: {str(e)}")
        st.stop()

    st.markdown("### File Preview")
    st.dataframe(df.head())

    lat_col, lon_col = find_coordinate_columns(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    id_col = st.selectbox("Select Unique ID Column", remaining_cols)
    stat_col = st.selectbox("Select Statistics Column", remaining_cols)

    if st.button("Start Geocoding"):
        processed_data = initialize_processed_data()
        for idx,row in df.iterrows():
            lat, lon = row[lat_col], row[lon_col]
            is_valid,status = validate_coordinate_values(lat, lon)
            if not is_valid:
                err = get_coordinate_error_record(status)
                for k,v in err.items(): processed_data[k].append(v)
            else:
                result = st.session_state.api_client.reverse_geocode(lat, lon)
                if result:
                    for k in ['street1','street2','city','state','postal','country','address']:
                        processed_data_key = {'street1':'Street1','street2':'Street2','city':'City','state':'State',
                                              'postal':'Postal Code','country':'Country','address':'Full Address'}[k]
                        processed_data[processed_data_key].append(result[k])
                    processed_data['Latitude'].append(lat)
                    processed_data['Longitude'].append(lon)
                    processed_data['Status'].append('Success')
                else:
                    err = get_error_record()
                    for k,v in err.items(): processed_data[k].append(v)
        result_df = prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col)
        st.session_state.processed_df = result_df
        st.success("Geocoding Complete!")
        st.dataframe(result_df.head())

        # Filter map by statistics
        filter_stats = st.multiselect("Filter by Statistics", options=result_df[stat_col].unique(), default=result_df[stat_col].unique())
        filtered_df = result_df[result_df[stat_col].isin(filter_stats)]
        filtered_df = filtered_df.loc[:, ~filtered_df.columns.duplicated()]

        # Pydeck Map
        if not filtered_df.empty:
            st.subheader("Map View")
            color_map = {"stopped":[255,0,0], "moving":[0,255,0], "idle":[255,255,0]}
            filtered_df['color'] = filtered_df[stat_col].map(lambda x: color_map.get(str(x).lower(), [0,0,255]))
            st.pydeck_chart(pdk.Deck(
                initial_view_state=pdk.ViewState(
                    latitude=filtered_df['Latitude'].mean(),
                    longitude=filtered_df['Longitude'].mean(),
                    zoom=6,
                    pitch=0
                ),
                layers=[pdk.Layer(
                    "ScatterplotLayer",
                    data=filtered_df,
                    get_position='[Longitude, Latitude]',
                    get_color='color',
                    get_radius=5000,
                    pickable=True,
                )],
                tooltip={"text": "{id_col}\n{stat_col}\n{Full Address}"}
            ))

        # Export
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name="Geocoded Data")
        excel_buffer.seek(0)
        st.download_button("Download Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("Download CSV", result_df.to_csv(index=False), file_name=f"{generate_unique_filename()}.csv")
else:
    st.info("Upload a file to get started.")
