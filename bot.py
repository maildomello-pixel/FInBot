import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import locale

# Configuração de moeda brasileira
locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")

def fmt(valor):
    """Formata número em moeda brasileira (R$)."""
    try:
        valor = float(valor)
    except (ValueError, TypeError):
        valor = 0.0
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# ---------------------- COMANDOS ---------------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Olá! Bem-vindo ao *FinBot*. Digite /ajuda para ver todos os comandos disponíveis.",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📌 *Comandos disponíveis:*\n\n"
        "🚀 /start - Iniciar o FinBot\n"
        "❓ /ajuda - Mostrar comandos disponíveis\n\n"
        "💵 /addreceita valor descrição - Registrar receita sua\n"
        "Ex: /addreceita 2000 Salário\n\n"
        "👩‍❤️‍👨 /addreceita_parceiro valor descrição - Registrar receita da parceira\n"
        "Ex: /addreceita_parceiro 1500 Salário\n\n"
        "🛒 /addgasto valor descrição - Registrar gasto\n"
        "Será pedido para escolher categoria: débito, crédito, alimentação, Pix\n\n"
        "🏠 /fixo valor descrição - Registrar despesa fixa\n"
        "Ex: /fixo 1200 Aluguel\n\n"
        "🍽️ /vale valor - Registrar vale-alimentação\n"
        "Ex: /vale 800\n\n"
        "📊 /saldo - Mostrar saldo atual\n"
        "🔥 /top3 - Mostrar três maiores gastos\n"
        "🧘 /mtp - Aplicar Método Traz Paz\n"
        "📄 /relatorio - Gerar relatório mensal\n"
        "🗑️ /reset - Apagar todos os dados"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def addreceita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:])
    except:
        await update.message.reply_text("❗ Uso correto: /addreceita valor descrição")
        return
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receitas (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Receita registrada: {fmt(valor)} ({descricao})")

async def addreceita_parceiro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:])
    except:
        await update.message.reply_text("❗ Uso correto: /addreceita_parceiro valor descrição")
        return
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receitas_parceiro (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Receita da parceira registrada: {fmt(valor)} ({descricao})")

async def addgasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:])
    except:
        await update.message.reply_text("❗ Uso correto: /addgasto valor descrição")
        return
    keyboard = [
        [InlineKeyboardButton("Débito", callback_data=f"débito|{valor}|{descricao}")],
        [InlineKeyboardButton("Crédito", callback_data=f"crédito|{valor}|{descricao}")],
        [InlineKeyboardButton("Vale-Alimentação", callback_data=f"alimentação|{valor}|{descricao}")],
        [InlineKeyboardButton("Pix", callback_data=f"pix|{valor}|{descricao}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Selecione a categoria para {fmt(valor)} ({descricao}):", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria, valor, descricao = query.data.split("|")
    valor = float(valor)
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO gastos (valor, descricao, categoria) VALUES (?, ?, ?)", (valor, descricao, categoria))
    conn.commit()
    conn.close()
    await query.edit_message_text(f"✅ Gasto registrado: {fmt(valor)} ({descricao})\ncategoria: {categoria}")

async def fixo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(context.args[0])
        descricao = " ".join(context.args[1:])
    except:
        await update.message.reply_text("❗ Uso correto: /fixo valor descrição")
        return
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO fixos (descricao, valor) VALUES (?, ?)", (descricao, valor))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Despesa fixa registrada: {fmt(valor)} ({descricao})")

async def vale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(context.args[0])
    except:
        await update.message.reply_text("❗ Uso correto: /vale valor")
        return
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vales (valor) VALUES (?)", (valor,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Vale-alimentação registrado: {fmt(valor)}")

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
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
    conn.close()
    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos
    await update.message.reply_text(f"💳 Saldo atual: {fmt(saldo)}")

async def top3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT valor, descricao FROM gastos ORDER BY valor DESC LIMIT 3")
    top = cursor.fetchall()
    conn.close()
    msg = "🔥 *Top 3 maiores gastos:*\n"
    for gasto in top:
        msg += f"- {gasto[1]}: {fmt(gasto[0])}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def mtp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
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
    conn.close()
    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos
    guardar = saldo * 0.5
    livre = saldo * 0.5
    reserva_emergencia = guardar * 0.5
    reserva_dividas = guardar * 0.5
    msg = (
        f"🧘 *Método Traz Paz (MTP)*\n"
        f"- Guardar: {fmt(guardar)}\n"
        f"  • Reserva de emergência: {fmt(reserva_emergencia)}\n"
        f"  • Reserva para dívidas: {fmt(reserva_dividas)}\n"
        f"- Livre para gastar: {fmt(livre)}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("finbot.db")
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
    conn.close()

    saldo = total_receitas + total_receitas_parceiro + total_vales - total_gastos - total_fixos
    guardar = saldo * 0.5
    livre = saldo * 0.5
    reserva_emergencia = guardar * 0.5
    reserva_dividas = guardar * 0.5

    msg = "📄 *Relatório Mensal:*\n\n"

    msg += "💰 *Receitas:*\n"
    for rec in receitas:
        msg += f"- {rec[0]}: {fmt(rec[1])}\n"
    for rec in receitas_parceiro:
        msg += f"- {rec[0]} (parceira): {fmt(rec[1])}\n"

    msg += f"\n📊 *Gastos:*\n"
    total_gastos_lista = 0
    for g in gastos:
        msg += f"- {g[1]} ({g[2]}): {fmt(g[0])}\n"
        total_gastos_lista += float(g[0])
    msg += f"🔹 *Total gastos:* {fmt(total_gastos_lista)}\n"

    msg += "\n🏠 *Despesas Fixas:*\n"
    for f in fixos:
        msg += f"- {f[0]}: {fmt(f[1])}\n"

    msg += "\n🍽️ *Vale-alimentação:*\n"
    for val in vales:
        msg += f"- {fmt(val[0])}\n"

    msg += f"\n💳 *Saldo:* {fmt(saldo)}\n"

    msg += "\n🧘 *Método Traz Paz (MTP)*\n"
    msg += f"- Guardar (50%): {fmt(guardar)}\n"
    msg += f"  • Reserva de emergência: {fmt(reserva_emergencia)}\n"
    msg += f"  • Reserva para pagamento de dívidas: {fmt(reserva_dividas)}\n"
    msg += f"- Livre para gastar (50%): {fmt(livre)}"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS receitas")
    cursor.execute("DROP TABLE IF EXISTS receitas_parceiro")
    cursor.execute("DROP TABLE IF EXISTS gastos")
    cursor.execute("DROP TABLE IF EXISTS fixos")
    cursor.execute("DROP TABLE IF EXISTS vales")
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ Todos os dados foram apagados com sucesso. O bot foi resetado.")

# ---------------------- INICIALIZAÇÃO ---------------------- #

def main():
    conn = sqlite3.connect("finbot.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS receitas (descricao TEXT, valor REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS receitas_parceiro (descricao TEXT, valor REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS gastos (valor REAL, descricao TEXT, categoria TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS fixos (descricao TEXT, valor REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS vales (valor REAL)")
    conn.commit()
    conn.close()

    app = Application.builder().token("8421394901:AAF4ZEbRTu3xFGRDHYJu7GTUfiIOlmtN94Y").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("addreceita", addreceita))
    app.add_handler(CommandHandler("addreceita_parceiro", addreceita_parceiro))
    app.add_handler(CommandHandler("addgasto", addgasto))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("fixo", fixo))
    app.add_handler(CommandHandler("vale", vale))
    app.add_handler(CommandHandler("saldo", saldo))
    app.add_handler(CommandHandler("top3", top3))
    app.add_handler(CommandHandler("mtp", mtp))
    app.add_handler(CommandHandler("relatorio", relatorio))
    app.add_handler(CommandHandler("reset", reset))

    app.run_polling()

if __name__ == "__main__":
    main()
