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
import DeleteIcon from '@mui/icons-material/Delete'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'

import {
  acknowledgeEscalation,
  deleteIncident,
  getIncident,
  listEngineers,
  requestEscalation,
  updateIncident,
} from '../api/client'
import useAuth from '../auth/useAuth'
import CommentThread from '../components/CommentThread'
import WorkflowStepper from '../components/WorkflowStepper'
import { isLocationArchived, locationPath } from '../facilities'
import {
  ADMIN_SETTABLE,
  ENGINEER_SETTABLE,
  PRIORITIES,
  STATUS_BLOCKED,
  STATUS_CLOSED,
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
  const navigate = useNavigate()

  const [status, setStatus] = useState('loading')
  const [incident, setIncident] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  const [engineers, setEngineers] = useState([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [toast, setToast] = useState('')

  const [blockedReason, setBlockedReason] = useState('')
  const [pendingStatus, setPendingStatus] = useState('')
  const [escalationReason, setEscalationReason] = useState('')
  const [escalating, setEscalating] = useState(false)
  const [escalationError, setEscalationError] = useState('')

  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

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

  /** Ask for this incident — the caller's own report — to be treated as urgent. */
  async function handleEscalate() {
    const reason = escalationReason.trim()
    if (!reason || escalating) {
      return
    }

    setEscalating(true)
    setEscalationError('')

    try {
      const data = await requestEscalation(id, reason)
      setIncident(data.incident)
      setEscalationReason('')
      setToast('Escalation requested. A Facility Admin will review it.')
    } catch (error) {
      setEscalationError(error.message)
    } finally {
      setEscalating(false)
    }
  }

  /** Mark the escalation handled. The reason stays on the record. */
  async function handleAcknowledge() {
    setSaving(true)
    try {
      const data = await acknowledgeEscalation(id)
      setIncident(data.incident)
      setToast('Escalation marked as handled.')
    } catch (error) {
      setSaveError(error.message)
    } finally {
      setSaving(false)
    }
  }

  /**
   * Change the status, collecting a reason first when moving to BLOCKED.
   *
   * The API requires one, so the control asks for it rather than letting the
   * user discover the rule through a rejection.
   */
  function handleStatusChange(next) {
    if (next === STATUS_BLOCKED) {
      setPendingStatus(next)
      return
    }
    save({ status: next }, 'Status updated.')
  }

  function confirmBlock() {
    const reason = blockedReason.trim()
    if (!reason) {
      return
    }
    save({ status: STATUS_BLOCKED, blocked_reason: reason }, 'Status updated.')
    setPendingStatus('')
    setBlockedReason('')
  }

  /**
   * Delete the incident, then leave — the page it is showing no longer exists.
   *
   * The success message is handed to the destination through router state,
   * since a Snackbar here would unmount with this component on navigation.
   */
  async function handleDelete() {
    setDeleting(true)
    setDeleteError('')

    try {
      await deleteIncident(id)
      navigate('/admin/incidents', {
        replace: true,
        state: { notice: `Incident #${id} and its comments were deleted.` },
      })
    } catch (error) {
      // Close the dialog so the failure is visible behind it, on the page.
      setDeleteError(error.message)
      setConfirmingDelete(false)
      setDeleting(false)
    }
  }

  // An engineer may only work incidents assigned to them; an admin, any.
  const canChangeStatus =
    incident && (isAdmin || (isEngineer && incident.assignee_id === user.id))

  // CLOSED is an admin's acceptance of the work, so it is absent from the
  // engineer's options. The backend rejects it too.
  const settableStatuses = isAdmin ? ADMIN_SETTABLE : ENGINEER_SETTABLE

  // Escalation is the reporter's voice, and only while the ticket is live.
  const isReporter = incident && incident.created_by === user.id
  const canEscalate =
    incident && !['RESOLVED', STATUS_CLOSED].includes(incident.status)

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
                {locationPath(incident) || <em>Not specified</em>}
                {/* The structured references are gone but the snapshot taken at
                    report time still describes where the problem was. */}
                {isLocationArchived(incident) && (
                  <Typography variant="caption" color="text.secondary" display="block">
                    This location has since been removed from the facility list.
                  </Typography>
                )}
              </DetailRow>
              {/* Only when there is a structured location above it — otherwise
                  locationPath already fell back to this same free text. */}
              {incident.location && (incident.building_name || incident.location_snapshot) && (
                <DetailRow label="Details">{incident.location}</DetailRow>
              )}
              <DetailRow label="Priority">
                <Chip
                  size="small"
                  variant="outlined"
                  label={priorityDisplay(incident.priority).label}
                  color={priorityDisplay(incident.priority).color}
                />
              </DetailRow>
              {incident.status === STATUS_BLOCKED && incident.blocked_reason && (
                <DetailRow label="Blocked because">{incident.blocked_reason}</DetailRow>
              )}
              {incident.escalation_requested && (
                <DetailRow label="Escalation">
                  <Chip size="small" color="error" label="Escalation requested" />
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    {incident.escalation_reason}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Requested {formatDateTime(incident.escalated_at)}
                  </Typography>
                </DetailRow>
              )}
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
                        onChange={(event) => handleStatusChange(event.target.value)}
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
                    {isAdmin && (
                      <TextField
                        select
                        size="small"
                        label="Priority"
                        value={incident.priority}
                        disabled={saving}
                        sx={{ minWidth: 180 }}
                        onChange={(event) =>
                          save({ priority: event.target.value }, 'Priority updated.')
                        }
                        helperText="Only an admin can re-prioritise"
                      >
                        {PRIORITIES.map((priority) => (
                          <MenuItem key={priority.value} value={priority.value}>
                            {priority.label}
                          </MenuItem>
                        ))}
                      </TextField>
                    )}
                  </Stack>

                  {/* Asked for up front, because the API requires a reason and
                      a rejection afterwards would lose what was typed. */}
                  {pendingStatus === STATUS_BLOCKED && (
                    <Stack spacing={1} sx={{ mt: 2 }}>
                      <TextField
                        fullWidth
                        size="small"
                        label="Why is this blocked?"
                        value={blockedReason}
                        disabled={saving}
                        onChange={(event) => setBlockedReason(event.target.value)}
                      />
                      <Stack direction="row" spacing={1}>
                        <Button
                          size="small"
                          variant="contained"
                          onClick={confirmBlock}
                          disabled={saving || !blockedReason.trim()}
                        >
                          Mark blocked
                        </Button>
                        <Button
                          size="small"
                          onClick={() => {
                            setPendingStatus('')
                            setBlockedReason('')
                          }}
                        >
                          Cancel
                        </Button>
                      </Stack>
                    </Stack>
                  )}

                  {isAdmin && incident.escalation_requested && (
                    <Alert
                      severity="warning"
                      sx={{ mt: 2 }}
                      action={
                        <Button color="inherit" size="small" onClick={handleAcknowledge}
                                disabled={saving}>
                          Mark handled
                        </Button>
                      }
                    >
                      The reporter asked for this to be escalated.
                    </Alert>
                  )}
                </Box>
              </>
            )}

            {/* The reporter's half of escalation: state a case, an admin decides.
                Hidden once the ticket is finished, which the API also enforces. */}
            {isReporter && !incident.escalation_requested && canEscalate && (
              <>
                <Divider />
                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    Need this looked at sooner?
                  </Typography>

                  {escalationError && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                      {escalationError}
                    </Alert>
                  )}

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    <TextField
                      fullWidth
                      size="small"
                      label="Why is this urgent?"
                      value={escalationReason}
                      disabled={escalating}
                      onChange={(event) => setEscalationReason(event.target.value)}
                    />
                    <Button
                      variant="outlined"
                      color="warning"
                      onClick={handleEscalate}
                      disabled={escalating || !escalationReason.trim()}
                      sx={{ flexShrink: 0 }}
                    >
                      {escalating ? 'Sending…' : 'Request escalation'}
                    </Button>
                  </Stack>
                </Box>
              </>
            )}

            {isReporter && incident.escalation_requested && (
              <>
                <Divider />
                <Alert severity="info">
                  Your escalation request is with a Facility Admin.
                </Alert>
              </>
            )}

            <Divider />

            {/* Reads the status from the loaded incident rather than its own
                copy, so closing or reopening above hides or restores the box
                immediately. */}
            <CommentThread
              incidentId={incident.id}
              isClosed={incident.status === STATUS_CLOSED}
            />

            {/* Admin only, and separated from the controls above because it is
                not a workflow step: closing records finished work, this removes
                the record. Hiding it is a courtesy — the API is the authority
                and refuses every other role. */}
            {isAdmin && (
              <>
                <Divider />
                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    Danger zone
                  </Typography>

                  {deleteError && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                      {deleteError}
                    </Alert>
                  )}

                  <Stack
                    direction={{ xs: 'column', sm: 'row' }}
                    spacing={2}
                    alignItems={{ sm: 'center' }}
                  >
                    <Button
                      variant="outlined"
                      color="error"
                      startIcon={<DeleteIcon />}
                      onClick={() => setConfirmingDelete(true)}
                    >
                      Delete incident
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                      Permanently removes this incident and its comments.
                    </Typography>
                  </Stack>
                </Box>
              </>
            )}
          </Stack>
        </Paper>
      )}

      <Dialog
        open={confirmingDelete}
        onClose={() => (deleting ? null : setConfirmingDelete(false))}
        aria-labelledby="delete-incident-title"
      >
        <DialogTitle id="delete-incident-title">Delete incident?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will permanently delete this incident and its comments. This action cannot
            be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmingDelete(false)} disabled={deleting}>
            Cancel
          </Button>
          <Button onClick={handleDelete} color="error" variant="contained" disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete incident'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={Boolean(toast)}
        autoHideDuration={4000}
        onClose={() => setToast('')}
        message={toast}
      />
    </Stack>
  )
}
