/**
 * The sign-in screen.
 *
 * WHERE THIS SITS IN THE FLOW
 *     this form
 *       -> useAuth().login()
 *         -> api/client.js  POST /api/v1/auth/login
 *           -> Lambda router (public route, no token needed)
 *             -> domains/auth.login  verifies the password hash
 *               -> PostgreSQL
 *             <- {token, user}
 *         <- AuthProvider stores the token and sets status 'authenticated'
 *       -> this component redirects to wherever the user was heading
 *
 * NOTE ON ERROR MESSAGES
 * The backend intentionally answers "Invalid email or password." for both a
 * wrong password and an unknown address, so it cannot be used to discover which
 * employees have accounts. We show its message unchanged rather than trying to
 * be more helpful — being more specific here would undo that protection.
 */

import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Link as MuiLink,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink, Navigate, useLocation, useNavigate } from 'react-router-dom'

import useAuth from '../auth/useAuth'

export default function LoginPage() {
  const { status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  // Someone already signed in has no business on the login page — for example
  // after pressing Back. Send them on instead of showing a form that would only
  // sign them in as themselves again.
  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  async function handleSubmit(event) {
    // Without this the browser performs its own form submission and reloads the
    // page, throwing away all React state mid-request.
    event.preventDefault()

    setSubmitting(true)
    setErrorMessage('')

    try {
      await login(email.trim(), password)

      // ProtectedRoute stashed the page the user originally wanted in
      // `location.state.from`. Returning them there is the difference between
      // "sign in and carry on" and "sign in and go hunting for the page again".
      const destination = location.state?.from?.pathname || '/'
      navigate(destination, { replace: true })
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      // `finally` so the button is re-enabled on both success and failure. If
      // this only ran on success, a failed attempt would leave the form frozen
      // and the user unable to try again.
      setSubmitting(false)
    }
  }

  return (
    <Container maxWidth="sm" sx={{ py: { xs: 4, sm: 8 } }}>
      <Typography variant="h5" component="h1" align="center" gutterBottom>
        ACME Facility Incident Management
      </Typography>
      <Typography variant="body2" color="text.secondary" align="center" sx={{ mb: 3 }}>
        Sign in with your ACME account
      </Typography>

      <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 4 } }}>
        {/* A real <form> element, not a div with a click handler. It gives us
            Enter-to-submit, browser password-manager support and correct
            screen-reader behaviour for free. */}
        <Box component="form" onSubmit={handleSubmit} noValidate>
          <Stack spacing={2.5}>
            {errorMessage && <Alert severity="error">{errorMessage}</Alert>}

            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              fullWidth
              autoFocus
              // Tells password managers and mobile keyboards what this field is
              // for, which is a genuine accessibility and usability win.
              autoComplete="email"
              disabled={submitting}
              placeholder="you@acme.inc"
            />

            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              fullWidth
              autoComplete="current-password"
              disabled={submitting}
            />

            <Button
              type="submit"
              variant="contained"
              size="large"
              fullWidth
              // Disabled while the request is in flight so an impatient double
              // click cannot fire two login attempts.
              disabled={submitting || !email || !password}
              startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
            >
              {submitting ? 'Signing in...' : 'Sign in'}
            </Button>

            <Typography variant="body2" align="center" color="text.secondary">
              No account?{' '}
              {/* RouterLink navigates within the single-page app instead of
                  reloading the whole thing from the server. */}
              <MuiLink component={RouterLink} to="/register">
                Register with your ACME email
              </MuiLink>
            </Typography>
          </Stack>
        </Box>
      </Paper>
    </Container>
  )
}
