#!/usr/bin/env python3

from dataclasses import dataclass
from functools import cache, cached_property, partial
import itertools
import sys
import json
import subprocess
import argparse
from typing import (
    Any,
    Mapping,
    NotRequired,
    Protocol,
    Sequence,
    Type,
    TypeVar,
    TypedDict,
)

OutType = TypeVar("OutType")


def niri_json_from_msg_raw(*msg: str, type: Type[OutType] = list) -> OutType:
    proc = subprocess.Popen(["niri", "msg", "--json", *msg], stdout=subprocess.PIPE)
    proc.wait()
    if proc.returncode != 0:
        raise Exception(f"niri returned non-zero status {proc.returncode}")

    if not proc.stdout:
        raise Exception("No output from niri")

    output = json.loads(proc.stdout.read())

    return output


@cache
def _niri_json_from_msg_cached(*msg: str, type: Type[OutType] = list) -> OutType:
    return niri_json_from_msg_raw(*msg, type=type)


def niri_json_from_msg(*msg: str, type: Type[OutType] = list) -> OutType:
    """Simple wrapper, just to avoid typing information being lost with cache"""
    return _niri_json_from_msg_cached(*msg, type=type)


class WindowEntryDict(TypedDict):
    id: int
    title: str
    app_id: str
    workspace_id: int
    is_focused: bool
    is_floating: bool


class WorkspaceEntryDict(TypedDict):
    id: int
    idx: int
    name: NotRequired[str]
    output: NotRequired[str]
    is_active: bool
    is_focused: bool
    active_window_id: int


@dataclass
class NiriState:
    windows: Sequence[WindowEntryDict]
    workspaces: Sequence[WorkspaceEntryDict]

    @classmethod
    def new(cls):
        windows = niri_json_from_msg("windows", type=Sequence[WindowEntryDict])
        workspaces = niri_json_from_msg(
            "workspaces", type=Sequence[WorkspaceEntryDict]
        )

        return cls(windows=windows, workspaces=workspaces)

    @cached_property
    def focused_window(self) -> WindowEntryDict | None:
        return next((w for w in self.windows if w["is_focused"]), None)

    @cached_property
    def focused_workspace(self) -> WorkspaceEntryDict | None:
        return next((w for w in self.workspaces if w["is_focused"]), None)

    @cached_property
    def active_workspaces(self) -> Sequence[WorkspaceEntryDict]:
        return [w for w in self.workspaces if w["is_active"]]

    @cached_property
    def focused_output(self) -> str | None:
        if focused := self.focused_workspace:
            return focused.get("output")


class Matcher(Protocol):
    def matches(self, item: Mapping[Any, Any]) -> bool: ...


class DictKeyMatcher:
    def __init__(self, key, value):
        self.key = key
        self.value = value

    def matches(self, item: Mapping) -> bool:
        return item.get(self.key) == self.value


class DictKeyAnyMatcher:
    def __init__(self, key, *values):
        self.key = key
        self.values = values

    def matches(self, item: Mapping) -> bool:
        return item.get(self.key) in self.values


def _filter_item_matches(filters: Sequence[Matcher], item: Mapping):
    return all(rule.matches(item) for rule in filters)


FilterItem = TypeVar("FilterItem", bound=Mapping)


def filter_by_dict(d: Sequence[FilterItem], filters: Sequence[Matcher]):
    filter_fn = partial(_filter_item_matches, filters)
    return filter(filter_fn, d)


MIN = -sys.maxsize - 1
MAX = sys.maxsize

class WindowHandler:
    def __init__(self, niri: NiriState, select_focused: bool, window_filters: Sequence[Matcher] | None):
        self.niri = niri
        self.workspace_id_map = {w["id"]: w for w in self.niri.workspaces}
        windows = self.niri.windows

        if window_filters:
            windows = filter_by_dict(windows, window_filters)

        # Sort windows by workspace, keeping the
        def sort_key(w: WindowEntryDict):
            workspace = self.workspace_id_map[w["workspace_id"]]
            output = workspace.get("output")

            # When we ask to select the focused window, keep it on top. Otherwise, keep it at the bottom
            if select_focused:
                window_prio = MIN if w["is_focused"] else 0
            else:
                window_prio = 0 if w["is_focused"] else MIN

            if workspace["is_focused"]:
                workspace_prio = MIN
            elif workspace["is_active"]:
                workspace_prio = MIN + 1
            else:
                workspace_prio = 0

            output_prio = MIN if output == niri.focused_output else 0

            return workspace_prio, window_prio, output_prio, output, workspace["idx"], w["id"]

        self.windows = list(sorted(windows, key=sort_key))
        self.multiple_workspaces = (
            len(set(win["workspace_id"] for win in self.windows)) > 1
        )
        self.multiple_outputs = (
            len(
                set(
                    self.workspace_id_map[win["workspace_id"]].get("output")
                    for win in self.windows
                )
            )
            > 1
        )

        self.dmenu_prompt = "Window"
        self.dmenu_entries = [self._entry_to_dmenu(w) for w in self.windows]
        self.dmenu_selected = (
            self._entry_to_dmenu(self.niri.focused_window)
            if select_focused and self.niri.focused_window
            else None
        )

    def _entry_to_dmenu(self, entry: WindowEntryDict) -> str:
        entry_dmenu = entry["title"]
        if entry["is_focused"]:
            entry_dmenu = f"* {entry_dmenu}"

        if self.multiple_workspaces and (
            workspace := self.workspace_id_map.get(entry["workspace_id"])
        ):
            workspace_name = workspace.get("name") or str(workspace["idx"])
            if self.multiple_outputs and (output := workspace.get("output")):
                workspace_name += f" / {output}"
            entry_dmenu += f" (@{workspace_name})"

        return entry_dmenu

    def select(self, idx: int):
        entry = self.windows[idx]
        wid = str(entry["id"])
        subprocess.run(["niri", "msg", "action", "focus-window", "--id", wid])


class WorkspaceHandler:
    def __init__(self, niri: NiriState, select_focused: bool):
        self.niri = niri
        self.window_id_map = {w["id"]: w for w in self.niri.windows}

        workspaces = self.niri.workspaces

        def sort_key(w: WorkspaceEntryDict):
            if w["is_focused"]:
                focus_prio = -2 if select_focused else MAX
            elif w["is_active"]:
                focus_prio = -1
            else:
                focus_prio = 0

            output_prio = -1 if w.get("output") == self.niri.focused_output else 0

            return focus_prio, output_prio, w.get("output"), w["idx"]

        self.workspaces = list(sorted(workspaces, key=sort_key))
        self.multiple_outputs = len(set(w.get("output") for w in self.workspaces)) > 1

        self.dmenu_prompt = "Workspace"
        self.dmenu_entries = [self._entry_to_dmenu(w) for w in self.workspaces]
        self.dmenu_selected = (
            self._entry_to_dmenu(self.niri.focused_workspace)
            if select_focused and self.niri.focused_workspace
            else None
        )

    def _entry_to_dmenu(self, entry: WorkspaceEntryDict):
        entry_name = entry.get("name") or entry["idx"]
        entry_dmenu = f"@{entry_name}"
        if entry["is_focused"]:
            entry_dmenu = f"* {entry_dmenu}"

        if self.multiple_outputs and (output := entry.get("output")):
            entry_dmenu = f"{entry_dmenu} / {output}"

        focused_window = self.window_id_map.get(
            entry["active_window_id"], {"title": "(empty)"}
        )
        entry_dmenu = f"{entry_dmenu} -- {focused_window['title']}"

        return entry_dmenu

    def select(self, idx: int):
        entry = self.workspaces[idx]
        if output := entry.get("output"):
            subprocess.run(["niri", "msg", "action", "focus-monitor", output])
        subprocess.run(["niri", "msg", "action", "focus-workspace", str(entry["idx"])])


def _parse_arg_as_json_dict(arg):
    try:
        parsed = json.loads(arg)
        return parsed if isinstance(parsed, Mapping) else None
    except ValueError:
        return None

def main():
    parser = argparse.ArgumentParser(description="Niri Fuzzel Selector")

    parser.add_argument(
        "--width", "-w", action="store", type=int, default=80, help="Width of the menu"
    )

    parser.add_argument(
        "--select-focused", action="store_true", help="Select the focused item by default"
    )

    parser.add_argument(
        "--prompt", action="store", help="Prompt to display in the dmenu", required=False
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--windows", action="store_true", help="Selects Windows")
    group.add_argument("--workspaces", action="store_true", help="Selects Workspaces")

    group_win = parser.add_argument_group("Windows")
    group_win.add_argument(
        "--app-id",
        action="store",
        help="Filter windows by app id. A value of @focused uses the app_id of the focused app",
        required=False,
    )
    group_win.add_argument(
        "--window-matching",
        help="Filter windows by a json dict of key-value pairs",
        required=False
    )
    group_win.add_argument(
        "--workspace",
        action="store",
        help="""Filter windows by workspace. Must be a single entry json dict
        containing a valid key for a window description and its expected value
        -- e.g. `{"name": "workspace name"}`
        """,
        required=False,
    )

    group_win = parser.add_argument_group("Windows")
    args, fuzzel_args = parser.parse_known_args()

    niri = NiriState.new()

    if args.windows:
        workspace_matchers = []
        window_filters = []

        match args.app_id:
            case None:
                pass
            case "@focused":
                if niri.focused_window:
                    window_filters.append(
                        DictKeyMatcher("app_id", niri.focused_window["app_id"])
                    )
                else:
                    niri=NiriState(windows=[], workspaces=[])
            case str():
                window_filters.append(DictKeyMatcher("app_id", args.app_id))

        match args.window_matching:
            case None:
                pass
            case str() if (window_matchers_arg := _parse_arg_as_json_dict(args.window_matching)):
                window_filters += [
                    DictKeyMatcher(k, v) for k, v in window_matchers_arg.items()
                ]
            case _:
                print("Invalid match rule for window", file=sys.stderr)
                sys.exit(1)

        match args.workspace:
            case None:
                pass
            case "@focused":
                workspace_matchers.append(DictKeyMatcher("is_focused", True))
            case "@active":
                workspace_matchers.append(DictKeyMatcher("is_active", True))
            case "@output" if (output := niri.focused_output):
                workspace_matchers.append(DictKeyAnyMatcher("output", output))
            case str() if (workspace_matchers_arg := _parse_arg_as_json_dict(args.workspace)):
                # Any json string such as {"name": "workspace name"}
                workspace_matchers += [
                    DictKeyMatcher(k, v) for k, v in workspace_matchers_arg.items()
                ]
            case _:
                print("Invalid match rule for workspace", file=sys.stderr)
                sys.exit(1)

        if workspace_matchers:
            filtered_workspaces = filter_by_dict(niri.workspaces, workspace_matchers)
            _ids = {w["id"] for w in filtered_workspaces}

            if not _ids:
                print("Could not found workspaces by provided rules", file=sys.stderr)
                sys.exit(1)

            window_filters.append(DictKeyAnyMatcher("workspace_id", *_ids))

        handler = WindowHandler(niri, args.select_focused, window_filters=window_filters)
    elif args.workspaces:
        handler = WorkspaceHandler(niri, args.select_focused)
    else:
        print("Must provide either --windows or --workspaces")
        sys.exit(1)

    prompt = args.prompt or handler.dmenu_prompt

    cmd = [
        "fuzzel",
        "--dmenu",
        "--index",
        "--prompt",
        f"{prompt}: ",
    ]

    if not any(arg.startswith("--match-mode") for arg in fuzzel_args):
        cmd.append("--match-mode=fuzzy")

    if not any(arg.startswith("--width") or arg == "-w" or arg.startswith("-w=") for arg in fuzzel_args):
        cmd.append(f"--width={args.width}")

    if handler.dmenu_selected:
        cmd += ["--select", handler.dmenu_selected]

    if fuzzel_args:
        cmd += fuzzel_args[1:]  # drop `--`

    fuzzel = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    out, err = fuzzel.communicate(input="\n".join(handler.dmenu_entries).encode("utf-8"))

    if fuzzel.returncode != 0:
        out_str = out.decode("utf-8")
        err_str = (err or b"").decode("utf-8")
        if out_str or err_str:
            print(f"Error: fuzzel returned non-zero status code: {fuzzel.returncode}")
            print(f"Fuzzel output:\n{out_str}")
            print(err_str, file=sys.stderr)

        sys.exit(2)

    selected_index = int(out.decode("utf-8").strip())

    handler.select(selected_index)


if __name__ == "__main__":
    main()
