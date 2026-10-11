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

custom_css = """
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 1rem;
    }
    h3 {
        margin-bottom: 0.5rem !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

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
    api_key_input = st.text_input(f"Kraken {piata_ales} API Key", value=default_key, type="password")
    api_secret_input = st.text_input(f"Kraken {piata_ales} API Secret", value=default_secret, type="password")

exchange = None
if api_key_input and api_secret_input:
    try:
        if piata_ales == "Futures":
            exchange = ccxt.krakenfutures({
                'apiKey': api_key_input.strip(),
                'secret': api_secret_input.strip(),
                'enableRateLimit': True
            })
        else:
            exchange = ccxt.kraken({
                'apiKey': api_key_input.strip(),
                'secret': api_secret_input.strip(),
                'enableRateLimit': True
            })
        
        exchange.load_markets()
        st.sidebar.success(f"Conectat la Kraken {piata_ales} cu succes! ✅")
    except Exception as e:
        st.sidebar.error(f"Eroare de conexiune: {e}")

def safe_float(val, default=0.0):
    try:
        if val is None:
            return default
        return float(val)
    except:
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
    except:
        return 'N/A', 'N/A'

def fetch_active_positions(exc, piata):
    try:
        if piata == "Futures":
            positions = exc.fetch_positions()
            active_pos = [p for p in (positions or []) if p and isinstance(p, dict) and safe_float(p.get('contracts', 0)) > 0]
            
            open_orders = []
            try:
                open_orders = exc.fetch_open_orders()
            except:
                pass

            data = []
            now_dt = datetime.now()
            if RO_TZ:
                now_dt = datetime.now(RO_TZ)
            now_str = now_dt.strftime("%d-%m-%Y %H:%M")

            for p in active_pos:
                simbol_raw = p.get('symbol', '')
                simbol_curat = simbol_raw.replace('PF_', '').replace('PI_', '').replace(':USD', '').replace('/USD', '').replace('_USD', '').replace('XBT', 'BTC').replace('USD', '').upper()
                pret_intrare = safe_float(p.get('entryPrice', 0))
                cantitate = safe_float(p.get('contracts', 0))
                valoare_usd = pret_intrare * cantitate
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
                        
                        if 'stop' in o_type or o_trigger > 0 and 'take' not in o_type:
                            sl_val = o_trigger if o_trigger > 0 else o_price
                        elif 'take' in o_type or ('profit' in o_type):
                            tp_val = o_price if o_price > 0 else o_trigger
                        elif 'limit' in o_type:
                            limit_val = o_price if o_price > 0 else "-"
                        elif 'trailing' in o_type:
                            trailing_val = "Activ"

                data.append({
                    "Data Preluării": now_str,
                    "Simbol": simbol_curat,
                    "Direcție": str(p.get('side', 'N/A')).upper(),
                    "Preț Intrare": pret_intrare,
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
            now_dt = datetime.now()
            if RO_TZ:
                now_dt = datetime.now(RO_TZ)
            now_str = now_dt.strftime("%d-%m-%Y %H:%M")
            for asset, amount in free_bal.items():
                if amount and safe_float(amount) > 0 and asset not in ['ZUSD', 'ZEUR', 'USDT', 'USDC']:
                    data.append({
                        "Data Preluării": now_str,
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
        except: return ''

    styled = df.style.map(highlight_tip, subset=['Direcție'])
    if "PnL" in df.columns:
        styled = styled.map(highlight_pnl, subset=['PnL'])

    formats = {
        "Preț Intrare": "${:,.2f}",
        "Valoare": "${:,.2f}",
        "Stop Loss": lambda x: f"${x:,.2f}" if safe_float(x) > 0 else "-",
        "Take Profit": lambda x: f"${x:,.2f}" if safe_float(x) > 0 else "-",
        "Limit": lambda x: f"${x:,.2f}" if safe_float(x) > 0 else "-",
        "PnL": lambda x: f"${safe_float(x):+,.2f}" if safe_float(x) != 0 else "$0.00"
    }

    return styled.format(formats)

def fetch_closed_trades_history(exc, piata):
    raw_rows = []
    try:
        order_map = {}
        try:
            if hasattr(exc, 'fetch_closed_orders'):
                closed_orders = exc.fetch_closed_orders(limit=1500)
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
        if hasattr(exc, 'fetch_my_trades'):
            try: 
                all_t = exc.fetch_my_trades(limit=2500)
                if all_t: 
                    trades_raw.extend(all_t)
                    fetched_standard = True
            except Exception: pass
            
        if piata == "Futures" and not fetched_standard:
            try:
                res = exc.private_get_fills()
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
            except Exception: pass

        unique_trades = {}
        for t in trades_raw:
            info = t.get('info', {}) or {}
            trade_id = str(t.get('id') or info.get('fill_id') or info.get('fillId') or id(t))
            unique_trades[trade_id] = t
            
        trades_curate = list(unique_trades.values())

        for t in trades_curate:
            if not t or not isinstance(t, dict): continue
                
            info = t.get('info', {}) or {}
            
            raw_ts = t.get('timestamp') or info.get('fillTime') or info.get('time') or info.get('launchTime')
            data_ora_minut, data_ora_grup = parse_timestamp(raw_ts)
                
            simbol_raw = str(t.get('symbol') or info.get('symbol') or 'N/A')
            simbol_curat = simbol_raw.replace('PF_', '').replace('PI_', '').replace(':USD', '').replace('/USD', '').replace('_USD', '').replace('XBT', 'BTC').replace('USD', '').upper()
            
            raw_side = str(t.get('side') or info.get('side') or 'N/A').lower()
            direcție = "LONG" if raw_side == "buy" else ("SHORT" if raw_side == "sell" else raw_side.upper())
            
            order_id = str(t.get('order') or info.get('order_id') or info.get('orderId') or f"{data_ora_minut}_{simbol_curat}_{direcție}")
            
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
            except:
                sort_ts = 0.0

            if cantitate > 0:
                raw_rows.append({
                    "grup_cheie": order_id,
                    "sort_timestamp": sort_ts,
                    "Data & Ora": data_ora_minut,
                    "Simbol": simbol_curat,
                    "Tip": direcție,
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
            
            status_val = "OPEN" if pnl_total == 0.0 else "CLOSED"
            
            aggregated_data.append({
                "sort_timestamp": first_row["sort_timestamp"],
                "Status": status_val,
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
            df_final = df_final.sort_values(by="sort_timestamp", ascending=False)
            
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
    if 'sort_timestamp' in df_viz.columns:
        df_viz = df_viz.drop(columns=['sort_timestamp'])

    df_viz['PnL'] = pd.to_numeric(df_viz['PnL'], errors='coerce').fillna(0.0)

    def highlight_closing_rows(row):
        try:
            status = str(row.get('Status', ''))
            if status == "CLOSED":
                return ['background-color: rgba(77, 163, 255, 0.12);'] * len(row)
            elif status == "OPEN":
                return ['background-color: rgba(255, 165, 0, 0.12);'] * len(row)
        except: pass
        return [''] * len(row)

    def highlight_status(val):
        if val == "OPEN": return 'color: #ffa500; font-weight: bold;'
        elif val == "CLOSED": return 'color: #4da3ff; font-weight: bold;'
        return ''

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
        except: return ''

    def highlight_simbol(val): return 'color: #00e676; font-weight: bold;'
    def highlight_date(val): return 'color: #4da3ff;'
    def highlight_gold(val): return 'color: #ffc107;'
    def highlight_purple(val): return 'color: #b19cd9;'
    def highlight_teal(val): return 'color: #20c997;'
    def highlight_orange(val): return 'color: #ffa500; font-weight: bold;'
    def highlight_pink(val): return 'color: #ff8c94;'

    styled = df_viz.style.apply(highlight_closing_rows, axis=1)
    
    if "Status" in df_viz.columns:
        styled = styled.map(highlight_status, subset=['Status'])
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
        except:
            return "$0.00"
    
    return styled.format({
        "Preț Execuție": "${:,.2f}",
        "Valoare": "${:,.2f}",
        "PnL": format_pnl
    })

if exchange:
    tab1, tab2 = st.tabs(["📌 Poziții Active", "📜 Istoricul Universal"])
    
    with tab1:
        st.subheader("Monitorizare în timp real")
        df_active = fetch_active_positions(exchange, piata_ales)
        if not df_active.empty:
            st.dataframe(color_active_table(df_active), use_container_width=True, height=280, hide_index=True, column_config={
                "PnL": st.column_config.NumberColumn("PnL", width="small")
            })
        else:
            st.info("Momentan nu ai poziții active.")
            
    with tab2:
        df_istoric = fetch_closed_trades_history(exchange, piata_ales)
        if not df_istoric.empty:
            
            # --- CALCULATOR PNL NET PE PERIOADĂ ---
            with st.container():
                st.markdown("#### 🧮 Calculator PnL Net & Comisioane per Interval")
                calc_col1, calc_col2, calc_col3 = st.columns(3)
                
                with calc_col1:
                    calc_start = st.date_input("Data de început", value=date.today() - timedelta(days=7), key="calc_start")
                with calc_col2:
                    calc_end = st.date_input("Data de sfârșit", value=date.today(), key="calc_end")
                
                df_calc = df_istoric.copy()
                df_calc['temp_date'] = pd.to_datetime(df_calc['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce').dt.date
                df_filtered_calc = df_calc[(df_calc['temp_date'] >= calc_start) & (df_calc['temp_date'] <= calc_end)]
                
                sum_pnl_brut = df_filtered_calc['PnL'].sum() if not df_filtered_calc.empty else 0.0
                sum_comisioane = df_filtered_calc['Comision_Val'].sum() if not df_filtered_calc.empty and 'Comision_Val' in df_filtered_calc.columns else 0.0
                pnl_net = sum_pnl_brut - sum_comisioane
                
                with calc_col3:
                    st.markdown(f"**Total Tranzacții în interval:** `{len(df_filtered_calc)}`")
                
                mcol1, mcol2, mcol3 = st.columns(3)
                mcol1.metric("PnL Brut", f"${sum_pnl_brut:+,.2f}")
                mcol2.metric("Total Comisioane", f"${sum_comisioane:,.4f}")
                
                net_color_style = "color: #28a745;" if pnl_net >= 0 else "color: #fd7e14;"
                mcol3.markdown(f"""
                    <div style="background-color: #1e222d; padding: 8px 12px; border-radius: 5px; border: 1px solid #2a2e39;">
                        <span style="font-size: 0.8rem; color: #a6b0cf;">PnL Net (După Comisioane)</span><br>
                        <span style="font-size: 1.25rem; font-weight: bold; {net_color_style}">${pnl_net:+,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)

            st.markdown("---")

            # --- OPȚIUNI EXPORT ---
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
                        start_date = st.date_input("De la", value=date.today() - timedelta(days=7), key="exp_start")
                    with col_exp3:
                        end_date = st.date_input("Până la", value=date.today(), key="exp_end")
                    
                    df_export_filtered['temp_dt'] = pd.to_datetime(df_export_filtered['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce').dt.date
                    df_export_filtered = df_export_filtered[(df_export_filtered['temp_dt'] >= start_date) & (df_export_filtered['temp_dt'] <= end_date)]
                    df_export_filtered = df_export_filtered.drop(columns=['temp_dt'])

                if not df_export_filtered.empty:
                    df_csv = df_export_filtered.copy()
                    if 'sort_timestamp' in df_csv.columns:
                        df_csv = df_csv.drop(columns=['sort_timestamp'])
                    
                    sum_valoare = df_csv['Valoare'].sum()
                    sum_pnl = df_csv['PnL'].sum()
                    sum_comision = df_csv['Comision_Val'].sum() if 'Comision_Val' in df_csv.columns else 0.0
                    
                    if 'Comision_Val' in df_csv.columns:
                        df_csv = df_csv.drop(columns=['Comision_Val'])
                    
                    total_row = pd.DataFrame([{
                        "Status": "",
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
            df_display = df_istoric.copy()
            if 'Comision_Val' in df_display.columns:
                df_display = df_display.drop(columns=['Comision_Val'])
            if 'sort_timestamp' in df_display.columns:
                df_display = df_display.drop(columns=['sort_timestamp'])
                
            st.dataframe(color_trade_table(df_display), use_container_width=True, height=480, hide_index=True)
            
        else:
            st.info("Nu s-au găsit tranzacții închise în istoric.")
else:
    st.info("👈 Introdu cheile API în meniul din stânga.")