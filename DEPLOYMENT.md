# Deploy ke Vercel

## 1. Siapkan GitHub

Push isi folder aplikasi ini sehingga `app.py`, `requirements.txt`, `vercel.json`, dan `public/` berada di root repository. Repository boleh publik: `.gitignore` mengecualikan `.env`, database lokal, kunci service account, serta file struk uji.

## 2. Siapkan Firebase

Pakai project Firebase yang sudah memiliki Firestore; aplikasi tidak membuat project/database baru. Firebase Storage tidak diperlukan untuk foto baru. Bucket hanya diperlukan bila ingin membuka struk lama yang tersimpan di Firebase Storage. Buat service account di project yang sama dan siapkan nilai Base64-nya mengikuti [SETUP.md](SETUP.md). Simpan key dengan aman.

## 3. Siapkan Google Drive

Di Google Cloud Console, pilih project, aktifkan **Google Drive API**, lalu buat OAuth client bertipe **Web application**. Tambahkan URI callback lokal `http://127.0.0.1:5000/auth/google-drive/callback` dan URI production persis `https://DOMAIN-VERCEL-ANDA/auth/google-drive/callback` ke **Authorized redirect URIs**. Buat OAuth consent screen dan tambahkan akun Google Anda sebagai test user. Selama status consent screen masih **Testing**, token dapat kedaluwarsa setelah 7 hari; untuk pemakaian terus-menerus, ubah aplikasi ke **In production** sesuai alur Google.

Buat satu kunci Fernet untuk mengenkripsi refresh token yang disimpan di Firestore:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Simpan hasilnya sebagai `GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY` dan gunakan nilai yang sama di local serta Vercel. Jangan commit secret ini.

## 4. Import ke Vercel

Di Vercel pilih **Add New → Project**, hubungkan repository GitHub, gunakan root folder repository, dan biarkan Vercel mendeteksi aplikasi Flask dari `app.py`. Jangan set output directory statis. `public/` berisi aset frontend dan `prompts/` disertakan dalam Function lewat `vercel.json`.

Tambahkan environment variables berikut sebelum deploy pertama:

| Variable | Nilai |
| --- | --- |
| `DASHBOARD_PASSWORD` | Kata sandi kuat dan unik untuk login dashboard |
| `SESSION_SECRET` | Secret acak minimal 32 karakter, tetap sama setiap deploy |
| `FIREBASE_SERVICE_ACCOUNT_BASE64` | JSON service account yang di-encode Base64 |
| `FIREBASE_STORAGE_BUCKET` | Opsional: hanya untuk membuka foto struk lama di Firebase Storage |
| `GOOGLE_DRIVE_CLIENT_ID` | OAuth Client ID dari Google Cloud Console |
| `GOOGLE_DRIVE_CLIENT_SECRET` | OAuth Client Secret; simpan sebagai secret |
| `GOOGLE_DRIVE_REDIRECT_URI` | `https://DOMAIN-VERCEL-ANDA/auth/google-drive/callback`, harus sama persis dengan URI OAuth |
| `GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY` | Kunci Fernet acak untuk mengenkripsi refresh token di Firestore |
| `MAX_UPLOAD_MB` | `4` (batas aman untuk payload Function Vercel) |
| `AI_ENABLED` | `false` atau `true` |

Jika AI diaktifkan, tambahkan `AI_PROVIDER=gemini` serta `GEMINI_API_KEY` dan `GEMINI_MODEL`, atau gunakan `AI_PROVIDER=openai`, `OPENAI_API_KEY`, dan `OPENAI_MODEL`. API key AI hanya disimpan di Vercel Environment Variables. Terapkan secret untuk environment **Production** dan **Preview** secara terpisah bila keduanya dipakai.

Klik **Deploy**. Setiap perubahan yang di-push ke branch production akan memicu deployment baru. Domain `.vercel.app` bisa dibuka dari ponsel tanpa laptop pengembang menyala.

## Model keamanan dan batas penggunaan

- Satu deployment memakai satu kata sandi bersama dan satu ledger. Jangan gunakan satu deployment untuk pengguna yang tidak saling percaya; pemisahan per-user memerlukan Firebase Authentication dan aturan isolasi data.
- Admin SDK berjalan hanya di server dan melewati Firestore/Storage Security Rules. Jangan membagikan kredensial service account atau menaruhnya di repository publik.
- Vercel membatasi body request Function hingga 4.5 MB. Aplikasi membatasi foto struk sampai 4 MB dan menampilkan batas efektif dari `MAX_UPLOAD_MB`.
- Struk baru diunggah ke folder Google Drive milik akun yang dihubungkan hanya setelah transaksi disimpan. Token refresh dienkripsi dengan `GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY` sebelum disimpan di koleksi Firestore `integrations`. Foto Firebase Storage lama tetap dapat dibuka bila bucket lama dikonfigurasi.
- Firestore dan layanan cloud lain ditagih sesuai pemakaian dan kuota project. Aktifkan billing/alerts sesuai kebutuhan dan buat backup berkala.

## Pemulihan data lama

Migrator tersedia di `scripts/migrate_sqlite_to_firestore.py`. Ia menyalin ledger dan foto dari database SQLite lama ke Firestore/Storage tanpa menghapus sumber. Baca [SETUP.md](SETUP.md) sebelum menjalankannya. Kredensial Firebase harus sudah diatur dan target harus kosong.
