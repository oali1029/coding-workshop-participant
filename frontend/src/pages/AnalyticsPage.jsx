/**
 * Analytics — the Facility Admin's dashboard.
 *
 * Every figure is counted by PostgreSQL and arrives ready to display; this page
 * does no tallying of its own. That is why it works without the admin's browser
 * ever holding the incident list.
 *
 * Each section pairs a donut with a table showing the same numbers. The table is
 * the authoritative version — it carries the exact counts and percentages, and
 * it stays readable without colour — so the chart is marked decorative.
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
  useTheme,
} from '@mui/material'

import { getAnalytics } from '../api/client'
import BreakdownSection from '../components/BreakdownSection'
import SummaryCards from '../components/SummaryCards'
import { CATEGORIES, PRIORITIES, STATUS_ORDER, priorityDisplay, statusDisplay } from '../incidents'

/**
 * Colours for category and building slices, which carry no meaning of their own
 * to map to — unlike statuses, where the chip colour already says "blocked is
 * bad". Taken from the theme so the charts match the rest of the application.
 */
function sliceColors(theme) {
  return [
    theme.palette.primary.main,
    theme.palette.secondary?.main || theme.palette.info.dark,
    theme.palette.success.main,
    theme.palette.warning.main,
    theme.palette.error.main,
    theme.palette.info.main,
    theme.palette.grey[600],
    theme.palette.primary.light,
    theme.palette.success.dark,
    theme.palette.warning.dark,
  ]
}

/** Seconds as "3h 12m", or a dash when nothing has reached that milestone. */
function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return '—'
  }

  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)

  if (hours >= 24) {
    const days = Math.floor(hours / 24)
    return `${days}d ${hours % 24}h`
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  if (minutes > 0) {
    return `${minutes}m`
  }
  return `${total}s`
}

/** One lifecycle average, with the sample it was taken from. */
function TimingCard({ label, seconds, count }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, flex: '1 1 200px', minWidth: 170 }}>
      <Typography variant="h5" component="p" sx={{ fontWeight: 600 }}>
        {formatDuration(seconds)}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      {/* Saying what the average is over stops a single early ticket being read
          as a settled organisational figure. */}
      <Typography variant="caption" color="text.secondary">
        {count === 0
          ? 'Not enough data yet'
          : `across ${count} ${count === 1 ? 'incident' : 'incidents'}`}
      </Typography>
    </Paper>
  )
}

export default function AnalyticsPage() {
  const theme = useTheme()
  const [status, setStatus] = useState('loading')
  const [summary, setSummary] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await getAnalytics()
        if (!ignore) {
          setSummary(data)
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

  function statusColor(value) {
    const { color } = statusDisplay(value)
    return theme.palette[color]?.main || theme.palette.grey[500]
  }

  const palette = sliceColors(theme)

  /** Turn an API breakdown list ([{label, count}]) into chart/table rows. */
  function locationRows(list) {
    return list.map((row, index) => ({
      key: row.label,
      label: row.label,
      count: row.count,
      color: palette[index % palette.length],
    }))
  }

  const statusRows =
    summary &&
    STATUS_ORDER.map((value) => ({
      key: value,
      label: statusDisplay(value).label,
      count: summary.by_status[value] ?? 0,
      color: statusColor(value),
    }))

  const priorityRows =
    summary &&
    PRIORITIES.map((priority) => ({
      key: priority.value,
      label: priority.label,
      count: summary.by_priority[priority.value] ?? 0,
      color: theme.palette[priorityDisplay(priority.value).color]?.main
        || theme.palette.grey[500],
    }))

  const categoryRows =
    summary &&
    CATEGORIES.map((category, index) => ({
      key: category.value,
      label: category.label,
      count: summary.by_category[category.value] ?? 0,
      color: palette[index % palette.length],
    }))

  const cards = summary
    ? [
        {
          key: 'total',
          label: 'Total Issues',
          count: summary.total,
          accent: theme.palette.text.primary,
        },
        ...STATUS_ORDER.map((value) => ({
          key: value,
          label: statusDisplay(value).short,
          count: summary.by_status[value] ?? 0,
          accent: statusColor(value),
        })),
      ]
    : []

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Analytics
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Where incidents are coming from, how fast they move, and who is carrying
          the work.
        </Typography>
      </Box>

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {status === 'error' && <Alert severity="error">{errorMessage}</Alert>}

      {status === 'success' && summary && (
        <>
          <SummaryCards cards={cards} />

          {summary.escalations_open > 0 && (
            <Alert severity="warning">
              {summary.escalations_open === 1
                ? '1 incident has an open escalation request.'
                : `${summary.escalations_open} incidents have open escalation requests.`}{' '}
              Open All Incidents to review them.
            </Alert>
          )}

          <SectionHeading
            title="Response times"
            description="Averaged in the database across every incident that reached each milestone. Incidents that have not got there yet are excluded rather than counted as zero."
          />
          <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
            <TimingCard
              label="Average time to acknowledgement"
              seconds={summary.lifecycle.seconds_to_acknowledge}
              count={summary.lifecycle.acknowledged_count}
            />
            <TimingCard
              label="Average time to assignment"
              seconds={summary.lifecycle.seconds_to_assign}
              count={summary.lifecycle.assigned_count}
            />
            <TimingCard
              label="Average time to resolution"
              seconds={summary.lifecycle.seconds_to_resolve}
              count={summary.lifecycle.resolved_count}
            />
            <TimingCard
              label="Average time to closure"
              seconds={summary.lifecycle.seconds_to_close}
              count={summary.lifecycle.closed_count}
            />
          </Stack>

          <SectionHeading title="What is being reported" />

          <BreakdownSection
            title="Issues by Status"
            tableTitle="Status Breakdown"
            firstColumn="Status"
            rows={statusRows}
            total={summary.total}
          />

          <BreakdownSection
            title="Issues by Priority"
            tableTitle="Priority Breakdown"
            firstColumn="Priority"
            rows={priorityRows}
            total={summary.total}
          />

          <BreakdownSection
            title="Issues by Category"
            tableTitle="Category Breakdown"
            firstColumn="Incident Type"
            rows={categoryRows}
            total={summary.total}
          />

          <SectionHeading
            title="Where issues are happening"
            description="Recurring problems show up as a building, floor or seat near the top of these tables."
          />

          {summary.by_building.length === 0 ? (
            <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
              <Typography variant="body2" color="text.secondary">
                No incidents have been reported yet.
              </Typography>
            </Paper>
          ) : (
            <>
              <BreakdownSection
                title="Issues by Building"
                tableTitle="Building Breakdown"
                firstColumn="Building"
                rows={locationRows(summary.by_building)}
                total={summary.total}
              />

              <BreakdownSection
                title="Issues by Floor"
                tableTitle="Floor Breakdown"
                firstColumn="Floor"
                rows={locationRows(summary.by_floor)}
                total={summary.total}
              />

              <BreakdownSection
                title="Issues by Seat"
                tableTitle="Seat Breakdown"
                firstColumn="Seat"
                rows={locationRows(summary.by_seat)}
                total={summary.total}
              />
            </>
          )}

          <SectionHeading
            title="Who is carrying the work"
            description="Active means anything not yet closed, so work awaiting review still counts against an engineer."
          />

          <BreakdownSection
            title="Issues by Assignee"
            tableTitle="Assignee Breakdown"
            firstColumn="Assigned to"
            rows={locationRows(summary.by_assignee)}
            total={summary.total}
          />

          <EngineerTable engineers={summary.engineers} />
        </>
      )}
    </Stack>
  )
}

/** A heading that groups the sections beneath it, so the page reads in parts. */
function SectionHeading({ title, description }) {
  return (
    <Box sx={{ pt: 1 }}>
      <Typography variant="h6" component="h3">
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary">
          {description}
        </Typography>
      )}
    </Box>
  )
}

/** Engineer availability beside live workload — the "who is free?" answer. */
function EngineerTable({ engineers }) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
      <Typography variant="subtitle1" gutterBottom>
        Engineer Availability and Workload
      </Typography>

      {engineers.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No engineers have been set up yet.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Engineer</TableCell>
              <TableCell>Availability</TableCell>
              <TableCell align="right">Active Tickets</TableCell>
              <TableCell align="right">Total Ever</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {engineers.map((engineer) => (
              <TableRow key={engineer.id}>
                <TableCell>{engineer.full_name}</TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    label={engineer.is_available ? 'Available' : 'Unavailable'}
                    color={engineer.is_available ? 'success' : 'default'}
                    variant={engineer.is_available ? 'filled' : 'outlined'}
                  />
                </TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {engineer.active_count}
                </TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {engineer.total_count}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  )
}
