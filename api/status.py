"""
状态与系统信息 API 蓝图
"""
import psutil
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify

status_bp = Blueprint('status', __name__)


def init_status_bp(scheduler, config_path: str, is_docker: bool, version: str):
    """初始化状态蓝图，注入依赖"""
    status_bp.scheduler = scheduler
    status_bp.config_path = config_path
    status_bp.is_docker = is_docker
    status_bp.version = version


@status_bp.route('/status', methods=['GET'])
def api_status():
    """获取系统状态"""
    scheduler = status_bp.scheduler
    config_path = status_bp.config_path
    is_docker = status_bp.is_docker
    version = status_bp.version
    
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
    config_path_obj = Path(config_path)
    if config_path_obj.exists():
        stat = config_path_obj.stat()
        config_stat = {
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    
    return jsonify({
        'running': scheduler.is_running,
        'queue_size': scheduler.get_queue_size(),
        'task_count': len(scheduler.tasks),
        'config_path': str(config_path),
        'is_docker': is_docker,
        'version': version,
        
        # 配置健康状态
        'config_health': {
            'exists': config_path_obj.exists(),
            'dir_exists': config_path_obj.parent.exists(),
            'dir_writable': config_path_obj.parent.exists() and config_path_obj.parent.is_dir(),
            'file_writable': config_path_obj.is_file() if config_path_obj.exists() else None,
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


@status_bp.route('/scheduler/start', methods=['POST'])
def api_start_scheduler():
    """启动调度器"""
    scheduler = status_bp.scheduler
    if not scheduler.is_running:
        scheduler.start()
    return jsonify({'success': True, 'running': scheduler.is_running})


@status_bp.route('/scheduler/stop', methods=['POST'])
def api_stop_scheduler():
    """停止调度器"""
    scheduler = status_bp.scheduler
    if scheduler.is_running:
        scheduler.stop()
    return jsonify({'success': True, 'running': scheduler.is_running})


@status_bp.route('/queue', methods=['GET'])
def api_queue():
    """获取当前任务队列信息"""
    scheduler = status_bp.scheduler
    queue_tasks = []
    
    # 获取队列中的任务（不移除）
    with scheduler.task_queue.mutex:
        queue_list = list(scheduler.task_queue.queue)
    
    for task_id in queue_list:
        task = scheduler.get_task(task_id)
        if task:
            data = task.to_dict()
            # 添加下次执行时间
            next_run_time = scheduler.get_next_run_time(task.id)
            if next_run_time:
                data['next_run_time'] = next_run_time.isoformat()
            else:
                data['next_run_time'] = None
            queue_tasks.append(data)
    
    return jsonify({'queue': queue_tasks})
