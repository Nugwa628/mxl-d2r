#!/usr/bin/env python
"""Scripted in-game checks for the untested rows of docs/testing.md, in game_ctl's BACKGROUND input mode.

Everything goes through tools/game_ctl.py's background path: console lines run through the plugin test harness
(`g.console_bg`, `g.console_text`), keys and mouse are window messages plus the plugin's virtual cursor, screenshots
are PrintWindow captures. This script never presses Ctrl+`, never calls SetForegroundWindow / SetCursorPos and never
uses ImageGrab. A watchdog thread samples GetCursorPos and GetForegroundWindow every 25 ms for the whole run and
aborts the run when the real cursor enters the game window or the game window becomes the foreground window.

Run with `py -3 tools/game_checks.py all [check ...]` (writes report.md, screenshots and logs into
%USERPROFILE%\\mxl-d2r-runs\\checks-<time>\\); `--slot N` picks a game slot.
Checks: mxl lockclock goblins respec cain cainsub heart catalyst tower lockout lockquest reenter cow goldcraft
craftflags areacycle mapmem casts itemevents medianai medianai_ctl tyrael resistcap absorb damagered avoidcaps
classlock hiregates itemrolls allqualsockets dye runestack goldclient bonusdrops summoner tooltiptext specialtext gameend itemstatsave trophy statcols
skilltree keybinds npcstrings automap scrollportals vendors monhover levelcap skillcaps townportal potions itemskills
cowportals cubeoutputs deathcrash nocorpse corpsepickup cooldowns collidetypes skillstarts activationfreq nslong orbtips strings goblinname rewardsound statorder infopanel sprint steadyaim restrictitems
heat trophytimer mapreveal wpauto hotkeys stashpages stashpage2 skillscaling nodurability nodurabilityui autoid townmana mercrevive questxp
questrewards gamble enginegaps monlevel normaltc leash bufficons uniquelimits assetpaths towncast npcheal tplock charmlimit arealevel bugfixes
respecbuffs signet dropilvl cubehotkey cowtowns freerespec grit statclick townmonsters
teleportgold skillafford hcdeath meleenotarget reqlevel cubedrop soulstealer wwproc morphdeath goblincrash skillicons releasetables.
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import hashlib
import os
import re
import shutil
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_ctl as g  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOCK = os.path.join(g.RUNS, "game.lock")
SAVES = g.SAVES
user32 = ctypes.windll.user32

# ------------------------------------------------------------------ run folder, lock, watchdog


def new_run():
    """Own run folder for this process (runs/current.txt is shared between lanes)."""
    name = "checks-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-s%d" % g.SLOT  # two slots may start in the same second
    d = os.path.join(g.RUNS, name)
    os.makedirs(d, exist_ok=True)
    g.current_run = lambda create=False: d
    return d


def lock(wait_s=3600):
    t0 = time.time()
    while True:
        try:
            os.mkdir(LOCK)
            return True
        except FileExistsError:
            if time.time() - t0 > wait_s:
                return False
            g.log("game.lock is held, waiting 30 s")
            time.sleep(30)


def unlock():
    try:
        os.rmdir(LOCK)
    except OSError:
        pass


def backup_saves():
    dst = os.path.join(g.RUNS, "save-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-s%d" % g.SLOT)
    if os.environ.get("MXL_CHAR"):
        from pathlib import Path
        os.makedirs(dst, exist_ok=True)
        for p in Path(SAVES).glob(g.CHAR_NAME + ".*"):
            if p.is_file():
                shutil.copy2(p, dst)
    else:
        shutil.copytree(SAVES, dst)
    return dst


class Watchdog(threading.Thread):
    """Samples the real cursor and the foreground window every 25 ms."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = False
        self.abort = None
        self.first = self.last = None
        self.min = [10 ** 9, 10 ** 9]
        self.max = [-10 ** 9, -10 ** 9]
        self.fg_changes = 0
        self.samples = 0
        self.cursor_moves = 0
        self._fg = None
        self.inside_prev = False
        self.rest_inside = None

    def run(self):
        pt = wt.POINT()
        prev = None
        while not self.stop_flag:
            user32.GetCursorPos(ctypes.byref(pt))
            cur = (pt.x, pt.y)
            fg = user32.GetForegroundWindow()
            self.samples += 1
            if self.first is None:
                self.first = cur
            self.last = cur
            self.min = [min(self.min[0], cur[0]), min(self.min[1], cur[1])]
            self.max = [max(self.max[0], cur[0]), max(self.max[1], cur[1])]
            if prev is not None and cur != prev:
                self.cursor_moves += 1
            prev = cur
            if self._fg is not None and fg != self._fg:
                self.fg_changes += 1
            self._fg = fg
            h = g.find_window()
            if h:
                l, t, r, b = g.client_rect(h)
                inside = l <= cur[0] < r and t <= cur[1] < b
                if inside and not self.inside_prev and prev is not None and cur != prev and not self.abort:
                    # the real cursor MOVED into the game window. A cursor the user left resting over the window
                    # (never moved by this run) is not an abort reason; a move into it is, whoever made it.
                    self.abort = "real cursor moved %s -> %s into the game window %s" % (prev, cur, (l, t, r, b))
                self.inside_prev = inside
                if fg == h and not self.abort and time.time() >= g.FG_GRACE_UNTIL:
                    self.abort = "the game window became the foreground window"
            time.sleep(0.025)

    def summary(self):
        return ("%d samples at 25 ms; cursor before %s, after %s, range x %s..%s y %s..%s, %d cursor changes (the user's own "
                "mouse); foreground window changed %d times; abort: %s" % (
                    self.samples, self.first, self.last, self.min[0], self.max[0], self.min[1], self.max[1],
                    self.cursor_moves, self.fg_changes, self.abort))


WD = None


def guard():
    if WD is not None and WD.abort:
        raise RuntimeError("ABORT: " + WD.abort)


# ------------------------------------------------------------------ images (PrintWindow captures)


def grab():
    import numpy as np
    return np.asarray(g.grab_client().convert("RGB")).astype(int)


def clusters(a, b, region, thr=120, minblocks=3):
    """Changed regions between two captures inside region (fractions): [(fx, fy, blocks)] sorted top to bottom."""
    import numpy as np
    h, w, _ = a.shape
    m = np.abs(a - b).sum(axis=2) > thr
    mask = np.zeros_like(m)
    mask[int(region[1] * h):int(region[3] * h), int(region[0] * w):int(region[2] * w)] = True
    m &= mask
    S = 8
    gh, gw = h // S, w // S
    blocks = m[:gh * S, :gw * S].reshape(gh, S, gw, S).sum(axis=(1, 3)) >= 8
    seen = np.zeros_like(blocks)
    out = []
    for y in range(gh):
        for x in range(gw):
            if blocks[y, x] and not seen[y, x]:
                st, pts = [(y, x)], []
                seen[y, x] = True
                while st:
                    cy, cx = st.pop()
                    pts.append((cy, cx))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < gh and 0 <= nx < gw and blocks[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                st.append((ny, nx))
                if len(pts) >= minblocks:
                    ys = [p[0] for p in pts]
                    xs = [p[1] for p in pts]
                    out.append((((min(xs) + max(xs) + 1) * S / 2) / w, ((min(ys) + max(ys) + 1) * S / 2) / h, len(pts)))
    return sorted(out, key=lambda t: (t[1], t[0]))


# ------------------------------------------------------------------ console (plugin harness) and logs

DEBUG_ON = {"v": False}


def con(cmd):
    """Run a console line. D2R's output is not readable in background mode."""
    guard()
    return g.console_bg(cmd)


def cheat(args):
    return con("cheat " + args)


def enable_debug():
    """`debug_mode` TOGGLES debug mode for the whole process; send it once per launch (the state cannot be read back:
    the effect of the next cheat is the check)."""
    if not DEBUG_ON["v"]:
        con("debug_mode")
        time.sleep(0.8)
        DEBUG_ON["v"] = True


def mxl_text():
    """The plugin's `mxl` command output (feature lines with their counters)."""
    return g.console_text("mxl", settle=1.0)


def mxl_mark():
    return g._size(g.MXL_LOG)


def mxl_lines_since(off):
    return [ln for ln in g._read_from(g.MXL_LOG, off).splitlines() if ln.strip()]


def counter(text, key, pattern):
    import re
    for ln in text.splitlines():
        if key in ln:
            m = re.search(pattern, ln)
            if m:
                return int(m.group(1))
    return None


# ------------------------------------------------------------------ menus / entering the game

DIFF_Y = {"normal": 0.42, "nightmare": 0.482, "hell": 0.542}


# MXL_ATTACH=1: the first start uses a game that is already running (one the Median XL launcher started, docs/launcher.md
# "Testing"; `game_ctl.py harness on` writes the harness file before that launch) instead of restarting it
ATTACH = {"v": os.environ.get("MXL_ATTACH") == "1"}


def to_menu():
    if ATTACH["v"] and g.game_pids():
        ATTACH["v"] = False
    elif g.game_pids():
        g.stop()
        time.sleep(2)
    DEBUG_ON["v"] = False
    if not g.start():
        return False
    if not g.clear_intro():
        return False
    time.sleep(2)
    g.click(0.62, 0.40)  # the menu swallows the first click
    time.sleep(1)
    return True


def wait_in_game(timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        guard()
        if g.in_game():
            return True
        time.sleep(2)
    return False


def play(difficulty="normal"):
    g.click(*g.UI["menu_play"])
    if wait_in_game(8):
        return True
    time.sleep(2)
    g.click(0.5, DIFF_Y[difficulty])
    if wait_in_game(45):
        return True
    g.click(*g.UI["menu_play"])
    time.sleep(3)
    g.click(0.5, DIFF_Y[difficulty])
    return wait_in_game(45)


STATE = {"in_game": False}


def enter_game(card=1):
    """From the main menu: play the selected character (card 1: the slot's most recently played one; card n: the n-th most recently
    played, see `card_of`) in Normal."""
    g.click(0.87, 0.076 + 0.091 * (card - 1))
    time.sleep(0.8)
    ok = play("normal")
    STATE["in_game"] = ok
    return ok


def card_of(name):
    """Position (1 = first) of a character on the main menu's list: the list is ordered by the time the character was last saved,
    newest first (what the .d2s files' modification times say). None when the character does not exist in this slot."""
    import glob
    files = sorted(glob.glob(os.path.join(SAVES, "*.d2s")), key=os.path.getmtime, reverse=True)
    names = [os.path.splitext(os.path.basename(f))[0] for f in files]
    return names.index(name) + 1 if name in names else None


# Hero select (fractions of the client rect, measured on slot 3 2026-10-24): the class figures stand in a row
HERO_X = {"amazon": 0.166, "assassin": 0.26, "necromancer": 0.35, "barbarian": 0.44, "paladin": 0.556, "sorceress": 0.65, "druid": 0.866}


def create_character(cls, name):
    """From the main menu: Create New, pick the class figure, type the name, Create (enters the game in Normal). The first click on
    the menu is swallowed, so one goes to empty scenery first."""
    g.click(0.62, 0.40)
    time.sleep(1)
    g.click(*g.UI["char_create"])
    time.sleep(3)
    g.click(HERO_X[cls], 0.50)
    time.sleep(2)
    g.click(*g.UI["name_box"])
    g.type_text(name)
    time.sleep(1)
    g.click(*g.UI["create_ok"])
    ok = wait_in_game(60)
    STATE["in_game"] = ok
    return ok


def cinematic_playing():
    """A cut scene plays in the game (the Act 5 one after the Tyrael walk): letterboxed, so the strip at the bottom where the HUD
    orbs are is black. Esc then skips the scene instead of opening the game menu."""
    from PIL import ImageStat
    im = g.grab_client(g.need_window()).convert("L")
    w, h = im.size
    return ImageStat.Stat(im.crop((0, int(.93 * h), w, h))).mean[0] < 3 and ImageStat.Stat(im.crop((0, int(.2 * h), w, int(.8 * h)))).mean[0] > 8


def skip_cinematic():
    n = 0
    while n < 12 and cinematic_playing():
        g.log("a cut scene plays: Esc held (%d)" % (n + 1))
        g.press("esc", hold=3)  # "Hold any button to skip"
        time.sleep(5)
        n += 1
    return n


def switch_character(name, cls, class_id):
    """Save and Exit, then play another character of the slot (created first when it does not exist); True when the game shows that
    class (`h state` class). A character that is already open is left as it is."""
    p = hstate()["player"]
    if p.get("class") == class_id:
        return True
    for attempt in range(3):
        skip_cinematic()
        g.key("esc")
        time.sleep(1.5)
        g.click(*g.UI["save_exit"])
        time.sleep(6)
        for _ in range(12):  # the save of a character with a long session behind it takes longer than 9 s
            if not g.in_game():
                break
            time.sleep(3)
        if not g.in_game():
            break
    if g.in_game():
        return False
    STATE["in_game"] = False
    time.sleep(2)
    if not g.menu_visible():  # after a long session the game can come back to the intro cinematic (morphdeath_blocked.png): skip it
        g.clear_intro(60)
        time.sleep(2)
        g.click(0.62, 0.40)  # the menu swallows the first click
        time.sleep(1)
    card = card_of(name)
    ok = create_character(cls, name) if card is None else enter_game(card)
    return bool(ok) and hstate()["player"].get("class") == class_id


def _checksum(d):
    d = bytearray(d)
    d[8:12] = len(d).to_bytes(4, "little")
    d[12:16] = b"\0\0\0\0"
    c = 0
    for b in d:
        c = ((c << 1) | (c >> 31)) & 0xffffffff
        c = (c + b) & 0xffffffff
    d[12:16] = c.to_bytes(4, "little")
    return bytes(d)


def patch_quests(name, quests):
    """Set 16-bit quest words {(difficulty, quest): word} in a closed character ('Woo!' section, 48 words per
    difficulty after 10 header bytes), fix the checksum and D2RLoader's `.d2rl` sidecar (docs/save-format.md)."""
    p = os.path.join(SAVES, name + ".d2s")
    s = bytearray(open(p, "rb").read())
    i = bytes(s).find(b"Woo!")
    for (diff, q), w in quests.items():
        struct.pack_into("<H", s, i + 10 + diff * 96 + q * 2, w)
    s = bytearray(_checksum(bytes(s)))
    open(p, "wb").write(bytes(s))
    sp = os.path.join(SAVES, name + ".d2rl")
    r = bytearray(open(sp, "rb").read())
    struct.pack_into("<I", r, 0x34, struct.unpack_from("<I", s, 12)[0])
    struct.pack_into("<I", r, 0x38, len(s))
    r[0x3c:0x5c] = hashlib.sha256(bytes(s)).digest()
    r[0x0c:0x2c] = hashlib.sha256(bytes(r[0x2c:])).digest()
    open(sp, "wb").write(bytes(r))


# ------------------------------------------------------------------ the plugin's gameplay commands (tools/game_ctl.hcmd)

def H(cmd, timeout=15):
    """One harness gameplay command (plugin/src/harness_cmds.cpp): (ok, lines). No mouse, no keyboard."""
    guard()
    return g.hcmd(cmd, timeout)


def kv(line):
    return {k: v for k, v in re.findall(r"(\w+)=(\S+)", line)}


def hstate():
    """`h state` parsed: player dict, items (dicts), mons, objs, plugin counters, npc menu."""
    ok, lines = H("state")
    st = {"ok": ok, "player": {}, "items": [], "mons": [], "objs": [], "plugin": "", "menu": {}, "lines": lines}
    for ln in lines:
        if ln.startswith("player "):
            st["player"] = {k: (int(v) if re.fullmatch(r"-?\d+", v) else v) for k, v in kv(ln).items()}
        elif ln.startswith("item "):
            st["items"].append({k: (int(v) if re.fullmatch(r"-?\d+", v) else v) for k, v in kv(ln).items()})
        elif ln.startswith("mon "):
            mon = {k: int(v) for k, v in kv(ln).items() if re.fullmatch(r"-?\d+", v)}
            lm = re.search(r"life=(\d+)/(\d+)", ln)
            if lm:
                mon["life"], mon["maxlife"] = int(lm.group(1)), int(lm.group(2))
            st["mons"].append(mon)
        elif ln.startswith("obj "):
            st["objs"].append({k: int(v) for k, v in kv(ln).items() if re.fullmatch(r"-?\d+", v)})
        elif ln.startswith("plugin "):
            st["plugin"] = ln
        elif ln.startswith("npcmenu "):
            st["menu"] = {k: int(v) for k, v in kv(ln).items()}
    return st


def items(st, code, page=None):
    return [i for i in st["items"] if str(i.get("code")) == code and (page is None or i.get("page") == page)]


def ensure_cube():
    """The cube checks put items in the Horadric Cube (`item <code> cube`), which fails with "placing failed" when the
    character carries no cube (a fresh test character does not; an earlier check that removed it leaves none): give it one."""
    if not items(hstate(), "box"):
        H("item box inv")


def ground_count(code):
    """Items of this code lying on the ground (`h dump ground` lists every item unit; mode 3 / 5 = on the ground): the quest
    bonus drops land there (one per player)."""
    ok, lines = H("dump ground")
    return len([l for l in lines if l.startswith("ground ") and ("code=%s " % code) in l and re.search(r"mode=[35] ", l)])


def stat_of(lines):
    m = re.search(r"= (-?\d+)", lines[0]) if lines else None
    return int(m.group(1)) if m else None


def lockout_counts(st):
    m = re.search(r"refused=(\d+) clocks=(\d+)", st["plugin"])
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def goblins_counts(st):
    m = re.search(r"(\d+) spawned .*?(\d+) rolls", st["plugin"])
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def player_dead(p):
    """The server's player unit is dead: mode 0 / 17, or life 0."""
    life = str(p.get("life", "1")).split("/")[0]
    return p.get("mode") in (0, 17) or life == "0"


def revive_if_dead(timeout=20):
    """A dead test character (player mode 0 / 17) closes the game on `cheat goto` and ignores hits, menus and hiring. Returns True
    when it was dead.
    Two kinds of death. A real one (life 0, the client shows the death state): Esc is the respawn request (the plugin holds it
    back for 5 s), pressed every 3 s. A harness-made one: a check that sets the life stat (`stat player 6`) after the character
    died leaves the server unit in mode 17 with life above 0 while the client believes the character is alive (a screenshot shows
    it standing, Esc opens the pause menu instead and `state` stops answering for 15 s); no respawn request can come from the
    client then. Save and Exit + Play loads the character in the town, which is what a respawn does."""
    p = hstate()["player"]
    if not p or not player_dead(p):
        return False
    life = str(p.get("life", "0")).split("/")[0]
    g.log("the test character is dead (mode %s, life %s)" % (p.get("mode"), life))
    if life == "0":
        t0 = time.time()
        while time.time() - t0 < timeout:
            g.press("esc")
            time.sleep(3)
            st = hstate()
            if not st["player"]:  # `state` does not answer: Esc paused the game (the character was not dead for the client)
                break
            if not player_dead(st["player"]):
                return True
    p = hstate()["player"]
    if p and not player_dead(p):
        return True
    g.log("no respawn request is possible (the client does not know the death): Save and Exit + Play")
    leave_and_reenter(menu_open=not hstate()["player"])  # `state` silent: the pause menu is already open
    return True


# Shapeshift forms (states.txt `transform` 1 and Median's own): the bear, Treewarden, Wereowl and werewolf form states.
SHAPE_STATES = (140, 236, 278, 300)


def held_item():
    """(unit id, code) of the item on the player's cursor, None when the cursor is empty."""
    ok, lines = H("cursor")
    m = re.search(r"cursor id=(\d+) code=(\S+)", " ".join(lines))
    return (int(m.group(1)), m.group(2)) if m else None


def release_held_item():
    """An item held on the cursor makes the server unit busy (0x4249f0): skill casts are refused (`cast` code 1: no cast
    animation, no mana, no missile), an NPC click opens no menu, left clicks drop the item instead of attacking. A character
    saved while it holds an item (a check that aborted between a lift and a drop) comes back holding it; slot 1's
    MxlBarb did for a whole suite (2026-10-23: cotr, a unique left by an earlier uniquelimits run). Drops it (client packet
    0x17 + id, onto the ground at the player's feet). Returns the (id, code) dropped, None when the cursor was empty, and
    raises when the item cannot be put down."""
    held = held_item()
    if held is None:
        return None
    for _ in range(3):
        H("pkt 17 " + " ".join("%02x" % b for b in struct.pack("<I", held[0])))
        time.sleep(1.0)
        if held_item() is None:
            return held
    raise RuntimeError("the item %d (%s) on the cursor cannot be dropped" % held)


def clear_shape_states():
    """Takes the shapeshift form states off the player (a character left morphed by another lane's work: the form's
    skills, models and NPC / cast rules are not those of the class). Returns the state ids that were on."""
    on = []
    for s in SHAPE_STATES:
        ok, lines = H("hasstate %d" % s)
        if re.search(r"hasstate \d+: 1\b", " ".join(lines)):
            on.append(s)
            H("setstate player %d 0" % s)
    return on


# Median's stances (states.txt: way_of_the_spider 308, way_of_the_phoenix 309, way_of_the_gryphon 332, way_of_the_raven 783): a cast of an
# earlier check leaves them on; Phoenix adds mastery and max mana and every later mana test pays for it
# (meleenotarget: both clicks lost ~1540 mana in the full group2, skillscaling read a mastery of 10 that was set to 0)
# Not alignment (105): the test character carries it from the start; with its bit taken off (run 085517 of lane suite-main-060) the casts of
# replacedskills did not start (mode stayed 1) and the 2e9 hit of playerdeath did not land.
STANCE_STATES = (308, 309, 332, 783)


def clear_stance_states():
    on = []
    for s in STANCE_STATES:
        ok, lines = H("hasstate %d" % s)
        if re.search(r"hasstate \d+: 1\b", " ".join(lines)):
            on.append(s)
            H("setstate player %d 0" % s)
    return on


def right_panel_open():
    """The inventory (or stash / cube) panel is open: the dark-red banner of the right-hand panel, 1600 x 900 client (0.09 of the
    pixels of that strip; 0.00 on every scene screenshot of earlier runs, 0.04 for a cube-only panel)."""
    im = g.grab_client(g.need_window()).convert("RGB").crop((840, 100, 1260, 160))
    px = list(im.getdata())
    return sum(1 for r, gr, b in px if r > 50 and r > 2 * gr and r > 2 * b) > 0.03 * len(px)


def close_right_panel():
    """Closes the inventory panel with the `i` key when the banner shows (a toggle, so only when it is open). Returns True when it
    was open. A panel on the right half moves the player to the left of the screen: every check that clicks at the player's
    projected position (monster hover) and the Save and Exit path miss their targets."""
    if not right_panel_open():
        return False
    g.press("i")
    time.sleep(1.0)
    if right_panel_open():
        g.press("esc")  # a stash or cube panel: one Esc closes it and the inventory with it
        time.sleep(0.8)
    return True


def clean_start_state(label, report_dead=False):
    """The state a check needs the test character to be in: alive, in its own shape, nothing on the cursor. Repairs what it can and
    returns the notes of what it repaired (an empty list when the character was clean); a state it cannot repair raises. Called before
    the first check and before every check (the check that leaves a state behind shows up as the row of the next one)."""
    notes = []
    if revive_if_dead() and report_dead:  # a check that kills the character on purpose (deathcrash) is revived silently
        notes.append("the character was dead (revived)")
    forms = clear_shape_states()
    if forms:
        notes.append("shapeshift states %s were on (taken off)" % forms)
    stances = clear_stance_states()
    if stances:
        notes.append("stance states %s were on (taken off)" % stances)
    try:  # a check that left the character at 1 life point (soak run 2026-10-25, slot 3: scrollportals before monhover) lets the next monster kill it
        life, top = rd("player", 6), rd("player", 7)
        if top and life is not None and life < top // 2:
            setstat("player", 6, top)
            notes.append("life was %d of %d points (set to full)" % (life >> 8, top >> 8))
    except Exception as e:
        g.log("start state before %s: life test failed: %r" % (label, e))
    held = release_held_item()
    if held:
        notes.append("item %d (%s) was held on the cursor (dropped; it blocks skill casts and NPC menus)" % held)
    try:
        if close_right_panel():
            notes.append("the inventory panel was open (closed with `i`; it covers the right half of the client)")
    except Exception as e:  # no window grab: the check that needs the screen will say so
        g.log("start state before %s: panel test failed: %r" % (label, e))
    try:  # what the character wears: a check that leaves an item on shows up as the row of the next one (it changes mana, masteries, resistances)
        worn = sorted("%s@%s" % (it.get("code"), it.get("body")) for it in hstate()["items"] if it.get("page") == 255 and it.get("body"))
        if STATE.get("worn") is not None and worn != STATE["worn"]:
            notes.append("worn items changed since the check before: %s -> %s" % (STATE["worn"], worn))
        STATE["worn"] = worn
    except Exception as e:
        g.log("start state before %s: worn test failed: %r" % (label, e))
    try:  # Molten Core (1682) is a passive: its stat 297 turns the mana regeneration into the heat drain on any class
        heat = stat_of(H("stat player 297")[1]) or 0
        if heat > 0 and hstate()["player"].get("class") != 1:
            left = clear_heat_stat()
            notes.append("stat 297 (heat drain of Molten Core) was %d (taken off, now %s)" % (heat, left))
    except Exception as e:
        g.log("start state before %s: heat test failed: %r" % (label, e))
    try:  # the mana pool of a quiet character does not fall by itself: a pool that does hides the cost of every mana check
        dip = mana_idle_dip()
        if dip is not None and dip > MANA_DIP_LIMIT:
            notes.append("the mana pool fell by %d points in %.1f s with nothing cast (%s)" % (dip, MANA_DIP_WINDOW, mana_drain_evidence()))
    except Exception as e:
        g.log("start state before %s: mana test failed: %r" % (label, e))
    if notes:
        g.log("start state before %s: %s" % (label, "; ".join(notes)))
    return notes


def clear_heat_stat():
    """Take the heat drain off the character: `setskill <id> 0` only writes the base level, the passive stat 297 that Molten Core
    (1682) put on the character stays until the next stat recalculation, and with it the mana drain of plugin/src/heat.cpp. The stat
    is set to 0, and what is still left (the part that sits in the skill's stat list) is cancelled by a negative value of the unit's
    own stat. Returns the stat 297 afterwards."""
    _setskill(1682, 0)
    for _ in range(2):
        left = stat_of(H("stat player 297")[1]) or 0
        if left == 0:
            break
        H("stat player 297 set %d" % 0)
        rest = stat_of(H("stat player 297")[1]) or 0
        if rest:
            H("stat player 297 set %d" % -rest)
    return stat_of(H("stat player 297")[1])


MANA_DIP_LIMIT = 100  # points; the idle regeneration of a full pool is above the pool, so any fall is a drain
MANA_DIP_WINDOW = 1.2


def mana_idle_dip():
    """Points the player's mana falls in MANA_DIP_WINDOW seconds from a full pool with nothing cast (plugin `manamin`: the lowest and
    highest value of every server frame), None when the pool or the answer is missing."""
    full = rd("player", 9)
    if not full:
        return None
    setstat("player", 8, full)
    time.sleep(0.2)
    H("manamin reset")
    time.sleep(MANA_DIP_WINDOW)
    m = re.search(r"manamin min=(-?\d+) max=(-?\d+)", " ".join(H("manamin")[1]))
    return (int(m.group(2)) - int(m.group(1))) if m else None


def mana_drain_evidence():
    """What can drain a pool, for the note of a start state that shows it: the player states on, the monsters in reach, the worn items."""
    on = [s for s in range(1, 360) if "hasstate %d: 1" % s in " ".join(H("hasstate %d" % s)[1])]
    st = hstate()
    mons = ["%s@%s" % (m.get("class"), m.get("dist")) for m in st["mons"] if not m.get("npc")][:10]
    worn = sorted("%s@%s" % (it.get("code"), it.get("body")) for it in st["items"] if it.get("page") == 255 and it.get("body"))
    heat = stat_of(H("stat player 297")[1])
    return "states on %s; stat 297 (heat) %s; monsters %s; worn %s" % (on, heat, mons, worn)


def goto(area, timeout=40):
    """Move the character to an area: D2R's own `cheat goto` (debug mode) for the same act, the plugin's `level`
    (the NPC travel) across acts. Waits until `h state` says so."""
    revive_if_dead()
    for attempt in range(2):
        enable_debug()
        con("cheat goto %d" % area) if attempt == 0 else H("level %d" % area)
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(2)
            st = hstate()
            if st["player"].get("area") == area:
                time.sleep(2)
                return st
    return hstate()


def wait_menu(timeout=60):
    """The NPC menu opens when the NPC's speech has played; returns the `menu list` lines or None."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        guard()
        ok, lines = g.hcmd("menu list", 5)
        if ok:
            return lines
        time.sleep(3)
    return None


def npc_menu(npc_class, spawn=True, attempts=4):
    """Stand next to an NPC (spawn it when it is not loaded), talk, wait for the menu. Returns the menu lines.
    The menu opens when the NPC's speech has played, and the click that starts the speech can be lost (the first talk of a long
    speech, an NPC that is still walking, an earlier menu still open): every attempt closes what is open, talks again and waits
    a shorter time; a dead character (it cannot talk) is revived first."""
    revive_if_dead()
    for attempt in range(attempts):
        close_menu()
        ok, lines = H("interact %d" % npc_class)  # the town's own NPC: its speech ends with the menu
        if not ok and spawn:
            H("spawn %d" % npc_class)
            time.sleep(1)
            ok, lines = H("interact %d" % npc_class)
        if not ok:
            time.sleep(2)
            continue
        menu = wait_menu(30 if attempt == 0 else 15)
        if menu is not None:
            return menu
    return None


def npc_within(npc_class, reach=6):
    """True when an NPC of that class stands within `reach` of the character (`h state` lists the units around it)."""
    near = [m for m in hstate()["mons"] if m.get("class") == npc_class]
    return bool(near) and near[0].get("dist", 99) <= reach


def npc_menu_near(npc_class, attempts=3):
    """npc_menu() for NPCs that stand far from the town's arrival point (Gheed, Charsi, Akara: 70+ units, the walk of an `interact`
    can take longer than the menu wait or end at a wall): walk next to the NPC first (`moveto`, repeated), a copy of the NPC next
    to the character when the walk does not get there, then talk; when the menu still does not open the whole round is repeated
    with a copy (the client has to learn a new unit before it can talk to it). Returns the menu lines or None."""
    revive_if_dead()
    if hstate()["player"].get("area") != 1:
        goto(1)
    close_menu()
    for attempt in range(attempts):
        for _ in range(5):
            ok, _l = H("moveto nearest %d" % npc_class)
            if not ok:
                break  # not loaded
            time.sleep(4)
            if npc_within(npc_class):
                break
        if not npc_within(npc_class) or attempt > 0:
            H("spawn %d" % npc_class)  # out of reach (behind a wall) or not loaded: a copy next to the character
            time.sleep(4)
        menu = npc_menu(npc_class, attempts=2)
        if menu is not None:
            return menu
    return None


def close_menu():
    g.hcmd("menu cancel", 5)


def kill_all_near():
    for _ in range(6):
        ok, _l = H("kill nearest")
        if not ok:
            break


# ------------------------------------------------------------------ results


class Result:
    def __init__(self, name, status, note, shots=(), log=()):
        self.name, self.status, self.note, self.shots, self.log = name, status, note, list(shots), list(log)


RESULTS = []


def add(name, status, note, shots=(), log=()):
    RESULTS.append(Result(name, status, note, shots, log))
    g.log("CHECK %s: %s %s" % (name, status, note))


def sh(name):
    return os.path.basename(g.shot(name))


def need_game():
    if not STATE["in_game"]:
        return False
    st = hstate()
    return st["ok"]


# ------------------------------------------------------------------ checks


def check_mxl():
    if not need_game():
        return add("mxl console command", "BLOCKED", "not in a game")
    txt = mxl_text()
    wanted = ["states fix", "level types", "calc codes", "skill functions", "item spells", "missile hits", "mana costs",
              "cube conditions", "craft flags", "act 1 quests", "dungeon lockout", "goblins on", "item events on",
              "npc actions on", "skill tree on", "corpse pickup on", "required level on", "hardcore death on", "teleport gold on", "skill afford on"]
    missing = [w for w in wanted if w not in txt]
    add("`mxl` console command output", "PASS" if not missing else "FAIL",
        "console_text('mxl') returned %d lines with all %d feature lines; first: %s" % (
            len(txt.splitlines()), len(wanted), txt.splitlines()[0][:90] if txt else "-") if not missing
        else "missing: %s" % missing, [sh("mxl_town")], txt.splitlines())


def check_goblins():
    name = "Treasure goblin spawns in the Blood Moor after a kill (MXL_GOBLINS_FORCE=1)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    st = goto(2)
    if st["player"].get("area") != 2:
        return add(name, "BLOCKED", "could not reach the Blood Moor (area %s)" % st["player"].get("area"))
    s0, r0 = goblins_counts(st)
    m = mxl_mark()
    log = []
    for rnd in range(4):
        H("spawn 18 2")
        H("kill nearest 18")
        ok, l = H("kill nearest 18")
        log += l
        time.sleep(18)  # the tick runs every 375 frames (15 s)
        st = hstate()
        s1, r1 = goblins_counts(st)
        if s1 is not None and s0 is not None and s1 > s0:
            break
    gob = [mm for mm in st["mons"] if mm.get("class", 0) >= 2700]
    lines = [ln for ln in mxl_lines_since(m) if "goblin" in ln and "spawned" in ln]
    shots = [sh("goblin_scene")]
    add(name, "PASS" if (s1 or 0) > (s0 or 0) else "FAIL",
        "`h state` counters: spawned %s -> %s, rolls %s -> %s; goblin monsters alive near the player: %s; log: %s" % (
            s0, s1, r0, r1, [(mm["class"], mm["dist"]) for mm in gob], lines[0][-80:] if lines else "-"),
        shots, lines + [st["plugin"]])
    goto(1)
    kill_all_near()


def check_respec():
    name = "Akara respec after Den of Evil (Reset Stat/Skill Points)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    H("quest 1 0 set")   # Den of Evil done
    H("quest 41 1 set")  # its respec reward is waiting
    base0 = stat_of(H("stat player 0")[1])
    base4 = stat_of(H("stat player 4")[1])
    H("stat player 0 set %d" % (base0 + 60))   # 60 points "spent" on strength
    # the read-back can differ from the value set when the test character wears strength items left by earlier runs:
    # compare against what the game reports, not against fixed numbers
    spent = stat_of(H("stat player 0")[1])
    base_stats = [stat_of(H("stat player %d" % i)[1]) for i in range(4)]  # strength, energy, dexterity, vitality before the respec
    menu = npc_menu(148)
    if not menu:
        return add(name, "BLOCKED", "Akara's menu did not open (menu list: %s)" % menu)
    shot = sh("respec_menu")
    plugin_lines = [ln for ln in menu if "handler=plugin" in ln]
    if not plugin_lines:
        return add(name, "FAIL", "no plugin line in Akara's menu: %s" % menu, [shot], menu)
    idx = int(re.search(r"line (\d+)", plugin_lines[0]).group(1))
    m = mxl_mark()
    # npcext PromptConfirm: the click opens D2R's Yes / No page and sends nothing; No ends it with the stats untouched
    ok, ml = H("menu %d" % idx)
    time.sleep(1.5)
    _, c1 = H("menu confirm")
    confirm_shot = sh("respec_confirm")
    asked = ok and any("open" in ln for ln in c1)
    _, held0 = H("stat player 0")
    ok_no, no_out = H("menu no")
    time.sleep(1)
    _, held1 = H("stat player 0")
    declined_lines = [ln for ln in mxl_lines_since(m) if "npc actions" in ln]
    declined = (ok_no and stat_of(held0) == spent and stat_of(held1) == spent
                and any("declined" in ln for ln in declined_lines) and not any("done" in ln for ln in declined_lines))
    menu = npc_menu(148)
    plugin_lines = [ln for ln in (menu or []) if "handler=plugin" in ln]
    if not plugin_lines:
        return add(name, "FAIL", "after No, the menu did not come back with the plugin line: %s" % menu, [shot, confirm_shot], ml + no_out)
    idx = int(re.search(r"line (\d+)", plugin_lines[0]).group(1))
    m = mxl_mark()
    unused0 = stat_of(H("stat player 4")[1])
    ok, ml2 = H("menu %d" % idx)
    time.sleep(1.5)
    _, c2 = H("menu confirm")
    ok, yes_out = H("menu yes")
    time.sleep(1)
    _, after0 = H("stat player 0")
    _, after4 = H("stat player 4")
    after_stats = [stat_of(H("stat player %d" % i)[1]) for i in range(4)]
    lines = [ln for ln in mxl_lines_since(m) if "npc actions" in ln]
    s0 = stat_of(after0)
    s4 = stat_of(after4)
    _, q = H("quest 41 dump")
    done = any("done" in ln for ln in lines)
    # Every base stat goes back to the class start (Barbarian: strength 30, ...) and every point spent comes back as unused points:
    # the refund is the sum over all four stats, not strength alone (a character that has spent points on dexterity, vitality and
    # energy gets those back too). Item bonuses sit on both sides of a stat's difference, so before - after is the base refund.
    refunded = sum(b - a for b, a in zip(base_stats, after_stats)) if None not in base_stats + after_stats else None
    asked2 = any("open" in ln for ln in c2)
    add(name, "PASS" if (asked and declined and asked2 and ok and done and s0 is not None and s0 < spent and refunded is not None
                         and refunded >= 60 and s4 == unused0 + refunded) else "FAIL",
        "menu lines %s; the click opens the Yes / No page (%s) and No leaves strength at %s (%s); after Yes strength %s -> %s "
        "(Barbarian start 30), stats 0-3 %s -> %s, unused stat points %s -> %s (%s refunded over the four stats); log `%s`; quest 41 %s" % (
            [ln.strip() for ln in menu[1:]], asked, spent, declined, spent, s0, base_stats, after_stats, unused0, s4, refunded,
            lines[-1][-60:] if lines else "none", q[0]),
        [shot, confirm_shot], menu + ml + c1 + no_out + ml2 + c2 + yes_out + lines)
    close_menu()
    for i, v in enumerate(base_stats):  # the respec reset every stat and raised the unused points: the saved test character keeps its numbers
        if v is not None:
            H("stat player %d set %d" % (i, v))
    H("stat player 4 set %d" % base4)


def messages_sent():
    m = re.search(r"client messages .*\(sent (\d+), failed (\d+)\)", mxl_text())
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def check_trophy():
    """Median's trophies (misc2 InteractString): the tooltip says "Right click to reveal trophy challenge" and the right
    click prints the challenge as chat lines (plugin/src/item_spells.cpp, mxl_items.h Trophies)."""
    name = "Trophy items: hover text, right click reveals the challenge (misc2 InteractString)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    H("remove a56 5")
    ok, made = H("item a56 inv")
    if not ok:
        return add(name, "BLOCKED", "could not create the Heart of Azmodan (a56): %s" % made)
    sent0, failed0 = messages_sent()
    g.press("i")  # inventory (background key message)
    time.sleep(1.5)
    shots = [sh("trophy_inventory")]
    # the item lands in the first free cell of the 15 x 10 inventory grid (a free cell right of the tall items: the HD panel puts it near 0.841, 0.580): hover it with the plugin's virtual cursor
    for n, (fx, fy) in enumerate(((0.841, 0.580), (0.841, 0.592))):
        g.click(fx, fy, move_only=True)
        time.sleep(1.0)
        shots.append(sh("trophy_hover%d" % n))
    g.press("i")
    time.sleep(0.5)
    ok, used = H("use a56")
    time.sleep(1.5)
    shots.append(sh("trophy_revealed"))
    sent1, failed1 = messages_sent()
    ok2, again = H("use a56")  # the trophy is kept: a second reveal works
    time.sleep(0.5)
    sent2, failed2 = messages_sent()
    _, held = H("state")
    kept = any("a56" in ln for ln in held)
    lines = [ln for ln in used if "pSpell 17" in ln]
    add(name, "PASS" if (ok and ok2 and lines and "kept" in lines[0] and sent0 is not None and sent1 - sent0 >= 8
                        and failed1 == failed0 and sent2 - sent1 >= 8 and kept) else "FAIL",
        "`use a56`: %s; client messages sent %s -> %s -> %s (failed %s -> %s), the item is kept: %s. Hover text and the "
        "printed lines are read from the screenshots (trophy_hover*.png, trophy_revealed.png)" % (
            used[0] if used else "-", sent0, sent1, sent2, failed0, failed2, kept), shots, made + used + again)
    H("remove a56 5")


def skill_usable(skill):
    """The game's usability code (`h skills`, 0x33f360) of one skill of the player, None when he has not got it."""
    ok, lines = H("skills")
    for ln in lines:
        m = re.match(r"skill id=(\d+) level=\d+ mode=\d+ owner=-?\d+ usable=(\d+)", ln)
        if m and int(m.group(1)) == skill:
            return int(m.group(2))
    return None


STEADY_AIM_STATE = 558  # states.txt sk1296_state: Hunter's Steady Aim (Heartseeker needs it, restrict 5)


def aim_clean():
    """No Steady Aim left over: the counter (stat 220 layer 5) and its state. The earlier check's last cast of Heartseeker may not
    have spent the counter, and a leftover state makes Heartseeker usable when a check expects it restricted."""
    H("stat player 220 5 set 0")
    H("setstate player %d 0" % STEADY_AIM_STATE)


def tough_target(cls):
    """A spawned monster that survives a long bow fight: its life and maximum life set to the engine's top. Returns its unit id. The
    shots of a level 150 character kill an ordinary class 3 monster with the first arrow, and the later casts then find only the
    town NPC next to the arrival point (`cast ... nearest` takes the nearest monster of any kind)."""
    mid = spawn_id(cls)
    if mid is not None:
        setstat("mon:%d" % mid, 7, BIG_LIFE)
        setstat("mon:%d" % mid, 6, BIG_LIFE)
    return mid


def check_steadyaim():
    """Hunter's Steady Aim (docs/median-rules-audit.md SK10): Steady Shot (D2R 1368) builds stat 220 layer 5 on state
    sk1296_state one per shot up to the cap; Heartseeker (352, restrict 5: needs the state) is refused without it
    (plugin/src/skill_restrict.cpp), spends one charge per cast and drops the state at the last one."""
    nm = "Steady Aim: Steady Shot builds the counter, Heartseeker needs it and spends it (restrict 5)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(2)  # Blood Moor
    kill_all_near()
    H("packclear")  # an unequip into a full backpack fails and the bow never gets into the hand
    st0 = hstate()["player"]
    cls0 = st0.get("class")
    log = []
    for cmd in ("class 5", "stat player 0 set 400", "stat player 2 set 400", "unequip rhand", "equip 163 rhand",
                "unequip lhand", "equip aqv lhand", "setskill 1368 5", "setskill 352 5"):
        ok, lines = H(cmd)
        log += lines
    counter = lambda: stat_of(H("stat player 220 5")[1])
    aim_clean()
    before = skill_usable(352)
    first = counter()
    tough_target(3)
    seen = []
    for _ in range(4):
        H("cast 1368 nearest")
        time.sleep(2.5)
        seen.append(counter())
    during = skill_usable(352)
    ok, lines = H("cast 352 nearest")
    log += lines
    time.sleep(2.5)
    after_one = counter()
    for _ in range(6):
        if not counter():
            break
        H("cast 352 nearest")
        time.sleep(2.5)
    end = counter()
    after = skill_usable(352)
    kill_all_near()
    aim_clean()
    if cls0 is not None:
        H("class %d" % cls0)
    good = (before == 4 and first == 0 and seen == [1, 2, 3, 4] and during == 0 and after_one is not None
            and 0 < after_one < seen[-1] + 1 and end == 0 and after in (1, 4))  # 1 = Heartseeker's cooldown answers before the restriction
    add(nm, "PASS" if good else "FAIL",
        "Heartseeker usability (4 = restricted) before the first shot %s, counter %s; after Steady Shot x4 the counter reads %s "
        "and Heartseeker %s; one Heartseeker leaves %s; spent to %s and Heartseeker %s (4 restricted, or 1 while its cooldown runs)" % (
            before, first, seen, during, after_one, end, after), (), log)


def check_restrictitems():
    """Restrict modes 3-7 on item-triggered skills (D2Sigma applies them on the player's cast path only: its restrict test
    0x6fd9f590 is called from D2Common 10787 alone, and the item event path 0x6fd114f0 -> 0x6fcc19a0 never reaches it; D2R's twin
    0x33f6a0 on the item path knows modes 0 to 2 only, so the port leaves modes 3 to 7 unrestricted there, as Median does).
    Heartseeker (352, restrict 5, needs Steady Aim's state) is refused for the player's own cast without the state (usable 4),
    yet an item with a "cast on kill" of it (stat 376, the item event registry's function 20 -> 0x5896e0 -> 0x589930) casts it
    both without and with the state: the handler is reached with the skill and its missile appears."""
    nm = "Restrict modes 3-7 on item-triggered skills: the cast path refuses Heartseeker, an item's cast on kill does not (as Median)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(2)  # Blood Moor
    kill_all_near()
    H("packclear")  # an unequip into a full backpack fails and the bow never gets into the hand
    st0 = hstate()["player"]
    cls0 = st0.get("class")
    log, notes = [], []
    for cmd in ("class 5", "stat player 0 set 400", "stat player 2 set 400", "unequip rhand", "equip 163 rhand",
                "unequip lhand", "equip aqv lhand", "setskill 1368 5", "setskill 352 5", "unequip lring"):
        log += H(cmd)[1]
    counter = lambda: stat_of(H("stat player 220 5")[1])

    def proc():
        """One cast on kill of Heartseeker level 5 from a ring: (handler reached, missiles seen)."""
        H("unequip lring")
        H("equip rin 376:%d=100 lring" % (352 * 64 + 5))
        m = spawn_id()
        time.sleep(2)  # a monster that was just spawned is not a valid target yet
        H("missiles reset")
        H("evtrace fire 9 player m%d" % m)
        _o, lm = H("missiles")
        _o2, lk = H("evtrace calls")
        log.extend(lm + lk)
        last = re.search(r"last cast on kill: skill (-?\d+) level (-?\d+)", " ".join(lk))
        seen = re.search(r"seen=(\d+)", " ".join(lm))
        H("kill nearest")
        H("unequip lring")
        return (last is not None and (int(last.group(1)), int(last.group(2))) == (352, 5)), int(seen.group(1)) if seen else None

    aim_clean()
    usable0 = skill_usable(352)
    counter0 = counter()
    reached0, seen0 = proc()
    notes.append("without Steady Aim (counter %s): player cast usable code %s (4 = restricted); item cast on kill reached %s, missiles seen %s" % (
        counter0, usable0, reached0, seen0))
    tough_target(3)
    for _ in range(4):
        H("cast 1368 nearest")
        time.sleep(2.5)
    counter1 = counter()
    usable1 = skill_usable(352)
    reached1, seen1 = proc()
    notes.append("with Steady Aim (counter %s): player cast usable code %s; item cast on kill reached %s, missiles seen %s" % (
        counter1, usable1, reached1, seen1))
    for _ in range(6):  # spend the counter as the steadyaim check does
        if not counter():
            break
        H("cast 352 nearest")
        time.sleep(2.5)
    kill_all_near()
    aim_clean()
    if cls0 is not None:
        H("class %d" % cls0)
    # the counter only has to exist for the restriction to lift (Steady Shot's own count 1..4 is the steadyaim check's subject: a weak
    # target can die after the first shot and the later shots find no enemy)
    good = (usable0 == 4 and not counter0 and reached0 and seen0 and counter1 and counter1 >= 1 and usable1 == 0 and reached1 and seen1)
    add(nm, "PASS" if good else "FAIL", " | ".join(notes), (), log)


def check_heat():
    """The Fire Sorceress's Heat (docs/median-rules-audit.md SK11): Molten Core (D2R 1682, a class skill) puts the heat loss
    rate in stat 297; with it set the mana bar drains outside a town instead of regenerating (plugin/src/heat.cpp), Flamefront
    (482) puts a negative rate on the caster for a moment, which builds heat, and a town stops the drain."""
    nm = "Heat: stat 297 drains the mana bar outside town, Flamefront builds it, a town holds it"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(2)
    kill_all_near()
    cls0 = hstate()["player"].get("class")
    log = []
    # Molten Core is a passive: left at level 5 it keeps stat 297 on the character, and every later check in the same game then
    # loses mana to the heat drain (p4-stability: npcheal / soulstealer / meleenotarget saw the bar fall 740-864 points in 1.2 s
    # with no click). Remember the levels and put them back at the end.
    before = {}
    for sid in (482, 1682):
        m = re.search(r"skill id=%d level=(-?\d+)" % sid, " ".join(H("skills")[1]))
        before[sid] = int(m.group(1)) if m else 0
    for cmd in ("class 1", "setskill 482 5", "setskill 1682 5"):
        ok, lines = H(cmd)
        log += lines
    mana = lambda: stat_of(H("stat player 8")[1])
    rate = stat_of(H("stat player 297")[1])
    # a full bar: the drain of one tick is a share of the MAXIMUM mana (heat_logic.h: base = max mana / regeneration frames, times
    # the rate), so a fixed 25600 (100 points) on the level 150 character of slot 1 (6300 mana) was gone within one tick
    maxmana = rd("player", 9) or 0  # raw (x256), the unit of stat 8
    full = max(25600, maxmana)
    H("stat player 8 set %d" % full)
    top = mana()
    time.sleep(2.5)
    mid = mana()
    time.sleep(2.5)
    low = mana()
    for _ in range(12):  # run it dry (the floor is 0)
        if mana() == 0:
            break
        time.sleep(2)
    empty = mana()
    H("spawn 3 1")
    peak = empty
    H("cast 482 nearest")
    seen_negative = False
    for _ in range(8):
        peak = max(peak, mana() or 0)
        seen_negative = seen_negative or (stat_of(H("stat player 297")[1]) or 0) < 0
    kill_all_near()
    goto(1)  # Rogue Encampment
    H("stat player 8 set 12800")
    time.sleep(3)
    town = mana()
    goto(2)
    H("stat player 8 set %d" % full)
    if cls0 is not None:
        H("class %d" % cls0)
    _setskill(482, before[482])
    if before[1682] > 0:
        _setskill(1682, before[1682])
        left = stat_of(H("stat player 297")[1])
    else:
        left = clear_heat_stat()
    good = (rate is not None and rate > 0 and top is not None and top >= full // 2 and mid is not None and mid < top and low is not None and low < mid
            and empty == 0 and peak > 0 and seen_negative and town == 12800 and (not left or before[1682] > 0))
    add(nm, "PASS" if good else "FAIL",
        "stat 297 = %s; mana x256 from full: %s -> %s (2.5 s) -> %s (5 s) -> %s (empty, floor 0); Flamefront at empty: peak %s, "
        "stat 297 went negative: %s; in town (set to 12800, 3 s later): %s; stat 297 after the skill levels went back (%s): %s" % (
            rate, top, mid, low, empty, peak, seen_negative, town, before, left), (), log)


def check_trophytimer():
    """Trophy challenge windows (docs/median-rules-audit.md CR4, DC6; plugin/src/trophy_timer.cpp). The Heart of Sin recipe
    (assassin row 6377: Azmodan's Heart a56, unique 27, challenge code 167166 in stat 378) must match within 10 s of the code
    appearing, be refused later, and be refused after the player left the area or died. Control: the stat still holds the
    code in every refused case, so the refusal is the window, not the stat compare."""
    nm = "Trophy timer: cube in time passes, too late / another zone / dead is refused"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(1)
    H("packclear")  # room for the cube and the cube items (a full backpack makes `item` fail with "placing failed")
    if not items(hstate(), "box"):  # the character may not have found its cube yet
        H("item box inv")
    H("cubeclear")
    cls0 = hstate()["player"]["class"]
    H("class 6")  # the recipe is for assassins
    log, res = [], {}

    def attempt(label):
        H("flag player 9 clear")  # the recipe sets it and the follow-up recipe 6358 (same item) opens with it
        H("cubeclear")
        H("item a56 cube uniq=27")
        ok, lines = H("cubecraft")
        r = re.search(r"recipe (\d+)", lines[0]) if lines else None
        res[label] = (ok and r is not None and r.group(1) == "6377", lines[0][:60] if lines else "-")
        log.extend(lines)
        H("cubeclear")

    def start():
        H("stat player 378 set 0")
        time.sleep(1)
        H("stat player 378 set 167166")
        time.sleep(1.5)  # the frame hook samples the players every 5 frames

    try:
        start()
        attempt("in time")
        start()
        time.sleep(11.5)
        held_late = stat_of(H("stat player 378")[1])
        attempt("too late")
        start()
        goto(2)
        goto(1)
        held_zone = stat_of(H("stat player 378")[1])
        attempt("other zone")
        goto(2)  # a town does not let a hit kill
        atk = spawn_attacker(1)
        start()
        H("stat player 6 set 25600")
        H("hit player phys 2000000000 %s" % (atk or ""))  # from a spawned monster; 1/256 life points
        for _ in range(12):  # the death animation runs a second or two
            time.sleep(1)
            if hstate()["player"].get("mode") in (0, 17):
                break
        died = hstate()["player"].get("mode") in (0, 17)
        time.sleep(3)  # the sampler sees the dead player
        revive_if_dead()
        goto(1)
        held_dead = stat_of(H("stat player 378")[1])
        attempt("died")
    finally:
        H("stat player 378 set 0")
        H("class %d" % cls0)
        H("cubeclear")
    held = (held_late, held_zone, held_dead)
    good = (res["in time"][0] and not res["too late"][0] and not res["other zone"][0] and not res["died"][0]
            and died and all(v == 167166 for v in held))
    add(nm, "PASS" if good else "FAIL",
        "recipe 6377 matched: in time %s; 12 s later %s; after goto 2 and back %s; after dying %s (the character died: %s; stat 378 "
        "still %s in the refused cases)" % (res["in time"][0], res["too late"][0], res["other zone"][0], res["died"][0], died, held),
        (), log)


def check_cain():
    name = "Cain crafting materials line (bug #23)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    m = mxl_mark()
    menu = npc_menu(265)
    time.sleep(1)
    s = sh("cain_menu")
    lines = [ln for ln in mxl_lines_since(m) if "npc actions" in ln]
    full = [ln for ln in lines if "full" in ln]
    # The popup is read from the screenshot (top left of the window: DECKARD CAIN / TALK / CRAFTING MATERIALS / CANCEL);
    # the script can only assert the log and that the menu opened.
    add(name, "PASS" if (menu and not full) else "FAIL",
        "menu opened by `h interact 265`: %s; no `menu record is full` log line: %s. Popup text must be read from the "
        "screenshot (cain_menu.png)" % (bool(menu), not full), [s], (menu or []) + lines)
    close_menu()


def check_cain_submenu():
    """Median's Cain page: a click on 'crafting materials' opens the submenu of the materials whose requirement holds
    (the server's plugin message 'N' makes the client rebuild the list; plugin/src/npc_actions.cpp)."""
    name = "Cain crafting materials: the click opens a submenu with the open entries"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    H("stat player 7 set 20000000")
    H("stat player 6 set 20000000")
    H("quest 4 0 set")  # Search for Cain done: the cube entry's requirement (the page needs one open entry)
    H("remove box 10")  # the entry shows only while the player lacks the cube
    menu = npc_menu(265)
    if not menu:
        return add(name, "FAIL", "Cain's menu did not open")
    # the menu flag is set when the talk starts; the client builds the list (and the plugin adds its line) when the speech ends (a first talk takes up to ~30 s)
    t0 = time.time()
    while time.time() - t0 < 240 and not any("handler=plugin" in x for x in menu):
        time.sleep(1)
        ok0, again = g.hcmd("menu list", 5)
        menu = again if ok0 else menu
    plugin_idx = [int(re.search(r"line (\d+)", x).group(1)) for x in menu if "handler=plugin" in x]
    if not plugin_idx:
        return add(name, "FAIL", "no plugin line in Cain's menu after the speech: %s" % menu, [sh("cain_submenu")], menu)
    before = len([l for l in menu if "line " in l])
    shot0 = sh("cain_menu_page")
    ok, l = H("menu %d" % plugin_idx[0])
    ok2, after = False, None
    for attempt in range(2):  # the client rebuilds the list when the server's plugin message arrives: wait for it, ask once more when it did not
        for _ in range(8):
            time.sleep(1.5)
            ok2, after = g.hcmd("menu list", 5)
            if ok2 and after != menu:
                break
        if ok2 and after != menu:
            break
        if attempt == 0:
            ok, l = H("menu %d" % plugin_idx[0])
    s = sh("cain_submenu")
    n_after = len([x for x in (after or []) if "line " in x])
    same = after == menu
    if ok2 and n_after >= 1 and not same:
        ok3, l3 = H("menu 0")  # the first entry: the Horadric Cube
        time.sleep(2)
        got = len(items(hstate(), "box"))
        add(name + " (entry gives the item)", "PASS" if got >= 1 else "FAIL",
            "`menu 0` in the submenu: %s; Horadric Cube (box) items now: %d" % (ok3, got), [sh("cain_entry")], l3 or [])
    add(name, "PASS" if (ok and ok2 and n_after >= 1 and not same) else "FAIL",
        "menu lines before %d; click on the plugin line: %s; menu open after: %s with %d lines (the list changed: %s). Entry texts must be "
        "read from the screenshots (cain_menu_page.png: Talk / crafting materials, cain_submenu.png: the entries)" % (before, ok, ok2, n_after, not same),
        [shot0, s], (menu or []) + (l or []) + (after or []))
    close_menu()


def check_heart():
    name = "Griswold's Heart from Akara after Cain (quest 4 bit 1)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    H("quest 4 1 set")
    H("packclear")  # room in the backpack: the Heart would be dropped on the floor otherwise
    H("remove 600 6")   # earlier runs' hearts
    H("remove rin 6")
    st0 = hstate()
    n0 = len(items(st0, "600"))
    ok0, _l0 = H("interact 148")
    if not ok0:
        H("spawn 148")
        H("interact 148")
    ok, ml = H("msg 148 0x76")
    for _ in range(15):  # (Akara's own speech sends the same message when it ends)
        time.sleep(2)
        st1 = hstate()
        if items(st1, "600"):
            break
    new = [i for i in items(st1, "600") if i["id"] not in [j["id"] for j in items(st0, "600")]]
    ring = [i for i in items(st1, "rin") if i["id"] not in [j["id"] for j in items(st0, "rin")]]
    _, q = H("quest 4 dump")
    snd = reward_stats()  # Akara's reward message 0x61 plays item_lightarmor (230) on the client
    if not (snd and snd[3] == 230):
        time.sleep(2)
        snd = reward_stats()
    add(name, "PASS" if (new and new[0].get("unique") == 69 and snd and snd[0] and snd[2] == 0x61 and snd[3] == 230) else "FAIL",
        "after `h msg 148 0x76`: new item(s) with base code 600: %s (unique index %s, Griswold's Heart = 69), vanilla ring "
        "reward: %s; quest 4 bits %s; client reward sound (hook, played, message, row) %s" % (len(new), new[0].get("unique") if new else "-", bool(ring), q[0], snd),
        [sh("heart")], ["before: %s" % [(i["id"], i["page"], i.get("unique")) for i in items(st0, "600")], "after: %s" % [(i["id"], i["page"], i.get("unique")) for i in items(st1, "600")]] + ml + [x for x in mxl_lines_since(0)[-6:]])
    close_menu()


def check_catalyst():
    name = "Andariel catalyst of disenchantment (Normal), not twice; Warriv re-issue"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    H("remove 3o[ 5")
    H("quest 47 0 clear")  # the plugin's "catalyst handed out" flag lives in the character's quest record: clear it
    H("difficulty 0")
    H("spawn 156")
    ok1, l1 = H("kill nearest 156")
    time.sleep(1)
    st1 = hstate()
    n1 = len(items(st1, "3o[")) + ground_count("3o[")
    H("spawn 156")
    H("kill nearest 156")
    time.sleep(1)
    st2 = hstate()
    n2 = len(items(st2, "3o[")) + ground_count("3o[")
    H("remove 3o[ 5")
    H("spawn 155")
    ok3, l3 = H("interact 155")
    time.sleep(2)
    st3 = hstate()
    n3 = len(items(st3, "3o["))
    _, q = H("quest 47 dump")
    ok = ok1 and n1 == 1 and n2 == 1 and n3 == 1
    add(name, "PASS" if ok else "FAIL",
        "catalysts in the inventory or on the ground: after kill 1 %d, after kill 2 %d (must stay 1), after removing it and talking to Warriv "
        "%d (re-issued); flag quest 47 %s" % (n1, n2, n3, q[0]), [sh("catalyst")], l1 + l3)
    close_menu()


def check_lockout():
    name = "Dungeon lockout: entry refused by level/difficulty (Normal level 1, portal to level 251)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    H("difficulty 0")
    st = hstate()
    r0, c0 = lockout_counts(st)
    H("item b60X")
    ok, l = H("use b60X")
    time.sleep(1.5)
    ok2, l2 = H("enter nearest")
    time.sleep(1.5)
    st1 = hstate()
    r1, c1 = lockout_counts(st1)
    add(name, "PASS" if (ok and r1 == (r0 or 0) + 1 and st1["player"]["area"] == 1) else "FAIL",
        "`use b60X` opened the portal (%s); `enter nearest`: %s; counters in `h state`: refused %s -> %s, clocks %s -> %s, "
        "still in area %s" % (ok, l2[0] if l2 else "-", r0, r1, c0, c1, st1["player"]["area"]), [sh("lock_normal")], l + l2)


def _qbits(q):
    """Bits 0-15 of quest q as a string of 0 / 1 (`h quest <q> dump`)."""
    ok, l = H("quest %d dump" % q)
    m = re.search(r"bits0-15 ([01]{16})", l[0]) if l else None
    return m.group(1) if m else None


def _qrestore(q, bits):
    for i, ch in enumerate(bits or ""):
        H("quest %d %d %s" % (q, i, "set" if ch == "1" else "clear"))


def check_lockquest():
    """Median's quest-table condition of the warp test (D2Sigma 0x5d810; leveldefs QuestFlagEx): level 73 (Duriel's Lair)
    names quest 13. `h lockcheck` asks the plugin's warp test for the verdict without moving anybody."""
    name = "Dungeon lockout: quest-table condition (level 73 needs quest 13: any of bits 1, 0, 0xe, 0xf)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    H("difficulty 0")
    saved = _qbits(13)
    if saved is None:
        return add(name, "BLOCKED", "could not read quest 13")
    notes, ok_all = [], True

    def verdict(level):
        ok, l = H("lockcheck %d" % level)
        m = re.search(r"= (\w+)", l[0]) if l else None
        return m.group(1) if m else "?"

    try:
        for b in (0, 1, 0xe, 0xf):
            H("quest 13 %d clear" % b)
        v0 = verdict(73)
        ok_all &= v0 == "quest"
        notes.append("no bits: %s (want quest)" % v0)
        for b in (1, 0, 0xe, 0xf):
            H("quest 13 %d set" % b)
            v = verdict(73)
            ok_all &= v == "allow"
            notes.append("bit %#x: %s" % (b, v))
            H("quest 13 %d clear" % b)
        v1 = verdict(157)  # butcher_s_lair: names no quest, must never be the quest verdict
        ok_all &= v1 != "quest"
        notes.append("level 157 (no quest): %s" % v1)
    finally:
        _qrestore(13, saved)
    add(name, "PASS" if ok_all else "FAIL", "; ".join(notes))


def check_tower():
    """Median's a1q5 guard (D2Sigma 0x9e8b0) on D2R's quest 5 kill handler: for a killer with quest 5 bit 0, 0xe or 0xf set
    the hook skips the vanilla handler. A Countess spawned by the harness is not on quest 5's unit list (the kill event
    never reaches the handler), so `h towerprobe` asks the hook's decision directly; the hook itself is only reached by the
    natural Countess in the Tower Cellar (docs/unported.md)."""
    name = "Forgotten Tower: quest 5 guard decides skip once quest 5 is done (towerprobe)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    H("difficulty 0")
    saved = _qbits(5)
    if saved is None:
        return add(name, "BLOCKED", "could not read quest 5")

    def probe():
        ok, l = H("towerprobe")
        m = re.search(r"skip=(\d)", l[0]) if l else None
        return int(m.group(1)) if m else None

    notes, ok_all = [], True
    try:
        H("spawn 45")
        for c in (0, 0xe, 0xf):
            H("quest 5 %d clear" % c)
        v = probe()
        ok_all &= v == 0
        notes.append("quest 5 open: skip=%s (want 0)" % v)
        for b in (0, 0xe, 0xf):
            for c in (0, 0xe, 0xf):
                H("quest 5 %d clear" % c)
            H("quest 5 %d set" % b)
            v = probe()
            ok_all &= v == 1
            notes.append("bit %#x set: skip=%s (want 1)" % (b, v))
        H("kill nearest 45")
    finally:
        _qrestore(5, saved)
    add(name, "PASS" if ok_all else "FAIL", "; ".join(notes))


def check_lockout_clock():
    """Hell rules in a Hell dungeon: god mode so the test character survives (see god())."""
    god(True)
    try:
        _check_lockout_clock()
    finally:
        god(False)


def _check_lockout_clock():
    n1 = "Dungeon lockout: clock starts on entry; re-entry inside the lock time (Hell rules, level 253 infernal_cave_2, 60 s)"
    n2 = "Dungeon lockout: level sealed after the lock time"
    if not need_game():
        add(n1, "BLOCKED", "not in a game")
        return add(n2, "BLOCKED", "not in a game")
    goto(1)
    lvl0 = hstate()["player"]["level"]
    H("difficulty 2")
    H("stat player 12 set 125")
    H("stat player 7 set 20000000")
    H("stat player 6 set 20000000")
    H("item b62X")
    ok, l = H("use b62X")
    r0, c0 = lockout_counts(hstate())

    def enter_portal():
        for _ in range(3):  # the portal object needs a frame or two before it works
            time.sleep(2)
            ok, ll = H("enter nearest")
            if ll and "moved" in ll[0]:
                return True, ll
        return False, ll

    moved, ll = enter_portal()
    t0 = time.time()
    time.sleep(4)
    st1 = hstate()
    r1, c1 = lockout_counts(st1)
    a1 = st1["player"].get("area")
    shots = [sh("lock_hell_inside")]
    goto(1)
    moved2, ll2 = enter_portal()
    time.sleep(3)
    st2 = hstate()
    r2, c2 = lockout_counts(st2)
    a2 = st2["player"].get("area")
    goto(1)
    ok1 = moved and a1 == 253 and c1 == (c0 or 0) + 1 and moved2 and r2 == r1
    add(n1, "PASS" if ok1 else "FAIL",
        "Hell rules (`h difficulty 2`, level 125): entry %s (area %s), counters (refused, clocks) %s/%s -> %s/%s; "
        "re-entry after %.0f s: %s (area %s), counters %s/%s" % (moved, a1, r0, c0, r1, c1, time.time() - t0, moved2, a2, r2, c2),
        shots, l + ll + ll2)
    while time.time() - t0 < 68:
        guard()
        time.sleep(3)
    for _ in range(2):
        ok3, ll3 = H("enter nearest")
        time.sleep(2)
    st3 = hstate()
    r3, c3 = lockout_counts(st3)
    a3 = st3["player"].get("area")
    add(n2, "PASS" if (r3 or 0) > (r2 or 0) and a3 == 1 else "FAIL",
        "68 s after the first entry: `enter nearest` -> %s; refused %s -> %s, still in area %s (sealed: %s)" % (
            ll3[0] if ll3 else "-", r2, r3, a3, (r3 or 0) > (r2 or 0)), [sh("lock_hell_sealed")], ll3)
    H("difficulty 0")
    H("stat player 12 set %d" % lvl0)


def check_cow():
    nm = "Cow portal recipe (Wirt's Leg): Normal town, Hell town, Hell field"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(1)
    ensure_cube()
    H("cubeclear")
    H("item leg cube")

    def cow(diff, area):
        H("difficulty %d" % diff)
        H("quest 40 0 set")  # the cow portal handler wants Baal killed in the game's difficulty
        before = {o["id"] for o in hstate()["objs"]}
        ok, l = H("cubecraft")
        time.sleep(1.5)
        st = hstate()
        new = [o for o in st["objs"] if o["id"] not in before and o.get("class") in (60, 600)]
        return ok, l, new

    ok1, l1, new1 = cow(0, 1)
    ok2, l2, new2 = cow(2, 1)
    goto(2)
    H("difficulty 2")
    H("cubeclear")
    H("item leg cube")
    ok3, l3, new3 = cow(2, 2)
    H("difficulty 0")
    goto(1)
    good = (not ok1) and ok2 and bool(new2) and (not ok3) and not new3
    add(nm, "PASS" if good else "FAIL",
        "cubecraft with the leg: Normal town -> %s (recipe has min difficulty Hell); Hell town -> %s, new portal object %s; "
        "Hell field (Blood Moor) -> %s, new portal object %s" % (
            l1[-1][:60], l2[0][:70], [(o['class']) for o in new2], l3[-1][:60], [(o['class']) for o in new3]),
        [sh("cow")], l1 + l2 + l3)
    H("cubeclear")


def check_goldcraft():
    nm = "Cube gold payment (rows 6327/6328): carried gold first, then the bank"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(1)
    ensure_cube()
    H("cubeclear")
    H("stat player 532 set 140")
    H("gold set 400000 100000")
    H("item 0u1 cube uniq=30 532=1")   # HotTJ; item stat 532 == 1 is the cubemain row's own condition (op 18)
    H("item f667 cube")
    ok1, l1 = H("cubecraft")
    _, g1 = H("gold get")
    H("cubeclear")
    H("gold set 20000 100000")
    H("item 0u1 cube uniq=30 532=1")
    H("item f667 cube")
    H("item f667 cube")
    ok2, l2 = H("cubecraft")
    _, g2 = H("gold get")
    H("cubeclear")
    c1 = re.search(r"carried=(\d+) bank=(\d+)", g1[0])
    c2 = re.search(r"carried=(\d+) bank=(\d+)", g2[0])
    good = ok1 and ok2 and c1 and c2 and (int(c1.group(1)), int(c1.group(2))) == (350000, 100000) and \
        (int(c2.group(1)), int(c2.group(2))) == (0, 20000)
    add(nm, "PASS" if good else "FAIL",
        "row 6327 (cost 50,000): %s, gold 400000 / 100000 -> %s; row 6328 (cost 100,000) with 20000 carried: %s, gold "
        "20000 / 100000 -> %s (carried first, the rest from the bank)" % (l1[0][:50], g1[0], l2[0][:50], g2[0]),
        [sh("goldcraft")], l1 + l2)
    H("stat player 532 set 0")


def check_craftflags():
    n1 = "Cube craft flag (player): the character class's setter row (6369 + 19 per class) sets it, row 6350 is offered afterwards"
    n2 = "Cube craft flag (game): dungeon key row 7102 sets game flag 50, a second try is refused"
    if not need_game():
        add(n1, "BLOCKED", "not in a game")
        return add(n2, "BLOCKED", "not in a game")
    goto(1)
    ensure_cube()
    H("cubeclear")
    # the setter recipes are class-split (rows 6369 assassin, 6388 paladin, 6407 druid, 6426 necromancer, 6445 sorceress, 6464
    # barbarian, 6483 amazon; flag 1 is the first row of each group): the character's own class picks its row. The check used to
    # switch the character to an assassin (`class 6`), but then the game refuses to place any item in the cube ("placing failed",
    # seen on the level 34 test character of slot 3), so no recipe matched
    cls0 = hstate()["player"]["class"]
    names = {6: ("assassin", 6369), 3: ("paladin", 6388), 5: ("druid", 6407), 2: ("necromancer", 6426),
             1: ("sorceress", 6445), 4: ("barbarian", 6464), 0: ("amazon", 6483)}
    cname, setter = names.get(cls0, ("class %d" % cls0, 6369))
    H("packclear")
    ok0, lp = H("item voXX cube uniq=55")
    try:
        H("stat player 378 set 214100")
        _, f0 = H("flag player 1 get")
        ok1, l1 = H("cubecraft")
        _, f1 = H("flag player 1 get")
        ok2, l2 = H("cubecraft")
    finally:
        H("stat player 378 set 0")
    H("cubeclear")
    r1 = re.search(r"recipe (\d+)", l1[0]) if l1 else None
    r2 = re.search(r"recipe (\d+)", l2[0]) if l2 else None
    add(n1, "PASS" if (ok0 and ok1 and r1 and r1.group(1) == str(setter) and f0[0].endswith("= 0") and f1[0].endswith("= 1") and ok2
                       and r2 and r2.group(1) == "6350") else "FAIL",
        "%s (row %d) with the quest item%s: before %s; first transmute %s; after %s; second transmute %s (6350 only offered "
        "with the flag)" % (cname, setter, "" if ok0 else " (NOT placed: %s)" % lp[-1][:50], f0[0], l1[0][:40], f1[0],
                           l2[0][:40] if l2 else "-"), [sh("craftflags")], l1 + l2)
    H("stat player 536 set 1000")
    H("item rx01 cube")
    H("item f700 cube")
    _, g0 = H("flag game 50 get")
    ok3, l3 = H("cubecraft")
    _, g1 = H("flag game 50 get")
    H("cubeclear")
    H("item rx01 cube")
    H("item f700 cube")
    ok4, l4 = H("cubecraft")
    H("cubeclear")
    H("stat player 536 set 0")
    r3 = re.search(r"recipe (\d+)", l3[0]) if l3 else None
    add(n2, "PASS" if (ok3 and r3 and r3.group(1) == "7102" and g0[0].endswith("= 0") and g1[0].endswith("= 1") and not ok4)
        else "FAIL",
        "key recipe: before %s; transmute %s; after %s; second try in the same game: %s" % (
            g0[0], l3[0][:50] if l3 else "-", g1[0], l4[-1][:60]), [sh("gameflag")], l3 + l4)
    H("flag game 50 clear")


def check_dungeon_reenter():
    """Bug #24b: a Median dungeon entered, left and entered again in one game. The client's missile tick called D2R's
    client "do" table through an empty slot for missiles whose pCltDoFunc is empty (row 5507 warp_crash_missile is fired by
    the monsters of level 251 Butcher's Lair 2 a few seconds after the arrival) and the game died with a call to address 0.
    The check enters level 251 (`b60X`, Hell rules, the 60 s lock) three times, fires row 5507 in each visit (`h missile`,
    the same call the monsters use) and needs the game alive and the player in the level every time. It runs after the
    checks that use `b60X` themselves (a second `use` while the portal stands fails), and 253 is sealed by lockclock by now."""
    name = "Median dungeon (251) entered three times in one game (bug #24b: empty client missile function slot)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    lvl0 = hstate()["player"]["level"]
    H("difficulty 2")
    H("stat player 12 set 125")
    notes, log, shots, ok = [], [], [], True
    off = g._size(g.MXL_LOG)

    def heal():
        H("stat player 7 set 2000000000")
        H("stat player 6 set 2000000000")

    heal()
    H("item b60X")
    _, l = H("use b60X")
    log += l
    time.sleep(1.5)
    ports = [o for o in hstate()["objs"] if o.get("class") in (59, 60, 600)]
    pid = max(ports, key=lambda o: o["id"])["id"] if ports else None
    t0 = time.time()
    for visit in (1, 2, 3):
        guard()
        heal()
        moved = False
        for _ in range(3):
            time.sleep(2)
            _, ll = H("enter %d" % pid) if pid is not None else (False, [])
            log += ll
            if ll and "moved" in ll[0]:
                moved = True
                break
        time.sleep(3)
        area = hstate()["player"].get("area") if g.game_pids() else None
        fired = []
        if area == 251:
            fired = [H("missile 5507")[0], H("missile 5507 -10 8")[0]]
            time.sleep(4)  # the client ticks the missiles in these seconds
        alive = bool(g.game_pids())
        if alive:
            shots.append(sh("reenter_%d" % visit))
        notes.append("visit %d at +%.0f s: portal %s moved %s, area %s, missiles %s, alive %s" % (
            visit, time.time() - t0, pid, moved, area, fired, alive))
        if not (alive and moved and area == 251 and all(fired)):
            ok = False
        if not alive:
            break
        heal()
        goto(1)
    skipped = [ln for ln in mxl_lines_since(off) if "which D2R leaves empty" in ln]
    if g.game_pids():
        H("difficulty 0")
        H("stat player 12 set %d" % lvl0)
    add(name, "PASS" if ok and g.game_pids() else "FAIL",
        "; ".join(notes) + "; plugin log: %s" % ("; ".join(x.split("mxl-core: ")[-1][:80] for x in skipped[:3]) or "no empty-slot call logged"),
        shots[-2:], log)


# lockclock goes first after mxl: entering the Median dungeon is a heavy level load and D2R's client asserts "asset cache
# exceeded" (512 assets) after a few area changes, then crashes (see docs/bugs.md)
def check_areacycle():
    """Bug #24: area changes in one game. MXL_AREAS (comma list, default 2..17) are visited in order with D2R's
    `cheat goto` / the plugin's `level`; the loader log is searched for the asset cache and biome assertions and the
    game process for being alive."""
    name = "Area changes in one game (bug #24: asset cache, empty biome)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    areas = [int(x) for x in os.environ.get("MXL_AREAS", "2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17").split(",")]
    off = g._size(g.LOADER_LOG)
    n_cache = n_biome = 0
    notes = []
    reached = 0
    for a in areas:
        guard()
        st = goto(a)
        at = st["player"].get("area")
        txt = g._read_from(g.LOADER_LOG, off)
        n_cache = txt.count("AssetCache.h")
        n_biome = txt.count("has no biome") + txt.count("empty biome filename")
        alive = bool(g.game_pids())
        notes.append("%d->%s cache=%d biome=%d%s" % (a, at, n_cache, n_biome, "" if alive else " DEAD"))
        if not alive:
            break
        if at == a:
            reached += 1
    ok = bool(g.game_pids()) and n_cache == 0 and n_biome == 0
    add(name, "PASS" if ok else "FAIL", "%d of %d areas reached; asset cache asserts %d, biome asserts %d; %s" % (
        reached, len(areas), n_cache, n_biome, "; ".join(notes)))


def mapmem_probe():
    """`h mapmem` (client verb) -> dict of the numbers, or None."""
    ok, lines = H("mapmem")
    ln = next((x for x in lines if x.startswith("mapmem ")), "")
    d = kv(ln)
    if not ok or "layer" not in d:
        return None
    cells = [int(x) for x in d.get("cells", "0").split(",")]
    return {"layer": int(d["layer"]), "bucket": int(d["bucket"]), "cells": sum(cells), "file": d.get("file") == "read",
            "nodes": int(d.get("nodes", 0)), "foreign": int(d.get("foreign", 0)), "clean": d.get("clean") == "1",
            "loads": int(d.get("loads", 0)), "saves": int(d.get("saves", 0)), "views": int(d.get("views", 0)),
            "resets": int(d.get("resets", 0))}


def check_mapmem():
    """Per-level map memory of Levels.txt layers above 99 (docs/subsystems/areas-drlg.md section 6, bug #24). D2R's map file
    has 100 chains indexed by the layer; the plugin indexes it by layer % 100 and shows the loader only the nodes of the
    layer it loads. MXL_MAPMEM (comma list; default 134,147,184,12,139: layers 101, 110, 140, 5 and 105, the last two share
    chain 5) is visited in order (walking a little in each level to explore it), then again in reverse order. Every visit
    must reach the level in a living game; every return must find a clean chain holding saved nodes of the level's own layer,
    room sets not smaller than when the level was left, and (layer 100 or more) a view counter that says the loader was served
    a filtered file."""
    name = "Map memory of levels with Layer above 99 (bug #24: 100-chain table, per-level rooms kept)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    areas = [int(x) for x in os.environ.get("MXL_MAPMEM", "134,147,184,12,139").split(",")]
    off = g._size(g.LOADER_LOG)
    notes, shots, bad = [], [], []
    left = {}
    shared_seen = False
    plan = [(a, "first") for a in areas] + [(a, "back") for a in reversed(areas)]
    for a, phase in plan:
        guard()
        st = goto(a)
        at = st["player"].get("area")
        if not g.game_pids():
            bad.append("%d %s: the game is gone" % (a, phase))
            break
        if at != a:
            bad.append("%d %s: stayed in %s" % (a, phase, at))
            continue
        time.sleep(2)
        arrive = mapmem_probe()
        if arrive is None:
            bad.append("%d %s: no mapmem line" % (a, phase))
            continue
        p = st["player"]
        for dx, dy in ((14, 0), (0, 14), (-14, 0), (0, -14)):  # a short walk reveals the rooms around the arrival
            H("move %d %d" % (int(p.get("x", 0)) + dx, int(p.get("y", 0)) + dy))
            time.sleep(1.5)
        now = mapmem_probe() or arrive
        notes.append("%s %d: layer %d cells %d -> %d nodes %d foreign %d clean %d views %d saves %d" % (
            phase, a, now["layer"], arrive["cells"], now["cells"], now["nodes"], now["foreign"], now["clean"], now["views"], now["saves"]))
        if phase == "first":
            left[a] = max(arrive["cells"], now["cells"])
            if a == areas[0]:
                shots.append(sh("mapmem_%d" % a))
        else:
            if not arrive["clean"] or not now["clean"]:
                bad.append("%d back: the chain of bucket %d is not clean" % (a, now["bucket"]))
            if now["layer"] >= 100 and now["views"] == 0:
                bad.append("%d back: layer %d never got a view" % (a, now["layer"]))
            if not arrive["file"] or arrive["nodes"] < 1:
                bad.append("%d back: no saved node of layer %d in the map file (file read %s, nodes %d)" % (a, now["layer"], arrive["file"], arrive["nodes"]))
            if arrive["cells"] < left[a]:
                bad.append("%d back: %d rooms on arrival, %d when it was left" % (a, arrive["cells"], left[a]))
        if now["foreign"] > 0:
            shared_seen = True
    txt = g._read_from(g.LOADER_LOG, off)
    reads = txt.count("Reading From")  # a few lines per level change; thousands of them is the loop of bug #24
    alive = bool(g.game_pids())
    if reads > 2000:
        bad.append("%d 'Reading From' lines in the loader log (a self-loop in the chain?)" % reads)
    nodes_back = [n for n in notes if n.startswith("back")]
    add(name, "PASS" if alive and not bad and len(nodes_back) == len(areas) else "FAIL",
        "%s%s; %s" % ("; ".join(bad) + "; " if bad else "", "chain of two layers shared %s" % ("seen" if shared_seen else "not seen"), " | ".join(notes)), shots)


def cast_and_watch(skill, level, target, tries=6, shot=None, approach=False):
    """setskill, then cast up to `tries` times and watch the missiles the server frames saw. A melee cast walks the player
    up to the monster first, and the Fallen of the Blood Moor wander and flee, so a cast at a monster 5-8 sub-tiles away only
    walks (mode 3) and the next one repeats it (regression hunt 2026-10-22: the same Bash passed or failed from run to run
    on exactly this): with `approach` the player is moved next to the monster before every try (`moveto nearest`) and the
    cast follows at once. Returns (cast_ok, cast_lines, mana_dropped, cast_mode_seen, missiles_seen, screenshot or None)."""
    H("setskill %d %d" % (skill, level))
    H("missiles reset")
    ok, lines, dropped, cast_mode, seen, shot_taken = False, [], False, False, 0, None
    for _ in range(tries):
        if approach:
            H("moveto nearest")
            time.sleep(0.4)
        ok, lines = H("cast %d %s" % (skill, target))
        m = re.search(r"mana (\d+) -> (\d+)", " ".join(lines))
        dropped = dropped or (bool(m) and int(m.group(2)) < int(m.group(1)))
        cast_mode = cast_mode or bool(re.search(r"mode now (7|10)", " ".join(lines)))
        t0 = time.time()
        while time.time() - t0 < 1.6:
            time.sleep(0.4)
            _ok, ml = H("missiles")
            m = [re.search(r"seen=(\d+)", ln) for ln in ml if ln.startswith("missiles ")]
            seen = int(m[0].group(1)) if m and m[0] else 0
            cast_mode = cast_mode or hstate()["player"].get("mode") in (7, 10)
            if shot and seen > 0 and shot_taken is None:  # the effect is on screen now (window-only capture)
                shot_taken = sh(shot)
        if seen > 0 and (dropped or cast_mode):
            break
        if not ok:
            H("spawn 18 1")  # the monster died or is gone
    return ok, lines, dropped, cast_mode, seen, shot_taken


def check_casts():
    nm = "Server-side skill casts (harness cast): Median Barbarian skills and a Sorceress spell, cast animation, missiles seen"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(2)  # Blood Moor: skills do not work in town
    kill_all_near()
    notes, shots, log, good = [], [], [], True
    # earthquake_2 (Median, melee: the cast walks the player to the monster first) fires earthquake missiles;
    # Fire Bolt is a Sorceress spell, cast by the Barbarian (the game does not check the class here)
    cases = [("earthquake_2 (Median Barbarian)", 1271, 5, True, True), ("Bash (vanilla Barbarian)", 126, 1, False, True),
             ("Fire Bolt (Sorceress spell)", 36, 5, True, False)]
    for label, skill, level, want_missiles, melee in cases:
        kill_all_near()
        H("spawn 18 1")
        if melee:
            H("moveto nearest")
        ok, lines, dropped, cast_mode, seen, shot = cast_and_watch(skill, level, "nearest", tries=10 if melee else 6,
                                                                       shot="cast_%d" % skill, approach=melee)
        passed = ok and (dropped or cast_mode) and (seen > 0 or not want_missiles)
        good = good and passed
        notes.append("%s: cast %s, cast animation %s, mana drop at the call %s, missiles seen %d" % (
            label, "OK" if ok else "FAIL", cast_mode, dropped, seen))
        shots.append(shot or sh("cast_%d" % skill))
        log += lines
        kill_all_near()
    add(nm, "PASS" if good else "FAIL", "; ".join(notes), shots, log)


def check_cursemissile():
    nm = "Curse skills without a client missile: no nMissile assert (cltdofunc 30 wrapper, sigma_skills.cpp CltDoCurse)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    import csv
    rows = list(csv.reader(open(os.path.join(MOD_DATA, "global", "excel", "skills.txt"), encoding="latin-1"), delimiter="	"))
    ix = {n: i for i, n in enumerate(rows[0])}
    bare, with_missile = [], []
    for r in rows[1:]:
        if len(r) <= ix["cltmissilec"] or r[ix["cltdofunc"]] != "30" or not r[ix["*Id"]].isdigit():
            continue
        (bare if not r[ix["cltmissilea"]] else with_missile).append(int(r[ix["*Id"]]))
    if len(bare) < 3 or not with_missile:
        return add(nm, "BLOCKED", "skills.txt has %d curse rows without and %d with a cltmissilea" % (len(bare), len(with_missile)))
    # 66 Amplify Damage, 91 Lower Resist and 77 Terror are Median curses with no client missile; 71 Dim Vision keeps its own
    samples = [i for i in (66, 91, 77) if i in bare] or bare[:3]
    keep = 71 if 71 in with_missile else with_missile[0]
    log, notes, good = [], [], True
    m = log_mark()
    for sk in samples + [keep]:
        ok, l = H("cltdo %d" % sk)
        log += l
        ret = re.search(r"returned=(-?\d+)", " ".join(l))
        good = good and ok and ret is not None and ret.group(1) == "1"
        notes.append("skill %d %s" % (sk, "returned %s" % (ret.group(1) if ret else "-")))
    time.sleep(0.5)
    new = [a for a in assertions_since(m) if "nMissile" in a]
    good = good and not new
    # control: D2R's own function (0x2b05d0) asserts on the same bare row
    m2 = log_mark()
    ok, l = H("cltdo %d orig" % samples[0])
    log += l
    time.sleep(0.5)
    ctl = [a for a in assertions_since(m2) if "nMissile" in a]
    add(nm, "PASS" if good and ctl else ("FAIL" if not good else "REVIEW"),
        "%d bare curse rows (%d with a missile); %s; nMissile asserts through the table: %d; control, D2R's own function on skill %d: %d" % (
            len(bare), len(with_missile), ", ".join(notes), len(new), samples[0], len(ctl)), [sh("cursemissile")], log + new + ctl)


def assert_lines(lines):
    """`asserttrace show` lines: [(message, file, [frame rvas])]."""
    out = []
    for ln in lines:
        m = re.search(r"assert \d+: (.*?) \| (.*?) \| ([0-9a-f ]*)$", ln)
        if m:
            out.append((m.group(1), m.group(2), [int(x, 16) for x in m.group(3).split()]))
    return out


def check_asserttrace():
    nm = "Engine assert trace (harness asserttrace): the call chain of an engine assert, and the probes of the open asserts"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    log = []
    ok, l = H("asserttrace on")
    log += l
    if not ok:
        return add(nm, "FAIL", "the hook of the assert report function 0x75ff0 did not install: %s" % " ".join(l)[:120], [], log)
    H("asserttrace clear")
    # control: D2R's own client curse function on a Median curse without a client missile raises nMissile from 0x2b05d0
    H("cltdo 66 orig")
    got = assert_lines(H("asserttrace show")[1])
    ctl = [a for a in got if "nMissile" in a[0] and any(0x2b05d0 <= f < 0x2b0800 for f in a[2])]
    notes = ["control (cltdo 66 orig): %d nMissile assert(s), chain %s" % (len(ctl), " ".join("%x" % f for f in ctl[0][2][:6]) if ctl else "-")]
    # control 2: Amplify Damage (66) has cltstfunc 18 and no client missile; D2R's own start function of its table slot
    # (cltstfunc 18, 0x2b0df0) asserts nMissile, the table entry (the plugin's wrapper CltStMissileC) does not and returns 1
    H("asserttrace clear")
    ok_o, l_o = H("cltst 66 orig")
    orig_got = [a_ for a_ in assert_lines(H("asserttrace show")[1]) if "nMissile" in a_[0] and any(0x2b0df0 <= f < 0x2b1000 for f in a_[2])]
    H("asserttrace clear")
    ok_t, l_t = H("cltst 66")
    table_got = [a_ for a_ in assert_lines(H("asserttrace show")[1]) if "nMissile" in a_[0]]
    notes.append("skill 66 start function: D2R's own (orig) %d nMissile assert(s) [%s]; through the table %d [%s]" % (
        len(orig_got), " ".join(l_o)[-70:], len(table_got), " ".join(l_t)[-70:]))
    start_ok = ok_o and ok_t and bool(orig_got) and not table_got and "returned=1" in " ".join(l_t)
    log += l_o + l_t
    # probes of the open asserts: the treasure goblin (nRadius), a hit by an andariel_ai monster (nSkillCastId)
    goto(2)
    kill_all_near()
    H("asserttrace clear")
    H("spawn 2791 1")
    time.sleep(6)
    probes = assert_lines(H("asserttrace show")[1])
    notes.append("treasure goblin spawn: %s" % ("; ".join("%s <- %s" % (a[0], " ".join("%x" % f for f in a[2][:8])) for a in probes) or "no assert"))
    # the goblin's aura skill 2583 (cltstfunc 18 chain seen on the old plugin) has no client missile: the wrapper CltStMissileC must keep it from asserting
    goblin_missile = [x for x in probes if "nMissile" in x[0]]
    if goblin_missile:
        notes.append("FAIL: the treasure goblin still raised %d nMissile assert(s)" % len(goblin_missile))
    kill_all_near()
    # the warp asserts of `goto` into Median-only levels (docs/testing.md assert table)
    warps = []
    for area in (16, 191, 250, 134):
        H("asserttrace clear")
        goto(area)
        time.sleep(1.5)
        found = assert_lines(H("asserttrace show")[1])
        warps += found
        notes.append("goto %d: %s" % (area, "; ".join(sorted(set("%s <- %s" % (a[0][:34], " ".join("%x" % f for f in a[2][:5])) for a in found))) or "no assert"))
    goto(1)
    log += ["%s | %s | %s" % (a[0], a[1], " ".join("%x" % f for f in a[2])) for a in got + probes + warps]
    add(nm, "PASS" if ctl and start_ok and not goblin_missile else "FAIL", "; ".join(notes), [sh("asserttrace")], log)


def check_cherry():
    name = "Cherries (item spells 12 / 17, D2Sigma 0x1007fa90 / 0x1007fb70): the cherry teleports to the Pacman level and casts its skill, home_cherry goes back, a set stat 467 refuses the cherry"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    rows, bad, shots = [], [], []
    god(True)
    try:
        goto(1)
        H("packclear")
        # control first: stat 467 (itemstatcost_467, D2R id 496) above 0 makes the cherry's calc1 0 = no destination
        H("stat player 496 set 1")
        H("item kpac inv")
        ok, _l = H("use kpac")
        area = hstate()["player"].get("area")
        rows.append("control, stat 467 = 1: cherry %s, area %s" % ("USED" if ok else "refused", area))
        if ok or area != 1:
            bad.append("the cherry was used with stat 467 set (area %s)" % area)
        H("stat player 496 set 0")
        H("packclear")
        H("item kpac inv")
        m = mxl_mark()
        ok, lines = H("use kpac")
        area = None
        for _ in range(10):
            time.sleep(2)
            area = hstate()["player"].get("area")
            if area == 219:
                break
        got = [ln for ln in mxl_lines_since(m) if "cherry:" in ln]
        shots.append(sh("cherry"))
        rows.append("cherry: use %s, area %s (the Pacman level is D2R level 219); %s" % ("ok" if ok else "refused", area, got[-1][-70:] if got else "no cherry log line"))
        if not ok or area != 219:
            bad.append("the cherry did not move the character to level 219 (area %s)" % area)
        if not got or not re.search(r"skill 1828 level 1 cast [1-9]", got[-1]):
            bad.append("the cherry's skill 1828 was not cast: %s" % (got[-1][-70:] if got else "no log line"))
        H("packclear")
        H("item pacb inv")
        ok, lines = H("use pacb")
        for _ in range(10):
            time.sleep(2)
            area = hstate()["player"].get("area")
            if area == 1:
                break
        rows.append("home_cherry: use %s, area %s" % ("ok" if ok else "refused", area))
        if not ok or area != 1:
            bad.append("home_cherry did not move the character to level 1 (area %s)" % area)
    finally:
        H("stat player 496 set 0")
        god(False)
        goto(1)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) + (("; " + "; ".join(bad)) if bad else ""), shots, rows)


def _skillstats():
    """The counters of the wrapped srvdofunc slots 41 and 73 (`skillstats`): (fan casts, melee hits, hammer casts, swaps)."""
    ok, lines = H("skillstats")
    m = re.search(r"fan casts=(\d+) melee hits=(\d+) hammer casts=(\d+) swaps=(\d+)", " ".join(lines))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0, 0)


def check_replacedskills():
    """Audit item 'replaced vanilla skill-function slots 41, 54, 73, 78, 112, 120': D2Sigma's version of slot 41 (vampiric_strike,
    deathgaze, batstrike_2, skills_2759) throws the melee hit at the target before the missile scatter, D2R's does not (the plugin
    wraps it); slot 73 (hammer_of_zerae, power_shift) takes srvmissilea / b / c by calc2 (hammer_of_zerae's calc2 = 1 + syn3, the
    player's stat 396 = D2R 425 with the skill as layer), D2R's always takes srvmissilea (wrapped). The other slots were compared in
    the disassembly and run D2R's own function. PASS: each 41 skill counts a melee hit and throws missiles; hammer_of_zerae with
    syn3 = 2 throws hammer_of_zerae_missile_2 (and hammer_of_zerae_missile without syn3)."""
    nm = "Replaced skill functions (slots 41 and 73): vampiric_strike / deathgaze / batstrike_2 hit then scatter missiles, hammer_of_zerae picks its missile by calc2"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, t, h = _skill_ids_by_name()
    mt = _tsv(os.path.join(BUILT_EXCEL, "missiles.txt"))
    mrow = {r[0]: i for i, r in enumerate(mt[1:]) if r and r[0]}
    need = ("vampiric_strike", "deathgaze", "batstrike_2", "hammer_of_zerae", "power_shift")
    sid = {n: by_name.get(n) for n in need}
    if None in sid.values() or "hammer_of_zerae_missile" not in mrow or "hammer_of_zerae_missile_2" not in mrow:
        return add(nm, "BLOCKED", "skills or missiles missing from the built tables: %s" % [n for n, v in sid.items() if v is None])
    fight_ready()
    god(True)
    notes, problems, shots, log = [], [], [], []
    H("packclear")
    for slot_ in ("rhand", "lhand"):
        H("unequip " + slot_)
    # The skills want weapon types (itypea1): vampiric_strike / batstrike_2 h2h (claw, j20 has no requirements), deathgaze axe (115),
    # hammer_of_zerae / power_shift blun (mace 124).
    cls0 = hstate()["player"].get("class") or 0
    weapon_of = {"vampiric_strike": "j20", "batstrike_2": "j20", "deathgaze": "115", "hammer_of_zerae": "124", "power_shift": "124"}
    wielded = {"code": ""}

    def wield(name):
        code = weapon_of[name]
        if wielded["code"] != code:
            H("unequip rhand")
            H("class %d" % (6 if code == "j20" else cls0))  # claws are assassin-only
            ok_w, _lw = H("equip %s q=2 rhand" % code)
            wielded["code"] = code if ok_w else ""
            if not ok_w:
                notes.append("could not equip %s for %s" % (code, name))

    def cast(name, rounds=4):
        skill = sid[name]
        wield(name)
        kill_all_near()
        tid = tough_target(18)
        if tid is not None:
            H("setstate mon:%d 1 1" % tid)
        H("moveto nearest")
        H("setskill %d 5" % skill)
        before = _skillstats()
        H("missiles reset")
        seen_text, ok = "", False
        for _ in range(rounds):
            H("moveto nearest")
            time.sleep(0.3)
            H("stat player 8 set %d" % (rd("player", 9) or 0))
            ok, cl = H("cast %d nearest" % skill)
            log.extend(cl[:2])
            time.sleep(1.5)
            seen_text = " ".join(H("missiles")[1])
            if ok and re.search(r"seen=[1-9]", seen_text):
                break
        after = _skillstats()
        classes = {int(c): int(n) for c, n in re.findall(r"class (\d+) x(\d+)", seen_text)}
        return ok, tuple(a - b for a, b in zip(after, before)), classes, tid

    for name in ("vampiric_strike", "deathgaze", "batstrike_2"):
        ok, d, classes, tid = cast(name)
        notes.append("%s (slot 41): cast %s, fan casts +%d, melee hits +%d, missile classes %s" % (name, "OK" if ok else "FAIL", d[0], d[1], classes))
        if not ok or d[0] < 1 or d[1] < 1 or not classes:
            problems.append("%s: cast %s, fan casts +%d, melee hits +%d, missiles %s" % (name, ok, d[0], d[1], classes))
        shots.append(sh("replaced_%s" % name))
    plain, second = mrow["hammer_of_zerae_missile"], mrow["hammer_of_zerae_missile_2"]
    for label, syn3 in (("syn3 = 0", 0), ("syn3 = 2", 2)):
        setstat("player", 425, syn3, sid["hammer_of_zerae"])
        ok, d, classes, tid = cast("hammer_of_zerae")
        want, other = (plain, second) if syn3 == 0 else (second, plain)
        notes.append("hammer_of_zerae, %s (slot 73): cast %s, casts +%d, swaps +%d, missile classes %s (plain %d, _2 %d)" % (
            label, "OK" if ok else "FAIL", d[2], d[3], classes, plain, second))
        if not ok or d[2] < 1 or want not in classes or other in classes or (syn3 == 2 and d[3] < 1):
            problems.append("hammer_of_zerae %s: cast %s, casts +%d, swaps +%d, classes %s, expected only %d" % (label, ok, d[2], d[3], classes, want))
        shots.append(sh("replaced_hammer_%d" % syn3))
    setstat("player", 425, 0, sid["hammer_of_zerae"])
    ok, d, classes, tid = cast("power_shift")
    notes.append("power_shift (slot 73): cast %s, casts +%d, swaps +%d, missile classes %s" % ("OK" if ok else "FAIL", d[2], d[3], classes))
    if not ok or d[2] < 1 or not classes:
        problems.append("power_shift: cast %s, casts +%d, classes %s" % (ok, d[2], classes))
    H("class %d" % cls0)
    alive = hstate()["ok"]
    god(False)
    kill_all_near()
    if not alive:
        problems.append("the game is gone")
    add(nm, "PASS" if not problems else "FAIL", ("%s | " % "; ".join(problems) if problems else "") + " | ".join(notes), shots, log)


def _vendor_codes():
    """Codes of weapons and armor rows in the built tables (the vendor's potions and scrolls are always in stock and not counted)."""
    codes = set()
    for tbl in ("weapons.txt", "armor.txt"):
        rows = _tsv(os.path.join(BUILT_EXCEL, "base", tbl))
        ci = rows[0].index("code")
        codes.update(r[ci].strip() for r in rows[1:] if len(r) > ci and r[ci].strip())
    return codes


def check_vendorstock():
    """Audit item 'Vendor stock rules (npcstores, D2NPC_10093f90)'. Median's stock builder (D2NPC 0x10093a30): item level
    ilvl = player level + 5, in Normal and Nightmare at most the act's last area (Act 1: levels row 35, MonLvl1Ex / 2Ex = 15 / 63)
    + 5; every item needs its base level <= ilvl; normal copies only while ilvl < 25 (NormalAreaLevelHigh); magic copies rand in
    [MagicMin, MagicMax] (3 at most) at that item level. D2R's builder (0x53c9f0) has the same shape, with its own cap (Normal
    only), a MagicLvl threshold per item (txt_migrate wrote 25 into it from the wrong npcstores byte) and 1 to 2 extra magic
    copies above item level 24."""
    nm = "Vendor stock (Charsi, Act 1): item level cap, magic stock at low levels, normal copies below item level 25, magic copies at most 3"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    gear = _vendor_codes()
    st0 = hstate()["player"]
    lvl0 = st0.get("level") or 1
    mdiff = re.search(r"difficulty = (\d)", " ".join(H("difficulty")[1]))
    diff0 = int(mdiff.group(1)) if mdiff else 0
    median_cap = {0: 15 + 5, 1: 63 + 5}
    rows, bad, log = [], [], []
    try:
        for diff in (0, 1, 2):
            for clvl in (10, 40, 90):
                H("difficulty %d" % diff)
                H("stat player 12 set %d" % clvl)
                close_menu()
                menu = npc_menu_near(154)
                if menu is None:
                    bad.append("diff %d level %d: no Charsi menu" % (diff, clvl))
                    continue
                H("shop 154 restock")
                H("menu 1")
                time.sleep(2.5)
                ok, lines = H("shop 154")
                items = [kv(l) for l in lines if l.startswith("item ")]
                trace = re.search(r"last item level (-?\d+) -> (-?\d+) \(cap\), difficulty (-?\d+)", " ".join(lines))
                g.click(*TRADE_CLOSE)
                time.sleep(0.8)
                close_menu()
                geared = [it for it in items if it.get("code", "").strip() in gear]
                magic = [it for it in geared if it.get("quality") == "4"]
                normal = [it for it in geared if it.get("quality") == "2"]
                per_code = {}
                for it in magic:
                    per_code[it["code"]] = per_code.get(it["code"], 0) + 1
                # The item level the builder used: the cap function's result (the items' own ilvl field reads 101 for every item
                # of this build, see docs/vendors.md).
                top = int(trace.group(2)) if trace else 0
                cap = min(clvl + 5, median_cap.get(diff, 999))
                line = "diff %d level %d: %d weapons/armor (%d normal, %d magic), builder item level %d (in %s, Median %d), most copies of one magic code %d" % (
                    diff, clvl, len(geared), len(normal), len(magic), top, trace.group(1) if trace else "?", cap, max(per_code.values()) if per_code else 0)
                rows.append(line)
                log.append(line)
                if not geared:
                    bad.append("diff %d level %d: no weapons or armor in stock" % (diff, clvl))
                    continue
                if top > cap:
                    bad.append("diff %d level %d: item level %d above Median's cap %d" % (diff, clvl, top, cap))
                if clvl == 10 and not magic:
                    bad.append("diff %d level 10: no magic items (Median stocks them from the item's base level up)" % diff)
                if cap >= 25 and normal:
                    bad.append("diff %d level %d: %d normal weapons/armor at item level %d (Median stops at 25)" % (diff, clvl, len(normal), cap))
                if per_code and max(per_code.values()) > 3:
                    bad.append("diff %d level %d: %d copies of one magic item (Median at most 3)" % (diff, clvl, max(per_code.values())))
    finally:
        H("stat player 12 set %d" % lvl0)
        H("difficulty %d" % diff0)
        close_menu()
    add(nm, "PASS" if not bad else "FAIL", "; ".join(bad + rows)[:1800], [], log)


def _median_orb_vendors():
    """Mystic orb codes per vendor (monstats row) in Median's npcstores.bin (docs/vendors.md): {npc row: set of codes}. The orbs are
    the misc rows of item type `mysticorb`-like codes named "Mystic Orb" in assets/median/item_names.txt."""
    names = os.path.join(REPO, "assets", "median", "item_names.txt")
    with open(names, encoding="latin-1") as f:
        orbs = {l.split("\t")[0] for l in f if "Mystic Orb" in l}
    data = open(os.path.join(REPO, "assets", "median", "data", "global", "excel", "npcstores.bin"), "rb").read()
    out = {}
    for i in range(struct.unpack_from("<I", data)[0]):
        row = data[4 + 52 * i:4 + 52 * (i + 1)]
        code = row[4:8].decode("latin-1").strip()
        if code in orbs:
            out.setdefault(struct.unpack_from("<H", row)[0], set()).add(code)
    return out, orbs


def check_vendororbs():
    """Bugs #37 / #38: who sells the mystic orbs. Median's npcstores.bin stocks them at Gheed, Drognan, Alkor, Halbu and Larzuk
    (48 orbs each, always in stock), not at Akara or Charsi. The Act 1 vendors are opened at player level 90 in Hell (no item level
    cap) and their stock is compared with Median's list."""
    nm = "Mystic orbs per vendor (bugs #37 / #38): Gheed sells Median's orbs, Akara and Charsi none (Median npcstores.bin)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    per_npc, orbs = _median_orb_vendors()
    revive_if_dead()
    goto(1)
    close_menu()
    st0 = hstate()["player"]
    lvl0 = st0.get("level") or 1
    mdiff = re.search(r"difficulty = (\d)", " ".join(H("difficulty")[1]))
    diff0 = int(mdiff.group(1)) if mdiff else 0
    rows, bad, log = [], [], []
    try:
        H("difficulty 2")
        H("stat player 12 set 90")
        for cls, name in ((148, "Akara"), (154, "Charsi"), (147, "Gheed")):
            want = per_npc.get(cls, set())
            close_menu()
            if npc_menu_near(cls) is None:
                bad.append("%s: no menu" % name)
                continue
            H("shop %d restock" % cls)
            H("menu 1")
            time.sleep(2.5)
            ok, lines = H("shop %d" % cls)
            g.click(*TRADE_CLOSE)
            time.sleep(0.8)
            close_menu()
            stock = [kv(l) for l in lines if l.startswith("item ")]
            sold = {it.get("code", "").strip() for it in stock} & orbs
            line = "%s (class %d): %d items, %d mystic orbs in stock (Median lists %d for this vendor)%s" % (
                name, cls, len(stock), len(sold), len(want), ": " + " ".join(sorted(sold)[:8]) if sold else "")
            rows.append(line)
            log.append(line)
            if not stock:
                bad.append("%s: empty stock" % name)
            elif not want and sold:
                bad.append("%s sells %d orbs, Median none" % (name, len(sold)))
            elif want and not sold:
                bad.append("%s sells no orbs, Median %d" % (name, len(want)))
            elif sold - want:
                bad.append("%s sells orbs Median does not list for it: %s" % (name, sorted(sold - want)))
    finally:
        H("stat player 12 set %d" % lvl0)
        H("difficulty %d" % diff0)
        close_menu()
    median = "; ".join("monstats row %d: %d orbs" % (k, len(v)) for k, v in sorted(per_npc.items()))
    add(nm, "PASS" if not bad else "FAIL", "; ".join(bad + rows) + " | Median npcstores: " + median, [], log)


def _monstats_class(name):
    t = _tsv(os.path.join(BUILT_EXCEL, "monstats.txt"))
    return next((i for i, r in enumerate(t[1:]) if r and r[0] == name), None)


def check_summonlife():
    """Bug #36: the Barbarian's wolf companion (skill wolf_companion, D2R's Raven summon srvdofunc 114, monster AI Raven) died a
    few seconds after it was summoned with no monster near. Summons it in an empty Blood Moor and in the town and follows its life for
    30 s; Guardian Spirit (srvdofunc 172, the plugin's multi-summon) is the control."""
    nm = "Summons stay alive with no monster near (bug #36): wolf_companion and guardian_spirit, 30 s in the field and in town"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, _t, _h = _skill_ids_by_name()
    rows, bad, log = [], [], []
    cls0 = hstate()["player"].get("class") or 0
    H("class 4")  # Barbarian
    try:
        for area in (2, 1):
            if area == 2:
                fight_ready()
            else:
                revive_if_dead()
                goto(1)
                close_menu()
            god(True)
            for skill, mon in (("wolf_companion", "wolf_companion"), ("guardian_spirit", "guardian_spirit")):
                sid, mcls = by_name.get(skill), _monstats_class(mon)
                if sid is None or mcls is None:
                    bad.append("%s: no skill or monstats row" % skill)
                    continue
                H("setskill %d 10" % sid)
                H("stat player 9 set %d" % (5000 << 8))  # the summon costs ~125 mana at level 10
                H("stat player 8 set %d" % (5000 << 8))
                ok, cl = H("cast %d self" % sid)
                log.extend(cl[:3])
                time.sleep(1.0)
                ids, samples, t0 = set(), [], time.time()
                pets = []
                while time.time() - t0 < 30:
                    pets = [m for m in hstate()["mons"] if m.get("class") == mcls and m.get("mode") not in (0, 12)]
                    ids.update(m["id"] for m in pets)
                    samples.append((round(time.time() - t0), len(pets), min((m.get("life", 0) for m in pets), default=0),
                                    max((m.get("maxlife", 0) for m in pets), default=0)))
                    time.sleep(2.0)
                first = next((s for s in samples if s[1]), None)
                # one empty sample is a gap of the unit listing (seen in town: missing at 26 s, back at 30 s with full life)
                after = [s for s in samples if first and s[0] > first[0]]
                died = next((a[0] for a, b in zip(after, after[1:]) if not a[1] and not b[1]), None)
                line = "area %d %s (skill %d, class %d): cast %s, %d unit(s) seen, alive at 30 s: %d, life (t, n, min life, max) %s" % (
                    area, skill, sid, mcls, "OK" if ok else "FAIL", len(ids), samples[-1][1] if samples else 0,
                    [s for s in samples[::3]] + samples[-1:])
                rows.append(line)
                log.append(line)
                if not first:
                    bad.append("area %d %s: no pet appeared (%s)" % (area, skill, " | ".join(cl[-1:])))
                elif died is not None or not samples[-1][1]:
                    bad.append("area %d %s: the pet died after about %s s with no monster near" % (area, skill, died))
                elif samples[-1][2] < first[2] * 0.9:
                    bad.append("area %d %s: life fell %d -> %d" % (area, skill, first[2], samples[-1][2]))
                for m in pets:
                    H("kill %d" % m["id"])
            god(False)
    finally:
        H("class %d" % cls0)
        god(False)
    add(nm, "PASS" if not bad else "FAIL", "; ".join(bad + rows)[:2400], [sh("summonlife")], log)


def check_nighthawks():
    """Bug #58: the Necromancer's Night Hawks (srvdofunc 172 multi-summon, monster night_hawk) dive at a monster and explode. Median
    has no monster skill for it: the hawk's monprop casts skills_374 on attack (stat 195, srvdofunc 156 -> slot 175, the plugin's
    "pet dies": the hawk is taken off the pet list and killed) and skills_373 on death (stat 271 = D2Sigma's event 14, raised by
    death_event.cpp on the victim of every death): missile 5444, the explosion with damage. Summons hawks next to a spawned monster
    with a large life pool and follows them: PASS when hawks appear, die at the monster, the explosion missile is seen, the monster
    loses life and the `mxl` death event line counts raised events. With `deathevent` off (MXL_CONTROL) the hawks still die but no
    explosion missile may appear."""
    nm = "Night Hawks explode on contact (bug #58): hawks die at the monster, explosion missile 5444, damage"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, t, h = _skill_ids_by_name()
    sid, hawk = by_name.get("night_hawks"), _monstats_class("night_hawk")
    boom = t[1:][[r[0] for r in t[1:]].index("skills_373")][h.index("srvmissile")] if "skills_373" in [r[0] for r in t[1:]] else ""
    mt = _tsv(os.path.join(BUILT_EXCEL, "missiles.txt"))
    mrow = {r[0]: i for i, r in enumerate(mt[1:]) if r and r[0]}
    if sid is None or hawk is None or boom not in mrow:
        return add(nm, "BLOCKED", "night_hawks %s, night_hawk %s, skills_373 missile %r not in the built tables" % (sid, hawk, boom))
    boom_id = mrow[boom]
    control = "death event off: left out" in mxl_text()
    notes, bad, log = [], [], []
    cls0 = hstate()["player"].get("class") or 0
    H("class 2")  # Necromancer
    try:
        fight_ready()
        kill_all_near()
        god(True)
        tid = tough_target(18)
        if tid is None:
            return add(nm, "BLOCKED", "no monster spawned")
        time.sleep(2)
        life0 = next((m.get("life") for m in hstate()["mons"] if m.get("id") == tid), None)
        H("asserttrace on")
        H("asserttrace clear")
        H("setskill %d 10" % sid)
        H("missiles reset")
        ids, alive_max, t0, life_min, gone = set(), 0, time.time(), life0, False
        casts = 0
        while time.time() - t0 < 20:
            if casts < 3:  # the hawks can reach the monster and explode within a second: the listing runs between the casts
                H("stat player 9 set %d" % (5000 << 8))
                H("stat player 8 set %d" % (5000 << 8))
                ok, cl = H("cast %d self" % sid)
                log.extend(cl[:2])
                casts += 1
            mons = hstate()["mons"]
            hawks = [m for m in mons if m.get("class") == hawk and m.get("mode") not in (0, 12)]
            ids.update(m["id"] for m in hawks)
            alive_max = max(alive_max, len(hawks))
            target = next((m for m in mons if m.get("id") == tid), None)
            if target is None or target.get("mode") in (0, 12):
                gone = True  # the explosions killed it (or it left the 40-unit listing)
            elif target.get("life") is not None and (life_min is None or target["life"] < life_min):
                life_min = target["life"]
            if casts >= 3 and ids and not hawks:
                break
            time.sleep(0.2 if casts < 3 else 1.0)
        mons = hstate()["mons"]
        alive = [m for m in mons if m.get("class") == hawk and m.get("mode") not in (0, 12)]
        asserts = sorted(set(a[0][:40] for a in assert_lines(H("asserttrace show")[1])))
        seen_text = " ".join(H("missiles")[1])
        classes = {int(c): int(n) for c, n in re.findall(r"class (\d+) x(\d+)", seen_text)}
        deaths = re.search(r"death event (.*?)\(deaths (\d+), raised (\d+), event (-?\d+)\)", mxl_text())
        notes.append("hawks seen %d (most at once %d), alive after 20 s %d; monster %s life %s -> lowest %s%s; explosion missile %d (%s) x%d; missiles %s; %s; asserts during the fight: %s" % (
            len(ids), alive_max, len(alive), tid, life0, life_min, " then dead / gone" if gone else "", boom_id, boom,
            classes.get(boom_id, 0), classes, deaths.group(0) if deaths else "no death event line", asserts or "none"))
        if not ids:
            bad.append("no hawk appeared")
        elif len(alive) == len(ids):
            bad.append("no hawk died (skills_374 / slot 175)")
        if control:
            if classes.get(boom_id):
                bad.append("control: explosion missile seen with deathevent off")
        else:
            if not classes.get(boom_id):
                bad.append("no explosion missile %d" % boom_id)
            if life0 is None or (not gone and (life_min is None or life_min >= life0)):
                bad.append("the monster lost no life")
            if not deaths or int(deaths.group(3)) < 1:
                bad.append("death event raised no event")
        for m in alive:
            H("kill %d" % m["id"])
        H("kill %d" % tid)
    finally:
        god(False)
        H("class %d" % cls0)
    add(nm + (" CONTROL (deathevent off)" if control else ""), "PASS" if not bad else "FAIL", "; ".join(bad + notes)[:2400], [sh("nighthawks")], log)


def check_abyssknight():
    """Bug #59: the Necromancer's Abyss Knights (skill abyss_knight, the plugin's multi-summon srvdofunc 172; monster abyss_knight,
    AI NecroPet, Skill1 abyss_knight_skill in mode S1) hit in melee and never used their AoE (abyss_knight_skill, srvdofunc 28,
    missile abyss_knight_skill_missile). Summons them in the Blood Moor, puts monsters a few yards away for 25 s, samples the
    knights' modes (4 attack1 = melee, 8 skill1 = the AoE) and counts the skill's missiles. The cause: D2Sigma marks pets of a
    multi-summon skill with Param7 as ranged pets (AI control +0x14), which sends NecroPet to its ranged branch; mxl-core does it
    in sigma_skills.cpp (off word `rangedpets`). With `MXL_CONTROL=rangedpets` the knights must melee as before (no skill1)."""
    nm = "Abyss Knights use their ranged AoE (bug #59): skill1 mode and abyss_knight_skill_missile while monsters stand at range"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, _t, _h = _skill_ids_by_name()
    sid, kcls = by_name.get("abyss_knight"), _monstats_class("abyss_knight")
    mt = _tsv(os.path.join(BUILT_EXCEL, "missiles.txt"))
    mis = next((i for i, r in enumerate(mt[1:]) if r and r[0] == "abyss_knight_skill_missile"), None)
    if sid is None or kcls is None or mis is None:
        return add(nm, "FAIL", "no abyss_knight skill / monstats row / abyss_knight_skill_missile row")
    rows, bad, log = [], [], []
    control = _ctl("rangedpets")
    cls0 = hstate()["player"].get("class") or 0
    H("class 2")  # Necromancer
    try:
        fight_ready()
        god(True)
        H("setskill %d 20" % sid)
        H("stat player 9 set %d" % (5000 << 8))
        H("stat player 8 set %d" % (5000 << 8))
        ok, cl = H("cast %d self" % sid)
        log.extend(cl[:3])
        time.sleep(1.5)
        knights = [m for m in hstate()["mons"] if m.get("class") == kcls and m.get("mode") not in (0, 12)]
        if not knights:
            return add(nm, "FAIL", "no Abyss Knight appeared (cast %s: %s)" % ("OK" if ok else "FAIL", " | ".join(cl[-1:])), [], log)
        p = hstate()["player"]
        px, py = p.get("x") or 0, p.get("y") or 0
        H("missiles reset")
        modes, t0 = {}, time.time()
        while time.time() - t0 < 25:
            st = hstate()
            foes = [m for m in st["mons"] if m.get("class") != kcls and not m.get("npc") and m.get("mode") not in (0, 12)
                    and m.get("dist", 99) < 25]
            if len(foes) < 2:
                _ok, sl = H("spawn 3 3 %d %d" % (px + 9, py + 9)) if px else H("spawn 3 3")
                log.extend(sl[:1])
            for m in st["mons"]:
                if m.get("class") == kcls:
                    modes[m.get("mode")] = modes.get(m.get("mode"), 0) + 1
            time.sleep(0.25)
        _ok, ml = H("missiles")
        summary = next((l for l in ml if l.startswith("missiles live=")), "")
        seen = re.search(r"class %d x(\d+)" % mis, summary)
        nmis = int(seen.group(1)) if seen else 0
        line = "%d knight(s), mode samples %s (4 attack1 melee, 8 skill1 AoE), missile %d seen %d | %s" % (
            len(knights), dict(sorted(modes.items())), mis, nmis, summary[:300])
        rows.append(line)
        log.append(line)
        s1, a1 = modes.get(8, 0), modes.get(4, 0) + modes.get(5, 0)
        if not nmis or s1 == 0:  # tell a broken skill from an AI that never picks it: one forced cast in mode S1
            kn = next((m for m in hstate()["mons"] if m.get("class") == kcls), None)
            ksid = by_name.get("abyss_knight_skill")
            if kn and ksid is not None:
                H("missiles reset")
                _ok, fl = H("mcast %d 8 unit %d" % (ksid, kn["id"]))
                time.sleep(1.5)
                _ok, ml2 = H("missiles")
                line = "forced cast: %s | %s" % (" | ".join(fl[-1:]), next((l for l in ml2 if l.startswith("missiles live=")), ""))
                rows.append(line[:400])
                log.append(line)
        if control:
            if s1 or not a1:
                bad.append("control (rangedpets off): expected melee only, got skill1 %d / attack1 %d samples" % (s1, a1))
        elif not nmis:
            bad.append("no abyss_knight_skill_missile was made")
        elif s1 == 0:
            bad.append("the knights never entered skill1 (the AoE)")
        elif a1 > s1:
            bad.append("melee (%d samples) outweighs the AoE (%d samples)" % (a1, s1))
        for m in hstate()["mons"]:
            if m.get("class") == kcls:
                H("kill %d" % m["id"])
        kill_all_near()
    finally:
        god(False)
        H("class %d" % cls0)
    add(nm + (" CONTROL (rangedpets off)" if control else ""), "PASS" if not bad else "FAIL", "; ".join(bad + rows)[:2400],
        [sh("abyssknight")], log)


def check_warprevisit():
    name = "Median-only levels entered twice by goto (warp tile asserts, ptWarp) - probe for docs/testing.md assert table"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    H("asserttrace on")
    notes = []
    for area in (250, 16, 191, 134):
        for visit in (1, 2):
            H("asserttrace clear")
            goto(area)
            time.sleep(2)
            found = assert_lines(H("asserttrace show")[1])
            notes.append("goto %d (visit %d): %s" % (area, visit, "; ".join(sorted(set("%s <- %s" % (a[0][:30], " ".join("%x" % f for f in a[2][:5])) for a in found))) or "no assert"))
            goto(2)
    add(name, "PASS", "; ".join(notes), [sh("warprevisit")], notes)


def spawn_id(cls=18):
    """Spawns a monster and returns its unit id (the `spawned class N id=M` line; the monster exists once that line is
    written, even when the closing "spawn OK" line is late)."""
    ok, lines = H("spawn %d 1" % cls)
    m = re.search(r"spawned class \d+ id=(\d+)", " ".join(lines))
    return int(m.group(1)) if m else None


def check_item_events():
    nm = "Item events (D2RCore registry): thorns 397 / 396 / 128, life on kill 265, cast on kill 376, open wounds / crushing blow skip immune monsters"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(2)
    close_menu()
    kill_all_near()
    H("unequip lring")
    log, notes = [], []
    H("stat player 6 0 set 700000")  # no god mode: it refills life, which hides the life-on-kill gain; the checks take a second

    def life_of(mid):
        ok, l = H("stat m%d 6" % mid)
        log.extend(l)
        return stat_of(l)

    # thorns: stat 397 (func 11, events 2 / 3): 50 fire damage is taken off the monster per event (life is stat 6, 1/256 points)
    ok, l = H("equip rin 397=50 lring")
    mid = spawn_id()
    log += l
    if mid is None:
        return add(nm, "BLOCKED", "no monster could be spawned")
    H("stat m%d 6 0 set 700000" % mid)  # a monster of the area's level has a few points of life, fewer than the 50 the event takes
    a = life_of(mid)
    H("evtrace fire 3 player m%d" % mid)
    b = life_of(mid)
    # the monster is next to the character and may attack in the same second: its own hit fires the event as well, so the loss
    # is one 50 or more (never a fraction of one)
    thorns = ok and a is not None and b is not None and a - b >= 50 * 256 and (a - b) % (50 * 256) == 0
    notes.append("thorns 50: monster life %s -> %s (%s)" % (a, b, "-%d points" % ((a - b) // 256) if thorns else "WRONG"))
    H("kill nearest")
    # thorns variants: stat 396 (func 12) and 128 (func 10) take the same 50 points per event (event 3)
    thorns_var = {}
    for stat in (396, 128):
        H("unequip lring")
        okv, lv = H("equip rin %d=50 lring" % stat)
        m2 = spawn_id()
        H("stat m%d 6 0 set 700000" % m2)
        a2 = life_of(m2)
        H("evtrace fire 3 player m%d" % m2)
        b2 = life_of(m2)
        thorns_var[stat] = okv and a2 is not None and b2 is not None and a2 - b2 >= 50 * 256 and (a2 - b2) % (50 * 256) == 0
        notes.append("thorns variant %d: monster life %s -> %s (%s)" % (stat, a2, b2, "-%d points" % ((a2 - b2) // 256) if thorns_var[stat] else "WRONG"))
        H("kill nearest")
    thorns = thorns and all(thorns_var.values())
    # life on kill: stat 265 = 50 (D2RCore function 33 -> D2R function 28), +50 points to a character at 100 life
    # (the character's own gear may heal on a kill too: the gain is measured against a kill without the ring)
    H("unequip lring")
    mid = spawn_id()
    H("stat player 6 0 set 25600")
    H("evtrace fire 9 player m%d" % mid)
    base = stat_of(H("stat player 6")[1])
    ok, l = H("equip rin 265=50 lring")
    H("stat player 6 0 set 25600")
    ok2, l2 = H("evtrace fire 9 player m%d" % mid)
    life = stat_of(H("stat player 6")[1])
    for _ in range(8):  # the heal may land a few frames after the event call returns: read again until it is whole (or 1.6 s have passed)
        if life is not None and base is not None and life - base >= 50 * 256:
            break
        time.sleep(0.2)
        life = stat_of(H("stat player 6")[1])
    heal = ok and ok2 and base is not None and life is not None and 50 * 256 <= life - base < 50 * 256 + 2000  # plus a little regeneration
    notes.append("life on kill 50: player life 25600 -> %s without the ring, %s with it (%s)" % (base, life, "+50 points" if heal else "WRONG"))
    # The measurement needed a character at 100 life; everything after it (cast on kill volleys, the wild monsters of the area) does
    # not, and a character left at 100 life dies: the server unit then stays dead (mode 17) for every later check. Life back up.
    H("stat player 6 0 set 700000")
    H("kill nearest")
    # cast on kill: stat 376 layer 36 * 64 + 5 (Fire Bolt level 5, 100 %): a missile (class 58) appears, the skill need not be known
    H("unequip lring")
    ok, l = H("equip rin 376:2309=100 lring")
    mid = spawn_id()
    time.sleep(2)  # a monster that was just spawned is not a valid target yet
    H("missiles reset")
    life0 = life_of(mid)
    H("evtrace fire 9 player m%d" % mid)
    ok2, l2 = H("missiles")
    time.sleep(1.5)
    life1 = life_of(mid)
    log += l2 + H("evtrace calls")[1]
    # the Fire Bolt is a missile (class 58) that may be gone again before `missiles` looks; it burns the monster
    cast = ok and (any("class 58" in x for x in l2) or (life0 is not None and life1 is not None and life1 < life0))
    notes.append("cast on kill (Fire Bolt 5): %s; monster life %s -> %s" % (" ".join(x for x in l2 if "missiles live" in x)[:60] or "-", life0, life1))
    H("kill nearest")
    # cast on kill with the skills Median's monsters cast (monprop: 855 a nova, 861 a missile volley) and the other rows that are
    # not a plain bolt: the missiles tracker counts every missile that outlives a server frame (`seen=`). Row 47 "Fire Ball" is a
    # Median stub (srvdofunc 18 self buff, srvmissile fire_ball_missile = missiles row 5540 with no velocity or range, no damage):
    # its missile dies within the frame it is created in, which a direct `missile 5540` shows as well (`missile 3456` lives).
    def cast_case(skill, level):
        # the event needs a live spawned monster and the ring in place; a try that never reached the handler (the last cast on kill
        # line still names the previous case) is repeated, up to 3 times
        for _try in range(3):
            res = cast_case_once(skill, level)
            if res[2] is not None and res[2][:2] == (skill, level):
                break
        return res

    def cast_case_once(skill, level):
        H("unequip lring")
        okc, _l = H("equip rin 376:%d=100 lring" % (skill * 64 + level))
        m = spawn_id()
        time.sleep(2)
        H("missiles reset")
        H("evtrace fire 9 player m%d" % m)
        okm, lm = H("missiles")
        okk, lk = H("evtrace calls")
        log.extend(lm + lk)
        seen = re.search(r"seen=(\d+)", " ".join(lm))
        last = re.search(r"last cast on kill: skill (-?\d+) level (-?\d+) warp (-?\d+)", " ".join(lk))
        H("kill nearest")
        return okc and okm and okk, int(seen.group(1)) if seen else None, tuple(int(x) for x in last.groups()) if last else None

    def direct_missile(row):
        H("missiles reset")
        H("missile %d 12 0" % row)
        ok1, l1 = H("missiles")
        log.extend(l1)
        seen = re.search(r"seen=(\d+)", " ".join(l1))
        time.sleep(1.5)
        return int(seen.group(1)) if seen else None

    cases = {}
    for skill, level in ((861, 50), (855, 2), (47, 10), (54, 1)):
        cases[skill] = cast_case(skill, level)
    kill_all_near()
    direct = {row: direct_missile(row) for row in (5540, 3456)}
    kill_all_near()
    c861, c855, c47, c54 = cases[861], cases[855], cases[47], cases[54]
    missiles_ok = (c861[0] and c861[1] and c861[1] > 0 and c861[2] and c861[2][:2] == (861, 50)
                   and c855[0] and c855[1] and c855[1] > 0 and c855[2] and c855[2][:2] == (855, 2))
    fire_ball = (c47[0] and c47[2] is not None and c47[2][:2] == (47, 10) and c47[1] == 0 and direct[5540] == 0
                 and direct[3456] is not None and direct[3456] > 0)
    warp = c54[0] and c54[2] is not None and c54[2][:2] == (54, 1) and c54[2][2] == 1 and c861[2] is not None and c861[2][2] == 0
    notes.append("cast on kill missiles seen: skill 861 L50 %s (class 3456), skill 855 L2 %s (class 3124) (%s)" % (
        c861[1], c855[1], "missiles" if missiles_ok else "WRONG"))
    notes.append("Fire Ball 47 L10: handler reached %s, missiles seen %s; direct `missile 5540` %s, `missile 3456` %s (%s: Median's row is a stub whose missile expires within the frame)" % (
        c47[2], c47[1], direct[5540], direct[3456], "as expected" if fire_ball else "WRONG"))
    notes.append("warp flag (Median 0x40): Teleport 54 %s, skill 861 %s (%s)" % (c54[2], c861[2], "read" if warp else "WRONG"))
    # open wounds (135) / crushing blow (136): lose life on a hit; a monster with stat 373 (Median 189) skips them
    H("unequip lring")
    ok, l = H("equip rin 135=100 136=100 lring")
    plain, immune = spawn_id(), spawn_id()
    H("stat m%d 373 0 set 1" % immune)
    res = {}
    for who in (plain, immune):
        a = life_of(who)
        H("evtrace fire 5 player m%d" % who)
        H("evtrace fire 6 player m%d" % who)
        res[who] = (a, life_of(who))
    wounds = ok and res[plain][1] < res[plain][0] and res[immune][1] == res[immune][0]
    notes.append("open wounds / crushing blow: plain monster life %s -> %s, immune (373) %s -> %s" % (
        res[plain][0], res[plain][1], res[immune][0], res[immune][1]))
    H("unequip lring")
    kill_all_near()
    H("stat player 6 0 set 2000000")  # the character is saved with its life: a dark orb is not taken for being in game on the next run
    txt = mxl_text()
    on = "item events on" in txt
    notes.append("`mxl`: %s" % ("item events on" if on else "item events not on"))
    add(nm, "PASS" if thorns and heal and cast and missiles_ok and fire_ball and warp and wounds and on else "FAIL", "; ".join(notes), [sh("item_events")], log)


def god(on):
    """D2R's god cheat around the checks that could kill the test character (Hell dungeon, bosses): a dead character
    makes later warps close the game. Off everywhere else: it also gives infinite mana and blocks damage."""
    enable_debug()
    con("cheat god %d" % (1 if on else 0))
    time.sleep(0.5)


def _andariel_ai_users():
    """(class id, name) of every monstats row whose AI column is andariel_ai in the built mod (the 47 users of AI 155)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data", "global", "excel", "monstats.txt")
    out = []
    with open(path, encoding="utf-8-sig") as f:
        head = f.readline().rstrip("\r\n").split("\t")
        ai = head.index("AI")
        for cls, line in enumerate(f):
            cols = line.rstrip("\r\n").split("\t")
            if len(cols) > ai and cols[ai] == "andariel_ai":
                out.append((cls, cols[0]))
    return out


AI_FIELDS = ("thinks", "wait", "attack", "enemy", "charge", "walk", "s1", "s2", "s3", "s4", "fallback", "controlled")


def ai_counters(text):
    """The `monster ai` line of `mxl`: counters of the native andariel_ai think (monster_ai.cpp MonsterAiStatus), or None."""
    for ln in text.splitlines():
        m = re.search(r"(\d+) thinks \(wait (\d+), attack (\d+) \+ (\d+) on the enemy, charge (\d+), walk (\d+), skills 1-4: (\d+) (\d+) (\d+) (\d+)\)"
                      r", fallback thinks (\d+), controlled thinks (\d+)", ln)
        if m:
            return dict(zip(AI_FIELDS, (int(x) for x in m.groups())))
    return None


def ai_delta(a, b):
    return {k: b[k] - a[k] for k in AI_FIELDS}


def clear_mons(rounds=3):
    """Kill every live monster `h state` lists (it lists at most 60 within 40 units). Ids that survive one kill are unkillable
    (town NPCs, Malthael's dark nephalems) and are not tried again."""
    skip = set()
    for _ in range(rounds):
        st = hstate()
        ids = [m.get("id") for m in st["mons"] if m.get("id") is not None and m.get("id") not in skip and not m.get("npc")]
        if not st["ok"] or not ids:
            return
        for i in ids:
            H("kill %d" % i)
        skip.update(ids)
        time.sleep(0.2)


def check_median_ai():
    """Native andariel_ai (plugin monster_ai.cpp, AI id 155) on every monstats row that uses it (47 classes, read from the built
    mod): each is spawned next to the god-mode player outside town and watched for ~3 s. PASS: the think ran (`mxl` counter
    `thinks` rose), the monster changed mode or distance or the counters show a wait / walk / attack / skill, and the game
    is still running with the monster listed. MXL_AI_CHUNK=a:b limits the run to users a..b-1 of the list."""
    name = "Median andariel_ai: all users act (think runs, mode or distance changes, no crash)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    users = _andariel_ai_users()
    lo, _, hi = os.environ.get("MXL_AI_CHUNK", "").partition(":")
    if lo or hi:
        users = users[int(lo or 0):int(hi or len(users))]
    god(True)
    goto(2)
    close_menu()
    kill_all_near()
    notes, shots, bad = [], [], []
    prev = ai_counters(mxl_text())
    if prev is None:
        god(False)
        return add(name, "FAIL", "the `mxl` monster ai line has no counters (medianai off, or the line changed)")
    skipped = []
    for cls, nm in users:
        clear_mons()
        ok, lines = H("spawn %d 1" % cls)
        mid = re.search(r"spawned class \d+ id=(\d+)", " ".join(lines))
        if not mid:
            skipped.append(nm)  # the harness cannot place it (e.g. a clone that needs its own room), not a failure of the AI
            notes.append("%d %s: NOT SPAWNABLE (%s)" % (cls, nm, " ".join(lines)[:60]))
            continue
        mid = int(mid.group(1))
        prev = ai_counters(mxl_text()) or prev  # counters from the monster alone (leftover summons are killed above)
        modes, dists, seen = set(), set(), 0
        for _ in range(6):
            time.sleep(0.5)
            st = hstate()
            if not st["ok"]:
                break
            for m in st["mons"]:
                if m.get("id") == mid:
                    seen += 1
                    modes.add(m.get("mode"))
                    dists.add(m.get("dist", m.get("distance")))
        cur = ai_counters(mxl_text())
        alive = hstate()["ok"] or (time.sleep(2) or hstate()["ok"])  # one retry: a `state` line can be late
        d = ai_delta(prev, cur) if cur else None
        prev = cur or prev
        acts = (d["wait"] + d["attack"] + d["enemy"] + d["charge"] + d["walk"] + d["s1"] + d["s2"] + d["s3"] + d["s4"]) if d else 0
        moved = len(modes) > 1 or len(dists) > 1
        # seen == 0 (it died within the first half second, or the listing is full of its summons) is judged on the counters alone
        good = alive and d is not None and d["thinks"] > 0 and (moved or acts > 0)
        if not good:
            bad.append(nm)
        notes.append("%d %s: %s, thinks %s (wait %s walk %s attack %s+%s charge %s skills %s), modes %s, %d distances, listed %d times%s" % (
            cls, nm, "PASS" if good else "FAIL", d and d["thinks"], d and d["wait"], d and d["walk"], d and d["attack"], d and d["enemy"],
            d and d["charge"], d and [d["s1"], d["s2"], d["s3"], d["s4"]], sorted(x for x in modes if x is not None), len(dists), seen,
            "" if alive else ", GAME GONE"))
        if cls in (156, 1244, 1729):
            shots.append(sh("medianai_%d" % cls))
        H("kill %d" % mid)  # by id: the listing can be full of unkillable summons (Malthael's dark nephalems, class 1239)
        if not alive:
            break
    clean_area()
    god(False)
    add(name, "PASS" if not bad and users else "FAIL", "%d of %d users acted%s%s | %s" % (
        len(users) - len(bad) - len(skipped), len(users), (" (FAILED: %s)" % ", ".join(bad)) if bad else "",
        (" (not spawnable by the harness: %s)" % ", ".join(skipped)) if skipped else "", " | ".join(notes)), shots)


def check_median_ai_controlled():
    """The controlled branch of andariel_ai: Median's gate is the monster's "last mode" field (monster data +0x68 in D2R, set by
    the unit-mode setter 0x4475xx to the mode being left, unless that is 1): 3 or 0x13 once a hit recovery ended. A spawned
    Maghda (1693) is hit through the game's damage path with `hit ... stagger` (GetHit forced); the `mxl` counter
    `controlled thinks` must stay 0 before the first hit, rise after it, and the game must keep running."""
    name = "Median andariel_ai: controlled branch runs after a hit recovery (last mode GetHit)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    cls = 1693
    god(True)
    goto(2)
    close_menu()
    kill_all_near()
    c0 = ai_counters(mxl_text())
    if c0 is None:
        god(False)
        return add(name, "FAIL", "the `mxl` monster ai line has no counters")
    mid = spawn_id(cls)
    if mid is None:
        god(False)
        return add(name, "BLOCKED", "could not spawn Maghda")
    time.sleep(1.0)
    c1 = ai_counters(mxl_text())
    log, seq, modes = [], [], []
    for i in range(6):
        ok, lines = H("hit mon:%d phys 1280 stagger" % mid)  # 5 life points; GetHit forced
        log += lines[:1]
        time.sleep(0.15)
        modes += [m.get("mode") for m in hstate()["mons"] if m.get("class") == cls]
        time.sleep(1.0)
        seq.append(ai_counters(mxl_text())["controlled"] - c1["controlled"])
        if seq[-1] > 0 and i >= 2:
            break
    time.sleep(1.5)
    c2 = ai_counters(mxl_text())
    alive = hstate()["ok"]
    before = c1["controlled"] - c0["controlled"]
    after = c2["controlled"] - c1["controlled"]
    shot = sh("medianai_controlled")
    clean_area()
    god(False)
    good = alive and before == 0 and after > 0 and c2["thinks"] > c1["thinks"]
    add(name, "PASS" if good else "FAIL",
        "controlled thinks before the first hit +%d (must be 0), after the hits +%d (must be > 0); thinks %d -> %d; controlled thinks after each staggering hit %s; monster modes right after the hits %s; game alive %s" % (
            before, after, c1["thinks"], c2["thinks"], seq, modes, alive), [shot], log[:8])


def check_tyrael():
    """Tyrael's travel line (Act 4, class 367) is gated by Median's quest 28 bit 0 instead of D2R's quest 26
    (npc_services.cpp FixTravelGates). The `mxl` npc actions line must say `travel gates moved 1`; the NPC menu (`menu list`)
    is read with quest 26 done / quest 28 clear, both clear, and quest 28 set: the travel line may only be there with
    quest 28. The quest bits are put back afterwards."""
    name = "Tyrael travel line follows quest 28 (Median), not quest 26"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    moved = counter(mxl_text(), "npc actions", r"travel gates moved (\d+)")
    god(True)
    goto(103)
    close_menu()
    saved = {}
    for q in (26, 28):
        _, l = H("quest %d 0 get" % q)
        saved[q] = bool(l) and l[0].rstrip().endswith("= 1")
    seen = {}
    for q, v in ((26, 0), (28, 0)):  # the first talk plays Tyrael's long speech and can miss the menu: talk once for nothing
        H("quest %d 0 %s" % (q, "set" if v else "clear"))
    npc_menu(367)
    close_menu()
    time.sleep(2)
    for q26, q28 in ((1, 0), (0, 0), (0, 1), (1, 1)):
        for q, v in ((26, q26), (28, q28)):
            H("quest %d 0 %s" % (q, "set" if v else "clear"))
        menu = npc_menu(367)
        seen[(q26, q28)] = menu
        close_menu()
        time.sleep(1)
    for q, v in saved.items():
        H("quest %d 0 %s" % (q, "set" if v else "clear"))
    god(False)
    if any(v is None for v in seen.values()):
        return add(name, "BLOCKED", "Tyrael's menu did not open in every state: %s" % {k: (v is not None) for k, v in seen.items()},
                   [sh("tyrael")], [("%s: %s" % (k, v)) for k, v in seen.items() if v is not None][:6])
    # the travel line is the one whose handler is 0x1162f0 (string 0x58d2); the other lines (talk, mercenary resurrect) have
    # their own conditions and are not looked at
    has = {k: any("handler=image+0x1162f0" in ln for ln in v) for k, v in seen.items()}
    gated = all(has[(q26, q28)] == bool(q28) for q26, q28 in has)
    log = []
    for k, v in seen.items():
        log += ["quest 26 %d, quest 28 %d:" % k] + v
    add(name, "PASS" if gated and moved == 1 else "FAIL",
        "`mxl` travel gates moved %s; travel line shown by (quest 26, quest 28): %s; it must appear with quest 28 only (bits restored to %s)" % (
            moved, ", ".join("%s -> %s" % (k, v) for k, v in has.items()), saved), [sh("tyrael")], log)


# ------------------------------------------------------------------ the "verify" rows of docs/unported.md (lane verify-checks)
# Deterministic where the engine allows it: the harness verbs hit / avoid / itemroll / colour / req / cstat (docs/testing.md)
# call the game's own damage, avoid, item generator, colour and requirement functions on units set up with `stat`.

def hv(cmd, verb=None, timeout=15):
    """One harness line -> (ok, first output line starting with the verb, all lines)."""
    ok, lines = H(cmd, timeout)
    verb = verb or cmd.split()[0]
    first = next((l for l in lines if l.startswith(verb + " ") or l.startswith(verb + "=")), lines[0] if lines else "")
    return ok, first, lines


def rd(ref, stat, layer=None):
    """Value of a stat of player / merc / mon:<id> (the base the checks restore afterwards)."""
    _, lines = H("stat %s %d%s" % (ref, stat, (" %d" % layer) if layer is not None else ""))
    return stat_of(lines)


def setstat(ref, stat, value, layer=None):
    H("stat %s %d%s set %d" % (ref, stat, (" %d" % layer) if layer is not None else "", value))


BIG_LIFE = 2097151  # 8191 life points in D2's 8.8 fixed point


def hit(ref, elem, amount, attacker=None):
    """One `hit`: the target at full life, returns (lost raw, absorbed raw, result flags, the element's field after the step) or None."""
    setstat(ref, 7, BIG_LIFE)
    setstat(ref, 6, BIG_LIFE)
    for _ in range(8):  # result 0: the engine ignored the hit (just arrived in the area, hit recovery); try again
        ok, line, _l = hv("hit %s %s %d%s" % (ref, elem, amount, (" " + attacker) if attacker else ""), "hit")
        m = re.search(r"life=(-?\d+)->(-?\d+) lost=\S+ absorbed=(-?\d+) result=0x(\w+)(?: field=(-?\d+))?", line)
        if not ok or not m:
            return None
        if int(m.group(4), 16) != 0:
            break
        time.sleep(1)
    return int(m.group(1)) - int(m.group(2)), int(m.group(3)), int(m.group(4), 16), int(m.group(5)) if m.group(5) else None


def spawn_attacker(cls=1):
    ok, lines = H("spawn %d" % cls)
    m = re.search(r"spawned class \d+ id=(\d+)", " ".join(lines))
    return ("mon:%s" % m.group(1)) if m else None


def leftover_monsters():
    """Live monsters `h state` lists around the player that are not town NPCs (it lists at most 60 within 40 units)."""
    st = hstate()
    return [m for m in st["mons"] if not m.get("npc") and m.get("mode") not in (0, 12)] if st["ok"] else []


def clean_area():
    """Kill every monster that can be killed around the player. What survives (the dark nephalems Malthael's AI summons in `medianai`,
    class 1239, are unkillable) stays in the level for the rest of the game and kills a later check's character the moment it
    arrives (a level 150 character died within two seconds of `cheat goto 2`): only a new game removes it. Save and Exit + Play puts
    the character in town, and the area is entered again."""
    st = hstate()
    area = st["player"].get("area") if st["ok"] else None
    if area in (None, 1):
        return
    clear_mons()
    kill_all_near()
    left = leftover_monsters()
    if left:
        g.log("clean_area: %d monsters cannot be killed (%s): a new game clears the level" % (
            len(left), ", ".join(str(m.get("class")) for m in left[:6])))
        revive_if_dead()  # what survives may have killed the character meanwhile; a dead one has no pause menu (Esc respawns it in the town)
        if not leave_and_reenter():
            return
        goto(area)
        close_menu()
        kill_all_near()


def fight_ready():
    """Outside the town (damage and avoidance run there), no god mode, no leftovers of the earlier check."""
    god(False)
    st = hstate()
    if st["player"].get("area") != 2:
        goto(2)
    close_menu()
    clean_area()


def have_merc():
    _, lines = H("merc")
    return any(l.startswith("merc id=") for l in lines)


def ensure_merc():
    """A hired mercenary (Kashya, act 1 Rogue) standing next to the player in the field. Starts from any state of the character: a
    dead character is revived first (it cannot hire), the old mercenary may be dead or missing (the hire replaces it), gold is
    set, the hire quest is set, the hirer's list is made again for every hire (as the client's hire menu does: a list made long before
    is the suspected cause of the one full-suite run where the server refused all entries), and when the server refuses one list
    entry the next free one is tried."""
    revive_if_dead()
    if not have_merc():
        for attempt in range(3):
            if hstate()["player"].get("area") != 1:
                goto(1)
            close_menu()
            H("gold set 20000 0")
            H("quest 2 0 set")  # Kashya hires once Blood Raven is dead (Median's gate is the quest alone)
            hired = False
            for n in range(6):  # `hire` counts the free entries of the list (hired / unavailable ones are skipped)
                ok, lines = H("hire 150 %d reopen" % n)
                if ok:
                    hired = True
                    break
                g.log("ensure_merc: attempt %d, free entry %d: %s" % (attempt, n, " | ".join(lines)[-200:]))
                if any("no such NPC" in ln for ln in lines):
                    H("spawn 150")  # the hirer is not loaded yet
                    time.sleep(2)
                elif any("no free entry" in ln for ln in lines):
                    break
                else:
                    time.sleep(1)
            if hired or have_merc():
                break
            # The server refused every entry (seen once in a full suite, when the character had stood in town a long time with a
            # corpse record and a hire list made long before): start the hire over from a fresh state - a hirer copy next to the
            # character (the handler checks the distance), then a new town entry (the hire lists are rebuilt per game session).
            g.log("ensure_merc: attempt %d refused, state: %s" % (attempt, hstate()["player"]))
            H("spawn 150")
            time.sleep(3)
            if attempt >= 1:
                goto(2)
                time.sleep(3)
            time.sleep(2)
    if not have_merc():
        return False
    if hstate()["player"].get("area") != 2:
        goto(2)
    for _ in range(30):  # the mercenary follows a few seconds after the player's area change
        if player_dead(hstate()["player"]):  # killed on arrival: revive (new game) and come back
            revive_if_dead()
            goto(2)
            kill_all_near()
        if H("stat merc 7")[0]:
            setstat("merc", 7, BIG_LIFE)  # a spawned monster would kill a level-4 mercenary before the check starts
            setstat("merc", 6, BIG_LIFE)
            return True
        time.sleep(1)
    return False


def merc_boost():
    """Strength / dexterity / level high enough that the requirement check judges the gate under test only."""
    setstat("merc", 0, 900)
    setstat("merc", 2, 900)
    setstat("merc", 12, 90)


def check_resistcap():
    name = "Max resistance cap 90: player and mercenary (fire / lightning / cold / magic, max-resist 0 / +10 / +50)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    fight_ready()  # first: it kills everything near, the mercenary too
    if not ensure_merc():
        return add(name, "BLOCKED", "no mercenary could be hired")
    atk = spawn_attacker()
    if atk is None:
        return add(name, "BLOCKED", "no attacker monster")
    elems = [("fire", 39, 40), ("ltng", 41, 42), ("cold", 43, 44), ("magic", 37, 38)]
    cases = [(0, 0.25), (10, 0.15), (50, 0.10)]  # resist 200; the cap is 75 + max-resist, at most 90 (95 would be 5%)
    amount, bad, rows = 100000, [], []
    for ref, attacker in (("player", atk), ("merc", atk)):  # never the nearest monster: that is the hired mercenary
        saved = {s: rd(ref, s) for e in elems for s in e[1:]}
        # Median's stat 184 (D2R 369) cuts the damage after the resistance, and an item of the character can carry it (the level 32
        # test character wields a weapon with 25%, so every hit did 75% of the cap's share): `stat set` writes the base value, so what
        # is left after zeroing it is what the gear gives, and the expectation is the cap's share cut by that.
        setstat(ref, 369, 0)
        cut = rd(ref, 369) or 0
        for elem, res, mx in elems:
            for add_max, want in cases:
                setstat(ref, res, 200)
                setstat(ref, mx, add_max)
                r = hit(ref, elem, amount, attacker)
                got = r[0] / amount if r else None
                want_cut = _reduce(round(want * amount), cut) / amount
                rows.append("%s %s max+%d: %s%%" % (ref, elem, add_max, "-" if got is None else "%.1f" % (got * 100)))
                if got is None or abs(got - want_cut) > 0.006:
                    bad.append("%s %s max+%d took %s (want %.1f%%: cap share %d%%, stat 184 from other sources %d%%)" % (
                        ref, elem, add_max, rows[-1].split(": ")[1], want_cut * 100, round(want * 100), cut))
        for s, v in saved.items():
            setstat(ref, s, v or 0)
        setstat(ref, 369, 0)
    H("kill nearest 1")
    panel_rows, panel_bad, panel_shots = _resistcap_panel()
    bad += panel_bad
    add(name, "PASS" if not bad else "FAIL",
        "resist 200 against a 100000-unit hit (damage taken; the cap's share cut by the gear's stat 184, if any): %s; character sheet: %s" % (
            "; ".join(rows) if not bad else "; ".join(bad), "; ".join(panel_rows)),
        [sh("resistcap")] + panel_shots, rows + panel_rows)


RESIST_PANEL_BOX = (395, 505, 525, 600)  # the Fire / Cold / Lightning / Poison rows of the HD character sheet (1600 x 900 client)
RESIST_PANEL_STATS = ((39, 40), (41, 42), (43, 44))  # fire, lightning, cold: resistance, maximum


def _resistcap_panel():
    """What the character sheet prints for the resistance rows at resistance 150 and maximum +0 / +10 / +15 / +16 / +20 / +50 (client
    copy of the stats, `cstat set`). The sheet is read by picture: the crop of the three elemental rows must be the same for every
    maximum from +15 up (75 + max is 90 and more, the cap shows 90) and must differ between +0, +10 and +15 (75 / 85 / 90). Without
    the compare patch the sheet showed 91% at +16..+19 while damage stayed at 90 (docs/unported.md). `MXL_CONTROL=combat` (the part
    off: 95 everywhere) expects +16 to differ from +15. Also logs the bytes of the three clamp sites (`peek`)."""
    from PIL import Image, ImageChops, ImageStat
    rows, bad, shots = [], [], []
    control = "combat" in CONTROL
    ok, lines = H("peek exe+14e728f 12")
    rows.append("sheet compare+clamp bytes %s" % (re.search(r"bytes=(\w+)", " ".join(lines)) or [0, "?"])[1])
    ok, lines = H("peek exe+14f4686 8")
    rows.append("hireling clamp bytes %s" % (re.search(r"bytes=(\w+)", " ".join(lines)) or [0, "?"])[1])
    stats = [s for pair in RESIST_PANEL_STATS for s in pair]
    saved = {}
    for s in stats:
        ok, lines = H("cstat %d" % s)
        m = re.search(r"cstat \d+:0 = (-?\d+)", " ".join(lines))
        if not ok or m is None:
            return rows, ["cannot read client stat %d" % s], shots
        saved[s] = int(m[1])
    crops = {}
    try:
        goto(1)
        close_menu()
        for mx in (0, 10, 15, 16, 20, 50):
            for res, mxs in RESIST_PANEL_STATS:
                H("cstat %d set 150" % res)
                H("cstat %d set %d" % (mxs, mx))
            if H("statorder open")[0] is False:
                bad.append("sheet did not open")
                break
            time.sleep(1.5)
            shot = "resistcap_sheet_%d" % mx
            shots.append(sh(shot))
            H("statorder close")
            time.sleep(0.5)
            crops[mx] = Image.open(_shot_path(shot)).convert("RGB").crop(RESIST_PANEL_BOX)
    finally:
        for s, v in saved.items():
            H("cstat %d set %d" % (s, v))
        H("statorder close")

    def diff(a, b):
        d = ImageChops.difference(crops[a], crops[b])
        return sum(ImageStat.Stat(d).mean) / 3.0
    if len(crops) == 6:
        same = {mx: diff(15, mx) for mx in (16, 20, 50)}
        far = {"0/10": diff(0, 10), "10/15": diff(10, 15)}
        rows.append("sheet rows, mean pixel difference to +15: %s; +0/+10 %.2f, +10/+15 %.2f" % (
            ", ".join("+%d %.2f" % kv for kv in same.items()), far["0/10"], far["10/15"]))
        for pair, d in far.items():
            if d < 0.3:
                bad.append("sheet rows at max %s look the same (difference %.2f): the sheet did not follow the stat" % (pair, d))
        if control:
            if same[16] < 0.3:
                bad.append("control (combat off): +16 reads as +15 on the sheet, the part is not off")
        else:
            for mx, d in same.items():
                if d >= 0.3:
                    bad.append("sheet at maximum +%d differs from +15 by %.2f: the number is not clamped to 90 like the damage" % (mx, d))
    return rows, bad, shots


def _reduce(amount, pct):
    if amount == 0 or pct == 0:
        return amount
    return max(amount - amount * pct // 100, 256)


def _credit(amount, divisor, pct, tpct):
    if amount != 0 and divisor != 0:
        amount = max(amount // divisor, 256)
    return _reduce(_reduce(amount, pct), tpct)


def check_absorb():
    name = "Absorb credit stats 184 / 189 / 417 (D2R 369 / 373 / 446): the healed amount"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    fight_ready()
    elem_res = [37, 39, 41, 43]
    saved = {s: rd("player", s) for s in elem_res + [142, 143, 146, 148, 369, 373]}
    saved_t = {l: rd("player", 446, l) for l in (1, 3, 4)}
    for s in elem_res:
        setstat("player", s, 0)
    setstat("player", 369, 0)  # `stat set` writes the base value; what is left is what other sources give
    base184 = rd("player", 369)
    amount, rows, bad = 100000, [], []

    def probe(label, elem, want):
        # the first hit after a stat write can read healed 0 (the game folds the stat change in on its next frame, as hit() waits for
        # a result): ask again, a short wait between, until the answer matches or the tries are gone; the last answer counts
        got = None
        for attempt in range(5):
            r = hit("player", elem, amount)
            got = r[1] if r else None
            if got is not None and abs(got - want) <= 2:
                break
            time.sleep(1)
        rows.append("%s: healed %s (want %s)" % (label, got, want) + ("" if attempt == 0 else " [after %d tries]" % (attempt + 1)))
        if got is None or abs(got - want) > 2:
            bad.append(rows[-1])

    setstat("player", 142, 30)  # 30% of the fire damage is absorbed: 30000
    probe("fire absorb 30%", "fire", _credit(30000, 0, base184, 0))
    setstat("player", 369, 50)
    p = rd("player", 369)
    probe("+ stat 184 -> %d%%" % p, "fire", _credit(30000, 0, p, 0))
    setstat("player", 369, 0)
    setstat("player", 373, 4)
    probe("+ stat 189 divisor 4", "fire", _credit(30000, 4, base184, 0))
    setstat("player", 373, saved[373] or 0)
    setstat("player", 446, 50, 1)
    probe("+ stat 417 layer 1 (fire) 50%", "fire", _credit(30000, 0, base184, 50))
    setstat("player", 148, 30)
    probe("cold with 417 layer 1 only (unchanged)", "cold", _credit(30000, 0, base184, 0))
    setstat("player", 446, 0, 1)
    setstat("player", 146, 30)
    setstat("player", 446, 50, 3)
    probe("magic with 417 layer 3 50%", "magic", _credit(30000, 0, base184, 50))
    setstat("player", 446, 0, 3)
    setstat("player", 142, 60)
    probe("percent limited to 40%", "fire", _credit(40000, 0, base184, 0))
    setstat("player", 142, 30)
    setstat("player", 143, 100)
    probe("percent 30 + flat 100", "fire", _credit(30000, 0, base184, 0) + _credit(25600, 0, base184, 0))
    for s, v in saved.items():
        setstat("player", s, 0 if (v is None or s == 369) else v)
    for l, v in saved_t.items():
        setstat("player", 446, v or 0, l)
    add(name, "PASS" if not bad else "FAIL",
        "100000-unit hits on the player (stat 184 from other sources: %s%%); healed amount = D2R's cut run through the three stats: %s"
        % (base184, "; ".join(rows)), [sh("absorb")], rows)


def _field_cut(field, pct):
    """Median's percent step on a damage field (D2Sigma 0x10057f10): no floor, the cut truncates."""
    return field - field * pct // 100 if field > 0 and pct else field


def _field_reduce(field, divisor, pct, tpct, duration=False):
    """What Median leaves of a field once D2R's step is done: 189 (divide, or halve a duration to 5 at least), 184, 417."""
    if field <= 0:
        return field
    if divisor:
        field = max(field >> 1, 5) if duration else field // divisor
    if duration:
        return field
    return _field_cut(_field_cut(field, pct), tpct)


def check_damagered():
    name = "Damage reduction stats 184 / 189 / 417 (D2R 369 / 373 / 446) on the incoming damage itself (D2Sigma 0x10057c10)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    fight_ready()
    elems = [("fire", 39, 40, 1), ("ltng", 41, 42, 2), ("cold", 43, 44, 4), ("magic", 37, 38, 3)]
    absorb = [142, 143, 144, 145, 146, 147, 148, 149]
    stats = [s for e in elems for s in e[1:3]] + absorb + [369, 373]
    saved = {s: rd("player", s) for s in stats}
    saved_t = {l: rd("player", 446, l) for l in range(0, 6)}
    for e in elems:  # resist 200 with no max-resist: the cap leaves 25% of every hit, whatever the difficulty's penalty
        setstat("player", e[1], 200)
        setstat("player", e[2], 0)
    for s in absorb:  # no absorb unless a probe asks for it
        setstat("player", s, 0)
    setstat("player", 369, 0)  # `stat set` writes the base value; what is left is what other sources give
    setstat("player", 373, 0)
    for l in range(0, 6):
        setstat("player", 446, 0, l)
    p0 = rd("player", 369) or 0
    amount, pre, rows, bad = 100000, 25000, [], []

    def note(label, got, want, ok):
        rows.append("%s: %s (want %s)" % (label, got, want))
        if not ok:
            bad.append(rows[-1])

    def probe(label, elem, want, amt=amount):
        r = hit("player", elem, amt)
        note(label, "field %s lost %s" % (r and r[3], r and r[0]), want, r is not None and r[3] == want and abs(r[0] - want) <= 2)

    probe("baseline, 184 from other sources %d%%" % p0, "fire", _field_reduce(pre, 0, p0, 0))
    setstat("player", 373, 4)
    probe("189 divisor 4", "fire", _field_reduce(pre, 4, p0, 0))
    setstat("player", 373, 0)
    setstat("player", 369, 50)
    p = rd("player", 369)
    probe("184 -> %d%%" % p, "fire", _field_reduce(pre, 0, p, 0))
    setstat("player", 369, 0)
    setstat("player", 446, 50, 1)
    probe("417 layer 1 (fire) 50%", "fire", _field_reduce(pre, 0, p0, 50))
    probe("417 layer 1 on cold (unchanged)", "cold", _field_reduce(pre, 0, p0, 0))
    setstat("player", 446, 0, 1)
    for elem, _res, _mx, layer in elems:
        setstat("player", 446, 40, layer)
        probe("417 layer %d (%s) 40%%" % (layer, elem), elem, _field_reduce(pre, 0, p0, 40))
        setstat("player", 446, 0, layer)
    # all three on odd numbers: the order (divide, 184, 417) and the truncation of every step show in the exact field
    setstat("player", 373, 3)
    setstat("player", 369, 33)
    p = rd("player", 369)
    setstat("player", 446, 17, 1)
    probe("all three on 25001 (189 3, 184 %d%%, 417 17%%)" % p, "fire", _field_reduce(25001, 3, p, 17), amt=100005)
    setstat("player", 373, 0)
    setstat("player", 369, 0)
    setstat("player", 446, 0, 1)
    # the absorb credit is computed before these stats: 30% of the 25000 left by the resist is 7500, healed through 189 (and 184)
    setstat("player", 142, 30)
    setstat("player", 373, 4)
    r = hit("player", "fire", amount)
    want_heal, want_field = _credit(7500, 4, p0, 0), _field_reduce(17500, 4, p0, 0)
    note("fire absorb 30% + 189 divisor 4", "healed %s field %s" % (r and r[1], r and r[3]), "healed %s field %s" % (want_heal, want_field),
         r is not None and abs(r[1] - want_heal) <= 2 and r[3] == want_field)
    setstat("player", 142, 0)
    setstat("player", 373, 0)
    # durations: 189 halves a freeze / cold length (at least 5 frames); 184 / 417 leave it alone
    for elem in ("flen", "clen"):
        r0 = hit("player", elem, 400)
        base = r0[3] if r0 else None
        if base is None:
            bad.append("%s: no hit" % elem)
            continue
        for label, divisor, pct, tpct in (("189 divisor 4", 4, 0, 0), ("189 divisor 1000", 1000, 0, 0), ("184 50%, 417 50%", 0, 50, 50)):
            setstat("player", 373, divisor)
            setstat("player", 369, pct)
            setstat("player", 446, tpct, 0)
            r = hit("player", elem, 400)
            want = _field_reduce(base, divisor, 0, 0, duration=True)
            note("%s %s (base %s)" % (elem, label, base), r and r[3], want, r is not None and r[3] == want)
            setstat("player", 373, 0)
            setstat("player", 369, 0)
            setstat("player", 446, 0, 0)
    setstat("player", 373, 2)
    r = hit("player", "flen", 16)
    note("flen 16 with 189 (the floor of 5 frames)", r and r[3], 5, r is not None and r[3] == 5)
    setstat("player", 373, 0)
    # physical damage takes stat 417 with layer 0 (the layer Median passes for it)
    r0 = hit("player", "phys", amount)
    setstat("player", 446, 50, 0)
    r1 = hit("player", "phys", amount)
    want = _field_cut(r0[3], 50) if r0 and r0[3] is not None else None
    note("phys 417 layer 0 50%% of %s" % (r0 and r0[3]), r1 and r1[3], want, r1 is not None and want is not None and r1[3] == want)
    for s, v in saved.items():
        setstat("player", s, 0 if (v is None or s in (369, 373)) else v)
    for l, v in saved_t.items():
        setstat("player", 446, v or 0, l)
    add(name, "PASS" if not bad else "FAIL",
        "hits on the player at resist 200 (25%% of 100000 left) and freeze / cold lengths; the damage field after D2R's step must equal Median's "
        "formula exactly (divide, then 184, then 417, no floor): %s" % ("; ".join(rows) if not bad else "; ".join(bad)),
        [sh("damagered")], rows)


def _avoid_rate(ref, kind, stat, value, max_avoid, n=2000):
    setstat(ref, stat, value)
    setstat(ref, 380, max_avoid)
    for _ in range(6):
        ok, line, _l = hv("avoid %s %s %d" % (ref, kind, n), "avoid", 60)
        m = re.search(r"n=(\d+) .* success=(\d+)", line)
        if ok and not m:
            time.sleep(0.5)  # the result line was lost (console output race): ask again
            continue
        if ok and m and int(m.group(2)) == 0 and kind != "evade" and ref != "player" and "mode=1 " not in line:
            time.sleep(1.5)  # a walking mercenary can neither dodge nor avoid: wait until it stands
            continue
        break
    return (int(m.group(2)) / int(m.group(1))) if ok and m else None


def check_avoidcaps():
    name = "Avoid / dodge / evade caps (min(75, 60 + stat 380)): player and mercenary"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    fight_ready()  # first: it kills everything near, the mercenary too
    if not ensure_merc():
        return add(name, "BLOCKED", "no mercenary could be hired")
    kinds = [("dodge", "melee", 338), ("avoid", "missile", 339), ("evade", "evade", 340)]
    cases = [(100, 0, 0.60), (100, 10, 0.70), (100, 30, 0.75), (50, 0, 0.50)]  # (stat, stat 380, expected success rate)
    rows, bad = [], []
    for ref in ("player", "merc"):
        saved = {s: rd(ref, s) for s in (338, 339, 340, 380)}
        for label, kind, stat in kinds:
            for value, mx, want in cases:
                r = _avoid_rate(ref, kind, stat, value, mx)
                rows.append("%s %s %d (380=%d): %s" % (ref, label, value, mx, "-" if r is None else "%.1f%%" % (r * 100)))
                if r is None or abs(r - want) > 0.04:
                    bad.append("%s (want %d%%)" % (rows[-1], round(want * 100)))
            setstat(ref, stat, 0)
        for s, v in saved.items():
            setstat(ref, s, v or 0)
    add(name, "PASS" if not bad else "FAIL",
        "success rate of 2000 checks of the game's avoid function: %s" % ("; ".join(rows) if not bad else "; ".join(bad)),
        [sh("avoidcaps")], rows)


def _make_ring(lock):
    ok, lines = H("item rin 492=%d inv" % lock)
    m = re.search(r"item id=(\d+)", " ".join(lines))
    return int(m.group(1)) if ok and m else None


def _req(ref, cls=None):
    ok, lines = H("req %s%s" % (ref, (" as %d" % cls) if cls is not None else ""), 30)
    rows = {}
    for l in lines:
        if l.startswith("req id="):
            d = kv(l)
            rows[int(d["id"])] = {"usable": int(d["usable"]), "lock": int(d["lock"]), "weapon": int(d["weapon"]),
                                  "shield": int(d["shield"]), "types": [] if d["types"] == "-" else [int(x) for x in d["types"].split(",")],
                                  "code": d["code"]}
    return rows


def _merc_lists():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "src", "mxl_hirelings.h"), encoding="utf-8").read()
    ids = lambda t: tuple(int(x) for x in t.split(",") if int(x) >= 0)
    return {int(m): (int(e), ids(a), ids(d)) for m, e, a, d in re.findall(r"\{(\d+), (\d+), \{([-\d, ]+)\}, \{([-\d, ]+)\}\}", src)}


MERC_LISTS = _merc_lists()  # item type ids follow itemtypes.txt rows, which the build may renumber
# monster class -> (the character class it equips as, weapon / shield types allowed, types refused again): hireclasses (mxl_hirelings.h)


def check_classlock():
    name = "Class-locked items (stat 492): player of each class and each mercenary type"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    if not ensure_merc():
        return add(name, "BLOCKED", "no mercenary could be hired")
    merc_boost()
    H("packclear")  # `req` lists a limited number of items: earlier checks' leftovers pushed the rings off the list
    rings = {lock: _make_ring(lock) for lock in range(1, 9)}
    if not all(rings.values()):
        return add(name, "BLOCKED", "could not create the locked rings: %s" % rings)
    cls0 = hstate()["player"]["class"]
    rows, bad = [], []
    try:
        for cls in range(7):
            r = _req("player", cls)
            got = "".join(str(r[rings[l]]["usable"]) for l in range(1, 9))
            want = "".join("1" if (l == 8 or l - 1 == cls) else "0" for l in range(1, 9))
            rows.append("player class %d: locks 1-8 usable %s" % (cls, got))
            if got != want:
                bad.append("player class %d: usable %s, want %s" % (cls, got, want))
        for mcls, (equiv, _a, _d) in MERC_LISTS.items():
            r = _req("merc", mcls)
            got = "".join(str(r[rings[l]]["usable"]) for l in range(1, 9))
            want = "".join("1" if (l == 8 or l - 1 == equiv) else "0" for l in range(1, 9))
            rows.append("merc class %d (equips as class %d): locks 1-8 usable %s" % (mcls, equiv, got))
            if got != want:
                bad.append("merc class %d: usable %s, want %s" % (mcls, got, want))
    finally:
        H("class %d" % cls0)
    add(name, "PASS" if not bad else "FAIL",
        "`req` (the engine's requirement check, hooked for stat 492) of rings with lock 1-8 (lock = class + 1, 8 = nobody): %s"
        % ("; ".join(rows) if not bad else "; ".join(bad)), [], rows)


def check_hiregates():
    name = "Mercenary equip gates by hire class (weapon / shield types), all four hire classes"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    if not ensure_merc():
        return add(name, "BLOCKED", "no mercenary could be hired")
    merc_boost()
    for code in ("163", "139", "156", "104", "110", "158", "!1!", "tow", "l53", "115"):
        H("item %s inv" % code)  # best effort: the backpack may be full of the earlier ones
    rows, bad = [], []
    for mcls, (equiv, allow, deny) in MERC_LISTS.items():
        r = _req("merc", mcls)
        allowed = refused = 0
        for iid, it in r.items():
            if not (it["weapon"] or it["shield"]):
                continue
            want = (not any(t in deny for t in it["types"])) and any(t in allow for t in it["types"])
            if want:
                allowed += 1
            else:
                refused += 1
            if bool(it["usable"]) != want:
                bad.append("class %d item %s (%s types %s): usable %d, want %d" % (mcls, it["code"], iid, it["types"], it["usable"], want))
        rows.append("class %d: %d weapons / shields allowed, %d refused" % (mcls, allowed, refused))
        if allowed == 0 or refused == 0:
            bad.append("class %d: no %s item in the backpack to judge" % (mcls, "allowed" if allowed == 0 else "refused"))
    add(name, "PASS" if not bad else "FAIL",
        "`req merc as <class>` over the backpack weapons / shields: %s" % ("; ".join(rows) if not bad else "; ".join(bad[:6])), [], rows)


ETH_RATE = 0.026  # Median: rand(1000) <= 25


def check_itemrolls():
    n1 = "Socket roll (quality 1-3): rand() % 7, clipped to the base"
    n2 = "Ethereal roll: 2.6%, +25% defence, 75% durability"
    if not need_game():
        add(n1, "BLOCKED", "not in a game")
        return add(n2, "BLOCKED", "not in a game")
    tried = []
    for code in ("tow", "plt", "hax", "bsd"):  # a shield, body armour, an axe and a sword: the first base the ethereal gate lets through
        ok, line, _l = hv("itemroll %s 4000 q=2 ilvl=110" % code, "itemroll", 120)
        lines = _l
        m0 = re.search(r"ethereal=(\d+)", line)
        tried.append("%s %s" % (code, m0.group(1) if m0 else "-"))
        if ok and m0 and int(m0.group(1)) > 0:
            break
    m = re.search(r"n=(\d+) failed=(\d+) ilvl=(\d+) ethereal=(\d+) (?:\w+=\S+ )*?sockets=\[([^\]]*)\]", line)  # identified= / qualities= / automagic= come with it
    d = next((l for l in lines if l.startswith("itemroll def")), "")
    md = re.search(r"normal n=(\d+) sum=(\d+), ethereal n=(\d+) sum=(\d+); maxdur normal (\d+)\.\.(\d+), ethereal (\d+)\.\.(-?\d+)", d)
    if not (ok and m and md):
        add(n1, "BLOCKED", "itemroll answered: %s" % lines[:2])
        return add(n2, "BLOCKED", "itemroll answered: %s" % lines[:2])
    n = int(m.group(1))
    hist = {int(a): int(b) for a, b in (p.split(":") for p in m.group(5).split())}
    top = max(hist)
    exp = {k: n / 7.0 for k in range(top)}
    exp[top] = n * (7 - top) / 7.0
    bad = []
    for k in range(top + 1):
        sd = (exp[k] * (1 - exp[k] / n)) ** 0.5
        if abs(hist.get(k, 0) - exp[k]) > 4 * sd:
            bad.append("%d sockets: %d (want %.0f +- %.0f)" % (k, hist.get(k, 0), exp[k], 4 * sd))
    add(n1, "PASS" if not bad and top >= 3 else "FAIL",
        "%d items of the last base (quality 2): sockets histogram %s; expected 1/7 for 0..%d sockets and %d/7 for %d (D2R's own: a third of the items, rand(max)+1): %s"
        % (n, m.group(5), top - 1, 7 - top, top, "; ".join(bad) or "all within 4 sigma"), [], [line])
    eth = int(m.group(4))
    rate = eth / float(n)
    nn, sn, ne, se, dmin, dmax, emin, emax = (int(x) for x in md.groups())
    avg_n = sn / float(nn) if nn else 0
    avg_e = se / float(ne) if ne else 0
    ratio = avg_e / avg_n if avg_n else 0
    bad2 = []
    mean, sd = n * ETH_RATE, (n * ETH_RATE * (1 - ETH_RATE)) ** 0.5
    if abs(eth - mean) > 4 * sd:
        bad2.append("%d ethereal outside 4 sigma of Median's 2.6%% (%.0f +- %.0f; D2R's own would be 5%%)" % (eth, mean, 4 * sd))
    if ne and not 1.17 <= ratio <= 1.33:
        bad2.append("defence ratio %.2f (want 1.25; D2R 1.5)" % ratio)
    want_dur = dmax * 75 // 100
    if ne and (emin != want_dur or emax != want_dur):
        bad2.append("ethereal max durability %d..%d (want %d = 75%% of %d)" % (emin, emax, want_dur, dmax))
    add(n2, "PASS" if not bad2 and ne >= 40 else "FAIL",
        "%d items at item level %s (ethereal count per base tried: %s): %d ethereal (%.2f%%); defence average %.1f -> %.1f (x%.2f); max durability %d -> %d..%d%s"
        % (n, m.group(3), ", ".join(tried), eth, rate * 100, avg_n, avg_e, ratio, dmax, emin, emax, ("; " + "; ".join(bad2)) if bad2 else ""),
        [], [line, d])
    # quality 1 (low): D2R's own gate never lets it through, Median's roll does (qualities word2 = 25 for quality 1 too)
    n3 = "Ethereal roll, quality 1 (low): 2.6%, +25%, 75% durability"
    ok, line, _l = hv("itemroll %s 4000 q=1 ilvl=110" % (tried[-1].split()[0]), "itemroll", 120)
    m3 = re.search(r"n=(\d+) failed=(\d+) ilvl=(\d+) ethereal=(\d+)", line)
    d3 = next((l for l in _l if l.startswith("itemroll def")), "")
    md3 = re.search(r"normal n=(\d+) sum=(\d+), ethereal n=(\d+) sum=(\d+); maxdur normal (\d+)\.\.(\d+), ethereal (\d+)\.\.(-?\d+)", d3)
    if not (ok and m3 and md3):
        return add(n3, "BLOCKED", "itemroll answered: %s" % _l[:2])
    n_, e_ = int(m3.group(1)), int(m3.group(4))
    mean, sd = n_ * ETH_RATE, (n_ * ETH_RATE * (1 - ETH_RATE)) ** 0.5
    bad3 = []
    if abs(e_ - mean) > 4 * sd:
        bad3.append("%d ethereal outside 4 sigma of 2.6%% (%.0f +- %.0f)" % (e_, mean, 4 * sd))
    dmax3 = int(md3.group(6))
    if e_ and (int(md3.group(7)) != dmax3 * 75 // 100 or int(md3.group(8)) != dmax3 * 75 // 100):
        bad3.append("ethereal max durability %s..%s (want %d)" % (md3.group(7), md3.group(8), dmax3 * 75 // 100))
    add(n3, "PASS" if not bad3 and e_ >= 40 else "FAIL",
        "%d items at item level %s: %d ethereal (%.2f%%), max durability %d -> %s..%s%s"
        % (n_, m3.group(3), e_, 100.0 * e_ / n_, dmax3, md3.group(7), md3.group(8), ("; " + "; ".join(bad3)) if bad3 else ""), [], [line, d3])


# Sockets and automagic for every quality (docs/sigma-patch-audit.md item 2; D2Sigma 0x1007e240, qualities.txt MaxSock /
# Automagics). Median: qualities 1-4 roll rand % 7 sockets, qualities 5-9 get the base's maximum without a die, and the
# automagic roll (item level 100+, base with an auto prefix group) runs for every quality, sets and uniques included.
AQ_BASES = ("60@", "6@C", "!90", "87@", "!14", "@43", "3@P")  # Median bases: 6 sockets, auto prefix group 406 with a row for the type, set and unique items
AQ_NAMES = {1: "low", 2: "normal", 3: "superior", 4: "magic", 5: "set", 6: "rare", 7: "unique", 8: "crafted", 9: "tempered"}
AQ_N = 3000


def _aq_roll(code, quality, n=AQ_N):
    """`itemroll` of one base and quality -> dict (n, failed, ilvl, hist {sockets: count}, quals {quality: count}, auto) or None."""
    ok, line, lines = hv("itemroll %s %d q=%d ilvl=110" % (code, n, quality), "itemroll", 240)
    m = re.search(r"n=(\d+) failed=(\d+) ilvl=(\d+) ethereal=(\d+) (?:\w+=\S+ )*?sockets=\[([^\]]*)\] qualities=\[([^\]]*)\] automagic=(\d+)", line)
    if not (ok and m):
        return None
    pairs = lambda s: {int(a): int(b) for a, b in (p.split(":") for p in s.split())}
    return {"n": int(m.group(1)), "failed": int(m.group(2)), "ilvl": int(m.group(3)), "hist": pairs(m.group(5)),
            "quals": pairs(m.group(6)), "auto": int(m.group(7)), "line": " | ".join(lines), "code": code, "q": quality}


def _aq_pick_base():
    """First base that holds sockets (normal items reach 4+) and has an auto prefix group (normal items show automagic)."""
    tried = []
    for code in AQ_BASES:
        r = _aq_roll(code, 2, 1500)
        if r is None:
            tried.append("%s -" % code)
            continue
        top = max(r["hist"]) if r["hist"] else 0
        tried.append("%s top=%d auto=%d" % (code, top, r["auto"]))
        if top >= 4 and r["auto"] > 0:
            return code, top, tried
    return None, 0, tried


def check_allqualsockets():
    name = "Sockets and automagic for every quality (Median MaxSock / Automagics)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    code, top, tried = _aq_pick_base()
    if code is None:
        return add(name, "BLOCKED", "no base with 4+ sockets and an auto prefix among %s" % ", ".join(tried))
    rolls, log = {}, []
    for q in range(1, 10):
        r = _aq_roll(code, q)
        for other in AQ_BASES:  # a base without a set / unique row of the right level gets a lower quality: try the next base
            if r is not None and r["quals"].get(q, 0) >= 0.9 * r["n"] or other == code:
                continue
            r2 = _aq_roll(other, q)
            if r2 is not None and r2["quals"].get(q, 0) >= 0.9 * r2["n"]:
                r = r2
                break
        rolls[q] = r
        log.append(r["line"] if r else "q=%d: no answer" % q)
    bad, rows = [], []
    for q in range(1, 10):
        r = rolls[q]
        if r is None:
            bad.append("%s: itemroll gave no answer" % AQ_NAMES[q])
            continue
        n = r["n"]
        made = r["quals"].get(q, 0)
        if n < 100 or made < n * 0.9:
            rows.append("%s: generator gave quality %s for %d of %d (not judged)" % (AQ_NAMES[q], r["quals"], n - made, n))
            continue
        hist = r["hist"]
        if q <= 4:  # the die: 1/7 for 0 .. top-1, (7 - top)/7 for top
            exp = {k: n / 7.0 for k in range(top)}
            exp[top] = n * (7 - top) / 7.0
            for k in range(top + 1):
                sd = (exp[k] * (1 - exp[k] / n)) ** 0.5
                if abs(hist.get(k, 0) - exp[k]) > 4 * sd:
                    bad.append("%s: %d sockets %d (want %.0f +- %.0f)" % (AQ_NAMES[q], k, hist.get(k, 0), exp[k], 4 * sd))
            rows.append("%s (%s): sockets %s" % (AQ_NAMES[q], r["code"], " ".join("%d:%d" % kv_ for kv_ in sorted(hist.items()))))
        else:  # the base's maximum for every item
            at_top = hist.get(top, 0)
            die_made = sum(c for k, c in r["quals"].items() if k <= 4)  # a fallback to a die quality may have fewer
            if n - at_top > die_made:
                bad.append("%s: %d of %d items have the maximum of %d sockets, histogram %s" % (AQ_NAMES[q], at_top, n, top, hist))
            rows.append("%s (%s): sockets %s" % (AQ_NAMES[q], r["code"], " ".join("%d:%d" % kv_ for kv_ in sorted(hist.items()))))
    # automagic: D2R's switch applied it to 1-4, 6, 8, 9; Median's Automagics column adds 5 and 7 at the same rate
    old = [q for q in (1, 2, 3, 4, 6, 8, 9) if rolls[q] and rolls[q]["quals"].get(q, 0) >= 0.9 * rolls[q]["n"]]
    old_n = sum(rolls[q]["n"] for q in old)
    old_a = sum(rolls[q]["auto"] for q in old)
    p = old_a / float(old_n) if old_n else 0.0
    rows.append("automagic: " + ", ".join("%s %d/%d" % (AQ_NAMES[q], rolls[q]["auto"], rolls[q]["n"]) for q in range(1, 10) if rolls[q]))
    for q in (5, 7):
        r = rolls[q]
        if r is None or r["quals"].get(q, 0) < 0.9 * r["n"]:
            continue
        if r["auto"] == 0:
            bad.append("%s: no automagic affix in %d items (other qualities %.1f%%)" % (AQ_NAMES[q], r["n"], 100 * p))
            continue
        sd = (p * (1 - p) / r["n"]) ** 0.5
        if p > 0 and abs(r["auto"] / float(r["n"]) - p) > 5 * sd:
            bad.append("%s: automagic rate %.1f%% against %.1f%% of the qualities D2R covers" % (AQ_NAMES[q], 100.0 * r["auto"] / r["n"], 100 * p))
    add(name, "PASS" if not bad else "FAIL",
        "base %s (max %d sockets; tried %s), %d items per quality at item level %d: %s%s"
        % (code, top, ", ".join(tried), AQ_N, rolls[2]["ilvl"] if rolls[2] else 0, " | ".join(rows), ("; FAIL: " + "; ".join(bad)) if bad else ""),
        [], log)


def check_dye():
    name = "Dye colour (stat 368): the item colour byte and palette"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ensure_cube()
    H("cubeclear")
    ok, lines = H("item tow cube")
    m = re.search(r"item id=(\d+)", " ".join(lines))
    if not ok or not m:
        return add(name, "BLOCKED", "no item to dye: %s" % lines[:1])
    iid = m.group(1)
    rows, bad = [], []
    for v in list(range(0, 22)) + [-5]:
        setstat(iid, 368, v)
        ok, line, _l = hv("colour %s" % iid, "colour")
        d = kv(line)
        byte = int(d.get("byte", "0xee"), 16) if ok else None
        dyed = v >= 1
        want_idx = v - 1
        good = ok and ((d.get("palette") == "set" and byte is not None and (byte & 0x1f) == want_idx) if dyed else d.get("palette") == "none")
        rows.append("%d->%s" % (v, ("0x%02x" % byte) if byte is not None else "-"))
        if not good:
            bad.append("stat 368 = %d gave %s" % (v, line[:70]))
    H("cubeclear")
    add(name, "PASS" if not bad else "FAIL",
        "item colour function on a tower shield with stat 368 = 0..21 and -5: index = stat - 1 with a palette entry, 0 / negative = undyed; bytes: %s%s"
        % (" ".join(rows), ("; " + "; ".join(bad[:4])) if bad else ""), [], rows)


# Bug #50: N identical runes in one item stack (Median gems.txt: each socketed rune applies its own mods to the parent).
# Server side: the item is made with sockets in the backpack, each rune goes to the cursor (packet 0x19) and into the item
# (packet 0x28, as the client's socket click); the parent's stats and D2R's own tooltip are read after each rune.
RS_CASES = (  # (label, base code, socketed item, body location, Runemaster bonus (stat 510), player stat, gain per socketed item)
    ("armor", "706", "r02", "body", 0, 22, 3),  # Eld: +3 maximum damage in armor / helm / shield (gems.txt), no defense
    ("helm", "crn", "r02", "head", 0, 22, 3),
    ("shield", "tow", "r02", "lhand", 0, 22, 3),
    ("weapon", "bsd", "r08", "rhand", 0, 39, 30),  # Ral: +30 fire resist in a weapon
    ("gem", "bsd", "gpv", "rhand", 0, 119, 50),  # control: gems (type gem) always worked
    ("jewel", "bsd", "jew 39=30 q=4", "rhand", 0, 39, 30),  # control: jewels (D2R type 58) always worked
    ("runemaster", "706", "r02", "body", 20, 182, None),  # each rune's stat 483 (D2R 512) feeds the Runemaster defense bonus
)
RS_REQ = ((0, 1000), (2, 1000), (12, 120))  # strength, dexterity, level: Median turns off the stats of an item whose requirements fail
RS_BODY = {"head": 1, "body": 3, "rhand": 4, "lhand": 5}


def _rs_item(spec):
    return _rs_item_of(*H("item " + spec))


def _rs_item_of(ok, lines):
    m = re.search(r"item id=(\d+) code=\S+ class=\d+ page=(\d+) x=(\d+) y=(\d+)", " ".join(lines))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if ok and m else None


def check_runestack():
    name = "Socketed runes stack (bug #50): 0-3 Eld in armor / helm / shield, 0-3 Ral in a weapon, gem and jewel controls"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    rows, bad = [], []
    rm0 = rd("player", 510)
    req0 = [(st, rd("player", st)) for st, _ in RS_REQ]
    for st, val in RS_REQ:
        setstat("player", st, val)
    for label, base, rune, loc, rm, stat, per in RS_CASES:
        for c in (base, rune.split()[0]):
            H("remove %s 9" % c)
        setstat("player", 510, rm)
        for l in (loc, "rhand") if loc == "lhand" else (loc,):  # a two-handed weapon blocks the shield
            H("unequip %s" % l)
        for _try in range(20):  # 194=3 sets the count; the socketed flag (0x800) comes from the item's own socket roll
            ok, lines = H("equip %s 194=3 q=2 %s" % (base, loc))
            it = _rs_item_of(ok, lines)
            fl = re.search(r"flags=0x([0-9a-f]+)", " ".join(lines))
            if it is None or (fl and int(fl.group(1), 16) & 0x800):
                break
            H("unequip %s" % loc)
        if it is None or not (fl and int(fl.group(1), 16) & 0x800):
            bad.append("%s: no socketed %s item" % (label, base))
            continue
        tid = it[0]
        time.sleep(0.4)
        vals = [rd("player", stat) or 0]
        for k in range(1, 4):
            r = _rs_item(rune)
            if r is None:
                bad.append("%s: no %s" % (label, rune))
                break
            H("pkt 19 " + _le(r[0], r[2], r[3], r[1]))  # to the cursor
            time.sleep(0.4)
            # D2R's 0x28 (0x4c0b20 -> 0x4f9f40): cursor id, target id, body location (1-10 when worn), else page and x / y (u16)
            H("pkt 28 " + _le(r[0], tid, RS_BODY[loc], it[1], it[2] | it[3] << 16))
            time.sleep(0.6)
            _, cur = H("cursor")
            if "empty" not in " ".join(cur):
                bad.append("%s: socketed item %d stayed on the cursor" % (label, k))
                H("pkt 17 " + _le(r[0]))
                break
            vals.append(rd("player", stat) or 0)
        gains = [v - vals[0] for v in vals]
        step = per if per is not None else gains[1] if len(gains) > 1 else 0
        want = [k * step for k in range(len(gains))]
        rows.append("%s %s+%s stat %d: %s" % (label, base, rune.split()[0], stat, "/".join(str(v) for v in vals)))
        if len(vals) == 4 and (gains != want or not step):
            bad.append("%s: stat %d gains %s, want %s" % (label, stat, gains, want if step else "> 0 per rune"))
        H("unequip %s" % loc)
        H("remove %s 9" % base)
    setstat("player", 510, rm0 or 0)
    for st, val in req0:
        if val is not None:
            setstat("player", st, val)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad))


def check_goldclient():
    name = "Gold payment: the client's gold follows the server after a cube payment"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    ensure_cube()
    H("cubeclear")
    H("stat player 532 set 140")
    H("gold set 400000 100000")
    H("item 0u1 cube uniq=30 532=1")
    H("item f667 cube")
    ok1, l1 = H("cubecraft")
    time.sleep(1.5)
    _, s1 = H("gold get")
    _, c14 = H("cstat 14")
    _, c15 = H("cstat 15")
    H("cubeclear")
    H("gold set 20000 100000")
    H("item 0u1 cube uniq=30 532=1")
    H("item f667 cube")
    H("item f667 cube")
    ok2, l2 = H("cubecraft")
    time.sleep(1.5)
    _, s2 = H("gold get")
    _, d14 = H("cstat 14")
    _, d15 = H("cstat 15")
    H("cubeclear")
    H("stat player 532 set 0")
    a = (stat_of(c14), stat_of(c15))
    b = (stat_of(d14), stat_of(d15))
    good = ok1 and ok2 and a == (350000, 100000) and b == (0, 20000)
    add(name, "PASS" if good else "FAIL",
        "row 6327: server %s, client carried/bank %s (want 350000/100000); row 6328 from 20000/100000: server %s, client %s (want 0/20000)"
        % (s1[0], a, s2[0], b), [], l1 + l2)


def leave_and_reenter(menu_open=False):
    """Esc menu -> Save and Exit -> character select -> Play (the same character). `menu_open`: the pause menu is already up."""
    if not menu_open:
        g.key("esc")
        time.sleep(1.5)
    left = False
    for attempt in range(3):  # a click the game did not take (seen once in a full group1 run) is repeated: first on the open menu, then with a new Esc
        if attempt == 2:
            g.key("esc")
            time.sleep(1.5)
        g.click(*g.UI["save_exit"])
        time.sleep(9)
        for _ in range(8):  # the save of a character with a long session behind it takes longer than 9 s
            if not g.in_game():
                break
            time.sleep(3)
        left = not g.in_game()
        if left:
            break
    STATE["in_game"] = False
    if not left:  # the click did not leave the game (a dead character has no pause menu): the game goes on
        STATE["in_game"] = True
        return False
    time.sleep(2)
    return enter_game()


def clear_quest_bits(q, only=None):
    """Clear the set bits of quest record `q` (the game's current difficulty) through the harness; `only` limits it to those bits."""
    _, lines = H("quest %d dump" % q)
    m = re.search(r"bits0-15 ([01]{16})", " ".join(lines))
    if not m:
        return
    for bit, v in enumerate(m.group(1)):
        if v == "1" and (only is None or bit in only):
            H("quest %d %d clear" % (q, bit))


def check_bonusdrops():
    name = "Summoner / Izual bonus catalysts (Nightmare): dropped once on the ground, flag set"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    fight_ready()
    H("difficulty 1")
    # D2R's quest engine only runs a quest's kill handler while the quest is open, and the first kill completes it (the quest
    # words 13 Summoner / 25 Izual stay set in the saved character); the catalyst flags are bits 1 / 2 of quest 47. Whatever an
    # earlier run or check left there, the quests are reopened before every kill and the flag cleared before the first one:
    # the second kill then reaches the hook with the flag set, which is what must hand out nothing.
    clear_quest_bits(47, {1, 2})
    out = []
    ok = True
    for cls, code, bit, quest in ((250, "0o[", 1, 13), (256, "jcat", 2, 25)):
        clear_quest_bits(quest)
        clear_quest_bits(47, {bit})
        before = ground_count(code)
        H("spawn %d" % cls)
        H("kill nearest %d" % cls)
        time.sleep(1)
        n1 = ground_count(code) - before
        _, q = H("quest 47 %d get" % bit)
        clear_quest_bits(quest)  # the first kill completed the quest: reopen it so that the hook runs again with the flag set
        H("spawn %d" % cls)
        H("kill nearest %d" % cls)
        time.sleep(1)
        n2 = ground_count(code) - before
        out.append("class %d: %s on the ground after kill 1: %d, after kill 2: %d; flag bit %d: %s" % (cls, code, n1, n2, bit, q[0]))
        ok = ok and n1 == 1 and n2 == 1
    H("difficulty 0")
    add(name, "PASS" if ok else "FAIL", "; ".join(out) + " (one per player: the multiplayer count is manual)", [sh("bonusdrops")], out)


def check_summoner():
    n1 = "Summoner AI (first skill branch by the aip3 roll) and MosquitoNest init"
    if not need_game():
        return add(n1, "BLOCKED", "not in a game")
    fight_ready()
    # fight_ready's clean_area removed what an earlier check left in Blood Moor: Malthael's dark nephalems of `medianai` (class 1239)
    # cannot be killed and kept the Summoner from casting ("modes [1]"); a new game clears them.
    god(True)
    notes, ok_all = [], True
    for cls, label in ((250, "Summoner"), (2053, "MosquitoNest")):
        H("spawn %d" % cls)
        per = {}
        t0 = time.time()
        while time.time() - t0 < 14:
            time.sleep(0.5)
            for m in hstate()["mons"]:
                if m.get("npc") or m.get("class") in (2, 271, 150):
                    continue
                d = per.setdefault(m["class"], {"modes": set(), "dists": set()})
                d["modes"].add(m.get("mode"))
                d["dists"].add(m.get("dist"))
        mine = per.get(cls, {"modes": set(), "dists": set()})
        others = sorted(k for k in per if k != cls)
        acted = len(mine["modes"]) > 1 or len(mine["dists"]) > 1
        if cls == 2053:
            acted = acted and bool(others)  # the nest's init sets up the spawn of mosquitoes
        ok_all = ok_all and acted
        notes.append("%s %d: modes %s, distances %s, other monsters that appeared: %s" % (
            label, cls, sorted(x for x in mine["modes"] if x is not None), sorted(x for x in mine["dists"] if x is not None)[:5], others))
        for _ in range(8):
            H("kill nearest")
    god(False)
    add(n1, "PASS" if ok_all else "FAIL", "; ".join(notes), [sh("summoner")], notes)


TIP_PINS = {  # results key (stat; GROUP + stat for a group line) -> the exact text of the line (docs/item-tooltips.md)
    16: "+12% Enhanced Defense", 36: "Physical Resist 12%", 74: "+1 Life Regenerated per Second",
    112: "Hit Causes Monster to Flee 9%", 289: "Orb Effects Applied to this Item are Doubled",
    456: "Activation Frequency +12", 492: "(Paladin Only)", 534: "+1 Life Regenerated per Second (Based on Character Level)",
    10000 + 0: "+12 to all Attributes",
}
# named items: (label, `item` command, regexes that must each match one line)
TIP_ITEMS = [
    ("unique 43 (cooldown, innate damage, all attributes)", "item |wc q=7 uniq=43 ground",
     [r"^\+\d+ to all Attributes$", r"^\d+% Innate Elemental Damage$", r"^.+ Cooldown Reduced by [0-9.]+$"]),
    ("unique 141 (honorific, all skills)", "item amu q=7 uniq=141 ground",
     [r"^Orb Effects Applied to this Item are Doubled$", r"^\+\d+ to All Skills$"]),
    ("unique 128 (reanimate, activation frequency)", "item amu q=7 uniq=128 ground",
     [r"^\d+% Reanimate as: \S", r"^Activation Frequency \+\d+$"]),
    ("unique 72 (life regeneration by level)", "item wd02 q=7 uniq=72 ground",
     [r"^\+\d+ Life Regenerated per Second \(Based on Character Level\)$", r"^Physical Resist \d+%$"]),
    ("unique 1557 (innate damage)", "item 60@ q=7 uniq=1557 ground",
     [r"^Innate \w+ Damage: \d+ \(\d+\.\d% of \w+\)$", r"^\+\d+ to Assassin Skill Levels$"]),
]
# rares / magic items of several bases: no fixed text, only the invariants
TIP_BASES = ["rin", "amu", "jew", "cm1", "cm2", "cm3"]


def _tip_lines(item_id):
    ok, out = H("tip %d" % item_id, 20)
    return ok, [m.group(1) for l in out for m in [re.match(r"tip line \d+: \[(.*)\]$", l)] if m]


def _tip_item(cmd):
    """Creates an item with the `item` verb and reads its tooltip: (item id or None, lines)."""
    ok, out = H(cmd, 20)
    m = re.search(r"item id=(\d+)", " ".join(out)) if ok else None
    if not m:
        return None, [], " ".join(out)[:80]
    ok, lines = _tip_lines(int(m.group(1)))
    return int(m.group(1)), lines, "" if ok else "tip failed"


def _tip_ready():
    """Prime the real item builder through a background inventory hover."""
    ok, lines = H("tip", 20)
    if not ok or not any(l.startswith("tip build") for l in lines):
        ok, out = H("item rin q=4 inv", 20)
        m = re.search(r"item id=\d+ .* x=(\d+) y=(\d+)", " ".join(out)) if ok else None
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            fx, fy = (1055 + (x + 0.5) * 27.6) / 1600.0, (381 + (y + 0.5) * 26.0) / 900.0  # the 15 x 10 backpack grid of the 1600 x 900 client
            g.key("i")
            time.sleep(1.2)
            g.click(fx, fy, move_only=True)
            time.sleep(1.0)
            g.click(fx + 0.002, fy + 0.002, move_only=True)  # the tooltip wants a second mouse move over the item and a dwell
            time.sleep(2.0)
            g.key("esc")
            ok, lines = H("tip", 20)
    return ok and any(l.startswith("tip build") for l in lines)


def check_tooltiptext():
    name = "Item tooltip text: every property line of the stat table and named items, read from the game (docs/item-tooltips.md)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    tools = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, tools)
    import tooltip_audit as ta
    goto(1)
    close_menu()
    bad, notes = [], []

    # 1. the formatter for every stat with a property line, and every group line, at a fixed sample
    answers = []
    for cmd in ta.commands():
        ok, out = H(cmd, 20)
        answers += out
    results = ta.parse_results(answers)
    audit = os.path.join(tools, "..", "work", "tooltip_audit")
    os.makedirs(audit, exist_ok=True)
    with open(os.path.join(audit, "results.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(l for l in answers if l.startswith("tipfmt stat=")) + "\n")
    probs = ta.problems(results)
    if not any(a.startswith("tipfmt stat=") for a in answers):
        return add(name, "BLOCKED", "no tipfmt answer (mxl-core-off.txt word `tooltipprobe` or `itemtext`, or an old plugin)")
    bad += probs[:8]
    for key, want in TIP_PINS.items():
        got = results.get(key)
        text = ta.norm(got[3]) if got else None
        if text != want:
            bad.append("%s: want [%s] got [%s]" % (key, want, text))
    judged = ta.judge(results)
    notes.append("%d lines: %s" % (len(judged), ", ".join("%d %s" % (sum(1 for j in judged if j["verdict"] == v), v)
                                                         for v in sorted({j["verdict"] for j in judged}))))

    # 2. Real items use the game's own builder, primed with a background hover.
    if not _tip_ready():
        return add(name, "FAIL", "real item text builder not reached by background hover", log=bad)
    seen = 0
    for label, cmd, wants in TIP_ITEMS:
        iid, text, err = _tip_item(cmd)
        if iid is None or not text:
            bad.append("%s: no tooltip (%s)" % (label, err))
            continue
        seen += len(text)
        for line in text:
            why = ta.leaks(ta.norm(line))
            if why:
                bad.append("%s: [%s] %s" % (label, ta.norm(line), why))
        for w in wants:
            if not any(re.search(w, ta.norm(l)) for l in text):
                bad.append("%s: no line matches %s in %s" % (label, w, [ta.norm(l) for l in text]))
    for code in TIP_BASES:
        for q in (4, 6):
            iid, text, err = _tip_item("item %s q=%d ground" % (code, q))
            if iid is None:
                continue  # a base that does not exist in this build
            seen += len(text)
            for line in text:
                why = ta.leaks(ta.norm(line))
                if why:
                    bad.append("%s q=%d: [%s] %s" % (code, q, ta.norm(line), why))
    notes.append("%d lines of %d named items and %d bases" % (seen, len(TIP_ITEMS), len(TIP_BASES)))
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad[:6]) if bad else "; ".join(notes), log=bad)


def check_allattrtip():
    """Bug #45: a magic amulet with Median's all-attributes suffix (property `nofreeze`: Strength, Energy, Dexterity and Vitality,
    magicsuffix rows on amul) and the suffix counter must read "+5 to all Attributes" and "Suffixes: 1" (Median's
    ItemSuffixCounter line), with no printf placeholder. Also rolls real magic amulets until one carries the suffix."""
    name = "Magic amulet all-attributes line and suffix counter (bug #45)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    import tooltip_audit as ta
    goto(1)
    close_menu()
    if not _tip_ready():
        return add(name, "FAIL", "real item text builder not reached by background hover")
    bad, notes, shots = [], [], []
    ok, out = H("item amu q=4 0=5 1=5 2=5 3=5 440=1 inv", 20)
    m = re.search(r"item id=(\d+) .* x=(\d+) y=(\d+)", " ".join(out)) if ok else None
    if not m:
        return add(name, "FAIL", "amulet not made: %s" % " ".join(out)[:120])
    iid, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    _, lines = _tip_lines(iid)
    text = [ta.norm(l) for l in lines]
    notes.append("forced amulet: %s" % text)
    for want in ("+5 to all Attributes", "Suffixes: 1"):
        if want not in text:
            bad.append("forced amulet: no line [%s] in %s" % (want, text))
    bad += ["forced amulet: [%s] %s" % (l, ta.leaks(l)) for l in text if ta.leaks(l)]
    fx, fy = inv_cell(x, y)
    g.key("i")
    time.sleep(1.2)
    g.click(fx, fy, move_only=True)
    time.sleep(1.0)
    g.click(fx + 0.002, fy + 0.002, move_only=True)
    time.sleep(2.0)
    shots.append(sh("allattrtip_amulet"))
    g.key("esc")
    H("remove amu 9")
    found = 0
    for _ in range(120):
        ok, out = H("item amu q=4 ilvl=60 ground", 20)
        m = re.search(r"item id=(\d+)", " ".join(out)) if ok else None
        if not m:
            continue
        _, lines = _tip_lines(int(m.group(1)))
        text = [ta.norm(l) for l in lines]
        bad += ["rolled amulet: [%s] %s" % (l, ta.leaks(l)) for l in text if ta.leaks(l)]
        if any(l.endswith("to all Attributes") for l in text):
            found += 1
            notes.append("rolled amulet: %s" % text)
            if not any(re.match(r"^\+\d+ to all Attributes$", l) for l in text):
                bad.append("rolled amulet: %s" % text)
            if found >= 3:
                break
    notes.append("%d rolled amulets with the all-attributes suffix" % found)
    if not found:
        bad.append("no rolled magic amulet carried the all-attributes suffix in 120 tries")
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad[:4]) if bad else "; ".join(notes), shots, notes + bad)


def check_specialtext():
    name = "Layered special item text (Sigma descfunc 31/34), colours and hidden passive names"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    import item_special_data as sd
    import tbl2json
    import tooltip_audit as ta
    control = "itemtext" in CONTROL
    goto(1)
    close_menu()
    original, _ = tbl2json.load_median()
    refs = sd.references()
    ids = sorted({r[3] for r in refs})
    bad, notes = [], []
    answers = []
    # Every layered string referenced by uniques, sets, runewords, affixes and cube recipes goes through the engine.
    # Long paragraphs exceed the native 256-byte property buffer; their complete list is documented separately.
    sweep = [11278] if control else ids
    long_ids = []
    for sid in sweep:
        want = ta.norm(original[sid][1])
        ok, lines = H("tipfmt 404 9 %d 4" % sid, 20)
        answers += lines
        result = ta.parse_results(lines).get(404)
        got = ta.norm(result[3]) if result else ""
        if control:
            if not ok or not result or got == want:
                bad.append("off control did not reproduce the missing Median text: %r" % got)
        elif len(original[sid][1].encode("utf-8")) > 251:
            long_ids.append(sid)
            if not ok or not got or not want.startswith(got):
                bad.append("long string %d: expected a bounded prefix, got %r" % (sid, got))
        elif not ok or got != want:
            bad.append("string %d: want %r got %r" % (sid, want, got))
    # All four stats, colour values 1..13, and Sigma's out-of-range fallback; func34 is always colour 8.
    for stat in (404, 406, 407, 414):
        for value in (-1, 0, *range(1, 15)):
            ok, lines = H("tipfmt %d %d 11278 4" % (stat, value), 20)
            answers += lines
            m = re.search(r"tipcolour .* colour=(-?\d+)", " ".join(lines))
            want = -1 if control else (8 if stat == 414 else value - 1 if 1 <= value <= 13 else 3)
            if not ok or not m or int(m.group(1)) != want:
                bad.append("stat %d colour value %d: expected %d, got %s" % (stat, value, want, lines))
    if not _tip_ready():
        return add(name, "FAIL", "real item builder not reached by background hover", log=bad)
    for label, cmd, string_ids in (
        ("Azure Wrath", "item 14@ uniq=1485 ground", (11278,)),
        ("Staff of Herding", "item wd02 uniq=72 ground", (11646,)),
        ("unique 30 (two special lines)", "item 0u1 uniq=30 ground", (12376, 12377)),
        ("Optical Detector", "item a55 uniq=21 ground", (11861, 12185)),
    ):
        iid, lines, err = _tip_item(cmd)
        got = ta.norm(" ".join(lines))
        notes.append("%s item=%s: %s" % (label, iid, got))
        if iid is None or not lines:
            bad.append("%s: no tooltip (%s)" % (label, err))
            continue
        for sid in string_ids:
            present = ta.norm(original[sid][1]) in got
            if present == control:
                bad.append("%s: string %d %s" % (label, sid, "unexpectedly present in off control" if control else "missing"))
        if label == "Azure Wrath" and (("FLYING POLAR BUFFALO ERROR" in got) != control):
            bad.append("Azure Wrath hidden passive suppression differs from control=%s" % control)
    run = os.path.join(g.current_run(), "special-text-readback.txt")
    with open(run, "w", encoding="utf-8") as f:
        f.write("\n".join(answers + notes + bad) + "\n")
    add(name + (" CONTROL itemtext off" if control else ""), "FAIL" if bad else "PASS",
        "; ".join(bad[:6]) if bad else "%d string IDs (%d property references); four real uniques; all four stats / 16 colour values; %d long paragraphs bounded (docs/unported.md)" % (len(sweep), len(refs), len(long_ids)),
        log=notes + bad)


def check_gameend():
    n1 = "Craft per-game flags reset when the game ends (dungeon key recipe sets game flag 50)"
    if not need_game():
        return add(n1, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    ensure_cube()
    H("cubeclear")
    H("stat player 536 set 1000")
    H("item rx01 cube")
    H("item f700 cube")
    ok0, l0 = H("cubecraft")
    _, g0 = H("flag game 50 get")
    H("cubeclear")
    H("stat player 536 set 0")
    t0 = mxl_text()
    e0 = counter(t0, "game end", r"games ended (\d+)")
    if not leave_and_reenter():
        return add(n1, "BLOCKED", "could not leave and re-enter the game (flag before: %s)" % g0[0])
    time.sleep(3)
    _, g1 = H("flag game 50 get")
    t1 = mxl_text()
    e1 = counter(t1, "game end", r"games ended (\d+)")
    ok = ok0 and g0[0].endswith("= 1") and g1[0].endswith("= 0") and e0 is not None and e1 is not None and e1 > e0
    add(n1, "PASS" if ok else "FAIL",
        "game flag 50 set by the recipe (%s): %s; after Save and Exit and Play again (a new game): %s; `mxl` games ended %s -> %s"
        % (l0[0][:40] if l0 else "-", g0[0], g1[0], e0, e1), [sh("gameend")], [x for x in t1.splitlines() if "game end" in x])


def check_itemstatsave():
    """The harness `item` verb puts its stat=value pairs on the item's magic stat list, the one the save writes: a charm made
    with fireresist= / lightresist= / coldresist= / poisonresist= keeps the stats and gives them to the player after Save and Exit
    and Play again (before 0.65.0 they sat on the base list: the item came back with none)."""
    n1 = "Harness item stats survive Save and Exit (charm with fireresist / lightresist / coldresist / poisonresist set by name)"
    if not need_game():
        return add(n1, "BLOCKED", "not in a game")
    close_menu()
    want = (21, 22, 23, 24)
    names = ("fireresist", "lightresist", "coldresist", "poisonresist")

    def num(lines):
        return int(lines[0].rsplit("=", 1)[1]) if lines and "=" in lines[0] else None

    def player():
        return [num(H("stat player %d" % s)[1]) for s in (39, 41, 43, 45)]

    def charms():
        out = []
        for it in hstate()["items"]:
            if it.get("code") == "cm2" and it.get("page") == 0:
                out.append((it["id"], tuple(num(H("stat %d %d" % (it["id"], s))[1]) for s in (39, 41, 43, 45))))
        return out

    if charms():
        return add(n1, "BLOCKED", "the character already carries a medium charm (cm2): the check would leave it or remove it")
    p0 = player()
    ok, lines = H("item cm2 " + " ".join("%s=%d" % (nm, v) for nm, v in zip(names, want)) + " inv")
    live = charms()
    p1 = player()
    gain = [b - a for a, b in zip(p0, p1)]
    if not leave_and_reenter():
        H("remove cm2 1")
        return add(n1, "BLOCKED", "could not leave and re-enter the game (made: %s, item stats live %s)" % (ok, live))
    time.sleep(2)
    after = charms()
    p2 = player()
    kept = [x for x in after if x[1] == want]
    shot = sh("itemstatsave")
    H("remove cm2 1")
    good = ok and len(live) == 1 and live[0][1] == want and gain == list(want) and len(kept) == 1 and p2 == p1
    add(n1, "PASS" if good else "FAIL",
        "made %s; item stats live %s, player gained %s; after Save and Exit and Play again: charms %s, player %s (before %s)"
        % (ok, live, gain, after, p2, p0), [shot])


def _weapon_bonus(code):
    """(StrBonus, DexBonus) of a weapons.txt row of the built mod (blank = 0): the independent source for the formula."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data", "global", "excel", "base", "weapons.txt")
    with open(path, encoding="utf-8-sig") as f:
        rows = [l.rstrip("\n").split("\t") for l in f]
    h = rows[0]
    for r in rows[1:]:
        if r[h.index("code")] == code:
            return int(r[h.index("StrBonus")] or 0), int(r[h.index("DexBonus")] or 0)
    return None


def _panelrow(stat):
    """`panelrow <stat>` -> (displayed value, text, weapon (str bonus, dex bonus) or None)."""
    ok, lines = H("panelrow %d" % stat)
    row = next((l for l in lines if l.startswith("panelrow %d " % stat)), "")
    m = re.search(r"value=(-?\d+) text=\[(.*)\]", row)
    w = next((l for l in lines if l.startswith("panelrow weapon")), "")
    mw = re.search(r"strbonus=(-?\d+) dexbonus=(-?\d+)", w)
    return (int(m.group(1)), m.group(2), (int(mw.group(1)), int(mw.group(2))) if mw else None) if ok and m else None


def check_statcols():
    name = "Stat pages: Str / Dex damage bonus rows and the total / % bonus / base columns of the Advanced Stats panel"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    rows, bad = [], []
    base = {s: rd("player", s) for s in (0, 2)}
    # hst (weapons.txt quest=10, the Horadric Staff) and hfh (quest=25, the Hell Forge Hammer) are quest items: D2R's place
    # function refuses them (`equip`: "does not fit body location 4") once the character's quest state says the quest is
    # done: quest 10 bit 0 for hst, quest 27 bits 0 / 1 for hfh (measured on a character whose quests the earlier checks had
    # completed; not a data or namespace matter: the same build equips both on a fresh character). Clear the bits for the
    # check, put them back afterwards.
    qsaved = {q: _qbits(q) for q in (10, 27)}
    for q in qsaved:
        for i in range(16):
            H("quest %d %d clear" % (q, i))
    try:
        # no weapon: both damage bonus rows are 0 (Median's handler returns 0 without a weapon)
        H("packclear")  # room in the backpack: an unequip into a full backpack fails and the hand stays occupied
        for slot in ("rhand", "lhand"):
            H("unequip " + slot)
        time.sleep(1)
        for stat in (299, 300):
            r = _panelrow(stat)
            rows.append("no weapon, stat %d: %s" % (stat, r))
            if r is None or r[0] != 0 or r[2] is not None:
                bad.append("no weapon: stat %d row %s (want value 0, no weapon)" % (stat, r))
        for code in ("hfh", "hst"):  # strength-only (16 / 0) and dexterity-only (0 / 6) in weapons.txt
            want_b = _weapon_bonus(code)
            if want_b is None:
                bad.append("%s is not in weapons.txt" % code)
                continue
            for sv, dv in ((50, 30), (123, 77), (300, 9)):
                setstat("player", 0, sv)
                setstat("player", 2, dv)
                ok, _l = H("equip %s rhand" % code)
                if not ok:
                    bad.append("equip %s failed: %s" % (code, _l[:1]))
                    continue
                time.sleep(1.2)
                # the totals the panel reads include the weapon's own bonus (the quest uniques carry properties that scale
                # with the character level: stat 2 reads 40 after `set 30` with hst on a level 20 character, `cstat` 30)
                tot_s, tot_d = rd("player", 0), rd("player", 2)
                r299, r300 = _panelrow(299), _panelrow(300)
                if r299 is None or r300 is None:
                    bad.append("%s str %d dex %d: panelrow failed" % (code, sv, dv))
                    H("unequip rhand")
                    continue
                want_s = tot_s * want_b[0] // 100
                want_d = tot_d * want_b[1] // 100
                rows.append("%s (bonus %d/%d), Str %s Dex %s: str row %d [%s], dex row %d [%s], weapon %s"
                            % (code, want_b[0], want_b[1], tot_s, tot_d, r299[0], r299[1], r300[0], r300[1], r299[2]))
                if r299[0] != want_s or r300[0] != want_d:
                    bad.append("%s Str %s Dex %s: rows %d / %d, want %d / %d" % (code, tot_s, tot_d, r299[0], r300[0], want_s, want_d))
                if r299[2] != want_b:
                    bad.append("%s: weapon bonuses read %s, weapons.txt %s" % (code, r299[2], want_b))
                for v, t, lbl in ((want_s, r299[1], "str"), (want_d, r300[1], "dex")):
                    if v != 0 and str(v) not in t:
                        bad.append("%s %s row text [%s] lacks %d" % (code, lbl, t, v))
                H("unequip rhand")
        # the columns: attribute rows carry the % stat and the base after the total
        setstat("player", 0, 100)
        setstat("player", 2, 60)
        time.sleep(1.2)
        for stat in (0, 2):
            r = _panelrow(stat)
            tot = stat_of(H("cstat %d" % stat)[1])
            rows.append("stat %d: total %s -> %s" % (stat, tot, r))
            if r is None:
                bad.append("stat %d: panelrow failed" % stat)
                continue
            if r[0] != tot:
                bad.append("stat %d: displayed value %d, total %s" % (stat, r[0], tot))
            if "%d base" % (rd("player", stat) or 0) not in r[1]:
                bad.append("stat %d: text [%s] lacks base %s" % (stat, r[1], rd("player", stat)))
        # a % stat on gear shows as the column (the stat has no row of its own)
        ok, _l = H("equip rin 388=25 389=-10 rring")
        time.sleep(1.2)
        rs, rdx = _panelrow(0), _panelrow(2)
        rows.append("ring with +25%% str / -10%% dex: %s / %s" % (rs, rdx))
        if not ok or rs is None or rdx is None or "+25%" not in rs[1] or "-10%" not in rdx[1]:
            bad.append("ring %% columns: %s / %s (equip ok %s)" % (rs, rdx, ok))
    finally:
        for s, v in base.items():
            if v is not None:
                setstat("player", s, v)
        for slot in ("rhand", "rring"):
            H("unequip " + slot)
        for q, bits in qsaved.items():
            _qrestore(q, bits)
    add(name, "PASS" if not bad else "FAIL",
        "panel row functions on the client's player copy (harness `panelrow`), formula Str * StrBonus / 100 and Dex * DexBonus / 100 of the "
        "wielded weapon vs weapons.txt: %s" % ("; ".join(rows[:6]) if not bad else "; ".join(bad)), [], rows)

# ------------------------------------------------------------------ lane bug-backlog-b: the old "fix to test" rows of docs/bugs.md
# Each check drives the game the way a player does (bg mouse / keys, panels) and reads the answer from the harness or the
# files the game writes. Harness verbs added for them: skilltab, str, hover, automap, shop, levelact (docs/testing.md).

MOD_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data")
ACT_TOWNS = {0: 1, 1: 40, 2: 75, 3: 103, 4: 109}  # act index (levels.txt Act column) -> town level


def log_mark():
    return g._size(g.LOADER_LOG)


def log_since(off):
    return g._read_from(g.LOADER_LOG, off)


def assertions_since(off):
    """The messages of the assertion boxes d2rloader.log wrote since `off` (D2R's own asserts continue after logging)."""
    return re.findall(r"Message : (.*?)\s*\|", log_since(off))


def _crop_hash(path, box):
    from PIL import Image
    im = Image.open(path).convert("RGB").crop(box)
    return hashlib.md5(im.tobytes()).hexdigest()[:10]


def _shot_path(name):
    return os.path.join(g.current_run(), name + ".png")


def _red_pixels(path, box):
    """Pixels of the red "None" text of an unbound key in the Options controls list."""
    from PIL import Image
    im = Image.open(path).convert("RGB").crop(box)
    return sum(1 for r, gr, b in im.getdata() if r > 150 and gr < 90 and b < 90)


# --- #3 skill tree tabs, #9 skill tooltips -----------------------------------------------------------------------------

TREE_X = (1148, 1258, 1368)  # skill icon columns of the HD tree panel (1600 x 900 client)
TREE_Y0, TREE_DY, TREE_ROWS = 232, 75, 6
TREE_CLOSE = (1485 / 1600.0, 103 / 900.0)


def open_skill_tree():
    """T toggles the panel; the tab setter hook (`h skilltab`) counts the clicks the panel takes, so a click on tab 2 tells if the
    panel is open."""
    x0, y0 = g.UI["skill_tab0"]
    for _ in range(2):
        g.key("t")
        time.sleep(1.5)
        ok, lines = g.hcmd("skilltab", 5)
        calls0 = int(re.search(r"setter_calls=(\d+)", " ".join(lines)).group(1)) if ok else -1
        g.click(x0 + g.UI["skill_tab_dx"] * 2, y0)
        time.sleep(1.0)
        ok, lines = g.hcmd("skilltab", 5)
        m = re.search(r"current=(\d+) setter_calls=(\d+)", " ".join(lines))
        if ok and m and int(m.group(2)) > calls0 and int(m.group(1)) == 2:
            return True
    return False


def check_skilltree():
    name = "Skill tree: 8 tabs open and show their own pages (#3); hovering every icon raises no skill tooltip assert (#9)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    off = log_mark()
    if not open_skill_tree():
        return add(name, "BLOCKED", "the skill tree did not open / take a tab click")
    x0, y0 = g.UI["skill_tab0"]
    dx = g.UI["skill_tab_dx"]
    tabs, hashes, shots, bad = [], [], [], []
    for i in range(8):
        g.click(x0 + dx * i, y0)
        time.sleep(1.2)
        ok, lines = g.hcmd("skilltab", 5)
        cur = int(re.search(r"current=(\d+)", " ".join(lines)).group(1)) if ok else -1
        tabs.append(cur)
        if cur != i:
            bad.append("tab %d selected page %d" % (i, cur))
        shots.append(sh("skilltab%d" % (i + 1)))
        hashes.append(_crop_hash(_shot_path("skilltab%d" % (i + 1)), (1075, 195, 1445, 650)))  # the icon area of the panel
    distinct = len(set(hashes))
    if distinct < 7:
        bad.append("only %d of 8 tabs look different (%s)" % (distinct, hashes))
    # #9: the mouse over every icon cell of every tab; D2R builds the tooltip lines (the assert sits in that renderer)
    hovers = 0
    for i in range(8):
        g.click(x0 + dx * i, y0)
        time.sleep(0.8)
        for row in range(TREE_ROWS):
            for fx in TREE_X:
                fy = TREE_Y0 + TREE_DY * row
                g.click(fx / 1600.0, fy / 900.0, move_only=True)
                time.sleep(0.3)
                g.click((fx + 3) / 1600.0, (fy + 3) / 900.0, move_only=True)  # the tooltip wants a second move over the icon
                time.sleep(0.4)
                hovers += 1
        if i == 0:
            shots.append(sh("skilltip"))
    g.click(*TREE_CLOSE)
    time.sleep(0.8)
    asserts = assertions_since(off)
    dummy = [a for a in asserts if "strdummy" in a or "stringIndex1" in a]
    new_asserts = sorted(set(asserts))
    if dummy:
        bad.append("%d skill tooltip assert(s) `stringIndex1 != strdummy`" % len(dummy))
    status = "PASS" if not bad else "FAIL"
    add(name, status, "page of each tab click (harness `skilltab`): %s; distinct panel pictures %d / 8; %d icon cells hovered, assert boxes in "
        "d2rloader.log: %s%s" % (tabs, distinct, hovers, new_asserts or "none", ("; " + "; ".join(bad)) if bad else ""), shots)


# --- #5 keybinds survive Save and Exit ---------------------------------------------------------------------------------

OPT_OPTIONS = (0.5, 0.375)
OPT_CONTROLS = (967 / 1600.0, 141 / 900.0)
OPT_SKILL9_KEY1 = (705 / 1600.0, 607 / 900.0)
OPT_APPLY = (591 / 1600.0, 775 / 900.0)
OPT_DEFAULT = (800 / 1600.0, 775 / 900.0)
OPT_LEGACY = (800 / 1600.0, 380 / 900.0)
OPT_CLOSE = (1189 / 1600.0, 69 / 900.0)
POPUP_SKILL = (910 / 1600.0, 740 / 900.0)  # the second icon of the lower row of the skill speed bar (S)


def _key_file():
    d2s = max((f for f in os.listdir(SAVES) if f.endswith(".d2s")), key=lambda f: os.path.getmtime(os.path.join(SAVES, f)))
    return os.path.join(SAVES, d2s[:-4] + ".key")


def _md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()[:8] if os.path.exists(p) else "(none)"


def open_controls():
    g.key("esc")
    time.sleep(1.5)
    g.click(*OPT_OPTIONS)
    time.sleep(1.5)
    g.click(*OPT_CONTROLS)
    time.sleep(1.5)


def close_options():
    g.click(*OPT_CLOSE)  # Options -> pause menu
    time.sleep(1.2)
    g.click(0.5, 0.505)  # Return to Game
    time.sleep(1.2)


def restore_legacy_keys():
    open_controls()
    g.click(*OPT_DEFAULT)
    time.sleep(1.5)
    g.click(*OPT_LEGACY)
    time.sleep(1.5)
    g.click(*OPT_APPLY)
    time.sleep(2.0)
    close_options()


def bind_skill_hotkey():
    """S opens the skill speed bar; with the mouse over an icon an F key binds that skill. Returns the (left, right) ids the key
    selects afterwards, or None."""
    g.key("s")
    time.sleep(1.5)
    g.click(*POPUP_SKILL, move_only=True)
    time.sleep(0.8)
    g.click(POPUP_SKILL[0] + 0.002, POPUP_SKILL[1] + 0.002, move_only=True)
    time.sleep(1.2)
    g.key("f6")
    time.sleep(1.0)
    g.key("s")
    time.sleep(1.0)
    return hotkey_skill()


def hotkey_skill(tries=3):
    """The (left, right) skill ids after F6 (retried: right after entering the game a key can arrive before the skill bar is ready)."""
    ids = None
    for _ in range(tries):
        H("skill left 0")
        H("skill right 0")
        g.key("f6")
        time.sleep(1.5)
        ok, lines = H("skill")
        m = re.search(r"left=(\d+) right=(\d+)", " ".join(lines))
        ids = (int(m.group(1)), int(m.group(2))) if ok and m else None
        if ids and ids != (0, 0):
            break
        time.sleep(2)
    return ids


def check_keybinds():
    name = "Keybinds survive Save and Exit and a restart (#5): a rebound key in Options > Controls and an F6 skill hotkey"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    keyfile = _key_file()
    shots, bad = [], []
    restore_legacy_keys()  # a failed earlier run may have left Skill 9 bound: start from the Legacy layout
    h0 = _md5(keyfile)
    # 1. Options > Controls: Skill 9 -> F9, Apply (D2R writes the character's .key file)
    open_controls()
    g.click(*OPT_SKILL9_KEY1)
    time.sleep(1.0)
    g.key("f9")
    time.sleep(1.0)
    shots.append(sh("keys_bound"))
    g.click(*OPT_APPLY)
    time.sleep(2.0)
    h1 = _md5(keyfile)
    if h1 == h0:
        bad.append("Apply did not change %s (%s)" % (os.path.basename(keyfile), h0))
    close_options()
    # 2. skill hotkey F6 through the speed bar
    ids0 = bind_skill_hotkey()
    if not ids0 or ids0 == (0, 0):
        bad.append("F6 bound no skill (the speed bar icon %s)" % (POPUP_SKILL,))
    # 3. Save and Exit, play again
    if not leave_and_reenter():
        return add(name, "BLOCKED", "could not leave and re-enter the game: %s" % "; ".join(bad))
    time.sleep(6)  # the town is still loading when the harness first answers
    for _ in range(10):
        if hstate()["ok"] and hstate()["player"].get("area") == 1:
            break
        time.sleep(2)
    h2 = _md5(keyfile)
    if h2 != h1:
        bad.append("the .key file changed on exit / restart (%s -> %s)" % (h1, h2))
    ids1 = hotkey_skill()
    if ids0 and ids1 != ids0:
        bad.append("F6 selected %s after the restart, %s before" % (ids1, ids0))
    open_controls()
    shots.append(sh("keys_after_restart"))
    red = _red_pixels(_shot_path("keys_after_restart"), (680, 598, 730, 616))
    if red > 5:
        bad.append("Skill 9 shows None after the restart (%d red pixels)" % red)
    # 4. put the bindings back: Default > Legacy is the layout the file started with
    g.click(*OPT_DEFAULT)
    time.sleep(1.5)
    g.click(*OPT_LEGACY)
    time.sleep(1.5)
    g.click(*OPT_APPLY)
    time.sleep(2.0)
    h3 = _md5(keyfile)
    close_options()
    if h3 != h0:
        bad.append("Default > Legacy > Apply did not restore the key file (%s, was %s)" % (h3, h0))
    add(name, "PASS" if not bad else "FAIL",
        ".key file md5 %s (before) -> %s (Skill 9 = F9 applied) -> %s (after Save and Exit + restart, Skill 9 still F9 in the list); "
        "F6 skill hotkey selects (left, right) %s before and %s after the restart; layout restored (%s, was %s)%s" % (
            h0, h1, h2, ids0, ids1, h3, h0, ("; " + "; ".join(bad)) if bad else ""), shots)


# --- #7 NPC / string texts ---------------------------------------------------------------------------------------------


def _strings_entries():
    import glob
    import json
    ents = []
    for f in sorted(glob.glob(os.path.join(MOD_DATA, "local", "lng", "strings", "*.json"))):
        for e in json.load(open(f, encoding="utf-8-sig")):
            ents.append((os.path.basename(f), e["id"], e["Key"], e["enUS"]))
    return ents


def _norm(text):
    """Letters only, lower case, without D2R's colour codes (the verb leaves the code's own character in the text)."""
    return re.sub(r"[^a-z]", "", re.sub("ÿc.", "", text).lower())[:200]


def check_npcstrings():
    name = "String ids by low 16 bits: no Median key shares a D2R string's id, so NPCs speak their own text (#7)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ents = _strings_entries()
    by_low = {}
    for f, i, k, t in ents:
        by_low.setdefault(i & 0xFFFF, {}).setdefault((i, k), t)
    clashes = {low: sorted(v) for low, v in by_low.items() if len({k for _i, k in v}) > 1}  # different keys on one 16-bit value
    # texts to read back from the running game: every NPC intro / gossip line and a seeded sample of Median's own strings
    import difflib
    import random
    rnd = random.Random(7)
    npc = [e for e in ents if re.search(r"Intro|Gossip|Greet", e[2]) and e[1] < 0x10000]
    new = [e for e in ents if 28106 <= e[1] < 0x10000]
    pick = {}
    for f, i, k, t in npc + rnd.sample(new, min(250, len(new))):
        if len(by_low[i & 0xFFFF]) == 1 and not (i & 0xFFFF) in clashes:
            pick[i & 0xFFFF] = (k, t)
    ids = sorted(pick)
    wrong, checked = [], 0
    for n in range(0, len(ids), 10):
        batch = ids[n:n + 10]
        ok, lines = H("strids " + " ".join(str(i) for i in batch))
        got = {}
        for ln in lines:
            m = re.match(r"\s*str (\d+) = \[(.*)\]\s*$", ln)
            if m:
                got[int(m.group(1))] = m.group(2)
        for i in batch:
            checked += 1
            want = _norm(pick[i][1])
            have = _norm(got.get(i, "(no answer)"))
            if (have or want) and difflib.SequenceMatcher(None, have, want).ratio() < 0.9:
                wrong.append("%d %s: game '%s' data '%s'" % (i, pick[i][0], have[:40], want[:40]))
    shots = []
    d2r_own = {27956, 28082}
    unexpected = {low: v for low, v in clashes.items() if low not in d2r_own}
    bad = []
    if unexpected:
        bad.append("%d 16-bit ids shared by different keys, e.g. %s" % (len(unexpected), list(unexpected.items())[:2]))
    if wrong:
        bad.append("%d of %d strings differ from the data: %s" % (len(wrong), checked, wrong[:3]))
    add(name, "PASS" if not bad else "FAIL",
        "%d keys in the string tables, %d 16-bit values hold two different keys (D2R ships %s itself: %s); the game's own string lookup (harness `str`) "
        "answered %d NPC intro / Median strings, %d wrong%s. What an NPC's subtitle looks like on screen stays a manual look" % (
            len(ents), len(clashes), sorted(d2r_own), sorted(set(clashes) & d2r_own), checked, len(wrong), ("; " + "; ".join(bad)) if bad else ""),
        shots, wrong[:20])


# --- #15 automap in Median-only level types ----------------------------------------------------------------------------

AUTOMAP_AREAS = {36: (138,), 37: (174, 175), 38: (191,), 39: (144,), 40: (247,), 41: (142,), 42: (152,), 43: (250,), 44: (243,),
                 51: (220,)}  # level type -> areas of it, tried in turn until the game's lookups hit a Median row (type 37 has wall rows only)


def check_automap():
    name = "Automap in Median-only areas: level types 36-51 resolve their Median automap rows (#15)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    ok, lines = H("automap")
    table = {}
    for ln in lines:
        m = re.search(r"automap type=(\d+) rows=(\d+)(?: resolved=(\d+) bad=(\d+))?", ln)
        if m:
            table[int(m.group(1))] = (int(m.group(2)), int(m.group(3) or 0), int(m.group(4) or 0))
    rows, bad, shots = [], [], []
    god(True)
    try:
        for typ, areas in AUTOMAP_AREAS.items():
            for area in areas:
                st = goto(area, timeout=50)
                ok2 = st["player"].get("area") == area
                _ok, lines = H("automap %d" % typ)
                m = re.search(r"game_lookups=(\d+) hits=(\d+)", " ".join(lines))
                lookups, hits = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
                if ok2 and hits > 0:
                    break
            n, resolved, badrows = table.get(typ, (0, 0, 0))
            g.key("tab")
            time.sleep(1.2)
            shots.append(sh("automap%d" % typ))
            g.key("tab")
            time.sleep(0.4)
            miss = ""
            if hits == 0:  # which (tile type, style) pairs the area asked for and the type's rows do not list
                txt = " ".join(lines)
                asked = ["%s/%s" % t for t in re.findall(r"miss tile=(\d+) style=(\d+)", txt)][:6]
                listed = ["%s/%s" % t for t in re.findall(r"row \d+ tile=(\d+) style=(\d+)", txt)]
                miss = " (it asked for tile/style %s, the rows list %s)" % (", ".join(asked), ", ".join(listed))
            rows.append("type %d (area %d%s): %d rows, %d resolved to a cel, game made %d lookups, %d found a Median row%s" % (
                typ, area, "" if ok2 else " NOT REACHED", n, resolved, lookups, hits, miss))
            if not ok2:
                bad.append("type %d: area %d not reached" % (typ, area))
            elif n >= 30 and (hits == 0 or lookups == 0):
                bad.append("type %d: the game's lookups found no Median row (%d lookups)" % (typ, lookups))
            if n and resolved < n * 0.99 - 1:
                bad.append("type %d: only %d of %d rows resolve to a cel the atlas has" % (typ, resolved, n))
    finally:
        god(False)
        goto(1)
    add(name, "PASS" if not bad else "FAIL",
        "%s. Types 45-50 (e.g. Heart of Darkness) have no Median rows, so they keep D2R's lookup (docs/plugin-spec.md)%s" % (
            "; ".join(rows), ("; " + "; ".join(bad)) if bad else ""), shots, rows)


# --- #17 levels above 255 through the summoning scrolls ------------------------------------------------------------------

SCROLLS = ["b60X", "b61X", "b62X", "b63X", "b64X", "b65X", "b66X", "b67X", "b68X", "b70X", "b71X", "b72X", "b73X"]


def _scroll_targets():
    """code -> Median level of the scroll's calc1 (misc.txt: `(stat(...)>0)?0:N`) -> D2R level id (mxl_items.h LevelIds: Median level
    n >= 137 is D2R's n + 1) and the act town the portal can be opened from (the portal links levels of one act)."""
    import csv
    rows = list(csv.reader(open(os.path.join(MOD_DATA, "global", "excel", "misc.txt"), encoding="latin-1"), delimiter="\t"))
    h = rows[0]
    ci = {n: i for i, n in enumerate(h)}
    lv = list(csv.reader(open(os.path.join(MOD_DATA, "global", "excel", "levels.txt"), encoding="latin-1"), delimiter="\t"))
    lci = {n: i for i, n in enumerate(lv[0])}
    act = {int(r[lci["Id"]]): int(r[lci["Act"]] or 0) for r in lv[1:] if len(r) > lci["Act"] and r[lci["Id"]].isdigit()}
    out = {}
    for r in rows[1:]:
        code = r[ci["code"]] if len(r) > ci["code"] else ""
        if code in SCROLLS:
            nums = re.findall(r"\?0:(\d+)$", r[ci["calc1"]].strip())
            median = int(nums[0]) if nums else 0
            did = median + 1 if median >= 137 else median
            out[code] = (median, did, ACT_TOWNS.get(act.get(did, 0), 1) if did else None)
    return out


def check_scrollportals():
    name = "Summoning scrolls open portals that lead into the levels above 255 (#17)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    targets = _scroll_targets()
    rows, bad, shots = [], [], []
    god(True)
    base = {}
    try:
        # the check's first screenshot is taken from a minimized window: game_ctl restores it without activating it (restore_noactivate)
        h_win = g.find_window()
        if h_win:
            g.user32.ShowWindow(h_win, 7)  # SW_SHOWMINNOACTIVE: minimized, the foreground window stays
            time.sleep(1.0)
        goto(1)
        base = {n: stat_of(H("stat player %d" % n)[1]) for n in (12, 6, 7)}  # level, life, max life: the character is saved on exit
        H("difficulty 2")  # Hell rules and a high level: the dungeon lockout refuses a low character (docs/plugin-spec.md)
        H("stat player 12 set 150")  # the highest entry requirement is 147 (mxl_dungeons.h)
        H("stat player 7 set 20000000")
        H("stat player 6 set 20000000")
        for code in SCROLLS:
            median, want, town = targets.get(code, (0, 0, None))
            if not want:
                # b73X: calc1 is 0 by Median's formula (no destination yet): the scroll must refuse
                goto(1)
                H("packclear")
                H("item %s inv" % code)
                ok, _l = H("use " + code)
                rows.append("%s: no destination in the data, %s" % (code, "refused" if not ok else "OPENED A PORTAL"))
                if ok:
                    bad.append("%s opened a portal without a destination" % code)
                continue
            st = goto(town, timeout=50)
            H("packclear")
            H("item %s inv" % code)
            before = {o["id"] for o in hstate()["objs"]}
            ok, lines = H("use " + code)
            time.sleep(1.5)
            new = [o for o in hstate()["objs"] if o["id"] not in before and o.get("class") in (59, 60, 600)]
            if not ok or not new:
                rows.append("%s -> level %d: the use was refused / no portal (%s)" % (code, want, lines[-1][:60] if lines else ""))
                bad.append("%s: no portal to level %d from town %d" % (code, want, town))
                continue
            moved = False
            for _ in range(3):  # the portal object needs a frame or two before it works
                time.sleep(2)
                ok, ll = H("enter %d" % new[0]["id"])
                if ll and "moved" in ll[0]:
                    moved = True
                    break
            area = None
            for _ in range(8):
                time.sleep(2)
                area = hstate()["player"].get("area")
                if area == want:
                    break
            if want > 255:
                shots.append(sh("portal%d" % want))
            rows.append("%s -> level %d%s: portal class %d, %s, entered area %s" % (code, want, " (>255)" if want > 255 else "", new[0]["class"], "moved" if moved else "REFUSED", area))
            if area != want:
                bad.append("%s: entered area %s, wanted %d" % (code, area, want))
    finally:
        god(False)
        H("difficulty 0")
        goto(1)
        for n, v in base.items():
            if v is not None:
                H("stat player %d set %d" % (n, v))
    # a minimized game window is restored by game_ctl without activation (restore_noactivate): the foreground window must not change
    for win, before, after, handed in g.RESTORES:
        rows.append("game window %s was minimized and restored; foreground window %s -> %s%s" % (
            win, before, after, " (D2R activated itself on the restore, the focus went back at once)" if handed else ""))
        if before != after:
            bad.append("restoring the minimized window left a different foreground window (%s -> %s)" % (before, after))
    add(name, "PASS" if not bad else "FAIL",
        "use the scroll in its act's town (Hell rules, level 150), `enter <portal id>`, read the area: %s%s" % ("; ".join(rows), ("; " + "; ".join(bad)) if bad else ""), shots, rows)


# --- #18 vendors ---------------------------------------------------------------------------------------------------------

SHOP_TABS = [(185 / 1600.0, 222 / 900.0), (289 / 1600.0, 222 / 900.0), (497 / 1600.0, 222 / 900.0)]  # Armor / Weapons / Misc
SHOP_GRID = (135, 248, 27.6)  # x0, y0, cell of the vendor panel's item grid (1600 x 900 client)
TRADE_CLOSE = (564 / 1600.0, 103 / 900.0)
# Legacy graphics (MXL_GRAPHICS=legacy, G): the 4:3 picture, pillarboxed in the 1600 x 900 client, puts the grids elsewhere
SHOP_TABS_LEGACY = [(412 / 1600.0, 232 / 900.0), (522 / 1600.0, 232 / 900.0), (724 / 1600.0, 232 / 900.0)]
SHOP_GRID_LEGACY = (365, 258, 27.3)


def legacy_gfx():
    return os.environ.get("MXL_GRAPHICS") == "legacy"


def inv_cell(x, y):
    """Client fractions of the centre of backpack cell (x, y) (the 15 x 10 grid of the 1600 x 900 client), HD or legacy graphics."""
    if legacy_gfx():
        return (835 + (x + 0.5) * 27.3) / 1600.0, (393 + (y + 0.5) * 27.3) / 900.0
    return (1055 + (x + 0.5) * 27.6) / 1600.0, (381 + (y + 0.5) * 26.0) / 900.0


def shop_cell(x, y):
    x0, y0, c = SHOP_GRID_LEGACY if legacy_gfx() else SHOP_GRID
    return (x0 + (x + 0.5) * c) / 1600.0, (y0 + (y + 0.5) * c) / 900.0


def shop_tab(i):
    return (SHOP_TABS_LEGACY if legacy_gfx() else SHOP_TABS)[i]


def trade_panel_open():
    """The vendor panel's red close button (X) is on screen."""
    im = g.grab_client(g.need_window()).convert("RGB").crop((552, 92, 576, 114))
    return sum(1 for r, gr, b in im.getdata() if r > 140 and gr < 80 and b < 80) > 8


def check_vendors():
    name = "Vendors Charsi, Gheed, Akara: open the trade panel, browse the tabs, buy by right click; no crash, no [default_unit] flood (#18)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    off = log_mark()
    rows, bad, shots = [], [], []
    for cls, nm in ((148, "Akara"), (154, "Charsi"), (147, "Gheed")):
        H("packclear")  # a bought item needs room in the backpack
        menu = npc_menu_near(cls)  # walks next to the NPC (a copy when out of reach), talks again when the first click was lost
        if menu is None:
            bad.append("%s: no menu" % nm)
            continue
        ok, _l = H("menu 1")  # Trade
        for _ in range(6):
            time.sleep(2)
            if trade_panel_open():
                break
        else:
            bad.append("%s: the trade panel did not open" % nm)
        g.log("trade panel open before `shop`: %s" % trade_panel_open())
        ok, lines = H("shop %d" % cls)
        g.log("trade panel open after `shop`: %s" % trade_panel_open())
        stock = [kv(l) for l in lines if l.startswith("item ")]
        n = len(stock)
        for i, (fx, fy) in enumerate(SHOP_TABS):
            if cls == 148 and i == 0:
                continue  # Akara has no Armor tab: a click on its empty place closes the panel
            g.click(fx, fy)
            time.sleep(1.0)
            g.log("trade panel open after tab %d click: %s" % (i + 1, trade_panel_open()))
            shots.append(sh("shop_%s_tab%d" % (nm.lower(), i + 1)))
        # buy: an ammo-like stack on the Misc tab (page 3) when the vendor has one, else any Misc item
        g.click(*SHOP_TABS[2])
        time.sleep(0.8)
        misc = [s for s in stock if s.get("page") == "3" and s.get("code") not in ("key",)]
        misc.sort(key=lambda s: -int(s.get("qty", 0)))
        bought = "nothing on the Misc tab"
        tried = []
        H("gold set 40000 8888")  # inside the level cap on carried gold
        for s in misc[:3]:  # the first stack that the right click buys (a throwing weapon bought replaces the weapon in hand)
            st0 = hstate()
            x, y = int(s["x"]), int(s["y"])
            fx = (SHOP_GRID[0] + (x + 0.5) * SHOP_GRID[2]) / 1600.0
            fy = (SHOP_GRID[1] + (y + 0.5) * SHOP_GRID[2]) / 900.0
            g.click(fx, fy, button="right")
            time.sleep(2.0)
            st1 = hstate()
            gained = len(st1["items"]) - len(st0["items"])
            gold0, gold1 = st0["player"].get("gold", 0), st1["player"].get("gold", 0)
            tried.append("%s qty %s: items %+d, gold %d -> %d" % (s["code"], s.get("qty", "0"), gained, gold0, gold1))
            if gold1 < gold0:
                break
        bought = "right click buys: " + "; ".join(tried) if misc else bought
        if not misc:
            bad.append("%s: no stock on the Misc tab to buy" % nm)
        elif hstate()["player"].get("gold", 0) >= 40000:
            bad.append("%s: the right click bought nothing (%s)" % (nm, "; ".join(tried)))
        g.click(*TRADE_CLOSE)
        time.sleep(1.0)
        close_menu()
        alive = hstate()["ok"]
        rows.append("%s: %d stock items, %s, game %s" % (nm, n, bought, "alive" if alive else "GONE"))
        if not alive:
            bad.append("%s: the game stopped answering" % nm)
            break
    new_log = log_since(off)
    flood = new_log.count("[default_unit]")
    notfound = new_log.count("File not found")
    asserts = sorted(set(assertions_since(off)))
    if flood or notfound:
        bad.append("%d `[default_unit]` / %d `File not found` lines in d2rloader.log" % (flood, notfound))
    H("packclear")
    add(name, "PASS" if not bad else "FAIL",
        "%s; log since the first vendor: %d `[default_unit]`, %d `File not found`, assert boxes: %s%s. Whether every vendor picture looks right "
        "stays a manual look (the screenshots show each tab)" % ("; ".join(rows), flood, notfound, asserts or "none", ("; " + "; ".join(bad)) if bad else ""),
        shots, rows)


# --- #22 monsters can be hovered and attacked --------------------------------------------------------------------------


def _mon_screen(player, mon, k=1.3):
    """The isometric projection of a world offset onto the 1600 x 900 client (the player stands at the centre)."""
    dx, dy = mon["mx"] - player["x"], mon["my"] - player["y"]
    return 800 + (dx - dy) * 16 * k, 450 + (dx + dy) * 8 * k - 20


def check_monster_hover():
    name = "Monsters can be hovered and attacked through the player's own click path (#22)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    god(False)
    goto(2)
    close_menu()
    kill_all_near()
    H("skill left 0")  # the basic attack
    mid = spawn_id(5)  # a slow melee monster (zombie1)
    if mid is None:
        return add(name, "BLOCKED", "could not spawn a monster")
    time.sleep(1.5)
    hovered, life0, lives = False, None, []
    for step in range(24):
        st = hstate()
        mons = [m for m in st["mons"] if m["id"] == mid]
        if not mons:
            lives.append("gone")
            break
        m = mons[0]
        if life0 is None:
            life0 = m["life"]
        lives.append(m["life"])
        sx, sy = _mon_screen(st["player"], m)
        g.click(sx / 1600.0, sy / 900.0, move_only=True)
        time.sleep(0.4)
        g.click((sx + 2) / 1600.0, (sy + 2) / 900.0, move_only=True)
        time.sleep(0.5)
        ok, lines = g.hcmd("hover", 5)
        hm = re.search(r"hover id=(\d+) type=(\d+) class=(\d+) age_ms=(\d+)", " ".join(lines))
        if hm and int(hm.group(1)) == mid and int(hm.group(4)) < 1500:
            hovered = True
        g.click((sx + 2) / 1600.0, (sy + 2) / 900.0)  # left click = the basic attack on the hovered monster
        time.sleep(1.5)
    shot = sh("monster_fight")
    st = hstate()
    left = [m for m in st["mons"] if m["id"] == mid]
    dead = not left or left[0]["life"] == 0
    bad = []
    if not hovered:
        bad.append("the game never reported the spawned monster (id %d) as hovered" % mid)
    if life0 is None or not (dead or (left and left[0]["life"] < life0)):
        bad.append("the clicks did not hurt the monster (life %s)" % lives)
    kill_all_near()
    add(name, "PASS" if not bad else "FAIL",
        "spawned zombie1 id %d next to the player; the mouse moved over its projected position (harness `hover` reports the unit under "
        "the cursor): %s; left clicks on it: life %s, %s%s" % (mid, "hovered" if hovered else "NOT hovered", lives, "killed" if dead else "alive",
                                                           ("; " + "; ".join(bad)) if bad else ""), [shot], [str(lives)])

def _cd_counts():
    """`h state`'s cooldowns line: (on, starts, reduced, shared, dropped, monsters) or None (retried: the answer can be cut short)."""
    for _ in range(4):
        for ln in hstate()["lines"]:
            m = re.match(r"cooldowns (on|off): starts=(-?\d+) reduced=(-?\d+) shared=(-?\d+) dropped=(-?\d+) monsters=(-?\d+)", ln)
            if m:
                return (m.group(1) == "on",) + tuple(int(x) for x in m.groups()[1:])
        time.sleep(0.5)
    return None


def _cd_frame():
    return hstate()["player"].get("frame")


_CD_LAST = {}


def _cd_wait_ready(skill, timeout=40):
    """Until `h skills` calls the skill usable (0) again: its cooldown (stat 359 at layer = skill id) has run out. The last
    usability code is kept in _CD_LAST for the failure note (1 mana / cooldown, 2 requirements, 7 no level)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        _ok, lines = H("skills")
        u = next((re.search(r"usable=(-?\d+)", ln) for ln in lines if re.match(r"skill id=%d " % skill, ln)), None)
        _CD_LAST[skill] = int(u.group(1)) if u else None
        if u and int(u.group(1)) == 0:
            return True
        time.sleep(0.5)
    return False


def _cd_cast(skill):
    """Cast the skill at a spawned monster and wait for the cooldown stat (359, layer = skill id) to appear: (end frame, frame
    when seen) or (None, None). The stat holds the end frame of D2R's per-skill cooldown timer."""
    H("spawn 18 1")
    H("stat player 8 set %d" % (3000 << 8))
    ok, _lines = H("cast %d nearest" % skill)
    t0 = time.time()
    while ok and time.time() - t0 < 6:
        time.sleep(0.15)
        end = rd("player", 359, skill)
        if end:
            return end, _cd_frame()
        if not ok:
            break
    return None, None


# A monster class with a skill that has a constant localdelay (built mod): Andariel (156) andariel_skill_2 (812, delay 125, anim SC = special cast, mode 7)
_CD_MON = (156, 812, 7)


def _cd_monster():
    """Median has no cooldown for non-players (D2Sigma 0x100b0a40+0x70: a unit that is not a player is always ready, and the start
    stores into the player's table only). A spawned monster uses a skill with a localdelay twice in a row (harness `mcast`, the
    AI's skill use 0x4a7bc0): both uses start, and the monster keeps no cooldown (stat 359 at the skill's layer and states 0xb9 /
    0x79 stay clear; D2R would store them), the plugin's `monsters` counter counts the two skipped starts. (problems, notes)."""
    cls, skill, mode = _CD_MON
    problems, notes = [], []
    c0 = _cd_counts()
    mid = spawn_id(cls)
    if mid is None:
        return ["no monster of class %d could be spawned" % cls], notes
    time.sleep(2)  # a monster that was just spawned is not a valid target yet
    seen = []
    for n in (1, 2):
        ok, lines = H("mcast %d %d unit %d" % (skill, mode, mid))
        text = " ".join(lines)
        m = re.search(r"returned (-?\d+), unit mode (\d+) -> (\d+), stat359\[\d+\]=(-?\d+) state 0xb9=(\d) state 0x79=(\d)", text)
        seen.append(m.groups() if m else None)
        if not ok or not m:
            problems.append("monster use %d of skill %d refused (%s)" % (n, skill, text[:160]))
            break
        deadline = time.time() + 6  # the attack animation runs; the skill finishes (and would start its cooldown) at its action frame
        while time.time() < deadline and _cd_counts()[5] - c0[5] < n and not rd("m%d" % mid, 359, skill):
            time.sleep(0.1)
        notes.append("use %d: %s; monsters counter +%d" % (n, m.group(0)[:120], _cd_counts()[5] - c0[5]))
    skipped = _cd_counts()[5] - c0[5]
    end = rd("m%d" % mid, 359, skill)
    notes.append("after both uses: stat 359 at layer %d = %s, monsters counter +%d (starts of non-players not passed on)" % (skill, end, skipped))
    if len(seen) == 2 and None not in seen:
        if end or any(x[4] != "0" or x[5] != "0" for x in seen):
            problems.append("the monster holds a cooldown (stat 359 at layer %d = %s, uses read %s): its start was passed on to D2R" % (skill, end, seen))
        if skipped:
            notes.append("the hook skipped %d start(s) D2R made for the monster" % skipped)
        else:
            notes.append("the monster's skill finish made no cooldown start at all (the hook has nothing to skip on this path)")
    H("kill %d" % mid)
    return problems, notes


# Barbarian skills of one skills2 cooldown group with a constant localdelay (built mod, mxl_cooldowns.h): group -> {skill: delay,
# reduction to test}. The first group whose skills the test character may use is tested.
_CD_GROUPS = (("99 (Deep Freeze, Thunderstorm, Purifying Flame, Mana Sweep)", {1310: 300, 1275: 300, 1309: 625, 1651: 480}, 200),
              ("4 (Blast Wave, skills_460, Cold Fear, Thunder Slam, Elvensong, Mind Control)", {554: 500, 532: 625, 1840: 350, 1954: 375, 1386: 500, 1897: 125}, 100),
              ("1 (Leap, Spirit Walk)", {1323: 75, 1290: None}, 50))
_CD_CONTROL = 1320  # Spirit Reave: localdelay 200, no group


def _cd_usable(skills):
    _ok, lines = H("skills")
    out = {}
    for ln in lines:
        m = re.match(r"skill id=(\d+) .*usable=(-?\d+)", ln)
        if m and int(m.group(1)) in skills:
            out[int(m.group(1))] = int(m.group(2))
    return out


def check_cooldowns():
    """Median's real cooldown reduction and shared groups (D2Sigma 0x100b0f40 / 0x100b1140 / 0x100b0ab0; audit section 4): the
    delay of a cooldown is the skill's localdelay minus stat 309 at layer = the skill id, and the skills of one skills2
    cooldown group share one timer. A skill of a group (the first usable one of _CD_GROUPS) is cast with stat 309 = 0 and with a
    reduction: the cooldown stat (359, layer = skill id) the game keeps must differ by the reduction (the plugin's `reduced`
    counter must rise); the group's other skills must then be on cooldown with the same end frame (`shared` counter, `h skills`
    usable code), and Spirit Reave (no group) must not be touched."""
    nm = "Cooldowns (Median): stat 309 shortens a skill's cooldown, skills of one group share one timer"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    c0 = _cd_counts()
    if c0 is None or not c0[0]:
        return add(nm, "FAIL", "plugin part cooldowns is not on (h state: %s; lines %s)" % (c0, [ln[:60] for ln in hstate()["lines"]][-8:]))
    goto(2)
    kill_all_near()
    god(True)
    problems, notes = [], []
    allskills = {sk for _g, d, _r in _CD_GROUPS for sk in d} | {_CD_CONTROL}
    for sk in sorted(allskills):
        H("setskill %d 1" % sk)
    base_level = rd("player", 12)
    setstat("player", 12, 80)  # the skills need character level 15-30
    codes = _cd_usable(allskills)
    notes.append("usable codes at level 80 (0 usable, 1 mana / cooldown, 2 requirements): %s" % codes)
    pick = None
    for label, delays, red in _CD_GROUPS:
        ok_skills = [sk for sk in delays if codes.get(sk) == 0]
        if len(ok_skills) >= 2:
            pick = (label, ok_skills, delays, red)
            break
    if pick is None:
        setstat("player", 12, base_level or 21)
        god(False)
        return add(nm, "FAIL", "no group with two usable skills for the test character | " + " | ".join(notes), [sh("cooldowns")])
    label, group, delays, red_amount = pick
    main, others = group[0], group[1:]
    base309 = rd("player", 309, main)
    durs = {}
    try:
        for red in (0, red_amount):
            for sk in group:
                setstat("player", 309, 0, sk)
            setstat("player", 309, red, main)
            if not _cd_wait_ready(main):
                problems.append("skill %d never became ready again before the cast with reduction %d (usable code %s)" % (main, red, _CD_LAST.get(main)))
                continue
            for sk in others:
                _cd_wait_ready(sk)
            before = _cd_counts()
            end, seen = _cd_cast(main)
            if end is None:
                problems.append("reduction %d: the cast of skill %d left no cooldown stat 359 at layer %d (cast refused, or the start hook never ran)" % (red, main, main))
                continue
            durs[red] = end - seen
            after = _cd_counts()
            notes.append("group %s, skill %d, reduction %d: end frame %d seen at %d -> %d frames left; starts %s->%s reduced %s->%s shared %s->%s dropped %s->%s" % (
                label, main, red, end, seen, end - seen, before[1], after[1], before[2], after[2], before[3], after[3], before[4], after[4]))
            if red and after[2] <= before[2]:
                problems.append("stat 309 = %d did not count as reduced (%s -> %s)" % (red, before[2], after[2]))
            if after[3] - before[3] < 1:
                problems.append("reduction %d: no shared start counted for the group's other skills" % red)
            usable = _cd_usable(allskills)
            ends = {sk: rd("player", 359, sk) for sk in sorted(allskills)}
            for sk in others:  # the same end frame: they are read one after the other, so a later start of a moving skill can lie between
                if usable.get(sk) == 0:
                    problems.append("reduction %d: group skill %d is not on cooldown after skill %d (usable 0)" % (red, sk, main))
                if ends[sk] != ends[main]:
                    problems.append("reduction %d: group skill %d ends at %s, skill %d at %s (one shared timer)" % (red, sk, ends[sk], main, ends[main]))
            if codes.get(_CD_CONTROL) == 0 and ends[_CD_CONTROL]:
                problems.append("reduction %d: Spirit Reave (no group) got a cooldown (end %s)" % (red, ends[_CD_CONTROL]))
            notes.append("  stat 359 ends %s usable %s" % (ends, usable))
        mp, mn = _cd_monster()
        problems += mp
        notes += mn
    finally:
        setstat("player", 309, base309 or 0, main)
        setstat("player", 12, base_level or 21)
        god(False)
        kill_all_near()
    if 0 in durs and red_amount in durs:
        gain = durs[0] - durs[red_amount]
        if abs(gain - red_amount) > 20:
            problems.append("stat 309 = %d shortened the cooldown by %d frames (%d -> %d)" % (red_amount, gain, durs[0], durs[red_amount]))
        want = delays.get(main)
        if want and not want - 35 <= durs[0] <= want + 5:
            problems.append("cooldown without reduction is %d frames, expected about %d (localdelay)" % (durs[0], want))
    add(nm, "FAIL" if problems else "PASS", "%s | %s" % ("; ".join(problems) if problems else "reduction and sharing as Median", " | ".join(notes)),
        [sh("cooldowns")])


def corpse_view():
    """Every body the game could show, on the SERVER and on the CLIENT (`h state` + `h ccorpses`), as numbers:
    srv_other = player-type units other than the character in any mode, mode17 = those in corpse mode 0x11, stored = entries in
    the character's corpse list (what a save writes as its "JM" corpse section), cli_other = player units other than the character
    in the client's own unit table (what the screen draws), plus the character's items / gold / experience for the comparisons.
    A value is None when the harness line is missing (old plugin): the callers treat that as a failure, never as zero."""
    st = hstate()
    txt = " ".join(st["lines"])
    mb = re.search(r"bodies other=(\d+) stored=(\d+) id0=(\d+) hidden=\d+ \| corpse pickup (\w+): enters=(\d+) picked=(\d+) kept=(\d+) faults=(\d+)", txt)
    mc = re.search(r"corpses (\d+) players=(\d+) self=(\d)", txt)
    sk = re.search(r"no corpse (\w+): skipped corpse calls=(\d+) penalty calls=(\d+) respawns held=(\d+) let=(\d+) xp=(\d+)", txt)
    _ok, cl = H("ccorpses")
    cc = re.search(r"ccorpses players=(\d+) self=(\d+) other=(\d+) hidden=\d+ ids=(.*)", " ".join(cl))
    p = st["player"]
    return {
        "srv_other": int(mb.group(1)) if mb else None, "stored": int(mb.group(2)) if mb else None, "stored_id": int(mb.group(3)) if mb else None,
        "pickup_on": mb.group(4) == "on" if mb else None,
        "enters": int(mb.group(5)) if mb else None, "picked": int(mb.group(6)) if mb else None, "kept": int(mb.group(7)) if mb else None,
        "faults": int(mb.group(8)) if mb else None,
        "mode17": int(mc.group(1)) if mc else None, "players": int(mc.group(2)) if mc else None, "self": int(mc.group(3)) if mc else None,
        "cli_other": int(cc.group(3)) if cc else None, "cli_self": int(cc.group(2)) if cc else None, "cli_ids": cc.group(4).strip() if cc else None,
        "on": sk.group(1) == "on" if sk else None, "skc": int(sk.group(2)) if sk else None, "skp": int(sk.group(3)) if sk else None,
        "held": int(sk.group(4)) if sk else None, "let": int(sk.group(5)) if sk else None, "xp": int(sk.group(6)) if sk else None,
        "eq": sorted((str(i.get("code")), i.get("body")) for i in st["items"] if i.get("body", 0) > 0),
        "items": len(st["items"]),
        "gold": p.get("gold"), "bank": p.get("bank"), "area": p.get("area"), "mode": p.get("mode"), "level": p.get("level"),
        "frame": p.get("frame"), "x": p.get("x"), "y": p.get("y"),
    }


def body_problems(label, v):
    """Median: no body anywhere. Empty list = none on the server, none on the client, none stored."""
    out = []
    for key, what in (("srv_other", "player-type units other than the character on the server"), ("mode17", "units in corpse mode 0x11 on the server"),
                      ("stored", "entries in the character's corpse list"), ("cli_other", "player-type units other than the character on the client")):
        if v[key] is None:
            out.append("%s: no reading of %s (old plugin, or `h state` / `h ccorpses` failed)" % (label, what))
        elif v[key] != 0:
            out.append("%s: %d %s" % (label, v[key], what))
    return out


def save_corpse_count(path=None):
    """The corpse count of a closed .d2s (docs/save-format.md): `JM 00 00 jf` = none; `JM 01 00` + 12 byte header + `JM` = one."""
    path = path or os.path.join(SAVES, g.CHAR_NAME + ".d2s")
    if not os.path.exists(path):
        return None
    d = open(path, "rb").read()
    if b"JM\x00\x00jf" in d:
        return 0
    if re.search(rb"JM\x01\x00\x00\x00\x00\x00.{8}JM", d, re.S):
        return 1
    return None


def _wait_dead(secs=14):
    for _ in range(secs):
        time.sleep(1)
        if hstate()["player"].get("mode") == 17:
            return True
    return hstate()["player"].get("mode") in (0, 17)


def _die(atk_ref):
    """One real death: a 2e9 hit from a spawned monster (life and mana topped up first, so only the hit kills). Returns (hit line, hit lines)."""
    setstat("player", 7, BIG_LIFE)
    setstat("player", 6, 256 * 100)
    ok, line, lines = hv("hit player phys 2000000000 %s" % atk_ref, "hit")
    return line, lines


def _respawn_after_wait(dead_frame):
    """Esc at once (must be held back), then the real respawn after the 5 s wait. Returns the snapshot a second after the early Esc,
    whether the game process survived, and whether the character was dead (revive_if_dead's answer)."""
    g.press("esc")
    time.sleep(1)
    early = corpse_view()
    waited = 0
    while waited < 15 and (hstate()["player"].get("frame") or 0) - (dead_frame or 0) < 130:
        time.sleep(1)
        waited += 1
    revived = revive_if_dead()
    time.sleep(2)
    return early, revived


def _round_problems(label, before, dead, early, after, revived, line, town_ok):
    """The checks of one death: the character died, the hooks saw it, no body anywhere in any of the three moments, the gear / gold /
    bank / experience as before, the early Esc held back, the respawn in a town."""
    pr = []
    if dead["mode"] not in (0, 17):
        pr.append("%s: the character did not die (mode %s): %s" % (label, dead["mode"], line[:90]))
    if (dead["skc"] or 0) <= (before["skc"] or 0) or (dead["skp"] or 0) <= (before["skp"] or 0):
        pr.append("%s: the death did not reach the corpse creator / penalty hooks (skipped calls %s/%s -> %s/%s)" % (
            label, before["skc"], before["skp"], dead["skc"], dead["skp"]))
    for moment, v in (("dead", dead), ("after the early Esc", early), ("after the respawn", after)):
        pr += body_problems("%s %s" % (label, moment), v)
        for k in ("eq", "gold", "bank", "xp"):
            if v[k] != before[k]:
                pr.append("%s %s: %s changed %s -> %s" % (label, moment, k, before[k], v[k]))
    if not revived or after["mode"] in (0, 17):
        pr.append("%s: respawn failed (revived %s, mode %s)" % (label, revived, after["mode"]))
    if early["mode"] not in (0, 17):
        pr.append("%s: the respawn at once was not held back (mode %s a second after the death)" % (label, early["mode"]))
    if (early["held"] or 0) <= (before["held"] or 0):
        pr.append("%s: the plugin did not count a held respawn request (%s -> %s)" % (label, before["held"], early["held"]))
    if (after["let"] or 0) <= (before["let"] or 0):
        pr.append("%s: the respawn after the wait did not pass the hook (let through %s -> %s)" % (label, before["let"], after["let"]))
    if town_ok and after["area"] not in (1, 40, 75, 103, 109):
        pr.append("%s: not in a town after the respawn (area %s)" % (label, after["area"]))
    return pr


def check_nocorpse():
    """Median's death rules (docs/subsystems/death.md; audit rows DC1-DC4): a dying player leaves NO corpse at all, keeps the
    equipment, loses neither gold nor experience, and the respawn request is held back for 5 s (125 frames).
    The character gets three equipped items, gold and a big experience value, then dies three times in a row (two in the field,
    one in the town), each time by a monster's hit; every time Esc at once (refused), Esc after 125 frames (works, in town).
    "No corpse" is absolute: at the start, while dead, after the early Esc and after each respawn there must be NO player-type
    unit other than the character on the server (any mode), none on the CLIENT (the screen draws the client's units), no entry
    in the character's corpse list, the same items on the same body locations, the same gold, bank and experience, and no gold pile.
    After the first death the field is entered again and the death spot is photographed (a screenshot and a unit count there).
    At the end Save and Exit + Play: the saved .d2s has corpse count 0 and the reloaded character still has no body.
    The plugin counts the calls it swallowed (`h state`): they must have risen at every death, or nothing was tested."""
    nm = "No corpse on death (Median): no corpse anywhere (server, client, saved list), gear and belt kept, gold and xp unchanged, respawn after 5 s, 3 deaths + save/reload"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    fight_ready()
    level0, xp0 = rd("player", 12), rd("player", 13)
    H("unequip lring")
    H("unequip amulet")
    ok1, _l1 = H("equip rin lring")
    ok2, _l2 = H("equip amu amulet")
    H("unequip belt")
    ok3, _l3 = H("equip 629 belt")  # a belt (Median code 629): the belt's potions would go to the corpse in D2 (audit DC1); the harness cannot fill a belt
    H("gold set 23456 7890")
    if level0 is not None and level0 < 2:
        setstat("player", 12, 20)  # the experience penalty only exists above level 1
    setstat("player", 13, 1000000000)
    atk = spawn_attacker(1)
    if atk is None or not (ok1 and ok2 and ok3):
        return add(nm, "BLOCKED", "no attacker monster" if atk is None else "could not equip the three test items")
    pids = sorted(g.game_pids())
    before = corpse_view()
    ground0 = ground_count("gld")
    problems = body_problems("start", before)
    if before["on"] is not True:
        problems.append("plugin part nocorpse is not on: %s" % before["on"])
    if before["self"] != 1 or before["cli_self"] != 1:
        problems.append("the unit scans do not see the character itself (server %s, client %s): the body counts mean nothing" % (before["self"], before["cli_self"]))
    if len(before["eq"]) < 2:
        problems.append("fewer than two equipped items before the first death: %s" % before["eq"])
    shots, notes, lines_all = [], [], []
    notes.append("stored corpses picked up when the character entered the game: level entries %s, picked %s, kept %s, faults %s" % (
        before["enters"], before["picked"], before["kept"], before["faults"]))
    if before["pickup_on"] is not True:
        problems.append("plugin part corpsepickup is not on: %s" % before["pickup_on"])
    if (before["kept"] or 0) != 0 or (before["faults"] or 0) != 0:
        problems.append("a stored corpse could not be picked up (kept %s, faults %s)" % (before["kept"], before["faults"]))
    spot = None
    for n, (label, town) in enumerate((("death 1 (field)", False), ("death 2 (field)", False), ("death 3 (town)", True)), start=1):
        if town:
            revive_if_dead()
            if hstate()["player"].get("area") not in (1, 40, 75, 103, 109):
                goto(1)
        else:
            if hstate()["player"].get("area") != 2:
                goto(2)
            close_menu()
            kill_all_near()
        atk = spawn_attacker(1)
        if atk is None:
            problems.append("%s: no attacker monster" % label)
            continue
        pos = hstate()["player"]
        if n == 1:
            spot = (pos.get("x"), pos.get("y"), pos.get("area"))
        setstat("player", 13, 1000000000)  # clearing the area gave experience (clamped by the level cap): the same numbers before every death
        H("gold set 23456 7890")
        round_before = corpse_view()
        if round_before["eq"] != before["eq"]:
            problems.append("%s: the gear differs from the start of the check: %s -> %s" % (label, before["eq"], round_before["eq"]))
        line, hl = _die(atk)
        lines_all += hl
        _wait_dead(6 if town else 14)
        dead = corpse_view()
        if town and dead["mode"] not in (0, 17):
            # The engine does not let a character die in a town (the damage leaves it at 100 life; `kill player` the same): nothing to
            # respawn from. What can be checked is that the attempt made no body and moved no gear, gold or experience.
            life_town = hstate()["player"].get("life")
            notes.append("%s: the character cannot die in the town (2e9 hit: mode %s, life %s); bodies srv/mode17/stored/cli %s/%s/%s/%s" % (
                label, dead["mode"], life_town, dead["srv_other"], dead["mode17"], dead["stored"], dead["cli_other"]))
            problems += body_problems("%s attempt" % label, dead)
            for k in ("eq", "gold", "bank", "xp"):
                if dead[k] != round_before[k]:
                    problems.append("%s attempt: %s changed %s -> %s" % (label, k, round_before[k], dead[k]))
            setstat("player", 7, BIG_LIFE)
            H("kill %s" % atk.split(":")[-1])  # the attacker (town NPCs stay)
            continue
        shots.append(sh("nocorpse_%d_dead" % n))
        early, revived = _respawn_after_wait(dead["frame"])
        after = corpse_view()
        shots.append(sh("nocorpse_%d_respawned" % n))
        survived = sorted(g.game_pids()) == pids and hstate()["ok"]
        if not survived:
            problems.append("%s: the game process did not survive" % label)
        problems += _round_problems(label, round_before, dead, early, after, revived, line, True)
        if after["area"] == round_before["area"] and ground_count("gld") != ground0:
            problems.append("%s: gold piles on the ground %s -> %s" % (label, ground0, ground_count("gld")))
        notes.append("%s: hooks swallowed corpse %s->%s penalty %s->%s, dead mode %s, bodies srv/mode17/stored/cli %s/%s/%s/%s -> after respawn %s/%s/%s/%s, area %s -> %s, frames %s->%s->%s" % (
            label, round_before["skc"], dead["skc"], round_before["skp"], dead["skp"], dead["mode"], dead["srv_other"], dead["mode17"], dead["stored"],
            dead["cli_other"], after["srv_other"], after["mode17"], after["stored"], after["cli_other"], round_before["area"], after["area"],
            dead["frame"], early["frame"], after["frame"]))
        if n == 1 and spot and spot[0] is not None:
            # the death spot: back to the field, to the exact place, count the units there and photograph it
            goto(spot[2] or 2)
            close_menu()
            H("move %d %d" % (spot[0], spot[1]))
            time.sleep(4)
            at_spot = corpse_view()
            shots.append(sh("nocorpse_death_spot"))
            problems += body_problems("death spot (%s,%s)" % (spot[0], spot[1]), at_spot)
            notes.append("death spot %s,%s in area %s revisited: bodies srv/mode17/stored/cli %s/%s/%s/%s" % (
                spot[0], spot[1], spot[2], at_spot["srv_other"], at_spot["mode17"], at_spot["stored"], at_spot["cli_other"]))
    # Save and Exit + Play: the written save has no corpse, the reloaded character has no body and the same gear
    pre_save = corpse_view()
    if leave_and_reenter():
        time.sleep(3)
        reloaded = corpse_view()
        problems += body_problems("after Save and Exit + Play", reloaded)
        cnt = save_corpse_count()
        if cnt != 0:
            problems.append("the saved .d2s has corpse count %s (want 0)" % cnt)
        if reloaded["eq"] != before["eq"]:
            problems.append("after Save and Exit + Play the gear differs: %s -> %s" % (before["eq"], reloaded["eq"]))
        notes.append("saved .d2s corpse count %s; reloaded: bodies srv/stored/cli %s/%s/%s, gear %s" % (
            cnt, reloaded["srv_other"], reloaded["stored"], reloaded["cli_other"], reloaded["eq"]))
        shots.append(sh("nocorpse_reloaded"))
    else:
        problems.append("could not Save and Exit + Play")
    add(nm, "FAIL" if problems else "PASS",
        "%s | before: items %s gold %s bank %s xp %s, bodies srv/mode17/stored/cli %s/%s/%s/%s; %s" % (
            "; ".join(problems) if problems else "all unchanged, no body anywhere", before["eq"], before["gold"], before["bank"], before["xp"],
            before["srv_other"], before["mode17"], before["stored"], before["cli_other"], " | ".join(notes)), shots, lines_all)
    # put the test character back
    H("unequip lring")
    H("unequip amulet")
    H("unequip belt")
    setstat("player", 13, xp0 if xp0 is not None else 0)
    if level0 is not None:
        setstat("player", 12, level0)
    setstat("player", 6, rd("player", 7) or BIG_LIFE)


def _leave_and_reenter():
    """Save and Exit + Play; a second try when the first Esc did not open the pause menu (right after a load the click can land in the world)."""
    for _ in range(3):
        if leave_and_reenter():
            return True
        time.sleep(3)
        if not hstate()["ok"]:
            return False
    return False


def _plugin_dir():
    return os.path.join(g.GAME_DIR, "mods", "D2R-XL", "d2rloader", "plugins")


def _write_off(words):
    """mxl-core-off.txt next to mxl-core.dll (read at load): the listed parts are left out. No words = file removed."""
    p = os.path.join(_plugin_dir(), "mxl-core-off.txt")
    if words:
        with open(p, "w") as f:
            f.write(" ".join(words) + "\n")
    elif os.path.exists(p):
        os.remove(p)


def _restart(off_words):
    """Close the game, set the off words, start it, play the character: True when in a game."""
    _write_off(off_words)
    STATE["in_game"] = False
    if not to_menu():
        return False
    return enter_game()


def check_corpsepickup():
    """Stored corpses (a character saved by D2R's own death, before the part existed) are picked up at load (docs/subsystems/death.md
    section 8). The check makes such a character itself, with D2R's own corpse creator, then loads it twice:
      1. mxl-core-off.txt `nocorpse` (the control for check `nocorpse`): the character equips ring, amulet and belt and dies in the
         field; D2R makes a corpse (a body unit, a corpse list entry) and moves the gear onto it; Save and Exit: the saved .d2s has
         corpse count 1 and the gear is gone from the character;
      2. off word `corpsepickup` (the control for the pickup): the character loads with the body visible on the server AND the client;
      3. all parts on: the body is picked up at load - no body on the server, none on the client, the corpse list empty, the gear
         on its body locations again (the same items), the counter `picked` up; Save and Exit + Play: the saved .d2s has corpse count 0.
    The test character's files are copied first and put back at the end (the stored corpse is a test fixture)."""
    nm = "Stored corpse is picked up at load (Median): gear back, no body on server / client / in the save; controls with nocorpse / corpsepickup off"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    d2s = os.path.join(SAVES, g.CHAR_NAME + ".d2s")
    keep = os.path.join(g.current_run(), "corpsepickup-save")
    os.makedirs(keep, exist_ok=True)
    for ext in (".d2s", ".d2rl"):
        if os.path.exists(os.path.join(SAVES, g.CHAR_NAME + ext)):
            shutil.copy2(os.path.join(SAVES, g.CHAR_NAME + ext), keep)
    problems, notes, shots, blocked = [], [], [], []
    try:
        fight_ready()
        level0, xp0 = rd("player", 12), rd("player", 13)
        # step 0: the gear the corpse will hold, on the character now; Save and Exit so the file has it, then restart with nocorpse off
        H("unequip lring")
        H("unequip amulet")
        ok1, _ = H("equip rin lring")
        ok2, _ = H("equip amu amulet")
        H("unequip belt")
        ok3, _ = H("equip 629 belt")
        if not (ok1 and ok2 and ok3):
            blocked.append("could not equip the three test items")
            return
        gear0 = corpse_view()["eq"]
        if len(gear0) < 2:
            blocked.append("fewer than two equipped items: %s" % gear0)
            return
        if not _leave_and_reenter():
            blocked.append("could not Save and Exit + Play")
            return
        gear_saved = corpse_view()["eq"]
        notes.append("gear before: %s (after a save and reload: %s)" % (gear0, gear_saved))
        # step 1: nocorpse off - the control: D2R makes the corpse
        if not _restart(["nocorpse"]):
            blocked.append("could not restart with nocorpse off")
            return
        v = corpse_view()
        if v["on"] is True:
            problems.append("control: nocorpse still reports on after the off word")
        fight_ready()
        atk = spawn_attacker(1)
        if atk is None:
            blocked.append("no attacker monster")
            return
        line, hl = _die(atk)
        _wait_dead()
        dead = corpse_view()
        shots.append(sh("corpsepickup_control_dead"))
        notes.append("control nocorpse off: dead (mode %s), bodies srv/mode17/stored/cli %s/%s/%s/%s, gear %s" % (
            dead["mode"], dead["srv_other"], dead["mode17"], dead["stored"], dead["cli_other"], dead["eq"]))
        revive_if_dead()
        time.sleep(2)
        town = corpse_view()
        shots.append(sh("corpsepickup_control_town"))
        notes.append("control nocorpse off: in town (area %s) bodies srv/stored/cli %s/%s/%s, gear %s" % (
            town["area"], town["srv_other"], town["stored"], town["cli_other"], town["eq"]))
        if not (dead["srv_other"] or dead["mode17"] or dead["stored"]):
            problems.append("control: with nocorpse off no corpse appeared (the check cannot see bodies, or the death did not run D2R's creator)")
        if (town["srv_other"] or 0) + (town["stored"] or 0) == 0:
            problems.append("control: the corpse did not follow the character to town (no body on the server, none stored)")
        if not _leave_and_reenter():
            problems.append("could not Save and Exit + Play with nocorpse off")
        # the stored corpse is in the save now: closed file check
        STATE["in_game"] = False
        g.stop()
        time.sleep(3)
        cnt = save_corpse_count()
        notes.append("saved .d2s corpse count after the control death: %s" % cnt)
        if cnt != 1:
            problems.append("control: the saved .d2s has corpse count %s after a death with nocorpse off (want 1)" % cnt)
        shutil.copy2(d2s, os.path.join(keep, "with-corpse.d2s"))
        sidecar = os.path.join(SAVES, g.CHAR_NAME + ".d2rl")
        if os.path.exists(sidecar):
            shutil.copy2(sidecar, os.path.join(keep, "with-corpse.d2rl"))
        # step 2: corpsepickup off - the corpse loads and is visible
        if not _restart(["corpsepickup"]):
            blocked.append("could not restart with corpsepickup off")
            return
        time.sleep(8)  # the loading screen is still up for a few seconds after the state answers
        seen = corpse_view()
        shots.append(sh("corpsepickup_off_loaded"))
        notes.append("corpsepickup off: bodies srv/mode17/stored/cli %s/%s/%s/%s, gear %s, pickup on=%s" % (
            seen["srv_other"], seen["mode17"], seen["stored"], seen["cli_other"], seen["eq"], seen["pickup_on"]))
        if seen["pickup_on"] is not False:
            problems.append("control: corpsepickup should be off, reports %s" % seen["pickup_on"])
        if not ((seen["srv_other"] or 0) >= 1 and (seen["cli_other"] or 0) >= 1 and (seen["stored"] or 0) >= 1):
            problems.append("control: with corpsepickup off the stored corpse should be visible on server and client and in the list (srv/cli/stored %s/%s/%s)" % (
                seen["srv_other"], seen["cli_other"], seen["stored"]))
        # step 3: all parts on - the pickup
        g.stop()
        time.sleep(3)
        if not _restart([]):
            blocked.append("could not restart with all parts on")
            return
        time.sleep(8)
        got = corpse_view()
        shots.append(sh("corpsepickup_on_loaded"))
        notes.append("all on: bodies srv/mode17/stored/cli %s/%s/%s/%s, gear %s, pickup picked=%s kept=%s faults=%s enters=%s" % (
            got["srv_other"], got["mode17"], got["stored"], got["cli_other"], got["eq"], got["picked"], got["kept"], got["faults"], got["enters"]))
        problems += body_problems("after the load with the pickup on", got)
        if got["pickup_on"] is not True:
            problems.append("corpsepickup is not on: %s" % got["pickup_on"])
        if (got["picked"] or 0) < 1 or (got["kept"] or 0) != 0 or (got["faults"] or 0) != 0:
            problems.append("pickup counters picked/kept/faults %s/%s/%s (want >=1/0/0)" % (got["picked"], got["kept"], got["faults"]))
        if got["eq"] != gear_saved:
            problems.append("gear after the pickup %s differs from the gear before the death %s" % (got["eq"], gear_saved))
        if not _leave_and_reenter():
            problems.append("could not Save and Exit + Play after the pickup")
        else:
            time.sleep(3)
            again = corpse_view()
            problems += body_problems("after Save and Exit + Play", again)
            if again["eq"] != gear_saved:
                problems.append("gear after the reload %s differs from %s" % (again["eq"], gear_saved))
            cnt2 = save_corpse_count()
            notes.append("after the pickup, Save and Exit + Play: saved .d2s corpse count %s, gear %s" % (cnt2, again["eq"]))
            if cnt2 != 0:
                problems.append("the saved .d2s still has corpse count %s after the pickup" % cnt2)
            shots.append(sh("corpsepickup_reloaded"))
    finally:
        _write_off([])
        if not (STATE["in_game"] and hstate()["ok"]):
            # leave the game running with all parts on for the checks after this one
            if g.game_pids():
                g.stop()
                time.sleep(3)
            _restart([])
        add(nm, "BLOCKED" if blocked else ("FAIL" if problems else "PASS"),
            "%s | %s | saves kept in %s" % ("; ".join(blocked) if blocked else ("; ".join(problems) if problems else "stored corpse picked up, gear back, no body, save clean; both controls show the corpse"), " | ".join(notes), keep), shots)



def _excel(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data", "global", "excel", "base", name + ".txt")
    with open(path, encoding="utf-8-sig") as f:
        rows = [l.rstrip(chr(10)).split(chr(9)) for l in f]
    return rows[0], rows[1:]


CLASS_NAMES = ["Amazon", "Sorceress", "Necromancer", "Paladin", "Barbarian", "Druid", "Assassin"]


def check_levelcap():
    name = "Level cap 150 (experience.txt MaxLvl): XP near levels 99 / 120 / 149, stat and skill points, save and reload"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    cls = hstate()["player"].get("class")
    if not isinstance(cls, int) or cls >= len(CLASS_NAMES):
        return add(name, "BLOCKED", "player class %r" % (cls,))
    col = CLASS_NAMES[cls]
    xh, xrows = _excel("experience")
    maxlvl = int(next(r for r in xrows if r[0] == "MaxLvl")[xh.index(col)])
    lv = {int(r[0]): int(r[xh.index(col)] or 0) for r in xrows if r[0].isdigit()}  # row L = experience at which level L + 1 starts

    def start(level):  # experience at which `level` starts
        return lv[level - 1]

    ch, crows = _excel("charstats")
    crow = next(r for r in crows if r[0] == col)
    per_stat, per_skill = int(crow[ch.index("StatPerLevel")] or 0), int(crow[ch.index("SkillsPerLevel")] or 0)
    keep = {s: rd("player", s) for s in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13)}
    log, bad = [], []
    # The save file keeps the unused stat points in itemstatcost CSvBits of stat 4 and the unused skill points in those of stat 5
    # (Median: 11 and 9 bits, so 2047 and 511; D2R's own: 10 and 8). A character that earned every level-up point keeps far
    # less (5 * 149 = 745 and 149 plus the quests), so the cap never bites in play; this check must test level 150, not the cap,
    # so the numbers it saves are the ones a real level 150 character carries (an earlier check's leftovers piled them up to
    # 2327 / 567 on slot 1, and the file stored the saturated 2047 / 511: 11 and 9 bits, not a bug of the level cap).
    ih, irows = _excel("itemstatcost")
    bits = {}
    for r in irows:
        if r and r[0] in ("statpts", "newskills"):
            bits[r[0]] = int(r[ih.index("CSvBits")] or 0)
    max_stat, max_skill = (1 << bits.get("statpts", 0)) - 1, (1 << bits.get("newskills", 0)) - 1
    earned_stat, earned_skill = per_stat * (maxlvl - 1), per_skill * (maxlvl - 1)
    log.append("save widths: stat points %s bits (max %d), skill points %s bits (max %d); a level %d character earns %d / %d" % (
        bits.get("statpts"), max_stat, bits.get("newskills"), max_skill, maxlvl, earned_stat, earned_skill))
    if max_stat < earned_stat or max_skill < earned_skill:
        bad.append("the save width cannot hold what a level %d %s earns: %s" % (maxlvl, col, log[-1]))
    setstat("player", 4, per_stat * 97)  # what the climbs below start from: level 98 with every point earned and none spent
    setstat("player", 5, per_skill * 97)

    def now():
        return {"level": rd("player", 12), "xp": rd("player", 13) & 0xffffffff, "stat": rd("player", 4), "skill": rd("player", 5)}

    def climb(label, from_level, to_level, expect_level, expect_gain):
        """Put the character at the start of `from_level` and award the experience that ends at the start of `to_level` (D2R's own
        award function runs the level-ups): the level and the points granted must match the table."""
        setstat("player", 12, from_level)
        setstat("player", 13, start(from_level))
        a = now()
        H("xp %d" % max(start(to_level) - start(from_level), 0))
        b = now()
        gained = b["level"] - a["level"]
        ok = b["level"] == expect_level and gained == expect_gain and b["stat"] - a["stat"] == gained * per_stat and b["skill"] - a["skill"] == gained * per_skill
        log.append("%s: level %d -> %d (want %d), stat points %+d (want %+d), skill points %+d (want %+d), experience %d" % (
            label, a["level"], b["level"], expect_level, b["stat"] - a["stat"], expect_gain * per_stat, b["skill"] - a["skill"],
            expect_gain * per_skill, b["xp"]))
        if not ok:
            bad.append(log[-1])
        return b

    if maxlvl != 150:
        bad.append("built experience.txt MaxLvl is %d for %s" % (maxlvl, col))
    climb("level 98 -> 99", 98, 99, 99, 1)
    climb("level 99 -> 100 (the old cap)", 99, 100, 100, 1)
    climb("level 119 -> 120", 119, 120, 120, 1)
    climb("level 148 -> 149", 148, 149, 149, 1)
    climb("level 149 -> 150", 149, 150, 150, 1)
    b = now()
    H("xp 100000000")  # past the last level: the level and the points stay
    c = now()
    log.append("150 + 100000000 experience: level %d, stat points %+d, skill points %+d, experience %d" % (
        c["level"], c["stat"] - b["stat"], c["skill"] - b["skill"], c["xp"]))
    if c["level"] != 150 or c["stat"] != b["stat"] or c["skill"] != b["skill"]:
        bad.append(log[-1])
    top = climb("one award from level 99 to the end of the table", 99, 150, 150, 51)
    time.sleep(1)
    _, c12 = H("cstat 12")
    log.append("client copy of the level (cstat 12): %s" % (c12[0] if c12 else None))
    if not c12 or not c12[0].rstrip().endswith("= 150"):
        bad.append("client level: %s" % (c12[0] if c12 else None))
    shots = []
    g.key("c")
    time.sleep(1.5)
    shots.append(sh("levelcap_charsheet"))
    g.key("c")
    time.sleep(0.5)
    # save and reload: Save and Exit writes the character, Play loads it again
    ok = leave_and_reenter()
    if not ok:
        bad.append("could not leave and re-enter the game")
    else:
        time.sleep(3)
        d = now()
        saved = None
        sp = os.path.join(SAVES, g.CHAR_NAME + ".d2s")
        if os.path.exists(sp):
            with open(sp, "rb") as f:
                saved = f.read(0x1c)[0x1b]
        log.append("after Save and Exit and Play: level %d (saved header byte %s), experience %d (was %d), stat points %d (was %d), "
                   "skill points %d (was %d)" % (d["level"], saved, d["xp"], top["xp"], d["stat"], top["stat"], d["skill"], top["skill"]))
        if d["level"] != 150 or d["xp"] != top["xp"] or d["stat"] != top["stat"] or d["skill"] != top["skill"] or saved != 150:
            bad.append(log[-1])
    # the test character goes back to the numbers it had
    for s_, v in keep.items():
        v = v or 0
        if s_ == 4:  # the numbers it had, but never more than the save file can hold (it would store the saturated value)
            v = min(v, max_stat)
        elif s_ == 5:
            v = min(v, max_skill)
        setstat("player", s_, v)
    add(name, "PASS" if not bad else "FAIL",
        "%s (class %s, %d stat / %d skill points per level, MaxLvl %d): %s" % (
            "all steps hold" if not bad else "; ".join(bad), col, per_stat, per_skill, maxlvl, "; ".join(log)), shots, log)

# ------------------------------------------------------------------ the old "fix to test" rows of docs/bugs.md (4, 6, 10, 12, 16, 19)
# Background mode, harness verbs only. Expected values come from sources other than the migration being tested: Median's
# own cubemain.bin / skills2 caps / named tables (names, not ids) and the built levels.txt.

import json  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT_EXCEL = os.path.join(REPO, "work", "mod", "data", "global", "excel")
TOWNS = [1, 40, 75, 103, 109]  # the town of act 1-5


def _tsv(path):
    import csv
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


def _main_checkout(path):
    """A worktree keeps no extract/: fall back to the main checkout's copy."""
    if os.path.exists(path):
        return path
    alt = os.path.join(os.path.expanduser("~"), "mxl-d2r", os.path.relpath(path, REPO))
    return alt if os.path.exists(alt) else path


def _level_acts():
    t = _tsv(os.path.join(BUILT_EXCEL, "levels.txt"))
    h = t[0]
    return {int(r[h.index("Id")]): int(r[h.index("Act")] or 0) for r in t[1:] if len(r) > 4 and r[h.index("Id")].isdigit()}


def go(area):
    """Move to an area: D2R's `cheat goto` inside an act, the plugin's `level` (NPC travel) across acts."""
    acts = _level_acts()
    now = hstate()["player"].get("area")
    if now is not None and acts.get(now) != acts.get(area):
        revive_if_dead()
        H("level %d" % area)
        t0 = time.time()
        while time.time() - t0 < 40:
            time.sleep(2)
            st = hstate()
            if st["player"].get("area") == area:
                time.sleep(2)
                return st
    return goto(area)


def new_portals(before):
    st = hstate()
    return [o for o in st["objs"] if o["id"] not in before and o.get("class") in (59, 60, 600)]


def check_cowportals():
    """Bug #19: the five 'Cow Portal' output recipes (rows 2, 3, 85, 4962, 7453) open the level Median's cubemain names, and
    the 256 cleaned empty output cells are empty in D2R's records."""
    n1 = "Cube portal outputs (bug #19): each Cow Portal recipe opens its own level"
    n2 = "Cube outputs (bug #19): no stray quotes, D2R's empty slots match the txt"
    if not need_game():
        add(n1, "BLOCKED", "not in a game")
        return add(n2, "BLOCKED", "not in a game")
    # expected: Median's special byte 1 slots (cubemain.bin: 4-byte count, 0x148 records, slots at +0x4c step 0x54, byte +8,
    # word +6 = Median level number), level numbers -> D2R ids by idmap.json
    data = open(_main_checkout(os.path.join(REPO, "extract", "mxl", "data", "global", "excel", "cubemain.bin")), "rb").read()
    count = struct.unpack_from("<I", data, 0)[0]
    idmap = json.load(open(_main_checkout(os.path.join(REPO, "work", "named", "idmap.json")), encoding="utf-8"))
    level_id = {e["row"]: e["id"] for e in idmap["levels"]}
    wants = []
    for row in range(count):
        for slot in range(3):
            s = 4 + row * 0x148 + 0x4c + 0x54 * slot
            if data[s + 8] == 1:
                median = struct.unpack_from("<H", data, s + 6)[0]
                wants.append((row, slot, median, level_id.get(median)))
    acts = _level_acts()
    rows, bad = [], []
    log = []
    H("difficulty 2")
    H("quest 40 0 set")  # the Cow Level's own handler wants Baal killed in the game's difficulty
    try:
        for row, slot, median, want in wants:
            town = TOWNS[acts.get(want, 0)] if want is not None else 1
            go(town)
            before = {o["id"] for o in hstate()["objs"]}
            ok, lines = H("cubeout %d %d" % (row, slot))
            time.sleep(1.5)
            new = new_portals(before)
            dests = [o.get("dest") for o in new]
            log.append("row %d slot %d: Median level %d -> D2R %s, town %d: ok=%s new portal dest %s" % (row, slot, median, want, town, ok, dests))
            rows.append("row %d -> %s" % (row, dests))
            if not ok or want not in dests:
                bad.append("row %d wants level %s, got %s" % (row, want, dests))
        sh("cowportals")
    finally:
        H("difficulty 0")
    add(n1, "PASS" if wants and not bad else "FAIL",
        "%d portal outputs from cubemain.bin (Median level numbers -> idmap.json -> D2R ids): %s%s" % (
            len(wants), "; ".join(rows), ("; WRONG: " + "; ".join(bad)) if bad else ""), [sh("cowportals")], log)

    # --- the empty output cells
    txt = _tsv(os.path.join(BUILT_EXCEL, "cubemain.txt"))
    h = txt[0]
    cols = [h.index("output"), h.index("output b"), h.index("output c")]
    quotes = sum(1 for r in txt[1:] for c in cols if c < len(r) and '"' in r[c])
    want_mask = []
    for r in txt[1:]:
        m = 0
        for i, c in enumerate(cols):
            if c < len(r) and r[c].strip():
                m |= 1 << i
        want_mask.append(m)
    # The reply is one line per 50 recipes. The plugin used to drop a line now and then (about 7% of the replies: the
    # console file was opened with fopen_s while the harness polled it; fixed in HarnessEcho by lane cube-outputs). A lost
    # line shifted every later recipe by 50 and the check failed with differences that were no cube output at all (run
    # checks-20261022-212141-s1: rows 4950-4962, 5083-5100, 5133-...). Each chunk is read by its line labels and asked
    # again until complete.
    got, lost = "", []
    for first in range(0, len(want_mask), 2500):
        count = min(2500, len(want_mask) - first)
        wanted = list(range(first, first + count, 50))
        for attempt in range(4):
            ok, lines = H("cubeslots %d %d" % (first, count), 60)
            by_first = {int(m.group(1)): m.group(2) for m in (re.match(r"cubeslots (\d+) (\d+)$", l.strip()) for l in lines) if m}
            if all(w in by_first and len(by_first[w]) == min(50, first + count - w) for w in wanted):
                break
        else:
            lost.append("recipes %d..%d: lines missing at %s" % (first, first + count - 1, [w for w in wanted if w not in by_first]))
        got += "".join(by_first.get(w, "9" * min(50, first + count - w)) for w in wanted)   # 9: unread, shows as a difference
    diffs = [(i, want_mask[i], int(got[i])) for i in range(min(len(got), len(want_mask))) if want_mask[i] != int(got[i])]
    add(n2, "PASS" if quotes == 0 and len(got) == len(want_mask) and not diffs and not lost else "FAIL",
        "%d recipes: %d output cells with a quote in the built cubemain.txt; D2R's records (slot +0x5a/0x5b/0x5b) hold %d of %d "
        "slots the txt names and %d empty ones; differences (row, txt mask, D2R mask): %s" % (
            len(want_mask), quotes, sum(bin(m).count("1") for m in want_mask), len(want_mask) * 3,
            len(want_mask) * 3 - sum(bin(m).count("1") for m in want_mask), diffs[:12]), [],
        ["recipe %d: txt %d D2R %d" % d for d in diffs[:40]])


def _unique_of(key):
    """(base code, unique index) of a Median-only unique in the built uniqueitems.txt: the index is the data row (`item ... uniq=`)."""
    t = _tsv(os.path.join(BUILT_EXCEL, "uniqueitems.txt"))
    h = t[0]
    for row, r in enumerate(t[1:]):
        if r and r[0] == "medianxl:" + key:
            return r[h.index("code")], row
    raise KeyError(key)


def check_cubeoutputs():
    """Cube OUTPUT cells that name an item. Row 4950 (the Dulra catalyst unique + a perfect gem, op 18 on stat 520 = 1): both
    outputs (`useitem` and `gpw`, output b) come out. Row 26 (outputs a Median-only unique named `medianxl:SunstoneOfTheGods`): the
    item has that unique's base, quality unique and index. The qualified form is what D2R resolves in an output (the inputs
    take it too, docs/strings-namespace.md "Item references"); the empty-slot audit is `cowportals`."""
    nm = "Cube outputs craft (rows 4950, 26): both outputs of 4950 come out, row 26's medianxl: unique is created"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    goto(1)
    ensure_cube()
    cube = lambda: [i for i in hstate()["items"] if i.get("page") == 3]
    dul_code, dul_row = _unique_of("DulraCatalyst")
    sun_code, sun_row = _unique_of("SunstoneOfTheGods")
    H("cubeclear")
    H("item %s cube uniq=%d 520=1" % (dul_code, dul_row))   # row 4950: the catalyst's stat 520 is 1 (op 18, param 520, value 1)
    H("item gpw cube")
    ok1, l1 = H("cubecraft")
    out1 = sorted((i.get("code"), i.get("quality"), i.get("unique")) for i in cube())
    H("cubeclear")
    for code in ("x5x", "x6x", "x7x"):   # row 26's inputs
        H("item %s cube" % code)
    ok2, l2 = H("cubecraft")
    out2 = sorted((i.get("code"), i.get("quality"), i.get("unique")) for i in cube())
    H("cubeclear")
    want1 = sorted([(dul_code, 7, dul_row), ("gpw", 2, 0)])
    want2 = [(sun_code, 7, sun_row)]
    good = ok1 and ok2 and "recipe 4950 " in l1[0] and "recipe 26 " in l2[0] and out1 == want1 and out2 == want2
    add(nm, "PASS" if good else "FAIL",
        "row 4950: %s, cube holds (code, quality, unique index) %s, wanted %s; row 26: %s, cube holds %s, wanted %s" % (
            l1[0][:50], out1, want1, l2[0][:50], out2, want2), [], l1 + l2)


def _caps_sources():
    """Median row -> (mlvl, skcn) from work/formulas/skill_caps.txt, Median row -> D2R id (idmap.json), D2R id -> name."""
    caps = {}
    for line in open(_main_checkout(os.path.join(REPO, "work", "formulas", "skill_caps.txt")), encoding="utf-8").read().splitlines()[1:]:
        f = (line.split("\t") + ["", ""])[:3]
        if f[0].isdigit():
            caps[int(f[0])] = (int(f[1] or 0), f[2])
    idmap = json.load(open(_main_checkout(os.path.join(REPO, "work", "named", "idmap.json")), encoding="utf-8"))
    ids = {e["row"]: e["id"] for e in idmap["skills"]}
    names = {e["id"]: e["name"] for e in idmap["skills"]}
    return caps, ids, names


def _setskill(skill, level):
    """`setskill`: the base level the game's own point function stopped at."""
    for _ in range(2):
        ok, lines = H("setskill %d %d" % (skill, level))
        m = re.search(r"base level (-?\d+)", " ".join(lines))
        if m:
            return int(m.group(1))
        time.sleep(1)
    return None


def check_skillcaps():
    """Bug #4: the skill-point caps. `setskill` raises a skill with the game's own point function until the skpoints formula
    answers 999, so the level it stops at is the cap."""
    nm = "Skill point caps (bug #4): per-skill cap, +N to a skill (skcp), Specialization"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    caps, ids, names = _caps_sources()
    stat_id = {e["row"]: e["id"] for e in json.load(open(_main_checkout(os.path.join(REPO, "work", "named", "idmap.json")), encoding="utf-8"))["itemstatcost"]}
    skcp, pst4 = stat_id[449], stat_id[397]  # Median's stat rows -> D2R ids (the harness takes D2R's)
    # sample: a plain (no skcn lock formula) skill of each cap value, spread over classes by taking every 7th
    t = _tsv(os.path.join(BUILT_EXCEL, "skills.txt"))
    reqlevel = {int(r[t[0].index("*Id")]): int(r[t[0].index("reqlevel")] or 0) for r in t[1:] if r and r[t[0].index("*Id")].isdigit()}
    by_cap = {}
    for row, (mlvl, skcn) in sorted(caps.items()):
        if mlvl > 0 and not skcn and row in ids and row > 6 and reqlevel.get(ids[row], 999) <= 80:
            by_cap.setdefault(mlvl, []).append(row)
    sample = []
    for mlvl, rows in sorted(by_cap.items()):
        sample += [(rows[i], mlvl) for i in range(0, len(rows), max(1, len(rows) // 2))][:2]
    sample.sort(key=lambda x: x[0] % 7)  # not all low caps first
    lvl0 = hstate()["player"].get("level")
    H("stat player 12 set 99")
    log, bad, done = [], [], []
    try:
        for row, mlvl in sample[:16]:
            sid = ids[row]
            got = _setskill(sid, 99)
            log.append("skill %s (Median row %d, id %d): cap by skill_caps.txt %d, game stopped at %s" % (names.get(sid), row, sid, mlvl, got))
            done.append(sid)
            if got != mlvl:
                bad.append("%s %s != %d" % (names.get(sid), got, mlvl))
            # +3 to the skill (skcp: stat 449 with the skill id as its parameter) raises the cap by 3
            H("stat player %d %d set 3" % (skcp, sid))
            got3 = _setskill(sid, 99)
            H("stat player %d %d set 0" % (skcp, sid))
            log.append("  with +3 to the skill: stopped at %s (want %d)" % (got3, mlvl + 3))
            if got3 != mlvl + 3:
                bad.append("%s +3: %s != %d" % (names.get(sid), got3, mlvl + 3))
            _setskill(sid, 0)
        # Specialization: earthquake_2 (Median row of the barbarian's tab) has its cap raised by the tab's Specialization
        # Specialization's first point needs skill('skills_1835'.pst4) > 0: pst4 is that skill's passivecalc4 = syn4 = the
        # player's stat 426 with the skill as its parameter (D2R id 1907 for the Median row 1835); the cap rises by the
        # Specialization's calc1 = blvl / 2
        by_name = _skill_ids_by_name()[0]
        spec, quake, gate = by_name.get("specialization_3"), by_name.get("earthquake_2"), by_name.get("skills_1835")
        spec_ok = False
        if spec and quake and gate:
            base = _setskill(quake, 99)
            _setskill(quake, 0)
            _setskill(gate, 1)
            H("stat player %d %d set 1" % (pst4, gate))
            lvl = _setskill(spec, 10)
            raised = _setskill(quake, 99)
            want = (base or 0) + (lvl or 0) // 2
            spec_ok = bool(lvl) and raised == want
            log.append("earthquake_2 (id %d): cap %s; Specialization (specialization_3, id %d) at level %s -> cap %s (want %s)" % (
                quake, base, spec, lvl, raised, want))
            if not spec_ok:
                bad.append("Specialization %s: earthquake_2 cap %s -> %s, want %s" % (lvl, base, raised, want))
            _setskill(quake, 0)
            _setskill(spec, 0)
            _setskill(gate, 0)
            H("stat player %d %d set 0" % (pst4, gate))
        else:
            bad.append("no specialization_3 / earthquake_2 / skills_1835 row (%s %s %s)" % (spec, quake, gate))
    finally:
        H("stat player 12 set %s" % (lvl0 if lvl0 else 1))
    add(nm, "PASS" if sample and not bad else "FAIL",
        "%d skills raised to their cap with the game's point function: cap = Median's mlvl (work/formulas/skill_caps.txt, "
        "skills with no lock formula); +3 to a skill (Median stat 449 = D2R 478) raised each cap by 3; Specialization (barbarian) raised "
        "earthquake_2's cap by half its level%s" % (len(done), ("; WRONG: " + "; ".join(bad[:8])) if bad else ""), [], log)


def _skill_ids_by_name():
    t = _tsv(os.path.join(BUILT_EXCEL, "skills.txt"))
    h = t[0]
    return {r[0]: int(r[h.index("*Id")]) for r in t[1:] if r and r[0] and r[h.index("*Id")].isdigit()}, t, h


def check_townportal():
    """Bug #6: the itemless Town Portal skill (D2R's srvdofunc 109): casts in the field, opens a portal to the town and one
    back, with no scroll or book."""
    nm = "Town Portal skill (bug #6): itemless cast opens a portal to town and back"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, t, h = _skill_ids_by_name()
    tp = by_name.get("town_portal")
    do109 = [r[0] for r in t[1:] if r and r[h.index("srvdofunc")] == "109"]
    if tp is None:
        return add(nm, "BLOCKED", "no town_portal row in skills.txt (rows with srvdofunc 109: %s)" % do109)
    fight_ready()  # Blood Moor, nothing alive nearby
    for code in ("tbk", "tsc", "ibk", "isc"):
        H("remove %s 99" % code)
    st0 = hstate()
    area = st0["player"].get("area")
    if not items(st0, "tbk") and not items(st0, "tsc"):
        pass
    _, sl = H("skills")
    if not any(l.startswith("skill id=%d " % tp) for l in sl):
        _setskill(tp, 1)
    H("stat player 8 set %d" % (rd("player", 9) or 0))  # full mana
    before = {o["id"] for o in hstate()["objs"]}
    ok, cl = H("cast %d self" % tp)
    new, t0 = [], time.time()
    while time.time() - t0 < 8 and not new:
        time.sleep(1)
        new = new_portals(before)
    sh("townportal_field")
    acts = _level_acts()
    want_town = TOWNS[acts.get(area, 0)]
    field = [o for o in new if o.get("class") == 59]
    log = cl + ["field portals after the cast: %s" % [(o["id"], o.get("class"), o.get("dest")) for o in new]]
    ok_field = bool(field) and field[0].get("dest") == want_town
    arrived = back = False
    if ok_field:
        for _ in range(3):
            ok1, l1 = H("enter nearest")
            log += l1
            time.sleep(4)
            if hstate()["player"].get("area") == want_town:
                arrived = True
                break
        if arrived:
            sh("townportal_town")
            town_objs = [o for o in hstate()["objs"] if o.get("class") == 59]
            log.append("portals in town: %s" % [(o["id"], o.get("dest")) for o in town_objs])
            for _ in range(3):
                H("enter nearest")
                time.sleep(4)
                if hstate()["player"].get("area") == area:
                    back = True
                    break
    add(nm, "PASS" if ok_field and arrived and back else "FAIL",
        "skill %d (town_portal; skills with srvdofunc 109: %s), no scroll or book in the pack, cast at the player in area %s: "
        "new blue portal %s (want dest = town %d); entering it -> %s; the town portal back -> %s" % (
            tp, do109, area, [(o.get("class"), o.get("dest")) for o in new], want_town,
            "arrived in town" if arrived else "not in town", "back in area %s" % area if back else "did not return"),
        [sh("townportal")], log)
    goto(2)


def _portal_ids():
    return {o["id"] for o in hstate()["objs"] if o.get("class") in (59, 60, 600)}


def check_funcslots():
    """Bug #31: Median rows on 1.13c's srvdofunc 109 (MonFrenzy, flash, feral_strike, bloodlord1_skill) ran D2R's itemless Town
    Portal (docs/function-slots.md); txt_migrate remaps them to D2R's own frenzy functions (srvdofunc 9, srvstfunc 67). The
    player casts feral_strike and flash at a monster, monsters cast MonFrenzy, flash and bloodlord1_skill (`mcast`, mode as
    monstats Sk<n>mode). PASS: no portal object ever appears (`h state`), the cast starts, and it does something (the target
    loses life, a missile is seen, or the monster changes mode); the game keeps running."""
    nm = "Function slots (bug #31): feral_strike, flash, MonFrenzy, bloodlord1_skill do not open a town portal"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, t, h = _skill_ids_by_name()
    row = {r[0]: r for r in t[1:] if r}
    sid = {n: by_name.get(n) for n in ("feral_strike", "flash", "MonFrenzy", "bloodlord1_skill", "town_portal")}
    if None in sid.values():
        return add(nm, "BLOCKED", "skills missing from the built skills.txt: %s" % [n for n, v in sid.items() if v is None])
    fn = {n: (row[n][h.index("srvstfunc")], row[n][h.index("srvdofunc")]) for n in sid}
    bad_data = [n for n in sid if n != "town_portal" and fn[n][1] == "109"]
    fight_ready()
    god(True)
    base_portals = _portal_ids()
    notes, log, problems, shots = [], [], [], []
    if bad_data:
        problems.append("built skills.txt still has srvdofunc 109 on %s" % bad_data)
    # feral_strike needs an axe or a sword in hand (skills.txt itypea1 axe, itypea2 swor): without one the game answers usable 2 and
    # the cast does nothing, whatever the character wields (the test character's hands hold what the earlier checks left there)
    H("packclear")
    for slot_ in ("rhand", "lhand"):
        H("unequip " + slot_)
    wield = ""
    for code in ("115", "bsd"):
        ok_w, lw = H("equip %s q=2 rhand" % code)
        if ok_w:
            wield = code
            break
        H("unequip rhand")
    notes.append("weapon in hand for feral_strike: %s" % (wield or "none could be equipped (%s)" % " | ".join(lw)[-80:]))
    # the player casts (setskill gives the skill; a monster skill has no class, the game does not check it)
    for name in ("feral_strike", "flash"):
        skill = sid[name]
        kill_all_near()
        tid = tough_target(18)  # the target; its life is what "dropped" reads (the town NPC next to the arrival point is a monster too)
        # frozen (state 1): feral_strike is melee and the harness cast does not walk, so a target that wanders off between the
        # cast and the hit frame is never touched (seen: dist 2 -> 8 within a second, life unchanged over 3 casts)
        if tid is not None:
            H("setstate mon:%d 1 1" % tid)
        H("moveto nearest")
        H("setskill %d 5" % skill)
        H("missiles reset")
        life0 = next((m["life"] for m in hstate()["mons"] if m.get("id") == tid and m.get("life")), None)
        ok, cl, seen, dropped, mode_seen = False, [], 0, False, False
        for _ in range(5):
            H("moveto nearest")
            time.sleep(0.3)
            H("stat player 8 set %d" % (rd("player", 9) or 0))
            ok, cl = H("cast %d nearest" % skill)
            log += cl[:2]
            t0 = time.time()
            while time.time() - t0 < 1.8:
                time.sleep(0.4)
                st = hstate()
                m = [re.search(r"seen=(\d+)", ln) for ln in H("missiles")[1] if ln.startswith("missiles ")]
                seen = max(seen, int(m[0].group(1)) if m and m[0] else 0)
                mode_seen = mode_seen or st["player"].get("mode") in (7, 8, 10)
                dropped = dropped or any(x.get("id") == tid and x.get("life") is not None and life0 is not None and x["life"] < life0
                                         for x in st["mons"])
            if ok and (seen or dropped):
                break
        portals = _portal_ids() - base_portals
        did = seen > 0 or dropped or mode_seen
        notes.append("%s (srvstfunc %s, srvdofunc %s): cast %s, missiles seen %d, target life dropped %s, attack mode %s, new portals %s" % (
            name, fn[name][0], fn[name][1], "OK" if ok else "FAIL", seen, dropped, mode_seen, sorted(portals)))
        shots.append(sh("funcslots_%s" % name))
        if portals:
            problems.append("%s opened a portal object %s" % (name, sorted(portals)))
        if not (ok and did):
            problems.append("%s: cast %s, no attack or missile seen" % (name, "OK" if ok else "refused"))
        kill_all_near()
    # monsters cast through the AI's skill use
    for cls, name, mode in ((127, "MonFrenzy", 7), (506, "bloodlord1_skill", 7), (1250, "flash", 10)):
        clear_mons()
        mid = spawn_id(cls)
        if mid is None:
            notes.append("%s: monster class %d could not be spawned (skipped)" % (name, cls))
            continue
        time.sleep(2)
        ok, lines = H("mcast %d %d unit %d" % (sid[name], mode, mid))
        text = " ".join(lines)
        log += lines[:1]
        m = re.search(r"unit mode (\d+) -> (\d+)", text)
        time.sleep(1.2)
        modes = [x.get("mode") for x in hstate()["mons"] if x.get("id") == mid]
        portals = _portal_ids() - base_portals
        notes.append("%s on class %d: mcast %s (%s), monster mode after %s, new portals %s" % (
            name, cls, "OK" if ok else "FAIL", m.group(0) if m else text[:80], modes, sorted(portals)))
        shots.append(sh("funcslots_mon_%s" % name))
        if portals:
            problems.append("monster %s opened a portal object %s" % (name, sorted(portals)))
        if not ok:
            problems.append("monster %s: mcast refused (%s)" % (name, text[:100]))
        H("kill %d" % mid)
    alive = hstate()["ok"]
    god(False)
    kill_all_near()
    if not alive:
        problems.append("the game is gone")
    add(nm, "PASS" if not problems else "FAIL", ("%s | " % "; ".join(problems) if problems else "") + " | ".join(notes), shots, log)


def check_potions():
    """Bug #10: Median's healing / mana / rejuvenation potions (item spell 22 -> D2R's timed potion). Two results: the life
    part (hp1, hp5, rvs, rvl: stat hpregen 74, life rises over a control wait) and the mana part (mp1, mp5: manarecoverybonus
    27 set by the potion, mana rises over a control wait)."""
    n1 = "Potions (bug #10): healing and rejuvenation potions restore life over time"
    n2 = "Potions (bug #10): mana potions raise the mana recovery (stat 27) and restore mana over time"
    if not need_game():
        add(n1, "BLOCKED", "not in a game")
        return add(n2, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    H("difficulty 0")
    # (code, heals, mana, stat 27 right after the use): Median's calc1 / calc2 are 100 / 200 per cent (rejuvenation 125 / 200); D2R's
    # timed potion stores calc / len, which ended mp1 / mp5 at 0 / 1 until txt_migrate multiplied the calc by len
    cases = [("hp1", True, False, None), ("hp5", True, False, None), ("rvs", True, False, 125), ("rvl", True, False, 200),
             ("mp1", False, True, 100), ("mp5", False, True, 200)]
    rows = {True: [], False: []}
    bad = {True: [], False: []}
    log = []
    maxhp, maxmp = rd("player", 7), rd("player", 9)

    def drain():
        # the previous potion's state (len 175 frames = 7 s) must be over: a second potion within it averages the stat
        for _ in range(40):
            if not rd("player", 27) and not rd("player", 74):
                break
            time.sleep(0.5)
        setstat("player", 6, maxhp // 5)
        setstat("player", 8, maxmp // 5)
        time.sleep(0.5)

    def gain(code, seconds=4):
        """Life and mana gain (raw 1/256) over `seconds` seconds after `use <code>` (code None: a control wait), with the
        regeneration stats read right after the use."""
        drain()
        l0, m0, h0, r0 = rd("player", 6), rd("player", 8), rd("player", 74), rd("player", 27)
        line = ""
        if code:
            ok, line, _ = hv("use %s" % code, "use")
            if not ok:
                return None
        if code:
            time.sleep(0.75)  # the potion's stat list can land a server frame after `use` returns (mp1 once read 0 right away)
        h1, r1 = rd("player", 74), rd("player", 27)
        time.sleep(seconds)
        return rd("player", 6) - l0, rd("player", 8) - m0, h0, h1, r0, r1, line

    control = gain(None)
    for code, heals, mana, want27 in cases:
        key = heals
        H("remove %s 9" % code)
        ok, line, _ = hv("item %s" % code, "item")
        r = gain(code) if ok else None
        left = len([i for i in hstate()["items"] if str(i.get("code")) == code])
        if r is None:
            rows[key].append("%s: WRONG (no item / use failed: %s)" % (code, line[:60]))
            bad[key].append(code)
            continue
        pl, pm, h0, h1, r0, r1, uline = r
        log += [line, uline, "%s: hpregen %s -> %s, manarecoverybonus %s -> %s; gain with potion life %d mana %d, control life %d mana %d" % (
            code, h0, h1, r0, r1, pl, pm, control[0], control[1])]
        good = left == 0
        if heals and (h1 is None or h1 <= (h0 or 0) or pl <= control[0] + 256 * 5):
            good = False
        if mana and (r1 is None or r1 <= (r0 or 0) or pm <= control[1] + 256 * 2):
            good = False
        if want27 is not None and (r1 or 0) - (r0 or 0) != want27:
            good = False
            rows[key].append("%s: manarecoverybonus rose by %s, wanted %d" % (code, (r1 or 0) - (r0 or 0), want27))
        rows[key].append("%s: %s (life +%d vs control +%d, mana +%d vs +%d, hpregen %s->%s, manarecoverybonus %s->%s)" % (
            code, "ok" if good else "WRONG", pl >> 8, control[0] >> 8, pm >> 8, control[1] >> 8, h0, h1, r0, r1))
        if not good:
            bad[key].append(code)
        H("remove %s 9" % code)
    setstat("player", 6, maxhp)
    setstat("player", 8, maxmp)
    shot = sh("potions")
    add(n1, "PASS" if not bad[True] else "FAIL",
        "`use` consumed each potion; in the 4 s after it hpregen (stat 74) rose and life rose above a control wait: " + "; ".join(rows[True]),
        [shot], log)
    add(n2, "PASS" if not bad[False] else "FAIL",
        "`use` consumed each potion; the potion sets manarecoverybonus (stat 27) to calc1 = 100 (mp1) / 200 (mp5) per cent and mana "
        "rises above a control wait: " + "; ".join(rows[False]), [shot], log)


def check_deathcrash():
    """Bug #12: the client formatted 'was slain by' with a missing %s argument and crashed. The test character is killed by a
    monster's hit; the game process must survive and the character must be able to respawn and travel."""
    nm = "Player death (bug #12): killed by a monster, the game survives, respawn works"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    # Outside the town and alive: a player in a town cannot be hurt (the hit is ignored, result 0) and a dead one cannot die again.
    # The check before this one (nocorpse) ends with a respawn, in the town.
    revive_if_dead()
    fight_ready()
    pids = sorted(g.game_pids())
    atk = spawn_attacker(1)
    if atk is None:
        return add(nm, "BLOCKED", "no attacker monster")
    setstat("player", 7, BIG_LIFE)
    setstat("player", 6, 256 * 100)
    for _ in range(5):  # the hit's own line (life, result) is read before the engine applies it; the player's mode tells whether it landed
        ok, line, lines = hv("hit player phys 2000000000 %s" % atk, "hit")
        time.sleep(1.5)
        if player_dead(hstate()["player"]):
            break
        setstat("player", 6, 256 * 100)  # ignored (the character had just arrived in the area): hit again
    time.sleep(3)
    p = hstate()["player"]
    shot_dead = sh("death")
    dead = p.get("mode") in (0, 17) or str(p.get("life", "1")).split("/")[0] == "0"
    alive_pids = sorted(g.game_pids())
    time.sleep(4)
    survived = sorted(g.game_pids()) == pids and hstate()["ok"]
    revived = revive_if_dead()
    st = hstate()
    again = st["player"].get("area") is not None and not (st["player"].get("mode") in (0, 17))
    moved = goto(2)["player"].get("area") == 2
    add(nm, "PASS" if dead and survived and again and moved else "FAIL",
        "hit amount 2e9 from a spawned monster: %s; player dead (mode %s) %s; game process %s; respawned %s, alive again %s, travel to "
        "Blood Moor %s" % (line[:90], p.get("mode"), dead, "survived" if survived else "GONE", revived, again, moved),
        [shot_dead], lines)
    setstat("player", 6, rd("player", 7) or BIG_LIFE)


def check_itemskills():
    """Bug #16: skill / monster parameters of item properties. Table audit (every parameter of Median's property tables by skill
    name, tools/item_skill_audit.py) plus in-game: unique items with each kind of skill property carry the right skill."""
    n1 = "Item property skill parameters (bug #16): all tables, by skill name"
    n2 = "Item property skill parameters (bug #16): uniques in game carry the named skill"
    import item_skill_audit as audit
    checked, bad, samples = audit.audit()
    # The pass criterion is the mismatches. The audit matches rows by their name cell with the `medianxl:` prefix stripped
    # (strings_ns.bare); a prefix it fails to strip would leave rows unmatched and shrink the count (3844 instead of ~6000)
    # without a mismatch, so the table coverage is the sanity check: every table whose Median rows carry a skill / monster
    # parameter must have contributed some (the count itself depends on the data and is not a criterion).
    tables = {t for t, _ in checked}
    present = sorted(audit.audit.wanted)
    silent = [t for t in present if t not in tables]
    add(n1, "PASS" if not bad and checked and not silent else "FAIL",
        "%d skill / monster parameters in %d of %d Median property tables compared with the skill's name (named/skills.txt, built "
        "skills.txt, rows matched by bare name cell); mismatches %d%s%s" % (sum(checked.values()), len(tables), len(present), len(bad),
                                                                          (": " + "; ".join(str(b) for b in bad[:4])) if bad else "",
                                                                          ("; tables with no parameter compared: %s" % ", ".join(silent)) if silent else ""))
    if not need_game():
        return add(n2, "BLOCKED", "not in a game")
    goto(1)
    ut = _tsv(os.path.join(BUILT_EXCEL, "uniqueitems.txt"))
    it = _tsv(os.path.join(BUILT_EXCEL, "itemstatcost.txt"))
    stat_id = {r[0]: int(r[it[0].index("*ID")]) for r in it[1:] if r and r[0] and r[it[0].index("*ID")].isdigit()}
    encode = {r[0]: r[it[0].index("Encode")] for r in it[1:] if r and r[0]}
    rows, bad2, log = [], [], []
    for code, picks in sorted(samples.items()):
        pick = next((p for p in picks if p[0] == "uniqueitems"), None)
        if pick is None:
            continue
        _table, index, uname, skill, skill_name, stat = pick
        base = ut[index + 1][ut[0].index("code")]
        if stat not in stat_id:
            continue
        H("cubeclear")
        ok, line, _ = hv("item %s uniq=%d" % (base, index), "item")
        m = re.search(r"item id=(\d+)", line)
        if not ok or not m:
            log.append("%s: item %s uniq=%d failed: %s" % (uname, base, index, line[:80]))
            rows.append("%s: no item" % uname)
            continue
        ok, lines = H("stat %s %d scan" % (m.group(1), stat_id[stat]), 60)
        layers = [(int(a), int(b)) for a, b in re.findall(r"scan \S+ \d+:(\d+) = (-?\d+)", " ".join(lines)) if int(b) != 0]
        # the layer is the skill (aura, oskill, ...) or skill << 6 | level (encode 2 / 3: skill on an event, charges)
        want_layer = lambda l: (l >> 6) == skill if encode.get(stat) in ("2", "3") else l == skill  # noqa: E731
        good = any(want_layer(l) for l, _v in layers)
        log.append("%s (uniq %d, prop %s, stat %s=%d, encode %s): skill %s = %d; layers %s" % (
            uname, index, code, stat, stat_id[stat], encode.get(stat), skill_name, skill, layers[:6]))
        rows.append("%s %s -> %s %s" % (uname, code, skill_name, "ok" if good else "WRONG %s" % layers[:3]))
        if not good:
            bad2.append(uname)
        H("remove %s 9" % base)
    add(n2, "PASS" if rows and not bad2 and len(rows) >= 8 else "FAIL",
        "%d unique items, one per skill property kind, created with `item <base> uniq=<row>`; `stat <item> <stat> scan` found the "
        "skill the name oracle expects: %s" % (len(rows), "; ".join(rows)), [], log)

def check_nslong():
    name = "Short aliases of the long Median keys (docs/strings-namespace.md): service text and displayed names"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    import json
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    aliases = json.load(open(os.path.join(root, "work", "mod", "strings_alias.json"), encoding="utf-8"))["aliases"]
    recs = {e["Key"]: e["enUS"] for e in json.load(open(os.path.join(
        root, "work", "mod", "data", "local", "lng", "strings", "medianxl", "median.json"), encoding="utf-8-sig"))}
    log, bad = [], []
    for k in ("Sunstone of the Twin Seas", "MRVasily's Falling Star", "To The Island of the Sunless Sea"):
        full = "medianxl:" + aliases[k]
        ok, lines = H("str key " + full)  # the harness splits a line at spaces: the long keys themselves cannot be asked
        # colour codes (ÿc + 1 character) are dropped on both sides, as check_strings does. The console shows the two
        # characters ÿc as two garbage characters and keeps the colour digit ("<2 junk>0Difficulty: <2 junk>2Very Easy"):
        # junk plus the character behind it is dropped from the answer.
        first = [w for w in recs[aliases[k]].split(chr(10)) if w][0]
        want = _COLOUR.sub("", first)
        want_console = first.replace(chr(255) + "c", "")
        got = " ".join(lines)
        got_plain = re.sub("[^\x00-\x7f]+.", "", _COLOUR.sub("", got))
        log.append("%s -> %s %s (record starts '%s')" % (full, ok, lines[0] if lines else "", want))
        if not (ok and (want in got_plain or want_console in got)):
            bad.append("alias %s does not give the record text '%s'" % (full, want))
    goto(1)
    close_menu()
    # ground labels (Alt held through the plugin's virtual modifier block) show the displayed names:
    # unique "Sunstone of the Twin Seas" (uniqueitems data row 9, code twi), set item "MRVasily's Falling Star" (setitems row 141)
    for cmd in ("item twi q=7 uniq=9 ground", "item 89@ q=5 uniq=141 ground", "item twi q=7 uniq=9 inv"):
        ok, lines = H(cmd)
        log.append("%s: %s" % (cmd, lines[0] if lines else ""))
    time.sleep(1.0)
    shots = []
    g._set_mods(("alt",))
    hwnd = g.need_window()
    g.user32.PostMessageW(hwnd, g.WM_SYSKEYDOWN, 0x12, g._lparam(0x12, 0, False))
    try:
        for i in range(3):
            time.sleep(1.5)
            shots.append(sh("nslong_labels%d" % i))
    finally:
        g.user32.PostMessageW(hwnd, g.WM_SYSKEYUP, 0x12, g._lparam(0x12, 0, True))
        g._set_mods(())
    add(name, "FAIL" if bad else "REVIEW", "service answers: %s; ground labels with Alt held (read the screenshots: the label is the displayed name)" % (
        "; ".join(bad) or "alias texts match the records"), shots, log)


def check_orbtips():
    """Mystic orb tooltips (audit T12): every orb's misc spelldescstr is its own string `mxlorb_<row>` (tools/orb_tips.py:
    limit per item, required level, properties, target type) instead of the shared "Right-Click to Apply"."""
    name = "Mystic orb tooltips: per-orb description (limit, level, properties, target type), hovered in the inventory"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    import csv
    import json
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(root, "work", "mod", "data", "global", "excel", "base", "misc.txt"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    col = {h: i for i, h in enumerate(rows[0])}
    orbs = [(r[col["code"]], r[col["spelldescstr"]].split(":", 1)[-1]) for r in rows[1:]
            if r[col["spelldescstr"]].split(":", 1)[-1].startswith("mxlorb_")]
    recs = {e["Key"]: e["enUS"] for e in json.load(open(os.path.join(
        root, "work", "mod", "data", "global", "..", "local", "lng", "strings", "medianxl", "median.json"), encoding="utf-8-sig"))}
    log, bad = [], []
    texts = [recs.get(key, "") for _c, key in orbs]
    if len(orbs) < 100 or len(set(texts)) < 90 or any("Right-Click" == t.strip() for t in texts):
        bad.append("%d orbs, %d distinct texts" % (len(orbs), len(set(texts))))
    # a spread of orbs: the first line of each record is read back through the string service (the game's own lookup)
    pick = {}
    for (code, key), text in zip(orbs, texts):
        row = int(key.split("_")[1])
        for tag, test in (("weapon", "(Weapon Only)" in text), ("armor", "(Armor Only)" in text), ("any", "(Any Equippable Item)" in text),
                          ("chance", "Chance to cast" in text), ("resist", "Resist" in text), ("rare", "Rare items only" in text)):
            if test and tag not in pick:
                pick[tag] = (code, key, row, text)
    goto(1)
    close_menu()
    placed = []
    for tag, (code, key, row, text) in pick.items():
        first = [w for w in text.split("\n") if w][0]
        ok, lines = H("str key medianxl:" + key)
        got = " ".join(lines)
        want = _COLOUR.sub("", first)
        want_console = first.replace(chr(255) + "c", "")
        got_plain = re.sub("[^\x00-\x7f]+.", "", _COLOUR.sub("", got))
        log.append("%s %s (%s): string answer %s; record %r" % (tag, key, code, got[:100], text.replace("\n", " | ")[:160]))
        if not (ok and (want in got_plain or want_console in got)):
            bad.append("%s does not give the record text '%s'" % (key, want))
        H("remove %s 9" % code)
        ok, made = H("item %s inv" % code)
        m = re.search(r"item id=(\d+) .* x=(\d+) y=(\d+)", " ".join(made[:1])) if ok else None
        if m:
            placed.append((tag, key, int(m.group(2)), int(m.group(3)), int(m.group(1))))
        else:
            bad.append("orb %s (%s) could not be created: %s" % (code, key, made[:1]))
    def drawn_tip(where, key, iid):
        """What `tip <id>` reads for the orb (bug #38). Info only: the orb's spelldesc lines are drawn outside the property text
        the harness reads (0 lines for an orb, run checks-20261027-123822-s2), so the screenshots are the evidence."""
        ok, got = _tip_lines(iid)
        plain = " | ".join(_COLOUR.sub("", l) for l in got)
        log.append("%s %s tip readback (%d lines): %s" % (where, key, len(got), plain[:300]))
        return plain

    g.key("i")
    time.sleep(1.2)
    shots = [sh("orbtips_inventory")]
    inv_tips = []
    for tag, key, x, y, iid in placed:
        fx, fy = inv_cell(x, y)
        g.click(fx, fy, move_only=True)
        time.sleep(1.0)
        g.click(fx + 0.002, fy + 0.002, move_only=True)  # the tooltip wants a second mouse move over the item and a dwell
        time.sleep(2.0)
        shots.append(sh("orbtips_%s_%s" % (tag, key)))
        inv_tips.append(key)
        drawn_tip("inventory", key, iid)
    g.key("esc")
    for tag, (code, _k, _r, _t) in pick.items():
        H("remove %s 9" % code)
    # bug #38: the same tooltip on Gheed's shelf (Hell, level 90: every orb he stocks), hovered on the Misc tab
    key_of = dict(orbs)
    shop_tips = []
    mdiff = re.search(r"difficulty = (\d)", " ".join(H("difficulty")[1]))
    diff0, lvl0 = int(mdiff.group(1)) if mdiff else 0, hstate()["player"].get("level") or 1
    try:
        H("difficulty 2")
        H("stat player 12 set 90")
        if npc_menu_near(147) is None:
            bad.append("Gheed: no menu")
        else:
            H("shop 147 restock")
            H("menu 1")
            time.sleep(2.5)
            _ok, lines = H("shop 147")
            stock = [kv(l) for l in lines if l.startswith("item ")]
            shelf = [s for s in stock if s.get("code", "").strip() in key_of and s.get("page") == "3"]
            g.click(*shop_tab(2))
            time.sleep(1.0)
            for s in shelf[:3]:
                code = s["code"].strip()
                fx, fy = shop_cell(int(s["x"]), int(s["y"]))
                g.click(fx, fy, move_only=True)
                time.sleep(1.0)
                g.click(fx + 0.002, fy + 0.002, move_only=True)
                time.sleep(2.0)
                shots.append(sh("orbtips_shop_%s" % key_of[code]))
                shop_tips.append(key_of[code])
                drawn_tip("shop", key_of[code], int(s["id"]))
            if not shelf:
                bad.append("Gheed's Misc tab holds no orb (%d stock items)" % len(stock))
            g.click(*TRADE_CLOSE)
            time.sleep(0.8)
    finally:
        close_menu()
        H("stat player 12 set %d" % lvl0)
        H("difficulty %d" % diff0)
    add(name, "FAIL" if bad else "REVIEW",
        "%d orbs with their own record (%d distinct texts); strings read back and orbs hovered in the inventory (%s) and on Gheed's shelf: "
        "hovered inventory [%s], shop [%s] (bug #38: the screenshots must show every line of the record, not only Right-Click to Apply); the screenshots show the tooltip (limit per item, required level, properties, target type); %s" % (
            len(orbs), len(set(texts)), ", ".join("%s=%s" % (t, k) for t, k, _x, _y, _i in placed), ", ".join(inv_tips), ", ".join(shop_tips),
            "; ".join(bad) or "no mismatch"), shots, log)


# ------------------------------------------------------------------ strings: what the player reads (lane ns-verify)
# docs/strings-namespace.md moves Median-only strings into the `medianxl` loader namespace and keeps D2R's own keys native.
# The proof that the switch changes nothing the player sees: a fixed sample of strings is read back through the plugin
# harness `text` verb (plugin/src/harness_cmds.cpp) and compared with Median's own text from its .tbl files
# (tools/tbl2json.py parse), the same text before and after the switch.
#   text id <n>                  the client's string lookup (what an NPC menu line shows: the u16 id a menu record holds)
#   text row <table> <row> <off> the u16 string reference at a byte offset of the compiled table row the game loaded
#                                (the display name of an item, unique, set, monster, level, skill, stat line), resolved
#                                by the same lookup. Offsets are the name columns of the compiled rows; ROW_FIELDS below
#                                holds them, a table that is not listed is calibrated from the sample (`text scan`).
#   text key <full key>          D2RLoader's localization service: `d2r:Key` (D2R's own) or `medianxl:Key` (namespaced)
# Every sample prints one `SAMPLE` line (category, label, PASS / FAIL, expected, got) into the log and strings.tsv.

STR_NS = "medianxl"
STR_BANK = int(os.environ.get("MXL_STRINGS_BANK", "3"))  # data table bank: 1 classic, 2 lod, 3 rotw
# table -> byte offset of the name reference in the compiled row (from the calibration run: MXL_STRINGS_CALIBRATE=1)
ROW_FIELDS = {"items": 0xfc, "uniqueitems": 0x22, "setitems": 0x24, "sets": 0x2, "monstats": 0x36, "superuniques": 0x2,
              "skilldesc": 0x8, "itemstatcost": 0x34}
LEVEL_CELLS = {"LevelName": 0xfd, "LevelWarp": 0x125}  # inline in the compiled Levels row (from `text scan levels`)
# Median-only keys that stay native (`d2r:<key>`, tools/strings_native.json): too long for a prefixed fixed-size cell. With the
# namespace on they are the ones that can show "Missing string". Each is read where it sits: uniqueitems / setitems index, levels.
STR_NATIVE = ["Armor of the Old Religion", "Body of the Forbidden One", "Claw of the Spirit Wolf", "DurandaltheBlazingSword",
              "Gift of the Spiritbeast", "MRAchilios' Sledgehammer", "MRHunter's Trackless Step", "MRImperius' Winged Feet",
              "MRVasily's Falling Star", "MRVasily's Shepherd Moon", "MRWarmage's Flameshroud", "MRWitchhunter's Crucifix",
              "MRZann Esu's Binding Circle", "Spirit Teacher's Headdress", "Staff of Herding Design", "Sunstone of the Twin Seas",
              "To The Dimensional Labyrinth 10", "To The Island of the Sunless Sea", "UpgradedBossSummonerRing"]
STR_NATIVE_WHERE = [("uniqueitems", "index"), ("setitems", "index"), ("levels", "LevelWarp"), ("levels", "LevelName")]
_COLOUR = re.compile("ÿc.")

# (category, table, column of the name key, keys). `items` rows are found by item code, `levels` by id, the rest by row index.
STR_ROWS = [
    ("item names", "items", {"misc": "namestr", "armor": "namestr", "weapons": "namestr"},
     [("misc", "cotw"), ("misc", "yq2"), ("misc", "cyc3"), ("misc", "en09"), ("armor", "w23"), ("armor", "704"),
      ("weapons", "4@A"), ("weapons", "123")]),
    ("uniques", "uniqueitems", "index", ["CycleOfGold", "Wolfpack", "Bonechewer", "Vilehand", "FrozenHeart", "ShardRefraction"]),
    ("sets", "setitems", "index", ["MRCelestia's Charge", "MRSerpent's Coil", "MRAvalanche", "M_WisdomEye3"]),
    ("sets", "sets", "name", ["MSPantheon", "Set_Lazbro"]),
    ("monsters", "monstats", "NameStr", ["ReanimatedWarrior", "BloodBengal", "SapphireLord", "Sewer Rat", "DiscipleofHatred", "WycBoss3"]),
    ("superuniques", "superuniques", "Name", ["Snotspill", "NewFleshdoom", "Maghda", "JurisKhan"]),
    ("levels", "levels", "LevelName", ["Caldeum", "Butcher's Lair", "Kingdom of Shadow", "The Void", "Dimensional Labyrinth 5", "Heroic Duncraig"]),
    ("skills", "skilldesc", "str name", ["MasteryNameMeditation", "SkillnameSnakeStance", "SkillnameBlight", "SkillnameDeathCoil",
                                         "SkillnameIceBoltNova", "SkillnameFortress"]),
    ("stat lines", "itemstatcost", "descstrpos", ["ModTotPhysDmg", "ModitemBlessed", "ModitemHealAttack", "ModItemNoUnsocket", "ModitemCorrupted"]),
]
# Rare item affixes: no data table of the SDK exposes them, so the loader's key lookup is the only path.
STR_KEYS = ["TerrQ", "Leviath", "halo", "spines"]
# D2R keys Median overrides: (key, whether `text key` can take it: no spaces) - resolved by D2R's own numeric id and by key.
STR_D2R = ["CfgRun", "Zakarumite", "Maggot Lair", "gcy", "r27", "Baal Subject 3", "StrSklTabItem1", "skillld49", "Skillld253", "CharsiGossip7"]
# Bug #7: the first-talk line of the town NPCs is the NPC's own, not another string's (Median's "ArcaneApe" shared Gheed's id)
STR_INTRO = ["GheedIntroGossip1", "AkaraIntroGossip1", "KashyaIntroGossip1", "CharsiIntroGossip1", "WarrivAct1IntroGossip1",
             "WarrivAct1IntroPalGossip1"]
# NPC menus (npc class, [(top-level plugin line key) ...], the native lines D2R itself shows)
STR_MENUS = [(265, "Deckard Cain", ["strCainMenuCraftMaterials"], ["TalkMenu", "NPCIdentify1"]),
             (148, "Akara", ["AkaraMenu1b"], ["TalkMenu"]),
             (175, "Warriv", [], ["TalkMenu"])]
STR_CAIN_SUB = ["strCainMenuCMHoradricCube", "strCainMenuCMCatalyst1", "strCainMenuCMCatalyst2", "strCainMenuCMCatalyst3"]


class _StrSrc:
    """Median's strings from the .tbl files and D2R's own string files: key -> expected text, D2R key -> numeric id."""

    def __init__(self):
        import json
        import glob
        import tbl2json as T
        by_id, winner = T.load_median()
        self.texts = {}
        for sid, (key, text) in by_id.items():
            fk = T.final_key(sid, key)
            if fk.startswith("mxl_") or winner[key] == sid:
                self.texts[fk] = text
        self.d2r = {}
        for p in glob.glob(str(T.D2R_LNG / "strings" / "*.json")):
            for e in json.load(open(p, encoding="utf-8-sig")):
                self.d2r[e["Key"]] = e
        # keys tbl2json leaves with D2R's text (placeholders differ): not Median's text, not part of the sample
        self.kept = {k for k, e in self.d2r.items() if k in self.texts and T.placeholders(self.texts[k]) != T.placeholders(e.get("enUS", ""))}
        ns = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "strings_namespace.json")
        self.ns_keys = set(json.load(open(ns, encoding="utf-8"))["keys"]) if os.path.exists(ns) else None

    def expected(self, key):
        t = self.texts.get(key)
        return None if t is None else _str_norm(t)

    def full_key(self, key):
        """`medianxl:Key` for a Median-only key once the namespace exists, else D2R's own `d2r:Key` (native loading)."""
        g2 = key not in self.d2r
        if self.ns_keys is not None:
            g2 = key in self.ns_keys
        return (STR_NS if g2 and self.ns_keys is not None else "d2r") + ":" + key


def _str_norm(text):
    """The verb's form of a string: colour codes removed, newlines written as the two characters \\n."""
    return _COLOUR.sub("", text).replace("\r", "").replace("\n", "\\n")


def _txt_rows(name, bank):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data", "global", "excel",
                        "" if bank == 3 else "base", name + ".txt")
    with open(path, encoding="utf-8-sig") as f:
        rows = [ln.rstrip("\n").split("\t") for ln in f]
    return rows[0], rows[1:]


def _cell_key(cell):
    """A localization cell is `Key`, `d2r:Key` or `medianxl:Key`: the plain key."""
    return cell.split(":", 1)[1] if cell.startswith((STR_NS + ":", "d2r:")) else cell


_HTXT = re.compile(r"(?:result=(\d+) )?len=(\d+) fnv=([0-9a-f]{8}) raw=([0-9a-f]*) = \[(.*)\]$")
_HSCAN = re.compile(r"\+0x([0-9a-f]+) id=(\d+) \[(.*)\]$")


def _fnv(text):
    h = 2166136261
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xffffffff
    return h


class _Got:
    """One `text` answer: the length and FNV-1a hash of the whole cleaned text (a speech does not fit one line) and its start."""

    def __init__(self, line):
        m = _HTXT.search(line)
        self.ok = m is not None
        self.result = int(m.group(1)) if m and m.group(1) else None
        self.n = int(m.group(2)) if m else -1
        self.fnv = int(m.group(3), 16) if m else -1
        self.raw = m.group(4) if m else ""
        self.text = m.group(5) if m else line

    def same(self, exp):
        return self.ok and exp is not None and self.n == len(exp.encode("utf-8")) and self.fnv == _fnv(exp)

    def sig(self):
        return (self.n, self.fnv)

    def show(self):
        return "%s%s" % (self.text, "..." if self.n > 200 else "")


def _text_id(sid):
    ok, lines = H("text id %d" % sid)
    return _Got(lines[0]) if ok and lines else None


def _text_key(full):
    """_Got of the loader's lookup (`result` set); a space in the key travels as ^ on the harness line."""
    ok, lines = H("text key " + full.replace(" ", "^"))
    return _Got(lines[0]) if lines else _Got("")


def _str_aliases():
    import json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "strings_alias.json")
    return json.load(open(p, encoding="utf-8"))["aliases"] if os.path.exists(p) else {}


def _row_ref(table, key, col, sub=None):
    """(row reference for the verb, plain keys of the row) of the first row of the built table whose cell is `key`."""
    name = sub or table
    head, rows = _txt_rows(name, STR_BANK)
    ci = head.index(col if isinstance(col, str) else col[name])
    alias = _str_aliases().get(key, key)  # a long key sits in its cell as its short alias (work/mod/strings_alias.json)
    for i, r in enumerate(rows):
        if ci < len(r) and _cell_key(r[ci]) in (key, alias):
            if table == "items":
                return "code:" + r[head.index("code")].ljust(4)[:4].replace(" ", ""), i
            return str(i), i
    return None, None


def check_strings():
    name = "Strings the player reads: items, monsters, levels, skills, NPC menus, stat lines, D2R overrides (namespace contract)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    src = _StrSrc()
    rows_out = []  # (category, label, status, expected, got, note)

    def record(cat, label, ok, expected, got, note=""):
        rows_out.append((cat, label, "PASS" if ok else "FAIL", expected, got, note))
        g.log("SAMPLE %s | %s | %s | expected [%s] got [%s] %s" % (cat, label, "PASS" if ok else "FAIL", expected, got, note))

    # ---- table rows: the display name field of the compiled row, resolved by the client's string lookup
    calibrate = {}
    pending = []  # (cat, table, label, key, ref, expected)
    cellof = {}  # label -> column, for levels
    for cat, table, col, keys in STR_ROWS:
        for item in keys:
            sub, key = item if table == "items" else (None, item)
            ref, _i = _row_ref(table, key, col, sub)
            exp = src.expected(key)
            if ref is None or exp is None:
                record(cat, "%s:%s" % (table, key), False, exp, None, "no row in the built table" if ref is None else "no text in Median's .tbl")
                continue
            pending.append((cat, table, "%s:%s %s" % (table, key, ref), key, ref, exp))
            cellof[pending[-1][2]] = col
    for key in STR_NATIVE:
        exp = src.expected(key)
        for table, col in STR_NATIVE_WHERE:
            ref, _i = _row_ref(table, key, col)
            if ref is not None:
                break
        if ref is None or exp is None:
            record("long keys", key, False, exp, None, "no row in the built table" if ref is None else "no text in Median's .tbl")
            continue
        pending.append(("long keys", table, "%s.%s:%s %s" % (table, col, key, ref), key, ref, exp))
        cellof[pending[-1][2]] = col
    for cat, table, label, key, ref, exp in pending:
        if table == "levels":
            continue
        if ROW_FIELDS.get(table) is None or os.environ.get("MXL_STRINGS_CALIBRATE"):
            hits = {}
            ok, lines = H("text scan %s %s %d" % (table, ref, STR_BANK))
            if not ok:
                g.log("CALIBRATE %s %s: %s" % (table, ref, lines[-1] if lines else "no answer"))
            want = exp.encode("utf-8")[:90].decode("utf-8", "ignore")  # the scan prints at most 90 bytes
            for ln in lines:
                m = _HSCAN.search(ln)
                if m and m.group(3) == want:
                    hits[int(m.group(1), 16)] = m.group(3)
            if not hits:
                for ln in lines:
                    g.log("SCAN %s %s %s" % (table, ref, ln[:160]))
            calibrate.setdefault(table, []).append(set(hits))
    for table, sets in calibrate.items():
        votes = {}
        for s in sets:
            for o in s:
                votes[o] = votes.get(o, 0) + 1
        best = max(votes, key=lambda o: (votes[o], -o)) if votes else None
        g.log("CALIBRATE %s: offset %s matches %d of %d sample rows (votes %s)" % (
            table, hex(best) if best is not None else None, votes.get(best, 0) if best is not None else 0, len(sets),
            {hex(o): n for o, n in sorted(votes.items())}))
        if best is not None and votes[best] * 2 > len(sets) and (ROW_FIELDS.get(table) is None):
            ROW_FIELDS[table] = best
    for cat, table, label, key, ref, exp in pending:
        if table == "levels":
            # Levels keeps LevelName as characters in the compiled row (the game resolves it by key when it draws the name):
            # the cell must name the string, and the loader must resolve that name to the expected text.
            ok, lines = H("text cstr levels %s %x %d" % (ref.split(":")[-1], LEVEL_CELLS[cellof[label]], STR_BANK))
            m = re.search(r"= \[(.*)\]$", lines[0]) if ok and lines else None
            cell = m.group(1) if m else None
            full = None if cell is None else (cell if ":" in cell else "d2r:" + cell)
            kg = _text_key(full) if full else None
            good = kg is not None and kg.result == 0 and kg.same(exp)
            record(cat, label, good, exp, kg.show() if kg else None,
                   "row cell [%s] -> %s (expected key %s)" % (cell, full, src.full_key(key)) + ("" if ok else "; " + (lines[-1] if lines else "no answer")))
            continue
        off = ROW_FIELDS.get(table)
        if off is None:
            record(cat, label, False, exp, None, "no field of the compiled row resolves to the expected text")
            continue
        ok, lines = H("text row %s %s %x %d" % (table, ref, off, STR_BANK))
        got = _Got(lines[0]) if ok and lines else None
        mid = re.search(r"id=(\d+) len", lines[0]) if ok and lines else None
        full = src.full_key(key)
        kg = _text_key(full)
        note = "row offset 0x%x id=%s; key %s -> %s" % (off, mid.group(1) if mid else "?", full, "n/a (space)" if kg is None else
                                                      ("ok" if kg.result == 0 and kg.same(exp) else "result %s [%s]" % (kg.result, kg.show())))
        if not ok:
            note += "; " + (lines[-1] if lines else "no answer")
        record(cat, label, got is not None and got.same(exp), exp, got.show() if got else None, note)

    # ---- rare affixes: the loader's key lookup only
    for key in STR_KEYS:
        full = src.full_key(key)
        kg = _text_key(full)
        exp = src.expected(key)
        record("rare affixes", full, kg is not None and kg.result == 0 and kg.same(exp), exp, kg.show() if kg else None,
               "result %s" % (kg.result if kg else None))

    # ---- the plugin's own string ids (`h mstr`): every menu text the plugin hands to D2R resolves and gets an id
    ok, lines = H("mstr " + src.full_key("AkaraMenu1b"))
    if ok or (lines and "unknown" not in lines[-1].lower()):
        for key in [k for _c, _n, ks, _l in STR_MENUS for k in ks] + STR_CAIN_SUB:
            full = src.full_key(key)
            ok, lines = H("mstr " + full)
            m = re.search(r'service=(\w+) text="(.*)" id=(\d+) \(0x[0-9a-f]+\) via D2R lookup="(.*)" ids=', lines[0]) if lines else None
            exp = src.expected(key)
            via = re.sub("[-].", "", m.group(4)) if m else None
            record("plugin string ids", full, bool(m) and m.group(1) == "ok" and int(m.group(3)) != 0 and via == exp, exp, via,
                   "service %s id %s" % (m.group(1), m.group(3)) if m else (lines[-1] if lines else "no answer"))

    # ---- native exceptions by key: the loader must know the key, native (`d2r:`) or in the namespace (an unqualified record of a
    # namespaced mod belongs to it); the row samples above are the proof of what the player sees
    for key in STR_NATIVE:
        exp = src.expected(key)
        tries = [_text_key(f + ":" + key) for f in ("d2r", STR_NS)]
        kg = next((t for t in tries if t is not None and t.result == 0 and t.same(exp)), tries[0])
        record("long keys (key)", key, kg is not None and kg.result == 0 and kg.same(exp), exp, kg.show() if kg else None,
               "d2r: result %s, %s: result %s" % (tries[0].result, STR_NS, tries[1].result))

    # ---- D2R keys Median overrides: D2R's numeric id (native, fixed) and the key
    for key in STR_D2R:
        e = src.d2r.get(key)
        exp = src.expected(key)
        if e is None or exp is None or key in src.kept:
            record("D2R overrides", key, False, exp, None, "not a D2R key Median overrides")
            continue
        got_id = _text_id(e["id"])
        kg = _text_key("d2r:" + key)
        ok = got_id is not None and got_id.same(exp) and (kg is None or (kg.result == 0 and kg.same(exp)))
        alt = ""
        if src.ns_keys is not None:  # a namespaced mod keeps an unqualified record in its own namespace: is Median's text there?
            ag = _text_key(STR_NS + ":" + key)
            alt = "; %s:%s -> %s" % (STR_NS, key, ag.show() if ag and ag.result == 0 else "absent")
        record("D2R overrides", "%s (id %d)" % (key, e["id"]), ok, exp, got_id.show() if got_id else None,
               "key d2r:%s -> %s%s" % (key, kg.show() if kg else None, alt))

    # ---- bug #7: the first-talk line of each town NPC is its own string, by D2R's numeric id
    other = {}  # (length, hash) of every Median-only text -> key: a first-talk line that is one of them is the bug
    for k, t in src.texts.items():
        if k not in src.d2r:
            other[(len(_str_norm(t).encode("utf-8")), _fnv(_str_norm(t)))] = k
    for key in STR_INTRO:
        e = src.d2r.get(key)
        exp = src.expected(key)
        got = _text_id(e["id"]) if e else None
        stray = other.get(got.sig()) if got is not None and not got.same(exp) else None
        record("first talk (bug #7)", "%s (id %s)" % (key, e["id"] if e else "?"), got is not None and got.same(exp) and stray is None,
               exp[:60], got.show()[:60] if got else None, ("shows another Median string: %s" % stray) if stray else "")

    # ---- NPC menu lines: the strings the menu record points at, resolved by the client
    goto(1)
    close_menu()
    H("stat player 7 set 20000000")
    H("stat player 6 set 20000000")
    H("quest 1 0 set")   # Den of Evil done: Akara's respec line is open
    H("quest 41 1 set")
    H("quest 4 0 set")   # Search for Cain done: Cain's page has an open entry
    H("remove box 10")   # the cube entry shows only while the player lacks the cube
    for npc_class, who, plugin_keys, native_keys in STR_MENUS:
        menu = npc_menu(npc_class)
        if not menu:
            record("NPC menus", who, False, None, None, "the menu did not open")
            continue
        t0 = time.time()
        while time.time() - t0 < 120 and not any("handler=plugin" in x for x in menu):  # the plugin line is added when the speech ends
            time.sleep(1)
            ok0, again = g.hcmd("menu list", 5)
            menu = again if ok0 else menu
        lines = []
        for x in menu:
            m = re.search(r"line (\d+) string=0x([0-9a-f]+) handler=(\w+)", x)
            if m:
                lines.append((int(m.group(1)), int(m.group(2), 16), m.group(3) == "plugin"))
        plug = [ln for ln in lines if ln[2]]
        nat = [ln for ln in lines if not ln[2]]
        for (idx, sid, _p), pk in zip(plug, plugin_keys + [None] * len(plug)):
            exp = src.expected(pk) if pk else None
            got = _text_id(sid)
            record("NPC menus", "%s line %d (%s)" % (who, idx, pk), pk is not None and got is not None and got.same(exp), exp,
                   got.show() if got else None, "string id 0x%x" % sid)
        if len(plug) < len(plugin_keys):
            record("NPC menus", "%s plugin lines" % who, False, plugin_keys, [ln[1] for ln in plug], "fewer plugin lines than expected")
        for (idx, sid, _p), nk in zip(nat, native_keys):
            exp = src.expected(nk)
            if exp is None:
                exp = _str_norm(src.d2r[nk].get("enUS", ""))
            got = _text_id(sid)
            record("NPC menus", "%s line %d (%s)" % (who, idx, nk), got is not None and got.same(exp), exp,
                   got.show() if got else None, "string id 0x%x" % sid)
        if npc_class == 265 and plug:  # Cain's submenu: the click rebuilds the list with the open crafting materials
            before = menu
            ok, _l = H("menu %d" % plug[0][0])
            time.sleep(2.5)
            ok2, after = g.hcmd("menu list", 5)
            sub = []
            for x in (after or []):
                m = re.search(r"line (\d+) string=0x([0-9a-f]+)", x)
                if m:
                    sub.append((int(m.group(1)), int(m.group(2), 16)))
            allowed = {(len(src.expected(k).encode("utf-8")), _fnv(src.expected(k))): k for k in STR_CAIN_SUB}
            if not (ok and ok2 and sub and after != before):
                record("NPC menus", "Cain submenu", False, sorted(allowed.values()), None, "the click did not open a submenu: %s" % (after,))
            for idx, sid in sub:
                got = _text_id(sid)
                record("NPC menus", "Cain submenu line %d" % idx, got is not None and got.sig() in allowed, sorted(allowed.values()),
                       got.show() if got else None, "string id 0x%x" % sid)
        close_menu()

    # ---- report
    p = os.path.join(g.current_run(), "strings.tsv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("category\tsample\tresult\texpected\tgot\tnote\n")
        for r in rows_out:
            f.write("\t".join(str(x).replace("\t", " ").replace("\n", "\\n") for x in r) + "\n")
    cats = []
    for r in rows_out:
        if r[0] not in cats:
            cats.append(r[0])
    bad = [r for r in rows_out if r[2] == "FAIL"]
    for c in cats:
        mine = [r for r in rows_out if r[0] == c]
        fails = [r for r in mine if r[2] == "FAIL"]
        add("Strings: " + c, "PASS" if not fails else "FAIL",
            "%d of %d samples read back as Median's text%s" % (len(mine) - len(fails), len(mine),
                                                              "; FAIL: " + "; ".join("%s got [%s]" % (r[1], str(r[4])[:50]) for r in fails[:6]) if fails else ""),
            log=["%s | %s | expected [%s] got [%s] %s" % (r[2], r[1], r[3], r[4], r[5]) for r in mine])
    add(name, "PASS" if rows_out and not bad else "FAIL",
        "%d samples, %d FAIL; namespace file %s; offsets %s; full list in %s" % (
            len(rows_out), len(bad), "present" if src.ns_keys is not None else "absent (native strings)",
            {k: hex(v) for k, v in ROW_FIELDS.items()}, os.path.basename(p)))



def check_goblinname():
    name = "Goblin notice names the variant (monstats NameStr, not the generic goblin)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    want = {2791: "Treasure Goblin", 2792: "Shiny Hoarder", 2793: "Voided Horror", 2799: "Relic Thief", 2802: "Rift Inspector"}
    got, bad = [], []
    for cls, text in want.items():
        ok, first, lines = hv("goblinsay %d" % cls)
        got.append("%d: %s" % (cls, first))
        if not ok or (text + " appears!") not in first:
            bad.append("class %d wanted '%s appears!', got %s" % (cls, text, lines[:2]))
    add(name, "PASS" if not bad else "FAIL",
        "`h goblinsay <class>` (the line a spawn sends): %s" % "; ".join(got) if not bad else "; ".join(bad), [], got)

def reward_stats():
    """`h rewardsnd` (client side): (hook on, sounds played, last message, last sound row)."""
    ok, first, _l = hv("rewardsnd")
    m = re.search(r"hook=(\d) played=(\d+) last message=0x([0-9a-f]+) sound=(\d+)", first)
    return (int(m.group(1)) == 1, int(m.group(2)), int(m.group(3), 16), int(m.group(4))) if m else None

def check_rewardsound():
    name = "Quest reward messages 0x5f-0x61: the client plays Median's sound (item_gem / shrine stand-in / item_lightarmor)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    s0 = reward_stats()
    if s0 is None or not s0[0]:
        return add(name, "FAIL", "client hook for packet 0x2c is off: %s" % (s0,))
    rows, bad = [], []
    played = s0[1]
    for msg, sound in ((0x5f, 217), (0x60, 2608), (0x61, 230)):
        ok, first, _l = hv("rewardmsg 0x%x" % msg)
        s1 = None
        for _ in range(12):  # the pending message goes out at the unit's next update
            time.sleep(0.5)
            s1 = reward_stats()
            if s1 and s1[1] > played:
                break
        rows.append("0x%x -> %s" % (msg, s1))
        if not ok or not s1 or s1[1] != played + 1 or s1[2] != msg or s1[3] != sound:
            bad.append("message 0x%x wanted sound %d with one more sound than %d, got %s (%s)" % (msg, sound, played, s1, first))
        elif s1:
            played = s1[1]
    add(name, "PASS" if not bad else "FAIL",
        "`h rewardmsg` through D2R's unit message, `h rewardsnd` on the client (hook, played, last message, sound row): %s"
        % ("; ".join(rows) if not bad else "; ".join(bad)), [], rows)

def _statorder():
    """`statorder` -> (ordered, rebuilds, rows) with rows a list of ("L", label) / ("S", D2R stat id)."""
    ok, lines = H("statorder")
    head = next((l for l in lines if l.startswith("statorder ordered=")), "")
    m = re.search(r"ordered=(\d) rebuilds=(\d+) rows=(\d+)", head)
    if not ok or not m:
        return None
    rows = []
    for l in lines:
        if l.startswith("statorder rows "):
            rows += [("L", a) if a else ("S", int(b)) for a, b in re.findall(r"\[([^\]]+)\]|(-?\d+)", l[len("statorder rows "):])]
    return int(m.group(1)) == 1, int(m.group(2)), rows

def check_statorder():
    name = "Stat pages: the Advanced Stats list in Median's order, under its section labels (stat_columns.cpp, mxl_statorder.h)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    import stat_screen
    goto(1)
    close_menu()
    ids = stat_screen.stat_ids()
    names = stat_screen.stat_names()
    expected = [("L", h) if h is not None else ("S", ids[s]) for h, s in stat_screen.section_order()]
    always = {ids[names.index(n)] for n in stat_screen.ALWAYS_LISTED}
    probe = 143  # item_absorbfire: under "Damage Absorb", listed while it is not 0
    bad, shots = [], []
    try:
        H("statorder close")
        time.sleep(1)
        rc = H("statorder open")
        time.sleep(2)
        rc = (rc[0], rc[1] + H("statorder adv")[1])
        time.sleep(3)
        first = _statorder()
        if first is None:
            return add(name, "FAIL", "`statorder` gave no answer")
        ordered, rebuilds, rows = first
        shots.append(sh("statorder_open"))
        if not ordered:
            bad.append("the rebuild hook is off (D2R's order)")
        if rebuilds < 1:
            bad.append("the panel built no list (open: %s)" % (rc[1][:3],))
        # the built list is a subsequence of Median's order: labels in sheet order, stats under their own label
        it = iter(expected)
        if not all(any(x == e for e in it) for x in rows):
            bad.append("rows are not in Median's order: %s" % (rows[:12],))
        labels = [r[1] for r in rows if r[0] == "L"]
        if not labels or labels[0] != "General":
            bad.append("the list does not start with the General label: %s" % (labels[:3],))
        missing = sorted(always - {r[1] for r in rows if r[0] == "S"})
        if missing:
            bad.append("always listed boxes missing: %s" % (missing,))
        if ("S", probe) in rows:
            bad.append("stat %d is listed at 0" % probe)
        # a stat that becomes non-zero makes the update rebuild the list: the stat appears, under Damage Absorb
        n0 = rebuilds
        ok_eq, l_eq = H("cstat %d set 25" % probe)  # the client's own copy: a stat set on the server's unit does not reach it
        time.sleep(3)
        cs = H("cstat %d" % probe)[1][:1]
        second = _statorder()
        if not ok_eq:
            bad.append("cstat %d set 25 failed: %s" % (probe, l_eq[:1]))
        elif second is None or ("S", probe) not in second[2]:
            bad.append("stat %d does not appear when the client copy has it (client reads %s)" % (probe, cs))
        else:
            if second[1] <= n0:
                bad.append("no rebuild after the stat changed (%d -> %d)" % (n0, second[1]))
            below = [r for r in second[2][:second[2].index(("S", probe))] if r[0] == "L"]
            if not below or below[-1][1] != "Damage Absorb":
                bad.append("stat %d is not under Damage Absorb (%s)" % (probe, below[-1:] if below else None))
            shots.append(sh("statorder_stat"))
        H("cstat %d set 0" % probe)
        time.sleep(3)
        third = _statorder()
        if third is None or ("S", probe) in third[2]:
            bad.append("stat %d stays listed after it went back to 0" % probe)
        add(name, "PASS" if not bad else "FAIL",
            "sheet opened with `statorder open`, Advanced Stats button pressed with `statorder adv`: %d rows, %d rebuilds, labels %s; "
            "%s. The grouping on the sheet is read from the screenshots (statorder_open.png, statorder_stat.png)" % (
                len(rows), rebuilds, labels, "; ".join(bad) if bad else "order = Median's, always boxes listed, a changed stat rebuilds the list"),
            shots, [str(r) for r in rows[:40]])
    finally:
        H("cstat %d set 0" % probe)
        H("statorder close")

def check_infopanel():
    name = "Infographic help panel: right click on the catalyst of disenchantment opens it (info_panels.cpp, plugin message 'I')"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    H("remove 3o[ 5")
    ok, made = H("item 3o[ inv")
    if not ok:
        return add(name, "BLOCKED", "could not create the catalyst (3o[): %s" % made)
    H("infopanel close 0")
    time.sleep(0.5)
    _, before = H("infopanel")
    ok, used = H("use 3o[")
    st, last, shots = None, "", []
    for _ in range(10):  # the open request crosses the hidden chat packet and the UI thread queue
        time.sleep(1)
        _, lines = H("infopanel")
        last = lines[0] if lines else ""
        m = re.search(r"state0=(-?\d+) .*opened=(\d+) failed=(\d+)", last)
        if m and int(m.group(1)) == 2:
            st = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            break
    time.sleep(1)
    shots.append(sh("infopanel_open"))
    _, closed = H("infopanel close 0")
    time.sleep(1)
    _, after = H("infopanel")
    state_after = re.search(r"state0=(-?\d+)", after[0] if after else "")
    _, held = H("state")
    kept = any("3o[" in ln for ln in held)
    H("remove 3o[ 5")
    good = ok and st is not None and st[1] >= 1 and st[2] == 0 and state_after and int(state_after.group(1)) == 1 and kept
    add(name, "PASS" if good else "FAIL",
        "`use 3o[`: %s; panel state after the right click %s (2 = open), `infopanel` before: %s, after close: %s; the catalyst is kept: %s. "
        "The text is read from the screenshot (infopanel_open.png)" % (used[0] if used else "-", last, before[0] if before else "-",
                                                                         after[0] if after else "-", kept), shots, made + used)



SPRINT_DIRS = [(0, 30), (30, 0), (0, -30), (-30, 0), (22, 22), (-22, -22), (22, -22), (-22, 22)]  # `move` offsets in `state` units; the Blood Moor start is cramped, so only short paths are accepted


STAMINA_POINT = 256  # stamina is stored <<8


def _charstats_row(cls):
    """Median's charstats row of the player class from the built tables (stamina, WalkVelocity, RunVelocity, RunDrain)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data", "global", "excel", "charstats.txt")
    with open(p, encoding="utf-8", errors="replace") as f:
        rows = [ln.rstrip("\n").split("\t") for ln in f]
    head = rows[0]
    row = rows[1 + cls]
    return {c: row[head.index(c)] for c in ("class", "stamina", "WalkVelocity", "RunVelocity", "RunDrain")}


def _sample():
    """(frame, x, y, mode, stamina raw) of one `state` reply, so the pairs of samples compare the stamina of known server frames."""
    p = hstate()["player"]
    return (p.get("frame", 0), p.get("x", 0), p.get("y", 0), p.get("mode", -1), p.get("stamina", 0))


def _sprint_leg(stam0, walk, max_s, stop_exhausted=False):
    """Stamina set to stam0, then `move` runs (or walks) along the first free direction of SPRINT_DIRS, re-issued when the
    path ends. Samples (frame, x, y, mode, stamina) until max_s seconds, or until a run has been forced back to walk."""
    setstat("player", 10, stam0)
    rows, di, ran, t0 = [], 0, False, time.time()
    while time.time() - t0 < max_s:
        row = _sample()
        rows.append(row)
        ran = ran or row[3] == 3
        if stop_exhausted and ran and row[3] == 2 and row[4] < STAMINA_POINT * 2:
            break
        if row[3] not in (2, 3):
            for k in range(len(SPRINT_DIRS)):
                dx, dy = SPRINT_DIRS[(di + k) % len(SPRINT_DIRS)]
                H("move %d %d%s" % (row[1] + dx, row[2] + dy, " walk" if walk else ""))
                if _sample()[3] in (2, 3):
                    di = (di + k) % len(SPRINT_DIRS)
                    break
            else:
                di += 1
    return rows


def _pairs(rows, mode):
    """Consecutive samples that are both in `mode` (a number, or a tuple of modes that count as one: 1 and 5 are both standing)."""
    modes = mode if isinstance(mode, tuple) else (mode,)
    return [(a, b) for a, b in zip(rows, rows[1:]) if a[3] in modes and b[3] in modes and b[0] > a[0]]


def _speed(rows, mode):
    """Units per frame in this mode; (speed, frames in the mode). The positions are whole units and the samples a few frames apart, so
    a single pair is off by a quarter: the speed is the distance between the ends of an unbroken stretch of samples in the mode (at
    least 12 frames), and the fastest stretch counts (one that turns a corner or is held up by an obstacle reads low)."""
    frames = sum(b[0] - a[0] for a, b in _pairs(rows, mode))
    stretches, cur = [], []
    for r in rows:
        if r[3] == mode and (not cur or r[0] > cur[-1][0]):
            cur.append(r)
            continue
        stretches.append(cur)
        cur = [r] if r[3] == mode else []
    stretches.append(cur)
    per = [((s[-1][1] - s[0][1]) ** 2 + (s[-1][2] - s[0][2]) ** 2) ** 0.5 / (s[-1][0] - s[0][0]) for s in stretches
           if len(s) > 1 and s[-1][0] - s[0][0] >= 12]
    return (max(per) if per else 0.0), frames


def _drain(rows):
    """Median stamina lost per frame (raw, <<8) over consecutive run samples."""
    per = sorted((a[4] - b[4]) / (b[0] - a[0]) for a, b in _pairs(rows, 3))
    return per[len(per) // 2] if per else 0.0


# The stamina stats the sprint check depends on: max (11), recovery bonus (28), drain percent (154), the skill percents (162 / 163) and
# the per-level / by-time gains (241 / 242 / 294 / 295). A character with gear, passives or a high level carries values in them (the level
# 150 test character ran for minutes on its stamina and never ran dry), so the check sets Median's own (charstats: 50 points,
# nothing per level or vitality, no bonuses) and puts the character's numbers back afterwards.
SPRINT_STAMINA_STATS = (28, 154, 162, 163, 241, 242, 294, 295)


def check_sprint():
    if not need_game():
        return add("Sprint (SK7)", "BLOCKED", "not in a game")
    revive_if_dead()
    fight_ready()
    kept = {s: rd("player", s) for s in (10, 11) + SPRINT_STAMINA_STATS}
    try:
        cs = _charstats_row(hstate()["player"].get("class", 0))
        own_max = int(cs["stamina"]) * STAMINA_POINT
    except Exception:
        own_max = 50 * STAMINA_POINT
    for s in SPRINT_STAMINA_STATS:
        setstat("player", s, 0)
    setstat("player", 11, own_max)
    setstat("player", 10, own_max)
    try:
        _check_sprint()
    finally:
        for s in SPRINT_STAMINA_STATS + (11, 10):
            if kept.get(s) is not None:
                setstat("player", s, kept[s])


def _check_sprint():
    """Median's stamina rules (audit SK7 and sigma-patch-audit item 15; plugin part `stamina`, D2Sigma 0x100a1f90), asserted per
    frame and exactly. With the character's stamina bonuses zeroed (the wrapper) and 50 points of maximum (12800 raw):
      standing (mode 1 / 5)      +max/256 = +50 raw per frame
      walking, attacking, ...    +75% of that = +37 raw per frame (D2R's own step gives 50% = 25)
      running (mode 3)           no regeneration, and the run's own drain: RunDrain x 2 = 120 raw per frame (D2Game 0x77bb0), so
                                 a run from full lasts ceil(12800 / 120) = 107 frames = 4.3 s and then falls back to walking
      state 136 (Stamina Shrine) fills the bar
      no cooldown: a run starts with two points of stamina and the bar is the only limit
    Every sample is one `state` reply: frame, mode and stamina of the same server frame. Two consecutive samples in the same mode
    must differ by exactly rate x frames; a pair whose mode changed in between and came back (a walk that stopped for a frame and was
    ordered again) lies strictly between its mode's rate and the neighbouring rates, and is counted as such, not as a pass."""
    name = "Sprint (SK7) / stamina rules (audit item 15): run 107 frames on 50 stamina, 120 drain, no regeneration while running, standing 50, walking 37 per frame, no cooldown"
    p0 = hstate()["player"]
    try:
        cs = _charstats_row(p0.get("class", 0))
    except Exception as e:
        return add(name, "BLOCKED", "work/mod charstats.txt not readable: %r" % (e,))
    walk_v, run_v, run_drain = int(cs["WalkVelocity"]), int(cs["RunVelocity"]), int(cs["RunDrain"])
    full = rd("player", 11) or 0
    stand_rate = full >> 8                      # max / 256 raw per frame (stat 28 is zero here)
    walk_rate = stand_rate * 75 // 100          # 75% in every other mode
    run_rate = -2 * run_drain                   # no regeneration, drain RunDrain x 2
    bad, notes, log = [], [], []

    def judge(label, rows, mode, rate, others, capped_at=None, need=8, allow_straddle=True):
        """Pairs of consecutive samples that are both in `mode` (and not at the bar's end, where the cap hides the step): exact when the
        stamina changed by rate x frames, a straddle when it lies strictly inside the band between `rate` and one of `others` (the
        mode changed and changed back between the samples), wrong otherwise."""
        exact = straddle = wrong = frames = 0
        for a, b in _pairs(rows, mode):
            d, n = b[4] - a[4], b[0] - a[0]
            if capped_at is not None and (a[4] + max(rate, 0) * n >= capped_at or b[4] >= capped_at):
                continue
            if rate < 0 and (a[4] + rate * n <= 0 or b[4] <= 0):
                continue
            frames += n
            if d == rate * n:
                exact += 1
            elif any(min(rate, o) * n < d < max(rate, o) * n for o in others):
                straddle += 1
            else:
                wrong += 1
        notes.append("%s: %d consecutive samples in mode %d change by exactly %d raw per frame (%d frames), %d straddle a mode change, %d wrong" % (
            label, exact, mode, rate, frames, straddle, wrong))
        if wrong or exact < need or (not allow_straddle and straddle):
            bad.append("%s: %d exact / %d straddling / %d wrong pairs (rule %d raw per frame in mode %d)" % (label, exact, straddle, wrong, rate, mode))
        return exact

    # 1. a run from full stamina: drain 120 per frame, no regeneration, 107 frames, forced back to walking at the end
    run = _sprint_leg(full, False, 14, stop_exhausted=True)
    log += ["run  " + " ".join(map(str, r)) for r in run]
    judge("running", run, 3, run_rate, (stand_rate, walk_rate), need=5)
    run_frames = sum(b[0] - a[0] for a, b in _pairs(run, 3))
    exhausted = any(r[3] == 2 and r[4] < STAMINA_POINT * 2 for r in run)
    want_frames = -(-full // -run_rate)
    notes.append("run from %d: %d frames seen running of the %d (= %.1f s) the bar allows" % (full >> 8, run_frames, want_frames, want_frames / 25))
    if not exhausted:
        bad.append("the run was never forced back to walking when the stamina ran out")
    run_speed, _ = _speed(run, 3)

    # 2. walking: +75% of the standing step, from empty (the bar is not full, so the cap hides nothing), no minimum stamina
    walk_from_empty = _sprint_leg(0, True, 3.5)
    log += ["empty " + " ".join(map(str, r)) for r in walk_from_empty]
    judge("walking from empty", walk_from_empty, 2, walk_rate, (stand_rate, 0), capped_at=full, need=8)
    gained = max((r[4] for r in walk_from_empty if r[3] == 2), default=0) - (walk_from_empty[0][4] if walk_from_empty else 0)
    if gained < STAMINA_POINT:
        bad.append("no stamina came back while walking from empty (gain %d)" % gained)
    # speed only: the bar is full. A leg that is held up (a corner, an NPC in the way: 0.52 against 0.62 units per frame was seen
    # on the level 150 character) reads low, so a leg that does not give the expected ratio is repeated twice and the fastest counts
    want_ratio = run_v / walk_v
    walk_speed, walk_frames = 0.0, 0
    for attempt in range(3):
        walk = _sprint_leg(full, True, 5)
        log += ["walk " + " ".join(map(str, r)) for r in walk]
        sp, fr = _speed(walk, 2)
        if sp > walk_speed:
            walk_speed, walk_frames = sp, fr
        if walk_speed and abs(run_speed / walk_speed - want_ratio) <= 0.15 * want_ratio:
            break
    ratio = run_speed / walk_speed if walk_speed else 0
    notes.append("walk speed %.3f units/frame over %d frames; run %.3f; run/walk %.2f (charstats %d/%d = %.2f)" % (
        walk_speed, walk_frames, run_speed, ratio, run_v, walk_v, want_ratio))
    if not walk_frames or abs(ratio - want_ratio) > 0.15 * want_ratio:
        bad.append("run/walk speed %.2f, charstats wants %.2f" % (ratio, want_ratio))

    # 3. standing: +50 per frame, no stamina threshold, refilled from empty in max / 50 = 256 frames. The character is idle, so
    # every pair is one mode and none may straddle.
    setstat("player", 10, STAMINA_POINT * 2)
    here = _sample()
    H("move %d %d walk" % (here[1], here[2]))
    time.sleep(1.5)
    setstat("player", 10, 0)
    refill = []
    t0 = time.time()
    while time.time() - t0 < 16:
        r = _sample()
        refill.append(r)
        if r[4] >= full:
            break
        time.sleep(0.2)
    log += ["refill " + " ".join(map(str, r)) for r in refill]
    judge("standing refill", refill, 1, stand_rate, (walk_rate, 0), capped_at=full, need=8, allow_straddle=False)
    first = refill[0] if refill else None
    frames_full = (refill[-1][0] - first[0]) if first else 0
    # From the first sample (stamina s0) the bar needs ceil((max - s0) / 50) frames; the last sample is the first at the maximum, so
    # it can come later than that by the gap to the sample before it, never earlier.
    need = -(-(full - first[4]) // stand_rate) if first else 0
    gap = (refill[-1][0] - refill[-2][0]) if len(refill) > 1 else 0
    notes.append("standing refill %d -> %d points: %d frames (= %.1f s; the rule needs %d from the first sample, up to %d with the sampling gap)" % (
        first[4] >> 8 if first else -1, refill[-1][4] >> 8 if refill else -1, frames_full, frames_full / 25, need, need + gap))
    if not refill or refill[-1][4] < full or not need <= frames_full <= need + gap:
        bad.append("standing refill took %d frames, the rule %d..%d, reached %s" % (frames_full, need, need + gap, refill[-1][4] if refill else None))

    # 4. no cooldown: two points of stamina are enough for a run to start (the first direction that is free; the points last only
    # a few frames, so sample at once)
    modes = set()
    for dx, dy in [(int(dx * k), int(dy * k)) for k in (1.0, 0.5, 0.25) for dx, dy in SPRINT_DIRS]:  # a cramped spot: shorter paths
        setstat("player", 10, STAMINA_POINT * 2)
        here = _sample()
        H("move %d %d" % (here[1] + dx, here[2] + dy))
        modes = {_sample()[3] for _ in range(4)}
        if 3 in modes:
            break
        H("move %d %d walk" % (here[1], here[2]))
        time.sleep(0.5)
    notes.append("with 2 points of stamina a run starts: modes %s" % sorted(modes))
    if 3 not in modes:
        bad.append("a run did not start with 2 points of stamina (modes %s)" % sorted(modes))
    here = _sample()
    H("move %d %d walk" % (here[1], here[2]))
    time.sleep(1.0)

    # 5. state 136 (the Stamina Shrine, "infinite stamina") fills the bar
    setstat("player", 10, 0)
    ok, ls = H("setstate player 136 1")
    time.sleep(1.0)
    filled = rd("player", 10) or 0
    H("setstate player 136 0")
    notes.append("state 136: stamina 0 -> %d of %d after 1 s" % (filled >> 8, full >> 8))
    if not ok or filled < full:
        bad.append("state 136 left the stamina at %d of %d" % (filled, full))

    # 6. the key: R (toggle sprint) makes a click-to-move run, R again walks. The toggle is restored. The click needs open ground
    # around the character, which the field the earlier checks left it in may not have (trees, a cliff): the town is open on every side.
    goto(1)
    setstat("player", 10, full)
    keyrun = {}
    # Screen points in the directions the legs walked (world offset to isometric screen, the character is in the middle of the
    # window), then a spread of fixed points: a character in a cramped spot has only a few free ways out.
    # A `state` reply takes about 0.6 s, so a click that walks 8 units (190 px) is over before the first sample: the far points come first
    # (30 units and more: two seconds of walking), then the near ones.
    click_points = [(0.12, 0.50), (0.88, 0.50), (0.50, 0.12), (0.50, 0.80), (0.20, 0.20), (0.80, 0.80), (0.20, 0.80), (0.80, 0.20)]
    for dx, dy in SPRINT_DIRS:
        u, v = dx - dy, (dx + dy) / 2.0
        n = (u * u + v * v) ** 0.5
        click_points.append((0.5 + u / n * 190 / 1600.0, 0.5 + v / n * 190 / 900.0))
    click_points += [(0.80, 0.50), (0.20, 0.50), (0.50, 0.85), (0.50, 0.15), (0.65, 0.65), (0.35, 0.35), (0.65, 0.30), (0.35, 0.70),
                     (0.58, 0.50), (0.42, 0.50)]
    for label in ("on", "off"):
        g.press_bg("r", hold=0.1)
        time.sleep(0.3)
        for fx, fy in click_points:  # a click on a wall does not move; the point depends on where the character stands
            g.click_bg(fx, fy)
            for _ in range(3):  # the order reaches the server a few frames after the click
                time.sleep(0.1)
                smp = _sample()
                keyrun[label] = smp[3]
                log.append("R %s click %.3f,%.3f -> frame %d x %d y %d mode %d" % ((label, fx, fy) + (smp[0], smp[1], smp[2], smp[3])))
                if keyrun[label] in (2, 3, 6):
                    break
            if keyrun[label] in (2, 3, 6):
                break
        time.sleep(2.5)
    # The run toggle is the character's own setting (it survives a restart), so the check does not know which way the first press goes:
    # the two presses must give one run and one walk, and the second press puts the character's toggle back.
    notes.append("key R: click-to-move mode %s after the first press, %s after the second (3 = run, 2 or 6 in the town = walk; one of each, the toggle ends where it began)" % (
        keyrun["on"], keyrun["off"]))
    if sorted(2 if m == 6 else m for m in (keyrun["on"], keyrun["off"])) != [2, 3]:  # 6 is walking in the town
        bad.append("toggle key R gave modes %s / %s (want one run and one walk)" % (keyrun["on"], keyrun["off"]))
    setstat("player", 10, full)
    shot = sh("sprint")
    goto(2)  # back to the field the next check starts from (standing there is mode 1, in the town it is mode 5)
    add(name, "PASS" if not bad else "FAIL", "; ".join(notes) if not bad else "; ".join(bad) + " | " + "; ".join(notes),
        [shot], log)


def mapcells():
    """`h mapcells` (client): dict cells / layer / layers / debugflag, or None."""
    ok, lines = H("mapcells")
    for ln in lines:
        if ln.startswith("mapcells "):
            return {k: int(v) for k, v in kv(ln).items() if re.fullmatch(r"-?\d+", v)}
    return None


def check_mapreveal():
    name = "Map reveal (audit MU2): the reveal action adds automap cells to a freshly entered level (reached without debug mode)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    # `cheat goto` needs debug mode, and in debug mode the game draws every level's automap whole on arrival (an earlier run of this
    # check measured +0 cells for that reason). So the level is entered with the plugin's `level` (the NPC travel, no debug mode) and
    # the baseline is read for a few seconds before the reveal: cells that stream in by themselves are not the reveal's.
    if DEBUG_ON["v"]:
        return add(name, "BLOCKED", "debug mode was switched on earlier in this game (its automap is drawn whole): run `mapreveal` first or alone")
    revive_if_dead()
    log, notes = [], []
    start = hstate()["player"].get("area")
    # `level` is the NPC travel (towns of other acts only; a field level answers nothing, as run checks-20261023-185038-s3 showed): the
    # freshly entered level is a town, Lut Gholein (a big one: most of its rooms are out of sight on arrival)
    area = 40
    if start == area:
        H("level 1")
        time.sleep(6)
    H("level %d" % area)
    t0 = time.time()
    while time.time() - t0 < 40 and hstate()["player"].get("area") != area:
        time.sleep(2)
    if hstate()["player"].get("area") != area:
        return add(name, "BLOCKED", "could not travel to area %d with `level`" % area)
    g.press("tab")  # automap overlay on (D2R's default key)
    series = []
    for _ in range(4):
        time.sleep(1.5)
        series.append(mapcells())
    a0 = series[-1]
    p0 = g.shot("mapreveal_before")
    c0 = travel_counts()
    ok, lines = H("hotkey reveal")
    time.sleep(2.5)
    a1 = mapcells()
    p1 = g.shot("mapreveal")
    c1 = travel_counts()
    ok2, lines2 = H("hotkey reveal")  # a second reveal finds nothing new
    time.sleep(1.5)
    a2 = mapcells()
    g.press("tab")
    goto(1)  # leave Lut Gholein: the checks after this one expect Act 1
    log = ["baseline series %s" % series, "after %s" % a1, "again %s" % a2, c0["line"], c1["line"]] + lines + lines2
    if not a0 or not a1 or not a2:
        return add(name, "BLOCKED", "no automap data: %s" % lines[:2], [], log)
    streaming = series[-1]["current"] - series[-2]["current"]
    grew = a1["current"] - a0["current"]
    again = a2["current"] - a1["current"]
    pressed = c1.get("reveal_n") == (c0.get("reveal_n") or 0) + 1 and c1.get("reveals") == (c0.get("reveals") or 0) + 1
    status = "PASS" if ok and ok2 and pressed and grew > max(50, 4 * abs(streaming)) and again <= max(5, abs(grew) // 50) else "FAIL"
    if status == "FAIL" and ok and ok2 and pressed and grew == 0 and again == 0 and a0["current"] >= 1500:
        status = "PARTIAL"  # the level was already drawn whole on arrival (its map is remembered from an earlier visit): nothing left for the reveal to add
    add(name, status,
        "level %d entered with `level` (debug mode off): cells of the current layer %d (steady: the last two samples differ by %+d) -> %d after one reveal (%+d), a second reveal %+d; "
        "all layers %d -> %d cells in %d -> %d layers, debug flag byte %d -> %d; presses %s -> %s, reveals %s -> %s. The port reveals the connected rooms of the current level; "
        "Median's call (0x887c0) walks every level of the act, which the client cannot show (its other levels are not loaded)" % (
            area, a0["current"], streaming, a1["current"], grew, again, a0["cells"], a1["cells"], a0["layers"], a1["layers"], a0["debugflag"], a1["debugflag"],
            c0.get("reveal_n"), c1.get("reveal_n"), c0.get("reveals"), c1.get("reveals")),
        [os.path.basename(p0), os.path.basename(p1)], log)


def wpbit(number):
    ok, lines = H("waypoint n %d get" % number)
    for ln in lines:
        m = re.match(r"waypoint number %d = (\d)" % number, ln)
        if m:
            return int(m.group(1))
    return None


def wpobjs():
    """`h wpobj`: (player dict, [object dicts])."""
    ok, lines = H("wpobj")
    player, objs = {}, []
    for ln in lines:
        if ln.startswith("wpobj player"):
            m = re.search(r"at (\d+),(\d+) level=(-?\d+) number=(-?\d+)", ln)
            if m:
                player = dict(x=int(m.group(1)), y=int(m.group(2)), level=int(m.group(3)), number=int(m.group(4)))
        elif ln.startswith("wpobj id="):
            m = re.search(r"id=(\d+) class=(\d+) at (\d+),(\d+) dist=(\d+) level=(-?\d+) inrange=(\d)", ln)
            if m:
                objs.append(dict(id=int(m.group(1)), cls=int(m.group(2)), x=int(m.group(3)), y=int(m.group(4)), dist=int(m.group(5)),
                                 level=int(m.group(6)), inrange=int(m.group(7))))
    return player, objs


def check_wparrival():
    name = "Waypoint travel arrives beside the level's real waypoint object"
    log, rows, bad = [], [], []
    control = "wparrival" in CONTROL
    text = mxl_text()
    log.append(text)
    if ("waypoint arrival off:" if control else "waypoint arrival on:") not in text:
        return add(name, "FAIL", "arrival part has the wrong on/off state", [], log)
    god(True)
    H("waypoint tabs")  # unlock test act tabs before the first panel is constructed
    # Approach is setup: load the real waypoint room and stand beside its object.
    # Record actual object coordinates before travel, independently of the selector.
    for area in (3, 138, 139, 141, 147, 153, 155, 169, 242):
        goto(area)
        log.extend(H("waypoint approach")[1])
        time.sleep(2)
        player, objects = wpobjs()
        here = [o for o in objects if o["level"] == area]
        if not here:
            bad.append("area %d has no loaded waypoint" % area)
            continue
        obj = min(here, key=lambda o: o["dist"])
        log.append("destination object %s" % obj)
        H("waypoint %d clear" % area)
        # OperateFn 23 activates the real object and sends its waypoint record.
        # The travel packet below does not depend on client panel state.
        log.extend(H("operate %d 23" % obj["id"])[1])
        time.sleep(1)
        if wpbit(player["number"]) != 1:
            bad.append("area %d did not activate" % area)
            continue
        source_area = 1 if area == 3 else 3
        goto(source_area)
        H("waypoint approach")
        time.sleep(2)
        _, sources = wpobjs()
        source = next((o for o in sources if o["level"] == source_area), None)
        if source is None:
            bad.append("no source waypoint")
            break
        log.append("source object %s" % source)
        H("move %d %d" % (source["x"] - 1, source["y"] - 1))
        time.sleep(4)
        source_player = hstate()["player"]
        if max(abs(source_player.get("x", 0) - source["x"]), abs(source_player.get("y", 0) - source["y"])) > 5:
            bad.append("could not walk beside the source waypoint for area %d" % area)
            continue
        log.extend(H("operate %d 23" % source["id"])[1])
        time.sleep(3)  # allow the source object's activation animation to finish
        packet = bytes([0x4b]) + struct.pack("<I", area)
        log.extend(H("pkt " + " ".join("%02x" % b for b in packet))[1])
        time.sleep(4)
        p = hstate()["player"]
        distance = max(abs(p.get("x", -99999) - obj["x"]), abs(p.get("y", -99999) - obj["y"]))
        correct = p.get("area") == area and distance <= 12
        expected = not control or area in (3, 153)  # maze levels already find their waypoint
        rows.append("area %d object %d,%d -> player %s,%s area %s distance %d (%s)" % (
            area, obj["x"], obj["y"], p.get("x"), p.get("y"), p.get("area"), distance,
            "waypoint" if correct else "entry fallback" if p.get("area") == area else "travel refused"))
        if correct != expected or p.get("area") != area:
            bad.append(rows[-1])
    log.extend(rows)
    goto(1)
    god(False)
    add(name, "FAIL" if bad else "PASS", "; ".join(bad or rows), [], log)


def check_wppanel():
    name = "HD waypoint panel lists all 47 Median waypoints under their acts"
    goto(1)
    H("waypoint approach")
    H("waypoint all set")
    H("waypoint tabs")
    _, objects = wpobjs()
    source = next((o for o in objects if o["level"] == 1), None)
    if source is None:
        return add(name, "BLOCKED", "no real source waypoint")
    H("operate %d 23" % source["id"])
    H("waypoint open")
    time.sleep(1)
    g.key("esc")  # it is known open; rebuild tabs after changing test quest flags
    H("waypoint tabs")
    H("waypoint open")
    time.sleep(3)
    expected = ((1, 3, 4, 5, 6, 27, 29, 32, 35, 153),
                (40, 48, 42, 57, 43, 44, 52, 74, 46, 147, 169),
                (75, 76, 77, 78, 79, 80, 81, 83, 101, 138, 141, 155),
                (103, 106, 107, 139),
                (109, 111, 112, 113, 115, 123, 117, 118, 129, 242))
    log, shots, bad = [], [], []
    for tab, levels in enumerate(expected):
        g.click(.1227 + tab * .04505, .205)
        time.sleep(1)
        lines = H("waypoint panel")[1]
        log.extend(lines)
        actual = [int(m.group(1)) for ln in lines if (m := re.search(r"waypoint button \d+: level (\d+)", ln))]
        if actual != list(levels):
            bad.append("tab %d: %s, expected %s" % (tab + 1, actual, levels))
        shots.append(sh("waypoints_hd_tab%d" % (tab + 1)))
    g.key("esc")
    add(name, "FAIL" if bad else "PASS", "; ".join(bad) if bad else "10/11/12/4/10 buttons; all eight added areas present", shots, log)


def check_wpauto():
    name = "Waypoint auto-activation: walking up to a waypoint (distance < 36) activates it, standing away does not"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    st = goto(3)
    if st["player"].get("area") != 3:
        return add(name, "BLOCKED", "could not go to area 3")
    time.sleep(2)
    player, objs = wpobjs()
    here = [o for o in objs if o["level"] == player.get("level")]
    log = ["player %s" % player] + ["obj %s" % o for o in here]
    if not here or player.get("number", -1) < 0:
        return add(name, "BLOCKED", "no waypoint object of this level is loaded yet (%s)" % log[:2], [], log)
    num = player["number"]
    wp = min(here, key=lambda o: o["dist"])
    res = []
    # A. wherever the character stands: clear the bit and see whether the rule re-sets it, by distance.
    H("waypoint n %d clear" % num)
    time.sleep(1.5)
    bit_a = wpbit(num)
    res.append("A: distance %d, bit after 1.5 s: %s" % (wp["dist"], bit_a))
    near_ok = (bit_a == 1) if wp["dist"] < 36 else (bit_a == 0)
    # B. walk to the waypoint from outside the radius: clear first, expect the bit to come on within the walk.
    far = None
    if wp["dist"] >= 36 and bit_a == 0:
        far = wp["dist"]
    else:
        # step away: try points 55 sub-tiles from the object in eight directions until the character is out of range
        for ox, oy in ((55, 0), (-55, 0), (0, 55), (0, -55), (40, 40), (-40, -40), (40, -40), (-40, 40)):
            H("move %d %d" % (wp["x"] + ox, wp["y"] + oy))
            t0 = time.time()
            while time.time() - t0 < 9:
                time.sleep(1)
                p2, o2 = wpobjs()
                w2 = [o for o in o2 if o["id"] == wp["id"]]
                if w2 and w2[0]["dist"] >= 40:
                    far = w2[0]["dist"]
                    break
            if far is not None:
                break
        H("waypoint n %d clear" % num)
        time.sleep(1.5)
    bit_far = wpbit(num)
    res.append("B: left to distance %s, bit cleared and still %s after 1.5 s (rule must not fire)" % (far, bit_far))
    walked_ok = None
    snd0 = reward_stats()
    if far is not None and bit_far == 0:
        H("move %d %d" % (wp["x"], wp["y"]))
        t0 = time.time()
        d_at = None
        while time.time() - t0 < 30:
            time.sleep(1)
            if wpbit(num) == 1:
                p3, o3 = wpobjs()
                w3 = [o for o in o3 if o["id"] == wp["id"]]
                d_at = w3[0]["dist"] if w3 else None
                break
        walked_ok = d_at is not None
        res.append("C: walking to the object set the bit at distance %s" % d_at)
        # Median's message 0x5e (the waypoint-open sound, row 2642) comes with the activation: the plugin's message 0x70.
        snd1 = None
        for _ in range(10):
            time.sleep(0.5)
            snd1 = reward_stats()
            if snd0 and snd1 and snd1[1] > snd0[1]:
                break
        sound_ok = bool(snd0 and snd1 and snd1[1] == snd0[1] + 1 and snd1[2] == 0x70 and snd1[3] == 2642)
        res.append("D: waypoint-open sound (message 0x70, row 2642): played %s -> %s, last message 0x%x sound %s"
                   % (snd0[1] if snd0 else None, snd1[1] if snd1 else None, snd1[2] if snd1 else 0, snd1[3] if snd1 else None))
        walked_ok = walked_ok and (sound_ok or not (snd0 and snd0[0]))
    status = [l for l in H("travel")[1] if l.startswith("travel ")]
    log += res + status
    if far is None or bit_far != 0:
        return add(name, "PARTIAL" if near_ok else "FAIL", "; ".join(res) + " (could not get out of range for the negative control)", [], log)
    add(name, "PASS" if (near_ok and walked_ok) else "FAIL", "waypoint number %d of level %d: %s" % (num, player["level"], "; ".join(res)), [sh("wpauto")], log)


def travel_counts():
    """`h travel` -> dict: pickup / reveal / transmute key presses, reveals, transmutes, blocked, registered bindings text, pickup
    state, cube state."""
    ok, lines = H("travel")
    line = next((l for l in lines if l.startswith("travel ")), "")
    d = {"line": line}
    m = re.search(r"keys pickup (\d+) reveal (\d+) transmute (\d+)", line)
    if m:
        d.update(pickup_n=int(m.group(1)), reveal_n=int(m.group(2)), transmute_n=int(m.group(3)))
    m = re.search(r"reveals (\d+)", line)
    d["reveals"] = int(m.group(1)) if m else None
    m = re.search(r"transmutes (\d+) \(blocked (\d+), cube (\w+)\)", line)
    if m:
        d.update(transmutes=int(m.group(1)), blocked=int(m.group(2)), cube=m.group(3))
    m = re.search(r"pickup (on|off)", line)
    d["pickup"] = m.group(1) if m else None
    d["bindings"] = line.split("||")[0]
    return d


def plugin_key_bindings(bindings):
    """{logical id: virtual key} from the `travel` line's registered bindings ("mxl_pickup_toggle: key 0x58 modifier 0 | ...")."""
    return {m.group(1): int(m.group(2), 16) for m in re.finditer(r"(mxl_\w+): key 0x([0-9a-f]+) modifier 0", bindings)}


def d2r_key_bindings():
    """{virtual key: [D2R action ids]} from the test character's own key file (`<character>.key` next to the save: D2R's key
    bindings; a six-byte header, then records of five 16-bit words: virtual key (65535 = unbound), slot (0 primary, 1 secondary), 0,
    action id, 0). None when the file does not exist."""
    path = os.path.join(SAVES, g.CHAR_NAME + ".key")
    if not os.path.exists(path):
        return None
    d = open(path, "rb").read()
    w = struct.unpack("<%dH" % (len(d) // 2), d[:len(d) // 2 * 2])
    out = {}
    for i in range(3, len(w) - 4, 5):
        if w[i] != 65535:
            out.setdefault(w[i], []).append(w[i + 3])
    return out


HOTKEY_DEFAULTS = {"mxl_pickup_toggle": 0x58, "mxl_map_reveal": 0x4c, "mxl_transmute": 0x4b}  # X, L, K (plugin/src/travel_logic.h)
HOTKEY_COUNTERS = ("pickup_n", "reveal_n", "transmute_n", "reveals", "transmutes", "blocked")


def check_hotkeys():
    name = "Hotkeys (auto pickup X, map reveal L, transmute K): one press, one action; none on a D2R key (R run toggle, C Character screen)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(3)
    time.sleep(2)
    t0 = travel_counts()
    if "pickup_n" not in t0:
        return add(name, "BLOCKED", "no travel status line: %s" % t0["line"][:100], [], [t0["line"]])
    log = [t0["line"]]
    res, bad = [], []
    bound = plugin_key_bindings(t0["bindings"])
    if set(bound) != set(HOTKEY_DEFAULTS):
        return add(name, "FAIL", "registered bindings %s, expected %s" % (t0["bindings"], sorted(HOTKEY_DEFAULTS)), [], log)
    keyname = {i: chr(k).lower() for i, k in bound.items()}

    def moved(before, after):
        """The counters that changed between two `travel` reads."""
        return [k for k in HOTKEY_COUNTERS if after.get(k) != before.get(k)]

    # 1. the registered keys: the plugin's defaults (unless the player rebound them in the Controls menu) and not one of them
    # bound by a D2R action. D2R's bindings come from the character's key file (the other keys D2R uses are in it too).
    for ident, want in HOTKEY_DEFAULTS.items():
        if bound[ident] != want:
            bad.append("%s is bound to %s, the default is %s" % (ident, chr(bound[ident]), chr(want)))
    d2r = d2r_key_bindings()
    if d2r is None:
        res.append("D2R key file not found (static conflict check skipped)")
    else:
        for ident, key in bound.items():
            if key in d2r:
                bad.append("%s key %s is also bound by D2R action(s) %s: one press does both" % (ident, chr(key), d2r[key]))
        res.append("plugin keys %s, D2R's own key file binds %d keys and none of these (D2R: R = action %s, the run toggle; C = action %s, the Character screen)" % (
            {i: chr(k) for i, k in bound.items()}, len(d2r), d2r.get(ord("R")), d2r.get(ord("C"))))
    for key in (ord("R"), ord("C")):
        if key in bound.values():
            bad.append("a plugin action is on %s, a D2R key" % chr(key))
    # 2. auto pickup key: toggles the flag, nothing else moves
    g.press(keyname["mxl_pickup_toggle"])
    time.sleep(0.6)
    t1 = travel_counts()
    g.press(keyname["mxl_pickup_toggle"])
    time.sleep(0.6)
    t2 = travel_counts()
    m1 = moved(t0, t1)
    x_ok = (t1["pickup_n"] == t0["pickup_n"] + 1 and t1["pickup"] != t0["pickup"] and t2["pickup_n"] == t0["pickup_n"] + 2 and
            t2["pickup"] == t0["pickup"] and m1 == ["pickup_n"])
    res.append("%s (auto pickup): presses %s->%s->%s, pickup %s->%s->%s, counters moved by the first press: %s" % (
        keyname["mxl_pickup_toggle"].upper(), t0["pickup_n"], t1["pickup_n"], t2["pickup_n"], t0["pickup"], t1["pickup"], t2["pickup"], m1))
    if not x_ok:
        bad.append("auto pickup key")
    # 3. map reveal key: one reveal, no transmute, no pickup toggle
    a0 = mapcells()
    g.press(keyname["mxl_map_reveal"])
    time.sleep(1.5)
    t3 = travel_counts()
    a1 = mapcells()
    m3 = moved(t2, t3)
    r_ok = t3["reveal_n"] == t2["reveal_n"] + 1 and t3["reveals"] == t2["reveals"] + 1 and set(m3) == {"reveal_n", "reveals"} and t3["pickup"] == t2["pickup"]
    res.append("%s (map reveal): presses %s->%s, reveals %s->%s, cells %s->%s, counters moved: %s" % (
        keyname["mxl_map_reveal"].upper(), t2["reveal_n"], t3["reveal_n"], t2["reveals"], t3["reveals"], a0 and a0["cells"], a1 and a1["cells"], m3))
    if not r_ok:
        bad.append("map reveal key")
    # 4. D2R's own keys: a press of R (run / walk toggle) or C (Character screen) must leave every plugin counter alone. C's panel
    # is in the screenshot; Esc closes it again.
    g.press("r")
    time.sleep(0.5)
    g.press("c")
    time.sleep(1.2)
    char_shot = sh("hotkeys_c_charscreen")
    t5 = travel_counts()
    g.press("esc")
    time.sleep(0.6)
    g.press("r")  # R is D2R's run toggle and the character keeps it: put it back
    time.sleep(0.4)
    m5 = moved(t3, t5)
    res.append("R and C pressed: plugin counters moved %s (must be none: the plugin has no action on D2R's run toggle and Character screen)" % (m5 or "none"))
    if m5 or t5["pickup"] != t3["pickup"]:
        bad.append("R / C moved a plugin counter: %s" % m5)
    # 5. the transmute key: closed cube -> counted and blocked, open cube -> transmutes once
    okb, lb = H("item box inv")
    log += lb
    mark = mxl_mark()
    g.press("i")
    time.sleep(1.2)
    inv_shot = sh("hotkeys_inventory")
    g.click(0.677, 0.452, "right")  # the cube item (inventory cell 0,0, 2 x 2 cells) in the 1600 x 900 inventory (hotkeys_inventory.png)
    time.sleep(1.5)
    cube_shot = sh("hotkeys_cube")
    msgs = [l for l in mxl_lines_since(mark) if "cube ui message" in l]
    log += msgs[:12]
    t_open = travel_counts()
    g.press("esc")  # one Esc closes the cube panel and the inventory with it (a second one would open the game menu)
    time.sleep(0.6)
    t6 = travel_counts()
    g.press(keyname["mxl_transmute"])
    time.sleep(0.8)
    t7 = travel_counts()
    m7 = moved(t6, t7)
    c_closed = t7["transmute_n"] == t6["transmute_n"] + 1 and t7["transmutes"] == t6["transmutes"] and "reveal_n" not in m7 and "pickup_n" not in m7
    res.append("%s (transmute), cube closed: presses %s->%s, transmutes %s->%s (blocked %s), counters moved: %s" % (
        keyname["mxl_transmute"].upper(), t6["transmute_n"], t7["transmute_n"], t6["transmutes"], t7["transmutes"], t7.get("blocked"), m7))
    if not c_closed:
        bad.append("transmute key, cube closed")
    log += [t1["line"], t2["line"], t3["line"], t5["line"], t7["line"], t0["bindings"]]
    open_note = "transmute with the cube open: not driven (the plugin did not see the cube panel open; ui messages: %s)" % (msgs[:3] or "none")
    if t_open.get("cube") == "open":
        g.press("i")  # open it again for the key
        time.sleep(1.0)
        g.click(0.677, 0.452, "right")
        time.sleep(1.2)
        t8 = travel_counts()
        g.press(keyname["mxl_transmute"])
        time.sleep(1.0)
        t9 = travel_counts()
        m9 = moved(t8, t9)
        c_open = t9.get("transmutes") == t8.get("transmutes", 0) + 1 and t9["transmute_n"] == t8["transmute_n"] + 1 and "reveal_n" not in m9 and "pickup_n" not in m9
        log += [t_open["line"], t8["line"], t9["line"]]
        open_note = "transmute with the cube open: presses %s->%s, transmutes %s->%s (cube %s; ui message %s)" % (
            t8["transmute_n"], t9["transmute_n"], t8.get("transmutes"), t9.get("transmutes"), t8.get("cube"), msgs[:1])
        if not c_open:
            bad.append("transmute key, cube open")
        g.press("esc")
        time.sleep(0.5)
    add(name, "PASS" if not bad else "FAIL", "; ".join(res) + "; " + open_note + ("; failed: %s" % bad if bad else ""),
        [sh("hotkeys"), inv_shot, cube_shot, char_shot], log)


def check_stashpages():
    name = "Stash pages: ten shared stash tabs exist (d2rloader.toml add_shared_tabs)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    res, log, wrong = [], [], []
    for tab in list(range(0, 11)) + [12]:
        ok, lines = H("stashprobe %d" % tab)
        if not ok:
            return add(name, "BLOCKED", "stashprobe refused: %s" % lines[:2], [], lines)
        out = ""
        for _ in range(20):
            time.sleep(0.4)
            ok2, l2 = H("stashprobe result")
            out = next((l for l in l2 if l.startswith("stashprobe result")), "")
            if " -1 " not in out:
                break
        log.append("tab %d: %s" % (tab, out))
        made = " 1 page=" in out
        should = tab < 10
        res.append("%d%s" % (tab, "+" if made else "-"))
        if made != should:
            wrong.append("tab %d %s" % (tab, "accepted an item" if made else "refused (%s)" % out[:60]))
    add(name, "PASS" if not wrong else "FAIL",
        "an item created in shared stash tab n through ItemService (+ accepted, - refused): %s; expected tabs 0-9 accepted and 10, 12 refused%s"
        % (" ".join(res), ("; wrong: " + "; ".join(wrong)) if wrong else ""), [], log)


def _stashpage_job(cmd, want):
    """A queued stashpage job (put / list / move / drop) and its answer: the `stashpage result` line once it is not pending."""
    ok, lines = H("stashpage " + cmd)
    if not ok:
        return False, "refused: %s" % (lines[:2],)
    out = ""
    for _ in range(20):
        time.sleep(0.4)
        ok2, l2 = H("stashpage result")
        out = next((l for l in l2 if l.startswith("stashpage result")), "")
        if " -1 pending" not in out and " -2 " not in out:
            break
    return want in out, out


def check_stashpage2():
    name = "Stash pages: personal page 2 (item page 6): panel, arrows, items on it, moves between the pages"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    txt = mxl_text()
    bad, res, log, shots = [], [], [], []
    if "stash pages on:" not in txt:
        return add(name, "FAIL", "`mxl` does not say `stash pages on`: %s" % next((l for l in txt.splitlines() if "stash pages" in l), "-"))
    # two test items on page 2 (codes the test character never carries)
    for cmd, label in (("put r05 1 1", "item 1"), ("put r06 5 5", "item 2")):
        ok, out = _stashpage_job(cmd, "container=9")  # 9 = the custom page
        log.append(out)
        if not ok:
            bad.append("%s not created on page 2 (%s)" % (label, out[:80]))
    ok, out = _stashpage_job("list", "p2:r05@1,1")
    log.append(out)
    res.append("page 2 holds both items: %s" % ("yes" if ok and "p2:r06@5,5" in out else "NO"))
    if not (ok and "p2:r06@5,5" in out):
        bad.append("page 2 list: %s" % out[:100])
    ids = {m.group(1): m.group(2) for m in re.finditer(r"p\d:(r0\d)@\d+,\d+#(\d+)", out)}
    # the stock stash with its strip, the arrow to page 2 and back (D2R's own messages; background clicks on the strip)
    H("stashpage uia PanelManager OpenPanel BankExpansionLayout")
    time.sleep(2)
    ok, lines = H("stashpage widget BankExpansionLayout MxlPersonalNavigation")
    log += lines
    strip = next((l for l in lines if "rect result 0" in l), "")
    res.append("stock stash has the 1 / 2 strip: %s" % ("yes" if strip else "NO"))
    if not strip:
        bad.append("MxlPersonalNavigation missing in the stock stash (%s)" % (lines[:1],))
    shots.append(sh("stashpage_p1"))
    g.click(0.2506, 0.6756)  # the right arrow of the stock strip
    time.sleep(1.8)
    st = next((l for l in H("stashpage state")[1] if l.startswith("stashpage state=")), "")
    opened = st.startswith("stashpage state=2")
    res.append("right arrow opens the page 2 panel: %s" % ("yes" if opened else "NO (%s)" % st[:40]))
    if not opened:
        bad.append("page 2 panel did not open")
    shots.append(sh("stashpage_p2"))
    g.click(0.1725, 0.6756)  # the left arrow of the page 2 strip: back to the stock stash
    time.sleep(1.8)
    st = next((l for l in H("stashpage state")[1] if l.startswith("stashpage state=")), "")
    closed = st.startswith("stashpage state=1")
    res.append("arrow on page 2 returns to the stock stash: %s" % ("yes" if closed else "NO (%s)" % st[:40]))
    if not closed:
        bad.append("the page 2 panel stayed open")
    # moves between the pages through ItemService (atomic), then back
    if "r05" in ids:
        ok1, o1 = _stashpage_job("move %s 1 2 2" % ids["r05"], "move rc=0 committed=1")
        ok2, l1 = _stashpage_job("list", "p1:r05@2,2")
        ok3, o3 = _stashpage_job("move %s 2" % ids["r05"], "move rc=0 committed=1")
        ok4, l2 = _stashpage_job("list", "p2:r05@")
        log += [o1, l1, o3, l2]
        res.append("item moved page 2 -> 1 -> 2: %s" % ("yes" if ok1 and ok2 and ok3 and ok4 else "NO"))
        if not (ok1 and ok2 and ok3 and ok4):
            bad.append("move between the pages failed (%s / %s / %s / %s)" % (o1[:50], l1[:60], o3[:50], l2[:60]))
    # clean-up: the test character keeps nothing on its pages
    H("stashpage uia PanelManager ClosePanel BankExpansionLayout")
    for code in ("r05", "r06"):
        ok, out = _stashpage_job("drop " + code, "1 destroyed")
        log.append(out)
        if not ok:
            bad.append("clean-up of %s failed (%s)" % (code, out[:60]))
    add(name, "PASS" if not bad else "FAIL", "; ".join(res) + ("; failed: %s" % "; ".join(bad) if bad else ""), shots, log)



def _sd_steps(st, lvl):
    """Per-level bonus: the five steps cover the levels 2-8, 9-16, 17-22, 23-28 and 29+."""
    if lvl <= 1:
        return 0
    total, prev = 0, 1
    for i, top in enumerate((8, 16, 22, 28, None)):
        top = lvl if top is None else min(top, lvl)
        if top <= prev:
            break
        total += (top - prev) * st[i]
        prev = top
    return total


def _sd_i32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def _sd_tdiv(a, b):
    """Integer division truncated toward zero (C)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _sd_pct(value, percent):
    """value * percent / 100 truncated toward zero (D2Sigma 0x10088e50); 0 when either factor is 0."""
    if value == 0 or percent == 0:
        return 0
    return _sd_i32(_sd_tdiv(value * percent, 100))


def _sd_base_synergy(clvl, energy, stat514):
    """((energy+20)*130/(energy+500) + 50 + min(stat/10, 100)) * (min(clvl, 120)+5) * 10 / 100 - 75 (0x100a6c70)."""
    extra = min(_sd_tdiv(stat514, 10), 100)
    spread = _sd_tdiv((energy + 20) * 130, energy + 500) if energy + 500 else 0
    return _sd_tdiv((spread + 50 + extra) * (min(clvl, 120) + 5) * 10, 100) - 75


def _sd_elemental(base, st, shift, lvl, percent, mastery):
    v = _sd_i32((_sd_steps(st, lvl) + base) << shift)
    if percent:
        v = _sd_i32(v + _sd_pct(v, percent))
    if mastery:
        v = _sd_i32(v + _sd_pct(v, mastery))
    return v


def _sd_physical(base, st, lvl, shift, percent, mastery):
    """Skills without a weapon share (SrcDam 0): the weapon part is 0."""
    own = _sd_steps(st, lvl) + base
    if percent:
        own = _sd_i32(own + _sd_pct(own, percent))
    if mastery:
        own = _sd_i32(own + _sd_pct(own, mastery))
    return _sd_i32(own << shift)


# damage type names of skills.txt EType that the mastery helper (0x337f40) maps to a mastery stat
_SD_MASTERY_TYPES = ("fire", "ltng", "mag", "cold", "pois")


_SD_MASTERY_STATS = (329, 330, 331, 332, 357)  # fire, lightning, cold, poison, magic mastery


def _sd_load():
    """D2R skill id -> the damage columns of the built skills.txt plus the skills2 flags (1 BaseSynergy, 2 StaticDamage)."""
    t = _tsv(os.path.join(BUILT_EXCEL, "skills.txt"))
    col = {c: i for i, c in enumerate(t[0])}

    def cell(r, c):
        return r[col[c]] if col[c] < len(r) else ""

    def num(r, c):
        try:
            return int(cell(r, c))
        except ValueError:
            return 0

    idmap = json.load(open(_main_checkout(os.path.join(REPO, "work", "named", "idmap.json")), encoding="utf-8"))
    sk2 = open(_main_checkout(os.path.join(REPO, "extract", "mxl", "data", "global", "excel", "skills2.bin")), "rb").read()
    n = struct.unpack_from("<I", sk2)[0]
    flags = {}
    for e in idmap["skills"]:
        if e["row"] < n:
            o = 4 + e["row"] * 66
            f = (1 if sk2[o + 0x2d] else 0) | (2 if sk2[o + 0x2e] else 0)
            if f:
                flags[e["id"]] = f
    skills = {}
    for r in t[1:]:
        if not r or not cell(r, "*Id").lstrip("-").isdigit():
            continue
        sid = int(cell(r, "*Id"))
        skills[sid] = {
            "name": r[0], "flags": flags.get(sid, 0), "shift": num(r, "HitShift"), "srcdam": num(r, "SrcDam"),
            "pmin": num(r, "MinDam"), "pmax": num(r, "MaxDam"), "pminst": [num(r, "MinLevDam%d" % i) for i in range(1, 6)],
            "pmaxst": [num(r, "MaxLevDam%d" % i) for i in range(1, 6)], "pcalc": cell(r, "DmgSymPerCalc"),
            "etype": cell(r, "EType"), "emin": num(r, "EMin"), "emax": num(r, "EMax"),
            "eminst": [num(r, "EMinLev%d" % i) for i in range(1, 6)], "emaxst": [num(r, "EMaxLev%d" % i) for i in range(1, 6)],
            "ecalc": cell(r, "EDmgSymPerCalc"), "passive": cell(r, "passive"),
        }
    return skills, {v["name"]: k for k, v in skills.items()}


def _sd_query(sid, lvl, mastery=True):
    """`skilldmg` parsed to a dict of ints; ele / phys / orig_ele / orig_phys are (min, max)."""
    for _ in range(3):  # the harness now and then misses its 15 s window while the game is busy
        ok, line, _l = hv("skilldmg %d %d%s" % (sid, lvl, "" if mastery else " nomastery"), "skilldmg")
        if ok and "skilldmg skill=" in line:
            break
        time.sleep(1)
    else:
        return None
    d = {k: int(v) for k, v in kv(line).items() if re.fullmatch(r"-?\d+", v)}
    for key in ("ele", "phys", "orig_ele", "orig_phys"):
        m = re.search(r"\b" + key + r"=(-?\d+)-(-?\d+)", line)
        d[key] = (int(m.group(1)), int(m.group(2))) if m else None
    return d


def check_skillscaling():
    nm = "Skill damage scaling (Median): BaseSynergy percent, StaticDamage skips mastery, physical magic mastery, per-level steps"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    try:
        skills, by_name = _sd_load()
    except Exception as e:
        return add(nm, "BLOCKED", "tables not readable: %r" % (e,))
    has_ele = lambda s: s["emax"] > 0 or s["emin"] > 0 or any(s["emaxst"])  # noqa: E731
    has_phys = lambda s: s["pmax"] > 0 or any(s["pmaxst"])  # noqa: E731
    active = lambda s: s["passive"] in ("", "0")  # noqa: E731  (a passive-flagged skill keeps D2R's physical function)
    pick = lambda pred, n=1: [i for i in sorted(skills) if pred(skills[i])][:n]  # noqa: E731
    elem_ok = lambda s: has_ele(s) and s["etype"] in _SD_MASTERY_TYPES  # noqa: E731
    phys_ok = lambda s: has_phys(s) and not has_ele(s) and s["srcdam"] == 0 and active(s)  # noqa: E731
    syn_ele = pick(lambda s: s["flags"] == 1 and elem_ok(s), 2)
    syn_phys = pick(lambda s: s["flags"] == 1 and phys_ok(s))
    static_ele = pick(lambda s: s["flags"] == 2 and elem_ok(s))
    static_phys = pick(lambda s: s["flags"] == 2 and phys_ok(s))
    plain_ele = pick(lambda s: s["flags"] == 0 and elem_ok(s) and not s["ecalc"], 2)
    plain_phys = pick(lambda s: s["flags"] == 0 and phys_ok(s) and not s["pcalc"], 2)
    plain_weapon = pick(lambda s: s["flags"] == 0 and s["srcdam"] != 0 and not has_ele(s) and active(s) and not s["pcalc"], 2)
    blvl = lambda s: [n for n in re.findall(r"skill\('([^']+)'\.blvl\)", s["ecalc"]) if n in by_name]  # noqa: E731
    calc_ele = pick(lambda s: elem_ok(s) and active(s) and blvl(s), 8)  # synergy formulas over other skills' levels
    # a worn item of an earlier check (skillstarts leaves a random amulet and ring on the character) can carry a mastery of its own:
    # one full group run read "mastery stat of ltng read 6, set 0" from it. The check measures the stats it sets, nothing else.
    for loc in ("rhand", "lhand", 1, 2, 3, 6, 7, 8, 9, 10, 11, 12):
        H("unequip %s" % loc)
    groups = [("BaseSynergy elemental", syn_ele), ("BaseSynergy physical", syn_phys), ("StaticDamage elemental", static_ele),
              ("StaticDamage physical", static_phys), ("plain elemental", plain_ele), ("plain physical", plain_phys),
              ("synergy-formula elemental", calc_ele[:2])]
    keep = {s: rd("player", s) for s in (1, 12, 514) + _SD_MASTERY_STATS}
    log, bad, checked = [], [], 0

    def expect(sid, d, lvl, mastery):
        """Median's value for one skill: table columns plus the inputs `skilldmg` printed for the player."""
        s = skills[sid]
        syn = _sd_base_synergy(d["clvl"], d["energy"], d["stat514"]) if s["flags"] & 1 else 0
        m_ele = d["masteryElem"] if mastery and not s["flags"] & 2 else 0
        m_phys = d["masteryMagic"] if not s["flags"] & 2 else 0
        out = {"baseSyn": syn}
        if has_ele(s):
            out["ele"] = (_sd_elemental(s["emin"], s["eminst"], s["shift"], lvl, d["calcElem"] + syn, m_ele),
                          _sd_elemental(s["emax"], s["emaxst"], s["shift"], lvl, d["calcElem"] + syn, m_ele))
        if has_phys(s):
            out["phys"] = (_sd_physical(s["pmin"], s["pminst"], lvl, s["shift"], d["calcPhys"] + syn, m_phys),
                           _sd_physical(s["pmax"], s["pmaxst"], lvl, s["shift"], d["calcPhys"] + syn, m_phys))
        return out

    try:
        for gname, ids in groups:
            if not ids:
                bad.append("no %s skill in the tables" % gname)
        scenarios = ((1, 0, 0, 0), (40, 150, 0, 25), (100, 300, 600, 40), (150, 1000, 5000, 60))  # clvl, energy, stat 514, mastery
        for clvl, energy, e514, mast in scenarios:
            setstat("player", 12, clvl)
            setstat("player", 1, energy)
            setstat("player", 514, e514)
            for st in _SD_MASTERY_STATS:
                setstat("player", st, mast)
            for gname, ids in groups:
                for sid in ids:
                    s = skills[sid]
                    for lvl in (1, 2, 8, 9, 16, 17, 22, 23, 28, 29, 45):
                        for mastery in ((True, False) if lvl in (1, 29) else (True,)):
                            d = _sd_query(sid, lvl, mastery)
                            if d is None or (d["ele"] is None and d["phys"] is None):
                                bad.append("skilldmg %d %d failed" % (sid, lvl))
                                continue
                            want = expect(sid, d, lvl, mastery)
                            problems = []
                            if d["flags"] != s["flags"]:
                                problems.append("plugin flags %d, skills2 %d" % (d["flags"], s["flags"]))
                            if want["baseSyn"] != d["baseSyn"]:
                                problems.append("BaseSynergy %d, formula %d" % (d["baseSyn"], want["baseSyn"]))
                            if has_ele(s) and d["masteryElem"] != mast:
                                problems.append("mastery stat of %s read %d, set %d" % (s["etype"], d["masteryElem"], mast))
                            if has_phys(s) and d["masteryMagic"] != mast:
                                problems.append("stat 357 read %d, set %d" % (d["masteryMagic"], mast))
                            for key in ("ele", "phys"):
                                if key in want and tuple(d[key]) != want[key]:
                                    problems.append("%s %s, Median's formula %s" % (key, d[key], want[key]))
                            checked += 1
                            if problems or (lvl in (1, 9, 29) and mastery and clvl in (1, 100)):
                                log.append("%s %s(%d) L%d clvl %d energy %d stat514 %d mastery %d%s: ele %s phys %s (calc %d/%d, synergy %d)%s" % (
                                    gname, s["name"], sid, lvl, clvl, energy, e514, mast, "" if mastery else " (nomastery)", d["ele"],
                                    d["phys"], d["calcElem"], d["calcPhys"], d["baseSyn"], " PROBLEM: " + "; ".join(problems) if problems else ""))
                            if problems:
                                bad.append(log[-1])
        # where Median's rules change nothing (no synergy flag, no mastery) the plugin must give D2R's own numbers
        setstat("player", 12, 30)
        setstat("player", 1, 50)
        for st in _SD_MASTERY_STATS:
            setstat("player", st, 0)
        same = 0
        for sid in plain_ele + plain_phys + plain_weapon:
            for lvl in (1, 10, 25):
                d = _sd_query(sid, lvl, True)
                if d is None:
                    bad.append("skilldmg %d %d failed" % (sid, lvl))
                    continue
                same += 1
                s = skills[sid]
                if has_ele(s) and d["ele"] != d["orig_ele"]:
                    bad.append("plain elemental %s L%d: plugin %s, D2R's own %s" % (s["name"], lvl, d["ele"], d["orig_ele"]))
                if (has_phys(s) or sid in plain_weapon) and d["phys"] != d["orig_phys"]:
                    bad.append("plain physical %s L%d: plugin %s, D2R's own %s" % (s["name"], lvl, d["phys"], d["orig_phys"]))
        log.append("%d plain-skill samples compared with D2R's own functions (%s)" % (same, ", ".join(skills[i]["name"] for i in plain_ele + plain_phys + plain_weapon)))
        # synergy: raising a skill that a synergy formula names raises the percent column, and the damage follows
        setstat("player", 12, 60)
        syn_done = 0
        for sid in calc_ele:
            s = skills[sid]
            names = blvl(s)
            src = by_name[names[0]]
            low = _setskill(src, 1)
            a = _sd_query(sid, 10, True)
            high = _setskill(src, 12)
            b = _sd_query(sid, 10, True)
            if a is None or b is None or low is None or high is None:
                bad.append("synergy test of %s from %s: setskill / skilldmg failed (%s %s)" % (s["name"], names[0], low, high))
                continue
            wa, wb = expect(sid, a, 10, True), expect(sid, b, 10, True)
            log.append("synergy %s(%d) from %s level %s -> %s: percent column %d -> %d, elemental %s -> %s (formula %s -> %s)" % (
                s["name"], sid, names[0], low, high, a["calcElem"], b["calcElem"], a["ele"], b["ele"], wa["ele"], wb["ele"]))
            syn_done += 1
            if b["calcElem"] <= a["calcElem"] or tuple(a["ele"]) != wa["ele"] or tuple(b["ele"]) != wb["ele"] or b["ele"][1] <= a["ele"][1]:
                bad.append(log[-1])
            if syn_done >= 3:
                break
        if not syn_done:
            bad.append("no skill with a skill() synergy formula could be tested")
    finally:
        for st, v in keep.items():
            if v is not None:
                setstat("player", st, v)
    add(nm, "PASS" if not bad and checked else "FAIL",
        ("%d samples at 11 skill levels and 4 character setups (%s) equal Median's formula computed from the tables; %d synergy raises followed" % (
            checked, ", ".join("%s: %s" % (n, "/".join(skills[i]["name"] for i in ids)) for n, ids in groups), syn_done))
        if not bad and checked else "; ".join(bad[:8]), [], log)



def _item_id(lines):
    m = re.search(r"item id=(\d+)", " ".join(lines))
    return int(m.group(1)) if m else None


def _iflags(item_id, unid=False):
    """`iflags`: the item's flag word, mode, quantity, durability (dict of ints) or None."""
    ok, lines = H("iflags %d%s" % (item_id, " unid" if unid else ""))
    m = next((l for l in lines if l.startswith("iflags ")), None)
    if not ok or m is None:
        print("iflags %d: %s %s" % (item_id, ok, lines[-2:]))
        return None
    return {k: int(v, 16) if v.startswith("0x") else int(v) for k, v in kv(m).items()}


def check_nodurability():
    """Audit IT1 / IT2 (Median: no durability, no quantity use): worn weapon and armour keep their durability through
    many melee wear steps (harness `wear`, the function behind every hit) and a throwing stack keeps its quantity through
    real throws (cast of the Throw skill, id 2)."""
    nm = "No durability loss and no quantity use (audit IT1, IT2; plugin parts durability + quantity)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    fight_ready()
    god(False)
    log, notes, good = [], [], True
    H("packclear")  # room in the backpack: an unequip into a full backpack fails and the hand stays occupied
    for slot in ("rhand", "lhand", "torso"):
        H("unequip " + slot)
    # hfh is a quest item that D2R's place function refuses once the character's quest state says its quest is done (see
    # check_statcols): fall back to ordinary weapons (115 axe, bsd broad sword)
    for code in ("hfh", "115", "bsd"):
        ok, l1 = H("equip %s q=2 rhand" % code)
        log += l1
        if ok and _item_id(l1):
            break
        H("unequip rhand")
    ok2, l2 = H("equip fld q=2 torso")
    log += l2
    weapon, armour = _item_id(l1), _item_id(l2)
    if not (ok and ok2 and weapon and armour):
        return add(nm, "BLOCKED", "could not equip a test weapon (hfh, 115, bsd) / armour fld: %s" % " | ".join((l1 + l2)[-3:]), [], log)
    w0, a0 = _iflags(weapon), _iflags(armour)
    log.append("before: weapon %s armour %s" % (w0, a0))
    if not w0 or not a0 or w0["maxdurability"] <= 0 or a0["maxdurability"] <= 0:
        return add(nm, "BLOCKED", "the test items have no durability to lose (weapon %s, armour %s)" % (w0, a0), [], log)
    mon = spawn_attacker(1)
    if mon is None:
        return add(nm, "BLOCKED", "no monster to hit", [], log)
    boosted = {}
    for st, val in ((0, 600), (2, 600), (12, 60)):  # strength, dexterity, level: the Throw skill checks the weapon's requirements
        boosted[st] = rd("player", st)
        setstat("player", st, val)
    # 2 x 300 wear steps: weapon (player attacks) and armour (monster attacks); the wear proc is 4 - 10 percent, so a
    # build that wears items loses dozens of points while this one must not lose one
    _, l3 = H("wear player %s 300" % mon, 60)
    _, l4 = H("wear %s player 300" % mon, 60)
    log += l3 + l4
    w1, a1 = _iflags(weapon), _iflags(armour)
    log.append("after: weapon %s armour %s" % (w1, a1))
    dur_ok = bool(w1 and a1) and w1["durability"] == w0["durability"] and a1["durability"] == a0["durability"]
    good = good and dur_ok
    notes.append("durability weapon %s -> %s, armour %s -> %s after 600 wear steps" % (
        w0["durability"], w1 and w1["durability"], a0["durability"], a1 and a1["durability"]))
    # get-hit: real monsters (SUnitDmg 0x44b2b0 -> 0x4526c0 -> the dispatcher 0x441b10) hit the armed character for a while.
    # The life lost shows that hits landed; the worn armour must keep its durability. This leg alone does not tell the part from
    # D2R: with the part off (control run) the armour did not wear down in 25 s of real hits either (613 life lost), the `wear`
    # step above (the same call SUnitDmg makes, 0x4526c0) is what shows the part (off: armour 48 -> 20).
    # Normal-difficulty level-1 skeletons almost never hit a level-150 character (measured: 0 - 1 life points in 20 s), so the
    # attackers are spawned under the Hell override (`h difficulty 2`; the same monsters took 13000 life in 20 s)
    setstat("player", 7, BIG_LIFE)
    setstat("player", 6, BIG_LIFE)
    H("difficulty 2")
    for _ in range(3):
        spawn_attacker(1)
    time.sleep(2)
    life0 = rd("player", 6) or 0
    a2, t_end, lost = _iflags(armour), time.time() + 25, 0
    while time.time() < t_end:
        time.sleep(2.5)
        now = rd("player", 6) or 0
        lost += max(0, life0 - now)
        life0 = now
        if now < BIG_LIFE // 2:
            setstat("player", 6, BIG_LIFE)
            life0 = BIG_LIFE
    a3 = _iflags(armour)
    kill_all_near()
    H("difficulty 0")
    log.append("get-hit: armour %s -> %s, life lost %d raw in 25 s" % (a2, a3, lost))
    hit_ok = bool(a2 and a3) and a3["durability"] == a2["durability"] and lost >= 256 * 20
    good = good and hit_ok
    notes.append("real monster hits: armour %s -> %s, %d life lost%s" % (
        a2 and a2["durability"], a3 and a3["durability"], lost >> 8, "" if lost >= 256 * 20 else " (too few hits landed to judge)"))
    # quantity: real throws
    H("unequip rhand")
    ok, l5 = H("equip tax q=2 rhand")
    log += l5
    knives = _item_id(l5)
    q0 = _iflags(knives) if knives else None
    if not ok or not q0 or q0["quantity"] <= 1:
        notes.append("throwing knives not usable here (%s)" % " | ".join(l5[-2:]))
        good = False
    else:
        boosted = {}
        for st, val in ((0, 600), (2, 600), (12, 60)):  # strength, dexterity, level: Throw checks the weapon's requirements
            boosted[st] = rd("player", st)
            setstat("player", st, val)
        H("setskill 2 1")
        throws = 0  # casts the game accepted with the skill usable (code 0) and the unit in a cast mode
        for _ in range(14):
            H("moveto nearest")
            time.sleep(0.4)
            okc, lc = H("cast 2 nearest")
            log += lc
            if okc and "usable=0" in " ".join(lc):
                throws += 1
            time.sleep(1.2)
            if throws >= 4:
                break
            if not okc or not hstate()["mons"]:
                spawn_attacker(1)
        q1 = _iflags(knives)
        qty_ok = bool(q1) and q1["quantity"] == q0["quantity"]
        good = good and qty_ok and throws > 0
        notes.append("quantity %s -> %s after %d accepted throws (Throw usable)" % (q0["quantity"], q1 and q1["quantity"], throws))
        for st, val in boosted.items():
            if val is not None:
                setstat("player", st, val)
    kill_all_near()
    for slot in ("rhand", "torso"):
        H("unequip " + slot)
    add(nm, "PASS" if good else "FAIL", "; ".join(notes), [], log)



REPAIR_STRIP = (110, 642, 572, 706)  # vendor panel (1600 x 900 client): between the item grid and the panel's lower edge, where the repair buttons sit


def _panel_diff(a, b, box=REPAIR_STRIP):
    """Mean absolute pixel difference (0-255) of two client grabs inside box."""
    from PIL import ImageChops, ImageStat
    d = ImageChops.difference(a.convert("RGB").crop(box), b.convert("RGB").crop(box))
    return sum(ImageStat.Stat(d).mean) / 3.0


def _desc_lines(item_id, eth=False):
    """`itemdesc`: the lines of D2R's own item description of the item (`eth`: as an ethereal item), colour codes stripped (None
    when the verb fails)."""
    ok, lines = H("itemdesc %d%s" % (item_id, " eth" if eth else ""))
    if not ok:
        return None
    return [re.sub(r"[\ue000-\uf8ff].", "", re.sub(r"^itemdesc id=\d+ line \d+: ", "", l)) for l in lines if re.match(r"itemdesc id=\d+ line \d+: ", l)]


def check_nodurabilityui():
    """Audit IT1 (what Median shows of durability: nothing). Items keep the durability stats Median has (stat 0x48 / 0x49, ethereal
    75%), but D2R's item description has no `Durability: x of y` line (plugin part durabilitytip), an ethereal item reads
    `Ethereal` (Median's text, not `Ethereal (Cannot be Repaired)`), Charsi's menu line is `trade` (0xd44) not `trade/repair`
    (0xd06) and her panel is the plain trade panel, not the repair panel (plugin part repairui)."""
    nm = "No durability in the UI: no tooltip line, ethereal text, no repair line or repair panel (audit IT1; plugin parts durabilitytip + repairui)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    log, notes, bad, shots = [], [], [], []
    H("packclear")
    # 1. descriptions of an armour, a weapon, an ethereal armour, a magic armour
    made, cells = {}, {}
    for key, cmd in (("armour", "item fld q=2 inv"), ("weapon", "item bsd q=2 inv"), ("magic armour", "item fld q=4 inv"), ("ethereal armour", "item fld q=2 inv")):
        ok, l = H(cmd)
        log += l
        iid = _item_id(l)
        if not ok or iid is None:
            bad.append("%s: could not be made (%s)" % (key, " | ".join(l[-2:])))
            continue
        made[key] = iid
        m = re.search(r"item id=\d+ .* x=(\d+) y=(\d+)", " ".join(l[:1]))
        if m:
            cells[key] = (int(m.group(1)), int(m.group(2)))
    descs = {}
    for key, iid in made.items():
        fl = _iflags(iid)
        d = _desc_lines(iid, eth=(key == "ethereal armour"))
        log.append("%s id %d: stats %s; description %s" % (key, iid, fl and {k: fl[k] for k in ("durability", "maxdurability")}, d))
        if d is None or not d:
            bad.append("%s: no description text (itemdesc failed)" % key)
            continue
        descs[key] = d
        if not fl or fl["maxdurability"] <= 0 or fl["durability"] <= 0:
            bad.append("%s: Median keeps the durability stats, this item has %s" % (key, fl and (fl["durability"], fl["maxdurability"])))
        hit = [x for x in d if re.search(r"durability|repair|indestructible", x, re.I)]
        if hit:
            bad.append("%s: the description still mentions durability/repair: %s" % (key, hit))
    eth = descs.get("ethereal armour")
    if eth is not None:
        if not any(x.strip().lower().startswith("ethereal") for x in eth):
            bad.append("ethereal armour: no `Ethereal` line in %s" % eth)
        if any("cannot be repaired" in x.lower() for x in eth):
            bad.append("ethereal armour still says Cannot be Repaired: %s" % eth)
    notes.append("descriptions (%s): %s" % (", ".join(sorted(descs)), "; ".join("%s: %d lines" % (k, len(v)) for k, v in sorted(descs.items()))))
    # the real tooltip on screen (for the human): hover the armour and the weapon in the inventory with the plugin's virtual cursor
    g.key("i")
    time.sleep(1.5)
    for key in ("armour", "weapon"):
        if key not in cells:
            continue
        fx, fy = (1055 + (cells[key][0] + 0.5) * 27.6) / 1600.0, (381 + (cells[key][1] + 1.0) * 26.0) / 900.0  # the 15 x 10 backpack grid of the 1600 x 900 client
        g.click(fx, fy, move_only=True)
        time.sleep(1.0)
        g.click(fx + 0.002, fy + 0.002, move_only=True)  # the tooltip wants a second mouse move over the item and a dwell
        time.sleep(2.0)
        shots.append(sh("nodur_tooltip_%s" % key))
    g.key("esc")
    time.sleep(0.5)
    # 2. Charsi: the menu line and the panel
    panels = {}
    for cls, nm_ in ((154, "charsi"), (147, "gheed")):
        H("packclear")
        menu = npc_menu_near(cls)
        if menu is None:
            bad.append("%s: no menu" % nm_)
            continue
        log += menu
        lines = [l for l in menu if re.match(r"\s*line \d+ ", l)]
        ids = [int(m.group(1), 16) for l in lines for m in [re.search(r"string=0x([0-9a-f]+)", l)] if m]
        notes.append("%s menu string ids %s" % (nm_, ", ".join("0x%x" % i for i in ids)))
        if 0xd06 in ids:
            bad.append("%s: the menu still has the trade/repair line (0xd06): %s" % (nm_, ids))
        if cls == 154 and 0xd44 not in ids:
            bad.append("charsi: the menu has no plain trade line (0xd44): %s" % ids)
        shots.append(sh("nodur_%s_menu" % nm_))
        trade = ids.index(0xd44) if 0xd44 in ids else (ids.index(0xd06) if 0xd06 in ids else 1)
        H("menu %d" % trade)
        for _ in range(6):
            time.sleep(2)
            if trade_panel_open():
                break
        else:
            bad.append("%s: the trade panel did not open" % nm_)
        time.sleep(1.5)
        panels[nm_] = g.grab_client(g.need_window())
        shots.append(sh("nodur_%s_panel" % nm_))
        g.click(*TRADE_CLOSE)
        time.sleep(1.0)
        close_menu()
    if "charsi" in panels and "gheed" in panels:
        diff = _panel_diff(panels["charsi"], panels["gheed"])
        notes.append("panel strip below the grid, Charsi vs Gheed: mean pixel difference %.2f (repair panel mode: far above 0, plain trade panel: ~0)" % diff)
        log.append("repair strip diff charsi/gheed: %.3f" % diff)
        if diff > 2.5:
            bad.append("Charsi's panel differs from the plain trade panel below the grid (diff %.2f): the repair mode is still on" % diff)
    add(nm, "PASS" if not bad else "FAIL", "; ".join(notes) + ("; PROBLEMS: " + "; ".join(bad) if bad else ""), shots, log)


def _quest_bit(q, bit):
    ok, lines = H("quest %d %d get" % (q, bit))
    return ok and any(re.search(r"= 1\b", l) for l in lines if l.startswith("quest"))


def check_potionamounts():
    """Audit item 11 (Median patches the Potion of Life to +50 life, was +20, and Lam Esen's Tome to 10 stat points, was 5): the
    game's own grant steps (harness `rewardstep`) run on the player; the plugin part `potionamounts` patches the two immediates."""
    nm = "Potion of Life +50 life, Lam Esen's Tome 10 stat points (audit item 11; plugin part potionamounts)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    log, notes, good = [], [], True
    life7, pts4 = rd("player", 7), rd("player", 4)
    ok, l1 = H("rewardstep potion")
    log += l1
    m = re.search(r"gained=(-?\d+) points=(-?\d+)", " ".join(l1))
    potion = int(m.group(2)) if m else None
    notes.append("Potion of Life: +%s max life (Median 50, D2R 20)" % potion)
    good = good and ok and potion == 50
    if life7 is not None:
        setstat("player", 7, life7)
    had = _quest_bit(17, 1)
    H("quest 17 1 set")
    ok, l2 = H("rewardstep tome")
    log += l2
    m = re.search(r"gained=(-?\d+)", " ".join(l2))
    tome = int(m.group(1)) if m else None
    notes.append("Lam Esen's Tome: +%s stat points (Median 10, D2R 5)" % tome)
    good = good and ok and tome == 10
    if pts4 is not None:
        setstat("player", 4, pts4)
    if not had:
        H("quest 17 1 clear")
    add(nm, "PASS" if good else "FAIL", "; ".join(notes), [], log)


def check_manarules():
    """Audit item 15 (Median's stamina and mana recovery, D2Sigma 0x100a1f90 / 0x100a1b50; plugin parts stamina + manaregen):
    stamina per frame standing 100%, walking 75% (D2R 50%); state 136 (Stamina Shrine, "infinite stamina") fills the bar; a run
    in the Rogue Encampment costs no stamina (vanilla's town rule); a mana pool smaller than the frame count regenerates
    nothing (D2R raises the base to 1)."""
    nm = "Stamina and mana recovery rules (audit item 15; plugin parts stamina + manaregen)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    fight_ready()
    log, notes, bad = [], [], []
    full = rd("player", 11) or 0
    bonus = rd("player", 28) or 0
    point = full >> 8
    step = point + point * bonus // 100

    def per_frame(rows, mode):
        pr = [(a, b) for a, b in _pairs(rows, mode) if a[4] + step * 4 < full]
        frames = sum(b[0] - a[0] for a, b in pr)
        gain = sum(b[4] - a[4] for a, b in pr)
        return (gain / frames if frames else None), frames

    # 1. standing in the field: max/256 raw per frame (x (100 + stat 28)%); walking 75% of it
    setstat("player", 10, 0)
    stand = []
    t0 = time.time()
    while time.time() - t0 < 4:
        stand.append(_sample())
        time.sleep(0.2)
    log += ["stand " + " ".join(map(str, r)) for r in stand]
    rate, frames = per_frame(stand, (1, 5))  # 5 (town neutral) is what a character has in the field until it moves after arriving
    notes.append("standing: %s raw/frame over %d frames (Median %d = max %d / 256 x (100+%d)%%)" % (
        ("%.1f" % rate) if rate is not None else "?", frames, step, point, bonus))
    if rate is None or abs(rate - step) > 0.05 * step:
        bad.append("standing recovery %s raw/frame, Median %d" % (rate, step))
    walk = _sprint_leg(0, True, 4)
    log += ["walk " + " ".join(map(str, r)) for r in walk]
    rate, frames = per_frame(walk, 2)
    want = step * 75 // 100
    notes.append("walking: %s raw/frame over %d frames (Median 75%% = %d, D2R 50%% = %d)" % (
        ("%.1f" % rate) if rate is not None else "?", frames, want, step // 2))
    if rate is None or frames < 10 or abs(rate - want) > 0.15 * want:  # a sample pair can straddle a standing frame (100%)
        bad.append("walking recovery %s raw/frame over %d frames, Median %d" % (rate, frames, want))

    # 2. state 136 fills the bar at once, whatever the mode
    H("move %d %d" % (walk[-1][1], walk[-1][2]))
    setstat("player", 10, 0)
    ok, ls = H("setstate player 136 1")
    log += ls
    time.sleep(1.0)
    filled = rd("player", 10) or 0
    H("setstate player 136 0")
    notes.append("state 136: stamina 0 -> %d of %d after 1 s" % (filled >> 8, point))
    if not ok or filled < full:
        bad.append("state 136 left the stamina at %d of %d" % (filled, full))

    # 3. a run in a town costs no stamina (infinite stamina in the Rogue Encampment)
    goto(1)
    close_menu()
    run = _sprint_leg(full, False, 5)
    log += ["town run " + " ".join(map(str, r)) for r in run]
    ran = [r for r in run if r[3] == 3]
    lowest = min((r[4] for r in run), default=0)
    notes.append("run in town: %d samples running, stamina lowest %d of %d" % (len(ran), lowest >> 8, point))
    if len(ran) < 3:
        notes.append("(too few running samples to judge the town drain)")
        bad.append("no run in the town to measure")
    elif lowest < full - 4 * step:
        bad.append("a run in town drained the stamina to %d of %d" % (lowest >> 8, point))

    # 4. a mana pool below the frame count regenerates nothing (Median's base has no floor of 1)
    fight_ready()
    saved = {s_: rd("player", s_) for s_ in (8, 9, 26, 27)}
    try:
        setstat("player", 9, 40)
        setstat("player", 8, 0)
        setstat("player", 26, 0)
        setstat("player", 27, 0)
        time.sleep(2.5)
        mana = rd("player", 8) or 0
        notes.append("mana pool 40 raw, bonuses off: %d raw after 2.5 s (Median 0, D2R +1 per frame)" % mana)
        if mana > 2:
            bad.append("a pool of 40 raw regenerated to %d (D2R's floor of 1 per frame)" % mana)
    finally:
        for s_, v in saved.items():
            if v is not None:
                setstat("player", s_, v)
    add(nm, "PASS" if not bad else "FAIL", "; ".join(notes) + ("; BAD: " + " | ".join(bad) if bad else ""), [], log)


def check_autoid():
    """Audit IT3 (Median: the magic, rare, set and unique generators push 1 into SetItemFlag(0x10 identified), D2Game 0x104c1,
    0x15443, 0x13daa and the unique picker): monster drops of those qualities lie on the ground identified. Real drops: the
    harness `item` / `itemroll` go through MakeItem (0x43d530), which identifies its item itself, so only monster kills show
    what the generator does. Andariel (class 156) drops magic and rare items; `dump ground` prints quality and the flag."""
    nm = "Items drop identified (audit IT3; plugin part autoid in item_gen.cpp)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    fight_ready()
    log, seen = [], set()

    def ground():
        out = []
        for l in H("dump ground")[1]:
            if l.startswith("ground ") and re.search(r"mode=[35] ", l):
                d = {k: v for k, v in re.findall(r"(\w+)=(-?\d+)", l)}
                if int(d["id"]) not in seen:
                    out.append(d)
        return out

    seen.update(int(d["id"]) for d in ground())
    drops = []
    for _ in range(14):
        H("spawn 156")
        ok, l = H("kill nearest 156")
        log += l
        time.sleep(1.5)
        for d in ground():
            seen.add(int(d["id"]))
            drops.append(d)
        if len([d for d in drops if 4 <= int(d["quality"]) <= 7]) >= 6:
            break
    kill_all_near()
    fancy = [d for d in drops if 4 <= int(d["quality"]) <= 7]
    ident = [d for d in fancy if d["identified"] == "1"]
    plain = [d for d in drops if int(d["quality"]) in (1, 2, 3)]
    pident = [d for d in plain if d["identified"] == "1"]
    note = "%d drops: %d magic/set/rare/unique, %d of them identified; %d low/normal/superior, %d identified" % (
        len(drops), len(fancy), len(ident), len(plain), len(pident))
    log.append(note)
    if len(fancy) < 3:
        return add(nm, "BLOCKED", "too few magic or better drops to judge (%s)" % note, [], log)
    add(nm, "PASS" if len(ident) == len(fancy) else "FAIL", note, [], log)


def _intown_skills(limit=60):
    """Skills of the built skills.txt that may be cast in town (InTown), can be selected (left / right skill) and cost mana
    (mana column), without a restrict value, by required level: [(id, name, mana, lvlmana, manashift)]."""
    import csv
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "mod", "data", "global", "excel", "skills.txt")
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        rows = list(csv.reader(f, delimiter="	"))
    h = rows[0]
    col = {c: h.index(c) for c in ("skill", "*Id", "InTown", "mana", "leftskill", "rightskill", "restrict", "reqlevel", "lvlmana", "manashift")}
    out = []
    for r in rows[1:]:
        if len(r) < len(h) or r[col["InTown"]] != "1" or r[col["restrict"]] or r[col["mana"]] in ("", "0"):
            continue
        if r[col["leftskill"]] != "1" and r[col["rightskill"]] != "1":
            continue
        out.append((int(r[col["reqlevel"]] or 0), int(r[col["*Id"]]), r[col["skill"]], r[col["mana"]], r[col["lvlmana"]], r[col["manashift"]]))
    out.sort()
    return [(i, n, m, lm, sh) for _lv, i, n, m, lm, sh in out[:limit]]


def drop_cursor_item(log):
    """Skills cannot be used while an item is held on the cursor (0x4249f0 "busy"): drop it (client packet 0x17)."""
    ok, lines = H("cursor")
    log.extend(lines)
    m = re.search(r"cursor id=(\d+)", " ".join(lines))
    if m:
        H("pkt 17 " + " ".join("%02x" % b for b in struct.pack("<I", int(m.group(1)))))
        time.sleep(1.0)
        log.extend(H("cursor")[1])


def check_townmana():
    """Audit SK3 (P2.1.0): skills cost no mana in a town. An InTown skill that costs mana (the first of skills.txt the game
    accepts as a cast) cast in the Rogue Encampment leaves the mana alone, cast in the Blood Moor it costs its normal price."""
    nm = "Free mana in town (audit SK3; plugin part townmana)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    log, notes = [], []
    saved = {}

    def prep(skill):
        for s_ in (9, 8, 12):
            if s_ not in saved:
                saved[s_] = rd("player", s_)
        setstat("player", 12, 60)  # the skills' level requirements
        setstat("player", 9, 5000 * 256)
        setstat("player", 8, 5000 * 256)
        H("setskill %d 5" % skill)

    def cast_mana(skill):
        # the mana of a cast is charged when its action starts and regenerated within a few frames: the plugin samples the
        # player's mana on every server frame (`manamin`), the lowest value since the reset is the cost
        H("manamin reset")
        ok, lines = H("cast %d self" % skill)
        log.extend(lines)
        time.sleep(2.0)
        _, ml = H("manamin")
        log.extend(ml)
        log.extend(H("manacharge")[1])
        m = re.search(r"manamin min=(-?\d+) max=(-?\d+)", " ".join(ml))
        # the pool was filled to its maximum before the cast, so the highest value seen is the start
        return (ok and "usable=0" in " ".join(lines)), (int(m.group(2)) if m else None), (int(m.group(1)) if m else None)

    goto(1)
    close_menu()
    drop_cursor_item(log)
    skill, t_ok, t0, t1 = None, False, None, None
    tried = []
    for cand, cname, *_cost in _intown_skills():
        prep(cand)
        t_ok, t0, t1 = cast_mana(cand)
        tried.append("%d %s" % (cand, cname))
        if t_ok:
            skill = cand
            break
    if skill is None:
        return add(nm, "BLOCKED", "no InTown skill could be cast in the Rogue Encampment (tried %s)" % ", ".join(tried), [], log)
    town_ok = t0 is not None and t1 is not None and t1 >= t0
    notes.append("town: skill %d cast OK (after %d tries), mana %s -> lowest %s" % (skill, len(tried), t0, t1))
    goto(2)
    close_menu()
    kill_all_near()
    prep(skill)
    f_ok, f0, f1 = cast_mana(skill)
    # the cost of skill 1558 at level 5 is 2 points: earlier runs read "1008" because the heat drain a former check left on the
    # character (Molten Core, check `heat`) was counted into it, so the field leg needs only a fall (the town leg then shows none)
    field_ok = f_ok and f0 is not None and f1 is not None and f0 - f1 >= 1
    notes.append("field: skill %d cast %s, mana %s -> lowest %s (cost %s)" % (skill, "OK" if f_ok else "refused", f0, f1, (f0 - f1) if f0 is not None and f1 is not None else "?"))
    kill_all_near()
    for s_, v in saved.items():
        if v is not None:
            setstat("player", s_, v)
    add(nm, "PASS" if town_ok and field_ok else "FAIL", "; ".join(notes), [], log)



def merc_dead():
    """True when the mercenary is dead (`h merc`: mode 0 / 8, or no life), None when there is none."""
    _, lines = H("merc")
    for l in lines:
        m = re.match(r"merc id=\d+ .*mode=(\d+) life=(-?\d+)/", l)
        if m:
            return int(m.group(1)) in (0, 8) or int(m.group(2)) <= 0
    return None


def revive_price_expected(level):
    """Median's mercenary revive price (D2Hirelings 0x10067450): 100 gold a level up to 105, then 250 * (level - 90)^1.5."""
    return level * 100 if level <= 105 else int(((level - 90) ** 1.5) * 250)


def check_gamble():
    name = "Gamble window (audit item 16, IT10): Gheed offers 32 items, ring and amulet among them, rare / set / unique chances from the data, a new draw on every request"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    txt = mxl_text()
    gamble_line = [ln for ln in txt.splitlines() if "gamble" in ln.lower()]
    bad, rows, log = [], [], list(gamble_line)
    if not any("gamble on" in ln for ln in gamble_line):
        bad.append("the `mxl` line does not say `gamble on`: %s" % (gamble_line or "no gamble line"))
    # open Gheed's gamble window the player's way: talk, then the Gamble line of the menu (its handler is 0x112c80)
    menu = npc_menu_near(147)
    if menu is None:
        return add(name, "BLOCKED", "Gheed's menu did not open (walked next to him, then a copy, three rounds)", log=log)
    line = None
    for ln in menu:
        m = re.search(r"line (\d+) .*handler=image\+0x112c80", ln)
        if m:
            line = int(m.group(1))
    log += menu
    if line is None:
        close_menu()
        return add(name, "FAIL", "Gheed's menu has no Gamble line (handler 0x112c80): %s" % menu[:6], log=log)
    H("menu %d" % line)
    time.sleep(2.5)
    ok, shop = H("shop 147")
    npc = next((kv(l) for l in shop if l.startswith("shop npc")), {})
    npc_id = int(npc.get("id", "0"))
    rounds, counts, firsts, same = [], {}, [], 0
    prev = None
    for i in range(13):
        if i > 0:  # the same request as the Gamble line sends: packet 0x38, kind 2, the NPC's id (little endian)
            b = [(npc_id >> (8 * k)) & 0xff for k in range(4)]
            H("pkt 38 02 00 00 00 %02x %02x %02x %02x" % tuple(b))
            time.sleep(0.6)
        ok, lines = H("gamble")
        items = [kv(l) for l in lines if l.startswith("item ")]
        n = len(items)
        codes = [it.get("code", "") for it in items]
        ids = sorted(int(it.get("id", "0")) for it in items)
        rounds.append(n)
        if i == 0:
            log += lines[:40]
        if n != 32:
            bad.append("round %d: %d offers instead of 32" % (i, n))
        if not any(c.startswith("rin") for c in codes) or not any(c.startswith("amu") for c in codes):
            bad.append("round %d: no ring or no amulet among %s" % (i, codes))
        for it in items:
            q = int(it.get("quality", "0"))
            counts[q] = counts.get(q, 0) + 1
        if len({(it.get("page"), it.get("x"), it.get("y")) for it in items}) != n:
            bad.append("round %d: two offers share a grid cell" % i)
        if prev is not None and ids == prev:
            same += 1
        prev = ids
    total = sum(counts.values())
    rare = counts.get(6, 0) * 1000 // max(total, 1)
    rows.append("offers per window %s" % sorted(set(rounds)))
    rows.append("%d offers sampled: magic %d, rare %d (%d per mille; Median's chance 250), set %d, unique %d, other %s" % (
        total, counts.get(4, 0), counts.get(6, 0), rare, counts.get(5, 0), counts.get(7, 0),
        {k: v for k, v in counts.items() if k not in (4, 5, 6, 7)}))
    if not 150 <= rare <= 350:
        bad.append("rare share %d per mille is far from Median's 250" % rare)
    if same == len(rounds) - 1:
        bad.append("the offers never changed between requests")
    rows.append("windows identical to the previous one: %d of %d" % (same, len(rounds) - 1))
    close_menu()
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows)[:900], [], log)


def check_engine_gaps():
    ctl = "recast" in set(os.environ.get("MXL_CONTROL", "").split())  # control run: the recast guard is left in (off word `recast`)
    name = "Small engine rules (audit item 21): hit 20 floor 0, recast guard of srvdofunc 47 removed (proved by a double cast), player slow floor -12 / -25 / -50 by difficulty%s" % (
        " [control: recast off]" if ctl else "")
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    txt = mxl_text()
    line = [ln for ln in txt.splitlines() if "engine gaps" in ln]
    bad, rows = [], []
    want_line = "recast guard 0x56f859 off (word)" if ctl else "recast guard 0x56f859 on"
    if not any("hit 20 floor 0x45edce on" in ln and want_line in ln and "0x449f40 on" in ln for ln in line):
        bad.append("the `mxl` engine gaps line is not as expected (%s): %s" % (want_line, line or "missing"))
    first = None
    for diff, want in ((0, -12), (1, -25), (2, -50)):
        H("difficulty %d" % diff)
        ok, lines = H("gaps")
        d = kv(lines[0]) if lines else {}
        if first is None:
            first = d
        got = d.get("slowfloor")
        rows.append("difficulty %d: slow floor %s (want %d)" % (diff, got, want))
        if got != str(want):
            bad.append("difficulty %d: slow floor %s, expected %d" % (diff, got, want))
    H("difficulty 0")
    if first:
        rows.append("hit20 bytes %s patched=%s, recast bytes %s patched=%s" % (first.get("hit20"), first.get("hit20_patched"), first.get("recast"), first.get("recast_patched")))
        if first.get("hit20_patched") != "1" or first.get("recast_patched") != ("0" if ctl else "1"):
            bad.append("a byte patch is not in memory as expected: %s" % first)
    else:
        bad.append("`h gaps` gave no answer")
    # recast: Howl of the Spirits (1404, srvdofunc 47: a timed self buff with a state) cast again while its state runs. D2R's function
    # returns at once when the caster has the state (the guard); Median's extends it. The cast needs the werewolf form state.
    log = line + ([rows[-1]] if rows else [])
    try:
        howl = _state_id("howl_of_the_spirits_state")
        were = _state_id("werewolf_form_state")
        goto(2)
        close_menu()
        setstat("player", 8, 1291520)
        H("setskill 1404 1")
        H("setstate player %d 1" % were)
        H("stat player 309 1404 set 1000")  # no cooldown between the casts
        H("setstate player %d 0" % howl)
        expiry = []
        for _ in range(3):
            H("cast 1404 self")
            time.sleep(1.0)
            on, listed, exp, frame = _has_state(howl)
            expiry.append((on, exp))
        H("setstate player %d 0" % were)
        H("setskill 1404 0")
        rows.append("Howl of the Spirits (1404) cast three times a second apart: state on / expiry frame %s" % expiry)
        log.append(rows[-1])
        grew = expiry[1][1] > expiry[0][1] and expiry[2][1] > expiry[1][1]
        if not expiry[0][0]:
            bad.append("the state is not on after the first cast: %s" % expiry)
        elif ctl:
            # with the guard in place D2R does not extend the running state: the second cast leaves the expiry as it was, or (as
            # observed) takes the state off, and the third cast starts it again
            if expiry[1][0] and expiry[1][1] != expiry[0][1]:
                bad.append("control: a second cast changed the expiry although the guard is in place: %s" % expiry)
        elif not all(e[0] for e in expiry):
            bad.append("the state is not on after a cast: %s" % expiry)
        elif not ctl and not grew:
            bad.append("the expiry did not move with the second and third cast (recast guard still in): %s" % expiry)
    except Exception as e:  # noqa: BLE001 - the byte checks above stand on their own
        bad.append("the recast cast test failed to run: %r" % (e,))
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)


CONTROL = set(os.environ.get("MXL_CONTROL", "").split())  # parts left out of this run (mxl-core-off.txt words): the check expects the old behaviour


def _ctl(word):
    return word in CONTROL


def _ground_piles():
    """{id: line} of the gold piles on the ground (`h dump ground`)."""
    out = {}
    for ln in H("dump ground")[1]:
        m = re.search(r"ground id=(\d+) code=gld ", ln)
        if m:
            out[int(m.group(1))] = ln
    return out


def _tpgold():
    m = re.search(r"teleports=(\d+) seen=(\d+) taken=(\d+)", " ".join(H("tpgold")[1]))
    return tuple(int(x) for x in m.groups()) if m else (None, None, None)


def _jump(tries=((24, 0), (-24, 0), (0, 24), (0, -24))):
    """One Teleport (skill 54, srvdofunc 179) of 24 sub-tiles to an offset that works; returns (from, to) or None."""
    for dx, dy in tries:
        p0 = hstate()["player"]
        setstat("player", 8, 1291520)
        H("cast 54 %d %d" % (p0["x"] + dx, p0["y"] + dy))
        time.sleep(1.5)
        p1 = hstate()["player"]
        if (p1["x"], p1["y"]) != (p0["x"], p0["y"]):
            return (p0["x"], p0["y"]), (p1["x"], p1["y"])
    return None


def check_teleportgold():
    """Gold auto-pickup after a teleport (Median D2AutoPickup.cpp: a teleport walks the units around the arrival point and picks up
    the gold in reach) and the X toggle (audit GS2). Teleport (skill 54, slot 179) 24 sub-tiles away from a dropped pile."""
    ctl = _ctl("teleportgold")
    name = "Gold auto-pickup after a teleport (GS2) and the X toggle%s" % (" [control: teleportgold off]" if ctl else "")
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    god(False)
    if hstate()["player"].get("area") != 2:
        goto(2)
    close_menu()
    clean_area()
    H("setskill 54 1")
    txt = mxl_text()
    line = [ln for ln in txt.splitlines() if "teleport gold" in ln]
    rows, bad, log = [], [], list(line)
    if not any(("teleport gold off" in ln) if ctl else ("teleport gold on" in ln) for ln in line):
        bad.append("the `mxl` teleport gold line is not `%s`: %s" % ("off" if ctl else "on", line or "missing"))
    if travel_counts().get("pickup") == "off":
        g.press("x")
        time.sleep(0.6)
    saved = rd("player", 14)

    strays = list(_ground_piles())  # piles that lie there before the first trial (monster drops of earlier checks)
    left_over = {}  # piles an earlier trial left on the ground: the later teleports come back into their reach

    def trial(label, gold_before, want_taken, drop=333):
        """Drop a pile where the character stands, teleport away, see whether the pile (and the gold) is gone. Piles left from
        earlier trials count as taken when they are within reach (36 sub-tiles) of the arrival point."""
        H("gold set %d 0" % gold_before)
        before = _ground_piles()
        H("item gld 14=%d ground" % drop)
        time.sleep(0.4)
        mine = [i for i in _ground_piles() if i not in before]
        t0 = _tpgold()
        j = _jump()
        time.sleep(0.5)
        gold = rd("player", 14)
        now = _ground_piles()
        left = [i for i in mine if i in now]
        t1 = _tpgold()
        near = far = 0  # earlier piles clearly in reach (<= 30) / maybe in reach (30..40)
        if j:
            for i, (px, py) in left_over.items():
                d = ((px - j[1][0]) ** 2 + (py - j[1][1]) ** 2) ** 0.5
                near += 1 if d <= 30 else 0
                far += 1 if 30 < d <= 40 else 0
        extra_ok = range(near * drop, (near + far) * drop + 1, drop) if want_taken else [0]
        # a pile of another size (gold a monster of an earlier check dropped in the area) in reach of the arrival point is picked up too
        stray = bool(strays) and want_taken
        row = "%s: pile %s, jump %s, gold %s -> %s, pile %s, counters %s -> %s, earlier piles in reach %d" % (
            label, mine, j, gold_before, gold, "left" if left else "gone", t0, t1, near)
        rows.append(row)
        log.append(row)
        if not mine:
            bad.append("%s: the pile was not dropped" % label)
        elif j is None:
            bad.append("%s: the teleport did not move the character" % label)
        elif want_taken and (left or gold - gold_before < drop or (gold - gold_before - drop) not in extra_ok and not stray):
            bad.append("%s: expected the pile taken (gold +%d), got %s" % (label, drop, row))
        elif not want_taken and (not left or gold != gold_before):
            bad.append("%s: expected the pile left alone, got %s" % (label, row))
        for i in left:
            m = re.search(r" at (\d+),(\d+)", now[i])
            if m:
                left_over[i] = (int(m.group(1)), int(m.group(2)))
        for i in list(left_over):
            if i not in now:
                del left_over[i]
        return gold

    trial("pile 24 behind the arrival point", 2000, not ctl)
    cap = (rd("player", 12) or 1) * 10000  # the most gold a character carries (engine function 0x34b320): 10000 per character level
    H("gold set %d 0" % cap)
    trial("purse full (%d gold, level %s)" % (cap, rd("player", 12)), cap, False)
    g.press("x")
    time.sleep(0.6)
    off = travel_counts().get("pickup")
    if off != "off":
        bad.append("the X key did not switch the pickup off (pickup %s)" % off)
    trial("X toggle off", 2000, False)
    g.press("x")
    time.sleep(0.6)
    if travel_counts().get("pickup") != "on":
        bad.append("the second X press did not switch the pickup on again")
    trial("X toggle on again", 2000, not ctl)
    H("gold set %d 0" % saved)
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)


def check_bendshadows():
    """Bend the Shadows (bug #57): the Necromancer's innate warp (charstats Skill 6; skill 1449 = Median 1377, srvdofunc 27 ->
    plugin slot 179 SrvDoRangedTeleport, range 14, 25 mana, cooldown group 1). Its row is leftskill-only with TargetableOnly 1, so
    as a left skill a plain click on the ground walks and Quick Cast does nothing; D2Sigma's skill picker ignored left/rightskill, so
    in Median it also sat on the right button, where a ground click casts. txt_migrate gives the active innate skills rightskill 1.
    Checks: the server cast moves the character to the point (the effect); the game selects it as the right skill; a right click on the
    ground (background mouse) warps and costs mana; Shift + left click warps too (a left click on a monster is logged only); the other innate skills
    that had neither column (mana_shield, titan_s_fortitude, mark_of_the_wild_2, vindicate_2) can be selected as the right skill."""
    name = "Bend the Shadows: the Necromancer's warp, on the right button too (#57)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    fight_ready()
    kill_all_near()
    rows, bad, log = [], [], []
    cls0 = hstate()["player"].get("class", 4)
    H("setskill 1449 1")
    H("class 2")  # the Necromancer, whose innate skill it is; a level-1 Necromancer has 75 mana, the cost is 25
    setstat("player", 9, 200 * 256)

    def warp(label, fn, want=True, wait=0.6):
        """Cooldown cleared and mana full, then `fn`; the character must (or must not) move and pay the mana."""
        H("stat player 359 1449 set 0")
        setstat("player", 8, 200 * 256)
        time.sleep(0.3)
        p0 = hstate()["player"]
        out = fn(p0)
        time.sleep(wait)
        p1 = hstate()["player"]
        a, b = (p0["x"], p0["y"]), (p1["x"], p1["y"])
        dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        rows.append("%s: %s -> %s (%.0f) %s" % (label, a, b, dist, out))
        if want and dist < 2:
            bad.append("%s: the character did not move" % label)
        time.sleep(2.5)  # the cooldown of group 1 (55 frames) and the cast mode run out
        return a, b, out

    H("skill left 1449")
    usable = _skill_usable(1449)
    rows.append("usable code %s" % usable)
    if usable != 0:
        bad.append("skill 1449 is not usable (code %s)" % usable)
    for dx, dy in ((10, 0), (0, 10)):
        a, b, out = warp("server cast at +%d,+%d" % (dx, dy), lambda p0: " | ".join(H("cast 1449 %d %d" % (p0["x"] + dx, p0["y"] + dy))[1])[-90:])
        if b != (a[0] + dx, a[1] + dy):
            bad.append("server cast at +%d,+%d: arrived at %s, not the point" % (dx, dy, b))
    right = " ".join(H("skill right 1449")[1])
    rows.append("right skill: %s" % right[-60:])
    if "active now 1449" not in right:
        bad.append("the game does not take Bend the Shadows as the right skill: %s" % right[-80:])
    else:
        _a, _b, r = warp("right click on the ground", lambda p0: _ground_click(0.62, 0.45, False, "right"))
        if not r or r[4] - r[5] < 20 * 256:
            bad.append("right click on the ground: no mana paid (modewatch %s)" % (r,))
    warp("Shift + left click on the ground", lambda p0: _ground_click(0.62, 0.45, True))
    mid = spawn_id(5)
    if mid is not None:
        time.sleep(1.0)
        st = hstate()
        mons = [m for m in st["mons"] if m["id"] == mid]
        if mons:
            fx, fy = _mon_screen(st["player"], mons[0])
            warp("left click on a monster (information: the cursor can miss a walking zombie)", lambda p0: _ground_click(fx / 1600, fy / 900, False), want=False)
    for sid, sname in ((1633, "mana_shield"), (1270, "titan_s_fortitude"), (1363, "mark_of_the_wild_2"), (1547, "vindicate_2")):
        H("setskill %d 1" % sid)
        line = " ".join(H("skill right %d" % sid)[1])
        rows.append("%s as the right skill: %s" % (sname, line[-40:]))
        if "active now %d" % sid not in line:
            bad.append("%s (%d) cannot be selected as the right skill" % (sname, sid))
    H("skill right 0")
    H("skill left 0")
    H("class %d" % cls0)
    log += rows
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)

def _skill_usable(skill):
    """`h skills` -> the usable code of one skill (0 usable, 1 not enough mana, ...) or None."""
    for ln in H("skills")[1]:
        m = re.match(r"skill id=(\d+) level=(\d+) mode=\S+ owner=\S+ usable=(-?\d+)", ln)
        if m and int(m.group(1)) == skill:
            return int(m.group(3))
    return None


def check_skillafford():
    """Skill affordability from the cost formulas (audit common2-016 (a); Median D2SkillValidation.cpp 0x100b0b60). D2R's test 0x340900
    reads the 16-bit mana columns; the 17 skills whose cost is a formula (calc7 / calc8: the summons' pet-count cost, titan's
    fortitude) read 256 (1 mana) there and are always affordable. With mana below the formula cost they must be refused."""
    ctl = _ctl("afford")
    name = "Skill affordability uses the calc7/calc8 cost formulas (common2-016)%s" % (" [control: afford off]" if ctl else "")
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(2)  # a field level of Act 1: after `mapreveal` the character stands in Lut Gholein and the formula answers the column value there
    god(False)
    close_menu()
    rows, bad, log = [], [], []
    line = [ln for ln in mxl_text().splitlines() if "skill afford" in ln]
    log += line
    if not any(("skill afford off" in ln) if ctl else ("skill afford on" in ln) for ln in line):
        bad.append("the `mxl` skill afford line is not `%s`: %s" % ("off" if ctl else "on", line or "missing"))
    max_mana = rd("player", 9) or 1291520
    saved = rd("player", 8)
    for skill in (1285, 488, 1114):  # guardian spirit, two more pet skills: cost = (level - 1) * lvlmana(pets) + mana
        H("setskill %d 10" % skill)
        ok, first, lines = hv("afford %d" % skill, "afford")
        m = re.search(r"afford=(\d) cost=(\d+) cols=(\d+)", first)
        if not m:
            bad.append("skill %d: `afford` gave no numbers: %s" % (skill, first[:120]))
            continue
        cost, cols = int(m.group(2)), int(m.group(3))
        log.append(first)
        if cost < 10 * 256 or cost <= 4 * cols or cost > max_mana // 2:
            bad.append("skill %d: formula cost %d vs the columns %d (need a clear gap and room under the mana maximum)" % (skill, cost, cols))
            continue
        seen = {}
        for label, mana in (("half the cost", cost // 2), ("twice the cost", min(cost * 2, max_mana))):
            setstat("player", 8, mana)
            ok, first, _l = hv("afford %d" % skill, "afford")
            m2 = re.search(r"afford=(\d)", first)
            seen[label] = (int(m2.group(1)) if m2 else None, _skill_usable(skill))
            log.append("%d with %s (mana set %d): %s | usable %s" % (skill, label, mana, first[:120], seen[label][1]))
        want_half = (1, 0) if ctl else (0, 1)  # (afford answer, usable code): D2R alone says affordable, the formula says no mana
        rows.append("skill %d level 10: formula cost %.1f mana, columns %.1f; at half the cost afford=%s usable=%s (want %s), at twice afford=%s usable=%s" % (
            skill, cost / 256, cols / 256, seen["half the cost"][0], seen["half the cost"][1], want_half, seen["twice the cost"][0], seen["twice the cost"][1]))
        if seen["half the cost"] != want_half:
            bad.append("skill %d: half the cost gives %s, want %s" % (skill, seen["half the cost"], want_half))
        if seen["twice the cost"] != (1, 0):
            bad.append("skill %d: twice the cost gives %s, want (1, 0)" % (skill, seen["twice the cost"]))
    setstat("player", 8, saved if saved is not None else max_mana)
    for skill in (1285, 488, 1114):
        H("setskill %d 0" % skill)
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)


def _hc_line():
    """`h hc` -> dict of the Hardcore flags (info word, hardcore bit, client flag, deaths seen / converted by the plugin)."""
    line = next((l for l in H("hc")[1] if l.startswith("hc ")), "")
    d = kv(line)
    d["line"] = line
    return d


def _hc_hard(d):
    """True when an `h hc` line says Hardcore: the info word's bit (the character's own record) or, when it looks like flags (the word of
    a client that has just joined can hold garbage), the client word's bit 0x800."""
    m = re.search(r"hc info=0x[0-9a-f]+ hardcore=(\d)", d.get("line", ""))
    word = int(d.get("client", "0"), 16)
    return bool((m and m.group(1) != "0") or (word < 0x10000 and word & 0x800))


def _d2s_status():
    """The character's status byte in the save (offset 0x14 of the D2R header: 0x04 hardcore, 0x08 died, 0x20 expansion)."""
    with open(os.path.join(SAVES, g.CHAR_NAME + ".d2s"), "rb") as f:
        return f.read(0x20)[0x14]


def check_hcdeath():
    """Hardcore death in Single Player (Median docs: a dead Hardcore character becomes Softcore; audit DC9 / HC1). D2R makes the
    dead character unplayable (died flag, locked for good). The test character is marked Hardcore with `h hc on`, killed by a
    monster's hit and respawned: the plugin must have cleared the Hardcore bits before D2R's death handlers ran, the character plays
    on and the save written by Save and Exit has the Hardcore bit (status byte 0x04) cleared."""
    ctl = _ctl("hcdeath")
    name = "Hardcore death in Single Player: the dead Hardcore character becomes Softcore%s" % (" [control: hcdeath off]" if ctl else "")
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    fight_ready()
    rows, bad, log = [], [], []
    line = [ln for ln in mxl_text().splitlines() if "hardcore death" in ln]
    log += line
    if not any(("hardcore death off" in ln) if ctl else ("hardcore death on" in ln) for ln in line):
        bad.append("the `mxl` hardcore death line is not `%s`: %s" % ("off" if ctl else "on", line or "missing"))
    status0 = _d2s_status()
    h0 = _hc_line()
    H("hc on")
    h1 = _hc_line()
    if h1.get("hardcore") != "1" or not int(h1.get("client", "0"), 16) & 0x800:
        bad.append("`hc on` did not mark the character Hardcore: %s" % h1["line"])
    atk = spawn_attacker(1)
    if atk is None:
        return add(name, "BLOCKED", "no attacker monster")
    setstat("player", 7, BIG_LIFE)
    setstat("player", 6, 256 * 100)
    ok, hline, _l = hv("hit player phys 2000000000 %s" % atk, "hit")
    for _ in range(12):
        time.sleep(1)
        if hstate()["player"].get("mode") == 17:
            break
    h2 = _hc_line()
    mode = hstate()["player"].get("mode")
    rows.append("before %s | marked %s | dead (mode %s): %s" % (h0["line"], h1["line"], mode, h2["line"]))
    log += [rows[-1], hline]
    if mode != 17:
        bad.append("the character did not die (mode %s): %s" % (mode, hline[:120]))
    if ctl:
        # D2R alone: still Hardcore after the death (and the character now unplayable): nothing converted
        if h2.get("hardcore") != "1" or h2.get("converted") != h1.get("converted"):
            bad.append("control: expected the character still Hardcore and nothing converted, got %s" % h2["line"])
        # what D2R alone writes: Save and Exit keeps the Hardcore bit (the character cannot be played again: the run ends here)
        left = leave_and_reenter()
        status1 = _d2s_status()
        rows.append("Save and Exit after the death: status byte 0x%02x -> 0x%02x (Hardcore bit 0x04 %s), re-entered: %s" % (
            status0, status1, "set" if status1 & 4 else "clear", left))
        if not status1 & 4:
            bad.append("control: the saved status byte has no Hardcore bit: 0x%02x" % status1)
        return add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)
    if _hc_hard(h2):
        bad.append("after the death the character is still Hardcore: %s" % h2["line"])
    if int(h2.get("converted", 0)) != int(h1.get("converted", 0)) + 1 or int(h2.get("deaths", 0)) != int(h1.get("deaths", 0)) + 1:
        bad.append("the plugin's counters did not each rise by one: %s -> %s" % (h1["line"], h2["line"]))
    time.sleep(6)
    revived = revive_if_dead()
    time.sleep(2)
    p = hstate()["player"]
    alive = p.get("mode") not in (0, 17)
    h3 = _hc_line()
    rows.append("respawn pressed (was dead %s), mode now %s, flags %s" % (revived, p.get("mode"), h3["line"]))
    if not alive or _hc_hard(h3):
        bad.append("the character did not come back as a Softcore player: %s" % rows[-1])
    if not leave_and_reenter():
        bad.append("Save and Exit + Play did not get back into a game")
    else:
        status1 = _d2s_status()
        h4 = _hc_line()
        # the client word (client+0x5658) of a game that has just been joined is not always the flags: runs read 0x5f8ae86f, 0xe83d1d8d
        # (and a changing 0x373611c7 before the first `hc on`), i.e. a Hardcore bit of garbage with the info word and the save clear.
        # The character's own record (info word) and the save decide; the client word counts only when it looks like flags.
        rows.append("save status byte 0x%02x -> 0x%02x (Hardcore bit 0x04 %s), after re-entering: %s" % (
            status0, status1, "set" if status1 & 4 else "clear", h4["line"]))
        if status1 & 4:
            bad.append("the saved status byte still has the Hardcore bit: 0x%02x" % status1)
        if _hc_hard(h4):
            bad.append("the re-entered character is Hardcore: %s" % h4["line"])
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)


def _modewatch():
    """`h modewatch read`: (attack modes, move modes, samples, last mode, mana at the start, lowest mana) since `modewatch start`."""
    ok, lines = H("modewatch read")
    m = re.search(r"attack=(\d+) move=(\d+) samples=(\d+) last=(-?\d+) mana=(-?\d+) min=(-?\d+)", " ".join(lines))
    return tuple(int(x) for x in m.groups()) if m else None


def _ground_click(fx, fy, shift, button="left"):
    """One left click on the ground in the game window (background input; Shift held as a window message state), watched by
    `modewatch`: the player unit's attack / walk modes and the lowest mana during the following second."""
    h = g.need_window()
    H("modewatch stop")
    H("modewatch start")
    time.sleep(0.2)
    if shift:
        g._set_mods(("shift",))
        g._post_key(h, "shift", False)
        time.sleep(0.1)
    g.click_bg(fx, fy, button)
    time.sleep(1.0)
    if shift:
        g._post_key(h, "shift", True)
        g._set_mods(())
    r = _modewatch()
    H("modewatch stop")
    return r


def check_meleenotarget():
    """Melee skills without a target (Median P2.3.0, audit SK8: most melee skills can be used with Shift and no target). D2R's own
    Shift-click does the same (the skill's start function runs at the clicked ground point and the character stands still); this
    checks it for three Median melee skills (spiral_dance 521, cherubim 548, 722) with nothing to attack in reach: with Shift held
    the character enters an attack mode and pays the skill's mana, without Shift it does not attack (it walks, or the skill is not used)."""
    name = "Melee skills without a target: Shift + click on the ground attacks (SK8)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    fight_ready()
    close_menu()
    H("packclear")
    H("unequip rhand")
    H("unequip lhand")  # no weapon: the skills need none to be usable, a bow in the hand would make them unusable
    for loc in (1, 2, 3, 6, 7, 8, 9, 10, 11, 12):  # nor a worn item of an earlier check (its mana drain / cost modifiers made the plain click pay in the full group)
        H("unequip %d" % loc)
    rows, bad, log = [], [], []
    on = [st_ for st_ in range(1, 360) if (lambda ls: any(re.search(r"hasstate %d: 1" % st_, l) for l in ls))(H("hasstate %d" % st_)[1])]
    log.append("player states on: %s; max mana %s, max life %s" % (on, rd("player", 9), rd("player", 7)))  # the long-group FAIL (mana cost on a plain click) is state dependent
    drain = []  # mana-only complaints, dropped when the pool falls by itself (idle dip above 100 points)
    for skill in (521, 548, 722):
        H("setskill %d 5" % skill)
        H("skill left %d" % skill)
        setstat("player", 8, rd("player", 9) or 1291520)  # the usable code is 1 (not enough mana) when an earlier check left the pool low
        time.sleep(0.5)
        usable = _skill_usable(skill)
        res = {}
        # the baseline: the same pool, the same watch, no click; a pool that falls by itself (a leftover of an earlier check in the full
        # group2: 1.5 thousand points in a second with the plain click too) hides the cost of the click
        setstat("player", 8, rd("player", 9) or 1291520)
        time.sleep(0.3)
        H("modewatch stop")
        H("modewatch start")
        time.sleep(1.2)
        idle = _modewatch()
        H("modewatch stop")
        idle_dip = (idle[4] - idle[5]) / 256 if idle else 0
        for label, shift in (("shift", True), ("plain", False)):
            # full mana: the pool regenerates (a few hundred points a second at 8191), so a start below the maximum refills past the
            # cost before the first sample and hides it; at the maximum the cost shows as a dip
            setstat("player", 8, rd("player", 9) or 1291520)
            time.sleep(0.3)
            res[label] = _ground_click(0.62, 0.45, shift)
            time.sleep(3.0)  # let the attack of the Shift click end before the next sample set starts
        s_, p_ = res["shift"], res["plain"]
        rows.append("skill %d (usable code %s): idle dip %.1f; Shift click -> attack modes %s, walk %s, mana %.1f -> %.1f; plain click -> attack %s, walk %s, mana lowest %.1f" % (
            skill, usable, idle_dip, s_[0] if s_ else None, s_[1] if s_ else None, (s_[4] / 256) if s_ else 0, (s_[5] / 256) if s_ else 0,
            p_[0] if p_ else None, p_[1] if p_ else None, (p_[5] / 256) if p_ else 0))
        log.append(rows[-1])
        steady = idle_dip <= 100
        if usable != 0:
            bad.append("skill %d is not usable without a weapon (code %s)" % (skill, usable))
        if not s_ or s_[0] < 1:
            bad.append("skill %d: Shift click did not attack: %s" % (skill, s_))
        elif s_[5] >= s_[4]:
            (bad if steady else drain).append("skill %d: Shift click did not spend mana: %s" % (skill, s_))
        if not p_ or p_[0] != 0:
            bad.append("skill %d: the plain click attacked: %s" % (skill, p_))
        elif p_[5] < p_[4]:
            (bad if steady else drain).append("skill %d: the plain click spent mana: %s" % (skill, p_))
    for skill in (521, 548, 722):
        H("setskill %d 0" % skill)
    if drain and not bad:
        return add(name, "PARTIAL", "the attack modes are right (Shift click attacks, the plain click does not) but the mana pool falls by itself "
                   "(idle dip above 100 points in a second, the cost cannot be told from it): %s | %s" % ("; ".join(drain), "; ".join(rows)), [], log)
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows) + ("; " + log[0] if bad else ""), [], log)


def _skills_row(skill_id):
    """{column: value} of one skills.txt row of the built mod."""
    t = _tsv(os.path.join(BUILT_EXCEL, "skills.txt"))
    head = t[0]
    for r in t[1:]:
        if len(r) > 300 and r[head.index("*Id")] == str(skill_id):
            return dict(zip(head, r))
    return {}


def _item_level_threshold(item_id, lo=1, hi=100):
    """The lowest character level at which `req player` calls the backpack item usable (the requirement function's level check:
    D2R's 0x3d4170 behind the executable's thunk 0x376de0), by bisection on stat 12. None when no level in lo..hi works."""
    def ok(level):
        setstat("player", 12, level)
        for ln in H("req player")[1]:
            if ln.startswith("req id=%d " % item_id):
                return "level=1" in ln
        return None
    if ok(hi) is not True:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def check_reqlevel():
    """Required level without the +6 oskill penalty (audit common1-013; Median's D2Common patch: "ITEMS_GetRequiredLevel no longer
    adds 6 for class-only (oskill) bonuses"). An amulet whose only property is +1 to a skill of another class (stat 97, layer =
    skill id; Teleport has no class) needs the skill's required level in Median (D2R: that plus 6). The lowest character level at
    which the item is usable is found by bisection on the level stat; the barbarian test character is of none of these classes."""
    ctl = _ctl("reqlevel")
    name = "Required level of an oskill item without the +6 (common1-013)%s" % (" [control: reqlevel off]" if ctl else "")
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    revive_if_dead()
    rows, bad, log = [], [], []
    ok, gl = H("gaps")
    sites = re.search(r"reqlevel_sites=(-?\d+)", " ".join(gl))
    log += gl[:1]
    n_sites = int(sites.group(1)) if sites else None
    if n_sites is None or (n_sites != 2 if not ctl else n_sites > 0):
        bad.append("reqlevel sites patched: %s (want %s)" % (n_sites, "none" if ctl else "2"))
    saved = rd("player", 12)
    H("packclear")
    for skill in (54, 483, 488):
        row = _skills_row(skill)
        want = int(row.get("reqlevel", "0")) + (6 if ctl else 0)
        ok, lines = H("item amu 97:%d=1 inv" % skill)
        m = re.search(r"item id=(\d+) ", " ".join(lines))
        if not m:
            bad.append("skill %d: the amulet could not be created: %s" % (skill, lines[:1]))
            continue
        iid = int(m.group(1))
        got = _item_level_threshold(iid)
        rows.append("skill %d (%s, class %r, reqlevel %s): usable from level %s (want %d)" % (skill, row.get("skill"), row.get("charclass"), row.get("reqlevel"), got, want))
        log.append(rows[-1])
        if got != want:
            bad.append(rows[-1])
        H("remove amu 1")
    setstat("player", 12, saved)
    add(name, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)


def check_cubedrop():
    """A Horadric Cube dropped with items inside (audit item 21, game6-001: D2Sigma D2Game 0xd7b75 makes the place-into-container call of
    the item-mode handler fail, so a cube dropped on the ground never takes its items back). D2R 3.3 has no such case to patch: its
    drop handler 0x4bd8f0 refuses to drop a cube that holds items (the cube stays on the cursor, the items stay in it, nothing
    reaches the ground), and an empty cube drops as usual. The check picks the cube up (packet 0x19) and drops it (0x17) with two
    items inside and again empty."""
    nm = "Cube dropped with items (game6-001): D2R refuses the drop, an empty cube drops"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    rows, bad, log = [], [], []
    H("packclear")
    H("cubeclear")
    drop_cursor_item(log)

    def cursor_id():
        m = re.search(r"cursor id=(\d+)", " ".join(H("cursor")[1]))
        return int(m.group(1)) if m else None

    def boxes_on_ground():
        return [l for l in H("dump ground")[1] if "code=box " in l and re.search(r"mode=[35] ", l)]

    H("item box inv")
    cube = next(iter(items(hstate(), "box")), None)
    if not cube:
        return add(nm, "BLOCKED", "no Horadric Cube in the backpack")
    ok1, l1 = H("item hp1 cube")
    ok2, l2 = H("item rin cube")
    inside = [i for i in hstate()["items"] if i.get("page") == 3]
    if not (ok1 and ok2) or len(inside) != 2:
        return add(nm, "BLOCKED", "could not put two items into the cube: %s %s" % (l1[:1], l2[:1]))
    g0 = len(boxes_on_ground())
    H("pkt 19 " + _le(cube["id"], cube["x"], cube["y"], 0))
    time.sleep(0.5)
    held = cursor_id()
    H("pkt 17 " + _le(cube["id"]))
    time.sleep(1.0)
    held2 = cursor_id()
    inside2 = [i for i in hstate()["items"] if i.get("page") == 3]
    g1 = len(boxes_on_ground())
    rows.append("cube with %d items: picked up (cursor %s), drop packet -> cursor %s, items still inside %d, cubes on the ground %d -> %d" % (
        len(inside), held, held2, len(inside2), g0, g1))
    if held != cube["id"]:
        bad.append("the cube did not reach the cursor (cursor %s)" % held)
    if held2 != cube["id"] or g1 != g0 or len(inside2) != len(inside):
        bad.append("the drop of the full cube was not refused: " + rows[-1])
    # the empty cube: back into the backpack, emptied, picked up, dropped
    H("pkt 18 " + _le(cube["id"], cube["x"], cube["y"], 0))
    time.sleep(0.5)
    H("cubeclear")
    H("pkt 19 " + _le(cube["id"], cube["x"], cube["y"], 0))
    time.sleep(0.5)
    held3 = cursor_id()
    H("pkt 17 " + _le(cube["id"]))
    time.sleep(1.0)
    held4 = cursor_id()
    g2 = len(boxes_on_ground())
    rows.append("empty cube: cursor %s, drop packet -> cursor %s, cubes on the ground %d -> %d" % (held3, held4, g1, g2))
    log += rows
    if held3 != cube["id"] or held4 is not None or g2 != g1 + 1:
        bad.append("the empty cube was not dropped: " + rows[-1])
    H("remove box 9")
    add(nm, "PASS" if not bad else "FAIL", "; ".join(bad + rows), [], log)


def check_mercrevive():
    name = "Mercenary revive price (Median: level x 100 to 105, 250 x (level - 90)^1.5 above)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    fight_ready()  # first: it kills everything near, the mercenary too
    if not ensure_merc():
        return add(name, "BLOCKED", "no mercenary could be hired")
    saved = rd("merc", 12)
    rows, bad, log = [], [], []
    txt = mxl_text()
    if "merc revive price on" not in txt:
        bad.append("`mxl` does not say `merc revive price on`: %s" % next((l for l in txt.splitlines() if "merc revive" in l), "-"))
    for level in (1, 80, 105, 106, 126, 150):
        ok, line, _l = hv("mercprice %d" % level, "mercprice")
        want = revive_price_expected(level)
        m = re.search(r"price=(-?\d+) median=(-?\d+)", line)
        got = int(m.group(1)) if m else None
        rows.append("level %d: D2R's price function says %s (want %d)" % (level, got, want))
        log.append(line)
        if not ok or got != want:
            bad.append(rows[-1])
    setstat("merc", 12, saved or 1)
    # the price the death computes (0x4ffb90 asks the price function at the moment the mercenary dies)
    priced0 = None
    mm = re.search(r"merc revive price .*\((\d+) priced", mxl_text())
    priced0 = int(mm.group(1)) if mm else None
    for level in (126,):  # one death: the dead mercenary cannot be killed twice; 126 differs from the sweep's last level 150
        if not ensure_merc():
            bad.append("no mercenary for the death test at level %d" % level)
            continue
        setstat("merc", 12, level)
        setstat("merc", 6, 256)  # one life point left, then one ordinary hit (a huge one is ignored by the engine)
        r = None
        for _ in range(4):
            ok, line, _l = hv("hit merc phys 100000", "hit")
            r = line[:100]
            if merc_dead() is not False:
                break
            time.sleep(1)
        if merc_dead() is False:
            # the harness' own kill, by id: the nearest monster can be a leftover of an earlier check (a class 2796 in the full group2)
            mid = re.search(r"merc id=(\d+)", " ".join(H("merc")[1]))
            H("kill %s" % mid.group(1) if mid else "kill nearest")
        time.sleep(1)
        txt = mxl_text()
        m = re.search(r"merc revive price .*\((\d+) priced, last (-?\d+) gold for level (\d+)\)", txt)
        last = (int(m.group(2)), int(m.group(3))) if m else None
        priced1 = int(m.group(1)) if m else None
        if priced0 is not None and priced1 == priced0:
            bad.append("death at level %d: the price function was not called (priced count stays %s)" % (level, priced1))
        priced0 = priced1
        dead = merc_dead()
        rows.append("merc of level %d killed (hit %s; merc afterwards: %s): last price %s" % (level, r, {True: "dead", False: "alive", None: "gone"}[dead], last))
        log.append(rows[-1])
        if last is None or last != (revive_price_expected(level), level):
            bad.append("death at level %d: last price %s, want %s" % (level, last, (revive_price_expected(level), level)))
    # at the NPC: the menu of Kashya with the mercenary dead (the price the dialog shows and charges is the same function)
    menu = None
    try:
        goto(1)
        close_menu()
        menu = npc_menu(150)
    except Exception as e:  # the dialog is the part most likely to differ; report it, do not fail on it
        log.append("npc menu: %s" % e)
    if menu:
        log += menu
        rows.append("Kashya's menu opened with the mercenary dead (%d lines listed; the revive line is the client's own, not clicked)" % len(menu))
    close_menu()
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) if not bad else "; ".join(bad[:6]), [sh("mercrevive")], log)


def check_questxp():
    name = "Act 5 quest experience (Rite of Passage): a flat 50,000 in every difficulty, none above level 129"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    st = goto(109)
    if st["player"].get("area") != 109:
        return add(name, "BLOCKED", "could not reach Harrogath (area %s)" % st["player"].get("area"))
    close_menu()
    god(False)
    lvl0, xp0 = rd("player", 12), rd("player", 13)
    d0 = st["player"].get("difficulty", 0)
    rows, bad, log = [], [], []
    txt = mxl_text()
    if "quest experience on" not in txt:
        bad.append("`mxl` does not say `quest experience on`: %s" % next((l for l in txt.splitlines() if "quest experience" in l), "-"))
    cases = ((0, 25, 50000), (1, 45, 50000), (2, 65, 50000), (2, 130, 0), (2, 150, 0))  # difficulty, level, wanted gain
    for diff, level, want in cases:
        H("difficulty %d" % diff)
        setstat("player", 12, level)
        setstat("player", 13, 1000)
        H("quest 39 0 clear")
        H("quest 39 13 clear")
        ok, line, lines = hv("a5done", "a5done")
        log += lines
        m = re.search(r"level (\d+)->(\d+) xp (-?\d+)->(-?\d+) gained=(-?\d+)", line)
        gained = int(m.group(5)) if m else None
        rows.append("difficulty %d level %d: gained %s (want %d)" % (diff, level, gained, want))
        if not ok or gained != want:
            bad.append(rows[-1] + " [%s]" % line)
    txt = mxl_text()
    log += [l for l in txt.splitlines() if "quest experience" in l]
    H("difficulty %d" % d0)
    setstat("player", 12, lvl0 or 1)
    setstat("player", 13, xp0 or 0)
    H("quest 39 0 clear")
    add(name, "PASS" if not bad else "FAIL", "`h a5done` (D2R's own Rite of Passage completion): %s" % ("; ".join(rows) if not bad else "; ".join(bad[:6])),
        [sh("questxp")], log)


def check_questrewards():
    name = "Quest rewards D2Sigma removes: Qual-Kehk runes, Akara ring, Andariel chipped gems, Hellforge and Countess classes"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    rows, bad, log = [], [], []
    m0 = mxl_mark()
    txt = mxl_text()
    qr = next((l for l in txt.splitlines() if "quest rewards" in l), "")
    log.append(qr)
    if "quest rewards on" not in qr:
        bad.append("`mxl`: %s" % (qr or "no quest rewards line"))
    runes = ("r07", "r08", "r09", "r10")

    def count(code):
        return len(items(hstate(), code)) + ground_count(code)

    def ground_total():
        for l in H("dump ground")[1]:
            m = re.match(r"ground items (\d+)", l)
            if m:
                return int(m.group(1))
        return 0

    # Qual-Kehk (Normal): Median's r08 r09 r10 only; D2R would add r07 r08 r09 (r07 absent, r08 / r09 once)
    st = goto(109)
    if st["player"].get("area") == 109:
        close_menu()
        H("difficulty 0")
        H("packclear")
        for r in runes:
            H("remove %s 6" % r)
        H("quest 36 0 clear")
        H("quest 36 1 set")
        H("quest 36 6 clear")
        H("quest 36 7 clear")
        before = {r: count(r) for r in runes}
        if not H("interact 515")[0]:  # the message packet is handled for the NPC the player is talking to
            H("spawn 515")
            H("interact 515")
        time.sleep(3)
        ok, ml = H("msg 515 0x4e8e")
        time.sleep(3)
        got = {r: count(r) - before[r] for r in runes}
        rows.append("Qual-Kehk gave %s" % " ".join("%s x%d" % (r, got[r]) for r in runes))
        log += ml
        if not ok:
            bad.append("Qual-Kehk could not be reached (msg 515)")
        elif got != {"r07": 0, "r08": 1, "r09": 1, "r10": 1}:
            bad.append("Qual-Kehk runes %s (want r08 r09 r10 once each, no r07)" % got)
    else:
        bad.append("could not reach Harrogath")

    # Akara: no ring (the Heart is the reward)
    goto(1)
    close_menu()
    H("quest 4 1 set")
    H("packclear")
    H("remove 600 6")
    H("remove rin 6")
    before = count("rin")
    if not H("interact 148")[0]:
        H("spawn 148")
    ok, ml = H("msg 148 0x76")
    time.sleep(3)
    ring, heart = count("rin") - before, count("600")
    rows.append("Akara gave %d rings and %d hearts" % (ring, heart))
    log += ml
    if ring != 0:
        bad.append("Akara still gave a ring")
    close_menu()

    # Andariel: the two chipped gems of the vanilla quest drop are gone (three kills would leave 6 or more of them)
    gems = ("gcv", "gcy", "gcb", "gcg", "gcr", "skc")
    H("difficulty 0")
    H("quest 47 0 clear")
    n0 = sum(count(c) for c in gems)
    for _ in range(3):
        H("spawn 156")
        H("kill nearest 156")
        time.sleep(1)
    n1 = sum(count(c) for c in gems) - n0
    rows.append("three Andariel kills dropped %d chipped gems (vanilla: at least 6, two a kill; the standard roll can add a few)" % n1)
    if n1 >= 6:
        bad.append("Andariel dropped %d chipped gems in three kills" % n1)

    # Hellforge (Hephasto 376) and the Countess (45): the plugin rolls Median's classes (counters in `mxl`)
    def counters():
        t = mxl_text()
        m = re.search(r"quest rewards .*\(hellforge (\d+), countess (\d+), prison of ice (\d+)\)", t)
        return tuple(int(x) for x in m.groups()) if m else None

    c0 = counters()
    g0 = ground_total()
    # the forge is an object (class 376) that the harness cannot spawn: the reward function runs on a monster standing in for it
    H("spawn 1")
    okh, lh = H("hellforgereward 1")
    time.sleep(1)
    c1 = counters()
    g1 = ground_total()
    rows.append("Hellforge reward function run (%s): hellforge counter %s -> %s, ground items %d -> %d" % ("ok" if okh else "failed", c0, c1, g0, g1))
    log += lh
    if not (c0 and c1 and c1[0] == c0[0] + 1 and g1 > g0):
        bad.append("Hellforge class not rolled: counters %s -> %s, ground items %d -> %d" % (c0, c1, g0, g1))
    # Anya's Prison of Ice reward task: D2R builds a ring request, the hook makes it an amulet
    H("packclear")
    a0 = count("amu")
    okp, lp = H("prisonreward")
    time.sleep(1)
    a1 = count("amu")
    c3 = counters()
    rows.append("Prison of Ice reward task run (%s): amulets %d -> %d, rewritten counter %s" % ("code rewritten" if okp else "code NOT rewritten", a0, a1, c3[2] if c3 else None))
    log += lp
    if not okp or a1 != a0 + 1:
        bad.append("Prison of Ice reward: amulets %d -> %d (%s)" % (a0, a1, lp[:1]))
    # a Countess spawned by the harness is not on quest 5's unit list (see check_tower): the kill never reaches the quest
    # handler, so the reward function runs on its own with the kill context set by hand
    c1, g1 = counters(), ground_total()
    H("spawn 45")
    okc, lc = H("countessreward")
    time.sleep(1)
    c2 = counters()
    g2 = ground_total()
    rows.append("Countess reward: counters %s -> %s, ground items %d -> %d" % (c1, c2, g1, g2))
    log += lc
    if not (c1 and c2 and c2[1] == c1[1] + 1 and g2 > g1):
        bad.append("Countess class not rolled: counters %s -> %s, ground items %d -> %d" % (c1, c2, g1, g2))
    log += [l for l in mxl_lines_since(m0) if re.search(r"hellforge|countess|qual-kehk|quest exp", l)]
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) if not bad else "; ".join(bad[:6]) + " | " + "; ".join(rows), [sh("questrewards")], log)


def _collide_table():
    """`collidetable` parsed: {"server": {type: (fn, mask)}, "client": {...}} (hex), or None when the tables are not moved."""
    ok, lines = H("collidetable")
    out = {}
    for ln in lines:
        m = re.match(r"collidetable (server|client):\s+tables moved(.*)", ln)
        if m:
            out[m.group(1)] = {int(t): (int(fn, 16), int(mask, 16)) for t, fn, mask in re.findall(r"(\d+):([0-9a-f]+)/([0-9a-f]+)", m.group(2))}
    return out if "server" in out and "client" in out else None


# D2R's own nine rows (type: fn RVA, mask) of the server and client tables (collide_types_logic.h)
_COLLIDE_D2R = {
    "server": {0: (0, 0), 1: (0x457c70, 0x84), 2: (0x457be0, 0x104), 3: (0x457d10, 0x184), 4: (0, 0), 5: (0x457be0, 0x104), 6: (0, 4),
               7: (0x457da0, 0x40), 8: (0x457d10, 0x185)},
    "client": {0: (0, 0), 1: (0x1b0080, 0x84), 2: (0x1b0020, 0x104), 3: (0x1b00f0, 0x184), 4: (0, 0), 5: (0x1b0020, 0x104), 6: (0, 4),
               7: (0x1b0150, 0x40), 8: (0x1b00f0, 0x185)},
}


def _collide_fire(row, dx, dy, ctype, wait=14):
    """`collide`: one missile of `row` towards (+dx, +dy) of the player with collision type `ctype`; waits until it is gone.
    Returns the `collide result` dict (frames, dist, ...) or None, and the log lines."""
    ok, lines = H("collide %d %d %d %d" % (row, dx, dy, ctype))
    if not ok:
        return None, lines
    res, t0 = None, time.time()
    while time.time() - t0 < wait:
        time.sleep(0.5)
        _ok, rl = H("collide result")
        lines += rl
        for ln in rl:
            if ln.startswith("collide result:"):
                res = {k: int(float(v)) for k, v in re.findall(r"(\w+)=(-?[\d.]+)", ln)}
        if res and res.get("flying") == 0 and res.get("frames", 0) > 0:
            return res, lines
    return res, lines


def _collide9_rows():
    """missiles.txt rows (0-based data rows = *ID) of the built mod with CollideType 9."""
    t = _tsv(os.path.join(BUILT_EXCEL, "missiles.txt"))
    h = t[0]
    i = h.index("CollideType")
    return [n for n, r in enumerate(t[1:]) if len(r) > i and r[i] == "9"]


def check_collidetypes():
    """Median's missile collide types 9 and 10 (D2Sigma D2Missile collide table, 11 types; audit item 14): D2R's tables hold nine
    rows, so the plugin moves them to 256-row copies (collide_types.cpp) with Median's rows added: type 9 = mask 0x180 and the
    check function of type 3 (no wall bit 4: the missile flies through walls and stops at monsters), type 10 = mask 0x2080 and the
    function of type 1. Checks: (1) both tables moved, rows 0-8 the engine's own, 9 and 10 as above, 255 empty; (2) the 15
    missiles.txt rows with CollideType 9 still have 9 in D2R's loaded records; (3) a plain arrow (row 0, type 3) is fired with its
    type set to 3, 8 and 9 at a monster: all stop at it (type 6, which the tick skips, flies on); (4) the same towards a wall (the
    tick's own wall test, bit 4 of the mask): D2R's movement ends every type at the wall (a plain arrow cannot show the missing
    wall bit of 9 / 10), so 1, 8, 9 and 10 must end where type 3 does."""
    nm = "Missile collide types 9 / 10 (Median): table rows, stop at monsters, pass walls"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    problems, notes, log = [], [], []
    tab = _collide_table()
    if tab is None:
        return add(nm, "FAIL", "plugin part collidetypes is not on (`collidetable` says the tables are not moved; mxl: %s)" % [
            ln[:80] for ln in H("mxl")[1] if "collide" in ln])
    for side in ("server", "client"):
        t = tab[side]
        for ty, want in _COLLIDE_D2R[side].items():
            if t.get(ty) != want:
                problems.append("%s table row %d is %s, the engine has %s" % (side, ty, t.get(ty), want))
        if t.get(9, (None, None))[1] != 0x180 or t.get(9, (None,))[0] != t.get(3, (0,))[0]:
            problems.append("%s row 9 is %s, want mask 0x180 and the function of row 3 %s" % (side, t.get(9), t.get(3)))
        if t.get(10, (None, None))[1] != 0x2080 or t.get(10, (None,))[0] != t.get(1, (0,))[0]:
            problems.append("%s row 10 is %s, want mask 0x2080 and the function of row 1 %s" % (side, t.get(10), t.get(1)))
        if t.get(255) != (0, 0):
            problems.append("%s row 255 is %s, want an empty row" % (side, t.get(255)))
    notes.append("tables: server %s client %s" % ({k: (hex(v[0]), hex(v[1])) for k, v in tab["server"].items() if k in (3, 9, 1, 10)},
                                                   {k: (hex(v[0]), hex(v[1])) for k, v in tab["client"].items() if k in (3, 9)}))
    _ok, rl = H("collidetable rows")
    notes.append("loaded records by CollideType: %s" % " ".join(rl)[:200])
    rows9 = _collide9_rows()
    got = {}
    for r in rows9:
        _ok, ql = H("collidetable row %d" % r)
        m = re.search(r"CollideType (-?\d+)", " ".join(ql))
        got[r] = int(m.group(1)) if m else None
    bad = {r: v for r, v in got.items() if v != 9}
    notes.append("built missiles.txt has %d rows with CollideType 9; loaded records say %s" % (len(rows9), sorted(set(got.values()), key=str)))
    if not rows9:
        problems.append("no built missiles.txt row has CollideType 9")
    elif bad:
        problems.append("%d of %d rows with CollideType 9 in missiles.txt load as another type: %s" % (len(bad), len(rows9), dict(list(bad.items())[:8])))
    goto(2)
    kill_all_near()
    god(True)
    try:
        # --- monsters: the monster stands between the player and the target
        want_stop = {3: True, 8: True, 9: True, 6: False}
        mon_notes = []
        for ty, stops in want_stop.items():
            verdict = None
            for attempt in range(14):  # the cloud stalker walks: most spawns are out of range or beside the player when read (a shot is rare)
                kill_all_near()
                sid = spawn_id(18)
                if sid is None:
                    continue
                time.sleep(0.5)
                st = hstate()
                p = st["player"]
                # the spawned monster itself: a town NPC left in the area (Deckard Cain, id 10, unkillable) is the nearest unit otherwise
                mons = [m for m in st["mons"] if "mx" in m and "my" in m and m["id"] == sid]
                if not mons:
                    continue
                mo = mons[0]
                vx, vy = mo["mx"] - p["x"], mo["my"] - p["y"]
                d0 = (vx * vx + vy * vy) ** 0.5
                if d0 < 7 or d0 > 18:  # the missile starts a few sub-tiles ahead of the player
                    continue
                k = 40.0 / d0
                res, ml = _collide_fire(0, int(vx * k), int(vy * k), ty)
                log += ml
                if not res:
                    continue
                dist = res.get("dist", 0)
                mon_notes.append("type %d: monster at %.0f, missile ended after %d frames at %d" % (ty, d0, res.get("frames", 0), dist))
                if stops and dist <= d0 + 8:
                    verdict = True
                    break
                if not stops and dist >= d0 + 12:
                    verdict = True
                    break
                verdict = False
            if not verdict:
                problems.append("type %d %s the monster (%s)" % (ty, "did not stop at" if stops else "did not pass", mon_notes[-1] if mon_notes else "no shot"))
        notes.append("monsters: " + "; ".join(mon_notes))
        kill_all_near()
        # --- walls: first area with a wall 6-20 sub-tiles away in one of the eight directions
        wall = None
        for area in (2, 3, 8, 9, 4):
            if hstate()["player"].get("area") != area:
                goto(area)
                kill_all_near()
                god(True)
            ok, wl = H("wallscan")
            log += wl
            mb = [re.match(r"wallscan best (-?\d+) (-?\d+) wall=(\d+)", ln) for ln in wl]
            mb = [m for m in mb if m]
            if mb:
                wall = (int(mb[0].group(1)), int(mb[0].group(2)), int(mb[0].group(3)), area)
                break
        if wall is None:
            problems.append("no wall 6-20 sub-tiles from the player found in areas 2 3 8 9 4 (wallscan)")
        else:
            wx, wy, wk, area = wall
            wall_dist = wk * (1.41 if wx and wy else 1)
            notes.append("wall: area %d direction %d,%d at %d sub-tiles (%.0f away), room cells beyond it" % (area, wx, wy, wk, wall_dist))
            ends = {}
            for ty in (3, 1, 8, 9, 10, 6, 4):
                res, wl2 = _collide_fire(0, wx * 40, wy * 40, ty)
                log += wl2
                ends[ty] = res.get("dist", -1) if res else -1
                notes.append("type %d: ended at %d after %s frames" % (ty, ends[ty], res.get("frames") if res else "?"))
                if res is None:
                    problems.append("type %d towards the wall: no result" % ty)
            # D2R's missile movement ends every type at a wall (types 4 and 6 have no wall test in the tick and end there too),
            # so Median's missing wall bit in type 9 / 10 shows as no difference for a plain arrow: they must end where type 3
            # does, neither earlier nor beyond the wall
            for ty in (1, 8, 9, 10):
                if ends[ty] >= 0 and ends[3] >= 0 and abs(ends[ty] - ends[3]) > 3:
                    problems.append("type %d ended at %d towards the wall, type 3 at %d" % (ty, ends[ty], ends[3]))
            if ends[3] > wall_dist + 4:
                problems.append("type 3 flew through the wall (wall %.0f, ended %d)" % (wall_dist, ends[3]))
    finally:
        god(False)
        kill_all_near()
    add(nm, "FAIL" if problems else "PASS", "%s | %s" % ("; ".join(problems) if problems else "rows, monster stops and wall passes as Median", " | ".join(notes)),
        [sh("collidetypes")], log)


def _state_id(name):
    """Row of a state in the built states.txt (skills.txt names its aurastate)."""
    if name.isdigit():
        return int(name)
    t = _tsv(os.path.join(BUILT_EXCEL, "states.txt"))
    for i, r in enumerate(t[1:]):
        if r and r[0] == name:
            return i
    return None


def _has_state(state):
    """`hasstate`: (on, list present, expiry frame, current frame)."""
    _ok, lines = H("hasstate %d" % state)
    m = re.search(r"hasstate \d+: (\d) list=(yes|no) expiry=(-?\d+) frame=(\d+)", " ".join(lines))
    return (int(m.group(1)), m.group(2) == "yes", int(m.group(3)), int(m.group(4))) if m else None


def _startfn(slot, skill, level):
    ok, lines = H("startfn %d %d %d" % (slot, skill, level))
    m = re.search(r"returned (-?\d+) frame=(\d+)", " ".join(lines))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _start_count(slot):
    """Starts the plugin counted for a slot (`startstats`)."""
    _ok, lines = H("startstats")
    m = re.search(r"slot %d (\d+) starts" % slot, " ".join(lines))
    return int(m.group(1)) if m else None


def check_skillstarts():
    """D2Sigma's own skill start functions D2R lacks (srvstfunc 30 and 66; audit item 20): txt_migrate moves Median's skills with 30
    (Flash, Move Only) to the free slot 71 and with 66 (sk851) to 72; the plugin fills those slots (skill_starts.cpp). Slot 71:
    the caster gets the skill's aurastate until frame + auralencalc (a skill without a state does not start); slot 72 the same
    but refuses while the state is on. Checks the built data, the mxl line, then calls both slots the way the cast path does
    (`startfn`) and reads the state back (`hasstate`): Flash's state is on for its length and clears; Move Only is refused; sk851
    (25*lvl frames) is refused while on and starts again after it ended; a real cast of sk851 runs the slot."""
    nm = "Skill start functions (Median srvstfunc 30 / 66 -> slots 71 / 72): timed state on the caster"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    problems, notes, log = [], [], []
    by_name, t, h = _skill_ids_by_name()
    col = {n: h.index(n) for n in ("srvstfunc", "aurastate", "auralencalc")}
    want = {"flash": ("71", "19"), "skills_851": ("72", "25*lvl"), "move_only": ("71", "")}
    ids = {}
    for name, (slot, _len) in want.items():
        row = next((r for r in t[1:] if r and r[0].lower() == name), None)
        if row is None:
            problems.append("no %s row in the built skills.txt" % name)
            continue
        ids[name] = int(row[h.index("*Id")])
        if row[col["srvstfunc"]] != slot:
            problems.append("%s has srvstfunc %s in the built skills.txt, want %s" % (name, row[col["srvstfunc"]], slot))
    oath = next((r for r in t[1:] if r and r[0].lower() == "blood oath"), None)
    if oath is not None and oath[col["srvstfunc"]] != "66":
        problems.append("Blood Oath (D2R's own 66) has srvstfunc %s, want it to keep 66" % oath[col["srvstfunc"]])
    xl = [ln for ln in mxl_text().splitlines() if "skill starts" in ln]
    notes.append("mxl: %s" % (xl[0][:110] if xl else "no 'skill starts' line"))
    if not xl or "(2/2)" not in xl[0]:
        problems.append("mxl line 'skill starts ... (2/2)' missing: %s" % xl)
    if len(ids) < 3:
        return add(nm, "FAIL", "; ".join(problems))
    fl = next(r for r in t[1:] if r and r[0].lower() == "flash")
    sk = next(r for r in t[1:] if r and r[0].lower() == "skills_851")
    st_flash, st_851 = _state_id(fl[col["aurastate"]]), _state_id(sk[col["aurastate"]])
    notes.append("Flash state %s (%s), sk851 state %s (%s)" % (st_flash, fl[col["aurastate"]], st_851, sk[col["aurastate"]]))
    if st_flash is None or st_851 is None:
        return add(nm, "FAIL", "aurastate not found in states.txt: " + "; ".join(problems + notes))
    goto(2)
    kill_all_near()
    god(True)
    try:
        for s in (st_flash, st_851):  # nothing on from an earlier run (the states end by themselves within seconds)
            for _ in range(10):
                if not (_has_state(s) or (0,))[0]:
                    break
                time.sleep(1)
        # slot 71 / Flash: level 1, length 19 frames
        r = _startfn(71, ids["flash"], 1)
        s1 = _has_state(st_flash)
        notes.append("slot 71 flash: %s, state %s" % (r, s1))
        if r is None or r[0] != 1 or not s1 or not s1[0] or not s1[1]:
            problems.append("slot 71 Flash: start %s, state %s (want 1, on, with a stat list)" % (r, s1))
        elif not 15 <= s1[2] - r[1] <= 22:
            problems.append("Flash's state ends %d frames after the call, want 19 (auralencalc)" % (s1[2] - r[1]))
        r2 = _startfn(71, ids["flash"], 1)
        s2 = _has_state(st_flash)
        if r2 is None or r2[0] != 1 or not s2 or s2[2] < s1[2]:
            problems.append("slot 71 again: %s, expiry %s -> %s (a second start prolongs the state)" % (r2, s1 and s1[2], s2 and s2[2]))
        time.sleep(2.5)  # 19 frames = 0.8 s
        s3 = _has_state(st_flash)
        notes.append("2.5 s later: %s" % (s3,))
        if not s3 or s3[0]:
            problems.append("Flash's state still on 2.5 s after a 19-frame start: %s" % (s3,))
        # slot 71 / Move Only: no aurastate, the cast does not start
        r = _startfn(71, ids["move_only"], 1)
        notes.append("slot 71 move_only: %s" % (r,))
        if r is None or r[0] != 0:
            problems.append("Move Only start returned %s, want 0 (no state)" % (r,))
        # slot 72 / sk851 level 3: 75 frames, refused while on
        r = _startfn(72, ids["skills_851"], 3)
        s1 = _has_state(st_851)
        notes.append("slot 72 sk851 level 3: %s, state %s" % (r, s1))
        if r is None or r[0] != 1 or not s1 or not s1[0]:
            problems.append("slot 72 sk851: start %s, state %s (want 1, on)" % (r, s1))
        elif not 70 <= s1[2] - r[1] <= 77:
            problems.append("sk851's state ends %d frames after the call, want 75 (25*lvl)" % (s1[2] - r[1]))
        r2 = _startfn(72, ids["skills_851"], 3)
        s2 = _has_state(st_851)
        notes.append("second call while on: %s, expiry %s -> %s" % (r2, s1 and s1[2], s2 and s2[2]))
        if r2 is None or r2[0] != 0 or (s1 and s2 and s2[2] != s1[2]):
            problems.append("sk851 while the state is on: %s, expiry %s -> %s (want refused, expiry unchanged)" % (r2, s1 and s1[2], s2 and s2[2]))
        time.sleep(4.5)  # 75 frames = 3 s
        s3 = _has_state(st_851)
        r3 = _startfn(72, ids["skills_851"], 1)
        s4 = _has_state(st_851)
        notes.append("4.5 s later: %s; start again: %s state %s" % (s3, r3, s4))
        if not s3 or s3[0]:
            problems.append("sk851's state still on 4.5 s after a 75-frame start: %s" % (s3,))
        if r3 is None or r3[0] != 1 or not s4 or not s4[0]:
            problems.append("sk851 after the state ended: %s, state %s (want a new start)" % (r3, s4))
        # a real cast of Flash (leftskill / rightskill): the cast path runs slot 71 (D2R's own start sequence)
        n0 = _start_count(71)
        H("setskill %d 5" % ids["flash"])
        H("stat player 8 set %d" % (rd("player", 9) or 0))
        ok, cl = H("cast %d self" % ids["flash"])
        time.sleep(1)
        n1 = _start_count(71)
        log += cl
        notes.append("real cast of Flash: ok=%s slot 71 starts %s -> %s; %s" % (ok, n0, n1, cl[-1][:100] if cl else ""))
        if n0 is None or n1 is None or n1 <= n0:
            problems.append("a real cast of Flash did not reach slot 71 (starts %s -> %s; cast lines %s)" % (n0, n1, [ln[:110] for ln in cl[-3:]]))
    finally:
        god(False)
    add(nm, "FAIL" if problems else "PASS", "%s | %s" % ("; ".join(problems) if problems else "start functions as D2Sigma", " | ".join(notes)),
        [sh("skillstarts")], log)


def _storm_count(skill, seconds):
    """Missile units the server frames saw in `seconds` after one cast of `skill` at the player."""
    H("missiles reset")
    ok, lines = H("cast %d self" % skill)
    time.sleep(seconds)
    _ok, ml = H("missiles")
    m = [re.search(r"seen=(\d+)", ln) for ln in ml if ln.startswith("missiles ")]
    return (int(m[0].group(1)) if m and m[0] else 0), ok, lines


def check_activationfreq():
    """Activation frequency (stat 427) on periodic skills (audit item 13): D2Sigma's formula (perdelay shortened by stat 427) sits in
    a patched path the game never reaches and no code reads stat 427 on the periodic events, so Median's real rate does NOT depend
    on the stat; the tooltip line is its only effect. Parity check: a periodic storm skill (Sentence, dofunc 29, perdelay 5) cast
    at the player with stat 427 = 0 and = 200: the missile counts over the same window must stay within 40 % of each other (a
    working +200 % rate would double them)."""
    nm = "Activation frequency (stat 427): periodic skill rate unchanged, as Median"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    by_name, t, h = _skill_ids_by_name()
    sk = by_name.get("sentence")
    if sk is None:
        return add(nm, "BLOCKED", "no sentence row in skills.txt")
    goto(2)
    kill_all_near()
    god(True)
    notes, counts, log = [], {}, []
    try:
        H("setskill %d 10" % sk)
        base427 = rd("player", 427)
        for val in (0, 200, 0, 200):
            setstat("player", 427, val)
            H("stat player 8 set %d" % (rd("player", 9) or 0))
            time.sleep(6)  # the earlier storm ends
            for _m in range(3):
                spawn_id(18)
            n, ok, cl = _storm_count(sk, 6)
            kill_all_near()
            log += cl
            counts.setdefault(val, []).append(n)
        setstat("player", 427, base427 or 0)
    finally:
        god(False)
    a, b = sum(counts[0]), sum(counts[200])
    notes.append("missiles in 6 s after a cast of Sentence (%d): stat 427 = 0: %s, = 200: %s" % (sk, counts[0], counts[200]))
    if a < 4:
        return add(nm, "FAIL", "the control produced only %d missiles: no measurement | %s" % (a, notes[0]), [sh("activationfreq")], log)
    ratio = b / float(a)
    ok = 0.6 <= ratio <= 1.4
    add(nm, "PASS" if ok else "FAIL", "stat 427 = 200 gave %.2f x the missiles of stat 427 = 0 (want about 1: no code reads the stat; Median's tooltip line only) | %s" % (ratio, notes[0]),
        [sh("activationfreq")], log)


def _spawn_ids(cls, count):
    """Spawns `count` monsters of a class; returns their unit ids (the `spawned class N id=M` lines)."""
    ok, lines = H("spawn %d %d" % (cls, count))
    return [int(m) for m in re.findall(r"spawned class \d+ id=(\d+)", " ".join(lines))]


def _monlevel_tables():
    """(area id -> [MonLvlEx per difficulty], monstats class -> {"level": [Level, Level(N), Level(H)], "lundead": bool, "npc": bool})
    from the built mod (the expansion's area levels: D2R's area-level function reads the Ex columns)."""
    lv = _tsv(_main_checkout(os.path.join(BUILT_EXCEL, "levels.txt")))
    h = lv[0]
    ci = {n: i for i, n in enumerate(h)}
    areas = {}
    for r in lv[1:]:
        if len(r) > ci["MonLvlEx(H)"] and r[ci["Id"]].isdigit():
            areas[int(r[ci["Id"]])] = [int(r[ci[c]] or 0) for c in ("MonLvlEx", "MonLvlEx(N)", "MonLvlEx(H)")]
    ms = _tsv(_main_checkout(os.path.join(BUILT_EXCEL, "monstats.txt")))
    mh = ms[0]
    mi = {n: i for i, n in enumerate(mh)}
    mons = {}
    for cls, r in enumerate(ms[1:]):
        if len(r) > mi["Level(H)"]:
            mons[cls] = {"level": [int(r[mi[c]] or 0) for c in ("Level", "Level(N)", "Level(H)")],
                         "lundead": (r[mi["lUndead"]] or "0") == "1", "npc": (r[mi["npc"]] or "0") == "1"}
    return areas, mons


def check_monlevel():
    name = "Monster level and players count (Median: the area level in every difficulty, life +(n-1)*50 %, no experience bonus)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    txt = mxl_text()
    bad, rows, log = [], [], []
    for word in ("monster level on", "players scaling on"):
        if word not in txt:
            bad.append("`mxl` does not say `%s`: %s" % (word, next((l for l in txt.splitlines() if word.split()[0] in l and word.split()[1] in l), "-")))
    areas, mons = _monlevel_tables()
    classes = (18, 0)  # a living class and a low-undead one (monstats flag 0x40: opted out of the area level before)
    god(True)
    try:
        H("players 1")
        for area in (2, 76, 111):
            goto(area)
            for diff in (0, 1, 2):
                H("difficulty %d" % diff)
                for cls in classes:
                    ids = _spawn_ids(cls, 1)
                    if not ids:
                        bad.append("area %d diff %d class %d: nothing spawned" % (area, diff, cls))
                        continue
                    got = rd("m%d" % ids[0], 12)
                    want = areas[area][diff]
                    if mons[cls]["npc"]:
                        want = mons[cls]["level"][diff]
                    rows.append("area %d %s class %d: level %s (area level %d, own row %d)" % (area, ("Normal", "Nightmare", "Hell")[diff], cls, got, areas[area][diff], mons[cls]["level"][diff]))
                    log.append(rows[-1])
                    if got != want:
                        bad.append(rows[-1] + ", want %d" % want)
                    H("kill %d" % ids[0])
        # players-count scaling: eight monsters at each setting, in Hell (the levels stay the same)
        goto(2)
        H("difficulty 2")
        stats = {}
        for players in (1, 8):
            ok, line, _l = hv("players %d" % players, "players")
            log.append(line)
            ids = _spawn_ids(18, 8)
            life = [rd("m%d" % i, 7) for i in ids]
            life = [v >> 8 for v in life if v]
            exp = {rd("m%d" % i, 13) for i in ids}
            lvl = {rd("m%d" % i, 12) for i in ids}
            n = {rd("m%d" % i, 100) for i in ids}
            stats[players] = (sum(life) / len(life) if life else 0, exp, lvl, n)
            log.append("players %d: %d monsters, mean max life %.0f, experience %s, level %s, players stat %s" % (players, len(ids), stats[players][0], sorted(exp), sorted(lvl), sorted(n)))
            kill_all_near()
        (l1, e1, v1, n1), (l8, e8, v8, n8) = stats[1], stats[8]
        ratio = l8 / l1 if l1 else 0
        rows.append("players 1 -> 8: life x%.2f (Median 4.50), experience %s -> %s, level %s -> %s, players stat %s -> %s" % (ratio, sorted(e1), sorted(e8), sorted(v1), sorted(v8), sorted(n1), sorted(n8)))
        if not (4.0 <= ratio <= 5.0):
            bad.append("life ratio 8 players / 1 player is %.2f, Median's is 4.50" % ratio)
        if e1 != e8 or len(e1) != 1:
            bad.append("experience differs with the players count: %s -> %s" % (sorted(e1), sorted(e8)))
        if v1 != v8:
            bad.append("level differs with the players count: %s -> %s" % (sorted(v1), sorted(v8)))
        if n1 != {1} or n8 != {8}:
            bad.append("the players stat is %s / %s, want 1 / 8 (the players setting did not reach the monsters)" % (sorted(n1), sorted(n8)))
        txt = mxl_text()
        log += [l for l in txt.splitlines() if "players scaling" in l or "monster level" in l]
    finally:
        H("players 1")
        H("difficulty 0")
        kill_all_near()
        god(False)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows[-4:]) if not bad else "; ".join(bad[:6]), [sh("monlevel")], log + rows)


def check_normaltc():
    name = "Normal-difficulty drops use the level-upgraded treasure class (Median 0x12d6a)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    txt = mxl_text()
    bad, rows, log = [], [], []
    if "normal-difficulty treasure class on" not in txt:
        bad.append("`mxl` does not say `normal-difficulty treasure class on`: %s" % next((l for l in txt.splitlines() if "treasure class" in l), "-"))
    god(True)
    try:
        goto(4)  # Wilderness 3: Normal monsters of level 6 (Median's area table)
        for diff in (0, 1):  # Normal, then Nightmare (the executor's own behaviour: the control)
            H("difficulty %d" % diff)
            H("tctrace reset")
            ids = _spawn_ids(18, 1)
            if not ids:
                bad.append("difficulty %d: nothing spawned" % diff)
                continue
            level = rd("m%d" % ids[0], 12)
            H("kill %d" % ids[0])
            time.sleep(1)
            ok, line, _l = hv("tctrace", "tctrace")
            m = re.search(r"calls=(\d+) leveled=(\d+) lastclass=(-?\d+) lastlevel=(-?\d+)", line)
            log.append("%s: killed a level %s monster; %s" % (("Normal", "Nightmare")[diff], level, line))
            if not m:
                bad.append("difficulty %d: no tctrace line (%s)" % (diff, line[:80]))
                continue
            calls, leveled, tc, lvl = (int(x) for x in m.groups())
            rows.append("%s kill of a level %s monster: %d class lookups, %d with a level, last class %d level %d" % (("Normal", "Nightmare")[diff], level, calls, leveled, tc, lvl))
            if calls < 1 or leveled < 1 or lvl != level:
                bad.append(rows[-1] + " (want the monster's level handed to the class getter)")
    finally:
        H("difficulty 0")
        kill_all_near()
        god(False)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) if not bad else "; ".join(bad[:6]), [sh("normaltc")], log)


def _leash_probe(dist, seconds=2.5):
    """Moves the player `dist` sub-tiles from the mercenary, then samples the Euclidean distance every harness round trip.
    Returns (placed distance, samples [(t, euclid)], largest single drop between two samples, the log lines)."""
    ok, line, _l = hv("leash %d" % dist, "leash")
    m = re.search(r"euclid=([\d.]+)", line)
    if not ok or not m:
        return None, [], 0, [line]
    start = float(m.group(1))
    t0 = time.time()
    samples, log = [(0.0, start)], [line]
    while time.time() - t0 < seconds:
        ok, line, _l = hv("leash", "leash")
        m = re.search(r"euclid=([\d.]+)", line)
        if m:
            samples.append((round(time.time() - t0, 2), float(m.group(1))))
            log.append(line)
    drop = max([a[1] - b[1] for a, b in zip(samples, samples[1:])] or [0])
    return start, samples, drop, log


def check_leash():
    name = "Summon / hireling leash (Median: warp to the owner past 40 sub-tiles)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    txt = mxl_text()
    bad, rows, log = [], [], []
    if "summon leash on" not in txt:
        bad.append("`mxl` does not say `summon leash on`: %s" % next((l for l in txt.splitlines() if "leash" in l), "-"))
    fight_ready()
    if not ensure_merc():
        return add(name, "BLOCKED", "no mercenary could be hired")
    god(True)
    try:
        # one probe per distance: the mercenary is placed that far from the player (moving the player would pull the mercenary
        # along at once); a warp is a jump of the distance, a walk a few sub-tiles per sample
        for dist, warps in ((20, False), (30, False), (36, False), (44, True), (47, True), (60, True)):
            start, samples, drop, lines = _leash_probe(dist)
            log += lines
            if start is None:
                bad.append("distance %d: the player could not be placed (%s)" % (dist, lines[0][:100]))
                continue
            warped = drop >= 15
            rows.append("mercenary %d sub-tiles from the player: %s (largest drop between two samples %.0f, %.1f after %.1f s)" % (
                dist, "warped to the owner" if warped else "walked back", drop, samples[-1][1], samples[-1][0]))
            if warped != warps:
                bad.append(rows[-1] + ", want %s" % ("a warp" if warps else "a walk"))
    finally:
        kill_all_near()
        god(False)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) if not bad else "; ".join(bad[:6]), [sh("leash")], log)



def _unique_limit_rows():
    """Rows of plugin/src/mxl_unique_limits.h (the committed data the plugin was built from): (row, group, count, dup)."""
    txt = open(os.path.join(REPO, "plugin", "src", "mxl_unique_limits.h"), encoding="utf-8").read()
    return [tuple(int(v) for v in m) for m in re.findall(r"\{(\d+), (-?\d+), (\d+), (\d+)\},", txt)]


def _ul_counts():
    """(checked, limited, refused, chat lines sent) from the `mxl` command, None without the `unique limits on` line."""
    txt = mxl_text()
    m = re.search(r"unique limits on.*moves into the backpack (\d+) \(limited (\d+), refused (\d+)\)", txt)
    s = re.search(r"client messages .*\(sent (\d+), failed (\d+)\)", txt)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(s.group(1)) if s else -1


def _le(*vals):
    return " ".join("%02x" % b for v in vals for b in struct.pack("<I", v & 0xffffffff))


def check_uniquelimits():
    """Median's unique carry limits (uniqueitems2: LimitGroup / LimitCount / PickDuplicates; audit I6). The rule (D2Sigma D2Units
    0x100bd0b0): a limited unique does not enter the backpack when LimitCount uniques of its group (group 0: copies of it) are
    there, or, in a group, when a copy of that very unique is. Paths: the container packets (0x19 pick from the cube, 0x18 put into
    the backpack: D2R's item move 0x471e90) and the ground pickup (packet 0x16 with the to-inventory flag: 0x471950)."""
    nm = "Unique carry limits (audit I6): group limit, no duplicates, single copy, cube -> backpack and ground pickup"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    bad, rows, log = [], [], []
    s0 = _ul_counts()
    if s0 is None:
        return add(nm, "FAIL", "the `mxl` command has no `unique limits on` line: %s" % next((l for l in mxl_text().splitlines() if "unique limits" in l), "-"))
    limits = _unique_limit_rows()
    t = _tsv(os.path.join(BUILT_EXCEL, "uniqueitems.txt"))
    col = t[0].index("code")
    code_of = lambda row: t[row + 1][col]
    # four members of group 1 (count 3, no duplicates) on four different base items: `remove <code>` then takes out exactly one.
    # 1 x 1 bases only: `item <code> cube` finds no spot for a taller item in the cube
    m = _tsv(os.path.join(BUILT_EXCEL, "misc.txt"))
    mc, mw, mh = m[0].index("code"), m[0].index("invwidth"), m[0].index("invheight")
    small = {r[mc] for r in m[1:] if len(r) > mh and r[mw] == "1" and r[mh] == "1"}
    limits = [r for r in limits if code_of(r[0]) in small]
    g1, seen = [], set()
    for r in limits:
        if r[1] == 1 and code_of(r[0]) not in seen:
            seen.add(code_of(r[0]))
            g1.append(r)
    solo = [r for r in limits if r[1] == 0 and r[2] == 1 and code_of(r[0]) not in seen]
    if len(g1) < 4 or len(solo) < 2 or g1[0][2] != 3 or g1[0][3] != 0:
        return add(nm, "FAIL", "the data has no group of count 3 with 4 members on different items / two single copies: %s" % limits[:6])
    A, B, C, D = (r[0] for r in g1[:4])
    S1, S2 = (r[0] for r in solo[:2])
    codes = sorted({code_of(r) for r in (A, B, C, D, S1, S2)})

    def reset():
        H("packclear")
        H("cubeclear")
        drop_cursor_item(log)  # a held item is not found by `remove`: drop it (packet 0x17)
        for c in codes:
            H("remove %s 9" % c)
        ensure_cube()

    def make(row, where):
        ok, lines = H("item %s %s uniq=%d" % (code_of(row), where, row))
        d = next((kv(l) for l in lines if l.startswith("item ")), {})
        if not ok or "id" not in d or d.get("unique") != str(row) or d.get("quality") != "7":
            bad.append("could not make unique %d (%s) in %s: %s" % (row, code_of(row), where, lines[:2]))
            return None
        return {"id": int(d["id"]), "x": int(d.get("x", "0")), "y": int(d.get("y", "0")), "row": row}

    def pack_count(row):
        return len([i for i in items(hstate(), code_of(row), 0) if i.get("unique") == row and i.get("quality") == 7])

    def cursor_id():
        ok, cur = H("cursor")
        m = re.search(r"cursor id=(\d+)", " ".join(cur))
        return int(m.group(1)) if m else None

    def near_ground(row):
        """A ground copy within 4 subtiles of the player (the pickup packet 0x16 only reaches that far; `item ... ground` drops
        up to 6 away): ground drops that landed too far are taken away again and the drop is repeated."""
        for _ in range(10):
            g = make(row, "ground")
            if not g:
                return None
            ok, st = H("state")
            m = re.search(r"player id=\d+ .*? x=(\d+) y=(\d+)", st[0] if st else "")
            ok, fl = H("iflags %d" % g["id"])
            f = next((kv(l) for l in fl if l.startswith("iflags")), {})
            if not m or ((int(f.get("x", "0")) - int(m.group(1))) ** 2 + (int(f.get("y", "0")) - int(m.group(2))) ** 2) <= 9:
                return g
            # (a far drop stays where it is: `remove <code> 1` takes the FIRST item of that code, which is the copy the check carries
            # in the backpack, not the ground one; reset() clears the leftovers by code)
        bad.append("no ground drop of unique %d landed within 4 subtiles of the player" % row)
        return None

    def cube_to_pack(it, cells=((12, 7), (13, 8), (10, 8), (3, 9))):
        """Pick the cube item up (packet 0x19), put it into the backpack (0x18: the move D2R's 0x471e90 checks). Returns
        (landed in the backpack, the id the cursor holds afterwards); a cell without room is skipped, a refusal by the rule
        (the plugin's counter went up) ends the tries."""
        H("pkt 19 " + _le(it["id"], it["x"], it["y"], 3))
        time.sleep(0.4)
        if cursor_id() != it["id"]:
            bad.append("the cube item %d did not reach the cursor (cursor holds %s)" % (it["id"], cursor_id()))
            return False, cursor_id()
        for (x, y) in cells:
            before = _ul_counts()
            H("pkt 18 " + _le(it["id"], x, y, 0))
            time.sleep(0.4)
            now = _ul_counts()
            if cursor_id() != it["id"]:
                return True, None
            if now and before and now[2] > before[2]:
                return False, it["id"]
        return False, cursor_id()

    reset()
    # 1. group 1 (count 3, no duplicates): three members carried, the fourth from the cube is refused
    for r in (A, B, C):
        make(r, "inv")
    d4 = make(D, "cube")
    if d4:
        before = _ul_counts()
        landed, held = cube_to_pack(d4)
        after = _ul_counts()
        rows.append("group full (A, B, C carried): fourth member %s, refused %d -> %d, limited %d -> %d" % ("LANDED" if landed else "refused", before[2], after[2], before[1], after[1]))
        if landed or held != d4["id"] or after[2] < before[2] + 1 or pack_count(D) != 0:
            bad.append("full group: the fourth member should be refused and stay on the cursor (landed %s, cursor %s, refused %d -> %d, in pack %d)" % (landed, held, before[2], after[2], pack_count(D)))
        # 2. positive control: free a place (remove A), the same item now lands
        H("remove %s 1" % code_of(A))
        if pack_count(A) == 0 and held == d4["id"]:
            before = _ul_counts()
            H("pkt 18 " + _le(d4["id"], 12, 7, 0))
            time.sleep(0.4)
            after = _ul_counts()
            rows.append("after one is removed: fourth member in the backpack %d, refused %d -> %d" % (pack_count(D), before[2], after[2]))
            if pack_count(D) != 1 or after[2] != before[2]:
                bad.append("one place free: the member should land (in pack %d, refused %d -> %d, cursor %s)" % (pack_count(D), before[2], after[2], cursor_id()))
        else:
            bad.append("could not free a place for the positive control (A in pack %d, cursor %s)" % (pack_count(A), cursor_id()))
    # 3. no duplicates: group at 2 of 3, a second copy of a carried member is refused although the group has room
    reset()
    make(B, "inv")
    make(C, "inv")
    dup = make(B, "cube")
    if dup:
        before = _ul_counts()
        landed, held = cube_to_pack(dup)
        after = _ul_counts()
        rows.append("duplicate of a carried member (group 2 of 3): %s, refused %d -> %d" % ("LANDED" if landed else "refused", before[2], after[2]))
        if landed or after[2] < before[2] + 1:
            bad.append("a second copy of the same unique in a group should be refused (landed %s, refused %d -> %d)" % (landed, before[2], after[2]))
    # 4. a single-copy unique (limit 1, group 0): a second copy lying on the ground is refused, a different single-copy unique is not
    #    (these two bases cannot be placed in the cube by the harness, so the ground path stands in for the cube here)
    def ground_pickup(row):
        g = near_ground(row)
        if not g:
            return None
        ok, fl = H("iflags %d" % g["id"])
        f = next((kv(l) for l in fl if l.startswith("iflags")), {})
        before = _ul_counts()
        H("pkt 16 " + _le(g["id"], int(f.get("x", "0")), int(f.get("y", "0")), 1))
        time.sleep(0.5)
        after = _ul_counts()
        ok, fl2 = H("iflags %d" % g["id"])
        f2 = next((kv(l) for l in fl2 if l.startswith("iflags")), {})
        return before, after, pack_count(row), f2.get("mode")

    reset()
    carried1 = make(S1, "inv")
    res = ground_pickup(S1) if carried1 else None
    if res:
        before, after, inpack, gmode = res
        rows.append("second copy of a single-copy unique picked up from the ground: refused %d -> %d, in pack %d, the ground copy's mode %s (3 = still on the ground)" % (
            before[2], after[2], inpack, gmode))
        # the carried copy must still be the only one in the pack and the ground copy must not have entered it
        if after[2] < before[2] + 1 or inpack != 1 or gmode not in ("3", "5"):
            bad.append("the second copy of a single-copy unique should be refused (refused %d -> %d, in pack %d, ground copy mode %s)" % (
                before[2], after[2], inpack, gmode))
    # a different single-copy unique is not counted: carry S1 and S2, lift S2 off the backpack (packet 0x19) and put it back (0x18)
    reset()
    make(S1, "inv")
    # (D2R's own one-per-type rule for unique charms refuses a second one of a type at placement, so many pairs cannot be
    # carried together at all: take the first single-copy unique that can be placed next to S1)
    s2 = None
    for cand in [r[0] for r in solo[1:]]:
        s2 = make(cand, "inv")
        if s2:
            S2 = cand
            break
        bad.pop()
    if not s2:
        rows.append("no second single-copy unique could be carried next to the first (D2R's one-per-type rule): positive control skipped")
    if s2:
        H("pkt 19 " + _le(s2["id"], s2["x"], s2["y"], 0))
        time.sleep(0.4)
        lifted = cursor_id() == s2["id"]
        before = _ul_counts()
        H("pkt 18 " + _le(s2["id"], s2["x"], s2["y"], 0))
        time.sleep(0.4)
        after = _ul_counts()
        rows.append("a different single-copy unique lifted off the backpack and put back: lifted %s, refused %d -> %d, in pack %d, cursor %s" % (lifted, before[2], after[2], pack_count(S2), cursor_id()))
        if not lifted or after[2] != before[2] or pack_count(S2) != 1 or cursor_id() is not None:
            bad.append("another single-copy unique must not count (lifted %s, refused %d -> %d, in pack %d, cursor %s)" % (lifted, before[2], after[2], pack_count(S2), cursor_id()))
    # 5. ground pickup into the inventory (packet 0x16, to-inventory flag 1): refused over the limit; to the cursor (flag 0) is allowed
    reset()
    for r in (A, B, C):
        make(r, "inv")
    gnd = near_ground(D)
    if gnd:
        def iflags():
            ok, fl = H("iflags %d" % gnd["id"])
            return next((kv(l) for l in fl if l.startswith("iflags")), {})
        f = iflags()
        gx, gy = int(f.get("x", "0")), int(f.get("y", "0"))
        before = _ul_counts()
        H("pkt 16 " + _le(gnd["id"], gx, gy, 1))
        time.sleep(0.5)
        after = _ul_counts()
        f2 = iflags()
        rows.append("ground pickup to the inventory over the limit: checked %d -> %d, refused %d -> %d, item mode %s (3 = still on the ground), in pack %d" % (before[0], after[0], before[2], after[2], f2.get("mode"), pack_count(D)))
        if after[2] < before[2] + 1 or pack_count(D) != 0 or f2.get("mode") not in ("3", "5"):
            bad.append("the pickup to the inventory should be refused and leave the item on the ground (refused %d -> %d, mode %s, in pack %d)" % (before[2], after[2], f2.get("mode"), pack_count(D)))
        H("pkt 16 " + _le(gnd["id"], gx, gy, 0))
        time.sleep(0.5)
        rows.append("ground pickup to the cursor: cursor holds %s (item %d)" % (cursor_id(), gnd["id"]))
        if cursor_id() != gnd["id"]:
            bad.append("a pickup to the cursor is not limited; the cursor holds %s" % cursor_id())
        else:
            before = _ul_counts()
            H("pkt 18 " + _le(gnd["id"], 12, 7, 0))
            time.sleep(0.4)
            after = _ul_counts()
            rows.append("cursor -> backpack over the limit: refused %d -> %d, cursor %s" % (before[2], after[2], cursor_id()))
            if after[2] < before[2] + 1 or cursor_id() != gnd["id"]:
                bad.append("the drop from the cursor into a full group should be refused (refused %d -> %d, cursor %s)" % (before[2], after[2], cursor_id()))
    # 6. wearing: all 334 limited uniques are misc items without a body location (nothing to equip), so the rule has no wear half
    # 7. the messages: one chat line per refusal (client messages sent)
    end = _ul_counts()
    reset()
    if end and s0:
        refusals = end[2] - s0[2]
        sent = end[3] - s0[3] if end[3] >= 0 and s0[3] >= 0 else None
        rows.append("refusals this run %d, chat lines sent %s" % (refusals, sent))
        if sent is not None and sent < refusals:
            bad.append("%d refusals but only %d chat lines sent" % (refusals, sent))
    add(nm, "PASS" if not bad else "FAIL", "; ".join(bad + rows) if bad else "; ".join(rows), [], log)

BUFF_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "src", "mxl_state_icons.h")


def _state_icon_rows():
    """The generated table (tools/state_icons.py): [(state, side, tint, frame, tooltip key)] in drawing order."""
    with open(BUFF_TABLE, encoding="utf-8") as f:
        return [(int(a), int(b), int(c), int(d), e) for a, b, c, d, e in
                re.findall(r'\{(\d+), (\d), (\d+), (\d+), "([^"]*)"\}', f.read())]


def _buff_icons():
    """`h bufficons` parsed: (counters dict, [icon dicts])."""
    ok, lines = H("bufficons")
    head = dict(kv(lines[0])) if lines and lines[0].startswith("bufficons ") else {}
    icons = [{k: int(v) for k, v in kv(ln).items()} for ln in lines if ln.startswith("bufficons icon ")]
    return head, icons


def check_bufficons():
    name = "Buff / debuff icon bar: Median's two icon groups, timers and hover tooltip (buff_icons.cpp, OverlayService rectangles; counters, not pixels)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    rows = _state_icon_rows()
    side_of = {r[0]: r[1] for r in rows}
    tip_of = {r[0]: r[4] for r in rows}
    order = {}
    for i, r in enumerate(rows):
        order.setdefault(r[0], i)  # the first row of a state decides its place in the drawing order
    left = [s for s in (32, 101, 26) if side_of.get(s) == 0]  # battle orders, holy shield, shout: no effect without stats
    right = [s for s in (89, 19) if side_of.get(s) == 1]  # battle cry, weaken
    if len(left) < 2 or not right:
        return add(name, "BLOCKED", "the table has no rows for the test states (left %s, right %s)" % (left, right))
    goto(1)
    close_menu()
    chosen = left + right
    for s in chosen:  # a clean start: no test state on the player
        H("setstate player %d 0" % s)
        g.hcmd("bufficons cstate %d 0" % s, 5)
    time.sleep(1.5)
    base_head, base_icons = _buff_icons()
    if base_head.get("on") != "1":
        return add(name, "FAIL", "the part is off: %s" % base_head)
    # Put the states on the server's player (a state list that ends in 10 minutes, the way D2R's self buffs do); then on the client's
    # copy if D2R's own packets did not carry them (the bar reads the client's unit).
    log = []
    for s in chosen:
        ok, out = H("setstate player %d 1" % s)
        log += out
    time.sleep(2.5)
    head, icons = _buff_icons()
    shown = {i["state"]: i for i in icons}
    carried = [s for s in chosen if s in shown]  # states that reached the client through D2R's own packets
    if len(carried) < len(chosen):
        for s in chosen:
            if s not in shown:
                ok, out = g.hcmd("bufficons cstate %d 1" % s, 5)
                log += out
        time.sleep(2.5)
        head, icons = _buff_icons()
        shown = {i["state"]: i for i in icons}
    problems = []
    for s in chosen:
        i = shown.get(s)
        if i is None:
            problems.append("state %d is not drawn" % s)
        elif i["side"] != side_of[s]:
            problems.append("state %d in group %d, expected %d" % (s, i["side"], side_of[s]))
    # Order within a group: table order, slots 0..n-1 without gaps
    for side in (0, 1):
        grp = sorted((i for i in icons if i["side"] == side), key=lambda i: order.get(i["state"], 9999))
        if [i["slot"] for i in grp] != list(range(len(grp))):
            problems.append("group %d slots %s are not 0..%d in table order" % (side, [i["slot"] for i in grp], len(grp) - 1))
    if int(head.get("failed", "1")) != 0:
        problems.append("the overlay refused %s draw requests (first result %s)" % (head.get("failed"), head.get("firstFail")))
    # Timers: set for 10 minutes by `setstate`, they must read about 600 s and count down
    secs0 = {s: shown[s]["secs"] for s in chosen if s in shown}
    time.sleep(5)
    head2, icons2 = _buff_icons()
    shown2 = {i["state"]: i for i in icons2}
    for s in chosen:
        if s in shown2 and s in secs0:
            a, b = secs0[s], shown2[s]["secs"]
            if not (a > 0 and b > 0 and 3 <= a - b <= 8):
                problems.append("state %d timer %d -> %d after 5 s" % (s, a, b))
            if a > 600 or a < 580:
                problems.append("state %d timer %d, expected about 600" % (s, a))
    # The screenshot for the human. It is not an assertion: PrintWindow of the background window does not capture the loader's
    # overlay (the same finding as the dungeon lockout timer), so the on-screen proof is the counters above, not the pixels.
    shots = [sh("bufficons_bar")]
    now_shot = grab()
    h, w, _ = now_shot.shape
    # Does the PrintWindow capture show the overlay at all? A magenta test rectangle
    H("bufficons probe on")
    time.sleep(1.5)
    probe_shot = grab()
    shots.append(sh("bufficons_probe"))
    H("bufficons probe off")
    region = (slice(int(h * 0.3) + 4, int(h * 0.45) - 4), slice(int(w * 0.3) + 4, int(w * 0.7) - 4))
    probe_seen = bool((abs(probe_shot[region] - now_shot[region]).sum(axis=2) > 200).mean() > 0.5)
    # Hover: the tooltip of the first left state that has one
    tip_state = next((s for s in left if tip_of.get(s)), None)
    hover_note = "no test state has a tooltip"
    if tip_state is not None:
        H("bufficons hover state %d" % tip_state)
        time.sleep(1.2)
        head3, icons3 = _buff_icons()
        hov = [i["state"] for i in icons3 if i["hover"]]
        if hov != [tip_state]:
            problems.append("hover on state %d: icons hovered %s" % (tip_state, hov))
        if int(head3.get("tooltip", "-1")) != tip_state or int(head3.get("lines", "0")) < 1:
            problems.append("hover on state %d drew no tooltip (%s lines %s)" % (tip_state, head3.get("tooltip"), head3.get("lines")))
        hover_note = "hover %d (%s): tooltip %s, %s line(s)" % (tip_state, tip_of[tip_state], head3.get("tooltip"), head3.get("lines"))
        shots.append(sh("bufficons_hover"))
        H("bufficons hover off")
    # Cleanup: the states go, the icons go
    for s in chosen:
        H("setstate player %d 0" % s)
        g.hcmd("bufficons cstate %d 0" % s, 5)
    time.sleep(2)
    head4, icons4 = _buff_icons()
    left_over = [i["state"] for i in icons4 if i["state"] in chosen]
    if left_over:
        problems.append("icons still drawn after clearing: %s" % left_over)
    note = ("states %s (left) %s (right): %s; %s left / %s right icons; timers %s -> %s; %s; overlay refused %s requests; rectangles per frame %s. "
            "The states reached the client %s. Probe rectangle seen in the PrintWindow capture: %s (informational; the loader's overlay is not part of that capture). Screenshots: bufficons_bar.png, bufficons_probe.png, bufficons_hover.png" % (
                left, right, "drawn in the right group, in table order, with their timers" if not problems else "PROBLEMS: " + "; ".join(problems),
                head2.get("left", "0"), head2.get("right", "0"), secs0, {s: shown2[s]["secs"] for s in shown2 if s in chosen},
                hover_note, head.get("failed"), head2.get("rectsLast"),
                "by D2R's own packets for %s, by `bufficons cstate` (the client's copy) for %s" % (carried, [s for s in chosen if s not in carried]), probe_seen))
    add(name, "PASS" if not problems else "FAIL", note, shots, log)


def _ap_pixels(path, box=(640, 260, 960, 620)):
    from PIL import Image
    import numpy as np
    return np.asarray(Image.open(path).convert("RGB").crop(box), dtype=np.int16)


def _ap_diff(a, b):
    import numpy as np
    return np.abs(a - b).sum(2) > 60


def check_assetpaths():
    """Assets at new paths (lane new-asset-paths, docs/hd-models.md section 3c): the Druid's Wereowl form (unit mxl_wereowl3d) and the
    Corrupted Wereowl have their model, texture and index entries at data/hd/character/mxl/..., not over the vanilla horse / pig
    paths. The engine loads a model of a path that its index (model_lod_desc.bin) does not list and never draws it, so the proof is
    the picture: a spawned unit changes pixels around the player that stayed still between three shots before the spawn.
    Judged: the Druid's form (`wereowl`: 5-9 % of the pixels against under 1 % with the index entry missing; limit 3 %). The Corrupted Wereowl is only
    reported: its green aura changes 25-30 % of the picture with or without the model."""
    nm = "Assets at new paths: the Druid's Wereowl form (model, textures at data/hd/character/mxl/) is drawn"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    fight_ready()
    enable_debug()
    god(True)
    mark = log_mark()
    time.sleep(3.0)
    base = []
    for k in range(3):  # the background's own change between shots (rain, light, leftovers of an earlier check)
        sh("assetpaths_base_%d" % k)
        base.append(_shot_path("assetpaths_base_%d" % k))
        time.sleep(1.0)
    px = [_ap_pixels(p) for p in base]
    moving = _ap_diff(px[0], px[1]) | _ap_diff(px[1], px[2])  # pixels that change by themselves: animated leftovers, rain
    noise = float(moving.mean())
    rows, shots, bad = [], [], []
    for uid in ("wereowl", "corrupted_wereowl"):
        known = {m.get("id") for m in hstate()["mons"]}
        cheat("mspawn %s" % uid)
        time.sleep(2.5)
        new = [m for m in hstate()["mons"] if m.get("id") not in known and not m.get("npc")]
        for attempt in range(2):  # the cheat line is lost now and then (suite-main-060 run 105541: corrupted_wereowl none in 11 s): once more
            for _ in range(8):  # in a long suite session the cheat's spawn can take longer (suite 2026-10-23: corrupted_wereowl at +2.5 s: none)
                if new:
                    break
                time.sleep(1.0)
                new = [m for m in hstate()["mons"] if m.get("id") not in known and not m.get("npc")]
            if new or attempt:
                break
            cheat("mspawn %s" % uid)
            time.sleep(2.5)
            new = [m for m in hstate()["mons"] if m.get("id") not in known and not m.get("npc")]
        for m in sorted(new, key=lambda m: m["id"])[1:]:  # the minions of a boss are in the picture: only the unit itself is judged
            H("kill %d" % m["id"])
        time.sleep(3.5)
        best = 0.0
        for k in range(3):
            name = "assetpaths_%s_%d" % (uid, k)
            shot = sh(name)
            best = max(best, float((_ap_diff(px[2], _ap_pixels(_shot_path(name))) & ~moving).mean()))
            if k == 0:
                shots.append(shot)
            time.sleep(0.4)
        for m in new:
            H("kill %d" % m["id"])
        time.sleep(1.0)
        clean_area()
        rows.append("%s: %d unit(s) spawned (the first one %s), %.1f%% of the pixels around the player changed" % (
            uid, len(new), "judged" if uid == "wereowl" else "only reported: its aura draws without the model", 100 * best))
        if not new:
            bad.append("%s did not spawn" % uid)
        elif uid == "wereowl" and best < 0.03:
            bad.append("%s: not drawn (%.1f%% changed)" % (uid, 100 * best))
    asserts = [a for a in assertions_since(mark) if re.search(r"MeshBindingCount|isMeshFlipbook|model_asset|LOD", a)]
    if asserts:
        bad.append("model assertions in d2rloader.log: %s" % sorted(set(asserts))[:3])
    god(False)
    add(nm, "PASS" if not bad else "FAIL", "%s; %.1f%% of the pixels moved by themselves before the spawn and are not counted%s" % ("; ".join(rows), 100 * noise, ("; PROBLEMS: " + "; ".join(bad)) if bad else ""),
        shots)


# ------------------------------------------------------------------ lane p4-verify-a: the verify rows of docs/unported.md (audit DC5 DC7 GS10 IT16 CR5 CR6 XP6 XP7 XP9 MU2)


def has_state(state):
    """`h hasstate <id>` -> 1 / 0 (None when the answer is missing)."""
    ok, lines = H("hasstate %d" % state)
    m = re.search(r"hasstate %d: (\d)" % state, " ".join(lines))
    return int(m.group(1)) if m else None


def akara_respec(log, quiet=False):
    """Akara's Reset Stat / Skill Points line: True when the click, Yes and the stat reset went through, False when the menu has no
    plugin (respec) line, None when the menu did not open."""
    menu = npc_menu(148)
    if not menu:
        return None
    plugin_lines = [ln for ln in menu if "handler=plugin" in ln]
    log.append("akara menu: %s" % [ln.strip() for ln in menu[1:]])
    if not plugin_lines:
        return False
    idx = int(re.search(r"line (\d+)", plugin_lines[0]).group(1))
    H("menu %d" % idx)
    time.sleep(1.5)
    H("menu confirm")
    ok, out = H("menu yes")
    time.sleep(1.5)
    log += out
    return ok


def respec_stats():
    """The four base stats and the unused points (the respec resets them; the checks put them back)."""
    return [rd("player", i) for i in range(4)] + [rd("player", 4)]


def restore_respec_stats(saved):
    close_menu()
    for i, v in enumerate(saved[:4]):
        if v is not None:
            setstat("player", i, v)
    if saved[4] is not None:
        setstat("player", 4, saved[4])


def check_respecbuffs():
    name = "Reset removes buffs (audit DC7): Akara's stat / skill reset clears the active buffs"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    H("quest 1 0 set")   # Den of Evil done
    H("quest 41 1 set")  # its respec reward is waiting
    H("quest 41 0 clear")
    saved = respec_stats()
    log = []
    states = (32, 101, 26)  # battle orders, holy shield, shout
    for s in states:
        H("setstate player %d 0" % s)
    # one real buff: Barbarian Shout (skill 138, state 26), cast on the player; the others are put on with the harness (a state list of ten minutes)
    H("setskill 138 5")
    ok, cl = H("cast 138 self")
    log += cl
    time.sleep(1.5)
    real = has_state(26) == 1
    for s in states:
        if has_state(s) != 1:
            H("setstate player %d 1" % s)
    before = {s: has_state(s) for s in states}
    log.append("states before: %s (shout from a real cast: %s)" % (before, real))
    done = akara_respec(log)
    after = {s: has_state(s) for s in states}
    log.append("states after: %s" % after)
    restore_respec_stats(saved)
    for s in states:
        H("setstate player %d 0" % s)
    if any(v != 1 for v in before.values()):
        return add(name, "BLOCKED", "the test states did not start: %s" % before, [], log)
    if not done:
        return add(name, "BLOCKED", "the respec did not run (%s)" % done, [], log)
    gone = [s for s, v in after.items() if v == 0]
    add(name, "PASS" if len(gone) == len(states) else "FAIL",
        "states %s on before the Akara respec (Shout from a real cast: %s); after it: %s" % (before, real, after), [], log)


def check_signet():
    name = "Signet of Learning (audit GS10): +1 stat point each, at most 400 (Median stat 185 = D2R 370)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    TOTAL = 370
    base_total, base_pts = rd("player", TOTAL), rd("player", 4)
    log, rows, bad = [], [], []
    # (signet code, signets' own amount, learning total before) -> expected points gained min(amount, 400 - total)
    cases = [("01^", 1, 0), ("01^", 1, 399), ("01^", 1, 400), ("05^", 5, 397), ("06^", 6, 398), ("05^", 5, 400)]
    H("packclear")
    try:
        for code, amount, total in cases:
            setstat("player", TOTAL, total)
            p0 = rd("player", 4)
            ok, cl = H("item %s inv" % code)
            log += cl
            if not ok:
                bad.append("item %s could not be created: %s" % (code, cl[:1]))
                continue
            ok, ul = H("use %s" % code)
            log += ul
            time.sleep(0.5)
            t1, p1 = rd("player", TOTAL), rd("player", 4)
            want = max(0, min(amount, 400 - total))
            rows.append("%s at %d: used=%s, learning %d -> %d, stat points %d -> %d (want +%d)" % (code, total, ok, total, t1, p0, p1, want))
            if t1 - total != want or p1 - p0 != want:
                bad.append(rows[-1])
            H("remove %s" % code)
    finally:
        setstat("player", TOTAL, base_total if base_total is not None else 0)
        if base_pts is not None:
            setstat("player", 4, base_pts)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def _ground_drops(seen):
    out = []
    for l in H("dump ground")[1]:
        if l.startswith("ground ") and re.search(r"mode=[35] ", l):
            d = {k: v for k, v in re.findall(r"(\w+)=(-?\d+)", l)}
            if int(d["id"]) not in seen:
                out.append(d)
    return out


def check_dropilvl():
    name = "Drop item level (audit IT16 / DF10): a monster's drops take the item level of the area it was found in (its monster level), not the town's, with and without a town trip"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    areas, mons = _monlevel_tables()
    log, rows, bad = [], [], []
    seen = set()
    god(True)
    try:
        # the reader: the item level of an item created with a known one (0x3730d0 reads item data +0x40)
        goto(1)
        H("packclear")
        calib = []
        # base items of low level (a Median signet or rune has its own, high `level`; ilvl cannot go below the base's)
        for code in ("rin", "amu", "tow"):
            for want in (1, 33, 77, 100, 150, 255):
                ok, cl = H("item %s inv ilvl=%d" % (code, want))
                log += cl
                got = None
                for ln in hstate()["lines"]:
                    m = re.match(r"item id=\d+ code=%s .* ilvl=(\d+)" % code, ln)
                    if m:
                        got = int(m.group(1))
                calib.append((code, want, got))
                H("remove %s" % code)
        rows.append("reader check (items created with ilvl 1 / 33 / 77 / 100 / 150 / 255 read): %s" % calib)
        log.append(rows[-1])
        reader_follows = all(w == g_ for _, w, g_ in calib)  # False: the generator gives every item the same level whatever is asked

        def drops_in(area, diff, trip):
            """Kills 4 monsters of a class with a treasure class, several times; returns (item levels, monster levels, drops)."""
            if trip:
                goto(1)  # the town trip
            H("difficulty %d" % diff)
            goto(area)
            clear_mons()
            time.sleep(3)  # the items an earlier visit left in the area reach the client as new units a moment after the arrival (soak run 2026-10-25: ilvl 1 drops of the Normal visit counted in Hell)
            seen.update(int(d["id"]) for d in _ground_drops(set()))
            drops, levels = [], set()
            for n in range(10):
                # classes with a treasure class in the built monstats (class 18 and the other vanilla trash have none in Median)
                ids = _spawn_ids((719, 722, 725, 714)[n % 4], 4)
                for i in ids:
                    levels.add(rd("m%d" % i, 12))
                for i in ids:
                    H("kill %d" % i)
                time.sleep(1.5)
                for d in _ground_drops(seen):
                    seen.add(int(d["id"]))
                    drops.append(d)
                if len(drops) >= 8:
                    break
                clear_mons()
            log.append("area %d diff %d trip %s: drops %s" % (area, diff, trip, sorted({(d["code"] if "code" in d else d.get("class"), int(d["ilvl"])) for d in drops}, key=str)[:14]))
            return sorted({int(d["ilvl"]) for d in drops}), sorted(levels), len(drops)

        for area, diff in ((2, 0), (76, 0), (2, 2), (76, 2)):  # town-adjacent and deep, Normal and Hell
            straight = drops_in(area, diff, False)
            trip = drops_in(area, diff, True)
            want, town = areas[area][diff], areas[1][diff]
            rows.append("area %d %s (area level %d, the town's %d): monster level %s; item levels without a town trip %s (%d drops), after one %s (%d drops)" % (
                area, ("Normal", "Nightmare", "Hell")[diff], want, town, trip[1], straight[0], straight[2], trip[0], trip[2]))
            log.append(rows[-1])
            if not straight[2] or not trip[2]:
                bad.append(rows[-1] + " (no drop to judge)")
            elif straight[0] != trip[0]:
                bad.append("a trip to town changed the item levels: %s" % rows[-1])
            elif town != want and trip[0] == [town]:
                bad.append("the drops carry the town's level %d: %s" % (town, rows[-1]))
            elif straight[1] != [want] or trip[1] != [want]:
                bad.append("monster level is not the area level %d: %s" % (want, rows[-1]))
            elif straight[0] != [want] or trip[0] != [want]:
                bad.append("the drops are not at the area level %d (Median: the monster's level = the area level): %s" % (want, rows[-1]))
    finally:
        H("difficulty 0")
        goto(1)
        god(False)
    if not reader_follows:
        bad.append("the item level reader returned the same level for every item created with a different `ilvl=`")
    status = "FAIL" if bad else "PASS"
    add(name, status, "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def check_soulstealer():
    name = "Soulstealer heal (audit DC5): a Soulstealer boss that kills a player heals 10% of its max life, an ordinary monster does not"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    txt = mxl_text()
    # Control run: mxl-core-off.txt word `soulstealer` - the plugin leaves the heal out and a boss that kills a player must not heal.
    control = "soulstealer off: left out by mxl-core-off.txt" in txt
    if not control and "soulstealer on:" not in txt:
        return add(name, "BLOCKED", "`mxl` does not say `soulstealer on:`: %s" % next((l for l in txt.splitlines() if "soulstealer" in l), "no soulstealer line"))
    log, rows, bad = [], [], []

    def heals():
        m = re.search(r"soulstealer on:.*heals (\d+)", mxl_text())
        return int(m.group(1)) if m else -1

    def trial(label, classes, expect_heal):
        revive_if_dead()
        fight_ready()
        cls, ref, top = None, None, 0
        for cls in classes:  # the first class that spawns with a life stat (some Soulstealer rows are placeholders)
            ids = _spawn_ids(cls, 1)
            ref = "mon:%d" % ids[0] if ids else None
            top = rd(ref, 7) if ref else 0
            if top:
                setstat(ref, 6, top * 3 // 10)
                time.sleep(2.5)  # a monster that regenerates by itself (or is healed by its own script) cannot show the kill heal
                if rd(ref, 6) <= top * 0.35:
                    break
                log.append("%s: class %d healed itself from 30%% to %d%% with no kill" % (label, cls, 100 * rd(ref, 6) // top))
                top = 0
                continue
            log.append("%s: class %d %s" % (label, cls, "did not spawn" if not ids else "has no max life (%s)" % ref))
        if not top:
            bad.append("%s: none of the classes %s spawned with a max life" % (label, list(classes)))
            return
        for attempt in range(3):
            if attempt:  # the player was dead before the hit landed (see below): a fresh boss at 30 % life, the player revived
                revive_if_dead()
                fight_ready()
                ids = _spawn_ids(cls, 1)
                ref = "mon:%d" % ids[0] if ids else None
                top = rd(ref, 7) if ref else 0
                if not top:
                    bad.append("%s: the boss did not spawn again for try %d" % (label, attempt + 1))
                    return
            setstat(ref, 6, top * 3 // 10)  # 30% life, room to heal
            before, n0 = rd(ref, 6), heals()
            setstat("player", 7, BIG_LIFE)  # (a boss with life leech would otherwise heal from the damage it deals, which hides the kill heal)
            setstat("player", 6, 256)  # 1 life point: the killing blow deals ~1 point, so a boss's own life leech cannot refill it before the heal
            killed = False
            first_hit = ""
            for k in range(4):
                ok, line, lines = hv("hit player phys 2000000000 %s" % ref, "hit")
                log.extend(lines)
                if k == 0:
                    first_hit = line
                time.sleep(1.5)
                if player_dead(hstate()["player"]):
                    killed = True
                    break
                setstat("player", 6, 256)  # 1 life point: the killing blow deals ~1 point, so a boss's own life leech cannot refill it before the heal
            after, n1 = rd(ref, 6), heals()
            # the hit of an earlier try found the player dead already (`life=0->0`): something else took the one life point between the
            # `stat set` and the hit (the boss's own swing at a player it stands next to counts as its kill, so that is another source)
            if killed and "life=0->0" in first_hit and n1 == n0 and attempt < 2:
                log.append("%s: the player was dead before the hit (%s); last killer: %s; trying again" % (label, first_hit[:90], _last_killer()))
                continue
            break
        gain = after - before
        rows.append("%s (class %d, max life %d raw): player killed %s; boss life %d -> %d (gain %.1f%% of max); heals counter %d -> %d%s" % (
            label, cls, top, killed, before, after, 100.0 * gain / top, n0, n1, "; try %d" % (attempt + 1) if attempt else ""))
        log.append(rows[-1])
        if not killed:
            bad.append("%s: the player did not die" % label)
        elif expect_heal and control:
            if gain > 0.02 * top:
                bad.append("%s: part off but the boss healed: %s" % (label, rows[-1]))
        elif expect_heal and not (0.09 * top <= gain <= 0.12 * top and n1 == n0 + 1):
            bad.append("%s: expected a heal of about 10%% of max life and one counted heal: %s; last killer: %s" % (label, rows[-1], _last_killer()))
        elif not expect_heal and (gain > 0.02 * top or n1 != n0):
            bad.append("%s: an ordinary monster healed: %s" % (label, rows[-1]))
        revive_if_dead()

    def _last_killer():
        m = re.search(r"player deaths \d+ \(last killer: [^)]*\)", mxl_text())
        return m.group(0) if m else "not reported"

    try:
        # Zagraal and Kabraxis (Median: Soulstealer bosses). The Leoric row (2907) refills itself to full life when it kills a player
        # (a script of its own, measured: 30% -> 100% with no plugin heal counted), so it cannot show the 10% rule.
        for boss in (2049, 1852):
            trial("Soulstealer boss %d" % boss, (boss,), True)
        trial("control, ordinary monster", (719,), False)
    finally:
        revive_if_dead()
        goto(1)
    if control:
        name = "Soulstealer heal (audit DC5), CONTROL with the part off (mxl-core-off.txt `soulstealer`): a boss that kills a player does not heal"
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def check_cowtowns():
    name = "Cow portal (audit CR6): Wirt's Leg opens the Cow Level in any act's town"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    log, rows, bad = [], [], []
    base_level = rd("player", 12)
    try:
        for act, town in enumerate(TOWNS, 1):
            go(town)
            time.sleep(1.5)
            ensure_cube()
            H("cubeclear")
            H("difficulty 2")   # set in every town: the travel to another act can reset both
            H("quest 40 0 set")  # the cow portal handler wants Baal killed in the game's difficulty
            H("item leg cube")
            _, cf = H("gameflag 4 11 clear")  # the portal opens once per game (the engine's own flag): clear it so every town is tried
            log += ["clear: %s" % " / ".join(cf)]
            if not any("= 0" in l for l in cf):
                bad.append("act %d: `gameflag 4 11 clear` did not clear the flag: %s" % (act, cf))
            before = {o["id"] for o in hstate()["objs"]}
            ok, cl = H("cubecraft")
            time.sleep(1.5)
            new = new_portals(before)
            ok_f, fl = H("gameflag 4 11 get")
            flag = any("= 1" in l for l in fl)
            log.append("mxl: %s" % next((l.strip() for l in mxl_text().splitlines() if "Cow portals" in l), "no Cow portal counters"))
            if new and not flag:
                bad.append("act %d: portal opened but the once-per-game flag was not set" % act)
            if not new:
                # a Cow Level portal stands in the town from an earlier act's craft? count every portal object of that class
                log.append("act %d portals now: %s" % (act, [(o.get("class"), o.get("dest")) for o in hstate()["objs"] if o.get("class") in (59, 60, 600)]))
            dests = [o.get("dest") for o in new]
            rows.append("act %d town %d: cubecraft %s, new portal objects %s (dest %s)" % (act, town, "OK" if ok else "refused", [o["class"] for o in new], dests))
            log.append(rows[-1])
            log += cl
            if not ok or not new:
                bad.append(rows[-1])
            elif act > 1:
                # the portal has to work: the Cow Level (area 39) is an act 1 level
                area = None
                cow_ids = [o["id"] for o in new if o.get("dest") == 39] or [o["id"] for o in new]
                # Median's dungeon table (mxl_dungeons.h) lets Moo Moo Farm in on Hell from character level 110: the plugin's
                # lockout refuses the portal below that, which is the rule, so the level is raised for the walk-in
                setstat("player", 12, 110)
                for _ in range(3):
                    time.sleep(2)
                    ok_e, el = H("enter %d" % cow_ids[0])
                    log += el
                    if el and "moved" in el[0]:
                        break
                time.sleep(4)
                area = hstate()["player"].get("area")
                rows[-1] += "; entered it: area %s" % area
                log.append(rows[-1])
                if area != 39:
                    bad.append("act %d: entering the portal ended in area %s, not the Cow Level (39)" % (act, area))
                else:
                    # the way back: the Cow Level's own portal leads to the town it was made in (another act again)
                    time.sleep(3)
                    # the Cow Level holds the portals of the towns visited before as well: take the one that leads to this town
                    outs = [(o["id"], o.get("dest")) for o in hstate()["objs"] if o.get("class") in (59, 60, 600)]
                    log.append("portals in the Cow Level (id, destination): %s" % outs)
                    way_out = [i for i, d in outs if d == town]
                    for _ in range(3):
                        time.sleep(2)
                        ok_b, bl = H("enter %d" % way_out[0]) if way_out else (False, ["no portal to town %d here" % town])
                        log += bl
                        if bl and "moved" in bl[0]:
                            break
                    time.sleep(4)
                    back = hstate()["player"].get("area")
                    rows[-1] += "; back through the Cow Level's portal: area %s" % back
                    log.append(rows[-1])
                    if back != town:
                        bad.append("act %d: the portal out of the Cow Level ended in area %s, not the town %d" % (act, back, town))
            H("cubeclear")
    finally:
        H("difficulty 0")
        setstat("player", 12, base_level or 1)
        go(1)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [sh("cowtowns")], log)


def check_cubehotkey():
    name = "Cube hotkey (audit CR5): the transmute action transmutes the cube's items while the cube panel is open and does nothing while it is closed"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    ensure_cube()
    H("cubeclear")
    H("difficulty 2")
    H("quest 40 0 set")  # Wirt's Leg + nothing = the Cow portal recipe (Hell)
    log, bad, notes = [], [], []
    try:
        H("gameflag 4 11 clear")
        H("item leg cube")
        H("stashpage uia PanelManager ClosePanel HoradricCubeLayout")
        time.sleep(1.0)
        t0 = travel_counts()
        before = {o["id"] for o in hstate()["objs"]}
        ok, hl = H("hotkey transmute")
        time.sleep(1.5)
        t1 = travel_counts()
        closed_new = new_portals(before)
        c_closed = ok and t1["transmute_n"] == t0["transmute_n"] + 1 and t1["transmutes"] == t0["transmutes"] and not closed_new
        notes.append("cube closed: presses %s->%s, transmutes %s->%s (blocked %s), new portals %s" % (
            t0["transmute_n"], t1["transmute_n"], t0["transmutes"], t1["transmutes"], t1.get("blocked"), len(closed_new)))
        if not c_closed:
            bad.append("closed cube: " + notes[-1])
        ok_o, ol = H("stashpage uia PanelManager OpenPanel HoradricCubeLayout")
        log += ol
        time.sleep(1.5)
        t2 = travel_counts()
        shot = sh("cubehotkey_open")
        if t2.get("cube") != "open":
            bad.append("the cube panel did not open through the UI action (travel says cube %s; uia: %s)" % (t2.get("cube"), ol[:1]))
        before = {o["id"] for o in hstate()["objs"]}
        ok2, hl2 = H("hotkey transmute")
        time.sleep(2.0)
        t3 = travel_counts()
        new = new_portals(before)
        c_open = ok2 and t3["transmute_n"] == t2["transmute_n"] + 1 and t3["transmutes"] == t2["transmutes"] + 1 and bool(new)
        notes.append("cube open: presses %s->%s, transmutes %s->%s, new portal objects %s (the leg's Cow portal recipe ran)" % (
            t2["transmute_n"], t3["transmute_n"], t2["transmutes"], t3["transmutes"], [o["class"] for o in new]))
        if not c_open:
            bad.append("open cube: " + notes[-1])
        log += [t0["line"], t1["line"], t2["line"], t3["line"]] + hl + hl2
        H("stashpage uia PanelManager ClosePanel HoradricCubeLayout")
        time.sleep(0.8)
    finally:
        H("difficulty 0")
        H("cubeclear")
    add(name, "PASS" if not bad else "FAIL", "; ".join(notes) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def check_freerespec():
    name = "Free respec until level 50 (audit XP7): Akara resets stats and skills again and again at level 20; above level 50 the token is used up"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    base_level = rd("player", 12)
    saved = respec_stats()
    log, rows, bad = [], [], []
    try:
        for level, rounds in ((20, 3), (50, 2), (51, 2), (60, 2)):
            H("quest 1 0 set")
            H("quest 41 1 set")
            H("quest 41 0 clear")
            setstat("player", 12, level)
            results, bits = [], []
            for r in range(rounds):
                setstat("player", 0, (rd("player", 0) or 30) + 10)  # a point spent, so there is something to reset
                res = akara_respec(log)
                _, q = H("quest 41 dump")
                results.append(res)
                mb = re.search(r"bits0-15 ([01]+)", " ".join(q))
                bits.append(mb.group(1)[:2] if mb else "?")
                log.append("level %d respec %d: %s, quest 41 %s" % (level, r + 1, res, q[0] if q else "?"))
            rows.append("level %d: respec results %s, quest 41 bits 0-1 after each %s" % (level, results, bits))
            if results != [True] * rounds:
                bad.append("level %d: want every respec offered, got %s" % (level, results))
            if level > 50 and any(b != "01" for b in bits):
                # D2Sigma 0x9e600: above level 50 the token is put back (bit 0 clear, bit 1 set) after the bookkeeping
                bad.append("level %d: quest 41 bits 0-1 should read 01 (token put back) after each respec, got %s" % (level, bits))
    finally:
        restore_respec_stats(saved)
        if base_level is not None:
            setstat("player", 12, base_level)
        H("quest 41 1 set")
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def grit_formula(strength, level, clc1=1, clc2=0):
    """Median's passive (class skill, e.g. 1272): min(25, clc2 + (clc1 * strength) / (((450 + ((98 * level) * level) / 100) * 200) / 22500)) in integers."""
    denom = ((450 + ((98 * level) * level) // 100) * 200) // 22500
    return min(25, clc2 + (clc1 * strength) // max(denom, 1))


def check_grit():
    name = "Grit (audit XP9): Strength grants damage reduction (Median stat 184 = D2R 369) through the class passive"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    GRIT = 369
    log, rows, bad = [], [], []
    # the stat comes from the class passive (skills.txt passivestat1 = itemstatcost 184 on rows 1090 / 1179 / 1272 / 1358 / 1456 / 1542 / 1618,
    # D2R ids below by idmap.json): learn the one of the test character's class at level 1, as Median's characters have it
    passive = None
    for sid in (1162, 1251, 1344, 1430, 1528, 1614, 1690):
        ok, sl = H("setskill %d 1" % sid)
        log += sl
        if ok:
            passive = sid
            break
    if passive is None:
        return add(name, "BLOCKED", "no class passive could be learned (setskill refused all seven)", [], log)
    base_str = rd("player", 0)
    base_lvl = rd("player", 12)
    base_pts = rd("player", 4)
    vals = []
    packet = None
    # Strength steps below the cap point (the test character's own 400 Strength is above it: min(25, ..) hides the growth) at level 20, where
    # the divisor is 7 and a step of Strength moves the stat; the passive's stat is worked out when the passive is applied (skill level
    # change), so every step re-applies it (level 0, then 1)
    try:
        setstat("player", 12, 20)
        # `setskill` lowers a level by writing it (the passive's stat is not taken off), so there is no clean control here: the control is
        # the stat following the passive's formula at five Strength values, which nothing else on the character gives
        for target in (30, 100, 150, 200, 300):
            H("setskill %d 0" % passive)
            setstat("player", 0, target)
            H("setskill %d 1" % passive)
            time.sleep(0.5)
            s_, grit, lvl = rd("player", 0), rd("player", GRIT), rd("player", 12)
            want = grit_formula(s_, lvl)
            vals.append((target, s_, grit, lvl, want))
            rows.append("strength %s: grit %s (formula %s at level %s)" % (s_, grit, want, lvl))
        # a shift-click on Strength (25 points): the engine re-evaluates the passives when an attribute point is spent
        H("setskill %d 0" % passive)
        setstat("player", 0, 100)
        H("setskill %d 1" % passive)
        setstat("player", 4, 60)
        before = (rd("player", 0), rd("player", GRIT))
        H("pkt 3a 00 00 04 00")
        time.sleep(0.5)
        after = (rd("player", 0), rd("player", GRIT))
        packet = (before, after)
        rows.append("shift-click on Strength: strength %s -> %s, grit %s -> %s (formula %s -> %s)" % (
            before[0], after[0], before[1], after[1], grit_formula(before[0], 20), grit_formula(after[0], 20)))
        if after[1] != grit_formula(after[0], 20):
            bad.append("after spending points on Strength the stat is not recalculated: %s" % (packet,))
    finally:
        setstat("player", 12, base_lvl if base_lvl is not None else 150)
        if base_str is not None:
            setstat("player", 0, base_str)
        if base_pts is not None:
            setstat("player", 4, base_pts)
        H("setskill %d 0" % passive)
    log += rows
    grits = [v[2] for v in vals]
    if None in grits or not grits[-1] > grits[0]:
        bad.append("grit does not grow with Strength: %s" % grits)
    if any(g_ > 25 for g_ in grits if g_ is not None):
        bad.append("grit above the 25 cap: %s" % grits)
    mism = [v for v in vals if v[2] != v[4]]
    if mism:
        bad.append("grit differs from the passive's calc min(25, clc2 + clc1 * str / ((450 + 98 * lvl^2 / 100) * 200 / 22500)) at skill level 1: %s" % mism)
    add(name, "PASS" if not bad else "FAIL", "passive skill %d at level 1: " % passive + "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def _poll_innate(new_value, want_of, attr=2, timeout=2.0, hold=3.0):
    """(attribute, fire) after a stat point packet: the game applies it and the plugin refreshes the passive within a few frames.
    D2R's equipment recheck takes each item off and puts it back after a point (at once, and again up to about two seconds later), and
    the passive stats are worked out while the item is half back; the plugin applies the passives again when the item is back (lane
    ied-vanish). Poll up to `timeout` s until the attribute has its new value and the fire matches, then keep reading for `hold` s:
    the first reading that differs is returned (the vanishing is a later reading), else the last one."""
    t0 = time.time()
    while True:
        value, fire = rd("player", attr), rd("player", 48)
        if value == new_value and fire == want_of(value):
            break
        if time.time() - t0 > timeout:
            return value, fire
        time.sleep(0.1)
    t1 = time.time()
    while time.time() - t1 < hold:
        time.sleep(0.2)
        value, fire = rd("player", attr), rd("player", 48)
        if value != new_value or fire != want_of(value):
            return value, fire
    return value, fire


def check_ied():
    """Measure Median's hidden innate passive, IED and attribute-point refresh.

    Synthetic item stats use the same skill/synergy combination as pr375.
    `MXL_CONTROL=innate` expects the original dropped Dexterity passive.
    """
    name = "Innate elemental damage: passive formula, IED multiplier and Dexterity point refresh"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    close_menu()
    log, rows, bad = [], [], []
    saved = {s: rd("player", s) for s in (0, 1, 2, 3, 4, 12, 329, 424, 513)}
    sid = 2072  # Median 2000: innate fire from Dexterity
    control = "innate" in CONTROL
    part = _mxl_line("innate damage")
    log.append(part)
    if ("innate damage off" if control else "innate damage on: attribute and equip refresh on") not in part:
        bad.append("unexpected innate part status: " + part)
    try:
        # Magic quality carries the synthetic property list to the client.
        # A level-one Median cap keeps generated affixes/requirements low.
        H("unequip head")
        H("unequip rhand")
        setstat("player", 12, 120)
        setstat("player", 0, 100)
        setstat("player", 2, 199)
        setstat("player", 513, 50)
        setstat("player", 4, 10)
        native_class = hstate()["player"]["class"]
        H("class 2")  # !70 is a Necromancer throwing knife
        try:
            ok, lines = H("equip !70 q=2 ilvl=1 rhand")
            log += lines
            if ok:
                native_syn, native_ied = rd("player", 412, sid), rd("player", 513)
                H("passiverefresh")
                native_before = (rd("player", 2), rd("player", 48))
                H("pkt 3a 02 00 00 00")
                native_after = _poll_innate(native_before[0] + 1, lambda dex: native_before[1] if control else
                                            native_before[1] - native_syn * native_before[0] * (100 + native_ied) // 10000 +
                                            native_syn * dex * (100 + native_ied) // 10000)
                rows.append("native innate weapon !70: %s -> %s" % (native_before, native_after))
                flat = native_before[1] - native_syn * native_before[0] * (100 + native_ied) // 10000
                want = flat if control else flat + native_syn * native_after[0] * (100 + native_ied) // 10000
                if native_after[0] != native_before[0] + 1 or native_after[1] != want:
                    bad.append("native weapon expected fire %d: %s" % (want, rows[-1]))
                for cmd in ("stat player 97 2072", "stat player 412 2072", "req player"):
                    log += H(cmd)[1]
            else:
                bad.append("cannot equip native innate weapon !70")
        finally:
            H("unequip rhand")
            H("remove !70 1")
            H("class %d" % native_class)
            H("passiverefresh")
        setstat("player", 2, 200)
        setstat("player", 424, 0)
        setstat("player", 513, 0)
        ok, lines = H("equip 615 q=4 ilvl=1 97:2072=1 412:2072=100 head")
        log += lines
        if not ok:
            return add(name, "BLOCKED", "cannot equip hidden-passive cap", [], log)
        # The item went on through the equip step: the plugin applies the passives when it is back, no explicit refresh here
        # (the part off, the original drops the passive on an equip as well, so there is nothing to compare in the control run).
        if not control:
            equip_dex, equip_syn, equip_ied = rd("player", 2), rd("player", 412, sid), rd("player", 513)
            equip_want = equip_syn * equip_dex * (100 + equip_ied) // 10000
            t0 = time.time()
            while True:
                equip_fire = rd("player", 48)
                if equip_fire == equip_want or time.time() - t0 > 2:
                    break
                time.sleep(0.1)
            rows.append("fire right after the equip, no refresh call: %s (expected %d = syn1 %d x Dex %d x (100 + IED %d) / 10000)" % (
                equip_fire, equip_want, equip_syn, equip_dex, equip_ied))
            if equip_fire != equip_want or equip_want <= 0:
                bad.append(rows[-1])

        # Explicit native refresh isolates the data formula from the point-
        # spending path below; no base level is learned in this hidden skill.
        def refresh():
            H("passiverefresh")

        for dex, ied, marker in ((200, 0, 0), (200, 50, 0), (201, 51, 0), (200, 0, 3), (200, 0, 4)):
            setstat("player", 2, dex)
            setstat("player", 513, ied)
            setstat("player", 424, marker)
            refresh()
            got = rd("player", 48)
            actual_dex = rd("player", 2)
            actual_ied = rd("player", 513)
            syn = rd("player", 412, sid)
            coefficient = syn if marker < 3 else syn * 16 // 10
            want = coefficient * actual_dex * (100 + actual_ied) // 10000 if marker < 4 else 0
            rows.append("Dex=%s IED=%s marker=%s syn1=%s fire=%s expected=%s" % (actual_dex, actual_ied, marker, syn, got, want))
            if got != want:
                bad.append(rows[-1])
        setstat("player", 424, 0)
        setstat("player", 513, 50)
        setstat("player", 2, 200)
        setstat("player", 4, 10)
        refresh()
        before = (rd("player", 2), rd("player", 48))
        H("pkt 3a 02 00 00 00")  # one ordinary Dexterity point
        after = _poll_innate(before[0] + 1, lambda dex: 0 if control else dex * 150 // 100)
        for cmd in ("state", "stat player 97 2072", "stat player 424", "stat player 513", "stat player 412 2072", "skills", "req player"):
            log += H(cmd)[1]
        expected = after[0] * 150 // 100
        wanted = 0 if control else expected
        rows.append("Dexterity point: %s -> %s; damage expected=%d (%s)" % (before, after, wanted, "off control" if control else "live refresh"))
        if after[0] != before[0] + 1 or after[1] != wanted:
            bad.append(rows[-1])
        if not control:
            for attr in (0, 1, 3):
                setstat("player", 4, 10)
                refresh()
                value = rd("player", attr)
                H("pkt 3a %02x 00 00 00" % attr)
                actual, fire = _poll_innate(value + 1, lambda _attr: expected, attr)
                rows.append("attribute %d point: %d -> %d, fire=%s expected=%d" % (attr, value, actual, fire, expected))
                if actual != value + 1 or fire != expected:
                    bad.append(rows[-1])
        refresh()  # isolate outgoing hits from the attribute-point refresh path
        rows.append("after explicit refresh fire=%s" % rd("player", 48))
        fight_ready()
        refresh()
        setstat("player", 329, 0)
        mid = spawn_id()
        if mid is None:
            bad.append("cannot spawn hit target")
        else:
            ref = "mon:%d" % mid
            for stat in (36, 39, 41, 43, 45, 37, 369, 373):
                setstat(ref, stat, 0)
            for src in (128, 64):
                setstat(ref, 7, 2000000)
                setstat(ref, 6, 2000000)
                ok, lines = H("weaponhit %s %d" % (ref, src))
                log += lines
                text = " ".join(lines)
                m = re.search(r"fire=(\d+).*lost=(\d+)", text)
                want_fire = rd("player", 48) * 256 * src // 128
                rows.append("weapon hit SrcDam=%d: %s; expected raw fire=%s" % (src, text, want_fire))
                if not ok or not m or int(m[1]) != want_fire or int(m[2]) < want_fire // 256 or int(m[2]) <= 0:
                    bad.append(rows[-1])
            H("kill %d" % mid)
        # Capture the client stat and item-format output independently.
        for cmd in ("cstat 48", "tipfmt 444 100 512"):
            ok, lines = H(cmd)
            log += lines
    finally:
        H("unequip head")
        H("remove 615 1")
        for stat, value in saved.items():
            if value is not None:
                setstat("player", stat, value)
        H("passiverefresh")
    log += rows
    add(name, "FAIL" if bad else "PASS", "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)


def check_iedtip():
    """Sigma descfunc 35: truncate percentage before damage, max(Str,Dex).

    Off control retains the previous port's floating damage / summed attributes.
    """
    name = "Innate tooltip: classic percentage truncation and larger Strength/Dexterity"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    saved = {s: rd("player", s) for s in (0, 2, 513)}
    rows, bad, log = [], [], []
    client_saved = {}
    control = "innate" in CONTROL
    try:
        for stat in saved:
            ok, lines = H("cstat %d" % stat)
            log += lines
            match = re.search(r"cstat \d+:0 = (-?\d+)", " ".join(lines))
            if not ok or match is None:
                return add(name, "BLOCKED", "cannot read client fixture stats", [], log)
            client_saved[stat] = int(match[1])
        for stat, value in ((0, 100), (2, 199), (513, 5)):
            setstat("player", stat, value)
            # This is a formatter probe, so inject its inputs in the client's
            # unit too. Server base-stat writes do not transmit custom stats.
            log += H("cstat %d set %d" % (stat, value))[1]
        for layer, expected in ((512, 20 if control else 19), (1024, 31 if control else 19)):
            ok, lines = H("tipfmt 444 10 %d" % layer)
            log += lines
            text = " ".join(lines)
            rows.append(text)
            if not ok or not re.search(r"Damage: %d \(10\.5%%" % expected, text):
                bad.append("layer %d expected damage %d: %s" % (layer, expected, text))
    finally:
        for stat, value in saved.items():
            if value is not None:
                setstat("player", stat, value)
        for stat, value in client_saved.items():
            H("cstat %d set %d" % (stat, value))
        H("passiverefresh")
    add(name, "FAIL" if bad else "PASS", "; ".join(rows + bad), [], log)


def check_statclick():
    name = "Stat point shift-click (audit XP6): the client's shift-click packet (0x3a, count 4) spends 25 points, a plain click 1 (Median 2.14: 25 per shift-click)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    goto(1)
    txt = mxl_text()
    log, rows, bad = [], [], []
    if "shift-click on" not in txt:
        bad.append("`mxl` does not say `shift-click on`: %s" % next((l for l in txt.splitlines() if "shift-click" in l), "-"))
    saved = respec_stats()
    try:
        # the packet the stat panel's "+" sends: [0x3a][stat u16][count u16]; the server spends count + 1 points (D2R: shift-click = count 4 = 5 points)
        for stat, count, want in ((1, 0, 1), (1, 4, 25), (2, 4, 25), (3, 0, 1), (0, 4, 25)):
            setstat("player", 4, 60)
            v0 = rd("player", stat)
            ok, pl = H("pkt 3a %02x 00 %02x 00" % (stat, count))
            log += pl
            time.sleep(0.5)
            v1, pts = rd("player", stat), rd("player", 4)
            rows.append("stat %d count %d: used=%s, stat %s -> %s, unused points 60 -> %s (want +%d)" % (stat, count, ok, v0, v1, pts, want))
            if not ok or v0 is None or v1 is None or v1 - v0 != want or pts != 60 - want:
                bad.append(rows[-1])
        # fewer points than the click wants: the game's own rule refuses it, nothing is spent
        setstat("player", 4, 7)
        v0 = rd("player", 1)
        H("pkt 3a 01 00 04 00")
        time.sleep(0.5)
        v1, pts = rd("player", 1), rd("player", 4)
        rows.append("7 unused points, shift-click: stat %s -> %s, points 7 -> %s (the game's own check, not Median's)" % (v0, v1, pts))
    finally:
        restore_respec_stats(saved)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; WRONG: " + "; ".join(bad) if bad else ""), [], log)




# --- phase 4 lane p4-verify-b: town rules (SK4, NPC1, UQ5) ----------------------------------------------------------------------


def check_townmonsters():
    """Median IsTown through D2R's shared checks, then a real Scosglen monster following across the open town border.
    MXL_CONTROL=mediantowns repeats the same engine actions with the classifier replacement disabled.
    No monster relocation, path/collision edits or harness-side town decision is used.
    """
    name = "Median towns: Scosglen monsters cannot enter Tur Dulra"
    control = "mediantowns" in os.environ.get("MXL_CONTROL", "").split()
    towns = {1, 40, 75, 103, 109, 138, 139, 242, 243}
    vanilla = {1, 40, 75, 103, 109}
    expected = vanilla if control else towns
    rows, log, bad = [], [], []
    for level in sorted(towns | {0, 2, 137, 140, 241, 244, 270, 271, 100000}):
        ok, lines = H("town %d" % level)
        log += lines
        line = next((kv(s) for s in lines if s.startswith("town level=")), {})
        if not ok or int(line.get("istown", -1)) != int(level in expected):
            bad.append("level %d classifier: %s" % (level, line))
    rows.append("%s: level classifier for all nine towns, adjacent fields and invalid ids" % ("control" if control else "enabled"))
    god(True)
    try:
        for level in (138, 139, 243, 242):
            st = go(level)
            ok, lines = H("town")
            log += lines
            line = next((kv(s) for s in lines if s.startswith("town level=")), {})
            if st["player"].get("area") != level or not ok or int(line.get("roomtown", -1)) != int(not control):
                bad.append("town %d room check: %s" % (level, line))
        # Generate the connected outdoor level too: a direct debug arrival in a preset town
        # does not create its outdoor neighbour's rooms.
        go(271)
        # Prepare the player near the entrance with the real Teleport skill, streaming rooms.
        # No monster exists yet; the pursuit below uses walking only.
        H("setskill 54 1")
        H("stat player 9 set 256000")
        p = hstate()["player"]
        H("move %d %d walk" % (p["x"] + 7, p["y"]))
        time.sleep(2)
        for _ in range(64):
            p = hstate()["player"]
            if p["x"] >= 5955 or (p["x"] >= 5935 and 11280 <= p["y"] <= 11320):
                break
            H("stat player 8 set 256000")
            if p["x"] >= 5900 and p["y"] > 11300:
                H("cast 54 %d %d" % (p["x"] - 10, p["y"] - 35))
            else:
                H("cast 54 %d %d" % (min(p["x"] + 35, 5960), p["y"]))
            time.sleep(1)
            q = hstate()["player"]
            if abs(q["x"] - p["x"]) < 3:
                H("cast 54 %d %d" % (q["x"], q["y"] - 30))
                time.sleep(1)
        ok, lines = H("town edges", timeout=30)
        log += lines
        edges = [kv(s) for s in lines if s.startswith("town edge ")]
        edges = [e for e in edges if {int(e["al"]), int(e["bl"])} == {242, 271}]
        # levels.txt places Tur Dulra at Scosglen's eastern edge (relative OffsetX 194, OffsetY 123).
        # Take short steps toward the border if the loaded rooms still stop short of it.
        for _ in range(4):
            if edges:
                break
            p = hstate()["player"]
            H("move %d %d walk" % (p["x"] + (15 if p.get("area") == 271 else -40), p["y"]))
            time.sleep(3)
            ok, lines = H("town edges", timeout=30)
            log += lines
            edges = [kv(s) for s in lines if s.startswith("town edge ")]
            edges = [e for e in edges if {int(e["al"]), int(e["bl"])} == {242, 271}]
        if not edges:
            return add(name, "FAIL" if bad else "BLOCKED", "; ".join(rows + bad + ["no loaded passable Tur Dulra / Scosglen border; no movement claim"]), [sh("town-border-blocked")], log)

        def walk(x, y, area, seconds=12):
            H("move %d %d walk" % (x, y))
            end = time.time() + seconds
            retry = time.time() + 2
            while time.time() < end:
                time.sleep(.5)
                p = hstate()["player"]
                if p.get("area") == area and (area == 242 or abs(p.get("x", 0) - x) + abs(p.get("y", 0) - y) < 4):
                    return True
                if time.time() >= retry:
                    H("move %d %d walk" % (x, y))
                    retry = time.time() + 2
            return False

        start = None
        for e in edges[::max(1, len(edges) // 8)]:
            ax, ay, bx, by = (int(e[k]) for k in ("ax", "ay", "bx", "by"))
            if int(e["al"]) == 242:
                ax, ay, bx, by = bx, by, ax, ay
            dx, dy = bx - ax, by - ay  # field -> town
            fx, fy, tx, ty = ax - 8 * dx, ay - 8 * dy, bx + 8 * dx, by + 8 * dy
            ready = walk(fx, fy, 271, seconds=3)
            if not ready:
                # Fixture only: blink to the passable field approach before any monster is spawned.
                H("stat player 8 set 256000")
                H("cast 54 %d %d" % (fx, fy))
                time.sleep(1)
                p = hstate()["player"]
                ready = p.get("area") == 271 and abs(p["x"] - fx) + abs(p["y"] - fy) < 5
            if ready:
                start = (fx, fy, tx, ty)
                break
        if start is None:
            return add(name, "FAIL" if bad else "BLOCKED", "; ".join(rows + bad + ["player could not reach the field fixture"]), [sh("town-walk-blocked")], log)
        fx, fy, tx, ty = start
        # Scytheclaw is one of Scosglen's native mon1..6 rows, resolved through the same idmap as the build.
        import json
        with open(os.path.join(os.path.dirname(__file__), "..", "work", "named", "idmap.json"), encoding="utf-8") as f:
            monster = next(e["id"] for e in json.load(f)["monstats"] if e["row"] == 1978)
        # The field monster sometimes stays idle until the player is gone (seen in 2 of 3 runs): then the pursuit says nothing,
        # so the player walks back to the field and a new monster is spawned, up to three times. A monster in town in any attempt counts.
        crossed = False
        for attempt in range(3):
            ok, lines = H("spawn %d 1 %d %d" % (monster, fx - 4, fy + 3))
            log += lines
            match = next((re.search(r"spawned class \d+ id=(\d+)", s) for s in lines if "spawned class" in s), None)
            if not ok or not match:
                return add(name, "BLOCKED", "; ".join(rows + bad + ["engine refused the field Scytheclaw spawn"]), [], log)
            mid = int(match.group(1))
            time.sleep(2)
            initial = next((m for m in hstate()["mons"] if m["id"] == mid), {})
            log.append("field monster before retreat (attempt %d): %s" % (attempt + 1, initial))
            arrived = walk(tx, ty, 242)
            samples = []
            for _ in range(24):
                st = hstate()
                m = next((m for m in st["mons"] if m["id"] == mid), {})
                samples.append(m)
                log.append("retreat player area=%s at=%s,%s monster=%s" % (st["player"].get("area"), st["player"].get("x"), st["player"].get("y"), m))
                time.sleep(.5)
            crossed = crossed or any(m.get("area") == 242 for m in samples)
            engaged = bool(initial) and ((initial.get("mx"), initial.get("my")) != (fx - 4, fy + 3) or
                                         any(m and (m.get("mx"), m.get("my"), m.get("mode")) !=
                                             (initial.get("mx"), initial.get("my"), initial.get("mode")) for m in samples))
            if arrived and initial and engaged:
                break
            H("kill %d" % mid)
            if attempt < 2:
                walk(fx, fy, 271, seconds=8)
        rows.append("Scytheclaw %d: player walked into town=%s, monster entered town=%s, monster acted=%s" % (mid, arrived, crossed, engaged))
        if not arrived or not initial or not engaged:
            bad.append("inconclusive pursuit setup")
        if crossed != control:
            bad.append("control must reproduce entry; enabled must prevent it")
        H("kill %d" % mid)
        add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [sh("townmonsters")], log)
    finally:
        god(False)


def _skills_by_town(intown, limit=60, need_mana=True):
    """Selectable skills of the built skills.txt (any class: `setskill` gives them) without a restrict value: those with InTown 1 (intown True) or without
    it, by required level: [(id, name, mana)]. The mana filter keeps the skills whose cast costs something (D2R shows the result)."""
    t = _tsv(os.path.join(BUILT_EXCEL, "skills.txt"))
    h = t[0]
    col = {c: h.index(c) for c in ("skill", "*Id", "InTown", "mana", "leftskill", "rightskill", "restrict", "reqlevel", "passive", "charclass")}
    out = []
    for r in t[1:]:
        if len(r) < len(h) or r[col["passive"]] == "1" or r[col["restrict"]]:
            continue
        if (r[col["InTown"]] == "1") != intown:
            continue
        if need_mana and r[col["mana"]] in ("", "0"):
            continue
        if r[col["leftskill"]] != "1" and r[col["rightskill"]] != "1":
            continue
        out.append((int(r[col["reqlevel"]] or 0), int(r[col["*Id"]]), r[col["skill"]], r[col["mana"]]))
    out.sort()
    return [(i, n, m) for _lv, i, n, m in out[:limit]]


def _mxl_line(word):
    return next((ln for ln in mxl_text().splitlines() if word in ln), "")


def check_towncast():
    """Audit SK4 (P1.1.0 .. P2.1.0): Median's `InTown` column decides which skills may be cast in town (buffs, totems, warp, summons) and
    which may not. The game's usability test (`usable=`) does not look at the town; the town refusal is the unit staying in its town-neutral mode (5)
    instead of entering the skill's cast mode. So a cast counts as started when the mode after it is neither 1 (field neutral) nor 5. Skills the
    character cannot use at all (usable not 0: other class) are left out of the count. Skills with InTown must start in the Rogue Encampment,
    skills without it must not, and the same skills must start in the Blood Moor (control: the refusal is the town, not the skill)."""
    nm = "Skills in town (audit SK4): the InTown column decides"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    pos = _skills_by_town(True)
    neg = _skills_by_town(False, limit=12)
    if len(pos) < 5 or len(neg) < 3:
        return add(nm, "FAIL", "the data has too few skills to judge: %d with InTown, %d without" % (len(pos), len(neg)))
    log, rows, bad = [], [], []
    saved = {s_: rd("player", s_) for s_ in (12, 9, 8)}

    def prep(skill):
        setstat("player", 12, 90)
        setstat("player", 9, 5000 * 256)
        setstat("player", 8, 5000 * 256)
        H("setskill %d 5" % skill)

    def try_cast(skill):
        """'cast' (the skill started), 'town' (usable, but the unit did not leave its neutral mode) or 'class' (not usable by this character)."""
        drop_cursor_item(log)
        ok, lines = H("cast %d self" % skill)
        log.extend(lines)
        time.sleep(1.2)
        close_menu()
        text = " ".join(lines)
        us, md = re.search(r"usable=(\d+)", text), re.search(r"mode now (\d+)", text)
        if not us or us.group(1) != "0":
            return "class"
        return "cast" if md and md.group(1) not in ("1", "5") else "town"

    def sweep(skills):
        res = {"cast": [], "town": [], "class": []}
        for sid, sname, _mana in skills:
            prep(sid)
            res[try_cast(sid)].append("%d %s" % (sid, sname))
            kill_all_near()
        return res

    goto(1)
    close_menu()
    kill_all_near()
    r1 = sweep(pos)
    rows.append("InTown skills in the Rogue Encampment: %d started, %d refused, %d not judged (other class: %s)" % (
        len(r1["cast"]), len(r1["town"]), len(r1["class"]), ", ".join(r1["class"][:4])))
    if r1["town"]:
        bad.append("skills with InTown=1 refused in town: %s" % ", ".join(r1["town"]))
    if len(r1["cast"]) < 3:
        bad.append("fewer than 3 InTown skills could be judged (%d)" % len(r1["cast"]))
    r2 = sweep(neg)
    rows.append("skills without InTown in the Rogue Encampment: %d refused, %d started, %d not judged" % (len(r2["town"]), len(r2["cast"]), len(r2["class"])))
    if r2["cast"]:
        bad.append("skills without InTown started in town: %s" % ", ".join(r2["cast"]))
    if len(r2["town"]) < 3:
        bad.append("fewer than 3 skills without InTown could be judged (%d)" % len(r2["town"]))
    goto(2)
    close_menu()
    kill_all_near()
    r3 = sweep(neg)
    rows.append("the same skills in the Blood Moor: %d started, %d refused" % (len(r3["cast"]), len(r3["town"])))
    if len(r3["cast"]) < len(r2["town"]):
        bad.append("the control skills are not usable in the field either (refused: %s)" % ", ".join(r3["town"]))
    for s_, v in saved.items():
        if v is not None:
            setstat("player", s_, v)
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [], log)


NPC_TABLE_CLASSES = [148, 146, 154, 150, 147, 155, 266, 175, 176, 177, 178, 202, 200, 210, 201, 198, 199, 377, 378, 265, 244, 245, 251, 252, 253,
                     254, 255, 264, 246, 406, 367, 408, 257, 405, 297, 331, 513, 512, 511, 514, 515, 521, 520]


def check_npcheal():
    """Audit NPC1 (P2.2.0): in Median every NPC heals you when you talk to him. D2R runs the heal function at every talk but heals only at
    the NPCs whose entry in the static NPC table (0x237ea60) has byte +6 set; the plugin part `npcheal` sets the byte on all 43 entries. Each
    class of the table is spawned in Act 1's Blood Moor (no town crowd), the character is hurt to a quarter of life and mana, the NPC is
    talked to (`interact`) and life must be full. With the part off (control run, mxl-core-off.txt word `npcheal`) only the act healers heal."""
    nm = "NPC healing (audit NPC1): every NPC heals on talk"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    line = _mxl_line("town rules")
    control = "npc heal off" in line or "left out by mxl-core-off.txt" in line
    if not control and "npc heal on" not in line:
        return add(nm, "FAIL", "the `mxl` command has no `npc heal on` line: %s" % (line or "no town rules line"))
    res, log = {}, [line]

    def cur():
        p = hstate()["player"]
        a, b = p.get("life").split("/")
        return int(a), int(b)

    def one_try(cls):
        # a hostile monster of the Blood Moor next to the character (p4-stability run: three zombies at 2-3 yards, none of them ours)
        # keeps the character in its hit recovery and the NPC never opens: clear the field first
        try:
            if any(not m.get("npc") and float(m.get("dist") or 99) < 15 for m in hstate()["mons"]):
                kill_all_near()
        except (TypeError, ValueError):
            pass
        ok, _sl = H("spawn %d" % cls)
        if not ok:
            return "spawn failed"
        time.sleep(0.8)
        maxl, maxm = rd("player", 7), rd("player", 9)
        setstat("player", 6, int(maxl * 0.25))
        setstat("player", 8, int(maxm * 0.25))
        ok, lines = H("interact %d" % cls)
        log.extend(lines[:1])
        if not ok:
            return "interact failed"
        healed = False
        for _ in range(4):
            time.sleep(3)
            a, b = cur()
            if a >= b - max(8, b // 100):  # full life, give or take what drains it again within the 3 s (the quarter we set is far away)
                healed = True
                break
        if not healed:  # what the player and the NPC looked like when the heal did not come (a talk that never started, an NPC out of reach)
            a, b = cur()
            menu_ok, _ml = H("menu list")
            log.append("npc class %d: no heal, life %d/%d after 12 s; menu %s; near %s" % (
                cls, a, b, "open" if menu_ok else "closed", ["%s@%s mode %s" % (m.get("class"), m.get("dist"), m.get("mode")) for m in hstate()["mons"][:6]]))
        close_menu()
        H("kill nearest %d" % cls)
        time.sleep(0.5)
        return "healed" if healed else "no heal"

    def one(cls):
        r = one_try(cls)
        if r in ("no heal", "interact failed") and not control:  # a talk that did not start (the NPC was not in reach, the menu was refused, the NPC died): once more with a fresh NPC
            log.append("npc class %d: %s, trying once more" % (cls, r))
            kill_all_near()
            r = one_try(cls)
        return r

    pending = list(NPC_TABLE_CLASSES)
    for _round in range(5):  # the area fills up after ~14 spawns: leave and come back, retry what failed to spawn
        if not pending:
            break
        goto(2, timeout=60)
        close_menu()
        kill_all_near()
        for cls in list(pending)[:12]:
            r = one(cls)
            if not r.endswith("failed"):
                res[cls] = r
                pending.remove(cls)
        goto(1, timeout=60)
    healed = sorted(c for c, r in res.items() if r == "healed")
    not_healed = sorted(c for c, r in res.items() if r != "healed")
    log.append("healed %s; not healed %s; not reached %s" % (healed, not_healed, pending))
    if control:
        good = 1 <= len(healed) <= 12 and bool(not_healed)
        return add(nm, "PASS" if good else "FAIL", "control run (npcheal off): %d of %d NPC classes healed (D2R's act healers), %d did not: %s" % (
            len(healed), len(res), len(not_healed), not_healed), [], log)
    ok = not not_healed and len(res) >= 38
    add(nm, "PASS" if ok else "FAIL", "%d of the 43 NPC classes of D2R's table talked to; %d healed, %d did not %s; %d could not be reached (spawn failed) %s" % (
        len(res), len(healed), len(not_healed), not_healed, len(pending), pending), [], log)


def _tplock_levels():
    """Levels with Median's Tplock flag (levels.bin +0x155) as the plugin was built with them: plugin/src/mxl_dungeons.h (D2R ids; the
    built levels.txt has no such column)."""
    txt = open(os.path.join(REPO, "plugin", "src", "mxl_dungeons.h"), encoding="utf-8").read()
    return [int(a) for a, b in re.findall(r"\{(\d+), \d+, \d+, \d+, \{[^}]*\}, \d+, \d+, (\d+),", txt) if b != "0"]


def _tplock_refusals():
    m = re.search(r"portal refusals (-?\d+)", _mxl_line("town rules"))
    return int(m.group(1)) if m else None


def check_tplock():
    """Audit UQ5 (P1.6.0): Median's levels.txt column Tplock closes the Town Portal skill in some zones (Edge of Nothingness corridor and
    others). The plugin part `tplock` hooks the skill's do function 0x5822b0. The itemless Town Portal is cast in levels with the flag and must
    be refused (no portal object, no mana spent, the part's refusal counter rises); in the Blood Moor a portal opens. With the part off
    (control run, word `tplock`) the portal opens in the locked level too."""
    nm = "Town portals disabled in some zones (audit UQ5): Tplock levels"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    line = _mxl_line("town rules")
    control = "town portal lock off" in line or "left out by mxl-core-off.txt" in line
    if not control and "town portal lock on" not in line:
        return add(nm, "FAIL", "the `mxl` command has no `town portal lock on` line: %s" % (line or "no town rules line"))
    by_name, _t, _h = _skill_ids_by_name()
    tp = by_name.get("town_portal")
    locked = _tplock_levels()
    if tp is None or not locked:
        return add(nm, "BLOCKED", "no town_portal skill or no Tplock level in the data (%s, %s)" % (tp, locked))
    log, rows, bad = [line], [], []
    base = {s_: rd("player", s_) for s_ in (12, 9, 8)}

    def cast_tp():
        setstat("player", 12, 90)
        setstat("player", 9, 5000 * 256)
        setstat("player", 8, 5000 * 256)
        H("setskill %d 5" % tp)
        before = _portal_ids()
        m0 = rd("player", 8)
        use0 = _skill_usable(tp)  # 0 = usable; another code (a cooldown from the cast before) makes the cast do nothing
        ok, lines = H("cast %d self" % tp)
        if not ok:  # the verb itself failed (the character was still busy from the teleport in): once more
            log.extend(lines)
            time.sleep(2.5)
            ok, lines = H("cast %d self" % tp)
        log.extend(lines)
        log.append("town portal skill usable code before the cast: %s; cast: %s" % (use0, lines[:1]))
        time.sleep(3.0)
        new = _portal_ids() - before
        return ok, bool(new), m0 - rd("player", 8)

    reached = 0
    try:
        c0 = _tplock_refusals()
        for lv in locked:
            if reached >= (1 if control else 3):
                break
            st = goto(lv, timeout=45)
            if st["player"].get("area") != lv:
                log.append("level %d: not reachable with goto" % lv)
                continue
            reached += 1
            kill_all_near()
            ok, opened, spent = cast_tp()
            rows.append("level %d (Tplock): cast %s, portal %s, mana spent %d" % (lv, "accepted" if ok else "refused", "OPENED" if opened else "none", spent >> 8))
            if control:
                if not opened:
                    bad.append("control run (tplock off): no portal in level %d" % lv)
            elif opened or spent > 0:
                bad.append("a portal opened (%s) or mana was spent (%d) in the locked level %d" % (opened, spent >> 8, lv))
        if not reached:
            bad.append("no Tplock level could be reached with goto (%s)" % locked)
        c1 = _tplock_refusals()
        rows.append("refusals %s -> %s" % (c0, c1))
        if not control and reached and (c0 is None or c1 is None or c1 - c0 < reached):
            bad.append("the part's refusal counter did not rise by %d (%s -> %s)" % (reached, c0, c1))
        goto(2, timeout=60)
        kill_all_near()
        time.sleep(8)  # the cooldown of a portal opened above
        ok, opened, spent = cast_tp()
        rows.append("Blood Moor (no Tplock): cast %s, portal %s" % ("accepted" if ok else "refused", "opened" if opened else "NONE"))
        if not opened:
            bad.append("no portal in the Blood Moor (the control)")
    finally:
        for s_, v in base.items():
            if v is not None:
                setstat("player", s_, v)
        goto(1)
    add(nm, "PASS" if not bad else "FAIL", ("control run (tplock off): " if control else "") + "; ".join(rows + bad), [], log)


# --- phase 4 lane p4-verify-b: charm limit (IC5) --------------------------------------------------------------------------------


def _charm_uniques():
    """Unique rows of the built uniqueitems.txt whose base item is a charm (itemtypes chain to `char`, relics excluded):
    [(row, code, carry1, nolimit, in the plugin's unique-limit table, 'width x height')]."""
    u = _tsv(os.path.join(BUILT_EXCEL, "uniqueitems.txt"))
    uh = u[0]
    uc, c1, nl = uh.index("code"), uh.index("carry1"), uh.index("nolimit")
    m = _tsv(os.path.join(BUILT_EXCEL, "misc.txt"))
    mh = m[0]
    mc, mt_, mw, mhh = mh.index("code"), mh.index("type"), mh.index("invwidth"), mh.index("invheight")
    base = {r[mc]: (r[mt_], r[mw], r[mhh]) for r in m[1:] if len(r) > mhh}
    t = _tsv(os.path.join(BUILT_EXCEL, "itemtypes.txt"))
    tc, e1, e2 = t[0].index("Code"), t[0].index("Equiv1"), t[0].index("Equiv2")
    par = {r[tc]: [r[e1], r[e2]] for r in t[1:] if len(r) > e2}

    def is_charm(tp, depth=0):
        return tp == "char" or (depth < 6 and any(is_charm(p, depth + 1) for p in par.get(tp, []) if p))

    limited = {r[0] for r in _unique_limit_rows()}
    out = []
    for i, r in enumerate(u[1:]):
        if len(r) > uc and r[uc] in base and base[r[uc]][0] != "reli" and is_charm(base[r[uc]][0]):
            out.append((i, r[uc], r[c1] == "1", r[nl] == "1", i in limited, "%sx%s" % (base[r[uc]][1], base[r[uc]][2])))
    return out


def check_charmlimit():
    """Audit IC5 (P1.0.0): only one charm of a kind may be carried (Median's fixed bug: more than one). D2R's rule is the `carry1` column of
    uniqueitems.txt (placement refuses a second copy), Median's own limits are the uniqueitems2 table (plugin part uniquelimits, tested by
    `uniquelimits`). Unique charms flagged carry1 (not in the plugin's table, so D2R alone decides) and ones with a plugin limit of one: the first
    copy is created in the backpack, the second must be refused (`item` places through the game's rules); a unique charm without either rule
    takes two copies (the control). Lane carry1-fix adds the half "different carry1 uniques are carried together" (`_charmlimit_different`)."""
    nm = "Charm limit (audit IC5): one charm of a kind"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    rows_all = _charm_uniques()
    limits = {r[0]: r for r in _unique_limit_rows()}
    carry = [r for r in rows_all if r[2] and not r[4]][:3]
    plug = [r for r in rows_all if r[4] and limits[r[0]][1] == 0 and limits[r[0]][2] == 1][:3]
    free = [r for r in rows_all if not r[2] and not r[4]][:4]
    if not (carry or plug) or not free:
        return add(nm, "FAIL", "the data has no charm unique to test (carry1 and not limited %d, single-copy limits %d, without a rule %d of %d charm uniques)" % (
            len(carry), len(plug), len(free), len(rows_all)))
    log, rows, bad = [], [], []
    goto(1)
    close_menu()

    def count(row, code):
        return len([i for i in items(hstate(), code, 0) if i.get("unique") == row and i.get("quality") == 7])

    def two(row, code, size):
        H("packclear")
        drop_cursor_item(log)
        ok1, l1 = H("item %s inv uniq=%d" % (code, row))
        ok2, l2 = H("item %s inv uniq=%d" % (code, row))
        log.extend(l1[:1] + l2[:1])
        n = count(row, code)
        H("remove %s 9" % code)
        return ok1, ok2, n

    for kind, group in (("carry1", carry), ("plugin limit 1", plug)):
        for row, code, _c1, _nl, _lim, size in group:
            ok1, ok2, n = two(row, code, size)
            rows.append("%s unique %d (%s, %s): first %s, second %s, %d in the backpack" % (kind, row, code, size, "placed" if ok1 else "refused", "PLACED" if ok2 else "refused", n))
            if not ok1:
                bad.append("could not place the first copy of unique %d (%s)" % (row, code))
            elif ok2 or n != 1:
                bad.append("%s unique %d (%s): a second copy was carried (%d in the backpack)" % (kind, row, code, n))
    twice = 0
    for row, code, _c1, _nl, _lim, size in free:
        ok1, ok2, n = two(row, code, size)
        rows.append("control unique %d (%s, %s, no carry rule): first %s, second %s, %d in the backpack" % (row, code, size, "placed" if ok1 else "refused", "placed" if ok2 else "refused", n))
        twice += 1 if (ok1 and ok2 and n == 2) else 0
    if not twice:  # a control that cannot be placed twice for another reason (the harness found no second cell) is not counted against the rule
        bad.append("no unique charm without a carry rule took two copies (%d tried)" % len(free))
    _charmlimit_different(rows_all, limits, rows, bad, log)
    H("packclear")
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [], log)


def _carry_stats():
    """(table loads, carry1 uniques, records rewritten) of the `unique carry` line of the `mxl` command, None without it."""
    m = re.search(r"unique carry on.*\(loads (\d+), carry1 uniques (\d+), rewritten (\d+)\)", mxl_text())
    return tuple(int(v) for v in m.groups()) if m else None


def _charmlimit_different(rows_all, limits, rows, bad, log):
    """Lane carry1-fix (plugin 0.66.0, part `uniquecarry`): D2R 3.3 refuses a carry1 unique when a carried one has the same carry1 NUMBER
    (unique record +0x30), and Median gives 1 to all 89 carry1 uniques, so a second DIFFERENT carry1 unique (the Butcher's Tooth, then the
    Laser Focus Crystal) was refused. With the part each carry1 unique has its own number: different carry1 uniques are carried together,
    through `item ... inv` and through a pickup from the ground (packet 0x16, to-inventory flag); a second copy of the same one is still
    refused on both paths. Control run (MXL_CONTROL=uniquecarry): the second different one is refused, as before."""
    control = "uniquecarry" in CONTROL
    carry1 = [r for r in rows_all if r[2] and r[5] == "1x1"]
    picks, codes, groups = [], set(), set()
    for r in carry1:  # three carry1 uniques on different bases that the plugin's own limit table keeps apart (distinct groups)
        grp = limits[r[0]][1] if r[0] in limits else 0
        if r[1] not in codes and (grp == 0 or grp not in groups) and len(picks) < 3:
            picks.append(r)
            codes.add(r[1])
            groups.add(grp)
    native = [r for r in rows_all if r[2] and not r[4] and r[1] not in codes][:1]  # one that only D2R's own rule governs (not in the plugin's table)
    if len(picks) < 3:
        bad.append("the data has no three carry1 uniques on different 1x1 bases (%d found)" % len(picks))
        return
    stats = _carry_stats()
    if control:
        rows.append("control (uniquecarry off): `unique carry` line %s" % next((l for l in mxl_text().splitlines() if "unique carry" in l), "-"))
        if stats is not None:
            bad.append("control run: the part uniquecarry should be off, the mxl command reports %s" % (stats,))
    elif stats is None or stats[2] == 0 or stats[1] == 0:
        bad.append("the `mxl` command has no `unique carry on` line with rewritten carry1 numbers: %s" % (stats,))
        return
    else:
        rows.append("unique carry: %d table loads, %d carry1 uniques, %d numbers rewritten" % stats)

    def count(row, code):
        return len([i for i in items(hstate(), code, 0) if i.get("unique") == row and i.get("quality") == 7])

    def make(row, code, where):
        ok, lines = H("item %s %s uniq=%d" % (code, where, row))
        d = next((kv(l) for l in lines if l.startswith("item ")), {})
        return (d if ok and "id" in d else None), lines

    def ground_pickup(row, code):
        """A ground copy within 4 subtiles of the player, picked up with packet 0x16 (to-inventory flag 1): True when it landed in the backpack."""
        for _ in range(10):
            d, lines = make(row, code, "ground")
            if d is None:
                log.extend(lines[:1])
                return None
            ok, fl = H("iflags %s" % d["id"])
            f = next((kv(l) for l in fl if l.startswith("iflags")), {})
            ok, st = H("state")
            m = re.search(r"player id=\d+ .*? x=(\d+) y=(\d+)", st[0] if st else "")
            if m and ((int(f.get("x", "0")) - int(m.group(1))) ** 2 + (int(f.get("y", "0")) - int(m.group(2))) ** 2) <= 9:
                before = count(row, code)
                H("pkt 16 " + _le(int(d["id"]), int(f.get("x", "0")), int(f.get("y", "0")), 1))
                time.sleep(0.6)
                return count(row, code) > before
        bad.append("no ground drop of unique %d landed within 4 subtiles of the player" % row)
        return None

    def fresh():
        H("packclear")
        drop_cursor_item(log)
        for r in picks + native:
            H("remove %s 9" % r[1])

    want = not control  # the fix lets different carry1 uniques be carried together
    A, B, C = picks
    fresh()
    # 1. `item ... inv`: A, then B, then C (three different carry1 uniques, one backpack)
    got = []
    for r in (A, B, C):
        d, lines = make(r[0], r[1], "inv")
        got.append(d is not None)
        if d is None:
            log.extend(lines[:1])
    n = [count(r[0], r[1]) for r in (A, B, C)]
    rows.append("%sitem inv: carry1 uniques %s (%s) placed %s, in the backpack %s" % ("control: " if control else "", [r[0] for r in (A, B, C)],
                " ".join(r[1] for r in (A, B, C)), got, n))
    if want and (got != [True, True, True] or n != [1, 1, 1]):
        bad.append("different carry1 uniques %s were not all placed through `item inv` (placed %s, in the backpack %s)" % ([r[0] for r in (A, B, C)], got, n))
    if not want and (got[0] is not True or got[1] or got[2] or n[0] != 1):
        bad.append("control run: only the first carry1 unique should be placed (placed %s, in the backpack %s)" % (got, n))
    # 2. a second copy of the same one is refused (inv and ground), the first stays
    if want:
        d, lines = make(A[0], A[1], "inv")
        rows.append("item inv: second copy of unique %d %s, in the backpack %d" % (A[0], "PLACED" if d else "refused", count(A[0], A[1])))
        if d is not None or count(A[0], A[1]) != 1:
            bad.append("a second copy of unique %d was carried through `item inv`" % A[0])
        landed = ground_pickup(A[0], A[1])
        rows.append("ground pickup: second copy of unique %d %s, in the backpack %d" % (A[0], "LANDED" if landed else "refused", count(A[0], A[1])))
        if landed is None or landed or count(A[0], A[1]) != 1:
            bad.append("a second copy of unique %d was picked up from the ground (landed %s)" % (A[0], landed))
    # 3. ground pickup of a different carry1 unique next to a carried one
    fresh()
    d, lines = make(A[0], A[1], "inv")
    if d is None:
        bad.append("could not place unique %d for the ground test: %s" % (A[0], lines[:1]))
    else:
        landed = ground_pickup(B[0], B[1])
        rows.append("%sground pickup: carry1 unique %d next to the carried %d: %s, in the backpack %d + %d" % (
            "control: " if control else "", B[0], A[0], "LANDED" if landed else "refused", count(A[0], A[1]), count(B[0], B[1])))
        if landed is not None and landed != want:
            bad.append("%s: ground pickup of a different carry1 unique %s" % ("control run (should be refused)" if control else "fix", "landed" if landed else "was refused"))
    # 4. a carry1 unique that only D2R's own rule governs (not in the plugin's table) next to a plugin-limited one, and its second copy
    fresh()
    if native:
        n0 = native[0]
        d1, _l1 = make(A[0], A[1], "inv")
        d2, _l2 = make(n0[0], n0[1], "inv")
        rows.append("%sitem inv, D2R-only rule: unique %d then %d: %s / %s" % ("control: " if control else "", A[0], n0[0], "placed" if d1 else "refused", "placed" if d2 else "refused"))
        if d1 is None or (d2 is not None) != want:
            bad.append("carry1 uniques %d and %d: first %s, second %s (want second %s)" % (
                A[0], n0[0], "placed" if d1 else "refused", "placed" if d2 else "refused", "placed" if want else "refused"))
        if want and d2 is not None:
            d3, _l3 = make(n0[0], n0[1], "inv")
            rows.append("item inv, D2R-only rule: second copy of unique %d %s" % (n0[0], "PLACED" if d3 else "refused"))
            if d3 is not None:
                bad.append("D2R-only carry1 unique %d: a second copy was carried" % n0[0])
    else:
        rows.append("no carry1 unique outside the plugin's table to test D2R's own rule")
    fresh()


# --- phase 4 lane p4-verify-b: area level (MU3, engine / data part) -------------------------------------------------------------


def check_arealevel():
    """Audit MU3 (P1.0.0): Median can show the area level in the corner. The drawing is client UI (docs/unported.md); the engine / data part is the
    number it shows: levels.txt MonLvlEx per difficulty, which the game must use for the monsters it generates (plugin part monlevel). Here the
    areas with the most different Hell area levels (up to the highest, 150) are visited, a monster is spawned in each difficulty and its level
    (stat 12) must be the area's level; the three areas of `monlevel` are not repeated."""
    nm = "Area level (audit MU3, engine/data part): monsters take levels.txt MonLvlEx of the difficulty in the highest areas"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    areas, mons = _monlevel_tables()
    town = set(_town_levels()) if "_town_levels" in globals() else set()
    byhell = {}
    for a, lv in sorted(areas.items()):
        if lv[2] and a not in (2, 76, 111) and a not in town and a < 256:
            byhell.setdefault(lv[2], a)
    pick = [byhell[k] for k in sorted(byhell, reverse=True)][:3] + [byhell[k] for k in sorted(byhell)][:2]
    bad, rows, log = [], [], []
    god(True)
    try:
        H("players 1")
        done = 0
        for area in pick:
            st = goto(area, timeout=45)
            if st["player"].get("area") != area:
                log.append("area %d: not reachable with goto" % area)
                continue
            for diff in (0, 2):
                H("difficulty %d" % diff)
                ids = _spawn_ids(18, 1)
                if not ids:
                    bad.append("area %d diff %d: nothing spawned" % (area, diff))
                    continue
                got, want = rd("m%d" % ids[0], 12), areas[area][diff]
                rows.append("area %d %s: monster level %s, levels.txt MonLvlEx %d" % (area, ("Normal", "Nightmare", "Hell")[diff], got, want))
                if got != want:
                    bad.append(rows[-1])
                H("kill %d" % ids[0])
            done += 1
        if done < 3:
            bad.append("only %d of the %d areas could be visited (%s)" % (done, len(pick), pick))
    finally:
        god(False)
        H("difficulty 0")
        goto(1)
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [], log)


# --- phase 4 lane p4-verify-b: D2 bugfix list (OT4) ---------------------------------------------------------------------------------


def check_bugfixes():
    """Audit OT4 (P1.0.0): the D2 bugs Median fixed, as far as they are engine behaviour that the harness reaches: life / mana above 32,767 do not roll
    over, a percentage above the 8 / 16-bit range (resist 286 = 256 + 30, 65586 = 65536 + 50) does not wrap, the damage of one hit is applied in full
    far above the old caps (up to 2^31 - 1), a character in a shapeshift state (wolf 139, bear 140) or with an aura state (might 33) dies from a
    lethal hit, loses the states with its death and is alive after the respawn (no ghost state, no aura left). The states are SET here (`setstate`);
    the other rows of the D2 bugfix list have their own checks: `strdex` (str / dex glitch), `wwproc` (whirlwind chance-to-cast) and `morphdeath`
    (a Druid casts the morph skills for real and dies morphed), see docs/unported.md."""
    nm = "D2 bugfixes (audit OT4): no rollover or wrap of life / mana / percentages / damage, no immortal morph, no ghost state"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    log, rows, bad = [], [], []
    goto(2)
    close_menu()
    kill_all_near()
    god(False)
    # `hit player` without an attacker uses the nearest live monster that can fight and the player itself when there is none
    # (a hit of the player on the player is ignored: result 0, nothing lost); kill_all_near just removed every monster
    atk = spawn_attacker()
    if atk is None:
        return add(nm, "BLOCKED", "no attacker monster for the hits on the player")
    P = 256
    big = 60000 * P
    saved = {stt: rd("player", stt) for stt in (7, 6, 9, 8)}  # put back at the end: a max mana of 60000 makes every later mana test regenerate in a blink
    # 1. life and mana above 32,767
    for stt in (7, 6, 9, 8):
        setstat("player", stt, big)
    got = [rd("player", stt) for stt in (6, 7, 8, 9)]
    rows.append("life / max life / mana / max mana set to 60000: %s" % [None if v is None else v // P for v in got])
    if any(v is None or v < 50000 * P for v in got):  # only a rollover matters here; the pools of a long run may start a regen or a drain apart
        bad.append("life or mana above 32,767 did not hold: %s" % got)
    hv("hit player phys %d %s" % (1000 * P, atk), "hit")
    hv("hit player mana %d %s" % (1000 * P, atk), "hit")
    life, mana = rd("player", 6), rd("player", 8)
    rows.append("after a hit of 1000 and a `mana` hit of 1000: life %s, mana %s" % (None if life is None else life // P, None if mana is None else mana // P))
    if life is None or not (50000 * P < life < big):
        bad.append("life after a hit of 1000 left 60000 range: %s" % life)
    if mana is None or not (45000 * P < mana <= rd("player", 9)):
        bad.append("mana after a drain of 1000 left the 60000 range: %s" % mana)
    # 2. percentages above the 8 / 16-bit range
    fields = {}
    for res in (0, 75, 255, 286, 300, 1000, 65586, 2 ** 31 - 1):
        for stt in (7, 6):
            setstat("player", stt, big)
        setstat("player", 39, res)
        ok, line, ls = hv("hit player fire 100000 %s" % atk, "hit")
        log.extend(ls)
        m = re.search(r"field=(-?\d+)", line)
        fields[res] = int(m.group(1)) if m else None
    rows.append("fire damage left of 100000 by fire resist (capped by the max resist): %s" % ", ".join("%d: %s" % (k, v) for k, v in fields.items()))
    if None in fields.values():
        bad.append("a hit gave no field value")
    else:
        if not fields[0] > fields[75] >= fields[255] > 0:
            bad.append("resist does not reduce in order: 0 -> %s, 75 -> %s, 255 -> %s" % (fields[0], fields[75], fields[255]))
        for res in (286, 300, 1000, 65586, 2 ** 31 - 1):
            if fields[res] != fields[255]:
                bad.append("fire resist %d wraps: %s left, %d at 255" % (res, fields[res], fields[255]))
    setstat("player", 39, 0)
    # 3. damage far above the old caps
    god(True)
    ids = _spawn_ids(18, 1)
    if not ids:
        bad.append("no monster for the damage test")
    else:
        mon = "mon:%d" % ids[0]
        start = 2000000000
        for amt in (1000000000, 1500000000):
            setstat(mon, 7, start)
            setstat(mon, 6, start)
            ok, line, ls = hv("hit %s phys %d" % (mon, amt), "hit")
            log.extend(ls)
            left = rd(mon, 6)
            rows.append("hit of %d on a monster with %d life: %s left" % (amt, start, left))
            if left is None or abs((start - amt) - left) > 2000000:
                bad.append("a hit of %d took %s of %d life" % (amt, None if left is None else start - left, start))
        setstat(mon, 7, start)
        setstat(mon, 6, start)
        hv("hit %s phys 2147483647" % mon, "hit")
        left = rd(mon, 6)
        rows.append("hit of 2^31 - 1: %s left" % left)
        if left != 0:
            bad.append("a hit of 2^31 - 1 did not kill a monster with %d life (%s left)" % (start, left))
        H("kill %d" % ids[0])
    god(False)
    # 4. death in a shapeshift or aura state, respawn
    setstat("player", 7, 1000 * P)
    setstat("player", 6, 1000 * P)
    on = []
    for stt in (139, 140, 33):
        H("setstate player %d 1" % stt)
        on.append(stt)
    ok, line, ls = hv("hit player phys %d %s" % (5000 * P, atk), "hit")
    log.extend(ls)
    time.sleep(2)
    p = hstate()["player"]
    dead = bool(p) and player_dead(p)
    left = [stt for stt in on if "hasstate %d: 1" % stt in " ".join(H("hasstate %d" % stt)[1])]
    rows.append("lethal hit in states wolf / bear / might: %s, states left on the dead character: %s" % ("died" if dead else "STILL ALIVE", left or "none"))
    if not dead:
        bad.append("the character in a shapeshift / aura state survived a lethal hit")
    if left:
        bad.append("states %s stayed on the dead character" % left)
    revive_if_dead()
    time.sleep(3)
    p = hstate()["player"]
    alive = bool(p) and not player_dead(p)
    again = [stt for stt in on if "hasstate %d: 1" % stt in " ".join(H("hasstate %d" % stt)[1])]
    rows.append("after the respawn: %s, mode %s, life %s, states on: %s" % ("alive" if alive else "NOT ALIVE", p.get("mode") if p else None, p.get("life") if p else None, again or "none"))
    if not alive:
        bad.append("the character is not alive after the respawn")
    if again:
        bad.append("states %s are on after the respawn" % again)
    for stt in on:  # a failed run must not leave the wolf / bear form and Might on for the checks after it (Might drains mana)
        H("setstate player %d 0" % stt)
    H("kill %s" % atk.split(":")[1])
    for stt, v in saved.items():
        if v is not None:
            setstat("player", stt, v)
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [], log)

# ------------------------------------------------------------------ lane p4-quests-verify (docs/unported.md rows of quests / objects / D2 bugfixes)
def _plugin_counter(st, pattern):
    m = re.search(pattern, st.get("plugin", ""))
    return int(m.group(1)) if m else None


def _ground_items():
    """Items (no gold) on the ground: `h dump ground nogold` count and the codes."""
    ok, lines = H("dump ground nogold")
    n = 0
    codes = []
    for ln in lines:
        m = re.match(r"ground items (\d+)", ln)
        if m:
            n = int(m.group(1))
        c = re.search(r"code=(\S+)", ln)
        if c and ln.startswith("ground "):
            codes.append(c.group(1))
    return n, codes


def check_towerkill():
    """Quest 5 (Forgotten Tower) through a real Countess kill. The Countess is spawned, put on quest 5's unit list with
    `questreg` (the level code does that for the real one) and killed, so D2R's own kill event reaches the quest handler
    (0x5e10c0). A: the killer already holds quest 5 bit 0 while the quest object is active (another player's quest in the same
    game): Median's guard (`TowerKillHook`) skips the handler, so no reward and no second end of the quest; with the off word
    `quests` (MXL_CONTROL="quests") the vanilla handler runs and completes quest 5 a second time. B (guard on only): the quest is
    open for the killer and the natural reward path runs: the `Quest Countess` class (counter of `mxl`), the drops on the
    ground, quest bits 0 and 13."""
    name = "Quest 5 repeat guard and natural Countess kill (real kill event, questreg)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ctl = "quests" in CONTROL
    rows, bad, log = [], [], []
    saved = _qbits(5)
    if saved is None:
        return add(name, "BLOCKED", "could not read quest 5")
    goto(25)
    close_menu()
    H("difficulty 0")
    god(True)

    def counters():
        t = mxl_text()
        m = re.search(r"quest rewards .*\(hellforge (\d+), countess (\d+), prison of ice (\d+)\)", t)
        return tuple(int(x) for x in m.groups()) if m else None

    def kill_countess():
        ok, l = H("spawn 45")
        m = re.search(r"id=(\d+)", " ".join(l))
        if not m:
            return False
        mid = int(m.group(1))
        ok2, l2 = H("questreg %d 5" % mid)
        log.extend(l + l2)
        H("kill %d" % mid)
        time.sleep(4)
        return ok2

    def setup(bit0):
        for b in (0, 0xd, 0xe, 0xf):
            H("quest 5 %d clear" % b)
        if bit0:
            H("quest 5 0 set")
        H("questobj 5 poke 312 0")  # the Countess-dead / reward-given flags (quest data +0x118 / +0x119): an earlier check
        H("questobj 5 poke 313 0")  # (questrewards' `countessreward`) leaves the reward given, and it is rolled once per player
        H("questobj 5 poke 17 1")  # the finish branch of the handler needs byte +0x11
        log.extend(H("questobj 5 active 1")[1])

    try:
        # A: repeat
        setup(True)
        s0 = _plugin_counter(hstate(), r"tower skips=(\d+)")
        n0, _c0 = _ground_items()
        c0 = counters()
        reached = kill_countess()
        s1 = _plugin_counter(hstate(), r"tower skips=(\d+)")
        n1, codes = _ground_items()
        c1 = counters()
        b13 = _qbits(5)[13] == "1"
        rows.append("A, bit 0 already set: tower skips %s -> %s, ground items %d -> %d %s, Countess class rolls %s -> %s, bit 13 %s" % (
            s0, s1, n0, n1, codes[:6], c0, c1, "set" if b13 else "clear"))
        if not reached:
            bad.append("the Countess could not be put on quest 5's list")
        if ctl:
            # the hook is off: no counter moves; what the vanilla handler does with the repeat is reported, not required
            if not (s1 == s0):
                bad.append("control run: the guard counter moved with the hook off (%s -> %s)" % (s0, s1))
            rows.append("control: the vanilla handler %s the quest again" % ("completed" if b13 or n1 > n0 else "did not complete"))
        elif not (s1 is not None and s0 is not None and s1 == s0 + 1 and n1 == n0 and not b13):
            bad.append("the guard did not skip the second reward (skips %s -> %s, items %d -> %d, bit 13 %s)" % (s0, s1, n0, n1, b13))
        # B: natural
        setup(False)
        n2, _ = _ground_items()
        c2 = counters()
        reached = kill_countess()
        s2 = _plugin_counter(hstate(), r"tower skips=(\d+)")
        n3, codes = _ground_items()
        c3 = counters()
        bits = _qbits(5)
        rows.append("B, quest open: tower skips %s, Countess class rolls %s -> %s, ground items %d -> %d %s, quest 5 bits 0 / 13 = %s / %s" % (
            s2, c2, c3, n2, n3, codes[:8], bits[0], bits[13]))
        if not ctl and not (reached and s2 == s1 and c2 and c3 and c3[1] == c2[1] + 1 and n3 > n2 and bits[0] == "1" and bits[13] == "1"):
            bad.append("the natural kill did not run the reward path (skips %s, rolls %s -> %s, items %d -> %d, bits %s)" % (s2, c2, c3, n2, n3, bits[:16]))
    finally:
        _qrestore(5, saved)
        god(False)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad) + ("; control run: off word quests" if ctl else ""), [], log)


def portal_ids():
    """{id: distance} of the portal objects (classes 59, 60, 600) of the game (a portal's partner in the other level is listed too)."""
    ids = {}
    for ln in H("objects")[1]:
        m = re.match(r"object id=(\d+) class=(59|60|600) mode=\d+ dist=(\d+)", ln)
        if m:
            ids[int(m.group(1))] = int(m.group(3))
    return ids


def check_lockwarp():
    """The dungeon lockout's quest-table condition (`0x5d810` (3), `Entry::questLock`) through real warps. A cube-made portal to a
    quest-locked level (`portal 66`: Median level 66, quest 13) and the real portal function (`enter <id>`, `0x58f680`): refused
    while quest 13 has none of its bits (the `lockout refused` counter goes up, the character stays in town), taken once bit 1 is
    set (the character stands in the level). The same for level 73 (Duriel's Lair), where D2R's own check `0x516a50` sits in front
    as well. Control run MXL_CONTROL="lockout": the plugin hook is off and D2R's own portal function does not take the cube portal at all (the
    character stays in town): the warp and its quest decision are the plugin's."""
    name = "Dungeon lockout quest condition: real portal warps into quest-locked levels (refused, then taken)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ctl = "lockout" in CONTROL
    rows, bad, log = [], [], []
    saved = _qbits(13)
    if saved is None:
        return add(name, "BLOCKED", "could not read quest 13")
    god(True)
    try:
        for level in ((66,) if ctl else (66, 73)):
            goto(40)
            close_menu()
            H("difficulty 0")
            for b in (0, 1, 0xe, 0xf):
                H("quest 13 %d clear" % b)
            lc = [] if ctl else H("lockcheck %d" % level)[1]  # the verb needs the lockout hook
            before = portal_ids()
            okp, lp = H("portal %d" % level)
            log += lc + lp
            after = portal_ids()
            new = sorted((i for i in after if i not in before), key=lambda i: after[i])  # the nearest new one is the town side
            if not okp or not new:
                bad.append("level %d: no portal could be opened (%s)" % (level, lp[:1]))
                continue
            pid = new[0]  # the portals of the earlier levels stay in town: enter this one by its id
            r0 = lockout_counts(hstate())[0]
            ok, le = H("enter %d" % pid)
            time.sleep(4)
            st = hstate()
            area0 = st["player"].get("area")
            r1 = lockout_counts(st)[0]
            log += le
            rows.append("level %d without the quest: %s -> area %s, lockout refused %s -> %s" % (level, " ".join(lc)[:40], area0, r0, r1))
            if ctl:
                # D2R's own portal function (0x58f680) does not take a cube portal to a Median level (partner level id -1): the warp and its
                # quest decision are the plugin's, so with the hook off the character stays in town and nothing is counted
                rows.append("control: D2R's own portal function %s" % ("did not take the portal" if area0 == 40 else "moved the character"))
                if area0 != 40:
                    bad.append("control run: D2R's own function moved the character to area %s" % area0)
                continue
            if not (area0 == 40 and r1 == (r0 or 0) + 1):
                bad.append("level %d without quest 13: not refused (area %s, refused %s -> %s)" % (level, area0, r0, r1))
                continue
            H("quest 13 1 set")
            log += H("enter %d" % pid)[1]
            time.sleep(4)
            area1 = hstate()["player"].get("area")
            rows.append("level %d with quest 13 bit 1: area %s" % (level, area1))
            if area1 != level:
                bad.append("level %d with quest 13 bit 1: the portal did not take the character (area %s)" % (level, area1))
    finally:
        _qrestore(13, saved)
        god(False)
        revive_if_dead()
        goto(40)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad) + ("; control run: off word lockout" if ctl else ""), [], log)


def check_tyraelwalk():
    """Tyrael's travel gate through the real objects. Act 4 (area 103): Tyrael's portal object (class 566, operate function 73,
    mode 2 = open) is used with quest 28 clear: the character is moved to Harrogath (area 109) and D2R's own function sets quest 28
    bit 0. Back in area 103 the Tyrael menu is read with quest 28 clear (no travel line, handler 0x1162f0) and set (the line is
    there); clicking it (`menu <line>`) takes the character to Harrogath and sets the Harrogath waypoint (number 30)."""
    name = "Tyrael travel: portal object sets quest 28, the travel line walks to Harrogath and sets the waypoint"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    rows, bad, log = [], [], []
    saved = {q: _qbits(q) for q in (26, 28)}
    if None in saved.values():
        return add(name, "BLOCKED", "could not read quests 26 / 28")
    god(True)
    try:
        goto(103)
        close_menu()
        H("quest 26 0 set")
        H("quest 28 0 clear")
        ok, lo = H("object 566")
        m = re.search(r"id=(\d+)", " ".join(lo))
        log += lo
        if not (ok and m):
            return add(name, "BLOCKED", "the portal object could not be made", [], log)
        oid = int(m.group(1))
        log += H("objmode %d 2" % oid)[1]
        ok, lop = H("operate %d 73" % oid)
        log += lop
        time.sleep(4)
        area = hstate()["player"].get("area")
        bit = _qbits(28)[0]
        rows.append("portal object 566 used with quest 28 clear: %s, area %s, quest 28 bit 0 = %s" % (" ".join(lop)[:70], area, bit))
        if not (area == 109 and bit == "1"):
            bad.append("the portal walk did not move the character to Harrogath and set quest 28 (area %s, bit %s)" % (area, bit))
        # the menu with quest 28 clear: no travel line; with it set: the line, and a click on it
        goto(103)
        close_menu()
        H("quest 26 0 set")
        H("quest 28 0 clear")
        npc_menu(367)  # the first talk plays the long speech and can miss the menu
        close_menu()
        time.sleep(1)
        menu = npc_menu(367) or []
        has0 = any("handler=image+0x1162f0" in ln for ln in menu)
        close_menu()
        H("quest 28 0 set")
        menu = npc_menu(367) or []
        has1 = any("handler=image+0x1162f0" in ln for ln in menu)
        log += menu
        idx = next((int(re.search(r"line (\d+)", ln).group(1)) for ln in menu if "handler=image+0x1162f0" in ln), None)
        H("waypoint n 30 clear")
        wp0 = wpbit(30)
        area2 = None
        if idx is not None:
            log += H("menu %d" % idx)[1]
            time.sleep(6)
            area2 = hstate()["player"].get("area")
        wp1 = wpbit(30)
        rows.append("travel line with quest 28 clear: %s, set: %s; clicked: area %s, Harrogath waypoint %s -> %s" % (has0, has1, area2, wp0, wp1))
        if has0 or not has1 or area2 != 109 or wp1 != 1:
            bad.append("travel line gate or walk wrong (line without quest %s, with quest %s, area %s, waypoint %s)" % (has0, has1, area2, wp1))
    finally:
        for q, bits in saved.items():
            _qrestore(q, bits)
        close_menu()
        god(False)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [sh("tyraelwalk")], log)


def check_worldstone():
    """Object functions 70 (Worldstone / Throne objects 563 and 569, plugin `ThroneHook`, off word `worldstone`) and 31 (Gidbinn's
    altar, class 252, D2R's own function). Objects are made next to the character (`object`), opened with `objmode 2` and used
    through the real operate functions (`operate`). Function 70: Baal's flag (quest 36 byte +0xa6) clear: no move; set but quest 39
    (the lockout's questLock of levels 131 / 132) not done: refused by the lockout; quest 39 done: 131 -> 132; and from 132 the
    function takes the character back to 131 (D2R's own function only goes 131 -> 132 and returns 0 elsewhere; control run
    MXL_CONTROL="worldstone"). Function 31: refused while quest 19 bit 7 is set, taken with it clear (object mode 0 -> 1)."""
    name = "Object functions 70 (Worldstone / Throne, both ways, lockout) and 31 (Gidbinn altar) through real operate calls"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ctl = "worldstone" in CONTROL
    rows, bad, log = [], [], []
    saved = {q: _qbits(q) for q in (19, 39)}
    if None in saved.values():
        return add(name, "BLOCKED", "could not read quests 19 / 39")
    god(True)

    def make(cls, mode):
        ok, lo = H("object %d" % cls)
        m = re.search(r"id=(\d+)", " ".join(lo))
        log.extend(lo)
        if not (ok and m):
            return None
        oid = int(m.group(1))
        log.extend(H("objmode %d %d" % (oid, mode))[1])
        return oid

    def operate(oid, fn):
        """(result, area afterwards, object mode afterwards)"""
        ok, lo = H("operate %d %d" % (oid, fn))
        log.extend(lo)
        text = " ".join(lo)
        m = re.search(r"result (-?\d+)", text)
        mm = re.search(r"mode now (\d+)", text)
        time.sleep(3)
        return (int(m.group(1)) if m else None), hstate()["player"].get("area"), (int(mm.group(1)) if mm else None)

    try:
        goto(131)
        close_menu()
        H("difficulty 0")
        for b in (0, 1, 0xe, 0xf):
            H("quest 39 %d clear" % b)
        thr = make(569, 2)
        if thr is None:
            return add(name, "BLOCKED", "object 569 could not be made", [], log)
        H("questobj 36 poke 166 0")
        r_a, a_a, _m = operate(thr, 70)
        H("questobj 36 poke 166 1")
        refused0 = lockout_counts(hstate())[0]
        r_b, a_b, _m = operate(thr, 70)
        refused1 = lockout_counts(hstate())[0]
        H("quest 39 0 set")
        r_c, a_c, _m = operate(thr, 70)
        rows.append("Throne object 569 in area 131: Baal flag clear -> result %s, area %s; flag set, quest 39 clear -> result %s, area %s (lockout refused %s -> %s); quest 39 done -> result %s, area %s" % (
            r_a, a_a, r_b, a_b, refused0, refused1, r_c, a_c))
        if ctl:
            # D2R's own function: it only needs the flag (+0xa6), goes 131 -> 132 with no lockout (quest 39 still clear: r_b / a_b) and,
            # standing in 132, finds nothing to do (r_c)
            if not (r_a == 0 and a_a == 131 and r_b == 1 and a_b == 132 and refused1 == refused0 and r_c == 0 and a_c == 132):
                bad.append("control run: D2R's own function behaved differently (results %s %s %s, areas %s %s %s)" % (r_a, r_b, r_c, a_a, a_b, a_c))
        elif not (r_a == 0 and a_a == 131 and r_b == 0 and a_b == 131 and refused1 == (refused0 or 0) + 1 and r_c == 1 and a_c == 132):
            bad.append("function 70 forward: wrong results")
        if a_c == 132:
            chamber = make(563, 2)
            r_d, a_d, _m = operate(chamber, 70) if chamber is not None else (None, None, None)
            rows.append("Worldstone object 563 in area 132: result %s, area %s%s" % (r_d, a_d, " (control: D2R's function does not go back)" if ctl else ""))
            if ctl:
                if not (r_d == 0 and a_d == 132):
                    bad.append("control run: D2R's own function should not go back from 132 (result %s, area %s)" % (r_d, a_d))
            elif not (r_d == 1 and a_d == 131):
                bad.append("function 70 back: the object in 132 did not take the character to 131 (result %s, area %s)" % (r_d, a_d))
        else:
            bad.append("the forward move did not reach area 132, so the way back was not tried")
        # function 31: Gidbinn's altar; D2R's function is the same code as D2Sigma's (quest 17 byte +0x11, quest 19 bits 0 / 7 / 8)
        goto(103)
        close_menu()
        for b in (0, 7, 8):
            H("quest 19 %d clear" % b)
        alt = make(252, 0)
        if alt is None:
            bad.append("object 252 could not be made")
        else:
            H("questobj 17 poke 17 1")
            H("quest 19 7 set")
            r1, _a, m1 = operate(alt, 31)
            H("quest 19 7 clear")
            r2, _a, m2 = operate(alt, 31)
            rows.append("Gidbinn altar 252: with quest 19 bit 7 set -> result %s (mode %s); clear -> result %s (mode %s)" % (r1, m1, r2, m2))
            if not (r1 == 0 and m1 == 0 and r2 == 1 and m2 == 1):
                bad.append("function 31 results wrong (%s/%s, %s/%s)" % (r1, m1, r2, m2))
        txt = mxl_text()
        line = next((ln for ln in txt.splitlines() if "dungeon lockout" in ln), "")
        rows.append("`mxl`: %s" % line.strip()[-190:])
        if not ctl and "Worldstone / Throne objects both ways" not in line:
            bad.append("`mxl` does not report the Worldstone hook")
        if ctl and "Worldstone / Throne objects off" not in line:
            bad.append("`mxl` does not report the Worldstone hook as off in the control run")
    finally:
        for q, bits in saved.items():
            _qrestore(q, bits)
        H("questobj 36 poke 166 0")
        god(False)
        revive_if_dead()
        goto(40)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad) + ("; control run: off word worldstone" if ctl else ""), [], log)


def check_hitfloor():
    """Missile hit function 20 (`0x45ec20`) with its second calc floored at 0 (byte patch `0x45edce`, off word `hitfloor`) in play.
    A Median missile of that function (missiles row 206) is fired at a skeleton that cannot move (velocity -100 %), its life is read
    before and after in raw 1/256 points, with skill 0 at level 0 and level 1 as the missile's skill (`missile 206 dx dy skill
    level`); every shot has to take life. The control run (MXL_CONTROL="hitfloor") shows the old bytes and fires the same shots.
    The second calc is the hit's target-count cap (`0x464fe0` compares the targets already hit with it), so the floor only matters
    for a skill whose `calc1` is 0 or less and a missile row with no value of its own; no skill tried (0-69) gave 0 targets, and the
    notes make no claim about a difference in damage."""
    name = "Missile hit 20 floor: low-damage missile hit on a monster, life before / after (patched vs control)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ctl = "hitfloor" in CONTROL
    rows, bad, log = [], [], []
    goto(2)
    close_menu()
    kill_all_near()
    god(False)
    H("stat player 6 0 set 2000000")
    # The missile's damage at skill level 0 is the character's own flat damage (stats 21 / 22 physical, 48 / 49 fire, 50 / 51 lightning):
    # the earlier runs had it from a Way of the Phoenix left on by another check (its fire damage), a fresh game or a start state that
    # took the stance off has none and every level 0 shot did nothing. Set a flat damage and put the values back at the end.
    flat0 = {st_: stat_of(H("stat player %d" % st_)[1]) for st_ in (21, 22, 48, 49, 50, 51)}
    for st_, v_ in ((21, 40), (22, 60), (48, 40), (49, 60), (50, 40), (51, 60)):
        H("stat player %d 0 set %d" % (st_, v_))
    gaps = " ".join(H("gaps")[1])
    m = re.search(r"hit20=(\w+) hit20_patched=(\d)", gaps)
    rows.append("bytes %s patched=%s" % (m.group(1) if m else None, m.group(2) if m else None))
    if not m or m.group(2) != ("0" if ctl else "1"):
        bad.append("hit 20 patch state does not match this run (control %s): %s" % (ctl, m.group(0) if m else gaps[:80]))

    def shot(skill, level):
        mid = spawn_id()
        time.sleep(1.5)
        H("stat m%d 67 0 set -100" % mid)
        H("stat m%d 6 0 set 2000000" % mid)
        st = hstate()
        me = st["player"]
        mon = next((x for x in st["mons"] if x.get("id") == mid), None)
        if not mon:
            return None
        dx, dy = mon.get("mx", 0) - me["x"], mon.get("my", 0) - me["y"]
        a = stat_of(H("stat m%d 6" % mid)[1])
        log.extend(H("missile 206 %d %d %d %d" % (dx, dy, skill, level))[1])
        time.sleep(3)
        b = stat_of(H("stat m%d 6" % mid)[1])
        H("kill %d" % mid)
        return None if a is None or b is None else a - b

    for skill, level in ((0, 0), (0, 1)):
        d = [shot(skill, level) for _ in range(5)]
        hit = [x for x in d if x]
        rows.append("skill %d level %d: life taken per shot (raw 1/256) %s" % (skill, level, d))
        if len(hit) < 4:
            bad.append("skill %d level %d: only %d of 5 shots took life" % (skill, level, len(hit)))
    kill_all_near()
    H("stat player 6 0 set 2000000")
    for st_, v_ in flat0.items():
        H("stat player %d 0 set %d" % (st_, v_ or 0))
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad) + ("; control run: off word hitfloor" if ctl else ""), [], log)


def check_strdex():
    """D2 bugfix list (audit OT4), the str / dex glitch in D2R's code: an item whose requirement the character misses is inactive
    (its stats are not on the character), becomes active when a worn item adds the strength and goes inactive again when that
    item is taken off (D2's glitch keeps it active). Armor '841' (reqstr 455) with fire resist 77 and a ring with +600 strength,
    in both orders of putting them on. The other two rows of the list have the checks `wwproc` (whirlwind 1306) and `morphdeath` (werebear
    morph 1375, werewolf 1380, wereowl 1364). The first attempt (check strdex, lane p4-quests-verify) used 1234 / 1303 and was refused with
    code 5: those are the `Id` values of Median's original table (assets/median/2_txt/skills.txt: Whirlwind 1234, Werebear Morph 1303);
    the build renumbers these rows by +72 (`*Id` 1306 / 1375, and 1234 / 1303 became `energize` / `runemaster`). `_skill_ids_by_name()` reads
    the built table and is right."""
    name = "D2 bugfix str / dex glitch: a worn item loses its stats when the strength item is taken off (both orders)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    rows, bad, log = [], [], []
    goto(2)
    close_menu()
    H("unequip lring")
    H("unequip body")
    level0 = rd("player", 12)
    setstat("player", 12, 90)  # the armor has a level requirement too: only the strength is the question

    def val(stat):
        return stat_of(H("stat player %d" % stat)[1])

    s0, r0 = val(0), val(39)
    rows.append("base strength %s, fire resist %s" % (s0, r0))
    if s0 is None or s0 >= 455:
        bad.append("the character already meets the armor's requirement (strength %s)" % s0)
    log += H("equip 841 39=77 body")[1]
    a1 = val(39)
    log += H("equip rin 0=600 lring")[1]
    a2, s2 = val(39), val(0)
    H("unequip lring")
    a3 = val(39)
    rows.append("armor first: fire resist %s (inactive), with the strength ring (str %s) %s, ring off %s" % (a1, s2, a2, a3))
    if not (a1 == r0 and a2 is not None and a2 >= r0 + 77 and a3 == r0):  # >=: the ring is a rare with random affixes, it may carry resistance itself
        bad.append("armor first: the stats of the armor did not follow the strength (%s, %s, %s from %s)" % (a1, a2, a3, r0))
    H("unequip body")
    log += H("equip rin 0=600 lring")[1]
    log += H("equip 841 39=77 body")[1]
    b1 = val(39)
    H("unequip lring")
    b2 = val(39)
    rows.append("ring first: fire resist %s (active), ring off %s" % (b1, b2))
    if not (b1 is not None and b1 >= r0 + 77 and b2 == r0):
        bad.append("ring first: the armor kept its stats after the ring came off (%s, %s from %s)" % (b1, b2, r0))
    H("unequip body")
    if level0:
        setstat("player", 12, level0)
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [], log)


# ------------------------------------------------------------------ lane p4-ww-morph (docs/unported.md row "D2 bugfix list")
WW_SKILL = 1306  # Median's Barbarian Whirlwind `whirlwind_2` (charclass bar, srvdofunc 76); D2R's own Whirlwind 151 has no class in Median


def _missiles_seen(cls=58):
    """Missiles of one class the harness tracker has seen since `missiles reset` (class 58: Fire Bolt's missile)."""
    m = re.search(r"class %d x(\d+)" % cls, " ".join(H("missiles")[1]))
    return int(m.group(1)) if m else 0


def _mon_lives(cls):
    return {m["id"]: m["life"] for m in hstate()["mons"] if m.get("class") == cls}


def _ww_group(cls=18):
    """Five monsters with the engine's top life next to the player (the spin and the attacks hit them and cannot kill them)."""
    for _ in range(6):
        H("kill nearest %d" % cls)
    ids = [tough_target(cls) for _ in range(5)]
    time.sleep(2)
    return ids


def check_wwproc():
    """Whirlwind chance-to-cast (docs/unported.md "D2 bugfix list", audit OT4). Median fixes D2's bug that a Whirlwind hit does not
    trigger a chance to cast on striking (stat 198) or on attack (stat 195). A ring with Fire Bolt level 5 at 100 % (skill 36, layer
    (36 << 6) | 5) is worn by the Barbarian; four spins with Median's Whirlwind (`whirlwind_2`, 1306, cast at a point 10 sub-tiles
    away, because a cast at an adjacent monster is a normal attack) through five monsters are counted in Fire Bolt missiles (class 58)
    and compared with eight normal attacks with the same ring and with spins without the ring (none). D2R refuses the item-event cast
    while the caster has state 54 (uninterruptable), which a spin holds: without the plugin's hook (plugin/src/whirlwind.cpp, off
    word `wwproc`, control run MXL_CONTROL="wwproc") the spins give 0 missiles and the attacks still do."""
    name = "Whirlwind chance-to-cast: a spin triggers 'cast on striking' (198) and 'cast on attack' (195) like a normal attack"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    ctl = _ctl("wwproc")
    rows, bad, log = [], [], []
    if not switch_character("MxlBarb", "barbarian", 4):
        return add(name, "BLOCKED", "the Barbarian test character cannot be opened")
    revive_if_dead()
    goto(2)
    close_menu()
    kill_all_near()
    god(False)
    txt = mxl_text()
    m = re.search(r"whirlwind procs (on|off)[^\n]*", txt)
    rows.append("plugin line: %s" % (m.group(0)[:150] if m else "missing"))
    if not m or m.group(1) != ("off" if ctl else "on"):
        bad.append("the `mxl` whirlwind procs line does not match this run (control %s): %s" % (ctl, m.group(0)[:100] if m else "no line"))
    log += H("setskill %d 20" % WW_SKILL)[1]
    layer = (36 << 6) | 5

    def spins(n):
        hurt = 0
        for k in range(n):
            p = hstate()["player"]
            dx, dy = ((10, 10), (-10, 10), (-10, -10), (10, -10))[k % 4]
            before = _mon_lives(18)
            log.extend(H("cast %d %d %d" % (WW_SKILL, p["x"] + dx, p["y"] + dy))[1])
            time.sleep(2.5)
            after = _mon_lives(18)
            hurt += sum(1 for i in before if i in after and after[i] < before[i])
        return hurt

    def attacks(n):
        for _ in range(n):
            log.extend(H("cast 0 nearest")[1])
            time.sleep(1.2)

    # spins without the ring: the missiles below can only come from procs
    _ww_group()
    H("missiles reset")
    spins(2)
    base = _missiles_seen()
    rows.append("spins without the ring: %d class-58 missiles" % base)
    if base:
        bad.append("class-58 missiles appeared without the ring (%d): the counts below prove nothing" % base)
    for stat in (198, 195):
        H("unequip lring")
        H("unequip rring")
        ok, lines = H("equip rin %d:%d=100 lring" % (stat, layer))
        log += lines
        if not ok:
            bad.append("the ring with stat %d did not equip: %s" % (stat, lines[-1:] if lines else ""))
            continue
        _ww_group()
        H("missiles reset")
        hurt = spins(4)
        ww = _missiles_seen()
        H("missiles reset")
        attacks(8)
        at = _missiles_seen()
        rows.append("stat %d: 4 spins hurt %d monsters and made %d Fire Bolts; 8 attacks made %d" % (stat, hurt, ww, at))
        if hurt < 2:  # soak run 2026-10-25: 3 of 4 spins hurt a monster and the procs came anyway; the proof is the Fire Bolts below
            bad.append("stat %d: the spins hurt only %d monsters" % (stat, hurt))
        if at < 1:
            bad.append("stat %d: the normal attacks made no Fire Bolt (the ring does not work at all)" % stat)
        if ctl:
            if ww:
                bad.append("stat %d: control run (wwproc off) but the spins made %d Fire Bolts" % (stat, ww))
        elif ww < 1:
            bad.append("stat %d: no Fire Bolt during the spins (D2R refuses the cast while the spin holds state 54)" % stat)
    H("unequip lring")
    kill_all_near()
    m = re.search(r"\((\d+) casts let through during a spin, (\d+) refused", mxl_text())
    rows.append("`mxl` counters after the run: %s" % (m.group(0) if m else "missing"))
    if not m or (int(m.group(1)) == 0) != ctl:
        bad.append("the plugin's counter of casts let through during a spin does not match this run (control %s): %s" % (ctl, m.group(0) if m else "missing"))
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad) + ("; control run: off word wwproc" if ctl else ""), [], log)


# Druid forms of Median's own skill table (charclass dru, srvdofunc 116): the skill, the form state it sets and the weapon it needs
# (skills.txt itypea1: axe / swor / knif; the weapon rows with no requirement are 114, 100 and 142)
MORPH_FORMS = (("werebear_morph", 1375, 140, "114"), ("werewolf_form", 1380, 300, "100"), ("wereowl_form", 1364, 278, "142"))


def _state_on(state):
    return bool(re.search(r"hasstate %d: 1\b" % state, " ".join(H("hasstate %d" % state)[1])))


def check_morphdeath():
    """Real shapeshift immortality (docs/unported.md "D2 bugfix list", audit OT4). Median fixes D2's bug that a character who dies
    while morphed stays alive or stuck. A Druid test character (MxlDru, created in the slot when missing) casts Median's morph skills
    for real (`cast <skill> self`, not `setstate`): werebear_morph 1375 (state 140), werewolf_form 1380 (300), wereowl_form 1364 (278); each
    needs a weapon of its type in the hand (axe / sword / knife), so a zero-requirement weapon is put on first.
    Each form takes a lethal hit (`hit player phys`); the bear is also killed by a real monster (Andariel). The character has to die
    (mode 0 / 17, life 0), the form state has to end with the death and the respawn (Esc) has to give a living character in town
    without the form. The Barbarian is played again afterwards."""
    name = "Real shapeshift death: Druid casts werebear / werewolf / wereowl for real, dies morphed, state ends, respawn works"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    rows, bad, log = [], [], []
    ids = _skill_ids_by_name()[0]
    for nm, sid, st, wpn in MORPH_FORMS:
        if ids.get(nm) != sid:
            bad.append("skills.txt: %s is %s, the check expects %d" % (nm, ids.get(nm), sid))
    if not switch_character("MxlDru", "druid", 5):
        shot = g.shot("morphdeath_blocked")  # what the screen shows after Save and Exit / the character list
        return add(name, "BLOCKED", "the Druid test character cannot be opened", [os.path.basename(shot)])
    P = 256

    def morph(sid, state, weapon):
        H("unequip rhand")
        H("equip %s rhand" % weapon)
        for _ in range(3):
            setstat("player", 7, 2000 * P)
            setstat("player", 6, 2000 * P)
            setstat("player", 9, 10000 * P)
            setstat("player", 8, 10000 * P)
            H("setskill %d 1" % sid)
            log.extend(H("cast %d self" % sid)[1])
            for _ in range(8):
                time.sleep(1)
                if _state_on(state):
                    return True
        return False

    def died(timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(1)
            p = hstate()["player"]
            if p and player_dead(p):
                return True
        return False

    def after_death(label, state):
        time.sleep(2)
        if _state_on(state):
            bad.append("%s: the form state %d is still on the dead character" % (label, state))
        was = revive_if_dead()
        time.sleep(3)
        p = hstate()["player"]
        alive = bool(p) and not player_dead(p)
        rows.append("%s: respawn %s, area %s, life %s, form %s" % (label, "alive" if alive else "NOT ALIVE", p.get("area") if p else None,
                                                                 p.get("life") if p else None, "on" if _state_on(state) else "off"))
        if not was:
            bad.append("%s: revive_if_dead found the character alive after the death" % label)
        if not alive:
            bad.append("%s: not alive after the respawn" % label)
        if _state_on(state):
            bad.append("%s: the form state %d is on after the respawn" % (label, state))

    try:
        revive_if_dead()
        clear_shape_states()
        for nm, sid, st, wpn in MORPH_FORMS:
            goto(2)
            close_menu()
            kill_all_near()
            god(False)
            if not morph(sid, st, wpn):
                bad.append("%s (%d): the cast did not set state %d" % (nm, sid, st))
                continue
            setstat("player", 7, 100 * P)
            setstat("player", 6, 100 * P)
            for _ in range(8):  # result 0: the engine ignored the hit (just arrived in the area); try again
                ok, line, ls = hv("hit player phys %d" % (5000 * P), "hit")
                log.extend(ls)
                m = re.search(r"result=0x(\w+)", line)
                if m and int(m.group(1), 16) != 0:
                    break
                time.sleep(1)
            if not died(8):
                bad.append("%s (%d): the morphed character survived a lethal hit (%s)" % (nm, sid, line[:100]))
                clear_shape_states()
                continue
            after_death("%s lethal hit" % nm, st)
        # a real monster as the killer, in the bear form
        nm, sid, st, wpn = MORPH_FORMS[0]
        goto(2)
        close_menu()
        kill_all_near()
        god(False)
        if morph(sid, st, wpn):
            setstat("player", 7, 100 * P)
            setstat("player", 6, 12 * P)  # Andariel's hits on a bear at this level are ~16: one hit kills, a later one does not have to land
            log.extend(H("spawn 156")[1])
            # Soak run 2026-10-25 (slot 1): Andariel's one hit did 7 of the 12 life left and no second hit landed in 40 s. The life goes
            # back to 1 point every second while she is at it (any hit kills), and a second Andariel comes after 15 s.
            killed, t_kill, respawned = False, time.time(), False
            while time.time() - t_kill < 40 and not killed:
                killed = died(1.5)
                if not killed:
                    p = hstate()["player"]
                    if p and not player_dead(p):
                        setstat("player", 6, 1 * P)
                    if not respawned and time.time() - t_kill > 15:
                        respawned = True
                        log.extend(H("spawn 156")[1])
            if killed:
                after_death("%s killed by Andariel" % nm, st)
            else:
                bad.append("%s: Andariel did not kill the morphed character in 40 s" % nm)
                clear_shape_states()
        else:
            bad.append("%s: the cast did not set state %d for the monster kill" % (nm, st))
    finally:
        kill_all_near()
        if not switch_character("MxlBarb", "barbarian", 4):
            bad.append("the Barbarian could not be opened again")
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows + bad), [], log)


# ------------------------------------------------------------------ bug #42: the Den of Evil boss (lane den-crash)

DEN_OF_EVIL = 8
# Median's superunique in Corpsefire's slot (superuniques row 40 `CorruptedNecro`): monstats corrupted_necromancer_16 (class 2833, code #I,
# HD stand-in skmage_cold1 x2.1: the "Leoric" look), A1 missile corrupted_necromancer_16_mi (bone spear, sub missile: glacial spikes),
# Skill1 SkeletonRaise; its minion enslaved_demon (2834, bighead) brings skeleton_warrior_5 (2832).
DEN_BOSS = 2833
DEN_BOSS_PARTY = (2834, 2832)
DEN_BOSS_RAISE = (158, 14)
DEN_HIT_SPAWNS = (2835, 2818)  # the bone spear's server hit 6 spawns sHitPar1: 2835 corrupted_necromancer_17 (the glacial spike trap)
DEN_WRONG_SPAWN = 2818  # ... and before the txt_migrate fix it was Median's row number 2818 = D2R's flying_polar_buffalo_error_110  # its Skill1 SkeletonRaise, Sk1mode seq_skeletonraise (the SQ sequence mode)


def graphics_mode():
    """'legacy' when the capture is pillarboxed (legacy graphics draw 4:3 with black side bars), else 'hd'. Only reliable in a lit
    area (the town): in a dark cave HD's own edges are black too."""
    import numpy as np
    a = grab()
    h, w, _ = a.shape
    bars = np.concatenate([a[:, : w // 10], a[:, w - w // 10:]], axis=1)
    return "legacy" if float(bars.mean()) < 6.0 else "hd"


def set_graphics(mode, tries=3):
    """G toggles legacy / HD graphics (a posted key, background mode). Call it in the town (see graphics_mode)."""
    for _ in range(tries):
        if graphics_mode() == mode:
            return True
        g.press_bg("g", hold=0.1)
        time.sleep(4.0)
    return graphics_mode() == mode


def game_alive():
    return bool(g.game_pids()) and hstate()["ok"]


def _den_find_boss(seconds):
    """Crawl through the Den of Evil until its own superunique is within `h state`'s reach: run to the nearest monster, kill it, repeat
    (the monsters of the next rooms come into reach as the player goes); when none is in reach, run a stretch in one of eight directions."""
    t0 = time.time()
    st = hstate()
    dirs = [(40, 0), (0, 40), (-40, 0), (0, -40), (30, 30), (-30, -30), (30, -30), (-30, 30)]
    k = 0
    while time.time() - t0 < seconds and st["ok"]:
        boss = [m for m in st["mons"] if m.get("class") == DEN_BOSS]
        if boss:
            return boss[0], st
        live = [m for m in st["mons"] if not m.get("npc") and m.get("mode") not in (0, 12)]
        if live:
            far = max(live, key=lambda m: m.get("dist", 0))  # the farthest one in reach pulls the player on into new rooms
            H("moveto %d" % far["id"])
            time.sleep(3.0)
            for m in live:
                H("kill %d" % m["id"])
        else:
            p = st["player"]
            dx, dy = dirs[k % len(dirs)]
            k += 1
            H("move %d %d" % (p.get("x", 0) + dx, p.get("y", 0) + dy))
            time.sleep(3.0)
        st = hstate()
    boss = [m for m in st["mons"] if m.get("class") == DEN_BOSS]
    return (boss[0] if boss else None), st


def _spawn_near(cls, st):
    """`h spawn` at the first free spot around the player (the default spot, 6 right / 6 down, can be outside the room by a wall)."""
    p = st["player"]
    for dx, dy in ((6, 6), (-6, 6), (6, -6), (-6, -6), (4, 0), (0, 4), (-4, 0), (0, -4), (10, 0), (0, 10), (-10, 0), (0, -10)):
        ok, _l = H("spawn %d 1 %d %d" % (cls, p.get("x", 0) + dx, p.get("y", 0) + dy))
        if ok:
            return True
    return False


def _den_fight(mode, seconds, rows, bad, shots, mortal=False, coldres=None):
    """One round: the boss (the Den's own when it is in reach, else spawned with its party) attacks the player for `seconds`, then it
    is killed. The game must stay up and the boss must die. `mortal`: god mode is off for the fight, so the boss's bone spear and its
    glacial spike sub missile really hit and hurt the character (the player report of bug #42); the round ends early when the
    character dies. `coldres`: the character's cold resistance (stat 43) for the fight, e.g. 0 or -100."""
    goto(1)
    close_menu()
    if not set_graphics(mode):
        rows.append("%s: G did not switch the graphics (the town capture says %s)" % (mode, graphics_mode()))
        return
    shots.append(sh("denboss_town_%s" % mode))
    if goto(DEN_OF_EVIL)["player"].get("area") != DEN_OF_EVIL:
        bad.append("%s: the character did not reach the Den of Evil" % mode)
        return
    boss, st = _den_find_boss(int(os.environ.get("MXL_DENBOSS_SEARCH", "30")))
    how = "the Den's own superunique"
    if boss is None:
        known = {m.get("id") for m in st["mons"]}
        _spawn_near(DEN_BOSS, st)
        for c in DEN_BOSS_PARTY:
            _spawn_near(c, st)
        time.sleep(2.0)
        st = hstate()
        boss = next((m for m in st["mons"] if m.get("class") == DEN_BOSS and m.get("id") not in known), None)
        how = "spawned (class %d and its party %s)" % (DEN_BOSS, list(DEN_BOSS_PARTY))
    if boss is None:
        bad.append("%s: no boss (class %d) in reach and the spawn made none" % (mode, DEN_BOSS))
        return
    res0 = stat_of(H("stat player 43")[1])
    if coldres is not None:
        H("stat player 43 set %d" % coldres)
    if mortal:
        full = stat_of(H("stat player 7")[1])  # each mortal round starts at full life
        if full:
            H("stat player 6 set %d" % full)
        god(False)
    p0 = hstate()["player"]
    life0 = _life_of(p0)
    life_min, hits, died, seen_classes = life0, 0, None, set()
    H("moveto %d" % boss["id"])
    t0, seen_modes, raised = time.time(), set(), None
    while time.time() - t0 < seconds:
        time.sleep(2.0)
        if mortal:
            if not g.game_pids():
                bad.append("%s: the game died %.0f s into the mortal fight (%s; %d life drops seen, life %s of %s)" % (
                    mode, time.time() - t0, how, hits, life_min, life0))
                return
            st_m = hstate()
            p = st_m["player"]
            seen_classes.update(m.get("class") for m in st_m["mons"] if m.get("class") in DEN_HIT_SPAWNS)
            life = _life_of(p)
            if life is not None and life_min is not None and life < life_min:
                hits += 1
                life_min = life
            if p and player_dead(p):
                died = time.time() - t0
                break
        if raised is None and time.time() - t0 > seconds / 2:  # its Skill1 needs a corpse: kill one of the party, then make it cast
            minion = next((m for m in hstate()["mons"] if m.get("class") in DEN_BOSS_PARTY and m.get("mode") not in (0, 12)), None)
            if minion:
                H("kill %d" % minion["id"])
                time.sleep(1.0)
            ok, l_c = H("mcast %d %d unit %d" % (DEN_BOSS_RAISE[0], DEN_BOSS_RAISE[1], boss["id"]))
            raised = "SkeletonRaise cast %s" % ("answered" if ok else "refused (%s)" % " ".join(l_c)[-80:])
        if not game_alive():
            bad.append("%s: the game died %.0f s into the fight (%s)" % (mode, time.time() - t0, how))
            return
        st = hstate()
        for m in st["mons"]:
            if m.get("id") == boss["id"]:
                seen_modes.add(m.get("mode"))
    shots.append(sh("denboss_%s%s" % (mode, "_mortal" if mortal else "")))
    hurt = ""
    if mortal:
        hurt = ", mortal (cold resist %s): %d life drops, life %s -> %s of %s%s, bone spear hit spawns seen %s" % (
            coldres if coldres is not None else res0, hits, life0, life_min, life0, ", died after %.0f s" % died if died is not None else "",
            sorted(seen_classes))
        if DEN_WRONG_SPAWN in seen_classes:
            bad.append("%s: the bone spear's hit spawned monster %d (sHitPar1 still Median's row number)" % (mode, DEN_WRONG_SPAWN))
        if not hits:
            bad.append("%s: the mortal character was never hurt (the hit path did not run)" % mode)
        if died is not None:
            time.sleep(3.0)
            if not g.game_pids():
                bad.append("%s: the game died after the character's death" % mode)
                return
            revive_if_dead()
            god(True)
            if coldres is not None and res0 is not None:
                H("stat player 43 set %d" % res0)
            rows.append("%s: boss %s id %s%s; boss not killed (the character died first)" % (mode, how, boss["id"], hurt))
            return
        god(True)
    if coldres is not None and res0 is not None:
        H("stat player 43 set %d" % res0)
    H("kill %d" % boss["id"])
    time.sleep(2.0)
    if not game_alive():
        bad.append("%s: the game died at the kill" % mode)
        return
    alive = [m for m in hstate()["mons"] if m.get("id") == boss["id"] and m.get("mode") not in (0, 12)]
    if alive:
        bad.append("%s: the boss is still alive after `kill`" % mode)
    rows.append("%s: boss %s id %s, %d s next to the player%s, %s, modes seen %s, killed %s" % (
        mode, how, boss["id"], seconds, hurt, raised or "SkeletonRaise not cast", sorted(x for x in seen_modes if x is not None), "yes" if not alive else "NO"))
    clean_area()


def _life_of(p):
    try:
        return int(str((p or {}).get("life", "")).split("/")[0])
    except ValueError:
        return None


def check_denboss():
    """Bug #42: hard crash at the Den of Evil boss. The boss (class 2833) attacks a god-mode player for MXL_DENBOSS_SECS seconds (default 30)
    in HD and in legacy graphics (G), then it is killed: the game must stay up (no new crash report), the boss must die, no new assert."""
    nm = "Den of Evil boss (bug #42): it fights a mortal character in HD and legacy graphics (cold resist as is, 0, -100), no crash"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    secs = int(os.environ.get("MXL_DENBOSS_SECS", "30"))
    revive_if_dead()
    enable_debug()
    crashes0 = sorted(os.listdir(g.CRASH_DIR)) if os.path.isdir(g.CRASH_DIR) else []
    mark = log_mark()
    god(True)
    rows, bad, shots = [], [], []
    goto(1)
    start_mode = graphics_mode()
    # mortal rounds (bug #42 reopened: the player was hit by the cold missile; god mode never runs that path); MXL_DENBOSS_GOD=1 adds
    # the old god-mode rounds for a long soak
    plan = [("hd", True, None), ("legacy", True, None), ("hd", True, 0), ("legacy", True, -100)]
    if os.environ.get("MXL_DENBOSS_GOD") == "1":
        plan += [("hd", False, None), ("legacy", False, None)]
    for mode, mortal, coldres in plan:
        _den_fight(mode, secs, rows, bad, shots, mortal, coldres)
        if not g.game_pids():
            break
    if len(rows) < len(plan) and not bad:
        bad.append("not every round was fought")
    if game_alive():
        goto(1)
        set_graphics(start_mode)
        god(False)
    crashes = [c for c in (sorted(os.listdir(g.CRASH_DIR)) if os.path.isdir(g.CRASH_DIR) else []) if c not in crashes0]
    if crashes:
        bad.append("new crash files: %s" % crashes[:4])
    asserts = sorted(set(assertions_since(mark)))
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; asserts in d2rloader.log: %s" % asserts[:4] if asserts else "; no new assert") +
        (("; PROBLEMS: " + "; ".join(bad)) if bad else ""), shots, rows)


# Bug #49 (a player crashed putting on a Tiara): wear every base item (and every unique) of the chosen body locations, one at a
# time, and see that the game survives drawing it. itemtypes BodyLoc1/BodyLoc2 through the Equiv chain give an armor type's
# location; the harness `equip` names: head neck torso rhand lhand rring lring belt feet gloves.
EQUIP_LOCS = {"head": "head", "tors": "torso", "glov": "gloves", "feet": "feet", "belt": "belt", "rarm": "rhand", "larm": "lhand"}


def _equip_targets(locs):
    """(label, equip arguments, body location) for every armor.txt base and every uniqueitems.txt row on one of `locs`."""
    ih, irows = _txt_rows("itemtypes", 3)
    types = {r[ih.index("Code")]: r for r in irows if len(r) > ih.index("BodyLoc1") and r[ih.index("Code")]}

    def loc_of(t, seen=()):
        r = types.get(t)
        if r is None or t in seen:
            return None
        bl = r[ih.index("BodyLoc1")]
        if bl in EQUIP_LOCS:
            return EQUIP_LOCS[bl]
        for col in ("Equiv1", "Equiv2"):
            l = loc_of(r[ih.index(col)], seen + (t,))
            if l:
                return l
        return None
    ah, arows = _txt_rows("armor", 3)
    base = {}
    for r in arows:
        code = r[ah.index("code")] if len(r) > ah.index("type") else ""
        if code and code != "xxx":
            l = loc_of(r[ah.index("type")])
            if l in locs:
                base[code] = l
    out = [(code, code, l) for code, l in base.items()]
    uh, urows = _txt_rows("uniqueitems", 3)
    for i, r in enumerate(urows):
        if len(r) > uh.index("code") and r[uh.index("code")] in base:
            code = r[uh.index("code")]
            out.append(("unique %d (%s on %s)" % (i, _cell_key(r[0]), code), "%s q=7 uniq=%d" % (code, i), base[code]))
    return out


def _equip_class_of():
    """Base code -> the class (itemtypes `Class`: ama sor nec pal bar dru ass) that alone may wear it, through the Equiv chain."""
    ih, irows = _txt_rows("itemtypes", 3)
    types = {r[ih.index("Code")]: r for r in irows if len(r) > ih.index("Class") and r[ih.index("Code")]}

    def cls(t, seen=()):
        r = types.get(t)
        if r is None or t in seen:
            return ""
        return r[ih.index("Class")] or cls(r[ih.index("Equiv1")], seen + (t,)) or cls(r[ih.index("Equiv2")], seen + (t,))
    ah, arows = _txt_rows("armor", 3)
    return {r[ah.index("code")]: cls(r[ah.index("type")]) for r in arows if len(r) > ah.index("type")}


EQUIP_CLASSES = ["ama", "sor", "nec", "pal", "bar", "dru", "ass"]  # player class id -> itemtypes Class


EQUIP_BODY = {"head": 1, "neck": 2, "torso": 3, "rhand": 4, "lhand": 5, "rring": 6, "lring": 7, "belt": 8, "feet": 9, "gloves": 10}


def _equip_by_packets(args, loc):
    """`item <args> inv`, then the client packets a player's clicks send: 0x19 (backpack item to the cursor) and 0x1a (cursor item
    to body location). (worn, lines)."""
    ok, lines = H("item %s inv" % args)
    m = re.search(r"id=(\d+) .*?x=(\d+) y=(\d+)", " ".join(lines))
    if not ok or not m:
        return False, lines
    iid, x, y = (int(v) for v in m.groups())
    worn, more = _equip_by_packets_id(iid, x, y, loc)
    return worn, lines + more


def _equip_by_packets_id(iid, x, y, loc):
    """A backpack item at (x, y) to the cursor (0x19), then to the body location (0x1a). (worn, lines)."""
    lines = []
    H("pkt 19 " + _le(iid, x, y, 0))
    time.sleep(0.4)
    held = held_item()
    if not held or held[0] != iid:
        return False, lines + ["the item %d did not reach the cursor (cursor %s)" % (iid, held)]
    time.sleep(0.4)  # drawn on the cursor for a moment
    H("pkt 1a " + _le(iid, EQUIP_BODY[loc]))
    time.sleep(0.4)
    worn = any(it.get("id") == iid and it.get("page") == 255 for it in hstate()["items"])
    if not worn:
        release_held_item()
    return worn, lines + ([] if worn else ["0x1a did not wear the item %d" % iid])


def _equip_from_ground(args, loc, to_pack):
    """As a player finds it: `item <args> ground`, picked up with packet 0x16 to the cursor and worn with 0x1a, or with the
    to-inventory flag (a plain click): D2R puts the item on straight away when its body location is empty (item mode 1; the
    owner's Coronet of bug #55), else into the backpack, from where it is lifted (0x19) and worn (0x1a). (worn, lines)."""
    ok, lines = H("item %s ground" % args)
    m = re.search(r"id=(\d+)", " ".join(lines))
    if not ok or not m:
        return False, lines
    iid = int(m.group(1))
    code = args.split()[0]
    before = {x.get("id") for x in hstate()["items"]}
    ok, fl = H("iflags %d" % iid)
    f = next((kv(x) for x in fl if x.startswith("iflags")), {})
    # picked up only from next to the item (within 3 subtiles; the drop lands up to ~4 away), to the cursor too
    H("move %d %d" % (int(f.get("x", "0")), int(f.get("y", "0")) - 1))
    time.sleep(0.4)
    H("pkt 16 " + _le(iid, int(f.get("x", "0")), int(f.get("y", "0")), 1 if to_pack else 0))
    time.sleep(0.6)
    if to_pack:
        it = None
        for _ in range(6):  # the player walks the last steps first
            if any(x.get("id") == iid and x.get("page") == 255 for x in hstate()["items"]):
                return True, lines + ["put on by the pickup itself (empty body location)"]
            # the backpack copy can carry a new unit id: take the item of that code that was not there before
            it = next((x for x in hstate()["items"] if x.get("page") == 0 and (x.get("id") == iid or (
                x.get("code") == code and x.get("id") not in before))), None)
            if it:
                iid = it["id"]
                break
            time.sleep(0.5)
        if it is None:
            ok, fl2 = H("iflags %d" % iid)
            f2 = next((kv(x) for x in fl2 if x.startswith("iflags")), {})
            held = held_item()
            release_held_item()
            H("remove %s 1" % args.split()[0])
            return False, lines + ["the pickup with the inventory flag did not land (item %d mode %s, cursor %s)" % (iid, f2.get("mode"), held)]
        lines.append("picked up into the backpack at %s,%s" % (it.get("x"), it.get("y")))
        H("pkt 19 " + _le(iid, it.get("x", 0), it.get("y", 0), 0))
        time.sleep(0.4)
    held = held_item()
    if not held or held[0] != iid:
        return False, lines + ["the item %d did not reach the cursor (cursor %s)" % (iid, held)]
    lines.append("on the cursor")
    H("pkt 1a " + _le(iid, EQUIP_BODY[loc]))
    time.sleep(0.4)
    worn = any(x.get("id") == iid and x.get("page") == 255 for x in hstate()["items"])
    if not worn:
        release_held_item()
    return worn, lines + ([] if worn else ["0x1a did not wear the item %d" % iid])


def check_equipall():
    """Bugs #49 / #55: wear every helm / circlet base and unique (MXL_EQUIP_LOCS=all: every armor body location) in turn; the game must
    survive each. MXL_EQUIP_SKIP=<code,...> leaves codes out (to find the next crasher after one), MXL_EQUIP_ONLY=<code,...>
    takes only those, MXL_EQUIP_NOUNIQ=1 only the bases."""
    locs = set(EQUIP_LOCS.values()) if os.environ.get("MXL_EQUIP_LOCS") == "all" else \
        set((os.environ.get("MXL_EQUIP_LOCS") or "head").split(","))
    nm = "Wear every base and unique of %s (bug #49: Tiara crash), graphics %s" % ("/".join(sorted(locs)), graphics_mode())
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    skip = set(filter(None, (os.environ.get("MXL_EQUIP_SKIP") or "").split(",")))
    only = set(filter(None, (os.environ.get("MXL_EQUIP_ONLY") or "").split(",")))
    targets = [t for t in _equip_targets(locs) if t[1].split()[0] not in skip and (not only or t[1].split()[0] in only)
               and not (os.environ.get("MXL_EQUIP_NOUNIQ") and "uniq=" in t[1])]
    quals = [q for q in (os.environ.get("MXL_EQUIP_QUALS") or "").split(",") if q]  # bases also as these qualities (4 magic, 6 rare)
    targets += [("%s q=%s" % (lb, q), "%s q=%s" % (a, q), l) for q in quals for lb, a, l in targets if "uniq=" not in a]
    targets *= max(1, int(os.environ.get("MXL_EQUIP_REPEAT") or 1))  # random affixes: each repeat is a new item
    mode = os.environ.get("MXL_EQUIP_MODE") or "harness"
    packet = mode != "harness"  # as a player: backpack -> cursor (0x19) -> body (0x1a), plugin hooks on the way
    if mode == "packet":
        nm += ", by the player's packets 0x19 / 0x1a"
    elif mode == "ground":  # each item twice: ground -> cursor -> body, and ground -> backpack -> cursor -> body
        nm += ", picked up from the ground (0x16 to the cursor, then 0x1a / with the inventory flag: put on at once)"
        targets = [(lb + via, a, l) for lb, a, l in targets for via in (" (ground to cursor)", " (ground to inventory)")]
    p = hstate()["player"]
    goto(1)  # a town: no monster interrupts
    if packet:  # the body packet checks the requirements (a level 1 test character wears nothing magic): level, Str, Dex well above
        for stat, v in ((12, 150), (0, 3000), (2, 3000)):
            setstat("player", stat, v)
    H("packclear")
    for l in sorted(locs):
        H("unequip " + l)
    pids = sorted(g.game_pids())
    rows, bad, n, worn, other = [], [], 0, 0, 0
    class_of = _equip_class_of()
    mine = EQUIP_CLASSES[int(p.get("class", 0))] if str(p.get("class", "")).isdigit() and int(p["class"]) < 7 else ""
    for label, args, l in targets:
        g.log("EQUIPALL wearing %s (%s)" % (label, args))
        if mode == "ground":
            ok, lines = _equip_from_ground(args, l, label.endswith("inventory)"))
        elif packet:
            ok, lines = _equip_by_packets(args, l)
        else:
            ok, lines = H("equip %s %s" % (args, l))
        time.sleep(1.2)  # a few frames with the item drawn on the character
        if not game_alive() or sorted(g.game_pids()) != pids:
            shot = []
            try:
                shot = [sh("equipall_crash")]
            except Exception:
                pass
            return add(nm, "FAIL", "class %s: the game died wearing %s (`equip %s %s`) after %d items OK; skip it with "
                       "MXL_EQUIP_SKIP to go on" % (p.get("class"), label, args, l, worn), shot, rows + lines)
        if not ok and class_of.get(args.split()[0], "") not in ("", mine):
            other += 1  # another class's helm (pelt, Amazon / Paladin helm): refused as in the game
        elif not ok:
            bad.append("%s: equip refused (%s)" % (label, " ".join(lines)[-80:]))
        else:
            worn += 1
        n += 1
        H("unequip " + l)
        if n % 20 == 0:
            H("packclear")
            rows.append("%d worn, last %s" % (n, label))
    H("packclear")
    add(nm, "PASS" if not bad else "REVIEW", "class %s: %d of %d items worn and taken off (%d another class's, refused as "
        "expected; %d refused), the game survived each%s" % (p.get("class"), worn, len(targets), other, len(bad),
                                                             ("; " + "; ".join(bad[:12])) if bad else ""),
        [sh("equipall_end")], rows + bad)


def check_typeids():
    """Bugs #49 / #55: D2R's fixed item type ids equal ours (itemtypes at D2R's numbers; plugin item_type_ids.cpp checks). The
    `mxl` line; a Thul rune (type `rune`, D2R's id 75, until 0.69.15 our circlet) socketed into a circlet with
    the socket packet 0x28, and the socketed circlet worn with 0x19 / 0x1a."""
    nm = "Item type ids (bugs #49/#55): `mxl` line, a rune into a circlet's socket (0x28), the circlet worn"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    line = next((l for l in mxl_text().splitlines() if "item type ids" in l), "")
    rows, bad = [line[:200]], []
    control = "typeids" in (os.environ.get("MXL_CONTROL") or "")
    if not control and "item type ids ok: 25 of 25" not in line:
        bad.append("the mxl line is not 'item type ids ok: 25 of 25 ...'")
    goto(1)
    for stat, v in ((12, 150), (0, 3000), (2, 3000)):
        setstat("player", stat, v)
    H("packclear")
    H("unequip head")
    pids = sorted(g.game_pids())
    circ = None
    for _ in range(12):  # Circlet (1) rolls 1-2 sockets most of the time
        ok, l = H("item k01 inv")
        it = kv(next((x for x in l if "item id=" in x), ""))
        if it.get("sockets", "0") not in ("0", ""):
            circ = it
            break
        H("packclear")
    if circ is None:
        return add(nm, "BLOCKED", "no socketed Circlet (1) in 12 tries", [], rows)
    ok, l = H("item r10 inv")
    rune = kv(next((x for x in l if "item id=" in x), ""))
    if not rune:
        return add(nm, "BLOCKED", "no Thul rune: %s" % l[:1], [], rows)
    H("pkt 19 " + _le(int(rune["id"]), int(rune["x"]), int(rune["y"]), 0))
    time.sleep(0.5)
    rows.append("rune %s on the cursor: %s" % (rune["id"], held_item()))
    # 0x28 is 21 bytes in D2R (1.13: 9; read by 0x4f9f40): filler id (on the cursor), target id, target body location (0 =
    # none), target page, target cell x | y << 16
    H("pkt 28 " + _le(int(rune["id"]), int(circ["id"]), 0, 0, int(circ["x"]) | int(circ["y"]) << 16))
    time.sleep(1.0)
    if not game_alive() or sorted(g.game_pids()) != pids:
        return add(nm, "FAIL", "the game died socketing the rune into the circlet", [], rows)
    held = held_item()
    socketed = held is None and not any(x.get("id") == int(rune["id"]) and x.get("page") == 0 for x in hstate()["items"])
    rows.append("after 0x28: cursor %s, socketed %s" % (held, socketed))
    if not socketed:
        bad.append("the rune did not go into the circlet's socket (cursor %s)" % (held,))
        release_held_item()
    worn, l = _equip_by_packets_id(int(circ["id"]), int(circ["x"]), int(circ["y"]), "head")
    time.sleep(1.2)
    if not game_alive() or sorted(g.game_pids()) != pids:
        return add(nm, "FAIL", "the game died wearing the socketed circlet", [], rows + l)
    rows.append("socketed circlet worn: %s" % worn)
    if not worn:
        bad.append("the socketed circlet was not worn: %s" % l[-1:])
    H("unequip head")
    H("packclear")
    add(nm, "PASS" if not bad else "FAIL", "; ".join(bad) if bad else "; ".join(rows), [sh("typeids")], rows)


GOBLIN_TYPES = (2791, 2792, 2796, 2797, 2798, 2793)  # treasure_goblin, shiny_hoarder, arcane_collector, rainbow, glowing_baron, voided_horror
GOBLIN_SKILLS = (2580, 2582)  # treasure_goblin_skill (slow curse, srvdofunc 30), treasure_goblin_skill_2 (Submerge: srvdo 94, cltdo 52)
GOBLIN_NO_SKILL = {(2797, 2582)}  # the rainbow goblin has no Submerge: forcing its mode 14 only raises D2R's hAnimSequence assert


def _goblin_round(mode, secs, rows, bad, shots):
    """One graphics mode: each goblin type is spawned next to the god-mode player in the Blood Moor, they run for `secs`, then they
    die; then the plugin's own roll (MXL_GOBLINS_FORCE) gets a kill and 18 s to spawn one. The game must stay up throughout."""
    goto(1)
    close_menu()
    if not set_graphics(mode):
        rows.append("%s: G did not switch the graphics (the town capture says %s)" % (mode, graphics_mode()))
        return
    if goto(2)["player"].get("area") != 2:
        bad.append("%s: the character did not reach the Blood Moor" % mode)
        return
    clean_area()
    spawned = []
    for cls in GOBLIN_TYPES:
        st = hstate()
        known = {m.get("id") for m in st["mons"]}
        _spawn_near(cls, st)
        time.sleep(1.5)
        if not game_alive():
            bad.append("%s: the game died at the spawn of goblin %d" % (mode, cls))
            return
        new = [m for m in hstate()["mons"] if m.get("class") == cls and m.get("id") not in known]
        spawned.append((cls, len(new)))
    t0 = time.time()
    while time.time() - t0 < secs:
        time.sleep(2.0)
        if not game_alive():
            bad.append("%s: the game died %.0f s after the goblins appeared" % (mode, time.time() - t0))
            return
    shots.append(sh("goblincrash_%s" % mode))
    # what a goblin does when a player chases it: its curse (skill 2580, Skill1) and its escape (2582 = D2R's Submerge, Skill6)
    casts = []
    for m in [m for m in hstate()["mons"] if m.get("class") in GOBLIN_TYPES and m.get("mode") not in (0, 12)]:
        H("moveto %d" % m["id"])
        time.sleep(1.0)
        for skill in GOBLIN_SKILLS:
            if (m["class"], skill) in GOBLIN_NO_SKILL:
                continue
            ok, l_c = H("mcast %d 14 unit %d" % (skill, m["id"]))
            casts.append((m["class"], skill, "ok" if ok else "refused"))
            time.sleep(2.0)
            if not game_alive():
                bad.append("%s: the game died after goblin %d cast skill %d (%s)" % (mode, m["class"], skill, " ".join(l_c)[-80:]))
                return
    time.sleep(4.0)
    if not game_alive():
        bad.append("%s: the game died after the goblin casts" % mode)
        return
    shots.append(sh("goblincrash_casts_%s" % mode))
    for m in hstate()["mons"]:
        if m.get("class") in GOBLIN_TYPES and m.get("mode") not in (0, 12):
            H("kill %d" % m["id"])
    time.sleep(3.0)
    if not game_alive():
        bad.append("%s: the game died at the goblin kills" % mode)
        return
    s0, _r0 = goblins_counts(hstate())
    H("spawn 18 1")
    H("kill nearest 18")
    time.sleep(18)  # the roll runs every 375 frames
    if not game_alive():
        bad.append("%s: the game died around the plugin's own goblin roll" % mode)
        return
    st = hstate()
    s1, _r1 = goblins_counts(st)
    natural = [m["class"] for m in st["mons"] if m.get("class") in range(2791, 2813)]
    for m in st["mons"]:
        if m.get("class") in range(2791, 2813) and m.get("mode") not in (0, 12):
            H("kill %d" % m["id"])
    time.sleep(2.0)
    if not game_alive():
        bad.append("%s: the game died at the kill of the rolled goblin" % mode)
        return
    missing = [c for c, n in spawned if n == 0]
    if missing:
        bad.append("%s: `h spawn` made no monster for %s" % (mode, missing))
    rows.append("%s: spawned %s, %d s alive, casts %s, killed; plugin roll spawned %s -> %s (near: %s)" % (mode, spawned, secs, casts, s0, s1, natural))
    clean_area()


TRISTRAM = 38
GRISWOLD = 365  # Median's Griswold: Skill1-3 griswold_skill; its missile chain (3804 -> 3805 -> 3806 -> 3807, server hit 6) spawns
GRISWOLD_TRAP = 2879  # griswold_2, a Trap-Poison blade trap that fires once (aip2 1) and dies


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(n, ctypes.c_size_t) for n in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


def game_private_mb():
    """Private bytes of the game process in MB (None when it cannot be read)."""
    pids = g.game_pids()
    if not pids:
        return None
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pids[0])  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        c = _PMC()
        c.cb = ctypes.sizeof(c)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return None
        return c.PrivateUsage // (1 << 20)
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def check_griswold():
    """Bug #60: crash at Griswold (D2R.exe+0xF3D028, a model instance built from the full 12 MB Renderer Pool). Griswold attacks a
    god-mode player in Tristram for MXL_GRISWOLD_SECS seconds (default 180); every 5 s the blade traps (class 2879) in reach, the live
    missiles and the game's private bytes are read. PASS: the game stays up, no new crash file, the traps do not pile up."""
    nm = "Griswold (bug #60) fights a god-mode character in Tristram; blade traps, missiles and memory stay bounded, no crash"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    secs = int(os.environ.get("MXL_GRISWOLD_SECS", "180"))
    revive_if_dead()
    enable_debug()
    crashes0 = sorted(os.listdir(g.CRASH_DIR)) if os.path.isdir(g.CRASH_DIR) else []
    mark = log_mark()
    god(True)
    bad, rows, shots = [], [], []
    st = goto(TRISTRAM)
    if st["player"].get("area") != TRISTRAM:
        god(False)
        return add(nm, "BLOCKED", "the character did not reach Tristram (area %s)" % st["player"].get("area"))
    boss = next((m for m in st["mons"] if m.get("class") == GRISWOLD), None)
    how = "Tristram's own"
    if boss is None:
        _spawn_near(GRISWOLD, st)
        time.sleep(2.0)
        boss = next((m for m in hstate()["mons"] if m.get("class") == GRISWOLD), None)
        how = "spawned"
    if boss is None:
        god(False)
        return add(nm, "BLOCKED", "no Griswold (class %d) in reach and the spawn made none" % GRISWOLD)
    H("missiles reset")
    H("moveto %d" % boss["id"])
    t0, samples, traps_max, mis_max = time.time(), [], 0, 0
    mem0 = game_private_mb()
    while time.time() - t0 < secs:
        time.sleep(5.0)
        if not game_alive():
            bad.append("the game died %.0f s into the fight" % (time.time() - t0))
            break
        st = hstate()
        traps = sum(1 for m in st["mons"] if m.get("class") == GRISWOLD_TRAP)
        ok, ml = H("missiles")
        mm = re.search(r"live=(\d+)", " ".join(ml))
        live = int(mm.group(1)) if mm else -1
        mem = game_private_mb()
        traps_max, mis_max = max(traps_max, traps), max(mis_max, live)
        samples.append("%ds traps=%d missiles=%d mem=%sMB" % (time.time() - t0, traps, live, mem))
        if not any(m.get("id") == boss["id"] for m in st["mons"]):
            H("moveto %d" % boss["id"])
        if len(samples) == 3:
            shots.append(sh("griswold_fight"))
    g.log("griswold: " + "; ".join(samples))
    if game_alive():
        _ok, ml = H("missiles")
        seen = " ".join(ml)
        rows.append("Griswold %s id %s, %d s, traps in reach max %d, live missiles max %d, private bytes %s -> %s MB; %s" % (
            how, boss["id"], secs, traps_max, mis_max, mem0, game_private_mb(), seen[-200:]))
        if traps_max > 40:
            bad.append("%d blade traps in reach at once (they pile up)" % traps_max)
        H("kill %d" % boss["id"])
        time.sleep(2.0)
        clean_area()
        god(False)
    crashes = [c for c in (sorted(os.listdir(g.CRASH_DIR)) if os.path.isdir(g.CRASH_DIR) else []) if c not in crashes0]
    if crashes:
        bad.append("new crash files: %s" % crashes[:4])
    asserts = sorted(set(assertions_since(mark)))
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows + samples[-3:]) + (
        "; asserts in d2rloader.log: %s" % asserts[:4] if asserts else "; no new assert") + (
        ("; PROBLEMS: " + "; ".join(bad)) if bad else ""), shots, samples)


def check_goblincrash():
    """Bug #46: hard crash when a treasure goblin appears. Six goblin types are spawned in the Blood Moor in HD and in legacy graphics,
    run for MXL_GOBLIN_SECS seconds (default 20), die; then the plugin's roll spawns one (start the game with MXL_GOBLINS_FORCE=1 for
    that part). PASS: the game stays up, no new crash report, no new assert. Run it on a release install as well (no -txt)."""
    nm = "Treasure goblins appear, run and die in HD and legacy graphics without a crash (bug #46)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    secs = int(os.environ.get("MXL_GOBLIN_SECS", "20"))
    revive_if_dead()
    enable_debug()
    crashes0 = sorted(os.listdir(g.CRASH_DIR)) if os.path.isdir(g.CRASH_DIR) else []
    mark = log_mark()
    god(True)
    rows, bad, shots = [], [], []
    goto(1)
    start_mode = graphics_mode()
    for mode in ("hd", "legacy"):
        _goblin_round(mode, secs, rows, bad, shots)
        if not game_alive():
            break
    if len(rows) < 2 and not bad:
        bad.append("not both graphics modes were run")
    if game_alive():
        goto(1)
        set_graphics(start_mode)
        god(False)
        plugin = hstate()["plugin"]
        norow = re.search(r"(\d+) without a monstats row", plugin)
        if norow and int(norow.group(1)) > 0:
            bad.append("%s goblin rolls found no monstats row (a table did not load)" % norow.group(1))
        # Bugs #42 / #46: a monster sound id outside sounds.txt crashed the client (0xd8c70, 0xda4a0); the plugin's sound guard
        # skips it. MXL_SOUNDGUARD_TEST=1 (dev DLL) feeds the goblins' Neutral sound as -1, so the guard must have skipped some.
        # On the start that builds D2RLoader's base compiler snapshot the game has D2R's own sounds table (`NOT D2R-XL's table`):
        # every Median sound is -1 there, skips are expected and the check only asks that the game stays up (releasetables
        # FAILs that start).
        skipped = re.search(r"(\d+) bad sound ids skipped[^|]*", plugin)
        short = "NOT D2R-XL's table" in plugin
        if skipped:
            rows.append("sound guard: " + skipped.group(0).strip())
            n = int(skipped.group(1))
            if os.environ.get("MXL_SOUNDGUARD_TEST") == "1":
                if n == 0:
                    bad.append("MXL_SOUNDGUARD_TEST=1 but the sound guard skipped nothing")
            elif n > 0 and short:
                rows.append("%d sound ids skipped: the loaded sounds table is not D2R-XL's (snapshot start), the game stayed up" % n)
            elif n > 0:
                bad.append("%d monster sound ids were outside sounds.txt (a sounds table did not load)" % n)
    crashes = [c for c in (sorted(os.listdir(g.CRASH_DIR)) if os.path.isdir(g.CRASH_DIR) else []) if c not in crashes0]
    if crashes:
        bad.append("new crash files: %s" % crashes[:4])
    asserts = sorted(set(assertions_since(mark)))
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows) + ("; asserts in d2rloader.log: %s" % asserts[:4] if asserts else "; no new assert") +
        (("; PROBLEMS: " + "; ".join(bad)) if bad else ""), shots, rows + asserts[:20])


def _tsv_rows(path):
    """Data rows of a .txt table (lines after the header, blank lines left out), or None when the file is missing."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="latin-1") as f:
        lines = [ln.rstrip("\r\n") for ln in f]
    return [ln for ln in lines[1:] if ln.strip()]


def _last_start(log):
    """d2rloader.log from the last `D2R command line:` on (the start of the running game)."""
    i = log.rfind("D2R command line:")
    return log[i:] if i >= 0 else log


def check_releasetables():
    """Bugs #42 / #46: the tables of the running start equal D2R-XL's. Meant for a release install (tools/release_install.py,
    no -txt), works on any install. sounds: the table the game loaded (`mxl` sound guard line; the plugin reads 0x3b20c0) has
    as many rows as the installed mod's sounds.txt (12449, the plugin's ModSoundRows), the Median-only sound
    treasuregoblin_neutral_1 is a row inside it, and d2rloader.log's sound step compiled the mod's sounds.txt with that many
    rows (not so on the start that builds D2RLoader's base compiler snapshot). objtype: D2R has no objtype.bin and D2RLoader
    compiles objtype.txt in neither mode (with or without -txt), so the installed objtype.txt files must equal the built
    data's (work/mod/data, when present)."""
    nm = "Release tables: the loaded sounds table is D2R-XL's, objtype as built (bugs #42 / #46)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    rows, bad = [], []
    excel = os.path.join(g.GAME_DIR, "mods", "D2R-XL", "D2R-XL.mpq", "data", "global", "excel")
    built = os.path.join(MOD_DATA, "global", "excel")
    sounds = _tsv_rows(os.path.join(excel, "sounds.txt"))
    if sounds is None:
        return add(nm, "FAIL", "no sounds.txt in %s" % excel)
    names = [ln.split("\t", 1)[0] for ln in sounds]
    ours = _tsv_rows(os.path.join(built, "sounds.txt"))
    if ours is not None and len(ours) != len(sounds):
        bad.append("installed sounds.txt has %d rows, the built data %d" % (len(sounds), len(ours)))
    line = _mxl_line("sound guard")
    m = re.search(r"sounds\.txt (\d+) rows \(D2R-XL (\d+)\)", line)
    if m is None:
        return add(nm, "FAIL", "no sounds.txt row count in `mxl`: %s" % line[:200])
    loaded, expected = int(m.group(1)), int(m.group(2))
    rows.append("loaded sounds table %d rows, installed sounds.txt %d, plugin ModSoundRows %d" % (loaded, len(sounds), expected))
    if loaded != len(sounds):
        bad.append("the game loaded %d sound rows, the mod has %d (D2R's own table has 11913)" % (loaded, len(sounds)))
    if expected != len(sounds):
        bad.append("plugin ModSoundRows %d differs from the mod's %d rows (update sound_guard.h)" % (expected, len(sounds)))
    probe = "treasuregoblin_neutral_1"
    idx = names.index(probe) if probe in names else -1
    rows.append("%s is row %d" % (probe, idx))
    if idx < 11913 or idx >= loaded:
        bad.append("%s (row %d) is not a Median-only row inside the loaded table" % (probe, idx))
    skipped = re.search(r"(\d+) bad sound ids skipped", line)
    if skipped and int(skipped.group(1)) > 0 and os.environ.get("MXL_SOUNDGUARD_TEST") is None:
        bad.append("the sound guard skipped %s sound ids" % skipped.group(1))
    log = _last_start(g._read_from(g.LOADER_LOG, 0))
    cmd = re.search(r"D2R command line: \S+ (.*)", log)
    rows.append("start args: %s" % (cmd.group(1).strip() if cmd else "?"))
    step = re.search(r"Loading sound data tables(.*?)Sound data tables loaded", log, re.S)
    if step is None:
        bad.append("no sound step in d2rloader.log")
    else:
        mod = re.findall(r"compiled mod\s+global/excel/sounds\.txt.*?table: (\d+) rows", step.group(1), re.S)
        snap = "Preparing base compiler snapshot" in step.group(1)
        rows.append("sound step: the mod's sounds.txt compiled %s%s" % (("with %s rows" % "/".join(mod)) if mod else "never",
                                                                       "; base snapshot built in this start" if snap else ""))
        if not mod or any(int(r) != len(sounds) for r in mod):
            bad.append("d2rloader.log: the sound step did not compile the mod's sounds.txt with %d rows%s" %
                       (len(sounds), " (D2RLoader built its base snapshot in this start; the next start loads it)" if snap else ""))
    for rel in ("objtype.txt", "base/objtype.txt"):
        inst = os.path.join(excel, *rel.split("/"))
        if not os.path.isfile(inst):
            bad.append("no %s in the installed mod" % rel)
            continue
        ref = os.path.join(built, *rel.split("/"))
        if os.path.isfile(ref):
            with open(inst, "rb") as a, open(ref, "rb") as b:
                same = a.read() == b.read()
            rows.append("%s %s the built data" % (rel, "equals" if same else "DIFFERS from"))
            if not same:
                bad.append("installed %s differs from the built data" % rel)
        else:
            rows.append("%s %d rows (no built data here to compare)" % (rel, len(_tsv_rows(inst))))
    compiled = re.findall(r"compiled (?:mod|game)\s+global/excel/(?:base/)?objtype\.txt", log)
    rows.append("objtype compiled in this start: %d times" % len(compiled))
    add(nm, "PASS" if not bad else "FAIL", "; ".join(rows) + (("; PROBLEMS: " + "; ".join(bad)) if bad else ""), [], rows)


SKILL_BTN_RIGHT = {"hd": (0.0, 0.0), "legacy": (0.0, 0.0)}  # right skill button (client fractions), measured below


def check_skillicons():
    """Bug #52: the skill bar (Attack on the left button), the right skill popup and the skill tree in HD and legacy graphics,
    for a look against Median's icons (tools/skill_icon_check.py compares the files; this shows them drawn)."""
    nm = "Skill icons drawn in HD and legacy: skill bar (Attack), right skill popup, skill tree (#52)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    revive_if_dead()
    goto(1)
    close_menu()
    mark = log_mark()
    start_mode = graphics_mode()
    shots, rows = [], []
    for mode in ("hd", "legacy"):
        if not set_graphics(mode):
            rows.append("%s: graphics mode not reached" % mode)
            continue
        close_menu()
        time.sleep(1.0)
        shots.append(sh("skillbar_%s" % mode))
        x, y = SKILL_BTN_RIGHT[mode]
        if x:
            g.click(x, y)
            time.sleep(1.2)
            shots.append(sh("skillpopup_%s" % mode))
            g.click(x, y)
            time.sleep(0.8)
        g.key("t")
        time.sleep(1.5)
        shots.append(sh("skilltree_%s" % mode))
        g.key("t")
        time.sleep(0.8)
        rows.append("%s: shots taken" % mode)
    set_graphics(start_mode)
    asserts = sorted(set(assertions_since(mark)))
    add(nm, "REVIEW", "; ".join(rows) + ("; asserts: %s" % asserts[:4] if asserts else "; no new assert"), shots, rows)


def check_otherplugins():
    """`mxl` names the other D2RLoader plugins of the process (bug #44; a test slot has none)."""
    nm = "`mxl` names the other loaded D2RLoader plugins"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    line = _mxl_line("other plugins")
    add(nm, "PASS" if line.startswith("other plugins:") else "FAIL", line or "no `other plugins` line in `mxl`")


def check_envguard():
    """`mxl` names the active mod and the plugin's own file, and the environment check passes on a test slot: the DLL is
    under <D2R>\\mods\\D2R-XL\\, the mod is D2R-XL, no second mxl-core (plugin/src/env_guard_logic.h, docs/bugs.md #53)."""
    nm = "`mxl` shows mod and plugin file, environment ok (bug #53)"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    first = _mxl_line("| file ")
    env = _mxl_line("environment ")
    m = re.search(r"\| mod (\S+) \| file (.+)$", first)
    good = (m is not None and m.group(1).lower() == "d2r-xl" and "\\mods\\d2r-xl\\d2rloader\\plugins\\" in m.group(2).lower()
            and env.strip() == "environment ok")
    add(nm, "PASS" if good else "FAIL", "%s | %s" % (first[-160:] or "no `| file` in the first `mxl` line", env or "no `environment` line"))


def check_transguard():
    """Crash guard on D2R's unit translation event handler 0x775fc0 (plugin/src/translation_guard.cpp, docs/bugs.md #34): the hook is on,
    it has seen events of the game(s) so far, and a probe event with the payload word of the crash reports (0x8000003F0) is skipped."""
    nm = "Translation event guard (D2R.exe+0x7761DC crash): the hook is on, the probe event is skipped"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    line = _mxl_line("translation guard")
    log = [line]
    if "translation guard on" not in line:
        return add(nm, "FAIL", "the `mxl` command has no `translation guard on` line: %s" % (line or "missing"))
    ok0, l0 = H("transguard")
    seen0 = re.search(r"events=(\d+) skipped=(\d+)", " ".join(l0))
    ok, l1 = H("transguard probe")
    log += l0 + l1
    m = re.search(r"events=(\d+) skipped=(\d+) probe=(\S+)", " ".join(l1))
    good = ok0 and ok and m is not None and m.group(3) == "skipped" and seen0 is not None and int(m.group(2)) == int(seen0.group(2)) + 1
    add(nm, "PASS" if good else "FAIL", "%s; before the probe %s events, %s skipped; probe: %s" % (
        line[:110], seen0.group(1) if seen0 else "?", seen0.group(2) if seen0 else "?", m.group(0) if m else " ".join(l1)[:80]), [], log)


def check_renderpool():
    """Renderer Pool fallback (plugin/src/render_pool.cpp, docs/bugs.md #60): the `mxl` line says on with the pool's size, and a probe
    block goes through the wrapped vtable (heap block, realloc, size, free) and leaves the live counters where they were."""
    nm = "Renderer Pool fallback (D2R.exe+0xF3D028 crash): the vtable swap is on, the probe block goes through it"
    if not need_game():
        return add(nm, "BLOCKED", "not in a game")
    line = _mxl_line("render pool")
    if "render pool on" not in line:
        return add(nm, "FAIL", "the `mxl` command has no `render pool on` line: %s" % (line or "missing"))
    ok, l1 = H("renderpool probe")
    m = re.search(r"live=(\d+) .*size=(\d+) probe=(\S+)", " ".join(l1))
    good = ok and m is not None and m.group(3) == "ok" and int(m.group(2)) == 0xc00000
    add(nm, "PASS" if good else "FAIL", "%s; %s" % (line[:120], m.group(0) if m else " ".join(l1)[:120]), [], [line] + l1)


def check_morphstress():
    """Stress for the engine crash of 2026-10-24 (`D2R.exe+0x7761DC`, the client's unit translation layer, during `morphdeath`'s
    character switch; docs/bugs.md): the Druid casts each of Median's three forms many times (the form is taken off by `setstate`
    after a short run) and the characters are switched with a form on / with fresh equipment. Not in the groups; run it alone:
    `MXL_STRESS_CYCLES=20 py -3 tools/game_checks.py all morphstress`."""
    name = "Morph stress: Druid forms cast many times, character switches in between (crash hunt)"
    if not need_game():
        return add(name, "BLOCKED", "not in a game")
    cycles = int(os.environ.get("MXL_STRESS_CYCLES", "10"))
    rows, bad, log = [], [], []
    P = 256
    done = {nm: 0 for nm, *_ in MORPH_FORMS}

    def cast_form(nm, sid, state, weapon):
        H("unequip rhand")
        H("equip %s rhand" % weapon)
        for _ in range(3):
            setstat("player", 7, 2000 * P)
            setstat("player", 6, 2000 * P)
            setstat("player", 9, 10000 * P)
            setstat("player", 8, 10000 * P)
            H("setskill %d 1" % sid)
            log.extend(H("cast %d self" % sid)[1])
            for _ in range(8):
                time.sleep(0.5)
                if _state_on(state):
                    return True
        return False

    for cyc in range(cycles):
        if not switch_character("MxlDru", "druid", 5):
            bad.append("cycle %d: the Druid could not be opened" % cyc)
            break
        revive_if_dead()
        goto(2)
        close_menu()
        kill_all_near()
        god(False)
        for nm, sid, st, wpn in MORPH_FORMS if cyc % 2 == 0 else reversed(MORPH_FORMS):
            for k in range(3):
                if cast_form(nm, sid, st, wpn):
                    done[nm] += 1
                else:
                    bad.append("cycle %d: %s did not start" % (cyc, nm))
                time.sleep(1.0 + k)
                H("setstate player %d 0" % st)
                time.sleep(0.5)
        # leave morphed on odd cycles: the switch happens with a form on
        if cyc % 2 == 1:
            nm, sid, st, wpn = MORPH_FORMS[2]
            cast_form(nm, sid, st, wpn)
        rows.append("cycle %d done: %s" % (cyc, done))
        g.log("morphstress cycle %d: %s" % (cyc, done))
        if not switch_character("MxlBarb", "barbarian", 4):
            bad.append("cycle %d: the Barbarian could not be opened" % cyc)
            break
        H("equip rin 198:%d=100 lring" % ((36 << 6) | 5))
        time.sleep(0.3)
        H("unequip lring")
    add(name, "PASS" if not bad else "FAIL", "; ".join(rows[-1:] + bad), [], log)


CHECKS = [("mxl", check_mxl), ("lockclock", check_lockout_clock), ("goblins", check_goblins), ("respec", check_respec),
          ("cain", check_cain), ("cainsub", check_cain_submenu), ("heart", check_heart), ("catalyst", check_catalyst), ("tower", check_tower), ("lockout", check_lockout), ("lockquest", check_lockquest),
          # reenter before cow: the cow check leaves a Cow Level portal in town that `enter nearest` would take
          ("reenter", check_dungeon_reenter), ("cow", check_cow), ("goldcraft", check_goldcraft), ("craftflags", check_craftflags),
          ("areacycle", check_areacycle), ("mapmem", check_mapmem), ("casts", check_casts), ("cursemissile", check_cursemissile), ("asserttrace", check_asserttrace), ("cherry", check_cherry), ("warprevisit", check_warprevisit), ("replacedskills", check_replacedskills), ("vendorstock", check_vendorstock), ("vendororbs", check_vendororbs), ("summonlife", check_summonlife), ("nighthawks", check_nighthawks), ("abyssknight", check_abyssknight), ("itemevents", check_item_events), ("medianai", check_median_ai), ("medianai_ctl", check_median_ai_controlled), ("tyrael", check_tyrael),
          # the verify rows of docs/unported.md
          ("resistcap", check_resistcap), ("absorb", check_absorb), ("damagered", check_damagered), ("avoidcaps", check_avoidcaps), ("classlock", check_classlock),
          ("hiregates", check_hiregates), ("itemrolls", check_itemrolls), ("allqualsockets", check_allqualsockets), ("dye", check_dye), ("runestack", check_runestack), ("goldclient", check_goldclient),
          ("bonusdrops", check_bonusdrops), ("summoner", check_summoner), ("tooltiptext", check_tooltiptext), ("specialtext", check_specialtext), ("gameend", check_gameend), ("itemstatsave", check_itemstatsave),
          ("trophy", check_trophy), ("statcols", check_statcols),
          # the old "fix to test" rows of docs/bugs.md
          ("skilltree", check_skilltree), ("keybinds", check_keybinds), ("npcstrings", check_npcstrings), ("automap", check_automap),
          ("scrollportals", check_scrollportals), ("vendors", check_vendors), ("monhover", check_monster_hover),
          ("levelcap", check_levelcap),
          ("skillcaps", check_skillcaps),
          ("townportal", check_townportal),
          ("funcslots", check_funcslots),
          ("potions", check_potions),
          ("itemskills", check_itemskills),
          ("cowportals", check_cowportals),
          ("cubeoutputs", check_cubeoutputs),
          ("deathcrash", check_deathcrash),
          ("nocorpse", check_nocorpse), ("corpsepickup", check_corpsepickup),
          ("cooldowns", check_cooldowns),
          ("collidetypes", check_collidetypes), ("skillstarts", check_skillstarts), ("activationfreq", check_activationfreq),
          ("nslong", check_nslong), ("orbtips", check_orbtips), ("allattrtip", check_allattrtip),
          ("strings", check_strings),
          ("goblinname", check_goblinname), ("rewardsound", check_rewardsound), ("statorder", check_statorder), ("infopanel", check_infopanel),
          ("sprint", check_sprint), ("steadyaim", check_steadyaim), ("restrictitems", check_restrictitems), ("heat", check_heat),
          ("trophytimer", check_trophytimer),
          ("mapreveal", check_mapreveal), ("wparrival", check_wparrival), ("wppanel", check_wppanel), ("wpauto", check_wpauto), ("hotkeys", check_hotkeys), ("stashpages", check_stashpages), ("stashpage2", check_stashpage2),
          ("skillscaling", check_skillscaling),
          ("nodurability", check_nodurability), ("nodurabilityui", check_nodurabilityui), ("autoid", check_autoid), ("townmana", check_townmana),
          ("potionamounts", check_potionamounts), ("manarules", check_manarules),
          ("mercrevive", check_mercrevive), ("questxp", check_questxp), ("questrewards", check_questrewards),
          ("monlevel", check_monlevel), ("normaltc", check_normaltc), ("leash", check_leash),
          ("gamble", check_gamble), ("enginegaps", check_engine_gaps), ("bufficons", check_bufficons), ("uniquelimits", check_uniquelimits),
          ("assetpaths", check_assetpaths),
          ("towncast", check_towncast), ("townmonsters", check_townmonsters),
          ("npcheal", check_npcheal),
          ("tplock", check_tplock),
          ("charmlimit", check_charmlimit),
          ("arealevel", check_arealevel),
          ("bugfixes", check_bugfixes),
          # lane p4-verify-a
          ("respecbuffs", check_respecbuffs), ("signet", check_signet), ("dropilvl", check_dropilvl), ("cubehotkey", check_cubehotkey),
          ("cowtowns", check_cowtowns), ("freerespec", check_freerespec), ("grit", check_grit), ("statclick", check_statclick),
          # lane p4-engine-a: engine rules of docs/unported.md (control runs: MXL_CONTROL="<off word>")
          ("teleportgold", check_teleportgold), ("skillafford", check_skillafford), ("hcdeath", check_hcdeath),
          ("meleenotarget", check_meleenotarget), ("reqlevel", check_reqlevel), ("cubedrop", check_cubedrop),
          # lane p4-leftovers
          ("soulstealer", check_soulstealer),
          # lane p4-quests-verify
          ("towerkill", check_towerkill), ("lockwarp", check_lockwarp), ("tyraelwalk", check_tyraelwalk),
          ("worldstone", check_worldstone), ("hitfloor", check_hitfloor), ("strdex", check_strdex),
          ("wwproc", check_wwproc), ("morphdeath", check_morphdeath), ("morphstress", check_morphstress), ("transguard", check_transguard), ("denboss", check_denboss), ("griswold", check_griswold), ("renderpool", check_renderpool), ("goblincrash", check_goblincrash), ("skillicons", check_skillicons), ("releasetables", check_releasetables), ("otherplugins", check_otherplugins), ("envguard", check_envguard),
          ("ied", check_ied), ("iedtip", check_iedtip), ("bendshadows", check_bendshadows),
          # bugs #49 / #55
          ("equipall", check_equipall), ("typeids", check_typeids)]


def write_report(extra=""):
    p = os.path.join(g.current_run(), "report.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# Game checks (background input, harness commands) %s\n\n" % os.path.basename(g.current_run()))
        f.write("| Check | Result | Note | Evidence |\n|---|---|---|---|\n")
        for r in RESULTS:
            f.write("| %s | %s | %s | %s |\n" % (r.name, r.status, r.note.replace("|", "/"), ", ".join(r.shots)))
        f.write("\n" + extra + "\n")
        for r in RESULTS:
            if r.log:
                f.write("\n### log: %s\n\n```\n%s\n```\n" % (r.name, "\n".join(x[:230] for x in r.log)))
    g.log("report " + p)
    return p


def lock(wait_s=1800):
    """The slot's run lock (tools/game_slots.py): wait, retry every 30 s."""
    t0 = time.time()
    while True:
        ok, msg = g.game_slots.acquire(g.SLOT, g.LOCK_OWNER)
        if ok:
            return True
        if time.time() - t0 > wait_s:
            g.log("slot %d: %s; giving up" % (g.SLOT, msg))
            return False
        g.log("slot %d lock is held (%s), waiting 30 s" % (g.SLOT, msg))
        time.sleep(30)


def unlock():
    g.game_slots.release(g.SLOT, g.LOCK_OWNER)


def enter_initial_character():
    """An explicit lane character must never fall back to the selected save."""
    if not os.environ.get("MXL_CHAR"):
        return enter_game()
    card = card_of(g.CHAR_NAME)
    if card is None:
        return create_character(os.environ.get("MXL_CHAR_CLASS") or "barbarian", g.CHAR_NAME)  # a new lane character's class
    return enter_game(card)


def unknown_checks(only):
    """Names in a check list that are not in CHECKS ('-' is the internal 'run nothing' marker)."""
    known = {name for name, _ in CHECKS}
    return [n for n in only or [] if n != "-" and n not in known]


def run_all(only=None):
    global WD
    bad_names = unknown_checks(only)
    if bad_names:  # before the lock, the game and the run folder: a misspelt name used to be skipped without a word
        print("unknown check name(s): %s (not in the CHECKS list at the end of tools/game_checks.py)" % ", ".join(bad_names))
        return 2
    new_run()
    if not lock():
        print("game lock held for 30 min, giving up")
        return 2
    os.environ["MXL_GOBLINS_FORCE"] = "1"
    WD = Watchdog()
    WD.start()
    try:
        backup_saves()
        if g.game_pids() and not ATTACH["v"]:
            g.stop()
            time.sleep(2)
        # Quest state of the test character: the kill / dialog checks need quests 4 (Cain rescued, bit 1) and 6 (Andariel)
        # active when the game is created (quest 5 open for the tower check), and the plugin's catalyst flag (quest 47) clear; the earlier run's rewards
        # completed them. Closed save, checksum and sidecar fixed (docs/save-format.md).
        for name in [g.CHAR_NAME] if os.path.exists(os.path.join(SAVES, g.CHAR_NAME + ".d2s")) else []:  # the test character only, never other saves
            patch_quests(name, {(0, 1): 0, (0, 4): 2, (0, 5): 0, (0, 6): 0, (0, 41): 0, (0, 47): 0,
                                (0, 13): 0, (1, 13): 0, (0, 25): 0, (1, 25): 0})
        g.snapshot_marks()
        if not to_menu():
            add("start game", "BLOCKED", "game did not reach the main menu")
        elif not enter_initial_character():
            add("enter game", "BLOCKED", "the character did not enter the game")
        else:
            try:
                notes = clean_start_state("the first check", report_dead=True)
                if notes:
                    add("Test character start state (an earlier run saved it like this)", "REVIEW", "; ".join(notes))
            except Exception as e:
                add("Test character start state", "BLOCKED", "cannot be repaired: %r" % (e,))
                only = ["-"]  # no check runs on a character that cannot be put in a clean state
            p0 = hstate()["player"]
            gfx = os.environ.get("MXL_GRAPHICS")  # "legacy": the whole run in legacy graphics (G), as a player who plays that way
            if gfx:
                goto(1)
                add("Graphics mode for the run: %s" % gfx, "INFO" if set_graphics(gfx) else "BLOCKED",
                    "graphics_mode() reads %s" % graphics_mode(), [sh("graphics_%s" % gfx)])
            if os.environ.get("MXL_ASSERT_TRACE"):  # every engine assert of the run gets its call chain in mxl-core.log (harness `asserttrace`)
                H("asserttrace on")
            for name, fn in CHECKS:
                if only and name not in only:
                    continue
                try:
                    guard()
                    notes = clean_start_state(name)
                    if notes:
                        add("Start state before %s (left by the check before)" % name, "REVIEW", "; ".join(notes))
                    fn()
                except Exception as e:
                    add(name, "BLOCKED", "script error: %r" % (e,))
                    if WD.abort:
                        break
            try:  # the test character is saved on exit: put the numbers the checks changed back
                release_held_item()  # nothing may stay on the cursor: the save would come back holding it (slot 1, 2026-10-23)
                H("difficulty 0")
                H("gold set %d %d" % (p0.get("gold", 0), p0.get("bank", 0)))
                H("cubeclear")
            except Exception:
                pass
            try:  # the translation guard's counters for the whole game session (no probe here: every skip counted is a real one)
                ok_tg, l_tg = H("transguard")
                g.log("TRANSGUARD at the end of the run: %s" % " ".join(l_tg))
                add("Translation event guard counters at the end of the run", "INFO", " ".join(l_tg)[:200])
            except Exception as e:
                g.log("TRANSGUARD at the end of the run: not readable (%r)" % (e,))
    finally:
        WD.stop_flag = True
        try:
            g.stop()
        finally:
            unlock()
            r = g.logscan()
            write_report("## Real input watchdog\n\n" + WD.summary() + "\n\n## logscan\n\n```\n" + r["text"] + "\n```")
            print(WD.summary())
    return 0


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "all":
        sys.exit(run_all(a[1:] or None))
    print(__doc__)


if __name__ == "__main__":
    main()
