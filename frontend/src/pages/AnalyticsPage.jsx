/**
 * Analytics — the Facility Admin's overview of where incidents are coming from.
 *
 * Every number here is counted by PostgreSQL and arrives ready to display; this
 * page does no tallying of its own. That is why it works without the admin's
 * browser ever holding the full incident list.
 *
 * Bars are drawn with MUI's LinearProgress rather than a charting library, which
 * keeps the bundle small and adds no dependency for what is a row of proportions.
 */

import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  CircularProgress,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material'

import { getAnalytics } from '../api/client'
import { CATEGORIES, statusDisplay } from '../incidents'

// The order the workflow runs in, so the status list reads as a pipeline rather
// than in whatever order the API happened to serialise the object.
const STATUS_ORDER = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED', 'CLOSED']

/** One labelled row with a proportional bar. */
function BreakdownRow({ label, count, total, color = 'primary' }) {
  // Guard against 0/0 on an empty dataset, which would render NaN.
  const percent = total > 0 ? (count / total) * 100 : 0

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
        <Typography variant="body2">{label}</Typography>
        <Typography variant="body2" color="text.secondary">
          {count}
        </Typography>
      </Stack>
      <LinearProgress
        variant="determinate"
        value={percent}
        color={color}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  )
}

function Section({ title, description, children }) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
      <Typography variant="subtitle1" gutterBottom>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {description}
        </Typography>
      )}
      {children}
    </Paper>
  )
}

export default function AnalyticsPage() {
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
          <Paper variant="outlined" sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="h3" component="p">
              {summary.total}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {summary.total === 1 ? 'incident reported' : 'incidents reported'}
            </Typography>
          </Paper>

          <Section
            title="By status"
            description="Every status is listed, including those nothing is currently in."
          >
            <Stack spacing={2}>
              {STATUS_ORDER.map((value) => (
                <BreakdownRow
                  key={value}
                  label={statusDisplay(value).label}
                  count={summary.by_status[value] ?? 0}
                  total={summary.total}
                  color={statusDisplay(value).color}
                />
              ))}
            </Stack>
          </Section>

          <Section title="By category">
            <Stack spacing={2}>
              {CATEGORIES.map((category) => (
                <BreakdownRow
                  key={category.value}
                  label={category.label}
                  count={summary.by_category[category.value] ?? 0}
                  total={summary.total}
                />
              ))}
            </Stack>
          </Section>

          <Section
            title="By building"
            description="Busiest first. Incidents whose building was later removed are grouped together, so these figures still add up to the total."
          >
            {summary.by_building.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No incidents have been reported yet.
              </Typography>
            ) : (
              <Stack spacing={2}>
                {summary.by_building.map((row) => (
                  <BreakdownRow
                    key={row.building}
                    label={row.building}
                    count={row.count}
                    total={summary.total}
                  />
                ))}
              </Stack>
            )}
          </Section>
        </>
      )}
    </Stack>
  )
}
