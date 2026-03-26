import os
import time
import ccxt
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich import box

load_dotenv()
console = Console()

BINANCE_PUB = os.getenv('BINANCE_PUBLIC_KEY')
BINANCE_SEC = os.getenv('BINANCE_SECRET_KEY')

if not all([BINANCE_PUB, BINANCE_SEC]):
    console.print("[bold red]Erreur API Binance[/bold red]")
    exit()

exchange = ccxt.binance({
    'apiKey': BINANCE_PUB,
    'secret': BINANCE_SEC,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True
    }
})
exchange.set_sandbox_mode(True)

ai_pool = []
gemini_model = None
openai_client = None
mistral_client = None

GEMINI_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    ai_pool.append("GEMINI")

OPENAI_KEY = os.getenv('OPENAI_API_KEY')
if OPENAI_KEY:
    openai_client = OpenAI(api_key=OPENAI_KEY)
    ai_pool.append("OPENAI")

MISTRAL_KEY = os.getenv('MISTRAL_API_KEY')
if MISTRAL_KEY:
    mistral_client = OpenAI(api_key=MISTRAL_KEY, base_url="https://api.mistral.ai/v1")
    ai_pool.append("MISTRAL")

if not ai_pool:
    console.print("[bold red]Erreur : Aucune cle API IA detectee[/bold red]")
    exit()

try:
    exchange.load_markets()
    SYMBOLS = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
except Exception:
    SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

QUOTE_CURRENCY = 'USDT'
TIMEFRAME = '1m'
LOOP_INTERVAL = 1

global_data = {
    "start_time": datetime.now(),
    "start_balance_usdt": 0.0,
    "current_balance_usdt": 0.0,
    "total_pnl_usdt": 0.0,
    "total_pnl_percent": 0.0,
    "trades": [],
    "global_status": "Initialisation...",
    "last_scanned": [],
    "ai_wins": 0,
    "ai_losses": 0,
    "ai_logs": []
}

coin_data = {
    sym: {
        "base": sym.split('/')[0],
        "balance": 0.0,
        "last_price": 0.0,
        "last_decision": "ATTENDRE",
        "last_buy_price": 0.0,
        "last_trade_result": "Aucun",
        "rsi": 50.0,
        "sma": 0.0
    } for sym in SYMBOLS
}

def add_ai_log(msg):
    time_str = datetime.now().strftime('%H:%M:%S')
    global_data["ai_logs"].append(f"[{time_str}] {msg}")
    if len(global_data["ai_logs"]) > 5:
        global_data["ai_logs"].pop(0)

def calculate_sma(prices, period=7):
    if len(prices) < period:
        return 0
    return sum(prices[-period:]) / period

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def fetch_all_data():
    try:
        balance = exchange.fetch_balance()
        global_data["current_balance_usdt"] = balance.get(QUOTE_CURRENCY, {}).get('free', 0.0)
        
        for sym in SYMBOLS:
            base = coin_data[sym]["base"]
            coin_data[sym]["balance"] = balance.get(base, {}).get('free', 0.0)
        return True
    except Exception as e:
        global_data["global_status"] = f"Erreur reseau balances: {str(e)[:30]}"
        return False

def query_single_ai(provider, prompt):
    try:
        if provider == "GEMINI":
            response = gemini_model.generate_content(prompt)
            return response.text.strip().upper()
        elif provider == "OPENAI":
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10
            )
            return response.choices[0].message.content.strip().upper()
        elif provider == "MISTRAL":
            response = mistral_client.chat.completions.create(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10
            )
            return response.choices[0].message.content.strip().upper()
    except Exception:
        return "ERREUR_API"
    return "ERREUR_API"

def analyze_symbol_consensus(sym):
    try:
        ohlcv = exchange.fetch_ohlcv(sym, TIMEFRAME, limit=30)
        if not ohlcv:
            return "ATTENDRE", 0.0, "-"
            
        closes = [d[4] for d in ohlcv]
        
        if len(set(closes)) == 1:
            coin_data[sym]["rsi"] = 50.0
            coin_data[sym]["sma"] = closes[0]
            if coin_data[sym]["balance"] < 0.0001:
                return "ATTENDRE", 0.0, "FILTRE_ZOMBIE"
                
        rsi = calculate_rsi(closes)
        sma = calculate_sma(closes)
        coin_data[sym]["rsi"] = rsi
        coin_data[sym]["sma"] = sma
        
        if 30 <= rsi <= 70 and coin_data[sym]["balance"] < 0.0001:
            return "ATTENDRE", 0.0, "FILTRE_LOCAL"
            
        feedback = coin_data[sym]["last_trade_result"]
        if coin_data[sym]["balance"] > 0.0001 and coin_data[sym]["last_buy_price"] > 0:
            latent_pnl = ((coin_data[sym]["last_price"] - coin_data[sym]["last_buy_price"]) / coin_data[sym]["last_buy_price"]) * 100
            feedback = f"Achat a {coin_data[sym]['last_buy_price']}, PnL: {latent_pnl:.2f}%."

        prompt = f"Expert HFT sur {sym}. Prix: {coin_data[sym]['last_price']}. RSI: {rsi:.2f}. SMA: {sma:.2f}. Historique: {feedback}. Capital: {global_data['current_balance_usdt']:.2f}. Score: {global_data['ai_wins']}V - {global_data['ai_losses']}D. Reponds UNIQUEMENT: ACTION:POURCENTAGE."
        
        add_ai_log(f"Requete envoyee pour {sym} | RSI: {rsi:.1f}")
        
        votes = []
        pcts = []
        responded_ais = []
        log_responses = []
        
        for provider in ai_pool:
            raw_response = query_single_ai(provider, prompt)
            if "ERREUR" not in raw_response:
                text_resp = raw_response.split(':')
                action = text_resp[0] if len(text_resp) > 0 else "ATTENDRE"
                pct = float(text_resp[1]) if len(text_resp) > 1 and text_resp[1].replace('.','',1).isdigit() else 0.0
                if action in ["ACHETER", "VENDRE", "ATTENDRE"]:
                    votes.append(action)
                    if pct > 0: pcts.append(pct)
                    responded_ais.append(provider)
                    log_responses.append(f"{provider}:{action}")
            else:
                log_responses.append(f"{provider}:BLOCKED")
                    
        add_ai_log(f"Reponses recues : {' | '.join(log_responses)}")
        
        if not votes:
            return "LIMITE_API", 0.0, "AUCUNE"
            
        buy_count = votes.count("ACHETER")
        sell_count = votes.count("VENDRE")
        majority_threshold = len(votes) / 2
        
        final_action = "ATTENDRE"
        if buy_count > majority_threshold:
            final_action = "ACHETER"
        elif sell_count > majority_threshold:
            final_action = "VENDRE"
            
        avg_pct = sum(pcts) / len(pcts) if pcts and final_action != "ATTENDRE" else 0.0
        ai_str = "+".join(responded_ais) if responded_ais else "AUCUNE"
        
        return final_action, min(max(avg_pct, 0.0), 100.0), ai_str
        
    except Exception:
        return "ERREUR_SYSTEME", 0.0, "ERREUR"

def execute_trade(sym, action, pct):
    if pct <= 0:
        return
        
    price = coin_data[sym]["last_price"]
    
    try:
        if action == "ACHETER" and global_data["current_balance_usdt"] > 5.0:
            trade_usdt = (global_data["current_balance_usdt"] * pct) / 100.0
            if trade_usdt < 5.0:
                trade_usdt = global_data["current_balance_usdt"]
                
            raw_amount = trade_usdt / price
            amount = float(Decimal(str(raw_amount)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))
            exchange.create_market_buy_order(sym, amount)
            
            coin_data[sym]["last_buy_price"] = price
            coin_data[sym]["last_trade_result"] = f"ACHAT a {price} ({pct:.1f}%)"
            
            global_data["trades"].append({
                "time": datetime.now().strftime('%H:%M:%S'),
                "sym": sym, "type": "ACHAT", "price": price, "amount": amount, "total": trade_usdt
            })
            
        elif action == "VENDRE" and coin_data[sym]["balance"] > 0.0001:
            sell_amount = (coin_data[sym]["balance"] * pct) / 100.0
            amount = float(Decimal(str(sell_amount)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))
            
            if amount <= 0:
                return
                
            exchange.create_market_sell_order(sym, amount)
            total_usdt = amount * price
            
            if coin_data[sym]["last_buy_price"] > 0:
                pnl = ((price - coin_data[sym]["last_buy_price"]) / coin_data[sym]["last_buy_price"]) * 100
                res = "PROFIT" if pnl >= 0 else "PERTE"
                coin_data[sym]["last_trade_result"] = f"VENTE a {price}. {res}: {pnl:.2f}%"
                
                if pnl >= 0:
                    global_data["ai_wins"] += 1
                else:
                    global_data["ai_losses"] += 1
            
            global_data["trades"].append({
                "time": datetime.now().strftime('%H:%M:%S'),
                "sym": sym, "type": "VENTE", "price": price, "amount": amount, "total": total_usdt
            })
    except Exception:
        pass

def update_pnl():
    total_crypto_value = sum([coin_data[sym]["balance"] * coin_data[sym]["last_price"] for sym in SYMBOLS])
    current_value = global_data["current_balance_usdt"] + total_crypto_value
    
    if global_data["start_balance_usdt"] > 0:
        global_data["total_pnl_usdt"] = current_value - global_data["start_balance_usdt"]
        global_data["total_pnl_percent"] = (global_data["total_pnl_usdt"] / global_data["start_balance_usdt"]) * 100

def make_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", size=10),
        Layout(name="ai_logs", size=8),
        Layout(name="footer", size=10)
    )
    return layout

def get_header_panel():
    time_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pool_str = " | ".join(ai_pool)
    score_str = f"Score : {global_data['ai_wins']}V - {global_data['ai_losses']}D"
    return Panel(Text(f"CONSENSUS HFT | {pool_str} | {score_str} | Statut: {global_data['global_status']}", justify="center", style="bold white on blue"), box=box.SIMPLE)

def get_balance_panel():
    table = Table(show_header=True, header_style="bold magenta", box=box.HORIZONTALS, expand=True)
    table.add_column("Actif", justify="center")
    table.add_column("Solde Dispo", justify="right")
    table.add_column("Valeur USDT", justify="right")
    
    table.add_row(QUOTE_CURRENCY, f"{global_data['current_balance_usdt']:.2f}", f"{global_data['current_balance_usdt']:.2f}")
    
    active_assets = 0
    for sym in SYMBOLS:
        base = coin_data[sym]["base"]
        bal = coin_data[sym]["balance"]
        if bal > 0.0001:
            val = bal * coin_data[sym]["last_price"]
            table.add_row(base, f"{bal:.5f}", f"{val:.2f}")
            active_assets += 1
            
    if active_assets == 0:
         table.add_row("-", "-", "-")
            
    pnl_style = "bold green" if global_data["total_pnl_usdt"] >= 0 else "bold red"
    pnl_text = f"{global_data['total_pnl_usdt']:.2f} USDT ({global_data['total_pnl_percent']:.2f}%)"
    return Panel(table, title=f"[bold white]Portefeuille | P/L: [/bold white][{pnl_style}]{pnl_text}[/{pnl_style}]", border_style="magenta")

def get_market_panel():
    table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)
    table.add_column("Paire", justify="left")
    table.add_column("Prix", justify="right")
    table.add_column("RSI", justify="center")
    table.add_column("Consensus IA", justify="center")
    
    display_syms = global_data["last_scanned"][-8:] if global_data["last_scanned"] else SYMBOLS[:8]
    
    for sym in reversed(display_syms):
        dec = coin_data[sym]["last_decision"]
        style = "green" if "ACHETER" in dec else "red" if "VENDRE" in dec else "white"
        if "LIMITE" in dec or "ERREUR" in dec:
            style = "yellow"
        elif "ZOMBIE" in dec:
            style = "dim cyan"
            
        table.add_row(
            sym,
            f"{coin_data[sym]['last_price']:.4f}",
            f"{coin_data[sym]['rsi']:.1f}",
            Text(dec, style=style)
        )
        
    return Panel(table, title="[bold white]Scanner Actif[/bold white]", border_style="cyan")

def get_ai_logs_panel():
    text = Text()
    for log in global_data["ai_logs"]:
        text.append(f"{log}\n")
    if not global_data["ai_logs"]:
        text.append("En attente des premieres analyses...", style="italic gray")
    return Panel(text, title="[bold white]Cerveau IA (Communication en direct)[/bold white]", border_style="blue")

def get_trades_panel():
    table = Table(show_header=True, header_style="bold yellow", box=box.SIMPLE, expand=True)
    table.add_column("Heure", justify="center")
    table.add_column("Paire", justify="center")
    table.add_column("Type", justify="center")
    table.add_column("Prix", justify="right")
    table.add_column("Total USDT", justify="right")
    
    for t in global_data["trades"][-3:]:
        type_style = "green" if t["type"] == "ACHAT" else "red"
        table.add_row(t["time"], t["sym"], Text(t["type"], style=type_style), f"{t['price']:.4f}", f"{t['total']:.2f}")
        
    return Panel(table, title="[bold white]Historique des Ordres[/bold white]", border_style="yellow")

def run_bot():
    layout = make_layout()
    
    if not fetch_all_data():
        return
        
    total_crypto = sum([coin_data[sym]["balance"] * coin_data[sym]["last_price"] for sym in SYMBOLS])
    global_data["start_balance_usdt"] = global_data["current_balance_usdt"] + total_crypto
    
    if global_data["start_balance_usdt"] < 10.0:
        global_data["current_balance_usdt"] = 100.0
        global_data["start_balance_usdt"] = 100.0

    layout["header"].update(get_header_panel())
    layout["main"].split_row(get_balance_panel(), get_market_panel())
    layout["ai_logs"].update(get_ai_logs_panel())
    layout["footer"].update(get_trades_panel())

    with Live(layout, refresh_per_second=2, screen=True) as live:
        while True:
            for sym in SYMBOLS:
                if sym not in global_data["last_scanned"]:
                    global_data["last_scanned"].append(sym)
                if len(global_data["last_scanned"]) > 8:
                    global_data["last_scanned"].pop(0)
                    
                global_data["global_status"] = f"Analyse {sym}..."
                layout["header"].update(get_header_panel())
                layout["main"].split_row(get_balance_panel(), get_market_panel())
                layout["ai_logs"].update(get_ai_logs_panel())
                layout["footer"].update(get_trades_panel())
                live.update(layout)
                
                try:
                    ticker = exchange.fetch_ticker(sym)
                    coin_data[sym]["last_price"] = ticker['last']
                except Exception:
                    pass
                
                action, pct, ai_used = analyze_symbol_consensus(sym)
                
                if action == "LIMITE_API":
                    coin_data[sym]["last_decision"] = "LIMITE GLOBALE (Pause 60s)"
                    global_data["global_status"] = "Quotas atteints sur toutes les IA, pause de 60 secondes..."
                    layout["header"].update(get_header_panel())
                    layout["main"].split_row(get_balance_panel(), get_market_panel())
                    layout["ai_logs"].update(get_ai_logs_panel())
                    live.update(layout)
                    time.sleep(60)
                    continue
                
                if action == "ATTENDRE" and pct == 0.0 and ai_used == "FILTRE_LOCAL":
                    coin_data[sym]["last_decision"] = "FILTRE (RSI STABLE)"
                elif action == "ATTENDRE" and pct == 0.0 and ai_used == "FILTRE_ZOMBIE":
                    coin_data[sym]["last_decision"] = "FILTRE ZOMBIE (Plate)"
                else:
                    coin_data[sym]["last_decision"] = f"[{ai_used}] {action} {pct:.1f}%"
                
                if action in ["ACHETER", "VENDRE"] and pct > 0:
                    global_data["global_status"] = f"Ordre {action} sur {sym} ({pct:.1f}%)..."
                    layout["header"].update(get_header_panel())
                    live.update(layout)
                    
                    execute_trade(sym, action, pct)
                    fetch_all_data()
                    
                if ai_used not in ["-", "FILTRE_LOCAL", "FILTRE_ZOMBIE", "AUCUNE"]:
                    time.sleep(6)

                update_pnl()
                layout["header"].update(get_header_panel())
                layout["main"].split_row(get_balance_panel(), get_market_panel())
                layout["ai_logs"].update(get_ai_logs_panel())
                layout["footer"].update(get_trades_panel())
                live.update(layout)
            
            global_data["global_status"] = "Fin du cycle complet. Repos..."
            layout["header"].update(get_header_panel())
            live.update(layout)
            time.sleep(LOOP_INTERVAL)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        console.print("\n[bold red]Bot arrete.[/bold red]")