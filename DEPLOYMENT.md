# Deploy ke Vercel

## 1. Siapkan GitHub

Push isi folder aplikasi ini sehingga `app.py`, `requirements.txt`, `vercel.json`, dan `public/` berada di root repository. Repository boleh publik: `.gitignore` mengecualikan `.env`, database lokal, kunci service account, serta file struk uji.

## 2. Siapkan Firebase

Pakai project Firebase yang sudah memiliki Firestore; aplikasi tidak membuat project/database baru. Firebase Storage opsional untuk foto struk. Jika dipakai, aktifkan bucket, siapkan billing account Blaze dan budget alert. Buat service account di project yang sama dan siapkan nilai Base64-nya mengikuti [SETUP.md](SETUP.md). Simpan key dengan aman.

## 3. Import ke Vercel

Di Vercel pilih **Add New → Project**, hubungkan repository GitHub, gunakan root folder repository, dan biarkan Vercel mendeteksi aplikasi Flask dari `app.py`. Jangan set output directory statis. `public/` berisi aset frontend dan `prompts/` disertakan dalam Function lewat `vercel.json`.

Tambahkan environment variables berikut sebelum deploy pertama:

| Variable | Nilai |
| --- | --- |
| `DASHBOARD_PASSWORD` | Kata sandi kuat dan unik untuk login dashboard |
| `SESSION_SECRET` | Secret acak minimal 32 karakter, tetap sama setiap deploy |
| `FIREBASE_SERVICE_ACCOUNT_BASE64` | JSON service account yang di-encode Base64 |
| `FIREBASE_STORAGE_BUCKET` | Opsional: nama bucket persis dari Firebase Console, untuk foto struk |
| `MAX_UPLOAD_MB` | `4` (batas aman untuk payload Function Vercel) |
| `AI_ENABLED` | `false` atau `true` |

Jika AI diaktifkan, tambahkan `AI_PROVIDER=gemini` serta `GEMINI_API_KEY` dan `GEMINI_MODEL`, atau gunakan `AI_PROVIDER=openai`, `OPENAI_API_KEY`, dan `OPENAI_MODEL`. API key AI hanya disimpan di Vercel Environment Variables. Terapkan secret untuk environment **Production** dan **Preview** secara terpisah bila keduanya dipakai.

Klik **Deploy**. Setiap perubahan yang di-push ke branch production akan memicu deployment baru. Domain `.vercel.app` bisa dibuka dari ponsel tanpa laptop pengembang menyala.

## Model keamanan dan batas penggunaan

- Satu deployment memakai satu kata sandi bersama dan satu ledger. Jangan gunakan satu deployment untuk pengguna yang tidak saling percaya; pemisahan per-user memerlukan Firebase Authentication dan aturan isolasi data.
- Admin SDK berjalan hanya di server dan melewati Firestore/Storage Security Rules. Jangan membagikan kredensial service account atau menaruhnya di repository publik.
- Vercel membatasi body request Function hingga 4.5 MB. Aplikasi membatasi foto struk sampai 4 MB dan menampilkan batas efektif dari `MAX_UPLOAD_MB`.
- Foto yang sudah dikaitkan dengan transaksi disimpan di `receipts/`. Foto draft yang tidak jadi disimpan berada di `draft-receipts/`; buat aturan lifecycle Storage untuk menghapus objek dengan prefix itu yang berumur lebih dari satu hari agar draft terbengkalai dibersihkan otomatis.
- Firestore dan Storage menimbulkan biaya sesuai pemakaian dan kuota project. Aktifkan billing/alerts sesuai kebutuhan dan buat backup berkala.

## Pemulihan data lama

Migrator tersedia di `scripts/migrate_sqlite_to_firestore.py`. Ia menyalin ledger dan foto dari database SQLite lama ke Firestore/Storage tanpa menghapus sumber. Baca [SETUP.md](SETUP.md) sebelum menjalankannya. Kredensial Firebase harus sudah diatur dan target harus kosong.
