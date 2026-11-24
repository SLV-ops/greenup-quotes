"""Relevé quotidien des cours de clôture pour le site GreenUp 2027 (EDHEC, groupe 5).

Source principale : Yahoo Finance (sans clé). Secours : Alpha Vantage (clé dans le secret
ALPHAVANTAGE_KEY). Si les deux échouent pour un titre, le dernier cours connu est conservé
avec sa date, pour que le site n'affiche jamais de valeur vide.
"""
import datetime, json, os, time, urllib.parse, urllib.request

OUT = "quotes.json"
STOCKS = {  # clé du site: (symbole Yahoo, symbole Alpha Vantage, devise)
    "ONT":   ("ONT",      "ONT",       "USD"),   # Onterris, NYSE
    "VIE":   ("VIE.PA",   "VIE.PAR",   "EUR"),   # Veolia, Euronext Paris
    "SCHP":  ("SCHP.PA",  "SCHP.PAR",  "EUR"),   # Séché Environnement, Euronext Paris
    "LAT1V": ("LASTIK.HE", "LASTIK.HEL", "EUR"),   # Lassila & Tikanoja (code LASTIK)
    "SDV":   ("SDV.AX",   "SDV.AX",    "AUD"),   # SciDev, ASX
}
FX = {"EURUSD": ("EURUSD=X", ("EUR", "USD")), "EURAUD": ("EURAUD=X", ("EUR", "AUD"))}
AV_KEY = os.environ.get("ALPHAVANTAGE_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0 (GreenUp quotes; +https://github.com)"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def yahoo(sym):
    last_err = None
    for host in ("query1", "query2"):
        try:
            j = get_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=5d&interval=1d")
            r = j["chart"]["result"][0]
            m = r["meta"]
            off = m.get("gmtoffset", 0) or 0
            ts = r.get("timestamp") or []
            cl = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            pairs = [(t, c) for t, c in zip(ts, cl) if c]
            # Dernier cours de marché : il couvre la dernière séance même quand la
            # bougie journalière n'est pas encore complétée (cas des places européennes).
            if m.get("regularMarketPrice") and m.get("regularMarketTime"):
                pairs.append((m["regularMarketTime"], m["regularMarketPrice"]))
            t, c = max(pairs, key=lambda x: x[0])
            d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).date().isoformat()
            return round(float(c), 4), d
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"Yahoo {sym}: {last_err}")


def av_stock(sym):
    if not AV_KEY:
        raise RuntimeError("pas de clé Alpha Vantage")
    j = get_json("https://www.alphavantage.co/query?" + urllib.parse.urlencode({"function": "GLOBAL_QUOTE", "symbol": sym, "apikey": AV_KEY}))
    q = j.get("Global Quote") or {}
    if not q.get("05. price"):
        raise RuntimeError(f"Alpha Vantage {sym}: {str(j)[:120]}")
    return round(float(q["05. price"]), 4), q.get("07. latest trading day")


def av_fx(a, b):
    if not AV_KEY:
        raise RuntimeError("pas de clé Alpha Vantage")
    j = get_json("https://www.alphavantage.co/query?" + urllib.parse.urlencode({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": a, "to_currency": b, "apikey": AV_KEY}))
    q = j.get("Realtime Currency Exchange Rate") or {}
    if not q.get("5. Exchange Rate"):
        raise RuntimeError(f"Alpha Vantage {a}{b}: {str(j)[:120]}")
    return round(float(q["5. Exchange Rate"]), 5), (q.get("6. Last Refreshed") or "")[:10]


def plausible(old, new):
    """Rejette une valeur absurde (division par 100, erreur de devise...)."""
    if new is None or new <= 0:
        return False
    if old and old.get("p"):
        ratio = new / old["p"]
        return 0.4 < ratio < 2.5
    return True


def main():
    try:
        data = json.load(open(OUT, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    data.setdefault("q", {})
    data.setdefault("fx", {})
    log = []
    av_calls = 0

    def with_fallback(key, store, ysym, av_fn):
        nonlocal av_calls
        old = store.get(key)
        for name, fn in (("yahoo", lambda: yahoo(ysym)), ("alphavantage", av_fn)):
            try:
                if name == "alphavantage":
                    if av_calls:
                        time.sleep(13)  # 5 requêtes par minute maximum en gratuit
                    av_calls += 1
                p, d = fn()
                if plausible(old, p):
                    return {"p": p, "d": d, "src": name}
                log.append(f"{key}: valeur rejetée {p} ({name})")
            except Exception as e:  # noqa: BLE001
                log.append(f"{key}: {name} indisponible ({e})")
        if old:
            log.append(f"{key}: dernier cours conservé ({old.get('d')})")
            return old
        return None

    for key, (ysym, avsym, cur) in STOCKS.items():
        v = with_fallback(key, data["q"], ysym, lambda s=avsym: av_stock(s))
        if v:
            v["c"] = cur
            data["q"][key] = v
    for key, (ysym, pair) in FX.items():
        v = with_fallback(key, data["fx"], ysym, lambda a=pair[0], b=pair[1]: av_fx(a, b))
        if v:
            data["fx"][key] = v

    data["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["notes"] = log
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(data, ensure_ascii=False, indent=1))
    for line in log:
        print("NOTE", line)


if __name__ == "__main__":
    main()
