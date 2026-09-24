/**
 * System status — the Slice 0 health check, now reached from the toolbar.
 *
 * Still the quickest way to diagnose a bad deployment:
 *   page will not load      -> S3/CloudFront is broken
 *   page loads, status errors -> the Lambda or its database is broken
 *   environment says "local"  -> the build picked up the wrong API address
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

function DetailRow({ label, children }) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={{ xs: 0.5, sm: 2 }}
      sx={{ py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
        {label}
      </Typography>
      {/* Stops the long PostgreSQL version string forcing horizontal scroll. */}
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

  // Changing this re-runs the effect, which keeps the request inside the effect
  // rather than firing it from the retry handler.
  const [reloadToken, setReloadToken] = useState(0)

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
          <Stack spacing={2} sx={{ alignItems: 'center', py: 4 }}>
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
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 2 }}>
              <Chip label="Operational" color="success" size="small" />
              <Typography variant="body2" color="text.secondary">
                All checks passed
              </Typography>
            </Stack>

            <DetailRow label="Environment">
              {health.environment === 'aws' ? 'AWS (deployed)' : 'Local development'}
            </DetailRow>

            {/* Mentions Aurora when genuinely deployed. */}
            <DetailRow label="Database">{health.database}</DetailRow>

            {/* Lags behind if a deployment failed to migrate. */}
            <DetailRow label="Schema version">{health.schema_version}</DetailRow>

            <DetailRow label="API address">{apiBaseUrl}</DetailRow>
          </Stack>
        )}
      </Paper>
    </Stack>
  )
}
