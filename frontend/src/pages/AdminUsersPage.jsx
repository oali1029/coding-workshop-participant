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
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useMediaQuery } from 'react-responsive'

import { listUsers, setUserRole } from '../api/client'
import useAuth from '../auth/useAuth'
import { MANAGEABLE_ROLES, ROLE_LABELS, roleLabel } from '../roles'

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
      const { user: updated } = await setUserRole(targetUser.id, role)

      // Replace just the changed row rather than refetching the whole list —
      // the server's response is the authoritative new state.
      setUsers((previous) =>
        previous.map((entry) => (entry.id === updated.id ? updated : entry)),
      )
      setToast(`${updated.full_name} is now ${roleLabel(updated.role)}.`)
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
          Promote an employee to engineer so incidents can be assigned to them.
        </Typography>
      </Box>

      {errorMessage && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 6 }}>
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
