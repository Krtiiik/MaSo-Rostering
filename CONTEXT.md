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
Building/Room configuration, from every other Season. A Season is identified
by a required label — a year plus jaro/podzim — that is unique among stored
Seasons, editable, and what orders Seasons in time. Every Season the app has
worked on stays stored, not only the current one.

**Helper**:
A volunteer who registered via the survey and is eligible to receive one of
the 6 solver-assigned Roles. Czech: pomocník.

**Hand-added Helper**:
A Helper entered directly into the app rather than parsed from the survey.
Only name and contact are required; every other field (Preferences, Building
preference, equipment, Friend preference, T-shirt size) is optional and left
at its normal empty/no-preference default.

**Locked Assignment** *(planned, not yet implemented)*:
An Assignment the user has fixed by hand for a chosen Helper so that a full
Solve keeps it; a Solve discards every Assignment that isn't locked. A lock
pins the whole Assignment (Building, Room, and Role together), never just
part of it. It belongs to one Season's roster, not to the Person, so it does
not carry over to a later Season. A lock never validates: a locked Assignment
may break a rule, and it is the rule that bends, never the lock. Moving a
locked Helper by hand moves the lock with them. A lock ends only when the user
clears it, or the Helper is marked Can't attend, or becomes an Organizer, or
their Room or Building no longer exists at the next Solve.

**Can't attend**:
A per-Helper flag marking them unavailable for the Season: excluded from the
solver and absent from the roster grid entirely, for as long as it's set.
Reversible at any time.

**Simulace**:
A rehearsal for the competition, held before the event day.

**Organizer** *(planned, not yet implemented)*:
A second category of tracked person, distinct from Helper. Created either
by hand (name only) or by promoting an existing Helper; promotion removes
them from the Helper pool, so a promoted Organizer receives no solved Role
that Season — one person is never both at once. An Organizer holds exactly
one placement (Building, or Building+Room) per Season, set implicitly by
assigning them into an Organizer role slot — there is no separate
placement step, and no placement without a role slot. A Helper's Friend
preference can name an Organizer as well as another Helper; it's scored
against the Organizer's placement (a Room match if placed in a Room, a
Building match if only placed at Building level), and can't be satisfied
against an unplaced Organizer. Organizers can carry Tags, same as Helpers.

**Building**:
A venue hosting part of the competition. The set of Buildings is not stable
across Seasons — always driven by that Season's configuration, never
hardcoded.

**Room**:
A room within a Building. Room groupings also change Season to Season —
rooms get merged or split.

**Large room**:
A Room noticeably bigger than the others, shown across two columns in the
exported roster. Judged automatically, never marked by hand: its size — the
Helpers placed in it across the five Roles other than Záloha, which is
building-wide — is at least 1.5 times the median size of the Rooms on the
roster that have Helpers. Judged against the roster as it currently stands,
so a hand edit or re-solve can change it. A Room the user has merged with a
neighbour is never Large.

**Building preference**:
The set of Buildings a Helper marked as acceptable on the survey (a
multi-select question, not a single ranked choice). Satisfied if the
Helper's assigned Building is in the set, or the set is empty (no
preference expressed).

**Equipment eligibility**:
A hard rule gating Fotograf: a Helper who didn't mark that they can
bring a camera cannot be assigned Fotograf, unless the rules can't all hold
and this becomes a Broken rule. Bringing a laptop is no longer
a hard constraint on Kreslič — it's tracked only for display (the roster
export's `(n)` tag).

**T-shirt size**:
A Helper's shirt size, one of XS, S, M, L, XL, XXL, or **Unknown** when the
survey answer is blank or unrecognizable (or a Hand-added Helper has none).
Editable by hand on the Helper. Counted per Building, by the Building the
person is placed in, for the shirt order.

**Tag**:
A label a Helper can carry: name (required, unique), colour, and note, plus an
optional single parent Tag it implies. Implication forms a tree — a Tag has
at most one parent and cannot imply itself or one of its own descendants. A
Helper's effective Tags are the ones assigned to them directly plus every
implied ancestor, computed live off the Tag tree rather than copied onto the
Helper.

**Tag constraint**:
A positive (allow-list) or negative (deny-list) restriction a Tag places on
Building or Role, inherited by every Helper who carries that Tag directly or
through implication. A Helper's effective allowed set per axis is the
intersection of every applicable Tag's positive list (a Tag with none doesn't
narrow it), minus anything any applicable Tag's negative list names — a
negative always wins. A Tag assignment that would leave a Helper with no
allowed Building or Role on either axis is invalid.

**Preference**:
A Helper's 5-point ordinal rating of one Role, from most to least willing:
Ano ("yes") → Klidně ("sure") → Nevadí ("don't mind") → Spíš ne ("rather
not") → Ne ("no"). A blank answer counts as Nevadí, so a Helper who left all
five blank has no preference between Roles.

**Friend preference**:
A Helper's soft request to share a Room with another named person — a
Helper or an Organizer — minimized-if-unsatisfied, never a hard
constraint. Configurable as `pairwise` (each request scores
independently) or `mutual` (only reciprocated requests count), and as
`symmetric` (a reciprocated pair merges into one scored unit) or not
(each direction scores separately).

**Forced friends group** *(planned, not yet implemented)*:
A named, user-authored hard constraint: a set of Helpers and Organizers who
must share every axis the group selects — Building, Room, and/or Role (Room
implies Building). Distinct from Friend preference, which is a soft survey
request the solver may leave unsatisfied. A person may belong to several
groups; overlapping groups are never merged. A group never includes an
Organizer on the Role axis, since an Organizer has no solved Role. A group is
inactive while it has fewer than two active members; a member who is
Can't attend, an unplaced Organizer, or not registered this Season is not
active. A group belongs to the people in it, not to one Season, so it carries
over to a later Season alongside Tag import.

**Assignment**:
The solver's output for one Helper: the Building, Room, and Role they're
placed into.

**Broken rule**:
A hard rule the current roster fails to satisfy: a Room or Building minimum,
a Tag constraint, a Forced-friend group, or Equipment eligibility. A solve
never fails outright because of one — it returns a full roster with as few
Broken rules as it can manage and lists what it had to bend. Rules bend in a
fixed order (minimums first, then Tag constraints, Forced-friend groups, and
Equipment eligibility last); a pre-placed Organizer never bends. Whether a
rule is broken is judged against the roster as it currently stands, so a
hand edit that fixes it clears it immediately. A hand edit is never refused
for breaking a rule — a placement that breaks one stands and simply shows as
a Broken rule, including an Organizer's hand placement; only minimums, which
routinely dip mid-edit, are exempt from warning at the moment of the edit.
_Avoid_: Infeasible solve

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
Draws problems/diagrams. No longer requires Equipment eligibility — a
Helper without a laptop can still be assigned Kreslič.

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

#### People

**Person** *(Helpers only so far; Organizers and name-based proposals are planned)*:
The durable identity of one individual across Seasons, distinct from the
per-Season record that represents them in a given Season — a Helper or an
Organizer. A Person carries identity only: it is what links a Season's
Helpers and Organizers to their earlier records, and so lets Tag import
re-apply a Season's Tags to the same people. A Person is recognized by
e-mail first, normalized name second (see Returning helper); a Person
accumulates every e-mail and normalized name seen for them across every
stored Season, and a new row is matched against all of them. A Person exists
only through the Seasons that record them: forgetting a Season forgets
whatever only it knew.
A promoted Helper keeps their Person; a
hand-created Organizer has no e-mail, so every match for them is uncertain
unless an e-mail is entered. Someone already known as an Organizer who shows
up in a new survey is offered a link to that Person, never auto-promoted.

**Returning helper**:
A Helper who also registered in an earlier Season and is recognized as the
same Person. Recognition looks at every earlier Season the app has stored,
not just the previous one, and applies the same way to a re-upload within
one Season (duplicate rows in one export collapse to the latest submission;
someone missing from a newer export is kept, not removed). A **confident match** is an identical normalized
e-mail — linked automatically even if the name differs. An **uncertain
match** *(planned, not yet implemented — today such a row is simply a new
Person)* is an identical normalized name with no e-mail match — proposed, not
linked until the user confirms it. Phone number is never a key. Anything
else is treated as a new Person.

#### Tags *(planned, not yet implemented)*

**Tag**:
A named, coloured label with an optional note, attached to any number of
Helpers. A Tag may imply other Tags (e.g. "8.M" implies "GCHD") and may
carry hard constraints on the Building or Role its Helpers can be assigned.
Each Season keeps its own Tags; they reach a later Season through Tag import.

**Tag import**:
Bringing an earlier Season's Tags into the current Season and re-applying
them to Returning helpers who carried them then. Each Season keeps its own
Tags, so an import copies the source Season's whole Tag tree (with its
constraints) rather than sharing it, and an imported Tag remembers which
earlier Tag it came from.

**Class promotion**:
Renaming school-class Tags — names of the form number, dot, optional space,
letters, e.g. "8.M" or "8. M" — to the number one school year up per school
year crossed since the imported Season (e.g. "8.M" → "9.M"). The school year
turns at the jaro → podzim boundary. There is no top year: a class keeps
counting up, since former students keep helping as "the same class" ("10.M").

### Application

**Workspace**:
The web app's single current session: the one Season currently open, plus
every edit made since. There is exactly one Workspace — no working on
several Seasons at once. Earlier Seasons stay stored and can be reopened
into the Workspace, which is the only way to correct them.

**Version**:
A named, timestamped snapshot of the open Season's whole state, saved and
restorable on demand. Restoring rolls back everything the Season holds
(Person links, Tags, Forced friends groups, Assignments) except its label,
and belongs to that Season — deleting the Season deletes its Versions.
