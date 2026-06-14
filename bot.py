import os
import json
import base64
import logging
import re
from datetime import datetime

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import anthropic
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SHEET_ID    = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS = json.loads(os.environ["GOOGLE_CREDENTIALS"])

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

HEADERS = ["Fecha", "Nombre", "Cargo", "Empresa", "Email",
           "Telefono", "Web", "LinkedIn", "Notas", "Estado"]


def get_sheet():
    creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
    if sheet.row_count == 0 or not sheet.row_values(1):
        sheet.insert_row(HEADERS, 1)
    return sheet


def extract_lead_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = (
        "Extrae la informacion de contacto de esta imagen "
        "(puede ser tarjeta de visita, captura de LinkedIn, WhatsApp, "
        "formulario web, perfil de red social, etc.).\n\n"
        "Devuelve UNICAMENTE un JSON valido con estos campos "
        "(deja el valor como cadena vacia si no aparece en la imagen):\n"
        '{\n'
        '  "nombre": "",\n'
        '  "cargo": "",\n'
        '  "empresa": "",\n'
        '  "email": "",\n'
        '  "telefono": "",\n'
        '  "web": "",\n'
        '  "linkedin": "",\n'
        '  "notas": ""\n'
        '}\n\n'
        "Solo el JSON, sin texto adicional ni bloques de codigo."
    )

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                }
            ],
        }]
    )

    raw = message.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot de Leads activo\n\n"
        "Mandame una foto de:\n"
        "- Tarjeta de visita\n"
        "- Captura de LinkedIn\n"
        "- Screenshot de WhatsApp\n"
        "- Cualquier perfil de contacto\n\n"
        "Extraere los datos y los guardare en Google Sheets automaticamente."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Analizando imagen con IA...")
    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await tg_file.download_as_bytearray())
        lead = extract_lead_from_image(image_bytes)
        if not lead or not any(v for v in lead.values()):
            await msg.edit_text("No encontre datos de contacto en la imagen.")
            return
        sheet = get_sheet()
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            lead.get("nombre", ""),
            lead.get("cargo", ""),
            lead.get("empresa", ""),
            lead.get("email", ""),
            lead.get("telefono", ""),
            lead.get("web", ""),
            lead.get("linkedin", ""),
            lead.get("notas", ""),
            "Nuevo",
        ]
        sheet.append_row(row)
        text = (
            "Lead guardado en Google Sheets:\n\n"
            + "\n".join(
                f"{k}: {v}"
                for k, v in zip(HEADERS, row)
                if v and k != "Estado"
            )
        )
        await msg.edit_text(text)
    except Exception as e:
        logger.error("Error en handle_photo: %s", e)
        await msg.edit_text("Error al procesar la imagen. Intentalo de nuevo.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text("Solo acepto imagenes. Sube un JPG o PNG.")
        return
    msg = await update.message.reply_text("Analizando imagen con IA...")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        image_bytes = bytes(await tg_file.download_as_bytearray())
        lead = extract_lead_from_image(image_bytes, mime_type=doc.mime_type)
        if not lead or not any(v for v in lead.values()):
            await msg.edit_text("No encontre datos de contacto en la imagen.")
            return
        sheet = get_sheet()
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            lead.get("nombre", ""),
            lead.get("cargo", ""),
            lead.get("empresa", ""),
            lead.get("email", ""),
            lead.get("telefono", ""),
            lead.get("web", ""),
            lead.get("linkedin", ""),
            lead.get("notas", ""),
            "Nuevo",
        ]
        sheet.append_row(row)
        text = (
            "Lead guardado en Google Sheets:\n\n"
            + "\n".join(
                f"{k}: {v}"
                for k, v in zip(HEADERS, row)
                if v and k != "Estado"
            )
        )
        await msg.edit_text(text)
    except Exception as e:
        logger.error("Error en handle_document: %s", e)
        await msg.edit_text("Error al procesar la imagen. Intentalo de nuevo.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
