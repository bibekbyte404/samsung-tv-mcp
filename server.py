"""samsung-tv-mcp: control Samsung Tizen TVs (2016+) from Claude via MCP.

Tools: tv_discover, tv_pair, tv_list, tv_status, tv_key, tv_keys, tv_launch_app,
tv_apps, tv_text, tv_power, tv_macro, tv_forget.

Config lives in ~/.samsung-tv/config.json and supports several TVs.
"""

import json
import socket
import time
from pathlib import Path
from typing import Any, Optional

import requests
import urllib3
from mcp.server.fastmcp import FastMCP
from samsungtvws import SamsungTVWS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG_DIR = Path.home() / ".samsung-tv"
CONFIG_PATH = CONFIG_DIR / "config.json"
CLIENT_NAME = "ClaudeRemote"

mcp = FastMCP("samsung-tv")

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def _load() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    return {"default": None, "tvs": {}}


def _save(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _tv_entry(name: Optional[str]) -> tuple[str, dict[str, Any]]:
    cfg = _load()
    if not cfg["tvs"]:
        raise RuntimeError("No TV paired yet. Run tv_discover then tv_pair.")
    key = name or cfg.get("default") or next(iter(cfg["tvs"]))
    if key not in cfg["tvs"]:
        raise RuntimeError(f"Unknown TV '{key}'. Known: {', '.join(cfg['tvs'])}")
    return key, cfg["tvs"][key]


def _connect(name: Optional[str], timeout: int = 10) -> tuple[str, SamsungTVWS]:
    key, tv = _tv_entry(name)
    ws = SamsungTVWS(
        host=tv["ip"],
        port=8002,
        name=CLIENT_NAME,
        token=tv.get("token"),
        timeout=timeout,
    )
    ws.open()
    if ws.token and ws.token != tv.get("token"):
        cfg = _load()
        cfg["tvs"][key]["token"] = ws.token
        _save(cfg)
    return key, ws


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def _info(ip: str, timeout: float = 2.0) -> Optional[dict]:
    try:
        r = requests.get(f"http://{ip}:8001/api/v2/", timeout=timeout)
        d = r.json().get("device", {})
        if d.get("type") != "Samsung SmartTV":
            return None
        return {
            "ip": ip,
            "name": d.get("name"),
            "model": d.get("modelName"),
            "os": d.get("OS"),
            "wifiMac": d.get("wifiMac"),
            "power": d.get("PowerState"),
            "tokenAuth": d.get("TokenAuthSupport"),
        }
    except Exception:
        return None


def _ssdp(timeout: float = 3.0) -> set[str]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n'
    ).encode()
    ips: set[str] = set()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(timeout)
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
        s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                break
            if b"Samsung" in data or b"samsung" in data:
                ips.add(addr[0])
    finally:
        s.close()
    return ips


@mcp.tool()
def tv_discover(ip_hint: Optional[str] = None) -> str:
    """Find Samsung TVs on the local network.

    Uses SSDP, then confirms each candidate via the TV's own /api/v2/ endpoint.
    Pass ip_hint (e.g. "192.168.1.50") to check one address directly, which
    is faster and works when multicast is blocked. Returns JSON list.
    """
    found: list[dict[str, Any]] = []
    if ip_hint:
        info = _info(ip_hint)
        if info:
            found.append(info)
    else:
        for ip in sorted(_ssdp()):
            info = _info(ip)
            if info:
                found.append(info)
    if not found:
        return json.dumps(
            {
                "tvs": [],
                "hint": "No TV answered. Is it on and on the same Wi-Fi? "
                "Try tv_discover with ip_hint=<the TV's IP from your router>.",
            }
        )
    return json.dumps({"tvs": found}, indent=2)


# ---------------------------------------------------------------------------
# pairing & config
# ---------------------------------------------------------------------------


@mcp.tool()
def tv_pair(ip: str, name: Optional[str] = None, make_default: bool = True) -> str:
    """Pair with a Samsung TV for the first time and save it.

    Tell the user: a prompt may appear on the TV asking to allow "ClaudeRemote";
    they should press Allow with the remote within 60 seconds. On many TVs the
    token is issued silently with no prompt.

    name: short label to refer to this TV later (defaults to the TV's own name).
    """
    info = _info(ip, timeout=4)
    if not info:
        return f"No Samsung TV answered at {ip}:8001. Check the IP and that the TV is on."
    key = name or (info.get("name") or f"tv-{ip}").replace(" ", "-").lower()
    ws = SamsungTVWS(host=ip, port=8002, name=CLIENT_NAME, timeout=60)
    try:
        ws.open()
    except Exception as e:  # noqa: BLE001
        return (
            f"Pairing failed: {type(e).__name__}: {e}. On the TV check "
            "Settings > General > External Device Manager > Device Connection Manager: "
            "Access Notification = First Time Only, and that ClaudeRemote is not Denied."
        )
    token = ws.token
    ws.close()
    if not token:
        return "Connected but the TV gave no token. Set the TV to the home screen and try again."
    cfg = _load()
    cfg["tvs"][key] = {
        "ip": ip,
        "mac": info.get("wifiMac"),
        "model": info.get("model"),
        "token": token,
    }
    if make_default or not cfg.get("default"):
        cfg["default"] = key
    _save(cfg)
    return f"Paired '{key}' ({info.get('model')} at {ip}). Token saved to {CONFIG_PATH}."


@mcp.tool()
def tv_list() -> str:
    """List paired TVs and which one is the default."""
    cfg = _load()
    return json.dumps(
        {
            "default": cfg.get("default"),
            "tvs": {k: {"ip": v["ip"], "model": v.get("model")} for k, v in cfg["tvs"].items()},
        },
        indent=2,
    )


@mcp.tool()
def tv_forget(name: str) -> str:
    """Remove a paired TV and its token from the config."""
    cfg = _load()
    if name not in cfg["tvs"]:
        return f"No TV named '{name}'."
    del cfg["tvs"][name]
    if cfg.get("default") == name:
        cfg["default"] = next(iter(cfg["tvs"]), None)
    _save(cfg)
    return f"Forgot '{name}'. The TV may still list ClaudeRemote under Device Connection Manager."


# ---------------------------------------------------------------------------
# control
# ---------------------------------------------------------------------------


@mcp.tool()
def tv_status(name: Optional[str] = None) -> str:
    """Power state, model and reachability of a paired TV (default TV if name omitted)."""
    key, tv = _tv_entry(name)
    info = _info(tv["ip"], timeout=3)
    if not info:
        return json.dumps({"tv": key, "ip": tv["ip"], "reachable": False, "power": "off or asleep"})
    info["tv"] = key
    info["reachable"] = True
    return json.dumps(info, indent=2)


@mcp.tool()
def tv_key(key: str, repeat: int = 1, delay_ms: int = 350, name: Optional[str] = None) -> str:
    """Press a remote key on the TV.

    key: Samsung key code, e.g. KEY_HOME, KEY_MENU, KEY_RETURN, KEY_ENTER,
    KEY_UP/DOWN/LEFT/RIGHT, KEY_VOLUP, KEY_VOLDOWN, KEY_MUTE, KEY_CHUP, KEY_CHDOWN,
    KEY_0..KEY_9, KEY_PLAY, KEY_PAUSE, KEY_STOP, KEY_REWIND, KEY_FF, KEY_SOURCE,
    KEY_GUIDE, KEY_INFO, KEY_EXIT, KEY_POWER. Bare names without KEY_ are accepted.
    repeat: press it this many times, with delay_ms between presses.
    """
    code = key.upper()
    if not code.startswith("KEY_"):
        code = "KEY_" + code
    tvname, ws = _connect(name)
    try:
        for i in range(max(1, repeat)):
            ws.send_key(code)
            if i < repeat - 1:
                time.sleep(delay_ms / 1000)
    finally:
        ws.close()
    return f"Sent {code} x{repeat} to {tvname}."


@mcp.tool()
def tv_keys(sequence: str, delay_ms: int = 500, name: Optional[str] = None) -> str:
    """Press a sequence of keys. sequence is comma or space separated, e.g.
    "HOME, DOWN, DOWN, ENTER". Use "WAIT:1500" to pause for 1.5 s mid-sequence.
    """
    parts = [p.strip() for p in sequence.replace(",", " ").split() if p.strip()]
    tvname, ws = _connect(name)
    sent: list[str] = []
    try:
        for p in parts:
            if p.upper().startswith("WAIT:"):
                time.sleep(int(p.split(":", 1)[1]) / 1000)
                continue
            code = p.upper()
            if not code.startswith("KEY_"):
                code = "KEY_" + code
            ws.send_key(code)
            sent.append(code)
            time.sleep(delay_ms / 1000)
    finally:
        ws.close()
    return f"Sent to {tvname}: {' '.join(sent)}"


# Well-known Tizen app IDs. Others can be launched by numeric ID directly.
APP_IDS = {
    "netflix": "11101200001",
    "youtube": "111299001912",
    "prime video": "3201512006785",
    "prime": "3201512006785",
    "disney+": "3201901017640",
    "disney": "3201901017640",
    "spotify": "3201606009684",
    "plex": "3201512006963",
    "apple tv": "3201807016597",
    "hbo max": "3201601007230",
    "max": "3201601007230",
    "twitch": "3202203026841",
    "jellyfin": "3202011022316",
    "browser": "org.tizen.browser",
    "internet": "org.tizen.browser",
    "samsung tv plus": "3201504001965",
    "tv plus": "3201504001965",
}


@mcp.tool()
def tv_launch_app(app: str, name: Optional[str] = None) -> str:
    """Launch an app on the TV by name (netflix, youtube, prime video, disney+,
    spotify, plex, apple tv, max, twitch, browser ...) or by Tizen app ID.
    """
    app_id = APP_IDS.get(app.strip().lower(), app.strip())
    key, tv = _tv_entry(name)
    r = requests.post(f"http://{tv['ip']}:8001/api/v2/applications/{app_id}", timeout=5)
    if r.status_code == 200:
        return f"Launched {app} ({app_id}) on {key}."
    return f"TV answered {r.status_code} for {app}: {r.text[:200]}"


@mcp.tool()
def tv_apps(name: Optional[str] = None) -> str:
    """List installed apps reported by the TV (name and app_id)."""
    _, ws = _connect(name)
    try:
        apps = ws.app_list() or []
    finally:
        ws.close()
    return json.dumps([{"name": a.get("name"), "app_id": a.get("appId")} for a in apps], indent=2)


@mcp.tool()
def tv_text(text: str, name: Optional[str] = None) -> str:
    """Type text into whatever text field is focused on the TV (search boxes etc.)."""
    tvname, ws = _connect(name)
    try:
        ws.send_text(text)
    finally:
        ws.close()
    return f"Typed {len(text)} characters on {tvname}."


def _wol(mac: str) -> None:
    clean = mac.replace(":", "").replace("-", "")
    payload = b"\xff" * 6 + bytes.fromhex(clean) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(payload, ("255.255.255.255", 9))
    s.close()


@mcp.tool()
def tv_power(state: str, name: Optional[str] = None) -> str:
    """Turn the TV on (Wake-on-LAN, needs the TV's Power On with Mobile setting)
    or off (KEY_POWER). state: "on" | "off" | "toggle".
    Ask the user before turning a TV off.
    """
    key, tv = _tv_entry(name)
    st = state.lower()
    if st == "on":
        if not tv.get("mac"):
            return "No MAC stored for this TV; re-pair to capture it."
        for _ in range(3):
            _wol(tv["mac"])
            time.sleep(0.3)
        return f"Sent Wake-on-LAN to {key}. It takes 5-15 s to boot."
    if st in ("off", "toggle"):
        tvname, ws = _connect(name)
        try:
            ws.send_key("KEY_POWER")
        finally:
            ws.close()
        return f"Sent KEY_POWER to {tvname}."
    return "state must be on, off or toggle."


# ---------------------------------------------------------------------------
# macros
# ---------------------------------------------------------------------------

MACROS: dict[str, dict[str, Any]] = {
    "open_settings": {
        "doc": "Open the All Settings page.",
        "keys": "HOME WAIT:1500 MENU WAIT:1500",
    },
    "open_network_status": {
        "doc": "Settings > General > Network > Network Status (Q74A / Tizen 6 layout). "
        "Verify on screen; menu order differs by model and firmware.",
        "keys": "MENU WAIT:1500 DOWN DOWN DOWN ENTER WAIT:800 DOWN DOWN ENTER WAIT:800 ENTER",
    },
    "home": {"doc": "Go to the home screen.", "keys": "HOME"},
    "back_out": {"doc": "Press Return five times to escape any menu.", "keys": "RETURN RETURN RETURN RETURN RETURN"},
    "mute_toggle": {"doc": "Toggle mute.", "keys": "MUTE"},
}


@mcp.tool()
def tv_macro(macro: str, name: Optional[str] = None) -> str:
    """Run a named key sequence. Call with macro="list" to see them.

    Menu macros are best-effort: Samsung menu layouts shift between models and
    firmware, so confirm the result on screen before pressing more keys.
    DNS and privacy settings cannot be set over this API; the user must type the
    values on the TV. The macros only get them to the right page.
    """
    if macro == "list":
        return json.dumps({k: v["doc"] for k, v in MACROS.items()}, indent=2)
    if macro not in MACROS:
        return f"Unknown macro '{macro}'. Known: {', '.join(MACROS)}"
    return tv_keys(MACROS[macro]["keys"], name=name)


if __name__ == "__main__":
    mcp.run()
