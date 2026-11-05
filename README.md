# Koeffitsiyent tahlilchi Telegram bot (Vercel + GitHub Actions, bepul)

- **Vercel** (bepul Hobby tarifi, karta kerak emas) — bot: tugmalar, ligalar, signallar, kredit
- **GitHub Actions** — har kuni prognozlarni yozadi, o'yindan keyin natija bilan solishtiradi, hisobot va signallarni Telegramga yuboradi

## Fayllar
- `api/index.py` — Vercel kirish nuqtasi: Telegram webhook va `/api/setup`
- `api/_bot.py` — bot mantiqi
- `api/_prognoz.py` — hisob-kitoblar (marja, EV, arbitraj, Puasson)
- `scripts/track.py` + `.github/workflows/track.yml` — kunlik prognoz, natija tekshiruvi va hisobot
- `data/predictions.json` — yozilgan prognozlar va natijalar, `api/_stats.py` — statistika (avtomatik)

## O'rnatish
1. **vercel.com** → *Continue with GitHub* → **Add New → Project** → `bukmeker-bot` reposini **Import**.
2. **Environment Variables** bo'limiga 3 ta qiymat qo'shing: `BOT_TOKEN`, `ODDS_API_KEY`, `TG_SECRET`. Keyin **Deploy**.
3. Deploy tugagach, brauzerda oching: `https://<loyiha-nomi>.vercel.app/api/setup?key=<TG_SECRET>`
   "✅ Webhook ulandi" chiqsa, Telegramda botga `/start` yozing.
4. Avto signal uchun: bot `/start` javobida chat ID ingizni ko'rsatadi. GitHub → Settings → Secrets → Actions'ga
   `CHAT_ID` (shu raqam), `BOT_TOKEN`, `ODDS_API_KEY` qo'shing. Sinash: Actions → **Avto signal** → Run workflow.

Kodni GitHub'ga yuklasangiz, Vercel o'zi yangilaydi.

## Kupon
Bot qiymatli tikishlarni 📝 Kupon'ga yozadi (summa — Kelly, bank `BANK` secret'idan, standart 100 000 so'm) va o'yindan keyin o'tgan/o'tmaganini hisoblaydi. Avtomatik tikish yo'q — kuponni 1xBet'ga o'zingiz kiritasiz.

## Kredit sarfi
Kunlik kuzatuv: 4 liga × 1 kredit + natijalar uchun ~2 kredit har bir ligaga ≈ kuniga 8–12 (oyiga ~300).
Botdagi har bir liga tugmasi = 1 kredit, "Signallar" = 3 kredit, "Natijalar" = 0.
Bepul tarifda oyiga 500 kredit bor. Ligalar ro'yxati: `scripts/track.py` dagi `TRACK`.

⚠️ Bu statistikani o'rganish vositasi. Musbat EV yutishni kafolatlamaydi.
