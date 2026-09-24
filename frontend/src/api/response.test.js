/**
 * Regression tests for the response contract, run with `npm test`.
 *
 * The bug these exist for: opening Assigned Incidents with no filters ("Any
 * Status") failed with `can't access property "incidents", ... is null`. The
 * request had come back 200 with an HTML body — CloudFront's SPA fallback
 * rewrites 403 and 404 into a 200 serving index.html, and that applies to
 * /api/v1 as well — and the client turned the unparseable body into null and
 * returned it as though it were data. The page then read `.incidents` off null.
 *
 * So the rule under test is: a success either carries a JSON object or it is
 * not a success.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiError, readResponse } from './response.js'

const INDEX_HTML = `<!doctype html>
<html lang="en"><head><title>ACME Facilities</title></head><body><div id="root"></div></body></html>`

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

test('a 200 carrying the SPA shell is an error, never null', async () => {
  const response = new Response(INDEX_HTML, {
    status: 200,
    headers: { 'Content-Type': 'text/html' },
  })

  // The old behaviour resolved to null here, which is what reached the page.
  await assert.rejects(() => readResponse(response), ApiError)
})

test('the SPA-shell 200 reports itself as an invalid response', async () => {
  const response = new Response(INDEX_HTML, {
    status: 200,
    headers: { 'Content-Type': 'text/html' },
  })

  await assert.rejects(
    () => readResponse(response),
    (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.code, 'invalid_response')
      assert.equal(error.status, 200)
      return true
    },
  )
})

test('an unfiltered list with results is returned unchanged', async () => {
  const response = json({ incidents: [{ id: 1 }, { id: 2 }] })

  const data = await readResponse(response)

  assert.deepEqual(data.incidents, [{ id: 1 }, { id: 2 }])
})

test('an empty queue is an empty array, not null', async () => {
  const response = json({ incidents: [] })

  const data = await readResponse(response)

  // The page reads `.incidents` directly, so this must never be null.
  assert.deepEqual(data.incidents, [])
  assert.equal(data.incidents.length, 0)
})

test('a 200 whose body is literally null is an error', async () => {
  const response = json(null)

  await assert.rejects(() => readResponse(response), ApiError)
})

test('204 still means no content, for the endpoints that delete', async () => {
  const response = new Response(null, { status: 204 })

  assert.equal(await readResponse(response), null)
})

test('a real API error keeps its status and the server message', async () => {
  const response = json({ error: 'forbidden', message: 'Engineers only.' }, 403)

  await assert.rejects(
    () => readResponse(response),
    (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.status, 403)
      assert.equal(error.code, 'forbidden')
      assert.equal(error.message, 'Engineers only.')
      return true
    },
  )
})

test('an error with an unreadable body still reports its status', async () => {
  const response = new Response(INDEX_HTML, {
    status: 502,
    headers: { 'Content-Type': 'text/html' },
  })

  await assert.rejects(
    () => readResponse(response),
    (error) => {
      assert.equal(error.status, 502)
      assert.match(error.message, /502/)
      return true
    },
  )
})
