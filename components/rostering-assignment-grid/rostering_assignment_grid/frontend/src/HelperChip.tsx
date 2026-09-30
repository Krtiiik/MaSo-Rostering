import { useDraggable } from "@dnd-kit/core";
import type { MouseEvent } from "react";
import type { Helper } from "./types";
import { tagStripeStyle, tagTitle } from "./tagStripes";

interface Props {
  helper: Helper;
  // The Tags overlay is on: stripe the chip in the Helper's direct Tag colours.
  showTags?: boolean;
  // Faded by the Tag filter (still in place, still draggable).
  dimmed?: boolean;
  // The satisfaction overlays: whether the placed Role / Building suits the
  // Helper's answers (undefined = overlay off or nothing to judge, no border).
  roleFit?: boolean;
  buildingFit?: boolean;
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
  roleFit,
  buildingFit,
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
    data: { kind: "helper" },
  });

  const titleText =
    [
      ...(broken ?? []),
      ...(unsatisfiedFriend ? ["Má nesplněné přání být s kamarádem"] : []),
      ...(roleFit === undefined ? [] : [roleFit ? "Spokojen/a s rolí" : "Nespokojen/a s rolí"]),
      ...(buildingFit === undefined ? [] : [buildingFit ? "Spokojen/a s budovou" : "Nespokojen/a s budovou"]),
      ...(showTags ? [tagTitle(helper.tags) ?? ""] : []),
    ]
      .filter(Boolean)
      .join("\n") || undefined;
  const stripes = showTags ? tagStripeStyle(helper.tags) : undefined;

  const style = {
    ...stripes,
    ...(transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 } : undefined),
  };

  const highlightClass = friendHighlight ? ` friend-highlight-${friendHighlight}` : "";
  const fitClass =
    (roleFit === undefined ? "" : roleFit ? " role-fit-ok" : " role-fit-bad") +
    (buildingFit === undefined ? "" : buildingFit ? " building-fit-ok" : " building-fit-bad");

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
      className={`helper-chip${isDragging ? " dragging" : ""}${unsatisfiedFriend ? " unsatisfied" : ""}${broken?.length ? " broken" : ""}${locked ? " locked" : ""}${dimmed ? " dimmed" : ""}${stripes ? " tag-striped" : ""}${fitClass}${highlightClass}`}
      title={titleText}
      onClick={handleClick}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
    >
      {locked && (
        <span className="helper-chip-lock" title="Uzamčeno: celé sestavení rozdělení toto přiřazení zachová">
          🔒{" "}
        </span>
      )}
      {helper.answers_changed && helper.answers_changed.length > 0 && (
        <span
          className="helper-chip-answers-changed"
          title={`Odpovědi se změnily od zařazení: ${helper.answers_changed.join(", ")}`}
        >
          ✎{" "}
        </span>
      )}
      {helper.forced_groups && helper.forced_groups.length > 0 && (
        <span
          className="helper-chip-forced"
          title={`Vynucené skupinky kamarádů: ${helper.forced_groups.join("; ")}`}
        >
          🔗{" "}
        </span>
      )}
      {helper.name}
      {helper.can_bring_notebook && <span title="Může přinést notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Může přinést fotoaparát"> 📷</span>}
    </div>
  );
}
