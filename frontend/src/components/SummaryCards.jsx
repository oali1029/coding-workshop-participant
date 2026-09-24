/**
 * A wrapping row of compact counts, used by all three dashboards.
 *
 * The same component serves the employee, the engineer and the admin because
 * all three ask the same question of different scopes — the numbers arrive
 * already counted by PostgreSQL, scoped per persona, so this only lays them out.
 */

import { Paper, Stack, Typography } from '@mui/material'

/** @param cards - [{ key, label, count, accent }] */
export default function SummaryCards({ cards }) {
  return (
    <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
      {cards.map((card) => (
        <Paper
          key={card.key}
          variant="outlined"
          sx={{
            p: 2,
            // Grows to share the row, wraps to a new line below ~140px rather
            // than squeezing six unreadable columns onto a phone.
            flex: '1 1 140px',
            minWidth: 120,
            textAlign: 'center',
            borderTop: 3,
            borderTopColor: card.accent,
          }}
        >
          <Typography variant="h4" component="p" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
            {card.count}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {card.label}
          </Typography>
        </Paper>
      ))}
    </Stack>
  )
}
