/**
 * Facilities — where a Facility Admin defines the estate.
 *
 * Three columns that drill down: choosing a building loads its floors, choosing
 * a floor loads its seats. The same shape the reporter's location picker uses,
 * which makes it self-explanatory.
 *
 * Nothing can be reported until at least one building and floor exist, so this
 * is the first page an admin visits on a new deployment.
 */

import { useCallback, useEffect, useState } from 'react'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Grid,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'

import {
  createBuilding,
  createFloor,
  createSeat,
  deleteBuilding,
  deleteFloor,
  deleteSeat,
  listBuildings,
  listFloors,
  listSeats,
} from '../api/client'

/**
 * One column of the drill-down: a heading, a list, and an add field.
 *
 * Written once and used three times rather than copying the markup, so the
 * columns stay visually identical.
 */
function FacilityColumn({
  title,
  hint,
  items,
  labelOf,
  selectedId,
  onSelect,
  onAdd,
  onDelete,
  addLabel,
  disabled,
  busy,
}) {
  const [draft, setDraft] = useState('')

  async function handleAdd(event) {
    event.preventDefault()
    if (!draft.trim()) {
      return
    }
    await onAdd(draft.trim())
    setDraft('')
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
      <Typography variant="subtitle1" gutterBottom>
        {title}
      </Typography>

      {disabled ? (
        <Typography variant="body2" color="text.secondary">
          {hint}
        </Typography>
      ) : (
        <>
          {items.length === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              None yet.
            </Typography>
          )}

          <List dense disablePadding>
            {items.map((item) => (
              <ListItemButton
                key={item.id}
                selected={item.id === selectedId}
                onClick={() => onSelect && onSelect(item.id)}
                sx={{ borderRadius: 1 }}
              >
                <ListItemText primary={labelOf(item)} />
                <IconButton
                  edge="end"
                  size="small"
                  aria-label={`Delete ${labelOf(item)}`}
                  disabled={busy}
                  onClick={(event) => {
                    // Without this the click also selects the row underneath.
                    event.stopPropagation()
                    onDelete(item)
                  }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </ListItemButton>
            ))}
          </List>

          <Box component="form" onSubmit={handleAdd} sx={{ mt: 2 }}>
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                fullWidth
                label={addLabel}
                value={draft}
                disabled={busy}
                onChange={(event) => setDraft(event.target.value)}
              />
              <Button type="submit" variant="outlined" disabled={busy || !draft.trim()}>
                <AddIcon fontSize="small" />
              </Button>
            </Stack>
          </Box>
        </>
      )}
    </Paper>
  )
}

export default function AdminFacilitiesPage() {
  const [buildings, setBuildings] = useState([])
  const [floors, setFloors] = useState([])
  const [seats, setSeats] = useState([])

  const [buildingId, setBuildingId] = useState(null)
  const [floorId, setFloorId] = useState(null)

  const [errorMessage, setErrorMessage] = useState('')
  const [busy, setBusy] = useState(false)

  // What the confirmation dialog is about to delete, or null when closed.
  const [pendingDelete, setPendingDelete] = useState(null)

  const loadBuildings = useCallback(async () => {
    const data = await listBuildings()
    setBuildings(data.buildings)
  }, [])

  useEffect(() => {
    async function load() {
      try {
        await loadBuildings()
      } catch (error) {
        setErrorMessage(error.message)
      }
    }
    load()
  }, [loadBuildings])

  // The `.then` keeps these setState calls out of the synchronous effect body;
  // the early return does no state work at all, so a cleared selection simply
  // leaves the previous list in place and the render below ignores it.
  useEffect(() => {
    if (!buildingId) {
      return
    }
    listFloors(buildingId)
      .then((data) => setFloors(data.floors))
      .catch((error) => setErrorMessage(error.message))
  }, [buildingId])

  useEffect(() => {
    if (!floorId) {
      return
    }
    listSeats(floorId)
      .then((data) => setSeats(data.seats))
      .catch((error) => setErrorMessage(error.message))
  }, [floorId])

  /** Run a mutation, then refresh whichever lists it could have changed. */
  async function run(action) {
    setBusy(true)
    setErrorMessage('')
    try {
      await action()
      await loadBuildings()
      if (buildingId) {
        setFloors((await listFloors(buildingId)).floors)
      }
      if (floorId) {
        setSeats((await listSeats(floorId)).seats)
      }
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function confirmDelete() {
    const target = pendingDelete
    setPendingDelete(null)

    await run(async () => {
      if (target.kind === 'building') {
        await deleteBuilding(target.item.id)
        // Selecting a deleted building would leave the other columns stale.
        if (buildingId === target.item.id) {
          setBuildingId(null)
          setFloorId(null)
        }
      } else if (target.kind === 'floor') {
        await deleteFloor(target.item.id)
        if (floorId === target.item.id) {
          setFloorId(null)
        }
      } else {
        await deleteSeat(target.item.id)
      }
    })
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" gutterBottom>
          Facilities
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Define the buildings, floors and seats people choose from when reporting
          an issue. At least one building and floor are needed before anyone can
          report.
        </Typography>
      </Box>

      {errorMessage && <Alert severity="error">{errorMessage}</Alert>}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 4 }}>
          <FacilityColumn
            title="Buildings"
            items={buildings}
            labelOf={(b) => b.name}
            selectedId={buildingId}
            onSelect={(id) => {
              setBuildingId(id)
              setFloorId(null)
            }}
            onAdd={(name) => run(() => createBuilding({ name }))}
            onDelete={(item) => setPendingDelete({ kind: 'building', item })}
            addLabel="New building"
            busy={busy}
          />
        </Grid>

        <Grid size={{ xs: 12, md: 4 }}>
          <FacilityColumn
            title="Floors"
            hint="Select a building to see its floors."
            items={buildingId ? floors : []}
            labelOf={(f) => f.name}
            selectedId={floorId}
            onSelect={setFloorId}
            onAdd={(name) => run(() => createFloor({ buildingId, name }))}
            onDelete={(item) => setPendingDelete({ kind: 'floor', item })}
            addLabel="New floor"
            disabled={!buildingId}
            busy={busy}
          />
        </Grid>

        <Grid size={{ xs: 12, md: 4 }}>
          <FacilityColumn
            title="Seats"
            hint="Select a floor to see its seats."
            items={floorId ? seats : []}
            labelOf={(s) => s.code}
            onAdd={(code) => run(() => createSeat({ floorId, code }))}
            onDelete={(item) => setPendingDelete({ kind: 'seat', item })}
            addLabel="New seat"
            disabled={!floorId}
            busy={busy}
          />
        </Grid>
      </Grid>

      {/* Deleting a building takes its floors and seats with it, and detaches
          any incidents reported there — so the consequences are spelled out. */}
      <Dialog open={Boolean(pendingDelete)} onClose={() => setPendingDelete(null)}>
        <DialogTitle>Delete this {pendingDelete?.kind}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {pendingDelete?.kind === 'building' &&
              'Its floors and seats will be deleted too. Incidents reported there are kept, and will show the location recorded when they were reported.'}
            {pendingDelete?.kind === 'floor' &&
              'Its seats will be deleted too. Incidents reported there are kept, and will show the location recorded when they were reported.'}
            {pendingDelete?.kind === 'seat' &&
              'Incidents reported at this seat are kept, and will show the location recorded when they were reported.'}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingDelete(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDelete}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
