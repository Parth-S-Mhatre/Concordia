// Firebase Authentication client (REST, no SDK needed for email/password).
// Google sign-in uses the Firebase JS SDK (loaded on demand); the backend
// verifies ID tokens with the Admin SDK and serves the public config.
import api from './api.js?v=5';

const SESSION_KEY = 'cg_auth';
// Default demo-admin password (seed_admin.py). If DEMO_ADMIN_PASSWORD was
// changed in .env, type it manually instead of using the fill button.
export const DEMO_ADMIN_DEFAULT_PASSWORD = 'Concordia-Admin-2026';

let cachedConfig = null;

export async function getPublicConfig() {
    if (!cachedConfig) cachedConfig = await api.getPublicConfig();
    return cachedConfig;
}

function readSession() {
    try {
        return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null');
    } catch {
        return null;
    }
}

function writeSession(session) {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
}

export function getSession() {
    return readSession();
}

function friendlyError(code) {
    const map = {
        EMAIL_NOT_FOUND: 'No account found for that email.',
        INVALID_PASSWORD: 'Incorrect password.',
        INVALID_LOGIN_CREDENTIALS: 'Invalid email or password.',
        USER_DISABLED: 'This account has been disabled.',
        OPERATION_NOT_ALLOWED: 'Email/password sign-in is not enabled in the Firebase console.',
    };
    return map[code] || 'Sign-in failed. Check the details and try again.';
}

export async function signIn(email, password) {
    const config = await getPublicConfig();
    if (!config.apiKey) throw new Error('Auth is not configured (FIREBASE_API_KEY missing on server).');
    const response = await fetch(
        `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${config.apiKey}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, returnSecureToken: true }),
        }
    );
    const data = await response.json();
    if (!response.ok) throw new Error(friendlyError(data?.error?.message));
    writeSession({
        idToken: data.idToken,
        refreshToken: data.refreshToken,
        expiresAt: Date.now() + Number(data.expiresIn || 3600) * 1000,
        email: data.email,
    });
    return data;
}

export async function signUp(email, password) {
    const config = await getPublicConfig();
    if (!config.apiKey) throw new Error('Auth is not configured (FIREBASE_API_KEY missing on server).');
    const response = await fetch(
        `https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${config.apiKey}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, returnSecureToken: true }),
        }
    );
    const data = await response.json();
    if (!response.ok) {
        const map = {
            EMAIL_EXISTS: 'An account with this email already exists. Sign in instead.',
            OPERATION_NOT_ALLOWED: 'Email/password sign-up is not enabled in the Firebase console.',
            WEAK_PASSWORD: 'Password must be at least 6 characters.',
        };
        throw new Error(map[data?.error?.message] || 'Sign-up failed. Check the details and try again.');
    }
    writeSession({
        idToken: data.idToken,
        refreshToken: data.refreshToken,
        expiresAt: Date.now() + Number(data.expiresIn || 3600) * 1000,
        email: data.email,
    });
    return data;
}

export async function refreshSession() {
    const session = readSession();
    const config = await getPublicConfig();
    if (!session?.refreshToken) throw new Error('Session expired. Sign in again.');
    const response = await fetch(`https://securetoken.googleapis.com/v1/token?key=${config.apiKey}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grant_type: 'refresh_token', refresh_token: session.refreshToken }),
    });
    const data = await response.json();
    if (!response.ok) {
        writeSession(null);
        throw new Error('Session expired. Sign in again.');
    }
    const updated = {
        ...session,
        idToken: data.id_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + Number(data.expires_in || 3600) * 1000,
    };
    writeSession(updated);
    return updated;
}

/** Valid token for the Authorization header, refreshing 5 min before expiry. */
export async function ensureToken() {
    const session = readSession();
    if (!session?.idToken) return null;
    if (Date.now() < (session.expiresAt || 0) - 5 * 60 * 1000) return session.idToken;
    try {
        const updated = await refreshSession();
        return updated.idToken;
    } catch {
        return null;
    }
}

export function signOut() {
    writeSession(null);
    try {
        if (window.firebase?.auth) window.firebase.auth().signOut().catch(() => {});
    } catch { /* noop */ }
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        if (document.querySelector(`script[src="${src}"]`)) return resolve();
        const s = document.createElement('script');
        s.src = src;
        s.async = true;
        s.onload = resolve;
        s.onerror = () => reject(new Error('Could not load Google sign-in. Check your connection and retry.'));
        document.head.appendChild(s);
    });
}

let firebaseReady = null;

async function ensureFirebase() {
    if (window.firebase?.apps?.length) return window.firebase;
    if (!firebaseReady) {
        firebaseReady = (async () => {
            await loadScript('https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js');
            await loadScript('https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js');
            const config = await getPublicConfig();
            if (!config.apiKey || !config.projectId) {
                throw new Error('Auth is not configured (FIREBASE_API_KEY missing on server).');
            }
            const appConfig = {
                apiKey: config.apiKey,
                authDomain: config.authDomain || `${config.projectId}.firebaseapp.com`,
                projectId: config.projectId,
            };
            window.firebase.initializeApp(appConfig);
            return window.firebase;
        })();
    }
    return firebaseReady;
}

/** Google sign-in via Firebase popup. Creates a fresh per-user workspace on first login. */
export async function signInWithGoogle() {
    const firebase = await ensureFirebase();
    const auth = firebase.auth();
    const provider = new firebase.auth.GoogleAuthProvider();
    provider.setCustomParameters({ prompt: 'select_account' });
    let result;
    try {
        result = await auth.signInWithPopup(provider);
    } catch (err) {
        const code = err?.code || '';
        if (code === 'auth/popup-blocked') throw new Error('Pop-up was blocked. Allow pop-ups for this site and try again.');
        if (code === 'auth/cancelled-popup-request' || code === 'auth/popup-closed-by-user') throw new Error('Google sign-in was cancelled.');
        if (code === 'auth/operation-not-allowed') throw new Error('Google sign-in is not enabled in the Firebase console (Authentication → Sign-in method → Google).');
        if (code === 'auth/unauthorized-domain') throw new Error('This domain is not authorized in Firebase console → Authentication → Settings → Authorized domains.');
        throw new Error(err?.message || 'Google sign-in failed. Try again.');
    }
    const idToken = await result.user.getIdToken();
    writeSession({
        idToken,
        refreshToken: result.user.refreshToken || null,
        expiresAt: Date.now() + 55 * 60 * 1000,
        email: result.user.email || null,
        provider: 'google',
    });
    return result.user;
}
