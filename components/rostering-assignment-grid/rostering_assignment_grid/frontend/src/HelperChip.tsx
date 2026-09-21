import { useDraggable } from "@dnd-kit/core";
import type { Helper } from "./types";

interface Props {
  helper: Helper;
  unsatisfiedFriend?: boolean;
  friendHighlight?: "satisfied" | "unsatisfied" | "requester";
  onHoverChange?: (hovering: boolean) => void;
}

export function HelperChip({ helper, unsatisfiedFriend, friendHighlight, onHoverChange }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  const highlightClass = friendHighlight ? ` friend-highlight-${friendHighlight}` : "";

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`helper-chip${isDragging ? " dragging" : ""}${unsatisfiedFriend ? " unsatisfied" : ""}${highlightClass}`}
      title={unsatisfiedFriend ? "Has an unsatisfied friend request" : undefined}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
    >
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
    </div>
  );
}
