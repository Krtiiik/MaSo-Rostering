import { useDraggable } from "@dnd-kit/core";
import type { Helper } from "./types";

interface Props {
  helper: Helper;
  unsatisfiedFriend?: boolean;
  satisfiedFriend?: boolean;
  friendHighlighted?: boolean;
  onHoverChange?: (hovering: boolean) => void;
}

export function HelperChip({ helper, unsatisfiedFriend, satisfiedFriend, friendHighlighted, onHoverChange }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  // A helper can have both satisfied and unsatisfied friend requests at
  // once (e.g. two different friends, only one co-located) — the
  // unsatisfied one wins the border color since it's the one needing
  // attention.
  const friendClass = unsatisfiedFriend ? " unsatisfied" : satisfiedFriend ? " satisfied" : "";
  const title = unsatisfiedFriend
    ? "Has an unsatisfied friend request"
    : satisfiedFriend
      ? "Friend request satisfied"
      : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`helper-chip${isDragging ? " dragging" : ""}${friendClass}${friendHighlighted ? " friend-highlight" : ""}`}
      title={title}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
    >
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
    </div>
  );
}
