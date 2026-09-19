import { useState } from "react";
import { api } from "../api";
import { ROLES, ROLE_LABELS } from "../types";
import type { BuildingConfig, Role, RoleCapacity, RoomConfig, SolverConfigT, WorkspaceState } from "../types";

interface Props {
  state: WorkspaceState;
  onStateChange: (state: WorkspaceState) => void;
  onSolved: () => void;
}

const EMPTY_CAPACITY: RoleCapacity = { minimum: 0, maximum: null };

function capacityOf(caps: Partial<Record<Role, RoleCapacity>>, role: Role): RoleCapacity {
  return caps[role] ?? EMPTY_CAPACITY;
}

function CapacityTable({
  capacities,
  onChange,
}: {
  capacities: Partial<Record<Role, RoleCapacity>>;
  onChange: (role: Role, cap: RoleCapacity) => void;
}) {
  return (
    <table className="capacity-table">
      <thead>
        <tr>
          <th>Role</th>
          <th>Min</th>
          <th>Max</th>
        </tr>
      </thead>
      <tbody>
        {ROLES.map((role) => {
          const cap = capacityOf(capacities, role);
          return (
            <tr key={role}>
              <td>{ROLE_LABELS[role]}</td>
              <td>
                <input
                  type="number"
                  min={0}
                  value={cap.minimum}
                  onChange={(e) => onChange(role, { ...cap, minimum: Number(e.target.value) })}
                />
              </td>
              <td>
                <input
                  type="number"
                  min={0}
                  placeholder="∞"
                  value={cap.maximum ?? ""}
                  onChange={(e) =>
                    onChange(role, {
                      ...cap,
                      maximum: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ConfigPage({ state, onStateChange, onSolved }: Props) {
  const [buildings, setBuildings] = useState<BuildingConfig[]>(state.config);
  const [solverConfig, setSolverConfig] = useState<SolverConfigT>(state.solver_config);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addBuilding() {
    const name = prompt("Building name?");
    if (!name) return;
    setBuildings([...buildings, { name, rooms: [], capacities: {} }]);
  }

  function removeBuilding(index: number) {
    setBuildings(buildings.filter((_, i) => i !== index));
  }

  function addRoom(buildingIndex: number) {
    const name = prompt("Room name?");
    if (!name) return;
    const next = [...buildings];
    next[buildingIndex] = {
      ...next[buildingIndex],
      rooms: [...next[buildingIndex].rooms, { name, capacities: {} } as RoomConfig],
    };
    setBuildings(next);
  }

  function removeRoom(buildingIndex: number, roomIndex: number) {
    const next = [...buildings];
    next[buildingIndex] = {
      ...next[buildingIndex],
      rooms: next[buildingIndex].rooms.filter((_, i) => i !== roomIndex),
    };
    setBuildings(next);
  }

  function updateBuildingCapacity(buildingIndex: number, role: Role, cap: RoleCapacity) {
    const next = [...buildings];
    next[buildingIndex] = {
      ...next[buildingIndex],
      capacities: { ...next[buildingIndex].capacities, [role]: cap },
    };
    setBuildings(next);
  }

  function updateRoomCapacity(buildingIndex: number, roomIndex: number, role: Role, cap: RoleCapacity) {
    const next = [...buildings];
    const rooms = [...next[buildingIndex].rooms];
    rooms[roomIndex] = { ...rooms[roomIndex], capacities: { ...rooms[roomIndex].capacities, [role]: cap } };
    next[buildingIndex] = { ...next[buildingIndex], rooms };
    setBuildings(next);
  }

  async function saveConfig() {
    setBusy(true);
    setError(null);
    try {
      const next = await api.putConfig(buildings);
      onStateChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveAndSolve() {
    setBusy(true);
    setError(null);
    try {
      await api.putConfig(buildings);
      await api.putSolverConfig(solverConfig);
      const solved = await api.solve();
      onStateChange(solved);
      onSolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>2. Buildings &amp; rooms</h2>
      <p>Define the buildings, their rooms, and how many of each role each can hold this season.</p>

      {buildings.map((building, bi) => (
        <div className="card" key={bi}>
          <div className="card-header">
            <input
              className="building-name"
              value={building.name}
              onChange={(e) => {
                const next = [...buildings];
                next[bi] = { ...next[bi], name: e.target.value };
                setBuildings(next);
              }}
            />
            <button onClick={() => removeBuilding(bi)}>Remove building</button>
          </div>

          <h4>Building-wide requirements (not tied to one room)</h4>
          <CapacityTable
            capacities={building.capacities}
            onChange={(role, cap) => updateBuildingCapacity(bi, role, cap)}
          />

          <h4>Rooms</h4>
          {building.rooms.map((room, ri) => (
            <div className="room-card" key={ri}>
              <div className="card-header">
                <input
                  value={room.name}
                  onChange={(e) => {
                    const next = [...buildings];
                    const rooms = [...next[bi].rooms];
                    rooms[ri] = { ...rooms[ri], name: e.target.value };
                    next[bi] = { ...next[bi], rooms };
                    setBuildings(next);
                  }}
                />
                <button onClick={() => removeRoom(bi, ri)}>Remove room</button>
              </div>
              <CapacityTable capacities={room.capacities} onChange={(role, cap) => updateRoomCapacity(bi, ri, role, cap)} />
            </div>
          ))}
          <button onClick={() => addRoom(bi)}>+ Add room</button>
        </div>
      ))}
      <button onClick={addBuilding}>+ Add building</button>

      <h3>Solver weights</h3>
      <div className="card">
        <label>
          Role preference weight
          <input
            type="number"
            value={solverConfig.weights.role_preference}
            onChange={(e) =>
              setSolverConfig({
                ...solverConfig,
                weights: { ...solverConfig.weights, role_preference: Number(e.target.value) },
              })
            }
          />
        </label>
        <label>
          Building mismatch weight
          <input
            type="number"
            value={solverConfig.weights.building_mismatch}
            onChange={(e) =>
              setSolverConfig({
                ...solverConfig,
                weights: { ...solverConfig.weights, building_mismatch: Number(e.target.value) },
              })
            }
          />
        </label>
        <label>
          Friend-unsatisfied weight
          <input
            type="number"
            value={solverConfig.weights.friend_unsatisfied}
            onChange={(e) =>
              setSolverConfig({
                ...solverConfig,
                weights: { ...solverConfig.weights, friend_unsatisfied: Number(e.target.value) },
              })
            }
          />
        </label>
        <label>
          Friend scoring mode
          <select
            value={solverConfig.friend_scoring.mode}
            onChange={(e) =>
              setSolverConfig({
                ...solverConfig,
                friend_scoring: { ...solverConfig.friend_scoring, mode: e.target.value as "pairwise" | "mutual" },
              })
            }
          >
            <option value="pairwise">Pairwise (partial credit per request)</option>
            <option value="mutual">Mutual only (both must name each other)</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={solverConfig.friend_scoring.symmetric}
            onChange={(e) =>
              setSolverConfig({
                ...solverConfig,
                friend_scoring: { ...solverConfig.friend_scoring, symmetric: e.target.checked },
              })
            }
          />
          Symmetric (merge a mutual pair into one scored request instead of two)
        </label>
      </div>

      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button disabled={busy} onClick={saveConfig}>
          Save config
        </button>
        <button disabled={busy || state.helpers.length === 0} onClick={saveAndSolve}>
          Save &amp; solve
        </button>
      </div>
      {state.helpers.length === 0 && <p className="hint">Upload helper responses first.</p>}
    </div>
  );
}
