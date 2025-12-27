# OwnTracks Setup Guide for Project Pepper

This guide explains how to configure OwnTracks on your phone to send GPS data to your Project Pepper server.

## Prerequisites

1. **OwnTracks App Installed**
   - iOS: [App Store](https://apps.apple.com/app/owntracks/id692424691)
   - Android: [Google Play](https://play.google.com/store/apps/details?id=org.owntracks.android)

2. **Project Pepper Server Running**
   - Your server URL (e.g., `https://pepper.onrender.com`)

3. **API Key** (Required for security)
   - Your `PEPSAFE_API_KEY` from your server configuration

---

## Step 1: Configure HTTP Mode with API Key

OwnTracks supports two modes: MQTT (default) and HTTP. We'll use HTTP mode with API key authentication.

### iOS Setup

1. Open OwnTracks app
2. Tap the **info (i) button** in the top-left
3. Tap **Settings**
4. Tap **Mode** → Select **HTTP**
5. Configure the following:

| Setting | Value |
|---------|-------|
| **URL** | `https://YOUR_SERVER/api/v1/ping/owntracks` |
| **User ID** | `pepper` |
| **Device ID** | `phone` (or your device name) |

6. **Add API Key Header** (IMPORTANT):
   - Scroll down to **HTTP Headers** (or **Custom Headers**)
   - Add a new header:
     - **Name**: `X-API-KEY`
     - **Value**: `YOUR_PEPSAFE_API_KEY`

### Android Setup

1. Open OwnTracks app
2. Tap the **hamburger menu (☰)** in the top-left
3. Tap **Preferences**
4. Tap **Connection**
5. Tap **Mode** → Select **HTTP**
6. Configure:

| Setting | Value |
|---------|-------|
| **Host** | `https://YOUR_SERVER/api/v1/ping/owntracks` |
| **Identification → Username** | `pepper` |
| **Identification → Device ID** | `phone` |

7. **Add API Key Header** (IMPORTANT):
   - In Connection settings, find **Headers** or **Custom Headers**
   - Add:
     - **Header Name**: `X-API-KEY`
     - **Header Value**: `YOUR_PEPSAFE_API_KEY`

> **Security Note**: Without the correct API key, your requests will be rejected with a 401 Unauthorized error.

---

## Step 2: Configure Location Tracking

### Recommended Settings for Dog Walks

| Setting | Value | Reason |
|---------|-------|--------|
| **Monitoring Mode** | **Significant** or **Move** | Balance between accuracy and battery |
| **Minimum Distance** | `10` meters | Captures walk path detail |
| **Minimum Time** | `5` seconds | High-frequency for reactivity detection |

### For Maximum Accuracy (Battery Heavy)

| Setting | Value |
|---------|-------|
| **Monitoring Mode** | Move |
| **Minimum Distance** | 5 meters |
| **Minimum Time** | 3 seconds |

---

## Step 3: Test the Connection

1. **In OwnTracks**: Go to the map view and force a location publish:
   - iOS: Tap the **publish button** (arrow icon)
   - Android: Long-press on your location marker

2. **Check your server**:
   ```bash
   curl https://YOUR_SERVER/health/pepper
   ```

3. **Expected response** (after first ping):
   ```json
   {
     "status": "active",
     "risk_score": 12.5,
     "risk_level": "LOW",
     "risk_emoji": "ok",
     "last_ping": "2024-06-15T14:30:00Z",
     "minutes_ago": 0,
     "features": {
       "jitter_30s": 0.42,
       "volatility_30s": 8.5,
       ...
     }
   }
   ```

---

## OwnTracks Payload Format

OwnTracks sends location data in this format:

```json
{
  "_type": "location",
  "lat": 32.0853,
  "lon": 34.7818,
  "vel": 5,          // velocity in km/h (converted to m/s by server)
  "cog": 180,        // course over ground (bearing) in degrees
  "acc": 10,         // accuracy in meters
  "tst": 1718451000, // Unix timestamp
  "tid": "PP",       // tracker ID (2 chars)
  "batt": 85         // battery percentage
}
```

The Project Pepper server automatically:
- Converts `vel` from km/h to m/s
- Maps `cog` to bearing
- Extracts user from the URL or `tid`

---

## Quick Reference: Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/ping/owntracks` | POST | OwnTracks webhook (automatic) |
| `/api/v1/ping` | POST | Direct GPS ping submission |
| `/health/pepper` | GET | Check Pepper's current risk score |
| `/health` | GET | Server health check |
| `/docs` | GET | API documentation (Swagger) |

---

## Troubleshooting

### "No data available for Pepper"

- Ensure OwnTracks is in HTTP mode
- Check the URL is correct (include `/api/v1/ping/owntracks`)
- Force a location publish and check server logs

### "Connection refused"

- Verify your server is running
- Check HTTPS certificate is valid
- Ensure firewall allows traffic on port 443

### Pings not appearing in real-time

- OwnTracks batches requests to save battery
- Force a manual publish to test immediately
- Check "Minimum Time" setting isn't too high

### Home zone pings being recorded

- Verify `PEPPER_HOME_LAT` and `PEPPER_HOME_LON` are set correctly
- Check `HOME_ZONE_RADIUS_METERS` (default 50m)
- Home zone pings are intentionally dropped for privacy

---

## Battery Optimization Tips

1. **Use "Significant" mode** when not actively walking
2. **Switch to "Move" mode** only during walks
3. **Increase minimum distance** to 20-50m for casual monitoring
4. **Use regions** to auto-switch modes when leaving home

---

## Alternative: Tasker Integration (Android)

For more control, use Tasker with HTTP Request action:

```
Task: Send GPS to Pepper
  1. HTTP Request
     Method: POST
     URL: https://YOUR_SERVER/api/v1/ping
     Headers:
       Content-Type: application/json
       X-API-KEY: YOUR_PEPSAFE_API_KEY
     Body: {
       "user": "pepper",
       "lat": %LOCN_LAT,
       "lon": %LOCN_LON,
       "speed": %LOCN_SPD,
       "bearing": %LOCN_BEAR,
       "accuracy": %LOCN_ACC,
       "timestamp": "%TIMES"
     }
```

Trigger: Every 5 seconds when GPS is active

> **Important**: Replace `YOUR_PEPSAFE_API_KEY` with your actual API key. Store it as a Tasker variable for security.

---

## Mobile Browser Bookmark

For quick risk checks during walks, bookmark this URL:

```
https://YOUR_SERVER/health/pepper
```

The response is JSON but readable. For a nicer view, use:

```
https://YOUR_SERVER/docs#/default/pepper_status_health_pepper_get
```

---

## Support

- **OwnTracks Documentation**: https://owntracks.org/booklet/
- **Project Pepper Issues**: Check your server logs
- **API Docs**: `https://YOUR_SERVER/docs`
