from flask import Flask, render_template, jsonify, request
import webbrowser
from threading import Timer, Thread
import osmnx as ox
from logica_algoritmos import MotorAlgoritmos
from datetime import datetime, timedelta
import math
import csv
import json
import os
import requests 
import re
import sqlite3
import time

app = Flask(__name__)

GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'AIzaSyDwcTata9GRrxeWx8_PP0hkH1EYEgrTJeQ')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'georuta_cache.db')

def conectar_bd():
    """Establece conexión con la base de datos local SQLite (Zero configuración)"""
    try: 
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row 
        return conn
    except Exception as e: 
        print(f"Error de conexión SQLite: {e}")
        return None

def crear_tablas():
    """Crea las tablas en el archivo .db local si no existen"""
    conexion = conectar_bd()
    if not conexion: 
        return False
    try:
        cursor = conexion.cursor()
        
        # Tabla principal de caché
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_rutas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen_lat REAL, origen_lon REAL,
            destino_lat REAL, destino_lon REAL,
            tiempo_segundos INTEGER, distancia_metros INTEGER, modo TEXT,
            ruta_json TEXT, segmentos_json TEXT, polyline TEXT,
            fecha_consulta DATETIME
        )""")

        # Tabla de historial de viajes
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial_viajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen_nombre TEXT,
            destino_nombre TEXT,
            origen_lat REAL,
            origen_lon REAL,
            destino_lat REAL,
            destino_lon REAL,
            modo TEXT,
            tiempo_minutos INTEGER,
            distancia_km REAL,
            polyline TEXT,
            fecha DATETIME
        )""")

        # Tabla de reseñas de eventos
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS evento_resenas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_nombre TEXT,
            calificacion INTEGER,
            comentario TEXT,
            fecha DATETIME
        )""")
        
        conexion.commit()
        cursor.close()
        conexion.close()
        return True
    except Exception as e: 
        print(f"Error creando tablas SQLite: {e}")
        return False

def purgar_fechas_futuras():
    """
    Limpiador automático: Detecta si la base de datos se quedó con horas del 
    futuro debido al bug anterior (UTC) y las elimina para forzar el uso de Google API
    y destrabar el caché de 10 minutos.
    """
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conexion = conectar_bd()
        if conexion:
            cursor = conexion.cursor()
            cursor.execute("DELETE FROM cache_rutas WHERE fecha_consulta > ?", (fecha_actual,))
            cursor.execute("DELETE FROM historial_viajes WHERE fecha > ?", (fecha_actual,))
            conexion.commit()
            conexion.close()
            print("✅ Limpieza de horas futuras completada.")
    except Exception as e:
        print(f"Error purgando fechas: {e}")

# GESTIÓN DE ARCHIVOS (JSON Y CSV)
DATASET_CSV = os.path.join(BASE_DIR, "eventos_carabayllo_2026_ampliado.csv")
HISTORIAL_JSON = os.path.join(BASE_DIR, "historial_busquedas.json")
historial_busquedas = []

def cargar_historial():
    global historial_busquedas
    if os.path.exists(HISTORIAL_JSON):
        try:
            with open(HISTORIAL_JSON, 'r', encoding='utf-8') as f:
                historial_busquedas = json.load(f)
        except: 
            historial_busquedas = [] 

def guardar_historial():
    try:
        with open(HISTORIAL_JSON, 'w', encoding='utf-8') as f:
            json.dump(historial_busquedas, f, ensure_ascii=False, indent=2)
    except Exception as e: 
        print(f"Error guardando historial: {e}")

def cargar_eventos_csv():
    eventos = []
    if os.path.exists(DATASET_CSV):
        try:
            try:
                with open(DATASET_CSV, newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader: eventos.append(row)
            except UnicodeDecodeError:
                with open(DATASET_CSV, newline='', encoding='latin-1') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader: eventos.append(row)
        except Exception as e: 
            pass
    return eventos

cargar_historial()

def haversine(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * 6371000 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))

def decode_polyline(polyline_str):
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(polyline_str):
        result, shift = 0, 0
        while True:
            char = ord(polyline_str[index]) - 63; index += 1
            result |= (char & 0x1f) << shift; shift += 5
            if not (char & 0x20): break
        lat += ~(result >> 1) if (result & 1) else (result >> 1)
        result, shift = 0, 0
        while True:
            char = ord(polyline_str[index]) - 63; index += 1
            result |= (char & 0x1f) << shift; shift += 5
            if not (char & 0x20): break
        lng += ~(result >> 1) if (result & 1) else (result >> 1)
        coords.append([lat / 1e5, lng / 1e5])
    return coords

def limpiar_html(texto):
    return re.sub(r'<[^>]+>', ' ', texto).strip()

def consultar_google_directions_api(lat_o, lon_o, lat_d, lon_d, modo='driving'):
    """Actualizado para utilizar Google Routes API v2 para mayor precisión."""
    modo_map = {'driving': 'DRIVE', 'walking': 'WALK', 'bicycling': 'BICYCLE'}
    modo_routes = modo_map.get(modo, 'DRIVE')
    try:
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': GOOGLE_MAPS_API_KEY,
            'X-Goog-FieldMask': 'routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.legs.steps.distanceMeters,routes.legs.steps.navigationInstruction,routes.legs.startLocation,routes.legs.endLocation'
        }
        payload = {
            "origin": {"location": {"latLng": {"latitude": lat_o, "longitude": lon_o}}},
            "destination": {"location": {"latLng": {"latitude": lat_d, "longitude": lon_d}}},
            "travelMode": modo_routes,
            "routingPreference": "TRAFFIC_AWARE" if modo_routes == 'DRIVE' else "ROUTING_PREFERENCE_UNSPECIFIED",
            "languageCode": "es-PE"
        }
        
        res = requests.post(url, headers=headers, json=payload, timeout=8).json()
        if 'routes' not in res or not res['routes']: return None
        
        route = res['routes'][0]
        tiempo_s = int(route.get('duration', '0s').replace('s', ''))
        dist_m = route.get('distanceMeters', 0)
        overview_polyline = route.get('polyline', {}).get('encodedPolyline', '')
        
        puntos = decode_polyline(overview_polyline) if overview_polyline else []
        
        leg = route.get('legs', [{}])[0]
        snapped_o = [leg.get('startLocation', {}).get('latLng', {}).get('latitude', lat_o), 
                     leg.get('startLocation', {}).get('latLng', {}).get('longitude', lon_o)]
        snapped_d = [leg.get('endLocation', {}).get('latLng', {}).get('latitude', lat_d), 
                     leg.get('endLocation', {}).get('latLng', {}).get('longitude', lon_d)]
        
        segmentos = []
        for step in leg.get('steps', []):
            instr = step.get('navigationInstruction', {}).get('instructions', 'Avanzar')
            dist_step = step.get('distanceMeters', 0)
            dist_text = f"{dist_step} m" if dist_step < 1000 else f"{round(dist_step/1000, 1)} km"
            segmentos.append({
                'nombre': instr, 
                'distancia_m': dist_text, 
                'trafico': 'Evaluado', 
                'complicaciones': []
            })

        if not puntos: return None

        return {
            'distancia_m': dist_m, 'tiempo_min': max(1, round(tiempo_s/60)), 
            'puntos_ruta': puntos, 'segmentos': segmentos,
            'snapped_o': snapped_o, 'snapped_d': snapped_d,
            'overview_polyline': overview_polyline  
        }
    except Exception as e: 
        print(f"Error Routes API: {e}")
        return None

# RECUPERACIÓN SILENCIOSA DE POLYLINES ANTERIORES
def recuperar_polylines_en_segundo_plano():
    time.sleep(5) 
    try:
        conexion = conectar_bd()
        if not conexion: return
        cursor = conexion.cursor()
        cursor.execute("SELECT id, origen_lat, origen_lon, destino_lat, destino_lon FROM historial_viajes WHERE polyline = '' OR polyline IS NULL")
        viajes_incompletos = cursor.fetchall()
        
        for viaje in viajes_incompletos:
            res = consultar_google_directions_api(viaje['origen_lat'], viaje['origen_lon'], viaje['destino_lat'], viaje['destino_lon'], 'driving')
            if res and res.get('overview_polyline'):
                cursor.execute("UPDATE historial_viajes SET polyline = ? WHERE id = ?", (res['overview_polyline'], viaje['id']))
                conexion.commit()
            time.sleep(1.5) 
        conexion.close()
    except Exception as e:
        print(f"Recuperación silenciosa finalizada o interrumpida: {e}")

@app.route('/snap', methods=['POST'])
def snap_to_road(): 
    data = request.json or {}
    lat = float(data.get('lat', 0))
    lng = float(data.get('lng', 0))
    if not G_busqueda:
        return jsonify({'lat': lat, 'lng': lng})
    try:
        nodo = nearest_node_por_coordenadas(G_busqueda, lat, lng)
        if nodo is None: return jsonify({'lat': lat, 'lng': lng})
        ndata = G_busqueda.nodes[nodo]
        return jsonify({'lat': ndata.get('y', lat), 'lng': ndata.get('x', lng)})
    except: return jsonify({'lat': lat, 'lng': lng})

def nearest_node_por_coordenadas(G, lat, lon):
    nodo_cercano = None; distancia_minima = float('inf')
    for nodo, datos in G.nodes(data=True):
        nodo_lat, nodo_lon = datos.get('y'), datos.get('x')
        if nodo_lat is None or nodo_lon is None: continue
        dist = haversine(lat, lon, nodo_lat, nodo_lon)
        if dist < distancia_minima: 
            distancia_minima = dist
            nodo_cercano = nodo
    return nodo_cercano

try:
    G_busqueda = ox.load_graphml("mapa_base.graphml")
    motor_alg = MotorAlgoritmos(G_busqueda)
except: 
    G_busqueda = None
    motor_alg = None

def open_browser(): webbrowser.open_new("http://127.0.0.1:5050")

@app.route('/')
def root(): return render_template('login.html', api_key=GOOGLE_MAPS_API_KEY)
@app.route('/login.html')
def login(): return render_template('login.html', api_key=GOOGLE_MAPS_API_KEY)
@app.route('/index.html')
def index(): return render_template('index.html', api_key=GOOGLE_MAPS_API_KEY)
@app.route('/admin.html')
def admin(): return render_template('admin.html', api_key=GOOGLE_MAPS_API_KEY)

@app.route('/api/agregar_resena', methods=['POST'])
def agregar_resena():
    data = request.json
    try:
        fecha_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conexion = conectar_bd()
        if conexion:
            cursor = conexion.cursor()
            sql = "INSERT INTO evento_resenas (evento_nombre, calificacion, comentario, fecha) VALUES (?, ?, ?, ?)"
            cursor.execute(sql, (data['evento_nombre'], data['calificacion'], data['comentario'], fecha_local))
            conexion.commit(); cursor.close(); conexion.close()
            return jsonify({"status": "success", "mensaje": "Reseña guardada exitosamente."})
        return jsonify({"status": "error", "mensaje": "Error de base de datos."})
    except Exception as e: return jsonify({"status": "error", "mensaje": str(e)})

@app.route('/api/ver_resenas/<evento>', methods=['GET'])
def ver_resenas(evento):
    try:
        conexion = conectar_bd()
        if conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT calificacion, comentario FROM evento_resenas WHERE evento_nombre = ? ORDER BY id DESC LIMIT 5", (evento,))
            resenas = [dict(row) for row in cursor.fetchall()]
            cursor.close(); conexion.close()
            return jsonify({"status": "success", "data": resenas})
    except: pass
    return jsonify({"status": "error", "data": []})

@app.route('/api/promedio_resenas/<evento>', methods=['GET'])
def promedio_resenas(evento):
    try:
        conexion = conectar_bd()
        if conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT AVG(calificacion) AS promedio, COUNT(*) AS total FROM evento_resenas WHERE evento_nombre = ?", (evento,))
            resultado = cursor.fetchone()
            cursor.close(); conexion.close()
            promedio = float(resultado['promedio']) if resultado and resultado['promedio'] is not None else 0.0
            total = int(resultado['total']) if resultado and resultado['total'] is not None else 0
            return jsonify({"status": "success", "promedio": round(promedio, 1), "total": total})
    except: pass
    return jsonify({"status": "error", "promedio": 0.0, "total": 0})

@app.route('/calcular_ruta', methods=['POST'])
def calcular_ruta():
    data = request.json
    try:
        raw_lat_o, raw_lon_o = data['origen']['lat'], data['origen']['lng']
        raw_lat_d, raw_lon_d = data['destino']['lat'], data['destino']['lng']
        modo = data.get('modo', 'Auto') 
        dir_o = data.get('direccion_origen', f"{raw_lat_o:.4f}, {raw_lon_o:.4f}")
        dir_d = data.get('direccion_destino', f"{raw_lat_d:.4f}, {raw_lon_d:.4f}")

        if modo == 'A pie': modo_google, vel = 'walking', 5.0
        elif modo == 'Moto': modo_google, vel = 'driving', 30.0
        else: modo_google, vel = 'driving', 40.0

        def registrar_historial(t_min, d_km, polyline_str, snap_lat_o, snap_lon_o, snap_lat_d, snap_lon_d):
            fecha_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                conx = conectar_bd()
                if conx:
                    cur = conx.cursor()
                    cur.execute("""
                        INSERT INTO historial_viajes (origen_nombre, destino_nombre, origen_lat, origen_lon,
                                                      destino_lat, destino_lon, modo, tiempo_minutos,
                                                      distancia_km, polyline, fecha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (dir_o, dir_d, snap_lat_o, snap_lon_o, snap_lat_d, snap_lon_d, modo, t_min, d_km, polyline_str, fecha_local))
                    conx.commit(); cur.close(); conx.close()
            except Exception as e: print(f"Error guardando SQL: {e}")

            nuevo_registro = {
                "id": len(historial_busquedas) + 1, "origen_nombre": dir_o, "destino_nombre": dir_d,
                "origen_lat": float(snap_lat_o), "origen_lon": float(snap_lon_o),
                "destino_lat": float(snap_lat_d), "destino_lon": float(snap_lon_d),
                "modo": modo, "tiempo_minutos": int(t_min), "distancia_km": float(d_km),
                "polyline": polyline_str, "fecha": datetime.now().strftime("%Y-%m-%d %I:%M %p")
            }
            historial_busquedas.insert(0, nuevo_registro)
            guardar_historial()

        conexion = conectar_bd()
        if conexion:
            try:
                # CANDADO ESTRICTO DE 10 MINUTOS
                limite_inferior = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
                limite_superior = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor = conexion.cursor()
                cursor.execute("""
                    SELECT * FROM cache_rutas 
                    WHERE modo = ? 
                    AND ABS(origen_lat - ?) < 0.002 AND ABS(origen_lon - ?) < 0.002
                    AND ABS(destino_lat - ?) < 0.002 AND ABS(destino_lon - ?) < 0.002
                    AND fecha_consulta >= ? AND fecha_consulta <= ?
                    ORDER BY id DESC LIMIT 1
                """, (modo, raw_lat_o, raw_lon_o, raw_lat_d, raw_lon_d, limite_inferior, limite_superior))
                cache_result = cursor.fetchone()
                
                if cache_result and cache_result['ruta_json']:
                    segs = json.loads(cache_result['segmentos_json']) if cache_result['segmentos_json'] else []
                    dist_km = round(cache_result['distancia_metros']/1000, 2)
                    
                    # Extraer los puntos snapped exactos de la caché
                    ruta_puntos = json.loads(cache_result['ruta_json'])
                    if ruta_puntos and len(ruta_puntos) > 0:
                        snap_lat_o, snap_lon_o = ruta_puntos[0][0], ruta_puntos[0][1]
                        snap_lat_d, snap_lon_d = ruta_puntos[-1][0], ruta_puntos[-1][1]
                    else:
                        snap_lat_o, snap_lon_o = float(cache_result['origen_lat']), float(cache_result['origen_lon'])
                        snap_lat_d, snap_lon_d = float(cache_result['destino_lat']), float(cache_result['destino_lon'])

                    registrar_historial(cache_result['tiempo_segundos'], dist_km, cache_result['polyline'] or '', snap_lat_o, snap_lon_o, snap_lat_d, snap_lon_d)
                    cursor.close(); conexion.close()
                    return jsonify({
                        "status": "success", "ruta": ruta_puntos, 
                        "tiempo": cache_result['tiempo_segundos'], "distancia": dist_km,
                        "velocidad": vel, "segmentos": segs, "explicacion": "Ruta cargada gratis desde Caché Local.",
                        "snapped_origen": [snap_lat_o, snap_lon_o], 
                        "snapped_destino": [snap_lat_d, snap_lon_d]
                    })
                cursor.close(); conexion.close()
            except Exception as e: print(f"Error caché local: {e}")

        # SI PASARON 10 MINUTOS, LLAMA A LA API OBLIGATORIAMENTE
        resultado_google = consultar_google_directions_api(raw_lat_o, raw_lon_o, raw_lat_d, raw_lon_d, modo_google)
        segmentos_finales, polyline_historial = [], ""
        fecha_local_cache = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if resultado_google and len(resultado_google['puntos_ruta']) > 0:
            dist_m = resultado_google['distancia_m']
            tiempo = max(1, int(resultado_google['tiempo_min'] * 0.75)) if modo == 'Moto' else resultado_google['tiempo_min']
            ruta = resultado_google['puntos_ruta']
            segmentos_finales = resultado_google.get('segmentos', [])
            polyline_historial = resultado_google.get('overview_polyline', '') or ""
            snap_lat_o, snap_lon_o = resultado_google['snapped_o']
            snap_lat_d, snap_lon_d = resultado_google['snapped_d']
            explicacion = "Ruta óptima calculada (Ajustada Moto)." if modo == 'Moto' else "Ruta óptima en tiempo real (Google API)."

            conexion = conectar_bd()
            if conexion:
                try:
                    cursor = conexion.cursor()
                    cursor.execute("""
                        INSERT INTO cache_rutas (origen_lat, origen_lon, destino_lat, destino_lon, tiempo_segundos, distancia_metros, modo, ruta_json, segmentos_json, polyline, fecha_consulta)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (raw_lat_o, raw_lon_o, raw_lat_d, raw_lon_d, tiempo, dist_m, modo, json.dumps(ruta), json.dumps(segmentos_finales), polyline_historial, fecha_local_cache))
                    conexion.commit(); cursor.close(); conexion.close()
                except Exception as e: print(f"Error guardando caché: {e}")

        else:
            if motor_alg and G_busqueda:
                nodo_origen = nearest_node_por_coordenadas(G_busqueda, raw_lat_o, raw_lon_o)
                nodo_destino = nearest_node_por_coordenadas(G_busqueda, raw_lat_d, raw_lon_d)
                ruta_nodos = motor_alg.calcular_ruta_mas_corta(nodo_origen, nodo_destino)
                if ruta_nodos:
                    ruta = [[G_busqueda.nodes[n]['y'], G_busqueda.nodes[n]['x']] for n in ruta_nodos]
                    
                    # REPARACIÓN: Unir exactamente el punto clicado con el primer y último nodo del grafo
                    if [raw_lat_o, raw_lon_o] != ruta[0]:
                        ruta.insert(0, [raw_lat_o, raw_lon_o])
                    if [raw_lat_d, raw_lon_d] != ruta[-1]:
                        ruta.append([raw_lat_d, raw_lon_d])

                    snap_lat_o, snap_lon_o = ruta[0][0], ruta[0][1]
                    snap_lat_d, snap_lon_d = ruta[-1][0], ruta[-1][1]
                    dist_m = int(haversine(snap_lat_o, snap_lon_o, snap_lat_d, snap_lon_d) * 1.3)
                    tiempo = max(1, round(((dist_m / 1000) / vel) * 60))
                    explicacion = "Ruta local calculada con Algoritmo Dijkstra."
                else: raise Exception("No ruta Google ni Dijkstra.")
            else: raise Exception("Error de Google y mapa local no disponible.")
            
            try:
                conexion = conectar_bd()
                if conexion:
                    cursor = conexion.cursor()
                    cursor.execute("""
                        INSERT INTO cache_rutas (origen_lat, origen_lon, destino_lat, destino_lon, tiempo_segundos, distancia_metros, modo, ruta_json, segmentos_json, polyline, fecha_consulta)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (raw_lat_o, raw_lon_o, raw_lat_d, raw_lon_d, tiempo, dist_m, modo, json.dumps(ruta), json.dumps(segmentos_finales), "", fecha_local_cache))
                    conexion.commit(); cursor.close(); conexion.close()
            except: pass

        dist_km = round(dist_m / 1000, 2)
        registrar_historial(tiempo, dist_km, polyline_historial, snap_lat_o, snap_lon_o, snap_lat_d, snap_lon_d)

        return jsonify({
            "status": "success", "ruta": ruta, "tiempo": tiempo, "distancia": dist_km,
            "velocidad": vel, "segmentos": segmentos_finales, "explicacion": explicacion,
            "snapped_origen": [snap_lat_o, snap_lon_o], "snapped_destino": [snap_lat_d, snap_lon_d]
        })
    except Exception as e: return jsonify({"status": "error", "mensaje": str(e)})

@app.route('/comparar_dijkstra', methods=['POST'])
def comparar_dijkstra():
    data = request.json
    try:
        raw_lat_o, raw_lon_o = data['origen']['lat'], data['origen']['lng']
        raw_lat_d, raw_lon_d = data['destino']['lat'], data['destino']['lng']
        if not motor_alg or not G_busqueda:
            return jsonify({"status": "error", "mensaje": "Grafo no inicializado."})
            
        nodo_origen = nearest_node_por_coordenadas(G_busqueda, raw_lat_o, raw_lon_o)
        nodo_destino = nearest_node_por_coordenadas(G_busqueda, raw_lat_d, raw_lon_d)
        ruta_nodos, dist_m = motor_alg.calcular_ruta_con_trafico(nodo_origen, nodo_destino)
        
        if ruta_nodos:
            ruta_coordenadas = [[G_busqueda.nodes[n]['y'], G_busqueda.nodes[n]['x']] for n in ruta_nodos]
            
            # REPARACIÓN: Unir exactamente el punto clicado con el primer y último nodo del grafo
            if [raw_lat_o, raw_lon_o] != ruta_coordenadas[0]:
                ruta_coordenadas.insert(0, [raw_lat_o, raw_lon_o])
            if [raw_lat_d, raw_lon_d] != ruta_coordenadas[-1]:
                ruta_coordenadas.append([raw_lat_d, raw_lon_d])

            import random
            vel_simulada = random.uniform(18.0, 32.0)
            tiempo_min = max(1, round(((dist_m / 1000) / vel_simulada) * 60))
            dist_km = round(dist_m / 1000, 2)
            
            return jsonify({
                "status": "success", "ruta": ruta_coordenadas, "tiempo": tiempo_min, "distancia": dist_km,
                "explicacion": f"Dijkstra Local con penalizaciones aleatorias. Vel media: {round(vel_simulada, 1)} km/h."
            })
        else: return jsonify({"status": "error", "mensaje": "No se encontró conexión vial."})
    except Exception as e: return jsonify({"status": "error", "mensaje": str(e)})

@app.route('/historial', methods=['GET'])
def historial():
    try:
        conexion = conectar_bd()
        if conexion:
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT id, origen_nombre, destino_nombre, origen_lat, origen_lon, 
                       destino_lat, destino_lon, modo, tiempo_minutos, distancia_km, 
                       polyline, fecha
                FROM historial_viajes ORDER BY fecha DESC LIMIT 50
            """)
            viajes = [dict(row) for row in cursor.fetchall()]
            cursor.close(); conexion.close()
            
            for v in viajes:
                try:
                    dt = datetime.strptime(v['fecha'], "%Y-%m-%d %H:%M:%S")
                    v['fecha'] = dt.strftime("%Y-%m-%d %I:%M %p")
                except: pass
                
            return jsonify(viajes)
    except: pass
    return jsonify(historial_busquedas)

@app.route('/historial/eliminar/<int:viaje_id>', methods=['DELETE'])
def eliminar_viaje(viaje_id):
    eliminado_db = False
    try:
        conexion = conectar_bd()
        if conexion:
            cursor = conexion.cursor()
            cursor.execute("DELETE FROM historial_viajes WHERE id = ?", (viaje_id,))
            conexion.commit()
            if cursor.rowcount > 0: eliminado_db = True
            cursor.close(); conexion.close()
    except Exception: pass
        
    global historial_busquedas
    original_len = len(historial_busquedas)
    historial_busquedas = [v for v in historial_busquedas if v.get('id') != viaje_id]
    if len(historial_busquedas) < original_len:
        guardar_historial()
        return jsonify({"status": "success", "mensaje": "Eliminado localmente."})
        
    if eliminado_db: return jsonify({"status": "success", "mensaje": "Viaje eliminado."})
    return jsonify({"status": "error", "mensaje": "No encontrado."})

@app.route('/eventos', methods=['GET'])
def eventos(): 
    return jsonify(cargar_eventos_csv())

crear_tablas()
purgar_fechas_futuras() 
if __name__ == '__main__':
    Thread(target=recuperar_polylines_en_segundo_plano, daemon=True).start()
    Timer(1.5, open_browser).start()
    app.run(port=5050, debug=True, use_reloader=False)