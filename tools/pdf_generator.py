import os
import json
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import qrcode
from io import BytesIO


def generar_constancia(alumno: dict, ciclo: dict) -> str:
    """
    Genera un PDF de constancia de matrícula usando reportlab.
    Incluye:
    - Encabezado: "ACADEMIA TESLA - CONSTANCIA DE MATRÍCULA"
    - Datos: nombre completo, DNI, ciclo, horario, precio, fecha matrícula
    - Número de constancia: f"TESLA-{año}-{alumno_id[:8].upper()}"
    - QR con JSON: {constancia_numero, dni, ciclo, fecha}
    Guarda en /tmp/{constancia_numero}.pdf
    Retorna la ruta del archivo.
    """
    # Generar número de constancia
    anio = datetime.now(timezone.utc).strftime("%Y")
    alumno_id = str(alumno.get("id", "00000000"))
    constancia_numero = f"TESLA-{anio}-{alumno_id[:8].upper()}"

    # Ruta de salida
    output_path = os.path.join("/tmp", f"{constancia_numero}.pdf")

    # Crear el canvas PDF
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    # --- Encabezado ---
    c.setFillColor(HexColor("#1a237e"))
    c.rect(0, height - 3 * cm, width, 3 * cm, fill=True, stroke=False)

    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, height - 1.8 * cm, "ACADEMIA TESLA")

    c.setFont("Helvetica", 13)
    c.drawCentredString(width / 2, height - 2.5 * cm, "CONSTANCIA DE MATRÍCULA")

    # --- Número de constancia ---
    c.setFillColor(HexColor("#333333"))
    c.setFont("Helvetica-Bold", 11)
    y_pos = height - 4.5 * cm
    c.drawString(2 * cm, y_pos, f"N° Constancia: {constancia_numero}")

    # --- Datos del alumno ---
    y_pos -= 1.5 * cm
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(HexColor("#1a237e"))
    c.drawString(2 * cm, y_pos, "DATOS DEL ALUMNO")

    c.setFillColor(HexColor("#333333"))
    c.setFont("Helvetica", 11)

    nombre_completo = f"{alumno.get('nombres', '')} {alumno.get('apellidos', '')}"
    datos_alumno = [
        ("Nombre completo:", nombre_completo),
        ("DNI:", alumno.get("dni_alumno", "")),
        ("Grado:", alumno.get("grado", "")),
    ]

    for label, valor in datos_alumno:
        y_pos -= 0.8 * cm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2.5 * cm, y_pos, label)
        c.setFont("Helvetica", 10)
        c.drawString(7 * cm, y_pos, str(valor))

    # --- Datos del ciclo ---
    y_pos -= 1.5 * cm
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(HexColor("#1a237e"))
    c.drawString(2 * cm, y_pos, "DATOS DEL CICLO ACADÉMICO")

    c.setFillColor(HexColor("#333333"))

    datos_ciclo = [
        ("Ciclo:", ciclo.get("nombre", "")),
        ("Código:", ciclo.get("codigo", "")),
        ("Horario:", ciclo.get("horario", "")),
        ("Modalidad:", ciclo.get("modalidad", "")),
        ("Precio:", f"S/ {ciclo.get('precio_soles', 0):.2f}"),
        ("Fecha de inicio:", ciclo.get("fecha_inicio", "")),
    ]

    for label, valor in datos_ciclo:
        y_pos -= 0.8 * cm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2.5 * cm, y_pos, label)
        c.setFont("Helvetica", 10)
        c.drawString(7 * cm, y_pos, str(valor))

    # --- Datos de pago ---
    y_pos -= 1.5 * cm
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(HexColor("#1a237e"))
    c.drawString(2 * cm, y_pos, "DATOS DE MATRÍCULA")

    c.setFillColor(HexColor("#333333"))

    fecha_matricula = alumno.get("fecha_matricula", datetime.now(timezone.utc).isoformat())
    monto_pagado = alumno.get("monto_pagado", 0)

    datos_matricula = [
        ("Fecha de matrícula:", str(fecha_matricula)[:10]),
        ("Monto pagado:", f"S/ {monto_pagado:.2f}" if monto_pagado else "Pendiente"),
        ("ID de pago:", alumno.get("charge_id", "N/A")),
    ]

    for label, valor in datos_matricula:
        y_pos -= 0.8 * cm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2.5 * cm, y_pos, label)
        c.setFont("Helvetica", 10)
        c.drawString(7 * cm, y_pos, str(valor))

    # --- Código QR ---
    qr_data = json.dumps({
        "constancia_numero": constancia_numero,
        "dni": alumno.get("dni_alumno", ""),
        "ciclo": ciclo.get("codigo", ""),
        "fecha": str(fecha_matricula)[:10]
    })

    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    # Guardar QR en buffer
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    from reportlab.lib.utils import ImageReader
    qr_image_reader = ImageReader(qr_buffer)

    qr_size = 4 * cm
    qr_x = width - 2 * cm - qr_size
    qr_y = y_pos - 1.5 * cm - qr_size
    c.drawImage(qr_image_reader, qr_x, qr_y, width=qr_size, height=qr_size)

    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#666666"))
    c.drawCentredString(qr_x + qr_size / 2, qr_y - 0.5 * cm, "Escanea para verificar")

    # --- Pie de página ---
    c.setFillColor(HexColor("#1a237e"))
    c.rect(0, 0, width, 1.5 * cm, fill=True, stroke=False)

    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 0.7 * cm, "Academia Tesla — Centro Preuniversitario | Documento generado automáticamente")

    # Guardar PDF
    c.save()

    return output_path
