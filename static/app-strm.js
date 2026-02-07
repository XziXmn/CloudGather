// CloudGather - STRM 任务管理前端逻辑
let strmTasksCache = [];
let currentStrmTab = 'sync'; // 当前任务 Tab (sync/strm)
let currentEditingStrmTaskId = null;

/**
 * 切换任务类型 Tab（主界面的同步/STRM切换）
 */
function switchMainTab(tabType) {
    currentStrmTab = tabType;
    
    // 更新 Tab 样式
    document.querySelectorAll('.task-tab').forEach(tab => tab.classList.remove('active'));
    document.getElementById(`tab-${tabType}`).classList.add('active');
    
    // 显示/隐藏对应面板
    document.getElementById('sync-tasks-panel').style.display = tabType === 'sync' ? 'block' : 'none';
    document.getElementById('strm-tasks-panel').style.display = tabType === 'strm' ? 'block' : 'none';
    
    // 加载对应类型的任务
    if (tabType === 'strm') {
        loadStrmTasks();
    } else {
        loadTasks(); // 调用原有的同步任务加载函数
    }
}

/**
 * 加载 STRM 任务列表
 */
async function loadStrmTasks() {
    try {
        const response = await fetch('/api/strm/tasks');
        const data = await response.json();
        const tasks = data.tasks || [];
        strmTasksCache = tasks;
        renderStrmTasks(tasks);
    } catch (error) {
        console.error('加载 STRM 任务失败:', error);
        showToast('加载 STRM 任务失败', 'error');
    }
}

/**
 * 渲染 STRM 任务列表
 */
function renderStrmTasks(tasks) {
    const container = document.getElementById('strm-tasks-container');
    if (tasks.length === 0) {
        container.innerHTML = '<div class="text-center py-12 text-gray-400"><i class="fas fa-video text-5xl mb-4"></i><p>暂无 STRM 任务</p></div>';
        return;
    }
    
    container.innerHTML = tasks.map(task => {
        // 调度信息
        let scheduleInfo = '';
        if (task.schedule_type === 'CRON') {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-calendar-alt text-purple-500 mr-2"></i><code class="px-2 py-1 bg-gray-100 rounded text-xs font-mono">${task.cron_expression}</code></div>`;
        } else {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-clock text-yellow-500 mr-2"></i><span>间隔：${formatInterval(task.interval)}</span></div>`;
        }
        
        // 进度条
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
                </div>
            `;
        }
        
        // 统计信息
        let statsInfo = '';
        if (task.stats) {
            statsInfo = `
                <div class="mt-2 text-xs text-gray-500">
                    <span class="mr-3"><i class="fas fa-check-circle text-green-500"></i> 成功: ${task.stats.success}</span>
                    <span class="mr-3"><i class="fas fa-skip-forward text-gray-400"></i> 跳过: ${task.stats.skipped}</span>
                    <span><i class="fas fa-times-circle text-red-500"></i> 失败: ${task.stats.failed}</span>
                </div>
            `;
        }
        
        // STRM 模式徽章
        const modeBadges = {
            'AlistURL': '<span class="pill text-xs">OpenList URL</span>',
            'RawURL': '<span class="pill text-xs">Raw URL</span>',
            'AlistPath': '<span class="pill text-xs">OpenList Path</span>'
        };
        const modeBadge = modeBadges[task.mode] || '';
        
        return `
            <div class="task-card" data-task-id="${task.id}">
                <div class="flex items-start justify-between mb-3">
                    <div class="flex-1">
                        <div class="flex items-center gap-3 mb-1">
                            <h4 class="text-lg font-bold">${task.name}</h4>
                            <div class="status-badge-container">${getStatusBadge(task.status)}</div>
                            ${modeBadge}
                        </div>
                    </div>
                    <div class="flex items-center gap-2" title="${task.enabled ? '任务已启用' : '任务已禁用'}">
                        <span class="text-sm text-gray-600">${task.enabled ? '已启用' : '已禁用'}</span>
                        <label class="toggle-switch">
                            <input type="checkbox" ${task.enabled ? 'checked' : ''} 
                                   onchange="toggleStrmTask('${task.id}')" 
                                   ${task.status === 'RUNNING' ? 'disabled' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                </div>
                
                <div class="mb-3">
                    <div class="flex items-center text-sm text-gray-600">
                        <div class="flex items-center"><i class="fas fa-folder-open text-blue-500 mr-2"></i><span class="font-mono truncate" title="${task.source_dir}">${task.source_dir}</span></div>
                        <span class="mx-1 text-gray-400">→</span>
                        <div class="flex items-center"><i class="fas fa-folder text-green-500 mr-2"></i><span class="font-mono truncate" title="${task.target_dir}">${task.target_dir}</span></div>
                    </div>
                </div>

                <div class="flex items-center gap-4 text-sm text-gray-600 mb-3">
                    ${scheduleInfo}
                    ${task.last_run_time ? `<span class="text-xs text-gray-500"><i class="fas fa-history mr-1"></i>上次: ${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                </div>

                <div class="flex gap-2 flex-wrap mt-3">
                    <button onclick="triggerStrmTask('${task.id}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}><i class="fas fa-play"></i>立即运行</button>
                    <button onclick="openLogWindow('${task.id}', '${task.name} - STRM 日志')" class="btn btn-secondary text-sm"><i class="fas fa-terminal"></i>查看日志</button>
                    <button onclick="showStrmAdvancedTools('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-wrench"></i>高级工具</button>
                    <button onclick="showEditStrmTaskModal('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-edit"></i>编辑</button>
                    <button onclick="deleteStrmTask('${task.id}')" class="btn btn-secondary text-sm border-red-500 text-red-500"><i class="fas fa-trash"></i>删除</button>
                </div>
                
                ${progressBar}
                ${statsInfo}
            </div>
        `;
    }).join('');
}

/**
 * 显示添加 STRM 任务模态框
 */
function showAddStrmTaskModal() {
    currentEditingStrmTaskId = null;
    
    // 创建模态框
    const modal = document.createElement('div');
    modal.id = 'strm-task-modal';
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto m-4">
            <div class="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between z-10">
                <h2 class="text-xl font-bold">添加 STRM 任务</h2>
                <button onclick="closeStrmTaskModal()" class="text-gray-400 hover:text-gray-600">
                    <i class="fas fa-times text-xl"></i>
                </button>
            </div>
            <form id="strm-task-form" class="p-6" onsubmit="saveStrmTask(event)">
                ${renderStrmTaskForm()}
                <div class="flex justify-end gap-3 pt-4 border-t border-gray-200">
                    <button type="button" onclick="closeStrmTaskModal()" class="btn btn-secondary">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // 初始化目录自动提示
    if (typeof initDirectoryAutocomplete === 'function') {
        initDirectoryAutocomplete();
    }
    
    // 加载 OpenList 配置
    loadOpenListConfigToForm();
}

/**
 * 显示编辑 STRM 任务模态框
 */
async function showEditStrmTaskModal(taskId) {
    currentEditingStrmTaskId = taskId;
    
    try {
        const response = await fetch(`/api/strm/tasks/${taskId}`);
        const data = await response.json();
        const task = data.task;
        
        const modal = document.createElement('div');
        modal.id = 'strm-task-modal';
        modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
        modal.innerHTML = `
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto m-4">
                <div class="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between z-10">
                    <h2 class="text-xl font-bold">编辑 STRM 任务</h2>
                    <button onclick="closeStrmTaskModal()" class="text-gray-400 hover:text-gray-600">
                        <i class="fas fa-times text-xl"></i>
                    </button>
                </div>
                <form id="strm-task-form" class="p-6" onsubmit="saveStrmTask(event)">
                    ${renderStrmTaskForm(task)}
                    <div class="flex justify-end gap-3 pt-4 border-t border-gray-200">
                        <button type="button" onclick="closeStrmTaskModal()" class="btn btn-secondary">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            </div>
        `;
        
        document.body.appendChild(modal);

        // 初始化目录自动提示
        if (typeof initDirectoryAutocomplete === 'function') {
            initDirectoryAutocomplete();
        }
    } catch (error) {
        console.error('加载任务详情失败:', error);
        showToast('加载任务详情失败', 'error');
    }
}

/**
 * 切换 STRM 任务编辑页签
 */
function switchStrmTaskTab(tab) {
    const basicBtn = document.getElementById('strmTaskTabBasic');
    const advancedBtn = document.getElementById('strmTaskTabAdvanced');
    const basicItems = document.querySelectorAll('.strm-tab-basic');
    const advancedItems = document.querySelectorAll('.strm-tab-advanced');

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

/**
 * 渲染 STRM 任务表单
 */
function renderStrmTaskForm(task = null) {
    const isEdit = task !== null;
    
    return `
        <!-- 页签切换 -->
        <div class="flex border-b border-gray-200 mb-6">
            <button type="button" id="strmTaskTabBasic" class="px-6 py-3 border-b-2 border-blue-500 text-blue-600 font-medium transition-colors" onclick="switchStrmTaskTab('basic')">
                <i class="fas fa-info-circle mr-2"></i>基础配置
            </button>
            <button type="button" id="strmTaskTabAdvanced" class="px-6 py-3 border-b-2 border-transparent text-gray-500 font-medium hover:text-blue-600 transition-colors" onclick="switchStrmTaskTab('advanced')">
                <i class="fas fa-sliders mr-2"></i>高级配置
            </button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 strm-tab-basic">
            <!-- 基本信息 -->
            <div class="md:col-span-2">
                <label class="block text-sm text-gray-600 mb-2">任务名称 *</label>
                <input type="text" id="strmTaskName" class="w-full px-4 py-3 rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none" 
                       placeholder="例如：电影库 STRM 生成" value="${task?.name || ''}" required>
            </div>
            
            <div>
                <label class="block text-sm text-gray-600 mb-2">OpenList 源目录 * <span class="text-xs text-gray-400">(输入后自动提示)</span></label>
                <input type="text" id="strmSourceDir" class="w-full px-4 py-3 rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none" 
                       placeholder="/电影" value="${task?.source_dir || ''}" autocomplete="off" required>
                <p class="text-xs text-gray-500 mt-1"><i class="fas fa-info-circle"></i> OpenList 中的源目录路径</p>
            </div>
            
            <div>
                <label class="block text-sm text-gray-600 mb-2">本地目标目录 * <span class="text-xs text-gray-400">(输入后自动提示)</span></label>
                <input type="text" id="strmTargetDir" class="w-full px-4 py-3 rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none" 
                       placeholder="/mnt/media/strm" value="${task?.target_dir || ''}" autocomplete="off" required>
                <p class="text-xs text-gray-500 mt-1"><i class="fas fa-info-circle"></i> 本地生成 .strm 文件的目录</p>
            </div>
            
            <!-- STRM 生成配置 -->
            <div class="md:col-span-2 border-t border-gray-200 pt-4">
                <h3 class="font-bold mb-3"><i class="fas fa-video text-purple-500 mr-2"></i>STRM 生成配置</h3>
                
                <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                    <div class="md:col-span-2">
                        <label class="block text-xs text-gray-500 mb-1">STRM 模式 *</label>
                        <select id="strmMode" class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none">
                            <option value="AlistURL" ${task?.mode === 'AlistURL' ? 'selected' : ''}>OpenList URL (推荐：支持 302 重定向)</option>
                            <option value="RawURL" ${task?.mode === 'RawURL' ? 'selected' : ''}>Raw URL (直链：直接请求原始地址)</option>
                            <option value="AlistPath" ${task?.mode === 'AlistPath' ? 'selected' : ''}>OpenList Path (路径：由客户端解析路径)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">最大并发数</label>
                        <input type="number" id="strmMaxWorkers" class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none" 
                               min="1" max="100" value="${task?.max_workers || 3}">
                    </div>
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">扫描间隔 (秒)</label>
                        <input type="number" id="strmWaitTime" class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none" 
                               min="0" step="0.1" value="${task?.wait_time || 0}">
                    </div>
                </div>

                <div class="mb-4">
                    <label class="block text-sm text-gray-600 mb-3">同步额外文件 <span class="text-xs text-gray-400">(除了生成 .strm 外，同时同步关联的元数据文件)</span></label>
                    <div class="flex flex-wrap gap-3 text-sm items-center">
                        <button type="button" 
                                id="strmSubtitle" 
                                class="px-4 py-2 rounded-lg border-2 transition-all duration-200 ${task?.subtitle ? 'border-blue-500 bg-blue-50 text-blue-800' : 'border-gray-200 bg-transparent text-gray-600'}"
                                data-active="${task?.subtitle ? 'true' : 'false'}"
                                title="同步字幕文件（如 .srt, .ass, .ssa 等），方便播放器自动加载。"
                                onclick="toggleStrmExtraFile(this)">
                            <i class="fas fa-closed-captioning mr-1"></i>同步字幕
                        </button>
                        
                        <button type="button" 
                                id="strmImage" 
                                class="px-4 py-2 rounded-lg border-2 transition-all duration-200 ${task?.image ? 'border-blue-500 bg-blue-50 text-blue-800' : 'border-gray-200 bg-transparent text-gray-600'}"
                                data-active="${task?.image ? 'true' : 'false'}"
                                title="同步图片文件（如 .jpg, .png, .webp 等），用于展示海报和剧照。"
                                onclick="toggleStrmExtraFile(this)">
                            <i class="fas fa-image mr-1"></i>同步图片
                        </button>
                        
                        <button type="button" 
                                id="strmNfo" 
                                class="px-4 py-2 rounded-lg border-2 transition-all duration-200 ${task?.nfo ? 'border-blue-500 bg-blue-50 text-blue-800' : 'border-gray-200 bg-transparent text-gray-600'}"
                                data-active="${task?.nfo ? 'true' : 'false'}"
                                title="同步 .nfo 元数据文件，包含影片信息、演职员表等，供 Emby/Jellyfin/Plex 使用。"
                                onclick="toggleStrmExtraFile(this)">
                            <i class="fas fa-file-code mr-1"></i>同步 NFO
                        </button>
                    </div>
                    <p class="text-xs text-gray-500 mt-2">
                        <i class="fas fa-info-circle"></i> 选中后，程序将在生成 .strm 的同时，将对应的字幕、图片或 NFO 文件物理复制到目标目录。
                    </p>
                </div>
            </div>

            <!-- 调度设置 -->
            <div class="md:col-span-2 border-t border-gray-200 pt-4">
                <h3 class="font-bold mb-3"><i class="fas fa-clock text-blue-500 mr-2"></i>调度设置</h3>
                
                <div id="strmCronConfig">
                    <label class="block text-sm text-gray-600 mb-2">Cron 表达式 * <span class="text-xs text-gray-400">(格式: 分 时 日 月 星期)</span></label>
                    <div class="flex gap-2 mb-2">
                        <input type="text" id="strmCronExpression" class="flex-1 px-4 py-3 rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none bg-white font-mono" 
                               placeholder="0 2 * * *" value="${task?.cron_expression || ''}" oninput="validateStrmCron()" required>
                        <button type="button" onclick="showStrmCronPresets()" class="btn btn-secondary whitespace-nowrap"><i class="fas fa-list"></i> 预设</button>
                        <button type="button" onclick="generateStrmRandomCron()" class="btn btn-secondary"><i class="fas fa-dice"></i></button>
                    </div>
                    <div id="strmCronValidation" class="text-xs mt-1"></div>
                    <div id="strmCronPresetList" class="mt-2" style="display: none;">
                        <div class="max-h-48 overflow-y-auto bg-gray-50 rounded-lg p-2 space-y-1"></div>
                    </div>
                </div>
            </div>
        </div>

        <div class="strm-tab-advanced hidden space-y-6">
            <!-- 同步删除配置 -->
            <div>
                <h3 class="font-bold mb-3 flex items-center gap-2"><i class="fas fa-sync-alt text-orange-500"></i>同步删除配置</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <label class="flex items-center gap-3 cursor-pointer p-3 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
                        <input type="checkbox" id="strmSyncServer" class="w-5 h-5 text-orange-500 rounded focus:ring-orange-400" ${task?.sync_server ? 'checked' : ''}>
                        <div class="flex-1">
                            <span class="text-sm font-medium text-gray-700">同步服务端删除</span>
                            <p class="text-xs text-gray-500">当源文件删除后，自动删除本地已有的 .strm 文件及关联文件</p>
                        </div>
                    </label>

                    <label class="flex items-center gap-3 cursor-pointer p-3 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
                        <input type="checkbox" id="strmSyncLocalDelete" class="w-5 h-5 text-red-500 rounded focus:ring-red-400" ${task?.sync_local_delete ? 'checked' : ''}>
                        <div class="flex-1">
                            <span class="text-sm font-medium text-gray-700">同步本地删除到服务器</span>
                            <p class="text-xs text-gray-500">当本地 .strm 被删除后，尝试同步删除服务器上的源文件</p>
                        </div>
                    </label>
                </div>
            </div>

            <!-- 智能保护 -->
            <div>
                <h3 class="font-bold mb-3 flex items-center gap-2"><i class="fas fa-shield-alt text-orange-500"></i>智能保护选项</h3>
                <div class="p-4 rounded-lg border border-orange-100">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-xs text-gray-500 mb-1">删除阈值</label>
                            <input type="number" id="strmThreshold" class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-orange-400 outline-none bg-white" 
                                   min="1" value="${task?.smart_protection?.threshold || 100}">
                            <p class="text-[10px] text-gray-400 mt-1">单次删除超过此值时拦截，防止服务端异常导致本地全删</p>
                        </div>
                        <div>
                            <label class="block text-xs text-gray-500 mb-1">宽限扫描次数</label>
                            <input type="number" id="strmGraceScans" class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-orange-400 outline-none bg-white" 
                                   min="1" value="${task?.smart_protection?.grace_scans || 3}">
                            <p class="text-[10px] text-gray-400 mt-1">连续确认缺失此次数后才执行物理删除</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 忽略文件 -->
            <div>
                <h3 class="font-bold mb-3 flex items-center gap-2"><i class="fas fa-eye-slash text-gray-500"></i>文件后缀过滤 (同步本地删除时生效)</h3>
                <div class="p-4 rounded-lg border border-gray-100">
                    <div class="flex flex-col md:flex-row items-stretch gap-2 mb-2">
                        <select id="strmSuffixMode" class="w-full md:w-40 px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none bg-white">
                            <option value="NONE" ${task?.suffix_mode === 'NONE' ? 'selected' : ''}>不过滤</option>
                            <option value="INCLUDE" ${task?.suffix_mode === 'INCLUDE' ? 'selected' : ''}>仅允许以下后缀</option>
                            <option value="EXCLUDE" ${task?.suffix_mode === 'EXCLUDE' ? 'selected' : ''}>排除以下后缀</option>
                        </select>
                        <div class="relative w-full md:flex-1">
                            <input type="text" id="strmSuffixList" class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-400 outline-none bg-white font-mono" 
                                   placeholder="例如: mp4,mkv,nfo" value="${(task?.suffix_list || []).join(',')}"
                                   onfocus="document.getElementById('strmSuffixPresetPanel').style.display='block'">
                            
                            <!-- 后缀预设面板 -->
                            <div id="strmSuffixPresetPanel" class="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50" style="display: none;">
                                <div class="p-2 text-xs text-gray-500 border-b border-gray-100">快速选择后缀组：</div>
                                <button type="button" class="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 transition-colors" onclick="fillStrmSuffix('mp4,mkv,avi,mov,flv,wmv,mpeg,mpg,m4v,ts,rmvb,webm')">
                                    <i class="fas fa-video text-blue-500 mr-2"></i>常用影视文件
                                </button>
                                <button type="button" class="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 transition-colors" onclick="fillStrmSuffix('nfo,srt,ass,sub,idx,txt,jpg,jpeg,png,bmp,tbn,xml')">
                                    <i class="fas fa-file-alt text-orange-500 mr-2"></i>常用元数据文件
                                </button>
                                <button type="button" class="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 transition-colors" onclick="fillStrmSuffix('')">
                                    <i class="fas fa-eraser text-gray-500 mr-2"></i>清空
                                </button>
                            </div>
                        </div>
                    </div>
                    <p class="text-[10px] text-gray-400">
                        <i class="fas fa-info-circle"></i> 多个后缀用逗号分隔，不需要带点。点击输入框可快速选择预设后缀组。
                    </p>
                </div>
            </div>
        </div>
    `;
}

/**
 * 切换同步服务端删除
 */
function toggleStrmSyncServer() {
    const enabled = document.getElementById('strmSyncServer').checked;
    document.getElementById('strmProtectionConfig').style.display = enabled ? 'block' : 'none';
}

/**
 * 切换额外文件选项按钮状态
 */
function toggleStrmExtraFile(button) {
    const isActive = button.dataset.active === 'true';
    if (isActive) {
        button.dataset.active = 'false';
        button.classList.remove('border-blue-500', 'bg-blue-50', 'text-blue-800');
        button.classList.add('border-gray-200', 'bg-transparent', 'text-gray-600');
    } else {
        button.dataset.active = 'true';
        button.classList.remove('border-gray-200', 'bg-transparent', 'text-gray-600');
        button.classList.add('border-blue-500', 'bg-blue-50', 'text-blue-800');
    }
}

/**
 * 加载 OpenList 配置到表单
 */
async function loadOpenListConfigToForm() {
    try {
        const response = await fetch('/api/settings/openlist');
        const data = await response.json();
        if (data.success && data.config) {
            // 不自动填充，保持留空状态
            // 用户可以手动复制全局配置，或者直接留空使用全局配置
        }
    } catch (error) {
        console.error('加载 OpenList 配置失败:', error);
    }
}

/**
 * 切换忽略面板显示
 */
function toggleStrmIgnorePanel() {
    const panel = document.getElementById('strmIgnorePresetPanel');
    if (panel) {
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
}

/**
 * 填充忽略后缀
 */
function fillStrmSuffix(extensions) {
    const input = document.getElementById('strmSuffixList');
    if (input) {
        input.value = extensions;
    }
    const panel = document.getElementById('strmSuffixPresetPanel');
    if (panel) {
        panel.style.display = 'none';
    }
}

// 监听点击外部关闭预设面板
document.addEventListener('click', (e) => {
    const panel = document.getElementById('strmSuffixPresetPanel');
    const input = document.getElementById('strmSuffixList');
    if (panel && input && !panel.contains(e.target) && !input.contains(e.target)) {
        panel.style.display = 'none';
    }
});

/**
 * 保存 STRM 任务
 */
async function saveStrmTask(event) {
    event.preventDefault();
    const taskData = {
        name: document.getElementById('strmTaskName').value.trim(),
        source_dir: document.getElementById('strmSourceDir').value.trim(),
        target_dir: document.getElementById('strmTargetDir').value.trim(),
        schedule_type: 'CRON',
        cron_expression: document.getElementById('strmCronExpression').value.trim(),
        
        // STRM 配置
        mode: document.getElementById('strmMode').value,
        subtitle: document.getElementById('strmSubtitle').dataset.active === 'true',
        image: document.getElementById('strmImage').dataset.active === 'true',
        nfo: document.getElementById('strmNfo').dataset.active === 'true',
        max_workers: parseInt(document.getElementById('strmMaxWorkers').value),
        wait_time: parseFloat(document.getElementById('strmWaitTime').value),
        
        // 同步删除配置
        sync_server: document.getElementById('strmSyncServer').checked,
        sync_local_delete: document.getElementById('strmSyncLocalDelete').checked,
        suffix_mode: document.getElementById('strmSuffixMode').value,
        suffix_list: document.getElementById('strmSuffixList').value.split(',').map(s => s.trim().replace(/^\./, '')).filter(s => s),
        smart_protection: {
            threshold: parseInt(document.getElementById('strmThreshold').value),
            grace_scans: parseInt(document.getElementById('strmGraceScans').value)
        }
    };
    
    try {
        let response;
        if (currentEditingStrmTaskId) {
            // 更新任务
            response = await fetch(`/api/strm/tasks/${currentEditingStrmTaskId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
        } else {
            // 创建任务
            response = await fetch('/api/strm/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
        }
        
        const result = await response.json();
        if (result.success) {
            // 先关闭模态框，再显示提示，确保交互流畅
            closeStrmTaskModal();
            showToast(currentEditingStrmTaskId ? 'STRM 任务已更新' : 'STRM 任务已创建', 'success');
            loadStrmTasks();
        } else {
            showToast(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存 STRM 任务失败:', error);
        showToast('保存失败: ' + error.message, 'error');
    }
}

/**
 * 关闭 STRM 任务模态框
 */
function closeStrmTaskModal() {
    const modal = document.getElementById('strm-task-modal');
    if (modal) {
        modal.remove();
    }
    currentEditingStrmTaskId = null;
}

/**
 * 切换 STRM 任务启用状态
 */
async function toggleStrmTask(taskId) {
    try {
        const response = await fetch(`/api/strm/tasks/${taskId}/toggle`, {
            method: 'POST'
        });
        const result = await response.json();
        if (result.success) {
            showToast(`任务已${result.enabled ? '启用' : '禁用'}`, 'success');
            loadStrmTasks();
        } else {
            showToast(result.error || '操作失败', 'error');
            loadStrmTasks(); // 恢复状态
        }
    } catch (error) {
        console.error('切换任务状态失败:', error);
        showToast('操作失败', 'error');
        loadStrmTasks();
    }
}

/**
 * 立即触发 STRM 任务
 */
async function triggerStrmTask(taskId) {
    if (!confirm('确定要立即执行此任务吗？')) return;
    
    try {
        const response = await fetch(`/api/strm/tasks/${taskId}/trigger`, {
            method: 'POST'
        });
        const result = await response.json();
        if (result.success) {
            showToast('任务已触发执行', 'success');
            setTimeout(() => loadStrmTasks(), 1000);
        } else {
            showToast(result.error || '触发失败', 'error');
        }
    } catch (error) {
        console.error('触发任务失败:', error);
        showToast('触发失败', 'error');
    }
}

/**
 * 删除 STRM 任务
 */
async function deleteStrmTask(taskId) {
    const task = strmTasksCache.find(t => t.id === taskId);
    if (!task) return;
    
    if (!confirm(`确定要删除 STRM 任务 "${task.name}" 吗？此操作不可恢复！`)) return;
    
    try {
        const response = await fetch(`/api/strm/tasks/${taskId}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        if (result.success) {
            showToast('STRM 任务已删除', 'success');
            loadStrmTasks();
        } else {
            showToast(result.error || '删除失败', 'error');
        }
    } catch (error) {
        console.error('删除任务失败:', error);
        showToast('删除失败', 'error');
    }
}

/**
 * Toast 提示
 */
function showToast(message, type = 'info') {
    // 优先使用全局 showNotification
    if (typeof window.showNotification === 'function') {
        window.showNotification(message, type);
    } else if (typeof showNotification === 'function') {
        showNotification(message, type);
    } else if (typeof window.showToast === 'function') {
        window.showToast(message, type);
    } else {
        alert(message);
    }
}

// 定时刷新 STRM 任务列表（仅当显示 STRM Tab 时）
setInterval(() => {
    if (currentView === 'tasks' && currentStrmTab === 'strm') {
        loadStrmTasks();
    }
}, 3000);

/**
 * STRM Cron 验证
 */
let strmCronValidationTimeout = null;
async function validateStrmCron() {
    clearTimeout(strmCronValidationTimeout);
    const expression = document.getElementById('strmCronExpression')?.value.trim();
    const validationDiv = document.getElementById('strmCronValidation');
    
    if (!validationDiv) return;
    
    if (!expression) {
        validationDiv.innerHTML = '';
        return;
    }
    
    strmCronValidationTimeout = setTimeout(async () => {
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

/**
 * 显示 STRM Cron 预设
 */
let strmCronPresetsCache = null;
async function showStrmCronPresets() {
    const presetList = document.getElementById('strmCronPresetList');
    const container = presetList.querySelector('div');
    
    if (!presetList || !container) return;
    
    if (presetList.style.display === 'block') {
        presetList.style.display = 'none';
        return;
    }
    
    if (!strmCronPresetsCache) {
        try {
            const response = await fetch('/api/cron/presets');
            const data = await response.json();
            strmCronPresetsCache = data.presets || [];
        } catch (error) {
            showToast('加载预设失败', 'error');
            return;
        }
    }
    
    container.innerHTML = strmCronPresetsCache.map(preset => `
        <div class="px-3 py-2 bg-white hover:bg-blue-50 rounded cursor-pointer text-sm transition-colors" onclick="selectStrmCronPreset('${preset.expression}')">
            <div class="flex items-center justify-between">
                <span class="font-semibold">${preset.name}</span>
                <code class="text-xs bg-gray-100 px-2 py-1 rounded">${preset.expression}</code>
            </div>
            <div class="text-xs text-gray-500 mt-1">${preset.description}</div>
        </div>
    `).join('');
    
    presetList.style.display = 'block';
}

/**
 * 选择 STRM Cron 预设
 */
function selectStrmCronPreset(expression) {
    const input = document.getElementById('strmCronExpression');
    const presetList = document.getElementById('strmCronPresetList');
    
    if (input) {
        input.value = expression;
        validateStrmCron();
    }
    if (presetList) {
        presetList.style.display = 'none';
    }
}

/**
 * 随机生成 STRM Cron
 */
async function generateStrmRandomCron() {
    const patterns = ['hourly', 'daily', 'night'];
    const randomPattern = patterns[Math.floor(Math.random() * patterns.length)];
    
    try {
        const response = await fetch(`/api/cron/random?pattern=${randomPattern}`);
        const data = await response.json();
        
        const input = document.getElementById('strmCronExpression');
        if (input) {
            input.value = data.expression;
            validateStrmCron();
            showToast(`随机生成: ${data.description}`, 'success');
        }
    } catch (error) {
        showToast('生成失败', 'error');
    }
}

/**
 * STRM 高级工具
 */
function showStrmAdvancedTools(taskId) {
    const task = strmTasksCache.find(t => t.id === taskId);
    if (!task) {
        showToast('任务不存在', 'error');
        return;
    }
    
    const modal = document.createElement('div');
    modal.className = 'overlay-modal show';
    modal.id = 'strmAdvancedToolsModal';
    modal.innerHTML = `
        <div class="modal-card card" onclick="event.stopPropagation()">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2">
                    <i class="fas fa-wrench text-purple-500 text-xl"></i>
                    <h3 class="text-xl font-bold">STRM 高级工具</h3>
                </div>
                <button class="btn btn-secondary text-sm" onclick="closeStrmAdvancedTools()"><i class="fas fa-times"></i>关闭</button>
            </div>
            <div class="mb-4">
                <p class="text-sm text-gray-600 mb-2">任务: <span class="font-bold">${task.name}</span></p>
                <p class="text-xs text-gray-500">${task.source_dir} → ${task.target_dir}</p>
            </div>
            <div class="space-y-3">
                <div class="border border-gray-200 rounded-lg p-4 hover:border-purple-300 transition-colors">
                    <div class="flex items-start gap-3">
                        <i class="fas fa-sync-alt text-purple-500 text-2xl mt-1"></i>
                        <div class="flex-1">
                            <h4 class="font-bold text-lg mb-1">全量覆盖生成</h4>
                            <p class="text-sm text-gray-600 mb-3">强制重新扫描并生成所有 .strm 文件，覆盖已存在的文件。此操作不会修改任务的持久配置。</p>
                            <button onclick="triggerStrmFullOverwrite('${taskId}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                                <i class="fas fa-bolt"></i>立即执行
                            </button>
                        </div>
                    </div>
                </div>
                
                <div class="border border-gray-200 rounded-lg p-4 hover:border-purple-300 transition-colors">
                    <div class="flex items-start gap-3">
                        <i class="fas fa-database text-blue-500 text-2xl mt-1"></i>
                        <div class="flex-1">
                            <h4 class="font-bold text-lg mb-1">重构历史缓存</h4>
                            <p class="text-sm text-gray-600 mb-3">扫描目标端已存在的 .strm 文件并回填缓存树。可避免升级后重复生成已存在的文件。</p>
                            <button onclick="triggerStrmReconstruct('${taskId}')" class="btn btn-secondary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                                <i class="fas fa-hammer"></i>开始重构
                            </button>
                        </div>
                    </div>
                </div>

                <div class="bg-blue-50 border border-blue-200 rounded-lg p-3">
                    <div class="flex items-start gap-2">
                        <i class="fas fa-info-circle text-blue-600 mt-0.5"></i>
                        <p class="text-xs text-blue-700">
                            <strong>注意：</strong>全量覆盖会忽略本地已有的文件状态，重新向 OpenList 发起请求并写入 .strm。此操作仅执行一次，不影响定时任务的增量策略。
                        </p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeStrmAdvancedTools();
    });
}

function closeStrmAdvancedTools() {
    const modal = document.getElementById('strmAdvancedToolsModal');
    if (modal) {
        modal.remove();
    }
}

async function triggerStrmFullOverwrite(taskId) {
    const task = strmTasksCache.find(t => t.id === taskId);
    if (!task) {
        showToast('任务不存在', 'error');
        return;
    }
    
    if (!confirm(`确认对 STRM 任务「${task.name}」执行全量覆盖生成吗？\n\n此操作将强制覆盖所有已存在的 .strm 文件！`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/strm/tasks/${taskId}/full-overwrite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('全量覆盖任务已加入队列', 'success');
            closeStrmAdvancedTools();
            setTimeout(() => {
                openLogWindow(taskId, task.name + ' - STRM 日志');
            }, 500);
        } else {
            showToast(result.error || '执行失败', 'error');
        }
    } catch (error) {
        console.error('全量覆盖失败:', error);
        showToast('执行失败', 'error');
    }
}

async function triggerStrmReconstruct(taskId) {
    const task = strmTasksCache.find(t => t.id === taskId);
    if (!task) {
        showToast('任务不存在', 'error');
        return;
    }
    
    if (!confirm(`确认重构 STRM 任务「${task.name}」的缓存吗？\n\n系统将扫描目标目录中的 .strm 文件并恢复其缓存状态。`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/strm/tasks/${taskId}/reconstruct`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('缓存重构任务已启动', 'success');
            closeStrmAdvancedTools();
            setTimeout(() => {
                openLogWindow(taskId, task.name + ' - STRM 日志');
            }, 500);
        } else {
            showToast(result.error || '执行失败', 'error');
        }
    } catch (error) {
        console.error('缓存重构失败:', error);
        showToast('执行失败', 'error');
    }
}
