import type { HelperCardData } from "./types";

interface Props {
  data: HelperCardData;
  top: number;
  left: number;
}

const STAR_FILLED = "★";
const STAR_EMPTY = "☆";

function stars(level: number): string {
  return STAR_FILLED.repeat(level) + STAR_EMPTY.repeat(Math.max(0, 5 - level));
}

/**
 * Floating hover card showing a helper's preferences: preferred building(s),
 * per-role star ratings, and friend requests color-coded to match the grid's
 * existing highlighting (green = co-located, red = not, purple = someone
 * else requested this helper). Positioned with `position: fixed` (computed
 * by HelperChip from the chip's bounding rect) so it escapes the grid's
 * scroll-container clipping regardless of where the chip sits in the table.
 */
export function HelperCard({ data, top, left }: Props) {
  const { helper, roleOrder, roleLabels, sharedFriends, differentFriends, requestedBy } = data;
  const hasFriendInfo = sharedFriends.length > 0 || differentFriends.length > 0 || requestedBy.length > 0;

  return (
    <div className="helper-card" style={{ top, left }}>
      <div className="helper-card-name">{helper.name}</div>

      <div className="helper-card-section">
        <div className="helper-card-label">Preferred building</div>
        <div>
          {helper.building_preferences.length > 0 ? helper.building_preferences.join(", ") : "No preference"}
        </div>
      </div>

      <div className="helper-card-section">
        <div className="helper-card-label">Role preferences</div>
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
                  <span className="helper-card-stars helper-card-stars-empty">not rated</span>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {hasFriendInfo && (
        <div className="helper-card-section">
          <div className="helper-card-label">Friend requests</div>
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
                {f.name} (requested them)
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
