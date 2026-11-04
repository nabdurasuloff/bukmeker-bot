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
from _bot import LEAGUES, MIN_EV, env, format_stats, send  # noqa: E402
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
            if a["arb"] < 1 or any(b["ev"] > MIN_EV for b in a["best"]):
                signals.append(f"[{LEAGUES.get(lg, lg)}]\n" + report(a))
            preds[e["id"]] = {
                "lg": lg, "home": a["home"], "away": a["away"], "time": a["time"],
                "draw": a["draw"], "src": a["source"],
                "fair": [round(x, 4) for x in a["fair"]],
                "best": [[b["odds"], b["book"]] for b in a["best"]],
                "books": {b["name"]: b["odds"] for b in a["books"]},
                "snap": NOW.isoformat(timespec="minutes"), "result": None,
            }
    return signals


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


def compute_stats(preds):
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
        fav["n"] += 1
        fav["p"] += fair[k]
        win = k == res
        fav["hit"] += win
        fav["profit"] += (best[k][0] - 1) if win else -1
        for i, q in enumerate(fair):
            if q * best[i][0] - 1 > MIN_EV:
                val["n"] += 1
                val["hit"] += i == res
                val["profit"] += (best[i][0] - 1) if i == res else -1
    recent = sorted(done, key=lambda p: p["time"], reverse=True)[:8]
    return {
        "updated": NOW.isoformat(timespec="minutes"),
        "matches": len(done),
        "pending": sum(1 for p in preds.values() if p.get("result") is None),
        "brier": round(brier / len(done), 4) if done else None,
        "fav": fav, "value": val,
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


def main():
    key = env("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY yo'q")
    preds = load()
    newly = settle(preds, key)
    signals = snapshot(preds, key)
    save(preds)
    st = compute_stats(preds)
    with open(STATS_PY, "w") as f:
        f.write("# Avtomatik yaratiladi (scripts/track.py). Qo'lda o'zgartirmang.\n")
        f.write("STATS = " + pprint.pformat(st, width=100, sort_dicts=False) + "\n")

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
