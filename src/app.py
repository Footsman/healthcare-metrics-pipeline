"""Nursing home staffing dashboard. Reads the gold layer only."""
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

LAKE = Path(__file__).resolve().parents[1] / "lake"
QTR  = "2024Q2"

INK, MUTED, ACCENT, GRID = "#1a1a1a", "#6b7280", "#2f6fb0", "#e5e7eb"

st.set_page_config(page_title="Nursing Home Staffing", layout="wide")


@st.cache_data
def load_quarter() -> pd.DataFrame:
    return pd.read_parquet(LAKE / "gold" / "metrics_facility_quarter" / f"cy_qtr={QTR}"
                           / "metrics_facility_quarter.parquet")


@st.cache_data
def load_month() -> pd.DataFrame:
    return pd.read_parquet(LAKE / "gold" / "metrics_facility_month" / f"cy_qtr={QTR}"
                           / "metrics_facility_month.parquet")


def style(fig, height=420):
    fig.update_layout(
        height=height, template="simple_white",
        margin=dict(l=10, r=10, t=56, b=10),
        title=dict(font=dict(size=16, color=INK), x=0, xanchor="left"),
        font=dict(color=MUTED, size=12), hoverlabel=dict(font_size=12))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


q_all = load_quarter()
mo    = load_month()

st.title("Nursing home staffing, Q2 2024")
st.caption("CMS Payroll-Based Journal · 14,564 facilities · 1 April to 30 June 2024")

with st.sidebar:
    st.header("Filters")
    show_all = st.toggle("Include non-reporting facilities", value=False,
                         help="93 facilities report implausibly low or no hours. "
                              "Excluded by default so rankings reflect real staffing.")
    states = sorted(q_all.state.dropna().unique())
    picked = st.multiselect("States", states, default=[])
    owners = sorted(q_all.ownership_type.dropna().unique())
    picked_own = st.multiselect("Ownership", owners, default=[])

q = q_all if show_all else q_all[q_all.reporting_complete]
if picked:     q = q[q.state.isin(picked)]
if picked_own: q = q[q.ownership_type.isin(picked_own)]

if q.empty:
    st.warning("No facilities match these filters.")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(
    ["National overview", "Staffing vs occupancy", "Facility ranking", "Weekend & contract"])

# ---------------------------------------------------------------- overview
with tab1:
    c = st.columns(4)
    # every figure here is sum-over-sum; averaging facility percentages would mislead
    c[0].metric("Facilities", f"{len(q):,}")
    c[1].metric("Hours per resident day",
                f"{q.direct_hours.sum() / q.resident_days.sum():.2f}")
    c[2].metric("Facility-days with no RN",
                f"{q.days_no_rn.sum() / q.days_reported.sum() * 100:.1f}%")
    c[3].metric("Contract share of hours",
                f"{q.direct_hours_ctr.sum() / q.direct_hours.sum() * 100:.1f}%",
                help="Share of all direct-care hours. The median facility uses far less; "
                     "agency use is concentrated.")

    by_state = (q.groupby("state")
                  .agg(hours=("direct_hours", "sum"), rdays=("resident_days", "sum"),
                       facilities=("ccn", "size")).reset_index())
    by_state["hprd"] = (by_state.hours / by_state.rdays).round(3)

    fig = px.choropleth(by_state, locations="state", locationmode="USA-states",
                        color="hprd", scope="usa", color_continuous_scale="Blues",
                        hover_data={"facilities": True, "hprd": ":.2f"},
                        labels={"hprd": "HPRD"})
    fig.update_layout(title="Staffing varies nearly twofold across states",
                      coloraxis_colorbar=dict(title="HPRD"))
    st.plotly_chart(style(fig, 480), use_container_width=True)

    worst = by_state.nsmallest(10, "hprd").sort_values("hprd")
    fig2 = px.bar(worst, x="hprd", y="state", orientation="h",
                  text=worst.hprd.round(2), color_discrete_sequence=[ACCENT])
    fig2.update_layout(title="Ten states with the lowest staffing",
                       xaxis_title="Hours per resident day", yaxis_title=None)
    fig2.update_traces(textposition="outside")
    st.plotly_chart(style(fig2, 420), use_container_width=True)

# ---------------------------------------------------- staffing vs occupancy
with tab2:
    s = q.dropna(subset=["occupancy", "hprd_total"])
    s = s[s.occupancy.between(0, 1.5)]

    # HPRD divides by census and occupancy multiplies by it, so correlating the two
    # directly has structure built in. Total hours against resident-days is the honest test.
    r_hprd  = s.occupancy.corr(s.hprd_total)
    r_hours = s.direct_hours.corr(s.resident_days)

    c = st.columns(3)
    c[0].metric("Total hours vs resident-days", f"{r_hours:+.2f}",
                help="Facility level. Near 1 means staffing scales with resident count.")
    c[1].metric("HPRD vs occupancy", f"{r_hprd:+.3f}",
                help="Near zero because hours per resident is already census-normalised.")
    c[2].metric("Facilities compared", f"{len(s):,}")

    d = s.copy()
    d["decile"] = pd.qcut(d.occupancy, 10, labels=False) + 1
    by_dec = (d.groupby("decile")
                .apply(lambda x: pd.Series({
                    "occupancy": x.occupancy.median(),
                    "hprd": x.direct_hours.sum() / x.resident_days.sum()}),
                        include_groups=False)
                .reset_index())

    fig = px.line(by_dec, x="occupancy", y="hprd", markers=True,
                  color_discrete_sequence=[ACCENT])
    spread = by_dec.hprd.iloc[-1] - by_dec.hprd.iloc[0]
    fig.update_layout(
        title=f"Twice as full, {spread / by_dec.hprd.iloc[0] * 100:.0f}% more care per resident",
        xaxis_title="Occupancy (census / certified beds), decile median",
        yaxis_title="Hours per resident day")
    fig.update_traces(line=dict(width=2), marker=dict(size=9))
    fig.update_yaxes(range=[0, 4.2])
    st.plotly_chart(style(fig, 430), use_container_width=True)
    st.caption("Each point is a decile of facilities ordered by occupancy, roughly 1,450 each. "
               "HPRD is computed sum-over-sum within each decile.")

    fig2 = px.scatter(s, x="resident_days", y="direct_hours", opacity=0.18,
                      color_discrete_sequence=[ACCENT],
                      hover_data={"provider_name": True, "state": True})
    fig2.update_layout(title=f"Staffing tracks resident count almost exactly (r = {r_hours:+.2f})",
                       xaxis_title="Resident-days in the quarter",
                       yaxis_title="Direct-care hours in the quarter")
    fig2.update_traces(marker=dict(size=4))
    st.plotly_chart(style(fig2, 460), use_container_width=True)

# -------------------------------------------------------- facility ranking
with tab3:
    st.subheader("Lowest staffing relative to resident load")
    cols = ["ccn", "provider_name", "state", "ownership_type", "hprd_total",
            "pct_days_no_rn", "contract_share_pct", "weekend_gap_pct",
            "occupancy", "certified_beds", "overall_rating", "readmit_adjusted"]
    st.dataframe(q.nsmallest(50, "hprd_total")[cols], use_container_width=True,
                 hide_index=True, height=560)
    st.caption(f"{len(q):,} facilities after filters. "
               f"{'Including' if show_all else 'Excluding'} non-reporters.")

# ------------------------------------------------------ weekend & contract
with tab4:
    w = q.dropna(subset=["weekend_gap_pct"])
    by_state_w = w.groupby("state").weekend_gap_pct.median().reset_index()

    fig = px.choropleth(by_state_w, locations="state", locationmode="USA-states",
                        color="weekend_gap_pct", scope="usa",
                        color_continuous_scale="Blues", labels={"weekend_gap_pct": "% drop"})
    fig.update_layout(title=f"The median facility loses {w.weekend_gap_pct.median():.0f}% of its staffing at weekends",
                      coloraxis_colorbar=dict(title="% drop"))
    st.plotly_chart(style(fig, 460), use_container_width=True)

    fig2 = px.histogram(q, x="contract_share_pct", nbins=60,
                        color_discrete_sequence=[ACCENT])
    fig2.update_layout(
        title=f"Most facilities use no agency staff, but {(q.contract_share_pct > 25).mean()*100:.0f}% rely on it for a quarter of hours",
        xaxis_title="Contract share of direct-care hours (%)", yaxis_title="Facilities")
    st.plotly_chart(style(fig2, 400), use_container_width=True)