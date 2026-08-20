import os
import re
import csv
import math
import cv2
import time
import torch
import sqlite3
import threading
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
from playwright.sync_api import sync_playwright
from ultralytics import YOLO
from flask import Flask, render_template, Response, request, jsonify

app = Flask(__name__)
DB_NAME = "sella.db"
CAMERA_ID = "k52QeyES"

# Variables globales compartidas
global_frame_bytes = None
reset_requested = False
lock = threading.Lock()

# -------------------------------------------------------------
# 1. BASE DE DATOS SQLITE
# -------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS canoas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            canoe_id INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

def guardar_canoa_en_db(canoe_id, timestamp_str):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO canoas (timestamp, canoe_id) VALUES (?, ?)", (timestamp_str, canoe_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error al guardar en DB: {e}")

# -------------------------------------------------------------
# 2. SISMÓGRAFO EN EL CIELO (TRANSPARENTE + ROJO)
# -------------------------------------------------------------
def dibujar_sismografo_cielo(img, canoe_timestamps, x, y, w, h):
    now = datetime.now()
    num_slots = 48
    minutos_por_slot = 5
    conteos = [0] * num_slots
    
    for i in range(num_slots):
        t_inicio = now - timedelta(minutes=(num_slots - i) * minutos_por_slot)
        t_fin = now - timedelta(minutes=(num_slots - i - 1) * minutos_por_slot)
        conteos[i] = sum(1 for t in canoe_timestamps if t_inicio <= t < t_fin)

    max_val = max(max(conteos), 4)

    margen_x = 10
    margen_y_top = 15
    margen_y_bot = 22
    area_h = h - margen_y_top - margen_y_bot
    area_w = w - (margen_x * 2)

    puntos = []
    for idx, valor in enumerate(conteos):
        px = int(x + margen_x + (idx / (num_slots - 1)) * area_w)
        py = int((y + h - margen_y_bot) - (valor / max_val) * area_h)
        puntos.append((px, py))

    linea_base_y = y + h - margen_y_bot
    cv2.line(img, (x + margen_x, linea_base_y), (x + w - margen_x, linea_base_y), (220, 220, 220), 1, cv2.LINE_AA)

    etiquetas_eje = ["-4h", "-3h", "-2h", "-1h", "0 (Ahora)"]
    num_marcas = len(etiquetas_eje)
    for i, texto in enumerate(etiquetas_eje):
        pos_x = int(x + margen_x + (i / (num_marcas - 1)) * area_w)
        cv2.line(img, (pos_x, linea_base_y), (pos_x, linea_base_y + 4), (220, 220, 220), 1, cv2.LINE_AA)
        offset_txt_x = 10 if i < num_marcas - 1 else 28
        cv2.putText(img, texto, (pos_x - offset_txt_x, linea_base_y + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(img, texto, (pos_x - offset_txt_x, linea_base_y + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

    poly_pts = np.array([(x + margen_x, linea_base_y)] + puntos + [(x + w - margen_x, linea_base_y)], dtype=np.int32)
    overlay = img.copy()
    cv2.fillPoly(overlay, [poly_pts], (0, 0, 180))
    cv2.addWeighted(overlay, 0.25, img, 0.75, 0, img)

    for i in range(len(puntos) - 1):
        cv2.line(img, puntos[i], puntos[i + 1], (0, 0, 255), 2, cv2.LINE_AA)

    ultimo_pt = puntos[-1]
    cv2.circle(img, ultimo_pt, 4, (0, 0, 255), -1, cv2.LINE_AA)
    cv2.circle(img, ultimo_pt, 7, (255, 255, 255), 1, cv2.LINE_AA)

# -------------------------------------------------------------
# 3. INTERCEPTOR PLAYWRIGHT
# -------------------------------------------------------------
def get_authenticated_stream_url(camera_id):
    embed_url = f"https://rtsp.me/embed/{camera_id}/"
    captured_url = None
    print("🤖 Conectando señal de Arriondas...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox", "--disable-web-security"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        def handle_request(request):
            nonlocal captured_url
            url = request.url
            if (".m4s" in url or ".m3u8" in url) and not captured_url:
                if ".m4s" in url:
                    captured_url = re.sub(r'-20[0-9]{6}-[0-9]+\.m4s', '.m3u8', url)
                else:
                    captured_url = url

        page.on("request", handle_request)

        try:
            page.goto(embed_url, timeout=15000)
            page.mouse.click(320, 240)
            for _ in range(12):
                if captured_url:
                    break
                page.wait_for_timeout(500)
        except Exception:
            pass
        finally:
            browser.close()

    return captured_url

# =====================================================================
# 4. TRACKER CHECKPOINT
# =====================================================================
class RiverTracker:
    def __init__(self, max_distance=90, max_disappeared=30, min_hits=3):
        self.next_id = 1
        self.objects = {}           
        self.birth_pos = {}         
        self.disappeared = {}       
        self.hits = {}              
        self.counted = set()        
        self.max_distance = max_distance
        self.max_disappeared = max_disappeared
        self.min_hits = min_hits

    def update(self, rects):
        if len(rects) == 0:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self._deregister(obj_id)
            return []

        input_centroids = []
        for (x1, y1, x2, y2) in rects:
            cx = int((x1 + x2) / 2.0)
            cy = int((y1 + y2) / 2.0)
            input_centroids.append((cx, cy, (x1, y1, x2, y2)))

        if len(self.objects) == 0:
            tracked_results = []
            for (cx, cy, box) in input_centroids:
                obj_id = self._register(cx, cy)
                tracked_results.append((obj_id, box, cx, cy))
            return tracked_results

        object_ids = list(self.objects.keys())
        object_centroids = list(self.objects.values())

        tracked_results = []
        used_inputs = set()
        used_objects = set()

        for obj_idx, obj_id in enumerate(object_ids):
            ox, oy = object_centroids[obj_idx]
            best_dist = float("inf")
            best_input_idx = -1

            for in_idx, (cx, cy, box) in enumerate(input_centroids):
                if in_idx in used_inputs:
                    continue
                dist = math.hypot(cx - ox, cy - oy)
                if dist < best_dist and dist < self.max_distance:
                    best_dist = dist
                    best_input_idx = in_idx

            if best_input_idx != -1:
                cx, cy, box = input_centroids[best_input_idx]
                self.objects[obj_id] = (cx, cy)
                self.disappeared[obj_id] = 0
                self.hits[obj_id] += 1
                used_inputs.add(best_input_idx)
                used_objects.add(obj_id)
                tracked_results.append((obj_id, box, cx, cy))

        for obj_id in object_ids:
            if obj_id not in used_objects:
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self._deregister(obj_id)

        for in_idx, (cx, cy, box) in enumerate(input_centroids):
            if in_idx not in used_inputs:
                new_id = self._register(cx, cy)
                tracked_results.append((new_id, box, cx, cy))

        return tracked_results

    def _register(self, cx, cy):
        new_id = self.next_id
        self.objects[new_id] = (cx, cy)
        self.birth_pos[new_id] = (cx, cy)
        self.disappeared[new_id] = 0
        self.hits[new_id] = 1
        self.next_id += 1
        return new_id

    def _deregister(self, obj_id):
        del self.objects[obj_id]
        del self.disappeared[obj_id]
        if obj_id in self.birth_pos:
            del self.birth_pos[obj_id]
        if obj_id in self.hits:
            del self.hits[obj_id]

# -------------------------------------------------------------
# 5. MOTOR DE VISIÓN IA EN SEGUNDO PLANO
# -------------------------------------------------------------
MAIN_X1, MAIN_X2 = 0.04, 0.96
MAIN_Y1, MAIN_Y2 = 0.15, 0.99
RIVER_X1, RIVER_X2 = 0.38, 0.63
RIVER_Y1, RIVER_Y2 = 0.81, 0.99
MIN_CANOE_AREA = 1000

def video_ai_worker():
    global global_frame_bytes, reset_requested
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"🚀 Iniciando Motor de IA [GPU: {device.upper()}]")

    stream_url = get_authenticated_stream_url(CAMERA_ID)
    if not stream_url:
        return

    model = YOLO("yolov8s.pt")
    cap = cv2.VideoCapture(stream_url)

    ret, test_frame = cap.read()
    if not ret:
        return

    orig_h, orig_w, _ = test_frame.shape

    my1, my2 = int(orig_h * MAIN_Y1), int(orig_h * MAIN_Y2)
    mx1, mx2 = int(orig_w * MAIN_X1), int(orig_w * MAIN_X2)
    main_h, main_w = my2 - my1, mx2 - mx1

    ry1, ry2 = int(orig_h * RIVER_Y1), int(orig_h * RIVER_Y2)
    rx1, rx2 = int(orig_w * RIVER_X1), int(orig_w * RIVER_X2)
    crop_h, crop_w = ry2 - ry1, rx2 - rx1

    rel_rx1 = rx1 - mx1
    rel_ry1 = ry1 - my1
    rel_rx2 = rx2 - mx1
    rel_ry2 = ry2 - my1

    sky_x = int(main_w * 0.12)
    sky_y = int(main_h * 0.03)
    sky_w = int(main_w * 0.38)
    sky_h = int(main_h * 0.16)

    tracker = RiverTracker(max_distance=90, max_disappeared=30, min_hits=3)
    
    total_canoas = 0
    fecha_hoy_str = datetime.now().strftime("%d/%m/%Y")
    start_time_str = datetime.now().strftime("%H:%M:%S")
    canoe_timestamps = []

    print("🟢 Motor de Visión transmitiendo a la web...")

    while True:
        # ATENDER PETICIÓN DE REINICIO DESDE LA WEB
        if reset_requested:
            total_canoas = 0
            canoe_timestamps.clear()
            tracker.counted.clear()
            start_time_str = datetime.now().strftime("%H:%M:%S")
            reset_requested = False
            print("🔄 ¡Contador de visión reseteado a 0!")

        ret, frame = cap.read()
        if not ret:
            print("⚠️ Reconectando señal...")
            stream_url = get_authenticated_stream_url(CAMERA_ID)
            if stream_url:
                cap = cv2.VideoCapture(stream_url)
                continue
            else:
                time.sleep(2)
                continue

        roi_river = frame[ry1:ry2, rx1:rx2].copy()
        now = datetime.now()

        results = model.predict(
            source=roi_river,
            classes=[8, 37],
            conf=0.15,
            imgsz=640,
            device=device,
            verbose=False
        )[0]

        raw_boxes = results.boxes.xyxy.cpu().numpy()
        confidences = results.boxes.conf.cpu().numpy()
        
        nms_boxes = []
        nms_scores = []
        for box, conf in zip(raw_boxes, confidences):
            bx1, by1, bx2, by2 = box
            area = (bx2 - bx1) * (by2 - by1)
            if area > MIN_CANOE_AREA:
                nms_boxes.append([int(bx1), int(by1), int(bx2 - bx1), int(by2 - by1)])
                nms_scores.append(float(conf))

        valid_boxes = []
        if len(nms_boxes) > 0:
            indices = cv2.dnn.NMSBoxes(nms_boxes, nms_scores, score_threshold=0.15, nms_threshold=0.30)
            if len(indices) > 0:
                for i in indices.flatten():
                    x, y, w, h = nms_boxes[i]
                    valid_boxes.append([x, y, x + w, y + h])

        tracked_objects = tracker.update(valid_boxes)

        for obj_id, (bx1, by1, bx2, by2), cx, cy in tracked_objects:
            confirmada = tracker.hits.get(obj_id, 0) >= tracker.min_hits

            if confirmada and (obj_id not in tracker.counted):
                tracker.counted.add(obj_id)
                total_canoas += 1
                canoe_timestamps.append(now)
                timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
                guardar_canoa_en_db(obj_id, timestamp_str)
                print(f"🛶 [{now.strftime('%H:%M:%S')}] ¡Canoa #{obj_id} contada! Total: {total_canoas}")

            color = (0, 255, 0) if obj_id in tracker.counted else (0, 220, 255)
            cv2.rectangle(roi_river, (bx1, by1), (bx2, by2), color, 2)
            cv2.putText(roi_river, f"Canoa #{obj_id}", (bx1, by1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # Composición Panorámica
        display_frame = frame[my1:my2, mx1:mx2].copy()

        cv2.rectangle(display_frame, (rel_rx1, rel_ry1), (rel_rx2, rel_ry2), (0, 255, 255), 2)
        cv2.putText(display_frame, "CHECKPOINT IA", (rel_rx1 + 8, rel_ry1 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

        pip_w = 480
        pip_h = int(pip_w * (crop_h / crop_w))
        roi_resized = cv2.resize(roi_river, (pip_w, pip_h))
        pip_x = 20
        pip_y = main_h - pip_h - 20

        display_frame[pip_y:pip_y+pip_h, pip_x:pip_x+pip_w] = roi_resized
        cv2.rectangle(display_frame, (pip_x, pip_y), (pip_x+pip_w, pip_y+pip_h), (0, 255, 0), 2)
        cv2.putText(display_frame, "ZOOM CHECKPOINT IA", (pip_x + 10, pip_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 255, 0), 2)

        panel_w, panel_h = 260, 75
        px1, py1 = main_w - panel_w - 20, 20
        px2, py2 = main_w - 20, py1 + panel_h

        cv2.rectangle(display_frame, (px1, py1), (px2, py2), (18, 15, 15), -1)
        cv2.rectangle(display_frame, (px1, py1), (px2, py2), (55, 55, 55), 1)

        cv2.putText(display_frame, f"CANOAS: {total_canoas}", (px1 + 15, py1 + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.80, (0, 255, 0), 2)
        cv2.putText(display_frame, f"{fecha_hoy_str} | Inicio: {start_time_str}", 
                    (px1 + 15, py1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1)

        dibujar_sismografo_cielo(display_frame, canoe_timestamps, sky_x, sky_y, sky_w, sky_h)

        _, buffer = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with lock:
            global_frame_bytes = buffer.tobytes()

threading.Thread(target=video_ai_worker, daemon=True).start()

# -------------------------------------------------------------
# 6. RUTAS DE FLASK
# -------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

def generate_video_stream():
    global global_frame_bytes
    while True:
        with lock:
            if global_frame_bytes is None:
                time.sleep(0.05)
                continue
            frame = global_frame_bytes

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.04)

@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/stats")
def obtener_estadisticas():
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM canoas WHERE timestamp LIKE ? ORDER BY timestamp ASC", (f"{hoy_str}%",))
    rows = cursor.fetchall()
    conn.close()

    total_hoy = len(rows)
    intervalos = defaultdict(int)

    for row in rows:
        dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        bloque_min = (dt.minute // 5) * 5
        fin_min = bloque_min + 4
        etiqueta = f"{dt.hour:02d}:{bloque_min:02d}-{dt.hour:02d}:{fin_min:02d}"
        intervalos[etiqueta] += 1

    tramos = sorted(intervalos.keys())
    conteos = [intervalos[t] for t in tramos]

    hora_punta = "Sin datos"
    if conteos:
        max_canoas = max(conteos)
        hora_punta = f"{tramos[conteos.index(max_canoas)]} ({max_canoas} canoas)"

    return jsonify({
        "total_hoy": total_hoy,
        "hora_punta": hora_punta,
        "tramos": tramos,
        "conteos": conteos
    })

# -------------------------------------------------------------
# 7. RUTA DE REINICIO SEGURO (ADMIN / ADMIN)
# -------------------------------------------------------------
@app.route("/api/reset", methods=["POST"])
def reset_counter():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if username == "admin" and password == "admin":
        global reset_requested
        reset_requested = True

        # Borrar registros de hoy en SQLite
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM canoas WHERE timestamp LIKE ?", (f"{hoy_str}%",))
        conn.commit()
        conn.close()

        return jsonify({"status": "ok", "message": "Contador reiniciado con éxito"}), 200
    else:
        return jsonify({"status": "error", "message": "Credenciales de administrador incorrectas"}), 401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)