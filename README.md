# facturacion-arca

Módulo de facturación electrónica AFIP/ARCA para Python, con API REST construida en FastAPI. Permite emitir Facturas A/B/C, Notas de Crédito y Notas de Débito en entornos de homologación y producción.

---

## Stack

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| API | FastAPI + Uvicorn |
| Firma digital | `cryptography` (Python) |
| Web Services AFIP | WSAA (autenticación) + WSFE (facturación electrónica) |
| Infraestructura | EC2 Ubuntu |

---

## Requisitos previos

1. **Certificado digital ARCA**
   - Generado desde el portal ARCA con `CN=Computadores` (o el CN correspondiente)
   - Habilitado para el servicio `wsfe` en producción
   - Archivos necesarios: `certificado_prod.crt` y `privada_prod.key`

2. **Punto de venta habilitado en AFIP**
   - Tipo: RECE para web services
   - En este proyecto: Punto de Venta `3`

3. **Python 3.10+** con entorno virtual

---

## Instalación

```bash
# Clonar el repo
git clone https://github.com/develophff-code/facturacion-arca.git
cd facturacion-arca

# Crear y activar entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

---

## Configuración

### Certificados

Colocar los certificados en `/var/www/facturacion-arca/afip_certs/`:

```
afip_certs/
├── certificado_prod.crt   # Certificado ARCA producción
├── privada_prod.key       # Clave privada producción
├── certificado_homo.crt   # Certificado ARCA homologación
└── privada_homo.key       # Clave privada homologación
```

Para copiar los certificados de homo a prod (si el certificado fue generado como producción):

```bash
cp afip_certs/certificado_homo.crt afip_certs/certificado_prod.crt
cp afip_certs/privada_homo.key     afip_certs/privada_prod.key
```

### API Key

Cambiar la clave por defecto en la configuración antes de exponer la API:

```python
# En main.py o en variable de entorno
API_KEY = "tu-clave-segura-aqui"
```

---

## Uso

### Iniciar el servidor

```bash
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8001
```

### Emitir una Factura A (concepto: productos)

```bash
curl -s -X POST http://127.0.0.1:8001/facturar \
  -H "Content-Type: application/json" \
  -H "X-API-Key: tu-clave-segura-aqui" \
  -d '{
    "env": "prod",
    "tipo_comprobante": 1,
    "punto_venta": 3,
    "concepto": 1,
    "fecha_emision": "2026-05-25",
    "condicion_venta": "Contado",
    "receptor": {
      "nombre": "CAMPODONICO ROBERTO EMILIO",
      "cuit": "20203031514",
      "condicion_iva": 1,
      "domicilio": "Entre Rios Sur 219 - San Juan"
    },
    "items": [
      {
        "descripcion": "Prueba de servicio",
        "cantidad": 1,
        "precio_unitario": 1.00,
        "alicuota_iva_id": 5
      }
    ]
  }' | python3 -m json.tool
```

### Respuesta exitosa

```json
{
  "status": "aprobada",
  "receptor": {
    "nombre": "CAMPODONICO ROBERTO EMILIO",
    "cuit": "20203031514",
    "condicion_iva": 1,
    "domicilio": "Entre Rios Sur 219 - San Juan"
  },
  "items": [...],
  "monto_total": 1.21,
  "imp_neto": 1.0,
  "imp_iva": 0.21,
  "comprobante_nro": 1,
  "punto_venta": 3,
  "tipo_comprobante": 1,
  "cae": "86216948117573",
  "cae_vto": "20260604",
  "fecha_emision": "20260525",
  "condicion_venta": "Contado",
  "comprobante_asociado": null
}
```

---

## Endpoints

### `POST /facturar`

Emite un comprobante electrónico y devuelve el CAE asignado por AFIP.

**Headers requeridos:**

| Header | Valor |
|---|---|
| `Content-Type` | `application/json` |
| `X-API-Key` | Clave configurada en el servidor |

**Body — campos principales:**

| Campo | Tipo | Descripción |
|---|---|---|
| `env` | string | `"prod"` o `"homo"` |
| `tipo_comprobante` | int | 1=Factura A, 6=Factura B, 11=Factura C |
| `punto_venta` | int | Número de punto de venta habilitado |
| `concepto` | int | 1=Productos, 2=Servicios, 3=Productos y Servicios |
| `fecha_emision` | string | Formato `YYYY-MM-DD` |
| `condicion_venta` | string | Ej: `"Contado"` |
| `receptor` | object | Ver estructura abajo |
| `items` | array | Ver estructura abajo |

**Estructura `receptor`:**

```json
{
  "nombre": "Razón social o nombre",
  "cuit": "20203031514",
  "condicion_iva": 1,
  "domicilio": "Calle 123 - Ciudad"
}
```

**Estructura `items`:**

```json
{
  "descripcion": "Descripción del producto o servicio",
  "cantidad": 1,
  "precio_unitario": 100.00,
  "alicuota_iva_id": 5
}
```

**Alicuotas IVA disponibles (`alicuota_iva_id`):**

| Id | Tasa |
|---|---|
| 3 | 0% |
| 4 | 10.5% |
| 5 | 21% |
| 6 | 27% |
| 8 | 5% |
| 9 | 2.5% |

---

## Notas técnicas AFIP

- Los campos `FchServDesde`, `FchServHasta` y `FchVtoPago` **solo se envían cuando `concepto` es 2 o 3**. Para concepto 1 (productos) AFIP los rechaza.
- El objeto `Iva` es obligatorio cuando `ImpNeto > 0`. El módulo lo construye automáticamente agrupando items por alicuota.
- El token WSAA tiene validez de 12 horas. El módulo cachea el token y lo renueva automáticamente.
- Los comprobantes asociados (para NC y ND) se construyen con `_build_cbtes_asoc`.

---

## Branches

| Branch | Descripción |
|---|---|
| `main` | Producción estable |
| `develop` | Desarrollo — se mergea a main antes de cada deploy |

---

## Seguridad — checklist antes de producción

- [ ] Cambiar `API_KEY` por una clave segura
- [ ] Exponer la API detrás de nginx con HTTPS (no exponer el puerto 8001 directo)
- [ ] Persistir cada CAE emitido en base de datos
- [ ] Rotar certificados antes de su vencimiento
- [ ] Restringir acceso SSH a IPs conocidas en el Security Group de EC2

---

## Licencia

Uso interno. No distribuir sin autorización.
