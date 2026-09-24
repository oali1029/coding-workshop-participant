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
import ClearIcon from '@mui/icons-material/Clear'
import SearchIcon from '@mui/icons-material/Search'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  InputAdornment,
  LinearProgress,
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
import { useLocation, useNavigate } from 'react-router-dom'

import { listAllIncidents, listBuildings, listEngineers } from '../api/client'
import { buildingLabel } from '../facilities'
import {
  ADMIN_SETTABLE,
  CATEGORIES,
  categoryLabel,
  formatDateTime,
  priorityDisplay,
  statusDisplay,
} from '../incidents'

// Long enough to cover typing, short enough to feel immediate.
const SEARCH_DEBOUNCE_MS = 300

// The value the assignee dropdown uses for "nobody". The backend understands
// this exact word — see list_all in backend/v1/app/domains/incidents.py.
const UNASSIGNED = 'unassigned'

const NO_FILTERS = { q: '', status: '', category: '', building: '', assignee: '' }

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

  // What the user typed, and the debounced copy the request actually uses.
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [filters, setFilters] = useState(NO_FILTERS)
  // The query the rows on screen were fetched with, so a refetch in progress is
  // simply "this does not match the current query".
  const [loadedQuery, setLoadedQuery] = useState(null)

  // Dropdown options. Loaded once; failures are not fatal, the filters just
  // offer fewer choices.
  const [buildings, setBuildings] = useState([])
  const [engineers, setEngineers] = useState([])

  const isCompact = useMediaQuery({ maxWidth: 900 })

  useEffect(() => {
    const timer = setTimeout(() => setAppliedSearch(search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search])

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

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <TextField
            fullWidth
            size="small"
            label="Search"
            placeholder="Title, description, reporter or engineer"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" />
                  </InputAdornment>
                ),
              },
            }}
          />

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} flexWrap="wrap" useFlexGap>
            <TextField
              select
              size="small"
              label="Status"
              value={filters.status}
              onChange={(event) => setFilter('status', event.target.value)}
              sx={{ minWidth: 180 }}
            >
              <MenuItem value="">Any status</MenuItem>
              {ADMIN_SETTABLE.map((value) => (
                <MenuItem key={value} value={value}>
                  {statusDisplay(value).label}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              size="small"
              label="Category"
              value={filters.category}
              onChange={(event) => setFilter('category', event.target.value)}
              sx={{ minWidth: 180 }}
            >
              <MenuItem value="">Any category</MenuItem>
              {CATEGORIES.map((category) => (
                <MenuItem key={category.value} value={category.value}>
                  {category.label}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              size="small"
              label="Building"
              value={filters.building}
              onChange={(event) => setFilter('building', event.target.value)}
              sx={{ minWidth: 180 }}
            >
              <MenuItem value="">Any building</MenuItem>
              {buildings.map((building) => (
                <MenuItem key={building.id} value={building.id}>
                  {building.name}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              size="small"
              label="Assigned to"
              value={filters.assignee}
              onChange={(event) => setFilter('assignee', event.target.value)}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">Anyone</MenuItem>
              <MenuItem value={UNASSIGNED}>Unassigned</MenuItem>
              {engineers.map((engineer) => (
                <MenuItem key={engineer.id} value={engineer.id}>
                  {engineer.full_name}
                </MenuItem>
              ))}
            </TextField>

            {isFiltered && (
              <Button size="small" startIcon={<ClearIcon />} onClick={clearAll}>
                Clear
              </Button>
            )}
          </Stack>
        </Stack>
      </Paper>

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
