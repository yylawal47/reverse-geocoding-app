import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import pydeck as pdk

# ==============================
# Utility Functions
# ==============================
def detect_lat_lon(df):
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
    return lat_col, lon_col

def validate_coordinates(df, lat_col, lon_col):
    return df[lat_col].notna() & df[lon_col].notna()

def generate_unique_filename():
    return f"geocoded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ==============================
# Streamlit App
# ==============================
st.set_page_config(page_title="🗺️ Map Dashboard", layout="wide")
st.title("🗺️ Map Dashboard")
st.markdown("Upload your file, view on map with tanker icons, and optionally run geocoding.")

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
        if not map_df.empty:
            # Add icon data
            map_df['icon_data'] = [{
                "url": "https://cdn-icons-png.flaticon.com/512/684/684908.png",  # tanker icon URL
                "width": 128,
                "height": 128,
                "anchorY": 128
            } for _ in range(len(map_df))]

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
                        'IconLayer',
                        data=map_df,
                        get_icon='icon_data',
                        get_size=4,
                        size_scale=15,
                        get_position=[lon_col, lat_col],
                        pickable=True
                    )
                ],
                tooltip={
                    "text": "\n".join([f"{c}: {{{c}}}" for c in map_df.columns if c != 'icon_data'])
                }
            ))
        else:
            st.warning("No valid coordinates to display on map.")

    # ==============================
    # Optional Geocoding
    # ==============================
    st.subheader("🚀 Optional Geocoding")
    st.info("Geocoding is optional. It can fill 'State' and other address columns if available.")
    if st.button("Run Optional Geocoding"):
        # Dummy geocoding for demonstration
        processed_data = {
            'Street1': [''] * len(df),
            'Street2': [''] * len(df),
            'City': [''] * len(df),
            'State': ['Unknown'] * len(df),
            'Postal Code': [''] * len(df),
            'Country': [''] * len(df),
            'Full Address': [''] * len(df)
        }
        result_df = df.copy()
        for k in processed_data.keys():
            result_df[k] = processed_data[k]
        st.session_state['processed_df'] = result_df
        st.success("Geocoding simulated. 'State' column added.")
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
