/**
 * The frame every signed-in page is rendered inside.
 *
 * Holds the top bar, the navigation links, the signed-in user's identity and
 * the sign-out button, then renders the current page beneath via `<Outlet />`.
 *
 * Putting this in one place means a page component only has to describe its own
 * content; it never repeats the header or worries about the logout button.
 *
 * RESPONSIVENESS
 * The bar adapts at phone width in two different ways, chosen deliberately:
 *
 *   - Layout changes (spacing, which text is shown) use MUI's `sx` breakpoints,
 *     because those are pure CSS and cost nothing.
 *   - Changes to what is RENDERED at all use `react-responsive`'s
 *     `useMediaQuery`, because that is a JavaScript decision. On a phone the
 *     role is shown as a compact chip and the navigation collapses to icons.
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
import { Outlet, useNavigate } from 'react-router-dom'

import useAuth from '../auth/useAuth'
import { roleLabel } from '../roles'

export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isCompact = useMediaQuery({ maxWidth: 700 })

  function handleLogout() {
    logout()
    // Send the user to the login screen explicitly. ProtectedRoute would also
    // redirect them, but doing it here makes the outcome of pressing the button
    // obvious rather than an indirect consequence.
    navigate('/login', { replace: true })
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" component="h1" sx={{ flexGrow: 1 }}>
            {isCompact ? 'ACME Incidents' : 'ACME Facility Incident Management'}
          </Typography>

          <Stack direction="row" spacing={isCompact ? 0.5 : 1.5} alignItems="center">
            {/* The system status page from Slice 0 is preserved, demoted to an
                icon in the toolbar so it stays reachable without competing with
                the product itself. */}
            <Tooltip title="System status">
              <IconButton color="inherit" onClick={() => navigate('/status')} size="small">
                <MonitorHeartIcon />
              </IconButton>
            </Tooltip>

            {/* Role awareness in the UI. For this slice that is all it does —
                display. It grants nothing; the backend decides permissions. */}
            <Chip
              label={roleLabel(user.role)}
              size="small"
              sx={{ bgcolor: 'rgba(255,255,255,0.18)', color: 'inherit', fontWeight: 600 }}
            />

            {/* The name is the widest element here, so it is the first thing
                dropped when space is tight. */}
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
        {/* Whichever protected page matched the current URL renders here. */}
        <Outlet />
      </Container>
    </Box>
  )
}
