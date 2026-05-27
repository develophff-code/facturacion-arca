from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, model_validator
from typing import Optional, List
import json
import os
import glob
import traceback

from afip_facturacion import AfipFacturacion

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY  = os.environ.get("AFIP_API_KEY", "cambiar-esta-clave")

with open(os.path.join(BASE_DIR, "config.json")) as f:
    config = json.load(f)

afip = AfipFacturacion(config, base_dir=BASE_DIR)

# ── Schemas ───────────────────────────────────────────────────────────────────

class ItemFactura(BaseModel):
    descripcion:      str
    cantidad:         float
    precio_unitario:  float
    unidad:           str   = "unidades"
    codigo:           str   = ""
    bonificacion_pct: float = 0.0
    # Código AFIP de alícuota IVA:
    #   3=0%  4=10,5%  5=21%  6=27%  8=5%  9=2,5%
    # Para Monotributo (FC tipo 11/12/13) se ignora; siempre queda en 0%.
    alicuota_iva_id:  int   = 3


class ReceptorFactura(BaseModel):
    nombre:        str
    cuit:          str
    condicion_iva: int = 5   # 1=RI  4=Exento  5=CF  6=Monotributo...
    domicilio:     str = ""


class FacturaRequest(BaseModel):
    # Ambiente
    env:              str = "prod"
    # Tipo de comprobante AFIP:
    #   1=FA  6=FB  11=FC  3=NCA  8=NCB  13=NCC  2=NDA  7=NDB  12=NDC
    tipo_comprobante: int

    # Punto de Venta
    punto_venta:      int = 3

    # 1=Productos  2=Servicios  3=Productos y Servicios
    concepto: int = 1

    receptor:        ReceptorFactura
    items:           List[ItemFactura]
    condicion_venta: str = "Contado"

    # Obligatorios para concepto 2 o 3 (formato YYYYMMDD)
    fch_serv_desde: Optional[str] = None
    fch_serv_hasta: Optional[str] = None
    fch_vto_pago:   Optional[str] = None

    @model_validator(mode="after")
    def validar_campos_servicio(self):
        if self.concepto in (2, 3):
            faltantes = [
                campo
                for campo, valor in [
                    ("fch_serv_desde", self.fch_serv_desde),
                    ("fch_serv_hasta", self.fch_serv_hasta),
                    ("fch_vto_pago",   self.fch_vto_pago),
                ]
                if not valor
            ]
            if faltantes:
                raise ValueError(
                    f"concepto={self.concepto} requiere los campos: {', '.join(faltantes)}"
                )
        return self

    @model_validator(mode="after")
    def validar_items_no_vacios(self):
        if not self.items:
            raise ValueError("La factura debe tener al menos un ítem")
        return self


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Facturación ARCA", docs_url=None, redoc_url=None)
api_key_header = APIKeyHeader(name="X-API-Key")


def verificar_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="API key inválida")
    return key


# ── Helpers ───────────────────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def _emitir(factura: FacturaRequest) -> dict:
    """Convierte el schema Pydantic a dict y llama a afip.emitir_factura."""
    payload = factura.model_dump()
    resultado = afip.emitir_factura(payload)
    if resultado is None:
        raise HTTPException(status_code=400, detail="Factura rechazada por AFIP/ARCA")
    return resultado


def _buscar_pdf(punto_venta: int, nro_cbte: int) -> str | None:
    """
    Localiza el PDF en output/ por PV y número de comprobante.
    El nombre tiene el patrón: {cuit}_{cod}_{pv:05}_{nro:08}.pdf
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pv_str  = str(punto_venta).zfill(5)
    nro_str = str(nro_cbte).zfill(8)
    patron  = os.path.join(OUTPUT_DIR, f"*_{pv_str}_{nro_str}.pdf")
    matches = glob.glob(patron)
    return matches[0] if matches else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/facturar")
def facturar(factura: FacturaRequest, _: str = Depends(verificar_api_key)):
    """
    Emite un comprobante en ARCA y devuelve el resultado con CAE.
    No genera PDF.
    """
    try:
        return _emitir(factura)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/facturar/pdf")
def facturar_con_pdf(factura: FacturaRequest, _: str = Depends(verificar_api_key)):
    """
    Emite un comprobante en ARCA y genera el PDF.
    Devuelve el resultado con CAE + pdf_path.
    Si el PDF falla el CAE ya es válido — no se hace rollback.
    """
    try:
        resultado = _emitir(factura)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    # PDF es best-effort: el CAE ya está aprobado aunque falle
    try:
        pdf_path = afip.generar_pdf(resultado, output_dir=OUTPUT_DIR)
        resultado["pdf_path"] = pdf_path
    except Exception as e:
        traceback.print_exc()
        resultado["pdf_path"] = None
        resultado["pdf_error"] = str(e)

    return resultado


@app.get("/factura/{punto_venta}/{nro_cbte}/pdf")
def descargar_pdf(
    punto_venta: int,
    nro_cbte:    int,
    _: str = Depends(verificar_api_key),
):
    """
    Descarga el PDF de un comprobante ya generado.
    Útil para reimpresión sin volver a llamar a AFIP.

    Ejemplo: GET /factura/3/42/pdf
    """
    pdf_path = _buscar_pdf(punto_venta, nro_cbte)
    if not pdf_path:
        raise HTTPException(
            status_code=404,
            detail=f"PDF no encontrado para PV={punto_venta} / NRO={nro_cbte}. "
                   "Generalo primero con POST /facturar/pdf",
        )
    filename = os.path.basename(pdf_path)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
    )
