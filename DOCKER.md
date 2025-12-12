# CloudGather v0.2 Docker 部署指南

## 🐳 快速开始

### 方式一：使用 Docker Run（推荐）

```bash
docker run -d \
  --name cloudgather \
  -p 8080:8080 \
  -v $(pwd)/config:/app/config \
  -v /path/to/source:/source \
  -v /path/to/target:/target \
  -e TZ=Asia/Shanghai \
  -e PUID=1000 \
  -e PGID=1000 \
  --restart unless-stopped \
  moyuemoyun/cloudgather:beta
```

### 方式二：使用 Docker Compose

1. 创建 `docker-compose.yml` 文件（已提供）
2. 修改挂载路径和环境变量
3. 运行：

```bash
docker-compose up -d
```

---

## ⚙️ 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `IS_DOCKER` | `true` | Docker 模式标识（自动设置） |
| `TZ` | `Asia/Shanghai` | 时区设置 |
| `PUID` | `1000` | 运行用户 UID |
| `PGID` | `1000` | 运行用户 GID |
| `STABILITY_DELAY` | `5` | 文件静默期检测延迟（秒） |

---

## 📁 卷挂载说明

### 必需挂载

| 容器路径 | 说明 | 示例 |
|---------|------|------|
| `/app/config` | 配置文件持久化 | `-v ./config:/app/config` |

### 可选挂载（按需配置）

| 容器路径 | 说明 | 示例 |
|---------|------|------|
| `/source` | 源目录 | `-v /mnt/nas/media:/source` |
| `/target` | 目标目录 | `-v /mnt/backup:/target` |

**重要提示**：
- Web 界面中配置任务时，使用**容器内路径**（如 `/source`），而非宿主机路径
- 可以挂载多个目录，使用不同的容器路径

---

## 👤 PUID/PGID 权限设置

### 为什么需要设置？

Docker 容器内的文件操作默认使用 root 用户，可能导致：
- 创建的文件宿主机无法访问
- 宿主机文件容器无法修改
- 权限混乱问题

### 如何获取正确的 UID/GID？

在宿主机上运行：
```bash
id
```

输出示例：
```
uid=1000(username) gid=1000(username) groups=...
```

使用对应的 UID 和 GID 设置环境变量。

### 常见场景

**场景1：NAS 设备（群晖、威联通等）**
```bash
# 通常为 1024 或 1000
-e PUID=1024
-e PGID=100
```

**场景2：Ubuntu/Debian**
```bash
# 通常为 1000
-e PUID=1000
-e PGID=1000
```

**场景3：多用户共享**
```bash
# 使用共享组的 GID
-e PUID=1000
-e PGID=users
```

---

## ⏰ 时区设置

### 为什么需要设置时区？

- 日志时间正确显示
- 定时任务按本地时间执行

### 常见时区

| 地区 | 时区值 |
|------|-------|
| 中国 | `Asia/Shanghai` |
| 美国东部 | `America/New_York` |
| 欧洲伦敦 | `Europe/London` |
| 日本 | `Asia/Tokyo` |

更多时区：https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

---

## 🔍 日志查看

### 查看容器日志

```bash
docker logs cloudgather
```

### 查看实时日志

```bash
docker logs -f cloudgather
```

### 查看最近 100 行

```bash
docker logs --tail 100 cloudgather
```

---

## 📊 监控和管理

### 查看容器状态

```bash
docker ps -a | grep cloudgather
```

### 查看资源使用

```bash
docker stats cloudgather
```

### 重启容器

```bash
docker restart cloudgather
```

### 停止容器

```bash
docker stop cloudgather
```

### 更新镜像

```bash
# 拉取最新镜像
docker pull moyuemoyun/cloudgather:beta

# 停止并删除旧容器
docker stop cloudgather
docker rm cloudgather

# 使用新镜像启动
docker run -d ...
```

---

## 🏷️ 镜像标签说明

| 标签 | 说明 | 推荐用途 |
|------|------|---------|
| `beta` | 测试版本（dev 分支） | 尝鲜新功能 |
| `latest` | 最新稳定版（main 分支） | 生产环境 |
| `v0.2` | 指定版本 | 固定版本部署 |
| `vX.X` | 其他版本号 | 版本锁定 |

---

## 🐛 故障排查

### 问题1：容器无法启动

```bash
# 查看详细错误
docker logs cloudgather

# 检查端口占用
netstat -tuln | grep 8080
```

### 问题2：找不到源目录

**错误**：`源目录不存在: /source`

**原因**：未正确挂载卷或路径配置错误

**解决**：
1. 检查 `-v` 参数是否正确
2. 确保宿主机目录存在
3. Web 界面中使用容器路径（如 `/source`）

### 问题3：权限拒绝

**错误**：`PermissionError: [Errno 13] Permission denied`

**解决**：
1. 检查 PUID/PGID 是否与宿主机用户匹配
2. 确保宿主机目录有正确权限：
```bash
chmod -R 755 /path/to/directory
```

### 问题4：时区不正确

**解决**：
```bash
# 设置正确的时区环境变量
-e TZ=Asia/Shanghai
```

---

## 📝 完整示例

### 群晖 NAS 部署

```bash
docker run -d \
  --name cloudgather \
  -p 8080:8080 \
  -v /volume1/docker/cloudgather/config:/app/config \
  -v /volume1/media:/media \
  -v /volume1/backup:/backup \
  -e TZ=Asia/Shanghai \
  -e PUID=1024 \
  -e PGID=100 \
  --restart unless-stopped \
  moyuemoyun/cloudgather:beta
```

然后在 Web 界面中：
- 源路径：`/media/movies`
- 目标路径：`/backup/movies`

---

## 🔗 相关链接

- Docker Hub: https://hub.docker.com/r/moyuemoyun/cloudgather
- GitHub: https://github.com/moyuemoyun/CloudGather
- 问题反馈: https://github.com/moyuemoyun/CloudGather/issues

---

## 📄 版本历史

### v0.2 (2025-12-12)
- ✨ 新增 PUID/PGID 权限设置
- ⏰ 新增时区配置支持
- 📝 日志增加完整时间信息（年月日时分秒）
- 🐳 提供 Docker 自动构建
- 🚀 支持 amd64 和 arm64 架构

---

**CloudGather（云集）** - 让媒体同步更简单、更智能 🚀
