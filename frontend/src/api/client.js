/**
 * =============================================================================
 * THE SINGLE PLACE THE FRONT END TALKS TO THE BACKEND
 * =============================================================================
 * Every network call in this application goes through this file. No React
 * component ever calls `fetch` directly.
 *
 * Centralising it means that concerns which apply to EVERY request — the server
 * address, JSON encoding, error handling, and later the login token — are
 * written once here instead of being repeated and gradually diverging in a
 * dozen components.
 *
 * =============================================================================
 * WHERE THE SERVER ADDRESS COMES FROM
 * =============================================================================
 * The address is not written into the code, because it is different in every
 * environment and is not known until after deployment.
 *
 * The chain that produces it:
 *
 *   1. Terraform deploys the backend and outputs the public URL.
 *   2. The script bin/generate-env.sh reads that output and writes
 *      frontend/.env.local containing a line like:
 *          VITE_API_URL=https://d1234abcd.cloudfront.net
 *   3. Vite, the build tool, reads that file and makes the value available in
 *      code as `import.meta.env.VITE_API_URL`.
 *
 * The `VITE_` prefix is required by Vite: only variables with that prefix are
 * exposed to browser code. This is a safety feature. Anything sent to the
 * browser is readable by anyone who opens developer tools, so the prefix forces
 * a deliberate decision and prevents secrets such as database passwords from
 * being bundled into the JavaScript by accident.
 *
 * =============================================================================
 * THE SAME REQUEST TAKES TWO DIFFERENT ROUTES
 * =============================================================================
 * We always ask for the same path, "/api/v1/health", but what happens next
 * depends on where the app is running:
 *
 *   ON A LAPTOP    VITE_API_URL is http://localhost:3001, which is a small
 *                  proxy script the workshop provides (bin/proxy-server.js).
 *                  It exists because the local AWS emulator has a bug that
 *                  makes browsers reject its responses on cross-origin
 *                  grounds. The proxy forwards the call and attaches the
 *                  headers the browser needs. It also STRIPS the "/api/v1"
 *                  prefix before forwarding.
 *
 *   ON AWS         VITE_API_URL is the CloudFront address. CloudFront sees the
 *                  "/api/v1" prefix, recognises it as an API call rather than
 *                  a request for a page, and forwards it to the Lambda —
 *                  KEEPING the prefix.
 *
 * That difference in the prefix is invisible here, because the backend router
 * removes the prefix if present. See the long explanation in
 * backend/v1/app/router.py.
 */

// Fall back to the local proxy address when the variable is missing, which
// happens if a developer runs `npm run dev` before the backend has ever been
// deployed. Without the fallback the app would try to call the Vite dev server
// itself and fail confusingly.
//
// The `replace` strips a trailing slash so that joining the base and the path
// can never produce a doubled "//", which some servers treat as a different
// and non-existent URL.
const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:3001').replace(/\/$/, '')

// Every endpoint in this backend lives under this prefix. Declared once so a
// future "/api/v2" is a one-line change rather than a search across the app.
const API_PREFIX = '/api/v1'

/**
 * Error thrown when the backend replies with a failure status.
 *
 * A custom class rather than a plain Error so that components can inspect the
 * `status` and `code` fields to decide what to do — for example, send the user
 * to the login page on a 401, but show an inline message on a 400.
 */
export class ApiError extends Error {
  constructor(message, status, code) {
    super(message)
    this.name = 'ApiError'
    this.status = status // HTTP status number, e.g. 404
    this.code = code // our own short label, e.g. "not_found"
  }
}

/**
 * Send a request to the backend and return the parsed response.
 *
 * This is the low-level function that `get` and `post` below build on.
 *
 * @param {string} path   Endpoint path WITHOUT the prefix, e.g. "/health".
 * @param {object} options
 * @param {string} [options.method='GET']  HTTP method.
 * @param {object} [options.body]          Value to send as JSON. Omit for GET.
 * @returns {Promise<any>}  The decoded response body, or null for a 204.
 * @throws {ApiError}  When the server replies with a status of 400 or above,
 *                     or when the network is unreachable.
 */
async function request(path, { method = 'GET', body } = {}) {
  const url = `${API_BASE}${API_PREFIX}${path}`

  const options = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }

  // A GET request must not carry a body. Only attach one when there is
  // something to send, and convert it to text here so callers can pass an
  // ordinary JavaScript object.
  if (body !== undefined) {
    options.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(url, options)
  } catch {
    // `fetch` only rejects when the request never completed at all — the
    // server is unreachable, the device is offline, or the browser blocked it.
    // A 404 or 500 does NOT land here; those are successful round trips that
    // happen to carry a failure status, and are handled below. Conflating the
    // two is a very common bug, which is why they are separated explicitly.
    throw new ApiError(
      'Could not reach the server. Check your connection and try again.',
      0,
      'network_error',
    )
  }

  // 204 means "it worked, and there is deliberately no content". Trying to
  // parse an empty body as JSON would throw, so return early.
  if (response.status === 204) {
    return null
  }

  // Read the body defensively. A crashing server or a misconfigured proxy can
  // return an HTML error page, which would break JSON parsing. We would rather
  // report the status code than mask it with a parsing error.
  let payload
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  // `response.ok` is true for any status in the 200–299 range.
  if (!response.ok) {
    // The backend sends failures as {error, message}; see
    // backend/v1/app/errors.py. If it did not (a proxy or CloudFront error
    // page, say), fall back to a generic message rather than showing the user
    // "undefined".
    throw new ApiError(
      payload?.message || `Request failed with status ${response.status}.`,
      response.status,
      payload?.error || 'unknown_error',
    )
  }

  return payload
}

/** Fetch data from the backend. */
export function get(path) {
  return request(path, { method: 'GET' })
}

/** Send data to the backend to create something. */
export function post(path, body) {
  return request(path, { method: 'POST', body })
}

/**
 * Ask the backend whether it is healthy and connected to its database.
 *
 * @returns {Promise<{ok: boolean, database: string, environment: string,
 *                    schema_version: number}>}
 */
export function getHealth() {
  return get('/health')
}

// Exported so the UI can display which server it is talking to. Useful when
// demonstrating the project, to prove the deployed site is calling the real
// cloud backend rather than something running locally.
export const apiBaseUrl = `${API_BASE}${API_PREFIX}`
