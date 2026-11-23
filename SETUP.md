# Panduan Lengkap Deploy My Finance Dashboard Sendiri

Panduan ini dibuat untuk pemula. Ikuti langkah-langkah di bawah ini secara berurutan untuk memiliki dashboard keuangan pribadi milikmu sendiri yang bisa diakses secara online.

---

## Tahap 1: Mengambil Kode Aplikasi (Clone Repository)

Kita akan menggunakan GitHub Desktop agar proses pengunduhan kode lebih mudah tanpa perlu mengetik perintah rumit.

1. Buka situs [desktop.github.com](https://desktop.github.com/) dan unduh aplikasi **GitHub Desktop**.
2. Instal dan buka aplikasinya, lalu *login* menggunakan akun GitHub milikmu.
3. Click "current repository" di kiri atas.
4. Click "add" lalu pilih "clone repository".
5. Pilih tab url, lalu masukkan "https://github.com/difta11/my-finance-dashboard"
6. Pilih lokasi folder di komputermu untuk menyimpan kode ini, lalu klik **Clone**.

---

## Tahap 2: Menyiapkan File Konfigurasi (.env)

Aplikasi membutuhkan file khusus untuk menyimpan kata sandi dan kunci rahasia. File ini sengaja disembunyikan agar aman.

1. Buka folder tempat kamu menyimpan kode tadi (kamu bisa klik tombol **Show in Explorer** / **Show in Finder** di GitHub Desktop).
2. Cari file bernama `.env.example`.
3. *Copy* (salin) file tersebut dan *paste* (tempel) di folder yang sama.
4. Ubah nama file hasil salinan tersebut dari `.env.example - Copy` menjadi `.env` saja (pastikan ada titik di depannya).
5. Buka file `.env` tersebut menggunakan aplikasi Notepad (Windows) atau TextEdit (Mac). Kita akan mengisi nilai-nilainya di langkah-langkah berikutnya.

---

## Tahap 3: Membuat Database Firebase

Aplikasi ini menggunakan Firebase dari Google untuk menyimpan data ketikan transaksimu (secara gratis).

1. Buka [console.firebase.google.com](https://console.firebase.google.com/) dan *login* dengan akun Google kamu.
2. Klik **Create a project** (Buat proyek), beri nama (misal: "Keuangan Pribadi"), lalu klik Continue. (Matikan opsi Google Analytics karena tidak diperlukan).
3. Setelah proyek siap, lihat menu di sebelah kiri, klik **Build**, lalu pilih **Firestore Database**.
4. Klik **Create database**, pilih lokasi *server* yang paling dekat (misal: `asia-southeast1` untuk Singapore atau `asia-southeast2` untuk Jakarta), dan mulai dalam mode produksi (*production mode*).
5. Sekarang, kita butuh "Kunci Akses" (Service Account) agar aplikasimu bisa membaca database ini:
   * Klik ikon roda gigi (Settings) di sebelah tulisan *Project Overview* di kiri atas, pilih **Project settings**.
   * Pindah ke tab **Service accounts**.
   * Klik tombol **Generate new private key**. Sebuah file dengan akhiran `.json` akan terunduh.
6. File `.json` ini harus diubah ke format teks (Base64). Lakukan langsung di komputermu sendiri. **Jangan** menempelkan isi file ini ke situs *online* mana pun, karena file tersebut berisi kunci rahasia (*private key*) yang memberi akses penuh ke database-mu.
   * **Windows:** buka aplikasi **PowerShell** (cari "PowerShell" di menu Start), lalu jalankan perintah berikut. Ganti `nama-file.json` dengan nama file yang baru kamu unduh:
     ```powershell
     [Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\Downloads\nama-file.json")) | Set-Clipboard
     ```
   * **Mac:** buka aplikasi **Terminal**, lalu jalankan perintah berikut (ganti juga `nama-file.json`):
     ```bash
     base64 -i ~/Downloads/nama-file.json | tr -d '\n' | pbcopy
     ```
   * Perintah di atas tidak menampilkan apa pun di layar. Hasilnya langsung tersalin ke *clipboard*. *Paste* hasil tersebut ke dalam file `.env` milikmu tepat di sebelah kanan tulisan `FIREBASE_SERVICE_ACCOUNT_BASE64=` (semuanya dalam satu baris, tanpa spasi atau baris baru).
   * Simpan file `.json` aslinya di tempat yang aman di luar folder kode ini, dan jangan pernah mengunggahnya ke GitHub.

---

## Tahap 4: Menyiapkan Penyimpanan Foto (Google Drive)

Agar foto struk otomatis tersimpan di Google Drive milikmu.

1. Buka [console.cloud.google.com](https://console.cloud.google.com/). Pastikan kamu berada di proyek Firebase yang baru saja kamu buat.
2. Cari kotak pencarian di bagian paling atas, ketik **"Google Drive API"**, pilih hasil teratas, lalu klik **Enable** (Aktifkan).
3. Lihat menu di sebelah kiri, klik **APIs & Services**, lalu pilih **OAuth consent screen** (Layar persetujuan).
4. Pilih **External**, lalu klik **Create**.
5. Isi nama aplikasi (misal: "Finance Dashboard") dan masukkan emailmu di kolom dukungan email. Klik **Save and Continue** sampai selesai (lewati bagian *Scopes*).
6. Kembali ke halaman *OAuth consent screen*, gulir ke bawah ke bagian **Test users**, klik **+ ADD USERS**, dan masukkan alamat email Gmail kamu. Ini penting agar kamu diizinkan mengaksesnya.
7. Sekarang, lihat menu sebelah kiri lagi, klik **Credentials** (Kredensial).
8. Klik **+ CREATE CREDENTIALS** di atas, lalu pilih **OAuth client ID**.
9. Pilih Application type: **Web application**.
10. Di bagian **Authorized redirect URIs**, klik **+ ADD URI** dan masukkan:
    `https://[nama-proyek-vercel-kamu.vercel.app]/auth/google-drive/callback`
    *(Catatan: Biarkan dulu jika kamu belum tahu URL Vercel-mu, nanti bisa diisi belakangan).*
11. Klik **Create**. Sebuah *pop-up* akan muncul menampilkan **Client ID** dan **Client Secret**.
12. *Copy* kedua kode tersebut dan masukkan ke dalam file `.env` di sebelah kanan `GOOGLE_DRIVE_CLIENT_ID=` dan `GOOGLE_DRIVE_CLIENT_SECRET=`.

---

## Tahap 5: Membuat Kunci Rahasia Tambahan

Buka file `.env` kamu. Masih ada beberapa variabel yang harus diisi secara mandiri:

1. **DASHBOARD_PASSWORD=**
   Ketikkan kata sandi apa saja yang ingin kamu gunakan untuk login ke dashboard-mu nanti (tanpa spasi).
2. **SESSION_SECRET=**
   Ketik sembarang huruf dan angka secara acak, minimal 32 karakter. Contoh: `a8b9c0d1e2f3g4h5i6j7k8l9m0n1o2p3q4r5s6t7`.
3. **GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY=**
   Ini adalah kunci khusus untuk keamanan Drive-mu. Karena kamu belum tentu menginstal Python di komputermu, gunakan cara termudah via internet:
   * Buka situs [online-python.com](https://www.online-python.com/) di browser.
   * Hapus semua teks bawaan yang ada di kotak putih, lalu *paste* kode ini: `from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())`
   * Klik tombol **Run** (Jalankan) di bagian bawah.
   * *Copy* teks acak yang muncul di kotak hitam (biasanya berakhiran tanda `=`) dan tempelkan sebagai nilai variabel ini.

---

## Tahap 6: Mengatur Smart Entry (Gemini)

Agar fitur AI untuk membaca struk dan mencatat transaksi berfungsi, kita akan menghubungkannya dengan Google Gemini secara gratis.

1. Buka situs [aistudio.google.com](https://aistudio.google.com/) dan *login* menggunakan akun Google kamu.
2. Di menu sebelah kiri, klik **Get API key**, lalu klik tombol **Create API key**.
3. Pilih *Create API key in a new project*.
4. *Copy* kunci API panjang yang diberikan.
5. Buka kembali file `.env` kamu, lalu pastikan variabel berikut diisi seperti ini:
   * `AI_ENABLED=true`
   * `AI_PROVIDER=gemini`
   * `GEMINI_API_KEY=[paste-kunci-api-kamu-di-sini]`

---

## Tahap 7: Publikasi (Deploy) ke Vercel agar Online

Langkah terakhir untuk membuat aplikasimu bisa diakses lewat internet.

1. Buka [vercel.com](https://vercel.com/) dan daftar menggunakan akun GitHub milikmu.
2. Di halaman utama Vercel, klik **Add New...** lalu pilih **Project**.
3. Vercel akan membaca repository GitHub kamu. Cari "My Finance Dashboard" di daftar, lalu klik **Import**.
4. Di bagian *Configure Project*, gulir ke bawah, lalu klik menu **Environment Variables**.
5. Buka kembali file `.env` di Notepad. *Copy* isi setiap variabel (nama dan nilainya) satu per satu dan masukkan ke dalam kolom Vercel tersebut, lalu klik **Add**. Lakukan untuk semua isi `.env`.
   * *Pastikan `GOOGLE_DRIVE_REDIRECT_URI` diisi dengan prediksi link vercel-mu (misal: `https://my-finance-dashboard.vercel.app/auth/google-drive/callback`).*
6. Jika semua variabel sudah ditambahkan, klik tombol **Deploy**.
7. Tunggu beberapa menit hingga selesai. 

**Langkah Penyesuaian Terakhir (Penting!):**
Buka link Vercel-mu yang sekarang sudah jadi.
1. Catat domain akhirnya (misal: `https://my-finance-dashboard-abcdef.vercel.app`).
2. Buka kembali **Vercel > Settings > Environment Variables**, ubah isi `GOOGLE_DRIVE_REDIRECT_URI` menjadi domain aslinya tersebut. Jangan lupa lakukan **Redeploy** (tab Deployments > titik tiga > Redeploy).
3. Buka **Google Cloud Console > Credentials**, klik nama OAuth-mu, ubah URI Pengalihan agar sama persis dengan domain Vercel barumu, dan **Save**.