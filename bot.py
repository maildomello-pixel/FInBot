"""
FinBot - Telegram Bot para Gestão Financeira Pessoal
=====================================================
Bot inteligente que permite registrar receitas, despesas, gastos fixos e vale-alimentação,
além de gerar relatórios financeiros e aplicar o Método Traz Paz (MTP).

Features:
- Registro de transações via comandos ou linguagem natural
- Categorização de gastos com botões interativos
- Relatórios financeiros detalhados
- Integração com Gemini para processamento de linguagem natural
- Método Traz Paz para planejamento financeiro
- Controle de fatura do cartão de crédito
- Datas personalizadas para transações
- Vale-alimentação com desconto automático
- Novo fluxo: pergunta data APÓS seleção da categoria
"""

import os
import json
import sqlite3
import re
import requests
import dateparser
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# Conexão com SQLite (permitindo multi-thread)
conn = sqlite3.connect("finbot.db", check_same_thread=False)
cursor = conn.cursor()

# Criação das tabelas
cursor.execute('''CREATE TABLE IF NOT EXISTS gastos
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL, descricao TEXT, data TEXT, categoria TEXT, forma TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS receitas
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL, descricao TEXT, data TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS fixos
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL, descricao TEXT, data TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS metas
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT, valor REAL)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS parceiro
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL, descricao TEXT, data TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS vale_alimentacao
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL, descricao TEXT, data TEXT)''')
conn.commit()

# API Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def extract_json(text):
    """Extrai JSON válido de uma string, mesmo que venha texto extra"""
    try:
        return json.loads(text)
    except:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                return None
    return None

def call_gemini_natural_language(prompt: str):
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
            "maxOutputTokens": 300
        }
    }

    response = requests.post(
        f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=20
    )

    if response.status_code == 200:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return extract_json(text)
    else:
        raise Exception(f"Erro Gemini: {response.status_code} — {response.text}")

# --- FUNÇÕES DO BOT ---

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("👋 Olá! Sou seu assistente financeiro.")

async def add_gasto(update: Update, context: CallbackContext):
    texto = " ".join(context.args) if context.args else update.message.text

    try:
        parsed = call_gemini_natural_language(texto)
        if not parsed:
            await update.message.reply_text("⚠️ Não consegui interpretar sua mensagem.")
            return

        valor = parsed.get("amount")
        categoria = parsed.get("category")
        descricao = parsed.get("item", parsed.get("description", ""))
        data_str = parsed.get("date", str(datetime.today().date()))

        # Converter "ontem", "hoje", etc
        data = dateparser.parse(data_str)
        if not data:
            data = datetime.today()
        data_fmt = data.strftime("%Y-%m-%d")

        # Guardar info no contexto antes do botão
        context.user_data["pending_gasto"] = {
            "valor": valor,
            "descricao": descricao,
            "categoria": categoria,
            "data": data_fmt
        }

        # Botões
        keyboard = [
            [InlineKeyboardButton("💳 Débito", callback_data="forma|debito")],
            [InlineKeyboardButton("💸 Crédito", callback_data="forma|credito")],
            [InlineKeyboardButton("📲 Pix", callback_data="forma|pix")],
            [InlineKeyboardButton("🍽 Vale Alimentação", callback_data="forma|vale")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"💰 Valor: {valor} BRL\n📂 Categoria: {categoria}\n📝 Descrição: {descricao}\n📅 Data: {data_fmt}\n\nEscolha a forma de pagamento:",
            reply_markup=reply_markup
        )

    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro ao processar gasto: {e}")

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if "pending_gasto" not in context.user_data:
        await query.edit_message_text("⚠️ Nenhum gasto em andamento.")
        return

    pending = context.user_data["pending_gasto"]
    _, forma = query.data.split("|")

    # Inserir no banco
    if forma == "vale":
        cursor.execute("INSERT INTO vale_alimentacao (valor, descricao, data) VALUES (?, ?, ?)",
                       (pending["valor"], pending["descricao"], pending["data"]))
    else:
        cursor.execute("INSERT INTO gastos (valor, descricao, data, categoria, forma) VALUES (?, ?, ?, ?, ?)",
                       (pending["valor"], pending["descricao"], pending["data"], pending["categoria"], forma))
    conn.commit()

    await query.edit_message_text(
        f"✅ Registrado: R$ {pending['valor']} — {pending['descricao']} ({forma}) em {pending['data']}"
    )
    del context.user_data["pending_gasto"]

async def saldo(update: Update, context: CallbackContext):
    cursor.execute("SELECT SUM(valor) FROM receitas")
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM parceiro")
    total_receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM vale_alimentacao")
    saldo_vale = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM gastos WHERE forma != 'vale'")
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM fixos")
    total_fixos = cursor.fetchone()[0] or 0

    saldo_final = total_receitas + total_receitas_parceiro - total_gastos - total_fixos
    saldo_final_com_vale = saldo_final + saldo_vale

    await update.message.reply_text(
        f"📊 Saldo:\n💵 Receitas: R$ {total_receitas}\n👥 Parceiro: R$ {total_receitas_parceiro}\n"
        f"🛒 Gastos: R$ {total_gastos}\n🏠 Fixos: R$ {total_fixos}\n🍽 Vale Alimentação: R$ {saldo_vale}\n\n"
        f"💰 Saldo Final: R$ {saldo_final}\n💰 Saldo + Vale: R$ {saldo_final_com_vale}"
    )

async def mtp(update: Update, context: CallbackContext):
    cursor.execute("SELECT SUM(valor) FROM metas")
    total_metas = cursor.fetchone()[0] or 0
    await update.message.reply_text(f"🎯 Total em metas: R$ {total_metas}")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addgasto", add_gasto))
    app.add_handler(CommandHandler("saldo", saldo))
    app.add_handler(CommandHandler("mtp", mtp))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
    main()

