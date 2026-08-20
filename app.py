import sqlite3
from datetime import datetime
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
# 3. API: RECIBIR CANOA DESDE TU MAC MINI
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
# 4. API: ESTADÍSTICAS EN TIEMPO REAL (BLOQUES DE 5 MIN)
# -------------------------------------------------------------
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
# 5. API: REINICIAR CONTADOR (ADMIN / ADMIN)
# -------------------------------------------------------------
@app.route("/api/reset", methods=["POST"])
def reset_counter():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if username == "admin" and password == "admin":
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