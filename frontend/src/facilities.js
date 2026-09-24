/**
 * Helpers for displaying incident locations.
 *
 * An incident stores its location twice: as live references to the building,
 * floor and seat, and as a text snapshot written when it was reported. The
 * snapshot is what survives if an admin later deletes the facility, so these
 * helpers prefer live names and fall back to it.
 */

// Must match the separator the backend uses when it writes location_snapshot
// (see _resolve_location in backend/v1/app/domains/incidents.py), because
// buildingLabel splits a stored snapshot on it.
const SEPARATOR = ' > '

/**
 * Full location path for an incident, e.g. "Building A › Floor 3 › A-312".
 *
 * Falls back to the snapshot for incidents whose facility has been deleted,
 * then to the old free-text column for incidents reported before Slice 5.
 */
export function locationPath(incident) {
  const parts = [incident.building_name, incident.floor_name, incident.seat_code].filter(Boolean)

  if (parts.length > 0) {
    return parts.join(SEPARATOR)
  }

  return incident.location_snapshot || incident.location || null
}

/**
 * Just the building, for list columns where a full path is too wide.
 *
 * Reads the building out of the snapshot when the live reference is gone, so a
 * deleted building still shows a name rather than a dash.
 */
export function buildingLabel(incident) {
  if (incident.building_name) {
    return incident.building_name
  }

  if (incident.location_snapshot) {
    return incident.location_snapshot.split(SEPARATOR)[0]
  }

  return null
}

/** True when the facility this incident referenced has since been deleted. */
export function isLocationArchived(incident) {
  return !incident.building_name && Boolean(incident.location_snapshot)
}
