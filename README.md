# 🎬 FnOS Media Mover

一个功能强大的 NAS 文件同步工具，专为媒体文件管理而设计。

## ✨ 核心特性

### 🔒 可靠性保障
- **原子化写入**：文件先复制到临时文件，校验通过后原子化重命名，确保数据完整性
- **静默期检测**：自动检测正在下载的文件，避免同步未完成的文件
- **MD5 校验**（可选）：确保文件完整性，防止损坏

### 🎯 智能功能
- **垃圾文件过滤**：自动跳过 `.DS_Store`、`@eaDir`、`#recycle` 等系统垃圾文件
- **递归同步**：支持子目录递归扫描和同步
- **定时调度**：使用 APScheduler 实现精确的定时同步

### 🎨 现代化界面
- **实时进度**：任务卡片显示同步进度条和状态
- **日志查看**：实时查看任务日志，方便调试
- **美观设计**：使用 NiceGUI 构建的现代化 Web 界面

## 🚀 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行应用
python main.py

# 3. 打开浏览器访问
# http://127.0.0.1:8080
```

### Docker 运行

```bash
# 设置 Docker 环境变量
export IS_DOCKER=true

# 运行
python main.py
```

## 📁 项目结构

```
FnOS-Media-Mover/
├── core/
│   ├── worker.py      # 文件同步核心类
│   ├── models.py      # 数据模型定义
│   └── scheduler.py   # 任务调度管理器
├── config/
│   └── tasks.json     # 任务配置文件
├── main.py            # Web 界面入口
└── requirements.txt   # 依赖列表
```

## 🛠️ 技术栈

- **Web 框架**：NiceGUI
- **任务调度**：APScheduler
- **文件操作**：pathlib + shutil
- **数据模型**：Python dataclass

## 📖 使用说明

### 添加同步任务

1. 点击右上角"添加任务"按钮
2. 填写任务信息：
   - 任务名称
   - 源目录路径
   - 目标目录路径
   - 同步间隔（秒）
3. 配置高级选项：
   - 递归同步子目录
   - MD5 校验
   - 启用任务
4. 点击"添加"保存

### 管理任务

- **立即运行**：手动触发任务立即执行
- **编辑**：修改任务配置
- **日志**：查看任务执行日志
- **删除**：移除任务

### 状态说明

- 🟢 **运行中**：任务正在执行同步
- 🟡 **队列中**：任务已加入执行队列，等待执行
- ⚪ **空闲**：任务等待下次定时触发
- 🔴 **错误**：任务执行出错

## ⚙️ 环境配置

### 配置文件路径

- **本地开发**：`config/tasks.json`
- **Docker 环境**：`/app/config/tasks.json`

### 环境变量

- `IS_DOCKER`：设置为 `true` 启用 Docker 模式

## 🔧 高级配置

### 静默期时间

在 `core/worker.py` 中修改：

```python
STABILITY_CHECK_DELAY = 5  # 秒
```

### 垃圾文件过滤

在 `core/worker.py` 中修改 `IGNORE_LIST`：

```python
IGNORE_LIST = {
    '.DS_Store',
    '@eaDir',
    '#recycle',
    # 添加更多...
}
```

## 📝 开发说明

### 核心类说明

#### FileSyncer (core/worker.py)
- `sync_file()` - 同步单个文件
- `sync_directory()` - 同步整个目录
- `check_file_stability()` - 静默期检测
- `calculate_md5()` - MD5 校验

#### TaskScheduler (core/scheduler.py)
- `add_task()` - 添加任务
- `remove_task()` - 移除任务
- `start()` - 启动调度器
- `stop()` - 停止调度器

#### SyncTask (core/models.py)
- `to_dict()` - 序列化为字典
- `from_dict()` - 从字典反序列化

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
