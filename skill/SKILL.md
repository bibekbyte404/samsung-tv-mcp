---
name: samsung-tv
description: Control a paired Samsung Tizen TV through the samsung-tv MCP server. Use when the user asks to open an app, press remote keys, mute, change volume, navigate menus, turn the TV on or off, or set up a new Samsung TV.
---

# Samsung TV remote

The `samsung-tv` MCP server exposes the TV as tools. Use them; never hand-roll
websocket or shell code to reach the TV.

## Which TV

Run `tv_list` to see what is paired and which one is the default. Omit `name`
on calls to use the default; pass it to target another TV.

## Everyday requests

| User says | Do |
|---|---|
| open Netflix / YouTube / Prime | `tv_launch_app("netflix")` |
| mute, louder, quieter | `tv_key("MUTE")`, `tv_key("VOLUP", repeat=3)` |
| go home / back | `tv_key("HOME")`, `tv_key("RETURN")` |
| up / down / left / right / ok | `tv_key("UP")` ... `tv_key("ENTER")` |
| pause / play | `tv_key("PAUSE")`, `tv_key("PLAY")` |
| search for X in YouTube | launch app, wait 3 s, `tv_key("UP")` to reach search, `tv_text("X")`, `tv_key("ENTER")` |
| turn on | `tv_power("on")` (Wake-on-LAN, 5-15 s) |
| turn off | ask first, then `tv_power("off")` |
| is it on? | `tv_status()` |

Use `tv_keys("HOME WAIT:1500 DOWN DOWN ENTER")` for sequences. Add
`WAIT:<ms>` between steps that open a new screen.

## Rules

- Confirm before powering off or changing anything inside Settings.
- The API only sends key presses; it cannot read the screen. Walk menus one
  step at a time and ask the user what is highlighted when unsure.
- DNS, privacy toggles and text in Settings must be typed on the TV. The
  macros only get the user to the right page.
- If a call fails with "No TV paired", run `tv_discover` then `tv_pair`.
- If the TV says unauthorized, the user must check Settings > General >
  External Device Manager > Device Connection Manager (Access Notification =
  First Time Only, ClaudeRemote not Denied), then re-pair.

## First-time setup for a new TV

1. TV on, same Wi-Fi as the PC running Claude Desktop.
2. `tv_discover()`; if empty, ask for the IP from the router and use
   `tv_discover(ip_hint=...)`.
3. `tv_pair(ip, name="living-room")`. Say a prompt may appear on the TV.
4. `tv_key("HOME")` to prove it works.

## Menu paths (Tizen 6, 2021 models; other firmware may differ)

- All Settings: HOME, then left to the gear, or `tv_key("MENU")`.
- Network status: Settings > General > Network > Network Status.
- DNS: Network Status > IP Settings > DNS Settings > Enter manually.
  An ad-blocking resolver such as AdGuard DNS (94.140.14.14) removes
  Samsung's home-screen ads and tracking.
- Ad and tracking toggles: Settings > Support > Terms & Privacy.
- Device Connection Manager: Settings > General > External Device Manager.

## What it will not do

- Block YouTube ads. Those are served with the video. TizenTube (via
  TizenBrew) is the only on-TV fix.
- Work from the mobile app when the desktop app on the PC is closed.
