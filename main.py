"""
CloudGather（云集）- 媒体文件同步工具
使用 Flask + HTML 前端
"""

import atexit
import os
import sys
import psutil
import threading
import logging
from logging.handlers import RotatingFileHandler
import requests
import glob
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from core.scheduler import TaskScheduler
from core.models import SyncTask
from version import __version__

# 版本信息
VERSION = __version__

# 环境适配：判断是否在 Docker 环境中
IS_DOCKER = os.getenv('IS_DOCKER', 'false').lower() == 'true'

# 配置日志格式
# 确保日志目录存在
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

# 从环境变量读取日志级别配置
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()  # 文件日志级别
CONSOLE_LEVEL = os.getenv('CONSOLE_LEVEL', 'WARNING').upper()  # 控制台日志级别（默认只显示警告和错误）
LOG_SAVE_DAYS = int(os.getenv('LOG_SAVE_DAYS', '7'))  # 日志保留天数

# 配置 root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)  # 设置为 DEBUG 以捕捉所有级别

# 文件 handler - 保存所有日志
file_handler = RotatingFileHandler(
    log_dir / 'cloudgather.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
file_formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
root_logger.addHandler(file_handler)

# 控制台 handler - 默认只显示警告和错误，不显示任务执行信息
console_handler = logging.StreamHandler(sys.stdout)  # 显式指定 stdout
console_handler.setLevel(getattr(logging, CONSOLE_LEVEL, logging.WARNING))
console_formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)
root_logger.addHandler(console_handler)

# Docker 环境下强制刷新输出
if IS_DOCKER:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)


def cleanup_old_logs():
    """清理过期日志文件"""
    try:
        cutoff_time = time.time() - (LOG_SAVE_DAYS * 86400)  # 转换为秒
        log_files = glob.glob(str(log_dir / 'cloudgather.log.*'))
        
        removed_count = 0
        for log_file in log_files:
            try:
                file_path = Path(log_file)
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    removed_count += 1
            except Exception as e:
                # 只写入文件，不输出控制台
                file_handler.handle(logging.LogRecord(
                    name='cloudgather',
                    level=logging.WARNING,
                    pathname='',
                    lineno=0,
                    msg=f"删除过期日志失败: {log_file} - {e}",
                    args=(),
                    exc_info=None
                ))
        
        # 清理成功信息只写入文件
        if removed_count > 0:
            file_handler.handle(logging.LogRecord(
                name='cloudgather',
                level=logging.INFO,
                pathname='',
                lineno=0,
                msg=f"✅ 已清理 {removed_count} 个过期日志文件",
                args=(),
                exc_info=None
            ))
    except Exception as e:
        # 错误信息只写入文件
        file_handler.handle(logging.LogRecord(
            name='cloudgather',
            level=logging.ERROR,
            pathname='',
            lineno=0,
            msg=f"清理日志失败: {e}",
            args=(),
            exc_info=None
        ))


# 启动时清理一次过期日志
cleanup_old_logs()

# 环境适配：配置路径
CONFIG_PATH = '/app/config/tasks.json' if IS_DOCKER else 'config/tasks.json'

# 全局调度器实例
scheduler = TaskScheduler(config_path=CONFIG_PATH)

# 日志存储
log_lock = threading.Lock()
MAX_LOGS = 500
_task_logs: Dict[str, List[str]] = {"general": []}  # task_id -> logs
_current_task_id: Optional[str] = None  # 当前正在执行的任务ID


def log_handler(message: str):
    """统一日志处理器，存入内存供前端拉取，只写文件不输出控制台"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = f"[{timestamp}] {message}"
    
    # 只写入文件日志，不输出到控制台
    file_handler.handle(logging.LogRecord(
        name='cloudgather',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg=message,
        args=(),
        exc_info=None
    ))
    
    with log_lock:
        # 添加到全局日志
        logs = _task_logs.setdefault('general', [])
        logs.append(entry)
        if len(logs) > MAX_LOGS:
            _task_logs['general'] = logs[-MAX_LOGS:]
        
        # 如果有当前任务，也添加到任务专属日志
        if _current_task_id:
            task_logs = _task_logs.setdefault(_current_task_id, [])
            task_logs.append(entry)
            if len(task_logs) > MAX_LOGS:
                _task_logs[_current_task_id] = task_logs[-MAX_LOGS:]


def set_current_task(task_id: Optional[str]):
    """设置当前正在执行的任务ID"""
    global _current_task_id
    _current_task_id = task_id


# 绑定调度器日志
scheduler.set_log_callback(log_handler)
scheduler.set_task_context_callback(set_current_task)

# 启动调度器（幂等）
def ensure_scheduler_running():
    if not scheduler.is_running:
        scheduler.start()


ensure_scheduler_running()

# Flask 应用
app = Flask(__name__, static_folder='static', template_folder='html')

# 设置 Werkzeug 日志：将 HTTP 访问日志压低到 WARNING 级别
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.WARNING)  # 只显示警告和错误
werkzeug_logger.propagate = True  # 传递到 root logger，确保警告/错误会被记录到文件

# 注册 API 蓝图
from api.status import status_bp, init_status_bp
from api.tasks import tasks_bp, init_tasks_bp
from api.settings import settings_bp, init_settings_bp
from api.strm import strm_bp, init_strm_bp

init_status_bp(scheduler, CONFIG_PATH, IS_DOCKER, VERSION)
init_tasks_bp(scheduler, log_handler, IS_DOCKER, _task_logs, log_lock)
init_settings_bp(IS_DOCKER)
init_strm_bp(scheduler, log_handler)

app.register_blueprint(status_bp, url_prefix='/api')
app.register_blueprint(tasks_bp, url_prefix='/api')
app.register_blueprint(settings_bp, url_prefix='/api')
app.register_blueprint(strm_bp, url_prefix='/api')


@app.route('/')
def index():
    return render_template('index.html')


@atexit.register
def _cleanup():
    """退出时清理资源"""
    if scheduler.is_running:
        scheduler.stop()


def fetch_hitokoto():
    """获取一言"""
    try:
        response = requests.get('https://v1.hitokoto.cn/', timeout=5)
        data = response.json()
        text = data.get('hitokoto', '今天也要加油哦！')
        from_who = data.get('from', '')
        return f"{text} —— {from_who}" if from_who else text
    except Exception as e:
        return '保持热爱，奔赴山海'


if __name__ == '__main__':
    # 获取一言
    hitokoto = fetch_hitokoto()
    
    # 只在非 debug 模式或主进程中显示启动信息
    # debug 模式下，os.environ.get('WERKZEUG_RUN_MAIN') 只在子进程中为 'true'
    if IS_DOCKER or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        # 启动信息
        print(f'\n✅ CloudGather v{VERSION} 启动成功')
        print(f'⏰ 时区: {os.getenv("TZ", "UTC")}')
        print(f'🌐 访问地址: http://127.0.0.1:3602')
        print(f'💬 一言: {hitokoto}')
        print('▶️  服务运行中... (按 CTRL+C 停止)\n')
    
    # 启动 Flask
    app.run(
        host='0.0.0.0' if IS_DOCKER else '127.0.0.1',
        port=3602,
        debug=not IS_DOCKER
    )
