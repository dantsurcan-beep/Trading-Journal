import streamlit as st
import pandas as pd
import ccxt
import time
import json
from datetime import datetime, timedelta, date, timezone
import os

try:
    from zoneinfo import ZoneInfo
    RO_TZ = ZoneInfo("Europe/Bucharest")
except ImportError:
    RO_TZ = None

st.set_page_config(page_title="Kraken Universal Trading Journal", layout="wide")

st.markdown("### 📊 Jurnal Universal de Trading (Kraken)")

KEYS_CACHE_FILE = os.path.expanduser("~/.kraken_journal_keys.json")


def load_cached_keys():
    try:
        if os.path.exists(KEYS_CACHE_FILE):
            with open(KEYS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_cached_keys(piata, key_val, secret_val):
    try:
        data = load_cached_keys()
        data[piata] = {"key": key_val.strip(), "secret": secret_val.strip()}
        with open(KEYS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


with st.sidebar:
    st.header("🔑 Conexiune Kraken")
    piata_ales = st.selectbox("Alege Piața", ["Futures", "Spot"])
    
    default_key = ""
    default_secret = ""
    
    try:
        if piata_ales == "Futures":
            default_key = st.secrets.get("KRAKEN_FUTURES_KEY", "")
            default_secret = st.secrets.get("KRAKEN_FUTURES_SECRET", "")
        else:
            default_key = st.secrets.get("KRAKEN_SPOT_KEY", "")
            default_secret = st.secrets.get("KRAKEN_SPOT_SECRET", "")
    except Exception:
        pass

    if not default_key or not default_secret:
        cached = load_cached_keys().get(piata_ales, {})
        default_key = default_key or cached.get("key", "")
        default_secret = default_secret or cached.get("secret", "")
        
    st.markdown("---")
    st.subheader("⚙️ Setări Monitorizare Live")
    auto_refresh = st.checkbox("Activează Auto-Refresh (Timp Real)", value=True)
    refresh_interval = st.slider("Interval reîmprospătare (secunde)", min_value=5, max_value=60, value=10)
    
    st.markdown("---")
    api_key_input = st.text_input(f"Kraken {piata_ales} API Key", value=default_key, type="password")
    api_secret_input = st.text_input(f"Kraken {piata_ales} API Secret", value=default_secret, type="password")


@st.cache_resource(show_spinner=False)
def get_exchange_connection(piata, api_key, api_secret):
    if piata == "Futures":
        exc = ccxt.krakenfutures({
            'apiKey': api_key.strip(),
            'secret': api_secret.strip(),
            'enableRateLimit': True,
            'timeout': 15000
        })
    else:
        exc = ccxt.kraken({
            'apiKey': api_key.strip(),
            'secret': api_secret.strip(),
            'enableRateLimit': True,
            'timeout': 15000
        })
    exc.load_markets()
    return exc


exchange = None
if api_key_input and api_secret_input:
    try:
        exchange = get_exchange_connection(piata_ales, api_key_input, api_secret_input)
        save_cached_keys(piata_ales, api_key_input, api_secret_input)
        st.sidebar.success(f"Conectat la Kraken {piata_ales} cu succes! ✅")
    except Exception as e:
        st.sidebar.error(f"Eroare de conexiune: {e}")


def safe_float(val, default=0.0):
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def format_smart_price(val):
    try:
        num = safe_float(val)
        if num <= 0:
            return "-"
        if num < 0.001:
            return f"${num:,.8f}"
        if num < 1.0:
            return f"${num:,.6f}"
        if num < 100.0:
            return f"${num:,.4f}"
        return f"${num:,.2f}"
    except Exception:
        return "-"


def get_ts_ms(raw_ts):
    if not raw_ts:
        return 0
    try:
        if isinstance(raw_ts, (int, float)):
            val = float(raw_ts)
            return int(val * 1000) if val < 1e12 else int(val)
        if isinstance(raw_ts, str):
            if 'T' in raw_ts or '-' in raw_ts:
                dt = datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
                return int(dt.timestamp() * 1000)
            val = float(raw_ts)
            return int(val * 1000) if val < 1e12 else int(val)
    except Exception:
        return 0
    return 0


def to_iso_utc(ts_ms):
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def parse_timestamp(raw_ts):
    ts_ms = get_ts_ms(raw_ts)
    if ts_ms <= 0:
        return 'N/A', 'N/A'
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        if RO_TZ:
            dt_ro = dt.astimezone(RO_TZ)
        else:
            is_summer = 3 <= dt.month <= 10
            offset = 3 if is_summer else 2
            dt_ro = dt + timedelta(hours=offset)
        return dt_ro.strftime('%d-%m-%Y %H:%M'), dt_ro.strftime('%d-%m-%Y %H')
    except Exception:
        return 'N/A', 'N/A'


def fetch_active_positions(exc, piata):
    try:
        if piata == "Futures":
            positions = exc.fetch_positions()
            active_pos = [p for p in (positions or []) if p and isinstance(p, dict) and safe_float(p.get('contracts', 0)) > 0]
            
            open_orders = []
            try:
                open_orders = exc.fetch_open_orders()
            except Exception:
                pass
                
            tickers = {}
            try:
                tickers = exc.fetch_tickers()
            except Exception:
                pass

            data = []
            now_dt = datetime.now(RO_TZ) if RO_TZ else datetime.now()
            now_str = now_dt.strftime("%d-%m-%Y %H:%M:%S")

            for p in active_pos:
                simbol_raw = p.get('symbol', '')
                p_info = p.get('info', {}) or {}
                raw_instrument = str(p_info.get('symbol') or simbol_raw)
                simbol_curat = simbol_raw.replace('PF_', '').replace('PI_', '').replace(':USD', '').replace('/USD', '').replace('_USD', '').replace('XBT', 'BTC').replace('USD', '').upper()
                
                pret_intrare = safe_float(p.get('entryPrice') or p_info.get('price', 0))
                cantitate = safe_float(p.get('contracts') or p_info.get('size', 0))
                valoare_usd = pret_intrare * cantitate
                directie = str(p.get('side') or p_info.get('side', 'N/A')).upper()
                if directie == "BUY":
                    directie = "LONG"
                elif directie == "SELL":
                    directie = "SHORT"
                
                t_obj = tickers.get(simbol_raw) or tickers.get(raw_instrument)
                if not t_obj and tickers:
                    for t_name, t_data in tickers.items():
                        if simbol_curat in t_name.upper():
                            t_obj = t_data
                            break
                            
                pret_mark = 0.0
                if t_obj:
                    t_info = t_obj.get('info', {}) or {}
                    pret_mark = safe_float(
                        t_info.get('markPrice') or 
                        t_obj.get('markPrice') or 
                        t_obj.get('last') or 
                        t_info.get('last', 0)
                    )
                if pret_mark <= 0:
                    pret_mark = safe_float(p.get('markPrice', 0))
                            
                if pret_mark > 0 and pret_intrare > 0:
                    if directie == "LONG":
                        pnl = (pret_mark - pret_intrare) * cantitate
                    elif directie == "SHORT":
                        pnl = (pret_intrare - pret_mark) * cantitate
                    else:
                        pnl = safe_float(p.get('unrealizedPnl', 0))
                else:
                    pnl = safe_float(p.get('unrealizedPnl', 0))
                
                sl_val, tp_val, limit_val, trailing_val = "-", "-", "-", "-"
                
                for o in open_orders:
                    if o.get('symbol') == simbol_raw or simbol_curat in str(o.get('symbol')):
                        o_type = str(o.get('type', '')).lower()
                        o_price = safe_float(o.get('price', 0))
                        o_info = o.get('info', {}) or {}
                        o_trigger = safe_float(o_info.get('stopPrice') or o_info.get('triggerPrice') or o.get('triggerPrice', 0))
                        
                        if 'stop' in o_type or (o_trigger > 0 and 'take' not in o_type):
                            sl_val = o_trigger if o_trigger > 0 else o_price
                        elif 'take' in o_type or 'profit' in o_type:
                            tp_val = o_price if o_price > 0 else o_trigger
                        elif 'limit' in o_type:
                            limit_val = o_price if o_price > 0 else "-"
                        elif 'trailing' in o_type:
                            trailing_val = "Activ"

                data.append({
                    "Ultima Actualizare": now_str,
                    "Simbol": simbol_curat,
                    "Direcție": directie,
                    "Preț Intrare": pret_intrare,
                    "Preț Mark (Live)": pret_mark,
                    "Cantitate": cantitate,
                    "Valoare": valoare_usd,
                    "Stop Loss": sl_val,
                    "Take Profit": tp_val,
                    "Limit": limit_val,
                    "Trailing": trailing_val,
                    "PnL": pnl
                })
            return pd.DataFrame(data)
        else:
            balance = exc.fetch_balance()
            free_bal = balance.get('free', {}) if balance else {}
            data = []
            now_dt = datetime.now(RO_TZ) if RO_TZ else datetime.now()
            now_str = now_dt.strftime("%d-%m-%Y %H:%M:%S")
            for asset, amount in free_bal.items():
                if amount and safe_float(amount) > 0 and asset not in ['ZUSD', 'ZEUR', 'USDT', 'USDC']:
                    data.append({
                        "Ultima Actualizare": now_str,
                        "Monedă": asset,
                        "Cantitate Disponibilă": amount
                    })
            return pd.DataFrame(data)
    except Exception as e:
        st.warning(f"Nu s-au putut prelua pozițiile active: {e}")
        return pd.DataFrame()


def color_active_table(df):
    if df.empty:
        return df

    def highlight_tip(val):
        if val == "LONG": return 'color: #28a745; font-weight: bold;'
        elif val == "SHORT": return 'color: #dc3545; font-weight: bold;'
        return ''

    def highlight_pnl(val):
        try:
            num = safe_float(val)
            if num > 0: return 'color: #28a745; font-weight: bold; font-size: 1.1em;'
            elif num < 0: return 'color: #ff3333; font-weight: bold; font-size: 1.1em;'
            else: return 'color: #6c757d;'
        except Exception:
            return ''

    styled = df.style.map(highlight_tip, subset=['Direcție'])
    if "PnL" in df.columns: styled = styled.map(highlight_pnl, subset=['PnL'])
    if "Ultima Actualizare" in df.columns: styled = styled.map(lambda _: 'color: #4da3ff;', subset=['Ultima Actualizare'])
    if "Simbol" in df.columns: styled = styled.map(lambda _: 'color: #00e676; font-weight: bold;', subset=['Simbol'])
    if "Preț Intrare" in df.columns: styled = styled.map(lambda _: 'color: #ffc107;', subset=['Preț Intrare'])
    if "Preț Mark (Live)" in df.columns: styled = styled.map(lambda _: 'color: #00d2ff; font-weight: bold;', subset=['Preț Mark (Live)'])
    if "Stop Loss" in df.columns: styled = styled.map(lambda _: 'color: #ffc107;', subset=['Stop Loss'])
    if "Take Profit" in df.columns: styled = styled.map(lambda _: 'color: #ffc107;', subset=['Take Profit'])
    if "Limit" in df.columns: styled = styled.map(lambda _: 'color: #ffc107;', subset=['Limit'])
    if "Cantitate" in df.columns: styled = styled.map(lambda _: 'color: #b19cd9;', subset=['Cantitate'])
    if "Valoare" in df.columns: styled = styled.map(lambda _: 'color: #20c997;', subset=['Valoare'])
    if "Trailing" in df.columns: styled = styled.map(lambda _: 'color: #ffa500; font-weight: bold;', subset=['Trailing'])

    def format_pnl(val):
        try:
            num = safe_float(val)
            return "$0.00" if num == 0 else f"${num:+,.2f}"
        except Exception:
            return "$0.00"

    return styled.format({
        "Preț Intrare": format_smart_price,
        "Preț Mark (Live)": format_smart_price,
        "Valoare": "${:,.2f}",
        "Stop Loss": format_smart_price,
        "Take Profit": format_smart_price,
        "Limit": format_smart_price,
        "PnL": format_pnl
    })


def match_symbol_cycles(sym_orders):
    n = len(sym_orders)
    cycles = []
    orphans = []

    def find_cycle_end(start_idx):
        open_side = sym_orders[start_idx]["Tip"]
        open_qty = 0.0
        close_qty = 0.0
        for k in range(start_idx, min(n, start_idx + 15)):
            q = sym_orders[k]["Cantitate"]
            if sym_orders[k]["Tip"] == open_side:
                if close_qty > 0:
                    break
                open_qty += q
            else:
                close_qty += q
                tol = max(1e-9, open_qty * 1e-4)
                if abs(open_qty - close_qty) <= tol:
                    return k
                elif close_qty > open_qty + tol:
                    return -1
        return -1

    i = 0
    while i < n:
        end_k = find_cycle_end(i)

        if end_k != -1 and end_k > i + 1:
            inner_end = find_cycle_end(i + 1)
            if inner_end != -1 and inner_end <= end_k:
                end_k = -1

        if end_k != -1:
            cycle_rows = [dict(r) for r in sym_orders[i:end_k + 1]]
            open_side = cycle_rows[0]["Tip"]
            total_open_qty = sum(r["Cantitate"] for r in cycle_rows if r["Tip"] == open_side)
            total_open_val = sum(r["Cantitate"] * r["Preț Execuție"] for r in cycle_rows if r["Tip"] == open_side)
            avg_entry_price = (total_open_val / total_open_qty) if total_open_qty > 0 else 0.0

            for r in cycle_rows:
                if r["Tip"] == open_side:
                    r["Rol"] = "DESCHIDERE"
                    r["PnL"] = 0.0
                else:
                    r["Rol"] = "ÎNCHIDERE"
                    if open_side == "LONG":
                        r["PnL"] = round((r["Preț Execuție"] - avg_entry_price) * r["Cantitate"], 2)
                    else:
                        r["PnL"] = round((avg_entry_price - r["Preț Execuție"]) * r["Cantitate"], 2)

            cycles.append({
                "status": "CLOSED",
                "close_ts": cycle_rows[-1]["sort_timestamp"],
                "rows": cycle_rows
            })
            i = end_k + 1
        else:
            if i == n - 1:
                r_active = dict(sym_orders[i])
                r_active["Rol"] = "ACTIVĂ"
                r_active["PnL"] = 0.0
                cycles.append({
                    "status": "OPEN",
                    "close_ts": r_active["sort_timestamp"],
                    "rows": [r_active]
                })
            else:
                r_orph = dict(sym_orders[i])
                r_orph["Rol"] = "ORFAN"
                r_orph["PnL"] = 0.0
                orphans.append(r_orph)
            i += 1

    return cycles, orphans


@st.cache_data(ttl=120, show_spinner="Se descarcă și se împerechează tranzacțiile de pe Kraken...")
def fetch_closed_trades_history(_exc, piata):
    raw_rows = []
    try:
        start_date_dt = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
        since_timestamp = int(start_date_dt.timestamp() * 1000)

        order_map = {}
        try:
            if hasattr(_exc, 'fetch_closed_orders'):
                closed_orders = _exc.fetch_closed_orders(limit=500)
                for o in (closed_orders or []):
                    o_id = str(o.get('id', ''))
                    if o_id:
                        o_type = str(o.get('type', '')).lower()
                        o_info_type = str((o.get('info') or {}).get('orderType', '')).lower()
                        order_map[o_id] = f"{o_type} {o_info_type}"
        except Exception:
            pass

        trades_raw = []

        if piata == "Futures":
            last_fill_time_param = None
            for _ in range(60):
                params = {'lastFillTime': last_fill_time_param} if last_fill_time_param else {}
                batch = []
                
                try:
                    res = _exc.private_get_fills(params)
                    if isinstance(res, dict) and 'fills' in res and res['fills']:
                        for f in res['fills']:
                            batch.append({
                                'id': f.get('fill_id') or f.get('fillId'),
                                'order': f.get('order_id') or f.get('orderId'),
                                'timestamp': f.get('fillTime') or f.get('time'),
                                'symbol': f.get('symbol'),
                                'side': f.get('side'),
                                'price': f.get('price'),
                                'amount': f.get('size'),
                                'fee': {'cost': f.get('feePaid')},
                                'info': f
                            })
                except Exception:
                    try:
                        batch = _exc.fetch_my_trades(limit=100, params=params)
                    except Exception:
                        break

                if not batch:
                    break

                trades_raw.extend(batch)

                oldest_ts_ms = None
                oldest_iso_str = None
                for item in batch:
                    info_item = item.get('info', {}) or {}
                    raw_t = info_item.get('fillTime') or item.get('timestamp') or info_item.get('time')
                    ts_ms = get_ts_ms(raw_t)
                    if ts_ms > 0 and (oldest_ts_ms is None or ts_ms < oldest_ts_ms):
                        oldest_ts_ms = ts_ms
                        oldest_iso_str = info_item.get('fillTime') if isinstance(info_item.get('fillTime'), str) else to_iso_utc(ts_ms)

                if oldest_ts_ms is None or oldest_ts_ms < (since_timestamp - 2 * 86400 * 1000):
                    break

                next_param = oldest_iso_str or to_iso_utc(oldest_ts_ms - 1)
                if next_param == last_fill_time_param:
                    next_param = to_iso_utc(oldest_ts_ms - 1)
                last_fill_time_param = next_param
        else:
            curr_since = since_timestamp
            for _ in range(20):
                try:
                    batch = _exc.fetch_my_trades(since=curr_since, limit=500)
                    if not batch:
                        break
                    trades_raw.extend(batch)
                    last_ts = get_ts_ms(batch[-1].get('timestamp'))
                    if last_ts > curr_since:
                        curr_since = last_ts + 1
                    else:
                        break
                except Exception:
                    break

        unique_trades = {}
        for t in trades_raw:
            if not t or not isinstance(t, dict):
                continue
            info = t.get('info', {}) or {}
            trade_id = str(t.get('id') or info.get('fill_id') or info.get('fillId') or id(t))
            unique_trades[trade_id] = t
            
        trades_curate = list(unique_trades.values())

        for t in trades_curate:
            info = t.get('info', {}) or {}
            raw_ts = t.get('timestamp') or info.get('fillTime') or info.get('time') or info.get('launchTime')
            sort_ts_ms = get_ts_ms(raw_ts)
            if sort_ts_ms <= 0:
                continue
            sort_ts = sort_ts_ms / 1000.0
            data_ora_minut, _ = parse_timestamp(sort_ts_ms)
            
            simbol_raw = str(t.get('symbol') or info.get('symbol') or 'N/A')
            simbol_curat = simbol_raw.replace('PF_', '').replace('PI_', '').replace(':USD', '').replace('/USD', '').replace('_USD', '').replace('XBT', 'BTC').replace('USD', '').upper()
            
            raw_side = str(t.get('side') or info.get('side') or 'N/A').lower()
            directie = "LONG" if raw_side == "buy" else ("SHORT" if raw_side == "sell" else raw_side.upper())
            
            order_id = str(t.get('order') or info.get('order_id') or info.get('orderId') or f"{data_ora_minut}_{simbol_curat}_{directie}")
            
            tip_ordin_din_map = order_map.get(order_id, "").lower()
            order_type_raw = str(info.get('type') or info.get('orderType') or t.get('type') or '').lower()
            order_reason = str(info.get('reason') or info.get('reduceOnly') or '').lower()
            fill_type = str(info.get('fillType') or t.get('takerOrMaker') or '').lower()
            
            tot_text = f"{order_type_raw} {order_reason} {tip_ordin_din_map}"
            
            if 'trailing' in tot_text:
                exec_detaliat = "TRAILING STOP"
            elif 'stop' in tot_text or 'stp' in tot_text:
                exec_detaliat = "STOP LOSS"
            elif 'take' in tot_text or 'profit' in tot_text or 'target' in tot_text:
                exec_detaliat = "TAKE PROFIT"
            elif 'limit' in tot_text or 'lmt' in tot_text or 'post' in tot_text:
                exec_detaliat = "SELL LIMIT" if raw_side == "sell" else ("BUY LIMIT" if raw_side == "buy" else "LIMIT")
            elif 'market' in tot_text or 'mkt' in tot_text or 'ioc' in tot_text:
                exec_detaliat = "MANUAL"
            else:
                if 'maker' in fill_type:
                    exec_detaliat = "SELL LIMIT" if raw_side == "sell" else "BUY LIMIT"
                else:
                    exec_detaliat = "MANUAL"
                
            pret = safe_float(
                t.get('price') or info.get('price') or 
                info.get('fillPrice') or info.get('executionPrice') or 0
            )
            cantitate = safe_float(t.get('amount') or info.get('size') or info.get('filled') or 0)
            valoare_fill = pret * cantitate
            
            fee_dict = t.get('fee', {}) or {}
            comision_api = safe_float(fee_dict.get('cost') or info.get('feePaid') or info.get('fee') or 0)
            if comision_api > 0:
                comision = comision_api
            else:
                fee_rate = 0.0002 if 'maker' in fill_type else 0.0005
                comision = valoare_fill * fee_rate

            if cantitate > 0:
                raw_rows.append({
                    "grup_cheie": order_id,
                    "sort_timestamp": sort_ts,
                    "Data & Ora": data_ora_minut,
                    "Simbol": simbol_curat,
                    "Tip": directie,
                    "pret_parțial": valoare_fill,
                    "Cantitate": cantitate,
                    "Execuție": exec_detaliat,
                    "Comision": comision
                })
                
        if not raw_rows:
            return pd.DataFrame(), pd.DataFrame()

        df_raw = pd.DataFrame(raw_rows)
        
        aggregated_data = []
        for cheie, grup in df_raw.groupby("grup_cheie"):
            cantitate_totala = safe_float(grup["Cantitate"].sum())
            valoare_totala = safe_float(grup["pret_parțial"].sum())
            pret_mediu = (valoare_totala / cantitate_totala) if cantitate_totala > 0 else 0.0
            
            comision_total = safe_float(grup["Comision"].sum())
            pct_comision = (comision_total / valoare_totala * 100) if valoare_totala > 0 else 0.0
            comision_str = f"${comision_total:,.4f} ({pct_comision:.2f}%)"
            
            grup_sortat = grup.sort_values(by="sort_timestamp", ascending=False)
            first_row = grup_sortat.iloc[0]
            
            aggregated_data.append({
                "sort_timestamp": first_row["sort_timestamp"],
                "Data & Ora": first_row["Data & Ora"],
                "Simbol": first_row["Simbol"],
                "Tip": first_row["Tip"],
                "Preț Execuție": pret_mediu,
                "Cantitate": cantitate_totala,
                "Valoare": valoare_totala,
                "Execuție": first_row["Execuție"],
                "Comision_Val": comision_total,
                "Comision": comision_str
            })

        aggregated_data.sort(key=lambda x: x["sort_timestamp"])

        by_symbol = {}
        for r in aggregated_data:
            by_symbol.setdefault(r["Simbol"], []).append(r)

        all_cycles = []
        all_orphans = []
        for sym, sym_orders in by_symbol.items():
            c_list, o_list = match_symbol_cycles(sym_orders)
            all_cycles.extend(c_list)
            all_orphans.extend(o_list)

        cutoff_sec = since_timestamp / 1000.0
        valid_cycles = [c for c in all_cycles if c["close_ts"] >= cutoff_sec]
        valid_cycles.sort(key=lambda c: c["close_ts"])

        final_rows = []
        closed_counter = 0
        for c in valid_cycles:
            if c["status"] == "CLOSED":
                closed_counter += 1
                trade_label = f"#{closed_counter}"
                cycle_pnl = sum(r["PnL"] for r in c["rows"])
            else:
                trade_label = "ACTIV"
                cycle_pnl = 0.0

            rows_desc = sorted(c["rows"], key=lambda x: x["sort_timestamp"], reverse=True)
            for r in rows_desc:
                r["Trade_ID"] = trade_label
                r["Status_Ciclu"] = c["status"]
                r["Ciclu_PnL"] = cycle_pnl
                r["Ciclu_Close_TS"] = c["close_ts"]
                final_rows.append(r)

        df_final = pd.DataFrame(final_rows)
        if not df_final.empty:
            df_final['PnL'] = pd.to_numeric(df_final['PnL'], errors='coerce').fillna(0.0)
            df_final = df_final.sort_values(
                by=["Ciclu_Close_TS", "sort_timestamp"],
                ascending=[False, False]
            ).reset_index(drop=True)

        df_orphans = pd.DataFrame(all_orphans)
        return df_final, df_orphans
        
    except Exception as e:
        st.warning(f"A apărut o problemă la preluarea datelor: {e}")
        return pd.DataFrame(), pd.DataFrame()


def render_boxed_trades_html(df):
    if df.empty:
        return "<p style='color: #aaa;'>Nu există tranzacții pentru filtrele selectate.</p>"

    css = """
<style>
.jurnal-scroll-box {
max-height: 640px;
overflow-y: auto;
overflow-x: hidden;
border: 1px solid #2b313e;
border-radius: 8px;
background-color: #0e1117;
padding: 6px;
}
.jurnal-table {
width: 100%;
border-collapse: separate;
border-spacing: 0;
font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
font-size: 0.83rem;
}
.jurnal-table thead th {
position: sticky;
top: 0;
background-color: #1a1f2c;
color: #a0aab8;
padding: 8px 8px;
text-align: left;
border-bottom: 2px solid #3a445e;
z-index: 10;
font-weight: 600;
font-size: 0.82rem;
white-space: nowrap;
}
.jurnal-table td {
padding: 6px 8px;
vertical-align: middle;
}
.row-open {
background-color: #131722;
}
.row-close-win {
background-color: rgba(40, 167, 69, 0.12);
}
.row-close-loss {
background-color: rgba(255, 51, 51, 0.12);
}
.row-active {
background-color: rgba(255, 193, 7, 0.12);
}
</style>
"""

    html_parts = [css, '<div class="jurnal-scroll-box"><table class="jurnal-table">']
    html_parts.append(
        '<thead><tr>'
        '<th style="width: 55px;">Trade</th>'
        '<th style="min-width: 130px;">Etapă & Dată</th>'
        '<th>Simbol</th>'
        '<th>Tip</th>'
        '<th>Preț Execuție</th>'
        '<th>Cantitate</th>'
        '<th>Valoare</th>'
        '<th>Execuție</th>'
        '<th>Comision</th>'
        '<th style="text-align: right; min-width: 75px;">PnL</th>'
        '</tr></thead><tbody>'
    )

    groups = []
    curr_id = None
    curr_group = []
    for _, row in df.iterrows():
        t_id = row["Trade_ID"]
        if t_id != curr_id:
            if curr_group:
                groups.append(curr_group)
            curr_group = [row]
            curr_id = t_id
        else:
            curr_group.append(row)
    if curr_group:
        groups.append(curr_group)

    for g_idx, group_rows in enumerate(groups):
        status = group_rows[0]["Status_Ciclu"]
        c_pnl = safe_float(group_rows[0]["Ciclu_PnL"])
        if status == "OPEN":
            border_color = "#ffc107"
        elif c_pnl > 0:
            border_color = "#28a745"
        elif c_pnl < 0:
            border_color = "#dc3545"
        else:
            border_color = "#4a6fa5"

        num_r = len(group_rows)
        for r_idx, r in enumerate(group_rows):
            rol = r["Rol"]
            pnl_num = safe_float(r["PnL"])

            if rol == "ACTIVĂ":
                row_cls = "row-active"
                etapa_text_style = "color: #fbbf24; font-weight: bold; font-size: 0.81rem;"
                etapa_icon = "⏳ ACTIVĂ"
            elif rol == "ÎNCHIDERE":
                row_cls = "row-close-win" if pnl_num >= 0 else "row-close-loss"
                etapa_text_style = "color: #60a5fa; font-weight: bold; font-size: 0.81rem;"
                etapa_icon = "⏹ ÎNCHIDERE"
            else:
                row_cls = "row-open"
                etapa_text_style = "color: #94a3b8; font-weight: bold; font-size: 0.81rem;"
                etapa_icon = "▶ DESCHIDERE"

            b_top = f"border-top: 2px solid {border_color};" if r_idx == 0 else "border-top: 1px dashed #2d3446;"
            b_bot = f"border-bottom: 2px solid {border_color};" if r_idx == num_r - 1 else ""
            b_left = f"border-left: 3px solid {border_color};"
            b_right = f"border-right: 2px solid {border_color};"

            tip_val = r["Tip"]
            tip_color = "#28a745" if tip_val == "LONG" else "#ff4d4d"

            if pnl_num > 0:
                pnl_str = f"+${pnl_num:,.2f}"
                pnl_style = "color: #00e676; font-weight: bold; font-size: 0.95rem;"
            elif pnl_num < 0:
                pnl_str = f"-${abs(pnl_num):,.2f}"
                pnl_style = "color: #ff4d4d; font-weight: bold; font-size: 0.95rem;"
            else:
                pnl_str = "$0.00"
                pnl_style = "color: #7a8291;"

            pret_str = format_smart_price(r["Preț Execuție"])
            cant_val = safe_float(r["Cantitate"])
            cant_str = f"{cant_val:,.0f}" if cant_val >= 100 else f"{cant_val:,.6f}"
            val_str = f"${safe_float(r['Valoare']):,.2f}"

            etapa_data_cell = (
                f'<div style="{etapa_text_style}">{etapa_icon}</div>'
                f'<div style="border-top: 1px solid rgba(255, 255, 255, 0.12); margin: 3px 0 2px 0;"></div>'
                f'<div style="color: #60a5fa; font-size: 0.75rem; white-space: nowrap;">{r["Data & Ora"]}</div>'
            )

            row_html = (
                f'<tr class="{row_cls}">'
                f'<td style="{b_top} {b_bot} {b_left} color: #e2e8f0; font-weight: bold;">{r["Trade_ID"]}</td>'
                f'<td style="{b_top} {b_bot}">{etapa_data_cell}</td>'
                f'<td style="{b_top} {b_bot} color: #00e676; font-weight: bold;">{r["Simbol"]}</td>'
                f'<td style="{b_top} {b_bot} color: {tip_color}; font-weight: bold;">{tip_val}</td>'
                f'<td style="{b_top} {b_bot} color: #ffc107;">{pret_str}</td>'
                f'<td style="{b_top} {b_bot} color: #b19cd9;">{cant_str}</td>'
                f'<td style="{b_top} {b_bot} color: #20c997;">{val_str}</td>'
                f'<td style="{b_top} {b_bot} color: #ffa500; font-weight: bold;">{r["Execuție"]}</td>'
                f'<td style="{b_top} {b_bot} color: #ff8c94;">{r["Comision"]}</td>'
                f'<td style="{b_top} {b_bot} {b_right} text-align: right; {pnl_style}">{pnl_str}</td>'
                f'</tr>'
            )
            html_parts.append(row_html)

        if g_idx < len(groups) - 1:
            html_parts.append('<tr style="height: 8px; background-color: #0e1117;"><td colspan="10" style="padding: 0; border: none;"></td></tr>')

    html_parts.append("</tbody></table></div>")
    raw_html = "\n".join(html_parts)
    return "\n".join(line.strip() for line in raw_html.splitlines() if line.strip())


if exchange:
    tab1, tab2 = st.tabs(["📌 Poziții Active Live", "📜 Istoricul Universal (Preluat Automat)"])
    
    with tab1:
        st.subheader("Monitorizare în timp real")
        run_every_val = f"{refresh_interval}s" if auto_refresh else None
        live_placeholder = st.empty()
        
        @st.fragment(run_every=run_every_val)
        def afiseaza_pozitii_live():
            df_active = fetch_active_positions(exchange, piata_ales)
            with live_placeholder.container():
                if not df_active.empty:
                    st.dataframe(
                        color_active_table(df_active),
                        width="stretch",
                        height=300,
                        hide_index=True
                    )
                else:
                    st.info("Momentan nu ai poziții active.")
                
        afiseaza_pozitii_live()
            
    with tab2:
        col_btn, _ = st.columns([1.5, 4])
        with col_btn:
            if st.button("🔄 Actualizează Istoricul"):
                fetch_closed_trades_history.clear()
                
        df_istoric, df_orphans = fetch_closed_trades_history(exchange, piata_ales)
        if not df_istoric.empty:
            df_istoric['temp_dt'] = pd.to_datetime(df_istoric['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce').dt.date
            min_date_avail = df_istoric['temp_dt'].dropna().min() or date(2026, 9, 20)
            max_date_avail = df_istoric['temp_dt'].dropna().max() or date.today()

            col_d1, col_d2 = st.columns(2)
            with col_d1:
                sel_start_date = st.date_input("🗓️ De la (ZZ/LL/AAAA)", value=min_date_avail, min_value=date(2026, 9, 1), max_value=max_date_avail, format="DD/MM/YYYY", key="flt_start")
            with col_d2:
                sel_end_date = st.date_input("🗓️ Până la (ZZ/LL/AAAA)", value=max_date_avail, min_value=date(2026, 9, 1), max_value=date.today(), format="DD/MM/YYYY", key="flt_end")

            lista_simboluri = sorted(df_istoric['Simbol'].dropna().unique().tolist())
            sel_simboluri = st.multiselect("🪙 Monede", options=lista_simboluri, default=lista_simboluri, key="flt_sym")

            sel_directii = st.multiselect("↕️ Direcție", options=["LONG", "SHORT"], default=["LONG", "SHORT"], key="flt_dir")

            matching_ids = df_istoric[
                (df_istoric['temp_dt'] >= sel_start_date) &
                (df_istoric['temp_dt'] <= sel_end_date) &
                (df_istoric['Simbol'].isin(sel_simboluri)) &
                (df_istoric['Tip'].isin(sel_directii))
            ]['Trade_ID'].unique()

            df_filtrat = df_istoric[df_istoric['Trade_ID'].isin(matching_ids)].copy().drop(columns=['temp_dt'])

            total_pnl = df_filtrat['PnL'].sum() if not df_filtrat.empty else 0.0
            total_comision = df_filtrat['Comision_Val'].sum() if ('Comision_Val' in df_filtrat.columns and not df_filtrat.empty) else 0.0
            
            df_closed_cycles = df_filtrat[df_filtrat['Status_Ciclu'] == "CLOSED"].groupby("Trade_ID", as_index=False)['PnL'].sum() if not df_filtrat.empty else pd.DataFrame()
            nr_tranzactii_inchise = len(df_closed_cycles)
            nr_active_acum = len(df_filtrat[df_filtrat['Status_Ciclu'] == "OPEN"]['Trade_ID'].unique()) if not df_filtrat.empty else 0

            win_rate = (len(df_closed_cycles[df_closed_cycles['PnL'] > 0]) / nr_tranzactii_inchise * 100.0) if nr_tranzactii_inchise > 0 else 0.0
            best_trade = df_closed_cycles['PnL'].max() if nr_tranzactii_inchise > 0 else 0.0
            worst_trade = df_closed_cycles['PnL'].min() if nr_tranzactii_inchise > 0 else 0.0

            st.markdown("<br>", unsafe_allow_html=True)
            
            col_pnl_box, col_kpi_table = st.columns([1.5, 3])

            with col_pnl_box:
                bg_color = "rgba(40, 167, 69, 0.15)" if total_pnl >= 0 else "rgba(255, 51, 51, 0.15)"
                text_color = "#00e676" if total_pnl >= 0 else "#ff3333"
                sign = "+" if total_pnl >= 0 else ""
                
                st.markdown(f"""
<div style="background-color: {bg_color}; border: 1px solid {text_color}; border-radius: 8px; padding: 15px; text-align: center;">
<h3 style="margin: 0; color: #ffffff; font-size: 1.2rem;">PnL Total Cumulat</h3>
<h2 style="margin: 5px 0 0 0; color: {text_color}; font-size: 2.2rem;">{sign}${total_pnl:,.2f}</h2>
</div>
""", unsafe_allow_html=True)

            with col_kpi_table:
                def color_val(val, is_currency=True, neutral=False):
                    if neutral: return f"<span style='color: #ffc107;'>{val}</span>"
                    if is_currency:
                        if val > 0: return f"<span style='color: #00e676;'>+${val:,.2f}</span>"
                        elif val < 0: return f"<span style='color: #ff3333;'>-${abs(val):,.2f}</span>"
                        else: return "<span style='color: #6c757d;'>$0.00</span>"
                    return val

                text_tranzactii = f"{nr_tranzactii_inchise}" + (f" (+{nr_active_acum} activă)" if nr_active_acum > 0 else "")

                st.markdown(f"""
<table style="width: 100%; text-align: center; border-collapse: collapse; font-size: 1rem; margin-top: 5px;">
<tr>
<th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Tranzacții Complete</th>
<th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Win Rate</th>
<th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Comision Perioadă</th>
<th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Cel mai bun Trade</th>
<th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Cel mai slab Trade</th>
</tr>
<tr>
<td style="padding: 10px; font-weight: bold;">{color_val(text_tranzactii, is_currency=False, neutral=True)}</td>
<td style="padding: 10px; font-weight: bold;">{color_val(f'{win_rate:.1f}%', is_currency=False, neutral=True)}</td>
<td style="padding: 10px; font-weight: bold; color: #ff8c94;">${total_comision:,.2f}</td>
<td style="padding: 10px; font-weight: bold;">{color_val(best_trade)}</td>
<td style="padding: 10px; font-weight: bold;">{color_val(worst_trade)}</td>
</tr>
</table>
""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            col_exp_chart, col_exp_csv = st.columns(2)
            
            with col_exp_chart:
                with st.expander("📈 Grafic Evoluție PnL Cumulat (Equity Curve)", expanded=False):
                    trades_inchise_rows = df_filtrat[df_filtrat['Rol'] == "ÎNCHIDERE"]
                    if not trades_inchise_rows.empty:
                        df_chart = trades_inchise_rows.iloc[::-1].copy()
                        df_chart['Timp_Fix'] = pd.to_datetime(df_chart['Data & Ora'], format='%d-%m-%Y %H:%M')
                        df_chart['PnL Cumulat ($)'] = df_chart['PnL'].cumsum()
                        st.line_chart(df_chart, x='Timp_Fix', y='PnL Cumulat ($)', color="#00e676")
                    else:
                        st.info("Nu există tranzacții închise în intervalul selectat.")

            with col_exp_csv:
                with st.expander("📥 Opțiuni Export CSV (Google Sheets)", expanded=False):
                    if not df_filtrat.empty:
                        cols_export = ["Trade_ID", "Rol", "Data & Ora", "Simbol", "Tip", "Preț Execuție", "Cantitate", "Valoare", "Execuție", "Comision", "PnL"]
                        df_csv = df_filtrat[cols_export].copy()
                        csv_data = df_csv.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label=f"📥 Descarcă CSV ({sel_start_date.strftime('%d.%m.%Y')} - {sel_end_date.strftime('%d.%m.%Y')})",
                            data=csv_data,
                            file_name=f"istoric_kraken_{sel_start_date}_{sel_end_date}.csv",
                            mime="text/csv",
                        )
                    else:
                        st.warning("Nu există date în intervalul selectat.")

            st.markdown("---")
            st.markdown(render_boxed_trades_html(df_filtrat), unsafe_allow_html=True)
            
        else:
            st.info("Nu s-au găsit tranzacții închise în istoric.")
else:
    st.info("👈 Introdu cheile API în bara din stânga pentru a te conecta.")