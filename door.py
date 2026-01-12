from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# 🔐 Configure your credentials and system data 
NETATMO_CLIENT_ID = "na_client_ios_welcome"  # client_id from the official iphone app
NETATMO_CLIENT_SECRET = "xxxx"
NETATMO_REFRESH_TOKEN = "xxxx"
NETATMO_SCOPE = "security_scopes"

API_KEY = "yourrandomapikey"

HOME_ID = "xxxx"              # your home's ID 
CALLE_ID = "xxxx"           # id of any door
PORTAL_ID = "xxxxx"   # id of other door


PUERTAS = {
    "calle": {
        "device_id": "xxxx",
        "bridge_id": "xxxx"
    },
    "portal": {
        "device_id": "xxxx",
        "bridge_id": "xxxx"
    }
}

@app.route("/abrir", methods=["POST"])
def abrir_puerta():
    data = request.get_json()
    if request.headers.get("X-API-KEY") != API_KEY:
        return jsonify({"error": "unauthorized"}), 403

    puerta = data.get("puerta") if data else None

    if not puerta or puerta not in PUERTAS:
        return jsonify({"error": "puerta no válida", "puertas_disponibles": list(PUERTAS.keys())}), 400

    device_id = PUERTAS[puerta]["device_id"]
    bridge_id = PUERTAS[puerta]["bridge_id"]

    # Paso 1: Obtener access_token mediante refresh_token
    login_data = {
        "grant_type": "refresh_token",
        "client_id": NETATMO_CLIENT_ID,
        "client_secret": NETATMO_CLIENT_SECRET,
        "refresh_token": NETATMO_REFRESH_TOKEN,
        "scope": NETATMO_SCOPE
    }

    login_resp = requests.post("https://app.netatmo.net/oauth2/token", data=login_data)
    if login_resp.status_code != 200:
        return jsonify({"error": "login_failed", "details": login_resp.text}), 500

    access_token = login_resp.json().get("access_token")
    if not access_token:
        return jsonify({"error": "no_access_token"}), 500

    # Paso 2: Construir cuerpo de apertura
    open_data = {
        "home": {
            "id": HOME_ID,
            "modules": [
                {
                    "id": device_id,
                    "lock": False,  # False = desbloquear
                    "bridge": bridge_id
                }
            ]
        },
        "app_identifier": "app_security"
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "NetatmoSecurity/6.15.0 (com.netatmo.camera; build:1155; iOS 26.0.0)"
    }

    open_resp = requests.post("https://app.netatmo.net/syncapi/v1/setstate", headers=headers, json=open_data)

    try:
        resp_json = open_resp.json()
    except:
        resp_json = {"raw": open_resp.text}

    return jsonify({
        "status_code": open_resp.status_code,
        "response": resp_json
    }), open_resp.status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
