import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO
import os
from datetime import datetime
import pydeck as pdk

# ==============================
# API CLIENT
# ==============================

class BaseGeocodingClient:
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError

class LocationIQClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def __init__(self, api_key): self.api_key = api_key
    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://us1.locationiq.com/v1/reverse.php?key={self.api_key}&lat={lat}&lon={lon}&format=json"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                address = data.get('address', {})
                return {
                    'street1': address.get('road',''),
                    'street2': address.get('suburb',''),
                    'city': address.get('city', address.get('town','')),
                    'state': address.get('state',''),
                    'postal': address.get('postcode',''),
                    'country': address.get('country',''),
                    'address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ LocationIQ API returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ LocationIQ API error: {e}")
            return None

class GoogleMapsClient(BaseGeocodingClient):
    RATE_LIMIT = 1
    def __init__(self, api_key): self.api_key = api_key
    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={self.api_key}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code==200:
                data = resp.json()
                if data.get('status')=='OK' and data.get('results'):
                    result = data['results'][0]
                    comps = {c['types'][0]:c['long_name'] for c in result['address_components']}
                    return {
                        'street1': comps.get('route',''),
                        'street2': comps.get('sublocality_level_1',''),
                        'city': comps.get('locality',''),
                        'state': comps.get('administrative_area_level_1',''),
                        'postal': comps.get('postal_code',''),
                        'country': comps.get('country',''),
                        'address': result.get('formatted_address','')
                    }
                return None
            else:
                if log_callback: log_callback(f"❌ Google Maps API returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ Google Maps API error: {e}")
            return None

class OpenStreetMapClient(BaseGeocodingClient):
    RATE_LIMIT=1
    def reverse_geocode(self, lat, lon, log_callback=None):
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        headers = {'User-Agent':'streamlit-geocoder-app'}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code==200:
                data=resp.json()
                address=data.get('address',{})
                return {
                    'street1': address.get('road',''),
                    'street2': address.get('suburb',''),
                    'city': address.get('city', address.get('town','')),
                    'state': address.get('state',''),
                    'postal': address.get('postcode',''),
                    'country': address.get('country',''),
                    'address': data.get('display_name','')
                }
            else:
                if log_callback: log_callback(f"❌ OSM API returned {resp.status_code}")
                return None
        except Exception as e:
            if log_callback: log_callback(f"❌ OSM API error: {e}")
            return None

def get_client(provider, api_key=None):
    if provider=="LocationIQ": return LocationIQClient(api_key)
    elif provider=="Google Maps": return GoogleMapsClient(api_key)
    elif provider=="OpenStreetMap (Nominatim)": return OpenStreetMapClient()
    else: raise ValueError(f"Unsupported provider: {provider}")

# ==============================
# UTILS
# ==============================

def get_api_key_from_env(provider):
    key_map = {"LocationIQ":"LOCATIONIQ_API_KEY","Google Maps":"GOOGLE_MAPS_API_KEY"}
    env_var = key_map.get(provider)
    if env_var: return os.environ.get(env_var)
    return None

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

def validate_coordinate_values(lat, lon):
    try:
        lat=float(lat); lon=float(lon)
        return -90<=lat<=90 and -180<=lon<=180, "Valid" if -90<=lat<=90 and -180<=lon<=180 else "Out of range"
    except: return False,"Invalid"

def initialize_processed_data():
    return {'Latitude':[],'Longitude':[],'Street1':[],'Street2':[],'City':[],'State':[],'Postal Code':[],'Country':[],'Full Address':[],'Status':[]}

def get_error_record(): return {'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'','Country':'','Full Address':'','Status':'Error'}
def get_coordinate_error_record(reason='Invalid'): return {'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'','Country':'','Full Address':'','Status':reason}

def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df=pd.DataFrame(processed_data)
    for c in df.columns:  # add other columns
        if c not in [lat_col, lon_col, id_col]: result_df[c]=df[c]
    result_df.insert(0,id_col,df[id_col])
    result_df.insert(1,lat_col,df[lat_col])
    result_df.insert(2,lon_col,df[lon_col])
    result_df.rename(columns={'Status':'Geocoding Status'}, inplace=True)
    return result_df

def generate_unique_filename(): return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", page_icon="🗺️", layout="wide")
st.title("🗺️ Geocoding & Map Dashboard")

if "df" not in st.session_state: st.session_state.df=None
if "processed_df" not in st.session_state: st.session_state.processed_df=None
if "logs" not in st.session_state: st.session_state.logs=[]
if "api_client" not in st.session_state: st.session_state.api_client=None
if "api_provider" not in st.session_state: st.session_state.api_provider=None

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Geocoding Provider", ["LocationIQ","Google Maps","OpenStreetMap (Nominatim)"])
st.session_state.api_provider=api_provider
env_api_key=get_api_key_from_env(api_provider)
if api_provider in ["LocationIQ","Google Maps"]:
    if env_api_key:
        st.sidebar.success("✅ API key loaded from environment")
        api_key = env_api_key
    else:
        api_key=st.sidebar.text_input(f"Enter {api_provider} API Key", type="password")
        if not api_key: st.sidebar.warning("⚠️ Please provide API key")
else: api_key=None

try:
    if api_key or api_provider=="OpenStreetMap (Nominatim)":
        st.session_state.api_client=get_client(api_provider, api_key)
except Exception as e: st.sidebar.error(f"❌ Failed to initialize API client: {str(e)}")

# File upload
uploaded_file=st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx","csv"])
if uploaded_file:
    df = load_file(uploaded_file)
    st.session_state.df = df
    st.markdown("### 📊 File Preview")
    st.dataframe(df.head())
    lat_col, lon_col = find_coordinate_columns(df)
    remaining_cols = [c for c in df.columns if c not in [lat_col, lon_col]]
    col1,col2,col3=st.columns(3)
    with col1: lat_col=st.selectbox("Latitude Column", df.columns, index=df.columns.get_loc(lat_col) if lat_col else 0)
    with col2: lon_col=st.selectbox("Longitude Column", df.columns, index=df.columns.get_loc(lon_col) if lon_col else 0)
    with col3:
        id_col=st.selectbox("Unique ID Column", remaining_cols)
    stat_col=st.selectbox("Statistic Column", [c for c in df.columns if c not in [lat_col, lon_col, id_col]])

    if st.button("🚀 Start Geocoding"):
        processed_data=initialize_processed_data()
        log_placeholder=st.empty(); progress_bar=st.progress(0); status_text=st.empty()
        processed_count=error_count=skipped_count=0

        for idx,(i,row) in enumerate(df.iterrows()):
            lat=row[lat_col]; lon=row[lon_col]
            valid,status=validate_coordinate_values(lat,lon)
            if not valid:
                err=get_coordinate_error_record(status)
                for k,v in err.items(): processed_data[k].append(v)
                skipped_count+=1
            else:
                result=st.session_state.api_client.reverse_geocode(lat,lon)
                if result:
                    for k in ['street1','street2','city','state','postal','country','address']:
                        processed_data_key={'street1':'Street1','street2':'Street2','city':'City','state':'State','postal':'Postal Code','country':'Country','address':'Full Address'}[k]
                        processed_data[processed_data_key].append(result[k])
                    processed_data['Latitude'].append(lat); processed_data['Longitude'].append(lon); processed_data['Status'].append('Success')
                    processed_count+=1
                else:
                    err=get_error_record()
                    for k,v in err.items(): processed_data[k].append(v)
                    error_count+=1
            progress_bar.progress((idx+1)/len(df))
            status_text.text(f"Processing {idx+1}/{len(df)} | ✅ {processed_count} | ❌ {error_count} | ⏭️ {skipped_count}")

        result_df = prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col)
        st.session_state.processed_df=result_df
        st.success(f"🎉 Geocoding Complete! ✅ {processed_count} | ❌ {error_count} | ⏭️ {skipped_count}")

        st.dataframe(result_df.head())

        excel_buffer=BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer: result_df.to_excel(writer,index=False)
        excel_buffer.seek(0)
        st.download_button("📥 Download Geocoded Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("📥 Download Geocoded CSV", result_df.to_csv(index=False), file_name=f"{generate_unique_filename()}.csv")

        # Map and summary option
        st.markdown("---")
        show_map = st.checkbox("🌍 View on Map")
        if show_map:
            map_df=result_df.copy()
            color_map={'stopped':[255,0,0],'moving':[0,255,0],'idle':[0,0,255]}
            map_df['color']=map_df[stat_col].str.lower().map(color_map).apply(lambda x: x if isinstance(x,list) else [128,128,128])
            st.pydeck_chart(pdk.Deck(
                map_style='mapbox://styles/mapbox/light-v10',
                initial_view_state=pdk.ViewState(
                    latitude=map_df['Latitude'].mean(),
                    longitude=map_df['Longitude'].mean(),
                    zoom=5,
                    pitch=0
                ),
                layers=[
                    pdk.Layer(
                        'ScatterplotLayer',
                        data=map_df,
                        get_position='[Longitude, Latitude]',
                        get_fill_color='color',
                        get_radius=5000,
                        pickable=True,
                        auto_highlight=True,
                        tooltip={ "text": f"ID: {{{id_col}}}\nState: {{State}}\nStatistic: {{{stat_col}}}" }
                    )
                ]
            ))

        show_summary = st.checkbox("📊 Show Summary by State")
        if show_summary:
            summary = result_df.groupby('State')[id_col].nunique().reset_index().rename(columns={id_col:"Count"})
            st.dataframe(summary)
            summary_buffer=BytesIO()
            with pd.ExcelWriter(summary_buffer, engine='openpyxl') as writer: summary.to_excel(writer,index=False)
            summary_buffer.seek(0)
            st.download_button("📥 Download Summary Excel", summary_buffer, file_name=f"summary_{generate_unique_filename()}.xlsx")
            st.download_button("📥 Download Summary CSV", summary.to_csv(index=False), file_name=f"summary_{generate_unique_filename()}.csv")

else:
    st.info("👈 Upload a CSV or Excel file to start")
