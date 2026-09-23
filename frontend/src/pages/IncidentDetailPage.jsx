/**
 * Incident Details — one incident, read-only for this slice.
 *
 * A 404 here means either "no such incident" or "it belongs to someone else";
 * the API deliberately does not distinguish the two, so this page shows the
 * same message for both.
 */

import { useEffect, useState } from 'react'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import { Link as RouterLink, useParams } from 'react-router-dom'

import { getIncident } from '../api/client'
import { categoryLabel, formatDateTime, priorityDisplay, statusDisplay } from '../incidents'

function DetailRow({ label, children }) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={{ xs: 0.5, sm: 2 }}
      sx={{ py: 1.5 }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 140 }}>
        {label}
      </Typography>
      <Box sx={{ wordBreak: 'break-word' }}>{children}</Box>
    </Stack>
  )
}

export default function IncidentDetailPage() {
  // The :id segment from the route. It is a string, and is sent to the API as
  // given — the backend validates it rather than the browser.
  const { id } = useParams()

  const [status, setStatus] = useState('loading')
  const [incident, setIncident] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await getIncident(id)
        if (!ignore) {
          setIncident(data.incident)
          setStatus('success')
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(
            error.status === 404
              ? 'That incident does not exist, or you do not have access to it.'
              : error.message,
          )
          setStatus('error')
        }
      }
    }

    load()

    return () => {
      ignore = true
    }
  }, [id])

  return (
    <Stack spacing={3}>
      <Box>
        <Button
          startIcon={<ArrowBackIcon />}
          component={RouterLink}
          to="/incidents"
          sx={{ mb: 1 }}
        >
          Back to my incidents
        </Button>
      </Box>

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status === 'error' && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'success' && incident && (
        <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
          <Stack spacing={2}>
            <Box>
              <Typography variant="h5" component="h2" gutterBottom>
                {incident.title}
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip
                  size="small"
                  label={statusDisplay(incident.status).label}
                  color={statusDisplay(incident.status).color}
                />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${priorityDisplay(incident.priority).label} priority`}
                  color={priorityDisplay(incident.priority).color}
                />
                <Chip size="small" variant="outlined" label={categoryLabel(incident.category)} />
              </Stack>
            </Box>

            <Divider />

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Description
              </Typography>
              {/* pre-wrap keeps the line breaks the reporter typed; without it
                  a multi-paragraph description collapses into one block. */}
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {incident.description}
              </Typography>
            </Box>

            <Divider />

            <Box>
              <DetailRow label="Reference">#{incident.id}</DetailRow>
              {/* Present for everyone, though it only tells an admin something
                  they did not already know — an employee is always their own
                  reporter. Keeping one response shape avoids a second page. */}
              <DetailRow label="Reported by">
                {incident.reporter_name}
                <Typography variant="caption" color="text.secondary" display="block">
                  {incident.reporter_email}
                </Typography>
              </DetailRow>
              <DetailRow label="Location">
                {incident.location || <em>Not specified</em>}
              </DetailRow>
              <DetailRow label="Reported">{formatDateTime(incident.created_at)}</DetailRow>
              <DetailRow label="Last updated">{formatDateTime(incident.updated_at)}</DetailRow>
            </Box>
          </Stack>
        </Paper>
      )}
    </Stack>
  )
}
