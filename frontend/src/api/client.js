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

/** Partial update of an existing record. */
export function patch(path, body, options) {
  return request(path, { ...options, method: 'PATCH', body })
}

/** Remove a record. Named `del` because `delete` is a reserved word. */
export function del(path, options) {
  return request(path, { ...options, method: 'DELETE' })
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

/**
 * Report a new incident.
 *
 * Only these five fields are sent. Status and reporter are set by the backend
 * from the verified token, and sending them would achieve nothing — see
 * backend/v1/app/domains/incidents.py.
 */
export function createIncident({
  title,
  description,
  category,
  priority,
  location,
  buildingId,
  floorId,
  seatId,
}) {
  return post('/incidents', {
    title,
    description,
    category,
    priority,
    location,
    // Building and floor are required by the API; the seat is optional and is
    // sent as null when no specific seat applies.
    building_id: buildingId,
    floor_id: floorId,
    seat_id: seatId,
  })
}

/**
 * Turn a filter object into a query string, dropping empty values so that
 * "no filter" and "filter for nothing" stay distinct.
 */
function withFilters(path, filters = {}) {
  const params = new URLSearchParams()

  for (const [key, value] of Object.entries(filters)) {
    if (value !== '' && value !== null && value !== undefined) {
      params.set(key, value)
    }
  }

  const query = params.toString()
  return query ? `${path}?${query}` : path
}

/**
 * List the incidents the signed-in user reported, newest first.
 *
 * Filters narrow the caller's own list. The backend applies its creator scope
 * first, so no filter here can reach another person's incidents.
 */
export function listIncidents(filters) {
  return get(withFilters('/incidents', filters))
}

/** Counts by status, priority and category for the caller's own reports. */
export function getMySummary() {
  return get('/incidents/summary')
}

/**
 * Fetch one incident. Returns 404 if it belongs to someone else, unless the
 * caller is a Facility Admin, who may open any incident.
 */
export function getIncident(id) {
  return get(`/incidents/${id}`)
}

/** An engineer's work queue: incidents assigned to them. Engineers only. */
export function listAssignedIncidents(filters) {
  return get(withFilters('/incidents/assigned', filters))
}

/** Counts for the signed-in engineer's own queue. Engineers only. */
export function getAssignedSummary() {
  return get('/incidents/assigned/summary')
}

/**
 * Change an incident's status, its assignee, or both.
 *
 * Only fields that are present are changed. Engineers may set a status on their
 * own assigned incidents; assignment is admin-only and re-validated server-side.
 */
export function updateIncident(id, changes) {
  return patch(`/incidents/${id}`, changes)
}

/**
 * Permanently remove an incident and its comments. Facility Admin only.
 *
 * Separate from setting the status to CLOSED: that records completed work,
 * this removes the record. The backend refuses every other role.
 */
export function deleteIncident(id) {
  return del(`/incidents/${id}`)
}

// --- Facility Admin only. The backend refuses these for other roles. ---

/**
 * Users who can be assigned work: active, role ENGINEER.
 *
 * Each row carries `is_available` and `active_count`, so the admin picks an
 * assignee with the workload in front of them.
 */
export function listEngineers() {
  return get('/engineers')
}

/** Mark an engineer available or unavailable for new work. Admin only. */
export function setEngineerAvailability(id, isAvailable) {
  return patch(`/users/${id}/availability`, { is_available: isAvailable })
}

// --- Facilities. Reads are open to everyone; writes are admin-only. ---

export function listBuildings() {
  return get('/buildings')
}

export function listFloors(buildingId) {
  return get(`/buildings/${buildingId}/floors`)
}

export function listSeats(floorId) {
  return get(`/floors/${floorId}/seats`)
}

export function createBuilding({ name, address }) {
  return post('/buildings', { name, address })
}

export function updateBuilding(id, changes) {
  return patch(`/buildings/${id}`, changes)
}

export function deleteBuilding(id) {
  return del(`/buildings/${id}`)
}

export function createFloor({ buildingId, name }) {
  return post('/floors', { building_id: buildingId, name })
}

export function updateFloor(id, name) {
  return patch(`/floors/${id}`, { name })
}

export function deleteFloor(id) {
  return del(`/floors/${id}`)
}

export function createSeat({ floorId, code }) {
  return post('/seats', { floor_id: floorId, code })
}

export function updateSeat(id, code) {
  return patch(`/seats/${id}`, { code })
}

export function deleteSeat(id) {
  return del(`/seats/${id}`)
}

/**
 * Read an incident's comments, oldest first.
 *
 * Open to whoever may see the incident — the reporter, the assigned engineer,
 * or an admin. Anyone else gets a 404, the same as for the incident itself.
 */
export function listComments(incidentId) {
  return get(`/incidents/${incidentId}/comments`)
}

/** Add a comment. Rejected with 403 once the incident is closed. */
export function createComment(incidentId, body) {
  return post(`/incidents/${incidentId}/comments`, { body })
}

/** Reword your own comment. The backend refuses anyone else's, admins included. */
export function updateComment(incidentId, commentId, body) {
  return patch(`/incidents/${incidentId}/comments/${commentId}`, { body })
}

/** Withdraw your own comment. */
export function deleteComment(incidentId, commentId) {
  return del(`/incidents/${incidentId}/comments/${commentId}`)
}

/**
 * Ask for your own incident to be treated as more urgent.
 *
 * Deliberately not a priority change: the reporter states a case and an admin
 * decides. Only the reporter may call it, and only while the ticket is live.
 */
export function requestEscalation(incidentId, reason) {
  return post(`/incidents/${incidentId}/escalation`, { reason })
}

/** Mark an escalation as handled. Facility Admin only; the reason is kept. */
export function acknowledgeEscalation(incidentId) {
  return del(`/incidents/${incidentId}/escalation`)
}

/**
 * Every incident in the organisation, newest first, with reporter details.
 *
 * Filters are optional and combine with AND. Empty values are dropped rather
 * than sent as blanks, so "no filter" and "filter for nothing" stay distinct.
 * Filtering runs in the database, so the browser never receives rows it hides.
 */
export function listAllIncidents(filters) {
  return get(withFilters('/admin/incidents', filters))
}

/** Incident totals by status, category and building. Facility Admin only. */
export function getAnalytics() {
  return get('/admin/analytics')
}

/** Every user account. */
export function listUsers() {
  return get('/users')
}

/**
 * Promote an employee to engineer, or demote one back.
 *
 * Only EMPLOYEE and ENGINEER are accepted; the backend rejects FACILITY_ADMIN.
 */
export function setUserRole(id, role) {
  return patch(`/users/${id}/role`, { role })
}

// Shown in the status page so it is obvious which backend the site is calling.
export const apiBaseUrl = `${API_BASE}${API_PREFIX}`
