/**
 * Self-registration screen.
 *
 * The checks in this file are convenience only — they give instant feedback
 * instead of a round trip, but anyone can bypass the browser and post straight
 * to the API. The backend repeats them and the database carries a CHECK
 * constraint on the email domain. See backend/v1/app/domains/auth.py.
 *
 * There is no role selector, and adding one would achieve nothing: the backend
 * never reads a role from the request and always assigns EMPLOYEE.
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
import { Link as RouterLink, Navigate, useNavigate } from 'react-router-dom'

import useAuth from '../auth/useAuth'

// Mirrors MIN_PASSWORD_LENGTH in backend/v1/app/domains/auth.py. Duplicated
// rather than fetched, for a constant that changes roughly never; if they ever
// disagree, the server's answer is the one that counts.
const MIN_PASSWORD_LENGTH = 8
const ACME_DOMAIN = '@acme.inc'

export default function RegisterPage() {
  const { status, register } = useAuth()
  const navigate = useNavigate()

  const [form, setForm] = useState({
    fullName: '',
    email: '',
    password: '',
    confirmPassword: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})

  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  // One handler for all inputs; clearing the field's error as the user types
  // confirms they have addressed it.
  function handleChange(field) {
    return (event) => {
      const { value } = event.target
      setForm((previous) => ({ ...previous, [field]: value }))
      setFieldErrors((previous) => ({ ...previous, [field]: '' }))
    }
  }

  function validate() {
    const errors = {}

    if (!form.fullName.trim()) {
      errors.fullName = 'Please enter your name.'
    }

    const email = form.email.trim().toLowerCase()
    if (!email) {
      errors.email = 'Please enter your email address.'
    } else if (!email.endsWith(ACME_DOMAIN)) {
      errors.email = `Registration is restricted to ${ACME_DOMAIN} addresses.`
    }

    if (form.password.length < MIN_PASSWORD_LENGTH) {
      errors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`
    }

    // The whole point of the confirm field: a mistyped password would lock
    // someone out of an account they just created.
    if (form.confirmPassword !== form.password) {
      errors.confirmPassword = 'Passwords do not match.'
    }

    return errors
  }

  async function handleSubmit(event) {
    event.preventDefault()

    const errors = validate()
    setFieldErrors(errors)
    setErrorMessage('')

    if (Object.keys(errors).length > 0) {
      return
    }

    setSubmitting(true)

    try {
      await register({
        fullName: form.fullName.trim(),
        email: form.email.trim(),
        password: form.password,
      })

      // Registration returns a token, so there is no separate sign-in step.
      navigate('/', { replace: true })
    } catch (error) {
      // The backend names the offending field where it can (e.g. a duplicate
      // email), which is clearer than a generic banner.
      if (error.details?.field) {
        setFieldErrors({ [error.details.field]: error.message })
      } else if (error.status === 409) {
        setFieldErrors({ email: error.message })
      } else {
        setErrorMessage(error.message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Container maxWidth="sm" sx={{ py: { xs: 4, sm: 8 } }}>
      <Typography variant="h5" component="h1" align="center" gutterBottom>
        Create your account
      </Typography>
      <Typography variant="body2" color="text.secondary" align="center" sx={{ mb: 3 }}>
        Registration is open to ACME employees with an {ACME_DOMAIN} address
      </Typography>

      <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 4 } }}>
        <Box component="form" onSubmit={handleSubmit} noValidate>
          <Stack spacing={2.5}>
            {errorMessage && <Alert severity="error">{errorMessage}</Alert>}

            <TextField
              label="Full name"
              value={form.fullName}
              onChange={handleChange('fullName')}
              required
              fullWidth
              autoFocus
              autoComplete="name"
              disabled={submitting}
              error={Boolean(fieldErrors.fullName)}
              helperText={fieldErrors.fullName}
            />

            <TextField
              label="ACME email"
              type="email"
              value={form.email}
              onChange={handleChange('email')}
              required
              fullWidth
              autoComplete="email"
              disabled={submitting}
              placeholder={`you${ACME_DOMAIN}`}
              error={Boolean(fieldErrors.email)}
              // State the rule up front rather than only after a failure.
              helperText={fieldErrors.email || `Must end in ${ACME_DOMAIN}`}
            />

            <TextField
              label="Password"
              type="password"
              value={form.password}
              onChange={handleChange('password')}
              required
              fullWidth
              // "new-password" prompts managers to generate and save one,
              // rather than autofilling an existing credential.
              autoComplete="new-password"
              disabled={submitting}
              error={Boolean(fieldErrors.password)}
              helperText={fieldErrors.password || `At least ${MIN_PASSWORD_LENGTH} characters`}
            />

            <TextField
              label="Confirm password"
              type="password"
              value={form.confirmPassword}
              onChange={handleChange('confirmPassword')}
              required
              fullWidth
              autoComplete="new-password"
              disabled={submitting}
              error={Boolean(fieldErrors.confirmPassword)}
              helperText={fieldErrors.confirmPassword}
            />

            <Button
              type="submit"
              variant="contained"
              size="large"
              fullWidth
              disabled={submitting}
              startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
            >
              {submitting ? 'Creating account...' : 'Create account'}
            </Button>

            <Typography variant="body2" align="center" color="text.secondary">
              Already registered?{' '}
              <MuiLink component={RouterLink} to="/login">
                Sign in
              </MuiLink>
            </Typography>
          </Stack>
        </Box>
      </Paper>
    </Container>
  )
}
