from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
import json
import os

from afip_facturacion import AfipFacturacion

# ── Config ────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
API_KEY    = os.environ.get("AFIP_API_KEY", "cambiar-esta-clave")

with open(os.path.join(BASE_DIR, "config.json")) as f:
    config = json.load(f)

afip = AfipFacturacion(config, base_dir=BASE_DIR)

# ── App ───────────────────────────────────────────────────
app        = FastAPI(title="Facturación ARCA", docs_url=None, redoc_url=None)
api_key_header = APIKeyHeader(name="X-API-Key")

def verificar_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="API key inválida")
    return key

# ── Endpoints ─────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/facturar")
def facturar(factura: dict, _: str = Depends(verificar_api_key)):
    try:
        resultado = afip.emitir_factura(factura)
        if resultado is None:
            raise HTTPException(status_code=400, detail="Factura rechazada por AFIP")
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/facturar/pdf")
def facturar_con_pdf(factura: dict, _: str = Depends(verificar_api_key)):
    try:
        resultado = afip.emitir_factura(factura)
        if resultado is None:
            raise HTTPException(status_code=400, detail="Factura rechazada por AFIP")
        pdf_path = afip.generar_pdf(resultado)
        resultado["pdf_path"] = pdf_path
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
