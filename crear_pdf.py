from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

doc = SimpleDocTemplate("CHULETA_CANOE_COUNTER_SELLA.pdf", pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
styles = getSampleStyleSheet()
story = []

# Estilos personalizados
titulo_style = ParagraphStyle('Titulo', parent=styles['Heading1'], fontSize=20, leading=24, textColor=colors.HexColor("#0ea5e9"), spaceAfter=6)
subtitulo_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor("#64748b"), spaceAfter=14)
h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=13, leading=16, textColor=colors.HexColor("#0f172a"), spaceBefore=10, spaceAfter=6)
body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor("#334155"))
code_style = ParagraphStyle('Code', parent=styles['Code'], fontSize=8.5, leading=11, textColor=colors.HexColor("#0f172a"), backColor=colors.HexColor("#f1f5f9"))

# 1. Cabecera
story.append(Paragraph("🛶 CHULETA MAESTRA — CANOE COUNTER SELLA", titulo_style))
story.append(Paragraph("Arriondas (Asturias) — Sistema Autónomo de Visión Artificial e Inteligencia Fluvial", subtitulo_style))
story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0ea5e9"), spaceAfter=12))

# 2. Enlaces
story.append(Paragraph("1. ENLACES Y PANELES OFICIALES", h2_style))
enlaces_data = [
    ["Servicio", "Dirección / URL"],
    ["Web Pública", "https://sella-canoe-counter.onrender.com"],
    ["Servidor IA (Hetzner)", "https://console.hetzner.cloud (IP: 167.233.81.133)"],
    ["Servidor Web (Render)", "https://dashboard.render.com"],
    ["Base de Datos (Neon)", "https://console.neon.tech"]
]
t_enlaces = Table(enlaces_data, colWidths=[130, 390])
t_enlaces.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8.5),
    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ('TOPPADDING', (0,0), (-1,-1), 4),
    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
]))
story.append(t_enlaces)
story.append(Spacer(1, 10))

# 3. Credenciales
story.append(Paragraph("2. ACCESOS Y CREDENCIALES", h2_style))
story.append(Paragraph("<b>Panel Web (Botón Reiniciar):</b> Usuario: <code>admin</code> | Contraseña: <code>arriondas</code>", body_style))
story.append(Paragraph("<b>Acceso SSH al Servidor IA:</b> <code>ssh root@167.233.81.133</code>", body_style))
story.append(Spacer(1, 10))

# 4. Comandos Hetzner
story.append(Paragraph("3. COMANDOS ÚTILES EN EL SERVIDOR (HETZNER)", h2_style))
comandos_data = [
    ["Acción", "Comando Linux"],
    ["Ver canoas en directo", "journalctl -u sella-worker.service -f"],
    ["Salir de los logs", "Control + C (el servicio NO se detiene)"],
    ["Ver consumo CPU/RAM", "htop (para salir pulsa 'q')"],
    ["Reiniciar servicio IA", "systemctl restart sella-worker.service"],
    ["Detener servicio IA", "systemctl stop sella-worker.service"],
    ["Comprobar Ping Render", "crontab -l (ejecuta cada 3 min)"],
    ["Salir del servidor", "exit"]
]
t_cmd = Table(comandos_data, colWidths=[150, 370])
t_cmd.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8),
    ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
    ('TOPPADDING', (0,0), (-1,-1), 3.5),
    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
]))
story.append(t_cmd)
story.append(Spacer(1, 10))

# 5. Rutina y Fin de Temporada
story.append(Paragraph("4. RUTINAS Y FIN DE TEMPORADA", h2_style))
story.append(Paragraph("• <b>Reinicio Diario Automático:</b> A las 23:59:59 el contador pasa a 0 y archiva el día en Histórico.", body_style))
story.append(Paragraph("• <b>Fin de Temporada (Octubre/Noviembre):</b> Entrar en Hetzner -> <i>Delete Server</i> (Coste pasa a 0,00 €/mes). Render y Neon guardan los datos gratis.", body_style))
story.append(Paragraph("• <b>Inicio de Temporada (Mayo/Junio):</b> Crear servidor nuevo, <code>git clone</code>, activar servicio y listo en 2 minutos.", body_style))

doc.build(story)
print("📄 ¡PDF generado con éxito como 'CHULETA_CANOE_COUNTER_SELLA.pdf'!")
