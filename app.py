import streamlit as st
import pandas as pd
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime
from io import BytesIO
import base64
from time import sleep

# ============================================
# APP CONFIGURATION
# ============================================
st.set_page_config(page_title="Fleet Geolocation Dashboard", layout="wide")
st.title("🚛 Fleet Geolocation Dashboard")
st.markdown("Monitor your fleet, decode addresses, visualize on a map, and analyze reports.")

# Theme toggle
theme = st.radio("🌓 Choose Theme", ["Light Mode", "Dark Mode"], horizontal=True)
if theme == "Dark Mode":
    st.markdown("""
    <style>
    body, .stApp {background-color: #0e1117; color: #e0e0e0;}
    .stButton>button {background-color: #262730; color: white; border-radius: 10px;}
    .stSelectbox, .stTextInput, .stMultiSelect {background-color: #262730 !important;}
    </style>
    """, unsafe_allow_html=True)

# ============================================
# FILE UPLOAD
# ============================================
st.sidebar.header("📂 Upload Vehicle Data File")
uploaded_file = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"])

# ============================================
# GEOCODING PROVIDER SELECTION
# ============================================
api_option = st.sidebar.selectbox("🌍 Geocoding Provider", ["Nominatim (Free)", "OpenCage", "Google Maps"])
api_key = ""
if api_option in ["OpenCage", "Google Maps"]:
    api_key = st.sidebar.text_input("🔑 Enter API Key")

# ============================================
# CACHE ANALYTICS
# ============================================
cache_stats = {"calls_made": 0, "cache_hits": 0}

# ============================================
# GEOCODING FUNCTION WITH CACHE
# ============================================
@st.cache_data(show_spinner=False)
def geocode_location(lat, lon, provider="Nominatim (Free)", key=None):
    if pd.isna(lat) or pd.isna(lon):
        return {"State": "Unavailable", "City": "Unavailable", "Postal": "Unavailable"}
    try:
        if provider == "Nominatim (Free)":
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1"
            res = requests.get(url, headers={'User-Agent': 'FleetApp'}, timeout=15).json()
            address = res.get("address", {})
            sleep(0.85)
            return {
                "State": address.get("state") or address.get("region") or address.get("county") or "Unavailable",
                "City": address.get("city") or address.get("town") or address.get("village") or "Unavailable",
                "Postal": address.get("postcode", "Unavailable")
            }
        elif provider == "OpenCage" and key:
            url = f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}&key={key}"
            res = requests.get(url).json()
            if res["results"]:
                comp = res["results"][0]["components"]
                return {
                    "State": comp.get("state", "Unavailable"),
                    "City": comp.get("city", comp.get("town", comp.get("village", "Unavailable"))),
                    "Postal": comp.get("postcode", "Unavailable")
                }
        elif provider == "Google Maps" and key:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={key}"
            res = requests.get(url).json()
            if res["results"]:
                comps = res["results"][0]["address_components"]
                state = city = postal = "Unavailable"
                for c in comps:
                    if "administrative_area_level_1" in c["types"]:
                        state = c["long_name"]
                    elif "locality" in c["types"]:
                        city = c["long_name"]
                    elif "postal_code" in c["types"]:
                        postal = c["long_name"]
                return {"State": state, "City": city, "Postal": postal}
    except:
        pass
    return {"State": "Unavailable", "City": "Unavailable", "Postal": "Unavailable"}

# ============================================
# MAIN PROCESSING
# ============================================
if uploaded_file:
    df = pd.read_excel(uploaded_file)
    st.sidebar.markdown("### 🧭 Column Mapping")

    truck_col = st.sidebar.selectbox("Truck Column", df.columns)
    lat_col = st.sidebar.selectbox("Latitude Column", df.columns)
    lon_col = st.sidebar.selectbox("Longitude Column", df.columns)
    date_col = st.sidebar.selectbox("Date Column", df.columns)

    st.info("Processing geocoding... please wait if many coordinates are present.")

    # Track unique coordinates
    coords = df[[lat_col, lon_col]].dropna().drop_duplicates()
    total_unique_coords = len(coords)

    # Apply geocoding with cache tracking
    results = []
    for _, row in df.iterrows():
        lat, lon = row[lat_col], row[lon_col]
        key_tuple = (lat, lon)

        # Check session cache
        cached = st.session_state.get("geo_cache", {})
        if key_tuple in cached:
            cache_stats["cache_hits"] += 1
            results.append(cached[key_tuple])
        else:
            loc = geocode_location(lat, lon, api_option, api_key)
            results.append(loc)
            cached[key_tuple] = loc
            st.session_state["geo_cache"] = cached
            cache_stats["calls_made"] += 1

    geo_df = pd.DataFrame(results)
    df = pd.concat([df, geo_df], axis=1)

    # Status & Days Since Last Report
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    now = datetime.now()
    df["Days_Since_Last_Report"] = (now - df.groupby(truck_col)[date_col].transform("max")).dt.days
    df["Status"] = df["Days_Since_Last_Report"].apply(lambda d: "Reporting" if d <= 1 else "Not Reporting")

    # ============================================
    # ANALYTICS
    # ============================================
    st.markdown("## 📈 Analytics Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Rows", len(df))
    c2.metric("Unique Coordinates", total_unique_coords)
    c3.metric("API Calls Made", cache_stats["calls_made"])
    c4.metric("API Calls Saved (Cache Hits)", cache_stats["cache_hits"])

    # ============================================
    # FILTERING
    # ============================================
    st.sidebar.header("🔍 Filter Options")
    unique_states = sorted(df["State"].unique())
    selected_states = st.sidebar.multiselect("Filter by State", unique_states, default=unique_states)
    df_filtered = df[df["State"].isin(selected_states)]

    # ============================================
    # CHARTS
    # ============================================
    st.markdown("### 🚚 Trucks by State")
    counts = df_filtered["State"].value_counts().reset_index()
    counts.columns = ["State", "Count"]
    st.bar_chart(data=counts.set_index("State"))

    # ============================================
    # MAP VIEW (CLEAN POPUPS)
    # ============================================
    st.markdown("---")
    st.markdown("### 🗺️ Fleet Map View (Clean Popups)")

    valid_coords = df_filtered.dropna(subset=[lat_col, lon_col])
    if len(valid_coords) > 0:
        avg_lat, avg_lon = valid_coords[lat_col].mean(), valid_coords[lon_col].mean()
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=6, tiles="CartoDB positron")
        cluster = MarkerCluster().add_to(m)

        for _, row in valid_coords.iterrows():
            popup_html = f"""
                <b>Truck:</b> {row[truck_col]}<br>
                <b>State:</b> {row['State']}<br>
                <b>City:</b> {row['City']}<br>
                <b>Postal:</b> {row['Postal']}
            """
            folium.CircleMarker(
                [row[lat_col], row[lon_col]],
                radius=6,
                color="blue",
                fill=True,
                fill_color="blue",
                popup=folium.Popup(popup_html, max_width=250)
            ).add_to(cluster)

        st_folium(m, width=1000, height=550)
        st.caption("Map shows only Truck Name + decoded address")
    else:
        st.warning("No coordinates available for map view.")

    # ============================================
    # EXPORT FILTERED DATA
    # ============================================
    st.markdown("---")
    st.subheader("📁 Export Filtered Results")

    buffer = BytesIO()
    df_filtered.to_excel(buffer, index=False)
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode()
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="Filtered_Vehicles.xlsx">📥 Download Filtered Excel</a>'
    st.markdown(href, unsafe_allow_html=True)

else:
    st.info("👆 Upload an Excel file to begin.")
