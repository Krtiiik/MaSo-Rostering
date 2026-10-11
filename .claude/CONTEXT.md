# Rostering

Assigns registered helpers to buildings, rooms, and roles for a recurring
Czech math competition, based on stated preferences, using a constraint
solver.

## Language

The app's front end is Czech. Terms below are English (as in code); each
carries its Czech UI name on a `Czech:` line. UI-only labels (tabs, actions)
are in `docs/czech-ui-glossary.md`.

Everything the user sees in the web app is Czech; code, identifiers, CLI usage
and developer docs stay English. Use the `Czech:` names below and the labels in
`docs/czech-ui-glossary.md` verbatim. Tab labels live in
`rostering/webapp/labels.py` (they double as the tab strip's values); counted
text goes through `rostering.czech.plural`. Values persisted in a Season's
state (for example the "answers changed" field names) keep English identifiers
and are translated only where they are displayed. A new UI string or a new
message raised to the user must be written in Czech from the start (the roster
grid's strings are in `rostering/webapp/ui/grid/render.py`; it has no build
step).

### Rostering

**Season**:
One occurrence of the competition, held twice a year — spring ("jaro") and
autumn ("podzim") — named like `2026-jaro`. Each Season is solved as an
independent rostering problem: new helper responses, and often a different
Building/Room configuration, from every other Season. A Season is identified
by a required label — a year plus jaro/podzim — that is unique among stored
Seasons, editable, and what orders Seasons in time. Every Season the app has
worked on stays stored, not only the current one.
Czech: Ročník.

**Helper**:
A volunteer who registered via the survey and is eligible to receive one of
the 6 solver-assigned Roles. Czech: Pomocník.

**Hand-added Helper**:
A Helper entered directly into the app rather than parsed from the survey. Only
name and contact are required; every other field is optional and left at its
normal empty/no-preference default. Otherwise an ordinary Helper.
Czech: Manuálně přidaný pomocník.

**Locked Assignment**:
An Assignment the user has fixed by hand so that a full Solve keeps it. A lock
pins Building, Room and Role together, belongs to one Season's roster, and never
validates: a locked Assignment may break a rule, and the rule bends, never the
lock.
Czech: Uzamčené přiřazení; the lock itself is "Zámek".

**Can't attend**:
A per-Helper (or per-Organizer) flag marking them unavailable for the Season:
excluded from the solver and absent from the roster grid while set. Reversible
at any time; flagging a placed person asks first, then clears their Assignment
and Manual role entries and makes the roster stale.
Czech: Nemůže se zúčastnit.

**Roster**:
The full set of Assignments for a Season — who is placed where, and in what
Role — as the solver produced it and hand edits have left it.
Czech: Rozdělení pomocníků.

**Stale roster**:
A roster that no longer matches the Helpers and rules it was solved for, though
nobody was moved (e.g. after clearing a Can't attend Helper's placement). A
banner near Solve gives the reason, Export is blocked until the next full
Solve, which clears it. Saved with Versions.
Czech: Neaktuální rozdělení pomocníků.

**Re-upload**:
Uploading a newer survey export into the open Season. It never moves or deletes
hand work: a recognized Helper refreshes their survey-derived fields, a new
registrant gets a fresh id and no Assignment, a Helper missing from the export
is kept.
Czech: Opětovné nahrání.

**Place new registrants**:
An action that solves only for the unassigned Helpers while every existing
Assignment, locked or not, is held fixed and nobody placed is moved. A full
Solve stays available and discards every Assignment except locked ones.
Czech: Zařadit nové registrované.

**Simulace**:
A rehearsal for the competition, held before the event day.

**Organizer**:
A second category of tracked person, distinct from Helper: a per-Season record
(id, Person link, name, optional e-mail, phone, T-shirt size) that uses no solved
Role. Created by hand, from the Organizers' own form, or by promoting a Helper
(and convertible back to one). Holds exactly one placement (Building, or
Building+Room), set implicitly by assigning them into an Organizer role slot.
The solver treats a placed Organizer as a fixed anchor that never moves. An
Organizer carries Tags and Can't attend like a Helper, can be named in a
Helper's Friend preference and can be a member of a Forced friends group.
Czech: Organizátor.

**Building**:
A venue hosting part of the competition. The set of Buildings is not stable
across Seasons — always driven by that Season's configuration, never
hardcoded, and there is no default layout: a new Season has no Buildings until
the user brings a layout from an earlier Season (the "Rozložení budov" section
of the import offer, see **Tag import**), reads it from the "Pomocníci v
místnostech" sheet or enters it by hand.
Czech: Budova.

**Room**:
A room within a Building. Room groupings also change Season to Season —
rooms get merged or split.
Czech: Místnost.

**Large room**:
A Room noticeably bigger than the others (at least 1.5 times the median size of
the Rooms that have Helpers), shown across two columns in the exported roster.
Judged automatically against the roster as it stands, never marked by hand.
Czech: Velká místnost.

**Building preference**:
The set of Buildings a Helper marked as acceptable on the survey (a multi-select
question, not a single ranked choice). Satisfied if the Helper's assigned
Building is in the set, or the set is empty (no preference expressed). A stored
preference is matched to the Season's configured Buildings and rewritten to their
names.
Czech: Preferované budovy.

**Equipment eligibility**:
A hard rule gating Fotograf: a Helper who didn't mark that they can
bring a camera cannot be assigned Fotograf, unless the rules can't all hold
and this becomes a Broken rule. Bringing a laptop is no longer
a hard constraint on Kreslič — it's tracked only for display (the roster
export's `(n)` tag).
Czech: Způsobilost dle vybavení.

**T-shirt size**:
A Helper's or Organizer's shirt size: XS to XXL, optionally with a cut ("pánské
M", "dámské S", its own size), or Unknown when blank or unrecognizable. Counted
per Building, by where the person is placed, for the shirt order.
Czech: Velikost trička (Unknown: Neznámá).

**Tag**:
A label a Helper can carry: name (required, unique), colour, and note, plus an
optional single parent Tag it implies. Implication forms a tree — a Tag has
at most one parent and cannot imply itself or one of its own descendants. A
Helper's effective Tags are the ones assigned to them directly plus every
implied ancestor, computed live off the Tag tree rather than copied onto the
Helper (e.g. "8.M" implies "GCHD", so an 8.M Helper is GCHD too). Each Season
keeps its own Tags; they reach a later Season through Tag import. Tags are
managed in the Tags tab and applied there or in a person's popup in the People tab; deleting a Tag strips it from its Helpers and moves its child Tags up to
its own parent.
Czech: Štítek.

**Tag constraint**:
A list of rules a Tag places on the people who carry it, inherited through
implication: must / must not be in some Buildings or Rooms, must / must not have
some Roles (each an any-of set), or must share a Building / Room / Role. A
"must not" always wins over a "must"; a placement outside the allowed set is a
Broken rule.
Czech: Omezení štítku.

**Preference**:
A Helper's 5-point ordinal rating of one Role, from most to least willing:
Ano ("yes") → Klidně ("sure") → Nevadí ("don't mind") → Spíš ne ("rather
not") → Ne ("no"). A blank answer counts as Nevadí, so a Helper who left all
five blank has no preference between Roles. The solver scores each rating with
a cost, set per rating on the solver tab as a whole number from 0 to 20 (the
fixed maximum, `MAX_ROLE_COST`, which also bounds the Záloha cost; the unit
that scales all costs is not bounded by it).
Czech: Preference rolí.

**Friend preference**:
A Helper's soft request to share a Room with another named person — a
Helper or an Organizer — minimized-if-unsatisfied, never a hard
constraint. Configurable as `pairwise` (each request scores
independently) or `mutual` (only reciprocated requests count), and as
`symmetric` (a reciprocated pair merges into one scored unit) or not
(each direction scores separately). A resolved request can be hardened into a
Forced friends group ("make forced"), which never changes the request itself.
Czech: Přání být s kamarádem (one request: žádost o kamaráda).

**Forced friends group**:
A named, user-authored hard constraint: a set of people (Persons) bound by a
list of rules that must all hold at once (share a Building, Room or Role, or
must / must not be in some places or have some Roles). Distinct from Friend
preference, which is a soft survey request the solver may leave unsatisfied.
Czech: Vynucená skupinka kamarádů ("make forced": Vynutit).

**Assignment**:
The solver's output for one Helper: the Building, Room, and Role they're
placed into.
Czech: Přiřazení.

**Broken rule**:
A hard rule the current roster fails to satisfy: a Room or Building role count,
a Tag constraint, a Forced-friend group, or Equipment eligibility. A solve never
fails because of one; it returns a full roster with as few Broken rules as it can
and lists what it bent. Judged live against the roster as it stands, and a hand
edit is never refused for breaking one.
Czech: Porušené pravidlo.
_Avoid_: Infeasible solve

#### Solver roles

**Role**:
The single Role the solver assigns to each Helper — exactly one, from a
fixed set of 6. Distinct from Organizer role and Additional role, which are
assigned by hand, not by the solver.
Czech: Role.

**Opravovatel**:
Corrector/grader.

**Měnič**:
"Changer" — swaps/exchanges papers or materials between rounds.

**Skenovač**:
Scans solutions.

**Kreslič**:
Draws problems/diagrams. No longer requires Equipment eligibility — a
Helper without a laptop can still be assigned Kreslič.

**Fotograf**:
Photographer. Requires Equipment eligibility for a camera.

**Záloha**:
Reserve/overflow. Not a Preference option on the survey; absorbs excess
Helpers with no capacity limit. Not free to fill: the solver scores it like
any other Role, at a cost worse than Nevadí but better than Spíš ne or Ne, so
a Helper who is fine with a real Role gets that rather than Záloha. Among
otherwise equal rosters it goes to the later registrants first (see
**Registration order**).

**Registration order**:
A Helper's place in the order they registered: the row of their first
submission in the survey export; anyone who arrives later (a new registrant on a
re-upload, a Hand-added Helper) comes after everyone. The solver adds a
surcharge to Záloha that falls linearly from the full `late_zaloha` weight for
the earliest attending Helper to nothing for the latest — a tie-breaker, not a
rule.
Czech: Pořadí registrace.

#### Manual roles

**Manual roles**:
Any role assigned by hand after the solver runs, rather than by the solver
itself — covers Organizer role and Additional role.
Czech: Manuální role.
_Avoid_: Out-of-solver roles

**Organizer role**:
A Manual role for Building/Room leadership or support duties, independent
of the assignee's solved Role — filled only by a tracked Organizer. A slot
entry saved before Organizers existed (a registered Helper's id or a
hand-typed name) is a legacy entry: still shown and exported, marked as not
yet a tracked Organizer, until replaced by dragging one in.
Czech: Organizátorská role.
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
Czech: Doplňková role.
_Avoid_: Overlay role

**Registrace**:
Registration desk. An Additional role, scoped to a Building.

**Uvaděči účastníků**:
Participant ushering. An Additional role, scoped to a Room.

**Focení předávání cen**:
Photographing the award ceremony. An Additional role, scoped to a Room.

**Tall cell**:
Two adjacent rows of the roster grid merged top-to-bottom into one cell over the
same Rooms (Vedoucí budovy with Pravá ruka, Pravá ruka with Vedoucí místností,
Fotograf with Focení předávání cen). One slot for both roles.
Czech: Sloučená buňka přes role.

#### People

**Person**:
The durable identity of one individual across Seasons, distinct from the
per-Season record (a Helper or an Organizer) that represents them. Recognized by
e-mail first, normalized name second; it accumulates every e-mail and name seen
for them across the stored Seasons.
Czech: Osoba.

**Returning helper**:
A Helper who also registered in an earlier Season and is recognized as the same
Person. A confident match is an identical normalized e-mail (linked
automatically); an uncertain match is an identical name only (proposed on a
review list, linked only when the user confirms).
Czech: Vracející se pomocník.

**GCHD sheet**:
An optional second sheet named GChD in a Helpers' survey export, listing students
of the GCHD school and their class. Uploading creates the Tag GCHD plus one Tag
per class and tags the Helper with the same e-mail.
Czech: List GChD.

#### Tag import and Class promotion

**Tag import**:
Bringing an earlier Season's building layout, Tags (with constraints) and
Forced friends groups into the current Season and re-applying Tags to Returning
helpers who carried them. Copies, never shares; each imported Tag remembers its
origin.
Czech: Import štítků; the offer is "Import z dřívějšího ročníku".

**Class promotion**:
Renaming school-class Tags (e.g. "8.M") one school year up ("9.M") for each school
year crossed since the imported Season.
Czech: Zestárnutí třídy (action: Zestárnout třídu).

### Application

**Workspace**:
The web app's single current session: the one Season currently open, plus
every edit made since. There is exactly one Workspace — no working on
several Seasons at once. Earlier Seasons stay stored and can be reopened
into the Workspace, which is the only way to correct them.
Czech: Pracovní plocha.

**Season export**:
A single `.zip` carrying chosen stored Seasons (and optionally their Versions)
from one machine to another. Importing previews each Season and needs an explicit
choice for one that meets a stored Season: Replace, Keep both or Skip.
Czech: Export ročníků / Import ročníků.

**Version**:
A named, timestamped snapshot of the open Season's whole state, saved and
restorable on demand. Restoring rolls back everything the Season holds
(Person links, Tags, Forced friends groups, Assignments) except its label,
and belongs to that Season — deleting the Season deletes its Versions.
Czech: Verze.

## Relationships

- A **Season** holds its own **Helpers**, **Organizers**, **Tags**, **Forced friends
  groups**, layout (**Buildings** and **Rooms**), **Roster** and **Versions**; only
  the **Person** link spans Seasons.
- A **Person** is represented in each Season by a **Helper** or an **Organizer**
  record (never both at once); **Tag import** and **Returning helper** recognition
  go through the Person.
- A **Roster** is the set of **Assignments**; each Assignment gives one Helper a
  Building, Room and solver **Role**. **Manual roles** sit beside it and are
  never solved.
- **Broken rules** are judged live from the Roster; **Tag constraints**,
  **Forced friends groups** and **Equipment eligibility** are the rules besides
  the Room and Building counts.

## Ambiguities

- "Overlay role" is the deprecated name of **Additional role**; "Structural role"
  of **Organizer role**; the grid's "Overlays" (Zobrazení chips) are unrelated to
  either.
- **Friend preference** (soft, from the survey) and **Forced friends group** (hard,
  authored by the user) are different things; "make forced" turns the first into
  the second without changing it.
- **Tag import** copies Tags between Seasons; **Season export** moves whole
  Seasons between machines.
