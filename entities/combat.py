"""
entities/combat.py
Wound-based combat system — Neo Scavenger / Dwarf Fortress flavour.

No HP pool. Damage accumulates as located wounds on specific body parts.
Wounds produce conditions (bleeding, pain, shock, mobility/grip loss) that
feed back into Mo's perception and eventually his action reliability.

Combat is one exchange per action: Mo attacks, the animal immediately
counter-attacks in the same resolution. Grapple persists across ticks.
Bleeding and shock update every game tick via CombatState.tick().
"""

import random
from dataclasses import dataclass, field
from enum import Enum


# ── Body parts ────────────────────────────────────────────────────────────────

class BodyPart(Enum):
    HEAD      = "head"
    TORSO     = "torso"
    RIGHT_ARM = "right arm"
    LEFT_ARM  = "left arm"
    RIGHT_LEG = "right leg"
    LEFT_LEG  = "left leg"


BODY_PART_LOOKUP: dict[str, BodyPart] = {
    "head":      BodyPart.HEAD,
    "torso":     BodyPart.TORSO,
    "chest":     BodyPart.TORSO,
    "body":      BodyPart.TORSO,
    "right arm": BodyPart.RIGHT_ARM,
    "left arm":  BodyPart.LEFT_ARM,
    "arm":       BodyPart.RIGHT_ARM,
    "right leg": BodyPart.RIGHT_LEG,
    "left leg":  BodyPart.LEFT_LEG,
    "leg":       BodyPart.RIGHT_LEG,
    "legs":      BodyPart.RIGHT_LEG,
}


# ── Wound severity ────────────────────────────────────────────────────────────

class WoundSeverity(Enum):
    BRUISE     = 1   # cosmetic, minor pain, no bleed
    CUT        = 2   # minor bleed, some pain
    DEEP_WOUND = 3   # moderate bleed, significant pain, some impairment
    FRACTURE   = 4   # heavy bleed, severe pain, major impairment
    CRITICAL   = 5   # life-threatening, extreme pain


# Bleed per tick (blood_loss units, 0-100 scale)
BLEED_RATE: dict[WoundSeverity, int] = {
    WoundSeverity.BRUISE:     0,
    WoundSeverity.CUT:        1,
    WoundSeverity.DEEP_WOUND: 3,
    WoundSeverity.FRACTURE:   6,
    WoundSeverity.CRITICAL:   10,
}

# Raw pain (before location multiplier)
PAIN_BASE: dict[WoundSeverity, int] = {
    WoundSeverity.BRUISE:     4,
    WoundSeverity.CUT:        10,
    WoundSeverity.DEEP_WOUND: 22,
    WoundSeverity.FRACTURE:   38,
    WoundSeverity.CRITICAL:   55,
}

# Location pain multipliers
PAIN_MULT: dict[BodyPart, float] = {
    BodyPart.HEAD:      2.5,
    BodyPart.TORSO:     2.0,
    BodyPart.RIGHT_ARM: 1.0,
    BodyPart.LEFT_ARM:  1.0,
    BodyPart.RIGHT_LEG: 1.2,
    BodyPart.LEFT_LEG:  1.2,
}

# Narrative labels
WOUND_LABELS: dict[WoundSeverity, tuple[str, str]] = {
    WoundSeverity.BRUISE:     ("bruise",      "dull ache"),
    WoundSeverity.CUT:        ("cut",          "bleeding"),
    WoundSeverity.DEEP_WOUND: ("deep wound",   "bleeding freely"),
    WoundSeverity.FRACTURE:   ("fracture",     "bleeding heavily, possibly broken"),
    WoundSeverity.CRITICAL:   ("critical",     "life-threatening"),
}


@dataclass
class Wound:
    part: BodyPart
    severity: WoundSeverity
    age: int = 0

    def bleed_rate(self) -> int:
        return BLEED_RATE[self.severity]

    def pain(self) -> float:
        return PAIN_BASE[self.severity] * PAIN_MULT[self.part]

    def describe(self) -> str:
        label, detail = WOUND_LABELS[self.severity]
        return f"{label} — {detail}"


# ── Stat blocks ───────────────────────────────────────────────────────────────

@dataclass
class CombatStats:
    strength:   int   = 5    # damage dealt
    speed:      int   = 5    # dodge, initiative, flee
    toughness:  int   = 4    # damage reduction
    aggression: float = 0.3  # chance of counter-attacking vs fleeing
    size:       int   = 5    # grapple modifier (1=tiny, 10=huge)


# Mo's fixed stats — average human, no progression
MORIARTY_STATS = CombatStats(
    strength=5, speed=5, toughness=4, aggression=0.5, size=5
)

# Per-species stat blocks
ANIMAL_STATS: dict[str, CombatStats] = {
    "rabbit": CombatStats(strength=1, speed=8, toughness=1, aggression=0.1,  size=1),
    "deer":   CombatStats(strength=5, speed=5, toughness=3, aggression=0.25, size=7),
    "fox":    CombatStats(strength=3, speed=7, toughness=2, aggression=0.5,  size=3),
    "bird":   CombatStats(strength=1, speed=9, toughness=1, aggression=0.05, size=1),
    "animal": CombatStats(strength=3, speed=5, toughness=2, aggression=0.3,  size=3),
}

# Preferred attack locations per species
ATTACK_PREFS: dict[str, list[BodyPart]] = {
    "rabbit": [BodyPart.RIGHT_LEG, BodyPart.LEFT_LEG],
    "deer":   [BodyPart.RIGHT_LEG, BodyPart.LEFT_LEG, BodyPart.TORSO],
    "fox":    [BodyPart.RIGHT_ARM, BodyPart.LEFT_ARM, BodyPart.HEAD],
    "bird":   [BodyPart.HEAD, BodyPart.RIGHT_ARM],
    "animal": [BodyPart.TORSO, BodyPart.RIGHT_ARM],
}

ATTACK_VERBS: dict[str, str] = {
    "rabbit": "scratches at",
    "deer":   "kicks at",
    "fox":    "bites",
    "bird":   "pecks at",
    "animal": "strikes",
}


# ── Combat state (Mo's accumulated condition) ─────────────────────────────────

@dataclass
class CombatState:
    wounds:       list  = field(default_factory=list)
    blood_loss:   int   = 0      # 0-100; 80+ = critical, 100 = death
    shock:        int   = 0      # 0-100; 80+ = incapacitated
    grappled_with: object = None  # Animal entity or None
    dodge_stance: bool  = False  # set by dodge action; cleared each tick
    pending_grapple_msg: str = ""  # grapple counter-attack narrative for next tick

    # --- Derived conditions ---

    def total_pain(self) -> int:
        return min(100, int(sum(w.pain() for w in self.wounds)))

    def total_bleed_rate(self) -> int:
        return sum(w.bleed_rate() for w in self.wounds)

    def mobility(self) -> int:
        """0-100. Leg wounds reduce this. 0 = can't move."""
        leg_wounds = [w for w in self.wounds
                      if w.part in (BodyPart.RIGHT_LEG, BodyPart.LEFT_LEG)]
        return max(0, 100 - sum(w.severity.value * 18 for w in leg_wounds))

    def grip_strength(self) -> int:
        """0-100. Arm wounds reduce this. 0 = can't hold weapon."""
        arm_wounds = [w for w in self.wounds
                      if w.part in (BodyPart.RIGHT_ARM, BodyPart.LEFT_ARM)]
        return max(0, 100 - sum(w.severity.value * 15 for w in arm_wounds))

    def is_conscious(self) -> bool:
        head_crit = any(
            w.part == BodyPart.HEAD and w.severity.value >= 4
            for w in self.wounds
        )
        return not head_crit and self.shock < 90 and self.blood_loss < 100

    def wound_at(self, part: BodyPart):
        hits = [w for w in self.wounds if w.part == part]
        return max(hits, key=lambda w: w.severity.value) if hits else None

    def apply_wound(self, wound: Wound):
        """Add wound; upgrade severity if same part is already wounded."""
        existing = self.wound_at(wound.part)
        if existing:
            if wound.severity.value > existing.severity.value:
                self.wounds.remove(existing)
                self.wounds.append(wound)
        else:
            self.wounds.append(wound)

    @property
    def any_wounds(self) -> bool:
        return bool(self.wounds)

    # --- Tick update ---

    def tick(self, world_state=None):
        """Called each game tick. Apply bleeding, update shock, age wounds."""
        bleed = self.total_bleed_rate()
        self.blood_loss = min(100, self.blood_loss + bleed)
        pain = self.total_pain()
        self.shock = min(100, int(pain * 0.3 + self.blood_loss * 0.4))
        for w in self.wounds:
            w.age += 1
        self.dodge_stance = False  # cleared each tick

        # Grappled animal attacks each tick
        if self.grappled_with and self.grappled_with.alive:
            animal = self.grappled_with
            stats = ANIMAL_STATS.get(animal.species, ANIMAL_STATS["animal"])
            msg = _animal_attack(self, animal, stats, MORIARTY_STATS)
            self.pending_grapple_msg = msg
        elif self.grappled_with and not self.grappled_with.alive:
            self.grappled_with = None

    # --- Perception text ---

    def describe_body(self) -> str:
        order = [
            BodyPart.HEAD, BodyPart.TORSO,
            BodyPart.RIGHT_ARM, BodyPart.LEFT_ARM,
            BodyPart.RIGHT_LEG, BodyPart.LEFT_LEG,
        ]
        lines = []
        for part in order:
            w = self.wound_at(part)
            status = w.describe() if w else "clear"
            lines.append(f"  {part.value:<12} {status}")
        return "\n".join(lines)

    def describe_conditions(self) -> str:
        pain = self.total_pain()
        pain_desc = (
            "excruciating — hard to think straight" if pain > 75 else
            "severe — difficult to focus"           if pain > 50 else
            "significant — noticeable intrusion"    if pain > 30 else
            "moderate — distracting"                if pain > 15 else
            "mild"                                  if pain >  5 else
            "none"
        )
        lines = [f"  Pain:      {pain_desc}"]
        if self.blood_loss > 0:
            blood_desc = (
                "critical — losing blood fast"    if self.blood_loss > 70 else
                "serious — pooling steadily"      if self.blood_loss > 45 else
                "moderate — a real flow"          if self.blood_loss > 25 else
                "low — just a trickle"
            )
            lines.append(f"  Blood loss: {blood_desc}")
        if self.shock > 10:
            shock_desc = (
                "severe — edges of things blurring"  if self.shock > 60 else
                "moderate — shaky, cold, distant"    if self.shock > 35 else
                "mild — slightly unreal feeling"
            )
            lines.append(f"  Shock:      {shock_desc}")
        mob = self.mobility()
        if mob < 80:
            lines.append(f"  Mobility:   {'can barely walk' if mob < 30 else 'impaired — movement costs more'}")
        grip = self.grip_strength()
        if grip < 70:
            lines.append(f"  Grip:       {'weapon may slip' if grip < 40 else 'weakened'}")
        if self.grappled_with:
            lines.append(f"  GRAPPLED:   locked with {self.grappled_with.name} — can't move or flee")
        if not self.is_conscious():
            lines.append("  ** UNCONSCIOUS **")
        return "\n".join(lines)


# ── Dice and resolution helpers ───────────────────────────────────────────────

def _roll(n: int = 2, sides: int = 6) -> int:
    return sum(random.randint(1, sides) for _ in range(n))


def _severity_from_margin(margin: int, toughness: int) -> WoundSeverity:
    effective = margin - max(0, toughness - 4)
    if effective <= 1:
        return WoundSeverity.BRUISE
    elif effective <= 3:
        return WoundSeverity.CUT
    elif effective <= 6:
        return WoundSeverity.DEEP_WOUND
    elif effective <= 9:
        return WoundSeverity.FRACTURE
    else:
        return WoundSeverity.CRITICAL


def _animal_attack(
    combat_state: CombatState,
    attacker,
    a_stats: CombatStats,
    d_stats: CombatStats,
) -> str:
    """Animal attacks Mo. Mutates combat_state. Returns narrative."""
    prefs = ATTACK_PREFS.get(attacker.species, [BodyPart.TORSO])
    part = random.choice(prefs)
    verb = ATTACK_VERBS.get(attacker.species, "strikes")

    dodge_bonus = 3 if combat_state.dodge_stance else 0
    atk = _roll() + (a_stats.strength - 5)
    tgt = 7 - (d_stats.speed - 5) + dodge_bonus

    if atk < tgt:
        return f"The {attacker.name} {verb} your {part.value} — you pull back just in time."

    margin = atk - tgt
    sev = _severity_from_margin(margin + a_stats.strength - 3, d_stats.toughness)
    wound = Wound(part=part, severity=sev)
    combat_state.apply_wound(wound)
    label, detail = WOUND_LABELS[sev]
    return f"The {attacker.name} {verb} your {part.value} — {label}. {detail.capitalize()}."


# ── Public resolution API ─────────────────────────────────────────────────────

def resolve_attack(
    combat_state: CombatState,
    target,              # Animal entity
    target_part,         # BodyPart or None (random)
    weapon_damage: int,
    world_state,
) -> str:
    """
    Full combat exchange: Mo attacks → animal counter-attacks.
    Mutates both combat_state and target.health.
    Returns complete narrative string (multi-line).
    """
    a_stats = MORIARTY_STATS
    d_stats = ANIMAL_STATS.get(target.species, ANIMAL_STATS["animal"])
    part = target_part or random.choice(list(BodyPart))

    # — Mo's attack —
    grip_penalty = 2 if combat_state.grip_strength() < 50 else 0
    atk = _roll() + (a_stats.strength - 5) + weapon_damage // 3 - grip_penalty
    tgt = 7 + d_stats.speed // 3

    lines = []

    if atk < tgt:
        lines.append(f"You swing at the {target.name}'s {part.value} — it dodges, fluid and fast.")
    else:
        margin = atk - tgt
        sev = _severity_from_margin(margin + weapon_damage - 3, d_stats.toughness)
        label, detail = WOUND_LABELS[sev]
        lines.append(f"You strike the {target.name}'s {part.value} — {label}. {detail.capitalize()}.")
        # Apply damage to animal
        died = target.take_damage(sev.value * 2, world_state)
        if died == "dead":
            lines.append(f"The {target.name} shudders and goes still.")
            if combat_state.grappled_with is target:
                combat_state.grappled_with = None
                lines.append("The grapple is over.")
            return "\n".join(lines)

    # — Animal counter-attack (if aggressive enough) —
    if random.random() < d_stats.aggression:
        counter = _animal_attack(combat_state, target, d_stats, a_stats)
        lines.append(counter)
    else:
        lines.append(f"The {target.name} flinches back but doesn't press the attack.")

    combat_state.dodge_stance = False
    return "\n".join(lines)


def resolve_grapple(
    combat_state: CombatState,
    target,
) -> str:
    """Attempt to grapple an adjacent animal."""
    if combat_state.grappled_with:
        return "You're already grappled — break free first."
    if combat_state.grip_strength() < 30:
        return "Your arm is too badly hurt to grab anything."

    a_stats = MORIARTY_STATS
    d_stats = ANIMAL_STATS.get(target.species, ANIMAL_STATS["animal"])

    atk = _roll() + a_stats.strength + a_stats.size // 2
    dfn = _roll() + d_stats.strength + d_stats.size // 2

    if atk > dfn:
        combat_state.grappled_with = target
        return (
            f"You seize the {target.name} — it thrashes and bites but you hold on.\n"
            f"You're now grappled. It will attack every tick. Use 'break grapple' or 'attack' to finish it."
        )
    return f"You lunge for the {target.name} but it twists away before you can grip it."


def resolve_break_grapple(combat_state: CombatState) -> str:
    """Attempt to break free from a grapple."""
    if not combat_state.grappled_with:
        return "You're not grappled."
    d_stats = ANIMAL_STATS.get(combat_state.grappled_with.species, ANIMAL_STATS["animal"])
    a_stats = MORIARTY_STATS

    atk = _roll() + a_stats.strength + a_stats.speed // 2
    dfn = _roll() + d_stats.strength + d_stats.size // 2

    if atk > dfn:
        name = combat_state.grappled_with.name
        combat_state.grappled_with = None
        return f"You wrench free from the {name} — distance between you now."
    return f"You strain against the {combat_state.grappled_with.name}'s grip but can't break free."


def resolve_dodge(combat_state: CombatState) -> str:
    """Take a defensive stance — boosts dodge next incoming hit."""
    if not combat_state.is_conscious():
        return "You can't do much in this state."
    combat_state.dodge_stance = True
    return "You settle into a defensive stance. Incoming attacks will be harder to land."


def resolve_flee_combat(combat_state: CombatState, actor, world_state) -> tuple[bool, str]:
    """Attempt to flee. Returns (success, message)."""
    if combat_state.grappled_with:
        return False, f"You're locked with the {combat_state.grappled_with.name} — break free first."
    mob = combat_state.mobility()
    if mob < 20:
        return False, "Your legs won't carry you — too injured to run."
    flee_roll = _roll() + MORIARTY_STATS.speed + mob // 25
    if flee_roll >= 10:
        return True, "You break away and put ground between yourself and the fight."
    return False, "You scramble to flee but the animal closes the gap — still in it."
