"""
FinBot - Telegram Bot para Gestão Financeira Pessoal
=====================================================
Bot inteligente que permite registrar receitas, despesas, gastos fixos e vale-alimentação.

Correção: Implementação de um fluxo de perguntas e respostas (State Machine)
para garantir que a data da transação seja sempre precisa, caso não seja fornecida
diretamente no comando.
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
    locale.setlocale(locale.LC_ALL, "pt_BR.UTF8")
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, "pt_BR")
    except locale.Error:
        pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Constante para indicar o estado da conversação
AWAITING_DATE = 1
AWAITING_CATEGORY = 2

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
                # Se for só dia/mês, assume o ano atual
                parsed_date = parsed_date.replace(year=datetime.now().year)
            return parsed_date
        except ValueError:
            continue
    
    # Tenta usar dateparser para flexibilidade
    try:
        parsed = dateparser.parse(date_str, languages=['pt', 'en'])
        if parsed:
            return parsed.date()
    except:
        pass
    
    return datetime.now().date() # Retorna a data de hoje como fallback

def extrair_valor_descricao_data(args):
    """Extrai valor, descrição e data de uma lista de argumentos de comando."""
    if not args:
        return None, "Sem descrição", None
            
    try:
        valor = float(args[0])
    except ValueError:
        return None, "Sem descrição", None # Retorna None para indicar que o valor falhou
    
    args_restantes = args[1:]
    data_str = None
    descricao = " ".join(args_restantes)
        
    if len(args_restantes) >= 1:
        ultimo_arg = args_restantes[-1]
        data_test = parse_date(ultimo_arg)
        data_hoje = datetime.now().date()
        
        # Heurística: se a última palavra é uma data válida e diferente da data de hoje, 
        # ou se é uma palavra-chave de data (hoje, ontem), a consideramos a data.
        if (data_test != data_hoje and data_test is not None) or ultimo_arg.lower() in ['hoje', 'today', 'ontem', 'yesterday', 'amanhã', 'tomorrow']:
            data_str = ultimo_arg
            descricao_parts = args_restantes[:-1]
            descricao = " ".join(descricao_parts) if descricao_parts else "Sem descrição"
        
    data_final = parse_date(data_str) if data_str else None # Retorna None se a data não foi fornecida
    
    return valor, descricao, data_final

# As funções call_gemini_natural_language, call_gemini_question e init_database permanecem inalteradas
# para brevidade, mas estão no código completo da resposta anterior.

# ====================== FUNÇÕES GEMINI E DB (Inalteradas para Brevidade) ======================

# Função call_gemini_natural_language (do código anterior)
# Função call_gemini_question (do código anterior)
# Função init_database (do código anterior)

# Apenas para garantir que o código funcione:
def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS receitas (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT NOT NULL, valor REAL NOT NULL, data_transacao DATE DEFAULT (strftime('%Y-%m-%d', 'now')))")
    cursor.execute("CREATE TABLE IF NOT EXISTS receitas_parceiro (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT NOT NULL, valor REAL NOT NULL, data_transacao DATE DEFAULT (strftime('%Y-%m-%d', 'now')))")
    cursor.execute("CREATE TABLE IF NOT EXISTS gastos (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL NOT NULL, descricao TEXT NOT NULL, categoria TEXT NOT NULL, data_transacao DATE DEFAULT (strftime('%Y-%m-%d', 'now')), pago INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS fixos (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT NOT NULL, valor REAL NOT NULL, data_transacao DATE DEFAULT (strftime('%Y-%m-%d', 'now')))")
    cursor.execute("CREATE TABLE IF NOT EXISTS vales (id INTEGER PRIMARY KEY AUTOINCREMENT, valor REAL NOT NULL, data_transacao DATE DEFAULT (strftime('%Y-%m-%d', 'now')))")
    cursor.execute("CREATE TABLE IF NOT EXISTS fatura_cartao (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT NOT NULL, valor REAL NOT NULL, data_transacao DATE DEFAULT (strftime('%Y-%m-%d', 'now')), pago INTEGER DEFAULT 0)")
    conn.commit()
    conn.close()

def call_gemini_natural_language(text):
    # Apenas um placeholder, o código completo está na resposta anterior
    return None 

def call_gemini_question(text):
    # Apenas um placeholder, o código completo está na resposta anterior
    return "Resposta da IA simulada."

# ====================== FLUXO DE CONVERSA E COMANDOS (MODIFICADOS) ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Mensagem de boas-vindas"""
    # ... (código start do bloco anterior)
    welcome_msg = (
        "🤖 Olá! Bem-vindo ao FinBot!\n\n"
        "Eu sou seu assistente financeiro pessoal. Posso ajudar você a:\n"
        "💰 Registrar receitas e despesas\n"
        "📊 Acompanhar seu saldo\n"
        "📄 Gerar relatórios mensais\n"
        "🧘 Aplicar o Método Traz Paz\n\n"
        "Para maior precisão, *se você não disser a data no comando*, eu vou perguntar!\n"
        "Exemplo: `/addgasto 50 Supermercado` -> Bot pergunta a data.\n\n"
        "Digite /ajuda para ver todos os comandos disponíveis."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def addreceita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addreceita - Registra uma receita ou inicia o pedido de data."""
    valor, descricao, data_final = extrair_valor_descricao_data(context.args)

    if valor is None:
        await update.message.reply_text(
            "❗ Uso correto: /addreceita <valor> <descrição> [data]\n"
            "Ex: /addreceita 2000 Salário 05/10",
            parse_mode="Markdown"
        )
        return

    if data_final is None:
        # Armazena dados parciais e muda o estado
        context.user_data['state'] = AWAITING_DATE
        context.user_data['temp_data'] = {'type': 'receita', 'valor': valor, 'descricao': descricao}
        await update.message.reply_text(
            f"✅ Quase lá: Receita de {fmt(valor)} - {descricao}.\n\n"
            "🗓️ *Quando foi essa receita?* (Ex: hoje, ontem, 15/09)",
            parse_mode="Markdown"
        )
        return

    # Se a data foi fornecida, salva diretamente
    data_str = data_final.strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO receitas (descricao, valor, data_transacao) VALUES (?, ?, ?)",
        (descricao, valor, data_str)
    )
    conn.commit()
    conn.close()

    data_display = "hoje" if data_final == datetime.now().date() else data_final.strftime('%d/%m/%Y')
    await update.message.reply_text(
        f"✅ Receita registrada!\n💰 {fmt(valor)} - {descricao}\n📅 Data: {data_display}",
        parse_mode="Markdown"
    )

async def addreceita_parceiro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addreceita_parceiro - Registra receita do parceiro(a) ou inicia o pedido de data."""
    valor, descricao, data_final = extrair_valor_descricao_data(context.args)

    if valor is None:
        await update.message.reply_text(
            "❗ Uso correto: /addreceita_parceiro <valor> <descrição> [data]\n"
            "Ex: /addreceita_parceiro 1500 Salário 05/10",
            parse_mode="Markdown"
        )
        return

    if data_final is None:
        # Armazena dados parciais e muda o estado
        context.user_data['state'] = AWAITING_DATE
        context.user_data['temp_data'] = {'type': 'receita_parceiro', 'valor': valor, 'descricao': descricao}
        await update.message.reply_text(
            f"✅ Quase lá: Receita da parceira de {fmt(valor)} - {descricao}.\n\n"
            "🗓️ *Quando foi essa receita?* (Ex: hoje, ontem, 15/09)",
            parse_mode="Markdown"
        )
        return
    
    # Se a data foi fornecida, salva diretamente
    data_str = data_final.strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO receitas_parceiro (descricao, valor, data_transacao) VALUES (?, ?, ?)", 
        (descricao, valor, data_str)
    )
    conn.commit()
    conn.close()

    data_display = "hoje" if data_final == datetime.now().date() else data_final.strftime('%d/%m/%Y')
    await update.message.reply_text(
        f"✅ Receita da parceira registrada!\n💰 {fmt(valor)} - {descricao}\n📅 Data: {data_display}",
        parse_mode="Markdown"
    )

async def fixo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /fixo - Registra uma despesa fixa mensal ou inicia o pedido de data."""
    valor, descricao, data_final = extrair_valor_descricao_data(context.args)

    if valor is None:
        await update.message.reply_text(
            "❗ Uso correto: /fixo <valor> <descrição> [data]\n"
            "Ex: /fixo 1200 Aluguel 01/10",
            parse_mode="Markdown"
        )
        return

    if data_final is None:
        # Armazena dados parciais e muda o estado
        context.user_data['state'] = AWAITING_DATE
        context.user_data['temp_data'] = {'type': 'fixo', 'valor': valor, 'descricao': descricao}
        await update.message.reply_text(
            f"✅ Quase lá: Despesa fixa de {fmt(valor)} - {descricao}.\n\n"
            "🗓️ *Quando foi essa despesa?* (Ex: hoje, 05/09, 1º dia do mês)",
            parse_mode="Markdown"
        )
        return
    
    # Se a data foi fornecida, salva diretamente
    data_str = data_final.strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO fixos (descricao, valor, data_transacao) VALUES (?, ?, ?)", 
        (descricao, valor, data_str)
    )
    conn.commit()
    conn.close()

    data_display = "hoje" if data_final == datetime.now().date() else data_final.strftime('%d/%m/%Y')
    await update.message.reply_text(
        f"✅ Despesa fixa registrada!\n🏠 {fmt(valor)} - {descricao}\n📅 Data: {data_display}",
        parse_mode="Markdown"
    )

async def addgasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addgasto - Inicia o registro de um gasto, perguntando a data se necessário."""
    valor, descricao, data_final = extrair_valor_descricao_data(context.args)
    
    if valor is None:
        await update.message.reply_text(
            "❗ *Uso correto:* `/addgasto <valor> <descrição> [data]`\n"
            "📝 *Exemplo:* `/addgasto 50 Supermercado 25/09`",
            parse_mode="Markdown"
        )
        return

    if data_final is None:
        # Armazena dados parciais e muda o estado para pedir a data
        context.user_data['state'] = AWAITING_DATE
        context.user_data['temp_data'] = {'type': 'gasto', 'valor': valor, 'descricao': descricao}
        await update.message.reply_text(
            f"✅ Quase lá: Gasto de {fmt(valor)} - {descricao}.\n\n"
            "🗓️ *Quando foi essa compra?* (Ex: hoje, ontem, 29/09)",
            parse_mode="Markdown"
        )
        return
    
    # Se a data foi fornecida, pulamos para a seleção de categoria
    data_str = data_final.strftime('%Y-%m-%d')
    
    # Armazena a data e muda o estado para pedir a categoria (simula o próximo passo)
    context.user_data['state'] = AWAITING_CATEGORY
    context.user_data['temp_data'] = {'type': 'gasto', 'valor': valor, 'descricao': descricao, 'data_str': data_str}
    
    await update_to_category_selection(update, context, data_final)

async def update_to_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, data_final: datetime.date):
    """Envia a mensagem para selecionar a categoria após obter a data (seja ela fornecida ou perguntada)."""
    temp_data = context.user_data['temp_data']
    valor = temp_data['valor']
    descricao = temp_data['descricao']
    data_str = temp_data['data_str']
    
    keyboard = [
        [InlineKeyboardButton("💳 Débito", callback_data=f"débito|{valor}|{descricao}|{data_str}")],
        [InlineKeyboardButton("💎 Crédito", callback_data=f"crédito|{valor}|{descricao}|{data_str}")],
        [InlineKeyboardButton("🍽️ Vale-Alimentação", callback_data=f"alimentação|{valor}|{descricao}|{data_str}")],
        [InlineKeyboardButton("📱 Pix", callback_data=f"pix|{valor}|{descricao}|{data_str}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    data_display = "hoje" if data_final == datetime.now().date() else data_final.strftime('%d/%m/%Y')
    
    # Limpa o estado da conversação
    context.user_data['state'] = None
    context.user_data['temp_data'] = {}
    
    await update.message.reply_text(
        f"🛒 *Selecione a categoria para:*\n"
        f"💰 {fmt(valor)} - {descricao}\n"
        f"📅 Data: {data_display}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata a resposta do usuário quando o bot está esperando uma data."""
    state = context.user_data.get('state')
    temp_data = context.user_data.get('temp_data')

    if state != AWAITING_DATE or not temp_data:
        # Se não estiver esperando data, ignora ou passa para o handler normal
        return await handle_message(update, context) 

    user_input = update.message.text
    data_final = parse_date(user_input)
    data_str = data_final.strftime('%Y-%m-%d')
    
    # Atualiza temp_data com a data
    temp_data['data_str'] = data_str
    
    # Salva os dados no banco de dados
    trans_type = temp_data['type']
    valor = temp_data['valor']
    descricao = temp_data['descricao']

    data_display = "hoje" if data_final == datetime.now().date() else data_final.strftime('%d/%m/%Y')

    if trans_type == 'gasto':
        # Para gastos, passamos para a seleção de categoria
        context.user_data['state'] = AWAITING_CATEGORY
        return await update_to_category_selection(update, context, data_final)
    
    # Para Receitas/Fixos, salvamos diretamente
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if trans_type == 'receita':
        cursor.execute("INSERT INTO receitas (descricao, valor, data_transacao) VALUES (?, ?, ?)", (descricao, valor, data_str))
        msg_prefix = f"✅ Receita registrada!\n💰 {fmt(valor)} - {descricao}"
    elif trans_type == 'receita_parceiro':
        cursor.execute("INSERT INTO receitas_parceiro (descricao, valor, data_transacao) VALUES (?, ?, ?)", (descricao, valor, data_str))
        msg_prefix = f"✅ Receita da parceira registrada!\n💰 {fmt(valor)} - {descricao}"
    elif trans_type == 'fixo':
        cursor.execute("INSERT INTO fixos (descricao, valor, data_transacao) VALUES (?, ?, ?)", (descricao, valor, data_str))
        msg_prefix = f"✅ Despesa fixa registrada!\n🏠 {fmt(valor)} - {descricao}"
    else:
        await update.message.reply_text("❌ Erro: Tipo de transação desconhecido no fluxo de data.")
        context.user_data['state'] = None
        context.user_data['temp_data'] = {}
        return
        
    conn.commit()
    conn.close()

    # Limpa o estado da conversação
    context.user_data['state'] = None
    context.user_data['temp_data'] = {}
    
    await update.message.reply_text(
        f"{msg_prefix}\n📅 Data: {data_display}",
        parse_mode="Markdown"
    )

# Funções `/vale`, `/saldo`, `/top3`, `/fatura`, `/mtp`, `/relatorio`, `/reset`, `button_handler`, `reset_button_handler`, e `ia`
# permanecem como as que corrigimos no bloco anterior, já que o foco principal era o input de data.

async def vale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /vale - Registra recebimento de vale-alimentação com data opcional"""
    valor, _, data_final = extrair_valor_descricao_data(context.args)

    if valor is None:
        await update.message.reply_text(
            "❗ Uso correto: /vale <valor> [data]\n"
            "Ex: /vale 800 05/10",
            parse_mode="Markdown"
        )
        return
    
    data_str = data_final.strftime('%Y-%m-%d') if data_final else datetime.now().strftime('%Y-%m-%d')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vales (valor, data_transacao) VALUES (?, ?)", (valor, data_str))
    conn.commit()
    conn.close()
    
    data_display = "hoje" if parse_date(data_str) == datetime.now().date() else parse_date(data_str).strftime('%d/%m/%Y')

    await update.message.reply_text(
        f"✅ Vale-alimentação registrado!\n🍽️ {fmt(valor)}\n📅 Data: {data_display}",
        parse_mode="Markdown"
    )

# IMPORTANTE: A função handle_message precisa ser ajustada para priorizar o estado da data.

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para mensagens em linguagem natural (não-comandos) ou
    para capturar a resposta quando estamos esperando uma data.
    """
    # 1. Checa o estado da conversação
    state = context.user_data.get('state')

    if state == AWAITING_DATE:
        return await handle_date_input(update, context)

    # 2. Se não estiver esperando data, tenta interpretar linguagem natural
    text = update.message.text
    
    # Tenta interpretar a mensagem com Gemini (código completo na resposta anterior)
    result = call_gemini_natural_language(text)

    # ... (O restante do handle_message do bloco anterior, que usa o Gemini 
    # ou tenta extrair vale-alimentação simples, deve vir aqui.
    # Colocarei um resumo, mas o código completo e funcional é o do bloco anterior.)

    if not result:
        # Código de fallback para vale-alimentação simples ou mensagem de erro
        texto_sem_acentos = remover_acentos(text.lower())
        palavras_vale = ['vale', 'alimentacao', 'va', 'vr', 'refeicao', 'ticket', 'alimentação']
        is_vale_texto = any(palavra in texto_sem_acentos for palavra in palavras_vale)

        if is_vale_texto:
            # Tenta registrar vale
            # (Código completo de registro de vale do bloco anterior)
            await update.message.reply_text("✅ Vale-alimentação registrado automaticamente (Simulado).", parse_mode="Markdown")
            return
        
        # Mensagem de erro padrão
        await update.message.reply_text(
            "🤔 Desculpe, não entendi. Tente novamente ou use /ajuda.",
            parse_mode="Markdown"
        )
        return

    # 3. Processa o resultado do Gemini
    transaction_type = result.get("type")
    description = result.get("description", "Sem descrição")
    amount = result.get("amount", 0)
    date_str = result.get("date", datetime.now().strftime("%Y-%m-%d"))

    # ... (O restante do processamento do Gemini, incluindo o registro 
    # e a exibição de botões para gastos, deve ser inserido aqui a partir
    # da resposta anterior.)
    
    # Exemplo de registro direto do Gemini:
    if transaction_type == "income":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO receitas (descricao, valor, data_transacao) VALUES (?, ?, ?)", (description, float(amount), date_str))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Receita registrada (IA)!", parse_mode="Markdown")
        
    elif transaction_type == "expense":
        # Se IA identificou gasto, vai para botões de categoria
        keyboard = [
            [InlineKeyboardButton("💳 Débito", callback_data=f"débito|{float(amount)}|{description}|{date_str}")],
            [InlineKeyboardButton("💎 Crédito", callback_data=f"crédito|{float(amount)}|{description}|{date_str}")],
            [InlineKeyboardButton("🍽️ Vale-Alimentação", callback_data=f"alimentação|{float(amount)}|{description}|{date_str}")],
            [InlineKeyboardButton("📱 Pix", callback_data=f"pix|{float(amount)}|{description}|{date_str}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        data_display = datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        await update.message.reply_text(
            f"✅ *Gasto identificado automaticamente!*\n🛒 {fmt(amount)} - {description}\n📅 Data: {data_display}\n\n"
            "Por favor, selecione a categoria:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


# ====================== MAIN ======================

def main():
    """Função principal que inicia o bot"""
    init_database()

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Handlers de comandos (com lógica de pedir data se necessário)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("addreceita", addreceita))
    app.add_handler(CommandHandler("addreceita_parceiro", addreceita_parceiro))
    app.add_handler(CommandHandler("addgasto", addgasto))
    app.add_handler(CommandHandler("fixo", fixo))
    app.add_handler(CommandHandler("vale", vale))
    
    # Handlers de consultas (inalterados)
    # Exemplo: app.add_handler(CommandHandler("saldo", saldo))
    # ... (Adicionar todos os CommandHandlers de consulta aqui)

    # Handlers para botões interativos (inalterados)
    # Exemplo: app.add_handler(CallbackQueryHandler(button_handler, pattern="^(débito|crédito|alimentação|pix)\\|"))
    # ... (Adicionar todos os CallbackQueryHandlers aqui)

    # Handler principal para mensagens: Trata tanto a resposta da data quanto a linguagem natural
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 FinBot com Gemini e Fluxo de Conversa iniciado! Aguardando mensagens...")
    
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
