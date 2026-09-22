/**
 * The landing page after signing in.
 *
 * SCOPE NOTE: for this slice it deliberately does one thing — confirm who is
 * signed in and with what role. The real per-role dashboards (open incidents,
 * engineer workload, reporting) come in a later slice. Building a placeholder
 * dashboard now would mean throwing it away, and would blur the line between
 * "authentication works" and "the product works".
 *
 * What it does demonstrate is that role information has travelled the whole way
 * from the database, through the token check, into the interface:
 *
 *     users.role in PostgreSQL
 *       -> GET /api/v1/auth/me
 *         -> AuthProvider
 *           -> useAuth()
 *             -> this page
 */

import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import { Alert, Box, Paper, Stack, Typography } from '@mui/material'

import useAuth from '../auth/useAuth'
import { roleLabel } from '../roles'

/** What each role will be able to do once the later slices land. */
const ROLE_DESCRIPTIONS = {
  EMPLOYEE:
    'You can report facility and workplace technology issues, track their progress, and add notes to your open tickets.',
  ENGINEER:
    'You can manage the tickets assigned to you, keep their status up to date, and communicate with the people who raised them.',
  FACILITY_ADMIN:
    'You can define buildings, floors and seats, manage engineer profiles, assign tickets, and oversee the full ticket lifecycle.',
}

export default function HomePage() {
  const { user } = useAuth()

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Welcome, {user.full_name}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          You are signed in as <strong>{roleLabel(user.role)}</strong>.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          <CheckCircleIcon color="success" />
          <Box>
            <Typography variant="subtitle1" gutterBottom>
              Your account
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
              {user.email}
            </Typography>
            <Typography variant="body2" sx={{ mt: 1.5 }}>
              {ROLE_DESCRIPTIONS[user.role]}
            </Typography>
          </Box>
        </Stack>
      </Paper>

      <Alert severity="info">
        Incident reporting, facilities management and dashboards are not built
        yet. This slice delivers sign-in, roles and permissions — the foundation
        everything else depends on.
      </Alert>
    </Stack>
  )
}
