"""PROTOTYPE — throwaway. Answers ticket #9: "What should managing and applying
Tags look like in the Streamlit app?"

Standalone, in-memory (nothing persists, nothing touches rostering state).
Three structurally different variants of the whole feature (tag CRUD, tagging
helpers, tags in the roster grid), switchable from the bottom bar or `?variant=A|B|C`.

Run:  uv run --with streamlit streamlit run prototypes/tags_ui_prototype.py
"""
from __future__ import annotations

import streamlit as st

BUILDINGS = ["Troja", "Karlín", "Impakt"]
ROOMS = {"Troja": ["T1", "T2"], "Karlín": ["K1", "K2"], "Impakt": ["I1"]}
ROLES = ["Opravovatel", "Měnič", "Skenovač", "Kreslič", "Fotograf", "Záloha"]
PALETTE = ["#e4572e", "#f3a712", "#29a19c", "#3b82f6", "#8b5cf6", "#d946ef", "#64748b", "#16a34a"]

_FIRST = ["Tereza", "Jan", "Veronika", "Petr", "Anna", "Lukáš", "Eliška", "Tomáš", "Kateřina", "Marek",
          "Barbora", "David", "Klára", "Ondřej", "Lucie", "Filip", "Markéta", "Jakub", "Adéla", "Matěj",
          "Nikola", "Vojtěch", "Šárka", "Martin"]
_LAST = ["Nováková", "Svoboda", "Dvořáková", "Černý", "Procházková", "Krejčí", "Horáková", "Němec",
         "Marešová", "Pospíšil", "Veselá", "Hájek", "Kolářová", "Bartoš", "Beneš", "Fiala", "Sedláčková",
         "Zeman", "Kučerová", "Urban", "Malá", "Kopecký", "Jelínková", "Sýkora"]


def _seed() -> None:
    if "tags" in st.session_state:
        return
    st.session_state.tags = {
        "GCHD": dict(colour="#3b82f6", note="Gymnázium Christiana Dopplera", parent=None,
                     allow_b=[], deny_b=[], allow_r=[], deny_r=[]),
        "8.M": dict(colour="#29a19c", note="Class 8.M at GCHD (promote to 9.M in autumn)", parent="GCHD",
                    allow_b=[], deny_b=[], allow_r=[], deny_r=[]),
        "Vozíčkář": dict(colour="#8b5cf6", note="Needs step-free building", parent=None,
                         allow_b=["Karlín"], deny_b=[], allow_r=[], deny_r=[]),
        "Nesnese fotit": dict(colour="#e4572e", note="Never Fotograf", parent=None,
                              allow_b=[], deny_b=[], allow_r=[], deny_r=["Fotograf"]),
        "Zkušený": dict(colour="#f3a712", note="Has done Opravovatel before", parent=None,
                        allow_b=[], deny_b=[], allow_r=[], deny_r=[]),
    }
    hs = []
    for i in range(24):
        b = BUILDINGS[i % 3]
        hs.append(dict(id=i, name=f"{_FIRST[i]} {_LAST[i]}", tags=[],
                       b=b, room=ROOMS[b][(i // 3) % len(ROOMS[b])], role=ROLES[(i * 5) % 6]))
    hs[0]["tags"] = ["8.M"]
    hs[1]["tags"] = ["GCHD", "Zkušený"]
    hs[2]["tags"] = ["8.M"]
    hs[5]["tags"] = ["Vozíčkář"]
    hs[7]["tags"] = ["Nesnese fotit"]
    st.session_state.helpers = hs
    st.session_state.setdefault("highlight", [])


# ---------------------------------------------------------------- tag logic
def ancestors(name: str) -> list[str]:
    out, cur = [], st.session_state.tags[name]["parent"]
    while cur:
        out.append(cur)
        cur = st.session_state.tags[cur]["parent"]
    return out


def descendants(name: str) -> list[str]:
    tags = st.session_state.tags
    return [t for t in tags if name in ancestors(t)]


def effective(direct: list[str]) -> list[str]:
    seen: list[str] = []
    for t in direct:
        for x in [t, *ancestors(t)]:
            if x not in seen:
                seen.append(x)
    return seen


def allowed(tag_names: list[str]) -> tuple[list[str], list[str]]:
    tags = st.session_state.tags
    b, r = set(BUILDINGS), set(ROLES)
    for t in effective(tag_names):
        d = tags[t]
        if d["allow_b"]:
            b &= set(d["allow_b"])
        if d["allow_r"]:
            r &= set(d["allow_r"])
    for t in effective(tag_names):
        b -= set(tags[t]["deny_b"])
        r -= set(tags[t]["deny_r"])
    return [x for x in BUILDINGS if x in b], [x for x in ROLES if x in r]


def assign_error(h: dict, new_direct: list[str]) -> str | None:
    b, r = allowed(new_direct)
    if not b:
        return f"**{h['name']}** would have no allowed Building."
    if not r:
        return f"**{h['name']}** would have no allowed Role."
    return None


def violates(h: dict) -> bool:
    b, r = allowed(h["tags"])
    return h["b"] not in b or h["role"] not in r


def helpers_by_tag(name: str) -> list[dict]:
    return [h for h in st.session_state.helpers if name in effective(h["tags"])]


def save_tag(old: str | None, new: str, data: dict) -> str | None:
    """Returns an error string, or None when saved. Validates name, cycles, and
    that no helper is left with an empty allowed set."""
    tags = st.session_state.tags
    new = new.strip()
    if not new:
        return "Name is required."
    if new != old and new in tags:
        return f"A tag called “{new}” already exists."
    if old and data["parent"] and (data["parent"] == old or data["parent"] in descendants(old)):
        return "A tag can't imply itself or one of its own descendants."
    snapshot = dict(tags)
    tags_new = {k: v for k, v in tags.items() if k != old}
    tags_new[new] = data
    if old and new != old:
        for v in tags_new.values():
            if v["parent"] == old:
                v["parent"] = new
    st.session_state.tags = tags_new
    for h in st.session_state.helpers:
        if old and new != old:
            h["tags"] = [new if t == old else t for t in h["tags"]]
        e = assign_error(h, h["tags"])
        if e:
            st.session_state.tags = snapshot
            return "Blocked — " + e
    return None


def delete_tag(name: str) -> None:
    tags = st.session_state.tags
    parent = tags[name]["parent"]
    for v in tags.values():
        if v["parent"] == name:
            v["parent"] = parent
    del tags[name]
    for h in st.session_state.helpers:
        h["tags"] = [t for t in h["tags"] if t != name]


def bulk_apply(ids: list[int], tag: str, add: bool) -> list[str]:
    errs = []
    for h in st.session_state.helpers:
        if h["id"] not in ids:
            continue
        new = [*h["tags"], tag] if add and tag not in h["tags"] else [t for t in h["tags"] if not (not add and t == tag)]
        e = assign_error(h, new)
        if e:
            errs.append(e)
        else:
            h["tags"] = new
    return errs


# ---------------------------------------------------------------- shared bits
def chip(name: str, faint: bool = False, small: bool = False) -> str:
    c = st.session_state.tags[name]["colour"]
    pad = "0 6px" if small else "1px 9px"
    fs = "0.68rem" if small else "0.78rem"
    if faint:
        return (f"<span style='border:1px dashed {c};color:{c};border-radius:99px;padding:{pad};"
                f"font-size:{fs};margin-right:3px;white-space:nowrap'>{name}</span>")
    return (f"<span style='background:{c};color:#fff;border-radius:99px;padding:{pad};"
            f"font-size:{fs};margin-right:3px;white-space:nowrap'>{name}</span>")


def chips(h: dict, small: bool = False) -> str:
    direct = h["tags"]
    return "".join([chip(t, small=small) for t in direct] +
                   [chip(t, faint=True, small=small) for t in effective(direct) if t not in direct])


def tag_form(old: str | None, key: str) -> None:
    """Shared field set (name, colour, note, parent, constraints) with live
    'what would a helper with only this tag be allowed' preview."""
    tags = st.session_state.tags
    d = tags.get(old) or dict(colour=PALETTE[len(tags) % len(PALETTE)], note="", parent=None,
                              allow_b=[], deny_b=[], allow_r=[], deny_r=[])
    with st.form(key, border=False):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("Name", old or "", key=f"{key}_n")
        colour = c2.color_picker("Colour", d["colour"], key=f"{key}_c")
        note = st.text_area("Note", d["note"], height=68, key=f"{key}_note")
        opts = ["— none —"] + [t for t in tags if t != old and (not old or t not in descendants(old))]
        cur = d["parent"] if d["parent"] in opts else "— none —"
        parent = st.selectbox("Implies (parent tag)", opts, index=opts.index(cur), key=f"{key}_p",
                              help="Everyone with this tag also gets the parent tag (and its constraints).")
        st.caption("Constraints — empty allow-list = no restriction; a deny always wins.")
        a1, a2 = st.columns(2)
        allow_b = a1.multiselect("Only these Buildings", BUILDINGS, d["allow_b"], key=f"{key}_ab")
        deny_b = a2.multiselect("Never these Buildings", BUILDINGS, d["deny_b"], key=f"{key}_db")
        allow_r = a1.multiselect("Only these Roles", ROLES, d["allow_r"], key=f"{key}_ar")
        deny_r = a2.multiselect("Never these Roles", ROLES, d["deny_r"], key=f"{key}_dr")
        ok = st.form_submit_button("Save tag" if old else "Create tag", type="primary")
    if ok:
        data = dict(colour=colour, note=note, parent=None if parent == "— none —" else parent,
                    allow_b=allow_b, deny_b=deny_b, allow_r=allow_r, deny_r=deny_r)
        err = save_tag(old, name, data)
        if err:
            st.error(err)
        else:
            st.session_state["_sel_tag"] = name.strip()
            st.toast(f"Saved “{name.strip()}”")
            st.rerun()


def delete_panel(name: str, key: str) -> None:
    aff, kids = helpers_by_tag(name), [t for t in st.session_state.tags if st.session_state.tags[t]["parent"] == name]
    with st.expander("Delete this tag…"):
        st.warning(f"Removes “{name}” from **{len(aff)}** helper(s)"
                   + (f" and re-parents child tag(s) {', '.join(kids)} to "
                      f"{st.session_state.tags[name]['parent'] or 'the root'}" if kids else "") + ".")
        if aff:
            st.caption(", ".join(h["name"] for h in aff))
        if st.button("Delete tag", key=key, type="primary"):
            delete_tag(name)
            st.session_state.pop("_sel_tag", None)
            st.rerun()


def tag_tree(select_key: str) -> str | None:
    """Indented tree of tags; returns the selected tag name."""
    tags = st.session_state.tags
    sel = st.session_state.get(select_key)

    def walk(parent: str | None, depth: int):
        nonlocal sel
        for t, d in tags.items():
            if d["parent"] != parent:
                continue
            n = len(helpers_by_tag(t))
            c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
            c1.markdown(f"<div style='padding-left:{depth * 18}px'>{'↳ ' if depth else ''}{chip(t)} "
                        f"<span style='opacity:.6;font-size:.8rem'>{n}</span></div>", unsafe_allow_html=True)
            if c2.button("edit", key=f"{select_key}_{t}", type="primary" if sel == t else "secondary"):
                st.session_state[select_key] = t
                st.rerun()
            walk(t, depth + 1)

    walk(None, 0)
    return sel


def mock_grid(mode: str = "chips", highlight: list[str] | None = None, only_matching: bool = False,
              key: str = "grid") -> None:
    """Fake roster grid: role rows × room columns. `mode`:
    chips  = name + small tag pills under it
    stripe = card coloured by first tag + tag names in tooltip
    """
    highlight = highlight or []
    rooms = [(b, r) for b in BUILDINGS for r in ROOMS[b]]
    hs = st.session_state.helpers
    st.caption("⚠ = current placement breaks the helper's Tag constraints" +
               ("  ·  dashed pill = inherited via implication" if mode == "chips" else ""))
    head = "".join(f"<th style='padding:4px 6px;text-align:left;border-bottom:2px solid #8884'>"
                   f"{b}<br><b>{r}</b></th>" for b, r in rooms)
    body = ""
    for role in ROLES:
        body += f"<tr><td style='padding:6px;font-weight:600;vertical-align:top;white-space:nowrap'>{role}</td>"
        for b, r in rooms:
            cell = ""
            for h in hs:
                if (h["b"], h["room"], h["role"]) != (b, r, role):
                    continue
                eff = effective(h["tags"])
                match = not highlight or any(t in eff for t in highlight)
                if only_matching and not match:
                    continue
                warn = " ⚠" if violates(h) else ""
                opacity = 1 if match else 0.22
                if mode == "chips":
                    cell += (f"<div style='border:1px solid #8886;border-radius:6px;padding:3px 6px;margin:2px 0;"
                             f"opacity:{opacity};background:#8881'><span style='font-size:.85rem'>{h['name']}{warn}</span>"
                             f"<div style='line-height:1.5'>{chips(h, small=True)}</div></div>")
                else:
                    first = h["tags"][0] if h["tags"] else None
                    col = st.session_state.tags[first]["colour"] if first else "#8886"
                    title = ", ".join(eff) or "no tags"
                    dots = "".join(f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
                                   f"background:{st.session_state.tags[t]['colour']};margin-left:3px'></span>" for t in eff)
                    cell += (f"<div title='{title}' style='border-left:6px solid {col};border-radius:4px;padding:3px 6px;"
                             f"margin:2px 0;opacity:{opacity};background:#8881;font-size:.85rem'>{h['name']}{warn}"
                             f"<span style='float:right'>{dots}</span></div>")
            body += f"<td style='padding:3px 6px;vertical-align:top;border-top:1px solid #8883;min-width:120px'>{cell}</td>"
        body += "</tr>"
    st.markdown(f"<table style='border-collapse:collapse;width:100%'><tr><th></th>{head}</tr>{body}</table>",
                unsafe_allow_html=True)


# ================================================================ VARIANT A
def variant_a() -> None:
    """A — dedicated 'Tags' tab: master/detail library + a bulk-tagging table.
    Grid: pills under names + 'highlight tag' dimming."""
    st.caption("Variant A · **A new “Tags” tab.** Tag library (tree + editor) on top, bulk tagging table below. "
               "Roster tab gets pills + highlight.")
    tab = st.segmented_control("Tab", ["1. Upload", "2. Buildings", "▶ Tags", "3. Roster"], default="▶ Tags",
                               label_visibility="collapsed", key="a_tab")
    if tab == "3. Roster":
        st.subheader("3. Roster")
        hl = st.multiselect("Highlight helpers with tag", list(st.session_state.tags), key="a_hl",
                            help="Dims everyone without it (inherited tags count).")
        mock_grid("chips", hl)
        return
    if tab != "▶ Tags":
        st.info("(unchanged existing tab)")
        return

    st.subheader("Tags")
    left, right = st.columns([2, 3], gap="large")
    with left:
        st.markdown("**Tag library**")
        if st.button("＋ New tag", key="a_new"):
            st.session_state["_sel_tag"] = "__new__"
            st.rerun()
        tag_tree("_sel_tag")
    with right:
        sel = st.session_state.get("_sel_tag")
        if sel == "__new__":
            st.markdown("**New tag**")
            tag_form(None, "a_form_new")
        elif sel in st.session_state.tags:
            st.markdown(f"**Edit** {chip(sel)}", unsafe_allow_html=True)
            tag_form(sel, f"a_form_{sel}")
            delete_panel(sel, f"a_del_{sel}")
        else:
            st.info("Pick a tag on the left to edit it, or create a new one.")

    st.divider()
    st.markdown("**Tag helpers**")
    f1, f2, f3 = st.columns([2, 2, 2])
    q = f1.text_input("Search name", key="a_q", placeholder="type to filter…")
    only = f2.selectbox("Show", ["All helpers", "Untagged only", *[f"Has “{t}”" for t in st.session_state.tags]], key="a_show")
    hs = [h for h in st.session_state.helpers if q.lower() in h["name"].lower()]
    if only == "Untagged only":
        hs = [h for h in hs if not h["tags"]]
    elif only != "All helpers":
        t = only.split("“")[1].rstrip("”")
        hs = [h for h in hs if t in effective(h["tags"])]
    rows = [{"Name": h["name"], "Tags": ", ".join(h["tags"]) or "—",
             "+ implied": ", ".join(t for t in effective(h["tags"]) if t not in h["tags"]) or "—"} for h in hs]
    ev = st.dataframe(rows, on_select="rerun", selection_mode="multi-row", hide_index=True, key="a_table", height=260)
    picked = [hs[i]["id"] for i in ev.selection.rows]
    b1, b2, b3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    tag = b1.selectbox("Tag", list(st.session_state.tags), key="a_bulk_tag")
    msgs: list[str] = []
    if b2.button(f"Add to {len(picked)} selected", disabled=not picked, key="a_add"):
        msgs = bulk_apply(picked, tag, True)
        st.toast(f"Tagged {len(picked) - len(msgs)} helper(s)")
    if b3.button("Remove from selected", disabled=not picked, key="a_rm"):
        msgs = bulk_apply(picked, tag, False)
    if picked and len(picked) == len(hs) and len(hs) < len(st.session_state.helpers):
        st.caption(f"Tip: all {len(hs)} filtered helpers are selected.")
    for m in msgs:
        st.error("Blocked — " + m)


# ================================================================ VARIANT B
@st.dialog("Manage tags", width="large")
def _manage_dialog() -> None:
    left, right = st.columns([2, 3], gap="large")
    with left:
        if st.button("＋ New tag", key="b_new"):
            st.session_state["_sel_b"] = "__new__"
            st.rerun(scope="fragment")
        tag_tree("_sel_b")
    with right:
        sel = st.session_state.get("_sel_b")
        if sel == "__new__":
            tag_form(None, "b_form_new")
        elif sel in st.session_state.tags:
            tag_form(sel, f"b_form_{sel}")
            delete_panel(sel, f"b_del_{sel}")
        else:
            st.info("Pick a tag to edit.")


def variant_b() -> None:
    """B — helper-centric: tags live in the helpers list itself (inline
    multiselect per helper); tag CRUD hides behind a dialog. Grid: stripe+dots,
    with a hard filter (hide non-matching)."""
    st.caption("Variant B · **No new tab.** Tagging happens inline in the helper list; tag CRUD is a dialog. "
               "Roster card = coloured stripe + dots, filter hides others.")
    tab = st.segmented_control("Tab", ["1. Upload (helpers)", "2. Buildings", "3. Roster"], default="1. Upload (helpers)",
                               label_visibility="collapsed", key="b_tab")
    if tab == "3. Roster":
        st.subheader("3. Roster")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        flt = c1.multiselect("Show only helpers tagged", list(st.session_state.tags), key="b_flt")
        c2.caption("Hover a card for its tags")
        mock_grid("stripe", flt, only_matching=True)
        return
    if tab != "1. Upload (helpers)":
        st.info("(unchanged existing tab)")
        return

    st.subheader("1. Upload responses")
    st.caption("(upload widget, ingestion warnings, Tag import banner… as today)")
    top = st.columns([3, 1, 1], vertical_alignment="bottom")
    q = top[0].text_input("Filter helpers", key="b_q", placeholder="name…")
    with top[1]:
        if st.button("🏷 Manage tags"):
            _manage_dialog()
    hs = [h for h in st.session_state.helpers if q.lower() in h["name"].lower()]
    top[2].markdown(f"{len(hs)} shown")

    with st.expander(f"Bulk: apply a tag to all {len(hs)} shown helpers"):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        t = c1.selectbox("Tag", list(st.session_state.tags), key="b_bulk")
        if c2.button("Apply to all shown", key="b_apply"):
            errs = bulk_apply([h["id"] for h in hs], t, True)
            for e in errs:
                st.error("Skipped — " + e)
            if not errs:
                st.rerun()

    hdr = st.columns([2, 4, 3])
    hdr[0].markdown("**Helper**")
    hdr[1].markdown("**Tags (direct)**")
    hdr[2].markdown("**Effective**")
    for h in hs:
        c = st.columns([2, 4, 3], vertical_alignment="center")
        c[0].write(h["name"])
        new = c[1].multiselect("tags", list(st.session_state.tags), h["tags"], key=f"b_h{h['id']}",
                               label_visibility="collapsed", placeholder="add tag…")
        if new != h["tags"]:
            e = assign_error(h, new)
            if e:
                c[1].error("Blocked — " + e)
            else:
                h["tags"] = new
                st.rerun()
        c[2].markdown(chips(h, small=True) or "—", unsafe_allow_html=True)


# ================================================================ VARIANT C
def variant_c() -> None:
    """C — tag-centric board: pick a tag, then move helpers in and out of it
    in a two-list transfer. Grid: whole card in tag colour + clickable legend
    that toggles highlight."""
    st.caption("Variant C · **Tag board.** Choose a tag; see who has it (direct / inherited) and add people from "
               "the rest. Roster has a clickable legend.")
    tab = st.segmented_control("Tab", ["1. Upload", "2. Buildings", "▶ Tag board", "3. Roster"], default="▶ Tag board",
                               label_visibility="collapsed", key="c_tab")
    tags = st.session_state.tags
    if tab == "3. Roster":
        st.subheader("3. Roster")
        hl = st.pills("Legend — click to highlight", list(tags), selection_mode="multi", key="c_hl",
                      format_func=lambda t: f"● {t}")
        mock_grid("chips", hl or [])
        return
    if tab != "▶ Tag board":
        st.info("(unchanged existing tab)")
        return

    st.subheader("Tag board")
    options = [*tags, "＋ new tag"]
    sel = st.pills("Tag", options, selection_mode="single", key="c_pick", label_visibility="collapsed",
                   default=list(tags)[0])
    if sel == "＋ new tag":
        tag_form(None, "c_form_new")
        return
    if sel not in tags:
        return
    d = tags[sel]
    b, r = allowed([sel])
    st.markdown(f"{chip(sel)}  &nbsp; {d['note'] or ''}", unsafe_allow_html=True)
    ancestry = ancestors(sel)
    kids = [t for t in tags if tags[t]["parent"] == sel]
    st.caption(f"Implies: {', '.join(ancestry) or '—'}  ·  Implied by: {', '.join(descendants(sel)) or '—'}  ·  "
               f"Allowed buildings: {', '.join(b) or 'NONE'}  ·  Allowed roles: {', '.join(r) or 'NONE'}")
    with st.expander("Edit tag definition"):
        tag_form(sel, f"c_form_{sel}")
        delete_panel(sel, f"c_del_{sel}")

    hs = st.session_state.helpers
    has = [h for h in hs if sel in effective(h["tags"])]
    rest = [h for h in hs if sel not in effective(h["tags"])]
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown(f"**Has “{sel}” ({len(has)})**")
        for h in has:
            direct = sel in h["tags"]
            via = "" if direct else f" <span style='opacity:.6;font-size:.75rem'>via {', '.join(t for t in h['tags'] if sel in effective([t]))}</span>"
            x, y = st.columns([6, 1], vertical_alignment="center")
            x.markdown(f"{h['name']}{via}", unsafe_allow_html=True)
            if direct and y.button("✕", key=f"c_rm{h['id']}_{sel}", help="Remove tag"):
                h["tags"].remove(sel)
                st.rerun()
    with col2:
        st.markdown(f"**Others ({len(rest)})**")
        q = st.text_input("Find", key="c_q", placeholder="type a name, Enter…", label_visibility="collapsed")
        pick = st.multiselect("Add", [h["name"] for h in rest if q.lower() in h["name"].lower()],
                              key=f"c_add_{sel}", placeholder="select helpers to add…", label_visibility="collapsed")
        if st.button(f"Add {len(pick)} to “{sel}”", disabled=not pick, type="primary", key=f"c_go_{sel}"):
            ids = [h["id"] for h in rest if h["name"] in pick]
            errs = bulk_apply(ids, sel, True)
            for e in errs:
                st.error("Skipped — " + e)
            if not errs:
                st.session_state.pop(f"c_add_{sel}", None)
                st.rerun()
        with st.expander("Untagged helpers"):
            st.write(", ".join(h["name"] for h in hs if not h["tags"]) or "—")


# ================================================================ shell
def main() -> None:
    st.set_page_config(page_title="PROTOTYPE · Tags UI", layout="wide")
    _seed()
    st.warning("PROTOTYPE — ticket #9. In-memory only, fake data, not wired to the real workspace.", icon="🧪")
    variants = {"A": ("A", variant_a), "B": ("B", variant_b), "C": ("C", variant_c)}
    names = {"A": "Dedicated Tags tab", "B": "Inline in helper list + dialog", "C": "Tag board"}
    cur = st.query_params.get("variant", "A")
    if cur not in variants:
        cur = "A"
    with st.sidebar:
        st.markdown("### Variant")
        pick = st.radio("Variant", list(variants), index=list(variants).index(cur),
                        format_func=lambda k: f"{k} — {names[k]}", label_visibility="collapsed")
        if st.button("Reset fake data"):
            for k in list(st.session_state):
                del st.session_state[k]
            st.rerun()
    if pick != cur:
        st.query_params["variant"] = pick
    variants[pick][1]()


main()
