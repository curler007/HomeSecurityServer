# Home + Security Door Unlock Server

## Project Overview

The goal of this project is to simplify the process of opening a door using the Netatmo system. In my case, I have a **Bticino doorbell** integrated with Netatmo.

My initial idea was to install custom firmware on the doorbell itself (thanks to the Telegram group https://t.me/bTicinoClasse300x). Unfortunately, this attempt resulted in a **bricked doorbell**, so I decided to change my strategy.

Instead of modifying the hardware, this project replaces the need to manually use the official Netatmo mobile application by exposing a small Python server that can be triggered externally (for example, via Siri Shortcuts).

---

## How the Official App Works

When using the official Netatmo app, **Home + Security**, the process to open the door is the following:

1. Unlock your phone  
2. Open the *Home + Security* app  
3. Slide the key button to unlock the door  

<!-- Screenshot of the official app -->

While this works, it is not very convenient for daily use.

---

## Motivation

If we can encapsulate this entire process into an **iOS Shortcut**, we can open the door simply by saying:

> “Hey Siri, outside door”

This also enables additional options:

- Trigger the shortcut from an **Apple Watch**
- Use **Siri voice commands**
- Assign the shortcut to a **custom gesture** or automation

All of this makes opening the door significantly faster and more convenient.

<!-- Screenshot of the iOS Shortcuts configuration -->

---

## Solution

This project implements a **lightweight Python server** that mimics the behavior of the official Netatmo mobile app.  
By calling this server from an iOS Shortcut, the door can be opened without manually interacting with the Netatmo app.

---

## Requirements

To use this project, you will need:

- An **iPhone** (with Siri Shortcuts enabled)
- A **server** (VPS, Raspberry Pi, or similar) capable of running Python
- Your **Netatmo account**
- Network access between your iPhone and the server
- A reverse proxy with HTTPS in front of the server

---

## What's New in v2

- **Multiple users**: every user has their own API key and a permission profile.
- **Secrets out of the code**: credentials and device IDs live in `config.toml`, users in `users.toml` (both git-ignored).
- **Street door + portal**: open the street door, the building portal, or both in sequence (the portal opens automatically after a configurable delay).
- **Refresh token rotation**: if Netatmo issues a new refresh token, it is persisted to `state.json`.
- **Access token caching**, request timeouts and a single automatic retry on expired tokens.
- **Audit log**: every request is logged with the user name and the client IP.

---

## Project Structure

| File | Purpose |
|---|---|
| `door.py` | Flask API |
| `manage_users.py` | CLI to add, rotate, disable and remove users |
| `config.example.toml` | Template for `config.toml` (Netatmo credentials, home and door IDs) |
| `users.example.toml` | Example of the `users.toml` format |
| `door.service.example` | Example systemd unit |
| `state.json` | Created at runtime when Netatmo rotates the refresh token |

---

## Installation

```bash
git clone -b v2 https://github.com/curler007/HomeSecurityServer.git door
cd door
python3 -m venv ../venv
../venv/bin/pip install -r requirements.txt

cp config.example.toml config.toml
chmod 600 config.toml
# edit config.toml with your Netatmo data (see "Authentication Notes")

../venv/bin/python manage_users.py add alice --profile total
```

Requires **Python 3.11+** (uses `tomllib`).

Run it with gunicorn behind a reverse proxy with HTTPS (nginx, Caddy…). Use a **single worker** (`-w 1`): the delayed portal opening runs in a background thread of that worker.

```bash
../venv/bin/gunicorn -w 1 -b 127.0.0.1:5000 door:app
```

See `door.service.example` to run it as a systemd service. By default the config files are read from the directory containing `door.py`; set `DOOR_DIR` to use another one.

---

## Users and Profiles

| Profile | Allowed modes |
|---|---|
| `total` | `calle`, `portal`, `ambas` |
| `parcial` | `calle` |

```bash
python manage_users.py list
python manage_users.py add bob --profile parcial   # prints bob's API key once
python manage_users.py rotate bob                   # new key, the old one stops working
python manage_users.py profile bob total
python manage_users.py disable bob
python manage_users.py enable bob
python manage_users.py remove bob
```

Only the SHA-256 hash of each key is stored in `users.toml`. Restart the service after any change.

---

## API

`POST /abrir` with header `X-API-KEY: <your key>` and JSON body:

```json
{ "puerta": "calle" }
```

| `puerta` | Action |
|---|---|
| `calle` | Opens the street door |
| `portal` | Opens the building portal |
| `ambas` | Opens the street door, then the portal after `portal_delay_seconds` |

| Status | Meaning |
|---|---|
| `200` | Door opened (Netatmo response in the body) |
| `400` | Missing or invalid `puerta` |
| `403` | Invalid API key, or the user's profile does not allow that mode |
| `502` / `504` | Netatmo returned an error / could not be reached |

```bash
curl -X POST https://your-server/abrir \
  -H "X-API-KEY: <your key>" -H "Content-Type: application/json" \
  -d '{"puerta": "ambas"}'
```

In an iOS Shortcut, use **Get Contents of URL** with method `POST`, a `X-API-KEY` header and a JSON body with the `puerta` field.

---

## Logs

When running under systemd, logs go to the journal:

```bash
journalctl -u door -f
```

---

## Authentication Notes

To interact with the Netatmo private API, you must first extract the required **private keys and tokens** so the server can impersonate the official iOS application.

To do this, you will need:

- **Charles Proxy** (free version is sufficient)

Charles Proxy is used to intercept the HTTPS traffic generated by the Netatmo app in order to retrieve the necessary authentication data.

> ⚠️ **Security warning**  
> These credentials grant full access to your Netatmo account.  
> Do not share them, and never expose your server publicly without proper authentication.

---

## Disclaimer

This project is **not affiliated with or endorsed by Netatmo**.  
It relies on reverse engineering of private APIs, which may change at any time and could stop working without notice.

Use this software at your own risk.
