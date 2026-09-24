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
  CircularProgress,
  Paper,
  Stack,
  Typography,
  useTheme,
} from '@mui/material'

import { getAnalytics } from '../api/client'
import BreakdownSection from '../components/BreakdownSection'
import { CATEGORIES, statusDisplay } from '../incidents'

// Workflow order, so the cards and rows read as a pipeline rather than in
// whatever order the API serialised the object.
const STATUS_ORDER = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED', 'CLOSED']

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

/** One compact figure at the top of the page. */
function SummaryCard({ label, count, accent }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        flex: '1 1 140px',
        minWidth: 130,
        textAlign: 'center',
        // A coloured top edge ties each card to its slice without flooding the
        // page with background colour.
        borderTop: 3,
        borderTopColor: accent,
      }}
    >
      <Typography variant="h4" component="p" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
        {count}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {label}
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

  const statusRows =
    summary &&
    STATUS_ORDER.map((value) => ({
      key: value,
      label: statusDisplay(value).label,
      count: summary.by_status[value] ?? 0,
      color: statusColor(value),
    }))

  const categoryRows =
    summary &&
    CATEGORIES.map((category, index) => ({
      key: category.value,
      label: category.label,
      count: summary.by_category[category.value] ?? 0,
      color: palette[index % palette.length],
    }))

  const buildingRows =
    summary &&
    summary.by_building.map((row, index) => ({
      key: row.building,
      label: row.building,
      count: row.count,
      color: palette[index % palette.length],
    }))

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Analytics
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Where incidents are coming from, across the whole organisation.
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
          {/* Wraps onto as many rows as it needs, so the six figures stay
              readable from a phone up. */}
          <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
            <SummaryCard
              label="Total Issues"
              count={summary.total}
              accent={theme.palette.text.primary}
            />
            {STATUS_ORDER.map((value) => (
              <SummaryCard
                key={value}
                label={statusDisplay(value).short}
                count={summary.by_status[value] ?? 0}
                accent={statusColor(value)}
              />
            ))}
          </Stack>

          <BreakdownSection
            title="Issues by Status"
            tableTitle="Status Breakdown"
            firstColumn="Status"
            rows={statusRows}
            total={summary.total}
          />

          <BreakdownSection
            title="Issues by Category"
            tableTitle="Category Breakdown"
            firstColumn="Incident Type"
            rows={categoryRows}
            total={summary.total}
          />

          {buildingRows.length === 0 ? (
            <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
              <Typography variant="subtitle1" gutterBottom>
                Issues by Building
              </Typography>
              <Typography variant="body2" color="text.secondary">
                No incidents have been reported yet.
              </Typography>
            </Paper>
          ) : (
            <BreakdownSection
              title="Issues by Building"
              tableTitle="Building Breakdown"
              firstColumn="Building"
              rows={buildingRows}
              total={summary.total}
            />
          )}
        </>
      )}
    </Stack>
  )
}
