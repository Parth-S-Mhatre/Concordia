// API Client for Concordia Entity Resolution Platform
// Local dev: backend on :8000. Production (Netlify/Vercel): relative /api
// is proxied to the Render backend (see frontend/_redirects, vercel.json).
const _host = window.location.hostname;
const _isLocal = _host === 'localhost' || _host === '127.0.0.1' || _host === '0.0.0.0';
const API_ORIGIN = `${window.location.protocol}//${_host}:8000`;
const API_BASE = _isLocal ? `${API_ORIGIN}/api` : '/api';

class ApiClient {
    constructor() {
        this.baseUrl = API_BASE;
        this.authProvider = null;
    }

    setAuthProvider(fn) {
        this.authProvider = fn;
    }

    async request(endpoint, options = {}) {
        const url = endpoint === '/health'
            ? (_isLocal ? `${API_ORIGIN}/health` : '/health')
            : `${this.baseUrl}${endpoint}`;
        const isFormData = options.body instanceof FormData;
        const headers = {
            ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
            ...options.headers,
        };
        if (this.authProvider && !headers.Authorization) {
            try {
                const token = await this.authProvider();
                if (token) headers.Authorization = `Bearer ${token}`;
            } catch {
                // Unauthenticated request; server decides (open demo vs 401)
            }
        }
        const config = { ...options, headers };

        if (config.body && typeof config.body === 'object' && !isFormData) {
            config.body = JSON.stringify(config.body);
        }

        try {
            const response = await fetch(url, config);
            const data = response.status === 204 ? null : await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || `HTTP ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error(`API Error (${endpoint}):`, error);
            throw error;
        }
    }

    // Health
    async health() {
        return this.request('/health');
    }

    // Auth
    async getPublicConfig() {
        return this.request('/auth/config');
    }

    async getMe() {
        return this.request('/auth/me');
    }

    // Sources
    async listSources() {
        return this.request('/sources');
    }

    async getSource(sourceId) {
        return this.request(`/sources/${sourceId}`);
    }

    async createSource(source) {
        return this.request('/sources', { method: 'POST', body: source });
    }

    async updateSource(sourceId, updates) {
        return this.request(`/sources/${sourceId}`, { method: 'PATCH', body: updates });
    }

    async deleteSource(sourceId) {
        return this.request(`/sources/${sourceId}`, { method: 'DELETE' });
    }

    async uploadCsv(sourceId, file) {
        return this.uploadFile(sourceId, file);
    }

    async uploadFile(sourceId, file) {
        const formData = new FormData();
        formData.append('file', file);
        return this.request(`/sources/${sourceId}/upload`, {
            method: 'POST',
            headers: {}, // Let browser set Content-Type for FormData
            body: formData,
        });
    }

    async inspectSchema(sourceId, file) {
        const formData = new FormData();
        formData.append('file', file);
        return this.request(`/sources/${sourceId}/schema`, {
            method: 'POST',
            headers: {},
            body: formData,
        });
    }

    async getMappingSuggestions(sourceId) {
        return this.request(`/sources/${sourceId}/mapping`);
    }

    async confirmMapping(sourceId, mappings) {
        return this.request(`/sources/${sourceId}/mapping`, {
            method: 'POST',
            body: { mappings },
        });
    }

    async getSourceStatus(sourceId) {
        return this.request(`/sources/${sourceId}/status`);
    }

    async getRelationships(sourceId) {
        return this.request(`/sources/${sourceId}/relationships`);
    }

    async getProfile(sourceId) {
        return this.request(`/sources/${sourceId}/profile`);
    }

    async getSourceGroup(groupId) {
        return this.request(`/sources/groups/${groupId}`);
    }

    // Processing
    async startProcessing(sourceId) {
        return this.request(`/processing/${sourceId}/start`, { method: 'POST' });
    }

    async getJobStatus(jobId) {
        return this.request(`/processing/jobs/${jobId}`);
    }

    async listJobs(sourceId = null) {
        const params = sourceId ? `?source_id=${sourceId}` : '';
        return this.request(`/processing/jobs${params}`);
    }

    async reprocessSource(sourceId) {
        return this.request(`/processing/reprocess/${sourceId}`, { method: 'POST' });
    }

    async resumeJob(jobId) {
        return this.request(`/processing/jobs/${jobId}/resume`, { method: 'POST' });
    }

    async getGlobalStats() {
        return this.request('/processing/stats/global');
    }

    // Search
    async searchEntity(query, limit = 10) {
        return this.request('/search', {
            method: 'POST',
            body: { query, limit },
        });
    }

    async getSearchSuggestions(query, limit = 10) {
        return this.request(`/search/suggestions?q=${encodeURIComponent(query)}&limit=${limit}`);
    }

    // Entities
    async listEntities(limit = 50, offset = 0, filters = {}) {
        const params = new URLSearchParams({ limit, offset, ...filters });
        return this.request(`/entities?${params.toString()}`);
    }

    async getEntity(entityId) {
        return this.request(`/entities/${entityId}`);
    }

    async getEntityTraceability(entityId) {
        return this.request(`/entities/${entityId}/traceability`);
    }

    async getEnrichmentPath(entityId) {
        return this.request(`/entities/${entityId}/enrichment-path`);
    }

    async getEntityHistory(entityId) {
        return this.request(`/entities/${entityId}/history`);
    }

    async getEntityGraph(entityId) {
        return this.request(`/entities/${entityId}/graph`);
    }

    async getEntityStats() {
        return this.request('/entities/stats/summary');
    }
}

// Export singleton
const api = new ApiClient();
export default api;