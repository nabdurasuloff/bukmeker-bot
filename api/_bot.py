"""Bot mantiqi (Vercel funksiyalari va GitHub Actions uchun umumiy)."""
import os

import requests

from _prognoz import analyse, report, fetch, fmt_time, verdict_core, verdict_short
from _model import blend, elo_info, load as load_elo

REGION = "eu"
MIN_EV = 0.02
MAX_MATCHES = 8

LEAGUES = {
    "soccer_epl": "🏴 Angliya Premer-ligasi",
    "soccer_spain_la_liga": "🇪🇸 La Liga",
    "soccer_italy_serie_a": "🇮🇹 Seriya A",
    "soccer_germany_bundesliga": "🇩🇪 Bundesliga",
    "soccer_france_ligue_one": "🇫🇷 Liga 1",
    "soccer_uefa_champs_league": "🏆 Chempionlar ligasi",
    "basketball_nba": "🏀 NBA",
    "basketball_euroleague": "🏀 Yevroliga",
}
SIGNAL_LEAGUES = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "basketball_nba"]

MAIN_KB = {"keyboard": [[{"text": "🧠 Tahlil: kim yutadi?"}],
                        [{"text": "📋 Ligalar"}, {"text": "🎾 Tennis"}],
                        [{"text": "🏦 1xBet reytingi"}],
                        [{"text": "📝 Kupon"}, {"text": "🔔 Signallar"}],
                        [{"text": "🧮 Hisob-kitob"}, {"text": "📊 Natijalar"}],
                        [{"text": "💳 Kredit"}, {"text": "🆔 Mening ID"}],
                        [{"text": "❓ Yordam"}]],
           "resize_keyboard": True}

HELP = (
    "ℹ️ Ko'rsatkichlar:\n\n"
    "• Adolatli ehtimol — bukmeker marjasi olib tashlangan ehtimol (asosan Pinnacle bo'yicha).\n"
    "• Adolatli koeffitsiyent = 1 / ehtimol.\n"
    "• EV — eng yaxshi koeffitsiyentning adolatli narxdan farqi. Musbat bo'lsa, koeffitsiyent \"qimmat\".\n"
    "• Arbitraj — barcha natijalarga tikkanda foyda qoladigan holat.\n"
    "• Kutilgan gollar — koeffitsiyentlardan Puasson modeli orqali hisoblangan.\n\n"
    "Har bir liga yoki turnir so'rovi 1 API kredit. \"Signallar\" va \"Natijalar\" kunlik saqlangan ma'lumotni ko'rsatadi (0 kredit), "
    "\"🔄 Hozir qayta tekshirish\" — 4 kredit. Betfair/Matchbook narxlari komissiya chegirilgan holda. "
    "Bot har kuni prognozlarni yozib, o'yindan keyin tekshiradi.\n\n"
    "⚠️ Bu statistikani o'rganish vositasi. Musbat EV yutishni kafolatlamaydi."
)


def my_bookies():
    """Siz o'ynaydigan bukmekerlar (Vercel/GitHub'da MY_BOOKIES, vergul bilan). Standart: 1xBet."""
    return [x.strip() for x in (os.environ.get("MY_BOOKIES") or "1xBet").split(",") if x.strip()]


def env(name):
    return os.environ.get(name, "").strip()


def tg(method, **data):
    try:
        return requests.post(f"https://api.telegram.org/bot{env('BOT_TOKEN')}/{method}",
                             json=data, timeout=20).json()
    except Exception as e:
        print("Telegram xatosi:", e)
        return {}


def send(chat, text, buttons=None, keyboard=None):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) > 3900:
            parts.append(cur)
            cur = ""
        cur += block + "\n\n"
    parts.append(cur)
    for i, p in enumerate(parts):
        extra = {}
        if i == len(parts) - 1:
            if buttons:
                extra["reply_markup"] = {"inline_keyboard": buttons}
            elif keyboard:
                extra["reply_markup"] = keyboard
        tg("sendMessage", chat_id=chat, text=p.strip() or "—", **extra)


def league_buttons():
    return [[{"text": n, "callback_data": f"lg:{k}"}] for k, n in LEAGUES.items()]


def upcoming_only(events):
    """Boshlanib ketgan o'yinlarni olib tashlaydi (ularning narxi eskirgan)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()[:19]
    return [e for e in events if (e.get("commence_time") or "")[:19] > now]


def analysed(league, limit=None):
    events, _ = fetch(env("ODDS_API_KEY"), league, REGION)
    events = upcoming_only(events)
    events = sorted(events, key=lambda e: e.get("commence_time", ""))[:limit]
    res = [a for a in (analyse(e) for e in events) if a]
    res.sort(key=lambda a: a["time"])
    return res


def is_signal(a):
    return any(b["ev"] > MIN_EV for b in a["best"])


def signals_text(leagues=SIGNAL_LEAGUES):
    """Jonli tekshiruv (har liga 1 kredit). Faqat MY_BOOKIES koeffitsiyentlari baholanadi."""
    found = []
    for lg in leagues:
        events, _ = fetch(env("ODDS_API_KEY"), lg, REGION)
        for e in upcoming_only(events):
            a = analyse(e, only=my_bookies())
            if a and is_signal(a):
                found.append(f"[{LEAGUES.get(lg, lg)}]\n" + report(a))
    if not found:
        return ""
    return f"🔔 {len(found)} ta signal ({', '.join(my_bookies())}):\n\n" + "\n\n".join(found)


def saved_signals():
    """Kunlik kuzatuv saqlagan signallar — kredit sarflamaydi."""
    st = load_stats()
    sig = st.get("signals") if st else None
    if sig is None:
        return "Saqlangan signallar hali yo'q (kunlik kuzatuv har kuni 12:37 da yangilanadi)."
    when = fmt_time(st.get("updated", ""))
    if not sig:
        return f"🔕 {when} holatiga {', '.join(my_bookies())} bo'yicha signal yo'q edi."
    return f"🔔 {len(sig)} ta signal ({when} holati, {', '.join(my_bookies())}):\n\n" + "\n\n".join(sig)


BOOKIES = ["1xBet"]


def bookie_buttons():
    return [[{"text": "🏦 " + b, "callback_data": f"bm:{i}"}] for i, b in enumerate(BOOKIES)]


def bookie_league_buttons(i):
    return [[{"text": n, "callback_data": f"bl:{i}:{k}"}] for k, n in LEAGUES.items()]


def bookie_report(i, league, top_n=10):
    """Tanlangan bukmeker koeffitsiyentlarini ehtimoli yuqoridan pastga saralaydi."""
    bname = BOOKIES[i]
    events, _ = fetch(env("ODDS_API_KEY"), league, REGION)
    events = upcoming_only(events)
    rows = []
    for e in events:
        a = analyse(e)
        if not a:
            continue
        mine = next((b for b in a["books"] if bname.lower() in b["name"].lower()), None)
        if not mine:
            continue
        lbl = ["1", "X", "2"] if a["draw"] else ["1", "2"]
        names = [a["home"], "Durang", a["away"]] if a["draw"] else [a["home"], a["away"]]
        for k in range(len(lbl)):
            if lbl[k] == "X":
                continue
            p, odd = a["fair"][k], mine["odds"][k]
            rows.append({"p": p, "odd": odd, "ev": p * odd - 1, "pick": names[k], "lbl": lbl[k],
                         "match": f"{a['home']} — {a['away']}", "time": a["time"]})
    if not rows:
        return f"🏦 {bname}: bu ligada uning koeffitsiyentlari topilmadi (yoki yaqin o'yin yo'q)."
    rows.sort(key=lambda r: -r["p"])
    out = [f"🏦 {bname} — {LEAGUES.get(league, league)}",
           "Ehtimoli eng yuqori natijalar (adolatli ehtimol bo'yicha):", ""]
    for n, r in enumerate(rows[:top_n], 1):
        mark = "✅ qimmat narx" if r["ev"] > 0 else ("➖ deyarli adolatli" if r["ev"] > -0.03 else "🔻 arzon narx")
        out.append(f"{n}. {r['pick']} ({r['lbl']}) — {r['p']*100:.1f}%\n"
                   f"   {bname}: {r['odd']:.2f} | adolatli: {1/r['p']:.2f} | EV {r['ev']*100:+.1f}% {mark}\n"
                   f"   {r['match']}, {fmt_time(r['time'])}")
    out.append("\nℹ️ Yuqori ehtimol — past koeffitsiyent degani. Foyda faqat ✅ (EV musbat) "
               "narxlarda uzoq muddatda bo'lishi mumkin; kafolat yo'q.")
    return "\n".join(out)


def money(x):
    return f"{int(round(x)):,} so'm".replace(",", " ")


def calc_items(lg, limit=10):
    """Yaqin o'yinlar: har biri uchun eng ehtimolli natija, uning ehtimoli va 1xBet koeffitsiyenti."""
    st = load_stats()
    items = (st.get("upcoming") or {}).get(lg)
    src = "kunlik ma'lumot, 0 kredit"
    if not items:
        events, _ = fetch(env("ODDS_API_KEY"), lg, REGION)
        items = []
        for e in upcoming_only(events):
            a = analyse(e)
            mine = analyse(e, only=my_bookies())
            if a:
                items.append({"home": a["home"], "away": a["away"], "time": a["time"], "draw": a["draw"],
                              "fair": a["fair"],
                              "mine": [[b["odds"], b["book"]] for b in mine["best"]] if mine else None})
        src = "jonli, 1 kredit"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()[:19]
    elo = load_elo()
    picks = []
    for m in sorted(items, key=lambda m: m["time"]):
        if m["time"][:19] <= now or not m.get("mine"):
            continue
        ei = elo_info(lg, m["home"], m["away"], elo) if m["draw"] else None
        pr = blend(ei["p"] if ei else None, m["fair"], ei["w"] if ei else 0.5)
        k = max(range(len(pr)), key=lambda i: pr[i])
        names = [m["home"], "Durang", m["away"]] if m["draw"] else [m["home"], m["away"]]
        picks.append({"m": f"{m['home']} — {m['away']}", "pick": names[k], "p": pr[k],
                      "odds": m["mine"][k][0]})
        if len(picks) >= limit:
            break
    return picks, src


def calc_text(lg, stake=10000, rate=75):
    import math
    picks, _ = calc_items(lg)
    if not picks:
        return f"{LEAGUES.get(lg, lg)}: 1xBet koeffitsiyenti bor yaqin o'yin topilmadi."
    n = len(picks)
    total = stake * n
    avg = sum(p["odds"] for p in picks) / n
    real = sum(p["p"] for p in picks) / n
    exp = sum(stake * p["p"] * p["odds"] for p in picks) - total
    win = stake * n * rate / 100 * avg - total
    need = math.ceil(n / avg - 1e-9)
    sign = lambda v: ("+" if v > 0 else "") + money(v)
    out = [f"🧮 {LEAGUES.get(lg, lg)} · {n} o'yin × {money(stake)} = {money(total)}", ""]
    out += [f"{i}. {p['pick']} @{p['odds']:.2f}" for i, p in enumerate(picks, 1)]
    out += ["",
            f"✅ {rate}% o'tsa: {sign(win)}",
            f"📈 Real kutilgan ({real*100:.0f}%): {sign(exp)}",
            f"⚖️ Zarar qilmaslik uchun: kamida {need} tasi o'tishi kerak"]
    if rate / 100 > real + 0.08:
        out.append(f"⚠️ {rate}% real emas — bu o'yinlar o'rtacha {real*100:.0f}% ehtimolli.")
    out += ["", "O'zgartirish: hisob 20000 80"]
    return "\n".join(out)


def calc_buttons(stake, rate):
    return [[{"text": LEAGUES[k], "callback_data": f"calc:{k}:{stake}:{rate}"}] for k in ANALYSIS_LEAGUES]


def coupon_text():
    st = load_stats()
    if not st:
        return "📝 Kupon hali tayyor emas (kunlik tahlil 12:37 da)."
    bank = st.get("bank", 100000)
    op = st.get("coupon_open") or []
    out = [f"📝 Kupon (1xBet, ordinar) — bank {money(bank)}", ""]
    if op:
        out += [f"{i}. {c['label']}" for i, c in enumerate(op, 1)]
        out.append(f"\nJami: {len(op)} ta, {money(sum(c['stake'] for c in op))}. "
                   f"Hammasi o'tsa: +{money(sum(c['win'] for c in op))}")
    else:
        out.append("Hozir ochiq kupon yo'q — 1xBet'da foydali narx topilmadi. Bu normal holat.")
    c = st.get("coupon") or {}
    if c.get("n"):
        roi = c["profit"] / c["staked"] * 100 if c["staked"] else 0
        out.append(f"\n📒 Oldingi kuponlar: {c['won']}/{c['n']} o'tdi · tikilgan {money(c['staked'])} · "
                   f"natija {'+' if c['profit'] > 0 else ''}{money(c['profit'])} ({roi:+.1f}%)")
        out += c.get("last", [])
    out.append("\nℹ️ Summalar Kelly bo'yicha (bitta tikish bankning 5% idan oshmaydi). Kupon har kuni 12:37 da yangilanadi. "
               "Qiymatli tikishlar ko'pincha o'tmaydi — natijani 50+ kupondan keyin baholang.")
    return "\n".join(out)


def format_short(st):
    """Kunlik xabar uchun qisqa xulosa (to'liq statistika — 📊 Natijalar tugmasida)."""
    vd = (st or {}).get("verdicts") or {}
    out = []
    a, b, c = vd.get("fav", {}), vd.get("value", {}), vd.get("total", {})
    if a.get("n"):
        out.append(f"🎯 Prognozlar: {a['ok']}/{a['n']} to'g'ri ({a['ok']/a['n']*100:.0f}%, kutilgan {a['p']/a['n']*100:.0f}%)")
    if b.get("n"):
        out.append(f"💰 Qiymatli tikishlar: {b['ok']}/{b['n']}, natija {b['profit']:+.1f} birlik")
    else:
        out.append("💰 Qiymatli tikishlar: hali yo'q")
    if c.get("n"):
        out.append(f"⚽ Total: {c['ok']}/{c['n']} to'g'ri")
    k = (st or {}).get("kelly")
    if k and k.get("bets"):
        out.append(f"🏦 Kelly bank: {k['bank']:,} so'm".replace(",", " "))
    c = (st or {}).get("coupon") or {}
    if c.get("n"):
        out.append(f"📝 Kuponlar jami: {c['won']}/{c['n']} o'tdi, {'+' if c['profit'] > 0 else ''}{money(c['profit'])}")
    out.append(f"Jami {st.get('matches', 0)} ta o'yin tekshirildi. Batafsil: 📊 Natijalar")
    return "\n".join(out)


def format_stats(st):
    """Kuzatuv statistikasini o'qiladigan matnga aylantiradi."""
    if not st or not st.get("matches"):
        pend = st.get("pending", 0) if st else 0
        h = elo_history()
        return ("📊 Hali yakunlangan o'yinlar yo'q. Bot har kuni prognozlarni yozib boradi, "
                f"o'yinlar tugagach natija shu yerda chiqadi. (Kutilmoqda: {pend})" + (f"\n\n{h}" if h else ""))
    f, v = st["fav"], st["value"]
    out = [f"📊 Prognozlar natijasi — {st['matches']} ta o'yin (kutilmoqda: {st['pending']})", ""]
    vd = st.get("verdicts")
    if vd:
        out.append("🎯 Bot xulosalari qanchalik to'g'ri chiqdi:")
        a = vd["fav"]
        if a["n"]:
            out.append(f"  Prognoz (kim yutadi): {a['ok']}/{a['n']} to'g'ri — {a['ok']/a['n']*100:.0f}% "
                       f"(bot kutgani {a['p']/a['n']*100:.0f}%)")
        b = vd["value"]
        if b["n"]:
            out.append(f"  Qiymatli tikishlar: {b['ok']}/{b['n']} yutdi, natija {b['profit']:+.1f} birlik "
                       f"(ROI {b['profit']/b['n']*100:+.1f}%)")
        c = vd["total"]
        if c["n"]:
            out.append(f"  Total (2.5): {c['ok']}/{c['n']} to'g'ri — {c['ok']/c['n']*100:.0f}%")
        if vd["skip"]:
            out.append(f"  O'tkazib yuborilgan: {vd['skip']} ta")
        out.append("")
    out.append(f"🎯 Favorit (eng yuqori ehtimolli natija) {f['hit']}/{f['n']} marta to'g'ri chiqdi: "
               f"{f['hit']/f['n']*100:.0f}% (bot kutgani: {f['p']/f['n']*100:.0f}%)")
    out.append("\nEhtimollar to'g'riligi (kalibrovka):")
    for b in st["buckets"]:
        out.append(f"  {b['lo']*100:.0f}–{b['hi']*100:.0f}%: kutilgan {b['p']/b['n']*100:.0f}%, "
                   f"haqiqatda {b['hit']/b['n']*100:.0f}% ({b['n']} ta)")
    out.append(f"\nBrier ko'rsatkichi: {st['brier']} (qancha kichik bo'lsa, shuncha aniq)")
    bk = ", ".join(st.get("bookies") or my_bookies())
    out.append(f"\n💡 Virtual tikish ({bk} narxida, 1 birlikdan, pul tikilmagan):")
    nb = f.get("bets", 0)
    if nb:
        out.append(f"  Har doim favoritga: {f['profit']:+.1f} birlik (ROI {f['profit']/nb*100:+.1f}%, {nb} ta)")
    else:
        out.append(f"  {bk} narxi bor o'yinlar hali yakunlanmagan")
    if v["n"]:
        out.append(f"  Faqat ✅ signallarga: {v['hit']}/{v['n']} yutdi, {v['profit']:+.1f} birlik "
                   f"(ROI {v['profit']/v['n']*100:+.1f}%)")
    else:
        out.append("  ✅ signallar hali yakunlanmagan")
    k = st.get("kelly")
    if k:
        if k["bets"]:
            sp = lambda x: f"{x:,}".replace(",", " ")
            out.append(f"\n🏦 Kelly bank (100 000 so'mdan boshlangan, chorak-Kelly): {sp(k['bank'])} so'm "
                       f"({k['bets']} ta tikish; eng yuqori {sp(k['peak'])}, eng past {sp(k['low'])})")
        else:
            out.append("\n🏦 Kelly bank: 100 000 so'm (hali signal yakunlanmagan)")
    c = st.get("clv")
    if c:
        if c["n"]:
            out.append(f"📈 CLV (signal narxi yopilish narxidan yaxshimi): o'rtacha {c['avg']*100:+.1f}%, "
                       f"{c['pos']}/{c['n']} tasida yaxshi. Musbat CLV — haqiqiy ustunlik belgisi.")
        else:
            out.append("📈 CLV: signal berilgan o'yinlar boshlanishi bilan hisoblanadi")
    e = st.get("elo")
    if e and e.get("n"):
        better = "Model" if e["brier_elo"] < e["brier_mkt"] else "Bozor"
        out.append(f"\n🧠 Elo modeli vs bozor ({e['n']} ta futbol o'yini): favoritni topdi {e['hit_elo']} vs "
                   f"{e['hit_mkt']}; Brier {e['brier_elo']} vs {e['brier_mkt']} → aniqroq: {better}")
    ev = elo_history()
    if ev:
        out.append(ev)
    if st.get("recent"):
        out.append("\nOxirgi o'yinlar:")
        for r in st["recent"]:
            out.append(f"  {'✅' if r['fav'] == r['res'] else '❌'} {r['m']} {r['score']} "
                       f"(favorit {r['p']*100:.0f}%)")
    out.append(f"\nYangilangan: {fmt_time(st['updated'])} · Kamida 100+ o'yindan keyin xulosa qiling.")
    return "\n".join(out)


def elo_history():
    """Elo modelining tarixiy sinovi (o'tgan mavsumlar) — model qurilganda hisoblanadi."""
    L = (load_elo().get("leagues") or {})
    ev = [v["eval"] for v in L.values() if v.get("eval")]
    if not ev:
        return ""
    n = sum(x["n"] for x in ev)
    ae = sum(x["acc_elo"] * x["n"] for x in ev) / n
    am = sum(x["acc_mkt"] * x["n"] for x in ev) / n
    le = sum(x["ll_elo"] * x["n"] for x in ev) / n
    lm = sum(x["ll_mkt"] * x["n"] for x in ev) / n
    bl = [x for x in ev if x.get("ll_blend")]
    lb = sum(x["ll_blend"] * x["n"] for x in bl) / sum(x["n"] for x in bl) if bl else None
    ws = ", ".join(f"{x.get('w', 0)*100:.0f}%" for x in ev)
    line = (f"📚 Tarixiy sinov ({n} ta o'yin, {len(ev)} liga): favorit to'g'ri — model {ae*100:.0f}%, bozor {am*100:.0f}%. "
            f"Log-loss (kichigi aniqroq): model {le:.3f}, bozor {lm:.3f}")
    if lb:
        line += f", aralash {lb:.3f} (model vazni ligalar bo'yicha: {ws})"
    E = load_elo()
    if E.get("alpha") is not None:
        line += f". Reytingda xG ulushi: {(1-E['alpha'])*100:.0f}%"
    return line


def load_stats():
    try:
        from _stats import STATS
        return STATS
    except Exception:
        return {}


ANALYSIS_LEAGUES = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
                    "soccer_germany_bundesliga", "soccer_france_ligue_one", "soccer_uefa_champs_league",
                    "basketball_nba"]


def analysis_buttons():
    return [[{"text": LEAGUES[k], "callback_data": f"an:{k}"}] for k in ANALYSIS_LEAGUES]


def pct(p):
    return f"{p*100:.0f}%"


def analysis_item(lg, m, elo):
    """Sodda tahlil: ehtimollar va bitta xulosa."""
    draw = m["draw"]
    names = [m["home"], "Durang", m["away"]] if draw else [m["home"], m["away"]]
    ei = elo_info(lg, m["home"], m["away"], elo) if draw else None
    pm = m.get("fair")
    comb = blend(ei["p"] if ei else None, pm, ei["w"] if ei else 0.5)
    mo = [x[0] for x in m["mine"]] if m.get("mine") else None
    probs = " · ".join(f"{'durang' if names[i] == 'Durang' else names[i]} {pct(comb[i])}" for i in range(len(comb)))
    v = verdict_core(comb, comb, names, mo if pm else None, m.get("o25"))
    return (f"{'⚽' if draw else '🏀'} {m['home']} — {m['away']} · {fmt_time(m['time'])}\n"
            f"{probs}\n{verdict_short(v, names)}")


def analysis_text(lg, live=False, limit=10):
    st = load_stats()
    cache = (st.get("upcoming") or {}).get(lg) if not live else None
    src = ""
    if cache:
        items = cache
        src = f"(ma'lumot {fmt_time(st.get('upcoming_at', ''))} holatiga, 0 kredit)"
    else:
        events, _ = fetch(env("ODDS_API_KEY"), lg, REGION)
        items = []
        for e in sorted(upcoming_only(events), key=lambda e: e.get("commence_time", "")):
            a = analyse(e)
            if not a:
                continue
            mine = analyse(e, only=my_bookies())
            items.append({"home": a["home"], "away": a["away"], "time": a["time"], "draw": a["draw"],
                          "fair": a["fair"], "o25": a.get("over25"),
                          "mine": [[b["odds"], b["book"]] for b in mine["best"]] if mine else None})
        src = "(jonli, 1 kredit)"
    if not items:
        return f"{LEAGUES.get(lg, lg)}: yaqin o'yinlar topilmadi."
    elo = load_elo()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()[:19]
    items = [m for m in items if m["time"][:19] > now]
    if not items:
        return f"{LEAGUES.get(lg, lg)}: yaqin o'yinlar topilmadi (saqlanganlari boshlanib bo'lgan)."
    items = sorted(items, key=lambda m: m["time"])[:limit]
    head = [f"🧠 {LEAGUES.get(lg, lg)} — {len(items)} ta o'yin", "", ""]
    foot = ["", "ℹ️ 🎯 — bot xulosasi; ✅ — 1xBet narxi foydali. Ehtimol kafolat emas."]
    return (head[0] + "\n\n" + "\n\n".join(analysis_item(lg, m, elo) for m in items)
            + "\n\n" + foot[1])


def tennis_buttons():
    """Hozir o'tayotgan tennis turnirlari (bu so'rov kredit sarflamaydi)."""
    try:
        r = requests.get("https://api.the-odds-api.com/v4/sports",
                         params={"apiKey": env("ODDS_API_KEY")}, timeout=15)
        sports = [s for s in r.json() if s.get("group") == "Tennis" and s.get("active")]
    except Exception:
        sports = []
    return [[{"text": "🎾 " + s["title"], "callback_data": f"lg:{s['key']}"}] for s in sports[:12]]


def credits_left():
    # /sports so'rovi kredit sarflamaydi, lekin qolgan kreditni ko'rsatadi
    try:
        k = env("ODDS_API_KEY")
        if not k:
            return "❌ ODDS_API_KEY serverda yo'q"
        r = requests.get("https://api.the-odds-api.com/v4/sports",
                         params={"apiKey": k}, timeout=15)
        if r.status_code != 200:
            return (f"❌ API xatosi {r.status_code}: {r.text[:200]}\n"
                    f"(kalit {len(k)} belgi, '{k[:3]}…' bilan boshlanadi)")
        used = r.headers.get("x-requests-used", "?")
        return f"{r.headers.get('x-requests-remaining', '?')} (ishlatilgan: {used})"
    except Exception as e:
        return f"❌ Ulanish xatosi: {e}"


def handle_text(chat, text):
    t = text.strip().lower()
    if t.startswith("/start"):
        send(chat, "Salom! Men koeffitsiyent tahlilchi botman 📊\n"
                   "Ligani tanlang yoki signallarni ko'ring.\n\n"
                   f"Sizning chat ID: {chat}", keyboard=MAIN_KB)
    elif "tahlil" in t or "kim yutadi" in t:
        send(chat, "Qaysi ligani tahlil qilaylik?", analysis_buttons())
    elif "bukmeker" in t or "1xbet" in t or "reyting" in t:
        send(chat, "🏦 1xBet: ligani tanlang — ehtimoli yuqoridan pastga saralanadi:", bookie_league_buttons(0))
    elif "tennis" in t:
        btns = tennis_buttons()
        send(chat, "Turnirni tanlang:" if btns else "Hozir faol tennis turnirlari topilmadi.", btns or None)
    elif "liga" in t:
        send(chat, "Ligani tanlang:", league_buttons())
    elif "signal" in t:
        send(chat, saved_signals(),
             [[{"text": "🔄 Hozir qayta tekshirish (4 kredit)", "callback_data": "live_signals"}]])
    elif "hisob" in t:
        import re as _re
        nums = [int(x) for x in _re.findall(r"\d+", t.replace(" 000", "000"))]
        stake = nums[0] if nums and nums[0] >= 100 else 10000
        rate = nums[1] if len(nums) > 1 and 0 < nums[1] <= 100 else 75
        send(chat, f"🧮 Har biriga {money(stake)}, o'tish {rate}% bo'yicha hisoblayman. Ligani tanlang:",
             calc_buttons(stake, rate))
    elif "kupon" in t:
        send(chat, coupon_text())
    elif "natija" in t:
        send(chat, format_stats(load_stats()))
    elif "kredit" in t:
        send(chat, f"💳 API kreditidan qoldi: {credits_left()}")
    elif "id" in t:
        send(chat, f"🆔 Sizning chat ID: {chat}\n(GitHub'dagi CHAT_ID secret'iga shu raqamni yozing)")
    elif "yordam" in t or t.startswith("/help"):
        send(chat, HELP)
    else:
        send(chat, "Buyruqni tushunmadim. /start ni bosing.", keyboard=MAIN_KB)


def handle_callback(cb):
    chat = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data.startswith("an:") or data.startswith("anl:"):
        live = data.startswith("anl:")
        lg = data.split(":", 1)[1]
        send(chat, analysis_text(lg, live=live),
             [[{"text": "🔄 Jonli yangilash (1 kredit)", "callback_data": f"anl:{lg}"}]] if not live else None)
        return
    if data.startswith("calc:"):
        _, lg, stake, rate = data.split(":")
        send(chat, calc_text(lg, int(stake), int(rate)))
        return
    if data == "live_signals":
        send(chat, "⏳ Tekshiryapman...")
        send(chat, signals_text() or
             f"Hozircha {', '.join(my_bookies())} bo'yicha signal yo'q (EV > {MIN_EV*100:.0f}%).")
        return
    if data.startswith("bm:"):
        i = int(data[3:])
        send(chat, f"🏦 {BOOKIES[i]} tanlandi. Ligani tanlang:", bookie_league_buttons(i))
        return
    if data.startswith("bl:"):
        _, i, lg = data.split(":", 2)
        send(chat, bookie_report(int(i), lg), bookie_league_buttons(int(i)))
        return
    if data.startswith("lg:"):
        lg = data[3:]
        name = LEAGUES.get(lg, lg.replace("tennis_", "🎾 ").replace("_", " ").upper())
        kb = None if lg.startswith("tennis_") else league_buttons()
        res = analysed(lg, MAX_MATCHES)
        if not res:
            send(chat, "Bu yerda yaqin o'yinlar topilmadi.", kb)
            return
        send(chat, f"{name} — {len(res)} ta o'yin\n\n"
             + "\n\n".join(report(a) for a in res), kb)


OWNER_ID = "6282774829"


def allowed_ids():
    """Botdan foydalanishga ruxsat berilganlar (ALLOWED_IDS, vergul bilan). Standart: egasi."""
    raw = os.environ.get("ALLOWED_IDS") or os.environ.get("CHAT_ID") or OWNER_ID
    return {x.strip() for x in raw.split(",") if x.strip()}


def handle_update(u):
    msg = u.get("message") or (u.get("callback_query") or {}).get("message") or {}
    chat = msg.get("chat", {}).get("id")
    if chat is not None and str(chat) not in allowed_ids():
        # Begona foydalanuvchi: API'ga murojaat qilinmaydi, kredit sarflanmaydi
        if "message" in u:
            tg("sendMessage", chat_id=chat,
               text=f"🔒 Bu shaxsiy bot. Sizning ID: {chat}\nKirish uchun bot egasiga murojaat qiling.")
        elif "callback_query" in u:
            tg("answerCallbackQuery", callback_query_id=u["callback_query"]["id"], text="🔒 Ruxsat yo'q")
        return
    try:
        if "message" in u and "text" in u["message"]:
            handle_text(u["message"]["chat"]["id"], u["message"]["text"])
        elif "callback_query" in u:
            handle_callback(u["callback_query"])
    except Exception as e:
        print("Xato:", e)
