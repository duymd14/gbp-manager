# Hướng dẫn Deploy GBP Manager Pro lên Railway

## Tóm tắt tình trạng project

| Thành phần | Trạng thái | Ghi chú |
|---|---|---|
| Web server (gbp_webapp.py) | Sẵn sàng deploy | Bind 0.0.0.0, đọc PORT từ env |
| Railway config | Có sẵn | `railway.toml` + `Procfile` + `runtime.txt` |
| Credentials | Đọc từ env vars | Không hardcode nữa |
| Mock mode | Hoạt động | Chạy demo không cần GBP API thật |
| CORS headers | Đã thêm | Cho phép frontend gọi API |
| Fallback demo data | Đã thêm | Dùng `locations.example.json` nếu chưa có `locations.json` |

---

## Bước 1: Push code lên GitHub

```bash
cd /path/to/GBP

# Nếu chưa có remote GitHub:
git remote add origin https://github.com/TEN_CUA_BAN/gbp-manager.git

# Add và commit các file đã thay đổi
git add gbp_manager.py gbp_webapp.py DEPLOY_GUIDE.md
git commit -m "fix: đọc credentials từ env vars, thêm CORS, fallback demo data"

# Push lên GitHub
git push -u origin main
```

> **Lưu ý**: Các file `locations.json`, `.env`, `gbp_token.json` đã có trong `.gitignore` — không bao giờ push lên GitHub.

---

## Bước 2: Deploy trên Railway (khuyến nghị cho giai đoạn test)

### Tại sao Railway?

- Project đã có sẵn `railway.toml` — zero config, deploy ngay
- Free tier: $5 credit/tháng (~100 giờ chạy)
- Auto-deploy khi push code mới lên GitHub
- Đọc PORT từ env tự động (đã xử lý trong code)
- HTTPS miễn phí

### Các bước deploy:

1. Truy cập [railway.app](https://railway.app) → Đăng ký bằng GitHub account

2. Click **New Project** → **Deploy from GitHub repo** → Chọn repo `gbp-manager`

3. Railway tự detect `railway.toml` và build. Chờ khoảng 2-3 phút.

4. Sau khi deploy xong, vào tab **Settings** → **Networking** → Click **Generate Domain** để có URL public.

5. Mở URL đó — app chạy ở chế độ **mock/demo** với dữ liệu giả (vì chưa có credentials thật).

---

## Bước 3: Kiểm tra hoạt động (Mock Mode)

Truy cập các URL sau để xác nhận server hoạt động:

| URL | Kết quả mong đợi |
|---|---|
| `https://your-app.up.railway.app/` | Dashboard HTML hiển thị |
| `https://your-app.up.railway.app/api/status` | JSON với `"authenticated": false` |
| `https://your-app.up.railway.app/api/locations` | JSON danh sách locations (demo) |
| `https://your-app.up.railway.app/api/reviews` | JSON danh sách reviews (mock) |

Nếu tất cả 4 endpoint trả về dữ liệu → **Tools hoạt động online**.

---

## Bước 4: Kết nối GBP API thật (sau khi test mock xong)

### Vấn đề quan trọng: OAuth Desktop Flow

App hiện dùng **Desktop App OAuth** (`InstalledAppFlow`), nghĩa là bước auth phải chạy trên **máy local** của bạn, không phải trên server.

**Quy trình:**

1. Trên máy local, tạo file `.env`:
   ```
   GBP_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GBP_CLIENT_SECRET=GOCSPX-your_secret
   ```

2. Chạy auth local để lấy token:
   ```bash
   python gbp_manager.py --action auth
   ```
   Trình duyệt mở ra → đăng nhập Google → file `gbp_token.json` được tạo.

3. Đọc nội dung file `gbp_token.json` và lưu vào **Railway Variable** với key `GBP_TOKEN_JSON`:
   ```bash
   cat gbp_token.json
   # Copy toàn bộ nội dung JSON này
   ```

4. Trong Railway → **Variables** → Thêm:
   - `GBP_CLIENT_ID` = client ID của bạn
   - `GBP_CLIENT_SECRET` = client secret của bạn
   - `GBP_TOKEN_JSON` = nội dung file gbp_token.json (cả chuỗi JSON)

5. Cập nhật `gbp_webapp.py` để đọc token từ env var `GBP_TOKEN_JSON` thay vì file.

> **Lưu ý**: Đây là điểm cần refactor thêm khi chuyển sang production thật.

---

## So sánh Platform Deploy

### Cho giai đoạn test hiện tại

| Platform | Chi phí | Ưu điểm | Nhược điểm |
|---|---|---|---|
| **Railway** ⭐ | $5 credit/tháng free | Đã config sẵn, auto-deploy, HTTPS | Sleep sau 30 ngày nếu hết credit |
| Render | Free (sleep sau 15 phút inactive) | Tương tự Railway | Sleep gây delay khi load lần đầu |
| Fly.io | ~$2/tháng | Nhanh, persistent volume | Cần cài CLI, phức tạp hơn |

### Cho production SaaS (thu phí user)

| Platform | Chi phí | Lý do chọn |
|---|---|---|
| **Railway Pro** | $20/tháng + usage | Đơn giản nhất, CI/CD tốt, dễ scale |
| **Render Starter** | $7/tháng | Không sleep, ổn định, rẻ hơn Railway Pro |
| **DigitalOcean App** | $12/tháng | Ổn định, hỗ trợ tốt, phù hợp SaaS |
| **VPS (Hetzner CX11)** | €3.79/tháng | Rẻ nhất, full control, cần biết Linux |

**Khuyến nghị cho SaaS**: Dùng **Render Starter** ($7/tháng) hoặc **Railway** để bắt đầu. Khi có 20+ user trả tiền thì chuyển sang VPS để tiết kiệm chi phí.

---

## Roadmap kỹ thuật trước khi thu phí

Trước khi bán subscription, cần làm thêm:

1. **Multi-tenant auth** — mỗi user đăng nhập bằng Google riêng, không dùng chung 1 OAuth token. Dùng Supabase Auth hoặc Firebase Auth.

2. **Database** — lưu locations, settings, token theo từng user. Dùng PostgreSQL (Railway có addon free) hoặc Supabase.

3. **Billing** — tích hợp Stripe. File `.env.example` đã chuẩn bị sẵn `STRIPE_SECRET_KEY`. Cần thêm webhook xử lý payment.

4. **Kết nối dashboard với API** — dashboard hiện dùng dữ liệu demo tĩnh. Cần update các hàm `renderLocations()`, `renderReviews()` để fetch từ API.

5. **Refactor web server** — chuyển từ Python stdlib `SimpleHTTPRequestHandler` sang **FastAPI** để dễ mở rộng và có tài liệu API tự động.

---

## Quick checklist trước khi demo cho khách hàng

- [ ] App load tại URL Railway không lỗi 500
- [ ] `/api/status` trả về JSON hợp lệ
- [ ] `/api/locations` có data (dù là mock)
- [ ] Dashboard HTML hiển thị đầy đủ 8 tab
- [ ] Chức năng "Gợi ý Reply" hoạt động (không cần GBP API thật)
- [ ] Templates hiển thị đúng DE/EN theo loại review

---

*Cập nhật: 13/04/2026*
