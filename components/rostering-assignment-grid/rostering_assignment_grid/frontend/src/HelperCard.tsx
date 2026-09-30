import type { HelperCardData } from "./types";

interface Props {
  data: HelperCardData;
  top: number;
  left: number;
  // Present only for a placed Helper (the Unassigned pool has no lock).
  locked?: boolean;
  onToggleLock?: () => void;
}

const CARD_WIDTH = 260;
// The card's real height varies with content (role/friend list length); this
// is just an estimate used to decide whether to flip above/left of the
// cursor so the card doesn't render off-screen.
const CARD_HEIGHT_ESTIMATE = 260;
const CURSOR_OFFSET = 14;
const VIEWPORT_MARGIN = 8;

// Anchors one corner of the card to the click position, flipping to the
// opposite side on either axis if the card would otherwise overflow the
// viewport.
export function computeCardPosition(clientX: number, clientY: number): { top: number; left: number } {
  let left = clientX + CURSOR_OFFSET;
  if (left + CARD_WIDTH + VIEWPORT_MARGIN > window.innerWidth) {
    left = clientX - CURSOR_OFFSET - CARD_WIDTH;
  }
  left = Math.max(VIEWPORT_MARGIN, left);

  let top = clientY + CURSOR_OFFSET;
  if (top + CARD_HEIGHT_ESTIMATE + VIEWPORT_MARGIN > window.innerHeight) {
    top = clientY - CURSOR_OFFSET - CARD_HEIGHT_ESTIMATE;
  }
  top = Math.max(VIEWPORT_MARGIN, top);

  return { top, left };
}

const STAR_FILLED = "★";
const STAR_EMPTY = "☆";

function stars(level: number): string {
  return STAR_FILLED.repeat(level) + STAR_EMPTY.repeat(Math.max(0, 5 - level));
}

/**
 * Floating details card, opened by clicking a chip, showing a helper's preferences: preferred building(s),
 * per-role star ratings, and friend requests color-coded to match the grid's
 * existing highlighting (green = co-located, red = not, purple = someone
 * else requested this helper). Positioned with `position: fixed` (computed
 * by computeCardPosition from the click) so it escapes the grid's
 * scroll-container clipping regardless of where the chip sits in the table.
 */
export function HelperCard({ data, top, left, locked, onToggleLock }: Props) {
  const { helper, roleOrder, roleLabels, sharedFriends, differentFriends, requestedBy } = data;
  const hasFriendInfo = sharedFriends.length > 0 || differentFriends.length > 0 || requestedBy.length > 0;

  return (
    <div className="helper-card" style={{ top, left }}>
      <div className="helper-card-name">{helper.name}</div>

      {onToggleLock && (
        <button
          type="button"
          className="helper-card-lock"
          title="Celé sestavení rozdělení uzamčené přiřazení zachová (přepíná se i ctrl/cmd-kliknutím na štítek pomocníka)"
          onClick={(e) => {
            e.stopPropagation();
            onToggleLock();
          }}
        >
          {locked ? "Odemknout" : "Zamknout"}
        </button>
      )}

      <div className="helper-card-section">
        <div className="helper-card-label">Preferované budovy</div>
        <div>
          {helper.building_preferences.length > 0 ? helper.building_preferences.join(", ") : "Žádná preference"}
        </div>
      </div>

      <div className="helper-card-section">
        <div className="helper-card-label">Preference rolí</div>
        <ul className="helper-card-roles">
          {roleOrder.map((role) => {
            const pref = helper.role_preferences[role];
            return (
              <li key={role}>
                <span className="helper-card-role-name">{roleLabels[role] ?? role}</span>
                {pref ? (
                  <span className="helper-card-stars" title={pref.label}>
                    {stars(pref.level)}
                  </span>
                ) : (
                  <span className="helper-card-stars helper-card-stars-empty">nehodnoceno</span>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {hasFriendInfo && (
        <div className="helper-card-section">
          <div className="helper-card-label">Přání být s kamarádem</div>
          <ul className="helper-card-friends">
            {sharedFriends.map((f) => (
              <li key={`shared-${f.id}`} className="friend-shared">
                {f.name}
              </li>
            ))}
            {differentFriends.map((f) => (
              <li key={`diff-${f.id}`} className="friend-different">
                {f.name}
              </li>
            ))}
            {requestedBy.map((f) => (
              <li key={`req-${f.id}`} className="friend-requested-by">
                {f.name} (chce být s ním/ní)
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
