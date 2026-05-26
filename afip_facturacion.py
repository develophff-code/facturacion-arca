#!/usr/bin/env python3
"""
Facturación Electrónica ARCA/AFIP — Módulo reutilizable
Genera comprobantes electrónicos via WSFEv1 + PDF en formato oficial.

Uso:
    from afip_facturacion import AfipFacturacion
    afip = AfipFacturacion(config_dict, base_dir="/ruta/proyecto")
    resultado = afip.emitir_factura(factura_json)
"""

import os
import json
import datetime
import subprocess
import tempfile
import requests
import psycopg2

from lxml import etree
from zeep import Client, Settings
from zeep.transports import Transport
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# SSL Adapter (DH keys débiles de AFIP)
# ============================================================


class AFIPSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


# ============================================================
# URLs AFIP (fijas)
# ============================================================

AFIP_URLS = {
    "homo": {
        "wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL",
        "wsfe": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
    },
    "prod": {
        "wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL",
        "wsfe": "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL",
    },
}

CONDICION_IVA_TEXTO = {
    1: "IVA Responsable Inscripto",
    4: "IVA Sujeto Exento",
    5: "Consumidor Final",
    6: "Responsable Monotributo",
}

TIPO_COMP_INFO = {
    1: ("A", "FACTURA", "001"),
    6: ("B", "FACTURA", "006"),
    11: ("C", "FACTURA", "011"),
    2: ("A", "NOTA DE DÉBITO", "002"),
    7: ("B", "NOTA DE DÉBITO", "007"),
    12: ("C", "NOTA DE DÉBITO", "012"),
    3: ("A", "NOTA DE CRÉDITO", "003"),
    8: ("B", "NOTA DE CRÉDITO", "008"),
    13: ("C", "NOTA DE CRÉDITO", "013"),
}

# Código AFIP → porcentaje de IVA (Tabla de alícuotas WSFEv1)
ALICUOTAS_IVA = {
    3: 0.0,  # 0%
    4: 10.5,  # 10,5%
    5: 21.0,  # 21%
    6: 27.0,  # 27%
    8: 5.0,  # 5%
    9: 2.5,  # 2,5%
}

ALICUOTA_TEXTO = {
    3: "0%",
    4: "10,5%",
    5: "21%",
    6: "27%",
    8: "5%",
    9: "2,5%",
}

# Tipos de comprobante que NO discriminan IVA (Monotributo / Consumidor Final)
TIPOS_SIN_IVA = {11, 12, 13}


# ============================================================
# Clase principal
# ============================================================


class AfipFacturacion:
    """
    Módulo de facturación electrónica ARCA/AFIP.

    Args:
        config (dict): Contenido del config.json (emisor, certificados, etc.)
        base_dir (str): Directorio raíz del proyecto (donde están afip_certs/ y output/).
                        Default: directorio de trabajo actual.
    """

    def __init__(self, config: dict, base_dir: str = None):
        self.base_dir = base_dir or os.getcwd()
        self.config = config

        # Datos del emisor
        self.cuit_emisor = config["emisor"]["cuit"]
        self.punto_venta = config.get("punto_venta", 1)
        self.tipo_cbte = config.get("tipo_comprobante", 11)
        self.concepto = config.get("concepto", 2)

        # Rutas a certificados por entorno
        self.certs = {}
        for env in ("homo", "prod"):
            if env in config.get("certificados", {}):
                self.certs[env] = {
                    "cert": os.path.join(
                        self.base_dir, config["certificados"][env]["cert"]
                    ),
                    "key": os.path.join(
                        self.base_dir, config["certificados"][env]["key"]
                    ),
                }

        # Directorio de caché de tokens
        self._token_cache_dir = os.path.join(self.base_dir, "afip_certs")
        os.makedirs(self._token_cache_dir, exist_ok=True)

        # Conexión PostgreSQL
        self._db_conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            dbname=os.getenv("DB_NAME", "facturacion"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )
        self._db_conn.autocommit = True

    # ----------------------------------------------------------
    # Punto de entrada principal
    # ----------------------------------------------------------

    def emitir_factura(self, factura_json: dict) -> dict | None:
        """
        Emite una factura electrónica a partir de un dict/JSON.

        Args:
            factura_json: Ver schema completo en README / ejemplo al pie.

        Returns:
            dict con el resultado (cae, nro, etc.) o None si fue rechazada.

        Raises:
            ValueError: Si faltan campos obligatorios.
            Exception:  Errores de comunicación con AFIP.
        """
        self._validar_json(factura_json)

        env = factura_json.get("env", "homo")
        tipo_cbte = factura_json.get("tipo_comprobante", self.tipo_cbte)
        pto_venta = factura_json.get("punto_venta", self.punto_venta)
        concepto = factura_json.get("concepto", self.concepto)
        receptor = factura_json["receptor"]
        items = factura_json["items"]

        # Calcular montos discriminando IVA por ítem
        es_sin_iva = tipo_cbte in TIPOS_SIN_IVA
        imp_neto = 0.0
        imp_iva = 0.0

        for i in items:
            cant = float(i["cantidad"])
            precio = float(i["precio_unitario"])
            bonif_pct = float(i.get("bonificacion_pct", 0))
            subtotal = cant * precio * (1 - bonif_pct / 100)
            imp_neto += subtotal

            if not es_sin_iva:
                alicuota_id = int(i.get("alicuota_iva_id", 3))
                pct = ALICUOTAS_IVA.get(alicuota_id, 0.0)
                imp_iva += subtotal * pct / 100

        monto_total = round(imp_neto + imp_iva, 2)
        imp_neto = round(imp_neto, 2)
        imp_iva = round(imp_iva, 2)

        # Fecha de emisión
        if "fecha_emision" in factura_json:
            today = datetime.date.fromisoformat(factura_json["fecha_emision"])
        else:
            today = datetime.date.today()

        fecha_emision = today.strftime("%Y%m%d")

        # Período de servicio (primer y último día del mes de emisión)
        first_day = today.replace(day=1)
        if today.month == 12:
            last_day = today.replace(day=31)
        else:
            last_day = today.replace(month=today.month + 1, day=1) - datetime.timedelta(
                days=1
            )

        fecha_desde = first_day.strftime("%Y%m%d")
        fecha_hasta = last_day.strftime("%Y%m%d")
        fecha_vto_pago = last_day.strftime("%Y%m%d")

        # Autenticación + cliente SOAP
        token, sign = self._authenticate(env)
        wsfe = self._get_wsfe_client(env)

        # Próximo número de comprobante
        last_num = self._get_last_voucher_number(
            wsfe, token, sign, pto_venta, tipo_cbte
        )
        next_num = last_num + 1

        print(f"📄 Próximo comprobante: {next_num}")

        auth = {
            "Token": token,
            "Sign": sign,
            "Cuit": int(self.cuit_emisor),
        }

        fe_cae_req = {
            "FeCabReq": {
                "CantReg": 1,
                "PtoVta": pto_venta,
                "CbteTipo": tipo_cbte,
            },
            "FeDetReq": {
                "FECAEDetRequest": [
                    {
                        "Concepto": concepto,
                        "DocTipo": 80,  # CUIT
                        "DocNro": int(receptor["cuit"]),
                        "CbteDesde": next_num,
                        "CbteHasta": next_num,
                        "CbteFch": fecha_emision,
                        "ImpTotal": monto_total,
                        "ImpTotConc": 0,
                        "ImpNeto": imp_neto,
                        "ImpOpEx": 0,
                        "ImpTrib": 0,
                        "ImpIVA": imp_iva,
                        # ✅ FIX 1: solo si concepto 2 o 3
                        **(
                            {
                                "FchServDesde": fecha_desde,
                                "FchServHasta": fecha_hasta,
                                "FchVtoPago": fecha_vto_pago,
                            }
                            if concepto in [2, 3]
                            else {}
                        ),
                        "MonId": "PES",
                        "MonCotiz": 1,
                        "CondicionIVAReceptorId": int(receptor["condicion_iva"]),
                        # ✅ FIX 2: array IVA obligatorio cuando ImpNeto > 0
                        **(
                            {"Iva": {"AlicIva": self._build_iva_array(items)}}
                            if imp_neto > 0
                            else {}
                        ),
                        # Comprobante asociado (requerido para NC y ND)
                        **self._build_cbtes_asoc(factura_json),
                    }
                ]
            },
        }

        print(f"\n📋 Generando factura:")
        print(f"   Receptor : {receptor['nombre']} (CUIT {receptor['cuit']})")
        print(f"   Monto    : ${monto_total:,.2f}")
        print(f"   Período  : {fecha_desde} → {fecha_hasta}")
        print(f"   Nro      : {next_num}")

        response = wsfe.service.FECAESolicitar(Auth=auth, FeCAEReq=fe_cae_req)
        det = response.FeDetResp.FECAEDetResponse[0]

        if det.Resultado == "A":
            print(f"\n✅ FACTURA APROBADA")
            print(f"   CAE : {det.CAE}  (vto {det.CAEFchVto})")

            result = {
                "status": "aprobada",
                "receptor": receptor,
                "items": items,
                "monto_total": monto_total,
                "imp_neto": imp_neto,
                "imp_iva": imp_iva,
                "comprobante_nro": next_num,
                "punto_venta": pto_venta,
                "tipo_comprobante": tipo_cbte,
                "cae": det.CAE,
                "cae_vto": det.CAEFchVto,
                "fecha_emision": fecha_emision,
                "periodo_desde": fecha_desde,
                "periodo_hasta": fecha_hasta,
                "condicion_venta": factura_json.get("condicion_venta", "Contado"),
                "comprobante_asociado": factura_json.get("comprobante_asociado"),
            }
            # Persistir en PostgreSQL
            try:
                with self._db_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO comprobantes_afip (
                            fecha_emision, tipo_comprobante, punto_venta,
                            comprobante_nro, cae, cae_vto,
                            receptor_nombre, receptor_cuit, receptor_condicion_iva,
                            imp_neto, imp_iva, monto_total,
                            concepto, condicion_venta, env, request_json
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                    """,
                        (
                            today,
                            tipo_cbte,
                            pto_venta,
                            next_num,
                            str(det.CAE),
                            datetime.date(
                                int(det.CAEFchVto[:4]),
                                int(det.CAEFchVto[4:6]),
                                int(det.CAEFchVto[6:]),
                            ),
                            receptor.get("nombre"),
                            receptor.get("cuit"),
                            int(receptor.get("condicion_iva", 0)),
                            imp_neto,
                            imp_iva,
                            monto_total,
                            concepto,
                            factura_json.get("condicion_venta", "Contado"),
                            env,
                            json.dumps(factura_json),
                        ),
                    )
                    print(f"   💾 Guardado en DB")
            except Exception as e:
                print(f"   ⚠️  Error guardando en DB: {e}")
            return result
        else:
            obs = ""
            errs = ""
            if det.Observaciones:
                obs = "; ".join([o.Msg for o in det.Observaciones.Obs])
            if response.Errors:
                errs = "; ".join([e.Msg for e in response.Errors.Err])
            print(f"\n❌ FACTURA RECHAZADA")
            print(f"   Obs    : {obs}")
            print(f"   Errores: {errs}")
            return None

    def generar_pdf(self, invoice_result: dict, output_dir: str = None) -> str | None:
        """
        Genera el PDF de una factura ya aprobada.

        Args:
            invoice_result: El dict devuelto por emitir_factura().
            output_dir: Directorio de salida. Default: <base_dir>/output/

        Returns:
            Ruta al PDF generado, o None si hubo error.
        """
        from generar_pdf_html import generar_pdf as _generar_pdf

        r = invoice_result
        receptor = r["receptor"]
        items = r["items"]
        emisor_cfg = self.config["emisor"]
        tipo_cbte = r["tipo_comprobante"]
        tipo_info = TIPO_COMP_INFO.get(tipo_cbte, ("C", "FACTURA", "011"))
        es_sin_iva = tipo_cbte in TIPOS_SIN_IVA

        def fmt_date(d):
            if len(d) == 8:
                return f"{d[6:8]}/{d[4:6]}/{d[0:4]}"
            return d

        def fmt_money(n):
            # Formato argentino: punto como separador de miles, coma decimal
            return (
                f"{float(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )

        # Acumuladores de IVA por alícuota
        acum_iva = {k: 0.0 for k in ALICUOTAS_IVA}
        neto_gravado = 0.0

        # Construir ítems para el template
        items_pdf = []
        for item in items:
            cant = float(item["cantidad"])
            precio = float(item["precio_unitario"])
            bonif_pct = float(item.get("bonificacion_pct", 0))
            bonif_imp = cant * precio * bonif_pct / 100
            subtotal = cant * precio - bonif_imp

            if es_sin_iva:
                alicuota_id = 3
            else:
                alicuota_id = int(item.get("alicuota_iva_id", 3))

            pct_iva = ALICUOTAS_IVA.get(alicuota_id, 0.0)
            iva_item = subtotal * pct_iva / 100
            subtotal_con_iva = subtotal + iva_item

            neto_gravado += subtotal
            acum_iva[alicuota_id] += iva_item

            items_pdf.append(
                {
                    "codigo": item.get("codigo", ""),
                    "descripcion": item["descripcion"],
                    "cantidad": fmt_money(cant),
                    "unidad": item.get("unidad", "unidades"),
                    "precio_unit": fmt_money(precio),
                    "bonif_pct": fmt_money(bonif_pct),
                    "bonif_imp": fmt_money(bonif_imp),
                    "subtotal": fmt_money(subtotal),
                    "alicuota_iva": ALICUOTA_TEXTO.get(alicuota_id, "0%"),
                    "subtotal_con_iva": fmt_money(subtotal_con_iva),
                }
            )

        otros_tributos = float(r.get("otros_tributos", 0))
        total_iva = sum(acum_iva.values())
        importe_total = neto_gravado + total_iva + otros_tributos

        totales = {
            "neto_gravado": fmt_money(neto_gravado),
            "iva_27": fmt_money(acum_iva[6]),
            "iva_21": fmt_money(acum_iva[5]),
            "iva_105": fmt_money(acum_iva[4]),
            "iva_5": fmt_money(acum_iva[8]),
            "iva_25": fmt_money(acum_iva[9]),
            "iva_0": fmt_money(acum_iva[3]),
            "otros_tributos": fmt_money(otros_tributos),
            "total": fmt_money(importe_total),
        }

        # ── Armar datos para el template ──────────────────────────────────────
        datos = {
            "emisor": {
                "razon_social": emisor_cfg["razon_social"],
                "domicilio": emisor_cfg["domicilio"],
                "condicion_iva": emisor_cfg["condicion_iva"],
                "cuit": emisor_cfg["cuit"],
                "iibb": emisor_cfg["ingresos_brutos"],
                "fecha_inicio": emisor_cfg["fecha_inicio_actividades"],
            },
            "cliente": {
                "nombre": receptor["nombre"],
                "cuit": receptor["cuit"],
                "condicion_iva": CONDICION_IVA_TEXTO.get(
                    int(receptor["condicion_iva"]), "IVA Responsable Inscripto"
                ),
                "domicilio": receptor.get("domicilio", ""),
            },
            "comprobante": {
                "punto_venta": str(r["punto_venta"]).zfill(5),
                "numero": str(r["comprobante_nro"]).zfill(8),
                "fecha_emision": fmt_date(r["fecha_emision"]),
                "periodo_desde": fmt_date(r["periodo_desde"]),
                "periodo_hasta": fmt_date(r["periodo_hasta"]),
                "fecha_vto_pago": fmt_date(r["periodo_hasta"]),
                "condicion_venta": r.get("condicion_venta", "Contado"),
                "cae": r["cae"],
                "cae_vto": fmt_date(r["cae_vto"]),
                "tipo_comprobante": tipo_cbte,
                "letra": tipo_info[0],
                "nombre_comprobante": tipo_info[1],
                "cod_comprobante": tipo_info[2],
            },
            "items": items_pdf,
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

    # ----------------------------------------------------------
    # WSAA — Autenticación
    # ----------------------------------------------------------

    def _authenticate(self, env: str) -> tuple[str, str]:
        """Obtiene Token y Sign del WSAA, con caché local (~12 hs)."""
        cache_file = os.path.join(self._token_cache_dir, f"token_cache_{env}.json")

        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                cached = json.load(f)
            exp = datetime.datetime.fromisoformat(cached["expiration"])
            if exp > datetime.datetime.now(datetime.timezone.utc):
                print(f"🔐 Token cacheado válido hasta {exp.strftime('%H:%M:%S')} UTC")
                return cached["token"], cached["sign"]

        print(f"🔐 Autenticando en WSAA ({env})...")

        if env not in self.certs:
            raise Exception(f"No hay certificados configurados para el entorno '{env}'")

        cert_path = self.certs[env]["cert"]
        key_path = self.certs[env]["key"]

        ltr_xml = self._create_login_ticket_request()
        cms_signed = self._sign_login_ticket(ltr_xml, cert_path, key_path)

        settings = Settings(strict=False, xml_huge_tree=True)
        client = Client(AFIP_URLS[env]["wsaa"], settings=settings)

        # DEBUG temporal
        print("=== CMS a enviar (primeros 200 chars) ===")
        print(cms_signed[:200])
        print("=========================================")

        response = client.service.loginCms(cms_signed)
        root = etree.fromstring(response.encode("utf-8"))

        token = root.find(".//token").text
        sign = root.find(".//sign").text
        expiration = root.find(".//expirationTime").text

        with open(cache_file, "w") as f:
            json.dump({"token": token, "sign": sign, "expiration": expiration}, f)

        print("✅ Autenticación exitosa")
        return token, sign

    def _create_login_ticket_request(self, service: str = "wsfe") -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        unique_id = int(now.timestamp())
        gen_time = (now - datetime.timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%S-00:00"
        )
        exp_time = (now + datetime.timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%S-00:00"
        )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<loginTicketRequest version="1.0">
  <header>
    <uniqueId>{unique_id}</uniqueId>
    <generationTime>{gen_time}</generationTime>
    <expirationTime>{exp_time}</expirationTime>
  </header>
  <service>{service}</service>
</loginTicketRequest>"""

    def _sign_login_ticket(self, ltr_xml: str, cert_path: str, key_path: str) -> str:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.serialization import pkcs7

        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

        with open(key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)

        data = ltr_xml.encode("utf-8")

        # AFIP requiere firma attached (contenido incluido) en PEM sin headers
        options = [pkcs7.PKCS7Options.NoAttributes]
        cms_pem = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(data)
            .add_signer(cert, key, hashes.SHA256())
            .sign(serialization.Encoding.PEM, options)
        )

        # Extraer solo el base64 sin headers PEM
        lines_pem = cms_pem.decode("ascii").strip().split("\n")
        return "".join(l for l in lines_pem if not l.startswith("-----"))

    def _build_cbtes_asoc(self, factura_json: dict) -> dict:
        """
        Construye el nodo CbtesAsoc si el JSON trae comprobante_asociado.
        Requerido para Notas de Crédito (tipos 3/8/13) y Débito (2/7/12).
        """
        asoc = factura_json.get("comprobante_asociado")
        if not asoc:
            return {}
        return {
            "CbtesAsoc": {
                "CbteAsoc": [
                    {
                        "Tipo": int(asoc["tipo"]),
                        "PtoVta": int(asoc["punto_venta"]),
                        "Nro": int(asoc["numero"]),
                        "Cuit": int(asoc["cuit_emisor"]),
                        "CbteFch": str(asoc["fecha"]).replace("-", ""),
                    }
                ]
            }
        }

    def _build_iva_array(self, items):
        """Agrupa items por alicuota y acumula base imponible e importe IVA."""
        from collections import defaultdict

        # Id AFIP → tasa
        tasas = {3: 0.00, 4: 0.105, 5: 0.21, 6: 0.27, 8: 0.05, 9: 0.025}

        grupos = defaultdict(float)
        for item in items:
            alicuota_id = item.get("alicuota_iva_id", 5)
            precio = item["precio_unitario"] * item["cantidad"]
            grupos[alicuota_id] += precio

        resultado = []
        for alicuota_id, base in grupos.items():
            tasa = tasas.get(alicuota_id, 0.21)
            resultado.append(
                {
                    "Id": alicuota_id,
                    "BaseImp": round(base, 2),
                    "Importe": round(base * tasa, 2),
                }
            )

        return resultado

    # ----------------------------------------------------------
    # WSFEv1 — Facturación
    # ----------------------------------------------------------

    def _get_wsfe_client(self, env: str):
        settings = Settings(strict=False, xml_huge_tree=True)
        session = requests.Session()
        session.mount("https://", AFIPSSLAdapter())
        transport = Transport(session=session)
        return Client(AFIP_URLS[env]["wsfe"], settings=settings, transport=transport)

    def _get_last_voucher_number(
        self, client, token: str, sign: str, pto_venta: int, tipo_cbte: int
    ) -> int:
        auth = {
            "Token": token,
            "Sign": sign,
            "Cuit": int(self.cuit_emisor),
        }
        response = client.service.FECompUltimoAutorizado(
            Auth=auth, PtoVta=pto_venta, CbteTipo=tipo_cbte
        )
        return response.CbteNro

    # ----------------------------------------------------------
    # Validación del JSON de entrada
    # ----------------------------------------------------------

    def _validar_json(self, data: dict):
        """Valida los campos mínimos obligatorios del JSON de factura."""
        errores = []

        if "receptor" not in data:
            errores.append("Falta campo 'receptor'")
        else:
            for campo in ("nombre", "cuit", "condicion_iva"):
                if campo not in data["receptor"]:
                    errores.append(f"Falta receptor.{campo}")

        if "items" not in data or not data["items"]:
            errores.append("Falta campo 'items' (lista de ítems no puede estar vacía)")
        else:
            for i, item in enumerate(data["items"]):
                for campo in ("descripcion", "cantidad", "precio_unitario"):
                    if campo not in item:
                        errores.append(f"Falta items[{i}].{campo}")

        if errores:
            raise ValueError(f"JSON de factura inválido:\n  " + "\n  ".join(errores))


# ============================================================
# CLI — para uso directo: python afip_facturacion.py factura.json homo
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python afip_facturacion.py <factura.json> [homo|prod]")
        print()
        print("Ejemplo de factura.json:")
        ejemplo = {
            "env": "homo",
            "tipo_comprobante": 11,
            "receptor": {
                "nombre": "GARCIA JUAN CARLOS",
                "cuit": "23123456789",
                "condicion_iva": 1,
                "domicilio": "Av. Corrientes 1234 - CABA",
            },
            "items": [
                {
                    "descripcion": "Desarrollo de software - Mayo 2025",
                    "cantidad": 1,
                    "precio_unitario": 150000.00,
                }
            ],
        }
        print(json.dumps(ejemplo, indent=2, ensure_ascii=False))
        sys.exit(1)

    factura_file = sys.argv[1]
    env_override = sys.argv[2] if len(sys.argv) > 2 else None

    # Cargar config
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(base_dir, "config.json")

    if not os.path.exists(config_file):
        print("❌ No se encontró config.json")
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Cargar JSON de la factura
    with open(factura_file, "r", encoding="utf-8") as f:
        factura_json = json.load(f)

    # Sobrescribir env si se pasó como argumento CLI
    if env_override:
        factura_json["env"] = env_override

    # Emitir
    afip = AfipFacturacion(config, base_dir=base_dir)
    result = afip.emitir_factura(factura_json)

    if result:
        print(f"\n{'='*50}")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        pdf_path = afip.generar_pdf(result)
        if pdf_path:
            print(f"\n📎 PDF generado: {pdf_path}")
