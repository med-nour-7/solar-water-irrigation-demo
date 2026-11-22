#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCADA / HMI — Station solaire, eau et irrigation
================================================

Démo hackathon :
  puits → pompe solaire → osmose inverse → réservoir à 5 m → goutte-à-goutte.
  La saumure (concentrat de l'osmose) refroidit les panneaux.

La météo du site utilise les coordonnées saisies dans l'interface. La page
téléphone (même Wi-Fi) affiche les mesures et les alertes de la station.

Dépendances :  Python 3.8+  ,  matplotlib   (pip install matplotlib)
Lancement :    python station_irrigation_scada.py
"""

import csv
import json
import math
import queue
import random
import socket
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from typing import Literal

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# ----------------------------------------------------------------------------
# Paramètres généraux
# ----------------------------------------------------------------------------
TANK_CAP = 5000.0          # capacité du réservoir (L)
TANK_ELEV = 5.0            # réservoir surélevé de 5 m (alimentation gravitaire)
TANK_WATER_H = 3.0         # hauteur d'eau utile dans le réservoir (m)
WELL_VOL = 12000.0         # volume utile du puits (L)
WELL_MIN = 8.0             # niveau minimal du puits (%)
PRESSURE_LOW = 0.28        # sous ce seuil (bar) la distribution est insuffisante
ZONE_FLOW_MIN_RATIO = 0.30 # débit minimum mesuré par rapport au débit attendu
IRRIGATION_CHECK_MIN = 4.0 # durée avant vérification de la réponse du sol (min)
MOISTURE_GAIN_MIN = 0.5    # hausse minimale mesurée après irrigation (%)

PV_AREA = 15.0             # surface des panneaux (m2)
PV_ETA = 0.19              # rendement nominal (STC)
PV_TEMP_COEF = 0.004       # perte de rendement par °C au-dessus de 25 °C
COOL_ON = 60.0             # seuil d'enclenchement du refroidissement (°C)
COOL_OFF = 52.0            # seuil d'arrêt du refroidissement (°C)
COOL_FLOW = 8.0            # débit de saumure qui assure le plein refroidissement (L/min)
BRINE_MIN = 1.5            # saumure minimale pour enclencher le refroidissement (L/min)

PUMP_MAX_FLOW = 80.0       # débit nominal de la pompe (L/min)
PUMP_POWER = 1200.0        # puissance pompe (W)
DESAL_POWER = 600.0        # puissance dessalement (W)
MIN_PUMP_POWER = 900.0     # puissance solaire minimale pour démarrer (W)
PUMP_START_PCT = 85.0      # la pompe démarre sous ce niveau de réservoir (%)
PUMP_STOP_PCT = 98.0       # la pompe s'arrête au-dessus de ce niveau (%)
DESAL_FAULT = 55.0         # efficacité sous laquelle le dessalement est en défaut

ZONE_FLOW = 12.0           # débit d'un secteur goutte-à-goutte ouvert (L/min)
IRRIG_RATE = 0.55          # gain d'humidité en irrigation (%/min)
LEAK_FLOW = 10.0           # débit de fuite simulé (L/min)
HUM_OPEN = 40.0            # ouverture automatique de la ligne sous ce seuil (%)
HUM_CLOSE = 70.0           # fermeture automatique de la ligne au-dessus (%)
MAX_OPEN_VALVES = 2        # nombre maximal de lignes ouvertes simultanément
TARGET_HUM = 70.0          # humidité cible pour le calcul du besoin en eau

HISTORY_LEN = 3600         # nombre de points conservés en historique
CHART_POINTS = 180         # nombre de points affichés sur la courbe
PHONE_PORT = 8765
DEFAULT_LAT = 36.8065      # Tunis, en attendant le GPS du téléphone
DEFAULT_LON = 10.1815

THEME = {
    "bg": "#f3f6fa",
    "card": "#ffffff",
    "card2": "#f6f8fb",
    "line": "#d5dee8",
    "text": "#1c2430",
    "muted": "#5c6b7a",
    "ok": "#1f9d55",
    "warn": "#c8880b",
    "bad": "#d64545",
    "water": "#1a73e8",
    "brine": "#d4892a",
    "dark": "#e6edf4",
    "ink": "#16324f",
    "off": "#9aa8b6",
}

# (couleur du bandeau, couleur du champ) selon l'humidité
ZONE_COLORS = {
    "red": ("#d64545", "#fdecec"),
    "yellow": ("#c8880b", "#fff6e4"),
    "green": ("#1f9d55", "#e7f7ee"),
}

# Tuyauterie (coordonnées canvas). La saumure revient de l'osmose vers les panneaux.
PIPE_WELL_PUMP = [(440, 195), (440, 125)]
PIPE_PUMP_DESAL = [(445, 105), (540, 105)]
PIPE_DESAL_TANK = [(720, 150), (830, 150)]
PIPE_COOLING = [(236, 148), (236, 156), (548, 156)]
PIPE_TOWER = [(905, 200), (905, 312)]
PIPE_HEADER = [(175, 312), (1180, 312)]
ZONE_CX = [175, 510, 845, 1180]
PIPE_BRANCHES = [[(cx, 312), (cx, 345)] for cx in ZONE_CX]

PHONE_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#f3f6fa">
<title>Station — téléphone</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Segoe UI", Helvetica, Arial, sans-serif;
         background: #f3f6fa; color: #1c2430; }
  header { padding: 22px 18px 8px; }
  h1 { margin: 0; font-size: 22px; }
  p.lead { margin: 6px 0 0; color: #5c6b7a; font-size: 14px; line-height: 1.4; }
  main { padding: 8px 14px 28px; display: grid; gap: 12px; }
  .card { background: #fff; border: 1px solid #d5dee8; border-radius: 14px; padding: 14px; }
  .row { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
  .k { color: #5c6b7a; font-size: 13px; }
  .v { font-weight: 700; font-size: 18px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  button { border: 0; border-radius: 10px; padding: 12px 14px; font-weight: 700;
           font-size: 14px; background: #1a73e8; color: #fff; width: 100%; }
  button.ghost { background: #e7eef8; color: #1c2430; }
  .zone { margin-top: 8px; }
  .bar { height: 8px; background: #e6edf4; border-radius: 99px; overflow: hidden; margin-top: 4px; }
  .bar span { display: block; height: 100%; background: #1f9d55; }
  .note { border-radius: 10px; padding: 10px 12px; margin-top: 8px; background: #f6f8fb; }
  .note.bad { background: #fdecec; }
  .note.warn { background: #fff6e4; }
  .note strong { display: block; font-size: 14px; }
  .time { color: #5c6b7a; font-size: 12px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
         background: #1f9d55; margin-right: 6px; }
</style>
</head>
<body>
<header>
  <h1>Station d'irrigation</h1>
  <p class="lead">Mesures en direct et alertes de la station. Gardez cette page ouverte.</p>
</header>
<main>
  <section class="card" id="weather">Météo…</section>
  <section class="grid" id="metrics"></section>
  <section class="card">
    <div class="k">Zones goutte-à-goutte</div>
    <div id="zones"></div>
  </section>
  <section class="card">
    <div class="row"><span class="k">Alertes</span><span class="time" id="link">connexion…</span></div>
    <div id="alerts" aria-live="polite" aria-relevant="additions text"></div>
    <div id="phone-status" class="time" role="status" style="margin-top:8px"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px">
      <button type="button" class="ghost" id="perm">Activer alertes système</button>
    </div>
  </section>
</main>
<script>
let lastId = 0;
let primed = false;

function showStatus(text) {
  document.getElementById("phone-status").textContent = text;
}

function showAlert(text) {
  showStatus("Nouvelle alerte : " + text);
}

function render(s) {
  const w = s.weather || {};
  const origin = w.from_phone ? "position du téléphone" : "site configuré";
  const sky = w.phrase || "—";
    if (typeof s.tank_pct !== "number") return;
    document.getElementById("weather").innerHTML =
    '<div class="row"><span class="k">Météo</span><span class="k">' + origin + '</span></div>' +
    '<div class="v" style="margin-top:6px">' + (w.ok ? (w.temp.toFixed(1) + " °C · " + sky) : "Météo indisponible") + '</div>' +
    '<div class="k" style="margin-top:6px">Nuages ' + (w.ok ? Math.round(w.cloud) + " %" : "—") +
    ' · vent ' + (w.ok ? Math.round(w.wind) + " km/h" : "—") +
    ' · soleil mesuré ' + (w.ok ? Math.round(w.ghi) + " W/m²" : "—") + '</div>';

  const tiles = [
    ["Réservoir", Math.round(s.tank_pct) + " %", Math.round(s.tank_l) + " L"],
    ["Solaire", Math.round(s.pv_power) + " W", s.cooling ? "refroidi par saumure" : (Math.round(s.pv_temp) + " °C")],
    ["Irrigation", s.drip.toFixed(1) + " L/min", s.pump_on ? "pompe en marche" : "pompe arrêtée"],
    ["Pression", s.pressure.toFixed(2) + " bar", "osmose " + s.desal_eff.toFixed(0) + " %"]
  ];
  document.getElementById("metrics").innerHTML = tiles.map(function (t) {
    return '<article class="card"><div class="k">' + t[0] + '</div><div class="v">' + t[1] +
           '</div><div class="k">' + t[2] + '</div></article>';
  }).join("");

  const colors = { red: "#d64545", yellow: "#c8880b", green: "#1f9d55" };
  document.getElementById("zones").innerHTML = (s.zones || []).map(function (z) {
    return '<div class="zone"><div class="row"><span>Zone ' + z.name + '</span><strong>' +
           z.humidity.toFixed(0) + ' %</strong></div><div class="bar"><span style="width:' +
           Math.max(0, Math.min(100, z.humidity)) + '%;background:' + (colors[z.status] || "#1f9d55") +
           '"></span></div><div class="k">' + (z.valve ? "ligne ouverte" : "ligne fermée") +
           (z.flow > 0 ? " · " + z.flow.toFixed(1) + " L/min" : "") + '</div></div>';
  }).join("");

  const notes = s.notifications || [];
  document.getElementById("alerts").innerHTML = notes.length ? notes.slice().reverse().slice(0, 8).map(function (n) {
    return '<div class="note ' + n.level + '"><strong>' + n.text + '</strong><span class="time">' + n.time + '</span></div>';
  }).join("") : '<div class="note"><strong>Aucune alerte.</strong><span class="time">La station est calme.</span></div>';

  document.getElementById("link").innerHTML = '<span class="dot"></span>' + (s.clock || "") +
    " · " + (s.mode || "") + (s.paused ? " · pause" : "");

  if (!primed) {
    lastId = notes.reduce(function (m, n) { return Math.max(m, n.id); }, 0);
    primed = true;
    return;
  }
  const fresh = notes.filter(function (n) { return n.id > lastId; });
  fresh.forEach(function (n) {
    showAlert(n.text);
    if (typeof Notification !== "undefined" && window.isSecureContext &&
        Notification.permission === "granted") {
      try {
        new Notification("Station d'irrigation", { body: n.text });
      } catch (e) {
        showStatus("Alerte affichée sur la page; notification système indisponible.");
      }
    }
    if (navigator.vibrate) navigator.vibrate(180);
  });
  if (notes.length) lastId = notes.reduce(function (m, n) { return Math.max(m, n.id); }, lastId);
}

async function poll() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    render(await res.json());
  } catch (e) {
    document.getElementById("link").textContent = "liaison perdue";
  }
}

document.getElementById("perm").onclick = function () {
  if (typeof Notification === "undefined" || !window.isSecureContext) {
    showStatus("Notifications système indisponibles sur ce lien HTTP du réseau local. Les alertes restent visibles sur cette page.");
    return;
  }
  Notification.requestPermission().then(function (permission) {
    showStatus(permission === "granted"
      ? "Notifications système activées."
      : "Permission refusée; les alertes restent visibles sur cette page.");
  }).catch(function () {
    showStatus("Impossible d'activer les notifications système; les alertes restent visibles sur cette page.");
  });
};

poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


def clamp(value, low, high):
    """Limite une valeur à l'intervalle [low, high]."""
    return max(low, min(high, value))


def flatten(points):
    """[(x1, y1), (x2, y2)] -> [x1, y1, x2, y2]"""
    return [coord for point in points for coord in point]


def local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def weather_phrase(code):
    code = int(code or 0)
    if code == 0:
        return "ciel dégagé"
    if code in (1, 2):
        return "peu nuageux"
    if code == 3:
        return "couvert"
    if code in (45, 48):
        return "brouillard"
    if 51 <= code <= 57:
        return "bruine"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "pluie"
    if code in (71, 73, 75, 77, 85, 86):
        return "neige"
    if code in (95, 96, 99):
        return "orage"
    return "conditions %d" % code


def fetch_weather(lat, lon, from_phone):
    query = (
        "https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
        "&current=temperature_2m,relative_humidity_2m,cloud_cover,"
        "shortwave_radiation,wind_speed_10m,weather_code&timezone=auto"
    ) % (lat, lon)
    request = urllib.request.Request(query, headers={"User-Agent": "station-irrigation-demo"})
    with urllib.request.urlopen(request, timeout=8) as response:
        current = json.loads(response.read().decode("utf-8"))["current"]
    return {
        "ok": True,
        "temp": float(current["temperature_2m"]),
        "rh": float(current.get("relative_humidity_2m") or 0.0),
        "cloud": float(current.get("cloud_cover") or 0.0),
        "ghi": float(current.get("shortwave_radiation") or 0.0),
        "wind": float(current.get("wind_speed_10m") or 0.0),
        "code": int(current.get("weather_code") or 0),
        "phrase": weather_phrase(current.get("weather_code")),
        "lat": lat,
        "lon": lon,
        "from_phone": from_phone,
        "updated": time.strftime("%H:%M"),
    }


# ----------------------------------------------------------------------------
# Lien téléphone : météo entrante, alertes sortantes
# ----------------------------------------------------------------------------
class PhoneBridge:
    """Serveur local ouvert par le téléphone, sur le même réseau Wi-Fi."""

    def __init__(self):
        self.lock = threading.Lock()
        self.location = {"lat": DEFAULT_LAT, "lon": DEFAULT_LON, "from_phone": False}
        self.weather = None
        self.weather_error = ""
        self.use_real_sun = False
        self.notifications = deque(maxlen=40)
        self.demo_faults = {}
        self.pending_commands = queue.Queue(maxsize=32)
        self._nid = 1
        self._seen_alarms = set()
        self.snapshot_data = {}
        self.last_phone_poll = 0.0
        self.httpd = None
        self.port = PHONE_PORT
        self.host_ip = local_ip()
        self.url = "http://%s:%d" % (self.host_ip, self.port)

    def start(self):
        handler = self._handler()
        last_error = None
        for port in range(PHONE_PORT, PHONE_PORT + 5):
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
                self.port = port
                self.url = "http://%s:%d" % (self.host_ip, self.port)
                break
            except OSError as exc:
                last_error = exc
                self.httpd = None
        if self.httpd is None:
            self.weather_error = "serveur téléphone indisponible (%s)" % last_error
            return
        threading.Thread(target=self.httpd.serve_forever, name="phone-http", daemon=True).start()
        threading.Thread(target=self._weather_loop, name="phone-weather", daemon=True).start()

    def stop(self):
        if self.httpd is not None:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def _handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                _ = (format, args)
                return

            def _send(self, code, body, content_type):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/phone"):
                    self._send(200, PHONE_PAGE, "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._send(200, json.dumps(bridge.state()), "application/json; charset=utf-8")
                else:
                    self._send(404, "introuvable", "text/plain; charset=utf-8")

            def do_POST(self):
                path = self.path.split("?", 1)[0]
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except (ValueError, UnicodeError):
                    self._send(400, '{"ok":false}', "application/json")
                    return
                if not isinstance(payload, dict):
                    self._send(400, '{"ok":false}', "application/json")
                    return
                if path == "/api/location":
                    try:
                        lat = float(payload["lat"])
                        lon = float(payload["lon"])
                    except (KeyError, TypeError, ValueError):
                        self._send(400, '{"ok":false}', "application/json")
                        return
                    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                        self._send(400, '{"ok":false}', "application/json")
                        return
                    bridge.set_location(lat, lon)
                    self._send(200, '{"ok":true}', "application/json")
                    return
                if path == "/api/demo/fault":
                    zone = payload.get("zone")
                    fault = payload.get("fault")
                    if not isinstance(zone, str) or zone not in ("A", "B", "C", "D") or fault not in (
                        "blocked", "no_response", "normal",
                    ):
                        self._send(400, '{"ok":false}', "application/json")
                        return
                    bridge.set_demo_fault(zone, fault)
                    self._send(200, '{"ok":true}', "application/json")
                    return
                if path == "/api/control/zone":
                    zone = payload.get("zone")
                    valve_open = payload.get("open")
                    if (
                        not isinstance(zone, str)
                        or zone not in ("A", "B", "C", "D")
                        or not isinstance(valve_open, bool)
                    ):
                        self._send(400, '{"ok":false}', "application/json")
                        return
                    if not bridge.queue_zone_command(zone, valve_open):
                        self._send(503, '{"ok":false,"error":"queue_full"}', "application/json")
                        return
                    self._send(202, '{"ok":true,"queued":true}', "application/json")
                    return
                if path == "/api/control/mode":
                    mode = payload.get("mode")
                    if mode not in ("AUTO", "MANUEL"):
                        self._send(400, '{"ok":false}', "application/json")
                        return
                    if not bridge.queue_mode_command(mode):
                        self._send(503, '{"ok":false,"error":"queue_full"}', "application/json")
                        return
                    self._send(202, '{"ok":true,"queued":true}', "application/json")
                    return
                self._send(404, "introuvable", "text/plain; charset=utf-8")

        return Handler

    def set_location(self, lat, lon):
        self.update_location(lat, lon, from_phone=True)

    def update_location(self, lat, lon, from_phone=False):
        with self.lock:
            self.location = {"lat": lat, "lon": lon, "from_phone": from_phone}
        self._pull_weather()

    def set_real_sun(self, enabled):
        with self.lock:
            self.use_real_sun = bool(enabled)

    def set_demo_fault(self, zone_name, fault):
        with self.lock:
            if fault == "normal":
                self.demo_faults.pop(zone_name, None)
            else:
                self.demo_faults[zone_name] = fault

    def queue_zone_command(self, zone_name, valve_open):
        try:
            self.pending_commands.put_nowait({
                "type": "zone",
                "zone": zone_name,
                "open": valve_open,
            })
        except queue.Full:
            return False
        return True

    def queue_mode_command(self, mode):
        try:
            self.pending_commands.put_nowait({"type": "mode", "mode": mode})
        except queue.Full:
            return False
        return True

    def apply_pending_commands(self, sim):
        while True:
            try:
                command = self.pending_commands.get_nowait()
            except queue.Empty:
                break
            if command["type"] == "mode":
                sim.auto = command["mode"] == "AUTO"
                if not sim.auto:
                    sim.pump_cmd = sim.pump_on
                continue
            sim.auto = False
            sim.pump_cmd = sim.pump_on
            zone = next(
                item for item in sim.zones if item.name == command["zone"]
            )
            zone.valve = command["open"]

    def apply_demo_faults(self, zones):
        with self.lock:
            faults = dict(self.demo_faults)
        for zone in zones:
            zone.set_demo_fault(faults.get(zone.name))

    def real_sun(self):
        with self.lock:
            return self.use_real_sun

    def phone_is_open(self):
        with self.lock:
            return (time.time() - self.last_phone_poll) < 6.0

    def weather_for_sim(self):
        with self.lock:
            return dict(self.weather) if self.weather else None

    def notify(self, text, level="info"):
        with self.lock:
            item = {
                "id": self._nid,
                "text": text,
                "level": level,
                "time": time.strftime("%H:%M:%S"),
            }
            self._nid += 1
            self.notifications.append(item)
        return item

    def sync_alarms(self, alarms):
        current = {alarm[0] for alarm in alarms}
        fresh = [(text, level) for text, level in alarms if text not in self._seen_alarms]
        self._seen_alarms = current
        for text, level in fresh:
            self.notify(text, level)

    def publish(self, sim, paused):
        data = {
            "clock": sim.clock_text,
            "paused": paused,
            "mode": "AUTO" if sim.auto else "MANUEL",
            "sun_mode": sim.sun_mode,
            "tank_pct": round(sim.tank_pct, 1),
            "tank_l": round(sim.tank_l, 0),
            "pressure": round(sim.pressure, 2),
            "well": round(sim.well_level, 1),
            "pv_power": round(sim.pv_power, 0),
            "pv_temp": round(sim.pv_temp, 1),
            "cooling": sim.cooling,
            "brine": round(sim.brine_flow, 1),
            "inflow": round(sim.inflow, 1),
            "drip": round(sim.drip_flow, 1),
            "pump_on": sim.pump_on,
            "pump_cmd": sim.pump_cmd,
            "desal_eff": round(sim.desal_eff, 1),
            "desal_state": sim.desal_state,
            "zones": [
                {
                    "name": zone.name,
                    "humidity": round(zone.humidity, 1),
                    "soil": round(zone.soil_temp, 1),
                    "valve": zone.valve,
                    "flow": round(zone.flow, 1),
                    "flow_expected": round(zone.flow_expected, 1),
                    "flow_ratio": round(zone.flow_ratio * 100.0, 0),
                    "pressure": round(zone.pressure, 2),
                    "irrigation_minutes": round(zone.irrigation_minutes, 1),
                    "moisture_gain": round(zone.moisture_gain, 1),
                    "diagnosis": zone.diagnosis,
                    "diagnosis_level": zone.diagnosis_level,
                    "demo_fault": zone.demo_fault or "normal",
                    "status": zone.status,
                    "need": round(zone.need, 0),
                }
                for zone in sim.zones
            ],
            "alarms": [{"text": text, "level": level} for text, level in sim.alarms],
        }
        with self.lock:
            self.snapshot_data = data

    def state(self):
        with self.lock:
            self.last_phone_poll = time.time()
            payload = dict(self.snapshot_data)
            payload["notifications"] = list(self.notifications)
            payload["weather"] = dict(self.weather) if self.weather else {"ok": False, "error": self.weather_error}
            payload["use_real_sun"] = self.use_real_sun
            payload["url"] = self.url
            return payload

    def _weather_loop(self):
        while True:
            self._pull_weather()
            time.sleep(60)

    def _pull_weather(self):
        with self.lock:
            loc = dict(self.location)
        try:
            weather = fetch_weather(loc["lat"], loc["lon"], loc["from_phone"])
        except (OSError, ValueError, KeyError) as exc:
            with self.lock:
                self.weather_error = str(exc)
            return
        with self.lock:
            self.weather = weather
            self.weather_error = ""


# ----------------------------------------------------------------------------
# Modèle de simulation (indépendant de l'interface)
# ----------------------------------------------------------------------------
class Zone:
    """Zone agricole avec capteur d'humidité et ligne goutte-à-goutte."""

    def __init__(self, name, humidity, soil_temp, dry_rate):
        self.name = name
        self.humidity = humidity
        self.soil_temp = soil_temp
        self.dry_rate = dry_rate
        self.valve = False
        self.flow = 0.0
        self.flow_expected = 0.0
        self.flow_ratio = 0.0
        self.pressure = 0.0
        self.irrigation_active = False
        self.irrigation_minutes = 0.0
        self.irrigation_start_humidity = humidity
        self.moisture_gain = 0.0
        self.diagnosis = ""
        self.diagnosis_level = ""
        self.demo_fault = None

    def set_demo_fault(self, fault):
        if fault != self.demo_fault:
            self.demo_fault = fault
            if fault is not None:
                self.valve = True
            self.irrigation_active = False
            self.irrigation_minutes = 0.0
            self.irrigation_start_humidity = self.humidity
            self.moisture_gain = 0.0
            self.diagnosis = ""
            self.diagnosis_level = ""

    @property
    def need(self):
        """Besoin en eau (%) par rapport à l'humidité cible."""
        return clamp((TARGET_HUM - self.humidity) / TARGET_HUM * 100.0, 0.0, 100.0)

    @property
    def status(self):
        """'red' < 30 %, 'yellow' de 30 à 60 %, 'green' > 60 %."""
        if self.humidity < 30.0:
            return "red"
        if self.humidity <= 60.0:
            return "yellow"
        return "green"


class Simulation:
    """Modèle physique simplifié. Un pas d'écran = 1 s, avancée scénario = min_per_tick."""

    def __init__(self):
        self.history = deque(maxlen=HISTORY_LEN)
        self.min_per_tick = 2.0
        self.auto = True
        self.reset()

    def reset(self):
        self.t = 0
        self.clock_min = 9 * 60.0
        self.cloud = 0.95
        self.irradiance = 0.0
        self.ambient = 24.0
        self.sun_mode = "demo"
        self.weather_live = False

        self.pv_temp = 35.0
        self.pv_power = 0.0
        self.pv_eff = 0.0
        self.cooling = False

        self.pump_cmd = False
        self.pump_on = False
        self.pump_flow = 0.0

        self.well_level = 78.0

        self.desal_base = 88.0
        self.desal_eff = 88.0

        self.tank_l = 3200.0
        self.inflow = 0.0
        self.brine_flow = 0.0
        self.outflow = 0.0
        self.drip_flow = 0.0
        self.pressure = 0.55
        self.leak = False
        self.leak_flow = 0.0

        self.zones = [
            Zone("A", 38.0, 22.0, 0.085),
            Zone("B", 52.0, 23.0, 0.070),
            Zone("C", 68.0, 21.0, 0.060),
            Zone("D", 44.0, 24.0, 0.095),
        ]
        self.alarms = []
        self.history.clear()
        self._compute_alarms()
        self._record()

    @property
    def tank_pct(self):
        return self.tank_l / TANK_CAP * 100.0

    @property
    def desal_fault(self):
        return self.desal_base < DESAL_FAULT

    @property
    def desal_state(self):
        if self.desal_fault:
            return "DÉFAUT"
        return "EN MARCHE" if self.pump_on else "ARRÊT"

    @property
    def clock_text(self):
        minutes = int(self.clock_min)
        return "%02d:%02d" % (minutes // 60, minutes % 60)

    def pump_block_reason(self):
        if not self.pump_cmd or self.pump_on:
            return ""
        reasons = []
        if self.pv_power < MIN_PUMP_POWER:
            reasons.append("soleil insuffisant")
        if self.well_level <= WELL_MIN:
            reasons.append("puits trop bas")
        if self.tank_l >= TANK_CAP:
            reasons.append("réservoir plein")
        if self.desal_fault:
            reasons.append("membrane en défaut")
        return ", ".join(reasons)

    def rinse_membrane(self):
        self.desal_base = 92.0

    def step(self, weather=None, use_real_sun=False):
        dt = self.min_per_tick
        self.t += 1
        self.clock_min = (self.clock_min + dt) % 1440.0
        hour = self.clock_min / 60.0

        if 6.0 <= hour <= 18.0:
            sun = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
        else:
            sun = 0.0

        if weather is not None and weather.get("ok"):
            self.ambient = float(weather["temp"])
            self.cloud = clamp(1.0 - 0.35 * float(weather["cloud"]) / 100.0, 0.65, 1.0)
            self.weather_live = True
        else:
            self.weather_live = False
            self.cloud = clamp(self.cloud + random.uniform(-0.03, 0.03), 0.65, 1.0)
            self.ambient = 24.0 + 9.0 * math.sin(2.0 * math.pi * (hour - 9.0) / 24.0)

        if (
            use_real_sun
            and weather is not None
            and weather.get("ok")
            and weather.get("ghi") is not None
        ):
            self.irradiance = max(0.0, float(weather["ghi"]))
            self.sun_mode = "reel"
            sun = clamp(self.irradiance / 1000.0, 0.0, 1.0)
        else:
            self.irradiance = 1000.0 * sun * self.cloud
            self.sun_mode = "demo"

        # La saumure du pas précédent refroidit les panneaux (hystérésis).
        target = self.ambient + 50.0 * sun * self.cloud
        if self.cooling:
            target -= 35.0 * clamp(self.brine_flow / COOL_FLOW, 0.0, 1.0)
        gain = clamp(0.18 * dt / 2.0, 0.0, 0.6)
        self.pv_temp += (target - self.pv_temp) * gain + random.uniform(-0.2, 0.2)

        brine_ok = self.brine_flow >= BRINE_MIN
        if self.cooling:
            if self.pv_temp < COOL_OFF or not brine_ok:
                self.cooling = False
        elif self.pv_temp > COOL_ON and brine_ok:
            self.cooling = True

        eff = max(0.05, PV_ETA * (1.0 - PV_TEMP_COEF * (self.pv_temp - 25.0)))
        self.pv_eff = eff * 100.0 if self.irradiance > 5.0 else 0.0
        self.pv_power = PV_AREA * self.irradiance * eff

        if self.auto:
            if self.tank_pct < PUMP_START_PCT:
                self.pump_cmd = True
            elif self.tank_pct >= PUMP_STOP_PCT:
                self.pump_cmd = False
        can_run = (
            self.pv_power >= MIN_PUMP_POWER
            and self.well_level > WELL_MIN
            and self.tank_l < TANK_CAP
            and not self.desal_fault
        )
        self.pump_on = bool(self.pump_cmd and can_run)

        if self.pump_on:
            load = clamp(self.pv_power / (PUMP_POWER + DESAL_POWER), 0.35, 1.0)
            self.pump_flow = PUMP_MAX_FLOW * load
            self.desal_base = max(30.0, self.desal_base - 0.003 * dt)
            self.desal_eff = clamp(self.desal_base + random.uniform(-0.4, 0.4), 0.0, 100.0)
            self.inflow = self.pump_flow * self.desal_eff / 100.0
            self.brine_flow = self.pump_flow - self.inflow
        else:
            self.pump_flow = 0.0
            self.desal_eff = self.desal_base
            self.inflow = 0.0
            self.brine_flow = 0.0

        # Le puits ne fournit que l'eau pompée. La saumure est déjà dans ce volume.
        drain = self.pump_flow * dt / WELL_VOL * 100.0
        recharge = (0.25 + 0.55 * (1.0 - self.well_level / 100.0)) * dt / 2.0
        self.well_level = clamp(self.well_level - drain + recharge, 0.0, 100.0)

        if self.auto:
            self._auto_valves()

        open_count = sum(1 for zone in self.zones if zone.valve)
        if self.tank_l > 0.5:
            frac = self.tank_l / TANK_CAP
            pressure = 0.098 * (TANK_ELEV + TANK_WATER_H * frac) - 0.03 * open_count
            if self.leak:
                pressure *= 0.55
            pressure += random.uniform(-0.01, 0.01)
            self.pressure = max(0.0, pressure)
        else:
            self.pressure = 0.0

        flow_factor = clamp(self.pressure / 1.0, 0.35, 1.0)
        available = self.tank_l > 0.5
        drip = 0.0
        for zone in self.zones:
            zone.pressure = self.pressure
            zone.flow_expected = ZONE_FLOW * flow_factor if (zone.valve and available) else 0.0
            if zone.demo_fault == "blocked":
                zone.flow = zone.flow_expected * 0.08
            else:
                zone.flow = zone.flow_expected
            zone.flow_ratio = (
                zone.flow / zone.flow_expected if zone.flow_expected > 0.0 else 0.0
            )
            drip += zone.flow
        self.drip_flow = drip
        self.leak_flow = LEAK_FLOW if (self.leak and available) else 0.0
        self.outflow = drip + self.leak_flow

        self.tank_l = clamp(self.tank_l + (self.inflow - self.outflow) * dt, 0.0, TANK_CAP)

        for zone in self.zones:
            evap = zone.dry_rate * (1.0 + max(0.0, zone.soil_temp - 20.0) / 25.0) * (0.4 + 0.6 * sun) * dt
            evap += random.uniform(-0.02, 0.02)
            irrig = IRRIG_RATE * (zone.flow / ZONE_FLOW) * dt if zone.flow > 0 else 0.0
            if zone.demo_fault == "no_response":
                irrig = 0.0
            zone.humidity = clamp(zone.humidity - evap + irrig, 0.0, 100.0)
            if zone.valve and zone.flow_expected > 0.0:
                if not zone.irrigation_active:
                    zone.irrigation_active = True
                    zone.irrigation_minutes = 0.0
                    zone.irrigation_start_humidity = zone.humidity
                zone.irrigation_minutes += dt
                zone.moisture_gain = zone.humidity - zone.irrigation_start_humidity
                if zone.pressure < PRESSURE_LOW:
                    zone.diagnosis = "Pression insuffisante : vérifier la conduite ou une fuite."
                    zone.diagnosis_level = "warn"
                elif zone.flow_ratio < ZONE_FLOW_MIN_RATIO:
                    zone.diagnosis = "Débit faible : goutteur bouché ou vanne défectueuse possible."
                    zone.diagnosis_level = "bad"
                elif (
                    zone.irrigation_minutes >= IRRIGATION_CHECK_MIN
                    and zone.moisture_gain < MOISTURE_GAIN_MIN
                ):
                    zone.diagnosis = "Humidité sans hausse : zone mal irriguée ou sonde à vérifier."
                    zone.diagnosis_level = "bad"
                else:
                    zone.diagnosis = ""
                    zone.diagnosis_level = ""
            else:
                zone.irrigation_active = False
                if zone.demo_fault is None:
                    zone.diagnosis = ""
                    zone.diagnosis_level = ""
            soil_target = self.ambient * 0.85 + 3.0 - (4.0 if zone.flow > 0 else 0.0)
            zone.soil_temp += (soil_target - zone.soil_temp) * clamp(0.06 * dt / 2.0, 0.0, 1.0)

        self._compute_alarms()
        self._record()

    def _auto_valves(self):
        for zone in self.zones:
            if zone.valve and zone.humidity >= HUM_CLOSE:
                zone.valve = False
        open_count = sum(1 for zone in self.zones if zone.valve)
        for zone in sorted(self.zones, key=lambda item: item.humidity):
            if open_count >= MAX_OPEN_VALVES:
                break
            if not zone.valve and zone.humidity < HUM_OPEN and self.tank_pct > 8.0:
                zone.valve = True
                open_count += 1

    def _compute_alarms(self):
        bad, warn = [], []
        if self.leak:
            bad.append("Fuite détectée sur le goutte-à-goutte")
        if self.pv_temp > COOL_ON:
            if self.cooling:
                warn.append("Panneaux > 60 °C : refroidissement par saumure")
            elif self.brine_flow < BRINE_MIN:
                bad.append("Surchauffe panneaux : saumure insuffisante")
            else:
                bad.append("Panneaux en surchauffe")
        if self.well_level <= WELL_MIN:
            bad.append("Puits vide : pompe bloquée")
        elif self.well_level < 20.0:
            warn.append("Puits : niveau bas")
        if self.tank_pct < 15.0:
            warn.append("Réservoir : niveau bas")
        if self.desal_fault:
            bad.append("Dessalement : défaut membrane")
        elif self.desal_base < 70.0:
            warn.append("Dessalement : efficacité faible")
        if 0.05 < self.pressure < PRESSURE_LOW:
            warn.append("Pression trop basse pour le goutte-à-goutte")
        for zone in self.zones:
            if zone.diagnosis:
                level = zone.diagnosis_level or "warn"
                (bad if level == "bad" else warn).append(
                    "Zone %s : %s" % (zone.name, zone.diagnosis)
                )
            if zone.humidity < 30.0:
                warn.append("Zone %s sèche (< 30 %%)" % zone.name)
        self.alarms = [(text, "bad") for text in bad] + [(text, "warn") for text in warn]

    def _record(self):
        self.history.append(
            {
                "t": self.t,
                "clock": self.clock_text,
                "tank": self.tank_pct,
                "hum": [zone.humidity for zone in self.zones],
                "pv_power": self.pv_power,
                "pv_temp": self.pv_temp,
                "pump_flow": self.pump_flow,
                "pressure": self.pressure,
                "well": self.well_level,
                "ambient": self.ambient,
                "irradiance": self.irradiance,
                "brine": self.brine_flow,
                "drip": self.drip_flow,
                "sun_mode": self.sun_mode,
                "zone_flow": [zone.flow for zone in self.zones],
                "zone_diagnosis": [zone.diagnosis for zone in self.zones],
            }
        )


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
class SCADAApp:
    CANVAS_W = 1360
    CANVAS_H = 500
    ZONE_X = [20, 355, 690, 1025]
    ZONE_Y0 = 345
    ZONE_Y1 = 490
    ZONE_W = 310

    def __init__(self, root):
        self.root = root
        self.sim = Simulation()
        self.phase = 0
        self.paused = False
        self._closing = False
        self.bridge = PhoneBridge()

        self.root.title("Station solaire — eau et irrigation")
        self.root.configure(bg=THEME["bg"])
        self.root.geometry("1380x980")
        self.root.minsize(1280, 900)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.family = self._pick_font()
        self._setup_styles()
        self._build_header()
        self._build_link_bar()
        self.notebook = ttk.Notebook(self.root, style="Main.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.notebook.enable_traversal()
        self._build_canvas()
        self._build_bottom()
        for index in range(4):
            self.root.bind(
                "<Control-Key-%d>" % (index + 1),
                lambda event, tab_index=index: self._on_tab_shortcut(tab_index, event),
            )
        self.bridge.start()

        self._draw_static()
        self._sync_controls()
        self._draw_dynamic()
        self._update_chart()
        self.bridge.publish(self.sim, self.paused)

        self.root.after(1000, self._sim_tick)
        self.root.after(100, self._anim_tick)

    @staticmethod
    def _pick_font():
        available = set(tkfont.families())
        for name in ("Segoe UI", "Helvetica Neue", "Inter", "DejaVu Sans", "Arial", "Helvetica"):
            if name in available:
                return name
        return "TkDefaultFont"

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        theme = THEME
        font = (self.family, 9)
        style.configure(
            "TButton", background="#ffffff", foreground=theme["text"],
            bordercolor=theme["line"], lightcolor="#ffffff", darkcolor="#ffffff",
            focuscolor="#ffffff", padding=(8, 5), font=font,
        )
        style.map("TButton", background=[("active", "#e7eef8")])
        for name, bg, fg in (
            ("On", theme["ok"], "#ffffff"),
            ("Off", "#e7edf3", theme["text"]),
            ("Bad", theme["bad"], "#ffffff"),
            ("Accent", theme["water"], "#ffffff"),
        ):
            style.configure(
                name + ".TButton", background=bg, foreground=fg,
                bordercolor=theme["line"], lightcolor=bg, darkcolor=bg,
                focuscolor=bg, padding=(8, 5), font=(self.family, 9, "bold"),
            )
            style.map(name + ".TButton", background=[("active", bg)], foreground=[("active", fg)])
        style.configure("Panel.TFrame", background=theme["card"])
        style.configure("Panel.TLabel", background=theme["card"], foreground=theme["text"], font=font)
        style.configure(
            "Title.TLabel", background=theme["card"], foreground=theme["muted"],
            font=(self.family, 9, "bold"),
        )
        style.configure(
            "Hint.TLabel", background=theme["card"], foreground=theme["muted"],
            font=(self.family, 8),
        )
        style.configure(
            "TRadiobutton", background=theme["card"], foreground=theme["text"], font=font,
            focuscolor=theme["card"],
        )
        style.map(
            "TRadiobutton", background=[("active", theme["card"])],
            indicatorcolor=[("selected", theme["ok"])],
        )
        style.configure("Horizontal.TScale", background=theme["card"], troughcolor="#e6edf4")
        style.configure("Url.TEntry", fieldbackground="#f6f8fb", foreground=theme["text"])
        style.configure(
            "Main.TNotebook", background=theme["bg"], borderwidth=0,
            tabmargins=(2, 4, 2, 0),
        )
        style.configure(
            "Main.TNotebook.Tab", background="#e7edf3", foreground=theme["muted"],
            padding=(18, 10), font=(self.family, 10, "bold"),
        )
        style.map(
            "Main.TNotebook.Tab",
            background=[("selected", theme["card"]), ("active", "#ffffff")],
            foreground=[("selected", theme["water"]), ("active", theme["text"])],
        )

    def _build_header(self):
        theme = THEME
        header = tk.Frame(self.root, bg=theme["card"], height=62, highlightbackground=theme["line"], highlightthickness=1)
        header.pack(fill="x", padx=8, pady=(8, 4))
        header.pack_propagate(False)
        left = tk.Frame(header, bg=theme["card"])
        left.pack(side="left", padx=14, pady=6)
        tk.Label(
            left, text="Station solaire  ·  eau  ·  agriculture",
            bg=theme["card"], fg=theme["text"], font=(self.family, 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left, text="Pompage photovoltaïque  →  osmose inverse  →  réservoir 5 m  →  goutte-à-goutte",
            bg=theme["card"], fg=theme["muted"], font=(self.family, 9),
        ).pack(anchor="w")
        self.clock_var = tk.StringVar(value="")
        tk.Label(
            header, textvariable=self.clock_var, bg=theme["card"], fg=theme["text"],
            font=(self.family, 10),
        ).pack(side="right", padx=14)

    def _build_link_bar(self):
        theme = THEME
        bar = tk.Frame(self.root, bg=theme["card"], highlightbackground=theme["line"], highlightthickness=1)
        bar.pack(fill="x", padx=8, pady=(0, 4))
        top = tk.Frame(bar, bg=theme["card"])
        top.pack(fill="x", padx=12, pady=(8, 2))
        self.phone_dot = tk.Label(top, text="●", bg=theme["card"], fg=theme["warn"], font=(self.family, 11, "bold"))
        self.phone_dot.pack(side="left")
        self.phone_var = tk.StringVar(value="Téléphone : en attente")
        tk.Label(top, textvariable=self.phone_var, bg=theme["card"], fg=theme["text"], font=(self.family, 9, "bold")).pack(side="left", padx=(6, 16))
        self.meteo_var = tk.StringVar(value="Météo : connexion…")
        tk.Label(top, textvariable=self.meteo_var, bg=theme["card"], fg=theme["muted"], font=(self.family, 9)).pack(side="left")

        location = tk.Frame(bar, bg=theme["card"])
        location.pack(fill="x", padx=12, pady=(2, 4))
        tk.Label(
            location, text="Coordonnées météo du site :", bg=theme["card"],
            fg=theme["muted"], font=(self.family, 9),
        ).pack(side="left", padx=(0, 6))
        self.lat_var = tk.StringVar(value=str(DEFAULT_LAT))
        ttk.Entry(location, textvariable=self.lat_var, width=11, style="Url.TEntry").pack(side="left")
        tk.Label(location, text="Latitude", bg=theme["card"], fg=theme["muted"],
                 font=(self.family, 8)).pack(side="left", padx=(4, 10))
        self.lon_var = tk.StringVar(value=str(DEFAULT_LON))
        ttk.Entry(location, textvariable=self.lon_var, width=11, style="Url.TEntry").pack(side="left")
        tk.Label(location, text="Longitude", bg=theme["card"], fg=theme["muted"],
                 font=(self.family, 8)).pack(side="left", padx=(4, 10))
        ttk.Button(location, text="Appliquer", command=self._apply_weather_location).pack(side="left")

        bottom = tk.Frame(bar, bg=theme["card"])
        bottom.pack(fill="x", padx=12, pady=(2, 8))
        self.url_var = tk.StringVar(value=self.bridge.url)
        entry = ttk.Entry(bottom, textvariable=self.url_var, state="readonly", style="Url.TEntry", font=(self.family, 10))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(bottom, text="Ouvrir la page", command=self._open_phone, style="Accent.TButton").pack(side="left", padx=2)
        self.btn_sun = ttk.Button(bottom, text="Soleil : journée démo", command=self._toggle_sun)
        self.btn_sun.pack(side="left", padx=2)
        ttk.Button(bottom, text="Tester l'alerte", command=self._test_notify).pack(side="left", padx=2)

    def _build_canvas(self):
        self.overview_tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        self.notebook.add(self.overview_tab, text="1 · Vue générale")
        holder = tk.Frame(self.overview_tab, bg=THEME["bg"])
        holder.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas = tk.Canvas(
            holder, width=self.CANVAS_W, height=self.CANVAS_H,
            bg=THEME["bg"], highlightthickness=0,
        )
        self.canvas.pack(anchor="center")
        self.canvas.bind("<Button-1>", self._on_canvas_click)

    def _build_bottom(self):
        theme = THEME
        self.agriculture_tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        self.trends_tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        self.commands_tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        self.notebook.add(self.agriculture_tab, text="2 · Agriculture")
        self.notebook.add(self.trends_tab, text="3 · Tendances")
        self.notebook.add(self.commands_tab, text="4 · Commandes")
        self._build_agriculture()

        chart_frame = tk.Frame(
            self.trends_tab, bg=theme["card"],
            highlightbackground=theme["line"], highlightthickness=1,
        )
        chart_frame.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(
            chart_frame, text="Évolution des mesures",
            bg=theme["card"], fg=theme["text"],
            font=(self.family, 13, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 0))

        self.fig = Figure(figsize=(11.0, 5.4), dpi=100, facecolor=theme["card"])
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.07, right=0.985, top=0.91, bottom=0.13)
        self.ax.set_facecolor("#f7fafc")
        for spine in self.ax.spines.values():
            spine.set_color(theme["line"])
        self.ax.tick_params(colors=theme["muted"], labelsize=8)
        self.ax.grid(True, color=theme["line"], linewidth=0.5, alpha=0.8)
        self.ax.set_ylim(0, 100)
        self.ax.set_xlim(0, CHART_POINTS)
        self.ax.set_ylabel("%", color=theme["muted"], fontsize=9)
        self.ax.set_xlabel("Temps réel (s)", color=theme["muted"], fontsize=8, labelpad=1)
        self.ax.axhline(30, color=theme["bad"], linestyle="--", linewidth=0.8, alpha=0.7)
        self.ax.axhline(60, color=theme["ok"], linestyle="--", linewidth=0.8, alpha=0.7)

        (self.line_tank,) = self.ax.plot([], [], color=theme["water"], linewidth=2.4, label="Réservoir")
        self.lines_h = []
        for name, color in zip("ABCD", ("#d64545", "#c8880b", "#1f9d55", "#7a4ec8")):
            (line,) = self.ax.plot([], [], color=color, linewidth=1.5, label="Humidité " + name)
            self.lines_h.append(line)
        legend = self.ax.legend(
            loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=5,
            frameon=False, fontsize=9,
        )
        for text in legend.get_texts():
            text.set_color(theme["text"])

        self.mpl_canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.mpl_canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        ctrl = ttk.Frame(self.commands_tab, style="Panel.TFrame")
        ctrl.pack(fill="both", expand=True, padx=12, pady=12)
        inner = ttk.Frame(ctrl, style="Panel.TFrame")
        inner.pack(fill="both", expand=True, padx=20, pady=16)
        for col in range(4):
            inner.columnconfigure(col, weight=1, uniform="c")

        ttk.Label(inner, text="COMMANDES", style="Title.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(
            inner, text="AUTO règle la pompe et les lignes. MANUEL vous laisse la main.",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))

        ttk.Label(inner, text="Mode", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.mode_var = tk.StringVar(value="AUTO")
        ttk.Radiobutton(
            inner, text="AUTO", value="AUTO", variable=self.mode_var, command=self._set_mode,
        ).grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(
            inner, text="MANUEL", value="MANUEL", variable=self.mode_var, command=self._set_mode,
        ).grid(row=2, column=2, columnspan=2, sticky="w")

        self.btn_pump = ttk.Button(inner, text="Pompe : ARRÊT", command=self._toggle_pump)
        self.btn_pump.grid(row=3, column=0, columnspan=4, sticky="ew", pady=3)

        self.btn_valves = []
        for index in range(4):
            btn = ttk.Button(
                inner, text="Ligne %s" % "ABCD"[index],
                command=lambda idx=index: self._toggle_valve(idx),
            )
            btn.grid(row=4, column=index, sticky="ew", padx=2, pady=3)
            self.btn_valves.append(btn)

        self.btn_leak = ttk.Button(inner, text="Injecter une fuite", command=self._toggle_leak)
        self.btn_leak.grid(row=5, column=0, columnspan=2, sticky="ew", padx=(0, 2), pady=3)
        ttk.Button(inner, text="Rincer la membrane", command=self._rinse).grid(
            row=5, column=2, columnspan=2, sticky="ew", padx=(2, 0), pady=3,
        )

        self.speed_label = ttk.Label(inner, text="", style="Panel.TLabel")
        self.speed_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.speed_scale = ttk.Scale(inner, from_=1, to=6, orient="horizontal", command=self._on_speed)
        self.speed_scale.set(2)
        self.speed_scale.grid(row=6, column=2, columnspan=2, sticky="ew", pady=(8, 0))

        self.btn_pause = ttk.Button(inner, text="Pause", command=self._toggle_pause)
        self.btn_pause.grid(row=7, column=0, columnspan=2, sticky="ew", padx=(0, 2), pady=(8, 3))
        ttk.Button(inner, text="Exporter CSV", command=self._export_csv).grid(
            row=7, column=2, columnspan=2, sticky="ew", padx=(2, 0), pady=(8, 3),
        )

        self.wait_var = tk.StringVar(value="")
        ttk.Label(
            inner, textvariable=self.wait_var, style="Hint.TLabel",
            wraplength=900, justify="left",
        ).grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(10, 0),
        )
        self.status_var = tk.StringVar(value="Cliquez un champ, ou une ligne, pour ouvrir le goutte-à-goutte.")
        ttk.Label(inner, textvariable=self.status_var, style="Panel.TLabel", wraplength=900, justify="left").grid(
            row=9, column=0, columnspan=4, sticky="w", pady=(6, 0),
        )

    def _build_agriculture(self):
        theme = THEME
        header = tk.Frame(self.agriculture_tab, bg=theme["card"])
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(
            header, text="Suivi des secteurs d'irrigation",
            bg=theme["card"], fg=theme["text"], font=(self.family, 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Comparez l'humidité, le débit, la pression et la réponse du sol après irrigation.",
            bg=theme["card"], fg=theme["muted"], font=(self.family, 9),
        ).pack(anchor="w", pady=(3, 0))

        grid = tk.Frame(self.agriculture_tab, bg=theme["bg"])
        grid.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        grid.columnconfigure(0, weight=1, uniform="zones")
        grid.columnconfigure(1, weight=1, uniform="zones")
        grid.rowconfigure(0, weight=1, uniform="zones")
        grid.rowconfigure(1, weight=1, uniform="zones")
        self.zone_views = []

        for index, zone in enumerate(self.sim.zones):
            card = tk.Frame(
                grid, bg=theme["card"], padx=16, pady=12,
                highlightbackground=theme["line"], highlightthickness=1,
            )
            card.grid(
                row=index // 2, column=index % 2, sticky="nsew",
                padx=4, pady=4,
            )
            title = tk.Label(
                card, text="Secteur %s" % zone.name,
                bg=theme["card"], fg=theme["text"],
                font=(self.family, 12, "bold"),
            )
            title.grid(row=0, column=0, sticky="w")
            status_var = tk.StringVar()
            status = tk.Label(
                card, textvariable=status_var,
                bg=theme["card"], font=(self.family, 9, "bold"),
            )
            status.grid(row=0, column=1, sticky="e")
            card.columnconfigure(0, weight=1)
            card.columnconfigure(1, weight=1)

            moisture_var = tk.StringVar()
            flow_var = tk.StringVar()
            pressure_var = tk.StringVar()
            response_var = tk.StringVar()
            diagnosis_var = tk.StringVar()
            for row, label, variable in (
                (1, "Humidité du sol", moisture_var),
                (2, "Débit mesuré / attendu", flow_var),
                (3, "Pression de ligne", pressure_var),
                (4, "Réponse du sol", response_var),
            ):
                tk.Label(
                    card, text=label, bg=theme["card"], fg=theme["muted"],
                    font=(self.family, 9),
                ).grid(row=row, column=0, sticky="w", pady=3)
                tk.Label(
                    card, textvariable=variable, bg=theme["card"],
                    fg=theme["text"], font=(self.family, 9, "bold"),
                ).grid(row=row, column=1, sticky="e", pady=3)
            diagnosis = tk.Label(
                card, textvariable=diagnosis_var, bg=theme["card"],
                fg=theme["muted"], font=(self.family, 9),
                wraplength=480, justify="left",
            )
            diagnosis.grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 6))

            actions = tk.Frame(card, bg=theme["card"])
            actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            ttk.Button(
                actions, text="Goutteur bouché",
                command=lambda name=zone.name: self._set_demo_fault(name, "blocked"),
            ).pack(side="left", padx=(0, 5))
            ttk.Button(
                actions, text="Pas de réponse",
                command=lambda name=zone.name: self._set_demo_fault(name, "no_response"),
            ).pack(side="left", padx=5)
            ttk.Button(
                actions, text="Réinitialiser",
                command=lambda name=zone.name: self._set_demo_fault(name, "normal"),
            ).pack(side="left", padx=5)
            self.zone_views.append({
                "status": status,
                "status_var": status_var,
                "moisture": moisture_var,
                "flow": flow_var,
                "pressure": pressure_var,
                "response": response_var,
                "diagnosis": diagnosis_var,
            })

        tk.Label(
            self.agriculture_tab,
            text="Mode démonstration : les défauts sont simulés et ne commandent aucun matériel réel.",
            bg=theme["bg"], fg=theme["muted"], font=(self.family, 8),
        ).pack(anchor="w", padx=18, pady=(0, 10))
        self._refresh_zone_overview()

    def _refresh_zone_overview(self):
        if not hasattr(self, "zone_views"):
            return
        for zone, view in zip(self.sim.zones, self.zone_views):
            if zone.diagnosis:
                status_text = "ANOMALIE"
                color = THEME["bad"] if zone.diagnosis_level == "bad" else THEME["warn"]
                diagnosis = zone.diagnosis
            else:
                status_text = "LIGNE OUVERTE" if zone.valve else "EN ATTENTE"
                color = THEME["ok"] if zone.valve else THEME["muted"]
                diagnosis = "Aucune anomalie détectée."
            view["status_var"].set(status_text)
            view["status"].configure(fg=color)
            view["moisture"].set("%.1f %%" % zone.humidity)
            view["flow"].set("%.1f / %.1f L/min" % (zone.flow, zone.flow_expected))
            view["pressure"].set("%.2f bar" % zone.pressure)
            view["response"].set(
                "%.1f %% après %.1f min" % (zone.moisture_gain, zone.irrigation_minutes)
            )
            view["diagnosis"].set(diagnosis)
        anomaly_count = sum(1 for zone in self.sim.zones if zone.diagnosis)
        title = "2 · Agriculture · %d alerte%s" % (
            anomaly_count, "" if anomaly_count == 1 else "s",
        )
        self.notebook.tab(self.agriculture_tab, text=title)

    def _select_tab(self, index):
        if index < len(self.notebook.tabs()):
            self.notebook.select(index)
        return "break"

    def _on_tab_shortcut(self, index, event):
        _ = event
        return self._select_tab(index)

    def _set_demo_fault(self, zone_name, fault):
        self.bridge.set_demo_fault(zone_name, fault)
        self.bridge.apply_demo_faults(self.sim.zones)
        if fault == "normal":
            self.status_var.set("Test réinitialisé pour la zone %s." % zone_name)
        else:
            label = "goutteur bouché" if fault == "blocked" else "absence de hausse d'humidité"
            self.status_var.set(
                "Test « %s » lancé pour la zone %s. Observez le débit et les alertes."
                % (label, zone_name)
            )
        self._sync_controls()
        self._refresh_zone_overview()

    def _ensure_manual(self):
        if self.sim.auto:
            self.sim.auto = False
            self.sim.pump_cmd = self.sim.pump_on
            self.status_var.set("Passage en mode MANUEL.")

    def _set_mode(self):
        self.sim.auto = self.mode_var.get() == "AUTO"
        if not self.sim.auto:
            self.sim.pump_cmd = self.sim.pump_on
        self.status_var.set("Mode %s activé." % ("AUTO" if self.sim.auto else "MANUEL"))
        self._sync_controls()

    def _toggle_pump(self):
        self._ensure_manual()
        self.sim.pump_cmd = not self.sim.pump_cmd
        if self.sim.pump_cmd:
            self.status_var.set("Pompe demandée. Elle démarre si le soleil, le puits et la membrane le permettent.")
        else:
            self.status_var.set("Pompe arrêtée.")
        self._sync_controls()

    def _toggle_valve(self, index):
        self._ensure_manual()
        zone = self.sim.zones[index]
        zone.valve = not zone.valve
        self.status_var.set(
            "Ligne %s %s." % (zone.name, "ouverte" if zone.valve else "fermée")
        )
        self._sync_controls()

    def _toggle_leak(self):
        self.sim.leak = not self.sim.leak
        self.status_var.set(
            "Fuite injectée sur le réseau goutte-à-goutte." if self.sim.leak else "Fuite réparée."
        )
        self._sync_controls()

    def _rinse(self):
        self.sim.rinse_membrane()
        self.status_var.set("Membrane rincée : efficacité remise à 92 %.")

    def _toggle_pause(self):
        self.paused = not self.paused
        self._sync_controls()

    def _on_speed(self, value):
        self.sim.min_per_tick = round(float(value))
        self.speed_label.configure(text="Scénario : %d min / s" % self.sim.min_per_tick)

    def _on_canvas_click(self, event):
        for index, x0 in enumerate(self.ZONE_X):
            if x0 <= event.x <= x0 + self.ZONE_W and self.ZONE_Y0 <= event.y <= self.ZONE_Y1:
                self._toggle_valve(index)
                return

    def _open_phone(self):
        webbrowser.open(self.bridge.url)

    def _apply_weather_location(self):
        try:
            lat = float(self.lat_var.get().strip())
            lon = float(self.lon_var.get().strip())
        except ValueError:
            messagebox.showerror("Coordonnées météo", "Saisissez une latitude et une longitude numériques.")
            return
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            messagebox.showerror(
                "Coordonnées météo",
                "La latitude doit être entre -90 et 90 et la longitude entre -180 et 180.",
            )
            return
        threading.Thread(
            target=self.bridge.update_location,
            args=(lat, lon),
            kwargs={"from_phone": False},
            name="site-weather-update",
            daemon=True,
        ).start()
        self.status_var.set("Coordonnées enregistrées. Mise à jour météo en cours.")

    def _toggle_sun(self):
        self.bridge.set_real_sun(not self.bridge.real_sun())
        if self.bridge.real_sun():
            self.status_var.set("Les panneaux suivent l'ensoleillement mesuré par la météo.")
        else:
            self.status_var.set("Journée de démonstration : le soleil suit l'horloge scénario, atténué par les nuages réels.")
        self._sync_controls()

    def _test_notify(self):
        self.bridge.notify("Test : le téléphone reçoit les alertes de la station.", "info")
        self.status_var.set("Alerte de test envoyée sur la page téléphone.")

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("Fichier CSV", "*.csv")],
            initialfile="historique_station.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow([
                    "temps_s", "heure_sim", "reservoir_pct", "hum_A_pct", "hum_B_pct",
                    "hum_C_pct", "hum_D_pct", "puits_pct", "puissance_PV_W",
                    "temp_panneau_C", "debit_pompe_Lmin", "pression_bar",
                    "temp_air_C", "irradiance_W_m2", "saumure_Lmin", "irrigation_Lmin", "soleil",
                ])
                for row in self.sim.history:
                    writer.writerow(
                        [row["t"], row["clock"], "%.1f" % row["tank"]]
                        + ["%.1f" % value for value in row["hum"]]
                        + [
                            "%.1f" % row["well"], "%.0f" % row["pv_power"],
                            "%.1f" % row["pv_temp"], "%.1f" % row["pump_flow"],
                            "%.2f" % row["pressure"], "%.1f" % row["ambient"],
                            "%.0f" % row["irradiance"], "%.1f" % row["brine"],
                            "%.1f" % row["drip"], row["sun_mode"],
                        ]
                    )
            self.status_var.set("Historique exporté : %s" % path)
        except OSError as exc:
            messagebox.showerror("Export CSV", "Impossible d'écrire le fichier :\n%s" % exc)

    def _on_close(self):
        self._closing = True
        self.bridge.stop()
        self.root.destroy()

    def _sync_controls(self):
        sim = self.sim
        self.mode_var.set("AUTO" if sim.auto else "MANUEL")
        if sim.pump_cmd and sim.pump_on:
            pump_text, pump_style = "Pompe : EN MARCHE", "On.TButton"
        elif sim.pump_cmd:
            pump_text, pump_style = "Pompe : DEMANDÉE", "Accent.TButton"
        else:
            pump_text, pump_style = "Pompe : ARRÊT", "Off.TButton"
        self.btn_pump.configure(text=pump_text, style=pump_style)
        for btn, zone in zip(self.btn_valves, sim.zones):
            btn.configure(
                text="%s · %s" % (zone.name, "ouverte" if zone.valve else "fermée"),
                style="On.TButton" if zone.valve else "Off.TButton",
            )
        if sim.leak:
            self.btn_leak.configure(text="Réparer la fuite", style="Bad.TButton")
        else:
            self.btn_leak.configure(text="Injecter une fuite", style="TButton")
        self.btn_pause.configure(
            text="Reprendre" if self.paused else "Pause",
            style="Accent.TButton" if self.paused else "TButton",
        )
        self.speed_label.configure(text="Scénario : %d min / s" % sim.min_per_tick)
        pause = "   ·   pause" if self.paused else ""
        self.clock_var.set("Heure scénario  %s   ·   %s%s" % (
            sim.clock_text, "AUTO" if sim.auto else "MANUEL", pause,
        ))
        reason = sim.pump_block_reason()
        if reason:
            self.wait_var.set("Pompe en attente : %s." % reason)
        elif sim.cooling:
            self.wait_var.set("Les panneaux sont refroidis par la saumure de l'osmose (%.0f L/min)." % sim.brine_flow)
        else:
            self.wait_var.set("La saumure de l'osmose refroidit les panneaux au-dessus de 60 °C.")

        if self.bridge.real_sun():
            self.btn_sun.configure(text="Soleil : météo réelle", style="Accent.TButton")
        else:
            self.btn_sun.configure(text="Soleil : journée démo", style="TButton")
        self.url_var.set(self.bridge.url)

        weather = self.bridge.weather_for_sim()
        if self.bridge.phone_is_open():
            self.phone_dot.configure(fg=THEME["ok"])
            gps = " · GPS reçu" if weather and weather.get("from_phone") else ""
            self.phone_var.set("Téléphone relié" + gps)
        else:
            self.phone_dot.configure(fg=THEME["warn"])
            self.phone_var.set("En attente du téléphone")

        if weather:
            where = "téléphone" if weather.get("from_phone") else "site configuré"
            sun = "soleil réel" if sim.sun_mode == "reel" else "journée démo"
            self.meteo_var.set(
                "%.0f °C · %s · nuages %.0f %% · mesuré %.0f W/m² · %s · %s (%.3f, %.3f)"
                % (
                    weather["temp"], weather["phrase"], weather["cloud"],
                    weather["ghi"], sun, where, weather["lat"], weather["lon"],
                )
            )
        elif self.bridge.weather_error:
            self.meteo_var.set("Météo indisponible (%s). Scénario local utilisé." % self.bridge.weather_error)
        else:
            self.meteo_var.set("Météo : connexion…")

    def _sim_tick(self):
        if self._closing:
            return
        self.bridge.apply_pending_commands(self.sim)
        self.bridge.apply_demo_faults(self.sim.zones)
        if not self.paused:
            self.sim.step(self.bridge.weather_for_sim(), self.bridge.real_sun())
            self._update_chart()
        self.bridge.sync_alarms(self.sim.alarms)
        self.bridge.publish(self.sim, self.paused)
        self._sync_controls()
        self._refresh_zone_overview()
        self.root.after(1000, self._sim_tick)

    def _anim_tick(self):
        if self._closing:
            return
        self.phase = (self.phase + 1) % 100000
        self._draw_dynamic()
        self.root.after(100, self._anim_tick)

    def _update_chart(self):
        hist = list(self.sim.history)[-CHART_POINTS:]
        if not hist:
            return
        times = [item["t"] for item in hist]
        self.line_tank.set_data(times, [item["tank"] for item in hist])
        for index, line in enumerate(self.lines_h):
            line.set_data(times, [item["hum"][index] for item in hist])
        t_max = times[-1]
        left = t_max - CHART_POINTS if t_max > CHART_POINTS else 0
        right = t_max if t_max > CHART_POINTS else CHART_POINTS
        self.ax.set_xlim(left, right)
        self.mpl_canvas.draw_idle()

    def _rrect(self, x0, y0, x1, y1, r=8, tags="static", **kw):
        pts = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
        ]
        return self.canvas.create_polygon(pts, smooth=True, tags=tags, **kw)

    def _text(
        self, x, y, text, size=9, bold=False, color=None,
        anchor: Literal["nw", "n", "ne", "w", "center", "e", "sw", "s", "se"] = "w",
        tags="dyn",
    ):
        font = (self.family, size, "bold") if bold else (self.family, size)
        return self.canvas.create_text(
            x, y, text=text, fill=color or THEME["text"], font=font, anchor=anchor, tags=tags,
        )

    def _pipe(self, points, color, flowing):
        flat = flatten(points)
        if flowing:
            offset = (-self.phase * 3) % 18
            self.canvas.create_line(
                *flat, fill=color, width=5, dash=(10, 8), dashoffset=offset,
                joinstyle="round", tags="dyn",
            )
        else:
            self.canvas.create_line(*flat, fill=color, width=5, joinstyle="round", tags="dyn")

    def _wire(self, points, active):
        flat = flatten(points)
        if active:
            self.canvas.create_line(
                *flat, fill=THEME["warn"], width=2, dash=(5, 4),
                dashoffset=(-self.phase * 2) % 9, tags="dyn",
            )
        else:
            self.canvas.create_line(*flat, fill=THEME["off"], width=2, dash=(5, 4), tags="dyn")

    def _draw_static(self):
        canvas = self.canvas
        theme = THEME

        self._rrect(8, 18, 1062, 298, 10, fill=theme["card"], outline=theme["line"])
        self._rrect(1070, 18, 1352, 298, 10, fill=theme["card"], outline=theme["line"])
        self._rrect(8, 302, 1352, 496, 10, fill=theme["card"], outline=theme["line"])

        self._text(24, 46, "PANNEAUX SOLAIRES", 9, True, theme["muted"], "w", "static")
        self._text(415, 46, "POMPE P1", 9, True, theme["muted"], "center", "static")
        self._text(630, 46, "OSMOSE INVERSE", 9, True, theme["muted"], "center", "static")
        self._text(905, 46, "RÉSERVOIR 5000 L", 9, True, theme["muted"], "center", "static")
        self._text(250, 146, "saumure", 8, True, theme["brine"], "w", "static")
        self._text(20, 312, "GOUTTE À GOUTTE", 8, True, theme["muted"], "w", "static")

        pipes = [PIPE_WELL_PUMP, PIPE_PUMP_DESAL, PIPE_DESAL_TANK, PIPE_COOLING, PIPE_TOWER, PIPE_HEADER] + PIPE_BRANCHES
        for pts in pipes:
            canvas.create_line(
                *flatten(pts), fill="#d0d7e0", width=11, capstyle="round",
                joinstyle="round", tags="static",
            )

        for row in range(3):
            for col in range(4):
                off = (2 - row) * 10
                x = 40 + col * 47 + off
                y = 62 + row * 27
                canvas.create_polygon(
                    x, y, x + 44, y, x + 34, y + 24, x - 10, y + 24,
                    fill="#1f4fa8", outline="#7fb2ff", tags="static",
                )
                canvas.create_line(x + 22, y, x + 12, y + 24, fill="#2f66c9", tags="static")

        canvas.create_rectangle(320, 185, 510, 285, fill="#c4a484", outline="#a88868", tags="static")
        canvas.create_rectangle(345, 195, 485, 275, fill="#e7f3fb", outline="#8eacc8", width=2, tags="static")

        self._rrect(540, 62, 720, 170, 8, fill=theme["card2"], outline="#8ea0b5", width=2)

        canvas.create_line(850, 200, 850, 294, fill="#8ea0b5", width=4, tags="static")
        canvas.create_line(960, 200, 960, 294, fill="#8ea0b5", width=4, tags="static")
        for (xa, ya, xb, yb) in (
            (850, 200, 960, 247), (960, 200, 850, 247),
            (850, 247, 960, 294), (960, 247, 850, 294),
        ):
            canvas.create_line(xa, ya, xb, yb, fill="#b7c4d4", width=2, tags="static")
        canvas.create_rectangle(835, 294, 975, 298, fill="#8ea0b5", outline="", tags="static")
        canvas.create_rectangle(830, 62, 980, 200, fill="#eef6fc", outline="#8eacc8", width=2, tags="static")
        for frac in (0.25, 0.5, 0.75):
            y = 197 - 132 * frac
            canvas.create_line(980, y, 987, y, fill="#8eacc8", tags="static")
        canvas.create_line(1005, 202, 1005, 294, fill=theme["muted"], arrow="both", tags="static")
        self._text(1013, 248, "5 m", 9, True, theme["muted"], "w", "static")

        for x0 in self.ZONE_X:
            self._rrect(x0, self.ZONE_Y0, x0 + self.ZONE_W, self.ZONE_Y1, 6, fill=theme["card2"], outline=theme["line"])

        self._text(1084, 36, "ÉTAT", 9, True, theme["muted"], "w", "static")
        for y, label in (
            (70, "Heure scénario"), (87, "Mode"), (104, "Irradiance"),
            (121, "Air extérieur"), (138, "Irrigation"), (155, "Pression"),
        ):
            self._text(1084, y, label, 9, False, theme["muted"], "w", "static")
        canvas.create_line(1084, 168, 1338, 168, fill=theme["line"], tags="static")
        self._text(1084, 182, "ALARMES", 9, True, theme["muted"], "w", "static")

    def _draw_dynamic(self):
        self.canvas.delete("dyn")
        sim = self.sim
        theme = THEME
        blink = (self.phase // 4) % 2 == 0
        idle = "#c5d0dc"

        dist_flow = sim.drip_flow > 0.01 or sim.leak_flow > 0.01
        if sim.leak:
            dist_color = theme["bad"] if blink else "#e89a9a"
        else:
            dist_color = theme["water"] if dist_flow else idle

        self._pipe(PIPE_WELL_PUMP, theme["water"] if sim.pump_on else idle, sim.pump_on)
        self._pipe(PIPE_PUMP_DESAL, theme["water"] if sim.pump_on else idle, sim.pump_on)
        self._pipe(PIPE_DESAL_TANK, theme["water"] if sim.inflow > 0.1 else idle, sim.inflow > 0.1)
        brine_moves = sim.brine_flow >= 0.4
        self._pipe(PIPE_COOLING, theme["brine"] if brine_moves else idle, brine_moves)
        self._pipe(PIPE_TOWER, dist_color, dist_flow)
        self._pipe(PIPE_HEADER, dist_color, dist_flow)
        for index, zone in enumerate(sim.zones):
            if sim.leak:
                color = dist_color
            else:
                color = theme["water"] if zone.flow > 0 else idle
            self._pipe(PIPE_BRANCHES[index], color, zone.flow > 0)

        powered = sim.pv_power > 50.0
        self._wire([(245, 75), (350, 75), (350, 88)], powered)
        self._wire([(300, 75), (300, 30), (630, 30), (630, 62)], powered and sim.pump_on)

        self._draw_solar()
        self._draw_pump()
        self._draw_well()
        self._draw_desal()
        self._draw_tank()
        self._draw_network_labels()
        for index, zone in enumerate(sim.zones):
            self._draw_zone(index, zone)
        self._draw_info_panel()

    def _draw_solar(self):
        canvas = self.canvas
        sim = self.sim
        theme = THEME
        if sim.pv_temp > COOL_ON:
            frame = theme["bad"]
        elif sim.pv_temp > 50.0:
            frame = theme["warn"]
        else:
            frame = theme["ok"]
        canvas.create_polygon(60, 62, 245, 62, 215, 140, 30, 140, fill="", outline=frame, width=3, tags="dyn")
        if sim.cooling:
            for k, x in enumerate((50, 90, 130, 170, 205)):
                for j in range(2):
                    y = 150 - ((self.phase * 2 + k * 5 + j * 6) % 12)
                    canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=theme["brine"], outline="", tags="dyn")
        rows = (
            (170, "Puissance", "%.0f W" % sim.pv_power, theme["text"]),
            (188, "Température", "%.1f °C" % sim.pv_temp, theme["bad"] if sim.pv_temp > COOL_ON else theme["text"]),
            (206, "Rendement", "%.1f %%" % sim.pv_eff, theme["text"]),
            (224, "Refroidissement", "SAUMURE" if sim.cooling else "arrêt", theme["brine"] if sim.cooling else theme["muted"]),
            (242, "Saumure", "%.1f L/min" % sim.brine_flow, theme["text"]),
        )
        for y, label, value, color in rows:
            self._text(24, y, label, 9, False, theme["muted"])
            self._text(262, y, value, 9, True, color, "e")

    def _draw_pump(self):
        canvas = self.canvas
        sim = self.sim
        theme = THEME
        canvas.create_rectangle(330, 88, 372, 122, fill="#d5dee8", outline=theme["line"], width=2, tags="dyn")
        for x in (338, 346, 354, 362):
            canvas.create_line(x, 90, x, 120, fill="#8ea0b5", tags="dyn")
        canvas.create_line(372, 105, 385, 105, fill="#8ea0b5", width=4, tags="dyn")
        body = theme["ok"] if sim.pump_on else theme["off"]
        canvas.create_rectangle(440, 98, 452, 112, fill=body, outline=theme["card"], tags="dyn")
        canvas.create_oval(385, 75, 445, 135, fill=body, outline=theme["card"], width=2, tags="dyn")
        angle = math.radians(self.phase * 25) if sim.pump_on else 0.0
        for k in range(3):
            arm = angle + k * 2.0944
            canvas.create_line(
                415, 105, 415 + 21 * math.cos(arm), 105 + 21 * math.sin(arm),
                fill="#ffffff", width=3, tags="dyn",
            )
        canvas.create_oval(411, 101, 419, 109, fill=theme["ink"], outline="", tags="dyn")
        if sim.pump_on:
            state, color = "EN MARCHE", theme["ok"]
        elif sim.pump_cmd:
            state, color = "DEMANDÉE", theme["water"]
        else:
            state, color = "ARRÊT", theme["muted"]
        self._text(455, 78, state, 9, True, color)
        self._text(455, 94, "%.0f L/min" % sim.pump_flow, 9, False, theme["text"])

    def _draw_well(self):
        canvas = self.canvas
        sim = self.sim
        theme = THEME
        top = 273 - 76 * sim.well_level / 100.0
        canvas.create_rectangle(347, top, 483, 273, fill=theme["water"], outline="", tags="dyn")
        canvas.create_line(347, top, 483, top, fill="#9ec9ff", width=2, tags="dyn")
        on_water = top < 228
        color = "#ffffff" if on_water else (theme["warn"] if sim.well_level < 20 else theme["ink"])
        shadow = theme["ink"] if on_water else "#ffffff"
        label = "PUITS  %.0f %%" % sim.well_level
        self._text(416, 236, label, 11, True, shadow, "center")
        self._text(415, 235, label, 11, True, color, "center")

    def _draw_desal(self):
        canvas = self.canvas
        sim = self.sim
        theme = THEME
        running = sim.pump_on
        fault = sim.desal_fault
        tube = "#d5dee8" if not running else "#d7f3f3"
        tube_line = theme["off"] if not running else "#149898"
        if fault:
            tube = "#fdecec"
            tube_line = theme["bad"]
        for i in range(3):
            y = 80 + i * 24
            self._rrect(560, y, 700, y + 14, 6, tags="dyn", fill=tube, outline=tube_line)
            for x in (595, 630, 665):
                canvas.create_line(x, y, x, y + 14, fill=tube_line, tags="dyn")
            if running:
                for k in range(4):
                    bx = 560 + ((self.phase * 4 + k * 35 + i * 11) % 140)
                    canvas.create_oval(bx - 2, y + 5, bx + 2, y + 9, fill=theme["water"], outline="", tags="dyn")
        led = theme["bad"] if fault else (theme["ok"] if running else theme["off"])
        canvas.create_oval(706, 66, 716, 76, fill=led, outline=theme["card"], tags="dyn")
        state_color = theme["bad"] if fault else (theme["ok"] if running else theme["muted"])
        self._text(630, 184, sim.desal_state, 9, True, state_color, "center")
        self._text(630, 200, "Efficacité  %.0f %%" % sim.desal_eff, 9, False, theme["text"], "center")
        self._text(
            630, 216,
            "Perméat %.0f   ·   saumure %.0f L/min" % (sim.inflow, sim.brine_flow),
            8, False, theme["muted"], "center",
        )
        canvas.create_rectangle(550, 226, 710, 234, fill=theme["dark"], outline="", tags="dyn")
        bar_color = theme["ok"] if sim.desal_eff >= 75 else (theme["warn"] if sim.desal_eff >= DESAL_FAULT else theme["bad"])
        canvas.create_rectangle(
            550, 226, 550 + 1.6 * clamp(sim.desal_eff, 0, 100), 234,
            fill=bar_color, outline="", tags="dyn",
        )

    def _draw_tank(self):
        canvas = self.canvas
        sim = self.sim
        theme = THEME
        x0, x1, y0, y1 = 833, 977, 65, 197
        frac = clamp(sim.tank_pct / 100.0, 0.0, 1.0)
        if frac > 0.002:
            ytop = clamp(y1 - (y1 - y0) * frac, y0 + 2, y1)
            pts = [(x0, y1)]
            for x in range(x0, x1 + 1, 6):
                wave = ytop + 1.6 * math.sin(self.phase * 0.35 + x * 0.09)
                pts.append((x, clamp(wave, y0, y1)))
            pts.append((x1, y1))
            canvas.create_polygon(flatten(pts), fill=theme["water"], outline="", tags="dyn")
        else:
            ytop = y1
        on_water = ytop < 150
        pct = "%.0f %%" % sim.tank_pct
        fill = "#ffffff" if on_water else theme["ink"]
        shadow = theme["ink"] if on_water else "#ffffff"
        self._text(906, 126, pct, 22, True, shadow, "center")
        self._text(905, 125, pct, 22, True, fill, "center")
        self._text(905, 154, "%.0f L" % sim.tank_l, 9, True, fill, "center")

    def _draw_network_labels(self):
        canvas = self.canvas
        sim = self.sim
        theme = THEME
        for index, zone in enumerate(sim.zones):
            cx = ZONE_CX[index]
            fill = theme["ok"] if zone.valve else "#d5dee8"
            canvas.create_oval(cx - 8, 320, cx + 8, 336, fill=fill, outline=theme["card"], width=2, tags="dyn")
            self._text(cx, 328, "G", 8, True, theme["ink"] if zone.valve else theme["muted"], "center")
        low = sim.pressure < PRESSURE_LOW and sim.tank_l > 0.5
        color = theme["bad"] if (sim.leak or low) else theme["ok"]
        canvas.create_rectangle(500, 294, 670, 316, fill=theme["card"], outline=color, width=2, tags="dyn")
        self._text(585, 305, "Pression  %.2f bar" % sim.pressure, 9, True, color, "center")
        if sim.leak:
            canvas.create_rectangle(250, 294, 360, 316, fill=theme["bad"], outline="", tags="dyn")
            self._text(305, 305, "FUITE", 9, True, "#ffffff", "center")
            for k in range(3):
                y = 318 + ((self.phase * 3 + k * 8) % 18)
                canvas.create_oval(300, y - 2, 306, y + 3, fill=theme["bad"], outline="", tags="dyn")

    def _draw_zone(self, index, zone):
        canvas = self.canvas
        theme = THEME
        x0 = self.ZONE_X[index]
        y0 = self.ZONE_Y0
        width = self.ZONE_W
        band, field = ZONE_COLORS[zone.status]
        labels = {"red": "SEC", "yellow": "MOYEN", "green": "BON"}
        if zone.diagnosis:
            band = THEME["bad"] if zone.diagnosis_level == "bad" else THEME["warn"]
            labels[zone.status] = "ANOMALIE"
        on_band = "#1c2430" if band == THEME["warn"] or zone.status == "yellow" else "#ffffff"

        canvas.create_rectangle(x0, y0, x0 + width, y0 + 22, fill=band, outline="", tags="dyn")
        self._text(x0 + 12, y0 + 11, "ZONE %s" % zone.name, 10, True, on_band)
        self._text(x0 + width - 12, y0 + 11, labels[zone.status], 9, True, on_band, "e")

        canvas.create_rectangle(x0 + 12, 375, x0 + 132, 482, fill=field, outline="#d5dee8", width=2, tags="dyn")
        canvas.create_line(x0 + 22, 392, x0 + 122, 392, fill="#8ea0b5", width=3, tags="dyn")
        for k, dx in enumerate((36, 60, 84, 108)):
            canvas.create_line(x0 + dx, 392, x0 + dx, 404, fill="#8ea0b5", width=2, tags="dyn")
            if zone.flow > 0:
                drop_y = 406 + ((self.phase * 3 + k * 9) % 62)
                canvas.create_oval(x0 + dx - 2, drop_y, x0 + dx + 2, drop_y + 6, fill=theme["water"], outline="", tags="dyn")
            else:
                canvas.create_oval(x0 + dx - 2, 404, x0 + dx + 2, 408, fill="#8ea0b5", outline="", tags="dyn")

        tx = x0 + 148
        self._text(tx, 380, "HUMIDITÉ", 8, True, theme["muted"])
        self._text(tx, 400, "%.0f %%" % zone.humidity, 18, True, band)
        canvas.create_rectangle(tx, 416, x0 + 298, 422, fill=theme["dark"], outline="", tags="dyn")
        canvas.create_rectangle(tx, 416, tx + 1.5 * clamp(zone.humidity, 0, 100), 422, fill=band, outline="", tags="dyn")
        for mark in (30, 60):
            canvas.create_line(tx + 1.5 * mark, 414, tx + 1.5 * mark, 424, fill=theme["muted"], tags="dyn")
        self._text(tx, 440, "Sol", 9, False, theme["muted"])
        self._text(x0 + 298, 440, "%.1f °C" % zone.soil_temp, 9, True, theme["text"], "e")
        self._text(tx, 458, "Besoin", 9, False, theme["muted"])
        self._text(x0 + 298, 458, "%.0f %%" % zone.need, 9, True, theme["text"], "e")
        if zone.diagnosis:
            diagnosis_color = theme["bad"] if zone.diagnosis_level == "bad" else theme["warn"]
            detail = (
                "DÉBIT FAIBLE" if zone.flow_ratio < ZONE_FLOW_MIN_RATIO
                else "PRESSION BASSE" if zone.pressure < PRESSURE_LOW
                else "PAS DE HAUSSE HUMIDITÉ"
            )
            self._text(tx, 476, "ALERTE · " + detail, 8, True, diagnosis_color)
        else:
            self._text(tx, 476, "Ligne", 9, False, theme["muted"])
            self._text(
                x0 + 298, 476, "ouverte" if zone.valve else "fermée", 9, True,
                theme["ok"] if zone.valve else theme["muted"], "e",
            )

    def _draw_info_panel(self):
        sim = self.sim
        theme = THEME
        sun = "scénario" if sim.sun_mode == "demo" else "réelle"
        values = (
            (70, sim.clock_text, theme["text"]),
            (87, "AUTO" if sim.auto else "MANUEL", theme["ok"] if sim.auto else theme["warn"]),
            (104, "%.0f W/m²  ·  %s" % (sim.irradiance, sun), theme["text"]),
            (121, "%.1f °C" % sim.ambient, theme["text"]),
            (138, "%.1f L/min" % sim.drip_flow, theme["text"]),
            (155, "%.2f bar" % sim.pressure, theme["bad"] if sim.leak else theme["text"]),
        )
        for y, value, color in values:
            self._text(1338, y, value, 9, True, color, "e")
        if not sim.alarms:
            self._text(1084, 204, "Tout est normal", 9, True, theme["ok"])
            return
        for k, (text, level) in enumerate(sim.alarms[:5]):
            color = theme["bad"] if level == "bad" else theme["warn"]
            self._text(1084, 204 + k * 16, "• " + text, 8, level == "bad", color)
        extra = len(sim.alarms) - 5
        if extra > 0:
            self._text(1084, 204 + 5 * 16, "+ %d autre(s)" % extra, 8, False, theme["muted"])


def main():
    root = tk.Tk()
    SCADAApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
