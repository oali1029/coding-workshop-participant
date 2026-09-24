/**
 * Cascading Building → Floor → Seat selector for reporting an incident.
 *
 * Building and floor are required; a seat is not, because lifts, bathrooms,
 * kitchens and plant rooms have none.
 *
 * Each level loads only once its parent is chosen, and changing a parent clears
 * its children — otherwise you could submit a floor that belongs to a different
 * building. The backend rejects that anyway; this just stops the user reaching
 * an invalid state.
 *
 * Controlled by the parent form: it owns `value` and receives changes through
 * `onChange`, so the form keeps a single source of truth for what will be sent.
 */

import { useEffect, useState } from 'react'
import { Alert, MenuItem, Stack, TextField } from '@mui/material'

import { listBuildings, listFloors, listSeats } from '../api/client'

export default function LocationPicker({ value, onChange, disabled, errors = {} }) {
  const [buildings, setBuildings] = useState([])

  // Each child list records which parent it was loaded for. Deriving the
  // visible list from that is simpler than clearing state when the parent
  // changes, and it cannot briefly show another building's floors.
  const [floorData, setFloorData] = useState({ parent: null, items: [] })
  const [seatData, setSeatData] = useState({ parent: null, items: [] })
  const [loadError, setLoadError] = useState('')

  // Distinguishes "still loading" from "genuinely none", so we do not tell the
  // user the estate is empty before we have asked.
  const [loadedBuildings, setLoadedBuildings] = useState(false)

  useEffect(() => {
    let ignore = false

    async function load() {
      try {
        const data = await listBuildings()
        if (!ignore) {
          setBuildings(data.buildings)
        }
      } catch (error) {
        if (!ignore) {
          setLoadError(error.message)
        }
      } finally {
        if (!ignore) {
          setLoadedBuildings(true)
        }
      }
    }

    load()
    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    if (!value.buildingId) {
      return undefined
    }

    let ignore = false
    const parent = value.buildingId

    async function load() {
      try {
        const data = await listFloors(parent)
        if (!ignore) {
          setFloorData({ parent, items: data.floors })
        }
      } catch {
        if (!ignore) {
          setFloorData({ parent, items: [] })
        }
      }
    }

    load()
    return () => {
      ignore = true
    }
  }, [value.buildingId])

  useEffect(() => {
    if (!value.floorId) {
      return undefined
    }

    let ignore = false
    const parent = value.floorId

    async function load() {
      try {
        const data = await listSeats(parent)
        if (!ignore) {
          setSeatData({ parent, items: data.seats })
        }
      } catch {
        if (!ignore) {
          setSeatData({ parent, items: [] })
        }
      }
    }

    load()
    return () => {
      ignore = true
    }
  }, [value.floorId])

  const floors = floorData.parent === value.buildingId ? floorData.items : []
  const seats = seatData.parent === value.floorId ? seatData.items : []

  // Changing a building invalidates the floor and seat beneath it.
  function handleBuilding(event) {
    onChange({ buildingId: event.target.value, floorId: '', seatId: '' })
  }

  function handleFloor(event) {
    onChange({ ...value, floorId: event.target.value, seatId: '' })
  }

  function handleSeat(event) {
    onChange({ ...value, seatId: event.target.value })
  }

  if (loadError) {
    return <Alert severity="error">Could not load locations. {loadError}</Alert>
  }

  // Nothing can be reported until an admin has defined the estate. Saying so is
  // far better than presenting an empty dropdown that looks broken.
  if (loadedBuildings && buildings.length === 0) {
    return (
      <Alert severity="warning">
        No buildings have been set up yet. A facility administrator needs to add a
        building and a floor before incidents can be reported.
      </Alert>
    )
  }

  return (
    <Stack spacing={2.5}>
      <TextField
        select
        required
        fullWidth
        label="Building"
        value={value.buildingId}
        onChange={handleBuilding}
        disabled={disabled}
        error={Boolean(errors.building_id)}
        helperText={errors.building_id}
      >
        {buildings.map((building) => (
          <MenuItem key={building.id} value={building.id}>
            {building.name}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        required
        fullWidth
        label="Floor"
        value={value.floorId}
        onChange={handleFloor}
        disabled={disabled || !value.buildingId}
        error={Boolean(errors.floor_id)}
        helperText={
          errors.floor_id ||
          (!value.buildingId
            ? 'Choose a building first'
            : floors.length === 0
              ? 'This building has no floors yet'
              : '')
        }
      >
        {floors.map((floor) => (
          <MenuItem key={floor.id} value={floor.id}>
            {floor.name}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        fullWidth
        label="Seat (optional)"
        value={value.seatId}
        onChange={handleSeat}
        disabled={disabled || !value.floorId}
        error={Boolean(errors.seat_id)}
        helperText={
          errors.seat_id ||
          (!value.floorId
            ? 'Choose a floor first'
            : 'Leave blank for shared areas such as lifts, bathrooms or kitchens')
        }
      >
        <MenuItem value="">
          <em>No specific seat</em>
        </MenuItem>
        {seats.map((seat) => (
          <MenuItem key={seat.id} value={seat.id}>
            {seat.code}
          </MenuItem>
        ))}
      </TextField>
    </Stack>
  )
}
