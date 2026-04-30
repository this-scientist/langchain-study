/**
 * 与后端同源部署时使用 ''；若静态页与 API 不同域，可在部署前改为 API 根 URL。
 */
const API_BASE = '';

class ApiClient {
    _url(path) {
        const p = path.startsWith('/') ? path : `/${path}`;
        return `${API_BASE}${p}`;
    }

    async request(url, options = {}) {
        const method = options.method || 'GET';
        const headers = { ...options.headers };
        if (options.body != null && typeof options.body === 'string' && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }
        try {
            const response = await fetch(this._url(url), {
                ...options,
                headers,
            });

            if (response.status === 204) {
                return null;
            }

            if (!response.ok) {
                const errBody = await response.json().catch(() => ({}));
                const detail = errBody.detail;
                const msg = typeof detail === 'string'
                    ? detail
                    : (Array.isArray(detail) ? detail.map((d) => d.msg || d).join('; ') : `HTTP ${response.status}`);
                throw new Error(msg || `HTTP ${response.status}`);
            }

            const ct = response.headers.get('content-type') || '';
            if (ct.includes('application/json')) {
                return await response.json();
            }
            return await response.text();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    async uploadDocument(file) {
        const formData = new FormData();
        formData.append('file', file);
        const response = await fetch(this._url('/api/upload'), {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || '上传失败');
        }
        return response.json();
    }

    /** POST /api/create-task?doc_id= */
    async createTask(docId) {
        const qs = new URLSearchParams({ doc_id: docId });
        return this.request(`/api/create-task?${qs}`, { method: 'POST' });
    }

    /** POST /api/tasks/{taskId}/start-analysis */
    async startAnalysisForTask(taskId, selectedPartIds) {
        return this.request(`/api/tasks/${encodeURIComponent(taskId)}/start-analysis`, {
            method: 'POST',
            body: JSON.stringify({ selected_part_ids: selectedPartIds || [] }),
        });
    }

    /** 兼容旧逻辑：无 task_id 时由后端自动建任务 */
    async startAnalysisLegacy(taskIdOrNull, selectedPartIds) {
        return this.request('/api/start-analysis', {
            method: 'POST',
            body: JSON.stringify({
                task_id: taskIdOrNull,
                selected_part_ids: selectedPartIds || [],
            }),
        });
    }

    async getDocumentPreview(docId) {
        return this.request(`/api/document-preview/${encodeURIComponent(docId)}`);
    }

    async getTaskStatus(taskId) {
        return this.request(`/api/task-status/${encodeURIComponent(taskId)}`);
    }

    async getTaskResults(taskId) {
        return this.request(`/api/task-results/${encodeURIComponent(taskId)}`);
    }

    async stopAnalysis(taskId) {
        return this.request(`/api/stop-analysis/${encodeURIComponent(taskId)}`, {
            method: 'POST',
        });
    }

    async getAllTasks() {
        return this.request('/api/tasks');
    }

    async getTaskDetail(taskId) {
        return this.request(`/api/tasks/${encodeURIComponent(taskId)}`);
    }

    async deleteTask(taskId) {
        return this.request(`/api/tasks/${encodeURIComponent(taskId)}`, {
            method: 'DELETE',
        });
    }

    async listTestPoints(taskId, limit = 200, offset = 0) {
        const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
        return this.request(`/api/tasks/${encodeURIComponent(taskId)}/test-points?${qs}`);
    }

    async patchTestPointSoftDelete(testPointId, taskId) {
        const qs = new URLSearchParams({ task_id: taskId });
        return this.request(`/api/test-points/${encodeURIComponent(testPointId)}?${qs}`, {
            method: 'PATCH',
            body: JSON.stringify({ is_deleted: true }),
        });
    }

    async regenerateTestPoints(taskId, testPointIds, userInstruction) {
        return this.request(`/api/tasks/${encodeURIComponent(taskId)}/regenerate-test-points`, {
            method: 'POST',
            body: JSON.stringify({
                test_point_ids: testPointIds,
                user_instruction: userInstruction || '',
            }),
        });
    }

    async getRegenerationJob(jobId) {
        return this.request(`/api/regeneration-jobs/${encodeURIComponent(jobId)}`);
    }

    /** 触发浏览器下载 Excel */
    exportTestPointsUrl(taskId, includeDeleted = false) {
        const qs = new URLSearchParams();
        if (taskId) qs.set('task_id', taskId);
        if (includeDeleted) qs.set('include_deleted', 'true');
        const q = qs.toString();
        return this._url(`/api/export-test-points${q ? `?${q}` : ''}`);
    }
}

window.apiClient = new ApiClient();
