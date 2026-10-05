// Dedicated login / signup page. On success → workspace (app.html).
// Already signed in → skip straight through.
import api from './api.js?v=5';
import * as auth from './auth.js?v=3';

const state = { mode: 'signin', config: null };

document.addEventListener('DOMContentLoaded', initialize);

async function initialize() {
    api.setAuthProvider(() => auth.ensureToken());
    bindTabs();
    document.getElementById('auth-form').addEventListener('submit', handleSubmit);
    document.getElementById('fill-demo-admin').addEventListener('click', () => {
        setMode('signin');
        document.getElementById('auth-email').value = (state.config && state.config.demoAdminEmail) || 'admin@concordia.demo';
        document.getElementById('auth-password').value = auth.DEMO_ADMIN_DEFAULT_PASSWORD;
    });
    document.getElementById('continue-guest').addEventListener('click', () => {
        window.location.href = '/app.html';
    });

    try {
        const line = document.getElementById('wake-status');
        const text = document.getElementById('wake-text');
        const submit = document.getElementById('auth-submit');
        line.hidden = false;
        text.textContent = 'Contacting the backend — about 30 seconds if it was idle.';
        submit.disabled = true;
        const ready = await api.warmup({});
        line.hidden = true;
        submit.disabled = false;
        if (!ready) {
            fail('The backend is not responding. Reload the page to retry.');
            return;
        }
        state.config = await auth.getPublicConfig();
    } catch {
        fail('The API is unreachable. Start the backend, then reload this page.');
        return;
    }
    if (!state.config.requireAuth) {
        document.getElementById('continue-guest').hidden = false;
    }
    if (auth.getSession()?.idToken) {
        try {
            const me = await api.getMe();
            if (!me.anonymous) {
                window.location.href = '/app.html';
                return;
            }
        } catch {
            // Stale session — stay on the login page
        }
    }
}

function bindTabs() {
    document.getElementById('tab-signin').addEventListener('click', () => setMode('signin'));
    document.getElementById('tab-signup').addEventListener('click', () => setMode('signup'));
}

function setMode(mode) {
    state.mode = mode;
    const signin = mode === 'signin';
    document.getElementById('tab-signin').classList.toggle('active', signin);
    document.getElementById('tab-signup').classList.toggle('active', !signin);
    document.getElementById('tab-signin').setAttribute('aria-selected', String(signin));
    document.getElementById('tab-signup').setAttribute('aria-selected', String(!signin));
    document.getElementById('auth-title').textContent = signin ? 'Sign in' : 'Create account';
    document.getElementById('auth-subtitle').textContent = signin
        ? 'Welcome back. Your sources and entities are waiting.'
        : 'One account for sources, mappings, and unified search.';
    document.getElementById('auth-submit').innerHTML = `${signin ? 'Sign in' : 'Create account'} <span aria-hidden="true">→</span>`;
    document.getElementById('confirm-wrap').hidden = signin;
    document.getElementById('auth-password').setAttribute('autocomplete', signin ? 'current-password' : 'new-password');
    document.getElementById('auth-error').hidden = true;
}

async function handleSubmit(event) {
    event.preventDefault();
    const error = document.getElementById('auth-error');
    const submit = document.getElementById('auth-submit');
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value;
    error.hidden = true;
    if (state.mode === 'signup') {
        const confirm = document.getElementById('auth-confirm').value;
        if (password.length < 6) return fail('Password must be at least 6 characters.');
        if (password !== confirm) return fail('Passwords do not match.');
    }
    submit.disabled = true;
    try {
        if (state.mode === 'signin') await auth.signIn(email, password);
        else await auth.signUp(email, password);
        window.location.href = '/app.html';
    } catch (err) {
        fail(err.message);
    } finally {
        submit.disabled = false;
    }
}

function fail(message) {
    const error = document.getElementById('auth-error');
    error.textContent = message;
    error.hidden = false;
}
