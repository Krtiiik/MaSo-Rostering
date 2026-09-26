# Rostering

Assigns registered helpers to buildings, rooms, and roles for a recurring
Czech math competition, based on stated preferences, using a constraint
solver.

## Language

### Rostering

**Season**:
One occurrence of the competition, held twice a year — spring ("jaro") and
autumn ("podzim") — named like `2026-jaro`. Each Season is solved as an
independent rostering problem: new helper responses, and often a different
Building/Room configuration, from every other Season.

**Helper**:
A volunteer who registered via the survey and is eligible to receive one of
the 6 solver-assigned Roles. Czech: pomocník.

**Simulace**:
A rehearsal for the competition, held before the event day.

**Organizer** *(planned, not yet implemented)*:
A second category of person, distinct from Helper, excluded from the
solver's Building/Room/Role assignment. People can still name an Organizer
in their Friend preference, and an Organizer is intended to be manually
assignable to Buildings/Rooms and to special roles, including before the
solver runs.

**Building**:
A venue hosting part of the competition. The set of Buildings is not stable
across Seasons — always driven by that Season's configuration, never
hardcoded.

**Room**:
A room within a Building. Room groupings also change Season to Season —
rooms get merged or split.

**Building preference**:
The set of Buildings a Helper marked as acceptable on the survey (a
multi-select question, not a single ranked choice). Satisfied if the
Helper's assigned Building is in the set, or the set is empty (no
preference expressed).

**Equipment eligibility**:
A hard constraint gating two Roles: a Helper who didn't mark that they can
bring a notebook cannot be assigned Kreslič, and one who didn't mark a
camera cannot be assigned Fotograf.

**Preference**:
A Helper's 5-point ordinal rating of one Role, from most to least willing:
Ano ("yes") → Klidně ("sure") → Nevadí ("don't mind") → Spíš ne ("rather
not") → Ne ("no").

**Friend preference**:
A Helper's soft request to share a Room with another named person —
minimized-if-unsatisfied, never a hard constraint. Configurable as
`pairwise` (each request scores independently) or `mutual` (only
reciprocated requests count), and as `symmetric` (a reciprocated pair
merges into one scored unit) or not (each direction scores separately).

**Assignment**:
The solver's output for one Helper: the Building, Room, and Role they're
placed into.

#### Solver roles

**Role**:
The single Role the solver assigns to each Helper — exactly one, from a
fixed set of 6. Distinct from Organizer role and Additional role, which are
assigned by hand, not by the solver.

**Opravovatel**:
Corrector/grader.

**Měnič**:
"Changer" — swaps/exchanges papers or materials between rounds.

**Skenovač**:
Scans solutions.

**Kreslič**:
Draws problems/diagrams. Requires Equipment eligibility for a notebook.

**Fotograf**:
Photographer. Requires Equipment eligibility for a camera.

**Záloha**:
Reserve/overflow. Not a Preference option on the survey; absorbs excess
Helpers with no capacity limit.

#### Manual roles

**Manual roles**:
Any role assigned by hand after the solver runs, rather than by the solver
itself — covers Organizer role and Additional role.
_Avoid_: Out-of-solver roles

**Organizer role**:
A Manual role for Building/Room leadership or support duties, independent
of the assignee's solved Role — intended for an Organizer, though today
(before Organizer is a tracked entity) it's filled by a registered Helper's
id or a hand-typed name for someone unregistered.
_Avoid_: Structural role

**Vedoucí budovy**:
Building lead. An Organizer role, scoped to one Building.

**Pravá ruka**:
Deputy to the Vedoucí budovy. An Organizer role, scoped to one Building or
Room.

**Vedoucí místností**:
Room lead. An Organizer role, scoped to one Room.

**Technická podpora**:
Technical support. An Organizer role, scoped to one Building.

**Additional role**:
A Manual role a Helper keeps in addition to their solved Role, since the
duties happen before/after the event and don't conflict in time. Scoped to
wherever the Helper is already solved into — Registrace by Building, the
other two by Room.
_Avoid_: Overlay role

**Registrace**:
Registration desk. An Additional role, scoped to a Building.

**Uvaděči účastníků**:
Participant ushering. An Additional role, scoped to a Room.

**Focení předávání cen**:
Photographing the award ceremony. An Additional role, scoped to a Room.

### Application

**Workspace**:
The web app's single current session: whatever Season's data is currently
loaded, plus every edit made since. There is exactly one Workspace — no
picking between multiple in-progress Seasons at once.

**Version**:
A named, timestamped snapshot of the Workspace's state, saved and
restorable on demand.
