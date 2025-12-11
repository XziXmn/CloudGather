"""
FnOS Media Mover - NAS 文件同步工具
使用 NiceGUI 构建的 Web 界面
"""

import os
from datetime import datetime
from typing import Dict, List
from collections import defaultdict

from nicegui import ui, app

from core.scheduler import TaskScheduler
from core.models import SyncTask, TaskStatus


# 环境适配：判断是否在 Docker 环境中
IS_DOCKER = os.getenv('IS_DOCKER', 'false').lower() == 'true'
CONFIG_PATH = '/app/config/tasks.json' if IS_DOCKER else 'config/tasks.json'

# 全局调度器实例
scheduler = TaskScheduler(config_path=CONFIG_PATH)

# 任务日志存储 (task_id -> list of log messages)
task_logs: Dict[str, List[str]] = defaultdict(list)

# 任务进度存储 (task_id -> progress info)
task_progress: Dict[str, dict] = {}

# 日志对话框状态
current_log_task_id: str | None = None


def log_handler(message: str):
    """
    全局日志处理器

    支持 "task_id|日志内容" 的前缀格式，用于按任务分组显示。

    Args:
        message: 日志消息
    """
    timestamp = datetime.now().strftime('%H:%M:%S')

    # 解析任务前缀
    task_id = None
    raw_message = message
    if '|' in message:
        possible_id, raw = message.split('|', 1)
        if len(possible_id) == 36:  # UUID 长度
            task_id = possible_id
            raw_message = raw

    log_entry = f"[{timestamp}] {raw_message}"
    print(log_entry)

    # 根据任务 ID 存储日志（默认归入 general）
    bucket = task_id or 'general'
    if bucket not in task_logs:
        task_logs[bucket] = []
    task_logs[bucket].append(log_entry)

    # 保留最近 1000 条日志
    if len(task_logs[bucket]) > 1000:
        task_logs[bucket] = task_logs[bucket][-1000:]

    # 完成后清理对应任务的进度
    if task_id and ('复制完成:' in raw_message or '同步完成' in raw_message or '任务执行完成' in raw_message):
        task_progress[task_id] = {'current': 0, 'total': 0, 'percentage': 0}


def progress_handler(task_id: str, current: int, total: int, filename: str):
    """任务进度回调"""
    percentage = int((current / total * 100) if total else 0)
    task_progress[task_id] = {
        'current': current,
        'total': total,
        'percentage': percentage,
        'filename': filename,
    }



# 设置调度器日志回调
scheduler.set_log_callback(log_handler)
scheduler.set_progress_callback(progress_handler)

# 全局主题色
ui.colors(primary='#6366f1', secondary='#0ea5e9', positive='#10b981', warning='#f59e0b')


def get_status_badge(status: TaskStatus) -> dict:
    """
    根据任务状态返回徽章配置
    
    Args:
        status: 任务状态
        
    Returns:
        包含 color 和 text 的字典
    """
    status_config = {
        TaskStatus.IDLE: {'color': 'grey', 'text': '空闲', 'icon': '⚪'},
        TaskStatus.QUEUED: {'color': 'orange', 'text': '队列中', 'icon': '🟡'},
        TaskStatus.RUNNING: {'color': 'green', 'text': '运行中', 'icon': '🟢'},
        TaskStatus.ERROR: {'color': 'red', 'text': '错误', 'icon': '🔴'},
    }
    return status_config.get(status, {'color': 'grey', 'text': '未知', 'icon': '⚫'})


def format_interval(seconds: int) -> str:
    """
    格式化时间间隔
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化后的字符串
    """
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        return f"{seconds // 60}分钟"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}小时{minutes}分钟" if minutes > 0 else f"{hours}小时"


async def show_add_task_dialog():
    """显示添加任务对话框"""
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl shadow-2xl'):
        # 对话框头部
        with ui.row().classes('w-full items-center gap-3 mb-6 pb-4 border-b border-gray-200'):
            ui.icon('add_circle', size='lg').classes('text-blue-600')
            ui.label('添加新任务').classes('text-2xl font-bold text-gray-800')
        
        with ui.column().classes('w-full gap-4'):
            name_input = ui.input('任务名称', placeholder='例如: 电影同步').classes('w-full').props('outlined')
            source_input = ui.input('源目录', placeholder='/nas/downloads/movies').classes('w-full').props('outlined')
            target_input = ui.input('目标目录', placeholder='/nas/media/movies').classes('w-full').props('outlined')
            interval_input = ui.number('同步间隔(秒)', value=300, min=10, max=86400).classes('w-full').props('outlined')
            
            with ui.card().classes('w-full bg-blue-50 border border-blue-200'):
                ui.label('高级选项').classes('font-semibold text-blue-800 mb-2')
                with ui.row().classes('w-full gap-4'):
                    recursive_checkbox = ui.checkbox('递归同步子目录', value=True)
                    verify_md5_checkbox = ui.checkbox('MD5校验', value=False)
                    enabled_checkbox = ui.checkbox('启用任务', value=True)
            
            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('取消', on_click=dialog.close, icon='close').props('flat')
                
                async def add_task():
                    # 验证输入
                    if not name_input.value or not source_input.value or not target_input.value:
                        ui.notify('⚠ 请填写所有必填项', type='warning', position='top')
                        return
                    
                    # 创建任务
                    task = SyncTask(
                        name=name_input.value,
                        source_path=source_input.value,
                        target_path=target_input.value,
                        interval=int(interval_input.value),
                        recursive=recursive_checkbox.value,
                        verify_md5=verify_md5_checkbox.value,
                        enabled=enabled_checkbox.value
                    )
                    
                    # 添加到调度器
                    if scheduler.add_task(task):
                        ui.notify(f'✓ 任务已添加: {task.name}', type='positive', position='top')
                        dialog.close()
                    else:
                        ui.notify('✗ 添加任务失败', type='negative', position='top')
                
                ui.button('添加', on_click=add_task, icon='check').props('color=primary unelevated')
    
    dialog.open()


async def show_edit_task_dialog(task: SyncTask):
    """显示编辑任务对话框"""
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl shadow-2xl'):
        # 对话框头部
        with ui.row().classes('w-full items-center gap-3 mb-6 pb-4 border-b border-gray-200'):
            ui.icon('edit', size='lg').classes('text-blue-600')
            ui.label(f'编辑任务: {task.name}').classes('text-2xl font-bold text-gray-800')
        
        with ui.column().classes('w-full gap-4'):
            name_input = ui.input('任务名称', value=task.name).classes('w-full').props('outlined')
            source_input = ui.input('源目录', value=task.source_path).classes('w-full').props('outlined')
            target_input = ui.input('目标目录', value=task.target_path).classes('w-full').props('outlined')
            interval_input = ui.number('同步间隔(秒)', value=task.interval, min=10, max=86400).classes('w-full').props('outlined')
            
            with ui.card().classes('w-full bg-blue-50 border border-blue-200'):
                ui.label('高级选项').classes('font-semibold text-blue-800 mb-2')
                with ui.row().classes('w-full gap-4'):
                    recursive_checkbox = ui.checkbox('递归同步子目录', value=task.recursive)
                    verify_md5_checkbox = ui.checkbox('MD5校验', value=task.verify_md5)
                    enabled_checkbox = ui.checkbox('启用任务', value=task.enabled)
            
            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('取消', on_click=dialog.close, icon='close').props('flat')
                
                async def update_task():
                    # 更新任务
                    if scheduler.update_task(
                        task.id,
                        name=name_input.value,
                        source_path=source_input.value,
                        target_path=target_input.value,
                        interval=int(interval_input.value),
                        recursive=recursive_checkbox.value,
                        verify_md5=verify_md5_checkbox.value,
                        enabled=enabled_checkbox.value
                    ):
                        ui.notify(f'✓ 任务已更新: {task.name}', type='positive', position='top')
                        dialog.close()
                    else:
                        ui.notify('✗ 更新任务失败', type='negative', position='top')
                
                ui.button('保存', on_click=update_task, icon='save').props('color=primary unelevated')
    
    dialog.open()


log_dialog = ui.dialog().props('persistent no-esc-dismiss no-backdrop-dismiss')
with log_dialog, ui.card().classes('w-full max-w-4xl bg-slate-900 text-slate-100 shadow-2xl border border-slate-800'):
    with ui.row().classes('w-full justify-between items-center mb-3'):
        log_title = ui.label('📋 任务日志').classes('text-2xl font-bold')
        ui.button(icon='close', on_click=lambda: close_log_dialog()).props('flat round dense color=white')

    log_container = ui.column().classes('w-full')
    with ui.scroll_area().classes('w-full h-[520px] rounded border border-slate-700 bg-slate-950/70 p-4 shadow-inner'):
        with log_container:
            ui.label('暂无日志').classes('text-slate-500')

    with ui.row().classes('w-full justify-between items-center mt-3 text-sm text-slate-300'):
        log_hint = ui.label('日志实时刷新中...')
        ui.button('清空日志', on_click=lambda: (task_logs.clear(), refresh_log_content(current_log_task_id)), icon='delete_sweep').props('outline color=warning')


def refresh_log_content(task_id: str | None):
    if not task_id:
        return

    log_container.clear()
    if task_id == 'general':
        logs = task_logs.get('general', [])
    else:
        logs = task_logs.get(task_id, [])

    with log_container:
        if logs:
            for log in logs[-200:]:
                ui.label(log).classes('font-mono text-sm text-emerald-300')
        else:
            ui.label('暂无日志').classes('text-slate-500')

    ui.run_javascript('const area = document.querySelector(".q-scrollarea__container"); if(area){area.scrollTop = area.scrollHeight;}')


def close_log_dialog():
    global current_log_task_id
    current_log_task_id = None
    log_timer.active = False
    log_dialog.close()


def show_task_logs(task_id: str, task_name: str):
    """显示任务日志对话框（常驻刷新）"""
    global current_log_task_id
    current_log_task_id = task_id
    log_title.set_text(f'📋 任务日志: {task_name}')
    refresh_log_content(task_id)
    log_timer.active = True
    log_dialog.open()


log_timer = ui.timer(1.0, lambda: refresh_log_content(current_log_task_id), active=False)


async def confirm_delete_task(task: SyncTask):
    """确认删除任务"""
    with ui.dialog() as dialog, ui.card().classes('shadow-2xl'):
        with ui.row().classes('w-full items-center gap-3 mb-4'):
            ui.icon('warning', size='lg').classes('text-red-600')
            ui.label('确认删除').classes('text-xl font-bold text-gray-800')
        
        ui.label(f'确定要删除任务 "{task.name}" 吗？').classes('mb-4 text-gray-700')
        ui.label('此操作不可恢复！').classes('mb-4 text-sm text-red-600')
        
        with ui.row().classes('gap-2 justify-end'):
            ui.button('取消', on_click=dialog.close, icon='close').props('flat')
            
            async def delete_task():
                if scheduler.remove_task(task.id):
                    ui.notify(f'✓ 任务已删除: {task.name}', type='positive', position='top')
                    dialog.close()
                else:
                    ui.notify('✗ 删除任务失败', type='negative', position='top')
            
            ui.button('删除', on_click=delete_task, icon='delete').props('color=negative unelevated')
    
    dialog.open()


def render_task_card(task: SyncTask):
    """
    渲染任务卡片
    
    Args:
        task: 同步任务对象
    """
    status_badge = get_status_badge(task.status)
    
    # 美化卡片样式
    card_style = 'shadow-xl hover:shadow-2xl transition-all duration-300 border border-slate-200/70 backdrop-blur bg-white/90'
    border_color = 'border-l-4 border-emerald-500' if task.status == TaskStatus.RUNNING else 'border-l-4 border-slate-200'

    with ui.card().classes(f'w-full mb-4 {card_style} {border_color}'):
        # 卡片头部
        with ui.row().classes('w-full justify-between items-center mb-3'):
            with ui.row().classes('items-center gap-3'):
                ui.label(status_badge['icon']).classes('text-3xl')
                with ui.column().classes('gap-0'):
                    ui.label(task.name).classes('text-xl font-bold text-gray-800')
                    if task.enabled:
                        ui.label('已启用').classes('text-xs text-green-600')
                    else:
                        ui.label('已禁用').classes('text-xs text-gray-400')
            
            ui.badge(status_badge['text']).props(f"color={status_badge['color']}")
        
        # 进度条（仅在运行时显示）
        if task.status == TaskStatus.RUNNING:
            progress_info = task_progress.get(task.id, {})
            progress_value = progress_info.get('percentage', 0)
            current_file = progress_info.get('filename', '')
            total_files = progress_info.get('total', 0)
            current_index = progress_info.get('current', 0)

            with ui.column().classes('w-full mb-3 bg-slate-100/60 p-3 rounded-lg'):
                with ui.row().classes('w-full justify-between items-center mb-1'):
                    ui.label('同步进度').classes('text-sm font-semibold text-gray-700')
                    ui.label(f'{progress_value}%').classes('text-sm font-mono text-emerald-700')

                ui.linear_progress(progress_value / 100).props('color=positive instant-feedback rounded')

                if current_file:
                    ui.label(f'正在处理: {current_file} ({current_index}/{total_files})').classes('text-xs text-slate-600 mt-1 font-mono')
        
        # 卡片内容
        with ui.column().classes('w-full gap-2 mb-3 bg-gray-50 p-3 rounded'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('folder_open', size='sm').classes('text-blue-500')
                ui.label('源路径:').classes('text-xs font-semibold text-gray-600')
                ui.label(task.source_path).classes('text-sm text-gray-800 font-mono')
            
            with ui.row().classes('items-center gap-2'):
                ui.icon('folder', size='sm').classes('text-green-500')
                ui.label('目标路径:').classes('text-xs font-semibold text-gray-600')
                ui.label(task.target_path).classes('text-sm text-gray-800 font-mono')
            
            with ui.row().classes('items-center gap-4'):
                with ui.row().classes('items-center gap-1'):
                    ui.icon('schedule', size='sm').classes('text-orange-500')
                    ui.label(f"间隔: {format_interval(task.interval)}").classes('text-sm text-gray-700')
                
                if task.verify_md5:
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('verified', size='sm').classes('text-purple-500')
                        ui.label('MD5校验').classes('text-xs text-purple-600')
                
                if task.recursive:
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('account_tree', size='sm').classes('text-teal-500')
                        ui.label('递归').classes('text-xs text-teal-600')
            
            if task.last_run_time:
                try:
                    last_run = datetime.fromisoformat(task.last_run_time).strftime('%Y-%m-%d %H:%M:%S')
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('access_time', size='sm').classes('text-gray-500')
                        ui.label(f"上次运行: {last_run}").classes('text-xs text-gray-600')
                except:
                    pass
        
        # 卡片按钮
        with ui.row().classes('gap-2'):
            def trigger_now():
                if scheduler.trigger_task_now(task.id):
                    ui.notify(f'✓ 任务已触发: {task.name}', type='positive', position='top')
                else:
                    ui.notify('⚠ 无法触发任务 (任务正在运行或队列中)', type='warning', position='top')
            
            ui.button('立即运行', on_click=trigger_now, icon='play_arrow').props('size=sm unelevated color=positive')
            ui.button('编辑', on_click=lambda: show_edit_task_dialog(task), icon='edit').props('size=sm outline color=primary')
            ui.button('日志', on_click=lambda: show_task_logs(task.id, task.name), icon='article').props('size=sm outline color=info')
            ui.button('删除', on_click=lambda: confirm_delete_task(task), icon='delete').props('size=sm outline color=negative')


@ui.page('/')
def main_page():
    """主页面 - 任务列表"""

    with ui.row().classes('w-full h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 text-slate-50'):
        # 左侧侧边栏
        with ui.column().classes('w-72 h-full bg-slate-900/80 border-r border-slate-800 p-5 gap-3 shadow-2xl backdrop-blur-xl'):
            with ui.row().classes('items-center gap-3 mb-6'):
                ui.icon('movie', size='lg').classes('text-emerald-400')
                ui.label('FnOS Media Mover').classes('text-xl font-bold text-white')

            # 导航
            with ui.column().classes('w-full gap-2'):
                ui.button('📋 任务面板', on_click=lambda: ui.navigate.to('/')).props('flat align=left color=white').classes('w-full justify-start hover:bg-emerald-500/20')
                ui.button('🧪 实验室', on_click=lambda: ui.navigate.to('/lab')).props('flat align=left color=white').classes('w-full justify-start hover:bg-emerald-500/20')
                ui.button('⚙️ 设置', on_click=lambda: ui.navigate.to('/settings')).props('flat align=left color=white').classes('w-full justify-start hover:bg-emerald-500/20')

            ui.separator().classes('bg-slate-700 my-2')

            with ui.card().classes('w-full bg-slate-800/80 border border-slate-700 shadow-lg'):
                ui.label('调度器').classes('font-bold text-slate-100 mb-2')
                scheduler_status = ui.label().classes('text-sm text-emerald-400')
                queue_size = ui.label().classes('text-xs text-slate-300')

                def update_scheduler_status():
                    scheduler_status.set_text('🟢 正在运行' if scheduler.is_running else '🔴 已停止')
                    queue_size.set_text(f'队列: {scheduler.get_queue_size()} 个任务')

                ui.timer(1.0, update_scheduler_status)

            ui.space()
            ui.label('v1.0.0').classes('text-xs text-slate-500 text-center')

        # 右侧主内容区
        with ui.column().classes('flex-1 h-full p-8 overflow-auto gap-6 bg-gradient-to-br from-slate-900/50 to-slate-800/40 backdrop-blur-xl'):
            # 顶部标题与操作
            with ui.row().classes('w-full justify-between items-center'):
                with ui.column().classes('gap-1'):
                    ui.label('📋 同步任务').classes('text-4xl font-bold text-white')
                    ui.label('让多端文件同步更智能、更可视').classes('text-sm text-slate-400')

                ui.button('添加任务', on_click=show_add_task_dialog, icon='add').props('color=primary size=lg unelevated').classes('shadow-lg')

            # 概览卡片
            with ui.row().classes('w-full gap-4 flex-wrap'):
                overview_card = lambda title, icon, color: ui.card().classes('flex-1 min-w-[200px] bg-white/5 border border-slate-800 shadow-xl backdrop-blur p-4 flex items-center gap-3')
                with overview_card('总任务', 'list', 'emerald'):
                    total_label = ui.label('0').classes('text-3xl font-bold text-white')
                    ui.label('总任务').classes('text-sm text-slate-400')
                    ui.icon('list').classes('text-emerald-400 ml-auto')
                with overview_card('运行中', 'play_arrow', 'amber'):
                    running_label = ui.label('0').classes('text-3xl font-bold text-white')
                    ui.label('运行中').classes('text-sm text-slate-400')
                    ui.icon('play_arrow').classes('text-amber-300 ml-auto')
                with overview_card('队列长度', 'schedule', 'blue'):
                    queue_label = ui.label('0').classes('text-3xl font-bold text-white')
                    ui.label('队列长度').classes('text-sm text-slate-400')
                    ui.icon('schedule').classes('text-sky-300 ml-auto')

            # 任务列表
            task_list_container = ui.column().classes('w-full gap-4')

            def refresh_task_list():
                tasks = scheduler.get_all_tasks()

                total_label.set_text(str(len(tasks)))
                running_label.set_text(str(len([t for t in tasks if t.status == TaskStatus.RUNNING])))
                queue_label.set_text(str(scheduler.get_queue_size()))

                task_list_container.clear()
                with task_list_container:
                    if not tasks:
                        with ui.card().classes('w-full text-center p-12 bg-white/5 border border-slate-800 shadow-xl backdrop-blur'):
                            ui.icon('inbox', size='xl').classes('text-slate-500 mb-4')
                            ui.label('暂无任务').classes('text-2xl text-white font-bold mb-2')
                            ui.label('点击右上角“添加任务”开启第一次同步').classes('text-sm text-slate-400')
                    else:
                        for task in tasks:
                            render_task_card(task)

            ui.timer(1.0, refresh_task_list)


@ui.page('/lab')
def lab_page():
    """实验室页面"""
    with ui.row().classes('w-full h-screen'):
        # 左侧侧边栏
        with ui.column().classes('w-64 h-full bg-gray-100 p-4 gap-2'):
            ui.label('FnOS Media Mover').classes('text-2xl font-bold mb-4 text-blue-600')
            
            with ui.column().classes('w-full gap-1'):
                ui.button('📋 任务', on_click=lambda: ui.navigate.to('/')).props('flat align=left').classes('w-full justify-start')
                ui.button('🧪 实验室', on_click=lambda: ui.navigate.to('/lab')).props('flat align=left').classes('w-full justify-start')
                ui.button('⚙️ 设置', on_click=lambda: ui.navigate.to('/settings')).props('flat align=left').classes('w-full justify-start')
        
        # 右侧主内容区
        with ui.column().classes('flex-1 h-full p-6'):
            ui.label('🧪 实验室').classes('text-3xl font-bold mb-6')
            
            with ui.card().classes('w-full'):
                ui.label('调试工具').classes('text-xl font-bold mb-4')
                
                with ui.row().classes('gap-2'):
                    ui.button('测试通知', on_click=lambda: ui.notify('这是一条测试通知', type='info'))
                    ui.button('清空日志', on_click=lambda: task_logs.clear() or ui.notify('日志已清空', type='positive'))


@ui.page('/settings')
def settings_page():
    """设置页面"""
    with ui.row().classes('w-full h-screen'):
        # 左侧侧边栏
        with ui.column().classes('w-64 h-full bg-gray-100 p-4 gap-2'):
            ui.label('FnOS Media Mover').classes('text-2xl font-bold mb-4 text-blue-600')
            
            with ui.column().classes('w-full gap-1'):
                ui.button('📋 任务', on_click=lambda: ui.navigate.to('/')).props('flat align=left').classes('w-full justify-start')
                ui.button('🧪 实验室', on_click=lambda: ui.navigate.to('/lab')).props('flat align=left').classes('w-full justify-start')
                ui.button('⚙️ 设置', on_click=lambda: ui.navigate.to('/settings')).props('flat align=left').classes('w-full justify-start')
        
        # 右侧主内容区
        with ui.column().classes('flex-1 h-full p-6'):
            ui.label('⚙️ 设置').classes('text-3xl font-bold mb-6')
            
            with ui.card().classes('w-full mb-4'):
                ui.label('环境信息').classes('text-xl font-bold mb-4')
                
                with ui.column().classes('gap-2'):
                    ui.label(f'运行环境: {"Docker 容器" if IS_DOCKER else "本地开发"}').classes('text-sm')
                    ui.label(f'配置文件: {CONFIG_PATH}').classes('text-sm')
                    ui.label(f'调度器状态: {"运行中" if scheduler.is_running else "已停止"}').classes('text-sm')
            
            with ui.card().classes('w-full'):
                ui.label('调度器控制').classes('text-xl font-bold mb-4')
                
                with ui.row().classes('gap-2'):
                    async def start_scheduler():
                        scheduler.start()
                        ui.notify('调度器已启动', type='positive')
                    
                    async def stop_scheduler():
                        scheduler.stop()
                        ui.notify('调度器已停止', type='warning')
                    
                    ui.button('启动调度器', on_click=start_scheduler, icon='play_arrow').props('color=positive')
                    ui.button('停止调度器', on_click=stop_scheduler, icon='stop').props('color=warning')


# 应用启动时自动启动调度器
app.on_startup(lambda: scheduler.start())

# 应用关闭时停止调度器
app.on_shutdown(lambda: scheduler.stop())


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='FnOS Media Mover',
        host='0.0.0.0' if IS_DOCKER else '127.0.0.1',
        port=8080,
        reload=not IS_DOCKER,  # Docker 环境中禁用热重载
        show=not IS_DOCKER,  # 本地环境自动打开浏览器
        favicon='🎬'
    )

