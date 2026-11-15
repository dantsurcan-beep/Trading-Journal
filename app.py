import streamlit as st
import pandas as pd
import ccxt
import requests
import json
import os
from datetime import datetime, timedelta, date, timezone

try:
    from zoneinfo import ZoneInfo
    RO_TZ = ZoneInfo("Europe/Bucharest")
except ImportError:
    RO_TZ = None

st.set_page_config(page_title="Universal Trading Journal (Kraken & Hyperliquid)", layout="wide")


def today_ro():
    """Returnează data curentă exactă după fusul orar al României."""
    return datetime.now(RO_TZ).date() if RO_TZ else date.today()


SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal_settings.json")
DEFAULT_SETTINGS = {
    "exchange_ales": "Kraken",
    "piata_ales": "Futures",
    "auto_refresh": True,
    "refresh_interval": 10,
    "hl_wallet": "",
    "start_date": "2026-09-20",
    "end_date": today_ro().strftime("%Y-%m-%d"),
    "last_Opened_day": today_ro().strftime("%Y-%m-%d"),
    "directii": ["LONG", "SHORT"],
    "monede_excluse": []
}


def load_user_settings():
    s = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    s.update(saved)
        except Exception:
            pass
    qp = st.query_params
    if qp.get("exc") in ["Kraken", "Hyperliquid"]:
        s["exchange_ales"] = qp["exc"]
    if qp.get("mkt") in ["Futures", "Spot"]:
        s["piata_ales"] = qp["mkt"]
    if "from" in qp:
        s["start_date"] = qp["from"]
    if "to" in qp:
        s["end_date"] = qp["to"]
    if qp.get("hl_w"):
        s["hl_wallet"] = qp["hl_w"]

    # Dacă am trecut într-o zi nouă, avansăm automat 'end_date' la ziua de azi
    azi_str = today_ro().strftime("%Y-%m-%d")
    if s.get("last_Opened_day") != azi_str or s.get("end_date", "") < azi_str:
        s["end_date"] = azi_str
        s["last_Opened_day"] = azi_str
    return s


def save_user_settings(updates):
    cur = load_user_settings()
    cur.update(updates)
    cur["last_Opened_day"] = today_ro().strftime("%Y-%m-%d")
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    try:
        st.query_params["exc"] = cur.get("exchange_ales", "Kraken")
        st.query_params["mkt"] = cur.get("piata_ales", "Futures")
        st.query_params["from"] = cur.get("start_date", "2026-09-20")
        st.query_params["to"] = cur.get("end_date", today_ro().strftime("%Y-%m-%d"))
        if cur.get("hl_wallet"):
            st.query_params["hl_w"] = cur["hl_wallet"]
    except Exception:
        pass


user_cfg = load_user_settings()
st.markdown("### 📊 Jurnal Universal de Trading (Kraken & Hyperliquid)")

with st.sidebar:
    st.header("🔑 Conexiune Platformă")
    exc_opts = ["Kraken", "Hyperliquid"]
    exc_index = exc_opts.index(user_cfg["exchange_ales"]) if user_cfg["exchange_ales"] in exc_opts else 0
    exchange_ales = st.selectbox("🏢 Alege Exchange-ul", exc_opts, index=exc_index)

    mkt_opts = ["Futures", "Spot"]
    mkt_index = mkt_opts.index(user_cfg["piata_ales"]) if user_cfg["piata_ales"] in mkt_opts else 0
    piata_ales = st.selectbox("📈 Alege Piața", mkt_opts, index=mkt_index)

    st.markdown("---")
    st.subheader("⚙️ Setări Monitorizare Live")
    auto_refresh = st.checkbox("Activează Auto-Refresh (Timp Real)", value=bool(user_cfg.get("auto_refresh", True)))
    refresh_interval = st.slider("Interval reîmprospătare (secunde)", min_value=5, max_value=60, value=int(user_cfg.get("refresh_interval", 10)))
    st.markdown("---")

    api_key_input, api_secret_input, hl_wallet_input = "", "", ""
    if exchange_ales == "Kraken":
        def_k, def_s = "", ""
        try:
            if piata_ales == "Futures":
                def_k = st.secrets.get("KRAKEN_FUTURES_KEY", "")
                def_s = st.secrets.get("KRAKEN_FUTURES_SECRET", "")
            else:
                def_k = st.secrets.get("KRAKEN_SPOT_KEY", "")
                def_s = st.secrets.get("KRAKEN_SPOT_SECRET", "")
        except Exception:
            pass
        api_key_input = st.text_input(f"Kraken {piata_ales} API Key", value=def_k, type="password")
        api_secret_input = st.text_input(f"Kraken {piata_ales} API Secret", value=def_s, type="password")
    else:
        def_hl = ""
        try:
            def_hl = st.secrets.get("HYPERLIQUID_WALLET", "")
        except Exception:
            pass
        if not def_hl:
            def_hl = user_cfg.get("hl_wallet", "")
        hl_wallet_input = st.text_input("Adresa Portofel Hyperliquid (0x...)", value=def_hl, placeholder="0x...").strip()
        st.caption("💡 Preluată automat din secrets.toml (HYPERLIQUID_WALLET) sau salvată local.")

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


@st.cache_resource(show_spinner=False)
def get_kraken_connection(piata, api_key, api_secret):
    cls = ccxt.krakenfutures if piata == "Futures" else ccxt.kraken
    exc = cls({'apiKey': api_key.strip(), 'secret': api_secret.strip(), 'enableRateLimit': True, 'timeout': 15000})
    exc.load_markets()
    return exc


def hl_post_info(payload):
    r = requests.post("https://api.hyperliquid.xyz/info", json=payload, headers={"Content-Type": "application/json"}, timeout=15)
    r.raise_for_status()
    return r.json()


exchange = None
connected_ok = False
if exchange_ales == "Kraken":
    if api_key_input and api_secret_input:
        try:
            exchange = get_kraken_connection(piata_ales, api_key_input, api_secret_input)
            connected_ok = True
            st.sidebar.success(f"Conectat la Kraken {piata_ales}! ✅")
        except Exception as e:
            st.sidebar.error(f"Eroare Kraken: {e}")
else:
    if hl_wallet_input.startswith("0x") and len(hl_wallet_input) >= 40:
        connected_ok = True
        st.sidebar.success(f"Conectat la Hyperliquid ({piata_ales})! ✅")
    elif hl_wallet_input:
        st.sidebar.error("Adresa trebuie să înceapă cu '0x' și să aibă 42 caractere.")


def safe_float(val, default=0.0):
    try:
        return default if val is None or val == "" else float(val)
    except Exception:
        return default


def get_ts_ms(raw_ts):
    if not raw_ts:
        return 0
    try:
        if isinstance(raw_ts, (int, float)):
            v = float(raw_ts)
            return int(v * 1000) if v < 1e12 else int(v)
        if isinstance(raw_ts, str):
            if 'T' in raw_ts or '-' in raw_ts:
                dt = datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
                return int(dt.timestamp() * 1000)
            v = float(raw_ts)
            return int(v * 1000) if v < 1e12 else int(v)
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
            offset = 3 if 3 <= dt.month <= 10 else 2
            dt_ro = dt + timedelta(hours=offset)
        return dt_ro.strftime('%d-%m-%Y %H:%M'), dt_ro.strftime('%d-%m-%Y %H')
    except Exception:
        return 'N/A', 'N/A'


def clean_sym(simbol_raw):
    return str(simbol_raw).replace('PF_', '').replace('PI_', '').replace(':USD', '').replace('/USD', '').replace('_USD', '').replace('XBT', 'BTC').replace('USD', '').upper()


def fetch_active_positions(platforma, exc, piata, hl_wallet=""):
    now_dt = datetime.now(RO_TZ) if RO_TZ else datetime.now()
    now_str = now_dt.strftime("%d-%m-%Y %H:%M:%S")

    if platforma == "Hyperliquid":
        try:
            if piata == "Futures":
                state = hl_post_info({"type": "clearinghouseState", "user": hl_wallet})
                all_mids = hl_post_info({"type": "allMids"}) or {}
                open_orders = hl_post_info({"type": "frontendOpenOrders", "user": hl_wallet}) or []
                data = []
                for ap in (state.get("assetPositions", []) if isinstance(state, dict) else []):
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
                    sl_val, tp_val, limit_val = "-", "-", "-"
                    for o in open_orders:
                        if str(o.get("coin", "")).upper() == coin:
                            o_type = str(o.get("orderType", "")).lower()
                            tpsl = str(o.get("tpsl", "")).lower()
                            trig_px = safe_float(o.get("triggerPx", 0))
                            lim_px = safe_float(o.get("limitPx", 0))
                            if tpsl == "sl" or "stop" in o_type:
                                sl_val = trig_px if trig_px > 0 else lim_px
                            elif tpsl == "tp" or "take" in o_type or "profit" in o_type:
                                tp_val = trig_px if trig_px > 0 else lim_px
                            elif not o.get("isTrigger", False) and lim_px > 0:
                                limit_val = lim_px
                    data.append({
                        "Ultima Actualizare": now_str, "Simbol": coin, "Direcție": directie,
                        "Preț Intrare": pret_intrare, "Preț Mark (Live)": pret_mark,
                        "Cantitate": cantitate, "Valoare": pret_intrare * cantitate,
                        "Stop Loss": sl_val, "Take Profit": tp_val, "Limit": limit_val,
                        "Trailing": "-", "PnL": safe_float(pos.get("unrealizedPnl", 0))
                    })
                return pd.DataFrame(data)
            else:
                spot_state = hl_post_info({"type": "spotClearinghouseState", "user": hl_wallet})
                balances = spot_state.get("balances", []) if isinstance(spot_state, dict) else []
                return pd.DataFrame([
                    {"Ultima Actualizare": now_str, "Monedă": str(b.get("coin", "")), "Cantitate Disponibilă": safe_float(b.get("total", 0))}
                    for b in balances if safe_float(b.get("total", 0)) > 0
                ])
        except Exception as e:
            st.warning(f"Eroare poziții Hyperliquid: {e}")
            return pd.DataFrame()

    try:
        if piata == "Futures":
            positions = exc.fetch_positions()
            active_pos = [p for p in (positions or []) if p and isinstance(p, dict) and safe_float(p.get('contracts', 0)) > 0]
            open_orders, tickers = [], {}
            try:
                open_orders = exc.fetch_open_orders()
            except Exception:
                pass
            try:
                tickers = exc.fetch_tickers()
            except Exception:
                pass
            data = []
            for p in active_pos:
                simbol_raw = p.get('symbol', '')
                p_info = p.get('info', {}) or {}
                raw_inst = str(p_info.get('symbol') or simbol_raw)
                simbol_curat = clean_sym(simbol_raw)
                pret_intrare = safe_float(p.get('entryPrice') or p_info.get('price', 0))
                cantitate = safe_float(p.get('contracts') or p_info.get('size', 0))
                directie = str(p.get('side') or p_info.get('side', 'N/A')).upper()
                directie = "LONG" if directie == "BUY" else ("SHORT" if directie == "SELL" else directie)
                t_obj = tickers.get(simbol_raw) or tickers.get(raw_inst)
                if not t_obj and tickers:
                    for t_name, t_data in tickers.items():
                        if simbol_curat in t_name.upper():
                            t_obj = t_data
                            break
                t_info = (t_obj.get('info', {}) if t_obj else {}) or {}
                pret_mark = safe_float(t_info.get('markPrice') or (t_obj.get('markPrice') if t_obj else 0) or (t_obj.get('last') if t_obj else 0) or p.get('markPrice', 0))
                if pret_mark > 0 and pret_intrare > 0:
                    pnl = (pret_mark - pret_intrare) * cantitate if directie == "LONG" else (pret_intrare - pret_mark) * cantitate
                else:
                    pnl = safe_float(p.get('unrealizedPnl', 0))
                sl_val, tp_val, limit_val, trailing_val = "-", "-", "-", "-"
                for o in open_orders:
                    if o.get('symbol') == simbol_raw or simbol_curat in str(o.get('symbol')):
                        o_type = str(o.get('type', '')).lower()
                        o_price = safe_float(o.get('price', 0))
                        o_info = o.get('info', {}) or {}
                        o_trig = safe_float(o_info.get('stopPrice') or o_info.get('triggerPrice') or o.get('triggerPrice', 0))
                        if 'stop' in o_type or (o_trig > 0 and 'take' not in o_type):
                            sl_val = o_trig if o_trig > 0 else o_price
                        elif 'take' in o_type or 'profit' in o_type:
                            tp_val = o_price if o_price > 0 else o_trig
                        elif 'limit' in o_type:
                            limit_val = o_price if o_price > 0 else "-"
                        elif 'trailing' in o_type:
                            trailing_val = "Activ"
                data.append({
                    "Ultima Actualizare": now_str, "Simbol": simbol_curat, "Direcție": directie,
                    "Preț Intrare": pret_intrare, "Preț Mark (Live)": pret_mark,
                    "Cantitate": cantitate, "Valoare": pret_intrare * cantitate,
                    "Stop Loss": sl_val, "Take Profit": tp_val, "Limit": limit_val,
                    "Trailing": trailing_val, "PnL": pnl
                })
            return pd.DataFrame(data)
        else:
            bal = exc.fetch_balance()
            free_b = bal.get('free', {}) if bal else {}
            return pd.DataFrame([
                {"Ultima Actualizare": now_str, "Monedă": k, "Cantitate Disponibilă": v}
                for k, v in free_b.items() if safe_float(v) > 0 and k not in ['ZUSD', 'ZEUR', 'USDT', 'USDC']
            ])
    except Exception as e:
        st.warning(f"Eroare poziții active: {e}")
        return pd.DataFrame()


def color_active_table(df):
    if df.empty or "Direcție" not in df.columns:
        return df
    styled = df.style.map(lambda v: 'color: #28a745; font-weight: bold;' if v == "LONG" else ('color: #ff3333; font-weight: bold;' if v == "SHORT" else ''), subset=['Direcție'])
    styled = styled.map(lambda v: 'color: #28a745; font-weight: bold; font-size: 1.1em;' if safe_float(v) > 0 else ('color: #ff3333; font-weight: bold; font-size: 1.1em;' if safe_float(v) < 0 else 'color: #6c757d;'), subset=['PnL'])
    styled = styled.map(lambda _: 'color: #4da3ff;', subset=['Ultima Actualizare'])
    styled = styled.map(lambda _: 'color: #00e676; font-weight: bold;', subset=['Simbol'])
    styled = styled.map(lambda _: 'color: #ffc107;', subset=['Preț Intrare', 'Stop Loss', 'Take Profit', 'Limit'])
    styled = styled.map(lambda _: 'color: #00d2ff; font-weight: bold;', subset=['Preț Mark (Live)'])
    styled = styled.map(lambda _: 'color: #b19cd9;', subset=['Cantitate'])
    styled = styled.map(lambda _: 'color: #20c997;', subset=['Valoare'])
    styled = styled.map(lambda _: 'color: #ffa500; font-weight: bold;', subset=['Trailing'])
    fmt_p = lambda v: "-" if safe_float(v) <= 0 else f"${safe_float(v):,.4f}"
    fmt_pnl = lambda v: "$0.00" if safe_float(v) == 0 else f"${safe_float(v):+,.2f}"
    return styled.format({"Preț Intrare": "${:,.4f}", "Preț Mark (Live)": fmt_p, "Valoare": "${:,.2f}", "Stop Loss": fmt_p, "Take Profit": fmt_p, "Limit": fmt_p, "PnL": fmt_pnl})


@st.cache_data(ttl=60, show_spinner="Se descarcă istoricul complet (începând din 20 septembrie)...")
def fetch_closed_trades_history(platforma, _exc, piata, hl_wallet=""):
    since_timestamp = int(datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

    if platforma == "Hyperliquid":
        try:
            spot_map = {}
            try:
                sm = hl_post_info({"type": "spotMeta"})
                if isinstance(sm, dict):
                    tks = {t["index"]: t["name"] for t in sm.get("tokens", []) if "index" in t and "name" in t}
                    for u in sm.get("universe", []):
                        if u.get("name") and u.get("tokens"):
                            spot_map[u["name"]] = tks.get(u["tokens"][0], u["name"])
            except Exception:
                pass
            all_fills = []
            curr_start = since_timestamp - (2 * 86400 * 1000)
            for _ in range(10):
                batch = hl_post_info({"type": "userFillsByTime", "user": hl_wallet, "startTime": curr_start, "aggregateByTime": True})
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
            unique_fills = {str(f.get("tid") or f.get("hash") or f"{f.get('time')}_{f.get('oid')}"): f for f in all_fills}
            raw_rows = []
            for f in unique_fills.values():
                coin_raw = str(f.get("coin", "N/A"))
                is_spot = coin_raw.startswith("@") or "/" in coin_raw or str(f.get("dir", "")) in ["Buy", "Sell"]
                if (piata == "Futures" and is_spot) or (piata == "Spot" and not is_spot):
                    continue
                ts_ms = int(f.get("time", 0))
                if ts_ms < since_timestamp:
                    continue
                simbol_curat = spot_map.get(coin_raw, coin_raw).replace("/USDC", "").upper()
                data_ora_minut, _ = parse_timestamp(ts_ms)
                directie = "LONG" if str(f.get("side", "")).upper() == "B" else "SHORT"
                exec_det = ("BUY LIMIT" if directie == "LONG" else "SELL LIMIT") if not bool(f.get("crossed", True)) else "MANUAL"
                pret, cant = safe_float(f.get("px", 0)), safe_float(f.get("sz", 0))
                if cant > 0:
                    raw_rows.append({
                        "grup_cheie": str(f.get("oid") or f"{data_ora_minut}_{simbol_curat}_{directie}"),
                        "sort_timestamp": ts_ms / 1000.0, "Data & Ora": data_ora_minut, "Simbol": simbol_curat,
                        "Tip": directie, "pret_parțial": pret * cant, "Cantitate": cant, "Execuție": exec_det,
                        "Comision": abs(safe_float(f.get("fee", 0))), "PnL": safe_float(f.get("closedPnl", 0))
                    })
            if not raw_rows:
                return pd.DataFrame()
            df_raw = pd.DataFrame(raw_rows)
            agg = []
            for _, g in df_raw.groupby("grup_cheie"):
                c_tot, v_tot = safe_float(g["Cantitate"].sum()), safe_float(g["pret_parțial"].sum())
                com_tot = safe_float(g["Comision"].sum())
                pct_c = (com_tot / v_tot * 100) if v_tot > 0 else 0.0
                first_r = g.sort_values(by="sort_timestamp", ascending=False).iloc[0]
                agg.append({
                    "sort_timestamp": first_r["sort_timestamp"], "Data & Ora": first_r["Data & Ora"],
                    "Simbol": first_r["Simbol"], "Tip": first_r["Tip"],
                    "Preț Execuție": (v_tot / c_tot) if c_tot > 0 else 0.0, "Cantitate": c_tot, "Valoare": v_tot,
                    "Execuție": first_r["Execuție"], "Comision_Val": com_tot,
                    "Comision": f"${com_tot:,.4f} ({pct_c:.2f}%)", "PnL": round(safe_float(g["PnL"].sum()), 2)
                })
            df_f = pd.DataFrame(agg)
            return df_f.sort_values(by="sort_timestamp", ascending=False).drop(columns=["sort_timestamp"]).reset_index(drop=True)
        except Exception as e:
            st.warning(f"Eroare istoric Hyperliquid: {e}")
            return pd.DataFrame()

    raw_rows = []
    try:
        order_map = {}
        try:
            if hasattr(_exc, 'fetch_closed_orders'):
                for o in (_exc.fetch_closed_orders(limit=500) or []):
                    o_id = str(o.get('id', ''))
                    if o_id:
                        order_map[o_id] = f"{str(o.get('type', '')).lower()} {str((o.get('info') or {}).get('orderType', '')).lower()}"
        except Exception:
            pass

        trades_raw = []
        if piata == "Futures":
            last_fill_time_param = None
            for _ in range(70):
                params = {'lastFillTime': last_fill_time_param} if last_fill_time_param else {}
                batch = []
                try:
                    res = _exc.private_get_fills(params)
                    if isinstance(res, dict) and res.get('fills'):
                        for f in res['fills']:
                            batch.append({
                                'id': f.get('fill_id') or f.get('fillId'), 'order': f.get('order_id') or f.get('orderId'),
                                'timestamp': f.get('fillTime') or f.get('time'), 'symbol': f.get('symbol'),
                                'side': f.get('side'), 'price': f.get('price'), 'amount': f.get('size'),
                                'fee': {'cost': f.get('feePaid')}, 'info': f
                            })
                except Exception:
                    try:
                        batch = _exc.fetch_my_trades(limit=100, params=params)
                    except Exception:
                        break
                if not batch:
                    break
                trades_raw.extend(batch)

                oldest_ts_ms, oldest_iso, newest_ts_ms = None, None, None
                for item in batch:
                    inf = item.get('info', {}) or {}
                    raw_t = inf.get('fillTime') or item.get('timestamp') or inf.get('time')
                    ts_ms = get_ts_ms(raw_t)
                    if ts_ms > 0:
                        if newest_ts_ms is None or ts_ms > newest_ts_ms:
                            newest_ts_ms = ts_ms
                        if oldest_ts_ms is None or ts_ms <= oldest_ts_ms:
                            oldest_ts_ms = ts_ms
                            oldest_iso = inf.get('fillTime') if isinstance(inf.get('fillTime'), str) else to_iso_utc(ts_ms)

                if oldest_ts_ms is None or oldest_ts_ms < (since_timestamp - 3 * 86400 * 1000):
                    break

                overlap_iso = to_iso_utc(oldest_ts_ms + 500) if (newest_ts_ms and newest_ts_ms > oldest_ts_ms + 1000) else oldest_iso
                if not overlap_iso or overlap_iso == last_fill_time_param:
                    overlap_iso = oldest_iso if (oldest_iso and oldest_iso != last_fill_time_param) else to_iso_utc(oldest_ts_ms - 1)
                last_fill_time_param = overlap_iso
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

        unique_trades = {str(t.get('id') or (t.get('info') or {}).get('fill_id') or (t.get('info') or {}).get('fillId') or id(t)): t for t in trades_raw if isinstance(t, dict)}
        for t in unique_trades.values():
            info = t.get('info', {}) or {}
            sort_ts_ms = get_ts_ms(t.get('timestamp') or info.get('fillTime') or info.get('time') or info.get('launchTime'))
            if sort_ts_ms <= 0:
                continue
            data_ora_minut, _ = parse_timestamp(sort_ts_ms)
            simbol_curat = clean_sym(t.get('symbol') or info.get('symbol') or 'N/A')
            raw_side = str(t.get('side') or info.get('side') or 'N/A').lower()
            directie = "LONG" if raw_side == "buy" else ("SHORT" if raw_side == "sell" else raw_side.upper())
            order_id = str(t.get('order') or info.get('order_id') or info.get('orderId') or f"{data_ora_minut}_{simbol_curat}_{directie}")
            tot_text = f"{str(info.get('type') or info.get('orderType') or t.get('type') or '').lower()} {str(info.get('reason') or '').lower()} {order_map.get(order_id, '').lower()}"
            fill_type = str(info.get('fillType') or t.get('takerOrMaker') or '').lower()

            if 'trailing' in tot_text:
                exec_det = "TRAILING STOP"
            elif 'stop' in tot_text or 'stp' in tot_text:
                exec_det = "STOP LOSS"
            elif 'take' in tot_text or 'profit' in tot_text or 'target' in tot_text:
                exec_det = "TAKE PROFIT"
            elif 'maker' in fill_type or 'post' in tot_text:
                exec_det = "SELL LIMIT" if raw_side == "sell" else "BUY LIMIT"
            elif 'taker' in fill_type or 'market' in tot_text or 'mkt' in tot_text or 'ioc' in tot_text:
                exec_det = "MANUAL"
            elif 'limit' in tot_text or 'lmt' in tot_text:
                exec_det = "SELL LIMIT" if raw_side == "sell" else "BUY LIMIT"
            else:
                exec_det = "MANUAL"

            pnl_val = safe_float(info.get('realisedPnl') or info.get('realizedPnl') or info.get('realised_pnl') or info.get('pnl') or t.get('pnl') or 0)
            pret = safe_float(t.get('price') or info.get('price') or info.get('fillPrice') or 0)
            cant = safe_float(t.get('amount') or info.get('size') or info.get('filled') or 0)
            val_fill = pret * cant
            com_api = safe_float((t.get('fee') or {}).get('cost') or info.get('feePaid') or info.get('fee') or 0)
            comision = com_api if com_api > 0 else val_fill * (0.0002 if 'maker' in fill_type else 0.0005)

            if cant > 0:
                raw_rows.append({
                    "grup_cheie": order_id, "sort_timestamp": sort_ts_ms / 1000.0, "Data & Ora": data_ora_minut,
                    "Simbol": simbol_curat, "Tip": directie, "pret_parțial": val_fill,
                    "Cantitate": cant, "Execuție": exec_det, "Comision": comision, "PnL": pnl_val
                })

        if not raw_rows:
            return pd.DataFrame()
        df_raw = pd.DataFrame(raw_rows)
        aggregated_data = []
        for _, grup in df_raw.groupby("grup_cheie"):
            c_tot, v_tot = safe_float(grup["Cantitate"].sum()), safe_float(grup["pret_parțial"].sum())
            com_tot = safe_float(grup["Comision"].sum())
            pct_c = (com_tot / v_tot * 100) if v_tot > 0 else 0.0
            first_row = grup.sort_values(by="sort_timestamp", ascending=False).iloc[0]
            aggregated_data.append({
                "sort_timestamp": first_row["sort_timestamp"], "Data & Ora": first_row["Data & Ora"],
                "Simbol": first_row["Simbol"], "Tip": first_row["Tip"],
                "Preț Execuție": (v_tot / c_tot) if c_tot > 0 else 0.0, "Cantitate": c_tot, "Valoare": v_tot,
                "Execuție": first_row["Execuție"], "Comision_Val": com_tot,
                "Comision": f"${com_tot:,.4f} ({pct_c:.2f}%)", "PnL_API": safe_float(grup["PnL"].sum())
            })

        aggregated_data.sort(key=lambda x: x["sort_timestamp"])
        by_sym = {}
        for row in aggregated_data:
            by_sym.setdefault(row["Simbol"], []).append(row)

        for sym, s_rows in by_sym.items():
            pos = {"side": None, "qty": 0.0, "price": 0.0, "ts": 0.0}
            n_rows = len(s_rows)

            for i, row in enumerate(s_rows):
                side = row["Tip"]
                qty = row["Cantitate"]
                price = row["Preț Execuție"]
                ts = row["sort_timestamp"]

                if pos["qty"] > 1e-9:
                    same_sums = []
                    acc_s = 0.0
                    idx = i
                    while idx < n_rows and s_rows[idx]["Tip"] == side:
                        acc_s += s_rows[idx]["Cantitate"]
                        same_sums.append(acc_s)
                        idx += 1

                    opp_sums = []
                    acc_o = 0.0
                    idx_o = idx
                    while idx_o < n_rows and s_rows[idx_o]["Tip"] != side:
                        acc_o += s_rows[idx_o]["Cantitate"]
                        opp_sums.append(acc_o)
                        idx_o += 1

                    tol_pos = max(1e-6, pos["qty"] * 0.005)
                    tol_qty = max(1e-6, qty * 0.005)

                    if pos["side"] != side:
                        matches_pos = any(abs(s_val - pos["qty"]) <= tol_pos for s_val in same_sums)
                        matches_next_opp = any(
                            abs(o_val - qty) <= tol_qty or abs(o_val - same_sums[-1]) <= max(1e-6, same_sums[-1] * 0.005)
                            for o_val in opp_sums
                        )
                        if not matches_pos and (matches_next_opp or (ts - pos["ts"] > 12 * 3600)):
                            pos = {"side": None, "qty": 0.0, "price": 0.0, "ts": 0.0}
                        elif matches_pos and matches_next_opp and (ts - pos["ts"] > 3600) and (idx < n_rows) and (s_rows[idx]["sort_timestamp"] - ts < 3600):
                            pos = {"side": None, "qty": 0.0, "price": 0.0, "ts": 0.0}
                    else:
                        matches_combined = any(
                            abs(o_val - (pos["qty"] + s_val)) <= max(1e-6, (pos["qty"] + s_val) * 0.005)
                            for s_val in same_sums for o_val in opp_sums
                        )
                        matches_fresh = any(
                            abs(o_val - qty) <= tol_qty or abs(o_val - same_sums[-1]) <= max(1e-6, same_sums[-1] * 0.005)
                            for o_val in opp_sums
                        )
                        if not matches_combined and (matches_fresh or (ts - pos["ts"] > 6 * 3600)):
                            pos = {"side": None, "qty": 0.0, "price": 0.0, "ts": 0.0}

                calc_pnl = 0.0
                if pos["qty"] <= 1e-9 or pos["side"] == side:
                    new_q = pos["qty"] + qty
                    new_p = ((pos["qty"] * pos["price"]) + (qty * price)) / new_q if new_q > 0 else price
                    pos = {"side": side, "qty": new_q, "price": new_p, "ts": ts}
                else:
                    closed_q = min(pos["qty"], qty)
                    calc_pnl = (price - pos["price"]) * closed_q if pos["side"] == "LONG" else (pos["price"] - price) * closed_q
                    rem_p = pos["qty"] - closed_q
                    rem_o = qty - closed_q
                    if rem_p > 1e-9:
                        pos = {"side": pos["side"], "qty": rem_p, "price": pos["price"], "ts": pos["ts"]}
                    elif rem_o > 1e-9:
                        pos = {"side": side, "qty": rem_o, "price": price, "ts": ts}
                    else:
                        pos = {"side": None, "qty": 0.0, "price": 0.0, "ts": 0.0}

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
        st.warning(f"Eroare preluare istoric: {e}")
        return pd.DataFrame()


def color_trade_table(df):
    if df.empty or 'PnL' not in df.columns:
        return df
    df_viz = df.drop(columns=['Comision_Val'], errors='ignore').copy()
    df_viz['PnL'] = pd.to_numeric(df_viz['PnL'], errors='coerce').fillna(0.0)
    styled = df_viz.style.apply(lambda r: ['background-color: rgba(77, 163, 255, 0.12);'] * len(r) if safe_float(r['PnL']) != 0.0 else [''] * len(r), axis=1)
    styled = styled.map(lambda v: 'color: #28a745; font-weight: bold;' if v == "LONG" else ('color: #ff3333; font-weight: bold;' if v == "SHORT" else ''), subset=['Tip'])
    styled = styled.map(lambda v: 'color: #28a745; font-weight: bold; font-size: 1.1em;' if safe_float(v) > 0 else ('color: #ff3333; font-weight: bold; font-size: 1.1em;' if safe_float(v) < 0 else 'color: #6c757d;'), subset=['PnL'])
    styled = styled.map(lambda _: 'color: #4da3ff;', subset=['Data & Ora'])
    styled = styled.map(lambda _: 'color: #00e676; font-weight: bold;', subset=['Simbol'])
    styled = styled.map(lambda _: 'color: #ffc107;', subset=['Preț Execuție'])
    styled = styled.map(lambda _: 'color: #b19cd9;', subset=['Cantitate'])
    styled = styled.map(lambda _: 'color: #20c997;', subset=['Valoare'])
    styled = styled.map(lambda _: 'color: #ffa500; font-weight: bold;', subset=['Execuție'])
    styled = styled.map(lambda _: 'color: #ff8c94;', subset=['Comision'])
    return styled.format({"Preț Execuție": "${:,.4f}", "Valoare": "${:,.2f}", "PnL": lambda v: "$0.00" if safe_float(v) == 0 else f"${safe_float(v):+,.2f}"})


if connected_ok:
    tab1, tab2 = st.tabs([f"📌 Poziții Active Live ({exchange_ales})", f"📜 Istoricul Universal ({exchange_ales} - {piata_ales})"])

    with tab1:
        st.subheader(f"Monitorizare în timp real — {exchange_ales} ({piata_ales})")
        run_every_val = f"{refresh_interval}s" if auto_refresh else None
        live_placeholder = st.empty()

        @st.fragment(run_every=run_every_val)
        def afiseaza_pozitii_live():
            df_active = fetch_active_positions(exchange_ales, exchange, piata_ales, hl_wallet_input)
            with live_placeholder.container():
                if not df_active.empty:
                    st.dataframe(color_active_table(df_active), width="stretch", height=300, hide_index=True)
                else:
                    st.info(f"Momentan nu ai poziții active pe {exchange_ales} ({piata_ales}).")
        afiseaza_pozitii_live()

    with tab2:
        cb1, cb2, _ = st.columns([1.2, 1.5, 3.3])
        with cb1:
            if st.button("🔄 Actualizează Istoricul"):
                fetch_closed_trades_history.clear()
        with cb2:
            if st.button("📅 Reset la Tot Istoricul (20 Sept - Azi)"):
                save_user_settings({
                    "start_date": "2026-09-20",
                    "end_date": today_ro().strftime("%Y-%m-%d"),
                    "monede_excluse": [],
                    "directii": ["LONG", "SHORT"]
                })
                st.rerun()

        df_istoric = fetch_closed_trades_history(exchange_ales, exchange, piata_ales, hl_wallet_input)
        if not df_istoric.empty:
            df_istoric['temp_dt'] = pd.to_datetime(df_istoric['Data & Ora'], format='%d-%m-%Y %H:%M', errors='coerce').dt.date
            min_bound = date(2026, 9, 1)
            azi_ro = today_ro()
            max_bound = max(azi_ro, df_istoric['temp_dt'].dropna().max() or azi_ro)

            try:
                saved_start = datetime.strptime(user_cfg.get("start_date", "2026-09-20"), "%Y-%m-%d").date()
            except Exception:
                saved_start = date(2026, 9, 20)
            try:
                saved_end = datetime.strptime(user_cfg.get("end_date", azi_ro.strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            except Exception:
                saved_end = azi_ro

            saved_start = max(min_bound, min(saved_start, max_bound))
            saved_end = max(saved_start, min(saved_end, max_bound))

            cd1, cd2 = st.columns(2)
            with cd1:
                sel_start_date = st.date_input("🗓️ De la (ZZ/LL/AAAA)", value=saved_start, min_value=min_bound, max_value=max_bound, format="DD/MM/YYYY")
            with cd2:
                sel_end_date = st.date_input("🗓️ Până la (ZZ/LL/AAAA)", value=saved_end, min_value=min_bound, max_value=max_bound, format="DD/MM/YYYY")

            lista_simboluri = sorted(df_istoric['Simbol'].dropna().unique().tolist())
            monede_excluse = user_cfg.get("monede_excluse", [])
            default_coins = [c for c in lista_simboluri if c not in monede_excluse] or lista_simboluri
            sel_simboluri = st.multiselect("🪙 Monede", options=lista_simboluri, default=default_coins)

            saved_dirs = [d for d in user_cfg.get("directii", ["LONG", "SHORT"]) if d in ["LONG", "SHORT"]]
            sel_directii = st.multiselect("↕️ Direcție", options=["LONG", "SHORT"], default=saved_dirs if saved_dirs else ["LONG", "SHORT"])

            new_s_str, new_e_str = sel_start_date.strftime("%Y-%m-%d"), sel_end_date.strftime("%Y-%m-%d")
            new_excluse = [c for c in lista_simboluri if c not in sel_simboluri]
            if (
                new_s_str != user_cfg.get("start_date") or
                new_e_str != user_cfg.get("end_date") or
                new_excluse != user_cfg.get("monede_excluse", []) or
                sel_directii != user_cfg.get("directii", ["LONG", "SHORT"])
            ):
                save_user_settings({
                    "start_date": new_s_str,
                    "end_date": new_e_str,
                    "monede_excluse": new_excluse,
                    "directii": sel_directii
                })

            df_filtrat = df_istoric[
                (df_istoric['temp_dt'] >= sel_start_date) & (df_istoric['temp_dt'] <= sel_end_date) &
                (df_istoric['Simbol'].isin(sel_simboluri)) & (df_istoric['Tip'].isin(sel_directii))
            ].copy().drop(columns=['temp_dt'])

            total_pnl = df_filtrat['PnL'].sum() if not df_filtrat.empty else 0.0
            total_comision = df_filtrat['Comision_Val'].sum() if ('Comision_Val' in df_filtrat.columns and not df_filtrat.empty) else 0.0
            trades_inchise = df_filtrat[df_filtrat['PnL'] != 0.0] if not df_filtrat.empty else pd.DataFrame()
            nr_inchise = len(trades_inchise)
            nr_wins = int(len(trades_inchise[trades_inchise['PnL'] > 0])) if nr_inchise > 0 else 0
            nr_losses = int(len(trades_inchise[trades_inchise['PnL'] < 0])) if nr_inchise > 0 else 0
            win_rate = (nr_wins / nr_inchise * 100.0) if nr_inchise > 0 else 0.0
            best_trade = trades_inchise['PnL'].max() if nr_inchise > 0 else 0.0
            worst_trade = trades_inchise['PnL'].min() if nr_inchise > 0 else 0.0

            col_pnl_box, col_kpi_table = st.columns([1.2, 3.3])
            with col_pnl_box:
                bg_c = "rgba(40, 167, 69, 0.15)" if total_pnl >= 0 else "rgba(255, 51, 51, 0.15)"
                tx_c = "#00e676" if total_pnl >= 0 else "#ff3333"
                sgn = "+" if total_pnl >= 0 else ""
                st.markdown(f"""
                <div style="background-color:{bg_c};border:1px solid {tx_c};border-radius:8px;padding:12px;text-align:center;">
                    <h3 style="margin:0;color:#fff;font-size:1.05rem;">PnL Total Cumulat</h3>
                    <h2 style="margin:4px 0 0 0;color:{tx_c};font-size:1.85rem;white-space:nowrap;">{sgn}${total_pnl:,.2f}</h2>
                </div>
                """, unsafe_allow_html=True)

            with col_kpi_table:
                def c_val(v, curr=True, neut=False):
                    if neut:
                        return f"<span style='color:#ffc107;white-space:nowrap;'>{v}</span>"
                    if curr:
                        if v > 0:
                            return f"<span style='color:#00e676;white-space:nowrap;'>+${v:,.2f}</span>"
                        elif v < 0:
                            return f"<span style='color:#ff3333;white-space:nowrap;'>-${abs(v):,.2f}</span>"
                        return "<span style='color:#6c757d;white-space:nowrap;'>$0.00</span>"
                    return v

                wl_html = (
                    f"<span style='color:#00e676;white-space:nowrap;'>{nr_wins} W</span>"
                    f" <span style='color:#888;'>/</span> "
                    f"<span style='color:#ff3333;white-space:nowrap;'>{nr_losses} L</span>"
                )

                st.markdown(f"""
                <table style="width:100%;text-align:center;border-collapse:collapse;font-size:0.92rem;">
                    <tr>
                        <th style="padding:6px;border-bottom:1px solid #444;color:#aaa;">Tranzacții Complete</th>
                        <th style="padding:6px;border-bottom:1px solid #444;color:#aaa;">Win / Loss</th>
                        <th style="padding:6px;border-bottom:1px solid #444;color:#aaa;">Win Rate</th>
                        <th style="padding:6px;border-bottom:1px solid #444;color:#aaa;">Comision Perioadă</th>
                        <th style="padding:6px;border-bottom:1px solid #444;color:#aaa;">Cel mai bun Trade</th>
                        <th style="padding:6px;border-bottom:1px solid #444;color:#aaa;">Cel mai slab Trade</th>
                    </tr>
                    <tr>
                        <td style="padding:8px;font-weight:bold;">{c_val(f'{nr_inchise}', False, True)}</td>
                        <td style="padding:8px;font-weight:bold;white-space:nowrap;">{wl_html}</td>
                        <td style="padding:8px;font-weight:bold;">{c_val(f'{win_rate:.1f}%', False, True)}</td>
                        <td style="padding:8px;font-weight:bold;color:#ff8c94;white-space:nowrap;">${total_comision:,.2f}</td>
                        <td style="padding:8px;font-weight:bold;">{c_val(best_trade)}</td>
                        <td style="padding:8px;font-weight:bold;">{c_val(worst_trade)}</td>
                    </tr>
                </table>
                """, unsafe_allow_html=True)

            col_exp_chart, col_exp_csv = st.columns(2)
            with col_exp_chart:
                with st.expander("📈 Grafic Evoluție PnL Cumulat (Equity Curve)", expanded=False):
                    if not trades_inchise.empty:
                        df_chart = trades_inchise.iloc[::-1].copy()
                        df_chart['Timp_Fix'] = pd.to_datetime(df_chart['Data & Ora'], format='%d-%m-%Y %H:%M')
                        df_chart['PnL Cumulat ($)'] = df_chart['PnL'].cumsum()
                        st.line_chart(df_chart, x='Timp_Fix', y='PnL Cumulat ($)', color="#00e676")
                    else:
                        st.info("Nu există tranzacții închise în intervalul selectat.")

            with col_exp_csv:
                with st.expander("📥 Opțiuni Export CSV (Google Sheets)", expanded=False):
                    if not df_filtrat.empty:
                        df_csv = df_filtrat.drop(columns=['Comision_Val'], errors='ignore').copy()
                        total_row = pd.DataFrame([{
                            "Data & Ora": "TOTAL PERIOADĂ", "Simbol": "", "Tip": "", "Preț Execuție": "",
                            "Cantitate": "", "Valoare": df_filtrat['Valoare'].sum(), "Execuție": "",
                            "Comision": total_comision, "PnL": total_pnl
                        }])
                        csv_data = pd.concat([df_csv, total_row], ignore_index=True).to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label=f"📥 Descarcă CSV ({sel_start_date.strftime('%d.%m.%Y')} - {sel_end_date.strftime('%d.%m.%Y')})",
                            data=csv_data,
                            file_name=f"istoric_{exchange_ales.lower()}_{sel_start_date}_{sel_end_date}.csv",
                            mime="text/csv"
                        )

            st.markdown("---")
            st.dataframe(color_trade_table(df_filtrat), width="stretch", height=540, hide_index=True)
        else:
            st.info(f"Nu s-au găsit tranzacții în istoric pe {exchange_ales} ({piata_ales}).")
else:
    st.info("👈 Introdu datele de conectare (Kraken API sau Adresa 0x... Hyperliquid) în bara din stânga.")