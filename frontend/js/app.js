import api from './api.js?v=5';
import * as auth from './auth.js?v=4';

const canonicalFields = ['', 'email', 'phone', 'username', 'member_id', 'name', 'address', 'company'];
const screenNames = ['dashboard', 'sources', 'mapping', 'search'];
const screens = Object.fromEntries(screenNames.map(name => [name, document.getElementById(`screen-${name}`)]));
const state = { sources: [], currentSourceId: null, mappings: [], mappingRequest: 0, toastTimer: null, navPending: 0 };

/* ---- Motion helpers: animated dot loader + nav progress bar ---- */
function dots() {
    return '<span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>';
}
function loadingRow(text) {
    return `<p class="empty-row">${escapeHtml(text)}${dots()}</p>`;
}
function showNavLoader() {
    state.navPending += 1;
    document.getElementById('nav-loader')?.classList.add('is-loading');
}
function hideNavLoader() {
    state.navPending = Math.max(0, state.navPending - 1);
    if (!state.navPending) document.getElementById('nav-loader')?.classList.remove('is-loading');
}

document.addEventListener('DOMContentLoaded', initialize);

async function initialize() {
    document.getElementById('today-label').textContent = new Intl.DateTimeFormat(undefined, {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
    }).format(new Date()).toUpperCase();
    bindEvents();
    api.setAuthProvider(() => auth.ensureToken());
    const awake = await warmBackend();
    if (!awake) return;
    const allowed = await initAuth();
    if (!allowed) return;
    await refreshConnection();
    await loadDashboard();
    await loadSources();
}

/** Block boot on backend readiness; the existing nav progress bar is the
indicator — no overlay, the shell stays visible behind it. */
async function warmBackend() {
    showNavLoader();
    const ready = await api.warmup({});
    hideNavLoader();
    if (!ready) {
        showToast('The backend is not responding. Reload the page to retry.', true);
    }
    return ready;
}

/** Auth gate: returns true when the workspace may load. */
async function initAuth() {
    let config = null;
    try {
        config = await auth.getPublicConfig();
        state.authConfig = config;
    } catch {
        return true; // Backend unreachable; connection dot will report it
    }
    let me = { anonymous: true };
    if (auth.getSession()?.idToken) {
        try {
            me = await api.getMe();
        } catch {
            me = { anonymous: true };
        }
    }
    renderUser(me);
    if (!me.anonymous) return true;
    if (config.requireAuth) {
        showGate(false);
        return false;
    }
    return true;
}

function showGate(allowGuest) {
    document.getElementById('continue-guest').hidden = !allowGuest;
    document.getElementById('login-error').hidden = true;
    document.getElementById('auth-gate').hidden = false;
}

function hideGate() {
    document.getElementById('auth-gate').hidden = true;
}

function renderUser(me) {
    const chip = document.getElementById('user-chip');
    const action = document.getElementById('auth-action');
    state.user = me;
    if (me && !me.anonymous) {
        chip.hidden = false;
        chip.innerHTML = `${escapeHtml(me.email || me.uid)}${me.admin ? '<span class="admin-badge">ADMIN</span>' : ''}`;
        action.textContent = 'Sign out';
    } else {
        chip.hidden = true;
        action.textContent = 'Sign in';
    }
}

async function handleLogin(event) {
    event.preventDefault();
    const error = document.getElementById('login-error');
    const submit = document.getElementById('login-submit');
    error.hidden = true;
    submit.disabled = true;
    try {
        await auth.signIn(
            document.getElementById('login-email').value.trim(),
            document.getElementById('login-password').value
        );
        const me = await api.getMe();
        renderUser(me);
        hideGate();
        showToast(me.admin ? 'Signed in as demo admin.' : 'Signed in.');
        await refreshConnection();
        await loadDashboard();
        await loadSources();
    } catch (loginError) {
        error.textContent = loginError.message;
        error.hidden = false;
    } finally {
        submit.disabled = false;
    }
}

function handleAuthAction() {
    if (state.user && !state.user.anonymous) {
        // End the session and leave the workspace: reload alone would
        // re-fetch and re-render the dashboard in open mode, so the
        // signed-out user would still see all results. Landing instead.
        auth.signOut();
        state.user = { anonymous: true };
        state.sources = [];
        window.location.href = '/index.html';
    } else {
        window.location.href = '/login.html';
    }
}

async function handleGoogleLogin() {
    const error = document.getElementById('login-error');
    error.hidden = true;
    try {
        await auth.signInWithGoogle();
        const me = await api.getMe();
        renderUser(me);
        hideGate();
        // Fresh Google accounts land on an empty dashboard by design.
        showToast(me.admin ? 'Signed in as demo admin.' : 'Signed in with Google. Your workspace is ready.');
        await refreshConnection();
        await loadDashboard();
        await loadSources();
    } catch (loginError) {
        error.textContent = loginError.message;
        error.hidden = false;
    }
}

function bindEvents() {
    document.querySelectorAll('[data-screen], [data-go]').forEach(control => {
        control.addEventListener('click', event => {
            event.preventDefault();
            switchScreen(control.dataset.screen || control.dataset.go);
        });
    });
    document.getElementById('open-upload').addEventListener('click', openUploadDialog);
    document.getElementById('open-upload-sources').addEventListener('click', openUploadDialog);
    document.getElementById('close-upload').addEventListener('click', closeUploadDialog);
    document.getElementById('cancel-upload').addEventListener('click', closeUploadDialog);
    document.getElementById('upload-dialog').addEventListener('click', event => {
        if (event.target === event.currentTarget) closeUploadDialog();
    });
    document.getElementById('upload-form').addEventListener('submit', uploadSource);
    document.getElementById('refresh-sources').addEventListener('click', loadSources);
    const refreshStats = document.getElementById('refresh-stats');
    if (refreshStats) refreshStats.addEventListener('click', loadGlobalStats);
    document.getElementById('mapping-source').addEventListener('change', event => {
        state.currentSourceId = event.target.value || null;
        loadMappings();
    });
    document.getElementById('confirm-mapping').addEventListener('click', confirmAndProcess);
    document.getElementById('reset-mapping').addEventListener('click', loadMappings);
    document.getElementById('search-form').addEventListener('submit', event => {
        event.preventDefault();
        searchEntity();
    });
    document.getElementById('try-example').addEventListener('click', fillDemoQuery);
    document.getElementById('try-example-2').addEventListener('click', fillDemoQuery);
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    document.getElementById('google-signin-gate')?.addEventListener('click', handleGoogleLogin);
    document.getElementById('fill-demo-admin').addEventListener('click', () => {
        document.getElementById('login-email').value = (state.authConfig && state.authConfig.demoAdminEmail) || 'admin@concordia.demo';
        document.getElementById('login-password').value = auth.DEMO_ADMIN_DEFAULT_PASSWORD;
        document.getElementById('login-password').focus();
        showToast('Demo admin credentials filled — click Sign in.');
    });
    document.getElementById('continue-guest').addEventListener('click', hideGate);
    document.getElementById('auth-action').addEventListener('click', handleAuthAction);
    document.addEventListener('click', event => {
        const mapButton = event.target.closest('[data-map-source]');
        if (mapButton) {
            state.currentSourceId = mapButton.dataset.mapSource;
            switchScreen('mapping');
            document.getElementById('mapping-source').value = state.currentSourceId;
            loadMappings();
        }
    });
}

async function refreshConnection() {
    const dot = document.getElementById('connection-dot');
    const label = document.getElementById('connection-label');
    try {
        await api.health();
        dot.className = 'status-light is-online';
        label.textContent = 'Services connected';
    } catch {
        dot.className = 'status-light is-offline';
        label.textContent = 'API unavailable';
    }
}

function switchScreen(name) {
    if (!screens[name]) return;
    showNavLoader();
    for (const [screenName, section] of Object.entries(screens)) {
        const active = screenName === name;
        section.hidden = !active;
        section.classList.toggle('active', active);
    }
    document.querySelectorAll('.nav-link').forEach(link => {
        const active = link.dataset.screen === name;
        link.classList.toggle('active', active);
        if (active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
    });
    if (name === 'dashboard') loadDashboard().finally(hideNavLoader);
    else if (name === 'sources') loadSources().finally(hideNavLoader);
    else if (name === 'mapping') loadMappingSources().finally(hideNavLoader);
    else hideNavLoader();
}

async function loadDashboard() {
    const [sourceResult, jobResult, entityResult, statsResult] = await Promise.allSettled([
        api.listSources(), api.listJobs(), api.listEntities(100), api.getGlobalStats(),
    ]);
    if (sourceResult.status === 'fulfilled') state.sources = sourceResult.value;
    const jobs = jobResult.status === 'fulfilled' ? jobResult.value : [];
    const entities = entityResult.status === 'fulfilled' ? entityResult.value : [];
    const recordCount = state.sources.reduce((sum, source) => sum + (source.total_records || 0), 0);
    const enrichedCount = entities.filter(entity => (entity.source_ids || []).length > 1).length;
    document.getElementById('stat-sources').textContent = formatNumber(state.sources.length);
    document.getElementById('stat-records').textContent = formatNumber(recordCount);
    document.getElementById('stat-entities').textContent = formatNumber(entities.length);
    document.getElementById('stat-enriched').textContent = formatNumber(enrichedCount);
    renderRecentSources(state.sources.slice(0, 6));
    renderJobs(jobs.slice(0, 5));
    if (statsResult.status === 'fulfilled') renderGlobalStats(statsResult.value);
    else renderGlobalStats(null);
}

async function loadGlobalStats() {
    const host = document.getElementById('global-stats');
    if (host)     host.innerHTML = loadingRow('Loading statistics');
    try {
        renderGlobalStats(await api.getGlobalStats());
    } catch {
        renderGlobalStats(null);
    }
}

function renderGlobalStats(stats) {
    const host = document.getElementById('global-stats');
    if (!host) return;
    if (!stats) {
        host.innerHTML = '<p class="empty-row">Statistics unavailable — check the API connection.</p>';
        return;
    }
    const cells = [
        ['Databases', stats.total_databases],
        ['Tables', stats.total_tables],
        ['Total records', stats.total_records],
        ['Records processed', stats.records_processed],
        ['Records matched', stats.records_matched],
        ['Master entities', stats.new_entities_created],
        ['Enriched (multi-source)', stats.entities_enriched],
        ['Duplicates in sample', stats.duplicate_records_detected],
        ['Unresolved records', stats.unresolved_records],
        ['Processing failures', stats.processing_failures],
        ['Last processed', stats.last_processed_time ? formatDate(stats.last_processed_time) : '—'],
    ];
    host.innerHTML = cells.map(([label, value]) => `<div class="stat-cell"><span>${escapeHtml(label)}</span><strong>${typeof value === 'number' ? formatNumber(value) : escapeHtml(value)}</strong></div>`).join('');
}

async function loadSources() {
    const table = document.getElementById('sources-table');
    table.innerHTML = loadingRow('Loading sources');
    try {
        state.sources = await api.listSources();
        document.getElementById('source-count-heading').textContent = `${state.sources.length} ${state.sources.length === 1 ? 'source' : 'sources'}`;
        renderSourcesTable(state.sources);
        renderMappingSourceOptions();
    } catch (error) {
        table.innerHTML = `<p class="empty-row">${escapeHtml(error.message)}. Check that the API and Firestore are available.</p>`;
    }
}

function renderRecentSources(items) {
    const host = document.getElementById('recent-sources');
    if (!items.length) {
        const fresh = state.user && !state.user.anonymous
            ? 'Your workspace is clean — no admin demo data here. Add your first dataset to populate these analytics.'
            : 'No sources yet. Add a dataset to get started.';
        host.innerHTML = `<p class="empty-row">${escapeHtml(fresh)}</p>`;
        return;
    }
    host.innerHTML = sourceTable(items, false);
}

function renderSourcesTable(items) {
    const host = document.getElementById('sources-table');
    if (!items.length) {
        host.innerHTML = '<div class="empty-state"><span class="empty-index">02</span><h2>No sources connected</h2><p>Add a CSV dataset to inspect its columns and begin resolving records.</p><button class="button button-dark" data-open-upload type="button">Add a source <span aria-hidden="true">+</span></button></div>';
        host.querySelector('[data-open-upload]').addEventListener('click', openUploadDialog);
        return;
    }
    host.innerHTML = sourceTable(items, true);
}

function sourceTable(items, actions) {
    const actionHeader = actions ? '<th>Next step</th>' : '';
    const rows = items.map(source => `<tr>
        <td class="source-name-cell"><strong>${escapeHtml(source.name)}</strong><small>${escapeHtml(source.filename || 'CSV dataset')}</small></td>
        <td><span class="count-inline">${formatNumber(source.total_records || 0)} rows</span></td>
        <td><span class="status-pill ${statusClass(source.status)}">${escapeHtml(source.status || 'UPLOADED')}</span></td>
        <td class="mono">${formatDate(source.updated_at || source.created_at)}</td>
        ${actions ? `<td><div class="source-row-actions"><button class="source-action" data-map-source="${escapeHtml(source.source_id)}" type="button">Review fields <span aria-hidden="true">→</span></button></div></td>` : ''}
    </tr>`).join('');
    return `<table class="data-table"><thead><tr><th>Source</th><th>Records</th><th>State</th><th>Updated</th>${actionHeader}</tr></thead><tbody>${rows}</tbody></table>`;
}

function renderJobs(jobs) {
    const host = document.getElementById('recent-jobs');
    if (!jobs.length) {
        host.innerHTML = '<p class="empty-row">Processing runs will appear here.</p>';
        return;
    }
    host.innerHTML = jobs.map(job => {
        const source = state.sources.find(item => item.source_id === job.source_id);
        const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
        return `<div class="job-item"><div><strong>${escapeHtml(source?.name || job.source_id)}</strong><small>${escapeHtml(job.job_type || 'Processing')} · ${formatDate(job.started_at || job.created_at)}</small></div><span class="status-pill ${statusClass(job.status)}">${escapeHtml(job.status)}</span><div class="job-progress"><span style="width:${progress}%"></span></div></div>`;
    }).join('');
}

function renderMappingSourceOptions() {
    const select = document.getElementById('mapping-source');
    const selected = state.currentSourceId || select.value;
    select.innerHTML = '<option value="">Select a dataset…</option>' + state.sources.map(source => `<option value="${escapeHtml(source.source_id)}">${escapeHtml(source.name)} · ${escapeHtml(source.filename)}</option>`).join('');
    if (selected && state.sources.some(source => source.source_id === selected)) select.value = selected;
}

async function loadMappingSources() {
    try {
        if (!state.sources.length) state.sources = await api.listSources();
        renderMappingSourceOptions();
        const select = document.getElementById('mapping-source');
        if (!select.value && state.sources.length) select.value = state.sources[0].source_id;
        state.currentSourceId = select.value || null;
        if (state.currentSourceId) await loadMappings();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function loadMappings() {
    const host = document.getElementById('mapping-content');
    const actions = document.getElementById('mapping-actions');
    const sourceId = state.currentSourceId;
    const requestId = ++state.mappingRequest;
    if (!state.currentSourceId) {
        host.innerHTML = '<div class="empty-state"><span class="empty-index">03</span><h2>Start with a dataset</h2><p>Choose an uploaded source to inspect its columns and review suggested fields.</p><button class="button button-outline" data-go="sources" type="button">Go to sources</button></div>';
        actions.hidden = true;
        return;
    }
    host.innerHTML = loadingRow('Inspecting fields');
    try {
        const response = await api.getMappingSuggestions(sourceId);
        if (requestId !== state.mappingRequest || sourceId !== state.currentSourceId) return;
        state.mappings = response.mappings.length ? response.mappings : response.suggested_mappings;
        document.getElementById('mapping-state').textContent = `${state.mappings.length} columns found`;
        host.innerHTML = `<table class="mapping-table"><thead><tr><th>Source column</th><th>Use as</th><th>Suggestion confidence</th></tr></thead><tbody>${state.mappings.map((mapping, index) => `<tr><td>${escapeHtml(mapping.source_column)}</td><td><select data-mapping-index="${index}" aria-label="Canonical field for ${escapeHtml(mapping.source_column)}">${canonicalFields.map(field => `<option value="${field}" ${mapping.canonical_field === field ? 'selected' : ''}>${field || 'Leave unmapped'}</option>`).join('')}</select></td><td class="confidence">${Math.round((mapping.confidence || 0) * 100)}%</td></tr>`).join('')}</tbody></table>`;
        actions.hidden = false;
        loadMappingInsights(sourceId);
    } catch (error) {
        if (requestId !== state.mappingRequest || sourceId !== state.currentSourceId) return;
        document.getElementById('mapping-state').textContent = 'Needs attention';
        host.innerHTML = `<p class="empty-row">${escapeHtml(error.message)}</p>`;
        actions.hidden = true;
    }
}

async function confirmAndProcess() {
    const button = document.getElementById('confirm-mapping');
    const sourceId = state.currentSourceId;
    const mappings = [...document.querySelectorAll('[data-mapping-index]')].map(select => ({
        ...state.mappings[Number(select.dataset.mappingIndex)],
        canonical_field: select.value,
        is_reviewed: true,
    }));
    if (!mappings.some(mapping => mapping.canonical_field)) {
        showToast('Choose at least one canonical field to process this source.', true);
        return;
    }
    button.disabled = true;
    button.textContent = 'Starting…';
    try {
        await api.confirmMapping(sourceId, mappings);
        const job = await api.startProcessing(sourceId);
        button.textContent = 'Processing…';
        showToast('Field review saved. Processing has started.');
        let finished = await waitForJob(job.job_id);
        if (finished.status !== 'COMPLETED') {
            try {
                const resumed = await api.resumeJob(job.job_id);
                showToast('Processing interrupted — resumed from checkpoint.');
                finished = await waitForJob(resumed.job_id || job.job_id);
            } catch { /* fall through to status message */ }
        }
        if (finished.status === 'COMPLETED') showToast('Source processing completed.');
        else showToast(finished.errors?.[0] || `Processing ${String(finished.status).toLowerCase()}.`, true);
        await loadSources();
        await loadDashboard();
        await loadMappings();
    } catch (error) {
        showToast(error.message, true);
    } finally {
        button.disabled = false;
        button.innerHTML = 'Confirm and process <span aria-hidden="true">→</span>';
    }
}

async function waitForJob(jobId) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
        const job = await api.getJobStatus(jobId);
        if (['COMPLETED', 'FAILED'].includes(job.status)) return job;
        await new Promise(resolve => setTimeout(resolve, 1200));
    }
    throw new Error('Processing is taking longer than expected. Check the source status shortly.');
}

async function loadMappingInsights(sourceId) {
    const host = document.getElementById('mapping-insights');
    if (!host) return;
    host.innerHTML = loadingRow('Loading tables and quality report');
    try {
        const [rels, profile] = await Promise.all([api.getRelationships(sourceId), api.getProfile(sourceId)]);
        const tables = (rels.tables || []).length ? rels.tables.map(t => `<li><code>${escapeHtml(t)}</code></li>`).join('') : '<li>No multi-table structure — single flat dataset.</li>';
        const edges = (rels.relationships || []).map(r => `<li><code>${escapeHtml(r.from_table)}.${escapeHtml(r.from_column)}</code> → <code>${escapeHtml(r.to_table)}.${escapeHtml(r.to_column)}</code> (${escapeHtml(r.kind)})</li>`).join('') || '<li>No shared identifiers detected across tables.</li>';
        const quality = profile.quality;
        const qcols = quality ? quality.columns.map(c => `<li><code>${escapeHtml(c.column)}</code> — ${(c.non_blank_rate * 100).toFixed(0)}% filled, ${c.distinct_values} distinct${c.malformed_values ? `, <strong>${c.malformed_values} malformed</strong>` : ''}</li>`).join('') : '<li>Quality report unavailable.</li>';
        host.innerHTML = `<div class="insight-box"><h3>Tables &amp; relationships</h3><ul>${tables}${edges}</ul>${profile.duplicate_of ? `<p class="duplicate-note">Duplicate of source ${escapeHtml(profile.duplicate_of)} — reprocessing will enrich, not duplicate, entities.</p>` : ''}</div><div class="insight-box"><h3>Quality report</h3><ul>${qcols}</ul></div>`;
    } catch (error) {
        host.innerHTML = `<p class="empty-row">${escapeHtml(error.message)}</p>`;
    }
}

function openUploadDialog() {
    document.getElementById('upload-error').hidden = true;
    document.getElementById('upload-dialog').showModal();
}

function closeUploadDialog() {
    document.getElementById('upload-dialog').close();
}

async function uploadSource(event) {
    event.preventDefault();
    const nameInput = document.getElementById('source-name');
    const fileInput = document.getElementById('source-file');
    const error = document.getElementById('upload-error');
    const submit = document.getElementById('submit-upload');
    const file = fileInput.files[0];
    const groupInput = document.getElementById('source-group');
    const partInput = document.getElementById('source-part');
    const lower = (file?.name || '').toLowerCase();
    if (!file || !(lower.endsWith('.csv') || lower.endsWith('.sql'))) {
        error.textContent = 'Choose a CSV or SQL dump (.sql) file to continue.';
        error.hidden = false;
        return;
    }
    if (file.size > 50 * 1024 * 1024) {
        error.textContent = 'This file is larger than the 50 MB upload limit.';
        error.hidden = false;
        return;
    }
    submit.disabled = true;
    submit.textContent = 'Uploading…';
    error.hidden = true;
    try {
        const payload = { name: nameInput.value.trim(), filename: file.name, type: lower.endsWith('.sql') ? 'sql' : 'csv' };
        if (groupInput && groupInput.value.trim()) payload.parent_group_id = groupInput.value.trim();
        if (partInput && partInput.value) payload.part_number = Number(partInput.value);
        const source = await api.createSource(payload);
        const uploadResult = await api.uploadFile(source.source_id, file);
        await api.inspectSchema(source.source_id, file);
        state.currentSourceId = source.source_id;
        closeUploadDialog();
        document.getElementById('upload-form').reset();
        await loadSources();
        switchScreen('mapping');
        document.getElementById('mapping-source').value = source.source_id;
        await loadMappings();
        showToast(uploadResult?.duplicate_of
            ? 'Source inspected. Note: identical content already exists — entities will not be duplicated.'
            : 'Source inspected. Review the suggested field mapping.');
    } catch (uploadError) {
        error.textContent = uploadError.message || 'The source could not be uploaded.';
        error.hidden = false;
    } finally {
        submit.disabled = false;
        submit.innerHTML = 'Inspect source <span aria-hidden="true">→</span>';
    }
}

function fillDemoQuery(event) {
    const query = event.currentTarget.dataset.query || 'john@example.com';
    document.getElementById('entity-query').value = query;
    searchEntity();
}

async function searchEntity() {
    const input = document.getElementById('entity-query');
    const button = document.getElementById('search-submit');
    const host = document.getElementById('search-result');
    const query = input.value.trim();
    if (!query) return;
    button.disabled = true;
    button.textContent = 'Following identifiers…';
    showNavLoader();
    host.innerHTML = `<div class="search-empty"><span class="search-rule"></span><p>Looking across connected records…${dots()}</p></div>`;
    try {
        const result = await api.searchEntity(query);
        renderSearchResult(result);
    } catch (error) {
        host.innerHTML = `<div class="not-found"><strong>Search could not complete</strong><p>${escapeHtml(error.message)}. Check that sources have been processed and the API is available.</p></div>`;
    } finally {
        button.disabled = false;
        button.innerHTML = 'Find record <span aria-hidden="true">→</span>';
        hideNavLoader();
    }
}

function renderSearchResult(result) {
    const host = document.getElementById('search-result');
    if (!result.entity) {
        host.innerHTML = '<div class="not-found"><strong>No matching entity found</strong><p>No indexed record contains that identifier yet. Add and process a source, then search again.</p></div>';
        return;
    }
    const entity = result.entity;
    const fields = ['name', 'email', 'phone', 'username', 'member_id', 'address', 'company'];
    const displayValue = field => entity[field]?.value || entity[field] || '';
    const name = displayValue('name') || displayValue('email') || displayValue('phone') || entity.entity_id;
    const populated = fields.filter(field => displayValue(field));
    const traces = populated.map(field => {
        const data = entity[field];
        const source = state.sources.find(item => item.source_id === data?.source_id);
        return `<div class="trace-item"><strong>${prettyField(field)}</strong><span>${escapeHtml(displayValue(field))}</span><small>${escapeHtml(source?.name || data?.source_id || 'Source not recorded')}${data?.source_field ? ` · ${escapeHtml(data.source_field)}` : ''}</small></div>`;
    }).join('');
    const steps = (result.enrichment_steps || []).map((step, index) => `<div class="enrichment-item"><span class="step-number">${index + 1}</span><div><strong>${escapeHtml(step.identifier_type)} found ${escapeHtml(step.source_name || 'in source')}</strong><small>${escapeHtml(step.identifier_value)}</small></div></div>`).join('');
    const sourceTags = (result.sources || []).map(source => `<span class="source-tag">${escapeHtml(source)}</span>`).join('');
    const fieldCards = fields.map(field => {
        const data = entity[field];
        const value = displayValue(field);
        const confidence = data && typeof data === 'object' && data.confidence != null ? `<span class="confidence-tag">${Math.round(data.confidence * 100)}%</span>` : '';
        const srcName = data && data.source_id ? (state.sources.find(source => source.source_id === data.source_id)?.name || data.source_id) : '';
        return `<div class="entity-field"><dt>${prettyField(field)}${confidence}</dt><dd>${value ? escapeHtml(value) : '<span class="mono">Not found</span>'}</dd>${srcName ? `<small>${escapeHtml(srcName)}${data.source_field ? ` · ${escapeHtml(data.source_field)}` : ''}</small>` : ''}</div>`;
    }).join('');
    host.innerHTML = `<article class="entity-result">
        <header class="entity-banner"><div><p class="eyebrow">UNIFIED PROFILE</p><h2>${escapeHtml(name)}</h2><p class="entity-count">${formatNumber(result.matched_records_count || 0)} linked records · ${(result.sources || []).length} sources</p></div><span class="entity-id">${escapeHtml(entity.entity_id)}</span></header>
        <dl class="entity-fields">${fieldCards}</dl>
        <div class="result-lower"><section class="result-section"><h3>Field provenance</h3><div class="trace-list">${traces || '<p class="empty-row">No source provenance available.</p>'}</div><div class="source-tags">${sourceTags}</div></section><section class="result-section"><h3>How the match grew</h3><div class="enrichment-list">${steps || '<p class="empty-row">No additional identifiers were discovered.</p>'}</div></section></div>
        <div class="result-lower"><section class="result-section"><h3>Relationship graph</h3><div class="graph-wrap" id="entity-graph">${loadingRow('Loading graph')}</div></section><section class="result-section"><h3>Entity timeline</h3><div class="timeline" id="entity-timeline">${loadingRow('Loading history')}</div></section></div>
    </article>`;
    loadEntityGraph(entity.entity_id);
    loadEntityTimeline(entity.entity_id);
}

function renderGraph(graph) {
    const nodes = graph.nodes || [];
    const edges = graph.edges || [];
    const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
    const lanes = { entity: 0, identifier: 1, source: 2 };
    const laneX = i => 90 + i * 220;
    const positions = {};
    const counters = { entity: 0, identifier: 0, source: 0 };
    nodes.forEach(n => {
        const lane = lanes[n.kind] ?? 1;
        positions[n.id] = { x: laneX(lane), y: 40 + (counters[n.kind] ?? 0) * 44 };
        counters[n.kind] = (counters[n.kind] ?? 0) + 1;
    });
    const height = Math.max(160, Math.max(...Object.values(positions).map(p => p.y), 0) + 50);
    const color = kind => (kind === 'entity' ? '#173b35' : kind === 'source' ? '#c76b50' : '#28584c');
    const lines = edges.filter(e => positions[e.from] && positions[e.to]).map(e =>
        `<line x1="${positions[e.from].x}" y1="${positions[e.from].y}" x2="${positions[e.to].x}" y2="${positions[e.to].y}" stroke="#cfd8d0" stroke-width="1.5"/>`).join('');
    const circles = nodes.map(n => {
        const p = positions[n.id];
        return `<g><circle cx="${p.x}" cy="${p.y}" r="13" fill="${color(n.kind)}"/><text x="${p.x + 20}" y="${p.y + 4}" class="graph-node" fill="#1e2926">${escapeHtml(String(n.label).slice(0, 34))}</text></g>`;
    }).join('');
    return `<svg viewBox="0 0 640 ${height}" role="img" aria-label="Entity relationship graph">${lines}${circles}</svg>`;
}

async function loadEntityGraph(entityId) {
    const host = document.getElementById('entity-graph');
    if (!host) return;
    try {
        host.innerHTML = renderGraph(await api.getEntityGraph(entityId));
    } catch (error) {
        host.innerHTML = `<p class="empty-row">${escapeHtml(error.message)}</p>`;
    }
}

async function loadEntityTimeline(entityId) {
    const host = document.getElementById('entity-timeline');
    if (!host) return;
    try {
        const { history } = await api.getEntityHistory(entityId);
        host.innerHTML = (history || []).map(item => `<div class="timeline-item"><span class="timeline-dot"></span><div><strong>${escapeHtml(item.event)}</strong><small>${escapeHtml(item.detail || '')}</small></div></div>`).join('') || '<p class="empty-row">No history yet.</p>';
    } catch (error) {
        host.innerHTML = `<p class="empty-row">${escapeHtml(error.message)}</p>`;
    }
}

function statusClass(status = '') {
    const value = String(status).toLowerCase();
    if (value === 'completed') return 'status-completed';
    if (value === 'failed') return 'status-failed';
    if (value === 'running' || value === 'pending') return `status-${value}`;
    return '';
}

function prettyField(field) {
    return field.replace('_', ' ');
}

function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value) || 0);
}

function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]);
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.classList.add('visible');
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove('visible'), 3600);
}