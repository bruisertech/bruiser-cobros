#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BRUISER TECH — Plataforma Virtual de Cobros y Contabilidad (100% Manejable desde iPhone / Android)
==================================================================================================
Diseñada especialmente para correr 24/7 en la nube GRATIS (Render.com Free Tier + GitHub) sin PC:
1. Interfaz Móvil (PWA) optimizada para iPhone y Android: agrega suscriptores, ve tu contabilidad
   y concilia pagos desde el navegador de tu celular.
2. Persistencia Automática en GitHub (Opcional con GITHUB_TOKEN y GITHUB_REPO): guarda tus archivos
   `suscriptores.csv` y `contabilidad_pagos.csv` automáticamente en tu repositorio privado de GitHub
   para que en Render Free Tier nunca se pierda un solo dato.
3. Tres modos de envío de WhatsApp (Cero riesgo de baneo):
   - MODO CELULAR 1-TOQUE (0% Baneo, 100% Gratis): El servidor crea el link en la API de Bold,
     arma el mensaje y te abre la app oficial de WhatsApp de tu iPhone/Android con todo escrito.
   - MODO META CLOUD API OFICIAL (0% Baneo, 100% Automático en la nube): Usa la API oficial de Meta.
   - MODO OPENWA SAFE-SENDING (Con pausa humana aleatoria y SEND_PACING_ENABLED=true).
"""

import csv
import hashlib
import hmac
import base64
import json
import logging
import os
import random
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, quote

# ==============================================================================
# 1. CONFIGURACIÓN GENERAL (Variables de entorno en Render / GitHub)
# ==============================================================================
PORT = int(os.environ.get("PORT", "8000"))
DATA_DIR = os.environ.get("DATA_DIR", "./datos")
LOGS_DIR = os.environ.get("LOGS_DIR", "./logs")

# Datos de tu negocio (Bruiser Tech)
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Bruiser Tech")
NEQUI_NUMBER = os.environ.get("NEQUI_NUMBER", "305 386 2774")
LLAVE_BREB = os.environ.get("LLAVE_BREB", "@bruisertech")
SUPPORT_WHATSAPP = os.environ.get("SUPPORT_WHATSAPP", "+57 305 386 2774")

# Credenciales de la API de Bold (https://developers.bold.co/pagos-en-linea/api-link-de-pagos)
BOLD_API_KEY = os.environ.get("BOLD_API_KEY", "")  # Tu Llave de Identidad de Bold
BOLD_WEBHOOK_SECRET = os.environ.get("BOLD_WEBHOOK_SECRET", "")  # Tu Llave Secreta para Webhooks
BOLD_BASE_URL = "https://integrations.api.bold.co"

# Opción A (Automático 0% Baneo): WhatsApp Cloud API Oficial de Meta
META_WA_TOKEN = os.environ.get("META_WA_TOKEN", "")
META_PHONE_ID = os.environ.get("META_PHONE_ID", "")

# Opción B (Automático Self-Hosted): OpenWA (https://www.open-wa.org/)
OPENWA_URL = os.environ.get("OPENWA_URL", "http://localhost:2785/api")
OPENWA_API_KEY = os.environ.get("OPENWA_API_KEY", "")
OPENWA_SESSION = os.environ.get("OPENWA_SESSION", "default")

# Persistencia automática en tu repositorio privado de GitHub (para que Render Free nunca borre tus CSV)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # Ejemplo: "tu_usuario/bruiser-cobros"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

# Comportamiento Anti-Baneo (https://docs.open-wa.org/guides/safe-sending)
MIN_HUMAN_DELAY_SEC = int(os.environ.get("MIN_HUMAN_DELAY_SEC", "25"))
MAX_HUMAN_DELAY_SEC = int(os.environ.get("MAX_HUMAN_DELAY_SEC", "55"))

# Comisiones estimadas de Bold para cálculo contable (2.99% + $900 COP por defecto)
BOLD_FEE_PERCENT = float(os.environ.get("BOLD_FEE_PERCENT", "0.0299"))
BOLD_FEE_FIXED = int(os.environ.get("BOLD_FEE_FIXED", "900"))

# Archivos CSV y Logs
SUBSCRIBERS_CSV = os.path.join(DATA_DIR, "suscriptores.csv")
LEDGER_CSV = os.path.join(DATA_DIR, "contabilidad_pagos.csv")
LOG_FILE = os.path.join(LOGS_DIR, "registro_envios_y_cobros.log")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ==============================================================================
# 2. SINCRONIZACIÓN AUTOMÁTICA CON GITHUB (Para no perder datos en Render Free)
# ==============================================================================
def sync_file_to_github(local_path, repo_relative_path):
    """Guarda automáticamente el CSV en tu repositorio privado de GitHub si configuraste GITHUB_TOKEN."""
    if not GITHUB_TOKEN or not GITHUB_REPO or not os.path.exists(local_path):
        return
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_relative_path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "BruiserTech-Billing"
    }
    sha = None
    try:
        req_get = urllib.request.Request(f"{api_url}?ref={GITHUB_BRANCH}", headers=headers, method="GET")
        with urllib.request.urlopen(req_get, timeout=10) as resp:
            sha = json.loads(resp.read().decode("utf-8")).get("sha")
    except Exception:
        pass

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "message": f"Auto-sync {repo_relative_path} ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    try:
        req_put = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req_put, timeout=15):
            logging.info(f"[GITHUB SYNC OK] {repo_relative_path} respaldado en {GITHUB_REPO}")
    except Exception as e:
        logging.warning(f"[GITHUB SYNC WARN] No se pudo respaldar {repo_relative_path}: {e}")


# ==============================================================================
# 3. INICIALIZACIÓN Y MANEJO DE ARCHIVOS CSV (Suscriptores y Contabilidad)
# ==============================================================================
SUBSCRIBER_HEADERS = [
    "id", "nombre", "telefono", "servicio", "cantidad_cop", "dia_cobro", "activo", "notas"
]

LEDGER_HEADERS = [
    "referencia", "periodo_mes", "id_suscriptor", "nombre", "telefono",
    "servicio", "monto_bruto_cop", "dia_cobro", "bold_link_id", "bold_url",
    "whatsapp_enviado", "fecha_envio_wa", "estado_pago", "metodo_pago",
    "comision_bold_cop", "monto_neto_cop", "fecha_pago"
]


def init_csv_files():
    """Crea los archivos CSV con ejemplos claros si todavía no existen."""
    if not os.path.exists(SUBSCRIBERS_CSV):
        with open(SUBSCRIBERS_CSV, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SUBSCRIBER_HEADERS)
            writer.writeheader()
            writer.writerow({
                "id": "SUB-001",
                "nombre": "Carlos Andrés Gómez",
                "telefono": "573001234567",
                "servicio": "Plan bruiserCare Web + Hosting Administrado",
                "cantidad_cop": "45900",
                "dia_cobro": "5",
                "activo": "SI",
                "notas": "Dominio tiendaejemplo.com"
            })
            writer.writerow({
                "id": "SUB-002",
                "nombre": "Laura Sofía Martínez",
                "telefono": "573109876543",
                "servicio": "Espacio Google Drive (2 TB) + Suscripción Mensual",
                "cantidad_cop": "25000",
                "dia_cobro": "15",
                "activo": "SI",
                "notas": "Cuenta Drive compartida"
            })
        logging.info("Archivo suscriptores.csv inicializado con clientes de ejemplo.")

    if not os.path.exists(LEDGER_CSV):
        with open(LEDGER_CSV, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
            writer.writeheader()
        logging.info("Archivo contabilidad_pagos.csv inicializado.")


def read_subscribers():
    init_csv_files()
    with open(SUBSCRIBERS_CSV, mode="r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_subscribers(rows):
    with open(SUBSCRIBERS_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUBSCRIBER_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    sync_file_to_github(SUBSCRIBERS_CSV, "datos/suscriptores.csv")


def read_ledger():
    init_csv_files()
    with open(LEDGER_CSV, mode="r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_ledger(rows):
    with open(LEDGER_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    sync_file_to_github(LEDGER_CSV, "datos/contabilidad_pagos.csv")


def format_cop(value):
    try:
        num = int(float(str(value).replace(".", "").replace(",", "").strip()))
        return f"${num:,}".replace(",", ".") + " COP"
    except Exception:
        return f"${value} COP"


# ==============================================================================
# 4. INTEGRACIÓN CON LA API DE BOLD (Creación y Consulta de Links de Pago)
# ==============================================================================
def create_bold_payment_link(subscriber, reference):
    """
    Crea un link de pago cerrado en Bold usando POST https://integrations.api.bold.co/online/link/v1
    Documentación oficial: https://developers.bold.co/pagos-en-linea/api-link-de-pagos
    """
    amount_cop = int(float(subscriber["cantidad_cop"]))
    description = f"{BUSINESS_NAME} - {subscriber['servicio']}"[:98]

    if not BOLD_API_KEY or BOLD_API_KEY.startswith("TU_"):
        fake_id = f"LNK_DEMO_{reference[-8:]}"
        fake_url = f"https://checkout.bold.co/{fake_id}"
        logging.warning(f"[MODO DEMO BOLD] Generado link de prueba {fake_url} para {subscriber['nombre']}")
        return fake_id, fake_url

    expiration_ns = int((time.time() + (10 * 86400)) * 1e9)

    payload = {
        "amount_type": "CLOSE",
        "amount": {
            "currency": "COP",
            "total_amount": amount_cop,
            "tip_amount": 0
        },
        "reference": reference[:60],
        "description": description,
        "expiration_date": expiration_ns,
        "payment_methods": ["CREDIT_CARD", "PSE", "BOTON_BANCOLOMBIA", "NEQUI"]
    }

    req = urllib.request.Request(
        url=f"{BOLD_BASE_URL}/online/link/v1",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"x-api-key {BOLD_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            link_data = data.get("payload", {})
            payment_link_id = link_data.get("payment_link", "")
            payment_url = link_data.get("url", f"https://checkout.bold.co/{payment_link_id}")
            logging.info(f"[BOLD API OK] Link creado: {payment_link_id} -> {payment_url}")
            return payment_link_id, payment_url
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        logging.error(f"[BOLD API ERROR {e.code}] No se pudo crear el link para {reference}: {err_body}")
        return "", ""
    except Exception as e:
        logging.error(f"[BOLD API EXCEPCIÓN] {e}")
        return "", ""


def check_bold_link_status(payment_link_id):
    """
    Consulta si un link de Bold ya fue pagado: GET /online/link/v1/{payment_link}
    """
    if not payment_link_id or payment_link_id.startswith("LNK_DEMO_") or not BOLD_API_KEY or BOLD_API_KEY.startswith("TU_"):
        return "ACTIVE", ""

    req = urllib.request.Request(
        url=f"{BOLD_BASE_URL}/online/link/v1/{payment_link_id}",
        headers={
            "Authorization": f"x-api-key {BOLD_API_KEY}",
            "Accept": "application/json"
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status", "ACTIVE")
            method = data.get("payment_method", "BOLD_ONLINE")
            return status, method
    except Exception as e:
        logging.warning(f"No se pudo consultar estado del link {payment_link_id}: {e}")
        return "ACTIVE", ""


# ==============================================================================
# 5. COMPOSICIÓN Y ENVÍO DE WHATSAPP (Modo Celular 1-Tap / Meta API / OpenWA)
# ==============================================================================
GREETINGS = [
    "¡esperamos que estés teniendo una excelente semana!",
    "¡esperamos que todo marche muy bien!",
    "¡un gusto saludarte hoy!",
    "¡esperamos que estés muy bien!"
]


def normalize_phone(phone):
    clean = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(clean) == 10 and clean.startswith("3"):
        clean = "57" + clean
    return clean


def compose_whatsapp_message(subscriber, bold_url, period_str):
    """
    Arma un mensaje personalizado con variaciones humanas sutiles para proteger la cuenta,
    mostrando el detalle del servicio, Nequi / Llave y el link alterno de Bold.
    """
    nombre = subscriber["nombre"].strip()
    servicio = subscriber["servicio"].strip()
    valor = format_cop(subscriber["cantidad_cop"])
    dia = subscriber["dia_cobro"].strip()
    saludo = random.choice(GREETINGS)

    link_section = (
        f"💳 *Opción 2 — Tarjeta de Crédito, Débito o PSE (Pasarela Bold):*\n"
        f"Si prefieres pagar con tarjeta o PSE, ingresa a tu link de pago aquí:\n"
        f"👉 {bold_url}\n"
    ) if bold_url else ""

    mensaje = (
        f"Hola *{nombre}* 👋, {saludo}\n\n"
        f"Te escribimos de *{BUSINESS_NAME}* para enviarte el recordatorio de tu suscripción mensual correspondiente al periodo *{period_str}*:\n\n"
        f"🧾 *Detalle de tu servicio:*\n"
        f"• *Concepto:* {servicio}\n"
        f"• *Valor mensual:* {valor}\n"
        f"• *Día de corte:* Día {dia} de cada mes\n\n"
        f"Puedes realizar tu pago por cualquiera de estos dos medios:\n\n"
        f"⚡ *Opción 1 — Transferencia directa a Nequi o a la Llave (Sin recargos):*\n"
        f"• *Nequi:* `{NEQUI_NUMBER}`\n"
        f"• *Llave (Bre-B / Transfiya):* `{LLAVE_BREB}`\n"
        f"_(Si pagas por Nequi o a la Llave, envíanos por favor el comprobante por este mismo chat para aplicarlo de inmediato)_.\n\n"
        f"{link_section}\n"
        f"¡Muchas gracias por confiar en *{BUSINESS_NAME}*! 🚀\n"
        f"🌐 https://bruiser.tech/"
    )
    return mensaje


def send_whatsapp_message(phone, message):
    """
    Intenta enviar el mensaje en este orden:
    1. Si configuraste META_WA_TOKEN + META_PHONE_ID -> Usa la API Oficial de Meta (0% Baneo en la nube).
    2. Si configuraste OPENWA_API_KEY -> Usa OpenWA con protección HTTP 429 SEND_PACING_LIMITED.
    3. Si no hay API automática configurada -> Queda listo para enviar en 1 toque desde tu iPhone/Android (wa.me).
    """
    clean_phone = normalize_phone(phone)

    # 1. API Oficial de WhatsApp Cloud de Meta (0% Baneo en la nube)
    if META_WA_TOKEN and META_PHONE_ID:
        url = f"https://graph.facebook.com/v21.0/{META_PHONE_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": True, "body": message}
        }
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {META_WA_TOKEN}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=20):
                logging.info(f"[META CLOUD API OK] WhatsApp enviado a {clean_phone}")
                return True, "SI (META API)"
        except Exception as e:
            logging.error(f"[ERROR META API] {e}")
            return False, "ERROR_META_API"

    # 2. OpenWA con Safe Sending
    if OPENWA_API_KEY and not OPENWA_API_KEY.startswith("TU_"):
        payload = {
            "sessionId": OPENWA_SESSION,
            "chatId": f"{clean_phone}@c.us",
            "text": message
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": OPENWA_API_KEY,
            "Authorization": f"Bearer {OPENWA_API_KEY}"
        }
        req = urllib.request.Request(
            url=f"{OPENWA_URL.rstrip('/')}/messages/text",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                resp_text = resp.read().decode("utf-8", errors="ignore")
                logging.info(f"[WHATSAPP ENVIADO OK] Destino: {clean_phone} | Respuesta: {resp_text[:120]}")
                return True, "SI (OPENWA)"
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429:
                try:
                    err_json = json.loads(err_body)
                    wait_sec = err_json.get("retryAfterSeconds", 60)
                    return False, f"PAUSADO_SAFE_PACING ({wait_sec}s)"
                except Exception:
                    pass
            return False, f"ERROR_HTTP_{e.code}"
        except Exception as e:
            logging.error(f"[ERROR WHATSAPP] Falló envío a {clean_phone}: {e}")
            return False, f"ERROR ({str(e)[:30]})"

    # 3. Modo Celular 1-Toque (El servidor genera el link de Bold y tú lo envías con 1 toque desde tu iPhone/Android)
    logging.info(f"[LISTO PARA CELULAR -> {clean_phone}] Link de Bold creado y mensaje preparado para 1-Tap en celular.")
    return True, "LISTO_PARA_1_TOQUE"


# ==============================================================================
# 6. MOTOR DE COBRO MENSUAL Y CONCILIACIÓN CONTABLE
# ==============================================================================
def ensure_monthly_order(subscriber_id):
    """
    Asegura que el suscriptor tenga su orden del mes creada con su Link de Pago de Bold
    y retorna la fila del libro contable junto con el mensaje de WhatsApp listo.
    """
    subscribers = read_subscribers()
    sub = next((s for s in subscribers if s["id"] == subscriber_id), None)
    if not sub:
        return None, ""

    now = datetime.now()
    period_str = now.strftime("%Y-%m")
    reference = f"BRU-{now.strftime('%Y%m')}-{sub['id']}"

    ledger = read_ledger()
    existing = next((r for r in ledger if r["referencia"] == reference), None)

    if existing and existing.get("bold_url"):
        bold_id, bold_url = existing["bold_link_id"], existing["bold_url"]
    else:
        bold_id, bold_url = create_bold_payment_link(sub, reference)

    msg = compose_whatsapp_message(sub, bold_url, period_str)

    if not existing:
        existing = {
            "referencia": reference,
            "periodo_mes": period_str,
            "id_suscriptor": sub["id"],
            "nombre": sub["nombre"],
            "telefono": sub["telefono"],
            "servicio": sub["servicio"],
            "monto_bruto_cop": sub["cantidad_cop"],
            "dia_cobro": sub["dia_cobro"],
            "bold_link_id": bold_id,
            "bold_url": bold_url,
            "whatsapp_enviado": "LISTO_PARA_ENVIAR",
            "fecha_envio_wa": "",
            "estado_pago": "PENDIENTE",
            "metodo_pago": "",
            "comision_bold_cop": "0",
            "monto_neto_cop": "0",
            "fecha_pago": ""
        }
        ledger.append(existing)
        save_ledger(ledger)

    return existing, msg


def generate_and_send_charge(subscriber_id, force=False):
    subscribers = read_subscribers()
    sub = next((s for s in subscribers if s["id"] == subscriber_id), None)
    if not sub:
        return False, "Suscriptor no encontrado"

    now = datetime.now()
    period_str = now.strftime("%Y-%m")
    reference = f"BRU-{now.strftime('%Y%m')}-{sub['id']}"

    ledger = read_ledger()
    existing = next((r for r in ledger if r["referencia"] == reference), None)

    if existing and existing["whatsapp_enviado"].startswith("SI") and not force:
        return False, f"Ya se envió el cobro de {period_str} a {sub['nombre']}"

    if existing and existing.get("bold_url"):
        bold_id, bold_url = existing["bold_link_id"], existing["bold_url"]
    else:
        bold_id, bold_url = create_bold_payment_link(sub, reference)

    msg = compose_whatsapp_message(sub, bold_url, period_str)
    wa_ok, wa_status = send_whatsapp_message(sub["telefono"], msg)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        existing["bold_link_id"] = bold_id
        existing["bold_url"] = bold_url
        existing["whatsapp_enviado"] = wa_status
        existing["fecha_envio_wa"] = now_str if wa_ok else existing.get("fecha_envio_wa", "")
    else:
        ledger.append({
            "referencia": reference,
            "periodo_mes": period_str,
            "id_suscriptor": sub["id"],
            "nombre": sub["nombre"],
            "telefono": sub["telefono"],
            "servicio": sub["servicio"],
            "monto_bruto_cop": sub["cantidad_cop"],
            "dia_cobro": sub["dia_cobro"],
            "bold_link_id": bold_id,
            "bold_url": bold_url,
            "whatsapp_enviado": wa_status,
            "fecha_envio_wa": now_str if wa_ok else "",
            "estado_pago": "PENDIENTE",
            "metodo_pago": "",
            "comision_bold_cop": "0",
            "monto_neto_cop": "0",
            "fecha_pago": ""
        })

    save_ledger(ledger)
    return wa_ok, f"Cobro {reference}: {wa_status}"


def mark_invoice_paid(reference, method="NEQUI_O_LLAVE"):
    ledger = read_ledger()
    row = next((r for r in ledger if r["referencia"] == reference), None)
    if not row:
        return False, "Referencia no encontrada"

    gross = int(float(row["monto_bruto_cop"]))
    if method in ("NEQUI_O_LLAVE", "NEQUI_DIRECTO", "LLAVE_BREB"):
        fee = 0
    else:
        fee = int(round(gross * BOLD_FEE_PERCENT)) + BOLD_FEE_FIXED

    net = max(0, gross - fee)
    row["estado_pago"] = "PAGADO"
    row["metodo_pago"] = method
    row["comision_bold_cop"] = str(fee)
    row["monto_neto_cop"] = str(net)
    row["fecha_pago"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_ledger(ledger)

    recibo_msg = (
        f"✅ *¡Pago Recibido con Éxito! — {BUSINESS_NAME}*\n\n"
        f"Hola *{row['nombre']}*, confirmamos la recepción de tu pago:\n"
        f"• *Referencia:* `{reference}`\n"
        f"• *Servicio:* {row['servicio']}\n"
        f"• *Valor pagado:* {format_cop(gross)}\n"
        f"• *Medio de pago:* {method}\n\n"
        f"Tu servicio se encuentra 100% activo y al día. ¡Muchas gracias! 🚀"
    )
    send_whatsapp_message(row["telefono"], recibo_msg)
    logging.info(f"[CONTABILIDAD] Pago asentado: {reference} | Método: {method} | Bruto: {gross} | Neto: {net}")
    return True, "Pago registrado en contabilidad"


def run_automatic_cycle(apply_human_delay=False):
    now = datetime.now()
    today_day = now.day

    subscribers = read_subscribers()
    ledger = read_ledger()
    sent_count = 0

    for sub in subscribers:
        if sub.get("activo", "SI").strip().upper() != "SI":
            continue
        try:
            due_day = int(sub.get("dia_cobro", "1"))
        except ValueError:
            due_day = 1

        ref = f"BRU-{now.strftime('%Y%m')}-{sub['id']}"
        existing = next((r for r in ledger if r["referencia"] == ref), None)

        if today_day >= due_day and (not existing or existing["whatsapp_enviado"] in ("NO_ENVIADO", "")):
            if sent_count > 0 and apply_human_delay:
                pause_sec = random.randint(MIN_HUMAN_DELAY_SEC, MAX_HUMAN_DELAY_SEC)
                logging.info(f"[SAFE-SENDING] Pausa humana de {pause_sec}s antes del siguiente mensaje...")
                time.sleep(pause_sec)

            logging.info(f"[AUTO-COBRO] Preparando cobro mensual para {sub['nombre']} (Día {due_day})")
            ok, _ = generate_and_send_charge(sub["id"], force=False)
            if ok:
                sent_count += 1

    ledger = read_ledger()
    for row in ledger:
        if row["estado_pago"] == "PENDIENTE" and row.get("bold_link_id"):
            status, method = check_bold_link_status(row["bold_link_id"])
            if status == "PAID":
                logging.info(f"[AUTO-CONCILIACIÓN BOLD] El link {row['bold_link_id']} aparece PAGADO.")
                mark_invoice_paid(row["referencia"], method=f"BOLD_{method or 'ONLINE'}")


def background_scheduler():
    while True:
        try:
            run_automatic_cycle(apply_human_delay=True)
        except Exception as e:
            logging.error(f"Error en ciclo automático: {e}")
        time.sleep(1800)


# ==============================================================================
# 7. INTERFAZ WEB MÓVIL (PWA PARA IPHONE Y ANDROID)
# ==============================================================================
def render_dashboard_html(flash_msg=""):
    subscribers = read_subscribers()
    ledger = read_ledger()
    now_period = datetime.now().strftime("%Y-%m")

    mrr_estimado = sum(
        int(float(s["cantidad_cop"])) for s in subscribers if s.get("activo", "SI").upper() == "SI"
    )
    total_recaudado_bruto = sum(
        int(float(r["monto_bruto_cop"])) for r in ledger if r["estado_pago"] == "PAGADO"
    )
    total_comisiones_bold = sum(
        int(float(r["comision_bold_cop"])) for r in ledger if r["estado_pago"] == "PAGADO"
    )
    total_neto_real = sum(
        int(float(r["monto_neto_cop"])) for r in ledger if r["estado_pago"] == "PAGADO"
    )
    pendientes_cobro = sum(
        int(float(r["monto_bruto_cop"])) for r in ledger if r["estado_pago"] == "PENDIENTE"
    )

    sub_rows_html = ""
    for s in subscribers:
        sample_msg = compose_whatsapp_message(
            s, f"https://checkout.bold.co/LNK_{s['id']}", now_period
        ).replace("`", "").replace('"', "&quot;")
        badge_activo = (
            '<span class="badge ok">ACTIVO</span>'
            if s.get("activo", "SI").upper() == "SI"
            else '<span class="badge warn">PAUSADO</span>'
        )
        sub_rows_html += f"""
        <tr>
            <td><code>{s['id']}</code></td>
            <td><strong>{s['nombre']}</strong><br><small style="color:#94a3b8">{s.get('notas','')}</small></td>
            <td><code>+{s['telefono']}</code></td>
            <td>{s['servicio']}</td>
            <td style="text-align:right;font-weight:700;color:#38bdf8">{format_cop(s['cantidad_cop'])}</td>
            <td style="text-align:center">Día <strong>{s['dia_cobro']}</strong></td>
            <td>{badge_activo}</td>
            <td style="display:flex;gap:6px;flex-wrap:wrap">
                <a href="/abrir-whatsapp-celular?id={s['id']}" class="btn btn-success" title="Crea el link en Bold y abre tu app de WhatsApp en iPhone/Android con 0% riesgo de baneo">
                    📱 Enviar desde mi Celular (0% Ban)
                </a>
                <form method="POST" action="/cobrar-ahora" style="margin:0">
                    <input type="hidden" name="id" value="{s['id']}">
                    <button type="submit" class="btn btn-primary">🤖 Auto-Enviar API</button>
                </form>
                <button type="button" class="btn btn-ghost" onclick="verMensaje(`{sample_msg}`)">👁️ Ver</button>
            </td>
        </tr>
        """

    ledger_rows_html = ""
    for r in reversed(ledger):
        wa_badge = (
            f'<span class="badge ok">✅ {r["whatsapp_enviado"]}</span><br><small>{r["fecha_envio_wa"]}</small>'
            if r["whatsapp_enviado"].startswith("SI") or r["whatsapp_enviado"] == "ENVIADO_DESDE_CELULAR"
            else f'<span class="badge warn">📲 {r["whatsapp_enviado"]}</span>'
        )
        if r["estado_pago"] == "PAGADO":
            pago_badge = f'<span class="badge ok">💰 PAGADO ({r["metodo_pago"]})</span><br><small>{r["fecha_pago"]}</small>'
            acciones_pago = '<span style="color:#64748b;font-size:12px">Conciliado ✓</span>'
        else:
            pago_badge = '<span class="badge warn">⏳ PENDIENTE</span>'
            acciones_pago = f"""
            <div style="display:flex;gap:6px;flex-wrap:wrap">
                <a href="/abrir-whatsapp-celular?id={r['id_suscriptor']}" class="btn btn-primary">📱 Reenviar desde Celular</a>
                <form method="POST" action="/marcar-pagado" style="margin:0">
                    <input type="hidden" name="referencia" value="{r['referencia']}">
                    <input type="hidden" name="metodo" value="NEQUI_O_LLAVE">
                    <button type="submit" class="btn btn-success">⚡ Pagó Nequi/Llave ($0)</button>
                </form>
                <form method="POST" action="/marcar-pagado" style="margin:0">
                    <input type="hidden" name="referencia" value="{r['referencia']}">
                    <input type="hidden" name="metodo" value="BOLD_LINK">
                    <button type="submit" class="btn btn-ghost">💳 Pagó Bold</button>
                </form>
            </div>
            """

        link_html = (
            f'<a href="{r["bold_url"]}" target="_blank" style="color:#38bdf8">{r["bold_link_id"]} ↗</a>'
            if r.get("bold_url")
            else "—"
        )
        ledger_rows_html += f"""
        <tr>
            <td><code>{r['referencia']}</code></td>
            <td><strong>{r['nombre']}</strong><br><small style="color:#94a3b8">{r['servicio']}</small></td>
            <td style="text-align:right">{format_cop(r['monto_bruto_cop'])}</td>
            <td>{link_html}</td>
            <td>{wa_badge}</td>
            <td>{pago_badge}</td>
            <td style="text-align:right;color:#f87171">-{format_cop(r['comision_bold_cop'])}</td>
            <td style="text-align:right;font-weight:700;color:#4ade80">{format_cop(r['monto_neto_cop'])}</td>
            <td>{acciones_pago}</td>
        </tr>
        """

    if not ledger_rows_html:
        ledger_rows_html = '<tr><td colspan="9" style="text-align:center;color:#94a3b8;padding:24px">Aún no hay cobros registrados este mes. Toca "📱 Enviar desde mi Celular (0% Ban)" o "⚡ Generar Links del Día".</td></tr>'

    flash_banner = (
        f'<div style="background:#065f46;border:1px solid #10b981;color:#ecfdf5;padding:12px 16px;border-radius:10px;margin-bottom:20px;font-weight:600">✨ {flash_msg}</div>'
        if flash_msg else ""
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Bruiser Tech — Cobros Móviles & Contabilidad</title>
<style>
  :root {{
    --bg: #0b0f19; --card: #111827; --border: #1e293b; --text: #f8fafc;
    --muted: #94a3b8; --accent: #38bdf8; --green: #22c55e; --amber: #f59e0b;
  }}
  * {{ box-sizing: border-box; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); padding: 14px; }}
  .container {{ max-width: 1320px; margin: 0 auto; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; border-bottom: 1px solid var(--border); padding-bottom: 14px; }}
  .brand {{ font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }}
  .brand span {{ color: var(--accent); }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }}
  .kpi-label {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
  .kpi-val {{ font-size: 20px; font-weight: 800; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; margin-bottom: 20px; overflow-x: auto; }}
  h2 {{ margin-top: 0; font-size: 16px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: middle; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; }}
  input, select {{ background: #0f172a; border: 1px solid #334155; color: #fff; padding: 10px 12px; border-radius: 8px; font-size: 14px; width: 100%; }}
  .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; align-items: end; }}
  .btn {{ border: none; border-radius: 8px; padding: 9px 12px; font-size: 12.5px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; }}
  .btn-primary {{ background: #0284c7; color: #fff; }}
  .btn-success {{ background: #16a34a; color: #fff; }}
  .btn-ghost {{ background: #1e293b; color: #e2e8f0; border: 1px solid #334155; }}
  .badge {{ padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; display: inline-block; }}
  .badge.ok {{ background: rgba(34,197,94,0.18); color: #4ade80; }}
  .badge.warn {{ background: rgba(245,158,11,0.18); color: #fbbf24; }}
  .badge.err {{ background: rgba(239,68,68,0.18); color: #f87171; }}
  .modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); align-items:center; justify-content:center; padding:16px; z-index:50; }}
  .modal-box {{ background:#1e293b; border:1px solid #475569; max-width:540px; width:100%; border-radius:14px; padding:18px; }}
  pre {{ white-space: pre-wrap; background:#0f172a; padding:12px; border-radius:10px; color:#e2e8f0; font-size:12.5px; line-height:1.5; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <div class="brand">bruiser<span>.tech</span> // App Móvil de Cobros & Contabilidad</div>
      <div style="color:var(--muted);font-size:12.5px;margin-top:4px">
        100% Virtual para iPhone y Android • Nequi: <strong>{NEQUI_NUMBER}</strong> • Llave: <strong>{LLAVE_BREB}</strong>
      </div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <form method="POST" action="/ejecutar-ciclo" style="margin:0">
        <button type="submit" class="btn btn-primary">⚡ Generar Links del Día</button>
      </form>
      <a href="/descargar/suscriptores.csv" class="btn btn-ghost">📥 suscriptores.csv</a>
      <a href="/descargar/contabilidad_pagos.csv" class="btn btn-ghost">📊 contabilidad.csv</a>
    </div>
  </div>

  {flash_banner}

  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">MRR Mensual Activo</div>
      <div class="kpi-val" style="color:#38bdf8">{format_cop(mrr_estimado)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Recaudado Bruto</div>
      <div class="kpi-val">{format_cop(total_recaudado_bruto)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Comisiones Bold</div>
      <div class="kpi-val" style="color:#f87171">-{format_cop(total_comisiones_bold)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Neto Real en tus Cuentas</div>
      <div class="kpi-val" style="color:#4ade80">{format_cop(total_neto_real)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Pendiente por Cobrar</div>
      <div class="kpi-val" style="color:#fbbf24">{format_cop(pendientes_cobro)}</div>
    </div>
  </div>

  <div class="card">
    <h2>➕ Agregar Nuevo Suscriptor desde tu Celular</h2>
    <form method="POST" action="/agregar-suscriptor" class="form-grid">
      <div>
        <label style="font-size:12px;color:var(--muted)">Nombre del Cliente</label>
        <input type="text" name="nombre" placeholder="Ej. Camilo Restrepo" required>
      </div>
      <div>
        <label style="font-size:12px;color:var(--muted)">WhatsApp (con 57)</label>
        <input type="tel" name="telefono" placeholder="Ej. 573001112233" required>
      </div>
      <div>
        <label style="font-size:12px;color:var(--muted)">Concepto / Servicio (Web, Drive, etc.)</label>
        <input type="text" name="servicio" placeholder="Ej. bruiserCare Web + Google Drive 2TB" required>
      </div>
      <div>
        <label style="font-size:12px;color:var(--muted)">Cantidad a Cobrar (COP)</label>
        <input type="number" name="cantidad_cop" placeholder="Ej. 45900" required>
      </div>
      <div>
        <label style="font-size:12px;color:var(--muted)">Día del Mes (1 al 28)</label>
        <input type="number" name="dia_cobro" min="1" max="31" value="5" required>
      </div>
      <div>
        <label style="font-size:12px;color:var(--muted)">Notas opcionales</label>
        <input type="text" name="notas" placeholder="Dominio o correo Drive">
      </div>
      <div>
        <button type="submit" class="btn btn-success" style="width:100%;padding:11px">+ Guardar Suscriptor</button>
      </div>
    </form>
  </div>

  <div class="card">
    <h2>👥 Suscriptores ({len(subscribers)}) — Toca "📱 Enviar desde mi Celular" para 0% Riesgo de Baneo</h2>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Cliente</th><th>WhatsApp</th><th>Servicio / Concepto</th>
          <th style="text-align:right">Valor</th><th style="text-align:center">Día</th>
          <th>Estado</th><th>Acciones desde tu iPhone / Android</th>
        </tr>
      </thead>
      <tbody>
        {sub_rows_html}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>📒 Libro Contable y Registro de Envíos</h2>
    <table>
      <thead>
        <tr>
          <th>Referencia</th><th>Cliente & Servicio</th><th style="text-align:right">Bruto</th>
          <th>Link de Bold</th><th>Estado WhatsApp</th><th>Estado Pago</th>
          <th style="text-align:right">Comisión Bold</th><th style="text-align:right">Neto Real</th>
          <th>Conciliar Pago</th>
        </tr>
      </thead>
      <tbody>
        {ledger_rows_html}
      </tbody>
    </table>
  </div>
</div>

<div class="modal" id="msgModal" onclick="this.style.display='none'">
  <div class="modal-box" onclick="event.stopPropagation()">
    <h3 style="margin-top:0">📱 Vista Previa del Mensaje de WhatsApp</h3>
    <pre id="msgPreviewText"></pre>
    <button class="btn btn-primary" onclick="document.getElementById('msgModal').style.display='none'">Cerrar</button>
  </div>
</div>

<script>
function verMensaje(texto) {{
  document.getElementById('msgPreviewText').textContent = texto;
  document.getElementById('msgModal').style.display = 'flex';
}}
</script>
</body>
</html>"""


class BillingHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            if parsed.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"alive"}')
                return
            qs = parse_qs(parsed.query)
            msg = qs.get("msg", [""])[0]
            body = render_dashboard_html(msg).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/abrir-whatsapp-celular":
            # Crea el link en la API de Bold, registra el cobro en contabilidad y abre la app de WhatsApp en iPhone/Android
            qs = parse_qs(parsed.query)
            sub_id = qs.get("id", [""])[0]
            row, msg = ensure_monthly_order(sub_id)
            if not row:
                self._redirect("/?msg=Suscriptor+no+encontrado")
                return
            ledger = read_ledger()
            for r in ledger:
                if r["referencia"] == row["referencia"]:
                    r["whatsapp_enviado"] = "ENVIADO_DESDE_CELULAR"
                    r["fecha_envio_wa"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_ledger(ledger)
            clean_phone = normalize_phone(row["telefono"])
            wa_link = f"https://api.whatsapp.com/send?phone={clean_phone}&text={quote(msg)}"
            self._redirect(wa_link)

        elif parsed.path == "/descargar/suscriptores.csv":
            init_csv_files()
            with open(SUBSCRIBERS_CSV, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="suscriptores.csv"')
            self.end_headers()
            self.wfile.write(data)

        elif parsed.path == "/descargar/contabilidad_pagos.csv":
            init_csv_files()
            with open(LEDGER_CSV, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="contabilidad_pagos.csv"')
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        parsed = urlparse(self.path)

        if parsed.path == "/api/webhooks/bold":
            signature = self.headers.get("x-bold-signature", "")
            if BOLD_WEBHOOK_SECRET and not BOLD_WEBHOOK_SECRET.startswith("TU_"):
                encoded = base64.b64encode(raw_body)
                hashed = hmac.new(BOLD_WEBHOOK_SECRET.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(hashed, signature):
                    self.send_response(400)
                    self.end_headers()
                    return

            try:
                event = json.loads(raw_body.decode("utf-8"))
                if event.get("type") == "SALE_APPROVED":
                    data = event.get("data", {})
                    ref = data.get("metadata", {}).get("reference", "")
                    method = data.get("payment_method", "BOLD_ONLINE")
                    if ref:
                        mark_invoice_paid(ref, method=f"BOLD_{method}")
            except Exception as e:
                logging.error(f"Error procesando webhook Bold: {e}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        form = parse_qs(raw_body.decode("utf-8"))

        if parsed.path == "/agregar-suscriptor":
            subscribers = read_subscribers()
            new_id = f"SUB-{len(subscribers) + 1:03d}"
            subscribers.append({
                "id": new_id,
                "nombre": form.get("nombre", [""])[0].strip(),
                "telefono": form.get("telefono", [""])[0].strip(),
                "servicio": form.get("servicio", [""])[0].strip(),
                "cantidad_cop": form.get("cantidad_cop", ["0"])[0].strip(),
                "dia_cobro": form.get("dia_cobro", ["1"])[0].strip(),
                "activo": "SI",
                "notas": form.get("notas", [""])[0].strip()
            })
            save_subscribers(subscribers)
            self._redirect(f"/?msg=Suscriptor+{new_id}+guardado+en+suscriptores.csv")

        elif parsed.path == "/cobrar-ahora":
            sub_id = form.get("id", [""])[0]
            _, msg = generate_and_send_charge(sub_id, force=True)
            self._redirect(f"/?msg={quote(msg)}")

        elif parsed.path == "/marcar-pagado":
            ref = form.get("referencia", [""])[0]
            metodo = form.get("metodo", ["NEQUI_O_LLAVE"])[0]
            _, msg = mark_invoice_paid(ref, method=metodo)
            self._redirect(f"/?msg={quote(msg)}")

        elif parsed.path == "/ejecutar-ciclo":
            run_automatic_cycle(apply_human_delay=False)
            self._redirect("/?msg=Links+de+Bold+del+dia+generados+y+pagos+verificados")

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


if __name__ == "__main__":
    init_csv_files()
    if "--cron" in sys.argv:
        logging.info("Ejecutando verificación única en modo --cron...")
        run_automatic_cycle(apply_human_delay=True)
        logging.info("Ciclo --cron finalizado correctamente.")
        sys.exit(0)

    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()
    logging.info(f"Servidor de Cobros Bruiser Tech iniciado en http://0.0.0.0:{PORT}")
    server = HTTPServer(("0.0.0.0", PORT), BillingHTTPHandler)
    server.serve_forever()