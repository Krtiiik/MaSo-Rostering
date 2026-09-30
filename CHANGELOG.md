# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Two more Zobrazení modes on the Roster tab: "Spokojenost s rolí" gives each placed
  chip a thick left border (green when the Role is rated Nevadí or better, red for
  Spíš ne / Ne; Záloha is not judged) and "Spokojenost s budovou" a thick top border
  (green when the Building is one the Helper marked acceptable or they named none,
  red otherwise). They combine with the other modes.
- An "Obnovit výchozí budovy" button in the Buildings tab's bottom bar replaces the
  layout being edited with the default bundled with the app. Nothing is saved until
  "Uložit konfiguraci" is clicked, so it can still be dropped by reloading the page.
- The People tab's Organizers and Helpers tables now have a "Can't attend"
  checkbox per row (replacing the read-only "Status" text), so a person can be
  flagged or brought back without opening their popup. Flagging someone with an
  Assignment or Manual role entries asks for confirmation first, as before.
- A "Clear roster" button in the Roster tab's bottom bar removes every Assignment
  (locked ones too) and resets the solver result and the out-of-date warning, back
  to the state before the first Solve. It asks first, saying how many Assignments
  (and how many locked) go; Helpers, Tags, Organizers and Manual roles are kept.

### Changed

- The confirmation lines for a person or Organizer who holds a leadership slot now read
  "Organizátorská role: …" instead of "Manuální role: …".
- Each group in the Forced friends tab is now one line: the bold group name, its
  members and the status badge, with the "Upravit skupinku" editor folded directly
  under it (the big heading and the separate members list are gone).
- The role preferences in a Helper's edit (and add) form are stacked one role per row:
  the role name, a star rating (five stars = Ano … one star = Ne, none = no answer,
  counted as Nevadí) and, to the right, the Preference the stars map to.
- "Vynutit přání být s kamarádem" moved from the Forced friends tab into a
  Helper's popup. Its tab is now "Kamarádi": every friend name from the survey on
  top under "K přiřazení" (matched ones stay there, in their original order, and
  can be changed in place; there is no "Změnit přiřazení jmen z dotazníku"
  expander), then the "Kamarádi" multiselect (moved here from the
  Details tab; a pick saves at once), then a "Vynucení kamarádi v místnosti"
  multiselect over that Helper's own friends (picking one makes the Forced friends
  group of the two, unpicking dissolves it; replaces the per-friend "Vynutit"
  buttons).
- On the 5. Parametry rozřazování tab, each of the five Preference costs (Ano, Klidně,
  Nevadí, Spíš ne, Ne) is a row with its label and star rating (Ano five stars down
  to Ne one) on the left and a 0–20 slider on the right, followed by a Záloha row
  (no stars) in the same form. 20 is a fixed maximum (`MAX_ROLE_COST`); a saved cost
  above it is shown at 20. The role cost unit stays a number input above the rows.
- The Tags tab's "who carries this Tag" section is now one multiselect over every
  Helper and Organizer (replacing the carrier list with per-person "Odebrat" buttons
  and the separate "add to other people" picker). Tick or untick people and press
  "Uložit změny" to add and remove in one go; someone who carries the Tag only
  through a child Tag is listed with "(přes …)" and gets it directly when ticked.
- In the People tab's Helpers table, the Friends column of a Helper with unmatched
  friend names is a button that opens their popup straight on the "Jména
  kamarádů" tab, where the names are matched.
- The People tab marks a Helper with unmatched friend names with a coloured ⚠️
  emoji (before their name and in the Friends column) instead of the small
  monochrome ⚠ glyph.
- The People tab's Tags column shows coloured pills (solid for direct Tags,
  dashed for inherited ones) instead of plain text. The Equipment column shows
  💻 / 📷 icons instead of text.
- The People tab's Organizers and Helpers tables no longer open a person's popup
  from their name: the name is plain text and a ⚙️ button in a new last
  column opens the same popup.
- The web app's front end is now Czech: tabs, sidebar panels, buttons, dialogs,
  the roster grid and the messages it shows (errors, confirmations, Broken rule
  lines, import summaries, ingestion warnings) all use the agreed terms from
  `CONTEXT.md` and `docs/czech-ui-glossary.md` (e.g. Season → ročník, Roster →
  rozdělení pomocníků, Tag → štítek). Code, identifiers, the CLI and developer
  docs stay English, and the Excel export was already Czech. Counted text
  follows Czech plural forms (`rostering.czech.plural`). Stored data is
  unchanged; stale-roster reasons and dropped-lock notes already saved keep the
  English wording they were written with.
- The People tab's Organizers and Helpers tables are much lighter to render and
  rerun: each row is now one `st.columns` row of plain elements (a name button, a
  text per field, the Can't attend checkbox) instead of a fixed-height container
  per cell. Tags show as plain text (implied ones in brackets) rather than
  coloured pills.
- The Roster tab's "Zobrazit štítky" toggle is replaced by a "Zobrazení" multi-select
  (Kamarádi, Štítky; more to come). Kamarádi is on to begin with and is what turns
  on the friend-request highlights (hover outlines and the orange marker on a
  person with an unsatisfied request); with it off, chips are plain. Štítky
  colours each person's block by their tags, split into equal segments, one per
  tag (Organizers in leadership slots too), instead of showing pills under the
  name; hover a block for the tag names. The "Filtrovat podle štítků" controls
  now appear only while Štítky is on, and dim no one while it is off.
- The People tab's tables now size each column to its widest cell in the browser
  instead of from a character count worked out beforehand.
- Solving (Solve, Save & solve and Place new registrants) now runs in a modal
  "Solving…" dialog with a spinner that can't be dismissed (no close button, Esc
  or outside click) and closes itself when the roster is ready. Before, touching
  any widget mid-solve could drop the result from the screen. If a solve fails,
  the dialog shows the reason with a Close button instead.
- Adding a Building on the Buildings tab is now a single full-width "+ Add
  building" button instead of a name form; the new Building starts as
  "Building N" and is renamed in its own "Building name" field.
- The solver settings (weights, role costs, time limit, friend scoring) moved
  from the Buildings tab to their own "5. Solver" tab, with its own "Save
  settings" and "Save & solve"; the Roster tab is now "6. Roster". The
  Buildings tab's "Save & solve" saves only the layout and solves with the
  saved solver settings.
- The Tags tab's "Others (N)" section in the Tag edit menu is now titled
  "Add tag to others", saying what it does instead of showing a count.
- On the Buildings tab, each building's grid takes only the width its columns
  need instead of spanning the whole page.
- The role numbers of a Room and of a Building (the Buildings tab) are now
  exact counts instead of minimums: a Room or Building with "Fotograf 2" gets
  exactly two Fotografs, so too many breaks the rule as much as too few. 0 still
  means no limit. The Buildings tab labels the number columns "Counts", and the
  Broken-rule banner words an overshoot like "Building B · Skenovač: 3 of 2
  required (1 too many)"; the rule is still bent first, before every other
  rule. A saved Season keeps its numbers, which now read as exact counts.
- The "Upload" tab is now "People": a table-like view with the Organizers above
  and the Helpers below, each with a "＋ Add" button under the last row. Click a
  name to open that person's popup, which holds everything that was spread over
  the tab before: their fields, Can't attend, Tags, Person links, deleting, and
  (for a Helper) promoting to Organizer and matching the friend names they wrote.
  An Organizer can now be added, renamed, given an e-mail and deleted there.
- Matching friend names moved from one long list on the tab into each helper's
  popup (Friend names); a helper with names still to match is marked ⚠ in the table.
- On the Roster tab, a helper's details card opens when you click their chip
  instead of on hover, so it no longer gets in the way of dragging. Clicking the
  chip again, pressing Escape, clicking elsewhere or starting a drag closes it.
- The Buildings tab shows an "Unsaved changes" note while the layout on screen
  differs from what the Season has saved.
- The Buildings tab now comes after Tags and Forced friends, just before Solver
  and Roster (tab order: People, Tags, Forced friends, Buildings, Solver,
  Roster). The People tab's continue button now leads to Tags.

### Removed

- The "Tag helpers" list on the Upload tab (per-person pickers, a name and Tag
  filter, and "Apply a tag to all shown"). A person's Tags are picked in their
  popup, and a Tag is given to many people at once from the Tags tab.
- The editable helper and organizer tables (T-shirt size and Can't attend
  columns), replaced by the popup.
- The "Find a helper" box above the "Add tag to others" picker when editing a Tag. The
  picker itself is searchable, so the extra filter was redundant.

### Fixed

- On the Buildings tab, the "Remove building" button no longer overlaps the
  "+ Add room" button when its label wraps in a narrow column.
- The "Kamarádi" column of the People tab no longer counts friends who are
  flagged Can't attend (Helpers or Organizers).

## [1.1.0] - 2026-09-30

### Added

- Tag import re-applies Tags to Organizers as well as Helpers. What a Person
  carried directly in the source Season, as a Helper or as an Organizer, is
  re-applied to their confidently linked record this Season, whichever kind it is
  now (so a Helper promoted since gets their Helper Tags as an Organizer, and a
  former Organizer who registered as a Helper gets theirs back). An Organizer's
  assignment that would leave them with no allowed Building is skipped and counted
  like a Helper's (they have no Role, so the Role axis never skips one). The
  import summary gains an "Organizers tagged" line and an "Organizers awaiting
  review, not tagged" line beside the Helper ones (shown once the Season has
  Organizers), and an Organizer whose link is confirmed after the import can be
  offered "apply their Tags?" through the same origin-then-name resolution
  (`late_link_organizer_tag_offer` / `apply_late_link_organizer_tags`; the
  Organizer review has no screen yet, so the prompt itself is not shown in the
  app).
- Forced friends groups carry over to a later Season in the "Import from an
  earlier Season" offer, as its second section after Tags. The dialog lists every
  group of the source Season with its returning and missing members and a tick
  per group; each ticked group with at least one recognized person (a confirmed
  link or the same e-mail, an Organizer included) is imported as an independent
  copy, the members not registered this Season staying in it as dim "not
  registered" placeholders that turn live when they register and are recognized
  (a group left with fewer than two active members is imported inactive). Links
  still awaiting review are not carried, a group already present with the same
  members and axes is skipped on a repeat import, the source Season is never
  edited, and an existing roster is marked stale. The import summary lists the
  groups imported, skipped, left out and not imported next to the Tags.
- Organizers can be members of a Forced friends group, and a friend request can
  be made forced. A placed Organizer anchors the group at their placement (their
  Building, and their Room when they hold one; a Room group with an Organizer who
  only leads a Building enforces just that Building), an unplaced Organizer is
  dormant. An Organizer cannot be added to a group that shares Role, nor can Role
  be ticked on a group with one in it; a member who is promoted to Organizer stays
  in the group, the Role axis is no longer applied to them and the group shows
  "Role not applied to <name>". Dragging a Helper away from a group with a placed
  Organizer is an ordinary Broken rule. In the Forced friends tab, "Make a friend
  request forced" turns a resolved friend request into a new Room group of the two
  people and leaves the request as it was.
- Forced friends groups report their state. Each group in the Forced friends tab
  shows a status badge: Active, Dormant (with the reason, e.g. fewer than two
  active members) or Violated by the roster as it stands, with the violation
  named under it. The Broken-rule line now says who and where, e.g. "Group
  Rodina [Anna, Petr, Jana] is split across rooms N4 and N6" (the same words from
  the solver and the live check), its "Go fix" opens the group's editor, and a
  drop that newly splits a group toasts the line and still applies. The roster
  grid marks the chips of members of a group in force with a link symbol whose
  tooltip lists the group(s) and the axes they share. Creating a group, or
  changing its people or axes, is now refused when their Tags leave them no
  Building (a Room group counts as Building) or Role in common on a shared axis,
  and a Tag edit or assignment that would newly cause that is refused too;
  group size, capacity and locked or fixed Assignments never block, they show as
  Broken rules.
- Forced friends groups: a new "4. Forced friends" tab (the Roster tab is now
  "5. Roster") lists named groups of people who must share a Building, Room
  and/or Role, each with an editable name, a people multiselect, the axes to
  share (ticking Room implies Building) and an Active/Inactive badge. The solver
  treats a group as a hard rule between the Tag restrictions and Equipment
  eligibility: it keeps the active members together, transitively and
  independently per group (overlapping groups are never merged), and when a
  group cannot be kept it bends only after minimums and Tag restrictions and the
  roster is still returned, with the group listed as a Broken rule (also shown
  live, and toasted when a hand move newly splits one). A person may be in
  several groups. A member who Can't attend stays in the group but is inactive
  and flagged until un-flagged; a member not registered this Season is shown dim
  as "not registered" and becomes live if they later register and are
  recognized; a group with fewer than two active members constrains nothing.
  Creating a group or changing its people or axes after a solve moves no one and
  makes the roster stale (the banner blocks Export until the next Solve);
  dissolving one does so only if it was active and its members currently satisfy
  it. Groups are saved in Versions, cleared by Start over and kept on re-upload.
  Making a group from a friend request, Organizers as members and carrying groups
  into a later Season are separate, later changes.
- "Place new registrants" in the Roster tab's bottom bar places only the
  unassigned Helpers (late registrants, someone un-flagged from Can't attend)
  while everyone already placed stays exactly where they are: every existing
  Assignment is held fixed, still counting toward Room/Building minimums and
  Friend preferences, so a hand move that breaks a rule is neither repaired nor
  disturbed. It neither creates nor clears locks, leaves the "roster is out of
  date" flag as it is and, when not every rule can hold, still returns a roster
  with the Broken rules reported like any solve. A full Solve is unchanged and
  still discards everything except locked Assignments; you can also drag
  newcomers into the grid by hand.
- A survey row of someone you already added by hand merges into that Helper, and
  a leadership name you typed is offered a link to a newly recognized Helper.
  A row with the hand-added Helper's e-mail updates them in place; a row with
  only the same name waits on the Upload tab's review list, where "Merge" folds
  it into the Helper you added. Either way they keep their id, Assignment, lock,
  Tags, Manual roles and flags, no duplicate is left, and every Friend
  preference or role entry pointing at the row now points at them; the survey
  answers fill every field you left at its default while a value you typed by
  hand wins. A name you typed into a Manual role for someone unregistered is
  offered, in a new "Typed role names matching a Helper" list above the review
  list, a link to a registered Helper of the same name: Link turns the text into
  a real Helper reference (in every slot holding it), "Not the same person"
  leaves the text and is not offered again.
- Re-upload into an open Season keeps your hand work. Uploading a newer export
  into the open Season now runs the same recognition rules as a first upload
  against the Helpers already loaded: an identical e-mail refreshes that Helper
  from the latest row (Building preference, role Preferences, equipment,
  friend names, ...) and they keep their id, Assignment, lock, Tags, Can't
  attend flag and Manual roles; the same name with another e-mail becomes a new
  registrant and goes to the review list; duplicate rows collapse to the latest
  submission; Helpers missing from the export are kept. New registrants get
  fresh ids and land in the Unassigned pool. A friend name you resolved by hand
  keeps its resolution while the same name is still in the row and loses it when
  the name changes or goes; a field you typed by hand and a T-shirt size you set
  by hand (while the survey answer is unchanged) are kept. A placed Helper whose
  Building preference, Preferences or equipment changed keeps their Assignment
  and gets a ✎ marker on their chip in the grid, which stays until you move or
  lock them (or a full Solve re-places them). A summary at the top of the Upload
  and Roster tabs lists new registrants, changed answers (with the fields),
  Helpers missing from the export and uncertain matches awaiting review, and
  stays until you dismiss it. Export is blocked, with the reason, while any
  registrant is unassigned, and lifts as they are placed.
- Class promotion: a "Promote classes" button in the Tags tab moves school-class
  Tags (names like "8.M", "8. M" or "10.M": number, dot, optional space,
  letters) up one school year per school year crossed since the Season they were
  imported from; the school year turns at the jaro to podzim boundary, there is
  no top year and any other Tag ("GCHD") is never touched. The dialog lists one
  checkbox per suggested rename (the number of years is not shown, and it says
  there is nothing to promote when none was crossed), lets you add any other Tag
  by hand with a target name that starts as its exact current name, and writes
  nothing until Apply. It also opens by itself after an import when the open
  Season is podzim and a school year was crossed. Apply renames in place, all
  ticked Tags together so "8.M, 9.M, 10.M" become "9.M, 10.M, 11.M"; a name that
  an unticked Tag already has blocks Apply, and Tags are never merged. The Season
  remembers what was promoted and what was left alone, so a re-import or a
  late-confirmed link gets the promoted name.
- Tag import: bring an earlier Season's Tags into the open Season. An
  "Import from an earlier Season" button in the Tags tab is always available,
  and a banner on the Upload tab offers it while the Season has Helpers but no
  Tags and an earlier Season has some (it does not wait for the possible
  returning helpers review). One source Season per import, the most recent
  earlier stored Season preselected with a picker for any earlier one; importing
  again from another Season adds to what is there and never copies a Tag twice.
  The source's whole Tag tree is copied as independent Tags (parents and unused
  parents like GCHD included, with colour, note and constraints; entries naming
  a Building missing from this Season are dropped, the Tag stays), each
  remembering the Season and Tag it came from through renames. Directly carried
  Tags are re-applied to every Helper linked to a Person who carried them (by
  e-mail or a confirmed link); implied Tags stay computed, unreviewed possible
  returning helpers are not tagged, and an assignment that would leave a Helper
  with no allowed Building or Role is skipped. A summary lists the Tags created,
  Helpers tagged, dropped constraint entries, skipped assignments and Helpers
  awaiting review. Confirming a possible returning helper's link afterwards asks
  "Apply their Tags?" (matched by origin first, then name). An imported Tag you
  deleted comes back on an explicit re-import, noted in the summary. The offer
  is section-based, so further importable things can plug into the same flow.
- Can't attend and Tags for Organizers. The Upload tab lists the Season's
  Organizers (name, placement) with the same Can't attend checkbox as a Helper:
  flagging one who holds a leadership slot asks first, then clears their slot
  entries (so their placement) and makes the roster stale; an absent Organizer
  can't be given a slot, is left out of the Broken-rule check and the export, and
  a Helper's friend request naming them silently stops counting. Un-flagging
  restores nothing. Organizers are tagged like Helpers, in the Tags tab (they
  appear among a Tag's carriers and in "Others") and in the Upload tab's inline
  "Tag helpers" list (bulk apply included), carry effective Tags, and take Tag
  constraints on the Building axis (no Role, since they have none): an edit
  that leaves an Organizer no allowed Building is refused, and an Organizer
  placed outside their allowed set is reported as a Tag-restriction Broken rule
  (with a "Go fix" to the Tag), even before the first solve; a hand placement is
  never blocked. The Roster grid shows Organizers' Tag pills under "Show tags",
  dims them with the Tag filter and marks their chip when their placement breaks
  a rule. Deleting a Tag now also warns about and strips Organizers who carry it.
  Promoting a Helper does not carry over their Can't attend flag. Re-applying an
  Organizer's Tags in a later Season is part of Tag import (see below).
- Friend preferences toward Organizers, and promoting a Helper to Organizer. A
  Helper's friends can now name an Organizer as well as another Helper: survey
  friend names are matched against the Season's Organizers too (same matching;
  names that match nobody still show up to resolve), and the Upload tab's name
  resolution and the Helper edit form can pick Organizers. The solver scores such
  a request like a Helper-to-Helper one and against the Organizer's placement:
  met by sharing their Room when placed in a Room, by sharing their Building when
  placed only at Building level, never met while they are unplaced, and never
  counted under mutual friend scoring since an Organizer can't reciprocate. A
  placed Organizer is a fixed anchor the solver never moves. "Promote to
  Organizer" in the Helper edit form turns a Helper into an Organizer who keeps
  their name, e-mail, Tags and Person link, leaves the solver pool (asking first
  when it clears an Assignment, lock or role entries) and takes over the
  friend requests other Helpers made toward them.
- Organizers as a tracked person category: the four leadership slots (Vedoucí
  budovy, Pravá ruka, Vedoucí místností, Technická podpora) now hold only a
  tracked Organizer instead of a Helper or free text. Type a name in a slot cell
  on the Roster grid to pick an existing Organizer (autocompleted, ignoring case
  and diacritics) or create one on the spot; an Organizer has a name, an id, a
  Person link and an optional e-mail, is saved with the Season and in Versions,
  and takes no solver Role or Role capacity. Assigning an Organizer to a slot is
  the only way they are placed (a Room-scoped slot sets Building and Room, a
  Building-scoped one the Building); assigning them to a slot elsewhere moves
  their placement and removes their previous slot entries, and removing them from
  every slot clears it. A hand placement is never refused for the rules it
  breaks. The exported slot cells show Organizer names and the Organizer counts
  once, in their placed Building, on the T-shirt and Building sheets. Slot
  entries saved before this (a Helper or typed text) still display and export,
  marked "not tracked" in the grid, until replaced. Organizers are recognized
  across Seasons like any Person: an e-mail match links confidently, one without
  an e-mail is only an uncertain name match, and someone known as an Organizer who
  later registers as a Helper is offered a link on the review list, never
  promoted.
- Roster grid Tag pills and Tag filter: a "Show tags" toggle above the grid
  (off by default) renders each Helper's Tags as pills under their name, direct
  Tags solid and Tags carried only by implication dashed. A "Filter by tags"
  multiselect with an "All of" / "Any of" selector dims every Helper who does
  not match, never hiding anyone or moving the layout; inherited Tags count as
  matches (filtering by "GCHD" finds every 8.M Helper). The filter works with or
  without the pills, and hovering a dimmed Helper restores it to full strength.
  Drag and drop, locks and Broken-rule marks are unchanged.
- Tag constraints: a Tag can restrict where its Helpers go with allow-lists and
  deny-lists on Building and Role (not Room), chosen in the Tags tab's edit form
  from the Season's configuration; an entry naming a Building the configuration
  no longer has is inert and shown as "not in this Season". A Helper's allowed
  set per axis is the intersection of the allow-lists of all their Tags (own plus
  implied; a Tag with none does not narrow) minus every deny-list, so a deny
  always wins. A Tag assignment (the Tags tab, the Helper list's inline
  multiselect or the bulk apply) or a Tag edit that would leave any Helper with
  no allowed Building or no allowed Role is refused with the reason. The solver
  treats the allowed sets as a hard rule that bends after the minimums and before
  Forced-friend groups and Equipment, so a solve still returns a roster; the live
  Broken-rule check and banner report a Helper placed outside their allowed set
  ("Helper Anna (Tag 8.M, allows only Building Karlín) is placed in Impakt") with
  a "Go fix" that opens the Tags tab on that Tag, and a drop that newly breaks one
  toasts and still applies.
- Tags: a new "3. Tags" tab (the Roster tab is now "4. Roster") builds the
  Season's tree of named, coloured Tags. A Tag has a required name (unique in the
  Season, ignoring case), a colour, a note and an optional single parent Tag it
  implies; it can never become its own ancestor. The tab shows the tree indented
  by implication with coloured pills, a Helper count and an edit link per Tag,
  a "New tag" button, an edit form, and a "Delete this tag" panel that warns
  first, listing the Helpers who lose the Tag and the child Tags that move up to
  its parent (or become top-level). Under the form, "Has this tag" lists every
  carrier (direct ones with a remove button, inherited ones marked "via <tag>")
  and "Others" adds many Helpers at once with a find box and a multiselect.
  A Helper's effective Tags (direct plus every ancestor) are computed live from
  the tree, never stored. The Upload tab's Helper list gains a "Tag helpers"
  section: a per-Helper multiselect of direct Tags, a column of pills (direct
  solid, implied dashed) and a bulk "apply a tag to all shown" over the
  filtered list. Tags are saved per Season, in Versions, kept on a re-upload,
  and cleared by Start over.
- Add, edit and delete a Helper by hand: an "Add a helper by hand" form on the
  Upload tab needs only a name and a contact (a blank name or contact is
  rejected; a name or e-mail another Helper of the Season already has shows a
  warning but does not block). An e-mail-shaped contact is stored as the
  Helper's e-mail, so it takes part in Person matching (and links to the same
  Person if an earlier stored Season recorded that e-mail); any other contact
  is kept as a display contact and matching falls back to the name. Everything
  else is optional and defaults like a blank survey row: no Role preferences
  (each reads as Nevadí), no Building preference, no equipment, no friends,
  T-shirt size Unknown. The new Helper gets a fresh Helper id that is never
  reused, and is solved, shown in the grid, tagged and flagged Can't attend like
  any other, with no visual distinction. "Edit or delete a helper" changes any
  field at any time (an edit never moves anyone) and deletes a Helper; deleting
  one who holds an Assignment or Manual role entry asks first, exactly like
  Can't attend, then clears the Assignment (and its lock) and those entries and
  marks the roster stale. A deleted Helper is also dropped from other Helpers'
  Friend preferences (a friend name resolved only to them goes back to
  unresolved). The record remembers which fields were typed by hand.
- Can't attend: a "Can't attend" checkbox on every Helper row of the Upload
  tab's Helper list takes an absent person out of the picture. A flagged Helper
  is left out of the solver, the roster grid, the Unassigned pool, the
  Broken-rule check and the Excel export (roster sheet, T-shirt and per-Building
  sheets), with no special look in the grid, and a Friend preference naming them
  silently stops scoring (it is kept, so un-flagging restores it). Flagging a
  Helper who has no Assignment or Manual role entry applies at once. Flagging
  one who does asks first, naming what will be cleared; confirming clears their
  Assignment (and its lock) and every Organizer role and Additional role entry
  holding them, and cancelling changes nothing. Un-flagging only clears the flag:
  it restores nothing and does not re-solve, so the Helper returns to the pool
  for the next Solve. The flag is kept when the same Helper re-submits the
  survey (matched by e-mail, like a Returning helper), is per Season, and is
  saved with Versions. A flagged Helper can't be placed by hand.
- Stale-roster banner: clearing a placed Helper this way marks the roster stale.
  A banner with the reason appears next to the Solve button (and on the Upload
  tab), Export to Excel is disabled while it is up, and the next full Solve
  clears it. The flag is saved with Versions and reusable by any edit that
  invalidates a roster without moving anyone.
- Lock controls in the roster tab's bottom bar: "Lock all placed", "Clear all
  locks", a live "N locked" count, and a Solve button that reads "Solve (keeps N
  locked)" while any lock is set. A full Solve (also the Buildings tab's "Save &
  solve") that would replace unlocked Assignments first asks "N unlocked
  Assignments will be replaced", and does not ask when nothing would be lost. A
  Solve that had to drop locks because their Room or Building was removed says
  so ("N locks dropped: Room X no longer exists"); removing a Room is never
  blocked or prompted in the Buildings tab. Locking operations don't affect the
  Broken-rule check or the Excel export, saved Versions restore locks (an older
  Version without the flag restores as unlocked), and "Start over" clears them.
- Locked Assignments: a placed Helper's whole Assignment (Building, Room and
  Role) can be locked so that a full Solve keeps it and re-places everyone else
  around it. Ctrl/cmd-click a chip, or press the Lock/Unlock button on its hover
  card, to toggle the lock; a plain click and a drag are unchanged (a drag now
  starts only after the pointer has moved a few pixels), dragging a locked chip
  moves the lock with it, dragging an unlocked chip never locks it, and dropping
  a chip on an Additional-role overlay cell leaves the lock alone. A locked chip
  shows a padlock and a heavier solid border. Locked Helpers count toward Room
  and Building minimums and Friend-preference co-location, a locked Assignment
  that breaks a rule is still kept, and a lock whose Room no longer exists is
  dropped at the next Solve. Locks are saved with the Season and its Versions
  and are not written to the Excel export.
- A solve never fails because the hard rules clash. Room and Building
  minimums and Equipment eligibility now bend in a fixed order (minimums
  first, Equipment last, with room reserved for Tag restrictions and
  Forced-friend groups in between) and the solver always returns a full roster,
  keeping the ordinary preference and friend objective among rosters that
  break equally few rules. What it had to bend is printed by
  `rostering solve` and shown in the roster tab's Broken-rule banner (below).
  Export is not blocked by a bent rule.
- Live Broken rules: the roster tab now checks the current Assignments against
  the current rules on every render (nothing is stored) and shows a warning
  banner above the grid, replacing the status caption, with one line per broken
  rule grouped by family (Room and Building minimums as counts, e.g. "Room N4 ·
  Fotograf: 1 of 2 required (needs 1 more)", and Equipment, e.g. "Helper X has
  no camera but is Fotograf"). A family with more than ten broken instances
  collapses into an expandable summary. Each line has a "Go fix" button that
  switches to the Buildings tab (minimums) or the Helper list on the Upload tab
  (Equipment) and marks what to fix there until the rule holds again. The
  drag-and-drop grid lightly marks the affected Room headers, role cells and
  helper chips. A hand move is still never refused, and a drop that newly
  breaks Equipment eligibility shows a transient toast worded like the banner
  (nothing for a rule that was already broken, and never for minimums, which
  only appear in the banner and the grid marks). Export is never blocked and the
  exported sheet is unchanged by Broken rules.
- A "Time limit (seconds)" setting on the Buildings tab's solver settings.

- Uncertain-match review list: after an export is loaded, the Upload tab lists
  every Helper who has the same name as someone from an earlier Season (or
  another row of the same export) but no matching e-mail, with that Person's
  name, Season and e-mail and the phone as a hint (the survey's phone column is
  now read, for display only). Each candidate offers "Link" or "Not the same
  person"; a Helper with several candidates picks one or none. Unreviewed
  candidates stay unlinked, a rejected pairing is never proposed again, and a
  confirmed link is remembered independently of e-mail. A "Person links"
  expander on the Upload tab unlinks any Helper's link or links them by hand to
  any past Person; link edits never change a Helper id. Links and rejections
  are rolled back by Versions.
- Returning helpers are recognized across Seasons. The survey's e-mail column
  is now read at upload whatever its header wording (e.g. "E-mailová adresa",
  "Email Address", "Tvůj e-mail") and compared trimmed and lower-cased; a Helper
  whose e-mail matches one recorded in any stored Season is linked to the same
  Person automatically, even if their name changed (the most recent appearance
  wins if the e-mail is on record for several). Phone numbers are never used.
  The Upload tab counts Returning helpers and shows the earlier Seasons each
  was in. A Person exists only through the Seasons that record them, so Start
  over and deleting a Season forget what only they knew. Same-name rows
  without a matching e-mail are not linked automatically (see the review list
  above); an export without an e-mail column warns once.
- Duplicate rows in one export with the same e-mail now collapse to one Helper,
  the latest submission winning, with an upload warning naming who was
  collapsed; rows with different or blank e-mails are never merged.
- Stored Seasons: every Season is now a stored, labelled unit (a year plus
  `jaro`/`podzim`, e.g. `2026-jaro`; unique among stored Seasons, editable,
  and the key that orders them in time) in its own directory
  `data/seasons/<label>/` with its saved state and its Versions, and the
  Workspace is the open Season. Uploading with no Season open creates one,
  with the label prefilled from the export's submission timestamps (January to
  June is jaro, July to December is podzim) and editable; when the timestamps
  can't be read the label is asked for. Uploading while a Season is open is
  always a re-upload into it. The open Season's label shows in a header above
  every tab and can be renamed there (a rename renames the directory; a stable
  Season id survives it).
- A Seasons panel in the sidebar lists every stored Season (label, Helper
  count, open or stored) with Open, Rename and Delete (not offered on the open
  Season; the confirmation names what is lost, and the Season's Versions are
  deleted with it), and a "New Season" button that opens a blank Season.
- The first launch after this change moves an existing saved state and its
  Versions from `data/workspace/` into a Season (asking once for the label,
  prefilled from the file's date, since the old state kept no export
  timestamps). A Season directory with no saved state (e.g. a hand-placed raw
  export) is ignored.
- The exported roster draws a Large room across two columns in every Role
  band, automatically (no setting): a Room whose Room-band Helpers
  (Opravovatel to Fotograf; Záloha and Manual roles excluded) number at least
  1.5 times the median Room on the sheet, provided it is taller than the
  other Rooms in at least one band. The first column of each band fills to
  the tallest ordinary Room's height (raised if the Large room would need
  more than two columns), the second takes the rest, unused slots stay grey;
  the Room header and the Vedoucí místností / Pravá ruka cells merge across
  both columns and Building headers and Building-wide rows span the extra
  column. Fewer than three Rooms with Helpers, or a Room merged with a
  neighbour, never overflow. The in-app grid is unchanged. A Room merged for
  a Role stays one wide cell (one name per row) and may stretch that band
  only; a Large room in the same band fills its first column down to the
  stretched height, and needs a second column only if it is still taller
  than that height (the merged group's configured minimums count too).
- T-shirt size: each Helper now has a size (XS, S, M, L, XL, XXL, or
  Unknown), read from the survey question "Tvoje velikost trička" (matched
  ignoring case and surrounding whitespace). A blank, "?" or free-text
  answer becomes Unknown and adds an upload warning naming the Helper and the
  raw text; an export without the column warns once and leaves every Helper
  Unknown. The size is saved with the workspace (workspaces saved earlier
  load as Unknown) and in the helpers CSV written by `rostering ingest`
  (older CSVs without the column load as Unknown).
- A Helper's T-shirt size can be fixed by hand: the Helper list on the Upload
  tab shows a "T-shirt size" column with a dropdown (XS to XXL, or Unknown) to
  resolve the Unknowns flagged by the upload warnings. The edit is saved with
  the workspace and shows in the "Trička" sheet and per-Building lists of the
  next export. A size outside that set is rejected. (A hand-set size is not
  yet kept when a newer survey export is re-uploaded; re-upload still replaces
  all Helpers.)
- The exported workbook has a new "Trička" sheet right after the roster:
  T-shirt counts per size (XS to XXL, plus an Unknown row only when someone
  counted is Unknown) for each Building with Rooms, with a Celkem column and
  a total row, for the shirt order. It counts every solved Helper in their
  solved Building plus everyone holding an Organizer role in the Building
  that role names, each person once; a hand-typed-name Organizer-role holder
  counts as Unknown and an Organizer-role entry with no Building is not
  counted.
- The exported workbook now also has one helper-list sheet per Building with
  Rooms, after "Trička", in config order, for a Building lead to print:
  columns Jméno, Velikost trička, Místnost and Role (no phone numbers, no
  (n)/(f) tags). It lists the same people as "Trička", each once, sorted by
  Czech collation on the full name as entered ("ch" after "h", diacritics as
  tie-breaks; implemented in code, independent of the machine's locale). A
  Helper shows their solved Room and Role; an Organizer-role holder shows
  their Organizer role(s) instead (e.g. "Vedoucí budovy"), with the Room left
  empty when placed only at Building level. Sheet names are the Building name
  without `/ \ ? * [ ] :`, cut to Excel's 31 characters and made unique (a
  " (2)" suffix) if that makes two collide or clash with the roster or
  "Trička" sheet.

### Changed

- A solve now scores each Helper's role Preferences by a cost per rating
  instead of the old linear penalty: Ano 0, Klidně 1, Nevadí 2, Záloha 4,
  Spíš ne 6, Ne 12, times a unit (the "Role preference" weight, default now 1).
  A Role left blank counts as Nevadí, so a blank is no longer as good as an
  "Ano" (the survey upload and preview still show it as blank), and Záloha is
  no longer a free landing spot: a Helper who does not mind a real Role gets it
  rather than Záloha, while one who rated every open Role Spíš ne or Ne is
  still placed in Záloha. A Helper with `k` explicit "Ano" ratings (a blank
  never counts) has every other Role's cost multiplied by 1 + 1/k (x2 for one
  "Ano", x1.5 for two, x1.33 for three), so when two Helpers compete for a Role
  the one with a single "Ano" is kept on it ahead of one who has several to
  fall back on. Every objective term is scaled internally and the
  reported objective stays in the old scale. The unit and the six costs are
  editable in the Buildings tab's solver weights ("Unit for role costs" and one
  field per rating, whole numbers of 0 or more, no ordering enforced) with a
  "Restore role cost defaults" button, and are saved with the solver config. The
  unit is saved under a new key: an old saved "Role preference" weight (which
  was on the old scale) is ignored and the unit starts at the new default of 1.
  A missing setting now loads as the solver's own default, including the
  Building-mismatch weight (3, not the 10 the loader used to fall back to).
- A solve that finds no roster before the time limit now says "No roster found
  within N seconds" with a hint to raise the limit or solve again, keeps the
  existing roster, and is no longer reported as INFEASIBLE.
- "Start over" now empties the open Season's state but keeps its label, Season
  id and Versions (and, as before, the saved buildings layout).
- A Version snapshots the whole Season except its identity, and restoring one
  asks for confirmation, saying that Person links, rejections, Tags,
  Forced-friend groups and Assignments are rolled back; the Season's label and
  id are never rolled back.
- `ROSTERING_SEASONS_DIR` sets the Seasons directory; `ROSTERING_WORKSPACE_DIR`
  (the old saved-state location) still isolates a throwaway run, with Seasons
  under `<dir>/seasons`.

### Fixed

- Solver: a Helper's Building preference is now matched against the Season
  config's buildings ignoring diacritics, case and spacing, and recognizing
  the survey's building aliases. Previously the comparison was an exact
  string match, so a config naming a building "Mala Strana", "Karlin" or
  "Troja" never matched the survey's "Malá Strana", "Karlín" or
  "Impakt + Troja" — every stated Building preference was then treated as
  unmet for those buildings, silently skewing the solved rosters.

### Removed

- Solver: bringing a laptop is no longer a hard constraint on being assigned
  Kreslič — a helper without a laptop can now be assigned that role. Bringing
  a camera is still required for Fotograf. Whether a helper can bring a
  laptop is still tracked and still shown in the roster export (the `(n)`
  tag).

## [1.0.0] - 2026-09-22

### Added

- The overlay role "Uvaděči / Předávání cen" is now two separate,
  room-scoped roles: **Uvaděči účastníků** and **Focení předávání cen**.
  All three overlay roles (these two plus the existing **Registrace**,
  which is building-scoped instead of room-scoped) can still be filled by
  typing/picking a name, and now also accept dragging a helper's existing
  chip directly onto the overlay cell for the room/building they're
  already solved into — this duplicates them into that overlay slot
  (shown with a dotted chip border to mark it as a duplicate) without
  moving their solved-role assignment. A drop onto a different room/
  building than the helper's own is rejected.
- Roster grid: adjacent rooms' *cells* can now be merged within a single
  row — like merging cells in Excel, not the whole column. Hover a cell to
  reveal a small edge handle and click it to merge with its neighbor
  (repeat to merge a third, fourth, ...); click the "⊟" icon on a merged
  cell to split it back apart. This only affects that one row (a solved
  role, or a room-scoped manual role) — the room header and every other
  row for the same rooms stay separate. Purely a display/export grouping
  (a season config's actual rooms, and each helper's exact room
  assignment, are untouched); a merged cell shows the combined content of
  its rooms, and dropping a helper into one assigns them to the group's
  first room. Unmerged by default, matching every existing season's
  layout. Reflected in the Excel export too, using the same per-row
  merged-cell approach (`ws.merge_range`).

- Roster grid: a helper chip with an unsatisfied friend request is marked
  orange; hovering it now highlights every friend they named, wherever
  they're placed in the grid — green if that particular request is
  satisfied (co-located), red if it isn't — instead of only a generic "has
  an unsatisfied request" marker with no way to see who the request was
  with. Hovering also highlights, in purple, any other helper who named
  *them* as a friend (independent of whether it's reciprocated), so both
  directions of the friend graph are visible from one chip. All of this is
  computed from each helper's raw friend list as entered on the form, not
  from the solver's satisfied/unsatisfied diagnostics — those are collapsed
  by the friend-scoring config's mode/symmetric settings and could make a
  one-directional request look mutual or disappear entirely from the grid.
- Roster grid: hovering a helper chip now shows a card with that helper's
  preferred building(s), a star-rating list of their preference for each of
  the 6 roles, and their friend requests — color-coded to match the grid's
  existing highlighting (green = friend co-located, red = friend elsewhere,
  purple = someone else requested to room with them). The card appears after
  a short hover delay (so it doesn't flash while skimming across the grid)
  anchored with one corner near the cursor tip, and follows the cursor while
  it stays over the chip. The role-preference list excludes Záloha, which
  isn't offered as a choice on the form.
- `StructuralAssignment`/`OverlayAssignment` (`rostering.domain`) now
  accept a `helper_name` in addition to `helper_id`, for manual-role
  entries referring to someone who isn't a registered helper.

### Fixed

- Buildings tab: clicking "Remove room" under a room could remove a
  different room (typically the rightmost one) instead of the one the
  button was under, and could also silently carry a removed room's stale
  name/capacity values into the room that shifted into its place. Caused
  by widgets being keyed by the room's position in the list rather than
  the room itself.

### Changed

- Upload tab's "Resolve friend names" now lets an unresolved name be matched
  to more than one helper (via a multi-select instead of a single-select),
  for cases where a free-text name actually refers to a group of people
  rather than one individual.
- Roster grid: the Vedoucí budovy, Pravá ruka, and Vedoucí místností manual
  role cells are now plain free-text input, with no autocomplete against
  registered helper names and no attempt to resolve a typed name to a
  helper record — these roles are typically filled by people (teachers,
  organizers) who never registered as a helper. Overlay roles and
  Technická podpora, which layer onto an already-registered, already-
  assigned helper, keep the registered-helper autocomplete.
- Roster grid: the Vedoucí budovy, Pravá ruka, and Vedoucí místností cells
  now hold at most one name each, since each is a single-holder role (one
  building lead, one deputy, one lead per room) — the add-input hides once
  a name is set, and an existing name must be removed before a new one can
  be entered.
- Pravá ruka (building lead's deputy) is now scoped per room instead of per
  building, matching Vedoucí místností — each room can have its own deputy.
  Applies to the roster grid, the Excel export, and the manual-roles YAML
  loader (`room:` is now meaningful for both roles).
- Excel roster export now matches the layout and styling of the historical
  hand-built rosters: a single sheet (previously split across a "Roster"
  sheet and a separate overlay sheet) with the structural roles (Vedoucí
  budovy, Pravá ruka, Vedoucí místností) listed above the 6 solved roles,
  followed by the overlay roles (Uvaděči / Předávání cen, Registrace),
  Záloha, and Technická podpora — plus matching per-role label/data cell
  colors, a bordered grid, Arial font, frozen first column, and "(n)"/"(f)"
  equipment tags appended to helper names. Empty helper slots (a role's
  row-block sized larger than a room's actual headcount) now get a neutral
  soft-gray fill instead of the role's color, so an empty slot reads as
  empty rather than as another filled cell in that role's block. Column
  widths are now sized to roughly fit their content instead of a fixed
  width for every column.
- Roster tab: the manual structural/overlay roles (Vedoucí budovy, Pravá
  ruka, Vedoucí místností, Uvaděči / Předávání cen, Registrace, Technická
  podpora) are now extra rows in the same assignment grid instead of a
  separate section of selectboxes/multiselects below it, matching the
  historical hand-built roster layout. Their cells are not drag-and-drop
  targets; each has a name input with autocomplete suggestions from
  registered helpers, plus the ability to type a new name for someone who
  isn't a registered helper (manual roles are commonly filled by people who
  never registered).

### Removed

- The per-role *maximum* headcount setting (buildings/rooms config, the
  Buildings tab's "Max" column, and the corresponding CP-SAT upper-bound
  constraint) — helper counts are small enough that capping a room's
  headcount was never actually needed. Only the *minimum* headcount setting
  remains. Older config files with a `{min, max}` mapping still load; `max`
  is now silently ignored.

### Fixed

- Excel roster export: a role's row-block was sized only from its
  configured *minimum* per-room headcount, so a room where the solver
  actually placed more helpers than that minimum (capacities are usually
  unbounded above) overflowed into the next role's rows instead of
  expanding its own block.

## [0.3.0] - 2026-09-21

### Changed

- The "Continue", "Save & solve", and "Solve"/"Export to Excel" buttons in
  each tab now live in a floating bar anchored to the bottom of the
  viewport (`st.bottom`) instead of being placed inline within each
  tab's content, so the main action is always in the same spot regardless
  of scroll position or which tab is active.

### Fixed

- Friend-name resolution (upload tab): picking a match (or dismissing)
  from a name's selectbox made that row disappear immediately, so the
  choice couldn't be reviewed or changed afterwards. The row now stays
  visible with the current decision selected, and re-picking it updates
  the friend link instead of duplicating or losing it.
- Buildings & rooms tab: the "+ Add room" column now stretches to match
  the capacity grid's actual height instead of a fixed, overly tall
  min-height. The "Remove building" button moved to the left of the
  building name field and is bottom-aligned with it.
- Buildings & rooms tab: the "+ Add room" column's height-matching CSS
  from the fix above still ballooned it to roughly the full page height
  in practice, because filling it via plain nested `height: 100%` triggers
  a Chromium flexbox layout runaway (each reflow re-measures a stale,
  ever-growing ancestor height). It's now anchored with absolute
  positioning against its already-correctly-stretched column instead,
  which can't feed back into an ancestor's auto-height calculation.
- Roster grid: helper names assigned to the same room/role cell were laid
  out horizontally, overflowing the cell instead of stacking. Cells now
  stack names vertically, one per line.
- Roster grid: the previous fix applied `display: flex` directly to each
  `<td>`, which overrides its table-cell display and made the browser
  collapse every room's column into the first one — all buildings' helpers
  visually piled into a single leftmost column. The flex-column layout now
  lives on an inner wrapper `<div>` inside each cell instead, so rooms keep
  their own columns while names still stack vertically within each cell.
- Roster grid: helpers within a cell, and in the "Unassigned" pool, are now
  always sorted by name instead of following assignment/upload order.

## [0.2.0] - 2026-09-20

### Added

- `rostering` with no subcommand (e.g. double-clicking the standalone
  `.exe` from Explorer) now defaults to `rostering serve`, so a
  non-technical user can launch the app without knowing about the CLI.

### Fixed

- Standalone executable: `rostering serve` crashed with
  `FileNotFoundError: ... rostering\streamlit_app\app.py` because
  `packaging/rostering.spec` only force-collected `streamlit`, `ortools`,
  and `rostering_assignment_grid` — the `rostering` package itself was left
  to PyInstaller's static import-graph analysis, which never discovers
  `rostering.streamlit_app.app` since it's only ever loaded by file path
  (via `streamlit.web.bootstrap`), never `import`ed. The whole
  `streamlit_app/` package was silently missing from every frozen build.
  Now `rostering` is `collect_all`'d too, and the build workflow verifies
  `app.py` actually lands in the bundle (the prior `serve` smoke test only
  curled `/`, which succeeds even with a broken script since script
  execution only starts once a browser session connects).

### Changed

- Buildings tab: the per-building capacity editor is now a single horizontal
  table (role rows, building-wide Min/Max columns, then a Min/Max column
  pair per room) using `number_input` steppers instead of a vertical
  `data_editor` per room, with remove-room buttons under each room and a
  vertical "+ Add room" button alongside the table.

## [0.1.0] - 2026-09-20

### Added

- GitHub Action (`.github/workflows/build-executables.yml`) that builds and
  publishes standalone Windows/Linux/macOS executables of the `rostering`
  CLI/app via PyInstaller, attaching them to a GitHub Release on `vX.Y.Z`
  tag pushes (or as workflow artifacts on manual dispatch).

### Changed

- `rostering serve` now launches Streamlit in-process via
  `streamlit.web.bootstrap` instead of shelling out to
  `sys.executable -m streamlit`, and explicitly disables Streamlit's
  `global.developmentMode`. Both are needed for the app to run correctly
  from a frozen executable (where `sys.executable` isn't a Python
  interpreter and Streamlit's own `__file__`-based install detection gets
  confused), but apply equally to normal installs.
