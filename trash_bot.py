import os
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler
from dotenv import load_dotenv
import re

# Configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
load_dotenv()
# Token del bot (da inserire)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 

# Stati per la conversazione
SELECTING_DAY = 1
SELECTING_TASK = 2
SELECTING_COFFEE_DAY = 3
CONFIGURING_TRASH = 4
ADDING_TRASH_TYPE = 5

# Costanti per i giorni della settimana in italiano
GIORNI = {
    "lunedi": 0,
    "martedi": 1,
    "mercoledi": 2,
    "giovedi": 3,
    "venerdi": 4
}

GIORNI_NOMI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì"]

def isCoffeeDay(day):
    return day in [1,3]

# Funzione per convertire l'indice del giorno nel nome in italiano
def get_giorno_nome(indice):
    return GIORNI_NOMI[indice]

# Funzione per convertire il nome del giorno in italiano nell'indice
def get_giorno_indice(nome):
    nome_lower = nome.lower().replace('ì', 'i').replace('è', 'e')
    return GIORNI.get(nome_lower, 0)  # Default a lunedì se non trovato

# Inizializzazione del database SQLite
def init_db():
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    
    # Tabella per i tipi di spazzatura per ogni giorno
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trash_schedule (
        day_of_week INTEGER PRIMARY KEY,
        trash_types TEXT
    )
    ''')
    
    # Tabella per le prenotazioni della spazzatura
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trash_bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_date DATE,
        user_id INTEGER,
        user_name TEXT
    )
    ''')
    
    # Tabella per le prenotazioni della macchina del caffè
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS coffee_bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_date DATE,
        user_id INTEGER,
        user_name TEXT
    )
    ''')
    
    # Inizializza il calendario della spazzatura se vuoto
    cursor.execute('SELECT COUNT(*) FROM trash_schedule')
    if cursor.fetchone()[0] == 0:
        default_schedule = {
            0: "Indifferenziato",
            1: "Organico",
            2: "Carta",
            3: "Organico",
            4: "Vetro, Organico, Plastica",
        }
        for day, trash_types in default_schedule.items():
            cursor.execute('INSERT INTO trash_schedule VALUES (?, ?)', (day, trash_types))
    
    conn.commit()
    conn.close()


def get_leaderboard():
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    
    # Unisce le prenotazioni di spazzatura e caffè, raggruppando per utente
    cursor.execute('''
        SELECT 
            user_name,
            SUM(trash_count) AS total_trash,
            SUM(coffee_count) AS total_coffee,
            (SUM(trash_count) + SUM(coffee_count)) AS total
        FROM (
            SELECT 
                user_name, 
                COUNT(*) AS trash_count,
                0 AS coffee_count
            FROM trash_bookings
            GROUP BY user_name
            
            UNION ALL
            
            SELECT 
                user_name, 
                0 AS trash_count,
                COUNT(*) AS coffee_count
            FROM coffee_bookings
            GROUP BY user_name
        )
        GROUP BY user_name
        ORDER BY total DESC
        LIMIT 10
    ''')
    
    leaderboard = cursor.fetchall()
    conn.close()
    return leaderboard

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra la classifica delle persone che hanno portato giù la spazzatura e pulito il caffè più volte."""
    leaderboard = get_leaderboard()
    
    if not leaderboard:
        await update.message.reply_text("🏆 Nessuna prenotazione trovata! Sii il primo a prenotarti per portare giù la spazzatura o pulire la macchina del caffè!")
        return
    
    message = "🏆 *Classifica Raccolta Differenziata e Pulizia del Caffè:*\n\n"
    for i, (user_name, total_trash, total_coffee, total) in enumerate(leaderboard, start=1):
        message += f"{i}. {user_name}\n"
        message += f"   - 🗑️ Spazzatura: {total_trash} volte\n"
        message += f"   - ☕ Caffè: {total_coffee} volte\n"
        message += f"   - 🔥 Totale: {total} volte\n\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")


# Funzioni per il database
def get_trash_types(day_of_week):
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT trash_types FROM trash_schedule WHERE day_of_week = ?', (day_of_week,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "Nessuna raccolta"

def set_trash_types(day_of_week, trash_types):
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE trash_schedule SET trash_types = ? WHERE day_of_week = ?', (trash_types, day_of_week))
    conn.commit()
    conn.close()

def add_trash_booking(booking_date, user_id, user_name):
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    
    # Controlla se l'utente è già prenotato per questa data
    cursor.execute('SELECT id FROM trash_bookings WHERE booking_date = ? AND user_id = ?', (booking_date, user_id))
    if cursor.fetchone():
        conn.close()
        return False  # L'utente è già prenotato per questa data
    
    # Aggiunge la prenotazione con la data specifica
    cursor.execute('INSERT INTO trash_bookings (booking_date, user_id, user_name) VALUES (?, ?, ?)',
                  (booking_date, user_id, user_name))
    conn.commit()
    conn.close()
    return True


def add_coffee_booking(booking_date, user_id, user_name):
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    
    # Controlla se l'utente è già prenotato per questa data
    cursor.execute('SELECT id FROM coffee_bookings WHERE booking_date = ? AND user_id = ?', (booking_date, user_id))
    if cursor.fetchone():
        conn.close()
        return False  # L'utente è già prenotato per questa data
    
    # Aggiunge la prenotazione con la data specifica
    cursor.execute('INSERT INTO coffee_bookings (booking_date, user_id, user_name) VALUES (?, ?, ?)',
                  (booking_date, user_id, user_name))
    conn.commit()
    conn.close()
    return True


def get_trash_bookings():
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT booking_date, user_name FROM trash_bookings ORDER BY booking_date')
    bookings = {}
    for date, user_name in cursor.fetchall():
        # La data è già nel formato YYYY-MM-DD, la convertiamo solo per la visualizzazione
        display_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')
        if display_date not in bookings:
            bookings[display_date] = []
        bookings[display_date].append(user_name)
    conn.close()
    return bookings


def get_coffee_bookings():
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT booking_date, user_name FROM coffee_bookings ORDER BY booking_date')
    bookings = {}
    for date, user_name in cursor.fetchall():
        # La data è già nel formato YYYY-MM-DD, la convertiamo solo per la visualizzazione
        display_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')
        if display_date not in bookings:
            bookings[display_date] = []
        bookings[display_date].append(user_name)
    conn.close()
    return bookings

def get_all_trash_types():
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT day_of_week, trash_types FROM trash_schedule ORDER BY day_of_week')
    schedule = {day: types for day, types in cursor.fetchall()}
    conn.close()
    return schedule

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia un messaggio di benvenuto quando viene emesso il comando /start."""
    await help_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia un messaggio di aiuto quando viene emesso il comando /aiuto."""
    await update.message.reply_text(
        "Comandi disponibili:\n"
        "/prenota - Prenota un giorno per portare giù la spazzatura\n"
        "/caffe - Prenota un giorno per pulire la macchina del caffè\n"
        "/visualizza - Visualizza tutte le prenotazioni attuali\n"
        "/cancella - Cancella una prenotazione esistente\n"
        "/calendario - Visualizza il calendario della raccolta differenziata e le prenotazioni rimanenti\n"
        "/configura - Configura i tipi di spazzatura per ogni giorno (solo amministratori)\n"
        "/leaderboard - Mostra la classifica di chi ha portato giù la spazzatura e pulito il caffè\n"
        "/aiuto - Mostra questo messaggio di aiuto",
        parse_mode="Markdown"
    )


async def book_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce il comando /prenota e mostra i giorni disponibili da oggi fino alla fine della settimana prossima."""
    keyboard = []
    today = datetime.now()
    current_weekday = today.weekday()  # 0 = Lunedì, ..., 6 = Domenica
    
    # 1. Mostra i giorni rimanenti di questa settimana (da oggi a Venerdì)
    for day_idx in range(current_weekday, 5):  # Da oggi fino a Venerdì
        day = today + timedelta(days=(day_idx - current_weekday))
        day_name = GIORNI_NOMI[day_idx]
        day_date = day_name + day.strftime(" %d/%m")  # es. "Mercoledì 25/02"
        trash_types = get_trash_types(day_idx)
        keyboard.append([InlineKeyboardButton(
            f"{day_date} - {trash_types}", 
            callback_data=f"book_trash_{day.strftime('%Y-%m-%d')}"
        )])
    
    # 2. Mostra tutti i giorni della settimana prossima (Lunedì - Venerdì)
    next_monday = today + timedelta(days=(7 - current_weekday))  # Trova il prossimo Lunedì
    for day_idx in range(5):  # 0 = Lunedì, ..., 4 = Venerdì
        next_day = next_monday + timedelta(days=day_idx)
        day_name = GIORNI_NOMI[day_idx]
        day_date = day_name + next_day.strftime(" %d/%m")  # es. "Lunedì 03/03"
        trash_types = get_trash_types(day_idx)
        keyboard.append([InlineKeyboardButton(
            f"{day_date} - {trash_types}", 
            callback_data=f"book_trash_{next_day.strftime('%Y-%m-%d')}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Seleziona un giorno per prenotarti a portare la spazzatura:", reply_markup=reply_markup)
    return SELECTING_DAY



async def coffee_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce il comando /caffe e mostra i giorni disponibili da oggi fino alla fine della settimana prossima."""
    keyboard = []
    today = datetime.now()
    current_weekday = today.weekday()  # 0 = Lunedì, ..., 6 = Domenica
    
    # 1. Mostra i giorni rimanenti di questa settimana (da oggi a Venerdì)
    for day_idx in (day for day in range(current_weekday, 5) if isCoffeeDay(day)):  # Da oggi fino al weekend, solo martedì e giovedì
        day = today + timedelta(days=(day_idx - current_weekday))
        day_name = GIORNI_NOMI[day_idx]
        day_date = day_name + day.strftime(" %d/%m")  # es. "Mercoledì 25/02"
        keyboard.append([InlineKeyboardButton(
            f"{day_date}", 
            callback_data=f"book_coffee_{day.strftime('%Y-%m-%d')}"
        )])
    
    # 2. Mostra tutti i giorni della settimana prossima (Lunedì - Venerdì)
    next_monday = today + timedelta(days=(7 - current_weekday))  # Trova il prossimo Lunedì
    for day_idx in (day for day in range(5) if isCoffeeDay(day)):  # Solo i martedì e giovedì
        next_day = next_monday + timedelta(days=day_idx)
        day_name = GIORNI_NOMI[day_idx]
        day_date = day_name + next_day.strftime(" %d/%m")  # es. "Lunedì 03/03"
        keyboard.append([InlineKeyboardButton(
            f"{day_date}", 
            callback_data=f"book_coffee_{next_day.strftime('%Y-%m-%d')}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Seleziona un giorno per prenotarti a pulire la macchina del caffè:", reply_markup=reply_markup)
    return SELECTING_COFFEE_DAY


async def handle_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce la selezione del giorno per la prenotazione e mostra le prenotazioni aggiornate."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_info = f"{user.first_name} {user.last_name if user.last_name else ''} (@{user.username})" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"
    
    callback_data = query.data.split("_")
    booking_type = callback_data[1]  # trash o coffee
    booking_date = callback_data[2]  # La data specifica in formato YYYY-MM-DD
    
    # Verifica che booking_date sia una data valida
    try:
        datetime.strptime(booking_date, '%Y-%m-%d')
    except ValueError:
        await query.edit_message_text("❌ Errore: Data non valida.")
        return ConversationHandler.END
    
    # Usa il nome del giorno in italiano
    day_name = datetime.strptime(booking_date, '%Y-%m-%d').strftime('%A')
    day_name_italian = {
        "Monday": "Lunedì",
        "Tuesday": "Martedì",
        "Wednesday": "Mercoledì",
        "Thursday": "Giovedì",
        "Friday": "Venerdì",
        "Saturday": "Sabato",
        "Sunday": "Domenica"
    }[day_name]
    
    if booking_type == "trash":
        success = add_trash_booking(booking_date, user.id, user_info)
        trash_types = get_trash_types(datetime.strptime(booking_date, '%Y-%m-%d').weekday())
        
        if success:
            message = f"Hai prenotato per portare la spazzatura il *{day_name_italian} {booking_date}*!\nTipo di rifiuti da raccogliere: {trash_types}"
        else:
            message = f"⚠️ Sei già prenotato per portare la spazzatura il *{day_name_italian} {booking_date}*!"
    
    elif booking_type == "coffee":
        success = add_coffee_booking(booking_date, user.id, user_info)
        
        if success:
            message = f"Hai prenotato per pulire la macchina del caffè il *{day_name_italian} {booking_date}*!"
        else:
            message = f"⚠️ Sei già prenotato per pulire la macchina del caffè il *{day_name_italian} {booking_date}*!"
    
    else:
        message = "❌ Si è verificato un errore. Riprova."
    
    # Mostra la conferma della prenotazione
    await query.edit_message_text(message, parse_mode="Markdown")
    
    # Mostra le prenotazioni aggiornate per la data selezionata
    trash_bookings = get_trash_bookings_for_date(booking_date)
    coffee_bookings = get_coffee_bookings_for_date(booking_date)
    
    booking_message = f"📅 *Prenotazioni per {day_name_italian} {booking_date}:*\n\n"
    
    # Prenotazioni per la spazzatura
    booking_message += "🗑️ *Spazzatura:*\n"
    if trash_bookings:
        for user in trash_bookings:
            booking_message += f"• {user}\n"
    else:
        booking_message += "• -\n"
    
    # Prenotazioni per il caffè
    booking_message += "\n☕ *Macchina del Caffè:*\n"
    if coffee_bookings:
        for user in coffee_bookings:
            booking_message += f"• {user}\n"
    else:
        booking_message += "• -\n"
    
    await query.message.reply_text(booking_message, parse_mode="Markdown")
    return ConversationHandler.END


def get_trash_bookings_for_date(booking_date):
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_name FROM trash_bookings WHERE booking_date = ? ORDER BY user_name', (booking_date,))
    bookings = [user_name[0] for user_name in cursor.fetchall()]
    conn.close()
    return bookings


def get_coffee_bookings_for_date(booking_date):
    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_name FROM coffee_bookings WHERE booking_date = ? ORDER BY user_name', (booking_date,))
    bookings = [user_name[0] for user_name in cursor.fetchall()]
    conn.close()
    return bookings

def escape_markdown_basic(text: str) -> str:
    """Escape solo i caratteri speciali per il Markdown normale (_ e *)."""
    return re.sub(r'([_*])', r'\\\1', text)


async def view_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Visualizza le prenotazioni della settimana corrente e della settimana prossima."""
    today = datetime.now()
    trash_bookings = get_trash_bookings()
    coffee_bookings = get_coffee_bookings()
    trash_schedule = get_all_trash_types()
    
    current_weekday = today.weekday()
    
    message = "📋 *Prenotazioni:*\n\n"
    
    # Parte 1: Prenotazioni rimanenti della settimana corrente
    if current_weekday < 5:
        message += "*🗓️ QUESTA SETTIMANA:*\n\n"
        
        days_since_monday = current_weekday
        this_monday = today - timedelta(days=days_since_monday)
        
        for day_idx in range(current_weekday, 5):
            this_day = this_monday + timedelta(days=day_idx)
            booking_date_display = escape_markdown_basic(this_day.strftime('%d/%m/%Y'))
            day_name = escape_markdown_basic(GIORNI_NOMI[day_idx])
            
            trash_types = escape_markdown_basic(trash_schedule.get(day_idx, "Nessuna raccolta"))
            
            message += f"*{day_name} {booking_date_display}*\n"
            message += f"*Spazzatura:* {trash_types}\n"
            
            # Prenotazioni spazzatura
            message += "*Prenotati per la spazzatura:*\n"
            if booking_date_display in trash_bookings:
                for user in trash_bookings[booking_date_display]:
                    message += f"• {escape_markdown_basic(user)}\n"
            else:
                message += "• -\n"
            
            # Prenotazioni macchina caffè, solo se il giorno da stampare è martedì o giovedì
            if isCoffeeDay(day_idx):
                message += "*Prenotati per la macchina del caffè:*\n"
                if booking_date_display in coffee_bookings:
                    for user in coffee_bookings[booking_date_display]:
                        message += f"• {escape_markdown_basic(user)}\n"
                else:
                    message += "• -\n"
                
            message += "\n"
        
        message += "───────────────────\n\n"
    
    # Parte 2: Prenotazioni della settimana prossima
    message += "*🗓️ SETTIMANA PROSSIMA:*\n\n"
    
    days_to_next_monday = (7 - today.weekday()) % 7
    if days_to_next_monday == 0:
        days_to_next_monday = 7
    next_monday = today + timedelta(days=days_to_next_monday)
    
    for day_idx in range(5):
        next_day = next_monday + timedelta(days=day_idx)
        booking_date_display = escape_markdown_basic(next_day.strftime('%d/%m/%Y'))
        day_name = escape_markdown_basic(GIORNI_NOMI[day_idx])
        
        trash_types = escape_markdown_basic(trash_schedule.get(day_idx, "Nessuna raccolta"))
        
        message += f"*{day_name} {booking_date_display}*\n"
        message += f"*Spazzatura:* {trash_types}\n"
        
        message += "*Prenotati per la spazzatura:*\n"
        if booking_date_display in trash_bookings:
            for user in trash_bookings[booking_date_display]:
                message += f"• {escape_markdown_basic(user)}\n"
        else:
            message += "• -\n"
        
        if isCoffeeDay(day_idx):
            message += "*Prenotati per la macchina del caffè:*\n"
            if booking_date_display in coffee_bookings:
                for user in coffee_bookings[booking_date_display]:
                    message += f"• {escape_markdown_basic(user)}\n"
            else:
                message += "• -\n"
            
        message += "\n"
    
    # **Mandiamo il messaggio con Markdown normale**
    await update.message.reply_text(message, parse_mode="Markdown")

async def cancel_booking_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permette all'utente di scegliere il tipo di prenotazione da cancellare."""
    keyboard = [
        [InlineKeyboardButton("🗑️ Cancella prenotazione spazzatura", callback_data="cancel_trash")],
        [InlineKeyboardButton("☕ Cancella prenotazione macchina del caffè", callback_data="cancel_coffee")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Che tipo di prenotazione vuoi cancellare?", reply_markup=reply_markup)

async def cancel_booking_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra le prenotazioni dell'utente per il tipo scelto e permette di cancellarle."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    booking_type = query.data  # "cancel_trash" o "cancel_coffee"

    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()

    if booking_type == "cancel_trash":
        cursor.execute('SELECT booking_date FROM trash_bookings WHERE user_id = ?', (user_id,))
        bookings = cursor.fetchall()
        booking_label = "spazzatura"
        callback_prefix = "delete_trash_"
    else:
        cursor.execute('SELECT booking_date FROM coffee_bookings WHERE user_id = ?', (user_id,))
        bookings = cursor.fetchall()
        booking_label = "macchina del caffè"
        callback_prefix = "delete_coffee_"

    conn.close()

    if not bookings:
        keyboard = [[InlineKeyboardButton("🔙 Indietro", callback_data="go_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"Non hai prenotazioni per la {booking_label} da cancellare.", reply_markup=reply_markup)
        return

    # Ordina le prenotazioni dalla più recente alla più lontana
    sorted_bookings = sorted(bookings, key=lambda x: datetime.strptime(x[0], "%Y-%m-%d"), reverse=True)

    keyboard = [
        [InlineKeyboardButton(f"Cancella {booking[0]}", callback_data=f"{callback_prefix}{booking[0]}")]
        for booking in sorted_bookings
    ]
    
    # Aggiunge il tasto "Indietro"
    keyboard.append([InlineKeyboardButton("🔙 Indietro", callback_data="go_back")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(f"Seleziona una prenotazione della {booking_label} da cancellare:", reply_markup=reply_markup)


async def delete_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancella la prenotazione selezionata dall'utente."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data  # Esempio: "delete_trash_2025-02-28" o "delete_coffee_2025-02-28"
    
    if data.startswith("delete_trash_"):
        booking_date = data.replace("delete_trash_", "")
        table = "trash_bookings"
        booking_label = "spazzatura"
    elif data.startswith("delete_coffee_"):
        booking_date = data.replace("delete_coffee_", "")
        table = "coffee_bookings"
        booking_label = "macchina del caffè"
    else:
        return  # Non dovrebbe mai accadere

    conn = sqlite3.connect('trash_scheduler.db')
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM {table} WHERE user_id = ? AND booking_date = ?', (user_id, booking_date))
    conn.commit()
    conn.close()

    await query.message.edit_text(f"✅ La prenotazione per la {booking_label} del {booking_date} è stata cancellata con successo.")

    
async def view_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Visualizza il calendario settimanale della raccolta differenziata e le prenotazioni rimanenti per la settimana corrente."""
    today = datetime.now()
    current_weekday = today.weekday()  # 0 = Lunedì, 4 = Venerdì
    trash_schedule = get_all_trash_types()
    trash_bookings = get_trash_bookings()
    coffee_bookings = get_coffee_bookings()
    
    message = "📅 *Calendario settimanale della raccolta differenziata:*\n\n"
    
    # Stampa il calendario settimanale
    for i in range(5):  # Da lunedì a venerdì
        day_name = GIORNI_NOMI[i]
        message += f"*{day_name}*: {trash_schedule.get(i, 'Nessuna raccolta')}\n"
    
    message += "\n📌 *Prenotazioni rimanenti per questa settimana:*\n\n"
    
    # Trova il lunedì della settimana corrente
    current_monday = today - timedelta(days=today.weekday())
    print(f"Lunedì corrente: {current_monday.strftime('%d/%m/%Y')}")

    remaining_days = False
    for i in range(current_weekday, 5):  # Dal giorno corrente a venerdì
        next_day = today + timedelta(days=(i - current_weekday))

        booking_date_db = next_day.strftime('%Y-%m-%d')  # Formato per il database
        booking_date_display = next_day.strftime('%d/%m/%Y')  # Formato per l'output
        day_name = GIORNI_NOMI[i]
        
        message += f"*{day_name} {booking_date_display}*\n"
        print(trash_bookings)
        print(booking_date_display)
        # Prenotazioni spazzatura
        message += "*Prenotati per la spazzatura:*\n"
        if booking_date_display in trash_bookings:
            for user in trash_bookings[booking_date_display]:
                message += f"• {user}\n"
        else:
            message += "• -\n"
        
        # Prenotazioni macchina caffè
        if isCoffeeDay(i):
            message += "*Prenotati per la macchina del caffè:*\n"
            if booking_date_display in coffee_bookings:
                for user in coffee_bookings[booking_date_display]:
                    message += f"• {user}\n"
            else:
                message += "• -\n"
        
        message += "\n"
        remaining_days = True
    
    if not remaining_days:
        message += "Non ci sono più giorni lavorativi rimanenti in questa settimana.\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

# Funzione per verificare se l'utente è un amministratore o il proprietario del gruppo
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Recupera i dettagli dell'utente nella chat
    member = await context.bot.get_chat_member(chat_id, user_id)
    
    # Controlla se l'utente è un amministratore o il proprietario del gruppo
    if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
        return True
    return False

# Modifica della funzione configure_command per includere il controllo amministratore
async def configure_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce il comando /configura e mostra i giorni disponibili SOLO per gli amministratori."""
    
    # Verifica se l'utente è un amministratore
    is_user_admin = await is_admin(update, context)
    if not is_user_admin:
        await update.message.reply_text("❌ Questo comando è riservato solo agli amministratori.")
        return ConversationHandler.END
    
    # Se l'utente è un amministratore, continua con la configurazione
    keyboard = []
    for i in range(5):  # 0 = Lunedì, 4 = Venerdì
        day_name = GIORNI_NOMI[i]
        trash_types = get_trash_types(i)
        keyboard.append([InlineKeyboardButton(
            f"{day_name} - {trash_types}", 
            callback_data=f"config_{i}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Seleziona un giorno per configurare i tipi di spazzatura:", reply_markup=reply_markup)
    return CONFIGURING_TRASH

async def handle_day_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce la selezione del giorno per la configurazione."""
    query = update.callback_query
    await query.answer()
    
    selected_day = int(query.data.split("_")[1])
    context.user_data["config_day"] = selected_day
    
    day_name = GIORNI_NOMI[selected_day]
    current_types = get_trash_types(selected_day)
    
    await query.edit_message_text(
        f"Configura i tipi di spazzatura per {day_name}\n"
        f"Attualmente: {current_types}\n\n"
        "Invia un messaggio con i tipi di spazzatura separati da virgola (es. 'Organico, Carta') "
        "o invia /annulla per annullare."
    )
    return ADDING_TRASH_TYPE

async def add_trash_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Aggiunge i tipi di spazzatura per un giorno."""
    if "config_day" not in context.user_data:
        await update.message.reply_text("Si è verificato un errore. Riprova con /configura.")
        return ConversationHandler.END
    
    day = context.user_data["config_day"]
    trash_types = update.message.text.strip()
    
    set_trash_types(day, trash_types)
    
    day_name = GIORNI_NOMI[day]
    
    await update.message.reply_text(f"Tipi di spazzatura per {day_name} aggiornati a: {trash_types}")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancella la conversazione corrente."""
    await update.message.reply_text("Operazione annullata.")
    return ConversationHandler.END

async def set_commands(application):
    commands = [
        BotCommand("start", "Avvia il bot"),
        BotCommand("prenota", "Prenota un giorno per portare giù la spazzatura"),
        BotCommand("cancella", "Cancella la tua prenotazione"),
        BotCommand("visualizza", "Visualizza tutte le prenotazioni"),
        BotCommand("caffe", "Prenota per la spazzatura"),
        BotCommand("calendario", "Visualizza il calendario della raccolta differenziata"),
        BotCommand("configura", "Configura i tipi di spazzatura per ogni giorno"),
        BotCommand("aiuto", "Mostra questo messaggio di aiuto"),
        BotCommand("leaderboard", "Mostra la classifica di chi ha portato giù la spazzatura e pulito il caffè"),
    ]
    
    await application.bot.set_my_commands(commands)
    
async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Torna alla schermata principale di cancellazione."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🗑️ Cancella prenotazione spazzatura", callback_data="cancel_trash")],
        [InlineKeyboardButton("☕ Cancella prenotazione macchina del caffè", callback_data="cancel_coffee")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("Che tipo di prenotazione vuoi cancellare?", reply_markup=reply_markup)
    
def main() -> None:
    """Avvia il bot."""
    # Inizializza il database
    init_db()
    
    # Crea l'applicazione
    application = ApplicationBuilder().token(TOKEN).build()
    # Imposta i comandi
    set_commands(application)
    
    # Crea il conversation handler per la prenotazione spazzatura
    trash_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("prenota", book_command)],
        states={
            SELECTING_DAY: [CallbackQueryHandler(handle_booking, pattern=r"^book_trash_")],
        },
        fallbacks=[CommandHandler("annulla", cancel)],
    )
    
    # Crea il conversation handler per la prenotazione caffè
    coffee_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("caffe", coffee_command)],
        states={
            SELECTING_COFFEE_DAY: [CallbackQueryHandler(handle_booking, pattern=r"^book_coffee_")],
        },
        fallbacks=[CommandHandler("annulla", cancel)],
    )
    
    # Crea il conversation handler per la configurazione
    config_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("configura", configure_command)],
        states={
            CONFIGURING_TRASH: [CallbackQueryHandler(handle_day_config, pattern=r"^config_")],
            ADDING_TRASH_TYPE: [MessageHandler(None, add_trash_type)],
        },
        fallbacks=[CommandHandler("annulla", cancel)],
    )
    
    application.add_handler(CommandHandler("cancella", cancel_booking_command))
    application.add_handler(CallbackQueryHandler(cancel_booking_selection, pattern="^cancel_"))
    application.add_handler(CallbackQueryHandler(delete_booking, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(go_back, pattern="^go_back$"))
    
    # Aggiungi gli handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("aiuto", help_command))
    application.add_handler(CommandHandler("visualizza", view_bookings))
    application.add_handler(CommandHandler("calendario", view_schedule))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(trash_conv_handler)
    application.add_handler(coffee_conv_handler)
    application.add_handler(config_conv_handler)
    
    # Avvia il bot
    application.run_polling()

if __name__ == "__main__":
    main()