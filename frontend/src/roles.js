/**
 * How the three application roles are presented to people.
 *
 * The database stores roles as fixed uppercase strings — 'EMPLOYEE',
 * 'ENGINEER', 'FACILITY_ADMIN' — because they are compared in Python, matched
 * in SQL CHECK constraints, and carried inside login tokens. Those values must
 * never drift, so they are deliberately unglamorous.
 *
 * Showing 'FACILITY_ADMIN' in the interface would leak that implementation
 * detail at the user, so the translation to readable text happens here, once,
 * at the edge of the application.
 *
 * This lives in its own file rather than beside a component because Vite's
 * fast refresh only works cleanly when a file exports components OR plain
 * values, not both.
 *
 * The strings on the LEFT must match backend/v1/app/security.py exactly. The
 * text on the right is display only and can change freely.
 */

export const ROLE_LABELS = {
  EMPLOYEE: 'Employee',
  ENGINEER: 'Engineer',
  FACILITY_ADMIN: 'Facility Admin',
}

/**
 * Convert a stored role into readable text.
 *
 * Falls back to the raw value rather than showing nothing, so that a role added
 * to the backend before this file is updated still displays something
 * recognisable instead of a blank space.
 *
 * @param {string} role
 * @returns {string}
 */
export function roleLabel(role) {
  return ROLE_LABELS[role] || role
}
