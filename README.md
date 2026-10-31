# My Finance Dashboard

Dashboard keuangan pribadi berbahasa Indonesia. Aplikasi Flask berjalan sebagai Vercel Function, data ledger tersimpan di Cloud Firestore, dan foto struk tersimpan di Firebase Storage. UI sudah responsif untuk ponsel.

## Deploy ke Vercel

1. Gunakan project Firebase yang sudah ada dan pastikan **Cloud Firestore** aktif. Tidak perlu membuat database kedua.
2. Buat service account untuk backend di project yang sama, unduh JSON key, lalu simpan di luar folder/repository publik. Encode JSON itu ke Base64 untuk nilai `FIREBASE_SERVICE_ACCOUNT_BASE64` (contoh PowerShell di [SETUP.md](SETUP.md)). Base64 hanya encoding, jadi nilainya tetap rahasia.
3. Push isi folder ini ke repository GitHub. Pastikan file `.env` dan semua file service account tetap diabaikan Git.
4. Di Vercel pilih **Add New → Project**, import repository, lalu atur environment variables yang dijelaskan di [DEPLOYMENT.md](DEPLOYMENT.md). Framework Flask terdeteksi dari `app.py` dan dependensi berasal dari `requirements.txt`.
5. Deploy, lalu buka URL Vercel dari ponsel atau perangkat lain.

Setiap deployment adalah dashboard satu pemilik dengan satu kata sandi. Orang yang men-deploy salinan repository mereka sendiri memakai project Firebase dan rahasia milik mereka. Jangan bagikan kata sandi dashboard: semua pengunjung yang bisa login ke satu deployment melihat ledger yang sama.

**Foto struk:** untuk menyimpan foto secara online, aktifkan Cloud Storage di project yang sama dan isi `FIREBASE_STORAGE_BUCKET`. Jika belum ingin memakai foto struk, Firestore dan dashboard tetap dapat digunakan tanpa Storage. Cloud Storage saat ini mensyaratkan paket Blaze (pay-as-you-go) untuk membuat dan memakai bucket; siapkan billing account dan budget alert.

## Pengaturan lokal

Salin `.env.example` menjadi `.env`, isi kredensial Firebase, kata sandi, dan rahasia sesi. Install Python 3.12 dan dependensi dari `requirements.txt`, kemudian jalankan `python app.py`. Firebase tetap menjadi penyimpanan; aplikasi tidak membuat database lokal.

Panduan Firebase dan Vercel: [SETUP.md](SETUP.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [Pengaturan AI](AI_SETUP.md). Lisensi: [MIT](LICENSE).

## Fitur

- Dashboard, transaksi, akun, kategori kustom, Budgetting, dan Wish.
- Budget per kategori pengeluaran dengan akun sumber, nominal terpakai, sisa dana, dan persentase otomatis.
- Koleksi Firestore `budgets` dibuat otomatis saat budget pertama disimpan; tidak perlu dibuat manual.
- Saldo, transfer antar-akun, filter rentang waktu, grafik aset/pengeluaran, dan CSV.
- Draft transaksi dari teks atau foto struk melalui Gemini atau OpenAI.
- Firebase Admin SDK hanya berjalan di backend; kredensial tidak dikirim ke browser.
