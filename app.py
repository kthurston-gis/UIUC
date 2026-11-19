import os
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

MAPBOX_API_KEY = os.getenv("MAPBOX_API_KEY", "")

st.set_page_config(
    page_title="Coal Facility Inspection Analytics Dashboard",
    layout="wide",
)

# ----------------------------
# Visual polish
# ----------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #f7faf9; }
    section[data-testid="stSidebar"] { background-color: #eef6f3; }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label { color: #123c3a; }
    div[data-baseweb="tag"] {
        background-color: #2e8b7d !important;
        color: white !important;
        border-radius: 6px !important;
    }
    div[data-testid="stMetric"] {
        background-color: white;
        border: 1px solid #d8e7e2;
        border-radius: 12px;
        padding: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Coal Facility Inspection Analytics Dashboard")
st.markdown(
    "Prototype analytical workflow for reviewing asset inventory, inspection findings, "
    "condition trends, data gaps, and map-based finding patterns across mock coal facility sites."
)

# ----------------------------
# Load Data
# ----------------------------
@st.cache_data
def load_data():
    base_dir = Path(__file__).parent if "__file__" in globals() else Path.cwd()
    assets_path = base_dir / "mock_coal_assets_facility_boundaries.csv"
    findings_path = base_dir / "mock_coal_findings_facility_boundaries.csv"

    if not assets_path.exists() or not findings_path.exists():
        st.error(
            "Could not find mock_coal_assets_facility_boundaries.csv and mock_coal_findings_facility_boundaries.csv. "
            "Place both files in the same folder as this Streamlit app."
        )
        st.stop()

    assets = pd.read_csv(assets_path)
    findings = pd.read_csv(findings_path)

    assets["latest_inspection_date"] = pd.to_datetime(assets["latest_inspection_date"], errors="coerce")
    findings["inspection_date"] = pd.to_datetime(findings["inspection_date"], errors="coerce")

    findings["month"] = findings["inspection_date"].dt.to_period("M").astype(str)
    findings["year"] = findings["inspection_date"].dt.year

    return assets, findings

assets_df, findings_df = load_data()

# ----------------------------
# Sidebar Filters
# ----------------------------
st.sidebar.header("Filters")

site_options = sorted(assets_df["facility_site"].dropna().unique().tolist())
facility_options = sorted(assets_df["facility_id"].dropna().unique().tolist())
asset_type_options = sorted(assets_df["asset_type"].dropna().unique().tolist())
condition_options = [c for c in ["Good", "Fair", "Poor", "Critical"] if c in findings_df["condition_score"].unique()]
priority_options = [p for p in ["Low", "Medium", "High"] if p in findings_df["priority_level"].unique()]
repair_status_options = sorted(findings_df["repair_status"].dropna().unique().tolist())

selected_sites = st.sidebar.multiselect("Facility Site", site_options, default=site_options)
selected_facilities = st.sidebar.multiselect("Facility ID", facility_options, default=facility_options)
selected_asset_types = st.sidebar.multiselect("Asset Type", asset_type_options, default=asset_type_options)
selected_conditions = st.sidebar.multiselect("Condition Score", condition_options, default=condition_options)
selected_priorities = st.sidebar.multiselect("Priority Level", priority_options, default=priority_options)
selected_repair_statuses = st.sidebar.multiselect("Repair Status", repair_status_options, default=repair_status_options)

min_date = findings_df["inspection_date"].min()
max_date = findings_df["inspection_date"].max()
selected_dates = st.sidebar.date_input(
    "Inspection Date Range",
    value=(min_date.date(), max_date.date()),
)

if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date, end_date = min_date.date(), max_date.date()

# ----------------------------
# Apply Filters
# ----------------------------
filtered_assets = assets_df[
    assets_df["facility_site"].isin(selected_sites)
    & assets_df["facility_id"].isin(selected_facilities)
    & assets_df["asset_type"].isin(selected_asset_types)
].copy()

filtered_findings = findings_df[
    findings_df["facility_site"].isin(selected_sites)
    & findings_df["facility_id"].isin(selected_facilities)
    & findings_df["asset_type"].isin(selected_asset_types)
    & findings_df["condition_score"].isin(selected_conditions)
    & findings_df["priority_level"].isin(selected_priorities)
    & findings_df["repair_status"].isin(selected_repair_statuses)
    & (findings_df["inspection_date"].dt.date >= start_date)
    & (findings_df["inspection_date"].dt.date <= end_date)
].copy()

asset_ids_with_visible_findings = set(filtered_findings["asset_id"].unique())
filtered_assets_for_map = filtered_assets[
    filtered_assets["asset_id"].isin(asset_ids_with_visible_findings) | filtered_findings.empty
].copy()

if filtered_assets.empty:
    st.warning("No assets match the current filters.")
    st.stop()

# ----------------------------
# Summary Metrics
# ----------------------------
st.subheader("Summary Metrics")

high_priority_pct = (filtered_findings["priority_level"].eq("High").mean() * 100) if len(filtered_findings) else 0
open_repair_pct = (filtered_findings["repair_status"].isin(["Not Started", "In Progress"]).mean() * 100) if len(filtered_findings) else 0
critical_assets = filtered_assets[filtered_assets["worst_condition_score"].eq("Critical")]["asset_id"].nunique()

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Assets", f"{filtered_assets['asset_id'].nunique():,}")
col2.metric("Findings", f"{len(filtered_findings):,}")
col3.metric("Critical Assets", f"{critical_assets:,}")
col4.metric("High Priority Findings", f"{high_priority_pct:.1f}%")
col5.metric("Open Repairs", f"{open_repair_pct:.1f}%")

# ----------------------------
# Data Quality Snapshot
# ----------------------------
st.subheader("Data Quality Snapshot")

dq = pd.DataFrame(
    [
        {"Check": "Assets missing coordinates", "Count": int(filtered_assets[["latitude", "longitude"]].isna().any(axis=1).sum())},
        {"Check": "Findings missing coordinates", "Count": int(filtered_findings[["finding_latitude", "finding_longitude"]].isna().any(axis=1).sum())},
        {"Check": "Findings missing inspection date", "Count": int(filtered_findings["inspection_date"].isna().sum())},
        {"Check": "Findings missing condition score", "Count": int(filtered_findings["condition_score"].isna().sum())},
        {"Check": "Findings missing priority level", "Count": int(filtered_findings["priority_level"].isna().sum())},
        {"Check": "Assets with no visible findings under filters", "Count": int(filtered_assets[~filtered_assets["asset_id"].isin(asset_ids_with_visible_findings)]["asset_id"].nunique())},
    ]
)
st.dataframe(dq, use_container_width=True, height=245)

if filtered_findings.empty:
    st.warning("No findings match the current filters. Try widening the date range or selecting more categories.")
    st.stop()

# ----------------------------
# Charts
# ----------------------------
st.subheader("Inspection Finding Patterns")

blue_green_scale = alt.Scale(range=["#d9f0e7", "#8bd3c7", "#3b9c8f", "#176d7a", "#0b3d5c"])

col_left, col_right = st.columns(2)

with col_left:
    findings_by_asset_type = (
        filtered_findings.groupby("asset_type", as_index=False)
        .agg(findings=("finding_id", "count"))
        .sort_values("findings", ascending=False)
    )
    chart = (
        alt.Chart(findings_by_asset_type)
        .mark_bar(color="#176d7a")
        .encode(
            x=alt.X("findings:Q", title="Finding Count"),
            y=alt.Y("asset_type:N", title="Asset Type", sort="-x"),
            tooltip=["asset_type", "findings"],
        )
        .properties(height=330)
    )
    st.altair_chart(chart, use_container_width=True)

with col_right:
    priority_order = ["Low", "Medium", "High"]
    priority_counts = filtered_findings["priority_level"].value_counts().reindex(priority_order).fillna(0).reset_index()
    priority_counts.columns = ["priority_level", "count"]
    chart = (
        alt.Chart(priority_counts)
        .mark_bar(color="#2e8b7d")
        .encode(
            x=alt.X("priority_level:N", title="Priority Level", sort=priority_order),
            y=alt.Y("count:Q", title="Finding Count"),
            tooltip=["priority_level", "count"],
        )
        .properties(height=330)
    )
    st.altair_chart(chart, use_container_width=True)

col_left, col_right = st.columns(2)

with col_left:
    trend_df = (
        filtered_findings.groupby("month", as_index=False)
        .agg(
            findings=("finding_id", "count"),
            high_priority_findings=("priority_level", lambda s: int((s == "High").sum())),
            unique_assets=("asset_id", "nunique"),
        )
        .sort_values("month")
    )
    chart = (
        alt.Chart(trend_df)
        .mark_line(point=True, color="#0b5f73")
        .encode(
            x=alt.X("month:N", title="Month", sort=list(trend_df["month"])),
            y=alt.Y("findings:Q", title="Finding Count"),
            tooltip=["month", "findings", "high_priority_findings", "unique_assets"],
        )
        .properties(height=330)
    )
    st.altair_chart(chart, use_container_width=True)

with col_right:
    facility_summary = (
        filtered_findings.groupby("facility_site", as_index=False)
        .agg(
            findings=("finding_id", "count"),
            unique_assets=("asset_id", "nunique"),
            high_priority_findings=("priority_level", lambda s: int((s == "High").sum())),
        )
        .sort_values("findings", ascending=False)
    )
    chart = (
        alt.Chart(facility_summary)
        .mark_bar(color="#3b9c8f")
        .encode(
            x=alt.X("facility_site:N", title="Facility Site", sort="-y"),
            y=alt.Y("findings:Q", title="Finding Count"),
            tooltip=["facility_site", "findings", "unique_assets", "high_priority_findings"],
        )
        .properties(height=330)
    )
    st.altair_chart(chart, use_container_width=True)

# ----------------------------
# Map
# ----------------------------
st.subheader("Asset and Finding Map")
st.caption("Hollow circles represent parent assets. Triangles represent individual findings associated with those assets.")

condition_color_map = {
    "Good": [92, 184, 146, 220],
    "Fair": [46, 139, 125, 220],
    "Poor": [23, 109, 122, 230],
    "Critical": [11, 61, 92, 240],
}
priority_color_map = {
    "Low": [92, 184, 146, 230],
    "Medium": [23, 109, 122, 240],
    "High": [11, 61, 92, 255],
}

map_assets = filtered_assets_for_map.dropna(subset=["latitude", "longitude"]).copy()
map_findings = filtered_findings.dropna(subset=["finding_latitude", "finding_longitude"]).copy()
map_findings["finding_color"] = map_findings["priority_level"].map(priority_color_map)
map_assets["border_color"] = map_assets["worst_condition_score"].map(condition_color_map)
map_assets["asset_radius"] = 24

# Build small triangle polygons around each finding point. This renders as a true triangle layer,
# instead of relying on a text symbol that can disappear depending on browser/font rendering.
def make_triangle(lon, lat, size=0.000035):
    return [
        [lon, lat + size],
        [lon - size, lat - size],
        [lon + size, lat - size],
    ]

if not map_findings.empty:
    map_findings["triangle_coords"] = map_findings.apply(
        lambda r: make_triangle(r["finding_longitude"], r["finding_latitude"]), axis=1
    )

if map_assets.empty and map_findings.empty:
    st.info("No mappable assets or findings under the current filters.")
else:
    center_lat = map_findings["finding_latitude"].mean() if not map_findings.empty else map_assets["latitude"].mean()
    center_lon = map_findings["finding_longitude"].mean() if not map_findings.empty else map_assets["longitude"].mean()

    if len(selected_sites) == 1:
        zoom = 14
    elif len(selected_sites) <= 2:
        zoom = 8
    else:
        zoom = 4

    view_state = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)

    # Parent assets: hollow circles, not pickable so the findings tooltip does not show blank placeholders.
    asset_layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_assets,
        get_position="[longitude, latitude]",
        get_radius="asset_radius",
        stroked=True,
        filled=False,
        get_line_color="border_color",
        line_width_min_pixels=2,
        line_width_max_pixels=5,
        pickable=False,
    )

    # Child findings: true filled triangle polygons, pickable for the finding tooltip.
    finding_layer = pdk.Layer(
        "PolygonLayer",
        data=map_findings,
        get_polygon="triangle_coords",
        get_fill_color="finding_color",
        get_line_color=[18, 60, 58, 240],
        line_width_min_pixels=1,
        stroked=True,
        filled=True,
        pickable=True,
    )

    tooltip = {
        "html": """
        <b>Finding:</b> {finding_id}<br/>
        <b>Asset:</b> {asset_id} / {asset_name}<br/>
        <b>Site:</b> {facility_site}<br/>
        <b>Asset Type:</b> {asset_type}<br/>
        <b>Finding Type:</b> {finding_type}<br/>
        <b>Condition:</b> {condition_score}<br/>
        <b>Priority:</b> {priority_level}<br/>
        <b>Repair Status:</b> {repair_status}<br/>
        <b>Cost Bin:</b> {estimated_cost_bin}
        """,
        "style": {"backgroundColor": "#123c3a", "color": "white"},
    }

    deck = pdk.Deck(
        map_style="mapbox://styles/mapbox/satellite-streets-v12" if MAPBOX_API_KEY else None,
        initial_view_state=view_state,
        layers=[asset_layer, finding_layer],
        tooltip=tooltip,
        api_keys={"mapbox": MAPBOX_API_KEY} if MAPBOX_API_KEY else None,
    )

    st.pydeck_chart(deck, use_container_width=True)

# ----------------------------
# Analytical Takeaways
# ----------------------------
st.subheader("Analytical Takeaways")

top_asset_type = findings_by_asset_type.iloc[0]["asset_type"] if not findings_by_asset_type.empty else "N/A"
top_site = facility_summary.iloc[0]["facility_site"] if not facility_summary.empty else "N/A"
most_common_finding = filtered_findings["finding_type"].mode().iloc[0] if not filtered_findings["finding_type"].mode().empty else "N/A"

st.markdown(
    f"""
    - The largest share of visible findings is associated with **{top_asset_type}** assets.
    - The site with the highest visible finding count is **{top_site}**.
    - The most common finding type under the current filters is **{most_common_finding}**.
    - The parent/child structure helps separate asset inventory from inspection findings: assets stay stable as parent records, while findings can be filtered, mapped, and summarized independently.
    """
)

# ----------------------------
# Detailed Tables
# ----------------------------
st.subheader("Filtered Asset Inventory")
asset_display_columns = [
    "asset_id", "asset_name", "facility_site", "facility_id", "asset_type", "latest_inspection_date",
    "inspection_count", "total_findings", "worst_condition_score", "highest_priority_level", "latitude", "longitude"
]
st.dataframe(
    filtered_assets[asset_display_columns].sort_values(["facility_site", "asset_type", "asset_id"]),
    use_container_width=True,
    height=300,
)

st.subheader("Filtered Findings Records")
finding_display_columns = [
    "finding_id", "asset_id", "asset_name", "facility_site", "facility_id", "asset_type", "inspection_date",
    "finding_type", "condition_score", "priority_level", "repair_status", "estimated_cost_bin",
    "finding_latitude", "finding_longitude"
]
st.dataframe(
    filtered_findings[finding_display_columns].sort_values("inspection_date", ascending=False),
    use_container_width=True,
    height=350,
)

# ----------------------------
# Downloads
# ----------------------------
col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        label="Download Filtered Assets CSV",
        data=filtered_assets.to_csv(index=False).encode("utf-8"),
        file_name="filtered_coal_assets.csv",
        mime="text/csv",
    )
with col_b:
    st.download_button(
        label="Download Filtered Findings CSV",
        data=filtered_findings.to_csv(index=False).encode("utf-8"),
        file_name="filtered_coal_findings.csv",
        mime="text/csv",
    )
