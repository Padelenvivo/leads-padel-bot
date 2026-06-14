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

TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SHEET_ID   = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS = json.loads(os.environ["GOOGLE_CREDENTIALS"])

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

HEADERS = ["Fecha", "Nombre", "Cargo", "Empresa", "Email",
           "Teléfono", "Web", "LinkedIn", "Notas", "Estado"]


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
                    "text": (
                        "Extrae la información de contacto de esta imagen "
                        "(puede ser tarjeta de visita, captura de LinkedIn, WhatsApp, "
                        "formulario web, perfil de red social, etc.).\n\n"
                        "Devuelve ÚNICAMENTE un JSON válido con estos campos "
                        "(deja el valor como cadena vacía \"\" si no aparece en la imagen):\n"
                        "{\n"
                        "  \"nombre\": \"\",\n"
                        "  \"cargo\": \"\",\n"
                        "  \"empresa\": \"\",\n"
                        "  \"email\": \"\",\n"
                        "  \"telefono\": \"\",\n"
                        "  \"web\": \"\",\n"
                        "  \"linkedin\": \"\",\n"
                        "  \"notas\": \"\"
"
                        "}\n\n"
                        "Solo el JSON, sin texto adicional ni bloques de código."
                    )
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
        "👋 *Bot de Leads activo*\n\n"
        "Mándame una foto de:\n"
        "• Tarjeta de visita\n"
        "• Captura de LinkedIn\n"
        "• Screenshot de WhatsApp\n"
        "• Cualquier perfil de contacto\n\n"
        "Extraeré los datos y los guardaré en Google Sheets automáticamente. 🚀",
        parse_mode="Markdown"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📸 Analizando imagen con IA...")
    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await tg_file.download_as_bytearray())
        lead = extract_lead_from_image(image_bytes)
        if not lead or not any(v for v in lead.values()):
            await msg.edit_text("❌ No encontré datos de contacto en la imagen.")
            return
        sheet = get_sheet()
        row = [
            datetime.now().strftime("%d/%m/%Y"),
            lead.get("nombre", ""), lead.get("cargo", ""), lead.get("empresa", ""),
            lead.get("email", ""), lead.get("telefono", ""), lead.get("web", ""),
            lead.get("linkedin", ""), lead.get("notas", ""), "Nuevo",
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        def f(val): return val if val else "—"
        reply_lines = ["✅ *Lead guardado en Google Sheets*\n", f"👤 *{f(lead.get('nombre'))}*"]
        if lead.get("cargo") or lead.get("empresa"):
            reply_lines.append(f"💼 {f(lead.get('cargo'))} · {f(lead.get('empresa'))}")
        if lead.get("email"): reply_lines.append(f"📧 {lead['email']}")
        if lead.get("telefono"): reply_lines.append(f"📱 {lead['telefono']}")
        if lead.get("web"): reply_lines.append(f"🌐 {lead['web']}")
        if lead.get("linkedin"): reply_lines.append(f"🔗 {lead['linkedin']}")
        if lead.get("notas"): reply_lines.append(f"\n_{lead['notas']}_")
        await msg.edit_text("\n".join(reply_lines), parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error procesando imagen")
        await msg.edit_text(f"❌ Error: {str(e)}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.mime_type.startswith("image/"):
        return
    msg = await update.message.reply_text("📎 Analizando archivo de imagen...")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        image_bytes = bytes(await tg_file.download_as_bytearray())
        lead = extract_lead_from_image(image_bytes, mime_type=doc.mime_type)
        if not lead or not any(v for v in lead.values()):
            await msg.edit_text("❌ No encontré datos de contacto en la imagen.")
            return
        sheet = get_sheet()
        row = [
            datetime.now().strftime("%d/%m/%Y"),
            lead.get("nombre", ""), lead.get("cargo", ""), lead.get("empresa", ""),
            lead.get("email", ""), lead.get("telefono", ""), lead.get("web", ""),
            lead.get("linkedin", ""), lead.get("notas", ""), "Nuevo",
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        def f(val): return val if val else "—"
        reply = f"✅ *Lead guardado*\n\n👤 *{f(lead.get('nombre'))}*\n💼 {f(lead.get('cargo'))} · {f(lead.get('empresa'))}\n📧 {f(lead.get('email'))}\n📱 {f(lead.get('telefono'))}"
        await msg.edit_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error procesando documento")
        await msg.edit_text(f"❌ Error: {str(e)}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    logger.info("Bot de leads iniciado ✓")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
