let selectedFile = null;
let currentTasks = [];
let pollTimer = null;

async function init() {
    await loadTasks();
}

async function loadTasks() {
    try {
        const data = await apiClient.getAllTasks();
        currentTasks = data.tasks || [];
        renderTaskList();
    } catch (error) {
        console.error('加载任务失败:', error);
        showToast('加载任务列表失败', 'error');
    }
}

function renderTaskList() {
    const container = document.getElementById('taskList');
    const countEl = document.getElementById('totalTasks');

    countEl.textContent = currentTasks.length;

    if (currentTasks.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="icon">📋</div>
                <p>暂无任务</p>
                <p class="hint">点击右上角按钮创建新任务</p>
            </div>
        `;
        return;
    }

    container.innerHTML = currentTasks.map((task) => {
        const tid = String(task.id || task.task_id || '');
        const statusInfo = formatStatus(task.status);
        return `
            <div class="task-item" onclick="showTaskDetail('${tid}')">
                <div class="task-info">
                    <div class="task-name">${escapeHtml(task.file_name || '未命名文档')}</div>
                    <div class="task-meta">
                        <span>创建时间: ${formatDate(task.created_at)}</span>
                        <span>测试点: ${task.test_point_count || 0} 个</span>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span class="task-status ${statusInfo.class}">${statusInfo.text}</span>
                    <div class="task-actions" onclick="event.stopPropagation()">
                        ${task.status === 'running' ? `
                            <button class="action-btn" onclick="stopTask('${tid}')">停止</button>
                        ` : ''}
                        <button class="action-btn" onclick="viewAnalysis('${tid}')">查看分析</button>
                        <button class="action-btn" onclick="deleteTask('${tid}')">删除</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function showCreateTaskModal() {
    document.getElementById('createTaskModal').classList.add('active');
}

function closeCreateTaskModal() {
    document.getElementById('createTaskModal').classList.remove('active');
    resetUpload();
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.docx')) {
        showToast('仅支持 .docx 文件', 'error');
        return;
    }

    selectedFile = file;
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileInfo').style.display = 'flex';
    document.getElementById('createTaskBtn').disabled = false;
}

function removeFile() {
    selectedFile = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('createTaskBtn').disabled = true;
}

function resetUpload() {
    removeFile();
}

async function createTask() {
    if (!selectedFile) {
        showToast('请先选择文件', 'error');
        return;
    }

    const btn = document.getElementById('createTaskBtn');
    btn.disabled = true;
    btn.textContent = '上传中...';

    try {
        const uploadResult = await apiClient.uploadDocument(selectedFile);

        const allPartIds = [];
        if (uploadResult.toc && Array.isArray(uploadResult.toc)) {
            uploadResult.toc.forEach((section) => {
                if (section.parts && Array.isArray(section.parts)) {
                    section.parts.forEach((part) => {
                        if (part.id) allPartIds.push(String(part.id));
                    });
                }
            });
        }

        if (allPartIds.length === 0) {
            throw new Error('未解析到需求片段，请检查文档结构');
        }

        const { task_id: taskId } = await apiClient.createTask(uploadResult.doc_id);
        await apiClient.startAnalysisForTask(taskId, allPartIds);

        closeCreateTaskModal();
        showToast('任务已创建并开始分析', 'success');
        await loadTasks();
        pollTaskStatus(taskId);
    } catch (error) {
        console.error('创建任务失败:', error);
        showToast(`创建失败: ${error.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '创建并分析';
    }
}

async function showTaskDetail(taskId) {
    try {
        const task = await apiClient.getTaskDetail(taskId);
        const tid = String(task.id || task.task_id || taskId);
        const statusInfo = formatStatus(task.status);

        document.getElementById('taskDetailContent').innerHTML = `
            <div class="detail-section">
                <h4>基本信息</h4>
                <div class="detail-row">
                    <span class="label">任务 ID:</span>
                    <span class="value" style="font-family:monospace;font-size:12px;">${escapeHtml(tid)}</span>
                </div>
                <div class="detail-row">
                    <span class="label">文件名:</span>
                    <span class="value">${escapeHtml(task.file_name || '')}</span>
                </div>
                <div class="detail-row">
                    <span class="label">状态:</span>
                    <span class="value"><span class="task-status ${statusInfo.class}">${statusInfo.text}</span></span>
                </div>
                <div class="detail-row">
                    <span class="label">创建时间:</span>
                    <span class="value">${formatDate(task.created_at)}</span>
                </div>
                <div class="detail-row">
                    <span class="label">测试点数量:</span>
                    <span class="value">${task.test_point_count || 0}</span>
                </div>
            </div>

            ${task.error_message ? `
                <div class="detail-section">
                    <h4>错误信息</h4>
                    <div class="error-message">${escapeHtml(task.error_message)}</div>
                </div>
            ` : ''}
        `;

        document.getElementById('taskDetailModal').classList.add('active');
    } catch (error) {
        console.error('获取任务详情失败:', error);
        showToast('获取任务详情失败', 'error');
    }
}

function closeTaskDetailModal() {
    document.getElementById('taskDetailModal').classList.remove('active');
}

async function viewAnalysis(taskId) {
    window.location.href = `/static/frontend/pages/analysis.html?taskId=${encodeURIComponent(taskId)}`;
}

async function stopTask(taskId) {
    if (!confirm('确定要停止此任务吗？')) return;

    try {
        await apiClient.stopAnalysis(taskId);
        showToast('任务已停止', 'info');
        await loadTasks();
    } catch (error) {
        console.error('停止任务失败:', error);
        showToast('停止任务失败', 'error');
    }
}

async function deleteTask(taskId) {
    if (!confirm('确定要删除此任务吗？将级联删除相关测试点与记录。')) return;

    try {
        await apiClient.deleteTask(taskId);
        showToast('任务已删除', 'success');
        await loadTasks();
    } catch (error) {
        console.error('删除任务失败:', error);
        showToast(`删除失败: ${error.message}`, 'error');
    }
}

function pollTaskStatus(taskId) {
    if (pollTimer) clearInterval(pollTimer);

    pollTimer = setInterval(async () => {
        try {
            const status = await apiClient.getTaskStatus(taskId);

            if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled' || status.status === 'error') {
                clearInterval(pollTimer);
                pollTimer = null;
                await loadTasks();

                if (status.status === 'completed') {
                    showToast('分析完成！', 'success');
                } else if (status.status === 'failed' || status.status === 'error') {
                    showToast('分析失败', 'error');
                }
            }
        } catch (error) {
            console.error('轮询状态失败:', error);
        }
    }, 2000);
}

document.addEventListener('DOMContentLoaded', init);
