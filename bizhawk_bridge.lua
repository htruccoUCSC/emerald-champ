-- Pokemon Emerald External AI Bridge for BizHawk
-- Reads addresses from comm_out.txt, then polls game memory.

local COMM_FILE_IN = "comm_in.txt"
local COMM_FILE_OUT = "comm_out.txt"

local EXT_CTRL_STATE_IDLE = 0
local EXT_CTRL_STATE_WAITING = 1
local EXT_CTRL_STATE_DONE = 2

local address = nil        -- gExternalControl
local stateAddr = nil      -- gExternalBattleState
local BATTLE_STATE_SIZE = 456  -- must match EXT_BATTLE_STATE_SIZE in C

-- Offsets within the gExternalControl struct (must match C struct layout)
local OFFSET_STATE            = 0   -- u8
local OFFSET_ACTION           = 1   -- u8
local OFFSET_INDEX            = 2   -- u16
local OFFSET_TARGET           = 4   -- u8
local OFFSET_NUM_VALID_MOVES  = 5   -- u8
local OFFSET_MOVE_IDS         = 6   -- u16[4] (8 bytes)
local OFFSET_MOVE_PP          = 14  -- u8[4]
local OFFSET_NUM_VALID_SWITCH = 18  -- u8
local OFFSET_VALID_SWITCH     = 19  -- u8[5]
local OFFSET_SWITCH_SPECIES   = 24  -- u16[5] (10 bytes)
-- Trainer items (offset 34)
local OFFSET_TRAINER_ITEMS    = 34  -- u16[4] (8 bytes)
local OFFSET_NUM_TRAINER_ITEMS = 42 -- u8
-- Double battle targeting info (offset 43)
local OFFSET_IS_DOUBLE         = 43  -- u8
local OFFSET_FIELD_SPECIES     = 44  -- u16[4] (8 bytes)
local OFFSET_ACTIVE_BATTLER_ID = 52  -- u8
local OFFSET_MOVE_TARGETS_TYPE = 53  -- u8[4]


function read_file(filename)
    local f = io.open(filename, "r")
    if f then
        local content = f:read("*all")
        f:close()
        return content
    end
    return nil
end

function write_file(filename, data)
    local f = io.open(filename, "w")
    if f then
        f:write(data)
        f:close()
    end
end

function split(s, delimiter)
    local result = {}
    for match in (s..delimiter):gmatch("(.-)"..delimiter) do
        table.insert(result, match)
    end
    return result
end

-- Read a block of raw bytes as space-separated decimal values
function read_byte_block(addr, size)
    local parts = {}
    for i = 0, size - 1 do
        parts[#parts + 1] = tostring(memory.read_u8(addr + i, "System Bus"))
    end
    return table.concat(parts, " ")
end

console.log("Starting External AI Bridge...")
console.log("Waiting for Python script to provide memory addresses...")

while true do
    -- 1. Read address or decisions from Python
    local out_content = read_file(COMM_FILE_OUT)
    if out_content ~= nil and out_content ~= "" then
        local parts = split(out_content, " ")

        if parts[1] == "ADDR" and parts[2] ~= nil then
            local hex_str = parts[2]:gsub("0x", "")
            address = tonumber(hex_str, 16)
            if address ~= nil then
                console.log(string.format("Registered gExternalControl at: 0x%X", address))
            else
                console.log("Failed to parse address: " .. tostring(parts[2]))
            end
            -- Check for second address (gExternalBattleState)
            if parts[3] ~= nil then
                local hex_str2 = parts[3]:gsub("0x", "")
                stateAddr = tonumber(hex_str2, 16)
                if stateAddr ~= nil then
                    console.log(string.format("Registered gExternalBattleState at: 0x%X", stateAddr))
                end
            end
            write_file(COMM_FILE_OUT, "") -- clear to acknowledge
        end

        if parts[1] == "DECISION" and address ~= nil then
            local action = tonumber(parts[2])
            local index = tonumber(parts[3])
            local target = tonumber(parts[4])

            -- Write decision to memory
            memory.write_u8(address + OFFSET_ACTION, action, "System Bus")
            memory.write_u16_le(address + OFFSET_INDEX, index, "System Bus")
            memory.write_u8(address + OFFSET_TARGET, target, "System Bus")

            -- Set state to DONE (2) so the game proceeds
            memory.write_u8(address + OFFSET_STATE, EXT_CTRL_STATE_DONE, "System Bus")
            console.log(string.format("Injected Decision: Action=%d, Index=%d, Target=%d", action, index, target))

            write_file(COMM_FILE_OUT, "") -- clear to acknowledge
            write_file(COMM_FILE_IN, "IDLE") -- Python can wait again
        end
    end

    -- 2. Check game state if we have the address
    if address ~= nil then
        local state = memory.read_u8(address + OFFSET_STATE, "System Bus")

        if state == EXT_CTRL_STATE_WAITING then
            -- Read validity data from expanded struct
            local in_content = read_file(COMM_FILE_IN)
            if in_content == nil or not in_content:find("^WAITING") then
                local numMoves = memory.read_u8(address + OFFSET_NUM_VALID_MOVES, "System Bus")
                local m0 = memory.read_u16_le(address + OFFSET_MOVE_IDS + 0, "System Bus")
                local m1 = memory.read_u16_le(address + OFFSET_MOVE_IDS + 2, "System Bus")
                local m2 = memory.read_u16_le(address + OFFSET_MOVE_IDS + 4, "System Bus")
                local m3 = memory.read_u16_le(address + OFFSET_MOVE_IDS + 6, "System Bus")
                local pp0 = memory.read_u8(address + OFFSET_MOVE_PP + 0, "System Bus")
                local pp1 = memory.read_u8(address + OFFSET_MOVE_PP + 1, "System Bus")
                local pp2 = memory.read_u8(address + OFFSET_MOVE_PP + 2, "System Bus")
                local pp3 = memory.read_u8(address + OFFSET_MOVE_PP + 3, "System Bus")
                local numSwitches = memory.read_u8(address + OFFSET_NUM_VALID_SWITCH, "System Bus")
                local sw = {}
                local sp = {}
                for si = 0, 4 do
                    sw[si] = memory.read_u8(address + OFFSET_VALID_SWITCH + si, "System Bus")
                    sp[si] = memory.read_u16_le(address + OFFSET_SWITCH_SPECIES + si * 2, "System Bus")
                end
                -- Read trainer items
                local numItems = memory.read_u8(address + OFFSET_NUM_TRAINER_ITEMS, "System Bus")
                local items = {}
                for ii = 0, 3 do
                    items[ii] = memory.read_u16_le(address + OFFSET_TRAINER_ITEMS + ii * 2, "System Bus")
                end
                -- Read double battle targeting info
                local isDouble = memory.read_u8(address + OFFSET_IS_DOUBLE, "System Bus")
                local activeBattlerId = memory.read_u8(address + OFFSET_ACTIVE_BATTLER_ID, "System Bus")
                local fieldSp = {}
                for fi = 0, 3 do
                    fieldSp[fi] = memory.read_u16_le(address + OFFSET_FIELD_SPECIES + fi * 2, "System Bus")
                end
                local mt = {}
                for mi = 0, 3 do
                    mt[mi] = memory.read_u8(address + OFFSET_MOVE_TARGETS_TYPE + mi, "System Bus")
                end

                -- Build the decision-data portion
                local msg = string.format("WAITING %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                    numMoves,
                    m0, pp0, m1, pp1, m2, pp2, m3, pp3,
                    numSwitches, sw[0], sp[0], sw[1], sp[1], sw[2], sp[2], sw[3], sp[3], sw[4], sp[4],
                    numItems, items[0], items[1], items[2], items[3],
                    isDouble, activeBattlerId, fieldSp[0], fieldSp[1], fieldSp[2], fieldSp[3],
                    mt[0], mt[1], mt[2], mt[3])

                -- Append full battle state if address is known
                if stateAddr ~= nil then
                    msg = msg .. " STATE " .. read_byte_block(stateAddr, BATTLE_STATE_SIZE)
                end

                write_file(COMM_FILE_IN, msg)
            end
        elseif state == EXT_CTRL_STATE_IDLE then
            -- Tell Python we are idle
            local in_content = read_file(COMM_FILE_IN)
            if in_content ~= "IDLE" then
                write_file(COMM_FILE_IN, "IDLE")
            end
        end
    end

    emu.frameadvance()
end