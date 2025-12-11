# CloudGather（云集） - 媒体文件同步工具

🎬 专为 NAS 设计的现代化媒体文件同步工具，采用 **Flask + HTML + Tailwind CSS** 架构，提供美观的 Web 界面和实时监控能力。

## ✨ 特性

- 🎯 **定时同步** - APScheduler 提供可靠的定时调度
- 🔄 **实时监控** - 自动刷新任务状态和日志
- 💾 **原子写入** - 保障数据完整性和安全性
- ⏱️ **静默期检测** - 防止同步未完成的文件
- 📊 **现代化 UI** - 基于 Tailwind CSS 的暗色主题界面
- 🚀 **零构建** - 无需 npm，直接运行
- 🐳 **Docker 支持** - 一键部署到容器环境

## 🏗️ 技术栈

### 后端
- **Flask** - 轻量级 Python Web 框架
- **APScheduler** - 任务调度
- **pathlib + shutil** - 文件操作

### 前端
- **HTML5** - 语义化标记
- **Tailwind CSS** - 实用优先的 CSS 框架（CDN）
- **原生 JavaScript** - 无框架依赖
- **Font Awesome** - 图标库

## 📦 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

#### 方式一：使用启动脚本（推荐）

双击 `start.bat` 或在终端运行：
```bash
start.bat
```

#### 方式二：手动启动

```bash
python main.py
```

### 3. 访问界面

打开浏览器访问：**http://127.0.0.1:8080**

就这么简单！🎊

## 🎮 使用指南

### 添加同步任务

1. 访问任务面板
2. 点击「添加任务」按钮
3. 填写任务信息：
   - 任务名称
   - 源目录路径
   - 目标目录路径
   - 同步间隔（秒）
   - 可选：递归同步、MD5 校验
4. 保存任务

### 管理任务

- **立即运行** - 手动触发任务执行
- **编辑** - 修改任务配置
- **删除** - 移除任务
- **启用/禁用** - 控制任务是否参与调度

### 查看日志

访问「实时日志」页面查看所有任务的执行日志，支持：
- 实时更新
- 自动滚动
- 清空日志

### 系统设置

在「系统设置」页面可以：
- 查看系统状态
- 启动/停止调度器
- 查看配置路径

## 🐳 Docker 部署

```bash
# 构建镜像
docker build -t cloudgather .

# 运行容器
docker run -d \
  -p 8080:8080 \
  -v /path/to/config:/app/config \
  -v /path/to/source:/source \
  -v /path/to/target:/target \
  -e IS_DOCKER=true \
  --name cloudgather \
  cloudgather
```

## 📁 项目结构

```
CloudGather/
├── main.py             # Flask 后端主文件
├── requirements.txt    # Python 依赖
├── start.bat           # 一键启动脚本
├── core/               # 核心业务逻辑
│   ├── models.py       # 数据模型
│   ├── scheduler.py    # 任务调度器
│   └── worker.py       # 文件同步工作器
├── templates/          # HTML 模板
│   └── index.html      # 主界面
├── static/             # 静态资源
│   └── app.js          # 前端交互脚本
└── config/             # 配置文件目录
    └── tasks.json      # 任务配置（自动生成）
```

## 🔧 配置说明

### 环境变量

- `IS_DOCKER` - 是否在 Docker 环境中运行（`true`/`false`）
- 默认配置路径：
  - 本地：`config/tasks.json`
  - Docker：`/app/config/tasks.json`

### API 端点

- `GET /api/status` - 获取系统状态
- `GET /api/tasks` - 获取任务列表
- `POST /api/tasks` - 创建任务
- `PUT /api/tasks/{id}` - 更新任务
- `DELETE /api/tasks/{id}` - 删除任务
- `POST /api/tasks/{id}/trigger` - 触发任务
- `POST /api/scheduler/start` - 启动调度器
- `POST /api/scheduler/stop` - 停止调度器
- `GET /api/logs` - 获取日志

## 📝 开发指南

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器（自动重载）
python main.py
```

### 前端修改

前端使用纯 HTML + JavaScript，无需构建步骤：
- 修改 `templates/index.html` - 界面结构和样式
- 修改 `static/app.js` - 交互逻辑
- 刷新浏览器即可看到更改

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 👨‍💻 作者

Your Name - [@yourhandle](https://github.com/yourhandle)

---

**CloudGather（云集）** - 让媒体同步更简单、更智能 🚀
