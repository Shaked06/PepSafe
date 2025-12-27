"""
Project Pepper - Real-time Walk Monitoring Dashboard

Streamlit dashboard for visualizing Pepper's walk data with
dual-window behavioral spike detection (30s vs 5m).

Run with: streamlit run dashboard/dashboard.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Page configuration
st.set_page_config(
    page_title="Project Pepper - Walk Monitor",
    page_icon="🐕",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for dark theme
st.markdown("""
<style>
    .stMetric {
        background-color: #1e1e1e;
        padding: 15px;
        border-radius: 10px;
    }
    .risk-high { color: #ff4b4b; font-weight: bold; }
    .risk-moderate { color: #ffa500; font-weight: bold; }
    .risk-low { color: #00cc00; font-weight: bold; }
    .spike-indicator {
        font-size: 2em;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)


def compute_risk_score(row: pd.Series) -> float:
    """Compute risk score from enriched ping features."""
    risk = 0.0

    # Get jitter value (prefer 30s for immediate spike detection)
    jitter = row.get("velocity_jitter_30s") or row.get("velocity_jitter_5m") or 0
    volatility = row.get("bearing_volatility_30s") or row.get("bearing_volatility_5m") or 0

    # Velocity Jitter (0-25 points)
    risk += min(25, (jitter / 2.0) * 25)

    # Bearing Volatility (0-25 points)
    risk += min(25, (volatility / 90) * 25)

    # Stop Event (0-10 points)
    if row.get("is_stop_event") and row.get("stop_duration_sec"):
        risk += min(10, (row["stop_duration_sec"] / 180) * 10)

    # Busyness Delta (0-30 points)
    if row.get("busyness_delta"):
        abs_delta = abs(row["busyness_delta"])
        if row["busyness_delta"] > 0:
            risk += min(30, (abs_delta / 40) * 30)
        else:
            risk += min(20, (abs_delta / 40) * 20)

    # Busyness Percentage (0-10 points)
    if row.get("busyness_pct") and row["busyness_pct"] > 70:
        risk += min(10, ((row["busyness_pct"] - 70) / 30) * 10)

    # Spike ratio boost
    if row.get("jitter_ratio") and row["jitter_ratio"] > 1.5:
        risk *= 1.2

    return min(100, max(0, round(risk, 1)))


def generate_demo_data(n_pings: int = 100) -> pd.DataFrame:
    """Generate demo walk data for visualization."""
    import numpy as np
    np.random.seed(42)

    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(seconds=5 * (n_pings - i)) for i in range(n_pings)]

    # Simulate a walk with a reactivity spike in the middle
    spike_start = n_pings // 3
    spike_end = spike_start + 10

    data = []
    for i in range(n_pings):
        is_spike = spike_start <= i < spike_end

        # 30s window features (immediate)
        jitter_30s = np.random.uniform(0.3, 0.8) if not is_spike else np.random.uniform(1.5, 2.5)
        volatility_30s = np.random.uniform(5, 15) if not is_spike else np.random.uniform(40, 80)

        # 5m window features (baseline)
        jitter_5m = np.random.uniform(0.4, 0.7)
        volatility_5m = np.random.uniform(8, 18)

        # Ratios (>1 = spike)
        jitter_ratio = jitter_30s / jitter_5m if jitter_5m > 0 else None
        volatility_ratio = volatility_30s / volatility_5m if volatility_5m > 0 else None

        # Stop event simulation
        is_stop = is_spike and i == spike_start
        stop_duration = 30 if is_stop else None

        # Environmental
        busyness_pct = np.random.uniform(20, 40) if not is_spike else np.random.uniform(50, 75)
        busyness_delta = np.random.uniform(-5, 5) if not is_spike else np.random.uniform(15, 30)

        row = {
            "timestamp": timestamps[i],
            "velocity_jitter_30s": jitter_30s,
            "bearing_volatility_30s": volatility_30s,
            "velocity_jitter_5m": jitter_5m,
            "bearing_volatility_5m": volatility_5m,
            "jitter_ratio": jitter_ratio,
            "volatility_ratio": volatility_ratio,
            "is_stop_event": is_stop,
            "stop_duration_sec": stop_duration,
            "busyness_pct": busyness_pct,
            "busyness_delta": busyness_delta,
            "ping_count_30s": np.random.randint(3, 8),
            "ping_count_5m": np.random.randint(20, 60),
        }
        row["risk_score"] = compute_risk_score(pd.Series(row))
        data.append(row)

    return pd.DataFrame(data)


def create_dual_window_chart(df: pd.DataFrame) -> go.Figure:
    """Create dual-window comparison chart (30s vs 5m)."""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Velocity Jitter (30s vs 5m)", "Bearing Volatility (30s vs 5m)"),
        vertical_spacing=0.12,
    )

    # Jitter comparison
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["velocity_jitter_30s"],
            name="Jitter 30s",
            line=dict(color="#ff6b6b", width=2),
            fill="tozeroy",
            fillcolor="rgba(255, 107, 107, 0.2)",
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["velocity_jitter_5m"],
            name="Jitter 5m (baseline)",
            line=dict(color="#4ecdc4", width=2, dash="dash"),
        ),
        row=1, col=1
    )

    # Volatility comparison
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["bearing_volatility_30s"],
            name="Volatility 30s",
            line=dict(color="#ffa502", width=2),
            fill="tozeroy",
            fillcolor="rgba(255, 165, 2, 0.2)",
        ),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["bearing_volatility_5m"],
            name="Volatility 5m (baseline)",
            line=dict(color="#2ed573", width=2, dash="dash"),
        ),
        row=2, col=1
    )

    fig.update_layout(
        height=500,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=80, b=50),
    )

    return fig


def create_spike_ratio_chart(df: pd.DataFrame) -> go.Figure:
    """Create spike ratio visualization (30s/5m ratios)."""
    fig = go.Figure()

    # Add spike threshold line
    fig.add_hline(y=1.5, line_dash="dash", line_color="red",
                  annotation_text="Spike Threshold (1.5x)")

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["jitter_ratio"],
            name="Jitter Ratio (30s/5m)",
            line=dict(color="#ff6b6b", width=2),
            mode="lines+markers",
            marker=dict(size=4),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["volatility_ratio"],
            name="Volatility Ratio (30s/5m)",
            line=dict(color="#ffa502", width=2),
            mode="lines+markers",
            marker=dict(size=4),
        )
    )

    fig.update_layout(
        title="Reactivity Spike Detection (Ratio > 1.5 = Spike)",
        height=350,
        template="plotly_dark",
        yaxis_title="Ratio (30s / 5m)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


def create_risk_timeline(df: pd.DataFrame) -> go.Figure:
    """Create risk score timeline with color-coded zones."""
    fig = go.Figure()

    # Add risk zones
    fig.add_hrect(y0=0, y1=40, fillcolor="green", opacity=0.1,
                  annotation_text="LOW", annotation_position="top left")
    fig.add_hrect(y0=40, y1=70, fillcolor="orange", opacity=0.1,
                  annotation_text="MODERATE", annotation_position="top left")
    fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.1,
                  annotation_text="HIGH", annotation_position="top left")

    # Risk score line
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["risk_score"],
            name="Risk Score",
            line=dict(color="#ffffff", width=3),
            fill="tozeroy",
            fillcolor="rgba(255, 255, 255, 0.1)",
        )
    )

    fig.update_layout(
        title="Risk Score Timeline",
        height=300,
        template="plotly_dark",
        yaxis=dict(title="Risk Score", range=[0, 100]),
        showlegend=False,
    )

    return fig


def main():
    """Main dashboard application."""
    st.title("🐕 Project Pepper - Walk Monitor")
    st.caption("Real-time canine reactivity detection with dual-window analysis")

    # Sidebar
    with st.sidebar:
        st.header("Settings")

        data_source = st.selectbox(
            "Data Source",
            ["Demo Data", "Live API"],
            help="Select demo data to see example visualizations"
        )

        if data_source == "Live API":
            api_url = st.text_input(
                "API URL",
                value="https://pepper.onrender.com",
                help="Your Project Pepper server URL"
            )
            api_key = st.text_input(
                "API Key",
                type="password",
                help="Your PEPSAFE_API_KEY"
            )

        st.divider()
        st.header("Thresholds")

        spike_threshold = st.slider(
            "Spike Threshold (Ratio)",
            min_value=1.0,
            max_value=3.0,
            value=1.5,
            step=0.1,
            help="Ratio of 30s/5m features to detect spike"
        )

        risk_threshold = st.slider(
            "Risk Alert Threshold",
            min_value=0,
            max_value=100,
            value=70,
            help="Trigger alert when risk score exceeds this"
        )

    # Load data
    if data_source == "Demo Data":
        df = generate_demo_data(100)
        st.info("Showing demo data. Connect to your API for live monitoring.", icon="ℹ️")
    else:
        st.warning("Live API connection not implemented in this demo", icon="⚠️")
        df = generate_demo_data(100)

    # Current status metrics
    st.header("Current Status")

    latest = df.iloc[-1]
    current_risk = latest["risk_score"]

    # Risk level
    if current_risk >= 70:
        risk_level = "HIGH"
        risk_color = "risk-high"
        risk_emoji = "🔴"
    elif current_risk >= 40:
        risk_level = "MODERATE"
        risk_color = "risk-moderate"
        risk_emoji = "🟡"
    else:
        risk_level = "LOW"
        risk_color = "risk-low"
        risk_emoji = "🟢"

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Risk Score",
            value=f"{current_risk:.1f}",
            delta=f"{current_risk - df.iloc[-2]['risk_score']:.1f}" if len(df) > 1 else None,
        )

    with col2:
        st.markdown(f"""
        <div class="spike-indicator">
            {risk_emoji}
            <span class="{risk_color}">{risk_level}</span>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        jitter_ratio = latest.get("jitter_ratio", 0) or 0
        is_spike = jitter_ratio > spike_threshold
        st.metric(
            label="Jitter Ratio (30s/5m)",
            value=f"{jitter_ratio:.2f}x",
            delta="SPIKE!" if is_spike else "Normal",
            delta_color="inverse" if is_spike else "normal",
        )

    with col4:
        volatility_ratio = latest.get("volatility_ratio", 0) or 0
        is_vol_spike = volatility_ratio > spike_threshold
        st.metric(
            label="Volatility Ratio",
            value=f"{volatility_ratio:.2f}x",
            delta="SPIKE!" if is_vol_spike else "Normal",
            delta_color="inverse" if is_vol_spike else "normal",
        )

    # Check for active spike
    recent_spikes = df[
        (df["jitter_ratio"] > spike_threshold) |
        (df["volatility_ratio"] > spike_threshold)
    ]
    if len(recent_spikes) > 0:
        st.error(
            f"⚠️ REACTIVITY SPIKE DETECTED: {len(recent_spikes)} pings with elevated behavioral markers",
            icon="🚨"
        )

    # Charts
    st.header("Dual-Window Analysis")

    st.plotly_chart(create_dual_window_chart(df), use_container_width=True)

    st.header("Spike Detection")

    st.plotly_chart(create_spike_ratio_chart(df), use_container_width=True)

    st.header("Risk Timeline")

    st.plotly_chart(create_risk_timeline(df), use_container_width=True)

    # Feature breakdown
    st.header("Feature Breakdown")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("30s Window (Immediate)")
        st.metric("Velocity Jitter", f"{latest['velocity_jitter_30s']:.3f} m/s")
        st.metric("Bearing Volatility", f"{latest['bearing_volatility_30s']:.1f}°")
        st.metric("Ping Count", latest["ping_count_30s"])

    with col2:
        st.subheader("5m Window (Baseline)")
        st.metric("Velocity Jitter", f"{latest['velocity_jitter_5m']:.3f} m/s")
        st.metric("Bearing Volatility", f"{latest['bearing_volatility_5m']:.1f}°")
        st.metric("Ping Count", latest["ping_count_5m"])

    # Environmental context
    st.header("Environmental Context")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Busyness", f"{latest['busyness_pct']:.0f}%")

    with col2:
        delta = latest["busyness_delta"]
        st.metric(
            "Busyness Delta",
            f"{delta:+.1f}%",
            delta="Crowding" if delta > 10 else "Clearing" if delta < -10 else "Stable"
        )

    with col3:
        if latest["is_stop_event"]:
            st.metric("Stop Event", f"{latest['stop_duration_sec']}s", delta="Freeze detected")
        else:
            st.metric("Stop Event", "None", delta="Moving")

    # Data table
    with st.expander("Raw Data"):
        st.dataframe(
            df[["timestamp", "risk_score", "jitter_ratio", "volatility_ratio",
                "velocity_jitter_30s", "velocity_jitter_5m",
                "busyness_pct", "busyness_delta"]].tail(20),
            use_container_width=True
        )

    # Footer
    st.divider()
    st.caption("Project Pepper v0.1.0 | Privacy-First Canine Reactivity Detection")


if __name__ == "__main__":
    main()
