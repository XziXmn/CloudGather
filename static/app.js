// CloudGather - 蓝粉白纯色 + 独立日志窗 + MD侧边栏 + Cron 调度 + 一言
let currentEditingTaskId = null;
let lastTasksData = null;
let tasksCache = [];
let queueCache = [];
let currentView = 'dashboard';
let taskFormDirty = false; // 表单是否已修改

function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    const toggle = document.getElementById('themeToggle');
    if (toggle) {
        toggle.innerHTML = theme === 'light'
            ? '<i class="fas fa-sun"></i><span class="hidden sm:inline">浅色</span>'
            : '<i class="fas fa-moon"></i><span class="hidden sm:inline">深色</span>';
    }
    localStorage.setItem('cg-theme', theme);
}

function toggleTheme() {
    const next = document.body.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    applyTheme(next);
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mask = document.getElementById('sidebar-mask');
    
    // 只在移动端执行切换逻辑
    if (window.innerWidth <= 1024) {
        sidebar.classList.toggle('show');
        if (mask) {
            mask.classList.toggle('show');
        }
    }
}

function setActiveNav(view, navEl = null) {
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    const el = navEl || document.querySelector(`.nav-item[data-view="${view}"]`);
    if (el) el.classList.add('active');
}

function switchView(view, navEl = null) {
    currentView = view;
    setActiveNav(view, navEl);
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById(`view-${view}`);
    if (target) target.classList.add('active');

    if (view === 'tasks') {
        loadTasks();
    } else if (view === 'about') {
        loadSystemStatus();
    } else if (view === 'dashboard') {
        loadSystemStatus();
        loadTasks();
    } else if (view === 'system-settings') {
        loadOpenListConfig();
        loadFileExtensions();
        loadSystemConfig();
    }
}

// 日志窗口相关逻辑已拆分到 app-logs.js

async function loadSystemStatus() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000); // 5秒超时
        
        const response = await fetch('/api/status', {
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        const data = await response.json();
        document.getElementById('stat-total').textContent = data.task_count;
        document.getElementById('stat-queued').textContent = data.queue_size;
        document.getElementById('stat-scheduler').textContent = data.running ? '运行中' : '异常';

        if (data.system) {
            const cpu = Math.round(data.system.cpu_percent);
            const memPercent = Math.round(data.system.memory_percent);
            const memUsed = formatBytes(data.system.memory_used);
            const memTotal = formatBytes(data.system.memory_total);
            document.getElementById('cpu-percent').textContent = cpu + '%';
            document.getElementById('cpu-progress').style.width = cpu + '%';
            document.getElementById('memory-text').textContent = `${memUsed} / ${memTotal}`;
            document.getElementById('memory-percent').textContent = memPercent + '%';
            document.getElementById('memory-progress').style.width = memPercent + '%';
            
            // 磁盘信息
            if (data.system.disk_total) {
                const diskPercent = Math.round(data.system.disk_percent);
                const diskUsed = formatBytes(data.system.disk_used);
                const diskTotal = formatBytes(data.system.disk_total);
                document.getElementById('disk-text').textContent = `${diskUsed} / ${diskTotal}`;
                document.getElementById('disk-percent').textContent = diskPercent + '%';
                document.getElementById('disk-progress').style.width = diskPercent + '%';
            }
        }
        
        // 最近执行任务
        if (data.recent_tasks && data.recent_tasks.length > 0) {
            const recentHtml = data.recent_tasks.map(t => {
                const time = t.last_run_time ? new Date(t.last_run_time).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}) : '-';
                return `<div class="flex items-center justify-between py-1 border-b border-gray-100 dark:border-gray-700 last:border-0">
                    <span class="truncate flex-1" title="${t.name}">${t.name}</span>
                    <span class="text-xs text-gray-500 ml-2">${time}</span>
                </div>`;
            }).join('');
            document.getElementById('recent-tasks').innerHTML = recentHtml;
        } else {
            document.getElementById('recent-tasks').innerHTML = '<p class="text-gray-500">暂无最近执行记录</p>';
        }
        
        document.getElementById('config-path').textContent = data.config_path;
        document.getElementById('is-docker').textContent = data.is_docker ? 'Docker' : '本地';
        document.getElementById('app-version').textContent = 'v' + (data.version || 'Unknown');  // 显示版本号
    } catch (error) {
        console.error('加载系统状态失败:', error);
    }
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatInterval(seconds) {
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}小时${mins}分钟` : `${hours}小时`;
}

function getStatusBadge(status) {
    const badges = {
        'IDLE': '<span class="status-badge status-idle"><i class="fas fa-circle mr-1"></i>空闲</span>',
        'QUEUED': '<span class="status-badge status-queued"><i class="fas fa-clock mr-1"></i>队列中</span>',
        'RUNNING': '<span class="status-badge status-running"><i class="fas fa-spinner fa-spin mr-1"></i>运行中</span>',
        'ERROR': '<span class="status-badge status-error"><i class="fas fa-exclamation-circle mr-1"></i>错误</span>'
    };
    return badges[status] || badges['IDLE'];
}

async function loadTasks() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000); // 5秒超时
        
        const response = await fetch('/api/tasks', {
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        const data = await response.json();
        const tasks = data.tasks || [];
        tasksCache = tasks;
        const running = tasks.filter(t => t.status === 'RUNNING').length;
        document.getElementById('stat-running').textContent = running;
        const currentData = JSON.stringify(tasks);
        if (currentData !== lastTasksData) {
            renderTasks(tasks);
            lastTasksData = currentData;
        } else {
            updateTaskStatus(tasks);
        }
    } catch (error) {
        console.error('加载任务失败:', error);
    }
}

function updateTaskStatus(tasks) {
    tasks.forEach(task => {
        const taskCard = document.querySelector(`[data-task-id="${task.id}"]`);
        if (taskCard) {
            const statusBadge = taskCard.querySelector('.status-badge-container');
            if (statusBadge) statusBadge.innerHTML = getStatusBadge(task.status);
        }
    });
}

function renderTasks(tasks) {
    const container = document.getElementById('tasks-container');
    if (tasks.length === 0) {
        container.innerHTML = '<div class="text-center py-12 text-gray-400"><i class="fas fa-inbox text-5xl mb-4"></i><p>暂无任务</p></div>';
        return;
    }
    container.innerHTML = tasks.map(task => {
        // 根据调度类型显示不同信息
        let scheduleInfo = '';
        if (task.schedule_type === 'CRON') {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-calendar-alt text-purple-500 mr-2"></i><code class="px-2 py-1 bg-gray-100 rounded text-xs font-mono">${task.cron_expression}</code></div>`;
        } else {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-clock text-yellow-500 mr-2"></i><span>间隔：${formatInterval(task.interval)}</span></div>`;
        }
        
        // 渲染进度条（仅当任务正在运行时）
        let progressBar = '';
        if (task.status === 'RUNNING' && task.progress) {
            const p = task.progress;
            progressBar = `
                <div class="mt-3 mb-2">
                    <div class="flex items-center justify-between text-xs mb-1">
                        <span class="text-gray-600">进度: ${p.done} / ${p.total} 文件</span>
                        <span class="text-blue-600 font-bold">${p.percent}%</span>
                    </div>
                    <div class="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div class="h-full bg-blue-500 transition-all" style="width: ${p.percent}%"></div>
                    </div>
                    <div class="flex items-center gap-3 text-xs text-gray-500 mt-1">
                        <span><i class="fas fa-check text-green-500 mr-1"></i>成功: ${p.success}</span>
                        <span><i class="fas fa-forward text-yellow-500 mr-1"></i>跳过: ${p.skipped}</span>
                        <span><i class="fas fa-times text-red-500 mr-1"></i>失败: ${p.failed}</span>
                    </div>
                </div>
            `;
        }
        
        // 渲染最终统计信息（仅当任务有执行结果时）
        let statsInfo = '';
        if (task.stats) {
            const s = task.stats;
            const filteredInfo = typeof s.skipped_filtered === 'number' && s.skipped_filtered > 0
                ? `<span><i class="fas fa-filter mr-1"></i>过滤: ${s.skipped_filtered}</span>`
                : '';
            statsInfo = `
                <div class="mt-2 p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs">
                    <div class="flex items-center gap-3 text-gray-600 dark:text-gray-400">
                        <span><i class="fas fa-file mr-1"></i>总数: ${s.total}</span>
                        <span><i class="fas fa-check text-green-500 mr-1"></i>成功: ${s.success}</span>
                        <span><i class="fas fa-forward text-yellow-500 mr-1"></i>跳过: ${s.skipped}</span>
                        <span><i class="fas fa-times text-red-500 mr-1"></i>失败: ${s.failed}</span>
                        ${filteredInfo}
                    </div>
                </div>
            `;
        }
        
        // 过滤规则概览
        let filterInfo = '';
        const filterParts = [];
        if (typeof task.size_min_bytes === 'number') {
            filterParts.push(`≥ ${Math.round(task.size_min_bytes / (1024 * 1024))} MB`);
        }
        if (typeof task.size_max_bytes === 'number') {
            filterParts.push(`≤ ${Math.round(task.size_max_bytes / (1024 * 1024))} MB`);
        }
        if (task.suffix_mode && task.suffix_mode !== 'NONE') {
            const list = Array.isArray(task.suffix_list) ? task.suffix_list.join(',') : '';
            if (task.suffix_mode === 'INCLUDE') {
                filterParts.push(`仅 [${list}]`);
            } else if (task.suffix_mode === 'EXCLUDE') {
                filterParts.push(`排除 [${list}]`);
            }
        }
        if (filterParts.length > 0) {
            filterInfo = `<div class="text-xs text-gray-500 mt-1"><i class="fas fa-filter mr-1"></i>过滤: ${filterParts.join('；')}</div>`;
        }
        
        // 删除源文件配置概览
        let deleteInfo = '';
        if (task.delete_source) {
            const baseLabel = (task.delete_time_base || 'SYNC_COMPLETE') === 'FILE_CREATE' ? '创建时间' : '同步完成时间';
            let delayLabel = '同步后立即删除';
            if (typeof task.delete_delay_days === 'number' && task.delete_delay_days > 0) {
                delayLabel = `${task.delete_delay_days} 天后删除`;
            }
            let parentLabel = '';
            if (task.delete_parent) {
                parentLabel = '，尝试删除文件目录';
                const levels = typeof task.delete_parent_levels === 'number' ? task.delete_parent_levels : 0;
                let levelLabel = '';
                if (levels === 0) {
                    levelLabel = '（仅删除文件）';
                } else if (levels === 1) {
                    levelLabel = '（删除文件所在目录）';
                } else if (levels === 2) {
                    levelLabel = '（删除文件所在目录及上一层）';
                } else if (levels > 2) {
                    levelLabel = `（最多向上 ${levels} 层）`;
                }
                const forceLabel = task.delete_parent_force ? '，可删除非空目录' : '';
                parentLabel += levelLabel + forceLabel;
            }
            deleteInfo = `<div class="text-xs text-red-500 mt-1"><i class="fas fa-trash-can mr-1"></i>${delayLabel}（基于${baseLabel}${parentLabel}）</div>`;
        }
        
        return `
        <div class="task-card" data-task-id="${task.id}">
            <div class="flex items-start justify-between mb-3">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-lg font-bold">${task.name}</h4>
                        <span class="status-badge-container">${getStatusBadge(task.status)}</span>
                        ${task.is_slow_storage ? '<span class="text-xs px-2 py-1 bg-orange-100 text-orange-600 rounded" title="网络云盘优化"><i class="fas fa-hdd mr-1"></i>云盘</span>' : ''}
                    </div>
                </div>
                <div class="flex items-center gap-2" title="${task.enabled ? '任务已启用' : '任务已禁用'}">
                    <span class="text-sm text-gray-600">${task.enabled ? '已启用' : '已禁用'}</span>
                    <label class="toggle-switch">
                        <input type="checkbox" ${task.enabled ? 'checked' : ''} onchange="toggleTaskEnabled('${task.id}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            <div class="mb-3">
                <div class="flex items-center text-sm text-gray-600">
                    <div class="flex items-center"><i class="fas fa-folder-open text-blue-500 mr-2"></i><span class="font-mono">${task.source_path}</span></div>
                    <span class="mx-1 text-gray-400">→</span>
                    <div class="flex items-center"><i class="fas fa-folder text-green-500 mr-2"></i><span class="font-mono">${task.target_path}</span></div>
                </div>
                ${filterInfo}
                ${deleteInfo}
            </div>
            <div class="flex items-center gap-4 text-sm text-gray-600 mb-3">
                ${scheduleInfo}
                ${task.last_run_time ? `<span class="text-xs text-gray-500"><i class="fas fa-history mr-1"></i>上次: ${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                ${task.next_run_time ? `<span class="text-xs text-blue-600"><i class="fas fa-clock mr-1"></i>下次: ${new Date(task.next_run_time).toLocaleString()}</span>` : ''}
            </div>
            <div class="flex gap-2 flex-wrap mt-3">
                <button onclick="triggerTask('${task.id}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}><i class="fas fa-play"></i>立即运行</button>
                <button onclick="openLogWindow('${task.id}', '${task.name.replace(/'/g, "''")} 日志')" class="btn btn-secondary text-sm"><i class="fas fa-terminal"></i>查看日志</button>
                <button onclick="showAdvancedTools('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-wrench"></i>高级工具</button>
                <button onclick="editTask('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-edit"></i>编辑</button>
                <button onclick="deleteTask('${task.id}', '${task.name.replace(/'/g, "''")}')" class="btn btn-secondary text-sm border-red-500 text-red-500"><i class="fas fa-trash"></i>删除</button>
            </div>
            ${progressBar}
            ${statsInfo}
        </div>
        `;
    }).join('');
}

async function loadQueue(updateTab = true) {
    try {
        const response = await fetch('/api/queue');
        const data = await response.json();
        const queue = data.queue || [];
        queueCache = queue;
        if (updateTab) renderQueueTab(queue);
    } catch (error) {
        console.error('加载队列失败:', error);
    }
}

function renderQueueTab(queue) {
    const container = document.getElementById('queue-container');
    if (queue.length === 0) {
        container.innerHTML = '<div class="text-center py-12 text-gray-400"><i class="fas fa-hourglass-half text-5xl mb-4"></i><p>队列为空</p></div>';
        return;
    }
    container.innerHTML = queue.map((task, index) => `
        <div class="task-card">
            <div class="flex items-center gap-4">
                <div class="h-10 w-10 rounded-full bg-yellow-100 flex items-center justify-center text-yellow-700 font-bold">${index + 1}</div>
                <div class="flex-1">
                    <h4 class="font-bold">${task.name}</h4>
                    <p class="text-sm text-gray-500">${task.source_path} → ${task.target_path}</p>
                </div>
                ${getStatusBadge(task.status)}
            </div>
        </div>
    `).join('');
}

function renderQueueModal(queue = []) {
    const modalCount = document.getElementById('queue-modal-count');
    const modalContainer = document.getElementById('queue-modal-container');
    modalCount.textContent = `${queue.length} 条`;
    if (queue.length === 0) {
        modalContainer.innerHTML = '<div class="text-gray-500 text-center py-6">队列为空</div>';
        return;
    }
    modalContainer.innerHTML = queue.map((task, index) => `
        <div class="task-card">
            <div class="flex items-center gap-4">
                <div class="h-10 w-10 rounded-full bg-yellow-100 flex items-center justify-center text-yellow-700 font-bold">${index + 1}</div>
                <div class="flex-1">
                    <h4 class="font-bold">${task.name}</h4>
                    <p class="text-sm text-gray-500">${task.source_path} → ${task.target_path}</p>
                </div>
                ${getStatusBadge(task.status)}
            </div>
        </div>
    `).join('');
}

// 加载日志逻辑已拆分到 app-logs.js

function showNotification(message, type = 'info') {
    const colors = { success: 'bg-green-500', error: 'bg-red-500', warning: 'bg-yellow-500', info: 'bg-blue-500' };
    const notification = document.createElement('div');
    notification.className = `fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 ${colors[type]} text-white px-8 py-4 rounded-xl shadow-2xl z-[9999] transition-all duration-300 opacity-0 transform scale-90`;
    notification.style.minWidth = '200px';
    notification.style.textAlign = 'center';
    notification.innerHTML = `
        <div class="flex flex-col items-center gap-2">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-times-circle' : 'fa-info-circle'} text-2xl"></i>
            <div class="font-bold">${message}</div>
        </div>
    `;
    document.body.appendChild(notification);
    
    // 动画进入
    setTimeout(() => {
        notification.classList.remove('opacity-0', 'scale-90');
        notification.classList.add('opacity-100', 'scale-100');
    }, 10);

    // 自动消失
    setTimeout(() => { 
        notification.classList.remove('opacity-100', 'scale-100');
        notification.classList.add('opacity-0', 'scale-90');
        setTimeout(() => notification.remove(), 300); 
    }, 3000);
}

function switchTaskTab(tab) {
    const basicBtn = document.getElementById('taskTabBasic');
    const advancedBtn = document.getElementById('taskTabAdvanced');
    const basicItems = document.querySelectorAll('.task-tab-basic');
    const advancedItems = document.querySelectorAll('.task-tab-advanced');

    if (!basicBtn || !advancedBtn) return;

    if (tab === 'advanced') {
        basicBtn.classList.remove('border-blue-500', 'text-blue-600');
        basicBtn.classList.add('border-transparent', 'text-gray-500');
        advancedBtn.classList.remove('border-transparent', 'text-gray-500');
        advancedBtn.classList.add('border-blue-500', 'text-blue-600');

        basicItems.forEach(el => el.classList.add('hidden'));
        advancedItems.forEach(el => el.classList.remove('hidden'));
    } else {
        advancedBtn.classList.remove('border-blue-500', 'text-blue-600');
        advancedBtn.classList.add('border-transparent', 'text-gray-500');
        basicBtn.classList.remove('border-transparent', 'text-gray-500');
        basicBtn.classList.add('border-blue-500', 'text-blue-600');

        basicItems.forEach(el => el.classList.remove('hidden'));
        advancedItems.forEach(el => el.classList.add('hidden'));
    }
}

function showAddTaskModal() {
    // 检查是否有草稿
    const draft = localStorage.getItem('task-draft');
    if (draft && !currentEditingTaskId) {
        if (confirm('检测到未保存的草稿，是否加载？')) {
            loadDraft();
            document.getElementById('taskModal').classList.add('show');
            return;
        } else {
            localStorage.removeItem('task-draft');
        }
    }
    
    currentEditingTaskId = null;
    taskFormDirty = false;
    document.getElementById('modalTitle').textContent = '添加任务';
    document.getElementById('taskForm').reset();
    document.getElementById('taskId').value = '';
    
    // 默认切换到基础配置标签页
    switchTaskTab('basic');
    
    // 重置过滤规则
    const sizeMinInput = document.getElementById('sizeMinMb');
    const sizeMaxInput = document.getElementById('sizeMaxMb');
    const suffixModeSelect = document.getElementById('suffixMode');
    const suffixListInput = document.getElementById('suffixList');
    const suffixPresetPanel = document.getElementById('suffixPresetPanel');
    if (sizeMinInput) sizeMinInput.value = '';
    if (sizeMaxInput) sizeMaxInput.value = '';
    if (suffixModeSelect) suffixModeSelect.value = 'NONE';
    if (suffixListInput) suffixListInput.value = '';
    if (suffixPresetPanel) suffixPresetPanel.style.display = 'none';
    
    // 重置删除源文件设置
    const deleteSourceCheckbox = document.getElementById('deleteSource');
    const deleteDelayInput = document.getElementById('deleteDelayDays');
    const deleteTimeBaseSelect = document.getElementById('deleteTimeBase');
    const deleteParentCheckbox = document.getElementById('deleteParentDir');
    const deleteParentLevelsSelect = document.getElementById('deleteParentLevels');
    const deleteParentForceCheckbox = document.getElementById('deleteParentForce');
    if (deleteSourceCheckbox) deleteSourceCheckbox.checked = false;
    if (deleteDelayInput) deleteDelayInput.value = '';
    if (deleteTimeBaseSelect) deleteTimeBaseSelect.value = 'SYNC_COMPLETE';
    if (deleteParentCheckbox) deleteParentCheckbox.checked = false;
    if (deleteParentLevelsSelect) deleteParentLevelsSelect.value = '1';
    if (deleteParentForceCheckbox) deleteParentForceCheckbox.checked = false;
            
    // 重置子规则按钮状态（默认启用「文件不存在」规则）
    ['ruleNotExists', 'ruleSizeDiff', 'ruleMtimeNewer'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
            // 默认启用「文件不存在」规则
            if (id === 'ruleNotExists') {
                btn.dataset.active = 'true';
                btn.style.borderColor = '#3b82f6';
                btn.style.background = '#eff6ff';
                btn.style.color = '#1e40af';
            } else {
                btn.dataset.active = 'false';
                btn.style.borderColor = '#e5e9f2';
                btn.style.background = 'transparent';
                btn.style.color = '#6b7280';
            }
        }
    });
    
    document.getElementById('taskModal').classList.add('show');
    
    // 初始化目录自动提示
    initDirectoryAutocomplete();
}

function loadDraft() {
    try {
        const draft = JSON.parse(localStorage.getItem('task-draft'));
        if (draft) {
            document.getElementById('taskName').value = draft.name || '';
            document.getElementById('taskSource').value = draft.source_path || '';
            document.getElementById('taskTarget').value = draft.target_path || '';
            document.getElementById('cronExpression').value = draft.cron_expression || '';
            document.getElementById('taskThreadCount').value = draft.thread_count || 1;
            
            // 恢复子规则状态
            const rules = {
                ruleNotExists: draft.rule_not_exists || false,
                ruleSizeDiff: draft.rule_size_diff || false,
                ruleMtimeNewer: draft.rule_mtime_newer || false
            };
            
            Object.keys(rules).forEach(id => {
                const btn = document.getElementById(id);
                if (btn && rules[id]) {
                    btn.dataset.active = 'true';
                    btn.style.borderColor = '#3b82f6';
                    btn.style.background = '#eff6ff';
                    btn.style.color = '#1e40af';
                }
            });
        }
    } catch (e) {
        console.error('加载草稿失败:', e);
    }
}

function saveDraft() {
    if (!taskFormDirty) return;
    const draft = {
        name: document.getElementById('taskName').value,
        source_path: document.getElementById('taskSource').value,
        target_path: document.getElementById('taskTarget').value,
        cron_expression: document.getElementById('cronExpression').value,
        thread_count: parseInt(document.getElementById('taskThreadCount').value) || 1,
        rule_not_exists: document.getElementById('ruleNotExists').dataset.active === 'true',
        rule_size_diff: document.getElementById('ruleSizeDiff').dataset.active === 'true',
        rule_mtime_newer: document.getElementById('ruleMtimeNewer').dataset.active === 'true'
    };
    localStorage.setItem('task-draft', JSON.stringify(draft));
}

function closeTaskModal() {
    // 默认保存草稿，不再提示
    if (taskFormDirty && !currentEditingTaskId) {
        saveDraft();
    }
    
    document.getElementById('taskModal').classList.remove('show');
    currentEditingTaskId = null;
    taskFormDirty = false;
    
    // 移除目录提示
    removeDirectoryAutocomplete();
}

// 切换子规则按钮状态
function toggleRule(button, ruleKey) {
    const isActive = button.dataset.active === 'true';
    
    if (isActive) {
        // 关闭
        button.dataset.active = 'false';
        button.style.borderColor = '#e5e9f2';
        button.style.background = 'transparent';
        button.style.color = '#6b7280';
    } else {
        // 启用
        button.dataset.active = 'true';
        button.style.borderColor = '#3b82f6';
        button.style.background = '#eff6ff';
        button.style.color = '#1e40af';
    }
    
    taskFormDirty = true;
}



// 加载一言（自动调用）
async function loadHitokoto() {
    const contentEl = document.getElementById('hitokoto-content');
    
    if (!contentEl) return;
    
    try {
        const response = await fetch('https://v1.hitokoto.cn/');
        const data = await response.json();
        
        // 显示一言内容
        const text = data.hitokoto || '今天也要加油哦！';
        const from = data.from ? ` —— ${data.from}` : '';
        contentEl.textContent = `${text}${from}`;
        
    } catch (error) {
        console.error('加载一言失败:', error);
        contentEl.textContent = '保持热爱，奔赴山海';
    }
}

// 页面加载时自动获取一言
window.addEventListener('DOMContentLoaded', () => {
    loadHitokoto();
    // 每30分钟更新一次一言
    setInterval(loadHitokoto, 30 * 60 * 1000);
});

async function editTask(taskId) {
    try {
        const response = await fetch('/api/tasks');
        const data = await response.json();
        const task = data.tasks.find(t => t.id === taskId);
        if (!task) { showNotification('任务不存在', 'error'); return; }
        currentEditingTaskId = taskId;
        document.getElementById('modalTitle').textContent = '编辑任务';
        document.getElementById('taskId').value = taskId;
        document.getElementById('taskName').value = task.name;
        document.getElementById('taskSource').value = task.source_path;
        document.getElementById('taskTarget').value = task.target_path;
        
        // 设置子规则按钮状态
        const rules = {
            ruleNotExists: task.rule_not_exists || false,
            ruleSizeDiff: task.rule_size_diff || false,
            ruleMtimeNewer: task.rule_mtime_newer || false
        };
        
        Object.keys(rules).forEach(id => {
            const btn = document.getElementById(id);
            if (btn) {
                if (rules[id]) {
                    btn.dataset.active = 'true';
                    btn.style.borderColor = '#3b82f6';
                    btn.style.background = '#eff6ff';
                    btn.style.color = '#1e40af';
                } else {
                    btn.dataset.active = 'false';
                    btn.style.borderColor = '#e5e9f2';
                    btn.style.background = 'transparent';
                    btn.style.color = '#6b7280';
                }
            }
        });
        
        // 线程数
        document.getElementById('taskThreadCount').value = task.thread_count || 1;
        
        // 慢速存储选项
        const slowStorageCheckbox = document.getElementById('isSlowStorage');
        if (slowStorageCheckbox) {
            slowStorageCheckbox.checked = task.is_slow_storage || false;
        }
        
        // 填充过滤规则
        const sizeMinInput = document.getElementById('sizeMinMb');
        const sizeMaxInput = document.getElementById('sizeMaxMb');
        const suffixModeSelect = document.getElementById('suffixMode');
        const suffixListInput = document.getElementById('suffixList');
        if (sizeMinInput) {
            sizeMinInput.value = typeof task.size_min_bytes === 'number' ? Math.round(task.size_min_bytes / (1024 * 1024)) : '';
        }
        if (sizeMaxInput) {
            sizeMaxInput.value = typeof task.size_max_bytes === 'number' ? Math.round(task.size_max_bytes / (1024 * 1024)) : '';
        }
        if (suffixModeSelect) {
            suffixModeSelect.value = (task.suffix_mode || 'NONE').toUpperCase();
        }
        if (suffixListInput) {
            if (Array.isArray(task.suffix_list)) {
                suffixListInput.value = task.suffix_list.join(',');
            } else {
                suffixListInput.value = '';
            }
        }
        
        // 删除源文件配置
        const deleteSourceCheckbox = document.getElementById('deleteSource');
        const deleteDelayInput = document.getElementById('deleteDelayDays');
        const deleteTimeBaseSelect = document.getElementById('deleteTimeBase');
        const deleteParentCheckbox = document.getElementById('deleteParentDir');
        const deleteParentLevelsSelect = document.getElementById('deleteParentLevels');
        const deleteParentForceCheckbox = document.getElementById('deleteParentForce');
        if (deleteSourceCheckbox) {
            deleteSourceCheckbox.checked = !!task.delete_source;
        }
        if (deleteDelayInput) {
            deleteDelayInput.value = typeof task.delete_delay_days === 'number' ? task.delete_delay_days : '';
        }
        if (deleteTimeBaseSelect) {
            deleteTimeBaseSelect.value = (task.delete_time_base || 'SYNC_COMPLETE').toUpperCase();
        }
        if (deleteParentCheckbox) {
            deleteParentCheckbox.checked = !!task.delete_parent;
        }
        if (deleteParentLevelsSelect) {
            let levels = typeof task.delete_parent_levels === 'number' ? task.delete_parent_levels : 1;
            if (!levels || levels < 1) {
                levels = 1;
            }
            deleteParentLevelsSelect.value = String(levels);
        }
        if (deleteParentForceCheckbox) {
            deleteParentForceCheckbox.checked = !!task.delete_parent_force;
        }
                        
        // 填充 Cron 表达式
        document.getElementById('cronExpression').value = task.cron_expression || '';
        validateCron();
        
        // 编辑时默认展示基础配置标签页
        switchTaskTab('basic');
        
        document.getElementById('taskModal').classList.add('show');
        initDirectoryAutocomplete();
    } catch (error) {
        console.error('加载任务失败:', error);
        showNotification('加载任务失败', 'error');
    }
}

document.getElementById('taskForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const taskData = {
        name: document.getElementById('taskName').value,
        source_path: document.getElementById('taskSource').value,
        target_path: document.getElementById('taskTarget').value,
        schedule_type: 'CRON',  // 只支持 Cron 模式
        cron_expression: document.getElementById('cronExpression').value.trim(),
        thread_count: parseInt(document.getElementById('taskThreadCount').value) || 1,
        rule_not_exists: document.getElementById('ruleNotExists').dataset.active === 'true',
        rule_size_diff: document.getElementById('ruleSizeDiff').dataset.active === 'true',
        rule_mtime_newer: document.getElementById('ruleMtimeNewer').dataset.active === 'true',
        is_slow_storage: document.getElementById('isSlowStorage') ? document.getElementById('isSlowStorage').checked : false,
        enabled: true  // 默认启用，后续可通过开关控制
    };
    
    // 组装过滤规则
    const sizeMinInput = document.getElementById('sizeMinMb');
    const sizeMaxInput = document.getElementById('sizeMaxMb');
    const suffixModeSelect = document.getElementById('suffixMode');
    const suffixListInput = document.getElementById('suffixList');
    if (sizeMinInput && sizeMinInput.value !== '') {
        const v = parseFloat(sizeMinInput.value);
        if (!Number.isNaN(v) && v >= 0) {
            taskData.size_min_bytes = Math.round(v * 1024 * 1024);
        }
    }
    if (sizeMaxInput && sizeMaxInput.value !== '') {
        const v = parseFloat(sizeMaxInput.value);
        if (!Number.isNaN(v) && v >= 0) {
            taskData.size_max_bytes = Math.round(v * 1024 * 1024);
        }
    }
    if (suffixModeSelect) {
        const mode = suffixModeSelect.value || 'NONE';
        // 始终设置 suffix_mode，包括 NONE 的情况
        taskData.suffix_mode = mode;
        
        if (mode !== 'NONE') {
            if (suffixListInput && suffixListInput.value.trim() !== '') {
                taskData.suffix_list = suffixListInput.value
                    .split(',')
                    .map(s => s.trim())
                    .filter(s => s.length > 0)
                    .map(s => s.replace(/^\./, ''));
            } else {
                taskData.suffix_list = [];
            }
        } else {
            // mode === 'NONE' 时，显式发送空列表以清除旧的过滤规则
            taskData.suffix_list = [];
        }
    }
    
    // 删除源文件配置
    const deleteSourceCheckbox = document.getElementById('deleteSource');
    const deleteDelayInput = document.getElementById('deleteDelayDays');
    const deleteTimeBaseSelect = document.getElementById('deleteTimeBase');
    const deleteParentCheckbox = document.getElementById('deleteParentDir');
    const deleteParentLevelsSelect = document.getElementById('deleteParentLevels');
    const deleteParentForceCheckbox = document.getElementById('deleteParentForce');
    if (deleteSourceCheckbox && deleteSourceCheckbox.checked) {
        taskData.delete_source = true;
        if (deleteDelayInput && deleteDelayInput.value !== '') {
            const dv = parseInt(deleteDelayInput.value, 10);
            if (!Number.isNaN(dv)) {
                taskData.delete_delay_days = dv;
            }
        }
        if (deleteTimeBaseSelect && deleteTimeBaseSelect.value) {
            taskData.delete_time_base = deleteTimeBaseSelect.value;
        }
        if (deleteParentCheckbox && deleteParentCheckbox.checked) {
            taskData.delete_parent = true;
            if (deleteParentLevelsSelect && deleteParentLevelsSelect.value !== '') {
                const lv = parseInt(deleteParentLevelsSelect.value, 10);
                if (!Number.isNaN(lv)) {
                    taskData.delete_parent_levels = lv;
                }
            }
            if (deleteParentForceCheckbox) {
                taskData.delete_parent_force = !!deleteParentForceCheckbox.checked;
            }
        }
    } else {
        taskData.delete_source = false;
    }
        
    if (!taskData.cron_expression) {
        showNotification('Cron 表达式不能为空', 'error');
        return;
    }
    
    try {
        let response;
        if (currentEditingTaskId) {
            response = await fetch(`/api/tasks/${currentEditingTaskId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(taskData) });
        } else {
            response = await fetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(taskData) });
        }
        const result = await response.json();
        if (result.success) {
            showNotification(currentEditingTaskId ? '任务已更新' : '任务已添加', 'success');
            // 清除草稿
            localStorage.removeItem('task-draft');
            taskFormDirty = false;
            closeTaskModal();
            loadTasks();
        } else {
            showNotification(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存任务失败:', error);
        showNotification('保存任务失败', 'error');
    }
});

// 监听表单变化
function initFormChangeListener() {
    const inputs = ['taskName', 'taskSource', 'taskTarget', 'cronExpression', 'taskThreadCount', 'sizeMinMb', 'sizeMaxMb', 'suffixList', 'deleteDelayDays'];
    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', () => { taskFormDirty = true; });
            el.addEventListener('change', () => { taskFormDirty = true; });
        }
    });
    const checkboxes = ['deleteSource', 'deleteParentDir', 'isSlowStorage'];
    checkboxes.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => { taskFormDirty = true; });
        }
    });

    const suffixListInput = document.getElementById('suffixList');
    const suffixModeSelect = document.getElementById('suffixMode');
    const suffixPresetPanel = document.getElementById('suffixPresetPanel');
    
    // 监听 suffixMode 变化，当切换到 NONE 时清空输入框
    if (suffixModeSelect && suffixListInput) {
        suffixModeSelect.addEventListener('change', () => {
            if (suffixModeSelect.value === 'NONE') {
                suffixListInput.value = '';
                taskFormDirty = true;
            }
        });
    }
    
    if (suffixListInput && suffixPresetPanel) {
        // 输入框获得焦点时显示面板
        suffixListInput.addEventListener('focus', () => {
            suffixPresetPanel.style.display = 'block';
        });
        
        // 点击预设按钮时填充后缀
        const presetButtons = suffixPresetPanel.querySelectorAll('button[data-suffixes]');
        presetButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                const suffixes = button.getAttribute('data-suffixes');
                if (suffixes) {
                    // 直接替换输入框内容，不合并
                    suffixListInput.value = suffixes;
                    // 触发 input 事件标记表单已修改
                    suffixListInput.dispatchEvent(new Event('input'));
                    // 隐藏面板
                    suffixPresetPanel.style.display = 'none';
                }
            });
        });
        
        // 点击其他地方时隐藏面板
        document.addEventListener('click', (e) => {
            if (!suffixListInput.contains(e.target) && !suffixPresetPanel.contains(e.target)) {
                suffixPresetPanel.style.display = 'none';
            }
        });
    }
    ['deleteSource', 'deleteTimeBase', 'deleteParentDir'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => { taskFormDirty = true; });
        }
    });
}

// 目录自动提示功能已拆分到 app-directory.js

async function deleteTask(taskId, taskName) {
    if (!confirm(`确定要删除任务"${taskName}"吗？`)) return;
    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        const result = await response.json();
        if (result.success) {
            showNotification('任务已删除', 'success');
            loadTasks();
        } else {
            showNotification(result.error || '删除失败', 'error');
        }
    } catch (error) {
        console.error('删除任务失败:', error);
        showNotification('删除任务失败', 'error');
    }
}

async function toggleTaskEnabled(taskId, enabled) {
    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        const result = await response.json();
        if (result.success) {
            showNotification(enabled ? '任务已启用' : '任务已禁用', 'success');
            loadTasks();
        } else {
            showNotification(result.error || '操作失败', 'error');
            // 恢复原来的状态
            loadTasks();
        }
    } catch (error) {
        console.error('切换任务状态失败:', error);
        showNotification('操作失败', 'error');
        loadTasks();
    }
}

async function triggerTask(taskId) {
    try {
        const response = await fetch(`/api/tasks/${taskId}/trigger`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            showNotification('任务已触发', 'success');
            loadTasks();
        } else {
            showNotification(result.error || '触发失败', 'error');
        }
    } catch (error) {
        console.error('触发任务失败:', error);
        showNotification('触发任务失败', 'error');
    }
}

async function startScheduler() { showNotification('调度器默认常驻运行，无需手动启动', 'info'); }
async function stopScheduler() { showNotification('调度器默认开启，不提供停用入口', 'info'); }

function openRunningModal() {
    const running = (tasksCache || []).filter(t => t.status === 'RUNNING');
    const countEl = document.getElementById('running-count');
    const container = document.getElementById('running-container');
    if (countEl) countEl.textContent = `${running.length} 条`;
    if (container) {
        if (running.length === 0) {
            container.innerHTML = '<div class="text-gray-500 text-center py-6">暂无运行中的任务</div>';
        } else {
            container.innerHTML = running.map(task => `
                <div class="task-card">
                    <div class="flex items-center justify-between mb-2"><div class="font-bold">${task.name}</div>${getStatusBadge(task.status)}</div>
                    <p class="text-sm text-gray-500">${task.source_path} → ${task.target_path}</p>
                    ${task.last_run_time ? `<p class="text-xs text-gray-400 mt-1"><i class="fas fa-clock mr-1"></i>${new Date(task.last_run_time).toLocaleString()}</p>` : ''}
                </div>
            `).join('');
        }
    }
    document.getElementById('runningModal').classList.add('show');
}

async function openQueueModal() {
    await loadQueue(false);
    renderQueueModal(queueCache);
    document.getElementById('queueModal').classList.add('show');
}

function closeOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('show');
}

// ========== Cron 相关功能 ==========

// Cron 验证
let cronValidationTimeout = null;
async function validateCron() {
    clearTimeout(cronValidationTimeout);
    const expression = document.getElementById('cronExpression').value.trim();
    const validationDiv = document.getElementById('cronValidation');
    
    if (!expression) {
        validationDiv.innerHTML = '';
        return;
    }
    
    cronValidationTimeout = setTimeout(async () => {
        try {
            const response = await fetch('/api/cron/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ expression })
            });
            const data = await response.json();
            
            if (data.valid) {
                validationDiv.innerHTML = `<span class="text-green-600">✓ ${data.description}</span>`;
            } else {
                validationDiv.innerHTML = `<span class="text-red-600">✗ ${data.error}</span>`;
            }
        } catch (error) {
            validationDiv.innerHTML = `<span class="text-red-600">✗ 验证失败</span>`;
        }
    }, 500);
}

// 显示 Cron 预设
let cronPresetsCache = null;
async function showCronPresets() {
    const presetList = document.getElementById('cronPresetList');
    const container = presetList.querySelector('div');
    
    if (presetList.style.display === 'block') {
        presetList.style.display = 'none';
        return;
    }
    
    if (!cronPresetsCache) {
        try {
            const response = await fetch('/api/cron/presets');
            const data = await response.json();
            cronPresetsCache = data.presets || [];
        } catch (error) {
            showNotification('加载预设失败', 'error');
            return;
        }
    }
    
    container.innerHTML = cronPresetsCache.map(preset => `
        <div class="px-3 py-2 bg-white hover:bg-blue-50 rounded cursor-pointer text-sm transition-colors" onclick="selectCronPreset('${preset.expression}')">
            <div class="flex items-center justify-between">
                <span class="font-semibold">${preset.name}</span>
                <code class="text-xs bg-gray-100 px-2 py-1 rounded">${preset.expression}</code>
            </div>
            <div class="text-xs text-gray-500 mt-1">${preset.description}</div>
        </div>
    `).join('');
    
    presetList.style.display = 'block';
}

function selectCronPreset(expression) {
    document.getElementById('cronExpression').value = expression;
    document.getElementById('cronPresetList').style.display = 'none';
    validateCron();
    taskFormDirty = true;
}

// 随机生成 Cron
async function generateRandomCron() {
    const patterns = ['hourly', 'daily', 'night'];
    const randomPattern = patterns[Math.floor(Math.random() * patterns.length)];
    
    try {
        const response = await fetch(`/api/cron/random?pattern=${randomPattern}`);
        const data = await response.json();
        
        document.getElementById('cronExpression').value = data.expression;
        validateCron();
        showNotification(`随机生成: ${data.description}`, 'success');
        taskFormDirty = true;
    } catch (error) {
        showNotification('生成失败', 'error');
    }
}

// 高级工具功能
function showAdvancedTools(taskId) {
    const task = tasksCache.find(t => t.id === taskId);
    if (!task) {
        showNotification('任务不存在', 'error');
        return;
    }
    
    // 创建高级工具弹窗
    const modal = document.createElement('div');
    modal.className = 'overlay-modal show';
    modal.id = 'advancedToolsModal';
    modal.innerHTML = `
        <div class="modal-card card" onclick="event.stopPropagation()">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2">
                    <i class="fas fa-wrench text-blue-500 text-xl"></i>
                    <h3 class="text-xl font-bold">高级工具</h3>
                </div>
                <button class="btn btn-secondary text-sm" onclick="closeAdvancedTools()"><i class="fas fa-times"></i>关闭</button>
            </div>
            <div class="mb-4">
                <p class="text-sm text-gray-600 mb-2">任务: <span class="font-bold">${task.name}</span></p>
                <p class="text-xs text-gray-500">${task.source_path} → ${task.target_path}</p>
            </div>
            <div class="space-y-3">
                <div class="border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors">
                    <div class="flex items-start gap-3">
                        <i class="fas fa-sync-alt text-orange-500 text-2xl mt-1"></i>
                        <div class="flex-1">
                            <h4 class="font-bold text-lg mb-1">全量覆盖更新</h4>
                            <p class="text-sm text-gray-600 mb-3">强制覆盖所有已存在的同名文件，不删除目标多余文件。此操作不会修改任务的持久配置。</p>
                            <button onclick="triggerFullOverwrite('${taskId}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                                <i class="fas fa-bolt"></i>立即执行
                            </button>
                        </div>
                    </div>
                </div>
                
                <div class="border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors">
                    <div class="flex items-start gap-3">
                        <i class="fas fa-database text-blue-500 text-2xl mt-1"></i>
                        <div class="flex-1">
                            <h4 class="font-bold text-lg mb-1">重构历史缓存</h4>
                            <p class="text-sm text-gray-600 mb-3">扫描目标端已存在的文件并回填缓存树。适用于老用户升级或手动维护目标端后的状态同步，可避免重复同步。</p>
                            <button onclick="triggerReconstruct('${taskId}')" class="btn btn-secondary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                                <i class="fas fa-hammer"></i>开始重构
                            </button>
                        </div>
                    </div>
                </div>

                <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                    <div class="flex items-start gap-2">
                        <i class="fas fa-exclamation-triangle text-yellow-600 mt-0.5"></i>
                        <p class="text-xs text-yellow-700">
                            <strong>注意：</strong>全量覆盖会替换所有已存在文件，请确保源文件完整且正确。此操作仅执行一次，不影响定时任务的同步策略。
                        </p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeAdvancedTools();
    });
}

function closeAdvancedTools() {
    const modal = document.getElementById('advancedToolsModal');
    if (modal) {
        modal.remove();
    }
}

async function triggerFullOverwrite(taskId) {
    const task = tasksCache.find(t => t.id === taskId);
    if (!task) {
        showNotification('任务不存在', 'error');
        return;
    }
    
    // 二次确认
    if (!confirm(`确认对任务「${task.name}」执行全量覆盖吗？\n\n此操作将强制覆盖所有已存在的同名文件！`)) {
        return;
    }
    
    try {
        // 发送全量覆盖请求
        const response = await fetch(`/api/tasks/${taskId}/full-overwrite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('全量覆盖任务已加入队列', 'success');
            closeAdvancedTools();
            // 打开日志窗口
            setTimeout(() => {
                openLogWindow(taskId, task.name + ' 日志');
            }, 500);
        } else {
            showNotification(result.error || '执行失败', 'error');
        }
    } catch (error) {
        console.error('全量覆盖失败:', error);
        showNotification('执行失败', 'error');
    }
}

async function triggerReconstruct(taskId) {
    const task = tasksCache.find(t => t.id === taskId);
    if (!task) {
        showNotification('任务不存在', 'error');
        return;
    }
    
    // 二次确认
    if (!confirm(`确认重构任务「${task.name}」的缓存吗？\n\n系统将扫描目标目录并尝试恢复同步状态。这对于避免重复同步非常有用。`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/tasks/${taskId}/reconstruct`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('缓存重构任务已启动', 'success');
            closeAdvancedTools();
            // 打开日志窗口
            setTimeout(() => {
                openLogWindow(taskId, task.name + ' 日志');
            }, 500);
        } else {
            showNotification(result.error || '执行失败', 'error');
        }
    } catch (error) {
        console.error('缓存重构失败:', error);
        showNotification('执行失败', 'error');
    }
}

// ========== 历史记录相关逻辑 ==========

async function openHistoryModal() {
    // 渲染任务过滤器
    const filter = document.getElementById('history-task-filter');
    if (filter) {
        try {
            // 并行获取两种任务
            const [syncRes, strmRes] = await Promise.all([
                fetch('/api/tasks'),
                fetch('/api/strm/tasks')
            ]);
            const syncData = await syncRes.json();
            const strmData = await strmRes.json();
            
            const syncTasks = syncData.tasks || [];
            const strmTasks = strmData.tasks || [];
            
            filter.innerHTML = '<option value="">全部任务</option>';
            
            if (syncTasks.length > 0) {
                const group = document.createElement('optgroup');
                group.label = '同步任务';
                syncTasks.forEach(task => {
                    const option = document.createElement('option');
                    option.value = task.id;
                    option.textContent = task.name;
                    group.appendChild(option);
                });
                filter.appendChild(group);
            }
            
            if (strmTasks.length > 0) {
                const group = document.createElement('optgroup');
                group.label = 'STRM 任务';
                strmTasks.forEach(task => {
                    const option = document.createElement('option');
                    option.value = task.id;
                    option.textContent = task.name;
                    group.appendChild(option);
                });
                filter.appendChild(group);
            }
        } catch (error) {
            console.error('加载任务过滤器失败:', error);
        }
    }

    loadHistory();
    document.getElementById('historyModal').classList.add('show');
}

async function loadHistory() {
    const taskId = document.getElementById('history-task-filter').value;
    const container = document.getElementById('history-container');
    const emptyEl = document.getElementById('history-empty');
    
    if (!container || !emptyEl) return;

    container.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>正在加载...</td></tr>';
    emptyEl.classList.add('hidden');

    try {
        const url = taskId ? `/api/history?task_id=${taskId}` : '/api/history';
        const response = await fetch(url);
        const data = await response.json();
        const history = data.history || [];

        if (history.length === 0) {
            container.innerHTML = '';
            emptyEl.classList.remove('hidden');
            return;
        }

        container.innerHTML = history.map(item => {
            const time = new Date(item.timestamp).toLocaleString();
            let statusClass = 'bg-gray-100 text-gray-600';
            let statusText = item.status;
            
            if (item.status === 'SYNCED') { statusClass = 'bg-green-100 text-green-700'; statusText = '同步成功'; }
            else if (item.status === 'SKIPPED') { statusClass = 'bg-blue-100 text-blue-700'; statusText = '跳过'; }
            else if (item.status === 'DELETED') { statusClass = 'bg-red-100 text-red-700'; statusText = '已删除'; }
            else if (item.status === 'FAILED') { statusClass = 'bg-orange-100 text-orange-700'; statusText = '失败'; }
            else if (item.status === 'PENDING') { statusClass = 'bg-gray-100 text-gray-500'; statusText = '等待中'; }
            
            const countBadge = item.count > 1 ? `<span class="ml-1 px-1.5 py-0.5 bg-gray-200 rounded-full text-[10px]" title="重复次数">${item.count}</span>` : '';
            
            return `
                <tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <td class="px-4 py-3 whitespace-nowrap text-gray-500 font-mono text-xs">${time}</td>
                    <td class="px-4 py-3">
                        <span class="px-2 py-1 rounded-md font-bold text-xs ${statusClass}">${statusText}${countBadge}</span>
                    </td>
                    <td class="px-4 py-3 truncate max-w-xs" title="${item.path}">${item.path}</td>
                    <td class="px-4 py-3 text-xs text-gray-400">${item.details || '-'}</td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('加载历史记录失败:', error);
        container.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-red-500">加载失败</td></tr>';
    }
}

async function clearHistory() {
    const taskId = document.getElementById('history-task-filter').value;
    const taskName = taskId ? document.querySelector(`#history-task-filter option[value="${taskId}"]`).textContent : '全部';
    
    if (!confirm(`确定要清空「${taskName}」的历史记录吗？`)) return;

    try {
        const url = taskId ? `/api/history/clear?task_id=${taskId}` : '/api/history/clear';
        const response = await fetch(url, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            showNotification('历史记录已清空', 'success');
            loadHistory();
        } else {
            showNotification(result.error || '清空失败', 'error');
        }
    } catch (error) {
        console.error('清空历史记录失败:', error);
        showNotification('操作失败', 'error');
    }
}

(function init() {
    const savedTheme = localStorage.getItem('cg-theme') || 'light';
    applyTheme(savedTheme);
    document.addEventListener('DOMContentLoaded', () => {
        loadSystemStatus();
        loadTasks();
        loadQueue(false);
        
        // 初始化表单监听
        initFormChangeListener();
        // 初始化密码输入监听
        initPasswordInputListener();
        
        setInterval(() => {
            loadSystemStatus();
            loadTasks();
            if (logWindows.size > 0) {
                logWindows.forEach((_, logId) => loadLogsFor(logId));
            }
            if (currentView === 'queue') loadQueue();
        }, 3000);
        
        // 修改任务模态框逻辑：禁用点击外部关闭，只支持 X 按钮和 ESC 键
        const taskModal = document.getElementById('taskModal');
        if (taskModal) {
            // 监听 ESC 键
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && taskModal.classList.contains('show')) {
                    closeTaskModal();
                }
            });
        }
        
        // 其他模态框保持原有逻辑
        ['runningModal', 'queueModal', 'historyModal'].forEach(id => {
            const modal = document.getElementById(id);
            if (modal) modal.addEventListener('click', (e) => { if (e.target.id === id) modal.classList.remove('show'); });
        });
    });
})();

// ========== OpenList 配置管理 ==========

/**
 * 加载 OpenList 配置
 */
async function loadOpenListConfig() {
    try {
        const response = await fetch('/api/settings/openlist');
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.config) {
                document.getElementById('openlist-url').value = data.config.url || '';
                document.getElementById('openlist-username').value = data.config.username || '';
                document.getElementById('openlist-password').value = ''; // 不回显密码
                // 添加密码状态提示
                updatePasswordStatusHint();
                document.getElementById('openlist-token').value = data.config.token || '';
                document.getElementById('openlist-public-url').value = data.config.public_url || '';
            }
        }
    } catch (error) {
        console.error('加载 OpenList 配置失败:', error);
    }
}

/**
 * 保存所有设置
 */
async function saveAllSettings() {
    // 禁用保存按钮防止重复点击
    const btn = document.querySelector('#view-system-settings .btn-primary');
    if (btn) {
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>正在保存...';
        
        try {
            // 获取所有配置
            const openlistConfig = {
                url: document.getElementById('openlist-url').value.trim(),
                username: document.getElementById('openlist-username').value.trim(),
                password: document.getElementById('openlist-password').value.trim(),
                token: document.getElementById('openlist-token').value.trim(),
                public_url: document.getElementById('openlist-public-url').value.trim()
            };
            
            const extensions = {
                subtitle: document.getElementById('subtitle-extensions').value.trim(),
                image: document.getElementById('image-extensions').value.trim(),
                nfo: document.getElementById('nfo-extensions').value.trim(),
                other: document.getElementById('other-extensions').value.trim()
            };
            
            const systemConfig = {
                sync_retry_count: parseInt(document.getElementById('system-retry-count').value)
            };
            
            // 验证
            if (!openlistConfig.url) {
                showNotification('请填写 OpenList 服务器地址', 'error');
                btn.disabled = false;
                btn.innerHTML = originalHtml;
                return;
            }
            
            // 并行发送请求
            const results = await Promise.all([
                fetch('/api/settings/openlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(openlistConfig)
                }),
                fetch('/api/settings/extensions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(extensions)
                }),
                fetch('/api/settings/system', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(systemConfig)
                })
            ]);
            
            const data = await Promise.all(results.map(r => r.json()));
            
            if (data.every(d => d.success)) {
                showNotification('所有设置已保存', 'success');
                // 清空密码框并更新状态提示
                document.getElementById('openlist-password').value = '';
                updatePasswordStatusHint();
            } else {
                const errors = data.filter(d => !d.success).map(d => d.error).join('; ');
                showNotification('部分设置保存失败: ' + errors, 'error');
            }
        } catch (error) {
            console.error('保存设置失败:', error);
            showNotification('保存失败: ' + error.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}

/**
 * 保存 OpenList 配置
 */
async function saveOpenListConfig() {
    const url = document.getElementById('openlist-url').value.trim();
    const username = document.getElementById('openlist-username').value.trim();
    const password = document.getElementById('openlist-password').value.trim();
    const token = document.getElementById('openlist-token').value.trim();
    const publicUrl = document.getElementById('openlist-public-url').value.trim();
    
    if (!url) {
        showNotification('请填写服务器地址', 'error');
        return;
    }
    
    // 验证 URL 格式
    try {
        new URL(url);
    } catch (e) {
        showNotification('服务器地址格式不正确', 'error');
        return;
    }
    
    const config = {
        url: url,
        username: username,
        password: password,
        token: token,
        public_url: publicUrl
    };
    
    try {
        const response = await fetch('/api/settings/openlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const result = await response.json();
        if (result.success) {
            showNotification('OpenList 配置已保存', 'success');
            // 清空密码输入框并更新状态提示（已保存到后端）
            document.getElementById('openlist-password').value = '';
            updatePasswordStatusHint();
        } else {
            showNotification(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存 OpenList 配置失败:', error);
        showNotification('保存失败: ' + error.message, 'error');
    }
}

/**
 * 更新密码状态提示
 */
function updatePasswordStatusHint() {
    const passwordInput = document.getElementById('openlist-password');
    const hintElement = document.getElementById('password-status-hint');
    
    if (!hintElement) {
        // 创建提示元素
        const hint = document.createElement('div');
        hint.id = 'password-status-hint';
        hint.className = 'text-xs text-gray-500 mt-1 flex items-center';
        hint.innerHTML = '<i class="fas fa-info-circle mr-1"></i>密码已保存，如需修改请重新输入';
        passwordInput.parentNode.appendChild(hint);
    } else {
        // 更新提示文本
        hintElement.innerHTML = '<i class="fas fa-info-circle mr-1"></i>密码已保存，如需修改请重新输入';
    }
}

/**
 * 监听密码输入框变化
 */
function initPasswordInputListener() {
    const passwordInput = document.getElementById('openlist-password');
    if (passwordInput) {
        passwordInput.addEventListener('input', function() {
            // 当用户开始输入时，移除状态提示
            const hintElement = document.getElementById('password-status-hint');
            if (hintElement) {
                hintElement.remove();
            }
        });
    }
}

async function testOpenListConnection() {
    const statusEl = document.getElementById('openlist-connection-status');
    const url = document.getElementById('openlist-url').value.trim();
    const username = document.getElementById('openlist-username').value.trim();
    const password = document.getElementById('openlist-password').value.trim();
    const token = document.getElementById('openlist-token').value.trim();
    
    if (!url) {
        showNotification('请填写服务器地址', 'error');
        return;
    }
    
    // 验证 URL 格式
    try {
        new URL(url);
    } catch (e) {
        showNotification('服务器地址格式不正确', 'error');
        return;
    }
    
    statusEl.innerHTML = '<i class="fas fa-spinner fa-spin text-blue-500"></i> <span class="text-gray-600">连接测试中...（使用' + (token ? 'Token' : '用户名密码') + '）</span>';
    
    try {
        const response = await fetch('/api/settings/openlist/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                username: username,
                password: password,
                token: token
            })
        });
        
        const result = await response.json();
        if (result.success) {
            statusEl.innerHTML = '<i class="fas fa-check-circle text-green-500"></i> <span class="text-green-600">' + result.message + '</span>';
            showNotification('OpenList 连接测试成功: ' + result.message, 'success');
        } else {
            statusEl.innerHTML = '<i class="fas fa-times-circle text-red-500"></i> <span class="text-red-600">连接失败: ' + (result.error || '未知错误') + '</span>';
            showNotification('连接失败: ' + (result.error || '未知错误'), 'error');
        }
    } catch (error) {
        console.error('测试 OpenList 连接失败:', error);
        statusEl.innerHTML = '<i class="fas fa-times-circle text-red-500"></i> <span class="text-red-600">连接失败: ' + error.message + '</span>';
        showNotification('连接测试失败: ' + error.message, 'error');
    }
}

// ========== 文件扩展名设置 ==========

/**
 * 加载文件扩展名设置
 */
async function loadFileExtensions() {
    try {
        const response = await fetch('/api/settings/extensions');
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.extensions) {
                document.getElementById('subtitle-extensions').value = data.extensions.subtitle || '.srt,.ass,.ssa,.sub,.vtt';
                document.getElementById('image-extensions').value = data.extensions.image || '.jpg,.jpeg,.png,.bmp,.gif,.webp';
                document.getElementById('nfo-extensions').value = data.extensions.nfo || '.nfo';
                document.getElementById('other-extensions').value = data.extensions.other || '';
            }
        }
    } catch (error) {
        console.error('加载文件扩展名设置失败:', error);
    }
}

/**
 * 加载系统通用设置
 */
async function loadSystemConfig() {
    try {
        const response = await fetch('/api/settings/system');
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.config) {
                const retryInput = document.getElementById('system-retry-count');
                if (retryInput) {
                    retryInput.value = data.config.sync_retry_count || 3;
                }
            }
        }
    } catch (error) {
        console.error('加载系统配置失败:', error);
    }
}

/**
 * 保存系统通用设置
 */
async function saveSystemConfig() {
    const retryCount = parseInt(document.getElementById('system-retry-count').value);
    
    if (isNaN(retryCount) || retryCount < 0) {
        showNotification('重试次数必须是非负整数', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/settings/system', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sync_retry_count: retryCount })
        });
        
        const result = await response.json();
        if (result.success) {
            showNotification('系统配置已保存', 'success');
        } else {
            showNotification(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存系统配置失败:', error);
        showNotification('保存失败: ' + error.message, 'error');
    }
}

/**
 * 保存文件扩展名设置
 */
async function saveFileExtensions() {
    const extensions = {
        subtitle: document.getElementById('subtitle-extensions').value.trim(),
        image: document.getElementById('image-extensions').value.trim(),
        nfo: document.getElementById('nfo-extensions').value.trim(),
        other: document.getElementById('other-extensions').value.trim()
    };
    
    // 验证格式
    for (const [key, value] of Object.entries(extensions)) {
        if (value && key !== 'other') {  // other 可以为空
            const exts = value.split(',').map(e => e.trim()).filter(e => e);
            for (const ext of exts) {
                if (!ext.startsWith('.')) {
                    showNotification(`扩展名格式错误: "${ext}" 必须以点开头`, 'error');
                    return;
                }
            }
        }
    }
    
    try {
        const response = await fetch('/api/settings/extensions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(extensions)
        });
        
        const result = await response.json();
        if (result.success) {
            showNotification('文件扩展名设置已保存', 'success');
        } else {
            showNotification(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存文件扩展名设置失败:', error);
        showNotification('保存失败: ' + error.message, 'error');
    }
}
