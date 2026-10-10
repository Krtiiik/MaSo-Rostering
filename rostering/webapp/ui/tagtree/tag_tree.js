// The Tags tab's tree in the browser. Python sends the rows (rostering/webapp/ui/
// tagtree/__init__.py: id, parent_id, depth, name, style, counts, note,
// has_children, focus) in tree order; this component draws them indented, keeps
// which branches are collapsed, filters by the search text, and turns clicks and
// drags into events. It decides nothing about a move except which rows to offer
// as a drop target (never the Tag itself or one of its descendants, nor the
// parent it already has); Python validates the move for real.
//
// Events: tag_select {id}; tag_move {id, parent_id} (parent_id null = make it a
// root); tag_toggle {id, collapsed}.

const EXPAND_AFTER_MS = 700; // hovering a collapsed branch with a Tag opens it

function normalize(text) {
  return String(text ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

export default {
  template: `
    <div class="tag-tree" :class="{ 'drop-root': overRoot }"
         @dragover="onRootDragOver" @dragleave="onRootDragLeave" @drop="onRootDrop">
      <div class="tag-tree-row tag-tree-head">
        <span>Štítek</span><span class="c">Pomocníci</span><span class="c">Organizátoři</span><span>Poznámka</span>
      </div>
      <div v-for="r in visible" :key="r.id" class="tag-tree-row" :data-id="r.id" draggable="true"
           :class="{ selected: r.id === selected, dragging: r.id === dragId, 'drop-into': r.id === overId }"
           @click="$emit('tag_select', { id: r.id })"
           @dragstart="onDragStart($event, r)" @dragend="onDragEnd"
           @dragover="onRowDragOver($event, r)" @dragleave="onRowDragLeave($event, r)" @drop="onRowDrop($event, r)">
        <span class="tag-tree-name" :style="{ paddingLeft: indent(r) + 'rem' }">
          <span class="tag-tree-chevron" @click.stop="toggle(r)">
            <q-icon v-if="r.has_children" :name="isCollapsed(r) ? 'chevron_right' : 'expand_more'" size="sm" />
          </span>
          <q-icon v-if="r.focus" name="play_arrow" color="primary" class="q-mr-xs" />
          <span :style="r.style">{{ r.name }}</span>
        </span>
        <span class="c">{{ r.helpers }}</span>
        <span class="c">{{ r.organizers }}</span>
        <span class="note" :title="r.note">{{ r.note }}</span>
      </div>
      <div v-if="!visible.length" class="tag-tree-empty">{{ rows.length ? 'Nic nenalezeno.' : 'Zatím žádné štítky.' }}</div>
    </div>`,
  props: {
    rows: Array,
    selected: { default: null },
    collapsed: { type: Array, default: () => [] },
    query: { type: String, default: "" },
  },
  data() {
    return { closed: new Set(this.collapsed), dragId: null, overId: null, overRoot: false };
  },
  computed: {
    byId() {
      return new Map(this.rows.map((r) => [r.id, r]));
    },
    // The rows to show: while searching, the matches and the branches above them;
    // otherwise everything not under a collapsed branch.
    visible() {
      const q = normalize(this.query.trim());
      if (q) {
        const keep = new Set();
        for (const r of this.rows) {
          if (!normalize(r.name + " " + r.note).includes(q)) continue;
          for (let n = r; n && !keep.has(n.id); n = this.byId.get(n.parent_id)) keep.add(n.id);
        }
        return this.rows.filter((r) => keep.has(r.id));
      }
      return this.rows.filter((r) => {
        for (let p = this.byId.get(r.parent_id); p; p = this.byId.get(p.parent_id)) {
          if (this.closed.has(p.id)) return false;
        }
        return true;
      });
    },
  },
  unmounted() {
    clearTimeout(this.expandTimer);
  },
  methods: {
    indent(r) {
      return r.depth * 1.25;
    },
    isCollapsed(r) {
      return this.closed.has(r.id) && !this.query.trim();
    },
    toggle(r) {
      if (this.query.trim()) return;
      const collapsed = !this.closed.has(r.id);
      const next = new Set(this.closed);
      collapsed ? next.add(r.id) : next.delete(r.id);
      this.closed = next;
      this.$emit("tag_toggle", { id: r.id, collapsed });
    },
    // ------------------------------------------------------------ drag-and-drop
    isDescendant(id, ofId) {
      for (let p = this.byId.get(id); p; p = this.byId.get(p.parent_id)) {
        if (p.parent_id === ofId) return true;
      }
      return false;
    },
    // Whether the Tag in flight may be dropped on ``target`` (a row, or null for
    // the empty space = make it a root).
    canDrop(target) {
      const dragged = this.byId.get(this.dragId);
      if (!dragged) return false;
      if (target === null) return dragged.parent_id !== null;
      return target.id !== dragged.id && target.id !== dragged.parent_id && !this.isDescendant(target.id, dragged.id);
    },
    onDragStart(e, r) {
      this.dragId = r.id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("application/x-rostering-tag", String(r.id));
    },
    onDragEnd() {
      this.dragId = null;
      this.overId = null;
      this.overRoot = false;
      clearTimeout(this.expandTimer);
    },
    setOver(id, root) {
      if (this.overId !== id) {
        clearTimeout(this.expandTimer);
        this.overId = id;
        const row = this.byId.get(id);
        if (row && row.has_children && this.closed.has(id)) {
          this.expandTimer = setTimeout(() => this.toggle(row), EXPAND_AFTER_MS);
        }
      }
      this.overRoot = root;
    },
    onRowDragOver(e, r) {
      if (this.dragId === null) return;
      e.stopPropagation();
      if (!this.canDrop(r)) {
        this.setOver(null, false);
        return;
      }
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      this.setOver(r.id, false);
    },
    onRowDragLeave(e, r) {
      if (!e.currentTarget.contains(e.relatedTarget) && this.overId === r.id) this.setOver(null, false);
    },
    onRowDrop(e, r) {
      if (this.dragId === null) return;
      e.stopPropagation();
      const allowed = this.canDrop(r);
      const id = this.dragId;
      this.onDragEnd();
      if (!allowed) return;
      e.preventDefault();
      this.$emit("tag_move", { id, parent_id: r.id });
    },
    // The space around the rows (the root's own area) takes a Tag as a root.
    onRootDragOver(e) {
      if (this.dragId === null || !this.canDrop(null)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      this.setOver(null, true);
    },
    onRootDragLeave(e) {
      if (!e.currentTarget.contains(e.relatedTarget)) this.overRoot = false;
    },
    onRootDrop(e) {
      if (this.dragId === null) return;
      const allowed = this.canDrop(null);
      const id = this.dragId;
      this.onDragEnd();
      if (!allowed) return;
      e.preventDefault();
      this.$emit("tag_move", { id, parent_id: null });
    },
  },
};
