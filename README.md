# 🛶 Sella Canoe Counter — AI River Traffic Vision

Sistema autónomo de visión artificial y telemetría en tiempo real para la monitorización y conteo del flujo de canoas durante el Descenso del Sella en Arriondas (Asturias).

## 🚀 Características
- **Captura Autónoma:** Interceptor dinámico de señal web con Playwright.
- **Detección y Tracking:** YOLOv8 + Tracker espacial por distancias euclídeas.
- **Telemetría en Vivo:** Vista panorámica PiP, Checkpoint IA y sismógrafo de ritmo de flujo proyectado en tiempo real.
- **Aceleración por Hardware:** Soporte nativo para Apple Silicon GPU (Metal Performance Shaders - MPS).

## 🛠️ Instalación rápida
```bash
git clone https://github.com/pintularrama-cyber/canoe-counter.git
cd canoe-counter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python test_stream.py