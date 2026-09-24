/**
 * Users — the Facility Admin's team management page.
 *
 * This is how an ENGINEER comes to exist: registration always creates an
 * employee, so someone has to promote them. Without this page nothing could be
 * assigned to an engineer in a later slice.
 *
 * Administrator accounts appear in the list but their role cannot be changed
 * here, matching the backend rule.
 */

import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useMediaQuery } from 'react-responsive'

import { listUsers, setEngineerAvailability, setUserRole } from '../api/client'
import useAuth from '../auth/useAuth'
import { MANAGEABLE_ROLES, ROLE_ENGINEER, ROLE_LABELS, roleLabel } from '../roles'

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth()

  const [status, setStatus] = useState('loading')
  const [users, setUsers] = useState([])
  const [errorMessage, setErrorMessage] = useState('')

  // Id of the row currently being saved, so only that dropdown is disabled
  // rather than the whole table.
  const [savingId, setSavingId] = useState(null)
  const [toast, setToast] = useState('')

  const isCompact = useMediaQuery({ maxWidth: 800 })

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listUsers()
        if (!ignore) {
          setUsers(data.users)
          setStatus('success')
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error.message)
          setStatus('error')
        }
      }
    }

    load()

    return () => {
      ignore = true
    }
  }, [])

  async function handleRoleChange(targetUser, role) {
    setSavingId(targetUser.id)
    setErrorMessage('')

    try {
      const { user: updated, incidents_unassigned: released } = await setUserRole(
        targetUser.id,
        role,
      )

      // Replace just the changed row rather than refetching the whole list —
      // the server's response is the authoritative new state.
      setUsers((previous) =>
        previous.map((entry) => (entry.id === updated.id ? updated : entry)),
      )

      // Demotion releases their live work, which is a consequence worth
      // reporting rather than leaving the admin to discover in the queue.
      setToast(
        released > 0
          ? `${updated.full_name} is now ${roleLabel(updated.role)}. `
            + `${released} active ${released === 1 ? 'incident' : 'incidents'} unassigned.`
          : `${updated.full_name} is now ${roleLabel(updated.role)}.`,
      )
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setSavingId(null)
    }
  }

  /**
   * Mark an engineer available or unavailable for new work.
   *
   * Unavailable does not move their existing tickets — reassigning someone's
   * queue the moment they go on leave would lose the context they have on each
   * one. The assignment endpoint simply refuses to give them anything new.
   */
  async function handleAvailabilityChange(targetUser, isAvailable) {
    setSavingId(targetUser.id)
    setErrorMessage('')

    try {
      const { user: updated } = await setEngineerAvailability(targetUser.id, isAvailable)

      setUsers((previous) =>
        previous.map((entry) => (entry.id === updated.id ? updated : entry)),
      )
      setToast(
        `${updated.full_name} is now ${updated.is_available ? 'available' : 'unavailable'}.`,
      )
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setSavingId(null)
    }
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Users
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Promote an employee to engineer so incidents can be assigned to them, and
          mark engineers unavailable while they are away.
        </Typography>
      </Box>

      {errorMessage && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'loading' && (
        <Stack sx={{ alignItems: 'center', py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status === 'success' && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                {!isCompact && <TableCell>Email</TableCell>}
                <TableCell>Role</TableCell>
                <TableCell>Availability</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((entry) => {
                // Administrators, including the signed-in one, are read-only
                // here. The backend enforces this too; the dropdown is simply
                // not offered for a change that would be refused.
                const canChangeRole = MANAGEABLE_ROLES.includes(entry.role)

                return (
                  <TableRow key={entry.id} hover>
                    <TableCell>
                      <Typography variant="body2">
                        {entry.full_name}
                        {entry.id === currentUser.id && (
                          <Chip size="small" label="You" sx={{ ml: 1 }} />
                        )}
                      </Typography>
                      {isCompact && (
                        <Typography variant="caption" color="text.secondary">
                          {entry.email}
                        </Typography>
                      )}
                    </TableCell>
                    {!isCompact && <TableCell>{entry.email}</TableCell>}
                    <TableCell sx={{ minWidth: 160 }}>
                      {canChangeRole ? (
                        <TextField
                          select
                          size="small"
                          fullWidth
                          value={entry.role}
                          disabled={savingId === entry.id}
                          onChange={(event) => handleRoleChange(entry, event.target.value)}
                        >
                          {MANAGEABLE_ROLES.map((role) => (
                            <MenuItem key={role} value={role}>
                              {ROLE_LABELS[role]}
                            </MenuItem>
                          ))}
                        </TextField>
                      ) : (
                        <Chip size="small" label={roleLabel(entry.role)} color="primary" />
                      )}
                    </TableCell>
                    <TableCell sx={{ minWidth: 150 }}>
                      {/* Only engineers can hold work, so only engineers have an
                          availability setting; the backend refuses it for anyone
                          else. */}
                      {entry.role === ROLE_ENGINEER ? (
                        <FormControlLabel
                          control={
                            <Switch
                              size="small"
                              checked={entry.is_available}
                              disabled={savingId === entry.id}
                              onChange={(event) =>
                                handleAvailabilityChange(entry, event.target.checked)
                              }
                            />
                          }
                          label={
                            <Typography variant="body2">
                              {entry.is_available ? 'Available' : 'Unavailable'}
                            </Typography>
                          }
                        />
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          —
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
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
