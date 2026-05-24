"""
FRAGMENTO — reemplaza el método generar_pdf() en afip_facturacion.py
(y el bloque de construcción de items_pdf + datos["totales"])
"""

# Alícuotas de IVA soportadas por AFIP (código → porcentaje)
# Ref: https://www.afip.gob.ar/fe/documentos/WSFE-Tablas.xls  (Tabla de IVA)
ALICUOTAS_IVA = {
    3:  0.0,    # 0%
    4:  10.5,   # 10,5%
    5:  21.0,   # 21%
    6:  27.0,   # 27%
    8:  5.0,    # 5%
    9:  2.5,    # 2,5%
}

# Texto para mostrar en la columna del template
ALICUOTA_TEXTO = {
    3:  "0%",
    4:  "10,5%",
    5:  "21%",
    6:  "27%",
    8:  "5%",
    9:  "2,5%",
}


def generar_pdf(self, invoice_result: dict, output_dir: str = None) -> str | None:
    """
    Genera el PDF de una factura ya aprobada.

    Cada ítem del JSON de entrada puede incluir:
        "alicuota_iva_id": int   →  código AFIP de alícuota (default: 3 = 0%)
    Si el emisor es Monotributo (tipo_comprobante 11/12/13) la alícuota
    siempre es 0% y se ignora lo que venga en el ítem.

    Args:
        invoice_result: El dict devuelto por emitir_factura().
        output_dir: Directorio de salida. Default: <base_dir>/output/

    Returns:
        Ruta al PDF generado, o None si hubo error.
    """
    from generar_pdf_html import generar_pdf as _generar_pdf

    r          = invoice_result
    receptor   = r["receptor"]
    items      = r["items"]
    emisor_cfg = self.config["emisor"]
    tipo_cbte  = r["tipo_comprobante"]
    tipo_info  = TIPO_COMP_INFO.get(tipo_cbte, ("C", "FACTURA", "011"))

    # Monotributo (Factura C = tipo 11,12,13) → siempre alícuota 0%
    es_monotributo = tipo_cbte in (11, 12, 13)

    def fmt_date(d):
        if len(d) == 8:
            return f"{d[6:8]}/{d[4:6]}/{d[0:4]}"
        return d

    def fmt_money(n):
        return f"{float(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # ── Construir ítems para el template ──────────────────────────────────────
    items_pdf = []
    acum_iva  = {k: 0.0 for k in ALICUOTAS_IVA}   # acumuladores por alícuota
    neto_gravado = 0.0

    for item in items:
        cantidad       = float(item["cantidad"])
        precio_unit    = float(item["precio_unitario"])
        bonif_pct      = float(item.get("bonificacion_pct", 0))
        bonif_imp      = cantidad * precio_unit * bonif_pct / 100
        subtotal_neto  = cantidad * precio_unit - bonif_imp

        # Alícuota IVA
        if es_monotributo:
            alicuota_id = 3   # 0% — Monotributo no discrimina IVA
        else:
            alicuota_id = int(item.get("alicuota_iva_id", 3))

        pct_iva          = ALICUOTAS_IVA.get(alicuota_id, 0.0)
        iva_item         = subtotal_neto * pct_iva / 100
        subtotal_con_iva = subtotal_neto + iva_item

        neto_gravado            += subtotal_neto
        acum_iva[alicuota_id]   += iva_item

        items_pdf.append({
            "codigo":          item.get("codigo", ""),
            "descripcion":     item["descripcion"],
            "cantidad":        fmt_money(cantidad),
            "unidad":          item.get("unidad", "unidades"),
            "precio_unit":     fmt_money(precio_unit),
            "bonif_pct":       fmt_money(bonif_pct),
            "bonif_imp":       fmt_money(bonif_imp),
            "subtotal":        fmt_money(subtotal_neto),
            "alicuota_iva":    ALICUOTA_TEXTO.get(alicuota_id, "0%"),
            "subtotal_con_iva":fmt_money(subtotal_con_iva),
        })

    # ── Totales ───────────────────────────────────────────────────────────────
    otros_tributos = float(r.get("otros_tributos", 0))
    total_iva      = sum(acum_iva.values())
    importe_total  = neto_gravado + total_iva + otros_tributos

    totales = {
        "neto_gravado":   fmt_money(neto_gravado),
        "iva_27":         fmt_money(acum_iva[6]),
        "iva_21":         fmt_money(acum_iva[5]),
        "iva_105":        fmt_money(acum_iva[4]),
        "iva_5":          fmt_money(acum_iva[8]),
        "iva_25":         fmt_money(acum_iva[9]),
        "iva_0":          fmt_money(acum_iva[3]),
        "otros_tributos": fmt_money(otros_tributos),
        "total":          fmt_money(importe_total),
    }

    # ── Armar datos para el template ──────────────────────────────────────────
    datos = {
        "emisor": {
            "razon_social": emisor_cfg["razon_social"],
            "domicilio":    emisor_cfg["domicilio"],
            "condicion_iva":emisor_cfg["condicion_iva"],
            "cuit":         emisor_cfg["cuit"],
            "iibb":         emisor_cfg["ingresos_brutos"],
            "fecha_inicio": emisor_cfg["fecha_inicio_actividades"],
        },
        "cliente": {
            "nombre":       receptor["nombre"],
            "cuit":         receptor["cuit"],
            "condicion_iva": CONDICION_IVA_TEXTO.get(
                int(receptor["condicion_iva"]), "IVA Responsable Inscripto"
            ),
            "domicilio":    receptor.get("domicilio", ""),
        },
        "comprobante": {
            "punto_venta":        str(r["punto_venta"]).zfill(5),
            "numero":             str(r["comprobante_nro"]).zfill(8),
            "fecha_emision":      fmt_date(r["fecha_emision"]),
            "periodo_desde":      fmt_date(r["periodo_desde"]),
            "periodo_hasta":      fmt_date(r["periodo_hasta"]),
            "fecha_vto_pago":     fmt_date(r["periodo_hasta"]),
            "condicion_venta":    r.get("condicion_venta", "Contado"),
            "cae":                r["cae"],
            "cae_vto":            fmt_date(r["cae_vto"]),
            "tipo_comprobante":   tipo_cbte,
            "letra":              tipo_info[0],
            "nombre_comprobante": tipo_info[1],
            "cod_comprobante":    tipo_info[2],
        },
        "items":   items_pdf,
        "totales": totales,
    }

    filename = (
        f"{self.cuit_emisor}_{tipo_info[2]}_"
        f"{str(r['punto_venta']).zfill(5)}_"
        f"{str(r['comprobante_nro']).zfill(8)}.pdf"
    )

    if output_dir is None:
        output_dir = os.path.join(self.base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, filename)
    _generar_pdf(datos, output_path)
    return output_path


"""
─────────────────────────────────────────────────────────────────
CAMBIO EN EL JSON DE ENTRADA (emitir_factura)
─────────────────────────────────────────────────────────────────

Cada ítem ahora puede llevar `alicuota_iva_id` (código AFIP):

    3  → 0%      (default, Monotributo, exentos)
    4  → 10,5%
    5  → 21%     ← el más común para RI
    6  → 27%
    8  → 5%
    9  → 2,5%

Ejemplo JSON para Factura A (IVA Responsable Inscripto):

{
  "env": "homo",
  "tipo_comprobante": 1,
  "receptor": {
    "nombre": "CAMPODONICO ROBERTO EMILIO",
    "cuit": "20203031514",
    "condicion_iva": 1,
    "domicilio": "Entre Rios (Sur) 219 - San Juan"
  },
  "items": [
    {
      "descripcion": "Lavandina",
      "cantidad": 5,
      "precio_unitario": 578.51,
      "unidad": "litros",
      "alicuota_iva_id": 5
    },
    {
      "descripcion": "Lisoform",
      "cantidad": 5,
      "precio_unitario": 743.80,
      "unidad": "litros",
      "alicuota_iva_id": 5
    }
  ]
}

Para Factura C (Monotributo, tipo_comprobante=11):
  No hace falta poner `alicuota_iva_id`, siempre queda en 0%.
─────────────────────────────────────────────────────────────────
"""
