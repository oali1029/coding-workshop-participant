/**
 * A donut chart drawn with one SVG circle per slice.
 *
 * No charting library: a donut is a ring of arcs, and `stroke-dasharray` draws
 * an arc directly — one dash the length of the slice, one gap for the rest of
 * the circle, offset by everything already drawn. That is a few lines of
 * arithmetic against roughly 100 KB of dependency for the only chart the
 * application has.
 *
 * The chart is decorative. Every figure it shows is also in the breakdown table
 * beside it, which is what a screen reader announces and what remains readable
 * to anyone who cannot distinguish the colours — hence aria-hidden here.
 */

import { Box, Stack, Typography } from '@mui/material'

const SIZE = 200
const RADIUS = 70
const THICKNESS = 28
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

/**
 * @param slices - [{ label, value, color }], zero values allowed and skipped.
 * @param centerLabel - the word under the total in the middle, e.g. "Total".
 */
export default function DonutChart({ slices, centerLabel = 'Total' }) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0)

  // Each arc starts where the previous one ended, so its offset is everything
  // before it. Derived from the slices rather than accumulated in a variable,
  // which keeps the render free of mutation.
  const visible = slices.filter((slice) => slice.value > 0)
  const arcs = visible.map((slice, index) => {
    const preceding = visible
      .slice(0, index)
      .reduce((sum, earlier) => sum + earlier.value, 0)

    return {
      ...slice,
      length: (slice.value / total) * CIRCUMFERENCE,
      offset: -(preceding / total) * CIRCUMFERENCE,
    }
  })

  return (
    <Stack alignItems="center" spacing={1}>
      <Box
        component="svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        aria-hidden="true"
        sx={{ width: '100%', maxWidth: SIZE, height: 'auto' }}
      >
        {/* Rotated so the first slice starts at the top rather than at 3 o'clock. */}
        <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
          {/* Track: also what shows when there is nothing to chart. */}
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="rgba(0,0,0,0.08)"
            strokeWidth={THICKNESS}
          />
          {arcs.map((arc) => (
            <circle
              key={arc.label}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={arc.color}
              strokeWidth={THICKNESS}
              strokeDasharray={`${arc.length} ${CIRCUMFERENCE - arc.length}`}
              strokeDashoffset={arc.offset}
            />
          ))}
        </g>

        {/* Outside the rotated group, or the text would be on its side. */}
        <text
          x={SIZE / 2}
          y={SIZE / 2 - 4}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: 34, fontWeight: 600, fill: 'currentColor' }}
        >
          {total}
        </text>
        <text
          x={SIZE / 2}
          y={SIZE / 2 + 24}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: 13, fill: 'currentColor', opacity: 0.6 }}
        >
          {centerLabel}
        </text>
      </Box>

      {total === 0 && (
        <Typography variant="caption" color="text.secondary">
          Nothing to chart yet
        </Typography>
      )}
    </Stack>
  )
}
