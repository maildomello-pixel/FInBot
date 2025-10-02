"""
FinBot - Telegram Bot para Gestão Financeira Pessoal
=====================================================
Bot inteligente que permite registrar receitas, despesas, gastos fixos e vale-alimentação,
além de gerar relatórios financeiros e aplicar o Método Traz Paz (MTP).

Features:
- Registro de transações via comandos ou linguagem natural
- Categorização de gastos com botões interativos
- Relatórios financeiros detalhados e exportação para PDF/Excel
- Integração com Gemini para processamento de linguagem natural
- Método Traz Paz para planejamento financeiro
- Controle de fatura do cartão de crédito
- Datas personalizadas para transações
- Vale-alimentação com desconto automático
- Metas de economia com acompanhamento
- Gráficos visuais de despesas
- Lembretes automáticos
- Categorias customizáveis
- Controle de orçamento
- Pagamentos recorrentes
- Dashboard interativo
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
import io
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

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'DejaVu Sans'
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

try:
    locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, "pt_BR")
    except locale.Error:
        pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

            if result.get("type") == "none" or result.get("confidence", 0) < 60:
                return None

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor_alvo REAL NOT NULL,
            valor_atual REAL DEFAULT 0,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluida INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lembretes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            dia_mes INTEGER NOT NULL,
            ativo INTEGER DEFAULT 1,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orcamento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            categoria TEXT,
            valor REAL NOT NULL,
            mes INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            UNIQUE(tipo, categoria, mes, ano)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recorrentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            dia_mes INTEGER NOT NULL,
            ativo INTEGER DEFAULT 1,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Mensagem de boas-vindas"""
    welcome_msg = (
        "🤖 Olá! Bem-vindo ao FinBot!\n\n"
        "Eu sou seu assistente financeiro pessoal. Posso ajudar você a:\n"
        "💰 Registrar receitas e despesas\n"
        "📊 Acompanhar seu saldo e orçamento\n"
        "📄 Gerar relatórios e gráficos\n"
        "🎯 Definir e acompanhar metas\n"
        "🔔 Configurar lembretes\n"
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
        "/addreceita_parceiro <valor> <descrição>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛒 DESPESAS (SAÍDAS)\n"
        "/addgasto <valor> <descrição>\n"
        "/fixo <valor> <descrição>\n"
        "/vale <valor>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 METAS DE ECONOMIA\n"
        "/metas - Ver todas as metas\n"
        "/addmeta <valor> <nome>\n"
        "   Ex: /addmeta 5000 Viagem para praia\n"
        "/progresso_meta <id> <valor>\n"
        "   Ex: /progresso_meta 1 500\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 GRÁFICOS E RELATÓRIOS\n"
        "/grafico - Gráfico de pizza das despesas\n"
        "/grafico_mensal - Evolução mensal\n"
        "/relatorio - Relatório do mês atual\n"
        "/relatorio_mes <mês> <ano> - Relatório de mês específico\n"
        "   Ex: /relatorio_mes 9 2024\n"
        "/saldo_mes <mês> <ano> - Saldo de mês específico\n"
        "/comparar_meses - Comparar mês atual com anterior\n"
        "/historico_meses - Últimos 6 meses\n"
        "/relatorio_detalhado - Relatório PDF\n"
        "/relatorio_exportar - Exportar para Excel\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔔 LEMBRETES\n"
        "/lembretes - Ver todos os lembretes\n"
        "/addlembrete <dia> <descrição>\n"
        "   Ex: /addlembrete 10 Pagar conta de luz\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏷️ CATEGORIAS\n"
        "/categorias - Ver categorias\n"
        "/addcategoria <nome>\n"
        "/removecategoria <nome>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 ORÇAMENTO\n"
        "/orcamento <valor> - Definir orçamento mensal\n"
        "/orcamento_categoria <categoria> <valor>\n"
        "   Ex: /orcamento_categoria Alimentação 500\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 PAGAMENTOS RECORRENTES\n"
        "/recorrentes - Ver todos recorrentes\n"
        "/addrecorrente <valor> <dia> <descrição>\n"
        "   Ex: /addrecorrente 100 15 Netflix\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📈 CONSULTAS\n"
        "/saldo - Ver saldo atual\n"
        "/dashboard - Visão geral completa\n"
        "/top3 - Ver 3 maiores gastos\n"
        "/fatura - Ver fatura do cartão\n"
        "/mtp - Aplicar Método Traz Paz\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 INTELIGÊNCIA ARTIFICIAL\n"
        "/ia <pergunta> - Fazer pergunta à IA\n\n"

        "💬 LINGUAGEM NATURAL\n"
        "Você pode simplesmente me dizer:\n"
        "   • 'Gastei 20 no Redbull'\n"
        "   • 'Recebi 3000 de salário'\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🗑️ GERENCIAMENTO\n"
        "/reset - Apagar todos os dados"
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
    
    context.user_data['pending_gasto'] = {
        'valor': valor,
        'descricao': descricao,
        'waiting_for_category': True
    }
    
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
    
    data_parts = query.data.split("|")
    categoria = data_parts[0]
    valor = float(data_parts[1])
    descricao = data_parts[2]
    
    context.user_data['pending_gasto'] = {
        'valor': valor,
        'descricao': descricao,
        'categoria': categoria,
        'waiting_for_date': True
    }
    
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

async def handle_date_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para respostas de data após seleção de categoria - BUG FIX #1"""
    if 'pending_gasto' not in context.user_data or not context.user_data['pending_gasto'].get('waiting_for_date'):
        return
    
    pending_gasto = context.user_data['pending_gasto']
    user_date_input = update.message.text.strip()
    
    data_transacao = parse_date(user_date_input)
    data_str = data_transacao.strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if pending_gasto['categoria'] == "crédito":
        cursor.execute(
            "INSERT INTO fatura_cartao (descricao, valor) VALUES (?, ?)",
            (pending_gasto['descricao'], pending_gasto['valor'])
        )
    
    if pending_gasto['categoria'] == "alimentação":
        cursor.execute("SELECT SUM(valor) FROM vales")
        total_vales = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'alimentação'")
        total_gastos_alimentacao = cursor.fetchone()[0] or 0
        saldo_vale = total_vales - total_gastos_alimentacao
        
        if saldo_vale < pending_gasto['valor']:
            conn.close()
            await update.message.reply_text(
                f"⚠️ *Saldo insuficiente no vale-alimentação!*\n"
                f"Saldo disponível: {fmt(saldo_vale)}\n"
                f"Valor do gasto: {fmt(pending_gasto['valor'])}",
                parse_mode="Markdown"
            )
            del context.user_data['pending_gasto']
            return
    
    cursor.execute(
        "INSERT INTO gastos (valor, descricao, categoria, data_transacao) VALUES (?, ?, ?, ?)",
        (pending_gasto['valor'], pending_gasto['descricao'], pending_gasto['categoria'], data_str)
    )
    conn.commit()
    conn.close()
    
    del context.user_data['pending_gasto']
    
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

async def metas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /metas - Lista todas as metas de economia"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, valor_alvo, valor_atual, concluida FROM metas ORDER BY concluida ASC, id DESC")
    todas_metas = cursor.fetchall()
    conn.close()

    if not todas_metas:
        await update.message.reply_text(
            "🎯 Nenhuma meta cadastrada ainda!\n\n"
            "Use /addmeta para criar uma nova meta:\n"
            "Ex: /addmeta 5000 Viagem para praia"
        )
        return

    msg = "🎯 SUAS METAS DE ECONOMIA\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for meta in todas_metas:
        meta_id, nome, valor_alvo, valor_atual, concluida = meta
        progresso = (valor_atual / valor_alvo * 100) if valor_alvo > 0 else 0
        
        if concluida:
            status = "✅"
        else:
            status = "🎯"
        
        msg += (
            f"{status} *Meta #{meta_id}: {nome}*\n"
            f"   Progresso: {fmt(valor_atual)} / {fmt(valor_alvo)} ({progresso:.1f}%)\n"
            f"   Faltam: {fmt(valor_alvo - valor_atual)}\n\n"
        )

    msg += "\n💡 Use /progresso_meta <id> <valor> para adicionar progresso"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def addmeta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addmeta - Adiciona uma nova meta de economia"""
    try:
        valor = float(context.args[0])
        nome = " ".join(context.args[1:]) if len(context.args) > 1 else "Meta sem nome"
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /addmeta <valor> <nome>\n"
            "Ex: /addmeta 5000 Viagem para praia"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO metas (nome, valor_alvo, valor_atual) VALUES (?, ?, 0)", (nome, valor))
    conn.commit()
    meta_id = cursor.lastrowid
    conn.close()

    await update.message.reply_text(
        f"✅ *Meta criada com sucesso!*\n\n"
        f"🎯 Meta #{meta_id}: {nome}\n"
        f"💰 Valor alvo: {fmt(valor)}\n\n"
        f"Use /progresso_meta {meta_id} <valor> para adicionar progresso!",
        parse_mode="Markdown"
    )

async def progresso_meta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /progresso_meta - Adiciona progresso a uma meta"""
    try:
        meta_id = int(context.args[0])
        valor_adicional = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /progresso_meta <id> <valor>\n"
            "Ex: /progresso_meta 1 500"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT nome, valor_alvo, valor_atual, concluida FROM metas WHERE id = ?", (meta_id,))
    meta = cursor.fetchone()
    
    if not meta:
        conn.close()
        await update.message.reply_text("❗ Meta não encontrada!")
        return
    
    nome, valor_alvo, valor_atual, concluida = meta
    
    if concluida:
        conn.close()
        await update.message.reply_text("✅ Esta meta já foi concluída!")
        return
    
    novo_valor = valor_atual + valor_adicional
    
    if novo_valor >= valor_alvo:
        cursor.execute("UPDATE metas SET valor_atual = ?, concluida = 1 WHERE id = ?", (valor_alvo, meta_id))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"🎉 *PARABÉNS! Meta concluída!*\n\n"
            f"✅ {nome}\n"
            f"💰 Valor alcançado: {fmt(valor_alvo)}\n\n"
            f"Você conseguiu! Continue assim! 🚀",
            parse_mode="Markdown"
        )
    else:
        cursor.execute("UPDATE metas SET valor_atual = ? WHERE id = ?", (novo_valor, meta_id))
        conn.commit()
        conn.close()
        
        progresso = (novo_valor / valor_alvo * 100)
        falta = valor_alvo - novo_valor
        
        await update.message.reply_text(
            f"✅ *Progresso adicionado!*\n\n"
            f"🎯 {nome}\n"
            f"💰 {fmt(novo_valor)} / {fmt(valor_alvo)} ({progresso:.1f}%)\n"
            f"📊 Faltam: {fmt(falta)}\n\n"
            f"Continue assim! 💪",
            parse_mode="Markdown"
        )

async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /grafico - Gera gráfico de pizza das despesas por categoria"""
    if not MATPLOTLIB_AVAILABLE:
        await update.message.reply_text("❗ Biblioteca matplotlib não disponível. Instale com: pip install matplotlib")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT categoria, SUM(valor) FROM gastos GROUP BY categoria")
    dados = cursor.fetchall()
    conn.close()

    if not dados:
        await update.message.reply_text("📊 Nenhum gasto registrado ainda.")
        return

    categorias = [item[0].capitalize() for item in dados]
    valores = [item[1] for item in dados]

    fig, ax = plt.subplots(figsize=(10, 7))
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8']
    
    wedges, texts, autotexts = ax.pie(valores, labels=categorias, autopct='%1.1f%%',
                                        startangle=90, colors=colors[:len(categorias)])
    
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(10)
        autotext.set_weight('bold')
    
    ax.set_title('Distribuição de Gastos por Categoria', fontsize=14, weight='bold', pad=20)
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()

    await update.message.reply_photo(photo=buf, caption="📊 *Gráfico de Gastos por Categoria*", parse_mode="Markdown")

async def grafico_mensal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /grafico_mensal - Gera gráfico de evolução mensal dos gastos"""
    if not MATPLOTLIB_AVAILABLE:
        await update.message.reply_text("❗ Biblioteca matplotlib não disponível.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%Y-%m', data_transacao) as mes, SUM(valor)
        FROM gastos
        WHERE data_transacao IS NOT NULL
        GROUP BY mes
        ORDER BY mes
    """)
    dados = cursor.fetchall()
    conn.close()

    if not dados:
        await update.message.reply_text("📊 Nenhum gasto com data registrado ainda.")
        return

    meses = [item[0] for item in dados]
    valores = [item[1] for item in dados]

    meses_formatados = [datetime.strptime(m, '%Y-%m').strftime('%b/%y') if m else 'N/A' for m in meses]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(meses_formatados, valores, marker='o', linewidth=2, markersize=8, color='#4ECDC4')
    ax.fill_between(range(len(valores)), valores, alpha=0.3, color='#4ECDC4')
    
    ax.set_xlabel('Mês', fontsize=12, weight='bold')
    ax.set_ylabel('Valor (R$)', fontsize=12, weight='bold')
    ax.set_title('Evolução Mensal de Gastos', fontsize=14, weight='bold', pad=20)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()

    await update.message.reply_photo(photo=buf, caption="📈 *Evolução Mensal de Gastos*", parse_mode="Markdown")

async def lembretes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /lembretes - Lista todos os lembretes"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao, dia_mes, ativo FROM lembretes ORDER BY dia_mes")
    todos_lembretes = cursor.fetchall()
    conn.close()

    if not todos_lembretes:
        await update.message.reply_text(
            "🔔 Nenhum lembrete cadastrado!\n\n"
            "Use /addlembrete para criar:\n"
            "Ex: /addlembrete 10 Pagar conta de luz"
        )
        return

    msg = "🔔 SEUS LEMBRETES\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for lembrete in todos_lembretes:
        lembrete_id, descricao, dia_mes, ativo = lembrete
        status = "🔔" if ativo else "🔕"
        msg += f"{status} *Dia {dia_mes}*: {descricao}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def addlembrete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addlembrete - Adiciona um novo lembrete"""
    try:
        dia = int(context.args[0])
        descricao = " ".join(context.args[1:]) if len(context.args) > 1 else "Lembrete sem descrição"
        
        if dia < 1 or dia > 31:
            raise ValueError("Dia inválido")
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /addlembrete <dia> <descrição>\n"
            "Ex: /addlembrete 10 Pagar conta de luz\n"
            "Dia deve ser entre 1 e 31"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO lembretes (descricao, dia_mes) VALUES (?, ?)", (descricao, dia))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Lembrete criado!*\n\n"
        f"🔔 Todo dia {dia}: {descricao}",
        parse_mode="Markdown"
    )

async def categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /categorias - Lista categorias personalizadas"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM categorias ORDER BY nome")
    cats = cursor.fetchall()
    conn.close()

    msg = "🏷️ CATEGORIAS CUSTOMIZADAS\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    categorias_padrao = ["Débito", "Crédito", "Alimentação", "Pix"]
    msg += "*Padrões:*\n"
    for cat in categorias_padrao:
        msg += f"• {cat}\n"
    
    if cats:
        msg += "\n*Suas categorias:*\n"
        for cat in cats:
            msg += f"• {cat[0]}\n"
    else:
        msg += "\n*Você ainda não criou categorias personalizadas.*"
    
    msg += "\n\nUse /addcategoria <nome> para criar nova categoria"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def addcategoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addcategoria - Adiciona uma categoria personalizada"""
    try:
        nome = " ".join(context.args)
        if not nome:
            raise ValueError("Nome vazio")
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /addcategoria <nome>\n"
            "Ex: /addcategoria Assinaturas"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("INSERT INTO categorias (nome) VALUES (?)", (nome,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ Categoria *{nome}* criada com sucesso!",
            parse_mode="Markdown"
        )
    except sqlite3.IntegrityError:
        conn.close()
        await update.message.reply_text(
            f"❗ A categoria *{nome}* já existe!",
            parse_mode="Markdown"
        )

async def removecategoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /removecategoria - Remove uma categoria personalizada"""
    try:
        nome = " ".join(context.args)
        if not nome:
            raise ValueError("Nome vazio")
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /removecategoria <nome>\n"
            "Ex: /removecategoria Assinaturas"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categorias WHERE nome = ?", (nome,))
    
    if cursor.rowcount > 0:
        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"✅ Categoria *{nome}* removida!",
            parse_mode="Markdown"
        )
    else:
        conn.close()
        await update.message.reply_text(
            f"❗ Categoria *{nome}* não encontrada!",
            parse_mode="Markdown"
        )

async def orcamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /orcamento - Define orçamento mensal geral"""
    try:
        valor = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /orcamento <valor>\n"
            "Ex: /orcamento 2000"
        )
        return

    now = datetime.now()
    mes = now.month
    ano = now.year

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO orcamento (tipo, categoria, valor, mes, ano)
        VALUES ('geral', NULL, ?, ?, ?)
    """, (valor, mes, ano))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Orçamento mensal definido!*\n\n"
        f"💰 Limite: {fmt(valor)} para {now.strftime('%B/%Y')}",
        parse_mode="Markdown"
    )

async def orcamento_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /orcamento_categoria - Define orçamento por categoria"""
    try:
        if len(context.args) < 2:
            raise ValueError("Argumentos insuficientes")
        
        valor = float(context.args[-1])
        categoria = " ".join(context.args[:-1])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /orcamento_categoria <categoria> <valor>\n"
            "Ex: /orcamento_categoria Alimentação 500"
        )
        return

    now = datetime.now()
    mes = now.month
    ano = now.year

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO orcamento (tipo, categoria, valor, mes, ano)
        VALUES ('categoria', ?, ?, ?, ?)
    """, (categoria, valor, mes, ano))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Orçamento por categoria definido!*\n\n"
        f"🏷️ Categoria: {categoria}\n"
        f"💰 Limite: {fmt(valor)} para {now.strftime('%B/%Y')}",
        parse_mode="Markdown"
    )

async def recorrentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /recorrentes - Lista pagamentos recorrentes"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao, valor, dia_mes, ativo FROM recorrentes ORDER BY dia_mes")
    todos_recorrentes = cursor.fetchall()
    conn.close()

    if not todos_recorrentes:
        await update.message.reply_text(
            "🔄 Nenhum pagamento recorrente!\n\n"
            "Use /addrecorrente para criar:\n"
            "Ex: /addrecorrente 100 15 Netflix"
        )
        return

    msg = "🔄 PAGAMENTOS RECORRENTES\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for rec in todos_recorrentes:
        rec_id, descricao, valor, dia_mes, ativo = rec
        status = "✅" if ativo else "❌"
        msg += f"{status} *Dia {dia_mes}*: {descricao} - {fmt(valor)}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def addrecorrente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addrecorrente - Adiciona pagamento recorrente"""
    try:
        valor = float(context.args[0])
        dia = int(context.args[1])
        descricao = " ".join(context.args[2:]) if len(context.args) > 2 else "Recorrente sem descrição"
        
        if dia < 1 or dia > 31:
            raise ValueError("Dia inválido")
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /addrecorrente <valor> <dia> <descrição>\n"
            "Ex: /addrecorrente 100 15 Netflix\n"
            "Dia deve ser entre 1 e 31"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO recorrentes (descricao, valor, dia_mes) VALUES (?, ?, ?)", 
                   (descricao, valor, dia))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Pagamento recorrente criado!*\n\n"
        f"🔄 {descricao}\n"
        f"💰 Valor: {fmt(valor)}\n"
        f"📅 Todo dia {dia}",
        parse_mode="Markdown"
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /dashboard - Dashboard interativo completo"""
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

    now = datetime.now()
    cursor.execute("SELECT valor FROM orcamento WHERE tipo = 'geral' AND mes = ? AND ano = ?", 
                   (now.month, now.year))
    orcamento_result = cursor.fetchone()
    orcamento_mensal = orcamento_result[0] if orcamento_result else 0

    cursor.execute("SELECT COUNT(*) FROM metas WHERE concluida = 0")
    metas_ativas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM lembretes WHERE ativo = 1 AND dia_mes = ?", (now.day,))
    lembretes_hoje = cursor.fetchone()[0] or 0

    conn.close()

    saldo_vale = total_vales - total_gastos_alimentacao
    saldo_final = total_receitas + total_receitas_parceiro - total_gastos - total_fixos

    orcamento_usado_pct = (total_gastos / orcamento_mensal * 100) if orcamento_mensal > 0 else 0
    
    if orcamento_usado_pct >= 90:
        alerta_orcamento = "🚨 ATENÇÃO: Orçamento quase esgotado!"
    elif orcamento_usado_pct >= 75:
        alerta_orcamento = "⚠️ ALERTA: 75% do orçamento usado"
    else:
        alerta_orcamento = "✅ Orçamento sob controle"

    msg = (
        "📊 *DASHBOARD FINANCEIRO*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "💰 *RESUMO GERAL*\n"
        f"• Receitas: {fmt(total_receitas + total_receitas_parceiro)}\n"
        f"• Gastos: {fmt(total_gastos)}\n"
        f"• Fixos: {fmt(total_fixos)}\n"
        f"• *Saldo: {fmt(saldo_final)}*\n\n"
        
        "🍽️ *VALE-ALIMENTAÇÃO*\n"
        f"• Total recebido: {fmt(total_vales)}\n"
        f"• Gasto: {fmt(total_gastos_alimentacao)}\n"
        f"• *Saldo: {fmt(saldo_vale)}*\n\n"
    )

    if orcamento_mensal > 0:
        msg += (
            "💳 *ORÇAMENTO MENSAL*\n"
            f"• Limite: {fmt(orcamento_mensal)}\n"
            f"• Usado: {fmt(total_gastos)} ({orcamento_usado_pct:.1f}%)\n"
            f"• Disponível: {fmt(orcamento_mensal - total_gastos)}\n"
            f"• {alerta_orcamento}\n\n"
        )

    msg += (
        "🎯 *STATUS*\n"
        f"• Metas ativas: {metas_ativas}\n"
        f"• Lembretes hoje: {lembretes_hoje}\n\n"
        
        "💡 *DICAS PERSONALIZADAS*\n"
    )

    if saldo_final < 0:
        msg += "• Atenção! Você está no vermelho. Revise seus gastos.\n"
    elif saldo_final < 500:
        msg += "• Seu saldo está baixo. Considere economizar mais.\n"
    else:
        msg += "• Ótimo! Você está com saldo positivo. Continue assim!\n"

    if orcamento_usado_pct > 90:
        msg += "• Cuidado com novos gastos este mês!\n"

    if metas_ativas > 0:
        msg += f"• Você tem {metas_ativas} meta(s) ativa(s). Use /metas para ver.\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def relatorio_detalhado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /relatorio_detalhado - Gera relatório PDF detalhado"""
    if not FPDF_AVAILABLE:
        await update.message.reply_text(
            "❗ Para gerar PDF, instale a biblioteca:\n"
            "pip install fpdf2"
        )
        return

    await update.message.reply_text("📄 Gerando relatório PDF detalhado...")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(valor) FROM receitas")
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM gastos")
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute("SELECT categoria, SUM(valor) FROM gastos GROUP BY categoria")
    gastos_por_categoria = cursor.fetchall()

    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "RELATORIO FINANCEIRO DETALHADO", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Data: {datetime.now().strftime('%d/%m/%Y')}", ln=True)
    pdf.ln(5)

    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "RESUMO GERAL", ln=True)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Receitas: R$ {total_receitas:.2f}", ln=True)
    pdf.cell(0, 10, f"Gastos: R$ {total_gastos:.2f}", ln=True)
    pdf.cell(0, 10, f"Saldo: R$ {total_receitas - total_gastos:.2f}", ln=True)
    pdf.ln(10)

    if gastos_por_categoria:
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "GASTOS POR CATEGORIA", ln=True)
        pdf.set_font("Arial", "", 12)
        for cat, valor in gastos_por_categoria:
            pdf.cell(0, 10, f"{cat.capitalize()}: R$ {valor:.2f}", ln=True)

    pdf_file = f"relatorio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf.output(pdf_file)

    with open(pdf_file, 'rb') as f:
        await update.message.reply_document(
            document=f,
            caption="📄 *Relatório Detalhado em PDF*",
            parse_mode="Markdown"
        )

    os.remove(pdf_file)

async def relatorio_exportar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /relatorio_exportar - Exporta dados para Excel/CSV"""
    if not PANDAS_AVAILABLE:
        await update.message.reply_text(
            "❗ Para exportar para Excel, instale:\n"
            "pip install pandas openpyxl"
        )
        return

    await update.message.reply_text("📊 Exportando dados para Excel...")

    conn = get_db_connection()

    df_receitas = pd.read_sql_query("SELECT * FROM receitas", conn)
    df_gastos = pd.read_sql_query("SELECT * FROM gastos", conn)
    df_fixos = pd.read_sql_query("SELECT * FROM fixos", conn)
    df_vales = pd.read_sql_query("SELECT * FROM vales", conn)

    conn.close()

    excel_file = f"financeiro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
        df_receitas.to_excel(writer, sheet_name='Receitas', index=False)
        df_gastos.to_excel(writer, sheet_name='Gastos', index=False)
        df_fixos.to_excel(writer, sheet_name='Fixos', index=False)
        df_vales.to_excel(writer, sheet_name='Vales', index=False)

    with open(excel_file, 'rb') as f:
        await update.message.reply_document(
            document=f,
            caption="📊 *Dados Exportados para Excel*",
            parse_mode="Markdown"
        )

    os.remove(excel_file)

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

    cursor.execute("SELECT SUM(valor) FROM gastos WHERE categoria = 'crédito'")
    total_credito = cursor.fetchone()[0] or 0

    cursor.execute("SELECT descricao, valor FROM fatura_cartao WHERE pago = 0")
    itens = cursor.fetchall()

    conn.close()

    msg = (
        "💎 FATURA DO CARTÃO\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 Total: {fmt(total_credito)}\n\n"
    )

    if itens:
        msg += "*Itens na fatura:*\n"
        for item in itens:
            msg += f"• {item[0]}: {fmt(item[1])}\n"
    else:
        msg += "Nenhum item pendente na fatura."

    await update.message.reply_text(msg, parse_mode="Markdown")

async def mtp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /mtp - Aplica o Método Traz Paz"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(valor) FROM receitas")
    receitas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM receitas_parceiro")
    receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM fixos")
    fixos = cursor.fetchone()[0] or 0

    conn.close()

    total_receitas = receitas + receitas_parceiro
    disponivel = total_receitas - fixos

    if disponivel <= 0:
        await update.message.reply_text(
            "⚠️ *Atenção!*\n"
            "Suas despesas fixas excedem suas receitas!\n"
            "Revise seus gastos urgentemente.",
            parse_mode="Markdown"
        )
        return

    necessidades = disponivel * 0.50
    prioridades = disponivel * 0.30
    qualidade_vida = disponivel * 0.15
    liberdade_financeira = disponivel * 0.05

    msg = (
        "🧘 *MÉTODO TRAZ PAZ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Total de receitas: {fmt(total_receitas)}\n"
        f"🏠 Despesas fixas: {fmt(fixos)}\n"
        f"✅ Disponível: {fmt(disponivel)}\n\n"
        
        "*Distribuição recomendada:*\n"
        f"🛒 Necessidades (50%): {fmt(necessidades)}\n"
        f"🎯 Prioridades (30%): {fmt(prioridades)}\n"
        f"😊 Qualidade de Vida (15%): {fmt(qualidade_vida)}\n"
        f"💎 Liberdade Financeira (5%): {fmt(liberdade_financeira)}\n\n"
        
        "*Dica:* Siga essa distribuição para ter uma vida financeira equilibrada!"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /relatorio - Gera relatório mensal completo"""
    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.now()
    mes_atual = now.month
    ano_atual = now.year

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

    cursor.execute("SELECT categoria, SUM(valor) FROM gastos GROUP BY categoria")
    gastos_categoria = cursor.fetchall()

    conn.close()

    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos

    msg = (
        f"📊 *RELATÓRIO - {now.strftime('%B/%Y').upper()}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "*ENTRADAS*\n"
        f"💰 Receitas: {fmt(total_receitas)}\n"
        f"💰 Receitas Parceiro: {fmt(total_receitas_parceiro)}\n"
        f"🍽️ Vales: {fmt(total_vales)}\n"
        f"*Total: {fmt(total_receitas + total_receitas_parceiro + total_vales)}*\n\n"
        
        "*SAÍDAS*\n"
        f"🛒 Gastos: {fmt(total_gastos)}\n"
        f"🏠 Fixos: {fmt(total_fixos)}\n"
        f"*Total: {fmt(total_gastos + total_fixos)}*\n\n"
    )

    if gastos_categoria:
        msg += "*GASTOS POR CATEGORIA*\n"
        for cat, valor in gastos_categoria:
            msg += f"• {cat.capitalize()}: {fmt(valor)}\n"
        msg += "\n"

    msg += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *SALDO FINAL: {fmt(saldo)}*"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def relatorio_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /relatorio_mes - Gera relatório de um mês específico"""
    try:
        if len(context.args) < 2:
            raise ValueError("Argumentos insuficientes")
        
        mes = int(context.args[0])
        ano = int(context.args[1])
        
        if mes < 1 or mes > 12:
            raise ValueError("Mês inválido")
        if ano < 2000 or ano > 2100:
            raise ValueError("Ano inválido")
            
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /relatorio_mes <mês> <ano>\n"
            "Ex: /relatorio_mes 9 2024\n"
            "   /relatorio_mes 10 2024"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT SUM(valor) FROM receitas WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM receitas_parceiro WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM vales WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_vales = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM fixos WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_fixos = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT categoria, SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ? GROUP BY categoria",
        (f"{mes:02d}", str(ano))
    )
    gastos_categoria = cursor.fetchall()

    conn.close()

    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos

    meses_pt = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }

    msg = (
        f"📊 *RELATÓRIO - {meses_pt[mes].upper()}/{ano}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "*ENTRADAS*\n"
        f"💰 Receitas: {fmt(total_receitas)}\n"
        f"💰 Receitas Parceiro: {fmt(total_receitas_parceiro)}\n"
        f"🍽️ Vales: {fmt(total_vales)}\n"
        f"*Total: {fmt(total_receitas + total_receitas_parceiro + total_vales)}*\n\n"
        
        "*SAÍDAS*\n"
        f"🛒 Gastos: {fmt(total_gastos)}\n"
        f"🏠 Fixos: {fmt(total_fixos)}\n"
        f"*Total: {fmt(total_gastos + total_fixos)}*\n\n"
    )

    if gastos_categoria:
        msg += "*GASTOS POR CATEGORIA*\n"
        for cat, valor in gastos_categoria:
            msg += f"• {cat.capitalize()}: {fmt(valor)}\n"
        msg += "\n"

    msg += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *SALDO: {fmt(saldo)}*"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def saldo_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /saldo_mes - Mostra saldo de um mês específico"""
    try:
        if len(context.args) < 2:
            raise ValueError("Argumentos insuficientes")
        
        mes = int(context.args[0])
        ano = int(context.args[1])
        
        if mes < 1 or mes > 12:
            raise ValueError("Mês inválido")
        if ano < 2000 or ano > 2100:
            raise ValueError("Ano inválido")
            
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❗ Uso correto: /saldo_mes <mês> <ano>\n"
            "Ex: /saldo_mes 9 2024"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT SUM(valor) FROM receitas WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_receitas = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM receitas_parceiro WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_receitas_parceiro = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM vales WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_vales = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM fixos WHERE strftime('%m', data) = ? AND strftime('%Y', data) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_fixos = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM gastos WHERE categoria = 'alimentação' AND strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ?",
        (f"{mes:02d}", str(ano))
    )
    total_gastos_alimentacao = cursor.fetchone()[0] or 0

    conn.close()

    saldo_vale = total_vales - total_gastos_alimentacao
    saldo_final = total_receitas + total_receitas_parceiro + saldo_vale - total_gastos - total_fixos

    meses_pt = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }

    msg = (
        f"💳 SALDO - {meses_pt[mes].upper()}/{ano}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Receitas: {fmt(total_receitas + total_receitas_parceiro)}\n"
        f"🍽️ Vales: {fmt(total_vales)} (Saldo: {fmt(saldo_vale)})\n"
        f"🛒 Gastos: {fmt(total_gastos)}\n"
        f"🏠 Fixos: {fmt(total_fixos)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Saldo: {fmt(saldo_final)}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def comparar_meses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /comparar_meses - Compara gastos entre mês atual e anterior"""
    now = datetime.now()
    mes_atual = now.month
    ano_atual = now.year
    
    if mes_atual == 1:
        mes_anterior = 12
        ano_anterior = ano_atual - 1
    else:
        mes_anterior = mes_atual - 1
        ano_anterior = ano_atual

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ?",
        (f"{mes_atual:02d}", str(ano_atual))
    )
    gastos_atual = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ?",
        (f"{mes_anterior:02d}", str(ano_anterior))
    )
    gastos_anterior = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT categoria, SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ? GROUP BY categoria",
        (f"{mes_atual:02d}", str(ano_atual))
    )
    cat_atual = cursor.fetchall()

    cursor.execute(
        "SELECT categoria, SUM(valor) FROM gastos WHERE strftime('%m', COALESCE(data_transacao, data)) = ? AND strftime('%Y', COALESCE(data_transacao, data)) = ? GROUP BY categoria",
        (f"{mes_anterior:02d}", str(ano_anterior))
    )
    cat_anterior = cursor.fetchall()

    conn.close()

    diferenca = gastos_atual - gastos_anterior
    percentual = (diferenca / gastos_anterior * 100) if gastos_anterior > 0 else 0

    if diferenca > 0:
        tendencia = f"📈 Aumento de {fmt(diferenca)} (+{percentual:.1f}%)"
    elif diferenca < 0:
        tendencia = f"📉 Redução de {fmt(abs(diferenca))} ({percentual:.1f}%)"
    else:
        tendencia = "➡️ Gastos mantidos"

    meses_pt = {
        1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr",
        5: "Mai", 6: "Jun", 7: "Jul", 8: "Ago",
        9: "Set", 10: "Out", 11: "Nov", 12: "Dez"
    }

    msg = (
        "📊 *COMPARAÇÃO DE GASTOS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {meses_pt[mes_anterior]}/{ano_anterior}: {fmt(gastos_anterior)}\n"
        f"📅 {meses_pt[mes_atual]}/{ano_atual}: {fmt(gastos_atual)}\n\n"
        f"{tendencia}\n\n"
    )

    if cat_atual:
        msg += "*Gastos por categoria (mês atual):*\n"
        for cat, valor in cat_atual:
            msg += f"• {cat.capitalize()}: {fmt(valor)}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def historico_meses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /historico_meses - Mostra histórico dos últimos 6 meses"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            strftime('%Y-%m', COALESCE(data_transacao, data)) as mes,
            SUM(valor) as total
        FROM gastos
        WHERE COALESCE(data_transacao, data) >= date('now', '-6 months')
        GROUP BY mes
        ORDER BY mes DESC
        LIMIT 6
    """)
    historico = cursor.fetchall()

    conn.close()

    if not historico:
        await update.message.reply_text("📊 Nenhum dado histórico disponível.")
        return

    msg = "📈 *HISTÓRICO DOS ÚLTIMOS 6 MESES*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    meses_pt = {
        "01": "Jan", "02": "Fev", "03": "Mar", "04": "Abr",
        "05": "Mai", "06": "Jun", "07": "Jul", "08": "Ago",
        "09": "Set", "10": "Out", "11": "Nov", "12": "Dez"
    }

    for mes_ano, total in reversed(historico):
        if mes_ano:
            ano, mes = mes_ano.split('-')
            mes_nome = meses_pt.get(mes, mes)
            msg += f"📅 {mes_nome}/{ano}: {fmt(total)}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ia - Faz pergunta à IA"""
    if not context.args:
        await update.message.reply_text(
            "❗ Uso correto: /ia <sua pergunta>\n"
            "Ex: /ia Como posso economizar mais?"
        )
        return

    pergunta = " ".join(context.args)
    resposta = call_gemini_question(pergunta)

    await update.message.reply_text(f"🤖 *IA Financeira:*\n\n{resposta}", parse_mode="Markdown")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /reset - Apaga todos os dados"""
    keyboard = [
        [InlineKeyboardButton("✅ SIM, apagar tudo", callback_data="reset_confirm")],
        [InlineKeyboardButton("❌ NÃO, cancelar", callback_data="reset_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚠️ *ATENÇÃO!*\n\n"
        "Você está prestes a apagar TODOS os dados:\n"
        "• Receitas\n"
        "• Gastos\n"
        "• Fixos\n"
        "• Vales\n"
        "• Metas\n"
        "• Lembretes\n"
        "• Categorias\n"
        "• Orçamentos\n"
        "• Recorrentes\n\n"
        "*Esta ação NÃO pode ser desfeita!*\n\n"
        "Tem certeza?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
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
        cursor.execute("DELETE FROM metas")
        cursor.execute("DELETE FROM lembretes")
        cursor.execute("DELETE FROM categorias")
        cursor.execute("DELETE FROM orcamento")
        cursor.execute("DELETE FROM recorrentes")

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "✅ *Todos os dados foram apagados!*\n\n"
            "Você pode começar do zero agora.",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "❌ Reset cancelado. Seus dados estão seguros!",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal para mensagens de texto"""
    if 'pending_gasto' in context.user_data and context.user_data['pending_gasto'].get('waiting_for_date'):
        await handle_date_response(update, context)
        return

    text = update.message.text
    result = call_gemini_natural_language(text)

    if not result:
        await update.message.reply_text(
            "🤔 Não consegui entender. Use /ajuda para ver os comandos disponíveis."
        )
        return

    transaction_type = result.get("type")
    amount = result.get("amount")
    description = result.get("description", "Sem descrição")

    if transaction_type == "income":
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
        context.user_data['pending_gasto'] = {
            'valor': float(amount),
            'descricao': description,
            'waiting_for_category': True
        }

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

def main():
    """Função principal que inicia o bot"""
    init_database()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

    app = Application.builder().token(token).build()

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
    
    app.add_handler(CommandHandler("metas", metas))
    app.add_handler(CommandHandler("addmeta", addmeta))
    app.add_handler(CommandHandler("progresso_meta", progresso_meta))
    app.add_handler(CommandHandler("grafico", grafico))
    app.add_handler(CommandHandler("grafico_mensal", grafico_mensal))
    app.add_handler(CommandHandler("lembretes", lembretes))
    app.add_handler(CommandHandler("addlembrete", addlembrete))
    app.add_handler(CommandHandler("categorias", categorias))
    app.add_handler(CommandHandler("addcategoria", addcategoria))
    app.add_handler(CommandHandler("removecategoria", removecategoria))
    app.add_handler(CommandHandler("orcamento", orcamento))
    app.add_handler(CommandHandler("orcamento_categoria", orcamento_categoria))
    app.add_handler(CommandHandler("recorrentes", recorrentes))
    app.add_handler(CommandHandler("addrecorrente", addrecorrente))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("relatorio_detalhado", relatorio_detalhado))
    app.add_handler(CommandHandler("relatorio_exportar", relatorio_exportar))
    app.add_handler(CommandHandler("relatorio_mes", relatorio_mes))
    app.add_handler(CommandHandler("saldo_mes", saldo_mes))
    app.add_handler(CommandHandler("comparar_meses", comparar_meses))
    app.add_handler(CommandHandler("historico_meses", historico_meses))

    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(débito|crédito|alimentação|pix)\\|"))
    app.add_handler(CallbackQueryHandler(reset_button_handler, pattern="^(reset_confirm|reset_cancel)$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 FinBot com recursos avançados iniciado! Aguardando mensagens...")
    
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
