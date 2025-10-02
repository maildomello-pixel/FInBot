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

import sqlite3
import os
import json
import locale
import httpx
import dateparser
import time
import unicodedata
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters
)

# ====================== CONFIGURAÇÃO ======================

try:
    locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, "pt_BR")
    except locale.Error:
        pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ====================== FUNÇÕES AUXILIARES ======================

def fmt(valor):
    """Formata um número em moeda brasileira (R$)."""
    try:
        valor = float(valor)
    except (ValueError, TypeError):
        valor = 0.0
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_db_connection():
    """Cria e retorna uma conexão com o banco de dados SQLite."""
    return sqlite3.connect("finbot.db")

def remover_acentos(texto):
    """Remove acentos de um texto"""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

def parse_date(date_str):
    """Converte string de data para objeto date, suporta vários formatos"""
    if not date_str:
        return datetime.now().date()
    
    # Remove espaços extras
    date_str = date_str.strip().lower()
    
    # Palavras-chave para datas relativas
    date_map = {
        'hoje': datetime.now().date(),
        'today': datetime.now().date(),
        'ontem': datetime.now().date() - timedelta(days=1),
        'yesterday': datetime.now().date() - timedelta(days=1),
        'amanhã': datetime.now().date() + timedelta(days=1),
        'amanha': datetime.now().date() + timedelta(days=1),
        'tomorrow': datetime.now().date() + timedelta(days=1)
    }
    
    if date_str in date_map:
        return date_map[date_str]
    
    # Tenta vários formatos numéricos
    formats = [
        '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y',
        '%d/%m/%y', '%d-%m-%y', '%d.%m.%y',
        '%d/%m', '%d-%m', '%d.%m'  # Assume ano atual
    ]
    
    for fmt_str in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt_str).date()
            # Se não tem ano, assume ano atual
            if fmt_str in ['%d/%m', '%d-%m', '%d.%m']:
                parsed_date = parsed_date.replace(year=datetime.now().year)
            return parsed_date
        except ValueError:
            continue
    
    # Tenta com dateparser como fallback
    try:
        parsed = dateparser.parse(date_str, languages=['pt'])
        if parsed:
            return parsed.date()
    except:
        pass
    
    return datetime.now().date()

def call_gemini_natural_language(text):
    """
    Usa Gemini para interpretar linguagem natural e extrair informações financeiras.
    """
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
    Analise a seguinte frase e extraia informações sobre uma transação financeira.
    Retorne APENAS um objeto JSON válido com os seguintes campos:
    - "type": "income" para receitas/ganhos/salário ou "expense" para gastos/despesas
    - "amount": valor numérico da transação (apenas número, sem R$)
    - "description": breve descrição do item
    - "confidence": 0-100 indicando sua confiança na interpretação

    Se a frase NÃO for sobre finanças OU for uma pergunta genérica sobre economia, 
    retorne: {{"type": "none", "confidence": 0}}

    Frase: "{text}"

    Responda APENAS com o JSON, sem texto adicional.
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 300
        }
    }

    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=30.0)

            if response.status_code != 200:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None

            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]

            result = json.loads(raw_text)

            # Só processar se tiver confiança razoável e não for "none"
            if result.get("type") == "none" or result.get("confidence", 0) < 60:
                return None

            # Processa o valor
            try:
                if "amount" in result:
                    amount_str = str(result["amount"]).replace(",", ".").replace("R$", "").strip()
                    # Remove pontos de milhar e converte para float
                    if "." in amount_str and "," in amount_str:
                        # Formato brasileiro: 1.500,99 -> 1500.99
                        parts = amount_str.split(",")
                        integer_part = parts[0].replace(".", "")
                        decimal_part = parts[1] if len(parts) > 1 else "00"
                        amount_str = f"{integer_part}.{decimal_part}"
                    elif "," in amount_str:
                        # Formato europeu: 1500,99 -> 1500.99
                        amount_str = amount_str.replace(",", ".")
                    result["amount"] = float(amount_str)
            except (ValueError, TypeError):
                return None

            return result

        except Exception as e:
            print(f"Erro Gemini (tentativa {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue

    return None

def call_gemini_question(text):
    """Usa Gemini para responder perguntas sobre finanças."""
    if not GEMINI_API_KEY:
        return "❗ Gemini API Key não configurada."

    prompt = f"""
    Você é um assistente financeiro útil e amigável que responde em português brasileiro.
    Forneça conselhos práticos e acionáveis sobre finanças pessoais.

    Pergunta: "{text}"

    Responda de forma clara e direta, sem incluir JSON ou estruturas de dados.
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 500
        }
    }

    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        if response.status_code == 200:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"Erro ao consultar Gemini: {response.text}"
    except Exception as e:
        return f"Erro de conexão: {str(e)}"

# ====================== INICIALIZAÇÃO DO BANCO ======================

def init_database():
    """Inicializa o banco de dados criando as tabelas necessárias"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Cria tabelas se não existirem
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receitas_parceiro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_transacao DATE,
            pago INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fixos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fatura_cartao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pago INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()

# ====================== COMANDOS DO BOT ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Mensagem de boas-vindas"""
    welcome_msg = (
        "🤖 Olá! Bem-vindo ao FinBot!\n\n"
        "Eu sou seu assistente financeiro pessoal. Posso ajudar você a:\n"
        "💰 Registrar receitas e despesas\n"
        "📊 Acompanhar seu saldo\n"
        "📄 Gerar relatórios mensais\n"
        "🧘 Aplicar o Método Traz Paz\n\n"
        "Você pode usar comandos ou simplesmente me dizer em linguagem natural! "
        "Por exemplo: 'Gastei 20 reais com Redbull'\n\n"
        "Digite /ajuda para ver todos os comandos disponíveis."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajuda - Lista todos os comandos disponíveis"""
    msg = (
        "📌 COMANDOS DISPONÍVEIS\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "🚀 INICIAR\n"
        "/start - Iniciar o FinBot\n"
        "/ajuda - Mostrar esta mensagem\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💵 RECEITAS (ENTRADAS)\n"
        "/addreceita <valor> <descrição>\n"
        "   Ex: /addreceita 2000 Salário\n\n"

        "/addreceita_parceiro <valor> <descrição>\n"
        "   Ex: /addreceita_parceiro 1500 Salário\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛒 DESPESAS (SAÍDAS)\n"
        "/addgasto <valor> <descrição>\n"
        "   Ex: /addgasto 50 Supermercado\n"
        "   Você escolherá a categoria: Débito, Crédito, Vale ou Pix\n"
        "   E depois informará a data do gasto\n\n"

        "/fixo <valor> <descrição>\n"
        "   Ex: /fixo 1200 Aluguel\n"
        "   Para despesas fixas mensais\n\n"

        "/vale <valor>\n"
        "   Ex: /vale 800\n"
        "   Registrar vale-alimentação recebido\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 CONSULTAS E RELATÓRIOS\n"
        "/saldo - Ver saldo atual\n"
        "/top3 - Ver os 3 maiores gastos\n"
        "/relatorio - Relatório mensal completo\n"
        "/mtp - Aplicar Método Traz Paz\n"
        "/fatura - Ver fatura do cartão de crédito\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 INTELIGÊNCIA ARTIFICIAL\n"
        "/ia <pergunta> - Fazer pergunta à IA\n"
        "   Ex: /ia Como posso economizar?\n\n"

        "💬 LINGUAGEM NATURAL\n"
        "Você pode simplesmente me dizer:\n"
        "   • 'Gastei 20 no Redbull'\n"
        "   • 'Recebi 3000 de salário'\n"
        "   • 'Paguei 50 de uber'\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🗑️ GERENCIAMENTO\n"
        "/reset - Apagar todos os dados\n"
        "   ⚠️ CUIDADO: Esta ação não pode ser desfeita!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def addreceita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addreceita - Registra uma receita (entrada) pessoal"""
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /addreceita <valor> <descrição>\n"
            "Ex: /addreceita 2000 Salário",
            parse_mode="Markdown"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receitas (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Receita registrada!\n💰 {fmt(valor)} - {descricao}",
        parse_mode="Markdown"
    )

async def addreceita_parceiro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addreceita_parceiro - Registra receita do parceiro(a)"""
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /addreceita_parceiro <valor> <descrição>\n"
            "Ex: /addreceita_parceiro 1500 Salário",
            parse_mode="Markdown"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receitas_parceiro (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Receita da parceira registrada!\n💰 {fmt(valor)} - {descricao}",
        parse_mode="Markdown"
    )

async def addgasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addgasto - Registra um gasto com seleção de categoria"""
    try:
        if not context.args:
            raise ValueError("Nenhum argumento fornecido")
            
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
        
    except (IndexError, ValueError) as e:
        await update.message.reply_text(
            "❗ *Uso correto:* `/addgasto <valor> <descrição>`\n\n"
            "📝 *Exemplo:*\n"
            "• `/addgasto 50 Supermercado`\n\n"
            "Você selecionará a categoria e depois informará a data.",
            parse_mode="Markdown"
        )
        return
    
    # Armazena temporariamente os dados do gasto para usar depois na seleção da data
    context.user_data['pending_gasto'] = {
        'valor': valor,
        'descricao': descricao
    }
    
    # Cria botões interativos para seleção de categoria
    keyboard = [
        [InlineKeyboardButton("💳 Débito", callback_data=f"débito|{valor}|{descricao}")],
        [InlineKeyboardButton("💎 Crédito", callback_data=f"crédito|{valor}|{descricao}")],
        [InlineKeyboardButton("🍽️ Vale-Alimentação", callback_data=f"alimentação|{valor}|{descricao}")],
        [InlineKeyboardButton("📱 Pix", callback_data=f"pix|{valor}|{descricao}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🛒 *Selecione a categoria para:*\n"
        f"💰 {fmt(valor)} - {descricao}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para botões interativos - Processa a seleção de categoria do gasto"""
    query = update.callback_query
    await query.answer()
    
    # Extrai dados do callback: categoria|valor|descricao
    data_parts = query.data.split("|")
    categoria = data_parts[0]
    valor = float(data_parts[1])
    descricao = data_parts[2]
    
    # Armazena os dados da categoria selecionada
    context.user_data['pending_gasto'] = {
        'valor': valor,
        'descricao': descricao,
        'categoria': categoria
    }
    
    # Emojis por categoria
    emoji_map = {
        "débito": "💳",
        "crédito": "💎",
        "alimentação": "🍽️",
        "pix": "📱"
    }
    
    await query.edit_message_text(
        f"✅ *Categoria selecionada!*\n"
        f"{emoji_map.get(categoria, '💰')} {fmt(valor)} - {descricao}\n"
        f"🏷️ Categoria: {categoria.capitalize()}\n\n"
        f"📅 *Quando foi esse gasto?*\n"
        f"Você pode responder com:\n"
        f"• 'hoje', 'ontem', 'amanhã'\n"
        f"• '25/09', '25/09/2024'\n"
        f"• Ou qualquer data no formato DD/MM/AAAA",
        parse_mode="Markdown"
    )

async def fixo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /fixo - Registra uma despesa fixa mensal"""
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /fixo <valor> <descrição>\n"
            "Ex: /fixo 1200 Aluguel",
            parse_mode="Markdown"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO fixos (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Despesa fixa registrada!\n🏠 {fmt(valor)} - {descricao}",
        parse_mode="Markdown"
    )

async def vale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /vale - Registra recebimento de vale-alimentação"""
    try:
        valor = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /vale <valor>\n"
            "Ex: /vale 800",
            parse_mode="Markdown"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vales (valor) VALUES (?)", (valor,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Vale-alimentação registrado!\n🍽️ {fmt(valor)}",
        parse_mode="Markdown"
    )

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /saldo - Mostra o saldo atual consolidado"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Soma todas as receitas
    cursor.execute("SELECT SUM(valor) FROM receitas")
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM receitas_parceiro")
    total_receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM vales")
    total_vales = cursor.fetchone()[0] or 0

    # Soma todas as despesas
    cursor.execute("SELECT SUM(valor) FROM gastos")
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM fixos")
    total_fixos = cursor.fetchone()[0] or 0

    # Calcula gastos com alimentação (para descontar do vale)
    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'alimentação'")
    total_gastos_alimentacao = cursor.fetchone()[0] or 0

    # Calcula saldo do vale-alimentação
    saldo_vale = total_vales - total_gastos_alimentacao

    conn.close()

    # Calcula saldo final (considerando o vale como parte das receitas, mas descontando os gastos com alimentação)
    saldo_final = total_receitas + total_receitas_parceiro + saldo_vale - total_gastos - total_fixos

    msg = (
        "💳 SALDO ATUAL\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Receitas: {fmt(total_receitas + total_receitas_parceiro)}\n"
        f"🍽️ Vales: {fmt(total_vales)} (Saldo: {fmt(saldo_vale)})\n"
        f"🛒 Gastos: {fmt(total_gastos)}\n"
        f"🏠 Fixos: {fmt(total_fixos)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Saldo: {fmt(saldo_final)}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def top3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /top3 - Mostra os 3 maiores gastos"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor, descricao, categoria FROM gastos ORDER BY valor DESC LIMIT 3")
    top = cursor.fetchall()
    conn.close()

    if not top:
        await update.message.reply_text("📊 Nenhum gasto registrado ainda.")
        return

    msg = "🔥 TOP 3 MAIORES GASTOS\n━━━━━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇", "🥈", "🥉"]

    for i, gasto in enumerate(top):
        msg += f"{medals[i]} {fmt(gasto[0])} - {gasto[1]} ({gasto[2]})\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def fatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /fatura - Mostra a fatura do cartão de crédito"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Busca gastos no crédito e itens da fatura
    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'crédito'")
    total_credito = cursor.fetchone()[0] or 0

    cursor.execute("SELECT descricao, valor FROM fatura_cartao WHERE pago = 0")
    itens_fatura = cursor.fetchall()

    conn.close()

    msg = "💎 FATURA DO CARTÃO DE CRÉDITO\n━━━━━━━━━━━━━━━━━━━━━━\n"

    if itens_fatura:
        for descricao, valor in itens_fatura:
            msg += f"• {descricao}: {fmt(valor)}\n"
        msg += f"\n💰 Total a pagar: {fmt(total_credito)}"
    else:
        msg += "Nenhuma compra no crédito pendente."

    await update.message.reply_text(msg, parse_mode="Markdown")

async def mtp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /mtp - Aplica o Método Traz Paz para planejamento financeiro"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Calcula totais
    cursor.execute("SELECT SUM(valor) FROM receitas")
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM receitas_parceiro")
    total_receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM vales")
    total_vales = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM gastos")
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM fixos")
    total_fixos = cursor.fetchone()[0] or 0

    conn.close()

    # Calcula saldo e aplica MTP
    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos

    if saldo <= 0:
        await update.message.reply_text(
            "⚠️ Saldo insuficiente\n"
            "Não há saldo positivo para aplicar o Método Traz Paz.",
            parse_mode="Markdown"
        )
        return

    guardar = saldo * 0.5  # 50% para guardar
    livre = saldo * 0.5    # 50% livre para gastar
    reserva_emergencia = guardar * 0.5  # 50% da reserva para emergência
    reserva_dividas = guardar * 0.5     # 50% da reserva para dívidas

    msg = (
        "🧘 MÉTODO TRAZ PAZ (MTP)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Saldo total: {fmt(saldo)}\n\n"
        f"💎 Guardar (50%): {fmt(guardar)}\n"
        f"   • Emergência: {fmt(reserva_emergencia)}\n"
        f"   • Dívidas: {fmt(reserva_dividas)}\n\n"
        f"🎉 Livre para gastar (50%): {fmt(livre)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "O MTP sugere guardar 50% e gastar 50% do seu saldo."
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /relatorio - Gera relatório mensal completo e detalhado"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Busca todas as transações
    cursor.execute("SELECT descricao, valor FROM receitas")
    receitas = cursor.fetchall()

    cursor.execute("SELECT descricao, valor FROM receitas_parceiro")
    receitas_parceiro = cursor.fetchall()

    cursor.execute("SELECT valor, descricao, categoria FROM gastos")
    gastos = cursor.fetchall()

    cursor.execute("SELECT descricao, valor FROM fixos")
    fixos = cursor.fetchall()

    cursor.execute("SELECT valor FROM vales")
    vales = cursor.fetchall()

    # Calcula totais
    cursor.execute("SELECT SUM(valor) FROM receitas")
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM receitas_parceiro")
    total_receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM gastos")
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM fixos")
    total_fixos = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM vales")
    total_vales = cursor.fetchone()[0] or 0

    # Calcula gastos com alimentação
    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'alimentação'")
    total_gastos_alimentacao = cursor.fetchone()[0] or 0

    # Calcula saldo do vale
    saldo_vale = total_vales - total_gastos_alimentacao

    conn.close()

    # Calcula saldo
    saldo = total_receitas + total_receitas_parceiro + saldo_vale - total_gastos - total_fixos

    # Monta relatório
    msg = "📄 RELATÓRIO MENSAL\n" + "━" * 30 + "\n\n"

    # Receitas
    msg += "💰 RECEITAS\n"
    if receitas or receitas_parceiro:
        for rec in receitas:
            msg += f"• {rec[0]}: {fmt(rec[1])}\n"
        for rec in receitas_parceiro:
            msg += f"• {rec[0]} (parceira): {fmt(rec[1])}\n"
        msg += f"Total: {fmt(total_receitas + total_receitas_parceiro)}\n\n"
    else:
        msg += "Nenhuma receita registrada\n\n"

    # Vale-alimentação
    msg += "🍽️ VALE-ALIMENTAÇÃO\n"
    if vales:
        for val in vales:
            msg += f"• {fmt(val[0])}\n"
        msg += f"Total recebido: {fmt(total_vales)}\n"
        msg += f"Gastos com alimentação: {fmt(total_gastos_alimentacao)}\n"
        msg += f"Saldo do vale: {fmt(saldo_vale)}\n\n"
    else:
        msg += "Nenhum vale registrado\n\n"

    # Gastos
    msg += "🛒 GASTOS\n"
    if gastos:
        for g in gastos:
            msg += f"• {g[1]} ({g[2]}): {fmt(g[0])}\n"
        msg += f"Total: {fmt(total_gastos)}\n\n"
    else:
        msg += "Nenhum gasto registrado\n\n"

    # Despesas Fixas
    msg += "🏠 DESPESAS FIXAS\n"
    if fixos:
        for f in fixos:
            msg += f"• {f[0]}: {fmt(f[1])}\n"
        msg += f"Total: {fmt(total_fixos)}\n\n"
    else:
        msg += "Nenhuma despesa fixa\n\n"

    # Saldo
    msg += "━" * 30 + "\n"
    msg += f"💵 SALDO FINAL: {fmt(saldo)}"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /reset - Apaga todos os dados do banco de dados com confirmação"""
    # Cria botões de confirmação
    keyboard = [
        [InlineKeyboardButton("✅ Sim, resetar tudo", callback_data="reset_confirm")],
        [InlineKeyboardButton("❌ Não, cancelar", callback_data="reset_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚠️ ATENÇÃO: RESET DE DADOS\n\n"
        "Você tem certeza que deseja resetar todos os dados?\n"
        "❗ Esta ação não poderá ser desfeita!\n\n"
        "Todos os registros de receitas, gastos, fixos e vales serão perdidos.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def reset_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para os botões de confirmação do reset"""
    query = update.callback_query
    await query.answer()

    if query.data == "reset_confirm":
        # Executa o reset
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM receitas")
        cursor.execute("DELETE FROM receitas_parceiro")
        cursor.execute("DELETE FROM gastos")
        cursor.execute("DELETE FROM fixos")
        cursor.execute("DELETE FROM vales")
        cursor.execute("DELETE FROM fatura_cartao")

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "🗑️ Todos os dados foram apagados!\n"
            "O banco de dados foi resetado com sucesso.",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✅ Reset cancelado.\n"
            "Seus dados estão seguros.",
            parse_mode="Markdown"
        )

async def ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ia - Faz uma pergunta à IA sobre finanças"""
    user_text = " ".join(context.args)

    if not user_text:
        await update.message.reply_text(
            "❗ Por favor, envie uma pergunta para a IA.\n"
            "Ex: /ia Como posso economizar dinheiro?",
            parse_mode="Markdown"
        )
        return

    # Mostra indicador de "digitando..."
    await update.message.chat.send_action("typing")

    answer = call_gemini_question(user_text)
    await update.message.reply_text(f"🤖 IA:\n\n{answer}", parse_mode="Markdown")

# ====================== HANDLER DE LINGUAGEM NATURAL ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para mensagens em linguagem natural (não-comandos).
    Usa Gemini para interpretar a mensagem e extrair informações financeiras.
    """
    text = update.message.text

    # PRIMEIRO: Verifica se é vale-alimentação analisando o texto original
    texto_sem_acentos = remover_acentos(text.lower())
    palavras_vale = ['vale', 'alimentacao', 'va', 'vr', 'refeicao', 'ticket', 'alimentação']
    
    # Verifica se o texto original contém palavras relacionadas a vale
    is_vale_texto = any(palavra in texto_sem_acentos for palavra in palavras_vale)

    # Tenta interpretar a mensagem com Gemini
    result = call_gemini_natural_language(text)

    if not result:
        # Se não conseguiu interpretar mas detectou que é sobre vale
        if is_vale_texto:
            try:
                # Tenta extrair o valor do texto diretamente
                numeros = re.findall(r"[\d]+[.,\d]*", text)
                if numeros:
                    valor_str = numeros[0].replace(',', '.')
                    valor = float(valor_str)
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO vales (valor) VALUES (?)", (valor,))
                    conn.commit()
                    conn.close()

                    await update.message.reply_text(
                        f"✅ *Vale-alimentação registrado automaticamente!*\n🍽️ {fmt(valor)}",
                        parse_mode="Markdown"
                    )
                    return
            except (ValueError, IndexError):
                pass

        # Não conseguiu interpretar ou não é sobre finanças
        await update.message.reply_text(
            "🤔 Desculpe, não entendi. Você pode:\n"
            "• Usar um comando (ex: /addgasto 20 Redbull)\n"
            "• Me dizer em linguagem natural (ex: 'Gastei 20 com Redbull')\n"
            "• Ver todos os comandos com /ajuda",
            parse_mode="Markdown"
        )
        return

    transaction_type = result.get("type")
    description = result.get("description", "Sem descrição")
    amount = result.get("amount", 0)

    if amount <= 0:
        await update.message.reply_text(
            "❗ Não consegui identificar o valor da transação. "
            "Tente novamente ou use um comando como /addgasto 20 Redbull",
            parse_mode="Markdown"
        )
        return

    # Verifica se é vale-alimentação (detecção mais abrangente)
    desc_sem_acentos = remover_acentos(description.lower())
    is_vale_desc = any(palavra in desc_sem_acentos for palavra in palavras_vale)
    
    # Combina as duas verificações
    is_vale = is_vale_texto or is_vale_desc

    # Se for um gasto e for relacionado a vale-alimentação, registra automaticamente como alimentação
    if transaction_type == "expense" and is_vale:
        # Armazena temporariamente para perguntar a data
        context.user_data['pending_gasto'] = {
            'valor': float(amount),
            'descricao': description,
            'categoria': 'alimentação'
        }
        
        await update.message.reply_text(
            f"✅ *Gasto com vale-alimentação identificado!*\n🍽️ {fmt(amount)} - {description}\n\n"
            f"📅 *Quando foi esse gasto?*\n"
            f"Você pode responder com:\n"
            f"• 'hoje', 'ontem', 'amanhã'\n"
            f"• '25/09', '25/09/2024'\n"
            f"• Ou qualquer data no formato DD/MM/AAAA",
            parse_mode="Markdown"
        )
        return

    elif transaction_type == "income" and is_vale:
        # Registra como vale-alimentação na tabela correta
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO vales (valor) VALUES (?)", (float(amount),))
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ *Vale-alimentação registrado automaticamente!*\n🍽️ {fmt(amount)}",
            parse_mode="Markdown"
        )

    elif transaction_type == "income":
        # Registra receita normalmente
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO receitas (descricao, valor) VALUES (?, ?)", (description, float(amount)))
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ *Receita registrada automaticamente!*\n💰 {fmt(amount)} - {description}",
            parse_mode="Markdown"
        )

    elif transaction_type == "expense":
        # Armazena temporariamente os dados do gasto
        context.user_data['pending_gasto'] = {
            'valor': float(amount),
            'descricao': description
        }
        
        # Mostra botões de categoria
        keyboard = [
            [InlineKeyboardButton("💳 Débito", callback_data=f"débito|{float(amount)}|{description}")],
            [InlineKeyboardButton("💎 Crédito", callback_data=f"crédito|{float(amount)}|{description}")],
            [InlineKeyboardButton("🍽️ Vale-Alimentação", callback_data=f"alimentação|{float(amount)}|{description}")],
            [InlineKeyboardButton("📱 Pix", callback_data=f"pix|{float(amount)}|{description}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"✅ *Gasto identificado automaticamente!*\n🛒 {fmt(amount)} - {description}\n\n"
            "Por favor, selecione a categoria:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def handle_date_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para respostas de data após seleção de categoria
    """
    # Verifica se há um gasto pendente aguardando data
    if 'pending_gasto' not in context.user_data:
        await update.message.reply_text(
            "🤔 Não tenho um gasto pendente. Por favor, registre um gasto primeiro.",
            parse_mode="Markdown"
        )
        return

    pending_gasto = context.user_data['pending_gasto']
    user_date_input = update.message.text.strip()
    
    # Parse da data
    data_transacao = parse_date(user_date_input)
    data_str = data_transacao.strftime('%Y-%m-%d')
    
    # Salva no banco de dados
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if pending_gasto['categoria'] == "crédito":
        # Se for crédito, adiciona também à fatura do cartão
        cursor.execute(
            "INSERT INTO fatura_cartao (descricao, valor) VALUES (?, ?)",
            (pending_gasto['descricao'], pending_gasto['valor'])
        )
    
    # Insere com data personalizada
    cursor.execute(
        "INSERT INTO gastos (valor, descricao, categoria, data_transacao) VALUES (?, ?, ?, ?)",
        (pending_gasto['valor'], pending_gasto['descricao'], pending_gasto['categoria'], data_str)
    )
    conn.commit()
    conn.close()
    
    # Remove o gasto pendente
    del context.user_data['pending_gasto']
    
    # Emojis por categoria
    emoji_map = {
        "débito": "💳",
        "crédito": "💎",
        "alimentação": "🍽️",
        "pix": "📱"
    }
    
    data_display = "hoje" if data_transacao == datetime.now().date() else data_transacao.strftime('%d/%m/%Y')
    
    await update.message.reply_text(
        f"✅ *Gasto registrado com sucesso!*\n"
        f"{emoji_map.get(pending_gasto['categoria'], '💰')} {fmt(pending_gasto['valor'])} - {pending_gasto['descricao']}\n"
        f"📅 Data: {data_display}\n"
        f"🏷️ Categoria: {pending_gasto['categoria'].capitalize()}",
        parse_mode="Markdown"
    )

# ====================== FILTROS PARA HANDLERS ======================

def is_date_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica se a mensagem é uma resposta de data para um gasto pendente"""
    return 'pending_gasto' in context.user_data and 'categoria' in context.user_data['pending_gasto']

# ====================== MAIN ======================

def main():
    """Função principal que inicia o bot"""
    # Inicializa banco de dados
    init_database()

    # Verifica token do Telegram
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

    # Cria aplicação
    app = Application.builder().token(token).build()

    # Registra handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("addreceita", addreceita))
    app.add_handler(CommandHandler("addreceita_parceiro", addreceita_parceiro))
    app.add_handler(CommandHandler("addgasto", addgasto))
    app.add_handler(CommandHandler("fixo", fixo))
    app.add_handler(CommandHandler("vale", vale))
    app.add_handler(CommandHandler("saldo", saldo))
    app.add_handler(CommandHandler("top3", top3))
    app.add_handler(CommandHandler("fatura", fatura))
    app.add_handler(CommandHandler("mtp", mtp))
    app.add_handler(CommandHandler("relatorio", relatorio))
    app.add_handler(CommandHandler("ia", ia))
    app.add_handler(CommandHandler("reset", reset))

    # Handlers para botões interativos
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(débito|crédito|alimentação|pix)\\|"))
    app.add_handler(CallbackQueryHandler(reset_button_handler, pattern="^(reset_confirm|reset_cancel)$"))

    # Handler para respostas de data (DEVE vir antes do handler de linguagem natural)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".*") & filters.Lambda(is_date_response), handle_date_response))

    # Handler para mensagens em linguagem natural (deve ser o último)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Inicia o bot
    print("🤖 FinBot com Gemini iniciado! Aguardando mensagens...")
    
    # Polling com reinício automático em caso de erro
    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False
            )
        except Exception as e:
            print(f"❌ Erro: {e}")
            print("🔄 Reiniciando em 10 segundos...")
            time.sleep(10)

if __name__ == "__main__":
    main()
