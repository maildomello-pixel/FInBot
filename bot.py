"""
FinBot - Telegram Bot para Gestão Financeira Pessoal (VERSÃO CORRIGIDA)
========================================================================
Correções principais:
1. ✅ Fluxo de data após categoria agora funciona corretamente
2. ✅ Melhor tratamento de erros e validações
3. ✅ Sistema de estados mais robusto
4. ✅ Feedback mais claro para o usuário
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
        '%d/%m', '%d-%m', '%d.%m'
    ]
    
    for fmt_str in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt_str).date()
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
    
    return None  # Retorna None se não conseguir parsear

def call_gemini_natural_language(text):
    """Usa Gemini para interpretar linguagem natural e extrair informações financeiras."""
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

            if result.get("type") == "none" or result.get("confidence", 0) < 60:
                return None

            # Processa o valor
            try:
                if "amount" in result:
                    amount_str = str(result["amount"]).replace(",", ".").replace("R$", "").strip()
                    if "." in amount_str and "," in amount_str:
                        parts = amount_str.split(",")
                        integer_part = parts[0].replace(".", "")
                        decimal_part = parts[1] if len(parts) > 1 else "00"
                        amount_str = f"{integer_part}.{decimal_part}"
                    elif "," in amount_str:
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
        return "Gemini API Key não configurada."

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
        "Olá! Bem-vindo ao FinBot!\n\n"
        "Eu sou seu assistente financeiro pessoal. Posso ajudar você a:\n"
        "• Registrar receitas e despesas\n"
        "• Acompanhar seu saldo\n"
        "• Gerar relatórios mensais\n"
        "• Aplicar o Método Traz Paz\n\n"
        "Você pode usar comandos ou simplesmente me dizer em linguagem natural! "
        "Por exemplo: 'Gastei 20 reais com Redbull'\n\n"
        "Digite /ajuda para ver todos os comandos disponíveis."
    )
    await update.message.reply_text(welcome_msg)

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajuda - Lista todos os comandos disponíveis"""
    msg = (
        "COMANDOS DISPONÍVEIS\n"
        "════════════════════════════════\n\n"

        "INICIAR\n"
        "/start - Iniciar o FinBot\n"
        "/ajuda - Mostrar esta mensagem\n\n"

        "RECEITAS (ENTRADAS)\n"
        "/addreceita <valor> <descrição>\n"
        "   Ex: /addreceita 2000 Salário\n\n"

        "/addreceita_parceiro <valor> <descrição>\n"
        "   Ex: /addreceita_parceiro 1500 Salário\n\n"

        "DESPESAS (SAÍDAS)\n"
        "/addgasto <valor> <descrição>\n"
        "   Ex: /addgasto 50 Supermercado\n\n"

        "/fixo <valor> <descrição>\n"
        "   Ex: /fixo 1200 Aluguel\n\n"

        "/vale <valor>\n"
        "   Ex: /vale 800\n\n"

        "CONSULTAS E RELATÓRIOS\n"
        "/saldo - Ver saldo atual\n"
        "/top3 - Ver os 3 maiores gastos\n"
        "/relatorio - Relatório mensal completo\n"
        "/mtp - Aplicar Método Traz Paz\n"
        "/fatura - Ver fatura do cartão de crédito\n\n"

        "INTELIGÊNCIA ARTIFICIAL\n"
        "/ia <pergunta> - Fazer pergunta à IA\n"
        "   Ex: /ia Como posso economizar?\n\n"

        "LINGUAGEM NATURAL\n"
        "Você pode simplesmente me dizer:\n"
        "• 'Gastei 20 no Redbull'\n"
        "• 'Recebi 3000 de salário'\n\n"

        "GERENCIAMENTO\n"
        "/reset - Apagar todos os dados"
    )
    await update.message.reply_text(msg)

async def addreceita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addreceita - Registra uma receita (entrada) pessoal"""
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Uso correto: /addreceita <valor> <descrição>\n"
            "Ex: /addreceita 2000 Salário"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receitas (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Receita registrada!\n{fmt(valor)} - {descricao}")

async def addreceita_parceiro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addreceita_parceiro - Registra receita do parceiro(a)"""
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Uso correto: /addreceita_parceiro <valor> <descrição>\n"
            "Ex: /addreceita_parceiro 1500 Salário"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receitas_parceiro (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Receita da parceira registrada!\n{fmt(valor)} - {descricao}")

async def addgasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addgasto - Registra um gasto com seleção de categoria"""
    try:
        if not context.args:
            raise ValueError("Nenhum argumento fornecido")
            
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
        
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Uso correto: /addgasto <valor> <descrição>\n"
            "Exemplo: /addgasto 50 Supermercado"
        )
        return
    
    # Armazena dados do gasto com estado
    context.user_data['pending_gasto'] = {
        'valor': valor,
        'descricao': descricao,
        'step': 'waiting_category'
    }
    
    # Botões de categoria
    keyboard = [
        [InlineKeyboardButton("Débito", callback_data="cat_débito")],
        [InlineKeyboardButton("Crédito", callback_data="cat_crédito")],
        [InlineKeyboardButton("Vale-Alimentação", callback_data="cat_alimentação")],
        [InlineKeyboardButton("Pix", callback_data="cat_pix")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Selecione a categoria:\n{fmt(valor)} - {descricao}",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para botões de categoria"""
    query = update.callback_query
    await query.answer()
    
    # Verifica se é um botão de categoria
    if query.data.startswith("cat_"):
        categoria = query.data.replace("cat_", "")
        
        # Atualiza dados do gasto pendente
        if 'pending_gasto' in context.user_data:
            context.user_data['pending_gasto']['categoria'] = categoria
            context.user_data['pending_gasto']['step'] = 'waiting_date'
            
            emoji_map = {
                "débito": "💳",
                "crédito": "💎",
                "alimentação": "🍽️",
                "pix": "📱"
            }
            
            await query.edit_message_text(
                f"Categoria selecionada: {emoji_map.get(categoria, '')} {categoria.capitalize()}\n"
                f"{fmt(context.user_data['pending_gasto']['valor'])} - {context.user_data['pending_gasto']['descricao']}\n\n"
                f"Quando foi esse gasto?\n"
                f"Você pode responder:\n"
                f"• 'hoje', 'ontem', 'amanhã'\n"
                f"• '25/09' ou '25/09/2024'\n"
                f"• DD/MM/AAAA"
            )
        else:
            await query.edit_message_text("Erro: dados do gasto não encontrados. Tente novamente com /addgasto")

async def fixo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /fixo - Registra uma despesa fixa mensal"""
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Sem descrição"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Uso correto: /fixo <valor> <descrição>\n"
            "Ex: /fixo 1200 Aluguel"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO fixos (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Despesa fixa registrada!\n{fmt(valor)} - {descricao}")

async def vale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /vale - Registra recebimento de vale-alimentação"""
    try:
        valor = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Uso correto: /vale <valor>\n"
            "Ex: /vale 800"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vales (valor) VALUES (?)", (valor,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Vale-alimentação registrado!\n{fmt(valor)}")

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /saldo - Mostra o saldo atual consolidado"""
    conn = get_db_connection()
    cursor = conn.cursor()

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

    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'alimentação'")
    total_gastos_alimentacao = cursor.fetchone()[0] or 0

    saldo_vale = total_vales - total_gastos_alimentacao

    conn.close()

    saldo_final = total_receitas + total_receitas_parceiro + saldo_vale - total_gastos - total_fixos

    msg = (
        "SALDO ATUAL\n"
        "════════════════════════════════\n"
        f"Receitas: {fmt(total_receitas + total_receitas_parceiro)}\n"
        f"Vales: {fmt(total_vales)} (Saldo: {fmt(saldo_vale)})\n"
        f"Gastos: {fmt(total_gastos)}\n"
        f"Fixos: {fmt(total_fixos)}\n"
        "════════════════════════════════\n"
        f"Saldo: {fmt(saldo_final)}"
    )

    await update.message.reply_text(msg)

async def top3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /top3 - Mostra os 3 maiores gastos"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor, descricao, categoria FROM gastos ORDER BY valor DESC LIMIT 3")
    top = cursor.fetchall()
    conn.close()

    if not top:
        await update.message.reply_text("Nenhum gasto registrado ainda.")
        return

    msg = "TOP 3 MAIORES GASTOS\n════════════════════════════════\n"
    medals = ["1.", "2.", "3."]

    for i, gasto in enumerate(top):
        msg += f"{medals[i]} {fmt(gasto[0])} - {gasto[1]} ({gasto[2]})\n"

    await update.message.reply_text(msg)

async def fatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /fatura - Mostra a fatura do cartão de crédito"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'crédito'")
    total_credito = cursor.fetchone()[0] or 0

    cursor.execute("SELECT descricao, valor FROM fatura_cartao WHERE pago = 0")
    itens_fatura = cursor.fetchall()

    conn.close()

    msg = "FATURA DO CARTÃO DE CRÉDITO\n════════════════════════════════\n"

    if itens_fatura:
        for descricao, valor in itens_fatura:
            msg += f"• {descricao}: {fmt(valor)}\n"
        msg += f"\nTotal a pagar: {fmt(total_credito)}"
    else:
        msg += "Nenhuma compra no crédito pendente."

    await update.message.reply_text(msg)

async def mtp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /mtp - Aplica o Método Traz Paz"""
    conn = get_db_connection()
    cursor = conn.cursor()

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

    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos

    if saldo <= 0:
        await update.message.reply_text("Saldo insuficiente para aplicar o Método Traz Paz.")
        return

    guardar = saldo * 0.5
    livre = saldo * 0.5
    reserva_emergencia = guardar * 0.5
    reserva_dividas = guardar * 0.5

    msg = (
        "MÉTODO TRAZ PAZ (MTP)\n"
        "════════════════════════════════\n"
        f"Saldo total: {fmt(saldo)}\n\n"
        f"Guardar (50%): {fmt(guardar)}\n"
        f"  • Emergência: {fmt(reserva_emergencia)}\n"
        f"  • Dívidas: {fmt(reserva_dividas)}\n\n"
        f"Livre (50%): {fmt(livre)}"
    )

    await update.message.reply_text(msg)

async def relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /relatorio - Gera relatório mensal completo"""
    conn = get_db_connection()
    cursor = conn.cursor()

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

    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'alimentação'")
    total_gastos_alimentacao = cursor.fetchone()[0] or 0

    saldo_vale = total_vales - total_gastos_alimentacao

    conn.close()

    saldo = total_receitas + total_receitas_parceiro + saldo_vale - total_gastos - total_fixos

    msg = "RELATÓRIO MENSAL\n" + "═" * 40 + "\n\n"

    msg += "RECEITAS\n"
    if receitas or receitas_parceiro:
        for rec in receitas:
            msg += f"• {rec[0]}: {fmt(rec[1])}\n"
        for rec in receitas_parceiro:
            msg += f"• {rec[0]} (parceira): {fmt(rec[1])}\n"
        msg += f"Total: {fmt(total_receitas + total_receitas_parceiro)}\n\n"
    else:
        msg += "Nenhuma receita\n\n"

    msg += "VALE-ALIMENTAÇÃO\n"
    if vales:
        for val in vales:
            msg += f"• {fmt(val[0])}\n"
        msg += f"Total: {fmt(total_vales)}\n"
        msg += f"Gastos: {fmt(total_gastos_alimentacao)}\n"
        msg += f"Saldo: {fmt(saldo_vale)}\n\n"
    else:
        msg += "Nenhum vale\n\n"

    msg += "GASTOS\n"
    if gastos:
        for g in gastos:
            msg += f"• {g[1]} ({g[2]}): {fmt(g[0])}\n"
        msg += f"Total: {fmt(total_gastos)}\n\n"
    else:
        msg += "Nenhum gasto\n\n"

    msg += "DESPESAS FIXAS\n"
    if fixos:
        for f in fixos:
            msg += f"• {f[0]}: {fmt(f[1])}\n"
        msg += f"Total: {fmt(total_fixos)}\n\n"
    else:
        msg += "Nenhuma despesa fixa\n\n"

    msg += "═" * 40 + "\n"
    msg += f"SALDO FINAL: {fmt(saldo)}"

    await update.message.reply_text(msg)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /reset - Apaga todos os dados"""
    keyboard = [
        [InlineKeyboardButton("Sim, resetar", callback_data="reset_confirm")],
        [InlineKeyboardButton("Não, cancelar", callback_data="reset_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "ATENÇÃO: RESET DE DADOS\n\n"
        "Tem certeza que deseja resetar todos os dados?\n"
        "Esta ação não pode ser desfeita!",
        reply_markup=reply_markup
    )

async def reset_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para confirmação do reset"""
    query = update.callback_query
    await query.answer()
if query.data == "reset_confirm":
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

        await query.edit_message_text("Todos os dados foram apagados!")
    else:
        await query.edit_message_text("Reset cancelado.")

async def ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ia - Faz pergunta à IA"""
    user_text = " ".join(context.args)

    if not user_text:
        await update.message.reply_text(
            "Por favor, envie uma pergunta.\n"
            "Ex: /ia Como posso economizar?"
        )
        return

    await update.message.chat.send_action("typing")
    answer = call_gemini_question(user_text)
    await update.message.reply_text(f"IA:\n\n{answer}")

# ====================== HANDLER DE LINGUAGEM NATURAL ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler principal para mensagens de texto.
    CORREÇÃO PRINCIPAL: Verifica PRIMEIRO se há fluxo pendente antes de processar com IA.
    """
    text = update.message.text.strip()

    # PRIORIDADE 1: Verifica se está aguardando data
    if 'pending_gasto' in context.user_data:
        pending = context.user_data['pending_gasto']
        
        if pending.get('step') == 'waiting_date':
            # Usuário está respondendo com a data
            data_transacao = parse_date(text)
            
            if data_transacao is None:
                await update.message.reply_text(
                    "Não consegui entender essa data.\n"
                    "Tente novamente com:\n"
                    "• 'hoje', 'ontem', 'amanhã'\n"
                    "• '25/09' ou '25/09/2024'\n"
                    "• DD/MM/AAAA"
                )
                return
            
            # Salva no banco
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if pending['categoria'] == "crédito":
                cursor.execute(
                    "INSERT INTO fatura_cartao (descricao, valor) VALUES (?, ?)",
                    (pending['descricao'], pending['valor'])
                )
            
            cursor.execute(
                "INSERT INTO gastos (valor, descricao, categoria, data_transacao) VALUES (?, ?, ?, ?)",
                (pending['valor'], pending['descricao'], pending['categoria'], data_transacao.strftime('%Y-%m-%d'))
            )
            conn.commit()
            conn.close()
            
            # Remove dados pendentes
            del context.user_data['pending_gasto']
            
            # Confirma registro
            emoji_map = {
                "débito": "💳",
                "crédito": "💎",
                "alimentação": "🍽️",
                "pix": "📱"
            }
            
            data_display = "hoje" if data_transacao == datetime.now().date() else data_transacao.strftime('%d/%m/%Y')
            
            await update.message.reply_text(
                f"Gasto registrado com sucesso!\n"
                f"{emoji_map.get(pending['categoria'], '')} {fmt(pending['valor'])} - {pending['descricao']}\n"
                f"Data: {data_display}\n"
                f"Categoria: {pending['categoria'].capitalize()}"
            )
            return

    # PRIORIDADE 2: Detecta vale-alimentação no texto original
    texto_sem_acentos = remover_acentos(text.lower())
    palavras_vale = ['vale', 'alimentacao', 'va', 'vr', 'refeicao', 'ticket', 'alimentação']
    is_vale_texto = any(palavra in texto_sem_acentos for palavra in palavras_vale)

    # PRIORIDADE 3: Tenta processar com Gemini
    result = call_gemini_natural_language(text)

    if not result:
        # Se mencionou vale mas Gemini não pegou, tenta extrair manualmente
        if is_vale_texto:
            try:
                numeros = re.findall(r"[\d]+[.,\d]*", text)
                if numeros:
                    valor_str = numeros[0].replace(',', '.')
                    valor = float(valor_str)
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO vales (valor) VALUES (?)", (valor,))
                    conn.commit()
                    conn.close()

                    await update.message.reply_text(f"Vale-alimentação registrado!\n{fmt(valor)}")
                    return
            except (ValueError, IndexError):
                pass

        # Não conseguiu interpretar
        await update.message.reply_text(
            "Não entendi. Você pode:\n"
            "• Usar um comando (ex: /addgasto 20 Redbull)\n"
            "• Me dizer em linguagem natural (ex: 'Gastei 20 com Redbull')\n"
            "• Ver comandos com /ajuda"
        )
        return

    # Processa resultado da Gemini
    transaction_type = result.get("type")
    description = result.get("description", "Sem descrição")
    amount = result.get("amount", 0)

    if amount <= 0:
        await update.message.reply_text(
            "Não consegui identificar o valor. "
            "Tente novamente ou use /addgasto 20 Redbull"
        )
        return

    # Detecta se é vale na descrição também
    desc_sem_acentos = remover_acentos(description.lower())
    is_vale_desc = any(palavra in desc_sem_acentos for palavra in palavras_vale)
    is_vale = is_vale_texto or is_vale_desc

    # Processa baseado no tipo
    if transaction_type == "expense" and is_vale:
        # Gasto com vale - pede data diretamente
        context.user_data['pending_gasto'] = {
            'valor': float(amount),
            'descricao': description,
            'categoria': 'alimentação',
            'step': 'waiting_date'
        }
        
        await update.message.reply_text(
            f"Gasto com vale-alimentação identificado!\n{fmt(amount)} - {description}\n\n"
            f"Quando foi esse gasto?\n"
            f"('hoje', 'ontem', '25/09', etc.)"
        )
        
    elif transaction_type == "income" and is_vale:
        # Recebeu vale
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO vales (valor) VALUES (?)", (float(amount),))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"Vale-alimentação registrado!\n{fmt(amount)}")

    elif transaction_type == "income":
        # Receita normal
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO receitas (descricao, valor) VALUES (?, ?)", (description, float(amount)))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"Receita registrada!\n{fmt(amount)} - {description}")

    elif transaction_type == "expense":
        # Gasto normal - armazena e pede categoria
        context.user_data['pending_gasto'] = {
            'valor': float(amount),
            'descricao': description,
            'step': 'waiting_category'
        }
        
        # Botões de categoria
        keyboard = [
            [InlineKeyboardButton("Débito", callback_data="cat_débito")],
            [InlineKeyboardButton("Crédito", callback_data="cat_crédito")],
            [InlineKeyboardButton("Vale-Alimentação", callback_data="cat_alimentação")],
            [InlineKeyboardButton("Pix", callback_data="cat_pix")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Gasto identificado!\n{fmt(amount)} - {description}\n\n"
            "Selecione a categoria:",
            reply_markup=reply_markup
        )

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
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(reset_button_handler, pattern="^reset_"))

    # Handler único para todas as mensagens de texto (DEVE SER O ÚLTIMO)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Inicia o bot
    print("FinBot iniciado! Aguardando mensagens...")
    
    # Polling com reinício automático em caso de erro
    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False
            )
        except Exception as e:
            print(f"Erro: {e}")
            print("Reiniciando em 10 segundos...")
            time.sleep(10)

if __name__ == "__main__":
    main()
  
