/**
 * The single place the frontend talks to the backend. No component calls
 * `fetch` directly, so concerns that apply to every request — base URL, JSON
 * encoding, error shape, and the auth token — are handled once. Attaching the
 * token in particular must never be forgotten, so no individual call decides it.
 *
 * The base URL is not hardcoded: Terraform outputs the deployed API address and
 * bin/generate-env.sh writes it as VITE_API_URL. Vite only exposes variables
 * with that prefix to browser code, which keeps server-side secrets out of the
 * bundle.
 *
 * Locally VITE_API_URL points at bin/proxy-server.js on :3001 (a workshop
 * helper that works around a CORS bug in the local AWS emulator); on AWS it is
 * the CloudFront address. The two differ in whether the "/api/v1" prefix
 * survives to the Lambda, which the backend router normalises — see
 * backend/v1/app/router.py.
 *
 * Token storage: kept in a module variable and mirrored to localStorage so a
 * page refresh does not sign the user out. localStorage is readable by any
 * script on the page, so an XSS bug could steal it; an httpOnly cookie would be
 * safer but needs CSRF handling and awkward cross-origin configuration through
 * CloudFront to a Lambda Function URL. Acceptable for a short-lived workshop
 * token, worth revisiting for real employee data.
 */

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:3001').replace(/\/$/, '')
const API_PREFIX = '/api/v1'
const TOKEN_STORAGE_KEY = 'acme.auth.token'

// Browsers throw on storage access in private mode or with site data blocked,
// and an exception here would stop the app booting.
let authToken = null
try {
  authToken = localStorage.getItem(TOKEN_STORAGE_KEY)
} catch {
  authToken = null
}

/** Store or clear the token, keeping the in-memory and persisted copies in step. */
export function setAuthToken(token) {
  authToken = token
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {
    // Storage unavailable; the in-memory copy still works for this tab.
  }
}

export function getAuthToken() {
  return authToken
}

/**
 * Thrown when the backend replies with a failure status. Components branch on
 * `status` and `code` — a 401 sends the user to login, a 400 shows inline.
 */
export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const url = `${API_BASE}${API_PREFIX}${path}`
  const headers = { 'Content-Type': 'application/json' }

  if (auth && authToken) {
    headers.Authorization = `Bearer ${authToken}`
  }

  const options = { method, headers }
  if (body !== undefined) {
    options.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(url, options)
  } catch {
    // fetch only rejects when the request never completed — offline, DNS
    // failure, blocked. A 404 or 500 is a successful round trip and is handled
    // below; conflating the two is a common source of misleading errors.
    throw new ApiError(
      'Could not reach the server. Check your connection and try again.',
      0,
      'network_error',
    )
  }

  if (response.status === 204) {
    return null
  }

  // A crashing server or a proxy can return an HTML error page; we would
  // rather report the status than mask it behind a JSON parse error.
  let payload
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    // Clearing the token here, where every response passes, prevents the app
    // looping on a credential the server has already rejected.
    if (response.status === 401) {
      setAuthToken(null)
    }

    throw new ApiError(
      payload?.message || `Request failed with status ${response.status}.`,
      response.status,
      payload?.error || 'unknown_error',
      payload?.details,
    )
  }

  return payload
}

export function get(path, options) {
  return request(path, { ...options, method: 'GET' })
}

export function post(path, body, options) {
  return request(path, { ...options, method: 'POST', body })
}

// Named helpers per endpoint so URLs live in one file.

/** Create an account. The backend always assigns the EMPLOYEE role. */
export function register({ fullName, email, password }) {
  // auth: false — no token yet, and sending a stale one could only confuse.
  return post('/auth/register', { full_name: fullName, email, password }, { auth: false })
}

export function login({ email, password }) {
  return post('/auth/login', { email, password }, { auth: false })
}

/** Turn a stored token back into a user, and confirm it is still valid. */
export function getMe() {
  return get('/auth/me')
}

export function getHealth() {
  return get('/health', { auth: false })
}

// Shown in the status page so it is obvious which backend the site is calling.
export const apiBaseUrl = `${API_BASE}${API_PREFIX}`
