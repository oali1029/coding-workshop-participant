/**
 * Turning one fetch Response into data, or into an ApiError.
 *
 * Kept out of client.js so it can be imported by `node --test`: client.js reads
 * Vite's `import.meta.env` at module scope, which only exists inside a Vite
 * build. This is also the single place that decides what counts as a usable
 * response, which is the rule every page depends on.
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

/**
 * Read a successful response's body, or throw an ApiError explaining why not.
 *
 * Returns null only for 204, the one status that legitimately carries no
 * content. Every other success resolves to the parsed JSON object.
 */
export async function readResponse(response) {
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
    throw new ApiError(
      payload?.message || `Request failed with status ${response.status}.`,
      response.status,
      payload?.error || 'unknown_error',
      payload?.details,
    )
  }

  // A 2xx carrying no readable JSON is not a usable success, and on AWS that is
  // a real case rather than a theoretical one: CloudFront's SPA fallback
  // rewrites 403 and 404 into a 200 serving index.html, and it applies to
  // /api/v1 too, so a genuine API error arrives here looking like a successful
  // request with an HTML body. Returning null would hand that to callers as if
  // it were data, and the failure would surface later and somewhere else — as
  // "can't access property 'incidents', ... is null" on the page that asked.
  // Every endpoint that succeeds with content answers with a JSON object, so
  // anything else is reported here, where the cause is still visible.
  if (payload === null || typeof payload !== 'object') {
    throw new ApiError(
      'The server returned an unreadable response. Please try again.',
      response.status,
      'invalid_response',
    )
  }

  return payload
}
