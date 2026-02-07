"""
STRM 任务管理 API 蓝图
"""
import logging
import threading
from typing import Dict
from flask import Blueprint, jsonify, request

from core.models import StrmTask
from core.strm_generator import StrmGenerator

strm_bp = Blueprint('strm', __name__)


def init_strm_bp(scheduler, log_handler):
    """初始化 STRM 任务蓝图，注入依赖"""
    strm_bp.scheduler = scheduler
    strm_bp.log_handler = log_handler


def _task_to_dict(task: StrmTask) -> dict:
    """将 STRM 任务对象转换为字典"""
    scheduler = strm_bp.scheduler
    data = task.to_dict()
    
    # 添加下次执行时间
    job_id = f"strm_{task.id}"
    job = scheduler.scheduler.get_job(job_id)
    if job and job.next_run_time:
        data['next_run_time'] = job.next_run_time.isoformat()
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


@strm_bp.route('/strm/tasks', methods=['GET', 'POST'])
def api_strm_tasks():
    """获取所有 STRM 任务或创建新任务"""
    scheduler = strm_bp.scheduler
    
    if request.method == 'GET':
        tasks = [_task_to_dict(t) for t in scheduler.strm_tasks.values()]
        return jsonify({'tasks': tasks})
    
    # POST - 创建新任务
    data = request.get_json(silent=True) or {}
    required_fields = ['name', 'source_dir', 'target_dir']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({'success': False, 'error': f"缺少字段: {', '.join(missing)}"}), 400
    
    # 获取调度类型
    schedule_type = data.get('schedule_type', 'INTERVAL')
    
    try:
        if schedule_type == 'CRON':
            # Cron 调度
            cron_expression = data.get('cron_expression', '').strip()
            if not cron_expression:
                return jsonify({'success': False, 'error': 'Cron 表达式不能为空'}), 400
            
            # 验证 cron 表达式格式
            parts = cron_expression.split()
            if len(parts) != 5:
                return jsonify({'success': False, 'error': 'Cron 表达式格式错误，应为 5 个字段：分 时 日 月 星期'}), 400
            
            task = StrmTask(
                name=data['name'],
                source_dir=data['source_dir'],
                target_dir=data['target_dir'],
                schedule_type='CRON',
                cron_expression=cron_expression,
                interval=3600,  # cron 模式下 interval 不使用，但 need 默认值
                enabled=_parse_bool(data.get('enabled', True), True),
                openlist_url=data.get('openlist_url'),
                openlist_username=data.get('openlist_username'),
                openlist_password=data.get('openlist_password'),
                openlist_token=data.get('openlist_token'),
                openlist_public_url=data.get('openlist_public_url'),
                mode=data.get('mode', 'AlistURL'),
                flatten_mode=_parse_bool(data.get('flatten_mode', False), False),
                subtitle=_parse_bool(data.get('subtitle', False), False),
                image=_parse_bool(data.get('image', False), False),
                nfo=_parse_bool(data.get('nfo', False), False),
                overwrite=_parse_bool(data.get('overwrite', False), False),
                other_ext=data.get('other_ext'),
                max_workers=int(data.get('max_workers', 50)),
                max_downloaders=int(data.get('max_downloaders', 5)),
                wait_time=float(data.get('wait_time', 0)),
                sync_server=_parse_bool(data.get('sync_server', False), False),
                sync_local_delete=_parse_bool(data.get('sync_local_delete', False), False),
                sync_ignore=data.get('sync_ignore'),
                suffix_mode=data.get('suffix_mode', 'NONE'),
                suffix_list=data.get('suffix_list', []),
                smart_protection=data.get('smart_protection', {"threshold": 100, "grace_scans": 3})
            )
        else:
            # 间隔调度
            try:
                interval = int(data.get('interval', 3600))
            except ValueError:
                return jsonify({'success': False, 'error': '同步间隔必须是数字'}), 400
            
            if interval < 60:
                return jsonify({'success': False, 'error': '同步间隔需大于等于 60 秒'}), 400
            
            task = StrmTask(
                name=data['name'],
                source_dir=data['source_dir'],
                target_dir=data['target_dir'],
                schedule_type='INTERVAL',
                interval=interval,
                enabled=_parse_bool(data.get('enabled', True), True),
                openlist_url=data.get('openlist_url'),
                openlist_username=data.get('openlist_username'),
                openlist_password=data.get('openlist_password'),
                openlist_token=data.get('openlist_token'),
                openlist_public_url=data.get('openlist_public_url'),
                mode=data.get('mode', 'AlistURL'),
                flatten_mode=_parse_bool(data.get('flatten_mode', False), False),
                subtitle=_parse_bool(data.get('subtitle', False), False),
                image=_parse_bool(data.get('image', False), False),
                nfo=_parse_bool(data.get('nfo', False), False),
                overwrite=_parse_bool(data.get('overwrite', False), False),
                other_ext=data.get('other_ext'),
                max_workers=int(data.get('max_workers', 50)),
                max_downloaders=int(data.get('max_downloaders', 5)),
                wait_time=float(data.get('wait_time', 0)),
                sync_server=_parse_bool(data.get('sync_server', False), False),
                sync_local_delete=_parse_bool(data.get('sync_local_delete', False), False),
                sync_ignore=data.get('sync_ignore'),
                suffix_mode=data.get('suffix_mode', 'NONE'),
                suffix_list=data.get('suffix_list', []),
                smart_protection=data.get('smart_protection', {"threshold": 100, "grace_scans": 3})
            )
        
        # 添加到调度器
        scheduler.strm_tasks[task.id] = task
        
        # 如果任务启用且调度器已运行，则添加定时任务
        if task.enabled and scheduler.is_running:
            scheduler._schedule_task(task, system_key='strm')
        
        # 保存配置
        scheduler.save_strm_tasks()
        
        if strm_bp.log_handler:
            strm_bp.log_handler(f"✓ STRM 任务添加完成: {task.name}")
        
        return jsonify({'success': True, 'task': _task_to_dict(task)})
        
    except Exception as e:
        logging.error(f"创建 STRM 任务失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@strm_bp.route('/strm/tasks/<task_id>', methods=['GET', 'PUT', 'DELETE'])
def api_strm_task(task_id: str):
    """获取、更新或删除指定的 STRM 任务"""
    scheduler = strm_bp.scheduler
    
    if task_id not in scheduler.strm_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    if request.method == 'GET':
        task = scheduler.strm_tasks[task_id]
        return jsonify({'success': True, 'task': _task_to_dict(task)})
    
    elif request.method == 'DELETE':
        # 删除任务
        task = scheduler.strm_tasks[task_id]
        
        # 从调度器中移除
        job_id = f"strm_{task_id}"
        if scheduler.scheduler.get_job(job_id):
            scheduler.scheduler.remove_job(job_id)
        
        # 从任务字典中移除
        del scheduler.strm_tasks[task_id]
        
        # 保存配置
        scheduler.save_strm_tasks()
        
        if strm_bp.log_handler:
            strm_bp.log_handler(f"✓ STRM 任务已移除: {task.name}")
        
        return jsonify({'success': True})
    
    elif request.method == 'PUT':
        # 更新任务
        data = request.get_json(silent=True) or {}
        task = scheduler.strm_tasks[task_id]
        
        old_enabled = task.enabled
        old_interval = task.interval
        old_cron = task.cron_expression
        old_schedule_type = task.schedule_type
        
        try:
            # 更新字段
            if 'name' in data:
                task.name = data['name']
            if 'source_dir' in data:
                task.source_dir = data['source_dir']
            if 'target_dir' in data:
                task.target_dir = data['target_dir']
            if 'interval' in data:
                task.interval = int(data['interval'])
            if 'schedule_type' in data:
                task.schedule_type = data['schedule_type']
            if 'cron_expression' in data:
                task.cron_expression = data['cron_expression']
            if 'enabled' in data:
                task.enabled = _parse_bool(data['enabled'], True)
            
            # OpenList 配置
            if 'openlist_url' in data:
                task.openlist_url = data['openlist_url']
            if 'openlist_username' in data:
                task.openlist_username = data['openlist_username']
            if 'openlist_password' in data:
                task.openlist_password = data['openlist_password']
            if 'openlist_token' in data:
                task.openlist_token = data['openlist_token']
            if 'openlist_public_url' in data:
                task.openlist_public_url = data['openlist_public_url']
            
            # STRM 配置
            if 'mode' in data:
                task.mode = data['mode']
            if 'flatten_mode' in data:
                task.flatten_mode = _parse_bool(data['flatten_mode'], False)
            if 'subtitle' in data:
                task.subtitle = _parse_bool(data['subtitle'], False)
            if 'image' in data:
                task.image = _parse_bool(data['image'], False)
            if 'nfo' in data:
                task.nfo = _parse_bool(data['nfo'], False)
            if 'overwrite' in data:
                task.overwrite = _parse_bool(data['overwrite'], False)
            if 'other_ext' in data:
                task.other_ext = data['other_ext']
            
            # 性能配置
            if 'max_workers' in data:
                task.max_workers = int(data['max_workers'])
            if 'max_downloaders' in data:
                task.max_downloaders = int(data['max_downloaders'])
            if 'wait_time' in data:
                task.wait_time = float(data['wait_time'])
            
            # 同步配置
            if 'sync_server' in data:
                task.sync_server = _parse_bool(data['sync_server'], False)
            if 'sync_local_delete' in data:
                task.sync_local_delete = _parse_bool(data['sync_local_delete'], False)
            if 'sync_ignore' in data:
                task.sync_ignore = data['sync_ignore']
            if 'suffix_mode' in data:
                task.suffix_mode = data['suffix_mode']
            if 'suffix_list' in data:
                task.suffix_list = data['suffix_list']
            if 'smart_protection' in data:
                task.smart_protection = data['smart_protection']
            
            # 如果间隔、启用状态或调度类型改变，重新调度
            schedule_changed = (
                task.interval != old_interval or
                task.enabled != old_enabled or
                task.schedule_type != old_schedule_type or
                task.cron_expression != old_cron
            )
            
            if schedule_changed and scheduler.is_running:
                job_id = f"strm_{task_id}"
                if scheduler.scheduler.get_job(job_id):
                    scheduler.scheduler.remove_job(job_id)
                
                if task.enabled:
                    scheduler._schedule_task(task, system_key='strm')
            
            # 保存配置
            scheduler.save_strm_tasks()
            
            if strm_bp.log_handler:
                strm_bp.log_handler(f"✓ STRM 任务已更新: {task.name}")
            
            return jsonify({'success': True, 'task': _task_to_dict(task)})
            
        except Exception as e:
            logging.error(f"更新 STRM 任务失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)}), 500


@strm_bp.route('/strm/tasks/<task_id>/trigger', methods=['POST'])
def api_trigger_strm_task(task_id: str):
    """立即触发 STRM 任务执行"""
    scheduler = strm_bp.scheduler
    
    if task_id not in scheduler.strm_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    task = scheduler.strm_tasks[task_id]
    
    if task.status.value != 'IDLE':
        return jsonify({'success': False, 'error': f'任务状态非空闲，无法立即执行 (状态: {task.status.value})'}), 400
    
    # 手动触发
    scheduler._on_task_triggered(task_id, system_key='strm')
    
    if strm_bp.log_handler:
        strm_bp.log_handler(f"⚡ 手动触发 STRM 任务: {task.name}")
    
    return jsonify({'success': True})


@strm_bp.route('/strm/tasks/<task_id>/toggle', methods=['POST'])
def api_toggle_strm_task(task_id: str):
    """启用/禁用 STRM 任务"""
    scheduler = strm_bp.scheduler
    
    if task_id not in scheduler.strm_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    task = scheduler.strm_tasks[task_id]
    task.enabled = not task.enabled
    
    # 更新调度
    job_id = f"strm_{task_id}"
    if scheduler.is_running:
        if scheduler.scheduler.get_job(job_id):
            scheduler.scheduler.remove_job(job_id)
        
        if task.enabled:
            scheduler._schedule_task(task, system_key='strm')
    
    # 保存配置
    scheduler.save_strm_tasks()
    
    status_text = "启用" if task.enabled else "禁用"
    if strm_bp.log_handler:
        strm_bp.log_handler(f"✓ STRM 任务已{status_text}: {task.name}")
    
    return jsonify({'success': True, 'enabled': task.enabled})


@strm_bp.route('/strm/tasks/<task_id>/full-overwrite', methods=['POST'])
def api_strm_full_overwrite(task_id: str):
    """触发全量覆盖生成"""
    scheduler = strm_bp.scheduler
    log_handler = strm_bp.log_handler
    
    if task_id not in scheduler.strm_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    task = scheduler.strm_tasks[task_id]
    if task.status.value != 'IDLE':
        return jsonify({'success': False, 'error': '任务状态非空闲，无法执行'}), 400
    
    def run_full_overwrite():
        try:
            log_handler(f"🚀 开始对 STRM 任务「{task.name}」执行全量覆盖生成...")
            generator = StrmGenerator(task, scheduler.db)
            generator.task.overwrite = True # 临时覆盖
            generator.run(log_callback=log_handler)
            log_handler(f"✅ 任务「{task.name}」全量覆盖生成完成")
        except Exception as e:
            log_handler(f"❌ 任务「{task.name}」执行失败: {e}")
            
    threading.Thread(target=run_full_overwrite, daemon=True).start()
    return jsonify({'success': True, 'message': '任务已启动'})


@strm_bp.route('/strm/tasks/<task_id>/reconstruct', methods=['POST'])
def api_strm_reconstruct(task_id: str):
    """重构 STRM 任务缓存"""
    scheduler = strm_bp.scheduler
    log_handler = strm_bp.log_handler
    
    if task_id not in scheduler.strm_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    task = scheduler.strm_tasks[task_id]
    if task.status.value != 'IDLE':
        return jsonify({'success': False, 'error': '任务状态非空闲，无法执行'}), 400
    
    def run_reconstruction():
        try:
            log_handler(f"🛠 开始对 STRM 任务「{task.name}」执行缓存重构...")
            generator = StrmGenerator(task, scheduler.db)
            generator.reconstruct_cache_from_target(log_callback=log_handler)
            log_handler(f"✅ 任务「{task.name}」缓存重构完成")
        except Exception as e:
            log_handler(f"❌ 任务「{task.name}」缓存重构失败: {e}")
            
    threading.Thread(target=run_reconstruction, daemon=True).start()
    return jsonify({'success': True, 'message': '缓存重构已在后台启动'})
