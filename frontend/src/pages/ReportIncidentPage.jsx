/**
 * Report Incident — the form for raising a new issue.
 *
 * There is no status field and no reporter field. Both are set by the backend
 * from the verified token, so there is nothing for the user to choose and
 * nothing for the form to send.
 */

import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'

import { createIncident } from '../api/client'
import { CATEGORIES, DEFAULT_PRIORITY, PRIORITIES } from '../incidents'

// Mirror the limits in backend/v1/app/domains/incidents.py so the user is told
// before submitting. The backend re-checks; these are for convenience only.
const MAX_TITLE_LENGTH = 200
const MAX_DESCRIPTION_LENGTH = 5000
const MAX_LOCATION_LENGTH = 200

export default function ReportIncidentPage() {
  const navigate = useNavigate()

  const [form, setForm] = useState({
    title: '',
    description: '',
    category: '',
    priority: DEFAULT_PRIORITY,
    location: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})

  function handleChange(field) {
    return (event) => {
      const { value } = event.target
      setForm((previous) => ({ ...previous, [field]: value }))
      setFieldErrors((previous) => ({ ...previous, [field]: '' }))
    }
  }

  function validate() {
    const errors = {}

    if (!form.title.trim()) {
      errors.title = 'Please give the issue a short title.'
    } else if (form.title.length > MAX_TITLE_LENGTH) {
      errors.title = `Must be ${MAX_TITLE_LENGTH} characters or fewer.`
    }

    if (!form.description.trim()) {
      errors.description = 'Please describe the problem.'
    } else if (form.description.length > MAX_DESCRIPTION_LENGTH) {
      errors.description = `Must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`
    }

    if (!form.category) {
      errors.category = 'Please choose a category.'
    }

    if (form.location.length > MAX_LOCATION_LENGTH) {
      errors.location = `Must be ${MAX_LOCATION_LENGTH} characters or fewer.`
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
      const { incident } = await createIncident({
        title: form.title.trim(),
        description: form.description.trim(),
        category: form.category,
        priority: form.priority,
        location: form.location.trim(),
      })

      // Go straight to the new incident so the user sees it was recorded, and
      // what its reference and status are.
      navigate(`/incidents/${incident.id}`, { replace: true })
    } catch (error) {
      // The backend names the offending field where it can, which is clearer
      // than a banner at the top of the form.
      if (error.details?.field) {
        setFieldErrors({ [error.details.field]: error.message })
      } else {
        setErrorMessage(error.message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Report an issue
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Tell us what is wrong and where. You can track progress on My Incidents.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: { xs: 2.5, sm: 3 } }}>
        <Box component="form" onSubmit={handleSubmit} noValidate>
          <Stack spacing={2.5}>
            {errorMessage && <Alert severity="error">{errorMessage}</Alert>}

            <TextField
              label="Title"
              value={form.title}
              onChange={handleChange('title')}
              required
              fullWidth
              autoFocus
              disabled={submitting}
              error={Boolean(fieldErrors.title)}
              helperText={fieldErrors.title || 'A short summary, e.g. "Leaking tap in kitchen"'}
            />

            <TextField
              label="Description"
              value={form.description}
              onChange={handleChange('description')}
              required
              fullWidth
              multiline
              minRows={4}
              disabled={submitting}
              error={Boolean(fieldErrors.description)}
              helperText={fieldErrors.description || 'What is happening, and since when?'}
            />

            <TextField
              label="Category"
              value={form.category}
              onChange={handleChange('category')}
              required
              fullWidth
              select
              disabled={submitting}
              error={Boolean(fieldErrors.category)}
              helperText={fieldErrors.category}
            >
              {CATEGORIES.map((category) => (
                <MenuItem key={category.value} value={category.value}>
                  {category.label}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              label="Priority"
              value={form.priority}
              onChange={handleChange('priority')}
              fullWidth
              select
              disabled={submitting}
              helperText="Defaults to Medium"
            >
              {PRIORITIES.map((priority) => (
                <MenuItem key={priority.value} value={priority.value}>
                  {priority.label}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              label="Location (optional)"
              value={form.location}
              onChange={handleChange('location')}
              fullWidth
              disabled={submitting}
              error={Boolean(fieldErrors.location)}
              helperText={fieldErrors.location || 'e.g. "Building A, 3rd floor kitchen"'}
            />

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={submitting}
                startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
              >
                {submitting ? 'Submitting...' : 'Submit report'}
              </Button>
              <Button
                variant="text"
                size="large"
                disabled={submitting}
                onClick={() => navigate('/incidents')}
              >
                Cancel
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Paper>
    </Stack>
  )
}
