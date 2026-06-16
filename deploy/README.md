# 云服务器部署骨架

当前部署骨架用于先把后端 API 跑起来，后续再接入真实 MySQL、Redis 队列、Dify、OSS 和微信支付。

## 1. 服务器建议

第一阶段 POC / 单客户试点：

```text
Ubuntu 22.04
8核 CPU
32GB 内存
200GB SSD
10Mbps+ 带宽
```

## 2. 准备环境变量

复制：

```bash
cp backend/.env.example backend/.env
```

至少确认：

```text
HAIR_AI_DB_PATH=/data/hair_ai.sqlite3
DATABASE_URL=sqlite:////data/hair_ai.sqlite3
REDIS_URL=redis://redis:6379/0
DIFY_BASE_URL=
DIFY_API_KEY=
```

不填 Dify 时，系统使用 Mock AI 生成。

## 3. 启动后端

```bash
docker compose up -d --build
```

验证：

```bash
curl http://127.0.0.1:8000/health
python backend/scripts/smoke_check.py http://127.0.0.1:8000
```

必须看到：

```json
{
  "status": "ok",
  "database": "ok"
}
```

## 4. Nginx

把 `deploy/nginx.hair-ai.conf` 复制到：

```bash
/etc/nginx/sites-available/hair-ai.conf
```

修改：

```text
server_name api.yourdomain.com;
```

启用：

```bash
ln -s /etc/nginx/sites-available/hair-ai.conf /etc/nginx/sites-enabled/hair-ai.conf
nginx -t
systemctl reload nginx
```

生产环境必须配置 HTTPS，微信小程序必须使用 HTTPS 域名。
微信公众平台还需要把 OSS Bucket 的 HTTPS 域名配置为 request 合法域名，供顾客端 PUT 上传自拍。
OSS 的 `temp/` 路径必须配置生命周期自动删除规则，作为后端主动清理临时自拍失败时的兜底。

## 5. 当前保留项

当前 Docker Compose 已预留 Redis 和 MySQL，但后端代码仍使用 SQLite 骨架验证业务逻辑。

MySQL 建表脚本：

```bash
mysql -u hair_ai -p hair_ai < backend/db/schema_mysql.sql
```

切换到 MySQL 时配置：

```text
DATABASE_URL=mysql+pymysql://hair_ai:change_this_password@mysql:3306/hair_ai
MYSQL_INIT_SCHEMA=0
```

如果要让后端启动时自动执行 MySQL 建表脚本：

```text
MYSQL_INIT_SCHEMA=1
```

下一步：

1. 在测试服务器上用 MySQL 跑一轮接口冒烟。
2. AI 任务队列已具备 Redis 骨架，并发限制已配置化，下一步按压测调整 Worker 数量。
3. Dify 配置真实工作流。
4. OSS 替换本地 Mock 临时 URL。
5. 微信支付替换 Mock 支付。
