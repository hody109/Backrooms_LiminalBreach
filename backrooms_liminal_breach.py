import math
import os
import random
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import wave
from dataclasses import dataclass, field

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows fallback
    winsound = None


SCREEN_W = 960
SCREEN_H = 600
VIEW_H = 520
HUD_H = SCREEN_H - VIEW_H
FOV = math.radians(64)
RAYS = 240
COL_W = SCREEN_W // RAYS
MAX_DIST = 18.0
MOVE_SPEED = 2.25
RUN_SPEED = 3.05
ROT_SPEED = 2.35
STRAFE_SPEED = 1.85
PLAYER_RADIUS = 0.18

WALL = "#"
OBJECTS = set("FT1234KBGPNX")


def clean_map(text):
    rows = [line.rstrip() for line in text.strip("\n").splitlines()]
    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise ValueError(f"Map row has length {len(row)}, expected {width}: {row}")
    return rows


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, int(v))) for v in rgb])


def shade(color, factor):
    r, g, b = hex_to_rgb(color)
    return rgb_to_hex((r * factor, g * factor, b * factor))


def mix(a, b, amount):
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return rgb_to_hex((ar + (br - ar) * amount, ag + (bg - ag) * amount, ab + (bb - ab) * amount))


def angle_delta(a, b):
    return (a - b + math.pi) % (math.tau) - math.pi


def beep(pattern):
    if winsound is None:
        return

    def worker():
        for freq, dur in pattern:
            try:
                winsound.Beep(freq, dur)
            except RuntimeError:
                return

    threading.Thread(target=worker, daemon=True).start()


class SoundSystem:
    def __init__(self):
        self.enabled = winsound is not None
        self.ambient_paths = {}
        self.current_ambient = ""

    def make_ambient_loop(self, profile):
        path = os.path.join(tempfile.gettempdir(), f"backrooms_liminal_{profile}.wav")
        if os.path.exists(path):
            return path

        rate = 22050
        seconds = 10
        total = rate * seconds
        frames = bytearray()
        rng = random.Random(404 + sum(ord(ch) for ch in profile))
        noise = [rng.uniform(-1.0, 1.0) for _ in range(total)]

        for i in range(total):
            t = i / rate
            wobble = 0.5 + 0.5 * math.sin(math.tau * 0.125 * t)

            if profile == "pool":
                value = 0.16 * math.sin(math.tau * 42 * t)
                value += 0.06 * math.sin(math.tau * 84 * t + 1.8)
                value += noise[i] * 0.018
                for drop_at in (1.2, 2.85, 4.1, 6.35, 8.0):
                    if drop_at < t < drop_at + 0.2:
                        local = t - drop_at
                        value += 0.34 * math.sin(math.tau * (520 - local * 900) * t) * math.exp(-local * 16)
                value += 0.08 * math.sin(math.tau * 7.5 * t) * (0.3 + wobble * 0.7)
            elif profile == "storage":
                value = 0.22 * math.sin(math.tau * 34 * t)
                value += 0.15 * math.sin(math.tau * 68 * t + 0.5)
                value += 0.05 * math.sin(math.tau * 12 * t)
                value += noise[i] * 0.03
                if 3.4 < t < 3.75 or 7.2 < t < 7.55:
                    local = (t - 3.4) if t < 4 else (t - 7.2)
                    value += 0.23 * math.sin(math.tau * 95 * t) * math.exp(-local * 5.5)
            elif profile == "archive":
                value = 0.12 * math.sin(math.tau * 49 * t)
                value += 0.07 * math.sin(math.tau * 98 * t + 2.0)
                value += noise[i] * 0.055
                flutter = math.sin(math.tau * 5.5 * t + math.sin(t * 2.0)) * 0.028
                value += flutter
                if 2.0 < t < 2.25 or 5.0 < t < 5.18 or 8.4 < t < 8.55:
                    local = (t % 1.0)
                    value += 0.18 * math.sin(math.tau * 260 * t) * math.exp(-local * 10)
            else:
                value = 0.28 * math.sin(math.tau * 58 * t)
                value += 0.12 * math.sin(math.tau * 116 * t + 0.8)
                value += 0.08 * math.sin(math.tau * 174 * t + 2.2)
                if 1.9 < t < 2.25 or 5.65 < t < 6.1:
                    local = (t - 1.9) if t < 3 else (t - 5.65)
                    value += 0.22 * math.sin(math.tau * 38 * t) * math.exp(-local * 6.0)
                value = (value * (0.46 + wobble * 0.2)) + noise[i] * 0.025

            frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, value)) * 6500)))

        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(frames)
        return path

    def play_ambient(self, profile):
        if not self.enabled:
            return
        if profile == self.current_ambient:
            return
        self.current_ambient = profile
        if profile not in self.ambient_paths:
            self.ambient_paths[profile] = self.make_ambient_loop(profile)
        try:
            winsound.PlaySound(
                self.ambient_paths[profile],
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
        except RuntimeError:
            self.enabled = False

    def stop_ambient(self):
        if not self.enabled:
            return
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except RuntimeError:
            pass

    def footstep(self, surface, running=False):
        if not self.enabled:
            return
        if surface == "water":
            pattern = [(150, 32), (92, 38), (180, 24)]
        elif surface == "concrete":
            pattern = [(118, 22), (84, 18)] if running else [(92, 24), (62, 18)]
        elif surface == "tile":
            pattern = [(170, 18), (105, 22)] if running else [(140, 20), (86, 18)]
        elif surface == "archive":
            pattern = [(100, 20), (70, 16), (220, 12)]
        elif running:
            pattern = [(96, 20)]
        else:
            pattern = [(78, 24)]
        beep(pattern)

    def monster_step(self, distance, surface):
        if not self.enabled:
            return
        if distance > 8.0:
            return
        weight = max(0.25, 1.0 - distance / 8.0)
        if surface == "water":
            base = int(62 + weight * 36)
            pattern = [(base, int(58 + weight * 78)), (135, int(42 + weight * 45))]
        elif surface == "concrete":
            base = int(42 + weight * 30)
            pattern = [(base, int(48 + weight * 80)), (base // 2 + 28, int(35 + weight * 50))]
        else:
            base = int(48 + weight * 32)
            pattern = [(base, int(34 + weight * 66)), (base // 2 + 32, int(22 + weight * 42))]
        beep(pattern)

    def jumpscare(self):
        if not self.enabled:
            return
        beep([(1200, 70), (70, 90), (1500, 80), (55, 140), (1800, 90), (90, 190)])


@dataclass
class Monster:
    name: str
    x: float
    y: float
    speed: float
    color: str
    eye: str
    wake_dist: float
    roam: list
    goal: int = 0
    scare_cooldown: float = 0.0
    seen_timer: float = 0.0
    step_meter: float = 0.0
    blink: float = field(default_factory=lambda: random.random() * 10.0)


@dataclass
class LevelDef:
    name: str
    label: str
    task_hint: str
    logic: str
    grid: list
    palette: dict
    start_angle: float
    monsters: list
    sequence: list = field(default_factory=list)
    code: str = ""
    ambience: tuple = ("The fluorescent hum gets louder.", "Something moves behind the drywall.")


LEVELS = [
    LevelDef(
        name="Level 0 - Yellow Office Maze",
        label="LEVEL 0",
        task_hint="Find 3 fuses, then wake the terminal.",
        logic="fuses",
        start_angle=0.0,
        palette={
            "ceiling": "#6d6539",
            "floor": "#9b9052",
            "floor_dark": "#524d30",
            "wall": "#c3b65d",
            "wall_alt": "#8c8248",
            "fog": "#18170e",
            "accent": "#f1df6c",
            "exit": "#43d8c8",
        },
        grid=clean_map(
            """
####################
#S.........F....#..#
#.##..#.#######.#..#
#..#..#.....#...#..#
##.#.#####..#.###..#
#..#.....#..#...#..#
#..#####.#..###.#..#
#F.....#.#......#..#
######.#.########..#
#......#......#....#
#.##########..#.####
#.#........#..#....#
#.#.######.#..####.#
#...#....#.#.....F.#
###.#.##.#.#####.#.#
#...#..T.#.....#X#.#
#..................#
####################
"""
        ),
        monsters=[
            {"name": "The Listener", "x": 16.5, "y": 10.5, "speed": 1.18, "wake": 6.0, "color": "#080808", "eye": "#f4efbd"},
        ],
        ambience=("The carpet is damp but nobody has walked here.", "A wall panel breathes in and out."),
    ),
    LevelDef(
        name="Level 37 - Poolrooms",
        label="LEVEL 37",
        task_hint="Turn valves in the order 2, 4, 1, 3.",
        logic="valves",
        sequence=["2", "4", "1", "3"],
        start_angle=0.0,
        palette={
            "ceiling": "#d6eee7",
            "floor": "#4aa7a9",
            "floor_dark": "#1c585e",
            "wall": "#d8f4ed",
            "wall_alt": "#88aaa5",
            "fog": "#05282b",
            "accent": "#f2f0bd",
            "exit": "#51e5ff",
        },
        grid=clean_map(
            """
####################
#S.....#~~~~~#...2X#
#.###..#~###~#.#####
#...#~~~~#~~~....#~#
###.######~#####.#~#
#...#~~~~~~#...#...#
#.###~######.#.###.#
#...#~~~~1~~~#~~~#~#
#.#.###########~#.##
#.#.....~~#~~~~~#..#
#.#####.#~#~#####..#
#...3...#~~~~~~~#..#
###.###########.#..#
#...#~~~~~~~4~~~#..#
#.###.###########..#
#......N~~~~~~.....#
#.....~~~~~~~......#
####################
"""
        ),
        monsters=[
            {"name": "Smiler", "x": 15.5, "y": 5.5, "speed": 1.28, "wake": 5.3, "color": "#020507", "eye": "#ffffff"},
            {"name": "Wet Shape", "x": 5.5, "y": 14.5, "speed": 0.9, "wake": 4.3, "color": "#031517", "eye": "#6cf7ff"},
        ],
        ambience=("Water drips upward from the ceiling.", "A smile reflects in the pool before you do."),
    ),
    LevelDef(
        name="Level 1 - Service Storage",
        label="LEVEL 1",
        task_hint="Find the keycard, flip both breakers, start the generator.",
        logic="generator",
        start_angle=0.0,
        palette={
            "ceiling": "#2b2d2d",
            "floor": "#5f6658",
            "floor_dark": "#272d29",
            "wall": "#626b5f",
            "wall_alt": "#313737",
            "fog": "#070909",
            "accent": "#d9d06d",
            "exit": "#9cff74",
        },
        grid=clean_map(
            """
####################
#S........#........#
#.######..#..####..#
#......#.....#..#..#
#.####.#.#####..#..#
#.#..#.#.....#.....#
#.#B.#.#####.#####.#
#.#....#...#.....#.#
#.######...#####.#.#
#................#.#
#.######...#####.#.#
#.#....#...#...#.#.#
#.#.##.#####.#.#.#K#
#...##.......#...#.#
###.###########.##.#
#B........G.....#X.#
#..................#
####################
"""
        ),
        monsters=[
            {"name": "Cart Without Wheels", "x": 9.5, "y": 9.5, "speed": 1.35, "wake": 5.8, "color": "#0c0c0d", "eye": "#ff5454"},
        ],
        ambience=("A forklift alarm chirps with no forklift.", "Metal shelves make a corridor inside the corridor."),
    ),
    LevelDef(
        name="Level 3 - Red Archive",
        label="LEVEL 3",
        task_hint="Collect 4 tapes. Enter the code 4132 at the archive terminal.",
        logic="archive",
        code="4132",
        start_angle=0.0,
        palette={
            "ceiling": "#20171b",
            "floor": "#47333a",
            "floor_dark": "#171015",
            "wall": "#5e2529",
            "wall_alt": "#21161c",
            "fog": "#030203",
            "accent": "#e75252",
            "exit": "#76e379",
        },
        grid=clean_map(
            """
####################
#S...#......#....P.#
#.##.#.####.#.####.#
#....#....#.#....#.#
####.####.#.####.#.#
#P...#....#....#...#
#.####.###########.#
#......#.....P.....#
#.####.#.#########.#
#.#....#.....#.....#
#.#.########.#.#####
#.#......#...#.....#
#.######.#.#######.#
#....P...#.....T#X.#
#.#############.#..#
#..................#
#..................#
####################
"""
        ),
        monsters=[
            {"name": "Archivist", "x": 12.5, "y": 10.5, "speed": 1.42, "wake": 7.0, "color": "#050505", "eye": "#ffefef"},
        ],
        ambience=("Every shelf label has your handwriting.", "The exit sign is written on the inside of your eyelids."),
    ),
]


class LiminalBreach:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Backrooms: Liminal Breach")
        self.root.resizable(False, False)
        self.fullscreen = True
        self.configure_fullscreen()
        self.canvas = tk.Canvas(self.root, width=SCREEN_W, height=SCREEN_H, highlightthickness=0, bg="#000000")
        self.canvas.pack()
        self.root.bind("<KeyPress>", self.on_key_down)
        self.root.bind("<KeyRelease>", self.on_key_up)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.sound = SoundSystem()
        self.keys = set()
        self.mode = "title"
        self.running = True
        self.level_index = 0
        self.level = None
        self.grid = []
        self.width = 0
        self.height = 0
        self.player_x = 1.5
        self.player_y = 1.5
        self.angle = 0.0
        self.prev_x = self.player_x
        self.prev_y = self.player_y
        self.taken = set()
        self.valves = []
        self.breakers = set()
        self.has_keycard = False
        self.fuses = 0
        self.tapes = 0
        self.exit_open = False
        self.mystery_door = None
        self.monsters = []
        self.object_positions = []
        self.message = "Press Enter to start."
        self.message_t = 4.0
        self.jumpscare_t = 0.0
        self.jumpscare_text = ""
        self.damage_flash = 0.0
        self.sanity = 100.0
        self.flicker = 1.0
        self.flicker_t = 0.0
        self.shake = 0.0
        self.code_buffer = ""
        self.run_time = 0.0
        self.level_time = 0.0
        self.last_frame = time.perf_counter()
        self.zbuffer = [MAX_DIST] * RAYS
        self.last_ambience = 0.0
        self.step_meter = 0.0
        self.step_side = 0
        self.load_level(0, title=True)
        self.sound.play_ambient(self.ambient_profile())

    def configure_fullscreen(self):
        global SCREEN_W, SCREEN_H, VIEW_H, HUD_H, RAYS, COL_W
        SCREEN_W = max(960, self.root.winfo_screenwidth())
        SCREEN_H = max(600, self.root.winfo_screenheight())
        HUD_H = max(82, min(120, int(SCREEN_H * 0.11)))
        VIEW_H = SCREEN_H - HUD_H
        RAYS = max(220, min(320, SCREEN_W // 5))
        COL_W = max(2, math.ceil(SCREEN_W / RAYS))
        self.root.attributes("-fullscreen", True)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def close(self):
        self.running = False
        self.sound.stop_ambient()
        self.root.destroy()

    def load_level(self, index, title=False):
        self.level_index = index
        self.level = LEVELS[index]
        self.grid = [list(row) for row in self.level.grid]
        self.width = len(self.grid[0])
        self.height = len(self.grid)
        self.taken = set()
        self.valves = []
        self.breakers = set()
        self.has_keycard = False
        self.fuses = 0
        self.tapes = 0
        self.exit_open = False
        self.mystery_door = None
        self.code_buffer = ""
        self.level_time = 0.0
        self.message = self.level.name
        self.message_t = 3.5
        self.angle = self.level.start_angle
        self.monsters = []
        self.object_positions = []

        for y, row in enumerate(self.grid):
            for x, ch in enumerate(row):
                if ch == "S":
                    self.player_x = x + 0.5
                    self.player_y = y + 0.5
                    self.grid[y][x] = "."
                elif ch == "X":
                    self.grid[y][x] = "."
                elif ch in OBJECTS:
                    self.object_positions.append((ch, x, y))

        for raw in self.level.monsters:
            roam = self.find_roam_points(raw["x"], raw["y"])
            self.monsters.append(
                Monster(
                    name=raw["name"],
                    x=raw["x"],
                    y=raw["y"],
                    speed=raw["speed"],
                    color=raw["color"],
                    eye=raw["eye"],
                    wake_dist=raw["wake"],
                    roam=roam,
                )
            )

        if not title:
            self.mode = "play"
            self.sound.play_ambient(self.ambient_profile())
            beep([(440, 75), (660, 90)])

    def find_roam_points(self, x, y):
        candidates = []
        cx = int(x)
        cy = int(y)
        for yy in range(max(1, cy - 6), min(self.height - 1, cy + 7)):
            for xx in range(max(1, cx - 6), min(self.width - 1, cx + 7)):
                if not self.is_wall(xx, yy) and random.random() < 0.1:
                    candidates.append((xx + 0.5, yy + 0.5))
        if not candidates:
            candidates = [(x, y)]
        random.shuffle(candidates)
        return candidates[:6]

    def is_wall(self, x, y):
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return True
        return self.grid[y][x] == WALL

    def tile_at(self, x, y):
        tx = int(x)
        ty = int(y)
        if tx < 0 or ty < 0 or tx >= self.width or ty >= self.height:
            return WALL
        return self.grid[ty][tx]

    def ambient_profile(self):
        if self.level.logic == "valves":
            return "pool"
        if self.level.logic == "generator":
            return "storage"
        if self.level.logic == "archive":
            return "archive"
        return "office"

    def surface_at(self, x, y):
        tile = self.tile_at(x, y)
        if self.level.logic == "valves":
            return "water" if tile == "~" else "tile"
        if self.level.logic == "generator":
            return "concrete"
        if self.level.logic == "archive":
            return "archive"
        return "carpet"

    def update(self, dt):
        if self.mode != "play":
            self.jumpscare_t = max(0.0, self.jumpscare_t - dt)
            self.message_t = max(0.0, self.message_t - dt)
            return

        self.run_time += dt
        self.level_time += dt
        self.message_t = max(0.0, self.message_t - dt)
        self.jumpscare_t = max(0.0, self.jumpscare_t - dt)
        self.damage_flash = max(0.0, self.damage_flash - dt)
        self.shake = max(0.0, self.shake - dt)
        self.flicker_t -= dt
        if self.flicker_t <= 0:
            self.flicker_t = random.uniform(0.05, 0.35)
            self.flicker = random.uniform(0.72, 1.05) if random.random() < 0.24 else random.uniform(0.92, 1.0)

        self.update_player(dt)
        self.update_monsters(dt)
        self.check_exit_tile()
        self.random_ambience()

    def update_player(self, dt):
        rot = 0.0
        if "Left" in self.keys or "a" in self.keys:
            rot -= 1.0
        if "Right" in self.keys or "d" in self.keys:
            rot += 1.0
        self.angle = (self.angle + rot * ROT_SPEED * dt) % math.tau

        speed = RUN_SPEED if "Shift_L" in self.keys or "Shift_R" in self.keys else MOVE_SPEED
        forward = 0.0
        strafe = 0.0
        if "Up" in self.keys or "w" in self.keys:
            forward += 1.0
        if "Down" in self.keys or "s" in self.keys:
            forward -= 1.0
        if "q" in self.keys:
            strafe -= 1.0
        if "e" in self.keys:
            strafe += 1.0

        surface = self.surface_at(self.player_x, self.player_y)
        slow = 0.62 if surface == "water" else 1.0
        dx = math.cos(self.angle) * forward * speed + math.cos(self.angle + math.pi / 2) * strafe * STRAFE_SPEED
        dy = math.sin(self.angle) * forward * speed + math.sin(self.angle + math.pi / 2) * strafe * STRAFE_SPEED
        self.try_move(dx * dt * slow, dy * dt * slow)
        moved = math.hypot(self.player_x - self.prev_x, self.player_y - self.prev_y)
        if moved > 0.001:
            self.step_meter += moved
            running = "Shift_L" in self.keys or "Shift_R" in self.keys
            step_len = 0.48 if running else 0.64
            if self.step_meter >= step_len:
                self.step_meter = 0.0
                self.step_side = 1 - self.step_side
                self.sound.footstep(surface, running=running)

    def try_move(self, dx, dy):
        self.prev_x = self.player_x
        self.prev_y = self.player_y
        nx = self.player_x + dx
        ny = self.player_y + dy
        if not self.collides(nx, self.player_y):
            self.player_x = nx
        if not self.collides(self.player_x, ny):
            self.player_y = ny

    def collides(self, x, y):
        checks = [
            (x - PLAYER_RADIUS, y - PLAYER_RADIUS),
            (x + PLAYER_RADIUS, y - PLAYER_RADIUS),
            (x - PLAYER_RADIUS, y + PLAYER_RADIUS),
            (x + PLAYER_RADIUS, y + PLAYER_RADIUS),
        ]
        return any(self.is_wall(int(cx), int(cy)) for cx, cy in checks)

    def update_monsters(self, dt):
        for monster in self.monsters:
            monster.scare_cooldown = max(0.0, monster.scare_cooldown - dt)
            dist = math.hypot(monster.x - self.player_x, monster.y - self.player_y)
            sees_player = dist < monster.wake_dist and self.line_of_sight(monster.x, monster.y, self.player_x, self.player_y)

            if sees_player or monster.seen_timer > 0:
                monster.seen_timer = 2.4
                target_x, target_y = self.player_x, self.player_y
                speed = monster.speed * (1.18 if dist < 3.0 else 1.0)
            else:
                monster.seen_timer = max(0.0, monster.seen_timer - dt)
                if not monster.roam:
                    continue
                target_x, target_y = monster.roam[monster.goal % len(monster.roam)]
                if math.hypot(target_x - monster.x, target_y - monster.y) < 0.25:
                    monster.goal += 1
                speed = monster.speed * 0.58

            vx = target_x - monster.x
            vy = target_y - monster.y
            length = math.hypot(vx, vy) or 1.0
            old_x, old_y = monster.x, monster.y
            self.move_monster(monster, vx / length * speed * dt, vy / length * speed * dt)
            moved = math.hypot(monster.x - old_x, monster.y - old_y)
            if moved > 0.001:
                monster.step_meter += moved
                step_len = 0.62 if sees_player else 0.95
                if monster.step_meter >= step_len:
                    monster.step_meter = 0.0
                    self.sound.monster_step(
                        math.hypot(monster.x - self.player_x, monster.y - self.player_y),
                        self.surface_at(monster.x, monster.y),
                    )

            dist = math.hypot(monster.x - self.player_x, monster.y - self.player_y)
            if dist < 0.72 and monster.scare_cooldown <= 0.0:
                monster.scare_cooldown = 4.0
                self.hurt(23.0, f"{monster.name} is too close.")
                self.trigger_jumpscare(monster.name.upper())
                monster.x -= math.cos(self.angle) * 1.2
                monster.y -= math.sin(self.angle) * 1.2

    def move_monster(self, monster, dx, dy):
        if not self.is_wall(int(monster.x + dx), int(monster.y)):
            monster.x += dx
        else:
            monster.goal += 1
        if not self.is_wall(int(monster.x), int(monster.y + dy)):
            monster.y += dy
        else:
            monster.goal += 1

    def line_of_sight(self, ax, ay, bx, by):
        dist = math.hypot(bx - ax, by - ay)
        steps = max(1, int(dist / 0.08))
        for i in range(1, steps):
            t = i / steps
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            if self.is_wall(int(x), int(y)):
                return False
        return True

    def random_ambience(self):
        if self.level_time - self.last_ambience > random.uniform(12.0, 20.0):
            self.last_ambience = self.level_time
            self.say(random.choice(self.level.ambience), 3.4)
            if random.random() < 0.35:
                self.shake = 0.12
                beep([(120, 60), (90, 80)])

    def interact(self):
        if self.mode == "code":
            return

        obj = self.nearest_object()
        if obj is None:
            self.say("There is only wet carpet and humming light.", 2.2)
            return

        ch, tx, ty, dist = obj
        key = (tx, ty)
        logic = self.level.logic

        if ch == "D":
            if self.exit_open:
                self.next_level()
            else:
                self.say("The door has no handle yet.", 2.5)
                self.shake = 0.12
            return

        if logic == "fuses":
            if ch == "F" and key not in self.taken:
                self.taken.add(key)
                self.fuses += 1
                self.say(f"Fuse collected: {self.fuses}/3.", 2.2)
                beep([(560, 60)])
                return
            if ch == "T":
                if self.fuses >= 3:
                    self.open_mystery_door("The terminal wakes up. A door appears somewhere it was not before.")
                    beep([(300, 80), (470, 80), (700, 120)])
                else:
                    self.say("Terminal: missing fuses.", 2.2)
                return

        if logic == "valves":
            if ch in "1234":
                expected = self.level.sequence[len(self.valves)]
                if ch == expected:
                    self.valves.append(ch)
                    self.say(f"Valve {ch} locks. {len(self.valves)}/4.", 2.2)
                    beep([(340 + len(self.valves) * 70, 90)])
                    if len(self.valves) == len(self.level.sequence):
                        self.open_mystery_door("The pool drains without a drain. A pale door rises from the wrong wall.")
                        beep([(500, 80), (650, 80), (820, 110)])
                else:
                    self.valves = []
                    self.hurt(8.0, "Wrong valve order.")
                    self.trigger_jumpscare("WRONG ORDER")
                    self.say("Pressure resets. Something under the water smiles.", 3.0)
                return
            if ch == "N":
                self.say("Scratched tile note: 2 - 4 - 1 - 3.", 3.0)
                return

        if logic == "generator":
            if ch == "K" and key not in self.taken:
                self.taken.add(key)
                self.has_keycard = True
                self.say("Keycard found. It is warm.", 2.4)
                beep([(620, 70)])
                return
            if ch == "B":
                if key in self.breakers:
                    self.say("This breaker is already up.", 1.8)
                else:
                    self.breakers.add(key)
                    self.say(f"Breaker flipped: {len(self.breakers)}/2.", 2.2)
                    beep([(240, 80), (330, 80)])
                return
            if ch == "G":
                if len(self.breakers) < 2:
                    self.say("The generator coughs. Two breakers are still needed.", 2.6)
                elif not self.has_keycard:
                    self.say("The generator asks for a keycard.", 2.4)
                else:
                    self.open_mystery_door("Power returns to lights that were never connected. A service door appears.")
                    beep([(220, 80), (360, 90), (520, 140)])
                return

        if logic == "archive":
            if ch == "P" and key not in self.taken:
                self.taken.add(key)
                self.tapes += 1
                hints = ["4", "1", "3", "2"]
                self.say(f"Tape {self.tapes}/4. The digit is {hints[self.tapes - 1]}.", 2.8)
                beep([(420 + self.tapes * 45, 70)])
                return
            if ch == "T":
                if self.tapes < 4:
                    self.say("Archive terminal: four tapes required.", 2.5)
                else:
                    self.mode = "code"
                    self.code_buffer = ""
                    self.say("Enter archive code.", 2.0)
                    beep([(390, 70)])
                return

    def nearest_object(self):
        best = None
        best_dist = 1.1
        px = self.player_x
        py = self.player_y
        if self.mystery_door:
            dx, dy = self.mystery_door
            door_dist = math.hypot(dx + 0.5 - px, dy + 0.5 - py)
            if door_dist < best_dist:
                best = ("D", dx, dy, door_dist)
                best_dist = door_dist
        for ch, x, y in self.object_positions:
            if (x, y) in self.taken:
                continue
            dist = math.hypot(x + 0.5 - px, y + 0.5 - py)
            if dist < best_dist:
                best = (ch, x, y, dist)
                best_dist = dist
        return best

    def check_exit_tile(self):
        if not self.exit_open or not self.mystery_door:
            return
        door_x, door_y = self.mystery_door
        if int(self.player_x) == door_x and int(self.player_y) == door_y:
            self.next_level()

    def reachable_tiles(self):
        start = (int(self.player_x), int(self.player_y))
        reachable = {start}
        queue = [start]
        while queue:
            x, y = queue.pop(0)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in reachable or self.is_wall(nx, ny):
                    continue
                reachable.add((nx, ny))
                queue.append((nx, ny))
        return reachable

    def open_mystery_door(self, message):
        if self.exit_open and self.mystery_door:
            self.say("The mysterious door is already waiting.", 2.4)
            return
        occupied = set()
        for _, x, y in self.object_positions:
            occupied.add((x, y))
        for monster in self.monsters:
            occupied.add((int(monster.x), int(monster.y)))

        candidates = []
        for x, y in self.reachable_tiles():
            if (x, y) in occupied:
                continue
            dist = math.hypot(x + 0.5 - self.player_x, y + 0.5 - self.player_y)
            if dist < 5.0:
                continue
            wall_neighbors = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if self.is_wall(x + dx, y + dy))
            if wall_neighbors == 0:
                continue
            candidates.append((dist, x, y))

        if not candidates:
            for x, y in self.reachable_tiles():
                dist = math.hypot(x + 0.5 - self.player_x, y + 0.5 - self.player_y)
                if dist >= 2.5 and (x, y) not in occupied:
                    candidates.append((dist, x, y))

        if not candidates:
            self.mystery_door = (int(self.player_x), int(self.player_y))
        else:
            far_half = sorted(candidates, reverse=True)[: max(1, len(candidates) // 2)]
            _, x, y = random.choice(far_half)
            self.mystery_door = (x, y)
        self.exit_open = True
        self.say(message, 4.0)
        self.shake = max(self.shake, 0.25)
        self.sound.jumpscare()

    def next_level(self):
        if self.level_index >= len(LEVELS) - 1:
            self.mode = "win"
            self.say("You clipped out before the room could learn your name.", 5.0)
            beep([(740, 100), (940, 140), (1180, 190)])
            return
        self.load_level(self.level_index + 1)

    def hurt(self, amount, reason):
        self.sanity = max(0.0, self.sanity - amount)
        self.damage_flash = 0.35
        self.shake = max(self.shake, 0.35)
        self.say(reason, 2.2)
        if self.sanity <= 0.0:
            self.mode = "dead"
            self.say("You forgot which wall was the floor.", 5.0)

    def trigger_jumpscare(self, text):
        self.jumpscare_t = 0.78
        self.jumpscare_text = text
        self.shake = max(self.shake, 0.5)
        self.sound.jumpscare()

    def say(self, text, seconds=2.5):
        self.message = text
        self.message_t = seconds

    def cast_ray(self, ray_angle):
        ray_x = math.cos(ray_angle)
        ray_y = math.sin(ray_angle)
        map_x = int(self.player_x)
        map_y = int(self.player_y)
        delta_x = abs(1.0 / ray_x) if abs(ray_x) > 1e-6 else 1e6
        delta_y = abs(1.0 / ray_y) if abs(ray_y) > 1e-6 else 1e6

        if ray_x < 0:
            step_x = -1
            side_x = (self.player_x - map_x) * delta_x
        else:
            step_x = 1
            side_x = (map_x + 1.0 - self.player_x) * delta_x

        if ray_y < 0:
            step_y = -1
            side_y = (self.player_y - map_y) * delta_y
        else:
            step_y = 1
            side_y = (map_y + 1.0 - self.player_y) * delta_y

        side = "x"
        dist = 0.0
        while dist < MAX_DIST:
            if side_x < side_y:
                map_x += step_x
                dist = side_x
                side_x += delta_x
                side = "x"
            else:
                map_y += step_y
                dist = side_y
                side_y += delta_y
                side = "y"
            if self.is_wall(map_x, map_y):
                return dist, map_x, map_y, side
        return MAX_DIST, map_x, map_y, side

    def draw(self):
        self.canvas.delete("all")
        shake_x = random.uniform(-8, 8) * self.shake if self.shake > 0 else 0
        shake_y = random.uniform(-5, 5) * self.shake if self.shake > 0 else 0

        self.draw_world(shake_x, shake_y)
        self.draw_hud()

        if self.mode == "title":
            self.draw_title()
        elif self.mode == "dead":
            self.draw_dead()
        elif self.mode == "code":
            self.draw_code_panel()
        elif self.mode == "win":
            self.draw_win()

        if self.jumpscare_t > 0:
            self.draw_jumpscare()
        if self.damage_flash > 0:
            alpha = self.damage_flash / 0.35
            self.canvas.create_rectangle(0, 0, SCREEN_W, SCREEN_H, fill=mix("#000000", "#8f1010", alpha * 0.55), outline="")

    def draw_world(self, sx, sy):
        p = self.level.palette
        self.draw_background(p, sx, sy)
        self.zbuffer = []

        for ray in range(RAYS):
            ray_angle = self.angle - FOV / 2 + FOV * (ray / (RAYS - 1))
            dist, tx, ty, side = self.cast_ray(ray_angle)
            corrected = max(0.05, dist * math.cos(angle_delta(ray_angle, self.angle)))
            self.zbuffer.append(corrected)
            wall_h = min(VIEW_H * 1.75, VIEW_H / corrected * 0.86)
            top = VIEW_H / 2 - wall_h / 2 + sy
            bottom = VIEW_H / 2 + wall_h / 2 + sy
            x0 = int(ray * SCREEN_W / RAYS) + sx
            x1 = int((ray + 1) * SCREEN_W / RAYS) + sx + 1
            base = p["wall"] if (tx + ty) % 2 == 0 else p["wall_alt"]
            light = max(0.12, 1.12 - corrected / MAX_DIST) * self.flicker
            if side == "y":
                light *= 0.78
            color = shade(base, light)
            self.canvas.create_rectangle(x0, top, x1, bottom, fill=color, outline="")

        self.draw_sprites(sx, sy)
        self.draw_crosshair()
        self.draw_vignette()

    def draw_background(self, p, sx, sy):
        surface = self.surface_at(self.player_x, self.player_y)
        ceiling = p["ceiling"]
        floor = p["floor"]
        floor_dark = p["floor_dark"]
        if self.level.logic == "valves":
            if surface == "water":
                floor = "#349aa1"
                floor_dark = "#123f45"
                ceiling = "#d8f5ee"
            else:
                floor = "#d8eee8"
                floor_dark = "#89aaa5"
                ceiling = "#eefbf7"
        elif self.level.logic == "generator":
            floor = "#515853"
            floor_dark = "#202424"
            ceiling = "#242829"
        elif self.level.logic == "archive":
            floor = "#3d272f"
            floor_dark = "#120b10"
            ceiling = "#1a1117"

        self.canvas.create_rectangle(0, 0, SCREEN_W, VIEW_H / 2 + sy, fill=ceiling, outline="")
        self.canvas.create_rectangle(0, VIEW_H / 2 + sy, SCREEN_W, VIEW_H, fill=floor, outline="")
        for i in range(16):
            y = int(i * (VIEW_H / 2) / 16)
            factor = 0.75 + i * 0.018
            self.canvas.create_rectangle(0, y + sy, SCREEN_W, y + 18 + sy, fill=shade(ceiling, factor * self.flicker), outline="")
        for i in range(18):
            y = int(VIEW_H / 2 + i * (VIEW_H / 2) / 18)
            factor = max(0.25, 0.95 - i * 0.034)
            self.canvas.create_rectangle(0, y + sy, SCREEN_W, y + 20 + sy, fill=shade(floor, factor), outline="")
        for i in range(20):
            y = VIEW_H / 2 + i * 18 + sy
            self.canvas.create_line(0, y, SCREEN_W, y, fill=shade(floor_dark, 0.65), width=1)
        if self.level.logic == "valves":
            if surface == "water":
                for i in range(8):
                    y = VIEW_H / 2 + 18 + i * 24 + sy
                    wave = math.sin(time.perf_counter() * 2.3 + i) * 18
                    self.canvas.create_line(0, y, SCREEN_W / 2 + wave, y + 5, SCREEN_W, y - 2, fill="#9de9ef", width=1)
            else:
                for i in range(7):
                    y = VIEW_H / 2 + i * 36 + sy
                    self.canvas.create_line(0, y, SCREEN_W, y, fill="#a9c8c2")
        elif self.level.logic == "generator":
            self.canvas.create_rectangle(0, VIEW_H / 2 + 10 + sy, SCREEN_W, VIEW_H / 2 + 18 + sy, fill="#3d4232", outline="")
            self.canvas.create_rectangle(0, VIEW_H / 2 + 52 + sy, SCREEN_W, VIEW_H / 2 + 57 + sy, fill="#1a1f1f", outline="")
        elif self.level.logic == "archive":
            for i in range(8):
                x = (i * 137 + int(time.perf_counter() * 8)) % SCREEN_W
                self.canvas.create_rectangle(x, VIEW_H / 2 + 28 + (i % 4) * 34 + sy, x + 42, VIEW_H / 2 + 34 + (i % 4) * 34 + sy, fill="#8c6b5d", outline="")
        else:
            self.canvas.create_rectangle(0, VIEW_H / 2 + 24 + sy, SCREEN_W, VIEW_H / 2 + 28 + sy, fill="#6f6734", outline="")

    def sprite_candidates(self):
        sprites = []
        for ch, x, y in self.object_positions:
            if (x, y) in self.taken:
                continue
            dist = math.hypot(x + 0.5 - self.player_x, y + 0.5 - self.player_y)
            sprites.append((dist, ch, x + 0.5, y + 0.5, None))
        if self.exit_open and self.mystery_door:
            x, y = self.mystery_door
            dist = math.hypot(x + 0.5 - self.player_x, y + 0.5 - self.player_y)
            sprites.append((dist, "mystery_door", x + 0.5, y + 0.5, None))
        for monster in self.monsters:
            dist = math.hypot(monster.x - self.player_x, monster.y - self.player_y)
            sprites.append((dist, "monster", monster.x, monster.y, monster))
        sprites.sort(reverse=True, key=lambda item: item[0])
        return sprites

    def draw_sprites(self, sx, sy):
        for dist, kind, x, y, monster in self.sprite_candidates():
            dx = x - self.player_x
            dy = y - self.player_y
            theta = math.atan2(dy, dx)
            rel = angle_delta(theta, self.angle)
            if abs(rel) > FOV / 2 + 0.22 or dist < 0.18:
                continue
            corrected = max(0.12, dist * math.cos(rel))
            screen_x = SCREEN_W / 2 + (rel / (FOV / 2)) * (SCREEN_W / 2)
            col = int(screen_x * RAYS / SCREEN_W)
            if col < 0 or col >= len(self.zbuffer) or corrected > self.zbuffer[col] + 0.45:
                continue
            size = min(290, max(18, VIEW_H / corrected * 0.42))
            base_y = VIEW_H / 2 + size * 0.55 + sy
            if kind == "monster":
                self.draw_monster_sprite(screen_x + sx, base_y, size, monster, corrected)
            else:
                self.draw_object_sprite(screen_x + sx, base_y, size, kind, corrected)

    def draw_object_sprite(self, x, base_y, size, kind, dist):
        p = self.level.palette
        scale = max(0.55, min(1.0, 1.35 - dist / MAX_DIST))
        color = p["accent"]
        if kind == "F":
            self.canvas.create_rectangle(x - size * 0.12, base_y - size * 0.48, x + size * 0.12, base_y, fill="#1b1c19", outline="")
            self.canvas.create_rectangle(x - size * 0.06, base_y - size * 0.6, x + size * 0.06, base_y - size * 0.4, fill="#f1df6c", outline="")
        elif kind in "1234":
            r = size * 0.2
            self.canvas.create_oval(x - r, base_y - size * 0.52, x + r, base_y - size * 0.12, fill="#16373a", outline=color, width=2)
            self.canvas.create_text(x, base_y - size * 0.32, text=kind, fill="#ffffff", font=("Courier New", max(10, int(size * 0.14)), "bold"))
        elif kind == "K":
            self.canvas.create_rectangle(x - size * 0.18, base_y - size * 0.45, x + size * 0.18, base_y - size * 0.22, fill="#d9d06d", outline="")
            self.canvas.create_line(x - size * 0.12, base_y - size * 0.34, x + size * 0.12, base_y - size * 0.34, fill="#20251f")
        elif kind == "B":
            self.canvas.create_rectangle(x - size * 0.18, base_y - size * 0.55, x + size * 0.18, base_y - size * 0.12, fill="#161c1d", outline=color)
            self.canvas.create_line(x, base_y - size * 0.45, x + size * 0.1, base_y - size * 0.25, fill=color, width=3)
        elif kind == "G" or kind == "T" or kind == "N":
            label = "GEN" if kind == "G" else "TERM" if kind == "T" else "NOTE"
            self.canvas.create_rectangle(x - size * 0.28, base_y - size * 0.58, x + size * 0.28, base_y - size * 0.16, fill="#101516", outline=color)
            self.canvas.create_rectangle(x - size * 0.19, base_y - size * 0.48, x + size * 0.19, base_y - size * 0.34, fill=shade(color, 0.8 * scale), outline="")
            self.canvas.create_text(x, base_y - size * 0.24, text=label, fill="#e8e6ce", font=("Courier New", max(7, int(size * 0.09)), "bold"))
        elif kind == "P":
            self.canvas.create_rectangle(x - size * 0.17, base_y - size * 0.45, x + size * 0.17, base_y - size * 0.18, fill="#151516", outline=color)
            self.canvas.create_oval(x - size * 0.13, base_y - size * 0.41, x - size * 0.02, base_y - size * 0.3, fill="#e75252", outline="")
            self.canvas.create_oval(x + size * 0.02, base_y - size * 0.41, x + size * 0.13, base_y - size * 0.3, fill="#e75252", outline="")
        elif kind == "exit":
            pulse = 0.5 + math.sin(time.perf_counter() * 7.0) * 0.5
            glow = mix(p["exit"], "#ffffff", pulse * 0.25)
            self.canvas.create_rectangle(x - size * 0.28, base_y - size * 0.75, x + size * 0.28, base_y - size * 0.05, fill="#030303", outline=glow, width=3)
            self.canvas.create_text(x, base_y - size * 0.42, text="NOCLIP", fill=glow, font=("Courier New", max(7, int(size * 0.08)), "bold"))
        elif kind == "mystery_door":
            pulse = 0.5 + math.sin(time.perf_counter() * 5.4) * 0.5
            glow = mix(p["exit"], "#ffffff", pulse * 0.35)
            self.canvas.create_rectangle(x - size * 0.34, base_y - size * 0.84, x + size * 0.34, base_y - size * 0.03, fill="#020303", outline=glow, width=max(2, int(size * 0.018)))
            self.canvas.create_rectangle(x - size * 0.25, base_y - size * 0.72, x + size * 0.25, base_y - size * 0.07, fill="#080909", outline=shade(glow, 0.65), width=max(1, int(size * 0.01)))
            self.canvas.create_oval(x + size * 0.16, base_y - size * 0.39, x + size * 0.22, base_y - size * 0.33, fill=glow, outline="")
            for crack in range(4):
                offset = (crack - 1.5) * size * 0.1
                self.canvas.create_line(x + offset, base_y - size * 0.7, x + offset * 0.35, base_y - size * 0.1, fill=shade(glow, 0.42), width=1)
            self.canvas.create_text(x, base_y - size * 0.9, text="?", fill=glow, font=("Courier New", max(10, int(size * 0.13)), "bold"))
        elif kind == "closed_exit":
            self.canvas.create_rectangle(x - size * 0.2, base_y - size * 0.65, x + size * 0.2, base_y - size * 0.05, fill="#121212", outline="#3a3333")

    def draw_monster_sprite(self, x, base_y, size, monster, dist):
        eye_on = math.sin(time.perf_counter() * 9.0 + monster.blink) > -0.4
        pulse = 0.5 + math.sin(time.perf_counter() * 8.0 + monster.blink) * 0.5
        outline = mix(monster.eye, "#050505", 0.55 + pulse * 0.25)
        body_w = size * 0.42
        body_h = size * 0.9
        head_w = size * 0.48
        head_h = size * 0.28
        shoulder_y = base_y - body_h * 0.72
        hip_y = base_y - body_h * 0.28
        head_y = base_y - body_h * 0.96

        self.canvas.create_oval(x - body_w * 0.78, base_y - 8, x + body_w * 0.78, base_y + 9, fill="#020202", outline="")
        self.canvas.create_polygon(
            x - body_w * 0.42,
            shoulder_y,
            x + body_w * 0.42,
            shoulder_y,
            x + body_w * 0.28,
            hip_y,
            x + body_w * 0.18,
            base_y - body_h * 0.04,
            x - body_w * 0.18,
            base_y - body_h * 0.04,
            x - body_w * 0.28,
            hip_y,
            fill=monster.color,
            outline=outline,
            width=max(1, int(size * 0.01)),
        )
        for rib in range(5):
            yy = shoulder_y + body_h * (0.08 + rib * 0.08)
            rib_w = body_w * (0.34 - rib * 0.035)
            self.canvas.create_line(x - rib_w, yy, x + rib_w, yy + size * 0.025, fill="#242424", width=max(1, int(size * 0.012)))

        arm_sway = math.sin(time.perf_counter() * 5.0 + monster.blink) * size * 0.035
        left_hand = (x - body_w * 0.88, base_y - body_h * 0.12 + arm_sway)
        right_hand = (x + body_w * 0.88, base_y - body_h * 0.12 - arm_sway)
        self.canvas.create_line(x - body_w * 0.36, shoulder_y + size * 0.02, x - body_w * 0.62, hip_y, left_hand[0], left_hand[1], fill=monster.color, width=max(3, int(size * 0.055)))
        self.canvas.create_line(x + body_w * 0.36, shoulder_y + size * 0.02, x + body_w * 0.62, hip_y, right_hand[0], right_hand[1], fill=monster.color, width=max(3, int(size * 0.055)))
        for hx, hy, flip in ((left_hand[0], left_hand[1], -1), (right_hand[0], right_hand[1], 1)):
            for claw in range(3):
                off = (claw - 1) * size * 0.035
                self.canvas.create_line(hx, hy, hx + flip * size * 0.15, hy + off + size * 0.04, fill=outline, width=max(1, int(size * 0.01)))

        self.canvas.create_line(x - body_w * 0.14, base_y - body_h * 0.06, x - body_w * 0.33, base_y, fill=monster.color, width=max(4, int(size * 0.07)))
        self.canvas.create_line(x + body_w * 0.14, base_y - body_h * 0.06, x + body_w * 0.33, base_y, fill=monster.color, width=max(4, int(size * 0.07)))

        self.canvas.create_oval(
            x - head_w / 2,
            head_y - head_h / 2,
            x + head_w / 2,
            head_y + head_h / 2,
            fill=monster.color,
            outline=outline,
            width=max(1, int(size * 0.012)),
        )
        self.canvas.create_polygon(
            x - head_w * 0.28,
            head_y - head_h * 0.36,
            x - head_w * 0.08,
            head_y - head_h * 0.64,
            x - head_w * 0.02,
            head_y - head_h * 0.28,
            fill=monster.color,
            outline=outline,
        )
        self.canvas.create_polygon(
            x + head_w * 0.28,
            head_y - head_h * 0.36,
            x + head_w * 0.08,
            head_y - head_h * 0.64,
            x + head_w * 0.02,
            head_y - head_h * 0.28,
            fill=monster.color,
            outline=outline,
        )
        if eye_on:
            eye = monster.eye
            self.canvas.create_oval(x - head_w * 0.28, head_y - head_h * 0.12, x - head_w * 0.08, head_y + head_h * 0.08, fill=eye, outline="")
            self.canvas.create_oval(x + head_w * 0.08, head_y - head_h * 0.12, x + head_w * 0.28, head_y + head_h * 0.08, fill=eye, outline="")
            self.canvas.create_oval(x - head_w * 0.2, head_y - head_h * 0.04, x - head_w * 0.15, head_y + head_h * 0.02, fill="#000000", outline="")
            self.canvas.create_oval(x + head_w * 0.15, head_y - head_h * 0.04, x + head_w * 0.2, head_y + head_h * 0.02, fill="#000000", outline="")
        mouth_y = head_y + head_h * 0.23
        self.canvas.create_line(x - head_w * 0.25, mouth_y, x + head_w * 0.25, mouth_y + size * 0.012, fill="#e8e4c8", width=max(1, int(size * 0.012)))
        for tooth in range(5):
            tx = x - head_w * 0.2 + tooth * head_w * 0.1
            self.canvas.create_polygon(tx, mouth_y, tx + head_w * 0.035, mouth_y, tx + head_w * 0.015, mouth_y + head_h * 0.18, fill="#e8e4c8", outline="")
        if dist < 2.8:
            self.canvas.create_text(x, base_y - body_h - 18, text=monster.name.upper(), fill="#e9e6d0", font=("Courier New", 9, "bold"))

    def draw_crosshair(self):
        c = "#d8d2a8"
        self.canvas.create_line(SCREEN_W / 2 - 7, VIEW_H / 2, SCREEN_W / 2 - 2, VIEW_H / 2, fill=c)
        self.canvas.create_line(SCREEN_W / 2 + 2, VIEW_H / 2, SCREEN_W / 2 + 7, VIEW_H / 2, fill=c)
        self.canvas.create_line(SCREEN_W / 2, VIEW_H / 2 - 7, SCREEN_W / 2, VIEW_H / 2 - 2, fill=c)
        self.canvas.create_line(SCREEN_W / 2, VIEW_H / 2 + 2, SCREEN_W / 2, VIEW_H / 2 + 7, fill=c)

    def draw_vignette(self):
        for i in range(10):
            inset = i * 9
            color = shade(self.level.palette["fog"], 0.7 + i * 0.02)
            self.canvas.create_rectangle(inset, inset, SCREEN_W - inset, VIEW_H - inset, outline=color)

    def draw_minimap(self):
        box_w = 150
        box_h = 132
        x0 = SCREEN_W - box_w - 14
        y0 = VIEW_H - box_h - 14
        p = self.level.palette
        self.canvas.create_rectangle(x0, y0, x0 + box_w, y0 + box_h, fill="#050707", outline="#3f4946")
        self.canvas.create_text(x0 + 8, y0 + 10, text="MINIMAP", anchor="w", fill="#aab8af", font=("Courier New", 8, "bold"))

        cell = min((box_w - 14) / self.width, (box_h - 24) / self.height)
        ox = x0 + 7 + ((box_w - 14) - cell * self.width) / 2
        oy = y0 + 20 + ((box_h - 24) - cell * self.height) / 2

        for yy, row in enumerate(self.grid):
            for xx, ch in enumerate(row):
                tx = ox + xx * cell
                ty = oy + yy * cell
                if ch == WALL:
                    color = shade(p["wall"], 0.72)
                elif ch == "~":
                    color = "#1d6268"
                else:
                    color = shade(p["floor_dark"], 0.7)
                self.canvas.create_rectangle(tx, ty, tx + cell + 0.4, ty + cell + 0.4, fill=color, outline=color)

                if ch in OBJECTS and (xx, yy) not in self.taken:
                    if ch == "X":
                        marker = p["exit"] if self.exit_open else "#5c6260"
                    elif ch in "FTKPB1234GNT":
                        marker = p["accent"]
                    else:
                        marker = "#d7cc77"
                    inset = max(0.8, cell * 0.28)
                    self.canvas.create_rectangle(tx + inset, ty + inset, tx + cell - inset, ty + cell - inset, fill=marker, outline="")

        if self.exit_open and self.mystery_door:
            dx, dy = self.mystery_door
            tx = ox + dx * cell
            ty = oy + dy * cell
            self.canvas.create_rectangle(tx, ty, tx + cell, ty + cell, fill=p["exit"], outline="#ffffff")

        px = ox + self.player_x * cell
        py = oy + self.player_y * cell
        nose = max(5.0, cell * 1.8)
        side = max(3.0, cell * 0.9)
        ax = math.cos(self.angle)
        ay = math.sin(self.angle)
        sx = math.cos(self.angle + math.pi / 2)
        sy = math.sin(self.angle + math.pi / 2)
        points = [
            px + ax * nose,
            py + ay * nose,
            px - ax * side + sx * side,
            py - ay * side + sy * side,
            px - ax * side - sx * side,
            py - ay * side - sy * side,
        ]
        self.canvas.create_polygon(*points, fill="#f2eed0", outline="#050707")
        self.canvas.create_rectangle(x0 + 1, y0 + box_h - 13, x0 + box_w - 1, y0 + box_h - 1, fill="#070809", outline="")
        self.canvas.create_text(x0 + 8, y0 + box_h - 7, text="bright = task / exit", anchor="w", fill="#737d78", font=("Courier New", 7))

    def objective_text(self):
        logic = self.level.logic
        if logic == "fuses":
            return f"Fuses {self.fuses}/3 | terminal {'awake' if self.exit_open else 'asleep'}"
        if logic == "valves":
            return f"Valves {len(self.valves)}/4 | order: {'-'.join(self.valves) or '?'}"
        if logic == "generator":
            card = "card" if self.has_keycard else "no card"
            return f"Breakers {len(self.breakers)}/2 | {card} | generator {'on' if self.exit_open else 'off'}"
        if logic == "archive":
            return f"Tapes {self.tapes}/4 | code {'accepted' if self.exit_open else 'locked'}"
        return self.level.task_hint

    def draw_hud(self):
        self.canvas.create_rectangle(0, VIEW_H, SCREEN_W, SCREEN_H, fill="#070809", outline="")
        self.canvas.create_line(0, VIEW_H, SCREEN_W, VIEW_H, fill="#2d3332")
        self.canvas.create_text(18, VIEW_H + 18, text=self.level.name, anchor="w", fill="#f0eed8", font=("Courier New", 13, "bold"))
        self.canvas.create_text(18, VIEW_H + 42, text=self.objective_text(), anchor="w", fill="#aab8af", font=("Courier New", 12))
        self.canvas.create_text(18, VIEW_H + 64, text="W/S move | A/D turn | Q/E strafe | Space use | Shift run | R restart", anchor="w", fill="#737d78", font=("Courier New", 10))
        sx = SCREEN_W - 238
        self.canvas.create_rectangle(sx, VIEW_H + 18, sx + 207, VIEW_H + 34, fill="#151818", outline="#424b49")
        sanity_w = int(205 * (self.sanity / 100.0))
        sanity_color = "#86df70" if self.sanity > 45 else "#ded66a" if self.sanity > 20 else "#e75252"
        self.canvas.create_rectangle(sx + 1, VIEW_H + 19, sx + 1 + sanity_w, VIEW_H + 33, fill=sanity_color, outline="")
        self.canvas.create_text(sx, VIEW_H + 48, text=f"SANITY {int(self.sanity):03d}  TIME {int(self.run_time):04d}s", anchor="w", fill="#f0eed8", font=("Courier New", 11, "bold"))
        self.draw_minimap()
        if self.message_t > 0:
            self.canvas.create_rectangle(20, 18, min(920, 44 + len(self.message) * 9), 48, fill="#050606", outline="#2d3332")
            self.canvas.create_text(32, 33, text=self.message, anchor="w", fill="#f0eed8", font=("Courier New", 12, "bold"))

    def draw_title(self):
        cx = SCREEN_W / 2
        cy = VIEW_H / 2
        w = min(720, SCREEN_W - 80)
        h = 328
        self.canvas.create_rectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, fill="#070808", outline="#d7cc77", width=2)
        self.canvas.create_text(cx, cy - 102, text="BACKROOMS: LIMINAL BREACH", fill="#f2eed0", font=("Courier New", 30, "bold"))
        self.canvas.create_text(cx, cy - 54, text="Fullscreen desktop 2.5D raycaster inspired by early Doom-era corridors", fill="#d7cc77", font=("Courier New", 13, "bold"))
        self.canvas.create_text(cx, cy + 1, text="Monsters stalk through blind corners. Wrong puzzle choices bite back.", fill="#aab8af", font=("Courier New", 13))
        self.canvas.create_text(cx, cy + 58, text="Enter starts | Space interacts | R restarts | F11 toggles fullscreen", fill="#f2eed0", font=("Courier New", 15, "bold"))
        self.canvas.create_text(cx, cy + 108, text="Use headphones if you want the room to feel less empty.", fill="#737d78", font=("Courier New", 11))

    def draw_dead(self):
        cx = SCREEN_W / 2
        cy = VIEW_H / 2
        self.canvas.create_rectangle(cx - 290, cy - 115, cx + 290, cy + 115, fill="#070404", outline="#e75252", width=2)
        self.canvas.create_text(cx, cy - 50, text="THE ROOM KEPT YOU", fill="#e75252", font=("Courier New", 34, "bold"))
        self.canvas.create_text(cx, cy + 10, text=self.message, fill="#f0eed8", font=("Courier New", 14, "bold"))
        self.canvas.create_text(cx, cy + 60, text="Press Enter or R to restart the level.", fill="#aab8af", font=("Courier New", 13))

    def draw_win(self):
        cx = SCREEN_W / 2
        cy = VIEW_H / 2
        self.canvas.create_rectangle(cx - 310, cy - 128, cx + 310, cy + 128, fill="#06100f", outline="#76e379", width=2)
        self.canvas.create_text(cx, cy - 52, text="YOU NOCLIPPED OUT", fill="#76e379", font=("Courier New", 34, "bold"))
        self.canvas.create_text(cx, cy + 8, text=f"Run time: {int(self.run_time)} seconds", fill="#f0eed8", font=("Courier New", 15, "bold"))
        self.canvas.create_text(cx, cy + 58, text="Press Enter to start again from Level 0.", fill="#aab8af", font=("Courier New", 13))

    def draw_code_panel(self):
        cx = SCREEN_W / 2
        cy = VIEW_H / 2
        self.canvas.create_rectangle(cx - 230, cy - 135, cx + 230, cy + 135, fill="#050606", outline="#76e379", width=2)
        self.canvas.create_text(cx, cy - 80, text="ARCHIVE TERMINAL", fill="#76e379", font=("Courier New", 24, "bold"))
        self.canvas.create_text(cx, cy - 37, text="Enter the four digits from the tapes.", fill="#aab8af", font=("Courier New", 13))
        display = " ".join(self.code_buffer.ljust(4, "_"))
        self.canvas.create_rectangle(cx - 150, cy, cx + 150, cy + 55, fill="#101516", outline="#76e379")
        self.canvas.create_text(cx, cy + 28, text=display, fill="#f0eed8", font=("Courier New", 26, "bold"))
        self.canvas.create_text(cx, cy + 89, text="Digits 1-4 | Enter confirm | Esc close", fill="#737d78", font=("Courier New", 11))

    def draw_jumpscare(self):
        t = self.jumpscare_t / 0.78
        bg = mix("#000000", "#7b0909", t)
        self.canvas.create_rectangle(0, 0, SCREEN_W, SCREEN_H, fill=bg, outline="")
        jitter = 18 * t
        cx = SCREEN_W / 2 + random.uniform(-jitter, jitter)
        cy = SCREEN_H / 2 + random.uniform(-jitter, jitter)
        self.canvas.create_oval(cx - 260, cy - 245, cx + 260, cy + 250, fill="#050505", outline="#f0eed8", width=3)
        self.canvas.create_oval(cx - 150, cy - 90, cx - 48, cy + 20, fill="#f5f1d9", outline="")
        self.canvas.create_oval(cx + 48, cy - 90, cx + 150, cy + 20, fill="#f5f1d9", outline="")
        self.canvas.create_rectangle(cx - 132, cy - 22, cx - 64, cy + 10, fill="#020202", outline="")
        self.canvas.create_rectangle(cx + 64, cy - 22, cx + 132, cy + 10, fill="#020202", outline="")
        self.canvas.create_polygon(cx - 170, cy + 120, cx, cy + 205, cx + 170, cy + 120, cx + 95, cy + 245, cx - 95, cy + 245, fill="#d91515", outline="#f0eed8")
        for _ in range(18):
            y = random.randint(0, SCREEN_H)
            self.canvas.create_rectangle(0, y, SCREEN_W, y + random.randint(2, 8), fill=random.choice(["#f0eed8", "#e75252", "#050505"]), outline="")
        self.canvas.create_text(cx, cy - 205, text=self.jumpscare_text, fill="#f0eed8", font=("Courier New", 24, "bold"))

    def on_key_down(self, event):
        key = event.keysym
        if key == "F11":
            self.toggle_fullscreen()
            return
        if self.mode == "title":
            if key in ("Return", "space"):
                self.mode = "play"
                self.run_time = 0.0
                self.say("The lights find you first.", 3.0)
                beep([(340, 90), (520, 120)])
            return

        if self.mode == "dead":
            if key in ("Return", "r", "R"):
                self.sanity = 100.0
                self.load_level(self.level_index)
            return

        if self.mode == "win":
            if key in ("Return", "r", "R"):
                self.sanity = 100.0
                self.run_time = 0.0
                self.load_level(0)
            return

        if self.mode == "code":
            self.handle_code_key(key)
            return

        if key in ("space", "Return"):
            self.interact()
            return
        if key in ("r", "R"):
            self.sanity = 100.0
            self.load_level(self.level_index)
            return
        self.keys.add(key)

    def handle_code_key(self, key):
        if key == "Escape":
            self.mode = "play"
            self.code_buffer = ""
            return
        if key == "BackSpace":
            self.code_buffer = self.code_buffer[:-1]
            return
        if key == "Return":
            if self.code_buffer == self.level.code:
                self.mode = "play"
                self.open_mystery_door("The archive admits the room was lying. A door writes itself into the map.")
                beep([(620, 80), (850, 130)])
            else:
                self.code_buffer = ""
                self.mode = "play"
                self.hurt(12.0, "The terminal repeats your wrong code in your voice.")
                self.trigger_jumpscare("BAD CODE")
            return
        if key in ("1", "2", "3", "4") and len(self.code_buffer) < 4:
            self.code_buffer += key
            beep([(300 + int(key) * 70, 45)])

    def on_key_up(self, event):
        self.keys.discard(event.keysym)

    def run(self):
        self.loop()
        self.root.mainloop()

    def loop(self):
        if not self.running:
            return
        now = time.perf_counter()
        dt = min(0.05, now - self.last_frame)
        self.last_frame = now
        self.update(dt)
        self.draw()
        self.root.after(16, self.loop)


def self_test():
    for idx, level in enumerate(LEVELS):
        w = len(level.grid[0])
        assert all(len(row) == w for row in level.grid), level.name
        assert any("S" in row for row in level.grid), level.name
        assert any("X" in row for row in level.grid), level.name
        assert level.monsters, level.name
        start = None
        targets = []
        for y, row in enumerate(level.grid):
            for x, ch in enumerate(row):
                if ch == "S":
                    start = (x, y)
                if ch in OBJECTS:
                    targets.append((ch, x, y))
                if ch == "S" or ch in OBJECTS or ch in (WALL, ".", "~"):
                    continue
                raise AssertionError(f"Unexpected tile {ch!r} in {level.name} at {x},{y}")
        reachable = {start}
        queue = [start]
        while queue:
            x, y = queue.pop(0)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in reachable:
                    continue
                if nx < 0 or ny < 0 or ny >= len(level.grid) or nx >= len(level.grid[0]):
                    continue
                if level.grid[ny][nx] == WALL:
                    continue
                reachable.add((nx, ny))
                queue.append((nx, ny))
        for ch, x, y in targets:
            assert (x, y) in reachable, f"{level.name}: unreachable {ch} at {x},{y}"
        if level.logic == "fuses":
            assert sum(row.count("F") for row in level.grid) >= 3
            assert any("T" in row for row in level.grid)
        if level.logic == "valves":
            for ch in level.sequence:
                assert any(ch in row for row in level.grid)
        if level.logic == "generator":
            assert sum(row.count("B") for row in level.grid) >= 2
            assert any("K" in row for row in level.grid)
            assert any("G" in row for row in level.grid)
        if level.logic == "archive":
            assert sum(row.count("P") for row in level.grid) >= 4
            assert any("T" in row for row in level.grid)
            assert level.code
    print("self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        LiminalBreach().run()
