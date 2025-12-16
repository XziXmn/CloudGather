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

# 配置日志格式
# 确保日志目录存在
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

# 从环境变量读取日志级别配置
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()  # 文件日志级别
CONSOLE_LEVEL = os.getenv('CONSOLE_LEVEL', 'INFO').upper()  # 控制台日志级别
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

# 控制台 handler - 只显示业务日志
console_handler = logging.StreamHandler()
console_handler.setLevel(getattr(logging, CONSOLE_LEVEL, logging.INFO))
console_formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)
root_logger.addHandler(console_handler)


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
                logging.warning(f"删除过期日志失败: {log_file} - {e}")
        
        if removed_count > 0:
            logging.info(f"✅ 已清理 {removed_count} 个过期日志文件")
    except Exception as e:
        logging.error(f"清理日志失败: {e}")


# 启动时清理一次过期日志
cleanup_old_logs()

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

# 设置 Werkzeug 日志：将 HTTP 访问日志压低到 WARNING 级别
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.WARNING)  # 只显示警告和错误
werkzeug_logger.propagate = True  # 传递到 root logger，确保警告/错误会被记录到文件


@app.route('/')
def index():
    return render_template('index.html')


def _task_to_dict(task: SyncTask) -> dict:
    data = task.to_dict()
    # 添加下次执行时间
    next_run_time = scheduler.get_next_run_time(task.id)
    if next_run_time:
        data['next_run_time'] = next_run_time.isoformat()
    else:
        data['next_run_time'] = None
    
    # 添加任务进度（如果正在执行）
    if task.status.value == 'RUNNING' and task.id in scheduler.task_progress:
        data['progress'] = scheduler.task_progress[task.id]
    
    # 添加最终统计信息（如果有）
    if task.id in scheduler.task_stats:
        data['stats'] = scheduler.task_stats[task.id]
    
    return data


def _parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {'true', '1', 'yes', 'on'}
    return default


def _validate_paths_for_request(source_path: str, target_path: str):
    """校验源/目标路径可用性，并在需要时创建目标目录"""
    source = Path(source_path)
    target = Path(target_path)
    
    if not source.exists():
        return False, f"源目录不存在: {source}"
    if not source.is_dir():
        return False, f"源路径不是目录: {source}"
    if not os.access(source, os.R_OK):
        return False, f"没有读取源目录的权限: {source}"
    
    try:
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            return False, f"目标路径不是目录: {target}"
        if not os.access(target, os.W_OK):
            return False, f"没有写入目标目录的权限: {target}"
    except PermissionError as e:
        return False, f"无法创建/访问目标目录: {e}"
    except Exception as e:
        return False, f"目标目录检查失败: {e}"
    
    return True, None


@app.route('/api/status', methods=['GET'])
def api_status():
    # 获取系统资源信息
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    disk_usage = psutil.disk_usage('/')
    
    # 统计任务状态
    task_stats = {
        'total': len(scheduler.tasks),
        'enabled': sum(1 for t in scheduler.tasks.values() if t.enabled),
        'disabled': sum(1 for t in scheduler.tasks.values() if not t.enabled),
        'idle': sum(1 for t in scheduler.tasks.values() if t.status.value == 'IDLE'),
        'running': sum(1 for t in scheduler.tasks.values() if t.status.value == 'RUNNING'),
        'queued': sum(1 for t in scheduler.tasks.values() if t.status.value == 'QUEUED'),
        'error': sum(1 for t in scheduler.tasks.values() if t.status.value == 'ERROR')
    }
    
    # 获取最近执行任务
    recent_tasks = sorted(
        [t for t in scheduler.tasks.values() if t.last_run_time],
        key=lambda x: x.last_run_time or '',
        reverse=True
    )[:5]
    
    # 配置文件信息
    config_stat = None
    if Path(CONFIG_PATH).exists():
        stat = Path(CONFIG_PATH).stat()
        config_stat = {
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    
    return jsonify({
        'running': scheduler.is_running,
        'queue_size': scheduler.get_queue_size(),
        'task_count': len(scheduler.tasks),
        'config_path': str(CONFIG_PATH),
        'is_docker': IS_DOCKER,
        'version': VERSION,
        
        # 配置健康状态
        'config_health': {
            'exists': Path(CONFIG_PATH).exists(),
            'dir_exists': Path(CONFIG_PATH).parent.exists(),
            'dir_writable': os.access(Path(CONFIG_PATH).parent, os.W_OK),
            'file_writable': os.access(Path(CONFIG_PATH), os.W_OK) if Path(CONFIG_PATH).exists() else None,
            'file_stat': config_stat
        },
        
        # 任务统计
        'task_stats': task_stats,
        
        # 最近执行的任务
        'recent_tasks': [
            {
                'id': t.id,
                'name': t.name,
                'last_run_time': t.last_run_time,
                'status': t.status.value
            } for t in recent_tasks
        ],
        
        # 系统资源
        'system': {
            'cpu_percent': cpu_percent,
            'memory_total': memory.total,
            'memory_used': memory.used,
            'memory_percent': memory.percent,
            'memory_available': memory.available,
            'disk_total': disk_usage.total,
            'disk_used': disk_usage.used,
            'disk_free': disk_usage.free,
            'disk_percent': disk_usage.percent
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

    source_path = data['source_path']
    target_path = data['target_path']
    ok, err = _validate_paths_for_request(source_path, target_path)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

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
            source_path=source_path,
            target_path=target_path,
            schedule_type='CRON',
            cron_expression=cron_expression,
            interval=300,  # cron 模式下 interval 不使用，但需要默认值
            enabled=_parse_bool(data.get('enabled', True), True),
            overwrite_existing=_parse_bool(data.get('overwrite_existing', False), False),
            thread_count=int(data.get('thread_count', 1)),
            rule_not_exists=_parse_bool(data.get('rule_not_exists', False), False),
            rule_size_diff=_parse_bool(data.get('rule_size_diff', False), False),
            rule_mtime_newer=_parse_bool(data.get('rule_mtime_newer', False), False),
            is_slow_storage=_parse_bool(data.get('is_slow_storage', False), False)
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
            source_path=source_path,
            target_path=target_path,
            schedule_type='INTERVAL',
            interval=interval,
            enabled=_parse_bool(data.get('enabled', True), True),
            overwrite_existing=_parse_bool(data.get('overwrite_existing', False), False),
            thread_count=int(data.get('thread_count', 1)),
            rule_not_exists=_parse_bool(data.get('rule_not_exists', False), False),
            rule_size_diff=_parse_bool(data.get('rule_size_diff', False), False),
            rule_mtime_newer=_parse_bool(data.get('rule_mtime_newer', False), False),
            is_slow_storage=_parse_bool(data.get('is_slow_storage', False), False)
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
    if 'enabled' in data:
        updates['enabled'] = _parse_bool(data['enabled'], task.enabled)
    if 'overwrite_existing' in data:
        updates['overwrite_existing'] = _parse_bool(data['overwrite_existing'], task.overwrite_existing)
    if 'thread_count' in data:
        try:
            updates['thread_count'] = max(1, int(data['thread_count']))
        except ValueError:
            return jsonify({'success': False, 'error': '线程数必须是数字'}), 400
    if 'rule_not_exists' in data:
        updates['rule_not_exists'] = _parse_bool(data['rule_not_exists'], task.rule_not_exists)
    if 'rule_size_diff' in data:
        updates['rule_size_diff'] = _parse_bool(data['rule_size_diff'], task.rule_size_diff)
    if 'rule_mtime_newer' in data:
        updates['rule_mtime_newer'] = _parse_bool(data['rule_mtime_newer'], task.rule_mtime_newer)
    if 'is_slow_storage' in data:
        updates['is_slow_storage'] = _parse_bool(data['is_slow_storage'], task.is_slow_storage)

    # 路径更新时校验并创建目标目录
    if 'source_path' in updates or 'target_path' in updates:
        new_source = updates.get('source_path', task.source_path)
        new_target = updates.get('target_path', task.target_path)
        ok, err = _validate_paths_for_request(new_source, new_target)
        if not ok:
            return jsonify({'success': False, 'error': err}), 400

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


@app.route('/api/tasks/<task_id>/full-overwrite', methods=['POST'])
def api_full_overwrite_task(task_id: str):
    """全量覆盖：一次性强制覆盖所有已存在文件"""
    task = scheduler.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    if task.status != 'IDLE':
        return jsonify({'success': False, 'error': '任务状态非空闲，无法执行'}), 400
    
    # 使用现有的 trigger_task_now 机制，但传递特殊标记
    # 注：这里需要修改任务的 overwrite_existing 为 True，执行后恢复
    original_overwrite = task.overwrite_existing
    task.overwrite_existing = True  # 临时设置为覆盖模式
    
    # 记录日志
    log_handler(f"🔥 开始执行全量覆盖: {task.name}")
    
    # 触发任务
    success = scheduler.trigger_task_now(task_id)
    
    if success:
        # 在后台恢复原始设置（不保存到文件）
        # 注：任务执行完后会自动恢复
        import threading
        def reset_overwrite():
            import time
            time.sleep(1)  # 等待任务开始执行
            task.overwrite_existing = original_overwrite
        threading.Thread(target=reset_overwrite, daemon=True).start()
        
        return jsonify({'success': True})
    else:
        task.overwrite_existing = original_overwrite  # 恢复
        return jsonify({'success': False, 'error': '触发任务失败'}), 500


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
