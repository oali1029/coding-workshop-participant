/**
 * Authenticated landing page.
 *
 * Intentionally minimal for this slice: it confirms who is signed in and with
 * what role, demonstrating that role data travelled from the users table
 * through the token check into the UI. Per-role dashboards belong to a later
 * slice, and a placeholder now would only be thrown away.
 */

import AddIcon from '@mui/icons-material/Add'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ListAltIcon from '@mui/icons-material/ListAlt'
import { Box, Button, Paper, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'

import useAuth from '../auth/useAuth'
import { roleLabel } from '../roles'

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
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'flex-start' }}>
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

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          component={RouterLink}
          to="/incidents/new"
        >
          Report an issue
        </Button>
        <Button
          variant="outlined"
          startIcon={<ListAltIcon />}
          component={RouterLink}
          to="/incidents"
        >
          View my incidents
        </Button>
      </Stack>
    </Stack>
  )
}
