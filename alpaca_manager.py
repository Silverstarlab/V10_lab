"""
alpaca_manager.py
====================
V10 Options - 포지션 관리 및 청산 (EMA 모멘텀 전략 맞춤형)
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from colorama import init, Fore

init(autoreset=True)

# 🔑 알파카 API 설정
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY",    "YOUR_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "YOUR_SECRET_KEY")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"

HEADERS = {
    "APCA-API-KEY-ID":     ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "Content-Type":        "application/json",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "alpaca_journal.csv")

# ⚙️ 청산 조건 (에러 수정 완료)
HOLDING_DAYS      = 5      # 최대 5일 보유
STOPLOSS_PCT      = -0.15  # -15% 손절
TAKEPROFIT_PCT    = 0.30   # +30% 익절
TRAILING_STOP_PCT = 0.10   # 고점 대비 -10% 트레일링 스탑
CHECK_INTERVAL    = 30     
COOLDOWN_MINUTES  = 60     

_high_water_marks = {}

def load_journal():
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    return pd.read_csv(LOG_FILE)

def save_journal(df):
    df.to_csv(LOG_FILE, index=False)

def get_option_price(symbol):
    url = f"{ALPACA_BASE_URL}/v2/options/quotes?symbols={symbol}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        quotes = res.json().get('quotes', {})
        if symbol in quotes:
            ask = float(quotes[symbol].get('ap', 0))
            bid = float(quotes[symbol].get('bp', 0))
            if ask > 0 and bid > 0: return (ask + bid) / 2.0
            return bid if bid > 0 else ask
    return None

def close_option_position(symbol, qty):
    payload = {"symbol": symbol, "qty": str(qty), "side": "sell", "type": "market", "time_in_force": "day"}
    res = requests.post(f"{ALPACA_BASE_URL}/v2/orders", json=payload, headers=HEADERS)
    return res.status_code == 200

def manage_positions():
    df = load_journal()
    if df.empty or "Status" not in df.columns: return
    
    open_idx = df[df["Status"] == "Open"].index
    if len(open_idx) == 0: return

    updated = 0
    now = datetime.now()

    for i in open_idx:
        ticker      = df.at[i, "Ticker"]
        opt_sym     = df.at[i, "Option_Symbol"]
        entry_price = float(df.at[i, "Entry_Option_Price"])
        contracts   = int(df.at[i, "Contracts"])
        entry_time  = datetime.strptime(df.at[i, "Time"], "%Y-%m-%d %H:%M:%S")

        curr_opt = get_option_price(opt_sym)
        if not curr_opt or curr_opt <= 0: continue

        pnl_pct = (curr_opt - entry_price) / entry_price
        pnl_dollar = (curr_opt - entry_price) * contracts * 100
        days_held = (now - entry_time).days

        hwm = _high_water_marks.get(opt_sym, entry_price)
        if curr_opt > hwm:
            hwm = curr_opt
            _high_water_marks[opt_sym] = hwm
        
        ts_price = hwm * (1 - TRAILING_STOP_PCT)
        close_reason = ""

        if hwm > entry_price and curr_opt <= ts_price:
            close_reason = "Trailing Stop (-10% from High)"
        elif pnl_pct >= TAKEPROFIT_PCT:
            close_reason = f"Take Profit (+{TAKEPROFIT_PCT*100:.0f}%)"
        elif pnl_pct <= STOPLOSS_PCT:
            close_reason = f"Stop Loss ({STOPLOSS_PCT*100:.0f}%)"
        elif days_held >= HOLDING_DAYS:
            close_reason = f"Time Exit ({HOLDING_DAYS} Days)"

        if close_reason:
            if close_option_position(opt_sym, contracts):
                df.at[i, "Status"]             = close_reason
                df.at[i, "Exit_Option_Price"]  = float(curr_opt)
                df.at[i, "Exit_Date"]          = now.strftime("%Y-%m-%d %H:%M:%S")
                df.at[i, "Return_Pct"]         = round(pnl_pct, 4)
                df.at[i, "PnL_Dollar"]         = round(pnl_dollar, 2)
                df.at[i, "Reason"]             = close_reason
                df.at[i, "Cooldown_Until"]     = (now + timedelta(minutes=COOLDOWN_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

                updated += 1
                print(Fore.YELLOW + f"  ⚠️ [{ticker}] 청산: {close_reason} | 수익률: {pnl_pct*100:+.1f}%")
                if opt_sym in _high_water_marks: del _high_water_marks[opt_sym]

    if updated > 0:
        save_journal(df)
        print(Fore.CYAN + f"✅ {updated}개 포지션 청산 완료.\n")

if __name__ == "__main__":
    print(Fore.CYAN + "========================================")
    print(Fore.CYAN + " 🦅 V10 Manager Started")
    print(Fore.CYAN + "========================================")
    while True:
        try: manage_positions()
        except Exception as e: print(Fore.RED + f"[매니저 에러] {e}")
        time.sleep(CHECK_INTERVAL)