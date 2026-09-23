/**
 * Sign-in screen.
 *
 * The backend answers "Invalid email or password." for both a wrong password
 * and an unknown address, so it cannot be used to discover which employees have
 * accounts. We show its message unchanged rather than trying to be more
 * helpful, which would undo that.
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

  // Someone already signed in has no use for this page, e.g. after pressing Back.
  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  async function handleSubmit(event) {
    event.preventDefault()

    setSubmitting(true)
    setErrorMessage('')

    try {
      await login(email.trim(), password)

      // ProtectedRoute recorded where the user was heading, so sign-in resumes
      // that journey rather than dropping everyone on the home page.
      navigate(location.state?.from?.pathname || '/', { replace: true })
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      // Also on failure, or a rejected attempt would leave the form frozen.
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
        {/* A real <form>: gives Enter-to-submit, password-manager support and
            correct screen-reader behaviour without extra code. */}
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
              disabled={submitting || !email || !password}
              startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
            >
              {submitting ? 'Signing in...' : 'Sign in'}
            </Button>

            <Typography variant="body2" align="center" color="text.secondary">
              No account?{' '}
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
