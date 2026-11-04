"""Kunlik kuzatuv (GitHub Actions):

1. Yaqin 36 soatdagi o'yinlar uchun bozor ehtimollarini (prognozni) data/predictions.json ga yozadi.
2. Tugagan o'yinlar natijasini The Odds API /scores orqali olib, prognoz bilan solishtiradi.
3. Statistikani api/_stats.py ga yozadi (bot "📊 Natijalar" tugmasi shuni o'qiydi).
4. Telegramga kunlik hisobot va signallarni yuboradi.

Hech qanday pul tikilmaydi — bu faqat "qog'ozda sinov".
"""
import json
import os
import pprint
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
from _bot import LEAGUES, MIN_EV, env, format_stats, is_signal, my_bookies, send  # noqa: E402
from _prognoz import API, analyse, fetch, fmt_time, report  # noqa: E402

# Kuzatiladigan ligalar (har biri kuniga ~1 kredit + natija uchun ~2 kredit)
TRACK = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "basketball_nba"]
DATA = os.path.join(ROOT, "data", "predictions.json")
STATS_PY = os.path.join(ROOT, "api", "_stats.py")
NOW = datetime.now(timezone.utc)


def parse(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def load():
    try:
        with open(DATA) as f:
            return json.load(f)
    except Exception:
        return {}


def save(preds):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w") as f:
        json.dump(preds, f, ensure_ascii=False, indent=0, sort_keys=True)


def snapshot(preds, key):
    """Yaqin o'yinlar prognozini yozadi, signallarni qaytaradi."""
    signals = []
    for lg in TRACK:
        events, _ = fetch(key, lg, "eu")
        for e in events:
            try:
                t = parse(e["commence_time"])
            except Exception:
                continue
            if not (NOW < t <= NOW + timedelta(hours=36)):
                continue
            a = analyse(e)
            if not a:
                continue
            mine = analyse(e, only=my_bookies())
            old = preds.get(e["id"], {})
            rec = record(lg, a)
            rec["sig"] = old.get("sig")
            if mine and is_signal(mine):
                signals.append(f"[{LEAGUES.get(lg, lg)}]\n" + report(mine))
                if not rec["sig"]:
                    k = max(range(len(mine["best"])), key=lambda i: mine["best"][i]["ev"])
                    b = mine["best"][k]
                    rec["sig"] = {"i": k, "odds": b["odds"], "book": b["book"],
                                  "fair": round(a["fair"][k], 4), "ev": round(b["ev"], 4),
                                  "at": NOW.isoformat(timespec="minutes")}
            preds[e["id"]] = rec
    return signals


def record(lg, a):
    return {
        "lg": lg, "home": a["home"], "away": a["away"], "time": a["time"],
        "draw": a["draw"], "src": a["source"],
        "fair": [round(x, 4) for x in a["fair"]],
        "best": [[b["odds"], b["book"]] for b in a["best"]],
        "books": {b["name"]: b["odds"] for b in a["books"]},
        "snap": NOW.isoformat(timespec="minutes"), "result": None,
    }


def closing(preds, key):
    """O'yin boshlanishiga ~70 daqiqa qolganda signal berilgan o'yinlarning yakuniy (yopilish) narxini yozadi.
    Faqat shunday o'yin bo'lsa API so'raladi — aks holda kredit sarflanmaydi."""
    due = {}
    for gid, p in preds.items():
        if p.get("sig") and not p.get("closed") and p.get("result") is None:
            t = parse(p["time"])
            if NOW < t <= NOW + timedelta(minutes=70):
                due.setdefault(p["lg"], []).append(gid)
    changed = 0
    for lg, ids in due.items():
        events, _ = fetch(env("ODDS_API_KEY"), lg, "eu")
        by_id = {e["id"]: e for e in events}
        for gid in ids:
            e = by_id.get(gid)
            a = analyse(e) if e else None
            if not a:
                continue
            p = preds[gid]
            p["fair"] = [round(x, 4) for x in a["fair"]]
            p["books"] = {b["name"]: b["odds"] for b in a["books"]}
            p["snap"] = NOW.isoformat(timespec="minutes")
            p["closed"] = True
            changed += 1
    return changed


def settle(preds, key):
    """Tugagan o'yinlar natijasini yozadi. Faqat kutilayotgan o'yini bor ligalar so'raladi."""
    pending = {p["lg"] for p in preds.values()
               if p.get("result") is None and parse(p["time"]) < NOW - timedelta(hours=2)}
    newly = []
    for lg in pending:
        try:
            r = requests.get(f"{API}/sports/{lg}/scores", timeout=20,
                             params={"apiKey": key, "daysFrom": 3})
            games = r.json() if r.status_code == 200 else []
        except Exception:
            games = []
        for g in games:
            p = preds.get(g.get("id"))
            if not p or p.get("result") is not None or not g.get("completed") or not g.get("scores"):
                continue
            sc = {s["name"]: float(s["score"]) for s in g["scores"] if s.get("score") is not None}
            h, a = sc.get(p["home"]), sc.get(p["away"])
            if h is None or a is None:
                continue
            if p["draw"]:
                p["result"] = 0 if h > a else (1 if h == a else 2)
            else:
                p["result"] = 0 if h > a else 1
            p["score"] = f"{int(h)}:{int(a)}"
            newly.append(p)
    # 5 kundan oshib ham natijasi topilmaganlar hisobga olinmaydi
    for p in preds.values():
        if p.get("result") is None and parse(p["time"]) < NOW - timedelta(days=5):
            p["result"] = "void"
    return newly


def my_odds(p):
    """Sizning bukmekerlaringizdagi eng yaxshi koeffitsiyent (yo'q bo'lsa — None)."""
    mine = [o for name, o in p.get("books", {}).items()
            if any(m.lower() in name.lower() for m in my_bookies())]
    if not mine:
        return None
    return [max(o[i] for o in mine) for i in range(len(p["fair"]))]


def compute_stats(preds, signals=None):
    done = [p for p in preds.values() if isinstance(p.get("result"), int)]
    buckets = [[0, .4], [.4, .5], [.5, .6], [.6, .7], [.7, .8], [.8, 1.01]]
    bstat = [{"lo": lo, "hi": min(hi, 1), "n": 0, "p": 0.0, "hit": 0} for lo, hi in buckets]
    fav = {"n": 0, "hit": 0, "p": 0.0, "profit": 0.0}
    val = {"n": 0, "hit": 0, "profit": 0.0}
    brier = 0.0
    for p in done:
        res, fair, best = p["result"], p["fair"], p["best"]
        brier += sum((fair[i] - (1 if i == res else 0)) ** 2 for i in range(len(fair)))
        for i, q in enumerate(fair):
            for b in bstat:
                if b["lo"] <= q < b["hi"] or (b["hi"] == 1 and q >= b["lo"]):
                    b["n"] += 1
                    b["p"] += q
                    b["hit"] += 1 if i == res else 0
                    break
        k = max(range(len(fair)), key=lambda i: fair[i])
        mo = my_odds(p)
        fav["n"] += 1
        fav["p"] += fair[k]
        win = k == res
        fav["hit"] += win
        if mo:  # virtual tikish faqat sizning bukmekeringiz narxida
            fav["bets"] = fav.get("bets", 0) + 1
            fav["profit"] += (mo[k] - 1) if win else -1
        sg = p.get("sig")
        if sg:  # signal berilgan paytdagi narxda
            val["n"] += 1
            val["hit"] += sg["i"] == res
            val["profit"] += (sg["odds"] - 1) if sg["i"] == res else -1
    # Kelly mezoni: virtual bank 100 000 so'm, chorak-Kelly, bitta tikish bankning 5% idan oshmaydi
    bank, peak, low, kb = 100000.0, 100000.0, 100000.0, 0
    for p in sorted(done, key=lambda p: p["time"]):
        sg = p.get("sig")
        if not sg:
            continue
        o, q = sg["odds"], sg["fair"]
        f = min(max((q * o - 1) / (o - 1), 0) * 0.25, 0.05)
        if f <= 0:
            continue
        stake = bank * f
        bank += stake * (o - 1) if sg["i"] == p["result"] else -stake
        peak, low, kb = max(peak, bank), min(low, bank), kb + 1
    kelly = {"bank": round(bank), "bets": kb, "peak": round(peak), "low": round(low)}
    # CLV: signal narxi yopilish paytidagi adolatli narxdan yaxshi bo'lganmi
    clvs = [p["sig"]["odds"] * p["fair"][p["sig"]["i"]] - 1
            for p in preds.values() if p.get("sig") and p.get("closed")]
    clv = {"n": len(clvs), "avg": round(sum(clvs) / len(clvs), 4) if clvs else None,
           "pos": sum(1 for c in clvs if c > 0)}
    recent = sorted(done, key=lambda p: p["time"], reverse=True)[:8]
    return {
        "updated": NOW.isoformat(timespec="minutes"),
        "bookies": my_bookies(),
        "signals": signals or [],
        "matches": len(done),
        "pending": sum(1 for p in preds.values() if p.get("result") is None),
        "brier": round(brier / len(done), 4) if done else None,
        "fav": fav, "value": val, "kelly": kelly, "clv": clv,
        "buckets": [b for b in bstat if b["n"]],
        "recent": [{"m": f"{p['home']} — {p['away']}", "score": p.get("score"),
                    "fav": max(range(len(p["fair"])), key=lambda i: p["fair"][i]),
                    "p": max(p["fair"]), "res": p["result"], "draw": p["draw"]} for p in recent],
    }


def result_line(p):
    k = max(range(len(p["fair"])), key=lambda i: p["fair"][i])
    names = [p["home"], "Durang", p["away"]] if p["draw"] else [p["home"], p["away"]]
    ok = "✅" if k == p["result"] else "❌"
    return f"{ok} {p['home']} — {p['away']} {p.get('score')} | prognoz: {names[k]} {max(p['fair'])*100:.0f}%"


def write_stats(preds, signals):
    st = compute_stats(preds, signals)
    with open(STATS_PY, "w") as f:
        f.write("# Avtomatik yaratiladi (scripts/track.py). Qo'lda o'zgartirmang.\n")
        f.write("STATS = " + pprint.pformat(st, width=100, sort_dicts=False) + "\n")
    return st


def previous_signals():
    try:
        sys.path.insert(0, os.path.join(ROOT, "api"))
        from _stats import STATS
        return STATS.get("signals", [])
    except Exception:
        return []


def main():
    key = env("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY yo'q")
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    preds = load()

    if mode == "closing":
        n = closing(preds, key)
        print(f"Yopilish narxi yozildi: {n}")
        if n:
            save(preds)
            write_stats(preds, previous_signals())
        return

    newly = settle(preds, key)
    signals = snapshot(preds, key)
    save(preds)
    st = write_stats(preds, signals)

    chat = env("CHAT_ID")
    print(f"Yangi natijalar: {len(newly)}, signallar: {len(signals)}, jami: {st['matches']}")
    if not chat:
        print("CHAT_ID yo'q — Telegramga yuborilmadi")
        return
    msg = ["📊 Kunlik hisobot"]
    if newly:
        msg.append("\nOxirgi natijalar:\n" + "\n".join(result_line(p) for p in newly[:15]))
    msg.append("\n" + format_stats(st))
    send(chat, "\n".join(msg))
    if signals:
        send(chat, f"🔔 {len(signals)} ta signal (yaqin 36 soat):\n\n" + "\n\n".join(signals))


if __name__ == "__main__":
    main()
