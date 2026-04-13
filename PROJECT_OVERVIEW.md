# GBP Manager Pro

**Công cụ tự động hóa Google Business Profile (GBP) dành cho chủ doanh nghiệp Việt tại Đức.**

Quản lý tập trung 20+ địa điểm GBP: tự động reply review, đăng bài theo lịch, tạo nội dung từ ảnh và keywords, theo dõi hiệu suất.

---

## Mục tiêu

Chủ sở hữu đang quản lý **20 GBP tại Đức** (nhà hàng Vietnamese/Asian Fusion + nail/beauty salon). Công việc thủ công hàng ngày bao gồm: reply review, đăng bài cập nhật trên GBP, theo dõi hiệu suất từng địa điểm. Bộ tools này tự động hóa toàn bộ quy trình đó.

---

## Kiến trúc tổng quan

```
GBP Manager Pro
├── gbp_dashboard.html    # Giao diện web (chạy thẳng trên trình duyệt, không cần server)
├── gbp_webapp.py         # Web server Python (REST API + serve dashboard)
├── gbp_manager.py        # Business logic core (GBP API client, reply, post)
├── review_templates.json # Kho template reply review (DE + EN, nhà hàng + beauty)
├── post_calendar.json    # Kho 32 bài đăng mẫu theo ngành và ngôn ngữ
├── locations.json        # Danh sách 20 địa điểm thực tế (tạo từ locations.example.json)
├── locations.example.json# Template mẫu 1 địa điểm để điền vào
├── requirements.txt      # Python dependencies
└── gbp_token.json        # OAuth2 token (tự sinh sau khi auth, không commit lên git)
```

---

## Cách chạy

### Cách 1: Mở thẳng trên trình duyệt (không cần Python)

Dành cho việc xem giao diện, chỉnh template, xem trước bài đăng.

```bash
# Chỉ cần double-click file hoặc dùng lệnh:
open gbp_dashboard.html          # macOS
start gbp_dashboard.html         # Windows
xdg-open gbp_dashboard.html      # Linux
```

Toàn bộ giao diện chạy client-side. Dữ liệu trong file là dữ liệu demo.

---

### Cách 2: Chạy web server đầy đủ (kết nối GBP API thật)

**Bước 1: Cài dependencies**

```bash
pip install -r requirements.txt
```

**Bước 2: Tạo file locations.json**

Copy từ file mẫu và điền thông tin thực:

```bash
cp locations.example.json locations.json
```

Mỗi location cần có `accountId` và `locationId` lấy từ Google Business Profile API.
Cấu trúc một location:

```json
{
  "id": 1,
  "name": "PHO Noodle Bar - Kreuzberg",
  "area": "Kreuzberg",
  "city": "Berlin",
  "type": "restaurant",
  "accountId": "accounts/1234567890",
  "locationId": "locations/9876543210",
  "website": "https://pho.berlin/",
  "keywords": ["pho bo", "vietnamese food", "halal", "kreuzberg"],
  "active": true
}
```

**Bước 3: Lấy Google OAuth2 Credentials**

1. Vào [Google Cloud Console](https://console.cloud.google.com)
2. Tạo project mới hoặc dùng project có sẵn
3. Bật API: `Business Profile API` và `My Business Account Management API`
4. Tạo OAuth 2.0 Client ID (loại: Desktop App)
5. Copy `Client ID` và `Client Secret` vào phần `CONFIG` trong `gbp_manager.py`:

```python
CONFIG = {
    "CLIENT_ID": "123456789.apps.googleusercontent.com",
    "CLIENT_SECRET": "GOCSPX-...",
    ...
}
```

**Bước 4: Xác thực lần đầu (chỉ làm 1 lần)**

```bash
python gbp_manager.py --action auth
```

Trình duyệt sẽ mở ra, đăng nhập Google và cấp quyền. Token sẽ được lưu vào `gbp_token.json` và tự động làm mới.

**Bước 5: Khởi động web server**

```bash
python gbp_webapp.py
# Server chạy tại: http://127.0.0.1:8000
```

Mở trình duyệt vào `http://127.0.0.1:8000` để dùng dashboard với dữ liệu thật từ GBP.

---

## Cấu trúc file chi tiết

### `gbp_dashboard.html`

Giao diện quản lý toàn bộ, gồm 8 trang:

| Trang | Chức năng |
|---|---|
| Dashboard | Tổng quan: cảnh báo cần xử lý, hoạt động gần đây |
| 20 Địa điểm | Bảng toàn bộ GBP, lọc theo ngành / thành phố |
| Phân tích | Biểu đồ lượt xem, top địa điểm, KPI |
| Quản lý Review | Xem review, chọn template, reply thủ công hoặc auto |
| Đăng bài tự động | Upload ảnh, chọn keywords, cài lịch, xem trước bài |
| Template Reply | Kho template DE/EN theo ngành và loại review |
| Cài đặt | Toggle tính năng auto-reply, tần suất đăng, ngôn ngữ |
| API & Kết nối | Nhập credentials, kiểm tra kết nối Google API |

**Trang Đăng bài tự động** (quy trình chính):

```
Upload ảnh → Chọn địa điểm → Thêm keywords → Cài lịch → Xem trước → Kích hoạt
```

Ảnh được đăng lần lượt theo thứ tự upload. Mỗi bài được sinh tự động từ keywords + nội dung ảnh + loại địa điểm (restaurant/beauty). Sau khi hết ảnh, hàng chờ lặp lại từ đầu.

---

### `gbp_manager.py`

Core logic, gồm 3 class chính:

**`GBPClient`**: Wrapper cho Google Business Profile API
- `get_reviews(location)`: Lấy danh sách review
- `reply_to_review(location, review_name, reply_text)`: Gửi reply
- `create_post(location, post_data)`: Đăng bài
- Khi chưa có credentials thật: tự dùng mock data để test

**`ReplyTemplateManager`**: Quản lý và áp dụng template reply
- `detect_language(text)`: Nhận diện DE/EN từ nội dung review
- `get_star_rating_int(star_str)`: Convert "FIVE" → 5
- `get_sentiment(stars)`: Phân loại positive/neutral/negative
- `get_reply(review, location, language)`: Chọn template phù hợp, điền biến

**`GBPManager`**: Điều phối toàn bộ tác vụ
- `run_reply_reviews()`: Chạy reply cho tất cả địa điểm một lần
- `run_publish_posts()`: Đăng bài cho tất cả địa điểm một lần
- `run_full_auto()`: Chạy cả hai
- `run_scheduler()`: Chạy 24/7 theo lịch (dùng thư viện `schedule`)

**Chạy qua CLI:**

```bash
python gbp_manager.py --action auth             # Xác thực Google API lần đầu
python gbp_manager.py --action reply_reviews    # Reply review tất cả GBP
python gbp_manager.py --action publish_posts    # Đăng bài tất cả GBP
python gbp_manager.py --action full_auto        # Cả hai, chạy 1 lần
python gbp_manager.py --action scheduler        # Chạy tự động 24/7
python gbp_manager.py --action report           # Xem báo cáo tóm tắt
python gbp_manager.py --dry-run                 # Chạy thử, không gửi dữ liệu thật
```

---

### `gbp_webapp.py`

Web server HTTP (Python stdlib, không cần Flask/FastAPI) phục vụ dashboard và REST API.

**REST API endpoints:**

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/` | Serve `gbp_dashboard.html` |
| GET | `/api/status` | Trạng thái kết nối Google API |
| GET | `/api/locations` | Danh sách địa điểm + số review pending |
| GET | `/api/reviews` | Danh sách review (lọc theo `location_id`, `pending_only=1`) |
| GET | `/api/templates` | Toàn bộ template reply |
| POST | `/api/auth` | Khởi động luồng OAuth |
| POST | `/api/reply/suggest` | Gợi ý reply cho 1 review |
| POST | `/api/reply` | Gửi reply thật lên GBP |
| POST | `/api/reply-all` | Auto-reply tất cả review pending |
| POST | `/api/posts/publish` | Đăng 1 bài lên GBP |

**Chạy server:**

```bash
python gbp_webapp.py
# Hoặc chỉ định port:
GBP_WEBAPP_PORT=9000 python gbp_webapp.py
```

---

### `review_templates.json`

Kho template reply, cấu trúc:

```
{industry}               → restaurant | beauty
  └── {sentiment}_{lang} → positive_de | positive_en | negative_de |
                           negative_en | neutral_de | neutral_en
       └── [{id, name, stars[], text}]
```

Biến có thể dùng trong text: `{name}` (tên khách), `{restaurant}` (tên địa điểm), `{city}` (thành phố).

Mỗi nhóm có nhiều variants để tránh lặp lại nội dung.

---

### `post_calendar.json`

32 bài đăng mẫu cho 30 ngày, chia theo:
- `type`: `restaurant` hoặc `beauty`
- `lang`: `de` (Đức) hoặc `en` (Anh)
- `week`: 1–4 (tuần trong tháng)
- `theme`: chủ đề bài (giới thiệu, món đặc trưng, ưu đãi, nhóm bạn...)

Script tự xoay vòng bài theo `(location_id + ngày_trong_năm) % số_bài`, đảm bảo mỗi địa điểm đăng nội dung khác nhau cùng ngày.

---

## Luồng dữ liệu thực tế

```
Google Business Profile API
        ↓ (pull reviews mỗi 2 giờ)
  GBPClient.get_reviews()
        ↓
  ReplyTemplateManager.get_reply()
    - Detect language (DE/EN)
    - Match sentiment (positive/neutral/negative)
    - Pick random template variant
    - Fill variables
        ↓
  GBPClient.reply_to_review()   →   Google API (POST reply)
        ↑
  GBPManager.run_scheduler()    →   cron: mỗi 2h reply, mỗi 2 ngày đăng bài
```

---

## Trạng thái hiện tại

| Thành phần | Trạng thái |
|---|---|
| Dashboard HTML | Hoàn chỉnh, chạy được |
| Web server (gbp_webapp.py) | Hoàn chỉnh, API đầy đủ |
| Core logic (gbp_manager.py) | Hoàn chỉnh, có mock mode để test |
| Template reply (DE + EN) | 20+ templates, 2 ngành, 6 loại |
| Lịch bài đăng | 32 bài, 2 ngành, 2 ngôn ngữ |
| Kết nối GBP API thật | Cần điền credentials + chạy auth |
| Kết nối ảnh thật vào API | Cần bổ sung multipart upload |
| Scheduler 24/7 | Hoạt động qua `schedule` library |

---

## Bước tiếp theo (Roadmap)

1. **Kết nối dashboard với web server**: Hiện tại dashboard dùng dữ liệu demo tĩnh. Cần thay các hàm `renderLocations()`, `renderReviews()` để fetch từ `/api/locations` và `/api/reviews`.
2. **Upload ảnh lên GBP**: Bổ sung multipart upload vào `GBPClient.create_post()` để đính kèm ảnh thật khi đăng bài.
3. **Lưu photo queue**: Hiện tại ảnh upload chỉ tồn tại trong bộ nhớ tab. Cần endpoint `/api/photos` để lưu server-side.
4. **Báo cáo hiệu suất thật**: Kết nối Google My Business Insights API để lấy views/interactions thật.
5. **Thông báo email**: Khi có review 1–2 sao, gửi email cảnh báo tới chủ sở hữu.
6. **Deploy lên server**: Đóng gói bằng Docker hoặc deploy lên VPS để chạy 24/7 không cần mở máy tính.

---

## Cấu trúc thư mục đề nghị khi scale up

```
gbp-manager/
├── backend/
│   ├── gbp_manager.py
│   ├── gbp_webapp.py
│   ├── requirements.txt
│   └── data/
│       ├── locations.json
│       ├── review_templates.json
│       └── post_calendar.json
├── frontend/
│   └── gbp_dashboard.html
├── photos/              # Thư mục lưu ảnh upload (tạo khi cần)
├── logs/
│   └── gbp_manager.log
├── .env                 # CLIENT_ID, CLIENT_SECRET (không commit)
├── gbp_token.json       # OAuth token (không commit)
└── PROJECT_OVERVIEW.md
```

---

## Lưu ý quan trọng cho developer

- **Không commit** `gbp_token.json` và `.env` lên git (thêm vào `.gitignore`)
- **Mock mode**: Khi chưa có credentials, `GBPClient` tự dùng dữ liệu giả để test. Log sẽ hiển thị `[CHẾ ĐỘ THỬ]`
- **Rate limiting**: Google API có giới hạn request. Script đã có `API_DELAY_SECONDS = 2` giữa các request và giới hạn `MAX_REPLIES_PER_RUN = 50`
- **Ngôn ngữ**: Dashboard hoàn toàn bằng tiếng Việt. Template reply và bài đăng bằng DE/EN. Code comment bằng tiếng Việt
- **Target audience**: Chủ nhà hàng/nail salon người Việt tại Đức, không phải developer. Giao diện ưu tiên đơn giản và trực quan

---

*Cập nhật lần cuối: 13/04/2026*
