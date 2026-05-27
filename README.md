# facturacion-arca

API REST para emisión electrónica de comprobantes fiscales (Facturas A/B/C, Notas de Crédito y Notas de Débito) contra los webservices de ARCA (ex-AFIP), con persistencia de CAE en PostgreSQL y generación de PDF.

**Producción:** `https://facturacion.chopperdigital.online`

---

## Stack

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| API | FastAPI + Uvicorn |
| Autenticación ARCA | WSAA (token/sign) |
| Facturación electrónica | WSFE |
| Firma digital | `cryptography` (Python) |
| Base de datos | PostgreSQL · base `facturacion` · tabla `comprobantes_afip` |
| Servidor | EC2 Ubuntu · Apache2 (reverse proxy + HTTPS) |
| Virtualenv | `/var/www/facturacion-arca/.venv` |
| Servicio | systemd `facturacion-arca` |

---

## Requisitos previos

1. **Certificado digital ARCA**
   - Generado desde el portal ARCA con `CN=Computadores`
   - Habilitado para el servicio `wsfe` en producción
   - Archivos: `certificado_prod.crt` y `privada_prod.key`

2. **Punto de venta habilitado en ARCA**
   - Tipo: RECE para web services
   - En este proyecto: Punto de Venta `3`

3. **PostgreSQL** con la base `facturacion` creada

4. **Python 3.10+**

---

## Instalación

```bash
git clone https://github.com/develophff-code/facturacion-arca.git
cd facturacion-arca

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Configuración

### Variables de entorno

Crear un archivo `.env` en la raíz del proyecto:

```env
AFIP_API_KEY=tu-clave-secura-aqui
DATABASE_URL=postgresql://usuario:password@localhost/facturacion
```

La API Key se lee en runtime desde esta variable. **No hardcodear en el código.**

### Certificados

Colocar los certificados en `/var/www/facturacion-arca/afip_certs/`:

```
afip_certs/
├── certificado_prod.crt
├── privada_prod.key
├── certificado_homo.crt
└── privada_homo.key
```

---

## Gestión del servicio en producción

```bash
# Estado
sudo systemctl status facturacion-arca

# Reiniciar tras cambios
sudo systemctl restart facturacion-arca

# Logs en tiempo real
sudo journalctl -u facturacion-arca -f
```

---

## Autenticación

Todos los endpoints (excepto `/health`) requieren el header:

```
X-API-Key: <valor de AFIP_API_KEY>
```

---

## Endpoints

### `GET /health`

Verifica que el servicio esté activo. No requiere autenticación.

**Response `200`**
```json
{ "status": "ok" }
```

---

### `POST /facturar`

Emite un comprobante electrónico contra ARCA, persiste el CAE en PostgreSQL y devuelve los datos del comprobante aprobado.

**Headers**

| Header | Valor |
|---|---|
| `Content-Type` | `application/json` |
| `X-API-Key` | API Key configurada en `.env` |

**Body**

```json
{
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
      "descripcion": "Servicio de desarrollo web",
      "cantidad": 1,
      "precio_unitario": 100.00,
      "alicuota_iva_id": 5
    }
  ]
}
```

**Campos del body**

| Campo | Tipo | Descripción |
|---|---|---|
| `env` | string | `"prod"` o `"homo"` |
| `tipo_comprobante` | int | Ver tabla de tipos abajo |
| `punto_venta` | int | Punto de venta habilitado en ARCA |
| `concepto` | int | 1=Productos, 2=Servicios, 3=Productos y Servicios |
| `fecha_emision` | string | Formato `YYYY-MM-DD` |
| `condicion_venta` | string | Ej: `"Contado"`, `"30 días"` |
| `receptor` | object | Ver estructura abajo |
| `items` | array | Ver estructura abajo |
| `comprobante_asociado` | object | Solo para NC/ND — ver sección correspondiente |

**Estructura `receptor`**

| Campo | Tipo | Descripción |
|---|---|---|
| `nombre` | string | Razón social o nombre del receptor |
| `cuit` | string | CUIT sin guiones |
| `condicion_iva` | int | 1=Responsable Inscripto, 4=Exento, 5=Consumidor Final, 6=Monotributista |
| `domicilio` | string | Dirección completa |

**Estructura `items`**

| Campo | Tipo | Descripción |
|---|---|---|
| `descripcion` | string | Descripción del producto o servicio |
| `cantidad` | int/float | Cantidad |
| `precio_unitario` | float | Precio unitario sin IVA |
| `alicuota_iva_id` | int | Ver tabla de alícuotas abajo |

**Alícuotas IVA**

| `alicuota_iva_id` | Tasa |
|---|---|
| 3 | 0% |
| 4 | 10.5% |
| 5 | 21% |
| 6 | 27% |
| 8 | 5% |
| 9 | 2.5% |

**Response `200`**

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
  "monto_total": 121.00,
  "imp_neto": 100.00,
  "imp_iva": 21.00,
  "comprobante_nro": 25,
  "punto_venta": 3,
  "tipo_comprobante": 1,
  "cae": "86216948117573",
  "cae_vto": "20260604",
  "fecha_emision": "20260525",
  "condicion_venta": "Contado",
  "comprobante_asociado": null
}
```

**Ejemplo con curl**

```bash
curl -s -X POST https://facturacion.chopperdigital.online/facturar \
  -H "Content-Type: application/json" \
  -H "X-API-Key: tu-api-key" \
  -d '{
    "env": "prod",
    "tipo_comprobante": 1,
    "punto_venta": 3,
    "concepto": 1,
    "fecha_emision": "2026-05-25",
    "condicion_venta": "Contado",
    "receptor": {
      "nombre": "EMPRESA CLIENTE SA",
      "cuit": "30712345678",
      "condicion_iva": 1,
      "domicilio": "Av. Corrientes 1234 - CABA"
    },
    "items": [
      {
        "descripcion": "Desarrollo de software",
        "cantidad": 1,
        "precio_unitario": 500.00,
        "alicuota_iva_id": 5
      }
    ]
  }' | python3 -m json.tool
```

---

### `POST /facturar/pdf`

Emite el comprobante electrónico, persiste el CAE y devuelve directamente el PDF del comprobante. El PDF incluye el nombre de fantasía **Chopper Digital**.

**Headers y body:** idénticos a `POST /facturar`.

**Response `200`**

```
Content-Type: application/pdf
Content-Disposition: attachment; filename="factura_3_25.pdf"
```

Archivo PDF listo para descargar o imprimir.

---

### `GET /factura/{pto_venta}/{nro}/pdf`

Recupera el PDF de un comprobante previamente emitido, reconstruyéndolo a partir de los datos persistidos en PostgreSQL.

**Path params**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `pto_venta` | int | Punto de venta |
| `nro` | int | Número de comprobante |

**Ejemplo**

```bash
curl -O -J https://facturacion.chopperdigital.online/factura/3/25/pdf \
  -H "X-API-Key: tu-api-key"
```

**Response `200`**
```
Content-Type: application/pdf
```

**Response `404`**
```json
{ "detail": "Comprobante no encontrado" }
```

---

## Tipos de comprobante — referencia completa

| Código | Descripción |
|---|---|
| 1 | Factura A |
| 2 | Nota de Débito A |
| 3 | Nota de Crédito A |
| 6 | Factura B |
| 7 | Nota de Débito B |
| 8 | Nota de Crédito B |
| 11 | Factura C |
| 12 | Nota de Débito C |
| 13 | Nota de Crédito C |

---

## Emisión de Notas de Crédito y Débito

Para emitir una NC o ND se usa el mismo endpoint `POST /facturar` o `POST /facturar/pdf`, indicando el tipo de comprobante correspondiente y agregando el campo `comprobante_asociado` con los datos de la factura original:

```json
{
  "env": "prod",
  "tipo_comprobante": 3,
  "punto_venta": 3,
  "concepto": 1,
  "fecha_emision": "2026-05-25",
  "condicion_venta": "Contado",
  "receptor": { ... },
  "items": [ ... ],
  "comprobante_asociado": {
    "tipo_comprobante": 1,
    "punto_venta": 3,
    "nro_comprobante": 10
  }
}
```

---

## Notas técnicas ARCA

- `FchServDesde`, `FchServHasta` y `FchVtoPago` **solo se envían cuando `concepto` es 2 o 3**. Para concepto 1 (productos) ARCA los rechaza.
- El objeto `Iva` es obligatorio cuando `ImpNeto > 0`. Se construye automáticamente agrupando items por alícuota.
- El token WSAA tiene validez de 12 horas. El módulo cachea el token y lo renueva automáticamente.

---

## Branches

| Branch | Descripción |
|---|---|
| `main` | Producción estable |
| `develop` | Desarrollo — se mergea a main antes de cada deploy |

---

## Checklist de producción

- [x] API Key cargada desde variable de entorno (`AFIP_API_KEY` en `.env`)
- [x] API expuesta vía Apache2 con HTTPS (certificado SSL activo)
- [x] CAE persistido en PostgreSQL tras cada emisión
- [x] Servicio administrado por systemd (`facturacion-arca`)
- [ ] Rotar certificados ARCA antes de su vencimiento
- [ ] Restringir acceso SSH a IPs conocidas en el Security Group de EC2

---

## Licencia

Uso interno — Chopper Digital. No distribuir sin autorización.
