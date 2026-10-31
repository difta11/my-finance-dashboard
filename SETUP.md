# Setup Firebase

1. Gunakan project Firebase yang sudah memiliki **Cloud Firestore**. Tidak perlu membuat database baru. Aplikasi akan memakai database default di project yang tertera pada kredensial service account.
2. Jika ingin menyimpan foto struk, aktifkan **Cloud Storage** di project yang sama. Salin nama bucket persis seperti di Firebase Console tanpa awalan `gs://`, lalu atur `FIREBASE_STORAGE_BUCKET`. Langkah ini opsional untuk transaksi dan grafik. Cloud Storage saat ini memerlukan paket Blaze/pay-as-you-go; siapkan billing account dan budget alert.
3. Dari **Project settings → Service accounts**, buat private key untuk service account server. Simpan JSON key di luar repository. Jangan pernah memasukkannya ke `public/`, `static/`, GitHub, atau kode browser.
4. Encode file JSON ke Base64. Di PowerShell, dari direktori tempat file key disimpan:

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes('.\firebase-service-account.json'))
   ```

   Perintah itu menampilkan satu nilai Base64. Masukkan nilainya sebagai `FIREBASE_SERVICE_ACCOUNT_BASE64` di environment Vercel atau `.env` lokal; jangan masukkan file JSON ke repo. Base64 tidak mengenkripsi key, jadi perlakukan nilainya sebagai kata sandi.

Buat `SESSION_SECRET` acak dengan `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Gunakan nilai berbeda untuk tiap deployment. Baca [syarat billing Cloud Storage](https://firebase.google.com/docs/storage/faqs-storage-changes-announced-sept-2024) sebelum membuat bucket.

Firebase Admin SDK memakai akses server. Firestore dan Storage tidak perlu dibuka untuk akses publik; biarkan Security Rules tetap menolak akses klien yang tidak berwenang. Jangan menaruh Firebase Admin key atau API key AI di JavaScript.

## Menjalankan lokal

Salin `.env.example` ke `.env`, lalu isi `DASHBOARD_PASSWORD`, `SESSION_SECRET`, dan `FIREBASE_SERVICE_ACCOUNT_BASE64`. Isi `FIREBASE_STORAGE_BUCKET` hanya jika foto struk akan disimpan. Install Python 3.12, kemudian:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Buka `http://localhost:5000`. Data tersimpan di project Firebase yang dikonfigurasi, bukan di laptop. `.env` masuk `.gitignore`; jangan menghapus pengecualian itu.

## Migrasi data lama (opsional)

Jika memiliki salinan database SQLite lama dan folder struknya, migrasikan sebelum membuang salinan tersebut. Isi konfigurasi Firebase di environment, pastikan koleksi `accounts`, `categories`, `transactions`, dan `wishes` di Firestore masih kosong, lalu jalankan:

```powershell
python scripts/migrate_sqlite_to_firestore.py C:\path\ke\finance.db --receipts-dir C:\path\ke\receipts
```

Skrip menolak migrasi jika koleksi tujuan sudah berisi dokumen dan tidak menghapus database sumber. Setelah migrasi, verifikasi saldo, kategori, transaksi, dan foto struk lewat dashboard sebelum menghapus backup lama.
