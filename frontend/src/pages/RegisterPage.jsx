/**
 * The self-registration screen.
 *
 * PRODUCT RULES ENFORCED HERE
 *   - Only @acme.inc addresses may register.
 *   - The password must be confirmed, to catch typing mistakes.
 *   - New accounts always receive the EMPLOYEE role.
 *
 * WHICH OF THOSE ARE REAL
 * Only the third is enforced where it matters, and not by this file: the
 * backend hard-codes the role and never reads one from the request, so there is
 * no field here that could ask for anything else.
 *
 * The email and password checks in this file are CONVENIENCE ONLY. They give
 * instant feedback instead of a round trip, but anyone can skip the browser and
 * post straight to the API. The backend repeats both checks, and the database
 * carries a CHECK constraint on the email domain as a third layer. See
 * backend/v1/app/domains/auth.py.
 *
 * Client-side validation is therefore a usability feature, never a security
 * one — a distinction worth being precise about, because assuming otherwise is
 * one of the most common ways web applications get breached.
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

// Must match MIN_PASSWORD_LENGTH in backend/v1/app/domains/auth.py. Duplicated
// values like this are a maintenance risk; the alternative is an extra API call
// just to fetch a number, which is not worth it for a constant that changes
// roughly never. The backend remains the authority — if these ever disagree,
// the server's answer is the one that counts.
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

  // Per-field messages, shown under the relevant input rather than all together
  // at the top, so it is obvious which box needs attention.
  const [fieldErrors, setFieldErrors] = useState({})

  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  /**
   * One handler for every input, keyed by field name.
   *
   * Writing four near-identical handlers would be repetitive and easy to get
   * wrong by copy-paste. Clearing that field's error as the user types gives
   * immediate feedback that they have addressed it.
   */
  function handleChange(field) {
    return (event) => {
      const { value } = event.target
      setForm((previous) => ({ ...previous, [field]: value }))
      setFieldErrors((previous) => ({ ...previous, [field]: '' }))
    }
  }

  /**
   * Check the form before sending it.
   *
   * @returns {object} field name -> message, empty when everything is valid.
   */
  function validate() {
    const errors = {}

    if (!form.fullName.trim()) {
      errors.fullName = 'Please enter your name.'
    }

    const email = form.email.trim().toLowerCase()
    if (!email) {
      errors.email = 'Please enter your email address.'
    } else if (!email.endsWith(ACME_DOMAIN)) {
      // Matches the backend rule, which compares the same way after
      // lower-casing, so a capitalised domain is accepted in both places.
      errors.email = `Registration is restricted to ${ACME_DOMAIN} addresses.`
    }

    if (form.password.length < MIN_PASSWORD_LENGTH) {
      errors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`
    }

    // The entire purpose of the confirm field: a mistyped password would
    // otherwise lock someone out of an account they just created, with no way
    // to discover what they actually typed.
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

      // The backend signs the user in as part of registering, so there is no
      // separate login step — go straight to the app.
      navigate('/', { replace: true })
    } catch (error) {
      // The backend tells us which field it objected to when it can, for
      // example a duplicate email. Placing the message on that field is far
      // clearer than a generic banner.
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
              // Show the rule up front rather than only after a failed attempt.
              helperText={fieldErrors.email || `Must end in ${ACME_DOMAIN}`}
            />

            <TextField
              label="Password"
              type="password"
              value={form.password}
              onChange={handleChange('password')}
              required
              fullWidth
              // "new-password" specifically — it prompts password managers to
              // offer to generate and save one, rather than autofilling an
              // existing credential as "current-password" would.
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
