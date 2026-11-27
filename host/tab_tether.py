#!/usr/bin/python3
import json
import os
import struct
import sys
import time
import uuid
from dataclasses import dataclass
from importlib import import_module

import gi
from gi.repository import Gio, GLib

gi.require_version("Atspi", "2.0")
Atspi = import_module("gi.repository.Atspi")


HEADER = struct.Struct("=I")
MAX_MESSAGE_BYTES = 4096
PAIRING_SECONDS = 30
PTYXIS_EXECUTABLE = "/usr/bin/ptyxis"
MAX_TREE_NODES = 512
BUS_SERVICE = "org.a11y.Bus"
BUS_PATH = "/org/a11y/bus"
DBUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
REGISTRY = "org.a11y.atspi.Registry"
REGISTRY_PATH = "/org/a11y/atspi/registry"
ACCESSIBLE_ROOT = "/org/a11y/atspi/accessible/root"
ACCESSIBLE = "org.a11y.atspi.Accessible"
OBJECT_EVENTS = "org.a11y.atspi.Event.Object"
CACHE = "org.a11y.atspi.Cache"


class InvalidMessage(Exception):
    pass


class UncertainTree(Exception):
    pass


class CommandDecoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        while len(self.buffer) >= HEADER.size:
            (size,) = HEADER.unpack_from(self.buffer)
            if not 0 < size <= MAX_MESSAGE_BYTES:
                raise InvalidMessage

            end = HEADER.size + size
            if len(self.buffer) < end:
                return

            payload = self.buffer[HEADER.size:end]
            del self.buffer[:end]
            yield self.decode(payload)

    def decode(self, payload):
        try:
            message = json.loads(payload.decode("utf-8"))
            if type(message) is not dict or message.keys() != {"type", "id"}:
                raise InvalidMessage

            kind = message["type"]
            pairing_id = message["id"]
            if kind not in ("arm", "forget") or not isinstance(pairing_id, str):
                raise InvalidMessage
            if len(pairing_id) != 36 or str(uuid.UUID(pairing_id)) != pairing_id:
                raise InvalidMessage
        except (ValueError, RecursionError) as error:
            raise InvalidMessage from error

        return kind, pairing_id


def write_event(stream, kind, pairing_id):
    payload = json.dumps({
        "type": kind,
        "id": pairing_id,
    }).encode("utf-8")
    stream.write(HEADER.pack(len(payload)) + payload)
    stream.flush()


@dataclass(frozen=True)
class Selection:
    frame: tuple[str, str]
    terminal: tuple[str, str]
    focused: bool


@dataclass
class PendingPairing:
    id: str
    deadline: float
    previous_focus: Selection | None
    needs_focus_baseline: bool


class Pairings:
    def __init__(self, emit, clock=time.monotonic):
        self.emit = emit
        self.clock = clock
        self.pending = None
        self.bound = {}
        self.last_terminal = None

    def arm(self, pairing_id, deadline, selection, *, needs_focus_baseline=False):
        if self.pending is not None:
            self.forget(self.pending.id)

        previous_focus = None
        if selection is not None and selection.focused:
            previous_focus = selection

        self.pending = PendingPairing(pairing_id, deadline, previous_focus, needs_focus_baseline)
        self.expire()

    def has_id(self, pairing_id):
        if self.pending is not None and self.pending.id == pairing_id:
            return True

        return pairing_id in self.bound.values()

    def forget(self, pairing_id):
        if self.pending is not None and self.pending.id == pairing_id:
            self.pending = None
            self.emit("forgotten", pairing_id)
            return

        for terminal, bound_id in self.bound.items():
            if bound_id == pairing_id:
                self.remove_terminal(terminal)
                return

    def remove_terminal(self, terminal):
        pairing_id = self.bound.pop(terminal, None)
        if self.last_terminal == terminal:
            self.last_terminal = None
        if pairing_id is not None:
            self.emit("forgotten", pairing_id)

    def remove_application(self, bus_name):
        for terminal in tuple(self.bound):
            if terminal[0] == bus_name:
                self.remove_terminal(terminal)

    def expire(self):
        if self.pending is None or self.clock() < self.pending.deadline:
            return

        pairing_id = self.pending.id
        self.pending = None
        self.emit("expired", pairing_id)

    def observe(self, selection, active_frames, focused_terminals):
        self.expire()
        if self.pending is not None and self.pending.needs_focus_baseline:
            self.pending.needs_focus_baseline = False
            self.pending.previous_focus = selection

        if selection is None:
            self.last_terminal = None
            if self.pending is not None:
                self.pending.previous_focus = None
            return

        terminal = selection.terminal
        previous_terminal = self.last_terminal
        self.last_terminal = terminal
        if self.pair_if_fresh(selection, active_frames, focused_terminals):
            return

        pairing_id = self.bound.get(terminal)
        if terminal != previous_terminal and pairing_id is not None:
            self.emit("selected", pairing_id)

    def pair_if_fresh(self, selection, active_frames, focused_terminals):
        if self.pending is None or self.pending.previous_focus == selection:
            return False

        self.pending.previous_focus = None
        fresh_focus = selection.terminal in focused_terminals
        fresh_activation = selection.frame in active_frames
        if not selection.focused or not (fresh_focus or fresh_activation):
            return False

        pairing_id = self.pending.id
        self.pending = None
        replaced_id = self.bound.get(selection.terminal)
        if replaced_id is not None:
            self.emit("forgotten", replaced_id)

        self.bound[selection.terminal] = pairing_id
        self.emit("paired", pairing_id)
        return True


def call(bus, destination, path, interface, method, reply_type, arguments=None):
    return bus.call_sync(
        destination,
        path,
        interface,
        method,
        arguments,
        GLib.VariantType.new(reply_type),
        Gio.DBusCallFlags.NONE,
        500,
        None,
    )


def bus_lookup(bus, method, name, reply_type):
    (value,) = call(
        bus, DBUS, DBUS_PATH, DBUS, method, reply_type, GLib.Variant("(s)", (name,))
    ).unpack()
    return value


def has_state(states, state):
    word, bit = divmod(int(state), 32)
    return bool(states[word] & (1 << bit))


def is_showing(states):
    return (
        has_state(states, Atspi.StateType.VISIBLE)
        and has_state(states, Atspi.StateType.SHOWING)
        and not has_state(states, Atspi.StateType.DEFUNCT)
    )


def is_ptyxis(pid):
    try:
        return os.path.samefile(f"/proc/{pid}/exe", PTYXIS_EXECUTABLE)
    except OSError:
        return False


class AccessibilitySession:
    def __init__(self, host):
        self.host = host
        self.applications = {}
        self.session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        (address,) = call(self.session_bus, BUS_SERVICE, BUS_PATH, BUS_SERVICE, "GetAddress", "(s)").unpack()
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        self.bus = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
        self.bus.set_exit_on_close(False)
        self.bus.connect("closed", self.bus_closed)
        arguments = GLib.Variant("(su)", (REGISTRY, 0))
        call(self.bus, DBUS, DBUS_PATH, DBUS, "StartServiceByName", "(u)", arguments)
        self.registry_owner = self.watch_service(self.bus, REGISTRY)
        self.watch_service(self.session_bus, BUS_SERVICE)
        registry_root = (self.registry_owner, ACCESSIBLE_ROOT)
        self.subscribe(self.registry_owner, OBJECT_EVENTS, "ChildrenChanged", self.desktop_changed, path=ACCESSIBLE_ROOT)
        for bus_name, path in self.children(registry_root):
            self.add_application(bus_name, path)

    def watch_service(self, bus, name):
        bus.signal_subscribe(
            DBUS, DBUS, "NameOwnerChanged", DBUS_PATH, name,
            Gio.DBusSignalFlags.NONE, self.service_changed,
        )
        return bus_lookup(bus, "GetNameOwner", name, "(s)")

    def service_changed(self, _bus, _sender, _path, _interface, _signal, parameters):
        _name, old_owner, _new_owner = parameters.unpack()
        if old_owner:
            self.host.stop()

    def bus_closed(self, *_args):
        self.host.stop()

    def subscribe(self, sender, interface, signal, callback, path=None, detail=None):
        return self.bus.signal_subscribe(
            sender, interface, signal, path, detail, Gio.DBusSignalFlags.NONE, callback,
        )

    def desktop_changed(self, _bus, _sender, _path, _interface, _signal, parameters):
        if parameters.get_type_string() != "(siiva{sv})":
            return

        operation = parameters.get_child_value(0).get_string()
        reference = parameters.get_child_value(3).get_variant()
        if reference.get_type_string() != "(so)":
            return

        bus_name, path = reference.unpack()
        if operation == "add":
            self.add_application(bus_name, path)
        elif operation == "remove":
            self.remove_application(bus_name)

    def add_application(self, bus_name, path):
        if not bus_name.startswith(":") or path != ACCESSIBLE_ROOT or bus_name in self.applications:
            return

        try:
            pid = bus_lookup(self.bus, "GetConnectionUnixProcessID", bus_name, "(u)")
            if not is_ptyxis(pid):
                return

            # GTK emits state and hierarchy events only while an AT is listening.
            for event_type in ("object:state-changed", "object:children-changed"):
                args = GLib.Variant("(sass)", (event_type, [], bus_name))
                call(self.bus, self.registry_owner, REGISTRY_PATH, REGISTRY, "RegisterEvent", "()", args)
        except GLib.Error:
            return

        subscriptions = [
            self.subscribe(DBUS, DBUS, "NameOwnerChanged", self.application_owner_changed, path=DBUS_PATH, detail=bus_name),
            self.subscribe(bus_name, OBJECT_EVENTS, "ChildrenChanged", self.application_activity),
            self.subscribe(bus_name, CACHE, "RemoveAccessible", self.accessible_removed),
        ]
        for state in ("active", "focused", "visible", "showing", "selected", "defunct"):
            subscriptions.append(self.subscribe(bus_name, OBJECT_EVENTS, "StateChanged", self.state_changed, detail=state))

        self.applications[bus_name] = (pid, subscriptions)

    def application_owner_changed(self, _bus, _sender, _path, _interface, _signal, parameters):
        name, _old_owner, new_owner = parameters.unpack()
        if not new_owner:
            self.remove_application(name)

    def remove_application(self, bus_name):
        application = self.applications.pop(bus_name, None)
        if application is None:
            return

        _pid, subscriptions = application
        for subscription in subscriptions:
            self.bus.signal_unsubscribe(subscription)

        self.host.application_removed(bus_name)

    def application_activity(self, _bus, sender, _path, _interface, _signal, _parameters):
        if sender in self.applications:
            self.host.schedule_observation()

    def state_changed(self, _bus, sender, path, _interface, _signal, parameters):
        if sender not in self.applications or parameters.get_type_string() != "(siiva{sv})":
            return

        state = parameters.get_child_value(0).get_string()
        enabled = parameters.get_child_value(1).get_int32() == 1
        self.host.state_changed((sender, path), state, enabled)

    def accessible_removed(self, _bus, sender, _path, _interface, _signal, parameters):
        if sender not in self.applications or parameters.get_type_string() != "((so))":
            return

        (reference,) = parameters.unpack()
        if reference[0] == sender:
            self.host.terminal_removed(reference)

    def query_accessible(self, reference, method, reply_type):
        bus_name, path = reference
        (value,) = call(self.bus, bus_name, path, ACCESSIBLE, method, reply_type).unpack()
        return value

    def children(self, reference):
        return self.query_accessible(reference, "GetChildren", "(a(so))")

    def role(self, reference):
        return self.query_accessible(reference, "GetRole", "(u)")

    def states(self, reference):
        states = self.query_accessible(reference, "GetState", "(au)")
        if len(states) != 2:
            raise UncertainTree

        return states

    def application_children(self, reference):
        children = self.children(reference)
        if any(child[0] != reference[0] for child in children):
            raise UncertainTree

        return children

    def active_frame(self):
        active = None
        for bus_name, (pid, _subscriptions) in self.applications.items():
            if not is_ptyxis(pid):
                raise UncertainTree

            for frame in self.application_children((bus_name, ACCESSIBLE_ROOT)):
                states = self.states(frame)
                if not has_state(states, Atspi.StateType.ACTIVE):
                    continue
                if active is not None or self.role(frame) != Atspi.Role.FRAME or not is_showing(states):
                    return None

                active = frame

        return active

    def showing_ancestors(self, node, parents):
        while node is not None:
            if not is_showing(self.states(node)):
                return False

            node = parents[node]

        return True

    def visible_terminal(self, frame):
        frontier = [frame]
        parents = {frame: None}
        visible = None
        while frontier:
            node = frontier.pop()
            if self.role(node) == Atspi.Role.TERMINAL:
                if self.showing_ancestors(node, parents):
                    if visible is not None:
                        return None

                    visible = node
                continue

            for child in self.application_children(node):
                if child in parents or len(parents) >= MAX_TREE_NODES:
                    raise UncertainTree

                parents[child] = node
                frontier.append(child)

        return visible

    def selection(self):
        frame = self.active_frame()
        if frame is None:
            return None

        terminal = self.visible_terminal(frame)
        if terminal is None or self.active_frame() != frame:
            return None

        terminal_states = self.states(terminal)
        if not is_showing(terminal_states):
            return None

        return Selection(frame, terminal, has_state(terminal_states, Atspi.StateType.FOCUSED))


class NativeHost:
    def __init__(self):
        self.loop = GLib.MainLoop()
        self.decoder = CommandDecoder()
        self.pairings = Pairings(self.emit)
        self.active_frames = set()
        self.focused_terminals = set()
        self.observation_source = None
        self.expiry_source = None
        self.accessibility = AccessibilitySession(self)

    def stop(self):
        self.loop.quit()

    def emit(self, kind, pairing_id):
        try:
            write_event(sys.stdout.buffer, kind, pairing_id)
        except OSError:
            self.stop()

    def run(self):
        fd = sys.stdin.fileno()
        watch = GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT, watch, self.read_input, fd)
        self.loop.run()

    def read_input(self, _source, _condition, fd):
        try:
            data = os.read(fd, MAX_MESSAGE_BYTES)
            if data:
                for kind, pairing_id in self.decoder.feed(data):
                    self.handle_command(kind, pairing_id)
                return GLib.SOURCE_CONTINUE
        except (InvalidMessage, OSError):
            print("tab-tether: invalid or unreadable native message", file=sys.stderr)

        self.stop()
        return GLib.SOURCE_REMOVE

    def handle_command(self, kind, pairing_id):
        self.pairings.expire()
        if kind == "forget":
            self.pairings.forget(pairing_id)
            return
        if self.pairings.has_id(pairing_id):
            return

        self.active_frames.clear()
        self.focused_terminals.clear()
        deadline = time.monotonic() + PAIRING_SECONDS
        needs_focus_baseline = False
        try:
            # Do not consume focus that was already present when Firefox armed.
            selection = self.accessibility.selection()
        except (GLib.Error, UncertainTree):
            selection = None
            needs_focus_baseline = True

        self.pairings.arm(pairing_id, deadline, selection, needs_focus_baseline=needs_focus_baseline)
        if self.expiry_source is not None:
            GLib.source_remove(self.expiry_source)

        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000) + 1)
        self.expiry_source = GLib.timeout_add(remaining_ms, self.expire)

    def expire(self):
        self.expiry_source = None
        self.pairings.expire()
        return GLib.SOURCE_REMOVE

    def schedule_observation(self):
        if self.pairings.pending is None and not self.pairings.bound:
            return
        if self.observation_source is not None:
            return

        # GTK focus, activation, and tree changes arrive as separate signals.
        self.observation_source = GLib.timeout_add(50, self.observe)

    def state_changed(self, reference, state, enabled):
        if state == "defunct" and enabled:
            self.terminal_removed(reference)
            return

        if self.pairings.pending is not None:
            if state == "active":
                self.record_state(self.active_frames, reference, enabled)
            elif state == "focused":
                self.record_state(self.focused_terminals, reference, enabled)

        self.schedule_observation()

    def record_state(self, references, reference, enabled):
        if enabled:
            references.add(reference)
        else:
            references.discard(reference)

    def terminal_removed(self, reference):
        self.active_frames.discard(reference)
        self.focused_terminals.discard(reference)
        self.pairings.remove_terminal(reference)
        self.schedule_observation()

    def application_removed(self, bus_name):
        self.pairings.remove_application(bus_name)
        self.active_frames.clear()
        self.focused_terminals.clear()
        self.schedule_observation()

    def observe(self):
        self.observation_source = None
        self.pairings.expire()
        try:
            if self.pairings.pending is not None or self.pairings.bound:
                selection = self.accessibility.selection()
                self.pairings.observe(selection, self.active_frames, self.focused_terminals)
        except (GLib.Error, UncertainTree):
            # A disappearing or changing object is not evidence of a selection.
            pass
        finally:
            self.active_frames.clear()
            self.focused_terminals.clear()

        return GLib.SOURCE_REMOVE


def main():
    try:
        NativeHost().run()
    except GLib.Error:
        print("tab-tether: cannot connect to the accessibility session", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
