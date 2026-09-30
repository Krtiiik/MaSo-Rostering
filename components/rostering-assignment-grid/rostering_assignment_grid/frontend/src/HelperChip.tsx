import { useDraggable } from "@dnd-kit/core";
import type { MouseEvent } from "react";
import type { Helper, TagPill } from "./types";

// Black or white, whichever reads better on the given "#rrggbb" fill (the same
// rule as rostering.streamlit_app.tag_pills).
function pillTextColour(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#000000" : "#ffffff";
}

export function TagPillView({ pill, implied }: { pill: TagPill; implied: boolean }) {
  const colour = /^#[0-9a-fA-F]{6}$/.test(pill.colour) ? pill.colour : "#888888";
  const style = implied
    ? { borderColor: colour, color: colour }
    : { borderColor: colour, background: colour, color: pillTextColour(colour) };
  return (
    <span className={`tag-pill ${implied ? "tag-pill-implied" : "tag-pill-direct"}`} style={style}>
      {pill.name}
    </span>
  );
}

interface Props {
  helper: Helper;
  // Show the Helper's Tag pills under their name.
  showTags?: boolean;
  // Faded by the Tag filter (still in place, still draggable).
  dimmed?: boolean;
  unsatisfiedFriend?: boolean;
  friendHighlight?: "satisfied" | "unsatisfied" | "requester";
  onHoverChange?: (hovering: boolean) => void;
  // A plain click on the chip, with the cursor position (opens the details card).
  onSelect?: (clientX: number, clientY: number) => void;
  // The Broken-rule lines this chip is part of, if any — marks it lightly.
  broken?: string[];
  // Lock state of a placed Helper's Assignment; `onToggleLock` is given only
  // for a placed chip (ctrl/cmd-click and the details card's button use it).
  locked?: boolean;
  onToggleLock?: () => void;
}

export function HelperChip({
  helper,
  showTags,
  dimmed,
  unsatisfiedFriend,
  friendHighlight,
  onHoverChange,
  onSelect,
  broken,
  locked,
  onToggleLock,
}: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  const titleText =
    [...(broken ?? []), ...(unsatisfiedFriend ? ["Has an unsatisfied friend request"] : [])].join("\n") || undefined;

  const highlightClass = friendHighlight ? ` friend-highlight-${friendHighlight}` : "";

  // ctrl/cmd-click toggles the lock; a plain click opens the details card (the
  // grid owns it, so it survives the chip moving). A drag never reaches here:
  // the grid's activation distance keeps it apart from a click, and dnd-kit
  // swallows the click that would follow a drag.
  function handleClick(event: MouseEvent<HTMLDivElement>) {
    if (onToggleLock && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      onToggleLock();
      return;
    }
    if (isDragging) return;
    onSelect?.(event.clientX, event.clientY);
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`helper-chip${isDragging ? " dragging" : ""}${unsatisfiedFriend ? " unsatisfied" : ""}${broken?.length ? " broken" : ""}${locked ? " locked" : ""}${dimmed ? " dimmed" : ""}${highlightClass}`}
      title={titleText}
      onClick={handleClick}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
    >
      {locked && (
        <span className="helper-chip-lock" title="Locked: a full Solve keeps this Assignment">
          🔒{" "}
        </span>
      )}
      {helper.answers_changed && helper.answers_changed.length > 0 && (
        <span
          className="helper-chip-answers-changed"
          title={`Answers changed since placed: ${helper.answers_changed.join(", ")}`}
        >
          ✎{" "}
        </span>
      )}
      {helper.forced_groups && helper.forced_groups.length > 0 && (
        <span
          className="helper-chip-forced"
          title={`Forced friends: ${helper.forced_groups.join("; ")}`}
        >
          🔗{" "}
        </span>
      )}
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
      {showTags && helper.tags && (helper.tags.direct.length > 0 || helper.tags.implied.length > 0) && (
        <div className="helper-chip-tags">
          {helper.tags.direct.map((pill) => (
            <TagPillView key={`d:${pill.name}`} pill={pill} implied={false} />
          ))}
          {helper.tags.implied.map((pill) => (
            <TagPillView key={`i:${pill.name}`} pill={pill} implied={true} />
          ))}
        </div>
      )}
    </div>
  );
}
