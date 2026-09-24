/**
 * Assigned Incidents — the engineer's work queue, with a dashboard and filters.
 *
 * Scoped by the backend to incidents assigned to the signed-in engineer. An
 * engineer who also reported something finds that under My Incidents; this page
 * answers only "what work do I currently hold?".
 */

import { useEffect, useMemo, useState } from 'react'
import PriorityHighIcon from '@mui/icons-material/PriorityHigh'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material'
import { useMediaQuery } from 'react-responsive'
import { useNavigate } from 'react-router-dom'

import { getAssignedSummary, listAssignedIncidents, listBuildings } from '../api/client'
import IncidentFilters from '../components/IncidentFilters'
import SummaryCards from '../components/SummaryCards'
import { buildingLabel } from '../facilities'
import { NO_FILTERS, useDebouncedSearch } from '../filters'
import {
  categoryLabel,
  formatDateTime,
  priorityDisplay,
  statusDisplay,
} from '../incidents'

// CLOSED is absent: an engineer cannot act on a closed ticket, so it would be a
// card they can never do anything about. The list below still shows them.
const QUEUE_STATUSES = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED']

export default function AssignedIncidentsPage() {
  const theme = useTheme()
  const [status, setStatus] = useState('loading')
  const [incidents, setIncidents] = useState([])
  const [errorMessage, setErrorMessage] = useState('')
  const navigate = useNavigate()

  const [summary, setSummary] = useState(null)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState(NO_FILTERS)
  const [buildings, setBuildings] = useState([])
  const [loadedQuery, setLoadedQuery] = useState(null)

  const appliedSearch = useDebouncedSearch(search)
  const isCompact = useMediaQuery({ maxWidth: 800 })

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const [counts, buildingData] = await Promise.all([
          getAssignedSummary(),
          listBuildings(),
        ])
        if (!ignore) {
          setSummary(counts)
          setBuildings(buildingData.buildings)
        }
      } catch {
        // Not fatal: the queue below still works without the cards or dropdown.
      }
    }

    load()

    return () => {
      ignore = true
    }
  }, [])

  const query = useMemo(() => ({ ...filters, q: appliedSearch }), [filters, appliedSearch])

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listAssignedIncidents(query)
        if (!ignore) {
          setIncidents(data.incidents)
          setStatus('success')
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error.message)
          setStatus('error')
        }
      } finally {
        if (!ignore) {
          setLoadedQuery(query)
        }
      }
    }

    load()

    return () => {
      ignore = true
    }
  }, [query])

  const refreshing = loadedQuery !== query
  const isFiltered = Boolean(appliedSearch) || Object.values(filters).some(Boolean)

  const cards = summary
    ? [
        {
          key: 'total',
          label: 'Total assigned',
          count: summary.total,
          accent: theme.palette.text.primary,
        },
        ...QUEUE_STATUSES.map((value) => ({
          key: value,
          label: statusDisplay(value).short,
          count: summary.by_status[value] ?? 0,
          accent: theme.palette[statusDisplay(value).color]?.main,
        })),
      ]
    : []

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Assigned to me
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Your work queue, newest first.
        </Typography>
      </Box>

      {summary && (
        <>
          <SummaryCards cards={cards} />

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              By priority
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {Object.entries(summary.by_priority).map(([value, count]) => (
                <Chip
                  key={value}
                  size="small"
                  variant="outlined"
                  color={priorityDisplay(value).color}
                  label={`${priorityDisplay(value).label}: ${count}`}
                />
              ))}
            </Stack>
          </Paper>
        </>
      )}

      <IncidentFilters
        search={search}
        onSearchChange={setSearch}
        filters={filters}
        onFilterChange={(name, value) =>
          setFilters((current) => ({ ...current, [name]: value }))
        }
        onClear={() => {
          setSearch('')
          setFilters(NO_FILTERS)
        }}
        buildings={buildings}
        isFiltered={isFiltered}
      />

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status !== 'loading' && refreshing && <LinearProgress />}

      {status === 'error' && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'success' && incidents.length === 0 && (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            {isFiltered
              ? 'No assigned incidents match these filters.'
              : 'Nothing is assigned to you right now.'}
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
                {!isCompact && <TableCell>Location</TableCell>}
                {!isCompact && <TableCell>Category</TableCell>}
                <TableCell>Status</TableCell>
                <TableCell>Priority</TableCell>
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
                    <TableCell>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        {incident.escalation_requested && (
                          <Tooltip title="Escalation requested">
                            <PriorityHighIcon color="error" fontSize="small" />
                          </Tooltip>
                        )}
                        <span>{incident.title}</span>
                      </Stack>
                    </TableCell>
                    <TableCell>{incident.reporter_name}</TableCell>
                    {!isCompact && <TableCell>{buildingLabel(incident) || '—'}</TableCell>}
                    {!isCompact && <TableCell>{categoryLabel(incident.category)}</TableCell>}
                    <TableCell>
                      <Chip size="small" label={statusChip.label} color={statusChip.color} />
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        variant="outlined"
                        label={priorityChip.label}
                        color={priorityChip.color}
                      />
                    </TableCell>
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
