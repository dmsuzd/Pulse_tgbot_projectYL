import telebot
from pandas import DataFrame
from tinkoff.invest import Client
from telebot import types
import threading
import time
from io import StringIO
import sqlite3
import csv
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()
bot = telebot.TeleBot(os.getenv("API_TOKEN"))

DB_NAME = "database.sqlite"
with sqlite3.connect(DB_NAME) as db:
    db.execute('''CREATE TABLE IF NOT EXISTS portfolios (
        user_id INTEGER,
        ticker TEXT,
        PRIMARY KEY (user_id, ticker)
    )''')

ticker = ""
USER_ALERTS = {}
USER_PORTFOLIOS = {}
POPULAR_TICKERS = ["sber", "gazp", "smlt", "ydex", "nvtk", "ozon", "lkoh", "rosn", "tsla",
                   "aapl", "goog", "msft", "nvda", "amzn", "meta"]
USER_DB = {}
TEMPORARY_DATA = {}

MARKUP_MAIN = types.ReplyKeyboardMarkup(resize_keyboard=True)
BTN1, BTN2 = types.KeyboardButton("/find_price"), types.KeyboardButton("/export")
BTN3, BTN4, BTN5 = types.KeyboardButton("/portfolio"), types.KeyboardButton("/alerts"), types.KeyboardButton("/help")
MARKUP_MAIN.row(BTN1, BTN2)
MARKUP_MAIN.row(BTN3, BTN4)
MARKUP_MAIN.row(BTN5)


@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id

    if user_id in USER_DB:
        show_main_menu(user_id, f"С возвращением, {message.from_user.first_name}!")
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = types.KeyboardButton("Зарегистрироваться")
        btn2 = types.KeyboardButton("Авторизоваться")
        markup.add(btn1)
        markup.add(btn2)

        bot.send_message(user_id,
                         f"👋 Привет, {message.from_user.first_name}!\n"
                         "🤖 Бот поможет тебе следить за акциями и получать уведомления об их изменениях.\n\n"
                         "Для начала работы необходимо зарегистрироваться или авторизоваться.",
                         reply_markup=markup)


@bot.message_handler(func=lambda message: message.text.lower() == "зарегистрироваться")
def register_start(message):
    user_id = message.chat.id
    TEMPORARY_DATA[user_id] = {"step": "waiting_password"}

    bot.send_message(user_id,
                     "🔐 Придумайте пароль для регистрации (минимум 4 символа):",
                     reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, register_finish)


def register_finish(message):
    user_id = message.chat.id
    password = message.text.strip()
    if len(password) < 4:
        bot.send_message(user_id, "❌ Пароль слишком короткий. Минимум 4 символа.")
        return
    if user_id in USER_DB:
        bot.send_message(user_id, "❌ Вы уже зарегистрированы!")
        return

    USER_DB[user_id] = {
        "password": password,
        "portfolio": [],
        "alerts": {}
    }

    show_main_menu(user_id, "✅ Регистрация успешно завершена!")


@bot.message_handler(func=lambda message: message.text.lower() == "авторизоваться")
def login_start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton("Зарегистрироваться")
    markup.add(btn)

    user_id = message.chat.id
    if user_id not in USER_DB:
        bot.send_message(user_id, "❌ Вы не зарегистрированы. Пожалуйста, зарегистрируйтесь.", reply_markup=markup)
        return

    TEMPORARY_DATA[user_id] = {"step": "waiting_password"}

    bot.send_message(user_id, "🔐 Введите ваш пароль:", reply_markup=types.ReplyKeyboardRemove())

    bot.register_next_step_handler(message, login_finish)


def login_finish(message):
    user_id = message.chat.id
    password = message.text.strip()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton("Авторизация")
    markup.add(btn)

    if USER_DB[user_id]["password"] != password:
        bot.send_message(user_id, "❌ Неверный пароль. Попробуйте снова.", reply_markup=markup)
        login_start(message)
        return

    show_main_menu(user_id, "✅ Вы успешно Авторизовались!")


def show_main_menu(user_id, welcome_message=""):
    bot.send_message(user_id,
                     f"{welcome_message}\n\n"
                     "Для ознакомления воспользуйтесь функцией /help",
                     reply_markup=MARKUP_MAIN)


@bot.message_handler(commands=['help'])
def help(message):
    bot.send_message(message.chat.id, '📊 Доступные команды:\n\n'
                                      '/find_price - получения информации и текущей цены акции по тикеру\n'
                                      '/export - экспорт данных\n'
                                      '/portfolio - добавление/удаление акциий из портфеля\n'
                                      '/alerts - настройка уведомлений о изменениях цен\n\n'
                                      'Пример использования:\n'
                                      '1. Введи /find_price\n'
                                      '2. Выберите или введите тикер акции (например, SBER)\n'
                                      '3. Получи текущую цену акции')


@bot.message_handler(commands=['find_price'])
def find_price(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    buttons = [types.KeyboardButton(ticker) for ticker in POPULAR_TICKERS]
    markup.add(*buttons)
    markup.add(types.KeyboardButton("Отмена"))

    bot.send_message(message.chat.id, '📈 Введи тикер акции или выбери из списка:', reply_markup=markup)
    bot.register_next_step_handler(message, process_ticker)


def process_ticker(message):
    global ticker
    if message.text.lower() == "отмена":
        bot.send_message(message.chat.id, "❌ Действие отменено", reply_markup=MARKUP_MAIN)
        return
    ticker = message.text.strip().lower()

    try:
        with Client(os.getenv("API_TOKEN_INVEST")) as cl:
            instruments = cl.instruments
            r = DataFrame(
                instruments.shares().instruments,
                columns=['name', 'figi', 'ticker', 'currency', 'sector']
            )
            stock_info = r[r['ticker'] == ticker.upper()].iloc[0]
            price_a = run(ticker, message).rstrip(''')( /.,''')
            info_msg = f"📋 Информация об акции:\n\n" \
                       f"Компания: {stock_info['name']}\n" \
                       f"Тикер: {stock_info['ticker']}\n" \
                       f"Валюта: {stock_info['currency']}\n" \
                       f"Сектор: {stock_info['sector']}\n" \
                       f"Текущая цена {ticker.upper()}: {price_a} {stock_info['currency']}\n"

            info_msg += f"\nСсылка на покупку: https://www.tbank.ru/invest/stocks/{stock_info['ticker']}/"

            bot.send_message(message.chat.id, info_msg, reply_markup=MARKUP_MAIN)
            run(ticker, message)

    except Exception:
        bot.send_message(message.chat.id, f'❌ Ошибка! Проверьте правильность тикера и попробуйте снова.',
                         reply_markup=MARKUP_MAIN)


def run(TICKER, message):
    try:
        with Client(os.getenv("API_TOKEN_INVEST")) as client:
            instruments = client.instruments
            r = DataFrame(
                instruments.shares().instruments,
                columns=['name', 'figi', 'ticker']
            )
            figi = r[r['ticker'] == TICKER.upper()]['figi'].iloc[0]
            return main(figi, message, TICKER)
    except Exception:
        bot.send_message(message.chat.id, f'❌ Ошибка, проблема с запросом по акции.')


def main(figi, message, TICKER):
    try:
        with Client(os.getenv("API_TOKEN_INVEST")) as client:
            k = client.market_data.get_last_prices(figi=[str(figi)])
            massive = list(str(k).split(','))
            tmp1 = "".join(massive[1]).split("=")
            tmp2 = "".join(massive[2]).split("=")
            price = f'{tmp1[2]}.{(tmp2[1])[:2]}'

            return price
    except Exception:
        bot.send_message(message.chat.id, f'❌ Не удалось получить цену, попробуйте ещё раз.')


@bot.message_handler(commands=['export'])
def export_menu(message):
    user_id = message.chat.id

    conn = sqlite3.connect('database.sqlite')
    cursor = conn.cursor()

    cursor.execute("SELECT ticker FROM portfolios WHERE user_id=?", (user_id,))
    portfolio = cursor.fetchall()
    print(portfolio)
    conn.close()

    if not portfolio:
        bot.send_message(user_id, "❌ Ваш портфель пуст.", reply_markup=MARKUP_MAIN)
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    btn1 = types.KeyboardButton("📝 TXT")
    btn2 = types.KeyboardButton("📊 CSV")
    btn3 = types.KeyboardButton("🗃️ SQL")
    btn4 = types.KeyboardButton("Отмена")
    markup.add(btn1, btn2, btn3)
    markup.add(btn4)

    bot.send_message(
        user_id,
        "📤 Выберите формат для экспорта вашего портфеля:",
        reply_markup=markup
    )


def get_portfolio_data(user_id, message):
    conn = sqlite3.connect('database.sqlite')
    cursor = conn.cursor()

    cursor.execute("SELECT ticker FROM portfolios WHERE user_id=?", (user_id,))
    tcrk = [i[0] for i in cursor.fetchall()]
    conn.close()

    portfolio = []
    for i in tcrk:
        temp = []
        with Client(os.getenv("API_TOKEN_INVEST")) as cl:
            instruments = cl.instruments
            r = DataFrame(
                instruments.shares().instruments,
                columns=['name', 'figi', 'ticker', 'currency', 'sector']
            )
            stock_info = r[r['ticker'] == i.upper()].iloc[0]
            price_a = run(i, message).rstrip(''')( /.,''')
            temp.append(stock_info['ticker'])
            temp.append(stock_info['name'])
            temp.append(price_a)
            temp.append(stock_info['currency'])
            temp.append(stock_info['sector'])
        portfolio.append(temp)

    return portfolio


@bot.message_handler(func=lambda m: m.text.lower() in ["📝 txt", "txt"])
def export_txt(message):
    user_id = message.chat.id
    portfolio = get_portfolio_data(user_id, message)

    if not portfolio:
        bot.send_message(user_id, "❌ Ваш портфель пуст.", reply_markup=MARKUP_MAIN)
        return

    txt_content = f"Портфель пользователя на {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    txt_content += "{:<10} {:<30} {:<15} {:<10} {:<20}\n".format(
        "Тикер", "Название", "Цена", "Валюта", "Сектор"
    )
    txt_content += "-" * 85 + "\n"

    for item in portfolio:
        ticker, name, price, currency, sector = item
        txt_content += "{:<10} {:<30} {:<15} {:<10} {:<20}\n".format(
            ticker, name or "N/A", str(price) or "N/A", currency or "N/A", sector or "N/A"
        )

    bot.send_document(
        user_id,
        ("portfolio.txt", txt_content.encode('utf-16')),
        caption="📝 Ваш портфель в формате TXT",
        reply_markup=MARKUP_MAIN
    )


@bot.message_handler(func=lambda m: m.text.lower() in ["📊 csv", "csv"])
def export_csv(message):
    user_id = message.chat.id
    portfolio = get_portfolio_data(user_id, message)

    if not portfolio:
        bot.send_message(user_id, "❌ Ваш портфель пуст.", reply_markup=MARKUP_MAIN)
        return

    csv_file = StringIO()
    writer = csv.writer(csv_file)

    writer.writerow(["Тикер", "Название", "Цена", "Валюта", "Сектор", "Дата экспорта"])

    for item in portfolio:
        ticker, name, price, currency, sector = item
        writer.writerow([
            ticker,
            name or "N/A",
            price or "N/A",
            currency or "N/A",
            sector or "N/A",
            datetime.now().strftime('%Y-%m-%d %H:%M')
        ])

    csv_file.seek(0)
    bot.send_document(
        user_id,
        ("portfolio.csv", csv_file.getvalue().encode('utf-16')),
        caption="📊 Ваш портфель в формате CSV",
        reply_markup=MARKUP_MAIN
    )


@bot.message_handler(func=lambda m: m.text.lower() in ["🗃️ sql", " sql"])
def export_sql(message):
    user_id = message.chat.id
    portfolio = get_portfolio_data(user_id, message)

    if not portfolio:
        bot.send_message(user_id, "❌ Ваш портфель пуст.", reply_markup=MARKUP_MAIN)
        return

    sql_content = f"-- Экспорт портфеля пользователя {user_id}\n"
    sql_content += f"-- Дата экспорта: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    sql_content += "CREATE TABLE IF NOT EXISTS exported_portfolio (\n"
    sql_content += "    ticker TEXT PRIMARY KEY,\n"
    sql_content += "    name TEXT,\n"
    sql_content += "    price REAL,\n"
    sql_content += "    currency TEXT,\n"
    sql_content += "    sector TEXT,\n"
    sql_content += "    export_date TEXT\n);\n\n"

    for item in portfolio:
        ticker, name, price, currency, sector = item
        sql_content += (
            f"""INSERT INTO exported_portfolio (ticker, name, price, currency, sector, export_date) """
            f"""VALUES ('{ticker}', {f"'{name}'" if name else 'NULL'}, """
            f"""{price if price else 'NULL'}, {f"'{currency}'" if currency else 'NULL'}, """
            f"""{f"'{sector}'" if sector else 'NULL'}, """
            f"""'{datetime.now().strftime('%Y-%m-%d %H:%M')}');\n"""
        )

    bot.send_document(
        user_id,
        ("portfolio.sql", sql_content.encode('utf-16')),
        caption="🗃️ Ваш портфель в формате SQL",
        reply_markup=MARKUP_MAIN
    )


@bot.message_handler(commands=['portfolio'])
def portfolio(message):
    user_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("Показать портфель")
    btn2 = types.KeyboardButton("Добавить акцию")
    btn3 = types.KeyboardButton("Удалить акцию")
    markup.row(btn1, btn2)
    markup.row(btn3)
    bot.send_message(user_id, f"📊 Управление портфелем", reply_markup=markup)

    bot.register_next_step_handler(message, process_portfolio)


def process_portfolio(message):
    user_id = message.chat.id
    text = message.text.lower()

    if text == "добавить акцию":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        buttons = [types.KeyboardButton(tick) for tick in POPULAR_TICKERS]
        markup.add(*buttons)
        markup.add(types.KeyboardButton("Отмена"))
        bot.send_message(user_id, "Выберете или введите тикер акции для добавления в портфель:", reply_markup=markup)
        bot.register_next_step_handler(message, add_to_portfolio)
    elif text == "удалить акцию":
        show_portfolio_for_deletion(user_id, message)
    elif text == "показать портфель":
        show_full_portfolio(user_id)
    else:
        bot.send_message(user_id, "❌ Неизвестная команда для взаимодействия с портфелем, выберите другую.",
                         reply_markup=MARKUP_MAIN)


def add_to_portfolio(message):
    user_id = message.chat.id
    ticker = message.text.strip().upper()

    if message.text.lower() == "отмена":
        bot.send_message(user_id, "❌ Действие отменено.", reply_markup=MARKUP_MAIN)
        return

    try:
        with Client(os.getenv("API_TOKEN_INVEST")) as cl:
            instruments = cl.instruments
            r = DataFrame(
                instruments.shares().instruments,
                columns=['name', 'figi', 'ticker']
            )

            if ticker not in r['ticker'].values:
                bot.send_message(user_id, "❌ Такой тикер не найден", reply_markup=MARKUP_MAIN)
                return

            if user_id not in USER_PORTFOLIOS:
                USER_PORTFOLIOS[user_id] = []

            if ticker not in USER_PORTFOLIOS[user_id]:
                USER_PORTFOLIOS[user_id].append(ticker)
                bot.send_message(user_id, f"✅ Акция {ticker} добавлена в ваш портфель", reply_markup=MARKUP_MAIN)
                add_to_portfolio_db(user_id, ticker)
            else:
                bot.send_message(user_id, f"ℹ️ Акция {ticker} уже есть в вашем портфеле", reply_markup=MARKUP_MAIN)

    except Exception:
        bot.send_message(user_id, f"❌ Ошибка, попробуйте снова.", reply_markup=MARKUP_MAIN)


def add_to_portfolio_db(user_id, ticker):
    conn = None
    try:
        conn = sqlite3.connect('database.sqlite')
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO portfolios (user_id, ticker)
            VALUES (?, ?)
        """, (user_id, ticker))

        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def show_portfolio_for_deletion(user_id, message):
    if user_id not in USER_PORTFOLIOS or not USER_PORTFOLIOS[user_id]:
        bot.send_message(user_id, "💼 Ваш портфель пуст.", reply_markup=MARKUP_MAIN)
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3, one_time_keyboard=True)
    buttons = [types.KeyboardButton(tick) for tick in USER_PORTFOLIOS[user_id]]
    markup.add(*buttons)
    markup.add(types.KeyboardButton("Отмена"))

    bot.send_message(user_id, "📋 Выберите акцию для удаления:", reply_markup=markup)

    bot.register_next_step_handler(message, process_ticker_selection, user_id)


def show_full_portfolio(user_id):
    if user_id not in USER_PORTFOLIOS or not USER_PORTFOLIOS[user_id]:
        bot.send_message(user_id, "💼 Ваш портфель пуст.", reply_markup=MARKUP_MAIN)
        return

    portfolio_msg = "💼 Ваш портфель:\n\n"
    total_value = 0

    with Client(os.getenv("API_TOKEN_INVEST")) as client:
        for ticker in USER_PORTFOLIOS[user_id]:
            try:
                instruments = client.instruments
                r = DataFrame(
                    instruments.shares().instruments,
                    columns=['name', 'figi', 'ticker']
                )
                figi = r[r['ticker'] == ticker]['figi'].iloc[0]

                k = client.market_data.get_last_prices(figi=[str(figi)])
                massive = list(str(k).split(','))
                tmp1 = "".join(massive[1]).split("=")
                tmp2 = "".join(massive[2]).split("=")
                price = float(f'{tmp1[2]}.{(tmp2[1])[:2]}'.rstrip(''')( /.,'''))
                total_value += price

                portfolio_msg += f"{ticker}: {price} руб.\n"

            except Exception:
                portfolio_msg += f"{ticker}: не удалось получить цену.\n"

    portfolio_msg += f"\n💰Общая стоимость: {round(total_value, 2)} руб."
    bot.send_message(user_id, portfolio_msg, reply_markup=MARKUP_MAIN)


def process_ticker_selection(message, user_id):
    if message.text.lower() == "отмена":
        bot.send_message(user_id, "❌ Действие отменено.", reply_markup=MARKUP_MAIN)
        return

    selected_ticker = message.text
    if selected_ticker in USER_PORTFOLIOS.get(user_id, []):
        USER_PORTFOLIOS[user_id].remove(selected_ticker)
        bot.send_message(user_id, f"✅ Акция {selected_ticker} успешно удалена из портфеля.", reply_markup=MARKUP_MAIN)
        delete_from_portfolio(user_id, ticker)
    else:
        bot.send_message(user_id, "❌ Указанная акция не найдена в вашем портфеле.", reply_markup=MARKUP_MAIN)


def delete_from_portfolio(user_id, ticker):
    conn = None
    try:
        conn = sqlite3.connect('database.sqlite')
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM portfolios 
            WHERE user_id = ? AND ticker = ?
        """, (user_id, ticker))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Ошибка базы данных: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


@bot.message_handler(commands=['alerts'])
def alerts(message):
    user_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    btn1 = types.KeyboardButton("Мои уведомления")
    btn2 = types.KeyboardButton("Добавить уведомление")
    btn3 = types.KeyboardButton("Удалить уведомление")
    markup.row(btn1, btn2)
    markup.row(btn3)

    bot.send_message(user_id, "🔔 Управление уведомлениями:", reply_markup=markup)

    bot.register_next_step_handler(message, process_alerts)


def process_alerts(message):
    user_id = message.chat.id
    text = message.text.lower()

    if text == "добавить уведомление":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        buttons = [types.KeyboardButton(tick) for tick in POPULAR_TICKERS]
        markup.add(*buttons)
        markup.add(types.KeyboardButton("Отмена"))
        bot.send_message(user_id, "Введите или выберите тикер акции для уведомления:", reply_markup=markup)
        bot.register_next_step_handler(message, add_alert_step1)
    elif text == "удалить уведомление":
        show_alerts_for_deletion(user_id)
    elif text == "мои уведомления":
        show_user_alerts(user_id)
    else:
        bot.send_message(user_id, "❌ Неизвестная команда для взаимодействия с уведомлениями, выберите другую.",
                         reply_markup=MARKUP_MAIN)


def add_alert_step1(message):
    user_id = message.chat.id
    ticker = message.text.strip().upper()

    if message.text.lower() == "отмена":
        bot.send_message(user_id, "❌ Действие отменено.", reply_markup=MARKUP_MAIN)
        return

    try:
        with Client(os.getenv("API_TOKEN_INVEST")) as cl:
            instruments = cl.instruments
            r = DataFrame(
                instruments.shares().instruments,
                columns=['name', 'figi', 'ticker']
            )

            if ticker not in r['ticker'].values:
                bot.send_message(user_id, "❌ Данный тикер не найден.", reply_markup=MARKUP_MAIN)
                return

            bot.send_message(user_id, f"Введите процент изменения цены для уведомления (например, 5 для 5%):",
                             reply_markup=types.ReplyKeyboardRemove())
            bot.register_next_step_handler(message, add_alert_step2, ticker)

    except Exception:
        bot.send_message(user_id, f"❌ Ошибка, попробуйте снова.", reply_markup=MARKUP_MAIN)


def add_alert_step2(message, ticker):
    user_id = message.chat.id
    try:
        percent = float(message.text)

        if user_id not in USER_ALERTS:
            USER_ALERTS[user_id] = {}

        USER_ALERTS[user_id][ticker] = percent

        with Client(os.getenv("API_TOKEN_INVEST")) as client:
            instruments = client.instruments
            r = DataFrame(
                instruments.shares().instruments,
                columns=['name', 'figi', 'ticker']
            )
            figi = r[r['ticker'] == ticker]['figi'].iloc[0]
            k = client.market_data.get_last_prices(figi=[str(figi)])
            massive = list(str(k).split(','))
            tmp1 = "".join(massive[1]).split("=")
            tmp2 = "".join(massive[2]).split("=")
            current_price = float(f'{tmp1[2]}.{(tmp2[1])[:2]}'.rstrip(''')( /.,'''))
            USER_ALERTS[user_id][f"{ticker}_price"] = current_price
        bot.send_message(user_id, f"🔔 Уведомление для {ticker} на {percent}% успешно добавлено!",
                         reply_markup=MARKUP_MAIN)

    except Exception:
        bot.send_message(user_id, f"❌ Некорректная запись.", reply_markup=MARKUP_MAIN)


def show_user_alerts(user_id):
    if user_id not in USER_ALERTS or not USER_ALERTS[user_id]:
        bot.send_message(user_id, "🔔 У вас нет активных уведомлений", reply_markup=MARKUP_MAIN)
        return

    alerts_msg = "🔔 Ваши активные уведомления:\n\n"
    for ticker in [k for k in USER_ALERTS[user_id].keys() if not k.endswith("_price")]:
        alerts_msg += f"{ticker}: уведомление при изменении на {USER_ALERTS[user_id][ticker]}%\n"

    bot.send_message(user_id, alerts_msg, reply_markup=MARKUP_MAIN)


def show_alerts_for_deletion(user_id):
    if user_id not in USER_ALERTS or not USER_ALERTS[user_id]:
        bot.send_message(user_id, "🔔 У вас нет активных уведомлений.", reply_markup=MARKUP_MAIN)
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3, one_time_keyboard=True)
    tickers = [k for k in USER_ALERTS[user_id].keys() if not k.endswith("_price")]

    if not tickers:
        bot.send_message(user_id, "🔔 Нет уведомлений для удаления.", reply_markup=MARKUP_MAIN)
        return

    buttons = [types.KeyboardButton(tick) for tick in tickers]
    markup.add(*buttons)
    markup.add(types.KeyboardButton("Отмена"))

    msg = bot.send_message(user_id, "📋 Выберите уведомление для удаления:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_alert_deletion, user_id)


def process_alert_deletion(message, user_id):
    if message.text.lower() == "отмена":
        bot.send_message(user_id, "❌ Действие отменено.", reply_markup=MARKUP_MAIN)
        return

    ticker = message.text.upper()
    if ticker in USER_ALERTS.get(user_id, {}):
        del USER_ALERTS[user_id][ticker]
        if f"{ticker}_price" in USER_ALERTS[user_id]:
            del USER_ALERTS[user_id][f"{ticker}_price"]
        bot.send_message(user_id, f"✅ Уведомления для {ticker} успешно удалены.", reply_markup=MARKUP_MAIN)
    else:
        bot.send_message(user_id, f"❌ Уведомление для {ticker} не найдено.", reply_markup=MARKUP_MAIN)


def check_price_changes():
    while True:
        try:
            for user_id in list(USER_ALERTS.keys()):
                if not USER_ALERTS[user_id]:
                    continue
                with Client(os.getenv("API_TOKEN_INVEST")) as client:
                    instruments = client.instruments
                    r = DataFrame(
                        instruments.shares().instruments,
                        columns=['name', 'figi', 'ticker']
                    )
                    alerts_to_check = [k for k in USER_ALERTS[user_id].keys() if not k.endswith("_price")]
                    for ticker in alerts_to_check:
                        try:
                            figi = r[r['ticker'] == ticker]['figi'].iloc[0]
                            k = client.market_data.get_last_prices(figi=[str(figi)])
                            massive = list(str(k).split(','))
                            tmp1 = "".join(massive[1]).split("=")
                            tmp2 = "".join(massive[2]).split("=")
                            current_price = float(f'{tmp1[2]}.{(tmp2[1])[:2]}'.rstrip(''')( /.,'''))

                            old_price = USER_ALERTS[user_id].get(f"{ticker}_price", current_price)
                            percent_change = abs((current_price - old_price) / old_price * 100)
                            alert_percent = USER_ALERTS[user_id][ticker]

                            if percent_change >= alert_percent:
                                direction = "выросла" if current_price > old_price else "упала"
                                bot.send_message(
                                    user_id,
                                    f"🚨 {ticker}: цена {direction} на {round(percent_change, 2)}%!\n"
                                    f"Старая цена: {old_price}\n"
                                    f"Текущая цена: {current_price}"
                                )
                                USER_ALERTS[user_id][f"{ticker}_price"] = current_price

                        except Exception as e:
                            print(f"Ошибка при проверке {ticker} для пользователя {user_id}: {str(e)}")
                            continue
        except Exception as e:
            print(f"Ошибка в check_price_changes: {str(e)}")

        time.sleep(300)


@bot.message_handler(func=lambda message: True)
def empty(message):
    bot.send_message(message.chat.id, '❌ Неизвестный текст, воспользуйтесь функциями', reply_markup=MARKUP_MAIN)


threading.Thread(target=check_price_changes, daemon=True).start()
bot.polling(none_stop=True)
