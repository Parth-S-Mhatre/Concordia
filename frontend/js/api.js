// API Client for Concordia Entity Resolution Platform
//
// Origin resolution (per page load):
//   1. Local dev backend (:8000) if it answers — fastest, preferred.
//   2. Otherwise the live Render backend — so the site works even with
//      no local server running.
// Note: 0.0.0.0 is mapped to localhost because browsers refuse to
// route 0.0.0.0 as a destination.
const RENDER_API = 'https://concordia-api-yl14.onrender.com';
const _host = window.location.hostname;
const _isLocalHost = _host === 'localhost' || _host === '127.0.0.1' || _host === '0.0.0.0';
const _fetchHost = _host === '0.0.0.0' ? 'localhost' : _host;
const LOCAL_API = `${window.location.protocol}//${_fetchHost}:8000`;

let _resolvedOrigin = null;

async function _probe(url, timeoutMs) {
    try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), timeoutMs);
        const response = await fetch(`${url}/health`, { signal: ctrl.signal });
        clearTimeout(timer);
        return response.ok;
    } catch {
        return false;
    }
}

/** Pick a working backend origin. Result is cached for the page lifetime. */
export async function resolveOrigin() {
    if (_resolvedOrigin) return _resolvedOrigin;
    if (!_isLocalHost) {
        _resolvedOrigin = RENDER_API;
    } else if (await _probe(LOCAL_API, 5000)) {
        _resolvedOrigin = LOCAL_API;
    } else {
        _resolvedOrigin = RENDER_API;
    }
    return _resolvedOrigin;
}

class ApiClient {
    constructor() {
        this.authProvider = null;
    }

    setAuthProvider(fn) {
        this.authProvider = fn;
    }

    async request(endpoint, options = {}) {
        const origin = await resolveOrigin();
        const url = endpoint === '/health'
            ? `${origin}/health`
            : `${origin}/api${endpoint}`;
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

    /**
     * Render free tier sleeps when idle; first contact can take ~30-60s.
     * Resolves the working origin first (local preferred, live fallback),
     * then polls /health until awake or timeout. Returns true when ready.
     */
    async warmup({ timeoutMs = 120000, intervalMs = 3000, onAttempt = null } = {}) {
        const origin = await resolveOrigin();
        const deadline = Date.now() + timeoutMs;
        let attempt = 0;
        for (;;) {
            attempt += 1;
            try {
                const ctrl = new AbortController();
                const timer = setTimeout(() => ctrl.abort(), 20000);
                const response = await fetch(`${origin}/health`, { signal: ctrl.signal });
                clearTimeout(timer);
                if (response.ok) return true;
            } catch {
                // Asleep, unreachable, or slow — keep polling until deadline
            }
            if (onAttempt) onAttempt(attempt);
            if (Date.now() >= deadline) return false;
            await new Promise((resolve) => setTimeout(resolve, intervalMs));
        }
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