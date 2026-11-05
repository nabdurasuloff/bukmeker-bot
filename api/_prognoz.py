#!/usr/bin/env python3
"""
Real vaqtda koeffitsiyent tahlilchisi (o'rganish uchun).

The Odds API dan futbol o'yinlari koeffitsiyentlarini oladi va har bir o'yin uchun:
  * har bir bukmekerning marjasini,
  * marjasiz "adolatli" ehtimollarni (bukmekerlar konsensusi),
  * eng yaxshi koeffitsiyent va uning kutilmasini (EV),
  * arbitraj ("vilka") bor-yo'qligini,
  * koeffitsiyentlardan teskari hisoblangan kutilgan gollarni (Puasson)
    va eng ehtimolli hisoblarni chiqaradi.

Ishga tushirish:
  pip install requests
  python prognoz_bot.py --demo                      # namuna ma'lumot bilan, kalitsiz
  python prognoz_bot.py --key SIZNING_KALIT         # haqiqiy ma'lumot
  python prognoz_bot.py --key KALIT --interval 60   # har 60 daqiqada yangilash
  python prognoz_bot.py --list-leagues --key KALIT  # mavjud ligalar ro'yxati

Telegramga yuborish (ixtiyoriy):
  --tg-token BOT_TOKEN --tg-chat CHAT_ID

Bepul kalit: https://the-odds-api.com (oyiga 500 kredit; 1 so'rov = 1 liga x 1 hudud).
"""
import argparse
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

API = "https://api.the-odds-api.com/v4"

DEFAULT_LEAGUES = ["soccer_epl", "soccer_spain_la_liga"]

DEMO = [
    {
        "home_team": "Arsenal", "away_team": "Chelsea",
        "commence_time": "2026-11-08T17:30:00Z",
        "bookmakers": [
            {"title": "Pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.95}, {"name": "Chelsea", "price": 4.10}, {"name": "Draw", "price": 3.70}]}]},
            {"title": "1xBet", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.92}, {"name": "Chelsea", "price": 4.30}, {"name": "Draw", "price": 3.60}]}]},
            {"title": "Bet365", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.90}, {"name": "Chelsea", "price": 4.00}, {"name": "Draw", "price": 3.75}]}]},
        ],
    },
    {
        "home_team": "Barcelona", "away_team": "Sevilla",
        "commence_time": "2026-11-09T20:00:00Z",
        "bookmakers": [
            {"title": "Pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Barcelona", "price": 1.40}, {"name": "Sevilla", "price": 8.00}, {"name": "Draw", "price": 5.20}]}]},
            {"title": "Marathonbet", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Barcelona", "price": 1.44}, {"name": "Sevilla", "price": 7.40}, {"name": "Draw", "price": 5.00}]}]},
            {"title": "Betway", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Barcelona", "price": 1.38}, {"name": "Sevilla", "price": 8.75}, {"name": "Draw", "price": 5.10}]}]},
        ],
    },
]


# ---------- Matematika ----------

def pois(k, lam):
    return lam ** k * math.exp(-lam) / math.factorial(k)


def score_matrix(lh, la, n=8):
    return [[pois(i, lh) * pois(j, la) for j in range(n + 1)] for i in range(n + 1)]


def outcome_probs(m):
    p1 = sum(m[i][j] for i in range(len(m)) for j in range(len(m)) if i > j)
    px = sum(m[i][i] for i in range(len(m)))
    p2 = sum(m[i][j] for i in range(len(m)) for j in range(len(m)) if i < j)
    s = p1 + px + p2
    return p1 / s, px / s, p2 / s


def implied_lambdas(p1, p2):
    """Bukmeker ehtimollariga eng mos keladigan kutilgan gollarni topadi (to'r bo'yicha qidiruv)."""
    best, err = (1.3, 1.1), 9.0
    steps = [x / 20 for x in range(4, 81)]  # 0.20 ... 4.00
    for lh in steps:
        for la in steps:
            q1, _, q2 = outcome_probs(score_matrix(lh, la, 7))
            e = (q1 - p1) ** 2 + (q2 - p2) ** 2
            if e < err:
                best, err = (lh, la), e
    # aniqlashtirish
    lh0, la0 = best
    for lh in [lh0 + d / 100 for d in range(-5, 6)]:
        for la in [la0 + d / 100 for d in range(-5, 6)]:
            if lh <= 0 or la <= 0:
                continue
            q1, _, q2 = outcome_probs(score_matrix(lh, la, 8))
            e = (q1 - p1) ** 2 + (q2 - p2) ** 2
            if e < err:
                best, err = (lh, la), e
    return best


# Birjalar yutuqdan komissiya oladi — koeffitsiyent shunga qarab kamaytiriladi
COMMISSION = {"betfair": 0.05, "matchbook": 0.02, "smarkets": 0.02}


def devig_power(odds):
    """Marjani "darajali" usulda olib tashlaydi: p_i = (1/o_i)^k, yig'indi = 1.
    Oddiy (proporsional) usuldan farqli o'laroq, autsayderlarga ko'proq marja yuklaydi —
    bukmekerlar marjani asosan autsayderlarga qo'yadi (favorit-autsayder effekti)."""
    inv = [1 / o for o in odds]
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(x ** k for x in inv) > 1:
            lo = k
        else:
            hi = k
    q = [x ** ((lo + hi) / 2) for x in inv]
    t = sum(q)
    return [x / t for x in q]


def net_odds(name, odd):
    c = next((v for k, v in COMMISSION.items() if k in name.lower()), 0)
    return round(1 + (odd - 1) * (1 - c), 3) if c else odd


def analyse(event, only=None):
    """3 natijali (futbol: 1-X-2) yoki 2 natijali (tennis, basketbol: 1-2) bozorni tahlil qiladi.

    only — faqat shu bukmekerlar (nomidagi so'z bo'yicha) koeffitsiyentlari "eng yaxshi" deb olinadi.
    """
    home, away = event["home_team"], event["away_team"]
    # Xokkey: natija qo'shimcha vaqt bilan keladi, shuning uchun faqat 2 natijali (OT bilan) narxlar olinadi.
    # 60 daqiqalik (durangli) narxlar e'tiborga olinmaydi.
    two_way_only = (event.get("sport_key") or "").startswith("icehockey")
    has_draw = (not two_way_only) and any(o.get("name") == "Draw"
                   for b in event.get("bookmakers", []) for mk in b.get("markets", [])
                   if mk.get("key") == "h2h" for o in mk.get("outcomes", []))
    keys = [home, "Draw", away] if has_draw else [home, away]
    n = len(keys)
    books = []
    for b in event.get("bookmakers", []):
        for mk in b.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            prices = {o["name"]: o["price"] for o in mk.get("outcomes", [])}
            if two_way_only and "Draw" in prices:
                continue
            if all(k in prices and prices[k] > 1 for k in keys):
                name = b.get("title", "?")
                odds = [net_odds(name, prices[k]) for k in keys]
                inv = [1 / o for o in odds]
                over = sum(inv)
                books.append({"name": name, "odds": odds,
                              "fair": devig_power(odds), "margin": over - 1})
    if not books:
        return None

    # Konsensus: Pinnacle bo'lsa o'shani (eng "o'tkir" bozor), aks holda o'rtacha
    sharp = [b for b in books if b["name"].lower() == "pinnacle"]
    if sharp:
        fair, source = sharp[0]["fair"], "Pinnacle"
    else:
        fair = [sum(b["fair"][i] for b in books) / len(books) for i in range(n)]
        source = f"{len(books)} ta bukmeker o'rtachasi"

    pool = books
    if only:
        pool = [b for b in books if any(o.lower() in b["name"].lower() for o in only)]
        if not pool:
            return None
    best = []
    for i in range(n):
        top = max(pool, key=lambda b: b["odds"][i])
        odd = top["odds"][i]
        best.append({"odds": odd, "book": top["name"], "ev": fair[i] * odd - 1})
    arb_sum = sum(1 / x["odds"] for x in best)

    res = {"home": home, "away": away, "time": event.get("commence_time", ""),
           "books": books, "fair": fair, "source": source, "best": best,
           "arb": arb_sum, "draw": has_draw, "lam": None}
    if has_draw:  # gollar modeli faqat futbolga mos
        lh, la = implied_lambdas(fair[0], fair[2])
        m = score_matrix(lh, la)
        cells = sorted(((i, j, m[i][j]) for i in range(len(m)) for j in range(len(m))),
                       key=lambda x: -x[2])
        res.update(lam=(lh, la), top=cells[:5],
                   over25=sum(m[i][j] for i in range(len(m)) for j in range(len(m)) if i + j > 2),
                   btts=sum(m[i][j] for i in range(1, len(m)) for j in range(1, len(m))))
    return res


# ---------- Chiqarish ----------

def fmt_time(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        tashkent = timezone(timedelta(hours=5))
        return t.astimezone(tashkent).strftime("%d.%m %H:%M")
    except Exception:
        return iso


VALUE_EV, FAV_P, TOTAL_P = 0.02, 0.60, 0.60


def short_book(b):
    return {"Marathon Bet": "Marathon"}.get(b, b)


def verdict_core(probs, fair, names, my_odds=None, over25=None, book="1xBet"):
    """book — bitta nom yoki har natija uchun nomlar ro'yxati (eng yaxshi narx qaysi bukmekerda)."""
    """Bitta aniq xulosa: qiymatli tikish / prognoz / o'tkazib yuborish (+ total)."""
    n = len(probs)
    v = {"type": "skip", "i": None, "p": None, "odds": None, "ev": None, "total": None}
    if my_odds:
        evs = [fair[i] * my_odds[i] - 1 for i in range(n)]
        j = max(range(n), key=lambda i: evs[i])
        if evs[j] > VALUE_EV:
            v.update(type="value", i=j, p=round(fair[j], 4), odds=my_odds[j], ev=round(evs[j], 4),
                     book=book[j] if isinstance(book, list) else book)
    if v["type"] == "skip":
        k = max(range(n), key=lambda i: probs[i])
        if probs[k] >= FAV_P:
            v.update(type="fav", i=k, p=round(probs[k], 4), odds=my_odds[k] if my_odds else None)
    if over25 is not None:
        side, p = ("under", 1 - over25) if over25 < 0.5 else ("over", over25)
        if p >= TOTAL_P:
            v["total"] = {"side": side, "p": round(p, 4)}
    nm = names[v["i"]] if v["i"] is not None else None
    if v["type"] == "value":
        what = "durang" if nm == "Durang" else f"{nm} g'alabasi"
        risk = "ko'pincha yutqazadi, lekin" if v["p"] < 0.5 else "yutish ehtimoli yuqori va"
        txt = (f"🎯 Xulosa: {what} — {v['odds']:.2f} ({short_book(v['book'])}). Qiymatli tikish: ehtimol {v['p']*100:.0f}%, "
               f"{risk} narx foydali (+{v['ev']*100:.1f}%).")
    elif v["type"] == "fav":
        what = "durang" if nm == "Durang" else f"{nm} yutadi"
        txt = (f"🎯 Xulosa: {what} ({v['p']*100:.0f}%). Bu prognoz; narx foydali emas, "
               f"pul tikish uchun afzallik yo'q.")
    else:
        txt = "🎯 Xulosa: aniq favorit ham, foydali narx ham yo'q — o'tkazib yuborish."
    if v["total"]:
        t = v["total"]
        txt += f"\n🎯 Total: 2.5 dan {'kam' if t['side'] == 'under' else 'ko‘p'} gol ({t['p']*100:.0f}%)."
    v["text"] = txt
    return v


def verdict_short(v, names):
    """Bir qatorli xulosa."""
    nm = None if v["i"] is None else ("durang" if names[v["i"]] == "Durang" else names[v["i"]])
    if v["type"] == "value":
        t = (f"🎯 ✅ {nm} @{v['odds']:.2f} ({short_book(v.get('book', ''))}) — foydali narx "
             f"(+{v['ev']*100:.0f}%), ehtimol {v['p']*100:.0f}%")
    elif v["type"] == "fav":
        t = f"🎯 {nm} yutadi ({v['p']*100:.0f}%)" if nm != "durang" else f"🎯 Durang ({v['p']*100:.0f}%)"
    else:
        t = "🎯 O'tkazib yuborish"
    if v.get("total"):
        tt = v["total"]
        t += f" · Total: {'kam' if tt['side'] == 'under' else 'ko‘p'} ({tt['p']*100:.0f}%)"
    return t


def my_best(a, mine=None):
    """Sizning bukmekerlaringiz ichidan har natija uchun eng yaxshi narx: (koeffitsiyentlar, bukmekerlar)."""
    mine = mine or MINE
    mbs = [b for b in a["books"] if any(m.lower() in b["name"].lower() for m in mine)]
    if not mbs:
        return None, None
    n = len(a["fair"])
    best = [max(mbs, key=lambda b: b["odds"][i]) for i in range(n)]
    return [b["odds"][i] for i, b in enumerate(best)], [b["name"] for b in best]


def my_odds_of(a, mine=None):
    return my_best(a, mine)[0]


def verdict(a, mine=None):
    names = [a["home"], "Durang", a["away"]] if a.get("draw", True) else [a["home"], a["away"]]
    odds, books = my_best(a, mine)
    return verdict_core(a["fair"], a["fair"], names, odds, a.get("over25"), books or "")


def check_verdict(v, result, score=None):
    """Xulosa to'g'ri chiqdimi: (natija_ok yoki None, total_ok yoki None)."""
    ok = None if v.get("i") is None else (v["i"] == result)
    tok = None
    if v.get("total") and score:
        try:
            g = sum(int(x) for x in score.split(":"))
            tok = (g < 2.5) if v["total"]["side"] == "under" else (g > 2.5)
        except Exception:
            tok = None
    return ok, tok


def report(a, mine=None):
    """Sodda ko'rinish: kim yutadi, hisoblar, total, eng yaxshi narx (1xBet / Marathon)."""
    draw = a.get("draw", True)
    fair = a["fair"]
    names = [a["home"], "Durang", a["away"]] if draw else [a["home"], a["away"]]
    icon = "⚽" if draw else "🏟"
    k = max(range(len(fair)), key=lambda i: fair[i])
    rest = ", ".join(f"{'durang' if names[i] == 'Durang' else names[i]} {fair[i]*100:.0f}%"
                     for i in range(len(fair)) if i != k)
    out = [f"{icon} {a['home']} — {a['away']} · {fmt_time(a['time'])}"]
    if names[k] == "Durang":
        out.append(f"• Eng ehtimolli: durang, {fair[k]*100:.0f}%. ({rest})")
    else:
        out.append(f"• Kim yutadi: {names[k]}, {fair[k]*100:.0f}%. ({rest})")
    if a.get("lam"):
        out.append("• Eng ehtimolli hisoblar: " + ", ".join(f"{i}:{j} ({p*100:.0f}%)" for i, j, p in a["top"][:2]))
        out.append(f"• Total 2.5: kam — {(1-a['over25'])*100:.0f}%, ko'p — {a['over25']*100:.0f}%. "
                   f"Ikkala jamoa uradi — {a['btts']*100:.0f}%")
    mo, bks = my_best(a, mine)
    out.append("• Eng yaxshi narx: " + (" / ".join(f"{o:.2f} ({short_book(b)})" for o, b in zip(mo, bks))
                                       if mo else "koeffitsiyent yo'q"))
    out.append(verdict(a, mine)["text"])
    return "\n".join(out)


# ---------- Ma'lumot olish ----------

# Faqat shu bukmekerlar olinadi: Pinnacle — adolatli baho uchun, 1xBet va Marathon Bet — siz o'ynaydigan bukmekerlar.
# (10 tagacha bukmeker = 1 kredit.) O'zgartirish: ODDS_BOOKMAKERS muhit o'zgaruvchisi, masalan "pinnacle,onexbet,marathonbet"
BOOKMAKERS = os.environ.get("ODDS_BOOKMAKERS", "pinnacle,onexbet,marathonbet")
# Siz o'ynaydigan bukmekerlar (nomidagi so'z bo'yicha)
MINE = [x.strip() for x in (os.environ.get("MY_BOOKIES") or "1xBet,Marathon Bet").split(",") if x.strip()]


def fetch(key, league, region):
    import requests
    params = {"apiKey": key, "markets": "h2h", "oddsFormat": "decimal"}
    if BOOKMAKERS:
        params["bookmakers"] = BOOKMAKERS
    else:
        params["regions"] = region
    r = requests.get(f"{API}/sports/{league}/odds", timeout=20, params=params)
    left = r.headers.get("x-requests-remaining")
    if r.status_code != 200:
        print(f"[{league}] xato {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return [], left
    return r.json(), left


def list_leagues(key):
    import requests
    r = requests.get(f"{API}/sports", params={"apiKey": key}, timeout=20)
    r.raise_for_status()
    for s in r.json():
        if s["group"] == "Soccer":
            print(f"{s['key']:40} {s['title']}")


def send_tg(token, chat, text):
    import requests
    for i in range(0, len(text), 3800):
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                      data={"chat_id": chat, "text": text[i:i + 3800]})


def run_once(args):
    events, left = [], None
    if args.demo:
        events = DEMO
    else:
        for lg in args.leagues:
            ev, left = fetch(args.key, lg, args.region)
            events += ev
    results = [r for r in (analyse(e) for e in events) if r]
    results = results[: args.limit]
    if args.only_signals:
        results = [r for r in results if r["arb"] < 1 or any(b["ev"] > args.min_ev for b in r["best"])]

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = f"📊 Hisobot {stamp} — {len(results)} ta o'yin\n\n" + "\n\n".join(report(r) for r in results)
    if left:
        text += f"\n\n(API: {left} kredit qoldi)"
    print(text)
    if args.tg_token and args.tg_chat and results:
        send_tg(args.tg_token, args.tg_chat, text)


def main():
    p = argparse.ArgumentParser(description="Koeffitsiyent tahlilchisi")
    p.add_argument("--key", help="The Odds API kaliti")
    p.add_argument("--demo", action="store_true", help="namuna ma'lumot bilan ishlash")
    p.add_argument("--leagues", nargs="+", default=DEFAULT_LEAGUES)
    p.add_argument("--region", default="eu", help="eu, uk, us, au")
    p.add_argument("--interval", type=int, default=0, help="har N daqiqada takrorlash (0 = bir marta)")
    p.add_argument("--limit", type=int, default=15, help="nechta o'yin ko'rsatilsin")
    p.add_argument("--only-signals", action="store_true", help="faqat arbitraj yoki musbat EV bo'lganlar")
    p.add_argument("--min-ev", type=float, default=0.02, help="EV chegarasi (0.02 = 2%%)")
    p.add_argument("--list-leagues", action="store_true")
    p.add_argument("--tg-token"); p.add_argument("--tg-chat")
    args = p.parse_args()

    if args.list_leagues:
        return list_leagues(args.key)
    if not args.demo and not args.key:
        p.error("--key kerak (yoki --demo)")
    while True:
        run_once(args)
        if not args.interval:
            break
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
