import os
import json
import sys
import time

# Make paths robust so it can be run from root or external_ai dir
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)


def resolve_map_file_path():
    """Return path to pokeemerald.map in script dir or parent dir."""
    candidates = [
        os.path.join(_SCRIPT_DIR, "pokeemerald.map"),
        os.path.join(_PROJECT_DIR, "pokeemerald.map"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


MAP_FILE = resolve_map_file_path()
LOOKUP_DIR = os.path.join(_SCRIPT_DIR, "lookups")
MOVES_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "moves_lookup.json")
SPECIES_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "species_lookup.json")
ITEMS_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "items_lookup.json")
COMM_FILE_IN = os.path.join(_SCRIPT_DIR, "comm_in.txt")
COMM_FILE_OUT = os.path.join(_SCRIPT_DIR, "comm_out.txt")

# EXT_CTRL constants
EXT_CTRL_STATE_IDLE = 0
EXT_CTRL_STATE_WAITING = 1
EXT_CTRL_STATE_DONE = 2

EXT_CTRL_ACTION_MOVE = 0
EXT_CTRL_ACTION_ITEM = 1
EXT_CTRL_ACTION_SWITCH = 2

# Move target types (from include/battle.h)
MOVE_TARGET_SELECTED         = 0
MOVE_TARGET_DEPENDS          = 1 << 0
MOVE_TARGET_USER_OR_SELECTED = 1 << 1
MOVE_TARGET_RANDOM           = 1 << 2
MOVE_TARGET_BOTH             = 1 << 3
MOVE_TARGET_USER             = 1 << 4
MOVE_TARGET_FOES_AND_ALLY    = 1 << 5
MOVE_TARGET_OPPONENTS_FIELD  = 1 << 6

# Battler positions
B_POSITION_PLAYER_LEFT    = 0
B_POSITION_OPPONENT_LEFT  = 1
B_POSITION_PLAYER_RIGHT   = 2
B_POSITION_OPPONENT_RIGHT = 3


# ---------------------------------------------------------------------------
# Name lookups (loaded from JSON files generated once from source headers)
# ---------------------------------------------------------------------------
def load_lookup_names(lookup_path, fallback_zero_name):
    """Load {id: name} mapping from JSON file with string keys."""
    names = {0: fallback_zero_name}

    try:
        with open(lookup_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for key, value in raw.items():
            try:
                names[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
    except FileNotFoundError:
        print(
            f"Warning: Could not find {lookup_path}. "
            "Names will show as numeric IDs."
        )
    except (OSError, json.JSONDecodeError):
        print(f"Warning: Failed to read {lookup_path}. Names will show as numeric IDs.")

    return names


MOVE_NAMES = load_lookup_names(MOVES_LOOKUP_FILE, "(None)")
SPECIES_NAMES = load_lookup_names(SPECIES_LOOKUP_FILE, "???")
ITEM_NAMES = load_lookup_names(ITEMS_LOOKUP_FILE, "(None)")


def move_name(move_id):
    return MOVE_NAMES.get(move_id, f"Move#{move_id}")


def species_name(species_id):
    return SPECIES_NAMES.get(species_id, f"Species#{species_id}")


def item_name(item_id):
    return ITEM_NAMES.get(item_id, f"Item#{item_id}")


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------
def get_symbol_address(symbol_name):
    map_file = resolve_map_file_path()
    try:
        with open(map_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == symbol_name:
                    addr = int(parts[0], 16)
                    # EWRAM addresses start at 0x02000000
                    if 0x02000000 <= addr < 0x03000000:
                        return addr
    except FileNotFoundError:
        print(
            "Error: Could not find pokeemerald.map in either "
            f"{_SCRIPT_DIR} or {_PROJECT_DIR}. Please compile the ROM first."
        )
        sys.exit(1)

    print(f"Error: Could not find symbol {symbol_name} in map file.")
    sys.exit(1)

def write_out(data):
    with open(COMM_FILE_OUT, "w") as f:
        f.write(data)

def read_in():
    try:
        with open(COMM_FILE_IN, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------------------
# Parse the WAITING message from Lua
# Format: WAITING <numMoves> <m0> <pp0> ... <numSwitches> <sw0> <sp0> ...
#                 <numItems> <i0..i3>
#                 <isDouble> <activeBattlerId> <fieldSp0..3> <mt0..3>
# Total: 1 + 1 + 8 + 1 + 10 + 1 + 4 + 1 + 1 + 4 + 4 = 36 parts
# ---------------------------------------------------------------------------
def parse_waiting_state(msg):
    parts = msg.split()
    if len(parts) < 36 or parts[0] != "WAITING":
        return None
    try:
        idx = 1
        num_moves = int(parts[idx]); idx += 1
        moves = []
        for i in range(4):
            mid = int(parts[idx]); idx += 1
            pp  = int(parts[idx]); idx += 1
            moves.append((mid, pp))
        num_switches = int(parts[idx]); idx += 1
        switch_slots = []
        switch_species = []
        for i in range(5):
            slot = int(parts[idx]); idx += 1
            sp   = int(parts[idx]); idx += 1
            switch_slots.append(slot)
            switch_species.append(sp)
        num_items = int(parts[idx]); idx += 1
        trainer_items = []
        for i in range(4):
            item_id = int(parts[idx]); idx += 1
            trainer_items.append(item_id)
        is_double = int(parts[idx]); idx += 1
        active_battler_id = int(parts[idx]); idx += 1
        field_species = []
        for i in range(4):
            fsp = int(parts[idx]); idx += 1
            field_species.append(fsp)
        move_targets = []
        for i in range(4):
            mt = int(parts[idx]); idx += 1
            move_targets.append(mt)
        return {
            "num_moves": num_moves,
            "moves": moves,
            "num_switches": num_switches,
            "switch_slots": switch_slots[:num_switches],
            "switch_species": switch_species[:num_switches],
            "num_items": num_items,
            "trainer_items": trainer_items,
            "is_double": is_double,
            "active_battler_id": active_battler_id,
            "field_species": field_species,
            "move_targets": move_targets,
        }
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Position labels for display
# ---------------------------------------------------------------------------
POSITION_LABELS = {
    B_POSITION_PLAYER_LEFT:    "Player Left",
    B_POSITION_OPPONENT_LEFT:  "Opponent Left",
    B_POSITION_PLAYER_RIGHT:   "Player Right",
    B_POSITION_OPPONENT_RIGHT: "Opponent Right",
}


def needs_single_target(move_target_type):
    """Return True if this move target type requires the user to pick one target."""
    return move_target_type == MOVE_TARGET_SELECTED


def get_valid_targets(info):
    """Return list of battler IDs that are valid targets for a single-target move.

    For MOVE_TARGET_SELECTED, valid targets are living battlers on the
    opposite side from the active battler.
    """
    active = info["active_battler_id"]
    active_side = active & 1  # 0 = player side, 1 = opponent side
    targets = []
    for pos in range(4):
        if (pos & 1) != active_side and info["field_species"][pos] != 0:
            targets.append(pos)
    return targets


def prompt_target(info):
    """Ask the user which battler to target. Returns a battler ID (0-3)."""
    valid = get_valid_targets(info)
    if len(valid) == 0:
        return 0  # fallback
    if len(valid) == 1:
        sp = info["field_species"][valid[0]]
        print(f"  (Auto-targeting {species_name(sp)} at {POSITION_LABELS[valid[0]]})")
        return valid[0]

    print("Select target:")
    for pos in valid:
        sp = info["field_species"][pos]
        print(f"  {pos}: {species_name(sp)}  ({POSITION_LABELS[pos]})")

    chosen = None
    while chosen not in valid:
        try:
            chosen = int(input(f"Target ({'/'.join(str(t) for t in valid)}): "))
            if chosen not in valid:
                print(f"Invalid. Choose from: {valid}")
        except ValueError:
            print("Invalid input.")
    return chosen


# ---------------------------------------------------------------------------
# Prompt the user with only valid choices
# ---------------------------------------------------------------------------
def prompt_action(info):
    """Display valid actions & sub-choices. Returns (action, index, target)."""
    valid_move_slots = [
        i for i, (mid, pp) in enumerate(info["moves"])
        if mid != 0 and pp > 0
    ]
    # Available trainer item slots (non-zero item IDs)
    valid_item_slots = [
        i for i, item_id in enumerate(info["trainer_items"])
        if item_id != 0
    ]
    has_moves    = len(valid_move_slots) > 0
    has_switches = info["num_switches"] > 0
    has_items    = len(valid_item_slots) > 0

    # Build menu of top-level actions
    options = []
    if has_moves:
        options.append(EXT_CTRL_ACTION_MOVE)
    if has_items:
        options.append(EXT_CTRL_ACTION_ITEM)
    if has_switches:
        options.append(EXT_CTRL_ACTION_SWITCH)

    # If nothing is available (shouldn't normally happen), default to Struggle
    if not options:
        print("  No valid actions available — forcing Move 0 (Struggle).")
        return (EXT_CTRL_ACTION_MOVE, 0, 0)

    # If only switch is available (forced switch after faint), skip the menu
    if options == [EXT_CTRL_ACTION_SWITCH]:
        print("\n--- A Pokemon fainted! Choose a replacement ---")
        action = EXT_CTRL_ACTION_SWITCH
    else:
        print("\n--- Opponent is waiting for a decision ---")
        print("Available actions:")
        action_labels = {
            EXT_CTRL_ACTION_MOVE:   "Use Move",
            EXT_CTRL_ACTION_ITEM:   "Use Item",
            EXT_CTRL_ACTION_SWITCH: "Switch Pokemon",
        }
        for opt in options:
            print(f"  {opt}: {action_labels[opt]}")

        action = None
        while action not in options:
            try:
                action = int(input(f"Select Action ({'/'.join(str(o) for o in options)}): "))
                if action not in options:
                    print(f"Invalid. Choose from: {options}")
            except ValueError:
                print("Invalid input.")

    index = 0
    target = 0

    if action == EXT_CTRL_ACTION_MOVE:
        print("Available moves:")
        for slot in valid_move_slots:
            mid, pp = info["moves"][slot]
            print(f"  {slot}: {move_name(mid)}  (PP: {pp})")

        chosen = None
        while chosen not in valid_move_slots:
            try:
                chosen = int(input(f"Select Move Slot ({'/'.join(str(s) for s in valid_move_slots)}): "))
                if chosen not in valid_move_slots:
                    print(f"Invalid. Choose from: {valid_move_slots}")
            except ValueError:
                print("Invalid input.")
        index = chosen
        # Targeting: in double battles, single-target moves need a target prompt
        if info["is_double"] and info["move_targets"][chosen] == MOVE_TARGET_SELECTED:
            target = prompt_target(info)
        else:
            target = 0

    elif action == EXT_CTRL_ACTION_ITEM:
        print("Available items:")
        for slot in valid_item_slots:
            print(f"  {slot}: {item_name(info['trainer_items'][slot])}")

        chosen = None
        while chosen not in valid_item_slots:
            try:
                chosen = int(input(f"Select Item Slot ({'/'.join(str(s) for s in valid_item_slots)}): "))
                if chosen not in valid_item_slots:
                    print(f"Invalid. Choose from: {valid_item_slots}")
            except ValueError:
                print("Invalid input.")
        index = chosen

    elif action == EXT_CTRL_ACTION_SWITCH:
        print("Available Pokemon to switch to:")
        for j, slot in enumerate(info["switch_slots"]):
            sp_id = info["switch_species"][j] if j < len(info["switch_species"]) else 0
            print(f"  {slot}: {species_name(sp_id)}")
        chosen = None
        while chosen not in info["switch_slots"]:
            try:
                chosen = int(input(f"Select Party Slot ({'/'.join(str(s) for s in info['switch_slots'])}): "))
                if chosen not in info["switch_slots"]:
                    print(f"Invalid. Choose from: {info['switch_slots']}")
            except ValueError:
                print("Invalid input.")
        index = chosen

    return (action, index, target)


def main():
    print("Pokemon Emerald External AI Controller")
    print("--------------------------------------")

    address = get_symbol_address("gExternalControl")
    print(f"Found gExternalControl at address: {hex(address)}")

    # Write the address to the OUT file so Lua knows where to look
    write_out(f"ADDR {hex(address)}")

    print("Waiting for game to request an action...")

    try:
        while True:
            state = read_in()
            if state.startswith("WAITING"):
                info = parse_waiting_state(state)
                if info is None:
                    # Fallback: old-style WAITING without data (shouldn't happen)
                    print("Warning: received WAITING without validity data.")
                    time.sleep(0.5)
                    continue

                action, index, target = prompt_action(info)

                # Format: DECISION <action> <index> <target>
                decision_str = f"DECISION {action} {index} {target}"
                write_out(decision_str)
                print("Sent decision to emulator.")
                print("Waiting for next action...")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nExiting...")
        if os.path.exists(COMM_FILE_IN):
            os.remove(COMM_FILE_IN)
        if os.path.exists(COMM_FILE_OUT):
            os.remove(COMM_FILE_OUT)

if __name__ == "__main__":
    main()
