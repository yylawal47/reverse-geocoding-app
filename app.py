import streamlit as st
import pandas as pd
import requests
from io import BytesIO
from datetime import datetime
import pydeck as pdk

# ==============================
# Geocoding Clients
# ==============================
class BaseGeocodingClient:
    RATE_LIMIT = 1
    def reverse_geocode(self, lat, lon, log_callback=None):
        raise NotImplementedError

class LocationIQClient(BaseGeocodingClient):
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
            return None
        except Exception as e:
            if log_callback: log_callback(f"❌ {str(e)}")
            return None

def get_client(provider, api_key=None):
    if provider == "LocationIQ":
        return LocationIQClient(api_key)
    else:
        raise ValueError("Unsupported provider")

# ==============================
# Utility Functions
# ==============================
def detect_lat_lon(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinates(df, lat_col, lon_col):
    return df[lat_col].notna() & df[lon_col].notna()

def prepare_output_dataframe(df, processed_data, lat_col, lon_col):
    df_copy = df.copy()
    df_copy['Street1'] = processed_data['Street1']
    df_copy['Street2'] = processed_data['Street2']
    df_copy['City'] = processed_data['City']
    df_copy['State'] = processed_data['State']
    df_copy['Postal Code'] = processed_data['Postal Code']
    df_copy['Country'] = processed_data['Country']
    df_copy['Full Address'] = processed_data['Full Address']
    return df_copy

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# Streamlit App
# ==============================
st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")
st.markdown("Upload your file, view on map, and optionally run geocoding.")

# ==============================
# File Upload
# ==============================
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV", type=["xlsx", "csv"])
if uploaded_file:
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    
    st.session_state['df'] = df
    lat_col, lon_col = detect_lat_lon(df)
    st.session_state['lat_col'] = lat_col
    st.session_state['lon_col'] = lon_col

    st.subheader("📊 File Preview")
    st.dataframe(df.head())

    # ==============================
    # Map View
    # ==============================
    st.subheader("🗺️ Map View")
    if st.checkbox("Show points on map"):
        map_df = df.copy()
        map_df = map_df[validate_coordinates(df, lat_col, lon_col)]
        st.pydeck_chart(pdk.Deck(
            map_style='mapbox://styles/mapbox/light-v11',
            initial_view_state=pdk.ViewState(
                latitude=map_df[lat_col].mean(),
                longitude=map_df[lon_col].mean(),
                zoom=5,
                pitch=0,
            ),
            layers=[
                pdk.Layer(
                    'ScatterplotLayer',
                    data=map_df,
                    get_position=[lon_col, lat_col],
                    get_color=[0, 128, 255],
                    get_radius=500,
                    pickable=True
                )
            ],
            tooltip={
                "text": "\n".join([f"{c}: {{{c}}}" for c in map_df.columns])
            }
        ))

    # ==============================
    # Geocoding Section
    # ==============================
    st.subheader("🚀 Geocoding")
    provider = st.selectbox("Select Geocoding Provider", ["LocationIQ"])
    api_key = st.text_input("Enter API Key for LocationIQ", type="password")
    run_geocode = st.button("Start Geocoding")

    if run_geocode:
        if not api_key:
            st.error("Please provide API Key for LocationIQ")
        else:
            client = get_client(provider, api_key)
            processed_data = {'Street1': [], 'Street2': [], 'City': [], 'State': [], 'Postal Code': [], 'Country': [], 'Full Address': []}
            for idx, row in df.iterrows():
                lat = row[lat_col]
                lon = row[lon_col]
                if pd.notna(lat) and pd.notna(lon):
                    result = client.reverse_geocode(lat, lon)
                    if result:
                        for k in processed_data.keys():
                            processed_data[k].append(result.get(k,''))
                    else:
                        for k in processed_data.keys():
                            processed_data[k].append('')
                else:
                    for k in processed_data.keys():
                        processed_data[k].append('')
            result_df = prepare_output_dataframe(df, processed_data, lat_col, lon_col)
            st.session_state['processed_df'] = result_df
            st.success("🎉 Geocoding Complete!")
            st.dataframe(result_df.head())

            # Download
            buffer = BytesIO()
            result_df.to_excel(buffer, index=False)
            buffer.seek(0)
            st.download_button("📥 Download Geocoded Excel", buffer, file_name=f"{generate_unique_filename()}.xlsx")

            # Summary Table
            st.subheader("📊 Summary by State")
            if 'State' in result_df.columns:
                summary_df = result_df.groupby('State')[lat_col].count().reset_index()
                summary_df.rename(columns={lat_col: 'Count'}, inplace=True)
                st.dataframe(summary_df)
