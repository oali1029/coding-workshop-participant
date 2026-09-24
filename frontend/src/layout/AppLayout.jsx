/**
 * Frame for every signed-in page: top bar, user identity, sign-out, and the
 * current page rendered via <Outlet />.
 *
 * Responsiveness is split deliberately. Layout adjustments use MUI's `sx`
 * breakpoints, which are plain CSS. Changes to what is *rendered at all* use
 * react-responsive, because that is a JavaScript decision — on a phone the name
 * is dropped and the sign-out button becomes an icon.
 */

import LogoutIcon from '@mui/icons-material/Logout'
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart'
import {
  AppBar,
  Box,
  Button,
  Chip,
  Container,
  IconButton,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material'
import { useMediaQuery } from 'react-responsive'
import { Link as RouterLink, Outlet, useNavigate } from 'react-router-dom'

import useAuth from '../auth/useAuth'
import { ROLE_ENGINEER, ROLE_FACILITY_ADMIN, roleLabel } from '../roles'

export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isCompact = useMediaQuery({ maxWidth: 700 })

  // Hiding links from other roles is presentation only — the endpoints behind
  // them refuse the wrong role regardless.
  const isAdmin = user.role === ROLE_FACILITY_ADMIN
  // Admins have no work queue: they are never assignees, so it would be empty.
  const isEngineer = user.role === ROLE_ENGINEER

  function handleLogout() {
    logout()
    // ProtectedRoute would redirect anyway, but navigating explicitly makes the
    // button's effect immediate and obvious.
    navigate('/login', { replace: true })
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static">
        <Toolbar>
          <Typography
            variant="h6"
            component={RouterLink}
            to="/"
            sx={{ color: 'inherit', textDecoration: 'none' }}
          >
            {isCompact ? 'ACME Incidents' : 'ACME Facility Incident Management'}
          </Typography>

          {/* Primary navigation. Labels are shortened on a phone, where the
              toolbar has no room for them alongside the user controls.

              An admin has more destinations than fit on a narrow screen, so the
              row scrolls sideways rather than hiding links. Buttons must not
              shrink, or they would squash into unreadable wrapped text instead. */}
          <Stack
            direction="row"
            spacing={1}
            sx={{
              flexGrow: 1,
              ml: { xs: 1, sm: 3 },
              overflowX: 'auto',
              '& .MuiButton-root': { flexShrink: 0 },
            }}
          >
            <Button color="inherit" component={RouterLink} to="/incidents" size="small">
              {isCompact ? 'Incidents' : 'My Incidents'}
            </Button>
            {!isCompact && (
              <Button color="inherit" component={RouterLink} to="/incidents/new" size="small">
                Report Issue
              </Button>
            )}
            {isEngineer && (
              <Button color="inherit" component={RouterLink} to="/assigned" size="small">
                Assigned
              </Button>
            )}
            {isAdmin && (
              <Button color="inherit" component={RouterLink} to="/admin/incidents" size="small">
                {isCompact ? 'All' : 'All Incidents'}
              </Button>
            )}
            {isAdmin && (
              <Button color="inherit" component={RouterLink} to="/admin/users" size="small">
                Users
              </Button>
            )}
            {isAdmin && (
              <Button color="inherit" component={RouterLink} to="/admin/analytics" size="small">
                Analytics
              </Button>
            )}
            {isAdmin && (
              <Button color="inherit" component={RouterLink} to="/admin/facilities" size="small">
                Facilities
              </Button>
            )}
          </Stack>

          <Stack direction="row" spacing={isCompact ? 0.5 : 1.5} sx={{ alignItems: 'center' }}>
            {/* The Slice 0 status page, kept reachable without competing with
                the product for space. */}
            <Tooltip title="System status">
              <IconButton color="inherit" onClick={() => navigate('/status')} size="small">
                <MonitorHeartIcon />
              </IconButton>
            </Tooltip>

            {/* Display only — it grants nothing; the backend decides access. */}
            <Chip
              label={roleLabel(user.role)}
              size="small"
              sx={{ bgcolor: 'rgba(255,255,255,0.18)', color: 'inherit', fontWeight: 600 }}
            />

            {/* Widest element, so the first dropped when space is tight. */}
            {!isCompact && (
              <Typography variant="body2" sx={{ maxWidth: 220 }} noWrap>
                {user.full_name}
              </Typography>
            )}

            {isCompact ? (
              <Tooltip title="Sign out">
                <IconButton color="inherit" onClick={handleLogout} size="small">
                  <LogoutIcon />
                </IconButton>
              </Tooltip>
            ) : (
              <Button color="inherit" startIcon={<LogoutIcon />} onClick={handleLogout}>
                Sign out
              </Button>
            )}
          </Stack>
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        <Outlet />
      </Container>
    </Box>
  )
}
