# Koeffitsiyent tahlilchi Telegram bot (Vercel + GitHub Actions, bepul)

- **Vercel** (bepul Hobby tarifi, karta kerak emas) — bot: tugmalar, ligalar, signallar, kredit
- **GitHub Actions** — har 6 soatda avto signal sizning Telegramingizga

## Fayllar
- `api/telegram.py` — Telegram webhook (Vercel funksiyasi)
- `api/setup.py` — webhook'ni bir marta ulash sahifasi
- `api/_bot.py` — bot mantiqi
- `api/_prognoz.py` — hisob-kitoblar (marja, EV, arbitraj, Puasson)
- `scripts/signal.py` + `.github/workflows/signal.yml` — avto signal

## O'rnatish
1. **vercel.com** → *Continue with GitHub* → **Add New → Project** → `bukmeker-bot` reposini **Import**.
2. **Environment Variables** bo'limiga 3 ta qiymat qo'shing: `BOT_TOKEN`, `ODDS_API_KEY`, `TG_SECRET`. Keyin **Deploy**.
3. Deploy tugagach, brauzerda oching: `https://<loyiha-nomi>.vercel.app/api/setup?key=<TG_SECRET>`
   "✅ Webhook ulandi" chiqsa, Telegramda botga `/start` yozing.
4. Avto signal uchun: bot `/start` javobida chat ID ingizni ko'rsatadi. GitHub → Settings → Secrets → Actions'ga
   `CHAT_ID` (shu raqam), `BOT_TOKEN`, `ODDS_API_KEY` qo'shing. Sinash: Actions → **Avto signal** → Run workflow.

Kodni GitHub'ga yuklasangiz, Vercel o'zi yangilaydi.

## Kredit sarfi
Har bir liga tugmasi = 1 kredit, "Signallar" = 3 kredit, avto signal kuniga 4 × 3 = 12 kredit (oyiga ~360).
Bepul tarifda oyiga 500 kredit bor. Kerak bo'lsa `signal.yml` dagi oraliqni `*/12` ga o'zgartiring.

⚠️ Bu statistikani o'rganish vositasi. Musbat EV yutishni kafolatlamaydi.
