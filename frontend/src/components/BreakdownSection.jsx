/**
 * One analytics section: a donut on the left, the same numbers as a table on
 * the right, stacking to a single column on a narrow screen.
 *
 * The table is the authoritative version. It carries exact counts and
 * percentages and stays readable without colour, which is why the chart beside
 * it is marked decorative rather than given its own description.
 */

import {
  Box,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'

import DonutChart from './DonutChart'

/** Whole-number percentage, and 0% rather than NaN on an empty set. */
function percentOf(count, total) {
  return total > 0 ? Math.round((count / total) * 100) : 0
}

// Counts and percentages line up column-wise only if the digits are the same
// width, which proportional fonts do not guarantee.
const NUMERIC = { fontVariantNumeric: 'tabular-nums' }

/**
 * @param rows - [{ key, label, count, color }]
 * @param firstColumn - what the rows are: "Status", "Incident Type", "Building".
 */
export default function BreakdownSection({ title, tableTitle, firstColumn, rows, total }) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', md: 'minmax(240px, 5fr) 7fr' },
        gap: 3,
        alignItems: 'start',
      }}
    >
      <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
        <Typography variant="subtitle1" gutterBottom>
          {title}
        </Typography>

        <DonutChart
          slices={rows.map(({ label, count, color }) => ({ label, value: count, color }))}
        />

        {/* Legend as a four-column grid rather than inline text, so a label and
            its count can never run together into "Open2". */}
        <Stack spacing={1} sx={{ mt: 2 }}>
          {rows.map((row) => (
            <Box
              key={row.key}
              sx={{
                display: 'grid',
                gridTemplateColumns: '14px 1fr auto auto',
                alignItems: 'center',
                columnGap: 1.5,
              }}
            >
              <Box sx={{ width: 12, height: 12, borderRadius: '3px', bgcolor: row.color }} />
              <Typography variant="body2" noWrap title={row.label}>
                {row.label}
              </Typography>
              <Typography variant="body2" sx={NUMERIC}>
                {row.count}
              </Typography>
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ ...NUMERIC, minWidth: 44, textAlign: 'right' }}
              >
                {percentOf(row.count, total)}%
              </Typography>
            </Box>
          ))}
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
        <Typography variant="subtitle1" gutterBottom>
          {tableTitle}
        </Typography>

        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{firstColumn}</TableCell>
              <TableCell align="right"># Incidents</TableCell>
              <TableCell align="right">Percentage</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.key}>
                <TableCell>{row.label}</TableCell>
                <TableCell align="right" sx={NUMERIC}>
                  {row.count}
                </TableCell>
                <TableCell align="right" sx={NUMERIC}>
                  {percentOf(row.count, total)}%
                </TableCell>
              </TableRow>
            ))}
            {/* Reconciles the section against the headline total — the quickest
                way to spot a figure that has gone missing. */}
            <TableRow>
              <TableCell sx={{ fontWeight: 600, borderBottom: 'none' }}>Total</TableCell>
              <TableCell align="right" sx={{ ...NUMERIC, fontWeight: 600, borderBottom: 'none' }}>
                {total}
              </TableCell>
              <TableCell align="right" sx={{ ...NUMERIC, fontWeight: 600, borderBottom: 'none' }}>
                {total > 0 ? '100%' : '0%'}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Paper>
    </Box>
  )
}
