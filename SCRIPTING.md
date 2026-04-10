# Scripting Guide

This guide covers the full command syntax for discord-plays, including chords, sequences, timing control, and analog sticks. All examples assume the default `!` prefix.

---

## Syntax Overview

```
!step step step ...
```

Each **step** is separated by a space. Steps are executed left to right, one after another.

A step is one of:

| Type | Syntax | Example |
|---|---|---|
| Button press | `button` or `button:ms` | `a`, `lb:500` |
| Chord | `input+input+...` | `a+b`, `down+right` |
| Analog stick | `axis:value` | `lx:70`, `ly:-100` |
| Wait | `~ms` | `~200` |

---

## Single Button Press

The simplest command. Press a button for the default hold duration (configured in `config.toml` as `press_duration_ms`, default 100ms).

```
!a          Press A
!start      Press Start
!lb         Press Left Bumper
```

Button names are case-insensitive: `!A`, `!a`, and `!Start` all work.

---

## Custom Hold Duration

Append `:ms` to hold a button for a specific number of milliseconds.

```
!a:500      Hold A for 500ms
!rt:2000    Hold Right Trigger for 2 seconds
```

The maximum hold per button is capped by `max_hold_ms` (default 5000ms).

---

## Chords (Simultaneous Buttons)

Use `+` to press multiple buttons at the same time.

```
!a+b        Press A and B together
!lb+rb      Press both bumpers
!down+right Press down and right on the d-pad simultaneously
```

Chords can mix buttons with different hold durations. The chord finishes when the longest-held button is released.

```
!a:200+b:500    Press A and B together; A releases at 200ms, B at 500ms
```

---

## Sequences (Multi-Step Commands)

Separate steps with spaces. Each step executes after the previous one finishes.

```
!down right a       Press down, then right, then A
!a b a b            Mash A-B-A-B
!up up down down    Konami opening
```

---

## Waits (Explicit Pauses)

Insert `~ms` to pause between steps. The number is milliseconds.

```
!a ~200 b           Press A, wait 200ms, press B
!a ~1000 a          Press A, wait 1 second, press A again
```

---

## Analog Sticks

Set the position of an analog stick axis using `axis:value` where value is -100 to 100 (percentage of full deflection).

| Axis | Stick | Direction |
|---|---|---|
| `lx` | Left stick | Horizontal (-100 = full left, 100 = full right) |
| `ly` | Left stick | Vertical (-100 = full up, 100 = full down) |
| `rx` | Right stick | Horizontal |
| `ry` | Right stick | Vertical |

```
!lx:100             Full right on left stick
!ly:-100            Full up on left stick
!lx:70+ly:-70       Left stick diagonal (upper-right)
!rx:0+ry:100        Right stick full down
```

Axis values are reset to centre (0) at the end of each step. To hold a stick across multiple button presses, include it in every chord:

```
!lx:100+a lx:100+b lx:0    Hold right while pressing A then B, then centre
```

Analog stick axes combine with buttons in chords:

```
!lx:100+a           Press A while pushing the left stick right
```

Note: `!ls` and `!rs` click the stick buttons (L3/R3). They do not move the sticks.

---

## Fighting Game Examples

### Hadouken (Quarter Circle Forward + Punch)

```
!down down+right right a
```

Four steps: down, down+right diagonal, right, then punch.

### Shoryuken (Forward, Down, Down-Forward + Punch)

```
!right down down+right a
```

### Charge Move (Hold Back, then Forward + Kick)

```
!left:2000 right+b
```

Hold left (back) for 2 seconds, then forward + B.

### Dash (Double Tap Forward)

```
!right ~50 right
```

Tap right, brief pause, tap right again.

### Super (Double Quarter Circle Forward + Punch)

```
!down down+right right down down+right right a
```

### Throw (Two Buttons Simultaneously)

```
!lb+rb
```

### Quick Combo

```
!a a:200 b:300 a+b
```

Light attack, medium attack (longer hold), heavy attack, then both.

### Analog Stick Circle Motion

```
!lx:100 lx:70+ly:70 ly:100 lx:-70+ly:70 lx:-100
```

Sweep the left stick from right through down to left (half-circle).

---

## Limits and Timesharing

### Static Limits (config.toml)

These are set at startup and reject commands that exceed them:

| Setting | Default | Effect |
|---|---|---|
| `max_hold_ms` | 5000 | Max hold per button (ms) |
| `max_sequence_steps` | 20 | Max steps per command |
| `max_total_duration_ms` | 10000 | Max estimated total duration (ms) |

### Runtime Limits (Operator Commands)

Admins can set per-command limits at runtime to enforce timesharing. Unlike static limits, these **truncate** commands at the point the limit is hit rather than rejecting them.

| Command | Effect |
|---|---|
| `!maxkeys 5` | Truncate commands after 5 button presses |
| `!maxtime 2000` | Truncate commands after 2000ms estimated duration |
| `!maxkeys 0` | Disable keypress limit |
| `!maxtime 0` | Disable duration limit |

When a command is truncated, the steps up to the limit still execute. Only the excess is dropped.

**What counts as a keypress:** Each button in a chord counts. A chord like `a+b` is 2 keypresses. Waits (`~200`) and axis inputs (`lx:50`) do not count as keypresses.

**How duration is estimated:** Each chord step adds the hold time of its longest button. Each wait adds its full duration. Axis-only steps add 0.

Example with `!maxkeys 3`:

```
!a b x y z    →  Executes !a b x (3 keys), y and z are dropped
!a+b x y      →  Executes !a+b (2 keys) then x (3 keys), y is dropped
```

---

## Voting with Sequences

In vote mode, each unique command is a separate vote. The canonical (normalized) form is used for grouping, so `!A+B` and `!b+a` count as the same vote. Ties are broken by earliest submission.
