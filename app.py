import streamlit as st
import pandas as pd
import requests
from io import BytesIO
from datetime import datetime
import pydeck as pdk
import os

# ==============================
# Geocoding Clients
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
                addr = data.get('address',{})
                return {
                    'street1': addr.get('road',''),
                    'street2': addr.get('suburb',''),
                    'city': addr.get('city', addr.get('town','')),
                    'state': addr.get('state',''),
                    'postal': addr.get('postcode',''),
                    'country': addr.get('country',''),
                    'address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ LocationIQ API status {resp.status_code}")
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
                if data.get('status')=='OK' and data.get('results'):
                    res = data['results'][0]
                    comps = {c['types'][0]: c['long_name'] for c in res['address_components']}
                    return {
                        'street1': comps.get('route',''),
                        'street2': comps.get('sublocality_level_1',''),
                        'city': comps.get('locality',''),
                        'state': comps.get('administrative_area_level_1',''),
                        'postal': comps.get('postal_code',''),
                        'country': comps.get('country',''),
                        'address': res.get('formatted_address','')
                    }
                return None
            else:
                if log_callback: log_callback(f"❌ Google Maps API status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ Google Maps API error: {str(e)}")
            return None

class OpenStreetMapClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        headers = {'User-Agent':'streamlit-geocoder-app'}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                addr = data.get('address',{})
                return {
                    'street1': addr.get('road',''),
                    'street2': addr.get('suburb',''),
                    'city': addr.get('city', addr.get('town','')),
                    'state': addr.get('state',''),
                    'postal': addr.get('postcode',''),
                    'country': addr.get('country',''),
                    'address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ OpenStreetMap API status {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OpenStreetMap API error: {str(e)}")
            return None

def get_client(provider, api_key=None):
    if provider=="LocationIQ": return LocationIQClient(api_key)
    elif provider=="Google Maps": return GoogleMapsClient(api_key)
    elif provider=="OpenStreetMap (Nominatim)": return OpenStreetMapClient()
    else: raise ValueError(f"Unsupported provider: {provider}")

# ==============================
# Utils
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
        lat = float(lat); lon = float(lon)
        return -90<=lat<=90 and -180<=lon<=180, 'Valid' if -90<=lat<=90 and -180<=lon<=180 else 'Out of range'
    except: return False,'Invalid'

def initialize_processed_data():
    return { 'Latitude':[],'Longitude':[],'Street1':[],'Street2':[],
            'City':[],'State':[],'Postal Code':[],'Country':[],
            'Full Address':[],'Status':[] }

def get_error_record():
    return { 'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'',
             'Country':'','Full Address':'','Status':'Error' }

def get_coordinate_error_record(reason='Invalid'):
    return { 'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'',
             'Country':'','Full Address':'','Status':reason }

def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    result_df.insert(0,id_col,df[id_col])
    result_df.insert(1,lat_col,df[lat_col])
    result_df.insert(2,lon_col,df[lon_col])
    result_df.rename(columns={'Status':'Geocoding Status'}, inplace=True)
    return result_df

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# Streamlit App
# ==============================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Geocoding Provider", ["LocationIQ","Google Maps","OpenStreetMap (Nominatim)"])
if api_provider in ["LocationIQ","Google Maps"]:
    api_key = st.sidebar.text_input(f"{api_provider} API Key", type="password")
else: api_key = None

uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx","csv"])

# Session state
if "df" not in st.session_state: st.session_state.df=None
if "processed_df" not in st.session_state: st.session_state.processed_df=None
if "logs" not in st.session_state: st.session_state.logs=[]
if "api_client" not in st.session_state: st.session_state.api_client=None

if uploaded_file:
    df = load_file(uploaded_file)
    st.session_state.df = df

    lat_col, lon_col = find_coordinate_columns(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    id_col = st.selectbox("Unique ID Column", remaining_cols)
    stat_col = st.selectbox("Statistic Column", remaining_cols)

    st.subheader("File Preview")
    st.dataframe(df.head())

    # Initialize API client
    if api_key or api_provider=="OpenStreetMap (Nominatim)":
        st.session_state.api_client = get_client(api_provider, api_key)

    # ---------------------------
    # Geocoding
    # ---------------------------
    if st.button("🚀 Run Geocoding"):
        processed_data = initialize_processed_data()
        for idx,row in df.iterrows():
            lat = row[lat_col]; lon=row[lon_col]
            is_valid,status=validate_coordinate_values(lat,lon)
            if not is_valid:
                err=get_coordinate_error_record(status)
                for k,v in err.items(): processed_data[k].append(v)
            else:
                result = st.session_state.api_client.reverse_geocode(lat,lon)
                if result:
                    for k in ['street1','street2','city','state','postal','country','address']:
                        key_map = {'street1':'Street1','street2':'Street2','city':'City','state':'State',
                                   'postal':'Postal Code','country':'Country','address':'Full Address'}
                        processed_data[key_map[k]].append(result[k])
                    processed_data['Latitude'].append(lat); processed_data['Longitude'].append(lon)
                    processed_data['Status'].append('Success')
                else:
                    err = get_error_record()
                    for k,v in err.items(): processed_data[k].append(v)
        result_df = prepare_output_dataframe(df,processed_data,id_col,lat_col,lon_col)
        st.session_state.processed_df=result_df
        st.success("🎉 Geocoding Complete!")
        st.dataframe(result_df.head())

        # Download geocoded
        excel_buffer=BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            result_df.to_excel(writer,index=False)
        excel_buffer.seek(0)
        st.download_button("Download Geocoded Excel", excel_buffer, file_name=generate_unique_filename()+".xlsx")
        st.download_button("Download Geocoded CSV", result_df.to_csv(index=False), file_name=generate_unique_filename()+".csv")

# ---------------------------
# Map View
# ---------------------------
show_map = st.checkbox("🌍 Show on Map")
if show_map:
    if st.session_state.processed_df is not None:
        map_df = st.session_state.processed_df.copy()
        lat_map_col = 'Latitude'; lon_map_col='Longitude'; stat_map_col=stat_col; id_map_col=id_col
    elif uploaded_file is not None:
        map_df = df.copy()
        lat_map_col=lat_col; lon_map_col=lon_col; stat_map_col=stat_col; id_map_col=id_col
    else:
        map_df=None
    if map_df is not None and len(map_df)>0:
        color_map={'stopped':[255,0,0],'moving':[0,255,0],'idle':[0,0,255]}
        map_df['color'] = map_df[stat_map_col].str.lower().map(color_map).apply(lambda x: x if isinstance(x,list) else [128,128,128])
        st.pydeck_chart(pdk.Deck(
            map_style='mapbox://styles/mapbox/light-v10',
            initial_view_state=pdk.ViewState(
                latitude=map_df[lat_map_col].mean(),
                longitude=map_df[lon_map_col].mean(),
                zoom=5
            ),
            layers=[
                pdk.Layer(
                    "ScatterplotLayer",
                    data=map_df,
                    get_position=f"[{lon_map_col},{lat_map_col}]",
                    get_fill_color='color',
                    get_radius=5000,
                    pickable=True,
                    auto_highlight=True,
                    tooltip={"text": f"ID: {{{id_map_col}}}\nStatistic: {{{stat_map_col}}}"}
                )
            ]
        ))

# ---------------------------
# Summary Table
# ---------------------------
show_summary = st.checkbox("📊 Show ID Distribution by State")
if show_summary:
    if st.session_state.processed_df is not None:
        summary_df = st.session_state.processed_df.groupby('State')[id_col].count().reset_index()
        summary_df.rename(columns={id_col:'Count'}, inplace=True)
        st.dataframe(summary_df)
        excel_buffer=BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            summary_df.to_excel(writer,index=False)
        excel_buffer.seek(0)
        st.download_button("Download Summary Excel", excel_buffer, file_name="summary.xlsx")
        st.download_button("Download Summary CSV", summary_df.to_csv(index=False), file_name="summary.csv")
    else:
        st.info("Run geocoding first to get summary")
