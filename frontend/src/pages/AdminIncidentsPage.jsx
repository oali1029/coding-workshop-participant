/**
 * All Incidents — the Facility Admin's organisation-wide view, with search
 * and filters.
 *
 * Distinct from My Incidents, which stays creator-scoped for every role
 * including admins.
 *
 * Filtering happens on the server. The alternative — fetching everything and
 * hiding rows in the browser — would send the admin's machine data it is only
 * going to discard, and would stop being viable as the list grows.
 *
 * The search box is debounced so that typing a word does not fire a request per
 * keystroke; the dropdowns apply immediately, since one click is one intent.
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
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import { useMediaQuery } from 'react-responsive'
import { useLocation, useNavigate } from 'react-router-dom'

import { listAllIncidents, listBuildings, listEngineers } from '../api/client'
import IncidentFilters from '../components/IncidentFilters'
import { buildingLabel } from '../facilities'
import { NO_FILTERS, useDebouncedSearch } from '../filters'
import { categoryLabel, formatDateTime, priorityDisplay, statusDisplay } from '../incidents'

export default function AdminIncidentsPage() {
  const [status, setStatus] = useState('loading')
  const [incidents, setIncidents] = useState([])
  const [errorMessage, setErrorMessage] = useState('')
  const navigate = useNavigate()
  const location = useLocation()

  // A page that navigated here — the detail page after a deletion — can hand
  // over a message through router state. Read during render rather than copied
  // into state by an effect, which React warns about.
  const notice = location.state?.notice || ''

  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState(NO_FILTERS)
  // The query the rows on screen were fetched with, so a refetch in progress is
  // simply "this does not match the current query".
  const [loadedQuery, setLoadedQuery] = useState(null)

  // Dropdown options. Loaded once; failures are not fatal, the filters just
  // offer fewer choices.
  const [buildings, setBuildings] = useState([])
  const [engineers, setEngineers] = useState([])

  const isCompact = useMediaQuery({ maxWidth: 900 })

  const appliedSearch = useDebouncedSearch(search)

  useEffect(() => {
    let ignore = false

    async function loadOptions() {
      try {
        const [buildingData, engineerData] = await Promise.all([
          listBuildings(),
          listEngineers(),
        ])
        if (!ignore) {
          setBuildings(buildingData.buildings)
          setEngineers(engineerData.engineers)
        }
      } catch {
        // The list itself still works; only the dropdowns are short of options.
      }
    }

    loadOptions()

    return () => {
      ignore = true
    }
  }, [])

  // The query the list is currently showing. Memoised so the effect below
  // re-runs when a filter value changes, not on every render.
  const query = useMemo(
    () => ({ ...filters, q: appliedSearch }),
    [filters, appliedSearch],
  )

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listAllIncidents(query)
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
        // Recording which query these rows came from, rather than flipping a
        // "loading" flag before the request, keeps every setState out of the
        // effect body — React warns about synchronous updates there.
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

  // A refetch keeps the previous rows on screen under a progress bar, so the
  // table does not blink empty every time a filter changes.
  const refreshing = loadedQuery !== query

  function setFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value }))
  }

  function clearAll() {
    setSearch('')
    setFilters(NO_FILTERS)
  }

  const isFiltered = Boolean(appliedSearch) || Object.values(filters).some(Boolean)

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

      <IncidentFilters
        search={search}
        onSearchChange={setSearch}
        filters={filters}
        onFilterChange={setFilter}
        onClear={clearAll}
        buildings={buildings}
        engineers={engineers}
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
              : 'No incidents have been reported yet.'}
          </Typography>
        </Paper>
      )}

      {status === 'success' && incidents.length > 0 && (
        <>
          <Typography variant="body2" color="text.secondary">
            {incidents.length === 1 ? '1 incident' : `${incidents.length} incidents`}
            {isFiltered ? ' matching' : ''}
          </Typography>

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
                      <TableCell>
                        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                          {/* The admin is the one who acts on escalations, so
                              they are flagged in the list rather than only on
                              the detail page. */}
                          {incident.escalation_requested && (
                            <Tooltip title={incident.escalation_reason || 'Escalation requested'}>
                              <PriorityHighIcon color="error" fontSize="small" />
                            </Tooltip>
                          )}
                          <span>{incident.title}</span>
                        </Stack>
                      </TableCell>
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
        </>
      )}

      <Snackbar
        open={Boolean(notice)}
        autoHideDuration={5000}
        message={notice}
        // Clearing the router state stops the message reappearing if the user
        // navigates back to this entry.
        onClose={() => navigate(location.pathname, { replace: true, state: null })}
      />
    </Stack>
  )
}
