# Shift Planner (Streamlit + Postgres)

Vardiya planlama aracı. Postgres veritabanı ile kalıcı veri saklama ve token bazlı erişim kontrolü.

## Özellikler

- **Departman / Personel Yönetimi**
  - Departman ekle / sil
  - Personel ekle, düzenle, sil
- **Planlama Ekranı**
  - Ay / hafta görünümü
  - HTML tablo yapısı (KolayİK benzeri)
  - Hücreye tıklayınca ilgili gün için vardiya ekleme/düzenleme
  - Bir günde birden fazla vardiya (max 2)
- **Token Bazlı Erişim**
  - Admin token: Tüm işlemler (ekle/düzenle/sil)
  - Viewer token: Sadece görüntüleme (read-only)
  - Paylaşım linkleri üretme ve yönetme
- **Export**
  - Departman + tarih aralığı filtresi
  - CSV export (sabit kolon sırası ve format)
  - Export filtreleri: team_member (multi), work_type (multi), food_payment (All/YES/NO), tarih aralığı
  - Export'ta `team_member`, `work_type`, `food_payment` değerleri **UPPERCASE** olarak çıkar

## Kurulum

### 1. Gereksinimler

```bash
cd /Users/bahadir/Shift
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Veritabanı Yapılandırması

**Lokal Kullanım:**

1. `.streamlit/secrets.toml` dosyası oluşturun:
```bash
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

2. `.streamlit/secrets.toml` dosyasını düzenleyin ve Neon Postgres URL'inizi ekleyin:
```toml
DATABASE_URL = "postgresql+psycopg://user:password@ep-xxx-xxx.region.aws.neon.tech/dbname?sslmode=require"
# Opsiyonel: Paylaşım linklerini tam URL olarak göstermek için:
# APP_BASE_URL = "https://your-app.streamlit.app"
# Opsiyonel: Kurulum/kurtarma ekranını açmak için (token kaybolursa):
# GLOBAL_ADMIN_TOKEN = "uzun-rastgele-bir-deger"
```

**Streamlit Cloud Deploy:**

1. Streamlit Cloud UI'dan (Settings -> Secrets) `DATABASE_URL` secret'ını ekleyin
2. Format: `postgresql+psycopg://user:password@host/dbname?sslmode=require`

**Not:** `DATABASE_URL` önce environment variable'dan (`os.getenv`), yoksa Streamlit secrets'tan okunur.

### 3. İlk Çalıştırma

```bash
streamlit run app.py
```

İlk çalıştırmada veritabanı tabloları otomatik oluşturulur (`init_db()`).

### 4. SQLite'dan Postgres'e Migration (Opsiyonel)

Eğer mevcut SQLite veritabanınız varsa:

```bash
# DATABASE_URL'i set edin (env veya secrets.toml)
python scripts/migrate_sqlite_to_postgres.py
```

## Veritabanı Şeması

### Postgres Tabloları

- **departments**
  - `id` INTEGER PRIMARY KEY
  - `name` VARCHAR UNIQUE NOT NULL

- **team_members**
  - `id` INTEGER PRIMARY KEY
  - `department_id` INTEGER (FK -> departments.id)
  - `team_member_id` VARCHAR NOT NULL (manuel ID)
  - `team_member` VARCHAR NOT NULL (isim)
  - UNIQUE(department_id, team_member_id)

- **shifts**
  - `id` INTEGER PRIMARY KEY
  - `department_id` INTEGER NOT NULL
  - `team_member_id` INTEGER (FK -> team_members.id)
  - `date` DATE NOT NULL
  - `work_type` VARCHAR NOT NULL
  - `food_payment` VARCHAR NOT NULL
  - `shift_start` TIMESTAMP NULL
  - `shift_end` TIMESTAMP NULL
  - `overtime_start` TIMESTAMP NULL
  - `overtime_end` TIMESTAMP NULL
  - `created_at` TIMESTAMP
  - `updated_at` TIMESTAMP
  - INDEX(department_id, team_member_id, date)

- **access_links**
  - `id` INTEGER PRIMARY KEY
  - `token` VARCHAR UNIQUE NOT NULL
  - `department_id` INTEGER (FK -> departments.id)
  - `role` VARCHAR NOT NULL ('admin' | 'viewer')
  - `label` VARCHAR
  - `created_at` TIMESTAMP

## Token Bazlı Erişim

Uygulama URL'de `?token=...` parametresi ile erişim kontrolü yapar:

- **Admin Token:** Tüm işlemler (Planning, People, Export, Paylaşım, Toplu İşlemler)
- **Viewer Token:** Sadece Planning görünümü (read-only, hücre tıklama kapalı)

Token'lar "Paylaşım" sekmesinden üretilir ve statiktir (rotate edilebilir).

## CSV Export Formatı

Export ekranından alınan CSV aşağıdaki kolonları içerir (sabit sıra):

1. `date` (M/D/YYYY formatında, örn: 1/5/2026)
2. `team_member_id` (string)
3. `team_member` (string, **UPPERCASE**)
4. `work_type` (string, **UPPERCASE**; custom label varsa örn. `CUSTOM: BABALIK İZNİ`)
5. `food_payment` (YES/NO, **UPPERCASE**)
6. `shift_start` (M/D/YYYY H:MM formatında, örn: 1/5/2026 9:00, boş olabilir)
7. `shift_end` (M/D/YYYY H:MM formatında, boş olabilir)
8. `overtime_start` (M/D/YYYY H:MM formatında, boş olabilir)
9. `overtime_end` (M/D/YYYY H:MM formatında, boş olabilir)

**Önemli:** 
- CSV kolon isimleri ve sırası her zaman sabittir
- Tarih formatları: `date` için M/D/YYYY, datetime için M/D/YYYY H:MM
- `team_member`, `work_type`, `food_payment` değerleri export'ta UPPERCASE olarak çıkar

## Deploy (Streamlit Community Cloud)

1. GitHub repository'yi bağlayın
2. Settings -> Secrets'tan `DATABASE_URL` ekleyin
3. Deploy edin

Uygulama otomatik olarak:
- `init_db()` ile tabloları oluşturur
- Token bazlı erişim kontrolü yapar
- Postgres bağlantısını secrets'tan okur

## Dosya Yapısı

```
Shift/
├── app.py                    # Ana Streamlit uygulaması
├── db_postgres.py            # Postgres DB katmanı (SQLAlchemy)
├── services.py               # İş mantığı fonksiyonları
├── requirements.txt          # Python bağımlılıkları
├── .streamlit/
│   ├── secrets.toml          # Lokal secrets (gitignore'da)
│   └── secrets.toml.example  # Örnek secrets dosyası
├── scripts/
│   └── migrate_sqlite_to_postgres.py  # Migration script
└── README.md
```

## Notlar

- SQLite desteği kaldırıldı; sadece Postgres kullanılır
- Token'lar 32-48 karakter random string'lerdir
- Viewer role ile DB'ye write (insert/update/delete) yasaktır
- Modal açma/kapama "one-shot" event gate ile kontrol edilir (tekrar açılma sorunu yok)
