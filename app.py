import streamlit as st
import pandas as pd
import time
from io import BytesIO
import pydeck as pdk

from api_client import get_client
from utils import (
    get_api_key_from_env,
    load_file,
    find_coordinate_columns,
    validate_coordinates,
    prepare_output_dataframe,
    initialize_processed_data,
    get_error_record,
    get_coordinate_error_record,
    generate_unique_filename,
    validate_coordinate_values,
    calculate_total_processing_time,
)

# Page config
st.set_page_config(
    page_title="🗺️ Geocoding Dashboard",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS (your existing styles)
st.markdown("""
<style>
...
</style>
""", unsafe_allow_html=True)

st.title("🗺️ Geocoding & Address Extraction Dashboard")
st.markdown(
    "Convert latitude/longitude coordinates to detailed addresses using LocationIQ, Google Maps, or OpenStreetMap"
)

# Initialize session state
for key in ["df", "processed_df", "logs", "api_client", "api_provider"]:
    if key not in st.session_state:
        st.session_state[key] = None if key != "logs" else []

# SIDEBAR CONFIG
st.sidebar.header("⚙️ Configuration")
api_provider = st.sidebar.radio(
    "🗺️ Select Geocoding Provider",
    options=["LocationIQ", "Google Maps", "OpenStreetMap (Nominatim)"],
)
st.session_state.api_provider = api_provider
env_api_key = get_api_key_from_env(api_provider)
api_key = None

if api_provider in ["LocationIQ", "Google Maps"]:
    if env_api_key:
        st.sidebar.success(f"✅ {api_provider} API key loaded from environment")
        api_key = env_api_key
    else:
        api_key = st.sidebar.text_input(f"🔑 Enter your {api_provider} API Key", type="password")
        if not api_key:
            st.sidebar.warning("⚠️ API key required")
st.session_state.api_client = get_client(api_provider, api_key) if api_key or api_provider == "OpenStreetMap (Nominatim)" else None

# File upload
st.sidebar.header("📤 Upload File")
uploaded_file = st.sidebar.file_uploader("Upload Excel or CSV file", type=["xlsx", "csv"])

# MAIN CONTENT
if uploaded_file:
    df, sheets, selected_sheet = load_file(uploaded_file)
    st.session_state.df = df

    st.markdown("### 🔍 Available Columns")
    st.write(df.columns.tolist())

    # Auto-detect coordinate columns
    lat_col, lon_col = find_coordinate_columns(df)
    col1, col2, col3 = st.columns(3)
    with col1:
        lat_col = st.selectbox("Select Latitude Column", df.columns, index=list(df.columns).index(lat_col))
    with col2:
        lon_col = st.selectbox("Select Longitude Column", df.columns, index=list(df.columns).index(lon_col))
    with col3:
        id_col = st.selectbox("Select Unique ID Column", [c for c in df.columns if c not in [lat_col, lon_col]])

    st.markdown("### 📋 Data Preview")
    st.dataframe(df[[id_col, lat_col, lon_col]].head(5))

    # PROCESSING
    if st.button("🚀 Start Geocoding"):
        valid_coords = validate_coordinates(df, lat_col, lon_col)
        st.success(f"✅ Found {valid_coords} valid coordinates")
        st.session_state.logs = []
        processed_data = initialize_processed_data()

        def log_message(msg):
            st.session_state.logs.append(msg)
            st.empty().markdown("<br>".join(st.session_state.logs[-20:]), unsafe_allow_html=True)

        for idx, (i, row) in enumerate(df.iterrows()):
            lat = row[lat_col]
            lon = row[lon_col]
            is_valid, coord_status = validate_coordinate_values(lat, lon)
            if not is_valid:
                rec = get_coordinate_error_record(coord_status)
            else:
                rec = st.session_state.api_client.reverse_geocode(lat, lon, log_message) or get_error_record()
            # Append to processed_data
            for k in processed_data:
                processed_data[k].append(rec.get(k, '') if isinstance(rec, dict) else rec[k])
            time.sleep(st.session_state.api_client.RATE_LIMIT)

        # Build processed DataFrame
        result_df = prepare_output_dataframe(df, processed_data, id_col, lat_col, lon_col)
        st.session_state.processed_df = result_df
        st.success(f"🎉 Geocoding complete! {len(result_df)} records processed.")

    # DISPLAY RESULTS
    if st.session_state.processed_df is not None:
        st.markdown("---")
        st.markdown("### 📊 Results")

        # Filter before download
        st.markdown("#### Filter Results")
        processed_df = st.session_state.processed_df.copy()
        states = processed_df['State'].unique().tolist()
        selected_states = st.multiselect("Filter by State", options=states, default=states)
        filtered_df = processed_df[processed_df['State'].isin(selected_states)]

        st.dataframe(filtered_df, height=300)

        # DOWNLOAD BUTTONS
        col1, col2 = st.columns(2)
        with col1:
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                filtered_df.to_excel(writer, index=False, sheet_name="Geocoded Data")
            excel_buffer.seek(0)
            st.download_button("📥 Download Excel", data=excel_buffer, file_name="geocoded_filtered.xlsx")
        with col2:
            csv_data = filtered_df.to_csv(index=False)
            st.download_button("📥 Download CSV", data=csv_data, file_name="geocoded_filtered.csv")

        # INTERACTIVE MAP
        st.markdown("### 🗺️ Geocoded Map")
        if not filtered_df.empty:
            filtered_df['lat'] = filtered_df[lat_col].astype(float)
            filtered_df['lon'] = filtered_df[lon_col].astype(float)
            # Prepare tooltip
            filtered_df['tooltip'] = filtered_df.apply(
                lambda x: f"ID: {x[id_col]}<br>City: {x['City']}<br>State: {x['State']}<br>Full Address: {x['Full Address']}", axis=1
            )

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=filtered_df,
                get_position='[lon, lat]',
                get_fill_color='[0, 128, 255, 160]',
                get_radius=200,
                pickable=True,
            )

            tooltip = {"html": "{tooltip}", "style": {"color": "white"}}

            view_state = pdk.ViewState(
                latitude=filtered_df['lat'].mean(),
                longitude=filtered_df['lon'].mean(),
                zoom=5,
                pitch=0
            )

            r = pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                tooltip=tooltip
            )
            st.pydeck_chart(r)
        else:
            st.info("No data to display on the map.")
else:
    st.info("👈 Please upload an Excel or CSV file to get started")
