"""OPENING simulator tests — shuffled deck, unlimited turns until Goal."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent" / "skills" / "piloting_starmie_froslass" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from arena.deck import load_deck_csv  # noqa: E402
from opening_cards import (  # noqa: E402
    BUDEW,
    FAN_ROTOM,
    HILDA,
    MEGA_STARMIE,
    POFFIN,
    STARYU,
    ULTRA_BALL,
    WATER_BASIC,
    is_pad_legal_target,
)
from opening_state import OpeningGameState, Pokemon  # noqa: E402
from opening_validate import assert_legal_simulation, validate_log  # noqa: E402
from setup_planner import classify_archetype, pick_setup_active, pick_setup_bench  # noqa: E402
from simulate_opening import MAX_TURNS, export_batch_log, run_batch, simulate_opening  # noqa: E402

DEFAULT_DECK = load_deck_csv(ROOT / "data" / "decks" / "starmie_froslass.csv")
PHASE0_SEEDS = (42, 43, 45, 47, 48)


def _deck_with_hand(hand7: list[int], rest: list[int] | None = None) -> list[int]:
    prizes = [860, 860, 861, 861, 1030, 860]
    tail = rest if rest is not None else DEFAULT_DECK[13:]
    return prizes + hand7 + tail


class TestSetupArchetypes(unittest.TestCase):
    def test_a2_staryu_rotom(self):
        hand = [STARYU, MEGA_STARMIE, MEGA_STARMIE, 112, 112, 104, FAN_ROTOM]
        self.assertEqual(pick_setup_active(hand), STARYU)
        self.assertEqual(pick_setup_bench(hand, STARYU), FAN_ROTOM)
        self.assertEqual(classify_archetype(STARYU, FAN_ROTOM), "A2")

    def test_s1_staryu_only_bench(self):
        hand = [STARYU, MEGA_STARMIE, HILDA, WATER_BASIC, 112, 104, 174]
        self.assertIsNone(pick_setup_bench([STARYU], STARYU))
        self.assertEqual(classify_archetype(STARYU, None), "S1")


class TestShuffledBatch(unittest.TestCase):
    def test_batch_export_with_turn_limit(self):
        log_path = ROOT / ".agent/skills/piloting_starmie_froslass/logs/test_batch_max5.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        run_batch(10, seed_base=42, verbose_failures=False, export_path=log_path)
        self.assertTrue(log_path.exists())
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("起手手牌", text)
        self.assertIn("My-T1", text)
        self.assertIn(f"回合上限: {MAX_TURNS}", text)


class TestDefaultDeckOrder(unittest.TestCase):
    def test_setup_a2(self):
        st = OpeningGameState.from_ordered_deck(DEFAULT_DECK)
        basics = st.hand_basics()
        self.assertIn(STARYU, basics)
        self.assertIn(FAN_ROTOM, basics)

    def test_shuffled_simulation_is_legal(self):
        st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=42, verbose=False)
        assert_legal_simulation(st)
        self.assertGreaterEqual(st.my_turn_number, 1)


class TestEdgeNoWaterOpening(unittest.TestCase):
    def test_seed42_simulation_is_legal(self):
        st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=42, verbose=False)
        assert_legal_simulation(st)


class TestPhase1Recovery(unittest.TestCase):
    def test_seed42_reaches_legal_goal(self) -> None:
        st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=42, verbose=False)
        assert_legal_simulation(st)
        self.assertTrue(st.opening_complete())
        self.assertLessEqual(st.my_turn_number, 3)

    def test_seed43_meowth_route(self) -> None:
        st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=43, verbose=False)
        assert_legal_simulation(st)
        self.assertTrue(
            any(a.kind == "ABILITY_LAST_DITCH" for a in st.log),
            "expected Meowth Last-Ditch Catch",
        )
        self.assertTrue(st.opening_complete())

    def test_fan_call_only_colorless(self) -> None:
        st = OpeningGameState.from_ordered_deck(
            _deck_with_hand([FAN_ROTOM, 112, HILDA, WATER_BASIC, MEGA_STARMIE, 104, 174])
        )
        st.bench = [Pokemon(FAN_ROTOM, 1)]
        st.deck = [860, 235, 1030, 65, 305, 174]
        st.fan_call()
        picked = [a.detail for a in st.log if a.kind == "ABILITY_FAN_CALL"][0]
        self.assertNotIn("Snorunt", picked)
        self.assertNotIn("Budew", picked)
        self.assertNotIn("Staryu", picked)

    def test_retreat_discards_energy(self) -> None:
        from opening_cards import DARK_BASIC, MEOWTH_EX, MUNKIDORI

        st = OpeningGameState.from_ordered_deck(DEFAULT_DECK)
        st.active = Pokemon(MEOWTH_EX, 0, energies=[DARK_BASIC])
        st.bench = [Pokemon(STARYU, 1)]
        st.retreat_promote_bench(0)
        self.assertEqual(st.bench[-1].energies, [])
        self.assertIn(DARK_BASIC, st.discard)
        self.assertTrue(any(a.kind == "DISCARD" for a in st.log))

    def test_prism_discarded_on_evolve(self) -> None:
        from opening_state import Pokemon

        st = OpeningGameState.from_ordered_deck(DEFAULT_DECK)
        p = Pokemon(STARYU, 1, energies=[16])
        st.hand = [MEGA_STARMIE]
        st.current_turn = 2
        st.my_turn_number = 2
        st.evolve_staryu(p, MEGA_STARMIE)
        self.assertNotIn(16, p.energies)
        self.assertIn(16, st.discard)

    def test_seed45_f1_reaches_goal(self) -> None:
        st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=45, verbose=False)
        assert_legal_simulation(st)
        self.assertTrue(st.opening_complete(), "F1 should Poffin T1 then Ball→1031 T2")

    def test_poffin_prefers_fan_rotom_over_snorunt(self) -> None:
        st = OpeningGameState.from_ordered_deck(
            _deck_with_hand([POFFIN, 112, 112, HILDA, WATER_BASIC, MEGA_STARMIE, 174])
        )
        st.deck = [860, FAN_ROTOM, STARYU] + st.deck
        st.hand = [POFFIN]
        st.poffin_to_bench()
        bench_ids = [p.card_id for p in st.bench]
        self.assertIn(STARYU, bench_ids)
        self.assertIn(FAN_ROTOM, bench_ids)
        self.assertNotIn(860, bench_ids)


class TestPhase0HardRules(unittest.TestCase):
    def test_pad_cannot_search_mega_ex(self) -> None:
        self.assertFalse(is_pad_legal_target(MEGA_STARMIE))

    def test_hilda_never_picks_staryu(self) -> None:
        st = OpeningGameState.from_ordered_deck(
            _deck_with_hand([112, HILDA, WATER_BASIC, MEGA_STARMIE, 104, BUDEW, 174])
        )
        st.hand = [HILDA]
        st.deck = [STARYU, WATER_BASIC, MEGA_STARMIE]
        st.hilda_search(need_evolution=True, need_energy=True)
        picked = [a.detail for a in st.log if "Hilda →" in a.detail][0]
        self.assertNotIn("Staryu", picked)
        self.assertIn("Mega Starmie ex", picked)

    def test_retreat_blocked_without_energy(self) -> None:
        st = OpeningGameState.from_ordered_deck(DEFAULT_DECK)
        st.active = OpeningGameState.from_ordered_deck(DEFAULT_DECK).active
        from opening_cards import MUNKIDORI
        from opening_state import Pokemon

        st.active = Pokemon(MUNKIDORI, 0)
        st.bench = [Pokemon(STARYU, 1)]
        ok = st.retreat_promote_bench(0)
        self.assertFalse(ok)
        self.assertTrue(any("Retreat blocked" in a.detail for a in st.log))

    def test_phase0_seeds_have_no_rule_violations(self) -> None:
        for seed in PHASE0_SEEDS:
            with self.subTest(seed=seed):
                st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=seed, verbose=False)
                violations = validate_log(st)
                self.assertEqual(violations, [], f"seed={seed}: {violations}")

    def test_phase0_seeds_simulation_is_legal(self) -> None:
        for seed in PHASE0_SEEDS:
            with self.subTest(seed=seed):
                st = simulate_opening(DEFAULT_DECK, shuffle=True, seed=seed, verbose=False)
                assert_legal_simulation(st)


class TestEdgeHildaOpening(unittest.TestCase):
    def test_no_hilda_for_g1_missing_staryu_on_field(self) -> None:
        hand = [112, 112, HILDA, WATER_BASIC, MEGA_STARMIE, 104, BUDEW]
        deck = _deck_with_hand(hand, [STARYU, STARYU, MEGA_STARMIE] + DEFAULT_DECK[16:])
        st = simulate_opening(deck, verbose=False)
        hilda_picks = [a.detail for a in st.log if "Hilda →" in a.detail]
        for detail in hilda_picks:
            self.assertNotIn("Staryu", detail)


class TestEdgeEvolveLock(unittest.TestCase):
    def test_g4_setup_staryu_cannot_evolve_t1(self):
        st = OpeningGameState.from_ordered_deck(DEFAULT_DECK)
        st.setup_play_active(STARYU)
        st.current_turn = 1
        st.my_turn_number = 1
        self.assertFalse(st._can_evolve_now(st.active))


if __name__ == "__main__":
    unittest.main()
