/**
 * The search and filter bar shared by all three incident lists.
 *
 * One component rather than three, because the controls are identical — what
 * differs is the scope the backend applies before them. The assignee dropdown is
 * admin-only and simply not rendered elsewhere; honouring it on a personal list
 * could only ever be a way to probe somebody else's work, and the backend
 * ignores it there regardless.
 *
 * Search is debounced so typing a word does not fire a request per keystroke;
 * the dropdowns apply immediately, since one click is one intent.
 */

import ClearIcon from '@mui/icons-material/Clear'
import SearchIcon from '@mui/icons-material/Search'
import {
  Button,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
} from '@mui/material'

import { UNASSIGNED } from '../filters'
import { ADMIN_SETTABLE, CATEGORIES, PRIORITIES, statusDisplay } from '../incidents'

/**
 * @param search - the raw text in the box, owned by the page so it can debounce.
 * @param engineers - assignee options; omit to hide the assignee dropdown.
 */
export default function IncidentFilters({
  search,
  onSearchChange,
  filters,
  onFilterChange,
  onClear,
  buildings = [],
  engineers = null,
  isFiltered,
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <TextField
          fullWidth
          size="small"
          label="Search"
          placeholder="Title, description, reporter or engineer"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />

        {/* Wraps rather than scrolling, so every control stays reachable on a
            phone without a horizontal swipe.

            flexWrap belongs in sx, not in a prop: Stack takes only its own
            props plus sx, so `flexWrap="wrap"` would land on the DOM node and
            never become CSS — leaving the row unable to wrap and the last
            dropdown overflowing the panel. */}
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          useFlexGap
          sx={{ flexWrap: 'wrap' }}
        >
          <TextField
            select
            size="small"
            label="Status"
            value={filters.status}
            onChange={(event) => onFilterChange('status', event.target.value)}
            sx={{ minWidth: 170 }}
          >
            <MenuItem value="">Any status</MenuItem>
            {ADMIN_SETTABLE.map((value) => (
              <MenuItem key={value} value={value}>
                {statusDisplay(value).label}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label="Priority"
            value={filters.priority}
            onChange={(event) => onFilterChange('priority', event.target.value)}
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="">Any priority</MenuItem>
            {PRIORITIES.map((priority) => (
              <MenuItem key={priority.value} value={priority.value}>
                {priority.label}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label="Category"
            value={filters.category}
            onChange={(event) => onFilterChange('category', event.target.value)}
            sx={{ minWidth: 170 }}
          >
            <MenuItem value="">Any category</MenuItem>
            {CATEGORIES.map((category) => (
              <MenuItem key={category.value} value={category.value}>
                {category.label}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label="Building"
            value={filters.building}
            onChange={(event) => onFilterChange('building', event.target.value)}
            sx={{ minWidth: 170 }}
          >
            <MenuItem value="">Any building</MenuItem>
            {buildings.map((building) => (
              <MenuItem key={building.id} value={building.id}>
                {building.name}
              </MenuItem>
            ))}
          </TextField>

          {engineers && (
            <TextField
              select
              size="small"
              label="Assigned to"
              value={filters.assignee}
              onChange={(event) => onFilterChange('assignee', event.target.value)}
              sx={{ minWidth: 190 }}
            >
              <MenuItem value="">Anyone</MenuItem>
              <MenuItem value={UNASSIGNED}>Unassigned</MenuItem>
              {engineers.map((engineer) => (
                <MenuItem key={engineer.id} value={engineer.id}>
                  {engineer.full_name}
                </MenuItem>
              ))}
            </TextField>
          )}

          {isFiltered && (
            <Button size="small" startIcon={<ClearIcon />} onClick={onClear}>
              Clear
            </Button>
          )}
        </Stack>
      </Stack>
    </Paper>
  )
}

