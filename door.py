from flask import Flask, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from pathlib import Path
import requests
import threading
import hashlib
import tomllib
import json
import time
import os
import logging

logger = logging.getLogger("gunicorn.error")

# ── Config paths ──────────────────────────────────────────────────────────────
# Next to this file by default; override with DOOR_DIR
BASE_DIR    = Path(os.environ.get("DOOR_DIR", Path(__file__).resolve().parent))
CONFIG_PATH = BASE_DIR / "config.toml"
USERS_PATH  = BASE_DIR / "users.toml"
STATE_PATH  = BASE_DIR / "state.json"   # refresh token rotated by Netatmo

NETATMO_TOKEN_URL    = "https://app.netatmo.net/oauth2/token"
NETATMO_SETSTATE_URL = "https://app.netatmo.net/syncapi/v1/setstate"
NETATMO_USER_AGENT   = "NetatmoSecurity/6.15.0 (com.netatmo.camera; build:1155; iOS 26.0.0)"
HTTP_TIMEOUT         = 10  # seconds

# API values: "calle" = street door, "portal" = building gate, "ambas" = both
VALID_MODES = ("calle", "portal", "ambas")

# 🔑 Modes each user profile is allowed to use
PROFILES = {
    "total":   ("calle", "portal", "ambas"),
    "parcial": ("calle",),
}

# ── Config loading ────────────────────────────────────────────────────────────
def _load_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)

def _load_users() -> dict:
    """Returns {sha256(api_key): {"name", "profile"}} for active users."""
    users = {}
    for u in _load_toml(USERS_PATH).get("users", []):
        if u["profile"] not in PROFILES:
            raise ValueError(f"Unknown profile '{u['profile']}' for user '{u['name']}'")
        if not u.get("active", True):
            continue
        users[u["key_sha256"].lower()] = {"name": u["name"], "profile": u["profile"]}
    return users

def _read_initial_refresh_token() -> str:
    # If Netatmo already rotated the token, the current one lives in state.json
    try:
        with open(STATE_PATH) as f:
            return json.load(f)["refresh_token"]
    except FileNotFoundError:
        return NETATMO["refresh_token"]

def _save_refresh_token(token: str):
    tmp = STATE_PATH.with_suffix(".tmp")
    fd  = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"refresh_token": token}, f)
    os.replace(tmp, STATE_PATH)

CONFIG  = _load_toml(CONFIG_PATH)
NETATMO = CONFIG["netatmo"]
DOORS   = CONFIG["doors"]
PORTAL_DELAY_SECONDS = CONFIG.get("opening", {}).get("portal_delay_seconds", 16)
USERS   = _load_users()

app = Flask(__name__)
# Behind the reverse proxy: log the real client IP (X-Forwarded-For)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
logger.info(f"[INFO] Door service started - v2 (multi-user, {len(USERS)} active users)")

# ── Netatmo token (cached) ────────────────────────────────────────────────────
_token_lock          = threading.Lock()
_refresh_token       = _read_initial_refresh_token()
_access_token        = None
_access_token_expiry = 0.0

def _get_access_token() -> str:
    global _access_token, _access_token_expiry, _refresh_token
    with _token_lock:
        if _access_token and time.time() < _access_token_expiry:
            return _access_token

        resp = requests.post(NETATMO_TOKEN_URL, data={
            "grant_type":    "refresh_token",
            "client_id":     NETATMO["client_id"],
            "client_secret": NETATMO["client_secret"],
            "refresh_token": _refresh_token,
            "scope":         NETATMO["scope"]
        }, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data  = resp.json()
        token = data.get("access_token")
        if not token:
            raise ValueError("No access_token received")

        _access_token        = token
        _access_token_expiry = time.time() + int(data.get("expires_in", 3600)) - 120

        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != _refresh_token:
            _refresh_token = new_refresh
            try:
                _save_refresh_token(new_refresh)
                logger.info("[INFO] Netatmo rotated the refresh token; saved to state.json")
            except OSError as e:
                logger.error(f"[ERROR] Could not save the rotated refresh token: {e}")
        return token

def _invalidate_access_token():
    global _access_token
    with _token_lock:
        _access_token = None

# ── Business logic ────────────────────────────────────────────────────────────
def open_door(id: str) -> dict:
    if id not in DOORS:
        raise KeyError(f"Unknown door: '{id}'. Available: {list(DOORS)}")
    door = DOORS[id]

    for attempt in range(2):
        token = _get_access_token()
        resp = requests.post(
            NETATMO_SETSTATE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
                "User-Agent":    NETATMO_USER_AGENT
            },
            json={
                "home": {
                    "id": NETATMO["home_id"],
                    "modules": [{
                        "id":     door["device_id"],
                        "lock":   False,
                        "bridge": door["bridge_id"]
                    }]
                },
                "app_identifier": "app_security"
            },
            timeout=HTTP_TIMEOUT
        )
        # Cached token revoked/expired early: renew and retry once
        if resp.status_code in (401, 403) and attempt == 0:
            _invalidate_access_token()
            continue
        break

    resp.raise_for_status()
    return resp.json()

def _open_portal_delayed(user: str):
    time.sleep(PORTAL_DELAY_SECONDS)
    try:
        open_door("portal")
        logger.info(f"[OK] Portal door opened (delayed) by '{user}'")
    except Exception as e:
        logger.error(f"[ERROR] Could not open the portal automatically for '{user}': {e}")

def _authenticate(api_key: str | None) -> dict | None:
    if not api_key:
        return None
    # Lookup is by hash, so the plaintext key is never compared directly
    return USERS.get(hashlib.sha256(api_key.encode()).hexdigest())

# ── HTTP endpoint ─────────────────────────────────────────────────────────────
@app.route("/abrir", methods=["POST"])
def endpoint_open():
    user = _authenticate(request.headers.get("X-API-KEY"))
    if not user:
        logger.warning(f"[WARN] Request rejected: invalid API key (ip={request.remote_addr})")
        return jsonify({"error": "unauthorized"}), 403
    name = user["name"]

    data = request.get_json(silent=True) or {}
    mode = data.get("puerta")
    if not isinstance(mode, str) or not mode.strip():
        return jsonify({"error": "missing 'puerta' field"}), 400
    mode = mode.strip().lower()

    logger.info(f"[INFO] Request received: user='{name}' puerta='{mode}' ip={request.remote_addr}")

    if mode not in VALID_MODES:
        return jsonify({"error": f"invalid mode. Use: {VALID_MODES}"}), 400

    if mode not in PROFILES[user["profile"]]:
        logger.warning(f"[WARN] User '{name}' (profile {user['profile']}) not allowed to open '{mode}'")
        return jsonify({"error": "forbidden"}), 403

    try:
        if mode == "calle":
            # Opens only the street door, portal untouched
            result = open_door("calle")
            logger.info(f"[OK] Street door opened by '{name}'")
            return jsonify(result), 200

        elif mode == "portal":
            # Opens only the portal
            result = open_door("portal")
            logger.info(f"[OK] Portal door opened by '{name}'")
            return jsonify(result), 200

        elif mode == "ambas":
            # Opens the street door and, after the delay, the portal
            result = open_door("calle")
            logger.info(f"[OK] Street door opened by '{name}'. Portal will open in {PORTAL_DELAY_SECONDS}s")
            threading.Thread(target=_open_portal_delayed, args=(name,), daemon=True).start()
            return jsonify(result), 200

    except requests.HTTPError as e:
        logger.error(f"[ERROR] Netatmo returned an error: {e}")
        return jsonify({"error": "netatmo_error"}), 502
    except requests.RequestException as e:
        logger.error(f"[ERROR] Could not reach Netatmo: {e}")
        return jsonify({"error": "netatmo_unreachable"}), 504
    except Exception as e:
        logger.exception(f"[ERROR] Unexpected error: {e}")
        return jsonify({"error": "internal_error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
