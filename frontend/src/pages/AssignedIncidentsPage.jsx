/**
 * Assigned Incidents — an engineer's work queue.
 *
 * Distinct from My Incidents, which is what this person personally reported.
 * An engineer who reports a fault and is assigned a different one sees each in
 * its own place; a ticket they both reported and were assigned appears in both.
 *
 * Engineers only. Admins have no queue because they are never assignees — they
 * oversee everything through All Incidents instead.
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

import { listAssignedIncidents } from '../api/client'
import { categoryLabel, formatDateTime, priorityDisplay, statusDisplay } from '../incidents'

export default function AssignedIncidentsPage() {
  const [status, setStatus] = useState('loading')
  const [incidents, setIncidents] = useState([])
  const [errorMessage, setErrorMessage] = useState('')
  const navigate = useNavigate()

  const isCompact = useMediaQuery({ maxWidth: 900 })

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listAssignedIncidents()
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
          Assigned to me
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Work assigned to you by a facility administrator. Open a ticket to
          update its progress.
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
          <Typography variant="body1" gutterBottom>
            Nothing assigned to you right now.
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Tickets appear here once an administrator assigns them to you.
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
                    <TableCell>{incident.reporter_name}</TableCell>
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
