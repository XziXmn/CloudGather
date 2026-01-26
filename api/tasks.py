"""
任务管理 API 蓝图
"""
import os
import threading
import random
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from flask import Blueprint, jsonify, request
from apscheduler.triggers.cron import CronTrigger

from core.models import SyncTask

tasks_bp = Blueprint('tasks', __name__)


def init_tasks_bp(scheduler, log_handler, is_docker: bool, task_logs, log_lock):
    """初始化任务蓝图，注入依赖"""
    tasks_bp.scheduler = scheduler
    tasks_bp.log_handler = log_handler
    tasks_bp.is_docker = is_docker
    tasks_bp.task_logs = task_logs
    tasks_bp.log_lock = log_lock


def _task_to_dict(task: SyncTask) -> dict:
    """将任务对象转换为字典"""
    scheduler = tasks_bp.scheduler
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
    """解析布尔值"""
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


@tasks_bp.route('/tasks', methods=['GET', 'POST'])
def api_tasks():
    """获取所有任务或创建新任务"""
    scheduler = tasks_bp.scheduler
    
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
    
    # 删除源文件配置
    delete_source = _parse_bool(data.get('delete_source', False), False)
    delete_delay_days = None
    if 'delete_delay_days' in data and data.get('delete_delay_days') not in (None, ''):
        try:
            delete_delay_days = int(data.get('delete_delay_days'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '删除延迟天数必须是整数'}), 400
        if delete_delay_days < 0:
            return jsonify({'success': False, 'error': '删除延迟天数不能为负数'}), 400
    delete_time_base = (data.get('delete_time_base', 'SYNC_COMPLETE') or 'SYNC_COMPLETE').upper()
    delete_parent = _parse_bool(data.get('delete_parent', False), False)
    # 删除目录层级：从文件所在目录向上最多尝试删除的层级数（0 表示不删目录）
    delete_parent_levels = 0
    if 'delete_parent_levels' in data and data.get('delete_parent_levels') not in (None, ''):
        try:
            delete_parent_levels = int(data.get('delete_parent_levels'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '删除目录层级必须是非负整数'}), 400
        if delete_parent_levels < 0:
            return jsonify({'success': False, 'error': '删除目录层级必须是非负整数'}), 400
    # 强制删除非空目录：就算目录下有未同步的元数据或者其他文件也删除（仍会保护未到期文件）
    delete_parent_force = _parse_bool(data.get('delete_parent_force', False), False)
    
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
            is_slow_storage=_parse_bool(data.get('is_slow_storage', False), False),
            size_min_bytes=data.get('size_min_bytes'),
            size_max_bytes=data.get('size_max_bytes'),
            suffix_mode=data.get('suffix_mode', 'NONE'),
            suffix_list=data.get('suffix_list'),
            delete_source=delete_source,
            delete_delay_days=delete_delay_days,
            delete_time_base=delete_time_base,
            delete_parent=delete_parent,
            delete_parent_levels=delete_parent_levels,
            delete_parent_force=delete_parent_force
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
            is_slow_storage=_parse_bool(data.get('is_slow_storage', False), False),
            size_min_bytes=data.get('size_min_bytes'),
            size_max_bytes=data.get('size_max_bytes'),
            suffix_mode=data.get('suffix_mode', 'NONE'),
            suffix_list=data.get('suffix_list'),
            delete_source=delete_source,
            delete_delay_days=delete_delay_days,
            delete_time_base=delete_time_base,
            delete_parent=delete_parent,
            delete_parent_levels=delete_parent_levels,
            delete_parent_force=delete_parent_force
        )

    if scheduler.add_task(task):
        return jsonify({'success': True, 'task': _task_to_dict(task)})
    return jsonify({'success': False, 'error': '添加任务失败'}), 500


@tasks_bp.route('/tasks/<task_id>', methods=['PUT', 'DELETE'])
def api_task_detail(task_id: str):
    """更新或删除任务"""
    scheduler = tasks_bp.scheduler
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
    if 'size_min_bytes' in data:
        updates['size_min_bytes'] = data['size_min_bytes']
    if 'size_max_bytes' in data:
        updates['size_max_bytes'] = data['size_max_bytes']
    if 'suffix_mode' in data:
        updates['suffix_mode'] = (data['suffix_mode'] or 'NONE').upper()
    if 'suffix_list' in data:
        updates['suffix_list'] = data['suffix_list']
    if 'delete_source' in data:
        updates['delete_source'] = _parse_bool(data['delete_source'], getattr(task, 'delete_source', False))
    if 'delete_delay_days' in data:
        raw_delay = data['delete_delay_days']
        if raw_delay in (None, ''):
            updates['delete_delay_days'] = None
        else:
            try:
                delay_val = int(raw_delay)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': '删除延迟天数必须是整数'}), 400
            if delay_val < 0:
                return jsonify({'success': False, 'error': '删除延迟天数不能为负数'}), 400
            updates['delete_delay_days'] = delay_val
    if 'delete_time_base' in data:
        updates['delete_time_base'] = (data['delete_time_base'] or 'SYNC_COMPLETE').upper()
    if 'delete_parent' in data:
        updates['delete_parent'] = _parse_bool(data['delete_parent'], getattr(task, 'delete_parent', False))
    if 'delete_parent_levels' in data:
        raw_levels = data['delete_parent_levels']
        if raw_levels in (None, ''):
            updates['delete_parent_levels'] = 0
        else:
            try:
                levels_val = int(raw_levels)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': '删除目录层级必须是非负整数'}), 400
            if levels_val < 0:
                return jsonify({'success': False, 'error': '删除目录层级必须是非负整数'}), 400
            updates['delete_parent_levels'] = levels_val
    if 'delete_parent_force' in data:
        updates['delete_parent_force'] = _parse_bool(data['delete_parent_force'], getattr(task, 'delete_parent_force', False))

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


@tasks_bp.route('/tasks/<task_id>/trigger', methods=['POST'])
def api_trigger_task(task_id: str):
    """立即触发任务"""
    scheduler = tasks_bp.scheduler
    if scheduler.trigger_task_now(task_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '任务状态非空闲或不存在'}), 400


@tasks_bp.route('/tasks/<task_id>/full-overwrite', methods=['POST'])
def api_full_overwrite_task(task_id: str):
    """全量覆盖：一次性强制覆盖所有已存在文件"""
    scheduler = tasks_bp.scheduler
    log_handler = tasks_bp.log_handler
    
    task = scheduler.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    if task.status.value != 'IDLE':
        return jsonify({'success': False, 'error': '任务状态非空闲，无法执行'}), 400
    
    # 临时设置为覆盖模式
    original_overwrite = task.overwrite_existing
    task.overwrite_existing = True
    
    log_handler(f"🔥 开始执行全量覆盖: {task.name}")
    
    success = scheduler.trigger_task_now(task_id)
    
    if success:
        # 在后台恢复原始设置
        def reset_overwrite():
            import time
            time.sleep(1)
            task.overwrite_existing = original_overwrite
        threading.Thread(target=reset_overwrite, daemon=True).start()
        
        return jsonify({'success': True})
    else:
        task.overwrite_existing = original_overwrite
        return jsonify({'success': False, 'error': '触发任务失败'}), 500


@tasks_bp.route('/logs', methods=['GET'])
def api_logs():
    """获取日志"""
    task_logs = tasks_bp.task_logs
    log_lock = tasks_bp.log_lock
    
    task_id = request.args.get('task_id', 'general')
    with log_lock:
        logs = list(task_logs.get(task_id, []))
    return jsonify({'logs': logs})


@tasks_bp.route('/logs/clear', methods=['POST'])
def api_clear_logs():
    """清除日志"""
    task_logs = tasks_bp.task_logs
    log_lock = tasks_bp.log_lock
    
    task_id = request.args.get('task_id', 'general')
    with log_lock:
        if task_id in task_logs:
            task_logs[task_id] = []
    return jsonify({'success': True})


@tasks_bp.route('/directories', methods=['GET'])
def api_list_directories():
    """列出指定路径下的目录"""
    is_docker = tasks_bp.is_docker
    path = request.args.get('path', '/')
    try:
        # 安全检查：确保路径存在
        target_path = Path(path)
        if not target_path.exists():
            parent = target_path.parent
            if parent.exists() and parent.is_dir():
                target_path = parent
            else:
                target_path = Path('/') if is_docker else Path.home()
        
        # 只列出目录
        dirs = []
        if target_path.is_dir():
            try:
                for item in sorted(target_path.iterdir()):
                    if item.is_dir():
                        try:
                            item.stat()
                            dirs.append({
                                'name': item.name,
                                'path': str(item),
                                'parent': str(item.parent)
                            })
                        except (PermissionError, OSError):
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


@tasks_bp.route('/cron/presets', methods=['GET'])
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


@tasks_bp.route('/cron/random', methods=['GET'])
def api_cron_random():
    """生成随机 Cron 表达式"""
    pattern = request.args.get('pattern', 'hourly')
    
    if pattern == 'daily':
        minute = random.randint(0, 59)
        hour = random.randint(0, 23)
        expression = f"{minute} {hour} * * *"
        description = f"每天 {hour:02d}:{minute:02d} 执行"
    elif pattern == 'hourly':
        minute = random.randint(0, 59)
        expression = f"{minute} * * * *"
        description = f"每小时的第 {minute} 分钟执行"
    elif pattern == 'night':
        minute = random.randint(0, 59)
        hour = random.choice([23, 0, 1, 2, 3, 4, 5])
        expression = f"{minute} {hour} * * *"
        description = f"每天凌晨 {hour:02d}:{minute:02d} 执行"
    else:
        minute = random.randint(0, 59)
        hour = random.randint(0, 23)
        expression = f"{minute} {hour} * * *"
        description = f"每天 {hour:02d}:{minute:02d} 执行"
    
    return jsonify({
        'expression': expression,
        'description': description,
        'pattern': pattern
    })


@tasks_bp.route('/cron/validate', methods=['POST'])
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
