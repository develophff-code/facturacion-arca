# Agent Instructions — AFIP Facturación Electrónica

You are controlling a billing system for Argentina's tax authority (ARCA/AFIP). This file tells you everything you need to operate it.

## What this does

Generates electronic invoices (Factura Electrónica) via AFIP's WSFEv1 SOAP API and produces official-format PDFs with QR codes.

## First-time setup

If the project hasn't been set up yet (no `config.json`, no certificates), refer the user to the **"Setup inicial"** section in `README.md`. It covers:

1. Generating RSA private key and CSR with OpenSSL
2. Obtaining a digital certificate from AFIP's "Administración de Certificados Digitales"
3. Creating a punto de venta for Web Services in RCEL
4. Associating the certificate to the `wsfe` service
5. Copying `config.example.json` → `config.json` and filling in real data
6. (Optional) Testing in homologación
7. Running the first real invoice

**Do not attempt to generate invoices until all setup steps are complete.**

## Prerequisites

Before each use, verify setup:

```bash
# Check Python deps are installed
python -c "import zeep, lxml, jinja2, weasyprint, segno" 2>&1 || pip install -r requirements.txt

# Check config exists
test -f config.json || echo "ERROR: config.json missing. Copy from config.example.json and fill in. See README.md for full setup guide."

# Check certificates exist
ls afip_certs/*.crt afip_certs/*.key 2>/dev/null || echo "ERROR: certificates missing in afip_certs/. See README.md Setup inicial steps 1-2."
```

## How to generate an invoice

### Step 1: Parse the user's request

The user will say something like:
- "facturale 2 millones a sergio"
- "invoice viviana for 4300000"
- "generá factura a ejemplo por 150000"

Extract: **client name** (key in config.json) and **amount** (number).

### Step 2: Show confirmation and wait for approval

**NEVER generate an invoice without explicit user confirmation.** Show:

```
Cliente: [NOMBRE COMPLETO] (CUIT: [CUIT])
Monto: $[AMOUNT]
Período: 01/[MM]/[YYYY] - [LAST_DAY]/[MM]/[YYYY]
Fecha de emisión: [TODAY]
Entorno: producción
```

### Step 3: Run the script

```bash
cd /path/to/afip-facturacion && python afip_facturacion.py <client_key> <amount> prod
```

Arguments:
- `client_key`: lowercase key from config.json's `clientes` section (e.g. "sergio", "viviana")
- `amount`: numeric amount, no dots or commas (e.g. 2200000)
- `prod`: use "prod" for real invoices, "homo" for testing

### Step 4: Verify and report

Check the output for `✅ FACTURA APROBADA`. Extract and report:
- **CAE**: the authorization code (14 digits)
- **Comp. Nro**: invoice number
- **CAE Vto**: expiration date
- **PDF path**: the generated PDF file

If you see `❌ FACTURA RECHAZADA`, report the error message to the user. Common issues:
- "El número o fecha del comprobante no se corresponde": sequence number mismatch
- SSL errors: the script handles weak DH keys automatically
- Token errors: cached tokens expire after ~12 hours, script auto-renews

## Config file structure (config.json)

```json
{
    "emisor": {
        "cuit": "20123456789",
        "razon_social": "COMPANY NAME",
        "domicilio": "Address",
        "condicion_iva": "Responsable Monotributo",
        "ingresos_brutos": "123456",
        "fecha_inicio_actividades": "01/01/2020"
    },
    "punto_venta": 1,
    "tipo_comprobante": 11,
    "concepto": 2,
    "descripcion_default": "Services description",
    "certificados": {
        "homo": { "cert": "afip_certs/cert_homo.crt", "key": "afip_certs/key_homo.key" },
        "prod": { "cert": "afip_certs/cert_prod.crt", "key": "afip_certs/key_prod.key" }
    },
    "clientes": {
        "client_key": {
            "nombre": "FULL NAME",
            "cuit": "20123456789",
            "condicion_iva": 1,
            "domicilio": "Address"
        }
    }
}
```

### Client condicion_iva codes
- 1 = IVA Responsable Inscripto
- 4 = IVA Sujeto Exento
- 5 = Consumidor Final
- 6 = Responsable Monotributo

### Tipo comprobante codes
- 11 = Factura C (Monotributo)
- 6 = Factura B
- 1 = Factura A

## Adding a new client

Edit `config.json` and add to the `clientes` object:

```json
"new_client": {
    "nombre": "LASTNAME FIRSTNAME",
    "cuit": "20XXXXXXXX9",
    "condicion_iva": 1,
    "domicilio": "Street 123 - City"
}
```

## Available clients

To list registered clients:
```bash
python -c "import json; c=json.load(open('config.json')); [print(f'  {k}: {v[\"nombre\"]} (CUIT {v[\"cuit\"]})') for k,v in c['clientes'].items()]"
```

## Files

| File | Purpose |
|------|---------|
| `afip_facturacion.py` | Main script: WSAA auth + WSFEv1 billing + PDF generation |
| `generar_pdf_html.py` | PDF engine: HTML template → PDF via WeasyPrint |
| `factura_template.html` | HTML template replicating official AFIP invoice format |
| `config.json` | Your configuration (not in repo) |
| `config.example.json` | Example configuration template |
| `afip_certs/` | Digital certificates directory |
| `output/` | Generated PDFs land here |
