import os
import re
import math
import psycopg2
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_LOCAL = "sella.db"
ZONA_MADRID = ZoneInfo("Europe/Madrid")

def get_db_connection():
    if DATABASE_URL:
        url = DATABASE_URL.replace("postgres://", "postgresql://")
        return psycopg2.connect(url)
    else:
        return sqlite3.connect(DB_LOCAL)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS canoas (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(30),
                canoe_id INTEGER
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS canoas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                canoe_id INTEGER
            );
        """)
    conn.commit()
    cursor.close()
    conn.close()

init_db()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/canoa", methods=["POST"])
def registrar_canoa():
    data = request.get_json(silent=True) or {}
    timestamp_str = data.get("timestamp", datetime.now(ZONA_MADRID).strftime("%Y-%m-%d %H:%M:%S"))
    canoe_id = data.get("canoe_id", 0)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("INSERT INTO canoas (timestamp, canoe_id) VALUES (%s, %s)", (timestamp_str, canoe_id))
        else:
            cursor.execute("INSERT INTO canoas (timestamp, canoe_id) VALUES (?, ?)", (timestamp_str, canoe_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "ok", "message": f"Canoa #{canoe_id} registrada"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/stats")
def obtener_estadisticas():
    now = datetime.now(ZONA_MADRID)
    hoy_str = now.strftime("%Y-%m-%d")
    mes_str = now.strftime("%Y-%m")
    ano_str = now.strftime("%Y")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. DATOS DE HOY
    query_hoy = "SELECT timestamp FROM canoas WHERE timestamp LIKE %s ORDER BY timestamp ASC" if DATABASE_URL else "SELECT timestamp FROM canoas WHERE timestamp LIKE ? ORDER BY timestamp ASC"
    cursor.execute(query_hoy, (f"{hoy_str}%",))
    rows_hoy = cursor.fetchall()
    total_hoy = len(rows_hoy)
    timestamps_hoy = []
    for r in rows_hoy:
        try:
            timestamps_hoy.append(datetime.strptime(str(r[0]), "%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass

    # Distribución 5 min de hoy
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
        max_c = max(conteos)
        hora_punta = f"{tramos[conteos.index(max_c)]} ({max_c} canoas)"

    # Sismógrafo 4H
    num_slots = 48
    minutos_por_slot = 5
    sismografo_conteos = [0] * num_slots
    sismografo_labels = [""] * num_slots
    ref_time = timestamps_hoy[-1] if timestamps_hoy else now

    for i in range(num_slots):
        t_inicio = ref_time - timedelta(minutes=(num_slots - i) * minutos_por_slot)
        t_fin = ref_time - timedelta(minutes=(num_slots - i - 1) * minutos_por_slot)
        sismografo_conteos[i] = sum(1 for t in timestamps_hoy if t_inicio <= t < t_fin)

        if i == 0: sismografo_labels[i] = "-4h"
        elif i == 12: sismografo_labels[i] = "-3h"
        elif i == 24: sismografo_labels[i] = "-2h"
        elif i == 36: sismografo_labels[i] = "-1h"
        elif i == num_slots - 1: sismografo_labels[i] = "Ahora"

    # 2. ACUMULADOS MES Y AÑO
    query_mes = "SELECT COUNT(*) FROM canoas WHERE timestamp LIKE %s" if DATABASE_URL else "SELECT COUNT(*) FROM canoas WHERE timestamp LIKE ?"
    cursor.execute(query_mes, (f"{mes_str}%",))
    total_mes = cursor.fetchone()[0]

    query_ano = "SELECT COUNT(*) FROM canoas WHERE timestamp LIKE %s" if DATABASE_URL else "SELECT COUNT(*) FROM canoas WHERE timestamp LIKE ?"
    cursor.execute(query_ano, (f"{ano_str}%",))
    total_ano = cursor.fetchone()[0]

    # 3. HISTÓRICO: TODOS LOS DÍAS
    cursor.execute("""
        SELECT substr(timestamp, 1, 10) as dia, COUNT(*) as total 
        FROM canoas 
        GROUP BY dia 
        ORDER BY dia ASC
    """)
    rows_dias = cursor.fetchall()

    # 4. HISTÓRICO: AGRUPADO POR MESES (YYYY-MM)
    cursor.execute("""
        SELECT substr(timestamp, 1, 7) as mes, COUNT(*) as total 
        FROM canoas 
        GROUP BY mes 
        ORDER BY mes ASC
    """)
    rows_meses = cursor.fetchall()

    # 5. HISTÓRICO: AGRUPADO POR AÑOS (YYYY)
    cursor.execute("""
        SELECT substr(timestamp, 1, 4) as ano, COUNT(*) as total 
        FROM canoas 
        GROUP BY ano 
        ORDER BY ano ASC
    """)
    rows_anos = cursor.fetchall()

    cursor.close()
    conn.close()

    hist_dias = [str(r[0]) for r in rows_dias]
    hist_totales_dias = [int(r[1]) for r in rows_dias]

    hist_meses = [str(r[0]) for r in rows_meses]
    hist_totales_meses = [int(r[1]) for r in rows_meses]

    hist_anos = [str(r[0]) for r in rows_anos]
    hist_totales_anos = [int(r[1]) for r in rows_anos]

    record_dia = "Sin datos"
    if rows_dias:
        dia_max = max(rows_dias, key=lambda x: x[1])
        dt_record = datetime.strptime(str(dia_max[0]), "%Y-%m-%d").strftime("%d/%m/%Y")
        record_dia = f"{dia_max[1]} canoas ({dt_record})"

    return jsonify({
        # Hoy
        "total_hoy": total_hoy,
        "hora_punta": hora_punta,
        "tramos": tramos,
        "conteos": conteos,
        "sismografo_labels": sismografo_labels,
        "sismografo_conteos": sismografo_conteos,
        # Tarjetas Récords
        "record_dia": record_dia,
        "total_mes": total_mes,
        "total_ano": total_ano,
        # Gráficas Históricas
        "hist_dias": hist_dias,
        "hist_totales_dias": hist_totales_dias,
        "hist_meses": hist_meses,
        "hist_totales_meses": hist_totales_meses,
        "hist_anos": hist_anos,
        "hist_totales_anos": hist_totales_anos
    })

@app.route("/api/reset", methods=["POST"])
def reset_counter():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if username == "admin" and password == "arriondas":
        hoy_str = datetime.now(ZONA_MADRID).strftime("%Y-%m-%d")
        conn = get_db_connection()
        cursor = conn.cursor()
        query_del = "DELETE FROM canoas WHERE timestamp LIKE %s" if DATABASE_URL else "DELETE FROM canoas WHERE timestamp LIKE ?"
        cursor.execute(query_del, (f"{hoy_str}%",))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "ok", "message": "Contador de hoy reiniciado con éxito"}), 200
    else:
        return jsonify({"status": "error", "message": "Credenciales incorrectas"}), 401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)