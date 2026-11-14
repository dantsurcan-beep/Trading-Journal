import streamlit as st
import pandas as pd
import ccxt
import requests
import json
from datetime import datetime, timedelta, date, timezone
import os

try:
    from zoneinfo import ZoneInfo
    RO_TZ = ZoneInfo("Europe/Bucharest")
except ImportError:
    RO_TZ = None

st.set_page_config(page_title="Universal Trading Journal (Kraken & Hyperliquid)", layout="wide")

# ==========================================
# SISTEM DE PERSISTENȚĂ A SETĂRILOR (DISK + URL)
# ==========================================
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal_settings.json")

DEFAULT_SETTINGS = {
    "exchange_ales": "Kraken",
    "piata_ales": "Futures",
    "auto_refresh": True,
    "refresh_interval": 10,
    "hl_wallet": "",
    "start_date": "2026-09-20",
    "end_date": date.today().strftime("%Y-%m-%d"),
    "directii": ["LONG", "SHORT"],
    "monede_selectate": []
}


def load_user_settings():
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    settings.update(saved)
        except Exception:
            pass

    # Sincronizare cu parametrii URL (util pe Streamlit Cloud la Refresh)
    qp = st.query_params
    if "exc" in qp and qp["exc"] in ["Kraken", "Hyperliquid"]:
        settings["exchange_ales"] = qp["exc"]
    if "mkt" in qp and qp["mkt"] in ["Futures", "Spot"]:
        settings["piata_ales"] = qp["mkt"]
    if "from" in qp:
        settings["start_date"] = qp["from"]
    if "to" in qp:
        settings["end_date"] = qp["to"]
    if "hl_w" in qp and qp["hl_w"]:
        settings["hl_wallet"] = qp["hl_w"]

    return settings


def save_user_settings(new_updates):
    current = load_user_settings()
    current.update(new_updates)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    # Actualizăm și URL-ul pentru persistență în browser / cloud
    try:
        st.query_params["exc"] = current.get("exchange_ales", "Kraken")
        st.query_params["mkt"] = current.get("piata_ales", "Futures")
        st.query_params["from"] = current.get("start_date", "2026-09-20")
        st.query_params["to"] = current.get("end_date", date.today().strftime("%Y-%m-%d"))
        if current.get("hl_wallet"):
            st.query_params["hl_w"] = current["hl_wallet"]
    except Exception:
        pass


user_cfg = load_user_settings()

st.markdown("### 📊 Jurnal Universal de Trading (Kraken & Hyperliquid)")

# ==========================================
# SIDEBAR: CONEXIUNE KRAKEN & HYPERLIQUID
# ==========================================
with st.sidebar:
    st.header("🔑 Conexiune Platformă")

    exc_options = ["Kraken", "Hyperliquid"]
    exc_idx = exc_options.index(user_cfg["exchange_ales"]) if user_cfg["exchange_ales"] in exc_options else 0
    exchange_ales = st.selectbox("🏢 Alege Exchange-ul", exc_options, index=exc_idx)

    mkt_options = ["Futures", "Spot"]
    mkt_idx = mkt_options.index(user_cfg["piata_ales"]) if user_cfg["piata_ales"] in mkt_options else 0
    piata_ales = st.selectbox("📈 Alege Piața", mkt_options, index=mkt_idx)

    st.markdown("---")
    st.subheader("⚙️ Setări Monitorizare Live")
    auto_refresh = st.checkbox("Activează Auto-Refresh (Timp Real)", value=bool(user_cfg.get("auto_refresh", True)))
    refresh_interval = st.slider(
        "Interval reîmprospătare (secunde)",
        min_value=5,
        max_value=60,
        value=int(user_cfg.get("refresh_interval", 10))
    )

    st.markdown("---")

    api_key_input = ""
    api_secret_input = ""
    hl_wallet_input = ""

    if exchange_ales == "Kraken":
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

        api_key_input = st.text_input(f"Kraken {piata_ales} API Key", value=default_key, type="password")
        api_secret_input = st.text_input(f"Kraken {piata_ales} API Secret", value=default_secret, type="password")
    else:
        default_hl_wallet = user_cfg.get("hl_wallet", "")
        try:
            if not default_hl_wallet:
                default_hl_wallet = st.secrets.get("HYPERLIQUID_WALLET", "")
        except Exception:
            pass

        hl_wallet_input = st.text_input(
            "Adresa Portofel Hyperliquid (0x...)",
            value=default_hl_wallet,
            placeholder="0x..."
        ).strip()
        st.caption("💡 Pe Hyperliquid este suficientă adresa publică a portofelului (0x...) pentru a prelua pozițiile live și tot istoricul.")

    # Salvăm automat dacă s-a schimbat vreo setare în sidebar
    if (
        exchange_ales != user_cfg.get("exchange_ales") or
        piata_ales != user_cfg.get("piata_ales") or
        auto_refresh != user_cfg.get("auto_refresh") or
        refresh_interval != user_cfg.get("refresh_interval") or
        (exchange_ales == "Hyperliquid" and hl_wallet_input != user_cfg.get("hl_wallet"))
    ):
        save_user_settings({
            "exchange_ales": exchange_ales,
            "piata_ales": piata_ales,
            "auto_refresh": auto_refresh,
            "refresh_interval": refresh_interval,
            "hl_wallet": hl_wallet_input if exchange_ales == "Hyperliquid" else user_cfg.get("hl_wallet", "")
        })


# ==========================================
# FUNCȚII UTILITARE & CONEXIUNI
# ==========================================
@st.cache_resource(show_spinner=False)
def get_kraken_connection(piata, api_key, api_secret):
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


def hl_post_info(payload):
    """Interogare rapidă către API-ul oficial Hyperliquid."""
    resp = requests.post(
        "https://api.hyperliquid.xyz/info",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()


exchange = None
connected_ok = False

if exchange_ales == "Kraken":
    if api_key_input and api_secret_input:
        try:
            exchange = get_kraken_connection(piata_ales, api_key_input, api_secret_input)
            connected_ok = True
            st.sidebar.success(f"Conectat la Kraken {piata_ales} cu succes! ✅")
        except Exception as e:
            st.sidebar.error(f"Eroare de conexiune Kraken: {e}")
else:
    if hl_wallet_input and hl_wallet_input.startswith("0x") and len(hl_wallet_input) >= 40:
        connected_ok = True
        st.sidebar.success(f"Conectat la Hyperliquid ({piata_ales})! ✅")
    elif hl_wallet_input:
        st.sidebar.error("Adresa Hyperliquid trebuie să înceapă cu '0x' și să aibă 42 de caractere.")


def safe_float(val, default=0.0):
    try:
        if val is None or val == "":
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


# ==========================================
# POZIȚII ACTIVE LIVE (KRAKEN + HYPERLIQUID)
# ==========================================
def fetch_active_positions(platforma, exc, piata, hl_wallet=""):
    now_dt = datetime.now(RO_TZ) if RO_TZ else datetime.now()
    now_str = now_dt.strftime("%d-%m-%Y %H:%M:%S")

    if platforma == "Hyperliquid":
        try:
            if piata == "Futures":
                state = hl_post_info({"type": "clearinghouseState", "user": hl_wallet})
                all_mids = {}
                try:
                    all_mids = hl_post_info({"type": "allMids"}) or {}
                except Exception:
                    pass

                open_orders = []
                try:
                    open_orders = hl_post_info({"type": "frontendOpenOrders", "user": hl_wallet}) or []
                except Exception:
                    pass

                asset_positions = state.get("assetPositions", []) if isinstance(state, dict) else []
                data = []

                for ap in asset_positions:
                    pos = ap.get("position", {}) if isinstance(ap, dict) else {}
                    szi = safe_float(pos.get("szi", 0))
                    if abs(szi) <= 1e-9:
                        continue

                    coin = str(pos.get("coin", "N/A")).upper()
                    cantitate = abs(szi)
                    directie = "LONG" if szi > 0 else "SHORT"
                    pret_intrare = safe_float(pos.get("entryPx", 0))
                    pret_mark = safe_float(all_mids.get(pos.get("coin"), 0))
                    if pret_mark <= 0 and cantitate > 0:
                        pret_mark = safe_float(pos.get("positionValue", 0)) / cantitate

                    valoare_usd = pret_intrare * cantitate
                    pnl = safe_float(pos.get("unrealizedPnl", 0))

                    sl_val = "-"
                    tp_val = "-"
                    limit_val = "-"
                    trailing_val = "-"

                    for o in open_orders:
                        if str(o.get("coin", "")).upper() == coin:
                            o_type = str(o.get("orderType", "")).lower()
                            tpsl = str(o.get("tpsl", "")).lower()
                            is_trig = bool(o.get("isTrigger", False))
                            trig_px = safe_float(o.get("triggerPx", 0))
                            lim_px = safe_float(o.get("limitPx", 0))

                            if tpsl == "sl" or "stop" in o_type:
                                sl_val = trig_px if trig_px > 0 else lim_px
                            elif tpsl == "tp" or "take" in o_type or "profit" in o_type:
                                tp_val = trig_px if trig_px > 0 else lim_px
                            elif not is_trig and lim_px > 0:
                                limit_val = lim_px

                    data.append({
                        "Ultima Actualizare": now_str,
                        "Simbol": coin,
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
                spot_state = hl_post_info({"type": "spotClearinghouseState", "user": hl_wallet})
                balances = spot_state.get("balances", []) if isinstance(spot_state, dict) else []
                data = []
                for b in balances:
                    coin = str(b.get("coin", ""))
                    total_amt = safe_float(b.get("total", 0))
                    if total_amt > 0:
                        data.append({
                            "Ultima Actualizare": now_str,
                            "Monedă": coin,
                            "Cantitate Disponibilă": total_amt
                        })
                return pd.DataFrame(data)
        except Exception as e:
            st.warning(f"Nu s-au putut prelua pozițiile active de pe Hyperliquid: {e}")
            return pd.DataFrame()

    # Ramura Kraken
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
    if df.empty or "Direcție" not in df.columns:
        return df

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


# ==========================================
# ISTORIC TRANZACȚII (KRAKEN + HYPERLIQUID)
# ==========================================
@st.cache_data(ttl=120, show_spinner="Se descarcă istoricul complet al tranzacțiilor (începând din 20 septembrie)...")
def fetch_closed_trades_history(platforma, _exc, piata, hl_wallet=""):
    start_date_dt = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    since_timestamp = int(start_date_dt.timestamp() * 1000)

    # ------------------------------------------
    # RAMURA 1: HYPERLIQUID HISTORY
    # ------------------------------------------
    if platforma == "Hyperliquid":
        try:
            spot_map = {}
            try:
                spot_meta = hl_post_info({"type": "spotMeta"})
                if isinstance(spot_meta, dict):
                    tokens = {t["index"]: t["name"] for t in spot_meta.get("tokens", []) if "index" in t and "name" in t}
                    for u in spot_meta.get("universe", []):
                        u_name = u.get("name", "")
                        u_tokens = u.get("tokens", [])
                        if u_name and u_tokens:
                            base_name = tokens.get(u_tokens[0], u_name)
                            spot_map[u_name] = base_name
            except Exception:
                pass

            all_fills = []
            curr_start = since_timestamp - (2 * 86400 * 1000)
            for _ in range(10):
                batch = hl_post_info({
                    "type": "userFillsByTime",
                    "user": hl_wallet,
                    "startTime": curr_start,
                    "aggregateByTime": True
                })
                if not isinstance(batch, list) or not batch:
                    break
                all_fills.extend(batch)
                if len(batch) < 2000:
                    break
                max_t = max(int(f.get("time", 0)) for f in batch)
                if max_t <= curr_start:
                    break
                curr_start = max_t + 1

            if not all_fills:
                return pd.DataFrame()

            raw_rows = []
            unique_fills = {}
            for f in all_fills:
                tid = str(f.get("tid") or f.get("hash") or f"{f.get('time')}_{f.get('oid')}")
                unique_fills[tid] = f

            for f in unique_fills.values():
                coin_raw = str(f.get("coin", "N/A"))
                is_spot_fill = coin_raw.startswith("@") or "/" in coin_raw or str(f.get("dir", "")) in ["Buy", "Sell"]

                if piata == "Futures" and is_spot_fill:
                    continue
                if piata == "Spot" and not is_spot_fill:
                    continue

                simbol_curat = spot_map.get(coin_raw, coin_raw).replace("/USDC", "").upper()
                ts_ms = int(f.get("time", 0))
                if ts_ms < since_timestamp:
                    continue

                sort_ts = ts_ms / 1000.0
                data_ora_minut, _ = parse_timestamp(ts_ms)

                side_raw = str(f.get("side", "")).upper()
                directie = "LONG" if side_raw == "B" else "SHORT"

                crossed = bool(f.get("crossed", True))
                if not crossed:
                    exec_detaliat = "BUY LIMIT" if directie == "LONG" else "SELL LIMIT"
                else:
                    exec_detaliat = "MANUAL"

                pret = safe_float(f.get("px", 0))
                cantitate = safe_float(f.get("sz", 0))
                valoare_fill = pret * cantitate
                comision = abs(safe_float(f.get("fee", 0)))
                pnl_val = safe_float(f.get("closedPnl", 0))
                order_id = str(f.get("oid") or f"{data_ora_minut}_{simbol_curat}_{directie}")

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
                pnl_total = round(safe_float(grup["PnL"].sum()), 2)
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
                df_final = df_final.sort_values(by="sort_timestamp", ascending=False).drop(columns=["sort_timestamp"]).reset_index(drop=True)
            return df_final

        except Exception as e:
            st.warning(f"A apărut o problemă la preluarea istoricului Hyperliquid: {e}")
            return pd.DataFrame()

    # ------------------------------------------
    # RAMURA 2: KRAKEN HISTORY
    # ------------------------------------------
    raw_rows = []
    try:
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
                    batch = _exc.fetch_my