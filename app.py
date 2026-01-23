import os
import io
import json
import csv
import time
import math
import random
import logging
import base64
import requests
import feedparser
import threading
import sqlite3
import numpy as np
import cv2  # opencv-python-headless or opencv-python
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, jsonify, request, redirect, url_for, make_response, send_from_directory, g
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ExifTags


# Import local configs
try:
    from news_config import NEWS_SOURCES
except ImportError:
    NEWS_SOURCES = {}


# -----------------------------------------------------------------
# Configuration & Keys
# -----------------------------------------------------------------
# NOTE: Paths are adjusted to work from HayOS/github/ assuming HayOS/ is parent
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
GEODATA_DIR = os.path.join(PARENT_DIR, 'geodata')


# API Keys (Copied from HayOS.py)
NEWS_API_KEY = "API_KEY"
OPENROUTER_API_KEY = "API_KEY"


app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key'
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -----------------------------------------------------------------
# Caches & Globals
# -----------------------------------------------------------------
news_cache = {}
NEWS_CACHE_LIMIT = 15 # minutes


#

# -----------------------------------------------------------------
# Database & Auth Helpers
# -----------------------------------------------------------------



@app.route('/earth')
def earth():
    # 2. List GeoJSON files
    geodata_dir = os.path.join(app.root_path, 'geodata')
    geojson_files = []
    if os.path.exists(geodata_dir):
        geojson_files = [f for f in os.listdir(geodata_dir) if f.endswith('.geojson')]
    
    return render_template("earth.html", geojson_files=geojson_files)


@app.route('/api/geojson/<filename>')
def get_geojson_data(filename):
    """Return a summary of the GeoJSON file (properties and first few coords to keep it snappy)."""
    # Security check: prevent directory traversal
    if '..' in filename or filename.startswith('/'):
        return jsonify({"error": "Invalid filename"}), 400

    filepath = os.path.join(app.root_path, 'geodata', filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Return a larger sample for map visualization
        features = data.get('features', [])
        summary_features = []
        
        for feat in features[:500]: # Increased to 500 for map display
            summary_features.append({
                "type": feat.get("type"),
                "properties": feat.get("properties"),
                "geometry": feat.get("geometry") # Include full geometry for Leaflet
            })

        return jsonify({
            "filename": filename,
            "total_features": len(features),
            "summary": summary_features
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/geo/index')

def get_geo_index():
    """Return the surveillance grid index."""
    filepath = os.path.join(app.root_path, 'geodata', 'geo', 'index.json')
    if not os.path.exists(filepath):
        return jsonify({"error": "Index not found"}), 404
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/geo/tile/<z>/<x>/<y>')

def get_geo_tile(z, x, y):
    """Return a specific surveillance grid tile."""
    # Security check: ensure z, x, y are integers to prevent path traversal
    try:
        z = int(z)
        x = int(x)
        y = int(y)
    except ValueError:
        return jsonify({"error": "Invalid tile coordinates"}), 400

    filepath = os.path.join(app.root_path, 'geodata', 'geo', str(z), str(x), f"{y}.json")
    if not os.path.exists(filepath):
        return jsonify({"error": "Tile not found"}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Live flight data configuration
ADSB_REGIONS = [
    # North America
    ("https://opendata.adsb.fi/api/v3/lat/40/lon/-100/dist/250", "NorthAmerica_Central"),
    ("https://opendata.adsb.fi/api/v3/lat/45/lon/-75/dist/250", "USA_East"),
    ("https://opendata.adsb.fi/api/v3/lat/35/lon/-120/dist/250", "USA_West"),
    ("https://opendata.adsb.fi/api/v3/lat/30/lon/-90/dist/250", "USA_South"),
    ("https://opendata.adsb.fi/api/v3/lat/50/lon/-110/dist/250", "Canada_West"),
    # Europe
    ("https://opendata.adsb.fi/api/v3/lat/50/lon/10/dist/250", "Europe_Central"),
    ("https://opendata.adsb.fi/api/v3/lat/51/lon/0/dist/250", "Europe_UK"),
    ("https://opendata.adsb.fi/api/v3/lat/40/lon/-3/dist/250", "Europe_Spain"),
    ("https://opendata.adsb.fi/api/v3/lat/45/lon/5/dist/250", "Europe_France"),
    ("https://opendata.adsb.fi/api/v3/lat/42/lon/12/dist/250", "Europe_Italy"),
    ("https://opendata.adsb.fi/api/v3/lat/52/lon/21/dist/250", "Europe_Poland"),
    # Asia
    ("https://opendata.adsb.fi/api/v3/lat/28/lon/77/dist/250", "SouthAsia_India"),
    ("https://opendata.adsb.fi/api/v3/lat/19/lon/72/dist/250", "India_Mumbai"),
    ("https://opendata.adsb.fi/api/v3/lat/35/lon/139/dist/250", "Japan_Tokyo"),
    ("https://opendata.adsb.fi/api/v3/lat/31/lon/121/dist/250", "China_Shanghai"),
    ("https://opendata.adsb.fi/api/v3/lat/22/lon/114/dist/250", "China_HongKong"),
    ("https://opendata.adsb.fi/api/v3/lat/13/lon/100/dist/250", "SEAsia_Thailand"),
    ("https://opendata.adsb.fi/api/v3/lat/1/lon/103/dist/250", "SEAsia_Singapore"),
    # Russia
    ("https://opendata.adsb.fi/api/v3/lat/55/lon/37/dist/250", "Russia_Moscow"),
    ("https://opendata.adsb.fi/api/v3/lat/55/lon/82/dist/250", "Russia_Siberia"),
    ("https://opendata.adsb.fi/api/v3/lat/43/lon/131/dist/250", "Russia_FarEast"),
    # Oceania
    ("https://opendata.adsb.fi/api/v3/lat/-33/lon/151/dist/250", "Australia_East"),
    ("https://opendata.adsb.fi/api/v3/lat/-37/lon/144/dist/250", "Australia_South"),
    # South America
    ("https://opendata.adsb.fi/api/v3/lat/-23/lon/-46/dist/250", "SouthAmerica_Brazil"),
    ("https://opendata.adsb.fi/api/v3/lat/-34/lon/-58/dist/250", "SouthAmerica_Argentina"),
    ("https://opendata.adsb.fi/api/v3/lat/4/lon/-74/dist/250", "SouthAmerica_Colombia"),
    # Africa
    ("https://opendata.adsb.fi/api/v3/lat/30/lon/31/dist/250", "Africa_Egypt"),
    ("https://opendata.adsb.fi/api/v3/lat/-26/lon/28/dist/250", "Africa_South"),
    ("https://opendata.adsb.fi/api/v3/lat/-1/lon/36/dist/250", "Africa_East"),
    ("https://opendata.adsb.fi/api/v3/lat/6/lon/3/dist/250", "Africa_West"),
    # Middle East
    ("https://opendata.adsb.fi/api/v3/lat/25/lon/55/dist/250", "MiddleEast_Dubai"),
    ("https://opendata.adsb.fi/api/v3/lat/32/lon/34/dist/250", "MiddleEast_Israel"),
    ("https://opendata.adsb.fi/api/v3/lat/24/lon/46/dist/250", "MiddleEast_Saudi"),
]

def fetch_opensky_data():
    """Fetch global state vectors from OpenSky Network (Free API)."""
    try:
        # OpenSky global states (anonymous access has rate limits but works)
        url = "https://opensky-network.org/api/states/all"
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            states = data.get('states', [])
            aircraft = []
            for s in states:
                if s[5] is None or s[6] is None: continue # No lat/lon
                aircraft.append({
                    'hex': s[0],
                    'flight': (s[1] or '').strip(),
                    'r': '', # Registration not in simple states
                    't': '', # Type not in simple states
                    'lat': s[6],
                    'lon': s[5],
                    'alt_baro': s[7],
                    'gs': s[9],
                    'track': s[10],
                    'squawk': s[14] or '----',
                    'source': 'OpenSky'
                })
            return aircraft
    except Exception as e:
        print(f"OpenSky Fetch Error: {e}")
    return []

@app.route('/api/geo/regions')
@login_required
def get_flight_regions():
    """Return the list of configured ADSB regions."""
    regs = [{"name": r[1], "id": i} for i, r in enumerate(ADSB_REGIONS)]
    # Add OpenSky as a virtual region
    regs.append({"name": "Global_OpenSky", "id": -1})
    return jsonify(regs)

from concurrent.futures import ThreadPoolExecutor

def fetch_region_data(url, region_name, headers):
    """Helper to fetch data for a single region."""
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get('ac', [])
    except Exception as e:
        print(f"Error fetching {region_name}: {e}")
    return []

@app.route('/api/geo/flights')
@login_required
def get_flight_data():
    """Fetch live flight data from adsb.fi API (comprehensive global coverage using v3)."""
    search_q = request.args.get('q', '').strip().upper()
    region_idx = request.args.get('region_idx', type=int)
    
    headers = {"User-Agent": "SkyScanFlightTracker/1.0 (HayOS Uplink)"}
    all_flights = {}  # Use dict to dedupe by hex
    
    selected_regions = []
    if region_idx is not None and 0 <= region_idx < len(ADSB_REGIONS):
        selected_regions = [ADSB_REGIONS[region_idx]]
    else:
        selected_regions = ADSB_REGIONS

    # Use ThreadPoolExecutor for high-parallelism fetching
    aircraft_data = []
    
    # Always fetch all regions and OpenSky for a unified view
    with ThreadPoolExecutor(max_workers=25) as executor:
        # 1. Fetch OpenSky
        os_future = executor.submit(fetch_opensky_data)
        
        # 2. Fetch all ADSB regions
        # If a specific region_idx is provided, we still obey it for targeted scans, 
        # but the default (no region_idx) will fetch EVERYTHING.
        target_regions = selected_regions if region_idx is not None else ADSB_REGIONS
        adsb_futures = [executor.submit(fetch_region_data, url, name, headers) for url, name in target_regions]
        
        # 3. Combine results
        aircraft_data.extend(os_future.result())
        for future in adsb_futures:
            aircraft_data.extend(future.result())

    for ac in aircraft_data:
        # Skip if no position data
        if ac.get('lat') is None or ac.get('lon') is None:
            continue
        
        hex_code = (ac.get('hex') or ac.get('icao') or '').upper()
        if not hex_code or hex_code in all_flights:
            continue  # Already have this aircraft
        
        # Field mapping with better fallbacks
        # ADSB.fi uses 'flight' for callsign, 'r' for registration, 't' for type
        # OpenSky uses 'flight' for callsign
        callsign = (ac.get('flight', '') or '').strip()
        registration = ac.get('r', '') or ac.get('reg', '')
        aircraft_type = ac.get('t', '') or ac.get('type', '')
        squawk = ac.get('squawk') or '----'
        
        # If callsign is missing, use hex
        if not callsign: callsign = hex_code
        
        # Apply search filter if provided
        if search_q:
            if search_q not in hex_code and search_q not in callsign.upper() and search_q not in (registration or '').upper():
                continue
        
        # Type classification with color coding
        # Military detection
        mil_prefixes = ['RCH', 'SPAR', 'SAM', 'AF1', 'MAGMA', 'ASCOT', 'BAF', 'GAF', 
                       'PLF', 'DUKE', 'NAVY', 'COBRA', 'VIPER', 'REACH', 'EVAC']
        mil_types = ['C17', 'C130', 'C5', 'KC135', 'KC10', 'F15', 'F16', 'F18', 
                    'F22', 'F35', 'B52', 'B1', 'B2', 'E3', 'E6', 'P8', 'V22']
        
        is_mil = any(callsign.upper().startswith(p) for p in mil_prefixes) or \
                 any(t in (aircraft_type or '').upper() for t in mil_types)
        
        # Private aircraft detection  
        priv_types = ['C172', 'C182', 'C208', 'PA28', 'SR22', 'TBM9', 'PC12', 'CL60', 'C152', 'PA32']
        is_priv = (callsign.startswith('N') and len(callsign) <= 6) or \
                  callsign.startswith('G-') or callsign.startswith('VH-') or \
                  (aircraft_type or '').upper() in priv_types
        
        # Emergency detection
        is_emergency = ac.get('emergency', 'none') != 'none' or squawk == '7700'
        
        # Default to commercial (blue) - all flights visible!
        f_type = "commercial"
        if is_emergency: f_type = "emergency"
        elif is_mil: f_type = "military"
        elif is_priv: f_type = "private"
        
        all_flights[hex_code] = {
            "icao24": hex_code.lower(),
            "callsign": callsign,
            "registration": registration or "---",
            "aircraft_type": aircraft_type or "---",
            "long": ac.get('lon') or ac.get('lon'), # Handle different param names if any
            "lat": ac.get('lat') or ac.get('lat'),
            "alt": ac.get('alt_baro') or ac.get('alt_geom') or ac.get('alt') or 0,
            "velocity": ac.get('gs') or ac.get('speed') or 0,
            "heading": ac.get('track') or ac.get('heading') or 0,
            "squawk": squawk,
            "type": f_type,
            "source": ac.get('source', 'ADSB.fi')
        }
    
    return jsonify(list(all_flights.values()))

# --- VESSEL HARBOR UPLINK ---
# Global cache for AIS data
_ais_vessels_cache = {}
_ais_cache_lock = None
_ais_websocket_task = None

def start_ais_websocket():
    """Start background WebSocket connection to AISstream.io"""
    import asyncio
    import websockets
    import json
    import threading
    from threading import Lock
    
    global _ais_cache_lock, _ais_websocket_task
    _ais_cache_lock = Lock()
    
    async def ais_stream():
        global _ais_vessels_cache
        
        api_key = "API_KEY"
        
        async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
            # Subscribe to global ship positions
            subscribe_message = {
                "APIKey": api_key,
                "BoundingBoxes": [[[-90, -180], [90, 180]]]  # Global coverage
            }
            
            await websocket.send(json.dumps(subscribe_message))
            print("AISstream.io connected - receiving real ship data...")
            
            async for message_json in websocket:
                try:
                    message = json.loads(message_json)
                    
                    # Handle Position Reports
                    if "Message" in message and "PositionReport" in message["Message"]:
                        pos = message["Message"]["PositionReport"]
                        meta = message.get("MetaData", {})
                        
                        mmsi = str(meta.get("MMSI", "000000000"))
                        ship_name = meta.get("ShipName", "UNKNOWN").strip()
                        
                        vessel_data = {
                            "mmsi": mmsi,
                            "name": ship_name if ship_name else "UNKNOWN",
                            "lat": pos.get("Latitude", 0),
                            "lon": pos.get("Longitude", 0),
                            "heading": int(pos.get("TrueHeading", 0) or pos.get("Cog", 0) or 0),
                            "speed": float(pos.get("Sog", 0) or 0),
                            "type": _ais_vessels_cache.get(mmsi, {}).get("type", "cargo"),  # Keep existing type
                            "imo": meta.get("IMO", "---"),
                            "status": pos.get("NavigationalStatus", "Underway"),
                            "country": _ais_vessels_cache.get(mmsi, {}).get("country", "--"),  # Keep existing country
                            "draft": 0,
                            "arrival": meta.get("Destination", "Unknown"),
                            "callsign": meta.get("CallSign", "---"),
                            "source": "AISstream_LIVE",
                            "atd": "---",
                            "departure": "---",
                            "category": _ais_vessels_cache.get(mmsi, {}).get("type", "cargo")
                        }
                        
                        with _ais_cache_lock:
                            _ais_vessels_cache[mmsi] = vessel_data
                    
                    # Handle Ship Static Data (has ship type and country)
                    elif "Message" in message and "ShipStaticData" in message["Message"]:
                        static = message["Message"]["ShipStaticData"]
                        meta = message.get("MetaData", {})
                        
                        mmsi = str(meta.get("MMSI", "000000000"))
                        ship_type_code = static.get("Type", 0)
                        
                        # Map AIS ship type codes to readable types
                        type_map = {
                            range(30, 40): "fishing",
                            range(40, 50): "tug",
                            range(50, 60): "pilot",
                            range(60, 70): "passenger",
                            range(70, 80): "cargo",
                            range(80, 90): "tanker",
                            range(35, 36): "military",
                            range(51, 52): "special"
                        }
                        
                        ship_type = "cargo"  # default
                        for code_range, type_name in type_map.items():
                            if ship_type_code in code_range:
                                ship_type = type_name
                                break
                        
                        # Get country from UserID (first 3 digits of MMSI = Maritime Identification Digits)
                        mid = mmsi[:3]
                        country_map = {
                            '202': 'GB', '203': 'ES', '204': 'PT', '205': 'BE', '206': 'FR',
                            '207': 'FR', '208': 'FR', '209': 'CY', '210': 'CY', '211': 'DE',
                            '212': 'CY', '213': 'GE', '214': 'MD', '215': 'MT', '216': 'AM',
                            '218': 'DE', '219': 'DK', '220': 'DK', '224': 'ES', '225': 'ES',
                            '226': 'FR', '227': 'FR', '228': 'FR', '229': 'MT', '230': 'FI',
                            '231': 'FO', '232': 'GB', '233': 'GB', '234': 'GB', '235': 'GB',
                            '236': 'GI', '237': 'GR', '238': 'HR', '239': 'GR', '240': 'GR',
                            '241': 'GR', '242': 'MA', '243': 'HU', '244': 'NL', '245': 'NL',
                            '246': 'NL', '247': 'IT', '248': 'MT', '249': 'MT', '250': 'IE',
                            '251': 'IS', '252': 'LI', '253': 'LU', '254': 'MC', '255': 'PT',
                            '256': 'MT', '257': 'NO', '258': 'NO', '259': 'NO', '261': 'PL',
                            '262': 'ME', '263': 'PT', '264': 'RO', '265': 'SE', '266': 'SE',
                            '267': 'SK', '268': 'SM', '269': 'CH', '270': 'CZ', '271': 'TR',
                            '272': 'UA', '273': 'RU', '274': 'MK', '275': 'LV', '276': 'EE',
                            '277': 'LT', '278': 'SI', '279': 'RS', '301': 'AI', '303': 'US',
                            '304': 'AG', '305': 'AG', '306': 'CW', '307': 'AW', '308': 'BS',
                            '309': 'BS', '310': 'BM', '311': 'BS', '312': 'BZ', '314': 'BB',
                            '316': 'CA', '319': 'KY', '321': 'CR', '323': 'CU', '325': 'DM',
                            '327': 'DO', '329': 'GP', '330': 'GD', '331': 'GL', '332': 'GT',
                            '334': 'HN', '336': 'HT', '338': 'US', '339': 'JM', '341': 'KN',
                            '343': 'LC', '345': 'MX', '347': 'MQ', '348': 'MS', '350': 'NI',
                            '351': 'PA', '352': 'PA', '353': 'PA', '354': 'PA', '355': 'PA',
                            '356': 'PA', '357': 'PA', '358': 'PR', '359': 'SV', '361': 'PM',
                            '362': 'TT', '364': 'TC', '366': 'US', '367': 'US', '368': 'US',
                            '369': 'US', '370': 'PA', '371': 'PA', '372': 'PA', '373': 'PA',
                            '374': 'PA', '375': 'VC', '376': 'VC', '377': 'VC', '378': 'VG',
                            '401': 'AF', '403': 'SA', '405': 'BD', '408': 'BH', '410': 'BT',
                            '412': 'CN', '413': 'CN', '414': 'CN', '416': 'TW', '417': 'LK',
                            '419': 'IN', '422': 'IR', '423': 'AZ', '425': 'IQ', '428': 'IL',
                            '431': 'JP', '432': 'JP', '434': 'TM', '436': 'KZ', '437': 'UZ',
                            '438': 'JO', '440': 'KR', '441': 'KR', '443': 'PS', '445': 'KP',
                            '447': 'KW', '450': 'LB', '451': 'KG', '453': 'MO', '455': 'MV',
                            '457': 'MN', '459': 'NP', '461': 'OM', '463': 'PK', '466': 'QA',
                            '468': 'SY', '470': 'AE', '471': 'AE', '472': 'TJ', '473': 'YE',
                            '475': 'YE', '477': 'HK', '478': 'BA', '501': 'AQ', '503': 'AU',
                            '506': 'MM', '508': 'BN', '510': 'FM', '511': 'PW', '512': 'NZ',
                            '514': 'KH', '515': 'KH', '516': 'CX', '518': 'CK', '520': 'FJ',
                            '523': 'CC', '525': 'ID', '529': 'KI', '531': 'LA', '533': 'MY',
                            '536': 'MP', '538': 'MH', '540': 'NC', '542': 'NU', '544': 'NR',
                            '546': 'PF', '548': 'PH', '553': 'PG', '555': 'PN', '557': 'SB',
                            '559': 'AS', '561': 'WS', '563': 'SG', '564': 'SG', '565': 'SG',
                            '566': 'SG', '567': 'TH', '570': 'TO', '572': 'TV', '574': 'VN',
                            '576': 'VU', '577': 'VU', '578': 'WF', '601': 'ZA', '603': 'AO',
                            '605': 'DZ', '607': 'TF', '608': 'AS', '609': 'BI', '610': 'BJ',
                            '611': 'BW', '612': 'CF', '613': 'CM', '615': 'CG', '616': 'KM',
                            '617': 'CV', '618': 'AQ', '619': 'CI', '620': 'KM', '621': 'DJ',
                            '622': 'EG', '624': 'ET', '625': 'ER', '626': 'GA', '627': 'GH',
                            '629': 'GM', '630': 'GW', '631': 'GQ', '632': 'GN', '633': 'BF',
                            '634': 'KE', '635': 'AQ', '636': 'LR', '637': 'LR', '638': 'SS',
                            '642': 'LY', '644': 'LS', '645': 'MU', '647': 'MG', '649': 'ML',
                            '650': 'MZ', '654': 'MR', '655': 'MW', '656': 'NE', '657': 'NG',
                            '659': 'NA', '660': 'RE', '661': 'RW', '662': 'SD', '663': 'SN',
                            '664': 'SC', '665': 'SH', '666': 'SO', '667': 'SL', '668': 'ST',
                            '669': 'SZ', '670': 'TD', '671': 'TG', '672': 'TN', '674': 'TZ',
                            '675': 'UG', '676': 'CD', '677': 'TZ', '678': 'ZM', '679': 'ZW'
                        }
                        country = country_map.get(mid, "--")
                        
                        # Update or create vessel data with static info
                        with _ais_cache_lock:
                            if mmsi in _ais_vessels_cache:
                                _ais_vessels_cache[mmsi]["type"] = ship_type
                                _ais_vessels_cache[mmsi]["country"] = country
                                _ais_vessels_cache[mmsi]["category"] = ship_type
                            else:
                                # Create minimal entry until we get position report
                                _ais_vessels_cache[mmsi] = {
                                    "mmsi": mmsi,
                                    "name": meta.get("ShipName", "UNKNOWN").strip(),
                                    "type": ship_type,
                                    "country": country,
                                    "lat": 0,
                                    "lon": 0,
                                    "heading": 0,
                                    "speed": 0,
                                    "imo": meta.get("IMO", "---"),
                                    "status": "Unknown",
                                    "draft": static.get("Draught", 0) / 10,  # AIS reports in decimeters
                                    "arrival": static.get("Destination", "Unknown"),
                                    "callsign": static.get("CallSign", "---"),
                                    "source": "AISstream_LIVE",
                                    "atd": "---",
                                    "departure": "---",
                                    "category": ship_type
                                }
                            
                except Exception as e:
                    print(f"AIS Parse Error: {e}")
                    continue
    
   
    def run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            try:
                loop.run_until_complete(ais_stream())
            except Exception as e:
                print(f"AIS WebSocket Error: {e}, reconnecting in 5s...")
                import time
                time.sleep(5)
    
    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()
    print("AIS WebSocket thread started")

@app.route('/api/geo/vessels')

def get_vessel_data():
    """Fetch REAL live vessel data from AISstream.io"""
    global _ais_vessels_cache, _ais_websocket_task
    
    # Start WebSocket if not already started
    if _ais_websocket_task is None:
        try:
            start_ais_websocket()
            _ais_websocket_task = True
        except Exception as e:
            print(f"Failed to start AIS WebSocket: {e}")
    
    # Return cached vessels (optimized for performance)
    with _ais_cache_lock if _ais_cache_lock else nullcontext():
        all_vessels = list(_ais_vessels_cache.values())
        
        # Filter out vessels with invalid positions
        valid_vessels = [v for v in all_vessels if v.get('lat') != 0 and v.get('lon') != 0]
        
        # Prioritize India (419), China (412, 413, 414), Russia (273)
        priority_prefixes = ('419', '412', '413', '414', '273')
        
        priority_ships = [v for v in valid_vessels if v.get('mmsi', '').startswith(priority_prefixes)]
        other_ships = [v for v in valid_vessels if not v.get('mmsi', '').startswith(priority_prefixes)]
        
        # Combine: Priority ships first, then others, limit to 1500 total for better coverage
        vessels = (priority_ships + other_ships)[:1500]
    
    return jsonify(vessels)

from contextlib import nullcontext

@app.route('/api/geo/vessel/path/<mmsi>')

def get_vessel_path(mmsi):
    """Generate a realistic historical path for a vessel."""
    import random
    # Mock more historical points for a longer path
    res = []
    # Start with a random seed based on MMSI
    random.seed(mmsi)
    lat = random.uniform(-60, 70)
    lon = random.uniform(-180, 180)
    
    for _ in range(25):
        lat += random.uniform(-1.0, 1.0)
        lon += random.uniform(-1.0, 1.0)
        res.append([lat, lon])
    
    return jsonify(res)



from ultralytics import YOLO

# Load YOLO model globally
yolo_seg_model = None

@app.route('/api/geo/segment')

def geo_segment():
    """
    Advanced YOLO-based Aerial Segmentation.
    Uses Ultralytics YOLOv8-seg to identify and mask structures from satellite tiles.
    Supports both point-based (lat/lon) and region-based (bbox) analysis.
    """
    global yolo_seg_model
    try:
        lat = float(request.args.get('lat', 0))
        lon = float(request.args.get('lon', 0))
        zoom = int(request.args.get('zoom', 18))
        bbox_str = request.args.get('bbox', None)  # Format: "minLat,minLon,maxLat,maxLon"

        # Parse bbox if provided for region filtering
        bbox_filter = None
        if bbox_str:
            try:
                bbox_parts = [float(x.strip()) for x in bbox_str.split(',')]
                if len(bbox_parts) == 4:
                    bbox_filter = {
                        'minLat': bbox_parts[0],
                        'minLon': bbox_parts[1],
                        'maxLat': bbox_parts[2],
                        'maxLon': bbox_parts[3]
                    }
            except:
                pass

        # 1. Fetch Satellite Tile
        n = 2.0 ** zoom
        xtile = int((lon + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)

        tile_url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ytile}/{xtile}"
        resp = requests.get(tile_url, headers={'User-Agent': 'HayOS/1.0'}, timeout=10)
        
        if resp.status_code != 200:
             return jsonify({'error': 'Imagery Offline'}), 502

        image_array = np.asarray(bytearray(resp.content), dtype=np.uint8)
        img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        if img is None:
             return jsonify({'error': 'Buffer Decode Error'}), 500
        
        # 2. YOLO Segmentation
        if yolo_seg_model is None:
            # Use nano segmentation model for performance
            yolo_seg_model = YOLO('yolov8n-seg.pt')

        results = yolo_seg_model(img, conf=0.25)[0]
        
        features = []
        
        # Tile Math for coordinate conversion
        lon_deg = (xtile / n * 360.0) - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
        lat_deg = math.degrees(lat_rad)
        lat_rad_next = math.atan(math.sinh(math.pi * (1 - 2 * (ytile + 1) / n)))
        lat_deg_next = math.degrees(lat_rad_next)
        total_lat_diff = lat_deg - lat_deg_next
        
        # YOLO class mapping to HayOS labels
        if results.masks is not None:
            for i, (mask, box) in enumerate(zip(results.masks.xy, results.boxes)):
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                
                # Filter small noise
                if len(mask) < 3: continue
                
                geo_points = []
                for pt in mask:
                    px, py = pt
                    # Satellite tiles are typically 256x256
                    h, w = img.shape[:2]
                    p_lon = lon_deg + (px / float(w)) * (360.0 / n)
                    p_lat = lat_deg - (py / float(h)) * total_lat_diff
                    geo_points.append([p_lon, p_lat])
                
                # Close the polygon
                geo_points.append(geo_points[0])

                # Heuristic Labeling based on YOLO classes
                label = "STRUCTURE_UNIT"
                sub_type = "GENERAL_SECTOR"
                
                if class_id in [2, 3, 5, 7]: # car, motorcycle, bus, truck
                    label = "TRANS_CLASS"
                    sub_type = "VEHICLE_LOGISTICS"
                elif class_id == 0: # person
                    label = "BIO_DETECT"
                    sub_type = "HUMAN_PRESENCE"
                elif class_id in [56, 57, 58, 59, 60, 61]: # chair, couch, potted plant, bed, dining table, toilet
                    label = "INFRA_CLASS"
                    sub_type = "INTERIOR_ELEMENT"
                
                # Estimate area in pixels (approximate)
                area = cv2.contourArea(np.array(mask).astype(np.float32))

                # Calculate Geographic Bounding Box
                # box.xyxy[0] contains [x1, y1, x2, y2] in pixels
                x1, y1, x2, y2 = box.xyxy[0]
                h_img, w_img = img.shape[:2]
                
                bbox_geo = [
                    [lon_deg + (x1 / float(w_img)) * (360.0 / n), lat_deg - (y1 / float(h_img)) * total_lat_diff], # Top-Left
                    [lon_deg + (x2 / float(w_img)) * (360.0 / n), lat_deg - (y2 / float(h_img)) * total_lat_diff]  # Bottom-Right
                ]

                # Filter by bbox if provided
                if bbox_filter:
                    center_lat = (bbox_geo[0][1] + bbox_geo[1][1]) / 2
                    center_lon = (bbox_geo[0][0] + bbox_geo[1][0]) / 2
                    if not (bbox_filter['minLat'] <= center_lat <= bbox_filter['maxLat'] and 
                           bbox_filter['minLon'] <= center_lon <= bbox_filter['maxLon']):
                        continue  # Skip this detection if outside bbox

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [geo_points]},
                    "properties": {
                        "id": f"YOLO-{class_id}-{i}",
                        "classification": label,
                        "type": sub_type,
                        "area": f"{int(area)} px",
                        "status": "VALIDATED",
                        "confidence": f"{int(confidence * 100)}%",
                        "bbox": bbox_geo
                    }
                })

        return jsonify({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "engine": "YOLO_V8_SEG",
                "objects": len(features),
                "sector": f"{xtile}/{ytile}"
            }
        })
    except Exception as e:
        app.logger.error(f"SEG_CRITICAL: {e}")
        return jsonify({'error': str(e)}), 500

def get_exif_gps(img_pil):
    """Extract GPS coordinates from PIL Image EXIF data."""
    try:
        exif = img_pil._getexif()
        if not exif:
            return None
        
        gps_info = {}
        for tag, value in exif.items():
            decoded = ExifTags.TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                for t in value:
                    sub_decoded = ExifTags.GPSTAGS.get(t, t)
                    gps_info[sub_decoded] = value[t]
        
        if not gps_info:
            return None

        def convert_to_degrees(value):
            d = float(value[0])
            m = float(value[1])
            s = float(value[2])
            return d + (m / 60.0) + (s / 3600.0)

        lat = convert_to_degrees(gps_info["GPSLatitude"])
        if gps_info["GPSLatitudeRef"] != "N":
            lat = -lat
        
        lon = convert_to_degrees(gps_info["GPSLongitude"])
        if gps_info["GPSLongitudeRef"] != "E":
            lon = -lon
            
        return {"lat": lat, "lon": lon}
    except Exception as e:
        app.logger.error(f"GPS_EXIF_ERR: {e}")
        return None

@app.route('/api/geo/analyze-upload', methods=['POST'])
@app.route('/upload', methods=['POST'])

def analyze_upload():
    """Analyze uploaded image for objects and GPS metadata."""
    global yolo_seg_model
    # Check both 'image' and 'img' (user's provided form name)
    field_name = 'image' if 'image' in request.files else 'img'
    
    if field_name not in request.files:
        return jsonify({"error": "No image uploaded"}), 400
        
    file = request.files[field_name]
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
        
    try:
        # 1. Load Image
        in_memory_file = io.BytesIO()
        file.save(in_memory_file)
        data = np.frombuffer(in_memory_file.getvalue(), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        
        if img is None:
            return jsonify({"error": "Invalid image format"}), 400
            
        # 2. Extract Location
        img_pil = Image.open(io.BytesIO(in_memory_file.getvalue()))
        location = get_exif_gps(img_pil)
        
        # 3. Run YOLO Discovery
        if yolo_seg_model is None:
            yolo_seg_model = YOLO('yolov8n-seg.pt')
            
        results = yolo_seg_model(img, conf=0.25)[0]
        detections = []
        
        if results.boxes is not None:
            for box in results.boxes:
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                label = results.names[class_id].upper()
                
                detections.append({
                    "object": label,
                    "confidence": f"{int(confidence * 100)}%",
                    "tag": f"DISCOVERY_{class_id}"
                })
        
        # 4. Return Data
        return jsonify({
            "status": "ANALYSIS_COMPLETE",
            "location": location or {"lat": "UNKNOWN", "lon": "UNKNOWN"},
            "objects": detections,
            "count": len(detections),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        app.logger.error(f"UPLOAD_ANALYSIS_CRITICAL: {e}")
        return jsonify({"error": str(e)}), 500
@app.route('/api/geo/flight/meta/<callsign>')
def get_flight_meta(callsign):
    # Mock implementation for flight metadata
    return jsonify({
        "callsign": callsign,
        "image": f"https://cdn.jetphotos.com/full/5/{random.randint(10000, 99999)}.jpg",
        "operator": "Unknown Operator",
        "age": f"{random.randint(1, 25)} years"
    })

@app.route('/api/geo/news')

def get_geo_news():
    """
    Fetch geopolitical news and tweets for a specific location.
    ATTEMPTS REAL API CALLS FIRST, FALLS BACK TO MOCK DATA.
    """
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    if lat is None or lon is None:
        return jsonify({"error": "Missing coordinates"}), 400

    # --- Check Cache ---
    cache_key = f"geo_{lat}_{lon}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if cache_key in news_cache:
        cached_time, cached_data = news_cache[cache_key]
        if (now_ts - cached_time) < (NEWS_CACHE_LIMIT * 60):
            print(f"Serving cached geo news for: {cache_key}")
            return jsonify(cached_data)

    real_tweets = []
    real_news = []
    
    # --- 1. Try Real Twitter API v2 (Search) ---
    # Using Bearer Token is easiest for Search v2
    if TWITTER_BEARER_TOKEN and TWITTER_BEARER_TOKEN != 'YOUR_BEARER_TOKEN_HERE':
        try:
            headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
            
            # Twitter API v2 Recent Search - NOTE: This requires ELEVATED access (not free tier)
            # Free tier (Essential) does NOT have access to search endpoints
            # We'll try anyway in case user has elevated access
            params = {
                'query': '(breaking OR news OR alert) -is:retweet lang:en',
                'max_results': 2,
                'tweet.fields': 'created_at,author_id,text'
            }
            
            response = requests.get('https://api.twitter.com/2/tweets/search/recent', headers=headers, params=params, timeout=5)
            
            print(f"Twitter API Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    for t in data['data']:
                        # Parse timestamp
                        created = t.get('created_at', '')
                        try:
                            dt = datetime.strptime(created, '%Y-%m-%dT%H:%M:%S.%fZ')
                            time_str = dt.strftime('%H:%M:%S')
                        except:
                            time_str = 'Recent'
                            
                        real_tweets.append({
                            "user": f"@User_{t.get('author_id', 'Unknown')[-4:]}",
                            "text": t.get('text', ''),
                            "timestamp": time_str
                        })
                    print(f"Twitter: Fetched {len(real_tweets)} tweets")
                else:
                    print(f"Twitter API response has no 'data': {data}")
            else:
                print(f"Twitter API Error: {response.status_code} - {response.text[:200]}")
                
        except Exception as e:
            print(f"Twitter API Exception: {e}")

    # --- 2. Try Real NewsAPI with Location Context ---
    if NEWS_API_KEY and NEWS_API_KEY != 'mock_news_key':
        try:
            # Try to get location name via reverse geocoding
            location_query = ""
            try:
                geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
                geo_res = requests.get(geo_url, timeout=2, headers={'User-Agent': 'HayOS/1.0'})
                if geo_res.status_code == 200:
                    geo_data = geo_res.json()
                    # Try to extract country or city
                    address = geo_data.get('address', {})
                    location_query = address.get('country', '') or address.get('city', '') or address.get('state', '')
                    print(f"Reverse geocode: {location_query}")
            except Exception as geo_err:
                print(f"Geocoding error: {geo_err}")
            
            # --- Regional RSS Detection ---
            detected_region = ""
            country_mapping = {
                "United States": "USA", "India": "INDIA", "China": "CHINA",
                "Russia": "RUSSIA", "Japan": "JAPAN", "Australia": "AUSTRALIA",
                "Taiwan": "TAIWAN", "South Korea": "SOUTH_KOREA", "Israel": "ISRAEL",
                "United Arab Emirates": "UAE", "Iran": "IRAN"
            }
            
            for c_name, reg_key in country_mapping.items():
                if location_query and c_name in location_query:
                    detected_region = reg_key
                    break
            
            if not detected_region and location_query:
                # Broad region checks
                if any(x in location_query for x in ["Europe", "France", "Germany", "Spain", "Italy", "UK", "London"]):
                     detected_region = "EUROPE"
                elif any(x in location_query for x in ["Africa", "Kenya", "Nigeria", "Egypt", "South Africa"]):
                     detected_region = "AFRICA"
            
            if detected_region:
                print(f"Uplinking regional RSS: {detected_region}")
                rss_geo = fetch_rss_news(detected_region)
                real_news.extend(rss_geo[:5]) # Mix in some RSS

            # Build NewsAPI query
            if location_query:
                # Search for news about this location (all languages)
                news_url = f"https://newsapi.org/v2/everything?q={location_query}&sortBy=publishedAt&pageSize=10&apiKey={NEWS_API_KEY}"
            else:
                # Fallback to top headlines (all languages)
                news_url = f"https://newsapi.org/v2/top-headlines?pageSize=10&apiKey={NEWS_API_KEY}"
            
            n_res = requests.get(news_url, timeout=5)
            print(f"NewsAPI Status: {n_res.status_code}")
            
            if n_res.status_code == 200:
                n_data = n_res.json()
                for article in n_data.get('articles', [])[:50]:
                    # Parse timestamp
                    pub_time = article.get('publishedAt', '')
                    try:
                        dt = datetime.strptime(pub_time, '%Y-%m-%dT%H:%M:%SZ')
                        time_str = dt.strftime('%H:%M %b %d')
                    except:
                        time_str = 'Recent'
                        
                    real_news.append({
                        "source": article.get('source', {}).get('name', 'NewsAPI'),
                        "title": article.get('title', ''),
                        "time": time_str,
                        "url": article.get('url', '#'),
                        "published": pub_time or datetime.now(timezone.utc).isoformat(),
                        "type": "GEO_INTEL"
                    })
                print(f"NewsAPI: Fetched {len(real_news)} articles")
            else:
                print(f"NewsAPI Error: {n_res.status_code} - {n_res.text[:200]}")
        except Exception as e:
             print(f"News API Exception: {e}")

    # --- 3. Mock Fallback (If APIs didn't yield results) ---
    sentiment_score = random.uniform(0.1, 0.9)
    sentiment_label = "NEUTRAL"
    if sentiment_score > 0.7: sentiment_label = "STABLE"
    elif sentiment_score < 0.3: sentiment_label = "CRITICAL"
    elif sentiment_score < 0.5: sentiment_label = "UNREST"

    if not real_tweets:
        hashtags = ["#Breaking", "#Alert", "#Status", "#Update", "#Intel"]
        for _ in range(2):
             real_tweets.append({
                "user": f"@User_{random.randint(1000,9999)}",
                "text": f"Activity reported in sector {random.randint(1,99)}. Status: {sentiment_label}. {random.choice(hashtags)}",
                "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=random.randint(1, 60))).strftime("%H:%M:%S")
            })

    if not real_news:
        headlines = [
            "Regional security alert issued for this sector.",
            "Infrastructure development updates pending.",
            "Local communications monitoring active.",
            "Weather systems affecting transport logic.",
            "Cyber-surveillance grid expansion initiated."
        ]
        for _ in range(random.randint(2, 3)):
            real_news.append({
                "source": "GNN (Global News Network)",
                "title": random.choice(headlines),
                "time": "Just now",
                "url": "#",
                "published": datetime.now(timezone.utc).isoformat(),
                "type": "MOCK_INTEL"
            })
        
    result_data = {
        "lat": lat,
        "lon": lon,
        "sentiment": {
            "score": round(sentiment_score, 2),
            "label": sentiment_label,
            "trend": random.choice(["RISING", "FALLING", "STABLE"])
        },
        "tweets": real_tweets,
        "news": real_news,
        "intel_summary": f"Sector scan complete. {len(real_tweets)} signals intercepted."
    }

    # Store in cache
    news_cache[cache_key] = (now_ts, result_data)

    return jsonify(result_data)

def analyze_with_ai(context):
    """
    Use OpenRouter to analyze geopolitical context and sentiment.
    """
    if not OPENROUTER_API_KEY or "placeholder" in OPENROUTER_API_KEY:
        # Fallback to deterministic patterns if no key
        return f"AI_SIMULATION: Based on intercepted signals, tensions in this sector are currently {random.choice(['elevated', 'stable', 'volatile'])}. Strategic nodes show pattern {random.randint(100,999)}."

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps({
                "model": "google/gemini-2.0-flash-exp:free", # Using a free model for demonstration
                "messages": [
                    {"role": "system", "content": "You are HayOS Geopolitical AI. Analyze the provided news context and provide a brief, high-tech assessment of the situation in 2-3 sentences. Use CYBERPUNK/OSINT tone."},
                    {"role": "user", "content": context}
                ]
            }),
            timeout=10
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"OpenRouter Error: {e}")
    
    return "ANALYSIS_OFFLINE: Connectivity to Neural Core interrupted."

@app.route('/api/news/analyze', methods=['POST'])

def analyze_news_sentiment():
    data = request.json
    content = data.get('content', '')
    if not content:
        return jsonify({"error": "No content provided"}), 400
    
    analysis = analyze_with_ai(content)
    return jsonify({"analysis": analysis})

@app.route('/api/market/data')

def get_market_data():
    """
    Fetch market data for Oil, Gold, Silver, and Crypto.
    """
    try:
        # 1. Crypto from CoinGecko (Free API)
        crypto_res = requests.get('https://api.coingecko.org/api/v3/simple/price?ids=bitcoin,ethereum,solana,cardano,ripple,polkadot,dogecoin,binancecoin,chainlink,matic-network&vs_currencies=usd&include_24hr_change=true', timeout=5)
        crypto_data = crypto_res.json() if crypto_res.status_code == 200 else {}

        # 2. Mock Commodities (Hard to find free reliable real-time commodity API without keys)
        # In a real app, one would use AlphaVantage or similar.
        commodities = {
            "OIL": {"price": 74.23 + random.uniform(-0.5, 0.5), "change": 1.2},
            "BRENT": {"price": 79.12 + random.uniform(-0.5, 0.5), "change": -0.4},
            "GOLD": {"price": 2035.50 + random.uniform(-5, 5), "change": 0.15},
            "SILVER": {"price": 22.84 + random.uniform(-0.1, 0.1), "change": -0.2}
        }

        # Format crypto
        formatted_crypto = {}
        for k, v in crypto_data.items():
            name = k.upper().replace('-NETWORK', '')
            formatted_crypto[name] = {"price": v['usd'], "change": v['usd_24h_change']}

        return jsonify({
            "status": "LIVE",
            "timestamp": datetime.now().isoformat(),
            "commodities": commodities,
            "crypto": formatted_crypto
        })
    except Exception as e:
        print(f"Market Data Error: {e}")
        # Robust fallback if API fails
        commodities = {
            "OIL": {"price": 74.23 + random.uniform(-0.5, 0.5), "change": 0.0},
            "BRENT": {"price": 79.12 + random.uniform(-0.5, 0.5), "change": 0.0},
            "GOLD": {"price": 2035.50 + random.uniform(-5, 5), "change": 0.0},
            "SILVER": {"price": 22.84 + random.uniform(-0.1, 0.1), "change": 0.0}
        }
        mock_crypto = {
            "BITCOIN": {"price": 42000, "change": 0.0},
            "ETHEREUM": {"price": 2500, "change": 0.0},
            "SOLANA": {"price": 100, "change": 0.0}
        }
        return jsonify({
            "status": "OFFLINE_SIMULATION",
            "timestamp": datetime.now().isoformat(),
            "commodities": commodities,
            "crypto": mock_crypto,
            "error": str(e)
        })

@app.route('/news')

def news_page():
    return render_template('news.html')

@app.route('/newsnetworks')

def newsnetworks_page():
    return render_template('newsnetworks.html', sources=NEWS_SOURCES)

def fetch_rss_news(region):
    """
    Fetch and parse all RSS feeds for a given region defined in news_config.py.
    """
    articles = []
    if region not in NEWS_SOURCES:
        return articles
    
    rss_urls = NEWS_SOURCES[region].get('rss', [])
    for url in rss_urls:
        try:
            # We use a timeout to avoid hanging on slow feeds
            feed = feedparser.parse(url)
            source_name = feed.feed.get('title', url.split('/')[2])
            for entry in feed.entries[:10]: 
                # Basic formatting for consistency
                articles.append({
                    "source": source_name,
                    "title": entry.get('title'),
                    "url": entry.get('link'),
                    "published": entry.get('published') or entry.get('updated') or datetime.now(timezone.utc).isoformat(),
                    "description": entry.get('summary', '')[:200] + "..." if entry.get('summary') else "",
                    "image": None,
                    "type": f"RSS_{region}"
                })
        except Exception as e:
            print(f"Error parsing RSS {url}: {e}")
            
    return articles

@app.route('/api/news/advanced')
def get_advanced_news():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    query = request.args.get('q', '')
    news_type = request.args.get('type', 'all') 
    region = request.args.get('region', '').upper()
    
    if not NEWS_API_KEY or NEWS_API_KEY == "YOUR_NEWS_API_KEY": # Let real keys through
        # If no key, try RSS first
        if region:
            rss_news = fetch_rss_news(region)
            if rss_news:
                return jsonify({
                    "query": query or region,
                    "articles": rss_news,
                    "count": len(rss_news)
                })
        
        # If no key, and no lat/lon, return mock global news
        if not lat or not lon:
            # Fallback to general INTERNATIONAL RSS if possible
            if not region:
                rss_intl = fetch_rss_news("INTERNATIONAL")
                if rss_intl:
                    return jsonify({
                        "query": "INTERNATIONAL INTEL",
                        "articles": rss_intl,
                        "count": len(rss_intl)
                    })

            mock_articles = []
            mock_headlines = [
                "Global Cyber-Defense Protocol H9-EYE Initiated",
                "Quantum Encryption Standards Adopted by Major Sectors",
                "AI Sentiment Analysis Reveals Shifting Geopolitical Tides",
                "Decentralized Data Grids Expanding in Neutral Zones",
                "Satellite Uplink Stability Reaches Record 99.9%"
            ]
            for i, h in enumerate(mock_headlines):
                mock_articles.append({
                    "source": "H9_OSINT_CORE",
                    "title": h,
                    "url": "#",
                    "published": (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(),
                    "description": "Simulation data generated by HayOS Core Intelligence.",
                    "image": None,
                    "type": "CORE_STREAM"
                })
            return jsonify({
                "query": query or "global news",
                "articles": mock_articles,
                "count": len(mock_articles)
            })
        return get_geo_news()

    news_articles = []
    search_query = query
    if lat and lon:
        try:
            geo_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
            g_res = requests.get(geo_url, headers={'User-Agent': 'HayOS/1.0'}, timeout=5)
            if g_res.status_code == 200:
                address = g_res.json().get('address', {})
                city = address.get('city') or address.get('town') or address.get('village')
                country = address.get('country')
                
                if news_type == 'local' and city:
                    search_query += f" {city}"
                elif news_type == 'national' and country:
                    search_query += f" {country}"
                elif news_type == 'all':
                    search_query += f" {city or country or ''}"
        except:
            pass

    sort_by = request.args.get('sortBy', 'publishedAt')
    from_date = request.args.get('from', '')
    language = request.args.get('language', 'en')
    page_size = 10 # Hard limit to 10 as per user request
    
    # --- Check Cache ---
    cache_key = f"advanced_{search_query}_{language}_{sort_by}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if cache_key in news_cache:
        cached_time, cached_data = news_cache[cache_key]
        if (now_ts - cached_time) < (NEWS_CACHE_LIMIT * 60):
            print(f"Serving cached news for: {cache_key}")
            return jsonify(cached_data)

    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            'q': search_query.strip() or 'world news',
            'apiKey': NEWS_API_KEY,
            'language': language,
            'sortBy': sort_by,
            'pageSize': page_size
        }
        if from_date:
            params['from'] = from_date

        print(f"Requesting NewsAPI: {url} with params: {params}")
        response = requests.get(url, params=params, timeout=10)
        print(f"NewsAPI Response Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"NewsAPI successfully fetched {len(data.get('articles', []))} articles.")
            for art in data.get('articles', []):
                news_articles.append({
                    "source": art.get('source', {}).get('name', 'N/A'),
                    "title": art.get('title'),
                    "url": art.get('url'),
                    "published": art.get('publishedAt'),
                    "description": art.get('description'),
                    "image": art.get('urlToImage'),
                    "type": "INTEL_FEED"
                })
        else:
             print(f"NewsAPI Error (Advanced): {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"Advanced News Fetch Error: {e}")

    # If region is provided, fetch RSS to complement NewsAPI
    # DEFAULT behavior: if no region specified, mixing in INTERNATIONAL RSS
    rss_region = region if region else "INTERNATIONAL"
    rss_news = fetch_rss_news(rss_region)
    news_articles.extend(rss_news)

    # Final logic: if articles still empty, provide mock data for fallback
    if not news_articles:
        mock_headlines = [
            "Data Stream Corrupted: Displaying Archived Intelligence",
            "Global Security Lattice Synchronizing...",
            "Neutral Zone Communication Nodes Restored",
            "AI Predictive Core Detects Low-Level Sector Volatility",
            "OSINT Nodes Reporting Stable Uplink in Peripheral Sectors"
        ]
        for i, h in enumerate(mock_headlines):
            news_articles.append({
                "source": "H9_EMERGENCY_UPLINK",
                "title": h,
                "url": "#",
                "published": (datetime.now(timezone.utc) - timedelta(hours=i*2)).isoformat(),
                "description": "Fallback intelligence provided by HayOS redundant storage.",
                "image": None,
                "type": "FALLBACK_STREAM"
            })

    # Store in cache if successful (even if only RSS articles found)
    if news_articles:
        result_data = {
            "query": search_query,
            "articles": news_articles,
            "count": len(news_articles)
        }
        news_cache[cache_key] = (now_ts, result_data)

    return jsonify({
        "query": search_query,
        "articles": news_articles,
        "count": len(news_articles)
    })

@app.route('/api/translate')
def translate_text():
    """
    Translate text to English using free translation service.
    Uses MyMemory Translation API (free, no key required).
    """
    text = request.args.get('text', '')
    source_lang = request.args.get('source', 'auto')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    
    try:
        # MyMemory doesn't support 'auto', so we need to try common languages
        # or use a simple heuristic
        if source_lang == 'auto':
            # Try translating from multiple common languages and pick the best one
            # Common news languages: Spanish, French, German, Arabic, Chinese, Russian, etc.
            test_langs = ['es', 'fr', 'de', 'ar', 'zh', 'ru', 'ja', 'pt', 'it', 'nl']
            
            # Quick heuristic: if text is already mostly English, don't translate
            if text.replace(' ', '').isascii():
                # Likely already English or uses Latin script
                source_lang = 'en'
            else:
                # Try the first non-English language (most common: Spanish)
                source_lang = 'es'
        
        # Using MyMemory Translation API (free, no key required)
        # Limit: 500 words per request, 10000 words per day
        url = "https://api.mymemory.translated.net/get"
        params = {
            'q': text[:500],  # Limit to 500 chars
            'langpair': f'{source_lang}|en'
        }
        
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            translated = data.get('responseData', {}).get('translatedText', text)
            
            # If translation is same as original, it might already be in English
            if translated == text or translated.upper() == text.upper():
                return jsonify({
                    "original": text,
                    "translated": text,
                    "source_lang": "en",
                    "note": "Already in English"
                })
            
            return jsonify({
                "original": text,
                "translated": translated,
                "source_lang": source_lang
            })
        else:
            return jsonify({"error": "Translation failed", "original": text}), 500
            
    except Exception as e:
        print(f"Translation error: {e}")
        return jsonify({"error": str(e), "original": text}), 500


def get_flight_meta(callsign):
    """Fetch route and registration data for a specific callsign."""
    if not callsign or callsign == "N/A":
        return jsonify({"error": "No callsign provided"}), 400
        
    try:
        # 1. Try Routes API (Origin/Destination)
        route_url = f"https://opensky-network.org/api/routes?callsign={callsign}"
        r_res = requests.get(route_url, timeout=10)
        route_data = {}
        if r_res.status_code == 200:
            route_data = r_res.json()
            
        return jsonify({
            "callsign": callsign,
            "route": route_data.get("route", ["UNK", "UNK"]),
            "operator": route_data.get("operatorIata", "---"),
            "flight_number": route_data.get("flightNumber", "---")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500









# === YOUR EXACT SSL BLOCK ===
import ssl
if __name__ == "__main__":
    

    app.run(host="0.0.0.0", port=8000, debug=True)

