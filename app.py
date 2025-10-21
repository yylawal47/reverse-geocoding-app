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
st.markdown("A smart, interactive dashboard for monitoring vehicle movement and reverse geocoding locations.")

# Dark / Light theme toggle
theme = st.radio("🌓 Choose Theme", ["Light Mode", "Dark Mode"], horizontal=True)
if theme == "Dark Mode":
    st.markdown(
        """
        <style>
        body, .stApp {background-color: #0e1117; color: #e0e0e0;}
        .stButton>button {background-color: #262730; color: white; border-radius: 10px;}
        .stSelectbox, .stTextInput, .stMultiSelect {background-color: #262730 !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ============================================
# FILE UPLOAD
# ============================================
st.sidebar.header("📂 Upload Vehicle Data File")
uploaded_file = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"])

# ============================================
# GEOCODING PROVIDER SELECTION
# ============================================
api_option = st.sidebar.selectbox(
    "🌍 Choose Geocoding Provider",
    ["Nominatim (Free)", "OpenCage", "Google Maps"]
)
api_key = ""
if api_option in ["OpenCage", "Google Maps"]:
    api_key = st.sidebar.text_input("🔑 Enter API Key")

# ============================================
# GEOCODING FUNCTION WITH CACHE
# ============================================
@st.cache_data(show_spinner=False)
def geocode_location(lat, lon, provider="Nominatim (Free)", key=None):
    if pd.isna(lat) or pd.isna(lon):
        return {"State": "Unavailable", "City": "Unavailable", "Postal": "Unavailable"}

    try:
        if provider == "Nominatim (Free)":
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
            res = requests.get(url, headers={'User-Agent': 'FleetApp'}).json()
            address = res.get("address", {})
            sleep(0.85)
            return {
                "State": address.get("state", "Unavailable"),
                "City": address.get("city", address.get("town", "Unavailable")),
                "Postal": address.get("postcode", "Unavailable")
            }

        elif provider == "OpenCage" and key:
            url = f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}&key={key}"
            res = requests.get(url).json()
            if res["results"]:
                comp = res["results"][0]["components"]
                return {
                    "State": comp.get("state", "Unavailable"),
                    "City": comp.get("city", comp.get("town", "Unavailable")),
                    "Postal": comp.get("postcode", "Unavailable")
                }
            return {"State": "Unavailable", "City": "Unavailable", "Postal": "Unavailable"}

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
            return {"State": "Unavailable", "City": "Unavailable", "Postal": "Unavailable"}

    except:
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

    geo_data = df.apply(lambda r: geocode_location(r[lat_col], r[lon_col], api_option, api_key), axis=1)
    geo_df = pd.DataFrame(list(geo_data))
    df = pd.concat([df, geo_df], axis=1)

    # Status and Last Report
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    now = datetime.now()
    df["Days_Since_Last_Report"] = (now - df.groupby(truck_col)[date_col].transform("max")).dt.days
    df["Status"] = df["Days_Since_Last_Report"].apply(lambda d: "Reporting" if d <= 1 else "Not Reporting")

    # ============================================
    # FILTERING
    # ============================================
    st.sidebar.header("🔍 Filter Options")
    unique_states = sorted(df["State"].unique())
    selected_states = st.sidebar.multiselect("Filter by State", unique_states, default=unique_states)
    df_filtered = df[df["State"].isin(selected_states)]

    # ============================================
    # SUMMARY & CHART
    # ============================================
    st.subheader("📊 Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Trucks", len(df))
    c2.metric("Reporting", (df["Status"] == "Reporting").sum())
    c3.metric("Not Reporting", (df["Status"] == "Not Reporting").sum())

    st.markdown("### 🚚 Trucks by State")
    counts = df_filtered["State"].value_counts().reset_index()
    counts.columns = ["State", "Count"]
    st.bar_chart(data=counts.set_index("State"))

    # ============================================
    # MAP VIEW (with Clustering)
    # ============================================
    st.markdown("---")
    st.subheader("🗺️ Map View")

    valid_coords = df_filtered.dropna(subset=[lat_col, lon_col])
    if len(valid_coords) > 0:
        avg_lat, avg_lon = valid_coords[lat_col].mean(), valid_coords[lon_col].mean()
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=6, tiles="CartoDB positron")

        marker_cluster = MarkerCluster().add_to(m)

        def color(status):
            return "green" if status == "Reporting" else "red"

        for _, row in valid_coords.iterrows():
            popup_html = f"""
                <b>Truck:</b> {row[truck_col]}<br>
                <b>State:</b> {row['State']}<br>
                <b>City:</b> {row['City']}<br>
                <b>Postal:</b> {row['Postal']}<br>
                <b>Status:</b> {row['Status']}<br>
                <b>Days Since Last Report:</b> {row['Days_Since_Last_Report']}
            """
            folium.CircleMarker(
                [row[lat_col], row[lon_col]],
                radius=6,
                color=color(row["Status"]),
                fill=True,
                fill_color=color(row["Status"]),
                popup=folium.Popup(popup_html, max_width=250)
            ).add_to(marker_cluster)

        st_folium(m, width=1000, height=550)
        st.caption("🟢 Reporting | 🔴 Not Reporting | ⚪ Unavailable")
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
