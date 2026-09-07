"""Calibrated level benefits from the maintained Duck Hunt v3 table."""

from __future__ import annotations

from dataclasses import dataclass


MAX_CALIBRATED_LEVEL = 100


@dataclass(frozen=True, slots=True)
class LevelPolicy:
    """One bounded combat profile attached to a displayed player level."""

    level: int
    weapon_key: str
    weapon_label: str
    accuracy_bps: int
    jam_bps: int
    ammo_capacity: int
    magazine_capacity: int
    armor_bps: int
    deflection_bps: int
    miss_penalty: int
    wild_penalty: int
    incident_penalty: int
    silent: bool
    nuisance_immune: bool


_LOW_ACCURACY_PERCENT = (
    55,
    55,
    57,
    59,
    61,
    63,
    65,
    66,
    67,
    67,
    70,
    71,
    72,
    73,
    74,
    75,
    76,
    77,
    78,
    78,
    81,
    82,
    83,
    84,
    85,
    86,
    87,
    88,
    89,
    89,
    92,
    93,
    93,
    94,
    94,
    95,
    95,
    96,
    96,
    97,
)

_LOW_RELIABILITY_PERCENT = (
    85,
    85,
    86,
    87,
    88,
    89,
    90,
    91,
    92,
    92,
    94,
    94,
    95,
    95,
    95,
    96,
    96,
    96,
    96,
    96,
    97,
    97,
    97,
    97,
    97,
    98,
    98,
    98,
    98,
    98,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
)

_LOW_ARMOR_PERCENT = (
    0,
    0,
    2,
    5,
    7,
    10,
    12,
    15,
    17,
    20,
    22,
    25,
    27,
    30,
    32,
    35,
    37,
    40,
    42,
    45,
    47,
    50,
    52,
    55,
    57,
    60,
    62,
    65,
    67,
    70,
    72,
    75,
    77,
    80,
    82,
    85,
    86,
    87,
    88,
    89,
)

_LOW_DEFLECTION_PERCENT = (
    0,
    0,
    0,
    1,
    2,
    4,
    6,
    8,
    10,
    12,
    14,
    16,
    18,
    20,
    22,
    24,
    26,
    28,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    48,
    49,
    49,
)


def level_policy(level: int) -> LevelPolicy:
    """Return the exact v3 policy, clamping post-table levels to level 100."""

    if type(level) is not int or level < 1:
        raise ValueError("level must be a positive integer")
    calibrated = min(level, MAX_CALIBRATED_LEVEL)

    if calibrated < 10:
        weapon_key, weapon_label = "machine_gun", "mitraillette"
        ammo_capacity, magazine_capacity = 6, 2
    elif calibrated < 20:
        weapon_key, weapon_label = "assault_rifle", "fusil d'assaut"
        ammo_capacity, magazine_capacity = 4, 3
    elif calibrated < 30:
        weapon_key, weapon_label = "shotgun", "fusil de chasse"
        ammo_capacity, magazine_capacity = 2, 4
    elif calibrated < 40:
        weapon_key, weapon_label = "sniper_rifle", "fusil de précision"
        ammo_capacity, magazine_capacity = 1, 6
    elif calibrated < 60:
        weapon_key, weapon_label = "bow", "arc"
        ammo_capacity, magazine_capacity = 1, 5
    else:
        weapon_key, weapon_label = "crossbow", "arbalète"
        ammo_capacity, magazine_capacity = 1, 5

    if calibrated < 40:
        accuracy_percent = _LOW_ACCURACY_PERCENT[calibrated]
        reliability_percent = _LOW_RELIABILITY_PERCENT[calibrated]
        armor_percent = _LOW_ARMOR_PERCENT[calibrated]
        deflection_percent = _LOW_DEFLECTION_PERCENT[calibrated]
    elif calibrated < 60:
        accuracy_percent = 90 + (calibrated - 40) // 5
        reliability_percent = 100
        armor_percent = min(100, 90 + calibrated - 40)
        deflection_percent = 50
    else:
        accuracy_percent = min(99, 94 + (calibrated - 60) // 5)
        if calibrated < 70:
            reliability_percent = 90
        elif calibrated < 80:
            reliability_percent = 91
        elif calibrated < 90:
            reliability_percent = 92
        elif calibrated < 95:
            reliability_percent = 93
        elif calibrated < 100:
            reliability_percent = 94
        else:
            reliability_percent = 95
        armor_percent = 100
        deflection_percent = 75

    if calibrated < 10:
        miss_penalty, wild_penalty, incident_penalty = 1, 1, 4
    elif calibrated < 20:
        miss_penalty, wild_penalty, incident_penalty = 1, 2, 6
    elif calibrated < 30:
        miss_penalty, wild_penalty, incident_penalty = 2, 5, 10
    elif calibrated < 40:
        miss_penalty, wild_penalty, incident_penalty = 4, 8, 15
    elif calibrated < 60:
        miss_penalty, wild_penalty, incident_penalty = 5, 10, 20
    elif calibrated < 70:
        miss_penalty, wild_penalty, incident_penalty = 6, 10, 25
    elif calibrated < 80:
        miss_penalty, wild_penalty, incident_penalty = 7, 12, 26
    elif calibrated < 90:
        miss_penalty, wild_penalty, incident_penalty = 8, 14, 27
    elif calibrated < 100:
        miss_penalty, wild_penalty, incident_penalty = 9, 16, 28
    else:
        miss_penalty, wild_penalty, incident_penalty = 10, 18, 30

    silent = calibrated >= 40
    return LevelPolicy(
        level=calibrated,
        weapon_key=weapon_key,
        weapon_label=weapon_label,
        accuracy_bps=accuracy_percent * 100,
        jam_bps=(100 - reliability_percent) * 100,
        ammo_capacity=ammo_capacity,
        magazine_capacity=magazine_capacity,
        armor_bps=armor_percent * 100,
        deflection_bps=deflection_percent * 100,
        miss_penalty=miss_penalty,
        wild_penalty=wild_penalty,
        incident_penalty=incident_penalty,
        silent=silent,
        nuisance_immune=silent,
    )
