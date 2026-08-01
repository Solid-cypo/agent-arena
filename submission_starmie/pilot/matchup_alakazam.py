"""Alakazam (胡地) matchup: confirmed ID + Plan B finisher window.

ID-001: sticky `confirmed` only on hard signals (Abra/Kadabra/Alakazam public).
WINDOW: opp Stage-1 (Kadabra) KO'd our Budew last opp turn → finisher window
        (Mega Starmie + Unfair Stamp). Soft signals never switch plan.
"""
from __future__ import annotations

from typing import Any

ABRA = 741
KADABRA = 742
ALAKAZAM = 743
BUDEW = 235
UNFAIR_STAMP = 1080
MEGA_STARMIE = 1031
STARYU = 1030
SNORUNT = 860
FROSLASS_104 = 104
MUNKIDORI = 112
SWITCH_CARD = 1123
HILDA = 1225
CRISPIN = 1198
POKE_PAD = 1152
ULTRA_BALL = 1121
POFFIN = 1086
WATER_BASIC = 3
DARK_BASIC = 7
PRISM = 16
_WATER_IDS = frozenset({WATER_BASIC, PRISM})
_DARK_IDS = frozenset({DARK_BASIC})

HARD_LINE = frozenset({ABRA, KADABRA, ALAKAZAM})
# Expert「一进」= Stage 1; Kadabra is the primary Stage-1 on this line.
STAGE1_IDS = frozenset({KADABRA})

def _si(x, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def _pokemon_list(player) -> list:
    out = []
    for p in player.active or []:
        if p is not None:
            out.append(p)
    for p in player.bench or []:
        if p is not None:
            out.append(p)
    return out


def _ids_from_cards(cards) -> set[int]:
    ids: set[int] = set()
    for c in cards or []:
        if c is None:
            continue
        cid = _si(getattr(c, "id", None))
        if cid > 0:
            ids.add(cid)
    return ids


def opp_public_pokemon_ids(obs, my_index: int) -> set[int]:
    """Opponent active + bench + discard card ids (visible hard signals)."""
    try:
        opp = obs.current.players[1 - my_index]
    except Exception:
        return set()
    ids = _ids_from_cards(_pokemon_list(opp))
    ids |= _ids_from_cards(getattr(opp, "discard", None) or [])
    # Revealed prize cards (engine may expose full list or only count)
    prize = getattr(opp, "prize", None) or []
    if prize and not isinstance(prize[0], int):
        ids |= _ids_from_cards(prize)
    return ids


def my_has_budew(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
    except Exception:
        return False
    return BUDEW in _ids_from_cards(_pokemon_list(me))


def my_active_is_budew(obs, my_index: int) -> bool:
    try:
        active = (obs.current.players[my_index].active or [None])[0]
        return bool(active) and _si(getattr(active, "id", None)) == BUDEW
    except Exception:
        return False


def opp_active_ids(obs, my_index: int) -> set[int]:
    try:
        active = obs.current.players[1 - my_index].active or []
        return _ids_from_cards(active)
    except Exception:
        return set()


def opp_active_is_stage1(obs, my_index: int) -> bool:
    """True if opp Active is Kadabra or any Stage-1 (has preEvolution)."""
    try:
        active = (obs.current.players[1 - my_index].active or [None])[0]
        if not active:
            return False
        cid = _si(getattr(active, "id", None))
        if cid in STAGE1_IDS:
            return True
        pre = getattr(active, "preEvolution", None) or []
        # Stage-1: non-empty preEvolution and not already a Stage-2 with Stage-1 in line
        # Heuristic: exactly one pre-evo layer → Stage 1; Kadabra always True above.
        if pre and cid not in HARD_LINE:
            return True
        if pre and cid == KADABRA:
            return True
        return False
    except Exception:
        return False


def hand_has_id(obs, my_index: int, card_id: int) -> bool:
    try:
        for c in obs.current.players[my_index].hand or []:
            if c and _si(getattr(c, "id", None)) == card_id:
                return True
    except Exception:
        pass
    return False


def hand_count_id(obs, my_index: int, card_id: int) -> int:
    n = 0
    try:
        for c in obs.current.players[my_index].hand or []:
            if c and _si(getattr(c, "id", None)) == card_id:
                n += 1
    except Exception:
        pass
    return n


def _energy_id(e) -> int:
    return _si(getattr(e, "id", e))


def _has_energy(pkm, ids) -> bool:
    for e in getattr(pkm, "energies", None) or []:
        if e is not None and _energy_id(e) in ids:
            return True
    return False


def _remaining_hp(pkm) -> int:
    """Engine convention: pkm.hp is remaining HP (maxHp - damage)."""
    return _si(getattr(pkm, "hp", None), 10**6)


def lock_deadline(board) -> int:
    """OA-LOCK deadline in my-turn numbers: T3 going first / T2 going second."""
    going_first = _si(getattr(board, "my_index", 0)) == _si(
        getattr(board, "first_player", 0)
    )
    return 3 if going_first else 2


def in_lock_window(board) -> bool:
    if board is None:
        return False
    mt = _si(getattr(board, "my_turn_number", 0))
    return 1 <= mt <= lock_deadline(board)


def oa_lock_state(obs, my_index: int, board) -> dict[str, bool]:
    """OA-LOCK pieces (frozen metrics 20260731):
    Active Budew + bench Froslass 104 + bench Munkidori with Dark."""
    budew_active = my_active_is_budew(obs, my_index)
    fro104 = bool(getattr(board, "froslass_104_on_field", False)) if board else False
    munk = bool(getattr(board, "munkidori_on_field", False)) if board else False
    munk_dark = munk and bool(getattr(board, "munkidori_has_dark", False))
    return {
        "budew_active": budew_active,
        "budew_on_field": my_has_budew(obs, my_index),
        "froslass104": fro104,
        "munk_on_field": munk,
        "munk_dark": munk_dark,
        "lock_done": budew_active and fro104 and munk_dark,
    }


def oa_arm_state(board) -> dict[str, bool]:
    """OA-ARM (frozen metrics): armed Mega Starmie (or Staryu+water) waiting on bench."""
    if board is None:
        return {"arm_done": False, "arm_partial": False}
    mega_bench_water = bool(getattr(board, "bench_mega_starmie_has_water", False))
    mega_on = bool(getattr(board, "mega_starmie_on_field", False))
    staryu_on = bool(getattr(board, "staryu_on_field", False))
    active_is_mega = bool(getattr(board, "active_is_mega_starmie", False))
    return {
        "arm_done": mega_bench_water,
        # partial: line exists off-Active (still convertible next turn)
        "arm_partial": (mega_on and not active_is_mega) or staryu_on,
    }


def doublekill_ready(obs, my_index: int) -> bool:
    """Frozen predicate: my Active Mega Starmie with water AND
    opp Active remaining HP <= 120 AND >=1 opp bench remaining HP <= 50."""
    try:
        me = obs.current.players[my_index]
        active = (me.active or [None])[0]
        if not active or _si(getattr(active, "id", None)) != MEGA_STARMIE:
            return False
        if not _has_energy(active, _WATER_IDS):
            return False
        opp = obs.current.players[1 - my_index]
        oa = (opp.active or [None])[0]
        if not oa or _remaining_hp(oa) > 120:
            return False
        for b in opp.bench or []:
            if b is not None and 0 < _remaining_hp(b) <= 50:
                return True
        return False
    except Exception:
        return False


def alak_lock_pick_order(obs, board, my_index: int) -> tuple[int, ...]:
    """Deck-search pick order while chasing OA-LOCK (missing pieces first).

    Used for Poffin/Pad/Ball selects inside the LOCK window; Staryu stays in
    the list so OA-ARM keeps a base once LOCK pieces are covered.
    """
    st = oa_lock_state(obs, my_index, board)
    snorunt_on = bool(getattr(board, "snorunt_on_field", False)) if board else False
    order: list[int] = []
    if not st["budew_on_field"]:
        order.append(BUDEW)
    # GS (deadline T2): Snorunt must land T1 for 104 by T2 — it outranks
    # Munkidori in searches (munk reaches the field naturally more often).
    snorunt_first = lock_deadline(board) == 2 if board is not None else False
    need_snorunt = not (st["froslass104"] or snorunt_on)
    if snorunt_first and need_snorunt:
        order.append(SNORUNT)
    if not st["munk_on_field"]:
        order.append(MUNKIDORI)
    if need_snorunt and not snorunt_first:
        order.append(SNORUNT)
    if snorunt_on and not st["froslass104"]:
        order.append(FROSLASS_104)
    if not (
        bool(getattr(board, "staryu_on_field", False))
        or bool(getattr(board, "mega_starmie_on_field", False))
    ):
        order.append(STARYU)
    return tuple(order)


def refresh_alakazam_matchup(
    state: dict[str, Any],
    obs,
    my_index: int,
    my_turn_number: int,
) -> dict[str, Any]:
    """Update sticky matchup flags on agent_state; return sit fragment."""
    pub = opp_public_pokemon_ids(obs, my_index)
    if pub & HARD_LINE:
        state["matchup_alakazam_confirmed"] = True

    confirmed = bool(state.get("matchup_alakazam_confirmed"))
    has_budew = my_has_budew(obs, my_index)

    # Mid-turn KO watch: the engine forces a promote select DURING the
    # opponent's turn right after our Budew dies — my_turn hasn't advanced
    # yet, but prev_my_had_budew would be overwritten below and the boundary
    # check would miss the KO. Latch it here.
    last_mt = int(state.get("alak_last_my_turn", -1))
    if (
        my_turn_number == last_mt
        and state.get("alak_prev_my_had_budew")
        and not has_budew
    ):
        state["alak_budew_ko_pending"] = True

    # Turn-boundary: detect Budew KO during opponent's turn
    if my_turn_number != last_mt:
        if (
            confirmed
            and (state.get("alak_prev_my_had_budew") or state.get("alak_budew_ko_pending"))
            and not has_budew
        ):
            state["alak_budew_ko_last_opp_turn"] = True
            if opp_active_is_stage1(obs, my_index) or (opp_active_ids(obs, my_index) & STAGE1_IDS):
                state["alak_finisher_window"] = True
                state["alak_follow_window"] = False
            else:
                # WN-WIDE (v2 20260801): KO'd by non-Stage-1 (A1 reality:
                # Alakazam 160-200 OHKO) — open the follow-style window
                # (Stamp raised via budew_ko flag; Jetting/promote via follow).
                state["alak_finisher_window"] = False
                state["alak_follow_window"] = True
        else:
            # New my-turn: previous finisher becomes follow; clear finisher
            if state.get("alak_finisher_window"):
                state["alak_follow_window"] = True
            state["alak_finisher_window"] = False
            state["alak_budew_ko_last_opp_turn"] = False
        state["alak_budew_ko_pending"] = False
        state["alak_last_my_turn"] = my_turn_number

    state["alak_prev_my_had_budew"] = has_budew

    return {
        "matchup_alakazam_confirmed": confirmed,
        "alak_finisher_window": bool(state.get("alak_finisher_window")),
        "alak_follow_window": bool(state.get("alak_follow_window")),
        "alak_budew_ko_last_opp_turn": bool(state.get("alak_budew_ko_last_opp_turn")),
        "alak_opp_hard_ids": sorted(pub & HARD_LINE),
    }


def protect_unfair_stamp_discard(
    obs, option, my_index: int, confirmed: bool, dominate_plus: float
) -> float:
    """Ban discarding last Unfair Stamp when matchup confirmed."""
    if not confirmed:
        return 0.0
    try:
        from cg.api import OptionType, SelectContext  # type: ignore
    except Exception:
        return 0.0
    if getattr(option, "type", None) != OptionType.CARD:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    if ctx != int(SelectContext.DISCARD):
        return 0.0
    # option card id
    try:
        from cg.api import AreaType  # type: ignore
        area = getattr(option, "area", None)
        idx = _si(getattr(option, "index", None), -1)
        me = obs.current.players[my_index]
        card = None
        if area == AreaType.HAND:
            hand = me.hand or []
            if 0 <= idx < len(hand):
                card = hand[idx]
        elif area == AreaType.DISCARD:
            return 0.0
        else:
            # fall through: try hand by index only
            hand = me.hand or []
            if 0 <= idx < len(hand):
                card = hand[idx]
        if not card or _si(getattr(card, "id", None)) != UNFAIR_STAMP:
            return 0.0
    except Exception:
        return 0.0
    if hand_count_id(obs, my_index, UNFAIR_STAMP) <= 1:
        return -dominate_plus
    return 0.0


def alakazam_plan_b_hard_bonus(
    obs,
    option,
    sit: dict[str, Any],
    *,
    dominate: float,
    dominate_mid: float,
    dominate_plus: float,
    dominate_open: float,
    dominate_attack: float,
    hand_card_id_fn,
    attack_id_fn,
    itchy_pollen_id: int,
    jetting_id: int,
    option_type_play,
    option_type_attack,
    option_type_evolve,
    option_type_card,
    select_switch_contexts: tuple[int, ...],
    dominate_path: float = 0.0,
    attach_target_fn=None,
    attach_energy_fn=None,
    evolve_104_fn=None,
    card_option_id_fn=None,
    option_type_attach=None,
    option_type_retreat=None,
    select_search_contexts: tuple[int, ...] = (),
) -> float:
    """Layer-1 bonuses for Plan B. 0 if not confirmed."""
    if not sit.get("matchup_alakazam_confirmed"):
        return 0.0

    mi = sit["my_index"]
    board = sit.get("board")
    phase = sit.get("phase")
    finisher = bool(sit.get("alak_finisher_window"))
    follow = bool(sit.get("alak_follow_window"))
    phase_name = getattr(phase, "primary", None) if phase is not None else None

    # ── Double kill (frozen 120/50): Jetting dominates all other attacks ──
    if option.type == option_type_attack and doublekill_ready(obs, mi):
        if attack_id_fn(option) == jetting_id:
            return dominate_attack + 10.0
        # short-circuit alternatives below Jetting but above baseline attacks
        return dominate_attack - 50.0

    # ── Finisher / follow: Unfair Stamp (合法前提：上回合我方被击倒，含羞苞被打死) ──
    if option.type == option_type_play:
        cid = hand_card_id_fn(obs, option, mi)
        if cid == UNFAIR_STAMP and (
            finisher or sit.get("alak_budew_ko_last_opp_turn") or sit.get("harvest_ko_last_turn")
        ):
            return dominate_open

    # ── Finisher / follow: prefer Jetting on Mega Starmie ──
    if (finisher or follow) and option.type == option_type_attack:
        atk = attack_id_fn(option)
        if atk == jetting_id and board is not None and getattr(
            board, "active_is_mega_starmie", False
        ):
            return dominate_attack + 5.0

    # Promote Mega Starmie on SWITCH during finisher window
    poke_fn = sit.get("_pokemon_in_area_fn")
    if finisher and option.type == option_type_card and callable(poke_fn):
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in select_switch_contexts:
            try:
                pkm = poke_fn(
                    obs, option.area, _si(getattr(option, "index", None)), mi
                )
                if pkm and _si(getattr(pkm, "id", None)) == MEGA_STARMIE:
                    return dominate_plus
                if pkm and _si(getattr(pkm, "id", None)) == STARYU:
                    return -dominate_mid
            except Exception:
                pass

    # ── Budew wall: never voluntarily switch/retreat Budew out of Active ──
    # (Expert line: the wall stays until the opponent breaks it → WINDOW.)
    if not finisher and not follow and my_active_is_budew(obs, mi):
        if option_type_retreat is not None and option.type == option_type_retreat:
            return -dominate_mid
        if option.type == option_type_play and hand_card_id_fn(obs, option, mi) == SWITCH_CARD:
            return -dominate_mid

    # ── LOCK window: benched Budew must reach Active — Switch is x1, so also
    # allow paying retreat (TO_ACTIVE select then picks Budew at dominate_path).
    if (
        not finisher
        and option_type_retreat is not None
        and option.type == option_type_retreat
        and in_lock_window(board)
        and my_has_budew(obs, mi)
        and not my_active_is_budew(obs, mi)
    ):
        return dominate_open - 15.0

    # ── Early Plan B: Budew lock (confirmed, not finisher) ──
    if not finisher and phase_name in ("OPENING", "AGGRESSION", None):
        in_window = in_lock_window(board)
        last_call = in_window and _si(
            getattr(board, "my_turn_number", 0)
        ) == lock_deadline(board)
        st = oa_lock_state(obs, mi, board)
        bench_open = int(getattr(board, "bench_open", 0) or 0) if board else 0
        snorunt_on = bool(getattr(board, "snorunt_on_field", False)) if board else False

        if option.type == option_type_play:
            cid = hand_card_id_fn(obs, option, mi)
            if cid == BUDEW:
                if bench_open > 0:
                    # In LOCK window Budew outranks generic setup (deadline-aware).
                    return dominate_open if in_window else dominate
            # LOCK window: Munkidori / Snorunt exempt from DEMOTE_SIDE and raised.
            if in_window and bench_open > 0:
                if cid == MUNKIDORI and not st["munk_on_field"]:
                    return dominate_mid + 30.0
                if cid == SNORUNT and not (st["froslass104"] or snorunt_on):
                    # GS T1: Snorunt must land now for 104 by the T2 deadline.
                    if (
                        lock_deadline(board) == 2
                        and _si(getattr(board, "my_turn_number", 0)) == 1
                    ):
                        return dominate_open - 3.0
                    return dominate_mid + 20.0
            # LOCK window: promote benched Budew to Active via Switch card.
            if (
                in_window
                and cid == SWITCH_CARD
                and st["budew_on_field"]
                and not st["budew_active"]
            ):
                return dominate_open
            # LOCK window: search items/supporters chase the missing pieces.
            if in_window:
                if cid == POFFIN and (
                    not st["budew_on_field"]
                    or not (st["froslass104"] or snorunt_on)
                ):
                    return dominate_open
                if cid in (POKE_PAD, ULTRA_BALL) and (
                    not st["munk_on_field"]
                    or (
                        snorunt_on
                        and not st["froslass104"]
                        and not hand_has_id(obs, mi, FROSLASS_104)
                    )
                ):
                    return dominate_open - 5.0
                if (
                    cid == HILDA
                    and snorunt_on
                    and not st["froslass104"]
                    and not hand_has_id(obs, mi, FROSLASS_104)
                ):
                    return dominate_open - 10.0
                # Crispin: the dark-to-Munkidori pipeline is already wired
                # (ATTACH_TO allows DARK when munk needs it) — raise the play
                # when munk sits dry and no dark is in hand. Supporter slot is
                # 1/turn: when the 104 line is live (Snorunt down, 104 still
                # missing) Hilda's search outranks Crispin.
                if (
                    cid == CRISPIN
                    and st["munk_on_field"]
                    and not st["munk_dark"]
                    and not hand_has_id(obs, mi, 7)  # DARK_BASIC
                ):
                    line_104_live = (
                        snorunt_on
                        and not st["froslass104"]
                        and not hand_has_id(obs, mi, FROSLASS_104)
                    )
                    return dominate_open - (12.0 if line_104_live else 8.0)

        # LOCK window: evolve Snorunt → Froslass 104 immediately.
        if (
            in_window
            and option.type == option_type_evolve
            and callable(evolve_104_fn)
            and not st["froslass104"]
            and evolve_104_fn(obs, option, mi)
        ):
            return dominate_open

        # LOCK window: Dark on Munkidori (last-call beats the water-line attach).
        if (
            option_type_attach is not None
            and option.type == option_type_attach
            and in_window
            and st["munk_on_field"]
            and not st["munk_dark"]
            and callable(attach_target_fn)
            and callable(attach_energy_fn)
        ):
            try:
                target = attach_target_fn(obs, option, mi)
                eid = attach_energy_fn(obs, option, mi)
            except Exception:
                target, eid = None, 0
            if target is not None and _si(getattr(target, "id", None)) == MUNKIDORI and eid in _DARK_IDS:
                # LOCK (65%) outranks ARM (50%, has +1 turn slack): Dark on
                # Munkidori beats the water-line attach inside the window.
                if dominate_path:
                    return dominate_path + 2.0
                return dominate_mid + 10.0

        # LOCK window: retreat fuel — benched Budew, no Switch in hand, dry
        # Active → any energy on Active enables paying retreat next decision.
        # Low priority: only fires when Munk-dark / water-line attaches不存在.
        if (
            option_type_attach is not None
            and option.type == option_type_attach
            and in_window
            and st["budew_on_field"]
            and not st["budew_active"]
            and not hand_has_id(obs, mi, SWITCH_CARD)
            and callable(attach_target_fn)
        ):
            try:
                target = attach_target_fn(obs, option, mi)
                active = (obs.current.players[mi].active or [None])[0]
            except Exception:
                target, active = None, None
            if (
                target is not None
                and active is not None
                and target is active
                and not (getattr(active, "energies", None) or [])
                and _si(getattr(active, "id", None)) != MEGA_STARMIE
            ):
                return dominate_mid - 30.0

        if option.type == option_type_attack and my_active_is_budew(obs, mi):
            atk = attack_id_fn(option)
            if itchy_pollen_id and atk == itchy_pollen_id:
                return dominate
            return dominate_mid

        # LOCK window: deck-search picks (Poffin/Pad/Ball) chase missing pieces.
        if (
            in_window
            and option.type == option_type_card
            and callable(card_option_id_fn)
            and select_search_contexts
            and dominate_path
        ):
            try:
                ctx = int(obs.select.context)
            except Exception:
                ctx = -1
            if ctx in select_search_contexts:
                cid = card_option_id_fn(obs, option, mi)
                order = alak_lock_pick_order(obs, board, mi)
                if cid in order:
                    return dominate_path + 8.0 - float(order.index(cid))

        if (
            option.type == option_type_card
            and (phase_name == "OPENING" or in_window)
            and callable(poke_fn)
        ):
            try:
                ctx = int(obs.select.context)
            except Exception:
                ctx = -1
            if ctx in select_switch_contexts:
                try:
                    pkm = poke_fn(
                        obs, option.area, _si(getattr(option, "index", None)), mi
                    )
                    if (
                        pkm
                        and _si(getattr(pkm, "id", None)) == BUDEW
                        and board is not None
                        and not getattr(board, "active_is_mega_starmie", False)
                    ):
                        # In-window the Budew pick must win the TO_ACTIVE select
                        # (wall to Active is the core of OA-LOCK).
                        if in_window and dominate_path:
                            return dominate_path + 2.0
                        return dominate_mid
                except Exception:
                    pass

    return 0.0
