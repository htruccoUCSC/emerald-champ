import os
import json
import struct
import sys
import time
import copy
import re
from dotenv import load_dotenv
load_dotenv()
from google import genai
from google.genai import types

apiKey = os.getenv("API_KEY")
client = genai.Client(api_key=apiKey)

# Make paths robust so it can be run from root or external_ai dir
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
LOOKUP_DIR = os.path.join(_SCRIPT_DIR, "lookups")
MOVES_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "moves_lookup.json")
SPECIES_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "species_lookup.json")
ITEMS_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "items_lookup.json")
ABILITIES_LOOKUP_FILE = os.path.join(LOOKUP_DIR, "abilities_lookup.json")
ADDRESS_CONFIG_FILE = os.path.join(LOOKUP_DIR, "external_addresses.json")
COMM_FILE_IN = os.path.join(_SCRIPT_DIR, "comm_in.txt")
COMM_FILE_OUT = os.path.join(_SCRIPT_DIR, "comm_out.txt")


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

# Battle state struct sizes (must match C header)
EXT_MON_DATA_SIZE    = 40
EXT_ACTIVE_MON_SIZE  = 48
EXT_BATTLE_STATE_SIZE = 456

# Type names (from include/constants/pokemon.h)
TYPE_NAMES = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison",
    4: "Ground", 5: "Rock", 6: "Bug", 7: "Ghost",
    8: "Steel", 9: "Mystery", 10: "Fire", 11: "Water",
    12: "Grass", 13: "Electric", 14: "Psychic", 15: "Ice",
    16: "Dragon", 17: "Dark", 255: "None",
}
#Ghost and Dark type moves were not very effective against Steel type Pokémon. in gen 3
TYPE_CHART = {
    "Water": {"Fire": 2, "Water": 0.5, "Electric": 1, "Grass": 0.5, "Ice": 1, "Fighting": 1, "Poison": 1, "Ground": 2, "Flying": 1, "Psychic": 1, "Bug": 1, "Rock": 2, "Ghost": 1, "Dragon": 0.5, "Dark": 1, "Steel": 1, "Normal": 1},
    "Fire": {"Fire": 0.5, "Water": 0.5, "Electric": 1, "Grass": 2, "Ice": 2, "Fighting": 1, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 1, "Bug": 2, "Rock": 0.5, "Ghost": 1, "Dragon": 0.5, "Dark": 1, "Steel": 2, "Normal": 1},
    "Electric": {"Fire": 1, "Water": 2, "Electric": 0.5, "Grass": 0.5, "Ice": 1, "Fighting": 1, "Poison": 1, "Ground": 0, "Flying": 2, "Psychic": 1, "Bug": 1, "Rock": 1, "Ghost": 1, "Dragon": 0.5, "Dark": 1, "Steel": 1, "Normal": 1},
    "Grass": {"Fire": 0.5, "Water": 2, "Electric": 1, "Grass": 0.5, "Ice": 1, "Fighting": 1, "Poison": 0.5, "Ground": 2, "Flying": 0.5, "Psychic": 1, "Bug": 0.5, "Rock": 2, "Ghost": 1, "Dragon": 0.5, "Dark": 1, "Steel": 0.5, "Normal": 1},
    "Ice": {"Fire": 0.5, "Water": 0.5, "Electric": 1, "Grass": 2, "Ice": 0.5, "Fighting": 1, "Poison": 1, "Ground": 2, "Flying": 2, "Psychic": 1, "Bug": 1, "Rock": 1, "Ghost": 1, "Dragon": 2, "Dark": 1, "Steel": 0.5, "Normal": 1},
    "Fighting": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 2, "Fighting": 1, "Poison": 0.5, "Ground": 1, "Flying": 0.5, "Psychic": 0.5, "Bug": 0.5, "Rock": 2, "Ghost": 0, "Dragon": 1, "Dark": 2, "Steel": 2, "Normal": 2},
    "Poison": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 2, "Ice": 1, "Fighting": 1, "Poison": 0.5, "Ground": 0.5, "Flying": 1, "Psychic": 1, "Bug": 1, "Rock": 0.5, "Ghost": 0.5, "Dragon": 1, "Dark": 1, "Steel": 0, "Normal": 1},
    "Ground": {"Fire": 2, "Water": 1, "Electric": 2, "Grass": 0.5, "Ice": 1, "Fighting": 1, "Poison": 2, "Ground": 1, "Flying": 0, "Psychic": 1, "Bug": 0.5, "Rock": 2, "Ghost": 1, "Dragon": 1, "Dark": 1, "Steel": 2, "Normal": 1},
    "Flying": {"Fire": 1, "Water": 1, "Electric": 0.5, "Grass": 2, "Ice": 1, "Fighting": 2, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 1, "Bug": 2, "Rock": 0.5, "Ghost": 1, "Dragon": 1, "Dark": 1, "Steel": 0.5, "Normal": 1},
    "Psychic": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 1, "Fighting": 2, "Poison": 2, "Ground": 1, "Flying": 1, "Psychic": 0.5, "Bug": 1, "Rock": 1, "Ghost": 1, "Dragon": 1, "Dark": 0, "Steel": 0.5, "Normal": 1},
    "Bug": {"Fire": 0.5, "Water": 1, "Electric": 1, "Grass": 2, "Ice": 1, "Fighting": 0.5, "Poison": 0.5, "Ground": 1, "Flying": 0.5, "Psychic": 2, "Bug": 1, "Rock": 1, "Ghost": 0.5, "Dragon": 1, "Dark": 2, "Steel": 0.5, "Normal": 1},
    "Rock": {"Fire": 2, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 2, "Fighting": 0.5, "Poison": 1, "Ground": 0.5, "Flying": 2, "Psychic": 1, "Bug": 2, "Rock": 1, "Ghost": 1, "Dragon": 1, "Dark": 1, "Steel": 0.5, "Normal": 1},
    "Ghost": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 1, "Fighting": 1, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 2, "Bug": 1, "Rock": 1, "Ghost": 2, "Dragon": 1, "Dark": 0.5, "Steel": 0.5, "Normal": 0},
    "Dragon": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 1, "Fighting": 1, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 1, "Bug": 1, "Rock": 1, "Ghost": 1, "Dragon": 2, "Dark": 1, "Steel": 0.5, "Normal": 1},
    "Dark": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 1, "Fighting": 0.5, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 2, "Bug": 1, "Rock": 1, "Ghost": 2, "Dragon": 1, "Dark": 0.5, "Steel": 0.5, "Normal": 1},
    "Steel": {"Fire": 0.5, "Water": 0.5, "Electric": 0.5, "Grass": 1, "Ice": 2, "Fighting": 1, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 1, "Bug": 1, "Rock": 2, "Ghost": 1, "Dragon": 1, "Dark": 1, "Steel": 0.5, "Normal": 1},
    "Normal": {"Fire": 1, "Water": 1, "Electric": 1, "Grass": 1, "Ice": 1, "Fighting": 1, "Poison": 1, "Ground": 1, "Flying": 1, "Psychic": 1, "Bug": 1, "Rock": 0.5, "Ghost": 0, "Dragon": 1, "Dark": 1, "Steel": 0.5, "Normal": 1}
}

# Weather bits (from include/constants/battle.h)
B_WEATHER_RAIN_TEMPORARY      = 1 << 0
B_WEATHER_RAIN_DOWNPOUR       = 1 << 1
B_WEATHER_RAIN_PERMANENT      = 1 << 2
B_WEATHER_RAIN                = B_WEATHER_RAIN_TEMPORARY | B_WEATHER_RAIN_DOWNPOUR | B_WEATHER_RAIN_PERMANENT
B_WEATHER_SANDSTORM_TEMPORARY = 1 << 3
B_WEATHER_SANDSTORM_PERMANENT = 1 << 4
B_WEATHER_SANDSTORM           = B_WEATHER_SANDSTORM_TEMPORARY | B_WEATHER_SANDSTORM_PERMANENT
B_WEATHER_SUN_TEMPORARY       = 1 << 5
B_WEATHER_SUN_PERMANENT       = 1 << 6
B_WEATHER_SUN                 = B_WEATHER_SUN_TEMPORARY | B_WEATHER_SUN_PERMANENT
B_WEATHER_HAIL_TEMPORARY      = 1 << 7
B_WEATHER_HAIL                = B_WEATHER_HAIL_TEMPORARY

# Stat stage names (indices into statStages[8])
STAT_STAGE_NAMES = ["HP", "Atk", "Def", "Spd", "SpAtk", "SpDef", "Acc", "Eva"]


# ---------------------------------------------------------------------------
# Name lookups (loaded from JSON files generated from source headers)
# ---------------------------------------------------------------------------
def load_lookup_names(lookup_path, fallback_zero_name=None):
    """Load {id: name} mapping from a JSON file with string/int keys."""
    data = {}
    if fallback_zero_name is not None:
        data[0] = {"name": fallback_zero_name}

    try:
        with open(lookup_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for key, value in raw.items():
            try:
                idx = int(key)
                if isinstance(value, str):
                    data[idx] = {"name": value}
                elif isinstance(value, dict):
                    data[idx] = value
            except (TypeError, ValueError):
                continue
    except FileNotFoundError:
        print(f"Warning: Could not find {lookup_path}")
    except (OSError, json.JSONDecodeError):
        print(f"Warning: Failed to read {lookup_path}")
    return data
    
    ###names = {0: fallback_zero_name}
    ###try:
    ###    with open(lookup_path, "r", encoding="utf-8") as f:
    ###        raw = json.load(f)
    ###    for key, value in raw.items():
    ###        try:
    ###            names[int(key)] = str(value)
    ###        except (TypeError, ValueError):
    ###            continue
    ###except FileNotFoundError:
    ###    print(
    ###        f"Warning: Could not find {lookup_path}. "
    ###        "Names will show as numeric IDs."
    ###    )
    ###except (OSError, json.JSONDecodeError):
    ###    print(f"Warning: Failed to read {lookup_path}. Names will show as numeric IDs.")
    ###return names


MOVE_NAMES = load_lookup_names(MOVES_LOOKUP_FILE, "(None)")
SPECIES_NAMES = load_lookup_names(SPECIES_LOOKUP_FILE, "???")
ITEM_NAMES = load_lookup_names(ITEMS_LOOKUP_FILE, "(None)")
ABILITY_NAMES = load_lookup_names(ABILITIES_LOOKUP_FILE, "(None)")
ITEM_NAMES[0] = "(None)"


def move_name(move_id):
    #return MOVE_NAMES.get(move_id, f"Move#{move_id}")
    move = MOVE_NAMES.get(move_id)
    if not move:
        return str(move_id)
    return move["name"]

def move_data(move_id):
    return MOVE_NAMES.get(move_id)

def type_effectiveness(move_type, target_type):
    return TYPE_CHART.get(move_type, {}).get(target_type, 1)

def species_name(species_id):
    return SPECIES_NAMES.get(species_id, f"Species#{species_id}")


def item_name(item_id):
    if item_id == 0:
        return "(None)"
    return ITEM_NAMES.get(item_id, f"Item#{item_id}")


def ability_name(ability_id):
    return ABILITY_NAMES.get(ability_id, f"Ability#{ability_id}")


def type_name(type_id):
    return TYPE_NAMES.get(type_id, f"Type#{type_id}")


def weather_str(weather_bits):
    """Convert weather bitmask to human-readable string."""
    if weather_bits == 0:
        return "Clear"
    labels = []
    if weather_bits & B_WEATHER_RAIN:
        labels.append("Rain")
    if weather_bits & B_WEATHER_SANDSTORM:
        labels.append("Sandstorm")
    if weather_bits & B_WEATHER_SUN:
        labels.append("Sun")
    if weather_bits & B_WEATHER_HAIL:
        labels.append("Hail")
    return ", ".join(labels) if labels else f"0x{weather_bits:04X}"


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------
def get_symbol_address(symbol_name):
    try:
        with open(MAP_FILE, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == symbol_name:
                    addr = int(parts[0], 16)
                    # EWRAM addresses start at 0x02000000
                    if 0x02000000 <= addr < 0x03000000:
                        return addr
    except FileNotFoundError:
        print(f"Error: Could not find {MAP_FILE}. Please compile the ROM first.")
        sys.exit(1)

    print(f"Error: Could not find symbol {symbol_name} in map file.")
    sys.exit(1)


def load_config_addresses():
    """Load cached external addresses from JSON config if present."""
    try:
        with open(ADDRESS_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        print(f"Warning: Failed to read {ADDRESS_CONFIG_FILE}; falling back to map lookup.")
        return None

    try:
        ctrl = int(str(data["gExternalControl"]), 0)
        state = int(str(data["gExternalBattleState"]), 0)
    except (KeyError, TypeError, ValueError):
        print(f"Warning: Invalid address data in {ADDRESS_CONFIG_FILE}; falling back to map lookup.")
        return None

    return (ctrl, state)


def save_config_addresses(ctrl_addr, state_addr):
    """Persist external addresses for map-free future runs."""
    payload = {
        "gExternalControl": hex(ctrl_addr),
        "gExternalBattleState": hex(state_addr),
    }
    try:
        with open(ADDRESS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        print(f"Warning: Could not write {ADDRESS_CONFIG_FILE}.")


def resolve_external_addresses():
    """Resolve addresses from config first; fallback to map and cache result."""
    cached = load_config_addresses()
    if cached is not None:
        ctrl_addr, state_addr = cached
        print(f"Loaded gExternalControl from config: {hex(ctrl_addr)}")
        print(f"Loaded gExternalBattleState from config: {hex(state_addr)}")
        return ctrl_addr, state_addr

    ctrl_addr = get_symbol_address("gExternalControl")
    print(f"Found gExternalControl at address: {hex(ctrl_addr)}")

    state_addr = get_symbol_address("gExternalBattleState")
    print(f"Found gExternalBattleState at address: {hex(state_addr)}")

    save_config_addresses(ctrl_addr, state_addr)
    print(f"Saved external addresses to {ADDRESS_CONFIG_FILE}")
    return ctrl_addr, state_addr

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
# Battle state decoding (456 raw bytes -> structured dict)
# Must match struct ExternalBattleState in external_battle_state.h
# ---------------------------------------------------------------------------
def decode_ext_mon(raw_bytes, offset):
    """Decode one ExtMonData (40 bytes) starting at *offset* within raw_bytes.

    Layout (little-endian):
      u32 status          (0)
      u16 species         (4)
      u16 heldItem        (6)
      u16 hp              (8)
      u16 maxHp           (10)
      u16 attack          (12)
      u16 defense         (14)
      u16 speed           (16)
      u16 spAttack        (18)
      u16 spDefense       (20)
      u16 moves[4]        (22)
      u8  pp[4]           (30)
      u8  level           (34)
      u8  ability         (35)
      u8  type1           (36)
      u8  type2           (37)
      u8  _pad[2]         (38)
    """
    fmt = "<I 9H 4H 4B 4B 2x"
    vals = struct.unpack_from(fmt, raw_bytes, offset)
    # vals: status, species,heldItem,hp,maxHp,atk,def,spd,spatk,spdef,
    #       mv0,mv1,mv2,mv3, pp0,pp1,pp2,pp3, level,ability,type1,type2
    return {
        "status": vals[0],
        "species": vals[1],
        "heldItem": vals[2],
        "hp": vals[3],
        "maxHp": vals[4],
        "attack": vals[5],
        "defense": vals[6],
        "speed": vals[7],
        "spAttack": vals[8],
        "spDefense": vals[9],
        "moves": [vals[10], vals[11], vals[12], vals[13]],
        "pp": [vals[14], vals[15], vals[16], vals[17]],
        "level": vals[18],
        "ability": vals[19],
        "type1": vals[20],
        "type2": vals[21],
    }


def decode_ext_active(raw_bytes, offset):
    """Decode one ExtActiveMon (48 bytes) = ExtMonData + s8 statStages[8]."""
    mon = decode_ext_mon(raw_bytes, offset)
    stages = struct.unpack_from("<8b", raw_bytes, offset + EXT_MON_DATA_SIZE)
    mon["statStages"] = list(stages)
    return mon


def decode_battle_state(raw_bytes):
    """Decode the full ExternalBattleState (456 bytes) into a dict."""
    if len(raw_bytes) < EXT_BATTLE_STATE_SIZE:
        return None

    state = {}

    # party[6] -- 6 * 40 = 240 bytes at offset 0
    state["party"] = []
    for i in range(6):
        state["party"].append(decode_ext_mon(raw_bytes, i * EXT_MON_DATA_SIZE))

    # active[4] -- 4 * 48 = 192 bytes at offset 240
    state["active"] = []
    base = 6 * EXT_MON_DATA_SIZE  # 240
    for i in range(4):
        state["active"].append(decode_ext_active(raw_bytes, base + i * EXT_ACTIVE_MON_SIZE))

    # Turn tracking at offset 432
    off = base + 4 * EXT_ACTIVE_MON_SIZE  # 432
    state["lastUsedMove"] = list(struct.unpack_from("<4H", raw_bytes, off))
    off += 8
    state["prevHp"] = list(struct.unpack_from("<4H", raw_bytes, off))
    off += 8
    state["weather"] = struct.unpack_from("<H", raw_bytes, off)[0]
    off += 2
    (state["turnNumber"], state["numBattlers"],
     state["numOwnAliveMons"], state["numPlayerAliveMons"]) = struct.unpack_from("<4B", raw_bytes, off)

    return state


# ---------------------------------------------------------------------------
# Display battle state in a readable format
# ---------------------------------------------------------------------------
def format_status(status_bits):
    """Decode STATUS1 flags into short labels."""
    if status_bits == 0:
        return ""
    labels = []
    # Sleep counter in bits 0-2
    sleep_turns = status_bits & 0x7
    if sleep_turns:
        labels.append(f"SLP({sleep_turns})")
    if status_bits & (1 << 3):
        labels.append("PSN")
    if status_bits & (1 << 4):
        labels.append("BRN")
    if status_bits & (1 << 5):
        labels.append("FRZ")
    if status_bits & (1 << 6):
        labels.append("PAR")
    if status_bits & (1 << 7):
        labels.append("TOX")
    return " ".join(labels)


def format_stat_stages(stages):
    """Return string of non-zero stat stage changes."""
    parts = []
    for i, name in enumerate(STAT_STAGE_NAMES):
        if i == 0:
            continue  # skip HP stage (always 0)
        val = stages[i] - 6  # stages are stored as 0-12, neutral = 6
        if val != 0:
            sign = "+" if val > 0 else ""
            parts.append(f"{name}{sign}{val}")
    return ", ".join(parts) if parts else "neutral"


def display_battle_state(bs):
    """Print a comprehensive battle summary."""
    print("\n" + "=" * 60)
    print(f"  BATTLE STATE  --  Turn {bs['turnNumber']}  |  Weather: {weather_str(bs['weather'])}")
    print(f"  Own alive: {bs['numOwnAliveMons']}  |  Player alive: {bs['numPlayerAliveMons']}  |  Battlers: {bs['numBattlers']}")
    print("=" * 60)

    # Active battlers on the field
    print("\n--- Active Battlers on Field ---")
    for i in range(bs["numBattlers"]):
        a = bs["active"][i]
        if a["species"] == 0:
            continue
        side = "OPP" if (i & 1) == 1 else "PLR"
        slot_label = f"[{side} {'L' if i < 2 else 'R'}]"
        status_str = format_status(a["status"])
        status_display = f"  [{status_str}]" if status_str else ""

        types = type_name(a["type1"])
        if a["type2"] != a["type1"]:
            types += "/" + type_name(a["type2"])
       
        print(f"  {slot_label} {species_name(a['species'])} Lv{a['level']}  "
              f"HP: {a['hp']}/{a['maxHp']}  {types}{status_display}")
        print(f"         Atk:{a['attack']} Def:{a['defense']} SpA:{a['spAttack']} "
              f"SpD:{a['spDefense']} Spe:{a['speed']}")
        print(f"         Ability: {ability_name(a['ability'])}  "
              f"Item: {item_name(a['heldItem'])}")
        print(f"         Stages: {format_stat_stages(a['statStages'])}")

        moves_str = "         Moves: "
        mvs = []
        for j in range(4):
            if a["moves"][j] != 0:
                mvs.append(f"{move_name(a['moves'][j])}(PP:{a['pp'][j]})")
        print(moves_str + ", ".join(mvs) if mvs else moves_str + "(none)")

        # Damage taken since last turn (prevHp - currentHp)
        prev = bs["prevHp"][i]
        if prev > 0 and prev > a["hp"]:
            dmg = prev - a["hp"]
            print(f"         ** Took {dmg} damage since last snapshot **")

        # Last move used
        last_mv = bs["lastUsedMove"][i]
        if last_mv != 0:
            print(f"         Last used: {move_name(last_mv)}")

    # Own party summary
    print("\n--- Own Party (Trainer being controlled) ---")
    for i, p in enumerate(bs["party"]):
        if p["species"] == 0:
            continue
        status_str = format_status(p["status"])
        status_display = f"  [{status_str}]" if status_str else ""
        types = type_name(p["type1"])
        if p["type2"] != p["type1"]:
            types += "/" + type_name(p["type2"])
        moves_list = [move_name(p["moves"][j]) for j in range(4) if p["moves"][j] != 0]
        print(f"  [{i}] {species_name(p['species'])} Lv{p['level']}  "
              f"HP: {p['hp']}/{p['maxHp']}  {types}{status_display}")
        print(f"       Atk:{p['attack']} Def:{p['defense']} SpA:{p['spAttack']} "
              f"SpD:{p['spDefense']} Spe:{p['speed']}  "
              f"Ability: {ability_name(p['ability'])}  Item: {item_name(p['heldItem'])}")
        if moves_list:
            pp_list = [str(p["pp"][j]) for j in range(4) if p["moves"][j] != 0]
            print(f"       Moves: {', '.join(moves_list)}  PP: {'/'.join(pp_list)}")


# ---------------------------------------------------------------------------
# Parse the WAITING message from Lua
# Format: WAITING <35 decision-data fields> [STATE <456 bytes>]
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

        # Check for optional battle state block
        battle_state = None
        if idx < len(parts) and parts[idx] == "STATE":
            idx += 1  # skip "STATE" token
            raw_count = len(parts) - idx
            if raw_count >= EXT_BATTLE_STATE_SIZE:
                raw_bytes = bytes(int(parts[idx + j]) for j in range(EXT_BATTLE_STATE_SIZE))
                battle_state = decode_battle_state(raw_bytes)

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
            "battle_state": battle_state,
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
    state = info["battle_state"]

    # Forced switch case --> if AI active pokemon is dead must switch
    if state and state["active"][AI_BATTLER_ID].get("hp", 0) <= 0:
        forced_switches = []
        for slot in info.get("switch_slots", []):
            if 0 <= slot < len(state.get("party", [])) and _is_alive(state["party"][slot]):
                forced_switches.append(slot)

        if forced_switches:
            # Choose the healthiest available replacement
            best_slot = max(
                forced_switches,
                key=lambda s: (
                    state["party"][s]["hp"] / state["party"][s]["maxHp"]
                    if state["party"][s].get("maxHp", 0) > 0
                    else 0
                ),
            )
            print(f"AI forced switch chose party slot: {best_slot}")
            return (EXT_CTRL_ACTION_SWITCH, best_slot, 0)

    score, best_action = choose_action_alpha_beta(info, state, depth=3)

    if best_action:
        action, index, target = best_action
        state["previous_move"] = state["lastUsedMove"][1]
        print(f"AI chose action: {action}, index: {index}, target: {target}")
        return action, index, target

    # Fallback if search returns no legal action --> prefers legal moves, then items, then switches
    if state:
        fallback_switches = []
        for slot in info.get("switch_slots", []):
            if 0 <= slot < len(state.get("party", [])) and _is_alive(state["party"][slot]):
                fallback_switches.append(slot)
        if fallback_switches:
            return (EXT_CTRL_ACTION_SWITCH, fallback_switches[0], 0)

    return (EXT_CTRL_ACTION_MOVE, 0, 0)


# ---------------------------------------------------------------------------
# Improved search (alpha-beta minimax)
# ---------------------------------------------------------------------------
# Change summary:
# 1) Uses alternating turns (AI maximizes, player minimizes)
# 2) Generates actions from the current simulated state, not just initial info
# 3) Simulates move/item/switch for AI, and move for player
# 4) Uses alpha-beta pruning to reduce explored branches
AI_BATTLER_ID = 1
PLAYER_BATTLER_ID = 0


def _is_alive(mon):
    return mon.get("species", 0) != 0 and mon.get("hp", 0) > 0


def _get_enemy_side(side):
    return PLAYER_BATTLER_ID if side == AI_BATTLER_ID else AI_BATTLER_ID


def evaluate_state(state):
    """Heuristic score where higher is better for AI (active battler index 1)."""
    ai = state["active"][AI_BATTLER_ID]
    player = state["active"][PLAYER_BATTLER_ID]

    ai_hp_ratio = (ai["hp"] / ai["maxHp"]) if ai.get("maxHp", 0) > 0 else 0
    player_hp_ratio = (player["hp"] / player["maxHp"]) if player.get("maxHp", 0) > 0 else 0

    # Reward lowering player HP and preserving AI HP
    score = (1.0 - player_hp_ratio) * 140.0
    score -= (1.0 - ai_hp_ratio) * 120.0

    # Strong terminal incentives
    if player.get("hp", 0) <= 0:
        score += 1000
    if ai.get("hp", 0) <= 0:
        score -= 1000

    # Small repeat move penalty to reduce loops
    if state.get("last_move") == state.get("lastUsedMove", [None, None])[AI_BATTLER_ID]:
        score -= 10

    return score


def generate_actions_for_side(info, state, side):
    """Generate legal-ish actions for the acting side from the current state"""
    actions = []
    actor = state["active"][side]

    # If AI active pokemon has fainted --> switch
    if not _is_alive(actor):
        if side == AI_BATTLER_ID:
            for slot in info.get("switch_slots", []):
                if 0 <= slot < len(state.get("party", [])) and _is_alive(state["party"][slot]):
                    actions.append((EXT_CTRL_ACTION_SWITCH, slot, 0))
        return actions

    enemy_side = _get_enemy_side(side)
    enemy_alive = _is_alive(state["active"][enemy_side])

    # Moves from simulated state (keeps PP and move list up to date)
    for slot, move_id in enumerate(actor.get("moves", [])):
        pp = actor.get("pp", [0, 0, 0, 0])[slot] if slot < 4 else 0
        if move_id == 0 or pp <= 0:
            continue

        # In singles --> target the opposing active by default
        if enemy_alive:
            actions.append((EXT_CTRL_ACTION_MOVE, slot, enemy_side))

    # AI only extras based on provided decision info
    if side == AI_BATTLER_ID:
        for slot, item_id in enumerate(info.get("trainer_items", [])):
            if item_id != 0:
                actions.append((EXT_CTRL_ACTION_ITEM, slot, 0))

        for slot in info.get("switch_slots", []):
            if 0 <= slot < len(state.get("party", [])):
                party_mon = state["party"][slot]
                if _is_alive(party_mon):
                    actions.append((EXT_CTRL_ACTION_SWITCH, slot, 0))

    return actions


def simulate_action_for_side(state, info, action, side):
    """Apply one simplified action transition for the acting side"""
    new_state = copy.deepcopy(state)
    act, idx, target = action

    if act == EXT_CTRL_ACTION_MOVE:
        attacker = new_state["active"][side]
        enemy_side = _get_enemy_side(side)

        if not _is_alive(attacker):
            return new_state

        # Use requested target when valid --> otherwise default to enemy active
        defender_idx = target if 0 <= target < len(new_state["active"]) else enemy_side
        if not _is_alive(new_state["active"][defender_idx]):
            defender_idx = enemy_side
        defender = new_state["active"][defender_idx]

        if idx < 0 or idx >= 4:
            return new_state

        move_id = attacker["moves"][idx]
        if move_id == 0 or attacker["pp"][idx] <= 0:
            return new_state

        damage = estimate_damage(attacker, defender, move_id)
        defender["hp"] = max(0, defender["hp"] - damage)
        attacker["pp"][idx] = max(0, attacker["pp"][idx] - 1)

        if side == AI_BATTLER_ID:
            new_state["last_move"] = move_id

    elif act == EXT_CTRL_ACTION_ITEM and side == AI_BATTLER_ID:
        ai = new_state["active"][AI_BATTLER_ID]
        if _is_alive(ai):
            ai["hp"] = min(ai["maxHp"], ai["hp"] + 40)

    elif act == EXT_CTRL_ACTION_SWITCH and side == AI_BATTLER_ID:
        # Swap active AI pokemon with selected party slot
        if 0 <= idx < len(new_state.get("party", [])):
            party_mon = new_state["party"][idx]
            if _is_alive(party_mon):
                old_active = new_state["active"][AI_BATTLER_ID]
                new_state["active"][AI_BATTLER_ID] = party_mon
                new_state["party"][idx] = old_active

    return new_state


def _alpha_beta(info, state, depth, side, alpha, beta):
    player_fainted = state["active"][PLAYER_BATTLER_ID].get("hp", 0) <= 0

    if depth == 0 or player_fainted:
        return evaluate_state(state), None

    actions = generate_actions_for_side(info, state, side)
    if not actions:
        return evaluate_state(state), None

    next_side = _get_enemy_side(side)

    if side == AI_BATTLER_ID:
        best_score = float("-inf")
        best_action = None
        for action in actions:
            new_state = simulate_action_for_side(state, info, action, side)
            score, _ = _alpha_beta(info, new_state, depth - 1, next_side, alpha, beta)
            if score > best_score:
                best_score = score
                best_action = action
            alpha = max(alpha, best_score)
            if beta <= alpha:
                break
        return best_score, best_action

    best_score = float("inf")
    best_action = None
    for action in actions:
        new_state = simulate_action_for_side(state, info, action, side)
        score, _ = _alpha_beta(info, new_state, depth - 1, next_side, alpha, beta)
        if score < best_score:
            best_score = score
            best_action = action
        beta = min(beta, best_score)
        if beta <= alpha:
            break
    return best_score, best_action


def choose_action_alpha_beta(info, state, depth=3):
    return _alpha_beta(
        info,
        state,
        depth,
        AI_BATTLER_ID,
        float("-inf"),
        float("inf"),
    )

def generate_actions(info):
    actions = []
    valid_move_slots = [
        i for i, (mid, pp) in enumerate(info["moves"])
        if mid != 0 and pp > 0
    ]
    valid_item_slots = [
        i for i, item in enumerate(info["trainer_items"])
        if item != 0
    ]

    for slot in valid_move_slots:
        if info["is_double"] and info["move_targets"][slot] == MOVE_TARGET_SELECTED:
            for t in get_valid_targets(info):
                actions.append((EXT_CTRL_ACTION_MOVE, slot, t))
        else:
            actions.append((EXT_CTRL_ACTION_MOVE, slot, 0))

    for slot in valid_item_slots:
        actions.append((EXT_CTRL_ACTION_ITEM, slot, 0))

    for slot in info["switch_slots"]:
        actions.append((EXT_CTRL_ACTION_SWITCH, slot, 0))

    return actions

def evaluate(state):
    score = 0

    player = state["active"][0]
    #oponent is AI
    opponent = state["active"][1]

    #these are currently correct
    #print("player: ", player)
    #print("opponent: ", opponent)

    if opponent["hp"] <= 0:
        #print("1")
        score -= 200
    elif opponent["maxHp"] > 0:
        #print("2")
        score += (1 - opponent["hp"] / opponent["maxHp"]) * 100
        #print("score after 2: ",score)
    
    if player["hp"] <= 0:
        #print("3")
        score += 200
    elif player["maxHp"] > 0:
        #print("4")
        score += (player["hp"] / player["maxHp"]) * 50
        #print("score after 4: ", score)
    #print("lastmove: ", state["lastUsedMove"][1])
    #print("state['last_move'] ", state["last_move"])

    last_real_move = state.get("lastUsedMove", [None, None])[1]
    simulated_move = state.get("last_move")
    #if state["lastUsedMove"][1] == state["last_move"]:
    if last_real_move == simulated_move:
        #print("did this work")
        score -= 20

    #print("score in evaluate: ", score)
    return score

llm_cache = {}

def matchup(attacker_type, defender):
    multiplier = type_effectiveness(attacker_type, defender["type1"])

    if defender["type2"] is not None:
        multiplier *= type_effectiveness(attacker_type, defender["type2"])

    return multiplier

def format_switches(party):
    switches = []
    for mon in party:
        if mon["hp"] <= 0 or mon["species"] == 0:
            continue

        switches.append(
            f'{species_name(mon["species"])} '
            f'(HP {mon["hp"]}/{mon["maxHp"]}, '
            f'Types: {type_name(mon["type1"])}/{type_name(mon["type2"])}, '
            f'Speed {mon["speed"]})'
        )
    return "\n".join(switches)

def LLM_evaluate(state):
    player = state["active"][0]
    opponent = state["active"][1]
    
    key = f'{species_name(player["species"])}_{player["hp"]}_{species_name(opponent["species"])}_{opponent["hp"]}'

    if key in llm_cache:
        return llm_cache[key]

    player_attack = max(
        matchup(player["type1"], opponent),
        matchup(player["type2"], opponent) if player["type2"] else 0
    )

    opponent_attack = max(
        matchup(opponent["type1"], player),
        matchup(opponent["type2"], player) if opponent["type2"] else 0
    )

    available_switches = [
        mon for mon in state["party"]
        if mon["hp"] > 0 and mon["species"] != 0
    ]

    prompt = f"""
        You are trying to evaluate the current state of a Pokemon battle and find the
        move that is most advantageous for the opponent which is the current AI we are training
        Evaluate this Pokemon battle at the current state.

        Player Pokemon: {species_name(player["species"])}
        Player HP: {player["hp"]}/{player["maxHp"]}
        Player types: {type_name(player["type1"])}, {type_name(player["type2"])}
        Player Stats: Special Defense: {player["spDefense"]}, Special Attack: {player["spAttack"]}, Speed: {player["speed"]}, Defense: {player["defense"]}, Attack: {player["attack"]}
        Player Ability: {player["ability"]}

        Opponent Pokemon: {species_name(opponent["species"])}
        Opponent HP: {opponent["hp"]}/{opponent["maxHp"]}
        Opponent types: {type_name(opponent["type1"])}, {type_name(opponent["type2"])}
        Opponent Stats: Special Defense: {opponent["spDefense"]}, Special Attack: {opponent["spAttack"]}, Speed: {opponent["speed"]}, Defense: {opponent["defense"]}, Attack: {opponent["attack"]}
        Opponent Ability: {opponent["ability"]}

        From the given information consider Pokemon type advantages heavily

        Best player STAB effectiveness: {player_attack}x
        Best opponent STAB effectiveness: {opponent_attack}x

        Available switches: {format_switches(state["party"])}

        Before evaluating, consider these factors:
        - HP remaining for both player and opponent
        - Speed advantage
        - Type advantage
        - Defensive matchups
        - Ability effects

        Score the position from 0 to 100:
        100 = AI guarateed win
        50 = equal
        0 = AI guaranteed loss

        Think silently and return only the score.
        Return ONLY valid JSON. Do not include explanations, markdown, or extra text.
        {{"score": number}}
    """
    #print(prompt)

    response = call_llm(prompt)

    response = re.sub(r"```json", "", response)
    response = re.sub(r"```", "", response)
    response = response.strip()

    try:
        match = re.search(r'\{.*?"score".*?\}', response, re.DOTALL)
        if match:
            data = json.loads(response)
            score = float(data["score"])
        else:
            raise ValueError("No JSON found")
    except Exception as e:
        print("response parsing failed: ", response)
        score = 50

    llm_cache[key] = score
    print(score)
    return score

def call_llm(prompt): 
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=types.Part.from_text(text=prompt),
        config=types.GenerateContentConfig(
            temperature=0, top_p=0.95, top_k=20
        ),
    )  
    text = response.text
    print("Text: ",text)
    return text

def simulate(state, action, ai_turn):
    new_state = copy.deepcopy(state)
    act, idx, target = action
    if act == EXT_CTRL_ACTION_MOVE:
            if ai_turn:
                attacker = new_state["active"][1] #AI
                defender = new_state["active"][0]
            else:

                attacker = new_state["active"][0] #Player
                defender = new_state["active"][1]

            #AI is attacker,
            #Player is Defender

            #get each moveID from AI
            move_id = attacker["moves"][idx]
            #estimate how much that move will do against player
            damage = estimate_damage(attacker, defender, move_id)

            defender["hp"] = max(0, defender["hp"] - damage)
            new_state["last_move"] = move_id
            #print("new_state['ya whatever tf']: ",new_state["last_move"] )
            #print("here is what defender hp is after dmg calc: ", defender["hp"])
    return new_state

def estimate_damage(attacker, defender, move_id):
    #print("move_id: ",move_id)
    mv = move_data(move_id)

    if not mv:
        return 0
    power = mv["power"]
    #print("power: ", power)
    if power == 0:
        return 0
    level = attacker["level"]

    if mv["category"] == "physical":
        attack = attacker["attack"]
        defense = defender["defense"]
    else:
        attack = attacker["spAttack"]
        defense = defender["spDefense"]

    damage = ((((2 * level + 10) / 250) * power * (attack / defense)) / 50) + 2
    #print("type, attacker type1, attacker type2: ", mv["type"], type_name(defender["type1"]), type_name(defender["type2"]))
    stab = 1
    #STAB damage
    if mv["type"] == type_name(attacker["type1"]) or mv["type"] == type_name(attacker["type2"]):
        #print("hello my damge is 1.5")
        stab *= 1.5

    multiplier = type_effectiveness(mv["type"], type_name(defender["type1"]))
    #print("Multiplier 1: ", multiplier)

    if defender["type2"] != defender["type1"]:
        #print(mv["type"], type_name(defender["type2"]))
        #print("type_effectiveness", type_effectiveness(mv["type"], type_name(defender["type2"])))
        multiplier *= type_effectiveness(mv["type"], type_name(defender["type2"]))
        #print("Multiplier 2: ", multiplier)

    #damage does not take into account the pokemon critical hits
    #or the randomness inputed
    damage = damage * stab * multiplier
    
    #print("here is was damage is after calculation: ", damage)
    return int(damage)

def minimax(info, state, depth, maximizing):
    #print("depth: ",depth)
    if depth == 0:
        return LLM_evaluate(state), None
    if maximizing:
        best_score = float("-inf")
        best_action = None

        actions = generate_actions(info)

        for action in actions:
            print("action: ", action)
            new_state = simulate(state, action, ai_turn=True)

            score, _ = minimax(info, new_state, depth - 1, False)

            if score > best_score:
                best_score = score
                best_action = action
        print("returning after maximizing: ",best_score, best_action)
        return best_score, best_action
    else:
        best_score = float("inf")
        actions = generate_actions(info)

        for action in actions:
            new_state = simulate(state, action, ai_turn=False)
            
            score, _ = minimax(info, new_state, depth-1, True)

            if score < best_score:
                best_score = score
        print("returning after minimizing: ", best_score)
        return best_score, None

def main():
    print("Pokemon Emerald External AI Controller")
    print("--------------------------------------")

    ctrl_addr, state_addr = resolve_external_addresses()

    # Write both addresses to the OUT file so Lua knows where to look
    write_out(f"ADDR {hex(ctrl_addr)} {hex(state_addr)}")

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

                # Display full battle state if available
                if info.get("battle_state"):
                    display_battle_state(info["battle_state"])

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
