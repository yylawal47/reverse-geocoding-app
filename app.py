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
# UTILITY FUNCTIONS
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


def prepare_output_dataframe(df, processed_data, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    # Keep original columns
    result_df = pd.concat([df.reset_index(drop=True), result_df], axis=1)
    result_df.rename(columns={'Status': 'Geocoding Status'}, inplace=True)
    return result_df


def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(
    page_title="🗺️ Geocoding & Map Dashboard",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Geocoding & Map Dashboard")

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Geocoding Provider",
                                options=["LocationIQ", "Google Maps", "OpenStreetMap (Nominatim)"])
env_api_key = get_api_key_from_env(api_provider)
if api_provider in ["LocationIQ", "Google Maps"]:
    if env_api_key:
        api_key = env_api_key
    else:
        api_key = st.sidebar.text_input(f"Enter your {api_provider} API Key", type="password")
else:
    api_key = None

# Initialize API client
if api_key or api_provider == "OpenStreetMap (Nominatim)":
    api_client = get_client(api_provider, api_key)
else:
    api_client = None

# File upload
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV file", type=["xlsx", "csv"])

if uploaded_file:
    df, sheets, selected_sheet = load_file(uploaded_file)
    st.subheader("📊 File Preview")
    st.dataframe(df.head())

    # Auto detect coordinates
    lat_col, lon_col = find_coordinate_columns(df)

    st.write(f"Latitude column detected: {lat_col}")
    st.write(f"Longitude column detected: {lon_col}")

    # Run geocoding
    if st.button("🚀 Run Geocoding"):
        if not api_client:
            st.error("API client not initialized or API key missing")
        else:
            processed_data = initialize_processed_data()
            for idx, row in df.iterrows():
                lat = row[lat_col]
                lon = row[lon_col]
                is_valid, status = validate_coordinate_values(lat, lon)
                if not is_valid:
                    err = get_coordinate_error_record(status)
                    for k, v in err.items(): processed_data[k].append(v)
                else:
                    result = api_client.reverse_geocode(lat, lon)
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
                        for k, v in err.items(): processed_data[k].append(v)

            result_df = prepare_output_dataframe(df, processed_data, lat_col, lon_col)
            st.success("🎉 Geocoding Complete!")
            st.dataframe(result_df.head())

            # Download
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                result_df.to_excel(writer, index=False)
            excel_buffer.seek(0)
            st.download_button("📥 Download as Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
            st.download_button("📥 Download as CSV", result_df.to_csv(index=False).encode(), file_name=f"{generate_unique_filename()}.csv")

# ---------------------
# Map view
# ---------------------
if uploaded_file:
    st.sidebar.header("📍 Map View")
    show_map = st.sidebar.checkbox("Show points on Map")
    mapbox_token = os.environ.get("MAPBOX_API_KEY", "")
    if show_map:
        if not mapbox_token:
            mapbox_token = st.sidebar.text_input("Enter Mapbox Access Token", type="password")
        if mapbox_token:
            map_df = df.copy()
            map_df.rename(columns={lat_col:'lat', lon_col:'lon'}, inplace=True)
            # Add tooltip text
            map_df['tooltip_text'] = map_df.apply(lambda x: '<br>'.join([f"{c}: {x[c]}" for c in map_df.columns]), axis=1)
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
                tooltip={"html": "{tooltip_text}"},
                mapbox_key=mapbox_token
            ))

# ---------------------
# Summary table
# ---------------------
if uploaded_file:
    st.sidebar.header("📊 Summary")
    show_summary = st.sidebar.checkbox("Show ID distribution by State")
    if show_summary:
        if 'State' in df.columns:
            summary_df = df.groupby('State').size().reset_index(name='Count')
            st.dataframe(summary_df)
            csv_buffer = summary_df.to_csv(index=False).encode()
            st.download_button("📥 Download Summary CSV", csv_buffer, file_name="state_summary.csv")
        else:
            st.warning("No 'State' column found in the data")
