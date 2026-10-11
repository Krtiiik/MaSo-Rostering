# Architecture

## Overview

Rostering assigns registered helpers to a Building, Room and Role for a recurring Czech math competition (a "Season" is one occurrence). It ingests the Google Forms survey export, solves an assignment with OR-Tools CP-SAT, lets the organiser correct the result by drag-and-drop, and exports a formatted Excel roster. It ships as one local, single-user NiceGUI web app (`rostering serve`, also the bare default), run from source or as a PyInstaller executable built by CI on release tags. The Czech UI is a hard requirement; code and docs are English (see the project instructions above).

## Components and flow

- **Domain and rule modules** (domain model, Tags, Forced friends, Building preferences, Organizers, Persons, merges): pure Python with no UI or storage knowledge. They define what a valid roster means.
- **Ingest** turns survey exports, the Organizers' sheet, the GChD sheet and the hand-drawn buildings table into domain records, driven by column-mapping candidates rather than fixed headers.
- **Solver** builds the CP-SAT model from the domain and returns an assignment plus the rules it had to bend. Its **live checker** judges any roster, solved or hand-edited, against the same rule families.
- **Persistence** keeps each Season as a JSON state dict plus named Versions on disk, and handles Season zip export/import.
- **Mutation layer** (`webapp` core): every user action is a function over the Workspace's state dict, which loads the state, changes it, saves it and returns. It is the only writer of state, raises `RosteringError` or `ConfirmationRequired`, and is tested without a UI.
- **UI** (`webapp/ui`): a per-browser-tab session holds the Workspace plus view-only state. It runs a mutation, shows errors or confirmations, then redraws. The tabs follow the work order: People, Buildings, Tags, Forced friends, Solver, Roster (Buildings before Tags and Forced friends because their rules pick Buildings and Rooms from the layout). The roster grid has a pure view-model builder, an HTML renderer and a small browser-side JS component that reports drag, click and lock events back to Python.
- **Export** writes the final Excel file from the state, merging in the manual overlay.

Typical flow: upload survey, then ingest, then mutations save state; Solve runs the solver off the event loop and stores assignments; a drag calls a mutation, the checker recomputes broken rules on the redraw; export reads the state. Details of each piece are in "Implementation notes" below, and the glossary terms are in `CONTEXT.md`.

## Design notes

**Single-process NiceGUI app, no API layer of our own.** The UI calls the domain, solver, ingest and export code directly. History shows the stack was replaced twice in the first days: FastAPI plus React/Vite, then Streamlit with a React/dnd-kit grid component, then NiceGUI. The Streamlit step cut the toolchain to one language; the NiceGUI step removed the second install, the Node/npm build and a UI that worked around Streamlit's rerun model. The grid is plain package data JS, so one `pip install` or one executable suffices.

**State is one JSON dict per Season, mutated by pure-ish functions.** Versions, Season export and Start over are then just copies of the dict, and a new feature mostly adds keys that old files lack, migrated on load. The cost is the many `migrate_*` hooks run on read. Identity (Season id, Person ids) is stamped by the Workspace and kept out of Versions so rollbacks cannot change it. (The pick of JSON files over a database is not explained in the history, so the reason is unconfirmed.)

**Pure view-model modules separate from rendering.** The grid's data, the to-do queries, the checker, Tag and forced-group logic compute from the state without NiceGUI. Tests exercise them directly, with only a few NiceGUI user-simulation tests for the UI. This replaced the earlier Streamlit AppTest tests. Views redraw from state after every mutation rather than tracking widget state.

**Hard rules are relaxed through tiered slack, never made infeasible.** A solve must always return a full roster, because the organiser then fixes it by hand. Minimums, Tag restrictions, Forced friends and Equipment are each a rule family with a penalty slack, ordered so a higher tier is bent only after a lower one. Commit 2c277ac introduced this, replacing an INFEASIBLE outcome. Locks, Can't attend and Tag rules likewise never block a solve. Only the one-Room/one-Role shape and fixed assignments stay absolute.

**One rule definition feeds both solver and live checker.** Each rule family registers its relaxation and a check under the same rule identity, and tests assert the two agree. That lets hand edits be judged and toasted instantly, without re-solving or storing results. Broken rules are therefore derived on each render, never persisted (the saved solver report is not shown).

**Persons without a registry; links derived from Helper records.** A Person is just a shared `person_id` across Season records, matched by e-mail, so deleting a Season forgets what only it held and each Season stays independent. Uncertain same-name matches are computed, not stored, and decisions live on the records so Versions roll them back.

**Tags, Forced friends and Building preferences share one rule model.** `placement_rules` holds the "must be / share" rule that both Tags and Forced groups use, so the solver, checker and editor cover both. Effective Tags are derived from the tree, never stored, so editing the tree can't leave stale copies.

**No default building layout.** A layout belongs to its Season (commit 7aa8617); a new Season starts empty and takes one from an earlier Season, the buildings sheet or by hand, because layouts change almost every year.

**Manual (Organizer/Additional) roles stay outside the solver.** They are entered in the same grid by drop and merged at export; the solver's role scope is fixed at six roles. Why they were kept out beyond "deliberately out of scope" is not stated (reason unconfirmed).

**The CLI is only `serve`.** `ingest` and `solve` commands were retired (9704ca1) since the web app is the sole interface.

## Domain behaviour in detail

The full rules behind the terms in `CONTEXT.md` whose definition there is short,
moved here verbatim from the glossary. Terms keep their glossary names.

**Hand-added Helper**:
A Helper entered directly into the app rather than parsed from the survey.
Only name and contact are required; every other field (Preferences, Building
preference, equipment, Friend preference, T-shirt size) is optional and left
at its normal empty/no-preference default. Otherwise an ordinary Helper, with
no visual distinction; every field is editable and it can be deleted at any
time, deleting one who holds an Assignment or Manual role entries being
confirmed and clearing them exactly as Can't attend does.
Czech: Manuálně přidaný pomocník.

**Locked Assignment**:
An Assignment the user has fixed by hand for a chosen Helper so that a full
Solve keeps it; a Solve discards every Assignment that isn't locked. A lock
pins the whole Assignment (Building, Room, and Role together), never just
part of it. It belongs to one Season's roster, not to the Person, so it does
not carry over to a later Season. A lock never validates: a locked Assignment
may break a rule, and it is the rule that bends, never the lock. Moving a
locked Helper by hand moves the lock with them. A lock ends only when the user
clears it, or the Helper is marked Can't attend, or becomes an Organizer, or
their Room or Building no longer exists at the next Solve.
Czech: Uzamčené přiřazení; the lock itself is "Zámek".

**Can't attend**:
A per-Helper (or per-Organizer, see Organizer) flag marking them unavailable for the Season: excluded from the
solver and absent from the roster grid entirely, for as long as it's set.
Reversible at any time. Flagging a Helper who already has an Assignment or
Manual role entries asks for confirmation, then clears the Assignment (and its
lock) and every Manual role entry holding them and makes the roster stale;
un-flagging restores none of it and never re-solves.
Czech: Nemůže se zúčastnit.

**Re-upload**:
Uploading a newer survey export into the open Season. It never moves or
deletes hand work: a recognized Helper (see Returning helper) refreshes their
survey-derived fields from the latest row and keeps their id, Assignment, lock,
Tags, Can't attend flag and Manual roles; a new registrant gets a fresh id and
no Assignment; a Helper missing from the export is kept. A friend name resolved
by hand keeps its resolution while the same free-text name remains, a field
typed by hand wins over the survey, and a T-shirt size set by hand survives
while the survey answer for it is unchanged. A row that is a Hand-added Helper
registering merges into them: automatically on an identical e-mail, and for a
same-name row only once the user confirms it on the review list. The Helper
keeps their id, Assignment, lock, Tags, Manual roles and flags, the survey
answers fill every field left at its default, and no duplicate is left. A Manual
role entry that names an unregistered person by typed text is offered, in the
review list, a link to a Helper of the same normalized name; confirming turns
the text into a Helper reference and declining leaves it as typed. A placed Helper whose Building
preference, Preferences or equipment changed keeps their Assignment and is
marked "answers changed since placed" until they are moved, locked or
re-placed by a full Solve. A summary of what changed stays at the top of the
People and Roster tabs until dismissed, and Export is blocked while any
registrant is unassigned.
Czech: Opětovné nahrání.

**Place new registrants**:
An action that solves only for the unassigned Helpers (new registrants of a
Re-upload, a Hand-added Helper, someone no longer Can't attend) while every
existing Assignment, locked or not, is held fixed: the fixed Helpers still
count toward Room and Building counts and Friend preferences, and nobody placed
is moved, repaired or re-solved even when a hand move of theirs breaks a rule.
It neither creates nor clears locks. If not every rule can hold, it still
returns a roster with Broken rules reported, like any solve. A full Solve
stays available and discards every Assignment except locked ones; newcomers
can also simply be dragged into the grid by hand.
Czech: Zařadit nové registrované.

**Organizer**:
A second category of tracked person, distinct from Helper: a per-Season
record with an id, a Person link, a name and an optional e-mail, saved with
the Season and in Versions. An Organizer uses no solved Role or Role
capacity. Created by hand (name only), typically on the spot when naming
someone in an Organizer role slot, or by promoting an existing Helper —
promotion keeps their Person link, name, e-mail and Tags, removes them from the
Helper pool (clearing their Assignment and lock) and re-points other Helpers'
Friend preferences that named them, so a promoted Organizer receives no solved
Role that Season and one person is never both at once. The way back is
**converting to a Helper** (Czech: "Převést na pomocníka"): the Helper keeps the
Organizer's Person link, name, e-mail, phone, T-shirt size, Can't attend flag and
Tags (one that would leave them no allowed Room or Role is not carried), has no
Assignment and joins the Helper pool, and other Helpers' Friend preferences that
named the Organizer now name them; the slots the Organizer held are emptied.
An Organizer holds exactly one placement (Building, or
Building+Room) per Season, set implicitly by assigning them into an
Organizer role slot — there is no separate placement step, and no placement
without a role slot. Assigning them to a slot at another placement moves the
placement and removes their previous slot entries; a slot at the same
placement is kept alongside; removing them from every slot clears it. A
hand placement is never blocked. A Helper's Friend preference can name an
Organizer as well as another Helper; it's scored, at the same weight as a
Helper-to-Helper request, against the Organizer's placement (a Room match if
placed in a Room, a Building match if only placed at Building level), can't be
satisfied against an unplaced Organizer, and never counts under `mutual` mode
since an Organizer can't reciprocate. The solver treats a placed Organizer as
a fixed anchor that never moves. Organizers carry Tags exactly as Helpers do
(same Tag constraints, on the Building axis, and the Room axis when they
hold a Room, since they have no solved Role; a hand placement is never blocked, and one outside their allowed set is a
Broken rule) and can be flagged Can't attend like a Helper (their slot entries
and so their placement are cleared, and while flagged they cannot be given a
slot, are left out of the check and the export, and a Friend preference naming
them stops counting). Promotion does not carry a Helper's Can't attend flag
over: promoting is a deliberate act, so the Organizer attends. An Organizer can
also be a member of a Forced friends group, as an anchor at their placement (see
**Forced friends group**).

An Organizer carries a phone, a **T-shirt size** and, once the Organizers' own
form was loaded, the answers they gave on it (Simulation and event-day
attendance, preference for each of the Organizer role slots, Registrace and
"Jet na jiné místo", preferred places, friend names, equipment, photo consent,
a comment). The answers are read-only display: nothing in them drives a
placement, a Tag, the solver or a Friend preference. Loading the form's export
("Načíst organizátory", needing an open Season) creates the Organizers it names
and refreshes in place the ones it recognizes again: the same e-mail if the
sheet has one, otherwise the same normalized name (so an Organizer made by hand
is adopted by their row, but two people with different e-mails never are). It
never touches placement, Tags, Can't attend or Person links, nor a phone, shirt
size, name or e-mail typed by hand. A new Organizer who answers "Ne" to joining
on the event day starts flagged Can't attend; a later answer changes only the
reported summary, never the flag. A name an Organizer shares with a Helper of
the Season is reported and nothing is removed: the user deletes one of the two.
Without an e-mail, linking an Organizer to an earlier Season's Person is a
name-only proposal for the user to confirm or reject.
Czech: Organizátor.

**Large room**:
A Room noticeably bigger than the others, shown across two columns in the
exported roster. Judged automatically, never marked by hand: its size — the
Helpers placed in it across the five Roles other than Záloha, which is
building-wide — is at least 1.5 times the median size of the Rooms on the
roster that have Helpers. Judged against the roster as it currently stands,
so a hand edit or re-solve can change it. A Room the user has merged with a
neighbour in a Role band stays one wide cell in that band only and is split in
the others; merges in the leader and Additional rows never matter.
Czech: Velká místnost.

**Building preference**:
The set of Buildings a Helper marked as acceptable on the survey (a
multi-select question, not a single ranked choice). Satisfied if the
Helper's assigned Building is in the set, or the set is empty (no
preference expressed). The survey spells a Building its own way, so a stored
preference is matched to the Season's configured Buildings (same name ignoring
diacritics, a known alias, or one name inside the other) and rewritten to their
names; one that matches none waits in the to-do panel until the user says which
Building(s) it means.
Czech: Preferované budovy.

**T-shirt size**:
A Helper's or Organizer's shirt size, one of XS, S, M, L, XL, XXL, optionally prefixed with a
cut ("pánské M", "dámské S" — a different shirt in the order, so its own size),
or **Unknown** when the survey answer is blank or unrecognizable (or a
Hand-added Helper has none). The survey answer is read flexibly: case,
diacritics, separators and word order don't matter ("Dámské - S", "XL pánské").
Editable by hand on the Helper or Organizer. Counted per Building, by the Building the
person is placed in, for the shirt order; the "Trička" sheet has a row only for
a size someone counted wears.
Czech: Velikost trička (Unknown: Neznámá).

**Tag constraint**:
A list of rules a Tag places on the people who carry it, inherited by every
Helper who carries that Tag directly or through implication. They are the same
rules a Forced friends group states about each member, written and edited the
same way: "must / must not be in some Buildings or Rooms", "must / must not have
some Roles" (each an any-of set), and "must share a Building / Room / Role". The
"be" and "have" rules restrict each carrier on their own; a "share" rule binds all
the people carrying the Tag (directly or through implication, Helpers and placed
Organizers alike) together, exactly as if they were a Forced friends group: it
needs two of them to bind, restricts nobody's allowed set, is a Broken rule when
the carriers end up apart (worded "Štítek 8.M [...] je rozdělen mezi místnosti ..."),
is bent in the Forced-friend tier, and its "Go fix" leads to the Tag. Unlike a
group it never blocks an edit. A Helper's effective
allowed set per axis is the intersection of every applicable "must" rule (a Tag
with none doesn't narrow it), minus anything any applicable "must not" rule
names — a "must not" always wins. A Room is allowed when the Room rules allow it
and its Building is allowed. A Tag assignment that would leave a Helper with no
allowed Building, Room or Role is invalid, and a Tag edit (its rules or its
parent) that would is refused too. An entry naming a Building or Room the
Season's configuration no longer has is inert — ignored by the solver and the
check, noted as "not in this Season" — and Buildings are matched by name the way
Building preference is. A Helper placed outside their allowed set is a Broken
rule; the solver bends it after the Room and Building counts. An Organizer is
judged on Building, and on Room when they hold one (they have no solved Role).
A Tag saved as the old four allow/deny lists is read as the equivalent rules.
Czech: Omezení štítku.

**Forced friends group**:
A named, user-authored hard constraint: a set of people — Persons, each
resolving in a Season to a Helper or to "not registered" — bound by a list of
rules that must all hold at once. A rule is either to share a Building, a Room or
a Role (never negated), or that every member must or must not be in some
Buildings or Rooms, or have some Roles (a set: any of them). Distinct from Friend preference, which is a soft survey request the solver may
leave unsatisfied. A person may belong to several groups; overlapping groups are
never merged. A rule binds from two active members when it shares, from one when
it places or assigns a Role, so a group of one can pin a person; a group no rule of
which binds is dormant. A member who is Can't attend or not registered this Season is not active (a Can't
attend member stays in the group, flagged, and is restored on un-flagging; a
member not registered this Season is shown dim as "not registered" and becomes
live if they later register and are recognized as the same Person). Groups are
saved per Season, in Versions, cleared by Start over and kept on re-upload.
Creating a group or changing its people or rules after a solve moves no one and
makes the roster stale; dissolving one does so only if a rule was pulling placed
members and they currently satisfy it. A rule naming a Building or Room this
Season's layout lacks is inert and flagged on the group; a group whose rules
provably contradict each other (nobody could meet them all) or repeat one is
refused. A group shows a status: active, dormant (with the
reason) or violated by the roster as it stands, and its member chips are marked
on the roster grid. It is refused when its members' effective allowed Buildings
(a Room counts as its Building) or Roles, from their Tags, have nothing in
common on an axis it shares, or leave a member nothing that the group's must-be-in
and must-have-role rules allow, and a Tag change that would cause that is refused;
size, capacity and fixed or locked Assignments never block. An Organizer can be
a member: a placed one is active and anchors the group at their placement (the
Building rules, and the Room rules when they hold a Room; a room rule on an
Organizer who only leads a Building is judged by their Building as far as that
goes), an unplaced one is not active. An Organizer never takes part in a Role
rule, since they have no solved Role: they may be in a group with one, which
shows a warning "Role se na <name> neuplatní" (as does a room rule met by a
Building-level Organizer), and a member who becomes an Organizer (promotion)
keeps their place in the group. Dragging a
Helper away from a group with a placed Organizer breaks the group like any other.
A resolved Friend preference can be hardened with "make forced", which creates a
new group of those two people with the one rule to share a Room and leaves the Friend preference
as it was. A group belongs to the people in it, not to one Season, so it carries
over to a later Season in the same "Import from an earlier Season" offer as Tag
import, as its third section, after the layout and Tags (see **Tag import**): every group of the
source that has at least one member recognized this Season is copied whole, with
the members not registered here as dim "not registered" placeholders (a group left
with fewer than two active members is imported inactive), each group ticked in one
overview of its returning and missing members. An import copies, never shares (the
source Season is never edited), skips a group already present with the same members
and rules, and carries no link that is still unreviewed.
Czech: Vynucená skupinka kamarádů ("make forced": Vynutit).

**Broken rule**:
A hard rule the current roster fails to satisfy: a Room or Building role
limit (an exact count, so too many breaks it as much as too few),
a Tag constraint, a Forced-friend group, or Equipment eligibility. A solve
never fails outright because of one — it returns a full roster with as few
Broken rules as it can manage and lists what it had to bend. Rules bend in a
fixed order (Room and Building counts first, then Tag constraints, Forced-friend groups, and
Equipment eligibility last); a pre-placed Organizer never bends. Whether a
rule is broken is judged against the roster as it currently stands, so a
hand edit that fixes it clears it immediately. A hand edit is never refused
for breaking a rule — a placement that breaks one stands and simply shows as
a Broken rule, including an Organizer's hand placement; only the Room and Building counts, which
routinely dip mid-edit, are exempt from warning at the moment of the edit.
Czech: Porušené pravidlo.
_Avoid_: Infeasible solve

**Tall cell**:
Two adjacent rows of the roster grid merged top-to-bottom into one cell over
exactly the same Rooms, the way two spreadsheet cells are merged vertically.
Only these pairs can be: Vedoucí budovy with Pravá ruka, Pravá ruka with
Vedoucí místností, and Fotograf with Focení předávání cen. Both rows must
already have one cell over the same Rooms (Vedoucí budovy's cell is always its
whole Building), and a row is never in two tall cells over the same Rooms. A
tall cell is one slot for all its roles: whoever is in it holds both roles
(over Vedoucí budovy, both at the Building, as an Organizer has a single
placement), a drop gives both, a chip's × removes both, and splitting it leaves
them in the upper role only. Over Fotograf and Focení předávání cen it is
the Helpers placed as Fotograf in its Rooms who count as Focení předávání cen,
with no entries of their own: merging folds away Focení entries over those
Rooms. Purely a way of holding and drawing those roles; the Excel roster draws
it as one merged range.
Czech: Sloučená buňka přes role.

**Person**:
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
A hand-created Organizer has no e-mail, so every match for them is uncertain
unless an e-mail is entered (a promoted Helper keeps their Person). Someone already known as an Organizer who shows
up in a new survey is offered a link to that Person, never auto-promoted.
Czech: Osoba.

**Returning helper**:
A Helper who also registered in an earlier Season and is recognized as the
same Person. Recognition looks at every earlier Season the app has stored,
not just the previous one, and applies the same way to a re-upload within
one Season (duplicate rows in one export collapse to the latest submission;
someone missing from a newer export is kept, not removed). A **confident match** is an identical normalized
e-mail — linked automatically even if the name differs. An **uncertain
match** is an identical normalized name with no e-mail match — proposed on a
review list right after an export is loaded, never linked until the user
confirms it (link, or "not the same person"; several same-name candidates
for one Helper are listed together and the user picks one or none; two rows
of one export with the same name but different e-mails go to the list too).
An unreviewed candidate counts as not linked, a rejected pairing is never
proposed again, and a confirmed link is remembered independently of e-mail.
Any Helper's link can also be undone (unlink) or pointed by hand at any past
Person; link edits change only the Person link, never a Helper id. Phone
number is never a key — shown on a candidate as a hint only. Anything else
is treated as a new Person.
Czech: Vracející se pomocník.

**GCHD sheet**:
An optional second sheet named GChD in a Helpers' survey export: the responses
of students of the GCHD school, which also answer "are you a current GCHD
student" and "which class". When it names at least one class, uploading the
export creates the Tag GCHD, one Tag per class (named exactly as the sheet
writes it, and implying GCHD) and gives each student's class Tag to the Helper
with the same e-mail. A row answering "no" to being a student, or naming no
class, is ignored. A Tag the Season already has is reused as it is; a student
with no Helper of that e-mail gets no Tag and is listed among the upload's
warnings. A re-upload only adds, so a class Tag taken off a Helper by hand comes
back.
Czech: List GChD.

**Tag import**:
Bringing an earlier Season's Tags into the current Season and re-applying
them to Returning helpers who carried them then. Each Season keeps its own
Tags, so an import copies the source Season's whole Tag tree (with its
constraints) rather than sharing it, and an imported Tag remembers which
earlier Tag it came from (its origin, surviving renames). One source Season
per import, by default the most recent earlier stored one; importing again
from another Season is additive. Offered by a button in the Tags tab and by a
banner after the first upload while the Season has no Tags, and from the
Buildings tab; the offer is made of sections (the building layout first, since
Tag rules are copied only with the Buildings the Season has, then Tags, then
Forced friends groups). The layout section copies the source's Buildings, Rooms,
counts, sideways merges and tall cells (never the leadership slot holders); with
no tick it goes into a Season that has no layout and nothing else, and it replaces
a built layout only when ticked and confirmed. Only
directly carried Tags are re-applied, to confidently linked Persons, whether
they are a Helper or an Organizer this Season and whichever they were in the
source (a Helper promoted since gets their Helper Tags as an Organizer);
an unreviewed uncertain match is not tagged until its link is confirmed, which
then asks whether to apply their Tags. An assignment that would leave a Helper
with no allowed Building, Room or Role, or an Organizer with no allowed Building, is
skipped and rule entries naming a
Building or Room the current Season lacks are dropped (a rule left with none goes). A re-import and that late
prompt find a Tag by origin first, then by name; a Tag deleted on purpose is
recreated only by an explicit re-import, which says so.
Czech: Import štítků; the offer is "Import z dřívějšího ročníku".

**Class promotion**:
Renaming school-class Tags — names of the form number, dot, optional space,
letters, e.g. "8.M" or "8. M" — to the number one school year up per school
year crossed since the imported Season (e.g. "8.M" → "9.M"). The school year
turns at the jaro → podzim boundary. There is no top year: a class keeps
counting up, since former students keep helping as "the same class" ("10.M").
Any other Tag is never suggested. The number of years crossed is never shown,
only the suggested renames, one checkbox each; with none crossed the dialog
says there is nothing to promote. The dialog opens from an always-available
button and by itself after an import when the current Season is podzim and a
school year was crossed; a Tag can also be added by hand with an editable
target name that starts as its exact current name. Nothing is written until
Apply, and skipping can be re-prompted. Apply renames in place (parent,
children, constraints, colour, note and spacing stay), all ticked Tags at once
so a chain of classes shifts without trampling; a target that an unticked Tag
already has blocks Apply, and Tags are never merged. Only the current Season is
edited. The Season records, per source, the promotion applied and which Tags
were deliberately left unpromoted, so a later import or a late-confirmed link
resolves the promoted name.
Czech: Zestárnutí třídy (action: Zestárnout třídu).

**Season export**:
A single `.zip` carrying chosen stored Seasons (state and, optionally, their
Versions, never raw uploads or the default layout) from one machine to another:
the way to move the whole data state, hand a Season to a colleague, or seed a
fresh install. Importing reads and validates the whole file first and previews
each Season: a new one is added; one that meets a stored Season (same Season id,
or the same label under another id) shows a list of differences (Pomocníci,
Přiřazení, Štítky, ...) and needs an explicit choice — Replace (the Season and,
when the file has them, its Versions are swapped for the incoming ones), Keep
both (the copy gets a new Season id and a free label the organizer picks) or
Skip; an identical one is skipped. There is no field-level merge: the whole
Season goes one way or the other. A backup of the stored Seasons is written
first, the apply is all or nothing, and Person ids are kept as they arrive (the
same human under two ids is the ordinary uncertain-match review). Into an empty
workspace the Season that was open when the file was made is reopened.
Czech: Export ročníků / Import ročníků.


## Implementation notes

The detailed record of how the app is built, moved here from `CLAUDE.md`. It names
files and functions, so check the code when a detail matters: when this and the
code disagree, the code wins and this should be fixed.

### Manual roles

See `CONTEXT.md` for what Organizer role and Additional role mean and which
named roles belong to each. Implementation details not in the glossary:

- Of the three Additional roles, Registrace is scoped by **building**; the
  other two (Uvaděči účastníků, Focení předávání cen) are scoped by **room**
  (stricter) — so a helper can only be tagged into the slot for their own
  building/room, not a different one.
- A manual role's cell in the grid is the same table cell as a solver role's
  (`render._manual_cell`): names are chips, and nothing can be typed into the
  grid — a cell is filled only by dropping a chip on it and a chip leaves it by
  its × (both the `manual_set` event). The row label marks the row as
  "Manuální role" / "Organizátorská role" (italic, with the Material `link_2` icon
  inlined as an SVG, `render.LINK_ICON`). Organizer rows and Helper rows (solver
  roles, Additional roles) are separated by a heavy `row-side-start` line.
- Organizers are draggable (`render.organizer_chip`, `data-kind="organizer"`; a
  Helper's chip is `data-kind="helper"`). Each droppable cell says what it takes in
  `data-drop` (`role`, `dup` for an Additional role, `org` for the four
  leadership-slot rows), and `roster_grid.js` `accepts` refuses a drag of the
  other kind (the cell fades while it is in flight); a drop lands only on the cell
  under the pointer. An Organizer drop is the `organizer_drop` event, handled by
  `mutations.move_organizer` (`assign_organizer`, plus leaving the slot cell the
  chip came from); Organizers holding no slot and not flagged Can't attend are the
  "Organizátoři" list of the Nezařazení area (`grid.data.grid_organizers`).
- Moving a placed Helper (`mutations.move_helper`) out of the place an Additional
  role entry of theirs is scoped to also drops that entry (`_entries_left_behind`;
  `_entry_covers` judges a room-scoped entry by the cell group its room sits in for
  its own row, so a merged pair is one place; legacy/typed entries and Organizer
  slots are never touched). Unless `confirmed`, it raises `ConfirmationRequired`
  (`move_manual_role_impact` gives the lines) and changes nothing; the Roster
  tab's `_drop` (the `helper_drop` event) asks through `UiSession.act`'s
  confirmation and calls it again confirmed.
- In the roster grid, all three Additional roles are filled by
  drag-and-dropping a helper's existing chip onto their own building's/room's
  overlay cell (which duplicates them into that slot without moving their
  solved assignment — shown with a dotted border to mark it as a duplicate);
  there is no typing.

### Ingestion rules

- The registration form's place question is a **multi-select checkbox**: model it
  as the acceptable-building set described in `CONTEXT.md` (Building preference),
  never as a single ranked preference. How it is matched to the configured layout
  is under "Building preference matching" below.
- Helper-named friends are free text (often nicknames/diminutives — "Terka" for
  "Tereza", "Verča" for "Veronika" — and occasionally jokes/non-names). Free-text
  friend names must be resolved to helper IDs during ingestion via
  normalized/fuzzy matching; **names that can't be confidently resolved must
  be surfaced as a warning**, not silently dropped (the old
  `utils/parse_helpers.py` silently dropped unmatched names). `CONTEXT.md` has the
  Friend preference concept and its `mode`/`symmetric` configuration axes
  (default: `pairwise` + `symmetric`).
- The survey's column wording and its Building/Room naming change almost every
  season, so ingestion must be column-mapping-driven, never hardcoded to one
  season's exact header text or Building names (the history is under "Known
  historical data quirks" below).

### Building preference matching

Matching it to the layout (`rostering/building_prefs.py`, pure): the survey's
spelling is rewritten to configured Building names by `reconcile(state)` — run by
`_set_layout`, `put_config_from_sheet`, `_merge_survey_rows` (on the fresh row, so a
re-upload is not reported as a changed answer) and `Workspace._read_state` /
`load_version` for older states. `match_buildings` tries the same normalized name,
then a shared `building_keys` alias, then one name inside the other (both at least
3 characters). A name matching none is kept (ingestion keeps an unrecognized
answer whole instead of dropping it; `parse_raw_survey(building_names=...)` also
spots the configured names in the answer), listed by `unresolved(state)` /
`mutations.get_building_match_offers` in the to-do panel (not while no Building is
configured), and settled by `mutations.match_building`, which stores
`state["building_matches"]` (survey name -> configured names) so later uploads and
layouts reuse it. Only Helpers have a Building set; an Organizer's "places"
answer is display-only.

### Data pipeline stages

1. **Raw survey export** (`data/seasons/<season>/raw-response.xlsx`) — the
   untouched Google Forms export. Column wording changes almost every season
   (see season-by-season header differences below) — ingestion must be
   column-mapping-driven, never hardcoded to one season's exact header text.
2. **Canonical helpers** — parsed into the domain model (`rostering.domain`)
   via `rostering.ingest`.
3. **Season config** (`data/seasons/<season>/config.yaml`) — buildings, rooms,
   and per-role min/max headcounts for that season.
4. **Solve** (`rostering.solver`) — CP-SAT model producing a room+role
   assignment per helper.
5. **Manual overlay** (`data/seasons/<season>/manual-roles.yaml`, optional) —
   hand-entered Organizer/Additional role assignments, merged in at export time.
6. **Export** (`rostering.export.excel`) — the final formatted roster
   spreadsheet.

### Known historical data quirks (why ingestion must stay flexible)

- Building names vary: `Karlín` one season, `Křižíkova` another, sometimes
  merged as `Impakt + Troja`.
- Room groupings vary: e.g. `N4`, `N6` some seasons; `"N4 + N5"`,
  `"N6 + N7 + N9"` in others.
- Survey question wording and structure changed materially between seasons —
  e.g. 2023-podzim asked one free-text "preferred role" + one free-text
  "role you don't want" field, while 2025/2026 ask five separate per-role
  Likert-style "Výběr role [X]" columns.
- Historical hand-built final rosters (`data/rosters/*.xlsx`) additionally
  track informal per-helper annotations like `(n)`/`(f)` next to names —
  these mark whether the helper can bring a notebook / camera respectively,
  not "new helper" as might be assumed at a glance.

### Dark mode

`ui/theme.py` owns it: `ThemeToggle` (header button, system -> light -> dark,
kept per browser in `localStorage`, applied once the page connects; `ui.run`
starts in auto) and `CSS`, which sets the page background and overrides the
Tailwind utility classes the tabs use (`bg-white`, `text-gray-*`, `bg-*-50`,
...) under `body.body--dark`. Quasar restyles its own components. The roster
grid colours itself with `--g-*` variables in `grid/render.py` `CSS` (light on
`:root`, dark on `body.body--dark`): a new colour there is a variable with both
values, never a bare hex. A new tab using a light-only Tailwind colour class
needs a dark override in `theme.CSS`, inside its `@layer overrides` block: NiceGUI
puts Quasar's `!important` utilities (`bg-white`, `text-black`, ...) in the later
`quasar_importants` layer, which beats any unlayered `!important` rule.

### Status and decisions log

- Tech stack: a single-process [NiceGUI](https://nicegui.io) app
  (`rostering/webapp/`) calling the domain/solver/ingest/export modules
  directly, in-process — no HTTP API layer of our own (the project previously
  shipped a FastAPI backend + React/Vite frontend, then a Streamlit app with a
  React grid component; both were replaced, the latter by the NiceGUI rework because most of
  its UI code worked around Streamlit's rerun model). `rostering/webapp/`
  holds the UI-free core: `mutations.py` (state-mutation functions: upload,
  solve, move a helper, friend resolution, ...) and `forced_groups.py`, which
  the screens call into and tests exercise directly. The UI is
  `rostering/webapp/ui/`: `app.py` (`root`, the page: header with the six step
  tabs and the "K vyřízení" (to-do) drawer, left drawer `sidebar.py` with
  Seasons and Versions, the person sheet), `session.py` (`UiSession`, one per
  browser tab: the `Workspace`, the state, the per-Season view state in
  `SeasonView` — drafts, Go-fix focus, grid overlays/filter, ... — and `act`,
  which runs a mutation, shows a `RosteringError` as a notification, asks a
  `ConfirmationRequired` through `dialogs.confirm` and refreshes every view),
  `dialogs.py` (awaitable dialogs; they nest), `solving.py` (Solve / Place new
  registrants / Clear roster), `todo.py`, `tag_import.py`, `fix_focus.py` and
  one module per tab in `tabs/`. Views redraw from the session's state after
  every mutation; there is no widget-key bookkeeping. Each step is drawn
  into its own kept-alive `ui.tab_panel` (`Page._show_step`): showing another
  step only switches the panel, and a step is redrawn when shown after a change
  (`Page._stale`). Redraws have a scope (`session._SCOPES`): `switch_tab` reaches
  only listeners registered `on_change(..., on="tab")` (the step, the Tag sheet),
  `refresh_view` (a change of view state alone: Tag selection, overlays, drafts)
  also those with `on="view"` (marks every step stale), and `refresh` everything,
  including the header's to-do count, the to-do panel and the sidebar, which read
  every stored Season. The to-do
  queries go through `UiSession.cached` (shared by the badge and the panel until
  the next `refresh`), the panel is drawn only while its drawer is open, its
  review lists are one `ui.html` block each with one delegated click handler
  (`todo._Review`, buttons with Quasar's classes and `data-act`), and
  `Workspace` keeps each stored Season's identity, Helper count and Person
  records per `state.json` stamp (`_digest`, dropped by `_write_json`). Single-workspace
  design: the Workspace is the one open Season —
  upload a raw survey export (which creates the Season when none is open),
  configure buildings/rooms directly in the browser, solve, drag helpers
  between cells, save/restore named versions, export to Excel. Every Season
  stays stored and is managed from the sidebar's Seasons panel (open, rename,
  delete, New Season); the open Season's label shows in a header above the
  tabs. Run via `rostering serve` (see CONTRIBUTING.md).
- Season storage (`rostering/persistence/workspace.py`, label rules in
  `season_label.py`): each Season is a directory `data/seasons/<label>/`
  holding `state.json` and `versions/*.json`, next to any hand-placed
  `raw-response.xlsx`/`config.yaml`; a directory without a `state.json` is
  not a stored Season and is ignored. `data/seasons/open-season.json` points
  at the open Season by id. The state carries its identity as
  `state["season"] = {"id", "label"}`, owned by `Workspace` (stamped on every
  save, never snapshotted into or rolled back from a Version); a rename
  renames the directory but never the id. With no Season open, the Workspace
  is an in-memory blank draft (New Season, or a fresh install) that an upload
  turns into a Season. Deleting a Season removes only its `state.json` and
  `versions/` (hand-placed files stay). `ROSTERING_SEASONS_DIR` overrides the
  seasons directory; `ROSTERING_WORKSPACE_DIR` is the pre-Seasons location
  (`state.json` + `versions/`), read once for the first-launch migration
  (`mutations.migrate_legacy_workspace`), and when set on its own it also
  isolates the seasons under `<dir>/seasons`. Uploads store their
  submission timestamps (`export_timestamps`), which the label prefill and the
  migration use; a legacy state has none, so its migration asks for the label
  (prefilled from the file's last-modified date).
- Season export and import (`rostering/persistence/transfer.py` pure zip build/read
  and validation, `season_diff.py` pure differences, `Workspace.export_package` /
  `preview_import` / `apply_import` / `write_backup`, `mutations.export_seasons` /
  `preview_import` / `import_seasons`, UI in `ui/season_transfer.py` opened from the
  sidebar's Seasons panel; see `CONTEXT.md` "Season export"): the file is
  `manifest.json` (`schema_version`, `app_version`, `open_season_id`, per-Season id,
  label, counts) plus `seasons/<label>/state.json` and `versions/*.json`. A newer
  `schema_version` is refused; an older one is read, its states migrating through
  `workspace.migrate_loaded_state` (the same function `_read_state` uses). Import
  first resolves the decisions (`{season id: {"action": add | replace | keep_both |
  skip, "label"}}`; a stored Season needs an explicit one) and checks the labels
  the stored Seasons will have afterwards are unique (so a label swapped between two
  Seasons works), stages every file in `<seasons>/.import-*`, writes a backup to
  `<seasons>/../backups/`, then only moves files, with an undo log (`_move` is the one
  seam) that restores everything if a move or the pointer write fails. Replace removes
  the matched Season (same id, else the one holding the label) and adds the incoming
  one, keeping hand-placed files in a reused directory; a file without Versions
  (`includes_versions` false) neither compares nor touches them. Labels must stay
  valid and unique, so Keep both takes a label from the user (the preview suggests
  the next free half-year). The pointer follows a replaced open Season; into an empty
  workspace (no stored Season, no draft Helpers) it opens the file's open Season.
  Person ids are kept as they arrive.
- Persons (`rostering/persons.py`): there is no Person registry. Every Helper
  record in a saved state carries `email` (normalized: trimmed, lower-cased;
  read through the `email` column mapping) and a never-reused random
  `person_id`, distinct from the per-Season Helper `id`. `upload_responses`
  links each row by identical normalized e-mail to the newest matching record
  across every stored Season (`Workspace.person_records()`, the open Season's
  previous upload included) and otherwise mints a fresh `person_id`; a Person's
  e-mails and normalized names (`mutations.list_persons`) are derived from
  those records, so Start over and Season deletion forget what only they held.
  A state saved before Persons existed gets `person_id`s written back on first
  load. Duplicate rows with one e-mail collapse inside `parse_raw_survey`
  (latest submission wins) before ids are assigned. Uncertain (same-name)
  matches are derived, not stored: `persons.uncertain_candidates` proposes,
  for each unsettled Helper of the open Season (one that shares its
  `person_id` with no other record and has no `link_confirmed`), every other
  Person with a record of the same normalized name, minus rejected pairings
  (`rejected_person_ids` on the Helper record, checked from either side).
  `mutations.get_uncertain_matches` / `link_helper` / `reject_person_match` /
  `unlink_helper` / `get_person_links` back the to-do panel's review list and
  the person sheet's "Person links" tab. Links, rejections and `link_confirmed` live on the
  Helper record (so Versions roll them back) and stay put through a re-upload,
  which updates the recognized record in place. The survey's phone (`phone`
  column mapping, `Helper.phone`) is captured for display only. So is the whole
  survey row: `Helper.survey_responses` (`[(question, answer)]` in column order,
  blank answers included, every column whether mapped or not; saved as
  `survey_responses: [{question, answer}]`, absent when empty) is refreshed by a
  re-upload with the other `_SURVEY_FIELDS` and listed in the person sheet's
  "Odpovědi z dotazníku" tab. A duplicate-e-mail resubmission keeps only the
  latest row's responses.
- The roster grid (`rostering/webapp/ui/grid/`) is native to the app, with no
  npm or build step: `data.py` builds the view model from the state (pure; rows,
  merged cell groups, chip data, friend statuses, satisfaction, Broken-rule
  marks, the details card), `render.py` turns it into escaped HTML whose
  `data-*` attributes carry everything the browser needs, and `RosterGrid`
  shows it through `roster_grid.js`, a plain ES-module Vue component that turns
  native HTML5 drag-and-drop, clicks, the friend hover and the chip removals
  into events (`helper_drop`, `organizer_drop`, `manual_set`,
  `cell_merge`, `lock`, `card`, `card_close`) by delegation on its root. It
  decides nothing the HTML does not say. The JS ships as package data of
  `rostering` (`pyproject.toml`), so one `pip install` is enough. (Never name a
  component event after a DOM event such as `drop`: NiceGUI's `.on` would hear
  the browser's native one too.) The grid replaced a React + dnd-kit Streamlit
  component after a prototype of both (branch `prototype/nicegui-grid`), on the
  condition that every feature carried over.
- Buildings sheet import (`rostering/ingest/building_sheet.py`,
  `mutations.read_building_sheet`, the Buildings tab's "Načíst konfiguraci budov"): reads the
  hand-drawn "Pomocníci v místnostech" table into the config shape, touching
  neither the Season nor the saved layout; the tab replaces its draft with it and saves it at once (`_put`, after the replace-leaders confirmation; a declined one leaves an unsaved draft). Two
  header rows above the first labelled row of column A (Buildings as merged cells,
  Rooms under them; a blank header cell continues the Room before it), Role rows
  found by label stem (`Opravovatelé`, `Měniči`, … ; other labels are ignored). A
  coloured cell (`openpyxl` RGB, indexed or theme fill with its tint, spread of
  channels above `_GRAY_SPREAD`) is one Helper, gray/white/empty none; a merged
  range counts once, for the Room it covers or the Building when it covers several.
  Only non-zero counts are written. It also reads the leadership rows (Vedoucí
  budovy, Pravá ruka, Vedoucí místností, Technická podpora: names split on commas,
  Building-level or filed under the first Room the cell covers), the sideways merges
  of every Room-level row (`cell_merges`) and the tall merges (`row_merges`); the
  names are matched to the Season's Organizers (`read_building_sheet`: an exact
  normalized-name match is placed, a Can't attend one is skipped and reported,
  nothing is created) and travel as `SeasonView.sheet_pending` beside the draft.
  A name with no exact match goes to `pending["unmatched"]`; `put_config_from_sheet`
  stores those as `state["organizer_slot_offers"]` (`id`, `name`, `role`, `building`,
  `room`; replaced by each saved sheet), and `get_organizer_slot_offers` lists them
  for the to-do panel with live `candidates` (`organizers.similar_names` /
  `name_similarity`: diacritics/case/word-order-insensitive, word by word, so
  "Terka Nováková" or a surname alone resemble the full name). `accept_organizer_slot_offer`
  places the picked Organizer like `assign_organizer` and closes the offer,
  `dismiss_organizer_slot_offer` just closes it; an offer whose slot the layout no
  longer has is not listed. `mutations.put_config_from_sheet`
  saves layout, merges and slots in one save, after a confirmation naming the slot
  holders it replaces; an Organizer named in several places keeps the last.
- Tall cells (`rostering/row_merges.py`, `state["row_merges"]` = `{building, room,
  row}`, `row` the upper row's key and `room` the first Room of the group;
  `mutations.set_row_merge`, `tall_cells`; see `CONTEXT.md` "Tall cell"): the pure
  module decides which exist (`tall_cells`, dropped when a row's group no longer
  matches) and which could be made (`candidates`). The slot mutations
  (`assign_organizer`, `move_organizer`, `set_slot_holders`, `unassign_organizer`)
  work on `_cell_roles` / `_slot_cell_entries`, so a tall cell is one slot for both
  roles; its entries are filed at the Building for a cell over Vedoucí budovy (Pravá
  ruka at Building level is shown only in such a cell) and under the group's first
  Room otherwise. `_fold_tall_cell` / `_unfold_tall_cell` are the data effect of
  merging (union for both roles; Focení entries folded away) and splitting (lower
  role emptied); `_set_layout` (`put_config`) splits a tall cell the new layout can't
  hold, and `set_cell_merges` refuses a sideways change that would break one. The
  grid draws a tall cell once with `rowspan=2` in its upper row (`render._Tall`,
  event `row_merge`); the export writes it as a merged range (`write_roster(...,
  tall_cells=...)`). Grid and export order of the lower rows is now Fotograf,
  Focení předávání cen, Uvaděči účastníků, Registrace, Záloha, Technická podpora.
- Equipment eligibility is a **hard** rule (see `CONTEXT.md`), meaning the
  solver bends it only last. Hard rules are never constraints that can make a
  solve infeasible: `rostering/solver/rules.py` relaxes each through a slack
  penalized in fixed, dominance-ordered tiers (`Tier`: minimums, Tag
  restrictions, Forced-friend groups, Equipment), and `solve_competition`
  returns a full roster with `SolveResult.broken_rules`. Only the one-Room /
  one-Role shape and `fixed_assignments` never bend. A new rule family (Tags,
  Forced friends) registers a `RuleFamily` via `register_rule_family`; each
  `Relaxation` it returns carries the `RuleInstance` identity (rule kind +
  entity), and the family must also give a `check` (a `RuleFamily` without
  one cannot be registered) that the live checker runs. The one remaining
  failure is the time limit expiring with no roster (`NoRosterFound`,
  surfaced as "No roster found within N seconds").
- Live Broken-rule check (`rostering/solver/checker.py`: `check_roster`,
  `newly_broken`; per-family checks live next to the relaxations in
  `rules.py`): a pure function of the config, Helpers and current
  Assignments, run on every render and never stored, returning
  `BrokenRule`s with the same identity/family/amount/line the solver reports
  plus `cells` (grid cells; a `None` role marks a whole Room), `helper_ids`
  (chips) and a `FixTarget`. `tests/test_live_broken_rules.py` asserts the
  checker equals the solver's own bent rules. Through the mutation layer:
  `mutations.broken_rules(state)` (empty before the first solve),
  `newly_broken_rules(before, after)`, `move_toast_lines(before, after)`
  (every family except minimums) and `broken_rule_marks(...)`. The Roster tab
  lists them in a side sheet opened from a toolbar badge (family sections
  collapse above 10 instances), the grid draws the marks (`grid.data.build_view`)
  and a drop notifies its toast lines; `ui/fix_focus.py` carries a "Go fix"
  target (`SeasonView.fix_focus`) to the Buildings/People/Tags/Forced friends
  tab and drops it once the rule holds. `move_helper` has no validation gate. `diagnostics["broken_rules"]`
  in the saved state is only the solver's report as of the last solve and is
  not shown anywhere.
- Locked Assignments: the lock is an optional `locked: true` on an entry of
  `state["assignments"]` (missing = unlocked; `Assignment.locked`, carried by
  `assignment_to_dict`/`assignment_from_dict`), so Versions snapshot it for free.
  `mutations.set_lock` (placed Helpers only), `move_helper` (a lock moves with
  its Helper; a move never creates one) and `solve` (passes the locked
  Assignments as `fixed_assignments`, re-flags them in the result, and drops a
  lock whose Helper or Room no longer exists) are the only code that reads or
  writes it. The grid reports a toggle as the `lock` event (`{helper_id,
  locked}`, from ctrl/cmd-click on a placed chip or the details card's
  Lock/Unlock button). The details card (`grid/card.py`) opens on a plain click
  on a chip (never on hover, so it can't block a drag); it also lists the Helper's Tags and Forced friends groups and its "Upravit" button
  opens the shared `PersonSheet` (`HelperCard(on_toggle_lock, on_edit(kind, id))`). An Organizer's
  chip opens a smaller card of the same class (`card` event with `organizer_id`,
  `grid.data.organizer_card_data`: placement and slots, phone, e-mail, T-shirt size,
  Tags, who asked for them; no Lock); one is open at a time,
  and clicking the same chip again, Escape, a press anywhere outside a chip or
  the card, or starting a drag closes it. It survives the tab's redraws
  (`HelperCard` keeps which one is open).
  Bulk control lives in the Roster tab's toolbar menu: `lock_all_placed`,
  `clear_all_locks`, `locked_count`, and `unlocked_assignments_replaced` (what
  a full Solve would throw away, a to-be-dropped lock included; zero means no
  confirmation). `ui/solving.py` `solve` shows that confirmation for the Roster
  tab's Solve and the Buildings and Solver tabs' "Save & solve" (which saves the
  config first so the count uses the new layout). Every Solve and Place new
  registrants runs off the event loop (`run.io_bound`) under a persistent
  "Solving…" dialog (`run_in_modal`) the user cannot close; the work raises
  `RosteringError`, and a failure keeps the dialog open with the message and a
  Close button. `solve` records the locks it dropped as lines in
  `diagnostics["dropped_locks"]` ("N locks dropped: Room X no longer exists"),
  which are notified once after the solve. Locks live only in the Season's own `assignments`, so a new
  Season or a Tag import never carries them.
- Can't attend: `cant_attend: true` on the Helper record in the Season's state
  (`Helper.cant_attend`; absent = off), set only by
  `mutations.set_cant_attend(workspace, helper_id, flag, confirmed=False)`.
  The one rule for "who takes part" is `Competition.attending()`, applied by
  `solve_competition`, `check_roster` and the export (`export/people.py`
  `without_absent`), and by `mutations._build_competition`; the grid
  (`grid.data.build_view`) filters its own helper list, name suggestions and
  friend ids. Flagging a
  Helper with an Assignment or Manual role entries raises
  `mutations.ConfirmationRequired` (`.lines` name what goes) unless
  `confirmed=True`, then clears them and sets the stale flag. A re-upload
  never touches the flag (the recognized record is updated in place). The stale
  flag is `state["stale_reasons"]` (list of lines; `mutations.stale_reasons`,
  `mark_stale`), cleared by `solve`, refusing `export_xlsx_bytes`, snapshotted
  by Versions like the rest of the state; the Roster tab shows it above the
  toolbar and disables Export, the to-do panel lists it too. Can't attend is a
  checkbox in the People tables' rows and in the person sheet's Details
  (`person_sheet.set_cant_attend`); flagging a placed person asks first.
- People tab (`tabs/people.py`, "1. Lidé"): the "Načíst pomocníky" button in the
  Helpers table header (same `_import_button` as the Organizers' "Načíst
  organizátory"; with no Season open these two buttons are the only thing on the
  tab, Organizers first, and either creates the Season, asking for the label —
  the Organizers' sheet has no dates to prefill it from). The intended upload order is
  Organizers, Helpers, Buildings sheet: the Buildings sheet names Organizers
  that must already exist, and Helpers' friend names can resolve to them. A summary, then two
  `ui.table`s — Organizers above, Helpers below — with search, sorting, the
  Can't attend checkbox and the Tag pills in the row (Vue cell slots emitting
  `cant_attend` / `open_friends`). A click on a row opens the person sheet
  (`tabs/person_sheet.py` `PersonSheet`, a seamless right-hand dialog, one per
  page, so the table stays usable behind it): for a Helper the tabs Details
  (Can't attend, every field via `helper_fields.HelperFields`, Save / Promote /
  Delete — Delete and Promote always confirm), Tags, Friends (every survey name,
  matched or not, on top under "K přiřazení" (`resolve_friend`); then the
  "Kamarádi" picker (saves at once via `update_helper(friends=...)`), then
  "Vynucení kamarádi v místnosti" (a pick over that Helper's own friends runs
  `make_forced`, an unpick `forced_groups.unforce`)) and Person links; for an
  Organizer Details and Tags. The sheet's pickers save on every change and are
  rebuilt only when what they show changed elsewhere (`_Section` signatures), so
  picking several values in a row keeps the list open; a refused pick is
  notified and the picker shows what is saved again. The review lists (possible
  returning Helpers, typed role names) are in the to-do panel (`ui/todo.py`).
- Hand-added Helpers: `mutations.add_helper` / `update_helper` /
  `delete_helper` (and `helper_collisions`, the non-blocking name/e-mail
  warning) write ordinary Helper records into `state["helpers"]`, so the
  solver, grid, export, Tags and Can't attend have no second code path. A
  record gets `hand_added: true` and `hand_typed` (the fields typed by hand,
  for the re-upload, which never overwrites them; a hand edit of any Helper adds to it,
  and the T-shirt table edit does for a hand-added one) — both live on the
  record dict only, not on the `Helper` dataclass. An e-mail-shaped contact is
  the normalized `email`, any other contact is `phone` (display-only). Ids come
  from `state["next_helper_id"]`, a high-water mark also bumped by a delete, so
  an id is never reused (Versions snapshot it with the rest of the state). The
  Person link is a confident e-mail match against *earlier* stored Seasons only
  (`link_persons`), else fresh. `delete_helper` reuses `cant_attend_impact` and
  `ConfirmationRequired`, then clears Assignment, lock and Manual role entries,
  prunes the id from every `friends` list and `friend_name_decisions` (a name
  left with no target returns to `unresolved_friend_names`) and marks the
  roster stale. The forms live in `rostering/webapp/ui/tabs/person_sheet.py` (fields in `helper_fields.py`). A
  re-upload keeps hand-added records (they are never listed as "missing from the
  export"); a row with the same e-mail updates one in place, skipping the fields
  in its `hand_typed`. A same-name row with no e-mail match is a new registrant
  on the review list whose candidate has `merges_into` (the hand-added Helper's
  id, `_hand_added_merge_target`); `link_helper` then does not link two records
  but folds the row into the hand-added Helper (`_merge_into_hand_added`): the
  survey answers go through `_refresh_from_survey` (so `hand_typed` wins and
  defaults fill), Tags are unioned, the row's Assignment and lock move over only
  if the Helper has none, every Friend preference, `friend_name_decisions` and
  Manual role entry naming the row's id is repointed, the row's record and its
  `upload_summary` entries disappear, and the Helper stays `hand_added` with
  `link_confirmed`. The Helper's own flags (Can't attend) win; the row's are not
  carried. Typed Manual role names (`helper_id` None, `helper_name` text) are
  matched live by normalized name against the attending Helpers
  (`get_typed_role_link_offers`, one offer per typed name with its candidates
  and slots; shown above the review list in the People tab);
  `link_typed_role_name` rewrites every such entry to `{helper_id, helper_name:
  None}` (dropping one whose slot the Helper already holds) and
  `decline_typed_role_link` records the pair in `state["declined_typed_role_links"]`
  (name key + Helper id) so it is never offered again.
- Re-upload (`mutations.upload_responses` with a Season open, via
  `_merge_survey_rows`): `parse_raw_survey` still numbers its rows 1..N, so the
  merge maps each parsed id to a real one first (`_recognize_rows`: an identical
  normalized e-mail against the Season's own Helpers, else the Person
  `link_persons` finds if a Season Helper carries it; a row is never taken by two
  Helpers) and gives a new registrant `_next_helper_id`. A recognized record is
  refreshed in place by `_refresh_from_survey`: `_SURVEY_FIELDS` (name, role
  preferences, Building set, equipment, e-mail, phone) except those in
  `hand_typed`; friend names keep their `friend_name_decisions` only while the
  same name is still unresolved in the row (`friend_name_order` is refreshed);
  the T-shirt size takes the row unless it was set by hand while the last
  survey answer (`survey_tshirt_size` on the record, written by every upload) is
  unchanged. Assignments, locks, manual roles, merges, Tags, Can't attend and
  every other non-survey key are never touched, and only the friend-pair
  diagnostics are recomputed. On a re-upload of a Season that had Helpers,
  `state["upload_summary"]` (`new`, `changed`, `missing`; hand-added Helpers are
  never "missing") accumulates until `dismiss_upload_summary`, and
  `upload_summary(workspace)` adds the live `uncertain` matches. A placed
  Helper whose Building set, Preferences (blank = Nevadí) or equipment changed
  gets `answers_changed` (the field labels) on the record, shown as a chip mark
  in the grid (`answers_changed` helper prop); it is cleared by `move_helper`,
  locking (`set_lock`, `lock_all_placed`), a full Solve for the Helpers it
  re-places, and losing the Assignment, never by dismissing the summary
  (`answers_changed_since_placed` reads it, ignoring an unplaced Helper).
  Export gate: `unplaced_helpers` / `unplaced_reason` (attending Helpers with no
  Assignment once a roster exists) feed `export_blockers` and
  `export_xlsx_bytes`; unlike `stale_reasons` it is derived live, so placing the
  newcomers by hand lifts it. UI: the to-do panel (`ui/todo.py`, the summary
  until hidden), the Roster tab's warning above its toolbar. A same-name row with
  no e-mail match is a new registrant plus a review-list entry, so re-uploading
  an export with no e-mail column duplicates every Helper as one to review.
- Place new registrants (`mutations.place_new_registrants`; Roster tab toolbar
  button, enabled while `unplaced_reason` is set): `solve_competition` with
  *every* standing Assignment as `fixed_assignments` (`_standing_assignments`,
  the shared filter behind `_split_locks`: it skips one whose Helper, Building or
  Room is gone), then only the newcomers' Assignments are taken from the result
  and appended, so every existing record stays byte-for-byte as it was (lock
  flag included). Never reads or writes a lock beyond reporting, in
  `diagnostics["dropped_locks"]`, a lock on a vanished Room (that Helper has no
  usable Assignment, so is placed afresh with the newcomers and its
  `answers_changed` marker cleared). Unlike `solve` it leaves `stale_reasons`
  alone, needs no confirmation (nothing placed can be lost) and raises
  `RosteringError` when there is no roster yet or nobody is unassigned.
  `diagnostics` come from the shared `_solve_diagnostics`, and the Broken-rule
  banner judges the result live like after any solve. Forced-friend groups
  need no code here: the rule family applies to the newcomers through the same
  fixed-Assignment solve.
  roster stale. The forms live in `rostering/webapp/ui/tabs/person_sheet.py` (fields in `helper_fields.py`). Note a
  re-upload still replaces the Season's whole Helper list, so it does not yet
  keep hand-added records.
- Organizers (`rostering/organizers.py`, the Organizers section of
  `mutations.py`): the Season's Organizers are `state["organizers"]` (dicts `id`,
  `person_id`, `name`, `email`, `building`, `room`; ids from the high-water mark
  `state["next_organizer_id"]`, never reused), part of every Version. They are
  not Helpers: `Competition.organizers` (domain `Organizer`) carries them to the
  export only, the solver never sees them. The four leadership slots hold them by
  `organizer_id` on a `manual_roles["structural"]` entry; the placement
  (`building`/`room`) on the record is derived, only ever written by
  `_sync_placements` from those entries (so `assign_organizer`,
  `unassign_organizer`, `set_slot_holders`, `delete_organizer` and
  `put_manual_roles` all end by re-deriving it). `organizers.SLOT_SCOPES` /
  `check_slot` define a slot's address (Vedoucí budovy and Technická podpora:
  Building only; Vedoucí místností: Building and Room; Pravá ruka: either), a
  mismatch being a `RosteringError`, never a rule matter. `assign_organizer`
  moves the placement (removing the Organizer's entries at another Building/Room;
  entries at the same one stay); every slot cell takes any number of Organizers.
  `set_slot_holders` backs the grid: a typed name picks a tracked Organizer
  (normalized-name match) or creates one on the spot, a legacy entry named in the
  cell is kept. A *legacy* entry (no `organizer_id`; a `helper_id` or typed
  `helper_name`) stays in `manual_roles`, exports as before, shows with a "not
  tracked" badge (`mutations.legacy_slot_entries`, `legacy` on the grid's
  `manual_entries`) and is dropped when its chip is removed or its name is no longer
  named in the cell; `put_manual_roles` stays lenient about legacy entries
  (only validating `organizer_id` ones). Person recognition: `records_from_state`
  yields Organizer records too (`PersonRecord.kind`, ids are per kind), so
  `list_persons`, e-mail matching (`add_organizer`/`update_organizer`) and the
  Helper review list (`get_uncertain_matches`, which thus offers a link to a
  Person known as an Organizer) cover them; `get_uncertain_organizer_matches` /
  `link_organizer` / `reject_organizer_match` / `unlink_organizer` mirror the
  Helper ones and have no UI yet. Promotion of a Helper, Friend preference toward
  an Organizer and Organizer Can't attend/Tags are separate, later tickets.
- Organizers' sheet import (`rostering/ingest/organizer_survey.py`,
  `mutations.import_organizers`, the "Organizers' survey import" section next to
  `assign_organizer`; with no Season open it takes a required `label` and creates
  the Season, as the Helpers' upload does — the sheet has no dates, so the People
  tab asks for the label with no prefill): the Organizers' own Google Forms export, parsed through
  `mapping.ORGANIZER_FIELD_HEADER_CANDIDATES` (a file with none of the
  Organizer-only questions, the role slots and the attendance ones, is refused so a
  Helper export can't be loaded here). Per row: `phone`, `tshirt_size`
  (`Organizer.tshirt_size`, read by `export/people.py` so the "Trička" counts stop
  being Unknown), `email` if the sheet has the column, and `survey`, the read-only
  answers as written (keys `organizer_survey.ANSWER_FIELDS`, labels
  `labels.ORGANIZER_ANSWER_LABELS`; they drive nothing). `_recognize_organizer_rows`
  matches by e-mail, then by normalized name (never across two different e-mails),
  one record per row; a row with no match is `_new_organizer` (Person link by
  e-mail only), flagged `cant_attend` when the event-day answer is a plain "no".
  A re-upload goes through `_apply_organizer_row`, which skips the fields in the
  record's `hand_typed` (`update_organizer` now takes phone and shirt size and marks
  what changed, as for Helpers) and never touches placement, Tags, flags or links.
  `state["organizer_upload_summary"]` (`new`, `adopted` = hand-made Organizers a row
  matched, `changed` = field keys, `missing` = earlier sheet Organizers absent now,
  `also_helper` = Organizer ids sharing a name with a Helper, filtered live in
  `organizer_upload_summary`, `warnings`) accumulates until
  `dismiss_organizer_upload_summary`; it is the to-do panel's "Co změnilo poslední
  nahrání organizátorů" card. The same panel shows the Organizer review list
  (`get_uncertain_organizer_matches`, `link_organizer`, `reject_organizer_match`),
  and a confirmed link queues `tag_import.queue_late_link_organizer_offer`
  (`SeasonView.late_link_organizer_id`). UI: the Organizers table's "Načíst
  organizátory" button (`PeopleTab._organizer_buttons`, a hidden Quasar uploader),
  phone/shirt columns, and the person sheet's Details fields and "Odpovědi" tab.
  Tests: `tests/test_organizer_import.py` and the end of `tests/test_webapp_ui.py`
  (generated sheets: `tests.survey_factory.generate_organizer_survey`).
- Forced friends groups (`rostering/forced_friends.py`, the lifecycle in
  `rostering/webapp/forced_groups.py`, UI in `ui/tabs/forced_friends.py` — the
  "3. Forced friends" tab, then "4. Buildings", "5. Solver" and "6. Roster"): a group is a dict in
  `state["forced_groups"]` (`id` from the high-water mark
  `next_forced_group_id`, `name`, `rules` and `members`, each `{person_id,
  name}` with the last-known name), part of
  every Version, empty after Start over and untouched by a re-upload. Members
  are Persons; who they are this Season is derived on every read
  (`forced_groups.list_groups`: `active` = a Helper who is attending,
  `cant_attend`, `not_registered`), never stored, so un-flagging or a later
  registration recognized by `person_id` makes a member live again by itself.
  `forced_friends.group_rules(helpers, groups)` is the one shared definition of
  a group's rules for the solver and the checker. A group holds a list of
  `forced_friends.Rule`s that all hold at once, saved as dicts: `{"kind":
  "share", "axis"}` (never negated) or `{"kind": "be", "must", "axis", "values"}`
  where `axis` is `building` / `room` (values are Building names, or `[building,
  room]` pairs) / `role` ("have role", `Role.name`s) and `values` is an any-of set
  (canonical order, so equal sets are equal rules; `Rule.key` is the identity
  inside a group, `Rule.text()` the Czech wording). A group saved before rules
  existed has `axes`; `forced_friends.migrate_state` rewrites it on load (each
  axis a `share` rule, the implied Building dropped when Room is there), in
  `Workspace._read_state` and `load_version`. `group_rules` yields one `GroupRule`
  per rule in force: a `share` rule per enforced axis (Room subsumes Building) when
  two or more members are active, a `be` rule when one is (`in_force`); a `be` rule
  keeps only the values the layout still has (`effective_values`) and one left with
  none is inert. Identity `RuleInstance("forced_friends", (group_id, rule key))`
  (`share:room`, `must:building:A|B`), size `split_units` for `share` (members
  outside the largest party sharing a value, so the Room axis compares `(building,
  room)`) and the number of members breaking it for `be` (`violates_be`; a Helper by
  their Assignment, an Organizer anchor by `Anchor.violates`). `solver/rules.py`
  `FORCED_FRIENDS_FAMILY` (tier between Tag restrictions and Equipment) states
  it as a max-count slack per share rule and a per-Helper "outside / inside the
  set" slack per be rule, and `_check_forced_friends` judges it live
  (the line is the same wording in both, `GroupRule.line(assignments)`: `Group
  Rodina [Anna, Petr, Jana] is split across rooms N4 and N6`, naming the active
  members and the distinct places their Assignments occupy on the axis (a Room
  name shared by two Buildings is suffixed with its Building); a be rule's reads
  `Skupinka Rodina: pravidlo „musí být v budově A“ porušují Petr (B)`). Because a slack
  knows no places, `Relaxation` has an optional `describe_placed(units,
  assignments)` that `to_broken_rule` uses with the solved roster; its
  `FixTarget` is `("forced_friends", group_id)`, which `fix_focus` turns into
  a highlight on the group's card, scrolled to while the rule is still broken). `Competition.forced_groups` carries the
  groups (`mutations._build_competition`, `attending()`). Mutations:
  `add_group(workspace, name, person_ids, rules)` / `update_group(..., rules=)` /
  `dissolve_group`; a create, or an edit of people or rules, marks an existing
  roster stale, a rename does not, and a dissolve does only if some rule was
  actually pulling placed members (`_was_pulling`, `in_force`). `_validated_rules`
  refuses no rules, a malformed or repeated rule, a Building/Room the layout lacks
  (unless the group already named it) and a provable contradiction
  (`forced_friends.contradictions`: the be rules' allowed Roles, Buildings and
  Rooms per member, intersected; share rules never contradict). A bare axis name
  is accepted as a `share` rule. Only registered people can be
  picked (a member already in the group is kept even when not registered).
  `list_groups` also gives each group a `status` (`active` / `dormant` /
  `violated`, the last from `mutations.broken_rules`, so never before a roster
  and never for a dormant group) and its `violations` lines; the tab's badge and
  the group cards (Edit opens a dialog with the rule list, Dissolve confirms)
  read them, with `rule_texts`, `badges` (Organizer warnings, see below) and
  `missing_places` (notes for be-rule places the layout lacks, which are inert).
  `mutations.grid_forced_groups(state)`
  gives the grid `{helper_id: ["Rodina (musí sdílet místnost; ...)"]}` for the active
  members of groups in force (a dormant group marks no one), passed as each
  helper's chip data; the chip (`grid/render.py` `helper_chip`) shows a link mark whose tooltip
  lists them. The one blocking edit-time check is `forced_friends.tag_clashes`
  (the members' `tags.allowed_values` intersected per shared Building/Role axis,
  and against what the be rules allow every member, a "must be in room X" counting
  as its Building; a clash is per member when no rule shares the axis; Room is
  judged as Building; a member with an empty allowed set of their own
  is left to the Helper dead-end check; Can't attend and unregistered members
  are not counted). `forced_groups._refuse_tag_clash` runs it on `add_group`
  and on an `update_group` that changes people or rules (a rename never blocks,
  and an already-clashing group can only be edited towards holding), and
  `mutations._stranded` / `_refuse_new_dead_ends` carry group clashes as
  `(group id, axis, "group")` entries next to the Helper dead ends, so
  `set_helper_tags`, `add_tag_to_helpers` and `update_tag` refuse a Tag change
  that newly empties a group's intersection. Organizer members: a member is a
  Person, and `list_groups` resolves them to a Helper, an Organizer (`kind`;
  state `active` when placed, `unplaced` otherwise, `cant_attend` when flagged)
  or nobody, so a promoted Helper (same `person_id`) stays a member. A placed,
  attending Organizer is an `Anchor` on a `GroupRule`
  (`group_rules(helpers, groups, organizers, buildings)`, `active_organizers`,
  `active_member_count`): a share rule on the Building axis takes every anchor,
  on the Room axis only those holding a Room, and a Room share with a
  Building-level anchor gets an extra Building rule for it; the Role axis never has
  anchors. A be rule on a Building judges every anchor by their Building, on a Room
  an anchor holding one by it and a Building-level one by its Building as far as
  that goes (`Anchor.violates`: "must" breaks only if the Building holds none of the
  rooms named, "must not" never breaks); a role rule skips Organizers. The solver
  adds an anchor as a fixed head to a share count of its Building/Room
  (`ModelContext.organizers`) and the anchors already breaking a be rule as a
  constant in its slack, the checker adds them to what it compares
  (`BrokenRule.organizer_ids`, cells for a Room-level anchor), and a rule with two
  anchors and no Helper is a constant the solver reports but cannot fix. An
  Organizer is never refused: `forced_groups.organizer_notes` gives non-blocking
  warnings (`Role se na <name> neuplatní`; a Building-level Organizer on a room
  rule), shown as the `badges` on the card and live in the edit dialog. The
  edit-time Tag check counts Helpers only. `forced_groups.friend_requests(state)` and
  `make_forced(workspace, helper_id, friend)` (friend: Helper id or
  `{"organizer_id": n}`) back the "Vynucení kamarádi v místnosti" multiselect in a Helper's popup (Friends tab; the Forced friends tab itself no longer has it; `unforce(workspace, helper_id, friend)` dissolves the exact two-person group whose only rule shares a Room again):
  a normal `add_group` named `Anna + Petr` with the one rule "share Room", refused when that
  exact group exists (`_same_group_exists` compares `effective_rules`, where `share
  building` beside `share room` adds nothing); the request is not touched. The grid marks Helper chips
  only (`grid_forced_groups` counts a placed Organizer towards a group being in
  force), Organizer slot chips carry no group mark. Import from an
  earlier Season: the second `ImportSection` (`forced_groups`, registered at the
  bottom of `forced_groups.py`; `mutations.py` imports that module last so it
  loads wherever `mutations` does), see the Tag import note below.
  Helper ones and have no UI yet. Organizer Can't attend/Tags are separate,
  later tickets (the Organizer record already may carry a direct-Tag id list,
  `tags`, which promotion fills; nothing else reads it yet).
  Helper ones and have no UI yet. Organizer Can't attend: `cant_attend: true`
  on the record (`Organizer.cant_attend`; absent = off), set only by
  `mutations.set_organizer_cant_attend` (+ `organizer_cant_attend_impact`), the
  Helper flow with the slot entries as the thing cleared (placement follows
  through `_sync_placements`, roster staled); `_place_organizer` refuses an
  absent Organizer (`RosteringError`), `Competition.attending()` drops absent
  Organizers (so the check, the solver's friend scoring — a request naming one
  is not scored, silently — and, via `export.people.without_absent`, the export
  never see them). `promote_helper` does not carry the Helper's flag over
  (documented choice: promoting is deliberate, the Organizer attends). UI:
  the Organizers table of the People tab (`ui/tabs/people.py`), whose person sheet has the Can't attend checkbox, the e-mail/name edit and a delete (`ui/tabs/person_sheet.py`, confirmed first). Organizer Tags: the
  record's direct-Tag id list `tags`, with parallel functions to the Helper ones
  (`organizer_tags`, `set_organizer_tags`, `remove_tag_from_organizer`,
  `tag_organizer_carriers` / `tag_organizer_counts`, `organizer_tag_pills`,
  `dimmed_organizer_ids`, `organizer_allowed`; `add_tag_to_helpers` takes
  `organizer_ids` too, `tag_delete_impact` lists `organizers`). The dead-end
  validation covers them on the Building axis only (`_stranded` keys are
  `(kind, id, axis)`); the live checker's tag family also judges an Organizer's
  placement (`RuleInstance("tag_building", ("organizer", id, building))`,
  `BrokenRule.organizer_ids`, `FixTarget.organizer_id`), which the solver never
  reports (a placed Organizer is a fixed anchor), and `mutations.broken_rules`
  judges those even before the first solve (only they: an empty roster breaks no
  minimum). The People tab's popups and the Tags tab list Organizers
  beside Helpers; the grid passes each slot chip's `tags`/`dimmed`/`broken` on its
  `manual_entries` entry. Tag import re-applies them to Organizers across Seasons
  (see the Tag import note below).
  Friend references: a Helper's `friends` is one list of unified references —
  a plain int is a Helper id, `{"organizer_id": n}` (`OrganizerRef` on the
  domain `Helper`; `serialize.friend_ref_to_json`/`friend_ref_from_json`) an
  Organizer; `mutations._friend_key` is their comparable form. Ingestion:
  `parse_raw_survey(path, organizers=...)` puts the Season's Organizers in the
  name-resolution pool next to the Helpers (same normalized/fuzzy matching, a
  Helper wins a shared name; `upload_responses` passes them), and
  `resolve_friend` takes `resolved_organizer_ids` too. A new Organizer
  (`add_organizer`, `import_organizers`) runs `mutations._retry_unresolved_friends`,
  which matches every still-unresolved name again with the survey's own rules
  (`raw_survey.build_friend_index` / `resolve_friend_names`, shared with
  `parse_raw_survey`) against the Season's Helpers and Organizers: a name that
  resolves cleanly (and not to the Helper themself) becomes a
  `friend_name_decisions` entry plus a `friends` entry, so it can be reset and
  returns to unresolved when the Organizer is deleted; the UI notifies the
  count (`person_sheet.notify_friends_matched`). Scoring:
  `scoring.build_organizer_requests` (none under `mutual`) feeds a term in
  `solve_competition` at the Helper-to-Helper weight — satisfied by the exact
  (Building, Room) when the Organizer has a Room, by any Room of the Building at
  Building level, never when unplaced; Organizers are constants there, never
  variables. `build_friend_pairs`, `SolveResult.*_friend_pairs` and the
  diagnostics stay Helper-to-Helper only. The grid's Kamarádi overlay shows the
  Organizer requests too, judged live by `grid.data.organizer_request_met` with
  the solver's rule (`GridView.organizer_status` / `organizer_requesters`, kept
  apart from the Helper maps because Helper and Organizer ids overlap; a request
  naming an Organizer who can't attend is not shown): the Helper chip's
  `data-organizer-friends`, the Organizer chip's `data-requesters`, the hover in
  `roster_grid.js`, the "(organizátor)" lines in the details card, and an unmet
  one counts for the unsatisfied marker. `mutations.promote_helper`
  (confirmation like Can't attend when the Helper has an Assignment or Manual
  role entries) creates the Organizer (Person link with `link_confirmed` /
  `rejected_person_ids`, name, e-mail, `tags`), removes the Helper, and re-points
  others' `friends` and `friend_name_decisions` via `_repoint_friend`;
  `delete_organizer` drops an Organizer from them like `delete_helper`.
  `mutations.demote_organizer` (UI: the Organizer sheet's "Převést na pomocníka") is the
  reverse: a hand-added Helper carrying the Organizer's `person_id`, link decisions, name,
  e-mail, phone, T-shirt size, Can't attend flag and Tags (`_add_valid_tags` skips one
  that would strand them on a Room/Role axis; `demote_organizer_impact` lists those and
  the slots held, which `ConfirmationRequired` shows), with a fresh Helper id; the
  Organizer's slots go (stale reason when any), others' friend references are repointed
  to the Helper id (`_repoint_friend`), and a Person already holding a Helper record of
  the Season is refused. The Organizers' sheet answers are not carried. A
  re-upload still replaces the whole Helper list, so it brings a promoted
  Helper back into the pool.
- Tags tab tree (`ui/tagtree/`): `build_rows(state, focus_tag_id)` (pure) makes the rows
  in `tags.tree_order` (`id`, `parent_id`, `depth`, `name`, pill `style`, counts, `note`,
  `has_children`, `focus`) and `TagTree` shows them through `tag_tree.js`, a plain ES-module
  Vue component (package data of `rostering.webapp.ui.tagtree`) that keeps the fold
  state and search filter client-side and emits `tag_select`, `tag_move {id, parent_id}`
  (null = root) and `tag_toggle`; it offers no drop on the Tag itself, a descendant
  or the current parent, but `TagsTab._move` just calls `mutations.update_tag(parent_id=...)`,
  which does the real validation. Siblings stay alphabetical, so a drop picks no position.
  `SeasonView.tags_collapsed` / `tags_search` survive redraws; the ancestors of the
  selected / "Go fix" Tag are opened on each draw.
- Tags (`rostering/tags.py`, the Tags mutations in `mutations.py`): the
  Season's Tag tree is `state["tags"]` (dicts `id`, `name`, `colour`, `note`,
  `parent_id`; ids from the high-water mark `state["next_tag_id"]`, never
  reused), and a Helper's *direct* Tags are the Tag ids in its record's
  `tags`. Effective Tags (direct plus every ancestor) are never stored:
  `tags.effective_tag_ids` / `implied_tag_ids` / `via_tag_id` are pure
  functions of the Tag definitions and the direct ids, reached through
  `mutations.helper_tags`, `tag_carriers` and `tag_helper_counts`. Writes are
  `add_tag` / `update_tag` (unique name ignoring case, hex colour, parent
  refused when it is the Tag itself or a descendant) / `delete_tag` (raises
  `ConfirmationRequired` for a Tag with carriers or children unless
  `confirmed`; then strips it and re-parents its children) and
  `set_helper_tags` / `add_tag_to_helpers` / `remove_tag_from_helper`. Tags
  are part of every Version, empty after Start over, and stay through a
  re-upload (the recognized record is updated in place); `Workspace` gives a
  state saved before Tags existed an empty tree on read. UI: `ui/tabs/tags.py` (a searchable table of the tree; a row click sets `SeasonView.selected_tag`) and `ui/tabs/tag_sheet.py` (`TagSheet`, the right-hand sheet with the form, carriers and delete, open exactly while a Tag or `"new"` is selected on the Tags tab)
  (the "2. Štítky" tab) and the Tag picker in a person's sheet in the People tab (`ui/tabs/person_sheet.py`), both drawing pills through `ui/pills.py`.
- GCHD sheet (`rostering/ingest/gchd_sheet.py` `read_gchd_sheet`, columns from
  `mapping.GCHD_FIELD_HEADER_CANDIDATES`; `mutations._apply_gchd_classes`, see
  `CONTEXT.md`): `parse_raw_survey` reads only the export's first sheet, so
  `upload_responses` reads the sheet named GChD (any later sheet, normalized name)
  from the same temp file and applies it to the loaded state after the merge,
  before the one save (`_append_tag` is `add_tag` minus the save; Tags reach a
  Helper through `_add_valid_tags`, so a Tag constraint can skip one). Helpers
  are matched to students by normalized e-mail only: a same-name student with
  another e-mail is not tagged, because that is the uncertain-match question
  Persons already ask. Unmatched students and skipped Tags go to
  `state["ingestion_warnings"]`. Tests: `tests/test_gchd_sheet.py`.
- Tag import (`mutations.py`, "Tag import" section; UI in
  `ui/tag_import.py`): `import_from_season(workspace, source_season_id,
  selections=None)` runs every `ImportSection` in `_IMPORT_SECTIONS`
  (`register_import_section`; the building layout is the first, Tags the second,
  Forced friends groups the third) over one earlier stored Season (read through `Workspace.stored_state`,
  never written) against the open state, saved once, and returns `{"source",
  "sections"}`; the Tags section summary has `tags_created`, `tags_restored`,
  `tags_reused`, `helpers_tagged`, `dropped_constraint_entries`,
  `skipped_assignments`, `awaiting_review` and display `lines`. A section a user
  can choose from also has an `overview` (`ImportSection.overview`, surfaced by
  `import_overview(workspace, source_season_id)`) and reads what was ticked from
  `ImportContext.selections[key]` (`selections` of `import_from_season`; no entry
  means everything). The Forced friends section (`forced_groups.py`, "Import from
  an earlier Season"; key `forced_groups`, selection = source group ids) lists
  each source group with `returning` / `missing` names, `importable` (at least
  one member is a Person with a Helper or Organizer record here, so recognized by
  `person_id`; an unreviewed uncertain match shares none, so is not carried and
  its member is a `not_registered` placeholder that turns live once the link is
  confirmed) and `already_present`; it copies each ticked, importable group whole
  (all members kept as `{person_id, name}`, own id from `next_forced_group_id`,
  canonical axes), skips one whose member `person_id` set and axes equal an
  existing group's, raises the stale flag when a roster exists and a group
  arrived, never refuses on a Tag clash (it lists it in the summary; the solver
  reports it as a Broken rule) and summarises `groups_imported`,
  `groups_inactive`, `groups_skipped`, `groups_left_out`,
  `groups_without_returning`, `tag_clashes` and `lines`. The UI dialog shows one
  tick per group before the Import button. Offer helpers: `import_sources`, `default_import_source`,
  `tag_import_offer` (also the `banner` flag). A Tag record gains `origins`, a
  list of `{season_id, tag_id}` (a copy gets one; a same-name Tag already there
  is matched and gains one, without being changed), and the state gains
  `tag_imports`: source Season id -> `{label, deleted_tag_ids}` (`delete_tag`
  records a deleted imported Tag there, so an explicit re-import restores it and
  reports it; Class promotion adds `promoted_years` and `unpromoted_tag_ids` to
  the same entries). Tags are resolved origin first, then name (`_resolve_import_tag`),
  the name being the source Tag's as promoted so far (`_imported_name`), by the
  import, and by the late-link step `late_link_tag_offer` /
  `apply_late_link_tags` (the Person's direct Tags in every imported Season;
  never recreates a deleted Tag). Applying Tags to a Helper goes through
  `_add_valid_tags`, which skips (not refuses) what would newly strand them.
  Organizers take part on both sides: `_source_direct_tags_by_person` unions a
  Person's Helper and Organizer records of the source (by `person_id`), the Tags
  section applies them to the open Season's Helpers *and* Organizers
  (`_add_valid_tags(..., kind="organizer")`, Building axis only like
  `_stranded`; a skip is `{"kind", "<kind>_id", "<kind>", "tag_id", "tag",
  "reason"}`), and so promotion (source Helper, now Organizer) and its reverse
  work through the shared `person_id`. The summary has `organizers_tagged` and
  `organizers_awaiting_review` next to the Helper lists (`uncertain_candidates`
  run per `kind`; the display lines for Organizers show once the Season has any).
  An Organizer's link is confirmed with `link_organizer` (no UI yet), then
  `late_link_organizer_tag_offer` / `apply_late_link_organizer_tags` mirror the
  Helper pair over the same `_late_link_tags`, so `render_late_link_prompt`
  (Helper-only) has no Organizer counterpart until the Organizer review has a
  screen. A Person who is both a Helper and an Organizer in the open Season
  (possible after a re-upload brings a promoted Helper back) is tagged on both
  records. Tests: `tests/test_tag_import_organizers.py`.
- Class promotion (`mutations.py`, "Class promotion" section; the pure name
  rules `tags.is_class_name` / `promoted_class_name`, the year rule
  `season_label.school_years_crossed`; UI in `ui/tag_import.py`):
  `class_promotion_offer(workspace)` returns `suggestions` (class Tags with an
  origin that are a school year behind: `tag_id`, `name`, `target`, from the
  Tag's newest origin's Season label read fresh, so a rename of the source is
  followed), `other_tags` (everything else, `target` = the exact current name,
  for adding by hand) and `nothing_to_promote`; the years crossed are never
  exposed. `apply_class_promotion(workspace, {tag_id: target})` renames all
  ticked Tags at once in place (a target equal to the current name is no rename),
  refusing with `RosteringError` on what `class_promotion_conflicts` lists (an
  empty name, or a target another Tag keeps or is renamed to, case-insensitive;
  no merging). It also records, per source in `tag_imports`, `promoted_years`
  and `unpromoted_tag_ids` (source Tag ids of suggestions left unticked, still
  suggested next time). `import_from_season` returns `promotion_prompt` (current
  label podzim and a school year crossed), which makes the import open
  the dialog by itself (`tag_import.open_import`); the Tags tab has an
  always-available "Promote classes" button.
- Roster grid Overlays, Tag colouring and filter: the Roster tab's "Zobrazení"
  (Overlays) chips (`grid.data.OVERLAYS`, key -> label; the choice is
  `SeasonView.grid_overlays`, Friends on to begin with) switch on decorations;
  `grid.data.build_view` takes the active keys. A future overlay (Buildings,
  Roles) is one entry in `OVERLAYS` plus its drawing in `grid/render.py`. (Not to
  be confused with the deprecated "Overlay role" term, see `CONTEXT.md`.)
  *Friends* gates the hover highlights (`roster_grid.js`, from the chip's
  `data-friends` / `data-requesters`) and the persistent orange unsatisfied
  marker (off = neither); the details card's friend lists are not an overlay.
  *Role satisfaction* (`role_fit`) gives a placed chip a thick left border and
  *Building satisfaction* (`building_fit`) a thick top border
  (`GridView.role_fit` / `building_fit`, `.role-fit-*` / `.building-fit-*` in
  `render.CSS`). Role satisfaction is a five-step gradient on the preference
  level for the placed Role (`role_fit` returns 5..1, `.role-fit-5` green, 4
  yellow-green, 3 yellow, 2 orange, 1 red; blank = Nevadí, Záloha unjudged);
  Building satisfaction stays green/red: satisfied when the Building is in the helper's `acceptable_buildings`
  (`grid.data.acceptable_buildings`, matched with `building_keys`; empty Building
  preference = every Building). *Tags* stripes each chip (Helper and Organizer
  alike) into equal segments, one per **direct** Tag in its colour
  (`render.tag_stripe_style`, tinted with `color-mix` so the normal text stays
  readable; Tag names incl. inherited ones go in the tooltip), and is the only
  thing that shows the Tag filter. `mutations.grid_tag_pills(state)` (each
  Helper's `{direct, implied}` pills as `{name, colour}`, from `helper_tags`)
  feeds the stripes and `mutations.dimmed_helper_ids(state, tag_ids, mode)` (over
  the pure `tags.matches_filter`: all-of / any-of, inherited Tags count, an empty
  filter or an unknown Tag id matches everyone) the dimming;
  `RosterTab._overlay_controls` renders the chips and, with Tags on, the "Filtrovat
  podle štítků" select in tree order and the All of / Any of radio
  (`SeasonView.grid_tag_filter` / `grid_tag_mode`, pruned of deleted Tags on each
  draw). With Tags on, the Tag legend under the filter (`RosterTab._draw_legend`, over
  `mutations.grid_tags_present`: every Tag carried, directly or by implication,
  by an attending Helper or Organizer, in tree order with a `count`; `direct` is
  False when it is only implied, drawn dashed) shows them as pills whose click
  toggles the filter through the select's own `on_change`. With Tags off the filter is hidden and dims no one; another Season opens
  with the defaults again. Dimming is a `chip-dimmed` class (opacity, restored on
  hover; never a bare `dimmed`, which is a Quasar utility class that lays a dark
  overlay over the nearest positioned ancestor — the whole cell). Covered by `tests/test_grid_tags.py`, `tests/test_webapp_grid.py` and
  the smoke script (`tests/scripts/e2e/smoke.mjs`).
- Tag constraints: a Tag record carries `rules`, a list of the same rule
  dicts a Forced friends group has (`{"kind": "be", "must", "axis", "values"}`,
  axis building / room / role, any-of `values`; a Room is `[building, room]`; or
  `{"kind": "share", "axis"}`). The
  rule model (`Rule`, `value_label`, `effective_values`, `violates_be`) lives in
  `rostering/placement_rules.py`, shared with `forced_friends` (which re-exports
  it); `Tag.rules` holds them as `Rule`s (`mutations._validated_tag_rules`; roles
  may be written as display names). `be` rules restrict each carrier on their own
  (`tags.restrictions` skips `share`); a `share` rule is a group of the Tag's
  carriers: `forced_friends.tag_groups` derives, per Tag with `share` rules, an
  unsaved `ForcedGroup` (`id` = minus the Tag's, `tag_id` set, members = the
  `person_id`s of every Helper and Organizer whose effective Tags include it),
  and `Competition.rule_groups()` (saved groups plus these) is what the solver's
  `ModelContext` and `_check_forced_friends` read, so they ride the existing
  `group_rules` / `FORCED_FRIENDS_FAMILY` machinery (line "Štítek X [..] je
  rozdělen ...", `FixTarget("tags", tag_id=...)`). Everything else that reads
  `Competition.forced_groups` (edit-time Tag clashes, grid chip marks, the Forced
  friends tab) sees saved groups only, so a Tag's share rule never blocks an edit.
  The editor is `ui/tabs/rule_editor.py` `RuleEditor`, used by the Forced friends
  dialog and `TagSheet` (both `allow_share=True`; a Tag's new row starts on
  "musí být v", `new_op`). A Tag saved as
  `building_allow` / `building_deny` / `role_allow` / `role_deny` is read as the
  equivalent rules (`tags.legacy_rules`) and rewritten on load
  (`tags.migrate_state`, called next to `forced_friends.migrate_state`). The single
  source of truth for what a Helper may do is `tags.restrictions` / `blocking` /
  `allowed_values` / `allowed_rooms` (a pure function of the Tag tree, the
  Helper's direct Tag ids and the axis universe: the Season's configured
  Buildings, their `(Building, Room)` pairs, or the six Roles), used by the
  solver's `tag_restrictions` `RuleFamily` (`solver/rules.py`, tier between
  minimums and Forced friends), the live checker and the edit-time validation.
  `Competition.tags` and `Helper.tags` (direct ids, read from the record's
  `tags`) carry them to the solver. Entries naming nothing in the universe are
  inert (a "must" of only such entries does not narrow); Buildings are matched
  with `building_keys`, as Building preferences are, and a Room by its Building so
  and its name. The relaxation has one instance per Helper and disallowed
  Building/Room/Role (`tag_building` / `tag_room` / `tag_role`, entity `(helper id,
  value)`, a Room's value flattened to `building, room`), so the solver's line and
  the checker's are identical (`Štítek 8.M, musí být v budově Karlín`, the rule's
  own `Rule.text()`), and its `FixTarget` is `("tags", helper_id, tag_id)` (the
  first Tag that excludes the placement), which `fix_focus.go_fix` turns into the
  Tags tab's selection (`SeasonView.selected_tag`). A "must" Room rule does not
  also narrow the Buildings (so `forced_friends.tag_clashes`, which looks at
  Building and Role only, ignores Room rules). Validation is one shared step in
  `mutations` (`_stranded` / `_refuse_new_dead_ends`), run by `set_helper_tags`,
  `add_tag_to_helpers` and `update_tag`: it refuses an edit that leaves a Helper
  with an empty allowed set (Building, Room or Role; the Room axis only for a
  Helper with a Room rule, and not again when no Building is allowed) that they
  did not already have, so a Helper stranded by a later configuration change
  never blocks unrelated edits; deleting a Tag or removing one from a Helper only
  widens, so is not checked. Read-side helper: `mutations.helper_allowed`
  (`buildings`, `rooms`, `roles`); the sheet's "not in this Season" notes are
  `forced_groups.missing_places`. Tag import copies each rule with the values the
  Season has (`dropped_constraint_entries`: `tag`, `rule`, `entry`).
- Merged cells and the solver: sideways merges (`state["cell_merges"]`) are
  presentational, but `Competition.cell_merges` hands them to `solve_competition`,
  whose balance term spreads a *Building-wide* role count (`Building.capacities`) over
  the cells that role's row is merged into (`group_adjacent_rooms`; ceiling of
  count / cells is the even share, each person above it costs `GROUP_BALANCE_WEIGHT`).
  Soft, in the ordinary objective (below every rule); a role with no merge in that
  Building, or with per-Room counts, is untouched.
- The solver's role scope is fixed at the 6 roles (see `CONTEXT.md`); the
  Organizer/Additional roles are deliberately out of solver scope, entered
  manually as extra rows inside the same drag-and-drop grid
  (by dropping chips, never typing; the Additional roles take a helper's
  existing chip onto their own building's/room's cell) and
  merged in at export time.
- There is no default buildings/rooms layout: `Workspace.empty_state()` has
  `config: []`, so a new Season, a blank draft and "Start over" all begin with no
  Buildings (the layout lives only in each Season's own state). It comes from an
  earlier Season through the first section of the import offer, `mutations.py`
  `_import_layout_section` (key `layout`, run before Tags because Tag rules are
  copied only with the Buildings the Season has): it copies `config` and the
  `cell_merges` / `row_merges` that still fit (unfolding the old tall cells first
  and folding the new ones), never the leadership slot holders. With no
  `selections["layout"]` it goes only into a Season whose layout is empty; a
  different built layout is replaced only when ticked, after a
  `ConfirmationRequired` (`import_from_season(..., confirmed=True)`, asked through
  `UiSession.act` in `ui/tag_import.py`), and raises the stale flag when a roster
  exists. The Buildings tab's "Převzít z dřívějšího ročníku" opens the same dialog
  (`where="buildings"`). Or from the sheet import / by hand.
