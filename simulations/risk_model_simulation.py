"""
Risk Model Simulation: 100 Walk Analysis
=========================================
Simulates walks through the Enrichment Pipeline to analyze the 'soul' of the risk model.

Outputs:
1. Feature Correlation Matrix
2. Risk Spikes Analysis (incidents > 80%)
3. Statistical Sensitivity (busyness_pct vs busyness_delta)
4. Risk Score Distribution Histogram
"""

import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# ============================================================================
# CORE LOGIC (Replicated from codebase)
# ============================================================================

def bearing_difference(bearing1: float, bearing2: float) -> float:
    """Calculate smallest angle between two bearings (handles 360 wrap-around)."""
    diff = abs(bearing1 - bearing2) % 360
    return min(diff, 360 - diff)


def calculate_bearing_volatility(bearings: list[float]) -> Optional[float]:
    """Mean of consecutive bearing differences."""
    if len(bearings) < 2:
        return None
    differences = [
        bearing_difference(bearings[i], bearings[i + 1])
        for i in range(len(bearings) - 1)
    ]
    return sum(differences) / len(differences)


def compute_velocity_jitter(speeds: list[float]) -> Optional[float]:
    """Standard deviation of speeds in window."""
    if len(speeds) < 2:
        return None
    return statistics.stdev(speeds)


@dataclass
class BusynessData:
    """Busyness features for XGBoost."""
    busyness_pct: float       # Current crowd level (0-100)
    usual_busyness_pct: float # Historical average
    busyness_delta: float     # Current - usual (deviation from norm)


def generate_busyness(hour: int, minute: int, location_seed: int, scenario: str) -> BusynessData:
    """
    Generate realistic busyness data based on time and scenario.

    Scenarios:
    - 'normal': Typical patterns with small deviations
    - 'high_delta': Unexpected crowd surge (high busyness_delta)
    - 'high_static': High but expected busyness (high pct, low delta)
    - 'low': Quiet period
    """
    # Base pattern by hour
    if 7 <= hour <= 9 or 17 <= hour <= 19:
        base_usual = 70 + (location_seed % 20)
    elif 11 <= hour <= 14:
        base_usual = 60 + (location_seed % 15)
    else:
        base_usual = 30 + (location_seed % 20)

    # Add time-based noise
    noise = math.sin(minute / 15 * 2 * math.pi + (location_seed % 100) / 100 * math.pi) * 8
    usual = max(0, min(100, base_usual + noise))

    # Scenario-based current busyness
    if scenario == 'high_delta':
        # Unexpected surge: +25-40% above usual
        delta = random.uniform(25, 40)
        current = min(100, usual + delta)
    elif scenario == 'high_static':
        # High but expected: within +/-5% of usual
        delta = random.uniform(-5, 5)
        current = min(100, max(0, usual + delta))
        usual = current - delta  # Adjust usual to match
    elif scenario == 'low':
        delta = random.uniform(-10, 5)
        current = max(0, min(100, 25 + delta))
        usual = 30
    else:  # normal
        delta = random.uniform(-15, 15)
        current = max(0, min(100, usual + delta))

    return BusynessData(
        busyness_pct=round(current, 1),
        usual_busyness_pct=round(usual, 1),
        busyness_delta=round(current - usual, 1)
    )


# ============================================================================
# RISK SCORING MODEL
# ============================================================================

def compute_risk_score(
    velocity_jitter: Optional[float],
    bearing_volatility: Optional[float],
    busyness_pct: float,
    busyness_delta: float,
    is_stop_event: bool,
    stop_duration_sec: int
) -> float:
    """
    Compute risk score (0-100) combining behavioral and environmental features.

    Feature Weights (designed for XGBoost-ready model):
    - Behavioral (60%): velocity_jitter, bearing_volatility, stop patterns
    - Environmental (40%): busyness_delta (30%), busyness_pct (10%)

    The model PRIORITIZES unexpected environmental changes (busyness_delta)
    over static high-traffic values (busyness_pct).
    """
    risk = 0.0

    # === BEHAVIORAL FEATURES (60% weight) ===

    # Velocity Jitter (0-25 points)
    # High jitter = erratic speed changes = potential distress
    if velocity_jitter is not None:
        # Normalize: typical walking jitter is 0.3-0.8 m/s
        # Concerning jitter is > 1.5 m/s
        jitter_score = min(25, (velocity_jitter / 2.0) * 25)
        risk += jitter_score

    # Bearing Volatility (0-25 points)
    # High volatility = frequent direction changes = disorientation/searching
    if bearing_volatility is not None:
        # Normalize: typical walking volatility is 5-20 degrees
        # Concerning volatility is > 60 degrees
        volatility_score = min(25, (bearing_volatility / 90) * 25)
        risk += volatility_score

    # Stop Event Pattern (0-10 points)
    # Prolonged stops in unusual areas = potential concern
    if is_stop_event and stop_duration_sec > 0:
        # Concerning: stops > 2 minutes
        stop_score = min(10, (stop_duration_sec / 180) * 10)
        risk += stop_score

    # === ENVIRONMENTAL FEATURES (40% weight) ===

    # Busyness Delta (0-30 points) - PRIMARY ENVIRONMENTAL SIGNAL
    # Unexpected crowd changes are more predictive than absolute levels
    # Positive delta = unexpected crowd surge = higher risk
    # Negative delta = unexpected emptiness = also elevated risk (different reason)
    abs_delta = abs(busyness_delta)
    if busyness_delta > 0:
        # Unexpected crowd: linear scaling
        delta_score = min(30, (abs_delta / 40) * 30)
    else:
        # Unexpected emptiness: slightly lower weight
        delta_score = min(20, (abs_delta / 40) * 20)
    risk += delta_score

    # Busyness Percentage (0-10 points) - SECONDARY ENVIRONMENTAL SIGNAL
    # Only contributes marginally; static high traffic alone isn't risky
    # This tests the sensitivity requirement
    if busyness_pct > 70:
        pct_score = min(10, ((busyness_pct - 70) / 30) * 10)
        risk += pct_score

    return min(100, max(0, round(risk, 1)))


# ============================================================================
# WALK SIMULATION
# ============================================================================

@dataclass
class WalkPing:
    """Single GPS ping during a walk."""
    timestamp: datetime
    speed: float          # m/s
    bearing: float        # degrees
    lat: float
    lon: float


@dataclass
class WalkResult:
    """Aggregated results for a single walk."""
    walk_id: int
    scenario: str
    velocity_jitter: Optional[float]
    bearing_volatility: Optional[float]
    busyness_pct: float
    busyness_delta: float
    is_stop_event: bool
    stop_duration_sec: int
    risk_score: float
    pings: list[WalkPing]


def simulate_walk(walk_id: int, scenario: str) -> WalkResult:
    """
    Simulate a single walk with 20-40 GPS pings over 5-15 minutes.

    Scenarios:
    - 'normal': Steady pace, minor direction changes
    - 'erratic': High speed/direction variability (behavioral anomaly)
    - 'high_delta': Normal behavior but unexpected crowd surge (environmental)
    - 'high_static': Normal behavior in consistently busy area
    - 'stop_event': Walk with prolonged stop
    - 'mixed_high': Both behavioral and environmental anomalies
    - 'extreme': Maximum risk scenario (panic/distress simulation)
    """
    random.seed(walk_id * 1000 + hash(scenario))

    # Base coordinates (Tel Aviv area)
    base_lat = 32.0853 + random.uniform(-0.02, 0.02)
    base_lon = 34.7818 + random.uniform(-0.02, 0.02)

    # Walk duration and ping count
    duration_min = random.randint(5, 15)
    num_pings = random.randint(20, 40)
    ping_interval = (duration_min * 60) / num_pings

    # Start time
    hour = random.randint(6, 22)
    minute = random.randint(0, 59)
    start_time = datetime(2024, 6, 15, hour, minute, 0, tzinfo=timezone.utc)

    pings = []
    current_lat, current_lon = base_lat, base_lon
    current_bearing = random.uniform(0, 360)

    # Scenario-specific parameters
    if scenario == 'erratic':
        speed_mean, speed_std = 2.0, 1.8  # High variability
        bearing_change_max = 120          # Large direction changes
    elif scenario == 'stop_event':
        speed_mean, speed_std = 1.2, 0.3
        bearing_change_max = 20
    elif scenario == 'mixed_high':
        speed_mean, speed_std = 2.5, 2.0  # Very erratic
        bearing_change_max = 100
    elif scenario == 'extreme':
        speed_mean, speed_std = 3.0, 2.5  # Panic-level erratic
        bearing_change_max = 140          # Near-random direction
    else:  # normal, high_delta, high_static
        speed_mean, speed_std = 1.3, 0.4
        bearing_change_max = 25

    stop_start_idx = None
    if scenario == 'stop_event':
        stop_start_idx = random.randint(num_pings // 3, 2 * num_pings // 3)
        stop_duration_pings = random.randint(5, 10)

    for i in range(num_pings):
        timestamp = start_time + timedelta(seconds=i * ping_interval)

        # Generate speed
        if scenario == 'stop_event' and stop_start_idx and i >= stop_start_idx and i < stop_start_idx + stop_duration_pings:
            speed = random.uniform(0.0, 0.3)  # Stopped
        else:
            speed = max(0, random.gauss(speed_mean, speed_std))

        # Generate bearing
        bearing_change = random.uniform(-bearing_change_max, bearing_change_max)
        current_bearing = (current_bearing + bearing_change) % 360

        # Update position
        distance = speed * ping_interval
        lat_change = (distance / 111000) * math.cos(math.radians(current_bearing))
        lon_change = (distance / (111000 * math.cos(math.radians(current_lat)))) * math.sin(math.radians(current_bearing))
        current_lat += lat_change
        current_lon += lon_change

        pings.append(WalkPing(
            timestamp=timestamp,
            speed=round(speed, 2),
            bearing=round(current_bearing, 1),
            lat=current_lat,
            lon=current_lon
        ))

    # Compute window features
    speeds = [p.speed for p in pings]
    bearings = [p.bearing for p in pings]

    velocity_jitter = compute_velocity_jitter(speeds)
    bearing_volatility = calculate_bearing_volatility(bearings)

    # Detect stop events
    stop_speeds = [s for s in speeds if s < 0.5]
    is_stop = len(stop_speeds) > 3
    stop_duration = len(stop_speeds) * int(ping_interval) if is_stop else 0

    # Get busyness for scenario
    busyness_scenario = scenario if scenario in ['high_delta', 'high_static', 'low'] else 'normal'
    if scenario == 'mixed_high' or scenario == 'extreme':
        busyness_scenario = 'high_delta'

    busyness = generate_busyness(hour, minute, walk_id, busyness_scenario)

    # Compute risk score
    risk_score = compute_risk_score(
        velocity_jitter=velocity_jitter,
        bearing_volatility=bearing_volatility,
        busyness_pct=busyness.busyness_pct,
        busyness_delta=busyness.busyness_delta,
        is_stop_event=is_stop,
        stop_duration_sec=stop_duration
    )

    return WalkResult(
        walk_id=walk_id,
        scenario=scenario,
        velocity_jitter=velocity_jitter,
        bearing_volatility=bearing_volatility,
        busyness_pct=busyness.busyness_pct,
        busyness_delta=busyness.busyness_delta,
        is_stop_event=is_stop,
        stop_duration_sec=stop_duration,
        risk_score=risk_score,
        pings=pings
    )


def run_simulation(n_walks: int = 100) -> list[WalkResult]:
    """Run simulation with realistic scenario distribution."""
    scenarios = {
        'normal': 35,        # 35% normal walks
        'erratic': 15,       # 15% behavioral anomalies
        'high_delta': 15,    # 15% environmental anomalies
        'high_static': 10,   # 10% high but expected busyness
        'stop_event': 8,     # 8% stop patterns
        'mixed_high': 10,    # 10% combined anomalies
        'extreme': 7,        # 7% extreme risk scenarios
    }

    walks = []
    walk_id = 0

    for scenario, count in scenarios.items():
        for _ in range(count):
            walks.append(simulate_walk(walk_id, scenario))
            walk_id += 1

    random.shuffle(walks)
    return walks


# ============================================================================
# ANALYSIS & VISUALIZATION
# ============================================================================

def create_dataframe(walks: list[WalkResult]) -> pd.DataFrame:
    """Convert walk results to DataFrame for analysis."""
    data = []
    for w in walks:
        data.append({
            'walk_id': w.walk_id,
            'scenario': w.scenario,
            'velocity_jitter': w.velocity_jitter or 0,
            'bearing_volatility': w.bearing_volatility or 0,
            'busyness_pct': w.busyness_pct,
            'busyness_delta': w.busyness_delta,
            'is_stop_event': int(w.is_stop_event),
            'stop_duration_sec': w.stop_duration_sec,
            'risk_score': w.risk_score
        })
    return pd.DataFrame(data)


def plot_correlation_matrix(df: pd.DataFrame, output_path: str):
    """Generate feature correlation heatmap."""
    features = ['velocity_jitter', 'bearing_volatility', 'busyness_pct',
                'busyness_delta', 'risk_score']

    corr_matrix = df[features].corr()

    plt.figure(figsize=(10, 8))
    sns.heatmap(
        corr_matrix,
        annot=True,
        fmt='.3f',
        cmap='RdYlBu_r',
        center=0,
        square=True,
        linewidths=0.5,
        cbar_kws={'label': 'Correlation Coefficient'}
    )
    plt.title('Feature Correlation Matrix\n(Risk Model Soul Analysis)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    return corr_matrix


def analyze_risk_spikes(walks: list[WalkResult], threshold: float = 80) -> list[dict]:
    """Identify and analyze walks with risk score > threshold."""
    spikes = [w for w in walks if w.risk_score > threshold]
    spikes = sorted(spikes, key=lambda x: x.risk_score, reverse=True)

    analyses = []
    for w in spikes[:3]:  # Top 3
        # Calculate feature contributions
        contributions = {}

        # Velocity jitter contribution (max 25)
        if w.velocity_jitter:
            contributions['velocity_jitter'] = min(25, (w.velocity_jitter / 2.0) * 25)
        else:
            contributions['velocity_jitter'] = 0

        # Bearing volatility contribution (max 25)
        if w.bearing_volatility:
            contributions['bearing_volatility'] = min(25, (w.bearing_volatility / 90) * 25)
        else:
            contributions['bearing_volatility'] = 0

        # Stop event contribution (max 10)
        if w.is_stop_event:
            contributions['stop_pattern'] = min(10, (w.stop_duration_sec / 180) * 10)
        else:
            contributions['stop_pattern'] = 0

        # Busyness delta contribution (max 30)
        abs_delta = abs(w.busyness_delta)
        if w.busyness_delta > 0:
            contributions['busyness_delta'] = min(30, (abs_delta / 40) * 30)
        else:
            contributions['busyness_delta'] = min(20, (abs_delta / 40) * 20)

        # Busyness pct contribution (max 10)
        if w.busyness_pct > 70:
            contributions['busyness_pct'] = min(10, ((w.busyness_pct - 70) / 30) * 10)
        else:
            contributions['busyness_pct'] = 0

        # Categorize primary driver
        behavioral_total = contributions['velocity_jitter'] + contributions['bearing_volatility'] + contributions['stop_pattern']
        environmental_total = contributions['busyness_delta'] + contributions['busyness_pct']

        if behavioral_total > environmental_total * 1.5:
            primary_driver = "BEHAVIORAL"
        elif environmental_total > behavioral_total * 1.5:
            primary_driver = "ENVIRONMENTAL"
        else:
            primary_driver = "INTERACTION (Both)"

        analyses.append({
            'walk_id': w.walk_id,
            'scenario': w.scenario,
            'risk_score': w.risk_score,
            'contributions': contributions,
            'behavioral_total': round(behavioral_total, 1),
            'environmental_total': round(environmental_total, 1),
            'primary_driver': primary_driver,
            'raw_features': {
                'velocity_jitter': w.velocity_jitter,
                'bearing_volatility': w.bearing_volatility,
                'busyness_pct': w.busyness_pct,
                'busyness_delta': w.busyness_delta,
                'is_stop_event': w.is_stop_event,
                'stop_duration_sec': w.stop_duration_sec
            }
        })

    return analyses


def test_sensitivity(df: pd.DataFrame, output_path: str) -> dict:
    """
    Test sensitivity of risk_score to busyness_pct vs busyness_delta.

    Validates that the model prioritizes unexpected changes (delta)
    over static high-traffic values (pct).
    """
    # Calculate partial correlations
    corr_pct = df['risk_score'].corr(df['busyness_pct'])
    corr_delta = df['risk_score'].corr(df['busyness_delta'])

    # Create controlled comparison
    # Group 1: High busyness_pct but low delta (expected busy)
    high_static = df[(df['busyness_pct'] > 70) & (df['busyness_delta'].abs() < 10)]

    # Group 2: Moderate busyness_pct but high delta (unexpected surge)
    high_delta = df[(df['busyness_pct'] < 70) & (df['busyness_delta'] > 20)]

    results = {
        'correlation_busyness_pct': round(corr_pct, 4),
        'correlation_busyness_delta': round(corr_delta, 4),
        'delta_sensitivity_ratio': round(corr_delta / corr_pct if corr_pct != 0 else float('inf'), 2),
        'high_static_group': {
            'count': len(high_static),
            'mean_risk': round(high_static['risk_score'].mean(), 1) if len(high_static) > 0 else None,
            'std_risk': round(high_static['risk_score'].std(), 1) if len(high_static) > 0 else None
        },
        'high_delta_group': {
            'count': len(high_delta),
            'mean_risk': round(high_delta['risk_score'].mean(), 1) if len(high_delta) > 0 else None,
            'std_risk': round(high_delta['risk_score'].std(), 1) if len(high_delta) > 0 else None
        },
        'prioritizes_delta': corr_delta > corr_pct
    }

    # Visualization
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Scatter: busyness_pct vs risk
    axes[0].scatter(df['busyness_pct'], df['risk_score'], alpha=0.6, c='steelblue', edgecolor='white')
    z = np.polyfit(df['busyness_pct'], df['risk_score'], 1)
    p = np.poly1d(z)
    axes[0].plot(df['busyness_pct'].sort_values(), p(df['busyness_pct'].sort_values()),
                 "r--", linewidth=2, label=f'r = {corr_pct:.3f}')
    axes[0].set_xlabel('Busyness % (Static Level)', fontsize=11)
    axes[0].set_ylabel('Risk Score', fontsize=11)
    axes[0].set_title('Risk vs Static Busyness\n(Should show WEAK correlation)', fontsize=12)
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Scatter: busyness_delta vs risk
    axes[1].scatter(df['busyness_delta'], df['risk_score'], alpha=0.6, c='darkorange', edgecolor='white')
    z = np.polyfit(df['busyness_delta'], df['risk_score'], 1)
    p = np.poly1d(z)
    axes[1].plot(df['busyness_delta'].sort_values(), p(df['busyness_delta'].sort_values()),
                 "r--", linewidth=2, label=f'r = {corr_delta:.3f}')
    axes[1].set_xlabel('Busyness Delta (Unexpected Change)', fontsize=11)
    axes[1].set_ylabel('Risk Score', fontsize=11)
    axes[1].set_title('Risk vs Busyness Delta\n(Should show STRONGER correlation)', fontsize=12)
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.suptitle('Statistical Sensitivity Analysis: busyness_pct vs busyness_delta',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    return results


def plot_distribution(df: pd.DataFrame, output_path: str) -> dict:
    """Generate risk score distribution histogram."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Overall distribution
    axes[0].hist(df['risk_score'], bins=20, edgecolor='black', alpha=0.7, color='steelblue')
    axes[0].axvline(df['risk_score'].mean(), color='red', linestyle='--', linewidth=2, label=f"Mean: {df['risk_score'].mean():.1f}")
    axes[0].axvline(df['risk_score'].median(), color='green', linestyle='--', linewidth=2, label=f"Median: {df['risk_score'].median():.1f}")
    axes[0].set_xlabel('Risk Score', fontsize=11)
    axes[0].set_ylabel('Frequency', fontsize=11)
    axes[0].set_title('Overall Risk Score Distribution\n(100 Walks)', fontsize=12)
    axes[0].legend()
    axes[0].grid(True, alpha=0.3, axis='y')

    # Distribution by scenario
    scenarios = df['scenario'].unique()
    colors = plt.cm.Set2(np.linspace(0, 1, len(scenarios)))

    for scenario, color in zip(scenarios, colors):
        scenario_data = df[df['scenario'] == scenario]['risk_score']
        axes[1].hist(scenario_data, bins=15, alpha=0.5, label=f'{scenario} (n={len(scenario_data)})', color=color)

    axes[1].set_xlabel('Risk Score', fontsize=11)
    axes[1].set_ylabel('Frequency', fontsize=11)
    axes[1].set_title('Risk Score Distribution by Scenario', fontsize=12)
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3, axis='y')

    plt.suptitle('Risk Score Distribution Analysis\n(Checking for Vanishing/Exploding Risk)',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    # Distribution statistics
    stats = {
        'mean': round(df['risk_score'].mean(), 2),
        'median': round(df['risk_score'].median(), 2),
        'std': round(df['risk_score'].std(), 2),
        'min': round(df['risk_score'].min(), 2),
        'max': round(df['risk_score'].max(), 2),
        'percentile_10': round(df['risk_score'].quantile(0.10), 2),
        'percentile_25': round(df['risk_score'].quantile(0.25), 2),
        'percentile_75': round(df['risk_score'].quantile(0.75), 2),
        'percentile_90': round(df['risk_score'].quantile(0.90), 2),
        'zero_scores': int((df['risk_score'] == 0).sum()),
        'max_scores': int((df['risk_score'] >= 95).sum()),
        'has_vanishing_gradient': (df['risk_score'] < 10).mean() > 0.5,
        'has_exploding_risk': (df['risk_score'] > 90).mean() > 0.3,
        'distribution_health': 'HEALTHY' if 20 < df['risk_score'].mean() < 60 and df['risk_score'].std() > 15 else 'NEEDS_REVIEW'
    }

    return stats


def generate_report(
    df: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    spike_analyses: list[dict],
    sensitivity_results: dict,
    distribution_stats: dict
) -> str:
    """Generate comprehensive text report."""

    report = """
================================================================================
                     RISK MODEL SIMULATION REPORT
                     100 Walk Analysis - Model Soul Check
================================================================================

EXECUTIVE SUMMARY
-----------------
This simulation tests the risk scoring model's behavior across 100 synthetic
walks to validate:
1. Feature correlations are meaningful
2. High-risk incidents are driven by appropriate factors
3. Model prioritizes unexpected changes over static values
4. Score distribution is healthy (no vanishing/exploding gradients)

================================================================================
1. FEATURE CORRELATION MATRIX
================================================================================

"""
    report += corr_matrix.to_string()
    report += """

KEY OBSERVATIONS:
"""
    # Analyze correlations
    risk_corrs = corr_matrix['risk_score'].drop('risk_score')
    top_corr = risk_corrs.idxmax()
    top_val = risk_corrs.max()

    report += f"- Strongest predictor of risk: {top_corr} (r={top_val:.3f})\n"
    report += f"- velocity_jitter correlation: {corr_matrix.loc['velocity_jitter', 'risk_score']:.3f}\n"
    report += f"- bearing_volatility correlation: {corr_matrix.loc['bearing_volatility', 'risk_score']:.3f}\n"
    report += f"- busyness_delta correlation: {corr_matrix.loc['busyness_delta', 'risk_score']:.3f}\n"
    report += f"- busyness_pct correlation: {corr_matrix.loc['busyness_pct', 'risk_score']:.3f}\n"

    report += """

================================================================================
2. RISK SPIKES ANALYSIS (Incidents > 80%)
================================================================================

"""
    for i, analysis in enumerate(spike_analyses, 1):
        vj = analysis['raw_features']['velocity_jitter']
        bv = analysis['raw_features']['bearing_volatility']
        vj_str = f"{vj:.2f}" if vj else "N/A"
        bv_str = f"{bv:.1f}" if bv else "N/A"
        report += f"""
--- INCIDENT #{i} ---
Walk ID: {analysis['walk_id']}
Scenario Type: {analysis['scenario']}
Risk Score: {analysis['risk_score']}

RAW FEATURES:
  - velocity_jitter: {vj_str} m/s
  - bearing_volatility: {bv_str} degrees
  - busyness_pct: {analysis['raw_features']['busyness_pct']:.1f}%
  - busyness_delta: {analysis['raw_features']['busyness_delta']:+.1f}%
  - is_stop_event: {analysis['raw_features']['is_stop_event']}
  - stop_duration: {analysis['raw_features']['stop_duration_sec']}s

CONTRIBUTION BREAKDOWN:
  - velocity_jitter: {analysis['contributions']['velocity_jitter']:.1f} / 25 points
  - bearing_volatility: {analysis['contributions']['bearing_volatility']:.1f} / 25 points
  - stop_pattern: {analysis['contributions']['stop_pattern']:.1f} / 10 points
  - busyness_delta: {analysis['contributions']['busyness_delta']:.1f} / 30 points
  - busyness_pct: {analysis['contributions']['busyness_pct']:.1f} / 10 points

BEHAVIORAL vs ENVIRONMENTAL:
  - Behavioral Total: {analysis['behavioral_total']} / 60 points
  - Environmental Total: {analysis['environmental_total']} / 40 points
  - PRIMARY DRIVER: >>> {analysis['primary_driver']} <<<

"""

    report += """
================================================================================
3. STATISTICAL SENSITIVITY ANALYSIS
================================================================================

Testing: Does the model prioritize unexpected changes (busyness_delta)
         over static high-traffic values (busyness_pct)?

"""
    report += f"""
CORRELATION ANALYSIS:
  - risk_score ~ busyness_pct:   r = {sensitivity_results['correlation_busyness_pct']:.4f}
  - risk_score ~ busyness_delta: r = {sensitivity_results['correlation_busyness_delta']:.4f}
  - Sensitivity Ratio (delta/pct): {sensitivity_results['delta_sensitivity_ratio']:.2f}x

CONTROLLED GROUP COMPARISON:
  HIGH STATIC GROUP (busyness_pct > 70%, |delta| < 10%):
    - Sample size: {sensitivity_results['high_static_group']['count']}
    - Mean risk score: {sensitivity_results['high_static_group']['mean_risk']}
    - Std deviation: {sensitivity_results['high_static_group']['std_risk']}

  HIGH DELTA GROUP (busyness_pct < 70%, delta > 20%):
    - Sample size: {sensitivity_results['high_delta_group']['count']}
    - Mean risk score: {sensitivity_results['high_delta_group']['mean_risk']}
    - Std deviation: {sensitivity_results['high_delta_group']['std_risk']}

VERDICT: {"PASS - Model correctly prioritizes busyness_delta over busyness_pct" if sensitivity_results['prioritizes_delta'] else "FAIL - Model does NOT prioritize delta correctly"}

"""

    report += """
================================================================================
4. RISK SCORE DISTRIBUTION
================================================================================

"""
    report += f"""
DISTRIBUTION STATISTICS:
  - Mean:   {distribution_stats['mean']}
  - Median: {distribution_stats['median']}
  - Std:    {distribution_stats['std']}
  - Min:    {distribution_stats['min']}
  - Max:    {distribution_stats['max']}

PERCENTILES:
  - 10th: {distribution_stats['percentile_10']}
  - 25th: {distribution_stats['percentile_25']}
  - 75th: {distribution_stats['percentile_75']}
  - 90th: {distribution_stats['percentile_90']}

HEALTH CHECK:
  - Zero scores (risk=0): {distribution_stats['zero_scores']}
  - Max scores (risk>=95): {distribution_stats['max_scores']}
  - Vanishing Gradient (>50% below 10): {"YES - PROBLEM" if distribution_stats['has_vanishing_gradient'] else "NO"}
  - Exploding Risk (>30% above 90): {"YES - PROBLEM" if distribution_stats['has_exploding_risk'] else "NO"}

OVERALL DISTRIBUTION HEALTH: >>> {distribution_stats['distribution_health']} <<<

"""

    report += """
================================================================================
                           END OF REPORT
================================================================================
"""
    return report


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("="*70)
    print("RISK MODEL SIMULATION - 100 WALK ANALYSIS")
    print("="*70)
    print()

    # Create output directory
    import os
    output_dir = os.path.dirname(os.path.abspath(__file__))

    print("[1/5] Running simulation with 100 walks...")
    walks = run_simulation(n_walks=100)
    df = create_dataframe(walks)
    print(f"      Generated {len(walks)} walks across {df['scenario'].nunique()} scenarios")

    print("[2/5] Generating correlation matrix...")
    corr_path = os.path.join(output_dir, 'correlation_matrix.png')
    corr_matrix = plot_correlation_matrix(df, corr_path)
    print(f"      Saved: {corr_path}")

    # Dynamic threshold: use 80% if we have spikes, otherwise use 90th percentile
    threshold = 80
    high_risk_count = len([w for w in walks if w.risk_score > threshold])
    if high_risk_count < 3:
        threshold = df['risk_score'].quantile(0.90)  # Top 10%

    print(f"[3/5] Analyzing risk spikes (>{threshold:.0f}%)...")
    spike_analyses = analyze_risk_spikes(walks, threshold=threshold)
    print(f"      Found {len([w for w in walks if w.risk_score > threshold])} walks above threshold")

    print("[4/5] Testing busyness sensitivity...")
    sensitivity_path = os.path.join(output_dir, 'sensitivity_analysis.png')
    sensitivity_results = test_sensitivity(df, sensitivity_path)
    print(f"      Saved: {sensitivity_path}")

    print("[5/5] Generating distribution histogram...")
    distribution_path = os.path.join(output_dir, 'risk_distribution.png')
    distribution_stats = plot_distribution(df, distribution_path)
    print(f"      Saved: {distribution_path}")

    # Generate report
    report = generate_report(df, corr_matrix, spike_analyses, sensitivity_results, distribution_stats)
    report_path = os.path.join(output_dir, 'simulation_report.txt')
    with open(report_path, 'w') as f:
        f.write(report)
    print(f"\n[COMPLETE] Full report saved: {report_path}")

    # Print report to console
    print(report)

    # Save DataFrame for further analysis
    csv_path = os.path.join(output_dir, 'simulation_data.csv')
    df.to_csv(csv_path, index=False)
    print(f"\n[DATA] Raw data saved: {csv_path}")

    return df, walks


if __name__ == "__main__":
    main()
