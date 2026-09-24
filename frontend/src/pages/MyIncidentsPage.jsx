/**
 * My Incidents — the issues the signed-in user has reported, with a dashboard
 * and filters over their own list.
 *
 * The backend decides what appears here; there is no client-side filtering by
 * user. GET /incidents and GET /incidents/summary only ever cover the caller's
 * own incidents, so no filter on this page can widen that.
 */

import { useEffect, useMemo, useState } from 'react'
import AddIcon from '@mui/icons-material/Add'
import PriorityHighIcon from '@mui/icons-material/PriorityHigh'
import {
  Alert,
  Box,
  Button,
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
import { Link as RouterLink, useNavigate } from 'react-router-dom'

import { getMySummary, listBuildings, listIncidents } from '../api/client'
import IncidentFilters from '../components/IncidentFilters'
import SummaryCards from '../components/SummaryCards'
import { buildingLabel } from '../facilities'
import { NO_FILTERS, useDebouncedSearch } from '../filters'
import {
  STATUS_ORDER,
  categoryLabel,
  formatDateTime,
  priorityDisplay,
  statusDisplay,
} from '../incidents'

export default function MyIncidentsPage() {
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

  // A table with six columns is unreadable on a phone, so narrow screens drop
  // the less essential columns rather than scrolling sideways.
  const isCompact = useMediaQuery({ maxWidth: 800 })

  // The summary is deliberately unfiltered: it describes everything you have
  // reported, so it stays still while you narrow the list beneath it.
  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const [counts, buildingData] = await Promise.all([getMySummary(), listBuildings()])
        if (!ignore) {
          setSummary(counts)
          setBuildings(buildingData.buildings)
        }
      } catch {
        // Not fatal: the list below still works without the cards or dropdown.
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
        const data = await listIncidents(query)
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
        { key: 'total', label: 'Total', count: summary.total, accent: theme.palette.text.primary },
        ...STATUS_ORDER.map((value) => ({
          key: value,
          label: statusDisplay(value).short,
          count: summary.by_status[value] ?? 0,
          accent: theme.palette[statusDisplay(value).color]?.main,
        })),
      ]
    : []

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        sx={{ justifyContent: 'space-between', alignItems: { sm: 'center' } }}
      >
        <Box>
          <Typography variant="h5" component="h2" gutterBottom>
            My incidents
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Everything you have reported, newest first.
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

      {summary && (
        <>
          <SummaryCards cards={cards} />

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              By priority
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
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
        <Stack sx={{ alignItems: 'center', py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status !== 'loading' && refreshing && <LinearProgress />}

      {status === 'error' && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'success' && incidents.length === 0 && (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            {isFiltered
              ? 'No incidents match these filters.'
              : 'You have not reported any incidents yet.'}
          </Typography>
        </Paper>
      )}

      {status === 'success' && incidents.length > 0 && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Title</TableCell>
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
                      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                        {incident.escalation_requested && (
                          <Tooltip title="Escalation requested">
                            <PriorityHighIcon color="error" fontSize="small" />
                          </Tooltip>
                        )}
                        <span>{incident.title}</span>
                      </Stack>
                    </TableCell>
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
