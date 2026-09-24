/**
 * The conversation on one incident, plus the box for adding to it.
 *
 * Only rendered on the detail page, which the API has already decided the user
 * may see — the comments endpoint applies the same rule, so there is no separate
 * permission check here.
 *
 * A closed incident shows its history but hides the box, because the API rejects
 * new comments on it. Hiding the control is a courtesy; the refusal is the rule.
 */

import { useEffect, useState } from 'react'
import SendIcon from '@mui/icons-material/Send'
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'

import { createComment, listComments } from '../api/client'
import { formatDateTime } from '../incidents'
import { roleLabel } from '../roles'

// Matches MAX_BODY_LENGTH in backend/v1/app/domains/comments.py. The backend
// re-checks; this only spares the user a round trip.
const MAX_LENGTH = 2000

/** First letters of a name, for the avatar: "Ada Lovelace" -> "AL". */
function initials(name) {
  return (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
}

function Comment({ comment }) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start">
      <Avatar sx={{ width: 32, height: 32, fontSize: 13 }}>
        {initials(comment.author_name)}
      </Avatar>
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle2">{comment.author_name}</Typography>
          <Chip size="small" variant="outlined" label={roleLabel(comment.author_role)} />
          <Typography variant="caption" color="text.secondary">
            {formatDateTime(comment.created_at)}
          </Typography>
        </Stack>
        {/* pre-wrap keeps the line breaks the author typed. */}
        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {comment.body}
        </Typography>
      </Box>
    </Stack>
  )
}

export default function CommentThread({ incidentId, isClosed }) {
  const [status, setStatus] = useState('loading')
  const [comments, setComments] = useState([])
  const [loadError, setLoadError] = useState('')

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listComments(incidentId)
        if (!ignore) {
          setComments(data.comments)
          setStatus('success')
        }
      } catch (error) {
        if (!ignore) {
          setLoadError(error.message)
          setStatus('error')
        }
      }
    }

    load()

    return () => {
      ignore = true
    }
  }, [incidentId])

  async function handleSubmit(event) {
    event.preventDefault()

    const body = draft.trim()
    if (!body || sending) {
      return
    }

    setSending(true)
    setSendError('')

    try {
      const data = await createComment(incidentId, body)
      // Append the server's version rather than the text we typed, so the
      // author name, role and timestamp are the stored ones.
      setComments((current) => [...current, data.comment])
      setDraft('')
    } catch (error) {
      setSendError(error.message)
    } finally {
      setSending(false)
    }
  }

  const tooLong = draft.length > MAX_LENGTH

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Comments
      </Typography>

      {status === 'loading' && (
        <Stack alignItems="center" sx={{ py: 3 }}>
          <CircularProgress size={24} />
        </Stack>
      )}

      {status === 'error' && <Alert severity="error">{loadError}</Alert>}

      {status === 'success' && (
        <Stack spacing={2}>
          {comments.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No comments yet.
            </Typography>
          ) : (
            <Stack spacing={2}>
              {comments.map((comment) => (
                <Comment key={comment.id} comment={comment} />
              ))}
            </Stack>
          )}

          {isClosed ? (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="body2" color="text.secondary">
                This incident is closed. A Facility Admin must reopen it before further
                comments can be added.
              </Typography>
            </Paper>
          ) : (
            <Box component="form" onSubmit={handleSubmit}>
              {sendError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {sendError}
                </Alert>
              )}

              <TextField
                fullWidth
                multiline
                minRows={2}
                size="small"
                label="Add a comment"
                value={draft}
                disabled={sending}
                onChange={(event) => setDraft(event.target.value)}
                error={tooLong}
                helperText={
                  tooLong ? `Comments must be ${MAX_LENGTH} characters or fewer.` : ' '
                }
              />

              <Stack direction="row" justifyContent="flex-end">
                <Button
                  type="submit"
                  variant="contained"
                  size="small"
                  startIcon={<SendIcon />}
                  disabled={sending || !draft.trim() || tooLong}
                >
                  {sending ? 'Posting…' : 'Post comment'}
                </Button>
              </Stack>
            </Box>
          )}
        </Stack>
      )}
    </Box>
  )
}
