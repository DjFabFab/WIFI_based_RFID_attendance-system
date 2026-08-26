#!/usr/bin/env python3
"""Presency Divera kiosk switcher.

Polls the Divera247 alarm API and controls the kiosk Chromium tab via the
Chrome DevTools Protocol (CDP) HTTP endpoints:

* while no alarm is active the kiosk shows the local Django attendance app,
* when Divera reports an active (not closed) alarm a new tab with the Divera
  dashboard is opened and kept visible for ALARM_VISIBLE_SECONDS (20 min by
  default) after the initial alarm (a newer alarm id extends the window),
* when the window expires the Divera tab is closed and the Django tab is
  brought to the front again.

API contract (verified live): ``GET /api/v2/pull/all?accesskey=...`` returns
``{"success": true, "data": {"alarm": {"items": [...], "new": n, "sorting": [...], "ts": ...}}}``
where ``items`` is a list (or dict keyed by id) of alarm objects; each alarm
has a monotonic integer ``id`` and a boolean ``closed`` field. An alarm counts
as ACTIVE when its ``closed`` value is falsy.

Chromium must be started with ``--remote-debugging-port=9222`` (see
``deployment/kiosk-browser.sh``). Only stdlib + ``requests`` are used.
"""

import logging
import os
import sys
import time
import urllib.parse

import requests

log = logging.getLogger("divera_kiosk")

DEFAULTS = {
    "divera_api_url": "https://app.divera247.com/api/v2/pull/all",
    "divera_page_url": "https://www.divera247.com/",
    "kiosk_home_url": "http://127.0.0.1:8000/",
    "cdp_base": "http://127.0.0.1:9222",
    "poll_seconds": 15,
    "alarm_visible_seconds": 1200,
}


def _env_int(environ, name, default):
    """Read an integer setting, falling back to ``default`` on any error."""
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        log.warning("Invalid integer for %s (%r), using default %s", name, raw, default)
        return default


def load_config(environ=None):
    """Read all settings from the environment (systemd EnvironmentFile)."""
    env = environ if environ is not None else os.environ
    return {
        "access_key": (env.get("DIVERA_ACCESS_KEY") or "").strip(),
        "divera_api_url": env.get("DIVERA_API_URL", DEFAULTS["divera_api_url"]),
        "divera_page_url": env.get("DIVERA_PAGE_URL", DEFAULTS["divera_page_url"]),
        "kiosk_home_url": env.get("KIOSK_HOME_URL", DEFAULTS["kiosk_home_url"]),
        "cdp_base": env.get("CDP_BASE", DEFAULTS["cdp_base"]),
        "poll_seconds": _env_int(env, "POLL_SECONDS", DEFAULTS["poll_seconds"]),
        "alarm_visible_seconds": _env_int(
            env, "ALARM_VISIBLE_SECONDS", DEFAULTS["alarm_visible_seconds"]
        ),
    }


def parse_latest_alarm(payload):
    """Extract ``(active, newest_id)`` from a Divera ``pull/all`` payload.

    The envelope is ``{"success": true, "data": {"alarm": {"items": [...]}}}``.
    ``data.alarm.items`` is a list of alarm objects (the pull API may also
    return a dict keyed by alarm id -- both are accepted). An alarm counts as
    ACTIVE when its ``"closed"`` value is falsy. ``newest_id`` is the highest
    alarm ``id`` seen (used to detect newer alarms and extend the window), or
    ``None`` when no alarms exist. Missing/malformed keys never raise --
    anything unusable is treated as "no alarm".
    """
    if not isinstance(payload, dict):
        return False, None
    if not payload.get("success"):
        return False, None
    data = payload.get("data")
    if not isinstance(data, dict):
        return False, None
    alarm = data.get("alarm")
    if not isinstance(alarm, dict):
        return False, None
    items = alarm.get("items")
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        return False, None
    alarms = [a for a in items if isinstance(a, dict)]
    active = any(not a.get("closed") for a in alarms)
    ids = [a.get("id") for a in alarms if isinstance(a.get("id"), int)]
    newest_id = max(ids) if ids else None
    return active, newest_id


def fetch_alarm(cfg):
    """Poll the Divera API; any error is logged and treated as "no alarm"."""
    params = {
        "accesskey": cfg["access_key"],
        "access-key": cfg["access_key"],
    }
    try:
        resp = requests.get(cfg["divera_api_url"], params=params, timeout=10)
        if resp.status_code != 200:
            log.warning("Divera API returned HTTP %s", resp.status_code)
            return False, None
        try:
            payload = resp.json()
        except ValueError:
            log.warning("Divera API returned invalid JSON")
            return False, None
        return parse_latest_alarm(payload)
    except requests.RequestException as exc:
        log.warning("Divera API request failed: %s", exc)
        return False, None


def cdp_list_targets(cfg):
    """Return the CDP target list; empty list on any failure."""
    try:
        resp = requests.get(cfg["cdp_base"] + "/json/list", timeout=5)
        resp.raise_for_status()
        targets = resp.json()
        return targets if isinstance(targets, list) else []
    except (requests.RequestException, ValueError) as exc:
        log.warning("CDP /json/list failed: %s", exc)
        return []


def find_home_target(targets, home_url):
    """Find the kiosk home tab (page whose url contains the home host)."""
    try:
        host = urllib.parse.urlsplit(home_url).netloc or home_url
    except ValueError:
        host = home_url
    for target in targets:
        if (
            isinstance(target, dict)
            and target.get("type") == "page"
            and host in (target.get("url") or "")
        ):
            return target
    return None


def cdp_open_tab(cfg, url):
    """Open ``url`` in a new tab; return its target id or None."""
    try:
        resp = requests.put(
            cfg["cdp_base"] + "/json/new?" + urllib.parse.quote(url, safe=""),
            timeout=5,
        )
        resp.raise_for_status()
        target = resp.json()
        return target.get("id") if isinstance(target, dict) else None
    except (requests.RequestException, ValueError, AttributeError) as exc:
        log.warning("CDP /json/new failed: %s", exc)
        return None


def cdp_close_tab(cfg, target_id):
    """Close the tab with the given target id."""
    if not target_id:
        return False
    try:
        resp = requests.put(cfg["cdp_base"] + "/json/close/" + target_id, timeout=5)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("CDP /json/close failed: %s", exc)
        return False


def cdp_activate_tab(cfg, target_id):
    """Bring the tab with the given target id to the front."""
    if not target_id:
        return False
    try:
        resp = requests.put(cfg["cdp_base"] + "/json/activate/" + target_id, timeout=5)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("CDP /json/activate failed: %s", exc)
        return False


def run(cfg):
    """Main state machine loop: home -> divera (until deadline) -> home."""
    state = "home"
    deadline = 0.0
    last_id = None
    divera_target_id = None

    while True:
        now = time.time()
        active, newest_id = fetch_alarm(cfg)

        if state == "home":
            if active:
                log.info("Active alarm detected, opening Divera tab")
                divera_target_id = cdp_open_tab(cfg, cfg["divera_page_url"])
                if divera_target_id is not None:
                    deadline = now + cfg["alarm_visible_seconds"]
                    last_id = newest_id
                    state = "divera"
                    log.info(
                        "Switched to Divera; visible for %.0f seconds",
                        cfg["alarm_visible_seconds"],
                    )
        else:  # state == "divera"
            if (
                newest_id is not None
                and last_id is not None
                and newest_id > last_id
            ):
                last_id = newest_id
                deadline = now + cfg["alarm_visible_seconds"]
                log.info("New alarm detected; extended Divera window")
            if now >= deadline:
                cdp_close_tab(cfg, divera_target_id)
                divera_target_id = None
                home_target = find_home_target(
                    cdp_list_targets(cfg), cfg["kiosk_home_url"]
                )
                if home_target is not None:
                    cdp_activate_tab(cfg, home_target["id"])
                    log.info("Returned to home tab")
                else:
                    log.warning("Home tab not found; skipping activation")
                state = "home"

        time.sleep(max(cfg["poll_seconds"], 1))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    cfg = load_config()
    if not cfg["access_key"]:
        log.error(
            "DIVERA_ACCESS_KEY is not set; refusing to start "
            "(exiting 0 so systemd Restart=on-failure does not restart-loop)"
        )
        sys.exit(0)
    log.info(
        "Starting: polling %s every %ss, Divera visible %ss, CDP at %s",
        cfg["divera_api_url"],
        cfg["poll_seconds"],
        cfg["alarm_visible_seconds"],
        cfg["cdp_base"],
    )
    run(cfg)


if __name__ == "__main__":
    main()
