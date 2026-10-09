// The roster grid's behaviour in the browser. Python renders the grid's HTML
// (rostering/webapp/ui/grid/render.py); this component shows it and turns what
// the user does on it into events for Python, by delegation on its root, so a
// fresh render needs no re-wiring. It decides nothing the HTML does not already
// say: chips and cells carry the data (kind, ids, placement, accepted drops).
//
// Events: helper_drop {helper_id, building, room, role}; organizer_drop
// {organizer_id, key, building, room, source}; manual_set {key, building, room,
// names} (a duplicate drop or a chip's ×; names are never typed); cell_merge
// {key, building, pairs, merged}; row_merge {key, building, room, merged} (a tall
// cell: the cell's row merged with the one under it, or split again); lock
// {helper_id, locked}; card {helper_id | organizer_id, x, y, width, height};
// card_close.

const DRAG_MIME = "application/x-rostering-chip";

// Auto-scroll while a chip is dragged: within EDGE px of the edge of a
// scrollable area the area scrolls, faster the closer the pointer is to it.
const SCROLL_EDGE = 70;
const SCROLL_MAX_SPEED = 24;

function closest(target, selector) {
  return target instanceof Element ? target.closest(selector) : null;
}

// The nearest ancestor of ``el`` that scrolls vertically, else the page itself.
function verticalScroller(el) {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const overflowY = getComputedStyle(node).overflowY;
    if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight) return node;
  }
  return document.scrollingElement || document.documentElement;
}

// How far (px per frame, signed) to scroll for a pointer at ``pos`` in the
// span [lo, hi]: 0 away from the edges.
function edgeSpeed(pos, lo, hi) {
  const toLo = pos - lo;
  const toHi = hi - pos;
  if (toLo < SCROLL_EDGE) return -SCROLL_MAX_SPEED * Math.min(1, (SCROLL_EDGE - toLo) / SCROLL_EDGE);
  if (toHi < SCROLL_EDGE) return SCROLL_MAX_SPEED * Math.min(1, (SCROLL_EDGE - toHi) / SCROLL_EDGE);
  return 0;
}

function jsonAttr(el, name, fallback) {
  const raw = el.getAttribute(name);
  if (raw === null || raw === "") return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export default {
  template: `<div class="roster-grid-root"><div v-html="html"></div></div>`,
  props: {
    html: String,
    friendsOn: Boolean,
  },
  data() {
    return { drag: null };
  },
  mounted() {
    const root = this.$el;
    this.listeners = {
      dragstart: (e) => this.onDragStart(e),
      dragover: (e) => this.onDragOver(e),
      dragleave: (e) => this.onDragLeave(e),
      drop: (e) => this.onDrop(e),
      dragend: () => this.onDragEnd(),
      click: (e) => this.onClick(e),
      mouseover: (e) => this.onMouseOver(e),
      mouseout: (e) => this.onMouseOut(e),
    };
    for (const [name, handler] of Object.entries(this.listeners)) root.addEventListener(name, handler);
    // The details card closes on a press anywhere but on it or on a chip (a
    // chip's own click switches it), and on Escape.
    this.onDocPointerDown = (e) => {
      if (!document.querySelector(".helper-card")) return;
      if (closest(e.target, ".helper-card") || closest(e.target, ".helper-chip, .organizer-chip")) return;
      this.$emit("card_close");
    };
    this.onDocKeyDown = (e) => {
      if (e.key === "Escape" && document.querySelector(".helper-card")) this.$emit("card_close");
    };
    document.addEventListener("pointerdown", this.onDocPointerDown);
    document.addEventListener("keydown", this.onDocKeyDown);
    // The sticky toolbar sits right under the fixed page header, and the sticky
    // Organizers pool right under the toolbar; both heights change when their
    // contents wrap.
    const toolbar = document.querySelector(".roster-toolbar");
    const header = document.querySelector(".q-header");
    if (typeof ResizeObserver !== "undefined" && (toolbar || header)) {
      const place = () => {
        const headerHeight = header ? header.offsetHeight : 0;
        document.documentElement.style.setProperty("--roster-header-height", `${headerHeight}px`);
        const top = toolbar ? parseFloat(getComputedStyle(toolbar).top) || 0 : headerHeight;
        root.style.setProperty("--roster-toolbar-bottom", `${top + (toolbar ? toolbar.offsetHeight : 0)}px`);
      };
      this.toolbarObserver = new ResizeObserver(place);
      if (toolbar) this.toolbarObserver.observe(toolbar);
      if (header) this.toolbarObserver.observe(header);
      place();
    }
  },
  unmounted() {
    if (this.toolbarObserver) this.toolbarObserver.disconnect();
    for (const [name, handler] of Object.entries(this.listeners)) this.$el.removeEventListener(name, handler);
    document.removeEventListener("pointerdown", this.onDocPointerDown);
    document.removeEventListener("keydown", this.onDocKeyDown);
  },
  methods: {
    // ------------------------------------------------------------ drag-and-drop
    chipInfo(chip) {
      if (chip.dataset.kind === "organizer") {
        return {
          kind: "organizer",
          organizerId: Number(chip.dataset.oid),
          source: jsonAttr(chip, "data-source", null),
        };
      }
      return {
        kind: "helper",
        helperId: Number(chip.dataset.hid),
        name: chip.dataset.name,
        building: chip.dataset.building ?? null,
        room: chip.dataset.room ?? null,
      };
    },
    // Whether ``cell`` takes the chip in flight: an Organizer only a leadership
    // slot; a Helper a solver Role cell, or an Additional role cell of the Room
    // (or, Building-scoped, the Building) they are placed in.
    accepts(cell, info) {
      const drop = cell.dataset.drop;
      if (info.kind === "organizer") return drop === "org";
      if (drop === "role") return true;
      if (drop !== "dup" || info.building === null) return false;
      if (cell.dataset.building !== info.building) return false;
      const rooms = jsonAttr(cell, "data-rooms", null);
      return rooms === null || rooms.includes(info.room);
    },
    onDragStart(e) {
      const chip = closest(e.target, "[data-kind]");
      if (!chip) return;
      this.drag = this.chipInfo(chip);
      this.startAutoScroll(e);
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData(DRAG_MIME, "1");
      chip.classList.add("dragging");
      this.dragChip = chip;
      // Cells refusing this chip fade while it is in flight.
      for (const cell of this.$el.querySelectorAll("td[data-drop]")) {
        if (!this.accepts(cell, this.drag)) cell.classList.add("drop-disabled");
      }
      if (document.querySelector(".helper-card")) this.$emit("card_close");
    },
    targetCell(e) {
      const cell = closest(e.target, "td[data-drop]");
      return cell && this.drag && this.accepts(cell, this.drag) ? cell : null;
    },
    onDragOver(e) {
      const cell = this.targetCell(e);
      if (!cell) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (this.overCell !== cell) {
        this.overCell?.classList.remove("drop-over");
        cell.classList.add("drop-over");
        this.overCell = cell;
      }
    },
    onDragLeave(e) {
      const cell = closest(e.target, "td[data-drop]");
      if (cell && !cell.contains(e.relatedTarget)) {
        cell.classList.remove("drop-over");
        if (this.overCell === cell) this.overCell = null;
      }
    },
    onDrop(e) {
      const cell = this.targetCell(e);
      const info = this.drag;
      this.onDragEnd();
      if (!cell || !info) return;
      e.preventDefault();
      const d = cell.dataset;
      if (info.kind === "organizer") {
        this.$emit("organizer_drop", {
          organizer_id: info.organizerId,
          key: d.key,
          building: d.building,
          room: d.room ?? null,
          source: info.source,
        });
        return;
      }
      if (d.drop === "role") {
        this.$emit("helper_drop", { helper_id: info.helperId, building: d.building, room: d.room, role: d.role });
        return;
      }
      // An Additional role: the Helper is added to the cell's names (stored under
      // the group's first Room), their Assignment stays where it is.
      const names = jsonAttr(cell, "data-names", []);
      if (names.includes(info.name)) return;
      this.$emit("manual_set", { key: d.key, building: d.building, room: d.room ?? null, names: [...names, info.name] });
    },
    // Scrolls the grid's own horizontal scroller and its vertical one while the
    // pointer is near their edges. The pointer is tracked on the document, so the
    // margins around the grid count too (a drag fires no pointer events).
    startAutoScroll(e) {
      this.stopAutoScroll();
      this.pointer = { x: e.clientX, y: e.clientY };
      this.onDocDragOver = (ev) => {
        this.pointer = { x: ev.clientX, y: ev.clientY };
      };
      document.addEventListener("dragover", this.onDocDragOver, true);
      const tick = () => {
        this.scrollFrame = requestAnimationFrame(tick);
        const { x, y } = this.pointer;
        const wide = this.$el.querySelector(".table-scroll");
        if (wide) {
          const r = wide.getBoundingClientRect();
          if (y >= r.top && y <= r.bottom) wide.scrollLeft += edgeSpeed(x, r.left, r.right);
        }
        const tall = verticalScroller(this.$el);
        const page = tall === document.scrollingElement || tall === document.documentElement;
        const top = page ? 0 : tall.getBoundingClientRect().top;
        const bottom = page ? window.innerHeight : tall.getBoundingClientRect().bottom;
        tall.scrollTop += edgeSpeed(y, top, bottom);
      };
      this.scrollFrame = requestAnimationFrame(tick);
    },
    stopAutoScroll() {
      if (this.scrollFrame) cancelAnimationFrame(this.scrollFrame);
      this.scrollFrame = null;
      if (this.onDocDragOver) document.removeEventListener("dragover", this.onDocDragOver, true);
      this.onDocDragOver = null;
    },
    onDragEnd() {
      this.stopAutoScroll();
      this.dragChip?.classList.remove("dragging");
      for (const cell of this.$el.querySelectorAll(".drop-disabled, .drop-over")) {
        cell.classList.remove("drop-disabled", "drop-over");
      }
      this.drag = null;
      this.dragChip = null;
      this.overCell = null;
    },
    // ------------------------------------------------------------ clicks
    onClick(e) {
      const rowMerge = closest(e.target, "[data-row-merge]");
      if (rowMerge) {
        e.stopPropagation();
        this.$emit("row_merge", {
          key: rowMerge.dataset.key,
          building: rowMerge.dataset.building,
          room: rowMerge.dataset.room,
          merged: rowMerge.dataset.rowMerge === "1",
        });
        return;
      }
      const merge = closest(e.target, "[data-merge]");
      if (merge) {
        e.stopPropagation();
        this.$emit("cell_merge", {
          key: merge.dataset.key,
          building: merge.dataset.building,
          pairs: jsonAttr(merge, "data-merge", []),
          merged: merge.dataset.merged === "1",
        });
        return;
      }
      const remove = closest(e.target, "[data-remove]");
      if (remove) {
        const cell = closest(remove, "td[data-names]");
        if (!cell) return;
        const names = jsonAttr(cell, "data-names", []).filter((n) => n !== remove.dataset.remove);
        this.$emit("manual_set", { key: cell.dataset.key, building: cell.dataset.building, room: cell.dataset.room ?? null, names });
        return;
      }
      const organizer = closest(e.target, ".organizer-chip");
      if (organizer) {
        this.$emit("card", {
          organizer_id: Number(organizer.dataset.oid),
          x: e.clientX,
          y: e.clientY,
          width: window.innerWidth,
          height: window.innerHeight,
        });
        return;
      }
      const chip = closest(e.target, ".helper-chip");
      if (chip) {
        const helperId = Number(chip.dataset.hid);
        // ctrl/cmd-click toggles the lock of a placed Helper; a plain click opens
        // (or, on the same chip, closes) the details card.
        if ((e.ctrlKey || e.metaKey) && chip.dataset.building !== undefined) {
          e.preventDefault();
          this.$emit("lock", { helper_id: helperId, locked: chip.dataset.locked !== "1" });
          return;
        }
        this.$emit("card", {
          helper_id: helperId,
          x: e.clientX,
          y: e.clientY,
          width: window.innerWidth,
          height: window.innerHeight,
        });
        return;
      }
    },
    // ------------------------------------------------------------ friend hover
    // With the Friends overlay on, hovering a Helper outlines the friends they
    // named (green: same Room, red: not; an Organizer they named is outlined the
    // same way) and, in purple, those who named them. Hovering an Organizer
    // outlines, in purple, the Helpers who named them.
    onMouseOver(e) {
      if (!this.friendsOn) return;
      const chip = closest(e.target, ".helper-chip, .organizer-chip");
      if (!chip || chip === this.hovered) return;
      this.clearHighlights();
      this.hovered = chip;
      const mark = (selector, cls) => {
        for (const other of this.$el.querySelectorAll(selector)) other.classList.add(cls);
      };
      const status = (ok) => (ok === "1" ? "friend-highlight-satisfied" : "friend-highlight-unsatisfied");
      const marked = new Set();
      for (const part of (chip.dataset.friends ?? "").split(",").filter(Boolean)) {
        const [id, ok] = part.split(":");
        marked.add(id);
        mark(`.helper-chip[data-hid="${id}"]`, status(ok));
      }
      for (const part of (chip.dataset.organizerFriends ?? "").split(",").filter(Boolean)) {
        const [id, ok] = part.split(":");
        mark(`.organizer-chip[data-oid="${id}"]`, status(ok));
      }
      for (const id of (chip.dataset.requesters ?? "").split(",").filter(Boolean)) {
        if (!marked.has(id)) mark(`.helper-chip[data-hid="${id}"]`, "friend-highlight-requester");
      }
    },
    onMouseOut(e) {
      const chip = closest(e.target, ".helper-chip, .organizer-chip");
      if (chip && chip === this.hovered && !chip.contains(e.relatedTarget)) {
        this.clearHighlights();
        this.hovered = null;
      }
    },
    clearHighlights() {
      for (const el of this.$el.querySelectorAll('[class*="friend-highlight-"]')) {
        el.classList.remove("friend-highlight-satisfied", "friend-highlight-unsatisfied", "friend-highlight-requester");
      }
    },
  },
};
