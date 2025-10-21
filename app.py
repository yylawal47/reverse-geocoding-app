import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
from io import BytesIO
from datetime import datetime
import os

# ==============================
# UTILITY FUNCTIONS
# ==============================

def load_file(uploaded_file):
    if uploaded_file.name.endswith('.xlsx'):
        df = pd.read_excel(uploaded_file)
    elif uploaded_file.name.endswith('.csv'):
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
        lat = float(lat)
        lon = float(lon)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return True
        return False
    except:
        return False

def generate_unique_filename(prefix="data"):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# STREAMLIT APP
# ==============================

st.set_page_config(page_title="🗺️ Geocoding & Map Dashboard", layout="wide")

st.title("🗺️ Geocoding & Map Dashboard")
st.markdown("Upload your file and view coordinates on the map. Optionally, run geocoding to get State/Address.")

# Session state
if "df" not in st.session_state: st.session_state.df = None
if "processed_df" not in st.session_state: st.session_state.processed_df = None
if "geocoded" not in st.session_state: st.session_state.geocoded = False

# ==============================
# File Upload
# ==============================
uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["xlsx", "csv"])

if uploaded_file:
    df = load_file(uploaded_file)
    st.session_state.df = df

    st.markdown("### 📊 File Preview")
    st.dataframe(df.head())

    lat_col, lon_col = find_coordinate_columns(df)
    if not lat_col or not lon_col:
        st.error("Could not automatically detect latitude and longitude columns.")
        st.stop()

    st.info(f"Detected Latitude: `{lat_col}` | Longitude: `{lon_col}`")

    # Filter valid coordinates
    df_valid = df[df[[lat_col, lon_col]].apply(lambda row: validate_coordinate_values(row[lat_col], row[lon_col]), axis=1)]

    # ==============================
    # Map Display
    # ==============================
    if not df_valid.empty:
    st.subheader("📍 Map View")
    st.markdown("Hover over points to see full row data.")
    map_df = df_valid.copy()
    
    # Prepare hover text with all columns
    hover_cols = df_valid.columns.tolist()
    map_df['hover'] = map_df.apply(lambda x: '<br>'.join([f"{col}: {x[col]}" for col in hover_cols]), axis=1)

    st.pydeck_chart(pdk.Deck(
        map_style='mapbox://styles/mapbox/streets-v12',
        initial_view_state=pdk.ViewState(
            latitude=map_df[lat_col].mean(),
            longitude=map_df[lon_col].mean(),
            zoom=10,
            pitch=0
        ),
        layers=[
            pdk.Layer(
                'IconLayer',
                data=map_df,
                get_icon={
                    "url": "https://img.icons8.com/emoji/48/tanker-truck.png",
                    "width": 128,
                    "height": 128,
                    "anchor": [64, 128]
                },
                get_size=4,
                size_scale=15,
                get_position=[lon_col, lat_col],
                pickable=True
            )
        ],
        tooltip={"html": "{hover}", "style": {"color": "white"}}
    ))
    # ==============================
    # Geocoding Option
    # ==============================
    st.subheader("🗺️ Geocoding (Optional)")
    st.markdown("If you want to fetch `State` for each coordinate, run geocoding:")

    if st.button("🚀 Run Geocoding"):
        # Use OpenStreetMap Nominatim
        processed_data = df.copy()
        state_list = []
        for idx, row in df.iterrows():
            lat = row[lat_col]
            lon = row[lon_col]
            if validate_coordinate_values(lat, lon):
                try:
                    resp = requests.get(f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json", headers={'User-Agent': 'streamlit-geocoder'})
                    data = resp.json()
                    state = data.get('address', {}).get('state', '')
                except:
                    state = ''
            else:
                state = ''
            state_list.append(state)
        processed_data['State'] = state_list
        st.session_state.processed_df = processed_data
        st.session_state.geocoded = True
        st.success("✅ Geocoding complete! 'State' column added.")

    # ==============================
    # Export Buttons
    # ==============================
    st.subheader("💾 Export Data")
    if st.session_state.geocoded:
        df_to_export = st.session_state.processed_df
    else:
        df_to_export = df

    # Export main data
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df_to_export.to_excel(writer, index=False, sheet_name="Data")
    excel_buffer.seek(0)
    st.download_button("📥 Download Data as Excel", excel_buffer, file_name=f"{generate_unique_filename()}.xlsx")

    # Export summary by State if geocoded
    if st.session_state.geocoded:
        st.subheader("📊 Summary by State")
        summary_df = st.session_state.processed_df.groupby('State').size().reset_index(name='Count')
        st.dataframe(summary_df)
        summary_csv = summary_df.to_csv(index=False)
        st.download_button("📥 Download Summary CSV", summary_csv, file_name=f"{generate_unique_filename('summary')}.csv")

else:
    st.info("👈 Please upload a file to get started.")
