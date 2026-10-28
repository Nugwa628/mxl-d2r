# Changelog

D2R-XL releases (the mod, version = the plugin's `PluginVersion`) and D2R-XL Downloader releases. Newest first.
Downloads: the downloader always installs the newest release; each release's 7z is at
`https://files.werdegames.com/mxl/releases/<version>/D2R-XL-<version>.7z`. Known bugs: [docs/bugs.md](docs/bugs.md).

All releases need Diablo II: Resurrected **3.3** (Battle.net or Steam) and **D2RLoader 1.3.1**.

## D2R-XL

### 0.69.17 (2026-10-28)
- **Fixed a crash in big fights (reported at Griswold)**: D2R draws units through a fixed 12 MB memory pool; when a
  busy Median scene filled it, the game wrote through an empty pointer and closed (`D2R.exe+0xF3D028`). The plugin now
  takes the extra memory from Windows when the pool is full, and the log says so once
  (`render pool: the Renderer Pool is full ...`). ([#60](docs/bugs.md))

### 0.69.16 (2026-10-27)
- **Socketed runes give their bonuses, and identical runes stack**: two Eld in a helm give +6 maximum damage, three
  Ral in a weapon +90% fire resistance. ([#50](docs/bugs.md))
- The circlet crash fix of 0.69.15 now comes from the game data: Median's item types are numbered the way D2R expects
  (D2R's own new types keep their numbers), so D2R's built-in item rules (runes, potions, charms, circlets, ...) match
  without changing the game's code. The plugin only checks at start that they match. ([#49, #55](docs/bugs.md))

### 0.69.15 (2026-10-27)
- **Fixed the crash when picking up or wearing a circlet** (Circlet, Coronet, Tiara, Diadem). D2R 3.x added an item
  type, so Median's item type numbers sit one lower than D2R's from that point on; D2R's built-in "is this a rune" check
  matched circlets and ran the rune-in-socket code on them. All 25 such built-in item type checks now use Median's
  numbers. ([#49, #55](docs/bugs.md))
- The same fix corrects other built-in item rules: runes, potions (mana potions were treated as healing potions),
  hand-to-hand weapons, pelts, charms and perfect gems.

### 0.69.14 (2026-10-27)
- **Fixed: Bend the Shadows** (the Necromancer's innate warp) can go on the **right** mouse button again, where a click on
  the ground casts it. The other innate skills that could not be selected at all (Mana Shield, Titan's Fortitude, Mark of
  the Wild, Vindicate) can now be put on a button too. ([#57](docs/bugs.md))

### 0.69.13 (2026-10-27)
- **Fixed: Abyss Knights use their void blast again** instead of only hitting in melee. As in Median, the Guardian Spirit,
  the Mana Tide and Elemental totems, and the Sinner, Frostwalker and Glowing Fungus summons also fight as ranged pets. ([#59](docs/bugs.md))

### 0.69.12 (2026-10-27)
- **Fixed: Night Hawks explode again.** A hawk that hits now dies and explodes, as in Median. ([#58](docs/bugs.md))
- **Median's "cast on death" effects work.** Monsters with a death effect (248 rows in Median's monster property table)
  now cast it when they die; before, none of them did.

### 0.69.11 (2026-10-27)
- **Fixed the remaining goblin / Den boss crash.** It happened on D2RLoader's very first start after installing or
  updating D2RLoader or D2R: on that start D2RLoader builds its table cache and loads only D2R's own sounds, so Median's
  sounds were missing. Every sound lookup is now guarded, so that start no longer crashes. ([#42, #46](docs/bugs.md))
- On that first start a notice asks you to **close the game and start it again**. Median's own sounds are silent until
  then, and play normally from the second start on.

### 0.69.10 (2026-10-27)
- **Fixed skill icons:** **Attack** and about 86 other shared skill icons (Throw, Unsummon and more) showed the icon
  next to theirs. A few class skills (Reckoning of Zerae, Batstrike, Pneumatic Burst, Shadow Flow) had the wrong
  frame. Every skill now uses Median's exact icon, in classic and HD. ([#52](docs/bugs.md))
- Known: about 160 skills that items put on the skill bar show Median's "?" icon in HD for now
  ([#56](docs/bugs.md)).

### 0.69.9 (2026-10-27)
- **Fixed a crash** when a **treasure goblin** (for example the Arcane Collector) appears, and when the **Den of Evil
  boss** casts its cold bone spear. The game looked up a Median sound that the player's install did not have. D2R-XL
  now skips such sounds instead of crashing. ([#42, #46](docs/bugs.md))
- **Fixed:** missiles that summon a monster on hit (406 Median missiles) summoned the wrong monster, e.g. the Den of Evil
  boss's bone spear. ([#42](docs/bugs.md))
- (Corrected in 0.69.11: the silent sounds came from D2RLoader's first start, not from `-txt`.)

### 0.69.8 (2026-10-27)
- Released with **Downloader 0.2.5**.
- The plugin checks that the game really runs it from `mods\D2R-XL`. If D2RLoader starts another mod, or an old copy
  of the plugin is loaded, it shows a red warning on screen and in the `mxl` line. The first `mxl` line now also shows
  the active mod and the plugin's file. ([#53](docs/bugs.md))

### 0.69.7 (2026-10-27)
- Released with **Downloader 0.2.3**. No game changes.
- **Steam players:** D2R-XL works on the Steam build 94995. It is the same game program as Battle.net's 93847, and the
  plugin always ran there; only the downloader refused it.

### 0.69.6 (2026-10-27)
- The in-game `mxl` console line and `mxl-core.log` now name any **other D2RLoader plugins** that are loaded. That helps
  with crash reports. ([#44](docs/bugs.md))
- README: **Known conflicts.** D2R-XL does not support other gameplay plugins alongside it (for example pSpell, vendor
  refresh, Qual-Kehk); disable them. Their features are planned as part of D2R-XL itself.
- The Den of Evil boss (Corrupted Necromancer) was tested in HD and legacy graphics: no crash with D2R-XL alone
  ([#42](docs/bugs.md)).

### 0.69.5 (2026-10-27)
- **Fixed:** the Barbarian's **wolf companion** and the **raven familiar** died about two seconds after being summoned.
  Their attack counter is now set the way Median sets it. ([#36](docs/bugs.md))

### 0.69.4 (2026-10-27)
- Released with **Downloader 0.2.2**. No game changes.

### 0.69.3 (2026-10-27)
- The release version and the plugin version are now always the same number (the `mxl` line and the wrong-build message
  show it). Released with **Downloader 0.2.1**. No game changes.

### 0.69.2 (2026-10-27)
- Installs into your own D2R folder (`mods\D2R-XL`) with the new **D2R-XL Downloader 0.2.0**.
- D2RLoader no longer needs the `-txt` launch argument.

### 0.69.1 (2026-10-26)
- The mod is now called **D2R-XL**: mod folder `mods\D2R-XL`, saves in `Saved Games\Diablo II Resurrected\mods\D2R-XL`.

### 0.69.0 (2026-10-26)
- **First public build.** A port of Median XL 2.14.4 to D2R 3.3, playable single-player in HD graphics mode:
  - Median's items, skills, monsters and quests;
  - the eight-page skill trees;
  - Median's engine rules in the D2RLoader plugin;
  - the Median-only areas and waypoints.

  Median-only monsters, effects and maps use the closest vanilla HD stand-ins. See the README, "Where it stands".

## D2R-XL Downloader

### 0.2.5 (2026-10-27)
- The requirement is the **game version, D2R 3.3**, not a build number. Any 3.3 build (Battle.net, Steam, later
  hotfixes) is accepted; the window shows "3.3, build N". (Advice from D2RLoader's author.)

### 0.2.4 (2026-10-27)
- **Warns when D2RLoader would start something else than the installed D2R-XL** ([#53](docs/bugs.md)):
  - D2RLoader's Default Mod is not D2R-XL: "D2RLoader starts the mod MedianXL, not D2R-XL". The **Default mod** button
    makes D2R-XL the default mod after asking; it changes only `default_mod` in `<D2R>\d2rloader\config\d2rloader.toml`.
  - An old copy of the D2R-XL plugin (`mxl-core*.dll`, or any DLL whose version info says D2R-XL) in
    `<D2R>\d2rloader\plugins` (it loads with every mod) or in another mod's plugins folder. The **Move plugin** button
    moves it to `%LOCALAPPDATA%\D2R-XL\removed\<date>\` after asking; nothing is deleted.
  - Command line: `--cli status` prints the warnings, `--cli fix-default-mod` and `--cli remove-stray-plugins` fix them.

### 0.2.3 (2026-10-27)
- **Steam:** accepts D2R build 94995, the same game program as 93847, instead of saying the build is not supported.
  ([#41](docs/bugs.md))

### 0.2.2 (2026-10-27)
- **Fixed:** "D2R or D2RLoader is running, close the game first" while both were closed. This happened when the
  downloader was saved inside the D2R folder. Now only `D2R.exe` and `D2RLoader*.exe` count, and the message names the
  program it found. ([#40](docs/bugs.md))

### 0.2.1 (2026-10-27)
- Downloads come from `files.werdegames.com` (a CDN-backed mirror). `dl.werdegames.com` stays as the backup
  (`--site`).

### 0.2.0 (2026-10-27)
- The launcher became the **D2R-XL Downloader**. It installs D2R-XL into your D2R folder's `mods\D2R-XL` and does not
  start the game.
- A fresh install downloads one 355 MB 7z and unpacks it; updates and Repair fetch only the changed files.
- It shows whether **D2RLoader 1.3.1** is installed, with a link to d2rloader.net, and warns about an unsupported D2R
  build.
- It offers once to delete the old private game copy of launcher 0.1.x.

### 0.1.2 (2026-10-27)
- **Fixed:** the launcher kept offering to update itself to the same version.

### 0.1.1 (2026-10-26)
- New D2R XL logo.
