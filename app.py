import streamlit as st
import pandas as pd
import ccxt
import time
from datetime import datetime, timedelta, date, timezone
import os

try:
    from zoneinfo import ZoneInfo
    RO_TZ = ZoneInfo("Europe/Bucharest")
except ImportError:
    RO_TZ = None

st.set_page_config(page_title="Kraken Universal Trading Journal", layout="wide")

st.markdown("### 📊 Jurnal Universal de Trading (Kraken)")

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
                
                sl_val = "-"
                tp_val = "-"
                limit_val = "-"
                trailing_val = "-"
                
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

    def format_price(val):
        try:
            num = safe_float(val)
            return "-" if num <= 0 else f"${num:,.4f}"
        except Exception:
            return "-"

    return styled.format({
        "Preț Intrare": "${:,.4f}",
        "Preț Mark (Live)": format_price,
        "Valoare": "${:,.2f}",
        "Stop Loss": format_price,
        "Take Profit": format_price,
        "Limit": format_price,
        "PnL": format_pnl
    })


@st.cache_data(ttl=120, show_spinner="Se descarcă istoricul complet de pe Kraken (începând din 20 septembrie)...")
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

                if oldest_ts_ms is None:
                    break
                if oldest_ts_ms < (since_timestamp - 2 * 86400 * 1000):
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
                
            pnl_val = safe_float(
                info.get('realisedPnl') or info.get('realizedPnl') or 
                info.get('realised_pnl') or info.get('realized_pnl') or 
                info.get('pnl') or t.get('pnl') or 0
            )
            
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
                    "Comision": comision,
                    "PnL": pnl_val
                })
                
        if not raw_rows:
            return pd.DataFrame()

        df_raw = pd.DataFrame(raw_rows)
        
        aggregated_data = []
        for cheie, grup in df_raw.groupby("grup_cheie"):
            cantitate_totala = safe_float(grup["Cantitate"].sum())
            valoare_totala = safe_float(grup["pret_parțial"].sum())
            pret_mediu = (valoare_totala / cantitate_totala) if cantitate_totala > 0 else 0.0
            
            comision_total = safe_float(grup["Comision"].sum())
            pnl_total = safe_float(grup["PnL"].sum())
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
                "Comision": comision_str,
                "PnL_API": pnl_total
            })

        aggregated_data.sort(key=lambda x: x["sort_timestamp"])
        open_positions = {}

        for row in aggregated_data:
            sym = row["Simbol"]
            side = row["Tip"]
            qty = row["Cantitate"]
            price = row["Preț Execuție"]
            pos = open_positions.get(sym, {"side": None, "qty": 0.0, "price": 0.0})
            calc_pnl = 0.0

            if pos["qty"] <= 1e-9 or pos["side"] == side:
                new_qty = pos["qty"] + qty
                new_price = ((pos["qty"] * pos["price"]) + (qty * price)) / new_qty if new_qty > 0 else price
                open_positions[sym] = {"side": side, "qty": new_qty, "price": new_price}
            else:
                closed_qty = min(pos["qty"], qty)
                if pos["side"] == "LONG":
                    calc_pnl = (price - pos["price"]) * closed_qty
                elif pos["side"] == "SHORT":
                    calc_pnl = (pos["price"] - price) * closed_qty

                rem_pos = pos["qty"] - closed_qty
                rem_order = qty - closed_qty

                if rem_pos > 1e-9:
                    open_positions[sym] = {"side": pos["side"], "qty": rem_pos, "price": pos["price"]}
                elif rem_order > 1e-9:
                    open_positions[sym] = {"side": side, "qty": rem_order, "price": price}
                else:
                    open_positions[sym] = {"side": None, "qty": 0.0, "price": 0.0}

            row["PnL"] = row["PnL_API"] if abs(row["PnL_API"]) > 1e-9 else round(calc_pnl, 2)
            del row["PnL_API"]

        cutoff_sec = since_timestamp / 1000.0
        aggregated_data = [r for r in aggregated_data if r["sort_timestamp"] >= cutoff_sec]

        df_final = pd.DataFrame(aggregated_data)
        
        if not df_final.empty:
            df_final['PnL'] = pd.to_numeric(df_final['PnL'], errors='coerce').fillna(0.0)
            df_final = df_final.sort_values(by="sort_timestamp", ascending=False).drop(columns=["sort_timestamp"]).reset_index(drop=True)
            
        return df_final
        
    except Exception as e:
        st.warning(f"A apărut o problemă la preluarea datelor: {e}")
        return pd.DataFrame()


def color_trade_table(df):
    if df.empty or 'PnL' not in df.columns:
        return df

    df_viz = df.copy()
    if 'Comision_Val' in df_viz.columns:
        df_viz = df_viz.drop(columns=['Comision_Val'])

    df_viz['PnL'] = pd.to_numeric(df_viz['PnL'], errors='coerce').fillna(0.0)

    def highlight_closing_rows(row):
        try:
            if safe_float(row['PnL']) != 0.0:
                return ['background-color: rgba(77, 163, 255, 0.12);'] * len(row)
        except Exception:
            pass
        return [''] * len(row)

    def highlight_tip(val):
        if val == "LONG": return 'color: #28a745; font-weight: bold;'
        elif val == "SHORT": return 'color: #ff3333; font-weight: bold;'
        return ''

    def highlight_pnl(val):
        try:
            num = safe_float(val)
            if num > 0: return 'color: #28a745; font-weight: bold; font-size: 1.1em;'
            elif num < 0: return 'color: #ff3333; font-weight: bold; font-size: 1.1em;'
            else: return 'color: #6c757d;'
        except Exception:
            return ''

    styled = df_viz.style.apply(highlight_closing_rows, axis=1)
    styled = styled.map(highlight_tip, subset=['Tip'])
    if "PnL" in df_viz.columns: styled = styled.map(highlight_pnl, subset=['PnL'])
    if "Data & Ora" in df_viz.columns: styled = styled.map(lambda _: 'color: #4da3ff;', subset=['Data & Ora'])
    if "Simbol" in df_viz.columns: styled = styled.map(lambda _: 'color: #00e676; font-weight: bold;', subset=['Simbol'])
    if "Preț Execuție" in df_viz.columns: styled = styled.map(lambda _: 'color: #ffc107;', subset=['Preț Execuție'])
    if "Cantitate" in df_viz.columns: styled = styled.map(lambda _: 'color: #b19cd9;', subset=['Cantitate'])
    if "Valoare" in df_viz.columns: styled = styled.map(lambda _: 'color: #20c997;', subset=['Valoare'])
    if "Execuție" in df_viz.columns: styled = styled.map(lambda _: 'color: #ffa500; font-weight: bold;', subset=['Execuție'])
    if "Comision" in df_viz.columns: styled = styled.map(lambda _: 'color: #ff8c94;', subset=['Comision'])
        
    def format_pnl(val):
        try:
            num = safe_float(val)
            return "$0.00" if num == 0 else f"${num:+,.2f}"
        except Exception:
            return "$0.00"
            
    return styled.format({
        "Preț Execuție": "${:,.4f}",
        "Valoare": "${:,.2f}",
        "PnL": format_pnl
    })


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
        col_btn, _ = st.columns([1, 4])
        with col_btn:
            if st.button("🔄 Actualizează Istoricul"):
                fetch_closed_trades_history.clear()
                
        df_istoric = fetch_closed_trades_history(exchange, piata_ales)
        if not df_istoric.empty:
            df_istoric['temp_dt'] = pd.to_datetime(df_istoric['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce').dt.date
            min_date_avail = df_istoric['temp_dt'].dropna().min() or date(2026, 9, 20)
            max_date_avail = df_istoric['temp_dt'].dropna().max() or date.today()

            col_d1, col_d2, col_sym, col_dir = st.columns([1.2, 1.2, 2.5, 1.5])

            with col_d1:
                sel_start_date = st.date_input("🗓️ De la (ZZ/LL/AAAA)", value=min_date_avail, min_value=date(2026, 9, 1), max_value=max_date_avail, format="DD/MM/YYYY")
            with col_d2:
                sel_end_date = st.date_input("🗓️ Până la (ZZ/LL/AAAA)", value=max_date_avail, min_value=date(2026, 9, 1), max_value=date.today(), format="DD/MM/YYYY")
            with col_sym:
                lista_simboluri = sorted(df_istoric['Simbol'].dropna().unique().tolist())
                sel_simboluri = st.multiselect("🪙 Monede", options=lista_simboluri, default=lista_simboluri)
            with col_dir:
                sel_directii = st.multiselect("↕️ Direcție", options=["LONG", "SHORT"], default=["LONG", "SHORT"])

            df_filtrat = df_istoric[
                (df_istoric['temp_dt'] >= sel_start_date) &
                (df_istoric['temp_dt'] <= sel_end_date) &
                (df_istoric['Simbol'].isin(sel_simboluri)) &
                (df_istoric['Tip'].isin(sel_directii))
            ].copy().drop(columns=['temp_dt'])

            total_pnl = df_filtrat['PnL'].sum() if not df_filtrat.empty else 0.0
            total_comision = df_filtrat['Comision_Val'].sum() if ('Comision_Val' in df_filtrat.columns and not df_filtrat.empty) else 0.0
            
            trades_inchise = df_filtrat[df_filtrat['PnL'] != 0.0] if not df_filtrat.empty else pd.DataFrame()
            nr_inchise = len(trades_inchise)
            win_rate = (len(trades_inchise[trades_inchise['PnL'] > 0]) / nr_inchise * 100.0) if nr_inchise > 0 else 0.0
            best_trade = trades_inchise['PnL'].max() if nr_inchise > 0 else 0.0
            worst_trade = trades_inchise['PnL'].min() if nr_inchise > 0 else 0.0

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

                st.markdown(f"""
                <table style="width: 100%; text-align: center; border-collapse: collapse; font-size: 1rem; margin-top: 5px;">
                    <tr>
                        <th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Tranzacții (Închise/Total)</th>
                        <th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Win Rate</th>
                        <th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Comision Perioadă</th>
                        <th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Cel mai bun Trade</th>
                        <th style="padding: 8px; border-bottom: 1px solid #444; color: #aaa;">Cel mai slab Trade</th>
                    </tr>
                    <tr>
                        <td style="padding: 10px; font-weight: bold;">{color_val(f'{nr_inchise} / {len(df_filtrat)}', is_currency=False, neutral=True)}</td>
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
                    if not trades_inchise.empty:
                        df_chart = trades_inchise.iloc[::-1].copy()
                        # REZOLVARE EROARE GRAFIC: Conversie string în Datetime strict pentru axa de timp
                        df_chart['Timp_Fix'] = pd.to_datetime(df_chart['Data & Ora'], format='%d-%m-%Y %H:%M')
                        df_chart['PnL Cumulat ($)'] = df_chart['PnL'].cumsum()
                        st.line_chart(df_chart, x='Timp_Fix', y='PnL Cumulat ($)', color="#00e676")
                    else:
                        st.info("Nu există tranzacții închise în intervalul selectat.")

            with col_exp_csv:
                with st.expander("📥 Opțiuni Export CSV (Google Sheets)", expanded=False):
                    if not df_filtrat.empty:
                        df_csv = df_filtrat.copy()
                        sum_valoare = df_csv['Valoare'].sum()
                        sum_pnl = df_csv['PnL'].sum()
                        sum_comision = df_csv['Comision_Val'].sum() if 'Comision_Val' in df_csv.columns else 0.0
                        if 'Comision_Val' in df_csv.columns:
                            df_csv = df_csv.drop(columns=['Comision_Val'])
                        total_row = pd.DataFrame([{
                            "Data & Ora": "TOTAL PERIOADĂ",
                            "Simbol": "",
                            "Tip": "",
                            "Preț Execuție": "",
                            "Cantitate": "",
                            "Valoare": sum_valoare,
                            "Execuție": "",
                            "Comision": sum_comision,
                            "PnL": sum_pnl
                        }])
                        df_csv_final = pd.concat([df_csv, total_row], ignore_index=True)
                        csv_data = df_csv_final.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label=f"📥 Descarcă CSV ({sel_start_date.strftime('%d.%m.%Y')} - {sel_end_date.strftime('%d.%m.%Y')})",
                            data=csv_data,
                            file_name=f"istoric_kraken_{sel_start_date}_{sel_end_date}.csv",
                            mime="text/csv",
                        )
                    else:
                        st.warning("Nu există date în intervalul selectat.")

            st.markdown("---")
            
            df_display = df_filtrat.copy()
            if 'Comision_Val' in df_display.columns:
                df_display = df_display.drop(columns=['Comision_Val'])
                
            st.dataframe(color_trade_table(df_display), width="stretch", height=540, hide_index=True)
            
        else:
            st.info("Nu s-au găsit tranzacții închise în istoric.")
else:
    st.info("👈 Introdu cheile API în bara din stânga pentru a te conecta.")