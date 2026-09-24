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
import {
  CATEGORIES,
  PRIORITIES,
  STATUS_ORDER,
  categoryLabel,
  priorityDisplay,
  statusDisplay,
} from '../incidents'

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

/** Whole pounds-style grouping, e.g. $1,200. Fractions of a currency unit are
 *  noise on an illustrative estimate, so they are not shown. */
function formatMoney(amount) {
  return `$${Math.round(amount || 0).toLocaleString()}`
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
        <Stack sx={{ alignItems: 'center', py: 6 }}>
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
          <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
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

          <OperationalInsights insights={summary.operational} />
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

/**
 * Recurring problems and what leaving them unresolved is costing, roughly.
 *
 * The distinction this section exists to make: three people reporting one
 * broken lift are three incidents everywhere else on this page, and one problem
 * here. The estimate charges for it once, at the highest priority anyone gave
 * it, so duplicate reports cannot inflate the figure.
 *
 * The disclaimer is not decoration. These are illustrative rates for ranking
 * problems by how much attention they deserve, not an accounting figure, and
 * the wording has to keep saying so wherever the number appears.
 */
function OperationalInsights({ insights }) {
  const { window_days: windowDays, hourly_rates: rates } = insights

  const cards = [
    {
      key: 'estimated',
      label: 'Estimated Operational Impact',
      value: formatMoney(insights.estimated_impact),
    },
    {
      key: 'active',
      label: 'Active Operational Impact',
      value: formatMoney(insights.active_impact),
    },
    {
      key: 'recurring',
      label: 'Recurring Problems',
      value: insights.recurring_count,
    },
  ]

  return (
    <>
      <SectionHeading
        title="Operational Insights"
        description={`Reports of the same problem in the same place, over the last ${windowDays} days.`}
      />

      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
        {cards.map((card) => (
          <Paper
            key={card.key}
            variant="outlined"
            sx={{ p: 2, flex: '1 1 200px', minWidth: 170, textAlign: 'center' }}
          >
            <Typography variant="h5" component="p" sx={{ fontWeight: 600 }}>
              {card.value}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {card.label}
            </Typography>
          </Paper>
        ))}
      </Stack>

      <Alert severity="info" icon={false}>
        Illustrative estimate based on incident priority and time unresolved.
        Duplicate reports of the same recurring problem are counted once.
        Rates: {Object.entries(rates)
          .map(([priority, rate]) => `${priorityDisplay(priority).label} $${rate}/hour`)
          .join(' · ')}.
      </Alert>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '7fr 5fr' },
          gap: 3,
          alignItems: 'start',
        }}
      >
        <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
          <Typography variant="subtitle1" gutterBottom>
            Recurring Problems
          </Typography>

          {insights.recurring_problems.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No recurring problems detected in the last {windowDays} days.
            </Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Location</TableCell>
                  <TableCell>Category</TableCell>
                  <TableCell align="right">Reports</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {insights.recurring_problems.map((problem) => (
                  <TableRow key={`${problem.location}-${problem.category}`}>
                    <TableCell>
                      {problem.location}
                      {problem.is_active && (
                        <Chip size="small" color="warning" label="Active" sx={{ ml: 1 }} />
                      )}
                    </TableCell>
                    <TableCell>{categoryLabel(problem.category)}</TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {problem.reports}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Paper>

        <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
          <Typography variant="subtitle1" gutterBottom>
            Impact by Priority
          </Typography>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Priority</TableCell>
                <TableCell align="right">Estimated Impact</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {PRIORITIES.map((priority) => (
                <TableRow key={priority.value}>
                  <TableCell>{priority.label}</TableCell>
                  <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {formatMoney(insights.impact_by_priority[priority.value])}
                  </TableCell>
                </TableRow>
              ))}
              {/* Reconciles with the headline card above — the quickest way to
                  see the per-priority split is complete. */}
              <TableRow>
                <TableCell sx={{ fontWeight: 600, borderBottom: 'none' }}>Total</TableCell>
                <TableCell
                  align="right"
                  sx={{ fontWeight: 600, borderBottom: 'none', fontVariantNumeric: 'tabular-nums' }}
                >
                  {formatMoney(insights.estimated_impact)}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Paper>
      </Box>
    </>
  )
}
