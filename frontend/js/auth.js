// Firebase Authentication client (REST, no SDK needed).
// Sign-in uses IdentityToolkit; refresh uses SecureToken; the backend
// verifies ID tokens with the Admin SDK and serves the public config.
import api from './api.js?v=3';

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
}
