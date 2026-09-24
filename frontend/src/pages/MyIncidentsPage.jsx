/**
 * My Incidents — the list of issues the signed-in user has reported.
 *
 * The backend decides what appears here; there is no client-side filtering by
 * user. GET /incidents only ever returns the caller's own incidents.
 */

import { useEffect, useState } from 'react'
import AddIcon from '@mui/icons-material/Add'
import {
  Alert,
  Box,
  Button,
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
import { Link as RouterLink, useNavigate } from 'react-router-dom'

import { listIncidents } from '../api/client'
import { buildingLabel } from '../facilities'
import { categoryLabel, formatDateTime, priorityDisplay, statusDisplay } from '../incidents'

export default function MyIncidentsPage() {
  const [status, setStatus] = useState('loading')
  const [incidents, setIncidents] = useState([])
  const [errorMessage, setErrorMessage] = useState('')
  const navigate = useNavigate()

  // A table with six columns is unreadable on a phone, so narrow screens drop
  // the less essential columns rather than scrolling sideways.
  const isCompact = useMediaQuery({ maxWidth: 800 })

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listIncidents()
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
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'stretch', sm: 'center' }}
        justifyContent="space-between"
      >
        <Box>
          <Typography variant="h5" component="h2" gutterBottom>
            My incidents
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Issues you have reported, newest first.
          </Typography>
        </Box>

        <Button
          variant="contained"
          startIcon={<AddIcon />}
          component={RouterLink}
          to="/incidents/new"
        >
          Report an issue
        </Button>
      </Stack>

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status === 'error' && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'success' && incidents.length === 0 && (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" gutterBottom>
            You have not reported any incidents yet.
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Report a facility or workplace technology problem and track it here.
          </Typography>
          <Button variant="contained" component={RouterLink} to="/incidents/new">
            Report your first issue
          </Button>
        </Paper>
      )}

      {status === 'success' && incidents.length > 0 && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Title</TableCell>
                <TableCell>Location</TableCell>
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
                    <TableCell>{buildingLabel(incident) || '—'}</TableCell>
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
