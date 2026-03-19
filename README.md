# Nanit — Home Assistant Integration

<p align="center">
  <img src="custom_components/nanit/brand/icon@2x.png" alt="Nanit" width="128" />
</p>

<p align="center">
  <em>Keep an eye on your little one — right from your Home Assistant dashboard.</em>
</p>

> [!NOTE]
> This is a fork of [wealthystudent/ha-nanit](https://github.com/wealthystudent/ha-nanit) with added **Nanit Sound + Light** support (power, sound track selection, volume).

---

## Entities

### Camera

| Type | Entity | Enabled by default |
|------|--------|--------------------|
| Camera | RTMPS live stream | Yes |
| Sensor | Temperature, Humidity, Light level | Yes |
| Binary Sensor | Motion, Sound (cloud-polled), Connectivity | Motion, Sound |
| Switch | Night Light, Camera Power | Yes |
| Number | Volume (0–100 %) | No |

### Sound + Light machine

The Nanit Sound + Light is a **separate device** from the camera. It connects to `wss://remote.nanit.com/speakers/...` using its own protobuf protocol (see [below](#sound--light-protocol)).

| Type | Entity | Enabled by default |
|------|--------|--------------------|
| Switch | Speaker Power (on/off) | Yes |
| Select | Sound Track | Yes |
| Number | Speaker Volume (0–100 %) | Yes |

> [!NOTE]
> Not all Nanit features are supported yet. If you'd like to add a missing feature, contributions are welcome — check the [AGENTS.md](AGENTS.md) guide for architecture details and development guidelines.

## Installation

### HACS (recommended)

1. Open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/briancoyne617/ha-nanit` as **Integration**.
3. Install **Nanit**, then restart Home Assistant.

### Manual

Copy `custom_components/nanit/` into your HA `config/custom_components/` directory and restart.

## Setup

1. **Settings → Devices & Services → Add Integration → Nanit**
2. Sign in with your Nanit email and password.
3. Enter the MFA code sent to your device.
4. *(Optional)* Enter your camera's local IP for faster, LAN-first connectivity.

| Field | Required | Description |
|-------|----------|-------------|
| Email | Yes | Nanit account email |
| Password | Yes | Nanit account password |
| Store credentials | No | Saves credentials for easier re-auth |
| Camera IP | No | LAN IP of the camera (port 442) |

## How it works

The integration communicates directly with the Nanit cloud and (optionally) your camera over the local network. No intermediary services.

```
Home Assistant              Nanit Camera (LAN)        Nanit Cloud
┌────────────┐  WebSocket   ┌──────────┐
│ nanit      │◄────────────►│ :442     │
│ integration│              └──────────┘
│            │  WebSocket + REST                      ┌─────────────────────┐
│ aionanit   │◄──────────────────────────────────────►│ api.nanit.com       │
│            │                                        │ remote.nanit.com    │
└────────────┘                                        └─────────────────────┘
                                                               ▲
                                                               │ WebSocket
                                                       ┌───────┴──────┐
                                                       │ Sound + Light│
                                                       │  (cloud only)│
                                                       └──────────────┘
```

| Mode | Description |
|------|-------------|
| **Camera cloud only** | Default. All camera communication via Nanit cloud. |
| **Camera local** | Cloud for auth and events, local WebSocket (:442) for camera sensors and controls. |
| **Speaker** | Always cloud (`wss://remote.nanit.com/speakers/...`). The speaker's port 442 is its outbound connection to the cloud, not for inbound app control. |

## Sound + Light Protocol

The Sound + Light machine uses a **completely different WebSocket endpoint and protobuf schema** from the camera — this tripped up early development significantly.

| | Camera | Sound + Light |
|---|---|---|
| WebSocket host | `api.nanit.com` | `remote.nanit.com` |
| Path | `/focus/cameras/{uid}/user_connect` | `/speakers/{uid}/user_connect/` |
| Proto schema | `aionanit/proto/` (in the `aionanit` package) | `sound_light_pb2.py` (bundled here) |
| Local access | Yes, via LAN IP on port 442 | No — cloud only |

### `sound_light_pb2.py`

`custom_components/nanit/sound_light_pb2.py` is a compiled Python protobuf module for the Sound + Light device. It was reverse-engineered from the Nanit Android APK by [com6056/nanit-sound-light](https://github.com/com6056/nanit-sound-light) (MIT License).

**You should never need to edit this file by hand.** If Nanit changes their protocol, regenerate it:

```bash
# 1. Update the .proto definition (see the comment block at the top of the file)
# 2. Install the compiler
pip install grpcio-tools
# 3. Regenerate (run from the custom_components/nanit/ directory)
python -m grpc_tools.protoc -I. --python_out=. sound_light.proto
# 4. Remove the ValidateProtobufRuntimeVersion call from the generated file
#    (it breaks on older protobuf versions that HA may ship)
```

The full `.proto` source is documented in the comment block at the top of `sound_light_pb2.py`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Integration won't load | Check **Settings → System → Logs** and filter for `nanit`. |
| MFA code rejected | Codes expire quickly — use the latest one and finish setup promptly. |
| Stream not playing | Streams start on demand. Verify HA can reach `rtmps://media-secured.nanit.com`. |
| Sensors unavailable | The WebSocket may have dropped. It reconnects automatically — check logs. |
| Local connection failing | Confirm the camera IP is correct and port 442 is reachable from HA. |

## Requirements

- Home Assistant **2025.12** or newer
- A Nanit account with email/password
- HACS (recommended) or manual file access

## License

MIT
