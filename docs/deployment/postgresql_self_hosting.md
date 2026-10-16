# PostgreSQL local: một quy trình từ JSON đến database

Chạy các lệnh PowerShell dưới đây từ thư mục gốc repository. Cần Docker Desktop đang chạy và môi trường Python của dự án đã cài dependencies. Quy trình này tạo **một database mới trên máy bạn** rồi nạp dữ liệu từ `dataset/BTC-Data-Vong1-TEAMS/catalog/`; không dùng dump hoặc database của teammate.

## 1. Tạo PostgreSQL

```powershell
docker run --name telesale-postgres `
  -e POSTGRES_USER=telesale `
  -e POSTGRES_PASSWORD=telesale_dev_password `
  -e POSTGRES_DB=telesale `
  -p 127.0.0.1:5432:5432 `
  -v telesale_pgdata:/var/lib/postgresql/data `
  -d postgres:16

docker logs telesale-postgres --tail 20
```

Chờ log báo `database system is ready to accept connections`. Container dùng volume `telesale_pgdata` nên dữ liệu còn sau khi dừng Docker. Lệnh `docker run` chỉ chạy **một lần** cho database mới.

## 2. Kết nối ứng dụng

Nếu chưa có `.env`, tạo từ mẫu:

```powershell
Copy-Item .env.example .env
```

Sửa dòng `DATABASE_URL` trong `.env` thành:

```dotenv
DATABASE_URL=postgresql://telesale:telesale_dev_password@localhost:5432/telesale?sslmode=disable
```

Không commit `.env`. Mật khẩu ở đây chỉ là ví dụ local; nếu đổi mật khẩu trong lệnh Docker thì đổi tương ứng trong URL.

## 3. Chuyển dữ liệu JSON vào PostgreSQL

```powershell
.\.venv\Scripts\python.exe scripts\migrate_catalog.py
```

`scripts/migrate_catalog.py` đọc bốn file `products.json`, `promotions.json`, `inventory_timeline.json`, `crm_seed.json` trong `dataset/BTC-Data-Vong1-TEAMS/catalog/`, tạo schema (kể cả `orders`) và nạp products, variants, promotions, inventory, customers cùng các order có sẵn trong CRM seed. Script **từ chối chạy nếu database đã có bảng ứng dụng**, để không ghi đè dữ liệu. Vì vậy chỉ chạy bước này một lần trên database mới.

## 4. Kiểm tra

```powershell
docker exec telesale-postgres psql -U telesale -d telesale -c "SELECT 'products' AS table_name, count(*) FROM products UNION ALL SELECT 'product_variants', count(*) FROM product_variants UNION ALL SELECT 'promotions', count(*) FROM promotions UNION ALL SELECT 'inventory_events', count(*) FROM inventory_events UNION ALL SELECT 'customers', count(*) FROM customers;"
```

Các bảng trên phải có bản ghi. Nếu muốn kiểm tra một khách hàng mẫu:

```powershell
docker exec telesale-postgres psql -U telesale -d telesale -c "SELECT customer_id, name, phone FROM customers WHERE phone = '0984726714';"
```

Sau này mở máy lại, dùng `docker start telesale-postgres`; không chạy lại bước nạp JSON. PostgreSQL lưu dữ liệu nghiệp vụ; self-learning memory vẫn là file `.md` dưới `CUSTOMER_MEMORY_ROOT`, không có bảng `customer_sessions`.
