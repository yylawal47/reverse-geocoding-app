import streamlit as st
import pandas as pd
import requests
from io import BytesIO
from datetime import datetime
import pydeck as pdk
import os

# ===========================
# Geocoding Clients
# ===========================

class BaseGeocodingClient:
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError()

class LocationIQClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def __init__(self, api_key):
        self.api_key = api_key
    def reverse_geocode(self, lat, lon, log_callback=None):
        try:
            url = f"https://us1.locationiq.com/v1/reverse.php?key={self.api_key}&lat={lat}&lon={lon}&format=json"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                address = data.get('address', {})
                return {
                    'Street1': address.get('road',''),
                    'Street2': address.get('suburb',''),
                    'City': address.get('city', address.get('town', address.get('village',''))),
                    'State': address.get('state',''),
                    'Postal Code': address.get('postcode',''),
                    'Country': address.get('country',''),
                    'Full Address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ LocationIQ returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ LocationIQ error: {e}")
            return None

class OpenStreetMapClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
            headers = {'User-Agent': 'streamlit-app'}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                address = data.get('address',{})
                return {
                    'Street1': address.get('road',''),
                    'Street2': address.get('suburb',''),
                    'City': address.get('city', address.get('town', address.get('village',''))),
                    'State': address.get('state',''),
                    'Postal Code': address.get('postcode',''),
                    'Country': address.get('country',''),
                    'Full Address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ OSM returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OSM error: {e}")
            return None

def get_client(provider, api_key=None):
    if provider=="LocationIQ": return LocationIQClient(api_key)
    elif provider=="OpenStreetMap (Nominatim)": return OpenStreetMapClient()
    else: raise ValueError("Unsupported provider")

# ===========================
# Utility Functions
# ===========================

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

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ===========================
# Streamlit App
# ===========================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")
st.markdown("Upload a CSV/XLSX with latitude & longitude to extract addresses and view on map.")

# --- Sidebar ---
st.sidebar.header("Settings")
api_provider = st.sidebar.radio("Geocoding Provider", ["LocationIQ", "OpenStreetMap (Nominatim)"])
api_key = None
if api_provider=="LocationIQ":
    api_key = st.sidebar.text_input("Enter LocationIQ API Key", type="password")
client = get_client(api_provider, api_key)

uploaded_file = st.sidebar.file_uploader("Upload CSV or Excel", type=['csv','xlsx'])

if uploaded_file:
    df = load_file(uploaded_file)
    lat_col, lon_col = find_coordinate_columns(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    id_col = st.selectbox("Select Unique ID Column", remaining_cols)
    stat_col = st.selectbox("Select Statistics Column", remaining_cols)

    st.markdown("### 📊 File Preview")
    st.dataframe(df[[id_col, lat_col, lon_col, stat_col]].head())

    if st.button("🚀 Start Geocoding"):
        processed_data = df.copy()
        processed_data['Street1'] = ''
        processed_data['Street2'] = ''
        processed_data['City'] = ''
        processed_data['State'] = ''
        processed_data['Postal Code'] = ''
        processed_data['Country'] = ''
        processed_data['Full Address'] = ''

        progress_bar = st.progress(0)
        for idx, row in processed_data.iterrows():
            lat, lon = row[lat_col], row[lon_col]
            try:
                lat, lon = float(lat), float(lon)
                if -90<=lat<=90 and -180<=lon<=180:
                    result = client.reverse_geocode(lat, lon)
                    if result:
                        for k,v in result.items(): processed_data.at[idx,k]=v
            except:
                pass
            progress_bar.progress((idx+1)/len(processed_data))

        st.success("🎉 Geocoding Complete!")
        st.session_state['processed_df'] = processed_data
        st.dataframe(processed_data.head())

        # --- Export ---
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            processed_data.to_excel(writer, index=False)
        buffer.seek(0)
        st.download_button("📥 Download Geocoded Excel", buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("📥 Download Geocoded CSV", processed_data.to_csv(index=False).encode(), file_name=f"{generate_unique_filename()}.csv")

        # --- Map Option ---
        if st.checkbox("🗺️ View on Map"):
            map_df = processed_data.dropna(subset=[lat_col, lon_col])
            map_df[lat_col] = pd.to_numeric(map_df[lat_col], errors='coerce')
            map_df[lon_col] = pd.to_numeric(map_df[lon_col], errors='coerce')
            map_df = map_df.dropna(subset=[lat_col, lon_col])
            
            # Color mapping
            color_map = {'stopped':[255,0,0],'moving':[0,255,0],'idle':[0,0,255]}
            map_df['color'] = map_df[stat_col].str.lower().map(color_map).apply(lambda x: x if isinstance(x,list) else [128,128,128])

            # Tooltip
            tooltip_cols = [id_col, stat_col, 'State','Full Address'] + [c for c in df.columns if c not in [id_col, lat_col, lon_col, stat_col]]
            tooltip_text = "{"+", ".join([f"{c}: {{{c}}}" for c in tooltip_cols])+"}"

            st.pydeck_chart(pdk.Deck(
                initial_view_state=pdk.ViewState(
                    latitude=map_df[lat_col].mean(),
                    longitude=map_df[lon_col].mean(),
                    zoom=5,
                    pitch=0
                ),
                layers=[pdk.Layer(
                    "ScatterplotLayer",
                    data=map_df,
                    get_position=f"[{lon_col}, {lat_col}]",
                    get_color='color',
                    get_radius=500,
                    pickable=True
                )],
                tooltip=tooltip_text
            ))

        # --- Summary by State ---
        if st.checkbox("📊 Show Summary by State"):
            summary = processed_data.groupby('State')[id_col].nunique().reset_index()
            summary.rename(columns={id_col:"Count"}, inplace=True)
            st.dataframe(summary)
            st.download_button("📥 Download State Summary CSV", summary.to_csv(index=False).encode(), file_name=f"state_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
