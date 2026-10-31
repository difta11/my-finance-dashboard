# Pengaturan AI

Fitur AI opsional. Masukkan setting di Vercel **Project → Settings → Environment Variables** (atau `.env` lokal); jangan menaruh API key pada frontend atau repository.

Gemini:

```env
AI_ENABLED=true
AI_PROVIDER=gemini
GEMINI_API_KEY=isi-key-di-environment
GEMINI_MODEL=gemini-3.8-flash
```

OpenAI:

```env
AI_ENABLED=true
AI_PROVIDER=openai
OPENAI_API_KEY=isi-key-di-environment
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Kategori aktif dan akun yang tersedia dikirim ke model pada saat parsing. Hasil teks atau struk tetap berupa draft yang harus diperiksa sebelum disimpan. Foto struk yang disimpan bersama transaksi masuk ke Firebase Storage.

Jika tidak ingin memakai AI, atur `AI_ENABLED=false`; transaksi manual tetap tersedia. Pemakaian AI dapat dikenai biaya dan batas kuota dari penyedia API.
