# In-game tests waiting to be run

Changes that are built and installed but not yet confirmed in the game. Restart D2R after an install. Move an item to
"Confirmed" (or into docs/bugs.md) once tested. Console command `mxl` shows the plugin version and how many skill
functions it installed.

## Waiting

Damage / IED audit: `game_checks.py all ied iedtip --slot 3`, and the same
with `MXL_CONTROL=innate`. Set `MXL_CHAR` to the lane's own throwaway; an
explicit name is entered or created, never replaced by the selected card.
`ied` grants the hidden passive using equipped stat=value pairs, checks
the data formula, spends a real Dexterity point, and applies native weapon
hits to a zero-resistance monster at SrcDam 128 and 64. `iedtip` checks the
client formatter with explicitly set and restored client inputs. Harness verbs `passiverefresh` and
`weaponhit mon:<id> [SrcDam]` expose the native passive refresh and weapon
build/hit/apply pipeline; `passivestate [arr|dump|watch|awatch]` reads the state list of the innate passive (skill 2072) and
`passivetrace on|clear|show [n]` records every passive apply / refresh with its inputs and call chain (lane ied-vanish); `weaponhit` reports raw damage fields (1/256 life)
and whole life lost. See [damage-ied-audit.md](damage-ied-audit.md).

Use [test-sessions.md](test-sessions.md) to run these checks by character.

| Since | What | How to test | Expected |
|---|---|---|---|
| 0.69.17 (lane griswold-crash) | **Crash at Griswold, bug #60: Renderer Pool fallback** (plugin/src/render_pool.cpp, off word `renderpool`; harness `renderpool [probe]`; checks `renderpool`, `griswold`). Not run in game yet (static analysis only) | `MXL_SLOT=N MXL_RUN=<lock> py -3 tools/game_checks.py all mxl renderpool griswold` (`MXL_GRISWOLD_SECS`, default 180). By hand: Tristram, fight Griswold and his pack for several minutes in HD | `mxl`: `render pool on: Renderer Pool 0x2810ff0 (12 MB) falls back to the heap when full`; the probe answers `probe=ok size=12582912`; Griswold fights for the whole time, no crash file. Tell me: whether `mxl-core.log` ever has `render pool: the Renderer Pool is full` (and the count), and `mxl`'s heap block / peak numbers after a long fight |
| 0.69.15 (lane equip-crash) | **Circlet crash on pickup / wear, bugs #49 (Tiara) and #55 (Coronet)**: D2R's fixed item type ids moved to Median's (plugin/src/item_type_ids.cpp, off word `typeids`; tools/item_type_ids.py) | `MXL_SLOT=<n> MXL_RUN=<lock> MXL_CHAR=<throwaway> py -3 tools/game_checks.py all mxl typeids equipall` with `MXL_EQUIP_MODE=ground MXL_EQUIP_ONLY=<circlet codes> MXL_EQUIP_QUALS=3,4` (pick up from the ground to the cursor and wear; and with the inventory flag, which puts the item on at once when the head is empty) or `MXL_EQUIP_MODE=packet` (every head base and unique by 0x19 / 0x1a); `MXL_GRAPHICS=legacy`, `MXL_CHAR_CLASS=<class>` for a new character of another class. By hand: pick up and wear a Tiara / Coronet; socket a rune into a circlet; drink a mana potion from the belt | `mxl`: `item type ids on: 25 of 25 ...`; `typeids` PASS (a Thul rune goes into a circlet's socket, the circlet is worn); `equipall` PASS, the game survives every item (another class's helms are refused as expected). Control (`typeids` in mxl-core-off.txt): wearing or picking up a circlet asserts `UnitGetType(hUnit) == UNIT_ITEM` (ItemMode.cpp:676) and the game dies or hangs. Run on slot 2 with the dev and the release install (Barbarian HD, Sorceress legacy). |
| 0.69.9 (lane goblin-crash) | **Den boss / goblin sound crash, bugs #42 / #46** (plugin/src/sound_guard.cpp, off word `soundguard`; tools/txt_migrate.py hit-6 spawns; tools/validate.py `hit6_spawns`; check `denboss` now mortal) | `MXL_SLOT=3 MXL_RUN=<lock> MXL_CHAR=<throwaway> py -3 tools/game_checks.py all mxl goblincrash denboss` (`MXL_DENBOSS_GOD=1` adds god-mode soak rounds; `MXL_SOUNDGUARD_TEST=1` on a dev DLL feeds the goblins' Neutral sound as -1, =2 reproduces the crash) | PASS: `goblincrash` shows `sound guard: 0 bad sound ids skipped`; `denboss` fights the boss mortal in HD and legacy (cold resist as is, 0, -100), the bone spear spawns 2835 (never 2818), the player lives, no crash file. Tell me: whether Median monster sounds play (goblin chatter) and your d2rloader.log `Loading sound data tables` lines |
| 0.69.9 (lane goblin-crash) | **Treasure goblin crash, bug #46** (check `goblincrash`, tools/game_checks.py; plugin/src/goblins.cpp: monstats row check before the spawn, `goblin <id> rolled ... spawning` log line before the spawn call) | `MXL_SLOT=3 MXL_RUN=<lock> MXL_GOBLINS_FORCE=1 py -3 tools/game_checks.py all mxl goblincrash` on a developer install and on a release install (downloader `--cli install`, `launch_arguments` without `-txt`, save folder `D2R-XL-sN/`, dev DLL swapped in) | PASS: in HD and legacy six goblin types spawn, run 20 s, cast their curse (2580) and Submerge (2582), die, and the plugin roll spawns one; no crash file, no new assert, `0 without a monstats row`. Tell me: on your install, the last mxl-core.log lines before any goblin crash |
| 0.69.8 (lane env-guard) | **Which build runs, bug #53** (plugin/src/env_guard_logic.h, off word `envguard`; check `envguard`), and the mod toml's `[d2rloader.advanced] suppress_global_extensions = true` (tools/install_mod.py) | `MXL_SLOT=<n> MXL_RUN=<lock> MXL_CHAR=<throwaway> py -3 tools/game_checks.py all mxl envguard otherplugins`; to see the warning: copy the dev mxl-core.dll into `<slot D2R>\d2rloader\plugins` (with and without suppress_global_extensions), start, run `mxl` | normal slot: first `mxl` line ends `| mod D2R-XL | file <slot>\mods\D2R-XL\d2rloader\plugins\mxl-core.dll`, `environment ok`. With the global copy and suppress on: d2rloader.log loads no global plugin, `environment ok`. With suppress off: about 15 s after the start mxl-core.log has `environment WARNING: ... a second copy ...` and the red line shows at the top. **Not run yet** (slots 2 and 3 were busy). |
| 0.69.6 (lane den-crash) | **Den of Evil boss, bug #42** (check `denboss`, tools/game_checks.py) and the **other plugins line** (bug #44; plugin/src/other_plugins_logic.h, off word `otherplugins`) | `MXL_SLOT=3 MXL_RUN=<lock> MXL_CHAR=<throwaway> py -3 tools/game_checks.py all denboss otherplugins` (`MXL_DENBOSS_SECS` fight seconds per graphics mode, default 30; `MXL_DENBOSS_SEARCH` seconds of crawling for the Den's own superunique, default 30) | `denboss`: HD round and legacy round (G pressed in the town), boss class 2833 with its party fights, casts SkeletonRaise, is killed; no crash file, no new assert. PASS `checks-20261027-122930-s3`, `checks-20261027-123712-s3`, `checks-20261027-125047-s3`. `otherplugins`: `mxl` has `other plugins: none` on a test slot; mxl-core.log has the line ~15 s after the start |
| lane pub-release (version not bumped; `mxl` first line now ends the version with `(dev)` or `(release)`) | **Player release package and wrong-build guard** (tools/package_release.py, docs/release.md; cmake `-DMXL_RELEASE=ON` compiles the test harness out; plugin/src/build_guard_logic.h) | `py -3 tools/package_release.py` after tools/build.py: dist/ gets the 7z (no zip since 2026-10-26), release-manifest.json, notes and SHA256SUMS. The release DLL cannot run on slots 2/3 (no harness, no `volserial`): test its folder with the dev DLL swapped in (`game_checks.py --slot 3 all mxl`). Wrong build: unit test `buildguard_tests` (no other D2R build installed) | Zip without harness / off / save files; `mxl` PASS on the release folder. On another D2R build the log has `D2R-XL <v> needs D2R build 93847; this is <n>`, the same line is drawn at the top of the screen and no hook goes in |
| lane p4-ww-morph (plugin 0.63.0; run `mxl` and read the `whirlwind procs` line, `on: chance to cast on striking / on attack works during a spin (0x5896e0 hooked) (N casts let through during a spin, M refused)`; off word `wwproc`) | **Whirlwind chance-to-cast, real shapeshift death** (`whirlwind.cpp`, `tools/game_checks.py`) | Barbarian: wear a ring with chance to cast Fire Bolt on striking or on attack and spin through a pack with Median's Whirlwind (skill 1306): Fire Bolts appear, as with normal attacks. Druid: wear an axe, cast Werebear (1375), let a monster kill you: you die, the form ends, Esc respawns you in town. | No automatic checks needed: `py -3 tools/game_checks.py --slot N all wwproc morphdeath` is PASS (see "Lane p4-ww-morph" below) |
| lane p4-quests-verify (plugin 0.62.0; run `mxl` and read the dungeon lockout line, `... Worldstone / Throne objects both ways, ... Worldstone / Throne warps N`; off word `worldstone`) | **Quest and object verification, Worldstone / Throne object function 70** (`dungeon_lockout.cpp` `ThroneHook`; harness verbs `objmode`, `questobj <id> poke <offset> <byte>`, `missile <row> dx dy skill level`, `dump ground nogold`) | `py -3 tools/game_checks.py --slot N all towerkill lockwarp tyraelwalk worldstone hitfloor strdex itemevents` (background mode; controls: `MXL_CONTROL=quests` towerkill, `lockout` lockwarp, `worldstone` worldstone, `hitfloor` hitfloor). By hand: `h object 569`, `h objmode <id> 2`, `h operate <id> 70` in area 131 with `h questobj 36 poke 166 1` | PASS, run `checks-20261023-234713-s3`; see the rows of docs/unported.md (quest 5 guard, lockout quest condition, Tyrael, item events, quest rewards, D2 bugfix leftovers, hit 20 floor, Gidbinn / Worldstone) |
| lane p4-leftovers (plugin 0.61.0; run `mxl` and read the `soulstealer` line, `on: 34 Soulstealer monsters heal 1/10 of max life when they kill a player ..., heals N, player deaths N (last killer: ...)`; off word `soulstealer`) | **Soulstealer heal, drop item level reader, hire robustness** (`no_corpse.cpp`, `harness_cmds.cpp`, `item_gen.cpp`, `tools/game_checks.py`) | Let a Soulstealer boss (Zagraal, Kabraxis) kill your character in the field: the boss gains a tenth of its max life, an ordinary monster gains nothing. Drops of monsters take the level of the area. | No automatic checks needed: `py -3 tools/game_checks.py --slot N all soulstealer dropilvl classlock` is PASS (see "Lane p4-leftovers" below) |
| lane p4-verify-a (version not bumped; run `mxl` and read the `act 2-5 quests`, `stat rules` and `craft flags` lines; off words `respecbuffs statclick`) | **Phase 4 verification: reset removes buffs (DC7), stat point shift-click (XP6), Cow portal in any town (CR6), Grit follows Strength (XP9)** (plugin/src/quests_act2_5.cpp `ClearTimedBuffs`, stat_rules.cpp `StatClickHook`, item_spells.cpp `CubeCowPortal`, craft_flags.cpp `PortalHook` and the act compare patch `0x432dd5`, dungeon_lockout.cpp cross-act portals by travel `0x4f2e40`; new harness verb `gameflag`, `enter` prints the refusal reasons; docs/unported.md) | `py -3 tools/game_checks.py --slot N all respecbuffs signet dropilvl cubehotkey cowtowns freerespec grit statclick mapreveal` (background mode). `mxl`: `act 2-5 quests ... respec clears buffs`, `shift-click on (25 points...)`, `craft flags ... portals cross acts | Cow portals outside act 1: N opened, M refused`, `dungeon lockout ... portals taken across acts N`. By hand: buff yourself, reset at Akara (the buffs go); shift-click a stat (25 points); put Wirt's Leg in the cube in Lut Gholein (a red portal to the Cow Level appears, once per game) | buffs off after the reset; 25 points per shift-click, 1 per click; the Cow portal opens in every town, can be walked into (Hell, character level 110, Median's table) and its own portal leads back to that town; Grit grows with Strength when the class passive is applied and when a Strength point is spent. The harness verb `gameflag <word> <bit> [get\|set\|clear]` reads and writes D2R's own game flags (the Cow portal's once-per-game flag is word 4 bit 11). Results and run folders: docs/unported.md rows DC7, GS10, CR5, XP6, XP7, MU2 |
| lane new-asset-paths (data only, no version change; rebuild with tools/build.py and install) | **Assets at new paths: the Wereowl units' models and textures at `data/hd/character/mxl/`** (tools/wereowl_models.py `place` / `index_new_paths`, tools/model_lod_desc.py: entries added to `data/hd/model_lod_desc.bin` and `texture_desc_cache.json` in the mod folder; docs/hd-models.md section 3c; `MXL_OLD_PATHS=1` builds the old override of the vanilla `horse` / `wargoatman` paths) | `py -3 tools/game_checks.py --slot N all assetpaths` (background mode; verified on slot 1; with the original `model_lod_desc.bin` the check fails: the unit is not drawn). By hand: `cheat mspawn wereowl`, `cheat mspawn corrupted_wereowl`, or cast the Druid's Wereowl skill | The Druid's Wereowl form and the Corrupted Wereowl are drawn (textured, animated with the werebear / goatman animations); `d2rloader.log` has no `model_asset.cpp` assertion. Not tested: other Median monsters at new paths (the recipe is the same), a new path for a unit with fewer than 5 LODs |
| lane p4-engine-b (version not bumped; run `mxl` and read the `vendorstock` line, `on: no extra magic copies above item level 24 (0x53cd2b patched), Nightmare item level cap (0x53cfa0 hooked)`; off word `vendorstock`) | **Vendor stock rules** (docs/vendors.md; `txt_migrate.py` MagicLvl 0, `waypoints_data.py` actinfo `maxnpcitemlevel`, plugin `vendor_stock.cpp`), the curse client function wrapper (no nMissile assert), the area aura radius guard (no nRadius assert), srvdofunc 41 / 73 wrappers, the cherry (item spell 17) with its lockout clock, the waypoint-open sound (message 0x70) | Game checks `vendorstock` (Charsi in all three difficulties at levels 10 / 40 / 90: builder item level 20 / 68 / none, at most 3 magic copies, magic stock at level 10), `cursemissile`, `asserttrace`, `replacedskills`, `cherry`, `warprevisit`, `wpauto` (step D) | Run folders in docs/unported.md rows 34, 62, 211, 212, 220; the vendor control is the same check before the changes (Normal cap 12, Nightmare 95 uncapped, 5 copies of one magic item, no magic stock at level 10) |
| lane carry1-fix (plugin 0.66.0; run `mxl` and read the `unique carry` line, `on: each carry1 unique gets its own carry number (row + 1) after the table load (loads 1, carry1 uniques 178, rewritten 178)`; off word `uniquecarry`) | **Different carry1 uniques (the 40 charm uniques, Butcher's Tooth to Elder Vial) can be carried together; a second copy of the same one is still refused** (plugin/src/unique_carry.cpp, unique_carry_logic.h) | `py -3 tools/game_checks.py --slot N all mxl charmlimit uniquelimits` (background mode; `MXL_CONTROL=uniquecarry` for the control). By hand: `h item a60 uniq=18 inv`, `h item a59 uniq=19 inv`, `h item a55 uniq=21 inv` (three different carry1 uniques in one backpack), then a second `h item a60 uniq=18 inv` (refused) | The three different uniques are placed, the second Butcher's Tooth is refused (`item: placing failed`); with `uniquecarry` in mxl-core-off.txt the second different one is refused again | Cause: D2R 3.3 reads carry1 as a number (unique record +0x30) and refuses a unique when a carried one has the same non-zero number; Median has 1 in all 89 carry1 rows (docs/d2r-addresses.md section 22b) |
| lane unique-limits (version not bumped; run `mxl` and read the `unique limits` line, `on, 334 limited uniques; moves into the backpack N (limited L, refused R)`; off word `uniquelimits`) | **Median's unique carry limits: at most 3 relics of a group, single-copy uniques, no second copy of the same unique in a group** (plugin/src/unique_limits.cpp: hooks the item move `0x471e90` and the ground pickup `0x471950`; data tools/unique_limits_data.py -> mxl_unique_limits.h; text: Median string 12109) | `py -3 tools/game_checks.py --slot N all uniquelimits` (background mode; verified on slot 2, see docs/unported.md). By hand: carry three relics of one kind (e.g. three Cotw uniques of the limit group 1), walk over a fourth lying on the ground, take a fourth out of the Horadric Cube or the stash onto the cursor and drop it into the backpack; pick up a single-copy item (e.g. the Sunstone of the Twin Seas) twice; put an item of the group in the stash first and check it can be taken back only while the count allows | The fourth relic stays on the ground / cursor and a system line says "You can only carry one Relic" (Median's one text for every limit); uniques without a limit and items in the stash / cube / belt / worn are not counted; a pickup to the cursor is not blocked, only the drop into the backpack. Not seen by hand: a real walk-over pickup, a cube recipe output landing in a full backpack, the message in the log |
| lane orb-tooltips (data only, no version change; rebuild with tools/build.py and install) | **Mystic orb tooltips** (tools/orb_tips.py, txt_migrate `orb_tooltips`: each of the 101 orbs has its own spelldescstr `medianxl:mxlorb_<row>`) | Spawn orbs (`h item <code> inv`, e.g. `46+`, `63+`, `&68`, `mo01`) or buy some, open the inventory, hover them | Each tooltip lists the old text, "Limit per item: N", "+N Required Level", the orb's properties and the target type, e.g. Heart of Frost: Ring, Amulet or Quiver Only / Weapon Physical Damage +9% / +5% to Cold Skill Damage / 2% Chance to cast level 40 Ice Bolt Nova on Melee Attack / +10 Required Level / Limit per item: 2 / Right-Click to Apply. Game check `orbtips` ran on slot 2 (REVIEW: screenshots read by hand) |
| lane pa2-stats (version not bumped; run `mxl` and read the `stat rules` line, `ok: potion amounts on (...), stamina on (0x42e850)`; off words `potionamounts stamina manaregen`) | **Potion of Life +50 life, Lam Esen's Tome 10 stat points, Median's stamina and mana recovery, get-hit durability** (plugin/src/stat_rules.cpp, stat_rules_logic.h, heat.cpp; audit items 11, 12, 15) | `py -3 tools/game_checks.py --slot N all potionamounts manarules nodurability heat townmana sprint` (background mode). By hand: drink a Potion of Life (max life +50, was +20), read Lam Esen's Tome (10 free stat points, was 5); walk with the stamina bar empty (it refills 3/4 as fast as standing); stand next to a Stamina Shrine's effect or use `h setstate player 136 1` (the bar fills at once); get hit by monsters with worn armour (durability stays) | Potion +50 life, Tome +10 points; stamina standing max / 256 raw per frame, walking 75% of that, running 0; state 136 fills the bar; a mana pool smaller than the regeneration frame count does not refill; a run in a town costs no stamina; armour and weapon keep their durability when hit. Not seen by hand: the real item use, a real shrine |
| lane tooltip-verify (version not bumped; run `mxl` and read the `item text` and `tooltip probe` lines; off words `itemtext tooltipprobe`) | **Item property text** (descfunc 32-38, class lock stat 492, `_mxl` string aliases; plugin/src/item_text.cpp; docs/item-tooltips.md) | Hover a unique with honorific / cooldown / innate damage / reanimate / life regeneration lines (e.g. unique relic `cotw` for the class line), a rare ring and a rare amulet | `+12% Enhanced Defense` style lines with the number once and no `%d` / `%+d%%` / `%0`; `Jitan's Gate Cooldown Reduced by 1`; `Innate <Element> Damage: N (P% of <Attribute>)`; `(Assassin Only)` on the class-locked relic; `Orb Effects Applied to this Item are Doubled`. Report any raw printf text, empty line or a skill name that reads like a placeholder |
| lane pa-quests (version not bumped; `mxl` shows the lines `merc revive price`, `quest experience`, `quest rewards`; off words `mercrevive questxp questrewards`) | **Median mercenary revive price, Act 5 quest experience, removed vanilla quest rewards** (plugin/src/quests_rewards.cpp, hirelings.cpp): kill your mercenary at level 126 and read Kashya's revive price; finish an Act 5 quest below level 130; finish Qual-Kehk's, Akara's, Andariel's, Anya's quests, smash the Hellforge soulstone, kill the Countess | the revive line costs level x 100 up to 105, `250 x (level - 90)^1.5` above (54,000 at level 126); each Act 5 quest gives exactly 50,000 experience (none from level 130); Qual-Kehk gives r08 r09 r10 only (Normal), Akara no ring, Andariel no two chipped gems, Anya's reward is an amulet, the Hellforge and the Countess drop their own classes. Game checks `mercrevive`, `questxp`, `questrewards` run the paths; the natural Hellforge smash and Countess kill are not covered by them |
| lane gap-classres (version not bumped; run `mxl` and read the `skill restrict`, `heat` and `trophy timer` lines, each `on: ...`) | **Hunter Steady Aim gate, Fire Sorceress Heat, trophy challenge windows** (plugin/src/skill_restrict.cpp: detour of the skill usability check `0x33f360`, modes 3-7; heat.cpp: detour of the mana regeneration `0x42e350`; trophy_timer.cpp: no hook, rides the goblins frame hook and the cube condition; off words `restrict`, `heat`, `trophy`) | (1) Druid with a bow (Hunter): look at Heartseeker and Cascade in the skill bar before any Steady Shot, then fire 4 Steady Shots and watch the Steady Aim counter. (2) Fire Sorceress with Molten Core: stand in the field with a full mana bar and wait; then cast Flamefront or Emberstep; walk into town. (3) Kill a trophy boss (e.g. Azmodan) and cube the heart: at once; after 15 s; after taking a town portal; after dying | (1) Heartseeker and Cascade cannot be used with no Steady Aim; the counter reads 1, 2, 3, 4; Heartseeker takes one charge per use. (2) The mana bar drains while Molten Core is active, fills while casting fire skills, holds in town. (3) The recipe works at once and not after 15 s, the zone change or death (a red chat line says the challenge is void). Tell me: whether the boss kill gives the challenge at all (nothing in the data says which skill a kill casts), the real time limit of each trophy, and whether the mana bar should say Heat |
| lane no-corpse-2 (version not bumped; run `mxl` and read the `corpse pickup` line: `on: stored corpses are picked up when a character enters a level (0x485350): picked N, kept N, faults N`; off word `corpsepickup`) | **No corpse ever: a corpse already stored in a save is picked up at load** (plugin/src/no_corpse.cpp hook on the level-entry function `0x485350` + D2R's own pickup `0x42b220`; docs/subsystems/death.md sections 8-9) | `py -3 tools/game_checks.py all nocorpse corpsepickup --slot N` (background mode; harness `state` lines `bodies other=.. stored=..`, client verb `ccorpses`). By hand: a character that died with the part off (`mxl-core-off.txt` = `nocorpse`) and is loaded with the part on | The body is not on screen, not after a respawn and not in town; the gear is back where it was; the next save has corpse count 0; a new death makes no body (server, client, saved list), the death spot is empty, gear / gold / xp unchanged, respawn after 5 s. Controls: with `nocorpse` off a body appears and follows to town; with `corpsepickup` off a stored body is loaded visibly |
| lane ns-plugin (version not bumped; needs the namespaced mod from ns-strings / ns-tables / ns-ui; `mxl` shows a `strings` line) | **Median text by key at run time** (plugin/src/strings.cpp: localization service, the plugin's own string ids for the NPC menu through a hook of D2R's numeric lookup `0x143e2b730`; docs/strings-namespace.md "Plugin uses") | Slot run: `mxl` must say `strings localization service on; string ids on`. Harness `mstr medianxl:AkaraMenu1b` (client): `service=ok text="Reset Stat/Skill Points"`, an id near 65000 and the same text via the D2R lookup. `game_checks.py all cain cainsub respec trophy lockout`: Akara's and Cain's lines show Median's text (not `medianxl:...`), the respec page header is the respec text, the trophy right click prints the challenge, a sealed dungeon prints its lines | Text of the lines equals Median's string; if a line shows `medianxl:<key>` the service could not find the key (namespace file not installed, or the loader refuses another package's key from a plugin) |
| lane median-ai (version not bumped; run `mxl` and read the `monster ai` line: `on: andariel_ai (AI 155), Summoner roll < aip3, MosquitoNest init`) | **Median monster AI: andariel_ai as AI id 155, Summoner first-branch rule, MosquitoNest init** (plugin/src/monster_ai.cpp; detours the AI table getter `0x4a36c0`, patches `0x5b4e49` / `0x5b4fed`, writes entry 83's init). Not yet seen in game: all slots were busy | Rebuild with tools/build.py, install, restart. `debug_mode`, then `mspawn` (or harness `h spawn 156` for Andariel) Andariel, Maghda and Radament near you; screenshots over ~30 s, `h state`. Then `mxl`: the `monster ai` line shows the counters. Also with `medianai` in mxl-core-off.txt (the line says `fallback`) | The monster must not stand still (the engine takes a 156-row monai.txt). Close: melee, with occasional skill 1 / 4. Far (aip3 distance or more): walks in, waits 15 frames after it has engaged. Mid range: skills 2 and 3 on an 11-frame cooldown. Counters for wait / attack / charge / walk / skills must all rise. Summoner (Act 2): first spell chosen by the aip3 roll, not by your resistances. A MosquitoNest (if enabled in the level) spawns its first mosquito after its init delay |
| lane waypoint-panel (version not bumped; `py -3 tools/ui_layouts.py` then install with the plugin, restart the game; run `mxl` and read the `waypoints` line) | **Waypoint panel lists every Median waypoint under its own act, more than 9 per tab** (plugin/src/waypoints.cpp: hook of the tab fill `0x1ea9b0`, relocated button table, 3 readers patched; HD layout `waypointspaneloriginalhd.json` with `buttonOffset` 100; data tools/waypoints_data.py) | (1) `mxl`: the `waypoints` line ends with `panel list has a button for 47` (or the plugin's own on-line). (2) With a debug character: `waypoint all set`, `waypoint tabs`, `waypoint open` (harness) and look at every tab. (3) Touch a real waypoint, click Duncraig, Tran Athulua, Skartara, Caldeum, Torajan Jungles, Vizjun, Silver City and the Act 5 button (level 242): each must travel there. (4) Setting `waypoints` in `mxl-core-off.txt` returns the old 9-per-tab panel (rollback). | Tab I 10 buttons (Rogue Encampment ... Duncraig last), II 11 (Tran Athulua, Skartara last), III 12 (Caldeum, Torajan Jungles, Vizjun last), IV 4 (Pandemonium Fortress ... Silver City), V 10 (Tur Dulra last), none cut off or overlapping the panel frame in HD. Seen in game (slot run, screenshots of all 5 tabs): the lists above. **Not yet seen: step (3), a travel click from a real waypoint object** (a click from the harness-opened panel reached the server and was refused with "Impossible") |
| lane waypoints (data + plugin check, no version change; rebuild with tools/build.py, install and restart) | **Median waypoints with numbers 50-90** (tools/waypoints_data.py writes actinfo.txt: Act 4's six free slots list silver_city, duncraig, tran_athulua, island_of_skartara, caldeum, torajan_jungles; plugin/src/waypoints.cpp read-only check, Off word `waypoints`) | (1) `mxl`: the `waypoints` line must say `47 waypoint levels, numbers up to 90 of 112 bits; panel has a button for 45, none for levels 155, 242`. (2) Open a waypoint panel with a character past Act 3 (tab IV is locked until D2R's act 4 intro quest): five tabs as before; tab IV lists the three Act 4 waypoints and then the six Median names. If the game fails to start or the panel is empty or broken, delete `data/global/excel/actinfo.txt` and `base/actinfo.txt` from the installed mod and report the errors.log line. (3) Touch the waypoints of Duncraig (153), Tran Athulua (147), Skartara (169), Caldeum (138), Torajan Jungles (141) and Silver City (139): the panel opens, the current level is marked, and from another waypoint the button for it is enabled and travels there. (4) Save and exit, reload: those waypoints stay activated; check normal and nightmare separately (bits are per difficulty). (5) Touch Vizjun (155) and the Act 5 waypoint (242): the touch must not crash; they have no button (expected, docs/subsystems/areas-drlg.md 3b). | Numbers above 38 are saved and travelled to without a crash; 6 of the 8 are listed in tab IV, 2 are not |
| next build after 0.46.0 (run `mxl`, read `act 2-5 quests`) | **Acts 2-5 quest rewards, Median's catalysts and the respec flag** (plugin/src/quests_act2_5.cpp; hooks a2q5 `0x5a5490` / `0x5a5360`, a2q6 `0x5a66b0`, a3q3 `0x5ef040`, a3q5 `0x5f0df0`, a4q1 `0x5e67c0` / `0x5e6660`, a5q2 `0x54c810`, a5q6 `0x54fa70`, respec bookkeeping `0x5d9ae0`; details docs/subsystems/quests-requirements.md section 5c) | `mxl` must say `act 2-5 quests on: ...` (10 hooks; `partial: N of 10` names a hook that failed). Use debug-friendly characters: (1) Act 2, **Nightmare**: kill the Summoner with quest 13 active; look in the inventory and on the floor; leave and re-enter the game, drop the catalyst, click any Act 2 NPC (Drognan, Atma). (2) Act 2 Normal: kill Duriel, talk to Jerhyn (his Duriel line). (3) Act 3 Normal: bring the Blade of the Old Religion (Gidbinn) to Ormus; repeat the same conversation. Also try Nightmare (3 items) and Hell (5). (4) Act 3: finish Khalim's Will (smash the Compelling Orb path) and talk to Cain in Kurast. (5) Act 4 **Nightmare**: kill Izual; drop the catalyst, click Tyrael in town. (6) Act 5: free the barbarians (Rescue on Mount Arreat) and talk to Qual-Kehk, per difficulty. (7) Act 5 **Hell**: with a level 110+ character kill Baal and stay in the Worldstone Chamber (also test with a second player in the chamber and one in town). (8) Akara respec: use Akara's reset line below level 51 (Den of Evil done) and again at level 51+; click it twice in a row at 51+ | (1) a catalyst of learning (`0o[ `) in the killer's inventory when the Summoner dies, once; the same game or a new game: clicking an Act 2 NPC hands out a replacement only while it is missing; Normal and Hell: nothing. (2) one Arcane Crystal (`qum `) with the vanilla reward, once. (3) 1 / 3 / 5 shrine consumables (`*_shrine_10`, random each) in Normal / Nightmare / Hell, once (a second conversation gives nothing). (4) one Arcane Crystal at Cain's line, once. (5) a catalyst of jewelcraft (`jcat`) in the killer's inventory, Nightmare only, once; Tyrael hands out a replacement while it is missing (and not at Izual's ghost). (6) runes on top of D2R's own three: Normal r08 r09 r10, Nightmare r15 r16 r17, Hell r22 r23 r24 (two or one fewer when quest bits 6 / 7 are set; expect the count 3 in a normal run). (7) a relic orb (`qrel`) for every player in the chamber at level 110+, once per character and difficulty; nothing in other areas. (8) **to check Median's intent**: D2Sigma replaces the respec bookkeeping so the respec token is never used up (at 51+ it is re-armed explicitly); if the line vanishes after the first use below level 51, the replacement did not take. Tell me, per step, what dropped and any difference from the above. Known gaps: no client notices (D2Sigma messages 0x5f-0x61), the drops go to the killer only (D2Sigma drops one per player on the ground). mxl-core-off.txt word `quests2` leaves it out |
| lane areas (data only, no version change; rebuild with tools/build.py and install) | **Median's own areas: map objects and monsters** (txt_migrate adds Median's table to ObjPreset.txt, rows Index 1000+; install_mod.py runs tools/ds1_remap.py on the installed tiles and prints `ds1 ids: ... type1_renumbered=4095, type2_renumbered=27526, type2_dropped=30`; audit with `py -3 tools/area_audit.py`, expect 0 problems) | Enter Median's areas through their portals / waypoints / quests (no warp command exists): Ruins of Ureh, Caldeum, Silver City, Trials of the Dimensional Labyrinth (a maze: level types 4, 17, 32-34), Heart of Darkness, Duncraig. Look for: the level generating at all (no crash, no assert dialog; the log `d2rloader.log` may show one-time ASSERTION blocks, send them), the exit portals / waypoints / doors / chests where expected, bosses present (e.g. the Duncraig arenas, Void traps) | Each area loads and has its objects and its boss; if an area is empty or full of wrong monsters/objects, tell me which area and what you saw. mxl-core-off.txt has no word for this (data) |
| next build after 0.43.0 (run `mxl`, read the `npc actions` line) | **D2R-native NPC services: Imbue (Charsi), Add sockets (Larzuk), Personalize (Anya), and the travel packages with their waypoint grants** (plugin/src/npc_services.cpp, read-only check of the NPC table `0x237ea60` and the client fix table `0x22a70e0`; no hook, no line of ours: D2R's own lines and server code do the work, docs/subsystems/npc-hirelings.md 1.6) | `mxl` must say `npc actions on: 6 menu lines (Akara, Cain); 8 slots are D2R's own, 8 of 8 D2R-native services match Median's rows; travel gates moved 1` (Tyrael's gate byte is moved from quest 26 to Median's quest 28 at load; `py -3 tools/game_checks.py all tyrael` reads his menu with the quest bits in each state). In game, Normal: (1) finish Tools of the Trade (hand Charsi the Horadric Malus), talk to Charsi, click **Imbue**, pick a normal-quality weapon or armor, confirm. Try a magic item, a socketed item and an item Median should accept. Open Charsi again. (2) Same with Larzuk after Siege on Harrogath (**Socket**: pick a socketable normal or magic item) and Anya after Prison of Ice (**Personalize**, type a name). (3) Reload the character after each and open the menu again. (4) Kill Andariel, then click Warriv: **go east** to Lut Gholein; do not touch the waypoint there, open the waypoint panel at any waypoint. (5) After Duriel, click Meshif in act 2 (sail east) and open a waypoint panel in Kurast Docks; after Diablo go through Tyrael's portal and open the panel in Harrogath. (6) Warriv act 2 (go west) and Meshif act 3 (sail west) | (1) The line shows only while the reward is pending, the panel opens, the chosen item is imbued (becomes rare) and the line is gone afterwards (reward spent, not repeatable; Median does the same). (2) Same for sockets (item gets its sockets) and personalize (name in the item). (3) The change persists in the save and the line does not return. (4)-(5) The arrival town's waypoint is already active (Lut Gholein 40, Kurast Docks 75, Harrogath 109) without touching it. (6) The west trips work and grant nothing. Tell me: whether each line shows at the right time, which items the panel accepts or refuses (Median's new bases and uniques), whether the log line count differs (`7 of 8` expected, Tyrael is known to differ: D2R gates on quest 26, Median on 28), and whether Tyrael offers a travel line at all. mxl-core-off.txt word `npc` leaves the npc actions out |
| next build after 0.42.0 (run `mxl` and read the `hirelings` line) | **Mercenary class bonuses and Kashya's hire gate** (plugin/src/hirelings.cpp; hook on D2R's mercenary stat setup `0x544f60`, which the hire, the save load and every level-up run; data: `equivalentcharclass` pal / sor for the act 2 and 3 hirelings) | `mxl` must say `hirelings on: class bonuses on 0x544f60 hooked, Kashya level gate cleared`; the log gets up to 8 lines `hirelings: class C id I level L str S dex D: N stats set`. In game, Normal: (1) hire a Rogue Scout (Kashya), a Desert Mercenary, an Iron Wolf and (act 5) a Barbarian; open the hireling screen (stats): resistances, damage, life regeneration and speed should be well above a plain D2R mercenary (Rogue: movement +100%, dodge; Desert: skill armor, crushing blow, damage resist; Iron Wolf: large energy and armor; Barbarian: strength / dexterity bonus). (2) Level the mercenary or save and reload: the bonuses are still there. (3) A level 8+ character who has not killed Blood Raven talks to Kashya: no Hire entry works. (4) Equip a Paladin-only item (shield or aura item) on the Desert Mercenary and a Sorceress-only item on the Iron Wolf; an Amazon-only item on the Rogue and a Barbarian-only item on the Barbarian | (1) numbers clearly higher than vanilla; the Fighter Mage type (Desert, third) also has fire / cold mastery. (2) unchanged after level-up and reload. (3) hire refused until the quest is done. (4) the class items equip (D2R's `equivalentcharclass`); if the Desert / Iron Wolf refuse them, `equivalentcharclass` for acts 2 and 3 is not honoured and the column should go back to blank. Tell me the `mxl` line, the stat values you see and what (3) and (4) did. mxl-core-off.txt word `hirelings` leaves the plugin part out |
| next build after 0.42.0 (run `mxl` and read the `requirement gates` line) | **Requirement gates on D2R's NPC service table** (plugin/src/requirement_gates.cpp; checks Median's npcext shop / gamble / hire flags and requirement rows against the static NPC table `0x237ea60`, writes only where they differ; data tools/npc_services_data.py -> mxl_npc_services.h) | `mxl` must say `requirement gates on: NPC table 43 entries vs 25 Sigma service rows: N services agree, 0 cleared, 0 hire gates set, M Sigma-only, 0 dynamic`. In game, Normal: (1) open Atma, Geglash (act 2 Harem), Cain in Lut Gholein and in Harrogath: Talk only, no Trade button. (2) Open Gheed, Elzix, Alkor, Jamella, Drehya, Nihlathak: Trade and Gamble (Nihlathak: Gamble only) work. (3) Kashya and Qual-Kehk before their quests (Blood Raven; Rescue on Mount Arreat): no hire; Greiz and Asheara: hire works. (4) Finish Blood Raven, talk to Kashya | (1) no shop (matches always-false row 32). (2) as listed. (3) the hire entry is refused before the quest and the log has no `requirement gates` write. (4) Kashya hires. Tell me the `mxl` line (the counts), and any NPC whose Trade, Gamble or Hire differs from the above. mxl-core-off.txt word `reqgates` leaves it out |
| next build after 0.48.0 (run `mxl` and read the `item generation` and `game end` lines) | **Mercenary equip lists, bonus drops per player, game-end reset** (plugin/src/item_gen.cpp `MercRequirement`, game_end.cpp, quests_common.h `DropBonusPerPlayer`; data tools/txt_migrate.py -> mxl_hirelings.h `MercClasses`) | Normal: (1) hire a Rogue, a Desert Mercenary, an Iron Wolf and a Barbarian and try to put on them: Rogue bows only (no crossbows or melee weapons, no shields); Desert Mercenary spears and polearms (no swords, no auric shields of other types); Iron Wolf swords and scepters; Barbarian swords and two-hand swords as Median's hireclasses. (2) Kill Andariel in a TCP/IP game with two players: each player gets one catalyst of disenchantment on the ground; kill her again: none. (3) Same for the Summoner (Nightmare) and Izual. (4) Leave a game and make a new one with the same character: the cube crafts that are once per game (dungeon key) work again | (1) refused items give the 'cannot use' reaction; the `item generation` line counts `mercenary equip refused`. (2)-(3) one item per player per kill, lying where the boss died. (4) the key recipe works again; the `game end` line counts the games left. Tell me which class accepts or refuses what differs from the lists. mxl-core-off.txt words `gameend` and `classlock` leave the parts out |
| lane pa-damagered (version not bumped; run `mxl`: the `combat` line must end `hooks 0x44ef70 ok, 0x450670 ok, 0x4523e0 ok`) | **Damage reduction stats 184/189/417 on the incoming damage** (plugin/src/combat.cpp `HitStepHook`, combat_logic.h `ReduceField`; off word `damagered`) | `py -3 tools/game_checks.py all damagered` passed on 2026-10-22. By hand: `stat player 39 set 200`, `stat player 40 set 0`, `stat player 373 set 4`, `hit player fire 100000`: the line ends `field=6250` (25000 without the stat) | Not run in game: a monster as the defender (monprop `time` / `stam` rows carry 189 / 417), poison and leech entries |
| lane caps-events (version not bumped; run `mxl` and read the `combat` line) | **Max resistance 90, absorb credit stats, mercenary avoid caps** (plugin/src/combat.cpp; patches the `0x5f` clamps at `0x4524dd` / `0x14e7294` / `0x14f4686`, hook on the absorb step `0x450670`, `0x44ef70` accepts hirelings via `0x3af240`) | `mxl` must say `combat on: ... resist cap 75+max (max 90, 3/3 clamps), absorb credit stats 184/189/417; hooks 0x44ef70 ok, 0x450670 ok`. Background mode (harness): `h stat player 39 set 300`, `h stat player 40 set 20` (max fire), `h stat player 7 set 512000` / `6` (life), `goto 2` on the console, `h spawn 383 1` (Skeleton Mage, fire), read `h state` life every 30 s: fire resist 0 loses X per 30 s; 300 with max 0 / +10 / +20 should lose about 25% / 15% / 10% of X (95 would show 5%). Absorb: `h stat player 142 set 40`, `h stat player 446 1 set 50`: the net loss rises (credit halved), the log has `combat: absorb of N healed M (layer 1)`. Mercenary: hire one in act 1 and give it 100%+ dodge or avoid (a ring with the stat): its hit chance stays under the 60+max cap | Resist caps as above (CAN be seen on the character sheet too: Fire Resist capped at 90 with +20 max). Absorb: 446 / 184 / 189 lower the healing only, never the damage cut. Mercenary resist 90 cap and avoid cap: not exercised yet - tell me what the hireling panel shows with stacked resistances. mxl-core-off.txt word `combat` leaves all of it out |
| 0.41.0 (run `mxl` and read the `npc actions` line) | **NPC menu actions: Akara respec and Cain's crafting materials** (plugin/src/npc_actions.cpp; hooks the NPC menu builder `0x1147a0` and the menu packet handler `0x4b0470`; table tools/npc_actions_data.py -> mxl_npc_actions.h) | `mxl` must say `npc actions on: 6 menu lines (...); N stubbed services`. (1) Normal: finish Den of Evil (this sets the respec flag, quest 41 bit 1) with a character that has spent some stat and skill points, then click Akara: the menu must list Talk, Trade, **Reset Stat/Skill Points**; click it. Open Akara again. (2) Before rescuing Cain: click Cain in town (any act): his menu shows Talk, **crafting materials**, Identify (Identify only with unidentified items); click crafting materials. Then finish the Search for Cain (talk to Akara) and click it again; click it a third time; drop the cube and click again. (3) Kill Andariel (Normal) so the Sisters to the Slaughter quest is done, click Cain's crafting materials; drop the catalyst and click again. (4) Read the log's `npc actions:` lines. (5) Open and close the Akara and Cain menus several times; open the Larzuk, Charsi, Anya, Warriv, Meshif and Tyrael menus | (1) Stats and skills are reset as D2R's own respec does (points back in the unspent pool, equipment that no longer fits is unequipped); the line then does nothing more (the vanilla respec quest is used up). (2) Before the rescue nothing happens (log `requirement not met`); after it a Horadric Cube lands in the inventory once; a second click gives nothing while you hold one, and the cube again after dropping it. (3) A catalyst of disenchantment (`3o[ `), not twice; Nightmare adds the catalysts of learning and jewelcraft after their Nightmare quests (rows 20, 21). The menu closes after every click. (4) Log lines `done` / `requirement not met` / `nothing to do` with the kind (0x10 + npcRow*16 + slot) and NPC class. (5) No crash, no duplicate lines, other menus unchanged (Larzuk, Charsi, Anya and the travel lines are stubs and are not drawn). Tell me: whether the lines show and look right (text, order), whether the respec really resets skills and stats, whether a line stays visible while its requirement fails (known), anything odd around Identify. mxl-core-off.txt word `npc` leaves it out |
| 0.40.0 (run `mxl` and read the `goblins` line) | **Treasure goblins** (plugin/src/goblins.cpp; hooks the server game frame `0x406550` and the kill wrapper `0x515640`, spawns with `0x4929e0`) | `mxl` must say `goblins on: tick on game frame, ...`. To provoke one quickly, set the environment variable `MXL_GOBLINS_FORCE=1` before launching D2RLoader (every roll passes; `=2` also skips the 'killed something in the last 15 s' test). Barbarian in Normal, leave town to the Blood Moor, kill one monster, then wait: the roll runs on game-frame multiples of 375 (every 15 s of game time), so within 15 s a goblin should appear 8 sub-tiles right/down of you. Run `mxl` again: the goblins line shows `N spawned (last <monster id> in level 2)`. Without the variable (real odds): fight continuously in the Blood Moor for several minutes: the Blood Moor chance is only 4/1024 per roll (one per ~250 rolls, about an hour), caves and most later areas 10/1024 (one per ~100 rolls, about 25 minutes), the Mirror Temple 16/1024; each extra player lowers it by 10% | A goblin (`treasure_goblin` id 2791 at most levels, also `shiny_hoarder` 2792, `arcane_collector` 2796, `glowing_baron` 2798) stands next to you; it runs away (AI OblivionKnight, speed 7) and drops gold, runes, jewelry and rare/Sacred gear from the `Goblin` treasure class when killed. Standing in town, being dead, or not fighting for 15 s gives none. The log has `mxl-core: goblin <id> spawned in level <n> near player <id> (frame <f>)` for the first 20. Tell me: whether the goblin shows up, where (inside a wall/off-screen?), whether it has the right name, whether it drops, and whether anything in the game misbehaves (a crash on game exit, kills not counted). mxl-core-off.txt word `goblins` leaves it out |
| 0.39.0 (run `mxl` and read the `act 1 quests` line) | **Act 1 quests: Griswold's Heart, Andariel catalyst, catalyst re-issue** (plugin/src/quests_act1.cpp; hooks a1q4 event 11 `0x5e0830`, a1q6 events 8 and 0 `0x5e1f00` / `0x5e1d30`, item generator `0x43cd50`) | `mxl` must say `act 1 quests on`. (1) Barbarian, Normal: finish Search for Cain (rescue Cain in Tristram, talk to him), then talk to Akara. (2) Normal: kill Andariel with quest 6 active; look in the inventory and on the floor. (3) Drop the catalyst (or sell it), then click Warriv in town. (4) Reload the character, join a new game in Normal and repeat 3. (5) Nightmare: kill Andariel again; click Warriv | (1) Griswold's Heart (Normal base, code 600) appears in the inventory at Akara's reward, together with the ring, once; Nightmare and Hell give the (N) / (H) versions. (2) A catalyst of disenchantment (`3o[ `) lands in the killer's inventory when Andariel dies (Normal only); no second one on a second kill. (3) Warriv hands it out again while it is missing, not while you hold one. (4) Same in a new game (the flag is a quest-record bit, quest 47 bit 0, so it is saved). (5) Nightmare gives no catalyst. Tell me: whether the Heart is the right unique (name and stats from uniqueitems rows 69-71), whether the log has a line `quests: Griswold's Heart ...`, whether Andariel and the quest still complete normally, and whether anything odd happens with the save. mxl-core-off.txt word `quests` leaves it out |
| 0.37.0 / 0.38.0 (hooks switched on in 0.38.0; run `mxl` and read the cube line; 0.38.0 also gives op 30 the +skills) | **Cube recipe conditions** (cubemain ops 29-42, cubemainext second condition and gold cost; stat ids in cubemain remapped) | Rebuild the data (python tools/build.py) and install. `mxl` must say `cube conditions on: 542 recipes`. In the Horadric Cube: (1) Wirt's Leg + Tome of Town Portal in town opens the Cow portal, in the field the cube makes nothing (op 36, recipe 2); (2) a recipe with a chance (ssgl + scum, recipes 5236-5238, op 37) works only some of the time; (3) the Boss Killer Ring recipes (op 33 state 893, e.g. ssgl + f700) work normally and stop while that state is active; (4) cubemain rows 6327-6329 (ext op 3: stat 532 at least 132 / 135 / 138, cost 50,000 / 100,000 / 200,000 gold) are offered only with that stat and the gold; (5) any of the 65 recipes with a gold cost (5,000 to 1,000,000 gold) is not offered when carried + banked gold is short (paying the gold: next row); (6) the 19 op-38 'useitem' recipes (6350-6368) are offered only after the craft that sets their flag (next row); (7) recipes with a stat condition on an item (amulets/rings/charms upgrades) now compare the right stat | The conditions hold: recipes show up in the cube only when they should (the Cow portal only in town). Tell me anything that becomes craftable that should not, or a recipe that no longer works; the log lists a line if the record pointer check fails. mxl-core-off.txt word `cube` leaves it out |
| 0.39.0 | **Cube craft flags and gold payment** (craft_flags.cpp; hook on the recipe executor 0x5269c0; `mxl` must say `craft flags on: 256 output effects`) | (1) Player flag: as an assassin with `RathmasSupremacy2`, craft recipe row 6369 (the upgrade of that quest item, sets player flag 1); then the op-38 recipe 6350 (same input item, output `useitem`) must be offered in the cube; before the craft it must not be. (2) Game flag: craft a dungeon key, recipe row 7100 (`UpgradedBossKillerRing` + `erun` + `f700`, sets game flag 50); a second try in the same game is refused, after leaving and creating a new game it works again. (3) Gold: recipe rows 6327-6329 (stat 532 at least 132 / 135 / 138; 50,000 / 100,000 / 200,000 gold), or any recipe with a gold cost: carried plus banked gold is reduced by the cost after the craft, carried gold first, then the bank | Flags unlock and guard as described and are gone in a new game; gold drops by the cost (read it on the inventory screen and the stash; if the carried gold only updates after reopening the inventory, say so, a stat packet is then needed). mxl-core-off.txt word `craftflags` leaves it out |
| lane sigma-behaviours-a (version not bumped; run `mxl` and read the `npc actions` line, it ends `respec confirm on`) | **Akara's respec confirmation and the trophy hover text** (plugin/src/npc_actions.cpp `OpenConfirm`, item_spells.cpp `RevealTrophy`; data tools/npc_actions_data.py, tools/txt_migrate.py `item_spells` / `item_level_line`; harness `menu confirm|yes|no`) | (1) `py -3 tools/game_checks.py all respec`: Akara's respec line opens D2R's Yes / No page (header: the respec text), `menu no` leaves strength unchanged, the line again then `menu yes` resets the stats. By hand: click Akara's Reset Stat/Skill Points line, answer No, then Yes. (2) `py -3 tools/game_checks.py all trophy`: `item a56 inv` (Heart of Azmodan), hover it in the inventory, then `use a56` (right click). (3) Types with `NoShowILvl` (runes, trophies, ...) never show an item level line, also with `display_item_levels = true` in d2rloader.toml | (1) The click shows the page and sends nothing; No closes the menu with the stats as they were; Yes respecs once. (2) The tooltip says "Right click to reveal trophy challenge" (not the challenge); the right click prints the challenge in the message log, title gold, and the item stays; the check reports `sent` +10 per use. (3) No "Item Level" line on those types. Seen in game (slot 3): (1) and (2) (`respec_confirm.png`, `trophy_revealed.png`); not seen: (3) |
| lane approx-items (version not bumped; run `mxl` and read the `npc actions`, `dungeon lockout`, `client messages` and `items` lines) | **Cain submenu, dungeon countdown, party experience** (plugin/src/npc_actions.cpp, dungeon_lockout.cpp, client_messages.cpp, items_ext.cpp; off words `clientmsg`, `lockout`, `npc`, `partyxp`) | (0) `cainsub` check passes (first talk with a Cain takes ~30 s before the list appears; the line is read from the record after the speech). (1) Talk to any Cain, click "crafting materials": the list is replaced by the entries whose requirement holds (horadric cube after the rescue, catalysts after their quest while you lack them); click one: the item is created; ESC / talk again shows the normal menu. (2) Enter a Median dungeon with a lock time (e.g. via `b62X` on Hell, level 253): orange "Closing in: mm:ss" + "ONCE YOU EXIT YOU CANNOT GO BACK" at the top of the screen counts down; leaving the level hides it. (3) Party of two near a monster: each gets the monster's whole experience, range about 179 units (two-player game not run yet) | Submenu entries show and give the item; the countdown runs and matches the sealing time; both party members gain the full experience |
| lane dungeon-lockout (version not bumped; run `mxl` and read the `dungeon lockout` line) | **Dungeon lockout and level entry requirements** (plugin/src/dungeon_lockout.cpp; hooks the warp action `0x491ff0` and the portal object operate function `0x58f680`; rules from D2Sigma `0x5d810` / `0x5cee0` / `0x5d9d0`) | `mxl` must say `dungeon lockout on: 162 levels; tile warps on, portals on`. Hell character of class Amazon, level about 100, Act 5 town. (1) Entry requirements: use a key or scroll that opens a level with a Hell level requirement above your level (e.g. a level 125 area) and step into the portal; Normal / Nightmare character with a Hell-only portal (level 138 and up); a non-Druid in a Mirror Temple (256-262). (2) Clock: open a portal to a level with a short lock time (157 Butcher's Lair, 20 s; 159 Proving Grounds, 20 s; or 251 with Scroll of Summoning, 60 s), step in, leave by the town portal inside the lock time and re-enter by the same portal: allowed. Wait out the lock time (inside or outside) and try again. (3) Stairs: a level with a lock time reached by stairs or a tile (132 World Stone Keep from the Throne of Destruction, 1200 s; 268 / 269 Heroic Library 6 / 7 share one clock) starts the clock too. (4) New game: leave the game, make a new one, repeat (2) | (1) The portal does not take you: the character stays where he is and plays the generic "can't do that" reaction; log line `lockout: entry requirements not met, refused (src -> dst)`. Meeting the level and difficulty enters normally. (2) First entry logs `lockout: clock started (src -> dst)`; entering again inside the lock time works; after the time has run out the portal / stairs no longer take you in (log `level sealed, entry refused`), the town portal out of the level still works. (3) Same for stairs. (4) The new game has no seals. Tell me: whether a refusal shows or says anything on screen (Median shows a text and a timer widget that D2R does not have), whether the portal / warp clicks leave the character in a stuck state, whether the one-way portals (objects 600) are refused too (if not, they use another operate function), and whether the lock time feels right against the table (docs/plugin-spec.md, dungeon lockout). mxl-core-off.txt word `lockout` leaves it out |
| data + plugin | **Skill tree look and pages: Median's tab titles, stone, arrows, all pages (8, Sorceress 9)** (bug #3; tools/skill_tree_art.py + ui_layouts.py; 9 tab pictures per class; plugin skill_tree.cpp makes pages 4-9 selectable and fills them: `mxl` shows `skill tree on: 13 sites + tab setter hook`; tools/skill_icons.py gives every skill its own icon) | Open the skill tree (T) in HD as a few classes (Barbarian, Sorceress, Paladin...) and click every tab; then press G and do the same in classic mode | HD: a row of 8 tabs with Median's titles (e.g. Barbarian: Nomad, Earthshaker, Windcarver, Elementalist, Warmonger, Shaman, Mastery, Reward), the clicked tab lit, a dark brown Median stone, sockets under every skill icon and Median's arrows between them (they should point the way the skills depend on each other); icons sit in the sockets. Classic: Median's stone with a column of 8 titled tabs on the right and sockets/arrows behind the icons. Every tab shows its skills on its sockets (Barbarian tab 7 Mastery: 9 icons, tab 8 Reward: 7). Report if only 3 tabs show art or tabs 5-8 act like tab 4, a socket stays empty, a tab shows the wrong class's picture, icons are off their sockets, or the panel is blank (screenshot). Sorceress: 9 tabs (Arcane, Fire, Lightning, Cold, Poison, Melee, Mastery, Coven, Reward); the other classes show 8 tabs and a blank 9th cell, and a click on it changes nothing (checked 2026-10-22, HD and G) |
| data | **Median stash size: 14 x 14** (personal and shared pages; inventory.txt Big Bank, HD stash panel with Median's art) | Open the stash: personal tab and the shared tabs. Put items in the far corners (column 14, row 14), switch tabs, leave and reload; check the shared stash still loads for another character | Median's stash art, 14 x 14 grid lined up with it (grid, tabs and gold box confirmed 2026-10-14), items scaled like the inventory; Personal/Shared tabs centred above the grid where Median's gold box was; Median's gold box now at the bottom with D2R's gold button and amount on it; shared-stash arrows and gold withdraw work; items stay put after reload. D2R's Gems/Materials/Runes tabs unchanged. Backup: mxl-manual-backups/all-before-14x14-stash. Also note: since this build the game logs a 'leaked Stats' check when it closes; tell me if anything misbehaves around quitting |
| data | **Median inventory and cube sizes: 15 x 10** (inventory.txt gridX/gridY; HD panels with Median's own art, tools/ui_panels.py + ui_layouts.py) | Open the inventory (I) and the Horadric Cube in HD. Move items into the new rows/columns, equip items in every slot, swap weapons (W), transmute something; save and reload; press G for classic | Inventory: Median's panel, 15 x 10 grid lined up with the art, equipment slots where Median has them, gold box bottom left. Cube: Median's crafting panel, 15 x 10 grid, transmute button under it. Items stay where they were after reload. Report anything misplaced (a screenshot helps). Press G: classic mode now has Median's art for inventory and cube (15 x 10 on scaled grids; items are smaller than in HD), check I / cube / C / stash (both tabs and shared pages) / a vendor: items on the grid cells, nothing overlapping (screenshot). Backup of all characters: mxl-manual-backups/all-before-15x10-inventory |
| data | **Median character sheet** (statsheet page 0 as the HD background, D2R stat widgets moved into its boxes; tools/ui_panels.py 'charsheet', tools/ui_layouts.py char_sheet()) | In HD press C; check with points to spend and with a weapon equipped; hover the stat labels | Median's panel with: name and Level / Class in the top bar, Life / Mana / Stamina and experience in the four bars around the circle, Strength / Dexterity / Vitality / Energy (value box left of the label) with the +1 buttons right of the rows, Fire / Cold / Lightning / Poison and Defense in the boxes, damage and attack rating of the left and right skill beside the weapon portraits, stat points remaining at the bottom. Report text outside its box, missing numbers or buttons off the rows (screenshot). Known: pages 2 and 3 of Median's sheet (extra stats) are not built |
| data | **Median stat pages as Advanced Stats rows** (itemstatcost advdisplay: 96 stats of Median's sheet pages 2-3, descfunc 19 for D2R's printf texts; tools/stat_screen.py, txt_migrate.py advanced_stats; docs/subsystems/stat-screen.md) | In HD press C, click the arrow on the sheet's right edge; scroll the list; equip items with speed / absorb / resist / damage mods | The list starts with thirteen rows shown even at 0 (attack rating, block, five speeds, six resistances), then only the stats the character has, texts like "+30 to Strength" / "+20% Faster Cast Rate" (no raw %d / %+d, no doubled value). Report garbled lines, a row for a stat Median's sheet does not show, or a stat that is missing. Item tooltips of those stats should read the same way |
| data | **Median trade window, NPC store and in-stash cube sizes** (inventory.txt Trade Page 1/2 = 7 x 15 each, Monster = 15 x 15; HD panels tradelayouthd / vendorpanellayouthd / bankexpansionlayouthd with Median's trade.dc6 and store.dc6 art; materials tab cube view 15 x 10; tools/txt_migrate.py, ui_panels.py, ui_layouts.py) | In HD: (1) trade with a second player (TCP/IP test): open the trade window, move items into both columns, accept; (2) open Gheed, Charsi, Akara and a gambler: all four tabs, buy and sell, repair (Charsi), refresh (gambler); (3) open the stash, Materials tab, put items into the cube view and transmute | (1) Two 7 x 15 grids side by side on Median's trade art, names and accept buttons in the header bars, gold under each grid; check which side is yours (left is 'them', right is 'us' in the layout, swap TRADE_GRIDS/TRADE_BARS in ui_layouts.py if wrong). (2) 15 x 15 store grid on Median's store art, D2R's tabs lined up over the four tab slots (none drawn pressed in the art), gold text in Median's gold bar at the top, repair/refresh buttons under the grid not overlapping it. (3) The cube view is a 15 x 10 grid on pasted art over the old recess (side stubs of D2R's art may show), items match the Horadric Cube panel; transmute button below. Classic (G): the trade window has Median's art and two 7 x 15 grids, untested (needs two players): check names, accept buttons and gold under the grids. Report where the item cells and art disagree (screenshot) |
| data | **Cold effect on monsters** (coldeffect -20, was read as 236) | Chill monsters (any cold skill or cold damage item) | Chilled monsters slow down (Median: -20%) instead of speeding up |
| data | **Monster sequence skills** (monstats Sk*mode `mqN` -> sequence names, 1,152 slots) | Fight monsters that raise or revive (Fallen Shamans, Greater Mummies, skeleton-raising casters), charging monsters, Sand Maggots | Shamans revive Fallen, mummies raise, maggots burrow and lay eggs, chargers charge; no monster stands still where it should use a skill |
| data | **HD item pictures: Median's own art** (tools/item_art.py, 987 base items + 45 uniques + 22 set items) | In HD, open a vendor (Gheed, Charsi, Akara) and the stash; look at Median-only items (charms, crafting items, Median armors, quest items); compare with G | They show Median's real picture (upscaled from classic, a bit soft) instead of a D2R look-alike; nothing missing or misplaced in the grid |
| 0.36.0 | **Whirlwind hit rate as in classic Median** (1.13c table: a hit every 4-16 frames by weapon speed) | barby: Whirlwind through a pack with the axe; if you have one, try a faster weapon or an IAS item | Noticeably more hits per spin than before (D2R's own timing hit about half as often). Tell me how it feels against classic Median; the log records the speeds of the first hits |
| data | **HD body animations for sequence skills** (tools/hd_skill_anims.py) | barby (level 10): cast Whirlwind outside town; also leap_2 if learnable. Other classes: Assassin smg (Blade Fury look), any class with hurricane_2 / virulence items | The HD Barbarian model spins during Whirlwind like D2R's own Whirlwind; check classic mode (G) too; leap_2 uses Leap's animation |
| 0.35.0 | **States fix off by default** (bug #22: D2RLoader syncs Median's states itself) | Load barby (now level 10, 50 energy, 9 skill points), go to the Blood Moor: hover and attack monsters; cast Whirlwind; play a while with buffs/auras | Monsters highlight and can be attacked; Whirlwind shows its spin; buffs show their effects; no random states, no crash |
| data | **Whirlwind and every other sequence skill** (2026-10-14: moves and hits now; spin effect still not drawn, server sets state 174, testing client state sync with 0.34.4 and the states fix off; anim GH -> SQ: they played the knockback and never started; plus D2R's stop functions and the overlay Character column) | barby: walk out of town (Whirlwind does not work in town), cast Whirlwind at the ground across monsters 3-4 times, let go once mid-spin. Any class: other multi-hit / sequence skills (Zeal-like strikes, Strafe-like volleys, Fend) | The character spins with D2R's whirlwind effect, moves to the clicked spot, hits monsters on the way and stops cleanly; the other sequence skills play their attack sequence instead of a knockback. Tooltip as before; G for classic |
| data (deferred by the user, 2026-10-07) | **Whirlpool, final pass** on a new Paladin (`paladin`): HD looks (missile_hd.py), sounds (Median's sound rows) | New Paladin; get Whirlpool (axe/item written into the save, or Leather of Aut), any melee weapon, hit a monster; also press G for classic graphics | HD: a blue tornado-style swirl on the target (placeholder for Median's ColdFuse), cold bolts flying out (Frozen Orb's), a bone-spirit burst when each swirl ends; the sewer-water sound plays with the swirl. Classic mode: the bolts and burst show, the swirl itself is invisible (ColdFuse art not ported yet). Tooltip: Whirlpool, % weapon damage, "item granted skill"; no crash |
| data (art and Median areas deferred by the user, 2026-10-07; hovering is bug #22) | **Median monsters (Phase 5 step 2)**: own animations + timing (animdata), HD look-alike model | Leave town in Act 1 and fight; press G now and then. Also try a Median-only area (e.g. a Trial) | HD: monsters look like D2R monsters as before, but attack/move with Median's timing; they can be hovered and targeted. Classic (G): Median's own monster art. Note any monster that is invisible, stuck, untargetable, or crashes the game (name + area). Player attack speeds now follow Median's animdata (e.g. Sorceress staff attack) |
| data | **Classic graphics (Phase 5 step 1)**: Median's item pictures (542 .dc6), missile and overlay animations now in the mod | In game press G (classic graphics). Open the inventory and a vendor (Gheed, Charsi): look at Median-only items (charms, runes, uniques). Cast Whirlpool on the Paladin; cast a few Median skills with missiles | Items show Median's own pictures in classic mode (in HD they keep the look-alikes). Whirlpool's swirl (coldfuse) is visible in classic mode. If classic mode shows nothing for these or crashes, D2R does not read classic art from mods: note which |
| 0.33.0 (deferred by the user, 2026-10-07) | **Automap in Median-only areas** (bug #15) | Enter an area on Median's own level types: Caldeum or Caldeum Library (Act 2 town area), Ruins of Ureh, Silver City, Corrupted Abbey, a Trial (Vasily, Bul-Kathos), a Dimensional Labyrinth. Open the map (Tab) and walk around | Walls and floors appear on the automap as you explore (before: an empty map there). Map pieces may look slightly off (Median art vs D2R's automap sprite); no crash when opening the map or changing area. Heart of Darkness / End of Time (type 50) have no Median automap rows, so they stay empty |
| 0.32.0 | **Phalanx** (Amazon phalanx_2; missile do 4 -> 46 / client 69 -> 14) and the **nova fix** (missile hit 66 never fired before) | Amazon: cast Phalanx at a pack. Any class: retest the 0.26.0 nova skills (frigid_nova, coronation, hammertime) | Phalanx: an invisible line walks out and leaves arrow-shooting tiles every few steps (the tiles may show only on the server side if their look is missing). Nova: a ring of sub-missiles when the missile ends. No crash |
| 0.31.0 | Formula functions itemstat / tabpoints (hidden passives: helmet/shield armour bonuses, skills_2062-2069 and 3001; Amazon skills_1473) | Character sheet with and without a helmet / shield equipped; compare Defense and the related bonuses before and after equipping | Bonuses that depend on the helmet or shield's own stats now change when you swap them (before: they acted as if nothing was equipped). No crash when equipping, swapping weapons (W) or dropping items |
| data | **Skill tree rules** (devotion locks, "up to three masteries"; in the skpoints formulas, bug #4) | Amazon: put a point in one devotion (e.g. Bow Devotion), then try another devotion. Any class with mastery unlocks: learn three masteries, then try a fourth | The second devotion and the fourth mastery refuse the point (the + button does nothing / shows no cost) |
| 0.30.0 | **Habeas Corpus** (Paladin; missile hit 73 -> slot 65) and **Resurrect** remembering what it raised | Paladin with Resurrect and Habeas Corpus (Item Spawner / skill points): kill a monster, Resurrect its corpse, then cast Habeas Corpus elsewhere. Also cast Habeas Corpus before ever resurrecting | After a Resurrect, Habeas Corpus leaves corpses of that monster type where it lands (D2Sigma spawns them in the "dead" mode; if D2R shows live monsters or nothing, note which). Before any Resurrect it does nothing. Resurrect itself still works as before; no crash |
| 0.29.0 | **Mana costs from the plugin**: summon costs that grow with petmax (16 summons, calc7) and Median's mana cost % (stat 228) | Cast a summon such as Blood Skeleton or Summon Sinner a few times and watch the mana it takes; equip an item with "+/-% mana cost" (stat 228) and cast any skill with and without it | Summons cost a share of max mana (D2Sigma's formula); with the item the drain changes by that %. Tooltip Mana Cost lines still show the plain table value for these (tooltips are not hooked). No crash on casting. If a skill suddenly costs nothing or everything, note which |
| data | **Mana costs** (D2Sigma's skills2 formulas -> skills.txt mana/lvlmana; tooltip type 77) | Any class skill: hover it in the skill tree, then cast it repeatedly | The tooltip shows a Mana Cost line; casting drains that much mana (e.g. Whirlpool about 75 at level 1, Fire Arrow about 3) and stops when mana runs out. Before this, skills cost only their minimum mana |
| data | **Bug #7**: string IDs below 65536 | New character; talk to Gheed (and Akara, Kashya, Charsi, Warriv) the first time; read a few item and skill tooltips | Gheed greets with his own line ("Good day to you partner! ..."), not "Arcane Ape"; no other text looks out of place |
| 0.28.0 | Missile hits: level portal (srvhit 69, D2Sigma 30), heal ally (67, D2Sigma 34), missile at owner's target (62 + client 6), client nova (client 7) | Portal: skills ancient_gate / judgementwander (a red portal where the missile lands; the one-way kind opens once per game). Heal: monster skills (sinew_shaper and others) heal their allies: hurt a pack, watch the healer's missiles top them up. Nova: frigid_nova, coronation, hammertime (the ring of bolts is now drawn on your screen too) | Portal opens and leads to its level; the hurt monsters' life goes up; nova ring visible; no crash |
| data | **Bug #18 stopgap**: HD pictures for all Median items (tools/item_hd.py) | Open a vendor (Charsi, Gheed, Akara) and browse every tab; buy a quiver; open the debug-mode Item Spawner and scroll its lists | Every item shows a picture (vanilla look-alikes: Median items share D2R art for now); no crash, no freeze at the vendor |
| 0.27.0 | Missile hit owner state (srvhit 63, D2Sigma 71) and summon (srvhit 68, D2Sigma 41) | State: skills Fire Ball (Median's), vanquish, brace_for_impact, inoculation; Summon: monsters corrupted_necromancer, councillor_ormac, sinew_shaper | State: after the missile lands the CASTER gets the buff (its stats show; the state's visual may be missing). Summon: a minion appears where the boss's missile lands; no crash |
| 0.26.0 (fix 0.32.0) | Missile hit nova (srvhit 66, D2Sigma 77) and explosion (D2Sigma 69 -> D2R hit 1) | Nova: skills frigid_nova, frigid_domain, coronation, hammertime, hurricane_2. Explosion: skills gorefest, wychwind, flamestrike, earthquake_2, mana_pulse, batstrike, warp_crash | Nova: when the missile ends, a ring of sub-missiles flies out (frigid nova: a ring of cold bolts); no crash. Explosion: the hit damages every monster in a small radius around the impact, not just the one hit |
| 0.12.0 | Mystic orbs (bug #11) | Buy an orb from Gheed (e.g. a stat orb), right-click it, click an armour or weapon in the inventory | Cursor changes like Identify; the item gains the orb's bonus and +4 level requirement; the orb is used up. Applying the same orb beyond its maximum (5 for normal orbs), or to an item it doesn't fit, does nothing and keeps the orb. Also try one on an equipped item |
| 0.12.0 | Dyes (bug #11) | Right-click a mystic dye, click an armour | Dye used up, no crash (the colour won't show: D2R draws items without Median's dye) |
| 0.14.0 | Arcane shard help | Hover an arcane shard, Arcane Crystal, Oil of Craft, a catalyst | The recipe help text shows in the tooltip (check the line order); right-click does nothing and the item stays |
| 0.14.0 | Containers (gem/rune clusters) | Cube Oil of Craft + a perfect gem -> gem cluster; carry 2-3 more of that perfect gem (inventory and cube; stash too while in town); right-click the cluster | The gems disappear, the cluster's count goes up by one each (up to 50), the cluster stays. No duplicates or ghost items after moving things around / relogging |
| 0.13.0 | Keys open portals | In Harrogath (Act V): right-click dimensional_link (`ktox`) or mind_warp (`kfau`). In Act IV town: key_of_lies (`kbel`) or key_of_sin (`kazm`). Riftstones `cr01` (Act I), `cr02` (Act II), Hell only | A red portal opens next to you, leads to the level and back. A second use of the same key in that game does nothing. `ktox`, `ksco`, `ktpx` and riftstones are used up; `kbel`/`kazm`/`kfau`/`tbr` stay (0.14.0) |
| 0.13.0 | Key in the wrong act | Right-click key_of_lies in Act I town | "Can't do that" message, key kept |
| 0.13.0 | One-way portals | charged_riftstone_16 (`cr21`, Act V) or scroll_of_summoning (`b60X`, Act I) | A portal (Median's one-way portal object) opens; check it can be entered |
| data | Item skill procs/oskills (bug #16) | A unique with "+N to <Median skill>" or "chance to cast", e.g. Book of Triune (Mind Control) | Tooltip and proc name the right skill |
| 0.8.0 | Synergies (syn1-syn6) | An item with "+X% to <skill>"-style synergy bonuses; compare the skill's damage/tooltip with and without it | Damage/tooltip changes with the item |
| 0.8.0 | Item max-level bonus (skcp) | An item with "+N to maximum level of <skill>" | That skill can take N more points |
| 0.9.0 | Base-level skill values (bl12/bd12...) and weapon damage % (wdm) | Skill tooltips that show per-level values or "% weapon damage"; raise the skill by a point and check the value moves | Non-zero values that grow with points spent (not with +skill items) |
| 0.11.0 | State-dependent formulas (hasstate) | Fire Ball's poison interaction, or any skill that changes while a buff/curse is on (e.g. Meditation, shrine effects) | Values change when the state is active |
| 0.11.0 | Layered stat formulas (statlayer) | Holy Shock tooltip with "activation frequency" items | Values include the per-skill item bonus |
| 0.10.0 | Missile formulas (msyn, blvl) | A skill whose missile damage/size scales with the skill's points or synergy items (32 missiles use blvl) | Missile effect grows with points spent |
| 0.9.0 | "Maxed skill" effects (bmax/maxe) | Skills whose tooltip/bonus changes when maxed (e.g. "max this skill ... to remove cooldown") | The bonus appears once the skill reaches its current cap |
| 0.9.0 | Cooldown in skill tooltips (skcd) | Tooltip of a skill with a cooldown | Shows the cooldown (not 0) |
| 0.54.x | Cooldown reduction and shared groups (`cooldowns`) | Item with stat 309 (reduces cooldown of a skill); cast a skill of a group (Deep Freeze, Thunderstorm, Purifying Flame) | The wait is shorter by the stat; the other skills of the group are on cooldown until the same moment (game check `cooldowns`) |
| lane skill-leftovers (version not bumped; `mxl` cooldowns line gains `non-player starts skipped N`) | Monsters have no cooldowns; restrict modes 3-7 do not apply to item procs (as Median) | `py -3 tools/game_checks.py all cooldowns restrictitems` passed on 2026-10-22: a spawned Andariel casts skill 812 (delay 125) twice in a row via `mcast 812 7 unit <id>` and holds no stat 359 / state 0xb9 / 0x79; Heartseeker is refused on the cast path without Steady Aim (code 4) and an item's cast on kill (stat 376, `evtrace fire 9`) fires both without and with it | The monster `monsters` counter stays 0: D2R's own monster skill finish does not reach `0x439500` here (same result with the part off), so the rule is a guard. Not run in game: a hireling or pet casting a delay skill |
| 0.69.16 (lane rune-stack; data: itemtypes ids, `typeids` a self-check) | **Socketed runes apply their gems.txt mods and stack (bug #50)**: D2R's hardcoded item type numbers (58 jewl, 68 h2h, 75 rune, 77 hpot, 82 wpot, 84 mcha, 96 gem4) match our itemtypes.txt (tools/txt_migrate.py `align_item_types`) | `py -3 tools/game_checks.py --slot N all mxl typeids runestack potions hiregates classlock equipall` (equipall as in the 0.69.15 row; run 2026-10-27 on slot 2, HD and legacy, also with the release launch keys `-w` without `-txt`); `mxl`: `item type ids ok: 25 of 25 ...`. `equipall` ground mode now walks to the item before the pickup to the cursor too (a drop ~4 subtiles away was not picked up: k11 / k19 superior). By hand: socket 1, 2, 3 Eld into a socketed helm or armour and read Maximum Damage | Each Eld adds +3 Maximum Damage in armour / helm / shield, each Ral +30 Fire Resist in a weapon; with the Runemaster bonus each rune adds its Defense %; gems and jewels as before |
| lane pa2-skills (version not bumped; `mxl` gains the lines `collide types` and `skill starts`; off words `collidetypes`, `skillstarts`) | Missile CollideType 9 / 10 in the collision tables, D2Sigma's start functions 30 / 66, activation frequency (stat 427) | `py -3 tools/game_checks.py all collidetypes skillstarts activationfreq` passed on 2026-10-23 (evidence `checks-20261023-015713-s3`): server / client rows 0-8 as D2R's, 9 = mask 0x180 with type 3's function, 10 = 0x2080 with type 1's, row 255 empty; the 15 missiles.txt rows with 9 load as 9 (they load as 8 without the record fix); a row-0 arrow fired as types 3, 8, 9 stops at a monster, as type 6 passes it, and every type ends at a wall at the same place; Flash gets state 182 for 19 frames, Move Only is refused, sk851 level 3 lasts 75 frames and is refused while on, a real Flash cast reaches slot 71; Sentence fires 6 missiles in 6 s with stat 427 = 0 and = 200 | A plain arrow cannot show the missing wall bit of type 9: D2R's movement ends every missile at a wall. A real cast of sk851 is not possible (no left / right skill flag); Flash's do function 109 is D2R's Town Portal. Harness verbs added: `collide`, `collidetable`, `wallscan`, `hasstate`, `startfn`, `startstats` |
| 0.9.0 | Area-dependent skills (area) | The class "slow missiles" passives (paragon_of_sanc...) in their level range | Active only in the areas their Param7..Param8 range covers |
| data | Formulas with other Median codes (aura, area, bl12...) | Skills whose tooltips previously showed odd or zero values | Values show (codes not yet implemented count as 0) |
| 0.6.0 | States fix (bug #14) | Play a while with buffs, auras, curses, summons; enter/leave towns and areas | No crashes; buffs show and expire normally |
| 0.6.0 | High-numbered Median states | A Median buff skill late in the list (e.g. a class aura/shout) and its icon/overlay | Effect applies and ends; no crash |
| data | Skill caps (Median's real rules) | Spend points in one tab | Each skill stops at its own cap (e.g. 20 or 25; Molten Core 1); a point in the tab's Specialization raises the caps; locked pairs (e.g. Molten Core vs Entanglement) can't both be taken |
| data | Town Portal (bug #6) | Put Town Portal on the right mouse button, cast outside town | Blue portal opens, leads to town and back |
| data | Death no longer crashes (bug #12) | Die to anything | "... was slain by ..." message, no crash |
| data | Tooltip number lines (296 strings kept from D2R) | Hover items and skills | "Durability: x of y", "Required Strength: n" etc. show their numbers |
| 0.15.0 | Minion scaling (Median's rules) | Necromancer blood_skeleton or Barbarian guardian_spirit at two different character levels / skill levels; hover the pet | Pet level = your level; life grows with skill level and your level (and "+% summon life" items); attack rating grows with skill level; "+summon resist" items raise its resists. Compare with the skill tooltip's life/AR lines (mnhp/mnar, now non-zero) |
| data | hyena_strike / exorcism (D2Sigma 161 -> D2R Rabies) | Amazon hyena_strike on a monster | Melee hit with poison damage, the hyena state on the target, hyena_strike_missile appears |
| 0.25.0 | Missile hit "cast skill" (srvhit 64) | Druid **Egg Trap**: let an egg hatch/hit; Sorceress wintertide, phoenix_wave | When the missile lands, the follow-up skill fires (e.g. Egg Trap's hatch effect) on the target or spot; no crash |
| 0.24.0 | Replaced client functions | vampiric_strike / deathgaze (fan of missiles on the target), parasite_2/3 or rock_shock (two missiles forming a wall at the target), Raise Skeleton (corpse effect), flamefront_15 | Missiles appear as described, no Amazon chain-lightning visuals on parasite/rock_shock, no crash |
| 0.23.0 | Client missile row / missile at target (client 110/112) | Druid Egg Trap, Sorceress flamefront (missile row); havoc or heaven_s_fury_2 (missile at target) | Missile-row skills show their row of missiles (server-drawn) with no Volcano effects; havoc / heaven_s_fury_2 show their missiles at the target; no crash |
| 0.22.0 | **Whirlpool** (server slot 178 + client slot 111) | Wear Leather of Aut (low-level unique; also Black Ice, Waterwalk) which grants Whirlpool; put it on a mouse button with a melee weapon and hit a monster | The hit lands, then a spinning blue whirlpool appears on the target and throws out growing rings of bolts (magic damage); no Warlock/sigil effects, no crash. Also try torment / crucify_2 / ravage (same functions) |
| 0.21.0 | Level portal skill (slot 173) | Whatever grants mysterious_companion_skill / judgementwander_2_skill (item or NPC skill) | A red portal opens next to you to that level; nothing when the level is in another act |
| data | resurrect_2 (-> D2R Revive) | Paladin level-90 resurrect_2 on a corpse | Monster revives as a pet; note its life (Median set it outright, D2R treats the value as a bonus) |
| 0.20.0 | Pets inherit the owner's procs | Wear an item with "X% chance to cast level Y <skill> when you kill an enemy" (or on attack), then cast a multi-summon (blood_skeleton, Druid Harvesters/Bear Companion) | The pets cast that skill on kill (chance divided by the pet type's divisor); no crash on summoning. If nothing ever procs, note it (the stat array may not have been found) |
| 0.19.0 | Levels above 255 (bug #17) | A summoning scroll to the Heroic Library / Heroic Duncraig / an arena (Act matching the scroll), or a Mirror Temple key | Portal opens and leads into the area (not a wrong low-numbered level); area loads with no crash; cast town portal there and come back through it |
| data | Cow Portal (bug #19) | Wirt's Leg + Tome of Town Portal in the cube in Act 1 town | Red portal to the Moo Moo Farm |
| data | Skill tooltips (bug #9) | Hover skills in every tree tab (and with synergies) | No assert/crash; synergy block starts "<Skill> Receives Bonuses From:" with the skill's name; values show. Note any skill whose tooltip looks empty or wrong |
| 0.21.0 | Median teleport range (slot 179; was on 173, which mysterious_companion_skill also used) | Druid harbinger (or Sorceress Teleport, Assassin blink): click far away, then close by | Lands at most the skill's range away along the line to the click (harbinger ~25); close clicks land on the spot; no teleport where Median forbids it; monsters with teleport skills still blink |
| 0.18.0 | Layered self buffs (slot 174) | Druid Steady Shot (sk1296), frigid_nova, lionheart_2, brace_for_impact, lunar_assault_2 | Buff state and its bonuses show; Steady Shot's stacking counter grows per cast and its proc state turns on at the cap; no crash |
| 0.21.0 | land_of_the_dead (slot 180) | The skill (or an item granting it) | Timed effect around the caster keeps firing; its bonuses apply |
| 0.17.0 | queen_of_blades (slot 190) | Assassin: queen_of_blades (level 25) near a pack of monsters | Buff state on; every few frames all enemies within range take lightning plus weapon damage; damage numbers grow with the weapon; buff and pulses end when the state runs out; no crash |
| 0.16.0 | Median item auras (slot 184) | Equip Majesty, Penumbra, Clockwork Slippers or The Pathless | Their aura's state icon shows; its bonuses apply (character sheet); no crash when equipping/unequipping or changing areas |
| 0.3.0 | Multi-summon, slot 172 | Necromancer: blood_skeleton (or Barbarian guardian_spirit) | Several pets per cast, up to the cap; at the cursor when in range |
| 0.2.0 | Barrage, slot 176 | Necromancer: catapult_shot | Missiles land at random spots around the target |
| 0.2.0 | Missile row, slot 177 | Necromancer: death_ripple_2 (or Assassin CountessFirewall) | A row of missiles across the aim line |
| 0.4.0 | Strike burst, slot 178 | Necromancer: torment (or Assassin crucify_2, Barbarian earthquake_2) | Target is hit, then missiles burst from it and fly past |
| 0.5.0 | Missile at target, slot 185 | A flamestrike skill | One missile appears on the cursor spot |
| data | Storm skills -> D2R Armageddon | Druid frigid_domain, Sorceress overheat, Barbarian thundergod | Timed effect around the caster that keeps firing |
| next | Item generation hooks installed | Start the game, run `mxl` | A line `item generation on: class lock (0x36bc50) hooked, ethereal (0x442d60, 0x3d3510) hooked, sockets (0x441fc0) hooked, dyes (0x3710d0) hooked` with the counters; a mismatch names the entry that differed |
| next | Class lock (items-xp.md section 5) | Make one of the 14 class-conversion recipes (cube recipe with `properties_422`) so a unique is locked to one class (stat 492 = class + 1, look at the `mxl` counter `class lock denied`); try to wear it on that class and on another | Own class: equips. Other class: the item shows as unusable (red) and cannot be equipped; `class lock denied` counts up. Add `classlock` to `mxl-core-off.txt`: every class can wear it |
| next | Ethereal rate (item level 100+) | Kill bosses in a high area (ilvl 100+) and watch `mxl` `ethereal N of M at item level 100+`; read a dropped ethereal item | Roughly 1 in 2 of the items D2R lets through (M) become ethereal: N/M about 0.5; ethereal items have +25% defence or damage (not +50%) and 75% of the base maximum durability (not half + 1); items that were not accepted keep full durability. Off word `ethereal` restores D2R's 5% / +50% / half |
| lane pa-sockets (version not bumped; run `mxl`, the `item generation` line ends `all qualities (0x44356a socket guard, 0x44364c automagic table) patched`) | **Sockets and automagic for every quality** (Median `qualities.txt` MaxSock / Automagics: magic items roll `rand % 7` sockets, set / rare / unique / crafted / tempered items get the base's maximum, set and unique items get their automagic mod; plugin/src/item_gen.cpp) | Collect rare, unique and magic drops at item level 100+ on socketable bases (`mxl` prints `sockets given N of M rolls (magic ..., set / rare / unique / crafted / tempered ...)`); read a unique's tooltip for the automagic line. Off word `allquals` restores D2R (no sockets from magic up, no automagic on set / unique) | Rare, unique, set and crafted items on a base that can hold 6 sockets arrive with 6; magic items with 0-6 evenly; uniques and sets show an innate automagic mod. Seen by check only (harness generator, not a real drop); a set item was never produced by the harness |
| next | Socket roll (quality 1-3 items) | Collect 40+ white, low and superior drops (`mxl`: `sockets given N of M rolls`) | About 6 of 7 socketable bases are socketed (1-6 sockets, clipped to what the base holds) instead of D2R's 1 in 3. Off word `sockets` restores D2R's |
| next | Dye paint in HD (bug #11) | Use a mystic dye on a body armour, a weapon and a shield; look at the inventory, the ground and the character; also dyes 16-21 (the stat is 5 bits signed) | The item sprite and the worn item change colour (`dyed colours drawn` grows). If dyes 16-21 do nothing or show colour 0 widen the stat's Send Bits to 6. Off word `dyes` restores the uncoloured look |
| later | Multiplayer (TCP/IP through D2RLoader) | Host + join with the same mod and plugin version | Both in game; new skills work for the joiner |

## Confirmed

| What | Notes |
|---|---|
| Sprint (audit SK7), game check `sprint` | 2026-10-22, Barbarian on slot 2. Median's sprint is its charstats stamina, not code: the check (rewritten by lane checks-robust, 2026-10-23, after the pa2-stats stamina step) asserts Median's rules exactly, per frame, from `state` replies that carry the server frame and the raw stamina: a run from full stamina (50 points = 12800 raw) loses exactly 120 raw per frame (RunDrain 60 x2) and regenerates nothing, 107 frames = 4.3 s, then is forced back to walking; walking from empty gains exactly 37 raw per frame (75% of max / 256 = 50; D2R's own step is 25); standing gains exactly 50 raw per frame and refills 0 to 50 in 253 to 261 frames (10.1 to 10.4 s); the run is about 1.3 times the walk speed (data 1.40, 15% allowed); a run starts again at 2 points of stamina (no cooldown timer); state 136 fills the bar; the R key gives one run and one walk (the toggle is the character's own setting and is put back). Rule: D2Sigma `0x100a1f90`, see the pa2-stats section |
| Bug #21 fix (0.33.3): barby loads; Akara, buying, moving items, potions, shared stash tabs work on barby and dewid | 2026-10-07. The stash-link check (bug #20) still fails once at the first join of a session |
| Plugin 0.33.0 loads; every engine change installs (Phase 4 verification, 2026-10-06 20:22, launched to the menu) | mxl-core.log: states fix on (73 sites), level types/automap on (10 Median row ranges), calc codes on (incl. itemstat, tabpoints), 15/15 skill functions, item spells on, 13/13 missile hits (no FAILED), mana costs on. d2rloader.log: only the known startup checks (state count, level-type names, both handled by the plugin); clean shutdown, no crash report |
| Vendors stock Median's items (bug #8) | |
| Skill points can be spent; 8-tab skill tree; skill icons | |
| Potions (bug #10) | |
| Flamefront needs Molten Core first (bug #13) | Median's rule, not a bug |

## Automated smoke run (tools/game_ctl.py)

`py -3 tools/game_ctl.py smoke` launches D2RLoader (windowed, resized to a 1600x900 client area), clears the
calibration screens and intro, plays the selected character (difficulty dialog: Normal), takes window-only screenshots
(never the desktop) of town, the character sheet (C), the skill tree (T) and its tabs, the inventory (I), runs the
console command `mxl`, then Save and Exit and re-enter (save/reload check), stops the game and scans the logs. Output
goes to `%USERPROFILE%\mxl-d2r-runs\<run>\` (`report.md`, PNGs, `logscan.txt`, `game_ctl.log`); look at the PNGs
yourself. Single steps: `start`, `shot NAME`, `key KEY..`, `click FX FY`, `console CMD`, `logscan`, `stop`.
`MXL_RUN=<name>` pins the run folder (instead of the shared `runs\current.txt`), so two lanes do not mix.

Covers: startup log (known asserts only), the skill tree look row, inventory and character-sheet panels, the plugin
status line, and the save/reload basics. Does not cover combat, vendors, stash, cube or anything needing a walk.

### Background mode (default): the user's mouse, keyboard and focus stay free

Unattended runs must not steal the real cursor, send global keys or take the foreground. Background mode is the
default; `--foreground` (anywhere on the command line) or env `MXL_INPUT=sendinput` selects the old SendInput +
SetCursorPos + SetForegroundWindow path (it needs the window in front and the user's hands off the PC).

It needs the plugin test harness (plugin/src/testharness.cpp, off in normal play): create an empty
`mxl-testharness.txt` next to `mxl-core.dll` (`...\mods\D2R-XL\d2rloader\plugins\`) before the game starts and
delete it afterwards. With it on, D2R takes no mouse, modifier state or focus from the real devices at all. Without
it the background mouse and console are unavailable (keys and screenshots still work).

What was measured (D2R 3.3.0 build 93847, D2RLoader 1.3.1, game window behind the user's windows on another monitor):

| Input | By window messages alone | How it works in background mode |
|---|---|---|
| Keys: Esc, Enter, letters (I, C, T), digits, F-keys, arrows | works (`PostMessage` WM_KEYDOWN/WM_KEYUP with scancode lParam) | same, no harness needed |
| Text typing (names) | WM_KEYDOWN + WM_CHAR, same path as keys | same (typing a character name is untested in game) |
| Mouse move / click / right click | does NOT work: D2R reads the position with GetCursorPos and the buttons with GetKeyState and ignores WM_MOUSEMOVE / WM_xBUTTON lParam, with or without focus | plugin harness: game_ctl writes a virtual cursor and button state into a shared block, the plugin answers GetCursorPos / GetKeyState from it, and the WM_ messages are posted as well; hover and ImGui menus work |
| Ctrl+` (developer console panel) | does NOT work (the console is a D2R input action; modifiers from posted messages are ignored, also with real focus) | plugin harness runs the line through D2RCore's `ExecuteConsoleCommand` on the UI thread; the panel stays closed |
| Modifier state (Shift/Ctrl/Alt) | not seen by D2R | virtual state in the shared block (GetKeyState) |

Other things the harness keeps off the user's desktop: D2R's own `SetCursorPos` (called once at start in a normal run)
and `ClipCursor` calls become no-ops (otherwise the real cursor jumps and is confined to the game window),
`SetForegroundWindow` and `SetActiveWindow` from the game do nothing, and top-level windows get WS_EX_NOACTIVATE so the
game window is never made the foreground window at launch (without it D2R sits in front for about a second, whatever
the STARTUPINFO show flag says: D2RLoader relaunches itself and the flag is lost).

Capture: `PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)` of the game window, cropped to the client area. It returns the
D2R DX12 window live (animations move) while it is behind other windows or on another monitor, and never touches the
desktop. (`PW_CLIENTONLY` returns black.) A minimized window cannot be captured: the script refuses, so the window must
stay un-minimized. D2R keeps rendering at 60 FPS when not in front; no D2R option had to be changed.

Found 2026-10-21 (cain-menu lane): the game starts in legacy (2D, 4:3 pillarbox) graphics here; `G` (`press_bg("g", hold=0.1)`, a few
seconds after the game is loaded) switches to HD. In both modes a background click on an NPC (hover works and shows the name) walks the
character next to it but the NPC menu does not open (the menu builder `0x1147a0` is never called; calling the opener `0x1141d0`
from the plugin does call it but draws nothing, and `0x10e6e0` crashed the game), so NPC menu checks still need `--foreground`.
Also: `stop()` returns early when no game is running and then leaves `mxl-testharness.txt` in place.

Limits: the output of D2R / D2RLoader commands (cheats, `help`) goes only to the console panel, so it cannot be read in
background mode (the effect of a cheat shows in game; the plugin's own `mxl` output is written to
`mxl-testharness-console.txt` and returned by `console_text()`). While the harness is on the game ignores the real
mouse and modifiers (no manual play). `mxl-testharness-trace.log` (rewritten every 3 s) lists the Windows input calls D2R
makes and who calls them, for finding what else needs faking.

Status 2026-10-21: the full smoke passes in background mode while the user worked on the same PC: the real cursor
never entered the game window, the game window was never the foreground window (sampled every 25 ms), and D2R's
`SetCursorPos` never reached the system.

### Parallel slots: up to three games at once (tools/game_slots.py, tools/parallel_smoke.py)

A slot is a full copy of D2R 3.3 build 93847 with D2RLoader and the mod, its own save folder and its own run lock.
Every `game_ctl.py` command takes `--slot N` (or env `MXL_SLOT=N`; default 1) and then only ever touches that slot's
process and window.

| Slot | Game folder | Saves (`Saved Games\Diablo II Resurrected\mods\...`) | Loader | Lock | Harness words |
|---|---|---|---|---|---|
| 1 | `C:\Program Files (x86)\Diablo II Resurrected` (Battle.net install) | `D2R-XL` | `D2RLoader.exe` | `game.lock.1` and the old `game.lock` | none |
| 2 | `D:\D2R-93847` | `D2R-XL-s2` | `D2RLoader-s2.exe` | `game.lock.2` | `volserial tag=s2` |
| 3 | `D:\D2R-93847-s3` | `D2R-XL-s3` | `D2RLoader-s3.exe` | `game.lock.3` | `volserial tag=s3` |

Set up (setup.md has the robocopy): `py -3 tools/game_slots.py setup` writes each slot's `modinfo.json` savepath (both
copies), copies `d2rloader.toml` / `debugsettings.json` from slot 1 when missing, makes the save folder and the
renamed loader copy; `status` shows folders, running processes and locks; `install` / `install_mod.py --slot all`
installs the built mod into every slot (the data is built once and copied; `--slot N`, `--savepath` for one). The
plugin DLL of slot 2 and 3 comes along with the install; slot 1's belongs to the release.

Locks are directories in `%USERPROFILE%\mxl-d2r-runs`: `game.lock.N` (slot 1 also `game.lock`, so lanes that still
`mkdir game.lock` keep working). `game_ctl start` takes the lock of its slot (owner file `owner.txt` with the run name
and PID; a lock whose owner PID is gone is replaced) and `stop` releases it. A lock made by hand (no `owner.txt`) is
taken to mean "the caller holds it" and is never removed by `game_ctl`. `game_slots.py lock N [OWNER]` / `unlock N [OWNER]`
by hand.

**Sharing slots between lanes (2026-10-27).** A lane holds a slot for its whole session with
`game_slots.py lock N <lane>` (a manual lock, pid 0), then runs `game_checks.py` / `game_ctl.py` / `release_install.py`
with `MXL_RUN=<lane>` as often as it needs, then restores the slot and runs `game_slots.py unlock N <lane>`. The runs
inside the session see the lock as theirs and do **not** release it at their end (`release()` keeps a manual lock; only
`unlock N` removes it), so no other lane can move in while a special install (e.g. `release_install.py`) is on the slot.
Before this, each run's end removed the lane's lock and another lane took the slot mid-session (slot 3, lanes sounds-bin
and quick-cast). Hold the lock only as long as needed: others are waiting.

**There is no single-instance check.** The string `DiabloII Check For Other Instances` is in D2R.exe, but no mutex,
event, window or named pipe with that name exists in a running D2RLoader (handles listed with
NtQuerySystemInformation, windows with EnumWindows / HWND_MESSAGE; the harness `diag` mode also logs every named
object, FindWindow and NtTerminateProcess), and a second D2RLoader in another folder starts fine next to the first.
What killed a copy of the game on another drive was something else, found with the harness `diag` mode:

- D2RLoader reads `%LOCALAPPDATA%\Blizzard Entertainment\ClientSdk\cookie.bin` (the Battle.net session record that
  proves the 30-day online check) at the "frontend launch" startup step and decrypts it (Botan CryptoBox) with a key
  that is `base64(SHA-1(...))` of data including the **volume serial number of the drive the loader runs from**
  (`FUN_1419ed830`: `GetModuleFileNameW` + `GetVolumeInformationW`). The cookie was written by the install on `C:`;
  from `D:` the key is another one, the integrity check fails, `Botan::Decoding_Error` is thrown and nothing catches
  it: the process dies with an `APPCRASH` (exception 0xe06d7363) about 8 s after the launch, no crash report. Without
  the cookie D2R shows the "not been online in the last 30 days" dialog (OK quits), so hiding it is no way out.
- The harness word `volserial` makes `NtQueryVolumeInformationFile(FileFsVolumeInformation)` report the serial of
  `C:` (read at load), so the key matches and the cookie decrypts. It also refuses every write open of `cookie.bin`
  (the user's real session file is never rewritten by a test instance). Slots on `C:` need no word.
- Tools that look for "the" game by name would still find a test instance. The old `game_ctl.stop` closes the first
  window titled `Diablo II: Resurrected` and then kills every `D2RLoader.exe`: a lane on the old tools closed or
  killed the other lane's game (seen: slot 2 and 3 games ended cleanly or silently at the moment the slot 1 lane
  stopped; with the renamed loader and the tagged title the same two games ran through while the other lane's game
kept running). So slots 2 and 3 run a renamed copy of the loader (`D2RLoader-sN.exe`, made by `game_slots.py setup`) and
  the harness word `tag=s2` renames the window to `Diablo II: Resurrected [s2]`; `game_ctl` finds its window by process
  and accepts the tagged title. Slot 1 is the plain `D2RLoader.exe` / `Diablo II: Resurrected` as before.

The harness block is per process: `Local\mxl-testharness-input-<game PID>` (plugin 0.46.0 as released uses the one
shared name `Local\mxl-testharness-input`, which `game_ctl` still falls back to, fine for a single instance such as
slot 1). The console output file `mxl-testharness-console.txt` and the trace log live in the slot's own plugin folder.
`mxl-testharness.txt` is a list of words written by `game_ctl start` (env `MXL_HARNESS_WORDS` overrides it): `volserial`,
`tag=NAME`, `nocookie` (hide cookie.bin: only for experiments), `diag` (log named objects, file opens, C++ exceptions
and process exit to `mxl-testharness-diag-<pid>.log`, plus the cookie record and CryptoBox input of D2RLoader 1.3.1).

`py -3 tools/parallel_smoke.py [--slots 1,2,3] [--name N]` takes the locks (a slot whose lock is held is skipped),
runs `game_ctl.py smoke --slot N` for each with `MXL_RUN=<N>-sN`, staggered by 4 s, samples the real cursor and the
foreground window every 25 ms (`tools/input_watch.py`: stops all games when a test instance becomes the foreground
window or the cursor teleports into a game window and stays), samples CPU / RAM / GPU every 3 s
(`tools/resource_sample.ps1`, per process, GPU through the Windows GPU Engine counters) and writes
`parallel-summary.md` into the run folder. Windows cascade (`100 + 60 (N-1)`, `60 + 40 (N-1)` on the primary monitor,
client 1600 x 900) and are sent to the bottom of the z-order at launch.

Results 2026-10-21 (RX 9070 XT, 32 logical cores, 64 GB; the user worked on the PC meanwhile):

| Run (run folder in `mxl-d2r-runs`) | Slots | Steps passed | Wall time |
|---|---|---|---|
| `par-3way-2` | 1, 2, 3 at once | 18/18, 18/18, 18/18 | 212 s (per slot 203 / 206 / 211 s) |
| `par-3way-1` | 1, 2, 3 | 18/18, 18/18, 0/1 (slot 3's files were being replaced by an install at that moment: that run's own fault) | 207 s |
| `par-2way-9`, `par-2way-8`, `par-2way-7` | 2, 3 | 18/18 each, all three runs | 206 s, 209 s, 209 s |

The 18 steps per slot are the whole smoke: start, menu, create or enter the character, the plugin `mxl` command, the
character sheet, the skill tree and its 8 tabs, the inventory, Save and Exit, reload (`report.md` and the PNGs of each
slot are in `<run>-sN\`; the three games show their own town and panels).

Real mouse and focus (25 ms samples, `input-watch.json`): in the 3-way run the cursor stayed at (2215, 466) for the
whole 212 s (before = after, range x 2215..2215, y 466..466, the user was away), 0 teleports into a game window, a
game window was the foreground window in 0 samples. In the runs where the user kept working (par-2way-7, 1,594 moves,
x 10..3781, y -945..1439) the same: 0 teleports, 0 foreground samples. The plugin trace of every game: D2R called
`SetCursorPos` 6 times, `ClipCursor` 9-11 times, `SetActiveWindow` once, `SetForegroundWindow` never, all answered by
the harness (none reached the system). With the windows on the primary monitor a resting cursor can lie under a game
window rectangle (counted separately, not a violation); an early version of the watcher aborted on that and on a hand
sweeping through a window, hence the "teleport" rule.

Load, 3 games at once (par-3way-2): machine CPU 26% mean, 57% peak of 32 logical cores; free RAM down to 18.0 GB (about
33-38 GB with no game); GPU engines (all processes, summed) 53% mean, 99% peak. Per game (par-2way-9, two games): about
1.5 cores on average and 6.6 cores at the startup peak (the txt compile), 6.6-7.2 GB RAM, 4.1-4.5 GB VRAM, GPU 17-21%
mean (28-57% peak). The RX 9070 XT (16 GB) has room for three; RAM is the thing to watch (about 7 GB per game).

### Test what players get: a release install (tools/release_install.py)

A slot set up by `tools/install_mod.py` is a **developer install**: data from work/mod, the dev plugin and the slot's
d2rloader.toml with `-w -txt`. Players get the **release install**: the D2R-XL Downloader unpacks the release 7z into
`mods\D2R-XL` and the release launch keys have no `-txt` (`launch_arguments = ""` since 0.69.2). A bug a player sees and
a developer install does not (bugs #38 and #45) is checked on a release install:

```
py -3 tools/game_slots.py lock 2 <name>
MXL_SLOT=2 MXL_RUN=<name> py -3 tools/release_install.py install --slot 2     # live stable release, by its own downloader
MXL_SLOT=2 MXL_RUN=<name> py -3 tools/game_checks.py all mxl orbtips allattrtip tooltiptext specialtext --slot 2
py -3 tools/game_slots.py lock 2 <name>                                         # game_checks released it
MXL_SLOT=2 MXL_RUN=<name> py -3 tools/release_install.py restore --slot 2      # the developer install and toml come back
```

`install` (slots 2 and 3 only, lock and no running game required) moves `mods\D2R-XL` to `<slot>.release-backup` (same
volume), copies the toml there, downloads the manifest's downloader (sha256-checked) and runs `--cli install` into the
empty folder like a player's first install. Then it changes only what background checks need, and writes each change to
`%USERPROFILE%\mxl-d2r-runs\release-install-sN\release-install.json`: the dev build of `mxl-core.dll` (the release DLL
has no test harness; it is kept in that folder, `--release-dll` keeps it in for a log-only launch), the slot's own
savepath, and `default_mod` / `launch_arguments` from the manifest's `launch` plus `-w`. Build the dev DLL of the same
version first (`tools/build_plugin.ps1`); `install` says when its PluginVersion differs from the release's. The checks
read the expected data from work/mod and assets/median as usual. `MXL_GRAPHICS=legacy` runs a whole game_checks run in
legacy graphics (G in town first; `inv_cell` / `shop_cell` give the legacy grid positions, the shop ones are not yet
right: the hover misses on Gheed's shelf).

First run (lane release-install, 2026-10-27, slot 2): releases 0.69.5 and 0.69.6 without `-txt`: `mxl`, `allattrtip`,
`tooltiptext`, `specialtext` PASS, `orbtips` REVIEW with complete tooltips (Gheed's shelf and inventory), also in legacy
graphics (inventory). D2RLoader logs "Compiled 188 tables from TXT ... 38 game, 150 mod" without `-txt` too. The
release DLL alone (`--release-dll`) installs every part including "item text on". Bugs #38 / #45 did not reproduce.

`releasetables` (bugs #42 / #46, lane sounds-bin): the sounds table the game loaded (`mxl` sound guard line `sounds.txt N
rows (D2R-XL 12449)`) has the installed mod's row count, the Median-only `treasuregoblin_neutral_1` (row 12214) is inside
it, d2rloader.log's sound step of this start compiled the mod's `sounds.txt` with that many rows, and the installed
`objtype.txt` files equal work/mod's (D2RLoader compiles objtype in neither mode). To see a player's first start, move
`<slot>\d2rloader\data\compiler` aside before the run (D2RLoader then builds its base snapshot and loads D2R's 11913
sound rows: `releasetables` FAILs and names it; `goblincrash` crashed before 0.69.15 and now passes with the skipped ids
listed, because the `mxl` line says `NOT D2R-XL's table`) and put it back afterwards. Runs 2026-10-27 on
the live release 0.69.8 with this lane's dev DLL (then labelled 0.69.10, 0.69.15 after the merge), no `-txt`: first start (snapshot moved aside) `releasetables` FAIL
"loaded sounds table 11913 rows ... base snapshot built in this start" and the plugin's warning in mxl-core.log
(checks-20261027-164906-s3); normal start `mxl releasetables goblincrash denboss` all PASS (checks-20261027-165028-s3). With every sound record
lookup guarded (0.69.15 follow-up, release 0.69.10, slot 3): first start `mxl goblincrash denboss` PASS and no crash,
`releasetables` FAIL by design (checks-20261027-171557-s3); normal start all PASS (`denboss` on the rerun,
checks-20261027-172425-s3 / checks-20261027-173418-s3).

## Harness commands (gameplay without input; plugin/src/harness_cmds.cpp)

World clicks do not register in background mode, so the plugin's test harness (only active while `mxl-testharness.txt`
sits next to `mxl-core.dll`; never in normal play) has gameplay commands that call the game's own functions. They use
the console mailbox that already carries `mxl`: `py -3 tools/game_ctl.py` / `game_ctl.hcmd("kill nearest 156")` writes
`h kill nearest 156`; the answer lines (`h: ...`, ending in `h: <verb> OK` or `h: <verb> FAIL <reason>`) are appended to
`mxl-testharness-console.txt`, and `hcmd` returns `(ok, lines)`. Server-side verbs are queued and run on the game thread
inside the server frame (a hook in `goblins.cpp` calls `HarnessGameFrame` after `0x406550`); the UI thread must not wait
for them (the server frames are driven from it). `menu` runs on the UI thread. A bad pointer inside a verb is caught
(`FAIL crashed`), it does not take the game down.

| Command | What it does |
|---|---|
| `state` | player (id, class, level, life, area, x, y, gold, bank, difficulty, frame), every inventory / cube / equipped item (`code`, `page` 0 backpack 3 cube 4 stash 255 equipped, position, quality, unique index), monsters within 40 (class, mode, distance, NPC flag), objects within 30 (portals are class 59 / 60 / 600 and print `dest=<D2R level id>`), plugin counters (goblins, lockout, tower skips), NPC menu globals |
| `kill <unit id>` / `kill nearest [class]` | the unit-death function `0x44db20(game, victim, player, 1)`, the player is the killer, so the quest kill hooks (`0x515640`) fire |
| `spawn <class> [n]` | `0x4929e0` next to the player (monsters and NPCs, e.g. 156 Andariel, 148 Akara) |
| `interact nearest` / `interact <npc class>` | stands next to the NPC (move `0x491ca0`) and sends the server packet 0x2f (start talking) through the packet handler table `0x1d2a790`: the NPC speaks, quest event 0 runs, the server answers 0x27 and the client opens the menu through its builder `0x1147a0` when the speech is over (up to ~30 s for a first talk) |
| `msg nearest\|<npc class> <message id>` | packet 0x31 (a dialog line ended): quest event 11 (Akara `0x76` = Griswold's Heart) |
| `menu list` / `menu <line>` / `menu cancel` | client side: the open NPC menu's record (`0x2a48830`, 48 x 0x48), line string ids and handler (`plugin@` = a plugin line); `menu <line>` calls that line's click handler |
| `quest <id> <bit> set\|clear\|get`, `quest <id> dump` | quest bits (`0x325c00` / `0x325990` / `0x325c50`) of the game's difficulty |
| `players <n>` | D2R's players setting (`0xe19e0()` then `0xd2f020(setting, n)`): monsters spawned afterwards carry players count `n` (stat 100) and the scaling record of that count; not persistent |
| `tctrace [reset]` | the class lookups of the treasure-class executor (`0x397290`): `calls leveled lastclass lastlevel` (level above 0 only when the monster's level steps the class up) |
| `leash [d]` | the mercenary against its owner: with `d` moves the mercenary `d` sub-tiles from the player (unit move `0x491ca0`); prints both positions, `0x596720`'s owner distance, the Euclidean distance and the mercenary's mode |
| `waypoint <level id>\|n <number>\|all [get\|set\|clear]`, `waypoint open\|tabs\|panel` | the server's waypoint record of the player's difficulty (`0x3d6890` set, `0x3d6930` test): one level, one number, or all 112; `open` sends packet 0x63 (`0x4812c0`) so the panel opens as in play; `tabs` sets the client's quests 7, 15, 23, 26 (bit 0) so tabs II-V are enabled; `panel` prints the plugin's button table (level, listed flag) |
| `item <code> [stat=value ...] [q=n] [ilvl=n] [uniq=n] [inv\|cube\|ground]` | creates the item in the backpack, the Horadric Cube or on the ground (port of `0x517530` with the page chosen and the stats set before the client is told); a stat is `<id>[:layer]=<value>` or `<name>[:layer]=<value>` with the `Stat` names of the build's itemstatcost.txt, Median's included (`fireresist=155`, `lightresist`, `coldresist`, `poisonresist`, `item_numsockets`; `plugin/src/mxl_stat_names.h`, made by `tools/stat_names_data.py`; an unknown name is an error), set as the item's total on its magic stat list (0.65.0: the list D2R saves, so the stats survive Save and Exit; before that they sat on the base list and the item came back with none). Charms are always made at quality 2 (the generator ignores `q=`), which keeps the stats; `uniq=<row>` makes a named unique (the generator hook of quests_act1.cpp picks it; unique index = `uniqueitems.txt` line - 2); answers with the item's id, page, position, quality, unique index |
| `cubecraft` / `cubeclear` / `cuberec <n>` | the transmute on the cube contents (`0x529090` search, then `0x5269c0`), prints the recipe row (`FAIL no recipe matches` when none does; portal outputs return no item, look at `state`); empties the cube; hex dump of a cubemain record |
| `cubeslots <first> <count>` | which of the three output slots (D2R record `+0x5a + 0x5b * i`) of recipes first..first+count-1 hold anything: a digit 0-7 per recipe (bit i = slot i filled: its first 0x0e bytes are not all zero, the tail holds -1 defaults even when empty), 50 recipes a line; the empty-output audit of `cowportals` compares it with the built cubemain.txt (reads the lines by their labels and asks again for a chunk with a missing line). Until lane cube-outputs the plugin lost about 7% of such replies' lines (`HarnessEcho` opened the console file with `fopen_s` while `hcmd` polled it, a failed open dropped the line silently): the release suite run `checks-20261022-212141-s1` lost the line of recipes 4950-4999, which shifted every later recipe by 50 and showed as "differences" at rows 4950-4962 / 5083-5100 / 5133-5141 (reproduced offline: delete that line from the built masks and the report's list comes out exactly). `HarnessEcho` now appends each line with one `WriteFile`, full sharing and a retry: 0 of 300 incomplete replies (was 20 of 300). Any harness verb with long output was exposed to the same loss |
| `cubeout <recipe> [slot]` | the executor's output dispatch (`0x526d3c`, handler table `0x1d3bfc0`) for the portal-output slots (special byte 1-4 at slot `+0x0d`) of a recipe, without inputs or conditions; look at `state` for the portal it opened |
| `flag player\|game <n> get\|set\|clear` | the craft flags (craft_flags.cpp) |
| `gameflag <word> <bit 0-15> [get\|set\|clear]` | D2R's own per-game flag bits (game +0x21d8 -> +0x10; get `0x325c50`, set `0x325c00`, clear is the byte of the record with that bit masked off): word 4 bit 11 is the Cow portal's once per game |
| `gold get` / `gold set <carried> <bank>` | gold stats 14 / 15 |
| `stat <ref> <stat> scan [max layer]` | every layer of the stat that reads non-zero (up to 40 lines `scan <ref> <stat>:<layer> = <value>` and a count; default max layer 262143): which skill an item's oskill / aura / proc property really carries (the layer is the skill, or skill << 6 \| level for encode 2 / 3 stats) |
| `stat player\|<item id>\|<item code> <stat> [layer] [set <value>]` | read or set any unit stat (`0x2f5020` / `0x2f7d10`) |
| `level <id>` | the NPC travel `0x4f2e40`: works across acts; inside an act it only opens a portal, use D2R's `cheat goto <id>` there. Do not send further commands for about 5 s (a second travel while one loads can hang the game) |
| `use <item code>` | the item-use check and use functions (`0x5817f0` / `0x581680`), the item is removed unless the item spell keeps it (keys and scrolls) |
| `remove <code> [n]` | takes items out of the inventory |
| `enter nearest\|<object id>` | walks into a portal object (`0x58f680`, as the click does, so the dungeon lockout hook sees it); the first call right after `use` can fail, repeat it |
| `missile <row> [dx dy]` | a missile of missiles.txt row <row> from the player towards (+dx, +dy) (default 12, 0), `0x5371a0` as the skills call it. In a town the client does not tick missiles; fire it in a dungeon (bug #24b: row 5507 crashed the client there before 0.48.0's empty-slot functions) |
| `missilescan [row]` | the rows whose client do / client hit index lands on an empty slot of D2R's tables (counts and the first rows); with a row number: the first 0x60 bytes of that missile record |
| `tile` | uses the nearest warp tile (`0x491ff0`) |
| `towerprobe` | whether the quest 5 kill hook would skip the vanilla handler for the nearest Countess (spawn 45 first): `skip=1` when quest 5 bit 0, 0xe or 0xf is set |
| `lockcheck <level>` | the dungeon warp test's verdict for the player entering the level (`allow`, `requirements`, `quest`, `sealed`, `none` when the table has no row), without moving anybody or counting (dungeon_lockout.cpp `DungeonLockoutProbe`) |
| `difficulty <0-2>` | writes the running game's difficulty byte (checks that need Hell rules without a Hell character; quest records are per difficulty) |
| `class <0-6>` | sets the player's class field (class bound recipes; set it back, the save keeps it) |
| `pkt <hex bytes>` | any client packet into the server handler table (fixed-size packets only: the walk / run packets 1 and 3 are 210 bytes with the client's path, a short one is read as garbage; use `move`) |
| `equip <code> [stat=value ...] [q=n] [ilvl=n] <bodyloc>` / `unequip <bodyloc>` | creates the item (stats as for `item`) and wears it (the game's place function `0x471500` with the location from `0x382df0`, so the owner gets the item's stats: a +77 strength ring raises stat 0 by 77 and `unequip` takes it back); body locations `head neck torso rhand lhand rring lring belt feet gloves altr altl` or 1-12; `state` prints `body=<n>` on worn items |
| `move <x> <y> [walk] [packet]` / `moveto <unit id>\|nearest [class]` | the player walks / runs to a position (state's x / y units) through `0x42d2c0(game, player, 0, 3, x, y, 0, 0)`, the call the walk packet ends in (the server finds the path); poll `state` for the arrival. `packet` sends the 210 byte walk packet through the handler table instead and prints the checks it makes (dead, position, distance <= 15) |
| `skills` / `skill [left\|right <id>]` | the player's skill list (id, base level, skill mode, the game's usability code from `0x33f360`: 0 usable, 2 passive or requirements, 5 no weapon), or selects the active left / right skill (packet 0x3c) |
| `xp <amount>` | D2R's award function `0x44f2e0(game, player, level, amount)`: adds the experience and runs the level-ups (stat / skill points, the class level cap); prints `level`, `experience`, `statpoints`, `skillpoints` |
| `setskill <id> <level>` | gives a skill levels with the game's own `0x438670` (stat 5 refilled each step, restored after); Median skills with prerequisites work, the prerequisite check is skipped |
| `skilldmg <skill> [level] [nomastery]` | the skill's damage at that level for the player through the damage hooks and through D2R's own functions (elemental and physical, min and max), with the inputs of Median's formula: flags (1 BaseSynergy, 2 StaticDamage), character level, energy, stat 514, the synergy percent columns, the BaseSynergy percent, the mastery stats (`docs/plugin-spec.md` "Skill damage scaling") |
| `collide <row> <dx> <dy> [type]` | a missile of missiles.txt row `row` from the player towards (dx, dy) like `missile`, optionally with its collision type (the unit's mode, read by the tick `0x463100`) set to `type`, followed every server frame; prints the record's CollideType and the mode on creation. `collide result`: frames alive, start / last position, distance |
| `collidetable [rows\|row <n>]` | the rows of the collide tables the server and client read now (types 0-10 and 255: check function RVA / mask), `rows`: missiles by CollideType, `row n`: one record's CollideType and the data-table-loaded counters |
| `wallscan [max]` | for the eight directions from the player, the distance to the first wall cell of the missile tick's test (`0x364d50` flag 4) with room cells beyond it; the last line is the best direction |
| `hasstate <state>` | the player's state bit, its stat list and end frame (float at list +0x24), and the game frame |
| `startfn <slot> <skill> [level]` / `startstats` | calls a server start-function table entry (`0x238e710`) the way the cast path does and prints its answer / the plugin's counters for slots 71 and 72 |
| `mcast <skill id> <mode 0-15> unit <id>\|nearest [class]` | a monster uses one of its own skills on the player through the AI's skill use `0x4a7bc0` (mode as monstats `Sk<n>mode`: 6 = A1, 7 = A2, 9 = SC, 10 = S1); prints the answer, the monster's mode before / after, its stat 359 at layer = skill (the end frame of D2R's cooldown timer) and its states `0xb9` / `0x79`. The skill finish (and with it the cooldown start) comes a few frames later |
| `cast <id> [x y\|unit <id>\|nearest [class]\|self]` | selects the skill as the left skill, then uses it the way the cast packets do (`0x4fdb40` at a position, `0x4f8de0` at a unit: a melee skill walks up to the monster first and the cast starts when it is in reach, so repeat it for a wandering target); prints the usability code, mode and mana at the call |
| `missiles [reset]` | live missile units (type 3, hash base `0x646`) and the distinct missiles seen by any server frame since `reset` (class ids; short-lived ones are counted); `state` ends with the same line |
| `dump player` / `dump client` / `dump mon <class>` / `dump ground` | hex dumps for the RE work behind plugin offsets: the player's data block (`0x34b240`: the character name at +0), the client record of the player in the game, a monstats record (`0x976e0`; the treasure class words are u16 at +0xc0 + difficulty * 0x10 + (n - 1) * 2, n = 1..4; the quest class is n = 4), the items on the ground |
| `merc` | the player's mercenary unit (`0x4ff1a0(game, player, 7, 0)`): id, class, level, mode, life, and every item in its inventory (equipped ones have page 255) |
| `hire [npc class] [n] [reopen]` | hires the n-th free mercenary of the nearest hirer (or of the given NPC class) as the client's hire button does (`reopen`: makes the NPC's list again first; the answer lists the NPC's distance, the player's mode and the gold): lists the entries of the NPC's mercenary list (`0x502b70`), prices it (`0x3c17b0`) and sends packet 0x36 into the server handler; then `merc` shows what the new hire carries |
| `stat player\|merc\|mon:<id>\|<item id>\|<code> <stat> [layer] [set <value>]` | reads (or writes the base of) a stat; `merc` and `mon:<id>` are the mercenary and any monster by unit id (the verify checks set resists, avoid stats, life, strength, level on them) |
| `hit <player\|merc\|mon:id> phys\|fire\|ltng\|magic\|cold\|pois\|life\|mana\|stam\|clen\|flen\|plen <amount> [attacker ref] [stagger]` | one hit through the game's own damage path: a damage block with the elemental field set (result flags bit 0), `0x44ce80` (resist, absorb) then `0x44a9b0` (life); the amount is in 1/256 life points. Prints life before -> after, the absorbed total (block `+0x130`), the result flags and `field=` (the element's field after the step; for `clen` / `flen` / `plen` the cold / freeze / poison length). The player cannot hurt its own mercenary: give an attacker (`mon:<id>` of a spawned monster). `stagger` (last word) sets the result flag 4 (hit recovery) between the two steps: the target enters GetHit even when it has no hit recovery (bosses), and its last-mode field (monster data +0x68) reads 3 when it leaves it, which is the gate of `andariel_ai`'s controlled branch. Nothing happens in town |
| `avoid <ref> melee\|missile\|evade [n]` | runs the game's avoid check `0x44ef70` n times (default 200, the hooked one with Median's caps; its first argument is the attacker unit, the player here) against the unit and tallies none / avoid (2) / dodge (4) / evade (8) / block (0x10); `evade` puts the unit into walk mode for the loop |
| `wear <attacker ref> <defender ref> [n]` | n melee wear steps (`0x4526c0`, the function every hit runs; it calls the wear dispatcher `0x441b10`) and the summed durability of the player's worn items before and after |
| `iflags <item unit id> [unid]` | flag word (0x10 identified), mode, quantity (stat 0x46), durability (0x48) and maximum (0x49) and position of any item unit, on the ground too; `unid` clears the identified flag first |
| `itemdesc <item unit id> [eth]` | the text of the item's description as the inventory tooltip builds it: D2R's own builder `0x2be560` (out string, item, flags, flag, text, options) called on the client's copy of the item; one line `h: itemdesc id=<id> line <n>: <text>` per description line (colour codes removed) and `itemdesc id=<id> lines <n>`; `eth` makes the client's copy read as ethereal for that one call (the item itself is not changed). The `Durability: x of y` line is the output of `0x2c1640` (plugin part `durabilitytip`) |
| `cursor` | the item on the player's cursor (id, code) or `empty`; a held item makes `0x4249f0` report "busy" and refuses every skill use (drop it with the client packet `17 <id u32>`) |
| `manamin [reset]` | the lowest and highest mana of the player on any server frame since `manamin reset` (a skill's mana is charged a frame or more after `cast` returns and regenerates within a few frames, so one read afterwards sees nothing) |
| `manacharge` | what the mana cost hook decided at the last charge site: calls, room, town test, cost, charge, site (1 server, 2 client, 3 the loader's server copy), and the return address of the last other caller |
| `rewardstep potion\|tome` | runs D2R's own grant step of the Potion of Life (`0x580680`, max life stat 7) or of Lam Esen's Tome (`0x5ed6d0`, unspent stat points stat 4; grants only while `quest 17 1` is set) on the player and prints the stat before and after, the difference and the points (life in whole points). The amounts are Median's +50 life and 10 points with the plugin part `potionamounts` (vanilla 20 and 5) |
| `setstate <ref> <state> <0\|1>` | D2R's set-state call (`0x3355a0`) on a unit; prints whether the unit has the state afterwards. Gives the player the Stamina Shrine's state 136 without a shrine |
| `itemroll <code> <n> [q=] [ilvl=]` | makes n items through the generator the way `item` does (quality default 2, item level default 110), reads sockets, the ethereal flag, defence and maximum durability, frees them; prints the socket histogram, the ethereal count, the defence sums and the durability ranges of normal and ethereal ones |
| `colour <item id\|code>` | the item colour function `0x3710d0` (hooked for stat 368) on an item of the player: the colour byte, the item's colour kind and whether a palette entry came back |
| `req <ref> [as <class>]` | the item requirement check `0x36bc50` (class lock stat 492, mercenary weapon / shield lists) of every backpack item against the player or the mercenary; `as` swaps the unit's class for the call (character class 0-6, or a hire monster class 271 / 338 / 359 / 561). Prints id, code, usable, lock, weapon / shield flags and the hireclasses list item types the item belongs to |
| `panelrow <stat>` | the Advanced Stats panel's row functions (`0x14eb1b0` value, `0x14eb250` text, hooked by `stat_columns.cpp`) on a stand-in panel of the player unit for a D2R stat id: prints `panelrow <stat> value=<displayed value> text=[...]` (colour codes removed) and `panelrow weapon strbonus=N dexbonus=N` (or `none`) |
| `cstat <stat> [layer] [set <value>]` | (client side, UI thread) the stat of the client's copy of the player: what the screen shows, to compare with `stat player` after an update packet; `set` writes the client's copy only (a stat set on the server's unit does not reach it) |
| `statorder [open\|adv\|close]` | (client side) `statorder` prints the list the Advanced Stats panel built (`ordered`, rebuild count, rows: `[Label]` / stat id); `open` / `close` the character sheet, `adv` presses its Advanced Stats button (WidgetService panel messages) |
| `bufficons [hover <x> <y> \| hover state <n> \| hover off \| probe [off] \| cstate <state> <0\|1>]` | (client side) counters of the buff icon bar (`on`, frames, icons per group, refused draw requests, rectangles per frame, tooltip state and lines) and one line per drawn icon (`state side slot row secs hover x y size`); `hover` overrides the cursor, `probe` draws a magenta test rectangle, `cstate` sets a state bit on the client's copy of the player |
| `infopanel [close <n>]` | (client side) the presentation state of Median's help panels (2 = open) and how many opens the plugin message `I` asked for / the UI thread did / failed |
| `tip [id\|code]`, `tiplog [n\|reset]`, `tipfmt <stat> <value> [layer [mode [flag]]]` | (client side, off words `itemtext`, `tooltipprobe`) `tipfmt` calls D2R's property formatter `0x2d6520` with the given stat, value and layer and prints `ret` and the text (flag 1 = the group line); `tip` prints the lines of an item (client id or a code on the ground) as the item text builder `0x2dc4b0` made them, with `tip build` arguments only after one hover (the check hovers a ring once); `tiplog` lists the last formatter calls of the hovered item (`reset` right before `tip`, the ring floods every frame) |
| `rewardsnd`, `rewardmsg`, `goblinsay` | the quest reward sound the client hook last played (0x5f-0x61); a reward unit message to the player; the goblin "<name> appears!" line for a monster class |
| `sysmsg <type> <colour> <text...>` | one chat packet 0x26 to the player (docs/d2r-addresses.md section 13): type 4 = message-log line, 5 = overhead bubble; colour byte 0-11 |
| `automap` | (client side) the automap's cell count (sum of the four element counts of every layer), current layer, layer count and the debug flag byte `0x2a2add4` |
| `reveal` | (client side) the R hotkey's work without the key: D2R's debug Reveal Automap `0xd42b0`, flag byte restored; fails when the part is off or no local player exists |
| `wpobj` | every waypoint object of the game (class, position, distance, level, whether it is within 36 sub-tiles) and the player's level and waypoint number |
| `travel` | (client side) the hotkey bindings (key and modifier as D2RLoader reports them), counters (waypoints activated, scans, reveals, key presses, transmutes, cube open / closed) and the distinct UI messages seen (`uimsgs`) |
| `stashprobe <tab>` / `stashprobe result` | queues, on the game thread, a rune created by ItemService in shared stash tab `<tab>` and destroyed again; `result` answers `1 page=<n> create=0 ...` when the tab took the item, `0` when it refused |
| `stashpage state\|open\|close\|toggle\|msgs\|uia <target> <command> [text]\|widget <panel> [child]\|vis <panel> <child> <0\|1>\|put <code> [x y]\|fill <1\|2>\|drop <code>\|list\|move <id> <1\|2> [x y]\|result` | (client side; put / fill / drop / list / move queue work on the game thread, `result` has the answer) the personal stash page 2: panel state (1 closed, 2 open), a native UI message through WidgetService (`uia PanelManager OpenPanel BankExpansionLayout`), a widget rect, items created / listed / moved between page 1 and page 2 in one ItemService transaction |

Where the answers cannot come from a call they come from the screenshot: the NPC popup text (`cain_menu.png`) and
D2R's own cheat output.

### Player actions (lane harness-cast, 2026-10-22, background mode, slot 2, plugin 0.48.0 + harness)

The `pkt` verb could not make the player act: the walk and run packets (1 / 3) are 210 bytes with the client's own path, and the
cast packets run through the character's active skill. `move`, `skill`, `setskill`, `cast`, `equip` and the missile counter now
drive the player server side with the game's own functions (no input of any kind; `py -3 tools/game_checks.py casts itemevents`).

| Row | Result | Evidence |
|---|---|---|
| `move` | PASS | `move 4725 5440` from 4704,5424: mode 3 (run), arrived at 4725,5440 within ~5 s |
| `cast` earthquake_2 (Median 1271, Barbarian) | PASS | melee: walks to the monster, mode 7, mana spent at the call (1000 -> 989 at level 5), 4-6 distinct missiles (earthquake missile classes 4164-4167, 5535-5537) |
| `cast` Bash (126) | PASS | mode 7, mana 1005 -> 996, no missile (a melee hit) |
| `cast` Fire Bolt (36, a Sorceress spell cast by the Barbarian) | PASS | mode 10, missile class 58; the game does not check the class here. The only character in the slot is a Barbarian, and Median's Sorceress skills with a missile and no prerequisite are rare (frigid_nova 485 answers usability 2 and does not run) |
| `equip` + `unequip` | PASS | worn item `body=4` / `body=7`; a +77 strength ring: stat 0 30 -> 107, back to 30 |
| Stat columns (rows 299 / 300, % bonus / base suffix) | PASS (`py -3 tools/game_checks.py all statcols`, slot 2) | `panelrow` with no weapon: 0 / 0; weapon `hfh` (StrBonus 16) at Str 50 / 123 / 300: 8 / 19 / 48; `hst` (DexBonus 6): Dex x 6 / 100; a ring `388=25 389=-10`: " (+25% bonus, N base)" / " (-10% bonus, M base)" on the Strength / Dexterity rows. The weapon bonuses come from the built weapons.txt. Not opened on screen |
| Level cap 150 (experience.txt `MaxLvl`) | PASS (`py -3 tools/game_checks.py all levelcap`, slot 1, 2026-10-22) | Barbarian, 5 stat / 1 skill points per level (charstats): `xp` from the start of level 98 / 99 / 119 / 148 / 149 reaches 99 / 100 / 120 / 149 / 150 with exactly +5 / +1 per level; one award of the whole table from level 99 gives level 150 and +255 / +51; more experience at 150 changes nothing (level 150, experience stays 12353407); the client copy (`cstat 12`) says 150, the character sheet shows `Level 150`; Save and Exit and Play: level 150, same experience and points, `.d2s` header byte 0x1b = 150. Before the fix (main's old `experience.txt`, `MaxLvl 99` last) the same check failed on every step: no award levelled the character at all (98 stayed 98, 149 stayed 149), the client level read 99, the saved character was level 99 |
| Item events (stat 397 / 265 / 376 / 135 / 136) | PASS (`py -3 tools/game_checks.py all itemevents`, slot 3) | ring `397=50`: the monster loses 50 points on `evtrace fire 3 player m<id>`; ring `265=50`: +50 life on `evtrace fire 9`; ring `376:2309=100`: a class-58 missile (Fire Bolt 5, skill not owned); ring `135=100 136=100`: a plain monster loses life on events 5 / 6, one with stat 373 does not. A weapon `115` in `rhand` does not apply its stats in the harness, use a ring. See docs/subsystems/items-xp.md section 5b |

Notes for whoever extends this: `cast` needs the skill to be the active left skill (the unit cast uses the player's active skill), the
harness selects it; a melee skill cast at a unit makes the player run to it first and the class 18 monsters wander off, so the check
repeats the cast; the mana cost cannot be read from `state` after the fact (regeneration refills in a few frames), only at the call.

### Item rules and free mana in town (lane gap-items, 2026-10-22, background mode, slot 1, plugin 0.54.0 + item rules)

`py -3 tools/game_checks.py all nodurability autoid townmana`, the plugin with and without the off words
`durability quantity autoid townmana` in `mxl-core-off.txt`.

| Check | With the parts | Off words | Evidence |
|---|---|---|---|
| `nodurability` (audit IT1, IT2) | PASS | FAIL | hfh weapon 110 -> 110 and fld armour 48 -> 48 after 600 `wear` steps (off: 110 -> 101, 48 -> 16); a tax stack, 4 accepted Throws (`cast 2 nearest`), quantity 58 -> 58 (off: 110 -> 109) |
| `autoid` (audit IT3) | PASS | FAIL | 14 Andariel kills (`spawn 156`, `kill nearest 156`), `dump ground` (now prints `quality=` and `identified=`, ground items only): 6 magic / set / rare / unique drops, 6 identified (off word: 0 of 6); the low / normal / superior drops are identified either way (D2R sets the flag on non-magic items itself). `itemroll` and `item` cannot show it: `MakeItem` `0x43d530` sets 0x10 at its end |
| `townmana` (audit SK3) | PASS | FAIL | skill 1558 (`sk1486`, InTown, level 5) cast at the player: Rogue Encampment, lowest mana 5000 of 5000 (cost 16 by the plugin, charged 0, `manacharge` site 3); Blood Moor, lowest 4993 (off: 4993 in town too) |

What the checks needed to learn (so the next check does not lose time on it):

- Mana is charged when the cast's action starts and refills in a few frames, so `cast`'s own "mana A -> B" and a read two
  seconds later both show nothing; `manamin` samples every server frame. The drop it sees (7) is smaller than the charge the
  plugin decides (16): regeneration refills in the same frames.
- `0x4249f0` ("busy") is also true while an item is on the cursor. `unequip` and a pick-up leave the item there, and the next
  cast is refused with code 1 although the usability code says 0. `cursor` shows it, packet `17 <id>` drops it.
- D2RLoader runs a re-assembled copy of the server's skill charge function (`0x436830`), so the return address of the mana
  cost call is a heap address: see docs/plugin-spec.md, Mana costs.
- A skill must be selectable (left or right skill); `cast` refuses the passives and the ones the game will not select
  ("would not select"). The check tries the InTown skills of the built `skills.txt` by required level until one is accepted
  (`usable=0`).
- Median's Throw (skill 2) needs strength 600 / dexterity 600 / level 60 for tax; the check sets the stats and restores them.

### Client messages (lane client-ui, 2026-10-22, background mode, slot 2, plugin 0.48.0, window-only screenshots)

| Row | Result | What the screenshot shows |
|---|---|---|
| `sysmsg 4 <colour>` / `sysmsg 5` | PASS | message-log lines in the colour of the byte (1 red, 2 green, 3 blue, 8 orange, 9 yellow); type 5 a bubble above the player |
| Lockout refusal, requirements | PASS | Normal, `h use b60X` + `h enter nearest` (level 125 char, level 251 needs Hell): red "Requires Hell difficulty" then D2R's "Impossible." |
| Lockout clock | PASS | Hell rules, key `b62X` into level 253: orange "Closing in: 01:00" and "ONCE YOU EXIT YOU CANNOT GO BACK" |
| Lockout sealed | PASS | 68 s after the first entry: red "This area is locked" / "Join another game to enter again" |
| Heart notice | PASS | `h quest 4 1 set`, `h msg 148 0x76`: "You have received: Griswold's Heart" |
| Arcane Crystal notice | PASS | in Lut Gholein (area 40), `h quest 14 3 set`, `h msg 201 0x1ba`: "You have received: Arcane Crystal" (the same message with Jerhyn spawned in Act 1 does nothing: the vanilla handler is not reached) |
| Goblin notice | PASS | `MXL_GOBLINS_FORCE=1`, Blood Moor: yellow "A treasure goblin has been sighted nearby!" |

Ormus' shrines and Cain's crystal use the same call as Jerhyn's and were not run. The game-start helper `clear_intro` (tools/game_ctl.py) looped on the Continue button when the main menu scene was bright; the runs here clicked the three calibration screens by hand. **Fixed 2026-10-22 (lane bug24b):** `clear_intro` now ends when `menu_visible()` sees the main menu (a 12 x 16 grey signature of the left button panel, `MENU_SIG`: mean difference 0 on the menu, about 27 with a dialog dimming it), clicks Continue at most 6 times and holds Esc at most 4 times (never once the menu is up: Esc on the menu opens the exit dialog); checked with synthetic frames (bright menu, three calibration screens, endless calibration, dimmed menu) and on slot 3's live menu, the real calibration screens did not come up on that slot.

### Results with the harness commands (2026-10-21, background mode, slot 2, plugin 0.47.0 + harness)

`py -3 tools/game_checks.py all` (MXL_SLOT=2), evidence in `%USERPROFILE%\mxl-d2r-runs\checks-20261021-210224\` (all rows
except the lockout clock) and `checks-20261021-211130\` (lockout clock, sealed). Real-input watchdog (cursor and foreground
window every 25 ms): no abort in any run, the game window was never the foreground window, the cursor never moved into it.

| Row | Result | Evidence |
|---|---|---|
| `mxl` command | PASS | 14 feature lines |
| Goblins (FORCE=1) | PASS | `h kill nearest` x2 in the Blood Moor: `h state` goblins 0 -> 1 spawned, log `goblin 2796 spawned in level 2` |
| Akara respec | PASS | `h interact 148`, menu list shows Talk, Trade, vanilla respec (`0x2ba0`) and the plugin line (`handler=plugin@`); `h menu 3`: strength 90 -> 30, 60 stat points refunded, log `npc actions: done (48, 148)` |
| Cain crafting materials line (bug #23) | PASS | menu opens, no `menu record is full` log line, `cain_menu.png` shows TALK / CRAFTING MATERIALS / CANCEL |
| Griswold's Heart | PASS | `h msg 148 0x76` with quest 4 bit 1: new item base `600`, unique index 69, plus the vanilla ring |
| Andariel catalyst, Warriv re-issue | PASS | `h spawn 156` + `h kill nearest 156`: 1 catalyst `3o[`; second kill: still 1; removed, `h interact 155`: re-issued. (Quest 6 must be active when the game is created and the flag, quest 47 bit 0, clear: game_checks patches the closed save first) |
| Median `andariel_ai` users (AI 155) | PASS 46 of 47 (`py -3 tools/game_checks.py all medianai`, slot 3, `MXL_AI_CHUNK=a:b` for a slice) | Every monstats row with AI `andariel_ai` is spawned beside the god-mode player and watched 3 s: the `monster ai` counters rise (thinks, attack, skills) and the monster changes mode; no crash. Diablo clone (333) cannot be spawned by the harness (nothing spawned). Malthael 10-13 and later users are judged on the counters only: Malthael's unkillable dark nephalems (class 1239) fill the `state` list; each monster is killed by id afterwards |
| `andariel_ai` controlled branch | PASS (`py -3 tools/game_checks.py all medianai_ctl`, slot 3) | Maghda hit with `hit mon:<id> phys 1280 stagger`: `controlled thinks` stays 0 before the first hit and rises after it |
| Tyrael travel line follows quest 28 | PASS (`py -3 tools/game_checks.py all tyrael`, slot 3) | `mxl`: `travel gates moved 1`; the line with handler 0x1162f0 is in his menu only with quest 28 bit 0 set, whatever quest 26 says |
| Dungeon lockout: refusal | PASS | Normal, `h use b60X` + `h enter nearest`: refused 0 -> 1, still in town |
| Dungeon lockout: clock, re-entry, sealed | PASS | Hell rules (`h difficulty 2`, level 125), key `b62X` (level 253): entry, clocks 0 -> 1; re-entry after 18 s allowed; after 68 s the entry is refused (refused counter +2, stays in town) |
| Cow portal recipe | PASS | leg in the cube: Normal town no recipe; Hell town recipe 2 runs and a class-60 portal object appears (the handler needs Baal killed in that difficulty: `h quest 40 0 set`); Hell field no recipe |
| Cube gold payment | PASS | row 6327 (50,000): 400000 -> 350000; row 6328 (100,000) with 20,000 carried: carried 0, bank 100000 -> 20000 |
| Craft flags | PASS | player flag: row 6369 (assassin) sets flag 1, then row 6350 is offered; game flag: key row 7102 sets game flag 50, a second try is refused |

Notes: the cube conditions of Median rows are partly on the player (`stat player 378`, `536`, `532`) and partly on the item
(op 18: item stat 532 == 1), see `game_checks.check_goldcraft` / `check_craftflags`. `h cubecraft` returns no item for
portal recipes; look at `h state`. Observed, not fixed (docs/bugs.md #24): entering a Median dungeon level through a portal
can crash the client after a few area changes in one game (assert `asset cache exceeded`, null call), so the lockout clock
check runs first and the full run ends with a crash on some runs.

### Regression hunt 0.49.0 (2026-10-22, lane regress049, slot 3)

Two checks of `game_checks.py all` failed on 0.49.0 and passed on 0.48.0.

| Check | Before (0.49.0) | Cause | After |
|---|---|---|---|
| `respec` | FAIL: Akara's menu had Talk and Trade only, no plugin line | Not the menu code, not quest 41. The Heart notice added in 0.49.0 (client messages, PR #55) is sent from the quest handler of Akara's speech, in the middle of the speech, and a chat line (types 1, 4, 5) during an NPC speech freezes it: the NPC menu never opens, the menu builder `0x1147a0` is never called (so the plugin's lines are never added). `mxl-core-off.txt` word `clientmsg` made the check pass; `h sysmsg 4/1/5` during the speech reproduced it, type 0 and a line after the menu is open do not. Details docs/d2r-addresses.md section 13 | PASS: notices of quest dialog handlers are held until the client's menu is open (`SendClientNotice`); the screenshot shows the menu and "You have received: Griswold's Heart" |
| `casts` | FAIL: Bash showed no cast animation / mana drop | The check, not the plugin: `cast` at a monster 5-8 sub-tiles away only walks to it (mode 3); the Fallen wander, so the same cast failed for Bash in one run and for earthquake_2 in the next (three runs on the same build, a different case each time). Bash's mana cost and animation are as before (mana 15 -> 12, mode 7) | PASS: `cast_and_watch(approach=True)` moves next to the monster before every try of a melee cast (10 tries) |

`py -3 tools/game_checks.py all mxl respec casts --slot 3` after the fix: all three PASS (`checks-20261022-033532-s3`). The
`respec` check now puts the unused stat points back (each run had raised them by the refunded 60 in the saved test character).

### Verify rows of unported.md (2026-10-22, lane verify-checks, background mode, slot 3, plugin 0.50.0)

Twelve new checks in `tools/game_checks.py` (`py -3 tools/game_checks.py --slot N all resistcap absorb avoidcaps classlock hiregates itemrolls dye goldclient bonusdrops summoner tooltiptext gameend craftflags`), built on the harness verbs `hit`, `avoid`, `itemroll`, `colour`, `req`, `cstat` and `stat player|merc|mon:<id>`. A check needs a merc: it hires Kashya (`quest 2 0 set` first, Blood Raven) and waits for the mercenary to follow into the field. Notes for writing checks: damage and avoidance run only outside the town; `fight_ready` kills everything near, the mercenary too, so call it before `ensure_merc`; a hit on a unit just arrived in an area can return result 0 (ignored), the `hit` helper retries; a walking mercenary cannot avoid or dodge.

| Row | Check | Result |
|---|---|---|
| Max resistance cap 90 (player, mercenary) | `resistcap` | PASS: resist 200 and max-resist +0 / +10 / +50 took 25 / 15 / 10% of a 100000 hit, fire / lightning / cold / magic, 24 of 24 |
| Absorb stats 184 / 189 / 417 | `absorb` | PASS: 8 probes, the healed amount equals the formula to the unit (e.g. 30% of 100000 with 7% stat 184: 27900; with 184 = 57%: 12900; divisor 4: 6975; 417 layer 1 at 50%: 13950) |
| Mercenary avoid / dodge / evade caps; player | `avoidcaps` | PASS: 2000 rolls each of the hooked `0x44ef70`: stat 100 with stat 380 = 0 / 10 / 30 gives 60 / 70 / 75%, stat 50 gives 50%, player and Rogue |
| Class-locked items (stat 492), players and mercenaries | `classlock` | PASS: locks 1-8 against 7 player classes and 3 merc types |
| Hireling equip gates by class | `hiregates` | PASS: 4 hire classes, allowed / refused weapon and shield types as the lists |
| Socket roll | `itemrolls` | PASS: 4000 items, 1/7 per socket count below the base maximum |
| Sockets and automagic for every quality | `allqualsockets` | PASS (slot 3, 2026-10-22, lane pa-sockets): 3000 items per quality at item level 101 on a 6-socket base (`60@`): low / normal / superior / magic 0..6 sockets, about 1/7 each; rare / unique / crafted / tempered 6 on all 3000; automagic mod on all 3000 including unique. With `allquals` off: magic 0, rare / unique / crafted / tempered 0 sockets, unique automagic 0 of 3000 (check FAIL as expected). Set (5) not generated by the harness: not judged |
| Ethereal roll + 25% | `itemrolls` | PASS (0.51.0, lane ethereal-avoid): the harness had passed generator bit 2 (no ethereal); fixed. 4000 tower shields at item level 101: 102 ethereal (2.55%, Median 2.6%), defence x1.24, maximum durability 60 -> 45; quality 1 (low): 94 ethereal, 19 -> 14. Rate required within 4 sigma. docs/bugs.md #25 |
| Dye colour (stat 368) | `dye` | PASS: bytes 0x00..0x14 for stat 1..21, undyed for 0 and negative |
| Socketed runes stack (bug #50) | `runestack` | PASS: player stat after 0-3 sockets filled (packet 0x28): Eld max damage 0/3/6/9 in armour, helm, shield; Ral fire res 0/30/60/90; gem gpv AR% 0/50/100/150; jewel fire res 0/30/60/90; Runemaster 20: Defense % 0/20/40/60 |
| Craft player flags by name | `craftflags` | PASS |
| Craft per-game flags reset on game end | `gameend` | PASS: flag 50 set by recipe 7102, 0 in the next game, `games ended` 0 -> 1 |
| Gold payment client update | `goldclient` | PASS: client gold stats equal the server's after rows 6327 / 6328 |
| Summoner AI / MosquitoNest | `summoner` | PASS: spawned, acted (cast and moved), summoned |
| Bonus drops (Summoner / Izual catalysts) | `bonusdrops` | PASS: one on the ground after each of two kills, quest bits set. Per-player count in multiplayer: manual |
| Item tooltip text (65 stats) | `tooltiptext` | PASS: 313 property lines read through D2R's formatter (294 equal Median's text, 19 read on real items, 0 wrong) plus 5 unique items and 12 rare / magic items read as real items; the table is docs/item-tooltips.md |
| Trade window | none | manual: needs two players (TCP/IP), not scriptable here |

Also found: the avoid hook's first parameter is the attacker unit, not the game (docs/bugs.md #26).

### Potion amounts, stamina and mana rules, get-hit durability (lane pa2-stats, 2026-10-23, background mode, slot 1, plugin 0.54.0 + this branch)

`py -3 tools/game_checks.py --slot 1 all manarules sprint`, then with `potionamounts stamina manaregen durability` in `mxl-core-off.txt`
`all manarules potionamounts nodurability sprint`. The first pass on slot 3 (`potionamounts manarules nodurability heat townmana sprint`)
gave PASS for `potionamounts`, `nodurability`, `heat` and `townmana`; its `manarules` failed only in the state 136 leg (the first
`setstate` made no state list) and in a 6% tolerance on the walking rate (39.7 against 37 raw per frame). Both were fixed in the check (the
`setstate` verb now builds the state list the way D2R's self buffs do; tolerance 15%).

| Check | With the parts | Off words | Evidence |
|---|---|---|---|
| `potionamounts` (audit item 11) | PASS | FAIL | harness `rewardstep potion` / `tome` (D2R's own grant steps `0x580680` / `0x5ed6d0`): +50 max life and +10 stat points (off: +20 and +5) |
| `manarules` (audit item 15) | PASS | FAIL | standing 49.5 raw per frame (off 50.6; max 50 / 256, both builds); walking 37.1 (off 25.8); state 136 set with `setstate`: stamina 0 -> 50 of 50 in 1 s (off: 6 of 50); a 40 raw mana pool with bonuses off: 0 after 2.5 s (off: 40, D2R's floor of 1 per frame); a run in the Rogue Encampment from full: 6 samples running, lowest 50 of 50 (off: 5 samples, 50 of 50, so the town rule is vanilla's) |
| `nodurability` (audit IT1, item 12) | PASS | FAIL | weapon 70 -> 70 and armour 48 -> 48 after 600 `wear` steps in both directions (off: 70 -> 63 and 48 -> 20); 25 s of real monster hits (850 life lost): armour 48 -> 48. With the part off the armour did not wear down in the real hits either (613 life lost), so that leg only shows that nothing breaks; the `wear` step is the SUnitDmg call `0x4526c0` itself |
| `heat`, `townmana` | PASS | not run | unchanged by the new mana step (heat: 25496 -> 18840 -> 11768 -> 0, Flamefront builds up, a town holds; townmana: cost 957 in the field, none in town) |
| `sprint` (audit SK7) | FAIL | FAIL | the check of that day measured the stamina with a second console read after the state read (a different frame) and judged medians, so its walking, timing and toggle results varied from run to run with every part of this lane off. It now reads frame, mode and stamina from one `state` reply and asserts the exact per-frame rules above (lane checks-robust) |

New harness verbs: `rewardstep potion|tome` and `setstate <ref> <state> <0|1>` (table above).

### Hunter Steady Aim, Fire Sorceress Heat, trophy windows (2026-10-22, lane gap-classres, background mode, slot 3, plugin 0.54.0 + the lane's parts)

`py -3 tools/game_checks.py --slot 3 all steadyaim heat trophytimer` (evidence `checks-20261022-215233-s3`, data and DLL installed together with `install_mod.py --slot 3`; the merge of main had changed the data, a run with the old data under the new DLL read the counter 6, 6, 6, 6). All three drive the plugin through the harness (no input).

| Check | Result |
|---|---|
| `steadyaim` | PASS: 4 Steady Shots read the counter (stat 220 layer 5) 1, 2, 3, 4; Heartseeker is refused (4, restricted) with no counter and usable with it; one Heartseeker leaves 3, the spend runs the counter to 0 and the skill is refused again |
| `heat` | PASS: Molten Core gives stat 297 = 107 at level 21; mana x256 from full 25284 -> 20228 (2.5 s) -> 15093 (5 s) -> 0 (floor 0); Flamefront at empty: peak 1106 and stat 297 goes negative; in the Rogue Encampment a set 12800 is still 12800 3 s later |
| `trophytimer` | PASS: Heart of Sin (stat 378 = 167166, assassin recipe 6377): in time the recipe matches; 12 s later, after Blood Moor and back, and after dying (spawned attacker, 2e9 hit) it does not, with the stat still 167166 each time |

How they work and what is not tested: `docs/plugin-spec.md` "Skill restrictions", "Steady Aim", "Heat", "Trophy timer". The trophy check
sets stat 378 to the Heart of Sin code (167166) with the harness: nothing in the data names the skill a boss kill casts, so the
kill itself is not exercised. Findings on the way: `tools/formula.py` turned a missile `stat(x, n)` with a layer into a plain stat
read (wrong layer), and `txt_migrate.py formula_proxies` read the `ParamN` columns by position; both fixed.

### Skill damage scaling (2026-10-22, lane pa-skills, background mode, slot 1, plugin 0.54.0 + the lane's part)

`py -3 tools/game_checks.py --slot 1 all skillscaling` (evidence `checks-20261022-223626-s1`; data and DLL installed together with `install_mod.py --slot 1`; the plugin reports `skill damage on: elemental + physical min/max, 164 BaseSynergy and 423 StaticDamage skills`). Nothing but the harness: `skilldmg` prints the damage through the hooks and through D2R's own functions, and the inputs the formula needs (character level, energy, stat 514, the synergy percent columns, the mastery stats); the check computes Median's formula in Python from the built `skills.txt` columns and `skills2.bin` flags and compares.

| Check | Result |
|---|---|
| `skillscaling` | PASS: 572 samples (7 groups of skills x skill levels 1, 2, 8, 9, 16, 17, 22, 23, 28, 29, 45 x 4 character setups: level 1 / energy 0, level 40 / 150, level 100 / 300 with stat 514 = 600, level 150 / 1000 with stat 514 = 5000, each with 0-60% mastery stats) equal the formula. BaseSynergy is -42% at level 1 and 1626% at level 100 / 300 energy / stat 514 600. Nova and Meteor (BaseSynergy elemental), blast_wave (BaseSynergy physical), Magic Arrow (StaticDamage elemental: mastery 40 changes nothing), immersion (StaticDamage physical), Fire Bolt, Telekinesis, DiabRun, PoisonBallTrap (plain; stat 357 raises the physical ones). 18 samples of skills with no flag and no mastery equal D2R's own functions to the digit (elemental, physical, and skills with a weapon share: Sanctuary, MonLeapAttack). Synergy: raising Fire Arrow 1 -> 12 raises Poison Javelin's percent column 12 -> 144 and its damage (8744-9891 -> 19051-21550) as the formula says; Charged Bolt from Lightning likewise |

Not tested in the game: the weapon share of the four BaseSynergy skills that have one (scorpion_blade, thunder_hammer, thunder_wave, angel_of_death; the unit tests cover the arithmetic, and the weapon share of plain skills equals D2R's), skills whose `passive` flag keeps D2R's physical function. A first run on slot 3 gave the same results but lost two samples to harness time-outs (`no answer in 15 s`); `_sd_query` now retries.

## Scripted checks (tools/game_checks.py, 2026-10-21, foreground input)

Console commands and measured coordinates: [dev-console.md](dev-console.md). Results of the partial run (the run was
stopped before the full set finished because the foreground input took the user's mouse; the checks are to be re-run
in background mode once `lane/bg-input` is on main). Evidence is in `%USERPROFILE%\mxl-d2r-runs\checks-20261021-140330`
(interactive exploration) and `checks-20261021-163305` (scripted run).

| Row | Result 2026-10-21 | Evidence / note |
|---|---|---|
| `mxl` command | PASS: prints all 15 feature lines (plugin 0.42.0) | `checks-20261021-161134\mxl_cmd.png` |
| Goblins (MXL_GOBLINS_FORCE=1) | PASS: after killing a Fallen in the Blood Moor a goblin spawned (log `goblin 2798 spawned in level 2 near player 1 (frame 5250)`, a second run `goblin 2791 ... frame 1500`); drop and name not looked at | `checks-20261021-140330\after18s.png`, `checks-20261021-163305\goblin_scene.png`, `goblin_mxl.png` |
| Akara respec | PASS by hand: with a level-12 character and the Den of Evil bit set (quest 41 word 2), Akara's menu shows Talk, Trade and two "Reset Stat/Skill Points"; the second one logs `npc actions: done (kind, npc class) (48, 148)` and the character sheet then shows 55 stat points remaining (reset). The scripted version clicked the wrong line (vanilla one) and is fixed but not re-run | `checks-20261021-140330\akara_menu1.png`, `respec_char_after_line2.png`, `checks-20261021-163305\respec_3_menu.png` |
| Cain crafting materials | FAIL (bug #23): the line does not show, log `menu record is full` | `checks-20261021-140330\cain_menu1.png` |
| Griswold's Heart | PASS (script): patched save with quest 4 bit 1, talked to Akara twice, one new item in the inventory; the unique's name/stats were not read | `checks-20261021-161134\heart_inventory.png` |
| Andariel catalyst, Warriv re-issue | BLOCKED: no cheat kills Andariel (`god`'s easykill does not one-shot her; 14 axe hits did not), and the quest state for event 8 was not set up | `checks-20261021-163305\catalyst_after_kill1.png` |
| Cow portal recipe, town vs field | PASS for Normal town (recipe 3 has min difficulty 2: nothing happens), earlier manual try; Hell town/field BLOCKED: `spawn leg` plus `spawn tbk` could not be picked up by the script in the later run | `checks-20261021-140330\cow_after.png`; script run `cow_hell_*_pickup_failed.png` |
| Cube gold payment, craft flags (6327-6329, 7100, 6369 -> 6350) | BLOCKED: the recipes need items with Median stats (stat 532, `UpgradedBossKillerRing`, `RathmasSupremacy2`) and no console cheat sets an item's stat or spawns these as upgraded; also `cubeinputs`/`cubestuff` failed for recipes 2, 3 | dev-console.md |
| Dungeon lockout (refusal, clock, seal) | BLOCKED: `spawn b61X` did not yield a usable scroll/portal in the script; not seen manually. The `mxl` command shows counters `refused N, clocks started N` that the check should read | `checks-20261021-163305\lock_normal_portal.png`, `lock_mxl.png` |
| Warriv re-issue | BLOCKED with the catalyst check | - |

### Background-mode run (2026-10-21 18:42, `py -3 tools/game_checks.py all ...`, plugin 0.46.0)

Run folder `%USERPROFILE%\mxl-d2r-runs\checks-20261021-184217\` (report.md, screenshots). Real-input watchdog (cursor
and foreground sampled every 25 ms for 10 minutes, 23,303 samples): the game window was never the foreground window and
the run never moved the real cursor into it (the cursor values in the report are the user's own mouse, x 0..5819,
y -1417..2159); no abort. Console lines go through the plugin harness; D2R's cheat output is not readable in this mode, so
cheats are verified by their effect in the screenshots.

| Row | Result | Note |
|---|---|---|
| `mxl` command | PASS | 14 feature lines read through `console_text` (`mxl_town.png`); the whirlwind line no longer exists in 0.46.0 |
| Goblins, Akara respec, Griswold's Heart, Andariel catalyst | FAIL / BLOCKED in this run: **clicks on the game world do not register in background mode** (a left click on a monster does not attack it, a click on Akara does not open her menu, the character does not walk; UI clicks on menus, the inventory and the cube panel do work). `goblin_scene.png` shows 14 spawned Fallen around the character, none hurt; `respec_3_menu.png` shows no menu after the click on Akara. The earlier foreground results above stand. Not yet verified why (hypothesis: world clicks need the button state to be held across several game frames or a hovered-unit update the virtual cursor does not provide); `lane/bg-input` needs to make `click()` work in the world, or the harness needs `interact <unit>` / `attack <unit>` / `move x y` commands |
| Cow portal recipe, lockout (refusal, clock, seal) | BLOCKED: after `cheat itemgridclear` the `cheat spawn box,inv` / `leg,inv` / `tbk,inv` lines through the harness put nothing into the inventory (`cow_normal_town_spawn_failed.png`); the same lines typed in the console panel in the foreground run did. The lockout needs the scroll in the inventory, the counters (`refused N, clocks started N` in `mxl`) are readable already |
| Cube gold payment, craft flags | BLOCKED: needs harness commands `item <code> [stat=value ...]` (item with stats in the inventory), `flag player\|game N get\|set\|clear`, `gold get` |
| Andariel kill (catalyst, Warriv) | BLOCKED: needs a harness command `kill <monster>` or world clicks that work, plus `quest <id> <state>` to put quest 6 in progress |

### Monster looks (lane sigma-behaviours-b, 2026-10-22, slot 3, background mode)

Run folder `%USERPROFILE%\mxl-d2r-runs\checks-20261022-101244-s3\` (not committed). `h spawn 2791 1` (treasure goblin) in the Blood Moor.

| Row | Result | Note |
|---|---|---|
| `mxl` monster looks line | PASS | "monster looks on: name colours on, automap on, spawn overlays on (1803 monsters in the table)" with counters |
| Automap marker and name | PASS | `goblin_automap.png`: Tab shows the blue NPC marker and "Treasure Goblin" under it; counter 124 markers / 124 names |
| Spawn overlay | PARTIAL | counter "1 spawn overlays (last 53 on monster 2791)" and the game stays up; the effect itself was not seen in the 0.4 s captures. The first build read the creation function's result without a check (callers that return 1) and ended the game on `cheat goto 2` (crash reports of `d2rloader\crashes`: read at address 1); fixed by only reading pointers |
| Name colour | BLOCKED | the hover needs the cursor over the monster; background mode cannot place it. Rules and data are unit tested (`monster_looks_test.cpp`), the hooks install ("name colours on") |
| PalShift stand-ins | PASS (tool) | `work/mod/effects_hd.md` paragraph PalShift: 21 shifted rows scored, 13 custom art; not looked at in game |

### Backlog B: the old "fix to test" rows of bugs.md (lane bug-backlog-b, 2026-10-22, slot 2, background mode, plugin 0.53.0 + this branch)

Run folders `%USERPROFILE%\mxl-d2r-runs\checks-20261022-*-s2\` (not committed). One check per bug, all PASS; run them with `py -3 tools/game_checks.py --slot N all <check>...` (at most three checks per call: a call stays under 10 minutes).

| Bug | Check | Result | What it does / what stays manual |
|---|---|---|---|
| #3 skill tabs | `skilltree` | PASS | clicks the 8 tabs; harness `skilltab` reads the page of each click ([0..7]) and 8 / 8 panel pictures differ. Titles and stone art: look at `skilltab1-8.png` |
| #9 skill tooltip assert | `skilltree` | PASS | hovers all 144 icon cells: no `stringIndex1 != strdummy` box in d2rloader.log. **Root cause of the old "hover does not work in background mode": WM_MOUSELEAVE.** The harness hook of `TrackMouseEvent` (testharness.cpp) now makes it a no-op, so the hover and its tooltip stay up |
| #5 keybinds | `keybinds` | PASS | Options > Controls: Skill 9 = F9, Apply; `<char>.key` md5 cd37237f -> 57e96a28; Save and Exit, restart: same md5 and Skill 9 still F9; F6 skill hotkey selects the same skill before and after. The layout is restored (Default key list) |
| #7 NPC text | `strings` | PASS | the client's string function (harness `str <id>`) for 592 NPC intro / Median strings: 0 wrong, no Median key shares a 16-bit id with a D2R string (D2R ships 27956/28082 shared itself). The subtitle on screen: manual look |
| #15 automap | `automap` | PASS | one area per level type 36-51; harness `automap [type]` lists rows, how many resolve to an atlas cel, the game's own lookups and hits, and (single type) the first missed tile/style pairs. Type 37 has only wall rows, the game asks for styles 2/7/30, so 0 hits there is Median's own table; types 45-50 have no rows (unported.md) |
| #17 levels > 255 | `scrollportals` | PASS | each summoning scroll in its act's town, `enter <portal id>`: areas 251-253, 263-268, 274-276 reached. Entry needs Hell (difficulty 2) and level 150 (mxl_dungeons.h levelReq 120-147); the check restores level 5 and difficulty 0 |
| #18 vendor crash | `vendors` | PASS | Akara, Charsi, Gheed: interact, Trade, tabs (Akara has no Armor tab: a click on that spot closes his panel), right click buys one Misc item each (gold 40000 -> 39999): game alive, 0 `[default_unit]`, 0 `File not found`. One skillDescTbl assert box per run (bugs.md #29). The vendor pictures: look at `shop_*.png` |
| #22 monsters | `monhover` | PASS | spawns a zombie, the virtual mouse goes over its projected position (harness `hover` names the unit), left clicks kill it in ~16 hits. Same WM_MOUSELEAVE root cause as #9 |

New harness verbs (client side unless noted): `skilltab [n]` (selected tab, or select tab n), `str <id>..`, `hover`, `automap [type]`, `shop [npc class]` (server: the vendor's stock; buy through the panel), `levelact <id>..` (server: act of a level). `state` monster lines carry `mx= my=` (world position).

Slot procedure used: `py -3 tools/game_slots.py lock 2 lane-backlog-b`, `py -3 tools/install_mod.py --slot 2`, `MXL_RUN=lane-backlog-b py -3 tools/game_checks.py --slot 2 all <checks>` (the run keeps the lock and releases it at its end). A full install is needed after another lane has used the slot: a partial data set from a foreign install made `strings` fail once (253 wrong, "Missing string"), and a re-install fixed it.
Noticed and not fixed: the Wolf Stance tooltip shows a literal `%+d%%` (bugs.md #30).

### Travel: map reveal, waypoint auto-activation, hotkeys, stash pages (lane gap-travel, 2026-10-22, slot 1, background mode)

Run folder `%USERPROFILE%\mxl-d2r-runs\checks-20261022-224210-s1\` (not committed; the run is `py -3 tools/game_checks.py --slot 1 all mapreveal wpauto hotkeys stashpages`). Plugin verbs: `mapcells`, `reveal`, `wpobj`, `travel`, `stashprobe` ([Harness commands](#harness-commands-gameplay-without-input-pluginsrcharness_cmdscpp)).

| Row | Result | Note |
|---|---|---|
| Map reveal (R, MU2) | PARTIAL | the harness `reveal` (the R hotkey's call of D2R's debug Reveal Automap) returns, the automap layer list grows 1 -> 25, a second reveal adds nothing, the debug flag byte is kept. The picture did not change: `cheat goto` and the town arrive with the map drawn whole (`mapreveal_before.png` = `mapreveal.png`), and the cell count stays 8878. A fresh field level reached by walking was not tested. A first pixel-difference criterion passed on a moving NPC only and was removed |
| Waypoint auto-activation (WP2, WP3) | PASS | Cold Plains waypoint (number 1): bit set within 1.5 s at distance 3, still clear at distance 47 (negative control), set at distance 24 while walking up. Two players in one game were not run |
| Hotkeys X / R / C (UI4, CR5) | PASS (first port; the defaults are now X / L / K, see "Checks that no longer depend on the test character's history" below) | window-message presses reach InputService: X toggles (0->1->2 presses, pickup on/off/on), R reveals (+1), C with the cube closed is counted and ignored (transmutes 0, blocked 1), C with the cube open calls Transmute (transmutes 1). The cube-open state comes from the UI message `PanelManager:OpenPanel(<cube panel>)` and `ClosePanel` / `UnloadPanel`. The default keys can overlap D2R's own R and C bindings; not checked |
| Stash pages (GS5) | PASS | `add_shared_tabs = 7` in `d2rloader.toml`: an item created through ItemService lands in shared tabs 0-9, tabs 10 and 12 are refused. The personal stash stays one page; no Prev / Next / Sort / Mode buttons |

### Monster level, players scaling, Normal drops, leash (lane pa2-monsters, 2026-10-23, slot 1, background mode, plugin 0.54.0 + the lane's parts)

Run folders `%USERPROFILE%\mxl-d2r-runs\checks-20261023-010539-s1\` (parts on) and `checks-20261023-010836-s1\` (negative control, `mxl-core-off.txt` words `monlevel playersx normaltc leash`; not committed): `py -3 tools/game_checks.py all monlevel normaltc leash --slot 1`. The plugin's real-input watchdog saw 0 cursor changes and 0 focus changes.

| Row | Result | Note |
|---|---|---|
| Monster level (DF3, item 17) | PASS | stat 12 of spawned monsters equals the area's `MonLvlEx` in areas 2 / 76 / 111 in Normal, Nightmare and Hell, for a living class (18) and a lUndead class (0). Off: Normal monsters keep their own monstats level (28 and 2 in area 2, where the area level is 1): FAIL |
| Players scaling (DF7, MP3) | PASS | 8 monsters in Hell at `players 1` and `players 8`: mean life x4.49 (Median 4.50), experience 450 / 450, level 100 / 100, players stat 1 / 8. Off: the `mxl` line says off and the checks fail on the line |
| Normal-difficulty drops (item 18) | PASS | a Normal kill of a level 6 monster hands the class getter level 6; a Nightmare kill of a level 52 monster level 52. Off: no lookups traced (the trace hook is only installed with the part) |
| Leash (item 19) | PASS | the mercenary moved 20 / 30 / 36 sub-tiles from the player walks back; at 44 / 47 / 60 it warps (distance drops 25 / 32 / 39 within one sample). Off: it walks back at 44 / 47 / 60 |

Not run: summons and the AI 112 / 107 followers (only the mercenary is checked), a second real player, the Baal throne delay, the items rolled by the stepped Normal class. Moving the player to make the distance pulls the mercenary along at once (that is how the first probe misled); the harness moves the mercenary instead.

### Gamble window and small engine rules (lane pa2-gamble, 2026-10-23, slot 3, background mode)

Run folder `%USERPROFILE%\mxl-d2r-runs\checks-20261023-003647-s3\` (not committed; `MXL_RUN=lane-pa2gamble py -3 tools/game_checks.py --slot 3 all mxl gamble enginegaps`). New harness verbs (server side): `gamble` (the player's gamble offers, player data `+0x108`, the same item lines as `shop`, then `gamble offers N`) and `gaps` (the bytes at the hit-20 floor and the recast guard, and the player slow floor through the hooked entry `0x449f40`).

| Row | Result | Note |
|---|---|---|
| Gamble offers (audit item 16, IT10) | PASS | Gheed opened through `interact 147` and the Gamble line of his menu (handler `0x112c80`), then the same request twelve more times through `pkt 38 02 ...` (packet `0x38` kind 2 with Gheed's id): every window has 32 offers (13 x 32 = 416) in 32 distinct cells of page 0, a ring (`rin`) and an amulet (`amu`) in each, 311 magic, 101 rare (242 per mille; Median's chance is 25000 per 100000), 4 unique, no set item, and no window equals the one before. Negative control (`mxl-core-off.txt` with `gamble`): 14 offers per window and the check fails, so 14 is D2R's own count |
| Hit 20 floor, recast guard (audit item 21) | PASS (bytes) | `gaps`: `0x45edce` reads `31 db 85 c0 0f 4f d8` and `0x56f859` is 13 x `90`; with the off word `recast` the guard keeps `e8 52 59 dc ff 85 c0 0f 85 b9 02 00 00`. The effect is not tried in play: it needs a skill whose calc comes out 0 or less (hit 20) and a srvdofunc 47 skill cast twice |
| Player slow floor (audit item 21) | PASS | `gaps` at difficulty 0 / 1 / 2 (`h difficulty n`): -12 / -25 / -50 through the hooked entry |

Off words are letters only (digits are dropped when `mxl-core-off.txt` is read): the hit-20 floor is `hitfloor`, the Worldstone / Throne object hook is `worldstone`.

### Checks that no longer depend on the test character's history (lane checks-robust, 2026-10-23, slots 1 and 3, background mode)

The release suite (0.54.0, runs `checks-20261022-212141-s1`, `-212441-s3`, `-2256*-s3`) failed checks that pass on a fresh character. The causes were in the checks, the state the earlier checks leave, or the stored settings of the install; none in the game rules the checks test, except the stored hotkeys (below). Run: `py -3 tools/game_checks.py --slot N all respec itemevents medianai medianai_ctl tyrael resistcap avoidcaps classlock bonusdrops summoner vendors itemskills nocorpse deathcrash sprint hotkeys manarules`, once on slot 3 (character `MxlBarb`, level 27 after the `respec` / `xp` checks) and once on slot 1 (level 150, different gear, stash and merc history).

| Check | Cause of the failure | Fix |
|---|---|---|
| respec | the check compared the unused stat points with a fixed number; a character that has spent points (strength 90 / 150) refunds more | `before` / `after` base stats 0-3 are read; the refund is the sum of the differences, and `unused after = unused before + refund`; the stats and stat 4 are put back afterwards |
| tyrael, vendors (Gheed "no menu") | the character was dead or the NPC click was lost; a dead character cannot talk | `npc_menu` revives first, then retries (close menu, interact, spawn a copy of the NPC, wait 30 s then 15 s) up to four times |
| avoidcaps, resistcap, classlock ("no mercenary could be hired") | (1) `itemevents` set life to 100 for its measurement and then wrote the life stat of a character that had died: the server unit stayed in mode 17 while the client believed it alive, so hits, menus and hires did nothing and Esc only paused the game (zombie death); (2) `medianai` leaves 30 unkillable dark nephalems (class 1239) in Blood Moor, which killed a level 150 character within two seconds of `cheat goto 2` | `revive_if_dead` (life 0: Esc every 3 s; zombie: Save and Exit + Play puts the character in town alive); `itemevents` puts life back; `ensure_merc` revives, sets gold and quest 2, tries `hire 150 n` for the free entries and spawns Kashya when missing; `clean_area` (used by `fight_ready`, `medianai`, `medianai_ctl`) kills what can be killed and starts a new game when something survives |
| bonusdrops | quest 13 / 25 and the flags (quest 47 bits 1 / 2) were already set by an earlier run, so the kill handler never ran or the catalyst was not re-issued | `clear_quest_bits` resets quests 13 / 25 and the bits before the first kill and the quest before the second |
| sprint | the character's stamina stats (max, recovery 28, drain 154, skill percents 162 / 163, per-level and by-time gains 241 / 242 / 294 / 295) changed the run time; the run toggle R is the character's own setting and survives a restart; the samples of stamina and of the frame were two replies apart | the wrapper zeroes the bonuses, sets Median's 50 points and restores everything; `state` reports `frame`, `stamina`, `maxstamina` in one reply, and the check asserts Median's rules (pa2-stats, audit item 15 / SK7) per frame and exactly: running -120 raw per frame (107 frames from full), walking +37, standing +50 (refill in 253-261 frames), a run starts with 2 points, state 136 fills, R gives one run and one walk. Nothing was loosened; the R-toggle step needs open ground and a `state` reply takes 0.6 s, so it goes to the Rogue Encampment, clicks the far points first (a click 8 units away is over before the first sample), accepts mode 6 (town walk) as walking, and goes back to Blood Moor; run/walk speed is the fastest unbroken stretch of samples (whole-unit positions a few frames apart are 25% off per pair); the 2-point run start also tries shorter paths |
| resistcap | slot 3's character wears an item with Median stat 184 (damage taken -25% after resistance, stat 369 here) that cut the 90% cap's share to 75% | the check zeroes stat 369 of player and merc and puts it back, and judges `_reduce(want, stat 184)` of what the gear still gives |
| (all checks) | `leave_and_reenter` left `in_game` False when the Save and Exit click did not leave the game, so every later check was BLOCKED "not in a game" | it restores the flag and returns False; `clean_area` then goes on in the same game |
| itemskills (table half) | `medianxl:` prefixes on the skill name cells: 3844 of ~6000 parameters compared, "mismatches 0" but FAIL on the count | `item_skill_audit.py` matches rows by `strings_ns.bare`; the criterion is mismatches plus "every table with skill parameters contributed" (6054 parameters, 10 of 10 tables) |
| summoner | `medianai` left class 1239 in Blood Moor: "Summoner 250: modes [1]" | `clean_area` (above) |
| deathcrash | a merge had put the `nocorpse` body inside it, and it ran in town (a player cannot be hurt there: `result=0`) | `nocorpse` is its own check, `deathcrash` revives, goes to Blood Moor, hits up to five times and judges by the player's mode, not by the hit's result line |
| nocorpse | the ground gold piles were compared between Blood Moor (before) and the town (after the respawn) | compared only inside the same area |
| itemevents | (1) the life-on-kill gain was read before the heal landed; (2) after the merge of pa2-monsters (monster level by area) a spawned monster has 3-7 points of life, so the 50-point thorns event killed it (life 0 is not `a - 50`), and a monster next to the character may fire the event a second time | (1) polls for up to 1.6 s; (2) the monster is given 2734 points of life before the event, and the loss is judged as a whole multiple (one or more) of 50 points |
| manarules (pa2-stats) | `standing` counted only mode 1, but a character that has just arrived in an area (`cheat goto`) stays in mode 5 (town neutral) until it moves: 0 frames, "recovery None" | standing = modes 1 and 5 (the rule is the same, audit item 15) |
| hotkeys | see below | see below |

Hotkey defaults. travel.cpp (PR #113) registered `mxl_pickup_toggle` X, `mxl_map_reveal` R, `mxl_transmute` C. In D2R, R is the run / walk toggle and C the Character screen (the character's `<name>.key` file: R = action 35, C = action 1, V = action 45), so one press did two things; the Median install on the test machine keeps its keys in `preferences.json` (nopickup 0x58 = X, revealmap 0x4c = L, transmute 0x56 = V) and V is a D2R action too. New defaults: **X** auto pickup (Median's), **L** map reveal (Median's), **K** transmute (the free key next to Median's V). The check reads the registered bindings from `h travel`, requires them to be the defaults, requires that none is in the D2R key file (57 bound keys), presses each key and requires that only its own counters move, presses R and C and requires that no plugin counter moves (with a Character screen screenshot), and drives the transmute key with the cube closed (counted, blocked) and open (transmutes 0 -> 1).

Stored bindings. D2RLoader writes every registered action's key into `<game>/d2rloader/config/input-bindings.toml` the first time the plugin registers it (`primary_key = 82` for R, `67` for C), and keeps it: changing a default in the plugin does not reach a player who already ran an older build. Slot 3 still had R and C stored, so the first run after the change failed with `mxl_map_reveal is bound to R` and the plugin's reveal swallowed the run toggle (sprint saw the first R press give no run). `tools/install_mod.py` now drops the two stored entries of the first port's defaults (only when the stored key is still the old default) so the next start registers the new keys. Players who rebound an action by hand keep their key.

Results of the final full run on both slots (the code of this commit, merged with main after PR #124):

| Check | Slot 1 (level 150, stash and merc history) | Slot 3 (level 27 after `respec` / `xp`) |
|---|---|---|
| respec | PASS | PASS |
| itemevents | PASS | PASS |
| medianai (all users act) | PASS | PASS |
| medianai_ctl (controlled branch) | PASS | PASS |
| tyrael | PASS | PASS |
| resistcap | PASS | PASS |
| avoidcaps | PASS | PASS |
| classlock | PASS | PASS |
| bonusdrops | PASS | PASS |
| summoner | PASS | PASS |
| vendors | PASS | PASS |
| itemskills (every table has parameters) | PASS | PASS |
| itemskills (unique parameters) | PASS | PASS |
| deathcrash | PASS | PASS |
| nocorpse | PASS | PASS |
| sprint | PASS | PASS |
| hotkeys | PASS | PASS |
| manarules | PASS | PASS |
| **Total** | **18 / 18 PASS** | **18 / 18 PASS** |

Run folders `checks-20261023-044022-s1` and `checks-20261023-044022-s3` (both 0 new crash files). Before the fix of bug #33, four of the long chains on slot 3 ended in the goblin crash; afterwards 120 goblin kills in a row on slot 1 and both final chains ran through.

Fixed: the intermittent client crash after a goblin kill, docs/bugs.md #33.

### Release 0.55.0 suite: the 9 FAIL and 4 BLOCKED rows (lane release-055-fixes, 2026-10-23, slots 1 and 3, background mode)

Cause of every non-pass of the first 0.55.0 run (88 checks; 94 PASS / 9 FAIL / 4 BLOCKED):

| Check | Cause | Kind | Fix |
|---|---|---|---|
| damagered, steadyaim, trophytimer, restrictitems, funcslots, nodurability (slot 1) | One shared cause: the emptied field leaves a **town NPC as the nearest monster**. `hit`'s default attacker and `kill` / `cast ... nearest` took the NPC (Warriv, Gheed), so no hit landed; a full backpack made the equips fail; the Steady Aim counter leaked from steadyaim into restrictitems; feral_strike needs an axe or a sword in hand and the melee target wandered off between cast and hit frame; Normal-difficulty level 1 monsters almost never hit a level 150 character (0 - 1 life points in 20 s, 13,000 in Hell) | game harness (the hit verb) and checks | plugin `h hit` default attacker is now the nearest live monster that is neither the mercenary nor an NPC (`NearestFighter`); the checks clear the pack first, clean the Steady Aim counter and state (`aim_clean`), use `tough_target`, wield an axe or sword, freeze the melee target (state 1) and spawn the get-hit attackers under `h difficulty 2` |
| levelcap | Not a game bug. The check piled up 2327 stat / 567 skill points of earlier checks; Median's own save fields are 11 bits (2047) and 9 bits (511) and D2RLoader's extended mode follows CSvBits and saturates | check | realistic totals (a level 150 character earns 745 / 149); the check reads and reports the widths ([save-format.md](save-format.md), [unported.md](unported.md)) |
| itemrolls, allqualsockets (BLOCKED) | `itemroll` gained `identified=`, `qualities=`, `automagic=` fields; the regexes did not allow them | check | regexes accept extra `name=value` fields |
| restrictitems | Behaviour is Median's (cast refused without Steady Aim code 4, allowed with counter 1 code 0, item cast on kill fires both times); the pass condition compared the wrong counters | check | pass condition |
| absorb | The first probe read 0 healed before the damage reduction settled | check | probe retries up to 5 times like `hit()` |
| craftflags (slot 3) | The check switched the character to an assassin (`class 6`); with any class other than its own the harness cannot place an item in the cube ("placing failed"), so no recipe matched | check | the setter row of the character's own class is used (6369 + 19 per class: ass, pal, dru, nec, sor, bar, ama) |
| gamble, vendors ("Gheed's menu did not open") | NPC interaction depended on the arrival position | check | `npc_menu_near`: walk next to the NPC, retry, then spawn a copy, three rounds |
| heat, sprint (slot 1, found in the full run) | heat: the drain per tick is a share of the **maximum** mana, so a fixed 100-point bar was gone in one tick on the 6300-mana character; sprint: the slowest walk leg read 0.52 against 0.62 units per frame | check | heat sets the full bar; sprint repeats a walk leg that does not give the expected ratio |

Final runs (same code, the two check edits for heat and sprint re-run on both slots afterwards): slot 1 (level 150) 106 PASS / 0 FAIL, slot 3 (level 34) 108 PASS / 0 FAIL of 111 rows each; the other rows are the standing REVIEW (short aliases, tooltip: screenshots to read by hand) and PARTIAL (map reveal: the level is already drawn whole on arrival) rows. Run folders `checks-20261023-062317-s1`, `-064559-s1`, `-071122-s1` and `checks-20261023-062317-s3`, `-064419-s3`, `-070748-s3`.

### Stash pages: personal page 2 (lane stash-pages, 2026-10-23, slot 3, background mode, plugin of this branch)

Throwaway character `StashPg` (`MXL_CHAR=StashPg`), saves backed up before each step; design in `docs/stash-pages.md`.

| Step | Result |
|---|---|
| `game_checks --slot 3 all stashpage2 stashpages` (final DLL) | `stashpages` PASS (shared tabs 0-9 accept an item, 10 and 12 refuse); `stashpage2` PASS (2 items on page 2, the stock stash has the "1 / 2" strip, right arrow opens the page 2 panel, the arrow on page 2 returns to the stock stash, an item moves 2 -> 1 -> 2, clean-up). Engine `BC_ASSERT` lines in d2rloader.log also appear in other lanes' runs (startup / shutdown) |
| Persistence | page 2 filled with 1x1 runes (392 items), Save and Exit, reloaded: 392 present, nothing lost |
| Load without the provider | `mxl-core-off.txt` = `stashpages` with items on page 6: the load stops with D2RCore's two ERROR lines, the `.d2s` hash is unchanged afterwards |
| Strip with the part off | `stashpages` off: the stock stash opens without the "1 / 2" strip (screenshot checked) |
| X / Esc / arrows | switching 1 -> 2 -> 1, X on either panel closes the stash, Esc on page 2 returns to page 1: as designed |

Not tested: TCP/IP with two clients (page replication is D2RLoader's); personal pages 3-10 and Sort are not built (`docs/unported.md`).

### No durability in the UI (lane no-durability, 2026-10-23, slot 2, background mode, plugin 0.55.0 + durabilitytip / repairui)

`py -3 tools/game_checks.py --slot 2 all nodurabilityui nodurability itemrolls vendors potions`: the new check and the four checks
that touch what it changes. Control run: `mxl-core-off.txt` with `durabilitytip repairui` (the tbl2json ethereal text is data and stays).

| Check | With the parts | Off words | Evidence |
|---|---|---|---|
| `nodurabilityui` (audit IT1, UI half) | PASS | FAIL | stats 72 / 73 > 0 on a Field Plate, a Battle Sword, a magic and an ethereal Field Plate; their descriptions (`itemdesc`, D2R's own builder) have no durability / repair / indestructible text; the ethereal one reads `Ethereal`, not `Ethereal (Cannot be Repaired)`; Charsi's menu ids are 0xd35, 0xd44 (no 0xd06), Gheed's 0xd35, 0xd44, 0xd46; the panel strip below the item grid, Charsi vs Gheed, differs by 0.12 (off words: `Durability: 48 of 48`, 0xd06 in Charsi's menu, strip diff 5.97) |
| `nodurability`, `itemrolls` (ethereal keeps +25% and the 75% durability), `vendors`, `potions` (2 rows) | PASS | | unchanged behaviour |

Screenshots (run folder `checks-20261023-093545-s2`): `nodur_tooltip_armour.png` and `nodur_tooltip_weapon.png` (the inventory
tooltip of a Field Plate: Defense, Required Strength, Socketed, no Durability line), `nodur_charsi_menu.png` and `nodur_charsi_panel.png`
(the plain trade panel, no Repair buttons), `nodur_gheed_menu.png` / `nodur_gheed_panel.png` for comparison.

### Buff / debuff icon bar (lane buff-icons, 2026-10-23, slot 3, background mode, plugin 0.55.0 + the lane's part)

`MXL_RUN=lane-bufficons py -3 tools/game_checks.py all bufficons --slot 3` (evidence `checks-20261023-093022-s3`, 0 new crash files, 0 cursor changes, foreground changed 0 times).

| Check | Result |
|---|---|
| `bufficons` | **PASS** (counters): states 32, 101, 26 in the left group and 89, 19 in the right group, slots 0..n-1 in table order; first icon at x = 460, y = 780, 32 px (1600 x 900); timers {32: 597, 101: 598, 26: 598, 89: 598, 19: 598} s -> {592, 592, 592, 593, 593} after 5 s; hover on state 32 (`medianxl:SkillnameMaenadFrenzy`): 1 tooltip line; 0 refused overlay requests, 2702 rectangles per frame; the icons go when the states are cleared; all five states reached the client through D2R's own packets (no `cstate` needed) |

**Not seen on screen.** The loader's overlay is not part of the PrintWindow capture of a background window (the dungeon lockout timer had the
same result), so the screenshots `bufficons_bar.png`, `bufficons_probe.png` and `bufficons_hover.png` in the run folder
(`%USERPROFILE%\mxl-d2r-runs\checks-20261023-093022-s3\`) show the HUD without the bar; the magenta probe rectangle, whose overlay calls all return
Success, is not in the picture either. The check therefore asserts counters only. **By hand** (normal window, foreground): enter a game, press `~` for
the console, `mxl` should say `buff icons on`; cast a self buff or run `h setstate player 32 1`; the icon bar sits just above the belt next to the orbs
(left group beside the health orb, curses on the right), a countdown under each icon, a tooltip box when the cursor is on an icon. Tell me: the
placement at your resolution, whether the art and tints look like Median's, and the frame rate in a fight with many states.

### Town rules, charms, area levels, D2 bugfixes, minimized window (lane p4-verify-b, 2026-10-23, slots 1 and 3, background mode, plugin 0.56.0)

`py -3 tools/game_checks.py --slot N all cain scrollportals towncast npcheal tplock charmlimit arealevel bugfixes`, run folder `%USERPROFILE%\mxl-d2r-runs\checks-20261023-195127-s1` (slot 1). Two earlier runs (`checks-20261023-194007-s1`, `checks-20261023-194334-s3`) aborted in `scrollportals` on the focus watchdog until the minimized-window give-back below worked. Control run with `mxl-core-off.txt` = `npcheal tplock` (slot 3): `checks-20261023-200935-s3`.

| Check | Result |
|---|---|
| `cain` (bug #23) | **PASS**: `menu list` has the 3 lines of Cain's popup, no `menu record is full` log line. The picture of the popup is `cain_menu_page.png` of `checks-20261023-190644-s1` (check `cainsub`): TALK / CRAFTING MATERIALS / CANCEL, read by eye |
| `scrollportals` (#17) | **PASS** with the window minimized: the check minimizes the window (`SW_SHOWMINNOACTIVE`) before its first screenshot and `game_ctl.restore_noactivate` brings it back with `SW_SHOWNOACTIVATE` and sends it to the bottom of the z-order. D2R activates its own window about a second after it is restored. The foreground goes back to the window that had it (`game_ctl.RESTORES`, log line `focus handed back`). A plain `SetForegroundWindow` is refused for this process (returns 0), so the give-back attaches the thread's input queue to the two windows' threads for the call (no input is sent), and the watchdog of game_checks lets those milliseconds pass (`FG_GRACE_UNTIL`). The old BLOCKED "game window minimized or has no size" is gone |
| `towncast` (SK4) | **PASS**: 3 class-free InTown skills start in the Rogue Encampment, 12 skills without InTown are refused there (the unit stays in its town-neutral mode 5; the usability code `0x33f360` does not look at the town) and all 12 start in the Blood Moor. The 8 other InTown skills are Warlock skills (`usable=3` for the test character), not judged |
| `npcheal` (NPC1) | **PASS**: 42 of the 43 NPC classes heal on talk (251 could not be spawned). Control (word `npcheal` off): 6 heal, 37 do not |
| `tplock` (UQ5) | **PASS**: levels 61, 73, 171 refuse (refusals 0 -> 3), the Blood Moor opens a portal. Control (word `tplock` off): level 61 opens a portal |
| `charmlimit` (IC5) | **PASS**: carry1 unique 106 and the limited uniques 7, 8, 9: the second copy is refused; unique 1773 without a rule takes two (unique 82 now refuses a second copy too, also with the part off; not analysed further, see docs/d2r-addresses.md section 22b). Lane carry1-fix (0.66.0) adds: uniques 7, 8, 9 (three different carry1 uniques) are all placed with `item inv`, a second copy of unique 7 is refused with `item inv` and with a ground pickup (packet 0x16, to-inventory flag), unique 8 picked up from the ground next to the carried 7 lands, unique 106 (only D2R's own rule) is placed next to unique 7 and its second copy refused. Runs: `checks-20261025-175642-s1` (fix on: `mxl`, `charmlimit`, `uniquelimits` all PASS), control `checks-20261025-175526-s1` (`MXL_CONTROL=uniquecarry`): the control places only the first and refuses the different ones on both paths |
| `arealevel` (MU3, data part) | **PASS**: monster levels of areas 216, 205, 204, 137, 3 in Normal and Hell equal levels.txt MonLvlEx |
| `bugfixes` (OT4) | **PASS** in the control run (in the first run my own assertion failed: the max resist caps every value from 75 up at the same damage): life / mana 60000 hold, resist 286 / 300 / 1000 / 65586 / 2^31-1 give the damage of 255, hits of 1e9 / 1.5e9 / 2^31-1 take exactly that much, death in the wolf / bear / might states leaves no state, alive after the respawn |

TCP/IP with two clients (slots 1 + 3, background input, LAN-only unlisted host): the session runs and both clients show the stash pages ready, but the harness cannot run stash verbs on the joiner (game-thread runner refuses), so the shared stash row stays `verify` (docs/unported.md "Shared stash in TCP/IP"). Not tested: the str / dex glitch and whirlwind chance-to-cast (OT4).
### Release suite on main (eccc3ad): slot 1 cluster, uniquelimits, engine asserts (lane suite-regressions, 2026-10-23, slots 1 and 2, background mode)

**The slot 1 cluster was the character, not the code.** The 13:45 run had Akara / Cain / Tyrael menus not opening, every harness cast doing nothing, zombie clicks
not hurting, and Griswold's Heart missing, on slot 1 only; both slots had the same plugin and data (hashes equal, same `d2rloader.toml` and off words).
`h state` showed `item id=62 code=143` in the player's state line: **an item held on the cursor** (a unique charm, left by an earlier `uniquelimits` run and
saved in the character). The engine's busy test (`0x4249f0`, nonzero with an item on the cursor or a trade open) refuses every skill use and every NPC
menu while the cursor is full, which is the whole cluster (the casts printed OK because the harness only calls the cast function). Dropping the item
(client packet 0x17 + item id) cured all of it; the check list then passed on slot 1 (65 PASS of 67). The character was backed up first
(`mxl-d2r-runs\save-backup-20261023-144201-s1`); no other character was touched.

`game_checks` now refuses and repairs that state (`clean_start_state`): before the first check and again before every check it revives a dead
character, ends the shapeshift states (140, 236, 278, 300), and drops an item held on the cursor (`release_held_item`, 3 tries, raises when the item stays);
a character that **started** dead / shapeshifted / holding something gets a REVIEW row ("Start state before the first check"), one left in that
state by the check before gets a REVIEW row naming that check, and a state that cannot be repaired gives BLOCKED rows instead of a wall of FAILs.

**uniquelimits "second copy of a single-copy unique should be refused (refused 2 -> 2, in pack 1)" was the check.** The ground-pickup part dropped the
first copy and then removed *its own carried copy* (`remove <code> 1` takes the first item of that code anywhere), so the second pickup found an empty
pack and nothing was there to refuse. The check now leaves the carried copy alone (a far drop stays; `reset()` clears leftovers), and reads back `iflags` of
the picked-up item (mode 3 or 5) and the pack count instead of the counter alone. The plugin rule was fine: the check passes on slot 2 after the change (`refused` moves on the second copy).

**Engine asserts** (`d2rloader.log`; "Continuing because assertion dialogs are disabled"; found by time stamp against the `hcmd` lines of the run log,
each one then reproduced alone with a probe where noted):

| Assert | Trigger (check / action) | Cause | Status |
|---|---|---|---|
| `nDesc >= 0 && nDesc < skillDescTbl.size()`, then `false` | tooltips of an item whose property names skill 2001 / 2004 / 669 / 2073 / 2076 / 741 (`tooltiptext`); a cast of skill 36 (Fire Bolt) or 126 (Bash) by `casts` | those skills have no `skilldesc` row in Median; the client reads the row of a skill when it is cast or named | **fixed** for the 8 skills: `txt_migrate.py blank_skilldesc` gives them a `blank` row (no name, Median's own shape of `avoid`); the other 1049 skills with ItemEffect 1 and no skilldesc assert once per cast in the same way (not changed: a row each changes the skill menus' lists) |
| `nMissile >= 0 && nMissile < NumMissileStats` (x2) | `kill` of class 2054 (unformed phantasm, the Summoner check), `monlevel` | Median's curse skills have `cltdofunc 30` but no `cltmissilea` / `cltmissilec` (52 of the 75 curse rows; vanilla Amplify Damage has `curseamplifydamage` / `cursecast`), D2R's curse client function (0x2b05d0) reads both | **fixed** (p4-engine-b): `sigma_skills.cpp CltDoCurse` wraps the slot in place; a row without a client missile draws nothing (as D2Sigma's function does: Median's look is the state overlay) and returns 1, a row with one runs D2R's function. Check `cursemissile` (run `checks-20261023-182147-s1`): 0 asserts through all 52 bare rows, control (harness `cltdo <skill> orig`) asserts once with the chain `2b0670` ... |
| `nMissile >= 0 && nMissile < NumMissileStats` (x2, second source) | the kill of class 2054 on 0.63.0 (`checks-20261024-105541-s1`), and the spawn of the treasure goblin (class 2791, `leash`, `charmlimit`, `medianai`) | **not a curse and not the Summoner:** `asserttrace` (run `checks-20261024-141208-s3`) gave the chain `2b0e86 21854e 341740 217759 1a56e7` (the trace label `skill 2583 class 2791` is only the harness' last cast skill): the client skill start function `0x218030` calls the start table slot of a skill (`0x235f590`, slot 18 = `0x2b0df0`, which draws the skill's `cltmissilec`); 52 Median rows with cltstfunc 18 have no client missile, so the function reads `cltmissilec` = -1 and asserts twice per start, then returns 1 (the Summoner kill only had a goblin spawned in the same game) | **fixed** (p4-stability, plugin 0.64.0): `sigma_skills.cpp CltStMissileC` wraps slot 18 in place, a row without a client missile draws nothing (Median's look, no D2R visual) and returns 1 as D2R's function does, a row with one runs D2R's function; the `mxl` line says `cltstfunc 18 start without client missile`. Check `asserttrace` calls the slot for skill 66 (D2R's own function asserts, the table entry does not) and fails when the treasure goblin spawn raises an nMissile assert (run `checks-20261024-195658-s3`: PASS, no assert) |
| `nRadius > 0` | spawn of class 2791 (treasure goblin; `goblins`, `medianai`) | the goblin's skill is `skills_2511` (srvdofunc 65, a monster property aura: dmg% = aura), not 2580 as first written. D2R's area applier of the aura functions (0x4327d0 -> 0x4398b0) asserts when `aurarangecalc` (skill +0x84) gives 0; Median leaves it blank on its self-only auras, D2Sigma applies the state to the caster and then to nobody. The assert fired every aura tick (about 400 ms per monster) | **fixed** (p4-engine-b): `sigma_skills.cpp AreaAuraHook` skips the call for a radius below 1 (the applier does nothing for it anyway), the state on the caster stays. Evidence: harness `asserttrace` probe, run `checks-20261023-190745-s3` (treasure goblin spawn: no assert) |
| `nSkillCastId && nSkillCastId != 0xFFFFFFFF` | `medianai` / `medianai_ctl` (andariel_ai users 1693 Maghda, 1899) after a hit; also the pulse of skill 2583 | traced to the client `FUN_140216920` (0x216920): at each aura pulse it looks up the caster's aura-state stat list (state of skill +0xa0) and reads stats 0x15e / 0x15f / 0xca; when the caster has no list for that state it gets cast id -1 / 0 and the engine asserts. Data-driven noise of the aura states Median defines without the stat triple D2R keeps; no wrong behaviour | **traced, not fixed**: log noise only; a fix would have to add the stat list that D2R's own aura skills get, which changes the stat lists of Median's states |
| `nDirectionIndex < nDirections`, `MONFLAG_ENABLED` | `medianai` spawning every andariel_ai user (class 990; class 971 after the not spawnable 333); tagged to skill 2583 / classes 2798, 2791 in the server `MissMode.cpp` | the check spawns disabled / odd monstats rows; the missile-mode assert is a direction count of a missile with no directions on those classes; not reproduced by a plain spawn and not traced further | harness artifact / open |
| `i != warpDefs.end()`, `BC_VERIFY: ptWarp`, `BC_ASSERT: 0` | `cheat goto 16` (Median's level 16 has no Vis / Warp rows, vanilla has Warp1 4 / Vis1 12), goto 191 / 250 / area 134 (`areacycle`, `automap`, `mapmem`) | Median-only levels entered by `goto`: the DS1 warp tile of the level looks up a warp id that Median's `levels.txt` row does not carry (16, 134, 191, 250). Not a port defect: a real walk never gets there, only `goto` into the DS1 of such a level (control: `asserttrace` probe, same levels, `warprevisit`) | **explained**, harness-only (`goto`); no change |
| `nParamIndex < 8` | `enter` into a class 600 portal of a Median dungeon (`lockout`, `scrollportals`, area 251 / 253) | the portal's level parameter; not reproduced in this lane (the earlier lead, andariel_ai Maghda 1693 / class 1899, is the `nSkillCastId` family) | open, not reproduced |
| `wPrefix != 0 \|\| wSuffix != 0` | harness `item <code> q=4` / `q=6` (`tooltiptext`, `trophy`) | the harness builds magic / rare items without affixes | harness artifact |
| `activeUnit` | start of `assetpaths` | not traced | open |
| `nDesc >= 0 && nDesc < skillDescTbl.size()`, then `false` (same pair as the first row) | `enginegaps`: `cast 463 self` (drakemaw, a monster skill, to prove the recast guard) | skill 463 has no `skilldesc` row; the client reads the row of a cast skill. A harness cast of a monster skill, not reachable by play | harness artifact, new trigger (suite-main-060, plugin 0.63.0) |
| `nStat >= 0 && nStat < statsTbl.size()` (`CmdAccess.h:1609`) | `signet`: the refused use of a Signet of Learning at the 400 cap (`use 01^` with stat 370 = 400, "the game refuses to use it") | the refusal path of the Median signet use reads a stat id outside D2R's stats table; the use is refused as wanted and nothing else is lost | open, new (suite-main-060), harmless so far |
| `input->IsValid()` (Domino `world.cpp:3251`, `dynamic_tree.h:257`) | `scrollportals`: `enter` into the class 600 portal of a summoning scroll level above 255 (seen once in two 0.63.0 runs, with the `nParamIndex < 8` family) | physics world of the client given an invalid body while the level changes | open, new (suite-main-060) |
| `BC_ASSERT: 0`, `ii < NUM_LEVEL_TYPES`, `sub.nCelNum`, `eLevelId > 0`, 2 x `statesTbl` | once per launch, on the way into the game | D2R reading Median's tables (states, level types) | open, constant |
| `s_StatsPool.IsEmpty()`, `m_allocated == 0`, `m_freed == 0`, ... | when the game exits or restarts (keybinds, Save and Exit) | pool leak checks of the engine | exit-only, ignored |

Other check fixes of this lane: the window capture puts a minimized game window back with SW_SHOWNOACTIVATE (the scrollportals run was BLOCKED once by
a minimized window: "game window minimized or has no size"; focus is not taken), and `assetpaths` waits up to 10 s for the spawned Corrupted Wereowl
(in two long suite sessions it was not in the unit list 2.5 s after the cheat and the check failed on "did not spawn"; alone it passes, and with the wait it passed in the final run).

Final runs on the fixed build (`py -3 tools/game_checks.py all <group> --slot N`, `group1.txt` on slot 1, `group2.txt` on slot 2, in parallel; folders
`mxl-d2r-runs\checks-20261023-171353-s1` / `-s2`): slot 1 **65 PASS**, 1 REVIEW (short aliases), 1 BLOCKED (`classlock`: `ensure_merc` was refused by the server for all 6
list entries in one of three full runs; it passes alone and in the other two runs, and in the rerun of `classlock casts medianai_ctl` on a fresh game: 3 of 3
PASS, with no `nDesc` / `false` assert at the cast); slot 2 **48 PASS**, 1 REVIEW (mystic orb tooltips), 1 PARTIAL (map reveal: the level was already drawn
whole). The first full runs of the day (before the fixes) were slot 1 with the cursor item and slot 2 with `uniquelimits` FAIL.

## Lane p4-engine-a: engine rules (plugin 0.57.0)

New checks (`tools/game_checks.py`, in `group1.txt` / `group2.txt`): `teleportgold`, `skillafford`, `hcdeath`, `meleenotarget`, `reqlevel`, `cubedrop`;
`enginegaps` now also casts Howl of the Spirits twice (recast guard). Harness verbs: `afford <id>`, `hc [on|off]`, `tpgold`, `modewatch start|stop|read`,
`peek`; `req player` prints level / str / dex; `gaps` prints `reqlevel_sites=`.

Control runs: `MXL_CONTROL="teleportgold afford reqlevel recast"` makes `game_ctl.harness_switch` write those words into `mxl-core-off.txt` for the launch;
the checks read the same variable and expect the old behaviour for their own word (`hcdeath` is controlled in a run of its own, because the control leaves a
Hardcore character dead and its saves are restored afterwards). Do not run `hcdeath` with `hc on` followed by Save and Exit and Play: the character is then a
dead Hardcore one that cannot join a game.

When saves are touched from a shell, always pass `--slot N` / `MXL_SLOT=N`: without it the default is slot 1's save folder.

Runs of the lane on plugin 0.57.0 (slot 2): `mxl-d2r-runs/checks-20261023-211144-s2` (normal: mxl, enginegaps, teleportgold, skillafford, meleenotarget, reqlevel, cubedrop: 7 PASS),
`checks-20261023-211416-s2` (control `teleportgold afford reqlevel recast`: 4 PASS with the old behaviour), `checks-20261023-210132-s2` (hcdeath) and
`checks-20261023-210509-s2` (control `hcdeath`). The two hcdeath runs are from the build before the last `afford`-verb fix (the Hardcore code is unchanged by it).

## Lane p4-leftovers (plugin 0.61.0): Soulstealer heal, drop item level reader, hire robustness

Slot procedure: `py -3 tools/game_slots.py lock 2 p4-leftovers`, `py -3 tools/install_mod.py --slot 2`, `MXL_RUN=p4-leftovers py -3 tools/game_checks.py --slot 2 all <checks>` (the run
releases the lock at its end, so the lock is taken again before each install).

| Item | Check | Result |
|---|---|---|
| Drop item level (audit IT16, DF10) | `dropilvl` (rewritten: reader test with `ilvl=` 1 / 33 / 77 / 100 / 150 / 255, then drops in areas 2 and 76 in Normal and Hell, with and without a town trip; item level must equal the area level and the monster level) | PASS, run `checks-20261023-221828-s2`. The old PARTIAL came from the harness's reader (`0x3730d0`, a field that stays 101); `0x36ccf0` reads the real level. Median's rule (area level) was already what D2R's `0x43e8a0` does, so no hook |
| Soulstealer (audit DC5) | `soulstealer` (new): a boss at 30% life kills the harness player (1 life point, so life leech cannot refill the boss), boss life must rise by 10% of max and the plugin counter by one; an ordinary monster must gain nothing | PASS, run `checks-20261023-221828-s2` (Zagraal +10.0%, Kabraxis +10.0%, control monster +0%); control with the part off (`mxl-core-off.txt`: `soulstealer`, or `MXL_CONTROL="soulstealer"`) PASS, run `checks-20261023-221613-s2` (bosses +0.0%). The Leoric (class 2907) refills to full life on its own before the death call, so it is left out of the check; the 40% heals are not ported (`docs/unported.md`) |
| `classlock` BLOCKED once ("no mercenary could be hired") | `classlock`, `hiregates`, `resistcap`, `avoidcaps` (all use `ensure_merc`) | PASS, run `checks-20261023-222736-s2`. The cause of the one refusal (run `checks-20261023-171353-s1`, all 6 list entries refused) was not reproduced; the hire verb now logs the NPC distance, the player mode, the gold and the current mercenary id, can remake the NPC's list (`reopen`, used by `ensure_merc` for every hire), and `ensure_merc` tries a hirer copy next to the character and another area before the next try |

## Lane p4-ww-morph (plugin 0.63.0): whirlwind chance-to-cast, real shapeshift death

Slot procedure: `py -3 tools/game_slots.py lock 3 p4-ww-morph`, `py -3 tools/install_mod.py --slot 3`, `MXL_RUN=p4-ww-morph py -3 tools/game_checks.py --slot 3 all <checks>` (the run
releases the lock at its end, so the lock is taken again before each install). `MXL_CONTROL=wwproc` makes the control run (off word written to `mxl-core-off.txt`).

| Item | Check | Result |
|---|---|---|
| Wrong skill ids in lane p4-quests-verify (1234 / 1303) | none (`strdex`, `bugfixes` docstrings) | Not a lookup bug: 1234 / 1303 are the `*Id` values of Median's original `skills.txt` (Whirlwind, Werebear Morph); the build renumbers those rows by +72, so the built ids are Barbarian `whirlwind_2` 1306, Druid `werebear_morph` 1375, `werewolf_form` 1380, `wereowl_form` 1364. `_skill_ids_by_name()` reads the built table and is right. |
| Whirlwind chance-to-cast (audit OT4) | `wwproc` (new): Barbarian `MxlBarb`, ring `stat 198` / `stat 195` = Fire Bolt level 5, 100 %; 4 spins of 1306 through 5 monsters vs 8 normal attacks, Fire Bolt missiles (class 58) counted; `mxl` line and counter checked | PASS, run `checks-20261024-012847-s3` (11 / 13 Fire Bolts in the spins, 4 / 6 from the attacks; 24 casts let through, 0 refused). Control `wwproc` off, run `checks-20261024-013722-s3`: line `off`, spins 0, attacks 5 / 6. Cause: D2R's `0x5896e0` refuses the cast while the caster has state 54 and a spin holds it; the plugin clears the bit around the cast when state 174 is on. |
| Real shapeshift immortality (audit OT4) | `morphdeath` (new): Druid `MxlDru` (created in the slot when missing), real `cast <id> self` of the three Median morph skills (weapon of type axe / sword / knife in hand, outside town), lethal hit, and Andariel as killer of the bear | PASS, run `checks-20261024-012847-s3`: death (mode 0 then 17), form state ends, Esc respawn gives a living character in area 1 without the form, for all three forms and the monster kill. D2R's code, nothing ported. |

## Lane suite-main-060: full suite on main (plugin 0.63.0)

Test-only lane. Runs on plugin 0.60.0 (slot 1 `checks-20261023-220521-s1` and `checks-20261023-224514-s1`), 0.61.0 (`checks-20261024-002546-s1/-s2`) and, as asked by the coordinator after #153 / #154,
on **0.63.0** (c2d85b0) with `group1.txt` on slot 1 and `group2.txt` on slot 2 in parallel. The run `checks-20261024-000518-s1` is void from about 00:11 (lane p4-ww-morph ran commands on slot 1 without `MXL_SLOT`). **Final pair on 0.63.0: `checks-20261024-120836-s1` PASS 82, FAIL 0, BLOCKED 0, PARTIAL 0, REVIEW 5; `checks-20261024-120837-s2` PASS 67, FAIL 0, BLOCKED 1 (`mapreveal`, by design after debug mode), PARTIAL 1 (`meleenotarget`), REVIEW 11** (the REVIEW rows are the start-state notes and two screenshot checks).

Fixes of the checks (all in `tools/game_checks.py`, no plugin change):

| Check | Problem | Fix |
|---|---|---|
| start state of every check | the inventory panel left open by a check covers the right half of the client: `monhover` and `levelcap` failed on projected clicks, `statorder` crashed the game (access violation and `m_listWidget` assert) | `clean_start_state` closes the panel (`i`, then Esc) and says so as a REVIEW row; it also notes when the worn items changed since the check before |
| `collidetypes` | the nearest unit was Deckard Cain (unkillable) or the monster moved | uses the spawned monster by id, 14 tries per type |
| `bugfixes` | `hit player` without an attacker is a hit of the player on the player (ignored) | spawns an attacker; saves and restores the pools; the bounds only exclude a rollover (the mana of a long session may start a regen apart) |
| `teleportgold` | the purse-full case hard-coded 160000 gold (a level 16 character); a stray pile of an earlier check was taken too | the cap is 10000 x level (D2R's gold limit, `0x34b320`); strays are tolerated |
| `meleenotarget` | mana regenerates at 8191 pools: the cost hid in the sample | starts from the maximum, waits 3 s after each click, takes every worn item off |
| `tplock` | one run: the first cast was refused by the verb (character still busy), refusal counter 2 instead of 3 | the cast is repeated once; diagnostics (usable code) in the log |
| `npcheal` | life 8190/8191 after the heal counted as "not healed" (and a talk that does not start) | full life within 1 %, one retry with a fresh NPC |
| `strdex` | needs the armor's level (a level 19 character): the stats stayed inactive; the rare ring has random affixes | sets the level 90 for the check; the ring may add resistance |
| `mapreveal` | FAIL when the level is already drawn whole on arrival; left the character in Lut Gholein (`skillafford` then read the column value, formula cost 256) | PARTIAL for that case; goes back to Act 1; `skillafford` starts in a field level |
| `morphdeath` | Andariel hit a level 2 bear for ~16 and stopped; Save and Exit took longer than 9 s after a long session | life 12 for the monster kill; `switch_character` waits up to 42 s |
| start state of every check (stances) | a Way of the Phoenix / Spider / Gryphon / Raven cast of an earlier check stays on the character: Phoenix adds fire damage, mastery and max mana (`meleenotarget`, `bugfixes`, `skillscaling` failed in the full `group2.txt`) | `clear_stance_states()` takes states 308 / 309 / 332 / 783 off and notes it. State 105 (alignment) is left alone: the test character carries it from the start and with it off the casts of `replacedskills` did not start and the 2e9 hit of `playerdeath` did not land (run `checks-20261024-085517-s2`) |
| `hitfloor` | the missile's damage at skill level 0 is the character's flat damage: the earlier runs had it from a Phoenix left on by another check; with the stance taken off (or in a fresh game) all five level 0 shots did nothing | sets flat damage (stats 21 / 22, 48 / 49, 50 / 51) for the shots and puts the values back |
| `mercrevive` | `kill nearest` killed a leftover class 2796 next to the mercenary, the mercenary stayed at 1 life | kills the mercenary by its unit id |
| `meleenotarget` (pool) | in the full `group2.txt` the pool falls by itself (idle dip 740-864 points in 1.2 s, no click), which hides the cost of a click; the usable code was read at a low pool (code 1 = not enough mana) | mana to the maximum before the usable code; an idle baseline: with an idle dip above 100 points the mana judgement is dropped and the status is PARTIAL (the attack modes are still judged) |
| `assetpaths` | the cheat line `mspawn corrupted_wereowl` is lost now and then (none in 11 s) | the cheat is sent once more |

Not regressions (start state, the check or the order of the group): `tplock` (one FAIL on 0.61.0, passed in later runs), `itemevents` (thorns 686816 vs 687200 once, passed alone), `statorder` (panel), `bugfixes` / `strdex` /
`skillafford` / `mapreveal` / `hitfloor` / `mercrevive` (order or start state, see the table), `npcheal` and `soulstealer` (a different NPC class or the boss 2049 fails in some runs, never the same set; 2049 fails with "heals counter 0 -> 0" while 1852 heals 10 %;
`npcheal` passed in the last pair).

Open, not fixed (the lane is test-only):

- **(solved by lane p4-stability: the `heat` check left Molten Core's stat 297 on the character, see "Lane p4-stability")** **The mana pool of the test character falls by itself in the full `group2.txt` on slot 2** (idle dip 740-864 points in 1.2 s, `meleenotarget` PARTIAL; in the earlier pair the plain click "paid" about 1540 mana and `bugfixes` read 58575 mana). `meleenotarget` passes alone and after `uniquelimits charmlimit arealevel bugfixes`; the stance states, the worn items and the player states (only 105) are not the cause, so some check in the middle of the group leaves something else (a stat list, a monster that drains) - not bisected.
- **(analysed by lane p4-stability: D2R's own, docs/bugs.md #34)** **An engine crash at the end of `group1.txt` on slot 1** (`checks-20261024-105541-s1`: `d2r-lastresort-crash-report (2026_10_24 01_55_42 UTC pid-31948).log`, access violation at `D2R.exe+0x7761DC`, generated 11:56:27 during `morphdeath`'s character switch to the Druid; the stack slots hold the string `data/hd/chicken/chicken_state_machine.js`, i.e. the game was loading an HD asset). The run ended without a `morphdeath` row; `wwproc morphdeath` alone (`checks-20261024-115748-s1`) and the full `group1.txt` again (`checks-20261024-120836-s1`) pass. One crash in three runs, not reproduced, not traced to a commit.
- Asserts (the `nMissile` one is fixed in plugin 0.64.0, see the table row for the start function): every assert of the final runs is a row of the table above. `nMissile >= 0 && nMissile < NumMissileStats` still fires once at the Summoner kill (class 2054) on 0.63.0 (`checks-20261024-105541-s1`, 11:08:52) although the table row says fixed by `cursemissile` (`cursemissile` itself has 0 asserts); the fix covers the curse client function, not whatever the kill of class 2054 reaches. `activeUnit` was not seen in these runs.
- `morphdeath` was BLOCKED inside the full `group1.txt` in the first runs of the lane (cut scene after `tyraelwalk` swallowing Esc and Save and Exit); `switch_character` now skips the cut scene and retries, and it passed in the last two full runs.

## Lane p4-stability: engine crash, nMissile assert, flaky checks (plugin 0.64.0)

Slots 1, 2 and 3, background mode. Plugin 0.64.0 = 0.63.0 + `sigma_skills.cpp CltStMissileC` + `translation_guard.cpp`; the harness gained `cltst` and `transguard`;
everything else is `tools/game_checks.py` and the docs. `tools/build.py` does not build the plugin (cmake does: `cmake -S plugin -B build\plugin -A x64`, `cmake --build build\plugin --config Release`);
a run of this lane that used an installed DLL older than the source was thrown away, every number below is from the 0.64.0 DLL (the `mxl` line of each run says `mxl-core 0.64.0`).

**1. Engine crash at `D2R.exe+0x7761DC` (`checks-20261024-105541-s1`, again `checks-20261024-183807-s1`).** The function is the handler of event type 0x10 of D2R's `UnitTranslationLayer`
event loop (`0x775fc0`); it reads `[[*event+0x70]+0x870]`, and the payload pointer was `0x8000003F0` (first crash) and `0x46B000003FD` (second): two small integers glued into a qword, i.e. memory that D2R reused
after the event was queued. No plugin code is in the frame; the details are in `docs/bugs.md` #34. It came back in 2 of about 7 full `group1.txt` runs (at the Druid switch of `morphdeath` or just after it), so it
cannot be left in the suite: `translation_guard.cpp` hooks `0x775fc0` and skips an event whose pointer chain is not readable (`VirtualQuery`), otherwise D2R's handler runs unchanged. Off word `transguard`, `mxl` line
`translation guard on (N events, M skipped)`, harness `transguard [probe]`, check `transguard` (PASS in `checks-20261024-195240-s3`: the probe event is skipped, the counters move). `morphstress` (env `MXL_STRESS_CYCLES`)
casts the three forms 30 times each per cycle with a character switch between the cycles: PASS 12 and 9 cycles (`checks-20261024-134134-s3`, `-143419-s3`), no crash: the crash is not triggered by the casts. In the four final runs
below `morphdeath` switched to the Druid in both group1 runs without a crash file. **What is not shown:** the guard skipped no real event in those runs, so it is proven only by the synthetic probe; if the crash comes back with the guard on, the
`mxl-core.log` has the three pointers (up to 8 warnings) and the next step is to find who queues the event.

**2. `nMissile >= 0 && nMissile < NumMissileStats`.** Not the Summoner kill and not a curse. `asserttrace` (`checks-20261024-141208-s3`, plugin 0.63.0) gave the chain `2b0e86 21854e 341740 217759 1a56e7` while the
treasure goblin (class 2791) was in the game: the client's skill start function `0x218030` calls slot 18 of the start table (`0x235f590`, `0x2b0df0`), which reads `cltmissilec` (-1) and asserts twice (it then returns 1). 52 Median
rows (curses such as Amplify Damage 66, Terror 77, Lower Resist 91 and many monster skills) have cltstfunc 18 and no `cltmissilec`. Median has no client missile for them and no D2R visual is wanted, so `CltStMissileC` wraps the slot in
place (like `CltDoCurse` for the curses): a row without a client missile returns 1 silently, a row with one runs D2R's function. `mxl` line `cltstfunc 18 start without client missile`; off word `skills`.
Check `asserttrace` now has control 2: harness `cltst 66 orig` (D2R's own function, past the wrapper) raises the assert and `cltst 66` (the table entry) raises none and returns 1; it also FAILs when the treasure goblin spawn raises an
nMissile assert. PASS in `checks-20261024-195658-s3`: control 1 assert, table 0, `treasure goblin spawn: no assert`; also PASS in both group2 runs below. (The trace label "skill 2583" of the old run is the harness' last cast skill, not the
asserting skill, and 2583's own cltstfunc is 0: the first version of the control used it and found an empty slot, so the control uses 66.)

**3. Flaky checks: the mana drain was the `heat` check.** The instrumented `group2.txt` run (`checks-20261024-134106-s2`; `clean_start_state` now measures the idle mana dip and names states, stat 297,
monsters and worn items) shows the first dip note (908 points in 1.2 s) at the start of `mapreveal`, the check after `heat`, and none before. `heat` casts Molten Core (1682, a passive, `stat 297` =
the heat loss rate) on the character for a Sorceress and restored only the class: the harness' `setskill <id> 0` only writes the base level, the passive stat 297 stays until the next recalculation, and
plugin/src/heat.cpp then drains the mana of a Barbarian (740-864 points in 1.2 s) in every later field check. Fixes: `heat` reads the levels of 482 / 1682 first, puts them back and clears what is left of stat 297
(`clear_heat_stat()`: stat set to 0, the remainder cancelled by a negative value); the start state clears a stat 297 above 0 on a character that is not a Sorceress and says so. `npcheal`, `soulstealer` and `meleenotarget` PASS in every
final run below. The old `townmana` PASS had counted that drain as the cost of the field cast ("cost 1008"); the real cost of skill 1558 at level 5 is 2-7 points, the field leg now needs a fall of at least 1 (the town leg stays exact: no fall).

Other flakes found in the repeated full runs and fixed in the checks: `npcheal` (hostile zombies of the Blood Moor at 2-3 yards kept the character in hit recovery, class 177 never opened its menu, and Tyrael 251 was
"not alive" for the interact: the field is cleared before every try, one more try after a `no heal` / `interact failed`); `hcdeath` (the client word `client+0x5658` of a freshly joined game holds garbage, e.g.
`0x5f8ae86f`, `0xe83d1d8d`, so its 0x800 bit read "Hardcore" in two of three full `group1.txt` runs: `_hc_hard()` judges by the character's info word and the save, the client word only when it looks like flags);
`skillscaling` (a random amulet that `skillstarts` leaves worn carried +6 lightning mastery: the check takes the worn items off); `soulstealer` (the player died before the hit once: the trial repeats up to three times
and names the last killer); `cainsub` (the plugin message that rebuilds Cain's list arrived after the 2.5 s the check waited, once: it waits up to 12 s and clicks a second time) and `leave_and_reenter` (a Save and Exit
click the game did not take failed `levelcap` once: three tries, the last with a new Esc).

**4. Final runs** (plugin 0.64.0, `group1.txt` on slot 1 and `group2.txt` on slot 2 in parallel; an earlier pair that ran `game_checks.py all` without the group list because of a wrapper mistake is not counted):

| Run | Result |
|---|---|
| `checks-20261024-221246-s1` (group1) | PASS 78, FAIL 2 (`cainsub`, `levelcap`: UI flakes, both PASS alone and in the next run; the checks were hardened afterwards), REVIEW 5; 0 crash files |
| `checks-20261024-231804-s1` (group1) | PASS 81, FAIL 0, BLOCKED 0, PARTIAL 0, REVIEW 5; 0 crash files; `morphdeath` PASS |
| `checks-20261024-221246-s2` (group2) | PASS 67, FAIL 0, BLOCKED 1 (`mapreveal`, by design after debug mode), PARTIAL 0, REVIEW 10; 0 crash files |
| `checks-20261024-231804-s2` (group2) | PASS 67, FAIL 0, BLOCKED 1 (`mapreveal`), PARTIAL 0, REVIEW 10; 0 crash files |

The hardened `cainsub` / `levelcap` were run once alone after the change (`checks-20261025-002747-s3`: PASS both); group1 was not run a third time on the final check code. The REVIEW rows are the start-state notes
(worn items changed, stance 309, inventory panel).

## Lane p4-soak: soak of the translation event guard (plugin 0.64.0, 2026-10-25)

Test only (plus fixes to `tools/game_checks.py`). Plugin 0.64.0 built from main 79bbf15 (`tools/build_plugin.ps1`, cmake from the Visual Studio install), data from `tools/build.py`, installed into slots 1-3 with
`install_mod.py --slot N`; the `mxl` check of every run reads `mxl-core 0.64.0` and `translation guard on: the unit translation event handler 0x775fc0 skips an event with an unreadable payload`.
Every full run is `py -3 tools/game_checks.py all $(cat group1.txt) --slot N` (or `group2.txt`), run folders `%USERPROFILE%\mxl-d2r-runs\checks-20261025-*` (not committed), three slots in parallel.
`run_all` now also reads `transguard` (no probe) before it stops the game and writes the counters into the report (`Translation event guard counters at the end of the run`, INFO): the groups never call the
probe, so every skipped event counted is a real one, and the three pointers of the first eight skips are in `mxl-core.log` (`translation event skipped: event ..., payload ..., payload+0x70 ...`).

| Run | List | Slot | Result | Crash files | Guard (events / real skips) |
|---|---|---|---|---|---|
| `checks-20261025-010224-s1` | group1 | 1 | PASS 81, FAIL 1 (`morphdeath`: Andariel did not kill the bear, see below), REVIEW 4 | 0 | 321 / 0 |
| `checks-20261025-010229-s2` | group1 | 2 | PASS 82, REVIEW 5 | 1 first-chance report at exit (below) | 314 / 0 |
| `checks-20261025-010235-s3` | group1 | 3 | PASS 82, REVIEW 5 | 1 first-chance report at exit | 299 / 0 |
| `checks-20261025-021629-s1` | group1 | 1 | PASS 80, FAIL 2 (`dropilvl`, `wwproc`), REVIEW 4 | 0 | 319 / 0 |
| `checks-20261025-021635-s2` | group1 | 2 | PASS 82, REVIEW 4 | 1 at exit | 319 / 0 |
| `checks-20261025-021640-s3` | group1 | 3 | PASS 81, FAIL 1 (`monhover`), REVIEW 4 | 1 at exit | 321 / **1** |
| `checks-20261025-032834-s2`, `-032839-s3` | group2 | 2, 3 | aborted after 13 / 14 checks (all PASS): the game died, `Present failed` (`DXGI_ERROR_DEVICE_REMOVED` 0x887A0005) in both processes in the same second (03:43:56), `d2r-crash-report` | 2 each (`.log` + `.dmp`) | not read |
| `checks-20261025-034503-s2`, `-034508-s3` | group2 | 2, 3 | aborted after 13 checks (all PASS): slot 2 `Present failed` again (04:02:17); slots 3 and 1 hung at the same moment (not responding, killed) | slot 2: 2 | not read |
| `checks-20261025-034025-s1` (killed) | group1 | 1 | hung at the same moment (04:02:30, check 29 of 88) | 0 | not read |

**The guard did skip a real event.** In `checks-20261025-021640-s3` the guard logged, at 03:17:25, during the character switch of `morphdeath` (`a cut scene plays: Esc held`, the Druid is loading):
`translation event skipped: event 00000001DD1AFCF8, payload 00000000a90f0d90, payload+0x70 0000000000002035 (not readable memory)`; the end-of-run counter says `events=321 skipped=1`. The payload pointer
read from the event (`+0x70`) is `0x2035`, a small integer and no pointer: the same kind of value as `0x8000003F0` and `0x46B000003FD` of the two crash reports, at the same place in the sequence. D2R would have read
`byte [0x2035 + 0x870]` there (the instruction of the crash at `D2R.exe+0x7761DC`). The run went on: the Druid loaded, `morphdeath` and all later checks PASS, no crash file besides the exit-time report below. The other five
complete group1 runs saw about 300 events each and no unreadable one. **Outcome (a): no crash at `D2R.exe+0x7761DC` in six full group1 runs with the guard on, and the guard skipped a real event at the point where the crash
happened before.** (One real skip in six runs; before the guard the crash came in 2 of about 7 runs.)

**Crash files that are not the crash.** The runs of slots 2 and 3 above each leave one `d2r-lastresort-crash-report (... pid-N).log` (reports with this address since 2026-10-22: 6 on slot 1, 17 on slot 2, 7 on slot 3):
`Record: 1 of at most 2`, a first-chance access violation at `Allocation Base 00007FFA3FFD0000 + 0x163644` (not `D2R.exe`), written within a second of the report `game_ctl.stop`, i.e. when the game exits
(`Generated` = the end of the run). It is a handled first-chance exception of a driver / system module at shutdown, not a death of the game: the run had finished and written its report. A real crash is the report whose
module is `D2R.exe` (`+0x7761DC` for bug #34) or a `d2r-crash-report` before the end of the run.

**The `Present failed` deaths and the hangs are the machine, not the mod.** `d2r-crash-report`: `D2Prism\src\D2Prism.cpp:2112 BC_ASSERT: result.Succeeded(), "Present failed"`, `systemCode 0x887A0005`
(`DXGI_ERROR_DEVICE_REMOVED`). Slots 2 and 3 died in the same second (03:43:56); at 04:02:17 slot 2 died again and the games of slots 1 and 3 hung. After that every new
D2R start of the session hung 10-20 s after the window opened (not responding, CPU idle; the main thread waits in `D2RLoader.exe+0x10e7d50` <- `dxgi.dll+0x62be4`, the window thread is in `win32u`): a DXGI wait that is
not answered, with `dwm.exe` showing 21 GB of GPU memory in the process counters and `Virtual Desktop Monitor` in status Error in `Win32_VideoController` (the PC has a remote-desktop / streaming host running). The single
start at 04:37 worked; the following ones (single or in parallel) did not, over more than an hour, so the group2 pair could not be finished in this session (see "Left").

**Flaky checks found in the full runs and fixed** (`tools/game_checks.py`; each passes alone):

- `morphdeath` (bear killed by Andariel, `checks-20261025-010224-s1`): Andariel's one hit took 7 of the 12 life left and no second hit came in 40 s. The life is put back to 1 point every second while she is at it and a second
  Andariel comes after 15 s.
- `monhover` (`checks-20261025-021640-s3`): `scrollportals` ran before it and left the Barbarian at **1 life point** (`life=1/8191` in the `state` before the zombie spawn); the zombie killed the character and the 24 clicks went to
  a corpse ("You have died" in `monster_fight.png`). `clean_start_state` now sets the life to full when it is under half of the maximum and says so in the row of the check (a REVIEW note).
- `wwproc` (`checks-20261025-021629-s1`): 3 of the 4 spins hurt a monster (the check wanted 4), the procs came anyway (6 Fire Bolts for 6 hits). The spins must hurt 2 monsters; the proof stays the Fire Bolts.
- `dropilvl` (`checks-20261025-021629-s1`): after the town trip in Hell, area 2, 7 drops of item level 1 were counted: they are items of the Normal visit that reach the client as new units a moment after the arrival (the
  area is the same game level), not drops of the kills. The check waits 3 s after the arrival before it records the ground items it must ignore.
- `cainsub` and `levelcap` (hardened by p4-stability, not yet re-run in a full group): PASS in all six full group1 runs above.

`checks-20261025-032845-s1` (`cainsub levelcap dropilvl wwproc monhover` alone, before these fixes): 6 PASS.
**Left:** `group2.txt` in full twice (both pairs died with the machine's GPU, above; the first 13-14 checks PASS on both slots each time, no `transguard` skip read because the counters are only written at the end of a run); the three
check fixes (`morphdeath`, `monhover`, `wwproc`, `dropilvl`) and the start-state life repair are compiled and read, but were not run in a full group after the edit (a game could not be started for more than an hour).

## Lane town-monsters: Median towns

Use a character created only for this check, with its explicit name so the harness never selects another lane's character:
`MXL_SLOT=2 MXL_RUN=town-monsters MXL_CHAR=TwnCodexOct py -3 tools/game_checks.py --slot 2 all mxl townmonsters`.
Take slot 2's lock as `town-monsters`, check it is still held immediately before installing with `tools/install_mod.py`,
and re-lock before every later install (game_checks releases it at the end). Never start if another lane's game is running.
The `MXL_CHAR` path now selects that exact character or creates it, and backs up only that character's files.

Repeat with `MXL_CONTROL=mediantowns` to leave D2R's five-town classifier intact. Both runs use the game's own level
thunk and room check, walk the player through the open Tur Dulra / Scosglen border and observe a native Scytheclaw's
room. The control must show the monster entering level 242; enabled must keep it in 271. Missing borders, inability
to walk to the setup or a monster that never acts cannot pass. All four added towns' room checks are read too.
No monster/path/collision flags are overridden by the harness. `h town [level]`, `h town x y`, `h town edges`,
monster `area=` in `h state` and optional `h spawn class count x y` provide the observations. Off word `mediantowns`;
console line `median towns`; version unchanged.

Final evidence (slot 2, throwaway `TwnCodexOct`, plugin 0.66.0):
- Control `checks-20261025-190752-s2`: `mxl` PASS, `townmonsters` PASS (bug reproduced: active Scytheclaw 30 enters 242).
- Enabled `checks-20261025-191034-s2`: `mxl` PASS, `townmonsters` PASS (active Scytheclaw 30 stays outside 242).
- All nine town ids, adjacent/invalid controls, and room checks in all four added towns match the expected classifier.
- Both runs: zero new crash files, no cursor or foreground changes, transguard skips 0. Enabled loader scan reports
  50 ERROR/ASSERT lines (startup level-type/automap, debug skill-description and exit pool assertions); it is not a clean assertion log.
  No mxl-core error/fail/assert lines. Earlier control setup attempts were BLOCKED/FAIL, including one enabled attempt
  that exposed an SDK patch-length refusal; the final equal-length guarded patch installs successfully.
- The fixture streams the outdoor approach using actual Teleport casts before spawning; it can blink past an approach
  obstruction. After spawn it uses walking only. No monster position, collision or path flags are overridden.
- The manual slot lock was retained between install/test iterations by a local runner, then released only after the
  last game stopped. Only the lane-created character was selected/backed up/patched. No slot/save incidents.
- Left: dedicated missile/skill aggression scenarios (shared classifier corrected), documented in `unported.md`.

### Layered special item text (special-text, 2026-10-25, background, slot 3)

`tooltiptext specialtext`: **PASS**, `checks-20261025-185239-s3`. The corrected audit reads 313 property lines
(294 OK / 19 ITEM); the new check sends all 812 referenced Median string IDs through the real property formatter,
checks 64 colour probes (four stats x 16 values), and reads Azure Wrath, Staff of Herding, unique 30 and Optical Detector
through the item builder. All 778 short paragraphs match fully; 34 long paragraphs match bounded prefixes, with their
precise IDs and remaining tail limitation in [unported.md](unported.md). `special-text-readback.txt` in the run folder
keeps the complete text answers. The harness adds `tipcolour` after the existing plain `tipfmt` answer.

Control: `MXL_CONTROL=itemtext`, off word `itemtext`, `specialtext` **PASS**, `checks-20261025-184439-s3`:
no Median special paragraphs; Azure's missing hidden-passive name returns; descfunc 31 prints the native Random Class
line. The final and control runs have zero crash files, zero cursor / foreground changes and no watchdog abort.
The lane's wrapper selected/created only `SpTextThree`; the earlier baseline used only `SpecialTxt` in slot 2
(`checks-20261025-182658-s2`). It did not use the default most-recent-character selection or back up other saves.
The earlier failed long-colour-boundary probe and intermediate build/startup problem are recorded in
[item-tooltips.md](item-tooltips.md). Existing startup, magic-item harness and exit pool assertions are unchanged.

## Waypoint arrival and HD panel regression (lane waypoints)

Use an owned slot lock, background input and an explicitly named throwaway character
(`MXL_SLOT=3`, `MXL_RUN=waypoints`, `MXL_CHAR=WpLane`, `MXL_INPUT=background`).
`game_checks` creates the named character if absent; with `MXL_CHAR` set, its save
backup includes only that character's files and it selects that character by name.

Run `py -3 tools/game_checks.py all wparrival wppanel` with
`MXL_CONTROL=wpauto` for the enabled case, then with
`MXL_CONTROL="wpauto wparrival"` for the control. `wpauto` is disabled in both:
the check clears each destination's server bit, operates its real object with
function 23, and verifies that the bit becomes set. `waypoint approach` loads the
waypoint room for setup; the object coordinates come independently from `wpobj`.
Travel uses the normal server packet 0x4b from Cold Plains (town for the vanilla
Cold Plains destination). A source-position check and animation wait prevent a
refused travel request from being counted as an entry fallback. Every arrival
must reach the requested level; the enabled check requires a stand position within
12 sub-tiles of the object, while the control requires the seven added preset areas to
reproduce their old fallback and the maze levels Cold Plains / Duncraig to remain correct.

`wppanel` unlocks the test character's client act-tab quests, opens the native HD
panel and clicks all five tabs using background input. It checks the actual button
table against all 47 destinations (10/11/12/4/10) and saves five screenshots.
Classic graphics (G) remains deferred in `unported.md`.

The installer now honors `MXL_SLOT` by default. With `MXL_RUN` set it refuses a
foreign/missing lock or a running game, before changing mod files or slot config.
`py -3 tools/test_install_mod.py` runs four refusal/selection regression tests
without writing game files. Reacquire the slot before every install; the default
harness shutdown releases its lock.

Final evidence under `%USERPROFILE%\mxl-d2r-runs`:

| Run | Arrival | HD panel | Log/input safety |
|---|---|---|---|
| `checks-20261025-191716-s3` (enabled) | PASS: all nine destinations one subtile from their object | PASS: 47 entries | No new errors/asserts/crashes; zero cursor/focus changes |
| `checks-20261025-192243-s3` (off control) | PASS: seven preset fallbacks, Cold Plains and Duncraig correct | PASS: 47 entries | No new errors/asserts/crashes; zero cursor/focus changes |
### Maximum resistance is capped at 90 by design (lane maxres-cap, 2026-10-25)

Median's rule is `min(75 + maximum-resistance stat, 90)`, not an uncapped maximum. See
[subsystems/combat-stats.md](subsystems/combat-stats.md#maximum-resistance-report-works-as-median-lane-maxres-cap-2026-10-25)
for the bundled data and D2Sigma patch evidence. The gameplay code and plugin version are unchanged.

Slot 2, background harness, freshly created lane-owned character **MaxresCodex**. Initial runs used plugin
**0.66.0** built from `ffd829032912c980ee97466921df447a648e3093`. Installed through `tools/install_mod.py::finish_install` after checking
the owned slot lock; existing installed data was retained (no data change).

- Existing check **resistcap: PASS**, run `checks-20261025-182129-s2`: 24/24 probes, player and Rogue hireling,
  fire / lightning / cold / magic. With resistance 200, maximum-resistance +0 / +10 / +50 left exactly
  25,000 / 15,000 / 10,000 of each 100,000-unit incoming hit: effective caps **75 / 85 / 90%**.
- The first item-gear probe in that folder is **invalid / FAIL**: it supplied ten `stat=value` pairs to an
  eight-pair harness command, which refused item creation. Its zero-resistance hits and screenshots are not
  cap measurements. This was a probe error, not a gameplay failure.

All run evidence stays outside git under `%USERPROFILE%\mxl-d2r-runs`. No game files or screenshots are committed.

Corrected item probe (local driver `mxl-d2r-runs/maxres-cap-check.py`, built on `game_checks.run_all`, retained outside
git to honour the docs-only direction) uses a `cm2` inventory charm with eight stat pairs, e.g.
`h item cm2 fireresist=150 maxfireresist=10 lightresist=150 maxlightresist=10 coldresist=150 maxcoldresist=10 magicresist=150 maxmagicresist=10 inv`.
It reads server `stat` and client `cstat`, calls the real damage step via `hit` outside town, then captures the character
panel in town. It never substitutes its own cap into the game. The expected cap is only an assertion in the driver.

**Confirmed display bug, separate from the correct gameplay ceiling:** with maximum-resistance **+16**, the character
panel shows **91%**, while the incoming 100,000-unit hit leaves **9,300** (90% resistance, then a separate 7% damage reduction). The server and client
raw stats both read resistance 150, maximum 16. Screenshots `maxresgear_0.png`, `_10.png`, `_15.png`, `_16.png` in
`checks-20261025-182510-s2` show **75 / 85 / 90 / 91%** for fire / cold / lightning. The character panel's unpatched
`cmp ecx,95` (`0x14e728f`) skips the patched `mov ecx,90` for computed maxima 91..94; the damage clamp and hireling
panel use the patched register for their comparison. This display issue is recorded in `unported.md`; it is not a
reason to raise the gameplay cap. No code change under the coordinator's docs-only direction.

The corrected eight-pair run `checks-20261025-182510-s2` initially marked the damage probe FAIL because its
expectation omitted that additional 7% damage reduction (for example 23,250 rather than 25,000 at the 75% cap).
Its gear and client-stat reads and panel captures are valid. A subsequent normal / control pair accounts for
stat 369 in the same way as the existing `resistcap` check. This run also logged a continuing `m_freed == 0`
engine assertion and no crash; it is not presented as an assertion-free run.

Final normal gear check **PASS (24/24)**: `checks-20261025-183121-s2`. With maximum resistance
**+0 / +10 / +15 / +16 / +20 / +50**, effective caps were **75 / 85 / 90 / 90 / 90 / 90%** for fire,
lightning, cold and magic. The loaded character supplied stat 369 = 7 despite a base-stat reset: damage fields
were **23,250 / 13,950 / 9,300 / 9,300 / 9,300 / 9,300** after that additional reduction. Server and client
raw resistance / maximum values matched the charm's 150 / requested maximum in every case. The panel screenshots
show 75 / 85 / 90 / 91 / 90 / 90 for the three visible elemental rows.

The final pair used the slot-installed 0.66.0 DLL, SHA-256
`44048202f7ccd3dc7d609dda40e9cd349fad33c146250bc16045aa661d5dc18d` (another lane installed its build while
this lane had released the lock). Initial source-build DLL SHA-256:
`01f5f1bdadb813cc61deafe91887d0399c98f9bf0b9e32cb218e87c865edf340`.
The `mxl` combat report confirms all three ceiling patches; the control uses the same DLL with **combat** disabled.

Control gear check **PASS (24/24)**: `checks-20261025-183640-s2`, `MXL_CONTROL=combat`, same DLL and character.
The `mxl` line says `combat off: left out by mxl-core-off.txt`. Maximum-resistance **+0 / +10 / +15 / +16 / +20 / +50**
leaves **25,000 / 15,000 / 10,000 / 9,000 / 5,000 / 5,000** of a 100,000-unit hit, i.e. native effective caps
**75 / 85 / 90 / 91 / 95 / 95%**. The character panel confirms 95% at +20 (screenshot `maxresgear_20.png`).
The control also disables combat's post-resistance damage reduction, so stat 369 is intentionally excluded from
that run's expected damage. Its report includes the preceding normal rows because the driver reuses the in-memory
results list; the rows marked `control=True` are the control measurements.

Final normal / control runs: **zero new engine assertion lines, zero crash files, watchdog abort None**.
Both games stopped before returning; the driver retained the lock between them and released it afterwards,
and the control off-file was removed. Only this lane's `MaxresCodex` save was modified. No slot/save incidents.
Left: correct the character panel's +16..+19 display comparison in a separately authorized code change.

Control log caveat: the slot-installed build logs an unrelated `median towns FAILED` safety-size mismatch at
`0x327850`. The combat part is deliberately off in that run; cap probes and the native character panel still
match the expected control values. This lane does not modify the towns part.

## Lane suite-067: targeted run of PRs #162-#166 and the character sheet resistance display (plugin 0.68.0, 2026-10-25)

Slot 2, background mode, one game at a time, character `MxlBarb` of the slot. A full `group1.txt` run (68 checks, `suite067-g1`) was
stopped by the owner after about 52 minutes (`game_ctl stop` of the slot, lock released); its results are not a verdict (one FAIL seen,
`itemevents`: thorns 50 took 52 points of monster life instead of 50; the 396 / 128 variants and the other rows of that check were
exact; the check is outside the five PRs; rerun in lane ied-vanish (section below): not reproduced). Targeted list (names as in the CHECKS list; `tooltip` and
`travel` are not check names: `tooltiptext` is the tooltip audit, `iedtip` is #164's tooltip check, `wparrival` / `wppanel` are #166's
travel checks): `mxl tooltiptext specialtext orbtips itemstatsave ied iedtip statclick grit townmonsters towncast npcheal tplock goblins
wparrival wppanel wpauto resistcap`. Also: `py -3 tools/validate.py` (0 errors, base 61 / rotw 102 warnings as before), the nine C++ test
executables (all pass), `tools/build.py` (needs `extract/` and `build/StormLib`, `build/CascLib`: a junction to the shared `extract` and
`tools/build_native.ps1`).

| Check (0.67.0, `checks-20261025-223505-s2`) | Result |
|---|---|
| mxl, goblins, tooltiptext, specialtext, itemstatsave, wparrival, wppanel, wpauto, towncast, npcheal, tplock, grit, statclick, iedtip | PASS |
| orbtips | REVIEW (screenshot review, as in every suite) |
| resistcap | FAIL: the new sheet read found the 91% display bug (+16 differs from +15 by 2.27); the damage rows 24/24 PASS |
| townmonsters | FAIL "inconclusive pursuit setup" (classifier part PASS); rerun alone PASS; see below |
| ied | FAIL (formula rows, IED, marker rows PASS; see below) |

**resistcap (fixed, 0.68.0):** `combat.cpp` now also patches the immediate of the character sheet's compare (`0x14e728f`: `cmp ecx,0x5f; jl +5;
mov ecx,0x5f`, bytes read with `peek`). `check_resistcap` reads the sheet: charm-free, with the client's copy of the stats (`cstat set`
resistance 150, maximum 0 / 10 / 15 / 16 / 20 / 50), `statorder open`, a screenshot, the crop of the Fire / Cold / Lightning rows
(`RESIST_PANEL_BOX`); +15, +16, +20 and +50 must be the same picture (mean pixel difference < 0.3) and +0 / +10 / +15 must differ. 0.67.0: +16 differs by
2.27 (FAIL); 0.68.0 (`checks-20261025-232904-s2`): +16 / +20 / +50 differ by 0.00, PASS, `4/4 clamps` in the `mxl` line. The
control (`MXL_CONTROL=combat`) expects +16 to differ from +15.

**townmonsters (flake of the check's fixture):** the field Scytheclaw sometimes stays idle during the pursuit ("monster acted=False"); that was 2 of 3 runs
before the change, the town classifier rows and "monster entered town=False" were the same in all three. `check_townmonsters` now respawns the monster up
to three times before it calls the setup inconclusive. After the change PASS (`suite067-t5`). With the `mediantowns` off word the check fails its control
expectation as designed.

**ied (open in this run, fixed in plugin 0.69.0, see "Lane ied-vanish" below):** the passive's data formula, IED, marker and explicit-refresh rows are exact,
`iedtip` PASS. What failed differed from run to run: the innate fire (stat 48) was 0 a second after a refresh, or after the live refresh of an attribute
packet. This was not caused by the five PRs: the engine's own equipment recheck took the stat away (details below). `check_ied` had been given a retry of the refresh (up to four times) and a 2 s poll in that run; the retry was removed again in 0.69.0, because it hid the loss.

## Lane ied-vanish: the innate fire that vanishes, `itemevents` thorns 52, check names (plugin 0.69.0, 2026-10-26)

Slot 2, background mode, one game at a time, throwaway character `IedVan`. The drivers are throwaway and not committed (in `%USERPROFILE%\mxl-d2r-runs`:
`iedvan_probe.py`, `iedvan_repeat.py`, `iedvan_load.py`, logs `iedvan-*.log`). New harness verbs (kept as diagnostics): `passivestate` (state list of skill 2072:
list pointer, stat array, inputs oskill / synergy / Dexterity / IED, fire), `passivetrace on|clear|show` (every call of the passive apply `0x337890` and refresh
`0x33f830` with the inputs at that moment and a call chain); the write-watch chain of `evtrace watch` now scans the stack for return addresses.

**1. Innate damage vanishing: root cause.** The state list of the passive (skill 2072, state 626) is never lost (`has=1`, same list pointer); its stat
array is rebuilt without the fire / min / max entries (4 entries -> 2). `passivetrace` shows who does it: D2R's own **equipment recheck** runs the apply
with flag 0 three times in a row and then does nothing more:
(a) the item is taken off: oskill 97:2072 = 0, Dexterity without the item's bonus -> level 0 -> fire 307 -> 0;
(b) the same once more;
(c) the item is put back through the equip step `0x475140`, but the apply runs while the list is half back (oskill and Dexterity are in, the synergy
stat 412:2072 is not yet: `osk=1 syn=0 dex=205`) -> fire stays 0. Nothing applies the passive again once the list is complete.
The recheck is not specific to the harness: it runs at once in the handler of every attribute packet (clean game, `iedvan-clean-trace.log`: fire 310 -> 0
inside the packet), D2R runs it again 0.4 - 2 s later (the one that took the stat "a second after a refresh"), and it runs when a character is loaded.
Load control (`iedvan_load.py`, character saved with the cap worn, then a game restart): **fire 0** from the first frame with the part off (`iedvan-load-off.log`),
205 with the fix (`iedvan-load.log`). So a real player loses the innate damage on every login with such gear, after spending points (the plugin's refresh
of 0.67.0 covered the immediate run only, not the second one), and after a gear change that goes through the equip step.
**Why only after other checks:** bisect (part `innate` off, 10 refreshes per run): nothing run before 0/10, `statclick` 0/10, `townmonsters` 3/10 -> `townmonsters`
is the earlier check that sets it up. The deferred second recheck is the part that needs the state it leaves; which single leftover does it is **not isolated**:
the god cheat on/off, cross-act travel (areas 271 / 242), the Teleport skill and mana stats, a move, a spawned monster, stat 328 (pierce index 35, the only stat
difference in the stat / state dump) and a socketed helm, each set alone in a clean game, gave 0 losses. The immediate recheck in the packet handler does not
depend on it.
**Before #164:** the pre-#164 plugin (0.66.0 + probe verbs, `iedvan-old-run.log`) loses the fire the same way (2 of 10 refreshes after `townmonsters`
`statclick`): the loss is the engine's, not a regression of #164, #165 or the other PRs.
**Fix (Median way: the passives are worked out once the item's stat list is complete):** `stat_rules.cpp` hooks `0x475140` under part `innate` and calls
`0x33f830(owner, 1)` after the original returns, for players only. `mxl` line: `innate damage on: attribute and equip refresh on`. No other behaviour changes.
**Results:** probe with the hook (`townmonsters statclick`, `iedvan-run7.log`): refresh 0 of 12 lost, packets 0 of 10 lost (without it 5/12 and 7/10).
`check_ied` is strict now (no retry of the refresh, a 3 s hold after each packet, and a row that reads the fire right after the equip without a refresh); with the
checks that set it up first (`townmonsters`, `statclick`), the same game: **5 of 5 PASS** (`checks-20261026-012834-s2`). Targeted set on the 0.69.0 build
`mxl statclick grit ied iedtip itemstatsave itemevents classlock`: all PASS (`checks-20261026-020458-s2`). `MXL_CONTROL=innate` with `innate` in
`mxl-core-off.txt`: `ied`, `iedtip` PASS their control expectations (`checks-20261026-021018-s2`).

**2. `itemevents` thorns 52: not reproduced.** Alone, three times in one game (`checks-20261026-013557-s2`): thorns 50 each time (one run had the 128 variant at
-100 points = two events, which the check allows: the monster's own hit fires the event too). After the group1 predecessors `mxl respec heart lockout cow areacycle`
(`checks-20261026-013854-s2`): 50 / 50 / 50. Again on the 0.69.0 build in the targeted set: PASS. A spawned class 18 monster at 700000 raw life lost nothing in
six 0.3 s readings in ten spawns (`iedvan-drain.log`), so there is no slow drain. The earlier 52 (and the 686816 vs 687200 of the 0.61.0 notes) stay unexplained
and rare; no leftover state was found, so the check is unchanged. (`respec` failed once in the predecessor run with "no plugin line in Akara's menu", and passed
alone with the hook on and off and again after `mxl`: a one-off outside this lane.)

**3. `group2.txt` / unknown names.** `group2.txt` (outside git) listed `tooltip`; removed (`tooltiptext` is the tooltip audit and is in the list). `game_checks.run_all`
now refuses a check list with a name that is not in `CHECKS` (prints the names, returns 2 before the lock, the game and the run folder), and
`tools/test_game_checks_names.py` covers it (`py -3 tools/test_game_checks_names.py`). The three group files have no unknown name.

Also run: `py -3 tools/validate.py` (errors 0, rotw warnings 102 as before), the nine C++ test executables (all pass), `git diff --check`.

### Lane player-bugs-1 (2026-10-27): player reports #35-#39 and #45 (docs/bugs.md)

Data only (tools/txt_migrate.py `raven_counts`), no plugin change, no version bump. Slot 2, character PlrBugsA.

| Check | What | Result |
|---|---|---|
| summonlife (new) | Barbarian: wolf_companion and guardian_spirit (control) summoned in the Blood Moor and in town, life sampled every 2 s for 30 s (one empty sample is a listing gap, two in a row or empty at the end is a death) | **PASS** (`checks-20261027-123822-s2`); before the fix the wolf died about 2 s after the cast in both areas (#36) |
| vendororbs (new) | Akara, Charsi and Gheed at Hell level 90: the mystic orbs on their shelves against Median's npcstores.bin | **PASS** (`checks-20261027-122117-s2`): Gheed 34 orbs, all in Median's list; Akara and Charsi none (#37 cancelled, as Median) |
| orbtips (extended) | also hovers up to 3 orbs on Gheed's Misc tab (Hell, level 90), screenshots `orbtips_shop_<key>` | REVIEW (`checks-20261027-124427-s2`): shop and inventory tooltips show every line of the orb's record (#38 not reproduced) |
| allattrtip (new) | a magic amulet with +5 to Strength / Energy / Dexterity / Vitality and the suffix counter, plus rolled magic amulets until one has the all-attributes suffix: "+N to all Attributes", "Suffixes: 1", no printf placeholder; capture `allattrtip_amulet.png` | **PASS** (`checks-20261027-123822-s2`, #45 not reproduced) |
| nodurabilityui | no repair button at Charsi, no durability line | **PASS** (`checks-20261027-122117-s2`; #39 as Median) |

Also run: `py -3 tools/validate.py` (errors 0, rotw warnings 102 as before), `py -3 tools/test_game_checks_names.py`.

### Lane abyss-knight (2026-10-27): bug #59, Abyss Knights melee (plugin 0.69.13)

Necromancer AbyssKnt, Abyss Knight level 20, monsters spawned 9 yards away, the knights' modes sampled for 25 s.

| Check | What | Result |
|---|---|---|
| abyssknight (new) | knights in skill1 (8, the void blast) more often than attack1 (4), `abyss_knight_skill_missile` made; with `MXL_CONTROL=rangedpets` melee only | before the fix (0.69.10 code, dev): modes {1: 58, 2: 81, 4: 101}, 0 missiles; a forced `mcast` in S1 made the missile (the skill works, the AI never picked it). Dev slot 2: **PASS** `checks-20261027-180606-s2` {1: 101, 2: 38, 8: 93}, 65 missiles; control **PASS** `checks-20261027-180946-s2` {1: 65, 2: 78, 4: 89}, 0 missiles. Release install (tools/release_install.py, slot 2, dev DLL): **PASS** `checks-20261027-181233-s2` {1: 95, 2: 14, 8: 115}, 71 missiles; control **PASS** `checks-20261027-181404-s2` {4: 108}, 0 missiles |
| mxl | `ranged pets on (marked N)` line | **PASS** (all four runs) |

Also run: `py -3 tools/validate.py` (errors 0), the twelve C++ test executables (all pass), `compileall`, `check_public.py`.
Each launch leaves a first-chance access violation report in `d2rloader\crashes` (3733 bytes). It came with the pre-fix plugin too and the game kept running.
