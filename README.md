# My Finance Dashboard

Dashboard keuangan pribadi berbahasa Indonesia. Aplikasi Flask berjalan sebagai Vercel Function, data ledger tersimpan di Cloud Firestore, dan foto struk baru tersimpan di Google Drive akun yang dihubungkan. UI sudah responsif untuk ponsel.

## Deploy ke Vercel

1. Gunakan project Firebase yang sudah ada dan pastikan **Cloud Firestore** aktif. Tidak perlu membuat database kedua.
2. Buat service account untuk backend di project yang sama, unduh JSON key, lalu simpan di luar folder/repository publik. Encode JSON itu ke Base64 untuk nilai `FIREBASE_SERVICE_ACCOUNT_BASE64` (contoh PowerShell di [SETUP.md](SETUP.md)). Base64 hanya encoding, jadi nilainya tetap rahasia.
3. Push isi folder ini ke repository GitHub. Pastikan file `.env` dan semua file service account tetap diabaikan Git.
4. Di Vercel pilih **Add New → Project**, import repository, lalu atur environment variables yang dijelaskan di [DEPLOYMENT.md](DEPLOYMENT.md). Framework Flask terdeteksi dari `app.py` dan dependensi berasal dari `requirements.txt`.
5. Deploy, lalu buka URL Vercel dari ponsel atau perangkat lain.

Setiap deployment adalah dashboard satu pemilik dengan satu kata sandi. Orang yang men-deploy salinan repository mereka sendiri memakai project Firebase dan rahasia milik mereka. Jangan bagikan kata sandi dashboard: semua pengunjung yang bisa login ke satu deployment melihat ledger yang sama.

**Foto struk:** foto baru disimpan di folder **My Finance Dashboard** pada Google Drive yang dihubungkan. Aktifkan Google Drive API, buat OAuth client tipe Web application, lalu isi `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, `GOOGLE_DRIVE_REDIRECT_URI`, dan `GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY` di `.env` atau Vercel. Saat login ke dashboard, buka Tanya AI dan pilih **Hubungkan**. Foto diunggah ke Drive ketika transaksi disimpan; tautan file di tabel transaksi hanya dapat dibuka oleh akun Drive pemiliknya. `FIREBASE_STORAGE_BUCKET` hanya diperlukan untuk membuka struk lama yang sebelumnya tersimpan di Firebase Storage.

## Pengaturan lokal

Salin `.env.example` menjadi `.env`, isi kredensial Firebase, Google Drive OAuth, kata sandi, dan rahasia sesi. Install Python 3.12 dan dependensi dari `requirements.txt`, kemudian jalankan `python app.py`. Firebase tetap menjadi penyimpanan; aplikasi tidak membuat database lokal.

Panduan Firebase dan Vercel: [SETUP.md](SETUP.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [Pengaturan AI](AI_SETUP.md). Lisensi: [MIT](LICENSE).

## Fitur

- Dashboard, transaksi, akun, kategori kustom, Budgetting, Wish, dan Behaviour.
- Pola pengeluaran harian, jam transaksi tersibuk, perbandingan weekday/weekend, dan rata-rata pengeluaran harian.
- Budget per kategori pengeluaran dengan nominal terpakai, sisa dana, dan persentase otomatis.
- Koleksi Firestore `budgets` dibuat otomatis saat budget pertama disimpan; tidak perlu dibuat manual.
- Saldo, transfer antar-akun, filter rentang waktu, grafik aset/pengeluaran, dan CSV.
- Draft transaksi dari teks atau foto struk melalui Gemini atau OpenAI.
- Firebase Admin SDK hanya berjalan di backend; kredensial tidak dikirim ke browser.
