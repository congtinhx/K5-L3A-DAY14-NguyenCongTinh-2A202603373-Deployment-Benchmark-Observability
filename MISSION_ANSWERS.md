# Day 14 Lab - Mission Answers

> Họ tên / MSSV: xem tên repo.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret trong code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Push code lên GitHub là lộ key và mật khẩu DB; muốn đổi key phải sửa code và deploy lại.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thật, log thấy rõ `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`. Ai đọc được log (log aggregator, đồng nghiệp, dịch vụ bên thứ ba) đều lấy được key.
3. **Dùng `print()` thay vì logging có cấu trúc** (dòng 33, 34, 38): không có level, không có timestamp, không phải JSON nên log aggregator (Loki, Datadog...) không lọc hay parse được; không tắt được log debug khi lên production.
4. **Config cứng, không đọc từ environment** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500`. Muốn đổi giữa dev/staging/prod phải sửa code, vi phạm 12-Factor (Config in env).
5. **Không có health check endpoint** (dòng 42): không có `/health`, `/ready`. Platform (Railway, Render, Kubernetes, load balancer) không biết agent còn sống hay đã treo để restart hoặc ngừng gửi traffic.
6. **Bind `host="localhost"`** (dòng 51): chỉ nhận kết nối từ chính máy đó. Chạy trong container hoặc trên cloud thì bên ngoài không gọi vào được; phải bind `0.0.0.0`.
7. **Port cố định 8000** (dòng 52): Railway/Render cấp port qua biến `PORT`; port cứng làm app không nhận được traffic trên cloud.
8. **`reload=True` khi chạy** (dòng 53): chế độ dev, tốn tài nguyên theo dõi file, có thể tự restart giữa chừng; không dùng cho production.
9. **Không xử lý shutdown**: không có lifespan hay xử lý SIGTERM. Khi platform tắt/redeploy, request đang chạy bị cắt ngang, không có bước dọn dẹp kết nối.

### Exercise 1.2: Chạy bản develop

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
```

```text
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Log của server:

```text
Starting agent on localhost:8000...
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
INFO:     127.0.0.1:33508 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Quan sát:** app chạy được và trả 200, nhưng chưa production-ready: secret lộ ngay trong log, chỉ nghe ở `localhost:8000`, chạy chế độ reload, không có health check.

### Exercise 1.3: So sánh với bản production

Chạy bản production:

```bash
cd ../production
cp .env.example .env
pip install -r requirements.txt
python app.py
```

```text
WARNING:root:OPENAI_API_KEY not set — using mock LLM
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":53.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T10:30:59.262374+00:00"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`OPENAI_API_KEY`, `DEBUG = True`, `MAX_TOKENS`) | Đọc từ env qua `config.py` (`os.getenv("PORT")`, `AGENT_API_KEY`, `DEBUG`...), mẫu trong `.env.example`; `validate()` báo lỗi nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` | Một image chạy được ở mọi môi trường, đổi config không cần sửa code; secret không nằm trong git |
| Secret | Key và mật khẩu DB ghi thẳng trong code, còn in ra log | Không có giá trị nhạy cảm trong code; log chỉ ghi `question_length`, `client_ip`, không log key | Tránh lộ key qua GitHub và qua log |
| Health check | Không có | `GET /health` (liveness, trả uptime/version/env) và `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform biết khi nào restart container và khi nào được gửi traffic vào |
| Logging | `print()` dạng text tự do | `logging` có level, định dạng JSON (`{"time":...,"level":...,"msg":...}`), sự kiện `agent_request` / `agent_response` | Log aggregator parse/lọc được; tắt được log debug ở production |
| Shutdown | Đột ngột, không xử lý | `lifespan` của FastAPI: khi tắt đặt `is_ready = False`, chờ request đang chạy, log `Shutdown complete`; có đăng ký handler SIGTERM | Redeploy/scale down không cắt ngang request của người dùng |
| Host / Port | `localhost:8000` cố định | `HOST` (mặc định `0.0.0.0`) và `PORT` từ env | Chạy được trong container và trên cloud (Railway/Render inject `PORT`) |
| Reload / Debug | `reload=True` luôn bật | `reload=settings.debug`, mặc định `DEBUG=false` | Production không chạy chế độ dev |
| Input | `question` qua query string, không kiểm tra | Body JSON, thiếu `question` → 422 có thông báo rõ | Lỗi đầu vào được báo rõ ràng cho client |
| CORS | Không cấu hình | `CORSMiddleware` với `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép mới gọi API từ trình duyệt |

**Checkpoint 1:**
- Hardcode secret nguy hiểm vì code được chia sẻ (git, review, image Docker) còn secret thì không được chia sẻ; secret lộ trong lịch sử git không xoá được bằng cách xoá file.
- Dùng env vars: `os.getenv("TÊN_BIẾN", "mặc định")`, giá trị thật đặt trong `.env` (đã nằm trong `.gitignore`) hoặc trên dashboard của platform.
- Health check cho platform biết process còn sống (liveness) và sẵn sàng nhận traffic (readiness).
- Graceful shutdown: khi nhận SIGTERM thì ngừng nhận request mới, xử lý xong request đang chạy, đóng kết nối rồi mới thoát.

## Part 2: Docker

### Exercise 2.1: Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (dòng `FROM python:3.11`), bản Python đầy đủ trên Debian, có sẵn compiler và nhiều công cụ nên rất nặng.
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer. Copy `requirements.txt` và `pip install` trước, copy code (`app.py`) sau, thì khi chỉ sửa code, Docker dùng lại layer đã cài dependencies và chỉ build lại các bước COPY code, nhanh hơn nhiều. Nếu `COPY . .` trước rồi mới cài, mỗi lần sửa một dòng code là phải cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/tham số mặc định, bị thay thế khi truyền lệnh khác lúc `docker run <image> <lệnh khác>`. `ENTRYPOINT` là chương trình cố định luôn chạy; tham số truyền lúc `docker run` (hoặc `CMD`) được nối thêm vào sau nó. Dockerfile này dùng `CMD ["python", "app.py"]` (exec form).

### Exercise 2.2: Build và run

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run --rm -p 8000:8000 my-agent:develop
```

Build xong sau `268.1s` (phần lớn là tải base image `python:3.11`, một layer đã 237 MB). Container chạy:

```text
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:51674 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

```text
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Request đến từ `172.17.0.1` (gateway của Docker bridge), tức là đi từ máy host vào container qua port mapping `-p 8000:8000`.

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 `builder`** (`FROM python:3.11-slim AS builder`): cài công cụ build `gcc`, `libpq-dev` bằng `apt-get`, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này chỉ dùng để build, không được deploy.
- **Stage 2 `runtime`** (`FROM python:3.11-slim AS runtime`): bắt đầu lại từ base slim sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` (các package đã cài) cùng `main.py` và `utils/mock_llm.py`, `chown` cho `appuser`, `USER appuser`, có `HEALTHCHECK` gọi `/health`, `CMD` chạy `uvicorn ... --workers 2`.
- **Vì sao image nhỏ hơn:** (1) base `python:3.11-slim` thay vì `python:3.11` full; (2) `gcc`, header, apt cache và pip cache chỉ nằm ở stage builder, image cuối không mang theo; (3) chỉ copy đúng file cần chạy.

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images | grep my-agent
```

```text
my-agent:advanced              f54fbf36715a        240MB         57.4MB
my-agent:develop               711652b77d7b       1.67GB          426MB
```

(Cột 1: disk usage, cột 2: content size, theo `docker images` của Docker Desktop.)

| Image | Disk usage | Content size |
|---|---:|---:|
| `my-agent:develop` (single-stage, `python:3.11`) | 1.67 GB ≈ 1670 MB | 426 MB |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 240 MB | 57.4 MB |
| **Chênh lệch** | **giảm ≈ 85.6%** ((1670 − 240) / 1670) | **giảm ≈ 86.5%** ((426 − 57.4) / 426) |

Image production nhỏ hơn khoảng 7 lần và dưới mức 500 MB. Ngoài ra chạy bằng user non-root, có HEALTHCHECK nên an toàn hơn.

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

```bash
cd 02-docker/production
touch .env.local            # compose cần file này (env_file), để trống vì dùng mock LLM; đã nằm trong .gitignore
docker compose -p k5-day14-docker up -d --build
docker compose -p k5-day14-docker ps
```

```text
NAME                       IMAGE                   SERVICE   STATUS                           PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up 1 second (health: starting)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up 1 second                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up 14 seconds (healthy)          6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up 13 seconds (healthy)          6379/tcp
```

**Các service được start:** `agent` (build từ `02-docker/production/Dockerfile`, target `runtime`), `redis` (`redis:7-alpine`), `qdrant` (`qdrant/qdrant:v1.9.0`), `nginx` (`nginx:alpine`). Compose cũng tạo network `k5-day14-docker_internal` và 2 volume `redis_data`, `qdrant_data`.

**Sơ đồ kiến trúc:**

```text
                 ┌──────────────────────── network "internal" (bridge) ────────────────────────┐
                 │                                                                              │
 Client ──:80──▶ │  nginx (reverse proxy, rate limit 10r/s,      ──▶  agent :8000              │
 (curl)          │         security headers)                          (FastAPI, uvicorn         │
                 │   upstream agent_backend = agent:8000               2 workers, non-root)     │
                 │                                                      │            │          │
                 │                                                      ▼            ▼          │
                 │                                            redis :6379      qdrant :6333    │
                 │                                            (cache, rate     (vector DB      │
                 │                                             limit)           cho RAG)       │
                 │                                            volume redis_data volume qdrant_data
                 └──────────────────────────────────────────────────────────────────────────────┘
```

**Các service giao tiếp thế nào:**
- Chỉ `nginx` publish port ra máy host (`80:80`, `443:443`). `agent`, `redis`, `qdrant` chỉ có port nội bộ (`8000/tcp`, `6379/tcp`, `6333-6334/tcp`), bên ngoài không gọi trực tiếp được.
- Tất cả nằm chung network `internal`, gọi nhau bằng **tên service** nhờ DNS nội bộ của Docker: nginx `proxy_pass http://agent_backend` với `server agent:8000`; agent dùng `REDIS_URL=redis://redis:6379/0` và `QDRANT_URL=http://qdrant:6333`.
- Thứ tự khởi động: `agent` có `depends_on` `redis` và `qdrant` với `condition: service_healthy`, nên chỉ start sau khi 2 service đó healthy (log: `qdrant-1 Healthy 10.0s`, `redis-1 Healthy 16.0s`, rồi `agent-1 Started 14.4s`). `nginx` `depends_on` `agent`.
- Secret không ghi trong compose mà đọc từ `env_file: .env.local` (ngoài git).

**Test qua Nginx:**

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":17.6,"version":"2.0.0","timestamp":"2026-11-25T10:50:36.845818"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Header `Server: nginx` và các header bảo mật (`X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`) do nginx thêm vào, chứng tỏ request đi qua Nginx rồi mới tới agent.

**Ghi chú:** comment đầu file ghi agent "2 replicas" nhưng compose không khai báo `deploy.replicas`, nên `ps` chỉ có 1 container `agent-1`. Muốn 2 instance phải chạy thêm `--scale agent=2`. Compose cũng cảnh báo thuộc tính `version: "3.9"` đã lỗi thời và bị bỏ qua.

**Checkpoint 2:** debug container bằng `docker compose -p k5-day14-docker logs agent` (xem log), `docker exec -it k5-day14-docker-agent-1 sh` (vào trong container), `docker compose -p k5-day14-docker ps` (xem trạng thái health).

## Part 3: Cloud Deployment

_(làm sau Part 6)_

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/`)

```bash
cd 04-api-gateway/develop
pip install -r requirements.txt
AGENT_API_KEY=secret-key-123 python app.py
```

**Không có key → 401:**

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

**Có key đúng → 200:**

```text
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

**Key sai → 403:**

```text
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}
```

App mẫu phân biệt **thiếu key → 401** (chưa xác thực) và **sai key → 403** (bị từ chối). Lưu ý: hợp đồng của Part 6 yêu cầu cả thiếu và sai key đều trả **401**, nên `06-lab-complete/app/auth.py` không làm giống app mẫu ở điểm này. Key được đọc từ biến môi trường `AGENT_API_KEY`, không ghi trong code.

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

```bash
cd ../production
pip install -r requirements.txt
python app.py
```

Lấy token bằng tài khoản `student` / `demo123` (token đã được che):

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"eyJhbGciOiJIUzI1NiIs...<đã che>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."}
```

**Có token → 200:**

```text
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

**Không có token → 401:**

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

**JWT khác API key thế nào:** API key là chuỗi bí mật cố định, không tự hết hạn, server phải so với giá trị lưu sẵn. JWT là token có chữ ký số (HS256), chứa thông tin user (`sub: student`, `role: user`), thời điểm tạo (`iat`) và hết hạn (`exp`, ở đây 60 phút). Server chỉ cần kiểm chữ ký là tin được nội dung, không cần tra database, và có thể phân quyền theo `role` (user khác admin về rate limit).

### Exercise 4.3: Rate limiting

Tài khoản `student` (role `user`) giới hạn 10 request / 60 giây. Gọi liên tục 15 lần ngay sau request "Explain JWT" ở trên:

```bash
for i in $(seq 1 15); do
  echo -n "Request $i: "
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/ask \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\":\"Test $i\"}"
done
```

```text
Request 1: 200
Request 2: 200
Request 3: 200
Request 4: 200
Request 5: 200
Request 6: 200
Request 7: 200
Request 8: 200
Request 9: 200
Request 10: 429
Request 11: 429
Request 12: 429
Request 13: 429
Request 14: 429
Request 15: 429
```

Chỉ 9 request trong vòng lặp được 200 vì request "Explain JWT" trước đó đã dùng 1 lượt (response báo `requests_remaining: 9`): 1 + 9 = 10 request trong 60 giây, request thứ 11 trở đi bị chặn.

**Response 429 đầy đủ:**

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795621762
retry-after: 58

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
```

**Cách hoạt động (`rate_limiter.py`):** thuật toán **sliding window**. Mỗi user có một `deque` lưu timestamp các request. Mỗi lần gọi, bỏ các timestamp cũ hơn 60 giây; nếu số còn lại ≥ `max_requests` thì trả 429 kèm header `Retry-After` (số giây đến khi request cũ nhất rơi khỏi cửa sổ) và `X-RateLimit-*`; nếu chưa thì thêm timestamp hiện tại. Role `admin` dùng limiter riêng với giới hạn cao hơn. Hạn chế: state nằm trong RAM của một process, nên khi chạy nhiều instance hoặc restart thì mất. Production cần chuyển sang Redis (sorted set: `ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `EXPIRE`), đúng như yêu cầu Part 6.

### Exercise 4.4: Cost guard

Usage sau khi chạy (cùng user `student`):

```text
$ curl -s http://localhost:8000/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":284,"cost_usd":0.000176,"budget_usd":1.0,"budget_remaining_usd":0.999824,"budget_used_pct":0.0}
```

`requests: 10` khớp với 10 request được 200 ở trên; 6 request bị 429 không được tính tiền vì rate limit chặn trước khi gọi LLM.

**Cách làm của `cost_guard.py` trong app mẫu:**
1. **Trước khi gọi LLM**, `/ask` gọi `cost_guard.check_budget(username)`:
   - Tổng chi phí toàn hệ thống trong ngày ≥ `global_daily_budget_usd` ($10) → **503** (bảo vệ tiền của cả dịch vụ).
   - Chi phí của user trong ngày ≥ `daily_budget_usd` ($1) → **402 Payment Required**, kèm `used_usd`, `budget_usd`, `resets_at`.
   - Dùng ≥ 80% budget → log cảnh báo.
2. **Sau khi gọi LLM**, `cost_guard.record_usage(username, input_tokens, output_tokens)` cộng token và tính tiền theo giá gpt-4o-mini: $0.00015 / 1K input, $0.0006 / 1K output. Kiểm tra: 40 input + 284 output → 0.04 × 0.00015 + 0.284 × 0.0006 = 0.000006 + 0.0001704 = **$0.0001764**, khớp `cost_usd: 0.000176`.
3. Record gắn với ngày (`day`); sang ngày mới thì tạo record mới, tức budget reset mỗi ngày.

**Hạn chế và cách làm đúng hơn:** state nằm trong dict trong RAM, mất khi restart và không dùng chung giữa các instance. Theo đề (budget $10/tháng, lưu trong Redis), cách làm là dùng key `budget:<user_id>:<YYYY-MM>`: đọc tổng hiện tại, nếu `hiện tại + chi phí ước tính > 10` thì chặn (402), nếu không thì `INCRBYFLOAT` cộng chi phí và `EXPIRE` khoảng 32 ngày để key tự hết hạn, nên tự reset đầu tháng. Part 6 làm theo hướng này (`check_budget` trước, `record_cost` sau, lưu Redis).

**Quan sát thêm:** trong response `/ask`, trường `usage.budget_remaining_usd` thực ra trả `usage.total_cost_usd` (tổng đã dùng, 1.6e-05), không phải phần còn lại; số đúng xem ở `/me/usage` (`budget_remaining_usd: 0.999824`).

**Checkpoint 4:** rate limit bảo vệ **tốc độ** (chống spam, quá tải, một user chiếm hết tài nguyên); cost guard bảo vệ **tiền** (kể cả khi gọi chậm, dưới rate limit, nhưng câu hỏi dài/token nhiều vẫn có thể đốt hết ngân sách). Cần cả hai vì chúng chặn hai kiểu rủi ro khác nhau.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/`)

```bash
cd 05-scaling-reliability/develop
pip install -r requirements.txt
python app.py
```

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":16.1,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T15:53:12.749902+00:00","checks":{"memory":{"status":"ok","used_percent":38.6}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

- **`/health` — liveness probe** ("process còn sống không?"): trả 200 kèm `status`, `uptime_seconds`, `version`, `environment` và các check nhẹ (ở đây là memory qua `psutil`; memory ≥ 90% thì `degraded`). Platform (Railway, Render, Kubernetes) gọi định kỳ; non-200 hoặc timeout thì **restart** container. Liveness không nên phụ thuộc DB/Redis, nếu không Redis chết sẽ làm platform restart agent vô ích.
- **`/ready` — readiness probe** ("có nên gửi traffic vào không?"): trả **503** khi `_is_ready = False` (đang khởi động, đang shutdown, hoặc dependency như Redis/DB chưa kết nối), 200 khi sẵn sàng. Load balancer dùng nó để **ngừng route traffic** vào instance đó, không restart. `in_flight_requests: 1` là chính request `/ready` đang được middleware `track_requests` đếm.

### Exercise 5.2: Graceful shutdown

App dùng `lifespan` của FastAPI: khi shutdown đặt `_is_ready = False` (để `/ready` trả 503, `/ask` từ chối request mới), rồi chờ `_in_flight_requests` về 0 (tối đa 30 giây) mới thoát; `uvicorn.run(..., timeout_graceful_shutdown=30)`. Có thêm handler `SIGTERM`/`SIGINT` để ghi log.

Test: bật server, chờ `/health` sẵn sàng, gửi một request rồi gửi SIGTERM sau 0.05 giây:

```bash
python app.py &
PID=$!
until curl -s http://localhost:8000/health > /dev/null; do sleep 0.5; done
curl -s -w "\nHTTP %{http_code}\n" -X POST "http://localhost:8000/ask?question=Long%20task" &
sleep 0.05
kill -TERM $PID
wait
```

```text
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:33010 - "GET /health HTTP/1.1" 200 OK
>>> Server đã sẵn sàng, gửi request rồi SIGTERM ngay
INFO:     Shutting down
INFO:     127.0.0.1:33016 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
HTTP 200
INFO:     Waiting for application shutdown.
2026-11-25 15:55:36,333 INFO 🔄 Graceful shutdown initiated...
2026-11-25 15:55:36,333 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [21861]
2026-11-25 15:55:36,334 INFO Received signal 15 — uvicorn will handle graceful shutdown
[1]-  Done                    python app.py
```

**Kết quả:** uvicorn nhận SIGTERM và in `Shutting down` **trước**, nhưng request `/ask` đang chạy vẫn hoàn thành với **HTTP 200** và có câu trả lời. Sau đó lifespan chạy phần shutdown (`Graceful shutdown initiated` → `Shutdown complete`), process thoát bình thường (`Done`, không phải `Killed`).

**Bài học từ lần thử đầu:** lần đầu tôi gửi request sau `sleep 3` cố định, server chưa khởi động xong nên curl báo `HTTP 000` (exit 7, không kết nối được) và process bị kill khi còn đang import (`Terminated`). Phải chờ `/health` trả 200 rồi mới test, cũng là lý do platform cần health check trước khi gửi traffic.

**Lưu ý:** handler `signal.signal(SIGTERM, ...)` của app được đăng ký lúc import, nhưng `uvicorn.run` cài lại handler riêng, nên dòng `Received signal 15` chỉ in ra ở cuối. Nếu tự đăng ký handler SIGTERM mà không gọi lại handler của uvicorn thì process sẽ không tắt (đây là lưu ý trong TODO của Part 6).

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

- **Anti-pattern:** lưu `conversation_history` trong dict của process. Khi chạy nhiều instance sau load balancer, request 1 của user A vào instance 1 (lưu history trong RAM instance 1), request 2 vào instance 2 → không thấy history. Restart hoặc scale down cũng làm mất state.
- **Bản production:** mọi state lưu trong **Redis** (`REDIS_URL`): `save_session()` dùng `SETEX session:<id>` với TTL 3600 giây, `load_session()` đọc lại, `append_to_history()` giữ tối đa 20 message gần nhất. Instance nào cũng đọc được session của user. Mỗi instance có `INSTANCE_ID` riêng và trả trong `served_by` để thấy request đi qua instance nào. Nếu không kết nối được Redis, app rơi về `_memory_store` và log `In-memory ⚠️` (chỉ để chạy demo, không an toàn khi scale).

### Exercise 5.4: Load balancing (`05-scaling-reliability/production/`)

```bash
cd 05-scaling-reliability/production
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
docker compose -p k5-day14-scaling ps
```

```text
NAME                       SERVICE   STATUS                            PORTS
k5-day14-scaling-agent-1   agent     Up 3 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-2   agent     Up 2 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-3   agent     Up 2 seconds (health: starting)   8000/tcp
k5-day14-scaling-nginx-1   nginx     Up 1 second                       0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis     Up 14 seconds (healthy)           6379/tcp
```

3 instance agent + 1 Redis + 1 Nginx; chỉ Nginx mở cổng ra ngoài (`8080->80`). Agent chỉ start sau khi Redis healthy (`redis-1 Healthy 14.2s`), log mỗi agent có `✅ Connected to Redis` và `Storage: Redis ✅`.

Gọi 10 request vào `POST /chat` và đọc header `X-Served-By` (Nginx gắn `$upstream_addr`):

```bash
for i in $(seq 1 10); do
  curl -s -o /dev/null -D - -X POST http://localhost:8080/chat -H "Content-Type: application/json" \
    -d "{\"question\":\"Request $i\"}" | grep -i x-served-by
done
```

```text
X-Served-By: 172.19.0.4:8000
X-Served-By: 172.19.0.3:8000
X-Served-By: 172.19.0.5:8000
X-Served-By: 172.19.0.4:8000
X-Served-By: 172.19.0.3:8000
X-Served-By: 172.19.0.5:8000
X-Served-By: 172.19.0.4:8000
X-Served-By: 172.19.0.3:8000
X-Served-By: 172.19.0.5:8000
X-Served-By: 172.19.0.4:8000
```

**Quan sát:** request được chia lần lượt cho 3 IP khác nhau theo vòng `.4 → .3 → .5` (**round-robin**, mặc định của Nginx): `.4` nhận 4 request, `.3` và `.5` mỗi IP 3 request. Nginx tìm các instance qua DNS của Docker: `upstream agent_cluster { server agent:8000; }` với `resolver 127.0.0.11 valid=10s`, tên `agent` phân giải ra IP của cả 3 container. Log `docker compose logs agent` cho thấy cả `agent-1`, `agent-2`, `agent-3` đều nhận `POST /chat` 200.

**Nếu 1 instance chết:** `nginx.conf` có `proxy_next_upstream error timeout http_503;` và `proxy_next_upstream_tries 3;`, nên request gặp lỗi kết nối, timeout hoặc 503 (instance đang shutdown, `/ready` không sẵn sàng) sẽ được Nginx thử lại ở instance khác; người dùng không thấy lỗi.

### Exercise 5.5: Test stateless

```bash
python test_stateless.py
```

```text
Session ID: 3ae744e8-1484-4380-a1ae-8bd6751e70e7

Request 1: [instance-e8f2a5]   Q: What is Docker?
Request 2: [instance-73d0ad]   Q: Why do we need containers?
Request 3: [instance-29951e]   Q: What is Kubernetes?
Request 4: [instance-e8f2a5]   Q: How does load balancing work?
Request 5: [instance-73d0ad]   Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-e8f2a5', 'instance-29951e', 'instance-73d0ad'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu hỏi trong **cùng một session** được phục vụ bởi **cả 3 instance** khác nhau (`instance-e8f2a5` = agent-1, `instance-29951e` = agent-2, `instance-73d0ad` = agent-3, đối chiếu với log `Starting instance ...`). Dù vậy, khi đọc lại history (`GET /chat/<session_id>/history`, phục vụ bởi agent-2 theo log) vẫn đủ **10 message** (5 câu hỏi + 5 câu trả lời) theo đúng thứ tự. Lý do: không instance nào giữ history trong RAM; mỗi request đọc session từ Redis (`session:<id>`), thêm message rồi ghi lại. Nếu lưu trong RAM, mỗi instance chỉ thấy 1–2 câu của mình và history sẽ bị thiếu.

Script không tự tắt instance nào (như README K5 ghi chú). Nhưng vì state nằm hết trong Redis, tắt hay restart một agent cũng không mất history; chỉ mất khi Redis mất dữ liệu (hoặc hết TTL 3600 giây).

Dọn dẹp:

```bash
docker compose -p k5-day14-scaling down
```

**Checkpoint 5:**
- Liveness (`/health`) trả lời "process còn sống không?", sai thì platform **restart**; readiness (`/ready`) trả lời "có nhận traffic được không?", sai thì load balancer **ngừng gửi request**, không restart.
- State trong RAM hỏng khi chạy nhiều instance vì mỗi instance có bộ nhớ riêng, request của cùng một user rơi vào instance khác nhau; state phải nằm ở nơi dùng chung (Redis).

## Part 6: Output check_production_ready.py

Chạy đầy đủ (có Docker) trong `06-lab-complete/`:

```bash
cd 06-lab-complete
pip install -r requirements.txt
python check_production_ready.py
```

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Một số số đo trong lần chạy: build image 115s, **image 238 MB** (< 500 MB), rate limit trả 429 sau 5 request thành công (`RATE_LIMIT_PER_MINUTE=5`) và vẫn 429 sau khi restart agent (state trong Redis), cost guard trả 402 khi budget 0.000001 USD, 17 dòng log JSON hợp lệ, SIGTERM khi đang có request → request vẫn 200 và process thoát exit code 0, `docker stop` thoát exit code 0 sau 1.3s.

**Lần chạy đầu tiên chỉ đạt 5/12** do môi trường, không phải do code: (1) máy chưa có Redis cho script test (`không có REDIS_URL, redis-server hay Docker`) nên mọi `/ask` trả 503 — sửa bằng `sudo apt install -y redis-server`; (2) `docker build` lỗi `error getting credentials` vì Docker trong WSL gọi credential helper của Windows bị timeout — sửa bằng cách tắt `credsStore` trong `~/.docker/config.json`.

### Thiết kế

| File | Cách làm |
|---|---|
| `app/config.py` | Dataclass `Settings`, mọi giá trị đọc bằng `os.getenv` (`PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`). `AGENT_API_KEY` không có mặc định. Nạp `.env` khi chạy local nhưng không ghi đè biến đã có |
| `app/auth.py` | `APIKeyHeader("X-API-Key", auto_error=False)`; thiếu, sai, hoặc server chưa cấu hình key → **401** (fail closed); so sánh bằng `hmac.compare_digest` |
| `app/redis_client.py` | `redis.from_url` không kết nối lúc import → app khởi động được khi chưa có Redis; timeout 1s; `redis_healthy()` = `PING` |
| `app/rate_limiter.py` | Sliding window 60s bằng sorted set Redis theo hash của API key, một transaction `ZREMRANGEBYSCORE → ZADD → ZCARD → EXPIRE`; vượt thì xoá lượt vừa ghi và trả **429** + `Retry-After`; Redis lỗi → 503 |
| `app/cost_guard.py` | `check_budget()` trước khi gọi LLM: tổng `cost:daily:YYYY-MM-DD` hoặc `cost:monthly:YYYY-MM` ≥ budget → **402**. `record_cost()` sau khi gọi: `INCRBYFLOAT` + `EXPIRE` (2 ngày / 32 ngày) nên tự reset |
| `app/main.py` | Logger JSON (`JsonFormatter` + `json.dumps`) cho startup, mỗi request, mỗi lần gọi LLM, shutdown. `/health` luôn 200 (không kiểm Redis), `/ready` 503 khi Redis không `PING` được. `/ask`: auth → rate limit → budget → LLM → ghi chi phí. Lỗi validate → 422 gọn, lỗi bất ngờ → 500 `Internal server error` (traceback chỉ nằm trong log). Graceful shutdown qua `lifespan` + cơ chế của uvicorn, không tự đăng ký handler SIGTERM |
| `Dockerfile` | Multi-stage: builder `pip install --prefix=/install`, runtime `python:3.11-slim` chỉ copy package + `app/` + `utils/`, user `agent` non-root, `HEALTHCHECK` gọi `/health`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --timeout-graceful-shutdown 8"]` để uvicorn là PID 1 |
| `docker-compose.yml` | `agent` build từ Dockerfile, `env_file .env (required: false)`, `REDIS_URL=redis://redis:6379/0`, `depends_on redis (service_healthy)`; `redis:7-alpine` có healthcheck và volume |
| `railway.toml` / `render.yaml` | Railway: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`. Render: web `runtime: docker`, `healthCheckPath: /health`, `AGENT_API_KEY` dùng `sync: false`, `REDIS_URL` lấy từ service Key Value |

## AI log

| # | Hỏi AI gì | Nhận được gì | Tôi tự kiểm tra / sửa thế nào |
|---|---|---|---|
| 1 | Nhờ Claude đọc toàn bộ đề, giải thích yêu cầu, luật và hướng dẫn cài đặt (WSL2, Docker Desktop, VS Code) | Tóm tắt rubric, các file không được sửa, các bước setup | Tự cài WSL Ubuntu-24.04, Docker Desktop; kiểm tra bằng `python3 --version` (3.12.3), `docker run --rm hello-world`, `os.name` = `posix` |
| 2 | Lỗi `sudo: Authentication failed` và Python 3.14 | Claude chỉ ra đang mở nhầm distro WSL khác, hướng dẫn `wsl --set-default Ubuntu-24.04` | Mở đúng Ubuntu-24.04 (user `tnh_n_l`), Python 3.12.3 |
| 3 | `git status` báo mọi file bị modified | Nguyên nhân là CRLF (clone bằng Git Windows); sửa bằng `git config core.autocrlf true` | Chạy `git status` → working tree clean, xác nhận không sửa `check_production_ready.py` và `golden_dataset.jsonl` |
| 4 | Nhờ Claude soạn phần trả lời Part 1, 2, 4 và 5 trong file này | Danh sách anti-pattern kèm số dòng, bảng so sánh develop/production | Tự chạy cả hai bản, output curl và log trong bài là của tôi; đã đối chiếu từng dòng code được trích với `develop/app.py`, `production/app.py`, `production/config.py` |
| 5 | Nhờ Claude viết code Part 6 (các TODO trong `06-lab-complete/`: `app/*.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) | Code đáp ứng bảng hợp đồng trong `06-lab-complete/README.md` | Tự chạy `python check_production_ready.py` đầy đủ trên máy (WSL + Docker): lần đầu 5/12 do thiếu Redis và lỗi credentials Docker, sửa môi trường rồi chạy lại đạt PASS 12/12. Không sửa `check_production_ready.py` |
| 6 | Lỗi `error getting credentials` khi `docker build` và thiếu Redis cho script chấm | Claude hướng dẫn cài `redis-server` trong WSL và tắt `credsStore` trong `~/.docker/config.json` | `docker pull python:3.11-slim` chạy được, script chấm tự bật redis-server tạm thời |
