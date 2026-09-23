/**
 * Incident Details — one incident, plus the controls the signed-in role may use.
 *
 * A 404 means "no such incident" *or* "you have no claim on it"; the API does
 * not distinguish them, so neither does this page.
 *
 * Who sees which controls:
 *   Employee   read-only, even on their own report
 *   Engineer   status control, only on incidents assigned to them, and never CLOSED
 *   Admin      status control on any incident, plus the assignee picker
 *
 * These are conveniences. The API re-checks every rule, so hiding a control only
 * spares the user a refusal they could not have acted on anyway.
 */

import { useCallback, useEffect, useState } from 'react'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink, useParams } from 'react-router-dom'

import { getIncident, listEngineers, updateIncident } from '../api/client'
import useAuth from '../auth/useAuth'
import WorkflowStepper from '../components/WorkflowStepper'
import {
  ADMIN_SETTABLE,
  ENGINEER_SETTABLE,
  categoryLabel,
  formatDateTime,
  priorityDisplay,
  statusDisplay,
} from '../incidents'
import { ROLE_ENGINEER, ROLE_FACILITY_ADMIN } from '../roles'

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
  const { id } = useParams()
  const { user } = useAuth()

  const [status, setStatus] = useState('loading')
  const [incident, setIncident] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  const [engineers, setEngineers] = useState([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [toast, setToast] = useState('')

  const isAdmin = user.role === ROLE_FACILITY_ADMIN
  const isEngineer = user.role === ROLE_ENGINEER

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

  // Only admins can assign, so only admins need the list of engineers.
  useEffect(() => {
    if (!isAdmin) {
      return undefined
    }

    let ignore = false

    async function loadEngineers() {
      try {
        const data = await listEngineers()
        if (!ignore) {
          setEngineers(data.engineers)
        }
      } catch {
        // Not fatal: the rest of the page still works, the picker is just empty.
      }
    }

    loadEngineers()

    return () => {
      ignore = true
    }
  }, [isAdmin])

  /**
   * Send a change and replace the incident with the server's version.
   *
   * We render what came back rather than what we sent, so the page always shows
   * what was actually stored — including fields the server derived, like
   * assignee_name and updated_at.
   */
  const save = useCallback(
    async (changes, message) => {
      setSaving(true)
      setSaveError('')

      try {
        const data = await updateIncident(id, changes)
        setIncident(data.incident)
        setToast(message)
      } catch (error) {
        setSaveError(error.message)
      } finally {
        setSaving(false)
      }
    },
    [id],
  )

  // An engineer may only work incidents assigned to them; an admin, any.
  const canChangeStatus =
    incident && (isAdmin || (isEngineer && incident.assignee_id === user.id))

  // CLOSED is an admin's acceptance of the work, so it is absent from the
  // engineer's options. The backend rejects it too.
  const settableStatuses = isAdmin ? ADMIN_SETTABLE : ENGINEER_SETTABLE

  return (
    <Stack spacing={3}>
      <Box>
        <Button
          startIcon={<ArrowBackIcon />}
          component={RouterLink}
          to={isAdmin ? '/admin/incidents' : '/incidents'}
          sx={{ mb: 1 }}
        >
          {isAdmin ? 'Back to all incidents' : 'Back to my incidents'}
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

            <WorkflowStepper status={incident.status} />

            <Divider />

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Description
              </Typography>
              {/* pre-wrap keeps the line breaks the reporter typed. */}
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {incident.description}
              </Typography>
            </Box>

            <Divider />

            <Box>
              <DetailRow label="Reference">#{incident.id}</DetailRow>
              <DetailRow label="Reported by">
                {incident.reporter_name}
                <Typography variant="caption" color="text.secondary" display="block">
                  {incident.reporter_email}
                </Typography>
              </DetailRow>
              <DetailRow label="Assigned to">
                {incident.assignee_name ? (
                  <>
                    {incident.assignee_name}
                    <Typography variant="caption" color="text.secondary" display="block">
                      {incident.assignee_email}
                    </Typography>
                  </>
                ) : (
                  <em>Unassigned</em>
                )}
              </DetailRow>
              <DetailRow label="Location">
                {incident.location || <em>Not specified</em>}
              </DetailRow>
              <DetailRow label="Reported">{formatDateTime(incident.created_at)}</DetailRow>
              <DetailRow label="Last updated">{formatDateTime(incident.updated_at)}</DetailRow>
            </Box>

            {(canChangeStatus || isAdmin) && (
              <>
                <Divider />
                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    Update this incident
                  </Typography>

                  {saveError && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                      {saveError}
                    </Alert>
                  )}

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    {canChangeStatus && (
                      <TextField
                        select
                        size="small"
                        label="Status"
                        value={incident.status}
                        disabled={saving}
                        sx={{ minWidth: 220 }}
                        onChange={(event) =>
                          save({ status: event.target.value }, 'Status updated.')
                        }
                      >
                        {/* A closed incident keeps CLOSED visible in its own
                            dropdown even for an engineer, so the current value
                            renders — though they cannot reach this control on a
                            closed ticket anyway. */}
                        {settableStatuses.map((value) => (
                          <MenuItem key={value} value={value}>
                            {statusDisplay(value).label}
                          </MenuItem>
                        ))}
                      </TextField>
                    )}

                    {isAdmin && (
                      <TextField
                        select
                        size="small"
                        label="Assigned engineer"
                        value={incident.assignee_id ?? ''}
                        disabled={saving}
                        sx={{ minWidth: 240 }}
                        onChange={(event) =>
                          save(
                            { assignee_id: event.target.value === '' ? null : event.target.value },
                            event.target.value === '' ? 'Incident unassigned.' : 'Incident assigned.',
                          )
                        }
                        helperText="Only engineers can be assigned"
                      >
                        <MenuItem value="">
                          <em>Unassigned</em>
                        </MenuItem>
                        {engineers.map((engineer) => (
                          <MenuItem key={engineer.id} value={engineer.id}>
                            {engineer.full_name}
                          </MenuItem>
                        ))}
                      </TextField>
                    )}
                  </Stack>
                </Box>
              </>
            )}
          </Stack>
        </Paper>
      )}

      <Snackbar
        open={Boolean(toast)}
        autoHideDuration={4000}
        onClose={() => setToast('')}
        message={toast}
      />
    </Stack>
  )
}
