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
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import SendIcon from '@mui/icons-material/Send'
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'

import { createComment, deleteComment, listComments, updateComment } from '../api/client'
import useAuth from '../auth/useAuth'
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

function Comment({ comment, canModify, onSave, onDelete, busy }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(comment.body)

  async function submit() {
    const body = draft.trim()
    if (!body) {
      return
    }
    const saved = await onSave(comment.id, body)
    if (saved) {
      setEditing(false)
    }
  }

  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: 'flex-start' }}>
      <Avatar sx={{ width: 32, height: 32, fontSize: 13 }}>
        {initials(comment.author_name)}
      </Avatar>
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography variant="subtitle2">{comment.author_name}</Typography>
          <Chip size="small" variant="outlined" label={roleLabel(comment.author_role)} />
          <Typography variant="caption" color="text.secondary">
            {formatDateTime(comment.created_at)}
          </Typography>
          {/* edited_at is set only by an edit, so its presence is the marker —
              a corrected note is visibly corrected rather than silently changed. */}
          {comment.edited_at && (
            <Tooltip title={`Edited ${formatDateTime(comment.edited_at)}`}>
              <Typography variant="caption" color="text.secondary">
                (edited)
              </Typography>
            </Tooltip>
          )}

          {canModify && !editing && (
            <Stack direction="row" sx={{ ml: 'auto' }}>
              <Tooltip title="Edit">
                <IconButton size="small" onClick={() => setEditing(true)} disabled={busy}>
                  <EditIcon fontSize="inherit" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Delete">
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => onDelete(comment.id)}
                  disabled={busy}
                >
                  <DeleteIcon fontSize="inherit" />
                </IconButton>
              </Tooltip>
            </Stack>
          )}
        </Stack>

        {editing ? (
          <Stack spacing={1} sx={{ mt: 1 }}>
            <TextField
              fullWidth
              multiline
              size="small"
              value={draft}
              disabled={busy}
              onChange={(event) => setDraft(event.target.value)}
              error={draft.length > MAX_LENGTH}
            />
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant="contained"
                onClick={submit}
                disabled={busy || !draft.trim() || draft.length > MAX_LENGTH}
              >
                Save
              </Button>
              <Button
                size="small"
                onClick={() => {
                  setDraft(comment.body)
                  setEditing(false)
                }}
              >
                Cancel
              </Button>
            </Stack>
          </Stack>
        ) : (
          /* pre-wrap keeps the line breaks the author typed. */
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {comment.body}
          </Typography>
        )}
      </Box>
    </Stack>
  )
}

export default function CommentThread({ incidentId, isClosed }) {
  const { user } = useAuth()
  const [status, setStatus] = useState('loading')
  const [comments, setComments] = useState([])
  const [loadError, setLoadError] = useState('')

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [busyId, setBusyId] = useState(null)

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

  /**
   * Save an edited note. Returns true so the row can leave edit mode only when
   * the server actually accepted it.
   */
  async function handleSave(commentId, body) {
    setBusyId(commentId)
    setSendError('')

    try {
      const data = await updateComment(incidentId, commentId, body)
      setComments((current) =>
        current.map((item) => (item.id === commentId ? data.comment : item)),
      )
      return true
    } catch (error) {
      setSendError(error.message)
      return false
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(commentId) {
    setBusyId(commentId)
    setSendError('')

    try {
      await deleteComment(incidentId, commentId)
      setComments((current) => current.filter((item) => item.id !== commentId))
    } catch (error) {
      setSendError(error.message)
    } finally {
      setBusyId(null)
    }
  }

  const tooLong = draft.length > MAX_LENGTH

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Comments
      </Typography>

      {status === 'loading' && (
        <Stack sx={{ alignItems: 'center', py: 3 }}>
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
                <Comment
                  key={comment.id}
                  comment={comment}
                  /* Authorship only — the backend refuses everyone else,
                     including admins, so this just hides a doomed button. A
                     closed incident seals the record entirely. */
                  canModify={comment.author_id === user.id && !isClosed}
                  onSave={handleSave}
                  onDelete={handleDelete}
                  busy={busyId === comment.id}
                />
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

              <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
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
