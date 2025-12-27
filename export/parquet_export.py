"""Export enriched ping data to Parquet/CSV for XGBoost training."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Schema for ML export - optimized for XGBoost time-series
# Updated for dual sliding window features (30s + 5m)
EXPORT_SCHEMA = pa.schema([
    ("ping_id", pa.int64()),
    ("user_id", pa.string()),
    ("timestamp", pa.timestamp("us")),  # Microsecond precision for time-series
    ("lat", pa.float64()),
    ("lon", pa.float64()),
    ("speed", pa.float64()),
    ("bearing", pa.float64()),
    ("accuracy", pa.float64()),
    # Weather features (OpenWeatherMap)
    ("temp_c", pa.float64()),
    ("feels_like_c", pa.float64()),
    ("humidity_pct", pa.float64()),
    ("rain_1h_mm", pa.float64()),
    ("wind_speed_ms", pa.float64()),
    ("wind_gust_ms", pa.float64()),
    ("visibility_m", pa.float64()),
    ("weather_condition", pa.string()),
    ("weather_condition_id", pa.int32()),
    ("is_daylight", pa.bool_()),
    # Busyness features (Google Live Busyness mock)
    ("busyness_pct", pa.float64()),
    ("usual_busyness_pct", pa.float64()),
    ("busyness_delta", pa.float64()),
    ("busyness_trend", pa.string()),
    ("location_type", pa.string()),
    ("busyness_confidence", pa.float64()),
    ("busyness_is_mock", pa.bool_()),
    # Dual sliding window features - Short window (30s)
    ("velocity_jitter_30s", pa.float64()),
    ("bearing_volatility_30s", pa.float64()),
    ("ping_count_30s", pa.int32()),
    # Dual sliding window features - Long window (5m)
    ("velocity_jitter_5m", pa.float64()),
    ("bearing_volatility_5m", pa.float64()),
    ("ping_count_5m", pa.int32()),
    # Derived spike detection ratios
    ("jitter_ratio", pa.float64()),  # 30s/5m (>1 = behavioral spike)
    ("volatility_ratio", pa.float64()),  # 30s/5m (>1 = erratic behavior)
    # Stop event features
    ("is_stop_event", pa.bool_()),
    ("stop_duration_sec", pa.int32()),
    # Choke point features (flattened)
    ("nearest_choke_point", pa.string()),
    ("nearest_choke_distance_m", pa.float64()),
])


async def export_to_parquet(
    output_path: Path,
    user_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> int:
    """
    Export enriched ping data to Parquet format for XGBoost.

    Data is sorted by user_id, then timestamp for time-series analysis.
    Only non-home-zone pings are exported (privacy preserved).

    Args:
        output_path: Path for output .parquet file
        user_id: Optional filter by user
        start_time: Optional start timestamp filter
        end_time: Optional end timestamp filter

    Returns:
        Number of rows exported
    """
    engine = create_async_engine(settings.database_url)

    query = """
        SELECT
            rp.id as ping_id,
            rp.user_id,
            rp.timestamp,
            rp.lat,
            rp.lon,
            rp.speed,
            rp.bearing,
            rp.accuracy,
            -- Weather features (OpenWeatherMap)
            ep.temp_c,
            ep.feels_like_c,
            ep.humidity_pct,
            ep.rain_1h_mm,
            ep.wind_speed_ms,
            ep.wind_gust_ms,
            ep.visibility_m,
            ep.weather_condition,
            ep.weather_condition_id,
            ep.is_daylight,
            -- Busyness features (Google Live Busyness mock)
            ep.busyness_pct,
            ep.usual_busyness_pct,
            ep.busyness_delta,
            ep.busyness_trend,
            ep.location_type,
            ep.busyness_confidence,
            ep.busyness_is_mock,
            -- Dual sliding window features - Short window (30s)
            ep.velocity_jitter_30s,
            ep.bearing_volatility_30s,
            ep.ping_count_30s,
            -- Dual sliding window features - Long window (5m)
            ep.velocity_jitter_5m,
            ep.bearing_volatility_5m,
            ep.ping_count_5m,
            -- Derived spike detection ratios
            ep.jitter_ratio,
            ep.volatility_ratio,
            -- Stop event features
            ep.is_stop_event,
            ep.stop_duration_sec,
            -- Choke point features
            (
                SELECT cp.name
                FROM ping_choke_proximity pcp
                JOIN choke_points cp ON pcp.choke_point_id = cp.id
                WHERE pcp.ping_id = rp.id
                ORDER BY pcp.distance_m ASC
                LIMIT 1
            ) as nearest_choke_point,
            (
                SELECT MIN(pcp.distance_m)
                FROM ping_choke_proximity pcp
                WHERE pcp.ping_id = rp.id
            ) as nearest_choke_distance_m
        FROM raw_pings rp
        LEFT JOIN enriched_pings ep ON rp.id = ep.ping_id
        WHERE rp.is_home_zone = FALSE
    """

    params = {}
    if user_id:
        query += " AND rp.user_id = :user_id"
        params["user_id"] = user_id
    if start_time:
        query += " AND rp.timestamp >= :start_time"
        params["start_time"] = start_time
    if end_time:
        query += " AND rp.timestamp <= :end_time"
        params["end_time"] = end_time

    # Sort for time-series: user first, then chronological
    query += " ORDER BY rp.user_id, rp.timestamp ASC"

    async with engine.connect() as conn:
        result = await conn.execute(text(query), params)
        rows = result.fetchall()

    if not rows:
        logger.info("No data to export")
        return 0

    # Convert to PyArrow table
    columns = {
        "ping_id": [],
        "user_id": [],
        "timestamp": [],
        "lat": [],
        "lon": [],
        "speed": [],
        "bearing": [],
        "accuracy": [],
        # Weather features
        "temp_c": [],
        "feels_like_c": [],
        "humidity_pct": [],
        "rain_1h_mm": [],
        "wind_speed_ms": [],
        "wind_gust_ms": [],
        "visibility_m": [],
        "weather_condition": [],
        "weather_condition_id": [],
        "is_daylight": [],
        # Busyness features
        "busyness_pct": [],
        "usual_busyness_pct": [],
        "busyness_delta": [],
        "busyness_trend": [],
        "location_type": [],
        "busyness_confidence": [],
        "busyness_is_mock": [],
        # Dual sliding window features - Short window (30s)
        "velocity_jitter_30s": [],
        "bearing_volatility_30s": [],
        "ping_count_30s": [],
        # Dual sliding window features - Long window (5m)
        "velocity_jitter_5m": [],
        "bearing_volatility_5m": [],
        "ping_count_5m": [],
        # Derived spike detection ratios
        "jitter_ratio": [],
        "volatility_ratio": [],
        # Stop event features
        "is_stop_event": [],
        "stop_duration_sec": [],
        # Choke point features
        "nearest_choke_point": [],
        "nearest_choke_distance_m": [],
    }

    for row in rows:
        # Base ping data (indices 0-7)
        columns["ping_id"].append(row[0])
        columns["user_id"].append(row[1])
        columns["timestamp"].append(row[2])
        columns["lat"].append(row[3])
        columns["lon"].append(row[4])
        columns["speed"].append(row[5])
        columns["bearing"].append(row[6])
        columns["accuracy"].append(row[7])
        # Weather features (indices 8-17)
        columns["temp_c"].append(row[8])
        columns["feels_like_c"].append(row[9])
        columns["humidity_pct"].append(row[10])
        columns["rain_1h_mm"].append(row[11])
        columns["wind_speed_ms"].append(row[12])
        columns["wind_gust_ms"].append(row[13])
        columns["visibility_m"].append(row[14])
        columns["weather_condition"].append(row[15])
        columns["weather_condition_id"].append(row[16])
        columns["is_daylight"].append(bool(row[17]) if row[17] is not None else None)
        # Busyness features (indices 18-24)
        columns["busyness_pct"].append(row[18])
        columns["usual_busyness_pct"].append(row[19])
        columns["busyness_delta"].append(row[20])
        columns["busyness_trend"].append(row[21])
        columns["location_type"].append(row[22])
        columns["busyness_confidence"].append(row[23])
        columns["busyness_is_mock"].append(bool(row[24]) if row[24] is not None else None)
        # Dual sliding window features - Short window (indices 25-27)
        columns["velocity_jitter_30s"].append(row[25])
        columns["bearing_volatility_30s"].append(row[26])
        columns["ping_count_30s"].append(row[27])
        # Dual sliding window features - Long window (indices 28-30)
        columns["velocity_jitter_5m"].append(row[28])
        columns["bearing_volatility_5m"].append(row[29])
        columns["ping_count_5m"].append(row[30])
        # Derived spike detection ratios (indices 31-32)
        columns["jitter_ratio"].append(row[31])
        columns["volatility_ratio"].append(row[32])
        # Stop event features (indices 33-34)
        columns["is_stop_event"].append(bool(row[33]) if row[33] is not None else False)
        columns["stop_duration_sec"].append(row[34])
        # Choke point features (indices 35-36)
        columns["nearest_choke_point"].append(row[35])
        columns["nearest_choke_distance_m"].append(row[36])

    table = pa.table(columns, schema=EXPORT_SCHEMA)

    # Write Parquet with compression
    pq.write_table(
        table,
        output_path,
        compression="snappy",
        use_dictionary=True,
    )

    logger.info(f"Exported {len(rows)} rows to {output_path}")
    return len(rows)


async def export_to_csv(
    output_path: Path,
    user_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> int:
    """
    Export enriched ping data to CSV format.

    Wrapper around Parquet export that converts to CSV.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        count = await export_to_parquet(tmp_path, user_id, start_time, end_time)
        if count == 0:
            return 0

        # Read Parquet and write CSV
        table = pq.read_table(tmp_path)
        import pyarrow.csv as csv
        csv.write_csv(table, output_path)

        return count
    finally:
        tmp_path.unlink(missing_ok=True)
