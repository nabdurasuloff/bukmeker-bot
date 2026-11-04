"""Bot mantiqi (Vercel funksiyalari va GitHub Actions uchun umumiy)."""
import os

import requests

from _prognoz import analyse, report, fetch, fmt_time

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
SIGNAL_LEAGUES = ["soccer_epl", "soccer_spain_la_liga", "soccer_uefa_champs_league"]

MAIN_KB = {"keyboard": [[{"text": "📋 Ligalar"}, {"text": "🎾 Tennis"}],
                        [{"text": "🏦 Mening bukmekerim"}],
                        [{"text": "🔔 Signallar"}, {"text": "📊 Natijalar"}],
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
    "\"🔄 Hozir qayta tekshirish\" — 3 kredit. Betfair/Matchbook narxlari komissiya chegirilgan holda. "
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


def analysed(league, limit=None):
    events, _ = fetch(env("ODDS_API_KEY"), league, REGION)
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
        for e in events:
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


BOOKIES = ["1xBet", "Marathon Bet", "Pinnacle", "Betfair", "William Hill",
           "Unibet", "Betsson", "888sport", "Bet365"]


def bookie_buttons():
    return [[{"text": "🏦 " + b, "callback_data": f"bm:{i}"}] for i, b in enumerate(BOOKIES)]


def bookie_league_buttons(i):
    return [[{"text": n, "callback_data": f"bl:{i}:{k}"}] for k, n in LEAGUES.items()]


def bookie_report(i, league, top_n=10):
    """Tanlangan bukmeker koeffitsiyentlarini ehtimoli yuqoridan pastga saralaydi."""
    bname = BOOKIES[i]
    events, _ = fetch(env("ODDS_API_KEY"), league, REGION)
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


def format_stats(st):
    """Kuzatuv statistikasini o'qiladigan matnga aylantiradi."""
    if not st or not st.get("matches"):
        pend = st.get("pending", 0) if st else 0
        return ("📊 Hali yakunlangan o'yinlar yo'q. Bot har kuni prognozlarni yozib boradi, "
                f"o'yinlar tugagach natija shu yerda chiqadi. (Kutilmoqda: {pend})")
    f, v = st["fav"], st["value"]
    out = [f"📊 Prognozlar natijasi — {st['matches']} ta o'yin (kutilmoqda: {st['pending']})", ""]
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
        out.append("  ✅ signallar hali bo'lmagan")
    if st.get("recent"):
        out.append("\nOxirgi o'yinlar:")
        for r in st["recent"]:
            out.append(f"  {'✅' if r['fav'] == r['res'] else '❌'} {r['m']} {r['score']} "
                       f"(favorit {r['p']*100:.0f}%)")
    out.append(f"\nYangilangan: {fmt_time(st['updated'])} · Kamida 100+ o'yindan keyin xulosa qiling.")
    return "\n".join(out)


def load_stats():
    try:
        from _stats import STATS
        return STATS
    except Exception:
        return {}


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
    elif "bukmeker" in t:
        send(chat, "Qaysi bukmekerda o'ynaysiz?", bookie_buttons())
    elif "tennis" in t:
        btns = tennis_buttons()
        send(chat, "Turnirni tanlang:" if btns else "Hozir faol tennis turnirlari topilmadi.", btns or None)
    elif "liga" in t:
        send(chat, "Ligani tanlang:", league_buttons())
    elif "signal" in t:
        send(chat, saved_signals(),
             [[{"text": "🔄 Hozir qayta tekshirish (3 kredit)", "callback_data": "live_signals"}]])
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


def handle_update(u):
    try:
        if "message" in u and "text" in u["message"]:
            handle_text(u["message"]["chat"]["id"], u["message"]["text"])
        elif "callback_query" in u:
            handle_callback(u["callback_query"])
    except Exception as e:
        print("Xato:", e)
