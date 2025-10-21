import streamlit as st
import pandas as pd
import requests
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
        raise NotImplementedError("This method should be implemented by subclasses.")

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
                    'street1': address.get('road', ''),
                    'street2': address.get('suburb', ''),
                    'city': address.get('city', address.get('town', address.get('village', ''))),
                    'state': address.get('state', ''),
                    'postal': address.get('postcode', ''),
                    'country': address.get('country', ''),
                    'address': data.get('display_name', '')
                }
            else: return None
        except: return None

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
            else: return None
        except: return None

def get_client(provider, api_key=None):
    if provider=="LocationIQ": return LocationIQClient(api_key)
    elif provider=="OpenStreetMap (Nominatim)": return OpenStreetMapClient()
    else: raise ValueError("Unsupported provider")

# ==============================
# UTILITIES
# ==============================
def load_file(uploaded_file):
    if uploaded_file.name.endswith('.xlsx'):
        xls = pd.ExcelFile(uploaded_file)
        return pd.read_excel(xls, sheet_name=xls.sheet_names[0])
    elif uploaded_file.name.endswith('.csv'):
        return pd.read_csv(uploaded_file)
    else:
        raise ValueError("Unsupported file type")

def find_coordinate_columns(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinate_values(lat, lon):
    try: lat, lon = float(lat), float(lon); return (-90<=lat<=90 and -180<=lon<=180), 'Valid'
    except: return False, 'Invalid'

def initialize_processed_data():
    return {'Latitude': [], 'Longitude': [], 'Street1': [], 'Street2': [], 'City': [], 'State': [],
            'Postal Code': [], 'Country': [], 'Full Address': [], 'Status': []}

def get_error_record():
    return {'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'',
            'Country':'','Full Address':'','Status':'Error'}

def get_coordinate_error_record(reason='Invalid'):
    return {'Street1':'','Street2':'','City':'','State':'Not Available','Postal Code':'',
            'Country':'','Full Address':'','Status':reason}

def prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col):
    result_df = pd.DataFrame(processed_data)
    result_df.insert(0, id_col, df[id_col])
    result_df.insert(1, lat_col, df[lat_col])
    result_df.insert(2, lon_col, df[lon_col])
    result_df.rename(columns={'Status':'Geocoding Status'}, inplace=True)
    # Preserve other columns
    for c in df.columns:
        if c not in result_df.columns:
            result_df[c] = df[c]
    return result_df

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================
st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")
st.title("🗺️ Geocoding & Map Dashboard")

# Session
if "df" not in st.session_state: st.session_state.df=None
if "processed_df" not in st.session_state: st.session_state.processed_df=None
if "api_client" not in st.session_state: st.session_state.api_client=None

# Sidebar
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio("Select Geocoding Provider", ["LocationIQ","OpenStreetMap (Nominatim)"])
api_key = None
if api_provider=="LocationIQ":
    api_key = st.sidebar.text_input("API Key for LocationIQ", type="password")
if api_key or api_provider=="OpenStreetMap (Nominatim)":
    st.session_state.api_client = get_client(api_provider, api_key)

# File upload
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx","csv"])
if uploaded_file:
    df = load_file(uploaded_file)
    st.session_state.df = df

    st.subheader("📊 File Preview")
    st.dataframe(df.head())

    lat_col, lon_col = find_coordinate_columns(df)
    col1, col2, col3 = st.columns(3)
    with col1: lat_col = st.selectbox("Latitude Column", df.columns, index=list(df.columns).index(lat_col) if lat_col else 0)
    with col2: lon_col = st.selectbox("Longitude Column", df.columns, index=list(df.columns).index(lon_col) if lon_col else 0)
    with col3: id_col = st.selectbox("Unique ID Column", df.columns)

    stat_col = st.selectbox("Statistics Column", df.columns, index=list(df.columns).index("Statistics") if "Statistics" in df.columns else 0)

    # Geocode
    if st.button("🚀 Start Geocoding"):
        processed_data = initialize_processed_data()
        for idx,row in df.iterrows():
            lat, lon = row[lat_col], row[lon_col]
            is_valid, status = validate_coordinate_values(lat, lon)
            if not is_valid:
                err = get_coordinate_error_record(status)
                for k,v in err.items(): processed_data[k].append(v)
            else:
                result = st.session_state.api_client.reverse_geocode(lat, lon)
                if result:
                    for k in ['street1','street2','city','state','postal','country','address']:
                        processed_data_key={'street1':'Street1','street2':'Street2','city':'City','state':'State',
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
        st.success("🎉 Geocoding Complete!")

        # Export
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer: result_df.to_excel(writer,index=False)
        excel_buffer.seek(0)
        st.download_button("📥 Download Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")
        st.download_button("📥 Download CSV", result_df.to_csv(index=False), file_name=f"{generate_unique_filename()}.csv")

        # Summary
        st.subheader("📈 Summary by State")
        summary_df = result_df.groupby('State')[id_col].count().reset_index().rename(columns={id_col:'Count'})
        st.dataframe(summary_df)
        # Export summary
        excel_buffer_summary = BytesIO()
        with pd.ExcelWriter(excel_buffer_summary, engine='openpyxl') as writer: summary_df.to_excel(writer,index=False)
        excel_buffer_summary.seek(0)
        st.download_button("📥 Download Summary Excel", excel_buffer_summary, file_name=f"summary_{generate_unique_filename()}.xlsx")

        # Map view
        st.subheader("🗺️ Map View")
        color_map = {'stopped':[255,0,0],'moving':[0,255,0],'idle':[0,0,255]}
        result_df['color'] = result_df[stat_col].map(color_map).apply(lambda x: x if isinstance(x,list) else [128,128,128])

        # Create tooltip with all columns
        tooltip_cols = [id_col, stat_col, 'State', 'Full Address']
        tooltip_text = "{"+", ".join(tooltip_cols)+"}"
        st.pydeck_chart(pdk.Deck(
            initial_view_state=pdk.ViewState(
                latitude=result_df['Latitude'].mean(),
                longitude=result_df['Longitude'].mean(),
                zoom=5, pitch=0
            ),
            layers=[pdk.Layer(
                "ScatterplotLayer",
                data=result_df,
                get_position='[Longitude, Latitude]',
                get_color='color',
                get_radius=500,
                pickable=True,
                tooltip=tooltip_text
            )]
        ))
