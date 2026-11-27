import io
import json
import unittest
from unittest.mock import patch

from host.tab_tether import (
    ACCESSIBLE_ROOT,
    HEADER,
    MAX_MESSAGE_BYTES,
    AccessibilitySession,
    Atspi,
    CommandDecoder,
    InvalidMessage,
    Pairings,
    Selection,
    UncertainTree,
    write_event,
)


FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"
BUS = ":1.7"
FRAME = (BUS, "/frame")
TERMINAL = (BUS, "/terminal")
FOCUSED = Selection(FRAME, TERMINAL, True)


def native_frame(kind, pairing_id):
    payload = json.dumps({
        "type": kind,
        "id": pairing_id,
    }).encode("utf-8")
    return HEADER.pack(len(payload)) + payload


class FramingTests(unittest.TestCase):
    def test_split_header_and_multiple_commands(self):
        arm = native_frame("arm", FIRST)
        forget = native_frame("forget", FIRST)
        decoder = CommandDecoder()

        self.assertEqual(list(decoder.feed(arm[:2])), [])
        self.assertEqual(list(decoder.feed(arm[2:-1])), [])
        self.assertEqual(list(decoder.feed(arm[-1:] + forget)), [
            ("arm", FIRST),
            ("forget", FIRST),
        ])

    def test_oversized_frame_fails_before_waiting_for_its_payload(self):
        header = HEADER.pack(MAX_MESSAGE_BYTES + 1)

        with self.assertRaises(InvalidMessage):
            list(CommandDecoder().feed(header))

    def test_non_uuid_command_is_rejected(self):
        with self.assertRaises(InvalidMessage):
            list(CommandDecoder().feed(native_frame("arm", "not-an-id")))

    def test_events_use_byte_length_and_only_send_the_type_and_id(self):
        stream = io.BytesIO()

        write_event(stream, "selected", FIRST)

        frame = stream.getvalue()
        self.assertEqual(HEADER.unpack_from(frame), (len(frame) - HEADER.size,))
        self.assertEqual(json.loads(frame[HEADER.size:]), {
            "type": "selected",
            "id": FIRST,
        })


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.now = 0
        self.pairings = Pairings(self.emit, clock=lambda: self.now)

    def emit(self, kind, pairing_id):
        self.events.append((kind, pairing_id))

    def test_pairing_requires_current_terminal_focus(self):
        self.pairings.arm(FIRST, 30, None)
        selection = Selection(FRAME, TERMINAL, False)

        self.pairings.observe(selection, {FRAME}, {TERMINAL})

        self.assertEqual(self.events, [])

    def test_existing_focus_does_not_complete_a_new_arm(self):
        self.pairings.arm(FIRST, 30, FOCUSED)

        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})

        self.assertEqual(self.events, [])

    def test_fresh_focus_after_leaving_the_original_terminal_pairs(self):
        self.pairings.arm(FIRST, 30, FOCUSED)
        self.pairings.observe(None, set(), set())

        self.pairings.observe(FOCUSED, {FRAME}, set())

        self.assertEqual(self.events, [("paired", FIRST)])

    def test_focus_on_another_widget_is_not_evidence_for_pairing(self):
        self.pairings.arm(FIRST, 30, None)

        self.pairings.observe(FOCUSED, set(), {(BUS, "/other-widget")})

        self.assertEqual(self.events, [])

    def test_pairing_deadline_applies_even_before_timeout_callback(self):
        self.pairings.arm(FIRST, 30, None)
        self.now = 30

        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})

        self.assertEqual(self.events, [("expired", FIRST)])

    def test_pairing_is_selected_once_on_return_even_without_terminal_focus(self):
        self.pairings.arm(FIRST, 30, None)
        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})
        self.pairings.observe(None, set(), set())
        visible = Selection(FRAME, TERMINAL, False)

        self.pairings.observe(visible, {FRAME}, set())
        self.pairings.observe(visible, set(), set())

        self.assertEqual(self.events, [
            ("paired", FIRST),
            ("selected", FIRST),
        ])

    def test_rebinding_notifies_old_then_new_id(self):
        self.pairings.arm(FIRST, 30, None)
        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})
        self.pairings.observe(None, set(), set())
        self.pairings.arm(SECOND, 30, None)

        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})

        self.assertEqual(self.events, [
            ("paired", FIRST),
            ("forgotten", FIRST),
            ("paired", SECOND),
        ])

    def test_browser_forget_cancels_a_pending_arm(self):
        self.pairings.arm(FIRST, 30, None)

        self.pairings.forget(FIRST)
        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})

        self.assertEqual(self.events, [("forgotten", FIRST)])

    def test_disappearing_terminal_cannot_select_its_old_pairing(self):
        self.pairings.arm(FIRST, 30, None)
        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})

        self.pairings.remove_terminal(TERMINAL)
        self.pairings.observe(FOCUSED, {FRAME}, {TERMINAL})

        self.assertEqual(self.events, [
            ("paired", FIRST),
            ("forgotten", FIRST),
        ])


class AccessibleTree(AccessibilitySession):
    def __init__(self, roles, children, states):
        self.tree_roles = roles
        self.tree_children = children
        self.tree_states = states

    def role(self, node):
        return self.tree_roles[node]

    def children(self, node):
        return self.tree_children[node]

    def states(self, node):
        return self.tree_states[node]


def showing():
    return [(1 << Atspi.StateType.VISIBLE) | (1 << Atspi.StateType.SHOWING), 0]


class TreeTests(unittest.TestCase):
    def test_two_active_ptyxis_frames_are_ambiguous(self):
        second_frame = (BUS, "/second-frame")
        active = showing()
        active[0] |= 1 << Atspi.StateType.ACTIVE
        tree = AccessibleTree(
            roles={
                FRAME: Atspi.Role.FRAME,
                second_frame: Atspi.Role.FRAME,
            },
            children={
                (BUS, ACCESSIBLE_ROOT): [FRAME, second_frame],
            },
            states={
                FRAME: active,
                second_frame: active,
            },
        )
        tree.applications = {
            BUS: (42, []),
        }

        with patch("host.tab_tether.is_ptyxis", return_value=True):
            self.assertIsNone(tree.active_frame())

    def test_two_showing_terminals_are_ambiguous(self):
        second_terminal = (BUS, "/second-terminal")
        tree = AccessibleTree(
            roles={
                FRAME: Atspi.Role.FRAME,
                TERMINAL: Atspi.Role.TERMINAL,
                second_terminal: Atspi.Role.TERMINAL,
            },
            children={
                FRAME: [TERMINAL, second_terminal],
            },
            states={
                FRAME: showing(),
                TERMINAL: showing(),
                second_terminal: showing(),
            },
        )

        self.assertIsNone(tree.visible_terminal(FRAME))

    def test_terminal_under_hidden_ancestor_is_not_showing(self):
        hidden_panel = (BUS, "/hidden-panel")
        hidden_terminal = (BUS, "/hidden-terminal")
        tree = AccessibleTree(
            roles={
                FRAME: Atspi.Role.FRAME,
                TERMINAL: Atspi.Role.TERMINAL,
                hidden_panel: Atspi.Role.PANEL,
                hidden_terminal: Atspi.Role.TERMINAL,
            },
            children={
                FRAME: [TERMINAL, hidden_panel],
                hidden_panel: [hidden_terminal],
            },
            states={
                FRAME: showing(),
                TERMINAL: showing(),
                hidden_panel: [0, 0],
                hidden_terminal: showing(),
            },
        )

        self.assertEqual(tree.visible_terminal(FRAME), TERMINAL)

    def test_foreign_bus_reference_is_not_inspected(self):
        tree = AccessibleTree(
            roles={
                FRAME: Atspi.Role.FRAME,
            },
            children={
                FRAME: [(":1.8", "/untrusted")],
            },
            states={},
        )

        with self.assertRaises(UncertainTree):
            tree.visible_terminal(FRAME)
