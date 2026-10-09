# 🌸 Cute Romantic Date Invitation Website

Fully functional, mobile-responsive romantic date invitation site  
**Flask + SQLite / Neon Postgres + Cloudinary + Vercel ready**

## Features

- Cute multi-step flow: Invitation → Surprise → Choose Date → Payment → QR → Confirmation
- Playful runaway “NO” button
- Date selection with validation
- NPR 1,000 playful confirmation fee
- **QR upload at `/upload`** (file picker + Cloudinary)
- Payment proof screenshots also go to Cloudinary
- Email notifications (no admin panel)
- Simple secret verification link for the owner
- Soft pastel aesthetic, floating hearts/flowers, fully responsive
- Deploy-ready for **Vercel + Neon + Cloudinary**

---

## Quick Start (Local)

```bash
cd date-invitation
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env (SECRET_KEY, mail, Cloudinary, etc.)
python app.py
```

Open → http://127.0.0.1:5000

---

## Upload your Payment QR (`/upload`)

Just open:

```
http://127.0.0.1:5000/upload
```

1. Choose the QR image with the file picker
2. Click **Upload QR**

No secret key required.  
It is saved to Cloudinary (or local fallback) and becomes live immediately.

---

## Cloudinary Setup (Recommended for Vercel)

1. Free account → [cloudinary.com](https://cloudinary.com)
2. Dashboard → copy **Cloud name**, **API Key**, **API Secret**
3. Add to `.env` / Vercel Environment Variables:

```env
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

When set:
- QR images uploaded via `/upload` go to Cloudinary
- Payment proof screenshots go to Cloudinary
- No local disk needed → works perfectly on Vercel

If Cloudinary is missing, files fall back to `static/uploads/`.

---

## Environment Variables

```env
SECRET_KEY=replace_with_a_long_random_string
DATABASE_URL=sqlite:///dates.db
# Neon example:
# DATABASE_URL=postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require

MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_gmail_app_password
OWNER_EMAIL=your_email@gmail.com

PAYMENT_AMOUNT=1000
PAYMENT_RECIPIENT=Your Name
PAYMENT_QR_PATH=static/images/payment-qr.png

CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
```

---

## Payment Verification (No Admin Panel)

When someone submits payment proof you get an email.

Visit:

```
https://your-domain.com/verify/<REQUEST_ID>/<YOUR_SECRET_KEY>
```

Click **Mark as Verified** → the user’s page shows “IT’S A DATE!!”.

---

## Deploy on Vercel + Neon (Deploy Ready)

### 1. Neon Database
- Create project at [neon.tech](https://neon.tech)
- Copy the connection string → set as `DATABASE_URL`

### 2. Cloudinary
- Set the three `CLOUDINARY_*` variables

### 3. Vercel
1. Push this folder to a GitHub repo
2. Import the repo in [vercel.com](https://vercel.com)
3. Add **all** environment variables from `.env`
4. Deploy

`vercel.json` is already included.  
After deploy, open:

```
https://your-app.vercel.app/upload
```

to set your real QR code.

### Notes for production
- Uploaded files live on Cloudinary (persistent)
- Sessions work via Flask secret key
- Rate limiting is in-memory (fine for personal use)
- Never commit `.env`

---

## Project Structure

```
date-invitation/
├── app.py
├── models.py
├── requirements.txt
├── .env.example
├── vercel.json
├── templates/
│   ├── index.html … confirmation.html
│   ├── upload.html / upload_login.html   ← /upload page
│   └── verify.html
└── static/
    ├── css/style.css
    ├── js/main.js
    ├── images/
    └── uploads/
```

Made with love 💕
