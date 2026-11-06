import streamlit as st
import pandas as pd
import ccxt
from datetime import datetime, timedelta, date
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
            'timeout': 10000
        })
    else:
        exc = ccxt.kraken({
            'apiKey': api_key.strip(),
            'secret': api_secret.strip(),
            'enableRateLimit': True,
            'timeout': 10000
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


def parse_timestamp(raw_ts):
    if not raw_ts:
        return 'N/A', 'N/A'
    try:
        if isinstance(raw_ts, str):
            if 'T' in raw_ts or '-' in raw_ts:
                dt = datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
            else:
                raw_ts = float(raw_ts)
                
        if isinstance(raw_ts, (int, float)):
            timestamp = float(raw_ts)
            if timestamp > 1e12:
                timestamp = timestamp / 1000.0
            dt = datetime.fromtimestamp(timestamp, tz=datetime.now().astimezone().tzinfo)
            
        if RO_TZ:
            dt_ro = dt.astimezone(RO_TZ)
        else:
            is_summer = 3 <= dt.month <= 10
            offset = 3 if is_summer else 2
            dt_ro = dt.astimezone(datetime.now().astimezone().tzinfo) + timedelta(hours=offset - dt.utcoffset().total_seconds()/3600 if dt.utcoffset() else 0)

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
            elif num < 0: return 'color: #dc3545; font-weight: bold; font-size: 1.1em;'
            else: return 'color: #6c757d;'
        except Exception:
            return ''

    def highlight_simbol(val): return 'color: #00e676; font-weight: bold;'
    def highlight_date(val): return 'color: #4da3ff;'
    def highlight_gold(val): return 'color: #ffc107;'
    def highlight_cyan(val): return 'color: #00d2ff; font-weight: bold;'
    def highlight_purple(val): return 'color: #b19cd9;'
    def highlight_teal(val): return 'color: #20c997;'
    def highlight_orange(val): return 'color: #ffa500; font-weight: bold;'

    styled = df.style.map(highlight_tip, subset=['Direcție'])
    if "PnL" in df.columns:
        styled = styled.map(highlight_pnl, subset=['PnL'])
    if "Ultima Actualizare" in df.columns:
        styled = styled.map(highlight_date, subset=['Ultima Actualizare'])
    if "Simbol" in df.columns:
        styled = styled.map(highlight_simbol, subset=['Simbol'])
    if "Preț Intrare" in df.columns:
        styled = styled.map(highlight_gold, subset=['Preț Intrare'])
    if "Preț Mark (Live)" in df.columns:
        styled = styled.map(highlight_cyan, subset=['Preț Mark (Live)'])
    if "Stop Loss" in df.columns:
        styled = styled.map(highlight_gold, subset=['Stop Loss'])
    if "Take Profit" in df.columns:
        styled = styled.map(highlight_gold, subset=['Take Profit'])
    if "Limit" in df.columns:
        styled = styled.map(highlight_gold, subset=['Limit'])
    if "Cantitate" in df.columns:
        styled = styled.map(highlight_purple, subset=['Cantitate'])
    if "Valoare" in df.columns:
        styled = styled.map(highlight_teal, subset=['Valoare'])
    if "Trailing" in df.columns:
        styled = styled.map(highlight_orange, subset=['Trailing'])

    def format_pnl(val):
        try:
            num = safe_float(val)
            if num == 0: return "$0.00"
            return f"${num:+,.2f}"
        except Exception:
            return "$0.00"

    def format_price(val):
        try:
            num = safe_float(val)
            if num <= 0: return "-"
            return f"${num:,.4f}"  # Aici am modificat la 4 zecimale
        except Exception:
            return "-"

    formats = {
        "Preț Intrare": "${:,.4f}", # Modificat la 4 zecimale
        "Preț Mark (Live)": format_price,
        "Valoare": "${:,.2f}",
        "Stop Loss": format_price,
        "Take Profit": format_price,
        "Limit": format_price,
        "PnL": format_pnl
    }

    return styled.format(formats)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_closed_trades_history(_exc, piata):
    raw_rows = []
    try:
        order_map = {}
        try:
            if hasattr(_exc, 'fetch_closed_orders'):
                closed_orders = _exc.fetch_closed_orders(limit=500)
                for o in closed_orders:
                    o_id = str(o.get('id', ''))
                    if o_id:
                        o_type = str(o.get('type', '')).lower()
                        o_info_type = str(o.get('info', {}).get('orderType', '')).lower()
                        order_map[o_id] = f"{o_type} {o_info_type}"
        except Exception:
            pass

        trades_raw = []
        fetched_standard = False
        if hasattr(_exc, 'fetch_my_trades'):
            try:
                all_t = _exc.fetch_my_trades(limit=1000)
                if all_t:
                    trades_raw.extend(all_t)
                fetched_standard = True
            except Exception:
                pass

        if piata == "Futures" and not fetched_standard:
            try:
                res = _exc.private_get_fills()
                if isinstance(res, dict) and 'fills' in res:
                    for f in res['fills']:
                        trades_raw.append({
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
                pass

        unique_trades = {}
        for t in trades_raw:
            info = t.get('info', {}) or {}
            trade_id = str(t.get('id') or info.get('fill_id') or info.get('fillId') or id(t))
            unique_trades[trade_id] = t
            
        trades_curate = list(unique_trades.values())

        for t in trades_curate:
            if not t or not isinstance(t, dict):
                continue
            
            info = t.get('info', {}) or {}
            raw_ts = t.get('timestamp') or info.get('fillTime') or info.get('time') or info.get('launchTime')
            data_ora_minut, _ = parse_timestamp(raw_ts)
            
            simbol_raw = str(t.get('symbol') or info.get('symbol') or 'N/A')
            simbol_curat = simbol_raw.replace('PF_', '').replace('PI_', '').replace(':USD', '').replace('/USD', '').replace('_USD', '').replace('XBT', 'BTC').replace('USD', '').upper()
            
            raw_side = str(t.get('side') or info.get('side') or 'N/A').lower()
            directie = "LONG" if raw_side == "buy" else ("SHORT" if raw_side == "sell" else raw_side.upper())
            
            order_id = str(t.get('order') or info.get('order_id') or info.get('orderId') or f"{data_ora_minut}_{simbol_curat}_{directie}")
            
            tip_ordin_din_map = order_map.get(order_id, "").lower()
            order_type_raw = str(info.get('type') or info.get('orderType') or t.get('type') or '').lower()
            order_reason = str(info.get('reason') or info.get('reduceOnly') or '').lower()
            
            tot_text = f"{order_type_raw} {order_reason} {tip_ordin_din_map}"
            
            if 'trailing' in tot_text:
                exec_detaliat = "TRAILING STOP"
            elif 'stop' in tot_text or 'stp' in tot_text:
                exec_detaliat = "STOP LOSS"
            elif 'take' in tot_text or 'profit' in tot_text or 'target' in tot_text:
                exec_detaliat = "TAKE PROFIT"
            elif 'limit' in tot_text or 'lmt' in tot_text or 'post' in tot_text:
                if raw_side == "sell":
                    exec_detaliat = "SELL LIMIT"
                elif raw_side == "buy":
                    exec_detaliat = "BUY LIMIT"
                else:
                    exec_detaliat = "LIMIT"
            else:
                exec_detaliat = "MANUAL"
                
            # Aici am restaurat logica completă pentru PnL
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
            
            fee_dict = t.get('fee', {}) or {}
            comision = safe_float(fee_dict.get('cost') or info.get('feePaid') or info.get('fee') or 0)
            
            try:
                sort_ts = float(raw_ts) if raw_ts else 0.0
                if sort_ts > 1e12:
                    sort_ts = sort_ts / 1000.0
            except Exception:
                sort_ts = 0.0

            if cantitate > 0:
                raw_rows.append({
                    "grup_cheie": order_id,
                    "sort_timestamp": sort_ts,
                    "Data & Ora": data_ora_minut,
                    "Simbol": simbol_curat,
                    "Tip": directie,
                    "pret_parțial": pret * cantitate,
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
                "PnL": pnl_total
            })
            
        df_final = pd.DataFrame(aggregated_data)
        
        if not df_final.empty:
            df_final['PnL'] = pd.to_numeric(df_final['PnL'], errors='coerce').fillna(0.0)
            df_final = df_final.sort_values(by="sort_timestamp", ascending=False).drop(columns=["sort_timestamp"])
            
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
            pnl = safe_float(row['PnL'])
            if pnl != 0.0: return ['background-color: rgba(77, 163, 255, 0.12);'] * len(row)
        except Exception:
            pass
        return [''] * len(row)

    def highlight_tip(val):
        if val == "LONG": return 'color: #28a745; font-weight: bold;'
        elif val == "SHORT": return 'color: #dc3545; font-weight: bold;'
        return ''

    def highlight_pnl(val):
        try:
            num = safe_float(val)
            if num > 0: return 'color: #28a745; font-weight: bold; font-size: 1.1em;'
            elif num < 0: return 'color: #fd7e14; font-weight: bold; font-size: 1.1em;'
            else: return 'color: #6c757d;'
        except Exception:
            return ''

    def highlight_simbol(val): return 'color: #00e676; font-weight: bold;'
    def highlight_date(val): return 'color: #4da3ff;'
    def highlight_gold(val): return 'color: #ffc107;'
    def highlight_purple(val): return 'color: #b19cd9;'
    def highlight_teal(val): return 'color: #20c997;'
    def highlight_orange(val): return 'color: #ffa500; font-weight: bold;'
    def highlight_pink(val): return 'color: #ff8c94;'

    styled = df_viz.style.apply(highlight_closing_rows, axis=1)
    
    styled = styled.map(highlight_tip, subset=['Tip'])
    if "PnL" in df_viz.columns:
        styled = styled.map(highlight_pnl, subset=['PnL'])
    if "Data & Ora" in df_viz.columns:
        styled = styled.map(highlight_date, subset=['Data & Ora'])
    if "Simbol" in df_viz.columns:
        styled = styled.map(highlight_simbol, subset=['Simbol'])
    if "Preț Execuție" in df_viz.columns:
        styled = styled.map(highlight_gold, subset=['Preț Execuție'])
    if "Cantitate" in df_viz.columns:
        styled = styled.map(highlight_purple, subset=['Cantitate'])
    if "Valoare" in df_viz.columns:
        styled = styled.map(highlight_teal, subset=['Valoare'])
    if "Execuție" in df_viz.columns:
        styled = styled.map(highlight_orange, subset=['Execuție'])
    if "Comision" in df_viz.columns:
        styled = styled.map(highlight_pink, subset=['Comision'])
        
    def format_pnl(val):
        try:
            num = safe_float(val)
            if num == 0: return "$0.00"
            return f"${num:+,.2f}"
        except Exception:
            return "$0.00"
            
    return styled.format({
        "Preț Execuție": "${:,.4f}",  # Modificat la 4 zecimale pentru execuție precisă
        "Valoare": "${:,.2f}",
        "PnL": format_pnl
    })


if exchange:
    tab1, tab2 = st.tabs(["📌 Poziții Active Live", "📜 Istoricul Universal (Preluat Automat)"])
    
    with tab1:
        st.subheader("Monitorizare în timp real")
        
        run_every_val = f"{refresh_interval}s" if auto_refresh else None
        
        # Am adăugat un placeholder în afara funcției de fragment pentru a reduce flickering-ul
        live_placeholder = st.empty()
        
        @st.fragment(run_every=run_every_val)
        def afiseaza_pozitii_live():
            df_active = fetch_active_positions(exchange, piata_ales)
            with live_placeholder.container():
                if not df_active.empty:
                    st.dataframe(
                        color_active_table(df_active),
                        use_container_width=True,
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
            
            with st.expander("📥 Opțiuni Export Personalizat (Google Sheets)", expanded=False):
                col_exp1, col_exp2, col_exp3 = st.columns(3)
                
                with col_exp1:
                    filtru_perioada = st.selectbox("Perioada Export", ["Toate datele", "Ultimele 3 zile", "Interval personalizat"])
                    
                df_export_filtered = df_istoric.copy()
                
                if filtru_perioada == "Ultimele 3 zile":
                    data_limita = datetime.now() - timedelta(days=3)
                    df_export_filtered['temp_dt'] = pd.to_datetime(df_export_filtered['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce')
                    df_export_filtered = df_export_filtered[df_export_filtered['temp_dt'] >= data_limita]
                    df_export_filtered = df_export_filtered.drop(columns=['temp_dt'])
                    
                elif filtru_perioada == "Interval personalizat":
                    with col_exp2:
                        start_date = st.date_input("De la data", value=date.today() - timedelta(days=7))
                    with col_exp3:
                        end_date = st.date_input("Până la data", value=date.today())
                        
                    df_export_filtered['temp_dt'] = pd.to_datetime(df_export_filtered['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce').dt.date
                    df_export_filtered = df_export_filtered[(df_export_filtered['temp_dt'] >= start_date) & (df_export_filtered['temp_dt'] <= end_date)]
                    df_export_filtered = df_export_filtered.drop(columns=['temp_dt'])

                if not df_export_filtered.empty:
                    df_csv = df_export_filtered.copy()
                    
                    sum_valoare = df_csv['Valoare'].sum()
                    sum_pnl = df_csv['PnL'].sum()
                    sum_comision = df_csv['Comision_Val'].sum() if 'Comision_Val' in df_csv.columns else 0.0
                    
                    if 'Comision_Val' in df_csv.columns:
                        df_csv = df_csv.drop(columns=['Comision_Val'])
                        
                    total_row = pd.DataFrame([{
                        "Data & Ora": "TOTAL",
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
                        label="📥 Descarcă CSV optimizat pentru Google Sheets",
                        data=csv_data,
                        file_name=f"istoric_kraken_{piata_ales.lower()}.csv",
                        mime="text/csv",
                    )
                else:
                    st.warning("Nu există date în intervalul selectat pentru export.")

            st.markdown("---")
            
            total_pnl = df_istoric['PnL'].sum()
            if total_pnl >= 0:
                st.success(f"### 📈 Profit Total Cumulat (PnL): +${total_pnl:,.2f}")
            else:
                st.error(f"### 📉 Pierdere Totală Cumulată (PnL): -${abs(total_pnl):,.2f}")

            df_display = df_istoric.copy()
            if 'Comision_Val' in df_display.columns:
                df_display = df_display.drop(columns=['Comision_Val'])
                
            st.dataframe(color_trade_table(df_display), use_container_width=True, height=520, hide_index=True)
            
        else:
            st.info("Nu s-au găsit tranzacții închise în istoric.")
else:
    st.info("👈 Introdu cheile API în bara din stânga pentru a te conecta.")