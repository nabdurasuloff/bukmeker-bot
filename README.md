# Koeffitsiyent tahlilchi Telegram bot (Firebase + GitHub)

Bot Firebase Cloud Functions'da 24/7 ishlaydi. Kodni GitHub'ga yuklasangiz,
GitHub Actions uni avtomatik ravishda Firebase'ga joylaydi va Telegram webhook'ni ulaydi.

```
Telegram ──► Cloud Function "telegram" ──► The Odds API
                     │                         │
                     └── Firestore (kesh, obunachilar, kredit)
Cloud Scheduler (har 6 soat) ──► Cloud Function "avto" ──► obunachilarga signal
```

## Fayllar
- `functions/main.py`: bot va avto signal funksiyalari
- `functions/prognoz.py`: hisob-kitoblar (marja, EV, arbitraj, Puasson)
- `.github/workflows/deploy.yml`: avtomatik deploy
- `firebase.json`: Firebase sozlamasi

## O'rnatish (bir marta)

### 1. Firestore yoqish
Firebase Console → loyihangiz → **Build → Firestore Database → Create database**.
Joylashuv uchun `eur3` yoki `europe-west`, rejim uchun **Production** ni tanlang.

### 2. Service account kaliti (GitHub Firebase'ga kirishi uchun)
Google Cloud Console (console.cloud.google.com) → shu loyiha → **IAM & Admin → Service Accounts → Create service account**.
Nomi masalan `github-deploy`. Unga quyidagi rollarni bering:
- **Editor**
- **Cloud Functions Admin**
- **Service Account User**

Yaratilgan accountni oching → **Keys → Add key → Create new key → JSON**. Fayl yuklab olinadi.

### 3. GitHub repo
Yangi **Private** repo yarating, masalan `bukmeker-bot`, va shu papkadagi barcha fayllarni yuklang.
`.github/workflows/deploy.yml` ham bo'lishi shart. Brauzerda yuklashda ko'rinmay qolsa,
uni **Add file → Create new file** orqali yarating: nomiga `.github/workflows/deploy.yml` deb yozib, ichiga faylning matnini qo'ying.

### 4. GitHub Secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Nomi | Qiymati |
|---|---|
| `FIREBASE_PROJECT_ID` | Firebase loyiha ID si (Project settings'da ko'rinadi) |
| `GCP_SA_KEY` | 2-qadamdagi JSON faylning **butun** matni |
| `BOT_TOKEN` | @BotFather bergan token |
| `ODDS_API_KEY` | the-odds-api.com kaliti |
| `TG_SECRET` | o'zingiz o'ylab topgan uzun so'z, faqat harf, raqam, `_` va `-` (masalan `MeningBotim_2026_xK9q`) |

### 5. Ishga tushirish
Repo → **Actions → "Firebase'ga joylash" → Run workflow**.
Jarayon 3–5 daqiqa davom etadi. Oxirgi qadamda `"ok":true` ko'rinsa, webhook ulangan bo'ladi.
Telegramda botingizga `/start` yozing.

Keyin `main` branch'ga har safar o'zgarish yuklaganingizda bot o'zi yangilanadi.

## Sozlamalar (`functions/main.py` boshida)
- `CACHE_MIN = 30`: bir liga ma'lumoti necha daqiqa saqlanadi (API kreditini tejaydi)
- `MIN_EV = 0.02`: signal chegarasi (2%)
- `AUTO_LEAGUES`: avto signal tekshiradigan ligalar
- Avto signal oralig'i `avto` funksiyasidagi `schedule="every 6 hours"` qatorida

## Narx
Bunday kichik bot uchun Cloud Functions, Firestore va Scheduler odatda bepul limit ichida qoladi.
Ehtiyot uchun Google Cloud → **Billing → Budgets & alerts** bo'limida masalan $5 lik ogohlantirish qo'ying.

## Muammo bo'lsa
- **Deploy "permission denied" desa:** xatoda ko'rsatilgan rolni service account'ga qo'shing.
- **Bot javob bermasa:** Firebase Console → Functions → `telegram` → **Logs** bo'limini tekshiring.
- **Kredit tugasa:** API 401/429 qaytaradi va bot "o'yin topilmadi" deydi. Oy boshida kredit tiklanadi.

⚠️ Bu statistikani o'rganish vositasi. Musbat EV yutishni kafolatlamaydi.
