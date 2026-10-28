// Gameplay commands for the test harness (docs/testing.md "Harness commands"): they call the game's own functions
// directly, no simulated mouse or keyboard, so an unattended background run can kill a boss, talk to an NPC, set a
// quest bit, create an item with chosen stats, craft in the cube and read the result.
//
// Only active while mxl-testharness.txt sits next to the DLL (testharness.cpp installs it). A line "h <verb> ..." coming
// through the harness console mailbox is routed here on the UI thread. Server-side verbs are queued and run on the game
// thread inside the frame hook (goblins.cpp calls HarnessGameFrame after 0x406550); client-side verbs (menu) run on the
// UI thread. Output goes to mxl-testharness-console.txt as "h: ..." lines, the last one of a command is
// "h: <verb> OK" or "h: <verb> FAIL <reason>".
#include "harness_cmds_logic.h"

#include "buff_icons.h"
#include "client_messages.h"
#include "collide_types.h"
#include "craft_flags.h"
#include "d2r.h"
#include "dungeon_lockout.h"
#include "engine_gaps.h"
#include "sound_guard.h"
#include "hardcore_death.h"
#include "translation_guard.h"
#include "render_pool.h"
#include "required_level.h"
#include "teleport.h"
#include "engine_gaps_logic.h"
#include "gamble_logic.h"
#include "vendor_stock.h"
#include "goblins.h"
#include "hirelings.h"
#include "hirelings_logic.h"
#include "info_panels.h"
#include "stash_pages.h"
#include "mxl_hirelings.h"
#include "cooldowns.h"
#include "no_corpse.h"
#include "item_events.h"
#include "item_spells.h"
#include "npc_actions.h"
#include "item_gen.h"
#include "mana_costs.h"
#include "map_memory.h"
#include "level_types.h"
#include "monster_looks.h"
#include "monster_rules.h"
#include "skill_damage.h"
#include "skill_starts.h"
#include "sigma_skills.h"
#include "skill_tree.h"
#include "mxl_skill_flags.h"
#include "quests_act1.h"
#include "stat_columns.h"
#include "strings.h"
#include "strings_probe.h"
#include "testharness.h"
#include "tooltip_probe.h"
#include "travel.h"
#include "travel_logic.h"
#include "waypoints.h"
#include "waypoints_logic.h"

#include <D2RLPlugin/api.h>

#define NOMINMAX
#include <windows.h>
#include <intrin.h>

#include <atomic>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <thread>

namespace {

using d2r::Game;
using d2r::Unit;

uint64_t g_base = 0;
volatile LONG g_ready = 0;
volatile LONG g_frames = 0, g_lastGame = 0;
volatile LONG g_playerId = 0;  // unit id of the player the last server frame saw (client verbs read their client copy)

// --- addresses (docs/d2r-addresses.md; the ones not listed there were read from the Ghidra decompile this session) ---
constexpr uint64_t RvaGetStat = 0x2f5020;       // (unit, stat, layer)
constexpr uint64_t RvaSetStat = 0x2f7d10;       // (unit, stat, value, layer)
constexpr uint64_t RvaPlayerData = 0x34b240;    // (player) -> player data; +0x40 + difficulty * 8 = quest record
constexpr uint64_t RvaQuestTest = 0x325c50;     // (record, quest, bit)
constexpr uint64_t RvaQuestSet = 0x325c00;
constexpr uint64_t RvaQuestClear = 0x325990;
constexpr uint64_t RvaWaypointSet = 0x3d6890;   // (record, number)
constexpr uint64_t RvaWaypointTest = 0x3d6930;  // (record, number) -> bit
constexpr uint64_t RvaWaypointSend = 0x4812c0;  // (client, record): packet 0x63, the client opens its waypoint panel
constexpr uint64_t RvaWaypointBits = 0x2389010; // 112 x {u16 word, u16 mask}
constexpr uint64_t RvaClientQuests = 0x10f180;  // () -> the client's quest record (the waypoint panel tests its tab-unlock quests there)
constexpr uint64_t RvaUnitId = 0x34a330;        // (unit, file, line)
constexpr uint64_t RvaUnitClass = 0x349860;     // (unit, file, line)
constexpr uint64_t RvaUnitMode = 0x34ab60;
constexpr uint64_t RvaUnitRoom = 0x34b440;
constexpr uint64_t RvaRoomLevel = 0x2efc10;
constexpr uint64_t RvaPortalLevel = 0x34ad40;   // (portal object) -> destination level (word)
constexpr uint64_t RvaClientUnit = 0x484c90;    // (client, 0) -> player unit
constexpr uint64_t RvaNpcRecord = 0x3971a0;     // (dataFlag, class) -> NPC table row or null
constexpr uint64_t RvaDistance = 0x325140;      // (unit, unit) -> distance
constexpr uint64_t RvaKill = 0x44db20;          // (game, victim, killer unit, 1): the unit death function
constexpr uint64_t RvaAddExperience = 0x44f2e0; // (game, unit, old level, amount): adds stat 13 and runs the level-ups (items_ext.cpp)
constexpr uint64_t RvaSpawn = 0x4929e0;         // (game, room, x, y, class, 1, radius, 0, 0)
constexpr uint64_t RvaInRoom = 0x38dfb0;        // (room, x, y)
constexpr uint64_t RvaTravel = 0x4f2e40;        // (game, player, level, 0): the NPC travel / waypoint warp
constexpr uint64_t RvaMove = 0x491ca0;          // (game, unit, 0, x, y, 0, 0)
constexpr uint64_t RvaFreeSpot = 0x517f90;
constexpr uint64_t RvaPacketTable = 0x1d2a790;  // server packet handlers: (game, player, packet, size)
constexpr uint64_t RvaInventory = 0x34a360;     // (unit, file, line)
constexpr uint64_t RvaInvFirst = 0x388c10;
constexpr uint64_t RvaInvNext = 0x38aba0;
constexpr uint64_t RvaItemLevel = 0x36ccf0;     // (item) -> item level (item data +0x38, at least 1; 0x3730d0 reads +0x40, another field)
constexpr uint64_t RvaItemPage = 0x36cfe0;      // (item) -> page byte (0 inventory, 3 cube, 4 stash)
constexpr uint64_t RvaItemLocation = 0x382d20;  // (int32 location[4], item): unit id, page, packed x/y
constexpr uint64_t RvaItemRecord = 0x314110;    // (dataFlag, class id)
constexpr uint64_t RvaItemByCode = 0x314070;    // (dataFlag, code, &class id) -> record
constexpr uint64_t RvaDefaultIlvl = 0x43e8a0;   // (player, 0)
constexpr uint64_t RvaMakeItem = 0x43d530;
constexpr uint64_t RvaMaxDurability = 0x2f4b60;
constexpr uint64_t RvaSetStatItem = 0x2f7940;   // (item, stat, value, layer)
constexpr uint64_t RvaItemStatList = 0x3d5230;  // (owner, item, state, flags) -> the item's stat list of those flags, made if missing
constexpr uint64_t RvaStatListAdd = 0x2f3330;   // (dataFlag, list, stat, value, layer): adds to the stat on that list
constexpr int32_t MagicStatListFlag = 0x40;     // the item's magic property list: the one the save writes (item_spells.cpp, items_ext.cpp)
constexpr uint64_t RvaLocInit = 0x382e10;       // (loc*, page, packed xy)
constexpr uint64_t RvaInvRecord = 0x34a410;     // (player, page kind, expansion)
constexpr uint64_t RvaFindSpot = 0x3865b0;      // (inventory, item, record, &x, &y, 0) -> found
constexpr uint64_t RvaPlace = 0x471500;         // (player, loc*, ids*, count, 0)
constexpr uint64_t RvaSendItem = 0x535f60;
constexpr uint64_t RvaIdentifyHook = 0x46e8c0;  // (game, player, item, 0)
constexpr uint64_t RvaAfterPlace = 0x3e2b61c;   // (item, player) -> nonzero: re-check equipment
constexpr uint64_t RvaRecheck = 0x470c90;       // (game, player, 0, 0)
constexpr uint64_t RvaDropFlags = 0x36d8f0;     // (item, flags, 0)
constexpr uint64_t RvaGround1 = 0x36de20, RvaGround2 = 0x36d730, RvaGround3 = 0x34e5f0, RvaGround4 = 0x34e210, RvaGround5 = 0x34e280;
constexpr uint64_t RvaUnitXY = 0x34a040;        // (unit, int32 xy[2])
constexpr uint64_t RvaGroundSpot = 0x43de10;    // (game, room, xy, &out, 1)
constexpr uint64_t RvaGroundDrop = 0x43dd00;    // (game, player, item, room, x, y)
constexpr uint64_t RvaSearch = 0x529090;        // (int* result, game, player, out)
constexpr uint64_t RvaCubeRecord = 0x3e3f60;    // (dataFlag, index)
constexpr uint64_t RvaCubeExec = 0x5269c0;      // (game, player, record, ctx)
constexpr uint64_t RvaUseCheck = 0x5817f0;      // (game, player, item, target)
constexpr uint64_t RvaUseItem = 0x581680;
constexpr uint64_t RvaSpellTable = 0x236fe30;   // 12 bytes per pSpell, flag (1 = not used up) at +8
constexpr uint64_t RvaSetByte5c = 0x36dea0;
constexpr uint64_t RvaFreeItem = 0x43ec10;      // (game, item)
constexpr uint64_t RvaInvChange = 0x472590;     // (player, adds, removes, addIds, removeIds, nAdds, nRemoves, 0)
constexpr uint64_t RvaStatsChanged = 0x34dbe0;  // (unit, 1)
constexpr uint64_t RvaUnitPosition = 0x34a110;
constexpr uint64_t RvaItemByte54 = 0x36ca10;
constexpr uint64_t RvaMoveBlocked = 0x350a20;   // (unit, x, y, mask)
// player actions (lane harness-cast; D2Game PlrMsg.cpp handlers 0x4ac050.. read from the Ghidra decompile)
constexpr uint64_t RvaSkillById = 0x33dcd0;     // (unit, skill id, owner item id or -1) -> Skill* or null (list at unit+0x100)
constexpr uint64_t RvaLeftSkill = 0x34a540;     // (unit) -> Skill* on the left button
constexpr uint64_t RvaRightSkill = 0x34b400;    // (unit) -> Skill* on the right button
constexpr uint64_t RvaAddSkillLevel = 0x438670; // (version byte, unit, skill id): one skill point (cost from stat 5) -> 1 / 0
constexpr uint64_t RvaCastAtPoint = 0x4fdb40;   // (game, unit, x, y, 1, Skill*): packets 5 / 0xc call it with the active skill
constexpr uint64_t RvaCastAtUnit = 0x4f8de0;    // (game, unit, target type, target id, Skill*, 1, shift): packets 6 / 7 / 0xd / 0xe
constexpr uint64_t RvaBodyLoc = 0x382df0;       // (int32 loc[4], body location 1-12)
constexpr uint64_t RvaSkillList = 0x34b6e0;     // (unit) -> list head: first Skill* at +0, Skill +8 = next, +0x10 skill mode, +0x40 base level
constexpr uint64_t RvaSkillUsable = 0x33f360;   // (unit, Skill*) -> 0 usable; 1 mana / cooldown, 2 requirements, 3 invalid, 7 no level...
constexpr uint64_t RvaPlayerAction = 0x42d2c0;  // (game, unit, Skill* or null, mode, x, y, 0, 0): what the walk / cast packets end in
constexpr uint64_t RvaPlayerBusy = 0x4249f0;    // (unit): nonzero blocks skill use (item on the cursor / trade)
constexpr uint64_t RvaDeadCheck = 0x34c2c0;     // (unit) -> 1 dead / dying
constexpr uint64_t RvaPosCheck = 0x4fe1f0;      // (unit, x, y, tolerance) -> 0 when the unit is within the tolerance of x,y
constexpr uint64_t RvaPathDistance = 0x325370;  // (unit, x, y) -> distance used by the walk packet check (<= 15 accepted)
constexpr uint64_t RvaUnitClientOf = 0x48fde0;  // (unit) -> client
constexpr uint64_t RvaMonsterUseSkill = 0x4a7bc0;  // (game, monster, mode < 0x10, skill id, target unit, x, y, 0): the AI's skill use -> 1 started
constexpr uint64_t RvaUnitHasState = 0x3351b0;     // (unit, state) -> non-zero when set
// client
constexpr uint64_t RvaClientFind = 0x9a5d0;     // (id, type) -> client unit
constexpr uint64_t RvaMenuRecord = 0x113990;    // (npc unit) -> row index in the NPC menu table
constexpr uint64_t RvaMenuOpenFlag = 0x2a486a4, RvaMenuNpcValid = 0x2a48760, RvaMenuNpcId = 0x2a4875c, RvaMenuNpcClass = 0x2a48764;
constexpr uint64_t RvaMenuTable = 0x2a48830, RvaMenuCount = 0x2a48838;
// offsets
constexpr int GameClients = 0x138, ClientNext = 0x628, ClientState = 0x04, GameFrame = 0x170, GameDifficulty = 0x104;
constexpr int HashPlayers = 0x446, HashMonsters = 0x4c6, HashItems = 0x5c6, HashObjects = 0x546, HashMissiles = 0x646;  // game + (base + (id & 0x7f)) * 8
constexpr int UnitNextInHash = 0x158, UnitClass = 0x04, UnitId = 0x08, UnitMode = 0x0c;
constexpr int StatLife = 6, StatMana = 8, StatLevel = 12, StatGold = 14, StatGoldBank = 15, StatDurability = 0x48;

using GetStatFn = int32_t (*)(Unit*, int32_t, int32_t);
using SetStatFn = void (*)(Unit*, int32_t, int32_t, int32_t);
using PlayerDataFn = uint8_t* (*)(Unit*);
using QuestFn = int32_t (*)(void*, int32_t, int32_t);
using ClientQuestsFn = void* (*)();
using WaypointFn = int32_t (*)(void* record, int32_t number);
using WaypointSendFn = void (*)(void* client, void* record);
using UnitIdFn = uint32_t (*)(Unit*, const char*, int32_t);
using UnitClassFn = int32_t (*)(Unit*, const char*, int32_t);
using UnitModeFn = int32_t (*)(Unit*);
using UnitRoomFn = void* (*)(Unit*);
using RoomLevelFn = int32_t (*)(void*);
using PortalLevelFn = uint16_t (*)(Unit*);
using ClientUnitFn = Unit* (*)(void*, int32_t);
using NpcRecordFn = void* (*)(uint32_t, int32_t);
using DistanceFn = uint32_t (*)(Unit*, Unit*);
using KillFn = void (*)(Game*, Unit*, Unit*, int32_t);
using AddExperienceFn = void (*)(Game*, Unit*, int32_t, int32_t);
using SpawnFn = Unit* (*)(Game*, void*, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t, uint16_t);
using InRoomFn = void* (*)(void*, int32_t, int32_t);
using TravelFn = void (*)(Game*, Unit*, int32_t, int32_t);
using MoveFn = int64_t (*)(Game*, Unit*, int32_t, int32_t, int32_t, int32_t, int32_t);
using FreeSpotFn = void (*)(Game*, void*, int32_t*, int32_t, int32_t, void**, int64_t, int32_t);
using PacketFn = void (*)(Game*, Unit*, const uint8_t*, int32_t);
using InventoryFn = void* (*)(Unit*, const char*, int32_t);
using InvFirstFn = Unit* (*)(void*);
using InvNextFn = Unit* (*)(Unit*);
using ItemByteFn = uint8_t (*)(Unit*);
using ItemLevelFn = uint32_t (*)(Unit*);
using ItemLocationFn = int32_t* (*)(int32_t*, Unit*);
using ItemRecordFn = const uint8_t* (*)(uint32_t, int32_t);
using ItemByCodeFn = const uint8_t* (*)(uint32_t, uint32_t, int32_t*);
using DefaultIlvlFn = int32_t (*)(Unit*, int32_t);
using MakeItemFn = Unit* (*)(Unit*, int32_t, Game*, int32_t, int64_t, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t);
using ItemStatFn = int32_t (*)(Unit*);
using SetItemStatFn = void (*)(Unit*, int32_t, int32_t, int32_t);
using LocInitFn = int32_t* (*)(int32_t*, int32_t, int32_t);
using InvRecordFn = int32_t (*)(Unit*, int32_t, int32_t);
using FindSpotFn = int32_t (*)(void*, Unit*, int32_t, uint16_t*, uint16_t*, int64_t);
using PlaceFn = uint8_t (*)(Unit*, int32_t*, uint32_t*, uint64_t, int64_t);
using SendItemFn = void (*)(Game*, Unit*, Unit*, int32_t, int32_t, int32_t, int32_t, int32_t, int32_t);
using IdentifyHookFn = void (*)(Game*, Unit*, Unit*, int32_t);
using AfterPlaceFn = int32_t (*)(Unit*, Unit*);
using RecheckFn = void (*)(Game*, Unit*, int32_t, int32_t);
using DropFlagsFn = void (*)(Unit*, int32_t, int32_t);
using ByteSetFn = void (*)(Unit*, int32_t);
using UnitXYFn = void (*)(Unit*, int32_t*);
using GroundSpotFn = void* (*)(Game*, void*, int32_t*, int32_t*, int32_t);
using GroundDropFn = void (*)(Game*, Unit*, Unit*, void*, int32_t, int32_t);
using SearchFn = void (*)(int32_t*, Game*, Unit*, void*);
using CubeRecordFn = const uint8_t* (*)(uint32_t, int32_t);
using CubeExecFn = Unit* (*)(Game*, Unit*, const uint8_t*, void*);
using UseFn = uint64_t (*)(Game*, Unit*, Unit*, Unit*);
using FreeItemFn = void (*)(Game*, Unit*);
using InvChangeFn = uint8_t (*)(Unit*, int32_t*, int32_t*, uint32_t*, uint32_t*, uint64_t, uint64_t, uint8_t);
using StatsChangedFn = void (*)(Unit*, int32_t);
using ItemStatListFn = void* (*)(Unit*, Unit*, int32_t, int32_t);
using StatListAddFn = void (*)(uint32_t, void*, int32_t, int32_t, int32_t);
using UnitPositionFn = uint32_t (*)(Unit*);
using BlockedFn = int32_t (*)(Unit*, int32_t, int32_t, int32_t);
using SkillByIdFn = uint8_t* (*)(Unit*, int32_t, int32_t);
using ActiveSkillFn = uint8_t* (*)(Unit*);
using AddSkillFn = int32_t (*)(uint32_t, Unit*, uint32_t);
using CastPointFn = int32_t (*)(Game*, Unit*, uint32_t, uint32_t, uint32_t, void*);
using CastUnitFn = void (*)(Game*, Unit*, uint32_t, uint32_t, void*, uint32_t, uint32_t);
using BodyLocFn = int32_t* (*)(int32_t*, int32_t);
using SkillListFn = uint8_t** (*)(Unit*);
using SkillUsableFn = int32_t (*)(Unit*, void*);
using PlayerActionFn = int64_t (*)(Game*, Unit*, void*, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t);
using PlayerBusyFn = int32_t (*)(Unit*);
using DeadCheckFn = int32_t (*)(Unit*);
using PosCheckFn = int32_t (*)(Unit*, uint32_t, uint32_t, int32_t);
using PathDistanceFn = int32_t (*)(Unit*, int32_t, int32_t);
using UnitClientFn = void* (*)(Unit*);
using MonsterUseSkillFn = int64_t (*)(Game*, Unit*, uint32_t, int32_t, Unit*, int32_t, int32_t, uint8_t);
using UnitHasStateFn = uint64_t (*)(Unit*, int32_t);
using ClientFindFn = Unit* (*)(uint32_t, int32_t);
using MenuRecordFn = int32_t (*)(Unit*);
using MenuHandlerFn = uint8_t (*)(uint8_t);

template <typename F>
auto Fn(uint64_t rva) noexcept -> F {
	return reinterpret_cast<F>(g_base + rva);
}

// --- output -----------------------------------------------------------------------------------------------------
void Out(const char* fmt, ...) noexcept {
	char body[400];
	va_list ap;
	va_start(ap, fmt);
	std::vsnprintf(body, sizeof(body), fmt, ap);
	va_end(ap);
	char line[420];
	std::snprintf(line, sizeof(line), "h: %s", body);
	HarnessEcho(line);
}

struct Ctx {
	Game* game = nullptr;
	Unit* player = nullptr;
	uint32_t dataFlag = 2;
	char verb[24] = "";
	char why[160] = "";
};

auto Fail(Ctx* c, const char* fmt, ...) noexcept -> bool {
	va_list ap;
	va_start(ap, fmt);
	std::vsnprintf(c->why, sizeof(c->why), fmt, ap);
	va_end(ap);
	return false;
}

auto TypeOf(const Unit* u) noexcept -> int32_t { return d2r::At<int32_t>(u, d2r::UnitType); }

auto SkillIdOf(const uint8_t* skill) noexcept -> int;  // defined with the player actions below
void PrintMissiles(Ctx* c) noexcept;

auto FindPlayer(Game* game) noexcept -> Unit* {
	int guard = 0;
	for (auto* client = d2r::At<uint8_t*>(game, GameClients); client != nullptr && guard < 64;
	     client = d2r::At<uint8_t*>(client, ClientNext), ++guard) {
		if (d2r::At<int32_t>(client, ClientState) != 4) {
			continue;
		}
		Unit* unit = Fn<ClientUnitFn>(RvaClientUnit)(client, 0);
		if (unit != nullptr && TypeOf(unit) == 0) {
			return unit;
		}
	}
	return nullptr;
}

auto QuestRecord(Ctx* c) noexcept -> void* {
	uint8_t* data = Fn<PlayerDataFn>(RvaPlayerData)(c->player);
	if (data == nullptr) {
		return nullptr;
	}
	return d2r::At<void*>(data, 0x40 + static_cast<int>(d2r::At<uint8_t>(c->game, GameDifficulty)) * 8);
}

// The player's waypoint record of the game's difficulty (playerData + 0x58 + difficulty * 8).
auto WaypointRecord(Ctx* c) noexcept -> uint8_t* {
	uint8_t* data = Fn<PlayerDataFn>(RvaPlayerData)(c->player);
	if (data == nullptr) {
		return nullptr;
	}
	return d2r::At<uint8_t*>(data, 0x58 + static_cast<int>(d2r::At<uint8_t>(c->game, GameDifficulty)) * 8);
}

auto Stat(Unit* u, int stat, int layer = 0) noexcept -> int32_t { return Fn<GetStatFn>(RvaGetStat)(u, stat, layer); }

auto IdOf(Unit* u) noexcept -> uint32_t { return d2r::At<uint32_t>(u, UnitId); }
auto ClassOf(Unit* u) noexcept -> int32_t { return d2r::At<int32_t>(u, UnitClass); }
auto ModeOf(Unit* u) noexcept -> int32_t { return d2r::At<int32_t>(u, UnitMode); }
auto IsAlive(Unit* u) noexcept -> bool {
	const int32_t m = ModeOf(u);
	return m != 0 && m != 12;
}

auto DistTo(Unit* a, Unit* b) noexcept -> double {
	int32_t ax = 0, ay = 0, bx = 0, by = 0;
	if (!d2r::UnitXY(a, &ax, &ay) || !d2r::UnitXY(b, &bx, &by)) {
		return 1e9;
	}
	return std::sqrt(static_cast<double>(ax - bx) * (ax - bx) + static_cast<double>(ay - by) * (ay - by));
}

// Calls f(unit) for every unit in one of the game's hash tables (type 1 monsters, 2 objects, 4 items).
template <typename F>
void EachUnit(Game* game, int hashBase, F f) noexcept {
	int guard = 0;
	for (int b = 0; b < 128; ++b) {
		for (auto* u = d2r::At<Unit*>(game, (hashBase + b) * 8); u != nullptr && guard < 20000;
		     u = d2r::At<Unit*>(u, UnitNextInHash), ++guard) {
			f(u);
		}
	}
}

auto NearestMonster(Ctx* c, long long cls, bool npcOnly) noexcept -> Unit* {
	Unit* best = nullptr;
	double bestD = 1e18;
	EachUnit(c->game, HashMonsters, [&](Unit* u) {
		if (TypeOf(u) != 1 || !IsAlive(u) || (cls >= 0 && ClassOf(u) != cls)) {
			return;
		}
		if (npcOnly && Fn<NpcRecordFn>(RvaNpcRecord)(c->dataFlag, ClassOf(u)) == nullptr) {
			return;
		}
		const double d = DistTo(c->player, u);
		if (d < bestD) {
			bestD = d;
			best = u;
		}
	});
	return best;
}

auto FindMonsterById(Ctx* c, uint32_t id) noexcept -> Unit* {
	Unit* found = nullptr;
	EachUnit(c->game, HashMonsters, [&](Unit* u) {
		if (found == nullptr && TypeOf(u) == 1 && IdOf(u) == id) {
			found = u;
		}
	});
	return found;
}

auto ResolveRef(Ctx* c, const char* text) noexcept -> Unit*;  // "player", "merc", "mon:<id>"; defined with the verify verbs

// Items of the player's inventory (all pages: backpack, cube, stash, equipped).
template <typename F>
void EachItemOf(Unit* owner, F f) noexcept {
	void* inv = Fn<InventoryFn>(RvaInventory)(owner, "harness", 0);
	if (inv == nullptr) {
		return;
	}
	int guard = 0;
	Unit* item = Fn<InvFirstFn>(RvaInvFirst)(inv);
	while (item != nullptr && guard++ < 2000) {
		Unit* next = Fn<InvNextFn>(RvaInvNext)(item);
		if (TypeOf(item) == 4) {
			f(item);
		}
		item = next;
	}
}

template <typename F>
void EachItem(Ctx* c, F f) noexcept {
	EachItemOf(c->player, f);
}

auto ItemCode(Ctx* c, Unit* item, char out[5]) noexcept -> void {
	const int32_t cls = Fn<UnitClassFn>(RvaUnitClass)(item, "harness", 0);
	const uint8_t* rec = Fn<ItemRecordFn>(RvaItemRecord)(c->dataFlag, cls);
	hcmd::DwordToCode(rec != nullptr ? d2r::At<uint32_t>(rec, 0x80) : 0x3f3f3f3fU, out);
}

void DescribeItem(Ctx* c, Unit* item) noexcept {
	char code[5];
	ItemCode(c, item, code);
	int32_t loc[8] = {};
	Fn<ItemLocationFn>(RvaItemLocation)(loc, item);
	const auto* data = Fn<uint8_t* (*)(Unit*)>(0x34a500)(item);  // item data: +0 quality, +0x34 unique index
	Out("item id=%u code=%s class=%d page=%d x=%d y=%d qty=%d stat532=%d quality=%d unique=%d body=%d sockets=%d flags=0x%x ilvl=%d", IdOf(item), code,
	    ClassOf(item), static_cast<int>(Fn<ItemByteFn>(RvaItemPage)(item)), loc[2] & 0xffff, (loc[2] >> 16) & 0xffff, Stat(item, 70), Stat(item, 532),
	    data != nullptr ? d2r::At<int32_t>(data, 0) : -1, data != nullptr ? d2r::At<int32_t>(data, 0x34) : -1,
	    loc[0] == 1 ? loc[3] : 0, Stat(item, 194), data != nullptr ? d2r::At<uint32_t>(data, 0x18) : 0U,
	    static_cast<int>(Fn<ItemLevelFn>(RvaItemLevel)(item)));
}

auto FindItemByCode(Ctx* c, uint32_t code, int page) noexcept -> Unit* {
	Unit* found = nullptr;
	EachItem(c, [&](Unit* it) {
		if (found != nullptr) {
			return;
		}
		const uint8_t* rec = Fn<ItemRecordFn>(RvaItemRecord)(c->dataFlag, Fn<UnitClassFn>(RvaUnitClass)(it, "harness", 0));
		if (rec != nullptr && d2r::At<uint32_t>(rec, 0x80) == code &&
		    (page < 0 || Fn<ItemByteFn>(RvaItemPage)(it) == page)) {
			found = it;
		}
	});
	return found;
}

// --- verbs ------------------------------------------------------------------------------------------------------

// Observe the game's own classifiers, not the plugin's replacement helper. Optional coordinates query a loaded room.
auto CmdTown(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long level = 0, x = 0, y = 0;
	void* room = Fn<UnitRoomFn>(RvaUnitRoom)(c->player);
	if (t.n == 2 && hcmd::LowerEq(t.tok[1], "edges")) {
		int32_t px = 0, py = 0;
		if (room == nullptr || !d2r::UnitXY(c->player, &px, &py)) {
			return Fail(c, "town edges: no room");
		}
		// InRoom searches only a room and its immediate neighbours. Walk the live room graph first,
		// otherwise a border two rooms from the waypoint is invisible to this read-only scan.
		void* rooms[512] = {room};
		int roomCount = 1;
		using NearFn = void (*)(void*, void***, uint32_t*);
		for (int i = 0; i < roomCount; ++i) {
			void** neighbours = nullptr;
			uint32_t n = 0;
			Fn<NearFn>(0x2efde0)(rooms[i], &neighbours, &n);
			for (uint32_t j = 0; neighbours != nullptr && j < n && j < 512; ++j) {
				bool seen = neighbours[j] == nullptr;
				for (int k = 0; !seen && k < roomCount; ++k) {
					seen = rooms[k] == neighbours[j];
				}
				if (!seen && roomCount < 512) {
					rooms[roomCount++] = neighbours[j];
				}
			}
		}
		const auto at = [&](int32_t x, int32_t y) -> void* {
			for (int i = 0; i < roomCount; ++i) {
				void* r = rooms[i];
				const int32_t rx = d2r::At<int32_t>(r, 0x80), ry = d2r::At<int32_t>(r, 0x84);
				if (x >= rx && y >= ry && x < rx + d2r::At<int32_t>(r, 0x88) && y < ry + d2r::At<int32_t>(r, 0x8c)) {
					return r;
				}
			}
			return nullptr;
		};
		int count = 0, borders = 0;
		for (int dx = -160; dx <= 160; ++dx) {
			for (int dy = -160; dy <= 160; ++dy) {
				const int32_t ax = px + dx, ay = py + dy;
				void* a = at(ax, ay);
				if (a == nullptr) {
					continue;
				}
				for (int dir = 0; dir < 2; ++dir) {
					const int32_t bx = ax + (dir == 0 ? 1 : 0), by = ay + (dir == 1 ? 1 : 0);
					void* b = at(bx, by);
					const int al = Fn<RoomLevelFn>(RvaRoomLevel)(a);
					const int bl = b != nullptr ? Fn<RoomLevelFn>(RvaRoomLevel)(b) : al;
					if (al == bl) {
						continue;
					}
					using CollideFn = uint32_t (*)(void*, int32_t, int32_t, int32_t, uint32_t);
					const uint32_t ca = Fn<CollideFn>(0x364d50)(a, ax, ay, 1, 0x1c09);
					const uint32_t cb = Fn<CollideFn>(0x364d50)(b, bx, by, 1, 0x1c09);
					if (borders++ < 8) {
						Out("town border ax=%d ay=%d al=%d bx=%d by=%d bl=%d ca=%x cb=%x", ax, ay, al, bx, by, bl, ca, cb);
					}
					if ((ca | cb) == 0 && count++ < 64) {
						Out("town edge ax=%d ay=%d al=%d bx=%d by=%d bl=%d", ax, ay, al, bx, by, bl);
					}
				}
			}
		}
		Out("town edges count=%d borders=%d rooms=%d at=%d,%d", count, borders, roomCount, px, py);
		return true;
	}
	if (t.n == 3 && hcmd::ParseInt(t.tok[1], &x) && hcmd::ParseInt(t.tok[2], &y)) {
		room = room != nullptr ? Fn<InRoomFn>(RvaInRoom)(room, static_cast<int32_t>(x), static_cast<int32_t>(y)) : nullptr;
	} else if (t.n > 2 || (t.n == 2 && !hcmd::ParseInt(t.tok[1], &level))) {
		return Fail(c, "usage: town [level] | town <x> <y>");
	}
	const int32_t roomLevel = room != nullptr ? Fn<RoomLevelFn>(RvaRoomLevel)(room) : -1;
	if (t.n != 2) {
		level = roomLevel;
	}
	const int isTown = Fn<int32_t (*)(int32_t)>(0x2f0780)(static_cast<int32_t>(level));
	const int roomTown = Fn<int32_t (*)(void*)>(0x2f0750)(room);
	Out("town level=%lld istown=%d roomlevel=%d roomtown=%d x=%lld y=%lld", level, isTown, roomLevel, roomTown, x, y);
	return true;
}

auto CmdState(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* p = c->player;
	void* room = Fn<UnitRoomFn>(RvaUnitRoom)(p);
	int32_t x = 0, y = 0;
	d2r::UnitXY(p, &x, &y);
	Out("player id=%u class=%d level=%d life=%d/%d mana=%d area=%d x=%d y=%d mode=%d gold=%d bank=%d difficulty=%d frame=%u stamina=%d maxstamina=%d",
	    IdOf(p), ClassOf(p), Stat(p, StatLevel), Stat(p, StatLife) >> 8, Stat(p, 7) >> 8, Stat(p, StatMana) >> 8,
	    room != nullptr ? Fn<RoomLevelFn>(RvaRoomLevel)(room) : -1, x, y, ModeOf(p), Stat(p, StatGold), Stat(p, StatGoldBank),
	    static_cast<int>(d2r::At<uint8_t>(c->game, GameDifficulty)), d2r::At<uint32_t>(c->game, GameFrame), Stat(p, 10), Stat(p, 11));  // raw, x256: the sprint check reads frame and stamina in one reply
	int items = 0;
	EachItem(c, [&](Unit* it) {
		++items;
		DescribeItem(c, it);
	});
	Out("items %d", items);
	// Player-type units in the game: the character itself, other players, and the corpse of a dead one (D2's corpse is a
	// second player unit in mode 0x11 with the character's name). `corpses` = player units other than this one.
	int players = 0, corpses = 0;
	bool self = false;
	EachUnit(c->game, HashPlayers, [&](Unit* u) {
		if (TypeOf(u) == 0) {
			++players;
			if (u == p) {
				self = true;
			} else if (ModeOf(u) == 17) {
				++corpses;
			}
		}
	});
	long skippedCorpses = 0, skippedPenalties = 0, respawnsHeld = 0, respawns = 0;
	const bool noCorpseOn = NoCorpseCounts(&skippedCorpses, &skippedPenalties, &respawnsHeld, &respawns);
	Out("corpses %d players=%d self=%d | no corpse %s: skipped corpse calls=%ld penalty calls=%ld respawns held=%ld let=%ld xp=%u", corpses,
	    players, self ? 1 : 0, noCorpseOn ? "on" : "off", skippedCorpses, skippedPenalties, respawnsHeld, respawns,
	    static_cast<uint32_t>(Stat(p, 13)));
	// Every body there is on the server: player-type units other than this one in ANY mode (a dead player left as a unit counts),
	// and the corpse list in the character's inventory (what a save writes as the "JM" corpse section). Median: both zero.
	// D2R keeps ten inert player-type units (ids 2-11, no position) next to the character; they are no body, and are counted apart.
	int otherPlayers = 0, hiddenPlayers = 0;
	EachUnit(c->game, HashPlayers, [&](Unit* u) {
		if (TypeOf(u) == 0 && u != p) {
			int32_t ux = 0, uy = 0;
			d2r::UnitXY(u, &ux, &uy);
			if (ux != 0 || uy != 0) {
				++otherPlayers;
			} else {
				++hiddenPlayers;
			}
		}
	});
	unsigned stored[16] = {};
	const int storedCount = StoredCorpseIds(p, stored, 16);
	long pickEnters = 0, pickPicked = 0, pickKept = 0, pickFaults = 0;
	const bool pickupOn = CorpsePickupCounts(&pickEnters, &pickPicked, &pickKept, &pickFaults);
	Out("bodies other=%d stored=%d id0=%u hidden=%d | corpse pickup %s: enters=%ld picked=%ld kept=%ld faults=%ld", otherPlayers, storedCount, stored[0],
	    hiddenPlayers, pickupOn ? "on" : "off", pickEnters, pickPicked, pickKept, pickFaults);
	long cdStarts = 0, cdReduced = 0, cdShared = 0, cdDropped = 0, cdMonsters = 0;
	const bool cooldownsOn = CooldownCounts(&cdStarts, &cdReduced, &cdShared, &cdDropped, &cdMonsters);
	Out("cooldowns %s: starts=%ld reduced=%ld shared=%ld dropped=%ld monsters=%ld", cooldownsOn ? "on" : "off", cdStarts, cdReduced, cdShared, cdDropped,
	    cdMonsters);
	Out("skills left=%d right=%d", SkillIdOf(Fn<ActiveSkillFn>(RvaLeftSkill)(p)), SkillIdOf(Fn<ActiveSkillFn>(RvaRightSkill)(p)));
	PrintMissiles(c);
	int mons = 0;
	EachUnit(c->game, HashMonsters, [&](Unit* u) {
		if (TypeOf(u) == 1 && IsAlive(u) && DistTo(p, u) < 40 && mons < 60) {
			++mons;
			int32_t mx = 0, my = 0;
			d2r::UnitXY(u, &mx, &my);
			void* monRoom = Fn<UnitRoomFn>(RvaUnitRoom)(u);
			Out("mon id=%u class=%d mode=%d dist=%.0f npc=%d life=%d/%d mx=%d my=%d area=%d", IdOf(u), ClassOf(u), ModeOf(u), DistTo(p, u),
			    Fn<NpcRecordFn>(RvaNpcRecord)(c->dataFlag, ClassOf(u)) != nullptr ? 1 : 0, Stat(u, StatLife) >> 8, Stat(u, 7) >> 8, mx, my,
			    monRoom != nullptr ? Fn<RoomLevelFn>(RvaRoomLevel)(monRoom) : -1);
		}
	});
	int objs = 0;
	EachUnit(c->game, HashObjects, [&](Unit* u) {
		// portals are always listed (a big town has more than 40 objects within 30 tiles, and the hash order is not by distance)
		const int32_t ocls = TypeOf(u) == 2 ? ClassOf(u) : -1;
		const bool portal = ocls == 59 || ocls == 60 || ocls == 600;
		if (TypeOf(u) == 2 && DistTo(p, u) < 30 && (objs < 40 || portal)) {
			++objs;
			int32_t ox = 0, oy = 0;
			d2r::UnitXY(u, &ox, &oy);
			if (portal) {  // portals: where they lead (D2R level id)
				Out("obj id=%u class=%d mode=%d dist=%.0f at %d,%d dest=%d", IdOf(u), ocls, ModeOf(u), DistTo(p, u), ox, oy,
				    static_cast<int>(Fn<PortalLevelFn>(RvaPortalLevel)(u)));
			} else {
				Out("obj id=%u class=%d mode=%d dist=%.0f at %d,%d", IdOf(u), ocls, ModeOf(u), DistTo(p, u), ox, oy);
			}
		}
	});
	char goblins[160] = "";
	GoblinsStatus(goblins, sizeof(goblins));
	int refused = 0, started = 0;
	DungeonLockoutCounts(&refused, &started);
	char sounds[96] = "";
	SoundGuardStatus(sounds, sizeof(sounds));
	Out("plugin goblins: %s | lockout refused=%d clocks=%d | tower skips=%d | sound guard: %s", goblins, refused, started, QuestsTowerSkips(), sounds);
	const auto* b = reinterpret_cast<const uint8_t*>(g_base);
	Out("npcmenu open=%u npc=%u class=%u rows=%u", *reinterpret_cast<const uint32_t*>(b + RvaMenuOpenFlag),
	    *reinterpret_cast<const uint32_t*>(b + RvaMenuNpcId), static_cast<unsigned>(*reinterpret_cast<const uint16_t*>(b + RvaMenuNpcClass)),
	    *reinterpret_cast<const uint32_t*>(b + RvaMenuCount));
	return true;
}

auto CmdQuest(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long q = 0, bit = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &q)) {
		return Fail(c, "usage: quest <id> <bit>|dump set|clear|get");
	}
	void* rec = QuestRecord(c);
	if (rec == nullptr) {
		return Fail(c, "no quest record");
	}
	if (hcmd::LowerEq(t.tok[2], "dump")) {
		char bits[17] = {};
		for (int i = 0; i < 16; ++i) {
			bits[i] = Fn<QuestFn>(RvaQuestTest)(rec, static_cast<int>(q), i) != 0 ? '1' : '0';
		}
		Out("quest %lld bits0-15 %s", q, bits);
		return true;
	}
	if (t.n < 4 || !hcmd::ParseInt(t.tok[2], &bit) || bit < 0 || bit > 15) {
		return Fail(c, "usage: quest <id> <bit 0-15> set|clear|get");
	}
	if (hcmd::LowerEq(t.tok[3], "set")) {
		Fn<QuestFn>(RvaQuestSet)(rec, static_cast<int>(q), static_cast<int>(bit));
	} else if (hcmd::LowerEq(t.tok[3], "clear")) {
		Fn<QuestFn>(RvaQuestClear)(rec, static_cast<int>(q), static_cast<int>(bit));
	} else if (!hcmd::LowerEq(t.tok[3], "get")) {
		return Fail(c, "quest: set, clear or get");
	}
	Out("quest %lld bit %lld = %d", q, bit, Fn<QuestFn>(RvaQuestTest)(rec, static_cast<int>(q), static_cast<int>(bit)));
	return true;
}

auto CmdFlag(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 0;
	if (t.n < 4 || !hcmd::ParseInt(t.tok[2], &n)) {
		return Fail(c, "usage: flag player|game <n> get|set|clear");
	}
	const bool game = hcmd::LowerEq(t.tok[1], "game");
	if (!game && !hcmd::LowerEq(t.tok[1], "player")) {
		return Fail(c, "flag: player or game");
	}
	if (hcmd::LowerEq(t.tok[3], "set") || hcmd::LowerEq(t.tok[3], "clear")) {
		SetCraftFlag(c->player, static_cast<int>(n), game, hcmd::LowerEq(t.tok[3], "set"));
	} else if (!hcmd::LowerEq(t.tok[3], "get")) {
		return Fail(c, "flag: set, clear or get");
	}
	Out("flag %s %lld = %d", game ? "game" : "player", n, CraftFlagTest(c->player, static_cast<int>(n), game) ? 1 : 0);
	return true;
}

// `gameflag <word> <bit> [get|set|clear]`: D2R's own per-game flag bits (the Cow portal's "opened in this game" is word 4 bit 0xb).
// The game's flags are a bit record like a quest record (game +0x21d8 -> +0x10): get and set are the quest bit functions (`0x325c50`,
// `0x325c00`), clear is the byte arithmetic of the game's bit set (0xa1ba30) with the mask inverted.
auto CmdGameFlag(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long word = 0;
	long long bit = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &word) || !hcmd::ParseInt(t.tok[2], &bit) || word < 0 || bit < 0 || bit > 15) {
		return Fail(c, "usage: gameflag <word> <bit 0-15> [get|set|clear]");
	}
	const bool set = t.n > 3 && hcmd::LowerEq(t.tok[3], "set");
	const bool clear = t.n > 3 && hcmd::LowerEq(t.tok[3], "clear");
	if (t.n > 3 && !set && !clear && !hcmd::LowerEq(t.tok[3], "get")) {
		return Fail(c, "gameflag: get, set or clear");
	}
	auto* holder = d2r::At<uint8_t*>(c->game, 0x21d8);
	auto** flags = holder != nullptr ? d2r::At<uint8_t**>(holder, 0x10) : nullptr;
	if (flags == nullptr || *flags == nullptr) {
		return Fail(c, "gameflag: no flag record");
	}
	const auto index = static_cast<uint32_t>(word * 16 + bit);
	if (set) {
		Fn<void (*)(void*, int32_t, int32_t)>(RvaQuestSet)(flags, static_cast<int32_t>(word), static_cast<int32_t>(bit));
	} else if (clear) {
		(*flags)[index >> 3] &= static_cast<uint8_t>(~(1U << (index & 7)));  // the set's table (0x1d996d0) holds 1 << n
	}
	Out("gameflag %lld %lld = %d (byte %u of the record = 0x%02x)", word, bit,
	    Fn<uint64_t (*)(void*, int32_t, int32_t)>(0x325c50)(flags, static_cast<int32_t>(word), static_cast<int32_t>(bit)) != 0 ? 1 : 0, index >> 3, (*flags)[index >> 3]);
	return true;
}

// `waypoint <level id>|n <number>|all [get|set|clear]`, `waypoint open`, `waypoint tabs`, `waypoint panel`: the player's waypoint bits (the level
// id goes through Median's levels.txt numbers, mxl_waypoints.h), `open` sends the record to the client as the waypoint object
// does (packet 0x63: the client opens its waypoint panel), `tabs` sets the client's own copy of the four tab-unlock quests (7, 15,
// 23, 26: bit 0; the panel shows tab 1 only until the client has them), `panel` prints the plugin's panel table (what the buttons list).
auto CmdWaypoint(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const char* usage = "usage: waypoint <level id>|n <number>|all [get|set|clear] | waypoint open | waypoint tabs | waypoint panel";
	if (t.n < 2) {
		return Fail(c, usage);
	}
	if (hcmd::LowerEq(t.tok[1], "approach")) {
		// Test setup only: load the current level's waypoint room and stand beside
		// its real map object. The test then operates it and sends packet 0x4b.
		void* current = Fn<UnitRoomFn>(RvaUnitRoom)(c->player);
		if (current == nullptr) return Fail(c, "waypoint: no room");
		const int level = Fn<RoomLevelFn>(RvaRoomLevel)(current);
		if (travel::WaypointNumberOfLevel(level) < 0) return Fail(c, "waypoint: none in this level");
		const auto flag = d2r::At<uint8_t>(c->game, 0x106);
		const auto act = Fn<uint8_t (*)(uint32_t, int)>(0x3e2b5c8)(flag, level);
		auto** acts = d2r::At<void**>(c->game, 0x190);
		if (act >= d2r::At<uint64_t>(c->game, 0x198)) return Fail(c, "waypoint: no act");
		int x = 0, y = 0;
		void* room = Fn<void* (*)(uint32_t, void*, int, int, int*, int*, int)>(0x2ef8b0)(flag, acts[act], level, 13, &x, &y, 1);
		if (room == nullptr) return Fail(c, "waypoint: no waypoint room");
		Fn<int64_t (*)(Game*, Unit*, void*, int, int, int, int)>(RvaMove)(c->game, c->player, room, x, y, 0, 0);
		Out("waypoint approach level=%d at %d,%d", level, x, y);
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "tabs")) {
		void* quests = Fn<ClientQuestsFn>(RvaClientQuests)();
		if (quests == nullptr) {
			return Fail(c, "waypoint: no client quest record");
		}
		for (const int q : {7, 15, 23, 26}) {
			Fn<QuestFn>(RvaQuestSet)(quests, q, 0);
		}
		Out("client quests 7, 15, 23, 26 set (reopen the panel)");
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "panel")) {
		char stats[160];
		WaypointPanelStats(stats, sizeof(stats));
		Out("waypoint %s", stats);
		int count = 0;
		const void* entries = nullptr;
		if (WaypointPanelTable(&count, &entries)) {
			for (int i = 0; i < count && i < wp::MaxButtons; ++i) {
				const auto& e = static_cast<const wp::ButtonEntry*>(entries)[i];
				Out("waypoint button %d: level %u other %d", i, e.level, e.other);
			}
		}
		return true;
	}
	uint8_t* rec = WaypointRecord(c);
	if (rec == nullptr) {
		return Fail(c, "no waypoint record");
	}
	if (hcmd::LowerEq(t.tok[1], "open")) {
		void* client = Fn<UnitClientFn>(RvaUnitClientOf)(c->player);
		if (client == nullptr) {
			return Fail(c, "waypoint: no client for the player");
		}
		Fn<WaypointSendFn>(RvaWaypointSend)(client, rec);
		Out("waypoint record sent to the client (the panel opens)");
		return true;
	}
	int first = 0, last = -1;  // the numbers acted on
	long long n = 0;
	int argAt = 2;
	if (hcmd::LowerEq(t.tok[1], "all")) {
		last = wp::RecordBits - 1;
	} else if (hcmd::LowerEq(t.tok[1], "n")) {
		if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &n) || n < 0 || n >= wp::RecordBits) {
			return Fail(c, usage);
		}
		first = last = static_cast<int>(n);
		argAt = 3;
	} else {
		if (!hcmd::ParseInt(t.tok[1], &n)) {
			return Fail(c, usage);
		}
		int found = -1;
		for (const mxl_wp::Level& l : mxl_wp::Levels) {
			if (l.level == n) {
				found = l.number;
			}
		}
		if (found < 0) {
			return Fail(c, "waypoint: that level has no waypoint number (levels.txt)");
		}
		first = last = found;
	}
	int action = 0;  // 0 get, 1 set, 2 clear
	if (t.n > argAt) {
		if (hcmd::LowerEq(t.tok[argAt], "set")) {
			action = 1;
		} else if (hcmd::LowerEq(t.tok[argAt], "clear")) {
			action = 2;
		} else if (!hcmd::LowerEq(t.tok[argAt], "get")) {
			return Fail(c, usage);
		}
	}
	const auto* bits = reinterpret_cast<const uint16_t*>(g_base + RvaWaypointBits);
	int setCount = 0;
	for (int i = first; i <= last; ++i) {
		if (action == 1) {
			Fn<WaypointFn>(RvaWaypointSet)(rec, i);
		} else if (action == 2) {
			*reinterpret_cast<uint16_t*>(rec + 2 * bits[2 * i]) &= static_cast<uint16_t>(~bits[2 * i + 1]);
		}
		setCount += Fn<WaypointFn>(RvaWaypointTest)(rec, i) != 0 ? 1 : 0;
	}
	if (first == last) {
		Out("waypoint number %d = %d", first, setCount);
	} else {
		Out("waypoints set: %d of %d", setCount, last - first + 1);
	}
	return true;
}

auto CmdGold(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 4 && hcmd::LowerEq(t.tok[1], "set")) {
		long long carried = 0, bank = 0;
		if (!hcmd::ParseInt(t.tok[2], &carried) || !hcmd::ParseInt(t.tok[3], &bank)) {
			return Fail(c, "usage: gold get | gold set <carried> <bank>");
		}
		Fn<SetStatFn>(RvaSetStat)(c->player, StatGold, static_cast<int32_t>(carried), 0);
		Fn<SetStatFn>(RvaSetStat)(c->player, StatGoldBank, static_cast<int32_t>(bank), 0);
	} else if (!(t.n >= 2 && hcmd::LowerEq(t.tok[1], "get"))) {
		return Fail(c, "usage: gold get | gold set <carried> <bank>");
	}
	Out("gold carried=%d bank=%d", Stat(c->player, StatGold), Stat(c->player, StatGoldBank));
	return true;
}

auto CmdStat(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long who = 0, stat = 0, layer = 0, value = 0;
	int next = 3;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &stat)) {
		return Fail(c, "usage: stat player|merc|mon:<id>|m<monster id>|<item unit id>|<item code> <stat> [layer] [set <value>] | scan [max layer]");
	}
	const bool scan = t.n > next && hcmd::LowerEq(t.tok[next], "scan");
	if (scan) {
		long long maxLayer = 262143;  // skill id << 6 | level stays below this for ids up to 4095
		if (t.n > next + 1 && !hcmd::ParseInt(t.tok[next + 1], &maxLayer)) {
			return Fail(c, "stat: scan needs a number");
		}
		next = t.n;
		layer = maxLayer;
	}
	if (!scan && t.n > next && !hcmd::LowerEq(t.tok[next], "set")) {
		if (!hcmd::ParseInt(t.tok[next], &layer)) {
			return Fail(c, "stat: layer must be a number");
		}
		++next;
	}
	const bool set = t.n > next && hcmd::LowerEq(t.tok[next], "set");
	if (set && (t.n <= next + 1 || !hcmd::ParseInt(t.tok[next + 1], &value))) {
		return Fail(c, "stat: set needs a number");
	}
	Unit* unit = nullptr;
	hcmd::UnitRef ref;
	if (hcmd::ParseUnitRef(t.tok[1], &ref)) {
		unit = ResolveRef(c, t.tok[1]);
	} else if ((t.tok[1][0] == 'm' || t.tok[1][0] == 'M') && hcmd::ParseInt(t.tok[1] + 1, &who)) {
		unit = FindMonsterById(c, static_cast<uint32_t>(who));  // monsters, e.g. stat m1234 6 (life is stat 6, times 256)
	} else if (hcmd::ParseInt(t.tok[1], &who)) {
		EachItem(c, [&](Unit* it) {
			if (unit == nullptr && IdOf(it) == static_cast<uint32_t>(who)) {
				unit = it;
			}
		});
	} else {
		unit = FindItemByCode(c, hcmd::CodeToDword(t.tok[1]), -1);
	}
	if (unit == nullptr) {
		return Fail(c, "stat: unit not found");
	}
	if (scan) {  // every layer of the stat that reads non-zero: which skill an item property or oskill really carries
		int shown = 0, total = 0;
		for (long long l = 0; l <= layer; ++l) {
			const int32_t v = Stat(unit, static_cast<int>(stat), static_cast<int>(l));
			if (v == 0) {
				continue;
			}
			++total;
			if (shown < 40) {
				Out("scan %s %lld:%lld = %d", t.tok[1], stat, l, v);
				++shown;
			}
		}
		Out("scan %s %lld: %d layers non-zero (up to %lld)", t.tok[1], stat, total, layer);
		return true;
	}
	if (set) {
		Fn<SetStatFn>(RvaSetStat)(unit, static_cast<int>(stat), static_cast<int32_t>(value), static_cast<int>(layer));
	}
	Out("stat %s %lld:%lld = %d", t.tok[1], stat, layer, Stat(unit, static_cast<int>(stat), static_cast<int>(layer)));
	return true;
}

// Packet 0x31 (a dialog line of an NPC was played to its end): u8 id, u8 kind (1 NPC), u16 message, u32 unit id. The server
// answers with quest event 11 (NPC message): Akara's Griswold's Heart, Cain, Jerhyn... react to it.
auto CmdMsg(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = -1, msg = 0;
	if (t.n < 3 || (!hcmd::LowerEq(t.tok[1], "nearest") && !hcmd::ParseInt(t.tok[1], &cls)) || !hcmd::ParseInt(t.tok[2], &msg)) {
		return Fail(c, "usage: msg nearest|<npc class> <message id>");
	}
	Unit* npc = NearestMonster(c, cls, true);
	if (npc == nullptr) {
		return Fail(c, "msg: no such NPC alive in this area");
	}
	uint8_t pkt[8] = {0x31, 1};
	const uint16_t m = static_cast<uint16_t>(msg);
	const uint32_t id = IdOf(npc);
	std::memcpy(pkt + 2, &m, 2);
	std::memcpy(pkt + 4, &id, 4);
	const auto handler = reinterpret_cast<PacketFn>(*reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + 0x31 * 8));
	handler(c->game, c->player, pkt, 8);
	Out("msg npc id=%u class=%d message 0x%x sent", id, ClassOf(npc), static_cast<unsigned>(m));
	return true;
}

// Walk into a portal object, as the click on it does (the portal object's operate function 0x58f680, ctx {game, portal,
// player, 0, class}): `enter nearest` (portal classes 59 town portal, 60 red portal, 600 Median one-way) or `enter <object id>`.
auto CmdEnter(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = -1;
	if (t.n < 2 || (!hcmd::LowerEq(t.tok[1], "nearest") && !hcmd::ParseInt(t.tok[1], &id))) {
		return Fail(c, "usage: enter nearest | enter <portal object id>");
	}
	Unit* portal = nullptr;
	double best = 1e18;
	EachUnit(c->game, HashObjects, [&](Unit* u) {
		const int32_t cls = ClassOf(u);
		const bool match = id >= 0 ? IdOf(u) == static_cast<uint32_t>(id) : (cls == 59 || cls == 60 || cls == 600);
		if (TypeOf(u) == 2 && match && DistTo(c->player, u) < best) {
			best = DistTo(c->player, u);
			portal = u;
		}
	});
	if (portal == nullptr) {
		return Fail(c, "enter: no such portal object");
	}
	int64_t ctx[8] = {reinterpret_cast<int64_t>(c->game), reinterpret_cast<int64_t>(portal), reinterpret_cast<int64_t>(c->player), 0,
	                  ClassOf(portal), 0, 0, 0};
	const int64_t moved = Fn<int64_t (*)(int64_t*)>(0x58f680)(ctx);
	Out("enter portal id=%u class=%d: %s", IdOf(portal), ClassOf(portal), moved != 0 ? "moved" : "refused / failed");
	if (moved == 0) {  // the tests of the handler 0x58f680 that can refuse, in order
		Unit* partner = Fn<Unit* (*)(Game*, Unit*)>(0x490070)(c->game, portal);
		const uint16_t dest = Fn<uint16_t (*)(Unit*)>(0x34ad40)(portal);
		const uint8_t* row = Fn<const uint8_t* (*)(uint8_t, uint16_t)>(0x32c4a0)(d2r::At<uint8_t>(c->game, 0x106), dest);
		const int64_t last = Fn<int64_t (*)(Unit*, int32_t)>(0x507bd0)(c->player, 0);
		const int64_t now = Fn<int64_t (*)()>(0x120d720)();
		Out("enter: partner %s (room %s), destination %u, levels row %s (+0xd = %d), player state 0x66 %d, last portal %lld ms ago",
		    partner != nullptr ? "found" : "NOT found", partner != nullptr && Fn<void* (*)(Unit*)>(0x34b440)(partner) != nullptr ? "set" : "none", dest,
		    row != nullptr ? "found" : "NOT found", row != nullptr ? row[0xd] : -1, static_cast<int>(Fn<uint64_t (*)(Unit*, int32_t)>(0x3351b0)(c->player, 0x66) != 0),
		    static_cast<long long>(now - last));
		if (partner != nullptr) {  // the free spot next to the partner (0x362f90) and the owner / room tests that come before the handler's later steps
			int32_t pos[2] = {0, 0};
			Fn<void (*)(Unit*, int32_t*)>(0x34a040)(partner, pos);
			void* room = Fn<void* (*)(Unit*)>(0x34b440)(partner);
			const int32_t radius = Fn<int32_t (*)(Unit*)>(0x34b580)(c->player);
			void* spot = Fn<void* (*)(void*, int32_t*, int32_t, int32_t, int32_t)>(0x362f90)(room, pos, radius, 0x1c09, 0);
			const int32_t owner = Fn<int32_t (*)(Unit*)>(0x510b80)(portal);
			Out("enter: partner at %d,%d, free spot %s (radius %d), portal owner id %d (player id %u), 0x424a60 %d, player level id %d, partner level id %d", pos[0], pos[1],
			    spot != nullptr ? "found" : "NOT found", radius, owner, IdOf(c->player), Fn<int32_t (*)(Game*, Unit*)>(0x424a60)(c->game, c->player),
			    Fn<int16_t (*)(Unit*)>(0x48e480)(c->player), Fn<int16_t (*)(Unit*)>(0x48e480)(partner));
		}
	}
	return true;
}

// `missile <row> [dx dy [skill level]]`: a missile of missiles.txt row <row> from the player towards (player + dx, dy) (default 12, 0), made by skill
// <skill> at level <level> (default 0 / 0: the hit calcs of hit function 20 read that skill's row),
// the same call the skills use (0x5371a0). Bug #24b: the client's missile "do" function table has no entry for a
// missile row whose pCltDoFunc is empty, so any such missile crashes the client; this creates one on demand.
auto CmdMissile(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long row = 0, dx = 12, dy = 0, skill = 0, level = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &row) || row < 0 || row > 0x7fff ||
	    (t.n >= 3 && !hcmd::ParseInt(t.tok[2], &dx)) || (t.n >= 4 && !hcmd::ParseInt(t.tok[3], &dy)) ||
	    (t.n >= 5 && (!hcmd::ParseInt(t.tok[4], &skill) || skill < 0 || skill > 0x7fff)) ||
	    (t.n >= 6 && (!hcmd::ParseInt(t.tok[5], &level) || level < 0 || level > 0xff))) {
		return Fail(c, "usage: missile <missiles.txt row> [dx dy [skill level]]");
	}
	int32_t px = 0, py = 0;
	if (!d2r::UnitXY(c->player, &px, &py)) {
		return Fail(c, "missile: player has no position");
	}
	d2r::MissileParams params;
	std::memset(&params, 0, sizeof(params));
	params.flags = 0x820;
	params.owner = c->player;
	params.origin = c->player;
	params.missile = static_cast<int32_t>(row);
	params.targetX = px + static_cast<int32_t>(dx);
	params.targetY = py + static_cast<int32_t>(dy);
	params.skill = static_cast<int32_t>(skill);
	params.skillLevel = static_cast<int32_t>(level);
	Unit* m = d2r::api.createMissile(c->game, &params);
	Out("missile row %lld: %s", row, m != nullptr ? "created" : "refused");
	return m != nullptr ? true : Fail(c, "missile: createMissile returned no unit");
}

// `missilescan`: every missiles.txt row whose client do / client hit function index lands on an empty slot of D2R's
// tables (0x2358430, bound at 0x2358a60; 0x2358710, bound at 0x2358a64): the client calls those through a null pointer
// (bug #24b). Lists the first rows of each kind and the counts.
auto CmdMissileScan(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const uint32_t flag = d2r::DataFlag(c->game);
	long long dumpRow = -1;
	if (t.n >= 2 && hcmd::ParseInt(t.tok[1], &dumpRow)) {  // `missilescan <row>`: the record's first 0x60 bytes
		const uint8_t* r = Fn<const uint8_t* (*)(uint32_t, int32_t)>(0x166040)(flag, static_cast<int32_t>(dumpRow));
		char hex[0xa0 * 3 + 1] = "";
		for (int i = 0; r != nullptr && i < 0xa0; ++i) {
			std::snprintf(hex + i * 3, 4, "%02x ", r[i]);
		}
		Out("missile record %lld: %s", dumpRow, r != nullptr ? hex : "none");
		return true;
	}
	const int32_t rows = Fn<int32_t (*)(uint32_t)>(0x1b89a0)(flag);
	const auto record = Fn<const uint8_t* (*)(uint32_t, int32_t)>(0x166040);
	const int32_t doBound = *reinterpret_cast<const int32_t*>(g_base + 0x2358a60);
	const int32_t hitBound = *reinterpret_cast<const int32_t*>(g_base + 0x2358a64);
	const auto* doTable = reinterpret_cast<const uint64_t*>(g_base + 0x2358430);
	const auto* hitTable = reinterpret_cast<const uint64_t*>(g_base + 0x2358710);
	int badDo = 0, badHit = 0, lastDo = -9;
	char listDo[400] = "", listHit[200] = "";
	for (int32_t row = 0; row < rows; ++row) {
		const uint8_t* r = record(flag, row);
		if (r == nullptr) {
			continue;
		}
		const int16_t d = d2r::At<int16_t>(r, 0x28), h = d2r::At<int16_t>(r, 0x2a);
		if (d >= 0 && d < doBound && doTable[d] == 0) {
			if (badDo++ < 12 || (row - lastDo != 1 && std::strlen(listDo) < sizeof(listDo) - 24)) {  // the first rows, then each run's start
				std::snprintf(listDo + std::strlen(listDo), sizeof(listDo) - std::strlen(listDo), " %d(do %d)", row, d);
			}
			lastDo = row;
		}
		if (h >= 0 && h < hitBound && hitTable[h] == 0) {
			if (badHit++ < 12) {
				std::snprintf(listHit + std::strlen(listHit), sizeof(listHit) - std::strlen(listHit), " %d(hit %d)", row, h);
			}
		}
	}
	Out("missilescan: %d rows, client do bound %d, client hit bound %d", rows, doBound, hitBound);
	Out("missilescan: %d rows call an empty client do slot:%s", badDo, listDo);
	Out("missilescan: %d rows call an empty client hit slot:%s", badHit, listHit);
	return true;
}

// Use the nearest warp tile (stairs, doors to another area): the server's warp action 0x491ff0 (game, player, tile).
// `sysmsg <type> <colour> <text...>`: a system line to the player through the chat packet 0x26 (client_messages.cpp);
// the type and colour bytes are free so the client's reading of them can be found in game.
auto CmdSysmsg(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long type = 0, colour = 0;
	if (t.n < 4 || !hcmd::ParseInt(t.tok[1], &type) || !hcmd::ParseInt(t.tok[2], &colour)) {
		return Fail(c, "usage: sysmsg <chat type> <colour> <text...>");
	}
	char text[256] = "";
	for (int i = 3; i < t.n; ++i) {
		std::snprintf(text + std::strlen(text), sizeof(text) - std::strlen(text), "%s%s", i > 3 ? " " : "", t.tok[i]);
	}
	if (!SendClientChat(c->player, static_cast<uint8_t>(type), static_cast<uint8_t>(colour), text)) {
		return Fail(c, "send failed (messages off or no client)");
	}
	Out("sysmsg type %lld colour %lld: %s", type, colour, text);
	return true;
}

// `rewardmsg <0x5f|0x60|0x61>`: the quest reward client message to the player through D2R's unit message (0x491960), the
// path Jerhyn / Cain / Ormus / Akara use. The client plays Median's sound (`rewardsnd`).
auto CmdRewardMsg(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long msg = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &msg)) {
		return Fail(c, "usage: rewardmsg <95|96|97 or 0x5f|0x60|0x61>");
	}
	if (!RewardSoundsOn()) {
		return Fail(c, "rewardmsg: the client hook for packet 0x2c is off");
	}
	if (!SendRewardMessage(c->player, static_cast<uint32_t>(msg), "Reward", 1)) {
		return Fail(c, "rewardmsg: not sent (no such reward message or no client)");
	}
	Out("rewardmsg 0x%llx sent", msg);
	return true;
}

// Client side: `rewardsnd` prints how many reward sounds (messages 0x5f-0x61) the client has played, the last message and
// the sound row it played (217 gem, 2608 shrine stand-in, 230 armor).
auto CmdRewardSound(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	int played = 0, message = 0, sound = 0;
	RewardSoundStats(&played, &message, &sound);
	Out("rewardsnd hook=%d played=%d last message=0x%x sound=%d", RewardSoundsOn() ? 1 : 0, played, message, sound);
	(void)c;
	return true;
}

// Client side: `infopanel [close <n>]` prints the help panels' presentation state (0 unknown, 1 closed, 2 open, -1 none) and
// the open requests the client part has handled; `close <n>` closes one.
auto CmdInfoPanel(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 0;
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "close")) {
		if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &n)) {
			return Fail(c, "usage: infopanel close <panel>");
		}
		Out("infopanel close %lld %s", n, InfoPanelClose(static_cast<int>(n)) ? "ok" : "failed");
		return true;
	}
	int asked = 0, opened = 0, failed = 0;
	InfoPanelCounts(&asked, &opened, &failed);
	Out("infopanel state0=%d state1=%d asked=%d opened=%d failed=%d", InfoPanelState(0), InfoPanelState(1), asked, opened, failed);
	return true;
}

// Client side: `bufficons` prints the buff icon bar's counters and the icons of the last overlay frame (state, group, slot,
// seconds left, -1 = no timer); `bufficons hover <x> <y>` / `hover state <n>` / `hover off` moves the cursor the bar sees (screen
// pixels; `state` = the centre of that state's icon); `bufficons cstate <state> <0|1>` sets a state bit on the client's copy of
// the player (the bar reads that copy; a state the server sets reaches it only through D2R's own packets).
auto CmdBuffIcons(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long a = 0, b = 0;
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "hover")) {
		if (t.n == 3 && hcmd::LowerEq(t.tok[2], "off")) {
			BuffIconsHover(0.0F, 0.0F, false);
			Out("bufficons hover off");
			return true;
		}
		float x = 0.0F, y = 0.0F;
		if (t.n == 4 && hcmd::LowerEq(t.tok[2], "state") && hcmd::ParseInt(t.tok[3], &a)) {
			if (!BuffIconsCentre(static_cast<int>(a), &x, &y)) {
				return Fail(c, "bufficons: state %lld is not shown", a);
			}
		} else if (t.n == 4 && hcmd::ParseInt(t.tok[2], &a) && hcmd::ParseInt(t.tok[3], &b)) {
			x = static_cast<float>(a);
			y = static_cast<float>(b);
		} else {
			return Fail(c, "usage: bufficons hover <x> <y> | state <n> | off");
		}
		BuffIconsHover(x, y, true);
		Out("bufficons hover %.0f %.0f", static_cast<double>(x), static_cast<double>(y));
		return true;
	}
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "probe")) {
		const bool on = t.n < 3 || !hcmd::LowerEq(t.tok[2], "off");
		BuffIconsProbe(on);
		Out("bufficons probe %s codes=0x%x", on ? "on" : "off", BuffIconsProbeCodes());
		return true;
	}
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "cstate")) {
		if (t.n != 4 || !hcmd::ParseInt(t.tok[2], &a) || !hcmd::ParseInt(t.tok[3], &b) || a < 1 || a > 1023) {
			return Fail(c, "usage: bufficons cstate <state> <0|1>");
		}
		if (!BuffIconsClientState(static_cast<int>(a), b != 0)) {
			return Fail(c, "bufficons: no local player (or the part is off)");
		}
		Out("bufficons cstate %lld %lld", a, b);
		return true;
	}
	char counters[512];
	BuffIconShown shown[64];
	const int n = BuffIconsStatus(counters, sizeof(counters), shown, 64);
	Out("bufficons %s", counters);
	for (int i = 0; i < n; ++i) {
		Out("bufficons icon state=%d side=%d slot=%d row=%d secs=%d hover=%d x=%.0f y=%.0f size=%.0f", shown[i].state, shown[i].side,
		    shown[i].slot, shown[i].row, shown[i].seconds, shown[i].hovered ? 1 : 0, static_cast<double>(shown[i].x),
		    static_cast<double>(shown[i].y), static_cast<double>(shown[i].size));
	}
	return true;
}

// Client side: `statorder` prints the Advanced Stats list as the panel built it last (stat_columns.cpp, Median's order):
// "statorder ordered=1 rebuilds=N rows=M", then the rows, a section label as [Label] and a stat as its D2R stat id.
// `statorder open` / `close` opens or closes the character sheet through D2R's panel messages, `statorder adv` presses its
// Advanced Stats button (the sheet must be open; the button's own onClickMessage).
auto CmdStatOrder(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 2 && (hcmd::LowerEq(t.tok[1], "open") || hcmd::LowerEq(t.tok[1], "close") || hcmd::LowerEq(t.tok[1], "adv"))) {
		const bool adv = hcmd::LowerEq(t.tok[1], "adv");
		const char* command = adv ? "ToggleAdvancedStats" : hcmd::LowerEq(t.tok[1], "open") ? "OpenPanel" : "ClosePanel";
		const int rc = adv ? HarnessUiAction("CharacterStatsPanelMessage", command, "") : HarnessUiAction("PanelManager", command, "CharacterStatsPanel");
		Out("statorder %s rc=%d", command, rc);
		return rc == 0;
	}
	bool ordered = false;
	int rebuilds = 0;
	int32_t ids[256];
	const int rows = StatOrderRows(&ordered, &rebuilds, ids, 256);
	Out("statorder ordered=%d rebuilds=%d rows=%d", ordered ? 1 : 0, rebuilds, rows);
	char line[400] = "";
	size_t n = 0;
	for (int i = 0; i < rows && i < 256; ++i) {
		const char* label = StatOrderLabel(ids[i]);
		char item[64];
		if (label[0] != '\0') {
			std::snprintf(item, sizeof(item), "[%s] ", label);
		} else {
			std::snprintf(item, sizeof(item), "%d ", ids[i]);
		}
		const size_t len = std::strlen(item);
		if (n + len >= sizeof(line)) {
			Out("statorder rows %s", line);
			n = 0;
			line[0] = '\0';
		}
		std::memcpy(line + n, item, len + 1);
		n += len;
	}
	if (n != 0) {
		Out("statorder rows %s", line);
	}
	(void)c;
	return true;
}

// `goblinsay <monster class>`: the goblin "<name> appears!" line for that variant to the player (the line a spawn sends).
auto CmdGoblinSay(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &cls)) {
		return Fail(c, "usage: goblinsay <monster class>");
	}
	char text[96];
	if (!GoblinAnnounce(c->player, static_cast<int>(cls), text, sizeof(text))) {
		return Fail(c, "goblinsay: not sent (messages off or no client)");
	}
	Out("goblinsay %lld: %s", cls, text);
	return true;
}

auto CmdTile(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* tile = nullptr;
	double best = 1e18;
	int guard = 0;
	for (auto* u = d2r::At<Unit*>(c->game, 0x3630); u != nullptr && guard < 2000; u = d2r::At<Unit*>(u, UnitNextInHash), ++guard) {
		if (TypeOf(u) == 5 && DistTo(c->player, u) < best) {
			best = DistTo(c->player, u);
			tile = u;
		}
	}
	if (tile == nullptr) {
		return Fail(c, "tile: no warp tile in this game");
	}
	Fn<void (*)(Game*, Unit*, Unit*)>(0x491ff0)(c->game, c->player, tile);
	Out("tile id=%u class=%d dist %.0f used", IdOf(tile), ClassOf(tile), best);
	return true;
}

// Raw client packet to the server's handler table: "pkt 13 02 00 00 00 <id bytes>" (hex bytes, the first is the packet id).
// For what no verb covers yet (clicking an object or a portal: packet 0x13).
auto CmdPkt(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	uint8_t pkt[64] = {};
	int n = 0;
	for (int i = 1; i < t.n && n < 64; ++i) {
		long long v = 0;
		char hex[8] = "0x";
		std::snprintf(hex + 2, sizeof(hex) - 2, "%.2s", t.tok[i]);
		if (!hcmd::ParseInt(hex, &v)) {
			return Fail(c, "pkt: '%.10s' is not a hex byte", t.tok[i]);
		}
		pkt[n++] = static_cast<uint8_t>(v);
	}
	if (n < 1 || pkt[0] >= 0x66 || *reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + pkt[0] * 8) == 0) {
		return Fail(c, "pkt: no server handler for that id");
	}
	const auto handler = reinterpret_cast<PacketFn>(*reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + pkt[0] * 8));
	handler(c->game, c->player, pkt, n);
	Out("pkt 0x%02x (%d bytes) handled", pkt[0], n);
	return true;
}

auto CmdLevel(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long level = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &level)) {
		return Fail(c, "usage: level <level id>");
	}
	Fn<TravelFn>(RvaTravel)(c->game, c->player, static_cast<int>(level), 0);
	return true;  // the move itself takes a few frames; `state` shows the new area
}

auto CmdSpawn(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = 0, count = 1, sx = 0, sy = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &cls) || (t.n > 2 && !hcmd::ParseInt(t.tok[2], &count)) ||
	    (t.n > 3 && (t.n != 5 || !hcmd::ParseInt(t.tok[3], &sx) || !hcmd::ParseInt(t.tok[4], &sy)))) {
		return Fail(c, "usage: spawn <monster class> [count [x y]]");
	}
	void* room = Fn<UnitRoomFn>(RvaUnitRoom)(c->player);
	int32_t px = 0, py = 0;
	if (room == nullptr || !d2r::UnitXY(c->player, &px, &py)) {
		return Fail(c, "spawn: player has no room");
	}
	int made = 0;
	for (long long i = 0; i < count && i < 20; ++i) {
		const int32_t x = (t.n == 5 ? static_cast<int32_t>(sx) : px + 6) + static_cast<int32_t>(i % 5) * 2;
		const int32_t y = (t.n == 5 ? static_cast<int32_t>(sy) : py + 6) + static_cast<int32_t>(i / 5) * 2;
		void* spawnRoom = Fn<InRoomFn>(RvaInRoom)(room, x, y);
		if (spawnRoom == nullptr) {
			continue;
		}
		if (Unit* m = Fn<SpawnFn>(RvaSpawn)(c->game, spawnRoom, x, y, static_cast<int32_t>(cls), 1, 2, 0, 0)) {
			Out("spawned class %lld id=%u at %d,%d", cls, IdOf(m), x, y);
			++made;
		}
	}
	return made > 0 ? true : Fail(c, "spawn: nothing spawned");
}

auto CmdKill(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: kill <unit id> | kill nearest [class] | kill player [monster id]");
	}
	Unit* victim = nullptr;
	long long v = 0;
	if (hcmd::LowerEq(t.tok[1], "player")) {
		// The unit death function on the character itself (a death where `hit` does not work, the town: monsters cannot damage
		// there), killed by the given monster or, without one, by the character.
		Unit* killer = c->player;
		if (t.n > 2 && hcmd::ParseInt(t.tok[2], &v)) {
			killer = FindMonsterById(c, static_cast<uint32_t>(v));
		}
		if (killer == nullptr) {
			return Fail(c, "kill player: no such live monster");
		}
		Fn<KillFn>(RvaKill)(c->game, c->player, killer, 1);
		Out("kill player: mode now %d (0 or 17 = dead)", ModeOf(c->player));
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "nearest")) {
		long long cls = -1;
		if (t.n > 2 && !hcmd::ParseInt(t.tok[2], &cls)) {
			return Fail(c, "kill nearest: class must be a number");
		}
		victim = NearestMonster(c, cls, false);
	} else if (hcmd::ParseInt(t.tok[1], &v)) {
		victim = FindMonsterById(c, static_cast<uint32_t>(v));
	}
	if (victim == nullptr) {
		return Fail(c, "kill: no such live monster");
	}
	const uint32_t id = IdOf(victim);
	const int32_t cls = ClassOf(victim);
	Fn<KillFn>(RvaKill)(c->game, victim, c->player, 1);
	Out("kill id=%u class=%d: mode now %d (0 or 12 = dead)", id, cls, ModeOf(victim));
	return true;
}

// `xp <amount>`: the experience award of a kill without the monster (D2R's own function, so the level-ups, the stat and skill
// points and the level cap are the engine's). Prints the numbers a level cap check reads.
auto CmdXp(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long amount = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &amount) || amount < 0 || amount > 0x7fffffff) {
		return Fail(c, "usage: xp <amount>");
	}
	Fn<AddExperienceFn>(RvaAddExperience)(c->game, c->player, Stat(c->player, StatLevel), static_cast<int32_t>(amount));
	Out("xp level=%d experience=%u statpoints=%d skillpoints=%d", Stat(c->player, StatLevel),
	    static_cast<uint32_t>(Stat(c->player, 13)), Stat(c->player, 4), Stat(c->player, 5));
	return true;
}

auto CmdInteract(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: interact nearest | interact <npc class>");
	}
	long long cls = -1;
	if (!hcmd::LowerEq(t.tok[1], "nearest") && !hcmd::ParseInt(t.tok[1], &cls)) {
		return Fail(c, "interact: nearest or an NPC class id");
	}
	Unit* npc = NearestMonster(c, cls, true);
	if (npc == nullptr) {
		return Fail(c, "interact: no such NPC alive in this area");
	}
	// The server accepts the click within a few sub-tiles of the NPC: stand next to it first, as a walk would.
	if (DistTo(c->player, npc) > 5.0) {
		int32_t nx = 0, ny = 0;
		d2r::UnitXY(npc, &nx, &ny);
		static const int off[][2] = {{2, 2}, {-2, 2}, {2, -2}, {-2, -2}, {3, 0}, {0, 3}, {-3, 0}, {0, -3}, {4, 4}, {-4, -4}};
		for (const auto& o : off) {
			if (Fn<BlockedFn>(RvaMoveBlocked)(c->player, nx + o[0], ny + o[1], 0x804) != 0) {
				continue;
			}
			Fn<MoveFn>(RvaMove)(c->game, c->player, 0, nx + o[0], ny + o[1], 0, 0);
			if (DistTo(c->player, npc) <= 5.0) {
				break;
			}
		}
	}
	// Packet 0x2f (start talking to an NPC): u8 id, u32 unit id. The handler answers the client with 0x27, which opens
	// the NPC menu through the client's own builder (0x1141d0 -> 0x1147a0), and fires quest event 0 (NPC activate).
	uint8_t pkt[5] = {0x2f};
	const uint32_t id = IdOf(npc);
	std::memcpy(pkt + 1, &id, 4);
	const auto handler = reinterpret_cast<PacketFn>(*reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + 0x2f * 8));
	handler(c->game, c->player, pkt, 5);
	Out("interact npc id=%u class=%d distance %.1f", id, ClassOf(npc), DistTo(c->player, npc));
	return true;
}

int g_uniq = -1;
using ItemDataFn = uint8_t* (*)(Unit*);
constexpr uint64_t RvaItemData = 0x34a500;  // (item) -> item data (+0 quality, +0x34 unique index)

// `difficulty <0-2>`: the running game's difficulty byte (game +0x104), for checks that need Hell rules without a Hell
// character. Quest records are per difficulty, so use it for lockout / recipe checks only.
auto CmdDifficulty(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 0;
	if (t.n >= 2 && hcmd::ParseInt(t.tok[1], &n) && n >= 0 && n <= 2) {
		*reinterpret_cast<uint8_t*>(reinterpret_cast<uint8_t*>(c->game) + GameDifficulty) = static_cast<uint8_t>(n);
	}
	Out("difficulty = %d", static_cast<int>(d2r::At<uint8_t>(c->game, GameDifficulty)));
	return true;
}

// `towerprobe`: would the quest 5 kill hook skip the vanilla handler for the nearest Countess (class 45)? Spawn one first.
auto CmdTowerprobe(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* victim = NearestMonster(c, 45, false);
	if (victim == nullptr) {
		return Fail(c, "towerprobe: no Countess (spawn 45) alive");
	}
	Out("towerprobe class=45 skip=%d", QuestsTowerProbe(c->game, victim, c->player) ? 1 : 0);
	return true;
}

// `a5done`: D2R's own Act 5 quest completion for quest 39 (Rite of Passage, 0x54af20(game, player)): with the quest not done,
// the player in Act 5 and a level of 20 / 40 / 60 or more by difficulty it sets the quest's bits and pays the quest experience
// (0x550c20). Prints the experience stat (13) and the level before and after.
constexpr uint64_t RvaRiteOfPassage = 0x54af20;
using RiteFn = void (*)(Game*, Unit*);

auto CmdA5Done(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	const int32_t xp0 = Stat(c->player, 13), lvl0 = Stat(c->player, StatLevel);
	Fn<RiteFn>(RvaRiteOfPassage)(c->game, c->player);
	const int32_t xp1 = Stat(c->player, 13), lvl1 = Stat(c->player, StatLevel);
	void* rec = QuestRecord(c);
	Out("a5done level %d->%d xp %d->%d gained=%d quest39bit0=%d", lvl0, lvl1, xp0, xp1, xp1 - xp0,
	    rec != nullptr ? Fn<QuestFn>(RvaQuestTest)(rec, 39, 0) : -1);
	return true;
}

// `countessreward`: the Countess reward function 0x5e3010 (quest 5, its data block at +0x20) run on its own for the nearest
// Countess (spawn 45 first), as if she had just died to the player: the data block's "dead" byte (+0x118) is set and the
// "handed out" byte (+0x119) cleared first, the quest 5 kill context is set by hand. Prints the byte afterwards.
constexpr uint64_t RvaFindQuest = 0x518220;     // (game, quest id) -> quest object
constexpr uint64_t RvaCountessReward = 0x5e3010;  // (quest 5, quest 5 + 0x20)
using FindQuestFn = uint8_t* (*)(Game*, int32_t);
using CountessRewardFn = void (*)(uint8_t*, uint8_t*);

auto CmdCountessReward(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* victim = NearestMonster(c, 45, false);
	if (victim == nullptr) {
		return Fail(c, "countessreward: no Countess (spawn 45) alive");
	}
	uint8_t* quest = Fn<FindQuestFn>(RvaFindQuest)(c->game, 5);
	if (quest == nullptr) {
		return Fail(c, "countessreward: no quest 5 object");
	}
	uint8_t* data = quest + 0x20;
	data[0x118] = 1;
	data[0x119] = 0;
	QuestsTowerKillSet(victim, c->player);
	Fn<CountessRewardFn>(RvaCountessReward)(quest, data);
	QuestsTowerKillSet(nullptr, nullptr);
	Out("countessreward done=%d", static_cast<int>(data[0x119]));
	return data[0x119] != 0;
}

// `questobj <id> [active <0|1>]`: the game's quest object (0x518220): bytes +0x00..+0x2f (the dispatcher 0x518ec0 calls a handler
// only while byte +0x12 is 1), its event 8 (kill) handler slot as an exe offset, and optionally a new value for +0x12.
auto CmdQuestObj(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0;
	long long active = -1, pokeOff = -1, pokeVal = 0;
	const bool poke = t.n > 4 && hcmd::LowerEq(t.tok[2], "poke");
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &id) ||
	    (t.n > 3 && !poke && (!hcmd::LowerEq(t.tok[2], "active") || !hcmd::ParseInt(t.tok[3], &active))) ||
	    (poke && (!hcmd::ParseInt(t.tok[3], &pokeOff) || !hcmd::ParseInt(t.tok[4], &pokeVal) || pokeOff < 0 || pokeOff >= 0x270))) {
		return Fail(c, "usage: questobj <id> [active <0|1> | poke <offset below 0x270> <byte>]");
	}
	uint8_t* quest = Fn<FindQuestFn>(RvaFindQuest)(c->game, static_cast<int32_t>(id));
	if (quest == nullptr) {
		return Fail(c, "questobj: no quest %lld", id);
	}
	if (active >= 0) {
		quest[0x12] = static_cast<uint8_t>(active);
	}
	if (poke) {
		quest[pokeOff] = static_cast<uint8_t>(pokeVal);
	}
	char hex[100] = "";
	for (int i = 0; i < 0x30; ++i) {
		std::snprintf(hex + i * 2, sizeof(hex) - static_cast<size_t>(i) * 2, "%02x", quest[i]);
	}
	const uint64_t kill = *reinterpret_cast<const uint64_t*>(quest + 0x270 + 8 * 8);
	Out("questobj %lld at %p active=%d bytes=%s kill=exe+%llx", id, static_cast<void*>(quest), static_cast<int>(quest[0x12]), hex,
	    static_cast<unsigned long long>(kill - g_base));
	return true;
}

// `questreg <monster id> <quest id>`: the game's own registration of a unit with a quest (0x514100: appends the quest object to the
// unit's quest list, unit +0xc0). The kill wrapper 0x515640 hands the death to a quest only for a victim that has such a list; the
// level code registers the real Countess when she is created, a `spawn`ed one has to be registered here.
auto CmdQuestReg(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0, quest = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &id) || !hcmd::ParseInt(t.tok[2], &quest)) {
		return Fail(c, "usage: questreg <monster id> <quest id>");
	}
	Unit* u = FindMonsterById(c, static_cast<uint32_t>(id));
	if (u == nullptr) {
		return Fail(c, "questreg: no such live monster");
	}
	const int64_t rc = Fn<int64_t (*)(Game*, Unit*, int32_t)>(0x514100)(c->game, u, static_cast<int32_t>(quest));
	Out("questreg unit id=%u class=%d quest %lld: %lld; unit quest list %s", IdOf(u), ClassOf(u), quest, static_cast<long long>(rc),
	    Fn<void* (*)(Unit*)>(0x34b3c0)(u) != nullptr ? "set" : "empty");
	return true;
}

// `objects [class]`: every object unit of the level (any distance) with its class, mode and position.
auto CmdObjects(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = -1;
	if (t.n > 1 && !hcmd::ParseInt(t.tok[1], &cls)) {
		return Fail(c, "usage: objects [class]");
	}
	int n = 0;
	EachUnit(c->game, HashObjects, [&](Unit* u) {
		if (TypeOf(u) != 2 || (cls >= 0 && ClassOf(u) != cls) || n >= 150) {
			return;
		}
		++n;
		int32_t ox = 0, oy = 0;
		d2r::UnitXY(u, &ox, &oy);
		Out("object id=%u class=%d mode=%d dist=%.0f at %d,%d", IdOf(u), ClassOf(u), ModeOf(u), DistTo(c->player, u), ox, oy);
	});
	Out("objects %d", n);
	return true;
}

// `object <class> [dx dy]`: an object unit of the class (objects.txt row, e.g. 376 the Hellforge, 252 Gidbinn's altar, 563 the final
// portal) next to the player (default 3 tiles to the east), made by D2R's unit creator 0x490410 as the portal routine 0x432ce0 does
// for its portal objects. The object is plain: its mode is the default one, no quest or level logic has run for it.
auto CmdObject(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = 0, dx = 3, dy = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &cls) || cls < 0 || cls > 0xffff || (t.n > 2 && !hcmd::ParseInt(t.tok[2], &dx)) ||
	    (t.n > 3 && !hcmd::ParseInt(t.tok[3], &dy))) {
		return Fail(c, "usage: object <objects.txt class> [dx dy]");
	}
	int32_t px = 0, py = 0;
	if (!d2r::UnitXY(c->player, &px, &py)) {
		return Fail(c, "object: player has no position");
	}
	void* room = Fn<void* (*)(Unit*)>(0x34b440)(c->player);
	const int32_t x = px + static_cast<int32_t>(dx), y = py + static_cast<int32_t>(dy);
	void* at = room != nullptr ? Fn<void* (*)(void*, int32_t, int32_t)>(0x38dfb0)(room, x, y) : nullptr;
	if (at == nullptr) {
		return Fail(c, "object: no room at %d,%d", x, y);
	}
	Unit* u = Fn<Unit* (*)(int32_t, int32_t, int32_t, int32_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t)>(0x490410)(
		2, static_cast<int32_t>(cls), x, y, reinterpret_cast<uint64_t>(c->game), reinterpret_cast<uint64_t>(at), 1, 1, 0, 0);
	if (u == nullptr) {
		return Fail(c, "object: the creator returned no unit");
	}
	Out("object created: id=%u class=%d mode=%d at %d,%d", IdOf(u), ClassOf(u), ModeOf(u), x, y);
	return true;
}

// `operate <object id> <function>`: the object operate function <function> (table 0x23a51c0, objects.txt OperateFn) with the
// context the game builds for a click: {game, object, player, 0, class}. Prints its result and the object's mode afterwards.
auto CmdOperate(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0, fn = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &id) || !hcmd::ParseInt(t.tok[2], &fn) || fn < 0 || fn > 120) {
		return Fail(c, "usage: operate <object id> <operate function>");
	}
	Unit* obj = nullptr;
	EachUnit(c->game, HashObjects, [&](Unit* u) {
		if (TypeOf(u) == 2 && IdOf(u) == static_cast<uint32_t>(id)) {
			obj = u;
		}
	});
	if (obj == nullptr) {
		return Fail(c, "operate: no such object");
	}
	const uint64_t entry = *reinterpret_cast<const uint64_t*>(g_base + 0x23a51c0 + 8 * static_cast<uint64_t>(fn));
	if (entry == 0) {
		return Fail(c, "operate: function %lld has no entry", fn);
	}
	int64_t ctx[8] = {reinterpret_cast<int64_t>(c->game), reinterpret_cast<int64_t>(obj), reinterpret_cast<int64_t>(c->player), 0,
	                  ClassOf(obj), 0, 0, 0};
	const int64_t rc = reinterpret_cast<int64_t (*)(int64_t*)>(entry)(ctx);
	Out("operate object id=%u class=%d with function %lld (exe+%llx): result %lld, object mode now %d", IdOf(obj), ClassOf(obj), fn,
	    static_cast<unsigned long long>(entry - g_base), static_cast<long long>(rc), ModeOf(obj));
	return true;
}

// `objmode <object id> <mode>`: the game's set-mode call (0x34e5f0) on an object; the operate functions test the mode (state 2 = open
// for the Worldstone / Throne objects 563 / 569 and Tyrael's portal object 566).
auto CmdObjMode(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0, mode = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &id) || !hcmd::ParseInt(t.tok[2], &mode) || mode < 0 || mode > 20) {
		return Fail(c, "usage: objmode <object id> <mode>");
	}
	Unit* obj = nullptr;
	EachUnit(c->game, HashObjects, [&](Unit* u) {
		if (TypeOf(u) == 2 && IdOf(u) == static_cast<uint32_t>(id)) {
			obj = u;
		}
	});
	if (obj == nullptr) {
		return Fail(c, "objmode: no such object");
	}
	const int64_t rc = Fn<int64_t (*)(Unit*, int32_t)>(0x34e5f0)(obj, static_cast<int32_t>(mode));
	Out("objmode object id=%u class=%d: set-mode returned %lld, mode now %d", IdOf(obj), ClassOf(obj), static_cast<long long>(rc), ModeOf(obj));
	return true;
}

// `portal <median level id>`: the cube recipe's red portal to a Median level (item_spells.cpp CubeLevelPortal, the same rules as
// the portal scrolls: same act, a linkable level), opened next to the player.
auto CmdPortal(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long level = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &level) || level < 0 || level > 0x7fff) {
		return Fail(c, "usage: portal <median level id>");
	}
	const bool ok = CubeLevelPortal(c->game, c->player, static_cast<int32_t>(level));
	Out("portal to Median level %lld: %s", level, ok ? "opened" : "refused");
	return ok ? true : Fail(c, "portal: refused");
}

// `hellforgereward [monster class]`: the Hellforge reward function 0x5e4540 (quest 27, called by the quest dispatcher 0x516370
// when the player smashes the Mephisto soulstone on the forge object, class 376) run on its own, with the nearest monster of
// the class (default 1: spawn one first) standing in for the forge: the quest's active byte (+0x23) is set first. Prints the
// byte afterwards (the plugin's hook clears it when it rolled Median's class; D2R's runes would clear it too, see the item count).
constexpr uint64_t RvaHellforgeReward = 0x5e4540;  // (quest 27, forge unit)
using HellforgeRewardFn = void (*)(uint8_t*, Unit*);

auto CmdHellforgeReward(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = 1;
	if (t.n >= 2 && !hcmd::ParseInt(t.tok[1], &cls)) {
		return Fail(c, "usage: hellforgereward [monster class]");
	}
	Unit* stand = NearestMonster(c, static_cast<int>(cls), false);
	if (stand == nullptr) {
		return Fail(c, "hellforgereward: no such monster alive (spawn it first)");
	}
	uint8_t* quest = Fn<FindQuestFn>(RvaFindQuest)(c->game, 27);
	if (quest == nullptr) {
		return Fail(c, "hellforgereward: no quest 27 object");
	}
	quest[0x23] = 1;
	Fn<HellforgeRewardFn>(RvaHellforgeReward)(quest, stand);
	Out("hellforgereward active=%d", static_cast<int>(quest[0x23]));
	return quest[0x23] == 0;
}

// `prisonreward`: Anya's Prison of Ice reward task 0x546cc0 (a5q3.cpp) run on its own with a task node built by hand:
// +8 the player's unit id, +0x10 the game, +0x18 the item code, here D2R's own ring ("rin "). The plugin's hook rewrites the
// code to Median's amulet ("amu "); the item is created rare for the player (inventory, or the ground when full).
constexpr uint64_t RvaPrisonReward = 0x546cc0;  // (task node, ctx)
using PrisonRewardFn = void (*)(uint8_t*, void*);

auto CmdPrisonReward(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	uint8_t node[0x40] = {};
	const uint32_t id = IdOf(c->player);
	const uint32_t code = 0x206e6972;  // "rin "
	std::memcpy(node + 8, &id, 4);
	std::memcpy(node + 0x10, &c->game, 8);
	std::memcpy(node + 0x18, &code, 4);
	Fn<PrisonRewardFn>(RvaPrisonReward)(node, nullptr);
	uint32_t after = 0;
	std::memcpy(&after, node + 0x18, 4);
	Out("prisonreward code now %.4s", reinterpret_cast<const char*>(&after));
	return after == 0x20756d61;  // "amu "
}

// `lockcheck <level>`: the dungeon warp test's verdict for the player entering the level (dungeon_lockout.cpp).
auto CmdLockcheck(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &n)) {
		Out("lockcheck: usage lockcheck <level>");
		return true;
	}
	static const char* const Names[] = {"allow", "requirements", "quest", "sealed"};
	const int v = DungeonLockoutProbe(c->game, c->player, static_cast<int>(n));
	Out("lockcheck %lld = %s", n, v >= 0 && v < 4 ? Names[v] : "none");
	return true;
}

// Class change for tests (`class <n>`): cube recipes can be class bound. The save keeps it, put the class back.
auto CmdClass(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 0;
	if (t.n >= 2 && hcmd::ParseInt(t.tok[1], &n) && n >= 0 && n <= 6) {
		*reinterpret_cast<int32_t*>(reinterpret_cast<uint8_t*>(c->player) + UnitClass) = static_cast<int32_t>(n);
	}
	Out("class = %d", ClassOf(c->player));
	return true;
}

// Port of 0x517530 with a choice of where the item goes and stats set before the client hears of it.
// bodyLoc 1-12 equips the item instead (Place with a body location, as the packet 0x1a handler's move does).
auto MakeItem(Ctx* c, uint32_t code, int quality, int ilvl, int page, const int (*stats)[3], const long long* values, int nstats,
              char* why, size_t whySize, int bodyLoc = 0) noexcept -> Unit* {
	int32_t classId = 0;
	const uint8_t* rec = Fn<ItemByCodeFn>(RvaItemByCode)(c->dataFlag, code, &classId);
	if (rec == nullptr) {
		std::snprintf(why, whySize, "item: unknown code");
		return nullptr;
	}
	if (ilvl == 0) {
		ilvl = Fn<DefaultIlvlFn>(RvaDefaultIlvl)(c->player, 0);
	}
	if (g_uniq >= 0) {  // the quest module's generator hook picks the unique (as for Griswold's Heart): quality 7, item level 255
		quality = 7;
		ilvl = 255;
		QuestsWantUnique(g_uniq + 1);
	}
	Unit* item = Fn<MakeItemFn>(RvaMakeItem)(c->player, classId, c->game, 4, quality, 0, 1, ilvl, 0, 0, 0);
	QuestsWantUnique(0);
	if (item == nullptr) {
		std::snprintf(why, whySize, "item: creation failed");
		return nullptr;
	}
	if (g_uniq >= 0) {  // a named unique (the cube matches uniques by index): item data +0 quality, +0x34 unique index
		if (auto* data = Fn<ItemDataFn>(RvaItemData)(item); data != nullptr && *reinterpret_cast<int32_t*>(data + 0x34) != g_uniq) {
			*reinterpret_cast<int32_t*>(data) = 7;
			*reinterpret_cast<int32_t*>(data + 0x34) = g_uniq;
		}
	}
	if (const int32_t dur = Fn<ItemStatFn>(RvaMaxDurability)(item); dur != 0) {
		Fn<SetItemStatFn>(RvaSetStatItem)(item, StatDurability, dur, 0);
	}
	// The stats go on the item's magic list (the one D2R saves and the owner reads, as for a rolled property), as a difference
	// so that the value is the item's total; a plain set would sit on the base list and vanish in the save.
	void* magic = nstats > 0 ? Fn<ItemStatListFn>(RvaItemStatList)(nullptr, item, 0, MagicStatListFlag) : nullptr;
	for (int i = 0; i < nstats; ++i) {
		if (magic != nullptr) {
			const int32_t delta = static_cast<int32_t>(values[i]) - Stat(item, stats[i][0], stats[i][1]);
			Fn<StatListAddFn>(RvaStatListAdd)(d2r::DataFlag(c->game), magic, stats[i][0], delta, stats[i][1]);
		} else {
			Fn<SetStatFn>(RvaSetStat)(item, stats[i][0], static_cast<int32_t>(values[i]), stats[i][1]);
		}
	}
	if (page < 0) {  // on the ground next to the player
		Fn<DropFlagsFn>(RvaDropFlags)(item, 0x4000, 0);
		Fn<ByteSetFn>(RvaGround1)(item, 0xff);
		Fn<ByteSetFn>(RvaGround2)(item, 0);
		Fn<ByteSetFn>(RvaGround3)(item, 3);
		Fn<ByteSetFn>(RvaGround4)(item, 0);
		Fn<ByteSetFn>(RvaGround5)(item, 0);
		int32_t xy[2] = {};
		Fn<UnitXYFn>(RvaUnitXY)(c->player, xy);
		void* room = Fn<UnitRoomFn>(RvaUnitRoom)(c->player);
		int32_t out[2] = {};
		void* spot = Fn<GroundSpotFn>(RvaGroundSpot)(c->game, room, xy, out, 1);
		if (spot == nullptr) {
			Fn<FreeItemFn>(RvaFreeItem)(c->game, item);
			std::snprintf(why, whySize, "item: no free ground spot");
			return nullptr;
		}
		Fn<GroundDropFn>(RvaGroundDrop)(c->game, c->player, item, spot, out[0], out[1]);
		return item;
	}
	int32_t loc[4] = {};
	if (bodyLoc > 0) {
		Fn<BodyLocFn>(RvaBodyLoc)(loc, bodyLoc);
	} else {
		void* inv = Fn<InventoryFn>(RvaInventory)(c->player, "harness", 0);
		const int32_t record = Fn<InvRecordFn>(RvaInvRecord)(c->player, page == 3 ? 3 : 0, d2r::At<uint8_t>(c->game, 0x106) != 1);
		uint16_t x = 0, y = 0;
		if (inv == nullptr || Fn<FindSpotFn>(RvaFindSpot)(inv, item, record, &x, &y, page) == 0) {
			Fn<FreeItemFn>(RvaFreeItem)(c->game, item);
			std::snprintf(why, whySize, "item: no room in %s", page == 3 ? "the cube" : "the inventory");
			return nullptr;
		}
		Fn<LocInitFn>(RvaLocInit)(loc, page, static_cast<int32_t>((static_cast<uint32_t>(y) << 16) | x));
	}
	uint32_t itemId = IdOf(item);
	if ((bodyLoc <= 0 && loc[0] != 0) || Fn<PlaceFn>(RvaPlace)(c->player, loc, &itemId, 1, 0) == 0) {
		Fn<FreeItemFn>(RvaFreeItem)(c->game, item);
		if (bodyLoc > 0) {
			std::snprintf(why, whySize, "equip: the item does not fit body location %d or it is occupied (unequip first)", bodyLoc);
		} else {
			std::snprintf(why, whySize, "item: placing failed");
		}
		return nullptr;
	}
	Fn<SendItemFn>(RvaSendItem)(c->game, c->player, item, 1, 2, loc[0], loc[1], loc[3], loc[2]);
	Fn<IdentifyHookFn>(RvaIdentifyHook)(c->game, c->player, item, 0);
	if (Fn<AfterPlaceFn>(RvaAfterPlace)(item, c->player) != 0) {
		Fn<RecheckFn>(RvaRecheck)(c->game, c->player, 0, 0);
	}
	return item;
}

// Shared by `item` and `equip`: <code> then stat=value pairs, q=, ilvl=, uniq=, a page word (inv cube ground) or a body location.
struct ItemSpec {
	int stats[8][3] = {};
	long long values[8] = {};
	int nstats = 0, quality = 2, ilvl = 0, page = 0, bodyLoc = 0;
};

auto ParseItemSpec(Ctx* c, const hcmd::Tokens& t, ItemSpec* spec) noexcept -> bool {
	g_uniq = -1;
	for (int i = 2; i < t.n; ++i) {
		long long v = 0;
		if (hcmd::LowerEq(t.tok[i], "inv")) {
			spec->page = 0;
		} else if (hcmd::LowerEq(t.tok[i], "cube")) {
			spec->page = 3;
		} else if (hcmd::LowerEq(t.tok[i], "ground")) {
			spec->page = -1;
		} else if (std::strncmp(t.tok[i], "q=", 2) == 0 && hcmd::ParseInt(t.tok[i] + 2, &v)) {
			spec->quality = static_cast<int>(v);
		} else if (std::strncmp(t.tok[i], "uniq=", 5) == 0 && hcmd::ParseInt(t.tok[i] + 5, &v)) {
			g_uniq = static_cast<int>(v);
		} else if (std::strncmp(t.tok[i], "ilvl=", 5) == 0 && hcmd::ParseInt(t.tok[i] + 5, &v)) {
			spec->ilvl = static_cast<int>(v);
		} else if (spec->nstats < 8 &&
		           hcmd::ParseStatArg(t.tok[i], &spec->stats[spec->nstats][0], &spec->stats[spec->nstats][1], &spec->values[spec->nstats])) {
			++spec->nstats;
		} else if (std::strchr(t.tok[i], '=') == nullptr && hcmd::ParseBodyLoc(t.tok[i]) != 0) {
			spec->bodyLoc = hcmd::ParseBodyLoc(t.tok[i]);
		} else {
			return Fail(c, "%s: cannot read '%.40s'", c->verb, t.tok[i]);
		}
	}
	return true;
}

auto CmdItem(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: item <code> [stat=value ...] [q=quality] [ilvl=n] [inv|cube|ground]  (equip: h equip)");
	}
	ItemSpec s;
	if (!ParseItemSpec(c, t, &s)) {
		return false;
	}
	if (s.bodyLoc != 0) {
		return Fail(c, "item: a body location needs the equip verb");
	}
	char why[120] = "";
	Unit* item = MakeItem(c, hcmd::CodeToDword(t.tok[1]), s.quality, s.ilvl, s.page, s.stats, s.values, s.nstats, why, sizeof(why));
	if (item == nullptr) {
		return Fail(c, "%s", why);
	}
	DescribeItem(c, item);
	for (int i = 0; i < s.nstats; ++i) {
		Out("  stat %d:%d = %d", s.stats[i][0], s.stats[i][1], Stat(item, s.stats[i][0], s.stats[i][1]));
	}
	return true;
}

// `equip <code> [stat=value ...] [q=n] [ilvl=n] [uniq=n] <body location>`: creates the item with the stats set first and
// puts it on the body location (head amulet body rhand lhand rring lring belt boots gloves altr altl, or 1-12), the way
// the equip packet does: the player's stats and the item events see it equipped. The location must be free (`unequip`).
auto CmdEquip(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 3) {
		return Fail(c, "usage: equip <code> [stat=value ...] [q=n] [ilvl=n] [uniq=n] <head|amulet|body|rhand|lhand|rring|lring|belt|boots|gloves>");
	}
	ItemSpec s;
	if (!ParseItemSpec(c, t, &s)) {
		return false;
	}
	if (s.bodyLoc == 0) {
		return Fail(c, "equip: name the body location (rhand, lhand, body, head, amulet, rring, lring, belt, boots, gloves)");
	}
	char why[160] = "";
	Unit* item = MakeItem(c, hcmd::CodeToDword(t.tok[1]), s.quality, s.ilvl, 0, s.stats, s.values, s.nstats, why, sizeof(why), s.bodyLoc);
	if (item == nullptr) {
		return Fail(c, "%s", why);
	}
	DescribeItem(c, item);
	for (int i = 0; i < s.nstats; ++i) {
		Out("  stat %d:%d = %d", s.stats[i][0], s.stats[i][1], Stat(item, s.stats[i][0], s.stats[i][1]));
	}
	return true;
}


// `cuberec <index>`: hex dump of a cubemain record (0x16c bytes) for diagnosing a recipe that does not match.
auto CmdCuberec(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long index = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &index)) {
		return Fail(c, "usage: cuberec <recipe index>");
	}
	const uint8_t* rec = Fn<CubeRecordFn>(RvaCubeRecord)(c->dataFlag, static_cast<int32_t>(index));
	if (rec == nullptr) {
		return Fail(c, "cuberec: no such record");
	}
	for (int row = 0; row < 0x16c; row += 32) {
		char line[200];
		int n = std::snprintf(line, sizeof(line), "rec %04x:", row);
		for (int i = row; i < row + 32 && i < 0x16c; ++i) {
			n += std::snprintf(line + n, sizeof(line) - static_cast<size_t>(n), " %02x", rec[i]);
		}
		Out("%s", line);
	}
	return true;
}

// `cubeslots <first> <count>`: which of the three output slots (record + 0x5a + 0x5b * i) of recipes first..first+count-1 hold
// anything (a digit 0-7: bit i = slot i is filled), 50 recipes a line. A slot's tail holds -1 defaults even when the output
// cell was empty, so only its first 0x0e bytes count (quantity / code / type word and the special-output byte at +0x0d).
auto CmdCubeSlots(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long first = 0, count = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &first) || !hcmd::ParseInt(t.tok[2], &count) || first < 0 || count < 1 || count > 20000) {
		return Fail(c, "usage: cubeslots <first recipe> <count>");
	}
	char line[80];
	int n = 0;
	long long lineFirst = first;
	for (long long i = first; i < first + count; ++i) {
		const uint8_t* rec = Fn<CubeRecordFn>(RvaCubeRecord)(c->dataFlag, static_cast<int32_t>(i));
		int mask = 0;
		if (rec == nullptr) {
			return Fail(c, "cubeslots: no record %lld", i);
		}
		for (int slot = 0; slot < 3; ++slot) {
			const uint8_t* s = rec + 0x5a + 0x5b * slot;
			for (int k = 0; k < 0x0e; ++k) {
				if (s[k] != 0) {
					mask |= 1 << slot;
					break;
				}
			}
		}
		line[n++] = static_cast<char>('0' + mask);
		if (n == 50 || i == first + count - 1) {
			line[n] = '\0';
			Out("cubeslots %lld %s", lineFirst, line);
			n = 0;
			lineFirst = i + 1;
		}
	}
	return true;
}

// `cubeout <recipe> [slot]`: the executor's output dispatch (0x526d3c) for the special-output slots of a recipe (byte at slot
// +0x0d, 1-4 = portals), without inputs or conditions: handler table 0x1d3bfc0 entry byte-1, called (game, player, slot).
// Prints `cubeout <recipe> slot <i> byte <b>` per slot it called; look at `state` for the portal it opened.
auto CmdCubeOut(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long index = 0, only = -1;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &index) || (t.n > 2 && !hcmd::ParseInt(t.tok[2], &only))) {
		return Fail(c, "usage: cubeout <recipe index> [slot 0-2]");
	}
	const uint8_t* rec = Fn<CubeRecordFn>(RvaCubeRecord)(c->dataFlag, static_cast<int32_t>(index));
	if (rec == nullptr) {
		return Fail(c, "cubeout: no such record");
	}
	using OutputFn = int64_t (*)(Game*, Unit*, const uint8_t*);
	int called = 0;
	for (int slot = 0; slot < 3; ++slot) {
		const uint8_t* s = rec + 0x5a + 0x5b * slot;
		const uint8_t byte = s[0x0d];
		if ((only >= 0 && slot != only) || byte < 1 || byte > 4) {
			continue;
		}
		const uint64_t* entry = OutputHandlerSlot(g_base, byte);
		if (entry == nullptr || *entry == 0) {
			return Fail(c, "cubeout: no handler for output byte %d in the table", byte);
		}
		reinterpret_cast<OutputFn>(*entry)(c->game, c->player, s);
		Out("cubeout %lld slot %d byte %d", index, slot, byte);
		++called;
	}
	if (called == 0) {
		return Fail(c, "cubeout: recipe %lld has no portal output slot", index);
	}
	return true;
}

auto CmdCubecraft(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	int32_t result[8] = {};
	alignas(16) uint8_t ctx[512] = {};
	Fn<SearchFn>(RvaSearch)(result, c->game, c->player, ctx);
	if (reinterpret_cast<const char*>(result)[4] == 0) {
		return Fail(c, "cubecraft: no recipe matches the cube contents");
	}
	const int32_t index = result[0];
	const uint8_t* record = Fn<CubeRecordFn>(RvaCubeRecord)(c->dataFlag, index);
	Unit* out = record != nullptr ? Fn<CubeExecFn>(RvaCubeExec)(c->game, c->player, record, ctx) : nullptr;
	if (out == nullptr) {  // portal / useitem outputs return no unit: `state` shows the effect
		Out("cubecraft recipe %d ran, returned no item (portal and special outputs return none; a failed recipe puts the inputs back)", index);
		return true;
	}
	char code[5];
	ItemCode(c, out, code);
	Out("cubecraft recipe %d made item id=%u code=%s", index, IdOf(out), code);
	return true;
}

// Takes an item out of the inventory and frees it, the way the game removes a used-up tome (0x4712a0).
auto RemoveItem(Ctx* c, Unit* item) noexcept -> bool {
	int32_t location[8] = {};
	Fn<ItemLocationFn>(RvaItemLocation)(location, item);
	uint32_t unitId = IdOf(item);
	if (Fn<InvChangeFn>(RvaInvChange)(c->player, nullptr, location, nullptr, &unitId, 0, 1, 0) == 0) {
		return false;
	}
	Fn<ByteSetFn>(RvaSetByte5c)(item, 0);
	Fn<SendItemFn>(RvaSendItem)(c->game, c->player, item, 0x20, 4, 0, 0, 0, location[2]);
	Fn<ByteSetFn>(RvaSetByte5c)(item, 0);
	Fn<FreeItemFn>(RvaFreeItem)(c->game, item);
	return true;
}

// `unequip <body location>`: takes the item off that slot and frees it (RemoveItem, the same path as `remove`).
auto CmdUnequip(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const int loc = t.n >= 2 ? hcmd::ParseBodyLoc(t.tok[1]) : 0;
	if (loc == 0) {
		return Fail(c, "usage: unequip <head|amulet|body|rhand|lhand|rring|lring|belt|boots|gloves|1-12>");
	}
	Unit* found = nullptr;
	EachItem(c, [&](Unit* it) {
		int32_t where[8] = {};
		Fn<ItemLocationFn>(RvaItemLocation)(where, it);
		if (found == nullptr && where[0] == 1 && where[3] == loc) {
			found = it;
		}
	});
	if (found == nullptr) {
		return Fail(c, "unequip: nothing on body location %d", loc);
	}
	char code[5];
	ItemCode(c, found, code);
	if (!RemoveItem(c, found)) {
		return Fail(c, "unequip: the game refused to take %s off", code);
	}
	Out("unequip %d: %s removed", loc, code);
	return true;
}

auto CmdUse(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: use <item code>");
	}
	Unit* item = FindItemByCode(c, hcmd::CodeToDword(t.tok[1]), 0);
	if (item == nullptr) {
		item = FindItemByCode(c, hcmd::CodeToDword(t.tok[1]), -1);
	}
	if (item == nullptr) {
		return Fail(c, "use: no such item in the inventory");
	}
	const auto check = Fn<UseFn>(RvaUseCheck);
	if ((check(c->game, c->player, item, nullptr) & 0xff) == 0) {
		return Fail(c, "use: the game refuses to use it (check returned 0)");
	}
	Fn<UseFn>(RvaUseItem)(c->game, c->player, item, nullptr);
	const int32_t cls = Fn<UnitClassFn>(RvaUnitClass)(item, "harness", 0);
	const uint8_t* rec = Fn<ItemRecordFn>(RvaItemRecord)(c->dataFlag, cls);
	const int32_t spell = rec != nullptr ? d2r::At<int32_t>(rec, 0x94) : -1;
	const bool keep = spell >= 0 && spell < 24 && *reinterpret_cast<const uint32_t*>(g_base + RvaSpellTable + static_cast<uint64_t>(spell) * 12 + 8) == 1;
	if (!keep) {
		RemoveItem(c, item);  // used up
	}
	Out("use %s: used (pSpell %d, %s)", t.tok[1], spell, keep ? "kept" : "consumed");
	return true;
}

// `cubeclear`: removes every item from the Horadric Cube (page 3), so a recipe test starts from an empty cube.
auto CmdCubeclear(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* batch[64];
	int n = 0;
	EachItem(c, [&](Unit* it) {
		if (n < 64 && Fn<ItemByteFn>(RvaItemPage)(it) == 3) {
			batch[n++] = it;
		}
	});
	int removed = 0;
	for (int i = 0; i < n; ++i) {
		removed += RemoveItem(c, batch[i]) ? 1 : 0;
	}
	Out("cubeclear: %d items removed", removed);
	return true;
}

// `packclear`: removes every backpack item except the Horadric Cube, so created items always find room.
auto CmdPackclear(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* batch[200];
	int n = 0;
	EachItem(c, [&](Unit* it) {
		char code[5];
		ItemCode(c, it, code);
		if (n < 200 && Fn<ItemByteFn>(RvaItemPage)(it) == 0 && std::strcmp(code, "box") != 0) {
			batch[n++] = it;
		}
	});
	int removed = 0;
	for (int i = 0; i < n; ++i) {
		removed += RemoveItem(c, batch[i]) ? 1 : 0;
	}
	Out("packclear: %d items removed", removed);
	return true;
}

auto CmdRemove(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: remove <item code> [count]");
	}
	long long count = 1;
	if (t.n > 2 && !hcmd::ParseInt(t.tok[2], &count)) {
		return Fail(c, "remove: count must be a number");
	}
	int removed = 0;
	while (removed < count) {
		Unit* item = FindItemByCode(c, hcmd::CodeToDword(t.tok[1]), -1);
		if (item == nullptr || !RemoveItem(c, item)) {
			break;
		}
		++removed;
	}
	Out("remove %s: %d removed", t.tok[1], removed);
	return removed > 0 ? true : Fail(c, "remove: no such item");
}

// --- player actions without input: move, skills, casting (lane harness-cast) --------------------------------------------
// The server handlers of the client packets are PlrMsg.cpp functions of the packet table; the walk / run packets (ids 1
// and 3) are 210 bytes and carry the client's path, a path length of 0 lets the server find it. Casting calls the
// functions the cast packets (5 location, 6 unit, 0xc / 0xd right button) end in, with the Skill* looked up by id.

auto SkillIdOf(const uint8_t* skill) noexcept -> int {
	const uint8_t* row = skill != nullptr ? d2r::At<const uint8_t*>(skill, 0) : nullptr;
	return row != nullptr ? static_cast<int>(*reinterpret_cast<const int16_t*>(row)) : -1;
}
auto SkillBaseLevel(const uint8_t* skill) noexcept -> int { return skill != nullptr ? d2r::At<int32_t>(skill, 0x40) : -1; }

auto PlayerPos(Ctx* c, int32_t* x, int32_t* y) noexcept -> bool { return d2r::UnitXY(c->player, x, y); }

// Walk (id 1) or run (id 3) packet into the server handler; returns the handler's code (0 = accepted) or -1 without a handler.
auto SendWalkPacket(Ctx* c, uint8_t id, int destX, int destY) noexcept -> int64_t {
	uint8_t pkt[hcmd::WalkPacketSize];
	int32_t px = 0, py = 0;
	PlayerPos(c, &px, &py);
	const size_t n = hcmd::BuildWalkPacket(pkt, id, px, py, destX, destY);
	const uint64_t h = *reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + id * 8);
	if (h == 0) {
		return -1;
	}
	using WalkPacketFn = uint64_t (*)(Game*, Unit*, const uint8_t*, int32_t);
	return static_cast<int64_t>(reinterpret_cast<WalkPacketFn>(h)(c->game, c->player, pkt, static_cast<int32_t>(n)) & 0xffffffffU);
}

// `move <x> <y> [walk] [packet]`: server-side path move to a sub-tile position (state x / y are in the same units). Runs
// unless `walk`. Default: the call the walk packet handler ends in (0x42d2c0 with no skill and mode 2 walk / 3 run, the
// server finds the path); `packet` sends the 210 byte walk packet through the handler table instead (the handler also
// checks the position and a distance of at most 15 per packet) and prints the checks it makes.
auto CmdMove(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long x = 0, y = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &x) || !hcmd::ParseInt(t.tok[2], &y) || x < 0 || y < 0 || x > 0xffff || y > 0xffff) {
		return Fail(c, "usage: move <x> <y> [walk] [packet]   (positions as in `state`)");
	}
	bool walk = false, packet = false;
	for (int i = 3; i < t.n; ++i) {
		walk = walk || hcmd::LowerEq(t.tok[i], "walk");
		packet = packet || hcmd::LowerEq(t.tok[i], "packet");
	}
	int32_t px = 0, py = 0;
	PlayerPos(c, &px, &py);
	int64_t rc = 0;
	if (packet) {
		rc = SendWalkPacket(c, walk ? 1 : 3, static_cast<int>(x), static_cast<int>(y));
		Out("move packet checks: dead=%d position=%d (0 ok) distance=%d (<= 15) client=%p", Fn<DeadCheckFn>(RvaDeadCheck)(c->player),
		    Fn<PosCheckFn>(RvaPosCheck)(c->player, static_cast<uint32_t>(px), static_cast<uint32_t>(py), 0x32),
		    Fn<PathDistanceFn>(RvaPathDistance)(c->player, static_cast<int32_t>(x), static_cast<int32_t>(y)), Fn<UnitClientFn>(RvaUnitClientOf)(c->player));
	} else {
		rc = Fn<PlayerActionFn>(RvaPlayerAction)(c->game, c->player, nullptr, walk ? 2 : 3, static_cast<uint32_t>(x), static_cast<uint32_t>(y), 0, 0) &
		     0xffffffffLL;
	}
	Out("move from %d,%d to %lld,%lld (%s%s): code %lld, mode now %d (0 = accepted; poll `state` for the arrival)", px, py, x, y,
	    walk ? "walk" : "run", packet ? ", packet" : "", static_cast<long long>(rc), ModeOf(c->player));
	return rc == 0 ? true : Fail(c, "move: the server refused (code %lld)", static_cast<long long>(rc));
}

// `moveto <unit id> | nearest [class]`: `move` to a monster's / NPC's position (the path stops next to it).
auto CmdMoveTo(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0, cls = -1;
	Unit* u = nullptr;
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "nearest") && (t.n < 3 || hcmd::ParseInt(t.tok[2], &cls))) {
		u = NearestMonster(c, cls, false);
	} else if (t.n >= 2 && hcmd::ParseInt(t.tok[1], &id)) {
		u = FindMonsterById(c, static_cast<uint32_t>(id));
	} else {
		return Fail(c, "usage: moveto <unit id> | moveto nearest [class]");
	}
	int32_t ux = 0, uy = 0;
	if (u == nullptr || !d2r::UnitXY(u, &ux, &uy)) {
		return Fail(c, "moveto: no such live monster");
	}
	const int64_t rc = Fn<PlayerActionFn>(RvaPlayerAction)(c->game, c->player, nullptr, 3, static_cast<uint32_t>(ux), static_cast<uint32_t>(uy), 0, 0) & 0xffffffffLL;
	Out("moveto unit id=%u class=%d at %d,%d: handler code %lld, mode now %d", IdOf(u), ClassOf(u), ux, uy, static_cast<long long>(rc),
	    ModeOf(c->player));
	return rc == 0 ? true : Fail(c, "moveto: the server refused the path (code %lld)", static_cast<long long>(rc));
}

// Selects an active skill through packet 0x3c's handler; returns the skill id that is active afterwards.
auto SelectSkill(Ctx* c, long long id, bool left) noexcept -> int {
	uint8_t pkt[9];
	const size_t n = hcmd::BuildSelectSkillPacket(pkt, static_cast<int>(id), left);
	const auto handler = reinterpret_cast<PacketFn>(*reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + 0x3c * 8));
	handler(c->game, c->player, pkt, static_cast<int32_t>(n));
	return SkillIdOf(left ? Fn<ActiveSkillFn>(RvaLeftSkill)(c->player) : Fn<ActiveSkillFn>(RvaRightSkill)(c->player));
}

// `skill` prints the active skills; `skill left|right <id>` selects one (packet 0x3c's handler: the skill needs a level,
// see `setskill`, or an item that grants it).
auto CmdSkill(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 3) {
		long long id = 0;
		const bool left = hcmd::LowerEq(t.tok[1], "left");
		if ((!left && !hcmd::LowerEq(t.tok[1], "right")) || !hcmd::ParseInt(t.tok[2], &id) || id < 0 || id > 0xffff) {
			return Fail(c, "usage: skill [left|right <skill id>]");
		}
		const int now = SelectSkill(c, id, left);
		Out("skill %s %lld: active now %d", left ? "left" : "right", id, now);
		return now == id ? true : Fail(c, "skill: the game did not select %lld (no level in it? try setskill)", id);
	}
	Out("skill left=%d right=%d", SkillIdOf(Fn<ActiveSkillFn>(RvaLeftSkill)(c->player)), SkillIdOf(Fn<ActiveSkillFn>(RvaRightSkill)(c->player)));
	return true;
}

// `setskill <id> <level>`: raises the skill with the game's own skill-point function (0x438670, packet 0x3b's body without
// its prerequisite checks) with a refilled stat 5 pool each step, then restores stat 5. Lowering writes the base level.
auto CmdSetSkill(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0, level = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &id) || !hcmd::ParseInt(t.tok[2], &level) || id < 0 || id > 0xffff || level < 0 || level > 200) {
		return Fail(c, "usage: setskill <skill id> <level 0-200>");
	}
	const int pool = Stat(c->player, 5);
	const uint32_t version = d2r::At<uint8_t>(c->game, 0x106);
	uint8_t* sk = Fn<SkillByIdFn>(RvaSkillById)(c->player, static_cast<int32_t>(id), -1);
	int guard = 0;
	while (SkillBaseLevel(sk) < level && guard++ < 220) {
		Fn<SetStatFn>(RvaSetStat)(c->player, 5, 255, 0);
		if (Fn<AddSkillFn>(RvaAddSkillLevel)(version, c->player, static_cast<uint32_t>(id)) == 0) {
			break;
		}
		sk = Fn<SkillByIdFn>(RvaSkillById)(c->player, static_cast<int32_t>(id), -1);
	}
	Fn<SetStatFn>(RvaSetStat)(c->player, 5, pool, 0);
	if (sk != nullptr && SkillBaseLevel(sk) > level) {  // lowering: no game function, write the level
		*reinterpret_cast<int32_t*>(sk + 0x40) = static_cast<int32_t>(level);
	}
	const int now = sk != nullptr ? SkillBaseLevel(sk) : 0;
	Out("setskill %lld: base level %d (wanted %lld), skill points restored to %d", id, now, level, pool);
	return now == level ? true : Fail(c, "setskill: stopped at level %d (the game refused the next point)", now);
}

// `skills`: every skill of the player's list: id, base level, skill mode (+0x10, 0 = unusable as an active skill), the game's
// usability code (0x33f360: 0 usable, 1 mana / cooldown, 2 requirements, 3 not a skill, 7 no level, 8 charges).
auto CmdSkills(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	uint8_t** list = Fn<SkillListFn>(RvaSkillList)(c->player);
	int n = 0;
	for (uint8_t* sk = list != nullptr ? *list : nullptr; sk != nullptr && n < 400; sk = d2r::At<uint8_t*>(sk, 8), ++n) {
		Out("skill id=%d level=%d mode=%d owner=%d usable=%d", SkillIdOf(sk), SkillBaseLevel(sk), d2r::At<int32_t>(sk, 0x10), d2r::At<int32_t>(sk, 0x4c),
		    Fn<SkillUsableFn>(RvaSkillUsable)(c->player, sk));
	}
	Out("skills %d", n);
	return true;
}

// `skilldmg <skill id> [level] [nomastery]`: the skill's damage at that level for the player, through the damage hooks
// and through D2R's own functions (elemental and physical, min and max), with the inputs of Median's formula
// (docs/plugin-spec.md, "Skill damage scaling"): flags (1 BaseSynergy, 2 StaticDamage), the player's level, energy and
// stat 514 (Median 485), the synergy percent columns evaluated for the player, the BaseSynergy percent, the mastery stats.
auto CmdSkillDmg(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0, level = 1;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &id) || id < 0 || id > 0xffff || (t.n > 2 && !hcmd::ParseInt(t.tok[2], &level)) ||
	    level < 1 || level > 255) {
		return Fail(c, "usage: skilldmg <skill id> [level 1-255] [nomastery]");
	}
	const bool mastery = !(t.n > 3 && hcmd::LowerEq(t.tok[3], "nomastery"));
	SkillDamageSample s;
	if (!SampleSkillDamage(c->player, c->dataFlag, static_cast<int32_t>(id), static_cast<int32_t>(level), mastery ? 1 : 0, &s)) {
		return Fail(c, "skilldmg: no skill record %lld (or the skill damage hooks are off)", id);
	}
	Out("skilldmg skill=%lld level=%lld mastery=%d flags=%d clvl=%d energy=%d stat%d=%d calcElem=%d calcPhys=%d baseSyn=%d masteryElem=%d "
	    "masteryMagic=%d ele=%d-%d phys=%d-%d orig_ele=%d-%d orig_phys=%d-%d",
	    id, level, mastery ? 1 : 0, s.flags, Stat(c->player, StatLevel), Stat(c->player, 1), mxl_skill_flags::StatBaseSynergy,
	    Stat(c->player, mxl_skill_flags::StatBaseSynergy), s.calcElem, s.calcPhys, s.baseSynergy, s.masteryElem, s.masteryMagic, s.eleMin,
	    s.eleMax, s.physMin, s.physMax, s.origEleMin, s.origEleMax, s.origPhysMin, s.origPhysMax);
	return true;
}

// `cast <skill id> [x y | unit <id> | nearest [class] | self]`: uses the skill the way the cast packets do (location: 0x4fdb40,
// unit: 0x4f8de0), from the player's own skill list. No target = the player's own position. The action runs over the
// next frames: poll `state` (mode, mana) and `missiles`.
auto CmdCast(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0;
	hcmd::CastTarget tg;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &id) || id < 0 || id > 0xffff || !hcmd::ParseCastTarget(t, 2, &tg)) {
		return Fail(c, "usage: cast <skill id> [x y | unit <id> | nearest [class] | self]");
	}
	uint8_t* sk = Fn<SkillByIdFn>(RvaSkillById)(c->player, static_cast<int32_t>(id), -1);
	if (sk == nullptr) {
		return Fail(c, "cast: the player has no skill %lld (setskill %lld 1 first)", id, id);
	}
	// Both cast calls use the player's active left skill (the unit one also walks into range first): select it.
	// A right-button-only skill (rightskill 1: the itemless Town Portal) cannot be the left skill: select it as the right
	// one, and for a cast at a position go on without a selection (the call takes the skill record itself).
	if (SkillIdOf(Fn<ActiveSkillFn>(RvaLeftSkill)(c->player)) != id && SelectSkill(c, id, true) != id &&
	    SelectSkill(c, id, false) != id && (tg.kind == hcmd::CastTarget::Unit || tg.kind == hcmd::CastTarget::Nearest)) {
		return Fail(c, "cast: the game would not select skill %lld (a passive, or not usable as an active skill)", id);
	}
	const int manaBefore = Stat(c->player, StatMana) >> 8;
	int32_t px = 0, py = 0;
	PlayerPos(c, &px, &py);
	Out("cast checks: usable=%d (0 ok) busy=%d (unit +0xa8 %d, +0xac %d, +0xb0 %d) skill mode=%d unit mode=%d", Fn<SkillUsableFn>(RvaSkillUsable)(c->player, sk),
	    Fn<PlayerBusyFn>(RvaPlayerBusy)(c->player), d2r::At<int32_t>(c->player, 0xa8), d2r::At<int32_t>(c->player, 0xac),
	    d2r::At<uint8_t>(c->player, 0xb0), d2r::At<int32_t>(sk, 0x10), ModeOf(c->player));
	if (tg.kind == hcmd::CastTarget::Unit || tg.kind == hcmd::CastTarget::Nearest) {
		Unit* target = tg.kind == hcmd::CastTarget::Unit ? FindMonsterById(c, static_cast<uint32_t>(tg.id)) : NearestMonster(c, tg.cls, false);
		if (target == nullptr) {
			return Fail(c, "cast: no such live monster");
		}
		Fn<CastUnitFn>(RvaCastAtUnit)(c->game, c->player, 1, IdOf(target), sk, 1, 0);
		Out("cast skill %lld (level %d) at monster id=%u class=%d dist %.0f: mode now %d, mana %d -> %d", id, SkillBaseLevel(sk), IdOf(target),
		    ClassOf(target), DistTo(c->player, target), ModeOf(c->player), manaBefore, Stat(c->player, StatMana) >> 8);
		return true;
	}
	const uint32_t x = tg.kind == hcmd::CastTarget::Point ? static_cast<uint32_t>(tg.x) : static_cast<uint32_t>(px);
	const uint32_t y = tg.kind == hcmd::CastTarget::Point ? static_cast<uint32_t>(tg.y) : static_cast<uint32_t>(py);
	const int32_t rc = Fn<CastPointFn>(RvaCastAtPoint)(c->game, c->player, x, y, 1, sk);
	Out("cast skill %lld (level %d) at %u,%u: code %d, mode now %d, mana %d -> %d", id, SkillBaseLevel(sk), x, y, rc, ModeOf(c->player),
	    manaBefore, Stat(c->player, StatMana) >> 8);
	return rc == 0 ? true : Fail(c, "cast: the game refused the skill use (code %d; town, no mana, cooldown or busy?)", rc);
}

// `mcast <skill id> <mode> unit <id> | nearest [class]`: the monster uses the skill on the player through the AI's skill use
// (0x4a7bc0, mode as monstats Sk<n>mode: 6 = A1, 7 = A2, 9 = SC, 10 = S1). The monster must own the skill (its monstats row
// lists it). Prints the call's answer, the monster's mode and, for the cooldown check, its stat 359 at layer = skill (the end frame
// of D2R's cooldown timer) and the states 0xb9 / 0x79 the cooldown starts set; poll `state` or repeat the command.
auto CmdMonsterCast(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long skill = 0, mode = 0;
	hcmd::CastTarget tg;
	if (t.n < 4 || !hcmd::ParseInt(t.tok[1], &skill) || !hcmd::ParseInt(t.tok[2], &mode) || skill < 0 || skill > 0xffff || mode < 0 || mode > 15 ||
	    !hcmd::ParseCastTarget(t, 3, &tg) || (tg.kind != hcmd::CastTarget::Unit && tg.kind != hcmd::CastTarget::Nearest)) {
		return Fail(c, "usage: mcast <skill id> <mode 0-15> unit <id> | nearest [class]");
	}
	Unit* mon = tg.kind == hcmd::CastTarget::Unit ? FindMonsterById(c, static_cast<uint32_t>(tg.id)) : NearestMonster(c, tg.cls, false);
	if (mon == nullptr) {
		return Fail(c, "mcast: no such live monster");
	}
	const int modeBefore = ModeOf(mon);
	const int64_t rc = Fn<MonsterUseSkillFn>(RvaMonsterUseSkill)(c->game, mon, static_cast<uint32_t>(mode), static_cast<int32_t>(skill), c->player, 0, 0, 0);
	const auto hasState = Fn<UnitHasStateFn>(RvaUnitHasState);
	Out("mcast monster id=%u class=%d skill %lld mode %lld: returned %lld, unit mode %d -> %d, stat359[%lld]=%d state 0xb9=%d state 0x79=%d", IdOf(mon),
	    ClassOf(mon), skill, mode, static_cast<long long>(rc), modeBefore, ModeOf(mon), skill, Stat(mon, 359, static_cast<int>(skill)),
	    hasState(mon, 0xb9) != 0 ? 1 : 0, hasState(mon, 0x79) != 0 ? 1 : 0);
	return rc != 0 ? true : Fail(c, "mcast: the monster did not start the skill (not its skill, or the mode is not allowed)");
}

// --- missiles ---------------------------------------------------------------------------------------------------------
hcmd::SeenUnits g_missileSeen;
volatile LONG g_trackMissiles = 0;

// The missile `collide` fired: followed every server frame until it is gone (check collidetypes).
struct CollideRun {
	volatile LONG active = 0;
	volatile LONG started = 0;
	uint32_t id = 0;
	int32_t row = 0, type = 0, modeAtStart = 0;
	int32_t sx = 0, sy = 0;
	volatile int32_t lx = 0, ly = 0;
	volatile LONG frames = 0;
};
CollideRun g_run;

void TrackMissiles(Game* game) noexcept {
	const bool following = g_run.active != 0;
	bool found = false;
	EachUnit(game, HashMissiles, [&](Unit* u) {
		if (TypeOf(u) == 3) {
			g_missileSeen.Add(IdOf(u), ClassOf(u));
			if (following && IdOf(u) == g_run.id) {
				found = true;
				int32_t x = 0, y = 0;
				if (d2r::UnitXY(u, &x, &y)) {
					g_run.lx = x;
					g_run.ly = y;
				}
			}
		}
	});
	if (following) {
		if (found && g_run.frames < 4000) {
			InterlockedIncrement(&g_run.frames);
		} else {
			InterlockedExchange(&g_run.active, 0);
		}
	}
}

void PrintMissiles(Ctx* c) noexcept {
	int live = 0;
	EachUnit(c->game, HashMissiles, [&](Unit* u) {
		if (TypeOf(u) != 3) {
			return;
		}
		if (live++ < 10) {
			int32_t x = 0, y = 0;
			d2r::UnitXY(u, &x, &y);
			Out("mis id=%u class=%d mode=%d at %d,%d dist=%.0f", IdOf(u), ClassOf(u), ModeOf(u), x, y, DistTo(c->player, u));
		}
	});
	char sum[160];
	g_missileSeen.Summary(sum, sizeof(sum));
	Out("missiles live=%d seen=%d%s tracking=%s [%s]", live, g_missileSeen.n, g_missileSeen.overflow > 0 ? "+" : "",
	    g_trackMissiles != 0 ? "on" : "off (missiles reset starts it)", sum);
}

// `missiles`: live missile units and the distinct ones seen since `missiles reset` (every server frame is sampled while
// tracking, so a short-lived missile is counted). `missiles reset` clears the count and starts tracking.
auto CmdMissiles(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 2) {
		if (!hcmd::LowerEq(t.tok[1], "reset")) {
			return Fail(c, "usage: missiles [reset]");
		}
		g_missileSeen.Reset();
		InterlockedExchange(&g_trackMissiles, 1);
	}
	PrintMissiles(c);
	return true;
}

// `collide <row> <dx> <dy> [type]`: a missile of missiles.txt row <row> from the player towards (player + dx, dy) like `missile`,
// then followed every server frame (`collide result`): frames alive and where it was last seen. [type] overwrites the missile's
// collision type (the unit's mode, which the server tick 0x463100 reads to pick a row of the collide table, collide_types.cpp)
// right after the creation, so one plain projectile (row 0, the arrow: type 3) can be fired as every type.
// `collide result`: the last run: id, row, type, mode when created, still flying, frames, start and last position, distance.
auto PrintCollideRun() noexcept -> void {
	const double dx = static_cast<double>(g_run.lx) - g_run.sx, dy = static_cast<double>(g_run.ly) - g_run.sy;
	Out("collide result: started=%ld id=%u row=%d type=%d mode0=%d flying=%d frames=%ld start=%d,%d last=%d,%d dist=%.0f", g_run.started, g_run.id,
	    g_run.row, g_run.type, g_run.modeAtStart, g_run.active != 0 ? 1 : 0, g_run.frames, g_run.sx, g_run.sy, static_cast<int>(g_run.lx),
	    static_cast<int>(g_run.ly), std::sqrt(dx * dx + dy * dy));
}

auto CmdCollide(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "result")) {
		PrintCollideRun();
		return true;
	}
	long long row = 0, dx = 0, dy = 0, type = -1;
	if (t.n < 4 || !hcmd::ParseInt(t.tok[1], &row) || !hcmd::ParseInt(t.tok[2], &dx) || !hcmd::ParseInt(t.tok[3], &dy) || row < 0 ||
	    row > 0x7fff || (t.n >= 5 && (!hcmd::ParseInt(t.tok[4], &type) || type < 0 || type > 255))) {
		return Fail(c, "usage: collide <missiles.txt row> <dx> <dy> [collision type 0-255] | collide result");
	}
	int32_t px = 0, py = 0;
	if (!d2r::UnitXY(c->player, &px, &py)) {
		return Fail(c, "collide: player has no position");
	}
	d2r::MissileParams params;
	std::memset(&params, 0, sizeof(params));
	params.flags = 0x820;
	params.owner = c->player;
	params.origin = c->player;
	params.missile = static_cast<int32_t>(row);
	params.targetX = px + static_cast<int32_t>(dx);
	params.targetY = py + static_cast<int32_t>(dy);
	Unit* m = d2r::api.createMissile(c->game, &params);
	if (m == nullptr) {
		return Fail(c, "collide: createMissile returned no unit");
	}
	InterlockedExchange(&g_run.active, 0);
	g_run.id = IdOf(m);
	g_run.row = static_cast<int32_t>(row);
	g_run.modeAtStart = ModeOf(m);
	if (type >= 0) {
		*reinterpret_cast<int32_t*>(reinterpret_cast<uint8_t*>(m) + UnitMode) = static_cast<int32_t>(type);
	}
	g_run.type = ModeOf(m);
	g_run.sx = g_run.lx = px;
	g_run.sy = g_run.ly = py;
	InterlockedExchange(&g_run.frames, 0);
	InterlockedIncrement(&g_run.started);
	InterlockedExchange(&g_trackMissiles, 1);
	InterlockedExchange(&g_run.active, 1);
	const uint8_t* record = Fn<const uint8_t* (*)(uint32_t, int32_t)>(0x166040)(c->dataFlag, static_cast<int32_t>(row));
	Out("collide: missile row %lld id=%u created at %d,%d aimed %d,%d; record CollideType %d, mode on creation %d, type now %d", row, g_run.id, px, py,
	    params.targetX, params.targetY, record != nullptr ? d2r::At<uint8_t>(record, 0x1ab) : -1, g_run.modeAtStart, g_run.type);
	return true;
}

// `collidetable`: the rows of the collide tables the server and client read now (types 0-10 and 255): check function RVA and
// mask (collide_types.cpp: 9 and 10 are Median's). `collidetable rows`: how many missiles.txt rows have each CollideType;
// `collidetable row <n>`: the CollideType of one row.
auto CmdCollideTable(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "rows")) {
		const auto record = Fn<const uint8_t* (*)(uint32_t, int32_t)>(0x166040);
		const int32_t rows = Fn<int32_t (*)(uint32_t)>(0x1b89a0)(c->dataFlag);
		int count[256] = {};
		int first[256];
		for (int& f : first) {
			f = -1;
		}
		for (int32_t row = 0; row < rows; ++row) {
			const uint8_t* r = record(c->dataFlag, row);
			if (r != nullptr) {
				const uint8_t type = d2r::At<uint8_t>(r, 0x1ab);
				if (count[type]++ == 0) {
					first[type] = row;
				}
			}
		}
		char line[320] = "";
		for (int type = 0; type < 256; ++type) {
			if (count[type] > 0 && std::strlen(line) < sizeof(line) - 24) {
				std::snprintf(line + std::strlen(line), sizeof(line) - std::strlen(line), " %d:%d(first row %d)", type, count[type], first[type]);
			}
		}
		Out("collidetable rows: %d rows, by CollideType:%s", rows, line);
		return true;
	}
	if (t.n >= 3 && hcmd::LowerEq(t.tok[1], "row")) {
		long long row = 0;
		if (!hcmd::ParseInt(t.tok[2], &row) || row < 0 || row > 0x7fff) {
			return Fail(c, "usage: collidetable row <missiles.txt row>");
		}
		const uint8_t* r = Fn<const uint8_t* (*)(uint32_t, int32_t)>(0x166040)(c->dataFlag, static_cast<int32_t>(row));
		long loads = 0, restored = 0;
		CollideRecordStats(&loads, &restored);
		Out("collidetable row %lld: CollideType %d (table loads seen %ld, records restored %ld)", row, r != nullptr ? d2r::At<uint8_t>(r, 0x1ab) : -1, loads,
		    restored);
		return true;
	}
	for (const bool server : {true, false}) {
		char line[400] = "";
		bool installed = true;
		for (const int type : {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 255}) {
			uint64_t fn = 0;
			uint32_t mask = 0;
			if (!CollideTypeRow(server, type, &fn, &mask)) {
				installed = false;
				break;
			}
			std::snprintf(line + std::strlen(line), sizeof(line) - std::strlen(line), " %d:%llx/%x", type, static_cast<unsigned long long>(fn), mask);
		}
		Out("collidetable %s: %s%s", server ? "server" : "client", installed ? "tables moved" : "tables NOT moved (engine's nine rows)", installed ? line : "");
	}
	return true;
}

// `wallscan [max]`: for the eight directions from the player, the distance in sub-tiles to the first cell the missile tick treats as
// a wall (collision flag 4 of 0x364d50, the bit that ends a missile of CollideType 1-3, 5, 8) within max (default 24). The
// last line names the best direction (a wall at 6-20 sub-tiles): `wallscan best dx dy wall=<k>`.
auto CmdWallScan(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long maxDist = 24;
	if (t.n >= 2 && (!hcmd::ParseInt(t.tok[1], &maxDist) || maxDist < 4 || maxDist > 60)) {
		return Fail(c, "usage: wallscan [max sub-tiles 4-60]");
	}
	void* room0 = Fn<UnitRoomFn>(RvaUnitRoom)(c->player);
	int32_t px = 0, py = 0;
	if (room0 == nullptr || !d2r::UnitXY(c->player, &px, &py)) {
		return Fail(c, "wallscan: the player has no room");
	}
	const auto roomAt = Fn<void* (*)(void*, int32_t, int32_t)>(0x38dfb0);
	const auto collide = Fn<uint32_t (*)(void*, int32_t, int32_t, int32_t, uint32_t)>(0x364d50);
	static const int Dirs[8][2] = {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}};
	int bestDir = -1, bestWall = 0;
	for (int d = 0; d < 8; ++d) {
		int wall = 0, seen = 0;
		for (int k = 1; k <= maxDist; ++k) {
			const int32_t x = px + Dirs[d][0] * k, y = py + Dirs[d][1] * k;
			void* room = roomAt(room0, x, y);
			if (room == nullptr) {
				break;
			}
			++seen;
			if ((collide(room, x, y, 1, 4) & 4) != 0) {
				wall = k;
				break;
			}
		}
		// room cells past the wall: a wall at the edge of the map (no room beyond) ends any missile, so it proves nothing
		int beyond = 0;
		for (int k = wall + 1; wall > 0 && k <= wall + 10; ++k) {
			if (roomAt(room0, px + Dirs[d][0] * k, py + Dirs[d][1] * k) == nullptr) {
				break;
			}
			++beyond;
		}
		Out("wallscan dir=%d,%d wall=%d cells=%d beyond=%d", Dirs[d][0], Dirs[d][1], wall, seen, beyond);
		if (wall >= 6 && wall <= 20 && beyond >= 10 && (bestDir < 0 || wall > bestWall)) {
			bestDir = d;
			bestWall = wall;
		}
	}
	if (bestDir < 0) {
		Out("wallscan best none at %d,%d", px, py);
	} else {
		Out("wallscan best %d %d wall=%d at %d,%d", Dirs[bestDir][0], Dirs[bestDir][1], bestWall, px, py);
	}
	return true;
}

// `hasstate <state>`: the player's state bit, the state's stat list and the end frame it carries (the float at list +0x24), and
// the game frame now (check skillstarts).
auto CmdHasState(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long state = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &state) || state < 0 || state > 4000) {
		return Fail(c, "usage: hasstate <state id>");
	}
	const uint64_t on = Fn<UnitHasStateFn>(RvaUnitHasState)(c->player, static_cast<int32_t>(state));
	void* list = Fn<void* (*)(Unit*, int32_t)>(0x2f5940)(c->player, static_cast<int32_t>(state));
	Out("hasstate %lld: %d list=%s expiry=%.0f frame=%u", state, on != 0 ? 1 : 0, list != nullptr ? "yes" : "no",
	    list != nullptr ? static_cast<double>(d2r::At<float>(list, 0x24)) : 0.0, d2r::At<uint32_t>(c->game, GameFrame));
	return true;
}

// `startfn <slot> <skill id> [level]`: the server start function table (0x238e710) entry the way the cast path calls it
// (game, player, skill, level); prints its answer (0 = the cast would stop). `startstats`: the plugin's counters for slots 71 / 72.
auto CmdStartFn(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long slot = 0, skill = 0, level = 1;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &slot) || !hcmd::ParseInt(t.tok[2], &skill) || slot < 0 || slot > 90 || skill < 0 || skill > 0xffff ||
	    (t.n >= 4 && (!hcmd::ParseInt(t.tok[3], &level) || level < 1 || level > 255))) {
		return Fail(c, "usage: startfn <slot 0-90> <skill id> [level]");
	}
	const uint64_t fn = *reinterpret_cast<const uint64_t*>(g_base + 0x238e710 + static_cast<uint64_t>(slot) * 8);
	if (fn == 0) {
		Out("startfn slot %lld: empty (the cast goes on)", slot);
		return true;
	}
	const int64_t r = reinterpret_cast<int64_t (*)(Game*, Unit*, int32_t, int32_t)>(fn)(c->game, c->player, static_cast<int32_t>(skill),
	                                                                                    static_cast<int32_t>(level));
	Out("startfn slot %lld skill %lld level %lld: returned %lld frame=%u", slot, skill, level, static_cast<long long>(r),
	    d2r::At<uint32_t>(c->game, GameFrame));
	return true;
}

auto CmdStartStats(Ctx* /*c*/, const hcmd::Tokens& /*t*/) noexcept -> bool {
	char text[240];
	SkillStartStats(text, sizeof(text));
	Out("startstats: %s", text);
	return true;
}

// `dump player|client|mon <class>|ground`: raw memory for the RE work behind the plugin's own offsets (player name,
// monstats treasure class fields, items on the ground).
void HexDump(const char* label, const uint8_t* p, int len) noexcept {
	for (int off = 0; off < len; off += 32) {
		char hex[120];
		int n = 0;
		for (int i = 0; i < 32 && off + i < len; ++i) {
			n += std::snprintf(hex + n, sizeof(hex) - static_cast<size_t>(n), "%02x%s", p[off + i], i % 4 == 3 ? " " : "");
		}
		Out("%s+%03x %s", label, off, hex);
	}
}

auto CmdDump(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: dump player | dump client | dump mon <class> | dump ground");
	}
	if (hcmd::LowerEq(t.tok[1], "player")) {
		const auto* data = Fn<PlayerDataFn>(RvaPlayerData)(c->player);
		Out("player unit %p, data %p, unit+0x10 %p", static_cast<void*>(c->player), static_cast<const void*>(data),
		    d2r::At<void*>(c->player, 0x10));
		if (data != nullptr) {
			HexDump("pdata", data, 0x80);
		}
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "client")) {
		int guard = 0;
		for (auto* client = d2r::At<uint8_t*>(c->game, GameClients); client != nullptr && guard < 64;
		     client = d2r::At<uint8_t*>(client, ClientNext), ++guard) {
			Out("client %p state %d", static_cast<void*>(client), d2r::At<int32_t>(client, ClientState));
			HexDump("client", client, 0x200);
		}
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "mon")) {
		long long cls = 0;
		if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &cls)) {
			return Fail(c, "usage: dump mon <class>");
		}
		const auto* rec = Fn<ItemRecordFn>(0x976e0)(c->dataFlag, static_cast<int32_t>(cls));
		if (rec == nullptr) {
			return Fail(c, "dump mon: no monstats row");
		}
		HexDump("monstats", rec, 0x200);
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "ground")) {  // `dump ground nogold` leaves the gold piles out
		const bool noGold = t.n > 2 && hcmd::LowerEq(t.tok[2], "nogold");
		int n = 0;
		EachUnit(c->game, HashItems, [&](Unit* it) {
			if (TypeOf(it) != 4 || n >= 400 || (ModeOf(it) != 3 && ModeOf(it) != 5)) {  // the character's own items are not "ground"
				return;
			}
			int32_t x = 0, y = 0;
			d2r::UnitXY(it, &x, &y);
			char code[5];
			ItemCode(c, it, code);
			if (noGold && std::strncmp(code, "gld", 3) == 0) {
				return;
			}
			++n;
			const auto* data = Fn<ItemDataFn>(0x34a500)(it);
			const uint32_t flags = data != nullptr ? d2r::At<uint32_t>(data, 0x18) : 0;
			Out("ground id=%u code=%s class=%d mode=%d at %d,%d ilvl=%d quality=%d identified=%d", IdOf(it), code, ClassOf(it), ModeOf(it), x, y,
			    static_cast<int>(Fn<ItemLevelFn>(RvaItemLevel)(it)), data != nullptr ? d2r::At<int32_t>(data, 0) : -1, (flags & 0x10) != 0 ? 1 : 0);
		});
		Out("ground items %d (mode 3 or 5 = on the ground)", n);
		return true;
	}
	return Fail(c, "dump: player | client | mon <class> | ground");
}

// `merc`: the player's mercenary unit and every item in its inventory (equipped ones have page 255).
constexpr uint64_t RvaFindMerc = 0x4ff1a0;     // (game, player, 7, 0) -> the player's mercenary unit or null
constexpr uint64_t RvaNpcMercList = 0x502b70;  // (game, npc, &scratch) -> list: entries pointer at +0x18, count at +0x20
constexpr uint64_t RvaClientOf = 0x48fde0;     // (player) -> its client record
constexpr uint64_t RvaOpenHireList = 0x540640; // (game, client, npc): fills the NPC's mercenary list and tells the client
constexpr uint64_t RvaHireCost = 0x3c17b0;     // (expansion, player, hireling id, npc row byte +10, difficulty, &out): out[5] = price
using FindMercFn = Unit* (*)(Game*, Unit*, int32_t, int32_t);
using MercListFn = uint8_t* (*)(Game*, Unit*, void*);
using HireCostFn = int32_t (*)(int32_t, Unit*, uint32_t, uint8_t, uint32_t, uint32_t*);

// `mercprice [level]`: the revive price of the player's mercenary from D2R's price function 0x3c1ad0 (the one the NPC dialog
// and the charge call), at the level given (the mercenary's level stat is put back afterwards), next to Median's formula.
constexpr uint64_t RvaRevivePrice = 0x3c1ad0;  // (merc, not classic, hireling id) -> gold
using RevivePriceFn = int32_t (*)(Unit*, int32_t, int32_t);

auto CmdMercPrice(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	Unit* merc = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
	if (merc == nullptr) {
		return Fail(c, "mercprice: the player has no mercenary");
	}
	const int32_t was = Stat(merc, StatLevel);
	long long level = was;
	if (t.n >= 2 && !hcmd::ParseInt(t.tok[1], &level)) {
		return Fail(c, "usage: mercprice [level]");
	}
	Fn<SetStatFn>(RvaSetStat)(merc, StatLevel, static_cast<int32_t>(level), 0);
	const int32_t price = Fn<RevivePriceFn>(RvaRevivePrice)(merc, 1, 0);
	Fn<SetStatFn>(RvaSetStat)(merc, StatLevel, was, 0);
	const int32_t expected = hire::RevivePrice(static_cast<int32_t>(level));
	Out("mercprice level=%lld price=%d median=%d", level, price, expected);
	return price == expected;
}

// `players [n]`: D2R's "Offline Difficulty Scaling" setting, the number the /players chat command sets (1-8): what the monster
// setup 0x543e90 reads as the players count of a monster spawned from now on. The chat command also saves the setting
// (0xa07670); this verb does not. Prints the value now.
constexpr uint64_t RvaPlayersSetting = 0xe19e0;     // () -> the setting object; the value at +0xc
constexpr uint64_t RvaPlayersSettingSet = 0xd2f020; // (setting, value)

auto CmdPlayers(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	void* setting = Fn<void* (*)()>(RvaPlayersSetting)();
	if (setting == nullptr) {
		return Fail(c, "players: no setting object");
	}
	if (t.n >= 2) {
		long long n = 0;
		if (!hcmd::ParseInt(t.tok[1], &n) || n < 1 || n > 8) {
			return Fail(c, "usage: players [1-8]");
		}
		Fn<void (*)(void*, int32_t)>(RvaPlayersSettingSet)(setting, static_cast<int32_t>(n));
	}
	Out("players setting=%d", d2r::At<int32_t>(setting, 0xc));
	return true;
}

// `tctrace [reset]`: the class lookups of the treasure-class executor since start (or the last reset): the level it handed
// the class getter 0x397290 is above 0 only when the monster's level steps the class up (Median: in Normal too).
auto CmdTcTrace(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	(void)c;
	const TcTrace tc = NormalTcTrace(t.n >= 2 && hcmd::LowerEq(t.tok[1], "reset"));
	Out("tctrace calls=%d leveled=%d lastclass=%d lastlevel=%d", tc.calls, tc.leveled, tc.lastClass, tc.lastLevel);
	return true;
}

// `leash [distance]`: the player's mercenary against its owner. With a distance, moves the MERCENARY (the unit move 0x491ca0,
// as `interact` does for the player) to a free spot that far from the player, along an axis or a diagonal: moving the player
// pulls the mercenary along at once, whatever the leash. Prints both positions, the distance D2R's own owner-distance function
// 0x596720 gives, the Euclidean one, and the mercenary's mode.
constexpr uint64_t RvaOwnerDistance = 0x596720;  // (unit, owner) -> sub-tile distance
using OwnerDistanceFn = int32_t (*)(Unit*, Unit*);

auto CmdLeash(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	Unit* merc = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
	if (merc == nullptr) {
		return Fail(c, "leash: the player has no mercenary");
	}
	long long want = -1;
	if (t.n >= 2 && (!hcmd::ParseInt(t.tok[1], &want) || want < 0 || want > 200)) {
		return Fail(c, "usage: leash [distance 0-200]");
	}
	int32_t px = 0, py = 0;
	d2r::UnitXY(c->player, &px, &py);
	if (want >= 0) {
		static const double dir[][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {0.7071, 0.7071}, {-0.7071, 0.7071}, {0.7071, -0.7071}, {-0.7071, -0.7071}};
		bool moved = false;
		for (const auto& d : dir) {
			const int32_t x = px + static_cast<int32_t>(std::lround(d[0] * static_cast<double>(want)));
			const int32_t y = py + static_cast<int32_t>(std::lround(d[1] * static_cast<double>(want)));
			if (x < 0 || y < 0 || Fn<BlockedFn>(RvaMoveBlocked)(merc, x, y, 0x804) != 0) {
				continue;
			}
			Fn<MoveFn>(RvaMove)(c->game, merc, 0, x, y, 0, 0);
			int32_t mx = 0, my = 0;
			d2r::UnitXY(merc, &mx, &my);
			if (mx == x && my == y) {
				moved = true;
				break;
			}
		}
		if (!moved) {
			return Fail(c, "leash: no free spot %lld sub-tiles from the player", want);
		}
	}
	int32_t mx = 0, my = 0;
	d2r::UnitXY(merc, &mx, &my);
	Out("leash merc id=%u at %d,%d player at %d,%d distance=%d euclid=%.1f mode=%d", IdOf(merc), mx, my, px, py,
	    Fn<OwnerDistanceFn>(RvaOwnerDistance)(merc, c->player),
	    std::sqrt(static_cast<double>((mx - px) * (mx - px) + (my - py) * (my - py))), ModeOf(merc));
	return true;
}

auto CmdMerc(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* merc = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
	if (merc == nullptr) {
		return Fail(c, "merc: the player has no mercenary");
	}
	Out("merc id=%u class=%d level=%d mode=%d life=%d/%d", IdOf(merc), ClassOf(merc), Stat(merc, StatLevel), ModeOf(merc),
	    Stat(merc, StatLife) >> 8, Stat(merc, 7) >> 8);
	int items = 0;
	EachItemOf(merc, [&](Unit* it) {
		++items;
		DescribeItem(c, it);
	});
	Out("merc items %d", items);
	return true;
}

// `mercreq`: the item requirement check (0x36bc50, the one item_gen.cpp hooks) of every backpack item against the player's
// mercenary: whether Median's mercenary lists (class lock, weapon / shield types) let it be equipped.
constexpr uint64_t RvaRequirement = 0x36bc50;  // (item, unit, flag, &str, &dex, &level, flag2) -> 1 usable
using RequirementFn = uint64_t (*)(Unit*, Unit*, int32_t, uint32_t*, uint32_t*, uint32_t*, int32_t);

auto CmdMercReq(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Unit* merc = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
	if (merc == nullptr) {
		return Fail(c, "mercreq: the player has no mercenary");
	}
	int n = 0;
	EachItemOf(c->player, [&](Unit* it) {
		if (Fn<ItemByteFn>(RvaItemPage)(it) != 0) {
			return;
		}
		char code[5];
		ItemCode(c, it, code);
		uint32_t str = 9, dex = 9, level = 9;
		const uint64_t r = Fn<RequirementFn>(RvaRequirement)(it, merc, 0, &str, &dex, &level, 0);
		Out("mercreq code=%s usable=%d str=%u dex=%u level=%u", code, static_cast<int>(r & 0xff), str, dex, level);
		++n;
	});
	Out("mercreq items %d", n);
	return true;
}

// `hire [npc class] [n] [reopen]`: hires the n-th (default first) free mercenary of the nearest hirer the way the client's hire
// button does: packet 0x36 (npc id, list index, price, current mercenary id or -1) into the server handler. `reopen` makes the
// list again first (what the client's hire menu does) even when the NPC already has one made long ago.
auto CmdHire(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = -1, which = 0;
	const bool reopen = t.n > 3 && hcmd::LowerEq(t.tok[3], "reopen");
	if ((t.n > 1 && !hcmd::ParseInt(t.tok[1], &cls)) || (t.n > 2 && !hcmd::ParseInt(t.tok[2], &which)) || (t.n > 3 && !reopen)) {
		return Fail(c, "usage: hire [npc class] [n] [reopen]");
	}
	Unit* npc = NearestMonster(c, cls, true);
	if (npc == nullptr) {
		return Fail(c, "hire: no such NPC alive in this area");
	}
	uint8_t scratch[64] = {};
	const uint8_t* list = Fn<MercListFn>(RvaNpcMercList)(c->game, npc, scratch);
	const uint8_t* npcRow = static_cast<const uint8_t*>(Fn<NpcRecordFn>(RvaNpcRecord)(c->dataFlag, ClassOf(npc)));
	if (list == nullptr || npcRow == nullptr) {
		return Fail(c, "hire: the NPC has no mercenary list");
	}
	if (reopen || d2r::At<uint64_t>(list, 0x20) == 0) {  // the list is made when the player opens the hire menu: do what that does
		void* client = Fn<void* (*)(Unit*)>(RvaClientOf)(c->player);
		Fn<void (*)(Game*, void*, Unit*)>(RvaOpenHireList)(c->game, client, npc);
		list = Fn<MercListFn>(RvaNpcMercList)(c->game, npc, scratch);
		if (list == nullptr) {
			return Fail(c, "hire: the NPC has no mercenary list");
		}
	}
	const auto* entries = d2r::At<const uint8_t*>(list, 0x18);
	const uint64_t count = d2r::At<uint64_t>(list, 0x20);
	Out("hire: %llu list entries", static_cast<unsigned long long>(count));
	long long seen = 0;
	for (uint64_t i = 0; entries != nullptr && i < count && i < 64; ++i) {
		const uint8_t* e = entries + i * 0x10;
		const uint32_t hired = d2r::At<uint32_t>(e, 8), avail = d2r::At<uint32_t>(e, 0xc);
		Out("hire: entry %llu index=%u id=%u hired=%u avail=%u", static_cast<unsigned long long>(i), d2r::At<uint16_t>(e, 0),
		    d2r::At<uint32_t>(e, 4), hired, avail);
		if (hired != 0 || avail == 0 || seen++ != which) {
			continue;
		}
		uint32_t out[16] = {};
		if (Fn<HireCostFn>(RvaHireCost)(c->dataFlag != 1 ? 1 : 0, c->player, d2r::At<uint32_t>(e, 4), npcRow[10],
		                                 d2r::At<uint8_t>(c->game, 0x104), out) == 0) {
			return Fail(c, "hire: price lookup failed");
		}
		Unit* merc = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 1);
		uint8_t pkt[17] = {0x36};
		const uint32_t id = IdOf(npc), index = d2r::At<uint16_t>(e, 0), cost = out[5], mercId = merc != nullptr ? IdOf(merc) : 0xffffffffU;
		std::memcpy(pkt + 1, &id, 4);
		std::memcpy(pkt + 5, &index, 4);
		std::memcpy(pkt + 9, &cost, 4);
		std::memcpy(pkt + 13, &mercId, 4);
		Out("hire: entry %llu, price %u, gold %d, npc %u at distance %.0f, player mode %d, current mercenary id %u", static_cast<unsigned long long>(i),
		    cost, Stat(c->player, StatGold), id, DistTo(c->player, npc), ModeOf(c->player), mercId);
		if (Stat(c->player, StatGold) < static_cast<int32_t>(cost)) {
			Fn<SetStatFn>(RvaSetStat)(c->player, StatGold, static_cast<int32_t>(cost) + 1000, 0);
		}
		const auto handler = reinterpret_cast<PacketFn>(*reinterpret_cast<const uint64_t*>(g_base + RvaPacketTable + 0x36 * 8));
		handler(c->game, c->player, pkt, 17);
		Unit* now = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
		Out("hire: mercenary now %s (class %d)", now != nullptr ? "present" : "absent", now != nullptr ? ClassOf(now) : -1);
		return now != nullptr ? true : Fail(c, "hire: the server did not hire (see the log)");
	}
	return Fail(c, "hire: no free entry %lld", which);
}

// --- verify verbs (docs/testing.md "Verify checks"): hit, avoid, itemroll, colour, req, cstat; unit references --------------
// A unit reference is "player", "merc" (the player's mercenary) or "mon:<unit id>" (hcmd::ParseUnitRef).
// The nearest live monster that can fight the player: not a town NPC (an NPC as the attacker of a hit does no damage: the hit step
// ends with result 0, see CmdHit) and not the player's own mercenary. `kill nearest` and the others keep using NearestMonster.
auto NearestFighter(Ctx* c) noexcept -> Unit* {
	Unit* merc = Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
	Unit* best = nullptr;
	double bestD = 1e18;
	EachUnit(c->game, HashMonsters, [&](Unit* u) {
		if (TypeOf(u) != 1 || !IsAlive(u) || u == merc || Fn<NpcRecordFn>(RvaNpcRecord)(c->dataFlag, ClassOf(u)) != nullptr) {
			return;
		}
		const double d = DistTo(c->player, u);
		if (d < bestD) {
			bestD = d;
			best = u;
		}
	});
	return best;
}

auto ResolveRef(Ctx* c, const char* text) noexcept -> Unit* {
	hcmd::UnitRef ref;
	if (!hcmd::ParseUnitRef(text, &ref)) {
		return nullptr;
	}
	switch (ref.kind) {
		case hcmd::UnitRef::Player:
			return c->player;
		case hcmd::UnitRef::Merc:
			return Fn<FindMercFn>(RvaFindMerc)(c->game, c->player, 7, 0);
		case hcmd::UnitRef::Monster:
			return FindMonsterById(c, static_cast<uint32_t>(ref.id));
		default:
			return nullptr;
	}
}

constexpr uint64_t RvaHitUnit = 0x44ce80;      // (game, attacker, target, 1, &damage)
constexpr uint64_t RvaApplyDamage = 0x44a9b0;  // (game, attacker, target, &damage)
constexpr uint64_t RvaAvoidCheck = 0x44ef70;   // (attacker unit, defender unit, missile flag) -> 0 / 2 / 4 / 8 / 0x10
constexpr uint64_t RvaAllocator = 0x12063c0;   // -> allocator object; vtable +0x20 frees
constexpr uint64_t RvaItemColour = 0x3710d0;   // (player, item, &colour byte, mode) -> palette entry
constexpr uint64_t RvaItemAutomagic = 0x36ca80;  // (item) -> automagic affix id (0 = none)
constexpr uint64_t RvaItemQuality = 0x36cf60;    // (item) -> quality
constexpr uint64_t RvaIsItemType = 0x373890;   // (item, type id) -> nonzero when the item is of that type
constexpr int ItemFlagsOffset = 0x18;          // item data: flag word (0x400000 ethereal, 0x800 socketed, 0x10 identified)
constexpr uint32_t ItemFlagEthereal = 0x400000;
constexpr int StatSockets = 194, StatDefence = 31, StatMaxDurabilityItem = 0x49, StatDye = 368, StatClassLock = 492;
using ItemQualityFn = int32_t (*)(Unit*);
using ItemAutomagicFn = uint32_t (*)(Unit*);
using HitUnitFn = void (*)(Game*, Unit*, Unit*, int32_t, void*);
using ApplyDamageFn = void (*)(Game*, Unit*, Unit*, void*);
using AvoidCheckFn = int32_t (*)(Unit* attacker, Unit* defender, int32_t missile);
constexpr uint64_t RvaUnitDataFlag = 0x34a0e0;  // (unit) -> data bank flag byte
using UnitDataFlagFn = uint8_t (*)(Unit* unit);
using AllocatorFn = void** (*)();
using AllocFreeFn = void (*)(void*, void*);
using DamageDestroyFn = void (*)(void*, int32_t);
using ItemColourFn = int64_t (*)(Unit*, Unit*, uint8_t*, int32_t);
using IsItemTypeFn = int32_t (*)(Unit*, int32_t);

// D2R's damage block (0x180 bytes), set up and torn down the way area_damage.cpp does it.
struct alignas(16) DamageBlock {
	uint8_t b[0x180];
};

template <typename T>
auto DmgField(DamageBlock& d, int off) noexcept -> T& {
	return *reinterpret_cast<T*>(d.b + off);
}

void DamageInit(DamageBlock& d) noexcept {
	std::memset(d.b, 0, sizeof(d.b));
	DmgField<uint8_t*>(d, 0x40) = d.b + 0x58;
	DmgField<uint64_t>(d, 0x50) = 0x8000000000000010ULL;
	DmgField<uint64_t>(d, 0x158) = 1;
}

void DamageFreeBlock(void* block) noexcept {
	void** allocator = Fn<AllocatorFn>(RvaAllocator)();
	reinterpret_cast<AllocFreeFn>(reinterpret_cast<void**>(*allocator)[4])(allocator, block);
}

void DamageDestroy(DamageBlock& d) noexcept {
	uint64_t& callback = DmgField<uint64_t>(d, 0x158);
	void* object = (callback & 1) == 0 ? static_cast<void*>(&callback) : reinterpret_cast<void*>(callback & ~1ULL);
	if (object != nullptr) {
		reinterpret_cast<DamageDestroyFn>((*static_cast<void***>(object))[0])(object, 0);
		if ((callback & 1) != 0) {
			DamageFreeBlock(reinterpret_cast<void*>(callback & ~1ULL));
		}
		callback = 1;
	}
	if (static_cast<int64_t>(DmgField<uint64_t>(d, 0x50)) >= 0) {
		DamageFreeBlock(DmgField<void*>(d, 0x40));
	}
}

auto FlagsOf(Unit* item) noexcept -> uint32_t {
	const auto* data = Fn<ItemDataFn>(RvaItemData)(item);
	return data != nullptr ? d2r::At<uint32_t>(data, ItemFlagsOffset) : 0;
}

// `hit <target ref> phys|fire|ltng|magic|cold|pois|life|mana|stam|clen|flen|plen <amount> [attacker ref] [stagger]`: one hit of that damage through D2R's hit and apply
// steps (0x44ce80, 0x44a9b0; the same pair the area damage hook uses), so the resist step 0x4523e0 and the absorb step
// 0x450670 run. The amount goes into the damage block's field as is. Attacker: the player; for the player as target the
// nearest live monster that can fight (not a town NPC, not the mercenary: their hits do no damage; else the player itself). `stagger` sets the result flag 4 (hit recovery) between the two steps, so the
// target enters its GetHit mode even when its hit recovery would not (bosses): the monster's last-mode field then reads 3 after it.
// `field=` is the element's field right after the hit step (what is left of `amount` after resist, absorb and Median's stats
// 184 / 189 / 417); for clen / flen / plen (cold, freeze and poison length) it is the shortened duration.
auto CmdHit(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	struct Elem {
		const char* name;
		int offset;
		int hitClass;
	};
	static const Elem elems[] = {{"phys", 0x18, 0}, {"fire", 0x20, 0x20}, {"ltng", 0x2c, 0x40}, {"magic", 0x30, 0}, {"cold", 0x34, 0x30},
	                          {"pois", 0x38, 0}, {"life", 0x120, 0}, {"mana", 0x124, 0}, {"stam", 0x128, 0}, {"clen", 0x118, 0},
	                          {"flen", 0x11c, 0}, {"plen", 0x3c, 0}};
	long long amount = 0;
	if (t.n < 4 || !hcmd::ParseInt(t.tok[3], &amount) || amount < 0) {
		return Fail(c, "usage: hit <player|merc|mon:id> phys|fire|ltng|magic|cold|pois|life|mana|stam|clen|flen|plen <amount> [attacker ref] [stagger]");
	}
	const Elem* elem = nullptr;
	for (const Elem& e : elems) {
		if (hcmd::LowerEq(t.tok[2], e.name)) {
			elem = &e;
		}
	}
	Unit* target = ResolveRef(c, t.tok[1]);
	if (elem == nullptr || target == nullptr) {
		return Fail(c, "hit: unknown element or target (%s)", t.tok[1]);
	}
	bool stagger = false;
	int n = t.n;
	if (n > 4 && hcmd::LowerEq(t.tok[n - 1], "stagger")) {
		stagger = true;
		--n;
	}
	Unit* attacker = nullptr;
	if (n > 4) {
		attacker = ResolveRef(c, t.tok[4]);
	} else if (target == c->player) {
		attacker = NearestFighter(c);
		if (attacker == nullptr) {
			attacker = target;
		}
	} else {
		attacker = c->player;
	}
	if (attacker == nullptr) {
		return Fail(c, "hit: attacker not found");
	}
	DamageBlock d;
	DamageInit(d);
	DmgField<uint32_t>(d, 0x00) |= 2;
	DmgField<uint16_t>(d, 0x04) |= 1;
	DmgField<int32_t>(d, elem->offset) = static_cast<int32_t>(amount);
	if (elem->hitClass != 0) {
		DmgField<int32_t>(d, 0x144) = elem->hitClass;
	}
	const int32_t before = Stat(target, StatLife);
	Fn<HitUnitFn>(RvaHitUnit)(c->game, attacker, target, 1, d.b);
	const int32_t fieldAfter = DmgField<int32_t>(d, elem->offset);
	if (stagger) {
		DmgField<uint16_t>(d, 0x04) |= 4;
	}
	Fn<ApplyDamageFn>(RvaApplyDamage)(c->game, attacker, target, d.b);
	const int32_t after = Stat(target, StatLife);
	Out("hit target=%s elem=%s amount=%lld life=%d->%d lost=%d absorbed=%d result=0x%x field=%d", t.tok[1], elem->name, amount, before, after,
	    hcmd::LifeLost(before, after), DmgField<int32_t>(d, 0x130), static_cast<unsigned>(DmgField<uint16_t>(d, 0x04)), fieldAfter);
	DamageDestroy(d);
	return true;
}

// Build and apply actual weapon damage, rather than injecting a chosen field
// like `hit`. Uses the same native pipeline as area_damage.cpp.
auto CmdPassiveRefresh(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	Fn<void (*)(Unit*, int32_t)>(0x33f830)(c->player, 1);
	Out("passiverefresh: native passive stats recalculated");
	return true;
}

// `passivestate [skill id=2072] [watch <hw slot 0-3> <hex offset> [len]] [dump]`: the state stat list a passive skill applies (skill
// record +0xb4 = passive state; 0x2f5940 finds the unit's list for it; list +0x1c flags, +0x20 state, +0x78 parent). Prints whether the
// list exists and the player's fire minimum / maximum (stat 48 / 49); `watch` sets a hardware write breakpoint on the list (evtrace dump
// prints the call chain of each write), `dump` prints the first 0xb0 bytes of the list.
auto CmdPassiveState(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long skill = 2072;
	int next = 1;
	if (t.n > 1 && hcmd::ParseInt(t.tok[1], &skill)) {
		next = 2;
	}
	const uint32_t dataFlag = Fn<UnitDataFlagFn>(RvaUnitDataFlag)(c->player);
	const uint8_t* record = d2r::api.getSkillRecord(dataFlag, static_cast<int32_t>(skill));
	if (record == nullptr) {
		return Fail(c, "passivestate: no skills.txt row %lld", skill);
	}
	const int state = d2r::At<int16_t>(record, 0xb4);
	uint8_t* list = static_cast<uint8_t*>(Fn<void* (*)(Unit*, int32_t)>(0x2f5940)(c->player, state));
	// the list's own stat array: pointer at +0x30, entry count at +0x38; an entry is {u16 layer, u16 stat, i32 value}
	const uint8_t* arr = list != nullptr ? d2r::At<const uint8_t*>(list, 0x30) : nullptr;
	const uint64_t count = list != nullptr ? d2r::At<uint64_t>(list, 0x38) : 0;
	Out("passivestate skill=%lld state=%d has=%d list=%p flags=%08x parent=%p arr=%p n=%llu fire=%d/%d frame=%u osk=%d syn=%d dex=%d ied=%d", skill, state,
	    Fn<UnitHasStateFn>(RvaUnitHasState)(c->player, state) != 0 ? 1 : 0, static_cast<void*>(list),
	    list != nullptr ? d2r::At<uint32_t>(list, 0x1c) : 0u, list != nullptr ? d2r::At<void*>(list, 0x78) : nullptr, static_cast<const void*>(arr),
	    static_cast<unsigned long long>(count), Stat(c->player, 48), Stat(c->player, 49), d2r::At<uint32_t>(c->game, GameFrame), Stat(c->player, 97, 2072), Stat(c->player, 412, 2072),
	    Stat(c->player, 2), Stat(c->player, 513));
	for (int i = next; i < t.n; ++i) {
		if (list == nullptr) {
			return Fail(c, "passivestate: no list to %s", t.tok[i]);
		}
		if (hcmd::LowerEq(t.tok[i], "arr") && arr != nullptr) {
			// 16-byte entries: {u16 layer, u16 0, u32 stat} {i32 value, i32 extra}
			for (int k = 0; k < 8 && d2r::At<uint32_t>(arr, k * 16 + 4) != 0; ++k) {
				Out("  arr+%02x layer=%u stat=%u value=%d extra=%d", k * 16, d2r::At<uint16_t>(arr, k * 16), d2r::At<uint32_t>(arr, k * 16 + 4),
				    d2r::At<int32_t>(arr, k * 16 + 8), d2r::At<int32_t>(arr, k * 16 + 12));
			}
		} else if (hcmd::LowerEq(t.tok[i], "awatch") && i + 2 < t.n && arr != nullptr) {
			// `awatch <hw slot> <hex byte offset>`: write breakpoint on 4 bytes of the list's stat array (the value of the first stat is at +8)
			long long slot = 0;
			if (!hcmd::ParseInt(t.tok[i + 1], &slot)) {
				return Fail(c, "passivestate: awatch <hw slot 0-3> <hex byte offset>");
			}
			const unsigned long long off = std::strtoull(t.tok[i + 2], nullptr, 16);
			i += 2;
			if (!item_events::WatchSet(static_cast<int>(slot), reinterpret_cast<uint64_t>(arr) + off, 4, g_base)) {
				return Fail(c, "passivestate: could not set the breakpoint");
			}
			Out("  watching arr+%llx at %p in slot %lld", off, static_cast<const void*>(arr + off), slot);
		} else if (hcmd::LowerEq(t.tok[i], "dump")) {
			for (int off = 0; off < 0xb0; off += 0x20) {
				Out("  +%02x: %016llx %016llx %016llx %016llx", off, static_cast<unsigned long long>(d2r::At<uint64_t>(list, off)),
				    static_cast<unsigned long long>(d2r::At<uint64_t>(list, off + 8)), static_cast<unsigned long long>(d2r::At<uint64_t>(list, off + 16)),
				    static_cast<unsigned long long>(d2r::At<uint64_t>(list, off + 24)));
			}
		} else if (hcmd::LowerEq(t.tok[i], "watch") && i + 2 < t.n) {
			long long slot = 0, len = 8;
			if (!hcmd::ParseInt(t.tok[i + 1], &slot)) {
				return Fail(c, "passivestate: watch slot must be a number");
			}
			const unsigned long long off = std::strtoull(t.tok[i + 2], nullptr, 16);
			if (i + 3 < t.n && hcmd::ParseInt(t.tok[i + 3], &len)) {
				++i;
			}
			i += 2;
			if (!item_events::WatchSet(static_cast<int>(slot), reinterpret_cast<uint64_t>(list) + off, static_cast<int>(len), g_base)) {
				return Fail(c, "passivestate: could not set the breakpoint");
			}
			Out("  watching list+%llx (%lld bytes) in slot %lld", off, len, slot);
		}
	}
	return true;
}

// Build and apply actual weapon damage through the area_damage.cpp pipeline.
auto CmdWeaponHit(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long src = 128;
	if (t.n < 2 || (t.n > 2 && !hcmd::ParseInt(t.tok[2], &src)) || src < 1 || src > 255) {
		return Fail(c, "usage: weaponhit <mon:id> [SrcDam 1-255]");
	}
	Unit* target = ResolveRef(c, t.tok[1]);
	if (target == nullptr || TypeOf(target) != 1 || !IsAlive(target)) {
		return Fail(c, "weaponhit: living monster required");
	}
	DamageBlock d;
	DamageInit(d);
	DmgField<uint32_t>(d, 0) = 2;
	DmgField<uint16_t>(d, 4) = 1;
	using WeaponFn = void (*)(Game*, Unit*, Unit*, void*, int32_t, uint8_t);
	Fn<WeaponFn>(0x44c030)(c->game, c->player, target, d.b, 0, static_cast<uint8_t>(src));
	const int32_t phys = DmgField<int32_t>(d, 0x18), fire = DmgField<int32_t>(d, 0x20);
	const int32_t light = DmgField<int32_t>(d, 0x2c), cold = DmgField<int32_t>(d, 0x34);
	const int32_t before = Stat(target, StatLife);
	Fn<HitUnitFn>(RvaHitUnit)(c->game, c->player, target, 1, d.b);
	Fn<ApplyDamageFn>(RvaApplyDamage)(c->game, c->player, target, d.b);
	Out("weaponhit src=%lld phys=%d fire=%d light=%d cold=%d lost=%d result=0x%x", src, phys, fire, light, cold,
	    hcmd::LifeLost(before, Stat(target, StatLife)), static_cast<unsigned>(DmgField<uint16_t>(d, 4)));
	DamageDestroy(d);
	return true;
}

// `avoid <ref> melee|missile|evade [n]`: D2R's avoid check 0x44ef70 (the hooked one: Median's caps) n times (default 200) against
// the unit (arguments: attacker unit = the player, defender unit, missile flag; a Game there crashes the debug logger); evade is rolled while walking, so the unit's mode is set to walk (2) for the loop and put back. Tally of the
// results: none, avoid (2), dodge (4), evade (8), block (0x10).
auto CmdAvoid(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 200;
	if (t.n < 3 || (t.n > 3 && !hcmd::ParseInt(t.tok[3], &n)) || n < 1 || n > 20000) {
		return Fail(c, "usage: avoid <player|merc|mon:id> melee|missile|evade [n]");
	}
	Unit* unit = ResolveRef(c, t.tok[1]);
	if (unit == nullptr) {
		return Fail(c, "avoid: unit not found (%s)", t.tok[1]);
	}
	const bool missile = hcmd::LowerEq(t.tok[2], "missile");
	const bool evade = hcmd::LowerEq(t.tok[2], "evade");
	if (!missile && !evade && !hcmd::LowerEq(t.tok[2], "melee")) {
		return Fail(c, "avoid: melee, missile or evade");
	}
	auto* modeField = reinterpret_cast<int32_t*>(reinterpret_cast<uint8_t*>(unit) + UnitMode);
	const int32_t savedMode = *modeField;
	if (evade) {
		*modeField = 2;
	}
	hcmd::AvoidTally tally;
	for (long long i = 0; i < n; ++i) {
		tally.Add(Fn<AvoidCheckFn>(RvaAvoidCheck)(c->player, unit, missile ? 1 : 0));
	}
	*modeField = savedMode;
	Out("avoid ref=%s kind=%s n=%d none=%d avoid=%d dodge=%d evade=%d block=%d other=%d success=%d mode=%d dataflag=%d gameflag=%d asgame=%d", t.tok[1], t.tok[2], tally.n,
	    tally.none, tally.avoid, tally.dodge, tally.evade, tally.block, tally.other, tally.Successes(), static_cast<int>(savedMode), static_cast<int>(Fn<UnitDataFlagFn>(RvaUnitDataFlag)(unit)),
	    static_cast<int>(c->dataFlag), static_cast<int>(d2r::DataFlag(reinterpret_cast<Game*>(c->player))));
	return true;
}

constexpr uint64_t RvaMeleeWear = 0x4526c0;  // (game, attacker, defender): wear of the attacker's weapon and one of the defender's armour pieces
using MeleeWearFn = void (*)(Game*, Unit*, Unit*);

// `wear <attacker ref> <defender ref> [n]`: n times (default 100) the wear step of a melee hit, `0x4526c0`, the function
// that calls the wear dispatcher `0x441b10` (weapon of the attacker, an armour piece of a player defender, 4 to 10 percent
// each). Prints the durability sum of both units' worn items before and after (item stat 0x48), so the item rules check
// (mxl-core "durability") can tell a worn-down item from one that stayed whole.
auto CmdWear(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 100;
	if (t.n < 3 || (t.n > 3 && !hcmd::ParseInt(t.tok[3], &n)) || n < 1 || n > 20000) {
		return Fail(c, "usage: wear <player|merc|mon:id> <player|merc|mon:id> [n]");
	}
	Unit* attacker = ResolveRef(c, t.tok[1]);
	Unit* defender = ResolveRef(c, t.tok[2]);
	if (attacker == nullptr || defender == nullptr) {
		return Fail(c, "wear: unit not found");
	}
	auto durability = [&]() {
		long long sum = 0;
		EachItemOf(c->player, [&](Unit* item) {
			if (Fn<ItemByteFn>(RvaItemPage)(item) == 0xff) {  // worn
				sum += Stat(item, StatDurability);
			}
		});
		return sum;
	};
	const long long before = durability();
	for (long long i = 0; i < n; ++i) {
		Fn<MeleeWearFn>(RvaMeleeWear)(c->game, attacker, defender);
	}
	Out("wear %s -> %s n=%lld durability worn before=%lld after=%lld", t.tok[1], t.tok[2], n, before, durability());
	return true;
}

constexpr uint64_t RvaPotionOfLifeStep = 0x580680;  // (game, unit): the Potion of Life's grant; max life (stat 7) += 0x1400 (Median 0x3200)
constexpr uint64_t RvaLamEsenStep = 0x5ed6d0;       // (game, unit): Lam Esen's Tome reward, once per quest bit; unspent stat points (stat 4) += 5 (Median 10)
constexpr uint64_t RvaSetState = 0x3355a0;          // (unit, state, on): needs the unit's state stat list
constexpr uint64_t RvaClearState = 0x3354c0;        // (unit, state, 0)
constexpr uint64_t RvaStateList = 0x2f5940;         // (unit, state) -> the unit's stat list for that state
constexpr uint64_t RvaCreateStateList = 0x433d20;   // (&params) -> list (D2R's self buffs, srvdofunc 18, 0x553e60)
constexpr uint64_t RvaBuffExpired = 0x5551f0;       // the self buffs' expiry callback
constexpr uint64_t RvaDetachList = 0x2f7920;        // (unit, list)
constexpr uint64_t RvaFreeList = 0x2f4180;          // (dataFlag, list)
using RewardStepFn = int (*)(Game*, Unit*);
using SetStateFn = void (*)(Unit*, int32_t, int32_t);
using StateListFn = void* (*)(Unit*, int32_t);
using CreateStateListFn = void* (*)(void* params);
using DetachListFn = void (*)(Unit*, void*);
using FreeListFn = void (*)(uint32_t, void*);

// `rewardstep potion|tome`: runs the game's own grant step of the Potion of Life or of Lam Esen's Tome on the player and prints
// the stat it changes (max life raw and in points; unspent stat points) before and after, so the amounts can be compared with
// Median's (+50 life, 10 stat points). The Tome step grants only while quest 17 has bit 1 set (`quest 17 1 set`) and clears it.
auto CmdRewardStep(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: rewardstep potion|tome");
	}
	const bool potion = hcmd::LowerEq(t.tok[1], "potion");
	if (!potion && !hcmd::LowerEq(t.tok[1], "tome")) {
		return Fail(c, "usage: rewardstep potion|tome");
	}
	const int stat = potion ? 7 : 4;
	const int32_t before = Stat(c->player, stat);
	Fn<RewardStepFn>(potion ? RvaPotionOfLifeStep : RvaLamEsenStep)(c->game, c->player);
	const int32_t after = Stat(c->player, stat);
	Out("rewardstep %s stat=%d before=%d after=%d gained=%d points=%d", t.tok[1], stat, before, after, after - before,
	    potion ? (after - before) >> 8 : after - before);
	return true;
}

// `setstate <ref> <state> <0|1>`: puts a state on a unit or takes it off, the way D2R's self buffs do (srvdofunc 18: a state
// stat list from 0x433d20, then the set-state call); on lasts 10 minutes. Prints whether the unit has the state afterwards.
// Gives the player the Stamina Shrine's state 136 without a shrine.
auto CmdSetState(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long state = 0, on = 0;
	if (t.n < 4 || !hcmd::ParseInt(t.tok[2], &state) || !hcmd::ParseInt(t.tok[3], &on) || state < 1 || state > 1023) {
		return Fail(c, "usage: setstate <player|merc|mon:id> <state> <0|1>");
	}
	Unit* unit = ResolveRef(c, t.tok[1]);
	if (unit == nullptr) {
		return Fail(c, "setstate: unit not found (%s)", t.tok[1]);
	}
	const int32_t st = static_cast<int32_t>(state);
	void* list = Fn<StateListFn>(RvaStateList)(unit, st);
	if (on != 0 && list == nullptr) {
		struct Params {  // the request of srvdofunc 18 (see missile_hits.cpp)
			Unit* caster;
			Unit* target;
			int32_t skill, level, duration, minus1, zero, state;
			void* expired;
		} params{unit, unit, 0, 1, 25 * 600, -1, 0, st, reinterpret_cast<void*>(g_base + RvaBuffExpired)};
		static_assert(sizeof(Params) == 0x30);
		list = Fn<CreateStateListFn>(RvaCreateStateList)(&params);
		if (list == nullptr) {
			return Fail(c, "setstate: no state list could be created");
		}
		Fn<SetStateFn>(RvaSetState)(unit, st, 1);
	} else if (on == 0 && list != nullptr) {
		Fn<SetStateFn>(RvaClearState)(unit, st, 0);
		Fn<DetachListFn>(RvaDetachList)(unit, list);
		Fn<FreeListFn>(RvaFreeList)(c->dataFlag, list);
	}
	Out("setstate %s state=%lld on=%lld has=%d", t.tok[1], state, on, Fn<UnitHasStateFn>(RvaUnitHasState)(unit, st) != 0 ? 1 : 0);
	return true;
}

// `manamin [reset]`: the lowest mana the player had on any server frame since `manamin reset` (a skill's mana is charged
// when its action starts, a frame or more after `cast` returns, and regeneration refills it within a few frames, so a
// single read after the cast sees nothing; every frame is sampled here).
Unit* volatile g_manaWatch = nullptr;
volatile LONG g_manaMin = 0;
volatile LONG g_manaMax = 0;

void TrackMana() noexcept {
	Unit* p = g_manaWatch;
	if (p != nullptr) {
		const LONG now = Stat(p, StatMana);
		if (now < g_manaMin) {
			InterlockedExchange(&g_manaMin, now);
		}
		if (now > g_manaMax) {
			InterlockedExchange(&g_manaMax, now);
		}
	}
}

auto CmdManaMin(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 2) {
		if (!hcmd::LowerEq(t.tok[1], "reset")) {
			return Fail(c, "usage: manamin [reset]");
		}
		const LONG now = Stat(c->player, StatMana);
		InterlockedExchange(&g_manaMin, now);
		InterlockedExchange(&g_manaMax, now);
		g_manaWatch = c->player;
	}
	Out("manamin min=%d max=%d now=%d tracking=%s", g_manaMin >> 8, g_manaMax >> 8, Stat(c->player, StatMana) >> 8,
	    g_manaWatch != nullptr ? "on" : "off (manamin reset starts it)");
	return true;
}

// `manacharge`: what the mana cost hook (mana_costs.cpp) decided at the last charge site: its calls, the caster's room and the
// town test, the cost and the charge in mana points, and the site (1 server, 2 client).
auto CmdManaCharge(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	const ManaChargeLog l = LastManaCharge();
	Out("manacharge calls=%u room=%p town=%d cost=%d charged=%d site=%d other=%u from=0x%llx skill=%d", l.calls, l.room, l.roomIsTown, l.cost,
	    l.charged, l.site, l.otherCalls, static_cast<unsigned long long>(l.otherFrom), l.otherSkill);
	(void)c;
	return true;
}

// `hc [on|off]`: the player's Hardcore marks (info flag 4 at +0xe of 0x48fde0's struct, dead flag 8, client record +0x5658 bit
// 0x800); `on` / `off` sets or clears the two Hardcore ones so a Softcore test character can die as a Hardcore one
// (hardcore_death.cpp). `converted` counts the deaths the hook made Softcore.
auto CmdHardcore(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	uint8_t* info = Fn<uint8_t* (*)(Unit*)>(0x48fde0)(c->player);
	if (info == nullptr) {
		return Fail(c, "hc: the player has no info struct");
	}
	uint8_t* client = nullptr;
	int guard = 0;
	for (auto* cl = d2r::At<uint8_t*>(c->game, GameClients); cl != nullptr && guard < 64; cl = d2r::At<uint8_t*>(cl, ClientNext), ++guard) {
		if (d2r::At<int32_t>(cl, ClientState) == 4 && Fn<ClientUnitFn>(RvaClientUnit)(cl, 0) == c->player) {
			client = cl;
		}
	}
	if (client == nullptr) {
		return Fail(c, "hc: no client record for the player");
	}
	if (t.n >= 2) {
		const bool on = hcmd::LowerEq(t.tok[1], "on");
		if (!on && !hcmd::LowerEq(t.tok[1], "off")) {
			return Fail(c, "usage: hc [on|off]");
		}
		uint16_t& flags = *reinterpret_cast<uint16_t*>(info + 0xe);
		uint32_t& cflags = *reinterpret_cast<uint32_t*>(client + 0x5658);
		flags = static_cast<uint16_t>(on ? (flags | 4) : (flags & ~4));
		cflags = on ? (cflags | 0x800) : (cflags & ~0x800u);
	}
	unsigned deaths = 0, converted = 0;
	HardcoreDeathStats(&deaths, &converted);
	Out("hc info=0x%x hardcore=%d dead=%d client=0x%x hardcore=%d mode=%d life=%d deaths=%u converted=%u", d2r::At<uint16_t>(info, 0xe),
	    (d2r::At<uint16_t>(info, 0xe) & 4) != 0 ? 1 : 0, (d2r::At<uint16_t>(info, 0xe) & 8) != 0 ? 1 : 0, d2r::At<uint32_t>(client, 0x5658),
	    (d2r::At<uint32_t>(client, 0x5658) & 0x800) != 0 ? 1 : 0, ModeOf(c->player), Stat(c->player, StatLife) >> 8, deaths, converted);
	return true;
}

// `renderpool [probe]`: the Renderer Pool fallback's counters (render_pool.cpp, bug #60); `probe` runs one heap block through the wrapped
// vtable (realloc, size, free) and expects the counters back where they were.
auto CmdRenderPool(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const bool probe = t.n >= 2 && hcmd::LowerEq(t.tok[1], "probe");
	const bool ok = probe ? RenderPoolProbe() : true;
	RenderPoolStats rp{};
	GetRenderPoolStats(&rp);
	Out("renderpool fallbacks=%u live=%u livebytes=%zu peak=%zu base=%llx size=%zu%s", rp.fallbacks, rp.live, rp.liveBytes, rp.peakBytes, rp.poolBase,
	    rp.poolSize, probe ? (ok ? " probe=ok" : " probe=FAILED") : "");
	return ok ? true : Fail(c, "renderpool: the probe block did not go through the fallback");
}

// `transguard [probe]`: the translation event guard's counters (translation_guard.cpp); `probe` feeds the hook one event with the payload
// word of the crash reports (0x8000003F0), which must be skipped (and counts as one skipped event and one log line).
auto CmdTransGuard(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const bool probe = t.n >= 2 && hcmd::LowerEq(t.tok[1], "probe");
	const bool skipped = probe ? TranslationGuardProbe() : false;
	unsigned seen = 0, skips = 0;
	TranslationGuardStats(&seen, &skips);
	Out("transguard events=%u skipped=%u%s", seen, skips, probe ? (skipped ? " probe=skipped" : " probe=NOT skipped") : "");
	return !probe || skipped ? true : Fail(c, "transguard: the probe event was not skipped");
}

// `tpgold`: the teleport gold pickup's counters (teleport.cpp): teleports that looked around, gold piles in reach, piles taken.
auto CmdTeleportGold(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	unsigned teleports = 0, seen = 0, piles = 0;
	TeleportGoldStats(&teleports, &seen, &piles);
	Out("tpgold teleports=%u seen=%u taken=%u gold=%d", teleports, seen, piles, Stat(c->player, StatGold));
	return true;
}

// `modewatch start|stop|read`: a thread samples the player's unit mode every 2 ms and counts the entries into the attack / cast /
// throw / kick / skill modes (7..14) and into walk / run (2, 3, 6): what a Shift click with a skill did, however short the swing.
std::atomic<bool> g_modeRun{false};
std::atomic<uint32_t> g_modeAttack{0}, g_modeMove{0}, g_modeSamples{0};
std::atomic<int32_t> g_modeLast{-1};
std::atomic<int32_t> g_modeMana0{0}, g_modeManaMin{0};

auto ReadUnitMode(Unit* u) noexcept -> int32_t {
	__try {
		return d2r::At<int32_t>(u, UnitMode);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		return -1;
	}
}

auto ReadManaSafe(Unit* u) noexcept -> int32_t {
	__try {
		return Stat(u, 8);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		return INT32_MAX;
	}
}

auto CmdModeWatch(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: modewatch start|stop|read");
	}
	if (hcmd::LowerEq(t.tok[1], "start")) {
		if (g_modeRun.load()) {
			return Fail(c, "modewatch: already running");
		}
		g_modeAttack = 0;
		g_modeMove = 0;
		g_modeSamples = 0;
		g_modeLast = -1;
		g_modeMana0 = Stat(c->player, 8);
		g_modeManaMin = g_modeMana0.load();
		g_modeRun = true;
		Unit* player = c->player;
		std::thread([player]() {
			int32_t last = ReadUnitMode(player);
			while (g_modeRun.load()) {
				const int32_t now = ReadUnitMode(player);
				const int32_t mana = ReadManaSafe(player);
				if (mana < g_modeManaMin.load()) {
					g_modeManaMin = mana;
				}
				if (now != last && now >= 0) {
					if (now >= 7 && now <= 14) {
						g_modeAttack.fetch_add(1);
					} else if (now == 2 || now == 3 || now == 6) {
						g_modeMove.fetch_add(1);
					}
					g_modeLast = now;
				}
				last = now;
				g_modeSamples.fetch_add(1);
				Sleep(2);
			}
		}).detach();
		Out("modewatch started");
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "stop")) {
		g_modeRun = false;
	}
	Out("modewatch running=%d attack=%u move=%u samples=%u last=%d mana=%d min=%d", g_modeRun.load() ? 1 : 0, g_modeAttack.load(), g_modeMove.load(),
	    g_modeSamples.load(), g_modeLast.load(), g_modeMana0.load(), g_modeManaMin.load());
	return true;
}

// `peek exe+<rva>|<address> [n]`: n bytes (default 32, at most 256) of the live process as hex, and the module the address is in
// (name, base, offset): reads D2RCore.dll's functions behind the executable's `jmp [rip+x]` thunks.
auto CmdPeek(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: peek exe+<hex rva>|<hex address> [bytes] [deref]");
	}
	const char* arg = t.tok[1];
	uint64_t address = 0;
	if (std::strncmp(arg, "exe+", 4) == 0) {
		address = g_base + std::strtoull(arg + 4, nullptr, 16);
	} else {
		address = std::strtoull(arg, nullptr, 16);
	}
	long long n = 32;
	if (t.n > 2 && (!hcmd::ParseInt(t.tok[2], &n) || n < 1 || n > 256)) {
		return Fail(c, "peek: bytes 1..256");
	}
	if (t.n > 3 && hcmd::LowerEq(t.tok[3], "deref")) {
		uint64_t pointer = 0;
		__try {
			pointer = *reinterpret_cast<const uint64_t*>(address);
		} __except (EXCEPTION_EXECUTE_HANDLER) {
			return Fail(c, "peek: unreadable %llx", static_cast<unsigned long long>(address));
		}
		address = pointer;
	}
	HMODULE module = nullptr;
	char name[MAX_PATH] = "?";
	if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
	                       reinterpret_cast<LPCSTR>(address), &module)) {
		GetModuleFileNameA(module, name, sizeof(name));
	}
	char hex[600] = "";
	size_t len = 0;
	__try {
		for (long long i = 0; i < n; ++i) {
			len += static_cast<size_t>(std::snprintf(hex + len, sizeof(hex) - len, "%02x", *reinterpret_cast<const uint8_t*>(address + i)));
		}
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		return Fail(c, "peek: unreadable at +%lld", static_cast<long long>(len / 2));
	}
	Out("peek address=%llx module=%s base=%llx offset=%llx bytes=%s", static_cast<unsigned long long>(address), name,
	    static_cast<unsigned long long>(reinterpret_cast<uint64_t>(module)), static_cast<unsigned long long>(address - reinterpret_cast<uint64_t>(module)), hex);
	return true;
}

// `afford <skill id>`: the usability test's afford step (0x340900, hooked by mana_costs.cpp InstallSkillAfford) for one of the
// player's skills, with the cost the hook compares (D2Sigma's, 1/256 points) and the mana now: `afford=1` when the mana
// covers it. D2R's own columns give `cols`, the cost D2R's test would use. `hook` counts the tests the hook answered / changed.
auto CmdAfford(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &id) || id < 0 || id > 0xffff) {
		return Fail(c, "usage: afford <skill id>");
	}
	uint8_t* sk = Fn<SkillByIdFn>(RvaSkillById)(c->player, static_cast<int32_t>(id), -1);
	if (sk == nullptr) {
		return Fail(c, "afford: the player has no skill %lld (setskill %lld 1 first)", id, id);
	}
	auto* entry = reinterpret_cast<int64_t*>(sk);
	const uint8_t* rec = d2r::At<const uint8_t*>(sk, 0);
	const int32_t cost = SigmaSkillCost(c->player, entry);
	const int32_t level = rec != nullptr ? d2r::At<int32_t>(sk, 0x40) : -1;
	const int32_t cols = rec != nullptr ? ((level > 0 ? level - 1 : 0) * d2r::At<int16_t>(rec, 0x22c) + d2r::At<int16_t>(rec, 0x22a))
	                                          << (d2r::At<uint8_t>(rec, 0x228) & 31)
	                                    : -1;
	const uint64_t verdict = Fn<uint64_t (*)(Unit*, int64_t*)>(0x340900)(c->player, entry);
	const AffordLog l = SkillAffordLog();
	Out("afford skill %lld level %d: afford=%llu cost=%d cols=%d mana=%d life=%d calc7=%d calc8=%d hook=%u/%u", id, level, static_cast<unsigned long long>(verdict),
	    cost, cols, Stat(c->player, StatMana), Stat(c->player, 6), rec != nullptr ? d2r::At<int32_t>(rec, 0x1a8) : -2,
	    rec != nullptr ? d2r::At<int32_t>(rec, 0x1ac) : -2, l.calls, l.changed);
	return true;
}

// `cursor`: the item on the player's cursor (inventory +0x40, the one 0x4249f0 reports as "busy": no skill can be used while
// it is held): id and code, or "empty". Drop it with the client packet 0x17 + id (u32).
auto CmdCursor(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	uint8_t* inv = static_cast<uint8_t*>(Fn<InventoryFn>(RvaInventory)(c->player, "harness", 0));
	Unit* item = inv != nullptr && d2r::At<uint32_t>(inv, 0) == 0x1020304 ? d2r::At<Unit*>(inv, 0x40) : nullptr;
	if (item == nullptr) {
		Out("cursor empty");
		return true;
	}
	char code[5] = {};
	ItemCode(c, item, code);
	Out("cursor id=%u code=%s", IdOf(item), code);
	return true;
}

// `iflags <item id> [unid]`: flags (0x10 identified), mode, quantity (stat 0x46), durability (0x48) and maximum (0x49) of any
// item unit in the game, on the ground too (`stat` only sees the player's items), and its position (the pick-up packet 0x16
// carries it: id, x, y, to-inventory flag, 17 bytes); `unid` first clears the identified flag
// (the generator may make the item identified already).
auto CmdItemFlags(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &id)) {
		return Fail(c, "usage: iflags <item unit id> [unid]");
	}
	Unit* found = nullptr;
	EachUnit(c->game, HashItems, [&](Unit* it) {
		if (found == nullptr && TypeOf(it) == 4 && IdOf(it) == static_cast<uint32_t>(id)) {
			found = it;
		}
	});
	if (found == nullptr) {
		return Fail(c, "iflags: no such item unit");
	}
	if (t.n > 2 && hcmd::LowerEq(t.tok[2], "unid")) {
		Fn<DropFlagsFn>(RvaDropFlags)(found, 0x10, 0);
	}
	const auto* data = Fn<ItemDataFn>(RvaItemData)(found);
	const uint32_t flags = data != nullptr ? d2r::At<uint32_t>(data, ItemFlagsOffset) : 0;
	int32_t x = 0, y = 0;
	d2r::UnitXY(found, &x, &y);
	Out("iflags id=%u flags=0x%x identified=%d mode=%d quantity=%d durability=%d maxdurability=%d x=%d y=%d", IdOf(found), flags,
	    (flags & 0x10) != 0 ? 1 : 0, ModeOf(found), Stat(found, 0x46), Stat(found, StatDurability), Stat(found, StatMaxDurabilityItem), x, y);
	return true;
}

// `itemdesc <item unit id>`: the text of the item's description (the hover tooltip of the inventory), built by D2R's own
// builder 0x2be560 (out string, item, flags, flag, text, options) on the client's copy of the item and printed one line
// per `h: itemdesc id=<id> line <n>: <text>` with the colour codes (U+E07E and a digit) removed. The builder returns a
// std::string-like block {char* text, size, capacity, inline buffer}; the line `Durability: x of y` is the output of
// 0x2c1640, which the plugin part durabilitytip replaces (docs/median-rules-audit.md IT1).
auto CmdItemDesc(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long id = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &id)) {
		return Fail(c, "usage: itemdesc <item unit id> [eth]");
	}
	static constexpr uint8_t BuilderEntry[] = {0x48, 0x89, 0x5c, 0x24, 0x18, 0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57};
	if (std::memcmp(reinterpret_cast<const void*>(g_base + 0x2be560), BuilderEntry, sizeof(BuilderEntry)) != 0) {
		return Fail(c, "itemdesc: the description builder 0x2be560 is not where it was (image mismatch)");
	}
	Unit* item = Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(id), 4);
	if (item == nullptr) {
		return Fail(c, "itemdesc: the client has no such item unit");
	}
	using BuilderFn = void (*)(void* out, Unit* item, uint32_t flags, char flag, char* text, void* options);
	alignas(16) uint8_t out[0x40] = {};
	alignas(16) uint8_t options[0x10] = {};  // {u64 value, u8 present = 0}
	auto* itemData = Fn<ItemDataFn>(RvaItemData)(item);
	const bool eth = t.n > 2 && hcmd::LowerEq(t.tok[2], "eth");  // `eth`: the client's copy reads as ethereal for this one call
	const uint32_t savedFlags = itemData != nullptr ? d2r::At<uint32_t>(itemData, ItemFlagsOffset) : 0;
	if (eth && itemData != nullptr) {
		*reinterpret_cast<uint32_t*>(itemData + ItemFlagsOffset) = savedFlags | ItemFlagEthereal;
	}
	Fn<BuilderFn>(0x2be560)(out, item, 0, 1, nullptr, options);
	if (eth && itemData != nullptr) {
		*reinterpret_cast<uint32_t*>(itemData + ItemFlagsOffset) = savedFlags;
	}
	const char* text = *reinterpret_cast<const char* const*>(out);
	const uint64_t size = *reinterpret_cast<const uint64_t*>(out + 8);
	if (text == nullptr || size > 0x4000) {
		return Fail(c, "itemdesc: the builder returned no text");
	}
	char line[300];
	size_t n = 0;
	int lines = 0;
	auto flush = [&] {
		line[n] = '\0';
		Out("itemdesc id=%u line %d: %s", static_cast<unsigned>(id), lines++, line);
		n = 0;
	};
	for (uint64_t i = 0; i < size; ++i) {
		const auto ch = static_cast<uint8_t>(text[i]);
		if (ch == 0xee && i + 3 < size && static_cast<uint8_t>(text[i + 1]) == 0x81 && static_cast<uint8_t>(text[i + 2]) == 0xbe) {
			i += 3;  // colour code: U+E07E (UTF-8 ee 81 be) and one digit
		} else if (ch == '\n') {
			flush();
		} else if (n + 1 < sizeof(line)) {
			line[n++] = static_cast<char>(ch);
		}
	}
	if (n > 0) {
		flush();
	}
	Out("itemdesc id=%u lines %d", static_cast<unsigned>(id), lines);
	return true;
}

// `itemroll <code> <n> [q=quality] [ilvl=level]`: makes n items the way `item` does (the generator, quality default 2, item
// level default 110 so the ethereal gate and the automagic roll are open), reads sockets, the ethereal flag, the quality the
// generator gave, the automagic affix id, defence and maximum durability and frees them again. Prints the socket histogram,
// the quality histogram, the automagic count and the ethereal count, then the defence and durability by ethereal or not.
auto CmdItemRoll(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 0, quality = 2, ilvl = 110;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &n) || n < 1 || n > 20000) {
		return Fail(c, "usage: itemroll <code> <n> [q=quality] [ilvl=level]");
	}
	for (int i = 3; i < t.n; ++i) {
		long long v = 0;
		if (std::strncmp(t.tok[i], "q=", 2) == 0 && hcmd::ParseInt(t.tok[i] + 2, &v)) {
			quality = v;
		} else if (std::strncmp(t.tok[i], "ilvl=", 5) == 0 && hcmd::ParseInt(t.tok[i] + 5, &v)) {
			ilvl = v;
		} else {
			return Fail(c, "itemroll: cannot read '%.40s'", t.tok[i]);
		}
	}
	int32_t classId = 0;
	if (Fn<ItemByCodeFn>(RvaItemByCode)(c->dataFlag, hcmd::CodeToDword(t.tok[1]), &classId) == nullptr) {
		return Fail(c, "itemroll: unknown code");
	}
	hcmd::RollTally tally;
	int failed = 0, nNormal = 0, nEth = 0, firstLevel = -1, nIdentified = 0;
	long long sumNormal = 0, sumEth = 0;
	int32_t durNormalMin = 1 << 30, durNormalMax = -1, durEthMin = 1 << 30, durEthMax = -1;
	for (long long i = 0; i < n; ++i) {
		Unit* item = Fn<MakeItemFn>(RvaMakeItem)(c->player, classId, c->game, 4, static_cast<int64_t>(quality), 0, 0, static_cast<int32_t>(ilvl), 0, 0, 0);  // bit B (the 2 in the generator flags) would skip the ethereal gate
		if (item == nullptr) {
			++failed;
			continue;
		}
		if (firstLevel < 0) {
			firstLevel = static_cast<int>(Fn<ItemLevelFn>(RvaItemLevel)(item));
		}
		const bool eth = (FlagsOf(item) & ItemFlagEthereal) != 0;
		const int32_t def = Stat(item, StatDefence), dur = Stat(item, StatMaxDurabilityItem);
		nIdentified += (FlagsOf(item) & 0x10) != 0 ? 1 : 0;
		tally.Add(Stat(item, StatSockets), eth);
		tally.AddQuality(Fn<ItemQualityFn>(RvaItemQuality)(item), Fn<ItemAutomagicFn>(RvaItemAutomagic)(item) != 0);
		if (eth) {
			++nEth;
			sumEth += def;
			durEthMin = dur < durEthMin ? dur : durEthMin;
			durEthMax = dur > durEthMax ? dur : durEthMax;
		} else {
			++nNormal;
			sumNormal += def;
			durNormalMin = dur < durNormalMin ? dur : durNormalMin;
			durNormalMax = dur > durNormalMax ? dur : durNormalMax;
		}
		Fn<FreeItemFn>(RvaFreeItem)(c->game, item);
	}
	char sockets[96], qualities[96];
	tally.Sockets(sockets, sizeof(sockets));
	tally.Qualities(qualities, sizeof(qualities));
	Out("itemroll code=%s n=%d failed=%d ilvl=%d ethereal=%d identified=%d sockets=[%s] qualities=[%s] automagic=%d", t.tok[1], tally.n, failed, firstLevel,
	    tally.ethereal, nIdentified, sockets, qualities, tally.automagic);
	Out("itemroll def normal n=%d sum=%lld, ethereal n=%d sum=%lld; maxdur normal %d..%d, ethereal %d..%d", nNormal, sumNormal, nEth, sumEth,
	    durNormalMax < 0 ? 0 : durNormalMin, durNormalMax, durEthMax < 0 ? 0 : durEthMin, durEthMax);
	char gate[512];
	ItemGenGateText(gate, sizeof(gate));
	Out("itemroll %s", gate);
	ItemGenSocketText(gate, sizeof(gate));
	Out("itemroll %s", gate);
	return true;
}

// `colour <item id|code>`: D2R's item colour function 0x3710d0 (hooked for stat 368, the dye) on an item of the player's:
// the colour byte (transform kind << 5 + colour) and the palette entry it returns.
auto CmdColour(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long who = 0;
	if (t.n < 2) {
		return Fail(c, "usage: colour <item unit id|item code>");
	}
	Unit* item = nullptr;
	if (hcmd::ParseInt(t.tok[1], &who)) {
		EachItem(c, [&](Unit* it) {
			if (item == nullptr && IdOf(it) == static_cast<uint32_t>(who)) {
				item = it;
			}
		});
	} else {
		item = FindItemByCode(c, hcmd::CodeToDword(t.tok[1]), -1);
	}
	if (item == nullptr) {
		return Fail(c, "colour: item not found");
	}
	uint8_t colour = 0xee;
	const int64_t palette = Fn<ItemColourFn>(RvaItemColour)(c->player, item, &colour, 0);
	const uint8_t* rec = Fn<ItemRecordFn>(RvaItemRecord)(c->dataFlag, Fn<UnitClassFn>(RvaUnitClass)(item, "harness", 0));
	Out("colour item=%u dye=%d byte=0x%02x kind=%d palette=%s", IdOf(item), Stat(item, StatDye), static_cast<unsigned>(colour),
	    rec != nullptr ? static_cast<int>(d2r::At<uint8_t>(rec, 0x151)) : -1, palette != 0 ? "set" : "none");
	return true;
}

// `req <ref> [as <class>]`: the item requirement check 0x36bc50 (item_gen.cpp hooks it: class lock, mercenary lists) of every
// backpack item against the player or the mercenary. `as` puts another class on the unit for the call (a character class 0-6
// for the player, a monster class such as 338 for the mercenary) and restores it. Prints the class lock stat of the item and
// the ids of the mercenary list item types (hireclasses allow / deny lists) it belongs to.
auto CmdReq(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long as = -1;
	if (t.n < 2 || (t.n > 2 && !(hcmd::LowerEq(t.tok[2], "as") && t.n > 3 && hcmd::ParseInt(t.tok[3], &as)))) {
		return Fail(c, "usage: req player|merc|mon:id [as <class>]");
	}
	Unit* unit = ResolveRef(c, t.tok[1]);
	if (unit == nullptr) {
		return Fail(c, "req: unit not found (%s)", t.tok[1]);
	}
	auto* classField = reinterpret_cast<int32_t*>(reinterpret_cast<uint8_t*>(unit) + UnitClass);
	const int32_t savedClass = *classField;
	if (as >= 0) {
		*classField = static_cast<int32_t>(as);
	}
	int n = 0;
	EachItemOf(c->player, [&](Unit* it) {
		if (Fn<ItemByteFn>(RvaItemPage)(it) != 0) {
			return;
		}
		char code[5];
		ItemCode(c, it, code);
		uint32_t str = 9, dex = 9, level = 9;
		const uint64_t r = Fn<RequirementFn>(RvaRequirement)(it, unit, 0, &str, &dex, &level, 0);
		char types[96] = "";
		size_t len = 0;
		int seen[16] = {};
		int nseen = 0;
		for (const auto& mc : mxl_hirelings::MercClasses) {
			for (const int32_t* list : {mc.allow, mc.deny}) {
				for (int k = 0; k < 7 && list[k] >= 0; ++k) {
					bool dup = false;
					for (int s = 0; s < nseen; ++s) {
						dup = dup || seen[s] == list[k];
					}
					if (dup || nseen >= 16) {
						continue;
					}
					seen[nseen++] = list[k];
					if (Fn<IsItemTypeFn>(RvaIsItemType)(it, list[k]) != 0 && len + 8 < sizeof(types)) {
						len += static_cast<size_t>(std::snprintf(types + len, sizeof(types) - len, "%s%d", len > 0 ? "," : "", list[k]));
					}
				}
			}
		}
		Out("req id=%u code=%s usable=%d level=%u str=%u dex=%u lock=%d weapon=%d shield=%d types=%s", IdOf(it), code, static_cast<int>(r & 0xff), level,
		    str, dex, Stat(it, StatClassLock), Fn<IsItemTypeFn>(RvaIsItemType)(it, 0x2d) != 0, Fn<IsItemTypeFn>(RvaIsItemType)(it, 2) != 0,
		    len > 0 ? types : "-");
		++n;
	});
	*classField = savedClass;
	Out("req items %d unit=%s class=%d%s", n, t.tok[1], static_cast<int>(savedClass), as >= 0 ? " (restored)" : "");
	return true;
}

// Client side (UI thread): `cstat <stat> [layer] [set <value>]` reads a stat of the client's copy of the player (what the screen
// shows); `set` writes it there (the server's copy is not touched: a stat set on the server's unit does not reach the client).
auto CmdClientStat(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long stat = 0, layer = 0, value = 0;
	int next = 2;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &stat)) {
		return Fail(c, "usage: cstat <stat> [layer] [set <value>]");
	}
	if (t.n > next && !hcmd::LowerEq(t.tok[next], "set")) {
		if (!hcmd::ParseInt(t.tok[next], &layer)) {
			return Fail(c, "cstat: layer must be a number");
		}
		++next;
	}
	const bool set = t.n > next && hcmd::LowerEq(t.tok[next], "set");
	if (set && (t.n <= next + 1 || !hcmd::ParseInt(t.tok[next + 1], &value))) {
		return Fail(c, "cstat: set needs a number");
	}
	if (g_playerId == 0) {
		return Fail(c, "cstat: no player seen yet");
	}
	Unit* unit = Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(g_playerId), 0);
	if (unit == nullptr) {
		return Fail(c, "cstat: no client player unit");
	}
	if (set) {
		Fn<SetStatFn>(RvaSetStat)(unit, static_cast<int>(stat), static_cast<int32_t>(value), static_cast<int>(layer));
	}
	Out("cstat %lld:%lld = %d", stat, layer, Stat(unit, static_cast<int>(stat), static_cast<int>(layer)));
	return true;
}

// Client side (UI thread): `cltdo <skill id> [orig]` runs the skill's client function (cltdofunc, table 0x235f7d0 - the one the skill
// dispatcher 0x216d20 calls with (unit, skill, level)) on the client's copy of the player, at the player's level of the skill (1
// when it has none). Prints the function slot, the row's cltmissilea and what the function returned. A curse without a client
// missile used to hit D2R's "nMissile >= 0" assert here (sigma_skills.cpp CltDoCurse); `orig` runs D2R's own curse function
// (0x2b05d0) instead of the table entry, for the control of that assert (slot 30 rows only).
// `skillstats`: counters of the wrapped srvdofunc slots 41 (casts, melee hits thrown) and 73 (casts, missile b / c taken).
auto CmdSkillStats(Ctx*, const hcmd::Tokens&) noexcept -> bool {
	long fanCasts = 0, fanHits = 0, hammerCasts = 0, hammerSwaps = 0;
	SigmaSkillCounters(&fanCasts, &fanHits, &hammerCasts, &hammerSwaps);
	Out("skillstats fan casts=%ld melee hits=%ld hammer casts=%ld swaps=%ld", fanCasts, fanHits, hammerCasts, hammerSwaps);
	return true;
}

auto CmdCltDo(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long skill = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &skill)) {
		return Fail(c, "usage: cltdo <skill id> [orig]");
	}
	if (g_playerId == 0) {
		return Fail(c, "cltdo: no player seen yet");
	}
	Unit* unit = Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(g_playerId), 0);
	if (unit == nullptr) {
		return Fail(c, "cltdo: no client player unit");
	}
	const uint32_t dataFlag = Fn<UnitDataFlagFn>(RvaUnitDataFlag)(unit);
	const uint8_t* record = d2r::api.getSkillRecord(dataFlag, static_cast<int32_t>(skill));
	if (record == nullptr) {
		return Fail(c, "cltdo: no skills.txt row %lld", skill);
	}
	const int slot = d2r::At<int16_t>(record, 0x14a);
	const int missile = d2r::At<int16_t>(record, 0x140);
	if (slot < 0 || slot >= 130) {
		return Fail(c, "cltdo: skill %lld has no client function (cltdofunc %d)", skill, slot);
	}
	using CltFn = int64_t (*)(Unit*, int32_t, int32_t);
	const bool orig = t.n > 2 && hcmd::LowerEq(t.tok[2], "orig") && slot == 30;
	const uint64_t entry = orig ? g_base + 0x2b05d0
	                            : *reinterpret_cast<const volatile uint64_t*>(g_base + 0x235f7d0 + static_cast<uint64_t>(slot) * 8);
	if (entry == 0) {
		return Fail(c, "cltdo: slot %d is empty", slot);
	}
	const int64_t r = reinterpret_cast<CltFn>(entry)(unit, static_cast<int32_t>(skill), 1);
	Out("cltdo skill=%lld cltdofunc=%d cltmissilea=%d %s returned=%lld", skill, slot, missile, orig ? "orig" : "table",
	    static_cast<long long>(r));
	return true;
}

// `cltst <skill id> [orig]`: the client start function of the skill (record +0x148 = cltstfunc, table 0x235f590) called the way
// the client's skill start 0x218030 calls it; `orig` calls D2R's own function of slot 18 (0x2b0df0) directly, past the plugin's wrapper.
auto CmdCltSt(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long skill = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &skill)) {
		return Fail(c, "usage: cltst <skill id> [orig]");
	}
	if (g_playerId == 0) {
		return Fail(c, "cltst: no player seen yet");
	}
	Unit* unit = Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(g_playerId), 0);
	if (unit == nullptr) {
		return Fail(c, "cltst: no client player unit");
	}
	const uint32_t dataFlag = Fn<UnitDataFlagFn>(RvaUnitDataFlag)(unit);
	const uint8_t* record = d2r::api.getSkillRecord(dataFlag, static_cast<int32_t>(skill));
	if (record == nullptr) {
		return Fail(c, "cltst: no skills.txt row %lld", skill);
	}
	const int slot = d2r::At<int16_t>(record, 0x148);
	const int bound = *reinterpret_cast<const volatile int32_t*>(g_base + 0x235f7c0);
	const int missile = d2r::At<int16_t>(record, 0x144);
	if (slot < 0 || slot >= bound) {
		return Fail(c, "cltst: skill %lld has no client start function (cltstfunc %d, table bound %d)", skill, slot, bound);
	}
	using CltFn = int64_t (*)(Unit*, int32_t, int32_t);
	const bool orig = t.n > 2 && hcmd::LowerEq(t.tok[2], "orig") && slot == 18;
	const uint64_t entry = orig ? g_base + 0x2b0df0
	                            : *reinterpret_cast<const volatile uint64_t*>(g_base + 0x235f590 + static_cast<uint64_t>(slot) * 8);
	if (entry == 0) {
		return Fail(c, "cltst: slot %d is empty", slot);
	}
	const int64_t r = reinterpret_cast<CltFn>(entry)(unit, static_cast<int32_t>(skill), 1);
	Out("cltst skill=%lld cltstfunc=%d cltmissilec=%d %s returned=%lld", skill, slot, missile, orig ? "orig" : "table", static_cast<long long>(r));
	return true;
}

// `panelrow <stat>` runs the Advanced Stats panel's row functions (0x14eb1b0, 0x14eb250 - hooked by stat_columns.cpp) for a D2R
// stat id on the server's player unit (the harness equips and sets stats there; the client's copy only learns of them through
// packets): the displayed value and the row text (D2R colour codes removed), then the Strength / Dexterity bonus of the wielded
// weapon. The panel reads the same unit functions on the client's copy in play.
auto CmdPanelRow(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long stat = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &stat)) {
		return Fail(c, "usage: panelrow <stat id>");
	}
	Unit* unit = c->player;
	if (unit == nullptr) {
		return Fail(c, "panelrow: no player");
	}
	int64_t value = 0;
	char raw[256] = "";
	if (!StatColumnsProbe(unit, static_cast<int32_t>(stat), &value, raw, sizeof(raw))) {
		return Fail(c, "panelrow: stat %lld has no record, or the stat columns hooks are off", stat);
	}
	char text[256];
	size_t n = 0;
	for (size_t i = 0; raw[i] != '\0' && n + 1 < sizeof(text); ++i) {
		const size_t lead = static_cast<unsigned char>(raw[i]) == 0xff ? 1 : (static_cast<unsigned char>(raw[i]) == 0xc3 && static_cast<unsigned char>(raw[i + 1]) == 0xbf ? 2 : 0);
		if (lead != 0 && raw[i + lead] == 'c' && raw[i + lead + 1] != '\0') {  // colour code: 0xff (UTF-8: c3 bf) 'c' <digit>
			i += lead + 1;
			continue;
		}
		text[n++] = raw[i];
	}
	text[n] = '\0';
	Out("panelrow %lld value=%lld text=[%s]", stat, static_cast<long long>(value), text);
	int32_t strBonus = 0, dexBonus = 0;
	if (StatColumnsWeapon(unit, &strBonus, &dexBonus)) {
		Out("panelrow weapon strbonus=%d dexbonus=%d", strBonus, dexBonus);
	} else {
		Out("panelrow weapon none");
	}
	return true;
}

// Client side (UI thread): `mapmem` prints the automap layer of the current level (layer, table index, the sizes of its four
// room sets) and what the character's map file holds for it (nodes of this layer, nodes of other layers sharing the chain),
// with the counters of the map memory hooks (map_memory.cpp).
auto CmdMapMem(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	MapMemoryInfo info;
	if (!MapMemoryProbe(&info)) {
		return Fail(c, "mapmem: no automap layer is current");
	}
	Out("mapmem layer=%d bucket=%d cells=%llu,%llu,%llu,%llu file=%s size=%u nodes=%d foreign=%d clean=%d loads=%ld saves=%ld views=%ld resets=%ld",
	    info.layer, info.bucket, static_cast<unsigned long long>(info.cells[0]), static_cast<unsigned long long>(info.cells[1]),
	    static_cast<unsigned long long>(info.cells[2]), static_cast<unsigned long long>(info.cells[3]), info.haveFile ? "read" : "none",
	    info.fileSize, info.nodes, info.foreign, info.clean ? 1 : 0, info.loads, info.saves, info.views, info.resets);
	return true;
}

// Client side (UI thread): `ccorpses` counts the player-type units of the CLIENT's unit table (D2R's client table 0x2a23910, one
// 128-bucket hash per unit type, 0x400 bytes each, chained through +0x158 as the server's): the character itself and every
// other one - a corpse is a second player unit. Prints "ccorpses players=N self=S other=O ids=..." plus each other unit's
// id, mode and position. Median: other=0 always.
auto CmdClientCorpses(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	constexpr uint64_t RvaClientUnits = 0x2a23910;
	if (g_playerId == 0) {
		return Fail(c, "ccorpses: no player seen yet");
	}
	int players = 0, self = 0, other = 0, hidden = 0, guard = 0;
	char ids[160] = "";
	size_t used = 0;
	for (int b = 0; b < 128; ++b) {
		auto* u = *reinterpret_cast<Unit* const*>(g_base + RvaClientUnits + static_cast<uint64_t>(b) * 8);
		for (; u != nullptr && guard < 20000; u = d2r::At<Unit*>(u, UnitNextInHash), ++guard) {
			if (TypeOf(u) != 0) {
				continue;
			}
			++players;
			if (static_cast<LONG>(IdOf(u)) == g_playerId) {
				++self;
				continue;
			}
			int32_t ux = 0, uy = 0;
			d2r::UnitXY(u, &ux, &uy);
			if (ux == 0 && uy == 0) {  // the ten inert player-type units of D2R (ids 2-11): no position, no body
				++hidden;
				continue;
			}
			++other;
			if (used < sizeof(ids) - 48) {
				used += static_cast<size_t>(std::snprintf(ids + used, sizeof(ids) - used, "%u@%d,%d/m%d ", IdOf(u), ux, uy, ModeOf(u)));
			}
		}
	}
	Out("ccorpses players=%d self=%d other=%d hidden=%d ids=%s", players, self, other, hidden, other > 0 ? ids : "-");
	return true;
}

// --- lane bug-backlog-b: verbs for the old "fix to test" rows of docs/bugs.md ----------------------------------------

// Client side (UI thread): `skilltab [n]` the selected tab of the skill tree panel (bug #3), or select tab n through the
// hooked setter (the panel is the one the setter last saw: click any tab first).
auto CmdSkillTab(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n > 1) {
		long long tab = 0;
		if (!hcmd::ParseInt(t.tok[1], &tab) || tab < 0 || tab > 8) {
			return Fail(c, "usage: skilltab [0-8]");
		}
		if (!SkillTreeSetTab(static_cast<int32_t>(tab))) {
			return Fail(c, "skilltab: the tab setter has not run yet (open the skill tree and click a tab)");
		}
	}
	Out("skilltab current=%d setter_calls=%u", SkillTreeCurrentTab(), SkillTreeSetterCalls());
	return true;
}

// The text without D2R's colour codes (0xff or UTF-8 c3 bf, then 'c' and a digit; the loaded strings carry the code as the
// private use character U+E07E, UTF-8 ee 81 be, and one more character for the colour) and control characters.
void PlainText(const char* raw, char* out, size_t outSize) noexcept {
	size_t n = 0;
	for (size_t i = 0; raw[i] != '\0' && n + 1 < outSize; ++i) {
		const unsigned char ch = static_cast<unsigned char>(raw[i]);
		if (ch == 0xee && static_cast<unsigned char>(raw[i + 1]) == 0x81 && static_cast<unsigned char>(raw[i + 2]) == 0xbe && raw[i + 3] != '\0') {
			i += 3;
			continue;
		}
		const size_t lead = ch == 0xff ? 1 : (ch == 0xc3 && static_cast<unsigned char>(raw[i + 1]) == 0xbf ? 2 : 0);
		if (lead != 0 && raw[i + lead] == 'c' && raw[i + lead + 1] != '\0') {
			i += lead + 1;
			continue;
		}
		out[n++] = ch < 0x20 ? ' ' : static_cast<char>(ch);
	}
	out[n] = '\0';
}

Unit* ClientItemById(uint32_t id) noexcept {
	Unit* player = g_playerId != 0 ? Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(g_playerId), 0) : nullptr;
	Unit* found = nullptr;
	if (player != nullptr) {
		EachItemOf(player, [&](Unit* it) {
			if (found == nullptr && IdOf(it) == id) {
				found = it;
			}
		});
	}
	// an item on the ground is a client unit of its own (type 4)
	return found != nullptr ? found : Fn<ClientFindFn>(RvaClientFind)(id, 4);
}

// Client side (UI thread): `tip <item id|code>` the property text D2R builds for an item of the client's player (docs/item-tooltips.md):
// the item text function 0x2dc4b0 with the arguments of the last build the game made itself (hover an item once), one `tip line`
// per property line. `tip` alone prints that last real build. `tiplog [n|reset]` the property line formatter's calls (stat, value,
// layer, mode, answer), `tipfmt <stat> <value> [layer [mode [flag]]]` one formatter call on the client's player.
auto CmdTip(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (g_playerId == 0) {
		return Fail(c, "tip: no player seen yet");
	}
	char text[1024];
	if (t.n < 2) {
		tip::Build b;
		if (!TipLastBuild(&b)) {
			return Fail(c, "tip: the game has not built an item text yet (hover an item in the inventory)");
		}
		Out("tip build #%u item=%llx p4=%llx p5=%llx p6=%llx p7=%llx p8=%llx p9=%llx p10=%llx optional=%llx/%d", b.seq,
		    static_cast<unsigned long long>(b.arg[0]), static_cast<unsigned long long>(b.arg[3]), static_cast<unsigned long long>(b.arg[4]),
		    static_cast<unsigned long long>(b.arg[5]), static_cast<unsigned long long>(b.arg[6]), static_cast<unsigned long long>(b.arg[7]),
		    static_cast<unsigned long long>(b.arg[8]), static_cast<unsigned long long>(b.arg[9]),
		    static_cast<unsigned long long>(*reinterpret_cast<const uint64_t*>(b.optional)), static_cast<int>(b.optional[8]));
		std::snprintf(text, sizeof(text), "%s", b.text);
	} else {
		Unit* item = nullptr;
		long long id = 0;
		if (hcmd::ParseInt(t.tok[1], &id)) {
			item = ClientItemById(static_cast<uint32_t>(id));
		} else {
			const uint32_t code = hcmd::CodeToDword(t.tok[1]);
			Unit* player = Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(g_playerId), 0);
			if (player != nullptr) {
				EachItemOf(player, [&](Unit* it) {
					const uint8_t* rec = Fn<ItemRecordFn>(RvaItemRecord)(c->dataFlag, Fn<UnitClassFn>(RvaUnitClass)(it, "harness", 0));
					if (item == nullptr && rec != nullptr && d2r::At<uint32_t>(rec, 0x80) == code) {
						item = it;
					}
				});
			}
		}
		if (item == nullptr) {
			return Fail(c, "tip: no such item on the client");
		}
		if (!TipRender(item, text, sizeof(text))) {
			return Fail(c, "tip: no build to take the arguments from yet (hover an item once)");
		}
		Out("tip item=%u", IdOf(item));
	}
	int lines = 0;
	for (const char* p = text; *p != '\0';) {
		const char* end = std::strchr(p, '\n');
		const size_t len = end != nullptr ? static_cast<size_t>(end - p) : std::strlen(p);
		char raw[512], one[512];
		std::snprintf(raw, sizeof(raw), "%.*s", static_cast<int>(len < sizeof(raw) - 1 ? len : sizeof(raw) - 1), p);
		PlainText(raw, one, sizeof(one));
		Out("tip line %d: [%s]", ++lines, one);
		p += len + (end != nullptr ? 1 : 0);
	}
	Out("tip lines %d", lines);
	return true;
}

auto CmdTipLog(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long n = 40;
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "reset")) {
		TipReset();
		Out("tiplog reset");
		return true;
	}
	if (t.n >= 2 && !hcmd::ParseInt(t.tok[1], &n)) {
		return Fail(c, "usage: tiplog [n|reset]");
	}
	const uint32_t last = TipLineCount();
	const uint32_t first = last > static_cast<uint32_t>(n) ? last - static_cast<uint32_t>(n) + 1 : 1;
	for (uint32_t s = first; s <= last; ++s) {
		tip::Line l;
		if (!TipLineAt(s, &l)) {
			continue;
		}
		char text[256];
		PlainText(l.text, text, sizeof(text));
		Out("tiplog #%u stat=%d value=%d layer=%u mode=%d flag=%d viewer=%d:%u ret=%d text=[%s]", l.seq, l.stat, l.value, l.layer, l.mode, l.flag,
		    l.viewerType, l.viewerId, l.ret, text);
	}
	Out("tiplog lines %u", last);
	return true;
}

auto CmdTipFmt(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long stat = 0, value = 0, layer = 0, mode = 4, flag = 0;
	if (t.n < 3 || !hcmd::ParseInt(t.tok[1], &stat) || !hcmd::ParseInt(t.tok[2], &value) || (t.n > 3 && !hcmd::ParseInt(t.tok[3], &layer)) ||
	    (t.n > 4 && !hcmd::ParseInt(t.tok[4], &mode)) || (t.n > 5 && !hcmd::ParseInt(t.tok[5], &flag))) {
		return Fail(c, "usage: tipfmt <stat> <value> [layer [mode [flag]]]  (flag 1 = the group line)");
	}
	Unit* player = g_playerId != 0 ? Fn<ClientFindFn>(RvaClientFind)(static_cast<uint32_t>(g_playerId), 0) : nullptr;
	if (player == nullptr) {
		return Fail(c, "tipfmt: no client player unit");
	}
	char raw[256] = "";
	const int ret = TipFormat(player, static_cast<int>(stat), static_cast<int>(value), static_cast<uint32_t>(layer), static_cast<int>(mode),
	                          static_cast<int>(flag), raw);
	if (ret < 0) {
		return Fail(c, "tipfmt: stat %lld has no record, or the tooltip probe is off", stat);
	}
	char text[256];
	PlainText(raw, text, sizeof(text));
	Out("tipfmt stat=%lld value=%lld layer=%lld mode=%lld flag=%lld ret=%d text=[%s]", stat, value, layer, mode, flag, ret, text);
	// Keep the existing plain-text answer stable; also expose the actual escape for colour regression checks.
	const auto* bytes = reinterpret_cast<const unsigned char*>(raw);
	int colour = -1;
	if (bytes[0] == 0xee && bytes[1] == 0x81 && bytes[2] == 0xbe && bytes[3] != 0) colour = bytes[3] - '0';
	else if (bytes[0] == 0xc3 && bytes[1] == 0xbf && bytes[2] == 'c' && bytes[3] != 0) colour = bytes[3] - '0';
	Out("tipcolour stat=%lld layer=%lld colour=%d bytes=%zu", stat, layer, colour, std::strlen(raw));
	return true;
}

// Client side: `strids <id>...` the text the client's string table gives for string ids (bug #7: Median's keys must not answer with
// another key's text). `strids 45` is GheedIntroGossip1.
auto CmdStrIds(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: strids <string id>...");
	}
	for (int i = 1; i < t.n; ++i) {
		long long id = 0;
		if (!hcmd::ParseInt(t.tok[i], &id) || id < 0 || id > 0xffff) {
			return Fail(c, "strids: %.12s is not a string id (0..65535)", t.tok[i]);
		}
		const char* text = Fn<const char* (*)(uint32_t)>(0x3e2b730)(static_cast<uint32_t>(id));
		char plain[300];
		PlainText(text != nullptr ? text : "(null)", plain, sizeof(plain));
		Out("str %lld = [%s]", id, plain);
	}
	return true;
}

// Client side: `hover` the unit the hover name builder last ran for (bug #22: a monster under the cursor).
auto CmdHover(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	uint32_t id = 0, type = 0, cls = 0;
	const uint64_t age = MonsterLooksHovered(&id, &type, &cls);
	if (age == 0xffffffffffffffffULL) {
		return Fail(c, "hover: nothing was hovered since the game started (or monster looks / name colours are off)");
	}
	Out("hover id=%u type=%u class=%u age_ms=%llu", id, type, cls, static_cast<unsigned long long>(age));
	return true;
}

// Client side: `automap [type]` Median's automap rows of level types 36-51 (bug #15): the row range, how many of its rows the hooked
// lookup resolves to a cel the atlas has (< 1499), and how many lookups the game itself made for the type so far.
auto CmdAutomap(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long only = -1;
	if (t.n > 1 && !hcmd::ParseInt(t.tok[1], &only)) {
		return Fail(c, "usage: automap [level type]");
	}
	for (int32_t type = 36; type <= 51; ++type) {
		if (only >= 0 && type != only) {
			continue;
		}
		int32_t first = 0, end = 0;
		uint32_t calls = 0, hits = 0;
		LevelTypeCounters(type, &calls, &hits);
		if (!LevelTypeRows(type, &first, &end)) {
			Out("automap type=%d rows=0 (no Median AutoMap rows) game_lookups=%u hits=%u", type, calls, hits);
			continue;
		}
		int ok = 0, bad = 0, unreadable = 0;
		for (int32_t i = first; i < end; ++i) {
			int32_t tile = 0, startSeq = 0, cels = 0;
			uint32_t style = 0, cel0 = 0;
			if (!LevelTypeRowTable(i, &tile, &style, &startSeq, &cels, &cel0)) {
				++unreadable;
				continue;
			}
			const uint64_t cel = LevelTypeProbe(type, tile, style == 0xff ? 0 : style, startSeq);
			if (cel < 1499) {
				++ok;
			} else {
				++bad;
			}
		}
		Out("automap type=%d rows=%d resolved=%d bad=%d unreadable=%d game_lookups=%u hits=%u", type, end - first, ok, bad, unreadable, calls, hits);
		if (only >= 0) {  // one type asked for: the (tile type, style) pairs the game looked for in vain, and the rows' own pairs
			for (int m = 0;; ++m) {
				int32_t mt = 0, ms = 0;
				if (!LevelTypeMiss(type, m, &mt, &ms)) {
					break;
				}
				Out("  miss tile=%d style=%d", mt, ms);
			}
			for (int32_t i = first; i < end && i < first + 12; ++i) {
				int32_t tile = 0, startSeq = 0, cels = 0;
				uint32_t style = 0, cel0 = 0;
				if (LevelTypeRowTable(i, &tile, &style, &startSeq, &cels, &cel0)) {
					Out("  row %d tile=%d style=%u seq=%d", i, tile, style, startSeq);
				}
			}
		}
	}
	return true;
}

// `levelact <level id>...`: the act D2R's level table gives each level (the key / scroll portals link only levels of the same act).
auto CmdLevelAct(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: levelact <level id>...");
	}
	for (int i = 1; i < t.n; ++i) {
		long long id = 0;
		if (!hcmd::ParseInt(t.tok[i], &id) || id < 0 || id > 0xffff) {
			return Fail(c, "levelact: %.12s is not a level id", t.tok[i]);
		}
		Out("levelact %lld = %d", id, static_cast<int>(Fn<uint8_t (*)(uint32_t, int32_t)>(0x3e2b5c8)(c->dataFlag, static_cast<int32_t>(id))));
	}
	return true;
}

// `shop [npc class]`: the inventory of the nearest vendor (the server builds it when a player opens the trade panel: `interact <npc>`,
// then `menu <Trade line>`); bug #18 buys through the panel itself (a right click), see tools/game_checks.py check_vendors.
//
// `shop <class> restock` marks the stock stale (byte +0x35 of the NPC's shop state, (game, npc, &scratch) 0x502b70; the trade request 0x540850 clears and
// rebuilds a stale stock for a single player), so the next trade panel is built for the player's level and difficulty as they are now.
// The stock is otherwise built once per game, which a check that changes the level between two shops needs to get around.
auto CmdShop(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	long long cls = -1;
	if (t.n > 1 && !hcmd::ParseInt(t.tok[1], &cls)) {
		return Fail(c, "usage: shop [npc class] [restock]");
	}
	Unit* npc = NearestMonster(c, cls, true);
	if (npc == nullptr) {
		return Fail(c, "shop: no such NPC alive in this area");
	}
	if (t.n > 2 && hcmd::LowerEq(t.tok[2], "restock")) {
		uint8_t scratch[8] = {};
		uint8_t* state = Fn<uint8_t* (*)(Game*, Unit*, void*)>(RvaNpcMercList)(c->game, npc, scratch);
		if (state == nullptr) {
			return Fail(c, "shop: the NPC has no shop state");
		}
		state[0x35] = 1;
		Out("shop restock marked for npc id=%u (built %d)", IdOf(npc), static_cast<int>(state[0x34]));
		return true;
	}
	{
		const VendorStockTrace trace = VendorStockTraceNow();
		Out("shop npc id=%u class=%d | stock builds %ld, last item level %d -> %d (cap), difficulty %d", IdOf(npc), ClassOf(npc), trace.builds,
		    trace.ilvlIn, trace.ilvlOut, trace.difficulty);
	}
	int items = 0;
	EachItemOf(npc, [&](Unit* it) {
		++items;
		if (items <= 60) {
			DescribeItem(c, it);
		}
	});
	Out("shop items %d", items);
	return true;
}

// `gamble`: the player's gamble offers (the server builds the list on every gamble request: `interact <Gheed>`, then `menu <Gamble
// line>`), read from the player data (+0x108); same item lines as `shop`, then `gamble offers N`. tools/game_checks.py check_gamble.
auto CmdGamble(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	const uint8_t* data = Fn<PlayerDataFn>(RvaPlayerData)(c->player);
	void* list = data != nullptr ? d2r::At<void*>(data, 0x108) : nullptr;
	int offers = 0;
	if (list != nullptr) {
		int guard = 0;
		Unit* item = Fn<InvFirstFn>(RvaInvFirst)(list);
		while (item != nullptr && guard++ < 200) {
			Unit* next = Fn<InvNextFn>(RvaInvNext)(item);
			if (TypeOf(item) == 4) {
				++offers;
				if (offers <= 60) {
					DescribeItem(c, item);
				}
			}
			item = next;
		}
	}
	Out("gamble offers %d (expected %d, list %s) difficulty=%d", offers, gamble::MedianOffers, list != nullptr ? "present" : "none",
	    static_cast<int>(d2r::At<uint8_t>(c->game, GameDifficulty)));
	return list != nullptr;
}

// `gaps`: the small engine rules (engine_gaps_logic.h): the bytes at the three patched places and the player's slow floor as the
// hooked function 0x449f40 returns it. tools/game_checks.py check_engine_gaps.
auto CmdGaps(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	auto hex = [](uint64_t rva, size_t n, char* out) {
		const uint8_t* p = reinterpret_cast<const uint8_t*>(g_base + rva);
		for (size_t i = 0; i < n; ++i) {
			std::snprintf(out + i * 2, 3, "%02x", p[i]);
		}
	};
	char hit[32] = "", recast[40] = "";
	hex(gaps::Hit20FloorRva, sizeof(gaps::Hit20FloorPatched), hit);
	hex(gaps::RecastGuardRva, sizeof(gaps::RecastGuardPatched), recast);
	const bool hitOn = gaps::SameBytes(reinterpret_cast<const uint8_t*>(g_base + gaps::Hit20FloorRva), gaps::Hit20FloorPatched, sizeof(gaps::Hit20FloorPatched));
	const bool recastOn =
	    gaps::SameBytes(reinterpret_cast<const uint8_t*>(g_base + gaps::RecastGuardRva), gaps::RecastGuardPatched, sizeof(gaps::RecastGuardPatched));
	const int difficulty = static_cast<int>(d2r::At<uint8_t>(c->game, GameDifficulty));
	Out("gaps hit20=%s hit20_patched=%d recast=%s recast_patched=%d slowfloor=%d expected_slowfloor=%d difficulty=%d reqlevel_sites=%d", hit,
	    hitOn ? 1 : 0, recast, recastOn ? 1 : 0, EngineGapsSlowFloor(c->game, c->player), gaps::PlayerSlowFloor(difficulty), difficulty,
	    RequiredLevelPatchedSites());
	return true;
}

// Client side: the plugin's own string ids (strings.h). `mstr <full key>` reads the key through the localization service,
// takes (or finds) the plugin id for it and reads the text back through D2R's numeric lookup, the way the NPC menu does.
auto CmdMstr(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: mstr <full key, e.g. medianxl:AkaraMenu1b>");
	}
	char service[512];
	char viaId[512];
	const bool found = StringLookup(t.tok[1], service, sizeof(service));
	const mxlstr::Ref ref{0, t.tok[1]};
	const uint16_t id = StringId(ref);
	StringProbeId(id, viaId, sizeof(viaId));
	Out("mstr %s service=%s text=\"%s\" id=%u (0x%x) via D2R lookup=\"%s\" ids=%d", t.tok[1], found ? "ok" : "missing", service, id,
	    id, viaId, StringIdCount());
	return id != 0;
}

auto CmdHelp(Ctx*, const hcmd::Tokens&) noexcept -> bool {
	Out("harness frames seen %ld last game %ld", static_cast<long>(g_frames), static_cast<long>(g_lastGame));
	Out("verbs: state | merc | mercreq | mercprice [level] | players [1-8] | tctrace [reset] | leash [distance] | a5done | countessreward | hellforgereward [class] | prisonreward | hire [npc class] [n] | dump player|client|mon <class>|ground | kill <id>|nearest [class] | xp <amount> | spawn <class> [n] | interact nearest|<npc class> | menu list|<line>|cancel|confirm|yes|no | "
	    "msg nearest|<npc class> <message id> | quest <id> <bit>|dump set|clear|get | item <code> [stat=value..] [q=n] [ilvl=n] [inv|cube|ground] | cubecraft | remove <code> [n] | pkt <hex bytes> | missile <row> [dx dy] | missilescan [row] | enter nearest|<portal id> | tile | packclear | cubeclear | cuberec <n> | class <0-6> | difficulty <0-2> | "
	    "flag player|game <n> get|set|clear | waypoint <level>|n <number>|all [get|set|clear]|open|tabs|panel | gold get|set <carried> <bank> | level <id> | use <code> | stat player|<id>|<code> <stat> [layer] | text id|key|row|scan (resolved display strings)");
	Out("player actions: move <x> <y> [walk] [packet] | moveto <unit id>|nearest [class] | skill [left|right <id>] | setskill <id> <level> | "
	    "skills | cast <id> [x y|unit <id>|nearest [class]|self] | mapcells (client) | reveal (client) | hotkey pickup|reveal|transmute (client) | wpobj | travel (client) | stashprobe <tab>|result (client) | stashpage state|open|close|toggle|msgs|uia|widget|vis|put|fill|drop|list|move|result (client) | equip <code> [stat=value..] <bodyloc> | unequip <bodyloc> | missiles [reset]");
	Out("backlog verbs: skilltab [n] (client) | strids <id>.. (client) | hover (client) | automap [type] (client) | shop [npc class] | gamble | gaps | levelact <id>..");
	Out("verify verbs: hit <player|merc|mon:id> phys|fire|ltng|magic|cold <amount> [attacker] [stagger] | avoid <ref> melee|missile|evade [n] | wear <attacker ref> <defender ref> [n] | iflags <item id> [unid] | cursor | manamin [reset] | manacharge | afford <skill> | hc [on|off] | tpgold | "
	    "itemroll <code> <n> [q=] [ilvl=] | colour <item id|code> | req <ref> [as <class>] | cstat <stat> [layer] (client) | panelrow <stat> | mapmem (client) | stat merc|mon:<id> <stat>");
	Out("backlog verbs: stat <ref> <stat> scan [max layer] | cubeslots <first> <count> | cubeout <recipe> [slot] (portal outputs) | state (portal dest=)");
	return true;
}

// Client side: strings through D2RLoader's localization service and D2R's own numeric lookup (docs/strings-namespace-research.md).
//   str key <full key>      getStringByKey ("medianxl:Key", "d2r:strCancel"; a bare key searches the plugin's own "mxl-core")
//   str id <n>              getStringById (original game IDs only)
//   str native <n>          D2R's numeric lookup (the thunk the NPC menu uses) for id n (0..65535)
//   str find <text>         every id 0..65535 whose native text contains <text> (case-insensitive, at most 40 listed)
auto CmdStr(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 3) {
		return Fail(c, "usage: str key <full key> | id <n> | native <n> | find <text>");
	}
	char text[1024];
	if (hcmd::LowerEq(t.tok[1], "key")) {
		const int rc = StringsProbeKey(t.tok[2], text, sizeof(text));
		Out("str key %s result=%d text=\"%s\"", t.tok[2], rc, text);
		return rc == 0;
	}
	long long id = 0;
	if (hcmd::LowerEq(t.tok[1], "id") || hcmd::LowerEq(t.tok[1], "native")) {
		if (!hcmd::ParseInt(t.tok[2], &id) || id < 0 || id > 0xffffffffLL) {
			return Fail(c, "str: bad id");
		}
		if (hcmd::LowerEq(t.tok[1], "id")) {
			const int rc = StringsProbeId(static_cast<uint32_t>(id), text, sizeof(text));
			Out("str id %lld result=%d text=\"%s\"", id, rc, text);
			return rc == 0;
		}
		const bool ok = StringsProbeNative(static_cast<uint32_t>(id), text, sizeof(text));
		Out("str native %lld %s text=\"%s\"", id, ok ? "ok" : "unreadable", text);
		return ok;
	}
	if (hcmd::LowerEq(t.tok[1], "find")) {
		char needle[128];
		std::snprintf(needle, sizeof(needle), "%s", t.tok[2]);
		for (char* p = needle; *p != '\0'; ++p) {
			if (*p >= 'A' && *p <= 'Z') *p = static_cast<char>(*p + 32);
		}
		int hits = 0;
		for (uint32_t i = 0; i <= 0xffff; ++i) {
			if (!StringsProbeNative(i, text, sizeof(text)) || text[0] == '\0') {
				continue;
			}
			char original[1024];
			std::snprintf(original, sizeof(original), "%s", text);
			for (char* p = text; *p != '\0'; ++p) {
				if (*p >= 'A' && *p <= 'Z') *p = static_cast<char>(*p + 32);
			}
			if (std::strstr(text, needle) != nullptr && ++hits <= 40) {
				Out("str find %u (0x%x) text=\"%s\"", i, i, original);
			}
		}
		Out("str find \"%s\": %d hits", needle, hits);
		return hits > 0;
	}
	return Fail(c, "usage: str key <full key> | id <n> | native <n> | find <text>");
}

// Client side (UI thread): the NPC menu the 0x27 packet opened.
auto CmdMenu(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "confirm")) {  // the Yes / No page of a respec-style line
		Out("menu confirm %s", NpcConfirmOpen() ? "open" : "closed");
		return true;
	}
	if (t.n >= 2 && (hcmd::LowerEq(t.tok[1], "yes") || hcmd::LowerEq(t.tok[1], "no"))) {
		const bool yes = hcmd::LowerEq(t.tok[1], "yes");
		if (!NpcConfirmAnswer(yes)) {
			return Fail(c, "menu: no confirmation is open");
		}
		Out("menu confirm answered %s", yes ? "yes" : "no");
		return true;
	}
	const auto* b = reinterpret_cast<const uint8_t*>(g_base);
	if (*reinterpret_cast<const uint32_t*>(b + RvaMenuNpcValid) == 0 || *reinterpret_cast<const uint32_t*>(b + RvaMenuOpenFlag) == 0) {
		return Fail(c, "menu: no NPC menu is open (interact first, then wait a moment for the client)");
	}
	Unit* npc = Fn<ClientFindFn>(RvaClientFind)(*reinterpret_cast<const uint32_t*>(b + RvaMenuNpcId), 1);
	const int32_t row = npc != nullptr ? Fn<MenuRecordFn>(RvaMenuRecord)(npc) : -1;
	const uint32_t count = *reinterpret_cast<const uint32_t*>(b + RvaMenuCount);
	const auto* table = *reinterpret_cast<const uint8_t* const*>(b + RvaMenuTable);
	if (row < 0 || static_cast<uint32_t>(row) >= count || table == nullptr) {
		return Fail(c, "menu: NPC row not found");
	}
	const uint8_t* r = table + static_cast<size_t>(row) * 0x48;
	const int32_t lines = d2r::At<int32_t>(r, 4);  // includes the final Cancel
	if (t.n < 2) {
		return Fail(c, "usage: menu list | menu <line index> | menu cancel | menu confirm | menu yes | menu no");
	}
	if (hcmd::LowerEq(t.tok[1], "list")) {
		Out("menu npc id=%u class=%u row=%d lines=%d (+ Cancel)", *reinterpret_cast<const uint32_t*>(b + RvaMenuNpcId),
		    static_cast<unsigned>(*reinterpret_cast<const uint16_t*>(b + RvaMenuNpcClass)), row, lines - 1);
		for (int i = 0; i < lines - 1 && i < 5; ++i) {
			const uint64_t handler = d2r::At<uint64_t>(r, 0x18 + 8 * i);
			const bool inImage = handler >= g_base && handler < g_base + 0x4000000;
			Out("  line %d string=0x%x handler=%s0x%llx", i, static_cast<unsigned>(d2r::At<uint16_t>(r, 8 + 2 * i)),
			    inImage ? "image+" : "plugin@", static_cast<unsigned long long>(inImage ? handler - g_base : handler));
		}
		return true;
	}
	long long line = 0;
	uint64_t handler = 0;
	if (hcmd::LowerEq(t.tok[1], "cancel")) {
		handler = g_base + 0x112c30;
	} else if (hcmd::ParseInt(t.tok[1], &line) && line >= 0 && line < lines - 1 && line < 5) {
		handler = d2r::At<uint64_t>(r, 0x18 + 8 * static_cast<int>(line));
	} else {
		return Fail(c, "menu: line %.20s is not in 0..%d", t.tok[1], lines - 2);
	}
	if (handler == 0) {
		return Fail(c, "menu: that line has no handler");
	}
	const uint8_t res = reinterpret_cast<MenuHandlerFn>(handler)(static_cast<uint8_t>(c->dataFlag));
	Out("menu line %s handler 0x%llx returned %u", t.tok[1], static_cast<unsigned long long>(handler), static_cast<unsigned>(res));
	return true;
}

// --- `text`: the display string the game resolves (lane ns-verify, game_checks.py "strings") ---------------------------------
// The string lookup the NPC menu uses (npc_actions.cpp): D2RCore's thunk, u16 string id -> UTF-8 text. Table rows hold the same
// u16 references, so reading a row's name field and resolving it here is what the player sees, whatever the loader assigned.
constexpr uint64_t RvaStringThunk = 0x3e2b730;  // (u32 id) -> const char*
using StringFn = const char* (*)(uint32_t);
const D2RL::PluginContext* g_textContext = nullptr;

// --- `asserttrace`: who raises D2R's engine asserts (lane p4-engine-b) -----------------------------------------------------------
// Every BC_ASSERT of the engine ends in the report function 0x75ff0 (descriptor pointer in rcx: file name at +0, message at +0x20).
// `asserttrace on` hooks it; each call keeps the message, the file and 16 return addresses found by scanning the stack (RVAs of the image) in a ring of 24 and writes them
// to mxl-core.log ("assert trace: ..."). `asserttrace show` prints the ring, `asserttrace clear` empties it. The log of the loader names the
// message but not the place; this gives the call chain, which is where a bad row or argument comes from.
constexpr uint64_t RvaAssertReport = 0x75ff0;
constexpr uint8_t AssertReportEntry[] = {0x48, 0x83, 0xec, 0x28, 0x48, 0x8d, 0x05, 0x05, 0x1f, 0xc4, 0x01};
constexpr int AssertFrames = 16;
constexpr int AssertRing = 24;
struct AssertEvent {
	char message[96];
	char file[96];
	uint32_t frames[AssertFrames];
	int count;
	long skill, level, cls;  // the last srvdofunc 65 call (see SrvDo65Hook)
};
AssertEvent g_asserts[AssertRing];
// The last skill the aura-style server function 65 (0x563d90, the nRadius assert's caller) ran for: skill id, level, unit class.
constexpr uint64_t RvaSrvDo65 = 0x563d90;
constexpr uint8_t SrvDo65Entry[] = {0x40, 0x55, 0x53, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x48, 0x8d, 0x6c, 0x24, 0xb8};
volatile LONG g_do65Skill = -1;
volatile LONG g_do65Level = -1;
volatile LONG g_do65Class = -1;
int64_t (*g_do65Original)(void*, void*, int, int) = nullptr;
auto SrvDo65Hook(void* game, void* unit, int skill, int level) noexcept -> int64_t {
	g_do65Skill = skill;
	g_do65Level = level;
	g_do65Class = -1;
	__try {
		g_do65Class = static_cast<LONG>(*reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(unit) + 4));
	} __except (EXCEPTION_EXECUTE_HANDLER) {
	}
	return g_do65Original(game, unit, skill, level);
}
volatile LONG g_assertCount = 0;
void (*g_assertOriginal)(void*) = nullptr;
bool g_assertHooked = false;

void ReadGuarded(const void* at, char* out, size_t cap) noexcept {
	out[0] = '\0';
	__try {
		const char* p = static_cast<const char*>(at);
		size_t i = 0;
		for (; i + 1 < cap && p[i] != '\0' && static_cast<unsigned char>(p[i]) >= 0x20; ++i) {
			out[i] = p[i];
		}
		out[i] = '\0';
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		out[0] = '\0';
	}
}

void AssertReportHook(void* descriptor) noexcept {
	const LONG slot = (InterlockedIncrement(&g_assertCount) - 1) % AssertRing;
	AssertEvent& e = g_asserts[slot];
	e.message[0] = e.file[0] = '\0';
	if (descriptor != nullptr) {
		const char* const* d = static_cast<const char* const*>(descriptor);
		__try {
			ReadGuarded(d[0], e.file, sizeof(e.file));
			ReadGuarded(d[4], e.message, sizeof(e.message));
		} __except (EXCEPTION_EXECUTE_HANDLER) {
		}
	}
	// The unwinder stops after one frame in the engine's code, so the stack is scanned: every value of the next 400 slots that is a
	// return address (inside the image, a call instruction before it) is a frame of the chain, innermost first.
	e.count = 0;
	e.skill = g_do65Skill;
	e.level = g_do65Level;
	e.cls = g_do65Class;
	char line[600];
	size_t used = static_cast<size_t>(std::snprintf(line, sizeof(line), "assert trace: %s | %s | skill %ld lvl %ld class %ld |", e.message, e.file,
	                                                  static_cast<long>(g_do65Skill), static_cast<long>(g_do65Level), static_cast<long>(g_do65Class)));
	const uint64_t* sp = static_cast<const uint64_t*>(_AddressOfReturnAddress());
	__try {
		for (int i = 0; i < 400 && e.count < AssertFrames; ++i) {
			const uint64_t v = sp[i];
			if (v < g_base + 0x1000 || v >= g_base + 0x1400000) {
				continue;
			}
			const uint8_t* at = reinterpret_cast<const uint8_t*>(v);
			if (at[-5] != 0xe8 && !(at[-6] == 0xff && (at[-5] & 0x38) == 0x10) && !(at[-2] == 0xff && (at[-1] & 0x38) == 0x10)) {
				continue;
			}
			e.frames[e.count++] = static_cast<uint32_t>(v - g_base);
			if (used + 12 < sizeof(line)) {
				used += static_cast<size_t>(std::snprintf(line + used, sizeof(line) - used, " %x", e.frames[e.count - 1]));
			}
		}
	} __except (EXCEPTION_EXECUTE_HANDLER) {
	}
	if (g_textContext != nullptr) {
		g_textContext->LogInfo(line);
	}
	if (g_assertOriginal != nullptr) {
		g_assertOriginal(descriptor);
	}
}

// --- `passivetrace`: who applies the skill passives (lane ied-vanish) ---------------------------------------------------------------
// `passivetrace on` hooks the passive apply step 0x337890 (unit, skill id, flag) and the passive refresh 0x33f830 (unit, flag). Every call keeps
// the time, the skill, the flag, the inputs of the innate formula (stat 97 / 412 of the hidden skill 2072 and Dexterity), the fire minimum
// before and after, and the call chain (RVAs found by scanning the stack for return addresses) in a ring of 256; `show` prints it.
constexpr uint64_t RvaPassiveApply = 0x337890;
constexpr uint8_t PassiveApplyEntry[] = {0x89, 0x54, 0x24, 0x10, 0x55, 0x56, 0x57, 0x41, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x60};
constexpr uint64_t RvaPassiveRefresh = 0x33f830;
constexpr uint8_t PassiveRefreshEntryBytes[] = {0x88, 0x54, 0x24, 0x10, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x58};
struct PassiveEvent {
	ULONGLONG ms;
	int kind;  // 0 apply, 1 refresh
	int skill, flag, osk, syn, dex, fireBefore, fireAfter;
	uint32_t chain[8];
};
constexpr int PassiveRing = 256;
PassiveEvent g_passiveEvents[PassiveRing];
volatile LONG g_passiveCount = 0;
bool g_passiveHooked = false;
void (*g_passiveApplyOriginal)(Unit*, int32_t, uint8_t) = nullptr;
void (*g_passiveRefreshOriginal)(Unit*, int32_t) = nullptr;

void PassiveChain(PassiveEvent& e) noexcept {
	int found = 0;
	const uint64_t* sp = static_cast<const uint64_t*>(_AddressOfReturnAddress());
	for (int k = 0; k < 200 && found < 8; ++k) {
		const uint64_t v = sp[k];
		if (v < g_base + 0x1000 || v >= g_base + 0x4000000) {
			continue;
		}
		const uint8_t* b = reinterpret_cast<const uint8_t*>(v);
		if (b[-5] == 0xe8 || (b[-6] == 0xff && b[-5] == 0x15) || (b[-2] == 0xff && (b[-1] & 0xf8) == 0xd0) ||
		    (b[-3] == 0x41 && b[-2] == 0xff && (b[-1] & 0xf8) == 0xd0)) {
			e.chain[found++] = static_cast<uint32_t>(v - g_base);
		}
	}
}

void PassiveBegin(PassiveEvent& e, Unit* unit, int kind, int skill, int flag) noexcept {
	e.ms = GetTickCount64();
	e.kind = kind;
	e.skill = skill;
	e.flag = flag;
	std::memset(e.chain, 0, sizeof(e.chain));
	PassiveChain(e);
	__try {
		e.osk = Stat(unit, 97, 2072);
		e.syn = Stat(unit, 412, 2072);
		e.dex = Stat(unit, 2);
		e.fireBefore = Stat(unit, 48);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		e.osk = e.syn = e.dex = e.fireBefore = -1;
	}
}

void PassiveApplyHook(Unit* unit, int32_t skill, uint8_t flag) noexcept {
	PassiveEvent e{};
	PassiveBegin(e, unit, 0, skill, flag);
	g_passiveApplyOriginal(unit, skill, flag);
	e.fireAfter = Stat(unit, 48);
	g_passiveEvents[InterlockedIncrement(&g_passiveCount) % PassiveRing] = e;
}

void PassiveRefreshHook(Unit* unit, int32_t flag) noexcept {
	PassiveEvent e{};
	PassiveBegin(e, unit, 1, -1, flag);
	g_passiveRefreshOriginal(unit, flag);
	e.fireAfter = Stat(unit, 48);
	g_passiveEvents[InterlockedIncrement(&g_passiveCount) % PassiveRing] = e;
}

// `passivetrace on|off-ring|clear|show [n]`
auto CmdPassiveTrace(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: passivetrace on|clear|show [last n]");
	}
	if (hcmd::LowerEq(t.tok[1], "on")) {
		if (!g_passiveHooked) {
			if (g_textContext == nullptr ||
			    !g_textContext->InstallInlineHook(RvaPassiveApply, PassiveApplyEntry, sizeof(PassiveApplyEntry), reinterpret_cast<void*>(&PassiveApplyHook),
			                                      reinterpret_cast<void**>(&g_passiveApplyOriginal)) ||
			    !g_textContext->InstallInlineHook(RvaPassiveRefresh, PassiveRefreshEntryBytes, sizeof(PassiveRefreshEntryBytes),
			                                      reinterpret_cast<void*>(&PassiveRefreshHook), reinterpret_cast<void**>(&g_passiveRefreshOriginal))) {
				return Fail(c, "passivetrace: hook of 0x337890 / 0x33f830 failed");
			}
			g_passiveHooked = true;
		}
		Out("passivetrace on (%ld events so far)", static_cast<long>(g_passiveCount));
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "clear")) {
		InterlockedExchange(&g_passiveCount, 0);
		Out("passivetrace cleared");
		return true;
	}
	long long last = 40;
	if (t.n > 2) {
		hcmd::ParseInt(t.tok[2], &last);
	}
	const LONG total = g_passiveCount;
	LONG first = total > PassiveRing ? total - PassiveRing + 1 : 1;
	if (total - first + 1 > last) {
		first = total - static_cast<LONG>(last) + 1;
	}
	const ULONGLONG now = GetTickCount64();
	for (LONG i = first; i <= total; ++i) {
		const PassiveEvent& e = g_passiveEvents[i % PassiveRing];
		Out("pt#%ld -%llums %s skill=%d flag=%d osk=%d syn=%d dex=%d fire %d->%d | %x %x %x %x %x %x %x %x", static_cast<long>(i),
		    static_cast<unsigned long long>(now - e.ms), e.kind == 0 ? "apply  " : "refresh", e.skill, e.flag, e.osk, e.syn, e.dex, e.fireBefore,
		    e.fireAfter, e.chain[0], e.chain[1], e.chain[2], e.chain[3], e.chain[4], e.chain[5], e.chain[6], e.chain[7]);
	}
	Out("passivetrace show: %ld events", static_cast<long>(total));
	return true;
}

auto CmdAssertTrace(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: asserttrace on|show|clear");
	}
	if (hcmd::LowerEq(t.tok[1], "on")) {
		if (!g_assertHooked) {
			if (g_textContext == nullptr ||
			    !g_textContext->InstallInlineHook(RvaAssertReport, AssertReportEntry, sizeof(AssertReportEntry),
			                                      reinterpret_cast<void*>(&AssertReportHook), reinterpret_cast<void**>(&g_assertOriginal))) {
				return Fail(c, "asserttrace: hook of 0x75ff0 failed");
			}
			g_assertHooked = true;
			if (g_textContext->InstallInlineHook(RvaSrvDo65, SrvDo65Entry, sizeof(SrvDo65Entry), reinterpret_cast<void*>(&SrvDo65Hook),
			                                     reinterpret_cast<void**>(&g_do65Original))) {
				Out("asserttrace: srvdofunc 65 tracked");
			}
		}
		Out("asserttrace on (%ld asserts so far)", static_cast<long>(g_assertCount));
		return true;
	}
	if (hcmd::LowerEq(t.tok[1], "clear")) {
		InterlockedExchange(&g_assertCount, 0);
		Out("asserttrace cleared");
		return true;
	}
	const LONG total = g_assertCount;
	const LONG first = total > AssertRing ? total - AssertRing : 0;
	for (LONG i = first; i < total; ++i) {
		const AssertEvent& e = g_asserts[i % AssertRing];
		char frames[256] = "";
		size_t used = 0;
		for (int k = 0; k < e.count && used + 12 < sizeof(frames); ++k) {
			used += static_cast<size_t>(std::snprintf(frames + used, sizeof(frames) - used, "%s%x", k > 0 ? " " : "", e.frames[k]));
		}
		Out("assert %ld: %s [do65 skill %ld lvl %ld class %ld] | %s | %s", static_cast<long>(i), e.message, e.skill, e.level, e.cls, e.file, frames);
	}
	Out("asserttrace show: %ld asserts", static_cast<long>(total));
	return true;
}


// D2R colour codes removed, newlines written as the two characters \n. A colour code is 0xff 'c' <char> (UTF-8 c3 bf) in the files;
// the loaded strings hold it as one private-use character (UTF-8 ee 81 be) followed by the colour character.
void CleanText(const char* raw, char* text, size_t cap) noexcept {
	size_t n = 0;
	for (size_t i = 0; raw != nullptr && raw[i] != '\0' && n + 2 < cap; ++i) {
		if (static_cast<unsigned char>(raw[i]) == 0xee && static_cast<unsigned char>(raw[i + 1]) == 0x81 && static_cast<unsigned char>(raw[i + 2]) == 0xbe &&
		    raw[i + 3] != '\0') {
			i += 3;
			continue;
		}
		const size_t lead = static_cast<unsigned char>(raw[i]) == 0xff ? 1 : (static_cast<unsigned char>(raw[i]) == 0xc3 && static_cast<unsigned char>(raw[i + 1]) == 0xbf ? 2 : 0);
		if (lead != 0 && raw[i + lead] == 'c' && raw[i + lead + 1] != '\0') {
			i += lead + 1;
			continue;
		}
		if (raw[i] == '\n') {
			text[n++] = '\\';
			text[n++] = 'n';
			continue;
		}
		if (raw[i] == '\r') {
			continue;
		}
		text[n++] = raw[i];
	}
	text[n] = '\0';
}

// One answer line: `<head> len=<bytes of the cleaned text> fnv=<FNV-1a of it> raw=<first bytes> = [<first 200 bytes>]`. A long text
// (an NPC speech) does not fit one line, so the caller compares the length and the hash.
void PrintText(const char* head, const char* raw) noexcept {
	static char text[4096];
	CleanText(raw, text, sizeof(text));
	uint32_t h = 2166136261u;
	size_t len = 0;
	for (; text[len] != '\0'; ++len) {
		h = (h ^ static_cast<unsigned char>(text[len])) * 16777619u;
	}
	char hex[16] = "";
	for (int i = 0; i < 6 && raw != nullptr && raw[i] != '\0'; ++i) {
		std::snprintf(hex + 2 * i, sizeof(hex) - 2 * static_cast<size_t>(i), "%02x", static_cast<unsigned>(static_cast<unsigned char>(raw[i])));
	}
	Out("%s len=%zu fnv=%08x raw=%s = [%.200s]", head, len, static_cast<unsigned>(h), hex, text);
}

auto TableByName(const char* name, D2RL::DataTables::TableId* id) noexcept -> bool {
	using T = D2RL::DataTables::TableId;
	static const struct {
		const char* name;
		T id;
	} tables[] = {{"itemstatcost", T::ItemStatCost}, {"skilldesc", T::SkillDesc}, {"skills", T::Skills}, {"levels", T::Levels},
	              {"monstats", T::MonStats}, {"superuniques", T::SuperUniques}, {"uniqueitems", T::UniqueItems},
	              {"setitems", T::SetItems}, {"sets", T::Sets}, {"magicaffixes", T::MagicAffixes}, {"items", T::Items},
	              {"itemtypes", T::ItemTypes}, {"runes", T::Runes}, {"shrines", T::Shrines}, {"objects", T::Objects},
	              {"states", T::States}, {"npc", T::Npc}, {"uniqueprefix", T::UniquePrefix}, {"uniquesuffix", T::UniqueSuffix},
	              {"uniqueappellation", T::UniqueAppellation}};
	for (const auto& e : tables) {
		if (hcmd::LowerEq(name, e.name)) {
			*id = e.id;
			return true;
		}
	}
	return false;
}

// A compiled row by `<index>`, `code:<abcd>` (Items, ItemTypes) or `id:<n>` (Skills, Levels, ...) on the data table service;
// the bank is the token at bankTok (1 classic, 2 lod, 3 rotw; default 3).
auto FindTextRow(Ctx* c, const hcmd::Tokens& t, int tableTok, int bankTok, D2RL::DataTables::RowView* row) noexcept -> bool {
	const D2RL::DataTableService* svc = nullptr;
	if (g_textContext == nullptr || g_textContext->QueryService(&svc) != D2RL::ServiceQueryResult::Success || svc == nullptr ||
	    !D2RL::HasDataTableServiceField(svc, D2RL::DataTableServiceRequiredSize)) {
		return Fail(c, "text: no data table service");
	}
	D2RL::DataTables::TableId table = D2RL::DataTables::TableId::Unknown;
	if (t.n <= tableTok + 1 || !TableByName(t.tok[tableTok], &table)) {
		return Fail(c, "text: unknown table %.30s", t.n > tableTok ? t.tok[tableTok] : "?");
	}
	long long bank = 3;
	if (bankTok < t.n && (!hcmd::ParseInt(t.tok[bankTok], &bank) || bank < 1 || bank > 3)) {
		return Fail(c, "text: bank is 1, 2 or 3");
	}
	const auto b = static_cast<D2RL::DataTables::Bank>(bank);
	const char* ref = t.tok[tableTok + 1];
	*row = {};
	row->structSize = D2RL::DataTables::RowViewSize;
	D2RL::DataTables::Result r = D2RL::DataTables::Result::NotFound;
	long long n = 0;
	if (std::strncmp(ref, "code:", 5) == 0) {
		char cc[4] = {' ', ' ', ' ', ' '};  // codes are padded with spaces
		for (int i = 0; i < 4 && ref[5 + i] != '\0'; ++i) {
			cc[i] = ref[5 + i];
		}
		r = svc->findRowByCode(g_textContext, b, table, D2RL::DataTables::MakeFourCC(cc[0], cc[1], cc[2], cc[3]), row);
	} else if (std::strncmp(ref, "id:", 3) == 0 && hcmd::ParseInt(ref + 3, &n)) {
		r = svc->findRowById(g_textContext, b, table, static_cast<uint32_t>(n), row);
	} else if (hcmd::ParseInt(ref, &n) && n >= 0) {
		r = svc->getRow(g_textContext, b, table, static_cast<uint32_t>(n), row);
	} else {
		return Fail(c, "text: row is <index>, code:<abcd> or id:<n>");
	}
	if (r != D2RL::DataTables::Result::Success || row->row == nullptr) {
		return Fail(c, "text: %.20s %.20s bank %lld: row lookup result %u", t.tok[tableTok], ref, bank, static_cast<unsigned>(r));
	}
	return true;
}

// `text id <n>` | `text key <full key>` | `text row <table> <index|code:abcd|id:n> <offset hex> [bank 1-3]` |
// `text cstr <table> <row> <offset hex> [bank]`: a cell kept as characters in the row,
// `text scan <table> <row> [bank]`: the resolved text of a string id (the client's own lookup), of a loader key (`d2r:Key`,
// `medianxl:Key`: the Localization service), of the u16 string reference at a byte offset of a compiled table row, or every
// row field that resolves (to find the offset of a name field).
auto CmdText(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const auto lookup = Fn<StringFn>(RvaStringThunk);
	char text[256];
	if (t.n >= 3 && hcmd::LowerEq(t.tok[1], "id")) {
		long long id = 0;
		if (!hcmd::ParseInt(t.tok[2], &id) || id < 0 || id > 0xffff) {
			return Fail(c, "text id: a string id 0..65535");
		}
		char head[64];
		std::snprintf(head, sizeof(head), "text id %lld", id);
		PrintText(head, lookup(static_cast<uint32_t>(id)));
		return true;
	}
	if (t.n >= 3 && hcmd::LowerEq(t.tok[1], "key")) {
		const D2RL::LocalizationService* svc = nullptr;
		if (g_textContext == nullptr || g_textContext->QueryService(&svc) != D2RL::ServiceQueryResult::Success || svc == nullptr ||
		    !D2RL::HasLocalizationServiceField(svc, sizeof(D2RL::LocalizationService))) {
			return Fail(c, "text key: no localization service");
		}
		static char raw[4096];
		raw[0] = '\0';
		uint32_t need = 0;
		char key[160];  // a harness argument has no spaces: `^` stands for one
		std::snprintf(key, sizeof(key), "%s", t.tok[2]);
		for (char* k = key; *k != '\0'; ++k) {
			if (*k == '^') {
				*k = ' ';
			}
		}
		const auto r = svc->getStringByKey(g_textContext, key, raw, sizeof(raw), &need);
		char head[200];
		std::snprintf(head, sizeof(head), "text key %.100s result=%u", key, static_cast<unsigned>(r));
		PrintText(head, raw);
		return r == D2RL::Localization::Result::Success;
	}
	if (t.n >= 5 && hcmd::LowerEq(t.tok[1], "row")) {
		char* end = nullptr;
		const unsigned long long off = std::strtoull(t.tok[4], &end, 16);
		if (end == t.tok[4] || *end != '\0') {
			return Fail(c, "text row: offset in hex");
		}
		D2RL::DataTables::RowView row;
		if (!FindTextRow(c, t, 2, 5, &row)) {
			return false;
		}
		if (off + 2 > row.rowSize || (off & 1) != 0) {
			return Fail(c, "text row: offset 0x%llx outside the %u byte row", off, row.rowSize);
		}
		const uint16_t id = d2r::At<uint16_t>(row.row, static_cast<int>(off));
		char head[96];
		std::snprintf(head, sizeof(head), "text row %.20s %.20s +0x%llx id=%u", t.tok[2], t.tok[3], off, static_cast<unsigned>(id));
		PrintText(head, lookup(id));
		return true;
	}
	if (t.n >= 5 && hcmd::LowerEq(t.tok[1], "cstr")) {  // a localization cell kept as characters in the row (Levels: LevelName)
		char* end = nullptr;
		const unsigned long long off = std::strtoull(t.tok[4], &end, 16);
		if (end == t.tok[4] || *end != '\0') {
			return Fail(c, "text cstr: offset in hex");
		}
		D2RL::DataTables::RowView row;
		if (!FindTextRow(c, t, 2, 5, &row)) {
			return false;
		}
		if (off >= row.rowSize) {
			return Fail(c, "text cstr: offset 0x%llx outside the %u byte row", off, row.rowSize);
		}
		const auto* bytes = static_cast<const char*>(row.row);
		char cell[80] = "";
		for (size_t i = 0; i + 1 < sizeof(cell) && off + i < row.rowSize && bytes[off + i] != '\0'; ++i) {
			cell[i] = bytes[off + i];
		}
		Out("text cstr %.20s %.20s +0x%llx = [%s]", t.tok[2], t.tok[3], off, cell);
		return true;
	}
	if (t.n >= 4 && hcmd::LowerEq(t.tok[1], "scan")) {
		D2RL::DataTables::RowView row;
		if (!FindTextRow(c, t, 2, 4, &row)) {
			return false;
		}
		Out("text scan %s %s size 0x%x index %u", t.tok[2], t.tok[3], row.rowSize, row.rowIndex);
		int shown = 0;
		for (uint32_t o = 0; o + 2 <= row.rowSize && shown < 200; o += 2) {
			const uint16_t id = d2r::At<uint16_t>(row.row, static_cast<int>(o));
			if (id < 256 || id == 0xffff) {
				continue;
			}
			CleanText(lookup(id), text, sizeof(text));
			if (text[0] != '\0') {
				Out("  +0x%x id=%u [%.90s]", o, static_cast<unsigned>(id), text);
				++shown;
			}
		}
		// printable text kept in the row itself (a key stored as characters rather than as a string reference)
		const auto* bytes = static_cast<const uint8_t*>(row.row);
		for (uint32_t o = 0; o < row.rowSize;) {
			uint32_t e = o;
			while (e < row.rowSize && bytes[e] >= 0x20 && bytes[e] < 0x7f) {
				++e;
			}
			if (e - o >= 4 && e < row.rowSize && bytes[e] == 0) {
				Out("  +0x%x text [%.60s]", o, reinterpret_cast<const char*>(bytes + o));
				o = e + 1;
			} else {
				o = e + 1;
			}
		}
		return true;
	}
	return Fail(c, "usage: text id <n> | key <full key> | row <table> <index|code:abcd|id:n> <offset hex> [bank] | cstr <table> <row> <offset hex> [bank] | scan <table> <row> [bank]");
}

// `evtrace on|off|clear|dump [slot name] [n]`: logs D2RLoader's unit-event entry points (register / unregister / has / clear /
// dispatch / registerFn) with their arguments and return addresses, to find who registers an item's events.
auto CmdEvTrace(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	if (t.n < 2) {
		return Fail(c, "usage: evtrace on|off|clear|dump [register|unregister|has|clear|dispatch|registerFn|all] [n]");
	}
	if (hcmd::LowerEq(t.tok[1], "on")) {
		if (!item_events::TraceStart(g_base)) {
			return Fail(c, "evtrace: the thunk slots are not readable");
		}
	} else if (hcmd::LowerEq(t.tok[1], "off")) {
		item_events::TraceStop();
	} else if (hcmd::LowerEq(t.tok[1], "clear")) {
		item_events::TraceClear();
	} else if (hcmd::LowerEq(t.tok[1], "watch")) {
		// `evtrace watch <slot 0-3> player|m<id>|<item id>|abs <hex address> <offset hex> [len]`: hardware write watch
		if (t.n < 5) {
			return Fail(c, "usage: evtrace watch <slot 0-3> player|m<monster id>|i<item id>|abs <offset or address hex> [len]");
		}
		long long slot = 0, len = 8;
		if (!hcmd::ParseInt(t.tok[2], &slot)) {
			return Fail(c, "evtrace watch: slot must be a number");
		}
		Unit* unit = nullptr;
		long long id = 0;
		const char* who = t.tok[3];
		bool absolute = hcmd::LowerEq(who, "abs");
		if (hcmd::LowerEq(who, "player")) {
			unit = c->player;
		} else if ((who[0] == 'm' || who[0] == 'M') && hcmd::ParseInt(who + 1, &id)) {
			unit = FindMonsterById(c, static_cast<uint32_t>(id));
		} else if ((who[0] == 'i' || who[0] == 'I') && hcmd::ParseInt(who + 1, &id)) {
			EachItem(c, [&](Unit* it) {
				if (unit == nullptr && IdOf(it) == static_cast<uint32_t>(id)) {
					unit = it;
				}
			});
		}
		if (unit == nullptr && !absolute) {
			return Fail(c, "evtrace watch: no such unit");
		}
		const unsigned long long off = std::strtoull(t.tok[4], nullptr, 16);
		if (t.n > 5) {
			hcmd::ParseInt(t.tok[5], &len);
		}
		const uint64_t addr = absolute ? off : reinterpret_cast<uint64_t>(unit) + off;
		if (!item_events::WatchSet(static_cast<int>(slot), addr, static_cast<int>(len), g_base)) {
			return Fail(c, "evtrace watch: could not set the breakpoint");
		}
		Out("watching %llx (%lld bytes) in slot %lld", static_cast<unsigned long long>(addr), len, slot);
	} else if (hcmd::LowerEq(t.tok[1], "rec")) {
		// `evtrace rec <stat id> [watch <slot>]`: the itemstatcost record (stride 0x144 in the array at manager + 0x1258), its event words,
		// and optionally a read/write breakpoint on the function word (+0x48)
		long long statId = 0, slot = -1;
		if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &statId)) {
			return Fail(c, "usage: evtrace rec <stat id> [<slot 0-3>]");
		}
		if (t.n > 3) {
			hcmd::ParseInt(t.tok[3], &slot);
		}
		const uint8_t* rec = nullptr;
		for (int idx = 0; idx < 4 && rec == nullptr; ++idx) {  // 0x300a90(idx) returns the pointer at exe + 0x2a9a580 + 16 * idx
			const uint8_t* mgr = *reinterpret_cast<const uint8_t* const*>(g_base + 0x2a9a580 + idx * 16);
			const uint8_t* arr = mgr != nullptr ? d2r::At<const uint8_t*>(mgr, 0x1258) : nullptr;
			const uint8_t* cand = arr != nullptr ? arr + statId * 0x144 : nullptr;
			Out("mgr[%d]=%llx arr=%llx", idx, static_cast<unsigned long long>(reinterpret_cast<uint64_t>(mgr)), static_cast<unsigned long long>(reinterpret_cast<uint64_t>(arr)));
			if (cand != nullptr && !IsBadReadPtr(cand, 0x144)) {
				rec = cand;
			}
		}
		if (rec == nullptr) {
			return Fail(c, "evtrace rec: no record array");
		}
		Out("rec %lld at %llx: event1 %d event2 %d func1 %d func2 %d", statId, static_cast<unsigned long long>(reinterpret_cast<uint64_t>(rec)),
		    d2r::At<int16_t>(rec, 0x44), d2r::At<int16_t>(rec, 0x46), d2r::At<int16_t>(rec, 0x48), d2r::At<int16_t>(rec, 0x4a));
		if (slot >= 0) {
			Out("%s", item_events::WatchSet(static_cast<int>(slot), reinterpret_cast<uint64_t>(rec) + 0x48, 4, g_base, true) ? "read watch set" : "watch failed");
		}
	} else if (hcmd::LowerEq(t.tok[1], "peek")) {
		// `evtrace peek <hex address> [n qwords]`: raw read, for D2RCore's tables
		long long n = 4;
		if (t.n < 3) {
			return Fail(c, "usage: evtrace peek <hex address> [n]");
		}
		if (t.n > 3) {
			hcmd::ParseInt(t.tok[3], &n);
		}
		const auto* p = reinterpret_cast<const uint64_t*>(std::strtoull(t.tok[2], nullptr, 16));
		if (n < 1 || n > 64 || IsBadReadPtr(p, static_cast<UINT_PTR>(n) * 8)) {
			return Fail(c, "evtrace peek: unreadable");
		}
		for (long long i = 0; i < n; ++i) {
			Out("%llx: %llx", static_cast<unsigned long long>(reinterpret_cast<uint64_t>(p + i)), static_cast<unsigned long long>(p[i]));
		}
	} else if (hcmd::LowerEq(t.tok[1], "fire")) {
		// `evtrace fire <event id> player|m<id> player|m<id>|none`: calls the dispatch wrapper 0x44d570(game, event, unit, other, 0)
		// the way the damage and kill code do, e.g. event 9 (kill) on the player with a monster
		long long ev = 0;
		auto unitOf = [&](const char* s) -> Unit* {
			long long id = 0;
			if (hcmd::LowerEq(s, "player")) {
				return c->player;
			}
			if ((s[0] == 'm' || s[0] == 'M') && hcmd::ParseInt(s + 1, &id)) {
				return FindMonsterById(c, static_cast<uint32_t>(id));
			}
			return nullptr;
		};
		if (t.n < 5 || !hcmd::ParseInt(t.tok[2], &ev)) {
			return Fail(c, "usage: evtrace fire <event id> player|m<id> player|m<id>|none");
		}
		Unit* a = unitOf(t.tok[3]);
		Unit* b = unitOf(t.tok[4]);
		if (a == nullptr || (b == nullptr && !hcmd::LowerEq(t.tok[4], "none"))) {
			return Fail(c, "evtrace fire: no such unit");
		}
		Fn<void (*)(void*, int, Unit*, Unit*, void*)>(0x44d570)(c->game, static_cast<int>(ev), a, b, nullptr);
		Out("fired event %lld", ev);
	} else if (hcmd::LowerEq(t.tok[1], "calls")) {
		// calls seen by the replaced D2RCore handlers 33 / 34 and the arguments of the last 33
		long heal = 0, cast = 0;
		uint64_t a[14] = {};
		item_events::Counters(&heal, &cast, a);
		Out("handler 33 calls %ld (returned %llx), handler 34 calls %ld (returned %llx)", heal, static_cast<unsigned long long>(a[9]), cast, static_cast<unsigned long long>(a[10]));
		Out("last cast on kill: skill %lld level %lld warp %lld", static_cast<long long>(a[11]), static_cast<long long>(a[12]), static_cast<long long>(a[13]));
		Out("last 33: game %llx event %lld unit %llx other %llx arg5 %llx code %llx a7 %llx a8 %llx a9 %llx", static_cast<unsigned long long>(a[0]),
		    static_cast<long long>(a[1]), static_cast<unsigned long long>(a[2]), static_cast<unsigned long long>(a[3]), static_cast<unsigned long long>(a[4]),
		    static_cast<unsigned long long>(a[5]), static_cast<unsigned long long>(a[6]), static_cast<unsigned long long>(a[7]), static_cast<unsigned long long>(a[8]));
	} else if (hcmd::LowerEq(t.tok[1], "wtest")) {
		Out("write watch self test: %s", item_events::WatchSelfTest() ? "hit" : "NO hit");
	} else if (hcmd::LowerEq(t.tok[1], "wclear")) {
		item_events::WatchClear();
	} else if (hcmd::LowerEq(t.tok[1], "wdump")) {
		item_events::WatchDump([](const char* line) { Out("%s", line); });
	} else if (hcmd::LowerEq(t.tok[1], "list")) {
		// the unit's event list (unit + 0xe0, 0x40-byte nodes in D2RCore's registry, next at +0x38): `evtrace list [player|m<id>]`
		Unit* unit = c->player;
		long long id = 0;
		if (t.n >= 3 && (t.tok[2][0] == 'm' || t.tok[2][0] == 'M') && hcmd::ParseInt(t.tok[2] + 1, &id)) {
			unit = FindMonsterById(c, static_cast<uint32_t>(id));
		}
		if (unit == nullptr) {
			return Fail(c, "evtrace list: no such unit");
		}
		int n = 0;
		for (const uint8_t* node = d2r::At<const uint8_t*>(unit, 0xe0); node != nullptr && n < 80; node = d2r::At<const uint8_t*>(node, 0x38), ++n) {
			const uint64_t* q = reinterpret_cast<const uint64_t*>(node);
			const uint64_t handler = q[5];
			Out("node %d: %02x %02x %04x | +4 %08x +8 %llx +10 %llx +18 %08x %08x +20 %08x %08x handler %llx (%s)", n, node[0], node[1],
			    d2r::At<uint16_t>(node, 2), d2r::At<uint32_t>(node, 4), static_cast<unsigned long long>(q[1]), static_cast<unsigned long long>(q[2]),
			    d2r::At<uint32_t>(node, 0x18), d2r::At<uint32_t>(node, 0x1c), d2r::At<uint32_t>(node, 0x20), d2r::At<uint32_t>(node, 0x24),
			    static_cast<unsigned long long>(handler),
			    handler >= g_base && handler < g_base + 0x4000000 ? "exe" : "other");
		}
		Out("events: %d nodes", n);
	} else if (hcmd::LowerEq(t.tok[1], "dump")) {
		static const char* const names[] = {"register", "unregister", "has", "clear", "dispatch", "registerFn"};
		int slot = -1;
		long long n = 40;
		for (int i = 2; i < t.n; ++i) {
			long long v = 0;
			if (hcmd::ParseInt(t.tok[i], &v)) {
				n = v;
				continue;
			}
			for (int k = 0; k < 6; ++k) {
				if (hcmd::LowerEq(t.tok[i], names[k])) {
					slot = k;
				}
			}
		}
		item_events::TraceDump(slot, static_cast<int>(n), [](const char* line) { Out("%s", line); });
	} else {
		return Fail(c, "evtrace: on, off, clear or dump");
	}
	return true;
}

// Client side (UI thread): the automap (layers, cells, the debug reveal flag) and the travel counters (waypoint auto-activation,
// hotkeys, map reveal). `mapcells` is what the mapreveal check compares before and after a reveal.
auto CmdMapCells(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	uint64_t cells = 0, current = 0;
	int layer = -1, flag = 0, layers = 0;
	if (!TravelAutomap(&cells, &layer, &flag, &layers, &current)) {
		return Fail(c, "mapcells: not available (no game yet)");
	}
	Out("mapcells cells=%llu layer=%d layers=%d debugflag=%d current=%llu", static_cast<unsigned long long>(cells), layer, layers, flag,
	    static_cast<unsigned long long>(current));
	return true;
}

// Client side (UI thread): `hotkey pickup|reveal|transmute` is one press of the plugin's own hotkey action (the InputService callback's
// code), without a key: a background run may not press keys. The result is in `travel` (counters) as for a real press.
auto CmdHotkey(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	int which = -1;
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "pickup")) {
		which = 0;
	} else if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "reveal")) {
		which = 1;
	} else if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "transmute")) {
		which = 2;
	}
	if (which < 0) {
		return Fail(c, "usage: hotkey pickup|reveal|transmute");
	}
	if (!TravelPressAction(which)) {
		return Fail(c, "hotkey: not available (travel part not installed)");
	}
	Out("hotkey %s pressed", t.tok[1]);
	return true;
}

auto CmdTravel(Ctx*, const hcmd::Tokens&) noexcept -> bool {
	char text[960];
	TravelHotkeyReport(text, sizeof(text));
	Out("travel %s", text);
	char msgs[900];
	TravelUiMessages("Panel", msgs, sizeof(msgs));
	Out("uimsgs %s", msgs);
	return true;
}

// stashprobe <page>: create a rune in shared stash tab <page> on the game thread, then delete it; stashprobe result: what happened.
auto CmdStashProbe(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	char text[200];
	if (t.n >= 2 && hcmd::LowerEq(t.tok[1], "result")) {
		const int rc = TravelStashResult(text, sizeof(text));
		Out("stashprobe result %d %s", rc, text);
		return true;
	}
	long long page = 0;
	if (t.n < 2 || !hcmd::ParseInt(t.tok[1], &page) || page < 0 || page > 998) {
		return Fail(c, "usage: stashprobe <tab 0..998> | stashprobe result");
	}
	if (TravelStashProbe(static_cast<int>(page), text, sizeof(text)) == 0) {
		return Fail(c, text);
	}
	Out("stashprobe tab %lld %s", page, text);
	return true;
}

// stashpage (client side): state | open | close | toggle | msgs | uia <target> <command> [text] | widget <panel> [child] |
// vis <panel> <child> 0|1 | put <code> [x y] | fill <1|2> | list | move <runtime id> <1|2> [x y] | result
// (put / fill / list / move queue work on the game thread; `stashpage result` has the answer).
auto CmdStashPage(Ctx* c, const hcmd::Tokens& t) noexcept -> bool {
	const char* usage = "usage: stashpage state|open|close|toggle|msgs|uia <target> <command> [text]|widget <panel> [child]|vis <panel> <child> <0|1>|put <code> [x y]|fill <1|2>|drop <code>|list|move <id> <1|2> [x y]|result";
	char text[1000];
	if (t.n < 2) {
		return Fail(c, usage);
	}
	const char* verb = t.tok[1];
	if (hcmd::LowerEq(verb, "state")) {
		char status[300];
		StashPagesStatus(status, sizeof(status));
		Out("stashpage state=%d %s", StashPageState(), status);
		return true;
	}
	if (hcmd::LowerEq(verb, "open") || hcmd::LowerEq(verb, "close") || hcmd::LowerEq(verb, "toggle")) {
		const int mode = hcmd::LowerEq(verb, "close") ? 0 : hcmd::LowerEq(verb, "open") ? 1 : 2;
		Out("stashpage %s %s", verb, StashPageOpen(mode) == 0 ? "queued" : "unavailable");
		return true;
	}
	if (hcmd::LowerEq(verb, "msgs")) {
		StashPageMessages(text, sizeof(text));
		Out("stashpage msgs %s", text);
		return true;
	}
	if (hcmd::LowerEq(verb, "uia")) {
		if (t.n < 4) {
			return Fail(c, usage);
		}
		Out("stashpage uia %s:%s(%s) = %d", t.tok[2], t.tok[3], t.n >= 5 ? t.tok[4] : "", StashPageUiAction(t.tok[2], t.tok[3], t.n >= 5 ? t.tok[4] : ""));
		return true;
	}
	if (hcmd::LowerEq(verb, "widget")) {
		if (t.n < 3) {
			return Fail(c, usage);
		}
		StashPageWidget(t.tok[2], t.n >= 4 ? t.tok[3] : "", text, sizeof(text));
		Out("stashpage widget %s", text);
		return true;
	}
	if (hcmd::LowerEq(verb, "vis")) {
		long long on = 0;
		if (t.n < 5 || !hcmd::ParseInt(t.tok[4], &on)) {
			return Fail(c, usage);
		}
		Out("stashpage vis %s/%s=%lld result %d", t.tok[2], t.tok[3], on, StashPageSetVisible(t.tok[2], t.tok[3], on != 0));
		return true;
	}
	if (hcmd::LowerEq(verb, "result")) {
		const int rc = StashPageResult(text, sizeof(text));
		Out("stashpage result %d %s", rc, text);
		return true;
	}
	long long a = 0, b = -1, d = -1;
	int queued = 0;
	if (hcmd::LowerEq(verb, "put")) {
		if (t.n < 3) {
			return Fail(c, usage);
		}
		if (t.n >= 5) {
			hcmd::ParseInt(t.tok[3], &b);
			hcmd::ParseInt(t.tok[4], &d);
		}
		queued = StashPageJob("put", b, d, 0, t.tok[2], text, sizeof(text));
	} else if (hcmd::LowerEq(verb, "fill")) {
		if (t.n < 3 || !hcmd::ParseInt(t.tok[2], &a)) {
			return Fail(c, usage);
		}
		queued = StashPageJob("fill", a, 0, 0, "", text, sizeof(text));
	} else if (hcmd::LowerEq(verb, "list")) {
		queued = StashPageJob("list", 0, 0, 0, "", text, sizeof(text));
	} else if (hcmd::LowerEq(verb, "drop")) {
		if (t.n < 3) {
			return Fail(c, usage);
		}
		queued = StashPageJob("drop", 0, 0, 0, t.tok[2], text, sizeof(text));
	} else if (hcmd::LowerEq(verb, "move")) {
		long long page = 0;
		if (t.n < 4 || !hcmd::ParseInt(t.tok[2], &a) || !hcmd::ParseInt(t.tok[3], &page)) {
			return Fail(c, usage);
		}
		if (t.n >= 6 && hcmd::ParseInt(t.tok[4], &b) && hcmd::ParseInt(t.tok[5], &d)) {
			queued = StashPageJob("move", a, page, (d << 8) | (b & 0xff), "", text, sizeof(text));
		} else {
			queued = StashPageJob("move", a, page, -1, "", text, sizeof(text));
		}
	} else {
		return Fail(c, usage);
	}
	if (queued == 0) {
		return Fail(c, text);
	}
	Out("stashpage %s %s", verb, text);
	return true;
}

// wpobj: every waypoint object of the game with its position and its distance to the player (the wpauto check walks to one).
auto CmdWpObj(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	int32_t px = 0, py = 0;
	PlayerPos(c, &px, &py);
	void* room = Fn<UnitRoomFn>(RvaUnitRoom)(c->player);
	const int32_t level = room != nullptr ? Fn<RoomLevelFn>(RvaRoomLevel)(room) : -1;
	int found = 0;
	EachUnit(c->game, HashObjects, [&](Unit* u) {
		if (TypeOf(u) != 2 || !travel::IsWaypointObject(ClassOf(u))) {
			return;
		}
		int32_t ox = 0, oy = 0;
		d2r::UnitXY(u, &ox, &oy);
		void* oroom = Fn<UnitRoomFn>(RvaUnitRoom)(u);
		++found;
		Out("wpobj id=%u class=%d at %d,%d dist=%.0f level=%d inrange=%d", IdOf(u), ClassOf(u), ox, oy, DistTo(c->player, u),
		    oroom != nullptr ? Fn<RoomLevelFn>(RvaRoomLevel)(oroom) : -1, travel::InPickupRange(px, py, ox, oy) ? 1 : 0);
	});
	Out("wpobj player at %d,%d level=%d number=%d objects=%d", px, py, level, travel::WaypointNumberOfLevel(level), found);
	return true;
}

// Client side (UI thread): the map reveal the R hotkey runs, without the key.
auto CmdReveal(Ctx* c, const hcmd::Tokens&) noexcept -> bool {
	const int rc = TravelRevealNow();
	if (rc < 0) {
		return Fail(c, "reveal: not available (off, or no local player)");
	}
	Out("reveal done");
	return true;
}

using VerbFn = bool (*)(Ctx*, const hcmd::Tokens&) noexcept;
struct Verb {
	const char* name;
	VerbFn fn;
	bool clientSide;
};
const Verb Verbs[] = {
    {"state", CmdState, false},   {"quest", CmdQuest, false}, {"flag", CmdFlag, false}, {"gameflag", CmdGameFlag, false},    {"gold", CmdGold, false}, {"waypoint", CmdWaypoint, false},
    {"stat", CmdStat, false}, {"town", CmdTown, false},     {"level", CmdLevel, false}, {"spawn", CmdSpawn, false},   {"kill", CmdKill, false}, {"xp", CmdXp, false},
    {"interact", CmdInteract, false}, {"msg", CmdMsg, false}, {"pkt", CmdPkt, false}, {"enter", CmdEnter, false}, {"missile", CmdMissile, false}, {"missilescan", CmdMissileScan, false}, {"packclear", CmdPackclear, false},{"cubeclear", CmdCubeclear, false},{"cuberec", CmdCuberec, false},{"difficulty", CmdDifficulty, false},{"lockcheck", CmdLockcheck, false},{"towerprobe", CmdTowerprobe, false},{"tile", CmdTile, false},{"sysmsg", CmdSysmsg, false},{"class", CmdClass, false},{"remove", CmdRemove, false},{"item", CmdItem, false}, {"cubecraft", CmdCubecraft, false}, {"use", CmdUse, false}, {"cubeslots", CmdCubeSlots, false}, {"cubeout", CmdCubeOut, false},
    {"equip", CmdEquip, false}, {"unequip", CmdUnequip, false}, {"move", CmdMove, false}, {"moveto", CmdMoveTo, false},
    {"skill", CmdSkill, false}, {"skills", CmdSkills, false}, {"skilldmg", CmdSkillDmg, false},  {"setskill", CmdSetSkill, false}, {"cast", CmdCast, false}, {"mcast", CmdMonsterCast, false}, {"missiles", CmdMissiles, false}, {"collide", CmdCollide, false}, {"collidetable", CmdCollideTable, false}, {"wallscan", CmdWallScan, false}, {"hasstate", CmdHasState, false}, {"passivestate", CmdPassiveState, false}, {"passivetrace", CmdPassiveTrace, false}, {"startfn", CmdStartFn, false}, {"startstats", CmdStartStats, false},
    {"hit", CmdHit, false}, {"weaponhit", CmdWeaponHit, false}, {"passiverefresh", CmdPassiveRefresh, false}, {"avoid", CmdAvoid, false}, {"itemroll", CmdItemRoll, false}, {"colour", CmdColour, false}, {"req", CmdReq, false}, {"wear", CmdWear, false}, {"rewardstep", CmdRewardStep, false}, {"setstate", CmdSetState, false}, {"iflags", CmdItemFlags, false}, {"cursor", CmdCursor, false}, {"manamin", CmdManaMin, false}, {"manacharge", CmdManaCharge, false},
    {"cstat", CmdClientStat, true}, {"cltdo", CmdCltDo, true}, {"cltst", CmdCltSt, true}, {"skillstats", CmdSkillStats, false}, {"asserttrace", CmdAssertTrace, false}, {"panelrow", CmdPanelRow, false}, {"tip", CmdTip, true}, {"tiplog", CmdTipLog, true}, {"tipfmt", CmdTipFmt, true},
    {"hit", CmdHit, false}, {"weaponhit", CmdWeaponHit, false}, {"passiverefresh", CmdPassiveRefresh, false}, {"avoid", CmdAvoid, false}, {"itemroll", CmdItemRoll, false}, {"colour", CmdColour, false}, {"req", CmdReq, false}, {"wear", CmdWear, false}, {"rewardstep", CmdRewardStep, false}, {"setstate", CmdSetState, false}, {"iflags", CmdItemFlags, false}, {"itemdesc", CmdItemDesc, false}, {"cursor", CmdCursor, false}, {"manamin", CmdManaMin, false}, {"manacharge", CmdManaCharge, false},
    {"cstat", CmdClientStat, true}, {"panelrow", CmdPanelRow, false},
    {"skilltab", CmdSkillTab, true}, {"strids", CmdStrIds, true}, {"str", CmdStr, true}, {"hover", CmdHover, true}, {"automap", CmdAutomap, true}, {"shop", CmdShop, false}, {"gamble", CmdGamble, false}, {"gaps", CmdGaps, false}, {"levelact", CmdLevelAct, false},
    {"dump", CmdDump, false}, {"evtrace", CmdEvTrace, false}, {"merc", CmdMerc, false}, {"mercreq", CmdMercReq, false}, {"mercprice", CmdMercPrice, false}, {"players", CmdPlayers, false}, {"tctrace", CmdTcTrace, false}, {"leash", CmdLeash, false}, {"a5done", CmdA5Done, false}, {"countessreward", CmdCountessReward, false}, {"questobj", CmdQuestObj, false}, {"questreg", CmdQuestReg, false}, {"objects", CmdObjects, false}, {"object", CmdObject, false}, {"operate", CmdOperate, false}, {"objmode", CmdObjMode, false}, {"portal", CmdPortal, false},{"hellforgereward", CmdHellforgeReward, false}, {"prisonreward", CmdPrisonReward, false}, {"hire", CmdHire, false}, {"help", CmdHelp, true},     {"menu", CmdMenu, true}, {"mstr", CmdMstr, true}, {"text", CmdText, true}, {"mapmem", CmdMapMem, true}, {"goblinsay", CmdGoblinSay, false}, {"rewardmsg", CmdRewardMsg, false}, {"rewardsnd", CmdRewardSound, true}, {"infopanel", CmdInfoPanel, true}, {"bufficons", CmdBuffIcons, true}, {"statorder", CmdStatOrder, true},
    {"mapcells", CmdMapCells, true}, {"reveal", CmdReveal, true}, {"hotkey", CmdHotkey, true}, {"wpobj", CmdWpObj, false}, {"travel", CmdTravel, true}, {"stashprobe", CmdStashProbe, true},
    {"stashpage", CmdStashPage, true}, {"ccorpses", CmdClientCorpses, true}, {"afford", CmdAfford, false}, {"transguard", CmdTransGuard, false}, {"renderpool", CmdRenderPool, false}, {"hc", CmdHardcore, false}, {"tpgold", CmdTeleportGold, false}, {"modewatch", CmdModeWatch, false}, {"peek", CmdPeek, false},
};

const Verb* FindVerb(const char* name) noexcept {
	for (const Verb& v : Verbs) {
		if (hcmd::LowerEq(name, v.name)) {
			return &v;
		}
	}
	return nullptr;
}

// SEH wrapper: a bad pointer in a game call must not take the whole game down.
auto RunVerb(const Verb* verb, Ctx* c, const hcmd::Tokens& t) noexcept -> int {
	__try {
		return verb->fn(c, t) ? 1 : 0;
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		return -2;
	}
}

void Finish(Ctx* c, int rc) noexcept {
	if (rc == 1) {
		Out("%s OK", c->verb);
	} else if (rc == -2) {
		Out("%s FAIL crashed (exception %s)", c->verb, c->why[0] != '\0' ? c->why : "in the game call");
	} else {
		Out("%s FAIL %s", c->verb, c->why[0] != '\0' ? c->why : "failed");
	}
}

// One queued server-side command (single slot: the mailbox runs one command at a time).
struct Job {
	hcmd::Tokens tokens;
	const Verb* verb = nullptr;
	volatile LONG state = 0;  // 0 idle, 1 queued, 2 running, 3 done
	int rc = 0;
	Ctx ctx;
};
Job g_job;

}  // namespace

void HarnessCmdsContext(const D2RL::PluginContext* context) noexcept {
	g_textContext = context;
}

void HarnessCmdsInit(uint64_t exeBase) noexcept {
	g_base = exeBase;
	InterlockedExchange(&g_ready, 1);
}

// Game thread, after the server frame.
void HarnessGameFrame(void* gamePtr) noexcept {
	InterlockedIncrement(&g_frames);
	g_lastGame = gamePtr != nullptr;
	if (g_ready != 0 && g_manaWatch != nullptr && gamePtr != nullptr) {
		__try {
			TrackMana();
		} __except (EXCEPTION_EXECUTE_HANDLER) {
			g_manaWatch = nullptr;
		}
	}
	if (g_ready != 0 && g_trackMissiles != 0 && gamePtr != nullptr) {
		__try {
			TrackMissiles(static_cast<Game*>(gamePtr));
		} __except (EXCEPTION_EXECUTE_HANDLER) {
			InterlockedExchange(&g_trackMissiles, 0);
		}
	}
	if (g_ready == 0 || g_job.state != 1 || gamePtr == nullptr) {
		return;
	}
	if (InterlockedCompareExchange(&g_job.state, 2, 1) != 1) {
		return;
	}
	Game* game = static_cast<Game*>(gamePtr);
	Ctx& c = g_job.ctx;
	c = Ctx();
	std::snprintf(c.verb, sizeof(c.verb), "%s", g_job.verb->name);
	c.game = game;
	c.dataFlag = d2r::At<uint8_t>(game, d2r::GameDataFlag);
	c.player = FindPlayer(game);
	if (c.player != nullptr) {
		InterlockedExchange(&g_playerId, static_cast<LONG>(IdOf(c.player)));
	}
	if (c.player == nullptr) {
		g_job.rc = 0;
		std::snprintf(c.why, sizeof(c.why), "no player in the game yet");
	} else {
		g_job.rc = RunVerb(g_job.verb, &c, g_job.tokens);
	}
	Finish(&c, g_job.rc);
	InterlockedExchange(&g_job.state, 3);
}

// UI thread (testharness.cpp ServiceCommands): "h <verb> ...". Returns 1 handled and OK, 0 failed, -2 crashed, -3 timed out.
auto HarnessCommand(const char* line) noexcept -> int {
	if (g_ready == 0) {
		return 0;
	}
	hcmd::Tokens all;
	hcmd::Split(line, &all);
	if (all.n < 2) {
		Out("usage: h <verb> ...   (h help)");
		return 0;
	}
	hcmd::Tokens t;  // the same tokens without the leading "h": t.tok[0] is the verb
	t.n = all.n - 1;
	for (int i = 0; i < t.n; ++i) {
		t.tok[i] = all.tok[i + 1];
	}
	const Verb* verb = FindVerb(t.tok[0]);
	if (verb == nullptr) {
		Out("%s FAIL unknown verb (h help)", t.tok[0]);
		return 0;
	}
	if (verb->clientSide) {
		Ctx c;
		std::snprintf(c.verb, sizeof(c.verb), "%s", verb->name);
		c.dataFlag = 2;
		const int rc = RunVerb(verb, &c, t);
		Finish(&c, rc);
		return rc;
	}
	if (InterlockedCompareExchange(&g_job.state, 0, 1) == 1 || g_job.state == 3) {  // a never-run or finished job is replaced
		InterlockedExchange(&g_job.state, 0);
	}
	if (g_job.state != 0) {
		Out("%s FAIL previous command still running", verb->name);
		return 0;
	}
	g_job.verb = verb;
	std::memcpy(g_job.tokens.text, all.text, sizeof(all.text));  // the job keeps its own copy of the line
	g_job.tokens.n = t.n;
	for (int i = 0; i < t.n; ++i) {
		g_job.tokens.tok[i] = g_job.tokens.text + (t.tok[i] - all.text);
	}
	g_job.rc = 0;
	// Queued, not waited for: the server frames are driven from this (UI) thread's loop, so blocking here would starve
	// the very frame that runs the job. The game thread ends the command with an "h: <verb> OK|FAIL" line.
	InterlockedExchange(&g_job.state, 1);
	return 1;
}
