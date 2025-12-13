"""
CloudGather（云集）- 媒体文件同步工具
使用 Flask + HTML 前端
Version: 0.2
"""

import atexit
import os
import psutil
import threading
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from core.scheduler import TaskScheduler
from core.models import SyncTask

# 版本信息
VERSION = "0.3.6"

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 环境适配：判断是否在 Docker 环境中
IS_DOCKER = os.getenv('IS_DOCKER', 'false').lower() == 'true'
CONFIG_PATH = '/app/config/tasks.json' if IS_DOCKER else 'config/tasks.json'

# 全局调度器实例
scheduler = TaskScheduler(config_path=CONFIG_PATH)

# 日志存储
log_lock = threading.Lock()
MAX_LOGS = 500
_task_logs: Dict[str, List[str]] = {"general": []}  # task_id -> logs
_current_task_id: Optional[str] = None  # 当前正在执行的任务ID


def log_handler(message: str):
    """统一日志处理器，存入内存供前端拉取"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = f"[{timestamp}] {message}"
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

# 配置 Flask 访问日志格式
import logging
from logging import Formatter

class TimestampedFormatter(Formatter):
    def format(self, record):
        # 为访问日志添加时间戳
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return f'[{timestamp}] {record.getMessage()}'

# 设置 werkzeug 日志格式
log = logging.getLogger('werkzeug')
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(TimestampedFormatter())
log.handlers = [handler]
log.propagate = False  # 关闭向 root logger 凒泡，避免重复输出


@app.route('/')
def index():
    return render_template('index.html')


def _task_to_dict(task: SyncTask) -> dict:
    data = task.to_dict()
    return data


def _parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {'true', '1', 'yes', 'on'}
    return default


@app.route('/api/status', methods=['GET'])
def api_status():
    # 获取系统资源信息
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    
    return jsonify({
        'running': scheduler.is_running,
        'queue_size': scheduler.get_queue_size(),
        'task_count': len(scheduler.tasks),
        'config_path': str(CONFIG_PATH),
        'is_docker': IS_DOCKER,
        'version': VERSION,
        # 系统资源
        'system': {
            'cpu_percent': cpu_percent,
            'memory_total': memory.total,
            'memory_used': memory.used,
            'memory_percent': memory.percent,
            'memory_available': memory.available,
        }
    })


@app.route('/api/tasks', methods=['GET', 'POST'])
def api_tasks():
    if request.method == 'GET':
        tasks = [_task_to_dict(t) for t in scheduler.get_all_tasks()]
        return jsonify({'tasks': tasks})

    data = request.get_json(silent=True) or {}
    required_fields = ['name', 'source_path', 'target_path']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({'success': False, 'error': f"缺少字段: {', '.join(missing)}"}), 400

    # 获取调度类型
    schedule_type = data.get('schedule_type', 'INTERVAL')
    
    if schedule_type == 'CRON':
        # Cron 调度
        cron_expression = data.get('cron_expression', '').strip()
        if not cron_expression:
            return jsonify({'success': False, 'error': 'Cron 表达式不能为空'}), 400
        
        # 验证 cron 表达式格式
        parts = cron_expression.split()
        if len(parts) != 5:
            return jsonify({'success': False, 'error': 'Cron 表达式格式错误，应为 5 个字段：分 时 日 月 星期'}), 400
        
        task = SyncTask(
            name=data['name'],
            source_path=data['source_path'],
            target_path=data['target_path'],
            schedule_type='CRON',
            cron_expression=cron_expression,
            interval=300,  # cron 模式下 interval 不使用，但需要默认值
            recursive=_parse_bool(data.get('recursive', True), True),
            verify_md5=_parse_bool(data.get('verify_md5', False), False),
            enabled=_parse_bool(data.get('enabled', True), True)
        )
    else:
        # 间隔调度
        try:
            interval = int(data.get('interval', 300))
        except ValueError:
            return jsonify({'success': False, 'error': '同步间隔必须是数字'}), 400

        if interval < 5:
            return jsonify({'success': False, 'error': '同步间隔需大于等于 5 秒'}), 400

        task = SyncTask(
            name=data['name'],
            source_path=data['source_path'],
            target_path=data['target_path'],
            schedule_type='INTERVAL',
            interval=interval,
            recursive=_parse_bool(data.get('recursive', True), True),
            verify_md5=_parse_bool(data.get('verify_md5', False), False),
            enabled=_parse_bool(data.get('enabled', True), True)
        )

    if scheduler.add_task(task):
        return jsonify({'success': True, 'task': _task_to_dict(task)})
    return jsonify({'success': False, 'error': '添加任务失败'}), 500


@app.route('/api/tasks/<task_id>', methods=['PUT', 'DELETE'])
def api_task_detail(task_id: str):
    task = scheduler.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404

    if request.method == 'DELETE':
        if scheduler.remove_task(task_id):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': '删除任务失败'}), 500

    data = request.get_json(silent=True) or {}
    updates: Dict[str, Optional[object]] = {}

    if 'name' in data:
        updates['name'] = data['name']
    if 'source_path' in data:
        updates['source_path'] = data['source_path']
    if 'target_path' in data:
        updates['target_path'] = data['target_path']
    if 'interval' in data:
        try:
            updates['interval'] = int(data['interval'])
        except ValueError:
            return jsonify({'success': False, 'error': '同步间隔必须是数字'}), 400
    if 'recursive' in data:
        updates['recursive'] = _parse_bool(data['recursive'], task.recursive)
    if 'verify_md5' in data:
        updates['verify_md5'] = _parse_bool(data['verify_md5'], task.verify_md5)
    if 'enabled' in data:
        updates['enabled'] = _parse_bool(data['enabled'], task.enabled)

    if 'interval' in updates and updates['interval'] is not None and updates['interval'] < 5:
        return jsonify({'success': False, 'error': '同步间隔需大于等于 5 秒'}), 400

    if scheduler.update_task(task_id, **updates):
        updated = scheduler.get_task(task_id)
        return jsonify({'success': True, 'task': _task_to_dict(updated)})
    return jsonify({'success': False, 'error': '更新任务失败'}), 500


@app.route('/api/tasks/<task_id>/trigger', methods=['POST'])
def api_trigger_task(task_id: str):
    if scheduler.trigger_task_now(task_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '任务状态非空闲或不存在'}), 400


@app.route('/api/scheduler/start', methods=['POST'])
def api_start_scheduler():
    ensure_scheduler_running()
    return jsonify({'success': True, 'running': scheduler.is_running})


@app.route('/api/scheduler/stop', methods=['POST'])
def api_stop_scheduler():
    if scheduler.is_running:
        scheduler.stop()
    return jsonify({'success': True, 'running': scheduler.is_running})


@app.route('/api/queue', methods=['GET'])
def api_queue():
    """获取当前任务队列信息"""
    queue_tasks = []
    # 获取队列中的任务（不移除）
    with scheduler.task_queue.mutex:
        queue_list = list(scheduler.task_queue.queue)
    
    for task_id in queue_list:
        task = scheduler.get_task(task_id)
        if task:
            queue_tasks.append(_task_to_dict(task))
    
    return jsonify({'queue': queue_tasks})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    task_id = request.args.get('task_id', 'general')
    with log_lock:
        logs = list(_task_logs.get(task_id, []))
    return jsonify({'logs': logs})


@app.route('/api/logs/clear', methods=['POST'])
def api_clear_logs():
    task_id = request.args.get('task_id', 'general')
    with log_lock:
        if task_id in _task_logs:
            _task_logs[task_id] = []
    return jsonify({'success': True})


@app.route('/api/directories', methods=['GET'])
def api_list_directories():
    """列出指定路径下的目录"""
    path = request.args.get('path', '/')
    try:
        from pathlib import Path
        import os
        
        # 安全检查：确保路径存在
        target_path = Path(path)
        if not target_path.exists():
            # 如果路径不存在，返回父目录
            parent = target_path.parent
            if parent.exists() and parent.is_dir():
                target_path = parent
            else:
                # 返回根目录或用户主目录
                target_path = Path('/') if IS_DOCKER else Path.home()
        
        # 只列出目录
        dirs = []
        if target_path.is_dir():
            try:
                for item in sorted(target_path.iterdir()):
                    if item.is_dir():
                        try:
                            # 检查是否可读
                            item.stat()
                            dirs.append({
                                'name': item.name,
                                'path': str(item),
                                'parent': str(item.parent)
                            })
                        except (PermissionError, OSError):
                            # 跳过无权限的目录
                            continue
            except PermissionError:
                return jsonify({
                    'success': False,
                    'error': '没有权限访问此目录',
                    'current_path': str(target_path),
                    'directories': []
                })
        
        return jsonify({
            'success': True,
            'current_path': str(target_path),
            'parent_path': str(target_path.parent) if target_path.parent != target_path else None,
            'directories': dirs
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'current_path': path,
            'directories': []
        })


@app.route('/api/cron/presets', methods=['GET'])
def api_cron_presets():
    """获取 Cron 表达式预设"""
    presets = [
        {'name': '每 5 分钟', 'expression': '*/5 * * * *', 'description': '每 5 分钟执行一次'},
        {'name': '每 10 分钟', 'expression': '*/10 * * * *', 'description': '每 10 分钟执行一次'},
        {'name': '每 15 分钟', 'expression': '*/15 * * * *', 'description': '每 15 分钟执行一次'},
        {'name': '每 30 分钟', 'expression': '*/30 * * * *', 'description': '每 30 分钟执行一次'},
        {'name': '每小时', 'expression': '0 * * * *', 'description': '每小时整点执行'},
        {'name': '每 2 小时', 'expression': '0 */2 * * *', 'description': '每 2 小时执行一次'},
        {'name': '每 6 小时', 'expression': '0 */6 * * *', 'description': '每 6 小时执行一次'},
        {'name': '每 12 小时', 'expression': '0 */12 * * *', 'description': '每 12 小时执行一次'},
        {'name': '每天凌晨 2 点', 'expression': '0 2 * * *', 'description': '每天凌晨 2:00 执行'},
        {'name': '每天凌晨 3 点', 'expression': '0 3 * * *', 'description': '每天凌晨 3:00 执行'},
        {'name': '每天早上 8 点', 'expression': '0 8 * * *', 'description': '每天早上 8:00 执行'},
        {'name': '每周一凌晨 2 点', 'expression': '0 2 * * 1', 'description': '每周一凌晨 2:00 执行'},
        {'name': '每月 1 号凌晨 2 点', 'expression': '0 2 1 * *', 'description': '每月 1 号凌晨 2:00 执行'},
        {'name': '工作日早上 9 点', 'expression': '0 9 * * 1-5', 'description': '周一到周五早上 9:00 执行'},
    ]
    return jsonify({'presets': presets})


@app.route('/api/cron/random', methods=['GET'])
def api_cron_random():
    """生成随机 Cron 表达式"""
    import random
    
    # 获取参数
    pattern = request.args.get('pattern', 'hourly')  # daily, hourly, custom
    
    if pattern == 'daily':
        # 每天随机时间
        minute = random.randint(0, 59)
        hour = random.randint(0, 23)
        expression = f"{minute} {hour} * * *"
        description = f"每天 {hour:02d}:{minute:02d} 执行"
    elif pattern == 'hourly':
        # 每小时随机分钟
        minute = random.randint(0, 59)
        expression = f"{minute} * * * *"
        description = f"每小时的第 {minute} 分钟执行"
    elif pattern == 'night':
        # 深夜随机时间（23:00-05:00）
        minute = random.randint(0, 59)
        hour = random.choice([23, 0, 1, 2, 3, 4, 5])
        expression = f"{minute} {hour} * * *"
        description = f"每天凌晨 {hour:02d}:{minute:02d} 执行"
    else:
        # 完全随机
        minute = random.randint(0, 59)
        hour = random.randint(0, 23)
        expression = f"{minute} {hour} * * *"
        description = f"每天 {hour:02d}:{minute:02d} 执行"
    
    return jsonify({
        'expression': expression,
        'description': description,
        'pattern': pattern
    })


@app.route('/api/cron/validate', methods=['POST'])
def api_cron_validate():
    """验证 Cron 表达式"""
    data = request.get_json(silent=True) or {}
    expression = data.get('expression', '').strip()
    
    if not expression:
        return jsonify({'valid': False, 'error': 'Cron 表达式不能为空'})
    
    parts = expression.split()
    if len(parts) != 5:
        return jsonify({'valid': False, 'error': 'Cron 表达式应包含 5 个字段：分 时 日 月 星期'})
    
    try:
        from apscheduler.triggers.cron import CronTrigger
        minute, hour, day, month, day_of_week = parts
        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week
        )
        # 获取下次执行时间
        next_run = trigger.get_next_fire_time(None, datetime.now())
        return jsonify({
            'valid': True,
            'next_run': next_run.isoformat() if next_run else None,
            'description': f"下次执行: {next_run.strftime('%Y-%m-%d %H:%M:%S')}" if next_run else '无法计算'
        })
    except Exception as e:
        return jsonify({'valid': False, 'error': f'验证失败: {str(e)}'})


@atexit.register
def _cleanup():
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
    
    # 启动信息
    print(f'\n✅ CloudGather v{VERSION} 启动成功')
    print(f'⏰ 时区: {os.getenv("TZ", "UTC")}')
    print(f'🌐 访问地址: http://127.0.0.1:8080')
    print(f'💬 一言: {hitokoto}')
    print('▶️  服务运行中... (按 CTRL+C 停止)\n')
    
    # 启动 Flask
    app.run(
        host='0.0.0.0' if IS_DOCKER else '127.0.0.1',
        port=8080,
        debug=not IS_DOCKER
    )
