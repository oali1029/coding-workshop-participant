/**
 * All Incidents — the Facility Admin's organisation-wide view.
 *
 * Distinct from My Incidents, which stays creator-scoped for every role
 * including admins. This is the list an admin will assign work from in a
 * later slice.
 */

import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useMediaQuery } from 'react-responsive'
import { useNavigate } from 'react-router-dom'

import { listAllIncidents } from '../api/client'
import { buildingLabel } from '../facilities'
import { categoryLabel, formatDateTime, priorityDisplay, statusDisplay } from '../incidents'

export default function AdminIncidentsPage() {
  const [status, setStatus] = useState('loading')
  const [incidents, setIncidents] = useState([])
  const [errorMessage, setErrorMessage] = useState('')
  const navigate = useNavigate()

  const isCompact = useMediaQuery({ maxWidth: 900 })

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listAllIncidents()
        if (!ignore) {
          setIncidents(data.incidents)
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

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          All incidents
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Every incident reported across the organisation, newest first.
        </Typography>
      </Box>

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status === 'error' && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'success' && incidents.length === 0 && (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            No incidents have been reported yet.
          </Typography>
        </Paper>
      )}

      {status === 'success' && incidents.length > 0 && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Title</TableCell>
                <TableCell>Reported by</TableCell>
                <TableCell>Assigned to</TableCell>
                {!isCompact && <TableCell>Location</TableCell>}
                {!isCompact && <TableCell>Category</TableCell>}
                <TableCell>Status</TableCell>
                {!isCompact && <TableCell>Priority</TableCell>}
                {!isCompact && <TableCell>Reported</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {incidents.map((incident) => {
                const statusChip = statusDisplay(incident.status)
                const priorityChip = priorityDisplay(incident.priority)

                return (
                  <TableRow
                    key={incident.id}
                    hover
                    onClick={() => navigate(`/incidents/${incident.id}`)}
                    sx={{ cursor: 'pointer' }}
                  >
                    <TableCell>{incident.title}</TableCell>
                    <TableCell>
                      <Typography variant="body2">{incident.reporter_name}</Typography>
                      {!isCompact && (
                        <Typography variant="caption" color="text.secondary">
                          {incident.reporter_email}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {incident.assignee_name || (
                        <Typography variant="body2" color="text.secondary">
                          Unassigned
                        </Typography>
                      )}
                    </TableCell>
                    {!isCompact && (
                      <TableCell>{buildingLabel(incident) || '—'}</TableCell>
                    )}
                    {!isCompact && <TableCell>{categoryLabel(incident.category)}</TableCell>}
                    <TableCell>
                      <Chip size="small" label={statusChip.label} color={statusChip.color} />
                    </TableCell>
                    {!isCompact && (
                      <TableCell>
                        <Chip
                          size="small"
                          variant="outlined"
                          label={priorityChip.label}
                          color={priorityChip.color}
                        />
                      </TableCell>
                    )}
                    {!isCompact && <TableCell>{formatDateTime(incident.created_at)}</TableCell>}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Paper>
      )}
    </Stack>
  )
}
