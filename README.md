# Facturación Electrónica ARCA/AFIP — Módulo Python

Módulo reutilizable para emitir comprobantes electrónicos (Facturas A, B y C, Notas de Crédito y Débito) a través del servicio WSFEv1 de ARCA/AFIP. Diseñado para integrarse como microservicio en otros sistemas mediante una API REST.

---

## Características

- Emisión de Facturas A, B y C
- Emisión de Notas de Crédito y Débito con comprobante asociado
- Discriminación de IVA por alícuota (0%, 2,5%, 5%, 10,5%, 21%, 27%)
- Generación de PDF con formato oficial ARCA
- Caché automático de token WSAA (~12 hs)
- Recibe los datos de cada factura vía JSON
- Usable como módulo importable o desde CLI

---

## Estructura del proyecto

```
afip-facturacion/
├── afip_facturacion.py       # Módulo principal — clase AfipFacturacion
├── generar_pdf_html.py       # Generador de PDF a partir del template HTML
├── factura_template.html     # Template Jinja2 con formato oficial ARCA
├── main.py                   # API FastAPI (para despliegue como servicio)
├── config.json               # Datos del emisor y rutas a certificados (no commitear)
├── config.example.json       # Ejemplo de config sin datos sensibles
├── requirements.txt          # Dependencias Python
├── afip_certs/
│   ├── certificado_homo.crt  # Certificado de homologación
│   ├── privada_homo.key      # Clave privada de homologación
│   ├── certificado_prod.crt  # Certificado de producción
│   ├── privada_prod.key      # Clave privada de producción
│   ├── token_cache_homo.json # Generado automáticamente
│   └── token_cache_prod.json # Generado automáticamente
└── output/                   # PDFs generados
```

> ⚠️ `config.json` y `afip_certs/*.key` **nunca deben commitearse**. Están incluidos en `.gitignore`.

---

## Requisitos

- Python 3.11+
- OpenSSL instalado en el sistema
- Certificado digital AFIP (homologación y/o producción)

### Dependencias del sistema (Ubuntu/Debian)

```bash
sudo apt install python3-dev libxml2-dev libxslt1-dev gcc libssl-dev
```

### Dependencias del sistema (Fedora)

```bash
sudo dnf install python3-devel libxml2-devel libxslt-devel gcc openssl-devel
```

---

## Instalación

```bash
git clone https://github.com/tu-usuario/afip-facturacion
cd afip-facturacion

python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

---

## Configuración

Copiá el ejemplo y completá con tus datos:

```bash
cp config.example.json config.json
```

### Estructura de `config.json`

```json
{
  "emisor": {
    "cuit":                      "20123456789",
    "razon_social":              "MI EMPRESA SRL",
    "domicilio":                 "Av. San Martín 1234 - Mendoza",
    "condicion_iva":             "IVA Responsable Inscripto",
    "ingresos_brutos":           "20123456789",
    "fecha_inicio_actividades":  "01/01/2020"
  },
  "punto_venta":       1,
  "tipo_comprobante":  11,
  "concepto":          2,
  "certificados": {
    "homo": {
      "cert": "afip_certs/certificado_homo.crt",
      "key":  "afip_certs/privada_homo.key"
    },
    "prod": {
      "cert": "afip_certs/certificado_prod.crt",
      "key":  "afip_certs/privada_prod.key"
    }
  }
}
```

**Campos del emisor:**

| Campo | Descripción |
|---|---|
| `cuit` | CUIT del emisor sin guiones |
| `razon_social` | Nombre o razón social |
| `domicilio` | Domicilio fiscal |
| `condicion_iva` | Texto a mostrar en el PDF |
| `ingresos_brutos` | Número de IIBB |
| `fecha_inicio_actividades` | Fecha en formato `DD/MM/YYYY` |

**Otros campos:**

| Campo | Descripción |
|---|---|
| `punto_venta` | Número de punto de venta habilitado en AFIP |
| `tipo_comprobante` | Tipo por defecto (se puede sobrescribir por factura) |
| `concepto` | 1 = Productos, 2 = Servicios, 3 = Productos y Servicios |

---

## Uso como módulo

```python
from afip_facturacion import AfipFacturacion
import json

with open("config.json") as f:
    config = json.load(f)

afip = AfipFacturacion(config, base_dir="/ruta/proyecto")

factura = { ... }   # ver schema más abajo

resultado = afip.emitir_factura(factura)

if resultado:
    pdf_path = afip.generar_pdf(resultado)
    print(f"CAE: {resultado['cae']}")
    print(f"PDF: {pdf_path}")
```

---

## Schema del JSON de factura

### Factura A — 2 ítems con IVA 21%

```json
{
  "env":               "homo",
  "tipo_comprobante":  1,
  "punto_venta":       2,
  "concepto":          1,
  "fecha_emision":     "2026-05-23",
  "condicion_venta":   "Contado",

  "receptor": {
    "nombre":        "CAMPODONICO ROBERTO EMILIO",
    "cuit":          "20203031514",
    "condicion_iva": 1,
    "domicilio":     "Entre Rios (Sur) 219 - San Juan, San Juan"
  },

  "items": [
    {
      "codigo":           "LAV01",
      "descripcion":      "Lavandina",
      "cantidad":         5,
      "precio_unitario":  578.51,
      "unidad":           "litros",
      "alicuota_iva_id":  5
    },
    {
      "codigo":           "DES01",
      "descripcion":      "Desengrasante",
      "cantidad":         5,
      "precio_unitario":  1404.96,
      "unidad":           "litros",
      "alicuota_iva_id":  5
    }
  ]
}
```

### Factura C — Monotributo (sin IVA)

```json
{
  "env":               "homo",
  "tipo_comprobante":  11,
  "receptor": {
    "nombre":        "GARCIA JUAN CARLOS",
    "cuit":          "23123456789",
    "condicion_iva": 5
  },
  "items": [
    {
      "descripcion":     "Servicio de desarrollo web - Mayo 2026",
      "cantidad":        1,
      "precio_unitario": 150000.00
    }
  ]
}
```

> Para Factura C no hace falta `alicuota_iva_id` — el módulo fuerza 0% automáticamente.

### Nota de Crédito A — para anular una Factura A

```json
{
  "env":               "homo",
  "tipo_comprobante":  3,
  "punto_venta":       2,
  "concepto":          1,
  "fecha_emision":     "2026-05-23",

  "comprobante_asociado": {
    "tipo":        1,
    "punto_venta": 2,
    "numero":      158,
    "fecha":       "2026-05-23",
    "cuit_emisor": "20124329362"
  },

  "receptor": {
    "nombre":        "CAMPODONICO ROBERTO EMILIO",
    "cuit":          "20203031514",
    "condicion_iva": 1,
    "domicilio":     "Entre Rios (Sur) 219 - San Juan, San Juan"
  },

  "items": [
    {
      "descripcion":     "Anulación — Lavandina (NC Fac. A 00002-00000158)",
      "cantidad":        5,
      "precio_unitario": 578.51,
      "unidad":          "litros",
      "alicuota_iva_id": 5
    },
    {
      "descripcion":     "Anulación — Desengrasante (NC Fac. A 00002-00000158)",
      "cantidad":        5,
      "precio_unitario": 1404.96,
      "unidad":          "litros",
      "alicuota_iva_id": 5
    }
  ]
}
```

### Referencia de campos

**Raíz del JSON:**

| Campo | Requerido | Descripción |
|---|---|---|
| `env` | No | `"homo"` o `"prod"`. Default: `"homo"` |
| `tipo_comprobante` | No | Ver tabla de tipos. Default: valor en `config.json` |
| `punto_venta` | No | Default: valor en `config.json` |
| `concepto` | No | 1=Productos, 2=Servicios, 3=Ambos. Default: config |
| `fecha_emision` | No | `YYYY-MM-DD`. Default: hoy |
| `condicion_venta` | No | Texto libre. Default: `"Contado"` |
| `comprobante_asociado` | Sí (NC/ND) | Requerido para Notas de Crédito y Débito |

**Receptor:**

| Campo | Requerido | Descripción |
|---|---|---|
| `nombre` | Sí | Razón social o apellido y nombre |
| `cuit` | Sí | CUIT sin guiones |
| `condicion_iva` | Sí | Código AFIP: 1=RI, 4=Exento, 5=CF, 6=Monotributo |
| `domicilio` | No | Domicilio comercial |

**Ítems:**

| Campo | Requerido | Descripción |
|---|---|---|
| `descripcion` | Sí | Descripción del producto o servicio |
| `cantidad` | Sí | Cantidad (acepta decimales) |
| `precio_unitario` | Sí | Precio unitario sin IVA |
| `alicuota_iva_id` | No | Código AFIP de alícuota (ver tabla). Default: 3 (0%) |
| `codigo` | No | Código interno del producto |
| `unidad` | No | Unidad de medida. Default: `"unidades"` |
| `bonificacion_pct` | No | % de bonificación. Default: 0 |

**Alícuotas de IVA:**

| `alicuota_iva_id` | Alícuota |
|---|---|
| 3 | 0% (Monotributo, exentos) |
| 4 | 10,5% |
| 5 | 21% |
| 6 | 27% |
| 8 | 5% |
| 9 | 2,5% |

**Tipos de comprobante:**

| Código | Tipo |
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

## Uso desde CLI

```bash
source .venv/bin/activate
python afip_facturacion.py factura.json homo
```

El segundo argumento sobrescribe el campo `env` del JSON.

---

## API REST (FastAPI)

El archivo `main.py` expone el módulo como servicio HTTP:

```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

**Endpoint:**

```
POST /facturar
Content-Type: application/json
X-API-Key: tu-api-key-secreta

{ ...json de factura... }
```

**Respuesta exitosa:**

```json
{
  "status":           "aprobada",
  "comprobante_nro":  158,
  "punto_venta":      2,
  "tipo_comprobante": 1,
  "cae":              "86216714039771",
  "cae_vto":          "20260602",
  "monto_total":      24000.05,
  "imp_neto":         19834.75,
  "imp_iva":          4165.30,
  "fecha_emision":    "20260523"
}
```

---

## Despliegue en servidor (Ubuntu con Apache)

### 1. Clonar y configurar

```bash
cd /var/www
git clone https://github.com/tu-usuario/afip-facturacion
cd afip-facturacion
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# Completar config.json y copiar certificados a afip_certs/
```

### 2. Servicio systemd

Crear `/etc/systemd/system/afip-facturacion.service`:

```ini
[Unit]
Description=AFIP Facturación API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/afip-facturacion
ExecStart=/var/www/afip-facturacion/.venv/bin/gunicorn \
    -w 2 -k uvicorn.workers.UvicornWorker \
    -b 127.0.0.1:8001 main:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable afip-facturacion
sudo systemctl start afip-facturacion
```

### 3. VirtualHost Apache

```apache
<VirtualHost *:443>
    ServerName afip.tu-dominio.com

    ProxyPass        / http://127.0.0.1:8001/
    ProxyPassReverse / http://127.0.0.1:8001/

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/tu-dominio.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/tu-dominio.com/privkey.pem
</VirtualHost>
```

```bash
sudo a2enmod proxy proxy_http ssl
sudo systemctl reload apache2
```

### 4. SSL con Certbot

```bash
sudo certbot --apache -d afip.tu-dominio.com
```

---

## Integración desde otra app (ejemplo fetch)

```javascript
const response = await fetch("https://afip.tu-dominio.com/facturar", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key":    process.env.AFIP_API_KEY
  },
  body: JSON.stringify(facturaJson)
});

const resultado = await response.json();
console.log(resultado.cae);
```

---

## Notas importantes

- Los certificados de **homologación** y **producción** son distintos y se obtienen por separado desde el portal de AFIP.
- El punto de venta también debe habilitarse en el entorno de homologación por separado.
- El caché de token se renueva automáticamente al vencer (~12 hs). No requiere intervención manual.
- Los PDFs se guardan en `output/` con el nombre `{cuit}_{tipo}_{ptoVta}_{nro}.pdf`.

---

## Roadmap

- [ ] Soporte para ítems con múltiples alícuotas de IVA en la misma factura
- [ ] Endpoint para consulta de comprobante por número
- [ ] Migración a AWS Lambda (reemplazando `subprocess openssl` por `cryptography` puro Python)
- [ ] Soporte para otros tributos (percepciones provinciales, municipales)
