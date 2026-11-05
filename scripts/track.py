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
from _bot import LEAGUES, MIN_EV, combo_stats, env, format_short, is_signal, my_bookies, send, value_legs  # noqa: E402
from _prognoz import API, analyse, check_verdict, fetch, fmt_time, my_best, report, short_book, verdict_core  # noqa: E402
from _model import blend, elo_info, load as load_elo  # noqa: E402

# Kuzatiladigan ligalar (har biri kuniga ~1 kredit + natija uchun ~2 kredit)
TRACK = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "basketball_nba"]
DATA = os.path.join(ROOT, "data", "predictions.json")
STATS_PY = os.path.join(ROOT, "api", "_stats.py")
NOW = datetime.now(timezone.utc)
UPCOMING = {}
NEW_COUPON = []
JSTATS = {}
BANK = int(float(os.environ.get("BANK") or 100000))
META = {"upcoming_at": None}


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
    elo = load_elo()
    for lg in TRACK:
        events, _ = fetch(key, lg, "eu")
        up = UPCOMING.setdefault(lg, [])
        META["upcoming_at"] = NOW.isoformat(timespec="minutes")
        for e in events:
            try:
                t = parse(e["commence_time"])
            except Exception:
                continue
            if not (NOW < t <= NOW + timedelta(days=7)):
                continue
            a = analyse(e)
            if not a:
                continue
            mine = analyse(e, only=my_bookies())
            ei = elo_info(lg, a["home"], a["away"], elo) if a["draw"] else None
            if ei is None and a["draw"]:
                print(f"Elo nomi topilmadi: {lg}: {a['home']} / {a['away']}")
            up.append({"id": e["id"], "home": a["home"], "away": a["away"], "time": a["time"], "draw": a["draw"],
                       "fair": [round(x, 4) for x in a["fair"]],
                       "o25": round(a["over25"], 4) if a.get("over25") is not None else None,
                       "mine": [[b["odds"], b["book"]] for b in mine["best"]] if mine else None,
                       "elo": [round(x, 4) for x in ei["p"]] if ei else None})
            if not (t <= NOW + timedelta(hours=36)):
                continue
            old = preds.get(e["id"], {})
            rec = record(lg, a)
            rec["sig"] = old.get("sig")
            if ei:
                rec["elo"] = [round(x, 4) for x in ei["p"]]
            names = [a["home"], "Durang", a["away"]] if a["draw"] else [a["home"], a["away"]]
            pb = blend(ei["p"], a["fair"], ei["w"]) if ei else a["fair"]
            mo, mb = my_best(a, my_bookies())
            vd = verdict_core(pb, pb, names, mo, a.get("over25"), mb or "")
            vd.pop("text", None)
            rec["blend"] = [round(x, 4) for x in pb]
            rec["coupon"] = old.get("coupon")
            if vd["type"] == "value" and not rec["coupon"]:
                o, q = vd["odds"], vd["p"]
                f = min(max((q * o - 1) / (o - 1), 0) * 0.25, 0.05)
                stake = max(round(BANK * f / 100) * 100, 100)
                rec["coupon"] = {"i": vd["i"], "odds": o, "p": q, "stake": stake, "book": vd.get("book", ""),
                                 "at": NOW.isoformat(timespec="minutes")}
                NEW_COUPON.append(gid_label(rec))
            rec["verdict"] = vd  # o'yin boshlanishiga eng yaqin xulosa saqlanadi
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


def gid_label(p):
    names = [p["home"], "Durang", p["away"]] if p["draw"] else [p["home"], p["away"]]
    c = p["coupon"]
    nm = "durang" if names[c["i"]] == "Durang" else f"{names[c['i']]} g'alabasi"
    return (f"{p['home']} — {p['away']} · {fmt_time(p['time'])}\n"
            f"   {nm} @{c['odds']:.2f} ({short_book(c.get('book') or '1xBet')}) → {money(c['stake'])}")


def money(x):
    return f"{int(round(x)):,} so'm".replace(",", " ")


def coupon_result(p):
    c = p["coupon"]
    won = c["i"] == p["result"]
    return won, (c["stake"] * (c["odds"] - 1) if won else -c["stake"])


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
    vs = {"fav": {"n": 0, "ok": 0, "p": 0.0}, "value": {"n": 0, "ok": 0, "profit": 0.0},
          "total": {"n": 0, "ok": 0}, "skip": 0}
    for p in done:
        v = p.get("verdict")
        if not v:
            continue
        ok, tok = check_verdict(v, p["result"], p.get("score"))
        if v["type"] == "fav":
            vs["fav"]["n"] += 1
            vs["fav"]["ok"] += bool(ok)
            vs["fav"]["p"] += v["p"]
        elif v["type"] == "value":
            vs["value"]["n"] += 1
            vs["value"]["ok"] += bool(ok)
            vs["value"]["profit"] += (v["odds"] - 1) if ok else -1
        else:
            vs["skip"] += 1
        if tok is not None:
            vs["total"]["n"] += 1
            vs["total"]["ok"] += bool(tok)
    cp = [p for p in done if p.get("coupon")]
    cst = {"n": len(cp), "won": 0, "staked": 0, "profit": 0.0, "last": []}
    for p in sorted(cp, key=lambda p: p["time"]):
        won, pr = coupon_result(p)
        cst["won"] += won
        cst["staked"] += p["coupon"]["stake"]
        cst["profit"] += pr
    for p in sorted(cp, key=lambda p: p["time"], reverse=True)[:6]:
        won, pr = coupon_result(p)
        names = [p["home"], "Durang", p["away"]] if p["draw"] else [p["home"], p["away"]]
        cst["last"].append(f"{'✅' if won else '❌'} {p['home']} — {p['away']} {p.get('score')} · "
                           f"{names[p['coupon']['i']]} @{p['coupon']['odds']:.2f} → {'+' if pr > 0 else ''}{money(pr)}")
    cst["profit"] = round(cst["profit"])
    opened = [p for p in preds.values() if p.get("coupon") and p.get("result") is None
              and parse(p["time"]) > NOW]
    copen = [{"label": gid_label(p), "stake": p["coupon"]["stake"],
              "win": round(p["coupon"]["stake"] * (p["coupon"]["odds"] - 1)), "time": p["time"]}
             for p in sorted(opened, key=lambda p: p["time"])]
    eb = [p for p in done if p.get("elo")]
    def brier_of(pr, res):
        return sum((pr[i] - (1 if i == res else 0)) ** 2 for i in range(len(pr)))
    elo_cmp = {"n": len(eb),
               "brier_elo": round(sum(brier_of(p["elo"], p["result"]) for p in eb) / len(eb), 4) if eb else None,
               "brier_mkt": round(sum(brier_of(p["fair"], p["result"]) for p in eb) / len(eb), 4) if eb else None,
               "hit_elo": sum(max(range(3), key=lambda i: p["elo"][i]) == p["result"] for p in eb),
               "hit_mkt": sum(max(range(3), key=lambda i: p["fair"][i]) == p["result"] for p in eb)}
    recent = sorted(done, key=lambda p: p["time"], reverse=True)[:8]
    return {
        "updated": NOW.isoformat(timespec="minutes"),
        "bookies": my_bookies(),
        "signals": signals or [],
        "matches": len(done),
        "pending": sum(1 for p in preds.values() if p.get("result") is None),
        "brier": round(brier / len(done), 4) if done else None,
        "fav": fav, "value": val, "kelly": kelly, "clv": clv, "elo": elo_cmp, "verdicts": vs,
        "coupon": cst, "coupon_open": copen, "bank": BANK, "jackpots": JSTATS,
        "upcoming": UPCOMING, "upcoming_at": META["upcoming_at"],
        "buckets": [b for b in bstat if b["n"]],
        "recent": [{"m": f"{p['home']} — {p['away']}", "score": p.get("score"),
                    "fav": max(range(len(p["fair"])), key=lambda i: p["fair"][i]),
                    "p": max(p["fair"]), "res": p["result"], "draw": p["draw"]} for p in recent],
    }


def result_line(p):
    """Bir qatorli natija: belgi, o'yin, hisob, bot xulosasi."""
    names = [p["home"], "Durang", p["away"]] if p["draw"] else [p["home"], p["away"]]
    head = f"{p['home']} — {p['away']} {p.get('score')}"
    v = p.get("verdict")
    if not v or v["type"] == "skip":
        tail = ""
        if v and v.get("total"):
            _, tok = check_verdict(v, p["result"], p.get("score"))
            if tok is not None:
                tail = f" · total {'✅' if tok else '❌'}"
        return f"⏭ {head}{tail}"
    ok, tok = check_verdict(v, p["result"], p.get("score"))
    nm = "durang" if names[v["i"]] == "Durang" else names[v["i"]]
    if v["type"] == "value":
        what = f"qiymat: {nm} @{v['odds']:.2f} ({'+' if ok else ''}{(v['odds'] - 1) if ok else -1:.2f})"
    else:
        what = f"{nm} ({v['p']*100:.0f}%)"
    tail = f" · total {'✅' if tok else '❌'}" if tok is not None else ""
    return f"{'✅' if ok else '❌'} {head} · {what}{tail}"


JACK = os.path.join(ROOT, "data", "jackpots.json")
NEW_JACK = []


def load_jack():
    try:
        with open(JACK) as f:
            return json.load(f)
    except Exception:
        return []


def jack_settle(jacks, preds):
    """Barcha o'yinlari tugagan jekpotlarni hisoblaydi (bekor o'yin koeffitsiyenti 1 deb olinadi)."""
    from itertools import combinations
    done_now = []
    for j in jacks:
        if j.get("done"):
            continue
        rs = []
        for l in j["legs"]:
            r = (preds.get(l["id"]) or {}).get("result")
            if r is None:
                break
            rs.append(1.0 if r == "void" else (l["odds"] if r == l["i"] else 0.0))
        else:
            ex = 1.0
            for x in rs:
                ex *= x
            j["express_ret"] = round(j["stake"] * ex)
            if j.get("k"):
                combos = list(combinations(range(len(rs)), j["k"]))
                per = j["stake"] / len(combos)
                ret = 0.0
                for c in combos:
                    q = 1.0
                    for i in c:
                        q *= rs[i]
                    ret += per * q
                j["system_ret"] = round(ret)
            j["hits"] = sum(1 for x in rs if x > 1)
            j["done"] = True
            done_now.append(j)
    return done_now


def jack_create(jacks, st):
    legs = [l for l in value_legs(st) if l.get("id")]
    if len(legs) < 2:
        return
    used = {l["id"] for j in jacks if not j.get("done") for l in j["legs"]}
    if any(l["id"] in used for l in legs):
        return  # ochiq jekpot bilan kesishadi — yangisini tuzmaymiz
    stake = max(round(BANK * 0.005 / 100) * 100, 500)
    odds, p, ev = combo_stats(legs)
    j = {"at": NOW.isoformat(timespec="minutes"), "legs": legs, "stake": stake,
         "k": len(legs) - 1 if len(legs) >= 3 else None, "odds": round(odds, 2), "p": round(p, 5), "ev": round(ev, 4)}
    jacks.append(j)
    NEW_JACK.append(j)


def jack_stats(jacks):
    done = [j for j in jacks if j.get("done")]
    st = {"n": len(done), "won": 0, "profit": 0, "last": []}
    for j in done:
        ret = j.get("express_ret", 0) + j.get("system_ret", 0)
        cost = j["stake"] * (2 if j.get("k") else 1)
        st["won"] += (j.get("express_ret", 0) > 0) or (j.get("system_ret", 0) > 0)
        st["profit"] += ret - cost
    for j in sorted(done, key=lambda j: j["at"], reverse=True)[:4]:
        n = len(j["legs"])
        line = f"{'✅' if j.get('express_ret') else '❌'} {fmt_time(j['at'])}: {j['hits']}/{n} o'tdi · ekspress @{j['odds']:.1f}"
        if j.get("k"):
            line += f" · sistema {j['k']}/{n}: {'+' if j['system_ret'] > j['stake'] else ''}{money(j['system_ret'] - j['stake'])}"
        st["last"].append(line)
    return st


def jack_msg(j):
    n = len(j["legs"])
    lines = [f"💎 Yangi jekpot ({n} ta ✅ tanlov):", ""]
    for i, l in enumerate(j["legs"], 1):
        lines.append(f"{i}. {l['m']} · {fmt_time(l['time'])}\n   {l['pick']} @{l['odds']:.2f} ({short_book(l['book'])})")
    lines += ["", f"🎰 Ekspress: @{j['odds']:.1f}, o'tish ehtimoli {j['p']*100:.2f}%, virtual {money(j['stake'])}"]
    if j.get("k"):
        lines.append(f"🎲 Sistema {j['k']}/{n}: virtual {money(j['stake'])}")
    lines.append("Bot natijani o'zi tekshiradi. Batafsil: 💎 Jekpot")
    return "\n".join(lines)


def write_stats(preds, signals):
    st = compute_stats(preds, signals)
    with open(STATS_PY, "w") as f:
        f.write("# Avtomatik yaratiladi (scripts/track.py). Qo'lda o'zgartirmang.\n")
        f.write("STATS = " + pprint.pformat(st, width=100, sort_dicts=False) + "\n")
    return st


def previous(key, default):
    try:
        sys.path.insert(0, os.path.join(ROOT, "api"))
        from _stats import STATS
        return STATS.get(key, default)
    except Exception:
        return default


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
            UPCOMING.update(previous("upcoming", {}))
            META["upcoming_at"] = previous("upcoming_at", None)
            JSTATS.update(previous("jackpots", {}))
            st = write_stats(preds, previous_signals())
        return

    newly = settle(preds, key)
    signals = snapshot(preds, key)
    save(preds)
    jacks = load_jack()
    jdone = jack_settle(jacks, preds)
    JSTATS.update(jack_stats(jacks))
    st = write_stats(preds, signals)
    jack_create(jacks, st)
    with open(JACK, "w") as f:
        json.dump(jacks, f, ensure_ascii=False, indent=0)

    chat = env("CHAT_ID")
    print(f"Yangi natijalar: {len(newly)}, signallar: {len(signals)}, jami: {st['matches']}")
    if not chat:
        print("CHAT_ID yo'q — Telegramga yuborilmadi")
        return
    msg = ["📊 Kunlik hisobot"]
    if newly:
        msg.append("\n" + "\n".join(result_line(p) for p in sorted(newly, key=lambda p: p["time"])[:20]))
    settled_c = [p for p in newly if p.get("coupon")]
    if settled_c:
        res = [coupon_result(p) for p in settled_c]
        msg.append(f"\n📝 Kupon: {sum(w for w, _ in res)}/{len(res)} o'tdi, natija "
                   f"{'+' if sum(x for _, x in res) > 0 else ''}{money(sum(x for _, x in res))}")
    for j in jdone:
        n = len(j["legs"])
        line = f"\n💎 Jekpot: {j['hits']}/{n} o'tdi — ekspress {'✅ +' + money(j['express_ret'] - j['stake']) if j['express_ret'] else '❌'}"
        if j.get("k"):
            line += f", sistema {j['k']}/{n}: {'+' if j['system_ret'] > j['stake'] else ''}{money(j['system_ret'] - j['stake'])}"
        msg.append(line)
    msg.append("\n" + format_short(st))
    send(chat, "\n".join(msg))
    for j in NEW_JACK:
        send(chat, jack_msg(j))
    if NEW_COUPON:
        send(chat, "📝 Yangi kupon (ordinar):\n\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(NEW_COUPON, 1))
             + "\n\nBotdagi 📝 Kupon tugmasida ham bor.")
    # Signallar alohida yuborilmaydi — kupon ularni o'z ichiga oladi (🔔 Signallar tugmasida ko'rish mumkin)


if __name__ == "__main__":
    main()
