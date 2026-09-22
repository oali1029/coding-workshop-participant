/**
 * The system status page — Slice 0's health check, preserved.
 *
 * This was the whole application in Slice 0. Now that there is a real product
 * behind a login, it has moved off the landing screen to /status, reachable
 * from the icon in the toolbar.
 *
 * IT IS STILL WORTH KEEPING. It is the fastest way to answer "is the deployment
 * actually working?", and it is the only screen that reports which environment
 * and which database the app is talking to. When something breaks after a
 * deploy, this is the first place to look:
 *
 *   - page will not load at all   -> the S3/CloudFront front end is broken
 *   - page loads, status errors   -> the Lambda or its database is broken
 *   - environment says "local"    -> the build picked up the wrong API address
 *
 * THE THREE STATES OF ANY SCREEN THAT LOADS DATA
 * Network calls take time and can fail, so every data-loading screen in this
 * project handles all three cases explicitly rather than showing a blank panel:
 *
 *   LOADING   request in flight  -> spinner
 *   ERROR     request failed     -> explain, and offer to retry
 *   SUCCESS   data arrived       -> show it
 */

import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material'

import { apiBaseUrl, getHealth } from '../api/client'

/**
 * One labelled line of information, e.g. "Environment: aws".
 *
 * Extracted because it is used four times below. Reusing it keeps the rows
 * visually identical and is the habit that prevents duplicated markup later.
 */
function DetailRow({ label, children }) {
  return (
    <Stack
      // Stack label above value on a phone so long text is not squeezed into a
      // sliver; side by side once there is room.
      direction={{ xs: 'column', sm: 'row' }}
      spacing={{ xs: 0.5, sm: 2 }}
      sx={{ py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
        {label}
      </Typography>
      {/* `wordBreak` stops the long PostgreSQL version string forcing the page
          wider than a phone screen and causing sideways scrolling. */}
      <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
        {children}
      </Typography>
    </Stack>
  )
}

export default function StatusPage() {
  const [status, setStatus] = useState('loading')
  const [health, setHealth] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  // Incremented by "Try again". The effect below depends on it, so changing it
  // is what re-runs the request. This indirection keeps all network access
  // inside the effect, where React manages its lifecycle.
  const [reloadToken, setReloadToken] = useState(0)

  /**
   * Fetch the health status when the page opens, and whenever retried.
   *
   * The `ignore` flag is a cleanup guard: if the user navigates away while the
   * request is still travelling, the late response must not write to state for
   * a component that no longer exists.
   */
  useEffect(() => {
    let ignore = false

    async function loadHealth() {
      try {
        const data = await getHealth()
        if (!ignore) {
          setHealth(data)
          setStatus('success')
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error.message)
          setStatus('error')
        }
      }
    }

    loadHealth()

    return () => {
      ignore = true
    }
  }, [reloadToken])

  const retry = useCallback(() => {
    setStatus('loading')
    setReloadToken((token) => token + 1)
  }, [])

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          System status
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Confirms that this web application can reach its backend service, and
          that the backend can reach its database.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
        {status === 'loading' && (
          <Stack alignItems="center" spacing={2} sx={{ py: 4 }}>
            <CircularProgress />
            <Typography variant="body2" color="text.secondary">
              Contacting the backend service...
            </Typography>
          </Stack>
        )}

        {status === 'error' && (
          <Stack spacing={2}>
            <Alert severity="error">
              <strong>Could not reach the backend.</strong> {errorMessage}
            </Alert>
            <Typography variant="caption" color="text.secondary">
              Tried: {apiBaseUrl}/health
            </Typography>
            <Box>
              <Button variant="contained" onClick={retry}>
                Try again
              </Button>
            </Box>
          </Stack>
        )}

        {status === 'success' && health && (
          <Stack spacing={0}>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
              <Chip label="Operational" color="success" size="small" />
              <Typography variant="body2" color="text.secondary">
                All checks passed
              </Typography>
            </Stack>

            <DetailRow label="Environment">
              {health.environment === 'aws' ? 'AWS (deployed)' : 'Local development'}
            </DetailRow>

            {/* Proof the Lambda genuinely queried PostgreSQL. On AWS this
                string mentions Aurora, Amazon's managed PostgreSQL. */}
            <DetailRow label="Database">{health.database}</DetailRow>

            {/* Which migration has been applied. A deployment that failed to
                update the schema would show an older number here. */}
            <DetailRow label="Schema version">{health.schema_version}</DetailRow>

            <DetailRow label="API address">{apiBaseUrl}</DetailRow>
          </Stack>
        )}
      </Paper>
    </Stack>
  )
}
