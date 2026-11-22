# Solar Water & Irrigation Demo

A hackathon demonstration of a solar-powered water station with reverse osmosis,
elevated storage, drip irrigation, and simulated irrigation-zone monitoring.

## Important

This project is a simulator. It does not connect to ESP32 sensors or control real
pumps, valves, or other hardware. Mobile valve commands affect only the Python
simulation. Hardware must not be connected without a separately designed and tested
controller, safety interlocks, and communications protocol.

## Windows desktop station

Install Python 3.8 or newer, then install the Python dependency from this folder:

```text
python -m pip install -r requirements.txt
```

Start the station with:

```text
python station_irrigation_scada.py
```

The desktop app shows the simulation and starts a local phone server. For phone
connectivity, allow Python on the private network in Windows Firewall.

## Android app

See [mobile_app/README.md](./mobile_app/README.md) for Expo Go setup, connecting
to the station over the same Wi-Fi, and Android build instructions.

## Project contents

- `station_irrigation_scada.py` — Python desktop simulator and local phone API.
- `mobile_app/` — Expo / React Native companion app.
- `requirements.txt` — Python dependencies.
