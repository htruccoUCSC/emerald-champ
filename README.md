# Pokemon Emerald External AI Controller

This directory contains the bridge scripts used to externally control enemy trainer AI decisions in Pokemon Emerald.

## Architecture

```(text)
ROM (C) --> BizHawk (Lua) --> text files --> Python CLI
                <--         <--
```

1. **Modified Emerald ROM** — All trainer battles use a custom `LinkOpponent` battle controller instead of the standard AI. Each turn the controller populates an EWRAM struct (`gExternalControl`) with the current battle state and sets its `state` field to `WAITING`, then spins until `state` becomes `DONE`.
2. **BizHawk Lua script (`bizhawk_bridge.lua`)** — Runs inside BizHawk every frame. Polls `gExternalControl.state` directly from EWRAM. When `WAITING`, it reads the full battle state from the struct and writes it to `comm_in.txt`. When it reads a `DECISION` from `comm_out.txt`, it writes the chosen action back into memory and sets `state = DONE`.
3. **Python script (`external_controller.py`)** — Parses `pokeemerald.map` to find the EWRAM address of `gExternalControl` and sends it to Lua once at startup. Then loops, reading `comm_in.txt` for `WAITING` messages and writing `DECISION` messages to `comm_out.txt` based on user input.

## The `gExternalControl` Struct

Defined in `include/external_control.h`. The ROM populates all read-only fields before setting `state = WAITING`. Python writes `action`, `index`, and `target`, then sets `state = DONE`.

| Offset | Field | Type | Direction | Description |
| -------- | ------- | ------ | ----------- | ------------- |
| 0 | `state` | `u8` | R/W | `0` = IDLE, `1` = WAITING, `2` = DONE |
| 1 | `action` | `u8` | Write | `0` = Move, `1` = Item, `2` = Switch |
| 2 | `index` | `u16` | Write | Move slot (0–3), item slot (0–3), or party slot (0–5) |
| 4 | `target` | `u8` | Write | Battler ID of the target (doubles only) |
| 5 | `numValidMoves` | `u8` | Read | Number of usable moves (have PP > 0) |
| 6 | `moveIds[4]` | `u16[4]` | Read | Move ID per slot (`0` = empty) |
| 14 | `movePp[4]` | `u8[4]` | Read | Current PP per slot |
| 18 | `numValidSwitches` | `u8` | Read | Number of party members that can be switched to |
| 19 | `validSwitchSlots[5]` | `u8[5]` | Read | Party indices of switchable Pokémon |
| 24 | `switchSpecies[5]` | `u16[5]` | Read | Species ID for each switchable slot |
| 34 | `trainerItemIds[4]` | `u16[4]` | Read | Item IDs in the trainer's inventory (`0` = used/empty) |
| 42 | `numTrainerItems` | `u8` | Read | Number of available items |
| 43 | `isDoubleBattle` | `u8` | Read | `1` if this is a double battle |
| 44 | `fieldSpecies[4]` | `u16[4]` | Read | Species at battler positions 0–3 (`0` = fainted/absent) |
| 52 | `activeBattlerId` | `u8` | Read | Battler position (0–3) of the mon choosing an action |
| 53 | `moveTargets[4]` | `u8[4]` | Read | `gBattleMoves[move].target` flag per move slot |

## IPC Message Format

### `comm_in.txt` (Lua → Python)

- `IDLE` — Game is not waiting for input.
- `WAITING <35 space-separated integers>` — Game is waiting. Fields in order:

  ```(text)
  numMoves  m0 pp0 m1 pp1 m2 pp2 m3 pp3
  numSwitches  sw0 sp0 sw1 sp1 sw2 sp2 sw3 sp3 sw4 sp4
  numItems  i0 i1 i2 i3
  isDouble activeBattlerId  fsp0 fsp1 fsp2 fsp3  mt0 mt1 mt2 mt3
  ```

### `comm_out.txt` (Python → Lua)

- `ADDR 0x02XXXXXX` — Sent once at startup to register the struct address.
- `DECISION <action> <index> <target>` — Sent after the user makes a choice.

## Available Actions

| Action | Value | `index` meaning | `target` meaning |
| -------- | ------- | ----------------- | ------------------ |
| Use Move | `0` | Move slot (0–3) | Battler ID; only used in doubles for `MOVE_TARGET_SELECTED` moves |
| Use Item | `1` | Trainer item slot (0–3) | Ignored |
| Switch | `2` | Party slot (0–5) | Ignored |

**Targeting in double battles:** The Python script checks `moveTargets[slot]`. If the flag is `MOVE_TARGET_SELECTED` (= 0), the move hits one target and the user is prompted to choose. Multi-target moves (Surf, etc.) and self-targeting moves (Harden, etc.) skip the prompt — the C controller resolves the target automatically.

**Item use:** The C controller handles all battle-script setup (`chosenItem`, `AI_itemType`, `AI_itemFlags`) when `DONE` is read with action = `1`. The Python script only needs to pass a valid item slot; the item is removed from the trainer's inventory automatically.

## Setup

### 1. Setup the ROM

Download the patch from the releases page and apply it to a legitimate copy of Pokemon Emerald.

Download the map file as well and place it in the root directory.
The Python script reads `pokeemerald.map` from the project root to locate `gExternalControl` in EWRAM.

### 2. Load the ROM in BizHawk

1. Download and install [BizHawk](https://tasvideos.org/BizHawk).
2. Open BizHawk and load `pokeemerald.gba`.
3. Open the Lua Console (`Tools` → `Lua Console`).
4. Click the folder icon and open `external_ai/bizhawk_bridge.lua`.
5. The console prints:

   ```(text)
   Starting External AI Bridge...
   Waiting for Python script to provide memory address...
   ```

### 3. Run the Python script

```bash
cd external_ai
python external_controller.py
```

The script finds `gExternalControl`, sends its address to Lua, then waits.

### 4. Play

Start a trainer battle. Each time the opponent needs to act, the Python terminal will print the available options and prompt for input, for example:

```(text)
--- Opponent is waiting for a decision ---
Available actions:
  0: Use Move
  1: Use Item
  2: Switch Pokemon
Select Action (0/1/2): 0
Available moves:
  0: Tackle  (PP: 35)
  1: Growl   (PP: 40)
Select Move Slot (0/1): 0
Sent decision to emulator.
```

In a double battle with a single-target move, an additional targeting prompt appears:

```(text)
Select target:
  0: Torchic  (Player Left)
  2: Mudkip   (Player Right)
Target (0/2):
```

## Extending the AI

`external_controller.py` is designed to be straightforward to modify. The `prompt_action(info)` function receives a dict with the full battle state and returns `(action, index, target)`. Replace the `input()` calls with any programmatic logic — rule-based heuristics, an RL model, an API call, etc. — to automate opponent decision-making.
