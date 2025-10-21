import streamlit as st
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="🗺️ Tanker Map Dashboard", layout="wide")
st.title("🛢️ Tanker Map Dashboard")

uploaded_file = st.file_uploader("Upload Excel or CSV", type=["xlsx", "csv"])
if uploaded_file:
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.subheader("📊 File Preview")
    st.dataframe(df.head())

    # Auto-detect latitude/longitude
    lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)

    if not lat_col or not lon_col:
        st.error("Could not detect latitude/longitude columns automatically.")
    else:
        st.subheader("🗺️ Map Options")
        show_map = st.checkbox("Show points on map")
        use_icons = st.checkbox("Use tanker icons", value=True)

        if show_map:
            df_map = df.dropna(subset=[lat_col, lon_col])
            if not df_map.empty:
                if use_icons:
                    # Add icon info
                    df_map["icon_data"] = {
                        "url": "https://img.icons8.com/fluency/48/tanker.png",
                        "width": 48,
                        "height": 48,
                        "anchorY": 24
                    }
                    layer = pdk.Layer(
                        "IconLayer",
                        data=df_map,
                        get_icon="icon_data",
                        get_size=4,
                        size_scale=15,
                        get_position=[lon_col, lat_col],
                        pickable=True
                    )
                else:
                    # ScatterplotLayer
                    layer = pdk.Layer(
                        "ScatterplotLayer",
                        data=df_map,
                        get_position=[lon_col, lat_col],
                        get_radius=500,
                        get_fill_color=[255, 0, 0],
                        pickable=True
                    )

                tooltip = {
                    "html": "<b>Info:</b><br>" + "<br>".join([f"{c}: {{{c}}}" for c in df_map.columns]),
                    "style": {"backgroundColor": "white", "color": "black", "fontSize": "12px"}
                }

                st.pydeck_chart(pdk.Deck(
                    layers=[layer],
                    initial_view_state=pdk.ViewState(
                        latitude=df_map[lat_col].mean(),
                        longitude=df_map[lon_col].mean(),
                        zoom=6,
                        pitch=0,
                    ),
                    tooltip=tooltip
                ))
            else:
                st.warning("No valid coordinates to display.")

        # Optional geocoding simulation
        st.subheader("🚀 Optional Geocoding")
        if st.button("Run Optional Geocoding"):
            result_df = df.copy()
            result_df['State'] = 'Unknown'  # placeholder for geocoding
            st.dataframe(result_df.head())

            # Download
            st.download_button("📥 Download Geocoded CSV", result_df.to_csv(index=False), file_name="geocoded.csv")

            # Summary by State
            st.subheader("📊 Summary by State")
            summary_df = result_df.groupby('State')[lat_col].count().reset_index()
            summary_df.rename(columns={lat_col: 'Count'}, inplace=True)
            st.dataframe(summary_df)
