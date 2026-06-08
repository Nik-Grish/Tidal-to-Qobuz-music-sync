# Tidal-to-Qobuz-music-sync

A lightweight Python script that syncs your **Tidal liked tracks** to **Qobuz favorites** — for free, without any third-party services.

No Soundiiz. No TuneMyMusic. No subscriptions. Just your own credentials talking directly to both APIs.

To use the app it is required to have an active subscription to both Tidal and Qobuz.
---

## How it works

1. Reads all liked tracks from your Tidal account via the unofficial [`tidalapi`](https://github.com/tamland/python-tidal) library
2. Searches each track in Qobuz — first by **ISRC** (the most reliable match), then falls back to fuzzy **text search** with normalization (strips "Remaster", "Album Version", "Deluxe", etc.)
3. Adds found tracks to your Qobuz favorites
4. Saves state to `synced_tracks.json` — re-running is always safe, duplicates are skipped

---

## Requirements

- Python 3.10+
- Active Tidal subscription
- Active Qobuz subscription

```bash
pip install tidalapi requests
```

---

## Setup

### 1. Get your Qobuz token

Qobuz no longer accepts password-based login via its public API. Instead, grab your session token from DevTools:

1. Open [play.qobuz.com](https://play.qobuz.com) in Chrome/Firefox
2. Open DevTools → **Network** tab
3. Log in to your Qobuz account
4. Find the `user/login` request in the network log
5. Click it → **Response** tab → copy the `user_auth_token` value
6. Also grab `X-App-Id` from the **Request Headers** tab

> **Note:** The token expires after some time. When it does, the script will tell you and exit with instructions to get a new one.

### 2. Configure the script

Open `tidal_to_qobuz.py` and fill in:

```python
QOBUZ_APP_ID     = "your_app_id"     # X-App-Id from DevTools → Request Headers
QOBUZ_USER_TOKEN = "your_token"      # user_auth_token from DevTools → Response
```

### 3. Run

```bash
python3 tidal_to_qobuz.py
```

On **first run**, the script will print a Tidal OAuth link — open it in your browser and confirm. The session is then cached in `tidal_session.json` and reused on subsequent runs.

---

## Usage

### Normal sync

```bash
python3 tidal_to_qobuz.py
```

Syncs all new liked tracks from Tidal to Qobuz. Already synced tracks are skipped.

### Retry failed tracks

```bash
python3 tidal_to_qobuz.py --retry
```

Re-attempts tracks from `failed_tracks.json` (tracks that weren't found in the Qobuz catalog on a previous run). Useful after updating the matching logic or waiting for catalog updates.

### Automate with cron

To sync automatically once a day at 9am:

```bash
crontab -e
# Add this line:
0 9 * * * python3 /path/to/tidal_to_qobuz.py >> /path/to/sync.log 2>&1
```

---

## Output files

| File | Description |
|------|-------------|
| `tidal_session.json` | Cached Tidal OAuth session (don't share) |
| `synced_tracks.json` | ISRCs of all successfully synced tracks |
| `failed_tracks.json` | Tracks not found in the Qobuz catalog |

---

## Matching logic

Tracks are matched in two steps:

1. **ISRC lookup** — every track has an International Standard Recording Code. When Qobuz has the same release, this gives a 100% accurate match.
2. **Fuzzy text search** — for tracks without ISRC or when ISRC lookup fails. The title and artist are normalized before comparison:
   - Unicode → ASCII transliteration
   - Lowercased
   - Parenthetical suffixes stripped: `(Remaster)`, `[Deluxe Edition]`, etc.
   - Dash suffixes stripped: `Title - Album Version` → `Title`
   - Noise words removed: `album`, `version`, `remaster`, `live`, `edit`, `remix`, etc.

---

## Why some tracks may not be found

- The track simply isn't in the Qobuz catalog (label licensing, regional restrictions)
- Artist or track name differs significantly between platforms
- The release is Tidal-exclusive

All unmatched tracks are saved to `failed_tracks.json` for manual review.

---

## License

MIT
