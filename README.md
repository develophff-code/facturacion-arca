# afip-facturacion

Sistema de facturación electrónica para [ARCA/AFIP](https://www.afip.gob.ar/) (Argentina). Genera comprobantes electrónicos (Factura C, B, A, Notas de Crédito/Débito) via Web Services WSFEv1 y produce PDFs en formato oficial.

## Características

- Autenticación WSAA con caché automático de tokens (~12hs)
- Facturación via WSFEv1 (Factura Electrónica v1)
- Generación de PDF en formato idéntico al oficial de ARCA/AFIP
- 3 copias por comprobante: ORIGINAL, DUPLICADO, TRIPLICADO
- QR code según RG 4291
- Soporte para entorno de homologación y producción
- Configuración externalizada en JSON (sin hardcodear datos)

## Requisitos

- Python 3.8+
- OpenSSL (para firmar tickets WSAA)
- Certificado digital de AFIP ([cómo obtenerlo](https://www.afip.gob.ar/ws/WSAA/wsaa_obtener_certificado_produccion.pdf))

```bash
pip install -r requirements.txt
```

## Setup inicial (una sola vez)

Antes de poder facturar necesitás hacer un setup en el sitio de ARCA/AFIP. Son ~15 minutos.

### 1. Generar clave privada y CSR

```bash
# Generar clave privada RSA 2048
openssl genrsa -out afip_certs/privada_prod.key 2048

# Generar pedido de certificado (CSR)
# IMPORTANTE: en "Common Name" poné tu CUIT (ej: 20123456789)
openssl req -new -key afip_certs/privada_prod.key -out afip_certs/pedido_prod.csr -subj "/C=AR/O=TU NOMBRE/CN=TU_CUIT/serialNumber=CUIT TU_CUIT"
```

### 2. Obtener certificado en AFIP

1. Entrá a [AFIP con clave fiscal](https://auth.afip.gob.ar/contribuyente_/login.xhtml)
2. Buscá el servicio **"Administración de Certificados Digitales"**
   - Si no lo tenés, agregalo desde "Administrador de Relaciones de Clave Fiscal"
3. Dentro del servicio:
   - Hacé click en **"Agregar alias / Crear certificado"**
   - Alias: poné un nombre descriptivo (ej: "facturacion-ws")
   - Pegá el contenido del archivo `pedido_prod.csr`
   - Confirmá y descargá el certificado generado
4. Guardá el certificado como `afip_certs/certificado_prod.crt`

### 3. Habilitar punto de venta para Web Services

1. Entrá a [Comprobantes en Línea (RCEL)](https://fe.afip.gob.ar/rcel/jsp/index.jsp) con clave fiscal
2. Seleccioná tu empresa
3. Andá a **"ABM de Puntos de Venta"** (en el menú de la izquierda)
4. Hacé click en **"Agregar"**
5. Elegí:
   - Número de punto de venta (ej: 3)
   - Sistema: **"Web Services / RECE"** (no "Factura en Línea")
   - Domicilio: seleccioná tu domicilio fiscal
6. Confirmá

### 4. Asociar certificado al Web Service

1. Entrá a **"Administración de Certificados Digitales"** de nuevo
2. Seleccioná el certificado que creaste (el alias)
3. Hacé click en **"Agregar relación"** o **"Autorizar WS"**
4. Buscá y seleccioná el servicio **"wsfe"** (Factura Electrónica)
5. Confirmá

### 5. Configurar el proyecto

```bash
cp config.example.json config.json
```

Editá `config.json` con tus datos reales: CUIT, razón social, domicilio, condición IVA, número de punto de venta, rutas a los certificados, y tus clientes.

### 6. Probar en homologación (opcional)

Para probar sin generar facturas reales, repetí los pasos 1-4 pero usando los endpoints de homologación. La clave privada puede ser la misma, pero el certificado se genera en el [entorno de testing de AFIP](https://wsaahomo.afip.gov.ar/).

```bash
python afip_facturacion.py ejemplo 100 homo
```

### 7. Primera factura real

```bash
python afip_facturacion.py tu_cliente 100000 prod
```

Si ves `✅ FACTURA APROBADA` con un CAE, todo está funcionando.

## Uso

```bash
# Homologación (testing)
python afip_facturacion.py ejemplo 100000 homo

# Producción
python afip_facturacion.py ejemplo 1500000 prod
```

El script autentica, genera la factura, obtiene el CAE, y produce el PDF automáticamente en `output/`.

## Estructura

```
afip-facturacion/
├── afip_facturacion.py      # Script principal (auth + facturación + PDF)
├── generar_pdf_html.py      # Motor de generación de PDF
├── factura_template.html    # Template HTML formato oficial AFIP
├── config.example.json      # Configuración de ejemplo
├── config.json              # Tu configuración (no se sube a git)
├── requirements.txt         # Dependencias Python
├── afip_certs/              # Certificados (no se suben a git)
│   ├── certificado_prod.crt
│   └── privada_prod.key
└── output/                  # PDFs generados (no se suben a git)
```

## Tipos de comprobante soportados

| Código | Letra | Tipo |
|--------|-------|------|
| 1 | A | Factura |
| 6 | B | Factura |
| 11 | C | Factura |
| 2 / 7 / 12 | A / B / C | Nota de Débito |
| 3 / 8 / 13 | A / B / C | Nota de Crédito |

## Licencia

MIT
