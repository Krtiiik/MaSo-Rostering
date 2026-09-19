import { useDraggable } from "@dnd-kit/core";
import type { Helper } from "../types";

interface Props {
  helper: Helper;
  unsatisfiedFriend?: boolean;
}

export function HelperChip({ helper, unsatisfiedFriend }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`helper-chip${isDragging ? " dragging" : ""}${unsatisfiedFriend ? " unsatisfied" : ""}`}
      title={unsatisfiedFriend ? "Has an unsatisfied friend request" : undefined}
    >
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
    </div>
  );
}
