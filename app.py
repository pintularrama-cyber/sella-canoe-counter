import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = "sella.db"

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

# -------------------------------------------------------------
# 2. RUTA PRINCIPAL
# -------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

# -------------------------------------------------------------
# 3. API: RECIBIR CANOA
# -------------------------------------------------------------
@app.route("/api/canoa", methods=["POST"])
def registrar_canoa():
    data = request.get_json(silent=True) or {}
    timestamp_str = data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    canoe_id = data.get("canoe_id", 0)

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO canoas (timestamp, canoe_id) VALUES (?, ?)", (timestamp_str, canoe_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "message": f"Canoa #{canoe_id} registrada"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# -------------------------------------------------------------
# 4. API: ESTADÍSTICAS + SISMÓGRAFO 4 HORAS
# -------------------------------------------------------------
@app.route("/api/stats")
def obtener_estadisticas():
    now = datetime.now()
    hoy_str = now.strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM canoas WHERE timestamp LIKE ? ORDER BY timestamp ASC", (f"{hoy_str}%",))
    rows = cursor.fetchall()
    conn.close()

    total_hoy = len(rows)
    timestamps_hoy = [datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") for r in rows]

    # 1. Agrupación por tramos de 5 min (Gráfica de barras)
    intervalos = defaultdict(int)
    for dt in timestamps_hoy:
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

    # 2. Datos del Sismógrafo (48 bloques de 5 min = 4 Horas)
    num_slots = 48
    minutos_por_slot = 5
    sismografo_conteos = [0] * num_slots
    sismografo_labels = [""] * num_slots

    for i in range(num_slots):
        t_inicio = now - timedelta(minutes=(num_slots - i) * minutos_por_slot)
        t_fin = now - timedelta(minutes=(num_slots - i - 1) * minutos_por_slot)
        sismografo_conteos[i] = sum(1 for t in timestamps_hoy if t_inicio <= t < t_fin)
        
        # Etiquetas guía: -4h, -3h, -2h, -1h, Ahora
        if i == 0:
            sismografo_labels[i] = "-4h"
        elif i == 12:
            sismografo_labels[i] = "-3h"
        elif i == 24:
            sismografo_labels[i] = "-2h"
        elif i == 36:
            sismografo_labels[i] = "-1h"
        elif i == num_slots - 1:
            sismografo_labels[i] = "Ahora"

    return jsonify({
        "total_hoy": total_hoy,
        "hora_punta": hora_punta,
        "tramos": tramos,
        "conteos": conteos,
        "sismografo_labels": sismografo_labels,
        "sismografo_conteos": sismografo_conteos
    })

# -------------------------------------------------------------
# 5. API: REINICIAR CONTADOR (ADMIN / ARRIONDAS)
# -------------------------------------------------------------
@app.route("/api/reset", methods=["POST"])
def reset_counter():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    # NUEVA CONTRASEÑA: arriondas
    if username == "admin" and password == "arriondas":
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM canoas WHERE timestamp LIKE ?", (f"{hoy_str}%",))
        conn.commit()
        conn.close()

        return jsonify({"status": "ok", "message": "Contador reiniciado con éxito"}), 200
    else:
        return jsonify({"status": "error", "message": "Credenciales incorrectas"}), 401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)