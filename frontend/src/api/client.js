/**
 * =============================================================================
 * THE SINGLE PLACE THE FRONT END TALKS TO THE BACKEND
 * =============================================================================
 * Every network call in this application goes through this file. No React
 * component ever calls `fetch` directly.
 *
 * Centralising it means that concerns which apply to EVERY request — the server
 * address, JSON encoding, error handling, and the login token — are written
 * once here instead of being repeated and gradually diverging across a dozen
 * components. Attaching the token in particular is something that must never be
 * forgotten on an individual call, so no individual call gets to decide.
 *
 * =============================================================================
 * WHERE THE SERVER ADDRESS COMES FROM
 * =============================================================================
 * The address is not written into the code, because it is different in every
 * environment and is not known until after deployment.
 *
 *   1. Terraform deploys the backend and outputs the public URL.
 *   2. bin/generate-env.sh (or bin/deploy-frontend.sh) writes it out as
 *          VITE_API_URL=https://d1234abcd.cloudfront.net
 *   3. Vite exposes it in code as `import.meta.env.VITE_API_URL`.
 *
 * The `VITE_` prefix is required by Vite: only variables with that prefix reach
 * browser code. That is a safety feature — anything sent to the browser is
 * readable by anyone who opens developer tools — and it stops a database
 * password being bundled into the JavaScript by accident.
 *
 * =============================================================================
 * THE SAME REQUEST TAKES TWO DIFFERENT ROUTES
 * =============================================================================
 * We always ask for the same path, e.g. "/api/v1/auth/login", but:
 *
 *   ON A LAPTOP    VITE_API_URL is http://localhost:3001, a small proxy the
 *                  workshop provides (bin/proxy-server.js). It exists because
 *                  the local AWS emulator has a CORS bug. It STRIPS the
 *                  "/api/v1" prefix before forwarding.
 *
 *   ON AWS         VITE_API_URL is the CloudFront address. CloudFront routes
 *                  "/api/v1*" to the Lambda, KEEPING the prefix.
 *
 * That difference is invisible here because the backend router removes the
 * prefix if present — see backend/v1/app/router.py.
 *
 * =============================================================================
 * HOW THE LOGIN TOKEN IS HANDLED
 * =============================================================================
 * After signing in, the backend gives us a signed token (a JWT). Every later
 * request must carry it in an `Authorization: Bearer ...` header, or the server
 * treats the caller as anonymous and replies 401.
 *
 * The token is held in a module variable for speed and mirrored into
 * `localStorage` so that refreshing the page does not sign the user out.
 *
 * STORAGE TRADEOFF, STATED PLAINLY: `localStorage` is readable by any
 * JavaScript running on the page, so a cross-site-scripting bug could steal the
 * token. The more secure alternative is an httpOnly cookie, which JavaScript
 * cannot read — but cookies would then need CSRF protection, and getting them
 * sent correctly across the CloudFront-to-Lambda-Function-URL boundary is
 * awkward. For a workshop application with a short-lived token, localStorage is
 * the reasonable choice; a production system handling real employee data should
 * revisit it.
 */

// Fall back to the local proxy address when the variable is missing, which
// happens if a developer runs `npm run dev` before the backend has ever been
// deployed. The `replace` strips a trailing slash so joining cannot produce a
// doubled "//", which some servers treat as a different, non-existent URL.
const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:3001').replace(/\/$/, '')

// Every endpoint in this backend lives under this prefix. Declared once so a
// future "/api/v2" is a one-line change.
const API_PREFIX = '/api/v1'

// The key under which the token is kept in the browser's local storage.
const TOKEN_STORAGE_KEY = 'acme.auth.token'

/**
 * In-memory copy of the token, so the common case does not touch localStorage.
 *
 * Initialised from storage on load. The try/catch is not paranoia: browsers
 * throw on storage access in private-browsing modes and when cookies are
 * blocked, and an exception here would stop the entire application booting.
 */
let authToken = null
try {
  authToken = localStorage.getItem(TOKEN_STORAGE_KEY)
} catch {
  authToken = null
}

/**
 * Store or clear the token.
 *
 * Called by the auth provider after a successful login, and with `null` on
 * logout. Keeping both copies in step is the whole reason this is a function
 * rather than two separate assignments scattered around the app.
 *
 * @param {string|null} token
 */
export function setAuthToken(token) {
  authToken = token
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {
    // Storage unavailable. The in-memory copy still works for this tab, so the
    // user stays signed in until they close it — degraded, but not broken.
  }
}

/** Return the current token, or null when signed out. */
export function getAuthToken() {
  return authToken
}

/**
 * Error thrown when the backend replies with a failure status.
 *
 * A custom class rather than a plain Error so components can inspect `status`
 * and `code` and react differently — send the user to the login page on a 401,
 * but show an inline message on a 400.
 */
export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message)
    this.name = 'ApiError'
    this.status = status // HTTP status number, e.g. 404
    this.code = code // our own short label, e.g. "validation_error"
    this.details = details // optional, e.g. which form field was wrong
  }
}

/**
 * Send a request to the backend and return the parsed response.
 *
 * @param {string} path   Endpoint path WITHOUT the prefix, e.g. "/auth/login".
 * @param {object} options
 * @param {string} [options.method='GET']
 * @param {object} [options.body]        Value to send as JSON.
 * @param {boolean} [options.auth=true]  Attach the token when we have one.
 * @returns {Promise<any>}  The decoded body, or null for a 204.
 * @throws {ApiError}
 */
async function request(path, { method = 'GET', body, auth = true } = {}) {
  const url = `${API_BASE}${API_PREFIX}${path}`

  const headers = { 'Content-Type': 'application/json' }

  // "Bearer" is the HTTP standard scheme for token authentication: whoever
  // holds (bears) the token may use it. The backend parses this same format in
  // security.authenticate_request.
  if (auth && authToken) {
    headers.Authorization = `Bearer ${authToken}`
  }

  const options = { method, headers }

  // A GET must not carry a body. Only attach one when there is something to
  // send, converting here so callers can pass a plain object.
  if (body !== undefined) {
    options.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(url, options)
  } catch {
    // `fetch` only rejects when the request never completed — offline, DNS
    // failure, or blocked by the browser. A 404 or 500 does NOT land here;
    // those are successful round trips carrying a failure status, handled
    // below. Conflating the two is a very common bug.
    throw new ApiError(
      'Could not reach the server. Check your connection and try again.',
      0,
      'network_error',
    )
  }

  // 204 means "it worked, and there is deliberately no content".
  if (response.status === 204) {
    return null
  }

  // Read defensively. A crashing server or a misconfigured proxy can return an
  // HTML error page, and we would rather report the status code than mask it
  // behind a JSON parsing error.
  let payload
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    // A 401 means the token is missing, expired, or no longer accepted — for
    // example because the account was deactivated. Clearing it here, in the one
    // place every response passes through, guarantees the app cannot get stuck
    // in a loop retrying with a credential the server has already rejected.
    if (response.status === 401) {
      setAuthToken(null)
    }

    // The backend sends failures as {error, message, details}; see
    // backend/v1/app/errors.py. Fall back to a generic message if something
    // else (a proxy, a CloudFront error page) replied instead.
    throw new ApiError(
      payload?.message || `Request failed with status ${response.status}.`,
      response.status,
      payload?.error || 'unknown_error',
      payload?.details,
    )
  }

  return payload
}

/** Fetch data from the backend. */
export function get(path, options) {
  return request(path, { ...options, method: 'GET' })
}

/** Send data to the backend to create something. */
export function post(path, body, options) {
  return request(path, { ...options, method: 'POST', body })
}

// ---------------------------------------------------------------------------
// Endpoint helpers
// ---------------------------------------------------------------------------
// Named functions per endpoint, rather than components assembling URL strings
// themselves. If a path changes, it changes here and nowhere else.

/**
 * Create a new account. The backend always assigns the EMPLOYEE role.
 *
 * `auth: false` because the caller has no token yet — and sending a stale one
 * from a previous session could only confuse matters.
 *
 * @returns {Promise<{token: string, user: object}>}
 */
export function register({ fullName, email, password }) {
  return post('/auth/register', { full_name: fullName, email, password }, { auth: false })
}

/**
 * Exchange an email and password for a token.
 *
 * @returns {Promise<{token: string, user: object}>}
 */
export function login({ email, password }) {
  return post('/auth/login', { email, password }, { auth: false })
}

/**
 * Ask the backend who the current token belongs to.
 *
 * Used on page load to turn a stored token back into a name and role, and as
 * the check that the token is still valid.
 *
 * @returns {Promise<{user: object}>}
 */
export function getMe() {
  return get('/auth/me')
}

/**
 * Report whether the backend is healthy and connected to its database.
 *
 * @returns {Promise<{ok: boolean, database: string, environment: string,
 *                    schema_version: number}>}
 */
export function getHealth() {
  return get('/health', { auth: false })
}

// Exported so the UI can display which server it is talking to — useful when
// demonstrating the project, to prove the deployed site is calling the real
// cloud backend rather than something running locally.
export const apiBaseUrl = `${API_BASE}${API_PREFIX}`
