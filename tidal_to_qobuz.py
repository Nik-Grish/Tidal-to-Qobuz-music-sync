#!/usr/bin/env python3
"""
Tidal → Qobuz  |  Favorites Sync
==================================
Reads all liked tracks from Tidal and adds them to Qobuz favorites.
Re-running is safe — already synced tracks are skipped.

Requirements:
    pip install tidalapi requests

Qobuz auth:
    Token is taken from browser DevTools (Network tab → user/login request
    → Response → user_auth_token field). Expires periodically — grab a new one when needed.

Tidal auth:
    On first run, a browser link will be shown — confirm it in the browser.
    Session is cached in tidal_session.json, no re-login needed afterwards.
"""

import json
import os
import time
import unicodedata
import re
import sys

import requests
import tidalapi

# ─────────────────────────────────────────────
# CONFIGURATION — fill in before running
# ─────────────────────────────────────────────

QOBUZ_APP_ID     = "798273057"       # X-App-Id from DevTools → Network → Request Headers
QOBUZ_USER_TOKEN = "YOUR_TOKEN_HERE" # user_auth_token from DevTools → Network → Response

TIDAL_SESSION_FILE = "tidal_session.json"  # cached Tidal OAuth session
STATE_FILE         = "synced_tracks.json"  # ISRCs of already synced tracks
FAILED_FILE        = "failed_tracks.json"  # tracks not found in Qobuz catalog

# Delay between Qobuz API requests (seconds) — be polite to the API
REQUEST_DELAY = 0.5

# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def normalize(text: str) -> str:
    """Normalize a string for fuzzy comparison."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[\(\[].*?[\)\]]", "", text)       # strip (Remaster), [Deluxe], etc.
    text = re.sub(r"\s*[-–—]\s*.*$", "", text)        # strip everything after a dash: "Title - Album Version"
    # strip common suffix noise words
    noise = r"\b(album|single|radio|live|acoustic|original|version|edit|remaster|remastered|remix|mix|cut|demo|bonus|track)\b"
    text = re.sub(noise, "", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    text = re.sub(r"\s+", " ", text)                  # collapse multiple spaces
    return text.strip()


def load_state() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()


def save_state(synced: set):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(synced), f, indent=2)


# ─────────────────────────────────────────────
# TIDAL
# ─────────────────────────────────────────────

def get_tidal_session() -> tidalapi.Session:
    session = tidalapi.Session()

    if os.path.exists(TIDAL_SESSION_FILE):
        with open(TIDAL_SESSION_FILE) as f:
            data = json.load(f)
        try:
            session.load_oauth_session(
                data["token_type"],
                data["access_token"],
                data["refresh_token"],
                data.get("expiry_time"),
            )
            if session.check_login():
                print("✅ Tidal: session restored from cache")
                return session
        except Exception:
            print("⚠️  Tidal: cached session expired, re-authenticating")

    # OAuth login via browser
    print("\n🔐 Tidal: open the link below in your browser and confirm:")
    login, future = session.login_oauth()
    print(f"\n   👉  {login.verification_uri_complete}\n")
    future.result()

    # Save session to disk
    with open(TIDAL_SESSION_FILE, "w") as f:
        json.dump(
            {
                "token_type":    session.token_type,
                "access_token":  session.access_token,
                "refresh_token": session.refresh_token,
                "expiry_time":   str(session.expiry_time),
            },
            f,
            indent=2,
        )
    print(f"✅ Tidal: authenticated, session saved to {TIDAL_SESSION_FILE}")
    return session


def get_tidal_favorites(session: tidalapi.Session) -> list[dict]:
    """Return all liked tracks from Tidal."""
    print("\n📥 Tidal: fetching liked tracks...")
    favorites = tidalapi.user.Favorites(session, session.user.id)
    tracks = favorites.tracks(limit=9999)

    result = []
    for track in tracks:
        result.append(
            {
                "title":    track.name,
                "artist":   track.artist.name if track.artist else "",
                "album":    track.album.name if track.album else "",
                "isrc":     track.isrc or "",
                "tidal_id": str(track.id),
            }
        )

    print(f"   Found: {len(result)} tracks")
    return result


# ─────────────────────────────────────────────
# QOBUZ
# ─────────────────────────────────────────────

class QobuzClient:
    BASE = "https://www.qobuz.com/api.json/0.2"

    def __init__(self, app_id: str, user_auth_token: str):
        self.app_id = app_id
        self.session = requests.Session()
        self.session.headers.update({
            "X-App-Id":          app_id,
            "X-User-Auth-Token": user_auth_token,
        })
        # Validate token
        resp = self.session.get(
            f"{self.BASE}/user/get",
            params={"app_id": self.app_id},
        )
        if resp.status_code == 401:
            print("\n❌ Qobuz: token expired!")
            print("   Open qobuz.com → DevTools → Network tab")
            print("   Log in → find user/login request → Response tab")
            print("   Copy user_auth_token and paste it into QOBUZ_USER_TOKEN\n")
            sys.exit(1)
        elif resp.status_code != 200:
            print(f"\n❌ Qobuz: token validation failed ({resp.status_code})")
            sys.exit(1)

        display_name = resp.json().get("display_name", "—")
        print(f"✅ Qobuz: authenticated as {display_name}")

    def get_favorite_track_ids(self) -> set[str]:
        """Fetch all track IDs already in Qobuz favorites."""
        print("📥 Qobuz: fetching existing favorites...")
        ids = set()
        offset = 0
        limit  = 500
        while True:
            resp = self.session.get(
                f"{self.BASE}/favorite/getUserFavorites",
                params={"type": "tracks", "limit": limit, "offset": offset, "app_id": self.app_id},
            )
            resp.raise_for_status()
            data  = resp.json().get("tracks", {})
            items = data.get("items", [])
            for t in items:
                ids.add(str(t["id"]))
            offset += len(items)
            if offset >= data.get("total", 0):
                break
        print(f"   Already in favorites: {len(ids)} tracks")
        return ids

    def search_track_by_isrc(self, isrc: str) -> str | None:
        """Look up a track by ISRC — most reliable matching method."""
        resp = self.session.get(
            f"{self.BASE}/track/search",
            params={"isrc": isrc, "app_id": self.app_id, "limit": 1},
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("tracks", {}).get("items", [])
        return str(items[0]["id"]) if items else None

    def search_track_by_text(self, title: str, artist: str) -> str | None:
        """Fallback text search with fuzzy normalization."""
        query = f"{artist} {title}".strip()
        resp  = self.session.get(
            f"{self.BASE}/track/search",
            params={"query": query, "app_id": self.app_id, "limit": 10},
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("tracks", {}).get("items", [])
        norm_title  = normalize(title)
        norm_artist = normalize(artist)
        # Strict match: title + artist
        for item in items:
            t_title  = normalize(item.get("title", ""))
            t_artist = normalize(item.get("performer", {}).get("name", ""))
            if t_title == norm_title and t_artist == norm_artist:
                return str(item["id"])
        # Soft match: title only
        for item in items:
            if normalize(item.get("title", "")) == norm_title:
                return str(item["id"])
        return None

    def add_to_favorites(self, track_id: str) -> bool:
        resp = self.session.get(
            f"{self.BASE}/favorite/create",
            params={"track_ids": track_id, "app_id": self.app_id},
        )
        return resp.status_code == 200


# ─────────────────────────────────────────────
# MAIN LOGIC
# ─────────────────────────────────────────────

def sync():
    print("=" * 55)
    print("  Tidal → Qobuz  |  Favorites Sync")
    print("=" * 55)

    # Guard: token must be set
    if QOBUZ_USER_TOKEN == "YOUR_TOKEN_HERE":
        print("\n❌ Please set QOBUZ_USER_TOKEN in the script config!\n")
        sys.exit(1)

    # 1. Load state from previous runs
    synced_isrcs = load_state()
    print(f"\n📂 Previously synced: {len(synced_isrcs)} tracks")

    # 2. Connect to Tidal
    tidal = get_tidal_session()
    tidal_tracks = get_tidal_favorites(tidal)

    # 3. Filter — keep only new tracks
    new_tracks = [t for t in tidal_tracks if t["isrc"] not in synced_isrcs]
    print(f"   New to sync: {len(new_tracks)}")

    if not new_tracks:
        print("\n✅ Everything is already synced. Nothing to do.")
        return

    # 4. Connect to Qobuz
    print()
    qobuz = QobuzClient(QOBUZ_APP_ID, QOBUZ_USER_TOKEN)
    existing_qobuz_ids = qobuz.get_favorite_track_ids()

    # 5. Sync
    print(f"\n🔄 Syncing {len(new_tracks)} tracks...\n")

    added = skipped = not_found = errors = 0
    failed_tracks = []

    for i, track in enumerate(new_tracks, 1):
        label = f"[{i}/{len(new_tracks)}] {track['artist']} — {track['title']}"
        sys.stdout.write(f"  {label[:65]:<65}")
        sys.stdout.flush()

        # Primary: search by ISRC
        qobuz_id = None
        if track["isrc"]:
            qobuz_id = qobuz.search_track_by_isrc(track["isrc"])

        # Fallback: text search
        if not qobuz_id:
            qobuz_id = qobuz.search_track_by_text(track["title"], track["artist"])

        if not qobuz_id:
            print("  ⚠️  not found")
            not_found += 1
            failed_tracks.append(track)
        elif qobuz_id in existing_qobuz_ids:
            print("  ⏭  already in favorites")
            skipped += 1
            synced_isrcs.add(track["isrc"])
        else:
            ok = qobuz.add_to_favorites(qobuz_id)
            if ok:
                print("  ✅ added")
                added += 1
                existing_qobuz_ids.add(qobuz_id)
                synced_isrcs.add(track["isrc"])
            else:
                print("  ❌ error")
                errors += 1

        time.sleep(REQUEST_DELAY)

        # Checkpoint save every 25 tracks
        if i % 25 == 0:
            save_state(synced_isrcs)

    # 6. Final save
    save_state(synced_isrcs)
    with open(FAILED_FILE, "w") as f:
        json.dump(failed_tracks, f, indent=2, ensure_ascii=False)

    # 7. Summary
    print(f"""
{'─' * 55}
  ✅ Added:           {added}
  ⏭  Already existed: {skipped}
  ⚠️  Not found:       {not_found}
  ❌ Errors:          {errors}
{'─' * 55}
  State saved to {STATE_FILE}
""")

    if not_found > 0:
        print("  Tip: tracks not found may be missing from the Qobuz catalog.")
        print(f"  Full list saved to {FAILED_FILE}")
        print(f"  Retry with: python3 tidal_to_qobuz.py --retry\n")


# ─────────────────────────────────────────────

def retry_failed():
    """Retry tracks from failed_tracks.json with current matching logic."""
    if not os.path.exists(FAILED_FILE):
        print(f"No {FAILED_FILE} found — nothing to retry.")
        return

    with open(FAILED_FILE) as f:
        failed = json.load(f)

    if not failed:
        print("✅ No failed tracks to retry.")
        return

    print(f"🔄 Retrying {len(failed)} tracks...\n")

    if QOBUZ_USER_TOKEN == "YOUR_TOKEN_HERE":
        print("❌ Please set QOBUZ_USER_TOKEN!\n")
        sys.exit(1)

    synced_isrcs = load_state()
    qobuz = QobuzClient(QOBUZ_APP_ID, QOBUZ_USER_TOKEN)
    existing_qobuz_ids = qobuz.get_favorite_track_ids()

    still_failed = []
    added = 0

    for track in failed:
        label = f"{track['artist']} — {track['title']}"
        sys.stdout.write(f"  {label[:65]:<65}")
        sys.stdout.flush()

        qobuz_id = qobuz.search_track_by_isrc(track["isrc"]) if track["isrc"] else None
        if not qobuz_id:
            qobuz_id = qobuz.search_track_by_text(track["title"], track["artist"])

        if not qobuz_id:
            print("  ⚠️  still not found")
            still_failed.append(track)
        elif qobuz_id in existing_qobuz_ids:
            print("  ⏭  already in favorites")
            synced_isrcs.add(track["isrc"])
        else:
            ok = qobuz.add_to_favorites(qobuz_id)
            if ok:
                print("  ✅ added")
                added += 1
                synced_isrcs.add(track["isrc"])
                existing_qobuz_ids.add(qobuz_id)
            else:
                print("  ❌ error")
                still_failed.append(track)
        time.sleep(REQUEST_DELAY)

    save_state(synced_isrcs)
    with open(FAILED_FILE, "w") as f:
        json.dump(still_failed, f, indent=2, ensure_ascii=False)

    print(f"\n{'─' * 55}")
    print(f"  ✅ Added:          {added}")
    print(f"  ⚠️  Still missing: {len(still_failed)}")
    print(f"{'─' * 55}\n")


if __name__ == "__main__":
    if "--retry" in sys.argv:
        retry_failed()
    else:
        sync()
