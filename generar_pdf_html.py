#!/usr/bin/env python3
"""
Generador de PDF de Factura Electrónica AFIP - Formato oficial
Usa HTML template + WeasyPrint para replicar el formato exacto de ARCA/AFIP.
"""

import json
import base64
import os
import segno
from io import BytesIO
from jinja2 import Template
from weasyprint import HTML


def generate_qr_code(data):
    """
    Genera QR code según especificación AFIP RG 4291.
    Devuelve data URI (base64 PNG) para embeber en HTML.
    """
    qr_data = {
        "ver": 1,
        "fecha": data["fecha"],
        "cuit": int(data["cuit_emisor"]),
        "ptoVta": int(data["punto_venta"]),
        "tipoCmp": int(data["tipo_comprobante"]),
        "nroCmp": int(data["numero"]),
        "importe": float(data["importe_total"]),
        "moneda": "PES",
        "ctz": 1,
        "tipoDocRec": int(data.get("tipo_doc_receptor", 80)),
        "nroDocRec": int(data["cuit_receptor"]),
        "tipoCodAut": "E",
        "codAut": int(data["cae"])
    }

    qr_text = "https://www.afip.gob.ar/fe/qr/?p=" + base64.urlsafe_b64encode(
        json.dumps(qr_data).encode("utf-8")
    ).decode("utf-8")

    qr = segno.make_qr(qr_text)
    buffer = BytesIO()
    qr.save(buffer, kind="png", scale=4)
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def generar_pdf(datos_factura, output_path):
    """
    Genera PDF de factura en formato oficial AFIP.
    Produce 3 páginas: ORIGINAL, DUPLICADO, TRIPLICADO.

    datos_factura: dict con claves "emisor", "cliente", "comprobante", "items", "totales".
    output_path: ruta donde guardar el PDF.
    """
    comp = datos_factura["comprobante"]
    emisor = datos_factura["emisor"]
    cliente = datos_factura["cliente"]

    # Parse fecha for QR (DD/MM/YYYY -> YYYY-MM-DD)
    fecha_parts = comp["fecha_emision"].split("/")
    fecha_qr = f"{fecha_parts[2]}-{fecha_parts[1]}-{fecha_parts[0]}"

    # Parse total for QR
    total_str = datos_factura["totales"]["total"].replace(".", "").replace(",", ".")

    qr_data = {
        "fecha": fecha_qr,
        "cuit_emisor": emisor["cuit"],
        "punto_venta": comp["punto_venta"].lstrip("0") or "0",
        "tipo_comprobante": comp.get("tipo_comprobante", 11),
        "numero": comp["numero"].lstrip("0") or "0",
        "importe_total": total_str,
        "tipo_doc_receptor": 80,
        "cuit_receptor": cliente["cuit"],
        "cae": comp["cae"]
    }
    qr_image = generate_qr_code(qr_data)

    # Load template
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factura_template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = Template(template_str)

    html_content = template.render(
        copies=["ORIGINAL", "DUPLICADO", "TRIPLICADO"],
        emisor=emisor,
        comp=comp,
        cliente=cliente,
        items=datos_factura["items"],
        totales=datos_factura["totales"],
        qr_image=qr_image
    )

    html = HTML(string=html_content)
    html.write_pdf(output_path)

    print(f"PDF generado: {output_path}")
    return output_path
