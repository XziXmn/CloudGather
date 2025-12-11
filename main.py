"""
CloudGather（云集）- 媒体文件同步工具
使用 Flask + HTML 前端
"""

import atexit
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from core.scheduler import TaskScheduler
from core.models import SyncTask

# 环境适配：判断是否在 Docker 环境中
IS_DOCKER = os.getenv('IS_DOCKER', 'false').lower() == 'true'
CONFIG_PATH = '/app/config/tasks.json' if IS_DOCKER else 'config/tasks.json'

# 全局调度器实例
scheduler = TaskScheduler(config_path=CONFIG_PATH)

# 日志存储
log_lock = threading.Lock()
MAX_LOGS = 500
_task_logs: Dict[str, List[str]] = {"general": []}


def log_handler(message: str):
    """统一日志处理器，存入内存供前端拉取"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    entry = f"[{timestamp}] {message}"
    with log_lock:
        logs = _task_logs.setdefault('general', [])
        logs.append(entry)
        if len(logs) > MAX_LOGS:
            _task_logs['general'] = logs[-MAX_LOGS:]


# 绑定调度器日志
scheduler.set_log_callback(log_handler)

# 启动调度器（幂等）
def ensure_scheduler_running():
    if not scheduler.is_running:
        scheduler.start()


ensure_scheduler_running()

# Flask 应用
app = Flask(__name__, static_folder='static', template_folder='templates')


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
    return jsonify({
        'running': scheduler.is_running,
        'queue_size': scheduler.get_queue_size(),
        'task_count': len(scheduler.tasks),
        'config_path': str(CONFIG_PATH),
        'is_docker': IS_DOCKER,
    })


@app.route('/api/tasks', methods=['GET', 'POST'])
def api_tasks():
    if request.method == 'GET':
        tasks = [_task_to_dict(t) for t in scheduler.get_all_tasks()]
        return jsonify({'tasks': tasks})

    data = request.get_json(silent=True) or {}
    required_fields = ['name', 'source_path', 'target_path', 'interval']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({'success': False, 'error': f"缺少字段: {', '.join(missing)}"}), 400

    try:
        interval = int(data.get('interval', 0))
    except ValueError:
        return jsonify({'success': False, 'error': '同步间隔必须是数字'}), 400

    if interval < 5:
        return jsonify({'success': False, 'error': '同步间隔需大于等于 5 秒'}), 400

    task = SyncTask(
        name=data['name'],
        source_path=data['source_path'],
        target_path=data['target_path'],
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


@app.route('/api/logs', methods=['GET'])
def api_logs():
    with log_lock:
        logs = list(_task_logs.get('general', []))
    return jsonify({'logs': logs})


@atexit.register
def _cleanup():
    if scheduler.is_running:
        scheduler.stop()


if __name__ == '__main__':
    app.run(
        host='0.0.0.0' if IS_DOCKER else '127.0.0.1',
        port=8080,
        debug=not IS_DOCKER
    )
