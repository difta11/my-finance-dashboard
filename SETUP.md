# Panduan Lengkap Deploy My Finance Dashboard Sendiri

Panduan ini dibuat untuk pemula. Ikuti langkah-langkah di bawah ini secara berurutan untuk memiliki dashboard keuangan pribadi milikmu sendiri yang bisa diakses secara online.[cite: 12]

---

## Tahap 1: Mengambil Kode Aplikasi (Clone Repository)

Kita akan menggunakan GitHub Desktop agar proses pengunduhan kode lebih mudah tanpa perlu mengetik perintah rumit.[cite: 12]

1. Buka situs [desktop.github.com](https://desktop.github.com/) dan unduh aplikasi **GitHub Desktop**.[cite: 12]
2. Instal dan buka aplikasinya, lalu *login* menggunakan akun GitHub milikmu.[cite: 12]
3. Click "current repository" di kiri atas.[cite: 12]
4. Click "add" lalu pilih "clone repository".[cite: 12]
5. Pilih tab url, lalu masukkan "https://github.com/difta11/my-finance-dashboard"[cite: 12]
6. Pilih lokasi folder di komputermu untuk menyimpan kode ini, lalu klik **Clone**.[cite: 12]

---

## Tahap 2: Menyiapkan File Konfigurasi (.env)

Aplikasi membutuhkan file khusus untuk menyimpan kata sandi dan kunci rahasia. File ini sengaja disembunyikan agar aman.[cite: 12]

1. Buka folder tempat kamu menyimpan kode tadi (kamu bisa klik tombol **Show in Explorer** / **Show in Finder** di GitHub Desktop).[cite: 12]
2. Cari file bernama `.env.example`.[cite: 12]
3. *Copy* (salin) file tersebut dan *paste* (tempel) di folder yang sama.[cite: 12]
4. Ubah nama file hasil salinan tersebut dari `.env.example - Copy` menjadi `.env` saja (pastikan ada titik di depannya).[cite: 12]
5. Buka file `.env` tersebut menggunakan aplikasi Notepad (Windows) atau TextEdit (Mac). Kita akan mengisi nilai-nilainya di langkah-langkah berikutnya.[cite: 12]

---

## Tahap 3: Membuat Database Firebase

Aplikasi ini menggunakan Firebase dari Google untuk menyimpan data ketikan transaksimu (secara gratis).[cite: 12]

1. Buka [console.firebase.google.com](https://console.firebase.google.com/) dan *login* dengan akun Google kamu.[cite: 12]
2. Klik **Create a project** (Buat proyek), beri nama (misal: "Keuangan Pribadi"), lalu klik Continue. (Matikan opsi Google Analytics karena tidak diperlukan).[cite: 12]
3. Setelah proyek siap, lihat menu di sebelah kiri, klik **Build**, lalu pilih **Firestore Database**.[cite: 12]
4. Klik **Create database**, pilih lokasi *server* yang paling dekat (misal: `asia-southeast1` untuk Singapore atau `asia-southeast2` untuk Jakarta), dan mulai dalam mode produksi (*production mode*).[cite: 12]
5. Sekarang, kita butuh "Kunci Akses" (Service Account) agar aplikasimu bisa membaca database ini:[cite: 12]
   * Klik ikon roda gigi (Settings) di sebelah tulisan *Project Overview* di kiri atas, pilih **Project settings**.[cite: 12]
   * Pindah ke tab **Service accounts**.[cite: 12]
   * Klik tombol **Generate new private key**. Sebuah file dengan akhiran `.json` akan terunduh.[cite: 12]
6. File `.json` ini harus diubah ke format teks (Base64).[cite: 12]
   * Buka situs web gratis seperti [base64encode.org](https://www.base64encode.org/).[cite: 12]
   * Buka file `.json` yang baru diunduh menggunakan Notepad, *copy* SEMUA isinya, lalu *paste* ke situs Base64 tadi.[cite: 12]
   * Klik tombol **Encode**.[cite: 12]
   * *Copy* hasil teks acak yang panjang tersebut, lalu *paste* ke dalam file `.env` milikmu tepat di sebelah kanan tulisan `FIREBASE_SERVICE_ACCOUNT_BASE64=`.[cite: 12]

---

## Tahap 4: Menyiapkan Penyimpanan Foto (Google Drive)

Agar foto struk otomatis tersimpan di Google Drive milikmu.[cite: 12]

1. Buka [console.cloud.google.com](https://console.cloud.google.com/). Pastikan kamu berada di proyek Firebase yang baru saja kamu buat.[cite: 12]
2. Cari kotak pencarian di bagian paling atas, ketik **"Google Drive API"**, pilih hasil teratas, lalu klik **Enable** (Aktifkan).[cite: 12]
3. Lihat menu di sebelah kiri, klik **APIs & Services**, lalu pilih **OAuth consent screen** (Layar persetujuan).[cite: 12]
4. Pilih **External**, lalu klik **Create**.[cite: 12]
5. Isi nama aplikasi (misal: "Finance Dashboard") dan masukkan emailmu di kolom dukungan email. Klik **Save and Continue** sampai selesai (lewati bagian *Scopes*).[cite: 12]
6. Kembali ke halaman *OAuth consent screen*, gulir ke bawah ke bagian **Test users**, klik **+ ADD USERS**, dan masukkan alamat email Gmail kamu. Ini penting agar kamu diizinkan mengaksesnya.[cite: 12]
7. Sekarang, lihat menu sebelah kiri lagi, klik **Credentials** (Kredensial).[cite: 12]
8. Klik **+ CREATE CREDENTIALS** di atas, lalu pilih **OAuth client ID**.[cite: 12]
9. Pilih Application type: **Web application**.[cite: 12]
10. Di bagian **Authorized redirect URIs**, klik **+ ADD URI** dan masukkan:[cite: 12]
    `https://[nama-proyek-vercel-kamu.vercel.app]/auth/google-drive/callback`[cite: 12]
    *(Catatan: Biarkan dulu jika kamu belum tahu URL Vercel-mu, nanti bisa diisi belakangan).*[cite: 12]
11. Klik **Create**. Sebuah *pop-up* akan muncul menampilkan **Client ID** dan **Client Secret**.[cite: 12]
12. *Copy* kedua kode tersebut dan masukkan ke dalam file `.env` di sebelah kanan `GOOGLE_DRIVE_CLIENT_ID=` dan `GOOGLE_DRIVE_CLIENT_SECRET=`.[cite: 12]

---

## Tahap 5: Membuat Kunci Rahasia Tambahan

Buka file `.env` kamu. Masih ada beberapa variabel yang harus diisi secara mandiri:[cite: 12]

1. **DASHBOARD_PASSWORD=**[cite: 12]
   Ketikkan kata sandi apa saja yang ingin kamu gunakan untuk login ke dashboard-mu nanti (tanpa spasi).[cite: 12]
2. **SESSION_SECRET=**[cite: 12]
   Ketik sembarang huruf dan angka secara acak, minimal 32 karakter. Contoh: `a8b9c0d1e2f3g4h5i6j7k8l9m0n1o2p3q4r5s6t7`.[cite: 12]
3. **GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY=**[cite: 12]
   Ini adalah kunci khusus untuk keamanan Drive-mu. Karena kamu belum tentu menginstal Python di komputermu, gunakan cara termudah via internet:[cite: 12]
   * Buka situs [online-python.com](https://www.online-python.com/) di browser.
   * Hapus semua teks bawaan yang ada di kotak putih, lalu *paste* kode ini: `from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())`
   * Klik tombol **Run** (Jalankan) di bagian bawah.
   * *Copy* teks acak yang muncul di kotak hitam (biasanya berakhiran tanda `=`) dan tempelkan sebagai nilai variabel ini.

---

## Tahap 6: Mengatur Fitur Tanya AI (Gemini)

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