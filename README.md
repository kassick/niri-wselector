# Niri Window Selector Hack

Quick hack to use [`fuzzel`](https://codeberg.org/dnkl/fuzzel) to select windows and workspaces in [niri](https://github.com/YaLTeR/niri).

## Installation

Run `pip install git+https://github.com/kassick/niri-wselector.git`, or copy the `niri_wselector/__main__.py` script somewhere in your `$PATH`.

Then you can update your niri bindings such as below:

```
    Mod+W hotkey-overlay-title="Windows" { spawn "niri-wselector" "--windows" "-w" "100" ; }
    Mod+Shift+W hotkey-overlay-title="Application Windows" { spawn "niri-wselector" "--windows" "--app-id" "@focused" "-w" "100" ; }
    Mod+Ctrl+W hotkey-overlay-title="Windows in current output" { spawn "niri-wselector" "--windows" "--workspace" "@output" "-w" "100" ; }
    Mod+Alt+W hotkey-overlay-title="Windows on current workspace" { spawn "niri-wselector" "--windows" "--workspace" "@focused" "-w" "100" ; }
    Mod+Alt+Shift+W hotkey-overlay-title="Windows in active workspaces" { spawn "niri-wselector" "--windows" "--workspace" "@active" "-w" "100" ; }
    Mod+S hotkey-overlay-title="Workspaces" { spawn "niri-wselector" "--workspaces" "-w" "100" ; }
```

## Usage

Run the script with either the `--windows` or `--workspaces` option to select _windows_ or _workspaces_.

### Window Filtering Options

When running the script with `--windows`, the command line exposes some filtering options you can use:

- `--app-id`: provide an specific app_id (e.g. `org.mozilla.firefox`) to show
  only those application windows. A special value of `@focused` will use the
  `app_id` of the currently focused window -- use it to filter by applications
  of the current application.

-   `--window-matching`: Filters windows whose properties match the ones provided in a json dict.

    For example, you can use `--window-matching '{"app_id": "org.mozilla.firefox"}'`
    to achieve the same as with `--app-id org.mozilla.firefox`. Or you can try fintering
    by floating windows: `--window-matching '{"is_floating": true}'`.

    Any value present in the window object returned by `niri msg --json windows` can be used here.

-   `--workspace`: Only shows windows that appear in workspaces matching the rules.

    The value can be a JSON dictionary to match against the available workspaces -- e.g.
    `--workspace '{"idx": 1}'` will only show windows of workspaces at Index 1.

    This parameters accepts a few special values:
    - `--workspace @focused` will show windows of the currently focused workspace
    - `--workspace @active` shows windows of all active workspaces -- handy if
      you have multiple monitors.
    - `--workspace @output` shows windows of all workspaces of the currently
      focused output.
