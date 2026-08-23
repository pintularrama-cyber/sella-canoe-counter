import os
import re
import csv
import math
import time
import cv2
import torch
import requests
import threading
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from collections import defaultdict
from playwright.sync_api import sync_playwright
from ultralytics import YOLO

CAMERA_ID = "k52QeyES"
CSV_FILE = "canoas_sella.csv"

# URL pública de tu servicio en Render (cámbiala si tu nombre es distinto)
API_WEB_URL = "https://sella-canoe-counter.onrender.com/api/canoa"

# -------------------------------------------------------------
# 1. ENVÍO EN SEGUNDO PLANO A LA WEB (RENDER)
# -------------------------------------------------------------
def enviar_canoa_a_la_web(canoe_id, timestamp_str):
    """Envía la canoa a Render en un hilo secundario para no frenar la IA"""
    def _enviar():
        try:
            requests.post(API_WEB_URL, json={"canoe_id": canoe_id, "timestamp": timestamp_str}, timeout=2)
        except Exception:
            pass
    threading.Thread(target=_enviar, daemon=True).start()

# -------------------------------------------------------------
# 2. SISMÓGRAFO EN EL CIELO (TRANSPARENTE + LÍNEA ROJA)
# -------------------------------------------------------------
def dibujar_sismografo_cielo(img, canoe_timestamps, x, y, w, h):
    """Dibuja el sismógrafo transparente sobre las nubes con línea roja y eje temporal"""
    now = datetime.now()

    # 48 bloques de 5 minutos = 240 minutos (4 Horas)
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

    # Eje horizontal
    cv2.line(img, (x + margen_x, linea_base_y), (x + w - margen_x, linea_base_y), (220, 220, 220), 1, cv2.LINE_AA)

    # Marcas del Eje X (-4h a 0)
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

    # Sombra roja suave
    poly_pts = np.array([(x + margen_x, linea_base_y)] + puntos + [(x + w - margen_x, linea_base_y)], dtype=np.int32)
    overlay = img.copy()
    cv2.fillPoly(overlay, [poly_pts], (0, 0, 180))
    cv2.addWeighted(overlay, 0.25, img, 0.75, 0, img)

    # Línea del sismógrafo
    for i in range(len(puntos) - 1):
        cv2.line(img, puntos[i], puntos[i + 1], (0, 0, 255), 2, cv2.LINE_AA)

    # Punto pulsante actual
    ultimo_pt = puntos[-1]
    cv2.circle(img, ultimo_pt, 4, (0, 0, 255), -1, cv2.LINE_AA)
    cv2.circle(img, ultimo_pt, 7, (255, 255, 255), 1, cv2.LINE_AA)

# -------------------------------------------------------------
# 3. GRÁFICA FINAL DE LA SESIÓN AL SALIR
# -------------------------------------------------------------
def generar_grafica_5min(csv_path, session_start):
    if not os.path.exists(csv_path):
        return

    intervalos_detectados = defaultdict(int)
    total_detectado = 0

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not row:
                continue
            dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if dt < session_start:
                continue

            bloque_min = (dt.minute // 5) * 5
            fin_min = bloque_min + 4
            etiqueta = f"{dt.hour:02d}:{bloque_min:02d}-{dt.hour:02d}:{fin_min:02d}"
            intervalos_detectados[etiqueta] += 1
            total_detectado += 1

    if not intervalos_detectados or total_detectado == 0:
        print(f"\nℹ️ No se registraron canoas durante esta sesión.")
        return

    tramos = sorted(intervalos_detectados.keys())
    conteos = [intervalos_detectados[t] for t in tramos]
    max_canoas = max(conteos)
    tramo_punta = tramos[conteos.index(max_canoas)]
    media_5m = total_detectado / len(tramos)

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(15, 7.5), facecolor='#0f172a')
    ax.set_facecolor('#0f172a')

    colores = ['#f97316' if c == max_canoas else '#0ea5e9' for c in conteos]
    barras = ax.bar(tramos, conteos, width=0.65, color=colores, alpha=0.9, zorder=3)
    ax.plot(tramos, conteos, color='#ffffff', linewidth=2, linestyle='--', alpha=0.4, marker='o', markersize=4, zorder=4)

    for barra in barras:
        altura = barra.get_height()
        if altura > 0:
            ax.annotate(f'{int(altura)}', xy=(barra.get_x() + barra.get_width() / 2, altura),
                        xytext=(0, 4), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9, fontweight='bold', color='#ffffff')

    fecha_sesion = session_start.strftime('%d/%m/%Y')
    plt.title(f"DESCENSO DEL SELLA — INFORME OFICIAL ({fecha_sesion})", fontsize=14, fontweight='bold', color='#f8fafc', pad=22)
    subtitulo = f"Total Contadas: {total_detectado} canoas  |  Hora Punta: {tramo_punta} ({max_canoas} canoas/5min)  |  Media: {media_5m:.1f} canoas/5min"
    ax.text(0.5, 1.02, subtitulo, transform=ax.transAxes, ha='center', fontsize=11, color='#38bdf8', fontweight='semibold')

    ax.set_ylabel("Número de Canoas", fontsize=11, fontweight='bold', color='#94a3b8', labelpad=10)
    ax.set_xticks(range(len(tramos)))
    ax.set_xticklabels(tramos, rotation=45, ha='right', fontsize=9, color='#94a3b8')
    ax.tick_params(colors='#94a3b8')
    ax.grid(axis='y', linestyle=':', color='#334155', alpha=0.7, zorder=0)
    for spine in ['top', 'right', 'left', 'bottom']:
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    nombre_archivo = f"informe_sella_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(nombre_archivo, dpi=200, facecolor=fig.get_facecolor())
    print(f"\n📊 ¡Informe oficial guardado como '{nombre_archivo}'!")
    plt.show()

# -------------------------------------------------------------
# 4. INTERCEPTOR PLAYWRIGHT
# -------------------------------------------------------------
def get_authenticated_stream_url(camera_id):
    embed_url = f"https://rtsp.me/embed/{camera_id}/"
    captured_url = None

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
# 5. TRACKER CHECKPOINT
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
# COORDENADAS EXACTAS
# -------------------------------------------------------------
MAIN_X1 = 0.04
MAIN_X2 = 0.96
MAIN_Y1 = 0.15
MAIN_Y2 = 0.99

# Checkpoint ajustado para evitar el saliente de la derecha
RIVER_X1 = 0.35   
RIVER_X2 = 0.56
RIVER_Y1 = 0.81
RIVER_Y2 = 0.99

MIN_CANOE_AREA = 1000

def main():
    session_start = datetime.now()
    fecha_hoy_str = session_start.strftime("%d/%m/%Y")
    start_time_str = session_start.strftime("%H:%M:%S")

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"🚀 Canoe Counter Arriondas [GPU: {device.upper()}] — Modo Continuo 24/7")

    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Canoa_ID"])

    print("🤖 Conectando señal de Arriondas...")
    stream_url = get_authenticated_stream_url(CAMERA_ID)
    if not stream_url:
        print("❌ Error al obtener señal inicial.")
        return

    model = YOLO("yolov8s.pt")
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        return

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
    canoe_timestamps = []

    print(f"🟢 SESIÓN INICIADA [{start_time_str}]. Pulsa 'q' para salir.")

    while True:
        ret, frame = cap.read()

        # -------------------------------------------------------------
        # AUTO-RECUPERACIÓN BLINDADA ANTE CORTES DE RED / STREAM
        # -------------------------------------------------------------
        if not ret:
            print("⚠️ Corte en la emisión del Sella. Reintentando conexión...")
            cap.release()
            
            reconectado = False
            while not reconectado:
                time.sleep(5)
                print("🔄 Intentando cazar nueva señal...")
                stream_url = get_authenticated_stream_url(CAMERA_ID)
                if stream_url:
                    cap = cv2.VideoCapture(stream_url)
                    if cap.isOpened():
                        ret_test, _ = cap.read()
                        if ret_test:
                            print("✅ ¡Señal del Sella restablecida!")
                            reconectado = True
            continue

        roi_river = frame[ry1:ry2, rx1:rx2].copy()
        now = datetime.now()

        # COMPROBACIÓN DE CAMBIO DE DÍA (REINICIO A MEDIANOCHE)
        if now.strftime("%d/%m/%Y") != fecha_hoy_str:
            fecha_hoy_str = now.strftime("%d/%m/%Y")
            start_time_str = now.strftime("%H:%M:%S")
            total_canoas = 0
            canoe_timestamps.clear()
            tracker.counted.clear()
            print(f"\n🌅 ¡Nuevo día detectado ({fecha_hoy_str})! Contador puesto a 0.")

        results = model.predict(
            source=roi_river,
            classes=[8, 37],    # SOLO embarcaciones
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
                
                # 1. Guardar en CSV local
                with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp_str, obj_id])

                # 2. Enviar a Render
                enviar_canoa_a_la_web(obj_id, timestamp_str)

                print(f"🛶 [{now.strftime('%H:%M:%S')}] ¡Canoa #{obj_id} contada! Total: {total_canoas}")

            color = (0, 255, 0) if obj_id in tracker.counted else (0, 220, 255)
            cv2.rectangle(roi_river, (bx1, by1), (bx2, by2), color, 2)
            cv2.putText(roi_river, f"Canoa #{obj_id}", (bx1, by1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # ---------------------------------------------------------
        # COMPOSICIÓN PANORÁMICA + WIDGETS
        # ---------------------------------------------------------
        display_frame = frame[my1:my2, mx1:mx2].copy()

        # Checkpoint IA (Recuadro Amarillo sobre el río)
        cv2.rectangle(display_frame, (rel_rx1, rel_ry1), (rel_rx2, rel_ry2), (0, 255, 255), 2)
        cv2.putText(display_frame, "CHECKPOINT IA", (rel_rx1 + 8, rel_ry1 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

        # Inset PiP: Zoom Grande
        pip_w = 480
        pip_h = int(pip_w * (crop_h / crop_w))
        roi_resized = cv2.resize(roi_river, (pip_w, pip_h))
        
        pip_x = 20
        pip_y = main_h - pip_h - 20

        display_frame[pip_y:pip_y+pip_h, pip_x:pip_x+pip_w] = roi_resized
        cv2.rectangle(display_frame, (pip_x, pip_y), (pip_x+pip_w, pip_y+pip_h), (0, 255, 0), 2)
        cv2.putText(display_frame, "ZOOM CHECKPOINT IA", (pip_x + 10, pip_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 255, 0), 2)

        # Panel de conteo superior derecho
        panel_w, panel_h = 260, 75
        px1, py1 = main_w - panel_w - 20, 20
        px2, py2 = main_w - 20, py1 + panel_h

        cv2.rectangle(display_frame, (px1, py1), (px2, py2), (18, 15, 15), -1)
        cv2.rectangle(display_frame, (px1, py1), (px2, py2), (55, 55, 55), 1)

        cv2.putText(display_frame, f"CANOAS: {total_canoas}", (px1 + 15, py1 + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.80, (0, 255, 0), 2)
        cv2.putText(display_frame, f"{fecha_hoy_str} | Inicio: {start_time_str}", 
                    (px1 + 15, py1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1)

        # Sismógrafo en el Cielo
        dibujar_sismografo_cielo(display_frame, canoe_timestamps, sky_x, sky_y, sky_w, sky_h)

        # Mostrar escena
        vista_final = cv2.resize(display_frame, (1280, 720))
        cv2.imshow("Canoe Counter - Sella (Arriondas)", vista_final)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    print("\nGenerando análisis gráfico oficial de la sesión...")
    generar_grafica_5min(CSV_FILE, session_start)

if __name__ == "__main__":
    main()