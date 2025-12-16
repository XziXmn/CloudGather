# CloudGather（云集）

<div align="center">

**基于飞牛OS的媒体文件同步工具**

[![Docker Image](https://img.shields.io/badge/docker-xzixmn%2Fcloudgather-blue)](https://hub.docker.com/r/xzixmn/cloudgather)
[![Version](https://img.shields.io/badge/version-0.2-green)](https://github.com/xzixmn/cloudgather)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

专为飞牛OS设计，将本地下载的影视资源自动备份到网盘，配合strm文件实现302播放

</div>

---

## ✨ 特性

- 🎬 **影视备份** - 本地下载资源自动备份到CloudDrive网盘挂载
- 🚀 **网盘优化** - 针对网盘挂载优化，智能限流与重试机制
- 📅 **定时同步** - Cron表达式定时任务，深夜自动备份不占带宽
- 📊 **实时进度** - 任务执行进度实时展示，文件统计一目了然
- 🎯 **增量备份** - 智能跳过已存在文件，仅同步新增内容
- 🌐 **现代UI** - 简洁美观的Web界面，支持深色模式
- 📝 **完整日志** - 分级日志记录，备份过程可追溯

## 🎯 完整工作流程

### 第一步：本地下载影视资源
使用qBittorrent、Transmission等工具下载到本地：
```
下载工具 → 飞牛OS本地存储 (/vol1/downloads/影视)
```

### 第二步：自动备份到网盘（CloudGather）
定时将本地资源备份到挂载的网盘：
```
本地存储 (/vol1/downloads/影视) → CloudDrive挂载 (/CloudDrive/影视库)
```

### 第三步：生成strm文件
使用strm生成工具创建302播放文件：
```
挂载的网盘链接 → strm文件 → Emby/Jellyfin/Plex
```

### 第四步：媒体服务器刮削
媒体服务器读取strm文件，实现302直链播放，**无需占用本地空间**！

## 🚀 快速开始

### Docker Compose 部署（推荐）

1. **创建 `docker-compose.yml`**

```yaml
services:
  cloudgather:
    image: xzixmn/cloudgather:beta
    container_name: cloudgather
    
    volumes:
      # 配置文件持久化
      - ./config:/app/config
      - ./logs:/app/logs
      # 挂载你的源目录和目标目录
      - /vol1/downloads:/downloads       # 本地下载目录（源）
      - /CloudDrive:/CloudDrive          # CloudDrive挂载点（目标）
      - /vol2/media:/media               # 其他存储池（可选）
    
    ports:
      - '3602:3602'
    
    environment:
      - TZ=Asia/Shanghai                 # 时区
      - IS_DOCKER=true
      - PUID=1000                        # 用户ID
      - PGID=1001                        # 用户组ID
      - LOG_LEVEL=INFO                   # 日志级别
      - CONSOLE_LEVEL=INFO               # 控制台日志级别
      - LOG_SAVE_DAYS=7                  # 日志保留天数
    
    restart: always
```

2. **启动服务**

```bash
docker-compose up -d
```

3. **访问界面**

打开浏览器访问：`http://飞牛OS的IP:3602`


## 📖 使用指南

### 创建同步任务

1. **基本信息**
   - 任务名称：例如「电影备份到123云盘」
   - 源路径：本地下载目录（如 `/vol1/downloads/电影`）
   - 目标路径：CloudDrive挂载目录（如 `/CloudDrive/影视库/电影`）

2. **同步规则**（可多选）
   - ✅ **文件不存在**：仅同步目标目录不存在的文件（推荐）
   - 📏 **大小不同**：文件大小不一致时同步
   - ⏰ **时间更新**：源文件更新时间更新时同步

3. **调度设置**
   - 使用Cron表达式设置定时任务
   - 支持预设模板（每小时、每天、每周等）
   - 支持随机时间生成，避免高峰期

4. **高级选项**
   - 🔧 **线程数**：建议设置为 1-2（网盘上传并发过高易失败）
   - 🌐 **慢速存储**：**必须勾选**，自动优化网盘上传（限流+重试）

### 网盘备份优化

针对CloudDrive网盘挂载场景（**推荐配置**）：

- ✅ **必须勾选**"目标是 NAS/网盘挂载"选项
- 系统自动优化：
  - 限制线程数 ≤ 4（避免网盘限流）
  - 延长超时时间（适应网络波动）
  - 增加重试次数（提高成功率）
  - 稳定上传大文件

### 高级工具

每个任务卡片提供快捷操作：

- ▶️ **立即运行**：手动触发一次同步
- 📝 **查看日志**：独立日志窗口，支持滚动浏览
- 🔧 **高级工具**：全量覆盖等高级操作

## ⚙️ 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `TZ` | 时区设置 | `Asia/Shanghai` |
| `PUID` | 运行用户ID | `1000` |
| `PGID` | 运行用户组ID | `1001` |
| `LOG_LEVEL` | 文件日志级别 | `INFO` |
| `CONSOLE_LEVEL` | 控制台日志级别 | `INFO` |
| `LOG_SAVE_DAYS` | 日志保留天数 | `7` |

日志级别可选：`DEBUG`, `INFO`, `WARNING`, `ERROR`

## 📁 目录结构

```
CloudGather/
├── config/           # 配置文件目录（持久化）
│   └── tasks.json   # 任务配置
├── logs/            # 日志文件目录
│   └── cloudgather.log
├── core/            # 核心模块
├── static/          # 前端资源
└── html/            # 模板文件
```

## 🔧 技术栈

- **后端**: Python + Flask
- **调度**: APScheduler（支持Cron表达式）
- **前端**: HTML + Tailwind CSS
- **容器**: Docker

## 💡 常见问题

### Q1: 为什么要备份到网盘而不是直接下载到网盘？
**A**: 本地下载速度快且稳定，下载完成后再备份到网盘，确保资源完整性。配合strm实现302播放，既节省本地空间又能流畅观看。

### Q2: CloudDrive上传失败怎么办？
**A**: 
  1. **必须勾选**"慢速存储"选项
  2. 线程数设置为 1 或 2
  3. 避开网络高峰期（推荐深夜定时同步）
  4. 检查CloudDrive挂载状态是否正常

### Q3: 如何避免重复上传已存在的文件？
**A**: 使用默认的"文件不存在"规则，系统会智能跳过网盘已存在的文件，仅上传新增内容。

### Q4: 支持哪些网盘？
**A**: 支持通过**飞牛OS原生挂载**或**CloudDrive**挂载的所有网盘（阿里云盘、百度网盘、OneDrive等）。

### Q5: 如何配合strm使用？
**A**: CloudGather负责备份，备份完成后使用strm生成工具（如AutoFilm）创建strm文件，最后在Emby/Jellyfin中添加媒体库即可。

### Q6: 飞牛OS上如何设置PUID和PGID？
**A**: SSH连接到飞牛OS，执行 `id 用户名` 查看对应的UID和GID。

## 🗺️ 路线图

- [x] Cron定时调度
- [x] 实时进度条
- [x] 网盘上传优化（限流+重试）
- [x] 日志自动清理
- [ ] 文件过滤规则（扩展名、大小、排除目录）
- [ ] 上传速度限制（避免占满带宽）
- [ ] 备份完成通知（微信/邮件）
- [ ] 未知


## 📄 许可证

MIT License

## 🙏 致谢

不知道致谢谁，致谢发达的ai，我已经是个废人了/_ \

---

<div align="center">

**如果这个工具对你有帮助，欢迎 Star ⭐**

</div>
