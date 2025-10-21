import streamlit as st
import pandas as pd
import requests
from io import BytesIO
from datetime import datetime
import pydeck as pdk
import os

# ==============================
# API CLIENT CLASSES
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
                addr = data.get('address', {})
                return {
                    'street1': addr.get('road',''),
                    'street2': addr.get('suburb',''),
                    'city': addr.get('city', addr.get('town', addr.get('village',''))),
                    'state': addr.get('state',''),
                    'postal': addr.get('postcode',''),
                    'country': addr.get('country',''),
                    'address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ LocationIQ API returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ LocationIQ API error: {str(e)}")
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
                addr = data.get('address',{})
                return {
                    'street1': addr.get('road',''),
                    'street2': addr.get('suburb',''),
                    'city': addr.get('city', addr.get('town', addr.get('village',''))),
                    'state': addr.get('state',''),
                    'postal': addr.get('postcode',''),
                    'country': addr.get('country',''),
                    'address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ OSM API returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OSM API error: {str(e)}")
            return None

def get_client(provider, api_key=None):
    if provider=="LocationIQ": return LocationIQClient(api_key)
    if provider=="OpenStreetMap (Nominatim)": return OpenStreetMapClient()
    raise ValueError(f"Unsupported provider: {provider}")

# ==============================
# UTILITY FUNCTIONS
# ==============================

def load_file(uploaded_file):
    if uploaded_file.name.endswith('.xlsx'):
        xls = pd.ExcelFile(uploaded_file)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
    elif uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        raise ValueError("Unsupported file type")
    return df

def find_lat_lon_cols(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinate(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        return -90<=lat<=90 and -180<=lon<=180
    except: return False

def generate_filename(prefix="geocoded"):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")
st.title("🗺️ Geocoding & Map Dashboard")

# Session State
for key in ["df","processed_df","logs","api_client","api_provider"]: 
    if key not in st.session_state: st.session_state[key] = None

# Sidebar - Provider
st.sidebar.header("⚙️ Configuration")
provider = st.sidebar.radio("Select Geocoding Provider", ["LocationIQ","OpenStreetMap (Nominatim)"])
st.session_state.api_provider = provider

if provider=="LocationIQ":
    api_key = st.sidebar.text_input("Enter LocationIQ API Key", type="password")
else:
    api_key = None

if api_key or provider=="OpenStreetMap (Nominatim)":
    st.session_state.api_client = get_client(provider, api_key)

# Sidebar - File Upload
st.sidebar.header("📤 Upload File")
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx","csv"])
if uploaded_file:
    df = load_file(uploaded_file)
    st.session_state.df = df
    st.subheader("📊 File Preview")
    st.dataframe(df.head())

    lat_col, lon_col = find_lat_lon_cols(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    id_col = st.selectbox("Select Unique ID Column", remaining_cols)
    stat_col = st.selectbox("Select Statistic Column", remaining_cols, index=remaining_cols.index("Statistic") if "Statistic" in remaining_cols else 0)

    lat_col = st.selectbox("Latitude Column", df.columns, index=df.columns.get_loc(lat_col) if lat_col else 0)
    lon_col = st.selectbox("Longitude Column", df.columns, index=df.columns.get_loc(lon_col) if lon_col else 0)

# ==============================
# GEOCODING
# ==============================
if uploaded_file and st.button("🚀 Start Geocoding"):
    processed_data = df.copy()
    logs = []
    for idx, row in processed_data.iterrows():
        lat, lon = row[lat_col], row[lon_col]
        if validate_coordinate(lat, lon):
            result = st.session_state.api_client.reverse_geocode(lat, lon, lambda msg: logs.append(msg))
            if result:
                for k,v in result.items():
                    processed_data.at[idx, k] = v
            else:
                for k in ['street1','street2','city','state','postal','country','address']:
                    processed_data.at[idx,k] = None
        else:
            for k in ['street1','street2','city','state','postal','country','address']:
                processed_data.at[idx,k] = None
    st.session_state.processed_df = processed_data
    st.success("🎉 Geocoding Complete!")
    st.dataframe(processed_data.head())

# ==============================
# MAP VIEW
# ==============================
if uploaded_file:
    st.subheader("🗺️ Map & Summary Options")
    show_map = st.checkbox("Show Points on Map")
    show_summary = st.checkbox("Show Summary by State")

    map_df = st.session_state.processed_df if st.session_state.processed_df is not None else st.session_state.df
    # Ensure Statistic column exists
    if stat_col not in map_df.columns:
        st.warning(f"Statistic column '{stat_col}' not found")
    else:
        color_map = {'stopped':[255,0,0],'moving':[0,255,0],'idle':[0,0,255]}
        map_df['color'] = map_df[stat_col].str.lower().map(color_map).apply(lambda x: x if isinstance(x,list) else [128,128,128])

        if show_map:
            st.write("### Map View")
            map_df_clean = map_df.dropna(subset=[lat_col, lon_col])
            st.pydeck_chart(pdk.Deck(
                initial_view_state=pdk.ViewState(
                    latitude=map_df_clean[lat_col].mean(),
                    longitude=map_df_clean[lon_col].mean(),
                    zoom=5,
                    pitch=0,
                ),
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        data=map_df_clean,
                        get_position=[lon_col, lat_col],
                        get_color="color",
                        get_radius=500,
                        pickable=True,
                    )
                ],
                tooltip={ "text": f"{id_col}: {{ {id_col} }}\n{stat_col}: {{ {stat_col} }}" }
            ))

        if show_summary:
            st.write("### Summary by State")
            summary = map_df.groupby('state')[id_col].count().reset_index().rename(columns={id_col:'Count'})
            st.dataframe(summary)
            # Download summary
            csv_buffer = BytesIO()
            summary.to_csv(csv_buffer, index=False)
            st.download_button("📥 Download Summary CSV", csv_buffer, file_name=f"{generate_filename('summary')}.csv")
