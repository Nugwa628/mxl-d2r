# D2R 3.3 build 93847: addresses fo
Item events (lane p4ev, 2026-10-22; docs/subsystems/items-xp.md section 5b):

| What | Address | Notes |
|---|---|---|
| unit-event thunks | exe `0x3e2a400` .. `0x3e2a428` | register, unregister, has, clear, dispatch, registerFn: slots into D2RCore |
| per-unit event list | `unit + 0xe0` | node `0x40` bytes: `+8` `(stat << 32) \| layer`, `+0x28` handler, `+0x38` next |
| event dispatch wrapper | exe `0x44d570` | `(game, event, unitA, unitB, arg5)`; kill = 9, thorns 2 / 3, open wounds / crushing blow 5 / 6 |
| core handler table | D2RCore `0x630260` | slot = itemeventfunc; handler `(game, event, unit, other, arg5, code64, a7, a8, a9)`; 15 `0x3d12b0`, 16 `0x3d1310` (a `jmp`), 33 `0x3d19b0` and 34 `0x3d1a20` are forwarders that return 0 |
| exe handler table | exe `0x238e5c0`, ids 1..40 | 6 `0x582b20` (thorns), 11 `0x582d30`, 12 `0x5828d0`, 15 `0x584170`, 16 `0x583150`, 20 `0x583b30` (cast), 28 `0x583a70` (life), 32 `0x42eea0`, 33 `0x42f300`, 34 `0x51f7b0`; code is `(stat << 16) \| layer` |
| itemstatcost records | `*(exe + 0x2a9a580 + 16) + 0x1258`, stride `0x144` | event words `+0x44 / +0x46`, function words `+0x48 / +0x4a` |
| unit death function | exe `0x44db20` | `(game, victim, killer or null, flag)`; returns at once for a monster in mode 0 / 12 or a player in mode 0 / 17; flag 1 takes a player's pet off the list (`0x4ffb90`); hooked by `death_event.cpp` (D2Sigma event 14 = D2R events row 18, bug #58) |
| monster owner | exe `0x4a53c0` | `(unit)` -> owner unit (monster data `+0x30` -> `+0x60/+0x68/+0x6c`), null without one; 1.13c `0x6fc41260` |r the blocked hooks (lane d2r-addresses, 2026-10-21)

All addresses are **RVAs** in the D2R image (`D2RLoader_6ab3782c_dump.exe` memory layout; file offset == RVA, base
`0x140000000`), x64 Microsoft ABI (rcx, rdx, r8, r9, then stack at `[rsp+0x20]...` at the callee's entry).
"Entry bytes" are the first 16 bytes of the function, for the plugin's expected-bytes check.

**Confidence:** *verified* = the code was read and matches the 1.13c function (same structure, constants, assert
strings, callers); *likely* = structure matches but one link rests on inference; *guess* = anchor only.

Everything here was found with `tools/d2r_find.py` (string search, RIP-relative xrefs, `.pdata` bounds, callers,
disassembly; see its docstring) plus Median's 1.13c D2Game decompile (`ghidra-lanes/addr/d2game` copy). Sections 4, 5 and 7-11 (lane
d2r-addresses-2) were read from the analysed Ghidra project (decompiles via `tools/ghidra_scripts/DecompOut.java`, `tools/ghidra_lane.ps1` for worktrees) plus
`tools/d2r_scan.py`; sections 1-3 and 6 are the earlier disassembly-only pass.

Reading aids that apply everywhere:

- `.pdata` splits big functions into pieces. `tools/d2r_find.py func X` can then report a *cold part* (e.g. `0x529d50`
  is a 0x2e-byte entry stub whose body is chained at `0x529dae`). The entry address is still the right hook address.
- Asserts show up as `D2Game\src\<Module>\<File>.cpp` strings; most of the logging strings are GUID-prefixed
  telemetry lines and are not useful anchors.
- Game object offsets seen in this lane: `game+0x104` u8 difficulty (0-2), `game+0x106` u8 expansion/dataFlag (every
  table getter takes it), `game+0x1aaa0` an object with a vtable (telemetry), `game+0x21d8` -> the game-wide quest
  list. Unit helpers: `0x34b240(unit)` = the player data (`+0x40 + difficulty*8` = that difficulty's quest record
  pointer), `0x34b440(unit)` = room, `0x2efc10(room)` = level id, `0x34a330/0x34a360/0x349860(unit, file, line)` =
  unit id / unit-data fetch / class id (the file+line are assert arguments), `0x34b9d0(unit)` = unit type
  (0 player, 1 monster, 4 item), `0x48fe80(game, type, id)` = find unit, `0x484de0(x)` = game from a unit/room.

## Summary

| # | Hook point | RVA | Confidence |
|---|---|---|---|
| 1 | Cube: execute a recipe (post-hook for craft flags + gold) | `0x5269c0` | verified |
| 1 | Cube: transmute packet handler (caller of search + execute) | `0x4f2490` | verified |
| 1 | Cube: recipe search / input match (already hooked, bytes now recorded) | `0x529090` / `0x529d50` | verified |
| 1 | Cube: output-effect dispatch (byte table; only for the "patch like Median" route) | `0x526d3c` (table `0x1d3bfc0`) | verified |
| 2 | Quest event dispatcher (per-player quest list) | `0x518ec0` | verified |
| 2 | Quest kill event wrapper (game, victim, killer) | `0x515640` | verified |
| 2 | Quest NPC-activate event wrapper | `0x515980` | verified |
| 2 | Quest NPC-message event wrapper (game, player, npc id, msg) | `0x516940` | verified |
| 2 | a1q4 (Search for Cain) event 11 handler: Akara messages (Median's Griswold's Heart hook) | `0x5e0830` | verified |
| 2 | a1q6 (Andariel) event 8 handler (kill): Median's catalyst drop | `0x5e1f00` | verified |
| 2 | a1q6 event 0 handler (NPC activate): Median's catalyst re-issue | `0x5e1d30` | verified |
| 2 | Create a quest item by 4-char code in the player's inventory | `0x517530` | likely |
| 2 | Quest bit test / set / clear (record, quest id, bit) | `0x325c50` / `0x325c00` / `0x325990` | verified / verified / likely |
| 2 | Player quest record for a game and player | `*(0x34b240(player) + game[0x104]*8 + 0x40)` | verified |
| 2 | Quest descriptor table (36 entries: init fn, act, quest id) | `0x239c5c0` (stride 0x20) | verified |
| 3 | NPC table (43 x 0x1c bytes: hire/trade/gamble flags, hire quest and level) | `0x237ea60`, getter `0x3971a0` | verified |
| 3 | Server NPC trade / gamble / hire packet handler | `0x4b0470` | verified |
| 3 | Mercenary stat setup from the hireling.txt row `(game, player, merc or null, level)`; run by hire, save load and level-up (hooked by hirelings.cpp, entry `48 8b c4 53 55 41 55 41 57 48 83 ec 58`) | `0x544f60` | verified |
| 3 | Hire packet 0x36 handler `0x4a9520` -> hire `0x53d350` (checks hire flag, quest/level gate, price) -> bind `0x544ac0`; save load of the mercenary `0x421240`; player's mercenary unit `0x4ff1a0(game, player, 7, 0)`; mercenary record by unit id `0x4ff2d0(player, id)` (hireling id at `+8`); hireling.txt row by id and level `0x3965d0(dataFlag, dataFlag != 1, id, level)` (row 0x150 bytes: `+0x1c` level, `+0x34/+0x38` strength and per level, `+0x3c/+0x40` dexterity) | see text | verified |
| 3 | NPC click packet (server; calls quest event 0) | block `0x4c26a7` of a PlrMsg handler | likely |
| 3 | NPC dialog-message packet (server; calls quest event 11) | `0x4c33e0` | likely |
| 3 | Client NPC menu module (`D2Client\src\UI\npcmenu.cpp`) | functions `0x10a520`-`0x117634` | likely (module only) |
| 4 | Warp interact packet (server) and the warp action it calls | `0x4adbb0` -> `0x491ff0` | verified (section 4, rewritten) |
| 4 | **Warp / use-level-tile action, the lockout hook** `(game, player, tile unit)` | `0x491ff0` | verified |
| 4 | Warp quest-lock test `(game, player, srcLevel, dstLevel)` -> nonzero refuses (the vanilla twin of Sigma `0x5d810`) | `0x516a50` (one caller, call at `0x49218c`) | verified |
| 4 | Teleport unit into a room at x,y (the level change itself) | `0x491ca0` | verified |
| 4 | Linked destination tile of a warp tile / room level id | `0x2efee0` / `0x2efc10` | verified / verified |
| 5 | **Server game frame** `(Game*)`, frame counter `game+0x170` (Median's `0x2e15a` tick) | `0x406550` | verified |
| 5 | Process all games (timer entry, loops the 1024 game slots) | `0x406400`, slots `0x2a9c020`, `0x4062f0(id)` = game | verified |
| 5 | **Spawn monster at room/x/y** `(game, room, x, y, class, ...)` | `0x4929e0` (core `0x493cc0(spawn struct*)`) | verified |
| 5 | Spawn N monsters around a unit | `0x4934d0` | verified |
| 6 | Requirement gates for NPC services | NPC table bytes +7/+8/+9/+0x10/+0x11 (section 6) | verified |
| 7 | **Treasure-class executor** (1.13c `0x12380`) | `0x4404f0` | verified |
| 7 | TC drop wrapper by TC index (1.13c `0x12d60`) | `0x441300` | verified |
| 7 | TC record getter by index, level-stepped | `0x397290` | verified |
| 7 | Create item from an item-gen struct (1.13c `0x11490`) | `0x43cd50` | verified |
| 7 | Create item of a class (struct builder, quality / ilvl / flags) | `0x43d530` | verified |
| 7 | Unique-item-by-index creator | not found: no equivalent function; see section 7 | open |
| 8 | **Game destroy** `(u64 game id)` ("Deallocate game %p") | `0x4057c0` (called by the idle sweep `0x406e40`; its prologue has a rip-relative load, so it cannot be hooked) | verified |
| 8 | **Per-game client teardown** `(Game*)`: the game-end event the plugin hooks (`game_end.cpp`; entry `40 56 48 83 ec 20 48 8b b1 38 01 00 00`, clean prologue) | `0x486be0` | verified (game_checks `gameend`) |
| 8 | Game struct: first client record `+0x138` (next `+0x628`, client state at `+4`, 4 = in the game); the players in a game are counted from that list (Median reads a count word at game `+0x8c`) | `quests_common.h` | verified |
| 8 | **Game create** (name, password, ... 14 args) | `0x4049d0` (no direct callers) | likely |
| 9 | Client NPC menu table (48 x 0x48 bytes, heap, global ptr) | pointer `0x2a48830`, count `0x2a48838`, filled by `0x360d0` | verified |
| 9 | Client menu builder / NPC row index / click-send | `0x1147a0` / `0x113990` / `0x117510` | verified |
| 9 | Server handler of the menu packet 0x38 `(kind, npc id)` | `0x4b0470` | verified |
| 10 | Gold stat 14/15 client sync | no explicit packet needed (section 10) | likely |
| 11 | Quest handlers 13, 14, 25, 38, 40 | section 11 | verified |
| 12 | **AI table entry getter** `(unit, mode)` -> entry; `mode` 0 = the monster's own AI (monstats `+0x52`, bounds-checked against 155, else entry 0), 1-17 = a command mode | `0x4a36c0` | verified |
| 12 | AI table (155 entries x 0x20: `+0` kind, `+8` init, `+0x10` think, `+0x18` alt) and the mode table (18 entries, same layout) | `0x2396e90` / `0x23981f0` | verified |
| 12 | AI think dispatcher per tick `(game, unit)` / AI set-state `(game, unit, ctl, mode)` | `0x4a2a00` / `0x4a2690` | verified |
| 12 | AI helpers: wait `(game, unit, frames)`, use skill `(game, unit, mode, skill, target, x, y, flag)`, flee `(game, unit, target, mode, n)`, unit seed pointer `(unit)` | `0x4a6d10` / `0x4a7bc0` / `0x4a7df0` / `0x34a1e0` | verified / verified / likely / verified |

## 1. Cube output / recipe result

### Flow (all verified by reading the code)

```
0x4f2490  transmute packet handler  (game, player, packet*, flag)   D2Game\src\Player\PlrMsg.cpp
  -> 0x529090 (int* result, game, player, out)    recipe search; result[0] = record index, result[1] = found
  -> if found and flag != 0:
       record = 0x3e3f60(game[0x106], result[0])
       0x5269c0 (game, player, record, ctx)       D2Game\src\Player\PlrTrade.cpp: consume inputs, run the outputs
```

`0x5269c0` also has a second caller, `0x412ad0` (in the function `0x412908`, which uses the returned item pointer).
That path is not the player's Transmute click (it has a different shape); the plugin's post-hook sees both.

| What | Value |
|---|---|
| `0x4f2490` entry bytes | `40 53 55 57 41 54 41 55 41 56 b8 c8 14 00 00 e8` |
| `0x5269c0` entry bytes | `40 55 53 56 57 41 54 41 55 41 56 41 57 48 8d ac` (prologue then `lea rbp,[rsp-0x15f8]`, 0x16f8-byte frame) |
| `0x529090` entry bytes (search) | `40 55 53 56 57 41 54 41 55 41 56 41 57 48 8d 6c` |
| `0x529d50` entry bytes (input match) | `44 89 4c 24 20 55 53 56 41 55 48 8b ec 48 83 ec` (stub of 0x2e bytes; the body is chained at `0x529dae`) |
| `0x3e3f60` entry bytes (record getter) | `48 89 5c 24 08 48 89 74 24 20 57 48 83 ec 30 48` |

Signature of the recipe executor, the recommended hook for craft flags and gold:

`void* ExecRecipe(Game* game /*rcx*/, Unit* player /*rdx*/, const CubeRecord* record /*r8*/, void* ctx /*r9*/)`
returns the **first output item on success** (`[rbp+0x120]` at `0x528128`) and **null on failure** (`0x528181`: no output
could be made, the inputs are put back with `0x471500`). The recipe row is `(record - 0x3e3f60(game[0x106], 0)) / 0x16c`, exactly the
formula `cube_conditions.cpp` already uses. `ctx` is the `out` buffer of the search (`[rsp+0x60]` in the caller).
**Recommendation (port spec option 2, the post-hook):** detour `0x5269c0`, call the original, and when it returns a
non-null item run the recipe's effect list from the generated table:
set player flag, set game flag, pay gold. The search has already validated the conditions, so the flag/gold step is
the only thing left. Option 1 (patch Median's way) is possible but awkward, see below.

### Recipe record and output slots (D2R, 0x16c bytes)

Verified from the cubemain.txt parser (`0x3e5e60`, which handles the output column and writes the "special" byte) and
from the executor loop (`0x5269c0`, `0x526b58..0x526d6f`):

- Output slot `i` (0-2) starts at **`record + 0x5a + 0x5b*i`** (slot size 0x5b).
- In a slot: `+0x00` dword (used by the Red Portal handler), `+0x04` word flags (bit 8 set by an item-code output),
  `+0x06` dword (item base id / class id parsed from the output cell), `+0x0a` byte, `+0x0b` / `+0x0c` bytes (read by
  the Red Portal handler), **`+0x0d` the special-output byte**, `+0x10` byte, `+0x59` word.
- Special byte values the D2R parser writes: **1 Cow Portal, 2 Pandemonium Portal, 3 Pandemonium Finale Portal, 4 Red
  Portal, 0xff `usetype`, 0xfe `useitem`, 0xfd and 0xfc item-by-name/by-code outputs.** Median's bytes 6-10 do not
  exist in D2R; its byte lives at slot `+8` and its parameter at slot `+6` in a 0x54-byte slot (so offsets differ).
- Dispatch (`0x526d3c`):
  ```
  0x526d3c  movzx ecx, byte [r15+0x67]        ; r15 = record + 0x5b*i, so this is slot+0x0d
  0x526d41  lea   eax, [rcx-1]
  0x526d44  cmp   al, 3                        ; bound: bytes 1..4  (imm8 at 0x526d45)
  0x526d46  ja    0x526d6f
  0x526d4a  lea   rcx, [rip-...]               ; rcx = image base
  0x526d51  mov   r9, [rcx+rax*8+0x1d3bfc0]    ; table entry (disp32 at 0x526d55)
  0x526d59  test  r9, r9 / je 0x526d6f
  0x526d5e  lea   r8, [r15+0x5a]               ; r8 = the output slot
  0x526d62  mov   rdx, rsi (player) ; mov rcx, r12 (game)
  0x526d68  call  r9                           ; handler(game, player, slot)
  ```
- Handler table at **`0x1d3bfc0`** (qwords, index = byte, entry 0 null): `[1]` `0x52a9d0` (jmp `0x5da2a0`, Cow),
  `[2]` `0x52a9f0` (jmp `0x5da590`, Pandemonium), `[3]` `0x52a9e0` (jmp `0x5da430`, Finale),
  `[4]` `0x52aa00` (calls `0x5da800` = Red Portal, args game, player, slot dword, slot[0xc], slot[0xb]). The table is
  followed immediately by assert strings, so it cannot be grown in place.
  Route 1 (patch the bound and table like Median) needs: change imm8 at `0x526d45` from 3 to 9, and point the disp32 at
  `0x526d55` to a plugin table. The disp32 is relative to the *image base* (rcx), so the plugin table must be within
  +-2 GB of it (VirtualAlloc near the base). It is workable but fragile; route 2 (post-hook) avoids both.

### Gold payment and flag storage

Gold stats: carried 14, bank 15 (`0x2f5020(unit, stat, layer)` total, `0x2f7d10(unit, stat, value, layer)` set; both
start with a `jmp [rip+..]` thunk, entry bytes `ff 25 f2 51 b3 03 90 90 90 90 ...` and `ff 25 32 25 b3 03 90 90 90 90
56 57 41 54 41 56`, already used by existing plugin code). The cost is checked by the search; the payment is the
post-hook's job: take `param*100` from stat 14 first, the rest from stat 15. Whether the client sees the new gold
without an extra packet: probably yes, no explicit update is needed (evidence in section 10; not tested in game).
Flags: nothing to find in D2R, they live in plugin memory keyed per game pointer and character name (the name is the first 16
bytes of the player data `0x34b240(unit)`; `craft_flags.cpp`). They are cleared in the game-end hook `0x486be0` (section 8,
`game_end.cpp`); a changed game pointer clears them as well.

## 2. Act 1 quest rewards (Barbarian milestone)

### Quest system layout (D2R, verified)

Quests are objects in a **game-wide list**: `game+0x21d8 -> { head* }`, `head -> quest`, next quest at
**`quest+0x310`**. Each player also has a per-player list (`0x34b3c0(player)`: nodes `{quest*, next@+8}`). A quest object:

| Offset | Meaning |
|---|---|
| `+0x08` | game |
| `+0x10` u8 | act the quest belongs to (events only reach quests whose act equals the act of the NPC's level) |
| `+0x11` u8 | state flag read by the kill handlers |
| `+0x12` u8 | active (1) |
| `+0x270 + 8*event` | **event callbacks (15 slots used)**, `(quest*, event*)` (1.13c: `+0xa0 + 4*event`) |
| `+0x310` | next quest in the list |

Event struct built by the wrappers (`rdx` of every callback, 1.13c `esi`): `+0` game, `+8` u32 event number,
`+0x10` primary unit (killed monster / NPC), `+0x18` the **player**, `+0x28` u16 NPC class id, `+0x30` u16 dialog
message id. Events seen: **0** player activates/clicks an NPC (`0x515980`, wrapper args `(x, player, npc, r9)`),
**2** `0x5158c0`, **3** `0x515c30`, **4/5** `0x515400/0x5154e0`, **8** monster killed (`0x515640`),
**9** `0x515a69`, **10** `0x515b4e`, **11** NPC dialog message (`0x516940`), 1/2 object events (`0x5182e0..0x518d00`).
The numbering matches Median's notes for slots 0, 2, 8, 11 (confirmed by the handler bodies below).

The generic sender is `0x518ec0(event*, bool allQuests)` (1.13c `0x9fb30`): runs the event number at `event+8` over the
quest list of the unit at `event+0x10`, calling `quest+0x270+8*n` for active quests (or all with the flag).
All the wrappers are tiny and stable; **hooking the wrappers is simpler than hooking each quest's handler** and covers
every quest at once (the plugin filters on quest id by comparing `quest` with the registered object, or on NPC class /
monster class itself).

Each quest's init function stores its handlers into the object. `tools/d2r_find.py qinit a1q6` prints them:

| Quest (file) | Init fn | event 0 (NPC activate) | event 8 (kill) | event 11 (NPC message) |
|---|---|---|---|---|
| id 4 `a1q4` (Search for Cain) | `0x5db310` | `0x5dfe90` | `0x5e29d0` | **`0x5e0830`** |
| id 6 `a1q6` (Andariel) | `0x5db6c0` | **`0x5e1d30`** | **`0x5e1f00`** | `0x5e2660` |

Quest id to source file and the full list of Median-hooked quests: Appendix A (the quest descriptor table at `0x239c5c0` gives id,
act and init function for all 36 quests; `d2r_find.py qinit <id>` lists the handlers).

Entry bytes: `0x5e0830` `40 53 55 56 57 41 56 48 83 ec 60 44 0f b7 72 28`; `0x5e1f00` `40 53 55 41 56 48 83 ec 40 33 ed 48 89 74 24 68`;
`0x5e1d30` `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 57`; `0x5e2660` `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 48`;
`0x5dfe90` `48 89 5c 24 10 48 89 6c 24 18 48 89 74 24 20 57`; `0x5e29d0` `48 89 5c 24 08 48 89 74 24 18 57 48 83 ec 40 48`;
wrappers: `0x515640` `48 89 5c 24 10 48 89 6c 24 18 57 48 83 ec 70 48`, `0x515980` `48 89 5c 24 08 48 89 74 24 10 57 48 83 ec 60 49`,
`0x516940` `40 53 48 83 ec 60 33 c0 48 89 4c 24 20 c7 44 24`, `0x518ec0` `48 89 74 24 10 57 48 83 ec 20 48 8b f9 0f b6 f2`.

### Kill wrapper `0x515640` (verified)

`void QuestKill(Game* game, Unit* victim, Unit* killer)`; called from `0x44db20` (D2Game\src\Unit\SUnitDmg.cpp, the
unit-death function, at `0x44dd20`) once per death. It resolves a minion killer to its owner player, builds event 8
(`+0x10` victim, `+0x18` player) and calls `0x518ec0`. A pre/post-hook here sees every kill with the killer player:
**Andariel = monster class 156 (`0x9c`)**; the vanilla handler does not test the class itself (the quest's own list
position does), so compare the victim's class id (`0x349860(victim, file, line)`).

### Andariel catalyst (Median `0x9e9f0`, vanilla 1.13c `0x67e00`; D2R `0x5e1f00`)

1.13c's `0x67e00` and D2R's `0x5e1f00` are the same function: tests quest-6 bits 0 and 1 (`0x325c50(record, 6, 0/1)`),
runs the drop sequence (D2R: random state table at `0x23aaa38/0x23aaa58`, drop via `0x43fbf0`), sets state. Median's hook
adds, in Normal, a once-per-player drop of TC "Quest Cata Disenchant" and sets a plugin-owned flag.
**Simplest port:** at `0x515640` (kill) or in a detour of `0x5e1f00`, when the victim class is 156, the game
difficulty `game[0x104] == 0`, and the killer has not yet got the flag, create the catalyst item directly in the
killer's inventory with `0x517530` (code `'3o[ '` = `0x205b6f33`) instead of rolling a treasure class. This avoids needing
D2R's treasure-class executor, now found at `0x4404f0` (section 7; 1.13c `0x12380`). `0x43fbf0` below is not the TC path: it
picks a gold / fallback item (`gld `, `0x443f40`) and creates it at the monster's position. Store the per-player flag as a plugin-owned bit in the player's quest record (e.g. quest 6,
bit 0xc) with the set function.

### Cain re-issue and Akara's reward

- Re-issue (Median `0x9eb40`, vanilla 1.13c `0x60a80`, D2R `0x5e1d30` = a1q6 event 0): when the player activates an NPC
  (event 0; `event+0x10` is the NPC, `event+0x18` the player) and the plugin flag is set, create `'3o[ '` if
  `0x441980(game, player, code)` (find item by code in the inventory, returns the item or null) says the player lacks it.
  Hook `0x515980` (every NPC click) or `0x5e1d30`.
- Akara's / Cain's reward (Median `0x9e730` / `0x9e810`, vanilla 1.13c `0x66ce0`, D2R **`0x5e0830`** = a1q4 event 11): the
  handler is the same function (same constants: NPC class `0x94` Akara, `0x109` = 265 Cain in town (messages `0x7b/0x7d/0x7e` are his), messages
  `0x61, 0x70, 0x76, 0x7d`, `Ordinal 10174` -> `0x325c50`). It handles `msg 0x61` (starts the deciphering), `msg 0x70`
  (hand over `bks `, create `bkd ` through `0x517530`) and `msg 0x76` (quest 4 bit 1 set: clear bit 1, set bit 0, give the
  vanilla `rin ` reward, then follow-up). Median adds Griswold's Heart at `msg 0x76` with bit 1 set: run before the vanilla
  handler (detour `0x5e0830`; `event+0x28` u16 == `0x94`, `event+0x30` u16 == `0x76`, bit test `0x325c50(rec, 4, 1)`),
  create the unique with `0x517530`-style creation (a unique by index needs the item-create call at `0x43d530`, see below).
  D2R's ring is delayed through a quest timer callback at `0x5d9a30` (creates `'rin '` for the player id in the callback
  struct); the Median hook can run independently.
  *Note:* the lane brief calls this "Akara's Heart / Den of Evil reward"; the code path is Akara's message `0x76` after
  the Cain rescue (quest 4), not quest 1.

### Reward and quest-bit helpers

| Function | RVA | Signature | Confidence | How |
|---|---|---|---|---|
| quest bit test | `0x325c50` | `(record, questId, bit)` -> 0/1 (bit `questId*16+bit` of the record's bitmap; tail of `0xa1ba50`) | verified | called 196 times in Quests code, args seen: `(rec, 6, 0)`, `(rec, 4, 1)` |
| quest bit set | `0x325c00` | same; tail `jmp 0xa1ba30` (`or [byte], mask`) | verified | same prologue, the or-form |
| quest bit clear | `0x325990` | same; tail `jmp 0xa1b810` | likely | same prologue, other mask table (`0x1d99750`), not seen executing |
| player quest record | `rec = *(u64*)(0x34b240(player) + game[0x104]*8 + 0x40)` | | verified | repeated in a1q4, a1q6 handlers |
| create quest item by code | `0x517530` | `(game, player, code /*r8d*/, itemLevel /*r9d, 0 = player's level*/, [rsp+0x20] quality/seed arg, [rsp+0x28] = 1)` -> item* or null; creates via `0x43d530`, adds to the inventory (`0x471500`), sends the item packet (`0x535f60`) | likely | matches 1.13c `0x36470` (`QUESTS.CPP`, create + inventory + packet); callers pass `'bkd '`, `'rin '` |
| find item by code in inventory | `0x441980` | `(game, player, code)` -> item or null (`D2Game\src\Items\Items.cpp`; walks the inventory, compares `0x36ef50(item)` with the code, and for quest items also stat 0x164 against the game difficulty) | verified | read; used before the scroll hand-over in `0x5e0830`; entry bytes `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 48` |
| monster drop item creation | `0x43fbf0` | `(game, monster, type /*2 in Andariel*/, out*, ..., -1, 0)`; builds a 0x84..0xc8-byte item-gen struct and calls `0x43cd50` | likely | matches 1.13c `0x11a70`'s role (the drop step of the kill handler) |
| item-gen core | `0x43cd50` | | guess | callee of `0x43fbf0` |

## 3. NPC interaction menu

### Server

- **NPC click**: block `0x4c26a7` of a PlrMsg packet handler (it calls `0x502f60`, sends the 0x27 reply with the NPC unit
  id/type via `0x47e340`, and runs quest event 0 through `0x515980` at `0x4c26f2`). `.pdata` only gives this block, not
  the function entry; the parent is a large `D2Game\src\Player\PlrMsg.cpp` switch. Prefer hooking the quest wrappers
  (section 2) for rule logic; use this block only to read how the click arrives.
- **Dialog message** (the player picks a dialog line): **`0x4c33e0`**, entry bytes
  `40 55 53 57 41 54 41 55 48 8d 6c 24 e0 48 81 ec`; it calls `0x515980` (event 0, `0x4c37b2`) and the message wrapper
  `0x516940` (event 11, at `0x4c35cf`, `0x4c3bbf`, `0x4c3bd4`). Custom actions (Median's 16 action slots) can be run by
  hooking `0x516940` (`(game, player, npc id /*r8d, -1 = none*/, msg /*r9w*/)`; the quest handlers read the message at
  `event+0x30` and the NPC class at `event+0x28`).
- **Trade / gamble / hire packet**: **`0x4b0470`** `(game, player, packet*, size)`, `D2Game\src\Player\PlrMsg.cpp`
  (assert strings "Can't trade / gamble / hire with this NPC. player: %u, dwParam1: %u, dwParam2: %u."). Entry bytes
  `40 55 53 56 57 41 54 41 55 48 8d 6c 24 d1 48 81`. It finds the NPC (`0x53b8f0`), fetches the NPC record
  `0x3971a0(dataFlag, npcClass)` and branches on the request type (`[rbp-8]`: 1 trade, 2 gamble, 3 hire) testing
  record bytes `+8` (trade), `+9` (gamble), `+7` (hire), see section 6.

### Client

The NPC dialog UI is in **`D2Client\src\UI\npcmenu.cpp`** (string `0x1cc78a0`): 22 functions between `0x10a520` and
`0x117634`; global state `0x2a4875c` (NPC unit id), `0x2a48764` (NPC class, word), `0x2a487b0`, `0x2a48760`. Three of
them call the NPC-table getter `0x3971a0` (`0x1147a0`, `0x1162f0`, `0x117510`; `0x117510` is the "click a menu item"
sender: it reads record byte `+0xb` and sends packet 0x2e through `0xec820`). **The menu is built from the same static
NPC table** as the server checks; so editing that table (section 6) changes both the buttons and the server answer.
How the visible list is composed (a heap table of 48 records, 5 lines per record), where extra lines can be added and
what the server does with a chosen line: section 9. Layout (sprites, JSON panels) is separate and not in this lane.

## 4. Level entry / warp (dungeon lockout)

Read from the Ghidra decompile (lane d2r-addresses-2, 2026-10-21). Entry bytes in the table at the end of this section.

### Flow (verified)

```
0x4adbb0  packet handler "use warp" (game, player, packet*, size = 5)   PlrMsg.cpp
   finds the clicked tile unit (type 5, id = packet dword), checks hostility 0x42bfb0 and the distance
   (0x325140(player, tile) < 0x33 then again < 5), then
-> 0x491ff0 (game, player, tile)                                     SUnit.cpp   <-- the warp action
   other callers: object-operate functions of stairs / ladders / trapdoors (0x58e230 -> 0x58e2d8, 0x590160, 0x5906e0,
   0x5a11a0): they look for the type-5 tile in the object's room and call 0x491ff0 with it
```

`0x491ff0(Game* rcx, Unit* rdx = player, Unit* r8 = tile)`; body (decompiled):

1. `room = 0x34b440(tile)`; `cls = 0x349860(tile, "SUnit.cpp", 0x133)` (= `*(u32*)(tile+4)`, the tile's class / link id).
2. `dst = 0x2efee0(game[0x106], room, cls, &out)`: **the linked tile unit in the destination room** (D2Common `Dungeon.cpp`
   walk of the room's unit list for a type-5 unit with the same class), `out` points at a record whose `+0x40/+0x44` are
   the x/y offsets to land at. `dst == 0` -> nothing happens.
3. `dstRoom = 0x34b440(dst)`; `(x, y)` = the tile's position (`unit data +0x10/+0x14`).
4. `landing = 0x362f90(dstRoom, &xy, size, 0x1c09, 1)` (find a free spot, unit size `0x34b580(player)`); null -> return.
5. `srcLevel = 0x2efc10(room)`, `dstLevel = 0x2efc10(landing)` (level id of a room, entry bytes in the table).
6. **Quest lock**: if `dstLevel - 0x49 < 0x3c` and bit `dstLevel-0x49` of `0x880200008000001` is set (levels 73, 100, 118, 128,
   132; 73 = Duriel's Lair, 100 = Durance of Hate 1, 132 = Worldstone Chamber, and 118 / 128 only when the source level is
   120 = the Ancients' gates) then `0x516a50(game, player, srcLevel, dstLevel)`; a nonzero result **refuses** (the code jumps to the end, `0x492295`).
   `0x516a50` is a small switch calling the quest checks (`0x59ec70` Duriel, `0x1405e99e0` level 100, `0x546b20`, `0x546c90`).
   It has exactly one caller (the call at `0x49218c`), and it is the vanilla twin of D2Sigma's replacement `0x5d810`
   `(game, player, srcLevel, dstLevel)` which returns 1 to refuse.
7. Otherwise `0x491ca0(game, player, dstRoom, x, y, 0, 0)` does the move (SetPos / room change; 25 callers: every teleport
   uses it); on success `0x42d2c0(game, player, 0, 2, x, y, 0, 0)` sets the walk mode and `0x47abc0(client, 0x0d, ...)`
   sends the position packet (id 0x0d) to the player.

### Where to refuse and how (answer)

- **Best hook: detour `0x491ff0` itself** (5 callers, one prologue, no mid-function patching). Compute the destination level
  before calling the original:
  ```
  room    = GetRoom(tile)                          // 0x34b440
  cls     = *(uint32_t*)(tile + 4)                 // what 0x349860 returns (the file/line args are only for asserts)
  dstTile = FindTile(game[0x106], room, cls, &out) // 0x2efee0
  dstLvl  = LevelOfRoom(GetRoom(dstTile))          // 0x2efc10(0x34b440(dstTile))
  srcLvl  = LevelOfRoom(room)
  ```
  then run the Median logic (sealed? difficulty / level / class requirements from `mxl_dungeons.h`, unlocking only by the
  lock group). To **refuse, return without calling the original**. That is the vanilla refusal path (`0x492295`): nothing
  is sent and the player stays where he is, the same as an unfinished Duriel quest. The client has no pending state for
  the click (it only sent "use tile"), so there is no hang.
- Alternative (smaller): patch the call at `0x49218c` to a plugin function with the `0x516a50` signature (return 1 to refuse)
  and also bypass the range test in front of it (it only calls `0x516a50` for the five levels above); a detour of
  `0x491ff0` avoids both.
- **Signalling to the player.** The vanilla path is silent. A message needs a server -> client packet. The ready-made
  chat sender `0x477a30` is documented in section 13 (found later; the plugin uses it). Raw send also works: the game
  has a network service singleton `0x649610()` (`lea rax, [global]; ret`), and a packet is sent with
  `(*(void(**)(void*, uint32_t conn, Span*))(*svc + 0x28))(svc, *client, &span)` where `span = {begin, end}` points at the
  packet bytes (see `0x47abc0`, which sends packet 0x0d this way; `client = *(Client**)(0x34b240(player) + 0xf0)`, `*client` is the
  connection id). For the lockout message use a chat / game-message packet (0x26 or 0x5a) built by hand, or let the
  D2RLoader client plugin show the text (it knows the level id).
- **Portals (red portal / town portal) do not go through `0x491ff0`** (their object functions place the player with their own
  code); Median starts the lockout clock in the portal-object operate functions (item_spells hooks), which are not part of
  this section.

The dungeon `Entry` table (`mxl_dungeons.h`) is plugin-owned: D2R's levels table has no +0x14b..+0x15f extension. Per-game
lockout state: use the game pointer as key and reset in the game-destroy hook (section 8).

| Function | RVA | Entry bytes |
|---|---|---|
| warp action | `0x491ff0` | `48 8b c4 53 55 57 41 56 48 83 ec 68 49 8b d8 4c` |
| quest-lock test | `0x516a50` | `45 8b d1 41 83 ea 49 74 33 41 83 ea 1b 74 28 41` |
| teleport into room | `0x491ca0` | `40 55 53 56 57 41 54 41 55 41 56 41 57 48 8d 6c` |
| linked tile finder | `0x2efee0` | `48 89 5c 24 18 56 48 83 ec 30 48 8b 52 18 48 8d` |
| room -> level id | `0x2efc10` | `48 85 c9 75 03 33 c0 c3 48 8b 49 18 e9 9f 13 07` |
| unit -> room | `0x34b440` | `40 53 48 83 ec 20 48 8b d9 48 85 c9 75 13 88 4c` |
| unit class id (assert args) | `0x349860` | `48 83 ec 28 48 85 c9 75 1d 88 4c 24 30 48 8d 4c` |

Confidence: verified (every step read in the decompile; the five quest-lock levels are decoded from the bit mask). The client's
entry-requirements text (Sigma `0x5d150`) is client UI and does not exist in D2R. The 1.13c function matching `0x491ff0` was not
named by address (D2Game's warp lives next to the quest-lock test that Sigma replaces).

## 5. Monster spawning and the game tick (treasure goblins)

### The server game frame (verified)

`0x406550(Game* game)` is the per-game frame, 25 Hz, called for every live game by `0x406400(tickMs)` ("int SrvProcessAllGames(unsigned
long)", global slot array `0x2a9c020`, 1024 u64 game ids, `0x4062f0(id)` -> `Game*`). It increments the frame counter
**`game+0x170`** (1.13c `+0xa8`), runs the subsystem updates (client list update, `0x516e40` every 20 frames, `0x4088c0` every 12 frames,
the per-player pass every 11 frames) and returns. This is the exact twin of 1.13c `0x2e050`, and Median patches the end of it
(`0x2e15a`). Hook: detour `0x406550`, call the original, then run the plugin's 15 s goblin tick
(`frame % 375 == 0`). Entry bytes `48 89 74 24 20 55 57 41 57 48 8d 6c 24 b9 48 81`. Found with `tools/d2r_scan.py pat2 "e9 a2 8b 2e"
"ab aa aa 2a" "67 66 66 66"` (the x%11, x%12, x%20 magic multipliers all in one function).

Useful game offsets from this function: `game+0x138` first client (linked via `client+0x628`, `client+4 == 4` is "in game",
`0x484c90(client, 0)` = the client's player unit), `game+0x190` vector of per-act level data, `game+0x106` expansion
flag, `game+0x104` difficulty, `game+0x1aaa0` the telemetry object. The frame counter is the clock for the "last kill within 375
frames" test (player's last-kill frame goes into plugin state; there is no D2R field for it).

### Spawn (verified)

All spawns go through **`0x493cc0(SpawnInfo* rcx)`** (returns the monster `Unit*`, null on failure). `SpawnInfo` (stack struct,
filled identically by `0x4929e0`, `0x4934d0` and `0x492e70`):

| Offset | Field |
|---|---|
| `+0x00` | `Game*` |
| `+0x08` | room (`Room*`) |
| `+0x10` | related unit (owner / summoner; 0 for a plain spawn) |
| `+0x18` | **monster class id** (monstats row, `0x1400976e0(game[0x106], class)` is the record getter) |
| `+0x1c` | u32, passed to unit creation (1 in observed calls) |
| `+0x20` | 0 |
| `+0x24` / `+0x28` | **x / y** (sub-room coordinates, absolute) |
| `+0x2c` | i32; -1 normally (negative = default) |
| `+0x30` | u16 flags (0x40 seen with minions; bit 0x80 tested) |

The simplest call is the wrapper **`0x4929e0(Game* game, Room* room, int x, int y, int classId, int a6 = 1, int a7 = -1, int a8 = 0, uint16 flags = 0)`**
(entry bytes `4c 8b dc 49 89 5b 08 57 48 83 ec 70 8b 84 24 a0`): it builds the struct, calls `0x493cc0`, and on success finishes the
monster with `0x4a5800(game, monster, unitId, 1, 1, a8)` (adds to the game / sends it to clients). Returns the monster or null.
`0x4934d0(game, nearUnit, classId, a4 = 1, a5, count, flags)` spawns `count` copies around a unit (used by Diablo's minion calls with
class ids 0x1c5, 0x185, 0x17d). The 1.13c spawn Median uses (`0x10042630(id, x, y)`) maps to `0x4929e0`.
The room for a goblin: `0x34b440(playerUnit)`; position near the player: `0x34a040(player, &xy)` (unit position as two ints) plus an offset,
checked with `0x38dfb0(room, x, y)` ("is this position inside the room", returns the room or null) like `0x43fbf0` does.

| Function | RVA | Entry bytes |
|---|---|---|
| game frame | `0x406550` | `48 89 74 24 20 55 57 41 57 48 8d 6c 24 b9 48 81` |
| process all games | `0x406400` | `48 89 5c 24 18 48 89 6c 24 20 56 57 41 57 48 83` |
| game by id | `0x4062f0` | `4c 8b 05 19 5d 69 02 48 8b d1 4d 85 c0 74 77 4d` |
| spawn core | `0x493cc0` | `48 89 5c 24 10 48 89 74 24 18 48 89 7c 24 20 55` |
| spawn at room x,y | `0x4929e0` | `4c 8b dc 49 89 5b 08 57 48 83 ec 70 8b 84 24 a0` |
| spawn N around unit | `0x4934d0` | `40 53 55 41 54 41 57 48 83 ec 78 45 8b f9 45 8b` |
| monster post-init / add | `0x4a5800` | `48 89 6c 24 18 57 41 56 41 57 48 83 ec 30 4c 8b` |

The "goblin sighted" notice (Median packet 0x5a type 0x15) has no D2R counterpart; use the raw send in section 4 or a client-side message.

## 6. Item / skill requirement checks (the requirements evaluator)

Median's requirement table only gates NPC services (quests-requirements.md). In D2R the same gates exist as **a static
NPC table**, and its checks run on both client and server:

- **Table: RVA `0x237ea60`, 43 entries of 0x1c bytes**, writable data; getter **`0x3971a0(dataFlag /*ecx*/, npcClass /*edx*/)`**
  returns the entry or null (linear scan, entry `+0` is an s16 class id). Entry bytes of the getter:
  `45 33 c0 4c 8d 15 b6 78 fe 01 41 8b c8 4d 8b ca`.
- Fields (verified with Kashya 150, Gheed 147, Qual-Kehk 515 against known game behaviour): `+0` class id (s16), `+7` hire
  allowed, `+8` trade (shop) allowed, `+9` gamble allowed, **`+0x10` hire quest gate: quest id + 1 (0 = none)** (Kashya `3`
  = quest 2 Blood Raven, Qual-Kehk `0x25` = quest 36 Rescue on Mount Arreat: **this is exactly Median's hire gating, so
  requirement rows 9 and 14 already hold in D2R**), `+0x11` minimum level for hiring (Kashya 8), `+0x0a` act index,
  `+0x18` a second id (`-1` none).
- The server checks (`0x4b0470`): hire needs `+7`, then the quest gate (`0x325c50(rec, quest-1, 0)` must be set) and the
  level (`stat 12`, via `0x2f5020`); trade needs `+8`; gamble needs `+9`.
- **Hook plan for `requirements.cpp`:** (1) static cases at plugin load: write the table bytes (Median turns the shop off
  for Atma 176, Geglash, Cain in acts 2 and 5, act2vendor1; the table is in `.data`, so a guarded write like the
  srvdofunc table works). (2) Dynamic cases (anything the table cannot say, such as Cain's per-catalyst buttons): hook the
  server packet handler `0x4b0470`, or call the evaluator from a detour of the getter `0x3971a0`... the getter has no
  player argument, so prefer `0x4b0470` for denial and the client menu functions for display.
- Item level/class requirement checks for equipment and skills (strength, level, class) are not gated by Median's
  evaluator; D2R's own `0x376de0(item, player)` (item level requirement, plugin-known) is the call to reuse.

## 7. Treasure classes and item creation

### Treasure-class executor (verified)

**`0x4404f0`** is 1.13c `0x12380`: same ten parameters, same algorithm (NoDrop float pow, pick count, `0x6ac690c5` LCG,
recursion stack, up to 6 results by default), `D2Game\src\Items\Items.cpp`, log line "Spawn From %d".

`void TCExec(Game* game /*rcx*/, Unit* monster /*rdx, rng owner and drop origin*/, Unit* killer /*r8, player (may be null)*/, TcRecord* tc /*r9*/, int quality /*5th, 0 = roll*/, int a6 /*6th, quality-roll input (1.13c: param_6 of the quality roll)*/, int force /*7th, nonzero skips the NoDrop roll*/, Unit** out /*8th: items array, or null*/, int* outCount /*9th*/, int max /*10th*/)`

(args 1-4 in registers, 5-10 at the caller's `[rsp+0x20]` ... `[rsp+0x48]`; entry `4c 8b dc 55 53 49 8d ab 08 f7 ff ff 48 81 ec e8`; the 5th-10th
meanings are taken from the identical 1.13c body, the D2R body keeps the same order: `out`/`max` are tested as `param_8`/`param_10` and `*outCount` as `param_9`).
With `out == null` up to 6 items (`max <= 0`) are created via the item-gen path around `monster`; with `out` they are returned in the array.
TC record (D2R, `0x397290` hands them out): `+0x10` total probability (classic), `+0x14` (expansion), `+0x18` picks (negative =
"all" mode), `+0x24` flags (0x40 = conditional), `+0x38` entries pointer, `+0x40` entry count; entry stride **0x20**: `+0` prob (classic),
`+4` prob (expansion), `+8` item id or TC id, `+0xc` flags (1 = item code, 2 = TC, 4 = unique/set class, 0x10 = "always", 0x40 = conditional).

**Wrapper by TC index: `0x441300(Game*, Unit* monster, Unit* killer, u16 tcIndex /*r9w*/, int quality, ...)`** (1.13c `0x12d60`): it
adds the monster's level (stat 12, or the area level) to select the right level step of the TC with **`0x397290(dataFlag, tcIndex, level)`**
(returns the TC record; group array `*(base ptr from 0x300a90() + 0xd78)`, count at `+0xd80`, stride `0x150`; if the group has level
steps the one whose `+2` level bound is not exceeded wins), then calls `0x4404f0`. Entry bytes `0x441300` `40 53 55 56 57 41 54 41 55 41 56 41 57 48 81 ec`;
`0x397290` `48 89 5c 24 08 55 56 57 48 83 ec 30 41 8b d8 0f`. Callers of `0x4404f0`: `0x441300` and `0x5932ec` (inside `0x5930b0`, a
monster-side caller, presumably the death drop; not read), exactly the two callers 1.13c `0x12380` has.

For the catalyst: `tcIndex` is the index of the named TC ("Quest Cata Disenchant") in the TreasureClassEx group array; resolve it once by scanning
`0x300a90()+0xd78` (stride 0x150) for the plugin's row (the name string is in the record), or take the index from the monstats row
(`TreasureClass1` field) like Median does. Not all of this has been exercised in game.

### Item creation (verified for the primitives, open for "unique by index")

Item-gen struct `ItemGen` (0xc8 bytes, zeroed by the builders): `+0x00` owner Unit* (the receiver), `+0x10` `Game*`, `+0x18` item level,
**`+0x20` base item class id**, `+0x24` mode (3 = on the ground, 4 = inventory), `+0x28`/`+0x2c` x/y, `+0x30` room, `+0x38` u16 = 1,
`+0x3a` u16 = `game[0x128]`, **`+0x3c` explicit-fields flag** (nonzero: the next fields are applied), `+0x40` quality / drop kind chosen by the caller
(2 in the quest creators, 5 or 6 at `0x541cec`; `0x43fbf0` re-rolls the base item until it can be magic when it is 4; **no reader of `+0x40` was found in
`0x43cd50`**, so how D2R applies it is open), `+0x44` stat 0x46 (defense) or gold amount, `+0x48` / `+0x4c` durability (0x48) / max durability (0x49)
(explicit mode), `+0x54` item flag word, `+0x58` unit seed, `+0x5c` item init seed, `+0x60` ear name.

- **`0x43cd50(Game* rcx, ItemGen* rdx, int applyExplicit /*r8d*/)`** = 1.13c `0x11490`: creates the item (`0x490410`), sets flags, level, stats,
  adds the ear owner for kind 7; returns the item or null. Entry `40 55 53 56 41 54 41 57 48 8d 6c 24 c9 48 81 ec`.
- **`0x43d530(Unit* owner, int classId, Game* game, int mode /*4*/, int quality, int bitA, int bitB, int ilvl, int applyExplicit,
  int seed, int initSeed)`** = a struct builder + `0x43cd50`; the 8 existing callers pass mode 4 and quality 2 (`0x4fa8fd`, `0x4fb843`, `0x4404a2`), a computed
  5 / 6 (`0x541cec`) or a variable. Entry `40 55 53 56 57 48 8d 6c 24 f8 48 81 ec 08 01 00`.
  `0x517530` (create by code in a player's inventory, section 2) is its main wrapper.
- **Unique item by index (open)**: Median's `D2UniqueItems.cpp` `0xbb330(game, owner, uniqueIdx)` (name lookup `0xbb4d0`, table at txt +0xc24, stride 0x14c)
  zeroes a 0x84-byte struct and sets owner, game, ilvl = unique row `+0x34`, class = the row's code (`+0x28`), mode 4, word 1 / game word, **quality 7
  at struct `+0x30`** and **unique row + 1 at struct `+0x40`**, then calls 1.13c `0x11490`. With the same layout shift as the other fields
  (1.13c `+0x2c` explicit flag = D2R `+0x3c`, `+0x30` = `+0x40`), the D2R slots would be quality `+0x40` and unique row + 1 at `+0x50`. **D2R's `0x43cd50` reads neither**
  (`+0x58` / `+0x5c` turned out to be seeds, `FUN_14034edd0` stores the unit seed), so there is no function taking a unique index that I could confirm; the
  quality / unique choice sits deeper in the unit creation (`0x490410` -> `0x1404905a0`), which was not read. Practical routes for Griswold's Heart:
  (1) create the unique's base item with `0x517530` / `0x43d530` with quality 7 in the 5th argument and **test in game** whether the struct's `+0x40`/`+0x50` slots
  select the row (run `0x43d530` and then patch the item data), (2) run a one-entry TC (`0x4404f0` with a TC whose only entry is the unique class).
  Route 2 reuses the vanilla unique roll and needs only TC data (unique drops by TC pick the unique whose base matches; if Griswold's Heart is the only unique
  of its base in the data it is deterministic). Confidence: primitives verified, unique-by-index open.

## 8. Game create and destroy (server)

- **Destroy: `0x4057c0(u64 gameId)`** (log "Deallocate game %p"): looks the game up in the id hash map (`0x2a9c010`), tells the network service,
  clears the id in the slot array (`0x2a9c020`, 1024 entries), frees per-game subsystems (`0x5128d0`, `0x513e20`, `0x5026f0`, `0x486be0`, `0x488bf0`...), then
  the node. The `Game*` is the map node + 0x10: get it with `0x4062f0(id)` **before** calling the original. Hook this to clear any per-game state
  (craft flags, dungeon lockout clocks, goblin timers). Entry bytes `40 53 48 81 ec 80 00 00 00 48 8b 15 40 68 69 02`. The only caller is the idle sweep
  **`0x406e40(tickMs)`** (`48 89 5c 24 18 89 4c 24 08 55 56 57 41 54 41 55`): it destroys a game 300 s after the last client left (`game+0x140 == 0`) or when
  `game+0x1a5d8 != 0`.
- **Create: `0x4049d0`** (14 arguments: name, password, description, ... difficulty, flags; frame of 0x14ec8 bytes, `D2Game\src\Game\Game.cpp`
  strings in the chunk `0x404b9a`): allocates the game, registers it in the slot array and the id map, initializes the subsystems. No direct
  callers (entered through a job / pointer). Entry `40 55 53 56 57 41 55 41 56 41 57 48 8d ac 24 70`. Likely: the function reads the
  game name for the duplicate check and registers the game; the `Game*` is not returned. A first frame hook (`0x406550` seeing a new pointer) is
  an equivalent create hook with no extra risk.
- Per-client join / leave states are handled in `0x408ea0(Game*)` (strings "[JOIN 5] %u clientid, SrvJoinAct: Added to game.", "[JOIN 6]").

## 9. Client NPC menu (npcmenu.cpp)

### Composition (verified)

The menu is **data driven**. `0x360d0` (a CRT static initializer, entry `48 89 5c 24 08 48 89 74 24 10 48 89 7c 24 18 55`) copies a stack image
into a heap array and stores it in the globals **`0x2a48830` (pointer)** and **`0x2a48838` / `0x2a48840` (count 0x30 / capacity)**.
`NpcMenu` records, **stride 0x48**, 48 of them:

| Offset | Field |
|---|---|
| `+0x00` u16 | NPC class id |
| `+0x04` u32 | line count **including the final Cancel** (3 = two lines + Cancel) |
| `+0x08` u16[8] | string table ids per line: **0xd35 Talk, 0xd44 Trade, 0xd46 Gamble, 0xd45 Hire, 0xd06 Repair, 0xfb4 Identify**, 0xd37 / 0xd39 two special lines |
| `+0x18` qword[5] | click handlers per line: **`0x112eb0` Talk, `0x112f30` Trade (sends 0x38 kind 1), `0x112c80` Gamble (0x38 kind 2), `0x112620` Hire, `0x114000` Identify, `0x1162f0` special (quest-gated)**, `0x112c30` Cancel (implicit) |
| `+0x40` u8 | flag (1 for all NPCs that talk) |

Key functions: **`0x1147a0(dataFlag)`** builds the visible list (reads record `0x113990(npcUnit)` = record index by class id; loops `count - 1`
lines, special-casing ids 0x1507, 0xfb4, 0x2ba0 and quest bits 0x29 / 1; line text = `0x143e2b730(stringId)`; adds each line to the list widget
`DAT_142a487b0` with `0x1401e9030`; the last line is always Cancel `0x102e` -> `0x112c30`); **`0x117510(param)`** sends packet 0x2e (the
NPC interact packet, built by `0xec820`); **`0xec730(id, a, b)`** builds the 9-byte client packets (the menu uses `0x38`).
The sprite / frame layout is separate. Records read from the initializer (class: lines): 148 Akara Talk+Trade; 147 Gheed and 199 Talk+Trade+Gamble;
154 Charsi Talk+Repair; 150 Kashya Talk; 198 Greiz and 252 Asheara have Hire (Asheara Talk+Hire+Trade); 244, 245, 246, 265 (0x109) and 520 (0x208), the Cains, are
Talk+Identify; 255 Ormus Talk+Trade; 511 Larzuk Talk+Repair; 512 Anya Talk+Trade+Gamble; 513 Malah Talk+Trade; 175 and 264 Talk plus one special line (0xd37 / 0xd39,
handler `0x1162f0`); 257 (first record) Repair only. All records can be listed again by decompiling `0x360d0` and reading the stack image
(`DecompOut.java 0x360d0`); the field layout is the table above. Maximum **5 lines per record** (the `+0x18` handler array has 5 slots, the id array 8);
there are no spare slots for 16 actions.

### Durability in the client UI (lane no-durability)

| What | Where | Notes |
|---|---|---|
| `Durability: x of y` line of the item description | `0x2c1640 (item, text buffer)`, no result | gate: `0x373540` (the base has durability), `0x2f4b60` (maximum durability > 0), `0x374710` (throwable-like: no line); strings `ItemStats1d` and `newline` appended with `0x1412276a0` (strcat into a 0x400 buffer). Callers: `0x2bd480` (inventory tooltip, 9 args, one direct caller `0x150c377`) and `0x2be560` (`std::string out, item, flags, char, char* text, options*`; one direct caller `0x87e8ac`: `rcx` = a 0x28-byte block `{char* text, size, cap, inline buffer}`, `r8d` = 0, `r9b` = 1, `[rsp+0x20]` = 0, `[rsp+0x28]` = a block whose byte `+8` is 0). The harness verb `itemdesc` calls `0x2be560` that way |
| Vendor panel mode | `0x2411e0` (VendorPanel set-up); dword `+0x168` of the panel: 0 trade, 1 repair vendor, 2 gambler | mode 1 for the NPC classes 0x9a Charsi, 0xb2, 0xfd, 0x101, 0x1ff Larzuk (the switch at `0x2412a3`, `mov [rbx+0x168],1` at `0x2412de`); mode 1 draws `button_repair`, `button_repair_all` and `background_repair` and hides `button_blank`, `button_close`, `background`; mode 2 draws `button_refresh` and the `tabs`. `0x22ba70` writes the same field of another panel (gold amount) and is not the vendor panel |
| NPC menu "trade/repair" line | string id 0xd06 (`NPCMenuTradeRepair`, `trade/repair`) in the records of Charsi, Larzuk and record 257 | 0xd44 is `NPCMenuTrade` (`trade`), used by Akara, Gheed, Ormus, Malah, Anya; same click handler `0x112f30` |

### Adding Median's action lines

Two options, both client-side data edits at load time (the table is on the heap, patch it after the process static-init, e.g. at the first
`0x1147a0` call or when `*(void**)(base+0x2a48830) != 0`):

1. **Edit the record** of the NPC (e.g. Cain 0xf4 / 0x109: Talk, Identify, +up to 3 actions): bump `+4`, write a string id in `+8` (use a plugin-added
   string, the string table id space is the same `tbl` lookup `0x143e2b730`), and put a plugin handler (`bool __fastcall (void)`, shaped like `0x112f30`)
   in `+0x18`. The handler sends the action: `0xec730(0x38, kind, npcUnitId)` with `npcUnitId = *(u32*)0x2a4875c` (current NPC) and kind >= 0x10.
2. **One "More..." line** (Median has 16 slots) whose handler opens a plugin list; avoids the 5-line cap.

### Server handler of a chosen custom line

The packet is `0x38 [kind u32][npc unit id u32]` (9 bytes) handled by **`0x4b0470(Game*, Unit* player, packet*, size = 9)`** (section 3). It finds the NPC
(`0x53b8f0`), its row `0x3971a0`, and branches on `kind`: 1 trade, 2 gamble, 3 hire (anything else is logged and dropped). Hook `0x4b0470`: if
`kind >= 0x10`, run the plugin action for `(player, npc, kind - 0x10)` (the requirements evaluator in `mxl_requirements.h`, then the action: cube
craft, catalyst, etc.) and return; otherwise call the original. The "Talk" line goes through the dialog-message packet and the quest wrappers
(`0x4c33e0`, `0x516940`, section 3), not through `0x38`.

### NPC actions lane (2026-10-21; plugin/src/npc_actions.cpp)

| What | Address | Notes |
|---|---|---|
| Menu builder hook | `0x1147a0` | entry `40 55 53 57 41 54 41 56 48 8d ac 24 10 fc ff ff 48 81 ec f0 04 00 00` (23 bytes, no rip-relative). The loop adds `count - 1` lines; the Identify line (id 0xfb4) overwrites the record's `+4` with 3 or 2 on every build, so lines behind it vanish and a skipped Identify is never retried: the plugin keeps its lines in front of Identify and writes the count back (lines + 1) after the builder returns, so the record shows what the list shows (the lowered count hid the plugin line from the harness `menu list`) and re-sets the count on each call |
| Menu packet hook | `0x4b0470` | entry `40 55 53 56 57 41 54 41 55 48 8d 6c 24 d1 48 81 ec c8 00 00 00` (21 bytes). Packet: `u8 0x38, u32 kind, u32 npc unit id` (9 bytes). The NPC is found with `0x53b8f0(player, unit id, 0x32)` (distance 50), its class is `[unit+4]` |
| Packet sender | `0xec730(u8 id, u32 a, u32 b)` | builds the 9-byte packet; `0xec820` is the 0x2e variant |
| Cancel handler | `0x112c30` | closes the list widget (`0x1e9390`), clears `0x2a486a4`, calls `0x10de80(npc id)` and `0xc7d30(8)`; returns 1 |
| Vanilla respec packet | `0x4b2530` = packet 0x39 (`CCMD_RESPEC`; 0x38 is `CCMD_SUBSCRIBE_TO_VENDOR`) | requires NPC table byte `+5`, and the quest `byte[+0x10] - 1` bit 1; then `0x580f20(game, player, 0)` and, when `+0x10 != 0`, `0x5d9ae0(game, player)` |
| Respec | `0x580f20` | `0x4360f0` (skills: refunds into stat 5, `0x46f220`, `0x474d20`), `0x52ddf0` (stat points back to the charstats start values), `0x470c90` (equipment re-check), `0x2f3760`, `0x474d60`, `0x491960(player, 2, player)` |
| Respec bookkeeping | `0x5d9ae0` | quest 41: sets bit 0, clears bit 1; if bit 0xf is clear the respec quest (a1q1 `+0x12`) is deactivated ("deactivated respec quest") |
| Imbue / sockets / personalize panel | panel 0xd = `ImbueItemsPanel` (`0xc7aa0`) | client opener `0x1e3e20` (mode 1 at `0x2a96960`, then `0x1e5b20`), called by the line handler `0x10dd30` and from the server-to-client message handler `0x1e3c00` (packet 0x58, byte `+5`: 0 open, 4, 5, 6/7 close). Class check `0x10d150` (current NPC class `0x2a48764`): 0x9a Charsi, 0x1ff Larzuk, 0x200 Anya. Item filters (D2Common, client and server): `0x36aed0` imbue, `0x36b410` sockets, `0x36b1d0` personalize |
| Service lines (client) | fix table RVA `0x22a70e0`, 9 x 24 bytes (class u32, quest u32, bit u32, condition u32, function), count dword `0x22a71b8`; consumer `0x1141d0` (the NPC menu opener) | Charsi q3 b1 -> `0x109100` (line `0xfb1`), Larzuk q35 b1 -> `0x109300` (`0x58dc`), Anya q38 b1 -> `0x109400` (`0x58dd`), all with handler `0x10dd30`; Warriv q6 b0 and Meshif q14 b0 add the travel lines. Run on the client's own quest record `0x2a48778` |
| Confirmation page (client) | list widget global `0x2a48798`; closer `0x110670`; creator `0x1e9200(cancel handler, 0, 1)`; line adder `0x1e9030(widget, text, flags, 1, handler, selectable)`; string thunk `0x3e2b730(id)` | D2R's own Yes / No page (its Repair All, `0x110b60` / `0x10d160`): the closer clears the eight list globals (`0x2a487b8`, `c0`, `b0`, `d0`, `98`, `a0`, `a8`, `c8`) and frees their widgets; the creator returns a centred list, byte `+8` = 1 is set by the caller; the header line has flags 4 and no handler, Yes and No are selectable lines (flags 0, handler, selectable 1) with the stock strings `0xd10` (3344) / `0xd11` (3345); `0x2a486a4` = 3 while it is up. The plugin builds it for npcext `PromptConfirm` lines (Akara's respec; `npc_actions.cpp` `OpenConfirm`), its Yes handler closes everything, sends the kind and runs the Cancel handler. `0x110740` (D2R's own No / Escape handler) returns to the vendor panel, so the plugin uses its own. Entries (whole instructions, no rip-relative): `0x110670` `40 53 48 83 ec 20`; `0x1e9200` `48 89 5c 24 08 48 89 6c 24 10 56 57 41 56 48 83 ec 40 41 8b f0 48 8b ea 4c 8b f1`; `0x1e9030` `48 89 5c 24 08 48 89 6c 24 10 56 57 41 56 48 83 ec 20 83 79 1c 0a 41 8b d9 41 8b e8 4c 8b f2`; `0x3e2b730` `ff 25` (D2RCore thunk). Checked in game (`game_checks respec`: click, `menu confirm`, `menu no`, `menu yes`) |
| Service confirmation (server) | packet `0x2e`: `0x4ae280` (21 bytes) -> `0x4fc230(game, player, packet, delayed)`; delayed run from the task `0x4b6050` | NPC `0x53b8f0`, NPC table row `0x3971a0` (`+0xb` service 1/2/3, `+0x10` quest + 1), quest bit 1 via `0x325c50`; spends the reward with `0x5da1c0` / `0x548b60` / `0x547c60` (bit 0 set, bit 1 cleared). Server packet table: handler = `0x1d2a790 + id * 8` (0x38 = `0x4b0470`) |
| Travel | client special line handler `0x1162f0` sends packet 0x37; server `0x4a9880` | NPC table row (static table `0x237ea60`, 0x1c bytes: `+0xb` service, `+0xc` destination s32, `+0x10` gate byte = quest + 1): gated lines test bit 0 of quest `gate - 1`, travel with `0x4f2e40(game, player, level, 0)`, then set the arrival act town's waypoint. D2R grants what Median grants; checked by npc_services.cpp |
| Waypoint record | `0x3d6670(version, level, u16* wp)` level -> waypoint field (levels row `+0xec`, 0xff = none); `0x3d6930(record, wp)` test; `0x3d6890(record, wp)` set (`*(u16*)(rec + 2 * T[wp].word) \|= T[wp].mask`, tables `0x2389010`, 112 entries); `0x4812c0(client, record)` sends packet 0x63 (record to the client, which also opens its waypoint UI); `0x40b540` sets every waypoint | record = `*(playerData + 0x58 + difficulty * 8)`, playerData = `0x34b240(player)`, difficulty = `game + 0x104`, version = `game + 0x106`. Object operate `0x58fe00` is the in-game touch (set, `0x481030` packet 0x64, `0x4812c0`). Entry bytes: `0x3d6890` `48 89 5c 24 08 57 48 83 ec 20 0f b7 da 48 8b f9`, `0x3d6670` `48 89 5c 24 08 48 89 6c 24 18 56 57 41 56 48 83`. Record = 112 bits (count dword `0x23891d0` = 0x70; number n = word `1 + n / 16`, mask `1 << n % 16`); save "WS" writer `0x52f090` / reader `0x52e910` copy 16 bytes of each 24-byte record (`0x3d6820` / `0x3d67c0`). Panel: `0x1ecbc0` loads the actinfo rows into 0x34-byte entries (vector `0x2a96a28`, 9 levels + 9 numbers each), `0x1ea9b0` fills a tab's 9-entry button table `0x2a969e0` (count `0x2a969d4`; entry bytes `40 55 53 56 41 55 41 56 48 8d 6c 24 c9`; mxl-core hooks it, see areas-drlg.md 3b), `0x1e9b40` builds the buttons, tab-unlock quest ids at panel `+0x1c8` (5 ints, set at `0x1e9adf`); use-waypoint server handler `0x4b6f10`. Table readers (each a 7-byte `lea reg,[rip+disp32]`, patched by mxl-core to its own table): `0x1ea198` (builder), `0x1ec05a` (click handler `0x1ebf50`), `0x1ec582` (refresh `0x1ec430`); the row vector is `0x2a96a28` data, `0x2a96a30` size, `0x2a96a38` capacity; buttons are `Act%d_Button%d` clones of `UnselectableButtonTemplate`, y = index * layout `buttonOffset` (default 123) + 264 |

## 10. Gold stat changes and the client

`0x2f7d10(unit, stat, value, layer)` and `0x2f5020` start with a 10-byte `jmp [rip+x]` (the D2RLoader / protection thunk) followed by the real body
(`0x2f7d1a`, sets the stat in the unit's stat list; asserts `0x2f1dc0`, calls `0x2f9b10`, `0x2f3030` and the stat-change path). The stat engine
itself is not in the dump (the thunk target is in `0x3e2a248`): the thunks are not a protection layer but **D2RLoader's own module D2RCore.dll** (see below). Evidence for "no explicit client update needed": the game's own gold
changes do not send anything: the gold pickup code (`PlrModes.cpp`, function `0x42c110`) does `0x2f5020(unit, 14)`, compares with the cap
(`0x2f5c60` family), then `0x2f7d10(unit, 14, newGold)` and **no packet call follows** (its only network calls are the item pickup packet `0x535f60`);
the same `0x2f7d10(unit, 0xe, ...)` is used by item creation for stackable gold (`0x43cd50`, `0x43ef10`). In 1.13c the stat list of a player
has the "send to client" callback installed, which makes the set function emit the 0x1d / 0x1e / 0x1f attribute packets itself. So the post-hook's
payment (`0x2f7d10(player, 14, gold - cost, 0)`, bank `15`) should show up on the client without extra work; **not tested in game**. If a
refresh is ever needed, the cheapest forcing step is to re-set the stat (set 14 to the old value and then to the new one). The stat-update packet
sender itself was not located (no packet-id constant for 0x1d-0x1f near the network service in 102 sender functions; the builder is behind the
stat callback). Confidence: likely.

### D2RCore.dll (lane caps-events, 2026-10-22)

Thirty-nine main-image stat functions (`0x2f5020` GetStat, `0x2f7d10` SetStat, `0x2f5c60`, `0x2f4d20`, `0x2f48c0`, ...) are
10-byte `ff 25 disp32 90 90 90 90` thunks whose slots (`0x3e2a2xx`, filled at start-up) point into **D2RCore.dll**, a PE
that D2RLoader maps at a random `0xc0de5xxxxxx` address (timestamp `0x6ab37824`; sections `.text` 0x1000, `.rdata`
0x53b000, `.data` 0x6fb000, `.d2rlapi` 0x80e000, `.d2rsym` 0x838000). It holds a reimplemented stat engine: the getter body
is at core RVA `0x3d8bd0`, stats live in sorted 16-byte `{key = stat << 32 | layer, value}` entries, stat ids go up to
0x8000. Everything that is *not* one of those 39 thunks is ordinary main-image code and hookable: the resist code
(`0x4523e0`), the damage table (`0x44df10`), the absorb step (`0x450670`). D2RLoader also redirects some call sites to
wrappers in a stub area (`0x3e2b496+`; slot `0x3e2aab0` -> core `0x826720`, which calls the original `0x4523e0` and tracks
damage in state `0xe7` / stat `0x54`); an inline hook on the *callee* still sees every call. Reading the core: attach to
the game process (`ReadProcessMemory`) and dump the module; it is not in `D2RLoader_*_dump.exe`.

## 11. Quest handlers (read)

D2R's quest objects keep the 1.13c private data **inline from `quest+0x20`** (1.13c: a separate block at `quest+0x18`): the Median flag offsets do not
carry over (fields moved: a2q5 uses +0x20/+0x28 (a pointer)/+0x30/+0x31), so keep Median's "once per player" flags in the plugin, keyed by game and player (or
use quest-record bits as in section 2).

| Quest | Event | D2R | Entry bytes | Read / matches | Median's use (1.13c) |
|---|---|---|---|---|---|
| 13 `a2q5` (Summoner) | 8 kill | **`0x5a5490`** | `48 89 5c 24 08 57 48 83 ec 20 80 79 11 00 48 8b` | string "killed summoner for quest"; sets state 2, `quest+0x20 = 1`; same as `0xc66b0` (line-for-line) | Nightmare: drop TC "Quest Cata Learning" (once per player), flag |
| 13 | 0 NPC activate | **`0x5a5360`** | `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 48` | tests quest-13 bits 1 / 0xd, `0x1405184b0` (npc is Drognan?), picks a dialog state | re-issue `0o[ ` |
| 14 `a2q6` (Duriel) | 11 NPC message | **`0x5a66b0`** | `48 89 5c 24 18 48 89 74 24 20 57 48 83 ec 50 48` | NPC `0xc9` = 201 (Jerhyn), message `0x1ba`: `0x325c50(rec, 0xe, 3)`, `0x325c00(rec, 0xe, 4)`, `0x325990(rec, 0xe, 3)`; the same constants as `0xc8050` | Jerhyn gives one Arcane Crystal `qum ` on `0x1ba` |
| 25 `a4q1` (Izual) | 8 kill | **`0x5e67c0`** | `48 89 5c 24 08 48 89 74 24 10 57 48 83 ec 20 48` | string "Finished quest", state 4, sets quest-25 bits 0xd and 1 when 0 and 1 are clear: `0xbabf0` line-for-line | Nightmare: TC "Quest Cata Jewelcraft" once per player |
| 25 | 0 NPC activate | **`0x5e6660`** | `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 48` | NPC class `0x196` (406, Tyrael), bits 0 / 5 / 1 / 0xd of the quest in `quest+0x2f0` | re-issue `jcat` |
| 38 `a5q4` | 2 | **`0x54dd30`** | `48 89 5c 24 08 57 48 83 ec 30 48 8b fa 48 8b d9` | `if NPC class == 0x200 (Anya, 512)`: `if (quest+0xa6) { quest+0x1c = 0; re-arm via 0x517b40; quest+0xa6 = 0 }`, `if (+0xa7 && !+0xa8) 0x550570`. Median's `0x9f960` uses the same fields (data+0x86/+0x88) = quest+0xa6/+0xa8 here (**the +0x20 inline shift holds for this quest**) | re-arm Anya's quest when byte +0x86 is set, keep +0x88 as done |
| 38 | init | `0x548590` | `4c 8b dc 48 81 ec c8 00 00 00 48 8b c1 48 8d 15` | stores event 0 `0x54ddc0`, 2 `0x54dd30`, 3 `0x54dc90`, 8 `0x54df80`, 10 `0x54e070`, 11 `0x54e570`, 13 `0x54e0d0` (the earlier note "init stores by another pattern" was a plain `*(code**)(q+0x270+8n)` store, ordered differently) | |
| 40 `a5q6` (Baal) | 8 kill | **`0x54fa70`** | `48 89 5c 24 20 55 56 57 41 56 41 57 48 81 ec 80` | `0x517db0(game, 0x13)`; reads the killed unit's room; quest-0x28 (40) bit tests; spawns the Baal clone path; same shape as `0x5fe30` | after the vanilla handler: Hell, players in level 132 above level 109 get a relic orb once (bit 0xb of quest 40) |

Acts 2-5 hooks (quests_act2_5.cpp, docs/subsystems/quests-requirements.md section 5c) also use: `0x518220(game, questId)` -> quest object (walks `game+0x21d8`; id 0x1e is
the respec quest object that `0x5d9ae0` switches off with `+0x12 = 0`), `0x490de0(game, 0, arg, callback(game, player, arg))` -> walks the game's
player table (`game+0x2230`, 128 buckets, next at unit `+0x158`, skipping units with state 7 or 0xba) and stops when the callback returns 1, and
handlers a3q3 `0x5ef040` (Ormus 0xff: message 0x24b hand-over, **0x251** with bits 6 set / 8 clear), a3q5 `0x5f0df0` (Cain 0xf5, message **0x272** with
bit 4), a5q2 `0x54c810` (Qual-Kehk 0x203, message **0x4e8e** with bit 1; pays out the rune table `0x23a02c0` = `r07 r08 r09`, count 3 / 2 with bit 6 / 1 with bit 7).
The quest-bit helpers in these handlers are the section 2 ones (`0x325c50` test, `0x325c00` set, `0x325990` clear). Quest 40 in D2R keeps vanilla
bit 0xb unused as far as read; the plugin can set it itself.

## 12. Monster AI dispatch (lane monster-ai, 2026-10-21; docs/subsystems/monsters-ai.md)

Read in the analysed Ghidra project (`Decompile.java` of the functions below; all 169 think functions of the table were decompiled for comparison)
plus `d2r_find.py`; nothing hooked. Compared with D2Sigma `D2AI.cpp` (table at `0x101d8480`, stride 0x10) and 1.13c D2Game's AI table.

**Getter `0x4a36c0 (unit, mode)`** (entry bytes `48 89 74 24 20 57 48 83 ec 30 48 89 5c 24 40 33`; `.pdata` splits it into a 0xa-byte stub and a body):
```
monstats = **(unit + 0x10)                 // unit type 1 only (asserts otherwise)
mode == 0 (after a mode 10-12 state test):  ai = u16 monstats[+0x52]
                                            return (0 <= ai < 0x9b) ? 0x2396e90 + ai*0x20 : 0x2396e90   // out of range = "None"
mode != 0:                                  return 0x23981f0 + mode*0x20
```
So a monai row at index 155 or higher (Median's `andariel_ai` as txt_migrate appends it) runs entry 0, whose think function `0x78d20` is a bare `ret`. `plugin/src/monster_ai.cpp` detours the getter (entry bytes above, 15 bytes = 4 whole instructions) and, when it returns entry 0 for a monster whose `+0x52` is 155, returns its own `{1, 0, think, 0}` entry. Init (`+8`) is `init(game, unit, args)` with `ctl = *args`; entry 83 (MosquitoNest) gets one written by the plugin (`0x23978f8`).
The tables are plain `.data` pointers; entries 0-154 line up one to one with `monai.txt` rows 0-154 (checked by name: Idle 1, Summoner 53,
Hireable 61, FetishShaman 65, MosquitoNest 83, Nihlathak 128, ColBarbFrenzy 154) and the table ends exactly where the mode table begins
(`0x2396e90 + 0x9b * 0x20 = 0x23981f0`), so it cannot grow in place.

**Entry layout** (0x20 bytes, absolute VAs): `+0` u32 kind (0 = no target search, NPCs; 1 and 3 = hostile target search; 2 = ally/minion
target search `0x595750`; 5 and 6 = command-mode search `0x4a6760`; chosen by a `switch` in `0x4a2a00`), `+8` init (called once when the AI is set,
by `0x4a2690`), `+0x10` think `(game, unit, args*)`, `+0x18` alt think (used instead of `think` when the AI is set again while `think` is already the
active handler). D2Sigma's entry is `{think, alt, kind, init}` (16 bytes); D2Sigma `D2AI.cpp` 0x4a280 sits in the alt slot and 0x4a110 in the init slot.

**Per-state prelude** at `0x2396e78` (state 0) and `0x2396e88` (state 1): two pointers (`0x5d7e10`, `0x5d7b60`) called before the handler by `0x4a2690` and `0x4a2a00`.

**Think arguments** (`args*`, 0x40 bytes; Sigma's fields are 4 bytes at half the offsets): `+0` ctl (the monster's AI control: three scratch ints at
`ctl+0x44/+0x48/+0x4c`, zeroed whenever the AI is set), `+0x10` target unit, `+0x20` i32 distance to the target, `+0x24` i32 "in reach" flag,
`+0x28` the monstats row, `+0x38` u8 difficulty (0-2).

**monstats row fields the AI functions read** (D2R, from `0x5b4d50` and `0x5aba70`): `+0x52` u16 AI id; `aip1..aip8` as u16 at `0x90 + 6*(n-1) + 2*difficulty`
(Sigma `0x56 + ...`); `Skill1..5` u16 at `0x1c4`, `0x1c6`, `0x1c8`, `0x1ca`, `0x1cc` (Sigma `0x170`...); `Sk1mode..5` u8 at `0x1d4`..`0x1d8` (Sigma `0x180`...).
Game frame `game+0x170` (Sigma `+0xa8`). Random: seed pointer `0x34a1e0(unit)` (= `unit+0x28`), `s = lo*0x6ac690c5 + hi`, roll = `(u32)s % 100`.

**Helpers** (D2R, matched to D2Sigma `D2AI.cpp` by structure):

| D2R | Signature | D2Sigma twin |
|---|---|---|
| `0x4a6d10` | wait `(game, unit, frames)`, 0 frames = 1 | `0x4b270` (D2AI.cpp:0xb4) |
| `0x4a7bc0` | use skill `(game, unit, u8 mode (< 0x10), skill id, target unit, x, y, flag)`; refused -> waits 10 | `0x4b310` (:0x116) |
| `0x4a7df0` | move away / flee `(game, unit, target, u8 mode, n)` | Sigma thunk `0x422e0` |
| `0x4a78e0` | set a mode action `(game, unit, mode, target)`: mode 4 = attack, 8 = the S1 "charge" (D2R's AIs call it with 8 at `0x5ae373`) | Sigma thunks `0x422c0` / `0x422e0` |
| `0x595f80` | nearest suitable target `(game, unit, int* outDistance, u32* aux) -> Unit*` (`outDistance` = `0x7fffffff` when none; `aux` 0 is fine; verified in the Summoner and in `andariel_ai`'s port) | Sigma `0x41c50` (`(unit-in-eax) (&distance, 0)`) |
| `0x4a7270` / `0x4a8740` | walk towards a target: `0x4a7270(unit, 1, 0, 0)` then `0x4a8740(game, unit, target, 7)` (D2R's Andariel think ends with exactly this) | Sigma `0x4b110` `AiMove(.., target, 2, 0, 0, 1, 7)` |
| `0x5a0b80` | Summoner AI init (Act 2 quest 5 hook, `Quests\a2q5.cpp`) | Sigma `0x41c70` |
| `0x4a3680` | the **Idle** think: `if room: wait(200)` | `0x4a210`: `wait(250)` |
| `0x5af320` | alt think of Hireable, FetishShaman, Nihlathak, mode 4: clear state 0xc, AiSet, wait(1) | `0x4a280`, identical |

Entry bytes (16): `0x4a2690` `48 85 c9 0f 84 8a 02 00 00 55 53 56 57 41 55 48`; `0x4a2a00` `48 89 54 24 10 48 89 4c 24 08 55 41 56 41 57 48`;
`0x4a6d10` `48 89 5c 24 08 48 89 74 24 10 57 48 83 ec 70 45`; `0x4a7bc0` `48 89 6c 24 10 48 89 74 24 20 57 48 83 ec 50 41`;
`0x595f80` `4c 8b dc 53 41 54 41 55 41 56 41 57 48 81 ec 50`; `0x4a3680` `48 89 5c 24 08 57 48 83 ec 20 48 8b f9 48 8b da`;
`0x5b4d50` (Summoner) `48 89 5c 24 08 55 56 57 41 54 41 55 41 56 41 57`; `0x5aba70` (Andariel) `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 48`.

## 13. Server -> client text messages (lane client-ui, 2026-10-22; plugin/src/client_messages.cpp)

Ready-made path, called not hooked, verified in game (slot 2, background mode):
- `0x48fde0(player unit)` -> the player's client (null for a non-player). Entry bytes `40 53 48 83 ec 20 48 8b d9 48 85 c9 74 1e e8`.
- `0x477a30(client, record)`: trims the 0x147-byte chat record (name <= 60, text <= 255) and writes **packet 0x26** to that client.
  Entry bytes `48 89 5c 24 18 55 56 57 41 56 41 57 48 81 ec`. The D2Game builder `0x53acf0` (SUnitMsg) uses the same two calls.
- Record: `+0 0x26`, `+1 chat type`, `+2 language`, `+3 speaker unit type`, `+4 speaker unit id`, `+8 colour`, `+9 name flag`,
  `+0x0a name[0x3d]`, `+0x47 text[0xff]`. Layout and builder: `clientmsg::BuildChat` (client_messages_logic.h, unit-tested).
- The client reads it in `0x12c190` (table `0x22bbc40`, 24-byte entries `{handler, size, 0}`; id 0x26).
- **Chat types seen on screen** (harness verb `sysmsg <type> <colour> <text>`): 4 = a line in the message log at the bottom left
  coloured by the colour byte (used for every notice); 1 = the same; 5 = overhead bubble above the player; 0, 2, 3, 6-9 show nothing.
  Colours (byte +8): 0 white, 1 red, 2 green, 3 blue, 4 tan, 8 orange, 9 yellow. Inline `Ã¿c1` colour codes are not interpreted.
- **A chat line during an NPC's speech freezes the speech** (found 2026-10-22, regression hunt `respec` on 0.49.0): while Akara's
  quest text scrolls (about 40 s with the Den of Evil and Cain speeches), any packet 0x26 of type 1, 4 or 5 stops it for good and the
  NPC menu never opens (the builder 0x1147a0 is never called, the subtitle box stays up). Type 0 (shows nothing) does not; a line
  that arrives with the menu already open does not either; the speaker fields and the delay (12 server frames) made no difference.
  The speech ends when the client's menu-open flag (`0x2a486a4`, u32, 1 while the menu is up) turns 1. So the notices of quest
  dialog handlers (the Heart is sent from the handler that the speech's own message 0x76 fires, in the middle of the speech) go
  through `SendClientNotice`: held until that flag is 1 for 2 server frames, sent anyway after 120 s. Lockout and goblin lines
  stay immediate (no NPC speech there). Limit: the flag is the local client's; a remote player of a TCP game gets the line after
  the 120 s fallback.
- Used for: Median's dungeon lockout texts (refusal "(Required Level: N)", "Requires Hell difficulty", "This area is locked / Join
  another game to enter again", clock "Closing in: mm:ss" and "ONCE YOU EXIT YOU CANNOT GO BACK" to every player of the game),
  the quest reward notices (Akara's Heart, Jerhyn / Cain crystals, Ormus shrines) and the goblin line ("Treasure Goblin appears!": Median's push notification is the unit name + string 12320 " appears!"). All shown in
  the screenshots of the lane report. The plugin counts messages sent / failed on the `mxl` command.
- Not used: the client packet table also has 0x5a (34 bytes, builder `0x5282b0(unit,type)`, sender `0x480510`; Median's goblin notice
  is type 0x15) and unit message `0x491960(player,msg,subject)` (0x14 = D2R's generic "Impossible." line; Median's 0x13 and 0x88
  have no D2R handler). Several client handlers sit behind protected thunks (`0x3e2b7xx`), so they cannot be read statically.
- **Plugin messages (lane approx-items, 2026-10-22; client_messages.cpp / client_messages_logic.h): a hidden server -> client
  data channel.** No NetworkService is needed: a chat packet 0x26 of type 0 (shows nothing, does not freeze an NPC's speech)
  whose text is the marker `\x01MXL`, one kind letter and the payload as lower-case hex (up to 125 bytes). The client's
  packet-table entry for 0x26 (table `0x22bbc40`, 24-byte entries, original handler `0x12c190`; the entry bytes of the handler
  are checked: `48 89 5c 24 10 48 89 74 24 18 57 48 81 ec 90`) is replaced by a plugin function that reads the text, hands a
  message that starts with the marker to the handler registered for the kind letter and passes every other chat packet to the
  original. Kinds: `N` = an NPC page answer (npc_actions.cpp: u32 page kind, u16 NPC class, u16 mask of open entries), `T` = the
  dungeon clock (dungeon_lockout.cpp: u16 level, u16 0, u32 ms left, 0 = no clock). Off word `clientmsg` switches it off with the
  rest of the module.
- **Dungeon countdown** (dungeon_lockout.cpp): the server sends `T` to everybody when a clock starts and to a player who enters a
  level (level + ms left; a level without a clock sends 0, which clears the old one). The client keeps the end tick and draws
  "Closing in: mm:ss" (string 11191) and "ONCE YOU EXIT YOU CANNOT GO BACK" (11193) with D2RLoader's OverlayService text calls from a
  frame callback (phase AfterGameUi), centred at the top of the screen, while the local player's level
  (`0x9a480(*(u32*)(image + 0x2a23704))` = the local player's unit, `0x34b440` its room, `0x2efc10` the room's level) equals the
  clock's level. The chat lines of 3a stay.

## 14. Player actions (lane harness-cast, 2026-10-22; plugin/src/harness_cmds.cpp)

Server side, called from the game-frame hook (verified in the game):

| What | RVA | Notes |
|---|---|---|
| walk / run packet handlers | table `0x1d2a790` ids 1 / 3 | 210 byte packets: `{id, curX u16, curY u16, destX u16, destY u16, pathLen byte ...}`; checks `0x34c2c0` (dead), `0x4fe1f0` (position within a tolerance of the packet's), `0x325370` (path distance <= 15) |
| player move | `0x42d2c0` | `(game, unit, Skill* or 0, mode, x, y, 0, 0)`: mode 2 walk, 3 run, returns 0 on success; what the walk packet ends in, the server finds the path |
| cast at a position / at a unit | `0x4fdb40(game, player, x, y, 1, Skill*)` / `0x4f8de0(game, player, type, id, Skill*, 1, shift)` | both use the player's active left skill; the unit form walks into range first |
| skill by id | `0x33dcd0(player, id, -1)` | `Skill*`: `+0` row pointer (i16 id), `+8` next, `+0x10` skill mode (7 attack, 10 cast, 11 / 15 passive), `+0x40` base level |
| skill list, usability | `0x34b6e0(unit)`, `0x33f360(unit, Skill*)` | list head with the first `Skill*` at `+0`; usability 0 ok, 2 passive / requirements, 5 no weapon |
| active skills | `0x34a540` (left), `0x34b400` (right) | select with packet 0x3c (handler `0x4b4250`: `{0x3c, id u16, ...}`, byte 4 = 0x80 for the left skill) |
| add a skill level | `0x438670(version, player, id)` | spends one point of stat 5, no prerequisite check |
| equip | `0x471500` place, `0x382df0(int32 loc[4])` body location 1-12 | location struct `{mode 1 = equipped, page, x\|y, bodyloc}`; `0x471e90` is the generic move |
| missiles | unit type 3 in the game's hash table base `0x646` | counted per server frame |
| player busy | `0x4249f0(unit)` | nonzero blocks skill use (item on the cursor, trade) |

## 15. Monster looks (lane sigma-behaviours-b, 2026-10-22; plugin/src/monster_looks.cpp)

Data: monstats3 (`mxl_monster_looks.h`, 1803 rows by D2R monster id). All entry bytes verified against the 93847 dump; whole
instructions, no rip-relative.

| What | RVA | Signature | Entry bytes | Use |
|---|---|---|---|---|
| hover name builder | `0xcea50` | (unit, a2, a3) | `48 89 5c 24 18 55 56 57` | stash the unit; 0x1634 bytes long |
| colour index -> rgba | `0x908690` | (&rgba, index, mode) | `40 53 57 48 83 ec 38` | mode 5 from inside 0xcea50: swap the index (0 white, 3 champion, 4 unique, 1 corpse, 0x1d possessed) |
| automap unit classifier | `0xd78f0` | (unit, &marker, &nameType) -> drawn | `40 53 56 57 48 83 ec 60` | flagged monsters: marker 6 (NPC), name type 4 / -1, return 1 |
| automap unit drawing | `0xd76e0` | (unit, ctx) | `48 89 6c 24 10 57 48 83 ec 40` | stash the unit |
| automap name drawing | `0xd6b20` | (text, pos, scale, colour index) | `4c 8b dc 55 53` | index 4 -> `AutomapNameColor` |
| automap marker sprite | `0xd6db0` | | | draws a sprite frame, no tint: `AutomapVectorColor` cannot be applied |
| monster creation | `0x493cc0` | (params) -> unit, 0 or not a unit | `48 89 5c 24 10 48 89 74 24 18 48 89 7c 24 20` | after it returns, `SetUnitOverlay` for the row's pair |
| `SetUnitOverlay` | `0x349020` | (unit, overlay row, 0) | not hooked | sets stat 0xb2; the client plays it at the next unit refresh (packet 0x11) |

Monster data (`unit+0x10`) u16 at `+0x1a`: 0x2 super unique, 0x4 champion, 0x8 unique. Unit mode `+0xc`: 0 death, 12 dead.
The creation function's callers do not all get a unit back (a value of 1 was seen), so the result is only read when it is a
pointer; reading it unguarded killed the game on the first area change. The skill monster spawn `0x556560` is not the
generic spawn (it is the do-function of a skill).

## 16. Player death, corpse, penalties and respawn (lane no-corpse, 2026-10-22; docs/subsystems/death.md, plugin/src/no_corpse.cpp)

Found by matching Median's two NOPs in D2Game (D2Sigma table records RVA `0x79790` and `0x79ed6`) to the D2R functions with the same
callers and assert strings (`D2Game\src\Player\PlrModes.cpp`, `Player.cpp`, `PlrMsg.cpp`).

| What | Address | Signature | Entry bytes (build 93847) | Notes |
|---|---|---|---|---|
| Corpse creator | `0x42c110` | `void (Game*, Unit* player, int x, int y, room)` | `40 55 53 56 57 41 54 41 55 41 56 41 57 48 8d ac 24 18 f9 ff ff 48 81 ec e8 07 00 00` (28 bytes) | = 1.13c `0x6fc99210`: builds the corpse unit, moves every body-location item onto it, drops gold. Callers `0x42a689` (in `0x42a5e0`, Dead mode 0x11 enter) and `0x42e24e` (in `0x42de40`, mode-change dispatcher, mode 0 branch). Return unused. mxl-core replaces it by a no-op |
| Death penalty | `0x424ac0` | `u64 (Game*, Unit* victim, Unit* killer)` | `40 53 56 57 48 83 ec 40 49 8b d8 48 8b f2 48 8b f9` (17 bytes; the `call` at +0x11 is rip-relative) | = 1.13c `0x6fc583a0`: calls the gold penalty `0x425cb0`, then (level > 1, killer a monster or a foreign player) lowers stat 13 by `(exp[level] - exp[level-1]) * pct / 100` (clamped at `exp[level-1]`), `0x486260` records the amount, `0x2f7d10(unit, 13, ..)` writes it. One caller: `0x42a441` in `0x429d10` (Death mode 0 enter). mxl-core replaces it by `return 0` |
| Gold penalty | `0x425cb0` | `(Game*, Unit* victim, ...)` | `48 89 5c 24 10 55 56 57 41 54 41 55 41 56 41 57` | = 1.13c `0x6fc58180`; reached only through `0x424ac0`. Not hooked (the call above is) |
| Gold drop helper | `0x424d90` | | | shared with other drops, not hooked |
| Respawn request | `0x4b6160` | `int (Game*, Unit* player, packet, int)` | `40 55 41 55 41 56 48 8d 6c 24 b9 48 81 ec b0 00 00 00` (18 bytes; the next instruction is rip-relative) | = 1.13c `0x6fcf14b0`, client packet `0x41`. Unit mode (`0x34ab60`) must be `0x11`; Hardcore branch tests `[client + 0x5658] & 0x800` (log at `0xa21be0`, returns 1); normal branch: reads max life / mana / stamina (`0x2f4d20`, `0x2f4e20`, `0x2f4f20`), sets stats 6, 8, 10 (`0x2f7d10`), notifies the client (`0x4f3ad0`), moves the character to the act's town (`0x42d2c0`), clears state `0x36` (`0x3354c0`), returns 0. mxl-core's `respawnwait` hooks it |
| Level entry (places stored corpses) | `0x485350` | `void (client, player, game, room, x, y)` | `see plugin/src/no_corpse.cpp EnterEntry` (21 bytes) | walks the player's corpse list (inventory from `0x34a360`, list head at inventory `+0x50`, nodes `{+0 flag, +4 id, +0x10 next}`) and creates every stored body in the room (`0x4245c0`) on every level entry and every respawn. Hooked by part `corpsepickup`: original first, then the pickup below |
| Corpse pickup | `0x42b220` | `void (out, game, player, corpse)` | | the interact handler's (`0x4b2be0`) pickup: body-location items back to the player, a taken place sends the item to the inventory; `out` = `{i64 remaining; u8 ok}` |
| Corpse removal | `0x389730` (list remove), `0x2ef4d0` (room remove), `0x476fc0` (clients, packet `0x8e`), `0x348b00` (clear collision mask), `0x48faa0` (free unit) | | | the sequence the interact handler runs after a pickup that left nothing behind; reproduced by `PickUpCorpse` in no_corpse.cpp. Helpers: unit by id `0x48fe80`, unit room `0x34b440`, inventory `0x34a360`, first / next item `0x388c10` / `0x38aba0`, first corpse entry `0x388780` |
| Client unit table | `0x2a23910` + type * `0x400` | 128 buckets of unit pointers, chain at unit `+0x158`, id `+8`, type `+0` | | lookup `0x9a5d0` (id, type); harness `ccorpses` walks type 0 |
| Game frame | `game + 0x170` | u32 | | server frame, 25 per second (harness `state` frame=) |
| Player units | `game + 0x446 * 8 + (id & 0x7f) * 8` | hash table | | type 0 units (the table before monsters `0x4c6`); a D2 corpse is a second player unit in mode `0x11` |

Level / experience stats: 12 / 13; gold 14, bank 15, `0xaf` gold lost (written by the penalty). The mode table entries for the player are
unchanged by the port.

## 17. Skill cooldowns (lane pa-cooldowns, 2026-10-22; plugin/src/cooldowns.cpp)

Median's rules (D2Sigma, read from the disassembly; audit item 4 in sigma-patch-audit.md): delay `0x100b0f40` = the skill's delay formula - stat 309 at layer = skill id
(unit total, only when not 0); start `0x100b1140` = player units only and delay > 0, end frame (now + delay) stored in the unit's extension
(`unit + 0xf4`) at `ext[+8][group]` when skills2 byte `+0x2c` (CooldownGroup) is not 0, else `ext[+4][skill]`, and client packet `0x2b`; ready test
`0x100b0ab0` = `now >= timer`, non-players always ready. The plugin passes on no start for a non-player (checked in game: the harness's monster skill use does not reach `0x439500` at all, with or without the hook). Median patch sites: D2Client `0xa2e06`, D2Common `0x52279` and `0x52462` (stub `0x1009b7f0`), D2Game `0xa09d5` /
`0xa1aed` (stub `0x1009bc90`).

| What | Address | Signature | Entry bytes (build 93847) | Notes |
|---|---|---|---|---|
| Server cooldown start | `0x439500` | `void (Game*, Unit*, int delay, int skillId)` | `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 57 48 83 ec 40` (20 bytes) | sets state `0xb9` with stat 359 (skill_cooldown) at layer = skill id, value = end frame (`game + 0x170` + delay), via `0x339e60`; D2R's ready test (`0x33f360`, usable code 1) treats stat 359 > 0 at the skill's layer as not ready. Hooked |
| Client cooldown start | `0x217b90` | `void (Unit*, int delay, int skill)` | `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 57 48 83 ec 20` (20 bytes) | time in ms = delay * 40; callers `0x2170d4`, `0x21604c`. Hooked |
| Delay evaluation | `0x3b5160` | `(dataFlag, Unit*, calc, skill, level)` | | skill record `+0x234` = globaldelay calc, `+0x238` = localdelay calc. Not hooked |
| Unit-wide delay state | `0x439470` | | | state `0x79` (Werewolf / Werebear); untouched, Median has no twin |
| Stat getter | `0x2f5020` | `int (Unit*, stat, layer)` | | used for stat 309 |
| Game frame | `game + 0x170` | u32 | | server frame, 25 per second |

Design: D2R has one timer per skill, Median one per group, so a hooked start for a player starts the timer of every member of the group
(`cooldowns_logic.h` StartList, proved equal to Median's bookkeeping by `cooldown_tests`). The group table comes from skills2 `CooldownGroup` through
`txt_migrate cooldown_tables`. Skill ids >= 357 are renumbered +72 from Median. Non-player units go straight to D2R's start.

## 18. Travel: waypoint auto-activation, map reveal, hotkeys, stash pages (lane gap-travel, 2026-10-22; plugin/src/travel.cpp)

How Median does it (D2Sigma.dll 1.13c, 32-bit, RVAs of the dump in `ghidra\D2Sigma.dll`):

| What | Median | Port |
|---|---|---|
| Waypoint activation | `D2AutoPickup.cpp` `0x4c7e0`, called after a walk order from `0xada40`: gold and waypoint objects are used when the distance to the unit is `< 0x24` (36 sub-tiles); the waypoint branch tests the player's record with `0xbffa0` and sets the bit when it is not known. A proximity rule after a walk, not "entering the area" | server scan, every 5th frame, `< 36` |
| Hotkey table | `0x1d9110 + 15 * index`: X (`0x68cf0`, toggles the no-pickup flag `*[0x101f1058]`), C (`0x69820`, transmute while the cube panel is open), R (`0x887c0`, reveals the whole act once per game: it walks every level of the act and calls the level initialiser) | InputService actions `mxl_pickup_toggle` (default X), `mxl_map_reveal` (default L), `mxl_transmute` (default K). The key codes are not in the table (names and handlers only): Median keeps them in the player's `preferences.json` (`hotkey_nopickup`, `hotkey_revealmap`, `hotkey_transmute`); on the test machine nopickup = 0x58 (X) and revealmap = 0x4c (L), transmute = 0x56 (V). D2R's own bindings (the character's `.key` file) use R (action 35, run / walk) and C (action 1, Character screen) and V (action 45), and leave X, L and K free, so the first port's defaults R and C pressed two actions and V would too; K is the free key nearest to Median's own |
| Stash pages | stash panel `0x113cf0` (`StashPanel:MainPanel`), page text `0x1130a0` prints `n / 10` in both modes (constant 10); buttons Prev / Next wrap modulo the page count, Sort and Mode | `add_shared_tabs = 7` in `d2rloader.toml` (3 normal tabs + 7 = 10) |

D2R side (RVA = address - `0x140000000`, build 93847; all first bytes read from the dump, plugin checks them with `memcmp` before calling; nothing here is hooked):

| What | RVA | Signature | Entry bytes | Use |
|---|---|---|---|---|
| waypoint set / test | `0x3d6890` / `0x3d6930` | (record, number u16) / -> nonzero | `48 89 5c 24 08 57 48 83 ec 20 0f b7 da 48 8b f9` (both) | the 112-bit record of section 11; the plugin sets the bit the way the object's operate function `0x58fe00` does |
| player data / room / level | `0x34b240` / `0x34b440` / `0x2efc10` | (unit) / (unit) / (room) | not hooked | record = `data + 0x58 + difficulty * 8`; the level of a player or object = `0x2efc10(0x34b440(unit))` |
| debug "Reveal Automap" | `0xd42b0` | () | `48 83 ec 58 48 8d 4c 24 20 48 c7 44 24 20 01 00` | breadth-first walk over the rooms joined to the player's room, visitor `0xd2240` adds each room's tiles and preset objects to the automap layer; then it flips the debug flag byte `0x2a2add4`, which the plugin writes back |
| automap layers | list head `0x2a2cf60` (next at `+0xa8`), current `0x2a2cf68` (first int = layer number) | | | cell count of a layer = sum of the four element counts at `+0x28 / 0x50 / 0x78 / 0xa0` |
| cube panel Transmute | `0x2cd720` | () | `4c 8b dc 55 53 48 8d 6c 24 88 48 81 ec 78 01 00` | the panel's own button handler: gathers the cube items and sends packet 0x20 (server `0x4c1590` -> `0x4f2490`) |
| local player | `0x8b2d0` / `0x9a480` | () -> id / (id) -> client unit or null | `8b 05 2e 84 99 02 c3` / `48 89 5c 24 08 57 48 83 ec 20 83 f9 08` | the reveal and transmute run on the UI thread only when this finds a player |

Waypoint object classes (`objects.txt` OperateFn 23, the same 16 rows in Median and vanilla): 119 145 156 157 237 238 288 323 324 398 402 429 494 496 511 539; waypoint numbers from `mxl_waypoints.h` (levels.txt Waypoint column).

Checked in game (slot 1, 2026-10-22, `py -3 tools/game_checks.py --slot 1 all mapreveal wpauto hotkeys stashpages`): the waypoint of Cold Plains (number 1) is set within 1.5 s when its bit is cleared at distance 3, stays clear at distance 47, and a `move` to it sets it at distance 25; the reveal call returns, the automap layer list grows from 1 to 25 layers (the act's levels), a second reveal adds nothing and the debug flag is as it was (the cell count stays 8878: `cheat goto` and the town arrive with the automap already drawn whole, so no picture shows the difference; an earlier run that sampled a Cold Plains still streaming in saw 965 -> 8663 cells, which is the streaming, not proof); X / R / C pressed as window messages reach the actions (X toggles, R reveals, C with the cube closed is counted and ignored); an item created through ItemService lands in shared stash tabs 0-9 and tab 10 is refused.

## 19. Client skill function tables (lane p4-stability, 2026-10-24; plugin/src/sigma_skills.cpp)

| Name | RVA | Notes |
|---|---|---|
| client start table (`cltstfunc`) | `0x235f590` | 55 slots (the bound is read from `0x235f7c0`), read by the skill start function `0x218030` at `skill record +0x148`; null = nothing runs |
| slot 18 | `0x2b0df0` | draws the skill's `cltmissilec` (record `+0x144`) at the caster; asserts `nMissile >= 0 && nMissile < NumMissileStats` twice and returns 1 for a row without one (52 Median rows, e.g. the curses Amplify Damage 66, Terror 77, Lower Resist 91 and monster skills; the treasure goblin's spawn raised it in the old trace); wrapped in place by `CltStMissileC` (plugin 0.64.0) |
| client do table (`cltdofunc`) | `0x235f7d0` | 130 slots; slot 30 = `0x2b05d0` (curse, wrapped by `CltDoCurse`), 31 = `0x2b0ac0`, 32 = `0x2b0180`, 33 = `0x2b0800` |
| `UnitTranslationLayer` event handler, type 0x10 | `0x775fc0` (loop `0x77a3b0`) | D2R's own; the crash `D2R.exe+0x7761DC` of docs/bugs.md #34 reads `[[event]+0x70]+0x870` |

## Appendix A. Quest descriptor table (D2R, verified)

`0x239c5c0`, 36 entries of 0x20 bytes: `+0` init function VA, `+8` u32 act (0-4), `+0xc` u32 (`0x64` or 0), `+0x10`
u32 flag, `+0x14` u32 ordinal in the act, **`+0x18` u32 quest id**. Ids: act 1 `1-6` and `41` (init `0x5db880`,
shared with id 29), act 2 `8-14, 30, 31`, act 3 `16-22, 32`, act 4 `24-27, 33`, act 5 `35-40`. Quest id N to source
file: act 1 `a1qN`, act 2 `a2q(N-8)`, act 3 `a3q(N-16)`, act 4 `a4q(N-24)`, act 5 `a5q(N-34)` (checked from the strings
each init's handlers reference). So Median's hooked quests are: 4 `a1q4`, 5 `a1q5`, 6 `a1q6`, 13 `a2q5`, 14 `a2q6`,
19 `a3q3`, 21 `a3q5`, 25 `a4q1`, 36 `a5q2`, 38 `a5q4`, 40 `a5q6`.

`py -3 tools/d2r_find.py qinit <id|all>` lists the handlers an init stores; results for the Median-hooked quests
(event 0 = NPC activate, 8 = kill, 11 = NPC message; entry bytes in the tool output):

| Quest | Init | event 0 | event 8 | event 11 | Confirmed by |
|---|---|---|---|---|---|
| 4 | `0x5db310` | `0x5dfe90` | `0x5e29d0` | `0x5e0830` | NPC 0x94, msgs 0x61/0x70/0x76/0x7d, same as 1.13c `0x66ce0` |
| 6 | `0x5db6c0` | `0x5e1d30` | `0x5e1f00` | `0x5e2660` | quest-6 bit tests, drop sequence = 1.13c `0x67e00` |
| 13 | `0x59f8f0` | `0x5a5360` | `0x5a5490` | `0x5a5920` | init only |
| 14 | `0x59f9f0` | `0x5a5d40` | (none) | `0x5a66b0` | init only |
| 19 | `0x5ea880` | `0x5ee920` | | `0x5ef040` | constants 0x251, 0xff (Ormus), 0x60 |
| 21 | `0x5eaad0` | `0x5f05d0` | `0x5f06f0` | `0x5f0df0` | constant 0x272 (Cain, act 3) |
| 25 | `0x5e4c20` | `0x5e6660` | `0x5e67c0` | `0x5e6d70` | init only |
| 36 | `0x548220` | `0x54c090` | `0x54c1e0` | `0x54c810` | constant 0x203 (Qual-Kehk) |
| 38 | `0x548590` | | | | init stores by another pattern, not listed |
| 40 | `0x5487f0` | `0x54f800` | `0x54fa70` | `0x550450` | init only |

## Appendix B. Median's D2Game patch table (1.13c call sites that need a D2R analog)

D2Sigma's loader patches D2Game from a table of 520 records at D2Sigma VA `0x101712f0` (five dwords: D2Game RVA, 0,
value, flag, 8). 285 records have flag 0 (a 32-bit constant or table pointer written into code: bounds, table
addresses, `0x90909090` nops, `0xe8`/`0xe9` opcode bytes); 235 have flag 1 (the rel32 of a call/jmp redirected to a
D2Sigma function). These are exactly the places where Median changes 1.13c behaviour. The grouped table is below, by
target; use `tools/ghidra_scripts/SiteFuncs.java` on the D2Game copy to name the 1.13c function around a site. Cases
already mapped: `0x7242a` / `0x72418` / `0x72421` = the cube output dispatch (section 1); `0x348a4..0x35349` and the
`0x101dd0e8/0f8/0fc` constants = the quest descriptor table (Appendix A: D2R has one table, patch nothing, hook the
handlers); `0x2e15a` = the end of the game frame function (the goblin / D2GS tick).

| Sigma target (VA) | D2Game patch sites (1.13c RVAs of the rel32 operand of a call/jmp) |
|---|---|
| `0x1004b560` | 2: 0x79f91 0xdef8b |
| `0x100573a0` | 1: 0xdb7b4 |
| `0x10057930` | 17: 0xdb98 0x760b8 0x7625e 0x76965 0x7cb77 0x7cbe6 0x7d3de 0x7f5d9 0x97891 0xa2f77 ... |
| `0x10057f50` | 4: 0xa10f1 0xdb7a0 0xdb7c2 0xdb846 |
| `0x10057f70` | 1: 0xdbd79 |
| `0x10057f80` | 3: 0x9a300 0xdc7cd 0xddb74 |
| `0x10057f90` | 1: 0xdc180 |
| `0x1005a840` | 1: 0x734f2 |
| `0x1005c780` | 21: 0x3afd9 0x42c20 0x430be 0x43370 0x4f23d 0x4f434 0x4f4b8 0x75664 0x92927 0x95543 ... |
| `0x1005ca30` | 1: 0x4b2ee |
| `0x1005ca50` | 1: 0x4b292 |
| `0x1005e900` | 1: 0xdc076 |
| `0x1005e910` | 1: 0xde8f1 |
| `0x10064dd0` | 1: 0xed30e |
| `0x100664a0` | 1: 0x2e15a |
| `0x10066900` | 1: 0xcedb8 |
| `0x10066c10` | 4: 0x49191 0x55d51 0xdddb0 0xedaef |
| `0x10067450` | 3: 0x97593 0x981f5 0xc0f0e |
| `0x10067910` | 5: 0x4919a 0x55de0 0xc0d9a 0xdddb9 0xedcf0 |
| `0x10067920` | 2: 0xd0d1a 0xd0d1a |
| `0x1006aff0` | 3: 0x79de4 0xd0902 0xd093d |
| `0x1007e3b0` | 1: 0x10c88 |
| `0x1007e7d0` | 2: 0x11e8f 0x4ee05 |
| `0x1008a910` | 1: 0x6f63e |
| `0x1008f880` | 1: 0xaf841 |
| `0x1008f8a0` | 1: 0xaccf5 |
| `0x100931e0` | 2: 0xce48e 0xce4a0 |
| `0x10093200` | 2: 0xcd4ce 0xcd4e0 |
| `0x100936f0` | 3: 0xbd20d 0xbd3ce 0xbf7f2 |
| `0x10093710` | 2: 0x2c4a4 0x2c7ac |
| `0x10093a30` | 3: 0xbf71f 0xbf7bf 0xbf8a0 |
| `0x10093e40` | 23: 0x8f638 0x8f715 0x8f7d4 0x8f82d 0x8f83d 0x8fab3 0x8fb0d 0x9029a 0x906c6 0xb0174 ... |
| `0x10093f90` | 4: 0x488af 0xc02b0 0xc02ca 0xc17f4 |
| `0x10097de0` | 3: 0x3876b 0x6cc74 0xaf531 |
| `0x10097fa0` | 1: 0x6bee9 |
| `0x10098890` | 2: 0x4b5b7 0xe1ac4 |
| `0x100988b0` | 1: 0x6a133 |
| `0x100988c0` | 1: 0xddd74 |
| `0x1009b660` | 1: 0xf0346 |
| `0x1009b720` | 1: 0xc73d7 |
| `0x1009b730` | 1: 0x36f1a |
| `0x1009b750` | 2: 0x2c428 0x2c76c |
| `0x1009b770` | 1: 0x2c567 |
| `0x1009b780` | 1: 0x2c813 |
| `0x1009b7a0` | 1: 0xf0dd5 |
| `0x1009b7b0` | 2: 0x2c48d 0x2c795 |
| `0x1009b7d0` | 1: 0x5fa19 |
| `0x1009b7e0` | 1: 0xdc4ea |
| `0x1009b850` | 1: 0x7242a |
| `0x1009b900` | 4: 0x6bd39 0x6e085 0xc8970 0xd0315 |
| `0x1009b920` | 1: 0xd7b75 |
| `0x1009b990` | 1: 0x2e8d2 |
| `0x1009b9b0` | 1: 0xe12f2 |
| `0x1009b9d0` | 1: 0x2e831 |
| `0x1009ba30` | 1: 0x2cd8b |
| `0x1009bad0` | 1: 0x2e43f |
| `0x1009bb20` | 2: 0x43413 0x6a78e |
| `0x1009bb40` | 2: 0x5618c 0x56389 |
| `0x1009bbc0` | 1: 0x10cca |
| `0x1009bc00` | 2: 0x106b0 0x10ca9 |
| `0x1009bc20` | 9: 0x53471 0x53978 0x539cc 0x53a03 0x53a43 0x53a89 0x53ac3 0x53b06 0xec0b8 |
| `0x1009bc40` | 3: 0x2d568 0x2d7b7 0x2d141 |
| `0x1009bc60` | 6: 0x55195 0x55938 0x79352 0xe1ee9 0xed0e0 0xed638 |
| `0x1009bc80` | 1: 0xe2121 |
| `0x1009bc90` | 3: 0xa09e3 0xa1cd9 0xa1cf1 |
| `0x1009bd10` | 2: 0x8580c 0x8581a |
| `0x1009bd70` | 2: 0xf4d6 0xf66d |
| `0x1009bd90` | 1: 0xf6b5 |
| `0x1009bdc0` | 1: 0xcadc5 |
| `0x1009bde0` | 1: 0x53f94 |
| `0x1009be30` | 2: 0xddeb8 0xddeee |
| `0x1009d420` | 3: 0x35444 0x359a5 0x48916 |
| `0x1009e6a0` | 1: 0xc0423 |
| `0x1009e9a0` | 1: 0x68cdd |
| `0x1009ff10` | 1: 0xc0597 |
| `0x1009ff20` | 3: 0x5c0f1 0x5c1bd 0x5efee |
| `0x1009ff40` | 1: 0x4b4bc |
| `0x100a2070` | 1: 0x9ed3e |
| `0x100a2080` | 3: 0x95d37 0x9fe88 0xa1c8b |
| `0x100a20a0` | 1: 0x79b7c |
| `0x100a20b0` | 1: 0x79b77 |
| `0x100a2370` | 1: 0xc057d |
| `0x100a2a50` | 3: 0x2c210 0x2c21e 0x2c289 |
| `0x100a4af0` | 1: 0x543d1 |
| `0x100aebc0` | 1: 0x459ab |
| `0x100afa10` | 1: 0x29456 |
| `0x100afa20` | 1: 0x3865a |
| `0x100b0f40` | 2: 0xa09d5 0xa1cb7 |
| `0x100b1390` | 2: 0x9fd66 0xa1aed |
| `0x100b3dc0` | 1: 0x7add7 |
| `0x100b3f30` | 3: 0x78a23 0x7addd 0xf3c0b |
| `0x100b6410` | 2: 0x7403f 0x7404d |
| `0x100bca20` | 3: 0x6b273 0x789bb 0xf3b37 |
| `0x100bcd10` | 9: 0x4b17e 0x4b1b6 0x5568b 0x55955 0x9dd29 0xe176f 0xe1858 0xed3fe 0xed655 |


## 19. Mercenary revive price, Act 5 quest experience, removed quest rewards (lane pa-quests, 2026-10-22)

Median patches (docs/sigma-patch-audit.md items 8-10) ported in `hirelings.cpp` (`InstallMercRevive`, off word `mercrevive`) and
`quests_rewards.cpp` (`InstallQuestXp` off word `questxp`, `InstallQuestRewards` off word `questrewards`). Entry bytes are checked before
every hook, patched bytes before every patch; whole instructions, no rip-relative operand.

| What | RVA | Entry bytes / patched bytes | Notes |
|---|---|---|---|
| Revive price (merc, not-classic flag, hireling id) -> gold | `0x3c1ad0` (hook) | `48 89 5c 24 08 48 89 6c 24 10 48 89 74 24 18 57 48 83 ec 20 41 8b f8` | D2R: `(level^2 / 2) x 15` capped by the hireling columns; Median `D2Hirelings 0x10067450`: level x 100 to 105, `(int)(pow(level - 90, 1.5) x 250)` above. Called at the mercenary's death (`0x4ffb90`, price stored and sent to the client) and again at charge time; the hook covers both. Harness `mercprice [level]` calls it. |
| Rite of Passage experience | `0x550c20` (hook, function replaced) | `48 89 6c 24 10 48 89 74 24 18 48 89 7c 24 20 41 54 41 56 41 57 48 83 ec 20` | D2R: 1.4M / 20M / 40M by difficulty. Replacement: client update `0x518620(game, player)`, then `0x44f2e0(game, player, level, 50000)`; none at level 130+. Harness `a5done` runs `0x54af20(game, player)` (the quest 39 completion that calls it). |
| Qual-Kehk rune loop | `0x54c9ac` | `e8 7f ab fc ff` -> `b8 01 00 00 00` (call `0x517530` becomes `mov eax,1`) | the loop still counts a created item, nothing is created; `QualKehkHook` gives Median's runes. |
| Akara ring | `0x5d9a6d` | `e8 be da f3 ff` -> `0f 1f 44 00 00` | the ring task `0x5d9a30`'s item creation. Griswold's Heart replaces it. |
| Andariel chipped gems | `0x5e1fbd` and `0x5e1fc7` | `8d 7d 02` -> `31 ff 90`; `48 8b` -> `eb 56` | jumps over the two-gem loop (`edi = 0` as the standard gem roll after it expects). The standard gem drop `0x5e201f` stays (D2Sigma's nop covers the loop only). |
| Prison of Ice item | `0x546cc0` (hook) | `48 89 5c 24 08 48 89 54 24 10 57 48 83 ec 30` | task node `+0x18` = item code; the hook writes `'amu '` before the original. The task is dispatched through the pointer table at `0x1d3d900`. |
| Hellforge reward (quest 27) | `0x5e4540` (hook) | `40 53 55 48 83 ec 48` | called with the quest and the dying Hephasto (class 376): rolls Median's `Quest Hellforge` class (monstats row 257, `TreasureClass1` of the difficulty) once, clears quest `+0x23`, then the original runs without runes. |
| Countess reward (quest 5) | `0x5e3010` (hook) | `48 8b c4 56 41 55 48 83 ec 58` | called by the quest 5 kill handler `0x5e10c0` (`TowerKillHook` records victim and killer) and by the retry task `0x5d98b0`. With a kill in progress and data `+0x118` set, `+0x119` clear: `DropBonusPerPlayer` of `Quest Countess` (row 266), `+0x119 = 1`. |

Median-side corrections found on the way: D2Sigma's Andariel patch removes only the two chipped gems (the standard gem stays, the audit said "100 bytes nopped: the vanilla gift disappears"); the formula in the audit row game5-026 (`250*1.5^(level-90)`) is a misreading of `pow(level - 90, 1.5) * 250`.

## 20. Gamble offers and small engine rules (lane pa2-gamble, 2026-10-23; plugin/src/gamble.cpp, engine_gaps.cpp)

Median patches game5-022, game2-014, game4-020, game4-029 (docs/sigma-patch-audit.md items 16 and 21). Expected bytes are checked before every patch / hook.

| What | RVA | Bytes | Notes |
|---|---|---|---|
| Gamble offer generator `(game, player, npc)` | `0x541880` | loop bound `83 fd 0e 0f 8c db fe ff ff` at `0x541a7c` (`cmp ebp, 0xe / jl 0x54195f`) -> immediate at `0x541a7e` becomes `0x20` | the only caller is `0x540913` (in `0x540850`, the gamble request). Offer 0 is item code `rin ` (`0x206e6972`), 1 is `amu ` (`0x20756d61`), the rest a random pick of the NPC's per-level list; the player's old list at player data `+0x108` is freed and a new one made (`0x386260`) |
| Offer quality `(game, npc, code, level, rng)` | `0x541ab0` | - | rolls `0..99999` (`0x153b00(rng, 100000)`) against the difficulty row at `0x300830(expansion, difficulty)`: `+0x6c` rare, `+0x70` set, `+0x74` unique, `+0x78` / `+0x7c` upgrade chances; unique below `+0x74`, set below `+0x74 + +0x70`, rare below the sum, else magic (quality 4). Median's difficultylevels file has 25000 / 1000 / 1000, D2R's own 10000 / 100 / 50 |
| Place the offer `(game, npc, item, list)` | `0x541d20` | - | `0x3865b0` / `0x389270` put it into the list's grid, which fails when the grid is full (the generator then returns): the 32 offers of Median fit page 0 of D2R's gamble grid |
| Client gamble line | `0x112c80` | - | sends `0xec730(0x38, 2, npc id)`; `0x2a4875c` holds the current NPC id |
| Missile hit 20 `(game, missile)` | `0x45ec20` (slot `0x23910d0`) | `3b c6 8b d8 0f 4c de` at `0x45edce` -> `31 db 85 c0 0f 4f d8` | two calc results floored at 1 (`0x45ed93` first, ebp; `0x45edce` second, ebx); Median changes the second (1.13c `0x6fc5de78`) |
| srvdofunc 47 `0x56f750` (table `0x238ea00` slot 47 at `0x238eb78`) | guard at `0x56f859` | `e8 52 59 dc ff 85 c0 0f 85 b9 02 00 00` -> 13 x `90` | `0x3351b0(unit, state)` tests the state on the caster, the jump (`0x56fb1f`) leaves the function |
| Slow / damage floor `(game, unit)` | `0x449f40` (hook) | entry `48 89 5c 24 08 57 48 83 ec 20` | unit type 1: monstats byte at record `+0x1ba + difficulty` (via `0x976e0`), else -0x32; difficulty is the byte at game `+0x104`. Callers `0x4509fa`, `0x451644`, `0x5619d8`, `0x561bde` (aura callback `0x5616f0`, aura apply `0x563d90`). The hook returns -12 / -25 / -50 for a player (unit type 0) on Normal / Nightmare / Hell |
| Required level `0x376de0` | - | `ff 25` thunk into D2RCore.dll (`[0x143e2a3c0]`) | patched in D2RCore.dll itself: the two `add 6` sites `+0x3d49ee` (with a player) and `+0x3d49e2` (without), 3-byte nops after a time stamp and byte check (`required_level.cpp`, off word `reqlevel`; common1-013 done) |

## 21. Monster level, players scaling, Normal drops, leash, Baal throne delay (lane pa2-monsters, 2026-10-23; plugin/src/monster_rules.cpp)

Median patches (docs/sigma-patch-audit.md items 17-19). Every patched byte is checked before it is changed; all sites of a part change or none.

| What | RVA | Entry / patched bytes | Notes |
|---|---|---|---|
| Monster level gate | `0x543d32` | `45 85 ff 74 19` -> 5 nops | `test r15d,r15d / je` inside `0x543b50` (called from the monster setup `0x543120`): the area level is taken only above Normal. Stays: the classic test `cmp dl,1 / je` (`0x543d2d`) and the npc flag `0x4` test (`0x543d3c`, mask `0x1d996d8`). |
| lUndead flag test | `0x543d44` | `85 05 9e 59 85 01 75 04` -> 8 nops | `test [rip+0x1859e],eax / jne`: mask `0x1d996e8` = `0x40`. The rip-relative operand is inside the patched bytes (nops, not a hook entry). |
| Players record rewrite | `0x543e90` (hook) | `40 55 53 57 41 54` (6 bytes) | `(game, monster, record*)`: record `+0x24` life %, `+0x28` experience %, `+0x34` players (D2RCore fills it through the thunk `0x3e2b43c`). The hook writes Median's `(n-1)*50` / 0 and runs the original. A 0 / 0 record stays. |
| Normal drop gate | `0x44138f` | `40 38 be 04 01 00 00 76 19` -> 9 nops | `cmp byte [rsi+0x104],dil / jbe 0x4413b1` in the executor `0x441300`: the monster's level (stat 12) goes to the class getter only above Normal. |
| Class getter (trace) | `0x397290` (hook) | `48 89 5c 24 08` (5 bytes) | `(dataFlag, tc index, level)`; the hook only counts calls and keeps the last level (harness `tctrace [reset]`). |
| Leash compares | `0x5bec51` `83 f9 64`; `0x5bd29f` `41 83 fc 50`; `0x5bd474` `41 83 fc 32`; `0x5c1136` `41 83 ff 32`; `0x5c96aa` `41 83 fc 32`; `0x5ccb39` `83 f8 32` | last byte -> `0x28` | Pet think `0x5bebe5`, approach chooser `0x5bd1e0` (two), owner think `0x5c1080`, AI 112 `0x5c95d0`, AI 107 `0x5cca50`. The distance is `0x596720(unit, owner)`: (max + min/2) of the coordinate differences minus both units' radii (about Euclid - 2). |
| Baal throne countdown | `0x5c71e6` | `81 c1 fa 00 00 00` -> `81 c1 7d 00 00 00` | AI 134 `0x5c7070`: first-wave start `frame + 0xfa` (250) becomes `0x7d` (125). This is the audit's game5-001 "delay 250 becomes 125", which is not a leash. |

Harness verbs: `players <n>` (sets D2R's players setting: `0xe19e0()` then `0xd2f020(setting, n)`; it is not persistent and only the next spawned monsters see it), `tctrace [reset]`, `leash [d]` (moves the mercenary `d` sub-tiles from the player with the unit move `0x491ca0`, prints both positions, `0x596720` and the mercenary's mode). Moving the player instead pulls the mercenary along at once, which hid the thresholds.

## 22. Item property text (lane tooltip-verify, 2026-10-23; plugin/src/item_text.cpp, tooltip_probe.cpp; docs/item-tooltips.md)

| What | RVA | Signature / meaning | Notes |
|---|---|---|---|
| Property formatter | `0x2d6520` (hooked, `item_text.cpp`) | `(viewer, record, value, layer, flag, char out[256], mode) -> al` | record (itemstatcost, D2R layout): id `+0`, descfunc `+0x32`, descval `+0x33`, descstrpos `+0x34`, negative text `+0x36`, str2 `+0x38`; with `flag != 0` it formats the group line from `+0x3c` (descfunc), `+0x3d` (descval), `+0x3e` / `+0x40` (strings). The caller `0x2d97e0` applies ValShift first. `viewer` is the ITEM unit (type 4) when the item text is built. |
| Item text builder | `0x2dc4b0` (observed by `tooltip_probe.cpp`) | builds all lines of one item's tooltip | the hovered item is rebuilt every frame (harness `tiplog reset` right before `tip`); the probe keeps its arguments from the last hover. |
| Data flag of a unit | `0x34a0e0` | `(unit) -> *(u8*)(unit + 0x1bd)` | client / server table selector, **not** the class. Pass it as the first argument of the table lookups below. |
| Skill name string id | `0x28bcf0` | `(data flag, skill id, 0) -> u16` | calls `FUN_140088850` (the skills table manager) and returns `*(u16*)(row + 8 + idx * 2)`, `0x1506` when there is none. A class value instead of the data flag crashes (null manager, RIP `D2R+0x88871`). |
| String by id | `0x3e2b730` | `(id) -> const char*` | D2RCore thunk target; the text of a string id. |
| GetStat | `0x2f5020` | `(unit, stat, layer) -> int` | |
| Local slot / slot unit | `0x8b2d0`, `0x9a480` | `() -> slot`; `(slot) -> player unit` | the entry bytes are checked before the hook is installed (as in `skill_tree.cpp`). |
| Client unit lookup | `0x9a5d0` | `(id, type) -> unit` | type 4 = item. |
## 22. Unique carry limits (lane unique-limits, 2026-10-23; plugin/src/unique_limits.cpp)

D2Sigma's `uniqueitems2` (LimitGroup, LimitCount, PickDuplicates) is enforced by `D2Units` `0x100bd060` / `0x100bd0b0` (read from the 1.13c
disassembly of D2Sigma.dll): the player's backpack (inventory page 0; equipped items, belt, stash, cube and cursor are not counted) is walked for
unique-quality items; a limited unique is refused when the number of uniques of its group (group 0: of the same unique index) is `>= LimitCount`, or,
for a group other than 0 with PickDuplicates 0, when a copy of that very unique is there. The check has no equip half (all 334 limited uniques are misc
items). Sigma runs it on the ground pickup into the inventory and on its quick-move packet (cube / stash / belt to the inventory).

| What | RVA | Bytes | Notes |
|---|---|---|---|
| Item move `bool (player, oldLocs, newLocs, ids, count, flag)` | `0x471e90` | entry `40 55 53 56 57 41 54 41 56 48 8d ac 24 58 56 ff ff` (17 bytes, hooked) | the funnel of the container packets: `0x18` cursor to container (`oldLoc` = `0x382e30` cursor, `newLoc` from the packet), `0x19` container to cursor, the stash / cube / belt moves (40 callers). `Loc` = 4 x int32 `{mode, page, x \| y << 16, body location}`; mode 0 page 0 is the backpack, `ids` are item unit ids (`0x48fe80(game, 4, id)`), `count` and `flag` are stack arguments 5 and 6 (`rbp + 0xaa00`, `rbp + 0xaa08`). False = the caller sends its refusal and the item stays where it was |
| Pickup `bool (player, itemId, toInventory, distance, a5, a6)` | `0x471950` | entry `48 89 5c 24 18 55 56 57 41 54 41 55 41 56 41 57 48 8d 6c 24 e9` (21 bytes, hooked) | ground item to the cursor (`toInventory` 0) or to the belt / backpack (1, the to-inventory flag of packet `0x16`); called by `0x4b9df0` (packet `0x16`) and six more. Looks the item up by id, checks the distance, then places it in the belt or the backpack (`0x4759e0`, `0x3865b0`; not read in detail) |
| Unit data | `0x34a500(item)` | - | `+0` quality (7 = unique), `+0x34` unique index = the row of the migrated `uniqueitems.txt`; page byte `0x36cfe0` (0 backpack, 3 cube, 4 stash); unit mode at unit `+0xc` (0 stored, 1 equipped, 2 belt, 3 ground, 4 cursor); game at unit `+0xd8` (`0x48ff00`) |
| Refusal text | - | - | Median string `12109` (`medianxl:12109`, "\xc3\xbfc1You can only carry one Relic"), sent as a system chat line (`SendClientMessage`). Sigma itself refuses with its own unit message `0x13`; 12109 is the only carry-limit text in Median's strings and is shown for every limit (the mapping of 0x13 to it was not proven) |

## 22b. D2R's carry1 test compares a number, not the unique (lane carry1-fix, 2026-10-25; plugin/src/unique_carry.cpp)

Found with the harness (`item <code> uniq=<row> inv` and a ground pickup with `pkt 16`) and the decompiled placement path. **D2R 3.3 refuses a
second, different carry1 unique** (Butcher's Tooth `a60` row 18, then Laser Focus Crystal `a59` row 19: `item: placing failed`; the ground
pickup stays on the ground). It is not the plugin: with `uniquelimits` in mxl-core-off.txt both paths are still refused (and with it on the plugin's
counter shows `limited 1, refused 0`), and the groups of rows 18 / 19 (13 / 14) are different anyway.

| What | RVA | Notes |
|---|---|---|
| Place item `bool (player, loc*, ids*, count, 0)` | `0x471500` | per item `0x473ed0`: grid check `0x472d20`, then the class / carry check `0x4734f0` (returns 0 = refuse) |
| Carry check, unique half | `0x473960 (item, uniqueList, uniqueListEnd, baseList, baseListEnd)` | for a unique (quality 7, `0x36cf60`; unique index `0x36ce70` = item data +0x34) whose record has `+0x30 > 0` it walks the carried unique indexes (the placing structure's two lists of carried unique indexes, `+0x780` and `+0x423a`, ushort entries) and calls the record comparison `0x3e2b556` (a jump thunk to a function in the protected region) on the two records; true = refuse. Record = `0x194320(dataFlag, index)` = table `0x300a90(dataFlag)` + `0x13c8` (array), `+0x13d0` (count, int64), 0x15c bytes per record. The comparison read at run time: `a != 0 && a->dword[0x30] == b->dword[0x30]` |
| Carry check, base half | `0x473960` second part | the items' base record byte `+0x13a` (misc.txt side) with the item code: refuse when the carried list has the same (code, value) pair; seen in the game: a normal `a60` is refused next to a unique `a60`, and unique 82 (`ebx`, no carry1) refuses its own second copy (not analysed further) |
| carry1 column | loader `0x31f1d0`: name `carry1` (`0x1cfbdf0`), type 2, record offset `0x30` | an int, not a flag |

Median's uniqueitems.txt has 1 in all 89 carry1 rows (rows 7-66 charms, relics and so on), so **every carry1 unique counted as "the same"**: only one of
them fitted in the backpack. Vanilla Diablo II compares the unique itself. The part `uniquecarry` rewrites the number of each carry1 record to row + 1
after the data tables are loaded (`DataTablesLoadedEvent`, as `collide_types.cpp` does for CollideType), so the comparison means "the same unique": the
second copy of one unique is refused, different ones are carried together. The plugin's own limit table (section 22, groups of 1-3 relics) is applied on
top, unchanged. Control: `MXL_CONTROL=uniquecarry` (the off list keeps letters only, a word with a digit such as `carry1` can never match).

## 23. Model and texture index: why new asset paths were invisible (lane new-asset-paths, 2026-10-23; tools/model_lod_desc.py)

Read from the memory dump (`tools/d2r_find.py`, RVA = file offset); format and the in-game proof in [hd-models.md](hd-models.md) section 3c.
The model asset cache is built once at startup from `data/hd/model_lod_desc.bin`; every model load goes through it.

| What | RVA | Notes |
|---|---|---|
| Model asset cache init `(cache this)` | `0xf75c60` (called from `0xe21850` at `0xe218cd`) | opens `data/hd/model_lod_desc.bin` (string `0x1e17880`, open `0xa00c60`), reads it into `this+0x120`; a file whose first dword (count) is 0 calls `0xf75760`; no file: assert `Binary desc cache is missing! ALL model loads will be blocking!` (`model_asset_cache.cpp`, string `0x1e17800`) and an empty table (`count 0`, offsets -4 / -12 / -20) |
| LOD resolver `(cache, name, lodHint, out)` | `0xf75fe0` | hashes the model name (FNV-1a 32 of the lower-cased path, `0x811c9dc5` / `0x1000193`, tail in `0x150140`), looks it up (`0xf75af0`), sets `out+0x178` = found; with an entry: LOD names `<name minus .model>` + `_lod` (string `0x1e17a78`) + `%d` (`0x1d070d4`), the entry's mask byte (`+0x1c`, bit k+1 = LOD k) says which exist; without one: `Failed to find LOD for model %s` (`0x1e17a80`, line 0xdd) and the plain name is used. The entry's bounds and stream records feed the later stages: an unlisted model loads but is never drawn |
| Table lookup `(table, hash)` -> entry or end | `0xf75af0` | lower bound over array 1 (44-byte entries, key `u32` at `+0`, sorted); found when the key matches |
| Model asset loader | `model_asset.cpp` (string `0x1e11d70`) | `:305` `MeshBindingCount >= 1` per `Model` (a file loaded by its plain name must bind a mesh in every `Model`), `:397` `isMeshFlipbook == GetModelInfo()->isMeshFlipbook` (fires when the stream offsets of the table are wrong: `d2rloader.log` shows `Invalid data detected!` and the game dies in the preload) |
| Other strings of the same code | `dynamic_lod_system.cpp` `0x1e275f0` | LOD selection by distance; not needed for new paths |

Why vanilla ignored new paths: the lookup key is the path's hash, not the file system, so a path that is not in the table is never
resolved to its `_lodN` files. How the fix works: the mod folder's `data/hd/model_lod_desc.bin` replaces the game's and has the new
paths added; the texture loader has the same kind of index (`data/hd/texture_desc_cache.json`, `filename` key, format / size / mips). No hook is
involved. The D2RLoader ResourceService (plugin-side files at `data/.../d2rloader/<plugin-id>/...`) serves files at new paths too,
but needs the same index entries.

## 24. Keyboard Quick Cast (lane quick-cast, 2026-10-27; bug #54, no plugin code)

Read from the 93847 dump (`tools/d2r_find.py`, Ghidra `DecompOut.java`). Keyboard Quick Cast runs through D2R's
ControllerManager (`D2Client/src/Game/ControllerManager`), the same queue as the gamepad skill buttons.

| What | Where | Notes |
|---|---|---|
| Option "Quick Cast Enabled" (Settings.json) | getter `0xe1c60` -> setting object `0x2a343f0`, value read with `0xd2e490` | read once at start; every save folder has its own Settings.json (`Saved Games/.../mods/<savepath>/Settings.json` for a mod) |
| Skill hotkey handlers | 32 small functions `0x119f70`-`0x11b185` (e.g. key down `0x119f70`, key up `0x11a960`) | `skill = 0x117d20(slot)` (hotkey table `0x2a488d0`, 0x1c per entry; `0x2a48a90` in another input mode); Quick Cast on and `0x14a970(cm, skill)` false -> `0x122f30(slot, 1)` on key down, `0x122f30(slot, 0)` on key up; otherwise key down calls `0x118d50` (switch only) |
| "Switch only" skills | `0x14a970(cm, skill)` | true when the skill's record in the per-skill table `cm+0x26e8` (0x210 bytes a skill, count `cm+0x26f0`) has byte `+0x20` set, except ids 357-364 and 370 (`0x3377d0`) |
| Per-skill controller table | loader `0x147450`, file `data/hd/global/excel/controllerskillsettings.json` keyed by `id` | `+0x0 usageType`, `+0x4 targetGroup`, `+0x18 usePredictiveTargeting`, `+0x1a ignoreTargetOnHold`, `+0x20 toggleSlotState`, `+0x24 tapWindowMS`, `+0x34 skillQueueDeadzoneMS`. Vanilla sets `toggleSlotState` on the 20 Paladin auras (98-125) only; skills missing from the file keep zeros |
| ControllerManager singleton | `0x144640` -> `0x2a4eab0` | per player 0xb8 bytes from `+0x1968`; tick `0x14b720` -> `0x14c540` per player |
| Quick cast start / queue | `0x145680(cm, player, slot, down)`, queue `0x149de0` -> `0x14b920` | `0x14b920` drops the queued cast when `0x21b170(player, Skill*)` is not in mask `0x347` (codes 0, 1, 2, 6, 8, 9 pass) |
| Usable test of the queue | `0x21b170` = `0x33f360` (the test `skill_restrict.cpp` detours) plus client checks (9) | 3 not a skill, 4 restricted, 5 no weapon, 7 no level -> no cast |

A targeted melee skill (`range h2h`, `TargetableOnly 1`) quick-cast with no monster under the cursor does nothing, in
vanilla rows (Bash) and Median rows alike (bugs.md #54).

## Unknown / next steps

Solved in lane d2r-addresses-2 (sections 4, 5, 7-11): warp destination and the lockout refusal point, game frame, spawn, TC executor,
game destroy / create, client menu composition, quest handlers 13 / 14 / 25 / 38 / 40, gold sync (by evidence).

1. **Unique item by index** (Griswold's Heart): no D2R function found that takes a unique row; see section 7 for the two workarounds (base item
   via `0x43d530`, or a one-entry treasure class through `0x4404f0`). Needs a look at the unit creation `0x490410` -> `0x1404905a0` or an in-game test.
2. ~~Portal objects~~ lane dungeon-lockout: the portal object operate function is **`0x58f680`** (ctx `{game, portal, player, ?, object class}`; it pairs
   the portal with its twin through `0x490070`, places the player with `0x491ca0`, returns 1 moved / 0 failed with unit message `0x14`). Entry bytes
   `48 89 4c 24 08 55 53 56 57 41 56 41 57 48 8b ec`. Destination level = word from `0x34ad40(portal)`. Hooked by dungeon_lockout.cpp.
2b. Object operate table (exe `0x23a51c0`, ctx `{game, object, player, 0, class, ...}`): fn 15 = `0x58f680` (portal), fn 31 = `0x5ea260` (Gidbinn altar,
   the same code as D2Sigma's), fn 49 = `0x5e5210` (Hellforge), fn 70 = `0x548c40` (Worldstone / Throne objects 563 / 569: needs object mode 2 from
   `0x34ab60`, the player in level 131 and quest 36 byte `+0xa6`, then `0x488180(game, player, 0x84, 0xb)`; hooked by dungeon_lockout.cpp
   `ThroneHook`, entry bytes `48 89 5c 24 08 57 48 83 ec 20 48 8b d9 48 8b 49 08`, off word `worldstone`), fn 73 = `0x5e57e0` (Tyrael's portal,
   sets quest 28 bit 0). `0x34e5f0(unit, mode)` sets an object's mode (harness `objmode`), `0x518220(game, id)` finds a quest object (`+0x11`
   finish byte, `+0x12` active byte, `+0x2b0` kill handler slot).
3. ~~System message sender~~ lane client-ui: chat packet 0x26 via `0x48fde0` + `0x477a30`, section 13.
4. Stat-update packet sender (0x1d-0x1f family) not located; gold sync argued from the game's own gold code (section 10), **untested**.
5. The game create function `0x4049d0` has no direct callers (called through a job pointer); the destroy hook covers the reset need, so this is
   cosmetic. The monster death drop caller `0x5930b0` (the other caller of `0x4404f0`) was not read.
6. Client: the string ids for new menu lines (tbl lookup `0x143e2b730`) and the layout / frame of a longer menu are untested; records hold only 5 lines.
7. Everything above is static analysis: none of the hooks has been run in the game yet.


## Waypoint arrival selection (lane waypoints, build 93847)

`0x5933f0(game, player, destinationLevel)` is called after packet 0x4b validates
an activated destination and a nearby operated waypoint (`0x4b6f10`). At
`0x59347b`, `e8 00 d3 d5 ff` calls the town predicate `0x2f0780` (thunk of
`0x327850`: levels 1/40/75/103/109). Towns, levels 46/74 and 133-137 select
entry kind 13; every other level selects 0. That is wrong for Median's added
preset waypoint levels 138/139/141/147/155/169/242. Duncraig (153) is a maze
level: its native waypoint search already succeeds with kind 0 (control verified).

`0x488180` performs the move (including act changes); `0x2ef8b0` calls
`0x3da650` and finds a free stand position with `0x362f90` (collision mask
0x1c09). In a preset level, kind 13 calls `0x3dad90`: first room flagged
`room+0x50 & 0x30000`, then preset objects (`room+0x98` list, next +0x10),
type 2 at +0x20, Objects row id +4. The object qualifies by record
`+0x127 & 0x40`; its coordinates (+8/+0x24), divided by 5, are added to the
room tile origin (+0x60/+0x64). Other kinds use `0x3dac20`'s preset entry list
(level+0x34, triples x/y/kind, count +0x200), explaining the portal/entrance
fallback. Maze levels already try the waypoint finder first.

`wparrival` changes only the predicate call in waypoint travel, preserving the
five town results and adding the generated Median waypoint levels. It does not
change the generic entry finder or ordinary portal/NPC/level travel.

## Median town classification (lane town-monsters)

Median `levels.bin` byte `+0x14b` (`IsTown` in `2_txt/sigma_named/levels.txt`) marks nine towns. The generated
`mxl_goblins::Towns` already maps these through the build's level id map. D2R's leaf `0x327850(int level)` instead
subtracts and compares only 1, 40, 75, 103 and 109. Its room wrapper `0x2f0750(room)` reads the level through
`0x360fc0(room + 0x18)` and tail-calls that leaf; `0x2f0780(level)` is another tail thunk. Neither reads a town field
from the loaded levels table. Level type is not the answer: Tur Dulra and Scosglen both use type 44.

| Median row | D2R id | IsTown | Level type | Vis0 / Warp0 (Median ids) |
|---|---|---|---|---|
| 137 Caldeum | 138 | 1 | 36 | 187 / -1 (also Vis1 182 / Warp1 68) |
| 138 Silver City | 139 | 1 | 39 | 142 / -1 (also Vis1 143 / Warp1 -1) |
| 241 Tur Dulra | 242 | 1 | 44 | 270 / -1 |
| 242 Frozen Sea | 243 | 1 | 44 | 245 / 100 |
| 270 Scosglen | 271 | 0 | 44 | 241 / -1 |

Tur Dulra and Scosglen have reciprocal open visibility connections; no warp object separates their walking rooms.
`0x340e70` (path computation) checks unit type 1, excludes `0x3b01c0`'s special monsters, resolves the destination room,
and calls `0x2f0750`; when true and its third parameter is zero it takes failure exit `0x341259`.
`0x510f00` suppresses room monster population using the same check. `0x512a50` uses it when initializing a unit's
flags through `0x34e5f0(unit, 2)`. Other callers include AI, target selection, skills and missiles. Room-generation
functions `0x328880` / `0x3608a0` call the leaf directly. Fixing only a movement caller or a harness helper would
leave those other readers inconsistent.

`town_rules.cpp` replaces the leaf entry with a 14-byte absolute indirect jump to a predicate over Median's generated
town list, checking all 34 original bytes first. It needs no trampoline (the original leaf has short branches and
an early return), changes no calling convention and preserves every vanilla town. The `mediantowns` off word leaves
the stock classifier intact; the `mxl` command has a `median towns` line. No plugin version change.

Harness observations: `h town [level]` calls the game's level thunk and room check (also accepts `h town x y` for a
loaded room); `h town edges` finds collision-free borders in loaded rooms, without moving anything. `h state` now
includes each nearby monster's area. `h spawn class count x y` calls the existing native spawn routine at a chosen
field position; it does not override its refusal checks. The `townmonsters` game check walks the player across the
Tur Dulra / Scosglen border and watches a native Scytheclaw's actual room. `MXL_CONTROL=mediantowns` must reproduce
entry and the enabled run must refuse it. Missing borders or failed setup are BLOCKED/FAIL, never PASS.

## 25. Renderer Pool (lane griswold-crash, 2026-10-28; bug #60, plugin/src/render_pool.cpp)

Read from the 93847 dump with `tools/d2r_find.py`; not seen in game.

| What | RVA | Notes |
|---|---|---|
| Pool object | `0x2810ff0` | `+0` vptr (`0x1d6d770`, set by the CRT initializer `0x4ed70`; `0x1cb90b0` after the exit destructor `0x1c8e3e0`), `+8` parent allocator, `+0x10` base, `+0x18` size, `+0x20` TLSF handle, `+0x28` lock |
| Pool start / stop | `0xf6efe0` / `0xf6ef70` | start: `0xc00000` bytes (12 MB) from the parent, TLSF create `0x1215a30`, names "Renderer Pool" / "TlsfAlloctor"; called from the renderer start `0xe213f6` ("Renderer Allocs"); stop zeroes base and size |
| Vtable `0x1d6d770` (6 entries; also used by the allocators at `0x246b470`, `0x2677438`, `0x27d1770`, `0x27d7848`, `0x27ff098`, `0x2807d00`) | `0x82dcf0` dtor, `0x82dad0` allocate(size, align), `0x82db40` reallocate(p, size, align), `0x82dbf0` TLSF realloc(p, size), `0x82dc60` free(p), `0x82dcb0` usable size(p) | no direct calls to any of them |
| Wrappers | `0xf6f060` allocate(size, align) (103 callers), `0xf6f0c0` free (165), `0xf6efd0` returns the object (11) | `0xf6f060` on null: `0xf6ef40` "Failed to allocate from Renderer pool!", then returns null |
| Crash site of bug #60 | `0xf3d028` in `0xf3cfd0` | moves 0x80-byte records into the new buffer of `0xf3d587` (vector grow) from `0xf3fef1` / `0xf3f840` (`D2Render\src\model_instance.cpp`) |
